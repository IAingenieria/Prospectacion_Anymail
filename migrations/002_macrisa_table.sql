-- ============================================================
-- Migración 002: Tabla MACRISA — Base de datos separada
-- Fecha: 2026-03-16
-- Cliente: Macrisa (base de datos propia del cliente)
-- NOTA: Esta tabla es COMPLETAMENTE independiente de leads_master
-- ============================================================

CREATE TABLE IF NOT EXISTS macrisa_leads (
  -- Identificadores
  id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  id_original       INTEGER,                    -- ID del Excel original

  -- Datos del negocio
  nombre            TEXT NOT NULL,
  municipio         TEXT,
  estado            TEXT,
  tipo              TEXT,                       -- 'empresa' | 'persona'
  ubicacion         TEXT,

  -- Contacto
  website           TEXT,
  telefono          TEXT,
  email             TEXT,
  email_status      TEXT DEFAULT 'pendiente_validacion',
  facebook          TEXT,
  instagram         TEXT,
  linkedin          TEXT,

  -- Metadata de origen
  fuente            TEXT,                       -- 'google_maps' | etc.
  confianza         TEXT,                       -- 'alta' | 'baja'
  notas             TEXT,                       -- ratings, reseñas, etc.

  -- Cross-reference con leads_master
  en_leads_master   BOOLEAN DEFAULT FALSE,      -- ¿Existe en la DB general?
  leads_master_id   UUID,                       -- ID del match en leads_master
  tipo_match        TEXT,                       -- 'nombre' | 'telefono' | 'email'

  -- AnyMailFinder
  anymail_procesado BOOLEAN DEFAULT FALSE,
  anymail_creditos  FLOAT DEFAULT 0,

  -- Calidad
  calidad_stars     INTEGER DEFAULT 1 CHECK (calidad_stars BETWEEN 1 AND 5),

  -- Timestamps
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ── Índices ──────────────────────────────────────────────────────────────────

-- Búsqueda por nombre (para cross-reference y deduplicación)
CREATE INDEX IF NOT EXISTS idx_macrisa_nombre
  ON macrisa_leads (nombre);

-- Búsqueda por email (para verificación AnyMailFinder)
CREATE INDEX IF NOT EXISTS idx_macrisa_email
  ON macrisa_leads (email)
  WHERE email IS NOT NULL;

-- Leads pendientes de verificar
CREATE INDEX IF NOT EXISTS idx_macrisa_email_status
  ON macrisa_leads (email_status)
  WHERE email IS NOT NULL;

-- Leads con website (para encontrar emails)
CREATE INDEX IF NOT EXISTS idx_macrisa_website
  ON macrisa_leads (website)
  WHERE website IS NOT NULL;

-- Filtros frecuentes
CREATE INDEX IF NOT EXISTS idx_macrisa_estado
  ON macrisa_leads (estado);

CREATE INDEX IF NOT EXISTS idx_macrisa_municipio
  ON macrisa_leads (municipio);

-- ── Trigger: updated_at automático ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_macrisa_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER macrisa_updated_at
  BEFORE UPDATE ON macrisa_leads
  FOR EACH ROW EXECUTE FUNCTION update_macrisa_updated_at();

-- ── Verificar resultado ───────────────────────────────────────────────────────
SELECT 'Tabla macrisa_leads creada correctamente' AS resultado;
