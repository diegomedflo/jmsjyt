"""Blueprint del portal del franquiciado."""
from flask import Blueprint

fq_portal_bp = Blueprint("franquiciado", __name__, url_prefix="/franquiciado")

from . import routes  # noqa: E402, F401
