"""
Configuraciones de la aplicación por entorno.
Lee variables sensibles desde el archivo .env
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _build_db_uri() -> str | None:
    """Construye la URI de base de datos.

    Orden de búsqueda:
      1. DATABASE_URL (manual)
      2. MYSQL_URL / MYSQL_PRIVATE_URL (Railway MySQL plugin)
      3. Variables individuales MYSQLHOST / MYSQLUSER / etc.
    Convierte 'mysql://' a 'mysql+pymysql://' automáticamente.
    """
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("MYSQL_URL")
        or os.environ.get("MYSQL_PRIVATE_URL")
    )

    if not raw:
        host = os.environ.get("MYSQLHOST")
        port = os.environ.get("MYSQLPORT", "3306")
        user = os.environ.get("MYSQLUSER")
        password = os.environ.get("MYSQLPASSWORD", "")
        database = os.environ.get("MYSQLDATABASE")
        if host and user and database:
            raw = f"mysql://{user}:{password}@{host}:{port}/{database}"

    if raw and raw.startswith("mysql://"):
        raw = "mysql+pymysql://" + raw[len("mysql://"):]

    return raw


class Config:
    """Configuración base compartida por todos los entornos."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "CAMBIA_ESTA_CLAVE_EN_PRODUCCION")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ITEMS_PER_PAGE = 20

    # ── Pool de conexiones SQLAlchemy ──────────────────────────────────────
    # Dimensionado para soportar hasta 50 franquiciados con MAX_CRON_WORKERS=4:
    #   pool_size    = workers(4) + hilo_principal(1) + margen(1) = 6
    #   max_overflow = 4  →  máximo absoluto = 10 conexiones simultáneas
    #
    # pool_pre_ping : ejecuta "SELECT 1" antes de cada checkout para detectar
    #                 conexiones muertas (Railway cierra idle connections).
    #                 Añade ~1 ms de overhead pero elimina errores de reconexión.
    # pool_recycle  : descarta conexiones > 30 min para evitar timeouts del lado
    #                 del servidor (PostgreSQL idle_in_transaction_session_timeout).
    # pool_timeout  : si el pool está agotado, espera max 30 s antes de lanzar
    #                 sqlalchemy.exc.TimeoutError (default SQLAlchemy = 30).
    # connect_timeout (psycopg2): TCP timeout al establecer la conexión inicial;
    #                 sin esto un host inalcanzable cuelga el proceso indefinidamente.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size":     6,
        "max_overflow":  4,
        "pool_timeout":  30,
        "pool_pre_ping": True,
        "pool_recycle":  1800,
        "connect_args":  {"connect_timeout": 10},
    }

    # Google Drive (backup de Excels importados)
    GOOGLE_DRIVE_FOLDER_ID  = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "1Uq8Po3FBcI37wB1QTmFyZi4NjQsDcHSM")
    DRIVE_TOKEN_PICKLE_PATH = os.environ.get("DRIVE_TOKEN_PICKLE_PATH")

    # Límite de subida de archivos (10 MB)
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    # Seguridad de sesión
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 86400 * 7  # 7 días


class DevelopmentConfig(Config):
    DEBUG = True
    # Ajusta usuario:contraseña según tu instalación local de PostgreSQL
    SQLALCHEMY_DATABASE_URI = (
        _build_db_uri() or "postgresql://postgres:postgres@localhost/jmsjyt"
    )
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _build_db_uri()
    SESSION_COOKIE_SECURE = True


config: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
