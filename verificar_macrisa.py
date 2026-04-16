"""
LeadForge — Verificación de Emails Macrisa con AnyMailFinder
=============================================================
Procesa la tabla macrisa_leads en dos rutas:

  RUTA A — Verificar emails existentes (0.1 créditos c/u)
    Leads con email_status = 'pendiente_validacion'

  RUTA B — Buscar email por nombre de empresa (1 crédito c/u)
    Leads SIN email pero CON website (señal de que es negocio activo en línea)

Al final actualiza calidad_stars y muestra reporte completo.

Uso:
  cd "C:/Users/Dell/Documents/CLAUDE DESKTOP/Claude Leads Instantly"
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py --dry-run
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py --solo-verificar     (solo Ruta A)
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py --solo-buscar        (solo Ruta B)
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py --limit 200          (máx 200 leads)
  venv\Scripts\python.exe -X utf8 verificar_macrisa.py --limit 500 --solo-verificar
"""
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# ── Configuración de logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 20     # Llamadas paralelas a AnyMailFinder por lote
DELAY_ENTRE_LOTES = 1.5  # Segundos de pausa entre lotes (throttle)


# ── Supabase ──────────────────────────────────────────────────────────────────
def get_supabase():
    from dotenv import load_dotenv
    import os
    load_dotenv(Path(__file__).parent / ".env")
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL o SUPABASE_SERVICE_KEY no configurados en .env")
    return create_client(url, key)


# ── Calidad stars para Macrisa ────────────────────────────────────────────────
def calcular_stars(email: str, telefono: str, website: str, confianza: str, email_status: str) -> int:
    """
    1 ★    = solo nombre
    2 ★★   = email O teléfono
    3 ★★★  = email + teléfono
    4 ★★★★ = email válido + teléfono (email_status='valid')
    5 ★★★★★ = email válido + teléfono + website + confianza alta
    """
    tiene_email = bool(email)
    tiene_tel = bool(telefono)
    tiene_web = bool(website)
    email_valido = (email_status == "valid") if email else False
    confianza_alta = (confianza == "alta") if confianza else False

    if email_valido and tiene_tel and tiene_web and confianza_alta:
        return 5
    if email_valido and tiene_tel:
        return 4
    if tiene_email and tiene_tel:
        return 3
    if tiene_email or tiene_tel:
        return 2
    return 1


# ── Fetch leads Ruta A: verificar emails existentes ───────────────────────────
def fetch_pendientes_verificacion(sb, limit: int) -> list[dict]:
    """
    Leads con email existente y email_status='pendiente_validacion'
    que aún no han sido procesados por AnyMailFinder.
    """
    resp = sb.table("macrisa_leads").select(
        "id, nombre, email, telefono, website, confianza, calidad_stars"
    ).eq("email_status", "pendiente_validacion").eq(
        "anymail_procesado", False
    ).not_.is_("email", "null").limit(limit).execute()

    return resp.data or []


# ── Fetch leads Ruta B: buscar email por empresa ──────────────────────────────
def fetch_sin_email_con_web(sb, limit: int) -> list[dict]:
    """
    Leads SIN email pero CON website, no procesados aún.
    Ideal para find_by_company ya que tienen presencia web confirmada.
    """
    resp = sb.table("macrisa_leads").select(
        "id, nombre, email, telefono, website, confianza, calidad_stars"
    ).is_("email", "null").eq(
        "anymail_procesado", False
    ).not_.is_("website", "null").limit(limit).execute()

    return resp.data or []


# ── Actualizar registro en Supabase ───────────────────────────────────────────
def actualizar_lead(
    sb,
    lead_id: str,
    email: str | None,
    email_status: str,
    anymail_creditos: float,
    telefono: str,
    website: str,
    confianza: str,
    dry_run: bool,
):
    """Actualiza macrisa_leads con resultado de AnyMailFinder."""
    new_stars = calcular_stars(email, telefono, website, confianza, email_status)

    updates = {
        "email_status": email_status,
        "anymail_procesado": True,
        "anymail_creditos": anymail_creditos,
        "calidad_stars": new_stars,
    }
    if email:
        updates["email"] = email

    if dry_run:
        return

    try:
        sb.table("macrisa_leads").update(updates).eq("id", lead_id).execute()
    except Exception as e:
        logger.warning(f"Error actualizando {lead_id}: {e}")


# ── Procesar lote Ruta A ──────────────────────────────────────────────────────
async def procesar_lote_verificacion(sb, lote: list[dict], dry_run: bool) -> dict:
    """Verifica emails existentes (0.1 crédito c/u)."""
    from leadforge.anymail_enricher import anymail

    stats = {"procesados": 0, "validos": 0, "invalidos": 0, "errores": 0, "creditos": 0.0}

    tasks = [anymail.verify_email(lead["email"]) for lead in lote]
    resultados = await asyncio.gather(*tasks, return_exceptions=True)

    for lead, resultado in zip(lote, resultados):
        if isinstance(resultado, Exception):
            stats["errores"] += 1
            actualizar_lead(
                sb, lead["id"],
                lead["email"], "error", 0.0,
                lead.get("telefono"), lead.get("website"), lead.get("confianza"),
                dry_run,
            )
            continue

        if resultado.error:
            stats["errores"] += 1
            actualizar_lead(
                sb, lead["id"],
                lead["email"], "error", 0.0,
                lead.get("telefono"), lead.get("website"), lead.get("confianza"),
                dry_run,
            )
            continue

        email_status = "unknown"
        if resultado.emails:
            email_status = resultado.emails[0].get("email_status", "unknown")

        if email_status == "valid":
            stats["validos"] += 1
        else:
            stats["invalidos"] += 1

        stats["creditos"] += resultado.credits_used
        stats["procesados"] += 1

        actualizar_lead(
            sb, lead["id"],
            lead["email"], email_status, resultado.credits_used,
            lead.get("telefono"), lead.get("website"), lead.get("confianza"),
            dry_run,
        )

    return stats


# ── Procesar lote Ruta B ──────────────────────────────────────────────────────
async def procesar_lote_busqueda(sb, lote: list[dict], dry_run: bool) -> dict:
    """Busca emails por nombre de empresa (1 crédito c/u)."""
    from leadforge.anymail_enricher import anymail

    stats = {
        "procesados": 0, "encontrados": 0, "sin_resultado": 0,
        "errores": 0, "creditos": 0.0
    }

    tasks = [anymail.find_by_company(lead["nombre"]) for lead in lote]
    resultados = await asyncio.gather(*tasks, return_exceptions=True)

    for lead, resultado in zip(lote, resultados):
        if isinstance(resultado, Exception):
            stats["errores"] += 1
            actualizar_lead(
                sb, lead["id"],
                None, "no_encontrado", 0.0,
                lead.get("telefono"), lead.get("website"), lead.get("confianza"),
                dry_run,
            )
            continue

        if resultado.error:
            stats["errores"] += 1
            actualizar_lead(
                sb, lead["id"],
                None, "error", 0.0,
                lead.get("telefono"), lead.get("website"), lead.get("confianza"),
                dry_run,
            )
            continue

        stats["creditos"] += resultado.credits_used
        stats["procesados"] += 1

        # Tomar el primer email válido que encuentre
        email_encontrado = None
        email_status = "no_encontrado"

        if resultado.emails:
            # Preferir email válido, si no tomar el primero
            for em in resultado.emails:
                if em.get("email_status") == "valid":
                    email_encontrado = em.get("email")
                    email_status = "valid"
                    break
            if not email_encontrado:
                email_encontrado = resultado.emails[0].get("email")
                email_status = resultado.emails[0].get("email_status", "unknown")

        if email_encontrado:
            stats["encontrados"] += 1
        else:
            stats["sin_resultado"] += 1

        actualizar_lead(
            sb, lead["id"],
            email_encontrado, email_status, resultado.credits_used,
            lead.get("telefono"), lead.get("website"), lead.get("confianza"),
            dry_run,
        )

    return stats


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Verificar emails Macrisa con AnyMailFinder")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin guardar en DB")
    parser.add_argument("--limit", type=int, default=500, help="Máx leads a procesar por ruta (default: 500)")
    parser.add_argument("--solo-verificar", action="store_true", help="Solo Ruta A: verificar emails existentes")
    parser.add_argument("--solo-buscar", action="store_true", help="Solo Ruta B: buscar emails por empresa")
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("  MACRISA — Verificación AnyMailFinder")
    print("=" * 65)
    if args.dry_run:
        print("  ⚠️  MODO DRY-RUN — No se guardará nada en Supabase")
    print()

    sb = get_supabase()

    # Verificar estado de cuenta AnyMailFinder
    from leadforge.anymail_enricher import anymail
    estado_cuenta = await anymail.check_account_status()
    if not estado_cuenta.get("ok"):
        print(f"  ❌ ERROR AnyMailFinder: {estado_cuenta.get('error')}")
        return
    creditos_inicio = estado_cuenta.get("credits_remaining", 0)
    print(f"  💳 Créditos disponibles: {creditos_inicio:,}")
    print()

    t_inicio = time.time()

    # ─── Estadísticas globales ─────────────────────────────────────────────────
    stats_global = {
        # Ruta A
        "a_total": 0, "a_validos": 0, "a_invalidos": 0,
        "a_errores": 0, "a_creditos": 0.0,
        # Ruta B
        "b_total": 0, "b_encontrados": 0, "b_sin_resultado": 0,
        "b_errores": 0, "b_creditos": 0.0,
    }

    # ──────────────────────────────────────────────────────────────────────────
    # RUTA A: Verificar emails existentes (0.1 crédito c/u)
    # ──────────────────────────────────────────────────────────────────────────
    if not args.solo_buscar:
        print(f"  RUTA A — Verificando emails existentes (0.1 crédito c/u)")
        print(f"  Límite: {args.limit} leads")
        print()

        leads_a = fetch_pendientes_verificacion(sb, args.limit)
        print(f"  → {len(leads_a)} leads pendientes de verificación encontrados")

        if leads_a:
            stats_global["a_total"] = len(leads_a)
            procesados_a = 0

            for i in range(0, len(leads_a), BATCH_SIZE):
                lote = leads_a[i:i + BATCH_SIZE]
                resultado = await procesar_lote_verificacion(sb, lote, args.dry_run)

                stats_global["a_validos"] += resultado["validos"]
                stats_global["a_invalidos"] += resultado["invalidos"]
                stats_global["a_errores"] += resultado["errores"]
                stats_global["a_creditos"] += resultado["creditos"]
                procesados_a += resultado["procesados"]

                pct = min((i + len(lote)) / len(leads_a) * 100, 100)
                print(
                    f"\r  A: {i + len(lote):>4}/{len(leads_a)} ({pct:.0f}%) "
                    f"| ✅ válidos: {stats_global['a_validos']} "
                    f"| ❌ inválidos: {stats_global['a_invalidos']} "
                    f"| 💳 {stats_global['a_creditos']:.1f} créditos  ",
                    end="", flush=True,
                )

                if i + BATCH_SIZE < len(leads_a):
                    await asyncio.sleep(DELAY_ENTRE_LOTES)

            print()  # nueva línea tras progreso

        print()

    # ──────────────────────────────────────────────────────────────────────────
    # RUTA B: Buscar email por empresa (1 crédito c/u)
    # ──────────────────────────────────────────────────────────────────────────
    if not args.solo_verificar:
        print(f"  RUTA B — Buscando emails por empresa (1 crédito c/u)")
        print(f"  Límite: {args.limit} leads (solo los que tienen website)")
        print()

        leads_b = fetch_sin_email_con_web(sb, args.limit)
        print(f"  → {len(leads_b)} leads sin email + con website encontrados")

        if leads_b:
            # Estimar costo
            costo_estimado = len(leads_b) * 1.0
            print(f"  → Costo estimado: {costo_estimado:,.0f} créditos")
            if costo_estimado > creditos_inicio * 0.5:
                print(f"  ⚠️  Esto usará >{costo_estimado/creditos_inicio*100:.0f}% de tus créditos")
            print()

            stats_global["b_total"] = len(leads_b)

            for i in range(0, len(leads_b), BATCH_SIZE):
                lote = leads_b[i:i + BATCH_SIZE]
                resultado = await procesar_lote_busqueda(sb, lote, args.dry_run)

                stats_global["b_encontrados"] += resultado["encontrados"]
                stats_global["b_sin_resultado"] += resultado["sin_resultado"]
                stats_global["b_errores"] += resultado["errores"]
                stats_global["b_creditos"] += resultado["creditos"]

                pct = min((i + len(lote)) / len(leads_b) * 100, 100)
                print(
                    f"\r  B: {i + len(lote):>4}/{len(leads_b)} ({pct:.0f}%) "
                    f"| 📧 encontrados: {stats_global['b_encontrados']} "
                    f"| ∅ sin resultado: {stats_global['b_sin_resultado']} "
                    f"| 💳 {stats_global['b_creditos']:.0f} créditos  ",
                    end="", flush=True,
                )

                if i + BATCH_SIZE < len(leads_b):
                    await asyncio.sleep(DELAY_ENTRE_LOTES)

            print()  # nueva línea

        print()

    elapsed = time.time() - t_inicio
    creditos_usados = stats_global["a_creditos"] + stats_global["b_creditos"]

    # ── Reporte final ──────────────────────────────────────────────────────────
    print("=" * 65)
    print("  RESULTADO FINAL — MACRISA AnyMailFinder")
    print("=" * 65)

    if not args.solo_buscar:
        print(f"\n  RUTA A — Verificación de emails existentes:")
        print(f"    Total procesados:    {stats_global['a_total']:>5,}")
        print(f"    ✅ Emails válidos:   {stats_global['a_validos']:>5,}")
        print(f"    ❌ Emails inválidos: {stats_global['a_invalidos']:>5,}")
        print(f"    ⚠️  Errores:          {stats_global['a_errores']:>5,}")
        print(f"    💳 Créditos usados:  {stats_global['a_creditos']:>7.1f}")

    if not args.solo_verificar:
        print(f"\n  RUTA B — Búsqueda de emails por empresa:")
        print(f"    Total procesados:    {stats_global['b_total']:>5,}")
        print(f"    📧 Emails encontrados: {stats_global['b_encontrados']:>4,}")
        print(f"    ∅  Sin resultado:    {stats_global['b_sin_resultado']:>5,}")
        print(f"    ⚠️  Errores:          {stats_global['b_errores']:>5,}")
        print(f"    💳 Créditos usados:  {stats_global['b_creditos']:>7.0f}")

    print(f"\n  RESUMEN:")
    print(f"    💳 Total créditos usados:  {creditos_usados:>7.1f}")
    print(f"    💳 Créditos restantes est: {creditos_inicio - creditos_usados:>7.1f}")
    print(f"    ⏱  Tiempo total:          {elapsed:>6.1f}s")

    if args.dry_run:
        print(f"\n  ⚠️  DRY-RUN: Ningún dato fue guardado en Supabase")

    # Distribución de calidad resultante
    try:
        resp = sb.table("macrisa_leads").select("calidad_stars", count="exact").execute()
        if hasattr(resp, 'count'):
            print(f"\n  Para ver distribución actualizada ejecuta en Supabase SQL Editor:")
            print(f"  SELECT calidad_stars, COUNT(*) FROM macrisa_leads GROUP BY 1 ORDER BY 1 DESC;")
    except Exception:
        pass

    print("=" * 65)
    print(f"\n  PRÓXIMO PASO:")
    print(f"    Revisar calidad en Supabase y lanzar campaña con leads ★★★★+")
    print()


if __name__ == "__main__":
    asyncio.run(main())
