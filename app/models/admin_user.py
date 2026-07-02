"""Modelos SQLAlchemy — AdminUser."""
from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


class AdminUser(UserMixin, db.Model):
    """Usuario del panel de administración."""

    __tablename__ = "admin_users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<AdminUser {self.username!r}>"


@login_manager.user_loader
def load_user(user_id: str) -> AdminUser | None:
    return db.session.get(AdminUser, int(user_id))
