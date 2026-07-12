-- ============================================================
-- Migración v2.5 — Segunda capa de verificación de red (ARE)
--
-- Contexto: se detectó contaminación cruzada — waybills de OTROS
-- franquiciados (ej. ARE-11, ARE-22) apareciendo en la cuenta de un
-- franquiciado distinto. Causa raíz: el filtro `recevierNetworkCode`
-- que el scraper OutletMonitor envía a la API de J&T no siempre filtra
-- correctamente en el backend de J&T (ver jt_scraper/outlet_monitor.py).
--
-- Esta migración agrega:
--   1. franquiciados.jt_network_code — código de red esperado (ej. "ARE-22")
--      que el admin configura manualmente por franquiciado.
--   2. paquetes.red_detectada / red_sospechosa — marca retroactiva cuando
--      el detalle de un paquete ya importado no coincide con la red
--      esperada (detecta contaminación previa a esta migración).
--   3. waybills_rechazados — auditoría de los waybills que el scraper
--      descarta en el momento de la sincronización por no coincidir.
--   4. excel_imports.rechazados — contador visible en el log de imports.
--
-- Idempotente: usa IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- ============================================================

ALTER TABLE franquiciados
    ADD COLUMN IF NOT EXISTS jt_network_code VARCHAR(50);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS red_detectada  VARCHAR(200),
    ADD COLUMN IF NOT EXISTS red_sospechosa BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE excel_imports
    ADD COLUMN IF NOT EXISTS rechazados INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS waybills_rechazados (
    id              SERIAL       PRIMARY KEY,
    franquiciado_id INTEGER      NOT NULL
                    REFERENCES franquiciados(id) ON DELETE CASCADE,
    waybill_no      VARCHAR(120) NOT NULL,
    red_detectada   VARCHAR(200),
    red_esperada    VARCHAR(50),
    origen          VARCHAR(20)  NOT NULL DEFAULT 'sync',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_waybills_rechazados_franq
    ON waybills_rechazados(franquiciado_id, created_at DESC);

-- ── Después de aplicar esta migración ──────────────────────────
-- 1. Ir a cada franquiciado en el panel Admin y completar "Código de red
--    JMS (ARE)" (visible en jms.jtlac.com como RECEIVER_NETWORK_NAME de
--    sus paquetes, ej. "ARE-22").
-- 2. Correr el cron de tracking una vez para que _verificar_red() marque
--    retroactivamente los paquetes 'pendiente' cuya red no coincide:
--      SELECT p.id, p.waybill_no, p.franquiciado_id, p.red_detectada
--      FROM paquetes p
--      WHERE p.red_sospechosa = TRUE;
