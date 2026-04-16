"""
LeadForge — Import BIG ONE: Lista de Negocios BASE 2026
========================================================
Importa los 651,955 negocios de México a las 2 bases de datos:
  - DB1 (email_leads):  negocios con email → para verificar con Anymail y usar en Instantly
  - DB2 (social_leads): negocios con teléfono → para WhatsApp via yCloud

FILOSOFÍA: NO se filtra por industria en la BIG ONE.
  La base de datos almacena TODO tipo de negocio porque cada cliente
  tiene un perfil de comprador diferente:
    - Cliente pinturas  → filtra herrerías, maquiladoras, constructoras
    - Cliente limpieza  → filtra restaurantes, tortillerías, panaderías ✓
    - Cliente uniformes → filtra fábricas, empresas con personal
    - Cliente X         → filtra según su caso de uso
  El filtro de categoría se aplica AL MOMENTO DE CREAR LA CAMPAÑA,
  no al importar la base de datos.

Fuente: Lista de Negocios BASE 2026.csv (DENUE - INEGI)
  42 columnas: nom_estab, nombre_act (categoría), municipio, entidad,
               telefono, correoelec, www, latitud, longitud, etc.

Uso:
  # Solo Nuevo León:
  python -X utf8 import_big_one.py --estado "Nuevo León"

  # Múltiples estados:
  python -X utf8 import_big_one.py --estados "Nuevo León,Coahuila,Jalisco"

  # Todo México (30-60 min):
  python -X utf8 import_big_one.py --todo

  # Solo contar sin importar:
  python -X utf8 import_big_one.py --estado "Nuevo León" --dry-run
"""
import csv
import re
import sys
import os
import argparse
from datetime import datetime, timezone
from collections import defaultdict, Counter
from typing import Optional

# ── Encoding Windows ──────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from leadforge.config import cfg
from supabase import create_client

# ============================================================
# CONFIGURACIÓN
# ============================================================
CSV_BASE_2026   = r"C:\Users\Dell\Downloads\Datos\Lista de Negocios BASE 2026.csv"
CLIENTE_ID      = cfg.cliente_id
BATCH_SIZE      = 200     # filas por lote en Supabase
MAX_PER_DOMAIN  = 2       # máximo 2 emails por dominio (protección)

# ============================================================
# FILTRO DE INDUSTRIA — Compradores de pinturas/recubrimientos
# ============================================================
# Códigos SCIAN (primeros 3 dígitos del campo codigo_act)
# Fuente: http://www.inegi.org.mx/app/scian/
SCIAN_COMPRADORES_PINTURA = {
    # ── Manufactura metálica (usan anticorrosivos, esmaltes, primarios) ──
    "331",  # Industrias metálicas básicas (acero, aluminio)
    "332",  # Fabricación de productos metálicos (herrería, estructuras, maquinado)
    "333",  # Fabricación de maquinaria y equipo industrial
    "334",  # Fabricación de equipo de cómputo y electrónico
    "335",  # Fabricación de accesorios de iluminación y equipo eléctrico
    "336",  # Fabricación de equipo de transporte (carrocerías, remolques)
    "339",  # Otras industrias manufactureras
    # ── Madera y muebles (usan barnices, lacas, selladores) ──
    "321",  # Industria de la madera (aserraderos, tableros)
    "337",  # Fabricación de muebles y colchones
    # ── Construcción (usan pintura para acabados de obra) ──
    "236",  # Edificación (casas, edificios)
    "237",  # Construcción de ingeniería civil (carreteras, presas)
    "238",  # Trabajos especializados de construcción (pintura de obra, acabados)
    # ── Impresión y papel (tintas, recubrimientos especiales) ──
    "322",  # Industria del papel y cartón
    "323",  # Impresión e industrias conexas (serigrafía, flexografía)
    # ── Plástico, hule y minerales (recubrimientos, desmoldantes) ──
    "325",  # Industria química (incluye fabricantes de pinturas = competidores Y clientes)
    "326",  # Industria del plástico y del hule
    "327",  # Fabricación de productos a base de minerales no metálicos (cemento, cerámica)
    # ── Derivados del petróleo (uso industrial de solventes) ──
    "324",  # Fabricación de productos derivados del petróleo y carbón
    # ── Comercio — distribuidores y revendedores ──
    "434",  # Comercio al por mayor de materiales de construcción, ferretería
    "467",  # Comercio al por menor de ferretería, tlapalería y vidrios
    # ── Reparación y mantenimiento automotriz ──
    "811",  # Reparación y mantenimiento de automóviles, camiones y motocicletas
    # ── Agricultura con invernaderos/estructuras metálicas ──
    "111",  # Agricultura — algunos usan pintura en estructuras agrícolas
}

# Normalización de estados
ESTADOS_NORM = {
    "CIUDAD DE MEXICO": "Ciudad de México",
    "NUEVO LEON": "Nuevo León",
    "JALISCO": "Jalisco",
    "MICHOACAN DE OCAMPO": "Michoacán de Ocampo",
    "VERACRUZ DE IGNACIO DE LA LLAVE": "Veracruz",
    "MEXICO": "Estado de México",
    "GUANAJUATO": "Guanajuato",
    "PUEBLA": "Puebla",
    "OAXACA": "Oaxaca",
    "CHIAPAS": "Chiapas",
    "GUERRERO": "Guerrero",
    "YUCATAN": "Yucatán",
    "HIDALGO": "Hidalgo",
    "TLAXCALA": "Tlaxcala",
    "SONORA": "Sonora",
    "COAHUILA DE ZARAGOZA": "Coahuila",
    "TAMAULIPAS": "Tamaulipas",
    "CHIHUAHUA": "Chihuahua",
    "SINALOA": "Sinaloa",
    "BAJA CALIFORNIA": "Baja California",
}

# Prefijos de email por jerarquía (como en migrate_csv_to_supabase.py)
EMAIL_HIERARCHY = {
    "ceo": 10, "director": 10, "propietario": 10, "gerente": 10,
    "manager": 8, "admin": 7, "ventas": 6, "sales": 6, "comercial": 6,
    "info": 2, "contact": 2, "hola": 2, "noreply": 1,
}


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def normalize_estado(raw: str) -> str:
    if not raw:
        return "México"
    upper = raw.strip().upper()
    return ESTADOS_NORM.get(upper, raw.strip().title())


def is_valid_email(email: str) -> bool:
    if not email or not email.strip():
        return False
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def is_valid_phone(phone: str) -> bool:
    if not phone or not phone.strip():
        return False
    cleaned = re.sub(r'\D', '', phone)
    return len(cleaned) >= 7 and cleaned not in ["0", "0000000"]


def format_phone(phone: str) -> Optional[str]:
    if not is_valid_phone(phone):
        return None
    cleaned = re.sub(r'\D', '', phone)
    if len(cleaned) == 10:
        return "+52" + cleaned
    if len(cleaned) == 12 and cleaned.startswith("52"):
        return "+" + cleaned
    return cleaned


def get_hierarchy_score(email: str) -> int:
    if not email or "@" not in email:
        return 0
    prefix = email.split("@")[0].lower()
    if prefix in EMAIL_HIERARCHY:
        return EMAIL_HIERARCHY[prefix]
    for kw, sc in sorted(EMAIL_HIERARCHY.items(), key=lambda x: -x[1]):
        if kw in prefix:
            return sc
    if re.match(r'^[a-z]{2,}\.[a-z]{2,}$', prefix):
        return 6
    if re.match(r'^[a-z]{2,}[0-9]{0,2}$', prefix):
        return 5
    return 3


def extract_domain(email: str) -> Optional[str]:
    if email and "@" in email:
        return email.split("@")[-1].lower().strip()
    return None


def build_email_lead(row: dict) -> dict:
    """Construye registro para email_leads desde una fila del DENUE."""
    email = row.get("correoelec", "").strip()
    nombre = (row.get("nom_estab") or row.get("raz_social") or "").strip()
    municipio = row.get("municipio", "").strip()
    entidad = normalize_estado(row.get("entidad", ""))
    categoria = row.get("nombre_act", "").strip()
    score = get_hierarchy_score(email)

    # Construir dirección desde campos DENUE
    tipo_vial = row.get("tipo_vial", "")
    nom_vial = row.get("nom_vial", "")
    num_ext = row.get("numero_ext", "")
    cod_postal = row.get("cod_postal", "").strip()
    nomb_asent = row.get("nomb_asent", "")
    direccion = f"{tipo_vial} {nom_vial} {num_ext}, {nomb_asent}, {cod_postal}".strip(", ")

    return {
        "nombre_negocio":     nombre,
        "email":              email.lower(),
        "email_status":       "unverified",
        "hierarchy_score":    score,
        "lead_score":         min(score * 8, 60),   # cap en 60 (calidad media — no verificado)
        "categoria":          categoria or "Sin categoría",
        "ciudad":             municipio,
        "estado":             entidad,
        "pais":               "Mexico",
        "sitio_web":          row.get("www", "").strip() or None,
        "telefono":           format_phone(row.get("telefono", "")),
        "direccion_completa": direccion or None,
        "rating":             None,
        "review_count":       None,
        "responds_to_reviews": False,
        "perfil_apify":       "denue_base_2026",
        "termino_busqueda":   f"denue:{row.get('codigo_act','')}",
        "cliente_id":         CLIENTE_ID,
        "do_not_contact":     False,
        "scraped_at":         datetime.now(timezone.utc).isoformat(),
    }


def build_social_lead(row: dict) -> dict:
    """Construye registro para social_leads desde una fila del DENUE."""
    nombre = (row.get("nom_estab") or row.get("raz_social") or "").strip()
    municipio = row.get("municipio", "").strip()
    entidad = normalize_estado(row.get("entidad", ""))
    categoria = row.get("nombre_act", "").strip()
    phone = format_phone(row.get("telefono", ""))

    return {
        "nombre_negocio":        nombre,
        "categoria":             categoria or "Sin categoría",
        "ciudad":                municipio,
        "estado_geografico":     entidad,
        "telefono":              phone,
        "actividad_digital_score": 20,   # sin datos digitales de este registro
        "canal_asignado":        "whatsapp",
        "estado_campania":       "pendiente",
        "cliente_id":            CLIENTE_ID,
        "scraped_at":            datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# UPLOAD EN LOTES
# ============================================================

def upload_batch(db, table: str, records: list[dict]) -> tuple[int, int]:
    """Inserta un lote. Maneja errores y duplicados."""
    inserted = 0
    errors = 0
    try:
        resp = db.table(table).insert(records).execute()
        n = len(resp.data) if resp.data else len(records)
        inserted += n
    except Exception as e:
        err_msg = str(e)
        if "unique" in err_msg.lower() or "duplicate" in err_msg.lower():
            # Insertar uno por uno para aprovechar los únicos
            for rec in records:
                try:
                    r = db.table(table).insert(rec).execute()
                    if r.data:
                        inserted += 1
                except Exception:
                    errors += 1
        elif "foreign key" in err_msg.lower():
            for rec in records:
                rec["cliente_id"] = None
            try:
                resp = db.table(table).insert(records).execute()
                n = len(resp.data) if resp.data else len(records)
                inserted += n
            except Exception as e2:
                print(f"      [ERROR FK] {e2}")
                errors += len(records)
        else:
            print(f"      [ERROR] {err_msg[:120]}")
            errors += len(records)
    return inserted, errors


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="LeadForge — Import BIG ONE")
    parser.add_argument("--estado", help="Filtrar por un estado: 'Nuevo León'")
    parser.add_argument("--estados", help="Filtrar por varios estados: 'Nuevo León,Coahuila'")
    parser.add_argument("--todo", action="store_true", help="Importar todo México")
    parser.add_argument("--dry-run", action="store_true", help="Solo contar, no importar")
    parser.add_argument("--limpiar", action="store_true", help="Eliminar registros anteriores de BASE 2026 antes de re-importar")
    args = parser.parse_args()

    # Necesitamos db antes de la limpieza
    if not args.dry_run:
        from supabase import create_client as _create
        db = _create(cfg.supabase_url, cfg.supabase_service_key)

    # Determinar estados a filtrar
    filtrar_estados = set()
    if args.todo:
        filtrar_estados = set()   # vacío = todos
        print("Modo: TODO MEXICO")
    elif args.estados:
        for e in args.estados.split(","):
            filtrar_estados.add(e.strip().lower())
        print(f"Modo: Estados = {args.estados}")
    elif args.estado:
        filtrar_estados.add(args.estado.strip().lower())
        print(f"Modo: Estado = {args.estado}")
    else:
        # Default: Nuevo León solamente
        filtrar_estados.add("nuevo león")
        filtrar_estados.add("nuevo leon")
        print("Modo: Por defecto → Nuevo León")

    dry_run = args.dry_run
    if dry_run:
        print("DRY-RUN activado — solo se cuenta, no se importa")

    print()
    print("=" * 65)
    print("  LeadForge — Import BASE 2026 (BIG ONE)")
    print("=" * 65)

    # ── Limpieza opcional ─────────────────────────────────────
    if getattr(args, 'limpiar', False) and not dry_run:
        print("\n[LIMPIEZA] Eliminando registros anteriores de denue_base_2026...")
        try:
            # Borrar email_leads de BASE 2026 (tienen perfil_apify marcado)
            r1 = db.table("email_leads").delete().eq(
                "perfil_apify", "denue_base_2026"
            ).execute()
            print(f"  email_leads eliminados: {len(r1.data) if r1.data else '?'}")
        except Exception as e:
            print(f"  [ERROR] al limpiar email_leads: {e}")
        print("  Nota: social_leads se mantienen (teléfonos siguen siendo útiles)")
        print()

    # ── Conectar a Supabase ───────────────────────────────────
    if not dry_run:
        print("\nConectando a Supabase...")
        db = create_client(cfg.supabase_url, cfg.supabase_service_key)
        print(f"  [OK] Conectado a {cfg.supabase_url[:40]}...")

        # Cargar emails ya existentes en DB para dedup
        print("  Cargando emails ya existentes en Supabase...")
        try:
            result = db.table("email_leads").select("email").eq("cliente_id", CLIENTE_ID).execute()
            existing_emails = {r["email"].lower() for r in (result.data or [])}
            print(f"  Emails existentes en Supabase: {len(existing_emails)}")
        except:
            existing_emails = set()

        # Cargar teléfonos ya existentes
        print("  Cargando teléfonos ya existentes en Supabase...")
        try:
            result2 = db.table("social_leads").select("telefono").eq("cliente_id", CLIENTE_ID).execute()
            existing_phones = {r["telefono"] for r in (result2.data or []) if r.get("telefono")}
            print(f"  Teléfonos existentes en Supabase: {len(existing_phones)}")
        except:
            existing_phones = set()
    else:
        db = None
        existing_emails = set()
        existing_phones = set()

    # ── Leer y procesar CSV ───────────────────────────────────
    print(f"\nLeyendo {CSV_BASE_2026}...")
    print("(Procesando 651,955 registros — por favor espera)\n")

    # Acumuladores
    email_batch  = []
    social_batch = []
    domain_counts = defaultdict(int)  # dedup por dominio

    # Estadísticas
    stats = Counter()
    total_email_inserted = 0
    total_social_inserted = 0
    total_email_errors   = 0
    total_social_errors  = 0
    last_print = 0

    with open(CSV_BASE_2026, "r", encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            stats["total"] += 1

            # Filtrar por estado si aplica
            entidad_raw = row.get("entidad", "").strip()
            entidad_norm = normalize_estado(entidad_raw)
            entidad_lower = entidad_raw.lower()

            if filtrar_estados:
                # Verificar si el estado coincide (permite parcial: "nuevo" matchea "Nuevo León")
                match = any(
                    f in entidad_lower or f in entidad_norm.lower()
                    for f in filtrar_estados
                )
                if not match:
                    continue

            stats["en_estado"] += 1

            nombre = (row.get("nom_estab") or row.get("raz_social") or "").strip()
            if not nombre:
                stats["sin_nombre"] += 1
                continue

            email = row.get("correoelec", "").strip()
            phone = row.get("telefono", "").strip()
            has_email = is_valid_email(email)
            has_phone = is_valid_phone(phone)

            if not has_email and not has_phone:
                stats["sin_contacto"] += 1
                continue

            # ── DB1: Email lead ──────────────────────────────
            if has_email:
                email_lower = email.lower()
                if email_lower in existing_emails:
                    stats["email_dup_existente"] += 1
                elif email_lower in {r.get("email", "") for r in email_batch}:
                    stats["email_dup_batch"] += 1
                else:
                    domain = extract_domain(email_lower)
                    if domain and domain_counts[domain] >= MAX_PER_DOMAIN:
                        stats["email_dup_dominio"] += 1
                    else:
                        if domain:
                            domain_counts[domain] += 1
                        email_batch.append(build_email_lead(row))
                        existing_emails.add(email_lower)
                        stats["email_nuevos"] += 1

            # ── DB2: Social lead (si no tiene email o tiene teléfono) ──
            if has_phone:
                phone_fmt = format_phone(phone)
                if phone_fmt and phone_fmt not in existing_phones:
                    social_batch.append(build_social_lead(row))
                    existing_phones.add(phone_fmt)
                    stats["phone_nuevos"] += 1
                else:
                    stats["phone_dup"] += 1

            # ── Upload en lotes ───────────────────────────────
            if not dry_run:
                if len(email_batch) >= BATCH_SIZE:
                    ins, err = upload_batch(db, "email_leads", email_batch[:BATCH_SIZE])
                    total_email_inserted += ins
                    total_email_errors   += err
                    email_batch = email_batch[BATCH_SIZE:]

                if len(social_batch) >= BATCH_SIZE:
                    ins, err = upload_batch(db, "social_leads", social_batch[:BATCH_SIZE])
                    total_social_inserted += ins
                    total_social_errors  = getattr(main, '_se', 0) + err
                    social_batch = social_batch[BATCH_SIZE:]

            # ── Progreso ─────────────────────────────────────
            if stats["en_estado"] - last_print >= 1000:
                last_print = stats["en_estado"]
                print(
                    f"  Procesados: {stats['en_estado']:>6,} | "
                    f"Email: {stats['email_nuevos']:>5,} | "
                    f"Tel: {stats['phone_nuevos']:>5,} | "
                    f"Insertados: {total_email_inserted+total_social_inserted:>5,}",
                    end="\r", flush=True
                )

    print()  # nueva línea después del \r

    # ── Subir remanentes ─────────────────────────────────────
    if not dry_run:
        if email_batch:
            print(f"\n  Subiendo {len(email_batch)} email leads restantes...")
            ins, err = upload_batch(db, "email_leads", email_batch)
            total_email_inserted += ins
            total_email_errors   += err

        if social_batch:
            print(f"  Subiendo {len(social_batch)} social leads restantes...")
            ins, err = upload_batch(db, "social_leads", social_batch)
            total_social_inserted += ins

    # ── Resumen ───────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  RESUMEN")
    print("=" * 65)
    print(f"  Total registros en CSV:          {stats['total']:>10,}")
    print(f"  En el/los estado(s) filtrado(s): {stats['en_estado']:>10,}")
    print(f"  Sin nombre (descartados):         {stats['sin_nombre']:>10,}")
    print(f"  Sin contacto (descartados):       {stats['sin_contacto']:>10,}")
    print(f"  Emails duplicados (omitidos):     {stats['email_dup_existente']+stats['email_dup_batch']+stats['email_dup_dominio']:>10,}")
    print(f"  Teléfonos duplicados (omitidos):  {stats['phone_dup']:>10,}")
    print()
    print(f"  Emails preparados:                {stats['email_nuevos']:>10,}")
    print(f"  Teléfonos preparados:             {stats['phone_nuevos']:>10,}")
    if not dry_run:
        print()
        print(f"  Email leads insertados (DB1):     {total_email_inserted:>10,}")
        print(f"  Social leads insertados (DB2):    {total_social_inserted:>10,}")
        print(f"  Errores email:                    {total_email_errors:>10,}")
    print("=" * 65)
    print()
    if not dry_run:
        print("Proximos pasos:")
        print("  1. Recarga Anymail Finder para verificar emails")
        print("  2. python -X utf8 run.py --verify-leads")
        print("  3. Para importar otro estado: python -X utf8 import_big_one.py --estado 'Jalisco'")
        print("  4. Para importar todo Mexico: python -X utf8 import_big_one.py --todo")
    else:
        print("Para importar, quita el flag --dry-run")


if __name__ == "__main__":
    main()
