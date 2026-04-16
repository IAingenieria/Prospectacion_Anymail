"""
LeadForge — Sistema de Alertas
Envía notificaciones por Telegram y macOS (fallback nativo).
Guarda todas las alertas en Supabase para auditoría.
"""
import logging
import platform
import subprocess
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

from ..config import cfg
from ..supabase_client import get_db

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


SEVERITY_EMOJI = {
    AlertSeverity.INFO: "ℹ️",
    AlertSeverity.WARNING: "⚠️",
    AlertSeverity.CRITICAL: "🚨",
}


# ============================================================
# NOTIFICACIÓN MACOS NATIVA (fallback si Telegram falla)
# ============================================================
def notify_macos(title: str, message: str, severity: AlertSeverity = AlertSeverity.WARNING) -> None:
    """Muestra una notificación nativa de macOS vía osascript."""
    if platform.system() != "Darwin":
        return
    try:
        script = f'display notification "{message}" with title "LeadForge: {title}"'
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception as e:
        logger.debug(f"macOS notification failed: {e}")


# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram(
    message: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """
    Envía mensaje a Telegram.
    Si no se especifica chat_id, usa el master chat de Zenon.
    """
    token = cfg.telegram_bot_token
    target_chat = chat_id or cfg.telegram_master_chat_id

    if not token or not target_chat:
        logger.warning("Telegram no configurado — skipping alert")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                TELEGRAM_API.format(token=token),
                json={
                    "chat_id": target_chat,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Error enviando Telegram: {e}")
        return False


def save_alert_to_db(
    tipo: str,
    mensaje: str,
    severidad: AlertSeverity,
    cliente_id: Optional[str] = None,
) -> None:
    """Guarda la alerta en Supabase para auditoría y seguimiento."""
    try:
        db = get_db()
        db.table("alertas").insert({
            "cliente_id": cliente_id or cfg.cliente_id,
            "tipo": tipo,
            "mensaje": mensaje,
            "severidad": severidad.value,
        }).execute()
    except Exception as e:
        logger.error(f"Error guardando alerta en DB: {e}")


async def fire_alert(
    tipo: str,
    mensaje: str,
    severidad: AlertSeverity = AlertSeverity.WARNING,
    cliente_id: Optional[str] = None,
    cliente_telegram_id: Optional[str] = None,
) -> None:
    """
    Dispara una alerta completa:
    1. Log en archivo
    2. Supabase (auditoría)
    3. Telegram (master + cliente si aplica)
    4. macOS nativa (fallback)
    """
    emoji = SEVERITY_EMOJI[severidad]
    timestamp = datetime.now().strftime("%d/%m %H:%M")

    # Log
    log_msg = f"[{severidad.value.upper()}] {tipo}: {mensaje}"
    if severidad == AlertSeverity.CRITICAL:
        logger.critical(log_msg)
    elif severidad == AlertSeverity.WARNING:
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Supabase
    save_alert_to_db(tipo, mensaje, severidad, cliente_id)

    # Telegram — Master (Zenon siempre recibe todo)
    tg_message = f"{emoji} *{tipo.upper()}*\n_{timestamp}_\n\n{mensaje}"
    await send_telegram(tg_message)

    # Telegram — Cliente (si tiene chat_id propio)
    if cliente_telegram_id and cliente_telegram_id != cfg.telegram_master_chat_id:
        await send_telegram(tg_message, chat_id=cliente_telegram_id)

    # macOS fallback (útil cuando el Mac Mini está frente a ti)
    notify_macos(tipo, mensaje[:100], severidad)
