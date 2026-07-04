"""Webhook para comandos de WhatsApp recibidos desde textmebot.

Textmebot envía un POST a esta URL con JSON cuando llega un mensaje al grupo.
Payload real de textmebot (mensajes de grupo):
  {
    "type":      "text",
    "from":      "51968547897",              ← teléfono del remitente individual
    "from_name": "Diego",
    "to":        "120363408989708753@g.us",  ← JID del grupo (ESTE identifica al franquiciado)
    "message":   "/estado",
    "origin":    "phone"
  }

La configuración del webhook en textmebot se hace UNA VEZ por API key:
  GET https://api.textmebot.com/webhook.php?apikey=TU_KEY&webhookurl=https://tuapp.com/webhook/whatsapp

El franquiciado se identifica por el campo "to" (group JID), que debe coincidir
exactamente con wa_grupo_id o wa_status_grupo_id en la BD.

Comandos soportados:
  /importar  — Importa paquetes desde JMS a la BD (límite: 1 vez al día).
  /estado    — Resumen de estados solo de los lotes de recojo aún activos.
  /agregar   — Activa espera de 2 min; el siguiente mensaje se trata como
               lista de códigos a agregar (separados por espacios o saltos).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

from sqlalchemy import func

from flask import current_app, request

from app.extensions import csrf, db
from app.models import Franquiciado, Paquete
from app.services.whatsapp_service import enviar_whatsapp

from . import whatsapp_bp

logger = logging.getLogger(__name__)

# UTC → Perú (servidor corre en UTC en producción)
PERU_UTC_OFFSET = timedelta(hours=5)
# Tiempo máximo de espera para /agregar (segundos)
AGREGAR_TIMEOUT_SEC = 120


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hora_peru() -> datetime:
    """Hora actual en zona horaria Perú (UTC-5)."""
    utc = datetime.utcnow()
    if current_app.debug:
        return utc  # en dev la hora local ya es Perú
    return utc - PERU_UTC_OFFSET


def _find_franquiciado(group_id: str) -> Franquiciado | None:
    """Devuelve el franquiciado activo cuyo grupo principal O secundario coincida."""
    if not group_id:
        return None
    f = Franquiciado.query.filter_by(wa_grupo_id=group_id, activo=True).first()
    if f:
        return f
    return Franquiciado.query.filter_by(wa_status_grupo_id=group_id, activo=True).first()


def _send_reply(franquiciado: Franquiciado, text: str, reply_to: str) -> None:
    """Envía un mensaje al grupo indicado vía textmebot."""
    ok, resp = enviar_whatsapp(
        api_key=franquiciado.textmebot_api_key,
        recipient=reply_to,
        text=text,
    )
    if not ok:
        logger.warning(
            "[wa_cmd] Fallo al enviar respuesta franq=%s group=%s: %s",
            franquiciado.id, reply_to, resp[:120],
        )


# ── Comando /estado ───────────────────────────────────────────────────────────

def _build_estado_message(franquiciado: Franquiciado, now_peru: datetime) -> str:
    """Construye el mensaje de estado filtrando solo lotes activos.

    Un lote = una fecha_recojo. Un lote está activo si aún tiene al menos
    1 paquete en estado 'pendiente'. Los devueltos/entregados de lotes
    ya cerrados (sin pendientes) se excluyen para no ensuciar el resumen.
    """
    fid = franquiciado.id

    # Fechas de recojo con al menos 1 paquete pendiente → lotes activos
    active_dates = [
        row[0]
        for row in db.session.query(func.date(Paquete.fecha_recojo))
        .filter(
            Paquete.franquiciado_id == fid,
            Paquete.estado == Paquete.ESTADO_PENDIENTE,
            Paquete.fecha_recojo.isnot(None),
        )
        .distinct()
        .all()
    ]

    # Pendientes: paquetes recogidos aún no entregados (trivialmente en lote activo)
    pendientes = (
        Paquete.query
        .filter(
            Paquete.franquiciado_id == fid,
            Paquete.estado == Paquete.ESTADO_PENDIENTE,
            Paquete.fecha_recojo.isnot(None),
        )
        .count()
    )

    if active_dates:
        devueltos = (
            Paquete.query
            .filter(
                Paquete.franquiciado_id == fid,
                Paquete.estado == Paquete.ESTADO_DEVUELTO,
                func.date(Paquete.fecha_recojo).in_(active_dates),
            )
            .count()
        )
        entregados = (
            Paquete.query
            .filter(
                Paquete.franquiciado_id == fid,
                Paquete.estado == Paquete.ESTADO_ENTREGADO,
                func.date(Paquete.fecha_recojo).in_(active_dates),
            )
            .count()
        )
    else:
        devueltos = 0
        entregados = 0

    total = pendientes + devueltos + entregados

    return (
        f"📦 *Estado de paquetes — {franquiciado.nombre}*\n"
        f"_(Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')})_\n\n"
        f"⏳ Pendientes: *{pendientes}*\n"
        f"↩️ Devueltos: *{devueltos}*\n"
        f"✅ Entregados: *{entregados}*\n"
        f"📊 Total: *{total}*\n\n"
        f"_Estados actualizados cada hora, de 8am a 11pm._"
    )


def _cmd_estado(franquiciado: Franquiciado, reply_to: str) -> None:
    """Responde con el resumen de estados de paquetes del franquiciado."""
    print(f"[WA_ESTADO] Construyendo mensaje para franquiciado id={franquiciado.id} reply_to={reply_to!r}", flush=True)
    now_peru = _hora_peru()
    try:
        msg = _build_estado_message(franquiciado, now_peru)
        print(f"[WA_ESTADO] Mensaje construido OK, enviando...", flush=True)
    except Exception as e:
        print(f"[WA_ESTADO] ERROR al construir mensaje: {e}", flush=True)
        raise
    franquiciado.last_wa_estado_at = datetime.utcnow()
    db.session.commit()
    _send_reply(franquiciado, msg, reply_to)
    print(f"[WA_ESTADO] _send_reply completado", flush=True)


# ── Comando /importar — lógica en hilo de fondo ───────────────────────────────

def _run_importar_bg(app, franquiciado_id: int, group_id: str) -> None:
    """Ejecuta la importación desde JMS en un hilo con su propio contexto de app."""
    with app.app_context():
        from app.models import Franquiciado as F
        from app.services.importar_service import import_waybills
        from jt_scraper.outlet_monitor import OutletMonitor
        from jt_scraper.instance_config import JTInstanceConfig

        franquiciado = db.session.get(F, franquiciado_id)
        if not franquiciado:
            return

        def _send(text: str) -> None:
            enviar_whatsapp(
                api_key=franquiciado.textmebot_api_key,
                recipient=group_id,
                text=text,
            )

        try:
            from datetime import date, timedelta
            from app.models import Configuracion

            sync_cfg = Configuracion.get()
            start_date = (date.today() - timedelta(days=sync_cfg.sync_dias_atras)).isoformat()
            end_date   = date.today().isoformat()

            cfg = JTInstanceConfig(
                jt_user=franquiciado.jt_user,
                jt_pass=franquiciado.jt_pass,
                token_getter=franquiciado.get_token_cache,
                token_setter=lambda v: _persist_token(franquiciado, v),
            )
            monitor = OutletMonitor(cfg)
            waybills = monitor.fetch_waybills(
                start_date=start_date,
                end_date=end_date,
                time_type=sync_cfg.sync_time_type,
            )

            if not waybills:
                _send(
                    f"⚠️ No se encontraron paquetes en JMS para el rango consultado "
                    f"({start_date} → {end_date}).\n"
                    "Verifica que tengas paquetes asignados en ese período."
                )
                return

            result = import_waybills(
                franquiciado_id=franquiciado.id,
                waybills=waybills,
                filename="wa_importar",
                import_mode="wa_command",
            )
            msg = (
                f"✅ *Importación completada*\n"
                f"• Paquetes nuevos: *{result['nuevos']}*\n"
                f"• Duplicados (ya existían): *{result['duplicados']}*\n"
                f"• Total procesados: *{result['total']}*\n\n"
                f"_Usa /estado para ver el resumen actualizado._"
            )
            _send(msg)

        except Exception as exc:
            logger.exception("[wa_cmd] Error en /importar franq=%s", franquiciado_id)
            _send(f"❌ Error durante la importación: {str(exc)[:300]}")


def _persist_token(franquiciado: Franquiciado, value) -> None:
    """Persiste el token cache del franquiciado en la BD."""
    franquiciado.set_token_cache(value)
    db.session.commit()


def _cmd_importar(franquiciado: Franquiciado, group_id: str) -> None:
    """Importa paquetes desde JMS. Rate limit: 1 ejecución por día."""
    now_peru = _hora_peru()

    # ── Verificar rate limit ──────────────────────────────────────────────
    if franquiciado.last_wa_import_at:
        last_utc = franquiciado.last_wa_import_at
        last_peru = last_utc if current_app.debug else (last_utc - PERU_UTC_OFFSET)
        if last_peru.date() >= now_peru.date():
            proxima = now_peru.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            _send_reply(
                franquiciado,
                f"⏳ Ya usaste */importar* hoy.\n"
                f"Podrás volver a usarlo mañana a partir de las "
                f"{proxima.strftime('%d/%m/%Y')} 00:00 (hora Perú).",
                group_id,
            )
            return

    # ── Registrar uso y avisar al grupo ──────────────────────────────────
    franquiciado.last_wa_import_at = datetime.utcnow()
    db.session.commit()

    _send_reply(
        franquiciado,
        "🔄 *Importación iniciada...*\n"
        "Consultando JMS y sincronizando paquetes con nuestra base de datos.\n"
        "Te avisaremos cuando termine (puede tardar 1-2 minutos).",
        group_id,
    )

    # ── Lanzar en hilo de fondo (evita bloquear el webhook) ──────────────
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_importar_bg,
        args=(app, franquiciado.id, group_id),
        daemon=True,
    )
    thread.start()


# ── Comando /agregar ──────────────────────────────────────────────────────────

def _cmd_agregar(franquiciado: Franquiciado, group_id: str) -> None:
    """Activa el modo espera de códigos (válido por 2 minutos)."""
    franquiciado.wa_esperando_codigos_at = datetime.utcnow()
    db.session.commit()
    _send_reply(
        franquiciado,
        "📝 *Modo agregar activado*\n"
        "Envía los códigos de paquetes que deseas agregar.\n"
        "Puedes separarlos por saltos de línea o espacios.\n\n"
        "_Tienes 2 minutos para enviarlos._",
        group_id,
    )


def _maybe_recibir_codigos(
    franquiciado: Franquiciado, group_id: str, message: str
) -> None:
    """Procesa el mensaje como lista de códigos si el bot está en modo espera."""
    if not franquiciado.wa_esperando_codigos_at:
        return  # No estaba esperando, ignorar

    elapsed = (datetime.utcnow() - franquiciado.wa_esperando_codigos_at).total_seconds()
    if elapsed > AGREGAR_TIMEOUT_SEC:
        # Venció el tiempo — limpiar sin avisar (el usuario debe usar /agregar de nuevo)
        franquiciado.wa_esperando_codigos_at = None
        db.session.commit()
        return

    # Parsear códigos: dividir por cualquier espacio en blanco (incluye \n, \r)
    raw_codes = message.split()
    codes = [c.strip().upper() for c in raw_codes if 4 <= len(c.strip()) <= 50]

    # Desactivar modo espera antes de procesar
    franquiciado.wa_esperando_codigos_at = None

    if not codes:
        db.session.commit()
        _send_reply(
            franquiciado,
            "⚠️ No se detectaron códigos válidos en tu mensaje.\n"
            "Usa /agregar para intentarlo de nuevo.",
            group_id,
        )
        return

    nuevos = 0
    duplicados = 0
    for code in codes:
        existing = Paquete.query.filter_by(
            franquiciado_id=franquiciado.id,
            waybill_no=code,
        ).first()
        if existing:
            duplicados += 1
        else:
            paquete = Paquete(franquiciado_id=franquiciado.id, waybill_no=code)
            db.session.add(paquete)
            nuevos += 1

    db.session.commit()

    msg = (
        f"✅ *Paquetes agregados*\n"
        f"• Nuevos: *{nuevos}*\n"
        f"• Ya existían (omitidos): *{duplicados}*\n"
        f"• Total enviados: *{nuevos + duplicados}*"
    )
    _send_reply(franquiciado, msg, group_id)


# ── Endpoint webhook ──────────────────────────────────────────────────────────

@whatsapp_bp.route("/whatsapp", methods=["GET", "POST"])
@csrf.exempt
def webhook():
    """Recibe mensajes entrantes de textmebot y despacha los comandos.

    Seguridad: valida el token secreto WA_WEBHOOK_TOKEN (query param ?token=...).
    Si WA_WEBHOOK_TOKEN no está configurado, el endpoint acepta cualquier petición.
    """
    # ── Validar token de seguridad ────────────────────────────────────────
    expected_token = os.environ.get("WA_WEBHOOK_TOKEN", "").strip()
    print(f"[WA_WEBHOOK] Petición recibida — método={request.method} token_requerido={bool(expected_token)}", flush=True)
    if expected_token:
        incoming_token = request.args.get("token", "").strip()
        if incoming_token != expected_token:
            logger.warning("[wa_webhook] Token inválido desde %s", request.remote_addr)
            print(f"[WA_WEBHOOK] ABORTANDO — token inválido: recibido={incoming_token!r}", flush=True)
            return "Unauthorized", 401

    # ── Extraer datos del mensaje (acepta JSON, form y query params) ──────
    data: dict = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    if not data:
        data = request.form.to_dict() or {}
    if not data:
        data = request.args.to_dict()

    # textmebot payload: {"from": "51968547897", "to": "120363...@g.us", "message": "..."}
    # "to"   = JID del grupo donde se escribió (termina en @g.us para grupos)
    # "from" = teléfono individual del remitente
    sender_phone = data.get("from", "").strip()
    group_jid    = data.get("to",   "").strip()

    # El destino de la respuesta es el grupo (to) si viene de un grupo, sino el sender
    reply_to = group_jid or sender_phone

    # El mensaje a ejecutar
    message = (
        data.get("message")
        or data.get("text")
        or data.get("body")
        or ""
    ).strip()

    print(f"[WA_WEBHOOK] method={request.method} sender={sender_phone!r} group_jid={group_jid!r} reply_to={reply_to!r} message={message[:80]!r}", flush=True)

    if not reply_to or not message:
        print(f"[WA_WEBHOOK] ABORTANDO — reply_to o message vacíos.", flush=True)
        return "ok", 200

    # ── Resolver franquiciado: busca primero por group JID, luego por phone ──
    franquiciado = _find_franquiciado(group_jid) if group_jid else None
    if not franquiciado and sender_phone:
        franquiciado = _find_franquiciado(sender_phone)
    if not franquiciado:
        print(f"[WA_WEBHOOK] ABORTANDO — ningún franquiciado activo con group_jid={group_jid!r} ni sender={sender_phone!r}", flush=True)
        return "ok", 200
    print(f"[WA_WEBHOOK] Franquiciado encontrado: id={franquiciado.id} nombre={franquiciado.nombre!r}", flush=True)

    # ── Mensaje sin "/" → posible respuesta al modo /agregar ─────────────
    if not message.startswith("/"):
        _maybe_recibir_codigos(franquiciado, reply_to, message)
        return "ok", 200

    # ── Despachar comando ─────────────────────────────────────────────────
    cmd = message.split()[0].lower()
    print(f"[WA_WEBHOOK] Comando detectado: {cmd!r}", flush=True)

    if cmd == "/agregar":
        _cmd_agregar(franquiciado, reply_to)
    elif cmd == "/importar":
        # Cualquier otro comando cancela el modo espera del /agregar
        if franquiciado.wa_esperando_codigos_at:
            franquiciado.wa_esperando_codigos_at = None
            db.session.commit()
        _cmd_importar(franquiciado, reply_to)
    elif cmd == "/estado":
        print(f"[WA_WEBHOOK] Ejecutando /estado para franquiciado id={franquiciado.id}", flush=True)
        if franquiciado.wa_esperando_codigos_at:
            franquiciado.wa_esperando_codigos_at = None
            db.session.commit()
        _cmd_estado(franquiciado, reply_to)
        print(f"[WA_WEBHOOK] /estado completado", flush=True)
    # Ignorar silenciosamente cualquier otro comando

    return "ok", 200
