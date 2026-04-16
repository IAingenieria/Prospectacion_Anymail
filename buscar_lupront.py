"""
buscar_lupront.py — Pipeline automatizado de leads para LuPront Pinturas
==========================================================================
Cliente: LuPront — Pinturas económicas y de aceite para el noreste de México
Target:  Constructoras, mantenimiento industrial, herrería, ferreterías,
         pintores profesionales, agregados/concreto.
Zonas:   Nuevo León, Coahuila, Tamaulipas

Flujo:
  1. DENUE — Ingesta masiva por sector y estado
  2. Supabase — Almacena leads con LUPRONT_CLIENTE_ID
  3. AnyMailFinder — Verifica emails existentes (Ruta A) + busca por empresa (Ruta B)

Uso:
  python buscar_lupront.py              # Pipeline completo
  python buscar_lupront.py --solo-denue # Solo DENUE (sin AnyMailFinder)
  python buscar_lupront.py --solo-email # Solo verificar emails
  python buscar_lupront.py --stats      # Ver estadisticas actuales
"""

import asyncio
import sys
import math
import time
import logging
from datetime import datetime

# ── Configuracion LuPront ─────────────────────────────────────────────────────
LUPRONT_CLIENTE_ID = "b8e2f4d6-1a3c-4e5f-8b0d-2c4e6a8f0b2d"

ESTADOS_OBJETIVO = [
    "Nuevo León",
    "Coahuila",
    "Tamaulipas",
]

# Sectores por prioridad según perfil NEGOCIO_LUPRONT.md
# Productos: Esmaltes L-7000, Vinílica L-9000, Pintura Alberca L-4000
# Precio 30-40% menor que Berel/Comex — fabricante directo
SECTORES_LUPRONT = [
    # ── CATEGORÍA A — Alta prioridad ─────────────────────────────────────────
    {
        "categoria": "constructoras",
        "razon": "CAT-A1: Pintura vinílica/económica para vivienda en entrega",
        "prioridad": 1,
    },
    {
        "categoria": "mantenimiento",
        "razon": "CAT-A2: Esmalte/aceite para mantenimiento industrial",
        "prioridad": 1,
    },
    {
        "categoria": "ferreterias",
        "razon": "CAT-A3: Distribuidores/revendedores de pinturas",
        "prioridad": 1,
    },
    # ── CATEGORÍA B — Media prioridad ────────────────────────────────────────
    {
        "categoria": "pintores",
        "razon": "CAT-B1: Pintores profesionales — compra recurrente directa",
        "prioridad": 2,
    },
    {
        "categoria": "albercas",
        "razon": "CAT-B3: Pintura especializada L-4000 para albercas",
        "prioridad": 2,
    },
    # ── CATEGORÍA C — Largo plazo ─────────────────────────────────────────────
    {
        "categoria": "arquitectos",
        "razon": "CAT-C1: Especificación de pinturas en proyectos",
        "prioridad": 3,
    },
    {
        "categoria": "hoteles",
        "razon": "CAT-C2: Hoteles, restaurantes y espacios comerciales",
        "prioridad": 3,
    },
]

ANYMAIL_BATCH = 800   # leads por lote AnyMailFinder (Ruta B)
ANYMAIL_DELAY = 0.5   # segundos entre requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lupront")


# ── Helpers ───────────────────────────────────────────────────────────────────

def separador(titulo: str = "", ancho: int = 65) -> None:
    if titulo:
        pad = (ancho - len(titulo) - 2) // 2
        print(f"\n{'═' * pad} {titulo} {'═' * pad}")
    else:
        print("═" * ancho)


def _v(x, lower: bool = True) -> str:
    """Limpia valores NaN/None a string vacío."""
    if x is None:
        return ""
    if isinstance(x, float) and math.isnan(x):
        return ""
    s = str(x).strip()
    if s.lower() in ("nan", "none", "null", ""):
        return ""
    return s.lower() if lower else s


# ── Fase 1: DENUE ─────────────────────────────────────────────────────────────

async def fase1_denue() -> dict:
    """Ingesta DENUE para todos los sectores y estados de LuPront."""
    from leadforge.denue_enricher import DenueEnricher

    separador("FASE 1 — DENUE / INEGI")
    print(f"  Cliente:  LuPront Pinturas")
    print(f"  ID:       {LUPRONT_CLIENTE_ID}")
    print(f"  Estados:  {', '.join(ESTADOS_OBJETIVO)}")
    print(f"  Sectores: {len(SECTORES_LUPRONT)}")
    print(f"  Total búsquedas: {len(ESTADOS_OBJETIVO) * len(SECTORES_LUPRONT)}\n")

    enricher = DenueEnricher()
    totales = {"encontrados": 0, "insertados": 0, "existian": 0, "errores": 0}
    log_detalle = []

    combo_total = len(ESTADOS_OBJETIVO) * len(SECTORES_LUPRONT)
    combo_actual = 0

    for estado in ESTADOS_OBJETIVO:
        separador(estado)
        for sector in SECTORES_LUPRONT:
            combo_actual += 1
            cat = sector["categoria"]
            print(
                f"  [{combo_actual:02d}/{combo_total:02d}] "
                f"{cat.upper()} — {sector['razon']}"
            )
            try:
                result = await enricher.ingestar_sector(
                    cliente_id=LUPRONT_CLIENTE_ID,
                    estado=estado,
                    categoria=cat,
                )
                n = result["encontrados_denue"]
                ins = result["insertados_nuevos"]
                ex = result["ya_existian"]
                print(f"         → {n} encontrados | {ins} nuevos | {ex} ya existían")
                totales["encontrados"] += n
                totales["insertados"] += ins
                totales["existian"] += ex
                log_detalle.append({
                    "estado": estado, "categoria": cat,
                    "encontrados": n, "insertados": ins,
                })
            except Exception as e:
                logger.error(f"  ERROR {estado}/{cat}: {e}")
                totales["errores"] += 1

            await asyncio.sleep(1.0)  # Respetar rate limit INEGI

    separador("RESUMEN DENUE")
    print(f"  🔍 Total encontrados:  {totales['encontrados']}")
    print(f"  ✅ Insertados nuevos:  {totales['insertados']}")
    print(f"  ♻️  Ya existían en DB:  {totales['existian']}")
    print(f"  ❌ Errores:            {totales['errores']}")
    return totales


# ── Fase 2: AnyMailFinder ─────────────────────────────────────────────────────

async def fase2_anymail() -> dict:
    """
    Verifica y busca emails para leads LuPront:
    - Ruta A: Verifica emails existentes (0.1 cr c/u)
    - Ruta B: Busca emails por empresa+web (1 cr c/u)
    """
    from leadforge.supabase_client import get_db
    from leadforge.anymail_enricher import AnymailEnricher
    from leadforge.denue_enricher import calcular_calidad_stars

    separador("FASE 2 — AnyMailFinder")

    anymail = AnymailEnricher()
    db = get_db()

    # Verificar créditos
    account = await anymail.check_account_status()
    creditos = account.get("credits_remaining", 0)
    print(f"  💳 Créditos disponibles: {creditos:,}")

    totales = {
        "ruta_a_procesados": 0, "ruta_a_validos": 0,
        "ruta_b_procesados": 0, "ruta_b_encontrados": 0,
        "creditos_usados": 0,
    }

    # ── Ruta A: verificar emails existentes ──────────────────────────────────
    print(f"\n  RUTA A — Verificación de emails existentes (0.1 cr c/u)")
    resp_a = db.table("leads_master").select(
        "id, nombre_negocio, email, sitio_web, telefono, latitud, razon_social, denue_confirmado"
    ).eq("cliente_id", LUPRONT_CLIENTE_ID).eq(
        "email_status", "pendiente_validacion"
    ).limit(1000).execute()

    leads_a = resp_a.data or []
    print(f"  → {len(leads_a)} leads con email pendiente de verificar")

    creditos_inicio = creditos
    for i, lead in enumerate(leads_a):
        email = _v(lead.get("email"), lower=True)
        if not email:
            continue
        try:
            result = await anymail.verify_email(email)
            email_status = result.emails[0].get("email_status", "unknown") if result.emails else "unknown"
            is_valid = email_status == "valid"

            upd = {
                "email_status": "valid" if is_valid else "invalid",
                "anymail_procesado": True,
            }
            lead_merged = {**lead, **upd}
            upd["calidad_stars"] = calcular_calidad_stars(
                lead_merged,
                denue_confirmado=bool(lead.get("denue_confirmado"))
            )
            db.table("leads_master").update(upd).eq("id", lead["id"]).execute()

            totales["ruta_a_procesados"] += 1
            if is_valid:
                totales["ruta_a_validos"] += 1

            if (i + 1) % 50 == 0:
                print(
                    f"  A: {i+1:>4}/{len(leads_a)} | "
                    f"✅ válidos: {totales['ruta_a_validos']} | "
                    f"💳 ~{(i+1)*0.1:.0f} créditos"
                )
        except Exception as e:
            logger.debug(f"Ruta A error {email}: {e}")
        await asyncio.sleep(ANYMAIL_DELAY)

    print(
        f"  A: ✅ {totales['ruta_a_validos']} válidos "
        f"de {totales['ruta_a_procesados']} verificados"
    )

    # ── Ruta B: buscar emails por empresa + web ───────────────────────────────
    print(f"\n  RUTA B — Búsqueda por empresa+web (1 cr c/u)")
    resp_b = db.table("leads_master").select(
        "id, nombre_negocio, sitio_web, telefono, ciudad, estado, latitud, razon_social, denue_confirmado"
    ).eq("cliente_id", LUPRONT_CLIENTE_ID).is_(
        "email", "null"
    ).not_.is_("sitio_web", "null").eq(
        "anymail_procesado", False
    ).limit(ANYMAIL_BATCH).execute()

    leads_b = resp_b.data or []
    creditos_disponibles_b = creditos - totales["ruta_a_procesados"] * 0.1
    print(f"  → {len(leads_b)} leads sin email + con website")
    print(f"  → Costo estimado: ~{len(leads_b)} créditos")

    if creditos_disponibles_b < len(leads_b):
        limite_b = int(creditos_disponibles_b * 0.8)
        leads_b = leads_b[:limite_b]
        print(f"  ⚠️  Limitando a {limite_b} por créditos disponibles")

    for i, lead in enumerate(leads_b):
        nombre = _v(lead.get("nombre_negocio"), lower=False)
        web = _v(lead.get("sitio_web"), lower=True)
        if not nombre:
            continue
        try:
            result = await anymail.find_by_company(company_name=nombre)
            emails = result.emails or []
            upd = {"anymail_procesado": True}

            if emails:
                nuevo_email = emails[0].get("email", "")
                if nuevo_email:
                    upd["email"] = nuevo_email
                    upd["email_status"] = "valid"
                    totales["ruta_b_encontrados"] += 1

            lead_merged = {**lead, **upd}
            upd["calidad_stars"] = calcular_calidad_stars(
                lead_merged,
                denue_confirmado=bool(lead.get("denue_confirmado"))
            )
            db.table("leads_master").update(upd).eq("id", lead["id"]).execute()
            totales["ruta_b_procesados"] += 1

            if (i + 1) % 50 == 0:
                print(
                    f"  B: {i+1:>4}/{len(leads_b)} | "
                    f"📧 encontrados: {totales['ruta_b_encontrados']} | "
                    f"💳 ~{i+1} créditos"
                )
        except Exception as e:
            logger.debug(f"Ruta B error {nombre}: {e}")
        await asyncio.sleep(ANYMAIL_DELAY)

    print(
        f"  B: 📧 {totales['ruta_b_encontrados']} emails encontrados "
        f"de {totales['ruta_b_procesados']} empresas"
    )

    totales["creditos_usados"] = (
        totales["ruta_a_procesados"] * 0.1 + totales["ruta_b_procesados"]
    )
    return totales


# ── Fase 3: Estadísticas ──────────────────────────────────────────────────────

def fase3_stats() -> None:
    """Muestra distribución de calidad de leads LuPront en Supabase."""
    from leadforge.supabase_client import get_db

    separador("ESTADÍSTICAS LUPRONT")
    db = get_db()

    result = db.table("leads_master").select(
        "calidad_stars, email, telefono, email_status, denue_confirmado"
    ).eq("cliente_id", LUPRONT_CLIENTE_ID).execute()

    leads = result.data or []
    total = len(leads)

    if not total:
        print("  No hay leads LuPront en la DB todavía.")
        return

    por_stars = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    con_email = 0
    email_valido = 0
    con_tel = 0
    con_denue = 0

    for l in leads:
        s = l.get("calidad_stars") or 1
        por_stars[s] = por_stars.get(s, 0) + 1
        if l.get("email"):
            con_email += 1
        if l.get("email_status") == "valid":
            email_valido += 1
        if l.get("telefono"):
            con_tel += 1
        if l.get("denue_confirmado"):
            con_denue += 1

    def barra(n, t, ancho=10):
        llenos = int(n * ancho / t) if t else 0
        return "█" * llenos + "░" * (ancho - llenos)

    print(f"  Total leads LuPront: {total:,}")
    print()
    for s in [5, 4, 3, 2, 1]:
        n = por_stars[s]
        estrellas = "★" * s + "☆" * (5 - s)
        print(f"  {estrellas} {n:>5}  {barra(n, total)}")
    print()
    print(f"  📧 Con email:          {con_email:>5} ({con_email*100//total}%)")
    print(f"  ✅ Email válido:        {email_valido:>5} ({email_valido*100//total}%)")
    print(f"  📞 Con teléfono:        {con_tel:>5} ({con_tel*100//total}%)")
    print(f"  🏛️  DENUE confirmado:    {con_denue:>5} ({con_denue*100//total}%)")
    print()
    print(f"  🎯 Listos para campaña (email válido): {email_valido}")
    separador()


# ── Main ──────────────────────────────────────────────────────────────────────

async def enviar_telegram(mensaje: str) -> None:
    """Envía mensaje de Telegram al master chat."""
    import httpx
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_MASTER_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram no configurado — sin notificación")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"},
            )
        logger.info("✅ Notificación Telegram enviada")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


async def main():
    args = sys.argv[1:]
    solo_denue = "--solo-denue" in args
    solo_email = "--solo-email" in args
    solo_stats = "--stats" in args

    separador("LUPRONT PINTURAS — Pipeline de Leads")
    print(f"  Inicio: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Target: 1,000 leads en NL + Coahuila + Tamaulipas")
    print(f"  Sectores: Constructoras, Mantenimiento, Ferreterías,")
    print(f"            Pintores, Albercas, Arquitectos, Hoteles")
    separador()

    t0 = time.time()

    if solo_stats:
        fase3_stats()
        return

    if not solo_email:
        denue_result = await fase1_denue()
    else:
        denue_result = {}

    if not solo_denue:
        email_result = await fase2_anymail()
    else:
        email_result = {}

    fase3_stats()

    elapsed = time.time() - t0

    separador("RESULTADO FINAL")
    if denue_result:
        print(f"  DENUE:     {denue_result.get('insertados', 0)} leads nuevos insertados")
    if email_result:
        print(
            f"  Emails:    "
            f"{email_result.get('ruta_a_validos', 0)} verificados válidos + "
            f"{email_result.get('ruta_b_encontrados', 0)} encontrados nuevos"
        )
        print(f"  Créditos:  ~{email_result.get('creditos_usados', 0):.0f} usados")
    print(f"  Tiempo:    {elapsed/60:.1f} minutos")
    separador()

    # ── Notificación Telegram ─────────────────────────────────────────────────
    ins = denue_result.get("insertados", 0)
    validos_a = email_result.get("ruta_a_validos", 0)
    encontrados_b = email_result.get("ruta_b_encontrados", 0)
    creditos = email_result.get("creditos_usados", 0)
    emails_total = validos_a + encontrados_b

    msg = (
        f"🎨 *LuPront — Pipeline Completado*\n\n"
        f"📍 NL + Coahuila + Tamaulipas\n"
        f"⏱ Tiempo: {elapsed/60:.0f} minutos\n\n"
        f"📊 *Resultados:*\n"
        f"  🏛️ Leads DENUE nuevos: *{ins:,}*\n"
        f"  📧 Emails válidos total: *{emails_total}*\n"
        f"     ✅ Verificados: {validos_a}\n"
        f"     🆕 Encontrados nuevos: {encontrados_b}\n"
        f"  💳 Créditos usados: ~{creditos:.0f}\n\n"
        f"Usa /calidad para ver distribución de estrellas."
    )
    await enviar_telegram(msg)


if __name__ == "__main__":
    asyncio.run(main())
