"""
LeadForge — Cliente de Supabase
Maneja la inserción y consulta de leads en DB1 (email) y DB2 (social).
Incluye caché de búsquedas para evitar pagos duplicados a Apify.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from supabase import create_client, Client

from .config import cfg

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Crea cliente Supabase con Service Key (bypasea RLS para escritura del backend)."""
    return create_client(cfg.supabase_url, cfg.supabase_service_key)


# Instancia lazy
_supabase: Optional[Client] = None


def get_db() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = _get_client()
    return _supabase


# ============================================================
# CACHÉ DE BÚSQUEDAS
# ============================================================
@dataclass
class CacheResult:
    action: str          # "REUSE" | "PARTIAL" | "SCRAPE"
    total_leads: int = 0
    dias_desde_ultimo: int = 0
    mensaje: str = ""


def check_search_cache(
    termino: str,
    ciudad: str,
    cliente_id: str,
    pais: str = "Mexico",
) -> CacheResult:
    """
    Consulta la caché LOCAL de búsquedas en Supabase.
    Retorna si debemos reusar, hacer scraping parcial o total.
    """
    db = get_db()

    try:
        result = db.table("busquedas_cache").select(
            "total_resultados, leads_validos, scraped_at, expira_at"
        ).eq("termino_busqueda", termino).eq("ciudad", ciudad).eq(
            "cliente_id", cliente_id
        ).eq("pais", pais).order("scraped_at", desc=True).limit(1).execute()

        if not result.data:
            return CacheResult(action="SCRAPE", mensaje="Sin datos previos")

        cache = result.data[0]
        scraped_at = datetime.fromisoformat(cache["scraped_at"].replace("Z", "+00:00"))
        expira_at = datetime.fromisoformat(cache["expira_at"].replace("Z", "+00:00"))
        now = datetime.now(scraped_at.tzinfo)
        dias = (now - scraped_at).days

        if now < expira_at and cache["total_resultados"] > 30:
            return CacheResult(
                action="REUSE",
                total_leads=cache["leads_validos"],
                dias_desde_ultimo=dias,
                mensaje=f"✅ Cache válido: {cache['leads_validos']} leads (hace {dias} días)",
            )
        else:
            return CacheResult(
                action="SCRAPE",
                total_leads=cache["total_resultados"],
                dias_desde_ultimo=dias,
                mensaje=f"⏰ Cache expirado (hace {dias} días) — re-scraping",
            )

    except Exception as e:
        logger.error(f"Error consultando caché: {e}")
        return CacheResult(action="SCRAPE", mensaje=f"Error de caché: {e}")


def save_search_cache(
    termino: str,
    ciudad: str,
    cliente_id: str,
    total_resultados: int,
    leads_validos: int,
    costo_apify: float = 0.0,
    costo_anymail: int = 0,
    perfil_apify: str = "",
    pais: str = "Mexico",
) -> None:
    """Guarda o actualiza la entrada de caché después de un scraping."""
    db = get_db()
    expira_at = (datetime.utcnow() + timedelta(days=cfg.cache_expiry_days)).isoformat()

    try:
        db.table("busquedas_cache").upsert({
            "termino_busqueda": termino,
            "ciudad": ciudad,
            "pais": pais,
            "cliente_id": cliente_id,
            "perfil_apify": perfil_apify,
            "total_resultados": total_resultados,
            "leads_validos": leads_validos,
            "costo_apify_usd": costo_apify,
            "costo_anymail_creditos": costo_anymail,
            "expira_at": expira_at,
        }, on_conflict="termino_busqueda,ciudad,pais,cliente_id").execute()
    except Exception as e:
        logger.error(f"Error guardando caché: {e}")


# ============================================================
# DB1: LEADS DE EMAIL
# ============================================================
def get_existing_emails(cliente_id: str) -> set[str]:
    """Obtiene todos los emails activos del cliente (para deduplicación)."""
    db = get_db()
    try:
        result = db.table("email_leads").select("email").eq(
            "cliente_id", cliente_id
        ).eq("do_not_contact", False).execute()
        return {row["email"].lower() for row in result.data}
    except Exception as e:
        logger.error(f"Error obteniendo emails existentes: {e}")
        return set()


def insert_email_lead(
    cliente_id: str,
    nombre_negocio: str,
    email: str,
    email_status: str,
    hierarchy_score: int,
    lead_score: int,
    categoria: str,
    ciudad: str,
    estado: str,
    sitio_web: Optional[str],
    telefono: Optional[str],
    direccion: Optional[str],
    owner_name: Optional[str],
    cargo_inferido: Optional[str],
    rating: Optional[float],
    review_count: Optional[int],
    responds_to_reviews: bool,
    facebook_url: Optional[str],
    instagram_url: Optional[str],
    apify_run_id: str,
    perfil_apify: str,
    termino_busqueda: str,
    pais: str = "Mexico",
) -> Optional[str]:
    """
    Inserta un lead validado en DB1 (email_leads).
    Devuelve el ID del registro creado o None si falló.
    """
    db = get_db()
    try:
        result = db.table("email_leads").insert({
            "cliente_id": cliente_id,
            "nombre_negocio": nombre_negocio,
            "email": email,
            "email_status": email_status,
            "hierarchy_score": hierarchy_score,
            "lead_score": lead_score,
            "categoria": categoria,
            "ciudad": ciudad,
            "estado": estado,
            "pais": pais,
            "sitio_web": sitio_web,
            "telefono": telefono,
            "direccion_completa": direccion,
            "owner_name": owner_name,
            "cargo_inferido": cargo_inferido,
            "rating": rating,
            "review_count": review_count,
            "responds_to_reviews": responds_to_reviews,
            "facebook_url": facebook_url,
            "instagram_url": instagram_url,
            "apify_run_id": apify_run_id,
            "perfil_apify": perfil_apify,
            "termino_busqueda": termino_busqueda,
        }).execute()

        if result.data:
            return result.data[0]["id"]
        return None

    except Exception as e:
        # Manejar duplicado de email silenciosamente
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug(f"Email duplicado ignorado: {email}")
        else:
            logger.error(f"Error insertando lead de email: {e}")
        return None


# ============================================================
# DB2: LEADS DE WHATSAPP/SOCIAL
# ============================================================
def insert_social_lead(
    cliente_id: str,
    nombre_negocio: str,
    telefono: Optional[str],
    facebook_url: Optional[str],
    instagram_handle: Optional[str],
    categoria: str,
    ciudad: str,
    owner_name: Optional[str],
    actividad_digital_score: int,
    email_lead_id: Optional[str] = None,
    seguidores_facebook: Optional[int] = None,
    seguidores_instagram: Optional[int] = None,
    dias_ultimo_post: Optional[int] = None,
) -> Optional[str]:
    """
    Inserta un lead en DB2 (social_leads) para WhatsApp/Social Media.
    """
    db = get_db()

    # Decidir canal según datos disponibles
    canal = None
    if telefono:
        canal = "whatsapp"
    elif facebook_url:
        canal = "facebook_dm"
    elif instagram_handle:
        canal = "instagram_dm"

    if not canal:
        return None  # Sin canal disponible

    try:
        result = db.table("social_leads").insert({
            "cliente_id": cliente_id,
            "email_lead_id": email_lead_id,
            "nombre_negocio": nombre_negocio,
            "categoria": categoria,
            "ciudad": ciudad,
            "telefono": telefono,
            "facebook_url": facebook_url,
            "instagram_handle": instagram_handle,
            "seguidores_facebook": seguidores_facebook,
            "seguidores_instagram": seguidores_instagram,
            "dias_ultimo_post": dias_ultimo_post,
            "actividad_digital_score": actividad_digital_score,
            "owner_name": owner_name,
            "canal_asignado": canal,
        }).execute()

        if result.data:
            return result.data[0]["id"]
        return None

    except Exception as e:
        logger.error(f"Error insertando lead social: {e}")
        return None


# ============================================================
# LEADS MASTER — TABLA UNIFICADA (BIG ONE + EMBUDO)
# ============================================================
def get_existing_names(cliente_id: str) -> set[str]:
    """Obtiene nombres de negocios ya guardados (para deduplicación en leads_master)."""
    db = get_db()
    try:
        result = db.table("leads_master").select("nombre_negocio,ciudad").eq(
            "cliente_id", cliente_id
        ).execute()
        return {f"{r['nombre_negocio'].lower()}|{(r['ciudad'] or '').lower()}" for r in result.data}
    except Exception as e:
        logger.error(f"Error obteniendo nombres existentes: {e}")
        return set()


def insert_lead_master(
    cliente_id: str,
    nombre_negocio: str,
    # Datos Apify
    categoria: Optional[str],
    ciudad: Optional[str],
    estado: Optional[str],
    pais: str = "MX",
    direccion: Optional[str] = None,
    sitio_web: Optional[str] = None,
    telefono: Optional[str] = None,
    facebook_url: Optional[str] = None,
    instagram_url: Optional[str] = None,
    rating: Optional[float] = None,
    review_count: Optional[int] = None,
    google_maps_url: Optional[str] = None,
    apify_run_id: Optional[str] = None,
    termino_busqueda: Optional[str] = None,
    # Anymail
    email: Optional[str] = None,
    email_status: Optional[str] = None,
    hierarchy_score: int = 0,
    anymail_procesado: bool = False,
    # Owner
    owner_name: Optional[str] = None,
    cargo_inferido: Optional[str] = None,
    # Score
    lead_score: int = 0,
    canal_recomendado: Optional[str] = None,
    actividad_digital_score: int = 0,
) -> Optional[str]:
    """
    Inserta un lead en la tabla unificada leads_master.
    Hace UPSERT por nombre_negocio+ciudad+cliente_id para evitar duplicados.
    Devuelve el ID del registro o None si falló.
    """
    db = get_db()

    # Determinar canal recomendado si no viene
    if not canal_recomendado:
        if email and email_status == "valid":
            canal_recomendado = "email"
        elif telefono:
            canal_recomendado = "whatsapp"
        elif facebook_url:
            canal_recomendado = "facebook_dm"
        elif instagram_url:
            canal_recomendado = "instagram_dm"

    try:
        result = db.table("leads_master").upsert({
            "cliente_id": cliente_id,
            "nombre_negocio": nombre_negocio,
            "categoria": categoria,
            "ciudad": ciudad,
            "estado": estado,
            "pais": pais,
            "direccion": direccion,
            "sitio_web": sitio_web,
            "telefono": telefono,
            "facebook_url": facebook_url,
            "instagram_url": instagram_url,
            "rating": rating,
            "review_count": review_count,
            "google_maps_url": google_maps_url,
            "apify_run_id": apify_run_id,
            "termino_busqueda": termino_busqueda,
            "email": email,
            "email_status": email_status,
            "hierarchy_score": hierarchy_score,
            "owner_name": owner_name,
            "cargo_inferido": cargo_inferido,
            "lead_score": lead_score,
            "canal_recomendado": canal_recomendado,
            "verificado": False,
            "calidad_stars": 1,
            "etapa": "nuevo",
        }, on_conflict="nombre_negocio,ciudad,cliente_id").execute()

        if result.data:
            logger.info(f"✅ leads_master: {nombre_negocio} | score:{lead_score} | canal:{canal_recomendado}")
            return result.data[0]["id"]
        return None

    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug(f"Duplicado ignorado: {nombre_negocio} en {ciudad}")
        else:
            logger.error(f"Error insertando en leads_master: {nombre_negocio} — {e}")
        return None


# ============================================================
# ACTUALIZACIÓN DE LEADS (post-DENUE, post-Apify, post-Anymail)
# ============================================================

def update_lead_apify_data(
    nombre_negocio: str,
    ciudad: str,
    cliente_id: str,
    facebook_url: Optional[str] = None,
    instagram_url: Optional[str] = None,
    rating: Optional[float] = None,
    review_count: Optional[int] = None,
    sitio_web_apify: Optional[str] = None,
    telefono_apify: Optional[str] = None,
    email_apify: Optional[str] = None,
    apify_run_id: Optional[str] = None,
) -> bool:
    """
    Actualiza un lead de DENUE con datos obtenidos de Apify (Google Maps).
    Redes sociales y rating siempre se actualizan (Apify es la fuente).
    Sitio web, teléfono y email solo se llenan si DENUE no los tenía.
    Registra discrepancias de sitio web en el log para revisión.
    """
    db = get_db()
    try:
        existing = db.table("leads_master").select(
            "id, sitio_web, telefono, email, fuente_datos"
        ).eq("nombre_negocio", nombre_negocio).eq("ciudad", ciudad).eq("cliente_id", cliente_id).execute()

        if not existing.data:
            return False

        lead = existing.data[0]
        update: dict = {}

        # Redes sociales — Apify es la única fuente para esto
        if facebook_url:
            update["facebook_url"] = facebook_url
        if instagram_url:
            update["instagram_url"] = instagram_url
        if rating is not None:
            update["rating"] = rating
        if review_count is not None:
            update["review_count"] = review_count
        if apify_run_id:
            update["apify_run_id"] = apify_run_id

        # Cross-check sitio web
        if sitio_web_apify:
            if not lead.get("sitio_web"):
                update["sitio_web"] = sitio_web_apify
            else:
                web_denue = lead["sitio_web"].replace("www.", "").rstrip("/")
                web_apify = sitio_web_apify.replace("www.", "").rstrip("/")
                if web_denue != web_apify:
                    logger.info(
                        f"Cross-check web [{nombre_negocio}]: DENUE='{lead['sitio_web']}' "
                        f"vs Apify='{sitio_web_apify}' — se mantiene DENUE"
                    )

        # Cross-check teléfono — llenar si DENUE no lo tenía
        if telefono_apify and not lead.get("telefono"):
            update["telefono"] = telefono_apify

        # Cross-check email — llenar si DENUE no lo tenía
        if email_apify and not lead.get("email"):
            update["email"] = email_apify

        # Marcar como fuente combinada
        fuente_actual = lead.get("fuente_datos") or "denue"
        if "apify" not in fuente_actual:
            update["fuente_datos"] = f"{fuente_actual}+apify"

        if update:
            db.table("leads_master").update(update).eq("id", lead["id"]).execute()
            logger.info(f"🔄 Apify update: {nombre_negocio} | {list(update.keys())}")
        return True

    except Exception as e:
        logger.error(f"Error update_lead_apify_data [{nombre_negocio}]: {e}")
        return False


def get_leads_con_sitio_web(
    ciudad: str,
    cliente_id: str,
    termino_busqueda: str,
) -> list[dict]:
    """
    Retorna leads del run actual con sitio_web pero aún no verificados por Anymail.
    Se usan para el paso de enriquecimiento de emails.
    """
    db = get_db()
    try:
        result = db.table("leads_master").select(
            "id, nombre_negocio, ciudad, sitio_web, email, telefono, facebook_url, instagram_url"
        ).eq("cliente_id", cliente_id).eq("ciudad", ciudad).eq(
            "termino_busqueda", termino_busqueda
        ).eq("verificado", False).not_.is_("sitio_web", "null").execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error get_leads_con_sitio_web: {e}")
        return []


def update_lead_anymail_verificado(
    nombre_negocio: str,
    ciudad: str,
    cliente_id: str,
    email: str,
    email_status: str,
    hierarchy_score: int,
    lead_score: int,
    calidad_stars: int,
    canal_recomendado: str,
) -> None:
    """
    Actualiza el lead con el email verificado por Anymail Finder.
    Marca verificado=True — solo estos leads son elegibles para campañas de email.
    """
    db = get_db()
    try:
        db.table("leads_master").update({
            "email": email,
            "email_status": email_status,
            "hierarchy_score": hierarchy_score,
            "anymail_procesado": True,
            "verificado": True,
            "lead_score": lead_score,
            "calidad_stars": calidad_stars,
            "canal_recomendado": canal_recomendado,
        }).eq("nombre_negocio", nombre_negocio).eq("ciudad", ciudad).eq("cliente_id", cliente_id).execute()
        logger.info(f"✅ Verificado: {nombre_negocio} | {email} ({email_status}) | {calidad_stars}⭐")
    except Exception as e:
        logger.error(f"Error update_lead_anymail_verificado [{nombre_negocio}]: {e}")


def update_lead_email_personal_verificado(
    lead_id: str,
    email: str,
    email_status: str,   # "valid" | "invalid" | "unknown"
    canal: str = "brevo",
) -> None:
    """
    Marca un email personal (Gmail/Hotmail/etc) como procesado por Anymail.
    - Si válido  → verificado=True, canal_recomendado="brevo"
    - Si inválido → anymail_procesado=True (no reenviar), verificado=False
    """
    db = get_db()
    try:
        update = {
            "email_status": email_status,
            "anymail_procesado": True,
        }
        if email_status == "valid":
            update["verificado"] = True
            update["canal_recomendado"] = canal
            logger.info(f"✅ Personal verificado [{lead_id}]: {email} → {canal}")
        else:
            update["verificado"] = False
            logger.info(f"❌ Personal inválido [{lead_id}]: {email} ({email_status})")

        db.table("leads_master").update(update).eq("id", lead_id).execute()
    except Exception as e:
        logger.error(f"Error update_lead_email_personal_verificado [{lead_id}]: {e}")


def update_lead_score(
    nombre_negocio: str,
    ciudad: str,
    cliente_id: str,
    lead_score: int,
    calidad_stars: int,
    canal_recomendado: Optional[str],
) -> None:
    """Actualiza el score y clasificación de estrellas de un lead."""
    db = get_db()
    try:
        data: dict = {"lead_score": lead_score, "calidad_stars": calidad_stars}
        if canal_recomendado:
            data["canal_recomendado"] = canal_recomendado
        db.table("leads_master").update(data).eq(
            "nombre_negocio", nombre_negocio
        ).eq("ciudad", ciudad).eq("cliente_id", cliente_id).execute()
    except Exception as e:
        logger.error(f"Error update_lead_score [{nombre_negocio}]: {e}")


# ============================================================
# ESTADÍSTICAS DE LEADS
# ============================================================
def get_leads_stats(cliente_id: str) -> dict:
    """Estadísticas generales de leads_master para el cliente."""
    db = get_db()
    try:
        result = db.table("leads_master").select(
            "email, verificado, calidad_stars, sitio_web"
        ).eq("cliente_id", cliente_id).execute()
        leads = result.data or []
        total = len(leads)
        return {
            "total": total,
            "con_web": sum(1 for l in leads if l.get("sitio_web")),
            "con_email": sum(1 for l in leads if l.get("email")),
            "verificados": sum(1 for l in leads if l.get("verificado")),
            "cinco_estrellas": sum(1 for l in leads if (l.get("calidad_stars") or 0) >= 5),
            "con_web_sin_verificar": sum(
                1 for l in leads
                if l.get("sitio_web") and not l.get("verificado")
            ),
        }
    except Exception as e:
        logger.error(f"Error get_leads_stats: {e}")
        return {"total": 0, "con_web": 0, "con_email": 0, "verificados": 0, "cinco_estrellas": 0, "con_web_sin_verificar": 0}


def get_all_pending_leads_anymail(cliente_id: str, limit: int = 300) -> list[dict]:
    """Fase 1: leads con sitio web que aún no han sido verificados por Anymail."""
    db = get_db()
    try:
        result = db.table("leads_master").select(
            "id, nombre_negocio, ciudad, sitio_web, email, telefono, facebook_url, instagram_url"
        ).eq("cliente_id", cliente_id).eq(
            "verificado", False
        ).not_.is_("sitio_web", "null").limit(limit).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error get_all_pending_leads_anymail: {e}")
        return []


def get_anymail_stats_por_cliente() -> list[dict]:
    """
    Estadísticas de AnymailFinder por cliente en leads_master.
    Retorna lista de dicts con: cliente_id, nombre, total, procesados, validos, pendientes.
    """
    db = get_db()
    try:
        # Traer solo columnas necesarias (paginado)
        all_rows = []
        offset = 0
        while True:
            r = db.table("leads_master").select(
                "cliente_id, anymail_procesado, email_status"
            ).range(offset, offset + 999).execute()
            chunk = r.data or []
            if not chunk:
                break
            all_rows.extend(chunk)
            if len(chunk) < 1000:
                break
            offset += 1000

        # Nombres de clientes registrados
        clientes_r = db.table("clientes").select("id, nombre").execute()
        nombres = {c["id"]: c["nombre"] for c in (clientes_r.data or [])}

        # Agrupar por cliente
        from collections import defaultdict
        grupos: dict[str, dict] = defaultdict(lambda: {"total": 0, "procesados": 0, "validos": 0})
        for row in all_rows:
            cid = row["cliente_id"]
            grupos[cid]["total"] += 1
            if row.get("anymail_procesado"):
                grupos[cid]["procesados"] += 1
            if row.get("email_status") in ("valid", "verified", "denue_verified"):
                grupos[cid]["validos"] += 1

        result = []
        for cid, g in sorted(grupos.items(), key=lambda x: -x[1]["total"]):
            result.append({
                "cliente_id": cid,
                "nombre": nombres.get(cid, f"Cliente {cid[:8]}…"),
                "total": g["total"],
                "procesados": g["procesados"],
                "pendientes": g["total"] - g["procesados"],
                "validos": g["validos"],
            })
        return result
    except Exception as e:
        logger.error(f"Error get_anymail_stats_por_cliente: {e}")
        return []


def get_leads_con_email_sin_verificar(cliente_id: str, limit: int = 300) -> list[dict]:
    """Fase 2: leads con email de DENUE (sin sitio_web) que no han sido verificados."""
    db = get_db()
    try:
        result = db.table("leads_master").select(
            "id, nombre_negocio, ciudad, sitio_web, email, telefono, facebook_url, instagram_url"
        ).eq("cliente_id", cliente_id).eq(
            "verificado", False
        ).eq("anymail_procesado", False).not_.is_(
            "email", "null"
        ).is_("sitio_web", "null").limit(limit).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error get_leads_con_email_sin_verificar: {e}")
        return []


# ============================================================
# ESTADÍSTICAS DE PIPELINE
# ============================================================
def get_run_stats(cliente_id: str, since_hours: int = 24) -> dict:
    """Estadísticas del pipeline de las últimas N horas."""
    db = get_db()
    try:
        from datetime import timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

        email_result = db.table("email_leads").select(
            "id", count="exact"
        ).eq("cliente_id", cliente_id).gte("created_at", cutoff).execute()

        social_result = db.table("social_leads").select(
            "id", count="exact"
        ).eq("cliente_id", cliente_id).gte("created_at", cutoff).execute()

        return {
            "email_leads_nuevos": email_result.count or 0,
            "social_leads_nuevos": social_result.count or 0,
            "periodo_horas": since_hours,
        }
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        return {}
