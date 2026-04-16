"""
LeadForge — Arranque de Fase 2 (Monitor + Telegram + Webhook)
Inicia todos los servicios de monitoreo simultáneamente:
  1. Health Daemon — checks cada 30 min
  2. Telegram Bot  — recibe comandos, envía alertas
  3. Webhook Server — recibe replies de Instantly.ai (puerto 8001)

Uso:
  python start_monitor.py           → Inicia todo
  python start_monitor.py --test    → Prueba de Telegram y un health check
  python start_monitor.py --webhook → Solo webhook server (para configurar ngrok)

Para que corra al iniciar el Mac Mini:
  Ver sección "Autostart en macOS" al final del archivo.
"""
import argparse
import asyncio
import logging
import signal
import sys
import threading
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent / "logs" / "monitor.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("leadforge.monitor")
(Path(__file__).parent / "logs").mkdir(exist_ok=True)


# ── Verificar configuración ───────────────────────────────────
def check_phase2_config() -> bool:
    from leadforge.config import cfg

    print("\n" + "=" * 50)
    print("LeadForge — Fase 2: Monitor + Telegram")
    print("=" * 50)

    checks = [
        ("TELEGRAM_BOT_TOKEN", cfg.telegram_bot_token),
        ("TELEGRAM_MASTER_CHAT_ID", cfg.telegram_master_chat_id),
        ("ANYMAIL_API_KEY", cfg.anymail_api_key),
    ]
    all_ok = True
    for name, value in checks:
        if value:
            masked = value[:8] + "..." if len(str(value)) > 8 else "***"
            print(f"  ✓ {name}: {masked}")
        else:
            print(f"  ✗ {name}: NO CONFIGURADO")
            all_ok = False

    # Opcionales (no bloquean el arranque)
    optional = [
        ("INSTANTLY_API_KEY", cfg.instantly_api_key),
        ("INSTANTLY_WEBHOOK_SECRET", cfg.instantly_webhook_secret),
    ]
    for name, value in optional:
        icon = "✓" if value else "○"
        print(f"  {icon} {name}: {'configurado' if value else 'opcional (no configurado)'}")

    return all_ok


# ── Webhook server en hilo separado ──────────────────────────
def start_webhook_in_thread(port: int = 8001) -> threading.Thread:
    """Inicia el servidor webhook en un hilo de fondo."""
    from leadforge.monitor.reply_webhook import start_webhook_server

    thread = threading.Thread(
        target=start_webhook_server,
        args=(port,),
        daemon=True,
        name="webhook-server",
    )
    thread.start()
    logger.info(f"🌐 Webhook server corriendo en http://0.0.0.0:{port}")
    logger.info(
        f"   Para recibir de Instantly.ai, configura ngrok:\n"
        f"   ngrok http {port}\n"
        f"   Luego pega la URL en Instantly → Settings → Webhooks"
    )
    return thread


# ── Aplicación principal ──────────────────────────────────────
async def run_all_services(webhook_port: int = 8001) -> None:
    """Corre todos los servicios async en paralelo."""
    from leadforge.config import cfg
    from leadforge.monitor.health_checker import health_daemon
    from leadforge.monitor.telegram_bot import build_application
    from leadforge.monitor.alerts import fire_alert, AlertSeverity

    # Iniciar health daemon
    health_daemon.start()

    # Alerta de inicio a Telegram
    await fire_alert(
        tipo="sistema_iniciado",
        mensaje=(
            "🚀 *LeadForge Monitor — Iniciado*\n\n"
            "✅ Health checks: cada 30 minutos\n"
            "✅ Bot de Telegram: activo\n"
            f"✅ Webhook server: puerto {webhook_port}\n\n"
            "Usa /ayuda para ver los comandos disponibles."
        ),
        severidad=AlertSeverity.INFO,
    )

    # Ejecutar un check inmediato al arrancar
    logger.info("Ejecutando health check inicial...")
    await health_daemon.run_once_now()

    # Iniciar Telegram bot (blocking — corre hasta Ctrl+C)
    logger.info("🤖 Iniciando Telegram bot...")
    bot_app = build_application()

    # Capturar señal de cierre — compatible con Windows y Unix
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Señal de cierre recibida")
        stop_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

    async with bot_app:
        await bot_app.start()
        await bot_app.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )

        logger.info("✅ Todos los servicios de Fase 2 corriendo")
        logger.info("   Ctrl+C para detener\n")

        # Esperar señal de cierre (en Windows Ctrl+C lanza KeyboardInterrupt)
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        # Cierre limpio
        logger.info("Cerrando servicios...")
        await bot_app.updater.stop()
        await bot_app.stop()
        health_daemon.stop()

    await fire_alert(
        tipo="sistema_detenido",
        mensaje="⏹️ *LeadForge Monitor — Detenido limpiamente*",
        severidad=AlertSeverity.INFO,
    )


# ── Entry point ───────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="LeadForge Monitor (Fase 2)")
    parser.add_argument("--test", action="store_true", help="Prueba de Telegram y health check")
    parser.add_argument("--webhook", action="store_true", help="Solo webhook server")
    parser.add_argument("--port", type=int, default=8001, help="Puerto del webhook (default: 8001)")
    args = parser.parse_args()

    # ── Modo test ──────────────────────────────────────────────
    if args.test:
        from leadforge.monitor.alerts import send_telegram
        from leadforge.monitor.health_checker import health_daemon

        print("\n🧪 Modo prueba:")
        print("  1. Enviando mensaje de prueba a Telegram...")
        ok = await send_telegram(
            "🧪 *LeadForge — Prueba de conexión exitosa*\n"
            "El sistema de alertas funciona correctamente."
        )
        print(f"     Telegram: {'✅ OK' if ok else '❌ FALLÓ — revisa TELEGRAM_BOT_TOKEN y CHAT_ID'}")

        print("  2. Ejecutando health checks...")
        await health_daemon.run_once_now()
        print("     ✅ Checks completados — revisa tu Telegram")
        return

    # ── Verificar config ───────────────────────────────────────
    if not check_phase2_config():
        print("\n❌ Configuración incompleta. Revisa .env")
        sys.exit(1)

    # ── Solo webhook ───────────────────────────────────────────
    if args.webhook:
        print(f"\n🌐 Iniciando solo webhook server en puerto {args.port}")
        from leadforge.monitor.reply_webhook import start_webhook_server
        start_webhook_server(args.port)  # blocking
        return

    # ── Todos los servicios ────────────────────────────────────
    start_webhook_in_thread(args.port)
    await run_all_services(args.port)


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================
# AUTOSTART EN MACOS (Mac Mini)
# Para que LeadForge Monitor arranque automáticamente al encender:
#
# 1. Crear el archivo LaunchAgent:
#    mkdir -p ~/Library/LaunchAgents
#    nano ~/Library/LaunchAgents/com.leadforge.monitor.plist
#
# 2. Contenido del .plist:
# <?xml version="1.0" encoding="UTF-8"?>
# <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
#   "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
# <plist version="1.0">
# <dict>
#   <key>Label</key>
#   <string>com.leadforge.monitor</string>
#   <key>ProgramArguments</key>
#   <array>
#     <string>/usr/bin/python3</string>
#     <string>/Users/TU_USUARIO/LeadForge/start_monitor.py</string>
#   </array>
#   <key>RunAtLoad</key>
#   <true/>
#   <key>KeepAlive</key>
#   <true/>
#   <key>StandardOutPath</key>
#   <string>/Users/TU_USUARIO/LeadForge/logs/monitor.log</string>
#   <key>StandardErrorPath</key>
#   <string>/Users/TU_USUARIO/LeadForge/logs/monitor_error.log</string>
# </dict>
# </plist>
#
# 3. Activar:
#    launchctl load ~/Library/LaunchAgents/com.leadforge.monitor.plist
#
# 4. Para detener:
#    launchctl unload ~/Library/LaunchAgents/com.leadforge.monitor.plist
# ============================================================
