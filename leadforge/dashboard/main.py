"""
LeadForge — Dashboard Web (Fase 4)
===================================
Servidor FastAPI que expone:
  - Archivos estáticos HTML/CSS/JS del dashboard
  - REST API para todos los datos del sistema
  - Endpoint SSE para progreso en tiempo real de campañas
  - Integración con Claude AI para el Campaign Wizard

Puerto: 5000 (configurable)
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import cfg
from ..supabase_client import get_db
from ..campaigns.account_manager import account_manager
from ..campaigns.instantly_manager import InstantlyManager, CampaignConfig
from ..campaigns.whatsapp_manager import whatsapp
from ..monitor.alerts import fire_alert, AlertSeverity
from .category_ai import expand_categories, estimate_campaign_cost
from .cost_tracker import get_dashboard_stats, get_weekly_costs, get_monthly_costs

logger = logging.getLogger(__name__)

# ── Directorio de estáticos ─────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="LeadForge Dashboard",
    description="Sistema de generación de leads B2B con IA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos (CSS, JS, imágenes)
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

# ── Cola de tareas en background ────────────────────────────────────────────
_campaign_tasks: dict[str, dict] = {}  # task_id → {status, progress, logs, result}


def _update_task(task_id: str, **kwargs) -> None:
    if task_id in _campaign_tasks:
        _campaign_tasks[task_id].update(kwargs)
        _campaign_tasks[task_id]["updated_at"] = datetime.utcnow().isoformat()


# ============================================================
# PÁGINAS HTML
# ============================================================

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/wizard")
async def wizard():
    return FileResponse(str(STATIC_DIR / "wizard.html"))

@app.get("/cuentas")
async def cuentas():
    return FileResponse(str(STATIC_DIR / "accounts.html"))

@app.get("/reportes")
async def reportes():
    return FileResponse(str(STATIC_DIR / "reports.html"))


# ============================================================
# API — ESTADO DEL SISTEMA
# ============================================================

@app.get("/api/status")
async def get_status():
    """Estado general del sistema: APIs, base de datos, cuentas."""
    status = {
        "timestamp": datetime.utcnow().isoformat(),
        "apis": {
            "anthropic": bool(cfg.anthropic_api_key),
            "apify": bool(cfg.apify_token),
            "anymail": bool(cfg.anymail_api_key),
            "instantly": bool(cfg.instantly_api_key),
            "ycloud": bool(cfg.ycloud_api_key),
            "telegram": bool(cfg.telegram_bot_token),
        },
        "supabase": False,
        "cuentas_activas": 0,
        "emails_disponibles_hoy": 0,
    }

    # Verificar Supabase
    try:
        db = get_db()
        db.table("email_leads").select("id").limit(1).execute()
        status["supabase"] = True
    except Exception:
        status["supabase"] = False

    # Estado de cuentas
    try:
        if account_manager.accounts:
            activas = sum(1 for a in account_manager.accounts.values() if a.is_available)
            disponibles = account_manager.total_available_today
            status["cuentas_activas"] = activas
            status["emails_disponibles_hoy"] = disponibles
    except Exception:
        pass

    return status


@app.get("/api/dashboard/stats")
async def dashboard_stats(cliente_id: Optional[str] = None):
    """Stats principales para las tarjetas del dashboard."""
    try:
        return get_dashboard_stats(cliente_id)
    except Exception as e:
        logger.error(f"Error obteniendo stats: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# API — CUENTAS DE EMAIL
# ============================================================

@app.get("/api/accounts")
async def get_accounts(sync: bool = False):
    """Lista todas las cuentas de Instantly.ai con su estado actual."""
    try:
        if sync or not account_manager.accounts:
            await account_manager.sync_from_instantly()

        accounts_list = []
        for acc in account_manager.accounts.values():
            accounts_list.append({
                "email": acc.email,
                "daily_limit": acc.daily_limit,
                "sent_today": acc.sent_today,
                "remaining_today": acc.remaining_today,
                "usage_percent": round(acc.usage_percent, 1),
                "status": acc.status,
                "bounce_rate": round(acc.bounce_rate, 2),
                "spam_rate": round(acc.spam_rate, 3),
                "is_available": acc.is_available,
                "health_emoji": acc.health_emoji,
            })

        accounts_list.sort(key=lambda a: a["email"])

        return {
            "accounts": accounts_list,
            "total_sent_today": sum(a["sent_today"] for a in accounts_list),
            "total_limit_today": sum(a["daily_limit"] for a in accounts_list),
            "total_remaining": sum(a["remaining_today"] for a in accounts_list),
            "active_count": sum(1 for a in accounts_list if a["is_available"]),
        }
    except Exception as e:
        logger.error(f"Error obteniendo cuentas: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/accounts/report")
async def accounts_report():
    """Reporte en texto de todas las cuentas."""
    await account_manager.sync_from_instantly()
    return {"report": account_manager.get_status_report()}


# ============================================================
# API — LEADS
# ============================================================

@app.get("/api/leads/stats")
async def leads_stats(cliente_id: Optional[str] = None):
    """Estadísticas de leads en DB1 y DB2."""
    cid = cliente_id or cfg.cliente_id
    db = get_db()

    try:
        # DB1
        r1 = db.table("email_leads").select("estado, lead_score, categoria").eq(
            "cliente_id", cid
        ).execute()
        leads_email = r1.data or []

        by_status = {}
        by_category = {}
        scores = []
        for lead in leads_email:
            est = lead.get("estado", "desconocido")
            by_status[est] = by_status.get(est, 0) + 1
            cat = lead.get("categoria", "Sin categoría")
            by_category[cat] = by_category.get(cat, 0) + 1
            if lead.get("lead_score"):
                scores.append(lead["lead_score"])

        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        # DB2
        r2 = db.table("social_leads").select("estado, canal_asignado").eq(
            "cliente_id", cid
        ).execute()
        leads_social = r2.data or []
        by_canal = {}
        for lead in leads_social:
            canal = lead.get("canal_asignado", "desconocido")
            by_canal[canal] = by_canal.get(canal, 0) + 1

        return {
            "db1": {
                "total": len(leads_email),
                "por_estado": by_status,
                "por_categoria": dict(
                    sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:10]
                ),
                "score_promedio": avg_score,
            },
            "db2": {
                "total": len(leads_social),
                "por_canal": by_canal,
            },
        }
    except Exception as e:
        logger.error(f"Error en leads stats: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/leads/recent")
async def leads_recent(cliente_id: Optional[str] = None, limit: int = 20):
    """Últimos leads agregados."""
    cid = cliente_id or cfg.cliente_id
    db = get_db()
    try:
        result = db.table("email_leads").select(
            "id, nombre_negocio, email, categoria, ciudad, lead_score, estado, created_at"
        ).eq("cliente_id", cid).order("created_at", desc=True).limit(limit).execute()
        return {"leads": result.data or []}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# API — ALERTAS
# ============================================================

@app.get("/api/alerts")
async def get_alerts(limite: int = 20, cliente_id: Optional[str] = None):
    """Últimas alertas del sistema."""
    cid = cliente_id or cfg.cliente_id
    db = get_db()
    try:
        result = db.table("alertas").select(
            "tipo, mensaje, severidad, creado_en"
        ).eq("cliente_id", cid).order("creado_en", desc=True).limit(limite).execute()
        return {"alertas": result.data or []}
    except Exception as e:
        # La tabla puede no existir aún — no es crítico
        return {"alertas": []}


# ============================================================
# API — COSTOS
# ============================================================

@app.get("/api/costs/weekly")
async def costs_weekly(cliente_id: Optional[str] = None):
    """Resumen de costos de los últimos 7 días."""
    try:
        return get_weekly_costs(cliente_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/costs/monthly")
async def costs_monthly(cliente_id: Optional[str] = None):
    """Resumen de costos de los últimos 30 días."""
    try:
        return get_monthly_costs(cliente_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# API — CAMPAIGN WIZARD (IA)
# ============================================================

class WizardRequest(BaseModel):
    product: str
    known_buyers: str = ""
    ciudad: str
    cliente_id: Optional[str] = None


@app.post("/api/wizard/analyze")
async def wizard_analyze(req: WizardRequest):
    """
    Llama a Claude para expandir las categorías de compradores.
    El núcleo del Campaign Wizard.
    """
    if not req.product or len(req.product.strip()) < 10:
        raise HTTPException(400, "Describe el producto con al menos 10 caracteres.")
    if not req.ciudad:
        raise HTTPException(400, "Especifica una ciudad.")

    try:
        categories = await expand_categories(
            product=req.product.strip(),
            known_buyers=req.known_buyers.strip(),
            ciudad=req.ciudad.strip(),
            cliente_id=req.cliente_id,
        )
        return {
            "categorias": categories,
            "total": len(categories),
            "en_cache": sum(1 for c in categories if c["ya_en_cache"]),
            "nuevas": sum(1 for c in categories if not c["ya_en_cache"]),
        }
    except Exception as e:
        logger.error(f"Error en wizard analyze: {e}")
        raise HTTPException(500, f"Error al analizar categorías: {e}")


class CostEstimateRequest(BaseModel):
    categorias: list[dict]
    ciudades: list[str]


@app.post("/api/wizard/estimate-cost")
async def wizard_estimate_cost(req: CostEstimateRequest):
    """Estima el costo de scraping para las categorías seleccionadas."""
    return estimate_campaign_cost(req.categorias, req.ciudades)


# ============================================================
# API — LANZAMIENTO DE CAMPAÑA
# ============================================================

class LaunchRequest(BaseModel):
    # Datos del wizard
    product: str
    known_buyers: str = ""
    ciudades: list[str]
    categorias_seleccionadas: list[dict]

    # Datos del vendedor
    vendedor_nombre: str
    empresa: str
    link_agenda: str

    # Config de Instantly
    daily_limit: int = 100
    buffer_days: int = 3
    campaign_name: str = ""

    # Opciones
    activar_whatsapp: bool = True
    cliente_id: Optional[str] = None


@app.post("/api/campaign/launch")
async def launch_campaign(req: LaunchRequest, background_tasks: BackgroundTasks):
    """
    Lanza el pipeline completo en background.
    Retorna un task_id para consultar el progreso vía SSE.
    """
    task_id = str(uuid.uuid4())[:8]
    _campaign_tasks[task_id] = {
        "status": "iniciando",
        "progress": 0,
        "logs": [],
        "result": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    # Notificar inicio
    campana_nombre = req.campaign_name or f"Campaña {datetime.now().strftime('%d/%m %H:%M')}"
    await fire_alert(
        tipo="campana_iniciada",
        mensaje=f"🚀 *Campaña iniciada desde dashboard:* _{campana_nombre}_",
        severidad=AlertSeverity.INFO,
    )

    # Lanzar en background
    background_tasks.add_task(
        _run_campaign_background,
        task_id=task_id,
        req=req,
        campana_nombre=campana_nombre,
    )

    return {"task_id": task_id, "status": "iniciado"}


async def _run_campaign_background(task_id: str, req: LaunchRequest, campana_nombre: str):
    """Ejecuta el pipeline completo en background y actualiza el task state."""
    from ..pipeline import run_pipeline

    logs = []

    def log(msg: str):
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        _update_task(task_id, logs=logs[-50:])  # Mantener últimos 50 logs
        logger.info(f"[Campaign {task_id}] {msg}")

    try:
        cliente_id = req.cliente_id or cfg.cliente_id
        total_cats = len(req.categorias_seleccionadas)
        total_leads_db1 = 0
        total_leads_db2 = 0
        total_costo = 0.0

        _update_task(task_id, status="pipeline", progress=5)
        log(f"Iniciando campaña: {campana_nombre}")
        log(f"Categorías: {total_cats} | Ciudades: {len(req.ciudades)}")

        # ── Fase A: Pipeline de datos ────────────────────────────────
        for i, cat in enumerate(req.categorias_seleccionadas):
            terminos = cat.get("sinonimos_google_maps", [cat["nombre_busqueda"]])

            for ciudad in req.ciudades:
                log(f"Scraping: '{cat['nombre_busqueda']}' en {ciudad.split(',')[0]}")

                try:
                    stats = await run_pipeline(
                        terminos=terminos,
                        location=ciudad,
                        cliente_id=cliente_id,
                        max_places=50,
                        force_scrape=False,
                    )
                    total_leads_db1 += stats.leads_db1
                    total_leads_db2 += stats.leads_db2
                    total_costo += stats.costo_estimado_usd

                    log(
                        f"  ✅ {stats.leads_db1} email | "
                        f"{stats.leads_db2} WA | "
                        f"~${stats.costo_estimado_usd:.2f}"
                    )
                except Exception as e:
                    log(f"  ❌ Error: {e}")

            progreso = 10 + int((i + 1) / total_cats * 50)
            _update_task(task_id, progress=progreso)

        log(f"Pipeline completado: {total_leads_db1} leads DB1 | {total_leads_db2} DB2")

        # ── Fase B: Inyección a Instantly.ai ────────────────────────
        _update_task(task_id, status="inyectando", progress=65)
        log("Sincronizando cuentas de Instantly.ai...")

        await account_manager.sync_from_instantly()
        disponibles = account_manager.total_available_today
        log(f"Cuentas activas: {disponibles} emails disponibles hoy")

        if disponibles > 0:
            campaign_config = CampaignConfig(
                campaign_id="",
                campaign_name=campana_nombre,
                daily_limit=req.daily_limit,
                from_name=req.vendedor_nombre,
                from_email="",
                reply_to="",
                subject_email1="",
                subject_email2="",
                producto=req.product[:100],
                producto_descripcion=req.product,
                beneficio_principal="",
                beneficio_secundario="",
                vendedor=req.vendedor_nombre,
                empresa=req.empresa,
                link_cal=req.link_agenda,
                oferta="",
            )

            db = get_db()
            leads_result = db.table("email_leads").select(
                "id, nombre_negocio, email, owner_name, categoria, ciudad, "
                "estado, hierarchy_score, lead_score"
            ).eq("cliente_id", cliente_id).eq("estado", "nuevo").gte(
                "lead_score", 25
            ).order("lead_score", desc=True).limit(req.daily_limit * req.buffer_days).execute()

            db1_leads = leads_result.data or []
            log(f"Leads listos para inyectar: {len(db1_leads)}")

            instantly_mgr = InstantlyManager()
            inj_result = await instantly_mgr.inject_leads_gradually(
                config=campaign_config,
                db_leads=db1_leads,
                account_mgr=account_manager,
                buffer_days=req.buffer_days,
            )
            log(f"✅ Inyectados a Instantly: {inj_result.get('inyectados', 0)} leads")
        else:
            log("⚠️ No hay cuentas disponibles hoy en Instantly.ai")

        # ── Fase C: WhatsApp ─────────────────────────────────────────
        _update_task(task_id, status="whatsapp", progress=85)
        if req.activar_whatsapp:
            log("Enviando mensajes de WhatsApp...")
            config_vars = {
                "vendedor": req.vendedor_nombre,
                "empresa": req.empresa,
                "producto_corto": req.product[:80],
                "link_cal": req.link_agenda,
            }
            mensajes = await whatsapp.prepare_messages_from_db(
                config_vars=config_vars,
                cliente_id=cliente_id,
                max_messages=50,
            )
            if mensajes:
                wa_result = await whatsapp.send_batch(mensajes, delay_seconds=30)
                log(f"✅ WhatsApp: {wa_result['sent']} enviados | {wa_result['failed']} fallidos")
            else:
                log("Sin mensajes de WhatsApp pendientes.")

        # ── Finalizar ────────────────────────────────────────────────
        result = {
            "leads_db1": total_leads_db1,
            "leads_db2": total_leads_db2,
            "costo_usd": round(total_costo, 2),
        }
        _update_task(task_id, status="completado", progress=100, result=result)
        log(f"🎉 Campaña completada. Costo: ~${total_costo:.2f} USD")

        await fire_alert(
            tipo="campana_completada",
            mensaje=(
                f"✅ *Campaña completada:* _{campana_nombre}_\n"
                f"📧 DB1: {total_leads_db1} leads\n"
                f"📱 DB2: {total_leads_db2} leads\n"
                f"💰 ~${total_costo:.2f} USD"
            ),
            severidad=AlertSeverity.INFO,
        )

    except Exception as e:
        logger.error(f"Error fatal en campaña {task_id}: {e}", exc_info=True)
        _update_task(task_id, status="error", progress=0)
        logs.append(f"❌ ERROR FATAL: {e}")
        _update_task(task_id, logs=logs)


@app.get("/api/campaign/{task_id}/status")
async def campaign_task_status(task_id: str):
    """Estado actual de una campaña en ejecución."""
    task = _campaign_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Tarea no encontrada")
    return task


@app.get("/api/campaign/{task_id}/stream")
async def campaign_stream(task_id: str):
    """Server-Sent Events: stream de logs de la campaña en tiempo real."""
    async def event_generator():
        last_log_count = 0
        max_wait = 600  # 10 minutos máximo
        waited = 0

        while waited < max_wait:
            task = _campaign_tasks.get(task_id)
            if not task:
                yield "data: {\"error\": \"Tarea no encontrada\"}\n\n"
                break

            logs = task.get("logs", [])
            new_logs = logs[last_log_count:]
            if new_logs:
                for log_line in new_logs:
                    data = json.dumps({
                        "log": log_line,
                        "status": task["status"],
                        "progress": task["progress"],
                    })
                    yield f"data: {data}\n\n"
                last_log_count = len(logs)

            if task["status"] in ("completado", "error"):
                final = json.dumps({"done": True, "result": task.get("result"), "status": task["status"]})
                yield f"data: {final}\n\n"
                break

            await asyncio.sleep(1)
            waited += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================
# API — REPORTES
# ============================================================

@app.get("/api/reports/weekly")
async def reports_weekly(cliente_id: Optional[str] = None):
    """Reporte semanal completo."""
    cid = cliente_id or cfg.cliente_id
    try:
        costos = get_weekly_costs(cid)
        db = get_db()

        # Respuestas de la semana
        from datetime import timedelta
        hace_7 = (datetime.utcnow() - timedelta(days=7)).isoformat()
        resp = db.table("email_leads").select("id", count="exact").eq(
            "cliente_id", cid
        ).eq("respondio_email", True).gte("fecha_respuesta", hace_7).execute()

        return {
            "periodo": "Últimos 7 días",
            "costos": costos,
            "respuestas": resp.count or 0,
            "generado_en": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "LeadForge Dashboard", "version": "1.0.0"}
