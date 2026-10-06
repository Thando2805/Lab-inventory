from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from models import db, User, AuditLog
from forms import LoginForm

auth_bp = Blueprint("auth", __name__)


def role_required(*roles):
    def wrapper(fn):
        @wraps(fn)
        @login_required
        def decorated(*args, **kwargs):
            if current_user.role not in roles:
                flash("This action requires admin privileges.", "error")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return decorated
    return wrapper


def _log(user, action, entity_type=None, entity_id=None):
    db.session.add(AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=request.remote_addr,
    ))
    db.session.commit()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=False)
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            _log(user, "LOGIN", "User", user.id)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("index"))
        flash("Invalid credentials.", "error")

    return render_template("login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    _log(current_user, "LOGOUT", "User", current_user.id)
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))