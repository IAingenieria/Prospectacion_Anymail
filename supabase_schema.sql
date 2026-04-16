-- ============================================================
-- LEADFORGE — Schema de Supabase
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
-- ============================================================

-- Habilitar extensión pgvector (búsqueda semántica)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLA DE CLIENTES (multi-tenant)
-- ============================================================
CREATE TABLE IF NOT EXISTS clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    api_key_hash TEXT NOT NULL,         -- bcrypt hash, nunca en texto plano
    telegram_chat_id BIGINT,            -- para notificaciones del cliente
    plan TEXT DEFAULT 'starter',        -- starter | growth | agency
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT plan_valido CHECK (plan IN ('starter', 'growth', 'agency'))
);

-- ============================================================
-- DB1: LEADS DE EMAIL (para Instantly.ai)
-- ============================================================
CREATE TABLE IF NOT EXISTS email_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,

    -- Datos del negocio
    nombre_negocio TEXT NOT NULL,
    categoria TEXT,
    ciudad TEXT,
    estado TEXT,
    pais TEXT DEFAULT 'Mexico',
    direccion_completa TEXT,
    sitio_web TEXT,
    telefono TEXT,

    -- Email
    email TEXT NOT NULL,
    email_status TEXT,                  -- valid | likely_valid | invalid | unknown
    hierarchy_score INTEGER DEFAULT 0, -- 0-100: ceo@=100, info@=5
    lead_score INTEGER DEFAULT 0,      -- 0-100: score compuesto

    -- Datos del propietario (extraídos de reseñas)
    owner_name TEXT,
    cargo_inferido TEXT,
    owner_extraction_confidence FLOAT,

    -- Datos de Google Maps
    rating FLOAT,
    review_count INTEGER,
    responds_to_reviews BOOLEAN DEFAULT FALSE,

    -- Redes sociales
    facebook_url TEXT,
    instagram_url TEXT,

    -- Metadata del scraping
    apify_run_id TEXT,
    perfil_apify TEXT,                 -- alta_densidad | media_densidad | baja_densidad
    termino_busqueda TEXT,             -- el término exacto usado en Google Maps
    config_version TEXT,               -- hash del JSON de Apify usado

    -- Embedding para búsqueda semántica
    embedding VECTOR(1536),

    -- Control de campaña
    campania_id TEXT,
    instantly_lead_id TEXT,
    estado_campania TEXT DEFAULT 'pendiente',
    fecha_envio_email TIMESTAMPTZ,
    respondio_email BOOLEAN DEFAULT FALSE,
    fecha_respuesta TIMESTAMPTZ,

    -- Compliance
    do_not_contact BOOLEAN DEFAULT FALSE,
    fecha_baja TIMESTAMPTZ,
    motivo_baja TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- DB2: LEADS DE WHATSAPP/SOCIAL (para yCloud + ManyChat)
-- ============================================================
CREATE TABLE IF NOT EXISTS social_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,

    -- Referencia al lead de email (si existe)
    email_lead_id UUID REFERENCES email_leads(id),

    -- Datos del negocio
    nombre_negocio TEXT NOT NULL,
    categoria TEXT,
    ciudad TEXT,
    estado_geografico TEXT,            -- estado geográfico (Nuevo León, CDMX, etc.)
    telefono TEXT,

    -- Social media
    facebook_url TEXT,
    instagram_handle TEXT,
    seguidores_facebook INTEGER,
    seguidores_instagram INTEGER,
    dias_ultimo_post INTEGER,          -- cuántos días desde el último post
    actividad_digital_score INTEGER,   -- 0-100

    -- Datos del propietario
    owner_name TEXT,

    -- Mensaje personalizado (generado por Claude)
    mensaje_whatsapp TEXT,
    mensaje_facebook_dm TEXT,
    mensaje_instagram_dm TEXT,

    -- Control de campaña
    canal_asignado TEXT,               -- whatsapp | facebook_dm | instagram_dm
    estado_campania TEXT DEFAULT 'pendiente',  -- pendiente | enviado | leido | respondio | cerrado
    fecha_envio TIMESTAMPTZ,
    respondio BOOLEAN DEFAULT FALSE,
    texto_respuesta TEXT,

    -- Compliance
    do_not_contact BOOLEAN DEFAULT FALSE,

    -- Embedding
    embedding VECTOR(1536),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- CACHÉ DE BÚSQUEDAS (para no pagar Apify dos veces)
-- ============================================================
CREATE TABLE IF NOT EXISTS busquedas_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,
    termino_busqueda TEXT NOT NULL,
    ciudad TEXT NOT NULL,
    pais TEXT DEFAULT 'Mexico',
    perfil_apify TEXT,
    config_hash TEXT,                  -- hash del JSON de Apify
    total_resultados INTEGER,
    leads_validos INTEGER,
    costo_apify_usd FLOAT,
    costo_anymail_creditos INTEGER,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    expira_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '45 days',
    UNIQUE(termino_busqueda, ciudad, pais, cliente_id)
);

-- ============================================================
-- CAMPAÑAS
-- ============================================================
CREATE TABLE IF NOT EXISTS campanias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    producto_descripcion TEXT,
    categoria_objetivo TEXT,
    ciudad TEXT,
    instantly_campaign_id TEXT,
    canal TEXT DEFAULT 'email',        -- email | whatsapp | social
    estado TEXT DEFAULT 'activa',
    leads_total INTEGER DEFAULT 0,
    leads_enviados INTEGER DEFAULT 0,
    opens INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    reuniones INTEGER DEFAULT 0,
    costo_total_usd FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id),
    accion TEXT NOT NULL,
    recurso_tipo TEXT,
    recurso_id TEXT,
    ip_address INET,
    detalles JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ALERTAS DEL SISTEMA
-- ============================================================
CREATE TABLE IF NOT EXISTS alertas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes(id),
    tipo TEXT NOT NULL,                -- api_error | bounce_rate | creditos_bajos | reply
    severidad TEXT DEFAULT 'warning',  -- info | warning | critical
    mensaje TEXT NOT NULL,
    resuelta BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ÍNDICES PARA PERFORMANCE
-- ============================================================
-- Índices vectoriales para búsqueda semántica
CREATE INDEX IF NOT EXISTS idx_email_leads_embedding
    ON email_leads USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_social_leads_embedding
    ON social_leads USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Índices de búsqueda comunes
CREATE INDEX IF NOT EXISTS idx_email_leads_cliente_categoria
    ON email_leads(cliente_id, categoria, ciudad);
CREATE INDEX IF NOT EXISTS idx_email_leads_email
    ON email_leads(email);
CREATE INDEX IF NOT EXISTS idx_email_leads_status
    ON email_leads(email_status, do_not_contact);
CREATE INDEX IF NOT EXISTS idx_busquedas_cache_lookup
    ON busquedas_cache(termino_busqueda, ciudad, cliente_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_cliente
    ON audit_log(cliente_id, timestamp);

-- ============================================================
-- ROW LEVEL SECURITY (RLS) — Ningún cliente ve datos de otro
-- ============================================================
ALTER TABLE email_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanias ENABLE ROW LEVEL SECURITY;
ALTER TABLE busquedas_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Política: solo acceder a registros propios
CREATE POLICY "email_leads_own_data" ON email_leads
    USING (cliente_id = auth.uid());

CREATE POLICY "social_leads_own_data" ON social_leads
    USING (cliente_id = auth.uid());

CREATE POLICY "campanias_own_data" ON campanias
    USING (cliente_id = auth.uid());

CREATE POLICY "cache_own_data" ON busquedas_cache
    USING (cliente_id = auth.uid());

CREATE POLICY "audit_own_data" ON audit_log
    USING (cliente_id = auth.uid());

-- ============================================================
-- FUNCIÓN: Búsqueda semántica de leads similares
-- ============================================================
CREATE OR REPLACE FUNCTION match_email_leads(
    query_embedding VECTOR(1536),
    similarity_threshold FLOAT DEFAULT 0.82,
    match_count INT DEFAULT 50,
    p_cliente_id UUID DEFAULT NULL,
    p_ciudad TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    nombre_negocio TEXT,
    email TEXT,
    categoria TEXT,
    ciudad TEXT,
    lead_score INT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        el.id,
        el.nombre_negocio,
        el.email,
        el.categoria,
        el.ciudad,
        el.lead_score,
        1 - (el.embedding <=> query_embedding) AS similarity
    FROM email_leads el
    WHERE
        (p_cliente_id IS NULL OR el.cliente_id = p_cliente_id)
        AND (p_ciudad IS NULL OR el.ciudad = p_ciudad)
        AND el.do_not_contact = FALSE
        AND el.email_status = 'valid'
        AND (1 - (el.embedding <=> query_embedding)) >= similarity_threshold
    ORDER BY el.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- USUARIO DE SERVICIO (para el backend de LeadForge)
-- Ejecutar como superusuario de Supabase
-- ============================================================
-- NOTA: En el dashboard de Supabase, crea un Service Role key
-- y úsala en el .env como SUPABASE_SERVICE_KEY
-- Esa key tiene acceso completo y bypasea RLS

-- ============================================================
-- VERIFICACIÓN
-- ============================================================
-- Después de ejecutar este script, verificar:
-- SELECT * FROM pg_tables WHERE schemaname = 'public';
-- Deberías ver: clientes, email_leads, social_leads, busquedas_cache,
--              campanias, audit_log, alertas
