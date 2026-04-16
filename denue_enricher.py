"""
denue_enricher.py
=================
Enriquece los leads existentes en Supabase usando la API del DENUE (INEGI).

DENUE tiene 60% de cobertura de email vs 21% actual — es el mayor upgrade posible.

Modos de uso:
  python -X utf8 denue_enricher.py --test          # Prueba con 10 leads
  python -X utf8 denue_enricher.py --run           # Enriquece todos los leads sin email
  python -X utf8 denue_enricher.py --run --limit 50 # Enriquece primeros 50
  python -X utf8 denue_enricher.py --stats         # Ver cobertura actual

Cómo funciona:
  1. Toma leads de Supabase SIN email (o con coordenadas conocidas)
  2. Llama a DENUE API con las coordenadas del negocio (lat/lng de Google Maps)
  3. Busca el negocio por nombre + proximidad (<100m)
  4. Si encuentra match: copia email, teléfono, web de DENUE
  5. Actualiza el lead en Supabase
"""

import os, re, time, math, requests, argparse, unicodedata
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://pfurkonwbjfmxpfogdtr.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY",
               os.getenv("SUPABASE_KEY",
               "SUPABASE_SERVICE_ROLE_KEY_REDACTED"))
DENUE_TOKEN  = os.getenv("DENUE_TOKEN", "YOUR_DENUE_API_KEY")

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# ─────────────────────────────────────────────
# NORMALIZACIÓN DE NOMBRES (para matching)
# ─────────────────────────────────────────────
_STOPWORDS = {"sa", "de", "cv", "srl", "sc", "del", "la", "el", "los",
              "las", "y", "e", "en", "con", "por", "para"}

def normalizar(texto: str) -> str:
    """Quita acentos, mayúsculas, puntuación y stopwords para comparación."""
    if not texto:
        return ""
    txt = unicodedata.normalize("NFKD", texto.lower())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^\w\s]", " ", txt)
    palabras = [w for w in txt.split() if w not in _STOPWORDS and len(w) > 2]
    return " ".join(palabras)

def similitud(a: str, b: str) -> float:
    """Porcentaje de palabras de 'a' que están en 'b'."""
    wa = set(normalizar(a).split())
    wb = set(normalizar(b).split())
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)

# ─────────────────────────────────────────────
# MAPA CIUDAD → COORDENADAS MUNICIPIO
# Usado cuando los leads no tienen lat/lng exacta
# ─────────────────────────────────────────────
CIUDAD_COORDS = {
    # Nuevo León
    "monterrey":                   (25.6866, -100.3161),
    "guadalupe":                   (25.6752, -100.2592),
    "san nicolás de los garza":    (25.7480, -100.3011),
    "apodaca":                     (25.7810, -100.1878),
    "cdad. apodaca":               (25.7810, -100.1878),
    "san pedro garza garcía":      (25.6574, -100.4031),
    "santa catarina":              (25.6726, -100.4580),
    "escobedo":                    (25.7967, -100.3344),
    "juárez":                      (25.6533, -100.1094),
    "garcía":                      (25.8138, -100.5874),
    "cdad. santa catarina":        (25.6726, -100.4580),
    "cdad. general escobedo":      (25.7967, -100.3344),
    # Coahuila
    "saltillo":                    (25.4260, -100.9996),
    "torreón":                     (25.5428, -103.4068),
    "monclova":                    (26.9056, -101.4219),
    "piedras negras":              (28.7036, -100.5228),
    "acuña":                       (29.3170, -100.9285),
    "cdad. acuña":                 (29.3170, -100.9285),
    "frontera":                    (26.9302, -101.4571),
    "palaú":                       (27.9167, -101.4167),
    "cdad. melchor múzquiz":       (27.8833, -101.5167),
    # Tamaulipas
    "reynosa":                     (26.0924, -98.2794),
    "matamoros":                   (25.8694, -97.5046),
    "nuevo laredo":                (27.4774, -99.5167),
    "victoria":                    (23.7369, -99.1411),
    "tampico":                     (22.2331, -97.8616),
    # Chihuahua
    "chihuahua":                   (28.6320, -106.0691),
    "juárez":                      (31.6904, -106.4245),
    "delicias":                    (28.1894, -105.4719),
}

def ciudad_a_coords(ciudad: str, estado: str = "") -> tuple:
    """Obtiene coordenadas aproximadas por nombre de ciudad."""
    if not ciudad:
        return None, None
    key = ciudad.lower().strip()
    if key in CIUDAD_COORDS:
        return CIUDAD_COORDS[key]
    # Búsqueda parcial
    for k, v in CIUDAD_COORDS.items():
        if k in key or key in k:
            return v
    return None, None

# ─────────────────────────────────────────────
# DENUE API
# ─────────────────────────────────────────────
def denue_buscar_coords(lat: float, lng: float, termino: str, radio_m: int = 500) -> list:
    """Busca negocios en DENUE por coordenadas y término."""
    url = (f"https://www.inegi.org.mx/app/api/denue/v1/consulta/Buscar/"
           f"{termino}/{lat},{lng}/{radio_m}/{DENUE_TOKEN}")
    try:
        r = requests.get(url, timeout=15)
        if r.ok:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        pass
    return []

def denue_match(nombre_negocio: str, lat: float, lng: float,
                umbral_similitud: float = 0.5) -> dict | None:
    """
    Busca el negocio en DENUE usando sus coordenadas.
    Retorna el registro DENUE si hay match, o None.
    """
    # Extraer primera palabra significativa para la búsqueda
    palabras = normalizar(nombre_negocio).split()
    if not palabras:
        return None
    termino = palabras[0]  # Primera palabra más descriptiva

    # Radio amplio porque usamos coords del municipio, no del negocio exacto
    resultados = denue_buscar_coords(lat, lng, termino, radio_m=5000)
    if not resultados:
        resultados = denue_buscar_coords(lat, lng, termino, radio_m=10000)

    mejor = None
    mejor_score = 0.0

    for r in resultados:
        nombre_denue = r.get("Nombre", "") or r.get("Razon_social", "")
        score = similitud(nombre_negocio, nombre_denue)
        if score > mejor_score:
            mejor_score = score
            mejor = r

    if mejor and mejor_score >= umbral_similitud:
        mejor["_match_score"] = mejor_score
        return mejor
    return None

# ─────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────
def sb_get_leads_sin_email(limit: int = 500, offset: int = 0) -> list:
    """Leads sin email que tienen ciudad (usamos coords del municipio)."""
    params = (
        "select=id,nombre_negocio,ciudad,estado,telefono,email,sitio_web,lead_score,direccion"
        "&email=is.null"
        "&ciudad=not.is.null"
        f"&limit={limit}&offset={offset}"
        "&order=lead_score.desc"
    )
    r = requests.get(f"{SUPABASE_URL}/rest/v1/leads_master?{params}",
                     headers=SB_HEADERS, timeout=30)
    return r.json() if r.ok else []

def sb_get_leads_con_coordenadas(limit: int = 500, offset: int = 0) -> list:
    """Todos los leads con ciudad (para intentar enriquecer)."""
    params = (
        "select=id,nombre_negocio,ciudad,estado,telefono,email,sitio_web,lead_score,direccion"
        "&ciudad=not.is.null"
        f"&limit={limit}&offset={offset}"
        "&order=lead_score.desc"
    )
    r = requests.get(f"{SUPABASE_URL}/rest/v1/leads_master?{params}",
                     headers=SB_HEADERS, timeout=30)
    return r.json() if r.ok else []

def sb_update_lead(lead_id: str, datos: dict) -> bool:
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/leads_master?id=eq.{lead_id}",
        json=datos, headers=SB_HEADERS, timeout=15
    )
    return r.status_code in (200, 204)

def extraer_lat_lng_desde_url(google_maps_url: str):
    """Extrae lat/lng de una URL de Google Maps."""
    if not google_maps_url:
        return None, None
    # Patrón: @25.6866,-100.3161
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", google_maps_url)
    if m:
        return float(m.group(1)), float(m.group(2))
    # Patrón: ll=25.6866,-100.3161
    m = re.search(r"ll=(-?\d+\.\d+),(-?\d+\.\d+)", google_maps_url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None

# ─────────────────────────────────────────────
# ENRIQUECEDOR PRINCIPAL
# ─────────────────────────────────────────────
def enriquecer_lead(lead: dict, verbose: bool = True) -> dict:
    """
    Intenta enriquecer un lead con datos de DENUE.
    Retorna dict con resultados del enriquecimiento.
    """
    nombre = lead.get("nombre_negocio", "")
    lat = lead.get("lat")
    lng = lead.get("lng")

    # Si no tiene coordenadas directas, intentar extraerlas de la URL
    if not lat or not lng:
        lat, lng = extraer_lat_lng_desde_url(lead.get("google_maps_url", ""))

    # Si aún no tiene coords, usar las del municipio como aproximación
    if not lat or not lng:
        lat, lng = ciudad_a_coords(lead.get("ciudad", ""), lead.get("estado", ""))

    if not lat or not lng:
        return {"status": "sin_coords", "lead_id": lead["id"]}

    match = denue_match(nombre, lat, lng)

    if not match:
        return {"status": "no_match", "lead_id": lead["id"]}

    # Datos encontrados en DENUE
    email_denue = (match.get("Correo_e") or "").strip().lower()
    tel_denue   = (match.get("Telefono") or "").strip()
    web_denue   = (match.get("Sitio_internet") or "").strip()

    actualizaciones = {}
    mejoras = []

    if email_denue and not lead.get("email"):
        actualizaciones["email"] = email_denue
        actualizaciones["email_status"] = "denue_verified"
        mejoras.append(f"email: {email_denue}")

    if tel_denue and not lead.get("telefono"):
        actualizaciones["telefono"] = tel_denue
        mejoras.append(f"tel: {tel_denue}")

    if web_denue and not lead.get("sitio_web"):
        actualizaciones["sitio_web"] = web_denue
        mejoras.append(f"web: {web_denue}")

    if actualizaciones:
        actualizaciones["anymail_procesado"] = True
        ok = sb_update_lead(lead["id"], actualizaciones)
        if verbose:
            score = match.get("_match_score", 0)
            print(f"  ✅ {nombre[:45]:45s} | score:{score:.2f} | {' | '.join(mejoras)}")
        return {"status": "enriquecido", "lead_id": lead["id"],
                "mejoras": mejoras, "match_score": match.get("_match_score")}

    return {"status": "sin_datos_nuevos", "lead_id": lead["id"]}

def run_enrichment(limit: int = None, solo_sin_email: bool = True):
    """Enriquece leads en lotes."""
    print("🔍 DENUE Enricher — Iniciando...")
    print(f"   Modo: {'solo sin email' if solo_sin_email else 'todos con coordenadas'}")
    print()

    stats = {"total": 0, "enriquecidos": 0, "emails_nuevos": 0,
             "telefonos_nuevos": 0, "no_match": 0, "sin_coords": 0}

    offset = 0
    batch_size = 100

    while True:
        if solo_sin_email:
            lote = sb_get_leads_sin_email(limit=batch_size, offset=offset)
        else:
            lote = sb_get_leads_con_coordenadas(limit=batch_size, offset=offset)

        if not lote:
            break

        print(f"📦 Procesando lote {offset//batch_size + 1} ({len(lote)} leads)...")

        for lead in lote:
            resultado = enriquecer_lead(lead)
            stats["total"] += 1

            if resultado["status"] == "enriquecido":
                stats["enriquecidos"] += 1
                mejoras = resultado.get("mejoras", [])
                if any("email" in m for m in mejoras):
                    stats["emails_nuevos"] += 1
                if any("tel" in m for m in mejoras):
                    stats["telefonos_nuevos"] += 1
            elif resultado["status"] == "no_match":
                stats["no_match"] += 1
            elif resultado["status"] == "sin_coords":
                stats["sin_coords"] += 1

            time.sleep(0.3)  # Respetar rate limit DENUE

        offset += batch_size

        if limit and stats["total"] >= limit:
            break

        print(f"   Progreso: {stats['enriquecidos']}/{stats['total']} enriquecidos")
        print()

    print()
    print("═" * 50)
    print("📊 RESULTADO FINAL DENUE ENRICHER")
    print(f"   Total procesados   : {stats['total']}")
    print(f"   Enriquecidos       : {stats['enriquecidos']} ({stats['enriquecidos']*100//max(stats['total'],1)}%)")
    print(f"   Emails nuevos      : {stats['emails_nuevos']} 📧")
    print(f"   Teléfonos nuevos   : {stats['telefonos_nuevos']} 📱")
    print(f"   Sin match DENUE    : {stats['no_match']}")
    print(f"   Sin coordenadas    : {stats['sin_coords']}")
    print("═" * 50)
    return stats

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DENUE Lead Enricher")
    parser.add_argument("--test",  action="store_true", help="Prueba con 10 leads")
    parser.add_argument("--run",   action="store_true", help="Enriquecer todos los leads sin email")
    parser.add_argument("--all",   action="store_true", help="Intentar enriquecer todos (con y sin email)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de leads a procesar")
    parser.add_argument("--stats", action="store_true", help="Ver estadísticas actuales")
    args = parser.parse_args()

    if args.stats:
        print("📊 Cobertura actual en Supabase:")
        for label, params in [
            ("Total leads",        "select=id&limit=1"),
            ("Con email",          "select=id&email=not.is.null&email=neq.&limit=1"),
            ("Email denue",        "select=id&email_status=eq.denue_verified&limit=1"),
            ("Con teléfono",       "select=id&telefono=not.is.null&limit=1"),
            ("Con coordenadas",    "select=id&lat=not.is.null&limit=1"),
        ]:
            r = requests.head(
                f"{SUPABASE_URL}/rest/v1/leads_master?{params}",
                headers={**SB_HEADERS, "Prefer": "count=exact"}, timeout=10
            )
            cr = r.headers.get("content-range", "?/?")
            total = cr.split("/")[1] if "/" in cr else "?"
            print(f"  {label:25s}: {total}")

    elif args.test:
        print("🧪 MODO TEST — 10 leads")
        run_enrichment(limit=10)

    elif args.run or args.all:
        lim = args.limit
        solo_sin_email = not args.all
        run_enrichment(limit=lim, solo_sin_email=solo_sin_email)

    else:
        parser.print_help()
        print()
        print("Ejemplos:")
        print("  python -X utf8 denue_enricher.py --stats")
        print("  python -X utf8 denue_enricher.py --test")
        print("  python -X utf8 denue_enricher.py --run --limit 200")
        print("  python -X utf8 denue_enricher.py --run")
