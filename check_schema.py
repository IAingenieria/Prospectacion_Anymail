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
service_key = env.get('SUPABASE_SERVICE_KEY') or env.get('SUPABASE_SERVICE_ROLE_KEY') or env.get('SUPABASE_ANON_KEY')
headers = {'apikey': service_key, 'Authorization': 'Bearer ' + service_key}

for tabla in ['email_leads', 'social_leads']:
    r = httpx.get(env['SUPABASE_URL'] + f'/rest/v1/{tabla}',
                  headers=headers, params={'select': '*', 'limit': '1'})
    print(f"\n=== {tabla} (status {r.status_code}) ===")
    if r.status_code == 200:
        data = r.json()
        if data:
            print("Columnas:", list(data[0].keys()))
        else:
            # Get column list via empty response headers
            print("Tabla vacía — columnas no disponibles sin datos")
    else:
        print("Error:", r.text[:200])
