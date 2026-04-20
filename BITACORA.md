# 📋 BITÁCORA — LeadForge / ZenonFinder

---

## 📅 2026-04-20 — Sesión B: Gestión de Clientes, Reasignación de Leads y AnymailFinder Mr Ruta

### CONTEXTO DE LA SESIÓN
Desde Claude Code Desktop (Windows): creación de 2 nuevos clientes en Supabase, reasignación de leads históricos a sus clientes correctos, procesamiento AnymailFinder sobre Mr Ruta y generación de CSV para Instantly.

### ✅ Auditoría de emails válidos en Supabase

Consulta directa vía REST API antes de iniciar:

| Cliente | Emails válidos |
|---|---|
| SQB | 1,084 |
| Zenon Admin | 561 |
| b8e2f4d6 (histórico) | 539 |
| Goodman Tech | 114 |
| **TOTAL** | **2,298** |

Canal recomendado de los válidos: `email` (1,378) · `NULL` (686) · `instantly` (155) · `whatsapp` (79)

### ✅ Nuevo cliente: Mr Ruta

- **ID:** `be119ffc-dfc3-431e-9ba7-b44123934258`
- **Plan:** growth
- **Segmento:** Sector alimentos — empresas con rutas de distribución a clientes

### ✅ Nuevo cliente: Salones

- **ID:** `9673cf95-c862-465c-9180-98bcf9a0bb87`
- **Plan:** growth
- **Segmento:** Salones de eventos, bodas, quinceañeras, jardines, haciendas

### ✅ Reasignación leads → Salones (510 leads)

Leads identificados por `termino_busqueda` conteniendo: salon, eventos, banquetes, quinceanera, jardin de eventos, hacienda para bodas, terraza para eventos, centro social.

| Ciudad | Leads |
|---|---|
| Monterrey | 124 |
| Guadalupe | 74 |
| Ciudad Apodaca | 61 |
| Ciudad General Escobedo | 52 |
| Ciudad Santa Catarina | 48 |
| Santiago | 33 |
| Montemorelos | 30 |
| Cadereyta Jiménez | 24 |
| San Pedro Garza García | 23 |
| Ciudad de Allende | 22 |

Estado final Salones: 510 leads · 358 tel · 176 web · 63 email · 24 válidos · 152 pendientes Anymail

### ✅ Reasignación leads → Mr Ruta (999 leads)

Leads identificados por `termino_busqueda` conteniendo: alimento, tortilla, fritura, embutido, tostada, molino, empaque, envasado, procesadora, porcicult, granja, etc.

| Fecha búsqueda | Leads |
|---|---|
| 2026-03-14 | 101 |
| 2026-03-16 | 10 |
| 2026-03-21 | 57 |
| 2026-04-16 | 831 |

Estados: Nuevo León (567) · Tamaulipas (255) · Coahuila (171)
Estado final Mr Ruta: 999 leads · 803 tel · 399 web · 99 email · 53 válidos

### ✅ AnymailFinder — Mr Ruta

Script `run_anymail_mr_ruta.py` creado y ejecutado.

| Fase | Leads | Resultado |
|---|---|---|
| Fase 1 (find-email/company por sitio_web) | 331 | 0 emails nuevos |
| Fase 2 (verify-email DENUE) | 6 | 0 válidos |

- **Créditos usados:** 43
- **Créditos restantes:** 17,373
- Resultado esperado: empresas del sector alimentos (tortillerías, carnicerías, frituras) son negocios familiares sin infraestructura de email corporativo — AnymailFinder no puede encontrar emails en esos dominios.
- Todos marcados `anymail_procesado=True` en Supabase — no se reprocesarán ni cobrarán de nuevo.

**Corrección en script:** endpoint `/find-email/domain` no existe en v5.1 → corregido a `/find-email/company` con `company_name` + `website` opcional. El endpoint acepta ambos parámetros y usa caché (0 créditos si dominio ya fue consultado).

### ✅ CSV para Instantly — Mr Ruta

Archivo generado: `mr_ruta_instantly.csv`
- 53 leads con `email_status='valid'`
- Columnas: `first_name`, `last_name`, `email`, `company_name`, `website`, `phone`, `city`, `personalization`
- Pendiente: crear campaña "Mr Ruta — Sector Alimentos" en Instantly UI e importar CSV

### 🔜 PENDIENTE — Sesión B 2026-04-20
- Crear campaña en Instantly UI: "Mr Ruta — Sector Alimentos" e importar `mr_ruta_instantly.csv` (53 leads)
- AnymailFinder sobre Salones: 152 leads con web pendientes (~60-80 emails esperados)
- Agregar Mr Ruta y Salones al selector de cliente del bot @ZenonFinder (telegram_bot.py)

---

## 📅 2026-04-20 — Sesión A: CostGuard Google Places + Nueva Campaña Instantly (Misceláneas/Rutas)

### CONTEXTO DE LA SESIÓN
- Implementación de `CostGuard` en `google_places_scraper.py` para evitar cargos inesperados en Google Places API
- Inicio de configuración de campaña Instantly para segmento misceláneas/tienditas con rutas a clientes

### ✅ CostGuard — google_places_scraper.py

Clase nueva agregada para rastrear el uso de la API de Google Places y evitar gastos no planificados.

**Dos niveles de protección:**

| Nivel | Variable `.env` | Default | Costo aprox. |
|-------|----------------|---------|--------------|
| Por corrida (memoria) | `GOOGLE_MAX_REQ_PER_RUN` | 500 req | ~$16 USD |
| Por mes (JSON en disco) | `GOOGLE_MAX_REQ_PER_MONTH` | 5,000 req | ~$160 USD |

**Comportamiento:**
- Al 90% del límite → warning en logs (una sola vez por key)
- Al 100% del límite → key marcada agotada con `mark_exhausted()`, scraping se detiene
- Persiste uso mensual en `logs/google_usage.json` (mantiene últimos 3 meses)
- `summary()` imprime tabla ASCII con uso por key, costo en USD y MXN

**Integración en GooglePlacesScraper:**
```python
# __init__
self.cost_guard = CostGuard()

# En _scrape_term — ANTES de la request:
ok, reason = self.cost_guard.can_request(key)
if not ok:
    self.rotator.mark_exhausted(key)
    break

# En _scrape_term — DESPUÉS de HTTP 200:
self.cost_guard.register(key)
```

**check_credits() ahora retorna:**
```python
{
    "ok": True,
    "details": {...},
    "uso_mensual_req": 120,
    "costo_mensual_usd": 3.84,
    "credito_restante_usd": 196.16,
}
```

### 🔜 PENDIENTE — Campaña Instantly Misceláneas/Rutas

Segmento objetivo identificado: misceláneas, tienditas, ventas al detalle con rutas a clientes.

**Leads en Supabase (2026-04-20):**
- Categoría "minisuper": 201 leads, 118 con email válido
- Categoría "tienda" (industriales/construcción): 39 válidos — NO son el target
- Categoría "abarrotes": 493 leads, solo 1 válido

**Pendiente confirmar con Zenon:**
1. ¿Los leads ya están cargados o hay que hacer nueva búsqueda con términos específicos?
2. ¿Para qué cliente es la campaña?
3. ¿Cuál es la solución para rutas? (software, servicio, producto)
4. ¿Nombre del remitente y empresa para el email?
5. ¿Qué cuentas de Instantly usar?

---

## 📅 2026-04-18 — Sesión: Social Enricher en producción + Salones de Eventos + WhatsApp

### CONTEXTO DE LA SESIÓN
- Corrida completa de `social_enricher.py` sobre todos los leads con sitio web (5 loops)
- Búsqueda de Salones de Eventos en 10 ciudades NL + Anymail enrichment
- Fix crítico en `social_enricher.py`: `whatsapp_url` no se guardaba en BD (faltaba en `to_dict()`)
- Extracción masiva de WhatsApp: 511 números recopilados en 4 runs
- Columna `whatsapp_url` agregada a `leads_master` en Supabase

### ✅ social_enricher.py — 5 runs en producción

| Run | Procesados | Con redes | Tasa |
|-----|-----------|-----------|------|
| 0 | 675 | 349 | 52% |
| 1 | 633 | 190 | 30% |
| 2 | 601 | 104 | 17% |
| 3 | 586 | 41 | 7% |
| 4 | 567 | 9 | 1.6% |
| **Total** | **3,062** | **693 nuevos** | — |

- Antes: 1,018 leads con FB. Después: **1,706 leads con redes sociales**
- Rendimiento típico decreciente (igual que Anymail batch)

### ✅ BÚSQUEDA — Salones de Eventos NL (10 ciudades)

**Términos (10):** salon de eventos, centro de convenciones, salon de bodas, salon de quince años, salon de fiestas, centro social, jardín de eventos, hacienda para eventos, banquetes, salon de graduaciones

| Ciudad | Leads |
|--------|-------|
| Monterrey | ~55 |
| Guadalupe | ~54 |
| Santa Catarina | ~55 |
| General Escobedo | ~55 |
| Apodaca | ~54 |
| San Pedro Garza García | ~55 |
| Cadereyta Jiménez | ~55 |
| Allende | ~55 |
| Montemorelos | ~55 |
| Santiago | ~52 |
| **TOTAL** | **~545** |

### ✅ ANYMAIL — Salones de Eventos

| Etapa | Resultado |
|-------|----------|
| Leads con sitio web | ~150 |
| Emails encontrados (Ruta A — find_by_company) | 99 |
| Válidos encontrados directamente | 14 |
| Verificados como valid (verify-email) | **85** |
| Inválidos | 1 |
| Unknown (no confirmados) | 25 |

### ✅ Fix social_enricher.py — whatsapp_url

`to_dict()` no incluía `whatsapp_url` → los WhatsApp detectados se perdían silenciosamente.

```python
# ANTES:
def to_dict(self) -> dict:
    return {k: v for k, v in {
        "facebook_url":  self.facebook_url,
        "instagram_url": self.instagram_url,
    }.items() if v is not None}

# DESPUÉS:
def to_dict(self) -> dict:
    return {k: v for k, v in {
        "facebook_url":  self.facebook_url,
        "instagram_url": self.instagram_url,
        "whatsapp_url":  self.whatsapp_url,
    }.items() if v is not None}
```

SQL ejecutado en Supabase dashboard:
```sql
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS whatsapp_url TEXT;
```

### ✅ WhatsApp Extractor — 4 runs

| Run | Procesados | Con WhatsApp | Tasa |
|-----|-----------|-------------|------|
| 1 | 1,000 | 371 | 37% |
| 2 | 1,000 | 96 | 9% |
| 3 | 1,000 | 38 | 3% |
| 4 | 1,000 | 6 | 0% |
| **Total** | **4,000 visits** | **511 números** | — |

- Método: httpx async (10 concurrentes), 5 regex patterns para wa.me / api.whatsapp.com
- Preparado para integración con YCloud (WhatsApp Business messaging)

### 📊 Estado de la BD al 2026-04-18

| Métrica | Valor |
|---------|-------|
| Total leads | ~23,900 |
| Con teléfono | ~11,000 |
| Con email | ~9,600 |
| Email válido (campaign-ready) | **~2,300** |
| Con Facebook | ~1,706 |
| Con Instagram | ~1,100 |
| Con WhatsApp | **511** |

### 🔜 PENDIENTE
- Commit y push `social_enricher.py` fix a GitHub develop
- Integrar Brevo API para emails personales (Gmail/Hotmail verificados)
- Activar billing en Google Cloud para GOOGLE_KEY_1 y GOOGLE_KEY_4
- Crear campañas Instantly.ai: salones eventos (85+ emails), manufactura alimentos (72+ emails)
- YCloud WhatsApp Business: registrar número y lanzar campañas con 511 contactos
- Campañas clientes: Pinturas LePront, Goodman Tech, Focus Coach

---

## 📅 2026-04-16 — Sesión: Reemplazo Apify → Google Places API + Expansión regional

### CONTEXTO DE LA SESIÓN
Migración definitiva de Apify a Google Places API con 4 keys propias y rotación automática.
Primera noche en producción: 1,267 leads en 19 ciudades a costo $0.
Creación de social_enricher.py para enriquecer leads con redes sociales.
Expansión regional de fabricantes de alimentos: Tamaulipas + Coahuila + NL extendido.

### ✅ Google Places API — 4 cuentas configuradas

| Key | Cuenta | Estado |
|-----|--------|--------|
| GOOGLE_KEY_1 | goodmantech.com.mx | ⚠️ 403 (billing no activo) |
| GOOGLE_KEY_2 | ia-ingenieria.com | ✅ Activa |
| GOOGLE_KEY_3 | quimicainteligente.mx | ✅ Activa |
| GOOGLE_KEY_4 | esgconsultores.com.mx | ⚠️ 403 (billing no activo) |

### ✅ google_places_scraper.py — creado y en producción

- Reemplaza `apify_scraper.py` completamente (alias `ApifyScraper = GooglePlacesScraper`)
- Rotación automática de 4 keys — fallback en 403/429
- Mismo output `NegocioRaw[]` que espera el pipeline
- `NegocioRaw` extendido: `reviews_text`, `raw_data`, `tiene_email`, `tiene_telefono`
- `check_credits()` para compatibilidad con pipeline.py
- `scrape_multi_term` acepta tanto `location`/`max_places` (pipeline) como `ciudad`/`estado`/`max_per_term`

### ✅ Primera noche en producción con Google Places

- **19 ciudades scrapeadas** — NL metro + Tamaulipas + Coahuila + NL extendido
- **1,267 leads generados** en una sola sesión
- Tiempo promedio: 12-35 segundos por ciudad
- **Costo: $0.00** (vs ~$5+ con Apify)

### ✅ social_enricher.py — creado

- Visita el sitio web de cada negocio y extrae redes sociales
- Detecta: Facebook, Instagram, TikTok, WhatsApp, LinkedIn
- Actualiza campos `facebook_url`, `instagram_url` en `leads_master`
- Estado: creado, pendiente de correr en producción

### ✅ BÚSQUEDA 1 — Tamaulipas + Coahuila (8 ciudades)

**Términos (10):** fabrica de tortillas, fabrica de tostadas, fabrica de frituras y botanas, fabrica de embutidos, empacadora de alimentos, distribuidora de alimentos, distribuidora de frituras, procesadora de alimentos, fabrica de carnitas, rastro y empacadora

| Ciudad | Estado | Insertados |
|--------|--------|-----------|
| Reynosa | Tamaulipas | 72 |
| Matamoros | Tamaulipas | 65 |
| Nuevo Laredo | Tamaulipas | 60 |
| Tampico | Tamaulipas | 71 |
| Ciudad Victoria | Tamaulipas | 62 |
| Saltillo | Coahuila | 72 |
| Torreon | Coahuila | 73 |
| Monclova | Coahuila | 67 |
| **TOTAL** | | **542** |

- DENUE: 13 leads | Google Places: 530 leads
- Costo Anymail: ~8 créditos (solo leads con sitio_web)

### ✅ BÚSQUEDA 2 — Nuevo León Extendido (10 ciudades fuera del metro)

| Ciudad | Insertados |
|--------|-----------|
| Apodaca | 61 |
| San Nicolás de los Garza | 70 |
| Guadalupe | 81 |
| General Escobedo | 73 |
| Linares | 41 |
| Montemorelos | 60 |
| Cadereyta Jiménez | 59 |
| Pesquería | 64 |
| Allende | 57 |
| Sabinas Hidalgo | 48 |
| **TOTAL** | **614** |

- DENUE: 13 leads | Google Places: 601 leads

### 📊 ACUMULADO TOTAL — Fabricantes de Alimentos

| Región | Leads |
|--------|-------|
| Monterrey metro (2026-04-15) | ~89 |
| Tamaulipas + Coahuila (2026-04-16) | 542 |
| NL extendido (2026-04-16) | 614 |
| **GRAN TOTAL** | **~1,267** |

### ⚠️ Notas técnicas
- Keys GOOGLE_KEY_1 y GOOGLE_KEY_4 siguen dando 403 (billing no activo) — el pipeline usa solo KEY_2 y KEY_3
- El pipeline instancia un nuevo `GooglePlacesScraper()` por cada ciudad, lo que resetea el KeyRotator en cada iteración (las keys 403 se re-intentan y se marcan agotadas en cada run, sin impacto funcional)
- DENUE falla en términos multi-palabra con "de" o "y" por problemas de URL encoding — solo los términos simples como "distribuidora de alimentos" o "procesadora de alimentos" funcionan

### ✅ ANYMAIL BATCH — Nuevas ciudades (285 leads con sitio_web)

| Etapa | Resultado |
|-------|----------|
| Leads con sitio web | 285 |
| Emails encontrados (`find_by_company`) | 89 |
| Verificados como `valid` (`verify-email`) | **72** |
| Inválidos | 2 |
| Unknown (no confirmados) | 15 |
| Créditos usados total | ~99 |

Emails válidos destacados del sector alimentos:
- `ventas@tortilleriadelconsuelo.com`, `informacion@tortilleriarubi.com`
- `lazaro@alimentosaltamira.com`, `privera@qualtia.com` (Qualtia Alimentos)
- `afonseca@bydsa.com` (Botanas y Derivados), `administracion@empacadoralahuerta.com`
- `anhuerta@sigma-alimentos.com` (Sigma Alimentos)

### 📊 Estado de la BD al 2026-04-16

| Métrica | Valor |
|---------|-------|
| Total leads | **23,364** |
| Con teléfono | 10,768 |
| Con email | 9,042 |
| Email válido (campaign-ready) | **2,128** |
| Con Facebook | 1,018 |
| Con Instagram | 668 |

### 🔜 PENDIENTE
- Correr `social_enricher.py` en producción para enriquecer leads con redes sociales
- Crear campaña Instantly.ai con los 72+ emails válidos de manufactura de alimentos
- Integrar Brevo API para emails personales verificados
- Activar billing en Google Cloud para GOOGLE_KEY_1 y GOOGLE_KEY_4
- Crear campañas Instantly.ai para clientes (Pinturas LePront, Goodman Tech, Focus Coach)
- WhatsApp sender usando Meta Cloud API ($0.0305/msg) — pendiente número registrado

---

## 📅 2026-04-15 — Sesión: Google Places API + Pipeline Food Manufacturing + Emails Personales

### CONTEXTO DE LA SESIÓN
Migración completa de Apify a Google Places API con rotación de 4 keys propias.
Búsqueda y carga de 89 empresas fabricantes/distribuidoras de alimentos en Monterrey NL.
Implementación de track separado para emails personales (Gmail/Hotmail) → Brevo.

---

### ✅ CAMBIO CENTRAL: Apify → Google Places API

**Motivación:** Apify tenía facturas pendientes bloqueando el scraping. Se reemplazó con 4
cuentas propias de Google Cloud que tienen créditos disponibles.

**Archivo modificado:** `leadforge/pipeline.py` — línea 18
```python
# ANTES:
from .apify_scraper import ApifyScraper, NegocioRaw
# AHORA:
from .google_places_scraper import ApifyScraper, NegocioRaw
```

**Keys en .env agregadas:**
```
GOOGLE_KEY_1=AIzaSyBWFPELXm7OG...   # goodmantech.com.mx     ← 403 (billing no activo)
GOOGLE_KEY_2=AIzaSyD4QTa5vpGfh...   # ia-ingenieria.com      ✅ activa
GOOGLE_KEY_3=AIzaSyAaD4TwKqtFaz...  # quimicainteligente.com.mx ✅ activa
GOOGLE_KEY_4=AIzaSyAZ5tphhWdi...    # esgconsultores.com.mx   ← 403 (billing no activo)
```
> Keys 1 y 4 dan 403 — requieren activar billing en Google Cloud Console.

---

### ✅ google_places_scraper.py — Correcciones y mejoras de compatibilidad

**Archivo:** `leadforge/google_places_scraper.py`

**Bug 1 corregido:** `nextPageToken` en FieldMask tenía prefijo incorrecto
```python
# MAL (causaba 400 INVALID_ARGUMENT):
"places.nextPageToken"
# BIEN:
"nextPageToken"   # campo top-level, no anidado bajo places.*
```

**Bug 2 corregido:** Error 403 causaba `break` en vez de rotar key
```python
# MAL:
if response.status_code in (429, 403):
    break   # ← detenía el loop completamente
# BIEN:
if response.status_code in (429, 403):
    self.rotator.mark_exhausted(key)
    await asyncio.sleep(0.5)
    continue  # ← rota a la siguiente key
```

**Compatibilidad con pipeline.py agregada:**

| Elemento | Descripción |
|---|---|
| `NegocioRaw.reviews_text` | Campo `list` con default `[]` — pipeline.py lo requería |
| `NegocioRaw.raw_data` | Campo `dict` con default `{}` — pipeline.py lo requería |
| `NegocioRaw.tiene_email` | Property `bool` — requería pipeline.py |
| `NegocioRaw.tiene_telefono` | Property `bool` — requería pipeline.py |
| `check_credits()` | Método async — pipeline llama esto antes de scraping. Retorna `{"ok": True}` si hay keys activas |
| `scrape_multi_term(location, max_places)` | Acepta la firma del pipeline (`location="Monterrey, NL, MX"`, `max_places=100`) además de la firma directa (`ciudad`, `estado`) |

**Alias para compatibilidad:**
```python
ApifyScraper = GooglePlacesScraper  # pipeline.py importa ApifyScraper
```

---

### ✅ BÚSQUEDA: 89 empresas alimentarias en Monterrey NL

**Términos usados (8):**
- fabrica de tortillas, fabrica de tostadas, fabrica de frituras y botanas
- fabrica de embutidos, empacadora de alimentos, distribuidora de alimentos
- distribuidora de frituras, procesadora de alimentos

**Resultados:**
| Fuente | Leads | Notas |
|---|---|---|
| DENUE/INEGI (gratis) | 12 | 9 ya traían email |
| Google Places API | 77 nuevos | max_per_term=12 |
| **Total Supabase** | **89** | cliente_id `d0542bc7` (Zenon Admin) |

**Anymail post-carga:**
- 3 leads con sitio_web verificados vía Anymail (0 emails válidos encontrados)
- Costo: 3 créditos Anymail
- Razón tasa baja: tortillerías/empacadoras PYME rara vez tienen dominio propio

**Leads destacados guardados:**
- Tostadas Hidalgo, Tostadas Los Reyes, FÁBRICA SANISSIMO, Tostadas D'Goyis
- Carnes Empacadora del Noreste, Zubex Industrial, Rastro y Empacadora Trevino
- TOSTADAS Y BOTANAS PREMIUM S.A. DE C.V., Tortitrigo S.A. De C.V.

---

### ✅ ENRIQUECIMIENTO ANYMAIL — Lote global Monterrey

Corrido sobre todos los leads de Monterrey con `sitio_web != null AND verificado=False`:

| Métrica | Valor |
|---|---|
| Leads procesados | 264 |
| Emails verificados aprobados | 18 |
| Créditos usados | 102.8 |
| Créditos restantes | 17,587 |

Emails verificados destacados: `admon@deportivocolinas.com`, `carlos@crocsa.com`,
`jmgarza@ayutlasa.com`, `drangel@incasa.com.mx`, `ana.aparicio@dina.com.mx`

---

### ✅ TRACK DE EMAILS PERSONALES (Gmail/Hotmail) — Nueva lógica

**Problema:** Los emails de DENUE incluyen Gmail/Hotmail de PYMEs que son válidos
pero no deben mezclarse con Instantly.ai (dañan domain reputation).

**Solución implementada:** Track separado → Brevo (pendiente de integrar API).

**Archivos modificados:**

**`leadforge/validation_cascade.py`:**
- Nuevo status `APROBADO_PERSONAL = "aprobado_personal"` en enum `ValidationStatus`
- Nueva constante `DOMINIOS_PERSONALES` (gmail, hotmail, yahoo, outlook, live, icloud, etc.)
- Nueva property `es_apto_para_brevo` en `ValidationResult`
- Nuevo Nivel 2.5 en cascade: detecta dominio personal → status `APROBADO_PERSONAL` → skip Instantly → va a Brevo

**`leadforge/supabase_client.py`:**
- Nueva función `update_lead_email_personal_verificado(lead_id, email, email_status, canal="brevo")`
  - Si válido: `verificado=True`, `canal_recomendado="brevo"`
  - Si inválido: `anymail_procesado=True`, `verificado=False`

**`leadforge/verify_personal_emails.py`** — Nuevo módulo:
- Lee todos los leads con email personal `anymail_procesado=False`
- Llama `POST /v5.1/verify-email` directamente (no `find-email/company`)
- Actualiza Supabase por `id` de lead
- Uso: `venv/bin/python -m leadforge.verify_personal_emails`

**Resultado de la primera corrida:**
```
Total emails personales procesados: 172
Válidos (→ Brevo): 0
Inválidos:         172
Créditos usados:   ~172
```
> Conclusión: Los emails de DENUE (hotmail/gmail) son de datos gubernamentales
> antiguos — la mayoría de cuentas están abandonadas/eliminadas.
> Emails personales frescos (de Google Places/formularios web) sí tendrán mejor tasa.

---

### 💬 ANÁLISIS: WhatsApp para leads sin email

**Contexto:** 55 leads de alimentos tienen teléfono pero no email verificado.

**Comparativa de precios para México:**
| Plataforma | Precio/msg marketing MX | Cuota plataforma | Recomendación |
|---|---|---|---|
| Meta Cloud API (directo) | **$0.0305 USD** | $0 | ✅ Recomendado |
| YCloud | ~$0.034-0.037 USD | ~$29/mes | Solo si se necesita dashboard |

**Decisión:** Meta Cloud API directo. Módulo `whatsapp_sender.py` pendiente de construir.
Requiere: número WhatsApp Business registrado + `WHATSAPP_TOKEN` + `PHONE_NUMBER_ID`.

---

### 🔧 PENDIENTES DE ESTA SESIÓN

| Prioridad | Tarea |
|---|---|
| Alta | Integrar Brevo API — `brevo_sender.py` (próximo paso confirmado) |
| Alta | Activar billing en Google Cloud para keys 1 y 4 (goodmantech, esgconsultores) |
| Media | Construir `whatsapp_sender.py` usando Meta Cloud API |
| Media | Registrar número WhatsApp Business en Meta for Developers |

---

## 📅 2026-03-17 al 2026-03-18 — Sesión: SQB Campaign Launch + Seguridad Supabase + Pipeline Autónomo

### CONTEXTO DE LA SESIÓN
Sesión en 3 bloques: (1) corrección de 5 vulnerabilidades de seguridad en Supabase,
(2) reconexión y configuración de 22 cuentas IONOS en Instantly.ai para SQB/Química Inteligente,
(3) construcción del pipeline autónomo DENUE→AMF→Export sin intervención manual.

---

### ✅ SUPABASE SECURITY HARDENING — 5 vulnerabilidades corregidas

**Archivo creado:** `migrations/003_security_hardening.sql`
**Vulnerabilidades corregidas:**
| # | Tabla / Función | Problema | Fix |
|---|---|---|---|
| 1 | `leads_master` | RLS no habilitado | `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` |
| 2 | `macrisa_leads` | RLS no habilitado | Ídem + policy service_role |
| 3 | `clientes` | RLS no habilitado | Ídem |
| 4 | `alertas` | RLS no habilitado | Ídem |
| 5 | `clientes_saas` | RLS no habilitado | Ídem (tabla extra descubierta en audit) |
| 6 | `update_leads_master_timestamp()` | `search_path` no fijo | `SET search_path = ''` + SECURITY INVOKER |
| 7 | `update_macrisa_updated_at()` | Ídem | Ídem |

**Policies creadas:**
- `leads_master`: anon SELECT (dashboard), service_role CRUD completo
- Resto de tablas: service_role only (no acceso anon)
- Total: 12 tablas con RLS habilitado ✅

---

### ✅ IONOS CONTRATOS RENOVADOS — 4 contratos

| Contrato IONOS | Dominio principal | Estado |
|---|---|---|
| 108757784 | quimica-inteligente.com (SQB) | ✅ Renovado |
| 109237444 | mallasycribas.com.mx (RC) | ✅ Renovado |
| 109237462 | tejidosdealambre.mx (RC) | ✅ Renovado |
| 109237616 | lupront.com (LP) | ✅ Renovado |

---

### ✅ INSTANTLY.AI — 22 cuentas IONOS SQB configuradas

**Script creado:** `ionos_accounts.csv` → `instantly_quimica_FINAL.csv`
**Proceso:**
1. Parseado CSV IONOS (separador `;`) → 25 cuentas Mail Basic + 1 forward
2. Identificadas 3 contraseñas por dominio:
   - `inteliquimica.com` / `inteli-quimica.com` / `quim-inteligente.com` → `Horacio#326`
   - `quimica-heavy.com` / `quimica-inteligente.com` / `quimica-smart.com` → `Mazatlan#4228`
   - `quimicainteli.com` / `quimicasmart.com` / `quiminteligente.com` → `PuertoMexico#338`
3. Generado CSV para Instantly (27 cuentas, 2 con error 422 excluidas)
4. 22 cuentas ya existían (Disconnected por vencimiento) → reconectadas via API v1
5. Sender actualizado a **Luis Vilchis** en las 22 cuentas via API
6. Límite de envío: **35 emails/día/cuenta** = 770 emails/día total

**Código clave (reconexión bulk via API):**
```python
requests.post("https://api.instantly.ai/api/v1/account/update", json={
    "api_key": API_KEY, "email": email,
    "smtp_host": "smtp.ionos.com", "smtp_port": 587,
    "imap_host": "imap.ionos.com", "imap_port": 993,
    "smtp_password": pwd, "imap_password": pwd,
})
```

---

### ✅ SQB LEADS — Base de datos inicial cargada

**Cliente ID:** `c7f3a2b1-9e4d-4f8a-b3c2-1e5f7a9d0b4c`
**Total leads SQB:** 2,103 (Nuevo León — manufactura CNC, alimentos, automotriz, flotas)
**Primera ronda AMF (8:15am):** 498 procesados → 86 válidos, 412 inválidos, 150 créditos
**Sectores cubiertos NL:** cnc, alimentos, automotriz, flotas (via DENUE)

**Conteos Supabase (2026-03-18):**
- `leads_master` total: **10,935**
- SQB: 2,103 | RC: 2,191 | LP: 6,641
- Macrisa (`macrisa_leads`): 5,470

---

### ✅ REGIO CRIBAS — Campaña activada en Instantly

**Estado:** ACTIVA ✅
**Contactos:** 30
**Progreso secuencia:** 36%
**Enviados:** Iniciando (primer día)

---

### ✅ NUEVO SCRIPT — sqb_pipeline.py (pipeline autónomo)

**Archivo:** `sqb_pipeline.py` (raíz del proyecto)
**Propósito:** Ejecuta sin intervención: DENUE → AMF → Export CSV
**Uso:**
```powershell
venv\Scripts\python.exe sqb_pipeline.py              # pipeline completo
venv\Scripts\python.exe sqb_pipeline.py --solo-denue  # solo scraping
venv\Scripts\python.exe sqb_pipeline.py --solo-amf    # solo AMF + export
venv\Scripts\python.exe sqb_pipeline.py --solo-export # solo CSV
```

**Cobertura DENUE programada (20 búsquedas):**
- Coahuila: cnc, alimentos, automotriz, flotas
- Tamaulipas: cnc, alimentos, automotriz, flotas
- Chihuahua: cnc, automotriz, alimentos
- Guanajuato: cnc, automotriz, alimentos
- San Luis Potosí: cnc, automotriz, alimentos
- Nuevo León: alimentos, automotriz, flotas (pendientes)

**Meta AMF:** 800 emails válidos SQB antes de exportar
**Notificaciones:** Telegram después de cada paso
**Estado:** ✅ Corriendo en producción

---

### ✅ NUEVO COMANDO BOT — /verificar sqb

**Archivo:** `leadforge/monitor/telegram_bot.py`
**Uso:** `/verificar sqb 500`
**Lógica:**
- Ruta A: verifica emails existentes con `anymail_procesado=False`
- Ruta B: busca emails por `find_by_company()` para leads con sitio_web sin email
**Resultado primera ejecución:** 86 válidos de 498 procesados (17% tasa)

---

### 📊 CRÉDITOS ANYMAIL FINDER (2026-03-18)

| Ronda | Procesados | Válidos | Créditos |
|---|---|---|---|
| Ronda 1 (8:15am) | 498 | 86 | 150.0 |
| Rondas 2-3 (10-11am) | ~500 | ~85 | ~150 |
| **Restantes** | — | — | **~8,588** |

---

### ⚠️ PROBLEMAS ENCONTRADOS Y RESUELTOS

| # | Problema | Fix |
|---|---|---|
| 1 | Bot corría con código viejo (no reconocía /verificar sqb) | Reinicio manual con venv\Scripts\python.exe |
| 2 | getUpdates retornaba 0 (bot ya consumió los mensajes) | Reenviar comandos vía API directamente |
| 3 | CSV IONOS con separador `;` → Excel lo mostraba en 1 columna | Parseado con Python split(';') |
| 4 | 409 en importación Instantly → cuentas ya existían Disconnected | Reconectadas via API update en vez de reimportar |
| 5 | `anymail_finder` module no encontrado | Módulo correcto: `anymail_enricher.AnymailEnricher` |
| 6 | `empresa` columna no existe en leads_master | Columna correcta: `nombre_negocio` |
| 7 | UnicodeEncodeError al imprimir emojis | `sys.stdout.reconfigure(encoding='utf-8')` |

---

## 📅 2026-03-15 al 2026-03-16 — Sesión extensa: Automatización completa + Recuperación masiva de datos

### CONTEXTO DE LA SESIÓN
Sesión de trabajo intensiva enfocada en 4 áreas: (1) diagnóstico y recuperación del bot caído,
(2) rescate masivo de datos históricos de Apify (~$14.50 USD en datos), (3) automatización
completa del pipeline para eliminar intervención manual, (4) estrategia de búsqueda para Malla Cribas.

---

### ✅ DIAGNÓSTICO — Bot Telegram estaba detenido

**Síntoma:** No había proceso Python corriendo (`Get-Process python` devolvía error)
**Causa:** El bot se había detenido sin aviso — no había auto-reinicio configurado
**Fix inmediato:** Reiniciar con `.\venv\Scripts\python.exe -X utf8 start_monitor.py`
**Fix permanente:** Ver sección de automatización más abajo

---

### ✅ HEARTBEAT — Latido cada 2 horas

**Archivo:** `leadforge/monitor/health_checker.py`
**Cambios:**
- Nueva función `send_heartbeat()` — envía mensaje "💚 ZenonFinder activo" a Telegram
- Job agregado en `_setup_jobs()` con `IntervalTrigger(hours=2)`
- Heartbeat inmediato al arrancar el bot (via `call_soon`)
**Propósito:** Si Zenon no ve el mensaje en 4+ horas, sabe que el bot cayó

---

### ✅ RECUPERACIÓN MASIVA — 67 runs históricos de Apify

**Herramienta usada:** `recover_apify_runs.py --limit 200 --all`
**Comando ejecutado:**
```powershell
.\venv\Scripts\python.exe -X utf8 recover_apify_runs.py --limit 200 --all
```
**Resultado:**
| Métrica | Valor |
|---|---|
| Runs con datos encontrados | 67 |
| Email leads recuperados | 86 |
| Social leads recuperados | 1,696 |
| **Total recuperado** | **1,782** |
| BD antes | 483 leads |
| BD después | **1,474 leads** |
| Emails verificados en BD | **330** |
| Valor estimado rescatado | ~$14.50 USD |

**Período cubierto:** 2026-02-14 al 2026-03-16 (algunos runs estaban a punto de expirar en 24-48h)

---

### ✅ AUTOMATIZACIÓN COMPLETA DEL PIPELINE

#### 1. DENUE inyectado en pipeline.py
**Archivo:** `leadforge/pipeline.py`
**Cambio:** Después de `asyncio.gather(*tasks)`, se ejecuta automáticamente `_denue_enrich_new_leads()`
para los social leads recién insertados.
```python
# --- DENUE ENRICHMENT AUTOMÁTICO ---
if stats.social_leads_insertados > 0:
    denue_nuevos = await _denue_enrich_new_leads(ciudad=ciudad, ...)
    stats.denue_emails_nuevos = denue_nuevos
```
**Campo nuevo en PipelineStats:** `denue_emails_nuevos: int = 0`

#### 2. DENUE nocturno en health_checker.py
**Archivo:** `leadforge/monitor/health_checker.py`
**Cambio:** Job `denue_nocturno` en APScheduler — corre cada día a las 3am
```python
self.scheduler.add_job(_run_denue_nocturno, trigger="cron", hour=3, minute=0)
```
Notifica por Telegram: cuántos emails nuevos encontró + leads enriquecidos

#### 3. start_zenonbot.bat — Auto-reinicio si cae
**Archivo:** `start_zenonbot.bat` (nuevo, raíz del proyecto)
```batch
:restart
.\venv\Scripts\python.exe -X utf8 start_monitor.py
timeout /t 10 /nobreak
goto restart
```
Si el bot cae por cualquier razón, se reinicia automáticamente a los 10 segundos.

#### 4. instalar_autostart.ps1 — Auto-arranque con Windows
**Archivo:** `instalar_autostart.ps1` (nuevo, raíz del proyecto)
Registra tarea `ZenonFinderBot` en Windows Task Scheduler — arranca al hacer login.
**Uso (una sola vez, como admin):**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\instalar_autostart.ps1
```

---

### ✅ DENUE — API Key obtenida

**API Key:** `4e4956b1-96b2-408c-a52f-d2c9412ec5a4`
**Fuente:** Portal INEGI — registro de usuario
**Estado:** Key válida. Endpoints documentados (`/v1/consulta/Buscar/...`) devuelven 404.
**Pendiente:** Verificar URL correcta del API DENUE en documentación actualizada de INEGI.

---

### ✅ ESTRATEGIA BÚSQUEDA — Malla Cribas (Regio Cribas)

**Problema identificado:** Los 330 emails en BD son mayormente constructoras/fraccionamientos, no el target de malla cribas.

**Target correcto para malla cribas:**
- Empresas que CONSUMEN malla cribas en proceso productivo
- Areneras, pedreras, canteras, graveras, plantas de concreto/block, plantas de asfalto

**Términos que SÍ funcionan en Google Maps MX:**
- `pedreras` ✅ (confirmado 54-70 resultados)
- `canteras` ✅ (confirmado Coahuila)
- `areneras` ✅
- `graveras` ✅
- `arena y grava` ✅

**Términos que NO funcionan:**
- `trituradoras de piedra` ❌ → 0 resultados
- `bancos de materiales` ❌ → ferreterías/tlapalerías (target incorrecto)

**Regla establecida:** Un solo estado por búsqueda.
```
❌ quiero 60 graveras en Nuevo León Coahuila Tamaulipas  → LOCATION NOT FOUND
✅ quiero 30 graveras en Nuevo León
✅ quiero 30 graveras en Coahuila
```

---

### ✅ ARQUITECTURA GEO-GRID — Diseñada (pendiente implementar)

**Problema:** Al buscar "100 ferreterías en Monterrey", Apify siempre devuelve el mismo TOP 100. No hay paginación real.

**Solución diseñada:**
- Tabla `municipios_mx` — municipios con población, coordenadas centro, estado
- Tabla `search_zones` — anillos concéntricos por municipio (Ring 0=centro, Ring 1-4=periferia)
- Prioridad de búsqueda: de mayor densidad (centro urbano) hacia la periferia
- `search_history` — registra término + zona + fecha para evitar duplicados en Apify
- Bot sugiere automáticamente zonas no cubiertas al pedir más del mismo término

**Municipios mapeados:** NL (9 AMM), Coahuila (5 principales), Tamaulipas, Chihuahua

---

### ⚠️ PROBLEMA DETECTADO — Instantly API v1 rota

**Síntoma:** Solo `campaign/list` funciona. `campaign/analytics/overview`, `campaign/get` → 404
**Causa:** Instantly migró a API v2 (Bearer token en header). La v1 solo mantiene `campaign/list`.
**4 campañas encontradas:** Regio Cribas, Pinturas Leprom, Limpieza de Cocinas/Damas, Limpieza
**Fix pendiente:** Crear API key v2 en `app.instantly.ai → Settings → API Keys`

---

### ⚠️ PROBLEMA DETECTADO — 502 Bad Gateway en Apify

**Run ID:** `5qdFUPAM3nOiAA6xs` (empresas mineras Coahuila)
**Síntoma:** `Server error '502 Bad Gateway'` al descargar dataset
**Causa:** Error temporal del servidor Apify
**Resultado:** Los 85 leads SÍ fueron guardados correctamente en Supabase (el pipeline tenía retry)
**Verificado:** BD pasó de 416 a 483 leads confirmando los datos guardados

---

### 📊 ANÁLISIS — Leads disponibles para campaña Regio Cribas

| Término de búsqueda | Emails disponibles | Relevante para Malla Cribas |
|---|---|---|
| baserow_import | 260 | ❓ Sin clasificar |
| casas nuevas / constructoras | 79 | ❌ No |
| fabricantes de tostadas | 14 | ❌ No |
| cantera / arena / material pétreo | 23 | ✅ Sí |

**Conclusión:** Solo 23 leads son target real. Necesitamos más búsquedas antes de lanzar campaña.

---

### 📊 ESTADO FINAL DE LA BD (2026-03-16)

| Métrica | Valor |
|---|---|
| Total leads en BD | 1,474 |
| Con email verificado | 330 |
| Email status "verified" | 257 |
| Email status "aprobado" | 73 |
| Principales estados | Nuevo León (~783), Coahuila (~163) |
| Leads sin campaña asignada | ~1,474 |

---

### 💡 DECISIÓN DE PLATAFORMA — Instantly vs MailerSend

**Discusión:** Zenon mencionó posibilidad de usar MailerSend ($25/mes vs Instantly $97/mes)
**Decisión tomada:** Continuar con Instantly por ahora
**Pendiente:** Cuando se decida migrar, crear `mailersend_manager.py` + `campaign_router.py`

---

> Registro cronológico de todos los cambios al sistema.
> **Propósito:** Que cualquier instancia de Claude (terminal, desktop, online, Windsurf, VS Code)
> pueda entender exactamente qué se hizo, por qué y cuándo.
> **Autor de cambios:** Claude Code + Zenon

---

## 📅 2026-03-14 — Sesión tarde: Goodman Webpage — Dashboard LeadsInstantly v2.0

### CONTEXTO DE LA SESIÓN
Desarrollo completo del módulo **Leads Instantly** dentro del sitio web Goodman Tech.
Partiendo del dashboard existente, se construyeron múltiples funcionalidades nuevas:
pantalla de selección de empresa post-login, modal de nueva empresa SaaS,
selector de períodos/fechas y gráfica de tendencia multi-línea.

---

### ✅ FIX — KPI Cards: icono superpuesto con etiqueta

**Archivo:** `LeadsInstantlyDashboard.tsx`
**Síntoma:** El nombre del ícono Material Symbols (ej. "location_on", "mail", "send") aparecía
como texto visible encima de la etiqueta del KPI ("TOTAL LEADS", "CON EMAIL", etc.).
**Causa:** El ícono y el label estaban en el mismo `flex items-center gap-1.5`,
lo que causaba que el nombre del símbolo se renderizara como texto al lado del label.
**Fix:** Cambiar a layout vertical stacked:
```tsx
// ANTES: flex row (icono + label lado a lado)
<div className="flex items-center gap-1.5 mb-1.5">
  <div className="w-6 h-6 ..."><span className="material-symbols-outlined">...</span></div>
  <p className="text-xs text-slate-500 uppercase">label</p>
</div>

// DESPUÉS: bloque apilado (icono arriba, label abajo)
<div className="w-7 h-7 rounded-md flex items-center justify-center mb-2">
  <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>icono</span>
</div>
<p className="text-xs text-slate-500 uppercase tracking-wide leading-tight mb-1">label</p>
<p className="text-xl font-black text-white">valor</p>
```

---

### ✅ NUEVA PANTALLA — LeadsInstantlySelectEmpresa.tsx

**Ruta:** `/leads_instantly/select-empresa`
**Archivo:** `src/pages/LeadsInstantlySelectEmpresa.tsx` (archivo nuevo)
**Propósito:** Pantalla de selección de empresa que aparece justo después del login,
antes de entrar al dashboard. El usuario elige para qué cliente trabajar hoy.

**Flujo:**
```
Login → /leads_instantly/select-empresa → (clic tarjeta) → /leads_instantly/dashboard
```

**Comportamiento:**
- Muestra 5 tarjetas de empresa + 1 tarjeta "Vista Global (Admin)"
- Cada tarjeta: ícono temático, nombre, descripción, industria, badge estado, leads/campañas
- Clic → guarda `sessionStorage['leadsEmpresa'] = key` → navega al dashboard
- "Vista Global" → guarda `'todos'` → dashboard sin filtro
- Botón Cerrar sesión limpia `leadsEmpresa` de sessionStorage

**Empresas configuradas:**
| Key | Empresa | Color | Ícono |
|---|---|---|---|
| regio_cribas | Regio Cribas | #3b82f6 | diamond |
| sqb | SQB | #10b981 | science |
| lupront | LuPront | #f59e0b | construction |
| goodman | Goodman Tech | #FACC15 | rocket_launch |
| focus | Focus / ESG | #8b5cf6 | eco |

---

### ✅ MODIFICACIÓN — LeadsInstantlyLogin.tsx

**Cambio:** Después de autenticación exitosa, redirige a `/leads_instantly/select-empresa`
en vez de ir directo a `/leads_instantly/dashboard`.
```tsx
// ANTES
navigate('/leads_instantly/dashboard');
// DESPUÉS
navigate('/leads_instantly/select-empresa');
```

---

### ✅ MODIFICACIÓN — App.tsx

**Cambio:** Agregada nueva ruta protegida:
```tsx
import LeadsInstantlySelectEmpresa from './pages/LeadsInstantlySelectEmpresa';
// ...
<Route path="/leads_instantly/select-empresa"
  element={<ProtectedRouteInstantly><LeadsInstantlySelectEmpresa /></ProtectedRouteInstantly>} />
```

---

### ✅ MODIFICACIÓN — LeadsInstantlyDashboard.tsx (múltiples mejoras)

#### 1. Leer empresa desde sessionStorage al montar

```tsx
useEffect(() => {
  const saved = sessionStorage.getItem('leadsEmpresa');
  if (saved && saved !== 'todos') setClienteFilter(saved);
}, []);
```

#### 2. Botón "Cambiar empresa" en top bar

Nuevo botón amarillo con ícono `swap_horiz` que llama `handleCambiarEmpresa()`:
- Limpia `sessionStorage['leadsEmpresa']`
- Navega a `/leads_instantly/select-empresa`

#### 3. Nombre de empresa activa en top bar

Subtítulo del logo cambia de "ZenonFinder · LeadForge" a "ZenonFinder · **Regio Cribas**"
(nombre en amarillo, legible, actualizado dinámicamente).

#### 4. Modal "Crear Nueva Empresa" (SaaS)

Botón "+ Nueva Empresa" (amarillo, ícono `add_business`) en el top bar y en filtros móvil.
Al hacer clic abre modal completo con campos:
- Nombre empresa (requerido), Contacto, Email, Teléfono
- Ciudad objetivo, Industria objetivo
- Servicio contratado (select con 5 opciones)
- Plan (pills: Básico / Profesional / Enterprise)
- Presupuesto mensual MXN
- Keywords para Apify (separadas por coma)
- Notas adicionales

Comportamiento del modal:
- Click fuera / botón ✕ / Cancelar → cierra y resetea el form
- "Crear Empresa" → `console.log` los datos (listo para POST a Supabase `clientes_saas`)
- Botón cambia a verde "¡Guardado!" y se cierra automáticamente a los 2 segundos

#### 5. Gráfica de tendencia — 4 líneas

Antes: 1 línea azul (leads).
Después: 4 líneas con leyenda visual:

| Línea | Color | Estilo |
|---|---|---|
| Leads generados | `#2463eb` azul | Sólido |
| Emails enviados | `#f97316` naranja | Punteado `5 3` |
| Abiertos | `#FACC15` amarillo | Sólido |
| Respondidos | `#22c55e` verde | Punteado `3 3` |

Leyenda de puntos de colores encima de la gráfica.
Subtítulo reactivo: "241 leads · 75 enviados · 6 respuestas"

#### 6. Selector de períodos con popover

Botón en top bar (desktop) con ícono de calendario y período activo.
Al hacer clic abre popover flotante con:

**Presets rápidos (grid 3 columnas):**
- Hoy (por hora 8am-3pm)
- 7 días (lu-do, datos actuales)
- 14 días (diario 1-14 Mar)
- 30 días (semanal S1 Feb - S1 Mar)
- Este mes (Mar 26)
- Todo el tiempo

**Rango personalizado:**
- Toggle "Personalizado" → expande 2 inputs `type="date"` (Desde / Hasta)
- Botón "Aplicar rango" (se habilita cuando ambas fechas están llenas)
- `colorScheme: 'dark'` para que los inputs date se vean bien en tema oscuro

**Info panel:** Muestra el período activo con texto legible.

**Datos mock por período:**
```
MOCK_TENDENCIA_HOY  → 8 puntos horarios (8am-3pm)
MOCK_TENDENCIA      → 7 días Lu-Do (array original)
MOCK_TENDENCIA_14D  → 14 días diario (1-14 Mar)
MOCK_TENDENCIA_30D  → 5 puntos semanales (S1 Feb - S1 Mar)
```

**Móvil:** `<select>` en barra de filtros con todos los períodos.

**Click outside:** `useRef` + `useEffect` → cierra el popover al hacer click fuera.

---

### ⚠️ PROBLEMAS ENCONTRADOS Y RESUELTOS (sesión tarde)

| # | Problema | Fix |
|---|---|---|
| 1 | El selector de empresa no era visible para el usuario (estaba en top bar desktop oculto) | Solución arquitectural: pantalla de selección post-login, más intuitivo |
| 2 | `useRef` no estaba en los imports | Agregado a la línea de import de React |
| 3 | Edit tool requiere que el archivo haya sido leído antes | Releer archivo antes de cada edición en sesión nueva |

---

### 📊 ESTADO DEL DASHBOARD AL CIERRE DE SESIÓN (2026-03-14 tarde)

| Funcionalidad | Estado |
|---|---|
| Landing `/leads-instantly` | ✅ Completa |
| Login `/leads_instantly` | ✅ Redirige a select-empresa |
| Pantalla selección empresa | ✅ Nueva, funcional |
| Dashboard — Tab Resumen | ✅ KPIs + 4 gráficas |
| Dashboard — Tab Leads | ✅ Tabla + filtros |
| Dashboard — Tab Campañas | ✅ Cards + comparativa |
| Dashboard — Tab Sistema | ✅ Servicios + cuentas |
| Filtros empresa / campaña | ✅ Bidireccional |
| Selector de período / fechas | ✅ 6 presets + custom range |
| Gráfica tendencia 4 líneas | ✅ Azul/naranja/amarillo/verde |
| Modal crear nueva empresa | ✅ Form completo (mock) |
| Botón cambiar empresa | ✅ Funcional |
| Datos reales (Supabase) | ✅ Conectado — sesión noche |
| Tabla `clientes_saas` | ❌ Pendiente crear |

---

## 📅 2026-03-14 — Sesión noche: Supabase conectado al Dashboard + Deploy a producción ✅

### CONTEXTO DE LA SESIÓN
Se conectó el dashboard del Goodman Webpage al proyecto Supabase real de LeadForge
(mismo proyecto que usa el bot Python). Se crearon los archivos necesarios y se desplegó
a producción con git push.

---

### ✅ NUEVO ARCHIVO — `.env` (Goodman Webpage)

**Ruta:** `C:\Users\Dell\CascadeProjects\Godman_Webpage\Godman_Webpage\.env`
```env
VITE_SUPABASE_URL=https://pfurkonwbjfmxpfogdtr.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```
Mismo proyecto Supabase que usa el bot LeadForge Python.
> ⚠️ Archivo en `.gitignore` — NO se sube al repositorio.

---

### ✅ NUEVO ARCHIVO — `src/lib/supabase.ts`

Cliente Supabase REST sin dependencia extra (`@supabase/supabase-js` no instalado).
Usa `fetch()` nativo con headers PostgREST.

**Funciones exportadas:**
| Función | Descripción |
|---|---|
| `sbQuery<T>(table, qs)` | Fetch genérico con query string |
| `sbCount(table, qs)` | Cuenta registros usando `Content-Range` header |
| `sbPing()` | Verifica conexión activa |
| `fetchDashboardStats()` | 5 conteos en paralelo (totalLeads, conEmail, abiertos, respondidos, calientes) |
| `fetchEmbudoData()` | Conteo por etapa del embudo (6 etapas) |
| `fetchUltimasRespuestas(n)` | Últimas N respuestas (`respondio_email=true`) |
| `fetchLeadsTabla(n)` | Últimos N leads para la tabla |

---

### ✅ MODIFICACIÓN — `LeadsInstantlyDashboard.tsx` (conexión a datos reales)

#### Imports agregados
```tsx
import {
  fetchDashboardStats, fetchEmbudoData,
  fetchUltimasRespuestas, fetchLeadsTabla,
  type LeadMaster,
} from '@/lib/supabase';
```

#### Estado nuevo
```tsx
const [sbLoading, setSbLoading]   = useState(true);
const [sbError,   setSbError]     = useState<string | null>(null);
const [sbStats,   setSbStats]     = useState<{...} | null>(null);
const [sbEmbudo,  setSbEmbudo]    = useState<...[] | null>(null);
const [sbReplies, setSbReplies]   = useState<LeadMaster[]>([]);
const [sbLeads,   setSbLeads]     = useState<LeadMaster[]>([]);
const [lastSbSync, setLastSbSync] = useState<Date | null>(null);
```

#### Función `loadSupabase()`
Llama las 4 queries en paralelo con `Promise.all()`. Si falla → `sbError` se popula y el dashboard usa mock data como fallback.

#### Estrategia de datos: real con fallback a mock
- `usingRealData = !!sbStats && !sbError`
- KPIs: usan valores reales si `usingRealData`, mock si no
- Embudo: `embudoData = usingRealData ? sbEmbudo : MOCK_EMBUDO`
- Tabla leads: mapeo dual `nombre_negocio ?? empresa` para compatibilidad
- Replies: mapeo dual `texto_respuesta_email ?? texto`

#### Badge de conexión en top bar (junto al título "Leads Instantly")
| Condición | Badge |
|---|---|
| Cargando | `⟳ sync` (gris) |
| Datos reales | `● HH:MM` (verde, hora del último sync) |
| Error / mock | `✗ mock` (rojo) |

#### Badge "● Datos reales" en gráfica Embudo
Aparece cuando `usingRealData = true`.

#### Footer del tab Leads
- Con datos reales: `✅ Datos reales desde Supabase · N leads · sync HH:MM`
- Sin datos: `⚠ Datos de muestra · Error: mensaje`

---

### ⚠️ ADVERTENCIA — RLS (Row Level Security)

Si Supabase tiene RLS activo en `leads_master`, el ANON key devolverá `[]`.
**Fix:** Ejecutar en Supabase SQL Editor:
```sql
CREATE POLICY "dashboard_anon_read" ON leads_master
  FOR SELECT TO anon USING (true);
```

---

### 🚀 DEPLOY A PRODUCCIÓN

Commit y push a repositorio. El sitio se despliega automáticamente via Vercel/hosting.

---

### 📊 ESTADO FINAL DEL MÓDULO LEADS INSTANTLY (2026-03-14 noche)

| Archivo | Estado |
|---|---|
| `LeadsInstantlyLanding.tsx` | ✅ Completo |
| `LeadsInstantlyLogin.tsx` | ✅ Redirige a select-empresa |
| `LeadsInstantlySelectEmpresa.tsx` | ✅ Nuevo — pantalla post-login |
| `LeadsInstantlyDashboard.tsx` | ✅ Conectado a Supabase real |
| `src/lib/supabase.ts` | ✅ Nuevo — cliente REST |
| `.env` | ✅ Nuevo — credentials Supabase |
| `App.tsx` | ✅ Nueva ruta protegida |
| **Tabla `clientes_saas`** | ❌ Pendiente crear en Supabase |
| **RLS policy** | ❓ Verificar si hace falta |

---

## 📅 2026-03-14 — Sesión mañana: Webhook Instantly.ai configurado y probado ✅

### CONTEXTO DE LA SESIÓN
Configuración completa del sistema de webhook para recibir eventos de Instantly.ai en tiempo real.
Se instaló ngrok en Windows para pruebas y se verificó la integración completa.

---

### ✅ WEBHOOK SERVER — webhook_server.py (creado en sesión anterior, validado hoy)

**Archivo:** `webhook_server.py` (raíz del proyecto)
**Función:** Launcher del servidor webhook FastAPI en puerto 8001
**Uso:**
```powershell
.\venv\Scripts\python.exe -X utf8 webhook_server.py
```
**Endpoints disponibles:**
- `POST /webhook/instantly` — Recibe eventos de Instantly.ai
- `GET /webhook/health` — Health check
- `GET /webhook/test-telegram` — Prueba notificaciones Telegram

---

### ✅ REPLY_WEBHOOK.PY — Actualizado a leads_master

**Archivo:** `leadforge/monitor/reply_webhook.py`
**Cambios aplicados:**
- Todas las referencias a `email_leads` → cambiadas a `leads_master`
- `handle_email_replied()` — actualiza `etapa="respondio"`, guarda `texto_respuesta_email`
- `handle_email_opened()` — actualiza `etapa="abierto"`, incrementa `veces_abierto`
- `handle_email_bounced()` — actualiza `etapa="descartado"`, marca `do_not_contact=True`
- Análisis de replies con Claude Haiku (sentiment, intent, urgency, suggested_response)
- Notificación automática a Telegram con la respuesta del lead + sugerencia de respuesta

---

### ✅ NGROK — Instalado y configurado en Windows

**Ruta:** `C:\Users\Dell\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe`
**Cuenta:** iaingenieria22@gmail.com (Plan Free)
**Authtoken configurado:** ✅ (3AvGETnxBOBO9vqhDZNTwEgywpk_...)
**Comando para usar:**
```powershell
cd "C:\Users\Dell\Downloads\ngrok-v3-stable-windows-amd64"
.\ngrok.exe http 8001
```
**Nota:** URL cambia en cada reinicio (limitación free). Para producción usar Mac Mini con IP fija.

---

### ✅ INSTANTLY.AI WEBHOOK — Configurado

**URL configurada:** `https://noncommemoratory-johnson-ureylene.ngrok-free.dev/webhook/instantly`
**ID del webhook:** `019ceaca-3eec-706c-be13-28a822b264de`
**Tipo de evento:** Todos los Eventos
**Campaña:** Todas las Campañas
**Encabezado:** Sin firma (modo desarrollo — `INSTANTLY_WEBHOOK_SECRET` pendiente configurar)

> ⚠️ La URL ngrok cambia al reiniciar. Habrá que actualizar el webhook en Instantly cuando cambie.

---

### ✅ TEST TELEGRAM EXITOSO

**Hora:** 23:24 CST
**URL testeada:** `https://noncommemoratory-johnson-ureylene.ngrok-free.dev/webhook/test-telegram`
**Resultado:** Mensaje recibido en @ZenonFinder:
```
✅ LeadForge Webhook — Test exitoso
El sistema de notificaciones funciona correctamente.
```

---

### ⚠️ PROBLEMAS ENCONTRADOS Y RESUELTOS

| # | Problema | Causa | Fix |
|---|---|---|---|
| 1 | `ngrok.exe` no reconocido en PATH | ngrok.exe no está en PATH del sistema | Usar ruta completa: `C:\Users\Dell\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe` |
| 2 | Authtoken inválido (ERR_NGROK_107) | Se usó API Key en vez de Authtoken | Ir a dashboard.ngrok.com/authtokens (diferente a API Keys) |
| 3 | 2 procesos Python corriendo | Se lanzó Start-Process dos veces | `Get-Process python \| Stop-Process -Force` |
| 4 | ngrok muestra página de advertencia en navegador | Protección anti-abuso de ngrok free | Normal — no afecta webhooks POST de Instantly |

---

### 📊 ESTADO FASE 2 AL CIERRE DE SESIÓN (2026-03-14)

| Componente | Estado |
|---|---|
| Webhook server (puerto 8001) | ✅ Funcionando |
| ngrok tunnel (Windows) | ✅ Activo |
| Instantly.ai webhook | ✅ Configurado |
| Telegram al recibir reply | ✅ Probado |
| Tabla `clientes` en Supabase | ❌ Pendiente |
| `campaign_launcher.py` | ❌ Pendiente |
| Primera campaña real | ❌ Pendiente |

---

## 📅 2026-03-13 — Sesión de planificación Fase 2 (tarde/noche)

### CONTEXTO DE LA SESIÓN
Después de estabilizar la Fase 1 (generación de leads), Zenon definió la Fase 2:
sistema de campañas de email automatizadas con Instantly.ai + Claude API para los 5 clientes.

### ✅ PERFILES DE CLIENTES RECIBIDOS (5/5 completos)

Zenon proporcionó perfiles completos para los 5 clientes del sistema. Cada perfil incluye:
quién son, qué venden, a quién le venden, diferenciadores y keywords de scraping.

| Cliente | Empresa | Producto/Servicio |
|---|---|---|
| Regio_Cribas | Regio Cribas S.A. de C.V. | Mallas y cribas de alambre (86 años, fabricante directo) |
| Le_Pront | LuPront / Pinturas Lupront | Pinturas industriales y arquitectónicas (fabricante, -30-40% vs Comex) |
| SQB | Soluciones Químicas Biodegradables | Limpieza industrial + químicos (Patente US, PEMEX validado, 40+ años) |
| Goodman_Tech | Goodman Tech | Automatización con IA para PyMEs (empresa de Zenon/Coyo) |
| Focus | ESG Consultores / Focus Coach | Consultoría ESG/Sostenibilidad (GRI+IASE, STPS deducible) |

> NOTA: Goodman Tech ES la empresa de Zenon. Regio Cribas aparece como cliente prueba social de Goodman Tech.

### ✅ ARQUITECTURA FASE 2 DEFINIDA

Flujo aprobado:
1. Filtrar leads_master por cliente y categorías afines
2. Claude API genera email personalizado (basado en perfil Google Maps del lead)
3. Agregar lead a campaña Instantly.ai via API
4. Instantly maneja secuencia: Email 1 (día 0) → Email 2 (día 3 si sin respuesta)
5. Webhook Instantly → Python actualiza etapa en leads_master
6. Si responde → alerta Telegram a Zenon

Decisión: Instantly.ai maneja la secuencia (NO scheduler Python)
Razón: Instantly fue diseñado para esto, más simple y confiable

### ✅ CUENTAS DE ENVÍO REGISTRADAS EN INSTANTLY.AI (4 cuentas)

| Cuenta | Uso |
|---|---|
| vilchiszeluis@gmail.com | Envío general / Goodman Tech |
| luisvilchisze@gmail.com | Envío general / rotación |
| ia-ingenieria22@gmail.com | Campañas IA / automatización |
| esg.mexico.mx@gmail.com | Campañas ESG / Focus |

Capacidad estimada: ~500 emails/día en régimen de crucero (30 días warm-up por cuenta).

### ⏳ PENDIENTE PARA PRÓXIMA SESIÓN

1. Crear tabla `clientes` en Supabase con los 5 perfiles
2. Crear script `campaign_launcher.py`
3. Configurar webhook Instantly.ai
4. Probar primer envío con Regio_Cribas (cliente más simple para testear)

---

## 📅 2026-03-13 — Sesión de corrección y estabilización

### CONTEXTO DE LA SESIÓN
Zenon activó el bot ZenonFinder por primera vez en producción. Realizó búsquedas reales
de "fábricas de tostadas" y "pedreras" en Nuevo León/Coahuila. El sistema tenía múltiples
bugs que impedían el funcionamiento correcto y la escritura a Supabase.

---

### 🔴 BUG #1 — `run_bot()` no existía en telegram_bot.py
**Hora detectado:** Mañana (sesión anterior)
**Archivo:** `leadforge/monitor/telegram_bot.py`
**Síntoma:** ImportError silencioso al arrancar start_monitor.py
**Causa:** `start_monitor.py` llamaba `run_bot()` pero la función no estaba definida
**Fix:** Se agregó la función `run_bot()` que inicializa la Application de python-telegram-bot
**Impacto:** Sin este fix el bot no arrancaba nunca

---

### 🔴 BUG #2 — Sin MessageHandler para texto libre
**Hora detectado:** Mañana
**Archivo:** `leadforge/monitor/telegram_bot.py`
**Síntoma:** El bot arrancaba pero no respondía a ningún mensaje de texto
**Causa:** Faltaba registrar el handler `MessageHandler(filters.TEXT, handle_free_text)`
**Fix:** Agregado handler en la función `run_bot()`
**Impacto:** Sin este fix el bot ignoraba todos los mensajes

---

### 🔴 BUG #3 — `loop.add_signal_handler()` falla en Windows
**Hora detectado:** Mañana
**Archivo:** `start_monitor.py`
**Síntoma:** `NotImplementedError` al arrancar en Windows
**Causa:** `add_signal_handler` no está implementado en el event loop de Windows
**Fix:** Guard `if sys.platform != "win32":` antes de registrar signal handlers
**Impacto:** Sin este fix el bot crasheaba inmediatamente en Windows

---

### 🔴 BUG #4 — UnicodeEncodeError en consola Windows
**Hora detectado:** Mañana
**Archivo:** `start_monitor.py` (punto de lanzamiento)
**Síntoma:** Caracteres con tildes y emojis causaban crash en consola Windows
**Causa:** La consola de Windows usa CP1252 por defecto, no UTF-8
**Fix:** Lanzar Python con el flag `-X utf8` (`python -X utf8 start_monitor.py`)
**Comando correcto:**
```powershell
Start-Process -FilePath 'venv\Scripts\python.exe' -ArgumentList '-X','utf8','start_monitor.py' ...
```
**Impacto:** Sin este fix el bot crasheaba con cualquier texto en español

---

### 🔴 BUG #5 — Claude Haiku devuelve JSON en markdown fences
**Hora detectado:** ~10:00 AM
**Archivo:** `leadforge/monitor/telegram_bot.py` → `parse_finder_intent()`
**Síntoma:** `json.JSONDecodeError` al parsear la respuesta de Claude
**Causa:** Claude Haiku devuelve el JSON envuelto en ` ```json ... ``` ` (markdown)
**Fix:** Strip de backticks y del prefijo "json" antes de `json.loads()`
```python
text = text.strip()
if text.startswith("```"):
    text = text.split("```")[1]
    if text.startswith("json"):
        text = text[4:]
```
**Impacto:** Sin este fix ninguna búsqueda se procesaba correctamente

---

### 🔴 BUG #6 — Actor Apify incorrecto (404)
**Hora detectado:** ~10:10 AM
**Archivo:** `leadforge/config.py`
**Síntoma:** Apify devolvía 404 en cada run
**Causa:** `APIFY_ACTOR_ID` estaba hardcodeado como `compass/crawler-google-places` (no existe)
**Fix:** Cambiado a `nwua9Gu5YrADL7ZDj` = `compass/google-maps-extractor`
**Nota:** El actor `lukaskrivka/...` existe pero cuesta $9/1000 vs $4/1000 del correcto
**Impacto:** Sin este fix NINGÚN run de Apify funcionaba

---

### 🟡 BUG #7 — `_get_dataset_items()` retornaba None
**Hora detectado:** ~10:15 AM
**Archivo:** `leadforge/apify_scraper.py`
**Síntoma:** Pipeline recibía `None` en vez de lista vacía, causaba TypeError
**Causa:** Faltaba manejo del caso donde el dataset response no tiene items
**Fix:** `return items or []` al final de `_get_dataset_items()`
**Impacto:** Crashes en el pipeline cuando Apify no encontraba resultados

---

### 🟡 BUG #8 — Anymail llamado para TODOS los negocios (muy lento)
**Hora detectado:** ~10:30 AM
**Archivo:** `leadforge/pipeline.py` → `process_negocio()`
**Síntoma:** Pipeline tardaba 5+ minutos para búsquedas de 83 negocios
**Causa:** Se llamaba Anymail Finder para cada negocio, incluso sin sitio_web
**Razonamiento:** Sin dominio web no hay email posible → llamada inútil y cara
**Fix:** Skip inmediato si el negocio no tiene `sitio_web` ni `email`
```python
if not negocio.sitio_web and not negocio.email:
    return AnymailResult(route_used="skip")
```
**Impacto:** Redujo tiempo de procesamiento de ~5 min a ~1-2 min

---

### 🟡 BUG #9 — `AnymailResult()` con kwarg inválido
**Hora detectado:** ~10:35 AM
**Archivo:** `leadforge/pipeline.py`
**Síntoma:** `TypeError: AnymailResult.__init__() got unexpected keyword argument 'raw_response'`
**Causa:** El dataclass AnymailResult no tenía el campo `raw_response`
**Fix:** Cambiado a `AnymailResult(route_used="skip")` (campo que sí existe)
**Impacto:** Crashes en el pipeline al crear resultados vacíos

---

### 🔴 BUG #10 — Tabla `leads_master` con schema incorrecto
**Hora detectado:** ~18:00
**Archivo:** Supabase (tabla `leads_master`)
**Síntoma:** Error `PGRST204: Could not find column 'categoria'` (y luego 'ciudad', etc.)
**Causa:** La tabla `leads_master` había sido creada con un schema completamente diferente
  al que el código Python esperaba. Las columnas básicas (`categoria`, `ciudad`, etc.) no existían.
**Historia:**
  - Primer intento: ALTER TABLE agregando columnas nuevas → seguía fallando en columnas básicas
  - Segundo intento: NOTIFY pgrst reload schema → no resolvió el problema
  - Solución definitiva: DROP TABLE CASCADE + CREATE TABLE desde cero con schema correcto
**Fix ejecutado en Supabase SQL Editor:**
```sql
DROP TABLE IF EXISTS leads_master CASCADE;
CREATE TABLE leads_master (id UUID PRIMARY KEY, nombre_negocio TEXT NOT NULL,
  categoria TEXT, ciudad TEXT, estado TEXT, pais TEXT DEFAULT 'MX', ...
  etapa TEXT NOT NULL DEFAULT 'nuevo', ...);
CREATE UNIQUE INDEX lm_dedup ON leads_master(nombre_negocio, ciudad, cliente_id);
NOTIFY pgrst, 'reload schema';
```
**Impacto:** NINGÚN lead se había guardado en Supabase hasta corregir esto

---

### 🔴 BUG #11 — Timeout Apify demasiado corto (3 min → corridas de 4-15 min)
**Hora detectado:** ~16:31 (análisis de logs de pedreras 4:28 PM)
**Archivo:** `leadforge/apify_scraper.py` → `_wait_for_completion()`
**Síntoma:** Bot reportaba "0 lugares encontrados" pero Apify SÍ tenía datos
**Causa:** `TIMEOUT_MINUTES = 3` pero las corridas reales tardaban 4-15 minutos
  La búsqueda de "pedreras" (7 categorías × 10) tardó 4.5 minutos → timeout en 3 min
  La búsqueda de "pedreras en Coahuila" tardó 12 minutos → timeout en 12 min (nuevo)
**Fix:** `TIMEOUT_MINUTES = 12` (cuadruplicado)
**Impacto:** Todas las búsquedas con muchas categorías perdían sus resultados

---

### 🔴 BUG #12 — Dinero pagado a Apify sin datos en Supabase
**Hora detectado:** ~17:09 (revisión de logs del día)
**Síntoma:** Varios runs de Apify cobrados ($0.25-$0.36 cada uno) pero 0 registros en Supabase
**Causa:** Combinación de Bug #10 (tabla incorrecta) y Bug #11 (timeout)
**Fix:** Crear herramienta `recover_apify_runs.py` para descargar datasets ya pagados

---

### ✅ NUEVA HERRAMIENTA — recover_apify_runs.py
**Hora creada:** 17:09
**Archivo:** `C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\recover_apify_runs.py`
**Propósito:** Recuperar runs de Apify que ya se pagaron pero no se insertaron en Supabase
**Uso:**
```powershell
# Listar runs recientes
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --limit 15

# Recuperar un run específico
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --run XXXXXXX

# Recuperar todos los runs exitosos con costo > $0.01
venv\Scripts\python.exe -X utf8 recover_apify_runs.py --all
```
**Resultado de primera ejecución (18:50):** 342 leads insertados en leads_master

---

### ✅ CORRECCIÓN SUPABASE — ALTER TABLE columnas faltantes
**Hora ejecutado:** ~18:40 (múltiples rondas)
**Herramienta:** Supabase SQL Editor
**Columnas agregadas en rondas sucesivas:**
- Ronda 1: `actividad_digital_score INTEGER DEFAULT 0`
- Ronda 2: 14 columnas (apify_run_id, termino_busqueda, email_status, hierarchy_score, etc.)
- Ronda 3: 19 columnas más (facebook_url, instagram_url, rating, review_count, etc.)
- Ronda 4: DROP TABLE CASCADE + CREATE TABLE completa (solución definitiva)
**SQL final ejecutado:**
```sql
DROP TABLE IF EXISTS leads_master CASCADE;
CREATE TABLE leads_master (...); -- schema completo
CREATE UNIQUE INDEX lm_dedup ON leads_master(nombre_negocio, ciudad, cliente_id);
NOTIFY pgrst, 'reload schema';
```

---

### 📊 RESULTADOS DEL DÍA (2026-03-13)

| Búsqueda | Categorías | Apify items | Leads DB | Costo |
|---|---|---|---|---|
| Fábricas de tostadas — NL | 9 | 83 | 57* | $0.32 |
| Ferreterías — Monterrey NL | 7 | ~20 | pendiente | $0.03 |
| Pedreras — Santa Catarina/Escobedo NL | 7 | 58 | recuperados | $0.25 |
| Pedreras — Coahuila | 8 | ~60 | recuperados | $0.27 |
| Otros runs del día | varios | varios | recuperados | $0.36+$0.17+$0.18 |
| **TOTAL recuperado con recover_apify_runs.py** | — | — | **342** | — |

*Los 57 de tostadas fueron a `social_leads` (tabla vieja, antes de migrar a `leads_master`)

---

## 📅 HISTORIAL PREVIO A 2026-03-13

### Arquitectura Original (pre-2026-03-13)
El proyecto comenzó como sistema N8N + Apify + Anymailfinder + Supabase + Claude API.
Se documentó en `C:\Users\Dell\Downloads\CONTEXT.md` (archivo original adjunto por Zenon).

**Stack original planificado:**
- N8N para workflow automation
- Apify actor `compass/crawler-google-places` (luego se descubrió que es 404)
- Dos bases de datos separadas: "BIG ONE" (raw) y "REFINED DB" (procesada)
- Frontend HTML con 166 categorías

**Evolución al stack actual:**
El sistema N8N fue reemplazado por código Python directo con bot de Telegram,
que es más flexible y permite interacción en lenguaje natural.
Las dos BDs separadas se unificaron en `leads_master`.
El actor Apify se corrigió a `nwua9Gu5YrADL7ZDj`.

### Proyectos de Enriquecimiento (anteriores a 2026-03-13)
- **MACRISA:** 1,809 registros enriquecidos pendientes (bloqueado por límite Apify $45)
- **Regio Cribas (RC):** 2,832 registros pendientes, tabla `regio_cribas_enriched` sin crear

---

## 📝 NOTAS PARA FUTUROS DESARROLLOS

### Lo que funciona bien ✅
- El bot responde búsquedas en lenguaje natural correctamente
- Apify extrae datos de Google Maps de forma confiable
- El pipeline completo (scrape → enrich → score → insert) funciona
- La deduplicación por `(nombre_negocio, ciudad, cliente_id)` evita duplicados
- El caché de búsquedas evita pagar Apify dos veces por la misma búsqueda
- La herramienta de recuperación funciona para rescatar runs pagados

### Lo que hay que tener cuidado ⚠️
- **Timeout:** Búsquedas grandes pueden tardar más de 12 min → aumentar si es necesario
- **Tabla leads_master:** El schema debe coincidir exactamente con el código Python
- **Actor Apify:** SIEMPRE usar `nwua9Gu5YrADL7ZDj`, NO el actor viejo
- **Windows encoding:** SIEMPRE lanzar con `-X utf8`
- **Schema cache Supabase:** Después de ALTER TABLE, ejecutar `NOTIFY pgrst, 'reload schema'`

### Decisiones de arquitectura tomadas
1. **Una sola tabla `leads_master`** en vez de email_leads + social_leads separadas
   → Razón: Simplifica queries, elimina fragmentación, facilita el embudo de ventas
2. **Skip de Anymail si no hay sitio_web**
   → Razón: Sin dominio no hay email posible, ahorrar tiempo y créditos
3. **Un solo run de Apify con todos los términos**
   → Razón: Más eficiente que N runs separados, Apify deduplica internamente
4. **Bot de Telegram en vez de formulario web**
   → Razón: Más flexible, permite lenguaje natural, no requiere frontend
5. **Claude Haiku (no Sonnet)** para parseo de intención y expansión de categorías
   → Razón: Más rápido y barato para tareas estructuradas simples

---

*BITÁCORA actualizada el 2026-03-16 CST por Claude Code*
*Próxima actualización: al inicio de la siguiente sesión de trabajo*
