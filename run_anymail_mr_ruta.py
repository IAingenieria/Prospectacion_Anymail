"""
AnymailFinder — Procesamiento completo para cliente Mr Ruta
Fase 1: leads con sitio_web → buscar email por dominio
Fase 2: leads con email DENUE (sin web) → verificar email existente
Actualiza verificado, email_status, anymail_procesado, canal_recomendado en Supabase.
"""
import asyncio
import re
import httpx
from supabase import create_client

SUPABASE_URL = "https://pfurkonwbjfmxpfogdtr.supabase.co"
SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBmdXJrb253YmpmbXhwZm9nZHRyIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjkxNDAyNCwiZXhwIjoyMDg4NDkwMDI0fQ.bDfVa-QyFOYRY7RuJqDMKyiTq1gJ5DujPETjsheQCHQ"
ANYMAIL_KEY = "SJ5S6ZgGxoMsm14cdbvTvGiD"
MR_RUTA_ID = "be119ffc-dfc3-431e-9ba7-b44123934258"
ANYMAIL_BASE = "https://api.anymailfinder.com/v5.1"
CONCURRENCY = 3
BATCH_SIZE = 50

db = create_client(SUPABASE_URL, SERVICE_KEY)
sem = asyncio.Semaphore(CONCURRENCY)

ANYMAIL_HEADERS = {
    "X-API-Key": ANYMAIL_KEY,
    "Content-Type": "application/json",
}

DOMINIOS_PERSONALES = {
    "gmail.com","hotmail.com","yahoo.com","outlook.com","live.com",
    "icloud.com","aol.com","hotmail.es","yahoo.com.mx","protonmail.com",
}


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    url = url.lower().strip()
    if not url.startswith("http"):
        url = "https://" + url
    m = re.search(r"https?://(?:www\.)?([^/\s?#]+)", url)
    return m.group(1) if m else None


def is_corporate_email(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain not in DOMINIOS_PERSONALES


async def find_email_by_company(company_name: str, website: str | None, client: httpx.AsyncClient) -> dict:
    async with sem:
        try:
            payload = {"company_name": company_name}
            if website:
                domain = extract_domain(website)
                if domain:
                    payload["website"] = domain
            r = await client.post(
                f"{ANYMAIL_BASE}/find-email/company",
                headers=ANYMAIL_HEADERS,
                json=payload,
                timeout=20,
            )
            if r.status_code in (401, 402):
                return {"error": f"HTTP {r.status_code}", "stop": True}
            return r.json()
        except Exception as e:
            return {"error": str(e)}


async def verify_email(email: str, client: httpx.AsyncClient) -> dict:
    async with sem:
        try:
            r = await client.post(
                f"{ANYMAIL_BASE}/verify-email",
                headers=ANYMAIL_HEADERS,
                json={"email": email},
                timeout=15,
            )
            if r.status_code in (401, 402):
                return {"error": f"HTTP {r.status_code}", "stop": True}
            return r.json()
        except Exception as e:
            return {"error": str(e)}


def update_lead(lead_id: str, updates: dict):
    db.table("leads_master").update(updates).eq("id", lead_id).execute()


async def check_credits() -> int:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{ANYMAIL_BASE}/account", headers=ANYMAIL_HEADERS)
        data = r.json()
        return data.get("credits_left", data.get("credits_remaining", 0))


async def process_fase1(leads: list[dict]) -> dict:
    """Fase 1: leads con sitio_web — buscar email por dominio."""
    stats = {"procesados": 0, "encontrados": 0, "sin_email": 0, "errores": 0, "stop": False}

    async def process_one(lead):
        if stats["stop"]:
            return
        if not lead.get("nombre_negocio"):
            update_lead(lead["id"], {"anymail_procesado": True})
            stats["procesados"] += 1
            return

        async with httpx.AsyncClient(timeout=25) as client:
            result = await find_email_by_company(lead.get("nombre_negocio", ""), lead.get("sitio_web"), client)

        if result.get("stop"):
            stats["stop"] = True
            return
        if result.get("error"):
            stats["errores"] += 1
            update_lead(lead["id"], {"anymail_procesado": True})
            stats["procesados"] += 1
            return

        emails = result.get("emails", [])
        best = None
        for e in emails:
            email_val = e.get("email", "") if isinstance(e, dict) else e
            status = e.get("email_status", "unknown") if isinstance(e, dict) else "unknown"
            if status == "valid" and is_corporate_email(email_val):
                best = {"email": email_val, "status": "valid"}
                break
        if not best:
            for e in emails:
                email_val = e.get("email", "") if isinstance(e, dict) else e
                status = e.get("email_status", "unknown") if isinstance(e, dict) else "unknown"
                if status in ("valid", "catch_all"):
                    best = {"email": email_val, "status": status}
                    break

        if best:
            canal = "email" if best["status"] == "valid" and is_corporate_email(best["email"]) else "brevo"
            update_lead(lead["id"], {
                "email": best["email"],
                "email_status": best["status"],
                "verificado": best["status"] == "valid",
                "anymail_procesado": True,
                "canal_recomendado": canal,
            })
            stats["encontrados"] += 1
        else:
            top_status = result.get("status", "not_found")
            update_lead(lead["id"], {
                "anymail_procesado": True,
                "email_status": top_status if top_status != "not_found" else None,
            })
            stats["sin_email"] += 1

        stats["procesados"] += 1

    # Process in batches
    for i in range(0, len(leads), BATCH_SIZE):
        if stats["stop"]:
            break
        batch = leads[i:i+BATCH_SIZE]
        await asyncio.gather(*[process_one(l) for l in batch])
        pct = int((i + len(batch)) / len(leads) * 100)
        print(f"  Fase 1 — {i+len(batch)}/{len(leads)} ({pct}%) | encontrados: {stats['encontrados']} | sin email: {stats['sin_email']}")

    return stats


async def process_fase2(leads: list[dict]) -> dict:
    """Fase 2: leads con email DENUE (sin web) — verificar email."""
    stats = {"procesados": 0, "validos": 0, "invalidos": 0, "errores": 0, "stop": False}

    async def process_one(lead):
        if stats["stop"]:
            return
        email = lead.get("email", "")
        if not email or "@" not in email:
            update_lead(lead["id"], {"anymail_procesado": True})
            stats["procesados"] += 1
            return

        async with httpx.AsyncClient(timeout=20) as client:
            result = await verify_email(email, client)

        if result.get("stop"):
            stats["stop"] = True
            return

        status = result.get("email_status", "unknown")
        canal = None
        verificado = False

        if status == "valid":
            verificado = True
            canal = "email" if is_corporate_email(email) else "brevo"
            stats["validos"] += 1
        else:
            stats["invalidos"] += 1

        update_lead(lead["id"], {
            "email_status": status,
            "verificado": verificado,
            "anymail_procesado": True,
            **({"canal_recomendado": canal} if canal else {}),
        })
        stats["procesados"] += 1

    for i in range(0, len(leads), BATCH_SIZE):
        if stats["stop"]:
            break
        batch = leads[i:i+BATCH_SIZE]
        await asyncio.gather(*[process_one(l) for l in batch])
        pct = int((i + len(batch)) / len(leads) * 100)
        print(f"  Fase 2 — {i+len(batch)}/{len(leads)} ({pct}%) | válidos: {stats['validos']} | inválidos: {stats['invalidos']}")

    return stats


async def main():
    print("=== AnymailFinder — Mr Ruta ===\n")

    # Check credits
    creditos = await check_credits()
    print(f"Créditos disponibles: {creditos:,}")
    if creditos < 50:
        print("⚠️  Créditos insuficientes. Abortando.")
        return

    # Fase 1: leads con sitio_web, verificado=False
    r1 = db.table("leads_master").select(
        "id, nombre_negocio, ciudad, sitio_web, email"
    ).eq("cliente_id", MR_RUTA_ID).eq("verificado", False).not_.is_(
        "sitio_web", "null"
    ).limit(2000).execute()
    fase1_leads = r1.data or []

    # Fase 2: leads con email, sin web, anymail_procesado=False
    r2 = db.table("leads_master").select(
        "id, nombre_negocio, ciudad, email"
    ).eq("cliente_id", MR_RUTA_ID).eq("verificado", False).eq(
        "anymail_procesado", False
    ).not_.is_("email", "null").is_("sitio_web", "null").limit(2000).execute()
    fase2_leads = r2.data or []

    print(f"Fase 1 pendientes (con sitio web): {len(fase1_leads)}")
    print(f"Fase 2 pendientes (email DENUE sin web): {len(fase2_leads)}")
    print(f"Total a procesar: {len(fase1_leads) + len(fase2_leads)}\n")

    if not fase1_leads and not fase2_leads:
        print("✅ No hay leads pendientes — todo ya fue procesado.")
        return

    # Run Fase 1
    if fase1_leads:
        print(f"▶ Iniciando Fase 1 ({len(fase1_leads)} leads con dominio)...")
        s1 = await process_fase1(fase1_leads)
        print(f"\n✅ Fase 1 completada:")
        print(f"   Procesados: {s1['procesados']}")
        print(f"   Emails encontrados: {s1['encontrados']}")
        print(f"   Sin email: {s1['sin_email']}")
        print(f"   Errores: {s1['errores']}")
        if s1["stop"]:
            print("⛔ Detenido por error de cuenta/créditos.")
            return

    # Run Fase 2
    if fase2_leads:
        print(f"\n▶ Iniciando Fase 2 ({len(fase2_leads)} emails DENUE a verificar)...")
        s2 = await process_fase2(fase2_leads)
        print(f"\n✅ Fase 2 completada:")
        print(f"   Procesados: {s2['procesados']}")
        print(f"   Emails válidos: {s2['validos']}")
        print(f"   Inválidos: {s2['invalidos']}")
        print(f"   Errores: {s2['errores']}")

    # Final credits
    creditos_final = await check_credits()
    print(f"\nCréditos usados: {creditos - creditos_final:.1f}")
    print(f"Créditos restantes: {creditos_final:,}")

    # Final stats from DB
    stats_r = db.table("leads_master").select(
        "email, verificado, email_status, anymail_procesado"
    ).eq("cliente_id", MR_RUTA_ID).execute()
    leads_final = stats_r.data or []
    verificados = sum(1 for l in leads_final if l.get("verificado"))
    validos = sum(1 for l in leads_final if l.get("email_status") == "valid")
    procesados_total = sum(1 for l in leads_final if l.get("anymail_procesado"))

    print(f"\n📊 Estado final Mr Ruta en Supabase:")
    print(f"   Total leads: {len(leads_final)}")
    print(f"   anymail_procesado=True: {procesados_total}")
    print(f"   verificado=True: {verificados}")
    print(f"   email_status='valid': {validos}")


if __name__ == "__main__":
    asyncio.run(main())
