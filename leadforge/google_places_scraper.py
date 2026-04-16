"""
google_places_scraper.py
═══════════════════════════════════════════════════════════════
Reemplazo directo de apify_scraper.py para LeadForge/ZenonFinder
Usa Google Places API con rotación automática de 4 keys
Mantiene exactamente la misma interfaz que ApifyScraper

INSTALACIÓN:
    pip install requests

CONFIGURACIÓN en .env:
    GOOGLE_KEY_1=AIzaSyBWFPELXm7OG...   # goodmantech.com.mx
    GOOGLE_KEY_2=AIzaSyD4QTa5vpGfh...   # ia-ingenieria.com
    GOOGLE_KEY_3=AIzaSyAaD4TwKqtFaz...  # quimicainteligente.com.mx
    GOOGLE_KEY_4=AIzaSyAZ5tphhWdi...    # esgconsultores.com.mx

USO (idéntico al original):
    scraper = GooglePlacesScraper()
    negocios = await scraper.scrape_multi_term(
        terminos=["taller mecanico", "refaccionaria"],
        ciudad="Monterrey",
        estado="Nuevo León",
        max_per_term=20
    )
═══════════════════════════════════════════════════════════════
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─── MODELO DE DATOS (idéntico a NegocioRaw original) ────────────────────────

@dataclass
class NegocioRaw:
    nombre:          str
    telefono:        Optional[str] = None
    sitio_web:       Optional[str] = None
    direccion:       Optional[str] = None
    ciudad:          Optional[str] = None
    estado:          Optional[str] = None
    pais:            str = "MX"
    categoria:       Optional[str] = None
    rating:          Optional[float] = None
    review_count:    int = 0
    google_maps_url: Optional[str] = None
    facebook_url:    Optional[str] = None
    instagram_url:   Optional[str] = None
    email:           Optional[str] = None
    termino_busqueda: Optional[str] = None
    apify_run_id:    Optional[str] = "google_places"  # compatibilidad
    emails:          list = field(default_factory=list)


# ─── ROTADOR DE KEYS ──────────────────────────────────────────────────────────

class KeyRotator:
    """
    Rota entre las 4 API keys automáticamente.
    Si una falla por quota, pasa a la siguiente sin interrumpir el scraping.
    """

    def __init__(self):
        self.keys = []
        self.usage = {}
        self.exhausted = set()
        self._load_keys()
        self._current = 0

    def _load_keys(self):
        for i in range(1, 10):  # soporta hasta 9 keys
            key = os.getenv(f"GOOGLE_KEY_{i}")
            if key and key.strip():
                self.keys.append(key.strip())
                self.usage[key.strip()] = 0
        if not self.keys:
            raise ValueError(
                "❌ No se encontraron keys de Google Places. "
                "Agrega GOOGLE_KEY_1, GOOGLE_KEY_2... en tu .env"
            )
        logger.info(f"✅ KeyRotator iniciado con {len(self.keys)} keys")

    def get_key(self) -> Optional[str]:
        """Retorna la siguiente key disponible en round-robin."""
        available = [k for k in self.keys if k not in self.exhausted]
        if not available:
            logger.error("❌ Todas las keys de Google Places están agotadas")
            return None

        key = available[self._current % len(available)]
        self._current += 1
        self.usage[key] = self.usage.get(key, 0) + 1
        return key

    def mark_exhausted(self, key: str):
        """Marca una key como agotada (quota excedida)."""
        self.exhausted.add(key)
        logger.warning(
            f"⚠️  Key ...{key[-8:]} agotada. "
            f"Keys restantes: {len(self.keys) - len(self.exhausted)}"
        )

    def status(self) -> dict:
        return {
            "total_keys": len(self.keys),
            "activas": len(self.keys) - len(self.exhausted),
            "agotadas": len(self.exhausted),
            "uso_por_key": {f"...{k[-8:]}": v for k, v in self.usage.items()}
        }


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────────────────

class GooglePlacesScraper:
    """
    Reemplazo directo de ApifyScraper.
    Misma interfaz, cero cambios en pipeline.py
    """

    BASE_URL = "https://places.googleapis.com/v1/places:searchText"

    def __init__(self):
        self.rotator = KeyRotator()
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── Método principal (igual que el original) ──────────────────────────────

    async def scrape_multi_term(
        self,
        terminos: list[str],
        ciudad: str,
        estado: str,
        max_per_term: int = 20,
        pais: str = "México"
    ) -> list[NegocioRaw]:
        """
        Scrapea múltiples términos y retorna lista unificada de NegocioRaw.
        Idéntico al método original de ApifyScraper.
        """
        logger.info(
            f"🔍 Google Places scraping: {len(terminos)} términos "
            f"en {ciudad}, {estado}"
        )

        all_negocios = []
        seen = set()  # deduplicación por nombre+teléfono

        tasks = [
            self._scrape_term(termino, ciudad, estado, max_per_term, pais)
            for termino in terminos
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for termino, result in zip(terminos, results):
            if isinstance(result, Exception):
                logger.error(f"❌ Error en término '{termino}': {result}")
                continue
            for negocio in result:
                key = f"{negocio.nombre}|{negocio.telefono}"
                if key not in seen:
                    seen.add(key)
                    all_negocios.append(negocio)

        logger.info(
            f"✅ Total negocios únicos encontrados: {len(all_negocios)}"
        )
        return all_negocios

    # ── Scraping por término individual ───────────────────────────────────────

    async def _scrape_term(
        self,
        termino: str,
        ciudad: str,
        estado: str,
        max_results: int,
        pais: str
    ) -> list[NegocioRaw]:
        """Busca un término específico en Google Places."""

        query = f"{termino} en {ciudad}, {estado}, {pais}"
        negocios = []
        next_page_token = None
        fetched = 0

        while fetched < max_results:
            key = self.rotator.get_key()
            if not key:
                break

            batch_size = min(20, max_results - fetched)
            payload = {
                "textQuery": query,
                "maxResultCount": batch_size,
                "languageCode": "es",
                "regionCode": "MX",
            }
            if next_page_token:
                payload["pageToken"] = next_page_token

            headers = {
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": (
                    "places.id,"
                    "places.displayName,"
                    "places.formattedAddress,"
                    "places.nationalPhoneNumber,"
                    "places.internationalPhoneNumber,"
                    "places.websiteUri,"
                    "places.rating,"
                    "places.userRatingCount,"
                    "places.primaryTypeDisplayName,"
                    "places.addressComponents,"
                    "places.googleMapsUri,"
                    "places.nextPageToken"
                )
            }

            try:
                # Google Places API es síncrona — corremos en executor
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.session.post(
                        self.BASE_URL,
                        json=payload,
                        headers=headers,
                        timeout=15
                    )
                )

                if response.status_code == 429:
                    logger.warning(f"⚠️  Quota excedida en key ...{key[-8:]}")
                    self.rotator.mark_exhausted(key)
                    await asyncio.sleep(1)
                    continue

                if response.status_code != 200:
                    logger.error(
                        f"❌ Error {response.status_code} "
                        f"para '{termino}': {response.text[:200]}"
                    )
                    break

                data = response.json()
                places = data.get("places", [])

                if not places:
                    break

                for place in places:
                    negocio = self._parse_place(place, termino, ciudad, estado)
                    if negocio:
                        negocios.append(negocio)

                fetched += len(places)
                next_page_token = data.get("nextPageToken")

                if not next_page_token or len(places) < batch_size:
                    break

                # Pausa breve para respetar rate limits
                await asyncio.sleep(0.3)

            except requests.exceptions.Timeout:
                logger.warning(f"⏱️  Timeout en '{termino}', reintentando...")
                await asyncio.sleep(2)
                continue
            except Exception as e:
                logger.error(f"❌ Excepción en '{termino}': {e}")
                break

        logger.debug(f"  '{termino}': {len(negocios)} negocios")
        return negocios

    # ── Parser de resultado individual ────────────────────────────────────────

    def _parse_place(
        self,
        place: dict,
        termino: str,
        ciudad_busqueda: str,
        estado_busqueda: str
    ) -> Optional[NegocioRaw]:
        """Convierte un resultado de Google Places a NegocioRaw."""

        try:
            nombre = place.get("displayName", {}).get("text", "")
            if not nombre:
                return None

            # Extraer componentes de dirección
            components = place.get("addressComponents", [])
            ciudad  = self._get_component(components, "locality") or ciudad_busqueda
            estado  = self._get_component(components, "administrative_area_level_1") or estado_busqueda
            pais    = self._get_component(components, "country") or "MX"

            # Teléfono — preferir formato nacional
            telefono = (
                place.get("nationalPhoneNumber") or
                place.get("internationalPhoneNumber")
            )

            # Sitio web — limpiar trailing slash
            sitio_web = place.get("websiteUri", "").rstrip("/") or None

            # Categoría
            categoria = place.get("primaryTypeDisplayName", {}).get("text")

            return NegocioRaw(
                nombre           = nombre,
                telefono         = telefono,
                sitio_web        = sitio_web,
                direccion        = place.get("formattedAddress"),
                ciudad           = ciudad,
                estado           = estado,
                pais             = pais,
                categoria        = categoria,
                rating           = place.get("rating"),
                review_count     = place.get("userRatingCount", 0),
                google_maps_url  = place.get("googleMapsUri"),
                termino_busqueda = termino,
                emails           = [],
            )

        except Exception as e:
            logger.warning(f"⚠️  Error parseando lugar: {e}")
            return None

    def _get_component(self, components: list, comp_type: str) -> Optional[str]:
        """Extrae un componente de dirección por tipo."""
        for comp in components:
            if comp_type in comp.get("types", []):
                return comp.get("longText") or comp.get("shortText")
        return None

    def status(self) -> dict:
        """Retorna estado actual del rotador de keys."""
        return self.rotator.status()


# ─── ALIAS para compatibilidad con pipeline.py ────────────────────────────────
# Si tu pipeline.py hace: from apify_scraper import ApifyScraper
# Solo cambia el import a: from google_places_scraper import ApifyScraper

ApifyScraper = GooglePlacesScraper


# ─── PRUEBA RÁPIDA ────────────────────────────────────────────────────────────

async def _test():
    logging.basicConfig(level=logging.INFO)
    scraper = GooglePlacesScraper()

    print("\n📊 Estado del rotador:")
    print(scraper.status())

    print("\n🔍 Probando búsqueda...")
    negocios = await scraper.scrape_multi_term(
        terminos=["taller mecanico", "refaccionaria"],
        ciudad="Monterrey",
        estado="Nuevo León",
        max_per_term=5
    )

    print(f"\n✅ Negocios encontrados: {len(negocios)}")
    for n in negocios[:3]:
        print(f"  • {n.nombre} | {n.telefono} | {n.sitio_web}")


if __name__ == "__main__":
    asyncio.run(_test())
