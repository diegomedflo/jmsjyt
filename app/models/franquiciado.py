"""Modelos SQLAlchemy — Franquiciado."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


class Franquiciado(db.Model):
    """Empresa distribuidora de paquetes JyT (franquiciado del SaaS).

    Almacena las credenciales JMS, el grupo de WhatsApp de alertas y la
    API key de textmebot necesarios para ejecutar el cron de alertas.
    """

    __tablename__ = "franquiciados"

    id                 = db.Column(db.Integer, primary_key=True)
    nombre             = db.Column(db.String(120), nullable=False)
    jt_user            = db.Column(db.String(120), nullable=False)
    jt_pass            = db.Column(db.String(255), nullable=False)
    jt_token_cache     = db.Column(JSONB, nullable=True)
    wa_grupo_id        = db.Column(db.String(120), nullable=False)
    wa_status_grupo_id = db.Column(db.String(120), nullable=True)
    textmebot_api_key  = db.Column(db.String(120), nullable=False)
    activo             = db.Column(db.Boolean, nullable=False, default=True)
    notas              = db.Column(db.Text, nullable=True)
    # ── Reglas de entrega personalizadas ──────────────────────────────────
    horas_total_entrega   = db.Column(db.Integer, nullable=False, default=120)  # 5 días = 120h
    horas_primera_gestion = db.Column(db.Integer, nullable=False, default=48)   # 48h para primera gestión
    horas_entre_gestiones = db.Column(db.Integer, nullable=False, default=48)   # max entre gestiones
    # ── Comandos WhatsApp ─────────────────────────────────────────────────
    last_wa_import_at        = db.Column(db.DateTime, nullable=True)   # rate-limit /importar (1/día)
    last_wa_estado_at        = db.Column(db.DateTime, nullable=True)   # última consulta /estado (UTC)
    wa_esperando_codigos_at  = db.Column(db.DateTime, nullable=True)   # inicio espera /agregar (UTC)
    created_at         = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at         = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    # Relaciones
    paquetes      = db.relationship("Paquete", back_populates="franquiciado",
                                    lazy="dynamic", cascade="all, delete-orphan")
    alertas_log   = db.relationship("AlertaLog", back_populates="franquiciado",
                                    lazy="dynamic", cascade="all, delete-orphan")

    # ── Helpers de token cache ──────────────────────────────────────────
    def get_token_cache(self) -> Optional[str]:
        """Devuelve el JSON serializado del cache de token, o None."""
        if not self.jt_token_cache:
            return None
        if isinstance(self.jt_token_cache, str):
            return self.jt_token_cache
        return json.dumps(self.jt_token_cache)

    def set_token_cache(self, value: Optional[str]) -> None:
        """Almacena el cache de token (JSON str → JSON column)."""
        if value is None:
            self.jt_token_cache = None
        elif isinstance(value, str):
            try:
                self.jt_token_cache = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                self.jt_token_cache = None
        else:
            self.jt_token_cache = value

    @property
    def paquetes_pendientes_count(self) -> int:
        return self.paquetes.filter_by(estado="pendiente").count()

    def __repr__(self) -> str:
        return f"<Franquiciado {self.id} {self.nombre!r} activo={self.activo}>"
