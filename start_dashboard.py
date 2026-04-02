"""
LeadForge — Dashboard Web (Fase 4)
====================================

Inicia el servidor del dashboard en http://localhost:5000

Uso:
  python start_dashboard.py              # Solo dashboard
  python start_dashboard.py --with-monitor  # Dashboard + Monitor + Webhook
  python start_dashboard.py --port 8080  # Puerto personalizado

El dashboard incluye:
  /           → Dashboard principal (estadísticas en tiempo real)
  /wizard     → Campaign Wizard con Claude IA
  /cuentas    → Gestión de cuentas Instantly.ai
  /reportes   → Reportes de costos y ROI

API REST:
  /api/status             → Estado del sistema
  /api/dashboard/stats    → KPIs principales
  /api/accounts           → Cuentas de email
  /api/leads/stats        → Estadísticas de leads
  /api/costs/weekly       → Costos semanales
  /api/wizard/analyze     → Expansión de categorías con Claude
  /api/campaign/launch    → Lanzar campaña desde wizard
  /api/campaign/{id}/stream → SSE: progreso en tiempo real
"""
import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path

# ─── Configurar logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("start_dashboard")

# Crear directorio de logs si no existe
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

# ─── Verificar Python ───────────────────────────────────────────────────────
if sys.version_info < (3, 10):
    print("❌ Python 3.10+ requerido.")
    sys.exit(1)

# ─── Importar módulos ───────────────────────────────────────────────────────
try:
    import uvicorn
    from leadforge.config import cfg
    from leadforge.dashboard.main import app as dashboard_app
except ImportError as e:
    print(f"\n❌ Error al importar módulos: {e}")
    print("   Asegúrate de haber instalado: pip install -r requirements.txt")
    sys.exit(1)


def start_monitor_in_background(webhook_port: int = 8001) -> None:
    """Inicia el monitor (Telegram bot + health checker + webhook) en un thread."""
    try:
        from leadforge.monitor.health_checker import health_daemon
        from leadforge.monitor.reply_webhook import start_webhook_server

        # Webhook en su propio thread
        webhook_thread = threading.Thread(
            target=start_webhook_server,
            args=(webhook_port,),
            daemon=True,
            name="webhook-server",
        )
        webhook_thread.start()
        logger.info(f"🌐 Webhook server iniciado en puerto {webhook_port}")

        # Health daemon
        health_daemon.start()
        logger.info("🔍 Health daemon iniciado (cada 30 min)")

    except Exception as e:
        logger.warning(f"Monitor no pudo iniciar: {e} — el dashboard funciona sin él.")


def print_banner(port: int, with_monitor: bool) -> None:
    """Muestra el banner de inicio."""
    print("\n" + "=" * 60)
    print("  🚀  LEADFORGE — Sistema de Lead Generation B2B con IA")
    print("=" * 60)
    print(f"\n  Dashboard:     http://localhost:{port}")
    print(f"  Wizard (IA):   http://localhost:{port}/wizard")
    print(f"  Cuentas:       http://localhost:{port}/cuentas")
    print(f"  Reportes:      http://localhost:{port}/reportes")
    print(f"  API Docs:      http://localhost:{port}/docs")
    if with_monitor:
        print(f"  Webhook:       http://localhost:8001/webhook/instantly")
    print()
    print(f"  Cliente ID:    {cfg.cliente_id or '⚠️ No configurado'}")
    print(f"  Supabase:      {'✅ Configurado' if cfg.supabase_url else '❌ Faltante'}")
    print(f"  Claude API:    {'✅ Configurado' if cfg.anthropic_api_key else '❌ Faltante'}")
    print(f"  Instantly:     {'✅ Configurado' if cfg.instantly_api_key else '⚠️ Opcional'}")
    print(f"  Monitor:       {'✅ Activo' if with_monitor else '⏭ Desactivado'}")
    print()
    print("  Presiona Ctrl+C para detener")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="LeadForge — Servidor del Dashboard Web",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--port", "-p", type=int, default=5000, help="Puerto del dashboard (default: 5000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--with-monitor", action="store_true", help="Iniciar también el monitor y webhook")
    parser.add_argument("--reload", action="store_true", help="Auto-reload en cambios de código (dev)")
    args = parser.parse_args()

    print_banner(args.port, args.with_monitor)

    # Iniciar monitor si se solicitó
    if args.with_monitor:
        start_monitor_in_background(webhook_port=8001)

    # Iniciar dashboard
    uvicorn.run(
        "leadforge.dashboard.main:app",
        host=args.host,
        port=args.port,
        log_level="warning",
        reload=args.reload,
        reload_dirs=["leadforge"] if args.reload else None,
    )


if __name__ == "__main__":
    main()
