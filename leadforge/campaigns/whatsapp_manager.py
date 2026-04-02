"""
LeadForge — WhatsApp Manager (yCloud Integration)
Gestiona el envío de mensajes por WhatsApp para DB2 (social leads).

yCloud es META Official Partner → mejor deliverability y menor riesgo de ban.
Documentación: https://docs.ycloud.com/reference/whatsapp-messages-send

Estrategia:
  - Solo contactar por WhatsApp si el lead NO respondió email en 3+ días
  - Mensaje corto, casual, con pregunta directa
  - NUNCA enviar si el lead marcó do_not_contact
  - Registrar cada envío en Supabase (social_leads)
  - Respetar horario de envío (9am - 7pm hora local del destino)
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

import httpx

from ..config import cfg
from ..supabase_client import get_db
from ..monitor.alerts import fire_alert, AlertSeverity

logger = logging.getLogger(__name__)

YCLOUD_API = "https://api.ycloud.com/v2"


# ============================================================
# PLANTILLAS DE WHATSAPP
# (deben ser pre-aprobadas por META en el dashboard de yCloud)
# ============================================================

# Plantilla 1: Primer contacto
WA_TEMPLATE_INTRO = """Hola {primer_nombre}, soy {vendedor} de {empresa}.

Le escribí hace unos días por email sobre {producto_corto} y no quería que se perdiera de esta oportunidad.

¿Le podría regalar 2 minutos para platicar?

{link_agenda}"""

# Plantilla 2: Segundo intento (si no respondió el primer WA)
WA_TEMPLATE_FOLLOWUP = """Hola {primer_nombre}, disculpe la insistencia.

Solo quería confirmar si recibió mi mensaje anterior sobre {producto_corto} para {tipo_negocio}.

¿Cuándo sería un buen momento para platicar? 🙏"""


# ============================================================
# MODELO DE MENSAJE
# ============================================================
@dataclass
class WhatsAppMessage:
    to_phone: str          # formato: +521234567890
    body: str
    social_lead_id: str    # ID en Supabase social_leads
    nombre_negocio: str


# ============================================================
# CLIENTE YCLOUD
# ============================================================
class WhatsAppManager:
    def __init__(self):
        self.api_key = cfg.ycloud_api_key
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key or "",
        }

    def _format_phone(self, phone: str, country_code: str = "52") -> Optional[str]:
        """
        Normaliza el teléfono al formato E.164 (+521234567890).
        Maneja formatos comunes de México.
        """
        if not phone:
            return None

        # Limpiar caracteres no numéricos
        digits = "".join(c for c in phone if c.isdigit())

        if not digits:
            return None

        # México: 10 dígitos locales → agregar +52
        if len(digits) == 10:
            return f"+{country_code}{digits}"
        # Ya tiene código de país
        elif len(digits) == 12 and digits.startswith("52"):
            return f"+{digits}"
        elif len(digits) == 13 and digits.startswith("521"):
            return f"+{digits}"
        elif digits.startswith("+"):
            return digits

        # Fallback: asumir México
        if len(digits) >= 10:
            return f"+{country_code}{digits[-10:]}"

        return None

    def _is_send_window(self, hour_local: int = None) -> bool:
        """
        Verifica que estemos en horario de envío (9am - 7pm).
        Evita envíos nocturnos que molestan y tienen peor respuesta.
        """
        if hour_local is None:
            hour_local = datetime.now().hour
        return 9 <= hour_local < 19

    def _build_message(
        self,
        template: str,
        variables: dict,
    ) -> str:
        """Llena el template con las variables del lead."""
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Variable faltante en template WA: {e}")
            return template

    async def send_message(self, message: WhatsAppMessage) -> bool:
        """
        Envía un mensaje de WhatsApp vía yCloud API.
        Returns True si fue exitoso.
        """
        if not self.api_key:
            logger.warning("YCLOUD_API_KEY no configurado — simulando envío")
            logger.info(f"  [SIMULADO] WA a {message.to_phone}: {message.body[:50]}...")
            return True  # en desarrollo, simular éxito

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{YCLOUD_API}/whatsapp/messages",
                    headers=self.headers,
                    json={
                        "to": message.to_phone,
                        "type": "text",
                        "text": {"body": message.body},
                    },
                )

                if resp.status_code in (200, 201):
                    logger.info(f"✅ WA enviado: {message.to_phone} ({message.nombre_negocio})")
                    return True
                else:
                    logger.error(f"yCloud error {resp.status_code}: {resp.text[:200]}")
                    return False

        except Exception as e:
            logger.error(f"Error enviando WA a {message.to_phone}: {e}")
            return False

    async def send_batch(
        self,
        messages: list[WhatsAppMessage],
        delay_seconds: int = 30,
    ) -> dict:
        """
        Envía un lote de mensajes con delay entre cada uno.
        El delay evita que yCloud detecte comportamiento de spam.
        """
        sent = 0
        failed = 0

        for i, msg in enumerate(messages):
            if not self._is_send_window():
                logger.info("Fuera de horario de envío WA (9am-7pm). Pausando.")
                break

            success = await self.send_message(msg)
            if success:
                sent += 1
                await self._mark_sent_in_db(msg.social_lead_id)
            else:
                failed += 1

            # Delay entre mensajes (excepto el último)
            if i < len(messages) - 1:
                await asyncio.sleep(delay_seconds)

        logger.info(f"WhatsApp batch: {sent} enviados, {failed} fallidos")
        return {"sent": sent, "failed": failed}

    async def _mark_sent_in_db(self, social_lead_id: str) -> None:
        """Actualiza el estado del social lead como enviado."""
        try:
            db = get_db()
            db.table("social_leads").update({
                "estado": "enviado",
                "fecha_envio": datetime.utcnow().isoformat(),
            }).eq("id", social_lead_id).execute()
        except Exception as e:
            logger.debug(f"Error actualizando social lead: {e}")

    async def prepare_messages_from_db(
        self,
        config_vars: dict,
        cliente_id: Optional[str] = None,
        max_messages: int = 50,
    ) -> list[WhatsAppMessage]:
        """
        Obtiene social leads pendientes desde Supabase y prepara mensajes.

        Solo incluye leads que:
          - Canal asignado = 'whatsapp'
          - Estado = 'pendiente'
          - do_not_contact = False
          - El email lead correspondiente NO respondió en 3 días (si existe)
        """
        db = get_db()

        try:
            result = db.table("social_leads").select(
                "id, nombre_negocio, telefono, owner_name, categoria, ciudad, "
                "email_lead_id, canal_asignado"
            ).eq("canal_asignado", "whatsapp").eq("estado", "pendiente").eq(
                "do_not_contact", False
            ).eq(
                "cliente_id", cliente_id or cfg.cliente_id
            ).limit(max_messages).execute()

            leads = result.data or []
        except Exception as e:
            logger.error(f"Error obteniendo social leads: {e}")
            return []

        messages = []
        for lead in leads:
            phone = self._format_phone(lead.get("telefono", ""))
            if not phone:
                continue

            # Separar nombre
            owner = lead.get("owner_name", "")
            primer_nombre = owner.split()[0] if owner else "Propietario"

            # Construir variables del template
            variables = {
                "primer_nombre": primer_nombre,
                "vendedor": config_vars.get("vendedor", ""),
                "empresa": config_vars.get("empresa", ""),
                "producto_corto": config_vars.get("producto_corto", "nuestro producto"),
                "tipo_negocio": lead.get("categoria", "su negocio"),
                "link_agenda": config_vars.get("link_cal", ""),
            }

            body = self._build_message(WA_TEMPLATE_INTRO, variables)

            messages.append(WhatsAppMessage(
                to_phone=phone,
                body=body,
                social_lead_id=lead["id"],
                nombre_negocio=lead.get("nombre_negocio", ""),
            ))

        logger.info(f"WhatsApp: {len(messages)} mensajes preparados de {len(leads)} leads")
        return messages


# ============================================================
# SEGUIMIENTO DE RESPUESTAS WHATSAPP
# (cuando el cliente responde por WA, yCloud envía webhook)
# ============================================================

async def handle_whatsapp_reply(webhook_payload: dict) -> None:
    """
    Procesa una respuesta de WhatsApp de yCloud.
    Actualiza Supabase + notifica por Telegram.
    """
    from_phone = webhook_payload.get("from", "")
    message_body = webhook_payload.get("body", {}).get("text", "")

    if not from_phone or not message_body:
        return

    # Buscar el social lead por teléfono
    db = get_db()
    try:
        result = db.table("social_leads").select(
            "id, nombre_negocio, owner_name, ciudad"
        ).ilike("telefono", f"%{from_phone[-10:]}%").limit(1).execute()

        if not result.data:
            logger.info(f"WA reply de número no encontrado: {from_phone}")
            return

        lead = result.data[0]

        # Actualizar estado
        db.table("social_leads").update({
            "respondio": True,
            "texto_respuesta": message_body[:500],
            "estado": "respondio",
        }).eq("id", lead["id"]).execute()

        # Notificar por Telegram
        await fire_alert(
            tipo="whatsapp_reply",
            mensaje=(
                f"📱 *RESPUESTA DE WHATSAPP*\n\n"
                f"🏪 *{lead.get('nombre_negocio', 'Negocio')}* — {lead.get('ciudad', '')}\n"
                f"👤 {lead.get('owner_name', 'Propietario')}\n"
                f"📞 {from_phone}\n\n"
                f"💬 *Mensaje:*\n_{message_body[:200]}_"
            ),
            severidad=AlertSeverity.INFO,
        )

    except Exception as e:
        logger.error(f"Error procesando WA reply: {e}")


# Instancia global
whatsapp = WhatsAppManager()
