"""
LeadForge — Apify Scraper
Actor: compass/google-maps-extractor — $4.00/1,000 lugares scrapeados.

ESTRATEGIA: UN solo run de Apify con TODOS los términos expandidos en
searchStringsArray y locationQuery a nivel estado. Resultado: ~19 segundos
en lugar de correr un run por ciudad por término (que multiplicaba el tiempo).

Los emails se enriquecen por separado vía Anymail Finder.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import cfg

logger = logging.getLogger(__name__)

# ─── Input para compass/google-maps-extractor ──────────────────────────────
# scrapeContacts=False → evitamos el add-on $0.003/evento (Anymail lo hace)
# scrapeSocialMediaProfiles=False → evitamos add-on $0.01/evento
# Solo datos base de Google Maps: nombre, teléfono, web, rating, dirección
_ACTOR_INPUT_BASE = {
    "includeWebResults": False,
    "language": "es",
    "maximumLeadsEnrichmentRecords": 0,
    "scrapeContacts": True,           # emails desde sitio web ($0.003/evento)
    "scrapeDirectories": False,
    "scrapePlaceDetailPage": False,
    "scrapeReviewsPersonalData": False,
    "scrapeSocialMediaProfiles": {
        "facebooks": True,            # Facebook/WhatsApp ($0.01/perfil encontrado)
        "instagrams": True,           # Instagram ($0.01/perfil encontrado)
        "tiktoks": False,
        "twitters": False,
        "youtubes": False,
    },
    "scrapeTableReservationProvider": False,
    "skipClosedPlaces": False,
    "maxReviews": 0,
    "maxImages": 0,
}


# ============================================================
# RESULTADO DEL SCRAPER
# ============================================================
@dataclass
class NegocioRaw:
    """Datos crudos de un negocio tal como vienen de Apify."""
    nombre: str
    categoria: str
    ciudad: str
    estado: str
    pais: str
    direccion: str
    telefono: Optional[str]
    email: Optional[str]
    sitio_web: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    facebook_url: Optional[str]
    instagram_url: Optional[str]
    reviews_text: list[str]
    termino_busqueda: str
    apify_run_id: str
    raw_data: dict

    @property
    def tiene_email(self) -> bool:
        return bool(self.email and "@" in self.email)

    @property
    def tiene_telefono(self) -> bool:
        return bool(self.telefono and len(self.telefono) >= 7)

    @property
    def tiene_social(self) -> bool:
        return bool(self.facebook_url or self.instagram_url)


# ============================================================
# CLIENTE DE APIFY
# ============================================================
class ApifyScraper:
    BASE_URL = "https://api.apify.com/v2"
    POLL_INTERVAL = 5       # segundos entre polls
    TIMEOUT_MINUTES = 12    # timeout máximo — runs grandes pueden tardar 5-8 min

    def __init__(self):
        self.token = cfg.apify_token
        # Actor slug: compass~google-maps-extractor (tilde = slash en URL de API)
        self.actor_id = cfg.apify_actor_id
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _build_input(self, terminos: list[str], location: str, max_per_term: int) -> dict:
        """
        Construye el input para compass/google-maps-extractor.
        Todos los términos van en searchStringsArray — UN solo run.
        max_per_term = número de lugares por cada término de búsqueda.
        """
        return {
            **_ACTOR_INPUT_BASE,
            "searchStringsArray": terminos,
            "locationQuery": location,
            "maxCrawledPlacesPerSearch": max_per_term,
        }

    async def _run_actor(self, input_data: dict) -> Optional[str]:
        """Inicia un run y devuelve el run_id."""
        url = f"{self.BASE_URL}/acts/{self.actor_id}/runs"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json=input_data)
            if resp.status_code == 403:
                raise RuntimeError(
                    "Apify rechazó el run (403) — revisa el límite de gasto en "
                    "console.apify.com → Billing → Spending limits"
                )
            resp.raise_for_status()
            run_id = resp.json()["data"]["id"]
            logger.info(f"Apify run iniciado: {run_id} | actor: {self.actor_id}")
            return run_id

    async def _wait_for_completion(self, run_id: str) -> bool:
        """Espera a que el run termine. Devuelve True si fue exitoso.
        Maneja errores 5xx transitorios de Apify con reintento automático.
        """
        import time
        url = f"{self.BASE_URL}/actor-runs/{run_id}"
        deadline = time.time() + (self.TIMEOUT_MINUTES * 60)
        consecutive_errors = 0
        MAX_ERRORS = 5  # máximo de errores 5xx consecutivos antes de abortar

        async with httpx.AsyncClient(timeout=15) as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(url, headers=self.headers)

                    # Errores 5xx (502, 503, 504…) = Apify temporalmente no disponible
                    # Reintentar en lugar de abortar
                    if resp.status_code >= 500:
                        consecutive_errors += 1
                        logger.warning(
                            f"Run {run_id}: Apify devolvió {resp.status_code} "
                            f"(error #{consecutive_errors}/{MAX_ERRORS}) — reintentando en {self.POLL_INTERVAL}s..."
                        )
                        if consecutive_errors >= MAX_ERRORS:
                            logger.error(
                                f"Run {run_id}: {MAX_ERRORS} errores 5xx consecutivos — "
                                f"intentando obtener dataset parcial..."
                            )
                            return "PARTIAL"
                        await asyncio.sleep(self.POLL_INTERVAL)
                        continue

                    # Errores 4xx = problema real, abortar
                    resp.raise_for_status()
                    consecutive_errors = 0  # reset contador en respuesta exitosa

                    data = resp.json()["data"]
                    status = data.get("status", "")

                    if status == "SUCCEEDED":
                        stats = data.get("stats", {})
                        logger.info(
                            f"Run {run_id} completado — "
                            f"{stats.get('itemCount', '?')} items | "
                            f"${data.get('usageTotalUsd', 0):.4f} USD"
                        )
                        return True
                    elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                        logger.error(f"Run {run_id} terminó con status: {status}")
                        return False

                    logger.debug(f"Run {run_id}: {status} — esperando {self.POLL_INTERVAL}s...")
                    await asyncio.sleep(self.POLL_INTERVAL)

                except httpx.TimeoutException:
                    consecutive_errors += 1
                    logger.warning(
                        f"Run {run_id}: timeout de conexión a Apify "
                        f"(#{consecutive_errors}/{MAX_ERRORS}) — reintentando..."
                    )
                    if consecutive_errors >= MAX_ERRORS:
                        return "PARTIAL"
                    await asyncio.sleep(self.POLL_INTERVAL)

        logger.warning(
            f"Run {run_id}: timeout después de {self.TIMEOUT_MINUTES} min — "
            f"intentando obtener resultados parciales del dataset..."
        )
        return "PARTIAL"

    async def _get_dataset_items(self, run_id: str) -> list[dict]:
        """Obtiene los resultados del dataset del run."""
        url = f"{self.BASE_URL}/actor-runs/{run_id}/dataset/items"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                url, headers=self.headers,
                params={"format": "json", "clean": "true"}
            )
            resp.raise_for_status()
            data = resp.json()

            if data is None:
                logger.warning(f"Dataset del run {run_id} devolvió null")
                return []
            if isinstance(data, dict):
                items = data.get("items") or []
                return items if isinstance(items, list) else []
            if isinstance(data, list):
                return data
            logger.warning(f"Dataset formato inesperado: {type(data)}")
            return []

    def _parse_item(self, item: dict, termino: str, run_id: str) -> Optional[NegocioRaw]:
        """Convierte un item raw de Apify en un NegocioRaw."""
        nombre = (item.get("title") or "").strip()
        if not nombre:
            return None

        # Emails: el actor puede incluirlos aunque scrapeContacts=False (del perfil público)
        emails = item.get("emails") or []
        email = emails[0] if emails else None

        # Teléfono: limpiar a solo dígitos y +
        telefono_raw = item.get("phone") or ""
        telefono = "".join(c for c in str(telefono_raw) if c.isdigit() or c == "+") or None

        # Website
        website = item.get("website") or item.get("domain") or None
        if website and not str(website).startswith("http"):
            website = f"https://{website}"

        # Social media (pueden venir vacíos si scrapeContacts=False)
        facebooks = item.get("facebooks") or []
        instagrams = item.get("instagrams") or []

        # Reseñas del dueño
        reviews = item.get("reviews") or []
        owner_responses = [
            r.get("responseFromOwnerText", "")
            for r in reviews
            if r.get("responseFromOwnerText")
        ]

        # Término: usar el que está en el item si existe, sino el pasado
        termino_usado = item.get("searchString") or termino

        return NegocioRaw(
            nombre=nombre,
            categoria=item.get("categoryName") or "",
            ciudad=item.get("city") or "",
            estado=item.get("state") or "",
            pais=item.get("countryCode") or "MX",
            direccion=item.get("address") or item.get("street") or "",
            telefono=telefono,
            email=email,
            sitio_web=website,
            rating=item.get("totalScore"),
            review_count=item.get("reviewsCount"),
            facebook_url=facebooks[0] if facebooks else None,
            instagram_url=instagrams[0] if instagrams else None,
            reviews_text=owner_responses,
            termino_busqueda=termino_usado,
            apify_run_id=run_id,
            raw_data=item,
        )

    async def scrape_all_terms(
        self,
        terminos: list[str],
        location: str,
        max_per_term: int = 50,
    ) -> list[NegocioRaw]:
        """
        UN SOLO RUN de Apify con todos los términos en searchStringsArray.
        El actor busca cada término y devuelve max_per_term resultados por término.
        Resultado: N_terminos × max_per_term lugares en ~19-30 segundos.

        Ej: 5 términos × 20 lugares = hasta 100 lugares en un run.
        """
        if not terminos:
            return []

        logger.info(
            f"Apify scrape: {len(terminos)} términos en '{location}' "
            f"(max {max_per_term} c/u → hasta {len(terminos)*max_per_term} total)"
        )
        input_data = self._build_input(terminos, location, max_per_term)

        run_id = await self._run_actor(input_data)
        if not run_id:
            return []

        success = await self._wait_for_completion(run_id)
        if success is False:
            return []

        if success == "PARTIAL":
            logger.warning(f"Run {run_id}: leyendo dataset parcial (run aún activo en Apify)...")

        items = await self._get_dataset_items(run_id)
        logger.info(f"Apify devolvió {len(items)} resultados raw")

        negocios = [n for item in items if (n := self._parse_item(item, terminos[0], run_id))]

        # Deduplicar por teléfono y dominio
        seen_phones: set[str] = set()
        seen_domains: set[str] = set()
        unique: list[NegocioRaw] = []

        for neg in negocios:
            dominio = None
            if neg.sitio_web:
                try:
                    dominio = urlparse(neg.sitio_web).netloc.replace("www.", "").lower()
                except Exception:
                    pass

            is_dup = (
                (neg.telefono and neg.telefono in seen_phones) or
                (dominio and dominio in seen_domains)
            )

            if not is_dup:
                unique.append(neg)
                if neg.telefono:
                    seen_phones.add(neg.telefono)
                if dominio:
                    seen_domains.add(dominio)

        removed = len(negocios) - len(unique)
        if removed:
            logger.info(f"Deduplicación: {removed} duplicados eliminados")
        logger.info(f"Resultado final: {len(unique)} negocios únicos")

        return unique

    # Alias para compatibilidad con pipeline.py existente
    async def scrape_multi_term(
        self,
        terminos: list[str],
        location: str,
        max_places: int = 50,
    ) -> list[NegocioRaw]:
        """
        Alias de scrape_all_terms. Mantiene compatibilidad con pipeline.py.
        max_places = total deseado. Se divide entre los términos.
        """
        max_per_term = max(10, max_places // max(len(terminos), 1))
        return await self.scrape_all_terms(terminos, location, max_per_term)

    async def scrape(
        self,
        termino: str,
        location: str,
        max_places: int = 50,
    ) -> list[NegocioRaw]:
        """Scraping para un solo término. Usa scrape_all_terms internamente."""
        return await self.scrape_all_terms([termino], location, max_places)


# Instancia global
apify = ApifyScraper()
