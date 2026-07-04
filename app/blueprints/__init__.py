"""Exportaciones del paquete de blueprints."""
from .auth      import auth_bp
from .admin     import admin_bp
from .whatsapp  import whatsapp_bp

__all__ = ["auth_bp", "admin_bp", "whatsapp_bp"]
