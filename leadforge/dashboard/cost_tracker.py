"""
LeadForge — Cost Tracker
========================
Calcula y rastrea el costo real de cada búsqueda y campaña.
Fuentes: busquedas_cache (Supabase) + datos de pipeline.
"""
import logging
from datetime import datetime, timedelta

from ..config import cfg
from ..supabase_client import get_db

logger = logging.getLogger(__name__)


def get_weekly_costs(cliente_id: str = None) -> dict:
    """
    Retorna el resumen de costos de los últimos 7 días.
    Lee de la tabla busquedas_cache donde se almacena el costo estimado.
    """
    cid = cliente_id or cfg.cliente_id
    db = get_db()
    hace_7_dias = (datetime.utcnow() - timedelta(days=7)).isoformat()

    try:
        result = db.table("busquedas_cache").select(
            "termino_busqueda, ciudad, total_resultados, resultados_validos, "
            "creado_en, costo_apify_usd, costo_anymail_usd"
        ).eq("cliente_id", cid).gte("creado_en", hace_7_dias).order(
            "creado_en", desc=True
        ).execute()

        rows = result.data or []
    except Exception as e:
        logger.error(f"Error obteniendo costos semanales: {e}")
        return _empty_costs()

    total_apify = sum(r.get("costo_apify_usd") or 0 for r in rows)
    total_anymail = sum(r.get("costo_anymail_usd") or 0 for r in rows)
    total_leads = sum(r.get("total_resultados") or 0 for r in rows)
    total_validos = sum(r.get("resultados_validos") or 0 for r in rows)

    # Agrupar por categoría
    por_categoria: dict[str, dict] = {}
    for r in rows:
        cat = r.get("termino_busqueda", "Desconocida")
        if cat not in por_categoria:
            por_categoria[cat] = {"leads": 0, "validos": 0, "costo": 0.0}
        por_categoria[cat]["leads"] += r.get("total_resultados") or 0
        por_categoria[cat]["validos"] += r.get("resultados_validos") or 0
        por_categoria[cat]["costo"] += (
            (r.get("costo_apify_usd") or 0) + (r.get("costo_anymail_usd") or 0)
        )

    # Calcular costo por lead para cada categoría
    tabla_categorias = []
    for cat, data in por_categoria.items():
        cpl = round(data["costo"] / data["validos"], 4) if data["validos"] > 0 else 0
        tabla_categorias.append({
            "categoria": cat,
            "leads": data["leads"],
            "validos": data["validos"],
            "costo_usd": round(data["costo"], 2),
            "costo_por_lead": cpl,
        })

    tabla_categorias.sort(key=lambda x: x["costo_por_lead"])

    total_usd = total_apify + total_anymail
    cpl_promedio = round(total_usd / total_validos, 4) if total_validos > 0 else 0

    return {
        "periodo_dias": 7,
        "total_busquedas": len(rows),
        "total_leads": total_leads,
        "leads_validos": total_validos,
        "apify_usd": round(total_apify, 2),
        "anymail_usd": round(total_anymail, 2),
        "total_usd": round(total_usd, 2),
        "costo_por_lead": cpl_promedio,
        "meta_costo_por_lead": 0.10,   # objetivo < $0.10
        "por_categoria": tabla_categorias,
    }


def get_monthly_costs(cliente_id: str = None) -> dict:
    """Costos de los últimos 30 días."""
    cid = cliente_id or cfg.cliente_id
    db = get_db()
    hace_30_dias = (datetime.utcnow() - timedelta(days=30)).isoformat()

    try:
        result = db.table("busquedas_cache").select(
            "total_resultados, resultados_validos, costo_apify_usd, costo_anymail_usd"
        ).eq("cliente_id", cid).gte("creado_en", hace_30_dias).execute()

        rows = result.data or []
    except Exception as e:
        logger.error(f"Error obteniendo costos mensuales: {e}")
        return _empty_costs()

    total_apify = sum(r.get("costo_apify_usd") or 0 for r in rows)
    total_anymail = sum(r.get("costo_anymail_usd") or 0 for r in rows)
    total_validos = sum(r.get("resultados_validos") or 0 for r in rows)
    total_usd = total_apify + total_anymail

    return {
        "periodo_dias": 30,
        "total_busquedas": len(rows),
        "leads_validos": total_validos,
        "total_usd": round(total_usd, 2),
        "costo_por_lead": round(total_usd / total_validos, 4) if total_validos > 0 else 0,
    }


def get_dashboard_stats(cliente_id: str = None) -> dict:
    """
    Stats completas para el dashboard principal.
    Combina datos de email_leads, social_leads y busquedas_cache.
    """
    cid = cliente_id or cfg.cliente_id
    db = get_db()

    stats = {
        "email_leads_total": 0,
        "email_leads_nuevos": 0,
        "email_leads_en_campana": 0,
        "social_leads_total": 0,
        "social_leads_pendientes": 0,
        "respuestas_hoy": 0,
        "costos_semana": 0.0,
        "costo_por_lead": 0.0,
        "cuentas_activas": 0,
        "emails_enviados_hoy": 0,
    }

    try:
        # DB1: email leads — total exacto + conteos por estado
        r_total = db.table("email_leads").select("id", count="exact").eq("cliente_id", cid).execute()
        stats["email_leads_total"] = r_total.count or 0

        r_nuevos = db.table("email_leads").select("id", count="exact").eq(
            "cliente_id", cid).eq("email_status", "unverified").execute()
        stats["email_leads_nuevos"] = r_nuevos.count or 0

        r_campana = db.table("email_leads").select("id", count="exact").eq(
            "cliente_id", cid).eq("email_status", "valid").execute()
        stats["email_leads_en_campana"] = r_campana.count or 0
    except Exception as e:
        logger.debug(f"Error contando email_leads: {e}")

    try:
        # DB2: social leads — total exacto + pendientes
        r2_total = db.table("social_leads").select("id", count="exact").eq("cliente_id", cid).execute()
        stats["social_leads_total"] = r2_total.count or 0

        r2_pend = db.table("social_leads").select("id", count="exact").eq(
            "cliente_id", cid).eq("estado_campania", "pendiente").execute()
        stats["social_leads_pendientes"] = r2_pend.count or 0
    except Exception as e:
        logger.debug(f"Error contando social_leads: {e}")

    try:
        # Respuestas hoy
        hoy = datetime.utcnow().strftime("%Y-%m-%d")
        r3 = db.table("email_leads").select("id", count="exact").eq(
            "cliente_id", cid
        ).eq("respondio_email", True).gte("fecha_respuesta", hoy).execute()
        stats["respuestas_hoy"] = r3.count or 0
    except Exception as e:
        logger.debug(f"Error contando respuestas: {e}")

    try:
        # Costos de esta semana
        costos = get_weekly_costs(cid)
        stats["costos_semana"] = costos["total_usd"]
        stats["costo_por_lead"] = costos["costo_por_lead"]
    except Exception as e:
        logger.debug(f"Error obteniendo costos: {e}")

    return stats


def _empty_costs() -> dict:
    return {
        "periodo_dias": 7,
        "total_busquedas": 0,
        "total_leads": 0,
        "leads_validos": 0,
        "apify_usd": 0.0,
        "anymail_usd": 0.0,
        "total_usd": 0.0,
        "costo_por_lead": 0.0,
        "meta_costo_por_lead": 0.10,
        "por_categoria": [],
    }
