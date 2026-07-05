-- ============================================================
-- Migración v2.4 — franquiciado_users
--
-- Crea la tabla de usuarios del portal del franquiciado.
-- Idempotente: usa CREATE TABLE IF NOT EXISTS.
-- ============================================================

CREATE TABLE IF NOT EXISTS franquiciado_users (
    id                  SERIAL       PRIMARY KEY,
    franquiciado_id     INTEGER      NOT NULL UNIQUE
                        REFERENCES franquiciados(id) ON DELETE CASCADE,
    username            VARCHAR(80)  NOT NULL UNIQUE,
    password_hash       VARCHAR(255) NOT NULL,
    puede_ver_dashboard BOOLEAN      NOT NULL DEFAULT FALSE,
    activo              BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fq_users_franquiciado ON franquiciado_users(franquiciado_id);
