"""Servicio de alertas de vencimiento — Regla General J&T.

En cada corrida del cron (horaria, dentro del horario laboral 8am–11pm Perú):

  1. Refresca el tracking de todos los paquetes pendientes del franquiciado.
  2. Aplica las reglas configurables de J&T:
       - Primera gestión: X horas desde el recojo (franquiciado.horas_primera_gestion).
         Una 'gestión' es cualquier acción: asignación de motorizado, escaneo de
         entrega o escaneo de excepción.
       - Entre gestiones: Y horas desde la última gestión (cfg.horas_entre_gestiones).
       - Vencimiento total: Z horas desde el recojo (franquiciado.horas_total_entrega).
     Máximo 3 intentos fallidos (n_intentos >= 3 → devuelto).
  3. Si un paquete está a ``umbral_horas`` o menos de vencer, se alerta por WA.
  4. Registra el resultado en ``alertas_log`` y en ``cron_log_detalles``.

Función principal de entrada: ``ejecutar_alertas_global``.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from typing import Callable, Optional

from flask import current_app

from app.extensions import db
from app.models import Franquiciado, Paquete, AlertaLog, CronLog, CronLogDetalle
from app.models import Configuracion
from app.services.tracking_service import refrescar_franquiciado
from app.services.whatsapp_service import enviar_whatsapp

logger = logging.getLogger(__name__)

# Número máximo de franquiciados procesados en paralelo en el cron.
MAX_CRON_WORKERS = 4

# Timeout por worker (segundos). Si un franquiciado no termina en este tiempo
# se marca como error y el cron continúa con los demás.
# El watchdog global en run_cron_alertas.py mata el proceso si el total supera 15 min.
WORKER_TIMEOUT_SEG = 300   # 5 min por franquiciado

# UTC → Perú (en producción el servidor corre en UTC)
PERU_UTC_OFFSET = timedelta(hours=5)


def hora_peru() -> datetime:
    """Devuelve la hora actual en zona horaria Perú."""
    utc = datetime.utcnow()
    if current_app.debug:
        return utc  # en dev asumimos que la hora local ya es Perú
    return utc - PERU_UTC_OFFSET


def _deadline_primera_gestion(fecha_recojo: datetime) -> datetime:
    return fecha_recojo + timedelta(hours=HORAS_PRIMERA_GESTION)


def _deadline_entre_gestiones(ultimo_intento: datetime) -> datetime:
    return ultimo_intento + timedelta(hours=HORAS_ENTRE_GESTIONES)


def _analizar_paquete(
    pkg: Paquete,
    now: datetime,
    umbral: float,
    horas_primera_gestion: int,
    horas_entre_gestiones: int,
    horas_total_entrega: int,
) -> list[dict]:
    """Analiza un paquete y devuelve lista de alertas activas (puede ser más de una)."""
    if not pkg.fecha_recojo:
        return []  # sin fecha de recojo no hay plazo calculable

    alertas: list[dict] = []

    # ── Regla 1: Primera gestión ──────────────────────────────────────────
    # Si no hay ninguna gestión, el plazo va desde el recojo
    if pkg.ultima_gestion_at is None:
        deadline = pkg.fecha_recojo + timedelta(hours=horas_primera_gestion)
        horas_restantes = (deadline - now).total_seconds() / 3600
        if horas_restantes <= umbral:
            alertas.append({
                "pkg":             pkg,
                "caso":            "primera_gestion",
                "deadline":        deadline,
                "horas_restantes": horas_restantes,
                "n_intentos":      pkg.n_intentos,
            })

    # ── Regla 2: Entre gestiones ─────────────────────────────────────────
    # Si hay al menos una gestión, medir desde la última
    elif pkg.ultima_gestion_at is not None:
        deadline = pkg.ultima_gestion_at + timedelta(hours=horas_entre_gestiones)
        horas_restantes = (deadline - now).total_seconds() / 3600
        if horas_restantes <= umbral:
            alertas.append({
                "pkg":             pkg,
                "caso":            "entre_gestiones",
                "deadline":        deadline,
                "horas_restantes": horas_restantes,
                "n_intentos":      pkg.n_intentos,
            })

    # ── Regla 3: Vencimiento total (5 días / 120h por defecto) ────────────
    total_deadline = pkg.fecha_recojo + timedelta(hours=horas_total_entrega)
    horas_total_restantes = (total_deadline - now).total_seconds() / 3600
    if horas_total_restantes <= umbral:
        alertas.append({
            "pkg":             pkg,
            "caso":            "vencimiento_total",
            "deadline":        total_deadline,
            "horas_restantes": horas_total_restantes,
            "n_intentos":      pkg.n_intentos,
        })

    return alertas


def _construir_mensaje(alertas: list[dict], franquiciado: Franquiciado, now: datetime) -> str:
    """Construye el texto del mensaje WhatsApp con los paquetes por vencer."""
    CASO_LABEL = {
        "primera_gestion":  "🔴 Primera gestión pendiente",
        "entre_gestiones":  "🟠 Entre gestiones (mucho tiempo sin acción)",
        "vencimiento_total": "⚠️ Vencimiento total del plazo J&T",
    }

    lineas = [
        f"⏰ *ALERTA JyT — {franquiciado.nombre}*",
        "Paquetes próximos a vencer su plazo:",
        "",
    ]

    for caso in ("primera_gestion", "entre_gestiones"):
        grupo = [a for a in alertas if a["caso"] == caso]
        if not grupo:
            continue
        lineas.append(CASO_LABEL[caso] + ":")
        for a in sorted(grupo, key=lambda x: x["horas_restantes"]):
            hr   = a["horas_restantes"]
            venc = a["deadline"].strftime("%d/%m %H:%M")
            n    = a["n_intentos"] + 1
            if hr < 0:
                estado = f"⚠️ VENCIDO hace {int(round(abs(hr)))}h"
            else:
                estado = f"faltan {int(round(hr))}h"
            lineas.append(
                f"  • {a['pkg'].waybill_no} — {estado} (vence {venc}) · intento {n}/3"
            )
        lineas.append("")

    lineas.append("⚠️ Gestionar *antes* del vencimiento para no siniestrar el paquete.")
    lineas.append(f"_Generado {now.strftime('%d/%m %H:%M')} (hora Perú)._")
    return "\n".join(lineas)


def _registrar_alerta(franquiciado: Franquiciado, wa_grupo_id: str,
                      tipo: str, mensaje: str, ok: bool, respuesta: str) -> None:
    db.session.add(AlertaLog(
        franquiciado_id=franquiciado.id,
        wa_grupo_id=wa_grupo_id,
        tipo=tipo,
        mensaje=mensaje,
        ok=ok,
        respuesta_api=respuesta[:500] if respuesta else None,
    ))
    db.session.commit()


def ejecutar_alertas_franquiciado(
    franquiciado: Franquiciado,
    umbral_horas: float,
    enviar: bool = True,
    delay_segundos: float = 8.0,
    on_event: Optional[Callable[[str], None]] = None,
) -> dict:
    """Ejecuta las alertas de vencimiento para UN franquiciado.

    Returns:
        dict con {consultados, errores, por_vencer, alerta_enviada}
    """
    def emit(msg: str) -> None:
        logger.info(msg)
        if on_event:
            on_event(msg)

    emit(f"[{franquiciado.nombre}] Inicio refresh tracking…")

    flask_debug = current_app.debug
    refresh_stats = refrescar_franquiciado(franquiciado, flask_debug=flask_debug)

    emit(
        f"[{franquiciado.nombre}] Refresh: consultados={refresh_stats['consultados']} "
        f"errores={refresh_stats['errores']} entregados={refresh_stats['entregados']} "
        f"devueltos={refresh_stats['devueltos']}"
    )

    now = hora_peru()
    cfg = Configuracion.get()
    pendientes = Paquete.query.filter_by(
        franquiciado_id=franquiciado.id,
        estado=Paquete.ESTADO_PENDIENTE,
    ).all()

    alertas = []
    for pkg in pendientes:
        resultados = _analizar_paquete(
            pkg, now, umbral_horas,
            horas_primera_gestion = franquiciado.horas_primera_gestion,
            horas_entre_gestiones  = cfg.horas_entre_gestiones,
            horas_total_entrega    = franquiciado.horas_total_entrega,
        )
        alertas.extend(resultados)

    emit(f"[{franquiciado.nombre}] Por vencer: {len(alertas)} de {len(pendientes)}")

    alerta_enviada = False
    if alertas:
        mensaje = _construir_mensaje(alertas, franquiciado, now)
        emit(f"[{franquiciado.nombre}] Enviando alerta → {franquiciado.wa_grupo_id}")

        if enviar:
            ok, resp = enviar_whatsapp(
                franquiciado.textmebot_api_key,
                franquiciado.wa_grupo_id,
                mensaje,
            )
            _registrar_alerta(franquiciado, franquiciado.wa_grupo_id,
                              AlertaLog.TIPO_ALERTA, mensaje, ok, resp)
            alerta_enviada = ok
            emit(f"[{franquiciado.nombre}] WA alerta → {'OK' if ok else 'ERROR'}: {resp[:80]}")
        else:
            # Preview sin enviar
            emit(f"[{franquiciado.nombre}] PREVIEW (no enviado):\n{mensaje}")
            alerta_enviada = False

    return {
        "consultados":    refresh_stats["consultados"],
        "errores":        refresh_stats["errores"],
        "por_vencer":     len(alertas),
        "alerta_enviada": alerta_enviada,
    }


def _worker_franquiciado(
    app,
    cron_log_id: int,
    fq_id: int,
    umbral_horas: float,
    enviar: bool,
    delay_segundos: float,
) -> dict:
    """Ejecuta las alertas de UN franquiciado en un thread propio."""
    with app.app_context():
        t_inicio = time.monotonic()
        try:
            fq = Franquiciado.query.get(fq_id)
            if fq is None:
                logger.error(f"[worker fq_id={fq_id}] Franquiciado no encontrado en BD")
                return {"fq_id": fq_id, "nombre": "?", "ok": False,
                        "error": f"Franquiciado id={fq_id} no encontrado",
                        "consultados": 0, "por_vencer": 0, "alerta_enviada": False, "errores": 1}

            n_pendientes = Paquete.query.filter_by(
                franquiciado_id=fq_id, estado=Paquete.ESTADO_PENDIENTE
            ).count()
            logger.info(
                f"[worker] ► INICIO {fq.nombre!r} (fq_id={fq_id}) — "
                f"{n_pendientes} paq pendientes"
            )

            res = ejecutar_alertas_franquiciado(
                fq,
                umbral_horas   = umbral_horas,
                enviar         = enviar,
                delay_segundos = delay_segundos,
                on_event       = None,
            )

            duracion = time.monotonic() - t_inicio
            logger.info(
                f"[worker] ◄ FIN   {fq.nombre!r} (fq_id={fq_id}) — "
                f"consultados={res['consultados']} errores={res['errores']} "
                f"por_vencer={res['por_vencer']} alerta={'SÍ' if res['alerta_enviada'] else 'NO'} "
                f"dur={duracion:.1f}s"
            )

            detalle = CronLogDetalle(
                cron_log_id          = cron_log_id,
                franquiciado_id      = fq_id,
                ok                   = res["errores"] == 0,
                paquetes_consultados = res["consultados"],
                por_vencer           = res["por_vencer"],
                alertas_enviadas     = 1 if res["alerta_enviada"] else 0,
            )
            db.session.add(detalle)
            db.session.commit()

            return {"fq_id": fq_id, "nombre": fq.nombre, "ok": True, "error": None, **res}

        except Exception as exc:
            duracion = time.monotonic() - t_inicio
            logger.exception(
                f"[worker fq_id={fq_id}] Error no capturado tras {duracion:.1f}s: {exc}"
            )
            try:
                db.session.rollback()
                db.session.add(CronLogDetalle(
                    cron_log_id     = cron_log_id,
                    franquiciado_id = fq_id,
                    ok              = False,
                    error_msg       = str(exc)[:500],
                ))
                db.session.commit()
            except Exception:
                pass
            return {"fq_id": fq_id, "nombre": "?", "ok": False, "error": str(exc),
                    "consultados": 0, "por_vencer": 0, "alerta_enviada": False, "errores": 1}
        finally:
            db.session.remove()


def ejecutar_alertas_global(
    umbral_horas: float,
    hora_prevista: int,
    enviar: bool = True,
    on_event: Optional[Callable[[str], None]] = None,
) -> CronLog:
    """Itera todos los franquiciados activos y ejecuta sus alertas de vencimiento.

    Crea y devuelve el ``CronLog`` de la corrida.
    """
    inicio = time.monotonic()
    cfg    = Configuracion.get()
    app    = current_app._get_current_object()   # objeto real, no el proxy (necesario en threads)

    cron_log = CronLog(
        hora_prevista=hora_prevista,
        umbral_horas=umbral_horas,
    )
    db.session.add(cron_log)
    db.session.flush()   # obtener el id antes de lanzar workers
    db.session.commit()  # confirmar para que los workers puedan leerlo

    fq_ids = [
        fq.id for fq in Franquiciado.query.filter_by(activo=True).all()
    ]

    totales = {
        "franquiciados_procesados": 0,
        "paquetes_consultados":     0,
        "paquetes_por_vencer":      0,
        "alertas_enviadas":         0,
        "errores":                  0,
    }

    if on_event:
        logger.warning(
            "ejecutar_alertas_global: on_event no es compatible con ejecución paralela — se ignora."
        )

    workers = min(MAX_CRON_WORKERS, len(fq_ids)) if fq_ids else 1
    logger.info(
        f"[cron] Lanzando {len(fq_ids)} franquiciado(s) con {workers} worker(s) paralelo(s). "
        f"Timeout por worker: {WORKER_TIMEOUT_SEG}s."
    )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _worker_franquiciado,
                app, cron_log.id, fq_id,
                umbral_horas, enviar, cfg.delay_whatsapp,
            ): fq_id
            for fq_id in fq_ids
        }
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {
        executor.submit(
            _worker_franquiciado,
            app, cron_log.id, fq_id,
            umbral_horas, enviar, cfg.delay_whatsapp,
        ): fq_id
        for fq_id in fq_ids
    }
    logger.info(f"[cron] {len(futures)} futures en cola. Esperando resultados…")

    completados = 0
    for future in as_completed(futures, timeout=WORKER_TIMEOUT_SEG * len(fq_ids) + 60):
        fq_id = futures[future]
        completados += 1
        try:
            res = future.result(timeout=WORKER_TIMEOUT_SEG)

        except FutureTimeoutError:
            logger.error(
                f"[cron] fq_id={fq_id} — TIMEOUT después de {WORKER_TIMEOUT_SEG}s. "
                f"Progreso: {completados}/{len(futures)}. El thread sigue en background."
            )
            totales["errores"] += 1
            continue

        except Exception as exc:
            logger.error(f"[cron] fq_id={fq_id} — Future falló: {exc}")
            totales["errores"] += 1
            continue

        if res["ok"]:
            totales["franquiciados_procesados"] += 1
            totales["paquetes_consultados"]     += res.get("consultados", 0)
            totales["paquetes_por_vencer"]      += res.get("por_vencer", 0)
            totales["alertas_enviadas"]         += 1 if res.get("alerta_enviada") else 0
            logger.info(
                f"[cron] [{completados}/{len(futures)}] {res['nombre']!r} OK — "
                f"consultados={res.get('consultados',0)} "
                f"por_vencer={res.get('por_vencer',0)}"
            )
        else:
            totales["errores"] += res.get("errores", 1)
            logger.error(
                f"[cron] [{completados}/{len(futures)}] {res['nombre']!r} ERROR: {res['error']}"
            )

    # shutdown(wait=False): no bloquea esperando threads colgados.
    # El watchdog en run_cron_alertas.py mata el proceso si es necesario.
    executor.shutdown(wait=False)
    logger.info("[cron] Executor shutdown(wait=False). Workers colgados quedan como daemons.")

    duracion = time.monotonic() - inicio

    cron_log.franquiciados_procesados = totales["franquiciados_procesados"]
    cron_log.paquetes_consultados     = totales["paquetes_consultados"]
    cron_log.paquetes_por_vencer      = totales["paquetes_por_vencer"]
    cron_log.alertas_enviadas         = totales["alertas_enviadas"]
    cron_log.errores                  = totales["errores"]
    cron_log.duracion_segundos        = round(duracion, 1)
    cron_log.ok                       = totales["errores"] == 0

    db.session.commit()
    return cron_log


def formatear_reporte_ejecucion(cron_log: CronLog, ahora: datetime, umbral: float) -> str:
    """Construye el mensaje de salud de la corrida para el grupo de monitoreo.

    Incluye resumen global + detalle por franquiciado (✅ / ❌).
    Requiere estar dentro de un app_context activo.
    """
    ts = ahora.strftime("%d/%m %H:%M")
    estado = "✅ *Ejecución correcta*" if cron_log.ok else "⚠️ *Completado con errores*"

    lineas = [
        "🤖 *JMSJyT SaaS — Reporte de ejecución*",
        f"🕒 {ts} (hora Perú) · umbral {umbral}h",
        estado,
        "",
        f"  • Franquiciados: {cron_log.franquiciados_procesados}",
        f"  • Paquetes:      {cron_log.paquetes_consultados} consultados",
        f"  • Por vencer:    {cron_log.paquetes_por_vencer}",
        f"  • Alertas WA:    {cron_log.alertas_enviadas}",
        f"  • Errores:       {cron_log.errores}",
        f"  • Duración:      {cron_log.duracion_segundos}s",
    ]

    # Detalle por franquiciado — consulta CronLogDetalle asociados al cron_log
    try:
        from app.models import CronLogDetalle as _CLD
        detalles = _CLD.query.filter_by(cron_log_id=cron_log.id).all()
        if detalles:
            lineas.append("")
            lineas.append("*Por franquiciado:*")
            for d in detalles:
                nombre = (
                    d.franquiciado.nombre
                    if d.franquiciado
                    else f"id={d.franquiciado_id}"
                )
                if d.ok:
                    lineas.append(
                        f"  ✅ {nombre}: {d.paquetes_consultados} paq"
                        + (f", {d.por_vencer} x vencer" if d.por_vencer else "")
                    )
                else:
                    err = (d.error_msg or "error desconocido")[:80]
                    lineas.append(f"  ❌ {nombre}: {err}")
    except Exception as exc:
        logger.warning(f"formatear_reporte_ejecucion: no se pudo cargar detalles: {exc}")

    return "\n".join(lineas)
