"""
LeadForge — Webhook de Respuestas de Instantly.ai
Recibe eventos de Instantly.ai (replies, bounces, unsubscribes).
Analiza cada respuesta con Claude → Notifica por Telegram.

Expone:
  POST /webhook/instantly        ← Todos los eventos de Instantly
  GET  /webhook/health           ← Health check del servidor webhook
  GET  /webhook/test-telegram    ← Prueba que Telegram funcione

Puerto: 8001 (configurable en .env)
"""
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Optional

import anthropic
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from ..config import cfg
from ..supabase_client import get_db
from .telegram_bot import send_reply_notification
from .alerts import fire_alert, AlertSeverity

logger = logging.getLogger(__name__)

app = FastAPI(title="LeadForge Webhook Server", version="1.0.0")

# ============================================================
# SEGURIDAD — Verificación de firma HMAC
# ============================================================

def verify_instantly_signature(
    payload: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """
    Verifica que el webhook venga realmente de Instantly.ai.
    Previene ataques de terceros que intenten disparar eventos falsos.
    """
    if not signature_header or not secret:
        # Si no hay secret configurado, aceptar (modo desarrollo)
        if not secret:
            logger.warning("INSTANTLY_WEBHOOK_SECRET no configurado — aceptando sin firma")
            return True
        return False

    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Comparación segura (constante de tiempo, evita timing attacks)
    return hmac.compare_digest(expected, signature_header)


# ============================================================
# ANÁLISIS DE REPLIES CON CLAUDE
# ============================================================

async def analyze_reply_with_claude(
    reply_text: str,
    lead_data: dict,
    product_description: str = "",
) -> dict:
    """
    Claude analiza la respuesta del lead y genera:
    - Sentimiento (positive/neutral/negative/question)
    - Intención (requesting_info, scheduling, objection, spam, unsubscribe)
    - Urgencia (high/medium/low)
    - Acción recomendada
    - Respuesta sugerida personalizada
    """
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    nombre = lead_data.get("owner_name") or "el contacto"
    negocio = lead_data.get("nombre_negocio", "el negocio")
    categoria = lead_data.get("categoria", "")

    prompt = f"""Analiza esta respuesta a un email de cold outreach B2B.

CONTEXTO:
- Negocio: {negocio} ({categoria})
- Contacto: {nombre}
- Email enviado sobre: {product_description or "nuestro producto/servicio"}

RESPUESTA DEL LEAD:
"{reply_text}"

Proporciona:
1. sentiment: positive | neutral | negative | question
2. intent: requesting_info | scheduling | objection | spam | unsubscribe | out_of_office | other
3. urgency: high | medium | low
4. suggested_action: texto breve de qué hacer (máx 20 palabras)
5. suggested_response: respuesta profesional en español (máx 80 palabras), personalizada para {nombre} de {negocio}

Responde en JSON válido."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",   # haiku: rápido y barato para análisis
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        import json, re
        text = message.content[0].text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

    except Exception as e:
        logger.error(f"Error en análisis Claude: {e}")

    # Fallback si Claude falla
    return {
        "sentiment": "unknown",
        "intent": "other",
        "urgency": "medium",
        "suggested_action": "Revisar y responder manualmente",
        "suggested_response": f"Hola {nombre}, muchas gracias por tu respuesta. ¿Cuándo podrías tener una llamada de 15 minutos para platicar?",
    }


# ============================================================
# MANEJO DE EVENTOS DE INSTANTLY.AI
# ============================================================

async def handle_email_replied(event_data: dict) -> None:
    """
    Procesa un evento de respuesta de email.
    - Busca el lead en leads_master
    - Analiza con Claude
    - Notifica por Telegram
    - Actualiza etapa en Supabase
    """
    lead_email = (
        event_data.get("from_email") or
        event_data.get("lead", {}).get("email", "")
    )
    reply_text = (
        event_data.get("body_text") or
        event_data.get("email", {}).get("body", "") or
        ""
    ).strip()

    if not lead_email:
        logger.warning("Reply sin email del remitente — ignorando")
        return

    # Buscar lead en leads_master (tabla activa)
    lead_data = {}
    cliente_telegram_id = None
    try:
        db = get_db()
        result = db.table("leads_master").select(
            "id, nombre_negocio, email, owner_name, ciudad, lead_score, "
            "categoria, cliente_id, etapa"
        ).eq("email", lead_email.lower()).limit(1).execute()

        if result.data:
            lead_data = result.data[0]

            # Obtener telegram del cliente si existe tabla clientes
            try:
                cliente_result = db.table("clientes").select("telegram_chat_id").eq(
                    "id", lead_data["cliente_id"]
                ).limit(1).execute()
                if cliente_result.data:
                    cliente_telegram_id = str(
                        cliente_result.data[0].get("telegram_chat_id", "") or ""
                    )
            except Exception:
                pass  # tabla clientes aún no existe → ok

            # Actualizar estado en leads_master
            db.table("leads_master").update({
                "respondio_email": True,
                "fecha_respuesta_email": datetime.utcnow().isoformat(),
                "texto_respuesta_email": reply_text[:500] if reply_text else None,
                "etapa": "respondio",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", lead_data["id"]).execute()
            logger.info(f"✅ etapa → respondio: {lead_email}")

    except Exception as e:
        logger.error(f"Error buscando lead {lead_email}: {e}")

    # Analizar con Claude
    analysis = await analyze_reply_with_claude(reply_text, lead_data)

    # Si es unsubscribe → marcar como do_not_contact
    if analysis.get("intent") == "unsubscribe":
        try:
            db = get_db()
            db.table("leads_master").update({
                "do_not_contact": True,
                "motivo_baja": "Unsubscribe — solicitó no contactar",
                "etapa": "descartado",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("email", lead_email.lower()).execute()
            logger.info(f"Unsubscribe procesado: {lead_email}")
        except Exception as e:
            logger.error(f"Error marcando unsubscribe: {e}")

    # Notificar por Telegram
    await send_reply_notification(
        lead_data=lead_data,
        reply_text=reply_text,
        analysis=analysis,
        suggested_response=analysis.get("suggested_response", ""),
        cliente_telegram_id=cliente_telegram_id or None,
    )

    logger.info(
        f"Reply procesado: {lead_email} | "
        f"sentiment={analysis.get('sentiment')} | "
        f"intent={analysis.get('intent')}"
    )


async def handle_email_bounced(event_data: dict) -> None:
    """
    Procesa un bounce. Actualiza el estado del lead en leads_master.
    """
    lead_email = event_data.get("lead", {}).get("email", "")
    campaign_name = event_data.get("campaign", {}).get("name", "Desconocida")

    if not lead_email:
        return

    # Marcar como bounced en leads_master
    try:
        db = get_db()
        db.table("leads_master").update({
            "email_status": "bounced",
            "do_not_contact": True,
            "motivo_baja": "Email bounced",
            "etapa": "descartado",
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("email", lead_email.lower()).execute()
        logger.info(f"Bounce registrado: {lead_email}")
    except Exception as e:
        logger.error(f"Error marcando bounce: {e}")

    # Alerta si hay muchos bounces en poco tiempo
    await fire_alert(
        tipo="email_bounce",
        mensaje=(
            f"📉 *Email bounce detectado*\n"
            f"Email: `{lead_email}`\n"
            f"Campaña: {campaign_name}\n"
            f"Si hay muchos bounces → riesgo para el dominio."
        ),
        severidad=AlertSeverity.INFO,
    )


async def handle_email_opened(event_data: dict) -> None:
    """Registra apertura de email en leads_master."""
    lead_email = event_data.get("lead", {}).get("email", "")
    if not lead_email:
        return
    logger.info(f"Email abierto por: {lead_email}")
    try:
        db = get_db()
        # Incrementar contador y marcar abierto
        result = db.table("leads_master").select(
            "id, veces_abierto, etapa"
        ).eq("email", lead_email.lower()).limit(1).execute()

        if result.data:
            lead = result.data[0]
            veces = (lead.get("veces_abierto") or 0) + 1
            update = {
                "email_abierto": True,
                "veces_abierto": veces,
                "updated_at": datetime.utcnow().isoformat(),
            }
            # Solo actualizar etapa si aún está en "contactado"
            if lead.get("etapa") == "contactado":
                update["etapa"] = "abierto"
                update["fecha_apertura"] = datetime.utcnow().isoformat()
            db.table("leads_master").update(update).eq("id", lead["id"]).execute()
            logger.info(f"✅ etapa → abierto ({veces}x): {lead_email}")
    except Exception as e:
        logger.error(f"Error registrando apertura: {e}")


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/webhook/health")
async def health_check():
    """Verifica que el servidor webhook esté corriendo."""
    return {
        "status": "ok",
        "service": "LeadForge Webhook Server",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/webhook/test-telegram")
async def test_telegram():
    """Envía un mensaje de prueba a Telegram."""
    from .alerts import send_telegram
    ok = await send_telegram(
        "✅ *LeadForge Webhook* — Test exitoso\n"
        "El sistema de notificaciones funciona correctamente."
    )
    return {"telegram_ok": ok}


@app.post("/webhook/instantly")
async def receive_instantly_event(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Endpoint principal para eventos de Instantly.ai.
    Verifica firma HMAC → procesa evento → responde rápido.
    """
    # Leer payload raw para verificar firma
    payload = await request.body()
    signature = request.headers.get("X-Instantly-Signature", "")

    # Verificar firma (seguridad)
    if cfg.instantly_webhook_secret:
        if not verify_instantly_signature(payload, signature, cfg.instantly_webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Parsear JSON
    try:
        import json
        data = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = data.get("event", data.get("type", ""))
    event_data = data.get("data", data)

    logger.info(f"Evento Instantly recibido: {event_type}")

    # Procesar en background (responder a Instantly rápido)
    if event_type in ("email.replied", "reply"):
        background_tasks.add_task(handle_email_replied, event_data)

    elif event_type in ("email.bounced", "bounce"):
        background_tasks.add_task(handle_email_bounced, event_data)

    elif event_type in ("email.opened", "open"):
        background_tasks.add_task(handle_email_opened, event_data)

    elif event_type in ("email.unsubscribed", "unsubscribe"):
        # El análisis de reply detectará el intent=unsubscribe
        background_tasks.add_task(handle_email_replied, event_data)

    else:
        logger.debug(f"Evento no manejado: {event_type}")

    # Respuesta inmediata a Instantly.ai (no esperar el procesamiento)
    return JSONResponse(content={"received": True, "event": event_type})


# ============================================================
# SERVIDOR
# ============================================================

def start_webhook_server(port: int = 8001) -> None:
    """Inicia el servidor webhook en el puerto especificado."""
    logger.info(f"🌐 Iniciando webhook server en puerto {port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
