"""
social_enricher.py
═══════════════════════════════════════════════════════════════
Enriquece leads_master con redes sociales buscando en el sitio web
de cada negocio. Complementa lo que Google Places no da.

CÓMO FUNCIONA:
1. Toma leads de Supabase que tienen sitio_web pero NO tienen redes sociales
2. Visita el sitio web de cada negocio
3. Extrae links de Facebook, Instagram, TikTok, WhatsApp
4. Actualiza leads_master en Supabase

INSTALACIÓN:
    pip install requests beautifulsoup4 supabase python-dotenv

USO:
    # Procesar 100 leads
    python social_enricher.py --limit 100

    # Procesar todos los pendientes
    python social_enricher.py --all

    # Solo ver cuántos hay pendientes
    python social_enricher.py --count

    # Cliente específico
    python social_enricher.py --cliente-id "c7f3a2b1-..."
═══════════════════════════════════════════════════════════════
"""

import asyncio
import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

TIMEOUT = 8          # segundos por request
DELAY   = 0.5        # segundos entre requests (ser amable con los servidores)
BATCH   = 50         # leads por lote

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

# ─── PATRONES DE REDES SOCIALES ───────────────────────────────────────────────

PATTERNS = {
    "facebook_url": [
        r'(?:https?://)?(?:www\.)?facebook\.com/(?!sharer|share|dialog|pages/category)([^"\'\s\?/]+)',
        r'(?:https?://)?(?:www\.)?fb\.com/([^"\'\s\?/]+)',
        r'(?:https?://)?(?:www\.)?fb\.me/([^"\'\s\?/]+)',
    ],
    "instagram_url": [
        r'(?:https?://)?(?:www\.)?instagram\.com/([^"\'\s\?/]+)',
        r'(?:https?://)?(?:www\.)?instagr\.am/([^"\'\s\?/]+)',
    ],
    "tiktok_url": [
        r'(?:https?://)?(?:www\.)?tiktok\.com/@([^"\'\s\?/]+)',
    ],
    "whatsapp_url": [
        r'(?:https?://)?(?:wa\.me|api\.whatsapp\.com/send|web\.whatsapp\.com/send)[?/]([^"\'\s]+)',
        r'(?:https?://)?(?:www\.)?whatsapp\.com/([^"\'\s]+)',
    ],
    "linkedin_url": [
        r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/([^"\'\s\?/]+)',
    ],
    "youtube_url": [
        r'(?:https?://)?(?:www\.)?youtube\.com/(?:channel|c|user|@)([^"\'\s\?/]+)',
    ],
}

# Dominios a ignorar (falsos positivos comunes)
IGNORE_DOMAINS = {
    'facebook.com/sharer', 'facebook.com/share', 'facebook.com/dialog',
    'facebook.com/tr', 'facebook.com/plugins', 'facebook.com/login',
    'instagram.com/p/', 'instagram.com/reel/', 'instagram.com/explore',
    'tiktok.com/tag', 'tiktok.com/trending',
}


# ─── EXTRACTOR DE REDES SOCIALES ──────────────────────────────────────────────

@dataclass
class SocialResult:
    facebook_url:  Optional[str] = None
    instagram_url: Optional[str] = None
    tiktok_url:    Optional[str] = None
    whatsapp_url:  Optional[str] = None
    linkedin_url:  Optional[str] = None
    youtube_url:   Optional[str] = None
    encontrado:    bool = False
    error:         Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "facebook_url":  self.facebook_url,
            "instagram_url": self.instagram_url,
            "whatsapp_url":  self.whatsapp_url,
        }.items() if v is not None}


def extract_social_from_html(html: str, base_url: str) -> SocialResult:
    """Extrae redes sociales del HTML de un sitio web."""
    result = SocialResult()

    # Buscar en todo el HTML (links, botones, texto)
    for red, patterns in PATTERNS.items():
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                # Reconstruir URL completa
                if red == "facebook_url":
                    url = f"https://facebook.com/{match}"
                    # Filtrar falsos positivos
                    if any(ig in url for ig in IGNORE_DOMAINS):
                        continue
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

                elif red == "instagram_url":
                    url = f"https://instagram.com/{match}"
                    if any(ig in url for ig in IGNORE_DOMAINS):
                        continue
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

                elif red == "tiktok_url":
                    url = f"https://tiktok.com/@{match}"
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

                elif red == "whatsapp_url":
                    url = f"https://wa.me/{match}"
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

                elif red == "linkedin_url":
                    url = f"https://linkedin.com/company/{match}"
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

                elif red == "youtube_url":
                    url = f"https://youtube.com/@{match}"
                    if not getattr(result, red):
                        setattr(result, red, url)
                        result.encontrado = True

    return result


def fetch_website(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Descarga el HTML de un sitio web.
    Retorna (html, error)
    """
    # Asegurar que tiene protocolo
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            verify=False  # algunos sitios MX tienen certs vencidos
        )
        if resp.status_code == 200:
            return resp.text, None
        else:
            return None, f"HTTP {resp.status_code}"

    except requests.exceptions.SSLError:
        # Reintentar con http://
        try:
            url_http = url.replace('https://', 'http://')
            resp = requests.get(url_http, headers=HEADERS, timeout=TIMEOUT)
            return resp.text, None
        except Exception as e:
            return None, str(e)[:100]

    except requests.exceptions.Timeout:
        return None, "timeout"

    except requests.exceptions.ConnectionError:
        return None, "connection_error"

    except Exception as e:
        return None, str(e)[:100]


# ─── CLIENTE SUPABASE ─────────────────────────────────────────────────────────

def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("❌ Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY en .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_leads_pendientes(sb, limite: int, cliente_id: Optional[str] = None) -> list:
    """
    Trae leads que tienen sitio_web pero NO tienen redes sociales.
    Son los candidatos para enriquecer.
    """
    query = (
        sb.table("leads_master")
        .select("id, nombre_negocio, sitio_web, ciudad, estado")
        .not_.is_("sitio_web", "null")
        .is_("facebook_url", "null")
        .is_("instagram_url", "null")
        .neq("sitio_web", "N/A")
        .neq("sitio_web", "")
        .order("lead_score", desc=True)
        .limit(limite)
    )

    if cliente_id:
        query = query.eq("cliente_id", cliente_id)

    result = query.execute()
    return result.data or []


def count_pendientes(sb, cliente_id: Optional[str] = None) -> dict:
    """Cuenta cuántos leads hay en cada categoría."""
    # Total
    total = sb.table("leads_master").select("id", count="exact").execute()

    # Con sitio web sin redes
    pendientes = (
        sb.table("leads_master")
        .select("id", count="exact")
        .not_.is_("sitio_web", "null")
        .is_("facebook_url", "null")
        .is_("instagram_url", "null")
        .neq("sitio_web", "N/A")
        .execute()
    )

    # Ya enriquecidos
    con_redes = (
        sb.table("leads_master")
        .select("id", count="exact")
        .not_.is_("facebook_url", "null")
        .execute()
    )

    return {
        "total": total.count,
        "pendientes_enriquecer": pendientes.count,
        "ya_con_redes": con_redes.count,
    }


def update_lead_social(sb, lead_id: str, social: SocialResult) -> bool:
    """Actualiza un lead con sus redes sociales encontradas."""
    data = social.to_dict()
    if not data:
        return False

    try:
        sb.table("leads_master").update(data).eq("id", lead_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Error actualizando lead {lead_id}: {e}")
        return False


# ─── PROCESO PRINCIPAL ────────────────────────────────────────────────────────

def procesar_leads(limite: int, cliente_id: Optional[str] = None):
    """
    Proceso principal: trae leads → visita webs → extrae redes → actualiza DB
    """
    sb = get_supabase()

    # Contar primero
    conteos = count_pendientes(sb, cliente_id)
    logger.info(f"📊 Total en DB: {conteos['total']:,}")
    logger.info(f"⏳ Pendientes de enriquecer: {conteos['pendientes_enriquecer']:,}")
    logger.info(f"✅ Ya con redes sociales: {conteos['ya_con_redes']:,}")
    logger.info(f"🎯 Procesando ahora: {min(limite, conteos['pendientes_enriquecer']):,}")
    logger.info("─" * 50)

    leads = get_leads_pendientes(sb, limite, cliente_id)
    if not leads:
        logger.info("✅ No hay leads pendientes de enriquecer")
        return

    # Estadísticas
    procesados = 0
    encontrados = 0
    errores = 0

    for i, lead in enumerate(leads, 1):
        nombre   = lead.get("nombre_negocio", "?")
        sitio    = lead.get("sitio_web", "")
        ciudad   = lead.get("ciudad", "")
        lead_id  = lead["id"]

        logger.info(f"[{i}/{len(leads)}] {nombre} ({ciudad}) → {sitio}")

        # Descargar HTML
        html, error = fetch_website(sitio)

        if error:
            logger.warning(f"  ⚠️  Error: {error}")
            errores += 1
            time.sleep(DELAY)
            continue

        # Extraer redes
        social = extract_social_from_html(html, sitio)

        if social.encontrado:
            # Actualizar en Supabase
            actualizado = update_lead_social(sb, lead_id, social)
            if actualizado:
                encontrados += 1
                redes = []
                if social.facebook_url:  redes.append(f"FB: {social.facebook_url[:50]}")
                if social.instagram_url: redes.append(f"IG: {social.instagram_url[:50]}")
                if social.tiktok_url:    redes.append(f"TK: {social.tiktok_url[:50]}")
                if social.whatsapp_url:  redes.append(f"WA: {social.whatsapp_url[:50]}")
                logger.info(f"  ✅ {' | '.join(redes)}")
        else:
            logger.info(f"  — Sin redes sociales encontradas")

        procesados += 1
        time.sleep(DELAY)

        # Reporte cada 25 leads
        if i % 25 == 0:
            tasa = (encontrados / procesados * 100) if procesados else 0
            logger.info(f"\n📊 Progreso: {procesados} procesados | "
                       f"{encontrados} con redes ({tasa:.0f}%) | "
                       f"{errores} errores\n")

    # Resumen final
    tasa = (encontrados / procesados * 100) if procesados else 0
    logger.info("\n" + "═" * 50)
    logger.info(f"✅ COMPLETADO")
    logger.info(f"   Procesados:  {procesados:,}")
    logger.info(f"   Con redes:   {encontrados:,} ({tasa:.1f}%)")
    logger.info(f"   Sin redes:   {procesados - encontrados - errores:,}")
    logger.info(f"   Errores web: {errores:,}")
    logger.info("═" * 50)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Social Media Enricher — LeadForge"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Número de leads a procesar (default: 100)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Procesar TODOS los leads pendientes"
    )
    parser.add_argument(
        "--count", action="store_true",
        help="Solo contar cuántos hay pendientes"
    )
    parser.add_argument(
        "--cliente-id", type=str, default=None,
        help="Filtrar por cliente específico"
    )

    args = parser.parse_args()

    # Suprimir warnings de SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if args.count:
        sb = get_supabase()
        conteos = count_pendientes(sb, args.cliente_id)
        print(f"\n📊 Estado del enriquecimiento social:")
        print(f"   Total leads en DB:          {conteos['total']:>8,}")
        print(f"   Pendientes de enriquecer:   {conteos['pendientes_enriquecer']:>8,}")
        print(f"   Ya con redes sociales:      {conteos['ya_con_redes']:>8,}")
        return

    limite = 999_999 if args.all else args.limit
    procesar_leads(limite, args.cliente_id)


if __name__ == "__main__":
    main()
