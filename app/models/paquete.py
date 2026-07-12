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

    # Datos estáticos del pedido (se guardan una sola vez desde get_order_detail)
    detalle_cargado        = db.Column(db.Boolean, nullable=False, default=False)
    destinatario_nombre    = db.Column(db.String(200), nullable=True)
    destinatario_telefono  = db.Column(db.String(50),  nullable=True)
    destinatario_provincia = db.Column(db.String(100), nullable=True)
    destinatario_ciudad    = db.Column(db.String(100), nullable=True)
    destinatario_area      = db.Column(db.String(100), nullable=True)
    destinatario_direccion = db.Column(db.String(500), nullable=True)
    peso_cobrado           = db.Column(db.Float,       nullable=True)  # kg
    tipo_mercancia         = db.Column(db.String(100), nullable=True)
    modo_pago              = db.Column(db.String(100), nullable=True)
    origen_pedido          = db.Column(db.String(100), nullable=True)  # TEMU, Shopee, etc.
    # Datos adicionales del pedido (remitente + códigos extra)
    remitente_nombre       = db.Column(db.String(200), nullable=True)  # sender.name
    remitente_telefono     = db.Column(db.String(50),  nullable=True)  # sender.phone
    remitente_provincia    = db.Column(db.String(100), nullable=True)  # sender.province
    remitente_ciudad       = db.Column(db.String(100), nullable=True)  # sender.city
    remitente_area         = db.Column(db.String(100), nullable=True)  # sender.area
    remitente_direccion    = db.Column(db.String(500), nullable=True)  # sender.address
    remitente_cp           = db.Column(db.String(20),  nullable=True)  # sender.postal_code
    codigo_cliente         = db.Column(db.String(100), nullable=True)  # customerCode
    nombre_cliente         = db.Column(db.String(200), nullable=True)  # customerName
    codigo_despacho        = db.Column(db.String(100), nullable=True)  # terminalDispatchCode
    pdv_destino            = db.Column(db.String(200), nullable=True)  # dispatchNetworkName
    # Datos adicionales del destinatario
    destinatario_cp        = db.Column(db.String(20),  nullable=True)  # receiver.postal_code
    # Datos del paquete (complementarios)
    nombre_mercancia       = db.Column(db.String(200), nullable=True)  # goodsName
    tipo_servicio          = db.Column(db.String(100), nullable=True)  # expressTypeName
    peso_volumetrico       = db.Column(db.Float,       nullable=True)  # packageVolume (kg)
    # Ruta logística
    pdv_recojo             = db.Column(db.String(200), nullable=True)  # realPickNetworkName
    hub_origen             = db.Column(db.String(200), nullable=True)  # initDistributeName
    hub_destino            = db.Column(db.String(200), nullable=True)  # destinationDistributeName

    # ── Verificación de red (segunda capa anti-contaminación cruzada) ──────
    # red_detectada: último código de red visto para esta guía (de sync o detalle).
    # red_sospechosa: True si red_detectada no coincide con franquiciado.jt_network_code
    #   — indica que el waybill pudo haberse importado con datos de OTRO franquiciado
    #   (el filtro recevierNetworkCode de J&T no siempre filtra correctamente).
    red_detectada          = db.Column(db.String(200), nullable=True)
    red_sospechosa         = db.Column(db.Boolean, nullable=False, default=False)

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
