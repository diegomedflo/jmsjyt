"""Servicio de tracking — refresca el historial POD de los paquetes de un franquiciado.

En cada corrida del cron:
  1. Construye un ``JTTracker`` con las credenciales del franquiciado.
  2. Para cada paquete en estado ``pendiente``, consulta el Registro POD.
  3. Guarda el historial en ``tracking_historial`` (delete + insert).
  4. Actualiza ``paquete.fecha_recojo``, ``n_intentos``, ``ultimo_intento_at``.
  5. Marca como ``entregado`` los paquetes con el evento "Paquete firmado".
  6. Marca como ``devuelto`` los paquetes con 3 intentos fallidos.

Toda la lógica de interpretación de los eventos sigue las mismas reglas
que el proyecto vasmat (Regla General de J&T).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from app.extensions import db
from app.models import Franquiciado, Paquete, TrackingHistorial

logger = logging.getLogger(__name__)

# Tipo de escaneo que indica entrega firmada.
TIPO_ENTREGADO = "Paquete firmado"
# Tipo de escaneo que indica intento fallido.
TIPO_EXCEPCION = "Escaneo de excepción"
# Máximo de intentos permitidos por la Regla General.
MAX_INTENTOS = 3

# Corrección UTC → Perú en producción (el servidor corre en UTC).
PERU_UTC_OFFSET = timedelta(hours=5)

# Detecta "Parada anterior【】" vacía (recojo del almacén de J&T).
_RE_PARADA_VACIA = re.compile(r"Parada anterior\s*【\s*】")
# Detecta nombre del motorizado.
_RE_MENSAJERO    = re.compile(r"su mensajero\s*【(.+?)】")

_SCAN_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
]


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in _SCAN_TIME_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _es_recojo_almacen(descripcion: str) -> bool:
    desc = (descripcion or "").strip()
    return desc.startswith("Llegada del paquete") and bool(
        _RE_PARADA_VACIA.search(desc)
    )


def interpretar_evento(scan_type: Optional[str], descripcion: Optional[str]) -> str:
    """Devuelve un resumen legible de un evento del Registro POD."""
    st   = (scan_type   or "").strip()
    desc = (descripcion or "").strip()

    m = _RE_MENSAJERO.search(desc)
    if m:
        return f"Asignado a motorizado: {m.group(1).strip()}"

    if _es_recojo_almacen(desc):
        return "Recogido del almacén JyT"

    if "excep" in st.lower():
        motivo = desc or "sin detalle"
        return f"Intento fallido: {motivo[:160]}"

    if st == TIPO_ENTREGADO:
        return "Entregado (firmado)"

    return st or "—"


def _guardar_historial(paquete: Paquete, eventos: list) -> None:
    """Reemplaza el historial de tracking del paquete (delete + insert)."""
    TrackingHistorial.query.filter_by(paquete_id=paquete.id).delete()
    for idx, ev in enumerate(reversed(eventos), start=1):
        db.session.add(TrackingHistorial(
            paquete_id     = paquete.id,
            n_orden        = idx,
            hora_escaneo   = _parse_dt(ev.scan_time),
            tiempo_carga   = _parse_dt(ev.upload_time),
            tipo_escaneo   = ev.scan_type,
            descripcion    = ev.description,
            interpretacion = interpretar_evento(ev.scan_type, ev.description),
        ))


def refrescar_franquiciado(
    franquiciado: Franquiciado,
    flask_debug: bool = False,
) -> dict:
    """Refresca el tracking de todos los paquetes pendientes del franquiciado.

    Returns:
        dict con {consultados, errores, entregados, devueltos}
    """
    from jt_scraper import JTTracker, JTInstanceConfig

    def _to_peru(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        return dt if flask_debug else dt - PERU_UTC_OFFSET

    # Callbacks de persistencia del token en BD
    def token_getter() -> Optional[str]:
        # Re-leer desde BD para evitar cache de sesión SQLAlchemy
        db.session.refresh(franquiciado)
        return franquiciado.get_token_cache()

    def token_setter(value: Optional[str]) -> None:
        franquiciado.set_token_cache(value)
        db.session.commit()

    cfg = JTInstanceConfig(
        jt_user      = franquiciado.jt_user,
        jt_pass      = franquiciado.jt_pass,
        token_getter = token_getter,
        token_setter = token_setter,
    )

    pendientes = Paquete.query.filter_by(
        franquiciado_id=franquiciado.id,
        estado=Paquete.ESTADO_PENDIENTE,
    ).all()

    if not pendientes:
        logger.info(f"[{franquiciado.nombre}] Sin paquetes pendientes.")
        return {"consultados": 0, "errores": 0, "entregados": 0, "devueltos": 0}

    try:
        tracker = JTTracker(cfg)
    except Exception as exc:
        logger.error(f"[{franquiciado.nombre}] No se pudo inicializar JTTracker: {exc}")
        return {"consultados": 0, "errores": len(pendientes), "entregados": 0, "devueltos": 0}

    stats = {"consultados": 0, "errores": 0, "entregados": 0, "devueltos": 0}

    for pkg in pendientes:
        try:
            result = tracker.track(pkg.waybill_no)
            stats["consultados"] += 1

            eventos = result.events or []
            _guardar_historial(pkg, eventos)

            # Determinar fecha de recojo del almacén
            for ev in reversed(eventos):
                if _es_recojo_almacen(ev.description or ""):
                    pkg.fecha_recojo = _to_peru(_parse_dt(ev.scan_time))
                    break

            # Contar intentos fallidos y registrar el más reciente
            intentos = [
                ev for ev in eventos
                if (ev.scan_type or "").strip() == TIPO_EXCEPCION
            ]
            pkg.n_intentos = len(intentos)
            if intentos:
                ultimo = _parse_dt(intentos[0].scan_time)  # más reciente primero
                pkg.ultimo_intento_at = _to_peru(ultimo)

            # Entregado
            if eventos and (eventos[0].scan_type or "").strip() == TIPO_ENTREGADO:
                pkg.estado = Paquete.ESTADO_ENTREGADO
                stats["entregados"] += 1
            # Devuelto (≥ 3 intentos)
            elif pkg.n_intentos >= MAX_INTENTOS:
                pkg.estado = Paquete.ESTADO_DEVUELTO
                stats["devueltos"] += 1

            db.session.commit()
            logger.debug(f"[{franquiciado.nombre}] {pkg.waybill_no}: OK ({pkg.estado})")

        except Exception as exc:
            db.session.rollback()
            stats["errores"] += 1
            logger.error(
                f"[{franquiciado.nombre}] Error al procesar {pkg.waybill_no}: {exc}"
            )

    return stats
