"""
LeadForge — Detector de Redes Sociales y Emails Corporativos

Analiza HTML de sitios web para extraer:
- URLs de redes sociales (Facebook, Instagram, LinkedIn, Twitter/X, TikTok, YouTube)
- Emails corporativos (filtrando proveedores gratuitos)

Módulo independiente — no tiene dependencias del resto de LeadForge.
"""
import re
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Proveedores de email gratuitos ───────────────────────────────────────────
# Cualquier email en estos dominios NO es corporativo
FREE_EMAIL_PROVIDERS = {
    "gmail.com", "hotmail.com", "yahoo.com", "yahoo.com.mx",
    "outlook.com", "live.com", "live.com.mx", "live.com.ar",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "protonmail.ch", "pm.me",
    "tutanota.com", "tutamail.com",
    "hotmail.es", "hotmail.com.mx", "hotmail.com.ar",
    "yahoo.es", "yahoo.com.ar",
    "msn.com", "aol.com",
    "zohomail.com", "yandex.com", "yandex.ru",
    "mail.com", "gmx.com", "gmx.net",
    "inbox.com", "fastmail.com",
    "outlook.es", "outlook.com.mx",
}

# ── Patrones de extracción de redes sociales ─────────────────────────────────
# Cada red puede tener múltiples patrones (más específico primero)
SOCIAL_PATTERNS = {
    "facebook_url": [
        r"https?://(?:www\.)?facebook\.com/(?:pages/[^/]+/)?([A-Za-z0-9_.%-]{3,})",
        r"https?://(?:www\.)?fb\.com/([A-Za-z0-9_.%-]{3,})",
    ],
    "instagram_url": [
        r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{1,})/?\b",
    ],
    "linkedin_url": [
        r"https?://(?:www\.)?linkedin\.com/(?:company|in|pub)/([A-Za-z0-9_.\-]{2,})",
    ],
    "twitter_url": [
        r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})\b",
    ],
    "tiktok_url": [
        r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]{2,})",
    ],
    "youtube_url": [
        r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)([A-Za-z0-9_.\-]{2,})",
    ],
}

# Fragmentos de URL que son páginas genéricas, no perfiles reales
_SOCIAL_PATH_BLACKLIST = {
    "sharer", "share", "intent", "dialog", "login", "signup",
    "register", "photo", "video", "watch", "hashtag", "search",
    "groups", "events", "marketplace", "gaming", "help",
    "policies", "about", "explore", "stories", "reels", "shop",
    "home", "feeds", "notifications", "messages", "bookmarks",
    "undefined", "null", "none", "page", "profile", "terms",
    "privacy", "ads", "business", "create",
    # Dominios que aparecen como falsos positivos
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com",
}

# Regex para emails
_EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}\b"
)

# Regex para limpiar HTML antes de buscar emails en texto plano
_HREF_REGEX = re.compile(r'href=["\']([^"\']{5,})["\']', re.IGNORECASE)
_MAILTO_REGEX = re.compile(r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10})', re.IGNORECASE)


# ── Funciones de email ────────────────────────────────────────────────────────

def is_free_email(email: str) -> bool:
    """True si el email pertenece a un proveedor gratuito (no corporativo)."""
    if not email or "@" not in email:
        return True
    domain = email.lower().split("@")[-1].strip()
    return domain in FREE_EMAIL_PROVIDERS


def extract_emails_from_text(text: str) -> list[str]:
    """Extrae todos los emails encontrados en un texto (incluyendo HTML)."""
    # Priorizar mailto: links
    mailto_emails = _MAILTO_REGEX.findall(text)
    # Buscar en texto general
    all_emails = _EMAIL_REGEX.findall(text)
    # Combinar: mailto primero (más confiables), luego los demás
    seen: set[str] = set()
    result: list[str] = []
    for email in mailto_emails + all_emails:
        normalized = email.lower().strip()
        if normalized not in seen and len(normalized) < 100:
            seen.add(normalized)
            result.append(email)
    return result


def filter_corporate_emails(emails: list[str]) -> list[str]:
    """
    Filtra y devuelve solo emails corporativos.
    Elimina: proveedores gratuitos, emails inválidos, ofuscaciones.
    """
    result = []
    for email in emails:
        if not email or "@" not in email:
            continue
        if is_free_email(email):
            continue
        # Filtrar emails ofuscados o con caracteres raros
        local, domain = email.lower().split("@", 1)
        if not local or not domain or "." not in domain:
            continue
        # Rechazar si parece imagen o asset (ej: imagen@2x.png)
        if any(domain.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg", ".css", ".js")):
            continue
        # Rechazar si el local es demasiado corto o sospechoso
        if len(local) < 2:
            continue
        result.append(email)
    return result


# ── Funciones de redes sociales ───────────────────────────────────────────────

def _is_valid_social_handle(handle: str) -> bool:
    """True si el handle/username parece real (no un falso positivo)."""
    if not handle:
        return False
    handle_clean = handle.strip("/").split("/")[0].lower()
    if handle_clean in _SOCIAL_PATH_BLACKLIST:
        return False
    if len(handle_clean) < 2:
        return False
    return True


def _build_canonical_url(network: str, handle: str, full_match: str) -> Optional[str]:
    """
    Construye la URL canónica para una red social.
    Devuelve URL limpia o None si es un falso positivo.
    """
    handle_clean = handle.strip("/").split("/")[0]
    if not _is_valid_social_handle(handle_clean):
        return None

    # Mantener URL completa para LinkedIn y YouTube (paths son significativos)
    if network == "linkedin_url":
        # Extraer path completo desde linkedin.com
        m = re.search(r"(https?://(?:www\.)?linkedin\.com/(?:company|in|pub)/[A-Za-z0-9_.\-]+)", full_match, re.I)
        return m.group(1) if m else None

    if network == "youtube_url":
        m = re.search(r"(https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)[A-Za-z0-9_.\-]+)", full_match, re.I)
        return m.group(1) if m else None

    canonical_bases = {
        "facebook_url": f"https://www.facebook.com/{handle_clean}",
        "instagram_url": f"https://www.instagram.com/{handle_clean}",
        "twitter_url":   f"https://twitter.com/{handle_clean}",
        "tiktok_url":    f"https://www.tiktok.com/@{handle_clean}",
    }
    return canonical_bases.get(network)


def detect_social_urls(html_content: str) -> dict[str, Optional[str]]:
    """
    Analiza HTML y extrae URLs de redes sociales.

    Estrategia:
    1. Buscar en atributos href (más confiable)
    2. Buscar en texto libre (captura URLs sin etiqueta)

    Returns:
        Dict con: facebook_url, instagram_url, linkedin_url,
                  twitter_url, tiktok_url, youtube_url
        Valor None para las redes no encontradas.
    """
    result: dict[str, Optional[str]] = {k: None for k in SOCIAL_PATTERNS}

    # Extraer hrefs primero (son los más confiables)
    hrefs = _HREF_REGEX.findall(html_content)
    # Texto completo para búsqueda secundaria
    combined = " ".join(hrefs) + " " + html_content

    for network, patterns in SOCIAL_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                handle = match.group(1)
                full_match = match.group(0)
                canonical = _build_canonical_url(network, handle, full_match)
                if canonical:
                    result[network] = canonical
                    break  # Primera coincidencia válida para esta red

    return result


def extract_all_from_html(html_content: str) -> dict:
    """
    Función principal: extrae emails corporativos y URLs sociales de un HTML.

    Returns:
        {
            "emails": list[str],   — emails corporativos encontrados
            "social": dict,        — URLs de redes sociales (None si no encontrada)
        }
    """
    all_emails = extract_emails_from_text(html_content)
    corporate = filter_corporate_emails(all_emails)
    social = detect_social_urls(html_content)

    return {
        "emails": corporate,
        "social": social,
    }
