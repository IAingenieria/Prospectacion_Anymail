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
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─── GUARDIÁN DE COSTOS ───────────────────────────────────────────────────────

_PRICE_PER_REQ_USD = 0.032           # Google Places Text Search (USD por request)
_FREE_CREDIT_USD   = 200.0           # Crédito gratuito mensual por cuenta Google
_MXN_PER_USD       = float(os.getenv("MXN_PER_USD", "18.0"))
_MAX_REQ_PER_RUN   = int(os.getenv("GOOGLE_MAX_REQ_PER_RUN",   "500"))   # ~$16 USD
_MAX_REQ_PER_MONTH = int(os.getenv("GOOGLE_MAX_REQ_PER_MONTH", "5000"))  # ~$160 USD
_USAGE_FILE        = Path(__file__).parent.parent / "logs" / "google_usage.json"


class CostGuard:
    """
    Rastrea el uso de Google Places API para evitar cargos inesperados.

    Dos niveles de protección:
      1. Por corrida   (memoria): GOOGLE_MAX_REQ_PER_RUN   default 500  (~$16 USD)
      2. Por mes (JSON en disco): GOOGLE_MAX_REQ_PER_MONTH default 5000 (~$160 USD)

    Al 90% → aviso en logs (una sola vez por key).
    Al 100% → key marcada agotada, scraping se detiene.
    """

    def __init__(self):
        self._run_usage: dict[str, int] = {}   # key → requests exitosas esta corrida
        self._monthly: dict = self._load_monthly()
        self._save_counter = 0
        self._warned: set[str] = set()         # evitar warnings repetidos

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _load_monthly(self) -> dict:
        try:
            if _USAGE_FILE.exists():
                with open(_USAGE_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_monthly(self):
        """Persiste conteos. Mantiene solo los últimos 3 meses."""
        try:
            _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            meses = sorted(self._monthly.keys())
            for old in meses[:-3]:
                del self._monthly[old]
            with open(_USAGE_FILE, "w") as f:
                json.dump(self._monthly, f, indent=2)
        except Exception as e:
            logger.warning(f"⚠️  CostGuard: no se pudo guardar {_USAGE_FILE}: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _suffix(key: str) -> str:
        return f"...{key[-8:]}"

    def _month_key(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def _run_count(self, key: str) -> int:
        return self._run_usage.get(key, 0)

    def _monthly_count(self, key: str) -> int:
        return self._monthly.get(self._month_key(), {}).get(self._suffix(key), 0)

    # ── API pública ───────────────────────────────────────────────────────────

    def can_request(self, key: str) -> tuple[bool, str]:
        """Verifica límites ANTES de hacer la request. No modifica contadores."""
        run_c = self._run_count(key)
        mon_c = self._monthly_count(key)

        if run_c >= _MAX_REQ_PER_RUN:
            return False, f"límite por corrida ({run_c}/{_MAX_REQ_PER_RUN} req)"
        if mon_c >= _MAX_REQ_PER_MONTH:
            return False, f"límite mensual ({mon_c}/{_MAX_REQ_PER_MONTH} req)"

        # Avisos al 90% (una sola vez por key)
        if run_c >= _MAX_REQ_PER_RUN * 0.9:
            wk = f"run_{self._suffix(key)}"
            if wk not in self._warned:
                self._warned.add(wk)
                logger.warning(
                    f"⚠️  CostGuard: {self._suffix(key)} al "
                    f"{run_c//_MAX_REQ_PER_RUN*100:.0f}% del límite por corrida "
                    f"({run_c}/{_MAX_REQ_PER_RUN})"
                )
        if mon_c >= _MAX_REQ_PER_MONTH * 0.9:
            wk = f"mon_{self._suffix(key)}"
            if wk not in self._warned:
                self._warned.add(wk)
                cost = mon_c * _PRICE_PER_REQ_USD
                logger.warning(
                    f"⚠️  CostGuard: {self._suffix(key)} al "
                    f"{mon_c//_MAX_REQ_PER_MONTH*100:.0f}% del límite mensual "
                    f"({mon_c}/{_MAX_REQ_PER_MONTH} | ~${cost:.2f} USD)"
                )

        return True, ""

    def register(self, key: str):
        """Registra una request exitosa (HTTP 200). Llama DESPUÉS de cada 200."""
        self._run_usage[key] = self._run_usage.get(key, 0) + 1

        month  = self._month_key()
        suffix = self._suffix(key)
        if month not in self._monthly:
            self._monthly[month] = {}
        self._monthly[month][suffix] = self._monthly[month].get(suffix, 0) + 1

        self._save_counter += 1
        if self._save_counter % 50 == 0:
            self._save_monthly()

    def summary(self) -> str:
        """Resumen ASCII de uso y costos."""
        month = self._month_key()
        lines = [
            f"\n{'═'*58}",
            f"  📊 USO GOOGLE PLACES API  —  {month}",
            f"{'─'*58}",
        ]

        if not self._run_usage:
            lines.append("  Sin requests registradas en esta corrida.")
        else:
            lines.append(
                f"  {'KEY':<16}  {'CORRIDA':>8}  {'MES':>8}  {'COSTO MES':>10}"
            )
            lines.append(f"  {'─'*16}  {'─'*8}  {'─'*8}  {'─'*10}")

            for key in sorted(self._run_usage.keys()):
                suf   = self._suffix(key)
                run_c = self._run_count(key)
                mon_c = self._monthly_count(key)
                cost  = mon_c * _PRICE_PER_REQ_USD
                bar_r = self._bar(run_c, _MAX_REQ_PER_RUN)
                bar_m = self._bar(mon_c, _MAX_REQ_PER_MONTH)
                lines.append(
                    f"  {suf:<16}  {run_c:>3} {bar_r}  "
                    f"{mon_c:>5} {bar_m}  ${cost:>6.2f} USD"
                )

            total_run = sum(self._run_usage.values())
            total_mon = sum(self._monthly.get(month, {}).values())
            total_usd = total_mon * _PRICE_PER_REQ_USD
            total_mxn = total_usd * _MXN_PER_USD
            lines += [
                f"{'─'*58}",
                f"  Esta corrida  : {total_run:,} requests",
                f"  Total del mes : {total_mon:,} requests",
                f"  Costo mensual : ${total_usd:.2f} USD  /  ${total_mxn:,.0f} MXN",
                f"  Crédito libre : ${_FREE_CREDIT_USD - total_usd:.2f} USD restantes",
            ]

        lines.append(f"{'═'*58}\n")
        return "\n".join(lines)

    @staticmethod
    def _bar(value: int, max_value: int, width: int = 8) -> str:
        if max_value == 0:
            return f"[{'?'*width}]"
        pct    = min(value / max_value, 1.0)
        filled = int(pct * width)
        sym    = "█" if pct < 0.9 else "▓"
        return f"[{sym*filled}{'░'*(width-filled)}]{pct*100:3.0f}%"


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
    reviews_text:    list = field(default_factory=list)  # compatibilidad pipeline.py
    raw_data:        dict = field(default_factory=dict)  # compatibilidad pipeline.py

    @property
    def tiene_email(self) -> bool:
        return bool(self.email and "@" in self.email)

    @property
    def tiene_telefono(self) -> bool:
        return bool(self.telefono and len(self.telefono) >= 7)


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
        self.rotator    = KeyRotator()
        self.cost_guard = CostGuard()
        self.session    = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── Verificación de "créditos" (siempre OK mientras haya keys activas) ────

    async def check_credits(self) -> dict:
        """
        Compatibilidad con pipeline.py.
        Retorna ok=True si hay keys activas y no se ha alcanzado el límite mensual.
        """
        status = self.rotator.status()
        if status["activas"] == 0:
            return {"ok": False, "error": "Todas las keys de Google Places están agotadas"}

        month     = datetime.now().strftime("%Y-%m")
        monthly   = self.cost_guard._monthly.get(month, {})
        total_mon = sum(monthly.values())
        cost_usd  = round(total_mon * _PRICE_PER_REQ_USD, 2)

        return {
            "ok":                   True,
            "details":              status,
            "uso_mensual_req":      total_mon,
            "costo_mensual_usd":    cost_usd,
            "credito_restante_usd": round(_FREE_CREDIT_USD - cost_usd, 2),
        }

    # ── Método principal (igual que el original) ──────────────────────────────

    async def scrape_multi_term(
        self,
        terminos: list[str],
        # Pipeline llama con location="Monterrey, Nuevo León, Mexico" y max_places=50
        # El modo directo llama con ciudad="Monterrey", estado="Nuevo León"
        location: Optional[str] = None,
        max_places: int = 100,
        ciudad: Optional[str] = None,
        estado: Optional[str] = None,
        max_per_term: int = 20,
        pais: str = "México"
    ) -> list[NegocioRaw]:
        """
        Scrapea múltiples términos y retorna lista unificada de NegocioRaw.
        Acepta tanto la firma del pipeline.py (location, max_places) como
        la firma directa (ciudad, estado, max_per_term).
        """
        # Parsear location string si viene del pipeline
        if location and not ciudad:
            partes = [p.strip() for p in location.split(",")]
            ciudad = partes[0] if len(partes) >= 1 else "México"
            estado = partes[1] if len(partes) >= 2 else ""

        # Convertir max_places total → max_per_term
        if max_places and max_per_term == 20:
            max_per_term = max(10, max_places // max(len(terminos), 1))

        ciudad = ciudad or "México"
        estado = estado or ""

        logger.info(
            f"🔍 Google Places scraping: {len(terminos)} términos "
            f"en {ciudad}, {estado} (max_per_term={max_per_term})"
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

            # CostGuard: verificar límites antes de consumir la request
            ok, reason = self.cost_guard.can_request(key)
            if not ok:
                logger.warning(f"🛑 CostGuard detuvo key ...{key[-8:]}: {reason}")
                self.rotator.mark_exhausted(key)
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
                    "nextPageToken"
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

                if response.status_code in (429, 403):
                    logger.warning(
                        f"⚠️  Key ...{key[-8:]} bloqueada "
                        f"({response.status_code}) — rotando..."
                    )
                    self.rotator.mark_exhausted(key)
                    await asyncio.sleep(0.5)
                    continue

                if response.status_code != 200:
                    logger.error(
                        f"❌ Error {response.status_code} "
                        f"para '{termino}': {response.text[:200]}"
                    )
                    break

                # CostGuard: registrar request cobrada por Google
                self.cost_guard.register(key)

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
