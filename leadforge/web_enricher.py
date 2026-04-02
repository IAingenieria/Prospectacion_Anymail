"""
LeadForge — Web Enricher
Módulo de enriquecimiento web para leads sin email corporativo.

Pipeline por lead (en orden):
  1. Scraping del sitio web propio
     → homepage, /contacto, /contact, /nosotros, /about, footer, header
  2. Búsqueda DuckDuckGo (si no hay URL o scraping falló)
     → busca nombre + ciudad + redes sociales
  3. Apify Place Details (opcional, solo si hay créditos)
     → actor: compass~google-maps-extractor con 1 lugar
  4. AnyMailFinder (último recurso antes de rendirse)
     → find_by_company con dominio o nombre+ciudad
  5. Actualizar Supabase
     → email, email_status, redes sociales, lead_score

Targets: leads_master con email vacío/gratuito y calidad_stars < 5
"""
import asyncio
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, quote_plus

import httpx

from .config import cfg
from .supabase_client import get_db
from .social_media_detector import (
    extract_all_from_html,
    is_free_email,
    FREE_EMAIL_PROVIDERS,
)
from .anymail_enricher import AnymailEnricher

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────
TIMEOUT_SECS = 10
DOMAIN_RATE_LIMIT = 0.5        # 500 ms entre requests al mismo dominio
DDG_RATE_LIMIT = 1.5           # 1.5 seg entre búsquedas DuckDuckGo
MAX_CONCURRENT = 5             # leads procesándose en paralelo
APIFY_CALL_TIMEOUT = 60        # segundos máx por llamada Apify

# Páginas a revisar en cada sitio web (en orden de prioridad)
CONTACT_PATHS = [
    "",            # homepage
    "/contacto",
    "/contact",
    "/contactanos",
    "/nosotros",
    "/about",
    "/about-us",
    "/quienes-somos",
    "/empresa",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Regex para detectar dominios en resultados de búsqueda
_DOMAIN_PATTERN = re.compile(
    r"https?://(?!(?:www\.)?(?:facebook|instagram|twitter|x|linkedin|"
    r"tiktok|youtube|duckduckgo|google|bing|yahoo|maps\.google)\.)([A-Za-z0-9.\-]+\.[a-z]{2,})"
)


# ── Dataclasses de resultado ─────────────────────────────────────────────────

@dataclass
class EnrichResult:
    """Resultado del enriquecimiento de un lead."""
    lead_id: str
    nombre: str
    email_found: Optional[str] = None
    email_source: Optional[str] = None   # web_found | google_found | apify_found | amf_found | not_found
    social: dict = field(default_factory=dict)
    website_found: Optional[str] = None  # sitio web descubierto por búsqueda
    error: Optional[str] = None

    @property
    def has_email(self) -> bool:
        return bool(self.email_found)

    @property
    def has_social(self) -> bool:
        return any(v for v in self.social.values() if v)


# ── Cliente HTTP compartido ───────────────────────────────────────────────────

def _make_client(timeout: float = TIMEOUT_SECS) -> httpx.AsyncClient:
    """Crea AsyncClient con SSL permisivo (muchos sitios MX tienen certs auto-firmados)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return httpx.AsyncClient(
        timeout=timeout,
        verify=False,
        follow_redirects=True,
        headers=_HEADERS,
    )


# ── Clase principal ───────────────────────────────────────────────────────────

class WebEnricher:
    """
    Enriquece leads sin email corporativo usando scraping web,
    búsqueda en DuckDuckGo, Apify y AnyMailFinder como escalada.
    """

    def __init__(self):
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._domain_timestamps: dict[str, float] = {}  # domain → last request time
        self._ddg_last_request: float = 0.0
        self._anymail = AnymailEnricher()

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        return self._semaphore

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def _wait_for_domain(self, domain: str) -> None:
        """Máx 2 requests/seg por dominio (500 ms de pausa)."""
        last = self._domain_timestamps.get(domain, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < DOMAIN_RATE_LIMIT:
            await asyncio.sleep(DOMAIN_RATE_LIMIT - elapsed)
        self._domain_timestamps[domain] = time.monotonic()

    async def _wait_for_ddg(self) -> None:
        """Pausa entre búsquedas DuckDuckGo para no ser bloqueado."""
        elapsed = time.monotonic() - self._ddg_last_request
        if elapsed < DDG_RATE_LIMIT:
            await asyncio.sleep(DDG_RATE_LIMIT - elapsed)
        self._ddg_last_request = time.monotonic()

    # ── Paso 1: Scraping del sitio web ────────────────────────────────────────

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Descarga una página y devuelve HTML. None en caso de error."""
        parsed = urlparse(url)
        domain = parsed.netloc
        await self._wait_for_domain(domain)
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                # Limitar a 500 KB para no procesar páginas enormes
                return resp.text[:500_000]
            logger.debug(f"HTTP {resp.status_code} para {url}")
        except httpx.TimeoutException:
            logger.debug(f"Timeout: {url}")
        except httpx.ConnectError:
            logger.debug(f"Conexión rechazada: {url}")
        except Exception as e:
            logger.debug(f"Error fetching {url}: {type(e).__name__}: {e}")
        return None

    async def _scrape_website(self, base_url: str) -> dict:
        """
        Scrapes páginas del sitio web buscando emails y redes sociales.

        Revisa: homepage, /contacto, /contact, /nosotros, /about, etc.
        Se detiene en cuanto encuentra un email corporativo.

        Returns:
            {"emails": list, "social": dict, "pages_checked": int}
        """
        if not base_url:
            return {"emails": [], "social": {k: None for k in ["facebook_url", "instagram_url", "linkedin_url", "twitter_url", "tiktok_url", "youtube_url"]}, "pages_checked": 0}

        # Normalizar URL
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url.lstrip("/")
        base_url = base_url.rstrip("/")

        parsed = urlparse(base_url)
        if not parsed.netloc:
            return {"emails": [], "social": {k: None for k in ["facebook_url", "instagram_url", "linkedin_url", "twitter_url", "tiktok_url", "youtube_url"]}, "pages_checked": 0}

        all_emails: list[str] = []
        all_social: dict[str, Optional[str]] = {k: None for k in ["facebook_url", "instagram_url", "linkedin_url", "twitter_url", "tiktok_url", "youtube_url"]}
        pages_checked = 0

        try:
            async with _make_client() as client:
                for path in CONTACT_PATHS:
                    url = base_url + path
                    html = await self._fetch_page(client, url)
                    if not html:
                        continue

                    pages_checked += 1
                    extracted = extract_all_from_html(html)

                    # Acumular emails
                    all_emails.extend(extracted["emails"])

                    # Acumular redes sociales (primer hit válido gana)
                    for network, url_found in extracted["social"].items():
                        if url_found and not all_social.get(network):
                            all_social[network] = url_found

                    # Si ya tenemos email corporativo, no seguimos scrapeando
                    if all_emails:
                        logger.debug(f"Email encontrado en {url} (página {pages_checked}) — parando scraping")
                        break

        except Exception as e:
            logger.warning(f"Error scrapeando {base_url}: {e}")

        # Deduplicar emails preservando orden (primero = más relevante)
        seen: set[str] = set()
        unique_emails: list[str] = []
        for e in all_emails:
            el = e.lower()
            if el not in seen:
                seen.add(el)
                unique_emails.append(e)

        return {
            "emails": unique_emails,
            "social": all_social,
            "pages_checked": pages_checked,
        }

    # ── Paso 2: Búsqueda DuckDuckGo ──────────────────────────────────────────

    async def _duckduckgo_search(self, nombre: str, ciudad: str) -> dict:
        """
        Busca el negocio en DuckDuckGo para encontrar:
        - Su sitio web oficial
        - Perfiles de redes sociales
        - Emails corporativos en resultados de búsqueda

        Returns:
            {"website": str|None, "emails": list, "social": dict}
        """
        empty_social = {k: None for k in ["facebook_url", "instagram_url", "linkedin_url", "twitter_url", "tiktok_url", "youtube_url"]}
        result = {"website": None, "emails": [], "social": dict(empty_social)}

        query = f'"{nombre}" "{ciudad}" site:facebook.com OR site:instagram.com OR correo contacto email'
        ddg_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

        await self._wait_for_ddg()
        try:
            async with _make_client(timeout=15) as client:
                resp = await client.get(
                    ddg_url,
                    headers={**_HEADERS, "Referer": "https://duckduckgo.com/"},
                )
                if resp.status_code != 200:
                    logger.debug(f"DuckDuckGo HTTP {resp.status_code}")
                    return result

                html = resp.text
                extracted = extract_all_from_html(html)
                result["emails"] = extracted["emails"]
                result["social"] = extracted["social"]

                # Buscar posible sitio web oficial del negocio en los resultados
                domain_matches = _DOMAIN_PATTERN.findall(html)
                nombre_palabras = {w.lower() for w in nombre.split() if len(w) > 3}
                for domain in domain_matches:
                    domain_lower = domain.lower()
                    # Verificar si el dominio contiene alguna palabra del nombre
                    if any(w in domain_lower for w in nombre_palabras):
                        result["website"] = f"https://{domain}"
                        logger.debug(f"Sitio web encontrado en DDG: {result['website']}")
                        break

        except asyncio.TimeoutError:
            logger.debug(f"DuckDuckGo timeout para '{nombre}'")
        except Exception as e:
            logger.debug(f"Error búsqueda DuckDuckGo '{nombre}': {type(e).__name__}: {e}")

        return result

    # ── Paso 3: Apify fallback ────────────────────────────────────────────────

    async def _check_apify_credits(self) -> bool:
        """True si hay créditos disponibles en Apify (>= $0.10)."""
        if not cfg.apify_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    "https://api.apify.com/v2/users/me",
                    headers={"Authorization": f"Bearer {cfg.apify_token}"},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    # La API de Apify devuelve "monthlyUsage" con uso actual
                    monthly = data.get("monthlyUsage", {})
                    used_usd = monthly.get("usedCreditsUsd", 0) or 0
                    limit_usd = monthly.get("monthlyUsageCreditsUsd", {})
                    if isinstance(limit_usd, dict):
                        limit_usd = limit_usd.get("value", 5.0)
                    remaining = float(limit_usd) - float(used_usd)
                    has_credits = remaining >= 0.10
                    logger.debug(f"Apify créditos: ${remaining:.2f} restantes")
                    return has_credits
        except Exception as e:
            logger.debug(f"Error verificando créditos Apify: {e}")
        return False

    async def _apify_place_search(
        self, nombre: str, ciudad: str, use_apify: bool = False
    ) -> dict:
        """
        Busca el negocio usando el Google Maps Extractor de Apify.
        Solo se ejecuta si use_apify=True y hay créditos disponibles.

        Returns:
            {"website": str|None, "phone": str|None, "emails": list,
             "facebook_url": str|None, "instagram_url": str|None}
        """
        empty = {
            "website": None, "phone": None, "emails": [],
            "facebook_url": None, "instagram_url": None,
        }

        if not use_apify or not cfg.apify_token:
            return empty

        has_credits = await self._check_apify_credits()
        if not has_credits:
            logger.info(f"Apify: sin créditos — skip para '{nombre}'")
            return empty

        try:
            async with httpx.AsyncClient(timeout=APIFY_CALL_TIMEOUT) as client:
                # Usar el mismo actor que el resto del sistema
                actor_url = (
                    "https://api.apify.com/v2/acts/compass~google-maps-extractor"
                    "/run-sync-get-dataset-items"
                )
                payload = {
                    "searchStringsArray": [f"{nombre} {ciudad}"],
                    "maxCrawledPlacesPerSearch": 1,
                    "language": "es",
                    "countryCode": "mx",
                    "scrapeContacts": True,
                }
                resp = await client.post(
                    actor_url,
                    headers={
                        "Authorization": f"Bearer {cfg.apify_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code != 200 or not resp.json():
                    return empty

                place = resp.json()[0]
                website = place.get("website")
                phone = place.get("phone")

                # Apify a veces incluye emails en descripción o categorías
                from .social_media_detector import filter_corporate_emails, extract_emails_from_text
                desc = (place.get("description") or "") + " " + (place.get("additionalInfo") or "")
                emails = filter_corporate_emails(extract_emails_from_text(desc))

                result = {
                    "website": website,
                    "phone": phone,
                    "emails": emails,
                    "facebook_url": place.get("facebook"),
                    "instagram_url": place.get("instagram"),
                }
                logger.info(f"Apify encontró datos para '{nombre}': website={website}")
                return result

        except asyncio.TimeoutError:
            logger.debug(f"Apify timeout para '{nombre}'")
        except Exception as e:
            logger.debug(f"Error Apify '{nombre}': {type(e).__name__}: {e}")

        return empty

    # ── Paso 4: AnyMailFinder ─────────────────────────────────────────────────

    async def _anymail_fallback(
        self, domain: Optional[str], nombre: str, ciudad: str
    ) -> Optional[str]:
        """
        Último recurso: usa AnyMailFinder para buscar email.
        Prioriza búsqueda por dominio si lo tenemos.

        Returns: email corporativo o None.
        """
        if not cfg.anymail_api_key:
            return None

        try:
            search_name = nombre if not ciudad else f"{nombre} {ciudad}"
            result = await self._anymail.find_by_company(company_name=search_name)

            if result.error:
                logger.debug(f"AnyMailFinder error: {result.error}")
                return None

            # Preferir emails válidos
            if result.tiene_emails_validos:
                valid_emails = [e for e in result.emails if e.get("email_status") == "valid"]
                email = valid_emails[0]["email"]
                if not is_free_email(email):
                    return email

            # Aceptar cualquier email corporativo encontrado
            for entry in result.emails:
                email = entry.get("email", "")
                if email and "@" in email and not is_free_email(email):
                    return email

        except Exception as e:
            logger.debug(f"Error AnyMailFinder '{nombre}': {e}")

        return None

    # ── Paso 5: Actualizar Supabase ───────────────────────────────────────────

    async def _update_supabase(
        self,
        lead: dict,
        email: Optional[str],
        email_source: str,
        social: dict[str, Optional[str]],
        new_website: Optional[str],
    ) -> None:
        """Guarda en Supabase los resultados del enriquecimiento."""
        try:
            db = get_db()
            now_iso = datetime.now(timezone.utc).isoformat()
            update_data: dict = {
                "email_status": email_source,
                "email_enriched_at": now_iso,
            }

            # Email encontrado
            if email:
                update_data["email"] = email
                # Incrementar lead_score (máximo 100)
                current_score = lead.get("lead_score") or 0
                update_data["lead_score"] = min(int(current_score) + 20, 100)
                # Subir calidad_stars si está baja
                current_stars = lead.get("calidad_stars") or 1
                if int(current_stars) < 4:
                    update_data["calidad_stars"] = int(current_stars) + 1

            # Redes sociales: solo agregar las que no existían
            for field_name in ["facebook_url", "instagram_url", "linkedin_url",
                                "twitter_url", "tiktok_url", "youtube_url"]:
                new_val = social.get(field_name)
                if new_val and not lead.get(field_name):
                    update_data[field_name] = new_val

            # Sitio web descubierto
            if new_website and not lead.get("sitio_web"):
                update_data["sitio_web"] = new_website

            db.table("leads_master").update(update_data).eq("id", lead["id"]).execute()
            logger.debug(
                f"Supabase actualizado: {lead.get('nombre_negocio')} "
                f"→ {email_source} | email={bool(email)} | "
                f"social={sum(1 for v in social.values() if v)}"
            )

        except Exception as e:
            logger.error(f"Error actualizando Supabase para {lead.get('nombre_negocio')}: {e}")

    # ── Pipeline principal por lead ───────────────────────────────────────────

    async def enrich_lead(self, lead: dict, use_apify: bool = False) -> EnrichResult:
        """
        Ejecuta el pipeline completo de enriquecimiento para un lead.

        Args:
            lead: Dict del lead (debe incluir al menos id, nombre_negocio, ciudad, sitio_web)
            use_apify: Si True, intenta Apify como paso 3 (más lento, consume créditos)

        Returns:
            EnrichResult con los datos encontrados.
        """
        lead_id = lead.get("id", "")
        nombre = lead.get("nombre_negocio", "")
        ciudad = (lead.get("ciudad") or "").strip()
        sitio_web = (lead.get("sitio_web") or "").strip()

        result = EnrichResult(lead_id=lead_id, nombre=nombre)

        all_social: dict[str, Optional[str]] = {
            k: lead.get(k)  # Preservar lo que ya existe en DB
            for k in ["facebook_url", "instagram_url", "linkedin_url",
                      "twitter_url", "tiktok_url", "youtube_url"]
        }
        found_email: Optional[str] = None
        email_source = "not_found"
        website_for_amf: Optional[str] = sitio_web

        async with self._get_semaphore():
            try:
                # ── PASO 1: Scraping del sitio web propio ──────────────────
                if sitio_web:
                    logger.debug(f"[Paso 1] Scrapeando {sitio_web} para '{nombre}'")
                    scraped = await self._scrape_website(sitio_web)

                    for net, url_val in scraped["social"].items():
                        if url_val and not all_social.get(net):
                            all_social[net] = url_val

                    if scraped["emails"]:
                        found_email = scraped["emails"][0]
                        email_source = "web_found"
                        logger.info(f"✅ [Paso 1] Email web: {found_email} ← '{nombre}'")

                # ── PASO 2: Búsqueda DuckDuckGo ────────────────────────────
                if not found_email:
                    logger.debug(f"[Paso 2] DuckDuckGo: '{nombre}' en '{ciudad}'")
                    ddg = await self._duckduckgo_search(nombre, ciudad)

                    for net, url_val in ddg["social"].items():
                        if url_val and not all_social.get(net):
                            all_social[net] = url_val

                    if ddg["emails"]:
                        found_email = ddg["emails"][0]
                        email_source = "google_found"
                        logger.info(f"✅ [Paso 2] Email búsqueda: {found_email} ← '{nombre}'")

                    # Si encontró un sitio web que no teníamos, scrapear también
                    if ddg["website"] and not sitio_web:
                        website_for_amf = ddg["website"]
                        result.website_found = ddg["website"]

                        if not found_email:
                            logger.debug(f"[Paso 2b] Scrapeando sitio descubierto: {ddg['website']}")
                            scraped2 = await self._scrape_website(ddg["website"])
                            for net, url_val in scraped2["social"].items():
                                if url_val and not all_social.get(net):
                                    all_social[net] = url_val
                            if scraped2["emails"]:
                                found_email = scraped2["emails"][0]
                                email_source = "web_found"
                                logger.info(f"✅ [Paso 2b] Email sitio descubierto: {found_email} ← '{nombre}'")

                # ── PASO 3: Apify fallback (opcional) ──────────────────────
                if not found_email and use_apify:
                    logger.debug(f"[Paso 3] Apify: '{nombre}' en '{ciudad}'")
                    apify_data = await self._apify_place_search(nombre, ciudad, use_apify=True)

                    if apify_data["emails"]:
                        found_email = apify_data["emails"][0]
                        email_source = "apify_found"
                        logger.info(f"✅ [Paso 3] Email Apify: {found_email} ← '{nombre}'")

                    if apify_data["facebook_url"] and not all_social.get("facebook_url"):
                        all_social["facebook_url"] = apify_data["facebook_url"]
                    if apify_data["instagram_url"] and not all_social.get("instagram_url"):
                        all_social["instagram_url"] = apify_data["instagram_url"]

                    if apify_data["website"] and not website_for_amf:
                        website_for_amf = apify_data["website"]
                        result.website_found = apify_data["website"]

                # ── PASO 4: AnyMailFinder ───────────────────────────────────
                if not found_email:
                    domain: Optional[str] = None
                    if website_for_amf:
                        parsed = urlparse(website_for_amf)
                        domain = parsed.netloc.lstrip("www.") if parsed.netloc else None

                    logger.debug(f"[Paso 4] AnyMailFinder: '{nombre}' (dominio: {domain})")
                    amf_email = await self._anymail_fallback(domain, nombre, ciudad)
                    if amf_email:
                        found_email = amf_email
                        email_source = "amf_found"
                        logger.info(f"✅ [Paso 4] Email AMF: {found_email} ← '{nombre}'")

                # ── PASO 5: Guardar en Supabase ─────────────────────────────
                await self._update_supabase(
                    lead=lead,
                    email=found_email,
                    email_source=email_source,
                    social=all_social,
                    new_website=result.website_found,
                )

                result.email_found = found_email
                result.email_source = email_source
                result.social = all_social

            except Exception as e:
                logger.error(f"Error en pipeline para '{nombre}' ({lead_id}): {e}")
                result.error = str(e)

        return result

    # ── Consulta de leads a enriquecer ────────────────────────────────────────

    async def get_leads_to_enrich(
        self,
        cliente_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Obtiene leads de leads_master que necesitan enriquecimiento:
        - Sin email O email de proveedor gratuito (gmail, hotmail, etc.)
        - calidad_stars < 5 (NO tocar leads verificados con 5 estrellas)

        Args:
            cliente_id: Filtrar por cliente. None = todos los clientes.
            limit: Número máximo de leads a devolver.

        Returns:
            Lista de dicts con los campos del lead.
        """
        db = get_db()

        try:
            query = db.table("leads_master").select(
                "id, nombre_negocio, ciudad, estado, sitio_web, email, "
                "lead_score, calidad_stars, email_status, "
                "facebook_url, instagram_url, linkedin_url, "
                "twitter_url, tiktok_url, youtube_url"
            )

            if cliente_id:
                query = query.eq("cliente_id", cliente_id)

            # Traer más de los necesarios para poder filtrar en Python
            # (la lógica de free email es más fácil en Python que en SQL)
            raw = query.limit(limit * 4).execute()
            leads_raw = raw.data or []

            filtered: list[dict] = []
            for lead in leads_raw:
                # Excluir leads con 5 estrellas (ya verificados — no tocar)
                stars = lead.get("calidad_stars") or 0
                if int(stars) >= 5:
                    continue

                # Incluir si no tiene email O si el email es de proveedor gratuito
                email = (lead.get("email") or "").strip()
                if not email or is_free_email(email):
                    filtered.append(lead)

                if len(filtered) >= limit:
                    break

            logger.info(
                f"get_leads_to_enrich: {len(leads_raw)} leads consultados → "
                f"{len(filtered)} a enriquecer (limit={limit})"
            )
            return filtered

        except Exception as e:
            logger.error(f"Error obteniendo leads para enriquecimiento: {e}")
            return []

    # ── Procesamiento en lote ─────────────────────────────────────────────────

    async def run_batch(
        self,
        leads: list[dict],
        progress_callback=None,
        use_apify: bool = False,
    ) -> dict:
        """
        Procesa un lote de leads con control de concurrencia.
        Llama a progress_callback cada 10 leads procesados.

        Args:
            leads: Lista de leads a procesar.
            progress_callback: async fn(stats, done, total) — llamada cada 10 leads.
            use_apify: Si True activa Apify como paso 3 (más lento, consume créditos).

        Returns:
            Dict de estadísticas: {total, procesados, email_encontrado,
                                   solo_social, no_encontrado, errores}
        """
        stats = {
            "total": len(leads),
            "procesados": 0,
            "email_encontrado": 0,
            "solo_social": 0,
            "no_encontrado": 0,
            "errores": 0,
        }

        async def process_one(lead: dict) -> None:
            try:
                enrich_result = await self.enrich_lead(lead, use_apify=use_apify)

                if enrich_result.error:
                    stats["errores"] += 1
                elif enrich_result.has_email:
                    stats["email_encontrado"] += 1
                elif enrich_result.has_social:
                    stats["solo_social"] += 1
                else:
                    stats["no_encontrado"] += 1

            except Exception as e:
                logger.error(f"Error procesando '{lead.get('nombre_negocio')}': {e}")
                stats["errores"] += 1
            finally:
                stats["procesados"] += 1
                if progress_callback and stats["procesados"] % 10 == 0:
                    try:
                        await progress_callback(
                            dict(stats),
                            stats["procesados"],
                            len(leads),
                        )
                    except Exception as cb_err:
                        logger.debug(f"Error en progress_callback: {cb_err}")

        # Procesar en paralelo respetando MAX_CONCURRENT (controlado por semáforo)
        tasks = [process_one(lead) for lead in leads]
        await asyncio.gather(*tasks, return_exceptions=True)

        return stats


# ── Instancia global (singleton) ─────────────────────────────────────────────
web_enricher = WebEnricher()
