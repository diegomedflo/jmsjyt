"""Rutas de autenticación — login y logout."""
from flask import redirect, render_template, request, url_for, flash
from flask_login import current_user, login_user, logout_user

from app.extensions import limiter
from app.models import AdminUser

from . import auth_bp


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = AdminUser.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=False)
            next_url = request.args.get("next") or url_for("admin.dashboard")
            # Protección contra open-redirect
            if not next_url.startswith("/"):
                next_url = url_for("admin.dashboard")
            return redirect(next_url)

        flash("Usuario o contraseña incorrectos.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
