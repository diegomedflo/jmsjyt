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

La corrida itera TODOS los franquiciados activos en una sola ejecución.
Al terminar, envía el reporte de salud al grupo de monitoreo (ADMIN_STATUS_GROUP).

Variables de entorno:
  ADMIN_STATUS_API_KEY    API key de textmebot para el grupo de monitoreo del admin.
  ADMIN_STATUS_GROUP      ID del grupo WA del admin (reporte de salud global).
  TEXTMEBOT_DELAY_SEG     Delay entre envíos WA (default: usa Configuracion.delay_whatsapp).
  FLASK_ENV               Entorno Flask (default 'production').
"""
import logging
import os
import sys
from datetime import timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

env = os.environ.get("FLASK_ENV", "production")

from app import create_app  # noqa: E402

app = create_app(env)

ADMIN_API_KEY     = os.environ.get("ADMIN_STATUS_API_KEY", "")
ADMIN_STATUS_GROUP = os.environ.get("ADMIN_STATUS_GROUP", "")

with app.app_context():
    from app.models       import Configuracion
    from app.services.partition_service import asegurar_particiones_proximos_meses
    from app.services.alertas_service import (
        ejecutar_alertas_global, formatear_reporte_ejecucion, hora_peru,
    )

    ahora = hora_peru()
    # Tolerar ±30 min de desfase en el disparo del cron (Railway).
    hora  = (ahora + timedelta(minutes=30)).hour

    cfg = Configuracion.get()

    # Garantizar que existan las particiones del mes actual y los 2 siguientes.
    # Costo mínimo: solo ejecuta SQL si la partición no existe.
    try:
        nuevas = asegurar_particiones_proximos_meses(meses_adelante=2)
        if nuevas:
            logging.info(f"Particiones creadas: {nuevas}")
    except Exception as exc_part:
        logging.warning(f"partition_service falló (no crítico): {exc_part}")

    if hora < cfg.hora_inicio or hora > cfg.hora_fin:
        print(
            f"[{ahora:%Y-%m-%d %H:%M}] Fuera de horario laboral "
            f"({cfg.hora_inicio}am–{cfg.hora_fin}pm; hora prevista {hora:02d}:00). "
            "Sin acción."
        )
        sys.exit(0)

    umbral = cfg.umbral_para_hora(hora)
    logging.info(f"Hora prevista: {hora:02d}:00 — Umbral: {umbral}h")

    cron_log   = None
    error_critico = None
    try:
        cron_log = ejecutar_alertas_global(
            umbral_horas =umbral,
            hora_prevista=hora,
            enviar        =True,
            on_event      =lambda ev: logging.info(ev),
        )
    except Exception as exc:  # noqa: BLE001
        error_critico = exc
        logging.exception("run_cron_alertas: fallo crítico")

    # ── Reporte global al grupo de monitoreo del admin ──
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
        logging.info(f"Reporte admin → {'OK' if ok else 'ERROR'}: {resp[:100]}")
    else:
        logging.warning(
            "ADMIN_STATUS_API_KEY o ADMIN_STATUS_GROUP no configurados. "
            "Reporte global no enviado."
        )

    if error_critico:
        sys.exit(1)

    print()
    print("=" * 55)
    print("  Alertas JyT completadas")
    print("=" * 55)
    print(f"  Hora prevista (Perú) : {hora:02d}:00 (real {ahora:%H:%M})")
    print(f"  Umbral               : {umbral}h")
    print(f"  Franquiciados        : {cron_log.franquiciados_procesados}")
    print(f"  Paquetes consultados : {cron_log.paquetes_consultados}")
    print(f"  Por vencer           : {cron_log.paquetes_por_vencer}")
    print(f"  Alertas WA enviadas  : {cron_log.alertas_enviadas}")
    print(f"  Errores              : {cron_log.errores}")
    print(f"  Duración             : {cron_log.duracion_segundos}s")
    print(f"  Estado               : {'OK' if cron_log.ok else 'CON ERRORES'}")
    print("=" * 55)

    sys.exit(0 if cron_log.ok else 1)
