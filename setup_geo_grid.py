"""
setup_geo_grid.py
=================
Crea en Supabase:
  1. municipios_mx     — municipios con población y coordenadas
  2. search_zones      — cuadrícula concéntrica por municipio (centro → periferia)
  3. search_history    — historial de búsquedas por zona

Lógica de zonas: anillos concéntricos ordenados de mayor a menor densidad poblacional.
  Anillo 0 → centro del municipio (radio 1500m)
  Anillo 1 → 4 puntos cardinales a 3km (radio 1500m)
  Anillo 2 → 8 puntos (cada 45°) a 5km (radio 1800m)
  Anillo 3 → 8 puntos a 8km (radio 2200m)

Uso:
  python -X utf8 setup_geo_grid.py          # Crear tablas y poblar datos
  python -X utf8 setup_geo_grid.py --check  # Solo verificar estado actual
"""

import os, math, time, requests, argparse, sys
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL  = os.getenv("SUPABASE_URL",  "https://pfurkonwbjfmxpfogdtr.supabase.co")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY",
                os.getenv("SUPABASE_KEY",
                "SUPABASE_SERVICE_ROLE_KEY_REDACTED"))

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

# ─────────────────────────────────────────────
# DATOS: MUNICIPIOS PRIORITARIOS
# Orden: de más a menos población (búsquedas futuras empiezan aquí)
# ─────────────────────────────────────────────
MUNICIPIOS = [
    # ── Nuevo León ──────────────────────────────────────────────────────
    {"clave_estado": "19", "clave_municipio": "039", "nombre": "Monterrey",
     "estado": "Nuevo León", "lat": 25.6866, "lng": -100.3161,
     "poblacion": 1135512, "area_km2": 325.0},
    {"clave_estado": "19", "clave_municipio": "018", "nombre": "Apodaca",
     "estado": "Nuevo León", "lat": 25.7810, "lng": -100.1878,
     "poblacion": 523370, "area_km2": 106.0},
    {"clave_estado": "19", "clave_municipio": "026", "nombre": "Guadalupe",
     "estado": "Nuevo León", "lat": 25.6752, "lng": -100.2592,
     "poblacion": 678006, "area_km2": 130.0},
    {"clave_estado": "19", "clave_municipio": "046", "nombre": "San Nicolás de los Garza",
     "estado": "Nuevo León", "lat": 25.7480, "lng": -100.3011,
     "poblacion": 430143, "area_km2": 58.0},
    {"clave_estado": "19", "clave_municipio": "021", "nombre": "Escobedo",
     "estado": "Nuevo León", "lat": 25.7967, "lng": -100.3344,
     "poblacion": 357937, "area_km2": 148.0},
    {"clave_estado": "19", "clave_municipio": "048", "nombre": "Santa Catarina",
     "estado": "Nuevo León", "lat": 25.6726, "lng": -100.4580,
     "poblacion": 268955, "area_km2": 906.0},
    {"clave_estado": "19", "clave_municipio": "031", "nombre": "Juárez",
     "estado": "Nuevo León", "lat": 25.6533, "lng": -100.1094,
     "poblacion": 256970, "area_km2": 184.0},
    {"clave_estado": "19", "clave_municipio": "019", "nombre": "García",
     "estado": "Nuevo León", "lat": 25.8138, "lng": -100.5874,
     "poblacion": 143531, "area_km2": 985.0},
    {"clave_estado": "19", "clave_municipio": "045", "nombre": "San Pedro Garza García",
     "estado": "Nuevo León", "lat": 25.6574, "lng": -100.4031,
     "poblacion": 122009, "area_km2": 72.0},
    # ── Coahuila ─────────────────────────────────────────────────────────
    {"clave_estado": "05", "clave_municipio": "030", "nombre": "Saltillo",
     "estado": "Coahuila de Zaragoza", "lat": 25.4260, "lng": -100.9996,
     "poblacion": 823128, "area_km2": 1832.0},
    {"clave_estado": "05", "clave_municipio": "035", "nombre": "Torreón",
     "estado": "Coahuila de Zaragoza", "lat": 25.5428, "lng": -103.4068,
     "poblacion": 679288, "area_km2": 918.0},
    {"clave_estado": "05", "clave_municipio": "021", "nombre": "Monclova",
     "estado": "Coahuila de Zaragoza", "lat": 26.9056, "lng": -101.4219,
     "poblacion": 231675, "area_km2": 1961.0},
    {"clave_estado": "05", "clave_municipio": "028", "nombre": "Piedras Negras",
     "estado": "Coahuila de Zaragoza", "lat": 28.7036, "lng": -100.5228,
     "poblacion": 163595, "area_km2": 1748.0},
    {"clave_estado": "05", "clave_municipio": "002", "nombre": "Acuña",
     "estado": "Coahuila de Zaragoza", "lat": 29.3170, "lng": -100.9285,
     "poblacion": 146235, "area_km2": 6772.0},
    # ── Tamaulipas ───────────────────────────────────────────────────────
    {"clave_estado": "28", "clave_municipio": "032", "nombre": "Reynosa",
     "estado": "Tamaulipas", "lat": 26.0924, "lng": -98.2794,
     "poblacion": 704767, "area_km2": 3156.0},
    {"clave_estado": "28", "clave_municipio": "009", "nombre": "Matamoros",
     "estado": "Tamaulipas", "lat": 25.8694, "lng": -97.5046,
     "poblacion": 520367, "area_km2": 4660.0},
    {"clave_estado": "28", "clave_municipio": "041", "nombre": "Nuevo Laredo",
     "estado": "Tamaulipas", "lat": 27.4774, "lng": -99.5167,
     "poblacion": 425058, "area_km2": 1339.0},
    {"clave_estado": "28", "clave_municipio": "038", "nombre": "Victoria",
     "estado": "Tamaulipas", "lat": 23.7369, "lng": -99.1411,
     "poblacion": 341910, "area_km2": 1527.0},
    {"clave_estado": "28", "clave_municipio": "039", "nombre": "Tampico",
     "estado": "Tamaulipas", "lat": 22.2331, "lng": -97.8616,
     "poblacion": 310983, "area_km2": 109.0},
    # ── Chihuahua ────────────────────────────────────────────────────────
    {"clave_estado": "08", "clave_municipio": "019", "nombre": "Juárez",
     "estado": "Chihuahua", "lat": 31.6904, "lng": -106.4245,
     "poblacion": 1512354, "area_km2": 3555.0},
    {"clave_estado": "08", "clave_municipio": "037", "nombre": "Chihuahua",
     "estado": "Chihuahua", "lat": 28.6320, "lng": -106.0691,
     "poblacion": 878062, "area_km2": 9376.0},
    # ── Sonora ───────────────────────────────────────────────────────────
    {"clave_estado": "26", "clave_municipio": "030", "nombre": "Hermosillo",
     "estado": "Sonora", "lat": 29.0729, "lng": -110.9559,
     "poblacion": 884273, "area_km2": 14893.0},
    # ── Zacatecas ────────────────────────────────────────────────────────
    {"clave_estado": "32", "clave_municipio": "056", "nombre": "Zacatecas",
     "estado": "Zacatecas", "lat": 22.7709, "lng": -102.5832,
     "poblacion": 138176, "area_km2": 399.0},
    {"clave_estado": "32", "clave_municipio": "017", "nombre": "Fresnillo",
     "estado": "Zacatecas", "lat": 23.1703, "lng": -102.8731,
     "poblacion": 225275, "area_km2": 3461.0},
    # ── San Luis Potosí ──────────────────────────────────────────────────
    {"clave_estado": "24", "clave_municipio": "028", "nombre": "San Luis Potosí",
     "estado": "San Luis Potosí", "lat": 22.1565, "lng": -100.9855,
     "poblacion": 824229, "area_km2": 1443.0},
]

# ─────────────────────────────────────────────
# GENERADOR DE ANILLOS CONCÉNTRICOS
# ─────────────────────────────────────────────
# 1° de latitud ≈ 111 km
KM_PER_LAT = 111.0

def km_to_lat(km): return km / KM_PER_LAT
def km_to_lng(km, lat): return km / (KM_PER_LAT * math.cos(math.radians(lat)))

ANILLOS = [
    # (distancia_km, radio_metros, sectores)
    (0,  1500, ["Centro"]),                                            # Anillo 0
    (3,  1500, ["N", "E", "S", "W"]),                                  # Anillo 1
    (5,  1800, ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),         # Anillo 2
    (8,  2200, ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),         # Anillo 3
    (13, 2800, ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),         # Anillo 4
]

SECTOR_ANGULOS = {
    "N": 0, "NE": 45, "E": 90, "SE": 135,
    "S": 180, "SW": 225, "W": 270, "NW": 315,
    "Centro": 0
}

def generar_zonas(municipio_id: int, lat_centro: float, lng_centro: float):
    """Genera la lista de zonas concéntricas para un municipio."""
    zonas = []
    orden = 1
    for anillo_idx, (dist_km, radio_m, sectores) in enumerate(ANILLOS):
        for sector in sectores:
            if dist_km == 0:
                z_lat, z_lng = lat_centro, lng_centro
            else:
                angulo_rad = math.radians(SECTOR_ANGULOS[sector])
                z_lat = lat_centro + km_to_lat(dist_km) * math.cos(angulo_rad)
                z_lng = lng_centro + km_to_lng(dist_km, lat_centro) * math.sin(angulo_rad)

            zonas.append({
                "municipio_id": municipio_id,
                "zona_nombre": f"{sector}-{anillo_idx}" if dist_km > 0 else "Centro",
                "lat": round(z_lat, 6),
                "lng": round(z_lng, 6),
                "radio_metros": radio_m,
                "anillo": anillo_idx,
                "sector": sector,
                "orden_prioridad": orden,
            })
            orden += 1
    return zonas

# ─────────────────────────────────────────────
# SQL PARA CREAR TABLAS (ejecutar en Supabase)
# ─────────────────────────────────────────────
SQL_TABLAS = """
-- ================================================
-- 1. MUNICIPIOS MX
-- ================================================
CREATE TABLE IF NOT EXISTS municipios_mx (
    id                 SERIAL PRIMARY KEY,
    clave_inegi        VARCHAR(5) UNIQUE,
    nombre             VARCHAR(100) NOT NULL,
    estado             VARCHAR(100) NOT NULL,
    clave_estado       VARCHAR(2)  NOT NULL,
    clave_municipio    VARCHAR(3)  NOT NULL,
    lat_centro         DECIMAL(9,6) NOT NULL,
    lng_centro         DECIMAL(9,6) NOT NULL,
    poblacion          INTEGER,
    area_km2           DECIMAL(10,2),
    densidad_hab_km2   DECIMAL(10,2),
    activo             BOOLEAN DEFAULT TRUE,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================
-- 2. SEARCH ZONES (cuadrícula concéntrica)
-- ================================================
CREATE TABLE IF NOT EXISTS search_zones (
    id                     SERIAL PRIMARY KEY,
    municipio_id           INTEGER REFERENCES municipios_mx(id) ON DELETE CASCADE,
    zona_nombre            VARCHAR(50) NOT NULL,
    lat                    DECIMAL(9,6) NOT NULL,
    lng                    DECIMAL(9,6) NOT NULL,
    radio_metros           INTEGER NOT NULL DEFAULT 1500,
    anillo                 INTEGER NOT NULL DEFAULT 0,
    sector                 VARCHAR(10),
    orden_prioridad        INTEGER NOT NULL,
    searches_realizadas    INTEGER DEFAULT 0,
    ultima_busqueda_at     TIMESTAMPTZ,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_search_zones_municipio ON search_zones(municipio_id);
CREATE INDEX IF NOT EXISTS idx_search_zones_orden ON search_zones(municipio_id, orden_prioridad);

-- ================================================
-- 3. SEARCH HISTORY (historial por zona)
-- ================================================
CREATE TABLE IF NOT EXISTS search_history (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id         UUID,
    termino_busqueda   VARCHAR(200) NOT NULL,
    municipio_id       INTEGER REFERENCES municipios_mx(id),
    zone_id            INTEGER REFERENCES search_zones(id),
    apify_run_id       VARCHAR(50),
    denue_consultado   BOOLEAN DEFAULT FALSE,
    leads_apify        INTEGER DEFAULT 0,
    leads_denue        INTEGER DEFAULT 0,
    leads_nuevos       INTEGER DEFAULT 0,
    duplicados         INTEGER DEFAULT 0,
    costo_apify_usd    DECIMAL(10,4),
    fecha              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_search_history_termino ON search_history(termino_busqueda, municipio_id);
"""

# ─────────────────────────────────────────────
# HELPERS SUPABASE REST
# ─────────────────────────────────────────────
def sb_insert(tabla: str, datos: list[dict], upsert_on: str = None) -> int:
    """Inserta registros en Supabase. Retorna cantidad insertada."""
    if not datos:
        return 0
    headers = dict(HEADERS)
    if upsert_on:
        headers["Prefer"] = f"resolution=merge-duplicates,return=minimal"
        headers["on_conflict"] = upsert_on

    # Insertar en lotes de 500
    total = 0
    for i in range(0, len(datos), 500):
        lote = datos[i:i+500]
        url = f"{SUPABASE_URL}/rest/v1/{tabla}"
        if upsert_on:
            url += f"?on_conflict={upsert_on}"
        r = requests.post(url, json=lote, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            total += len(lote)
        else:
            print(f"  ⚠️  Error inserting {tabla}: {r.status_code} — {r.text[:200]}")
    return total

def sb_get(tabla: str, params: str = "") -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{tabla}?{params}",
        headers={**HEADERS, "Prefer": "count=exact"},
        timeout=30
    )
    return r.json() if r.ok else []

def sb_count(tabla: str, params: str = "") -> int:
    r = requests.head(
        f"{SUPABASE_URL}/rest/v1/{tabla}?{params}",
        headers={**HEADERS, "Prefer": "count=exact"},
        timeout=30
    )
    cr = r.headers.get("content-range", "0/0")
    try:
        return int(cr.split("/")[1])
    except:
        return 0

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Solo verificar estado")
    parser.add_argument("--sql",   action="store_true", help="Imprimir SQL para crear tablas")
    args = parser.parse_args()

    if args.sql:
        print(SQL_TABLAS)
        return

    if args.check:
        print("📊 Estado actual de las tablas geo:")
        for tabla in ["municipios_mx", "search_zones", "search_history"]:
            n = sb_count(tabla)
            print(f"  {tabla:20s}: {n} registros")
        return

    print("🏗️  Configurando base de datos geográfica...")
    print()
    print("⚠️  PASO 1: Crea las tablas en Supabase SQL Editor:")
    print("   Ve a: https://supabase.com/dashboard/project/pfurkonwbjfmxpfogdtr/sql")
    print()
    print("   Ejecuta este SQL:")
    print("─" * 60)
    print(SQL_TABLAS)
    print("─" * 60)

    resp = input("\n¿Ya ejecutaste el SQL en Supabase? (s/n): ").strip().lower()
    if resp != "s":
        print("Abre Supabase SQL Editor, pega el SQL de arriba y presiona Run.")
        print("Luego vuelve a ejecutar este script.")
        return

    print()
    print("📍 PASO 2: Insertando municipios...")

    municipios_data = []
    for m in MUNICIPIOS:
        densidad = round(m["poblacion"] / m["area_km2"], 2) if m["area_km2"] else 0
        municipios_data.append({
            "clave_inegi":      m["clave_estado"] + m["clave_municipio"],
            "nombre":           m["nombre"],
            "estado":           m["estado"],
            "clave_estado":     m["clave_estado"],
            "clave_municipio":  m["clave_municipio"],
            "lat_centro":       m["lat"],
            "lng_centro":       m["lng"],
            "poblacion":        m["poblacion"],
            "area_km2":         m["area_km2"],
            "densidad_hab_km2": densidad,
        })

    n = sb_insert("municipios_mx", municipios_data, upsert_on="clave_inegi")
    print(f"  ✅ {n} municipios insertados")

    # Obtener IDs asignados
    rows = sb_get("municipios_mx", "select=id,clave_inegi,nombre,lat_centro,lng_centro&order=poblacion.desc.nullslast&limit=100")
    id_map = {r["clave_inegi"]: r for r in rows}

    print()
    print("🗺️  PASO 3: Generando zonas concéntricas...")

    total_zonas = 0
    for m in MUNICIPIOS:
        clave = m["clave_estado"] + m["clave_municipio"]
        if clave not in id_map:
            print(f"  ⚠️  No encontré ID para {m['nombre']}")
            continue
        mun_row = id_map[clave]
        zonas = generar_zonas(mun_row["id"], mun_row["lat_centro"], mun_row["lng_centro"])
        n = sb_insert("search_zones", zonas)
        total_zonas += n
        print(f"  📍 {m['nombre']:30s} → {n} zonas")
        time.sleep(0.2)

    print()
    print("═" * 50)
    print(f"✅ COMPLETADO")
    print(f"   Municipios : {len(MUNICIPIOS)}")
    print(f"   Zonas      : {total_zonas}")
    print(f"   Cobertura  : {len(MUNICIPIOS)} ciudades × {total_zonas//len(MUNICIPIOS)} zonas c/u")
    print()
    print("El bot ahora puede buscar en orden de densidad poblacional.")
    print("Ejecuta: python -X utf8 setup_geo_grid.py --check  para verificar")

if __name__ == "__main__":
    main()
