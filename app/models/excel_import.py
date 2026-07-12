"""Modelo SQLAlchemy — registro de cada importación de Excel."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class ExcelImport(db.Model):
    """Log de cada archivo Excel importado (manual o automático).

    Guarda cuántos waybills nuevos se agregaron vs. cuántos eran duplicados,
    el nombre del archivo, y opcionalmente el file_id de Google Drive.
    """

    __tablename__ = "excel_imports"

    id              = db.Column(db.Integer, primary_key=True)
    franquiciado_id = db.Column(
        db.Integer, db.ForeignKey("franquiciados.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename        = db.Column(db.String(255), nullable=False)
    drive_file_id   = db.Column(db.String(100), nullable=True)
    total_waybills  = db.Column(db.Integer, nullable=False, default=0)
    nuevos          = db.Column(db.Integer, nullable=False, default=0)
    duplicados      = db.Column(db.Integer, nullable=False, default=0)
    # Waybills descartados por no coincidir con la red esperada del franquiciado
    # (ver WaybillRechazado — solo se llena en imports desde el scraper OutletMonitor).
    rechazados      = db.Column(db.Integer, nullable=False, default=0)
    # 'manual' = subido por el admin | 'auto' = obtenido por el scraper
    import_mode     = db.Column(db.String(20), nullable=False, default="manual")
    imported_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    franquiciado = db.relationship(
        "Franquiciado",
        backref=db.backref("excel_imports", lazy="dynamic", order_by="ExcelImport.imported_at.desc()"),
    )

    @property
    def drive_url(self) -> str | None:
        if not self.drive_file_id:
            return None
        return f"https://drive.google.com/file/d/{self.drive_file_id}/view"

    def __repr__(self) -> str:
        return (
            f"<ExcelImport id={self.id} franq={self.franquiciado_id} "
            f"nuevos={self.nuevos} dup={self.duplicados} mode={self.import_mode!r}>"
        )
