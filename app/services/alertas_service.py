"""Servicio de alertas de vencimiento — Regla General J&T.

En cada corrida del cron (horaria, dentro del horario laboral 8am–11pm Perú):

  1. Refresca el tracking de todos los paquetes pendientes del franquiciado.
  2. Aplica la Regla General de J&T:
       - Primera gestión: 48h desde el recojo del almacén (fecha_recojo).
       - Entre gestiones: 24h desde el último intento fallido (ultimo_intento_at).
     Máximo 3 intentos (n_intentos >= 3 → devuelto).
  3. Si un paquete está a ``umbral_horas`` o menos de vencer su plazo vigente,
     se incluye en la alerta de WhatsApp del franquiciado.
  4. Registra el resultado en ``alertas_log`` y en ``cron_log_detalles``.

Función principal de entrada: ``ejecutar_alertas_global``.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from flask import current_app

from app.extensions import db
from app.models import Franquiciado, Paquete, AlertaLog, CronLog, CronLogDetalle
from app.models import Configuracion
from app.services.tracking_service import refrescar_franquiciado
from app.services.whatsapp_service import enviar_whatsapp

logger = logging.getLogger(__name__)

# Regla General J&T
HORAS_PRIMERA_GESTION = 48
HORAS_ENTRE_GESTIONES = 24

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


def _analizar_paquete(pkg: Paquete, now: datetime, umbral: float) -> Optional[dict]:
    """Analiza un paquete y devuelve datos de alerta si está por vencer, o None."""
    if not pkg.fecha_recojo:
        return None  # sin fecha de recojo, no se puede calcular el plazo

    if pkg.n_intentos == 0:
        # Primera gestión: 48h desde recojo
        deadline = _deadline_primera_gestion(pkg.fecha_recojo)
        caso     = "primera_gestion"
    else:
        # Entre gestiones: 24h desde el último intento fallido
        if not pkg.ultimo_intento_at:
            return None
        deadline = _deadline_entre_gestiones(pkg.ultimo_intento_at)
        caso     = "entre_gestiones"

    horas_restantes = (deadline - now).total_seconds() / 3600
    if horas_restantes <= umbral:
        return {
            "pkg":             pkg,
            "caso":            caso,
            "deadline":        deadline,
            "horas_restantes": horas_restantes,
            "n_intentos":      pkg.n_intentos,
        }
    return None


def _construir_mensaje(alertas: list[dict], franquiciado: Franquiciado, now: datetime) -> str:
    """Construye el texto del mensaje WhatsApp con los paquetes por vencer."""
    CASO_LABEL = {
        "primera_gestion": "🔴 Primera gestión (48h desde recojo)",
        "entre_gestiones": "🟠 Entre gestiones (24h desde último intento)",
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
    pendientes = Paquete.query.filter_by(
        franquiciado_id=franquiciado.id,
        estado=Paquete.ESTADO_PENDIENTE,
    ).all()

    alertas = []
    for pkg in pendientes:
        resultado = _analizar_paquete(pkg, now, umbral_horas)
        if resultado:
            alertas.append(resultado)

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

    cron_log = CronLog(
        hora_prevista=hora_prevista,
        umbral_horas=umbral_horas,
    )
    db.session.add(cron_log)
    db.session.flush()  # obtener el id

    franquiciados = Franquiciado.query.filter_by(activo=True).all()

    totales = {
        "franquiciados_procesados": 0,
        "paquetes_consultados":     0,
        "paquetes_por_vencer":      0,
        "alertas_enviadas":         0,
        "errores":                  0,
    }

    for idx, fq in enumerate(franquiciados):
        try:
            if idx > 0 and enviar:
                time.sleep(cfg.delay_whatsapp)

            res = ejecutar_alertas_franquiciado(
                fq,
                umbral_horas=umbral_horas,
                enviar=enviar,
                delay_segundos=cfg.delay_whatsapp,
                on_event=on_event,
            )

            detalle = CronLogDetalle(
                cron_log_id         =cron_log.id,
                franquiciado_id     =fq.id,
                ok                  =res["errores"] == 0,
                paquetes_consultados=res["consultados"],
                por_vencer          =res["por_vencer"],
                alertas_enviadas    =1 if res["alerta_enviada"] else 0,
            )
            db.session.add(detalle)

            totales["franquiciados_procesados"] += 1
            totales["paquetes_consultados"]     += res["consultados"]
            totales["paquetes_por_vencer"]      += res["por_vencer"]
            totales["alertas_enviadas"]         += 1 if res["alerta_enviada"] else 0
            totales["errores"]                  += res["errores"]

        except Exception as exc:
            logger.exception(f"[{fq.nombre}] Fallo no capturado: {exc}")
            db.session.rollback()
            db.session.add(CronLogDetalle(
                cron_log_id    =cron_log.id,
                franquiciado_id=fq.id,
                ok             =False,
                error_msg      =str(exc)[:500],
            ))
            totales["errores"] += 1

        db.session.commit()

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
    """Construye el mensaje de salud de la corrida para el grupo de monitoreo."""
    ts = ahora.strftime("%d/%m %H:%M")
    estado = "✅ *Ejecución correcta*" if cron_log.ok else "⚠️ *Completado con errores*"

    return "\n".join([
        "🤖 *JMSJyT SaaS — Reporte de ejecución*",
        f"🕒 {ts} (hora Perú) · umbral {umbral}h",
        estado,
        "",
        f"  • Franquiciados procesados: {cron_log.franquiciados_procesados}",
        f"  • Paquetes consultados:     {cron_log.paquetes_consultados}",
        f"  • Por vencer detectados:    {cron_log.paquetes_por_vencer}",
        f"  • Alertas WA enviadas:      {cron_log.alertas_enviadas}",
        f"  • Errores:                  {cron_log.errores}",
        f"  • Duración:                 {cron_log.duracion_segundos}s",
    ])
