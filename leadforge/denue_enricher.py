"""
LeadForge — DENUE Enricher
Cliente oficial de la API DENUE (INEGI) para enriquecimiento de leads en México.

Endpoints verificados (2026-03-16):
  GET /Buscar/{termino}/{lat},{lon}/{metros}/{token}
      → Busca por coordenadas dentro de un radio (max 5,000m)
  GET /BuscarEntidad/{termino}/{entidad}/{start}/{end}/{token}
      → Busca por nombre/actividad en un estado (código 01-32)
  GET /BuscarAreaAct/{entidad}/{municipio}/0/0/0/{sector}/{subsector}/{rama}/{clase}/{nombre}/{start}/{end}/0/{token}
      → Busca por código SCIAN (sector, subsector, rama, clase)
  GET /Ficha/{id}/{token}
      → Detalle completo de un establecimiento

Respuesta DENUE — campos clave:
  CLEE           → ID único del establecimiento
  Nombre         → Nombre comercial
  Razon_social   → Razón social legal
  Clase_actividad → Descripción actividad SCIAN
  Estrato        → Tamaño (0-5 personas, 6-10, etc.)
  Telefono       → Teléfono
  Correo_e       → Email
  Sitio_internet → Página web
  Latitud / Longitud → Coordenadas GPS

Uso:
  from leadforge.denue_enricher import DenueEnricher, calcular_calidad_stars
  enricher = DenueEnricher()
  establecimientos = await enricher.buscar_por_estado("cantera", "19", 1, 100)
"""
import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import cfg
from .supabase_client import get_db, insert_lead_master

logger = logging.getLogger(__name__)

DENUE_BASE = "https://www.inegi.org.mx/app/api/denue/v1/consulta"

# ── Códigos de entidad (estados) ─────────────────────────────────────────────
ESTADO_CODES: dict[str, str] = {
    "aguascalientes": "01",
    "baja california": "02",
    "baja california sur": "03",
    "campeche": "04",
    "coahuila": "05",
    "colima": "06",
    "chiapas": "07",
    "chihuahua": "08",
    "ciudad de mexico": "09",
    "cdmx": "09",
    "df": "09",
    "durango": "10",
    "guanajuato": "11",
    "guerrero": "12",
    "hidalgo": "13",
    "jalisco": "14",
    "mexico": "15",
    "estado de mexico": "15",
    "edomex": "15",
    "michoacan": "16",
    "michoacán": "16",
    "morelos": "17",
    "nayarit": "18",
    "nuevo leon": "19",
    "nuevo león": "19",
    "nl": "19",
    "oaxaca": "20",
    "puebla": "21",
    "queretaro": "22",
    "querétaro": "22",
    "quintana roo": "23",
    "san luis potosi": "24",
    "san luis potosí": "24",
    "sinaloa": "25",
    "sonora": "26",
    "tabasco": "27",
    "tamaulipas": "28",
    "tlaxcala": "29",
    "veracruz": "30",
    "yucatan": "31",
    "yucatán": "31",
    "zacatecas": "32",
}

# ── Términos DENUE para industria minera (target Regio Cribas) ───────────────
TERMINOS_MINERIA = [
    "cantera",
    "arenera",
    "pedrera",
    "gravera",
    "trituradora",
    "arena",
    "grava",
    "marmol",
    "caliza",
    "extraccion",
]

# ── Sectores SCIAN relevantes ─────────────────────────────────────────────────
SCIAN_MINERIA = "21"         # Sector: Minería
SCIAN_NO_METALICOS = "212"   # Subsector: Minería de minerales no metálicos
SCIAN_ARENA_GRAVA = "2123"   # Rama: Arena, grava y arcilla

# ── Catálogo multi-sector para /denue [estado] [categoria] ────────────────────
SECTORES_DENUE: dict[str, dict] = {
    "mineria": {
        "label": "Minería",
        "scian_sector": "21", "scian_subsector": "212", "scian_rama": "2123",
        "terminos": ["cantera", "arenera", "pedrera", "gravera", "trituradora",
                     "arena", "grava", "marmol", "caliza", "extraccion"],
        "categoria_default": "Minería / Extracción",
        "descripcion": "canteras, areneras, pedreras, graveras, trituradoras",
    },
    "constructoras": {
        "label": "Construcción",
        "scian_sector": "23", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["constructora", "desarrolladora", "fraccionamiento",
                     "edificacion", "obra civil", "vivienda"],
        "categoria_default": "Construcción",
        "descripcion": "constructoras, desarrolladoras, fraccionamientos",
    },
    "ferreterias": {
        "label": "Ferreterías / Tlapalerías",
        "scian_sector": "46", "scian_subsector": "467", "scian_rama": "4671",
        "terminos": ["ferreteria", "tlapaleria", "materiales construccion",
                     "materiales para construccion"],
        "categoria_default": "Ferretería / Materiales",
        "descripcion": "ferreterías, tlapalerías, materiales de construcción",
    },
    "mantenimiento": {
        "label": "Mantenimiento Industrial",
        "scian_sector": "81", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["mantenimiento industrial", "pintura industrial",
                     "contratista industrial", "servicios industriales"],
        "categoria_default": "Mantenimiento Industrial",
        "descripcion": "mantenimiento industrial, pintura industrial, contratistas",
    },
    "albercas": {
        "label": "Albercas / Piscinas",
        "scian_sector": "0", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["alberca", "piscina", "mantenimiento alberca",
                     "construccion alberca"],
        "categoria_default": "Albercas / Piscinas",
        "descripcion": "albercas, piscinas, mantenimiento de albercas",
    },
    "arquitectos": {
        "label": "Arquitectos / Diseño",
        "scian_sector": "54", "scian_subsector": "541", "scian_rama": "5413",
        "terminos": ["arquitecto", "despacho arquitectura", "diseño interior",
                     "interiorista"],
        "categoria_default": "Arquitectura / Diseño",
        "descripcion": "arquitectos, despachos de arquitectura, diseñadores",
    },
    "hoteles": {
        "label": "Hoteles / Restaurantes",
        "scian_sector": "72", "scian_subsector": "721", "scian_rama": "0",
        "terminos": ["hotel", "restaurante", "plaza comercial", "hospedaje"],
        "categoria_default": "Hotelería / Restaurantes",
        "descripcion": "hoteles, restaurantes, plazas comerciales",
    },
    "molinera": {
        "label": "Alimentos / Molineras",
        "scian_sector": "31", "scian_subsector": "311", "scian_rama": "0",
        "terminos": ["molinera", "arrocera", "azucarera", "aceite vegetal",
                     "fertilizadora", "procesadora granos"],
        "categoria_default": "Alimentos / Molinería",
        "descripcion": "molineras, arroceras, azucareras, aceiteras",
    },
    "porcicultura": {
        "label": "Porcicultura / Ganadería",
        "scian_sector": "11", "scian_subsector": "112", "scian_rama": "1122",
        "terminos": ["granja porcina", "porcicultura", "ganaderia porcina",
                     "cerdos", "engorda"],
        "categoria_default": "Ganadería Porcina",
        "descripcion": "granjas porcinas, integradores porcícolas",
    },
    "automotriz": {
        "label": "Manufactura Automotriz",
        "scian_sector": "33", "scian_subsector": "336", "scian_rama": "0",
        "terminos": ["automotriz", "autopartes", "manufactura automotriz",
                     "tier 1", "tier 2"],
        "categoria_default": "Automotriz / Manufactura",
        "descripcion": "plantas automotrices, Tier 1, Tier 2, autopartes",
    },
    "cnc": {
        "label": "CNC / Metal-Mecánica Industrial",
        "scian_sector": "33", "scian_subsector": "332", "scian_rama": "0",
        "terminos": ["maquinado cnc", "taller cnc", "maquinado industrial",
                     "troquelado", "metal mecanica", "mecanizado",
                     "fabricacion piezas", "fresado", "tornos cnc",
                     "estampado metal", "corte laser industrial"],
        "categoria_default": "CNC / Metal-Mecánica",
        "descripcion": "talleres CNC, maquinado industrial, troquelado, fresado",
    },
    "alimentos": {
        "label": "Plantas de Alimentos / Bebidas",
        "scian_sector": "31", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["planta alimentos", "procesadora alimentos",
                     "empacadora", "planta lacteos", "rastro tif",
                     "procesadora carne", "planta bebidas",
                     "panificadora industrial", "congeladora industrial",
                     "planta embutidos", "planta tortilla industrial"],
        "categoria_default": "Planta de Alimentos / Bebidas",
        "descripcion": "plantas procesadoras de alimentos, empacadoras, lácteos, cárnicos",
    },
    "flotas": {
        "label": "Empresas de Transporte / Flotas",
        "scian_sector": "48", "scian_subsector": "484", "scian_rama": "0",
        "terminos": ["transporte de carga", "empresa transporte",
                     "flotilla camiones", "logistica carga",
                     "carga consolidada", "transporte refrigerado",
                     "tracto camion", "arrendadora vehiculos"],
        "categoria_default": "Transporte / Flotas",
        "descripcion": "empresas de transporte, flotillas, logística de carga",
    },
    "agregados": {
        "label": "Agregados / Concreto",
        "scian_sector": "23", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["concreto", "agregados", "arena construccion",
                     "planta concreto", "block"],
        "categoria_default": "Agregados / Concreto",
        "descripcion": "plantas de concreto, agregados pétreos",
    },
    "recicladora": {
        "label": "Reciclaje / Plásticos",
        "scian_sector": "32", "scian_subsector": "325", "scian_rama": "0",
        "terminos": ["recicladora", "reciclaje plastico", "pellets", "hule"],
        "categoria_default": "Reciclaje / Plásticos",
        "descripcion": "recicladoras de plástico, procesadoras de pellets",
    },
    "fundidora": {
        "label": "Fundición / Metal Mecánica",
        "scian_sector": "33", "scian_subsector": "331", "scian_rama": "0",
        "terminos": ["fundidora", "metal mecanica", "forja", "maquinado",
                     "fundicion"],
        "categoria_default": "Fundición / Metal Mecánica",
        "descripcion": "fundidoras, talleres de maquinado, forjas",
    },
    "pintores": {
        "label": "Pintores / Acabados",
        "scian_sector": "23", "scian_subsector": "238", "scian_rama": "0",
        "terminos": ["pintor", "pintura exterior", "acabados",
                     "servicio pintura", "contratista pintura"],
        "categoria_default": "Pintores / Acabados",
        "descripcion": "pintores profesionales, contratistas de acabados",
    },
    "pinturas": {
        "label": "Pinturas / Recubrimientos (clientes)",
        "scian_sector": "23", "scian_subsector": "0", "scian_rama": "0",
        "terminos": ["constructora", "ferreteria", "mantenimiento industrial",
                     "pintor", "administradora condominios"],
        "categoria_default": "Cliente Pinturas",
        "descripcion": "constructoras, ferreterías, mantenimiento industrial",
    },
    "condominios": {
        "label": "Administradoras de Condominios",
        "scian_sector": "53", "scian_subsector": "531", "scian_rama": "0",
        "terminos": ["administradora condominios", "administracion condominios",
                     "condominio", "fraccionamiento privado", "residencial"],
        "categoria_default": "Administradora de Condominios",
        "descripcion": "administradoras de condominios, fraccionamientos privados",
    },
}


# ============================================================
# DATACLASS: ESTABLECIMIENTO DENUE
# ============================================================
@dataclass
class DenueEstablecimiento:
    """Representa un establecimiento del padrón DENUE/INEGI."""
    clee: str             # Clave única INEGI (CLEE)
    denue_id: str         # Id numérico interno
    nombre: str           # Nombre comercial
    razon_social: str     # Razón social
    clase_actividad: str  # Descripción SCIAN
    estrato: str          # Tamaño de la empresa
    calle: str
    num_exterior: str
    colonia: str
    cp: str
    municipio_raw: str    # Ciudad/municipio del campo Ubicacion
    estado_raw: str       # Estado del campo Ubicacion
    telefono: str
    email: str
    sitio_web: str
    latitud: Optional[float]
    longitud: Optional[float]

    @property
    def ciudad(self) -> str:
        """Ciudad limpia desde campo Ubicacion."""
        return self.municipio_raw.title()

    @property
    def estado(self) -> str:
        """Estado limpio."""
        return self.estado_raw.title()

    @property
    def direccion_completa(self) -> str:
        """Construye dirección formateada."""
        partes = []
        if self.calle:
            partes.append(self.calle.title())
        if self.num_exterior:
            partes.append(f"#{self.num_exterior}")
        if self.colonia:
            partes.append(f"Col. {self.colonia.title()}")
        if self.cp:
            partes.append(f"CP {self.cp}")
        return ", ".join(partes) if partes else ""

    @classmethod
    def from_dict(cls, d: dict) -> "DenueEstablecimiento":
        ubicacion = d.get("Ubicacion", "")
        partes_ub = [p.strip() for p in ubicacion.split(",")]
        municipio_raw = partes_ub[0] if partes_ub else ""
        estado_raw = partes_ub[-1] if len(partes_ub) > 1 else ""

        lat: Optional[float] = None
        lon: Optional[float] = None
        try:
            lat_raw = d.get("Latitud", "")
            lon_raw = d.get("Longitud", "")
            if lat_raw:
                lat = float(lat_raw)
            if lon_raw:
                lon = float(lon_raw)
        except (ValueError, TypeError):
            pass

        return cls(
            clee=d.get("CLEE", ""),
            denue_id=d.get("Id", ""),
            nombre=d.get("Nombre", "").strip().title(),
            razon_social=d.get("Razon_social", "").strip(),
            clase_actividad=d.get("Clase_actividad", ""),
            estrato=d.get("Estrato", ""),
            calle=d.get("Calle", ""),
            num_exterior=d.get("Num_Exterior", ""),
            colonia=d.get("Colonia", ""),
            cp=d.get("CP", ""),
            municipio_raw=municipio_raw,
            estado_raw=estado_raw,
            telefono=d.get("Telefono", ""),
            email=d.get("Correo_e", "").strip().lower(),
            sitio_web=d.get("Sitio_internet", "").strip().lower(),
            latitud=lat,
            longitud=lon,
        )


# ============================================================
# UTILIDAD: DISTANCIA HAVERSINE
# ============================================================
def _distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas GPS (fórmula Haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# ============================================================
# SISTEMA DE CALIDAD 1-5 ESTRELLAS
# ============================================================
def calcular_calidad_stars(lead: dict, denue_confirmado: bool = False) -> int:
    """
    Calidad de un lead en escala 1-5 estrellas.

    ★     (1) — Solo nombre y ciudad. Sin contacto.
    ★★    (2) — Tiene teléfono O email (sin verificar).
    ★★★   (3) — Teléfono + dirección O DENUE confirmado con coords.
    ★★★★  (4) — Email verificado (valid) + teléfono.
    ★★★★★ (5) — Dos fuentes (DENUE + Apify) + email valid + teléfono + web.
    """
    tiene_email = bool(lead.get("email"))
    email_valid = lead.get("email_status") in ("valid",)
    tiene_tel = bool(lead.get("telefono"))
    tiene_web = bool(lead.get("sitio_web"))
    tiene_dir = bool(lead.get("direccion"))
    tiene_owner = bool(lead.get("owner_name"))
    tiene_coords = bool(lead.get("latitud") and lead.get("longitud"))
    tiene_razon = bool(lead.get("razon_social"))
    denue_ok = denue_confirmado or bool(lead.get("denue_confirmado"))
    tiene_apify = bool(lead.get("apify_run_id"))
    fuente = lead.get("fuente_datos", "")
    dos_fuentes = (denue_ok and tiene_apify) or ("+" in fuente)

    # ── Score base ───────────────────────────────────────────
    if dos_fuentes and email_valid and tiene_tel and (tiene_web or tiene_owner):
        return 5
    if email_valid and tiene_tel:
        return 4
    if tiene_tel and (tiene_dir or tiene_coords or tiene_razon) and (tiene_email or denue_ok):
        return 3
    if tiene_email or tiene_tel:
        return 2
    return 1


# ============================================================
# CLIENTE DENUE
# ============================================================
class DenueEnricher:
    """
    Cliente asíncrono para la API DENUE del INEGI.
    Autenticación: token en la URL (no header).
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or cfg.denue_api_key
        if not self.token:
            raise ValueError(
                "DENUE_API_KEY no configurada. Agrega al .env:\n"
                "DENUE_API_KEY=YOUR_DENUE_API_KEY"
            )

    async def _get(self, endpoint: str) -> Optional[list]:
        """GET genérico a la API DENUE. Retorna lista de dicts o None."""
        url = f"{DENUE_BASE}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return [data]
                    return []
                logger.warning(f"DENUE HTTP {resp.status_code}: {url}")
                return None
        except httpx.TimeoutException:
            logger.warning(f"DENUE timeout: {url}")
            return None
        except Exception as e:
            logger.error(f"DENUE error en {url}: {e}")
            return None

    # ── Endpoints públicos ────────────────────────────────────

    async def buscar_por_coordenadas(
        self,
        lat: float,
        lon: float,
        metros: int = 500,
        termino: str = "0",
    ) -> list[DenueEstablecimiento]:
        """
        Establecimientos dentro de un radio geográfico.
        termino='0' → todos los tipos de negocio.
        Máximo permitido: 5,000 metros.
        """
        metros = max(50, min(metros, 5000))
        endpoint = f"Buscar/{termino}/{lat},{lon}/{metros}/{self.token}"
        raw = await self._get(endpoint)
        if not raw:
            return []
        return [DenueEstablecimiento.from_dict(d) for d in raw if isinstance(d, dict)]

    async def buscar_por_estado(
        self,
        termino: str,
        entidad: str,
        start: int = 1,
        end: int = 100,
    ) -> list[DenueEstablecimiento]:
        """
        Busca por nombre/actividad en un estado.
        entidad: código 2 dígitos (ej. '19' = Nuevo León).
        Máximo 200 registros por llamada.
        """
        end = min(end, 200)
        endpoint = f"BuscarEntidad/{termino}/{entidad}/{start}/{end}/{self.token}"
        raw = await self._get(endpoint)
        if not raw:
            return []
        return [DenueEstablecimiento.from_dict(d) for d in raw if isinstance(d, dict)]

    async def buscar_por_actividad_scian(
        self,
        entidad: str,
        municipio: str = "0",
        sector: str = "0",
        subsector: str = "0",
        rama: str = "0",
        clase: str = "0",
        nombre: str = "0",
        start: int = 1,
        end: int = 200,
    ) -> list[DenueEstablecimiento]:
        """
        Búsqueda por clasificación SCIAN.
        Ejemplo minería: sector='21', subsector='212', rama='2123'
        """
        end = min(end, 200)
        endpoint = (
            f"BuscarAreaAct/{entidad}/{municipio}/0/0/0/"
            f"{sector}/{subsector}/{rama}/{clase}/"
            f"{nombre}/{start}/{end}/0/{self.token}"
        )
        raw = await self._get(endpoint)
        if not raw:
            return []
        return [DenueEstablecimiento.from_dict(d) for d in raw if isinstance(d, dict)]

    async def ficha(self, denue_id: str) -> Optional[DenueEstablecimiento]:
        """Detalle completo de un establecimiento específico."""
        endpoint = f"Ficha/{denue_id}/{self.token}"
        raw = await self._get(endpoint)
        if raw and isinstance(raw[0], dict):
            return DenueEstablecimiento.from_dict(raw[0])
        return None

    # ── Matching por nombre ───────────────────────────────────

    def _similitud_jaccard(self, texto_a: str, texto_b: str) -> float:
        """Similitud Jaccard por palabras entre dos textos."""
        palabras_a = set(texto_a.lower().split())
        palabras_b = set(texto_b.lower().split())
        union = palabras_a | palabras_b
        if not union:
            return 0.0
        return len(palabras_a & palabras_b) / len(union)

    def encontrar_mejor_match(
        self,
        nombre_lead: str,
        establecimientos: list[DenueEstablecimiento],
        umbral: float = 0.5,
    ) -> Optional[DenueEstablecimiento]:
        """
        Retorna el establecimiento DENUE con mayor similitud de nombre.
        Umbral mínimo: 0.5 (50% de palabras coincidentes).
        """
        mejor: Optional[DenueEstablecimiento] = None
        mejor_score = 0.0

        for est in establecimientos:
            score = self._similitud_jaccard(nombre_lead, est.nombre)
            # Bonus si la razón social también coincide
            if est.razon_social:
                score_rs = self._similitud_jaccard(nombre_lead, est.razon_social)
                score = max(score, score_rs * 0.9)
            if score > mejor_score:
                mejor_score = score
                mejor = est

        if mejor and mejor_score >= umbral:
            logger.debug(
                f"Match DENUE: '{nombre_lead}' → '{mejor.nombre}' "
                f"(score={mejor_score:.2f})"
            )
            return mejor
        return None

    # ── Enriquecimiento de leads existentes ──────────────────

    async def enriquecer_lead(
        self,
        lead_id: str,
        nombre_negocio: str,
        ciudad: str,
        estado: str,
    ) -> dict:
        """
        Enriquece un lead de leads_master con datos DENUE.
        Estrategia: busca por primera palabra del nombre en el estado.
        """
        entidad = ESTADO_CODES.get(estado.lower().strip())
        if not entidad:
            # Intentar normalizar
            for key, code in ESTADO_CODES.items():
                if key in estado.lower():
                    entidad = code
                    break

        if not entidad:
            logger.warning(f"Estado '{estado}' no reconocido para DENUE")
            return {"status": "estado_no_reconocido", "lead_id": lead_id}

        # Buscar con la primera palabra significativa del nombre
        palabras = [p for p in nombre_negocio.split() if len(p) > 3]
        termino_busqueda = palabras[0][:20] if palabras else nombre_negocio[:15]

        establecimientos = await self.buscar_por_estado(
            termino=termino_busqueda,
            entidad=entidad,
            start=1,
            end=50,
        )

        if not establecimientos:
            return {"status": "no_resultados", "lead_id": lead_id}

        # Filtrar por ciudad si es posible
        ciudad_lower = ciudad.lower()
        filtrados = [
            e for e in establecimientos
            if ciudad_lower in e.municipio_raw.lower()
        ]
        candidatos = filtrados if filtrados else establecimientos

        match = self.encontrar_mejor_match(nombre_negocio, candidatos)
        if not match:
            return {"status": "sin_coincidencia", "lead_id": lead_id}

        return await self._actualizar_lead_master(lead_id, match)

    async def _actualizar_lead_master(
        self,
        lead_id: str,
        est: DenueEstablecimiento,
    ) -> dict:
        """Aplica datos DENUE a un registro en leads_master."""
        db = get_db()
        mejoras = []

        update_data: dict = {
            "denue_id": est.clee,
            "denue_confirmado": True,
            "fuente_datos": "apify+denue",
            "razon_social": est.razon_social or None,
        }

        if est.latitud:
            update_data["latitud"] = est.latitud
            update_data["longitud"] = est.longitud
            mejoras.append("coordenadas")

        if est.telefono:
            update_data["telefono"] = est.telefono
            mejoras.append("telefono")

        if est.email:
            update_data["email"] = est.email
            update_data["email_status"] = "pendiente_validacion"
            mejoras.append("email")

        if est.sitio_web:
            update_data["sitio_web"] = est.sitio_web
            mejoras.append("sitio_web")

        if est.direccion_completa:
            update_data["direccion"] = est.direccion_completa
            mejoras.append("direccion")

        try:
            # Obtener datos actuales para calcular stars
            current_resp = db.table("leads_master").select(
                "email, email_status, telefono, sitio_web, direccion, "
                "owner_name, apify_run_id, razon_social, latitud, longitud"
            ).eq("id", lead_id).limit(1).execute()

            current = current_resp.data[0] if current_resp.data else {}
            merged = {**current, **update_data}
            stars = calcular_calidad_stars(merged, denue_confirmado=True)
            update_data["calidad_stars"] = stars

            db.table("leads_master").update(update_data).eq("id", lead_id).execute()

            logger.info(
                f"✅ DENUE → lead {lead_id}: {est.nombre} | "
                f"{stars}⭐ | mejoras: {mejoras}"
            )
            return {
                "status": "enriquecido",
                "lead_id": lead_id,
                "denue_nombre": est.nombre,
                "calidad_stars": stars,
                "mejoras": mejoras,
            }

        except Exception as e:
            logger.error(f"Error actualizando lead {lead_id} con DENUE: {e}")
            return {"status": "error", "lead_id": lead_id, "error": str(e)}

    # ── Ingesta masiva de minería ─────────────────────────────

    async def ingestar_mineria(
        self,
        cliente_id: str,
        estado: str = "Nuevo León",
        municipio: str = "0",
    ) -> dict:
        """
        Ingesta masiva de establecimientos mineros desde DENUE.
        Target: Regio Cribas / Malla Cribas — canteras, areneras, pedreras.

        Estrategia dual:
          1. Búsqueda SCIAN sector 21 (Minería)
          2. Búsqueda por términos de nombre (cantera, arenera, etc.)
        """
        entidad = ESTADO_CODES.get(estado.lower().strip(), "19")
        logger.info(f"🏗️ DENUE: ingestando minería | entidad={entidad} ({estado})")

        todos: list[DenueEstablecimiento] = []

        # 1. Búsqueda por SCIAN minería
        por_scian = await self.buscar_por_actividad_scian(
            entidad=entidad,
            municipio=municipio,
            sector=SCIAN_MINERIA,
            subsector=SCIAN_NO_METALICOS,
            rama=SCIAN_ARENA_GRAVA,
            start=1,
            end=200,
        )
        todos.extend(por_scian)
        logger.info(f"  SCIAN 2123: {len(por_scian)} establecimientos")

        # 2. Búsqueda por términos de nombre
        for termino in TERMINOS_MINERIA:
            lote = await self.buscar_por_estado(termino, entidad, start=1, end=100)
            todos.extend(lote)
            logger.info(f"  '{termino}': {len(lote)} resultados")
            await asyncio.sleep(0.4)  # Respetar rate limit INEGI

        # Deduplicar por CLEE
        vistos: set[str] = set()
        unicos: list[DenueEstablecimiento] = []
        for est in todos:
            if est.clee and est.clee not in vistos:
                vistos.add(est.clee)
                unicos.append(est)

        logger.info(f"Total únicos DENUE minería: {len(unicos)}")

        # Insertar/actualizar en leads_master
        insertados = 0
        actualizados = 0
        db = get_db()

        for est in unicos:
            lead_id = insert_lead_master(
                cliente_id=cliente_id,
                nombre_negocio=est.nombre,
                categoria=est.clase_actividad or "Minería / Extracción",
                ciudad=est.ciudad,
                estado=est.estado,
                pais="MX",
                direccion=est.direccion_completa or None,
                telefono=est.telefono or None,
                email=est.email or None,
                email_status="pendiente_validacion" if est.email else None,
                sitio_web=est.sitio_web or None,
            )

            if lead_id:
                # Actualizar campos DENUE específicos (no en insert_lead_master)
                stars_data = {
                    "email": est.email,
                    "telefono": est.telefono,
                    "sitio_web": est.sitio_web,
                    "latitud": est.latitud,
                    "razon_social": est.razon_social,
                }
                stars = calcular_calidad_stars(stars_data, denue_confirmado=True)

                try:
                    db.table("leads_master").update({
                        "denue_id": est.clee,
                        "razon_social": est.razon_social or None,
                        "latitud": est.latitud,
                        "longitud": est.longitud,
                        "denue_confirmado": True,
                        "fuente_datos": "denue",
                        "calidad_stars": stars,
                    }).eq("id", lead_id).execute()
                    insertados += 1
                except Exception as e:
                    logger.debug(f"DENUE campos extra: {e}")
            else:
                actualizados += 1

        resultado = {
            "estado": estado,
            "entidad_code": entidad,
            "encontrados_denue": len(unicos),
            "insertados_nuevos": insertados,
            "ya_existian": actualizados,
            "total_procesados": insertados + actualizados,
        }
        logger.info(
            f"✅ DENUE minería: {insertados} nuevos | "
            f"{actualizados} ya existían | estado={estado}"
        )
        return resultado

    # ── Ingesta genérica por sector ───────────────────────────────────────────

    async def ingestar_sector(
        self,
        cliente_id: str,
        estado: str = "Nuevo León",
        categoria: str = "mineria",
        municipio: str = "0",
    ) -> dict:
        """
        Ingesta masiva de establecimientos por sector/categoría desde DENUE.
        Usa SECTORES_DENUE para determinar SCIAN codes y términos de búsqueda.

        Uso:
          await enricher.ingestar_sector(cliente_id, estado="Nuevo León",
                                         categoria="constructoras")
        """
        cat_key = categoria.lower().strip()
        cfg_sector = SECTORES_DENUE.get(cat_key)
        if not cfg_sector:
            available = ", ".join(SECTORES_DENUE.keys())
            raise ValueError(
                f"Categoría '{categoria}' no reconocida. "
                f"Disponibles: {available}"
            )

        entidad = ESTADO_CODES.get(estado.lower().strip(), "19")
        # Normalización parcial
        if entidad == "19":
            for key, code in ESTADO_CODES.items():
                if key in estado.lower():
                    entidad = code
                    break

        logger.info(
            f"🏗️ DENUE: ingestando {cfg_sector['label']} | "
            f"entidad={entidad} ({estado})"
        )

        todos: list[DenueEstablecimiento] = []

        # 1. Búsqueda por SCIAN (si el sector tiene código definido)
        if cfg_sector["scian_sector"] != "0":
            por_scian = await self.buscar_por_actividad_scian(
                entidad=entidad,
                municipio=municipio,
                sector=cfg_sector["scian_sector"],
                subsector=cfg_sector["scian_subsector"],
                rama=cfg_sector["scian_rama"],
                start=1,
                end=200,
            )
            todos.extend(por_scian)
            logger.info(
                f"  SCIAN {cfg_sector['scian_sector']}: "
                f"{len(por_scian)} establecimientos"
            )

        # 2. Búsqueda por términos de nombre
        for termino in cfg_sector["terminos"]:
            lote = await self.buscar_por_estado(termino, entidad, start=1, end=100)
            todos.extend(lote)
            logger.info(f"  '{termino}': {len(lote)} resultados")
            await asyncio.sleep(0.4)

        # Deduplicar por CLEE
        vistos: set[str] = set()
        unicos: list[DenueEstablecimiento] = []
        for est in todos:
            if est.clee and est.clee not in vistos:
                vistos.add(est.clee)
                unicos.append(est)

        logger.info(
            f"Total únicos DENUE {cfg_sector['label']}: {len(unicos)}"
        )

        # Insertar/actualizar en leads_master
        insertados = 0
        actualizados = 0
        db = get_db()

        for est in unicos:
            lead_id = insert_lead_master(
                cliente_id=cliente_id,
                nombre_negocio=est.nombre,
                categoria=est.clase_actividad or cfg_sector["categoria_default"],
                ciudad=est.ciudad,
                estado=est.estado,
                pais="MX",
                direccion=est.direccion_completa or None,
                telefono=est.telefono or None,
                email=est.email or None,
                email_status="pendiente_validacion" if est.email else None,
                sitio_web=est.sitio_web or None,
            )

            if lead_id:
                stars_data = {
                    "email": est.email,
                    "telefono": est.telefono,
                    "sitio_web": est.sitio_web,
                    "latitud": est.latitud,
                    "razon_social": est.razon_social,
                }
                stars = calcular_calidad_stars(stars_data, denue_confirmado=True)
                try:
                    db.table("leads_master").update({
                        "denue_id": est.clee,
                        "razon_social": est.razon_social or None,
                        "latitud": est.latitud,
                        "longitud": est.longitud,
                        "denue_confirmado": True,
                        "fuente_datos": "denue",
                        "calidad_stars": stars,
                    }).eq("id", lead_id).execute()
                    insertados += 1
                except Exception as e:
                    logger.debug(f"DENUE campos extra: {e}")
            else:
                actualizados += 1

        resultado = {
            "estado": estado,
            "entidad_code": entidad,
            "categoria": cfg_sector["label"],
            "encontrados_denue": len(unicos),
            "insertados_nuevos": insertados,
            "ya_existian": actualizados,
            "total_procesados": insertados + actualizados,
        }
        logger.info(
            f"✅ DENUE {cfg_sector['label']}: {insertados} nuevos | "
            f"{actualizados} ya existían | estado={estado}"
        )
        return resultado


# ============================================================
# FUNCIÓN DE ALTO NIVEL: BATCH ENRIQUECIMIENTO
# ============================================================
async def batch_enriquecer_leads(
    cliente_id: str,
    estado: str = "Nuevo León",
    limit: int = 50,
) -> dict:
    """
    Enriquece en lote leads de leads_master que no tienen datos DENUE.
    Úsalo para mejorar leads que ya tienes de Apify pero les falta
    teléfono, coordenadas o email oficial.

    Args:
        cliente_id: UUID del cliente
        estado: Estado para la búsqueda DENUE
        limit: Cuántos leads procesar por vez
    """
    db = get_db()
    enricher = DenueEnricher()

    # Leads sin DENUE del estado indicado
    result = db.table("leads_master").select(
        "id, nombre_negocio, ciudad, estado, email, telefono, sitio_web"
    ).eq(
        "cliente_id", cliente_id
    ).is_(
        "denue_id", "null"
    ).limit(limit).execute()

    leads = result.data or []
    logger.info(f"Leads sin DENUE para enriquecer: {len(leads)}")

    stats = {
        "total": len(leads),
        "enriquecidos": 0,
        "sin_match": 0,
        "errores": 0,
    }

    for lead in leads:
        lead_estado = lead.get("estado") or estado
        try:
            res = await enricher.enriquecer_lead(
                lead_id=lead["id"],
                nombre_negocio=lead["nombre_negocio"],
                ciudad=lead.get("ciudad") or "",
                estado=lead_estado,
            )
            if res.get("status") == "enriquecido":
                stats["enriquecidos"] += 1
            else:
                stats["sin_match"] += 1
        except Exception as e:
            logger.error(f"Error enriching {lead['nombre_negocio']}: {e}")
            stats["errores"] += 1

        await asyncio.sleep(0.25)  # Rate limit amigable con INEGI

    logger.info(
        f"✅ DENUE batch: {stats['enriquecidos']} enriquecidos | "
        f"{stats['sin_match']} sin match | {stats['errores']} errores"
    )
    return stats


# ============================================================
# FUNCIÓN AUXILIAR: Cargar leads sin email para denue_enricher.py legacy
# ============================================================
def sb_get_leads_sin_email(limit: int = 50, offset: int = 0) -> list[dict]:
    """Obtiene leads sin email para enriquecimiento (compatible legacy)."""
    db = get_db()
    try:
        result = db.table("leads_master").select(
            "id, nombre_negocio, ciudad, estado, telefono"
        ).is_(
            "email", "null"
        ).range(offset, offset + limit - 1).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error obteniendo leads sin email: {e}")
        return []


# Instancia global
denue = DenueEnricher() if cfg.denue_api_key else None
