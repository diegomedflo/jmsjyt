-- ============================================================
-- JMSJyT SaaS -- Esquema PostgreSQL v2.1
--
-- Instrucciones:
--   1. Conectarse a la BD (local: jmsjyt / Railway: railway)
--   2. Ejecutar este script completo.
--   3. El admin inicial se crea al final automaticamente.
--      usuario: admin | contrasena: Mateo1997
-- ============================================================


-- ── Admin Users ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(80)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_admin_username UNIQUE (username)
);


-- ── Franquiciados ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS franquiciados (
    id                 SERIAL       PRIMARY KEY,
    nombre             VARCHAR(120) NOT NULL,
    jt_user            VARCHAR(120) NOT NULL,
    jt_pass            VARCHAR(255) NOT NULL,
    jt_token_cache     JSONB,
    wa_grupo_id        VARCHAR(120) NOT NULL,
    wa_status_grupo_id VARCHAR(120),
    textmebot_api_key  VARCHAR(120) NOT NULL,
    activo             BOOLEAN      NOT NULL DEFAULT TRUE,
    notas              TEXT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);


-- ── Paquetes ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paquetes (
    id                BIGSERIAL    PRIMARY KEY,
    franquiciado_id   INTEGER      NOT NULL
                      REFERENCES franquiciados(id) ON DELETE CASCADE,
    waybill_no        VARCHAR(120) NOT NULL,
    estado            VARCHAR(20)  NOT NULL DEFAULT 'pendiente'
                      CHECK (estado IN ('pendiente','entregado','devuelto','cancelado')),
    fecha_recojo      TIMESTAMPTZ,
    n_intentos        SMALLINT     NOT NULL DEFAULT 0,
    ultimo_intento_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_franq_waybill UNIQUE (franquiciado_id, waybill_no)
);

CREATE INDEX IF NOT EXISTS idx_paquetes_franq_estado ON paquetes(franquiciado_id, estado);
CREATE INDEX IF NOT EXISTS idx_paquetes_waybill       ON paquetes(waybill_no);


-- ── Tracking Historial (particionado por mes) ─────────────────
CREATE TABLE IF NOT EXISTS tracking_historial (
    id             BIGSERIAL    NOT NULL,
    paquete_id     BIGINT       NOT NULL,
    n_orden        INTEGER      NOT NULL,
    hora_escaneo   TIMESTAMPTZ,
    tiempo_carga   TIMESTAMPTZ,
    tipo_escaneo   VARCHAR(120),
    descripcion    TEXT,
    interpretacion VARCHAR(255),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_tracking_created_brin
    ON tracking_historial USING BRIN (created_at)
    WITH (pages_per_range = 128);

CREATE INDEX IF NOT EXISTS idx_tracking_paquete ON tracking_historial(paquete_id);

CREATE TABLE IF NOT EXISTS tracking_historial_2026_07
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-07-01 00:00:00+00') TO ('2026-08-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2026_08
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2026_09
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2026_10
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2026_11
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2026_12
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_01
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2027-02-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_02
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-02-01 00:00:00+00') TO ('2027-03-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_03
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-03-01 00:00:00+00') TO ('2027-04-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_04
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-04-01 00:00:00+00') TO ('2027-05-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_05
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-05-01 00:00:00+00') TO ('2027-06-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_06
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-06-01 00:00:00+00') TO ('2027-07-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_07
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-07-01 00:00:00+00') TO ('2027-08-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_08
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-08-01 00:00:00+00') TO ('2027-09-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_09
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-09-01 00:00:00+00') TO ('2027-10-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_10
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-10-01 00:00:00+00') TO ('2027-11-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_11
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-11-01 00:00:00+00') TO ('2027-12-01 00:00:00+00');

CREATE TABLE IF NOT EXISTS tracking_historial_2027_12
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-12-01 00:00:00+00') TO ('2028-01-01 00:00:00+00');


-- ── Cron Logs ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cron_logs (
    id                       SERIAL      PRIMARY KEY,
    ejecutado_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hora_prevista            SMALLINT    NOT NULL,
    umbral_horas             REAL        NOT NULL,
    franquiciados_procesados INTEGER     NOT NULL DEFAULT 0,
    paquetes_consultados     INTEGER     NOT NULL DEFAULT 0,
    paquetes_por_vencer      INTEGER     NOT NULL DEFAULT 0,
    alertas_enviadas         INTEGER     NOT NULL DEFAULT 0,
    errores                  INTEGER     NOT NULL DEFAULT 0,
    duracion_segundos        REAL,
    ok                       BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_cron_ejecutado ON cron_logs(ejecutado_at DESC);


-- ── Cron Log Detalles ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cron_log_detalles (
    id                   SERIAL   PRIMARY KEY,
    cron_log_id          INTEGER  NOT NULL
                         REFERENCES cron_logs(id) ON DELETE CASCADE,
    franquiciado_id      INTEGER  NOT NULL
                         REFERENCES franquiciados(id) ON DELETE CASCADE,
    ok                   BOOLEAN  NOT NULL DEFAULT TRUE,
    paquetes_consultados INTEGER  NOT NULL DEFAULT 0,
    por_vencer           INTEGER  NOT NULL DEFAULT 0,
    alertas_enviadas     INTEGER  NOT NULL DEFAULT 0,
    error_msg            TEXT
);

CREATE INDEX IF NOT EXISTS idx_cld_log ON cron_log_detalles(cron_log_id);


-- ── Alertas Log ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alertas_log (
    id              BIGSERIAL    PRIMARY KEY,
    franquiciado_id INTEGER      NOT NULL
                    REFERENCES franquiciados(id) ON DELETE CASCADE,
    wa_grupo_id     VARCHAR(120) NOT NULL,
    tipo            VARCHAR(10)  NOT NULL DEFAULT 'alerta'
                    CHECK (tipo IN ('alerta','status')),
    mensaje         TEXT         NOT NULL,
    enviado_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ok              BOOLEAN      NOT NULL DEFAULT TRUE,
    respuesta_api   VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS idx_alerta_franq_enviado
    ON alertas_log(franquiciado_id, enviado_at DESC);


-- ── Configuracion (singleton id=1) ────────────────────────────
CREATE TABLE IF NOT EXISTS configuracion (
    id              SMALLINT    PRIMARY KEY DEFAULT 1,
    umbral_dia      REAL        NOT NULL DEFAULT 3.0,
    umbral_22       REAL        NOT NULL DEFAULT 10.0,
    umbral_23       REAL        NOT NULL DEFAULT 9.0,
    hora_inicio     SMALLINT    NOT NULL DEFAULT 8,
    hora_fin        SMALLINT    NOT NULL DEFAULT 23,
    delay_whatsapp  REAL        NOT NULL DEFAULT 8.0,
    sync_dias_atras SMALLINT    NOT NULL DEFAULT 30,
    sync_time_type  SMALLINT    NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_singleton CHECK (id = 1)
);

INSERT INTO configuracion (id) VALUES (1) ON CONFLICT DO NOTHING;


-- ── Excel Imports Log ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS excel_imports (
    id              SERIAL       PRIMARY KEY,
    franquiciado_id INTEGER      NOT NULL
                    REFERENCES franquiciados(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    drive_file_id   VARCHAR(100),
    total_waybills  INTEGER      NOT NULL DEFAULT 0,
    nuevos          INTEGER      NOT NULL DEFAULT 0,
    duplicados      INTEGER      NOT NULL DEFAULT 0,
    import_mode     VARCHAR(20)  NOT NULL DEFAULT 'manual',
    imported_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_excel_imports_franq
    ON excel_imports(franquiciado_id, imported_at DESC);


-- ── Migraciones incrementales ─────────────────────────────────
-- Columnas agregadas después de la creación inicial de la tabla.
-- Usar ADD COLUMN IF NOT EXISTS para idempotencia.

-- v2.2: columnas de reglas personalizadas por franquiciado
ALTER TABLE franquiciados
    ADD COLUMN IF NOT EXISTS horas_total_entrega   INTEGER NOT NULL DEFAULT 120,
    ADD COLUMN IF NOT EXISTS horas_primera_gestion INTEGER NOT NULL DEFAULT 48;

-- v2.3: timestamps para rate-limit y auditoría de comandos WhatsApp
ALTER TABLE franquiciados
    ADD COLUMN IF NOT EXISTS last_wa_import_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_wa_estado_at  TIMESTAMPTZ;

-- v2.4: columnas de detalle del paquete (datos estáticos del pedido)
ALTER TABLE paquetes
    ADD COLUMN IF NOT EXISTS ultima_gestion_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS detalle_cargado        BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS destinatario_nombre    VARCHAR(200),
    ADD COLUMN IF NOT EXISTS destinatario_telefono  VARCHAR(50),
    ADD COLUMN IF NOT EXISTS destinatario_provincia VARCHAR(100),
    ADD COLUMN IF NOT EXISTS destinatario_ciudad    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS destinatario_area      VARCHAR(100),
    ADD COLUMN IF NOT EXISTS destinatario_direccion VARCHAR(500),
    ADD COLUMN IF NOT EXISTS peso_cobrado           REAL,
    ADD COLUMN IF NOT EXISTS tipo_mercancia         VARCHAR(100),
    ADD COLUMN IF NOT EXISTS modo_pago              VARCHAR(100),
    ADD COLUMN IF NOT EXISTS origen_pedido          VARCHAR(100);

-- v2.4b: estado siniestrado
ALTER TABLE paquetes
    DROP CONSTRAINT IF EXISTS paquetes_estado_check;
ALTER TABLE paquetes
    ADD CONSTRAINT paquetes_estado_check
    CHECK (estado IN ('pendiente','entregado','devuelto','cancelado','siniestrado'));

-- wa_status_grupo_id en franquiciados (para reportes al admin)
ALTER TABLE franquiciados
    ADD COLUMN IF NOT EXISTS wa_status_grupo_id VARCHAR(120);


-- ── Admin user inicial ────────────────────────────────────────
-- usuario: admin | contrasena: Mateo1997
INSERT INTO admin_users (username, password_hash)
VALUES (
    'admin',
    'pbkdf2:sha256:600000$v3AFpNeY4Ft6jOG6$9f7f3bfac4126c54667af18e09d70df6658a09079ef43b8d47ec54bed7ab58a3'
)
ON CONFLICT (username) DO NOTHING;
