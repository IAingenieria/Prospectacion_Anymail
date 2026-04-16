-- ================================================================
-- Migración 004: RFC, redes sociales y fuente en leads_master
-- Ejecutar en Supabase SQL Editor
-- ================================================================

-- RFC de la empresa (dato oficial DENUE/SAT)
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS rfc TEXT;

-- Fuente del lead: 'denue' | 'google_maps' | 'apify' | 'manual'
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS fuente TEXT DEFAULT 'denue';

-- Redes sociales (por si no existen aún)
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS facebook_url TEXT;
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS instagram_url TEXT;
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS whatsapp TEXT;

-- Canal de prospección recomendado
ALTER TABLE leads_master ADD COLUMN IF NOT EXISTS canal_recomendado TEXT;

-- Índices para búsquedas frecuentes
CREATE INDEX IF NOT EXISTS idx_leads_master_rfc ON leads_master(rfc) WHERE rfc IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_master_fuente ON leads_master(fuente);
CREATE INDEX IF NOT EXISTS idx_leads_master_canal ON leads_master(canal_recomendado);
