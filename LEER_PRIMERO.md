# 🍎 LeadForge en Mac Mini — Guía de Instalación y Operación
> Este archivo es el punto de partida en la Mac Mini. Léelo completo antes de hacer cualquier cosa.

---

## 1. ¿Qué es esto?
Bot de Telegram (@ZenonFinder) que genera leads B2B en México automáticamente:
- **DENUE (INEGI)** → obtiene empresas por estado y sector
- **AnyMailFinder** → verifica/encuentra emails corporativos
- **Instantly.ai** → envía campañas cold email con 22 cuentas IONOS

**Operador:** Zenon (Luis Vilchis) — vilchiszeluis@gmail.com

---

## 2. Instalación inicial (solo la primera vez)

```bash
# Clona o copia esta carpeta a ~/LeadForge/
# Asegúrate de estar en el directorio correcto
cd ~/LeadForge

# Python 3.12 recomendado (brew install python@3.12)
python3.12 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.template .env
nano .env          # Llena todas las keys (pídelas a Zenon si no las tienes)
```

### Keys que necesitas para el .env:
| Variable | Dónde obtenerla |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather en Telegram |
| `TELEGRAM_MASTER_CHAT_ID` | Tu chat ID personal (usa @userinfobot) |
| `SUPABASE_KEY` | Supabase → Settings → API → service_role key |
| `ANYMAIL_API_KEY` | anymailfinder.com → Account → API |
| `DENUE_API_KEY` | inegi.org.mx → DENUE API |
| `INSTANTLY_API_KEY` | Instantly.ai → Settings → API |

---

## 3. Arrancar el bot (operación diaria)

```bash
cd ~/LeadForge
source venv/bin/activate
python start_monitor.py
```

Para dejarlo corriendo 24/7 sin que esté visible → ver sección 5.

---

## 4. Comandos Telegram disponibles

| Comando | Función |
|---|---|
| `/verificar sqb 500` | AMF ronda 500 leads SQB (Química Inteligente) |
| `/verificar rc 300` | AMF ronda Regio Cribas |
| `/verificar lp 500` | AMF ronda LuPront |
| `/verificar mac 300` | AMF ronda Macrisa |
| `/denue [Estado] [sector]` | Scraping DENUE (sectores: cnc, alimentos, automotriz, flotas, mineria...) |
| `/creditos` | Ver créditos AnyMailFinder restantes |
| `/leads` | Resumen de leads en base de datos |
| `/no` | Cancelar búsqueda en curso |

---

## 5. Automatizar 24/7 con launchd

```bash
# Edita el plist y reemplaza AQUI_VA_TU_USUARIO con tu usuario Mac
# Ejemplo: si tu usuario es "zenon", cambia todas las ocurrencias
sed -i '' 's/AQUI_VA_TU_USUARIO/zenon/g' ~/LeadForge/mac_autostart/com.zenon.leadforge.plist

# Instalar el servicio
mkdir -p ~/Library/LaunchAgents
cp ~/LeadForge/mac_autostart/com.zenon.leadforge.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.zenon.leadforge.plist

# Verificar que está corriendo
launchctl list | grep leadforge

# Ver logs en tiempo real
tail -f ~/LeadForge/logs/launchd.log
```

---

## 6. Pipeline SQB autónomo (Química Inteligente)

```bash
cd ~/LeadForge
source venv/bin/activate

# Pipeline completo (DENUE → AMF → CSV export)
python sqb_pipeline.py

# Solo verificar emails (si DENUE ya corrió)
python sqb_pipeline.py --solo-amf

# Solo exportar CSV
python sqb_pipeline.py --solo-export
```

El CSV se guarda en `~/Downloads/sqb_instantly_FECHA.csv`

---

## 7. Clientes activos

| Cliente | Leads total | Válidos | Estado campaña |
|---|---|---|---|
| **SQB** (Química Inteligente) | 2,103+ | en proceso | Pipeline corriendo |
| **Regio Cribas** | 2,191 | 656 | ✅ ACTIVA en Instantly |
| **LuPront** | 6,641 | 656 | ⚠️ Pendiente crear |
| **Macrisa** | 5,470 | 625 | ⚠️ Pendiente crear |

---

## 8. Error más común

```
ModuleNotFoundError: No module named 'dotenv'
```
**Causa:** Olvidaste activar el venv
**Fix:** `source venv/bin/activate` antes de cualquier `python`

---

## 9. Archivos importantes

| Archivo | Contenido |
|---|---|
| `START_HERE.md` | Estado actual del proyecto (actualizar cada sesión) |
| `CONTEXT.md` | Arquitectura completa y stack técnico |
| `BITACORA.md` | Historial de sesiones y cambios |
| `sqb_pipeline.py` | Pipeline autónomo SQB |
| `leadforge/monitor/telegram_bot.py` | Bot de Telegram completo |
| `.env` | Keys API (NUNCA subir a git) |
| `mac_autostart/com.zenon.leadforge.plist` | Servicio launchd 24/7 |
