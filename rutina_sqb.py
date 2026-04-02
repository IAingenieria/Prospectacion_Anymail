"""
Rutina de Enriquecimiento SQB — Automática o por Telegram
==========================================================
Paso 1: Enriquece empresas sin email con Apify Google Maps + AMF
Paso 2: Limpia duplicados en Supabase (mismo nombre o teléfono)

Uso:
  python rutina_sqb.py               # Paso 1 + 2 completos
  python rutina_sqb.py --paso1       # Solo Apify + AMF
  python rutina_sqb.py --paso2       # Solo deduplicar
  python rutina_sqb.py --dry-run     # Simular sin borrar
"""
import asyncio
import logging
import os
import sys
import argparse
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(".env")

from leadforge.supabase_client import get_db

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/rutina_sqb.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("rutina_sqb")

# ── Config ───────────────────────────────────────────────────────────────────
SQB_CLIENTE_ID  = "c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c"
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_MASTER_CHAT_ID")

# Términos Google Maps por sector
APIFY_TERMINOS = {
    "cnc":        ["planta CNC", "manufactura CNC", "mecanizado CNC", "maquinado industrial", "troquelado metal"],
    "alimentos":  ["planta de alimentos", "industria alimentaria", "procesadora alimentos", "manufactura alimentos", "empacadora alimentos"],
    "automotriz": ["autopartes", "planta automotriz", "industria automotriz", "manufactura automotriz", "proveedor automotriz"],
    "flotas":     ["flotilla camiones", "transporte de carga", "logística empresarial", "renta de camiones", "transporte industrial"],
    "hoteles":    ["hotel industrial", "hotel corporativo", "hotel negocios"],
    "quimica":    ["empresa química", "planta química", "industria química", "laboratorio industrial"],
}

ESTADOS_TARGET = ["Nuevo León", "Coahuila", "Tamaulipas"]
APIFY_MAX = 100


# ── Telegram ──────────────────────────────────────────────────────────────────
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


# ── PASO 1: Enriquecer sin email ──────────────────────────────────────────────
async def paso1_enriquecer():
    """
    Busca empresas SQB sin email en Supabase, las enriquece con Apify Google Maps
    para obtener website, luego AMF busca el email desde el website.
    """
    log.info("=" * 60)
    log.info("PASO 1 — Enriquecimiento Apify + AMF")
    log.info("=" * 60)

    db = get_db()
    from leadforge.apify_scraper import ApifyScraper
    from leadforge.anymail_enricher import AnymailEnricher

    # Contar situación actual
    r_total = db.table("leads_master").select("id", count="exact") \
        .eq("cliente_id", SQB_CLIENTE_ID).execute()
    r_sin_email = db.table("leads_master").select("id", count="exact") \
        .eq("cliente_id", SQB_CLIENTE_ID) \
        .is_("email", "null").execute()
    r_validos = db.table("leads_master").select("id", count="exact") \
        .eq("cliente_id", SQB_CLIENTE_ID) \
        .eq("email_status", "valid").execute()

    total    = r_total.count or 0
    sin_mail = r_sin_email.count or 0
    validos  = r_validos.count or 0

    log.info(f"Estado inicial: {total} empresas | {validos} con email válido | {sin_mail} sin email")
    await tg(
        "🔄 *Rutina SQB — Paso 1 iniciado*\n\n"
        f"📊 Total empresas: *{total}*\n"
        f"✅ Con email válido: *{validos}*\n"
        f"❌ Sin email: *{sin_mail}*\n\n"
        "🗺️ Buscando en Google Maps para encontrar websites..."
    )

    # ── Fase A: Apify — buscar websites por sector/estado ────────────────────
    scraper = ApifyScraper()
    nuevos = 0
    actualizados = 0

    for estado in ESTADOS_TARGET:
        for sector, terminos in APIFY_TERMINOS.items():
            location = f"{estado}, Mexico"
            try:
                resultados = await scraper.scrape_all_terms(
                    terminos=terminos,
                    location=location,
                    max_per_term=APIFY_MAX,
                )

                n = a = 0
                for neg in resultados:
                    # Buscar match en Supabase (por teléfono, nombre, o nombre+ciudad)
                    existe = None
                    if neg.telefono:
                        r = db.table("leads_master").select("id,sitio_web,email,telefono,facebook_url,instagram_url") \
                            .eq("cliente_id", SQB_CLIENTE_ID) \
                            .eq("telefono", neg.telefono).limit(1).execute()
                        existe = r.data[0] if r.data else None

                    if not existe and neg.nombre:
                        r = db.table("leads_master").select("id,sitio_web,email,telefono,facebook_url,instagram_url") \
                            .eq("cliente_id", SQB_CLIENTE_ID) \
                            .ilike("nombre_negocio", neg.nombre[:30]).limit(1).execute()
                        existe = r.data[0] if r.data else None

                    # Check por nombre+ciudad para evitar 23505
                    if not existe and neg.nombre and neg.ciudad:
                        r = db.table("leads_master").select("id,sitio_web,email,telefono,facebook_url,instagram_url") \
                            .eq("cliente_id", SQB_CLIENTE_ID) \
                            .ilike("nombre_negocio", f"%{neg.nombre[:25]}%") \
                            .ilike("ciudad", f"%{neg.ciudad[:15]}%").limit(1).execute()
                        existe = r.data[0] if r.data else None

                    if existe:
                        upd = {}
                        if neg.sitio_web and not existe.get("sitio_web"):
                            upd["sitio_web"] = neg.sitio_web
                        if neg.telefono and not existe.get("telefono"):
                            upd["telefono"] = neg.telefono
                        if neg.facebook_url and not existe.get("facebook_url"):
                            upd["facebook_url"] = neg.facebook_url
                        if neg.instagram_url and not existe.get("instagram_url"):
                            upd["instagram_url"] = neg.instagram_url
                        if neg.email and not existe.get("email"):
                            upd["email"] = neg.email
                            upd["email_status"] = "pendiente_validacion"
                        if upd:
                            db.table("leads_master").update(upd).eq("id", existe["id"]).execute()
                            a += 1
                    else:
                        try:
                            db.table("leads_master").insert({
                                "cliente_id":    SQB_CLIENTE_ID,
                                "nombre_negocio": neg.nombre,
                                "categoria":     sector,
                                "ciudad":        neg.ciudad,
                                "estado":        estado,
                                "sitio_web":     neg.sitio_web,
                                "telefono":      neg.telefono,
                                "facebook_url":  neg.facebook_url,
                                "instagram_url": neg.instagram_url,
                                "email":         neg.email,
                                "email_status":  "pendiente_validacion" if neg.email else None,
                                "anymail_procesado": False,
                                "fuente":        "google_maps",
                            }).execute()
                            n += 1
                        except Exception as ins_err:
                            if "23505" in str(ins_err):
                                # Duplicado por constraint — actualizar en vez de insertar
                                try:
                                    r2 = db.table("leads_master").select("id,sitio_web,email,telefono,facebook_url,instagram_url") \
                                        .eq("cliente_id", SQB_CLIENTE_ID) \
                                        .ilike("nombre_negocio", f"%{(neg.nombre or '')[:20]}%").limit(1).execute()
                                    if r2.data:
                                        upd2 = {}
                                        if neg.sitio_web and not r2.data[0].get("sitio_web"):
                                            upd2["sitio_web"] = neg.sitio_web
                                        if neg.facebook_url and not r2.data[0].get("facebook_url"):
                                            upd2["facebook_url"] = neg.facebook_url
                                        if upd2:
                                            db.table("leads_master").update(upd2).eq("id", r2.data[0]["id"]).execute()
                                            a += 1
                                except Exception:
                                    pass
                            else:
                                raise

                nuevos += n
                actualizados += a
                log.info(f"  Apify {estado}/{sector}: {len(resultados)} resultados → {n} nuevos, {a} enriquecidos")

            except Exception as e:
                log.error(f"Apify error {estado}/{sector}: {e}")
                await tg(f"⚠️ Apify {estado}/{sector}: `{str(e)[:150]}`")

            await asyncio.sleep(2)

    await tg(
        f"✅ *Google Maps completado*\n\n"
        f"🆕 Nuevas empresas: *{nuevos}*\n"
        f"🔄 Empresas enriquecidas con web/redes: *{actualizados}*\n\n"
        f"📧 Iniciando verificación AMF de emails..."
    )

    # ── Fase B: AMF — buscar emails desde websites ────────────────────────────
    amf = AnymailEnricher()
    AMF_LOTE = 50
    MAX_RONDAS = 30
    META = 1200  # meta de emails válidos SQB

    for ronda in range(1, MAX_RONDAS + 1):
        r_v = db.table("leads_master").select("id", count="exact") \
            .eq("cliente_id", SQB_CLIENTE_ID).eq("email_status", "valid").execute()
        validos_ahora = r_v.count or 0

        if validos_ahora >= META:
            log.info(f"✅ Meta {META} alcanzada: {validos_ahora} emails válidos")
            await tg(f"🎯 *Meta alcanzada: {validos_ahora} emails válidos SQB*\n▶️ Exportando CSV...")
            break

        # Leads con website pero sin email
        resp = db.table("leads_master") \
            .select("id,nombre_negocio,sitio_web") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .eq("anymail_procesado", False) \
            .not_.is_("sitio_web", "null") \
            .is_("email", "null") \
            .limit(AMF_LOTE).execute()

        if not resp.data:
            log.info("No hay más leads con website sin email")
            await tg(f"📊 AMF completado: {validos_ahora} emails válidos SQB")
            break

        procesados = validos_nuevos = 0
        for lead in resp.data:
            try:
                domain = _extract_domain(lead.get("sitio_web", ""))
                if not domain:
                    db.table("leads_master").update({"anymail_procesado": True}) \
                        .eq("id", lead["id"]).execute()
                    continue

                resultado = await amf.find_email(
                    domain=domain,
                    company=lead.get("nombre_negocio", ""),
                )

                upd = {"anymail_procesado": True}
                if resultado and resultado.get("email"):
                    upd["email"] = resultado["email"]
                    upd["email_status"] = resultado.get("status", "valid")
                    if upd["email_status"] == "valid":
                        validos_nuevos += 1

                db.table("leads_master").update(upd).eq("id", lead["id"]).execute()
                procesados += 1
                await asyncio.sleep(0.5)

            except Exception as e:
                log.error(f"AMF error {lead.get('id')}: {e}")

        log.info(f"Ronda AMF {ronda}: {procesados} procesados, {validos_nuevos} nuevos válidos, total {validos_ahora}")
        await asyncio.sleep(1)

    # Reporte final
    r_final = db.table("leads_master").select("id", count="exact") \
        .eq("cliente_id", SQB_CLIENTE_ID).eq("email_status", "valid").execute()
    final = r_final.count or 0

    await tg(
        f"🏁 *Paso 1 completado*\n\n"
        f"✅ Emails válidos SQB: *{final}*\n"
        f"📈 Ganancia: +{final - validos} emails\n\n"
        f"▶️ Ejecuta `/pipeline sqb` para exportar CSV"
    )
    return final


def _extract_domain(url: str) -> str:
    """Extrae dominio limpio de una URL."""
    if not url:
        return ""
    url = url.lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.split("/")[0].split("?")[0].strip()
    return url if "." in url else ""


# ── PASO 2: Limpiar duplicados ────────────────────────────────────────────────
async def paso2_deduplicar(dry_run: bool = False):
    """
    Encuentra y elimina registros duplicados en Supabase para SQB.
    Criterios de duplicado:
      - Mismo nombre_negocio normalizado (lowercase, sin SA/CV/etc.)
      - O mismo teléfono
    Conserva el registro con más información (email > sitio_web > teléfono).
    """
    log.info("=" * 60)
    log.info(f"PASO 2 — Deduplicación Supabase {'(DRY RUN)' if dry_run else ''}")
    log.info("=" * 60)

    db = get_db()
    await tg(
        f"🧹 *Rutina SQB — Paso 2{'  (simulación)' if dry_run else ''}*\n\n"
        "Buscando registros duplicados en Supabase...\n"
        "_(mismo nombre o teléfono)_"
    )

    # Obtener TODOS los leads SQB
    offset = 0
    page_size = 1000
    todos = []
    while True:
        r = db.table("leads_master") \
            .select("id,nombre_negocio,telefono,email,email_status,sitio_web,facebook_url,instagram_url,fuente") \
            .eq("cliente_id", SQB_CLIENTE_ID) \
            .range(offset, offset + page_size - 1) \
            .execute()
        if not r.data:
            break
        todos.extend(r.data)
        if len(r.data) < page_size:
            break
        offset += page_size

    log.info(f"Total registros SQB en Supabase: {len(todos)}")

    # ── Agrupar por nombre normalizado ────────────────────────────────────────
    def normalizar(nombre: str) -> str:
        if not nombre:
            return ""
        n = nombre.lower().strip()
        # Quitar sufijos legales
        for s in [" sa de cv", " s.a. de c.v.", " sapi", " s de rl", " sa", " sc"]:
            n = n.replace(s, "")
        # Quitar puntuación extra
        n = re.sub(r"[,.\-_]", " ", n)
        n = re.sub(r"\s+", " ", n).strip()
        return n

    def score(lead: dict) -> int:
        """Puntaje de completitud — más alto = mejor registro."""
        s = 0
        if lead.get("email") and lead.get("email_status") == "valid":
            s += 100
        if lead.get("email"):
            s += 50
        if lead.get("sitio_web"):
            s += 20
        if lead.get("telefono"):
            s += 10
        if lead.get("facebook_url"):
            s += 5
        if lead.get("instagram_url"):
            s += 5
        return s

    # Agrupar por nombre normalizado
    grupos_nombre: dict = {}
    for lead in todos:
        key = normalizar(lead.get("nombre_negocio", ""))
        if key:
            grupos_nombre.setdefault(key, []).append(lead)

    # Agrupar por teléfono
    grupos_tel: dict = {}
    for lead in todos:
        tel = (lead.get("telefono") or "").strip()
        if tel and tel != "0":
            grupos_tel.setdefault(tel, []).append(lead)

    # Encontrar IDs a eliminar
    ids_a_borrar = set()

    for key, grupo in grupos_nombre.items():
        if len(grupo) > 1:
            ordenado = sorted(grupo, key=score, reverse=True)
            ganador = ordenado[0]
            perdedores = ordenado[1:]
            for p in perdedores:
                ids_a_borrar.add(p["id"])
            if len(grupo) > 1:
                log.info(f"  Dup nombre '{key}': {len(grupo)} → conserva id={ganador['id']} ({ganador.get('nombre_negocio')})")

    for tel, grupo in grupos_tel.items():
        if len(grupo) > 1:
            ordenado = sorted(grupo, key=score, reverse=True)
            ganador = ordenado[0]
            for p in ordenado[1:]:
                if p["id"] not in ids_a_borrar:
                    ids_a_borrar.add(p["id"])
            log.info(f"  Dup teléfono '{tel}': {len(grupo)} → conserva id={ganador['id']}")

    total_borrar = len(ids_a_borrar)
    log.info(f"Duplicados encontrados: {total_borrar}")

    if total_borrar == 0:
        await tg("✅ *Sin duplicados* — Base de datos limpia")
        return 0

    if dry_run:
        await tg(
            f"🔍 *Simulación completada*\n\n"
            f"Se eliminarían *{total_borrar}* registros duplicados\n"
            f"Ejecuta sin `--dry-run` para confirmar"
        )
        return total_borrar

    # Eliminar en lotes de 100
    ids_lista = list(ids_a_borrar)
    eliminados = 0
    LOTE = 100
    for i in range(0, len(ids_lista), LOTE):
        lote = ids_lista[i:i + LOTE]
        db.table("leads_master").delete().in_("id", lote).execute()
        eliminados += len(lote)
        log.info(f"  Eliminados {eliminados}/{total_borrar}...")

    await tg(
        f"✅ *Deduplicación completada*\n\n"
        f"🗑️ Duplicados eliminados: *{eliminados}*\n"
        f"📊 Registros únicos restantes: *{len(todos) - eliminados}*"
    )
    return eliminados


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Rutina de enriquecimiento SQB")
    parser.add_argument("--paso1",   action="store_true", help="Solo Apify + AMF")
    parser.add_argument("--paso2",   action="store_true", help="Solo deduplicar")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin borrar")
    args = parser.parse_args()

    start = datetime.now()
    await tg(f"🚀 *Rutina SQB iniciada*\n📅 {start.strftime('%d/%m/%Y %H:%M')}")

    if args.paso1:
        await paso1_enriquecer()
    elif args.paso2:
        await paso2_deduplicar(dry_run=args.dry_run)
    else:
        # Completo: primero limpiar, luego enriquecer
        await paso2_deduplicar(dry_run=args.dry_run)
        await paso1_enriquecer()

    elapsed = (datetime.now() - start).seconds // 60
    await tg(f"🏁 *Rutina SQB terminada* en {elapsed} min")


if __name__ == "__main__":
    asyncio.run(main())
