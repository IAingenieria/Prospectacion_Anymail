-- ================================================================
-- Migración 005: Campos para Web Enricher
-- Agrega columnas de redes sociales extendidas + tracking de enriquecimiento
--
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
-- Fecha: 2026-04-02
-- ================================================================

-- ── leads_master: redes sociales extendidas ──────────────────────────────────
-- facebook_url e instagram_url ya existen (migración 004)
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS linkedin_url   TEXT;
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS twitter_url    TEXT;
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS tiktok_url     TEXT;
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS youtube_url    TEXT;

-- ── leads_master: tracking del web enricher ──────────────────────────────────
-- Fecha en que se ejecutó el web enricher sobre este lead
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS email_enriched_at TIMESTAMPTZ;

-- email_status ya existe — nuevos valores válidos:
--   'web_found'    → email encontrado scrapeando el sitio web del negocio
--   'google_found' → email encontrado en resultados de búsqueda (DuckDuckGo)
--   'apify_found'  → email encontrado via Apify Place Details
--   'amf_found'    → email encontrado via AnyMailFinder
--   'not_found'    → web enricher no encontró nada
-- (son TEXT libre — no hace falta ENUM constraint)

-- ── social_leads: redes sociales extendidas ──────────────────────────────────
ALTER TABLE social_leads ADD COLUMN IF NOT EXISTS linkedin_url   TEXT;
ALTER TABLE social_leads ADD COLUMN IF NOT EXISTS twitter_url    TEXT;
ALTER TABLE social_leads ADD COLUMN IF NOT EXISTS tiktok_url     TEXT;
ALTER TABLE social_leads ADD COLUMN IF NOT EXISTS youtube_url    TEXT;

-- ── Índices para búsquedas por redes sociales ────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_leads_master_linkedin
    ON leads_master(linkedin_url) WHERE linkedin_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_master_twitter
    ON leads_master(twitter_url) WHERE twitter_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_master_tiktok
    ON leads_master(tiktok_url) WHERE tiktok_url IS NOT NULL;

-- Índice para encontrar leads pendientes de enriquecimiento web
CREATE INDEX IF NOT EXISTS idx_leads_master_enriched_at
    ON leads_master(email_enriched_at) WHERE email_enriched_at IS NULL;

-- ── Verificar columnas creadas ────────────────────────────────────────────────
-- Ejecuta esto después para confirmar:
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'leads_master'
--   AND column_name IN (
--     'linkedin_url', 'twitter_url', 'tiktok_url', 'youtube_url',
--     'email_enriched_at'
--   )
-- ORDER BY column_name;
