# LeadForge — Mapa de Flujos
### (Equivalente al canvas de n8n)
Última actualización: 2026-03-07

---

## ¿Cómo leer este documento?
Cada bloque `[ ]` es un "nodo" como en n8n.
Las flechas `→` son las conexiones entre nodos.
Los iconos indican el tipo: 🗄️ Base de datos | 🤖 IA | 📧 Email | 📱 WhatsApp | 🔔 Alerta

---

## FLUJO 1 — Importación de Leads a Base de Datos
**Archivo .exe:** `import_big_one.py` o `migrate_csv_to_supabase.py`
**Cuándo corre:** Manual (tú lo ejecutas) o cuando hay nuevos datos

```
[CSV Local]                     [Supabase DB]
Lista de Negocios               ┌─────────────────┐
BASE 2026.csv       →  Filtrar  │ DB1: email_leads │  32,830 registros
(651,955 filas)     →  Dedup    │ DB2: social_leads│ 376,702 registros
                    →  Validar  └─────────────────┘
                                        ↓
                              [Telegram] 🔔
                              "✅ Importación completa
                               +X email leads
                               +X social leads"
```

**Criterios de filtro aplicados:**
- ✅ Requiere nombre del negocio
- ✅ Email válido → va a DB1 (email_leads)
- ✅ Solo teléfono → va a DB2 (social_leads)
- ✅ Max 2 emails por dominio
- ✅ Sin duplicados (verifica contra Supabase antes de insertar)

---

## FLUJO 2 — Verificación de Emails con Anymail Finder
**Archivo .exe:** `python run.py --verify-leads`
**Cuándo corre:** Después de importar, antes de lanzar campaña
**⚠️ REQUIERE:** Créditos de Anymail Finder

```
[DB1: email_leads]
email_status = "unverified"   →  [Anymail Finder API]  →  Resultado:
(32,830 pendientes)               Verifica si el email       ✅ "valid"   → listo para campaña
                                  existe y recibe correo     ❌ "invalid" → descartado
                                                             ⚠️ "risky"  → en cola baja prioridad
                                                                    ↓
                                                          [DB1 actualizado]
                                                          email_status = "valid/invalid/risky"
                                                                    ↓
                                                          [Telegram] 🔔
                                                          "X emails verificados
                                                           Y válidos listos"
```

---

## FLUJO 3 — Lanzar Campaña de Email (Instantly.ai)
**Archivo .exe:** `python start_dashboard.py` → botón "Nueva Campaña"
**Cuándo corre:** Tú decides cuándo lanzar desde el dashboard

```
[Dashboard Web]          [Claude IA 🤖]           [Instantly.ai]
Tú llenas el wizard  →  Expande categorías    →   Crea campaña
- Producto               de compradores           - Asigna cuentas
- Ciudad                 "pinturas" →             - Inyecta leads
- Presupuesto            ferreterías,             - Programa envíos
                         maquiladoras, etc.
                                ↓
                    [DB1: email_leads]
                    Filtra: email_status = "valid"
                    Ordena: lead_score DESC
                    Toma: X leads para la campaña
                                ↓
                    [Instantly.ai] 📧
                    Envía emails con:
                    - Secuencia personalizada
                    - Rotación de cuentas
                    - Límite diario respetado
                                ↓
                    [Telegram] 🔔
                    "🚀 Campaña lanzada
                     X leads inyectados
                     Costo: $X.XX"
```

---

## FLUJO 4 — Respuesta de un Lead (Webhook)
**Archivo .exe:** Automático — `start_monitor.py` escucha en puerto 8001
**Cuándo corre:** Cada vez que alguien responde un email

```
[Lead responde email]
en Gmail/Outlook      →  [Instantly.ai]  →  [Webhook POST /webhook/instantly]
                          detecta la         puerto 8001 en tu computadora
                          respuesta                    ↓
                                            [Python procesa la respuesta]
                                            - Actualiza DB: respondio_email = true
                                            - Calcula score de respuesta
                                                        ↓
                                            [Telegram] 🔔
                                            "📩 RESPUESTA RECIBIDA
                                             Empresa: ACERO DEL NORTE SA
                                             Email: gerente@acero.com
                                             Score: 8/10
                                             Ver en Instantly →"
```

---

## FLUJO 5 — WhatsApp (Social Leads)
**Archivo .exe:** Parte del wizard de campaña
**Cuándo corre:** Simultáneo a la campaña de email

```
[DB2: social_leads]
estado_campania = "pendiente"   →  [yCloud API]  →  WhatsApp enviado
(376,702 disponibles)              Envía mensaje     - Delay 30 seg entre mensajes
                                   personalizado     - Máx 50 por lote
                                   al teléfono                ↓
                                                   [DB2 actualizado]
                                                   estado_campania = "enviado"
                                                              ↓
                                                   [Telegram] 🔔
                                                   "X WhatsApp enviados
                                                    Y fallidos"
```

---

## FLUJO 6 — Monitor de Salud del Sistema
**Archivo .exe:** `python start_monitor.py` (corre 24/7 en background)
**Cuándo corre:** Cada 30 minutos automáticamente

```
[Health Daemon]
cada 30 minutos  →  Verifica:
                    ✅ Supabase conectado?
                    ✅ Instantly.ai responde?
                    ✅ Créditos Anymail > 100?
                    ✅ Bounce rate < 3%?
                    ✅ Spam rate < 0.1%?
                              ↓
                    Todo OK:  [Silencio] (no molesta)
                    Problema: [Telegram] 🚨
                              "⚠️ ALERTA
                               Bounce rate: 4.2% (límite: 3%)
                               Acción: revisar dominio X"
```

---

## MAPA GENERAL (visión de n8n canvas)

```
FUENTES DE DATOS                   PROCESAMIENTO              DESTINOS
─────────────────                  ─────────────              ────────

[CSV DENUE/INEGI]  ─── Flujo 1 ──► [Supabase DB] ─── Flujo 3 ──► [Instantly.ai] ──► [Emails enviados]
651,955 negocios                   DB1: 32,830 ✅               📧 Campaña email      ↓
                                   DB2: 376,702 ✅                                [Respuestas] ──► [Telegram]
[CSV Apify/Google] ─── migrate ──►                ─── Flujo 5 ──► [yCloud/WA]
Leads con emails                                                   📱 WhatsApp

                                   [Anymail Finder] ── Flujo 2 ──► DB1 verificados

[Instantly Webhook] ─── Flujo 4 ──► [DB actualizado] ──────────────────────────► [Telegram]

[Health Daemon] ──── Flujo 6 ─────────────────────────────────────────────────► [Telegram]
```

---

## Estado Actual del Sistema (2026-03-07)

| Flujo | Estado | Pendiente |
|-------|--------|-----------|
| Flujo 1 — Importación | ✅ COMPLETO | México entero importado (32 estados) |
| Flujo 2 — Verificación | ⏳ PENDIENTE | Necesita créditos Anymail Finder |
| Flujo 3 — Campaña Email | ⏳ PENDIENTE | Esperando emails verificados |
| Flujo 4 — Webhook | ⏳ PENDIENTE | Necesita ngrok o Cloudflare Tunnel |
| Flujo 5 — WhatsApp | ⏳ PENDIENTE | Necesita configurar yCloud |
| Flujo 6 — Monitor | ✅ LISTO | Solo falta ejecutar start_monitor.py |

---

## El "Panel de Control" — Cómo arrancar todo

```bash
# Opción A: Solo Dashboard (lo que necesitas hoy)
python start_dashboard.py
# Abre: http://localhost:5000

# Opción B: Dashboard + Monitor + Webhook (sistema completo)
python start_dashboard.py --with-monitor

# Opción C: Solo importar más leads
python -X utf8 import_big_one.py --estado "Jalisco"

# Opción D: Verificar emails con Anymail
python -X utf8 run.py --verify-leads
```

---

## Próximos pasos en orden de prioridad

1. **Recargar créditos Anymail Finder** → Verificar los 32,830 emails
2. **Configurar ngrok o Cloudflare Tunnel** → Recibir respuestas automáticamente
3. **Lanzar primera campaña** desde el Dashboard → Wizard de IA
4. **Configurar yCloud** → Activar canal WhatsApp (376,702 teléfonos listos)
