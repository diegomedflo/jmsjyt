-- ============================================================
-- JMSJyT SaaS — Esquema MySQL
-- Versión: 1.0.0
--
-- Instrucciones:
--   1. Crear la base de datos en Railway (o local).
--   2. Ejecutar este script completo en MySQL Workbench.
--   3. Insertar el primer admin con:
--        INSERT INTO admin_users (username, password_hash) VALUES ('admin', '...');
--      (genera el hash con werkzeug: from werkzeug.security import generate_password_hash)
-- ============================================================

SET FOREIGN_KEY_CHECKS = 0;
SET NAMES utf8mb4;

-- ── Admin Users ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(80)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_admin_username (username)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Usuarios del panel de administración';

-- ── Franquiciados ─────────────────────────────────────────────────────────────
-- Cada franquiciado es una empresa distribuidora de paquetes JyT.
-- Tiene sus propias credenciales JMS, un grupo WhatsApp de alertas,
-- y una API key de textmebot.
CREATE TABLE IF NOT EXISTS franquiciados (
    id                 INT          AUTO_INCREMENT PRIMARY KEY,
    nombre             VARCHAR(120) NOT NULL,
    jt_user            VARCHAR(120) NOT NULL           COMMENT 'Usuario en jms.jtlac.com',
    jt_pass            VARCHAR(255) NOT NULL           COMMENT 'Contraseña en jms.jtlac.com',
    jt_token_cache     JSON                            COMMENT 'Cache del authtoken {token, ts}',
    wa_grupo_id        VARCHAR(120) NOT NULL           COMMENT 'ID grupo WhatsApp de alertas',
    wa_status_grupo_id VARCHAR(120)                    COMMENT 'ID grupo WhatsApp de monitoreo (opcional)',
    textmebot_api_key  VARCHAR(120) NOT NULL           COMMENT 'API key de textmebot',
    activo             TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=activo, 0=desactivado',
    notas              TEXT                            COMMENT 'Notas internas del admin',
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Franquiciados: empresas distribuidoras de paquetes JyT';

-- ── Paquetes ──────────────────────────────────────────────────────────────────
-- Un paquete es una guía JyT (waybill) asignada a un franquiciado.
-- El estado refleja el ciclo de vida: pendiente → entregado | devuelto | cancelado.
CREATE TABLE IF NOT EXISTS paquetes (
    id                BIGINT       AUTO_INCREMENT PRIMARY KEY,
    franquiciado_id   INT          NOT NULL,
    waybill_no        VARCHAR(120) NOT NULL              COMMENT 'Código de guía JyT',
    estado            ENUM('pendiente','entregado','devuelto','cancelado')
                                   NOT NULL DEFAULT 'pendiente',
    fecha_recojo      DATETIME                           COMMENT 'Cuando JyT recogió del almacén',
    n_intentos        TINYINT      NOT NULL DEFAULT 0    COMMENT 'Número de intentos de entrega',
    ultimo_intento_at DATETIME                           COMMENT 'Fecha del último intento fallido',
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_franq_waybill (franquiciado_id, waybill_no),
    INDEX idx_estado  (estado),
    INDEX idx_waybill (waybill_no),
    CONSTRAINT fk_paquetes_franquiciado
        FOREIGN KEY (franquiciado_id) REFERENCES franquiciados(id)
        ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Paquetes/guías JyT activas por franquiciado';

-- ── Tracking Historial ────────────────────────────────────────────────────────
-- Eventos del Registro POD de cada paquete.  Se refresca en cada corrida del cron.
CREATE TABLE IF NOT EXISTS tracking_historial (
    id             BIGINT      AUTO_INCREMENT PRIMARY KEY,
    paquete_id     BIGINT      NOT NULL,
    n_orden        INT         NOT NULL        COMMENT '1 = más antiguo',
    hora_escaneo   DATETIME                    COMMENT 'Hora de Escaneo del evento',
    tiempo_carga   DATETIME                    COMMENT 'Tiempo de carga del evento',
    tipo_escaneo   VARCHAR(120)                COMMENT 'Tipo de escaneo JyT',
    descripcion    TEXT                        COMMENT 'Descripción del historial de seguimiento',
    interpretacion VARCHAR(255)                COMMENT 'Resumen legible del evento',
    created_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tracking_paquete (paquete_id),
    CONSTRAINT fk_tracking_paquete
        FOREIGN KEY (paquete_id) REFERENCES paquetes(id)
        ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Historial de tracking POD por paquete';

-- ── Cron Logs (resumen global por corrida) ───────────────────────────────────
-- Cada ejecución del cron genera un registro aquí.
CREATE TABLE IF NOT EXISTS cron_logs (
    id                       INT      AUTO_INCREMENT PRIMARY KEY,
    ejecutado_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hora_prevista            TINYINT  NOT NULL COMMENT 'Hora Peru redondeada',
    umbral_horas             FLOAT    NOT NULL,
    franquiciados_procesados INT      NOT NULL DEFAULT 0,
    paquetes_consultados     INT      NOT NULL DEFAULT 0,
    paquetes_por_vencer      INT      NOT NULL DEFAULT 0,
    alertas_enviadas         INT      NOT NULL DEFAULT 0,
    errores                  INT      NOT NULL DEFAULT 0,
    duracion_segundos        FLOAT                      COMMENT 'Duración total en segundos',
    ok                       TINYINT(1) NOT NULL DEFAULT 1,
    INDEX idx_cron_ejecutado (ejecutado_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Logs globales de ejecución del cron de alertas';

-- ── Cron Log Detalles (por franquiciado por corrida) ─────────────────────────
CREATE TABLE IF NOT EXISTS cron_log_detalles (
    id                   INT  AUTO_INCREMENT PRIMARY KEY,
    cron_log_id          INT  NOT NULL,
    franquiciado_id      INT  NOT NULL,
    ok                   TINYINT(1) NOT NULL DEFAULT 1,
    paquetes_consultados INT  NOT NULL DEFAULT 0,
    por_vencer           INT  NOT NULL DEFAULT 0,
    alertas_enviadas     INT  NOT NULL DEFAULT 0,
    error_msg            TEXT                   COMMENT 'Mensaje de error si ok=0',
    CONSTRAINT fk_detalle_cron_log
        FOREIGN KEY (cron_log_id) REFERENCES cron_logs(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_detalle_franquiciado
        FOREIGN KEY (franquiciado_id) REFERENCES franquiciados(id)
        ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Detalle por franquiciado de cada corrida del cron';

-- ── Alertas Log ───────────────────────────────────────────────────────────────
-- Historial de mensajes WhatsApp enviados (alertas de vencimiento + status).
CREATE TABLE IF NOT EXISTS alertas_log (
    id              BIGINT       AUTO_INCREMENT PRIMARY KEY,
    franquiciado_id INT          NOT NULL,
    wa_grupo_id     VARCHAR(120) NOT NULL,
    tipo            ENUM('alerta','status') NOT NULL DEFAULT 'alerta',
    mensaje         TEXT         NOT NULL,
    enviado_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ok              TINYINT(1)   NOT NULL DEFAULT 1,
    respuesta_api   VARCHAR(500)           COMMENT 'Respuesta cruda de textmebot',
    INDEX idx_alerta_franquiciado (franquiciado_id, enviado_at),
    CONSTRAINT fk_alerta_franquiciado
        FOREIGN KEY (franquiciado_id) REFERENCES franquiciados(id)
        ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Historial de mensajes WhatsApp enviados';

-- ── Configuracion (singleton fila id=1) ──────────────────────────────────────
-- Parámetros globales del cron de alertas.  Solo existe la fila con id=1.
CREATE TABLE IF NOT EXISTS configuracion (
    id             TINYINT  NOT NULL DEFAULT 1,
    umbral_dia     FLOAT    NOT NULL DEFAULT 3.0  COMMENT 'Umbral h para 8am–9pm',
    umbral_22      FLOAT    NOT NULL DEFAULT 10.0 COMMENT 'Umbral h para 10pm',
    umbral_23      FLOAT    NOT NULL DEFAULT 9.0  COMMENT 'Umbral h para 11pm',
    hora_inicio    TINYINT  NOT NULL DEFAULT 8    COMMENT 'Primera hora laboral (Perú)',
    hora_fin       TINYINT  NOT NULL DEFAULT 23   COMMENT 'Última hora laboral (Perú)',
    delay_whatsapp FLOAT    NOT NULL DEFAULT 8.0  COMMENT 'Seg entre envíos WA (anti-ban)',
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT chk_singleton CHECK (id = 1)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Configuración global del sistema (singleton)';

-- Seed: fila única de configuración con valores por defecto.
INSERT INTO configuracion (id)
VALUES (1)
ON DUPLICATE KEY UPDATE id = 1;

SET FOREIGN_KEY_CHECKS = 1;
