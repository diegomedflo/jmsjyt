"""Modelo SQLAlchemy — auditoría de waybills rechazados por red no coincidente.

Cuando OutletMonitor detecta que un waybill devuelto por el filtro
`recevierNetworkCode` de J&T tiene una RECEIVER_NETWORK_NAME distinta a la
configurada en franquiciado.jt_network_code, el waybill NO se importa a
`paquetes` — se registra aquí para que el admin pueda auditar el hallazgo.
"""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class WaybillRechazado(db.Model):
    __tablename__ = "waybills_rechazados"

    id              = db.Column(db.Integer, primary_key=True)
    franquiciado_id = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    waybill_no      = db.Column(db.String(120), nullable=False)
    red_detectada   = db.Column(db.String(200), nullable=True)
    red_esperada    = db.Column(db.String(50),  nullable=True)
    origen          = db.Column(db.String(20),  nullable=False, default="sync")  # sync | detalle
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    franquiciado = db.relationship(
        "Franquiciado",
        backref=db.backref("waybills_rechazados", lazy="dynamic",
                            order_by="WaybillRechazado.created_at.desc()"),
    )

    def __repr__(self) -> str:
        return (
            f"<WaybillRechazado {self.waybill_no!r} franq={self.franquiciado_id} "
            f"detectada={self.red_detectada!r} esperada={self.red_esperada!r}>"
        )
