"""Modelos SQLAlchemy — CronLog, CronLogDetalle, AlertaLog."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class CronLog(db.Model):
    """Resumen global de cada ejecución del cron de alertas."""

    __tablename__ = "cron_logs"

    id                       = db.Column(db.Integer, primary_key=True)
    ejecutado_at             = db.Column(db.DateTime, nullable=False,
                                         default=datetime.utcnow, index=True)
    hora_prevista            = db.Column(db.SmallInteger, nullable=False)
    umbral_horas             = db.Column(db.Float, nullable=False)
    franquiciados_procesados = db.Column(db.Integer, nullable=False, default=0)
    paquetes_consultados     = db.Column(db.Integer, nullable=False, default=0)
    paquetes_por_vencer      = db.Column(db.Integer, nullable=False, default=0)
    alertas_enviadas         = db.Column(db.Integer, nullable=False, default=0)
    errores                  = db.Column(db.Integer, nullable=False, default=0)
    duracion_segundos        = db.Column(db.Float, nullable=True)
    ok                       = db.Column(db.Boolean, nullable=False, default=True)

    # Relaciones
    detalles = db.relationship(
        "CronLogDetalle", back_populates="cron_log",
        lazy="dynamic", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<CronLog {self.id} {self.ejecutado_at:%Y-%m-%d %H:%M} "
            f"ok={self.ok}>"
        )


class CronLogDetalle(db.Model):
    """Detalle por franquiciado de una corrida del cron."""

    __tablename__ = "cron_log_detalles"

    id                   = db.Column(db.Integer, primary_key=True)
    cron_log_id          = db.Column(
        db.Integer, db.ForeignKey("cron_logs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    franquiciado_id      = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False,
    )
    ok                   = db.Column(db.Boolean, nullable=False, default=True)
    paquetes_consultados = db.Column(db.Integer, nullable=False, default=0)
    por_vencer           = db.Column(db.Integer, nullable=False, default=0)
    alertas_enviadas     = db.Column(db.Integer, nullable=False, default=0)
    error_msg            = db.Column(db.Text, nullable=True)

    # Relaciones
    cron_log     = db.relationship("CronLog", back_populates="detalles")
    franquiciado = db.relationship("Franquiciado")

    def __repr__(self) -> str:
        return (
            f"<CronLogDetalle log={self.cron_log_id} "
            f"franq={self.franquiciado_id} ok={self.ok}>"
        )


class AlertaLog(db.Model):
    """Historial de mensajes WhatsApp enviados (alertas de vencimiento y status)."""

    __tablename__ = "alertas_log"

    TIPO_ALERTA = "alerta"
    TIPO_STATUS = "status"

    id              = db.Column(db.BigInteger, primary_key=True)
    franquiciado_id = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    wa_grupo_id     = db.Column(db.String(120), nullable=False)
    tipo            = db.Column(
        db.Enum("alerta", "status"), nullable=False, default="alerta",
    )
    mensaje         = db.Column(db.Text, nullable=False)
    enviado_at      = db.Column(db.DateTime, nullable=False,
                                default=datetime.utcnow, index=True)
    ok              = db.Column(db.Boolean, nullable=False, default=True)
    respuesta_api   = db.Column(db.String(500), nullable=True)

    # Relaciones
    franquiciado = db.relationship("Franquiciado", back_populates="alertas_log")

    def __repr__(self) -> str:
        return (
            f"<AlertaLog franq={self.franquiciado_id} "
            f"tipo={self.tipo} ok={self.ok}>"
        )
