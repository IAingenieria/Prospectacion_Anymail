# 🚀 LeadForge / ZenonFinder — Contexto Maestro del Proyecto

> **Proyecto:** Sistema automatizado de generación de leads B2B mediante Google Maps scraping
> **Nombres del sistema:** LeadForge (backend) / ZenonFinder (bot de Telegram)
> **Operador:** Zenon — dueño del sistema, usuario master
> **Objetivo:** Bot de Telegram que recibe búsquedas en lenguaje natural, scraping Google Maps, enriquecimiento de emails, almacenamiento en Supabase con embudo de ventas
> **Stack Principal:** Python 3.14 + Telegram Bot + Apify + Anymail Finder + Claude Haiku + Supabase
> **Última actualización:** 2026-03-16 (sesión completa)

---

## 📋 TABLA DE CONTENIDOS

1. [Visión General](#visión-general)
2. [Stack Tecnológico](#stack-tecnológico)
3. [Directorio del Proyecto](#directorio-del-proyecto)
4. [Archivos Clave](#archivos-clave)
5. [APIs y Servicios](#apis-y-servicios)
6. [Base de Datos Supabase](#base-de-datos-supabase)
7. [Flujo del Bot](#flujo-del-bot)
8. [Pipeline de Procesamiento](#pipeline-de-procesamiento)
9. [Actor Apify](#actor-apify)
10. [Arrancar el Bot](#arrancar-el-bot)
11. [Herramientas de Recuperación](#herramientas-de-recuperación)
12. [Estado Actual](#estado-actual)
13. [Pendientes Importantes](#pendientes-importantes)
14. [Perfil del Operador](#perfil-del-operador)
15. [Otros Proyectos Relacionados](#otros-proyectos-relacionados)

---

## 🏢 VISIÓN GENERAL

### Modelo de Negocio
Sistema automatizado de generación de leads B2B para México. Extrae negocios de Google Maps, los enriquece con emails corporativos y los organiza en un embudo de ventas.

### Servicios que ofrece el sistema
1. **Extracción de datos** de negocios desde Google Maps (Apify)
2. **Expansión inteligente de categorías** (Claude Haiku convierte "pedreras" → 7 términos de búsqueda)
3. **Enriquecimiento de contactos** (Anymail Finder busca emails corporativos)
4. **Base de datos maestra** en Supabase con deduplicación automática
5. **Embudo de ventas** completo: nuevo → cliente
6. **Caché de búsquedas** para evitar pagos duplicados a Apify

### Mercado Geográfico
- **Principal:** Noreste de México (Nuevo León, Coahuila, Tamaulipas)
- **Ciudades clave:** Monterrey, Apodaca, Guadalupe, Santa Catarina, San Pedro, Escobedo

---

## 🔧 STACK TECNOLÓGICO

| Componente | Tecnología | Versión / Detalle |
|---|---|---|
| Lenguaje | Python | 3.14.2 |
| Bot de Telegram | python-telegram-bot | @ZenonFinder |
| Scraping | Apify | Actor `nwua9Gu5YrADL7ZDj` (compass/google-maps-extractor) |
| Enriquecimiento emails | Anymail Finder | API REST |
| IA / Parseo | Claude Haiku | `claude-haiku-4-5-20251001` |
| Base de datos | Supabase (PostgreSQL) | Proyecto "Generacion de Leads" |
| Email outreach | Instantly.ai | Campañas cold email |
| WhatsApp outreach | yCloud | Mensajes masivos |
| Entorno | Windows 11 (Dell laptop) | Virtualenv en `venv/` |

---

## 📁 DIRECTORIO DEL PROYECTO

```
C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\
```

### Estructura de archivos

```
Claude Leads Instantly/
├── start_monitor.py              ← PUNTO DE ENTRADA PRINCIPAL (bot Telegram)
├── webhook_server.py             ← PUNTO DE ENTRADA WEBHOOK (Instantly.ai)
├── .env                          ← Todas las API keys (NO subir a git)
├── .env.example                  ← Plantilla (actor viejo pendiente corregir)
├── requirements.txt
├── recover_apify_runs.py         ← Herramienta de recuperación de runs pagados
├── CONTEXT.md                    ← Descripción general del proyecto
├── BITACORA.md                   ← Changelog con fechas y razones
├── SESION_CONTEXTO_2026-03-13.md ← Contexto sesión del día
│
├── leadforge/
│   ├── __init__.py
│   ├── config.py                 ← Configuración desde .env (APIFY_ACTOR_ID, etc.)
│   ├── apify_scraper.py          ← Scraping Google Maps — 1 run multi-término
│   ├── pipeline.py               ← Orquestador principal run_pipeline()
│   ├── anymail_enricher.py       ← Búsqueda de emails corporativos
│   ├── validation_cascade.py     ← Validación emails: status→MX→catch-all→dedup
│   ├── lead_scorer.py            ← Score 0-100 por señales del negocio
│   ├── owner_extractor.py        ← Extrae nombre dueño de reseñas Google
│   ├── supabase_client.py        ← insert_lead_master(), cache, get_existing_emails()
│   ├── campaigns/
│   │   ├── instantly_manager.py  ← Cliente API Instantly.ai + inyección gradual
│   │   ├── email_builder.py      ← Personalización de emails con Claude
│   │   └── account_manager.py   ← Gestión de cuentas de envío
│   └── monitor/
│       ├── telegram_bot.py       ← Bot ZenonFinder — handle_free_text(), cmd_si()
│       ├── reply_webhook.py      ← FastAPI webhook — recibe eventos Instantly.ai ✅
│       ├── health_checker.py     ← Health checks cada 30 min
│       ├── alerts.py             ← send_telegram(), fire_alert()
│       └── telegram_bot.py      ← send_reply_notification()
│
├── logs/
│   ├── monitor.log               ← Log del bot Telegram
│   └── webhook.log               ← Log del servidor webhook
│
└── sql/
    ├── setup_leads_master.sql    ← CREATE TABLE leads_master (schema correcto)
    └── setup_supabase_regio_cribas.sql ← Pendiente ejecutar para RC
```

---

## 🔑 APIs Y SERVICIOS

| Servicio | Variable `.env` | Valor / Notas |
|---|---|---|
| Apify | `APIFY_TOKEN` | Token de cuenta Apify |
| Actor Apify | `APIFY_ACTOR_ID` | `nwua9Gu5YrADL7ZDj` ← actor correcto |
| Anthropic | `ANTHROPIC_API_KEY` | Claude Haiku para parsear búsquedas |
| Telegram Bot | `TELEGRAM_BOT_TOKEN` | Bot @ZenonFinder |
| Telegram Master | `TELEGRAM_MASTER_CHAT_ID` | Chat ID de Zenon (recibe alertas) |
| Supabase URL | `SUPABASE_URL` | URL del proyecto Supabase |
| Supabase Key | `SUPABASE_SERVICE_KEY` | Service key (bypasa RLS) |
| Anymail | `ANYMAIL_API_KEY` | Búsqueda emails corporativos |
| Instantly | `INSTANTLY_API_KEY` | Campañas cold email |
| Cliente ID | `CLIENTE_ID` | `d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99` |

> ⚠️ **IMPORTANTE:** El actor Apify correcto es `nwua9Gu5YrADL7ZDj` = `compass/google-maps-extractor`
> **NO usar** `compass/crawler-google-places` (devuelve 404)
> **NO usar** `lukaskrivka/...` (cuesta $9/1000 vs $4/1000)

---

## 🗄️ BASE DE DATOS SUPABASE

### Tabla Principal: `leads_master` (creada 2026-03-13)

**Tabla unificada — reemplaza email_leads + social_leads**

```sql
CREATE TABLE leads_master (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id      UUID NOT NULL DEFAULT 'a0000000-0000-0000-0000-000000000001',
  nombre_negocio  TEXT NOT NULL,
  categoria       TEXT,
  ciudad          TEXT,
  estado          TEXT,
  pais            TEXT DEFAULT 'MX',
  direccion       TEXT,
  sitio_web       TEXT,
  telefono        TEXT,
  facebook_url    TEXT,
  instagram_url   TEXT,
  rating          NUMERIC(3,1),
  review_count    INTEGER DEFAULT 0,
  google_maps_url TEXT,
  apify_run_id    TEXT,
  termino_busqueda TEXT,
  email           TEXT,
  email_status    TEXT,
  hierarchy_score INTEGER DEFAULT 0,
  anymail_procesado BOOLEAN DEFAULT FALSE,
  owner_name      TEXT,
  cargo_inferido  TEXT,
  lead_score      INTEGER DEFAULT 0,
  canal_recomendado TEXT,
  actividad_digital_score INTEGER DEFAULT 0,
  etapa           TEXT NOT NULL DEFAULT 'nuevo',
  campania_id     TEXT,
  instantly_lead_id TEXT,
  fecha_envio_email    TIMESTAMPTZ,
  email_abierto        BOOLEAN DEFAULT FALSE,
  fecha_apertura       TIMESTAMPTZ,
  veces_abierto        INTEGER DEFAULT 0,
  respondio_email      BOOLEAN DEFAULT FALSE,
  fecha_respuesta_email TIMESTAMPTZ,
  texto_respuesta_email TEXT,
  whatsapp_enviado     BOOLEAN DEFAULT FALSE,
  fecha_envio_whatsapp TIMESTAMPTZ,
  respondio_whatsapp   BOOLEAN DEFAULT FALSE,
  fecha_respuesta_whatsapp TIMESTAMPTZ,
  texto_respuesta_whatsapp TEXT,
  dm_enviado           BOOLEAN DEFAULT FALSE,
  fecha_envio_dm       TIMESTAMPTZ,
  respondio_dm         BOOLEAN DEFAULT FALSE,
  notas           TEXT,
  do_not_contact  BOOLEAN DEFAULT FALSE,
  motivo_baja     TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  scraped_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX lm_dedup ON leads_master(nombre_negocio, ciudad, cliente_id);
CREATE INDEX lm_cliente    ON leads_master(cliente_id);
CREATE INDEX lm_etapa      ON leads_master(etapa);
CREATE INDEX lm_lead_score ON leads_master(lead_score DESC);
CREATE INDEX lm_created    ON leads_master(created_at DESC);
```

### Embudo de Ventas (campo `etapa`)

```
nuevo → calificado → contactado → abierto → respondio
                                                  ↓
                                        interesado | descartado
                                                  ↓
                                         reunion → propuesta → cliente
```

### Otras Tablas (mantener, NO eliminar)

| Tabla | Propósito |
|---|---|
| `email_leads` | Tabla antigua — historial pre-2026-03-13 |
| `social_leads` | Tabla antigua — historial pre-2026-03-13 |
| `busquedas_cache` | Caché de búsquedas para no repetir Apify |
| `lista_general_enriched` | Datos del proceso MACRISA |
| `alertas` | Alertas del sistema |
| `campanias` | Campañas de email outreach |
| `clientes` | Clientes del servicio |

### Vistas Creadas

| Vista | Descripción |
|---|---|
| `embudo_ventas` | Conteo de leads por etapa |
| `leads_calientes` | score > 60 y etapa = nuevo |
| `metricas_diarias` | Estadísticas por día |

---

## 🤖 FLUJO DEL BOT (telegram_bot.py)

```
[Usuario escribe texto libre en Telegram]
          ↓
handle_free_text()
          ↓
parse_finder_intent() → Claude Haiku
  Prompt: "Extrae intención de búsqueda de leads"
  Output JSON: {es_busqueda, terminos[], ciudades[], estado, cantidad}
  ⚠️ Claude devuelve JSON en ```json fences → strip de backticks antes de json.loads
          ↓
expand_search_terms() → Claude Haiku
  Expande 1 término → 7-9 categorías relacionadas
  Ejemplo: "pedreras" → [pedreras, cantera, extracción de piedra, ...]
          ↓
Bot muestra resumen y pregunta: ¿Confirmas? /si · /no
          ↓  (usuario escribe /si)
cmd_si()
  asyncio.create_task(run_all())  ← no bloquea el bot
          ↓
run_all() → run_pipeline()
          ↓
Bot envía resumen: "N lugares encontrados | N email leads | N social leads"
```

---

## ⚙️ PIPELINE DE PROCESAMIENTO (pipeline.py)

```
run_pipeline(terminos, location, cantidad, cliente_id)
          ↓
check_search_cache()   ← ¿Ya se buscó esto? → REUSE o SCRAPE
          ↓ (si SCRAPE)
ApifyScraper.scrape_multi_term()
  → _run_actor()         POST /v2/acts/{id}/runs
  → _wait_for_completion()  poll cada 5s, timeout 12 min
  → _get_dataset_items()    GET /v2/actor-runs/{id}/dataset/items
  → _parse_item()           NegocioRaw[]
  → deduplicar por teléfono y dominio
          ↓
anymail.check_account_status()  ← ¿Créditos disponibles?
          ↓
asyncio.gather( process_negocio() × N )   Semaphore = concurrencia limitada
          ↓
Para cada negocio:
  1. extract_owner_from_reviews()   regex + Claude Haiku
  2. if sitio_web or email → anymail.enrich_negocio()
     else → AnymailResult vacío (skip) ← ahorra tiempo y créditos
  3. validate_company_emails()
  4. calculate_lead_score() → 0-100
  5. insert_lead_master() → Supabase leads_master
          ↓
save_search_cache()  → busquedas_cache
          ↓
PipelineStats → Bot envía resumen a Telegram
```

**Optimización clave:** Anymail solo se llama si el negocio tiene `sitio_web` o `email`.
Sin dominio = sin email posible = skip inmediato. Reduce tiempo de ~5 min a ~1-2 min.

---

## 🗺️ ACTOR APIFY

**Actor:** `nwua9Gu5YrADL7ZDj` = `compass/google-maps-extractor`
**Costo:** $4.00 / 1,000 resultados

Input JSON que usa el sistema:
```json
{
  "searchStringsArray": ["término1", "término2", "término3"],
  "locationQuery": "Nuevo León, Mexico",
  "maxCrawledPlacesPerSearch": 10,
  "language": "es-419",
  "scrapeContacts": true,
  "includeWebResults": false,
  "maxImages": 0,
  "skipClosedPlaces": false
}
```

**Comportamiento:** Un solo run con múltiples términos cubre TODO el estado.
Apify divide automáticamente en segmentos del mapa para cada término.
**Tiempos reales observados:**
- Búsquedas de 7-9 términos × 10 c/u → 4-15 minutos
- El timeout en `_wait_for_completion()` está en **12 minutos** (aumentado de 3 min)

---

## 🚀 ARRANCAR EL SISTEMA

### Windows (laptop Dell — desarrollo/pruebas)

**Método recomendado — auto-reinicio si cae:**
```powershell
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
.\start_zenonbot.bat
```

**Instalar auto-arranque con Windows (una sola vez, como admin):**
```powershell
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\instalar_autostart.ps1
```

**PowerShell #1 — Bot Telegram (manual):**
```powershell
# Matar proceso anterior (si existe)
Get-Process python | Stop-Process -Force

# Arrancar bot
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
.\venv\Scripts\python.exe -X utf8 start_monitor.py
```

**PowerShell #2 — Webhook server:**
```powershell
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
.\venv\Scripts\python.exe -X utf8 webhook_server.py
```

**PowerShell #3 — ngrok (exponer webhook al exterior):**
```powershell
cd "C:\Users\Dell\Downloads\ngrok-v3-stable-windows-amd64"
.\ngrok.exe http 8001
# URL pública: https://XXXX.ngrok-free.app/webhook/instantly
```

> ⚠️ ngrok gratis cambia la URL cada reinicio. En producción (Mac Mini) usar IP fija con port forwarding.

### Verificar que está corriendo

```powershell
Get-Process python | Select-Object Id, HasExited
```

### Ver logs en tiempo real

```powershell
# Log del bot
Get-Content 'C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\logs\monitor.log' -Wait -Tail 30

# Log del webhook
Get-Content 'C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\logs\webhook.log' -Wait -Tail 30
```

### Health checks

```
# Webhook server
https://XXXX.ngrok-free.app/webhook/health

# Test Telegram
https://XXXX.ngrok-free.app/webhook/test-telegram
```

---

## 🔧 HERRAMIENTAS DE RECUPERACIÓN

### recover_apify_runs.py (creado 2026-03-13)

Herramienta para recuperar runs de Apify que ya se pagaron pero no se registraron en Supabase (por timeout del pipeline).

```powershell
cd "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"

# Listar runs recientes
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --limit 15

# Recuperar un run específico
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --run RUN_ID

# Recuperar TODOS los runs exitosos ($0.01+) de los últimos 15
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --all
```

**Cómo funciona:**
1. Consulta la API de Apify para listar runs recientes
2. Filtra runs con `status=SUCCEEDED` y costo > $0.01
3. Descarga el dataset de cada run
4. Procesa los items a través del mismo pipeline (sin llamar Apify de nuevo)
5. Inserta en `leads_master`

---

## 📊 ESTADO ACTUAL (2026-03-18)

### ✅ Funcionando correctamente
- Bot de Telegram @ZenonFinder corriendo con código actualizado
- Parseo de lenguaje natural (Claude Haiku)
- Expansión de categorías (Claude Haiku)
- Scraping Google Maps (Apify actor correcto)
- Pipeline de procesamiento completo con DENUE automático
- Tabla `leads_master` — **10,935+ leads / 108+ SQB válidos**
- Script de recuperación `recover_apify_runs.py` — rescató 1,782 leads históricos
- **Webhook server** (FastAPI puerto 8001) — recibe eventos Instantly.ai ✅
- **ngrok tunnel** configurado en Windows para pruebas ✅
- **Instantly.ai webhook** configurado y apuntando al servidor ✅
- **Notificaciones Telegram** probadas y confirmadas para replies ✅
- **Heartbeat** cada 2h — bot avisa "sigo vivo" por Telegram ✅
- **DENUE automático** — enriquece leads sin email después de cada búsqueda ✅
- **DENUE nocturno** — job 3am diario en APScheduler ✅
- **Auto-arranque Windows** — start_zenonbot.bat + instalar_autostart.ps1 ✅
- **Supabase RLS** — habilitado en las 12 tablas, 5 vulnerabilidades de seguridad corregidas ✅
- **22 cuentas IONOS en Instantly** — Química Inteligente/SQB, 35 emails/día = 770/día ✅
- **Regio Cribas campaña ACTIVA** — 30 contactos, enviando ✅
- **sqb_pipeline.py** — pipeline autónomo DENUE→AMF→Export sin intervención humana ✅
- **Comando /verificar sqb** — verificación AMF SQB desde Telegram ✅

### 📊 Leads por cliente (2026-03-18)
| Cliente | Total leads | Emails válidos | Estado campaña |
|---|---|---|---|
| SQB | 2,103 | 108+ (creciendo) | Pipeline corriendo |
| Regio Cribas | 2,191 | 656 (no-standard status) | ✅ Activa en Instantly |
| LuPront | 6,641 | 656 valid | Pendiente campaña |
| Macrisa | 5,470 | 625 valid | Pendiente campaña |

### 📧 Cuentas de envío Instantly.ai (2026-03-18)
| Grupo | Cuentas | Límite/día | Total/día | Estado |
|---|---|---|---|---|
| Química Inteligente (SQB) | 22 cuentas IONOS | 35 | **770/día** | ✅ Activas |
| Regio Cribas | contacto@mallasycribas.com.mx | 30 | 30/día | ✅ En campaña |
| LuPront | contacto@lupront.com | — | — | ⚠️ Pendiente |

Sender en todas las cuentas SQB: **Luis Vilchis**

### 🔴 Bugs Críticos Corregidos en 2026-03-13
| # | Bug | Archivo | Fix Aplicado |
|---|---|---|---|
| 1 | `run_bot()` no existía → ImportError silencioso | telegram_bot.py | Función agregada |
| 2 | Sin MessageHandler para texto libre | telegram_bot.py | Handler agregado |
| 3 | `loop.add_signal_handler()` falla en Windows | start_monitor.py | Guard `sys.platform != "win32"` |
| 4 | `UnicodeEncodeError` en consola Windows | start_monitor.py | Lanzar con `-X utf8` |
| 5 | Claude Haiku devuelve JSON en ```json fences | telegram_bot.py | Strip de backticks |
| 6 | Actor Apify hardcodeado como 404 | config.py | Cambiado a `nwua9Gu5YrADL7ZDj` |
| 7 | `_get_dataset_items` retornaba None | apify_scraper.py | `return items or []` |
| 8 | Anymail para TODOS los negocios (muy lento) | pipeline.py | Skip si sin sitio_web |
| 9 | `AnymailResult()` con kwarg inválido | pipeline.py | Cambiado a `route_used="skip"` |
| 10 | Tabla `leads_master` con schema incorrecto | Supabase | Tabla recreada desde cero |
| 11 | Timeout Apify = 3 min (runs tardan 4-15 min) | apify_scraper.py | Aumentado a 12 min |
| 12 | Bot reportaba 0 leads aunque Apify tenía datos | pipeline.py + apify_scraper.py | Fix timeout + tool recuperación |

---

## ❌ PENDIENTES IMPORTANTES

### Alta Prioridad
1. **Crear campaña SQB en Instantly** — CSV listo en Downloads, subir cuando pipeline llegue a 400+ válidos
2. **Crear campaña LuPront** — 656 emails válidos listos, solo falta crear campaña + subir leads
3. **Crear campaña Macrisa** — 625 emails válidos listos, ídem
4. **Automatizar pipeline sin presencia del usuario** — ver sección de automatización abajo
5. **Reconectar emails Regio Cribas/LuPront en Instantly** — dominios IONOS renovados, pendiente importar
6. **Actualizar API Instantly a v2** — el endpoint `campaign/analytics/overview` da 404 en v1
7. **Crear tabla `search_history`** en Supabase — evitar duplicados en Apify

### Media Prioridad
8. **Conectar `denue_enricher.py` al pipeline** — verificar que las funciones `sb_get_leads_sin_email()` y `run_enrichment()` existan y sean compatibles
9. **Migrar Instantly a v2** — actualizar `instantly_manager.py` para usar `Bearer token` en header en vez de `api_key` en query param
10. **Buscar leads Malla Cribas** — términos correctos: `pedreras`, `areneras`, `canteras`, `graveras`, `arena y grava` (un estado a la vez)
11. **Crear tabla `clientes`** en Supabase e insertar los 5 clientes
12. **Migrar webhook a Mac Mini** — configurar con IP fija (en vez de ngrok) cuando se migre

### Baja Prioridad
13. **`.env.example`** — todavía referencia actor viejo `compass/crawler-google-places`
14. **MacMini migration** — archivos listos en `C:\Users\Dell\Documents\CLAUDE DESKTOP\MacMini\`
15. **`INSTANTLY_WEBHOOK_SECRET`** — configurar en `.env` para asegurar HMAC (actualmente sin firma)
16. **MailerSend como plataforma alternativa** — más barato que Instantly ($25 vs $97/mes). Pendiente crear `mailersend_manager.py` + `campaign_router.py`

---

## 👤 PERFIL DEL OPERADOR

**Zenon** — Dueño y operador del sistema LeadForge
- Es el "master" del bot ZenonFinder (`TELEGRAM_MASTER_CHAT_ID`)
- `CLIENTE_ID` en Supabase: `d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99`
- Opera en México, enfocado en generación de leads B2B
- Trabaja en Windows 11 (laptop Dell), planes de migrar a MacMini
- Maneja múltiples proyectos: MACRISA, RC (Regio Cribas), ZenonFinder
- Delega la implementación técnica a Claude Code

---

## 🗂️ OTROS PROYECTOS RELACIONADOS

### Excel_Apify Tool
- **Ruta:** `C:\Users\Dell\Documents\CLAUDE DESKTOP\Excel_Apify\`
- **Propósito:** Sistema separado para enriquecer listas Excel con datos de Apify
- **Estado:** En desarrollo

### MacMini Migration
- **Ruta:** `C:\Users\Dell\Documents\CLAUDE DESKTOP\MacMini\`
- **Propósito:** Migrar el bot de Windows a MacMini (más estable, siempre encendido)
- **Estado:** Archivos preparados, ver `LEER_PRIMERO.md` y `setup_macos.sh`

### MACRISA Enrichment
- **Tabla Supabase:** `lista_general_enriched`
- **Registros pendientes:** 1,809
- **Bloqueado por:** Límite Apify $45 alcanzado

### Regio Cribas (RC) Enrichment
- **Tabla Supabase:** `regio_cribas_enriched` (pendiente crear)
- **SQL:** `setup_supabase_regio_cribas.sql`
- **Registros pendientes:** 2,832

---

## 🖥️ GOODMAN WEBPAGE — DASHBOARD LEADS INSTANTLY

**Proyecto web:** `C:\Users\Dell\CascadeProjects\Godman_Webpage\Godman_Webpage`
**Stack:** React 18 + TypeScript + Vite + Tailwind CSS + Shadcn/UI + Recharts
**Dev server:** `npm run dev` → `http://localhost:5173`
**Supabase:** ✅ Conectado — mismo proyecto que LeadForge (`pfurkonwbjfmxpfogdtr.supabase.co`)

### Rutas del módulo Leads Instantly

| Ruta | Archivo | Descripción |
|---|---|---|
| `/leads-instantly` | `LeadsInstantlyLanding.tsx` | Landing pública — hero, features, how-it-works, 5 clientes, CTA |
| `/leads_instantly` | `LeadsInstantlyLogin.tsx` | Login privado (mismas credenciales que /leads) |
| `/leads_instantly/select-empresa` | `LeadsInstantlySelectEmpresa.tsx` | **Pantalla post-login** — selección de empresa cliente |
| `/leads_instantly/dashboard` | `LeadsInstantlyDashboard.tsx` | Dashboard completo con 4 tabs |

### Credenciales de acceso

```
Email:    vilchiszeluis@gmail.com
Password: Pineapplegoat2026
```
Auth guardada en `sessionStorage['leadsAuth'] = 'true'`
Empresa seleccionada en `sessionStorage['leadsEmpresa']`

### Flujo de navegación completo

```
/leads-instantly          ← Landing pública (botón "Comenzar aquí")
       ↓
/leads_instantly          ← Login
       ↓ autenticación exitosa
/leads_instantly/select-empresa   ← Seleccionar empresa
       ↓ clic en tarjeta de empresa
/leads_instantly/dashboard        ← Dashboard pre-filtrado por empresa
```

### Dashboard — Tabs y funcionalidades

| Tab | Contenido |
|---|---|
| **Resumen** | 8 KPI cards, embudo ventas (bar), gráfica 7 días (4 líneas), leads por cliente (bar), últimas respuestas, actividad reciente |
| **Leads** | Tabla completa con búsqueda, filtros etapa/empresa, badge score, exportar |
| **Campañas** | 4 KPI cards, tarjetas por campaña con progress bars, gráfica comparativa |
| **Sistema** | Estado 8 servicios, cuentas de envío (warmup), tracker de costo Apify, historial runs |

### Conexión a Supabase (cliente REST sin dependencia extra)

**Archivo:** `src/lib/supabase.ts`
**Método:** `fetch()` nativo con headers PostgREST (sin `@supabase/supabase-js`)
**Funciones:**
- `sbQuery<T>(table, qs)` — fetch con query string
- `sbCount(table, qs)` — cuenta registros (Content-Range header)
- `fetchDashboardStats()` — 5 métricas en paralelo
- `fetchEmbudoData()` — conteo por etapa
- `fetchUltimasRespuestas(n)` — últimas respuestas
- `fetchLeadsTabla(n)` — últimos N leads

**Variables .env del proyecto web:**
```
VITE_SUPABASE_URL=https://pfurkonwbjfmxpfogdtr.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGci...
```

**Estado de conexión en top bar:**
- `⟳ sync` (cargando) → `● HH:MM` verde (datos reales) → `✗ mock` rojo (error)

**⚠️ RLS:** Si `leads_master` tiene Row Level Security, ejecutar en Supabase SQL Editor:
```sql
CREATE POLICY "dashboard_anon_read" ON leads_master
  FOR SELECT TO anon USING (true);
```

### Filtros disponibles

- **Empresa/cliente** — dropdown (Regio Cribas, SQB, LuPront, Goodman Tech, Focus/ESG, Todos)
- **Campaña** — dropdown (se auto-sincroniza con empresa)
- **Período / fecha** — popover con 6 presets + rango personalizado con `<input type="date">`
- **Badge filtro activo** — muestra filtro aplicado con botón ✕ para limpiar

### Gráfica de tendencia — 4 líneas

| Línea | Color | Datos |
|---|---|---|
| Leads generados | Azul `#2463eb` | Nuevos leads scrapeados |
| Emails enviados | Naranja `#f97316` | Enviados (Instantly.ai) — trazo punteado |
| Abiertos | Amarillo `#FACC15` | Emails abiertos por prospecto |
| Respondidos | Verde `#22c55e` | Respuestas recibidas — trazo punteado |

Datos por período: Hoy (por hora), 7d (diario), 14d (diario), 30d (semanal), Todo

### Pantalla Selección de Empresa

Aparece justo después del login. Muestra tarjetas para cada empresa cliente con:
- Ícono temático, nombre, descripción, industria
- Badge de estado (activa / pausada / pendiente)
- Contador de leads y campañas activas
- Tarjeta especial "Vista Global" (Admin) para ver todo sin filtro

### Modal Crear Nueva Empresa

Accesible desde botón amarillo "+ Nueva Empresa" en el top bar.
Campos del formulario:
- Nombre empresa (requerido), Contacto principal, Email, Teléfono
- Ciudad objetivo, Industria objetivo
- Servicio SaaS contratado (select), Plan (Básico / Profesional / Enterprise)
- Presupuesto mensual (MXN), Palabras clave para Apify (comma-separated)
- Notas adicionales

> **Guardado:** `console.log` por ahora — POST a Supabase tabla `clientes_saas` pendiente crear

### Paleta de colores del dashboard

```
BLUE   = '#2463eb'    ← azul principal
YELLOW = '#FACC15'    ← amarillo / acento
DARK   = '#0F172A'    ← fondo oscuro
CARD   = '#1e293b'    ← cards
DARKER = '#0f172a'    ← tooltips / backgrounds internos
```

### Fonts y CSS externos

```html
<!-- Google Fonts -->
Plus Jakarta Sans (headings, KPI values)
Inter (body text)
Material Symbols Outlined (iconos: location_on, mail, send, etc.)
```

---

## 🏢 CLIENTES DEL SISTEMA

| Cliente ID | Empresa | Producto / Servicio | Años | Target Principal |
|---|---|---|---|---|
| Regio_Cribas | Regio Cribas S.A. de C.V. | Mallas y cribas de alambre (fabricante directo) | 86 | Minería, alimentos, porcicultura, automotriz, construcción |
| Le_Pront | LuPront / Pinturas Lupront | Pinturas industriales y arquitectónicas (30-40% más barato que Berel/Comex, secado 3 min) | — | Constructoras, mantenimiento industrial, ferreterías, pintores, albercas |
| SQB | Soluciones Químicas Biodegradables | Limpieza industrial + químicos biodegradables (Patente US 11,555,126 B2, PEMEX validado) | 40+ | Petroquímica, manufactura, alimentos, flotas |
| Goodman_Tech | Goodman Tech (empresa de Zenon) | Automatización con IA para PyMEs — Claude + n8n + Make + Instantly | — | PyMEs con equipos de ventas, sin presencia digital, gastando en ads sin conversión |
| Focus | ESG Consultores / Focus Coach & Consulting | Consultoría sostenibilidad ESG (doble cert GRI+IASE, STPS deducible, ticket $35,000+ MXN) | — | Manufactura exportadora, PyMEs que quieren entrar a cadenas de suministro globales |

> Nota: Goodman Tech ES la empresa de Zenon/Coyo. Regio Cribas aparece también como cliente prueba social de Goodman Tech.

---

## 📧 FASE 2 — SISTEMA DE CAMPAÑAS (EN DESARROLLO)

### Arquitectura General

| Componente | Descripción |
|---|---|
| Tabla `clientes` en Supabase | Perfiles completos de los 5 clientes (propuesta de valor, diferenciadores, tono, firma) |
| `campaign_launcher.py` | Filtra leads de `leads_master` por cliente, genera email personalizado con Claude API, sube lead a Instantly.ai |
| Webhook handler | Recibe eventos de Instantly.ai y actualiza el campo `etapa` en `leads_master` |
| Alerta Telegram | Notifica a Zenon cuando un prospecto responde |

### Flujo de Campaña

```
1. Filtrar leads_master por cliente y categorías afines
2. Claude API genera email personalizado (basado en perfil Google Maps del lead)
3. Agregar lead a campaña Instantly.ai via API
4. Instantly maneja la secuencia:
   → Email 1 (día 0): contacto inicial personalizado con datos del perfil Google Maps
   → Email 2 (día 3): follow-up si no respondió
5. Webhook Instantly → Python actualiza leads_master.etapa
6. Si responde → alerta Telegram a Zenon
```

> **Decisión de arquitectura:** Instantly.ai maneja la secuencia de emails (NO un scheduler Python propio).
> Razón: Instantly fue diseñado para esto — más simple, confiable y con mejor deliverability.

### 📨 Cuentas de Envío Configuradas en Instantly.ai

| Cuenta | Uso asignado |
|---|---|
| vilchiszeluis@gmail.com | Envío general / Goodman Tech |
| luisvilchisze@gmail.com | Envío general / rotación |
| ia-ingenieria22@gmail.com | Campañas IA / automatización |
| esg.mexico.mx@gmail.com | Campañas ESG / Focus |

> ⚠️ Gmail tiene límite de ~100-150 emails/día por cuenta con warm-up activo en Instantly.
> Con 4 cuentas = hasta ~500 emails/día en régimen de crucero (después de 30 días warm-up).

---

## 🗄️ TABLA CLIENTES (PENDIENTE CREAR)

```sql
CREATE TABLE clientes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre          TEXT NOT NULL UNIQUE,
  razon_social    TEXT,
  industria       TEXT,
  propuesta_valor TEXT,
  diferenciadores TEXT,
  categorias_lead TEXT[],
  tono_email      TEXT DEFAULT 'profesional',
  firma_email     TEXT,
  instantly_campaign_id TEXT,
  activo          BOOLEAN DEFAULT TRUE,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Clientes iniciales a insertar: `Regio_Cribas`, `Le_Pront`, `SQB`, `Goodman_Tech`, `Focus`

---

## 💡 PARA INICIAR UNA NUEVA SESIÓN CON CLAUDE

```
Estoy trabajando en el proyecto LeadForge / ZenonFinder.
Es un bot de Telegram para generación de leads B2B en México.
Lee el archivo CONTEXT.md (o SESION_CONTEXTO_2026-03-13.md) para el contexto completo.

El proyecto está en:
C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\

El bot se lanza con:
Start-Process -FilePath 'venv\Scripts\python.exe' -ArgumentList '-X','utf8','start_monitor.py' -WorkingDirectory 'C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly' -WindowStyle Normal

Lo que necesito ahora: [DESCRIBE TU TAREA]
```

---

*Para ver el historial completo de cambios, consultar BITACORA.md*
## 🔑 DENUE (INEGI)

**API Key:** `YOUR_DENUE_API_KEY`
**Variable .env:** `DENUE_API_KEY`
**Propósito:** Directorio Estadístico Nacional de Unidades Económicas — datos oficiales de negocios mexicanos con coordenadas, emails y teléfonos
**Estado:** API key activa. Endpoints documentados devuelven 404. Pendiente verificar URL correcta.
**Uso esperado:**
- Enriquecer leads de Supabase sin email (buscar por coordenadas + categoría)
- Validar datos de Apify contra registros INEGI
- `denue_enricher.py` — script listo, pendiente verificar conexión API

## 🗺️ REGLAS DE BÚSQUEDA EN TELEGRAM (aprendidas en producción)

### Regla 1 — Un estado a la vez
```
❌ quiero 60 graveras en Nuevo León Coahuila Tamaulipas
✅ quiero 30 graveras en Nuevo León
✅ quiero 30 graveras en Coahuila
```
Multi-estado causa LOCATION NOT FOUND en Apify.

### Regla 2 — Términos correctos para Google Maps
Usar el nombre como el dueño del negocio se describe en Google Maps (coloquial), no el término técnico:
```
❌ trituradoras de piedra   → 0 resultados
❌ bancos de materiales     → ferreterías/tlapalerías (target incorrecto)
✅ pedreras                 → 54-70 resultados
✅ canteras                 → funcionó en Coahuila
✅ areneras                 → extracción de arena
✅ graveras                 → extracción de grava
✅ arena y grava            → término coloquial que sí usan
```

### Regla 3 — Target correcto para Malla Cribas (Regio Cribas)
Negocios que COMPRAN malla cribas (la consumen en proceso productivo):
- pedreras, areneras, canteras, graveras, arena y grava
- agregados pétreos, material pétreo
- plantas de concreto/block (consumen agregados cribados)
- NOT: bancos de materiales (son ferreterías/tlapalerías)
- NOT: trituradoras de piedra (término no usado en Google Maps MX)

## 📊 CAMPAÑAS INSTANTLY.AI (estado 2026-03-16)

| Campaña | ID | Estado API |
|---|---|---|
| Regio Cribas | `ed81e355-716e-4a12-9175-9ae241e2ec05` | ⚠️ Solo list funciona (v1) |
| Pinturas Leprom | `58351f41-d23a-4f49-9629-52b0cd52e899` | ⚠️ Solo list funciona (v1) |
| Limpieza de Cocinas / Damas | `287a4cb7-e59a-4668-97f1-e5824f3835b7` | ⚠️ Solo list funciona (v1) |
| Limpieza | `c345507c-bfae-4f90-bb19-aded659ec9f5` | ⚠️ Solo list funciona (v1) |

**Problema:** Instantly migró a API v2. El endpoint `campaign/analytics/overview` da 404 en v1.
**Fix pendiente:** Crear nueva API key v2 en `app.instantly.ai → Settings → API Keys`

### Leads disponibles para Regio Cribas
- Total con email sin asignar a campaña: **330**
- Relevantes para Malla Cribas (pedreras/canteras/arena): **~23**
- Baserow import sin clasificar: **260** (categoría desconocida)
- **Acción requerida:** Buscar más leads mining antes de lanzar campaña

---

## 🤖 AUTOMATIZACIÓN SIN PRESENCIA DEL USUARIO

### Archivos clave
| Archivo | Propósito |
|---|---|
| `sqb_pipeline.py` | Pipeline DENUE→AMF→Export completamente autónomo |
| `start_zenonbot.bat` | Auto-reinicio del bot si cae |
| `instalar_autostart.ps1` | Registra bot en Windows Task Scheduler |

### Opciones para correr sin presencia (propuestas)

**Opción 1 — Windows Task Scheduler (ya tienes la base)**
```powershell
# Agregar tarea para sqb_pipeline.py diariamente a las 2am
schtasks /create /tn "SQB_Pipeline" /tr "venv\Scripts\python.exe sqb_pipeline.py" /sc daily /st 02:00
```
Ventaja: sin costo adicional. Requiere que la laptop esté encendida.

**Opción 2 — APScheduler dentro del monitor (recomendado)**
Agregar en `health_checker.py` un job diario que llame `sqb_pipeline.py`:
```python
scheduler.add_job(run_sqb_pipeline, trigger="cron", hour=2, minute=0)
```
Ventaja: corre junto con el bot, misma infraestructura. Sin configuración extra.

**Opción 3 — Mac Mini (ideal largo plazo)**
Migrar el bot + pipeline a Mac Mini siempre encendido.
Archivos de migración ya están en `C:\Users\Dell\Documents\CLAUDE DESKTOP\MacMini\`

**Opción 4 — Railway / Render (cloud, sin laptop)**
Deploy del pipeline como worker en Railway ($5/mes).
Requiere dockerizar `sqb_pipeline.py` — Dockerfile ya existe en el proyecto.

### Flujo ideal automatizado (meta)
```
2:00am → DENUE scraping (nuevos estados/sectores)
3:00am → AMF verification (rondas automáticas hasta meta)
4:00am → Export CSV + notificación Telegram con link
8:00am → Reporte diario con métricas
```

---

*Última actualización: 2026-03-18 CST*
