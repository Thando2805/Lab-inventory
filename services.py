"""
Import / Export services for the Lab Inventory app.

Two export formats:
  - Native: one sheet per category + a Transactions sheet
  - SOP:    mirror of the controlled workbook (Master Inventory + Stock Movements)

Two import shapes, auto-detected:
  - SOP shape: has Inventory ID + Opening Qty + Min Level
  - Snapshot shape: has Item Description (or Item) + Quantity (or Qty)
"""

import io
from datetime import datetime, date
import pandas as pd

from models import (db, Item, Transaction, Area, CATEGORIES)


# -----------------------------------------------------------------------------
# Category mapping for snapshot imports
# -----------------------------------------------------------------------------
CATEGORY_MAP = {
    "glassware": "Apparatus",
    "pipettes": "Apparatus",
    "pipette": "Apparatus",
    "accessories": "Apparatus",
    "equipment": "Equipment",
    "microbiology equipment": "Equipment",
    "chemical": "Chemical",
    "chemicals": "Chemical",
    "reagent": "Reagent",
    "reagents": "Reagent",
    "media": "Reagent",
    "stain": "Reagent",
    "stains": "Reagent",
    "consumable": "Consumable",
    "consumables": "Consumable",
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
    if not s or s in ("—", "―", "-", "N/A", "NA", "n/a"):
        return None
    return s


def _num(v, default=0.0):
    try:
        if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
            return default
        s = str(v).strip()
        if s in ("—", "―", "-", "N/A", "NA"):
            return default
        return float(s)
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
    return str(c or "").strip().lower()


# -----------------------------------------------------------------------------
# Header detection — finds the row that actually contains column names
# -----------------------------------------------------------------------------
def _find_header_row(raw_df, max_scan=8):
    """
    Scan the first `max_scan` rows of a header-less dataframe and return the
    index of the row that looks like the real header (contains 'item' and
    'quantity' or 'qty'). Return None if nothing looks right.
    """
    for i in range(min(max_scan, len(raw_df))):
        row_vals = [_norm(v) for v in raw_df.iloc[i].tolist() if pd.notna(v)]
        joined = " | ".join(row_vals)
        has_item = any(k in joined for k in
                       ["item description", "item number", "itemnumber",
                        "item", "description"])
        has_qty = any(k in joined for k in ["quantity", "qty"])
        if has_item and has_qty:
            return i
    return None


def _prepare_sheet(df):
    """
    Given a raw dataframe (with pd.read_excel(..., header=None)), detect the
    header row and return a normalized dataframe with clean column names.
    Returns None if the sheet isn't recognizable.
    """
    hdr = _find_header_row(df)
    if hdr is None:
        return None

    df = df.iloc[hdr + 1:].reset_index(drop=True)
    df.columns = [_norm(c) for c in df.iloc[0].tolist()] if False else \
                 [_norm(c) for c in
                  pd.read_excel if False else
                  [str(x) for x in df.columns]]
    # Rebuild with the header row values as column names
    df.columns = [_norm(c) for c in df.columns]

    # Because we sliced after reading without a header, we lost the column
    # names. So re-read isn't possible here — instead, take the header row
    # values from the original slice.
    return df


# The two helpers above are messy. Replace _prepare_sheet with a simpler version
# that receives the full sheet read with header=None and the detected row index.
def _extract_table(df_raw):
    """
    df_raw was loaded with pd.read_excel(file, sheet_name=None, header=None).
    Detect the header row, cut, and return a DataFrame with proper columns.
    """
    if df_raw is None or df_raw.empty:
        return None

    hdr = _find_header_row(df_raw)
    if hdr is None:
        return None

    header_vals = [_norm(v) if pd.notna(v) else "" for v in df_raw.iloc[hdr].tolist()]

    body = df_raw.iloc[hdr + 1:].reset_index(drop=True)
    body.columns = header_vals
    body = body.dropna(how="all")
    return body


# -----------------------------------------------------------------------------
# Shape detection
# -----------------------------------------------------------------------------
def detect_shape(df):
    cols = [_norm(c) for c in df.columns]
    joined = " | ".join(cols)
    has_sop = ("inventory id" in joined
               and "opening qty" in joined
               and "min level" in joined)
    if has_sop:
        return "sop"

    has_name = any(k in cols for k in
                   ["item description", "item", "itemnumber",
                    "item number", "description"])
    has_qty = any(k in cols for k in ["quantity", "qty"])
    if has_name and has_qty:
        return "snapshot"

    return "unknown"


# -----------------------------------------------------------------------------
# Row helpers — column lookups with synonyms
# -----------------------------------------------------------------------------
def _get(row, *keys, default=None):
    for k in keys:
        if k in row and row[k] is not None:
            v = row[k]
            if not (isinstance(v, float) and pd.isna(v)):
                return v
    return default


def _row_name(row):
    return _clean(_get(row,
                       "item description",
                       "item",
                       "itemnumber",
                       "item number",
                       "description",
                       "name"))


def _row_qty(row):
    return _num(_get(row, "quantity", "qty", default=0))


def _row_unit(row, default="pcs"):
    u = _clean(_get(row, "units", "unit"))
    return u or default


def _row_category(row):
    return _clean(_get(row, "category", "catergory", "cat"))


# -----------------------------------------------------------------------------
# Import — SOP shape
# -----------------------------------------------------------------------------
def _import_sop_sheet(df, user_id):
    cols = {}
    for c in df.columns:
        cols[_norm(c)] = c

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_inv = col("inventory id")
    c_name = col("item / description", "item description", "item")
    c_cat = col("category")
    c_opening = col("opening qty", "opening_qty")
    c_unit = col("unit")
    c_min = col("min level", "min_level")
    c_reorder = col("reorder level", "reorder_level")
    c_crit = col("critical?")
    c_loc = col("location")
    c_mfr = col("manufacturer / supplier", "manufacturer")
    c_lot = col("lot / serial", "lot_serial")
    c_recv = col("received / acquired", "received_date")
    c_exp = col("expiry date", "expiry_date")
    c_svc = col("cal./service due", "service_due")
    c_val = col("unit value (usd)", "unit_value")
    c_resp = col("responsible person", "responsible")
    c_cond = col("condition / status", "condition_status")

    added, updated, skipped = 0, 0, 0

    for _, row in df.iterrows():
        inv_id = _clean(row.get(c_inv)) if c_inv else None
        name = _clean(row.get(c_name)) if c_name else None
        if not (inv_id or name):
            skipped += 1
            continue
        n_up = (name or "").upper()
        if n_up.startswith("TOTAL"):
            skipped += 1
            continue

        category = _clean(row.get(c_cat)) if c_cat else "Apparatus"
        if category not in CATEGORIES:
            category = "Apparatus"

        existing = None
        if inv_id:
            existing = Item.query.filter_by(inventory_id=inv_id).first()
        elif name:
            existing = Item.query.filter_by(name=name, category=category).first()

        opening = _num(row.get(c_opening)) if c_opening else 0.0
        unit = (_clean(row.get(c_unit)) if c_unit else None) or "each"
        min_lvl = _num(row.get(c_min)) if c_min else 0.0
        reorder = _num(row.get(c_reorder)) if c_reorder else 0.0
        crit_raw = _clean(row.get(c_crit)) if c_crit else None
        critical = (crit_raw or "").lower() in ("yes", "true", "1", "y")
        location = _clean(row.get(c_loc)) if c_loc else None
        manufacturer = _clean(row.get(c_mfr)) if c_mfr else None
        lot = _clean(row.get(c_lot)) if c_lot else None
        received = _date(row.get(c_recv)) if c_recv else None
        expiry = _date(row.get(c_exp)) if c_exp else None
        service_due = _date(row.get(c_svc)) if c_svc else None
        unit_value = _num(row.get(c_val)) if c_val else 0.0
        responsible = _clean(row.get(c_resp)) if c_resp else None
        condition = (_clean(row.get(c_cond)) if c_cond else None) or "Active"

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
# Import — Snapshot shape (per-sheet area, category mapping)
# -----------------------------------------------------------------------------
def _import_snapshot_sheet(df, user_id, sheet_name):
    area_name = (sheet_name or "Imported").strip()
    area = Area.query.filter_by(name=area_name).first()
    if not area:
        area = Area(name=area_name,
                    sort_order=(Area.query.count() or 0) + 1)
        db.session.add(area)
        db.session.flush()

    added, updated, skipped = 0, 0, 0

    for _, row in df.iterrows():
        name = _row_name(row)
        if not name:
            skipped += 1
            continue

        n_up = name.upper()
        if n_up.startswith("TOTAL") or n_up == "TOTAL ITEMS":
            skipped += 1
            continue

        raw_cat = _row_category(row) or ""
        mapped_cat = CATEGORY_MAP.get(_norm(raw_cat), "Consumable")

        qty = _row_qty(row)
        unit = _row_unit(row, default="pcs")

        # Capacity gets appended if present (Biochemical sheet)
        cap = _clean(_get(row, "capacity"))
        full_name = f"{name} {cap}".strip() if cap else name

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
SKIP_SHEETS = {
    "instructions", "dashboard", "lists",
    "monthly count", "discrepancy capa", "disposal register",
}


def import_workbook(file_storage, user_id):
    filename = file_storage.filename.lower()

    summary = {
        "shape": None,
        "sheets": [],
        "totals": {"added": 0, "updated": 0, "skipped": 0},
    }

    # ---- CSV path -----------------------------------------------------------
    if filename.endswith(".csv"):
        df = pd.read_csv(file_storage)
        shape = detect_shape(df)
        summary["shape"] = shape or "unknown"
        if shape == "sop":
            a, u, s = _import_sop_sheet(df, user_id)
        elif shape == "snapshot":
            a, u, s = _import_snapshot_sheet(df, user_id, "Imported")
        else:
            raise ValueError("Unrecognized CSV columns.")
        summary["sheets"].append({"name": file_storage.filename,
                                  "added": a, "updated": u, "skipped": s})
        summary["totals"] = {"added": a, "updated": u, "skipped": s}
        db.session.commit()
        return summary

    # ---- Excel path — read every sheet with no header ----------------------
    raw_sheets = pd.read_excel(file_storage, sheet_name=None, header=None)

    for sheet_name, df_raw in raw_sheets.items():
        if df_raw is None or df_raw.empty:
            continue
        if _norm(sheet_name) in SKIP_SHEETS:
            continue

        table = _extract_table(df_raw)
        if table is None or table.empty:
            continue

        shape = detect_shape(table)
        if summary["shape"] is None and shape != "unknown":
            summary["shape"] = shape

        if shape == "sop":
            a, u, s = _import_sop_sheet(table, user_id)
        elif shape == "snapshot":
            a, u, s = _import_snapshot_sheet(table, user_id, sheet_name)
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
            df.to_excel(w, sheet_name=cat[:31], index=False)

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