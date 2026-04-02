"""
webhook_server.py — Servidor webhook de LeadForge
Recibe eventos de Instantly.ai y actualiza Supabase + Telegram.

Uso:
    python -X utf8 webhook_server.py              # Puerto 8001 (default)
    python -X utf8 webhook_server.py --port 9000  # Puerto personalizado

Endpoints:
    POST /webhook/instantly      ← Recibe eventos de Instantly.ai
    GET  /webhook/health         ← Health check
    GET  /webhook/test-telegram  ← Prueba Telegram

Configurar en Instantly.ai:
    Settings → Webhooks → Add Webhook
    URL: http://TU_IP:8001/webhook/instantly
    Events: Reply, Bounce, Open, Unsubscribe
    Secret: (el valor de INSTANTLY_WEBHOOK_SECRET en .env)
"""
import argparse
import logging
import sys
from pathlib import Path

# Asegurar que el directorio raíz esté en el path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/webhook.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("webhook_server")


def main():
    parser = argparse.ArgumentParser(description="LeadForge Webhook Server")
    parser.add_argument(
        "--port", type=int, default=8001,
        help="Puerto del servidor (default: 8001)"
    )
    args = parser.parse_args()

    # Crear directorio de logs si no existe
    Path("logs").mkdir(exist_ok=True)

    logger.info("=" * 50)
    logger.info("🌐 LeadForge Webhook Server")
    logger.info(f"   Puerto: {args.port}")
    logger.info(f"   Endpoint: POST /webhook/instantly")
    logger.info("=" * 50)

    # Verificar config
    from leadforge.config import cfg
    if not cfg.instantly_api_key:
        logger.warning("⚠️  INSTANTLY_API_KEY no configurado en .env")
    if not cfg.instantly_webhook_secret:
        logger.warning("⚠️  INSTANTLY_WEBHOOK_SECRET no configurado — aceptando sin firma (inseguro)")
    else:
        logger.info("✅ Firma HMAC configurada — solo acepta eventos de Instantly")

    if cfg.telegram_bot_token and cfg.telegram_master_chat_id:
        logger.info("✅ Telegram configurado — recibirás alertas")
    else:
        logger.warning("⚠️  Telegram no configurado — sin alertas")

    # Iniciar servidor
    from leadforge.monitor.reply_webhook import start_webhook_server
    start_webhook_server(port=args.port)


if __name__ == "__main__":
    main()
