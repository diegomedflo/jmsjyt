"""Rutas del panel de administración."""
from __future__ import annotations

from flask import (
    flash, redirect, render_template, request, url_for,
)
from flask_login import login_required

from app.extensions import db
from app.models import (
    AdminUser, AlertaLog, Configuracion, CronLog,
    Franquiciado, Paquete,
)

from .forms import ConfiguracionForm, FranquiciadoForm, ImportarWaybillsForm
from . import admin_bp


# ── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@login_required
def dashboard():
    total_franquiciados = Franquiciado.query.count()
    activos             = Franquiciado.query.filter_by(activo=True).count()
    total_paquetes      = Paquete.query.count()
    pendientes          = Paquete.query.filter_by(estado="pendiente").count()
    ultimo_cron         = CronLog.query.order_by(CronLog.ejecutado_at.desc()).first()
    return render_template(
        "admin/dashboard.html",
        total_franquiciados=total_franquiciados,
        activos=activos,
        total_paquetes=total_paquetes,
        pendientes=pendientes,
        ultimo_cron=ultimo_cron,
    )


# ── Franquiciados ────────────────────────────────────────────────────────────

@admin_bp.route("/franquiciados")
@login_required
def franquiciados_lista():
    franquiciados = Franquiciado.query.order_by(Franquiciado.nombre).all()
    return render_template("admin/franquiciados/lista.html", franquiciados=franquiciados)


@admin_bp.route("/franquiciados/nuevo", methods=["GET", "POST"])
@login_required
def franquiciados_nuevo():
    form = FranquiciadoForm()
    if form.validate_on_submit():
        if not form.jt_pass.data:
            flash("La contraseña JMS es obligatoria al crear un franquiciado.", "danger")
            return render_template("admin/franquiciados/form.html", form=form, modo="nuevo")

        fq = Franquiciado(
            nombre            =form.nombre.data.strip(),
            jt_user           =form.jt_user.data.strip(),
            jt_pass           =form.jt_pass.data,
            wa_grupo_id       =form.wa_grupo_id.data.strip(),
            wa_status_grupo_id=form.wa_status_grupo_id.data.strip() or None,
            textmebot_api_key =form.textmebot_api_key.data.strip(),
            activo            =form.activo.data,
            notas             =form.notas.data or None,
        )
        db.session.add(fq)
        db.session.commit()
        flash(f"Franquiciado «{fq.nombre}» creado correctamente.", "success")
        return redirect(url_for("admin.franquiciados_detalle", fq_id=fq.id))

    return render_template("admin/franquiciados/form.html", form=form, modo="nuevo")


@admin_bp.route("/franquiciados/<int:fq_id>")
@login_required
def franquiciados_detalle(fq_id: int):
    fq         = db.get_or_404(Franquiciado, fq_id)
    paquetes   = Paquete.query.filter_by(franquiciado_id=fq_id).order_by(
        Paquete.estado, Paquete.created_at.desc()
    ).limit(100).all()
    alertas    = AlertaLog.query.filter_by(franquiciado_id=fq_id).order_by(
        AlertaLog.enviado_at.desc()
    ).limit(20).all()
    return render_template(
        "admin/franquiciados/detalle.html",
        fq=fq, paquetes=paquetes, alertas=alertas,
    )


@admin_bp.route("/franquiciados/<int:fq_id>/editar", methods=["GET", "POST"])
@login_required
def franquiciados_editar(fq_id: int):
    fq   = db.get_or_404(Franquiciado, fq_id)
    form = FranquiciadoForm(obj=fq)

    if form.validate_on_submit():
        fq.nombre             = form.nombre.data.strip()
        fq.jt_user            = form.jt_user.data.strip()
        if form.jt_pass.data:
            fq.jt_pass = form.jt_pass.data
        fq.wa_grupo_id        = form.wa_grupo_id.data.strip()
        fq.wa_status_grupo_id = form.wa_status_grupo_id.data.strip() or None
        fq.textmebot_api_key  = form.textmebot_api_key.data.strip()
        fq.activo             = form.activo.data
        fq.notas              = form.notas.data or None
        # Invalidar cache de token si cambia el usuario o clave
        fq.jt_token_cache = None
        db.session.commit()
        flash(f"Franquiciado «{fq.nombre}» actualizado.", "success")
        return redirect(url_for("admin.franquiciados_detalle", fq_id=fq.id))

    return render_template("admin/franquiciados/form.html", form=form, modo="editar", fq=fq)


@admin_bp.route("/franquiciados/<int:fq_id>/toggle", methods=["POST"])
@login_required
def franquiciados_toggle(fq_id: int):
    fq = db.get_or_404(Franquiciado, fq_id)
    fq.activo = not fq.activo
    db.session.commit()
    estado = "activado" if fq.activo else "desactivado"
    flash(f"Franquiciado «{fq.nombre}» {estado}.", "info")
    return redirect(url_for("admin.franquiciados_lista"))


# ── Paquetes ─────────────────────────────────────────────────────────────────

@admin_bp.route("/franquiciados/<int:fq_id>/paquetes/importar", methods=["GET", "POST"])
@login_required
def paquetes_importar(fq_id: int):
    fq   = db.get_or_404(Franquiciado, fq_id)
    form = ImportarWaybillsForm()

    if form.validate_on_submit():
        raw_lines = form.waybills.data.splitlines()
        waybills  = [l.strip() for l in raw_lines if l.strip()]

        agregados = 0
        duplicados = 0
        for wb in waybills:
            existente = Paquete.query.filter_by(
                franquiciado_id=fq_id, waybill_no=wb
            ).first()
            if existente:
                duplicados += 1
                continue
            db.session.add(Paquete(
                franquiciado_id=fq_id,
                waybill_no=wb,
                estado="pendiente",
            ))
            agregados += 1

        db.session.commit()
        flash(
            f"{agregados} paquete(s) importado(s). {duplicados} duplicado(s) ignorado(s).",
            "success",
        )
        return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))

    return render_template("admin/paquetes/importar.html", form=form, fq=fq)


@admin_bp.route("/paquetes/<int:pkg_id>/cancelar", methods=["POST"])
@login_required
def paquetes_cancelar(pkg_id: int):
    pkg = db.get_or_404(Paquete, pkg_id)
    fq_id = pkg.franquiciado_id
    pkg.estado = Paquete.ESTADO_CANCELADO
    db.session.commit()
    flash(f"Paquete {pkg.waybill_no} cancelado.", "info")
    return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))


# ── Cron Logs ────────────────────────────────────────────────────────────────

@admin_bp.route("/cron-logs")
@login_required
def cron_logs():
    logs = CronLog.query.order_by(CronLog.ejecutado_at.desc()).limit(100).all()
    return render_template("admin/cron_logs/lista.html", logs=logs)


# ── Alertas Log ──────────────────────────────────────────────────────────────

@admin_bp.route("/alertas")
@login_required
def alertas_lista():
    page    = request.args.get("page", 1, type=int)
    fq_id   = request.args.get("franquiciado_id", type=int)

    query = AlertaLog.query.order_by(AlertaLog.enviado_at.desc())
    if fq_id:
        query = query.filter_by(franquiciado_id=fq_id)

    pagination  = query.paginate(page=page, per_page=50, error_out=False)
    franquiciados = Franquiciado.query.order_by(Franquiciado.nombre).all()
    return render_template(
        "admin/alertas/lista.html",
        pagination=pagination,
        alertas=pagination.items,
        franquiciados=franquiciados,
        fq_id_filtro=fq_id,
    )


# ── Configuración ────────────────────────────────────────────────────────────

@admin_bp.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    cfg  = Configuracion.get()
    form = ConfiguracionForm(obj=cfg)

    if form.validate_on_submit():
        cfg.umbral_dia     = form.umbral_dia.data
        cfg.umbral_22      = form.umbral_22.data
        cfg.umbral_23      = form.umbral_23.data
        cfg.hora_inicio    = form.hora_inicio.data
        cfg.hora_fin       = form.hora_fin.data
        cfg.delay_whatsapp = form.delay_whatsapp.data
        db.session.commit()
        flash("Configuración guardada.", "success")
        return redirect(url_for("admin.configuracion"))

    return render_template("admin/configuracion/form.html", form=form, cfg=cfg)
