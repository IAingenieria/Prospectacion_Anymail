import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

env = {}
with open('.env', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

import httpx

# Use SERVICE key for full read access
service_key = env.get('SUPABASE_SERVICE_KEY') or env.get('SUPABASE_SERVICE_ROLE_KEY') or env.get('SUPABASE_ANON_KEY')
headers = {
    'apikey': service_key,
    'Authorization': 'Bearer ' + service_key,
}

# Check social_leads
r = httpx.get(env['SUPABASE_URL'] + '/rest/v1/social_leads',
              headers=headers,
              params={'select': '*', 'order': 'created_at.desc', 'limit': '15'})

print("HTTP status:", r.status_code)
if r.status_code != 200:
    print("Error:", r.text[:300])
    sys.exit(1)

data = r.json()
print("Total rows (last 15):", len(data))

if not data:
    print("Tabla vacía o sin acceso")
    sys.exit(0)

# Show column names
print("Columnas:", list(data[0].keys()))
print()

# Find phone-related columns
phone_cols = [k for k in data[0].keys() if 'tel' in k.lower() or 'phone' in k.lower() or 'cel' in k.lower()]
name_cols = [k for k in data[0].keys() if 'nombre' in k.lower() or 'name' in k.lower() or 'biz' in k.lower()]
city_cols = [k for k in data[0].keys() if 'ciudad' in k.lower() or 'city' in k.lower()]

print(f"Columna telefono detectada: {phone_cols}")
print(f"Columna nombre detectada: {name_cols}")
print()

con_tel = 0
sin_tel = 0
for row in data:
    nombre = str(row.get(name_cols[0], '') if name_cols else '')[:35]
    tel = None
    for pc in phone_cols:
        if row.get(pc):
            tel = row[pc]
            break
    ciudad = str(row.get(city_cols[0], '') if city_cols else '')[:15]
    if tel:
        con_tel += 1
    else:
        sin_tel += 1
        tel = 'SIN TELEFONO'
    print(nombre.ljust(35), "|", str(tel).ljust(20), "|", ciudad)

print()
print(f"Con telefono: {con_tel} / {len(data)} | Sin telefono: {sin_tel}")
