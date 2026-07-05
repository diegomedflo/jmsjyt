"""Rutas del portal del franquiciado — acceso limitado sin panel admin."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    flash, redirect, render_template, request,
    session, url_for,
)

from app.extensions import db, limiter
from app.models import Franquiciado, Paquete
from app.models.franquiciado_user import FranquiciadoUser

from . import fq_portal_bp

# ── Constantes ────────────────────────────────────────────────────────────────
_SESSION_KEY     = "fq_portal_user_id"
_PERU_OFFSET     = timedelta(hours=5)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _current_fq_user() -> FranquiciadoUser | None:
    uid = session.get(_SESSION_KEY)
    return db.session.get(FranquiciadoUser, uid) if uid else None


def _portal_required(f):
    """Verifica sesión de franquiciado y que el fq_id coincida."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _current_fq_user()
        fq_id = kwargs.get("fq_id")
        if user is None or not user.activo:
            session.pop(_SESSION_KEY, None)
            return redirect(url_for("franquiciado.login"))
        if fq_id is not None and user.franquiciado_id != fq_id:
            return redirect(url_for("franquiciado.portal", fq_id=user.franquiciado_id))
        return f(*args, **kwargs)
    return decorated


# ── Login / Logout ────────────────────────────────────────────────────────────

@fq_portal_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    user = _current_fq_user()
    if user and user.activo:
        return redirect(url_for("franquiciado.portal", fq_id=user.franquiciado_id))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        fq_user  = FranquiciadoUser.query.filter_by(username=username, activo=True).first()
        if fq_user and fq_user.check_password(password):
            session[_SESSION_KEY] = fq_user.id
            return redirect(url_for("franquiciado.portal", fq_id=fq_user.franquiciado_id))
        flash("Usuario o contraseña incorrectos.", "danger")

    return render_template("franquiciado/login.html")


@fq_portal_bp.route("/logout")
def logout():
    session.pop(_SESSION_KEY, None)
    return redirect(url_for("franquiciado.login"))


# ── Portal principal ──────────────────────────────────────────────────────────

@fq_portal_bp.route("/<int:fq_id>/portal")
@_portal_required
def portal(fq_id: int):
    fq      = db.get_or_404(Franquiciado, fq_id)
    fq_user = _current_fq_user()

    page        = request.args.get("page", 1, type=int)
    estado      = request.args.get("estado", "")
    q_waybill   = request.args.get("q", "").strip()
    campo_fecha = request.args.get("campo_fecha", "")
    fecha_desde = request.args.get("fecha_desde", "")
    fecha_hasta = request.args.get("fecha_hasta", "")

    q_pkg = Paquete.query.filter_by(franquiciado_id=fq_id)
    if q_waybill:
        q_pkg = q_pkg.filter(Paquete.waybill_no.ilike(f"%{q_waybill}%"))
    if estado:
        q_pkg = q_pkg.filter_by(estado=estado)

    _campo_map = {
        "recojo":    Paquete.fecha_recojo,
        "gestion":   Paquete.ultima_gestion_at,
        "importado": Paquete.created_at,
    }
    _col = _campo_map.get(campo_fecha)
    if _col is not None:
        if fecha_desde:
            try:
                q_pkg = q_pkg.filter(_col >= datetime.strptime(fecha_desde, "%Y-%m-%d"))
            except ValueError:
                pass
        if fecha_hasta:
            try:
                dt_h = datetime.strptime(fecha_hasta, "%Y-%m-%d") + timedelta(days=1)
                q_pkg = q_pkg.filter(_col < dt_h)
            except ValueError:
                pass

    pagination = q_pkg.order_by(Paquete.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    return render_template(
        "franquiciado/portal.html",
        fq=fq,
        fq_user=fq_user,
        paquetes=pagination.items,
        pagination=pagination,
        estado_filtro=estado,
        campo_fecha=campo_fecha,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        q_waybill=q_waybill,
        now=datetime.now(timezone.utc),
        last_tracking_peru=(fq.last_tracking_at - _PERU_OFFSET) if fq.last_tracking_at else None,
    )


# ── Importar paquetes por texto ───────────────────────────────────────────────

@fq_portal_bp.route("/<int:fq_id>/importar-texto", methods=["POST"])
@_portal_required
def importar_texto(fq_id: int):
    raw      = request.form.get("waybills", "")
    waybills = [l.strip() for l in raw.replace(",", "\n").splitlines() if l.strip()]

    if not waybills:
        flash("No se ingresaron códigos válidos.", "warning")
        return redirect(url_for("franquiciado.portal", fq_id=fq_id))

    agregados = duplicados = 0
    for wb in waybills:
        if not Paquete.query.filter_by(franquiciado_id=fq_id, waybill_no=wb).first():
            db.session.add(Paquete(franquiciado_id=fq_id, waybill_no=wb, estado="pendiente"))
            agregados += 1
        else:
            duplicados += 1
    db.session.commit()
    flash(
        f"{agregados} paquete(s) agregado(s). {duplicados} duplicado(s) ignorado(s).",
        "success",
    )
    return redirect(url_for("franquiciado.portal", fq_id=fq_id))


# ── Enviar resumen de estado por WhatsApp ─────────────────────────────────────

@fq_portal_bp.route("/<int:fq_id>/wa-estado", methods=["POST"])
@_portal_required
def wa_estado(fq_id: int):
    from app.blueprints.whatsapp.webhook import _build_estado_message
    from app.services.whatsapp_service import enviar_whatsapp

    fq       = db.get_or_404(Franquiciado, fq_id)
    now_utc  = datetime.utcnow()
    now_peru = now_utc - _PERU_OFFSET
    msg      = _build_estado_message(fq, now_peru)
    ok, resp = enviar_whatsapp(fq.textmebot_api_key, fq.wa_grupo_id, msg)
    fq.last_wa_estado_at = now_utc
    db.session.commit()

    flash("Resumen enviado al grupo WhatsApp." if ok else f"Error al enviar: {resp}",
          "success" if ok else "danger")
    return redirect(url_for("franquiciado.portal", fq_id=fq_id))


# ── Dashboard (solo si puede_ver_dashboard) ───────────────────────────────────

@fq_portal_bp.route("/<int:fq_id>/dashboard")
@_portal_required
def dashboard(fq_id: int):
    fq_user = _current_fq_user()
    if not fq_user.puede_ver_dashboard:
        flash("No tienes acceso al dashboard.", "warning")
        return redirect(url_for("franquiciado.portal", fq_id=fq_id))

    # Reutiliza la lógica de queries del dashboard admin
    from sqlalchemy import func, cast
    from sqlalchemy.types import Date as SADate

    fq  = db.get_or_404(Franquiciado, fq_id)
    hoy = datetime.utcnow().date()

    _min_recojo  = db.session.query(func.min(Paquete.fecha_recojo)).filter(
        Paquete.franquiciado_id == fq_id, Paquete.fecha_recojo.isnot(None)
    ).scalar()
    _min_entrega = db.session.query(func.min(Paquete.ultima_gestion_at)).filter(
        Paquete.franquiciado_id == fq_id, Paquete.ultima_gestion_at.isnot(None)
    ).scalar()

    def _to_date(v):
        return v.date() if v is not None and hasattr(v, "date") else v

    _candidates = [_to_date(_min_recojo), _to_date(_min_entrega)]
    primer_dia  = min(d for d in _candidates if d is not None) if any(_candidates) else hoy - timedelta(days=29)
    fecha_inicio = datetime(primer_dia.year, primer_dia.month, primer_dia.day)

    por_estado_raw = (
        db.session.query(Paquete.estado, func.count().label("n"))
        .filter(Paquete.franquiciado_id == fq_id)
        .group_by(Paquete.estado).all()
    )
    por_estado     = {r.estado: r.n for r in por_estado_raw}
    total_paquetes = sum(por_estado.values())
    tasa_entrega   = (
        round(por_estado.get("entregado", 0) / total_paquetes * 100, 1)
        if total_paquetes else 0
    )

    n_dias      = (hoy - primer_dia).days + 1
    dias_date   = [primer_dia + timedelta(days=i) for i in range(n_dias)]
    dias_iso    = [d.isoformat() for d in dias_date]
    dias_labels = [d.strftime("%d/%m") for d in dias_date]

    def _key(val):
        return val.isoformat() if hasattr(val, "isoformat") else str(val)[:10]

    dia_recojo    = cast(Paquete.fecha_recojo, SADate)
    recogidos_raw = (
        db.session.query(dia_recojo.label("dia"), func.count().label("n"))
        .filter(Paquete.franquiciado_id == fq_id, Paquete.fecha_recojo >= fecha_inicio)
        .group_by(dia_recojo).all()
    )
    recogidos_map = {_key(r.dia): r.n for r in recogidos_raw}

    dia_gestion    = cast(Paquete.ultima_gestion_at, SADate)
    entregados_raw = (
        db.session.query(dia_gestion.label("dia"), func.count().label("n"))
        .filter(
            Paquete.franquiciado_id == fq_id,
            Paquete.estado == "entregado",
            Paquete.ultima_gestion_at >= fecha_inicio,
        ).group_by(dia_gestion).all()
    )
    entregados_map = {_key(r.dia): r.n for r in entregados_raw}

    recogidos_series  = [recogidos_map.get(d, 0) for d in dias_iso]
    entregados_series = [entregados_map.get(d, 0) for d in dias_iso]

    return render_template(
        "admin/franquiciados/dashboard.html",
        fq=fq,
        fq_user=fq_user,
        portal_mode=True,
        por_estado=por_estado,
        total_paquetes=total_paquetes,
        tasa_entrega=tasa_entrega,
        dias_labels=dias_labels,
        recogidos_series=recogidos_series,
        entregados_series=entregados_series,
    )


# ── Historial de tracking (versión franquiciado) ──────────────────────────────

@fq_portal_bp.route("/<int:fq_id>/paquetes/<int:pkg_id>/tracking-historial")
@_portal_required
def paquete_tracking_historial(fq_id: int, pkg_id: int):
    pkg = db.get_or_404(Paquete, pkg_id)
    if pkg.franquiciado_id != fq_id:
        return {"error": "No autorizado"}, 403

    historial = pkg.historial.all()

    from app.services.tracking_service import (
        _es_recojo_almacen, TIPO_EXCEPCION, TIPO_ENTREGADO,
        _es_devolucion_jyt, _es_gestion,
    )

    recojo_id      = None
    exception_count = 0
    events_data    = []

    for ev in historial:
        if recojo_id is None and _es_recojo_almacen(ev.descripcion or "", ev.tipo_escaneo or ""):
            recojo_id = ev.id

    for ev in historial:
        h_label = h_class = None
        if ev.id == recojo_id:
            h_label, h_class = "Recojo", "recojo"
        elif (ev.tipo_escaneo or "").strip() == TIPO_EXCEPCION:
            exception_count += 1
            lbl_map = {1: ("1er Fallido", "fallido-1"), 2: ("2do Fallido", "fallido-2"), 3: ("3er Fallido", "fallido-3")}
            h_label, h_class = lbl_map.get(exception_count, (f"{exception_count}o Fallido", "fallido-other"))
        elif (ev.tipo_escaneo or "").strip() == TIPO_ENTREGADO:
            h_label, h_class = "Entregado", "entregado"
        elif _es_devolucion_jyt(ev.tipo_escaneo or ""):
            h_label, h_class = "Devuelto", "devuelto"

        es_gest = bool(
            pkg.fecha_recojo and ev.hora_escaneo and ev.hora_escaneo > pkg.fecha_recojo
            and _es_gestion(ev.tipo_escaneo or "", ev.descripcion or "")
        )
        events_data.append({
            "id": ev.id, "n_orden": ev.n_orden,
            "hora_escaneo": ev.hora_escaneo.strftime("%d/%m/%Y %H:%M:%S") if ev.hora_escaneo else "—",
            "tipo_escaneo": ev.tipo_escaneo,
            "descripcion": ev.descripcion,
            "interpretacion": ev.interpretacion,
            "label": h_label, "class": h_class, "es_gestion": es_gest,
        })

    return {
        "waybill_no": pkg.waybill_no,
        "estado": pkg.estado,
        "n_intentos": pkg.n_intentos,
        "fecha_recojo": pkg.fecha_recojo.strftime("%d/%m/%Y %H:%M:%S") if pkg.fecha_recojo else None,
        "ultimo_intento_at": pkg.ultimo_intento_at.strftime("%d/%m/%Y %H:%M:%S") if pkg.ultimo_intento_at else None,
        "ultima_gestion_at": pkg.ultima_gestion_at.strftime("%d/%m/%Y %H:%M:%S") if pkg.ultima_gestion_at else None,
        "historial": events_data,
    }
