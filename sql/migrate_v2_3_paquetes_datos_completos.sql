-- ============================================================
-- Migración v2.3 — paquetes: datos completos de destinatario,
--                  remitente, paquete y ruta logística
--
-- Agrega las columnas que el modelo Paquete define en v2.3
-- pero que no existían en la BD.
--
-- Idempotente: usa ADD COLUMN IF NOT EXISTS.
-- ============================================================

-- ── Destinatario (complemento) ───────────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_cp        VARCHAR(20);

-- ── Remitente (dirección completa) ───────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_provincia    VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_ciudad       VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_area         VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_direccion    VARCHAR(500);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_cp           VARCHAR(20);

-- ── Paquete (complemento) ────────────────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS nombre_mercancia       VARCHAR(200);   -- goodsName

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS tipo_servicio          VARCHAR(100);   -- expressTypeName

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS peso_volumetrico       DOUBLE PRECISION; -- packageVolume (kg)

-- ── Ruta logística ───────────────────────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS pdv_recojo             VARCHAR(200);   -- realPickNetworkName

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS hub_origen             VARCHAR(200);   -- initDistributeName

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS hub_destino            VARCHAR(200);   -- destinationDistributeName
