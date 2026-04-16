"""
LeadForge — Email Builder
Construye emails personalizados para cada lead usando datos reales del negocio.

Características:
  - Template de 2 emails (presentación + follow-up mismo hilo)
  - Variables dinámicas por lead: nombre del negocio, dueño, ciudad, etc.
  - Claude genera el pitch por categoría (cacheado: 1 call por categoría, no por lead)
  - Personalización profunda: "Estimado Carlos" en lugar de "Estimado propietario"
  - Generación de subject lines A/B para testing automático
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from ..config import cfg

logger = logging.getLogger(__name__)

# ============================================================
# CACHÉ DE PITCHES POR CATEGORÍA
# (evita llamar a Claude por cada lead — 1 vez por categoría)
# ============================================================
_PITCH_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "pitch_cache.json"
_pitch_cache: dict[str, dict] = {}


def _load_pitch_cache() -> None:
    global _pitch_cache
    if _PITCH_CACHE_FILE.exists():
        try:
            _pitch_cache = json.loads(_PITCH_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _pitch_cache = {}


def _save_pitch_cache() -> None:
    _PITCH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PITCH_CACHE_FILE.write_text(
        json.dumps(_pitch_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_load_pitch_cache()


# ============================================================
# CONFIGURACIÓN DE CAMPAÑA
# ============================================================
@dataclass
class CampaignConfig:
    """Configuración completa de una campaña de email."""
    nombre_campana: str
    producto: str                        # "Desengrasantes industriales biodegradables"
    empresa_vendedora: str               # "DesenGras MX"
    link_cal: str                        # "https://cal.com/zenon/15min"
    firma: str                           # "Zenon González\nDirector Comercial"
    subject_email1: str                  # Asunto del primer email
    instantly_campaign_id: str           # ID de la campaña en Instantly.ai
    daily_limit: int = 100              # Emails máximos por día en esta campaña
    cliente_id: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: str) -> "CampaignConfig":
        """Carga configuración desde archivo YAML."""
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> "CampaignConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================
# GENERADOR DE PITCH CON CLAUDE (cacheado por categoría)
# ============================================================

async def generate_pitch_for_category(
    categoria: str,
    producto: str,
    pitch_num: int = 1,
) -> str:
    """
    Genera una línea de pitch personalizada para una categoría de negocio.
    El resultado se cachea para no re-llamar a Claude por cada lead.

    Args:
        categoria: tipo de negocio ("taller mecánico", "ferretería", etc.)
        producto: descripción del producto que se vende
        pitch_num: 1 = pitch principal email 1, 2 = ángulo email 2

    Returns:
        Texto de 15-25 palabras listo para insertar en el email.
    """
    cache_key = f"{categoria}|{producto}|{pitch_num}"

    if cache_key in _pitch_cache:
        logger.debug(f"Pitch desde caché: {categoria}")
        return _pitch_cache[cache_key]

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    if pitch_num == 1:
        prompt = f"""Eres un copywriter B2B experto en ventas para México.
Producto: "{producto}"
Tipo de negocio comprador: "{categoria}"

Escribe UNA oración de 15-20 palabras en español (México) que explique
POR QUÉ este tipo de negocio específicamente se beneficia de este producto.
Debe ser directa, creíble, sin exageración ni signos de exclamación.
Solo la oración, sin comillas ni explicación."""

    else:  # email 2 - ángulo diferente
        prompt = f"""Eres un copywriter B2B experto en ventas para México.
Producto: "{producto}"
Tipo de negocio comprador: "{categoria}"

Ya enviamos un primer email. Escribe UNA oración de 12-18 palabras con
un ÁNGULO DIFERENTE al beneficio del producto para este tipo de negocio.
Enfócate en una ventaja que no mencionaste antes (costo, medio ambiente,
facilidad, competidores que ya lo usan, etc.).
Solo la oración, sin comillas."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        pitch = message.content[0].text.strip().strip('"\'')
        _pitch_cache[cache_key] = pitch
        _save_pitch_cache()
        logger.info(f"Pitch generado para '{categoria}': {pitch}")
        return pitch

    except Exception as e:
        logger.error(f"Error generando pitch: {e}")
        fallback = (
            f"nos especializamos en proveer {producto.lower()} "
            f"para negocios como el suyo"
        )
        return fallback


# ============================================================
# TEMPLATES DE EMAIL
# ============================================================

# Saludo inteligente: "Estimado Carlos" si hay nombre, "Estimados" si no
def _build_salutation(owner_name: Optional[str], negocio: str) -> str:
    if owner_name:
        primer_nombre = owner_name.split()[0]
        return f"Estimado {primer_nombre}"
    return f"Estimados directivos de {negocio}"


def build_email1(
    lead: dict,
    config: CampaignConfig,
    pitch_linea: str,
) -> tuple[str, str]:
    """
    Construye el email de presentación (Email #1).
    Returns: (subject, body)
    """
    nombre_negocio = lead.get("nombre_negocio", "su negocio")
    owner_name = lead.get("owner_name")
    ciudad = lead.get("ciudad", "")
    categoria = lead.get("categoria", "su giro")

    saludo = _build_salutation(owner_name, nombre_negocio)

    body = f"""{saludo},

Nos comunicamos desde {config.empresa_vendedora} porque creemos que {pitch_linea}.

Trabajamos con {config.producto} y nos gustaría que conocieran las ventajas \
que podemos ofrecerles a {nombre_negocio}{f' en {ciudad}' if ciudad else ''}.

Para que puedan evaluar sin compromiso, les dejo este link para agendar \
una videollamada de 15 minutos a la hora que mejor les convenga:

{config.link_cal}

Quedamos atentos a su respuesta.

{config.firma}"""

    return config.subject_email1, body


def build_email2(
    lead: dict,
    config: CampaignConfig,
    pitch_secundario: str,
) -> tuple[str, str]:
    """
    Construye el email de seguimiento (Email #2, mismo hilo).
    Subject vacío = continúa en el mismo hilo en Instantly.
    Returns: (subject, body)  — subject siempre vacío para mismo hilo
    """
    owner_name = lead.get("owner_name")
    nombre_negocio = lead.get("nombre_negocio", "su negocio")
    saludo = _build_salutation(owner_name, nombre_negocio)

    body = f"""{saludo},

Quizá mi correo anterior no llegó en buen momento y no quisiera \
que se perdieran de esta oportunidad.

{pitch_secundario}

El link para agendar una llamada rápida sigue disponible:

{config.link_cal}

{config.firma}"""

    return "", body  # Subject vacío = mismo hilo en Instantly


# ============================================================
# DATOS DE LEAD PARA INSTANTLY.AI
# ============================================================
@dataclass
class InstantlyLead:
    """Estructura de lead lista para enviar a Instantly.ai API."""
    email: str
    first_name: str
    last_name: str
    company_name: str
    personalization: str        # primera línea personalizada (el pitch)
    custom_variables: dict      # variables adicionales para el template

    def to_instantly_payload(self) -> dict:
        """Convierte al formato exacto que espera Instantly.ai API."""
        return {
            "email": self.email,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "companyName": self.company_name,
            "personalization": self.personalization,
            **{f"custom{i+1}": v for i, v in enumerate(self.custom_variables.values())},
        }


async def prepare_lead_for_instantly(
    lead: dict,
    config: CampaignConfig,
) -> InstantlyLead:
    """
    Prepara todos los datos personalizados de un lead para Instantly.ai.
    Genera el pitch de la categoría (desde caché si ya existe).
    """
    categoria = lead.get("categoria", "negocio")
    owner_name = lead.get("owner_name", "")

    # Obtener pitch (desde caché o generar con Claude)
    pitch_1 = await generate_pitch_for_category(categoria, config.producto, 1)
    pitch_2 = await generate_pitch_for_category(categoria, config.producto, 2)

    # Separar nombre del propietario
    nombre_parts = (owner_name or "").strip().split()
    first_name = nombre_parts[0] if nombre_parts else "Propietario"
    last_name = " ".join(nombre_parts[1:]) if len(nombre_parts) > 1 else ""

    return InstantlyLead(
        email=lead["email"],
        first_name=first_name,
        last_name=last_name,
        company_name=lead.get("nombre_negocio", ""),
        personalization=pitch_1,   # primera línea personalizada por categoría
        custom_variables={
            "tipo_negocio": categoria,
            "ciudad": lead.get("ciudad", ""),
            "link_cal": config.link_cal,
            "empresa_vendedora": config.empresa_vendedora,
            "pitch_secundario": pitch_2,
            "firma": config.firma,
        },
    )


# ============================================================
# GENERADOR DE A/B SUBJECTS
# ============================================================

async def generate_ab_subjects(
    categoria: str,
    producto: str,
) -> tuple[str, str]:
    """
    Genera 2 versiones del subject line para A/B testing.
    Instantly.ai puede manejar A/B automáticamente.
    """
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    prompt = f"""Genera 2 asuntos de email en español para cold outreach B2B.
Producto: "{producto}"
Negocio destino: "{categoria}"

Requisitos:
- Máximo 8 palabras cada uno
- Sin spam words (GRATIS, URGENTE, etc.)
- Diferentes entre sí (uno directo, uno con pregunta)
- En español de México, profesional pero amigable

Responde SOLO JSON: {{"version_a": "...", "version_b": "..."}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        import re
        text = message.content[0].text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return data.get("version_a", ""), data.get("version_b", "")
    except Exception as e:
        logger.error(f"Error generando A/B subjects: {e}")

    return f"{producto[:30]} para su negocio", f"¿Le interesa conocer {producto[:25]}?"
