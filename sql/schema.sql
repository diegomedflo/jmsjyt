-- ============================================================
-- JMSJyT SaaS — Esquema PostgreSQL
-- Versión: 2.1.0
--
-- Instrucciones:
--   1. Crear la BD:  CREATE DATABASE jmsjyt ENCODING 'UTF8';
--   2. Conectarse a la BD y ejecutar este script completo.
--   3. Crear el admin (ver sección al final).
--
-- Nota: updated_at lo gestiona SQLAlchemy (onupdate) en el ORM.
--   No se usan triggers para evitar problemas de encoding en
--   clientes Windows (PowerShell interpreta $$ como variable).
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

CREATE INDEX IF NOT EXISTS idx_tracking_paquete
    ON tracking_historial(paquete_id);

-- Particiones jul 2026 - dic 2027
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
    id             SMALLINT    PRIMARY KEY DEFAULT 1,
    umbral_dia     REAL        NOT NULL DEFAULT 3.0,
    umbral_22      REAL        NOT NULL DEFAULT 10.0,
    umbral_23      REAL        NOT NULL DEFAULT 9.0,
    hora_inicio    SMALLINT    NOT NULL DEFAULT 8,
    hora_fin       SMALLINT    NOT NULL DEFAULT 23,
    delay_whatsapp REAL        NOT NULL DEFAULT 8.0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_singleton CHECK (id = 1)
);

INSERT INTO configuracion (id) VALUES (1) ON CONFLICT DO NOTHING;


-- ── Admin user inicial ────────────────────────────────────────
-- usuario: admin  |  contraseña: Mateo1997
INSERT INTO admin_users (username, password_hash)
VALUES (
    'admin',
    'pbkdf2:sha256:600000$v3AFpNeY4Ft6jOG6$9f7f3bfac4126c54667af18e09d70df6658a09079ef43b8d47ec54bed7ab58a3'
)
ON CONFLICT (username) DO NOTHING;

--
-- Instrucciones:
--   1. Crear la BD:  CREATE DATABASE jmsjyt ENCODING 'UTF8';
--   2. Conectarse a la BD jmsjyt y ejecutar este script completo.
--   3. Crear el primer admin desde Flask shell (ver sección de puesta en marcha).
--
-- Notas de diseño:
--   - tracking_historial está PARTICIONADO por mes (created_at).
--     Permite queries 10-50x más rápidos y borrado instantáneo de históricos.
--   - BRIN index en created_at: ~160KB vs ~2GB de B-Tree para 18M filas.
--   - JSONB en jt_token_cache: binario, comprimido, indexable.
--   - Triggers de updated_at (PostgreSQL no soporta ON UPDATE como MySQL).
-- ============================================================

-- Función genérica reutilizada por todos los triggers updated_at
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── Admin Users ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(80)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_admin_username UNIQUE (username)
);

COMMENT ON TABLE  admin_users IS 'Usuarios del panel de administración';


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

COMMENT ON TABLE  franquiciados                IS 'Empresas distribuidoras de paquetes JyT';
COMMENT ON COLUMN franquiciados.jt_user        IS 'Usuario en jms.jtlac.com';
COMMENT ON COLUMN franquiciados.jt_pass        IS 'Contraseña en jms.jtlac.com';
COMMENT ON COLUMN franquiciados.jt_token_cache IS 'Cache del authtoken {token, ts} — JSONB';
COMMENT ON COLUMN franquiciados.wa_grupo_id    IS 'ID grupo WhatsApp de alertas';

CREATE TRIGGER trg_franquiciados_updated_at
    BEFORE UPDATE ON franquiciados
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


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

COMMENT ON TABLE  paquetes            IS 'Guías JyT activas por franquiciado';
COMMENT ON COLUMN paquetes.n_intentos IS 'Intentos fallidos de entrega (máx 3)';

-- Índice compuesto para el query más frecuente: franq + estado = pendiente
CREATE INDEX idx_paquetes_franq_estado ON paquetes(franquiciado_id, estado);
CREATE INDEX idx_paquetes_waybill       ON paquetes(waybill_no);

CREATE TRIGGER trg_paquetes_updated_at
    BEFORE UPDATE ON paquetes
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- ── Tracking Historial (PARTICIONADO por mes en created_at) ───
--
-- Tabla más grande del sistema. Estimado: 90M filas/año con 50 franquiciados.
--
-- PARTICIONADA por RANGE en created_at (mensual).
-- Beneficios:
--   • Partition pruning: cada query lee solo la partición relevante.
--   • BRIN index: ~160KB en vez de ~2GB de B-Tree para 18M filas.
--   • Purga histórica: DROP TABLE partition = instantáneo (vs 40min DELETE).
--   • Inserciones más rápidas (índice pequeño por partición).
--
-- Las nuevas particiones se crean automáticamente desde el cron
-- (app/services/partition_service.py).
-- ─────────────────────────────────────────────────────────────

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

COMMENT ON TABLE tracking_historial IS
    'Historial POD por paquete — particionado mensualmente por created_at';

-- BRIN: perfecto para datos insertados en orden cronológico.
-- pages_per_range=128 = buen balance entre tamaño y precisión.
CREATE INDEX idx_tracking_created_brin
    ON tracking_historial USING BRIN (created_at)
    WITH (pages_per_range = 128);

-- B-Tree para buscar eventos de un paquete específico
CREATE INDEX idx_tracking_paquete ON tracking_historial(paquete_id);


-- Particiones jul 2026 – dic 2027 (el cron crea las siguientes automáticamente)

CREATE TABLE tracking_historial_2026_07
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-07-01 00:00:00+00') TO ('2026-08-01 00:00:00+00');

CREATE TABLE tracking_historial_2026_08
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');

CREATE TABLE tracking_historial_2026_09
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');

CREATE TABLE tracking_historial_2026_10
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');

CREATE TABLE tracking_historial_2026_11
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

CREATE TABLE tracking_historial_2026_12
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_01
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2027-02-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_02
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-02-01 00:00:00+00') TO ('2027-03-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_03
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-03-01 00:00:00+00') TO ('2027-04-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_04
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-04-01 00:00:00+00') TO ('2027-05-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_05
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-05-01 00:00:00+00') TO ('2027-06-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_06
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-06-01 00:00:00+00') TO ('2027-07-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_07
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-07-01 00:00:00+00') TO ('2027-08-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_08
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-08-01 00:00:00+00') TO ('2027-09-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_09
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-09-01 00:00:00+00') TO ('2027-10-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_10
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-10-01 00:00:00+00') TO ('2027-11-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_11
    PARTITION OF tracking_historial
    FOR VALUES FROM ('2027-11-01 00:00:00+00') TO ('2027-12-01 00:00:00+00');

CREATE TABLE tracking_historial_2027_12
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

COMMENT ON TABLE cron_logs IS 'Resumen global por ejecución del cron de alertas';

CREATE INDEX idx_cron_ejecutado ON cron_logs(ejecutado_at DESC);


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

COMMENT ON TABLE cron_log_detalles IS 'Detalle por franquiciado de cada corrida';

CREATE INDEX idx_cld_log ON cron_log_detalles(cron_log_id);


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

COMMENT ON TABLE alertas_log IS 'Historial de mensajes WhatsApp enviados';

CREATE INDEX idx_alerta_franq_enviado
    ON alertas_log(franquiciado_id, enviado_at DESC);


-- ── Configuracion (singleton id=1) ────────────────────────────
CREATE TABLE IF NOT EXISTS configuracion (
    id             SMALLINT    PRIMARY KEY DEFAULT 1,
    umbral_dia     REAL        NOT NULL DEFAULT 3.0,
    umbral_22      REAL        NOT NULL DEFAULT 10.0,
    umbral_23      REAL        NOT NULL DEFAULT 9.0,
    hora_inicio    SMALLINT    NOT NULL DEFAULT 8,
    hora_fin       SMALLINT    NOT NULL DEFAULT 23,
    delay_whatsapp REAL        NOT NULL DEFAULT 8.0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_singleton CHECK (id = 1)
);

COMMENT ON TABLE configuracion IS 'Parámetros globales del sistema (singleton id=1)';
COMMENT ON COLUMN configuracion.umbral_dia IS 'Umbral horas para 8am–9pm (default 3h)';
COMMENT ON COLUMN configuracion.umbral_22  IS 'Umbral horas para 10pm (default 10h)';
COMMENT ON COLUMN configuracion.umbral_23  IS 'Umbral horas para 11pm (default 9h)';

CREATE TRIGGER trg_configuracion_updated_at
    BEFORE UPDATE ON configuracion
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- Seed: fila única con valores por defecto
INSERT INTO configuracion (id) VALUES (1) ON CONFLICT DO NOTHING;

