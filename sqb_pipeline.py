"""
SQB Pipeline Autónomo — Soluciones Químicas Biodegradables
==========================================================
Ejecuta en secuencia sin intervención humana:
  1. DENUE scraping por estado + sector → leads_master
  2. AnyMailFinder verification → email_status = valid
  3. Export CSV listo para Instantly.ai
  4. Notificación Telegram al terminar cada etapa

Uso:
  venv\Scripts\python.exe sqb_pipeline.py
  venv\Scripts\python.exe sqb_pipeline.py --solo-denue
  venv\Scripts\python.exe sqb_pipeline.py --solo-amf
  venv\Scripts\python.exe sqb_pipeline.py --solo-export
"""
import asyncio
import csv
import logging
import os
import sys
import argparse
from datetime import datetime

# ── Setup path ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(".env")

from leadforge.denue_enricher import DenueEnricher, SECTORES_DENUE
from leadforge.supabase_client import get_db

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/sqb_pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("sqb_pipeline")

# ── Configuración ─────────────────────────────────────────────────────────────
SQB_CLIENTE_ID = "c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_MASTER_CHAT_ID")

# Estados y sectores a procesar en orden
PIPELINE_TARGETS = [
    # (estado, sector)  — ya procesado NL en sesión anterior
    ("Coahuila",        "cnc"),
    ("Coahuila",        "alimentos"),
    ("Coahuila",        "automotriz"),
    ("Coahuila",        "flotas"),
    ("Tamaulipas",      "cnc"),
    ("Tamaulipas",      "alimentos"),
    ("Tamaulipas",      "automotriz"),
    ("Tamaulipas",      "flotas"),
    ("Chihuahua",       "cnc"),
    ("Chihuahua",       "automotriz"),
    ("Chihuahua",       "alimentos"),
    ("Guanajuato",      "cnc"),
    ("Guanajuato",      "automotriz"),
    ("Guanajuato",      "alimentos"),
    ("San Luis Potosi", "cnc"),
    ("San Luis Potosi", "automotriz"),
    ("San Luis Potosi", "alimentos"),
    ("Nuevo Leon",      "alimentos"),   # sector pendiente de NL
    ("Nuevo Leon",      "automotriz"),
    ("Nuevo Leon",      "flotas"),
]

AMF_LOTE        = 300   # leads por ronda AMF
AMF_MAX_RONDAS  = 20    # máximo de rondas antes de exportar
META_VALIDOS    = 800   # leads válidos meta para exportar

# Términos de búsqueda en Google Maps por sector SQB
APIFY_TERMINOS = {
    "cnc":        ["planta CNC", "manufactura CNC", "mecanizado CNC", "maquinado industrial", "troquelado metal"],
    "alimentos":  ["planta de alimentos", "industria alimentaria", "procesadora alimentos", "manufactura alimentos", "empacadora alimentos"],
    "automotriz": ["autopartes", "planta automotriz", "industria automotriz", "manufactura automotriz", "proveedor automotriz"],
    "flotas":     ["flotilla camiones", "transporte de carga", "logística empresarial", "renta de camiones", "transporte industrial"],
}
APIFY_MAX_POR_TERMINO = 100  # lugares por término de búsqueda en Google Maps


# ── Telegram helper ───────────────────────────────────────────────────────────
async def tg(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    import httpx
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        log.warning(f"Telegram error: {e}")


# ── Fase 1: DENUE scraping ────────────────────────────────────────────────────
async def fase_denue():
    log.info("=" * 60)
    log.info("FASE 1 — DENUE Scraping")
    log.info("=" * 60)

    await tg(
        "🏗️ *SQB Pipeline iniciado*\n\n"
        f"📋 {len(PIPELINE_TARGETS)} búsquedas DENUE programadas\n"
        "Iniciando scraping automático..."
    )

    enricher = DenueEnricher()
    total_insertados = 0

    for i, (estado, sector) in enumerate(PIPELINE_TARGETS, 1):
        log.info(f"[{i}/{len(PIPELINE_TARGETS)}] {estado} — {sector}")
        try:
            result = await enricher.ingestar_sector(
                cliente_id=SQB_CLIENTE_ID,
                estado=estado,
                categoria=sector,
            )
            insertados = result.get("insertados_nuevos", 0)
            encontrados = result.get("encontrados_denue", 0)
            total_insertados += insertados
            log.info(f"  ✅ {estado}/{sector}: {encontrados} encontrados, {insertados} nuevos")

            await tg(
                f"✅ *DENUE {i}/{len(PIPELINE_TARGETS)}*\n"
                f"📍 {estado} — {sector}\n"
                f"🔍 {encontrados} encontrados | {insertados} nuevos en DB"
            )

        except Exception as e:
            log.error(f"  ❌ {estado}/{sector}: {e}")
            await tg(f"⚠️ Error DENUE {estado}/{sector}: `{str(e)[:150]}`")

        # Pausa entre búsquedas para no saturar la API DENUE
        await asyncio.sleep(3)

    log.info(f"DENUE completado — {total_insertados} leads nuevos insertados")
    await tg(
        f"🏁 *DENUE completado*\n\n"
        f"📊 Total nuevos en DB: *{total_insertados}*\n"
        f"▶️ Iniciando verificación AMF..."
    )
    return total_insertados


# ── Fase 2: Apify Google Maps — enriquecer con web, teléfono, redes sociales ──
async def fase_apify():
    log.info("=" * 60)
    log.info("FASE 2 — Apify Google Maps (web + teléfono + redes sociales)")
    log.info("=" * 60)

    from leadforge.apify_scraper import ApifyScraper
    db = get_db()
    scraper = ApifyScraper()

    total_nuevos = 0
    total_actualizados = 0

    await tg(
        "🗺️ *Apify Google Maps iniciado*\n\n"
        "Buscando websites, teléfonos, Facebook e Instagram\n"
        "para todas las empresas DENUE sin datos de contacto..."
    )

    for estado, sector in PIPELINE_TARGETS:
        terminos = APIFY_TERMINOS.get(sector, [sector])
        location = f"{estado}, Mexico"
        log.info(f"Apify: {estado} / {sector} — {len(terminos)} términos")

        try:
            resultados = await scraper.scrape_all_terms(
                terminos=terminos,
                location=location,
                max_per_term=APIFY_MAX_POR_TERMINO,
            )

            nuevos = actualizados = 0

            for neg in resultados:
                # Buscar si ya existe en leads_master por teléfono o nombre+ciudad
                existe = None
                if neg.telefono:
                    r = db.table("leads_master").select("id,sitio_web,facebook_url,instagram_url,telefono") \
                        .eq("cliente_id", SQB_CLIENTE_ID) \
                        .eq("telefono", neg.telefono) \
                        .limit(1).execute()
                    existe = r.data[0] if r.data else None

                if not existe:
                    r = db.table("leads_master").select("id,sitio_web,facebook_url,instagram_url,telefono") \
                        .eq("cliente_id", SQB_CLIENTE_ID) \
                        .ilike("nombre_negocio", neg.nombre[:30]) \
                        .ilike("ciudad", neg.ciudad or "") \
                        .limit(1).execute()
                    existe = r.data[0] if r.data else None

                if existe:
                    # Actualizar solo campos vacíos — no sobreescribir datos DENUE
                    upd = {}
                    if neg.sitio_web and not existe.get("sitio_web"):
                        upd["sitio_web"] = neg.sitio_web
                    if neg.telefono and not existe.get("telefono"):
                        upd["telefono"] = neg.telefono
                    if neg.facebook_url and not existe.get("facebook_url"):
                        upd["facebook_url"] = neg.facebook_url
                    if neg.instagram_url and not existe.get("instagram_url"):
                        upd["instagram_url"] = neg.instagram_url
                    if upd:
                        db.table("leads_master").update(upd).eq("id", existe["id"]).execute()
                        actualizados += 1
                else:
                    # Insertar nuevo lead de Google Maps
                    db.table("leads_master").insert({
                        "cliente_id":   SQB_CLIENTE_ID,
                        "nombre_negocio": neg.nombre,
                        "categoria":    sector,
                        "ciudad":       neg.ciudad,
                        "estado":       estado,
                        "sitio_web":    neg.sitio_web,
                        "telefono":     neg.telefono,
                        "facebook_url": neg.facebook_url,
                        "instagram_url": neg.instagram_url,
                        "email":        neg.email,
                        "email_status": "pendiente_validacion" if neg.email else None,
                        "anymail_procesado": False,
                        "fuente":       "google_maps",
                    }).execute()
                    nuevos += 1

            total_nuevos += nuevos
            total_actualizados += actualizados
            log.info(f"  {estado}/{sector}: {len(resultados)} Google Maps → {nuevos} nuevos, {actualizados} actualizados")

            await tg(
                f"🗺️ *Apify {estado} — {sector}*\n"
                f"📍 {len(resultados)} encontrados en Google Maps\n"
                f"🆕 {nuevos} nuevos leads | 🔄 {actualizados} enriquecidos con web/redes"
            )

        except Exception as e:
            log.error(f"Apify error {estado}/{sector}: {e}")
            await tg(f"⚠️ Apify error {estado}/{sector}: `{str(e)[:150]}`")

        await asyncio.sleep(3)

    log.info(f"Apify completado — {total_nuevos} nuevos, {total_actualizados} actualizados")
    await tg(
        f"✅ *Apify Google Maps completado*\n\n"
        f"🆕 Leads nuevos de Google Maps: *{total_nuevos}*\n"
        f"🔄 Leads DENUE enriquecidos: *{total_actualizados}*\n"
        f"  (+ website, teléfono, Facebook, Instagram)\n\n"
        f"▶️ Iniciando verificación de emails AMF..."
    )
    return total_nuevos, total_actualizados


# ── Fase 3: AnyMailFinder verification ───────────────────────────────────────
async def fase_amf():
    log.info("=" * 60)
    log.info("FASE 2 — AnyMailFinder Verification")
    log.info("=" * 60)

    from leadforge.anymail_enricher import AnymailEnricher
    db = get_db()
    amf = AnymailEnricher()

    total_validos = 0
    total_procesados = 0
    ronda = 0

    while ronda < AMF_MAX_RONDAS:
        ronda += 1

        # Contar válidos actuales
        r_count = db.table("leads_master") \
            .select("id", count="exact") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .eq("email_status", "valid") \
            .execute()
        validos_actuales = r_count.count or 0

        log.info(f"Ronda {ronda}: {validos_actuales} válidos acumulados (meta: {META_VALIDOS})")

        if validos_actuales >= META_VALIDOS:
            log.info(f"✅ Meta de {META_VALIDOS} válidos alcanzada")
            await tg(f"🎯 *Meta AMF alcanzada*: {validos_actuales} emails válidos SQB")
            break

        # Ruta A: verificar emails existentes con status desconocido
        resp_a = db.table("leads_master") \
            .select("id,email,nombre_negocio") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .eq("anymail_procesado", False) \
            .not_.is_("email", "null") \
            .limit(AMF_LOTE // 2) \
            .execute()

        # Ruta B: buscar emails por dominio web
        resp_b = db.table("leads_master") \
            .select("id,nombre_negocio,sitio_web,ciudad") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .eq("anymail_procesado", False) \
            .is_("email", "null") \
            .not_.is_("sitio_web", "null") \
            .limit(AMF_LOTE // 2) \
            .execute()

        leads_a = resp_a.data or []
        leads_b = resp_b.data or []

        if not leads_a and not leads_b:
            log.info("No hay más leads pendientes para AMF")
            await tg("ℹ️ SQB: Sin más leads pendientes para AMF")
            break

        log.info(f"  Ruta A (verificar): {len(leads_a)} | Ruta B (buscar): {len(leads_b)}")

        validos_ronda = invalidos_ronda = 0
        creditos_ronda = 0.0

        # Procesar Ruta A — verify_email
        for lead in leads_a:
            try:
                result = await amf.verify_email(lead["email"])
                is_valid = result.tiene_emails_validos
                status = "valid" if is_valid else "invalid"
                db.table("leads_master").update({
                    "email_status": status,
                    "anymail_procesado": True,
                }).eq("id", lead["id"]).execute()
                creditos_ronda += result.credits_used
                if is_valid:
                    validos_ronda += 1
                else:
                    invalidos_ronda += 1
            except Exception as e:
                log.warning(f"AMF verify error {lead.get('email')}: {e}")

        # Procesar Ruta B — find_by_company
        for lead in leads_b:
            try:
                result = await amf.find_by_company(company_name=lead["nombre_negocio"])
                update_data = {"anymail_procesado": True}
                if result.tiene_emails_validos:
                    best = next(e for e in result.emails if e.get("email_status") == "valid")
                    update_data["email"] = best["email"]
                    update_data["email_status"] = "valid"
                    validos_ronda += 1
                else:
                    update_data["email_status"] = "not_found"
                    invalidos_ronda += 1
                db.table("leads_master").update(update_data).eq("id", lead["id"]).execute()
                creditos_ronda += result.credits_used
            except Exception as e:
                log.warning(f"AMF find error {lead.get('nombre_negocio')}: {e}")

        total_validos += validos_ronda
        total_procesados += len(leads_a) + len(leads_b)

        log.info(f"  Ronda {ronda}: +{validos_ronda} válidos, {invalidos_ronda} inválidos, {creditos_ronda:.1f} créditos")
        await tg(
            f"🔬 *AMF Ronda {ronda}*\n"
            f"✅ +{validos_ronda} válidos | ❌ {invalidos_ronda} inválidos\n"
            f"📊 Acumulado válidos: {validos_actuales + validos_ronda}\n"
            f"💳 Créditos ronda: {creditos_ronda:.1f}"
        )

        await asyncio.sleep(2)

    # Total final
    r_final = db.table("leads_master") \
        .select("id", count="exact") \
        .eq("cliente_id", SQB_CLIENTE_ID) \
        .eq("email_status", "valid") \
        .execute()
    validos_final = r_final.count or 0

    await tg(
        f"✅ *AMF completado*\n\n"
        f"📊 Emails válidos SQB: *{validos_final}*\n"
        f"▶️ Exportando CSV para Instantly..."
    )
    return validos_final


# ── Fase 3: Export CSV para Instantly ─────────────────────────────────────────
async def fase_export():
    log.info("=" * 60)
    log.info("FASE 3 — Export CSV Instantly")
    log.info("=" * 60)

    db = get_db()
    all_leads = []
    offset = 0

    while True:
        r = db.table("leads_master") \
            .select("nombre_negocio,email,owner_name,telefono,ciudad,estado,sitio_web,categoria") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .eq("email_status", "valid") \
            .limit(1000) \
            .offset(offset) \
            .execute()
        batch = r.data or []
        all_leads.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    downloads = os.path.expanduser("~/Downloads")
    os.makedirs(downloads, exist_ok=True)
    output = os.path.join(downloads, f"sqb_instantly_{timestamp}.csv")

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email","first_name","last_name","company_name","phone","city","website"])
        for l in all_leads:
            nombre = (l.get("owner_name") or "").strip()
            parts = nombre.split()
            first = parts[0] if parts else "Equipo"
            last  = " ".join(parts[1:]) if len(parts) > 1 else "de Compras"
            writer.writerow([
                l.get("email",""),
                first, last,
                l.get("nombre_negocio",""),
                l.get("telefono",""),
                l.get("ciudad",""),
                l.get("sitio_web",""),
            ])

    log.info(f"CSV exportado: {output} ({len(all_leads)} leads)")
    await tg(
        f"📁 *CSV listo para Instantly*\n\n"
        f"📊 {len(all_leads)} emails válidos SQB\n"
        f"📂 `{output}`\n\n"
        f"🚀 Sube el CSV a Instantly → campaña SQB lista"
    )
    return output, len(all_leads)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main(solo_denue=False, solo_amf=False, solo_export=False, solo_apify=False):
    log.info("🚀 SQB Pipeline — Iniciando")
    start = datetime.now()

    try:
        if solo_export:
            await fase_export()
        elif solo_amf:
            await fase_amf()
            await fase_export()
        elif solo_denue:
            await fase_denue()
        elif solo_apify:
            await fase_apify()
        else:
            # Pipeline completo: DENUE → Google Maps → AMF → CSV
            await fase_denue()
            await fase_apify()
            await fase_amf()
            await fase_export()

        elapsed = (datetime.now() - start).seconds // 60
        log.info(f"✅ Pipeline completado en {elapsed} minutos")
        await tg(f"🏁 *SQB Pipeline completado* en {elapsed} min\n✅ Todo listo para campaña")

    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
        await tg(f"❌ *SQB Pipeline error*\n`{str(e)[:300]}`")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQB Pipeline autónomo")
    parser.add_argument("--solo-denue",  action="store_true", help="Solo fase DENUE")
    parser.add_argument("--solo-apify",  action="store_true", help="Solo fase Apify Google Maps")
    parser.add_argument("--solo-amf",    action="store_true", help="Solo fase AMF + export")
    parser.add_argument("--solo-export", action="store_true", help="Solo exportar CSV")
    args = parser.parse_args()

    asyncio.run(main(
        solo_denue=args.solo_denue,
        solo_apify=args.solo_apify,
        solo_amf=args.solo_amf,
        solo_export=args.solo_export,
    ))
