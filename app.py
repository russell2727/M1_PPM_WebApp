"""
M1 Data & Analytics — In-Market Auto Shoppers dashboard.

Run locally:   python app.py
On Render:     gunicorn app:app   (see render.yaml)
"""
from __future__ import annotations

import csv
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, abort, jsonify, render_template, request,
                   send_from_directory)

load_dotenv()

import config  # noqa: E402
from services import data, mailer, pdf  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = config.SECRET_KEY
app.json.sort_keys = False  # keep vehicle-type and distance-ring ordering
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

# Warm the cache so the first visitor doesn't wait on the geocoder.
try:
    data.load_shoppers()
except Exception:  # noqa: BLE001
    log.exception("Could not load shopper data at startup — check config.COLUMNS and the data/ folder")


# --------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template(
        "index.html",
        brand=config.BRAND,
        radius_options=config.RADIUS_OPTIONS,
        vehicle_types=data.available_vehicle_types(),
        email_enabled=config.EMAIL_ENABLED,
    )


@app.post("/api/report")
def api_report():
    f = request.get_json(silent=True) or request.form
    prospect = {
        "name":       (f.get("name") or "").strip(),
        "email":      (f.get("email") or "").strip().lower(),
        "dealership": (f.get("dealership") or "").strip(),
        "zip":        (f.get("zip") or "").strip(),
    }
    conditions = f.getlist("condition") if hasattr(f, "getlist") else (f.get("condition") or [])
    if isinstance(conditions, str):
        conditions = [conditions]
    vehicle_types = f.getlist("vehicle_type") if hasattr(f, "getlist") else (f.get("vehicle_type") or [])
    if isinstance(vehicle_types, str):
        vehicle_types = [vehicle_types]
    try:
        radius = float(f.get("radius") or 25)
    except ValueError:
        radius = 25.0

    errors = {}
    if len(prospect["name"]) < 2:
        errors["name"] = "Enter your name."
    if not EMAIL_RE.match(prospect["email"]):
        errors["email"] = "Enter a valid email address."
    if len(prospect["dealership"]) < 2:
        errors["dealership"] = "Enter the dealership name."
    if not ZIP_RE.match(prospect["zip"]):
        errors["zip"] = "Enter a valid 5-digit ZIP."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    try:
        result = data.query(prospect["zip"], radius, conditions, vehicle_types or None)
    except ValueError as e:
        return jsonify({"ok": False, "errors": {"zip": str(e)}}), 400

    # ---- PDF
    report_id = uuid.uuid4().hex[:12]
    safe_dealer = re.sub(r"[^A-Za-z0-9]+", "_", prospect["dealership"]).strip("_")[:40]
    pdf_name = f"M1_InMarket_Report_{safe_dealer}_{report_id}.pdf"
    pdf_path = pdf.build_pdf(result, prospect, config.OUTPUT_DIR / pdf_name)

    # ---- email + lead capture
    emailed = mailer.send_report(prospect["email"], prospect, result, pdf_path)
    _record_lead(prospect, radius, conditions, result, pdf_name, emailed)

    payload = {k: v for k, v in result.items() if k != "center"}
    payload["center"] = result["center"]
    return jsonify({
        "ok": True,
        "result": payload,
        "pdf_url": f"/reports/{pdf_name}",
        "emailed": emailed,
    })


@app.get("/reports/<path:filename>")
def report_file(filename):
    if not re.match(r"^M1_InMarket_Report_[A-Za-z0-9_]+\.pdf$", filename):
        abort(404)
    return send_from_directory(config.OUTPUT_DIR, filename, as_attachment=False)


@app.get("/healthz")
def healthz():
    df = data.load_shoppers()
    return jsonify({"ok": True, "rows": int(len(df)), "zips": int(df["zip"].nunique()), "email": config.EMAIL_ENABLED})


# --------------------------------------------------------------------------
def _record_lead(prospect, radius, conditions, result, pdf_name, emailed):
    """Append every submission to leads.csv (persistent only if OUTPUT_DIR is on a Render disk)."""
    new = not config.LEADS_FILE.exists()
    with open(config.LEADS_FILE, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["timestamp", "name", "email", "dealership", "zip", "radius_mi", "conditions",
                        "total_shoppers", "pdf", "emailed"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), prospect["name"], prospect["email"],
                    prospect["dealership"], prospect["zip"], radius, "|".join(conditions),
                    result["total_shoppers"], pdf_name, emailed])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
