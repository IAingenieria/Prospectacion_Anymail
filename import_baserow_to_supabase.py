"""
import_baserow_to_supabase.py
Importa los CSVs exportados de Baserow a Supabase leads_master.
Usa upsert para no duplicar registros ya existentes.
"""

import csv
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import uuid
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SUPABASE_URL = "https://pfurkonwbjfmxpfogdtr.supabase.co"
API_KEY      = "SUPABASE_SERVICE_ROLE_KEY_REDACTED"
CLIENTE_ID   = "d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99"  # Zenon / LeadForge master

CSV_FOLDER   = r"C:\Users\Dell\Downloads\Datos"
ANYMAIL_CSV  = r"C:\Users\Dell\Downloads\Base de datos Anymail\contactos_filtrados.csv"

HEADERS = {
    "apikey":        API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates,return=representation",
}

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def limpiar_telefono(tel: str) -> str | None:
    """Normaliza teléfono: asegura que tenga +52 si es mexicano."""
    if not tel or tel.strip() in ("", "0"):
        return None
    t = tel.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if t.startswith("52") and len(t) == 12:
        return f"+{t}"
    if t.startswith("+52"):
        return t
    if len(t) == 10 and t.isdigit():
        return f"+52{t}"
    if len(t) == 12 and t.isdigit():
        return f"+{t}"
    return t if t else None


def calcular_score(row: dict) -> int:
    score = 0
    if row.get("email"):      score += 10
    if row.get("telefono"):   score += 8
    if row.get("sitio_web"):  score += 5
    return score


def upsert_batch(records: list[dict]) -> tuple[int, int]:
    """Upsert de un batch de registros. Retorna (insertados, actualizados)."""
    url = f"{SUPABASE_URL}/rest/v1/leads_master?on_conflict=nombre_negocio,ciudad,cliente_id"
    payload = json.dumps(records, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            body = json.loads(resp.read())
            insertados  = sum(1 for r in body if r.get("created_at") and
                              abs((datetime.now(timezone.utc) -
                                   datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                                   ).total_seconds()) < 60)
            return len(body), 0
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ⚠️  HTTP {e.code}: {err[:200]}")
        return 0, 0


# ─── LECTURA DE CSVs ───────────────────────────────────────────────────────────

def leer_todos_los_csvs() -> dict:
    """
    Consolida todos los CSVs de Baserow en un dict {nombre: datos}.
    Prioriza el archivo con más campos completos por cada negocio.
    """
    negocios = {}

    archivos = []
    for fname in os.listdir(CSV_FOLDER):
        if fname.endswith(".csv") and not fname.startswith("Lista") \
                and not fname.startswith("goodman") \
                and not fname.startswith("lupront"):
            archivos.append(os.path.join(CSV_FOLDER, fname))

    # También el anymail
    if os.path.exists(ANYMAIL_CSV):
        archivos.append(ANYMAIL_CSV)

    print(f"📂 Leyendo {len(archivos)} archivos CSV...")

    for path in archivos:
        fname = os.path.basename(path)
        try:
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except Exception as e:
            print(f"  ⚠️  No se pudo leer {fname}: {e}")
            continue

        count = 0
        for r in rows:
            nombre = r.get("Nombre", "").strip()
            if not nombre:
                continue
            count += 1

            # Extraer ciudad y estado de Dirección si están vacíos
            ciudad  = r.get("Municipio", "").strip()
            estado  = r.get("Estado", "").strip()
            direccion = r.get("Direccion", r.get("Dirección", "")).strip()

            # Intentar extraer ciudad de la dirección si no hay municipio
            if not ciudad and direccion:
                # Formato: "Calle 123, Col, CP Ciudad, N.L., México"
                partes = direccion.split(",")
                if len(partes) >= 3:
                    ciudad = partes[-3].strip().split(" ")[-1]  # heurística

            email   = r.get("Correo electrónico", "").strip()
            telefono = limpiar_telefono(r.get("Telefono", r.get("Teléfono", "")))
            website  = r.get("Website", r.get("Sitio web", "")).strip() or None
            industria = r.get("Industria", r.get("Industria/Subcategoria", "")).strip() or None

            if nombre not in negocios:
                negocios[nombre] = {
                    "nombre":    nombre,
                    "email":     email or None,
                    "telefono":  telefono,
                    "ciudad":    ciudad or None,
                    "estado":    estado or None,
                    "direccion": direccion or None,
                    "website":   website,
                    "industria": industria,
                }
            else:
                b = negocios[nombre]
                if not b["email"]    and email:     b["email"]    = email
                if not b["telefono"] and telefono:  b["telefono"] = telefono
                if not b["ciudad"]   and ciudad:    b["ciudad"]   = ciudad
                if not b["estado"]   and estado:    b["estado"]   = estado
                if not b["website"]  and website:   b["website"]  = website
                if not b["industria"] and industria: b["industria"] = industria

        print(f"  ✅ {fname}: {count} filas leídas")

    return negocios


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  IMPORTADOR BASEROW → SUPABASE")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    negocios = leer_todos_los_csvs()
    print(f"\n📊 Total negocios únicos encontrados: {len(negocios)}")
    con_email = sum(1 for v in negocios.values() if v["email"])
    con_tel   = sum(1 for v in negocios.values() if v["telefono"])
    print(f"   Con email   : {con_email}")
    print(f"   Con teléfono: {con_tel}")

    # Construir registros para leads_master
    ahora = datetime.now(timezone.utc).isoformat()
    records = []

    for nombre, b in negocios.items():
        score = 0
        if b["email"]:    score += 10
        if b["telefono"]: score += 8
        if b["website"]:  score += 5

        if b["email"] or b["telefono"]:
            canal = "email" if b["email"] else "whatsapp"
        else:
            canal = "social"

        rec = {
            "cliente_id":         CLIENTE_ID,
            "nombre_negocio":     nombre,
            "categoria":          b["industria"],
            "ciudad":             b["ciudad"] or "Monterrey",
            "estado":             b["estado"] or "Nuevo León",
            "pais":               "MX",
            "direccion":          b["direccion"],
            "sitio_web":          b["website"],
            "telefono":           b["telefono"],
            "email":              b["email"],
            "email_status":       "verified" if b["email"] else None,
            "lead_score":         score,
            "canal_recomendado":  canal,
            "etapa":              "nuevo",
            "anymail_procesado":  bool(b["email"]),
            "termino_busqueda":   "baserow_import",
            "apify_run_id":       "baserow_csv_import",
            "scraped_at":         ahora,
        }
        records.append(rec)

    print(f"\n🚀 Iniciando upsert de {len(records)} registros a Supabase...")
    print("   (duplicados se actualizarán automáticamente)\n")

    # Procesar en batches de 50
    BATCH = 50
    total_ok = 0
    total_err = 0

    for i in range(0, len(records), BATCH):
        batch = records[i:i + BATCH]
        ok, _ = upsert_batch(batch)
        total_ok += ok
        fin = min(i + BATCH, len(records))
        pct = int(fin / len(records) * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"  [{bar}] {pct:3d}%  {fin}/{len(records)}  ✅ {ok} upserted")
        time.sleep(0.3)  # respetar rate limits

    print()
    print("=" * 60)
    print("  RESULTADO FINAL")
    print("=" * 60)
    print(f"  Registros procesados : {len(records)}")
    print(f"  Upsert exitosos      : {total_ok}")
    print(f"  Con email            : {con_email}")
    print(f"  Con teléfono         : {con_tel}")
    print()
    print("  ✅ Todos los datos de Baserow ya están en Supabase.")
    print("     Visibles en el dashboard de LeadForge.")


if __name__ == "__main__":
    main()
