-- ============================================================
-- Migración 001: Columnas DENUE + Calidad Stars en leads_master
-- Fecha: 2026-03-16
-- Ejecutar en: Supabase SQL Editor
-- ============================================================

-- 1. Identificador único DENUE (CLEE — Clave de Localización de Establecimientos)
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS denue_id TEXT;

-- 2. Razón social oficial (nombre legal registrado en INEGI)
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS razon_social TEXT;

-- 3. Coordenadas GPS (de DENUE — más precisas que Google Maps)
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS latitud DOUBLE PRECISION;

ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS longitud DOUBLE PRECISION;

-- 4. Fuente de los datos: 'apify' | 'denue' | 'apify+denue' | 'manual'
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS fuente_datos TEXT DEFAULT 'apify';

-- 5. ¿El lead fue confirmado/enriquecido por DENUE?
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS denue_confirmado BOOLEAN DEFAULT FALSE;

-- 6. Fecha del último enriquecimiento DENUE
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS denue_enriched_at TIMESTAMPTZ;

-- 7. Calidad del lead: 1-5 estrellas
--    1★ = solo nombre/ciudad
--    2★ = tiene teléfono o email
--    3★ = teléfono + dirección o DENUE confirmado
--    4★ = email verificado + teléfono
--    5★ = dos fuentes + email valid + teléfono + web
ALTER TABLE leads_master
  ADD COLUMN IF NOT EXISTS calidad_stars INTEGER DEFAULT 1
  CHECK (calidad_stars BETWEEN 1 AND 5);

-- ============================================================
-- Índices para consultas frecuentes
-- ============================================================

-- Buscar leads por calidad (para campañas — primero los mejores)
CREATE INDEX IF NOT EXISTS idx_leads_master_calidad_stars
  ON leads_master (cliente_id, calidad_stars DESC);

-- Buscar por DENUE ID (para evitar duplicados)
CREATE INDEX IF NOT EXISTS idx_leads_master_denue_id
  ON leads_master (denue_id)
  WHERE denue_id IS NOT NULL;

-- Buscar leads con/sin DENUE (para batch enrichment)
CREATE INDEX IF NOT EXISTS idx_leads_master_denue_confirmado
  ON leads_master (cliente_id, denue_confirmado);

-- Búsqueda geoespacial aproximada (por coordenadas)
CREATE INDEX IF NOT EXISTS idx_leads_master_coords
  ON leads_master (latitud, longitud)
  WHERE latitud IS NOT NULL AND longitud IS NOT NULL;

-- ============================================================
-- Actualizar leads existentes con fuente_datos = 'apify'
-- (los que ya tienen apify_run_id)
-- ============================================================
UPDATE leads_master
SET fuente_datos = 'apify'
WHERE fuente_datos IS NULL
  AND apify_run_id IS NOT NULL;

UPDATE leads_master
SET fuente_datos = 'manual'
WHERE fuente_datos IS NULL
  AND apify_run_id IS NULL;

-- ============================================================
-- Calcular calidad_stars para leads existentes
-- (lógica simplificada en SQL)
-- ============================================================
UPDATE leads_master
SET calidad_stars = CASE
  -- 5 estrellas: email válido + teléfono + web + (denue OR apify)
  WHEN email_status = 'valid'
    AND telefono IS NOT NULL
    AND sitio_web IS NOT NULL
    AND apify_run_id IS NOT NULL
    THEN 5

  -- 4 estrellas: email válido + teléfono
  WHEN email_status = 'valid'
    AND telefono IS NOT NULL
    THEN 4

  -- 3 estrellas: email + teléfono (sin verificar) O datos completos
  WHEN email IS NOT NULL
    AND telefono IS NOT NULL
    THEN 3

  -- 2 estrellas: tiene email O teléfono
  WHEN email IS NOT NULL OR telefono IS NOT NULL
    THEN 2

  -- 1 estrella: solo nombre y ciudad
  ELSE 1
END
WHERE calidad_stars = 1 OR calidad_stars IS NULL;

-- ============================================================
-- Verificar resultado
-- ============================================================
SELECT
  calidad_stars,
  COUNT(*) as total,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as porcentaje
FROM leads_master
GROUP BY calidad_stars
ORDER BY calidad_stars DESC;
