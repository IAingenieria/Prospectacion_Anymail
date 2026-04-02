import csv, os, json

folder = r'C:\Users\Dell\Downloads\Datos'

negocios = {}

for fname in os.listdir(folder):
    if not fname.startswith('export') or not fname.endswith('.csv'):
        continue
    with open(os.path.join(folder, fname), encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        nombre = r.get('Nombre', '').strip()
        if not nombre:
            continue
        if nombre not in negocios:
            negocios[nombre] = {
                'nombre': nombre,
                'telefono': r.get('Telefono', '').strip(),
                'email': r.get('Correo electrónico', '').strip(),
                'municipio': r.get('Municipio', '').strip(),
                'estado': r.get('Estado', '').strip(),
                'website': r.get('Website', '').strip(),
            }
        else:
            b = negocios[nombre]
            if not b['email']:
                b['email'] = r.get('Correo electrónico', '').strip()
            if not b['telefono']:
                b['telefono'] = r.get('Telefono', '').strip()
            if not b['municipio']:
                b['municipio'] = r.get('Municipio', '').strip()

print(f'Total negocios unicos en CSVs Baserow: {len(negocios)}')
con_email = sum(1 for v in negocios.values() if v['email'])
con_tel = sum(1 for v in negocios.values() if v['telefono'] and v['telefono'] != '0')
print(f'Con email: {con_email}')
print(f'Con telefono: {con_tel}')

with open(r'C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\temp_baserow_negocios.json', 'w', encoding='utf-8') as f:
    json.dump(list(negocios.keys()), f, ensure_ascii=False)

print()
print('Muestra de negocios:')
for n in list(negocios.keys())[:8]:
    b = negocios[n]
    tel = b['telefono'][:10] if b['telefono'] else '-'
    em = 'si' if b['email'] else 'no'
    print(f'  {n} | {b["municipio"]} | tel:{tel} | email:{em}')

# Cruzar contra Supabase — tomar muestra de 10 nombres
import urllib.request, urllib.parse
API_KEY = 'SUPABASE_SERVICE_ROLE_KEY_REDACTED'
BASE = 'https://pfurkonwbjfmxpfogdtr.supabase.co/rest/v1/leads_master'

sample_names = list(negocios.keys())[:20]
encontrados = 0
no_encontrados = []

for nombre in sample_names:
    encoded = urllib.parse.quote(nombre)
    url = f'{BASE}?nombre_negocio=eq.{encoded}&select=nombre_negocio,ciudad&limit=1'
    req = urllib.request.Request(url, headers={
        'apikey': API_KEY,
        'Authorization': f'Bearer {API_KEY}',
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            if data:
                encontrados += 1
            else:
                no_encontrados.append(nombre)
    except Exception as e:
        no_encontrados.append(f'{nombre} (err)')

print()
print(f'CRUCE SUPABASE (muestra de {len(sample_names)}):')
print(f'  Ya en Supabase: {encontrados}/{len(sample_names)}')
print(f'  NO en Supabase: {len(no_encontrados)}/{len(sample_names)}')
if no_encontrados:
    print('  Faltantes:')
    for n in no_encontrados[:5]:
        print(f'    - {n}')
