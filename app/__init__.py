"""Application Factory — JMSJyT SaaS."""
from __future__ import annotations

import os

from flask import Flask, redirect, url_for

from config import config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(env: str | None = None) -> Flask:
    """Crea y devuelve la instancia de Flask configurada."""
    env = env or os.environ.get("FLASK_ENV", "default")
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config[env])

    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_shell_context(app)

    return app


# ── Helpers privados ─────────────────────────────────────────────────────────

def _init_extensions(app: Flask) -> None:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    # Lazy import to avoid circular dependency (services.__init__ imports from extensions)
    from app.services.google_drive_service import google_drive_service
    google_drive_service.init_app(app)


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.auth      import auth_bp
    from app.blueprints.admin     import admin_bp
    from app.blueprints.whatsapp  import whatsapp_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(whatsapp_bp)

    # Redirigir raíz al dashboard
    @app.route("/")
    def index():
        return redirect(url_for("admin.dashboard"))


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500


def _register_shell_context(app: Flask) -> None:
    from app.models import (
        AdminUser, AlertaLog, Configuracion,
        CronLog, CronLogDetalle, Franquiciado, Paquete, TrackingHistorial,
    )

    @app.shell_context_processor
    def make_shell_context():
        return {
            "db": db,
            "AdminUser":       AdminUser,
            "Franquiciado":    Franquiciado,
            "Paquete":         Paquete,
            "TrackingHistorial": TrackingHistorial,
            "CronLog":         CronLog,
            "CronLogDetalle":  CronLogDetalle,
            "AlertaLog":       AlertaLog,
            "Configuracion":   Configuracion,
        }
