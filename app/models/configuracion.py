"""Modelo SQLAlchemy — Configuracion (singleton fila id=1)."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Configuracion(db.Model):
    """Parámetros globales del sistema.  Solo existe la fila con id = 1.

    Uso:
        cfg = Configuracion.get()
        cfg.umbral_dia = 4
        db.session.commit()
    """

    __tablename__ = "configuracion"

    id             = db.Column(db.SmallInteger, primary_key=True, default=1)
    umbral_dia            = db.Column(db.Float, nullable=False, default=3.0)
    umbral_22             = db.Column(db.Float, nullable=False, default=10.0)
    umbral_23             = db.Column(db.Float, nullable=False, default=9.0)
    hora_inicio           = db.Column(db.SmallInteger, nullable=False, default=8)
    hora_fin              = db.Column(db.SmallInteger, nullable=False, default=23)
    delay_whatsapp        = db.Column(db.Float, nullable=False, default=8.0)
    # ── Configuración de sincronización automática (OutletMonitor) ──────────────────────
    sync_dias_atras       = db.Column(db.SmallInteger, nullable=False, default=30)
    sync_time_type        = db.Column(db.SmallInteger, nullable=False, default=1)
    # ── Regla General J&T (global) ───────────────────────────────────────────────
    horas_entre_gestiones = db.Column(db.Integer, nullable=False, default=48)  # max entre gestiones
    updated_at     = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    @classmethod
    def get(cls) -> "Configuracion":
        """Devuelve la fila única de configuración, creándola si no existe."""
        obj = db.session.get(cls, 1)
        if obj is None:
            obj = cls(id=1)
            db.session.add(obj)
            db.session.commit()
        return obj

    def umbral_para_hora(self, hora: int) -> float:
        """Devuelve el umbral de horas según la hora Perú (redondeada)."""
        if hora == 22:
            return self.umbral_22
        if hora == 23:
            return self.umbral_23
        return self.umbral_dia

    def __repr__(self) -> str:
        return (
            f"<Configuracion umbral_dia={self.umbral_dia} "
            f"horario={self.hora_inicio}–{self.hora_fin}>"
        )
