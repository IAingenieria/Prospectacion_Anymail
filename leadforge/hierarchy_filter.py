"""
LeadForge — Filtro de Jerarquía de Emails
Puntúa cada email por su probabilidad de pertenecer a un tomador de decisiones.
Como Anymail Finder NO devuelve cargo/puesto, inferimos la jerarquía del prefijo.
"""
import re
from dataclasses import dataclass
from typing import Optional


# ============================================================
# LISTAS DE PREFIJOS POR NIVEL JERÁRQUICO
# ============================================================
TIER_1_EJECUTIVOS = {
    # CEO / Dueño / Fundador / Director General
    "ceo", "director", "dueño", "dueno", "owner", "propietario",
    "fundador", "founder", "presidente", "socio", "gerente",
    "gm", "coo", "cfo", "cto", "cmo", "vp", "jefe",
    # Variantes con guión/punto (se detectan en la lógica, no aquí)
}

TIER_2_DECISION = {
    # Gerentes y encargados con poder de compra
    "encargado", "responsable", "administrador", "coordinador",
    "supervisor", "manager", "lider", "líder",
}

EMAILS_GENERICOS = {
    # Emails de buzón genérico — nadie los revisa regularmente
    "info", "contacto", "contact", "hola", "hello", "hi",
    "ventas", "sales", "compras", "purchases", "admin",
    "administracion", "administración", "recepcion", "recepción",
    "soporte", "support", "ayuda", "help", "atencion",
    "atención", "servicio", "service", "team", "equipo",
    "oficina", "office", "general", "mail", "correo",
    "no-reply", "noreply", "donotreply", "postmaster",
    "webmaster", "hello", "inbox", "buzon",
}


def score_email(email: str) -> int:
    """
    Puntúa un email por probabilidad de pertenecer a un tomador de decisiones.

    Returns:
        0-100 donde 100 = máxima jerarquía (ceo@, director@, etc.)
    """
    if not email or "@" not in email:
        return 0

    prefix = email.split("@")[0].lower()
    # Remover números al final (ej: director2@)
    prefix_clean = re.sub(r"\d+$", "", prefix)

    # Tier 1: Título ejecutivo explícito en el prefijo
    for titulo in TIER_1_EJECUTIVOS:
        if titulo in prefix_clean:
            return 100

    # Tier 2: Email genérico → baja prioridad
    # Usar el prefijo sin guiones/puntos para match exacto
    prefix_bare = re.sub(r"[-._]", "", prefix_clean)
    if prefix_bare in EMAILS_GENERICOS or prefix_clean in EMAILS_GENERICOS:
        return 5

    # Tier 3: Nombre propio (tiene punto, guión o guión bajo)
    # Patrón: juan.garcia@, j.garcia@, juan-garcia@
    if "." in prefix or "_" in prefix or "-" in prefix:
        return 65

    # Tier 4: Nombre corto probable (solo letras, longitud razonable)
    # Patrón: juang@, mgarcia@, perez@ — probable abreviatura de nombre
    if len(prefix_clean) <= 12 and re.match(r"^[a-záéíóúüñ]+$", prefix_clean):
        return 40

    # Tier 5: Cualquier otro patrón
    return 20


@dataclass
class EmailScore:
    email: str
    score: int
    email_status: str
    reason: str
    raw_data: dict  # datos originales de Anymail Finder


def filter_top_emails(
    emails_data: list[dict],
    max_count: int = 2,
    only_valid: bool = True,
) -> list[EmailScore]:
    """
    Filtra y ordena emails por jerarquía. Devuelve los mejores `max_count`.

    Args:
        emails_data: Lista de objetos de email de Anymail Finder.
                     Cada uno tiene al menos: {email, email_status}
        max_count: Máximo de emails a devolver (default: 2)
        only_valid: Si True, solo acepta email_status="valid".
                    Si False, acepta también "likely_valid" como fallback.

    Returns:
        Lista de EmailScore ordenada por score descendente.
    """
    scored: list[EmailScore] = []

    for item in emails_data:
        email_str = item.get("email", "")
        status = item.get("email_status", "unknown")

        # Filtro de status
        if only_valid and status != "valid":
            continue
        if not only_valid and status not in ("valid", "likely_valid"):
            continue

        score = score_email(email_str)

        # Determinar razón del score para trazabilidad
        prefix = email_str.split("@")[0].lower() if "@" in email_str else ""
        if any(t in prefix for t in TIER_1_EJECUTIVOS):
            reason = "ejecutivo_detectado"
        elif re.sub(r"[-._]", "", prefix) in EMAILS_GENERICOS:
            reason = "email_generico"
        elif "." in prefix or "_" in prefix:
            reason = "nombre_propio"
        elif len(prefix) <= 12:
            reason = "abreviatura_probable"
        else:
            reason = "patron_desconocido"

        scored.append(EmailScore(
            email=email_str,
            score=score,
            email_status=status,
            reason=reason,
            raw_data=item,
        ))

    # Ordenar por score descendente → tomar los mejores
    scored.sort(key=lambda x: x.score, reverse=True)
    result = scored[:max_count]

    if not result and not only_valid:
        # Si no hay válidos y se permite likely_valid, ya se manejó arriba
        pass

    return result


def get_email_tier_label(score: int) -> str:
    """Etiqueta legible del nivel de jerarquía."""
    if score >= 90:
        return "Ejecutivo C-Level"
    elif score >= 60:
        return "Nombre propio (probable tomador de decisiones)"
    elif score >= 35:
        return "Abreviatura de nombre"
    elif score >= 15:
        return "Email genérico"
    else:
        return "Sin clasificar"
