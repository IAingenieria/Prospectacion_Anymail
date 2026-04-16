"""
LeadForge — Pipeline Principal
Orquesta el flujo completo:
  Caché check → DENUE (gratuito, INEGI) → Apify (Google Maps, costo) →
  Anymail enrichment → Validación en cascada → Lead scoring → Supabase

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

from .google_places_scraper import ApifyScraper, NegocioRaw
from .anymail_enricher import AnymailEnricher, AnymailResult as _AR, AnymailResult
from .validation_cascade import validate_company_emails, ValidationStatus
from .owner_extractor import extract_owner_from_reviews
from .lead_scorer import LeadSignals, calculate_lead_score, get_recommended_channels
from .supabase_client import (
    check_search_cache, save_search_cache,
    get_existing_emails, insert_email_lead, insert_social_lead,
    get_existing_names, insert_lead_master,
    update_lead_apify_data, get_leads_con_sitio_web,
    update_lead_anymail_verificado, update_lead_score,
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

    # Contadores por fuente
    denue_negocios: int = 0
    denue_con_email: int = 0
    apify_resultados: int = 0
    apify_nuevos: int = 0           # nuevos de Apify no en DENUE
    apify_actualizados: int = 0     # leads DENUE enriquecidos con datos de Apify
    apify_sin_creditos: bool = False

    # Anymail / verificación
    anymail_llamadas: int = 0
    anymail_creditos_usados: float = 0.0
    leads_verificados: int = 0      # verificados por Anymail (email válido, verificado=True)
    leads_5_estrellas: int = 0      # campaign-ready

    # Totales guardados en Supabase
    total_insertados: int = 0

    # Rechazos
    rechazados_status: int = 0
    rechazados_sin_mx: int = 0
    catch_all: int = 0
    duplicados: int = 0

    # Tiempo
    inicio: float = field(default_factory=time.time)
    fin: Optional[float] = None

    @property
    def duracion_segundos(self) -> float:
        if self.fin:
            return self.fin - self.inicio
        return time.time() - self.inicio

    def resumen(self) -> str:
        apify_status = "⚠️ Sin créditos — omitido" if self.apify_sin_creditos else (
            f"{self.apify_resultados} total / {self.apify_nuevos} nuevos / "
            f"{self.apify_actualizados} actualizados"
        )
        return (
            f"\n{'='*50}\n"
            f"RESUMEN DEL PIPELINE\n"
            f"{'='*50}\n"
            f"Términos: {', '.join(self.terminos)}\n"
            f"Ubicación: {self.location}\n"
            f"\nFUENTES:\n"
            f"  DENUE (INEGI, gratis): {self.denue_negocios} negocios ({self.denue_con_email} con email)\n"
            f"  Apify (Google Maps):   {apify_status}\n"
            f"\nRESULTADOS EN SUPABASE:\n"
            f"  Total guardados:  {self.total_insertados}\n"
            f"  Verificados (Anymail): ✅ {self.leads_verificados}\n"
            f"  5 estrellas (campaign-ready): ⭐ {self.leads_5_estrellas}\n"
            f"\nRECHAZOS ANYMAIL:\n"
            f"  Status inválido:  {self.rechazados_status}\n"
            f"  Sin registro MX:  {self.rechazados_sin_mx}\n"
            f"  Catch-all:        {self.catch_all}\n"
            f"  Duplicados:       {self.duplicados}\n"
            f"\nCOSTOS:\n"
            f"  Anymail créditos usados: {self.anymail_creditos_usados:.1f}\n"
            f"\nTIEMPO: {self.duracion_segundos:.1f} segundos\n"
            f"{'='*50}"
        )


async def _insert_negocio(
    negocio: NegocioRaw,
    cliente_id: str,
    existing_emails: set[str],
    stats: PipelineStats,
) -> None:
    """
    Guarda un negocio en Supabase con los datos disponibles (DENUE o Apify).
    No llama a Anymail — eso se hace en una fase posterior.
    """
    owner_info = await extract_owner_from_reviews(
        reviews_text=negocio.reviews_text,
        business_name=negocio.nombre,
    )

    # Score preliminar (sin verificación Anymail aún)
    signals = LeadSignals(
        hierarchy_score=0,
        review_count=negocio.review_count,
        responds_to_reviews=bool(negocio.reviews_text),
        has_owner_name=bool(owner_info.nombre),
        days_since_last_social=None,
        has_website=bool(negocio.sitio_web),
        rating=negocio.rating,
        has_phone=negocio.tiene_telefono,
        has_facebook=bool(negocio.facebook_url),
        has_instagram=bool(negocio.instagram_url),
    )
    lead_score = calculate_lead_score(signals)
    channels = get_recommended_channels(lead_score)

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
        email=negocio.email or None,
        email_status=None,
        hierarchy_score=0,
        anymail_procesado=False,
        owner_name=owner_info.nombre,
        cargo_inferido=owner_info.cargo,
        lead_score=lead_score,
        canal_recomendado=channels[0] if channels else None,
        actividad_digital_score=(
            (30 if negocio.sitio_web else 0) +
            (25 if negocio.facebook_url else 0) +
            (25 if negocio.instagram_url else 0) +
            (20 if negocio.tiene_telefono else 0)
        ),
    )

    if lead_id:
        stats.total_insertados += 1
        if negocio.email:
            existing_emails.add(negocio.email.lower())


async def _denue_buscar_negocios(
    terminos: list[str],
    location: str,
    ciudad: str,
) -> list[NegocioRaw]:
    """
    Busca negocios en DENUE/INEGI (gratuito) antes de gastar en Apify.
    Convierte DenueEstablecimiento → NegocioRaw para procesar con el mismo pipeline.
    """
    from .denue_enricher import DenueEnricher, ESTADO_CODES

    try:
        denue = DenueEnricher()
    except ValueError as e:
        logger.warning(f"DENUE no disponible: {e}")
        return []

    # Extraer estado del location string.
    # Soporta dos formatos:
    #   "Monterrey, Nuevo León, Mexico"  → estado en partes[1]
    #   "Nuevo León, México"             → estado en partes[0] (búsqueda por estado)
    partes = [p.strip() for p in location.split(",")]
    entidad = ""
    busqueda_por_estado = False  # True = no filtrar por ciudad (toda la entidad)

    # Intentar primero partes[0] (búsqueda tipo "Estado, País")
    if ESTADO_CODES.get(partes[0].lower()):
        entidad = ESTADO_CODES[partes[0].lower()]
        busqueda_por_estado = True
    # Luego intentar partes[1] (búsqueda tipo "Ciudad, Estado, País")
    elif len(partes) >= 2 and ESTADO_CODES.get(partes[1].lower()):
        entidad = ESTADO_CODES[partes[1].lower()]

    if not entidad:
        logger.warning(f"DENUE: no se encontró estado en location '{location}' — omitiendo DENUE")
        return []

    logger.info(f"DENUE: estado={entidad} | {'toda la entidad' if busqueda_por_estado else f'ciudad={ciudad}'}")

    negocios: list[NegocioRaw] = []
    seen_names: set[str] = set()

    for termino in terminos:
        logger.info(f"🏛️ DENUE: buscando '{termino}' en estado {entidad}...")
        establecimientos = await denue.buscar_por_estado(
            termino=termino,
            entidad=entidad,
            start=1,
            end=200,
        )
        logger.info(f"  → {len(establecimientos)} resultados DENUE para '{termino}'")

        for est in establecimientos:
            # Filtrar por ciudad solo si es búsqueda por ciudad específica
            if not busqueda_por_estado and ciudad and ciudad.lower() not in est.ciudad.lower():
                continue

            key = est.nombre.lower().strip()
            if key in seen_names:
                continue
            seen_names.add(key)

            negocios.append(NegocioRaw(
                nombre=est.nombre,
                categoria=est.clase_actividad or termino,
                ciudad=est.ciudad,
                estado=est.estado,
                pais="MX",
                direccion=est.direccion_completa,
                telefono=est.telefono or None,
                email=est.email or None,
                sitio_web=est.sitio_web or None,
                rating=None,
                review_count=None,
                facebook_url=None,
                instagram_url=None,
                reviews_text=[],
                termino_busqueda=termino,
                apify_run_id="denue",
                raw_data={
                    "denue_id": est.denue_id,
                    "clee": est.clee,
                    "razon_social": est.razon_social,
                    "estrato": est.estrato,
                    "latitud": est.latitud,
                    "longitud": est.longitud,
                },
            ))

    logger.info(f"✅ DENUE total: {len(negocios)} negocios únicos en {ciudad}")
    return negocios


async def run_pipeline(
    terminos: list[str],
    location: str,
    cliente_id: str,
    max_places: int = 50,
    force_scrape: bool = False,
) -> PipelineStats:
    """
    Pipeline completo de generación de leads.

    Orden de ejecución:
      1. Caché check
      2. DENUE/INEGI (gratuito) → inserta leads a Supabase
      3. Apify/Google Maps (costo) → actualiza leads DENUE + inserta nuevos
         - Si no hay créditos: notifica por Telegram y salta al paso 4
      4. Anymail Finder → verifica email para leads con sitio web
         - Actualiza Supabase con email + marca verificado=True
      5. Lead scoring + notificación por Telegram (ZenonFinder)
    """
    stats = PipelineStats(terminos=terminos, location=location, perfil_apify="nwua9Gu5YrADL7ZDj")
    ciudad = location.split(",")[0].strip()

    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 Iniciando pipeline: {terminos} en {location}")
    logger.info(f"{'='*50}")

    # ── PASO 1: CACHÉ ─────────────────────────────────────────────────────────
    if not force_scrape:
        cache = check_search_cache(terminos[0], ciudad, cliente_id)
        logger.info(f"Cache: {cache.mensaje}")
        if cache.action == "REUSE":
            logger.info(f"✅ Reutilizando {cache.total_leads} leads del caché. Sin costo.")
            stats.fin = time.time()
            return stats

    # ── PASO 2: DENUE (gratuito, INEGI) ───────────────────────────────────────
    denue_negocios = await _denue_buscar_negocios(terminos, location, ciudad)
    stats.denue_negocios = len(denue_negocios)
    stats.denue_con_email = sum(1 for n in denue_negocios if n.email)

    existing_emails = get_existing_emails(cliente_id)
    semaphore = asyncio.Semaphore(cfg.anymail_concurrent_calls)

    # Insertar leads de DENUE a Supabase
    async def insert_sem(negocio: NegocioRaw):
        async with semaphore:
            await _insert_negocio(negocio, cliente_id, existing_emails, stats)

    await asyncio.gather(*[insert_sem(n) for n in denue_negocios])
    logger.info(f"DENUE: {stats.denue_negocios} insertados ({stats.denue_con_email} con email)")

    # ── PASO 3: APIFY (Google Maps, costo) ────────────────────────────────────
    apify = ApifyScraper()
    apify_credits = await apify.check_credits()

    if not apify_credits.get("ok"):
        stats.apify_sin_creditos = True
        msg = (
            f"⚠️ *Apify sin créditos — pipeline continuó sin Google Maps*\n"
            f"Motivo: {apify_credits.get('error', 'desconocido')}\n"
            f"DENUE aportó {stats.denue_negocios} negocios.\n"
            f"Recargar en: console.apify.com → Billing"
        )
        logger.warning(f"Apify sin créditos: {apify_credits.get('error')} — saltando paso 3")
        try:
            from .monitor.alerts import send_telegram
            await send_telegram(msg)
        except Exception:
            pass
    else:
        logger.info(f"🗺️ Apify: buscando {terminos} en {location}...")
        apify_negocios = await apify.scrape_multi_term(
            terminos=terminos,
            location=location,
            max_places=max_places,
        )

        # scrape_multi_term devuelve [] si _run_actor retornó None (403 / sin créditos)
        if not apify_negocios and stats.apify_resultados == 0:
            # Verificar si fue por 403 revisando el log (el warning ya fue emitido en _run_actor)
            stats.apify_sin_creditos = True
            try:
                from .monitor.alerts import send_telegram
                await send_telegram(
                    f"⚠️ *Apify — Sin créditos o límite alcanzado*\n"
                    f"El pipeline continuó con los {stats.denue_negocios} leads de DENUE.\n"
                    f"Recargar en: console.apify.com → Billing → Spending limits"
                )
            except Exception:
                pass

        stats.apify_resultados = len(apify_negocios)

        denue_names = {n.nombre.lower().strip() for n in denue_negocios}

        for neg in apify_negocios:
            key = neg.nombre.lower().strip()
            if key in denue_names:
                # Ya está en DENUE → actualizar con datos de redes sociales + cross-check
                updated = update_lead_apify_data(
                    nombre_negocio=neg.nombre,
                    ciudad=neg.ciudad,
                    cliente_id=cliente_id,
                    facebook_url=neg.facebook_url,
                    instagram_url=neg.instagram_url,
                    rating=neg.rating,
                    review_count=neg.review_count,
                    sitio_web_apify=neg.sitio_web,
                    telefono_apify=neg.telefono,
                    email_apify=neg.email,
                    apify_run_id=neg.apify_run_id,
                )
                if updated:
                    stats.apify_actualizados += 1
            else:
                # Nuevo negocio no encontrado en DENUE → insertar
                await _insert_negocio(neg, cliente_id, existing_emails, stats)
                stats.apify_nuevos += 1

        logger.info(
            f"Apify: {stats.apify_resultados} total / "
            f"{stats.apify_nuevos} nuevos / {stats.apify_actualizados} actualizados en DENUE"
        )

    # ── PASO 4: ANYMAIL FINDER (verificación de emails) ───────────────────────
    anymail = AnymailEnricher()
    account_status = await anymail.check_account_status()

    if not account_status.get("ok"):
        logger.warning(f"⚠️ Anymail no disponible: {account_status.get('error')} — saltando verificación")
    else:
        # Cargar todos los leads del run actual que tienen web pero no están verificados
        leads_con_web = get_leads_con_sitio_web(
            ciudad=ciudad,
            cliente_id=cliente_id,
            termino_busqueda=terminos[0],
        )
        logger.info(f"Anymail: {len(leads_con_web)} leads con sitio web para verificar...")

        async def verificar_lead(lead: dict):
            async with semaphore:
                result: AnymailResult = await anymail.enrich_negocio(
                    company_name=lead["nombre_negocio"],
                    existing_email=lead.get("email"),
                )
                stats.anymail_llamadas += 1
                stats.anymail_creditos_usados += result.credits_used

                if not result.emails:
                    return

                # Validar emails encontrados
                validation_results = await validate_company_emails(
                    emails_raw=result.emails,
                    anymail_api_key=cfg.anymail_api_key,
                    existing_emails=existing_emails,
                    max_per_company=cfg.max_emails_per_company,
                )

                for vr in validation_results:
                    if vr.status == ValidationStatus.RECHAZADO_STATUS:
                        stats.rechazados_status += 1
                    elif vr.status == ValidationStatus.RECHAZADO_SIN_MX:
                        stats.rechazados_sin_mx += 1
                    elif vr.status == ValidationStatus.CATCH_ALL:
                        stats.catch_all += 1
                    elif vr.status == ValidationStatus.DUPLICADO:
                        stats.duplicados += 1

                # Tomar el mejor email aprobado
                aprobados = [vr for vr in validation_results if vr.es_apto_para_campana]
                if not aprobados:
                    return

                best = max(aprobados, key=lambda v: v.score)

                # Calcular calidad_stars final (5 = verificado + info completa)
                tiene_tel = bool(lead.get("telefono"))
                tiene_web = bool(lead.get("sitio_web"))
                if best.status.value == "valid" and tiene_tel and tiene_web:
                    stars = 5
                    stats.leads_5_estrellas += 1
                elif best.status.value == "valid" and tiene_tel:
                    stars = 4
                else:
                    stars = 3

                signals = LeadSignals(
                    hierarchy_score=best.score,
                    review_count=None,
                    responds_to_reviews=False,
                    has_owner_name=False,
                    days_since_last_social=None,
                    has_website=tiene_web,
                    rating=None,
                    has_phone=tiene_tel,
                    has_facebook=bool(lead.get("facebook_url")),
                    has_instagram=bool(lead.get("instagram_url")),
                )
                lead_score = calculate_lead_score(signals)
                channels = get_recommended_channels(lead_score)

                update_lead_anymail_verificado(
                    nombre_negocio=lead["nombre_negocio"],
                    ciudad=lead["ciudad"],
                    cliente_id=cliente_id,
                    email=best.email,
                    email_status=best.status.value,
                    hierarchy_score=best.score,
                    lead_score=lead_score,
                    calidad_stars=stars,
                    canal_recomendado=channels[0] if channels else "email",
                )
                stats.leads_verificados += 1
                existing_emails.add(best.email.lower())

        await asyncio.gather(*[verificar_lead(l) for l in leads_con_web])
        logger.info(
            f"Anymail: {stats.leads_verificados} verificados | "
            f"{stats.leads_5_estrellas} ⭐⭐⭐⭐⭐ campaign-ready"
        )

    # ── PASO 5: NOTIFICACIÓN TELEGRAM (ZenonFinder) ───────────────────────────
    try:
        from .monitor.alerts import send_telegram
        apify_linea = (
            "⚠️ Apify sin créditos — solo DENUE"
            if stats.apify_sin_creditos
            else f"{stats.apify_resultados} resultados ({stats.apify_nuevos} nuevos)"
        )
        msg = (
            f"✅ *Pipeline completado*\n"
            f"_{', '.join(terminos)} — {ciudad}_\n\n"
            f"🏛️ DENUE: {stats.denue_negocios} negocios\n"
            f"🗺️ Apify: {apify_linea}\n"
            f"📧 Verificados (Anymail): {stats.leads_verificados}\n"
            f"⭐ 5 estrellas (campaign-ready): {stats.leads_5_estrellas}\n"
            f"💳 Créditos Anymail usados: {stats.anymail_creditos_usados:.1f}\n"
            f"⏱ Tiempo: {stats.duracion_segundos:.0f}s"
        )
        await send_telegram(msg)
    except Exception as e:
        logger.warning(f"No se pudo enviar notificación Telegram: {e}")

    # ── ACTUALIZAR CACHÉ ───────────────────────────────────────────────────────
    save_search_cache(
        termino=terminos[0],
        ciudad=ciudad,
        cliente_id=cliente_id,
        total_resultados=stats.apify_resultados or stats.denue_negocios,
        leads_validos=stats.leads_verificados,
        costo_anymail=int(stats.anymail_creditos_usados),
        perfil_apify="L5MMRiysAv4Xs57uZ",
    )

    stats.fin = time.time()
    logger.info(stats.resumen())
    return stats
