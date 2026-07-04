#!/usr/bin/env python
"""
Cron job horario de alertas de vencimiento JyT — JMSJyT SaaS.

Diseñado para Railway Cron Job (cada hora):
    python run_cron_alertas.py

Lógica de umbral (hora Perú redondeada):
  - 8am–9pm  → umbral 3h  (configurable en Configuracion.umbral_dia)
  - 10pm     → umbral 10h (Configuracion.umbral_22)
  - 11pm     → umbral 9h  (Configuracion.umbral_23)
  Fuera del horario laboral (12am–7am) no hace nada.

Variables de entorno:
  ADMIN_STATUS_API_KEY    API key de textmebot para el grupo de monitoreo del admin.
  ADMIN_STATUS_GROUP      ID del grupo WA del admin (reporte de salud global).
  FLASK_ENV               Entorno Flask (default 'production').
"""
import logging
import os
import sys
from datetime import datetime, timedelta

# ── DEBUG: primer print antes de cualquier import de app ──────────────────
print(">>> [CRON] Script iniciado — imports stdlib OK", flush=True)

# ── Forzar stdout sin buffer para que Railway muestre logs en tiempo real ──
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass  # Python < 3.7

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

# ── Puente loguru → logging estándar ──────────────────────────────────────
# jt_scraper usa loguru; sin este puente sus logs no aparecen en Railway.
try:
    from loguru import logger as _loguru_logger
    import logging as _logging

    class _LoguruToStdlib(logging.Handler):
        def emit(self, record):
            pass  # evitar ciclo infinito

    _loguru_logger.remove()
    _loguru_logger.add(
        lambda msg: print(msg, end="", flush=True),
        format="{time:YYYY-MM-DD HH:mm:ss} [<level>{level}</level>] {name} — {message}",
        level="DEBUG",
        colorize=False,
    )
except ImportError:
    pass  # loguru no instalado

print(f">>> [CRON] loguru bridge configurado. Arrancando lógica principal…", flush=True)

# ── Fast-exit: salida inmediata si es claramente madrugada Perú ─────────────
# Evita arrancar Flask + BD completos en runs que no van a hacer nada.
# Umbral conservador 7h: hora_inicio mínima del sistema es 8h, y con el
# buffer de +30 min cualquier run antes de las 7:30am Perú saldría igual.
_hora_peru_ahora = datetime.utcnow() - timedelta(hours=5)
_hora_peru_buffered = (_hora_peru_ahora + timedelta(minutes=30)).hour
print(f">>> [CRON] Hora UTC: {datetime.utcnow():%H:%M} | Hora Perú: {_hora_peru_ahora:%H:%M} | Hora buffered: {_hora_peru_buffered:02d}h", flush=True)
if _hora_peru_buffered < 7:
    msg = f"[CRON] Fast-exit: madrugada Perú ({_hora_peru_ahora:%H:%M}). Flask no iniciado — sin acción."
    print(f">>> {msg}", flush=True)
    logging.info(msg)
    sys.exit(0)

env = os.environ.get("FLASK_ENV", "production")
print(f">>> [CRON] FLASK_ENV={env} | Iniciando create_app…", flush=True)

from app import create_app  # noqa: E402

app = create_app(env)
print(">>> [CRON] create_app OK — conectando a BD…", flush=True)

ADMIN_API_KEY      = os.environ.get("ADMIN_STATUS_API_KEY", "")
ADMIN_STATUS_GROUP = os.environ.get("ADMIN_STATUS_GROUP", "")

with app.app_context():
    from app.models       import Configuracion, Franquiciado
    from app.services.partition_service import asegurar_particiones_proximos_meses
    from app.services.alertas_service import (
        ejecutar_alertas_global, formatear_reporte_ejecucion, hora_peru,
    )
    print(">>> [CRON] Modelos y servicios importados — consultando BD…", flush=True)

    ahora = hora_peru()
    # Tolerar ±30 min de desfase en el disparo del cron (Railway).
    hora  = (ahora + timedelta(minutes=30)).hour
    cfg   = Configuracion.get()

    # ── Cabecera del log ──────────────────────────────────────
    fq_activos = Franquiciado.query.filter_by(activo=True).count()
    print(f">>> [CRON] BD OK | Hora Perú real: {ahora:%H:%M} | Hora prevista: {hora:02d}h | Franquiciados activos: {fq_activos}", flush=True)
    logging.info("=" * 60)
    logging.info(f"[CRON] INICIO — hora Perú: {ahora:%Y-%m-%d %H:%M}")
    logging.info(f"[CRON] Franquiciados activos: {fq_activos}")
    logging.info(f"[CRON] Hora prevista: {hora:02d}:00  |  Ventana: {cfg.hora_inicio:02d}–00–{cfg.hora_fin:02d}:00")
    logging.info("=" * 60)

    # ── Verificación de horario ──────────────────────────────
    print(f">>> [CRON] Ventana configurada: {cfg.hora_inicio:02d}h–{cfg.hora_fin:02d}h | Hora prevista: {hora:02d}h", flush=True)
    if hora < cfg.hora_inicio or hora > cfg.hora_fin:
        msg = f"[CRON] Fuera de horario ({cfg.hora_inicio:02d}–{cfg.hora_fin:02d}h). Hora actual Perú: {ahora:%H:%M} — sin acción."
        print(f">>> {msg}", flush=True)
        logging.info(msg)
        sys.exit(0)

    # ── Particiones ──────────────────────────────────────
    logging.info("[PASO 0] Verificando particiones de tracking_historial…")
    try:
        nuevas = asegurar_particiones_proximos_meses(meses_adelante=2)
        if nuevas:
            logging.info(f"[PASO 0] Particiones creadas: {nuevas}")
        else:
            logging.info("[PASO 0] Particiones OK (sin cambios).")
    except Exception as exc_part:
        logging.warning(f"[PASO 0] partition_service falló (no crítico): {exc_part}")

    umbral = cfg.umbral_para_hora(hora)
    print(f">>> [CRON] Umbral activo: {umbral}h — lanzando ejecutar_alertas_global…", flush=True)
    logging.info(f"[PASO 1] Umbral activo: {umbral}h")

    # ── Ejecución principal ───────────────────────────────
    cron_log      = None
    error_critico = None
    logging.info("[PASO 2] Iniciando ejecución de alertas para todos los franquiciados…")
    try:
        cron_log = ejecutar_alertas_global(
            umbral_horas =umbral,
            hora_prevista=hora,
            enviar        =True,
        )
    except Exception as exc:  # noqa: BLE001
        error_critico = exc
        logging.exception("[PASO 2] run_cron_alertas: fallo crítico")

    # ── Reporte global al grupo de monitoreo del admin ──
    logging.info("[PASO 3] Enviando reporte al grupo admin…")
    if ADMIN_API_KEY and ADMIN_STATUS_GROUP:
        import time
        from app.services.whatsapp_service import enviar_whatsapp

        if error_critico:
            msg = (
                "❌ *JMSJyT — FALLO CRÍTICO del cron*\n"
                f"Error: `{str(error_critico)[:300]}`"
            )
        else:
            msg = formatear_reporte_ejecucion(cron_log, ahora, umbral)

        time.sleep(cfg.delay_whatsapp)
        ok, resp = enviar_whatsapp(ADMIN_API_KEY, ADMIN_STATUS_GROUP, msg)
        logging.info(f"[PASO 3] Reporte admin → {'OK' if ok else 'ERROR'}: {resp[:100]}")
    else:
        logging.warning(
            "[PASO 3] ADMIN_STATUS_API_KEY o ADMIN_STATUS_GROUP no configurados. "
            "Reporte global no enviado."
        )

    # ── Resumen final ───────────────────────────────────
    if error_critico:
        print(f">>> [CRON] FALLO CRÍTICO: {error_critico}", flush=True)
        logging.error("[CRON] FALLO — saliendo con código 1")
        sys.exit(1)

    print(f">>> [CRON] Ejecución OK | paq consultados={cron_log.paquetes_consultados} | por_vencer={cron_log.paquetes_por_vencer} | alertas_WA={cron_log.alertas_enviadas} | errores={cron_log.errores}", flush=True)
    logging.info("=" * 60)
    logging.info("[CRON] RESUMEN FINAL")
    logging.info(f"  Hora prevista (Perú) : {hora:02d}:00 (real {ahora:%H:%M})")
    logging.info(f"  Umbral               : {umbral}h")
    logging.info(f"  Franquiciados        : {cron_log.franquiciados_procesados}")
    logging.info(f"  Paquetes consultados : {cron_log.paquetes_consultados}")
    logging.info(f"  Por vencer           : {cron_log.paquetes_por_vencer}")
    logging.info(f"  Alertas WA enviadas  : {cron_log.alertas_enviadas}")
    logging.info(f"  Errores              : {cron_log.errores}")
    logging.info(f"  Duración             : {cron_log.duracion_segundos:.1f}s")
    logging.info(f"  Estado               : {'OK' if cron_log.ok else 'CON ERRORES'}")
    logging.info("=" * 60)

    # Detalle por franquiciado
    try:
        from app.models import CronLogDetalle
        detalles = CronLogDetalle.query.filter_by(cron_log_id=cron_log.id).all()
        if detalles:
            logging.info("[CRON] Detalle por franquiciado:")
            for d in detalles:
                nombre = d.franquiciado.nombre if d.franquiciado else f"id={d.franquiciado_id}"
                if d.ok:
                    extra = f"{d.paquetes_consultados} paq, {d.por_vencer} x vencer"
                    logging.info(f"  ✓  {nombre:<30} {extra}")
                else:
                    err = (d.error_msg or "error desconocido")[:80]
                    logging.error(f"  ✗  {nombre:<30} ERROR: {err}")
    except Exception as exc:
        logging.warning(f"No se pudo mostrar detalle por franquiciado: {exc}")

    logging.info("[CRON] Fin normal.")
    sys.exit(0 if cron_log.ok else 1)
