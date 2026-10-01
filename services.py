"""
Import / Export services for the Lab Inventory app.

Two export formats:
  - Native: one sheet per category + a Transactions sheet
  - SOP:    mirror of the controlled workbook (Master Inventory + Stock Movements)

Two import shapes, auto-detected:
  - SOP shape: has Inventory ID + Opening Qty + Min Level
  - Snapshot shape: has Item Description + Quantity + Units (File 2 style)
"""

import io
from datetime import datetime, date
import pandas as pd

from models import (db, Item, Transaction, Area, CATEGORIES)


# -----------------------------------------------------------------------------
# Category mapping for snapshot imports (File 2 -> SOP)
# -----------------------------------------------------------------------------
CATEGORY_MAP = {
    "glassware": "Apparatus",
    "pipettes": "Apparatus",
    "accessories": "Apparatus",
    "equipment": "Equipment",
    "microbiology equipment": "Equipment",
    "chemical": "Chemical",
    "reagent": "Reagent",
    "media": "Reagent",
    "stain": "Reagent",
    "consumable": "Consumable",
    "plasticware": "Consumable",
    "ppe": "Consumable",
    "cleaning material": "Consumable",
    "cleaning materials": "Consumable",
}

ID_PREFIX = {
    "Apparatus": "APP",
    "Equipment": "EQU",
    "Reagent": "RGT",
    "Chemical": "CHM",
    "Consumable": "CON",
}


def next_inventory_id(category):
    prefix = ID_PREFIX.get(category, "ITM")
    rows = Item.query.filter(Item.inventory_id.like(f"{prefix}-%")).all()
    max_n = 0
    for r in rows:
        try:
            max_n = max(max_n, int(r.inventory_id.split("-")[-1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}-{max_n + 1:03d}"


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def _num(v, default=0.0):
    try:
        if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _date(v):
    if v is None or v == "":
        return None
    try:
        d = pd.to_datetime(v, errors="coerce")
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def _norm(c):
    return (c or "").strip().lower()


# -----------------------------------------------------------------------------
# Import — shape detection
# -----------------------------------------------------------------------------
def _read_file(file_storage):
    filename = file_storage.filename.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file_storage)
    # .xlsx / .xls
    return pd.read_excel(file_storage, sheet_name=None)


def detect_shape(df):
    cols = [_norm(c) for c in df.columns]
    has_sop = all(k in cols for k in
                  ["inventory id", "opening qty", "min level"])
    has_snap = all(k in cols for k in
                   ["item description", "quantity", "units"])
    if has_sop:
        return "sop"
    if has_snap:
        return "snapshot"
    return "unknown"


# -----------------------------------------------------------------------------
# Import — SOP shape
# -----------------------------------------------------------------------------
def _import_sop_sheet(df, user_id, default_area=None):
    """Import a single dataframe that matches the SOP Master Inventory layout."""
    df.columns = [_norm(c).replace(" ", "_").replace("/", "_").replace(".", "")
                  for c in df.columns]

    added, updated, skipped = 0, 0, 0

    for _, row in df.iterrows():
        inv_id = _clean(row.get("inventory_id"))
        name = _clean(row.get("item___description")) or _clean(row.get("item_description")) or _clean(row.get("item"))
        if not (inv_id or name):
            skipped += 1
            continue

        category = _clean(row.get("category")) or "Apparatus"
        if category not in CATEGORIES:
            category = "Apparatus"

        existing = None
        if inv_id:
            existing = Item.query.filter_by(inventory_id=inv_id).first()
        elif name:
            existing = Item.query.filter_by(name=name, category=category).first()

        opening = _num(row.get("opening_qty"))
        unit = _clean(row.get("unit")) or "each"
        min_lvl = _num(row.get("min_level"))
        reorder = _num(row.get("reorder_level"))
        critical = _norm(row.get("critical")) in ("yes", "true", "1", "y")
        location = _clean(row.get("location"))
        manufacturer = _clean(row.get("manufacturer___supplier")) \
                       or _clean(row.get("manufacturer_supplier")) \
                       or _clean(row.get("manufacturer"))
        lot = _clean(row.get("lot___serial")) or _clean(row.get("lot_serial")) or _clean(row.get("lot"))
        received = _date(row.get("received___acquired")) or _date(row.get("received_acquired"))
        expiry = _date(row.get("expiry_date"))
        service_due = _date(row.get("cal_service_due")) or _date(row.get("service_due"))
        unit_value = _num(row.get("unit_value__usd")) or _num(row.get("unit_value"))
        responsible = _clean(row.get("responsible_person"))
        condition = _clean(row.get("condition___status")) or _clean(row.get("condition_status")) or "Active"

        if existing:
            existing.opening_qty = opening or existing.opening_qty
            existing.unit = unit or existing.unit
            existing.min_level = min_lvl
            existing.reorder_level = reorder
            existing.critical = critical
            existing.location = location or existing.location
            existing.manufacturer = manufacturer or existing.manufacturer
            existing.lot_serial = lot or existing.lot_serial
            existing.received_date = received or existing.received_date
            existing.expiry_date = expiry or existing.expiry_date
            existing.service_due = service_due or existing.service_due
            existing.unit_value = unit_value or existing.unit_value
            existing.responsible = responsible or existing.responsible
            existing.condition_status = condition or existing.condition_status
            updated += 1
        else:
            item = Item(
                inventory_id=inv_id or next_inventory_id(category),
                name=name or "Unnamed item",
                category=category,
                area_id=default_area,
                manufacturer=manufacturer,
                lot_serial=lot,
                opening_qty=opening,
                unit=unit,
                location=location,
                received_date=received,
                expiry_date=expiry,
                min_level=min_lvl,
                reorder_level=reorder,
                critical=critical,
                condition_status=condition,
                service_due=service_due,
                unit_value=unit_value,
                responsible=responsible,
                created_by_id=user_id,
            )
            db.session.add(item)
            db.session.flush()

            if opening > 0:
                db.session.add(Transaction(
                    item_id=item.id,
                    trans_date=date.today(),
                    trans_type="RECEIVE",
                    qty_in=opening,
                    unit=unit,
                    user_id=user_id,
                    reference_notes="Imported opening balance",
                ))
            added += 1

    return added, updated, skipped


# -----------------------------------------------------------------------------
# Import — Snapshot shape (File 2)
# -----------------------------------------------------------------------------
def _import_snapshot_sheet(df, user_id, sheet_name):
    """Import one sheet where each row is Item Description / Category / Quantity / Units."""
    df.columns = [_norm(c).replace(" ", "_") for c in df.columns]

    # Create area from sheet name if it doesn't exist
    area_name = (sheet_name or "Imported").strip()
    area = Area.query.filter_by(name=area_name).first()
    if not area:
        area = Area(name=area_name,
                    sort_order=(Area.query.count() or 0) + 1)
        db.session.add(area)
        db.session.flush()

    added, updated, skipped = 0, 0, 0

    for _, row in df.iterrows():
        name = _clean(row.get("item_description")) \
               or _clean(row.get("item")) \
               or _clean(row.get("item_number"))
        if not name:
            skipped += 1
            continue

        # Skip obvious summary rows
        n_up = name.upper()
        if n_up.startswith("TOTAL") or n_up == "TOTAL ITEMS":
            skipped += 1
            continue

        raw_cat = _clean(row.get("category")) or ""
        mapped_cat = CATEGORY_MAP.get(_norm(raw_cat), "Consumable")

        qty = _num(row.get("quantity"))
        unit = _clean(row.get("units")) or _clean(row.get("unit")) or "each"

        # Capacity / size gets appended to the name for clarity
        cap = _clean(row.get("capacity"))
        full_name = f"{name} {cap}".strip() if cap and cap != "—" else name

        existing = Item.query.filter_by(name=full_name,
                                        category=mapped_cat).first()
        if existing:
            updated += 1
            continue

        item = Item(
            inventory_id=next_inventory_id(mapped_cat),
            name=full_name,
            category=mapped_cat,
            area_id=area.id,
            opening_qty=qty,
            unit=unit,
            min_level=0.0,
            reorder_level=0.0,
            critical=False,
            condition_status="Active",
            created_by_id=user_id,
        )
        db.session.add(item)
        db.session.flush()

        if qty > 0:
            db.session.add(Transaction(
                item_id=item.id,
                trans_date=date.today(),
                trans_type="RECEIVE",
                qty_in=qty,
                unit=unit,
                user_id=user_id,
                reference_notes=f"Imported from {sheet_name}",
            ))
        added += 1

    return added, updated, skipped


# -----------------------------------------------------------------------------
# Public — import dispatcher
# -----------------------------------------------------------------------------
def import_workbook(file_storage, user_id):
    """
    Returns a summary dict:
      { 'shape': 'sop' | 'snapshot',
        'sheets': [ {name, added, updated, skipped}, ... ],
        'totals': { added, updated, skipped } }
    """
    filename = file_storage.filename.lower()

    summary = {
        "shape": None,
        "sheets": [],
        "totals": {"added": 0, "updated": 0, "skipped": 0},
    }

    if filename.endswith(".csv"):
        df = pd.read_csv(file_storage)
        shape = detect_shape(df)
        summary["shape"] = shape
        if shape == "sop":
            a, u, s = _import_sop_sheet(df, user_id)
        elif shape == "snapshot":
            a, u, s = _import_snapshot_sheet(df, user_id, "Imported")
        else:
            raise ValueError("Unrecognized file shape. Expected SOP or snapshot columns.")
        summary["sheets"].append({"name": file_storage.filename,
                                  "added": a, "updated": u, "skipped": s})
        summary["totals"] = {"added": a, "updated": u, "skipped": s}
        db.session.commit()
        return summary

    # Excel — read every sheet
    sheets = pd.read_excel(file_storage, sheet_name=None)

    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue

        # Skip known meta sheets
        if _norm(sheet_name) in ("instructions", "dashboard", "lists",
                                 "monthly count", "discrepancy capa",
                                 "disposal register"):
            continue

        shape = detect_shape(df)
        if summary["shape"] is None and shape != "unknown":
            summary["shape"] = shape

        if shape == "sop":
            a, u, s = _import_sop_sheet(df, user_id)
        elif shape == "snapshot":
            a, u, s = _import_snapshot_sheet(df, user_id, sheet_name)
        else:
            continue

        summary["sheets"].append({
            "name": sheet_name, "added": a, "updated": u, "skipped": s
        })
        summary["totals"]["added"] += a
        summary["totals"]["updated"] += u
        summary["totals"]["skipped"] += s

    db.session.commit()
    return summary


# -----------------------------------------------------------------------------
# Export — Native
# -----------------------------------------------------------------------------
def export_native():
    """Multi-sheet Excel: one sheet per category + Transactions."""
    buf = io.BytesIO()

    def rows_for(category):
        items = Item.query.filter_by(category=category, is_archived=False) \
                          .order_by(Item.name).all()
        out = []
        for i in items:
            out.append({
                "Inventory ID": i.inventory_id,
                "Item / Description": i.name,
                "Category": i.category,
                "Area": i.area.name if i.area else "",
                "Manufacturer / Supplier": i.manufacturer or "",
                "Lot / Serial": i.lot_serial or "",
                "Opening Qty": i.opening_qty,
                "Unit": i.unit,
                "Location": i.location or "",
                "Received / Acquired": i.received_date or "",
                "Expiry Date": i.expiry_date or "",
                "Min Level": i.min_level,
                "Reorder Level": i.reorder_level,
                "Critical?": "Yes" if i.critical else "No",
                "Condition / Status": i.condition_status or "",
                "Cal./Service Due": i.service_due or "",
                "Unit Value (USD)": i.unit_value,
                "Responsible Person": i.responsible or "",
                "Qty In (auto)": i.qty_in,
                "Qty Out (auto)": i.qty_out,
                "Current Qty (auto)": i.current_qty,
                "Stock Status (auto)": i.stock_status,
                "Days to Expiry": i.days_to_expiry if i.days_to_expiry is not None else "",
                "Expiry Status (auto)": i.expiry_status,
                "Service Status (auto)": i.service_status,
                "Current Value (auto)": i.current_value,
                "Notes": i.notes or "",
            })
        return out

    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for cat in CATEGORIES:
            rows = rows_for(cat)
            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["Inventory ID", "Item / Description", "Category"])
            sheet_name = cat[:31]
            df.to_excel(w, sheet_name=sheet_name, index=False)

        # Transactions
        txs = Transaction.query.order_by(Transaction.entry_date.desc()).all()
        tx_rows = [{
            "Transaction Date": t.trans_date,
            "Transaction Ref.": t.trans_ref or "",
            "Inventory ID": t.item.inventory_id,
            "Item / Description": t.item.name,
            "Lot / Serial": t.item.lot_serial or "",
            "Transaction Type": t.trans_type,
            "Qty In": t.qty_in or "",
            "Qty Out": t.qty_out or "",
            "Unit": t.unit or "",
            "From Location": t.from_location or "",
            "To Location": t.to_location or "",
            "User": t.user.username if t.user else "",
            "Reference / Notes": t.reference_notes or "",
            "Entry Date": t.entry_date,
        } for t in txs]
        tx_df = pd.DataFrame(tx_rows) if tx_rows else pd.DataFrame(
            columns=["Transaction Date", "Inventory ID", "Transaction Type"])
        tx_df.to_excel(w, sheet_name="Transactions", index=False)

    buf.seek(0)
    return buf


# -----------------------------------------------------------------------------
# Export — SOP-compatible
# -----------------------------------------------------------------------------
SOP_MASTER_HEADERS = [
    "Inventory ID", "Item / Description", "Category", "Manufacturer / Supplier",
    "Lot / Serial", "Opening Qty", "Unit", "Location", "Received / Acquired",
    "Expiry Date", "Min Level", "Reorder Level", "Critical?", "Condition / Status",
    "Cal./Service Due", "Unit Value (USD)", "Responsible Person",
    "Qty In (auto)", "Qty Out (auto)", "Current Qty (auto)", "Stock Status (auto)",
    "Days to Expiry", "Expiry Status (auto)", "Service Status (auto)",
    "Current Value (auto)", "Last Updated",
]

SOP_STOCK_HEADERS = [
    "Transaction Date", "Transaction Ref.", "Inventory ID", "Item / Description",
    "Lot / Serial", "Transaction Type", "Qty In", "Qty Out", "Unit",
    "From Location", "To Location", "User", "Reference / Notes", "Entry Date",
]


def export_sop():
    """Single-sheet Excel matching the SOP Master Inventory layout + Stock Movements."""
    buf = io.BytesIO()

    master_rows = []
    items = Item.query.filter_by(is_archived=False).order_by(
        Item.category, Item.name).all()
    for i in items:
        master_rows.append({
            "Inventory ID": i.inventory_id,
            "Item / Description": i.name,
            "Category": i.category,
            "Manufacturer / Supplier": i.manufacturer or "",
            "Lot / Serial": i.lot_serial or "",
            "Opening Qty": i.opening_qty,
            "Unit": i.unit,
            "Location": i.location or "",
            "Received / Acquired": i.received_date or "",
            "Expiry Date": i.expiry_date or "",
            "Min Level": i.min_level,
            "Reorder Level": i.reorder_level,
            "Critical?": "Yes" if i.critical else "No",
            "Condition / Status": i.condition_status or "",
            "Cal./Service Due": i.service_due or "",
            "Unit Value (USD)": i.unit_value,
            "Responsible Person": i.responsible or "",
            "Qty In (auto)": i.qty_in,
            "Qty Out (auto)": i.qty_out,
            "Current Qty (auto)": i.current_qty,
            "Stock Status (auto)": i.stock_status,
            "Days to Expiry": i.days_to_expiry if i.days_to_expiry is not None else "",
            "Expiry Status (auto)": i.expiry_status,
            "Service Status (auto)": i.service_status,
            "Current Value (auto)": i.current_value,
            "Last Updated": i.updated_at.strftime("%Y-%m-%d %H:%M") if i.updated_at else "",
        })

    master_df = pd.DataFrame(master_rows, columns=SOP_MASTER_HEADERS)

    tx_rows = []
    for t in Transaction.query.order_by(Transaction.entry_date.desc()).all():
        tx_rows.append({
            "Transaction Date": t.trans_date,
            "Transaction Ref.": t.trans_ref or "",
            "Inventory ID": t.item.inventory_id,
            "Item / Description": t.item.name,
            "Lot / Serial": t.item.lot_serial or "",
            "Transaction Type": t.trans_type,
            "Qty In": t.qty_in or "",
            "Qty Out": t.qty_out or "",
            "Unit": t.unit or "",
            "From Location": t.from_location or "",
            "To Location": t.to_location or "",
            "User": t.user.username if t.user else "",
            "Reference / Notes": t.reference_notes or "",
            "Entry Date": t.entry_date.strftime("%Y-%m-%d %H:%M") if t.entry_date else "",
        })
    tx_df = pd.DataFrame(tx_rows, columns=SOP_STOCK_HEADERS)

    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        master_df.to_excel(w, sheet_name="Master Inventory", index=False)
        tx_df.to_excel(w, sheet_name="Stock Movements", index=False)

    buf.seek(0)
    return buf