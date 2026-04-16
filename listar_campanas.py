"""
Diagnóstico rápido: Lista campañas disponibles en Instantly.ai
y muestra los 216 leads mineros disponibles para Regio Cribas.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx

API_KEY = os.getenv("INSTANTLY_API_KEY")
BASE = "https://api.instantly.ai/api/v1"


async def main():
    print("\n" + "=" * 60)
    print("  INSTANTLY.AI — Campañas disponibles")
    print("=" * 60)

    if not API_KEY:
        print("❌ INSTANTLY_API_KEY no encontrada en .env")
        return

    async with httpx.AsyncClient(timeout=15) as client:

        # Listar campañas
        resp = await client.get(
            f"{BASE}/campaign/list",
            params={"api_key": API_KEY, "limit": 50, "skip": 0},
        )
        print(f"\nStatus API: HTTP {resp.status_code}")

        if resp.status_code != 200:
            print(f"Error: {resp.text[:300]}")
            return

        data = resp.json()
        campanas = data if isinstance(data, list) else data.get("data", [])

        if not campanas:
            print("\n⚠️  No hay campañas creadas en Instantly.")
            print("   Crea una en: https://app.instantly.ai/app/campaigns")
        else:
            print(f"\n{len(campanas)} campaña(s) encontradas:\n")
            for c in campanas:
                cid = c.get("id", c.get("campaign_id", "?"))
                nombre = c.get("name", "Sin nombre")
                status = c.get("status_description", c.get("status", "?"))
                leads = c.get("lead_count", "?")
                print(f"  📋 {nombre}")
                print(f"     ID:     {cid}")
                print(f"     Status: {status} | Leads: {leads}")
                print()

        # También mostrar info de cuenta
        resp2 = await client.get(
            f"{BASE}/account/list",
            params={"api_key": API_KEY, "limit": 20, "skip": 0},
        )
        if resp2.status_code == 200:
            cuentas = resp2.json()
            if isinstance(cuentas, dict):
                cuentas = cuentas.get("data", [])
            print(f"\n📧 Cuentas de email conectadas: {len(cuentas)}")
            for cuenta in cuentas[:5]:
                email_c = cuenta.get("email", "?")
                warmup = cuenta.get("warmup_status", "?")
                daily = cuenta.get("daily_limit", "?")
                print(f"   {email_c} | warmup: {warmup} | límite: {daily}/día")

    print("\n" + "=" * 60)
    print("  LEADS MINEROS disponibles (Regio Cribas)")
    print("=" * 60)

    from supabase import create_client
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

    resp3 = sb.table("leads_master").select(
        "id, nombre_negocio, email, telefono, categoria, ciudad, estado"
    ).eq("cliente_id", "d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99"
    ).eq("denue_confirmado", True
    ).eq("email_status", "valid"
    ).or_(
        "categoria.ilike.%cantera%,"
        "categoria.ilike.%arena%,"
        "categoria.ilike.%grava%,"
        "categoria.ilike.%marmol%,"
        "categoria.ilike.%miner%,"
        "categoria.ilike.%extrac%,"
        "categoria.ilike.%piedra%,"
        "categoria.ilike.%cemento%,"
        "categoria.ilike.%caliza%"
    ).limit(300).execute()

    leads = resp3.data or []
    print(f"\n✅ {len(leads)} leads mineros con email válido")
    print("\nPrimeros 5:")
    for l in leads[:5]:
        print(f"  • {l['nombre_negocio']} — {l['email']} — {l.get('ciudad', '?')}")

    print(f"\n{'='*60}")
    print("PRÓXIMO PASO:")
    print("  1. Copia el ID de la campaña de arriba (o créala en Instantly)")
    print("  2. Ejecuta: .\\venv\\Scripts\\python.exe -X utf8 lanzar_regio_cribas.py <CAMPAIGN_ID>")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
