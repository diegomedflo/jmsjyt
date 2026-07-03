"""Modelos SQLAlchemy — Paquete y TrackingHistorial."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Paquete(db.Model):
    """Guía JyT activa asignada a un franquiciado.

    Estados:
      pendiente  — en proceso de entrega, se analiza en cada corrida del cron.
      entregado  — firmado por el destinatario (Paquete firmado en POD).
      devuelto   — 3 intentos fallidos, se devuelve al remitente.
      cancelado  — dado de baja manualmente, ya no se procesa.
    """

    __tablename__ = "paquetes"

    ESTADO_PENDIENTE   = "pendiente"
    ESTADO_ENTREGADO   = "entregado"
    ESTADO_DEVUELTO    = "devuelto"
    ESTADO_CANCELADO   = "cancelado"
    ESTADO_SINIESTRADO = "siniestrado"

    id                = db.Column(db.BigInteger, primary_key=True)
    franquiciado_id   = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    waybill_no        = db.Column(db.String(120), nullable=False, index=True)
    estado            = db.Column(
        db.Enum("pendiente", "entregado", "devuelto", "cancelado", "siniestrado", native_enum=False),
        nullable=False, default="pendiente", index=True,
    )
    fecha_recojo      = db.Column(db.DateTime, nullable=True)
    n_intentos        = db.Column(db.SmallInteger, nullable=False, default=0)
    ultimo_intento_at = db.Column(db.DateTime, nullable=True)
    ultima_gestion_at = db.Column(db.DateTime, nullable=True)  # cualquier gestión (asignación, entrega, excepción)
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at        = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    # Relaciones
    franquiciado = db.relationship("Franquiciado", back_populates="paquetes")
    historial    = db.relationship(
        "TrackingHistorial", back_populates="paquete",
        lazy="dynamic", cascade="all, delete-orphan",
        order_by="TrackingHistorial.n_orden",
    )

    __table_args__ = (
        db.UniqueConstraint("franquiciado_id", "waybill_no", name="uq_franq_waybill"),
    )

    @property
    def esta_pendiente(self) -> bool:
        return self.estado == self.ESTADO_PENDIENTE

    def __repr__(self) -> str:
        return f"<Paquete {self.waybill_no!r} franq={self.franquiciado_id} {self.estado}>"


class TrackingHistorial(db.Model):
    """Eventos del Registro POD de un paquete, sincronizados en cada corrida del cron."""

    __tablename__ = "tracking_historial"

    id             = db.Column(db.BigInteger, primary_key=True)
    paquete_id     = db.Column(
        db.BigInteger, db.ForeignKey("paquetes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    n_orden        = db.Column(db.Integer, nullable=False)
    hora_escaneo   = db.Column(db.DateTime, nullable=True)
    tiempo_carga   = db.Column(db.DateTime, nullable=True)
    tipo_escaneo   = db.Column(db.String(120), nullable=True)
    descripcion    = db.Column(db.Text, nullable=True)
    interpretacion = db.Column(db.String(255), nullable=True)
    created_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relaciones
    paquete = db.relationship("Paquete", back_populates="historial")

    def __repr__(self) -> str:
        return (
            f"<TrackingHistorial paquete={self.paquete_id} "
            f"N={self.n_orden} {self.tipo_escaneo!r}>"
        )
