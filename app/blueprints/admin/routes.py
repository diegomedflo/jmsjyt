"""Rutas del panel de administración."""
from __future__ import annotations

from flask import (
    flash, redirect, render_template, request, url_for, current_app,
)
from flask_login import login_required

from app.extensions import db
from app.models import (
    AdminUser, AlertaLog, Configuracion, CronLog,
    Franquiciado, Paquete,
)
from app.models.excel_import import ExcelImport

from .forms import ConfiguracionForm, FranquiciadoForm, ImportarWaybillsForm, ImportarExcelForm
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
            nombre                =form.nombre.data.strip(),
            jt_user               =form.jt_user.data.strip(),
            jt_pass               =form.jt_pass.data,
            wa_grupo_id           =form.wa_grupo_id.data.strip(),
            wa_status_grupo_id    =form.wa_status_grupo_id.data.strip() or None,
            textmebot_api_key     =form.textmebot_api_key.data.strip(),
            activo                =form.activo.data,
            notas                 =form.notas.data or None,
            horas_total_entrega   =form.horas_total_entrega.data,
            horas_primera_gestion =form.horas_primera_gestion.data,
        )
        db.session.add(fq)
        db.session.commit()
        flash(f"Franquiciado «{fq.nombre}» creado correctamente.", "success")
        return redirect(url_for("admin.franquiciados_detalle", fq_id=fq.id))

    return render_template("admin/franquiciados/form.html", form=form, modo="nuevo")


@admin_bp.route("/franquiciados/<int:fq_id>")
@login_required
def franquiciados_detalle(fq_id: int):
    fq      = db.get_or_404(Franquiciado, fq_id)
    page    = request.args.get("page", 1, type=int)
    estado  = request.args.get("estado", "")
    q_pkg   = Paquete.query.filter_by(franquiciado_id=fq_id)
    if estado:
        q_pkg = q_pkg.filter_by(estado=estado)
    q_pkg      = q_pkg.order_by(Paquete.created_at.desc())
    pagination = q_pkg.paginate(page=page, per_page=50, error_out=False)
    alertas    = AlertaLog.query.filter_by(franquiciado_id=fq_id).order_by(
        AlertaLog.enviado_at.desc()
    ).limit(20).all()
    return render_template(
        "admin/franquiciados/detalle.html",
        fq=fq,
        paquetes=pagination.items,
        pagination=pagination,
        estado_filtro=estado,
        alertas=alertas,
    )


@admin_bp.route("/franquiciados/<int:fq_id>/editar", methods=["GET", "POST"])
@login_required
def franquiciados_editar(fq_id: int):
    fq   = db.get_or_404(Franquiciado, fq_id)
    form = FranquiciadoForm(obj=fq)

    if form.validate_on_submit():
        fq.nombre                = form.nombre.data.strip()
        fq.jt_user               = form.jt_user.data.strip()
        if form.jt_pass.data:
            fq.jt_pass = form.jt_pass.data
        fq.wa_grupo_id           = form.wa_grupo_id.data.strip()
        fq.wa_status_grupo_id    = form.wa_status_grupo_id.data.strip() or None
        fq.textmebot_api_key     = form.textmebot_api_key.data.strip()
        fq.activo                = form.activo.data
        fq.notas                 = form.notas.data or None
        fq.horas_total_entrega   = form.horas_total_entrega.data
        fq.horas_primera_gestion = form.horas_primera_gestion.data
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


# ── Importar Excel (J&T "Monitoreo entrada al puerto") ───────────────────────

@admin_bp.route("/franquiciados/<int:fq_id>/paquetes/importar-excel", methods=["GET", "POST"])
@login_required
def paquetes_importar_excel(fq_id: int):
    """Sube un Excel exportado desde JMS y agrega sus waybills al franquiciado."""
    from app.services.importar_service import parse_excel_waybills, import_waybills
    from app.services.google_drive_service import google_drive_service as drive_service

    fq   = db.get_or_404(Franquiciado, fq_id)
    form = ImportarExcelForm()

    if form.validate_on_submit():
        uploaded = form.excel_file.data
        file_bytes = uploaded.read()
        filename   = uploaded.filename

        # 1. Parsear Excel
        try:
            waybills = parse_excel_waybills(file_bytes)
        except Exception as exc:
            flash(f"Error al leer el Excel: {exc}", "danger")
            return render_template("admin/paquetes/importar_excel.html", form=form, fq=fq)

        if not waybills:
            flash("El Excel no contiene waybills válidos.", "warning")
            return render_template("admin/paquetes/importar_excel.html", form=form, fq=fq)

        # 2. Subir a Google Drive (si hay credenciales)
        drive_file_id = None
        folder_id = current_app.config.get("GOOGLE_DRIVE_FOLDER_ID")
        if folder_id:
            try:
                drive_file_id = drive_service.upload_file(
                    file_bytes=file_bytes,
                    filename=filename,
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        if filename.lower().endswith(".xlsx")
                        else "application/vnd.ms-excel"
                    ),
                    folder_id=folder_id,
                )
                flash(
                    f'Excel guardado en Drive. '
                    f'<a href="https://drive.google.com/file/d/{drive_file_id}/view" '
                    f'target="_blank">Ver archivo</a>',
                    "info",
                )
            except Exception as exc:
                current_app.logger.warning(f"Drive upload falló: {exc}")
                flash("No se pudo subir el Excel a Google Drive (credenciales no configuradas o error de red).", "warning")

        # 3. Importar a BD
        result = import_waybills(
            franquiciado_id=fq_id,
            waybills=waybills,
            filename=filename,
            drive_file_id=drive_file_id,
            import_mode="manual",
        )

        flash(
            f"{result['nuevos']} paquete(s) agregado(s). "
            f"{result['duplicados']} duplicado(s) ignorado(s). "
            f"Total en Excel: {result['total']}.",
            "success",
        )
        return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))

    return render_template("admin/paquetes/importar_excel.html", form=form, fq=fq)


# ── Sincronizar automáticamente desde el portal J&T ─────────────────────────

@admin_bp.route("/franquiciados/<int:fq_id>/paquetes/sincronizar", methods=["POST"])
@login_required
def paquetes_sincronizar(fq_id: int):
    """Usa el scraper OutletMonitor para obtener waybills directamente del portal."""
    from datetime import date, timedelta
    from jt_scraper.outlet_monitor import OutletMonitor
    from jt_scraper.instance_config import JTInstanceConfig
    from app.services.importar_service import import_waybills
    from app.models import Configuracion

    fq  = db.get_or_404(Franquiciado, fq_id)
    cfg = Configuracion.get()

    instance_cfg = JTInstanceConfig(
        jt_user=fq.jt_user,
        jt_pass=fq.jt_pass,
        token_getter=fq.get_token_cache,
        token_setter=lambda v: (fq.set_token_cache(v), db.session.commit()),
    )

    try:
        monitor    = OutletMonitor(instance_cfg)
        start_date = (date.today() - timedelta(days=cfg.sync_dias_atras)).isoformat()
        end_date   = date.today().isoformat()
        waybills   = monitor.fetch_waybills(start_date, end_date, time_type=cfg.sync_time_type)

        if not waybills:
            flash("El scraper no encontró waybills en el portal.", "warning")
            return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))

        result = import_waybills(
            franquiciado_id=fq_id,
            waybills=waybills,
            filename=f"auto_sync_{end_date}.xlsx",
            import_mode="auto",
        )
        flash(
            f"Sincronización completa: {result['nuevos']} nuevo(s), "
            f"{result['duplicados']} duplicado(s). Total encontrado: {result['total']}.",
            "success",
        )
    except Exception as exc:
        current_app.logger.exception(f"Error en sincronización franq={fq_id}")
        flash(f"Error en sincronización: {exc}", "danger")

    return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))


@admin_bp.route("/paquetes/<int:pkg_id>/cancelar", methods=["POST"])
@login_required
def paquetes_cancelar(pkg_id: int):
    pkg = db.get_or_404(Paquete, pkg_id)
    fq_id = pkg.franquiciado_id
    pkg.estado = Paquete.ESTADO_CANCELADO
    db.session.commit()
    flash(f"Paquete {pkg.waybill_no} cancelado.", "info")
    return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))


@admin_bp.route("/paquetes/<int:pkg_id>/siniestrar", methods=["POST"])
@login_required
def paquetes_siniestrar(pkg_id: int):
    pkg = db.get_or_404(Paquete, pkg_id)
    fq_id = pkg.franquiciado_id
    pkg.estado = Paquete.ESTADO_SINIESTRADO
    db.session.commit()
    flash(f"Paquete {pkg.waybill_no} marcado como siniestrado.", "warning")
    return redirect(url_for("admin.franquiciados_detalle", fq_id=fq_id))


# ── Actualizar tracking de un franquiciado ───────────────────────────────────

@admin_bp.route("/franquiciados/<int:fq_id>/paquetes/actualizar-tracking", methods=["POST"])
@login_required
def paquetes_actualizar_tracking(fq_id: int):
    """Consulta el POD de J&T para cada paquete pendiente del franquiciado
    y actualiza fecha_recojo, n_intentos, ultimo_intento_at, ultima_gestion_at.
    Equivale a ejecutar el cron solo para este franquiciado."""
    from app.services.tracking_service import refrescar_franquiciado

    fq = db.get_or_404(Franquiciado, fq_id)

    try:
        stats = refrescar_franquiciado(fq, flask_debug=current_app.debug)
        flash(
            f"Tracking actualizado: {stats['consultados']} paquete(s) procesado(s). "
            f"Entregados: {stats['entregados']} · Devueltos: {stats['devueltos']} · "
            f"Errores: {stats['errores']}.",
            "success" if stats["errores"] == 0 else "warning",
        )
    except Exception as exc:
        current_app.logger.exception(f"Error actualizando tracking franq={fq_id}")
        flash(f"Error al actualizar tracking: {exc}", "danger")

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
        cfg.umbral_dia            = form.umbral_dia.data
        cfg.umbral_22             = form.umbral_22.data
        cfg.umbral_23             = form.umbral_23.data
        cfg.hora_inicio           = form.hora_inicio.data
        cfg.hora_fin              = form.hora_fin.data
        cfg.delay_whatsapp        = form.delay_whatsapp.data
        cfg.sync_dias_atras       = form.sync_dias_atras.data
        cfg.sync_time_type        = form.sync_time_type.data
        cfg.horas_entre_gestiones = form.horas_entre_gestiones.data
        db.session.commit()
        flash("Configuración guardada.", "success")
        return redirect(url_for("admin.configuracion"))

    return render_template("admin/configuracion/form.html", form=form, cfg=cfg)
