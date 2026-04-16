"""
LeadForge — CLI de Lanzamiento de Campañas (Fase 3)
====================================================

Orquesta el pipeline completo de una campaña desde un archivo YAML de config.

Uso:
  python start_campaign.py --config campaign_configs/mi_campana.yaml
  python start_campaign.py --config campaign_configs/mi_campana.yaml --dry-run
  python start_campaign.py --config campaign_configs/mi_campana.yaml --solo-pipeline
  python start_campaign.py --config campaign_configs/mi_campana.yaml --solo-inyectar
  python start_campaign.py --config campaign_configs/mi_campana.yaml --solo-whatsapp
  python start_campaign.py --status

Ejemplos:
  # Correr todo el flujo (scraping + email + WhatsApp):
  python start_campaign.py --config campaign_configs/pinturas_monterrey.yaml

  # Solo probar sin guardar nada:
  python start_campaign.py --config campaign_configs/pinturas_monterrey.yaml --dry-run

  # Solo inyectar a Instantly.ai lo que ya está en DB (sin re-scraping):
  python start_campaign.py --config campaign_configs/pinturas_monterrey.yaml --solo-inyectar
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

# ─── Setup de logging ANTES de importar módulos internos ────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            f"logs/campaign_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("start_campaign")

# Crear directorio de logs si no existe
Path("logs").mkdir(exist_ok=True)

# ─── Importaciones del proyecto ─────────────────────────────────────────────
try:
    from leadforge.config import cfg
    from leadforge.pipeline import run_pipeline, PipelineStats
    from leadforge.supabase_client import get_db
    from leadforge.campaigns.account_manager import account_manager
    from leadforge.campaigns.instantly_manager import InstantlyManager, CampaignConfig
    from leadforge.campaigns.whatsapp_manager import whatsapp
    from leadforge.monitor.alerts import fire_alert, AlertSeverity
except ImportError as e:
    print(f"\n❌ Error al importar módulos de LeadForge: {e}")
    print("   Verifica que estás en la raíz del proyecto y que el .env está configurado.")
    sys.exit(1)


# ============================================================
# CARGA DE CONFIGURACIÓN YAML
# ============================================================

def load_config(config_path: str) -> dict:
    """Carga y valida el archivo YAML de configuración de la campaña."""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Archivo de configuración no encontrado: {config_path}")
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Error al parsear el YAML: {e}")
        sys.exit(1)

    # Validaciones básicas
    required_fields = [
        ("campana.nombre", lambda c: c.get("campana", {}).get("nombre")),
        ("producto.nombre_corto", lambda c: c.get("producto", {}).get("nombre_corto")),
        ("vendedor.nombre", lambda c: c.get("vendedor", {}).get("nombre")),
        ("vendedor.link_agenda", lambda c: c.get("vendedor", {}).get("link_agenda")),
        ("targeting.categorias", lambda c: c.get("targeting", {}).get("categorias")),
        ("targeting.ciudades", lambda c: c.get("targeting", {}).get("ciudades")),
    ]

    errores = []
    for field_name, getter in required_fields:
        if not getter(config):
            errores.append(f"  ✗ Campo requerido faltante: {field_name}")

    if errores:
        logger.error("Configuración inválida:\n" + "\n".join(errores))
        sys.exit(1)

    logger.info(f"✅ Config cargada: {config['campana']['nombre']}")
    return config


def update_config_metadata(config_path: str, config: dict) -> None:
    """Actualiza la metadata del archivo YAML después de cada ejecución."""
    try:
        config.setdefault("_meta", {})
        config["_meta"]["ultima_ejecucion"] = datetime.now().isoformat()
        config["_meta"]["total_ejecuciones"] = (
            config["_meta"].get("total_ejecuciones", 0) + 1
        )
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        logger.debug(f"No se pudo actualizar metadata del YAML: {e}")


# ============================================================
# FASE A: PIPELINE DE DATOS (Apify + Anymail + Supabase)
# ============================================================

async def run_data_pipeline(config: dict, dry_run: bool = False) -> PipelineStats:
    """
    Ejecuta el pipeline de scraping + enriquecimiento + validación + guardado.
    Para TODAS las categorías y ciudades definidas en el YAML.
    """
    campana_nombre = config["campana"]["nombre"]
    cliente_id = config["campana"].get("cliente_id") or cfg.cliente_id
    pipeline_cfg = config.get("pipeline", {})
    targeting = config["targeting"]

    logger.info("=" * 60)
    logger.info(f"  FASE A — PIPELINE DE DATOS")
    logger.info(f"  Campaña: {campana_nombre}")
    logger.info("=" * 60)

    stats_total = PipelineStats(
        terminos_procesados=0,
        negocios_encontrados=0,
        emails_validos=0,
        leads_db1=0,
        leads_db2=0,
        leads_descartados=0,
        costo_estimado_usd=0.0,
        errores=[],
    )

    ciudades = targeting["ciudades"]
    categorias = sorted(targeting["categorias"], key=lambda c: c.get("prioridad", 99))

    for categoria in categorias:
        terminos = categoria.get("sinonimos", [categoria["nombre"]])
        perfil = categoria.get("perfil_apify", "media_densidad")

        for ciudad in ciudades:
            logger.info(f"\n▶ Categoría: '{categoria['nombre']}' | Ciudad: {ciudad}")
            logger.info(f"  Términos: {terminos}")
            logger.info(f"  Perfil Apify: {perfil}")

            if dry_run:
                logger.info("  [DRY-RUN] Se omite la ejecución real.")
                continue

            try:
                stats = await run_pipeline(
                    terminos=terminos,
                    location=ciudad,
                    cliente_id=cliente_id,
                    perfil_apify=perfil,
                    force_scrape=pipeline_cfg.get("forzar_rescraping", False),
                    max_leads=pipeline_cfg.get("max_leads", 500),
                )

                # Acumular stats
                stats_total.terminos_procesados += stats.terminos_procesados
                stats_total.negocios_encontrados += stats.negocios_encontrados
                stats_total.emails_validos += stats.emails_validos
                stats_total.leads_db1 += stats.leads_db1
                stats_total.leads_db2 += stats.leads_db2
                stats_total.leads_descartados += stats.leads_descartados
                stats_total.costo_estimado_usd += stats.costo_estimado_usd
                stats_total.errores.extend(stats.errores)

                logger.info(
                    f"  ✅ Resultado: {stats.leads_db1} email | "
                    f"{stats.leads_db2} WA | "
                    f"~${stats.costo_estimado_usd:.2f} USD"
                )

                # Delay entre categorías para respetar rate limits
                delay = pipeline_cfg.get("delay_entre_categorias", 5)
                if delay > 0:
                    logger.info(f"  ⏱ Esperando {delay}s antes de la siguiente categoría...")
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"  ❌ Error en pipeline para '{categoria['nombre']}' / {ciudad}: {e}")
                stats_total.errores.append(str(e))

    logger.info("\n" + "=" * 60)
    logger.info("  RESUMEN FASE A")
    logger.info(f"  DB1 (Email):    {stats_total.leads_db1:>5} leads")
    logger.info(f"  DB2 (WhatsApp): {stats_total.leads_db2:>5} leads")
    logger.info(f"  Descartados:    {stats_total.leads_descartados:>5} leads")
    logger.info(f"  Costo total:    ${stats_total.costo_estimado_usd:.2f} USD")
    logger.info("=" * 60)

    return stats_total


# ============================================================
# FASE B: INYECCIÓN A INSTANTLY.AI
# ============================================================

async def run_injection(config: dict, dry_run: bool = False) -> dict:
    """
    Sincroniza cuentas de Instantly.ai y luego inyecta los leads de DB1
    de forma gradual (buffer_days × daily_limit).
    """
    instantly_cfg = config.get("instantly", {})
    cliente_id = config["campana"].get("cliente_id") or cfg.cliente_id
    filtros = config.get("filtros", {})
    vendedor = config["vendedor"]
    producto = config["producto"]

    logger.info("\n" + "=" * 60)
    logger.info("  FASE B — INYECCIÓN A INSTANTLY.AI")
    logger.info("=" * 60)

    # Sincronizar cuentas de email desde Instantly
    logger.info("▶ Sincronizando cuentas de email...")
    await account_manager.sync_from_instantly()
    logger.info(account_manager.get_status_report())

    if account_manager.total_available_today == 0:
        logger.warning("⚠️ No hay cuentas disponibles hoy. Todos los límites alcanzados.")
        return {"inyectados": 0, "error": "No hay cuentas disponibles"}

    # Preparar configuración de campaña de Instantly
    campaign_config = CampaignConfig(
        campaign_id=instantly_cfg.get("campaign_id", ""),
        campaign_name=instantly_cfg.get("campaign_name", config["campana"]["nombre"]),
        daily_limit=instantly_cfg.get("daily_limit", 100),
        from_name=vendedor["nombre"],
        from_email="",     # Instantly asigna automáticamente desde las cuentas rotadas
        reply_to="",
        subject_email1="",  # Se genera por Claude en email_builder
        subject_email2="",  # Vacío = mismo hilo
        producto=producto["nombre_corto"],
        producto_descripcion=producto["descripcion_completa"],
        beneficio_principal=producto["beneficio_principal"],
        beneficio_secundario=producto.get("beneficio_secundario", ""),
        vendedor=vendedor["nombre"],
        empresa=vendedor["empresa"],
        link_cal=vendedor["link_agenda"],
        oferta=producto.get("oferta_especial", ""),
    )

    # Obtener leads de DB1 pendientes de inyección
    db = get_db()
    lead_score_min = filtros.get("lead_score_minimo", 25)
    try:
        result = db.table("email_leads").select(
            "id, nombre_negocio, email, owner_name, categoria, ciudad, "
            "estado, hierarchy_score, lead_score"
        ).eq("cliente_id", cliente_id).eq("estado", "nuevo").gte(
            "lead_score", lead_score_min
        ).order("lead_score", desc=True).limit(1000).execute()

        db1_leads = result.data or []
        logger.info(f"▶ Leads en DB1 listos para inyectar: {len(db1_leads)}")
    except Exception as e:
        logger.error(f"Error obteniendo leads de DB1: {e}")
        return {"inyectados": 0, "error": str(e)}

    if not db1_leads:
        logger.info("  No hay leads nuevos para inyectar.")
        return {"inyectados": 0}

    if dry_run:
        logger.info(f"  [DRY-RUN] Se inyectarían {len(db1_leads)} leads (máx buffer).")
        return {"inyectados": 0, "dry_run": True}

    # Ejecutar inyección gradual
    instantly_mgr = InstantlyManager()
    result = await instantly_mgr.inject_leads_gradually(
        config=campaign_config,
        db_leads=db1_leads,
        account_mgr=account_manager,
        buffer_days=instantly_cfg.get("buffer_days", 3),
    )

    logger.info(f"\n  ✅ Inyectados: {result.get('inyectados', 0)} leads")
    logger.info(f"  En cola para mañana: {result.get('en_cola', 0)} leads")
    return result


# ============================================================
# FASE C: WHATSAPP (yCloud)
# ============================================================

async def run_whatsapp(config: dict, dry_run: bool = False) -> dict:
    """
    Envía mensajes de WhatsApp a leads de DB2 que cumplan los criterios.
    Solo contactar si: no respondió email en 3+ días Y score >= mínimo.
    """
    wa_cfg = config.get("whatsapp", {})
    cliente_id = config["campana"].get("cliente_id") or cfg.cliente_id
    vendedor = config["vendedor"]
    producto = config["producto"]

    if not wa_cfg.get("activo", True):
        logger.info("\n⏭ WhatsApp desactivado en esta campaña.")
        return {"enviados": 0, "desactivado": True}

    logger.info("\n" + "=" * 60)
    logger.info("  FASE C — WHATSAPP (yCloud)")
    logger.info("=" * 60)

    config_vars = {
        "vendedor": vendedor["nombre"],
        "empresa": vendedor["empresa"],
        "producto_corto": producto["nombre_corto"],
        "link_cal": vendedor["link_agenda"],
    }

    max_mensajes = wa_cfg.get("max_mensajes_por_dia", 50)
    score_min = wa_cfg.get("score_minimo", 40)

    # Preparar mensajes desde DB2
    mensajes = await whatsapp.prepare_messages_from_db(
        config_vars=config_vars,
        cliente_id=cliente_id,
        max_messages=max_mensajes,
    )

    logger.info(f"▶ Mensajes preparados: {len(mensajes)}")

    if not mensajes:
        logger.info("  No hay leads de WhatsApp pendientes.")
        return {"enviados": 0, "fallidos": 0}

    if dry_run:
        logger.info(f"  [DRY-RUN] Se enviarían {len(mensajes)} mensajes de WhatsApp.")
        for msg in mensajes[:3]:
            logger.info(f"  → {msg.to_phone} ({msg.nombre_negocio}): {msg.body[:60]}...")
        return {"enviados": 0, "dry_run": True}

    # Enviar lote
    delay_seg = wa_cfg.get("delay_entre_mensajes", 30)
    result = await whatsapp.send_batch(mensajes, delay_seconds=delay_seg)

    logger.info(f"\n  ✅ Enviados: {result['sent']} | Fallidos: {result['failed']}")
    return result


# ============================================================
# REPORTE FINAL
# ============================================================

async def send_final_report(
    config: dict,
    stats_pipeline: PipelineStats,
    stats_instantly: dict,
    stats_wa: dict,
    duracion_seg: float,
) -> None:
    """Envía reporte completo a Telegram al finalizar la campaña."""
    campana = config["campana"]["nombre"]
    minutos = duracion_seg / 60

    inyectados = stats_instantly.get("inyectados", 0)
    wa_enviados = stats_wa.get("enviados", 0)

    mensaje = (
        f"🚀 *CAMPAÑA COMPLETADA*\n\n"
        f"📋 *{campana}*\n"
        f"⏱ Duración: {minutos:.1f} minutos\n\n"
        f"📊 *PIPELINE DE DATOS*\n"
        f"  📧 DB1 (Email):    {stats_pipeline.leads_db1} leads nuevos\n"
        f"  📱 DB2 (WhatsApp): {stats_pipeline.leads_db2} leads nuevos\n"
        f"  🗑 Descartados:    {stats_pipeline.leads_descartados}\n"
        f"  💰 Costo aprox:    ${stats_pipeline.costo_estimado_usd:.2f} USD\n\n"
        f"📨 *INSTANTLY.AI*\n"
        f"  ✅ Leads inyectados: {inyectados}\n\n"
        f"📱 *WHATSAPP*\n"
        f"  ✅ Mensajes enviados: {wa_enviados}\n\n"
        f"{'⚠️ *ERRORES:* ' + str(len(stats_pipeline.errores)) if stats_pipeline.errores else '✅ Sin errores'}"
    )

    await fire_alert(
        tipo="campana_completada",
        mensaje=mensaje,
        severidad=AlertSeverity.INFO,
    )


# ============================================================
# COMANDO --STATUS
# ============================================================

async def show_status() -> None:
    """Muestra el estado general del sistema sin ejecutar ninguna campaña."""
    print("\n" + "=" * 65)
    print("  LEADFORGE — ESTADO DEL SISTEMA")
    print("=" * 65)

    # Estado de cuentas de email
    print("\n📧 CUENTAS DE EMAIL (Instantly.ai):")
    await account_manager.sync_from_instantly()
    print(account_manager.get_status_report())

    # Leads en base de datos
    print("\n📦 BASE DE DATOS (Supabase):")
    try:
        db = get_db()
        r1 = db.table("email_leads").select("id", count="exact").execute()
        r2 = db.table("social_leads").select("id", count="exact").execute()
        print(f"  DB1 (email_leads):  {r1.count:,} registros totales")
        print(f"  DB2 (social_leads): {r2.count:,} registros totales")

        nuevos = db.table("email_leads").select("id", count="exact").eq("estado", "nuevo").execute()
        print(f"  → Pendientes de inyectar a Instantly: {nuevos.count:,}")
    except Exception as e:
        print(f"  ❌ No se pudo conectar a Supabase: {e}")

    # Config actual
    print(f"\n⚙️  CONFIGURACIÓN:")
    print(f"  Cliente ID:         {cfg.cliente_id or '(no configurado)'}")
    print(f"  Anthropic API:      {'✅' if cfg.anthropic_api_key else '❌ Faltante'}")
    print(f"  Apify Token:        {'✅' if cfg.apify_token else '❌ Faltante'}")
    print(f"  Anymail API:        {'✅' if cfg.anymail_api_key else '❌ Faltante'}")
    print(f"  Instantly API:      {'✅' if cfg.instantly_api_key else '❌ Faltante'}")
    print(f"  yCloud API (WA):    {'✅' if cfg.ycloud_api_key else '⚠️ Opcional'}")
    print(f"  Telegram Bot:       {'✅' if cfg.telegram_bot_token else '⚠️ Opcional'}")
    print()


# ============================================================
# ENTRYPOINT PRINCIPAL
# ============================================================

async def main():
    parser = argparse.ArgumentParser(
        description="LeadForge — Lanzador de Campañas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--config", "-c",
        metavar="ARCHIVO.yaml",
        help="Ruta al archivo YAML de configuración de la campaña",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula la ejecución sin guardar datos ni enviar mensajes",
    )
    parser.add_argument(
        "--solo-pipeline",
        action="store_true",
        help="Solo ejecuta el pipeline de datos (sin Instantly ni WhatsApp)",
    )
    parser.add_argument(
        "--solo-inyectar",
        action="store_true",
        help="Solo inyecta leads ya procesados a Instantly.ai (sin re-scraping)",
    )
    parser.add_argument(
        "--solo-whatsapp",
        action="store_true",
        help="Solo envía los mensajes de WhatsApp pendientes",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Muestra el estado actual del sistema y sale",
    )

    args = parser.parse_args()

    # ── Mostrar estado y salir
    if args.status:
        await show_status()
        return

    # ── Verificar que se proporcionó un config
    if not args.config:
        parser.error("Se requiere --config ARCHIVO.yaml (o --status para ver el estado)")

    # ── Cargar configuración
    config = load_config(args.config)
    campana_nombre = config["campana"]["nombre"]

    if args.dry_run:
        logger.info("🧪 MODO DRY-RUN — No se guardarán datos ni se enviarán mensajes")

    start_time = datetime.now()
    logger.info(f"\n🚀 Iniciando campaña: {campana_nombre}")
    logger.info(f"   Fecha/hora: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Notificar inicio a Telegram
    if not args.dry_run:
        await fire_alert(
            tipo="campana_iniciada",
            mensaje=f"🚀 *Campaña iniciada:* _{campana_nombre}_",
            severidad=AlertSeverity.INFO,
        )

    stats_pipeline = PipelineStats(0, 0, 0, 0, 0, 0, 0.0, [])
    stats_instantly = {}
    stats_wa = {}

    try:
        # ── Fase A: Pipeline de datos
        if not args.solo_inyectar and not args.solo_whatsapp:
            stats_pipeline = await run_data_pipeline(config, dry_run=args.dry_run)

        # ── Fase B: Inyección a Instantly.ai
        if not args.solo_pipeline and not args.solo_whatsapp:
            stats_instantly = await run_injection(config, dry_run=args.dry_run)

        # ── Fase C: WhatsApp
        if not args.solo_pipeline and not args.solo_inyectar:
            stats_wa = await run_whatsapp(config, dry_run=args.dry_run)

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Campaña interrumpida por el usuario (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ Error fatal en la campaña: {e}", exc_info=True)
        if not args.dry_run:
            await fire_alert(
                tipo="campana_error",
                mensaje=f"❌ *Error en campaña* _{campana_nombre}_\n`{e}`",
                severidad=AlertSeverity.CRITICAL,
            )
        sys.exit(1)

    # ── Resumen final
    duracion = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n✅ Campaña completada en {duracion/60:.1f} minutos")

    if not args.dry_run:
        # Enviar reporte final a Telegram
        await send_final_report(
            config, stats_pipeline, stats_instantly, stats_wa, duracion
        )
        # Actualizar metadata del YAML
        update_config_metadata(args.config, config)


if __name__ == "__main__":
    # Verificar versión de Python
    if sys.version_info < (3, 10):
        print("❌ Python 3.10+ requerido. Versión actual: " + sys.version)
        sys.exit(1)

    asyncio.run(main())
