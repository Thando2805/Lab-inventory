from datetime import date, datetime
from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_file)
from flask_login import LoginManager, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from models import (db, User, Item, Transaction, Area, AuditLog,
                    CATEGORIES)
from forms import LoginForm, ItemForm, TransactionForm
from auth import auth_bp, role_required
from services import import_workbook, export_native, export_sop

login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_globals():
        return {"CATEGORIES": CATEGORIES}

    register_routes(app)

    with app.app_context():
        db.create_all()
        bootstrap_admin(app)
        bootstrap_areas(app)

    return app


def bootstrap_admin(app):
    if User.query.count() > 0:
        return
    u = User(
        username=app.config["ADMIN_USERNAME"],
        role="admin",
        full_name=app.config["ADMIN_FULLNAME"],
        is_active=True,
    )
    u.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(u)
    db.session.commit()
    app.logger.info(f"Bootstrap admin '{u.username}' created.")


DEFAULT_AREAS = [
    "Biochemical Analysis",
    "Microbio 2",
    "Preparation Lab",
    "Preparation Room",
    "Microbiology Lab Equipment",
    "Microbiology Lab",
]


def bootstrap_areas(app):
    if Area.query.count() > 0:
        return
    for i, name in enumerate(DEFAULT_AREAS):
        db.session.add(Area(name=name, sort_order=i))
    db.session.commit()
    app.logger.info("Default areas created.")


ID_PREFIX = {
    "Apparatus": "APP",
    "Equipment": "EQU",
    "Reagent": "RGT",
    "Chemical": "CHM",
    "Consumable": "CON",
}


def next_inventory_id(category):
    prefix = ID_PREFIX.get(category, "ITM")
    existing = Item.query.filter(Item.inventory_id.like(f"{prefix}-%")).all()
    max_n = 0
    for it in existing:
        try:
            n = int(it.inventory_id.split("-")[-1])
            max_n = max(max_n, n)
        except (ValueError, IndexError):
            continue
    return f"{prefix}-{max_n + 1:03d}"


def log_audit(action, entity_type=None, entity_id=None):
    db.session.add(AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=request.remote_addr,
    ))


def register_routes(app):

    @app.route("/health")
    def health():
        return {"status": "ok", "service": "lab-inventory"}, 200

    # ----- Dashboard ---------------------------------------------------------
    @app.route("/")
    @login_required
    def index():
        items = Item.query.filter_by(is_archived=False).all()

        total_lines = len(items)
        critical = sum(1 for i in items if i.stock_status == "CRITICAL")
        below_min = sum(1 for i in items if i.stock_status == "BELOW MIN")
        reorder = sum(1 for i in items if i.stock_status == "REORDER")
        ok = sum(1 for i in items if i.stock_status == "OK")

        near_expiry = sum(1 for i in items if i.expiry_status == "NEAR EXPIRY")
        expired = sum(1 for i in items if i.expiry_status == "EXPIRED")

        service_due_30 = sum(1 for i in items if i.service_status == "DUE <=30 DAYS")
        service_overdue = sum(1 for i in items if i.service_status == "OVERDUE")

        total_value = round(sum(i.current_value for i in items), 2)

        cat_counts = {c: sum(1 for i in items if i.category == c)
                      for c in CATEGORIES}

        return render_template(
            "dashboard.html",
            total_lines=total_lines,
            critical=critical,
            below_min=below_min,
            reorder=reorder,
            ok=ok,
            near_expiry=near_expiry,
            expired=expired,
            service_due_30=service_due_30,
            service_overdue=service_overdue,
            total_value=total_value,
            cat_counts=cat_counts,
            categories=CATEGORIES,
        )

    # ----- Section -----------------------------------------------------------
    @app.route("/section/<category>")
    @login_required
    def section(category):
        if category not in CATEGORIES:
            flash("Unknown category.", "error")
            return redirect(url_for("index"))

        show = request.args.get("show", "active")
        area_id = request.args.get("area", type=int)
        q = request.args.get("q", "").strip()

        query = Item.query.filter_by(category=category, is_archived=False)

        if area_id:
            query = query.filter_by(area_id=area_id)

        if q:
            like = f"%{q}%"
            query = query.filter(db.or_(
                Item.name.ilike(like),
                Item.inventory_id.ilike(like),
                Item.lot_serial.ilike(like),
                Item.location.ilike(like),
            ))

        items = query.order_by(Item.name).all()

        if show == "active":
            items = [i for i in items if i.current_qty > 0]
        elif show == "low":
            items = [i for i in items
                     if i.current_qty > 0
                     and i.stock_status in ("CRITICAL", "BELOW MIN", "REORDER")]
        elif show == "out":
            items = [i for i in items if i.current_qty <= 0]

        all_in_cat = Item.query.filter_by(category=category, is_archived=False).all()
        counts = {
            "active": sum(1 for i in all_in_cat if i.current_qty > 0),
            "low": sum(1 for i in all_in_cat
                       if i.current_qty > 0
                       and i.stock_status in ("CRITICAL", "BELOW MIN", "REORDER")),
            "out": sum(1 for i in all_in_cat if i.current_qty <= 0),
            "all": len(all_in_cat),
        }

        areas = Area.query.order_by(Area.sort_order).all()

        return render_template(
            "section.html",
            category=category,
            items=items,
            show=show,
            area_id=area_id,
            q=q,
            counts=counts,
            areas=areas,
        )

    # ----- Add Item ----------------------------------------------------------
    @app.route("/item/new/<category>", methods=["GET", "POST"])
    @role_required("admin")
    def item_new(category):
        if category not in CATEGORIES:
            abort(404)

        form = ItemForm()
        form.category.data = category
        form.area_id.choices = [(0, "—")] + [
            (a.id, a.name) for a in Area.query.order_by(Area.sort_order).all()
        ]

        if form.validate_on_submit():
            item = Item()
            item.category = category
            item.inventory_id = (form.inventory_id.data or "").strip() \
                                or next_inventory_id(category)
            item.name = form.name.data.strip()
            item.area_id = form.area_id.data or None
            item.manufacturer = form.manufacturer.data
            item.lot_serial = form.lot_serial.data
            item.opening_qty = form.opening_qty.data or 0.0
            item.unit = form.unit.data
            item.location = form.location.data
            item.received_date = form.received_date.data
            item.expiry_date = form.expiry_date.data
            item.min_level = form.min_level.data or 0.0
            item.reorder_level = form.reorder_level.data or 0.0
            item.critical = bool(form.critical.data)
            item.condition_status = form.condition_status.data
            item.service_due = form.service_due.data
            item.unit_value = form.unit_value.data or 0.0
            item.responsible = form.responsible.data
            item.notes = form.notes.data
            item.created_by_id = current_user.id

            db.session.add(item)
            db.session.flush()

            if item.opening_qty > 0:
                db.session.add(Transaction(
                    item_id=item.id,
                    trans_date=date.today(),
                    trans_type="RECEIVE",
                    qty_in=item.opening_qty,
                    unit=item.unit,
                    user_id=current_user.id,
                    reference_notes="Opening balance",
                ))

            log_audit("CREATE", "Item", item.id)
            db.session.commit()

            flash(f"Item {item.inventory_id} created.", "success")
            return redirect(url_for("item_detail", item_id=item.id))

        return render_template("item_form.html", form=form,
                               category=category, item=None)

    # ----- Edit Item ---------------------------------------------------------
    @app.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
    @role_required("admin")
    def item_edit(item_id):
        item = Item.query.get_or_404(item_id)
        form = ItemForm(obj=item)
        form.category.data = item.category
        form.area_id.choices = [(0, "—")] + [
            (a.id, a.name) for a in Area.query.order_by(Area.sort_order).all()
        ]

        if form.validate_on_submit():
            item.inventory_id = (form.inventory_id.data or "").strip() or item.inventory_id
            item.name = form.name.data.strip()
            item.area_id = form.area_id.data or None
            item.manufacturer = form.manufacturer.data
            item.lot_serial = form.lot_serial.data
            item.opening_qty = form.opening_qty.data or 0.0
            item.unit = form.unit.data
            item.location = form.location.data
            item.received_date = form.received_date.data
            item.expiry_date = form.expiry_date.data
            item.min_level = form.min_level.data or 0.0
            item.reorder_level = form.reorder_level.data or 0.0
            item.critical = bool(form.critical.data)
            item.condition_status = form.condition_status.data
            item.service_due = form.service_due.data
            item.unit_value = form.unit_value.data or 0.0
            item.responsible = form.responsible.data
            item.notes = form.notes.data

            log_audit("UPDATE", "Item", item.id)
            db.session.commit()

            flash("Item updated.", "success")
            return redirect(url_for("item_detail", item_id=item.id))

        return render_template("item_form.html", form=form,
                               category=item.category, item=item)

    # ----- Item detail -------------------------------------------------------
    @app.route("/item/<int:item_id>")
    @login_required
    def item_detail(item_id):
        item = Item.query.get_or_404(item_id)
        tx_form = TransactionForm()
        tx_form.unit.data = item.unit
        return render_template("item_detail.html", item=item, tx_form=tx_form)

    # ----- Log transaction ---------------------------------------------------
    @app.route("/item/<int:item_id>/transaction", methods=["POST"])
    @role_required("admin")
    def item_transaction(item_id):
        item = Item.query.get_or_404(item_id)
        form = TransactionForm()

        if not form.validate_on_submit():
            flash("Please check the form values.", "error")
            return redirect(url_for("item_detail", item_id=item.id))

        tx = Transaction(
            item_id=item.id,
            trans_date=form.trans_date.data or date.today(),
            trans_type=form.trans_type.data,
            qty_in=form.qty_in.data or 0.0,
            qty_out=form.qty_out.data or 0.0,
            unit=form.unit.data or item.unit,
            from_location=form.from_location.data,
            to_location=form.to_location.data,
            trans_ref=form.trans_ref.data,
            reference_notes=form.reference_notes.data,
            user_id=current_user.id,
        )
        db.session.add(tx)
        log_audit("CREATE", "Transaction", None)
        db.session.commit()

        flash(f"Movement recorded for {item.inventory_id}.", "success")
        return redirect(url_for("item_detail", item_id=item.id))

    # ----- Archived ----------------------------------------------------------
    @app.route("/archived")
    @login_required
    def archived():
        items = Item.query.filter_by(is_archived=False).all()
        out_items = [i for i in items if i.current_qty <= 0]
        out_items.sort(key=lambda i: (i.category, i.name))
        return render_template("archived.html", items=out_items)

    # ----- Transactions log --------------------------------------------------
    @app.route("/transactions")
    @login_required
    def transactions():
        txs = (Transaction.query
               .order_by(Transaction.entry_date.desc())
               .limit(300).all())
        return render_template("transactions.html", txs=txs)

    # ----- Import ------------------------------------------------------------
    @app.route("/import", methods=["GET", "POST"])
    @role_required("admin")
    def import_page():
        if request.method == "POST":
            f = request.files.get("file")
            if not f or f.filename == "":
                flash("Please choose a file.", "error")
                return redirect(url_for("import_page"))

            try:
                summary = import_workbook(f, current_user.id)
                log_audit("IMPORT", "Item", None)
                db.session.commit()
                return render_template("import.html", summary=summary)
            except Exception as e:
                db.session.rollback()
                flash(f"Import failed: {e}", "error")
                return redirect(url_for("import_page"))

        return render_template("import.html", summary=None)

    # ----- Export ------------------------------------------------------------
    @app.route("/export")
    @login_required
    def export_page():
        return render_template("export.html")

    @app.route("/export/native")
    @login_required
    def export_native_route():
        buf = export_native()
        log_audit("EXPORT", "Item", None)
        db.session.commit()
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"lab_inventory_native_{stamp}.xlsx",
        )

    @app.route("/export/sop")
    @login_required
    def export_sop_route():
        buf = export_sop()
        log_audit("EXPORT", "Item", None)
        db.session.commit()
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"master_inventory_sop_{stamp}.xlsx",
        )


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").getenv("PORT", "5000")), debug=app.config.get("DEBUG", False))