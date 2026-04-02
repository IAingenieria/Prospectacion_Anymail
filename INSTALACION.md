# LeadForge - Instalacion y Uso Completo

## Requisitos
- Python 3.11+
- Docker Desktop (opcional)
- Cuentas: Supabase, Apify, Anymail Finder, Anthropic Claude

---

## Paso 1: Base de Datos (Supabase)
1. Crear cuenta en https://supabase.com
2. Crear proyecto nuevo
3. SQL Editor > New Query > pegar supabase_schema.sql > Run
4. Anotar: Project URL y Service Role Key (Settings > API)

## Paso 2: Variables de Entorno
```
cp .env.example .env
```
Variables requeridas: CLIENTE_ID, SUPABASE_URL, SUPABASE_SERVICE_KEY,
APIFY_TOKEN, ANYMAIL_API_KEY, ANTHROPIC_API_KEY, INSTANTLY_API_KEY

## Paso 3: Instalar Dependencias
```
python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Paso 4: Verificar
```
python run.py --check
```

---

## INICIAR EL SISTEMA

### Opcion A: Un solo comando (recomendado)
```
python start_all.py
```
Inicia: Dashboard (5000) + Monitor Telegram + Webhook (8001)

### Opcion B: Servicios separados
```
# Terminal 1
python start_dashboard.py

# Terminal 2
python start_monitor.py
```

### Opcion C: Docker
```
docker-compose up -d
docker-compose logs -f
```

---

## CREAR CAMPANAS

### Wizard Web (mas facil)
1. Abrir http://localhost:5000/wizard
2. Describir producto -> Claude genera categorias con IA
3. Seleccionar categorias -> ver costo estimado
4. Configurar vendedor y Instantly.ai -> Lanzar

### Archivo YAML (para repetir)
```
cp campaign_configs/ejemplo_campana.yaml campaign_configs/mi_campana.yaml
python start_campaign.py --config campaign_configs/mi_campana.yaml
python start_campaign.py --config campaign_configs/mi_campana.yaml --dry-run
python start_campaign.py --config campaign_configs/mi_campana.yaml --solo-inyectar
python start_campaign.py --status
```

### CLI directo (pruebas rapidas)
```
python run.py --categoria "taller mecanico" --ciudad "Monterrey" --estado "Nuevo Leon"
python run.py --categoria "ferreteria" --sinonimos "distribuidora de materiales" --ciudad "CDMX" --perfil alta_densidad
```

---

## AUTOSTART MAC MINI
```
bash mac_autostart/instalar_autostart.sh
```
Instala como LaunchAgent: arranca con el sistema automaticamente.
```
tail -f logs/stdout.log            # Ver logs
launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist  # Detener
```

---

## DASHBOARD WEB
- localhost:5000           Dashboard principal (KPIs, cuentas, alertas)
- localhost:5000/wizard    Campaign Wizard con IA de Claude
- localhost:5000/cuentas   Cuentas Instantly.ai + bounce/spam rates
- localhost:5000/reportes  Costos, ROI, desglose por categoria
- localhost:5000/docs      API REST documentada automaticamente

---

## BOT DE TELEGRAM
/status     Estado del sistema
/leads      Ultimos leads
/respuestas Respuestas pendientes
/creditos   Saldo Anymail Finder
/reporte    Reporte completo
/ayuda      Todos los comandos

---

## PERFILES APIFY
- alta_densidad:  ferreterias, farmacias, salones (50/termino)
- media_densidad: talleres, clinicas, agencias (30/termino)
- baja_densidad:  industria, contratistas, CNC (100/termino)

---

## METAS DE COSTO
- Costo por lead: menos $0.10 USD (ver en Reportes)
- Bounce rate: menos 3% por cuenta
- Spam rate: menos 0.1% por cuenta
- Respuesta emails: 2-4% esperado

---

## ESTRUCTURA DEL PROYECTO
```
Claude Leads Instantly/
  start_all.py           <- 1 comando = todo el sistema
  start_dashboard.py     <- Solo dashboard (puerto 5000)
  start_monitor.py       <- Solo monitor Telegram + webhook
  start_campaign.py      <- CLI para campanas desde YAML
  run.py                 <- CLI para scraping directo
  leadforge/
    config.py / pipeline.py / apify_scraper.py / anymail_enricher.py
    hierarchy_filter.py / validation_cascade.py / owner_extractor.py
    lead_scorer.py / supabase_client.py
    monitor/    alerts.py, health_checker.py, telegram_bot.py, reply_webhook.py
    campaigns/  email_builder.py, account_manager.py, instantly_manager.py, whatsapp_manager.py
    dashboard/  main.py, category_ai.py, cost_tracker.py
                static/  index.html, wizard.html, accounts.html, reports.html
  campaign_configs/  ejemplo_campana.yaml
  mac_autostart/     instalar_autostart.sh, com.leadforge.system.plist
  supabase_schema.sql / requirements.txt / .env.example
  Dockerfile / docker-compose.yml
```

---

## SOLUCION DE PROBLEMAS
- "Variable requerida no encontrada": revisar .env sin espacios extra
- "Anymail Finder HTTP 402": suscripcion vencida en anymailfinder.com/account
- "Apify FAILED": revisar actor compass/crawler-google-places en Apify
- "No inserta en Supabase": ejecutar supabase_schema.sql y usar SERVICE_KEY (no Anon Key)
- "Dashboard no carga": lsof -i :5000 para ver si el puerto esta ocupado
- "Telegram no responde": verificar TELEGRAM_BOT_TOKEN y TELEGRAM_MASTER_CHAT_ID
