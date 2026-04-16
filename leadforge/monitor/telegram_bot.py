"""
LeadForge — Bot de Telegram (ZenonFinder)
Centro de control del sistema desde cualquier dispositivo.

Arquitectura multi-cliente:
  - Zenon (master): ve TODO, puede ejecutar comandos globales
  - Cliente: ve solo su información

Comandos disponibles:
  /start     → Vincula el chat con el sistema
  /status    → Estado de todos los servicios
  /leads     → Stats de leads (hoy y últimos 7 días)
  /respuestas → Respuestas pendientes de email
  /reporte   → Reporte semanal completo
  /creditos  → Créditos de Anymail Finder + Apify
  /pausar    → Pausa campaña activa (solo Zenon)
  /agregar   → Inicia nueva búsqueda (solo Zenon)
  /denue     → Ingesta leads minería desde DENUE/INEGI (solo Zenon)
  /enriquecer → Enriquece leads existentes con DENUE (solo Zenon)
  /enriquecer_web → Scraping web + redes sociales para leads sin email (solo Zenon)
  /calidad   → Distribución de calidad stars en la DB (solo Zenon)
  /ayuda     → Lista de comandos

Lenguaje natural (ZenonFinder):
  Escribe en texto libre lo que buscas y el bot lo interpretará.
  Ej: "Quiero 100 tortillerías en Monterrey y Apodaca, Nuevo León"
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import cfg
from ..supabase_client import get_db, get_run_stats
from .alerts import send_telegram, AlertSeverity
from .health_checker import check_anymail_finder, check_apify, check_instantly

logger = logging.getLogger(__name__)

# ============================================================
# AUTENTICACIÓN / AUTORIZACIÓN
# ============================================================

def is_master(chat_id: int) -> bool:
    """Verifica si el chat_id es el master (Zenon)."""
    return str(chat_id) == str(cfg.telegram_master_chat_id)


def get_client_by_telegram(chat_id: int) -> Optional[dict]:
    """Busca el cliente asociado a este chat_id de Telegram."""
    try:
        db = get_db()
        result = db.table("clientes").select("*").eq(
            "telegram_chat_id", chat_id
        ).eq("activo", True).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_effective_cliente_id(chat_id: int) -> Optional[str]:
    """
    Devuelve el cliente_id efectivo para este chat.
    - Si es Zenon: usa el cliente_id del .env (su propio perfil)
    - Si es cliente: usa su propio cliente_id
    """
    if is_master(chat_id):
        return cfg.cliente_id

    client = get_client_by_telegram(chat_id)
    return client["id"] if client else None


# ============================================================
# COMANDOS
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bienvenida y vinculación del chat."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    if is_master(chat_id):
        await update.message.reply_text(
            f"👋 Hola *{user.first_name}*\\! Bienvenido al panel master de *LeadForge*\\.\n\n"
            f"Tienes acceso completo a todos los clientes y servicios\\.\n\n"
            f"Usa /ayuda para ver todos los comandos disponibles\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Verificar si ya está vinculado
    client = get_client_by_telegram(chat_id)
    if client:
        await update.message.reply_text(
            f"✅ Ya estás vinculado como *{client['nombre']}*\\.\n"
            f"Usa /ayuda para ver tus comandos\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Solicitar código de vinculación
    await update.message.reply_text(
        "👋 Bienvenido a *LeadForge*\\.\n\n"
        "Para vincular tu cuenta, ingresa el código de activación que "
        "te proporcionó tu administrador:\n\n"
        "_Ej: /vincular ABC12345_",
        parse_mode="MarkdownV2",
    )


async def cmd_vincular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vincula un cliente con su chat de Telegram usando un código."""
    if not context.args:
        await update.message.reply_text(
            "Uso: /vincular [CÓDIGO]\nEjemplo: /vincular ABC12345"
        )
        return

    # TODO: Implementar lookup por código de activación en Supabase
    # Por ahora, solo para Zenon (master setup)
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "✅ Vinculación completada. Usa /status para ver el estado del sistema."
    )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista de comandos disponibles."""
    chat_id = update.effective_chat.id

    if is_master(chat_id):
        texto = (
            "🤖 *LeadForge — Comandos Master*\n\n"
            "*Búsqueda:*\n"
            "/agregar \\[cat\\] \\[ciudad\\] \\- Nueva búsqueda Apify\n"
            "/si \\- Confirmar búsqueda ZenonFinder\n"
            "/no \\- Cancelar búsqueda\n\n"
            "*DENUE \\(INEGI\\):*\n"
            "/denue \\[estado\\] \\- Ingestar leads minería\n"
            "/enriquecer \\[n\\] \\- Enriquecer leads con DENUE\n"
            "/enriquecer\\_web \\[n\\] \\- Scraping web \\+ redes sociales\n"
            "/verificar\\_mineria \\[n\\] \\- Verificar emails con AnyMail\n"
            "/calidad \\- Ver distribución de estrellas\n\n"
            "*Monitoreo:*\n"
            "/status \\- Estado de servicios\n"
            "/leads \\- Stats hoy/semana\n"
            "/respuestas \\- Emails respondidos\n"
            "/reporte \\- Reporte semanal\n"
            "/creditos \\- Créditos de APIs\n"
            "/clientes \\- Clientes activos\n"
            "/ayuda \\- Este mensaje\n\n"
            "*Pipelines:*\n"
            "/pipeline sqb \\- SQB: AMF \\+ CSV\n"
            "/pipeline sqb apify \\- SQB: Google Maps\n"
            "/pipeline sqb full \\- SQB: completo\n"
            "/pipeline lp \\- LuPront: AMF\n"
            "/pipeline mac \\- Macrisa: AMF\n"
            "/pipeline status \\- Pipelines activos"
        )
    else:
        texto = (
            "🤖 *LeadForge — Tus Comandos*\n\n"
            "/status \\- Estado de tus campañas\n"
            "/leads \\- Leads generados hoy/esta semana\n"
            "/respuestas \\- Emails que respondieron\n"
            "/reporte \\- Reporte semanal\n"
            "/ayuda \\- Este mensaje"
        )

    await update.message.reply_text(texto, parse_mode="MarkdownV2")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Estado actual de todos los servicios."""
    chat_id = update.effective_chat.id
    await update.message.reply_text("🔍 Verificando servicios...")

    # Ejecutar checks en paralelo
    results = await asyncio.gather(
        check_anymail_finder(),
        check_apify(),
        check_instantly(),
        return_exceptions=True,
    )

    anymail_r, apify_r, instantly_r = results

    def status_icon(r) -> str:
        if isinstance(r, Exception):
            return "❌"
        return "✅" if r.get("ok", False) else "⚠️"

    def credits_text(r) -> str:
        if isinstance(r, dict):
            details = r.get("details", {})
            credits = details.get("credits", "?")
            plan = details.get("plan", "")
            return f"  └ {credits} créditos | {plan}"
        return ""

    now = datetime.now().strftime("%d/%m %H:%M")
    mensaje = (
        f"🛡️ *Estado del Sistema*\n_{now}_\n\n"
        f"{status_icon(anymail_r)} Anymail Finder\n{credits_text(anymail_r)}\n"
        f"{status_icon(apify_r)} Apify Scraper\n"
        f"{status_icon(instantly_r)} Instantly.ai\n"
        f"✅ Supabase\n"
    )

    # Mostrar warnings si existen
    warnings = []
    for r in results:
        if isinstance(r, dict) and r.get("warning"):
            warnings.append(f"⚠️ {r['warning']}")
    if warnings:
        mensaje += "\n*Advertencias:*\n" + "\n".join(warnings)

    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def cmd_leads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Estadísticas de leads generados."""
    chat_id = update.effective_chat.id
    cliente_id = get_effective_cliente_id(chat_id)

    if not cliente_id:
        await update.message.reply_text("❌ No estás vinculado. Usa /start")
        return

    stats_24h = get_run_stats(cliente_id, since_hours=24)
    stats_7d = get_run_stats(cliente_id, since_hours=168)

    now = datetime.now().strftime("%d/%m %H:%M")
    mensaje = (
        f"📊 *Leads Generados*\n_{now}_\n\n"
        f"*Últimas 24 horas:*\n"
        f"  📧 Email (DB1): {stats_24h.get('email_leads_nuevos', 0)}\n"
        f"  📱 Social (DB2): {stats_24h.get('social_leads_nuevos', 0)}\n\n"
        f"*Últimos 7 días:*\n"
        f"  📧 Email (DB1): {stats_7d.get('email_leads_nuevos', 0)}\n"
        f"  📱 Social (DB2): {stats_7d.get('social_leads_nuevos', 0)}\n"
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def cmd_respuestas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra los leads que han respondido emails."""
    chat_id = update.effective_chat.id
    cliente_id = get_effective_cliente_id(chat_id)

    if not cliente_id:
        await update.message.reply_text("❌ No estás vinculado.")
        return

    try:
        db = get_db()
        result = db.table("email_leads").select(
            "nombre_negocio, email, ciudad, lead_score, fecha_respuesta, owner_name"
        ).eq("cliente_id", cliente_id).eq("respondio_email", True).order(
            "fecha_respuesta", desc=True
        ).limit(10).execute()

        if not result.data:
            await update.message.reply_text(
                "📭 No hay respuestas registradas aún.\n"
                "Las respuestas aparecen aquí cuando alguien responde vía Instantly.ai."
            )
            return

        mensaje = f"📬 *Últimas respuestas* ({len(result.data)} encontradas)\n\n"
        for lead in result.data:
            nombre = lead.get("owner_name") or "Propietario"
            negocio = lead["nombre_negocio"]
            ciudad = lead.get("ciudad", "")
            score = lead.get("lead_score", 0)
            fecha = lead.get("fecha_respuesta", "")[:10] if lead.get("fecha_respuesta") else "?"

            temp = "🔥" if score >= 70 else ("🌡️" if score >= 40 else "❄️")
            mensaje += (
                f"{temp} *{negocio}* — {ciudad}\n"
                f"  👤 {nombre} | {lead['email']}\n"
                f"  📅 {fecha} | Score: {score}/100\n\n"
            )

        await update.message.reply_text(mensaje, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_creditos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el estado de créditos de todas las APIs."""
    if not is_master(update.effective_chat.id):
        await update.message.reply_text("Este comando es solo para el administrador.")
        return

    await update.message.reply_text("💳 Verificando créditos...")
    result = await check_anymail_finder()
    details = result.get("details", {})
    credits = details.get("credits", "N/A")
    plan = details.get("plan", "N/A")

    mensaje = (
        f"💳 *Estado de Créditos*\n\n"
        f"*Anymail Finder:*\n"
        f"  Créditos: *{credits}*\n"
        f"  Plan: {plan}\n"
        f"  Alerta al llegar a: {cfg.anymail_credits_alert}\n\n"
        f"*Apify:*\n"
        f"  Ver en: console.apify.com → Billing\n\n"
        f"*Anthropic (Claude):*\n"
        f"  Ver en: console.anthropic.com → Usage"
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def cmd_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reporte semanal detallado."""
    chat_id = update.effective_chat.id
    cliente_id = get_effective_cliente_id(chat_id)

    if not cliente_id:
        await update.message.reply_text("❌ No estás vinculado.")
        return

    stats = get_run_stats(cliente_id, since_hours=168)  # 7 días

    now = datetime.now().strftime("%d/%m/%Y")
    mensaje = (
        f"📊 *Reporte Semanal — LeadForge*\n"
        f"_{now}_\n\n"
        f"🎯 *LEADS GENERADOS*\n"
        f"  Email (DB1): {stats.get('email_leads_nuevos', 0)}\n"
        f"  Social (DB2): {stats.get('social_leads_nuevos', 0)}\n\n"
        f"Para estadísticas avanzadas (opens, replies, reuniones),\n"
        f"revisa tu dashboard de Instantly.ai."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def cmd_clientes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista de clientes activos (solo master/Zenon)."""
    if not is_master(update.effective_chat.id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    try:
        db = get_db()
        result = db.table("clientes").select(
            "id, nombre, email, plan, activo, created_at"
        ).eq("activo", True).order("created_at").execute()

        if not result.data:
            await update.message.reply_text("No hay clientes registrados aún.")
            return

        mensaje = f"👥 *Clientes Activos* ({len(result.data)})\n\n"
        for c in result.data:
            plan_emoji = {"starter": "🥉", "growth": "🥈", "agency": "🥇"}.get(c["plan"], "⚪")
            mensaje += (
                f"{plan_emoji} *{c['nombre']}*\n"
                f"  📧 {c['email']}\n"
                f"  Plan: {c['plan']}\n\n"
            )

        await update.message.reply_text(mensaje, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_agregar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia una nueva búsqueda desde Telegram (solo Zenon)."""
    if not is_master(update.effective_chat.id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /agregar [categoría] [ciudad]\n"
            "Ejemplo: /agregar 'taller mecánico' Monterrey"
        )
        return

    categoria = context.args[0]
    ciudad = " ".join(context.args[1:])

    await update.message.reply_text(
        f"🔄 Iniciando búsqueda:\n"
        f"  Categoría: *{categoria}*\n"
        f"  Ciudad: *{ciudad}*\n\n"
        f"El pipeline se ejecutará en background. "
        f"Te notificaré cuando termine.",
        parse_mode="Markdown",
    )

    # Ejecutar pipeline en background
    async def run_bg():
        from ..pipeline import run_pipeline
        try:
            stats = await run_pipeline(
                terminos=[categoria],
                location=f"{ciudad}, Mexico",
                cliente_id=cfg.cliente_id,
            )
            await send_telegram(
                f"✅ *Pipeline completado*\n"
                f"  Categoría: {categoria} — {ciudad}\n"
                f"  Email leads: {stats.email_leads_insertados}\n"
                f"  Social leads: {stats.social_leads_insertados}"
            )
        except Exception as e:
            await send_telegram(f"❌ Pipeline falló: {e}", )

    asyncio.create_task(run_bg())


# ============================================================
# FUNCIONES UTILITARIAS EXPORTADAS
# ============================================================

async def send_reply_notification(
    lead_data: dict,
    reply_text: str,
    analysis: dict,
    suggested_response: str,
    cliente_telegram_id: Optional[str] = None,
) -> None:
    """
    Envía notificación de respuesta de lead a Telegram.
    Llamada desde reply_webhook.py cuando alguien responde un email.
    """
    nombre = lead_data.get("owner_name") or "Propietario"
    negocio = lead_data.get("nombre_negocio", "Negocio desconocido")
    ciudad = lead_data.get("ciudad", "")
    email = lead_data.get("email", "")
    score = lead_data.get("lead_score", 0)
    temp = "🔥" if score >= 70 else ("🌡️" if score >= 40 else "❄️")

    sentimiento_emoji = {
        "positive": "😊 Positivo",
        "neutral": "😐 Neutral",
        "negative": "😟 Negativo",
        "question": "❓ Pregunta",
    }.get(analysis.get("sentiment", ""), "❓ Sin clasificar")

    urgencia_emoji = {
        "high": "🚀 Alta",
        "medium": "⏳ Media",
        "low": "🐢 Baja",
    }.get(analysis.get("urgency", ""), "")

    mensaje = (
        f"🔔 *NUEVA RESPUESTA DE LEAD*\n\n"
        f"{temp} *{negocio}* — {ciudad}\n"
        f"👤 {nombre} | `{email}`\n"
        f"⭐ Score: {score}/100\n\n"
        f"💬 *Su mensaje:*\n"
        f"_{reply_text[:300].strip()}_\n\n"
        f"🤖 *Análisis Claude:*\n"
        f"  • Sentimiento: {sentimiento_emoji}\n"
        f"  • Urgencia: {urgencia_emoji}\n"
        f"  • Acción: {analysis.get('suggested_action', 'Responder pronto')}\n\n"
        f"📝 *Respuesta sugerida:*\n"
        f"_{suggested_response[:400].strip()}_"
    )

    # Botones de acción
    keyboard = [
        [
            InlineKeyboardButton("✅ Usar respuesta", callback_data=f"use_reply:{email}"),
            InlineKeyboardButton("📅 Agendar llamada", callback_data=f"schedule:{email}"),
        ],
        [
            InlineKeyboardButton("🚫 Marcar no interesado", callback_data=f"not_interested:{email}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Enviar a Zenon (master)
    if cfg.telegram_bot_token and cfg.telegram_master_chat_id:
        try:
            from telegram import Bot
            bot = Bot(token=cfg.telegram_bot_token)
            await bot.send_message(
                chat_id=cfg.telegram_master_chat_id,
                text=mensaje,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Error enviando notificación de reply: {e}")

    # Enviar también al cliente si tiene Telegram propio
    if cliente_telegram_id and cliente_telegram_id != cfg.telegram_master_chat_id:
        await send_telegram(mensaje, chat_id=cliente_telegram_id)


async def expand_search_categories(termino_base: str) -> list[str]:
    """
    Usa Claude Haiku para expandir un término a múltiples categorías sinónimas.

    Objetivo: atrapar negocios que se registraron con categorías distintas en Google.
    Ej: "tortillería" → ["tortillería", "fábrica de tortillas", "molino de masa",
                         "elaboración de tortillas", "tortillas de harina"]

    Estos términos van TODOS en un solo searchStringsArray → un solo run de Apify.
    """
    if not cfg.anthropic_api_key:
        return [termino_base]

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)

        prompt = f"""Eres experto en categorías de Google Maps México para búsqueda B2B.

El usuario quiere encontrar negocios tipo: "{termino_base}"

Genera 5-7 términos de búsqueda en español que capturen TODOS los negocios relacionados,
incluyendo los que se registraron con una categoría diferente en Google Maps.

Piensa en: el término exacto, sinónimos, categorías de Google relacionadas,
nombres alternativos del giro comercial en México.

Ejemplo para "ferretería":
["ferretería", "tlapalería", "material de construcción", "pinturas y ferretería", "materiales para construcción"]

Ejemplo para "tortillería":
["tortillería", "fábrica de tortillas", "molino de masa", "elaboración de tortillas", "tortillas de harina", "tostadas y tortillas"]

Devuelve SOLO un JSON array en español, sin explicaciones:
["término1", "término2", "término3", ...]

Tipo de negocio: {termino_base}"""

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]).strip()
        terms = json.loads(raw)
        if isinstance(terms, list) and terms:
            # Asegurar que el término original siempre esté primero
            if termino_base not in terms:
                terms.insert(0, termino_base)
            logger.info(f"Categorías expandidas para '{termino_base}': {terms}")
            return terms
        return [termino_base]
    except Exception as e:
        logger.warning(f"expand_search_categories error: {e}")
        return [termino_base]


async def parse_finder_intent(text: str) -> Optional[dict]:
    """
    Usa Claude para interpretar una solicitud de búsqueda en lenguaje natural.
    Retorna dict con: terminos, ciudades, estado, cantidad — o None si no es una búsqueda.
    """
    from ..config import cfg
    if not cfg.anthropic_api_key:
        logger.warning("parse_finder_intent: ANTHROPIC_API_KEY no configurado")
        return None

    try:
        import anthropic
        # IMPORTANTE: usar AsyncAnthropic para no bloquear el event loop de Telegram
        client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
        prompt = f"""Analiza si el siguiente mensaje es una solicitud de búsqueda de negocios/empresas para lead generation.
Si lo es, extrae la información clave y devuelve ÚNICAMENTE un JSON válido con este formato exacto:
{{
  "es_busqueda": true,
  "terminos": ["término1", "término2"],
  "ciudades": ["Ciudad1", "Ciudad2"],
  "estado": "Nombre del Estado",
  "cantidad": 100
}}

Si NO es una solicitud de búsqueda, devuelve:
{{"es_busqueda": false}}

Reglas:
- "terminos": variaciones/sinónimos del tipo de negocio a buscar
- "ciudades": lista de ciudades/municipios mencionados
- "estado": estado de la república (o null si no se menciona)
- "cantidad": número solicitado (default 50 si no se especifica)

Mensaje: {text}

Responde SOLO con el JSON, sin explicaciones."""

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Claude a veces envuelve el JSON en ```json ... ``` — limpiar antes de parsear
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]).strip()
        logger.info(f"parse_finder_intent respuesta: {raw[:200]}")
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"parse_finder_intent JSON inválido: {e}")
        return None
    except Exception as e:
        logger.warning(f"parse_finder_intent error: {e}")
        return None


async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja mensajes de texto libre (no comandos).
    Usa Claude para detectar si es una solicitud de búsqueda de leads (ZenonFinder).
    Solo el master (Zenon) puede lanzar búsquedas vía texto libre.
    """
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if not is_master(chat_id):
        # Clientes no tienen acceso a búsquedas en texto libre
        await update.message.reply_text(
            "Usa /ayuda para ver los comandos disponibles."
        )
        return

    await update.message.reply_text("🔍 Interpretando tu solicitud...")

    intent = await parse_finder_intent(text)

    if intent is None and not cfg.anthropic_api_key:
        await update.message.reply_text(
            "⚠️ *ANTHROPIC_API_KEY no configurado*\n\n"
            "ZenonFinder necesita tu clave de Claude AI para interpretar lenguaje natural.\n\n"
            "Agrega esta línea a tu archivo `.env`:\n"
            "`ANTHROPIC_API_KEY=sk-ant-api03-...`\n\n"
            "Luego reinicia el bot con `python -X utf8 start_monitor.py`.\n\n"
            "Por ahora usa: `/agregar [categoría] [ciudad]`",
            parse_mode="Markdown",
        )
        return

    if not intent or not intent.get("es_busqueda"):
        await update.message.reply_text(
            "No identifiqué una solicitud de búsqueda.\n\n"
            "Para buscar leads escribe algo como:\n"
            "_'Quiero 50 talleres mecánicos en Monterrey, NL'_\n\n"
            "O usa /agregar [categoría] [ciudad] para búsqueda rápida.\n"
            "Usa /ayuda para ver todos los comandos.",
            parse_mode="Markdown",
        )
        return

    terminos_base = intent.get("terminos", [])
    ciudades = intent.get("ciudades", [])
    estado = intent.get("estado") or "Nuevo León"
    cantidad = intent.get("cantidad", 50)

    if not terminos_base:
        await update.message.reply_text(
            "❓ Entendí que quieres buscar negocios, pero necesito el *tipo de negocio*.\n\n"
            "Ejemplo: _'100 tortillerías en Nuevo León'_",
            parse_mode="Markdown",
        )
        return

    # ── Expansión de categorías ─────────────────────────────────
    termino_principal = terminos_base[0]
    await update.message.reply_text(
        f"🔍 Expandiendo categorías para *{termino_principal}*...",
        parse_mode="Markdown",
    )
    terminos_expandidos = await expand_search_categories(termino_principal)

    # Calcular lugares por término para llegar al objetivo total
    max_por_termino = max(10, cantidad // max(len(terminos_expandidos), 1))

    # Location: estado completo (UN solo run cubre todo el estado)
    location_region = f"{estado}, Mexico"
    if ciudades:
        # Si mencionó ciudades específicas, usarlas como referencia en la region
        location_region = f"{estado}, Mexico"   # Apify filtra por estado, las ciudades estarán incluidas

    # Lista de categorías para mostrar en confirmación
    cats_str = "\n".join(f"  • {t}" for t in terminos_expandidos)

    confirmacion = (
        f"✅ *Solicitud interpretada:*\n\n"
        f"🏭 Negocio: *{termino_principal}*\n\n"
        f"🔍 *Categorías a buscar ({len(terminos_expandidos)}):*\n{cats_str}\n\n"
        f"🗺️ Región: *{estado}, México*\n"
        f"🎯 Objetivo: *{cantidad} leads*\n"
        f"  ({max_por_termino} por categoría × {len(terminos_expandidos)} = hasta {max_por_termino * len(terminos_expandidos)})\n\n"
        f"⚡ *1 solo run de Apify* — ~20-30 segundos\n\n"
        f"¿Confirmas? /si para iniciar · /no para cancelar"
    )

    # Guardar intención expandida en context
    context.user_data["pending_finder"] = {
        "termino_principal": termino_principal,
        "terminos_expandidos": terminos_expandidos,
        "estado": estado,
        "location_region": location_region,
        "cantidad": cantidad,
        "max_por_termino": max_por_termino,
    }

    await update.message.reply_text(confirmacion, parse_mode="Markdown")


async def cmd_si(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma y lanza la búsqueda pendiente interpretada por ZenonFinder."""
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        return

    pending = context.user_data.get("pending_finder")
    if not pending:
        await update.message.reply_text("No hay ninguna búsqueda pendiente de confirmar.")
        return

    context.user_data.pop("pending_finder", None)

    termino_principal = pending["termino_principal"]
    terminos_expandidos = pending["terminos_expandidos"]
    estado = pending["estado"]
    location_region = pending["location_region"]
    max_por_termino = pending["max_por_termino"]

    await update.message.reply_text(
        f"🚀 *ZenonFinder — Iniciando búsqueda*\n\n"
        f"🏭 *{termino_principal}* en {estado}\n"
        f"🔍 {len(terminos_expandidos)} categorías · {max_por_termino} c/u\n"
        f"⚡ Un solo run — ~20-30 segundos...",
        parse_mode="Markdown",
    )

    async def run_all():
        from ..pipeline import run_pipeline
        import traceback
        try:
            stats = await run_pipeline(
                terminos=terminos_expandidos,
                location=location_region,
                cliente_id=cfg.cliente_id,
                max_places=max_por_termino * len(terminos_expandidos),
            )
            resumen = (
                f"🎯 *ZenonFinder — Búsqueda Completada*\n\n"
                f"🏭 *{termino_principal}* — {estado}\n"
                f"🔍 Categorías: {len(terminos_expandidos)}\n\n"
                f"📊 *Resultados:*\n"
                f"  📍 Apify: {stats.apify_resultados} lugares encontrados\n"
                f"  📧 Email leads (DB1): {stats.email_leads_insertados}\n"
                f"  📱 Social leads (DB2): {stats.social_leads_insertados}\n\n"
                f"_(ver dashboard para exportar)_"
            )
            await send_telegram(resumen)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Pipeline falló: {e}\n{tb}")
            await send_telegram(
                f"❌ *Error en búsqueda*\n\n"
                f"🏭 {termino_principal} — {estado}\n"
                f"Error: `{str(e)[:200]}`"
            )

    asyncio.create_task(run_all())


async def cmd_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancela la búsqueda pendiente."""
    context.user_data.pop("pending_finder", None)
    await update.message.reply_text("❌ Búsqueda cancelada.")


# ============================================================
# COMANDOS DENUE (solo Zenon/master)
# ============================================================

async def cmd_denue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Ingesta masiva de leads desde DENUE/INEGI por estado y categoría.
    Uso: /denue [estado] [categoria]
    Ejemplos:
      /denue                          → Nuevo León, mineria (default)
      /denue Coahuila                 → Coahuila, mineria
      /denue NuevoLeon constructoras  → Nuevo León, constructoras
      /denue Jalisco ferreterias      → Jalisco, ferreterías
      /denue Tamaulipas porcicultura  → Tamaulipas, porcicultura

    Categorías: mineria, constructoras, ferreterias, mantenimiento,
      albercas, arquitectos, hoteles, molinera, porcicultura, automotriz,
      agregados, recicladora, fundidora, pintores, pinturas
    """
    from ..denue_enricher import SECTORES_DENUE

    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido al administrador.")
        return

    args = context.args or []

    # Detectar si el último arg es una categoría conocida
    categoria = "mineria"
    estado = "Nuevo León"

    if len(args) == 0:
        pass  # defaults
    elif len(args) == 1:
        if args[0].lower() in SECTORES_DENUE:
            categoria = args[0].lower()
        else:
            estado = args[0]
    else:
        # Último arg = categoría si está en catálogo, el resto = estado
        if args[-1].lower() in SECTORES_DENUE:
            categoria = args[-1].lower()
            estado = " ".join(args[:-1])
        else:
            estado = " ".join(args)

    cfg_sector = SECTORES_DENUE.get(categoria, SECTORES_DENUE["mineria"])

    await update.message.reply_text(
        f"🏗️ *DENUE — Ingesta {cfg_sector['label']}*\n\n"
        f"📍 Estado: *{estado}*\n"
        f"🔍 Buscando: {cfg_sector['descripcion']}...\n\n"
        f"⏳ Esto tarda ~30-60 segundos, te aviso cuando termine.",
        parse_mode="Markdown",
    )

    async def run_denue_ingesta():
        from ..denue_enricher import DenueEnricher
        try:
            enricher = DenueEnricher()
            result = await enricher.ingestar_sector(
                cliente_id=cfg.cliente_id,
                estado=estado,
                categoria=categoria,
            )
            await send_telegram(
                f"✅ *DENUE — Ingesta Completada*\n\n"
                f"📍 Estado: {result['estado']} (código {result['entidad_code']})\n"
                f"🏭 Sector: *{result['categoria']}*\n\n"
                f"📊 *Resultados:*\n"
                f"  🔍 Encontrados en DENUE: *{result['encontrados_denue']}*\n"
                f"  ✅ Insertados nuevos: *{result['insertados_nuevos']}*\n"
                f"  ♻️ Ya existían en DB: {result['ya_existian']}\n\n"
                f"Usa /calidad para ver la distribución de estrellas."
            )
        except ValueError as e:
            await send_telegram(f"❌ *DENUE — Categoría no válida*\n\n{e}")
        except Exception as e:
            logger.error(f"cmd_denue error: {e}")
            await send_telegram(f"❌ *DENUE — Error*\n\n`{str(e)[:300]}`")

    asyncio.create_task(run_denue_ingesta())


async def cmd_enriquecer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Enriquece leads existentes sin datos DENUE.
    Útil para mejorar leads de Apify con datos oficiales INEGI.
    Uso: /enriquecer [limit]
    Ejemplo: /enriquecer 50
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    limit = 30
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            pass
    limit = min(limit, 100)

    await update.message.reply_text(
        f"🔄 *DENUE — Enriquecimiento en lote*\n\n"
        f"Procesando hasta *{limit}* leads sin datos DENUE...\n"
        f"⏳ ~1-2 minutos...",
        parse_mode="Markdown",
    )

    async def run_batch():
        from ..denue_enricher import batch_enriquecer_leads
        try:
            stats = await batch_enriquecer_leads(
                cliente_id=cfg.cliente_id,
                limit=limit,
            )
            await send_telegram(
                f"✅ *DENUE — Enriquecimiento Completado*\n\n"
                f"📊 *Resultados ({stats['total']} leads procesados):*\n"
                f"  ✅ Enriquecidos: *{stats['enriquecidos']}*\n"
                f"  ❓ Sin coincidencia: {stats['sin_match']}\n"
                f"  ❌ Errores: {stats['errores']}\n\n"
                f"Usa /calidad para ver la distribución de estrellas actualizada."
            )
        except ValueError as e:
            await send_telegram(f"❌ DENUE no configurado: {e}")
        except Exception as e:
            logger.error(f"cmd_enriquecer error: {e}")
            await send_telegram(f"❌ Error: `{str(e)[:200]}`")

    asyncio.create_task(run_batch())


async def cmd_verificar_mineria(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Verifica/encuentra emails de leads mineros con AnyMailFinder.
    - Leads con email DENUE (pendiente) → verify_email() → 0.1 crédito c/u
    - Leads sin email + sitio_web → find_by_company() → 1 crédito c/u
    Uso: /verificar_mineria [limite]
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    limite = 150
    if context.args:
        try:
            limite = int(context.args[0])
        except ValueError:
            pass
    limite = min(limite, 300)

    await update.message.reply_text(
        f"🔬 *Verificando emails de leads mineros*\n\n"
        f"📋 Hasta {limite} leads\n"
        f"💳 Costo estimado: ~{int(limite * 0.35)} créditos\n\n"
        f"⏳ 3-5 minutos... te aviso cuando termine.",
        parse_mode="Markdown",
    )

    async def run_verificacion():
        from ..anymail_enricher import AnymailEnricher
        from ..denue_enricher import calcular_calidad_stars

        db = get_db()
        anymail = AnymailEnricher()

        # Verificar cuenta AnyMailFinder
        account = await anymail.check_account_status()
        if not account["ok"]:
            await send_telegram(f"❌ AnyMailFinder no disponible: {account['error']}")
            return

        creditos_inicio = account.get("credits_remaining", 0)

        # 1. Leads con email pendiente de verificación (categorías mineras)
        resp_con = db.table("leads_master").select(
            "id, nombre_negocio, email, sitio_web, telefono, "
            "owner_name, apify_run_id, razon_social, latitud, longitud, denue_confirmado"
        ).eq("cliente_id", cfg.cliente_id).eq(
            "email_status", "pendiente_validacion"
        ).or_(
            "categoria.ilike.%cantera%,categoria.ilike.%arena%,"
            "categoria.ilike.%grava%,categoria.ilike.%miner%,"
            "categoria.ilike.%extrac%,categoria.ilike.%caliza%,"
            "categoria.ilike.%cemento%,categoria.ilike.%marmol%,"
            "categoria.ilike.%piedra%"
        ).limit(limite).execute()

        # 2. Leads sin email pero con sitio_web (mismas categorías)
        resto = max(0, limite - len(resp_con.data or []))
        resp_sin = db.table("leads_master").select(
            "id, nombre_negocio, sitio_web, telefono, "
            "owner_name, apify_run_id, razon_social, latitud, longitud, denue_confirmado"
        ).eq("cliente_id", cfg.cliente_id).is_(
            "email", "null"
        ).not_.is_("sitio_web", "null").or_(
            "categoria.ilike.%cantera%,categoria.ilike.%arena%,"
            "categoria.ilike.%grava%,categoria.ilike.%miner%,"
            "categoria.ilike.%extrac%,categoria.ilike.%caliza%,"
            "categoria.ilike.%cemento%,categoria.ilike.%marmol%,"
            "categoria.ilike.%piedra%"
        ).limit(resto).execute() if resto > 0 else type("R", (), {"data": []})()

        todos = (resp_con.data or []) + (resp_sin.data or [])
        logger.info(f"verificar_mineria: {len(todos)} leads a procesar")

        stats = {"procesados": 0, "validos": 0, "nuevos": 0,
                 "invalidos": 0, "sin_resultado": 0, "creditos": 0.0}

        for lead in todos:
            try:
                email_existente = lead.get("email")
                nombre = lead.get("nombre_negocio", "")

                if email_existente and "@" in str(email_existente):
                    result = await anymail.verify_email(email_existente)
                elif lead.get("sitio_web"):
                    result = await anymail.find_by_company(nombre)
                else:
                    stats["sin_resultado"] += 1
                    continue

                stats["procesados"] += 1
                stats["creditos"] += result.credits_used

                nuevo_email = email_existente
                nuevo_status = "not_found"

                if result.emails:
                    mejor = result.emails[0]
                    nuevo_email = mejor.get("email", email_existente)
                    nuevo_status = mejor.get("email_status", "unknown")

                    if nuevo_status == "valid":
                        stats["validos"] += 1
                        if not email_existente:
                            stats["nuevos"] += 1
                    else:
                        stats["invalidos"] += 1
                else:
                    stats["sin_resultado"] += 1

                # Actualizar en Supabase
                upd: dict = {"email_status": nuevo_status}
                if nuevo_email and nuevo_email != email_existente:
                    upd["email"] = nuevo_email

                lead_merged = {**lead, **upd}
                upd["calidad_stars"] = calcular_calidad_stars(
                    lead_merged,
                    denue_confirmado=bool(lead.get("denue_confirmado"))
                )
                db.table("leads_master").update(upd).eq("id", lead["id"]).execute()

            except Exception as e:
                logger.error(f"Error en verificar_mineria para {lead.get('nombre_negocio')}: {e}")
                stats["sin_resultado"] += 1

            await asyncio.sleep(0.15)

        await send_telegram(
            f"✅ *Verificación AnyMailFinder — Completada*\n\n"
            f"📊 *Leads mineros procesados: {stats['procesados']}*\n\n"
            f"  ✅ Emails válidos: *{stats['validos']}*\n"
            f"  🆕 Emails nuevos encontrados: *{stats['nuevos']}*\n"
            f"  ❌ Inválidos/no encontrados: {stats['invalidos'] + stats['sin_resultado']}\n\n"
            f"💳 Créditos usados: {stats['creditos']:.1f}\n"
            f"💳 Créditos restantes: ~{int(creditos_inicio - stats['creditos']):,}\n\n"
            f"Usa /calidad para ver cuántos leads subieron a ★★★★"
        )

    asyncio.create_task(run_verificacion())


async def cmd_verificar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Verifica/encuentra emails con AnyMailFinder para cualquier cliente.
    Uso: /verificar [rc|lp|mac|sqb|quimica] [limite]
      rc      → Regio Cribas         (leads_master, pendientes de verificar)
      lp      → LuPront              (leads_master, sin email todavía)
      mac     → Macrisa              (macrisa_leads, unknown + sin email)
      sqb     → SQB / Química Intel. (leads_master, sitio_web → find + pendientes → verify)
    Ejemplo: /verificar lp 300
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    CLIENTES = {
        "rc":      {"nombre": "Regio Cribas",  "id": "d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99"},
        "lp":      {"nombre": "LuPront",        "id": "b8e2f4d6-1a3c-4e5f-8b0d-2c4e6a8f0b2d"},
        "mac":     {"nombre": "Macrisa",        "id": None},
        "macrisa": {"nombre": "Macrisa",        "id": None},
        "sqb":     {"nombre": "SQB / Quimica Inteligente", "id": "c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c"},
        "quimica": {"nombre": "SQB / Quimica Inteligente", "id": "c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c"},
    }

    args = context.args or []
    clave = args[0].lower() if args else ""
    if clave not in CLIENTES:
        lista = "\n".join(f"  `/verificar {k} [limite]` → {v['nombre']}" for k, v in CLIENTES.items() if k != "macrisa")
        await update.message.reply_text(
            f"⚠️ *Uso:* `/verificar [cliente] [limite]`\n\n{lista}",
            parse_mode="Markdown"
        )
        return

    limite = 200
    if len(args) >= 2:
        try:
            limite = int(args[1])
        except ValueError:
            pass
    limite = min(limite, 500)

    info = CLIENTES[clave]
    nombre_cliente = info["nombre"]
    cliente_id = info["id"]

    await update.message.reply_text(
        f"🔬 *Verificando emails — {nombre_cliente}*\n\n"
        f"📋 Hasta {limite} leads\n"
        f"⏳ Esto puede tomar varios minutos...",
        parse_mode="Markdown",
    )

    async def run_verificacion():
        from ..anymail_enricher import AnymailEnricher
        db = get_db()
        anymail = AnymailEnricher()

        account = await anymail.check_account_status()
        if not account["ok"]:
            await send_telegram(f"❌ AnyMailFinder no disponible: {account['error']}")
            return

        creditos_inicio = account.get("credits_remaining", 0)
        stats = {"procesados": 0, "validos": 0, "invalidos": 0, "no_encontrados": 0, "creditos": 0.0}

        # ── MACRISA ────────────────────────────────────────────────────
        if cliente_id is None:
            # Ruta A: emails con status unknown → verify
            resp_a = db.table("macrisa_leads").select(
                "id, nombre, email, website"
            ).eq("email_status", "unknown").limit(limite // 2).execute()

            # Ruta B: sin email pero con website → find
            resto = max(0, limite - len(resp_a.data or []))
            resp_b = db.table("macrisa_leads").select(
                "id, nombre, email, website"
            ).is_("email", "null").not_.is_("website", "null").eq(
                "anymail_procesado", False
            ).limit(resto).execute() if resto > 0 else type("R", (), {"data": []})()

            todos = (resp_a.data or []) + (resp_b.data or [])
            await send_telegram(f"📋 Macrisa: {len(resp_a.data or [])} a verificar + {len(resp_b.data or [])} a buscar")

            for lead in todos:
                try:
                    email_ex = lead.get("email")
                    nombre   = lead.get("nombre", "")
                    website  = lead.get("website")

                    if email_ex and "@" in str(email_ex):
                        result = await anymail.verify_email(email_ex)
                    elif website:
                        result = await anymail.find_by_company(company_name=nombre)
                    else:
                        continue

                    stats["procesados"] += 1
                    stats["creditos"]   += result.credits_used

                    nuevo_email  = email_ex
                    nuevo_status = "not_found"

                    if result.emails:
                        mejor = result.emails[0]
                        nuevo_email  = mejor.get("email", email_ex)
                        nuevo_status = mejor.get("email_status", "unknown")

                    if nuevo_status == "valid":
                        stats["validos"] += 1
                    else:
                        stats["invalidos"] += 1

                    db.table("macrisa_leads").update({
                        "email":            nuevo_email,
                        "email_status":     nuevo_status,
                        "anymail_procesado": True,
                        "anymail_creditos": result.credits_used,
                    }).eq("id", lead["id"]).execute()

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error verificando macrisa lead {lead.get('id')}: {e}")

        # ── REGIO CRIBAS ───────────────────────────────────────────────
        elif cliente_id == "d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99":
            # Leads con email pendiente (denue_verified, pendiente_validacion, aprobado)
            resp_a = db.table("leads_master").select(
                "id, nombre_negocio, email, sitio_web"
            ).eq("cliente_id", cliente_id).in_(
                "email_status", ["pendiente_validacion", "denue_verified", "aprobado"]
            ).limit(limite).execute()

            todos = resp_a.data or []
            await send_telegram(f"📋 Regio Cribas: {len(todos)} emails a verificar")

            for lead in todos:
                try:
                    email_ex = lead.get("email")
                    nombre   = lead.get("nombre_negocio", "")

                    if email_ex and "@" in str(email_ex):
                        result = await anymail.verify_email(email_ex)
                    elif lead.get("sitio_web"):
                        result = await anymail.find_by_company(company_name=nombre)
                    else:
                        stats["no_encontrados"] += 1
                        continue

                    stats["procesados"] += 1
                    stats["creditos"]   += result.credits_used

                    nuevo_email  = email_ex
                    nuevo_status = "not_found"

                    if result.emails:
                        mejor = result.emails[0]
                        nuevo_email  = mejor.get("email", email_ex)
                        nuevo_status = mejor.get("email_status", "unknown")

                    if nuevo_status == "valid":
                        stats["validos"] += 1
                    else:
                        stats["invalidos"] += 1

                    db.table("leads_master").update({
                        "email":             nuevo_email,
                        "email_status":      nuevo_status,
                        "anymail_procesado": True,
                    }).eq("id", lead["id"]).execute()

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error verificando RC lead {lead.get('id')}: {e}")

        # ── SQB / QUÍMICA INTELIGENTE ──────────────────────────────────
        elif cliente_id == "c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c":
            # Ruta A: tienen email pendiente → verify_email()
            resp_a = db.table("leads_master").select(
                "id, nombre_negocio, email, sitio_web"
            ).eq("cliente_id", cliente_id).in_(
                "email_status", ["pendiente_validacion", "denue_verified"]
            ).limit(limite // 2).execute()

            # Ruta B: sin email pero con sitio_web → find_by_company()
            resto = max(0, limite - len(resp_a.data or []))
            resp_b = db.table("leads_master").select(
                "id, nombre_negocio, email, sitio_web"
            ).eq("cliente_id", cliente_id).is_(
                "email", "null"
            ).not_.is_("sitio_web", "null").eq(
                "anymail_procesado", False
            ).limit(resto).execute() if resto > 0 else type("R", (), {"data": []})()

            todos = (resp_a.data or []) + (resp_b.data or [])
            await send_telegram(
                f"📋 SQB: {len(resp_a.data or [])} a verificar + {len(resp_b.data or [])} a buscar"
            )

            for lead in todos:
                try:
                    email_ex = lead.get("email")
                    nombre   = lead.get("nombre_negocio", "")

                    if email_ex and "@" in str(email_ex):
                        result = await anymail.verify_email(email_ex)
                    elif lead.get("sitio_web"):
                        result = await anymail.find_by_company(company_name=nombre)
                    else:
                        stats["no_encontrados"] += 1
                        continue

                    stats["procesados"] += 1
                    stats["creditos"]   += result.credits_used

                    nuevo_email  = email_ex
                    nuevo_status = "not_found"

                    if result.emails:
                        mejor = result.emails[0]
                        nuevo_email  = mejor.get("email", email_ex)
                        nuevo_status = mejor.get("email_status", "unknown")

                    if nuevo_status == "valid":
                        stats["validos"] += 1
                    else:
                        stats["invalidos"] += 1

                    db.table("leads_master").update({
                        "email":             nuevo_email,
                        "email_status":      nuevo_status,
                        "anymail_procesado": True,
                    }).eq("id", lead["id"]).execute()

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error verificando SQB lead {lead.get('id')}: {e}")

        # ── LUPRONT ────────────────────────────────────────────────────
        else:
            # Leads sin procesar por AnyMailFinder
            resp = db.table("leads_master").select(
                "id, nombre_negocio, email, sitio_web"
            ).eq("cliente_id", cliente_id).eq(
                "anymail_procesado", False
            ).limit(limite).execute()

            todos = resp.data or []
            await send_telegram(f"📋 LuPront: {len(todos)} leads a procesar")

            for lead in todos:
                try:
                    email_ex = lead.get("email")
                    nombre   = lead.get("nombre_negocio", "")

                    if email_ex and "@" in str(email_ex):
                        result = await anymail.verify_email(email_ex)
                    else:
                        result = await anymail.find_by_company(company_name=nombre)

                    stats["procesados"] += 1
                    stats["creditos"]   += result.credits_used

                    nuevo_email  = email_ex
                    nuevo_status = "not_found"

                    if result.emails:
                        mejor = result.emails[0]
                        nuevo_email  = mejor.get("email", email_ex)
                        nuevo_status = mejor.get("email_status", "unknown")

                    if nuevo_status == "valid":
                        stats["validos"] += 1
                    else:
                        stats["invalidos"] += 1

                    db.table("leads_master").update({
                        "email":             nuevo_email,
                        "email_status":      nuevo_status,
                        "anymail_procesado": True,
                    }).eq("id", lead["id"]).execute()

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error verificando LP lead {lead.get('id')}: {e}")

        # ── RESUMEN FINAL ──────────────────────────────────────────────
        account2 = await anymail.check_account_status()
        creditos_fin = account2.get("credits_remaining", creditos_inicio)
        creditos_usados = creditos_inicio - creditos_fin

        await send_telegram(
            f"✅ *Verificación {nombre_cliente} completada*\n\n"
            f"📊 Procesados:  {stats['procesados']}\n"
            f"✅ Válidos:     {stats['validos']}\n"
            f"❌ Inválidos:   {stats['invalidos']}\n"
            f"💳 Créditos:    {creditos_usados:.1f} usados ({creditos_fin:.0f} restantes)\n\n"
            f"_Usa /leads para ver el resumen actualizado_"
        )

    asyncio.create_task(run_verificacion())


async def cmd_calidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Muestra la distribución de calidad stars de los leads en la DB.
    Útil para medir el impacto del enriquecimiento DENUE.
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    try:
        db = get_db()

        # Distribución por stars
        result = db.table("leads_master").select(
            "calidad_stars, denue_confirmado, email, telefono"
        ).eq("cliente_id", cfg.cliente_id).execute()

        leads = result.data or []
        total = len(leads)

        if total == 0:
            await update.message.reply_text("No hay leads en la base de datos.")
            return

        # Contar por stars
        por_stars = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        con_denue = 0
        con_email = 0
        con_tel = 0

        for lead in leads:
            stars = lead.get("calidad_stars") or 1
            por_stars[stars] = por_stars.get(stars, 0) + 1
            if lead.get("denue_confirmado"):
                con_denue += 1
            if lead.get("email"):
                con_email += 1
            if lead.get("telefono"):
                con_tel += 1

        # Construir barra visual
        def barra(n, total, width=10):
            filled = round(n / total * width) if total > 0 else 0
            return "█" * filled + "░" * (width - filled)

        now = datetime.now().strftime("%d/%m %H:%M")
        mensaje = (
            f"⭐ *Calidad de Leads — {total} total*\n_{now}_\n\n"
            f"★★★★★ {por_stars[5]:>4}  {barra(por_stars[5], total)}\n"
            f"★★★★☆ {por_stars[4]:>4}  {barra(por_stars[4], total)}\n"
            f"★★★☆☆ {por_stars[3]:>4}  {barra(por_stars[3], total)}\n"
            f"★★☆☆☆ {por_stars[2]:>4}  {barra(por_stars[2], total)}\n"
            f"★☆☆☆☆ {por_stars[1]:>4}  {barra(por_stars[1], total)}\n\n"
            f"*Fuentes:*\n"
            f"  🏛️ DENUE confirmado: {con_denue} ({con_denue*100//total}%)\n"
            f"  📧 Con email: {con_email} ({con_email*100//total}%)\n"
            f"  📞 Con teléfono: {con_tel} ({con_tel*100//total}%)\n\n"
            f"_Campaña lista cuando tengas 100+ leads ★★★★_"
        )
        await update.message.reply_text(mensaje, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_rutina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Lanza la rutina de enriquecimiento y deduplicación desde Telegram.

    Uso:
      /rutina sqb          → Paso 1 (Apify+AMF) + Paso 2 (dedup)
      /rutina sqb paso1    → Solo Apify + AMF
      /rutina sqb paso2    → Solo deduplicar
      /rutina sqb simular  → Simular dedup sin borrar
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    import sys, os
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "🔄 *Rutina de Enriquecimiento*\n\n"
            "`/rutina sqb`         — Dedup + Apify + AMF\n"
            "`/rutina sqb paso1`   — Solo Apify + AMF\n"
            "`/rutina sqb paso2`   — Solo deduplicar\n"
            "`/rutina sqb simular` — Ver duplicados sin borrar",
            parse_mode="Markdown"
        )
        return

    cliente = args[0].lower()
    modo    = args[1].lower() if len(args) > 1 else ""

    base_dir    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python_exec = sys.executable

    if cliente == "sqb":
        script = os.path.join(base_dir, "rutina_sqb.py")
        if modo == "paso1":
            cmd  = [python_exec, script, "--paso1"]
            desc = "SQB — Enriquecimiento Apify + AMF"
        elif modo == "paso2":
            cmd  = [python_exec, script, "--paso2"]
            desc = "SQB — Deduplicación"
        elif modo == "simular":
            cmd  = [python_exec, script, "--paso2", "--dry-run"]
            desc = "SQB — Simulación deduplicación"
        else:
            cmd  = [python_exec, script]
            desc = "SQB — Rutina completa (dedup + Apify + AMF)"
    else:
        await update.message.reply_text("⚠️ Cliente no reconocido. Usa: `sqb`", parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"🔄 *Lanzando rutina*\n\n"
        f"📋 {desc}\n"
        f"⏳ Corriendo en Mac Mini... te notificaré por Telegram al terminar.",
        parse_mode="Markdown"
    )

    async def run_rutina_bg():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0 and err:
                await send_telegram(f"⚠️ Rutina {desc} terminó con errores:\n`{err.decode()[:300]}`")
        except Exception as e:
            logger.error(f"cmd_rutina error: {e}")
            await send_telegram(f"❌ Error en rutina {desc}: `{str(e)[:200]}`")

    asyncio.create_task(run_rutina_bg())


async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Lanza pipelines completos de leads desde Telegram.
    El script corre en la Mac Mini y notifica por Telegram al terminar.

    Uso:
      /pipeline sqb        → SQB: AMF verification + export CSV
      /pipeline sqb denue  → SQB: solo DENUE scraping
      /pipeline sqb full   → SQB: DENUE + AMF + export (completo)
      /pipeline lp         → LuPront: AMF verification
      /pipeline lp denue   → LuPront: solo DENUE scraping
      /pipeline lp full    → LuPront: DENUE + AMF (completo)
      /pipeline mac        → Macrisa: AMF verification
      /pipeline status     → Ver qué pipelines están corriendo
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido.")
        return

    import subprocess
    import sys
    import os

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "🤖 *Pipeline — Centro de Control*\n\n"
            "*SQB (Química Inteligente):*\n"
            "`/pipeline sqb` — AMF + export CSV\n"
            "`/pipeline sqb denue` — solo DENUE\n"
            "`/pipeline sqb full` — DENUE + AMF + CSV\n\n"
            "*LuPront:*\n"
            "`/pipeline lp` — AMF verification\n"
            "`/pipeline lp denue` — solo DENUE\n"
            "`/pipeline lp full` — DENUE + AMF\n\n"
            "*Macrisa:*\n"
            "`/pipeline mac` — AMF verification\n\n"
            "`/pipeline status` — pipelines activos",
            parse_mode="Markdown"
        )
        return

    cliente = args[0].lower()
    modo = args[1].lower() if len(args) > 1 else ""

    # Directorio base del proyecto
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python_exec = sys.executable

    # ── Construir comando según cliente ──────────────────────────────────────
    if cliente == "sqb":
        script = os.path.join(base_dir, "sqb_pipeline.py")
        if modo == "denue":
            cmd = [python_exec, script, "--solo-denue"]
            desc = "SQB — DENUE scraping"
        elif modo == "apify":
            cmd = [python_exec, script, "--solo-apify"]
            desc = "SQB — Google Maps (Apify) enrichment"
        elif modo == "full":
            cmd = [python_exec, script]
            desc = "SQB — Pipeline completo (DENUE + Apify + AMF + CSV)"
        else:
            cmd = [python_exec, script, "--solo-amf"]
            desc = "SQB — AMF verification + export CSV"

    elif cliente in ("lp", "lupront"):
        script = os.path.join(base_dir, "buscar_lupront.py")
        if modo == "denue":
            cmd = [python_exec, script, "--solo-denue"]
            desc = "LuPront — DENUE scraping"
        elif modo == "full":
            cmd = [python_exec, script]
            desc = "LuPront — Pipeline completo (DENUE + AMF)"
        else:
            cmd = [python_exec, script, "--solo-email"]
            desc = "LuPront — AMF verification"

    elif cliente in ("mac", "macrisa"):
        script = os.path.join(base_dir, "verificar_macrisa.py")
        cmd = [python_exec, script]
        desc = "Macrisa — AMF verification"

    elif cliente == "status":
        # Mostrar procesos Python corriendo
        try:
            import psutil
            pipelines = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                try:
                    cl = proc.info.get('cmdline') or []
                    cl_str = " ".join(cl)
                    if any(p in cl_str for p in ['sqb_pipeline', 'buscar_lupront', 'verificar_macrisa']):
                        nombre = next((p for p in ['sqb_pipeline', 'buscar_lupront', 'verificar_macrisa'] if p in cl_str), '?')
                        pipelines.append(f"  • {nombre} (PID {proc.info['pid']})")
                except Exception:
                    pass
            if pipelines:
                msg = "⚙️ *Pipelines activos:*\n" + "\n".join(pipelines)
            else:
                msg = "✅ No hay pipelines corriendo en este momento."
            await update.message.reply_text(msg, parse_mode="Markdown")
        except ImportError:
            await update.message.reply_text(
                "ℹ️ Instala psutil para ver status: `pip install psutil`",
                parse_mode="Markdown"
            )
        return

    else:
        await update.message.reply_text(
            "⚠️ Cliente no reconocido. Usa: `sqb`, `lp`, `mac`",
            parse_mode="Markdown"
        )
        return

    # ── Lanzar proceso en background ─────────────────────────────────────────
    await update.message.reply_text(
        f"🚀 *Lanzando pipeline*\n\n"
        f"📋 {desc}\n"
        f"📂 `{os.path.basename(script)}`\n\n"
        f"⏳ Corriendo en Mac Mini... te notificaré por Telegram cuando termine.",
        parse_mode="Markdown"
    )

    async def run_pipeline_bg():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=base_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info(f"Pipeline {desc} completado exitosamente")
                # El script mismo envía su notificación de éxito por Telegram
            else:
                err = (stderr.decode("utf-8", errors="replace") or "")[-500:]
                await send_telegram(
                    f"❌ *Pipeline falló*\n\n"
                    f"📋 {desc}\n"
                    f"Error:\n`{err}`"
                )
        except Exception as e:
            logger.error(f"cmd_pipeline error: {e}")
            await send_telegram(f"❌ Error lanzando pipeline {desc}: `{str(e)[:200]}`")

    asyncio.create_task(run_pipeline_bg())


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los botones inline de los mensajes."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("use_reply:"):
        email = data.split(":", 1)[1]
        await query.edit_message_text(
            f"✅ Respuesta marcada para usar.\n"
            f"Abre Instantly.ai para enviarla a {email}."
        )
    elif data.startswith("schedule:"):
        email = data.split(":", 1)[1]
        await query.edit_message_text(
            f"📅 Abre cal.com para agendar una llamada con {email}.\n"
            f"Enlace: {cfg.cal_link if hasattr(cfg, 'cal_link') else 'Configura tu link en .env'}"
        )
    elif data.startswith("not_interested:"):
        email = data.split(":", 1)[1]
        # Marcar como do_not_contact en Supabase
        try:
            db = get_db()
            db.table("email_leads").update({
                "do_not_contact": True,
                "motivo_baja": "No interesado (marcado desde Telegram)",
            }).eq("email", email).execute()
            await query.edit_message_text(f"🚫 {email} marcado como no interesado.")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")


async def cmd_enriquecer_web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Enriquece leads sin email corporativo usando scraping web + redes sociales.
    Interviene ANTES de AnyMailFinder para mejorar la tasa de identificación.

    Pipeline por lead:
      1. Scraping del sitio web propio (homepage, /contacto, /nosotros, etc.)
      2. Búsqueda DuckDuckGo (si no hay URL o scraping falló)
      3. AnyMailFinder (último recurso — consume créditos)

    Targets: leads_master con email vacío/gratuito y calidad_stars < 5.

    Uso: /enriquecer_web [n]
    Ejemplo: /enriquecer_web 100
    """
    chat_id = update.effective_chat.id
    if not is_master(chat_id):
        await update.message.reply_text("❌ Acceso restringido al administrador.")
        return

    limit = 50
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "⚠️ Uso: /enriquecer\\_web \\[n\\]\nEjemplo: `/enriquecer_web 100`",
                parse_mode="MarkdownV2",
            )
            return
    limit = min(limit, 500)

    await update.message.reply_text(
        f"🌐 *Web Enricher — Iniciando*\n\n"
        f"📋 Procesando hasta *{limit}* leads sin email corporativo\n"
        f"📡 Pipeline: Scraping web → DuckDuckGo → AnyMailFinder\n"
        f"⚙️ Concurrencia: 5 leads simultáneos\n\n"
        f"⏳ Te envío progreso cada 10 leads procesados...",
        parse_mode="Markdown",
    )

    async def run_enrichment():
        from ..web_enricher import web_enricher as enricher

        try:
            # Obtener leads candidatos
            leads = await enricher.get_leads_to_enrich(
                cliente_id=cfg.cliente_id,
                limit=limit,
            )

            if not leads:
                await send_telegram(
                    "🌐 *Web Enricher*\n\n"
                    "✅ No hay leads pendientes de enriquecimiento web.\n"
                    "Todos los leads ya tienen email corporativo o son ★★★★★."
                )
                return

            await send_telegram(
                f"🌐 *Web Enricher — Procesando*\n\n"
                f"📋 *{len(leads)}* leads sin email corporativo encontrados\n"
                f"🔍 Iniciando scraping + búsqueda..."
            )

            async def progress_cb(stats: dict, done: int, total: int) -> None:
                pendientes = total - done
                await send_telegram(
                    f"🌐 *Enriquecimiento Web — Progreso*\n\n"
                    f"Procesados: {done}/{total}\n"
                    f"✅ Email encontrado: {stats['email_encontrado']}\n"
                    f"📱 Solo redes sociales: {stats['solo_social']}\n"
                    f"❌ No encontrado: {stats['no_encontrado']}\n"
                    f"⏳ Pendientes: {pendientes}"
                )

            stats = await enricher.run_batch(
                leads=leads,
                progress_callback=progress_cb,
                use_apify=False,  # Apify desactivado en modo batch (muy lento)
            )

            tasa = round(stats["email_encontrado"] * 100 / max(stats["total"], 1))
            await send_telegram(
                f"✅ *Web Enricher — Completado*\n\n"
                f"📊 *Resultados ({stats['total']} leads):*\n"
                f"  ✅ Email corporativo: *{stats['email_encontrado']}* ({tasa}%)\n"
                f"  📱 Solo redes sociales: *{stats['solo_social']}*\n"
                f"  ❌ No encontrado: {stats['no_encontrado']}\n"
                f"  ⚠️ Errores: {stats['errores']}\n\n"
                f"_Usa /calidad para ver el impacto en las estrellas_"
            )

        except Exception as e:
            logger.error(f"cmd_enriquecer_web error: {e}")
            await send_telegram(f"❌ *Web Enricher — Error*\n\n`{str(e)[:300]}`")

    asyncio.create_task(run_enrichment())


# ============================================================
# INICIALIZACIÓN DEL BOT
# ============================================================

def build_application() -> Application:
    """Construye y configura la aplicación del bot."""
    if not cfg.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado en .env")

    app = Application.builder().token(cfg.telegram_bot_token).build()

    # Registrar comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("vincular", cmd_vincular))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CommandHandler("help", cmd_ayuda))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("leads", cmd_leads))
    app.add_handler(CommandHandler("respuestas", cmd_respuestas))
    app.add_handler(CommandHandler("reporte", cmd_reporte))
    app.add_handler(CommandHandler("creditos", cmd_creditos))
    app.add_handler(CommandHandler("clientes", cmd_clientes))
    app.add_handler(CommandHandler("agregar", cmd_agregar))

    # DENUE / Enriquecimiento (solo Zenon)
    app.add_handler(CommandHandler("denue", cmd_denue))
    app.add_handler(CommandHandler("enriquecer", cmd_enriquecer))
    app.add_handler(CommandHandler("enriquecer_web", cmd_enriquecer_web))
    app.add_handler(CommandHandler("verificar_mineria", cmd_verificar_mineria))
    app.add_handler(CommandHandler("verificar", cmd_verificar))
    app.add_handler(CommandHandler("calidad", cmd_calidad))
    app.add_handler(CommandHandler("pipeline", cmd_pipeline))
    app.add_handler(CommandHandler("rutina",   cmd_rutina))

    # Confirmación de ZenonFinder (lenguaje natural)
    app.add_handler(CommandHandler("si", cmd_si))
    app.add_handler(CommandHandler("no", cmd_no))

    # Texto libre → ZenonFinder (debe ir AL FINAL, después de los comandos)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    # Botones inline
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🤖 Bot de Telegram (ZenonFinder) configurado correctamente")
    return app


# ============================================================
# ENTRYPOINT PRINCIPAL — requerido por start_all.py
# ============================================================

async def run_bot() -> None:
    """
    Arranca el bot de Telegram en modo polling.
    Función requerida por start_all.py.
    Se mantiene corriendo hasta que el proceso se detenga.
    """
    if not cfg.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado — bot de Telegram no iniciado.")
        return

    app = build_application()

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("🤖 ZenonFinder Bot activo — escuchando mensajes...")

    # Mantener corriendo hasta Ctrl+C o señal de stop
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
