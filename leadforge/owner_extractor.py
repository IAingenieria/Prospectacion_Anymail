"""
LeadForge — Extractor del Nombre del Dueño desde Reseñas de Google Maps
Analiza las respuestas del propietario a reseñas para extraer su nombre.
Convierte "Estimado propietario" en "Estimado Carlos Martínez".
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from .config import cfg

logger = logging.getLogger(__name__)


@dataclass
class OwnerInfo:
    nombre: Optional[str]
    cargo: Optional[str]
    confianza: float          # 0.0 - 1.0
    fuente: str               # "reseña" | "website" | "inferido" | "desconocido"


def _extract_with_patterns(texts: list[str]) -> Optional[tuple[str, str, float]]:
    """
    Intento rápido con regex antes de llamar a Claude.
    Busca patrones comunes de firma en México.
    Devuelve (nombre, cargo, confianza) o None.
    """
    FIRMA_PATTERNS = [
        # "Atentamente, Carlos Martínez — Propietario"
        r"(?:atentamente|saludos|cordialmente)[,.]?\s+([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)+)\s*[—–-]\s*(\w+(?:\s+\w+)?)",
        # "Carlos Martínez, Gerente"
        r"([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)\s*,\s*(gerente|director|propietario|dueño|encargado|administrador|socio|ceo|fundador)",
        # "— Carlos, Propietario"
        r"[—–-]\s*([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?)\s*,\s*(gerente|director|propietario|dueño|encargado)",
    ]

    for text in texts:
        for pattern in FIRMA_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                nombre = match.group(1).strip()
                cargo = match.group(2).strip().capitalize()
                # Validar que parece un nombre real (2+ palabras o una sola > 4 letras)
                if len(nombre.split()) >= 2 or len(nombre) > 4:
                    return nombre, cargo, 0.85

    return None


async def extract_owner_from_reviews(
    reviews_text: list[str],
    business_name: str,
) -> OwnerInfo:
    """
    Extrae el nombre del dueño/encargado de las respuestas a reseñas.

    Strategy:
    1. Intento rápido con regex (sin costo de API)
    2. Si falla, usar Claude para análisis más complejo
    """
    if not reviews_text:
        return OwnerInfo(nombre=None, cargo=None, confianza=0.0, fuente="desconocido")

    # Intentar con patrones regex primero (sin costo)
    regex_result = _extract_with_patterns(reviews_text)
    if regex_result:
        nombre, cargo, confianza = regex_result
        logger.debug(f"Nombre extraído vía regex: {nombre} ({cargo})")
        return OwnerInfo(nombre=nombre, cargo=cargo, confianza=confianza, fuente="reseña")

    # Si regex no encontró nada, usar Claude (solo si hay texto suficiente)
    combined_text = "\n---\n".join(reviews_text[:5])  # máximo 5 respuestas
    if len(combined_text) < 50:
        return OwnerInfo(nombre=None, cargo=None, confianza=0.0, fuente="desconocido")

    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",   # haiku: más barato para tareas simples
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"""Analiza estas respuestas a reseñas de Google Maps del negocio "{business_name}".
Busca si el propietario o encargado firma con su nombre.

Respuestas:
{combined_text}

Responde SOLO con JSON: {{"nombre": "...", "cargo": "...", "confianza": 0.0-1.0}}
Si no hay nombre claro: {{"nombre": null, "cargo": null, "confianza": 0.0}}"""
            }]
        )

        import json
        text = message.content[0].text.strip()
        # Extraer JSON del response
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return OwnerInfo(
                nombre=data.get("nombre"),
                cargo=data.get("cargo"),
                confianza=float(data.get("confianza", 0.0)),
                fuente="reseña",
            )

    except Exception as e:
        logger.warning(f"Error en extracción con Claude para '{business_name}': {e}")

    return OwnerInfo(nombre=None, cargo=None, confianza=0.0, fuente="desconocido")
