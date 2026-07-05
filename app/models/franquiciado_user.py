"""Modelo SQLAlchemy — FranquiciadoUser (usuario del portal del franquiciado)."""
from __future__ import annotations

from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class FranquiciadoUser(db.Model):
    """Cuenta de acceso al portal del franquiciado (área restringida)."""

    __tablename__ = "franquiciado_users"

    id                  = db.Column(db.Integer, primary_key=True)
    franquiciado_id     = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    username            = db.Column(db.String(80), nullable=False, unique=True)
    password_hash       = db.Column(db.String(255), nullable=False)
    puede_ver_dashboard = db.Column(db.Boolean, nullable=False, default=False)
    activo              = db.Column(db.Boolean, nullable=False, default=True)
    created_at          = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at          = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    franquiciado = db.relationship("Franquiciado", back_populates="usuario_portal")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<FranquiciadoUser {self.username!r} fq={self.franquiciado_id}>"
