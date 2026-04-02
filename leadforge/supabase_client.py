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
# ESTADÍSTICAS
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
