"""Segunda capa de verificación de red — auditoría de contaminación cruzada.

El filtro `recevierNetworkCode` que OutletMonitor envía a la API de J&T no
siempre es confiable (ver jt_scraper/outlet_monitor.py). Cuando detecta un
waybill cuya RECEIVER_NETWORK_NAME no coincide con la red configurada del
franquiciado (`Franquiciado.jt_network_code`), lo excluye de la importación
y lo deja en `OutletMonitor.last_rejected`. Este módulo persiste esos
hallazgos en `waybills_rechazados` para que el admin pueda auditarlos.
"""
from __future__ import annotations

from loguru import logger

from app.extensions import db
from app.models import WaybillRechazado


def registrar_rechazados(
    franquiciado_id: int,
    rejected: list[dict],
    origen: str = "sync",
) -> int:
    """Persiste los waybills rechazados por red no coincidente.

    Args:
        rejected: lista de dicts {"waybill","red_detectada","red_esperada"}
            (formato de OutletMonitor.last_rejected).
        origen: "sync" (OutletMonitor) o "detalle" (verificación retroactiva
            al cargar el detalle de un paquete ya importado).

    Returns:
        Cantidad de registros persistidos.
    """
    if not rejected:
        return 0

    for r in rejected:
        db.session.add(WaybillRechazado(
            franquiciado_id=franquiciado_id,
            waybill_no=r["waybill"],
            red_detectada=r.get("red_detectada"),
            red_esperada=r.get("red_esperada"),
            origen=origen,
        ))
    db.session.commit()

    logger.warning(
        f"[red_verificacion] franq={franquiciado_id} — {len(rejected)} waybill(s) "
        f"rechazado(s) por red no coincidente (origen={origen})"
    )
    return len(rejected)
