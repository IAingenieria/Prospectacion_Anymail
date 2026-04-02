"""
LeadForge — Pipeline Principal (Fase 1)
Orquesta el flujo completo:
  Caché check → Apify scraping → Anymail enrichment →
  Validación en cascada → Lead scoring → Supabase (DB1 + DB2)

Uso:
  from leadforge.pipeline import run_pipeline
  await run_pipeline(terminos=["taller mecánico"], location="Monterrey, Mexico",
                     cliente_id="uuid-aqui")
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .apify_scraper import ApifyScraper, NegocioRaw
from .anymail_enricher import AnymailEnricher, AnymailResult as _AR, AnymailResult
from .validation_cascade import validate_company_emails, ValidationStatus
from .owner_extractor import extract_owner_from_reviews
from .lead_scorer import LeadSignals, calculate_lead_score, get_recommended_channels
from .supabase_client import (
    check_search_cache, save_search_cache,
    get_existing_emails, insert_email_lead, insert_social_lead,
    get_existing_names, insert_lead_master,
    get_run_stats,
)
from .config import cfg

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Estadísticas de una ejecución del pipeline."""
    terminos: list[str]
    location: str
    perfil_apify: str

    # Contadores
    apify_resultados: int = 0
    anymail_llamadas: int = 0
    anymail_creditos_usados: float = 0.0
    email_leads_insertados: int = 0
    social_leads_insertados: int = 0

    denue_emails_nuevos: int = 0

    # Rechazos por nivel
    rechazados_status: int = 0
    rechazados_sin_mx: int = 0
    catch_all: int = 0
    duplicados: int = 0
    sin_email_ni_telefono: int = 0

    # Tiempo
    inicio: float = field(default_factory=time.time)
    fin: Optional[float] = None

    @property
    def duracion_segundos(self) -> float:
        if self.fin:
            return self.fin - self.inicio
        return time.time() - self.inicio

    def resumen(self) -> str:
        return (
            f"\n{'='*50}\n"
            f"RESUMEN DEL PIPELINE\n"
            f"{'='*50}\n"
            f"Términos buscados: {', '.join(self.terminos)}\n"
            f"Ubicación: {self.location}\n"
            f"Perfil Apify: {self.perfil_apify}\n"
            f"\nRESULTADOS APIFY: {self.apify_resultados} negocios\n"
            f"\nDB1 - Email leads insertados: ✅ {self.email_leads_insertados}\n"
            f"DB2 - Social leads insertados: ✅ {self.social_leads_insertados}\n"
            f"DB DENUE - Emails adicionales: ✅ {self.denue_emails_nuevos}\n"
            f"\nRECHAZOS:\n"
            f"  Status inválido (not valid):  {self.rechazados_status}\n"
            f"  Sin registro MX:              {self.rechazados_sin_mx}\n"
            f"  Catch-all (revisión manual):  {self.catch_all}\n"
            f"  Duplicados:                   {self.duplicados}\n"
            f"  Sin email ni teléfono:        {self.sin_email_ni_telefono}\n"
            f"\nCOSTOS ESTIMADOS:\n"
            f"  Anymail créditos usados: {self.anymail_creditos_usados:.1f}\n"
            f"\nTIEMPO: {self.duracion_segundos:.1f} segundos\n"
            f"{'='*50}"
        )


async def process_negocio(
    negocio: NegocioRaw,
    cliente_id: str,
    existing_emails: set[str],
    anymail: Optional[AnymailEnricher],
    stats: PipelineStats,
) -> None:
    """Procesa un negocio individual: enriquece, valida e inserta."""

    # --- Paso 1: Extraer nombre del dueño (sin costo si regex funciona) ---
    owner_info = await extract_owner_from_reviews(
        reviews_text=negocio.reviews_text,
        business_name=negocio.nombre,
    )

    # --- Paso 2: Enriquecimiento con Anymail Finder ---
    # Solo buscamos email si el negocio tiene website Y Anymail está disponible
    if anymail and (negocio.sitio_web or negocio.email):
        anymail_result: AnymailResult = await anymail.enrich_negocio(
            company_name=negocio.nombre,
            existing_email=negocio.email,
        )
        stats.anymail_llamadas += 1
        stats.anymail_creditos_usados += anymail_result.credits_used
    else:
        # Sin website/email o Anymail no disponible → pasar directo a social lead
        anymail_result = _AR(company_name=negocio.nombre, emails=[], route_used="skip", credits_used=0)

    # --- Paso 3: Validación en cascada ---
    validation_results = await validate_company_emails(
        emails_raw=anymail_result.emails,
        anymail_api_key=cfg.anymail_api_key,
        existing_emails=existing_emails,
        max_per_company=cfg.max_emails_per_company,
    )

    # Contabilizar rechazos
    for vr in validation_results:
        if vr.status == ValidationStatus.RECHAZADO_STATUS:
            stats.rechazados_status += 1
        elif vr.status == ValidationStatus.RECHAZADO_SIN_MX:
            stats.rechazados_sin_mx += 1
        elif vr.status == ValidationStatus.CATCH_ALL:
            stats.catch_all += 1
        elif vr.status == ValidationStatus.DUPLICADO:
            stats.duplicados += 1

    # --- Paso 4: Calcular score del negocio ---
    days_social = None
    if negocio.facebook_url or negocio.instagram_url:
        # TODO: enriquecer con Apify social scraper (Fase 2)
        days_social = None  # Por ahora desconocido

    signals = LeadSignals(
        hierarchy_score=0,  # se calculará por email individual
        review_count=negocio.review_count,
        responds_to_reviews=bool(negocio.reviews_text),
        has_owner_name=bool(owner_info.nombre),
        days_since_last_social=days_social,
        has_website=bool(negocio.sitio_web),
        rating=negocio.rating,
        has_phone=negocio.tiene_telefono,
        has_facebook=bool(negocio.facebook_url),
        has_instagram=bool(negocio.instagram_url),
    )

    # --- Paso 5: Calcular score y determinar mejor email ---
    aprobados = [vr for vr in validation_results if vr.es_apto_para_campana]
    best_email = None
    best_email_status = None
    best_hierarchy = 0

    for vr in aprobados:
        signals.hierarchy_score = vr.score
        if vr.score > best_hierarchy:
            best_hierarchy = vr.score
            best_email = vr.email
            best_email_status = vr.status.value

    # Contabilizar rechazos
    if not aprobados and anymail_result.emails:
        pass  # ya contabilizado arriba

    lead_score = calculate_lead_score(signals)
    channels = get_recommended_channels(lead_score)

    # Calcular score digital
    digital_score = 0
    if negocio.sitio_web:   digital_score += 30
    if negocio.facebook_url: digital_score += 25
    if negocio.instagram_url: digital_score += 25
    if negocio.tiene_telefono: digital_score += 20

    # --- Paso 6: Insertar en leads_master (tabla unificada BIG ONE) ---
    lead_id = insert_lead_master(
        cliente_id=cliente_id,
        nombre_negocio=negocio.nombre,
        categoria=negocio.categoria,
        ciudad=negocio.ciudad,
        estado=negocio.estado,
        pais="MX",
        direccion=negocio.direccion,
        sitio_web=negocio.sitio_web,
        telefono=negocio.telefono,
        facebook_url=negocio.facebook_url,
        instagram_url=negocio.instagram_url,
        rating=negocio.rating,
        review_count=negocio.review_count,
        google_maps_url=None,
        apify_run_id=negocio.apify_run_id,
        termino_busqueda=negocio.termino_busqueda,
        email=best_email,
        email_status=best_email_status,
        hierarchy_score=best_hierarchy,
        anymail_procesado=anymail_result is not None,
        owner_name=owner_info.nombre,
        cargo_inferido=owner_info.cargo,
        lead_score=lead_score,
        canal_recomendado=channels[0] if channels else None,
        actividad_digital_score=digital_score,
    )

    if lead_id:
        if best_email:
            stats.email_leads_insertados += 1
            existing_emails.add(best_email.lower())
        else:
            stats.social_leads_insertados += 1
        if not negocio.tiene_telefono and not best_email and not negocio.tiene_social:
            stats.sin_email_ni_telefono += 1


async def _denue_enrich_new_leads(ciudad: str, apify_run_id: str = None) -> int:
    """
    Enriquece con DENUE los leads recién insertados (sin email).
    Retorna cantidad de emails nuevos encontrados.
    """
    import asyncio as _asyncio
    from concurrent.futures import ThreadPoolExecutor
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    def _run_denue_sync():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "denue_enricher",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "denue_enricher.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Buscar leads sin email de esta ciudad específica
            leads = mod.sb_get_leads_sin_email(limit=50, offset=0)
            # Filtrar por ciudad si aplica
            if ciudad:
                ciudad_lower = ciudad.lower()
                leads = [l for l in leads if ciudad_lower in (l.get('ciudad') or '').lower()][:30]

            count = 0
            for lead in leads:
                resultado = mod.enriquecer_lead(lead, verbose=False)
                if resultado.get('status') == 'enriquecido':
                    mejoras = resultado.get('mejoras', [])
                    if any('email' in m for m in mejoras):
                        count += 1
            return count
        except Exception as e:
            logger.warning(f"DENUE sync error: {e}")
            return 0

    loop = _asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _run_denue_sync)
    return result


async def run_pipeline(
    terminos: list[str],
    location: str,
    cliente_id: str,
    max_places: int = 50,
    force_scrape: bool = False,
) -> PipelineStats:
    """
    Ejecuta el pipeline completo para una búsqueda.

    Args:
        terminos: Lista de términos de búsqueda (sinónimos) para Google Maps
        location: "Ciudad, Estado, País" (ej: "Monterrey, Nuevo León, Mexico")
        cliente_id: UUID del cliente en Supabase
        max_places: Máximo de lugares a extraer por término
        force_scrape: Si True, ignora el caché y siempre hace scraping
    """
    stats = PipelineStats(terminos=terminos, location=location, perfil_apify="nwua9Gu5YrADL7ZDj")
    ciudad = location.split(",")[0].strip()

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 Iniciando pipeline: {terminos} en {location}")
    logger.info(f"{'='*50}")

    # --- CACHÉ CHECK ---
    if not force_scrape:
        cache = check_search_cache(terminos[0], ciudad, cliente_id)
        logger.info(f"Cache: {cache.mensaje}")
        if cache.action == "REUSE":
            logger.info(f"✅ Reutilizando {cache.total_leads} leads del caché. Sin costo de Apify.")
            stats.fin = time.time()
            return stats

    # --- APIFY SCRAPING ---
    apify = ApifyScraper()
    negocios = await apify.scrape_multi_term(
        terminos=terminos,
        location=location,
        max_places=max_places,
    )
    stats.apify_resultados = len(negocios)

    if not negocios:
        logger.warning("Apify no devolvió resultados")
        stats.fin = time.time()
        return stats

    # --- PREPARAR ANYMAIL Y DATOS EXISTENTES ---
    anymail = AnymailEnricher()

    # Verificar cuenta Anymail antes de procesar
    account_status = await anymail.check_account_status()
    anymail_disponible = account_status["ok"]
    if not anymail_disponible:
        logger.warning(f"⚠️ Anymail Finder no disponible: {account_status['error']}")
        logger.warning("Continuando sin enriquecimiento — leads irán como social leads.")

    # Cargar emails existentes (para deduplicación)
    existing_emails = get_existing_emails(cliente_id)
    logger.info(f"Emails en DB: {len(existing_emails)} (para deduplicación)")

    # --- PROCESAR NEGOCIOS (con concurrencia limitada) ---
    semaphore = asyncio.Semaphore(cfg.anymail_concurrent_calls)

    async def process_with_semaphore(negocio: NegocioRaw):
        async with semaphore:
            await process_negocio(
                negocio=negocio,
                cliente_id=cliente_id,
                existing_emails=existing_emails,
                anymail=anymail if anymail_disponible else None,
                stats=stats,
            )

    tasks = [process_with_semaphore(n) for n in negocios]
    await asyncio.gather(*tasks)

    # --- DENUE ENRICHMENT AUTOMÁTICO ---
    # Enriquecer leads recién insertados que quedaron sin email
    if stats.social_leads_insertados > 0:
        logger.info(f"🔍 DENUE: enriqueciendo {stats.social_leads_insertados} social leads...")
        try:
            denue_nuevos = await _denue_enrich_new_leads(
                ciudad=ciudad,
                apify_run_id=negocios[0].apify_run_id if negocios else None,
            )
            stats.denue_emails_nuevos = denue_nuevos
            if denue_nuevos > 0:
                logger.info(f"✅ DENUE encontró {denue_nuevos} emails adicionales")
        except Exception as e:
            logger.warning(f"DENUE enrichment falló (no crítico): {e}")

    # --- ACTUALIZAR CACHÉ ---
    save_search_cache(
        termino=terminos[0],
        ciudad=ciudad,
        cliente_id=cliente_id,
        total_resultados=stats.apify_resultados,
        leads_validos=stats.email_leads_insertados,
        costo_anymail=int(stats.anymail_creditos_usados),
        perfil_apify="L5MMRiysAv4Xs57uZ",
    )

    stats.fin = time.time()
    logger.info(stats.resumen())
    return stats
