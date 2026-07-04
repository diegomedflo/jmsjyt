"""Webhook para comandos de WhatsApp recibidos desde textmebot.

Textmebot envía un GET (o POST) a esta URL cuando llega un mensaje al grupo.
Parámetros típicos:
  GET /webhook/whatsapp?token=SECRET&phone=GROUP_JID&message=/importar

Comandos soportados:
  /importar  — Importa paquetes desde JMS a la BD (límite: 1 vez al día).
  /estado    — Muestra el resumen de estados de paquetes del franquiciado.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

from flask import current_app, request

from app.extensions import csrf, db
from app.models import Franquiciado, Paquete
from app.services.whatsapp_service import enviar_whatsapp

from . import whatsapp_bp

logger = logging.getLogger(__name__)

# UTC → Perú (servidor corre en UTC en producción)
PERU_UTC_OFFSET = timedelta(hours=5)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hora_peru() -> datetime:
    """Hora actual en zona horaria Perú (UTC-5)."""
    utc = datetime.utcnow()
    if current_app.debug:
        return utc  # en dev la hora local ya es Perú
    return utc - PERU_UTC_OFFSET


def _find_franquiciado(group_id: str) -> Franquiciado | None:
    """Devuelve el franquiciado activo cuyo wa_grupo_id coincida con group_id."""
    if not group_id:
        return None
    return Franquiciado.query.filter_by(wa_grupo_id=group_id, activo=True).first()


def _send_reply(franquiciado: Franquiciado, text: str) -> None:
    """Envía un mensaje al grupo del franquiciado vía textmebot."""
    ok, resp = enviar_whatsapp(
        api_key=franquiciado.textmebot_api_key,
        recipient=franquiciado.wa_grupo_id,
        text=text,
    )
    if not ok:
        logger.warning(
            "[wa_cmd] Fallo al enviar respuesta franq=%s: %s",
            franquiciado.id, resp[:120],
        )


# ── Comando /estado ───────────────────────────────────────────────────────────

def _build_estado_message(franquiciado: Franquiciado, now_peru: datetime) -> str:
    """Construye el mensaje de estado de paquetes del franquiciado."""
    fid = franquiciado.id

    # En tránsito: pendiente SIN fecha_recojo (aún no llegó al PDV desde Lima)
    en_transito = (
        Paquete.query
        .filter_by(franquiciado_id=fid, estado="pendiente")
        .filter(Paquete.fecha_recojo.is_(None))
        .count()
    )

    # Pendientes: pendiente CON fecha_recojo (ya en PDV, pendiente de entrega)
    pendientes = (
        Paquete.query
        .filter_by(franquiciado_id=fid, estado="pendiente")
        .filter(Paquete.fecha_recojo.isnot(None))
        .count()
    )

    devueltos  = Paquete.query.filter_by(franquiciado_id=fid, estado="devuelto").count()
    entregados = Paquete.query.filter_by(franquiciado_id=fid, estado="entregado").count()

    return (
        f"📦 *Estado de paquetes — {franquiciado.nombre}*\n"
        f"_(Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')} hora Perú)_\n\n"
        f"🚚 En tránsito (Lima → Cedis): *{en_transito}*\n"
        f"⏳ Pendientes de entrega: *{pendientes}*\n"
        f"↩️ Devueltos: *{devueltos}*\n"
        f"✅ Entregados: *{entregados}*\n\n"
        f"_Nuestro sistema actualiza estados cada hora, de 8am a 11pm (hora Perú)._"
    )


def _cmd_estado(franquiciado: Franquiciado) -> None:
    """Responde con el resumen de estados de paquetes del franquiciado."""
    now_peru = _hora_peru()
    msg = _build_estado_message(franquiciado, now_peru)

    # Guardar timestamp de última consulta (en UTC)
    franquiciado.last_wa_estado_at = datetime.utcnow()
    db.session.commit()

    _send_reply(franquiciado, msg)


# ── Comando /importar — lógica en hilo de fondo ───────────────────────────────

def _run_importar_bg(app, franquiciado_id: int) -> None:
    """Ejecuta la importación desde JMS en un hilo con su propio contexto de app."""
    with app.app_context():
        from app.models import Franquiciado as F
        from app.services.importar_service import import_waybills
        from jt_scraper.outlet_monitor import OutletMonitor
        from jt_scraper.instance_config import JTInstanceConfig

        franquiciado = F.query.get(franquiciado_id)
        if not franquiciado:
            return

        def _send(text: str) -> None:
            enviar_whatsapp(
                api_key=franquiciado.textmebot_api_key,
                recipient=franquiciado.wa_grupo_id,
                text=text,
            )

        try:
            cfg = JTInstanceConfig(
                jt_user=franquiciado.jt_user,
                jt_pass=franquiciado.jt_pass,
                token_getter=franquiciado.get_token_cache,
                token_setter=lambda v: _persist_token(franquiciado, v),
            )
            monitor = OutletMonitor(cfg)
            waybills = monitor.fetch_waybills()

            if not waybills:
                _send(
                    "⚠️ No se encontraron paquetes en JMS para el rango de fechas consultado.\n"
                    "Verifica que tengas paquetes asignados en los últimos 30 días."
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


def _cmd_importar(franquiciado: Franquiciado) -> None:
    """Importa paquetes desde JMS. Rate limit: 1 ejecución por día."""
    now_peru = _hora_peru()

    # ── Verificar rate limit ──────────────────────────────────────────────
    if franquiciado.last_wa_import_at:
        # Convertir UTC guardado → hora Perú para comparar fecha
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
    )

    # ── Lanzar en hilo de fondo (evita bloquear el webhook) ──────────────
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_importar_bg,
        args=(app, franquiciado.id),
        daemon=True,
    )
    thread.start()


# ── Endpoint webhook ──────────────────────────────────────────────────────────

@whatsapp_bp.route("/whatsapp", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@csrf.exempt
def webhook():
    """Recibe mensajes entrantes de textmebot y despacha los comandos /importar y /estado.

    Seguridad: valida el token secreto WA_WEBHOOK_TOKEN (query param ?token=...).
    Si WA_WEBHOOK_TOKEN no está configurado, el endpoint acepta cualquier petición.
    """
    # ── Validar token de seguridad ────────────────────────────────────────
    expected_token = os.environ.get("WA_WEBHOOK_TOKEN", "").strip()
    if expected_token:
        incoming_token = request.args.get("token", "").strip()
        if incoming_token != expected_token:
            logger.warning("[wa_webhook] Token inválido desde %s", request.remote_addr)
            return "Unauthorized", 401

    # ── Extraer datos del mensaje (acepta JSON, form y query params) ──────
    data: dict = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    if not data:
        data = request.form.to_dict() or {}
    if not data:
        data = request.args.to_dict()

    # textmebot envía el ID de grupo en el campo "phone" para mensajes de grupo
    group_id = (
        data.get("phone")
        or data.get("group")
        or data.get("groupId")
        or data.get("recipient")
        or ""
    ).strip()

    message = (
        data.get("message")
        or data.get("text")
        or data.get("body")
        or ""
    ).strip()

    logger.debug("[wa_webhook] group=%r msg=%r", group_id, message[:60] if message else "")

    if not group_id or not message or not message.startswith("/"):
        return "ok", 200

    # ── Resolver franquiciado ─────────────────────────────────────────────
    franquiciado = _find_franquiciado(group_id)
    if not franquiciado:
        logger.debug("[wa_webhook] group_id %r no registrado", group_id)
        return "ok", 200

    # ── Despachar comando ─────────────────────────────────────────────────
    cmd = message.split()[0].lower()

    if cmd == "/importar":
        _cmd_importar(franquiciado)
    elif cmd == "/estado":
        _cmd_estado(franquiciado)
    # Ignorar silenciosamente cualquier otro comando

    return "ok", 200
