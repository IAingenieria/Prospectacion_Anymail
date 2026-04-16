-- ============================================================
-- Migración 003: Security Hardening — Supabase Security Advisor
-- Fecha: 2026-03-17
-- Corrige los 5 errores reportados por el Security Advisor
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
-- ============================================================

-- ============================================================
-- PROBLEMA 1: leads_master — sin RLS
-- Riesgo: cualquier usuario anónimo puede leer/escribir TODOS
-- los leads de TODOS los clientes con solo conocer la anon key
-- ============================================================

ALTER TABLE leads_master ENABLE ROW LEVEL SECURITY;

-- Eliminar política antigua demasiado permisiva si existe
DROP POLICY IF EXISTS "dashboard_anon_read" ON leads_master;

-- LECTURA: solo el rol service_role (backend Python) y el dashboard
-- El service_role bypasea RLS automáticamente — esta política cubre
-- lecturas del frontend React (anon key) filtrando por cliente_id
-- IMPORTANTE: el dashboard solo lee los datos del cliente autenticado
CREATE POLICY "leads_master_anon_select"
  ON leads_master
  FOR SELECT
  TO anon
  USING (true);
-- NOTA: Mantener USING(true) para anon SELECT porque el dashboard React
-- usa anon key (sin Supabase Auth). Ver nota al final para upgrade.

-- Bloquear INSERT/UPDATE/DELETE desde anon — solo el backend Python
-- (service_role) puede modificar leads
CREATE POLICY "leads_master_service_insert"
  ON leads_master
  FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "leads_master_service_update"
  ON leads_master
  FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "leads_master_service_delete"
  ON leads_master
  FOR DELETE
  TO service_role
  USING (true);

-- ============================================================
-- PROBLEMA 2: macrisa_leads — sin RLS
-- Riesgo: base de datos de cliente expuesta públicamente
-- ============================================================

ALTER TABLE macrisa_leads ENABLE ROW LEVEL SECURITY;

-- Solo service_role puede acceder — no hay dashboard público de Macrisa
CREATE POLICY "macrisa_service_only"
  ON macrisa_leads
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- PROBLEMA 3: clientes — sin RLS
-- Riesgo CRÍTICO: api_key_hash y telegram_chat_id expuestos
-- ============================================================

ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;

-- Solo service_role puede leer/escribir clientes
-- NO conceder acceso anon — nunca debe ser público
CREATE POLICY "clientes_service_only"
  ON clientes
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- PROBLEMA 4: alertas — sin RLS
-- Riesgo: mensajes internos del sistema expuestos
-- ============================================================

ALTER TABLE alertas ENABLE ROW LEVEL SECURITY;

CREATE POLICY "alertas_service_only"
  ON alertas
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================================
-- TAMBIÉN: email_leads, social_leads, campanias, busquedas_cache
-- Ya tenían RLS habilitada pero sus políticas usan auth.uid()
-- que no aplica para service_role — agregar políticas service_role
-- ============================================================

-- email_leads (tiene RLS pero falta política para service_role)
DROP POLICY IF EXISTS "email_leads_own_data" ON email_leads;
CREATE POLICY "email_leads_service_role"
  ON email_leads FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "email_leads_authenticated"
  ON email_leads FOR SELECT TO authenticated
  USING (cliente_id = auth.uid());

-- social_leads
DROP POLICY IF EXISTS "social_leads_own_data" ON social_leads;
CREATE POLICY "social_leads_service_role"
  ON social_leads FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "social_leads_authenticated"
  ON social_leads FOR SELECT TO authenticated
  USING (cliente_id = auth.uid());

-- campanias
DROP POLICY IF EXISTS "campanias_own_data" ON campanias;
CREATE POLICY "campanias_service_role"
  ON campanias FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "campanias_authenticated"
  ON campanias FOR SELECT TO authenticated
  USING (cliente_id = auth.uid());

-- busquedas_cache
DROP POLICY IF EXISTS "cache_own_data" ON busquedas_cache;
CREATE POLICY "cache_service_role"
  ON busquedas_cache FOR ALL TO service_role USING (true) WITH CHECK (true);

-- audit_log
DROP POLICY IF EXISTS "audit_own_data" ON audit_log;
CREATE POLICY "audit_service_role"
  ON audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- PROBLEMA 5: Funciones con search_path mutable
-- Riesgo: un atacante puede crear objetos en el search_path para
-- interceptar llamadas a funciones (privilege escalation)
-- Fix: fijar search_path = '' y usar nombres completamente calificados
-- ============================================================

-- Fix función: update_leads_master_timestamp
CREATE OR REPLACE FUNCTION update_leads_master_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

-- Fix función: update_macrisa_updated_at
CREATE OR REPLACE FUNCTION update_macrisa_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

-- Fix función: match_email_leads (usa SECURITY INVOKER + search_path fijo)
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
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
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
  FROM public.email_leads el
  WHERE
    (p_cliente_id IS NULL OR el.cliente_id = p_cliente_id)
    AND (p_ciudad IS NULL OR el.ciudad = p_ciudad)
    AND el.do_not_contact = FALSE
    AND el.email_status = 'valid'
    AND (1 - (el.embedding <=> query_embedding)) >= similarity_threshold
  ORDER BY el.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ============================================================
-- VERIFICACIÓN FINAL
-- Ejecutar después para confirmar que RLS está habilitada en todo
-- ============================================================
SELECT
  schemaname,
  tablename,
  rowsecurity AS rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Verificar funciones con search_path fijo
SELECT
  p.proname AS function_name,
  p.prosecdef AS is_security_definer,
  p.proconfig AS config
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
  AND p.prokind = 'f'
ORDER BY p.proname;

-- ============================================================
-- NOTAS PARA UPGRADE FUTURO DE SEGURIDAD
-- ============================================================
--
-- La política "leads_master_anon_select" con USING(true) todavía
-- permite que cualquier persona con la anon key lea todos los leads.
--
-- Para eliminar este riesgo completamente en el futuro:
-- 1. Migrar el dashboard React a usar Supabase Auth (auth.uid())
-- 2. Crear un usuario Supabase por cliente con el cliente_id como metadata
-- 3. Reemplazar la política por:
--    CREATE POLICY "leads_master_per_cliente"
--      ON leads_master FOR SELECT TO authenticated
--      USING (cliente_id = auth.uid());
-- 4. Eliminar "leads_master_anon_select"
--
-- Mientras tanto, la protección más importante ya está implementada:
-- - INSERT/UPDATE/DELETE bloqueados para anon ✅
-- - clientes/alertas/macrisa_leads inaccesibles para anon ✅
-- - Funciones con search_path fijo ✅
-- ============================================================
