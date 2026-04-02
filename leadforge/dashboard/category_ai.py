"""
LeadForge — Category AI (Expansión de Categorías con Claude)
=============================================================

El corazón del Campaign Wizard: Claude analiza el producto/servicio
y descubre compradores que el usuario no imaginaría por sí solo.

Flujo:
  1. Revisar caché de Supabase → ¿ya tenemos leads de categorías similares?
  2. Llamar a Claude con producto + compradores conocidos + caché existente
  3. Claude genera 10-15 categorías (obvias + sorpresa) con razones y sinónimos
  4. Enriquecer cada categoría con datos reales del caché
  5. Devolver lista ordenada por potencial
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

import anthropic

from ..config import cfg
from ..supabase_client import get_db

logger = logging.getLogger(__name__)


# ============================================================
# MODELO DE CATEGORÍA SUGERIDA
# ============================================================

def _empty_category(nombre: str) -> dict:
    return {
        "nombre_busqueda": nombre,
        "tipo": "obvia",
        "razon": "Categoría identificada automáticamente.",
        "potencial": "medio",
        "sinonimos_google_maps": [nombre],
        "ya_en_cache": False,
        "leads_disponibles": 0,
        "leads_con_email": 0,
        "cache_dias": None,
    }


# ============================================================
# PROMPT MAESTRO DE CLAUDE
# ============================================================

SYSTEM_PROMPT = """Eres un experto en ventas B2B para el mercado latinoamericano (México, LATAM).
Tu especialidad es identificar compradores no obvios para cualquier producto o servicio.
Siempre respondes con JSON válido, sin comentarios, sin markdown, sin explicaciones adicionales."""


def _build_user_prompt(
    product: str,
    known_buyers: str,
    ciudad: str,
    existing_categories: list[str],
) -> str:
    existing_str = (
        f"\n\nCATEGORÍAS QUE YA TENEMOS EN BASE DE DATOS (para {ciudad}):\n"
        + ", ".join(existing_categories[:30])
        if existing_categories
        else ""
    )

    return f"""Analiza este producto/servicio y genera compradores potenciales para buscar en Google Maps.

PRODUCTO/SERVICIO:
{product}

COMPRADORES QUE YA CONOCE EL CLIENTE:
{known_buyers or "No especificados"}

CIUDAD OBJETIVO: {ciudad}{existing_str}

Genera una lista JSON de 10 a 15 tipos de negocios que comprarían este producto/servicio.
Incluye tanto los obvios como categorías SORPRESA que el cliente no imagina.

Para cada categoría, responde con este formato exacto:
{{
  "nombre_busqueda": "ferretería",
  "tipo": "obvia",
  "razon": "Las ferreterías revenden pinturas como producto complementario y tienen clientela habitual.",
  "potencial": "alto",
  "sinonimos_google_maps": ["ferretería", "distribuidora de materiales", "pinturas y ferretería", "tienda de materiales"]
}}

Reglas:
- nombre_busqueda: término singular o plural natural en español, como se buscaría en Google Maps
- tipo: "obvia" (el cliente ya lo sabe) | "sorpresa" (no lo habría pensado)
- razon: 15-30 palabras explicando POR QUÉ comprarían, con datos concretos si es posible
- potencial: "alto" | "medio" | "bajo"
- sinonimos_google_maps: 3-5 variantes de búsqueda (sinónimos, formas alternativas en el mismo mercado)

Responde SOLO con el array JSON. Sin texto adicional."""


# ============================================================
# ENRIQUECIMIENTO CON DATOS DEL CACHÉ
# ============================================================

def _enrich_with_cache(categories: list[dict], ciudad: str, cliente_id: str) -> list[dict]:
    """
    Para cada categoría sugerida por Claude, verifica si ya tenemos leads
    en Supabase (caché) y cuántos están disponibles.
    """
    db = get_db()
    enriched = []

    for cat in categories:
        nombre = cat.get("nombre_busqueda", "")
        sinonimos = cat.get("sinonimos_google_maps", [nombre])
        leads_total = 0
        leads_con_email = 0
        cache_dias = None

        # Buscar en Supabase por todos los sinónimos
        for termino in [nombre] + sinonimos:
            try:
                # Buscar en caché de búsquedas
                cache_result = db.table("busquedas_cache").select(
                    "total_resultados, resultados_validos, creado_en"
                ).ilike("termino_busqueda", f"%{termino}%").ilike(
                    "ciudad", f"%{ciudad.split(',')[0]}%"
                ).eq("cliente_id", cliente_id or cfg.cliente_id).limit(1).execute()

                if cache_result.data:
                    row = cache_result.data[0]
                    leads_total = max(leads_total, row.get("total_resultados", 0))
                    leads_con_email = max(leads_con_email, row.get("resultados_validos", 0))
                    # Calcular días desde la última búsqueda
                    created = row.get("creado_en", "")
                    if created:
                        try:
                            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            dias = (datetime.now().astimezone() - dt).days
                            if cache_dias is None or dias < cache_dias:
                                cache_dias = dias
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Error en caché check para '{termino}': {e}")

        cat["ya_en_cache"] = leads_total >= 30
        cat["leads_disponibles"] = leads_total
        cat["leads_con_email"] = leads_con_email
        cat["cache_dias"] = cache_dias
        enriched.append(cat)

    return enriched


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

async def expand_categories(
    product: str,
    known_buyers: str,
    ciudad: str,
    cliente_id: Optional[str] = None,
) -> list[dict]:
    """
    Expande las categorías de compradores usando Claude.

    Args:
        product: Descripción del producto/servicio que vende el cliente.
        known_buyers: Tipos de negocio que el cliente ya conoce como compradores.
        ciudad: Ciudad objetivo (ej: "Monterrey, Nuevo León").
        cliente_id: ID del cliente en Supabase (para verificar caché).

    Returns:
        Lista de categorías con: nombre, tipo, razón, potencial, sinónimos,
        ya_en_cache, leads_disponibles, leads_con_email.
    """
    client_id = cliente_id or cfg.cliente_id

    # Obtener categorías existentes en caché (para que Claude no repita)
    existing_categories: list[str] = []
    try:
        db = get_db()
        result = db.table("busquedas_cache").select("termino_busqueda").eq(
            "cliente_id", client_id
        ).ilike("ciudad", f"%{ciudad.split(',')[0]}%").limit(50).execute()
        existing_categories = [r["termino_busqueda"] for r in (result.data or [])]
    except Exception as e:
        logger.debug(f"No se pudo obtener caché existente: {e}")

    # Llamar a Claude
    categories = []
    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",       # Sonnet para mejor razonamiento
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": _build_user_prompt(product, known_buyers, ciudad, existing_categories),
            }],
        )

        text = message.content[0].text.strip()

        # Extraer JSON del response
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            categories = json.loads(json_match.group())
        else:
            logger.error(f"Claude no devolvió JSON válido: {text[:200]}")
            categories = []

    except json.JSONDecodeError as e:
        logger.error(f"Error parseando JSON de Claude: {e}")
    except Exception as e:
        logger.error(f"Error llamando a Claude: {e}")

    # Fallback si Claude falla
    if not categories:
        logger.warning("Usando categorías de fallback (Claude no disponible)")
        known_list = [b.strip() for b in known_buyers.split(",") if b.strip()]
        categories = [_empty_category(b) for b in known_list[:5]]

    # Validar y normalizar estructura
    validated = []
    for cat in categories:
        if not isinstance(cat, dict) or not cat.get("nombre_busqueda"):
            continue
        validated.append({
            "nombre_busqueda": str(cat.get("nombre_busqueda", ""))[:100],
            "tipo": cat.get("tipo", "obvia") if cat.get("tipo") in ("obvia", "sorpresa") else "obvia",
            "razon": str(cat.get("razon", ""))[:300],
            "potencial": cat.get("potencial", "medio") if cat.get("potencial") in ("alto", "medio", "bajo") else "medio",
            "sinonimos_google_maps": [str(s) for s in cat.get("sinonimos_google_maps", [])[:5]],
            "ya_en_cache": False,
            "leads_disponibles": 0,
            "leads_con_email": 0,
            "cache_dias": None,
        })

    # Enriquecer con datos de caché
    enriched = _enrich_with_cache(validated, ciudad, client_id)

    # Ordenar: caché primero, luego por potencial
    potencial_orden = {"alto": 0, "medio": 1, "bajo": 2}
    enriched.sort(key=lambda c: (
        0 if c["ya_en_cache"] else 1,
        potencial_orden.get(c["potencial"], 2),
    ))

    logger.info(f"Categorías generadas: {len(enriched)} ({sum(1 for c in enriched if c['ya_en_cache'])} en caché)")
    return enriched


# ============================================================
# ESTIMACIÓN DE COSTO
# ============================================================

def estimate_campaign_cost(
    categorias_seleccionadas: list[dict],
    ciudades: list[str],
) -> dict:
    """
    Estima el costo en créditos de Apify y Anymail Finder para
    las categorías seleccionadas que NO están en caché.
    """
    apify_cost = 0.0
    anymail_cost = 0.0
    leads_estimados = 0
    categorias_nuevas = 0

    for cat in categorias_seleccionadas:
        if cat.get("ya_en_cache"):
            # No cuesta nada extra usar el caché
            leads_estimados += cat.get("leads_con_email", 0)
            continue

        categorias_nuevas += 1
        num_terminos = len(cat.get("sinonimos_google_maps", [cat["nombre_busqueda"]]))
        num_ciudades = len(ciudades)

        # Perfil alta densidad: 50 resultados por búsqueda
        # ~0.016 créditos Apify por lugar scrapeado
        resultados_por_termino = 50
        apify_por_categoria = num_terminos * num_ciudades * resultados_por_termino * 0.016
        apify_cost += apify_por_categoria

        # Anymail: ~60% de negocios tienen email buscable → 1 crédito por empresa
        # (algunos ya traen email de Apify → ~30% ahorro)
        empresas_estimadas = resultados_por_termino * num_terminos * num_ciudades
        empresas_unicas = int(empresas_estimadas * 0.7)  # dedup ~30%
        anymail_credits = empresas_unicas * 0.7  # 70% necesitan búsqueda vs verify
        anymail_cost += anymail_credits * 0.01  # $0.01 por crédito (aprox)

        leads_validos = int(empresas_unicas * 0.25)  # ~25% pasan validación estricta
        leads_estimados += leads_validos

    return {
        "apify_creditos": round(apify_cost, 2),
        "anymail_creditos": round(anymail_cost / 0.01, 0),
        "anymail_usd": round(anymail_cost, 2),
        "total_usd": round(apify_cost + anymail_cost, 2),
        "leads_estimados": leads_estimados,
        "categorias_nuevas": categorias_nuevas,
        "categorias_cache": len(categorias_seleccionadas) - categorias_nuevas,
        "costo_por_lead": round(
            (apify_cost + anymail_cost) / leads_estimados, 4
        ) if leads_estimados > 0 else 0,
    }
