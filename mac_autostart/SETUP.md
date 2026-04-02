# 🖥️ SETUP — ZenonFinder en Mac Mini (24/7)

> **Objetivo:** Migrar el bot ZenonFinder de la laptop Windows al Mac Mini que corre 24/7.
> **Tiempo estimado:** 20-30 minutos
> **Prerequisito:** Mac Mini con Claude Code Terminal ya instalado y Telegram configurado.
> **Última actualización:** 2026-03-13

---

## 📋 ÍNDICE

1. [Prerrequisitos](#1-prerrequisitos)
2. [Transferir el proyecto](#2-transferir-el-proyecto)
3. [Configurar Python y dependencias](#3-configurar-python-y-dependencias)
4. [Configurar el archivo .env](#4-configurar-el-archivo-env)
5. [Probar el bot manualmente](#5-probar-el-bot-manualmente)
6. [Instalar autostart (LaunchAgent)](#6-instalar-autostart-launchagent)
7. [Verificar que todo funciona](#7-verificar-que-todo-funciona)
8. [Comandos de mantenimiento](#8-comandos-de-mantenimiento)
9. [Solución de problemas](#9-solución-de-problemas)

---

## 1. PRERREQUISITOS

Verificar en el Mac Mini que tienes instalado:

```bash
# Verificar Python 3.11+ (preferiblemente 3.12 o 3.14)
python3 --version

# Verificar pip
pip3 --version

# Verificar git (para clonar o actualizar)
git --version
```

Si Python no está instalado:
```bash
# Instalar Homebrew (si no está)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Instalar Python
brew install python@3.12
```

---

## 2. TRANSFERIR EL PROYECTO

### Opción A — Copiar desde Windows via USB/red (recomendado)

Desde la **laptop Windows**, comprime la carpeta del proyecto:
```
C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\
```

> ⚠️ **NO incluir** en la copia:
> - `venv/` (se recrea en Mac)
> - `__pycache__/` (se recrea automáticamente)
> - `logs/*.log` (opcional, no necesario)

Archivos que **SÍ debes copiar** obligatoriamente:
```
Claude Leads Instantly/
├── start_monitor.py              ← PUNTO DE ENTRADA
├── .env                          ← TODAS LAS API KEYS (crítico)
├── requirements.txt
├── recover_apify_runs.py         ← Herramienta de recuperación
├── leadforge/
│   ├── __init__.py
│   ├── config.py
│   ├── apify_scraper.py
│   ├── pipeline.py
│   ├── anymail_enricher.py
│   ├── validation_cascade.py
│   ├── lead_scorer.py
│   ├── owner_extractor.py
│   ├── supabase_client.py
│   └── monitor/
│       ├── telegram_bot.py
│       ├── health_checker.py
│       └── alerts.py
└── mac_autostart/
    ├── SETUP.md                  ← Este archivo
    ├── com.leadforge.system.plist
    └── instalar_autostart.sh
```

### Destino en Mac Mini

Coloca el proyecto en:
```
/Users/TU_USUARIO/leadforge/
```

> Reemplaza `TU_USUARIO` con el resultado de ejecutar `whoami` en el Mac Mini.

```bash
# Verificar tu usuario en Mac
whoami

# Crear el directorio destino
mkdir -p ~/leadforge

# Si copiaste por USB, mueve los archivos:
cp -r /Volumes/USB/Claude\ Leads\ Instantly/* ~/leadforge/

# Si usas red local (desde Windows al Mac):
# En Windows: net use \\MAC_IP\Users
# O usa AirDrop / iCloud Drive / USB
```

---

## 3. CONFIGURAR PYTHON Y DEPENDENCIAS

```bash
# Entrar al directorio del proyecto
cd ~/leadforge

# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
source venv/bin/activate

# Actualizar pip
pip install --upgrade pip

# Instalar dependencias
pip install -r requirements.txt

# Verificar instalación correcta
python -c "import telegram; import supabase; import anthropic; print('OK')"
```

Si hay errores de instalación:
```bash
# Instalar dependencias de sistema si faltan
brew install libpq

# Reinstalar con verbose para ver el error específico
pip install -r requirements.txt -v
```

---

## 4. CONFIGURAR EL ARCHIVO .ENV

El archivo `.env` debería haberse copiado desde Windows. Verificar que está completo:

```bash
cd ~/leadforge
cat .env
```

Debe contener **todas estas variables**:

```env
# ── Apify ──────────────────────────────────────────────────────
APIFY_TOKEN=tu_token_aqui
APIFY_ACTOR_ID=nwua9Gu5YrADL7ZDj

# ── Anthropic (Claude Haiku) ───────────────────────────────────
ANTHROPIC_API_KEY=tu_key_aqui

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=tu_token_aqui
TELEGRAM_MASTER_CHAT_ID=tu_chat_id_aqui

# ── Supabase ───────────────────────────────────────────────────
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...tu_service_key

# ── Anymail Finder ─────────────────────────────────────────────
ANYMAIL_API_KEY=tu_key_aqui

# ── Instantly.ai ───────────────────────────────────────────────
INSTANTLY_API_KEY=tu_key_aqui

# ── Cliente ────────────────────────────────────────────────────
CLIENTE_ID=d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99
```

> ⚠️ **IMPORTANTE:** El `APIFY_ACTOR_ID` correcto es `nwua9Gu5YrADL7ZDj`
> NO uses `compass/crawler-google-places` (ese da 404)

Si el `.env` no se copió, créalo desde cero:
```bash
nano ~/leadforge/.env
# Pega todas las variables y guarda con Ctrl+X → Y → Enter
```

---

## 5. PROBAR EL BOT MANUALMENTE

Antes de configurar el autostart, prueba que el bot funciona:

```bash
cd ~/leadforge

# Activar entorno virtual
source venv/bin/activate

# Lanzar el bot (Mac NO necesita el flag -X utf8)
python start_monitor.py
```

Deberías ver en la terminal algo como:
```
[INFO] LeadForge Monitor iniciando...
[INFO] Bot de Telegram iniciado — @ZenonFinder
[INFO] Health checker activo
```

**Prueba en Telegram:** Escríbele al bot:
```
Busco 5 ferreterías en Monterrey Nuevo León
```

Si responde con categorías expandidas → ✅ Bot funcionando correctamente.

Detener con `Ctrl+C` y continuar al paso 6.

---

## 6. INSTALAR AUTOSTART (LAUNCHAGENT)

El LaunchAgent hace que el bot arranque automáticamente cuando el Mac Mini enciende
y lo reinicia si se cae.

### Método automático (recomendado)

```bash
cd ~/leadforge

# Dar permisos de ejecución al script
chmod +x mac_autostart/instalar_autostart.sh

# Ejecutar instalador
bash mac_autostart/instalar_autostart.sh
```

### Método manual (si el automático falla)

```bash
# Paso 1: Obtener tu usuario
USUARIO=$(whoami)
echo "Tu usuario es: $USUARIO"

# Paso 2: Generar el .plist con las rutas correctas
cat > ~/Library/LaunchAgents/com.leadforge.system.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.leadforge.system</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/$USUARIO/leadforge/venv/bin/python</string>
    <string>/Users/$USUARIO/leadforge/start_monitor.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/$USUARIO/leadforge</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PYTHONDONTWRITEBYTECODE</key>
    <string>1</string>
    <key>PYTHONIOENCODING</key>
    <string>utf-8</string>
  </dict>

  <key>KeepAlive</key>
  <true/>

  <key>RunAtLoad</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>/Users/$USUARIO/leadforge/logs/stdout.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/$USUARIO/leadforge/logs/stderr.log</string>

  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF

# Paso 3: Crear directorio de logs
mkdir -p ~/leadforge/logs

# Paso 4: Cargar el LaunchAgent
launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.leadforge.system.plist

echo "✅ LaunchAgent instalado"
```

---

## 7. VERIFICAR QUE TODO FUNCIONA

```bash
# Verificar que el LaunchAgent está activo
launchctl list | grep leadforge

# Debe mostrar algo como:
# 69208    0    com.leadforge.system

# Ver logs en tiempo real
tail -f ~/leadforge/logs/stdout.log

# Ver errores (si hay problemas)
tail -f ~/leadforge/logs/stderr.log
```

**Prueba final:** Escríbele al bot en Telegram y confirma que:
1. Responde con categorías expandidas ✅
2. Después de `/si` inicia la búsqueda ✅
3. Al terminar reporta los resultados con leads > 0 ✅
4. Los leads aparecen en Supabase (`leads_master`) ✅

---

## 8. COMANDOS DE MANTENIMIENTO

### Control del bot

```bash
# Ver estado del LaunchAgent
launchctl list | grep leadforge

# Detener el bot
launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist

# Iniciar el bot
launchctl load ~/Library/LaunchAgents/com.leadforge.system.plist

# Reiniciar el bot (si hiciste cambios al código)
launchctl kickstart -k gui/$(id -u)/com.leadforge.system

# Desinstalar autostart completamente
launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist
rm ~/Library/LaunchAgents/com.leadforge.system.plist
```

### Monitorear logs

```bash
# Logs del bot (stdout)
tail -f ~/leadforge/logs/stdout.log

# Errores (stderr)
tail -f ~/leadforge/logs/stderr.log

# Últimas 50 líneas del log principal
tail -50 ~/leadforge/logs/monitor.log

# Buscar errores específicos
grep -i "error" ~/leadforge/logs/stderr.log | tail -20
```

### Recuperar runs de Apify pagados (si el timeout vuelve a fallar)

```bash
cd ~/leadforge
source venv/bin/activate

# Listar runs recientes
python recover_apify_runs.py --limit 15

# Recuperar todos los runs exitosos
python recover_apify_runs.py --all

# Recuperar un run específico
python recover_apify_runs.py --run RUN_ID_AQUI
```

### Actualizar el código (cuando hay cambios desde Windows)

```bash
cd ~/leadforge

# Detener el bot primero
launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist

# Copiar archivos actualizados (desde USB o red)
cp /Volumes/USB/leadforge/leadforge/*.py ~/leadforge/leadforge/
cp /Volumes/USB/leadforge/leadforge/monitor/*.py ~/leadforge/leadforge/monitor/
cp /Volumes/USB/leadforge/*.py ~/leadforge/

# Reiniciar el bot
launchctl load ~/Library/LaunchAgents/com.leadforge.system.plist

# Verificar
launchctl list | grep leadforge
```

---

## 9. SOLUCIÓN DE PROBLEMAS

### ❌ El bot no arranca / no aparece en launchctl list

```bash
# Ver el error directamente
cat ~/leadforge/logs/stderr.log

# Probar manualmente para ver el error
cd ~/leadforge
source venv/bin/activate
python start_monitor.py
```

### ❌ ModuleNotFoundError al arrancar

```bash
# Reinstalar dependencias
cd ~/leadforge
source venv/bin/activate
pip install -r requirements.txt
```

### ❌ "No se puede conectar a Telegram"

- Verificar que el Mac Mini tiene internet
- Verificar que `TELEGRAM_BOT_TOKEN` en `.env` es correcto
- Verificar que no hay otro proceso usando el mismo bot (solo puede correr UNA instancia)

```bash
# Ver si hay procesos duplicados
ps aux | grep start_monitor
```

### ❌ Apify devuelve 0 resultados

- Verificar que `APIFY_ACTOR_ID=nwua9Gu5YrADL7ZDj` en `.env`
- Verificar que el token de Apify tiene saldo
- Usar la herramienta de recuperación si ya se pagó el run

### ❌ Leads no aparecen en Supabase

- Verificar `SUPABASE_URL` y `SUPABASE_SERVICE_KEY` en `.env`
- Verificar que la tabla `leads_master` existe con el schema correcto
- Ver el log de errores: `grep "Error insertando" ~/leadforge/logs/stderr.log`

### ❌ El bot se cae y no se reinicia solo

```bash
# Verificar que KeepAlive está en true en el plist
cat ~/Library/LaunchAgents/com.leadforge.system.plist | grep -A1 KeepAlive

# Reinstalar el LaunchAgent
bash ~/leadforge/mac_autostart/instalar_autostart.sh
```

### ❌ Caracteres especiales/tildes en logs con basura

```bash
# Verificar que PYTHONIOENCODING está en el plist
cat ~/Library/LaunchAgents/com.leadforge.system.plist | grep -A1 PYTHONIOENCODING
# Si no está, reinstalar con el script actualizado
```

---

## 📊 DIFERENCIAS WINDOWS vs MAC

| Aspecto | Windows (laptop) | Mac Mini |
|---|---|---|
| Comando arranque | `Start-Process ... -X utf8 start_monitor.py` | `python start_monitor.py` (sin -X utf8) |
| Autostart | Manual (cada vez) | LaunchAgent (automático) |
| Encoding | Necesita `-X utf8` | UTF-8 por defecto |
| Signal handlers | NO funciona (Win32) | SÍ funciona |
| Uptime | Depende de la laptop | 24/7 garantizado |
| Logs | `logs\monitor.log` | `logs/stdout.log` + `logs/stderr.log` |
| Reinicio automático | No | Sí (KeepAlive en LaunchAgent) |

---

## 🔑 REFERENCIA RÁPIDA

```bash
# Arrancar                    launchctl load ~/Library/LaunchAgents/com.leadforge.system.plist
# Detener                     launchctl unload ~/Library/LaunchAgents/com.leadforge.system.plist
# Reiniciar                   launchctl kickstart -k gui/$(id -u)/com.leadforge.system
# Ver estado                  launchctl list | grep leadforge
# Ver logs                    tail -f ~/leadforge/logs/stdout.log
# Ver errores                 tail -f ~/leadforge/logs/stderr.log
# Recuperar runs Apify        cd ~/leadforge && python recover_apify_runs.py --all
```

---

## 🚀 FASE 2 — COMPONENTES ADICIONALES (instalar después de Fase 1)

Una vez que el bot de generación de leads esté funcionando en Mac Mini,
instala los componentes de la Fase 2 (campañas de email):

### Archivos nuevos de Fase 2 (copiar desde Windows cuando estén listos)

```
leadforge/
├── campaign_launcher.py      ← Genera emails con Claude + sube a Instantly
├── webhook_server.py         ← Recibe eventos de Instantly (FastAPI)
└── leadforge/
    └── campaigns/
        ├── email_generator.py    ← Claude API genera emails personalizados
        ├── instantly_client.py   ← Cliente API de Instantly.ai
        └── campaign_manager.py   ← Gestión de campañas por cliente
```

### Variables .env adicionales para Fase 2

```env
# ── Instantly.ai (ya deberías tenerlo) ────────────────
INSTANTLY_API_KEY=tu_key_aqui
INSTANTLY_WORKSPACE_ID=tu_workspace_id

# ── Webhook (para recibir eventos de Instantly) ────────
WEBHOOK_SECRET=tu_secret_aqui
WEBHOOK_PORT=8080
```

### Iniciar webhook server (Fase 2)

```bash
# El webhook server corre junto al bot en segundo plano
cd ~/leadforge
source venv/bin/activate
python webhook_server.py &

# Ver logs del webhook
tail -f ~/leadforge/logs/webhook.log
```

### Clientes configurados en el sistema

| ID | Cliente | Industria |
|---|---|---|
| 1 | Regio_Cribas | Mallas y cribas de alambre |
| 2 | Le_Pront | Pinturas industriales |
| 3 | SQB | Química industrial / Limpieza |
| 4 | Goodman_Tech | Automatización con IA |
| 5 | Focus | Consultoría ESG |

### Cuentas de envío Instantly.ai

| Cuenta Gmail | Uso |
|---|---|
| vilchiszeluis@gmail.com | General / Goodman Tech |
| luisvilchisze@gmail.com | General / rotación |
| ia-ingenieria22@gmail.com | Campañas IA |
| esg.mexico.mx@gmail.com | Campañas ESG / Focus |

> Capacidad: ~500 emails/día con las 4 cuentas en warm-up completo.

---

*SETUP.md generado el 2026-03-13 — LeadForge / ZenonFinder*
*Para contexto completo del sistema: ver CONTEXT.md y BITACORA.md*
