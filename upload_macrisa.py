"""
LeadForge — Carga de Base de Datos Macrisa
==========================================
Lee el Excel de Macrisa, cruza con leads_master, e inserta en macrisa_leads.

Funciones:
  1. Cross-reference: detecta si el lead ya existe en leads_master
     - Match por teléfono (exacto)
     - Match por email (exacto)
     - Match por nombre (similitud Jaccard >= 0.7)
  2. Calcula calidad_stars inicial
  3. Inserta en macrisa_leads (tabla separada, nunca toca leads_master)
  4. Reporta estadísticas al final

Uso:
  cd "C:/Users/Dell/Documents/CLAUDE DESKTOP/Claude Leads Instantly"
  .\\venv\\Scripts\\python.exe -X utf8 upload_macrisa.py
  .\\venv\\Scripts\\python.exe -X utf8 upload_macrisa.py --dry-run
  .\\venv\\Scripts\\python.exe -X utf8 upload_macrisa.py --limit 100
"""
import argparse
import logging
import math
import sys
import time
from pathlib import Path

import pandas as pd
from supabase import create_client

# ── Configuración ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

EXCEL_PATH = Path(r"C:\Users\Dell\Downloads\Datos\lista_general_ Macrisa_revisada (1).xlsx")
BATCH_SIZE = 50  # Registros por lote a Supabase


# ── Supabase ──────────────────────────────────────────────────────────────────
def get_supabase():
    from dotenv import load_dotenv
    import os
    load_dotenv(Path(__file__).parent / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL o SUPABASE_SERVICE_KEY no configurados en .env")
    return create_client(url, key)


# ── Limpieza de valores NaN de pandas ────────────────────────────────────────
def _v(x, lower: bool = False) -> str | None:
    """
    Convierte NaN/None/string-'nan'/vacío a None.
    Pandas puede devolver float('nan') en iterrows aunque se haya hecho where(notna()).
    """
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None
    return s.lower() if lower else s


def _vi(x) -> int | None:
    """Convierte a int, devuelve None si es NaN/None."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    try:
        return int(x)
    except (ValueError, TypeError):
        return None


# ── Similitud de nombres ──────────────────────────────────────────────────────
def similitud_jaccard(a: str, b: str) -> float:
    palabras_a = set(a.lower().split())
    palabras_b = set(b.lower().split())
    union = palabras_a | palabras_b
    if not union:
        return 0.0
    return len(palabras_a & palabras_b) / len(union)


# ── Calidad stars ─────────────────────────────────────────────────────────────
def calcular_stars(row: dict) -> int:
    tiene_email = bool(row.get("email"))
    tiene_tel = bool(row.get("telefono"))
    tiene_web = bool(row.get("website"))
    confianza_alta = row.get("confianza") == "alta"

    if tiene_email and tiene_tel and tiene_web and confianza_alta:
        return 4
    if tiene_email and tiene_tel:
        return 3
    if tiene_email or tiene_tel:
        return 2
    return 1


# ── Carga y limpieza del Excel ────────────────────────────────────────────────
def cargar_excel(limit: int = None) -> pd.DataFrame:
    logger.info(f"Leyendo Excel: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    logger.info(f"Filas totales: {len(df)}")

    # Limpiar NaN → None (primera pasada a nivel dataframe)
    df = df.where(pd.notna(df), None)

    # Normalizar teléfonos — usar _v() que también atrapa float('nan') residual
    if "telefono" in df.columns:
        df["telefono"] = df["telefono"].apply(_v)

    # Normalizar emails (lowercase)
    if "email" in df.columns:
        df["email"] = df["email"].apply(lambda x: _v(x, lower=True))

    # Normalizar nombres (strip)
    if "nombre" in df.columns:
        df["nombre"] = df["nombre"].apply(_v)

    if limit:
        df = df.head(limit)
        logger.info(f"Limitado a {limit} filas")

    return df


# ── Cargar datos de referencia de leads_master ───────────────────────────────
def cargar_referencias(sb) -> dict:
    """
    Carga teléfonos, emails y nombres de leads_master para cross-reference.
    Retorna dict con sets para búsqueda O(1).
    """
    logger.info("Cargando referencias de leads_master para cross-reference...")

    telefonos = {}  # telefono → {id, nombre}
    emails_dict = {}    # email → {id, nombre}
    nombres = []    # [(nombre_lower, id, nombre_original)]

    # Cargar en páginas (leads_master puede tener miles de registros)
    page_size = 1000
    offset = 0
    total = 0

    while True:
        resp = sb.table("leads_master").select(
            "id, nombre_negocio, telefono, email"
        ).range(offset, offset + page_size - 1).execute()

        batch = resp.data or []
        if not batch:
            break

        for row in batch:
            lead_id = row["id"]
            nombre = row.get("nombre_negocio", "") or ""
            tel = row.get("telefono", "") or ""
            em = row.get("email", "") or ""

            if tel:
                telefonos[tel.strip()] = {"id": lead_id, "nombre": nombre}
            if em:
                emails_dict[em.strip().lower()] = {"id": lead_id, "nombre": nombre}
            if nombre:
                nombres.append((nombre.lower().strip(), lead_id, nombre))

        total += len(batch)
        offset += page_size
        if len(batch) < page_size:
            break

    logger.info(
        f"Referencias cargadas: {total} leads_master "
        f"| {len(telefonos)} teléfonos | {len(emails_dict)} emails"
    )
    return {"telefonos": telefonos, "emails": emails_dict, "nombres": nombres}


# ── Cross-reference ───────────────────────────────────────────────────────────
def buscar_en_leads_master(
    nombre: str,
    telefono: str,
    email: str,
    refs: dict,
) -> tuple[bool, str | None, str | None]:
    """
    Busca si el lead existe en leads_master.
    Retorna: (encontrado, leads_master_id, tipo_match)
    """
    # 1. Match exacto por email
    if email and email in refs["emails"]:
        match = refs["emails"][email]
        return True, match["id"], "email"

    # 2. Match exacto por teléfono
    if telefono and telefono in refs["telefonos"]:
        match = refs["telefonos"][telefono]
        return True, match["id"], "telefono"

    # 3. Match por similitud de nombre (Jaccard >= 0.70)
    if nombre:
        nombre_lower = nombre.lower().strip()
        for (ref_nombre, ref_id, _) in refs["nombres"]:
            score = similitud_jaccard(nombre_lower, ref_nombre)
            if score >= 0.70:
                return True, ref_id, "nombre"

    return False, None, None


# ── Inserción en macrisa_leads ────────────────────────────────────────────────
def insertar_batch(sb, lote: list[dict], dry_run: bool = False) -> int:
    """Inserta un lote de registros en macrisa_leads."""
    if dry_run:
        return len(lote)

    try:
        resp = sb.table("macrisa_leads").insert(lote).execute()
        return len(resp.data or [])
    except Exception as e:
        # Mostrar el error real la primera vez para diagnóstico
        logger.error(f"Error en lote: {e}")
        # Intentar uno a uno para aislar qué fila falla
        insertados = 0
        _primer_error_mostrado = False
        for row in lote:
            try:
                sb.table("macrisa_leads").insert(row).execute()
                insertados += 1
            except Exception as e2:
                if not _primer_error_mostrado:
                    logger.error(f"Error fila '{row.get('nombre', '?')}': {e2}")
                    logger.error(f"Datos fila: { {k: v for k, v in row.items() if v is not None} }")
                    _primer_error_mostrado = True
        return insertados


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Carga base de datos Macrisa a Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin insertar")
    parser.add_argument("--limit", type=int, default=None, help="Limitar filas a procesar")
    parser.add_argument("--skip-crossref", action="store_true", help="No cruzar con leads_master")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("MACRISA — Carga de Base de Datos")
    print("=" * 60)
    if args.dry_run:
        print("⚠️  MODO DRY-RUN — No se insertará nada en Supabase")
    print()

    # Inicializar
    sb = get_supabase()
    df = cargar_excel(args.limit)

    # Cross-reference
    refs = {"telefonos": {}, "emails": {}, "nombres": []}
    if not args.skip_crossref:
        refs = cargar_referencias(sb)

    # Estadísticas
    stats = {
        "total": len(df),
        "insertados": 0,
        "ya_en_leads_master": 0,
        "con_email": 0,
        "con_telefono": 0,
        "con_website": 0,
        "errores": 0,
        "stars": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        "matches": {"email": 0, "telefono": 0, "nombre": 0},
    }

    lote_actual = []
    t_inicio = time.time()

    print(f"Procesando {len(df)} registros...\n")

    for idx, row in df.iterrows():
        # _v() segunda pasada: pandas puede re-introducir float('nan') en iterrows()
        nombre = _v(row.get("nombre")) or ""
        if not nombre:
            stats["errores"] += 1
            continue

        telefono = _v(row.get("telefono"))
        email = _v(row.get("email"), lower=True)
        website = _v(row.get("website"))

        if email:
            stats["con_email"] += 1
        if telefono:
            stats["con_telefono"] += 1
        if website:
            stats["con_website"] += 1

        # Cross-reference
        en_lm, lm_id, tipo_match = False, None, None
        if not args.skip_crossref:
            en_lm, lm_id, tipo_match = buscar_en_leads_master(
                nombre=nombre,
                telefono=telefono,
                email=email,
                refs=refs,
            )
            if en_lm:
                stats["ya_en_leads_master"] += 1
                if tipo_match in stats["matches"]:
                    stats["matches"][tipo_match] += 1

        # Calcular calidad
        stars = calcular_stars({
            "email": email,
            "telefono": telefono,
            "website": website,
            "confianza": row.get("confianza"),
        })
        stats["stars"][stars] = stats["stars"].get(stars, 0) + 1

        # Preparar registro — _v() garantiza que ningún float('nan') llegue a Supabase
        registro = {
            "id_original": _vi(row.get("id")),
            "nombre": nombre,
            "municipio": _v(row.get("municipio")),
            "estado": _v(row.get("estado")),
            "tipo": _v(row.get("tipo")),
            "ubicacion": _v(row.get("ubicacion")),
            "website": website,
            "telefono": telefono,
            "email": email,
            "email_status": "pendiente_validacion" if email else None,
            "facebook": _v(row.get("facebook")),
            "instagram": _v(row.get("instagram")),
            "linkedin": _v(row.get("linkedin")),
            "fuente": _v(row.get("fuente")),
            "confianza": _v(row.get("confianza")),
            "notas": _v(row.get("notas")),
            "en_leads_master": en_lm,
            "leads_master_id": lm_id,
            "tipo_match": tipo_match,
            "calidad_stars": stars,
            "anymail_procesado": False,
        }

        lote_actual.append(registro)

        # Insertar cuando el lote esté lleno
        if len(lote_actual) >= BATCH_SIZE:
            insertados = insertar_batch(sb, lote_actual, args.dry_run)
            stats["insertados"] += insertados
            lote_actual = []

            # Progreso
            pct = (idx + 1) / len(df) * 100
            elapsed = time.time() - t_inicio
            eta = elapsed / (idx + 1) * (len(df) - idx - 1)
            print(
                f"\r  {idx + 1:,}/{len(df):,} ({pct:.0f}%) "
                f"| Insertados: {stats['insertados']:,} "
                f"| En LM: {stats['ya_en_leads_master']:,} "
                f"| ETA: {eta:.0f}s   ",
                end="", flush=True,
            )

    # Último lote
    if lote_actual:
        insertados = insertar_batch(sb, lote_actual, args.dry_run)
        stats["insertados"] += insertados

    elapsed = time.time() - t_inicio

    # ── Reporte final ─────────────────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("RESULTADO FINAL — MACRISA")
    print("=" * 60)
    print(f"\nTOTAL PROCESADOS:    {stats['total']:>6,}")
    print(f"Insertados en DB:    {stats['insertados']:>6,}")
    print(f"Errores:             {stats['errores']:>6,}")
    print(f"\nCONTACTO:")
    print(f"  Con email:         {stats['con_email']:>6,} ({stats['con_email']*100//stats['total']}%)")
    print(f"  Con teléfono:      {stats['con_telefono']:>6,} ({stats['con_telefono']*100//stats['total']}%)")
    print(f"  Con website:       {stats['con_website']:>6,} ({stats['con_website']*100//stats['total']}%)")
    print(f"\nCROSS-REFERENCE con leads_master:")
    print(f"  Ya existían:       {stats['ya_en_leads_master']:>6,}")
    print(f"    → Match email:   {stats['matches']['email']:>6,}")
    print(f"    → Match tel:     {stats['matches']['telefono']:>6,}")
    print(f"    → Match nombre:  {stats['matches']['nombre']:>6,}")
    print(f"\nCALIDAD STARS:")
    for s in range(5, 0, -1):
        bar = "█" * (stats['stars'].get(s, 0) * 20 // max(stats['total'], 1))
        print(f"  {'★'*s + '☆'*(5-s)}  {stats['stars'].get(s,0):>5,}  {bar}")
    print(f"\nTIEMPO: {elapsed:.1f} segundos")
    print(f"\nPRÓXIMO PASO:")
    print(f"  Verifica emails con AnyMailFinder:")
    print(f"  venv\\Scripts\\python.exe -X utf8 verificar_macrisa.py")
    print("=" * 60)

    return stats


if __name__ == "__main__":
    main()
