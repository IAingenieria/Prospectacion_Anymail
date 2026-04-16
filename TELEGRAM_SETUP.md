# LeadForge — Configuración de Telegram (Fase 2)

## Paso 1: Crear el Bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Escribe: `/newbot`
3. Cuando pregunte el nombre: escribe `LeadForge Monitor`
4. Cuando pregunte el username: escribe algo como `leadforge_zenon_bot` (debe terminar en `bot`)
5. BotFather te dará un token como: `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
6. Copia ese token → ponlo en `.env` como `TELEGRAM_BOT_TOKEN=`

## Paso 2: Obtener tu Chat ID (Zenon)

1. Abre Telegram y busca **@userinfobot**
2. Escribe `/start`
3. El bot te responderá con tu ID numérico (ej: `123456789`)
4. Copia ese número → ponlo en `.env` como `TELEGRAM_MASTER_CHAT_ID=123456789`

## Paso 3: Iniciar el Bot

```bash
# Instalar dependencias de Fase 2
pip install -r requirements.txt

# Probar que Telegram funciona
python start_monitor.py --test

# Si ves "✅ OK" → el bot está configurado correctamente
```

Deberías recibir un mensaje en tu Telegram que dice:
> 🧪 LeadForge — Prueba de conexión exitosa

## Paso 4: Iniciar Todos los Servicios

```bash
python start_monitor.py
```

Recibirás en Telegram:
> 🚀 LeadForge Monitor — Iniciado
> ✅ Health checks: cada 30 minutos
> ✅ Bot de Telegram: activo
> ✅ Webhook server: puerto 8001

## Paso 5: Configurar el Webhook de Instantly.ai

Para recibir notificaciones cuando un lead responda tu email,
necesitas exponer el puerto 8001 a Internet.

### Opción A: ngrok (para Mac Mini en casa)

```bash
# Instalar ngrok (solo una vez)
brew install ngrok

# Exponer puerto 8001
ngrok http 8001

# ngrok te dará una URL como:
# https://abc123.ngrok.io
```

1. Copia esa URL (ej: `https://abc123.ngrok.io`)
2. Ve a Instantly.ai → Settings → Integrations → Webhooks
3. Agrega el webhook: `https://abc123.ngrok.io/webhook/instantly`
4. Selecciona eventos: `Email Replied`, `Email Bounced`, `Email Unsubscribed`
5. Si Instantly pide un secret, genéralo con:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Y ponlo en `.env` como `INSTANTLY_WEBHOOK_SECRET=`

### Opción B: Cloudflare Tunnel (más estable, gratis)

```bash
# Instalar cloudflared
brew install cloudflare/cloudflare/cloudflared

# Crear túnel permanente (no cambia la URL)
cloudflared tunnel --url http://localhost:8001
```

## Paso 6: Configurar Telegram para tus Clientes

Cuando un cliente contrate el servicio:

1. El cliente busca en Telegram: `@tu_bot_name`
2. El cliente escribe `/start`
3. El bot pide un código de vinculación
4. Tú obtienes su chat_id y lo registras en Supabase:

```sql
-- En el SQL Editor de Supabase
UPDATE clientes
SET telegram_chat_id = 987654321  -- chat_id del cliente
WHERE email = 'cliente@empresa.com';
```

A partir de ese momento, el cliente recibe SUS alertas directamente
en su Telegram sin que tú tengas que reenviar nada.

## Comandos que puede usar Zenon

```
/status           → Estado de todos los servicios
/leads            → Leads de las últimas 24h y 7 días
/respuestas       → Emails que han respondido
/reporte          → Reporte semanal completo
/creditos         → Créditos de Anymail y APIs
/clientes         → Ver todos los clientes activos
/agregar taller mecánico Monterrey → Nueva búsqueda
/pausar           → Pausar campaña activa
/ayuda            → Ver todos los comandos
```

## Autostart en Mac Mini (para que corra siempre)

```bash
# Crear el archivo de servicio
cat > ~/Library/LaunchAgents/com.leadforge.monitor.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.leadforge.monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/TU_USUARIO/Documents/CLAUDE DESKTOP/Claude Leads Instantly/start_monitor.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>/Users/TU_USUARIO/Documents/CLAUDE DESKTOP/Claude Leads Instantly</string>
  <key>StandardOutPath</key>
  <string>/Users/TU_USUARIO/Documents/CLAUDE DESKTOP/Claude Leads Instantly/logs/monitor.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/TU_USUARIO/Documents/CLAUDE DESKTOP/Claude Leads Instantly/logs/monitor_error.log</string>
</dict>
</plist>
EOF

# Reemplaza TU_USUARIO con tu nombre de usuario del Mac Mini

# Activar el servicio
launchctl load ~/Library/LaunchAgents/com.leadforge.monitor.plist

# Verificar que esté corriendo
launchctl list | grep leadforge
```

A partir de ahora, cada vez que enciendas el Mac Mini,
LeadForge Monitor arranca automáticamente.
