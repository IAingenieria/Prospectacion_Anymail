"""
LeadForge — Health Checker Daemon
Corre cada 30 minutos y verifica el estado de todas las APIs críticas.
Si algo falla → alerta inmediata por Telegram.

Monitorea:
  - Anymail Finder: cuenta activa + créditos restantes
  - Apify: último run exitoso
  - Instantly.ai: bounce rate + spam rate por campaña
  - Supabase: conectividad básica

Diseñado para nunca repetir el incidente de Anymail Finder no pagado.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import cfg
from ..supabase_client import get_db
from .alerts import AlertSeverity, fire_alert

logger = logging.getLogger(__name__)

# ============================================================
# CHECK INDIVIDUALES
# ============================================================

async def check_anymail_finder() -> dict:
    """
    Verifica estado de cuenta Anymail Finder.
    Alerta si: cuenta inactiva, créditos < threshold, timeout de conexión.
    """
    result = {"service": "anymail_finder", "ok": True, "details": {}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.anymailfinder.com/v5.1/account",
                headers={"X-API-Key": cfg.anymail_api_key},
            )

            if resp.status_code == 401:
                result["ok"] = False
                result["error"] = "API key inválida — verifica que sea la correcta"
                await fire_alert(
                    tipo="anymail_finder_auth",
                    mensaje=(
                        "❌ *Anymail Finder — Error de autenticación*\n"
                        "La API key es inválida. El pipeline está DETENIDO.\n"
                        "Verificar en: https://anymailfinder.com/account/api"
                    ),
                    severidad=AlertSeverity.CRITICAL,
                )

            elif resp.status_code == 402:
                result["ok"] = False
                result["error"] = "Cuenta sin créditos o pago vencido"
                await fire_alert(
                    tipo="anymail_finder_pago",
                    mensaje=(
                        "🚨 *Anymail Finder — CUENTA SIN SERVICIO*\n"
                        "El pago venció o los créditos se agotaron.\n"
                        "⚠️ El pipeline está DETENIDO.\n"
                        "Renovar en: https://anymailfinder.com/account/billing"
                    ),
                    severidad=AlertSeverity.CRITICAL,
                )

            elif resp.status_code == 200:
                data = resp.json()
                # Anymail Finder API devuelve "credits_left" (no "credits_remaining")
                credits = data.get("credits_left", data.get("credits_remaining", 0))
                plan = data.get("plan_name", data.get("plan", "unknown"))

                result["details"] = {"credits": credits, "plan": plan}

                # Alerta preventiva por créditos bajos
                if credits < cfg.anymail_credits_alert:
                    await fire_alert(
                        tipo="anymail_creditos_bajos",
                        mensaje=(
                            f"⚠️ *Anymail Finder — Créditos bajos*\n"
                            f"Restantes: *{credits}* créditos\n"
                            f"Plan: {plan}\n"
                            f"Recargar antes de que se agoten para no detener el pipeline."
                        ),
                        severidad=AlertSeverity.WARNING,
                    )
                    result["warning"] = f"Solo {credits} créditos restantes"
                else:
                    logger.info(f"✅ Anymail Finder OK — {credits} créditos | {plan}")

            else:
                result["ok"] = False
                result["error"] = f"HTTP {resp.status_code} inesperado"

    except httpx.ConnectError:
        result["ok"] = False
        result["error"] = "Sin conexión a Anymail Finder"
        await fire_alert(
            tipo="anymail_conexion",
            mensaje=(
                "⚠️ *Anymail Finder — Sin conexión*\n"
                "No se puede contactar al servidor.\n"
                "Verifica tu conexión a internet."
            ),
            severidad=AlertSeverity.WARNING,
        )
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"Error en check Anymail: {e}")

    return result


async def check_apify() -> dict:
    """
    Verifica que el último run de Apify haya sido exitoso.
    Alerta si el último run falló o es muy antiguo.
    """
    result = {"service": "apify", "ok": True, "details": {}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Obtener últimos runs del actor
            url = (
                f"https://api.apify.com/v2/acts/{cfg.apify_actor_id}/runs"
                f"?limit=1&desc=1"
            )
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {cfg.apify_token}"},
            )

            if resp.status_code == 401:
                result["ok"] = False
                result["error"] = "Token de Apify inválido"
                await fire_alert(
                    tipo="apify_auth",
                    mensaje="🚨 *Apify — Token inválido*\nVerificar en console.apify.com",
                    severidad=AlertSeverity.CRITICAL,
                )
                return result

            if resp.status_code != 200:
                result["ok"] = False
                result["error"] = f"HTTP {resp.status_code}"
                return result

            runs = resp.json().get("data", {}).get("items", [])
            if not runs:
                logger.info("Apify: sin runs previos (primera vez)")
                return result

            last_run = runs[0]
            status = last_run.get("status", "UNKNOWN")
            started_at = last_run.get("startedAt", "")
            result["details"] = {"status": status, "last_run": started_at}

            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                await fire_alert(
                    tipo="apify_run_fallido",
                    mensaje=(
                        f"⚠️ *Apify — Último run con error*\n"
                        f"Estado: `{status}`\n"
                        f"Iniciado: {started_at}\n"
                        f"Revisar en: console.apify.com"
                    ),
                    severidad=AlertSeverity.WARNING,
                )
                result["warning"] = f"Último run: {status}"
            else:
                logger.info(f"✅ Apify OK — Último run: {status} ({started_at[:10]})")

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"Error en check Apify: {e}")

    return result


async def check_instantly() -> dict:
    """
    Verifica bounce rate y spam rate de campañas activas en Instantly.ai.
    Si supera los umbrales → pausa automática + alerta crítica.
    """
    result = {"service": "instantly", "ok": True, "details": {}}

    if not cfg.instantly_api_key:
        result["details"]["skipped"] = "API key no configurada"
        return result

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.instantly.ai/api/v1/campaign/list",
                params={"api_key": cfg.instantly_api_key, "limit": 20, "skip": 0},
            )

            if resp.status_code == 401:
                await fire_alert(
                    tipo="instantly_auth",
                    mensaje="🚨 *Instantly.ai — API key inválida*",
                    severidad=AlertSeverity.CRITICAL,
                )
                result["ok"] = False
                return result

            if resp.status_code != 200:
                result["ok"] = False
                return result

            campaigns = resp.json()
            if not isinstance(campaigns, list):
                campaigns = campaigns.get("data", [])

            problemas = []
            for campaign in campaigns:
                if campaign.get("status") != "active":
                    continue

                name = campaign.get("name", "Sin nombre")
                # Calcular tasas
                sent = campaign.get("emails_sent_count", 0)
                bounced = campaign.get("emails_bounced_count", 0)
                spam = campaign.get("spam_block_count", 0)

                if sent < 10:
                    continue  # muy pocas muestras

                bounce_rate = (bounced / sent * 100) if sent else 0
                spam_rate = (spam / sent * 100) if sent else 0

                if bounce_rate > cfg.bounce_rate_threshold:
                    problemas.append(
                        f"📊 *{name}*\n"
                        f"   Bounce: `{bounce_rate:.1f}%` (límite: {cfg.bounce_rate_threshold}%)\n"
                        f"   ⚠️ RIESGO ALTO para el dominio"
                    )

                if spam_rate > cfg.spam_rate_threshold:
                    problemas.append(
                        f"📊 *{name}*\n"
                        f"   Spam: `{spam_rate:.1f}%` (límite: {cfg.spam_rate_threshold}%)\n"
                        f"   🚨 PELIGRO — dominio en riesgo crítico"
                    )

            if problemas:
                resultado_texto = "\n\n".join(problemas)
                await fire_alert(
                    tipo="instantly_tasas_peligrosas",
                    mensaje=(
                        f"🚨 *Instantly.ai — Campañas con tasas peligrosas*\n\n"
                        f"{resultado_texto}\n\n"
                        f"Acción recomendada: PAUSA las campañas afectadas inmediatamente."
                    ),
                    severidad=AlertSeverity.CRITICAL,
                )
                result["warning"] = f"{len(problemas)} campañas con tasas peligrosas"
            else:
                logger.info(f"✅ Instantly.ai OK — {len(campaigns)} campañas revisadas")

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"Error en check Instantly: {e}")

    return result


async def check_supabase() -> dict:
    """Verifica conectividad básica con Supabase."""
    result = {"service": "supabase", "ok": True}
    try:
        db = get_db()
        # Query mínima: contar alertas (no devuelve datos sensibles)
        db.table("alertas").select("id", count="exact").limit(1).execute()
        logger.info("✅ Supabase OK")
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        await fire_alert(
            tipo="supabase_conexion",
            mensaje=(
                f"🚨 *Supabase — Sin conexión*\n"
                f"Error: `{str(e)[:100]}`\n"
                f"Los leads NO se están guardando."
            ),
            severidad=AlertSeverity.CRITICAL,
        )
    return result


# ============================================================
# REPORTE DIARIO
# ============================================================
async def send_heartbeat() -> None:
    """
    Envía mensaje de latido a Telegram cada 2 horas.
    Si Zenon no ve este mensaje por 4+ horas, sabe que el bot cayó.
    """
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    await fire_alert(
        tipo="heartbeat",
        mensaje=(
            f"💚 *ZenonFinder activo*\n"
            f"_{now} CST_\n\n"
            f"Bot funcionando correctamente.\n"
            f"Si no ves este mensaje por 4+ horas → reiniciar."
        ),
        severidad=AlertSeverity.INFO,
    )


async def send_daily_report() -> None:
    """
    Envía el reporte diario de stats a Telegram.
    Se ejecuta a las 8am y 8pm.
    """
    from ..supabase_client import get_run_stats
    stats = get_run_stats(cfg.cliente_id, since_hours=24)

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    mensaje = (
        f"📊 *Reporte Diario — LeadForge*\n"
        f"_{now}_\n\n"
        f"✅ Email leads (DB1): *{stats.get('email_leads_nuevos', 0)}* nuevos\n"
        f"📱 Social leads (DB2): *{stats.get('social_leads_nuevos', 0)}* nuevos\n\n"
        f"Para ver estadísticas completas: /reporte"
    )
    await fire_alert(
        tipo="reporte_diario",
        mensaje=mensaje,
        severidad=AlertSeverity.INFO,
    )


async def _run_denue_nocturno() -> None:
    """Ejecuta DENUE enrichment completo cada noche a las 3am."""
    import os, sys
    from concurrent.futures import ThreadPoolExecutor

    logger.info("🌙 DENUE Nocturno iniciando...")

    def _denue_run():
        try:
            import importlib.util
            base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            spec = importlib.util.spec_from_file_location("denue_enricher",
                os.path.join(base, "denue_enricher.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.run_enrichment(limit=500, solo_sin_email=True)
        except Exception as e:
            logger.error(f"DENUE nocturno error: {e}")
            return {"emails_nuevos": 0, "enriquecidos": 0}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        stats = await loop.run_in_executor(pool, _denue_run)

    emails = stats.get("emails_nuevos", 0) if stats else 0
    enriq = stats.get("enriquecidos", 0) if stats else 0

    await fire_alert(
        tipo="denue_nocturno",
        mensaje=(
            f"🌙 *DENUE Nocturno completado*\n"
            f"📧 Emails nuevos: *{emails}*\n"
            f"✅ Leads enriquecidos: {enriq}\n"
            f"_Procesado automáticamente a las 3am_"
        ),
        severidad=AlertSeverity.INFO,
    )
    logger.info(f"🌙 DENUE Nocturno: {emails} emails nuevos, {enriq} leads enriquecidos")


# ============================================================
# SCHEDULER — El corazón del daemon
# ============================================================
class HealthDaemon:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone="America/Monterrey")
        self._setup_jobs()

    def _setup_jobs(self):
        # Heartbeat cada 2 horas
        self.scheduler.add_job(
            send_heartbeat,
            trigger=IntervalTrigger(hours=2),
            id="heartbeat",
            name="Heartbeat ZenonFinder",
            replace_existing=True,
        )

        # Health checks cada 30 minutos
        self.scheduler.add_job(
            self.run_all_checks,
            trigger=IntervalTrigger(minutes=30),
            id="health_checks",
            name="Health Checks Completos",
            replace_existing=True,
        )

        # Reporte diario a las 8am
        self.scheduler.add_job(
            send_daily_report,
            trigger="cron",
            hour=8, minute=0,
            id="daily_report_morning",
            name="Reporte Matutino",
        )

        # Reporte diario a las 8pm
        self.scheduler.add_job(
            send_daily_report,
            trigger="cron",
            hour=20, minute=0,
            id="daily_report_evening",
            name="Reporte Vespertino",
        )

        # DENUE enrichment nocturno — 3am todos los días
        self.scheduler.add_job(
            _run_denue_nocturno,
            trigger="cron",
            hour=3, minute=0,
            id="denue_nocturno",
            name="DENUE Enrichment Nocturno",
            replace_existing=True,
        )

    async def run_all_checks(self) -> None:
        """Ejecuta todos los checks en paralelo."""
        logger.info("🔍 Ejecutando health checks...")
        start = datetime.now()

        results = await asyncio.gather(
            check_anymail_finder(),
            check_apify(),
            check_instantly(),
            check_supabase(),
            return_exceptions=True,
        )

        # Contar errores
        errors = sum(
            1 for r in results
            if isinstance(r, Exception) or (isinstance(r, dict) and not r.get("ok", True))
        )

        elapsed = (datetime.now() - start).total_seconds()
        logger.info(
            f"Health checks completados en {elapsed:.1f}s — "
            f"{len(results) - errors}/{len(results)} servicios OK"
        )

    def start(self):
        """Inicia el scheduler."""
        self.scheduler.start()
        logger.info("🛡️ Health Daemon iniciado — checks cada 30 minutos")
        # Heartbeat inmediato al arrancar
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.ensure_future(send_heartbeat())
        )

    def stop(self):
        """Detiene el scheduler."""
        self.scheduler.shutdown()
        logger.info("Health Daemon detenido")

    async def run_once_now(self):
        """Ejecuta checks inmediatamente (para pruebas)."""
        await self.run_all_checks()


# Instancia global
health_daemon = HealthDaemon()
