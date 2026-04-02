-- ============================================================
-- LeadForge — Tabla UNIFICADA: leads_master
-- Reemplaza email_leads + social_leads en UNA sola tabla
-- Contiene: datos crudos de Apify + enriquecimiento + embudo
-- Ejecutar en Supabase SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS leads_master (

  -- ── IDENTIDAD ─────────────────────────────────────────────
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id      UUID NOT NULL DEFAULT 'a0000000-0000-0000-0000-000000000001',

  -- ── DATOS CRUDOS APIFY (BIG ONE) ─────────────────────────
  nombre_negocio  TEXT NOT NULL,
  categoria       TEXT,                     -- categoryName de Google Maps
  ciudad          TEXT,
  estado          TEXT,
  pais            TEXT DEFAULT 'MX',
  direccion       TEXT,                     -- street address completa
  sitio_web       TEXT,
  telefono        TEXT,
  facebook_url    TEXT,
  instagram_url   TEXT,
  rating          NUMERIC(3,1),             -- 0.0 – 5.0
  review_count    INTEGER DEFAULT 0,
  google_maps_url TEXT,                     -- URL directa al lugar
  apify_run_id    TEXT,
  termino_busqueda TEXT,                    -- término que lo encontró

  -- ── ENRIQUECIMIENTO ANYMAIL ───────────────────────────────
  email           TEXT,                     -- email encontrado (puede ser null)
  email_status    TEXT,                     -- valid | catch_all | not_valid | null
  hierarchy_score INTEGER DEFAULT 0,        -- 0-100 jerarquía del email
  anymail_procesado BOOLEAN DEFAULT FALSE,  -- ¿ya se buscó email?

  -- ── EXTRACCIÓN DE DUEÑO ───────────────────────────────────
  owner_name      TEXT,
  cargo_inferido  TEXT,

  -- ── SCORE DEL LEAD ────────────────────────────────────────
  lead_score      INTEGER DEFAULT 0,        -- 0-100 score compuesto
  canal_recomendado TEXT,                   -- email | whatsapp | instagram | llamada

  -- ── EMBUDO DE VENTAS ─────────────────────────────────────
  -- Etapas: nuevo → calificado → contactado → abierto → respondio
  --         → interesado → reunion → propuesta → cliente → descartado
  etapa           TEXT NOT NULL DEFAULT 'nuevo',

  -- ── SEGUIMIENTO EMAIL ─────────────────────────────────────
  campania_id     TEXT,                     -- ID campaña Instantly.ai
  instantly_lead_id TEXT,
  fecha_envio_email   TIMESTAMPTZ,
  email_abierto       BOOLEAN DEFAULT FALSE,
  fecha_apertura      TIMESTAMPTZ,
  veces_abierto       INTEGER DEFAULT 0,
  respondio_email     BOOLEAN DEFAULT FALSE,
  fecha_respuesta_email TIMESTAMPTZ,
  texto_respuesta_email TEXT,

  -- ── SEGUIMIENTO WHATSAPP ──────────────────────────────────
  whatsapp_enviado    BOOLEAN DEFAULT FALSE,
  fecha_envio_whatsapp TIMESTAMPTZ,
  respondio_whatsapp   BOOLEAN DEFAULT FALSE,
  fecha_respuesta_whatsapp TIMESTAMPTZ,
  texto_respuesta_whatsapp TEXT,

  -- ── SEGUIMIENTO INSTAGRAM / FACEBOOK ─────────────────────
  dm_enviado          BOOLEAN DEFAULT FALSE,
  fecha_envio_dm      TIMESTAMPTZ,
  respondio_dm        BOOLEAN DEFAULT FALSE,

  -- ── NOTAS Y CONTROL ───────────────────────────────────────
  notas           TEXT,                     -- notas manuales del vendedor
  do_not_contact  BOOLEAN DEFAULT FALSE,
  motivo_baja     TEXT,
  actividad_digital_score INTEGER DEFAULT 0,

  -- ── METADATA ──────────────────────────────────────────────
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  scraped_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── ÍNDICES ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS lm_cliente      ON leads_master(cliente_id);
CREATE INDEX IF NOT EXISTS lm_etapa        ON leads_master(etapa);
CREATE INDEX IF NOT EXISTS lm_email        ON leads_master(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS lm_telefono     ON leads_master(telefono) WHERE telefono IS NOT NULL;
CREATE INDEX IF NOT EXISTS lm_ciudad       ON leads_master(ciudad);
CREATE INDEX IF NOT EXISTS lm_lead_score   ON leads_master(lead_score DESC);
CREATE INDEX IF NOT EXISTS lm_created      ON leads_master(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS lm_dedup ON leads_master(nombre_negocio, ciudad, cliente_id);

-- ── AUTO-UPDATE updated_at ────────────────────────────────────
CREATE OR REPLACE FUNCTION update_leads_master_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_leads_master_updated ON leads_master;
CREATE TRIGGER set_leads_master_updated
  BEFORE UPDATE ON leads_master
  FOR EACH ROW EXECUTE FUNCTION update_leads_master_timestamp();

-- ── VISTA: EMBUDO DE VENTAS ───────────────────────────────────
CREATE OR REPLACE VIEW embudo_ventas AS
SELECT
  etapa,
  COUNT(*)                                    AS total,
  COUNT(*) FILTER (WHERE email IS NOT NULL)   AS con_email,
  COUNT(*) FILTER (WHERE telefono IS NOT NULL) AS con_telefono,
  ROUND(AVG(lead_score), 1)                   AS score_promedio,
  COUNT(*) FILTER (WHERE respondio_email OR respondio_whatsapp OR respondio_dm) AS respondieron
FROM leads_master
WHERE do_not_contact = FALSE
GROUP BY etapa
ORDER BY
  ARRAY_POSITION(
    ARRAY['nuevo','calificado','contactado','abierto','respondio',
          'interesado','reunion','propuesta','cliente','descartado'],
    etapa
  );

-- ── VISTA: LEADS CALIENTES (score > 60 sin contactar) ─────────
CREATE OR REPLACE VIEW leads_calientes AS
SELECT
  nombre_negocio, ciudad, estado, telefono, email,
  sitio_web, facebook_url, instagram_url,
  lead_score, canal_recomendado, etapa, categoria, created_at
FROM leads_master
WHERE lead_score > 60
  AND etapa = 'nuevo'
  AND do_not_contact = FALSE
ORDER BY lead_score DESC;

-- ── VISTA: MÉTRICAS DIARIAS ───────────────────────────────────
CREATE OR REPLACE VIEW metricas_diarias AS
SELECT
  DATE(created_at) AS fecha,
  COUNT(*)          AS leads_nuevos,
  COUNT(*) FILTER (WHERE email IS NOT NULL) AS con_email,
  COUNT(*) FILTER (WHERE email_abierto)     AS emails_abiertos,
  COUNT(*) FILTER (WHERE respondio_email)   AS respondieron,
  ROUND(AVG(lead_score), 1)                 AS score_promedio
FROM leads_master
GROUP BY DATE(created_at)
ORDER BY fecha DESC;

-- ============================================================
-- RESULTADO ESPERADO:
-- ✅ Tabla leads_master creada
-- ✅ Vista embudo_ventas
-- ✅ Vista leads_calientes
-- ✅ Vista metricas_diarias
-- ============================================================
