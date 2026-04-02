# 🚀 START HERE — LeadForge / ZenonFinder
> Lee este archivo PRIMERO en cualquier sesión nueva. Luego CONTEXT.md para detalles técnicos.

## ¿Qué es este sistema?
Bot de Telegram (@ZenonFinder) que genera leads B2B en México automáticamente:
DENUE (INEGI) + Apify (Google Maps) → AnyMailFinder (emails) → Instantly.ai (campañas cold email)

**Operador:** Zenon (Luis Vilchis) — vilchiszeluis@gmail.com
**Proyecto:** `C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\`
**Mac Mini:** `~/LeadForge/` (mismo contenido, paths diferentes)

---

## Estado al 2026-03-18 (actualizar cada sesión)

### Clientes activos
| Cliente | ID Supabase | Leads total | Válidos | Campaña Instantly |
|---|---|---|---|---|
| **SQB** (Química Inteligente) | `c7f3a2b1-...` | 2,103 | 108+ ↑ | ⚠️ Pendiente crear |
| **Regio Cribas** | `d0542bc7-...` | 2,191 | 656 | ✅ ACTIVA (30 contactos) |
| **LuPront** | `b8e2f4d6-...` | 6,641 | 656 | ⚠️ Pendiente crear |
| **Macrisa** | — | 5,470 | 625 | ⚠️ Pendiente crear |

### Pipeline SQB corriendo AHORA
```
sqb_pipeline.py  →  DENUE 20 estados/sectores  →  AMF hasta 800 válidos  →  CSV export
```
Monitorear con: `type logs\sqb_pipeline.log` (Windows) o `tail -f logs/sqb_pipeline.log` (Mac)

### Cuentas Instantly.ai SQB
- **22 cuentas IONOS** activas, sender: Luis Vilchis
- **35 emails/día/cuenta = 770 emails/día**
- Servidor: smtp.ionos.com:587 / imap.ionos.com:993

---

## Arrancar el sistema

### Windows (laptop Dell)
```powershell
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
# Bot Telegram (SIEMPRE con venv, NO con python del sistema)
venv\Scripts\python.exe start_monitor.py

# Pipeline SQB autónomo
venv\Scripts\python.exe sqb_pipeline.py

# Solo AMF + export (si DENUE ya corrió)
venv\Scripts\python.exe sqb_pipeline.py --solo-amf
```

### Mac Mini
```bash
cd ~/LeadForge
source venv/bin/activate
python start_monitor.py        # bot 24/7
python sqb_pipeline.py         # pipeline SQB
```

---

## Comandos Telegram activos
| Comando | Función |
|---|---|
| `/verificar sqb 500` | AMF ronda de 500 leads SQB |
| `/verificar rc 300` | AMF ronda Regio Cribas |
| `/verificar lp 500` | AMF ronda LuPront |
| `/verificar mac 300` | AMF ronda Macrisa |
| `/denue [Estado] [sector]` | DENUE scraping (cnc, alimentos, automotriz, flotas, mineria...) |
| `/creditos` | Ver créditos AMF restantes |
| `/leads` | Resumen de leads en BD |
| `/no` | Cancelar búsqueda en curso |

---

## APIs y keys (.env)
```
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
SUPABASE_URL=https://pfurkonwbjfmxpfogdtr.supabase.co
INSTANTLY_API_KEY=YOUR_INSTANTLY_API_KEY   (v1 — funciona para accounts)
DENUE_API_KEY=YOUR_DENUE_API_KEY
```
> ⚠️ Las keys completas están en el .env — nunca en git

---

## Próximas acciones prioritarias
1. ⏳ Esperar que `sqb_pipeline.py` llegue a 800 emails válidos SQB
2. 📧 Crear campaña SQB en Instantly con CSV generado automáticamente
3. 📧 Crear campaña LuPront (656 válidos listos ya)
4. 📧 Crear campaña Macrisa (625 válidos listos ya)
5. 🤖 Integrar sqb_pipeline.py en APScheduler del monitor (corre a las 2am sin intervención)
6. 💻 Migrar bot a Mac Mini para 24/7 sin depender de laptop

---

## Archivos de referencia
| Archivo | Contenido |
|---|---|
| `CONTEXT.md` | Arquitectura completa, stack, DB schema, flujos |
| `BITACORA.md` | Historial detallado de cambios por sesión |
| `sqb_pipeline.py` | Pipeline DENUE→AMF→CSV autónomo |
| `leadforge/monitor/telegram_bot.py` | Bot completo con todos los comandos |
| `leadforge/denue_enricher.py` | DENUE API client + SECTORES_DENUE catálogo |
| `leadforge/anymail_enricher.py` | AnyMailFinder client |
| `.env` | Todas las API keys |

---

## Error más común
```
ModuleNotFoundError: No module named 'dotenv'
```
**Causa:** Se usó `python` del sistema (Python 3.14) en vez del venv
**Fix:** Siempre usar `venv\Scripts\python.exe` (Windows) o `source venv/bin/activate` (Mac)
