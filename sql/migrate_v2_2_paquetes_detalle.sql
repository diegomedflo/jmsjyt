-- ============================================================
-- Migración v2.2 — paquetes: columnas de detalle y remitente
--
-- Agrega todas las columnas de detalle del pedido que el modelo
-- SQLAlchemy define pero que el schema original no incluía.
-- También amplía el CHECK de estado para incluir 'siniestrado'.
--
-- Idempotente: usa ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS.
-- ============================================================

-- ── Columnas de estado y gestión ─────────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS ultima_gestion_at TIMESTAMPTZ;

-- ── Columnas de detalle del pedido ───────────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS detalle_cargado        BOOLEAN      NOT NULL DEFAULT FALSE;

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_nombre    VARCHAR(200);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_telefono  VARCHAR(50);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_provincia VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_ciudad    VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_area      VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS destinatario_direccion VARCHAR(500);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS peso_cobrado           DOUBLE PRECISION;

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS tipo_mercancia         VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS modo_pago              VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS origen_pedido          VARCHAR(100);

-- ── Columnas de remitente y códigos extra ────────────────────
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_nombre       VARCHAR(200);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS remitente_telefono     VARCHAR(50);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS codigo_cliente         VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS nombre_cliente         VARCHAR(200);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS codigo_despacho        VARCHAR(100);

ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS pdv_destino            VARCHAR(200);

-- ── Ampliar CHECK de estado para incluir 'siniestrado' ───────
ALTER TABLE paquetes
    DROP CONSTRAINT IF EXISTS paquetes_estado_check;

ALTER TABLE paquetes
    ADD CONSTRAINT paquetes_estado_check
    CHECK (estado IN ('pendiente','entregado','devuelto','cancelado','siniestrado'));
