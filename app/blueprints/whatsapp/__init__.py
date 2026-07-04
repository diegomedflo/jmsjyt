"""Blueprint para el webhook de comandos WhatsApp."""
from flask import Blueprint

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/webhook")

from . import webhook  # noqa: E402, F401
