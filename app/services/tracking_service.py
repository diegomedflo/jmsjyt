"""Servicio de tracking — refresca el historial POD de los paquetes de un franquiciado.

En cada corrida del cron:
  1. Construye un ``JTTracker`` con las credenciales del franquiciado.
  2. Para cada paquete en estado ``pendiente``, consulta el Registro POD.
  3. Guarda el historial en ``tracking_historial`` (delete + insert).
  4. Actualiza ``paquete.fecha_recojo``, ``n_intentos``, ``ultimo_intento_at``, ``ultima_gestion_at``.
  5. Marca como ``entregado`` los paquetes con el evento "Paquete firmado".
  6. Marca como ``devuelto`` los paquetes con "Registro de devolución" o "Escaneo de devolución".
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
# Tipos de escaneo exactos que J&T usa cuando inicia la devolución de un paquete.
# Detectados en el Registro POD (eventos #25 y #26 en el historial real):
#   - "Registro de devolución" : J&T registra la orden de devolver el paquete
#   - "Escaneo de devolución"  : J&T escanea el paquete para iniciar el retorno
_TIPOS_DEVOLUCION = {
    "registro de devolución",
    "escaneo de devolución",
}

# Corrección UTC → Perú en producción (el servidor corre en UTC).
PERU_UTC_OFFSET = timedelta(hours=5)

# Horas mínimas entre revisiones para paquetes en tránsito (sin fecha_recojo).
# Reduce llamadas API innecesarias para paquetes que aún no llegaron al PDV.
HORAS_TRANSITO_SKIP = 4

# --- Detección de fecha de recojo ------------------------------------------
# Evento objetivo: "Descarga TR1/2" cuando el paquete llega al PDV desde el CEDIS.
#
# Criterios que identifican ÚNICAMENTE este evento (#9 en el historial):
#   1. Descripción contiene "Llegada del paquete 【*.pdv】"  → destino es el PDV del franquiciado
#   2. "Parada anterior 【*.Cedis】"                         → viene del hub regional (CEDIS)
#
# Eventos que NO deben matchear (Descarga en nodos intermedios):
#   - "Llegada del paquete 【Callao.SC】 Parada anterior 【HQ.LIM】"     → destino no es .pdv
#   - "Llegada del paquete 【AREQUIPA.Cedis】 Parada anterior 【Callao.SC】" → destino no es .pdv

_RE_PDV_DEST    = re.compile(r"Llegada del paquete\s*【[^】]*\.pdv[^】]*】")
_RE_CEDIS_PARADA = re.compile(r"Parada anterior\s*【[^】]*\.Cedis[^】]*】")

# --- Detección de gestiones (cualquier acción del motorizado o asignación) ---
_RE_MENSAJERO    = re.compile(r"su mensajero\s*【(.+?)】")
_RE_MENSAJERO_OK = re.compile(r"su mensajero\s*【([^】\s][^】]*)】")

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


def _es_devolucion_jyt(scan_type: str) -> bool:
    """Detecta si J&T marcó explícitamente el paquete como devuelto.

    Busca coincidencia exacta (case-insensitive) con los tipos de escaneo
    'Registro de devolución' o 'Escaneo de devolución'.
    """
    st = (scan_type or "").strip().lower()
    return st in _TIPOS_DEVOLUCION


def _es_recojo_almacen(descripcion: str, tipo_escaneo: str = "") -> bool:
    """Detecta cuando el paquete llega al PDV del franquiciado desde el CEDIS.

    Identifica el evento "Descarga TR1/2" número 9 del historial:
      - Destino en la descripción contiene '.pdv'  (ej. 'ARE-22.pdv')
      - Parada anterior contiene '.Cedis'           (ej. 'AREQUIPA.Cedis')

    Ambas condiciones deben cumplirse simultáneamente para evitar falsos
    positivos en descargas en nodos intermedios (Callao.SC, AREQUIPA.Cedis, etc.).
    """
    desc = (descripcion or "").strip()
    return bool(_RE_PDV_DEST.search(desc) and _RE_CEDIS_PARADA.search(desc))


def _es_gestion(scan_type: str, descripcion: str) -> bool:
    """Detecta cualquier gestión del motorizado o asignación tras el recojo:
      - Escaneo de entrega (entrega en curso)
      - Escaneo de excepción (intento fallido)
      - Asignación a motorizado (descripción menciona mensajero)
    """
    st   = (scan_type   or "").strip()
    desc = (descripcion or "").strip()
    if st in ("Escaneo de entrega", TIPO_EXCEPCION):
        return True
    if "excep" in st.lower() or "entrega" in st.lower():
        return True
    # Asignación a motorizado con nombre no vacío
    if _RE_MENSAJERO_OK.search(desc):
        return True
    return False


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


def _guardar_detalle(paquete: Paquete, detail) -> None:
    """Persiste los datos estáticos del pedido (solo la primera vez)."""
    if not detail:
        return
    r = detail.receiver
    s = detail.sender
    paquete.destinatario_nombre    = r.name
    paquete.destinatario_telefono  = r.phone
    paquete.destinatario_provincia = r.province
    paquete.destinatario_ciudad    = r.city
    paquete.destinatario_area      = r.area
    paquete.destinatario_direccion = r.address
    paquete.peso_cobrado           = detail.charge_weight
    paquete.tipo_mercancia         = detail.goods_type
    paquete.modo_pago              = detail.payment_mode
    paquete.origen_pedido          = detail.order_source
    # Campos adicionales — misma llamada API, sin costo extra
    paquete.remitente_nombre       = s.name
    paquete.remitente_telefono     = s.phone
    paquete.codigo_cliente         = detail.customer_code
    paquete.nombre_cliente         = detail.customer_name
    paquete.codigo_despacho        = detail.third_code
    paquete.pdv_destino            = detail.route.dest_pdv
    paquete.detalle_cargado        = True


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
    progress_callback=None,
) -> dict:
    """Refresca el tracking de todos los paquetes pendientes del franquiciado.

    Args:
        progress_callback: callable(done, total, waybill, status) llamado tras
            procesar cada paquete, donde status es 'ok' o 'error'.

    Returns:
        dict con {consultados, errores, entregados, devueltos}
    """
    from jt_scraper import JTTracker, JTInstanceConfig

    def _to_peru(dt: Optional[datetime]) -> Optional[datetime]:
        # La API de JyT ya retorna hora peruana (UTC-5) — sin conversión adicional
        return dt

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

    import time as _time
    _t_inicio_fq = _time.monotonic()
    logger.info(
        f"[{franquiciado.nombre}] Iniciando tracking — "
        f"{len(pendientes)} paq pendientes en cola."
    )

    try:
        tracker = JTTracker(cfg)
    except Exception as exc:
        logger.error(f"[{franquiciado.nombre}] No se pudo inicializar JTTracker: {exc}")
        return {"consultados": 0, "errores": len(pendientes), "entregados": 0, "devueltos": 0}

    stats = {"consultados": 0, "errores": 0, "entregados": 0, "devueltos": 0, "omitidos": 0}
    _total = len(pendientes)
    _done  = 0
    _now   = datetime.utcnow()

    for pkg in pendientes:
        _pkg_error = False
        _t0 = _time.monotonic()
        try:
            # Paquetes en tránsito (sin fecha_recojo): solo revisar cada HORAS_TRANSITO_SKIP horas.
            if pkg.fecha_recojo is None:
                ultima_revision = pkg.updated_at or pkg.created_at
                if ultima_revision and (_now - ultima_revision) < timedelta(hours=HORAS_TRANSITO_SKIP):
                    stats["omitidos"] += 1
                    logger.debug(
                        f"[{franquiciado.nombre}] {pkg.waybill_no}: "
                        f"en tránsito, omitido (revisado hace <{HORAS_TRANSITO_SKIP}h)"
                    )
                    _done += 1
                    if progress_callback:
                        progress_callback(_done, _total, pkg.waybill_no, "omitido")
                    continue

            include_detail = not pkg.detalle_cargado
            result = tracker.track(pkg.waybill_no, include_detail=include_detail)
            _dur = _time.monotonic() - _t0
            stats["consultados"] += 1
            logger.info(
                f"[{franquiciado.nombre}] [{_done+1}/{_total}] "
                f"{pkg.waybill_no} — API OK en {_dur:.1f}s"
            )

            eventos = result.events or []
            _guardar_historial(pkg, eventos)

            if include_detail:
                _guardar_detalle(pkg, result.detail)
                # Si el detalle sigue sin cargarse (API no lo devolvió o falló),
                # marcar igual para no reintentar en cada corrida del cron.
                if not pkg.detalle_cargado:
                    pkg.detalle_cargado = True
                    logger.debug(
                        f"[{franquiciado.nombre}] {pkg.waybill_no}: "
                        "detalle estático no disponible — marcado para no reintentar."
                    )

            # Determinar fecha de recojo del almacén (primera vez que llega al PDV)
            for ev in reversed(eventos):
                if _es_recojo_almacen(ev.description or "", ev.scan_type or ""):
                    pkg.fecha_recojo = _to_peru(_parse_dt(ev.scan_time))
                    break

            # Contar intentos fallidos (Escaneo de excepción) y última gestión
            intentos = [
                ev for ev in eventos
                if (ev.scan_type or "").strip() == TIPO_EXCEPCION
            ]
            pkg.n_intentos = len(intentos)
            if intentos:
                ultimo = _parse_dt(intentos[0].scan_time)  # más reciente primero
                pkg.ultimo_intento_at = _to_peru(ultimo)

            # Última gestión: cualquier acción del motorizado (asignación, entrega, excepción)
            for ev in eventos:  # newest-first
                if pkg.fecha_recojo and _parse_dt(ev.scan_time):
                    ev_dt = _to_peru(_parse_dt(ev.scan_time))
                    # Solo contar gestiones DESPUÉS del recojo
                    if ev_dt and ev_dt > pkg.fecha_recojo:
                        if _es_gestion(ev.scan_type or "", ev.description or ""):
                            pkg.ultima_gestion_at = ev_dt
                            break

            # Entregado: J&T registró firma del destinatario
            if eventos and (eventos[0].scan_type or "").strip() == TIPO_ENTREGADO:
                pkg.estado = Paquete.ESTADO_ENTREGADO
                stats["entregados"] += 1

            # Devuelto: J&T registró "Registro de devolución" o "Escaneo de devolución"
            elif any(_es_devolucion_jyt(ev.scan_type or "") for ev in eventos):
                pkg.estado = Paquete.ESTADO_DEVUELTO
                stats["devueltos"] += 1

            db.session.commit()
            logger.debug(f"[{franquiciado.nombre}] {pkg.waybill_no}: OK ({pkg.estado})")

        except Exception as exc:
            _dur = _time.monotonic() - _t0
            db.session.rollback()
            stats["errores"] += 1
            _pkg_error = True
            logger.error(
                f"[{franquiciado.nombre}] [{_done+1}/{_total}] "
                f"{pkg.waybill_no} — ERROR tras {_dur:.1f}s: {exc}"
            )

        finally:
            _done += 1
            if progress_callback:
                progress_callback(_done, _total, pkg.waybill_no,
                                  "error" if _pkg_error else "ok")

    _dur_fq = _time.monotonic() - _t_inicio_fq
    logger.info(
        f"[{franquiciado.nombre}] Tracking completado en {_dur_fq:.1f}s — "
        f"consultados={stats['consultados']} omitidos={stats['omitidos']} "
        f"errores={stats['errores']} entregados={stats['entregados']} "
        f"devueltos={stats['devueltos']}"
    )
    return stats


def refrescar_lote_stream(
    franquiciado: Franquiciado,
    paquetes: list,
    flask_debug: bool = False,
):
    """Generator: procesa una lista concreta de paquetes y emite eventos de progreso.

    Yields:
        - {'type':'progress', 'done', 'total', 'waybill', 'status'}
        - {'type':'batch_done', 'stats', 'next_after_id'}
    """
    from jt_scraper import JTTracker, JTInstanceConfig

    def _to_peru(dt: Optional[datetime]) -> Optional[datetime]:
        # La API de JyT ya retorna hora peruana (UTC-5) — sin conversión adicional
        return dt

    def token_getter() -> Optional[str]:
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

    total   = len(paquetes)
    last_id = paquetes[-1].id if paquetes else 0
    stats   = {"consultados": 0, "errores": 0, "entregados": 0, "devueltos": 0}

    try:
        tracker = JTTracker(cfg)
    except Exception as exc:
        logger.error(f"[{franquiciado.nombre}] No se pudo inicializar JTTracker (lote): {exc}")
        stats["errores"] = total
        for idx, pkg in enumerate(paquetes, 1):
            yield {"type": "progress", "done": idx, "total": total,
                   "waybill": pkg.waybill_no, "status": "error"}
        yield {"type": "batch_done", "stats": stats, "next_after_id": last_id}
        return

    for idx, pkg in enumerate(paquetes, 1):
        _error     = False
        _entregado = False
        _devuelto  = False
        try:
            include_detail = not pkg.detalle_cargado
            result = tracker.track(pkg.waybill_no, include_detail=include_detail)
            stats["consultados"] += 1

            eventos = result.events or []
            _guardar_historial(pkg, eventos)

            if include_detail:
                _guardar_detalle(pkg, result.detail)
                if not pkg.detalle_cargado:
                    pkg.detalle_cargado = True

            for ev in reversed(eventos):
                if _es_recojo_almacen(ev.description or "", ev.scan_type or ""):
                    pkg.fecha_recojo = _to_peru(_parse_dt(ev.scan_time))
                    break

            intentos = [
                ev for ev in eventos
                if (ev.scan_type or "").strip() == TIPO_EXCEPCION
            ]
            pkg.n_intentos = len(intentos)
            if intentos:
                pkg.ultimo_intento_at = _to_peru(_parse_dt(intentos[0].scan_time))

            for ev in eventos:
                if pkg.fecha_recojo and _parse_dt(ev.scan_time):
                    ev_dt = _to_peru(_parse_dt(ev.scan_time))
                    if ev_dt and ev_dt > pkg.fecha_recojo:
                        if _es_gestion(ev.scan_type or "", ev.description or ""):
                            pkg.ultima_gestion_at = ev_dt
                            break

            if eventos and (eventos[0].scan_type or "").strip() == TIPO_ENTREGADO:
                pkg.estado = Paquete.ESTADO_ENTREGADO
                stats["entregados"] += 1
                _entregado = True
            elif any(_es_devolucion_jyt(ev.scan_type or "") for ev in eventos):
                pkg.estado = Paquete.ESTADO_DEVUELTO
                stats["devueltos"] += 1
                _devuelto = True

            db.session.commit()
            logger.debug(f"[{franquiciado.nombre}] {pkg.waybill_no}: OK ({pkg.estado})")

        except Exception as exc:
            db.session.rollback()
            stats["errores"] += 1
            _error = True
            logger.error(
                f"[{franquiciado.nombre}] Error al procesar {pkg.waybill_no}: {exc}"
            )

        yield {
            "type":    "progress",
            "done":    idx,
            "total":   total,
            "waybill": pkg.waybill_no,
            "status":  "error" if _error else (
                        "entregado" if _entregado else (
                        "devuelto"  if _devuelto  else "ok")),
        }

    yield {"type": "batch_done", "stats": stats, "next_after_id": last_id}
