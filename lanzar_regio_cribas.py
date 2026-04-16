"""
LeadForge — Lanzar campaña Regio Cribas en Instantly.ai
========================================================
Toma los leads mineros con email validado (email_status='valid')
y los inyecta en la campaña Regio Cribas de Instantly.

Variables del template:
  {{first_name}} → nombre del negocio (o contacto si existe)
  {{city}}       → ciudad del lead

Uso:
  cd "C:/Users/Dell/Documents/CLAUDE DESKTOP/Claude Leads Instantly"
  .\\venv\\Scripts\\python.exe -X utf8 lanzar_regio_cribas.py
  .\\venv\\Scripts\\python.exe -X utf8 lanzar_regio_cribas.py --dry-run
  .\\venv\\Scripts\\python.exe -X utf8 lanzar_regio_cribas.py --limit 20
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx
from supabase import create_client

# ── Config ─────────────────────────────────────────────────────────────────────
CAMPAIGN_ID   = "ed81e355-716e-4a12-9175-9ae241e2ec05"
CLIENTE_ID    = "d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99"   # Regio Cribas
API_KEY       = os.getenv("INSTANTLY_API_KEY")
BASE          = "https://api.instantly.ai/api/v1"
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY")

# Categorías mineras objetivo
CATEGORIAS_MINERIA = [
    "cantera", "arena", "grava", "marmol", "miner",
    "extrac", "piedra", "cemento", "caliza", "triturad",
    "barita", "yeso", "silice", "feldespato",
]


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def nombre_a_first_name(nombre_negocio: str) -> str:
    """
    Convierte el nombre del negocio a un {{first_name}} presentable.
    Toma las primeras 2 palabras para no saturar el saludo.
    Ej: 'CALIZAS TRITURADAS INDUSTRIALES SA DE CV' → 'Calizas Trituradas'
    """
    palabras = nombre_negocio.strip().title().split()
    # Quitar sufijos legales comunes
    stopwords = {"Sa", "De", "Cv", "S.A.", "S.A", "De", "C.V", "C.V.", "Srl", "Ac"}
    palabras_limpias = [p for p in palabras if p not in stopwords]
    return " ".join(palabras_limpias[:2]) if palabras_limpias else nombre_negocio[:20]


def construir_payload_lead(lead: dict) -> dict:
    """
    Construye el payload de Instantly para un lead de leads_master.
    Campos usados en el template: {{first_name}}, {{city}}
    """
    nombre = lead.get("nombre_negocio") or ""
    ciudad = lead.get("ciudad") or lead.get("estado") or "tu ciudad"
    email  = lead.get("email", "")
    tel    = lead.get("telefono") or ""
    web    = lead.get("sitio_web") or ""

    first_name = nombre_a_first_name(nombre) if nombre else "equipo"

    # Personalización: primera línea del email (opcional pero mejora open rate)
    personalization = (
        f"Vi que están en el sector de {lead.get('categoria', 'materiales')} "
        f"en {ciudad} y creo que podemos ayudarles."
    )

    payload = {
        "email": email,
        "first_name": first_name,
        "last_name": "",
        "company_name": nombre[:100] if nombre else "",
        "personalization": personalization,
        "phone": tel,
        "website": web,
        "custom_variables": {
            "city": ciudad,
            "empresa": nombre[:80] if nombre else "",
            "categoria": lead.get("categoria", ""),
        },
    }
    return payload


async def add_leads_to_instantly(leads_payload: list[dict], dry_run: bool) -> dict:
    """Envía los leads a Instantly en lotes de 100."""
    if dry_run:
        print(f"\n  [DRY-RUN] Se enviarían {len(leads_payload)} leads a Instantly")
        for l in leads_payload[:3]:
            print(f"    • {l['email']} | first_name='{l['first_name']}' | city='{l['custom_variables'].get('city')}'")
        return {"total_new_leads": len(leads_payload), "dry_run": True}

    total_added = 0
    BATCH = 100

    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(leads_payload), BATCH):
            lote = leads_payload[i:i + BATCH]
            body = {
                "campaign_id": CAMPAIGN_ID,
                "leads": lote,
                "skip_if_in_workspace": True,   # no duplicar
            }
            resp = await client.post(
                f"{BASE}/lead/add",
                params={"api_key": API_KEY},
                json=body,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                added = data.get("total_new_leads", len(lote))
                total_added += added
                print(f"  ✅ Lote {i//BATCH + 1}: +{added} leads inyectados")
            else:
                print(f"  ❌ Error lote {i//BATCH + 1}: HTTP {resp.status_code} — {resp.text[:200]}")

            if i + BATCH < len(leads_payload):
                await asyncio.sleep(1)

    return {"total_new_leads": total_added}


async def main():
    parser = argparse.ArgumentParser(description="Inyectar leads mineros en Regio Cribas (Instantly)")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin enviar a Instantly")
    parser.add_argument("--limit", type=int, default=None, help="Limitar cantidad de leads")
    parser.add_argument("--incluir-pendientes", action="store_true",
                        help="Incluir tambien leads con email_status='pendiente_validacion'")
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("  REGIO CRIBAS — Inyección de leads en Instantly.ai")
    print("=" * 65)
    if args.dry_run:
        print("  ⚠️  DRY-RUN — No se enviará nada a Instantly")
    print(f"  Campaign ID: {CAMPAIGN_ID}")
    print()

    if not API_KEY:
        print("❌ INSTANTLY_API_KEY no configurada en .env")
        return

    sb = get_supabase()

    # ── Verificar campaña (vía /campaign/list, ya que /campaign/get da 404) ──
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{BASE}/campaign/list",
            params={"api_key": API_KEY, "limit": 100, "skip": 0},
        )
        if resp.status_code != 200:
            print(f"❌ No se pudo listar campañas (HTTP {resp.status_code})")
            return
        data = resp.json()
        campanas = data if isinstance(data, list) else data.get("data", [])
        camp = next((c for c in campanas if c.get("id") == CAMPAIGN_ID or c.get("campaign_id") == CAMPAIGN_ID), None)
        if not camp:
            print(f"❌ Campaña {CAMPAIGN_ID} no encontrada en tu workspace.")
            print(f"   Campañas disponibles:")
            for c in campanas:
                print(f"     • {c.get('name')} → {c.get('id', c.get('campaign_id'))}")
            return
        print(f"  Campaña: {camp.get('name', 'Sin nombre')}")
        print(f"  Status:  {camp.get('status_description', camp.get('status', '?'))}")

    # ── Obtener leads mineros de Supabase ───────────────────────────────────
    print(f"\n  Buscando leads mineros con email validado...")

    # Construir filtro OR para categorías
    filtro_cat = ",".join([f"categoria.ilike.%{c}%" for c in CATEGORIAS_MINERIA])

    statuses = ["valid"]
    if args.incluir_pendientes:
        statuses.append("pendiente_validacion")

    query = (
        sb.table("leads_master")
        .select("id, nombre_negocio, email, telefono, ciudad, estado, categoria, sitio_web, email_status")
        .eq("cliente_id", CLIENTE_ID)
        .in_("email_status", statuses)
        .or_(filtro_cat)
    )
    if args.limit:
        query = query.limit(args.limit)
    else:
        query = query.limit(500)

    result = query.execute()
    leads = result.data or []

    print(f"  → {len(leads)} leads encontrados")

    if not leads:
        print("\n  ⚠️  Sin leads disponibles. Verifica:")
        print("     - email_status = 'valid' en leads_master")
        print("     - cliente_id correcto")
        print("     - Que las categorías coincidan (cantera, arena, cemento, etc.)")
        return

    # ── Preparar payloads ───────────────────────────────────────────────────
    print(f"\n  Preparando payloads para Instantly...")
    payloads = []
    for lead in leads:
        if not lead.get("email"):
            continue
        payload = construir_payload_lead(lead)
        payloads.append(payload)

    print(f"  → {len(payloads)} leads listos para inyectar")
    print(f"\n  Preview primeros 3:")
    for p in payloads[:3]:
        print(f"    • {p['email']}")
        print(f"      first_name: '{p['first_name']}' | city: '{p['custom_variables'].get('city')}'")
        print(f"      personalización: {p['personalization'][:80]}...")
        print()

    # ── Inyectar en Instantly ───────────────────────────────────────────────
    print(f"  Inyectando en campaña Regio Cribas...")
    resultado = await add_leads_to_instantly(payloads, args.dry_run)

    # ── Resumen ─────────────────────────────────────────────────────────────
    total = resultado.get("total_new_leads", 0)
    print("\n" + "=" * 65)
    print("  RESULTADO")
    print("=" * 65)
    print(f"  Leads disponibles:    {len(leads)}")
    print(f"  Leads inyectados:     {total}")
    print(f"  Daily limit:          30/día")
    print(f"  Duración estimada:    {max(1, total // 30)} días")
    print()
    if not args.dry_run and total > 0:
        print("  ✅ Los leads están en cola en Instantly.")
        print("  La campaña enviará automáticamente L-V 9am-6pm.")
        print(f"\n  Revisa: https://app.instantly.ai/app/campaign/{CAMPAIGN_ID}/analytics")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
