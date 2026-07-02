"""Extensiones de Flask — creadas sin app para evitar importaciones circulares."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db            = SQLAlchemy()
login_manager = LoginManager()
migrate       = Migrate()
csrf          = CSRFProtect()
limiter       = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)

# Flask-Login config
login_manager.login_view             = "auth.login"
login_manager.login_message          = "Inicia sesión para acceder al panel."
login_manager.login_message_category = "warning"
