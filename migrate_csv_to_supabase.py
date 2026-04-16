"""
LeadForge — Migración de CSVs de Apify a Supabase
===================================================
Lee los CSVs exportados de Baserow/Apify:
  - export - Google Maps - Cuadrícula.csv
  - export - Leads Telefonos - Cuadrícula.csv

Aplica criterios LeadForge:
  1. Requiere nombre del negocio
  2. Valida formato de email
  3. Score de jerarquía de email (ceo@ > info@)
  4. Deduplicación por email (1 por email)
  5. Deduplicación por dominio (max 2 por dominio, mayor jerarquía primero)
  6. DB1 (email_leads): registros con email válido
  7. DB2 (social_leads): registros con solo teléfono

Uso: python -X utf8 migrate_csv_to_supabase.py
"""
import csv
import re
import sys
import os
import hashlib
from datetime import datetime
from collections import defaultdict
from typing import Optional

# ── Encoding Windows ──────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ── Agregar raíz al path ──────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from leadforge.config import cfg
from supabase import create_client

# ============================================================
# CONFIGURACIÓN
# ============================================================
DATOS_DIR = r"C:\Users\Dell\Downloads\Datos"

# Todos los CSVs a procesar (rutas relativas a DATOS_DIR)
CSV_FILES = [
    r"export - Google Maps - Cuadrícula_20260307_170159.csv",   # hoy - más completo
    r"export - Google Maps Completo.csv",                        # versión extendida
    r"export - Google Maps - Cuadrícula.csv",                    # versión original
    r"export - Leads Telefonos - Cuadrícula.csv",                # solo teléfonos
    r"contactos_filtrados.csv",                                  # ya filtrado por Anymail
]

CLIENTE_ID          = cfg.cliente_id
MAX_PER_DOMAIN      = 2        # máximo 2 emails por dominio
BATCH_SIZE          = 50       # filas por lote en Supabase

# Email hierarchy: cuanto mayor el score, mejor para cold email
EMAIL_HIERARCHY = {
    "ceo": 10, "director": 10, "directora": 10,
    "owner": 10, "dueno": 10, "propietario": 10, "propietaria": 10,
    "presidente": 10, "presidenta": 10, "gerente": 10, "gerenta": 10,
    "vp": 8, "vice": 8, "socio": 8, "socia": 8,
    "manager": 8, "administrador": 8, "administradora": 8,
    "admin": 7,
    "ventas": 6, "sales": 6, "comercial": 6, "compras": 6,
    "negocios": 6, "business": 6, "marketing": 6,
    "operaciones": 4, "operations": 4, "contabilidad": 4,
    "info": 2, "contact": 2, "contacto": 2, "hola": 2, "hello": 2,
    "team": 2, "support": 2, "soporte": 2, "ayuda": 2, "help": 2,
    "mail": 2, "email": 2, "correo": 2,
    "noreply": 1, "no-reply": 1, "donotreply": 1,
}

# ============================================================
# FUNCIONES DE UTILIDAD
# ============================================================

def get_hierarchy_score(email: str) -> int:
    """Score 1-10 basado en el prefijo del email."""
    if not email or "@" not in email:
        return 0
    prefix = email.split("@")[0].lower()
    # Buscar match exacto
    if prefix in EMAIL_HIERARCHY:
        return EMAIL_HIERARCHY[prefix]
    # Buscar si el prefijo contiene alguna palabra clave
    for keyword, score in sorted(EMAIL_HIERARCHY.items(), key=lambda x: -x[1]):
        if keyword in prefix:
            return score
    # Patrón nombre.apellido o primeranombre → probablemente persona real → score medio-alto
    if re.match(r'^[a-z]{2,}\.[a-z]{2,}$', prefix):    # juan.perez
        return 8
    if re.match(r'^[a-z]{2,}[0-9]{0,2}$', prefix):     # juan, juan12
        return 7
    return 5  # default


def extract_domain(email: str) -> Optional[str]:
    """Extrae el dominio del email."""
    if email and "@" in email:
        return email.split("@")[-1].lower().strip()
    return None


def is_valid_email(email: str) -> bool:
    """Verifica formato básico de email. No acepta dominios genéricos de ejemplo."""
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email.strip()):
        return False
    # Rechazar dominios de ejemplo / placeholder
    bad_domains = {"example.com", "test.com", "email.com", "correo.com", "N/A"}
    domain = extract_domain(email)
    if domain in bad_domains or email.upper() == "N/A":
        return False
    return True


def is_valid_phone(phone) -> bool:
    """Verifica que el teléfono sea usable."""
    if phone is None:
        return False
    cleaned = str(phone).strip().replace(" ", "").replace("-", "")
    return cleaned not in ["", "0", "nan", "None", "false", "False"] and len(cleaned) >= 7


def format_phone(phone) -> Optional[str]:
    """Normaliza teléfono a formato internacional."""
    if not is_valid_phone(phone):
        return None
    cleaned = re.sub(r'[^0-9+]', '', str(phone).strip())
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("52") and len(cleaned) >= 12:
        return "+" + cleaned
    if len(cleaned) == 10:
        return "+52" + cleaned
    return cleaned


def parse_info_completa(info: str) -> dict:
    """Extrae datos estructurados del campo 'Info Completa'."""
    result = {
        "categoria": None, "ciudad": None, "estado": None,
        "codigo_postal": None, "rating": None, "review_count": None,
        "google_maps_url": None,
    }
    if not info:
        return result

    # Categoría
    m = re.search(r'Categor[íi]a:\s*(.+?)(?:\n|$)', info)
    if m:
        result["categoria"] = m.group(1).strip()

    # Rating y reviews
    m = re.search(r'Calificaci[oó]n:\s*([\d.]+)\s*estrellas\s*\(basado en (\d+)', info)
    if m:
        result["rating"] = float(m.group(1))
        result["review_count"] = int(m.group(2))

    # Ciudad — buscar patrón "Ciudad: Monterrey, Nuevo León"
    m = re.search(r'Ciudad:\s*(.+?)(?:\n|$)', info)
    if m:
        ciudad_raw = m.group(1).strip()
        parts = ciudad_raw.split(",")
        result["ciudad"] = parts[0].strip()
        if len(parts) > 1:
            result["estado"] = parts[-1].strip()

    # Código Postal desde dirección
    m = re.search(r'\b(\d{5})\b', info)
    if m:
        result["codigo_postal"] = m.group(1)

    # Google Maps URL
    m = re.search(r'(https://www\.google\.com/maps/\S+)', info)
    if m:
        result["google_maps_url"] = m.group(1).strip()

    return result


def parse_address(address: str) -> dict:
    """Extrae ciudad y estado de la dirección si Info Completa no lo tiene."""
    result = {"ciudad": None, "estado": None, "codigo_postal": None}
    if not address:
        return result
    # Patrón: "Calle, Colonia, CP Ciudad, Estado, País"
    m = re.search(r'(\d{5})\s+([^,]+),\s*([^,]+),', address)
    if m:
        result["codigo_postal"] = m.group(1)
        result["ciudad"] = m.group(2).strip()
        raw_estado = m.group(3).strip()
        estado_map = {
            "N.L.": "Nuevo León", "N. L.": "Nuevo León",
            "CDMX": "Ciudad de México", "D.F.": "Ciudad de México",
            "Jal.": "Jalisco", "Ver.": "Veracruz",
            "Coah.": "Coahuila", "Tamps.": "Tamaulipas",
            "Chih.": "Chihuahua", "Son.": "Sonora",
        }
        result["estado"] = estado_map.get(raw_estado, raw_estado)
    return result


# ============================================================
# LEER CSVs
# ============================================================

def read_csv_robust(filepath: str) -> list[dict]:
    """Lee CSV con campos multi-línea, prueba múltiples encodings."""
    for encoding in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(filepath, "r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
            print(f"  [{encoding}] {len(rows)} filas")
            return rows
        except Exception:
            continue
    print(f"  [ERROR] No se pudo leer: {filepath}")
    return []


# ============================================================
# FILTRADO Y DEDUPLICACIÓN
# ============================================================

def filter_leads(all_rows: list[dict]) -> dict:
    """
    Aplica criterios LeadForge y separa leads en DB1 y DB2.
    Retorna: {email_leads, social_leads, stats}
    """
    stats = defaultdict(int)
    has_email = []
    has_phone_only = []

    for row in all_rows:
        nombre = row.get("Nombre", "").strip()
        email  = row.get("Correo electrónico", "").strip()
        phone  = row.get("Telefono", "").strip()

        if not nombre:
            stats["sin_nombre"] += 1
            continue

        if is_valid_email(email):
            row["_email_clean"] = email.lower().strip()
            row["_score"]       = get_hierarchy_score(email)
            row["_domain"]      = extract_domain(email.lower())
            has_email.append(row)
        elif is_valid_phone(phone):
            has_phone_only.append(row)
        else:
            stats["sin_contacto"] += 1

    # ── DB1: Ordenar por score descendente ──────────────────
    has_email.sort(key=lambda x: x["_score"], reverse=True)

    # Dedup por email exacto
    seen_emails = {}
    email_deduped = []
    for row in has_email:
        em = row["_email_clean"]
        if em in seen_emails:
            stats["dup_email"] += 1
        else:
            seen_emails[em] = True
            email_deduped.append(row)

    # Dedup por dominio (max 2 por dominio)
    domain_counts = defaultdict(int)
    final_email = []
    for row in email_deduped:
        d = row.get("_domain", "")
        if not d:
            continue
        if domain_counts[d] >= MAX_PER_DOMAIN:
            stats["dup_dominio"] += 1
            continue
        domain_counts[d] += 1
        final_email.append(row)

    # ── DB2: Dedup por teléfono ──────────────────────────────
    seen_phones = set()
    final_social = []
    for row in has_phone_only:
        phone = format_phone(row.get("Telefono", ""))
        if phone and phone not in seen_phones:
            seen_phones.add(phone)
            final_social.append(row)

    return {
        "email_leads":  final_email,
        "social_leads": final_social,
        "stats": dict(stats),
    }


# ============================================================
# CONSTRUIR REGISTROS PARA SUPABASE
# ============================================================

def build_email_record(row: dict) -> dict:
    """Construye dict para insertar en email_leads."""
    email   = row.get("_email_clean") or row.get("Correo electrónico", "").strip().lower()
    info    = row.get("Info Completa", "") or ""
    address = row.get("Direccion", "") or ""

    parsed = parse_info_completa(info)
    if not parsed["ciudad"]:
        addr = parse_address(address)
        parsed["ciudad"] = addr.get("ciudad")
        parsed["estado"]  = parsed["estado"] or addr.get("estado")
        parsed["codigo_postal"] = parsed["codigo_postal"] or addr.get("codigo_postal")

    # Categoria: priorizar Info Completa > columna Industria > columna Subcategoria > default
    categoria = (
        parsed.get("categoria")
        or row.get("Industria", "").strip()
        or row.get("Subcategoria", "").strip()
        or "Sin categoría"
    )

    score = row.get("_score", get_hierarchy_score(email))

    return {
        "nombre_negocio":    row.get("Nombre", "").strip(),
        "email":             email,
        "email_status":      "unverified",
        "hierarchy_score":   score,
        "lead_score":        min(score * 10, 100),
        "categoria":         categoria,
        "ciudad":            parsed.get("ciudad") or row.get("Municipio", "").strip() or "Monterrey",
        "estado":            parsed.get("estado") or row.get("Estado", "").strip() or "Nuevo León",
        "pais":              row.get("Pais", "").strip() or "Mexico",
        "sitio_web":         row.get("Website", "").strip() or None,
        "telefono":          format_phone(row.get("Telefono", "")),
        "direccion_completa": address or None,
        "rating":            parsed.get("rating"),
        "review_count":      parsed.get("review_count"),
        "responds_to_reviews": False,
        "perfil_apify":      "importado_csv",
        "termino_busqueda":  "importacion_manual",
        "cliente_id":        CLIENTE_ID,
        "do_not_contact":    False,
        "scraped_at":        datetime.utcnow().isoformat(),
    }


def build_social_record(row: dict) -> dict:
    """Construye dict para insertar en social_leads."""
    info    = row.get("Info Completa", "") or ""
    address = row.get("Direccion", "") or ""

    parsed = parse_info_completa(info)
    if not parsed["ciudad"]:
        addr = parse_address(address)
        parsed["ciudad"] = addr.get("ciudad")
        parsed["estado"]  = parsed["estado"] or addr.get("estado")

    categoria = (
        parsed.get("categoria")
        or row.get("Industria", "").strip()
        or "Sin categoría"
    )

    phone = format_phone(row.get("Telefono", ""))

    return {
        "nombre_negocio":        row.get("Nombre", "").strip(),
        "categoria":             categoria,
        "ciudad":                parsed.get("ciudad") or "Monterrey",
        "estado_geografico":     parsed.get("estado") or "Nuevo León",
        "telefono":              phone,
        "actividad_digital_score": 30,
        "canal_asignado":        "whatsapp" if phone else None,
        "estado_campania":       "pendiente",
        "cliente_id":            CLIENTE_ID,
        "scraped_at":            datetime.utcnow().isoformat(),
    }


# ============================================================
# SUPABASE: CREAR CLIENTE SI NO EXISTE
# ============================================================

def ensure_client_exists(db) -> bool:
    """
    Verifica que exista el registro de cliente en Supabase.
    Si no existe, lo crea con datos mínimos.
    FK constraint requiere que cliente_id exista en clientes.
    """
    try:
        result = db.table("clientes").select("id").eq("id", CLIENTE_ID).execute()
        if result.data:
            print(f"  [OK] Cliente {CLIENTE_ID[:8]}... ya existe en Supabase")
            return True

        # No existe → crearlo
        api_key_hash = hashlib.sha256(CLIENTE_ID.encode()).hexdigest()
        db.table("clientes").insert({
            "id":           CLIENTE_ID,
            "nombre":       "Zenon — LeadForge Admin",
            "email":        "admin@leadforge.local",
            "api_key_hash": api_key_hash,
            "plan":         "agency",
            "activo":       True,
        }).execute()
        print(f"  [OK] Cliente creado: {CLIENTE_ID[:8]}...")
        return True
    except Exception as e:
        print(f"  [WARN] No se pudo verificar/crear cliente: {e}")
        print(f"  [INFO] Intentando insertar leads sin cliente_id...")
        return False


# ============================================================
# SUBIR A SUPABASE
# ============================================================

def upload_batch(db, table: str, records: list[dict]) -> tuple[int, int]:
    """
    Inserta un lote en Supabase.
    Retorna (insertados, errores).
    """
    inserted = 0
    errors = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        try:
            resp = db.table(table).insert(batch).execute()
            n = len(resp.data) if resp.data else len(batch)
            inserted += n
            print(f"    Lote {i // BATCH_SIZE + 1}/{(len(records) - 1) // BATCH_SIZE + 1}: +{n} filas")
        except Exception as e:
            err_msg = str(e)
            # Si es error de FK por cliente_id, intentar sin cliente_id
            if "foreign key" in err_msg.lower() or "fk_" in err_msg.lower():
                print(f"    [WARN] FK error — reintentando sin cliente_id...")
                for rec in batch:
                    rec["cliente_id"] = None
                try:
                    resp = db.table(table).insert(batch).execute()
                    n = len(resp.data) if resp.data else len(batch)
                    inserted += n
                    print(f"    Lote {i // BATCH_SIZE + 1}: +{n} filas (sin cliente_id)")
                except Exception as e2:
                    print(f"    [ERROR] Lote {i // BATCH_SIZE + 1}: {e2}")
                    errors += len(batch)
            elif "unique" in err_msg.lower() or "duplicate" in err_msg.lower():
                # Insertar uno por uno para aprovechar los no duplicados
                print(f"    [INFO] Duplicados detectados — insertando uno a uno...")
                for rec in batch:
                    try:
                        r = db.table(table).insert(rec).execute()
                        if r.data:
                            inserted += 1
                    except Exception:
                        errors += 1
            else:
                print(f"    [ERROR] Lote {i // BATCH_SIZE + 1}: {err_msg[:120]}")
                errors += len(batch)
    return inserted, errors


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 65)
    print("  LeadForge — Migración CSV -> Supabase")
    print("=" * 65)

    # ── 1. Leer CSVs ─────────────────────────────────────────
    print("\n[1/4] Leyendo archivos CSV...")
    all_rows = []

    for filename in CSV_FILES:
        path = os.path.join(DATOS_DIR, filename)
        if os.path.exists(path):
            print(f"  {filename}")
            rows = read_csv_robust(path)
            # Normalizar columna de email (algunos CSV usan 'Email' en lugar de 'Correo electrónico')
            for row in rows:
                if "Email" in row and "Correo electrónico" not in row:
                    row["Correo electrónico"] = row.get("Email", "")
                if "Municipio" in row and "Ciudad" not in row:
                    row["Ciudad"] = row.get("Municipio", "")
            all_rows.extend(rows)
        else:
            print(f"  [SKIP] No encontrado: {filename}")

    print(f"\n  Total combinado antes de filtrar: {len(all_rows)} filas")

    if not all_rows:
        print("\n  [ERROR] No hay datos para procesar. Verifica rutas de los CSV.")
        return

    # ── 2. Filtrar y deduplicar ───────────────────────────────
    print("\n[2/4] Aplicando filtros LeadForge...")
    filtered   = filter_leads(all_rows)
    email_recs = filtered["email_leads"]
    social_recs = filtered["social_leads"]
    stats      = filtered["stats"]

    print(f"\n  Filtros aplicados:")
    for k, v in stats.items():
        print(f"    {k:<20}: {v}")

    print(f"\n  --> DB1 (email_leads):  {len(email_recs)} leads listos")
    print(f"  --> DB2 (social_leads): {len(social_recs)} leads listos")

    if email_recs:
        print(f"\n  Top 8 email leads (por jerarquía):")
        for r in email_recs[:8]:
            em = r.get("_email_clean", "")
            sc = r.get("_score", 0)
            nm = r.get("Nombre", "")[:35]
            print(f"    [{sc}/10] {em:<35} — {nm}")

    # ── 3. Conectar a Supabase ────────────────────────────────
    print("\n[3/4] Conectando a Supabase...")
    try:
        db = create_client(cfg.supabase_url, cfg.supabase_service_key)
        print(f"  [OK] Conectado a {cfg.supabase_url[:40]}...")
    except Exception as e:
        print(f"  [ERROR] No se pudo conectar: {e}")
        return

    # Verificar/crear cliente
    client_ok = ensure_client_exists(db)
    if not client_ok:
        print("  Continuando sin garantía de FK...")

    # ── 4. Subir a Supabase ───────────────────────────────────
    print("\n[4/4] Subiendo registros a Supabase...")
    total_inserted = 0
    total_errors   = 0

    # DB1: email_leads
    if email_recs:
        print(f"\n  Insertando {len(email_recs)} registros en email_leads...")
        records = []
        for row in email_recs:
            try:
                records.append(build_email_record(row))
            except Exception as e:
                print(f"    [WARN] Error construyendo registro: {e}")
                total_errors += 1

        ins, err = upload_batch(db, "email_leads", records)
        total_inserted += ins
        total_errors   += err

    # DB2: social_leads
    if social_recs:
        print(f"\n  Insertando {len(social_recs)} registros en social_leads...")
        records = []
        for row in social_recs:
            try:
                records.append(build_social_record(row))
            except Exception as e:
                print(f"    [WARN] Error construyendo registro social: {e}")
                total_errors += 1

        ins, err = upload_batch(db, "social_leads", records)
        total_inserted += ins
        total_errors   += err

    # ── Resumen final ─────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  RESUMEN FINAL")
    print("=" * 65)
    print(f"  Filas en CSV (total bruto):   {len(all_rows)}")
    print(f"  Email leads procesados:        {len(email_recs)}")
    print(f"  Social leads procesados:       {len(social_recs)}")
    print(f"  Insertados en Supabase:        {total_inserted}")
    print(f"  Errores:                       {total_errors}")
    print(f"\n  Estado email_status:           'unverified'")
    print(f"  Proximos pasos:")
    print(f"    1. Recarga creditos Anymail Finder")
    print(f"    2. Ejecuta verificacion: python -X utf8 run.py --verify-leads")
    print(f"    3. Solo los 'valid' iran a campanas de Instantly.ai")
    print("=" * 65)


if __name__ == "__main__":
    main()
