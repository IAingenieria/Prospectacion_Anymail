# 🚀 LeadForge / ZenonFinder — Contexto Maestro del Proyecto

> **Proyecto:** Sistema automatizado de generación de leads B2B en México
> **Bot Telegram:** @ZenonFinder
> **Operador:** Gabriel (Zenon) — master del sistema
> **Stack:** Python 3.14 + Telegram Bot + Google Places API (4 keys) + DENUE/INEGI + Anymail Finder + Claude Haiku + Supabase + Brevo (pendiente)
> **Plataforma de producción:** Mac Mini `/Users/macmini/LeadForge/` (LaunchAgent con KeepAlive)
> **Última actualización:** 2026-04-18

---

## 📋 TABLA DE CONTENIDOS

1. [Infraestructura de Producción](#infraestructura-de-producción)
2. [Stack Tecnológico](#stack-tecnológico)
3. [Clientes Registrados](#clientes-registrados)
4. [Base de Datos Supabase](#base-de-datos-supabase)
5. [Diagrama de Flujo y Menús](#diagrama-de-flujo-y-menús)
6. [Comandos del Bot](#comandos-del-bot)
7. [Pipeline de Procesamiento](#pipeline-de-procesamiento)
8. [Categorías DENUE Disponibles](#categorías-denue-disponibles)
9. [AnymailFinder — Fases](#anymailfinder--fases)
10. [Estado Actual](#estado-actual-2026-03-24)
11. [Bugs Corregidos](#bugs-corregidos-historial)
12. [Pendientes](#pendientes)
13. [Perfil del Operador](#perfil-del-operador)

---

## 🖥️ INFRAESTRUCTURA DE PRODUCCIÓN

### Mac Mini (producción, siempre encendido)

```
Directorio: /Users/macmini/LeadForge/
Espejo:     /Users/macmini/Downloads/LeadForge/  ← mantener sincronizado
```

### LaunchAgent (auto-arranque)

```
~/Library/LaunchAgents/com.zenon.leadforge.plist
  KeepAlive = true   ← reinicia si el proceso muere
  StandardOut → /Users/macmini/LeadForge/logs/launchd.log
  StandardErr → /Users/macmini/LeadForge/logs/launchd_err.log
```

**Comandos de control:**
```bash
# Reiniciar bot limpio
launchctl unload ~/Library/LaunchAgents/com.zenon.leadforge.plist
kill $(lsof -ti :8001)
sleep 3
launchctl load ~/Library/LaunchAgents/com.zenon.leadforge.plist

# Ver logs en tiempo real
tail -f /Users/macmini/LeadForge/logs/launchd.log
tail -f /Users/macmini/LeadForge/logs/launchd_err.log

# Verificar proceso
pgrep -a -f "start_monitor"
lsof -i :8001 | grep LISTEN
```

> ⚠️ **REGLA CRÍTICA:** Siempre editar en `/Users/macmini/LeadForge/` y luego sincronizar:
> `rsync -a LeadForge/leadforge/ Downloads/LeadForge/leadforge/`

---

## 🔧 STACK TECNOLÓGICO

| Componente | Tecnología | Detalle |
|---|---|---|
| Lenguaje | Python 3.14 | venv en `LeadForge/venv/` |
| Bot Telegram | python-telegram-bot | @ZenonFinder |
| Scraping Google Maps | **Google Places API** (New) | 4 keys propias con rotación automática — reemplazó Apify |
| Scraping legado | Apify | Actor `nwua9Gu5YrADL7ZDj` ⚠️ bloqueado por facturas pendientes |
| Directorio oficial MX | DENUE/INEGI | API gratuita con token — datos oficiales |
| Emails corporativos | Anymail Finder | API REST — ~17,587 créditos disponibles (2026-04-15) |
| IA / Parseo NL | Claude Haiku | `claude-haiku-4-5-20251001` |
| Base de datos | Supabase (PostgreSQL) | Proyecto "Generacion de Leads" |
| Email outreach (corporativo) | Instantly.ai | Dominios IONOS calentados — solo emails corporativos |
| Email outreach (personal) | **Brevo** | ⏳ Pendiente integrar — Gmail/Hotmail/Yahoo verificados |
| WhatsApp outreach | **YCloud** | ⏳ Pendiente — 511 leads con whatsapp_url recopilados |
| Monitoreo | APScheduler | Health checks cada 30 min |

---

## 👥 CLIENTES REGISTRADOS

Tabla `clientes` en Supabase — 5 clientes activos:

| cliente_id (primeros 8) | Nombre | Plan | Leads en DB |
|---|---|---|---|
| `d0542bc7` | Zenon — LeadForge Admin | agency | ~2,900 |
| `c7f3a2b1` | Soluciones Quimicas Biodegradables (SQB) | agency | ~10,400+ |
| `4610cd20` | Pinturas LePront | growth | 0 (nuevo) |
| `729c24ce` | Goodman Tech | growth | 0 (nuevo) |
| `9024baa2` | Focus Coach | starter | 0 (nuevo) |

> `b8e2f4d6` — cliente sin nombre en tabla (datos históricos, ~6,641 leads en leads_master)

**Selector de cliente:** Todos los comandos de búsqueda muestran InlineKeyboard para elegir
el cliente antes de ejecutar. Los leads quedan asociados al cliente seleccionado.

---

## 🗄️ BASE DE DATOS SUPABASE

### Tabla Principal: `leads_master` (~24,000 leads totales al 2026-04-18)

```sql
CREATE TABLE leads_master (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id        UUID NOT NULL,
  nombre_negocio    TEXT NOT NULL,
  categoria         TEXT,
  ciudad            TEXT,
  estado            TEXT,
  pais              TEXT DEFAULT 'MX',
  direccion         TEXT,
  sitio_web         TEXT,
  telefono          TEXT,
  facebook_url      TEXT,
  instagram_url     TEXT,
  whatsapp_url      TEXT,           -- ⭐ 2026-04-18: agregado para integración YCloud
  rating            NUMERIC(3,1),
  review_count      INTEGER DEFAULT 0,
  google_maps_url   TEXT,
  apify_run_id      TEXT,
  termino_busqueda  TEXT,
  email             TEXT,
  email_status      TEXT,          -- 'valid' | 'catch_all' | 'unverified' | 'invalid'
  hierarchy_score   INTEGER DEFAULT 0,
  anymail_procesado BOOLEAN DEFAULT FALSE,
  verificado        BOOLEAN DEFAULT FALSE,
  owner_name        TEXT,
  cargo_inferido    TEXT,
  lead_score        INTEGER DEFAULT 0,
  canal_recomendado TEXT,
  calidad_stars     INTEGER DEFAULT 1,
  etapa             TEXT DEFAULT 'nuevo',
  ...
);
CREATE UNIQUE INDEX lm_dedup ON leads_master(nombre_negocio, ciudad, cliente_id);
```

### Estado de la BD (2026-04-18)

| Métrica | Valor |
|---------|-------|
| Total leads | **~24,000** |
| Con teléfono | ~11,000 |
| Con email | ~9,600 |
| **Email válido (campaign-ready)** | **~2,300** |
| Con Facebook | ~1,706 |
| Con Instagram | ~1,100 |
| Con WhatsApp | **511** |

### Estado de AnymailFinder (2026-04-18)

| Cliente | Total | Emails válidos |
|---|---|---|
| SQB | ~10,095 | ~1,279 |
| b8e2f4d6 | ~6,641 | ~356 |
| Zenon Admin + alimentos | ~6,628 | ~493 |
| **TOTAL** | **~23,364** | **~2,128** |

Créditos Anymail disponibles: ~17,300 (al 2026-04-18)

### Otras Tablas

| Tabla | Propósito |
|---|---|
| `clientes` | 5 clientes activos + api_key_hash |
| `email_leads` | Tabla legacy (32,830 filas, `email_status='unverified'`) |
| `busquedas_cache` | Caché Apify para evitar pagos duplicados |
| `social_leads` | Tabla legacy |
| `alertas` | Alertas del sistema |

---

## 🗺️ DIAGRAMA DE FLUJO Y MENÚS

```mermaid
flowchart TD
    USER([👤 Usuario en Telegram])

    USER -->|Texto libre| NL[handle_free_text\nZenonFinder NLP]
    USER -->|/denue estado cat| DENUE_CMD[cmd_denue]
    USER -->|/agregar cat ciudad| AGREGAR_CMD[cmd_agregar]
    USER -->|/anymailfinder| AMF_CMD[cmd_anymailfinder]
    USER -->|/anymailfinder N| AMF_DIRECT[Lanza directo\nmax_leads=N]
    USER -->|/accion| ACCION_CMD[cmd_accion]
    USER -->|/status /leads /creditos| INFO_CMDS[Comandos info\nsin selector]

    %% ZenonFinder natural language flow
    NL --> CLAUDE{Claude Haiku\nparse_finder_intent}
    CLAUDE -->|es_busqueda=true| EXPAND[expand_search_terms\n7-9 categorías]
    EXPAND --> CONFIRM_NL[Muestra resumen\n¿Confirmas? /si · /no]
    CONFIRM_NL -->|/si| SELECTOR_ZF[🔘 Selector de Cliente\nInlineKeyboard]

    %% /denue flow
    DENUE_CMD --> PARSE_DENUE[Parsea estado + categoría\nGuarda en user_data]
    PARSE_DENUE --> SELECTOR_DN[🔘 Selector de Cliente\nInlineKeyboard]

    %% /agregar flow
    AGREGAR_CMD --> PARSE_AGR[Parsea categoría + ciudad\nGuarda en user_data]
    PARSE_AGR --> SELECTOR_AG[🔘 Selector de Cliente\nInlineKeyboard]

    %% Client selector (shared component)
    SELECTOR_ZF --> CLIENT_CHOICE{Elige cliente}
    SELECTOR_DN --> CLIENT_CHOICE
    SELECTOR_AG --> CLIENT_CHOICE

    CLIENT_CHOICE -->|SQB| RUN_PIPELINE_SQB[run_pipeline\nclient=SQB]
    CLIENT_CHOICE -->|LePront| RUN_PIPELINE_LP[run_pipeline\nclient=LePront]
    CLIENT_CHOICE -->|Goodman| RUN_PIPELINE_GM[run_pipeline\nclient=Goodman]
    CLIENT_CHOICE -->|Focus| RUN_PIPELINE_FC[run_pipeline\nclient=Focus]
    CLIENT_CHOICE -->|Zenon Admin| RUN_PIPELINE_ZN[run_pipeline\nclient=Zenon]
    CLIENT_CHOICE -->|❌ Cancelar| CANCEL[Cancelado]

    %% Pipeline execution
    RUN_PIPELINE_SQB --> PIPELINE[⚙️ pipeline.py\nrun_pipeline]
    RUN_PIPELINE_LP --> PIPELINE
    RUN_PIPELINE_GM --> PIPELINE
    RUN_PIPELINE_FC --> PIPELINE
    RUN_PIPELINE_ZN --> PIPELINE

    PIPELINE --> APIFY{Apify\ndisponible?}
    APIFY -->|Sí| GMAPS[Google Maps\nScraping]
    APIFY -->|No - billing| DENUE_ONLY[Solo DENUE]
    GMAPS --> DENUE_ENRICH[DENUE/INEGI\nEnriquecimiento]
    DENUE_ONLY --> DENUE_ENRICH
    DENUE_ENRICH --> INSERT_LEADS[(leads_master\nUPSERT)]
    INSERT_LEADS --> NOTIFY_DONE[✅ Notificación\ncompleted]

    %% /accion flow
    ACCION_CMD --> STATS[get_leads_stats\npor cliente_id]
    STATS --> ACCION_PANEL[📊 Panel: total · web · email\nverificados · 5★ · pendientes]
    ACCION_PANEL --> ACCION_KB{InlineKeyboard}
    ACCION_KB -->|📧 AnymailFinder| RUN_AMF_BG[_run_anymailfinder_full\nen background]
    ACCION_KB -->|📥 Exportar CSV| EXPORT_CSV[_run_accion_exportar\nSend document]
    ACCION_KB -->|⭐ Calidad| QUALITY[Distribución\nde estrellas]
    ACCION_KB -->|❌ Cancelar| CANCEL

    %% /anymailfinder flow
    AMF_CMD --> AMF_STATS[get_anymail_stats_por_cliente\nTodos los clientes]
    AMF_STATS --> AMF_TABLE[📊 Tabla por cliente\nprocesados · pendientes · válidos]
    AMF_TABLE --> AMF_KB{InlineKeyboard}
    AMF_KB -->|▶️ Procesar [Cliente]| RUN_AMF_BG
    AMF_KB -->|🚀 Procesar TODOS| RUN_ALL_CLIENTS[Loop por cliente\nasyncio.create_task × N]
    AMF_KB -->|❌ Cancelar| CANCEL

    %% /anymailfinder N (direct)
    AMF_DIRECT --> RUN_AMF_BG

    %% AnymailFinder background execution
    RUN_AMF_BG --> AMF_CHECK[check_account_status\ncreditos_inicio]
    AMF_CHECK --> LOAD_F1[Fase 1: leads con sitio_web\nverificado=False\nlimit=10,000]
    LOAD_F1 --> LOAD_F2[Fase 2: leads con email DENUE\nsin web · anymail_procesado=False\nlimit=10,000]
    LOAD_F2 --> APPLY_CAP{max_leads\nparámetro?}
    APPLY_CAP -->|Sí| TRUNCATE[fase1 = fase1:max_leads\nfase2 = fase2:resto]
    APPLY_CAP -->|No| BATCH_F1
    TRUNCATE --> BATCH_F1

    BATCH_F1[Fase 1 en lotes de 300\nasyncio.gather] --> CHECK_CREDITS{Créditos\n< 300?}
    CHECK_CREDITS -->|Sí| PAUSE_MSG[⚠️ Créditos insuficientes\nMensaje de pausa]
    CHECK_CREDITS -->|No + no último lote| PROGRESS_F1[📊 Progreso intermedio\nTelegram] --> BATCH_F1
    CHECK_CREDITS -->|No + último lote F1| BATCH_F2[Fase 2 en lotes de 300]

    BATCH_F2 --> CHECK_CREDITS2{Créditos\n< 300?}
    CHECK_CREDITS2 -->|Sí| PAUSE_MSG
    CHECK_CREDITS2 -->|No + no último lote| PROGRESS_F2[📊 Progreso intermedio] --> BATCH_F2
    CHECK_CREDITS2 -->|No + último lote| FINAL_REPORT[✅ Resumen final\nCliente · F1 · F2 · créditos usados]
```

---

## 🤖 COMANDOS DEL BOT

### Comandos de Búsqueda (todos muestran selector de cliente)

| Comando | Descripción | Flujo |
|---|---|---|
| Texto libre | ZenonFinder NLP — Claude Haiku interpreta | NL → `/si` → selector → pipeline |
| `/denue [estado] [cat]` | Ingesta DENUE/INEGI por sector | args → selector → DENUE API |
| `/agregar [cat] [ciudad]` | Búsqueda Google Maps vía Apify | args → selector → pipeline |

### Comandos de Gestión de Leads

| Comando | Descripción |
|---|---|
| `/accion` | Panel stats + botones: AnymailFinder, Exportar CSV, Calidad |
| `/anymailfinder` | Tabla por cliente + botones procesamiento |
| `/anymailfinder [N]` | Lanza directamente con límite N (ej: `/anymailfinder 4000`) |
| `/calidad` | Distribución de calidad ⭐ en la DB |
| `/verificar_mineria [n]` | Verificar emails de leads mineros (legacy) |
| `/enriquecer [n]` | Enriquecer leads existentes con DENUE |

### Comandos de Monitoreo

| Comando | Descripción |
|---|---|
| `/status` | Estado de todos los servicios (Anymail, Apify, Instantly, Supabase) |
| `/leads` | Stats leads hoy/7 días |
| `/creditos` | Créditos Anymail Finder disponibles |
| `/clientes` | Lista de clientes activos con plan |
| `/respuestas` | Emails que respondieron |
| `/reporte` | Reporte semanal |
| `/pipeline [sqb|lp|mac] [apify|full]` | Pipelines predefinidos por cliente |
| `/ayuda` | Lista completa de comandos |

### Comandos de Confirmación ZenonFinder

| Comando | Descripción |
|---|---|
| `/si` | Confirma búsqueda → abre selector de cliente |
| `/no` | Cancela búsqueda pendiente |

---

## ⚙️ PIPELINE DE PROCESAMIENTO

```
run_pipeline(terminos, location, cliente_id, max_places)
      ↓
check_search_cache()  → REUSE / SCRAPE
      ↓ (SCRAPE)
ApifyScraper.scrape_multi_term()
  → POST /v2/acts/{id}/runs
  → poll cada 5s, timeout 12 min
  → _parse_item() → NegocioRaw[]
      ↓ (si Apify falla → 403 "Too many outstanding invoices")
DenueEnricher.ingestar_sector()  ← DENUE como fallback y fuente primaria
  → GET BuscarEntidad/{termino}/{entidad}/{start}/{end}/{token}
  → Pagina de 50 en 50 hasta agotar resultados
      ↓
Para cada negocio:
  1. extract_owner_from_reviews()
  2. if sitio_web → anymail.enrich_negocio()  ← SOLO si tiene web
  3. calculate_lead_score() → 0-100
  4. insert_lead_master() → UPSERT (nombre_negocio, ciudad, cliente_id)
      ↓
save_search_cache()
      ↓
PipelineStats → send_telegram() con resumen
```

**Optimización clave:** Anymail solo se llama si el negocio tiene `sitio_web`.
Sin dominio = sin email posible = skip. Reduce tiempo 5 min → 1-2 min.

---

## 🏭 CATEGORÍAS DENUE DISPONIBLES

Uso: `/denue [estado] [categoría]`

| Clave | Label | SCIAN | Descripción |
|---|---|---|---|
| `mineria` | Minería | 21/212/2123 | canteras, areneras, pedreras, graveras |
| `constructoras` | Construcción | 23 | constructoras, desarrolladoras |
| `ferreterias` | Ferreterías | 46/467/4671 | ferreterías, tlapalerías, materiales |
| `mantenimiento` | Mantenimiento Industrial | 81 | mantenimiento industrial, pintura industrial |
| `albercas` | Albercas | — | albercas, piscinas |
| `arquitectos` | Arquitectos | 54/541/5413 | arquitectos, diseñadores |
| `hoteles` | Hoteles/Restaurantes | 72/721 | hoteles, restaurantes |
| `molinera` | Alimentos/Molineras | 31/311 | molineras, arroceras |
| `porcicultura` | Porcicultura | 11/114 | granjas porcinas |
| `automotriz` | Automotriz | 45/441 | agencias, distribuidoras |
| `cnc` | Maquinado CNC | 33/332 | talleres CNC, maquinados |
| `alimentos` | Alimentos | 31 | plantas de alimentos |
| `flotas` | Flotas/Transporte | 48/484 | empresas de transporte |
| `agregados` | Agregados Pétreos | 23/2371 | plantas de concreto, block |
| `recicladora` | Recicladoras | 38/383 | reciclaje industrial |
| `fundidora` | Fundidoras | 33/331 | fundidoras de metal |
| `pintores` | Pintores/Despachos | 23/238 | pintores industriales |
| `pinturas` | Pinturas/Recubrimientos | 44/444 | distribuidores de pintura |
| `condominios` | Condominios | 53/531 | administradoras de condominios |
| `parques_industriales` | Parques Industriales ⭐ NEW | 53/531 | parques, zonas, corredores industriales |
| `manufactura` | Manufactura ⭐ NEW | 31 | maquiladoras, plantas industriales |
| `quimica` | Química/Laboratorios ⭐ NEW | 32/325 | empresas químicas, limpieza industrial |

**Estados soportados:** todos los 32 estados de México (nombre completo o abreviatura).

---

## 📧 ANYMAILFINDER — FASES

### Fase 1: Búsqueda por página web
- Leads con `sitio_web IS NOT NULL` y `verificado = FALSE`
- Llama `anymail.enrich_negocio()` — busca emails en el dominio
- Guarda el mejor email con `email_status = 'valid'`

### Fase 2: Verificación de emails DENUE
- Leads con `email IS NOT NULL`, `sitio_web IS NULL`, `anymail_procesado = FALSE`
- Llama `anymail.verify_email()` — verifica SMTP
- Confirma si es válido o lo marca como inválido

### Procesamiento en lotes
- **LOTE = 300** leads por lote
- Verifica créditos después de cada lote
- Envía progreso intermedio por Telegram
- Se detiene automáticamente si créditos < 300
- **Semaphore** = `cfg.anymail_concurrent_calls` (concurrencia limitada)

### Comandos de ejecución
```
/anymailfinder              → Menú por cliente con estadísticas
/anymailfinder 4000         → Lanza directo con límite de 4,000 leads
```

---

## 📊 ESTADO ACTUAL (2026-04-18)

### ✅ Funcionando

- Bot @ZenonFinder en Mac Mini — LaunchAgent KeepAlive
- **Google Places API** — reemplazó Apify como fuente de scraping (4 keys, KeyRotator)
- DENUE/INEGI — fuente primaria gratuita, siempre activa
- AnymailFinder — lotes de 300, progreso intermedio, ~17,300 créditos disponibles
- Selector de cliente en `/denue`, `/agregar`, `/si` (ZenonFinder)
- 5 clientes registrados en tabla `clientes`
- `/accion` — panel de stats + exportar CSV + calidad
- `/anymailfinder` — vista por cliente con botones individuales y "Procesar TODOS"
- Track de emails personales: `verify_personal_emails.py` + status `APROBADO_PERSONAL`
- `social_enricher.py` — extrae FB/IG/TikTok/WA/LinkedIn de sitios web (1,706 leads enriquecidos)
- `whatsapp_url` columna activa en `leads_master` — 511 números recopilados

### ⚠️ Pendiente / Bloqueado

- **Apify bloqueado** — facturas pendientes (ya no es crítico, Google Places lo reemplazó)
- **Google Keys 1 y 4** — activar billing en Google Cloud Console para goodmantech y esgconsultores
- **Brevo** — integrar `brevo_sender.py` para emails personales verificados (próximo paso)
- **YCloud WhatsApp** — registrar número Business, luego campañas con 511 contactos recopilados
- **Instantly campañas pendientes** — salones eventos (85 emails), alimentos (72 emails), LePront/Goodman/Focus

### 📊 Campañas Instantly.ai

| Campaña | Estado |
|---|---|
| SQB — Química Inteligente | 22 cuentas IONOS, 770 emails/día |
| Regio Cribas | Activa |
| Pinturas LePront | Activa |
| Limpieza / SQB | Activa |
| Salones de Eventos NL | ⏳ Pendiente — 85 emails válidos listos |
| Manufactura Alimentos NE/TAM/COAH | ⏳ Pendiente — 72 emails válidos listos |

---

## 🔧 HISTORIAL DE CAMBIOS EN CÓDIGO

> Documentación de todos los cambios implementados desde el commit inicial (2026-04-02).
> Ordenado por archivo, de más reciente a más antiguo.

---

### `social_enricher.py` (raíz del proyecto)
**Creado:** 2026-04-16 | **Fix crítico:** 2026-04-18

Script standalone para enriquecer `leads_master` con redes sociales scrapeando el sitio web de cada negocio.

**Funciones principales:**
```python
extract_social_from_html(html, base_url) -> SocialResult   # regex sobre HTML completo
fetch_website(url) -> (html, error)                         # GET con retry SSL→HTTP
get_leads_pendientes(sb, limite, cliente_id) -> list        # leads con web sin redes
update_lead_social(sb, lead_id, social) -> bool             # UPDATE en Supabase
procesar_leads(limite, cliente_id)                          # loop principal
```

**Patrones regex detectados:** `facebook.com`, `fb.com/me`, `instagram.com`, `instagr.am`, `tiktok.com/@`, `wa.me`, `api.whatsapp.com/send`, `linkedin.com/company`, `youtube.com/@`

**Fix 2026-04-18 — Bug crítico:** `to_dict()` no incluía `whatsapp_url` → los WhatsApp detectados se perdían sin error.

```python
# ANTES (bug silencioso):
def to_dict(self) -> dict:
    return {k: v for k, v in {
        "facebook_url":  self.facebook_url,
        "instagram_url": self.instagram_url,
    }.items() if v is not None}

# DESPUÉS (correcto):
def to_dict(self) -> dict:
    return {k: v for k, v in {
        "facebook_url":  self.facebook_url,
        "instagram_url": self.instagram_url,
        "whatsapp_url":  self.whatsapp_url,   # ← agregado
    }.items() if v is not None}
```

**Nota operativa:** Supabase limita queries a 1,000 filas → se necesitan múltiples runs en loop hasta tasa ~0%.

---

### `leadforge/google_places_scraper.py`
**Creado:** 2026-04-15 — reemplaza `apify_scraper.py` como fuente de scraping

**Clases:**

| Clase | Descripción |
|---|---|
| `NegocioRaw` | dataclass con campos: nombre, teléfono, sitio_web, facebook_url, instagram_url, rating, reviews_text, raw_data, tiene_email (property), tiene_telefono (property) |
| `KeyRotator` | Carga hasta 9 keys desde `.env` (`GOOGLE_KEY_1..9`). `get_key()` rota round-robin. `mark_exhausted(key)` la saca del pool. `status()` muestra conteos. |
| `GooglePlacesScraper` | Scraper principal. Llama a Places API New (`/v1/places:searchText`). Paginación con `nextPageToken`. Parsea dirección, teléfono, website, coordenadas, horarios. |

**Métodos clave:**
```python
check_credits() -> dict          # retorna {"ok": True} si hay keys activas
scrape_multi_term(                # acepta AMBAS firmas:
    location, max_places,         #   firma pipeline.py (Monterrey NL MX, 100)
    ciudad, estado, max_per_term  #   firma directa (Monterrey, NL, 12)
) -> list[NegocioRaw]
_scrape_term(term, location, ...)  # una búsqueda + paginación
_parse_place(place_dict) -> NegocioRaw  # extrae campos del JSON de Places API
```

**Bugs corregidos durante desarrollo:**
- `nextPageToken` en FieldMask tenía prefijo `places.` incorrecto → causa 400 INVALID_ARGUMENT → fix: campo top-level
- Error 403 causaba `break` (detenía loop) → fix: `mark_exhausted` + `continue` (rota a siguiente key)

**Alias de compatibilidad:**
```python
ApifyScraper = GooglePlacesScraper  # pipeline.py importa ApifyScraper
```

---

### `leadforge/pipeline.py`
**Modificado:** 2026-04-15

**Cambio principal — import del scraper:**
```python
# ANTES:
from .apify_scraper import ApifyScraper, NegocioRaw
# AHORA:
from .google_places_scraper import ApifyScraper, NegocioRaw
```

**Nuevos imports de supabase_client:**
```python
from .supabase_client import (
    ...
    update_lead_apify_data,        # enriquece lead DENUE con datos Apify
    get_leads_con_sitio_web,       # lista leads con sitio_web para Anymail
    update_lead_anymail_verificado,
    update_lead_score,
)
```

**`PipelineStats` refactorizado** — contadores anteriores eliminados, nuevos:

| Campo nuevo | Descripción |
|---|---|
| `denue_negocios` | Total leads traídos de DENUE |
| `denue_con_email` | De esos, cuántos traían email DENUE |
| `apify_nuevos` | Negocios Apify no presentes en DENUE |
| `apify_actualizados` | Leads DENUE enriquecidos con datos Apify |
| `apify_sin_creditos` | Bool — Apify falló por billing |
| `leads_verificados` | Leads con email válido confirmado por Anymail |
| `leads_5_estrellas` | Campaign-ready (calidad_stars = 5) |
| `total_insertados` | Total guardados en Supabase |

**Función renombrada:** `process_negocio` → `_insert_negocio`

---

### `leadforge/supabase_client.py`
**Modificado:** 2026-04-15

Funciones **nuevas** agregadas (no existían en commit inicial):

| Función | Descripción |
|---|---|
| `update_lead_apify_data(nombre, ciudad, cliente_id, facebook_url, instagram_url, rating, review_count, sitio_web_apify, telefono_apify, email_apify, apify_run_id)` | Enriquece un lead DENUE con datos de Apify/Google Places. Regla: redes sociales siempre se actualizan; sitio_web/teléfono/email solo si DENUE no los tenía. Cross-check de sitios web discrepantes al log. |
| `get_leads_con_sitio_web(cliente_id, limit)` | Leads con `sitio_web IS NOT NULL` y `verificado=False` — input para Anymail Fase 1 |
| `update_lead_anymail_verificado(nombre_negocio, ciudad, cliente_id, email, email_status, hierarchy_score, lead_score, calidad_stars, canal_recomendado)` | Marca `verificado=True`, guarda email y calidad. Dispara subida a Instantly si `calidad_stars >= 4`. |
| `update_lead_email_personal_verificado(lead_id, email, email_status, canal)` | Para emails personales (Gmail/Hotmail) verificados. Marca `verificado=True`, `canal_recomendado="brevo"`. |
| `update_lead_score(nombre_negocio, ciudad, cliente_id, lead_score, calidad_stars)` | Actualiza score numérico y clasificación en estrellas. |
| `get_leads_stats(cliente_id)` | Retorna dict: total, con_web, con_email, verificados, cinco_estrellas, con_web_sin_verificar |
| `get_all_pending_leads_anymail(cliente_id, limit=300)` | Fase 1: leads con sitio_web, `verificado=False` |
| `get_anymail_stats_por_cliente()` | Stats por cliente con paginación completa (evita límite 1,000 Supabase) |
| `get_leads_con_email_sin_verificar(cliente_id, limit=300)` | Fase 2: leads con email DENUE, sin sitio_web, `anymail_procesado=False` |

---

### `leadforge/validation_cascade.py`
**Modificado:** 2026-04-15

**Cambios:**

1. Nuevo estado en enum `ValidationStatus`:
```python
APROBADO_PERSONAL = "aprobado_personal"  # Gmail/Hotmail → canal Brevo (no Instantly)
```

2. Nuevo set de dominios personales:
```python
DOMINIOS_PERSONALES = {
    "gmail.com", "hotmail.com", "hotmail.com.mx",
    "yahoo.com", "yahoo.com.mx", "yahoo.es",
    "outlook.com", "outlook.com.mx",
    "live.com", "live.com.mx",
    "icloud.com", "me.com",
    "protonmail.com", "pm.me",
}
```

3. Nueva property en `ValidationResult`:
```python
@property
def es_apto_para_brevo(self) -> bool:
    return self.status == ValidationStatus.APROBADO_PERSONAL
```

4. **Nivel 2.5** en cascada de validación (entre niveles 2 y 3):
   - Si el dominio del email está en `DOMINIOS_PERSONALES` → `APROBADO_PERSONAL`
   - No pasa por Anymail Finder (inútil para Gmail)
   - Canal asignado: `"brevo"` en vez de `"instantly"`

---

### `leadforge/verify_personal_emails.py`
**Creado:** 2026-04-15 (archivo nuevo)

Script para verificar emails personales (Gmail/Hotmail/etc) que vienen de DENUE y nunca pasaron por Anymail Finder.

**Flujo:**
1. Lee leads con email personal + `anymail_procesado=False` de `leads_master`
2. Llama a endpoint `anymail verify-email` (0.1 créditos, no 1 crédito)
3. Si `valid` → `verificado=True`, `canal_recomendado="brevo"`
4. Si `invalid` → `anymail_procesado=True`, `verificado=False`

**Funciones:**
```python
_verificar_email(client, email, semaphore) -> str      # llama verify-email
get_personal_leads_pendientes(db, cliente_id) -> list  # leads con email personal sin verificar
procesar_emails_personales(cliente_id, limit) -> dict  # loop principal
```

---

### `leadforge/denue_enricher.py`
**Modificado:** 2026-04-15

**Nuevos sectores agregados** a `SECTORES_DENUE`:

| Clave | SCIAN | Descripción |
|---|---|---|
| `parques_industriales` | 53/531 | Parques, zonas y corredores industriales |
| `manufactura` | 31 | Maquiladoras, plantas industriales |
| `quimica` | 32/325 | Empresas químicas, limpieza industrial |

---

### `leadforge/apify_scraper.py`
**Modificado:** 2026-04-15

Método nuevo agregado:
```python
async def check_credits(self) -> dict:
    """
    Verifica presupuesto disponible en cuenta Apify.
    Retorna {"ok": True} o {"ok": False, "error": "..."}.
    Retorna ok=False si used >= 95% del límite mensual.
    """
```
Esto permite que `pipeline.py` verifique créditos antes de lanzar scraping y muestre advertencia si Apify está bloqueado.

---

### Migraciones SQL (`migrations/`)

| Archivo | Fecha | Cambios |
|---|---|---|
| `004_rfc_social_fuente.sql` | 2026-04-16 | `rfc TEXT`, `fuente TEXT DEFAULT 'denue'`, `facebook_url`, `instagram_url`, `whatsapp TEXT` (campo legacy), `canal_recomendado TEXT` + índices |
| `005_social_web_fields.sql` | 2026-04-02 | `linkedin_url`, `twitter_url`, `tiktok_url`, `youtube_url`, `email_enriched_at TIMESTAMPTZ` + índices |
| SQL manual (2026-04-18) | 2026-04-18 | `whatsapp_url TEXT` — columna nueva para URLs `wa.me/` (distinta del campo legacy `whatsapp` de migración 004) |

> **Nota:** `whatsapp` (migración 004) es el campo de número legacy. `whatsapp_url` (2026-04-18) es la URL completa `https://wa.me/52...` para YCloud.

---

## 🐛 BUGS CORREGIDOS (HISTORIAL)

### Sesión 2026-04-18

| # | Bug | Archivo | Fix |
|---|---|---|---|
| 1 | `whatsapp_url` detectado pero no guardado en BD | `social_enricher.py` | Agregado a `to_dict()` — campo faltaba silenciosamente |
| 2 | `whatsapp_url` column doesn't exist en Supabase | DB | `ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS whatsapp_url TEXT` ejecutado en dashboard |

### Sesión 2026-04-15 (Google Places)

| # | Bug | Archivo | Fix |
|---|---|---|---|
| 1 | `nextPageToken` en FieldMask causaba 400 INVALID_ARGUMENT | `google_places_scraper.py` | Movido a campo top-level (no anidado bajo `places.*`) |
| 2 | Error 403 Apify key causaba `break` → detenía loop | `google_places_scraper.py` | Cambiado a `mark_exhausted(key)` + `continue` |
| 3 | `process_negocio` AttributeError (`email_leads_insertados`) | `pipeline.py` | Función renombrada a `_insert_negocio`, contadores refactorizados |
| 4 | Anymail llamaba a leads sin sitio_web | `pipeline.py` | Skip explícito si `not negocio.sitio_web` |
| 5 | `get_leads_stats()` devolvía máx 1,000 (límite Supabase) | `supabase_client.py` | `get_anymail_stats_por_cliente()` usa COUNT aggregation, no select rows |

### Sesión 2026-03-24 (Mac Mini setup)

| # | Bug | Fix |
|---|---|---|
| 1 | Dos procesos bot compitiendo (LaunchAgent + manual) | Matar proceso Downloads, solo LaunchAgent en LeadForge/ |
| 2 | `/si` decía "No hay búsqueda pendiente" | Causado por dos procesos — fix = un solo bot |
| 3 | `email_leads_insertados` AttributeError en `/agregar` | Reemplazado por `logger.info()` |
| 4 | `ModuleNotFoundError: No module named 'leadforge.scoring'` | Cambiado a `leadforge.lead_scorer` |
| 5 | AnymailFinder procesaba 0 leads (fallaba silenciosamente) | Fix del import anterior |
| 6 | Apify 403 mal interpretado como "spending limit" | Es "Too many outstanding invoices" (billing) |
| 7 | `get_leads_stats()` devolvía 1,000 (límite Supabase) | Supabase por defecto limita a 1,000 filas sin paginación |
| 8 | 358 leads industriales Coahuila bajo Zenon Admin | Migrados a SQB (291 movidos, 53 duplicados eliminados) |

### Sesiones anteriores (2026-03-13 a 2026-03-18)

| # | Bug | Fix |
|---|---|---|
| 1 | `run_bot()` no existía → ImportError silencioso | Función agregada |
| 2 | Sin MessageHandler para texto libre | Handler agregado |
| 3 | Actor Apify incorrecto (404) | Cambiado a `nwua9Gu5YrADL7ZDj` |
| 4 | Timeout Apify 3 min (runs tardan 4-15 min) | Aumentado a 12 min |
| 5 | Anymail para TODOS los negocios (muy lento) | Skip si sin sitio_web |
| 6 | Claude devuelve JSON en ```json fences | Strip de backticks antes de json.loads |
| 7 | Tabla `leads_master` con schema incorrecto | Recreada desde cero |

---

## ❌ PENDIENTES

### Alta Prioridad
1. **Integrar Brevo** — `brevo_sender.py` para emails personales verificados (Gmail/Hotmail — `verify_personal_emails.py` ya los detecta, falta el sender)
2. **Activar billing Google Cloud** — keys GOOGLE_KEY_1 (goodmantech) y GOOGLE_KEY_4 (esgconsultores)
3. **YCloud WhatsApp** — registrar número Business, luego campañas con 511 contactos en `whatsapp_url`
4. **Crear campañas Instantly** — salones eventos NL (85 emails), manufactura alimentos (72 emails)
5. **Leads para nuevos clientes** — ejecutar pipeline para Pinturas LePront, Goodman Tech, Focus Coach

### Media Prioridad
6. **Pagar facturas Apify** — ya no crítico (Google Places lo reemplazó), pero desbloquea actor de social media
7. **Emails reales de clientes** — actualizar tabla `clientes` con emails de contacto correctos
8. **`telegram_chat_id`** en tabla clientes — vincular cada cliente a su chat de Telegram
9. **Instantly API v2** — migrar `instantly_manager.py` (v1 da 404 en analytics)
10. **`busquedas_cache`** — verificar que DENUE runs también queden en caché

### Baja Prioridad
11. **Dashboard Goodman Webpage** — actualizar filtros para 5 clientes nuevos
12. **`sqb_pipeline.py`** — job nocturno APScheduler (ya configurado)

---

## 📁 ESTRUCTURA DEL PROYECTO (Mac Mini)

```
/Users/macmini/LeadForge/
├── start_monitor.py              ← PUNTO DE ENTRADA (LaunchAgent lo ejecuta)
├── .env                          ← API keys (NO subir a git)
├── leadforge/
│   ├── config.py                 ← Configuración desde .env
│   ├── pipeline.py               ← run_pipeline() — orquestador principal
│   │                               ⚠️ Importa desde google_places_scraper (no apify_scraper)
│   ├── google_places_scraper.py  ← ⭐ 2026-04-15: Google Places API — reemplaza Apify
│   │                               KeyRotator (hasta 9 keys GOOGLE_KEY_N, round-robin)
│   │                               check_credits() + scrape_multi_term(location/ciudad/estado)
│   │                               ApifyScraper = GooglePlacesScraper (alias compatibilidad)
│   ├── apify_scraper.py          ← Legado — Google Maps vía Apify (bloqueado por facturas)
│   ├── denue_enricher.py         ← DENUE/INEGI — SECTORES_DENUE + ingestar_sector()
│   ├── anymail_enricher.py       ← AnymailEnricher — enrich_negocio() + verify_email()
│   ├── verify_personal_emails.py ← ⭐ 2026-04-15: verifica emails Gmail/Hotmail/Yahoo de DENUE
│   │                               Usa verify-email (0.1 créditos, no find-email)
│   │                               Si válido → verificado=True, canal_recomendado="brevo"
├── social_enricher.py            ← ⭐ 2026-04-16: extrae FB/IG/TikTok/WA/LinkedIn de sitios web
│                                   Fix 2026-04-18: to_dict() incluye whatsapp_url
│   ├── lead_scorer.py            ← LeadSignals + calculate_lead_score() + get_recommended_channels()
│   ├── supabase_client.py        ← get_db(), insert_lead_master(), get_leads_stats()
│   │                               get_all_pending_leads_anymail(), get_leads_con_email_sin_verificar()
│   │                               get_anymail_stats_por_cliente(), update_lead_anymail_verificado()
│   │                               update_lead_email_personal_verificado() ← ⭐ NUEVO
│   ├── validation_cascade.py     ← 5 niveles + APROBADO_PERSONAL + DOMINIOS_PERSONALES
│   │                               Nivel 2.5: detecta dominio personal → canal Brevo
│   ├── hierarchy_filter.py
│   ├── owner_extractor.py
│   └── monitor/
│       ├── telegram_bot.py       ← Bot ZenonFinder — todos los comandos + callbacks
│       ├── health_checker.py     ← Health checks APScheduler
│       ├── alerts.py             ← send_telegram()
│       └── reply_webhook.py      ← FastAPI puerto 8001
├── logs/
│   ├── launchd.log               ← stdout del bot
│   └── launchd_err.log           ← stderr del bot
└── venv/                         ← Entorno Python 3.14
```

### Funciones clave en `supabase_client.py`

| Función | Descripción |
|---|---|
| `get_leads_stats(cliente_id)` | Retorna: total, con_web, con_email, verificados, cinco_estrellas, con_web_sin_verificar |
| `get_all_pending_leads_anymail(cliente_id, limit)` | Fase 1: leads con sitio_web, verificado=False |
| `get_leads_con_email_sin_verificar(cliente_id, limit)` | Fase 2: leads con email DENUE, sin web |
| `get_anymail_stats_por_cliente()` | Stats por cliente con paginación completa (no hit 1000-row limit) |
| `update_lead_anymail_verificado(...)` | Marca verificado=True + guarda email + calidad_stars → Instantly |
| `update_lead_email_personal_verificado(lead_id, email, email_status, canal)` | ⭐ NUEVO: emails Gmail/Hotmail verificados → canal Brevo |
| `check_search_cache(...)` | Verifica si ya se buscó: REUSE / SCRAPE |
| `insert_lead_master(...)` | UPSERT por (nombre_negocio, ciudad, cliente_id) |

---

## 🔑 APIs Y CREDENCIALES

| Servicio | Variable `.env` | Notas |
|---|---|---|
| Telegram Bot | `TELEGRAM_BOT_TOKEN` | @ZenonFinder |
| Telegram Master | `TELEGRAM_MASTER_CHAT_ID` | Chat ID de Gabriel/Zenon |
| Supabase URL | `SUPABASE_URL` | `pfurkonwbjfmxpfogdtr.supabase.co` |
| Supabase Key | `SUPABASE_SERVICE_KEY` | Service key (bypasa RLS) |
| Anymail | `ANYMAIL_API_KEY` | ~17,587 créditos (2026-04-15) |
| Google Places | `GOOGLE_KEY_1..4` | 4 keys con KeyRotator — Keys 2,3 activas; 1,4 requieren billing |
| Apify | `APIFY_TOKEN` | ⚠️ Bloqueado por facturas (no crítico, reemplazado) |
| Actor Apify | `APIFY_ACTOR_ID` | `nwua9Gu5YrADL7ZDj` |
| Anthropic | `ANTHROPIC_API_KEY` | Claude Haiku |
| DENUE | `DENUE_API_KEY` | `4e4956b1-96b2-408c-a52f-d2c9412ec5a4` |
| Instantly | `INSTANTLY_API_KEY` | Campañas cold email (solo emails corporativos) |
| Brevo | `BREVO_API_KEY` | ⏳ Pendiente — para emails personales verificados |
| WhatsApp | `WHATSAPP_TOKEN` + `PHONE_NUMBER_ID` | ⏳ Pendiente — Meta Cloud API |
| Cliente ID | `CLIENTE_ID` | `d0542bc7-f8e0-48cf-bce2-5c4ce8bdcd99` (Zenon Admin) |

> ⚠️ `APIFY_ACTOR_ID` correcto = `nwua9Gu5YrADL7ZDj` (`compass/google-maps-extractor`)
> NO usar `compass/crawler-google-places` (devuelve 404)

---

## 👤 PERFIL DEL OPERADOR

**Gabriel** (Zenon) — Dueño y operador del sistema LeadForge
- Master del bot @ZenonFinder (`TELEGRAM_MASTER_CHAT_ID`)
- Opera en México, generación de leads B2B
- Mac Mini siempre encendido como servidor de producción
- Múltiples clientes: SQB, LePront, Goodman Tech, Focus Coach
- Delega implementación técnica a Claude Code

---

## 💡 PARA INICIAR UNA NUEVA SESIÓN CON CLAUDE

```
Proyecto: LeadForge / ZenonFinder — bot Telegram generación leads B2B México
Producción: Mac Mini en /Users/macmini/LeadForge/ (LaunchAgent)
Lee CONTEXT.md para el contexto completo.

Tarea: [DESCRIBE TU TAREA]
```

---

*Última actualización: 2026-04-18 — social_enricher 5 runs: 1,706 redes sociales | Salones NL: 545 leads + 85 emails válidos | WhatsApp: 511 números recopilados | BD: ~24,000 leads, ~2,300 emails válidos*
