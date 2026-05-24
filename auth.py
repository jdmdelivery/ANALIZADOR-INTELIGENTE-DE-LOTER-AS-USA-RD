"""Autenticación Flask-Login."""

from datetime import datetime
from functools import wraps

from flask import abort, jsonify, redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required

from models import get_user_by_id

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Debes iniciar sesión para continuar."
login_manager.session_protection = "strong"


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.password_hash = row["password_hash"]
        self.nombre = row.get("nombre") or ""
        self.email = row.get("email") or ""
        self.role = row.get("role") or "usuario"
        self._db_active = bool(row.get("is_active", 1))
        self.expires_at = row.get("expires_at")
        self.must_change_password = bool(row.get("must_change_password", 0))
        self.created_at = row.get("created_at")
        self.updated_at = row.get("updated_at")
        self.last_login = row.get("last_login")

    @property
    def is_active(self):
        return self._db_active

    def is_admin(self):
        return self.role == "admin"

    def is_expired(self):
        if not self.expires_at:
            return False
        try:
            exp = datetime.strptime(str(self.expires_at)[:10], "%Y-%m-%d")
            return exp.date() < datetime.now().date()
        except ValueError:
            return False

    def check_access(self):
        if not self._db_active:
            return False, "blocked"
        if self.is_expired():
            return False, "expired"
        return True, None

    def status_badge(self):
        if not self._db_active:
            return "bloqueado", "🔴 Bloqueado"
        if self.is_expired():
            return "vencido", "⏳ Vencido"
        if self.role == "admin":
            return "admin", "👑 Admin"
        return "activo", "🟢 Activo"


@login_manager.user_loader
def load_user(user_id):
    row = get_user_by_id(int(user_id))
    return User(row) if row else None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "No autenticado. Inicia sesión."}), 401
    return redirect(url_for("login", next=request.url))


def init_auth(app):
    login_manager.init_app(app)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "Acceso denegado. Solo administradores."}), 403
            abort(403)
        return view(*args, **kwargs)

    return wrapped
