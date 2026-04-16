"""
LeadForge — Lead Scorer
Calcula el score compuesto (0-100) de cada lead basado en múltiples señales.
Mayor score = lead más caliente = prioridad en campaña.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class LeadSignals:
    """Todas las señales disponibles para calcular el score."""
    hierarchy_score: int          # 0-100: score del email (ceo@=100, info@=5)
    review_count: Optional[int]   # Número de reseñas en Google Maps
    responds_to_reviews: bool     # ¿El dueño responde a reseñas?
    has_owner_name: bool          # ¿Encontramos el nombre del dueño?
    days_since_last_social: Optional[int]  # Días desde último post en redes
    has_website: bool             # ¿Tiene sitio web propio?
    rating: Optional[float]       # Calificación en Google Maps (1-5)
    has_phone: bool               # ¿Tiene teléfono?
    has_facebook: bool
    has_instagram: bool


def calculate_lead_score(signals: LeadSignals) -> int:
    """
    Calcula el score compuesto del lead.

    Distribución de puntos (total: 100):
    - Jerarquía del email:     30 pts (el más importante)
    - Actividad/reseñas:       25 pts
    - Responde reseñas:        15 pts
    - Nombre del dueño:        10 pts
    - Actividad social:        10 pts
    - Website:                  5 pts
    - Rating alto:              5 pts
    """
    score = 0

    # --- Email hierarchy (30 pts máx) ---
    # Escalar el hierarchy_score (0-100) a 30 pts máx
    score += min(30, int(signals.hierarchy_score * 0.30))

    # --- Actividad en Google Maps (25 pts máx) ---
    rc = signals.review_count or 0
    if rc >= 200:
        score += 25
    elif rc >= 100:
        score += 20
    elif rc >= 50:
        score += 15
    elif rc >= 20:
        score += 10
    elif rc >= 5:
        score += 5
    # 0-4 reseñas: 0 pts

    # --- Responde a reseñas (15 pts) ---
    # Indica un dueño activo y accesible
    if signals.responds_to_reviews:
        score += 15

    # --- Nombre del dueño extraído (10 pts) ---
    # Si tenemos el nombre → el email puede ser personalizado
    if signals.has_owner_name:
        score += 10

    # --- Presencia social activa (10 pts) ---
    days = signals.days_since_last_social
    if days is not None:
        if days <= 3:
            score += 10   # Muy activo
        elif days <= 7:
            score += 8
        elif days <= 30:
            score += 5
        elif days <= 90:
            score += 2
        # Más de 90 días inactivo: 0 pts
    elif signals.has_facebook or signals.has_instagram:
        score += 3    # Tiene redes pero no sabemos actividad

    # --- Website propio (5 pts) ---
    if signals.has_website:
        score += 5

    # --- Rating alto (5 pts) ---
    rating = signals.rating or 0
    if rating >= 4.5:
        score += 5
    elif rating >= 4.0:
        score += 3

    return min(score, 100)


def get_lead_temperature(score: int) -> str:
    """Etiqueta de temperatura del lead."""
    if score >= 70:
        return "🔥 CALIENTE"
    elif score >= 40:
        return "🌡️ TIBIO"
    else:
        return "❄️ FRÍO"


def get_recommended_channels(score: int) -> list[str]:
    """Canales de contacto recomendados según el score."""
    if score >= 70:
        return ["email", "whatsapp", "social_dm"]
    elif score >= 40:
        return ["email", "whatsapp"]
    else:
        return ["email"]
