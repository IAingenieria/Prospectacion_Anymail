"""
LeadForge — Lanzador Maestro (1 comando = todo el sistema)
============================================================

Inicia los TRES servicios simultáneamente:
  1. Dashboard Web   → http://localhost:5000
  2. Monitor         → Telegram bot + health checks (cada 30 min)
  3. Webhook Server  → http://localhost:8001/webhook/instantly

Uso:
  python start_all.py                    # Modo normal
  python start_all.py --no-monitor       # Solo dashboard (sin Telegram)
  python start_all.py --port 8080        # Dashboard en puerto diferente
  python start_all.py --dev             # Con hot-reload (desarrollo)

El sistema se detiene completamente con Ctrl+C.
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# ── Setup de logging ─────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/leadforge_system.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("start_all")

# ── Verificar Python ──────────────────────────────────────────────────────────
if sys.version_info < (3, 10):
    print("❌ Python 3.10+ requerido.")
    sys.exit(1)


def print_banner(dashboard_port: int, webhook_port: int, monitor: bool) -> None:
    os.system("clear" if os.name != "nt" else "cls")
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║        🚀  LEADFORGE — Sistema de Leads B2B          ║")
    print("  ║           Plataforma SaaS de Lead Generation          ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  🌐  Dashboard:       http://localhost:{dashboard_port}")
    print(f"  🧙  Wizard (IA):     http://localhost:{dashboard_port}/wizard")
    print(f"  📧  Cuentas Email:   http://localhost:{dashboard_port}/cuentas")
    print(f"  📊  Reportes:        http://localhost:{dashboard_port}/reportes")
    print(f"  📚  API Docs:        http://localhost:{dashboard_port}/docs")
    if monitor:
        print(f"  🔗  Webhook:         http://localhost:{webhook_port}/webhook/instantly")
        print(f"  🤖  Telegram Bot:    Activo (polling)")
        print(f"  🔍  Health checks:   Cada 30 minutos")
    print()
    print("  ─────────────────────────────────────────────────────")
    print()
    _show_config_status()
    print()
    print("  Presiona Ctrl+C para detener todos los servicios")
    print()


def _show_config_status() -> None:
    """Muestra el estado de las APIs configuradas."""
    try:
        from leadforge.config import cfg
        apis = {
            "Supabase": bool(cfg.supabase_url and cfg.supabase_service_key),
            "Claude (IA)": bool(cfg.anthropic_api_key),
            "Apify": bool(cfg.apify_token),
            "Anymail Finder": bool(cfg.anymail_api_key),
            "Instantly.ai": bool(cfg.instantly_api_key),
            "Telegram Bot": bool(cfg.telegram_bot_token),
            "yCloud (WA)": bool(cfg.ycloud_api_key),
        }
        for nombre, ok in apis.items():
            icon = "  ✅" if ok else "  ⚠️ "
            estado = "Configurado" if ok else "Faltante en .env"
            print(f"  {icon}  {nombre:<18} {estado}")
    except Exception as e:
        print(f"  ⚠️  No se pudo leer config: {e}")


# ═══════════════════════════════════════════════════════════════
# HILOS DE SERVICIO
# ═══════════════════════════════════════════════════════════════

_stop_event = threading.Event()


def run_dashboard(port: int, reload: bool = False) -> None:
    """Corre el servidor FastAPI del dashboard (hilo principal de uvicorn)."""
    try:
        import uvicorn
        uvicorn.run(
            "leadforge.dashboard.main:app",
            host="0.0.0.0",
            port=port,
            log_level="warning",
            reload=reload,
            reload_dirs=["leadforge"] if reload else None,
        )
    except Exception as e:
        logger.error(f"Dashboard falló: {e}")
        _stop_event.set()


def run_webhook_server(port: int) -> None:
    """Corre el webhook FastAPI para recibir eventos de Instantly.ai."""
    try:
        from leadforge.monitor.reply_webhook import start_webhook_server
        start_webhook_server(port)
    except Exception as e:
        logger.warning(f"Webhook server no pudo iniciar: {e}")


def run_monitor() -> None:
    """Corre el Telegram bot + health daemon en un loop asyncio propio."""
    try:
        import asyncio
        from leadforge.monitor.health_checker import health_daemon
        from leadforge.monitor.telegram_bot import run_bot

        # Iniciar health daemon (APScheduler — no requiere asyncio)
        health_daemon.start()
        logger.info("🔍 Health daemon activo (checks cada 30 min)")

        # Iniciar Telegram bot (requiere asyncio)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())
    except Exception as e:
        logger.warning(f"Monitor (Telegram) no pudo iniciar: {e}")
        logger.info("   El sistema funciona sin el monitor.")


def fire_startup_alert(dashboard_port: int, webhook_port: int) -> None:
    """Envía alerta a Telegram indicando que el sistema arrancó."""
    try:
        import asyncio
        from leadforge.monitor.alerts import fire_alert, AlertSeverity

        async def _alert():
            await fire_alert(
                tipo="sistema_iniciado",
                mensaje=(
                    f"🚀 *LeadForge iniciado*\n\n"
                    f"🌐 Dashboard: `http://localhost:{dashboard_port}`\n"
                    f"🔗 Webhook: `http://localhost:{webhook_port}`\n\n"
                    f"Todos los servicios activos ✅"
                ),
                severidad=AlertSeverity.INFO,
            )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_alert())
        loop.close()
    except Exception as e:
        logger.debug(f"No se pudo enviar alerta de inicio: {e}")


# ═══════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LeadForge — Lanzador Maestro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--port", "-p", type=int, default=5000, help="Puerto del dashboard (default: 5000)")
    parser.add_argument("--webhook-port", type=int, default=8001, help="Puerto del webhook (default: 8001)")
    parser.add_argument("--no-monitor", action="store_true", help="No iniciar Telegram bot ni health checks")
    parser.add_argument("--dev", action="store_true", help="Modo desarrollo (hot-reload)")
    args = parser.parse_args()

    monitor_activo = not args.no_monitor
    print_banner(args.port, args.webhook_port, monitor_activo)

    threads: list[threading.Thread] = []

    # ── Hilo 1: Webhook server (Instantly.ai events) ──────────────────
    if monitor_activo:
        t_webhook = threading.Thread(
            target=run_webhook_server,
            args=(args.webhook_port,),
            daemon=True,
            name="webhook",
        )
        t_webhook.start()
        threads.append(t_webhook)
        time.sleep(1)  # Esperar que el webhook arranque
        logger.info(f"🔗 Webhook server → puerto {args.webhook_port}")

    # ── Hilo 2: Monitor (Telegram bot + health daemon) ────────────────
    if monitor_activo:
        t_monitor = threading.Thread(
            target=run_monitor,
            daemon=True,
            name="monitor",
        )
        t_monitor.start()
        threads.append(t_monitor)
        logger.info("🤖 Monitor iniciado (Telegram bot + health daemon)")

    # ── Alerta de inicio ──────────────────────────────────────────────
    if monitor_activo:
        t_alert = threading.Thread(
            target=fire_startup_alert,
            args=(args.port, args.webhook_port),
            daemon=True,
            name="startup-alert",
        )
        t_alert.start()

    # ── Hilo principal: Dashboard (uvicorn) ───────────────────────────
    logger.info(f"🌐 Iniciando dashboard en http://localhost:{args.port}")
    try:
        run_dashboard(args.port, reload=args.dev)
    except KeyboardInterrupt:
        pass

    # ── Apagado limpio ────────────────────────────────────────────────
    logger.info("\n⛔ Deteniendo LeadForge...")
    _stop_event.set()

    try:
        from leadforge.monitor.health_checker import health_daemon
        health_daemon.stop()
    except Exception:
        pass

    logger.info("✅ Sistema detenido correctamente. ¡Hasta pronto!")


if __name__ == "__main__":
    # Capturar Ctrl+C limpiamente en Windows
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
