"""
Central configuration for the M1 Data In-Market Auto Shoppers dashboard.

Everything a non-developer may need to change lives here:
  - where the data files are
  - what the columns in YOUR data file are called
  - brand colors
  - email settings (read from environment variables on Render)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# DATA FILES
# --------------------------------------------------------------------------
# The data directory is resolved in this order:
#   1. DATA_DIR environment variable (use this on Render if you attach a
#      persistent disk, e.g. DATA_DIR=/var/data)
#   2. ./data inside the repo (the default — commit your CSVs there)
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))

SHOPPERS_FILE = DATA_DIR / os.getenv("SHOPPERS_FILE", "in_market_auto_shoppers.csv.gz")
VEHICLE_TYPE_LOOKUP_FILE = DATA_DIR / os.getenv("VEHICLE_TYPE_LOOKUP_FILE", "vehicle_type_lookup.csv")

# --------------------------------------------------------------------------
# COLUMN MAP  ->  rename the right-hand side to match YOUR file's headers.
# The app only ever uses the left-hand (canonical) names internally.
# --------------------------------------------------------------------------
COLUMNS = {
    "zip":          "zip",            # 5-digit ZIP of the shopper (source: "Zip Code")
    "state":        "state",          # optional — not in the PPM export; derived from ZIP
    "msa":          "msa",            # optional — MSA Name
    "condition":    "condition",      # "New" or "Used"           (source: "PPM Type")
    "vehicle_key":  "segment",        # joins to the vehicle-type lookup (source: "PPM Segment")
    "shoppers":     "shopper_count",  # in-market shoppers in that row (source: "Total")
}

# Vehicle-type lookup: maps the raw value in COLUMNS["vehicle_key"] to a clean
# category (Sedan, Truck, SUV, ...). Two columns expected:
LOOKUP_COLUMNS = {
    "key":   "segment",        # must contain the same values as COLUMNS["vehicle_key"]
    "type":  "vehicle_type",   # e.g. Sedan / Truck / SUV / Van / Coupe / ...
}

# Radius options shown on the form (miles)
RADIUS_OPTIONS = [10, 25, 50, 75, 100, 150]

# --------------------------------------------------------------------------
# BRAND
# --------------------------------------------------------------------------
BRAND = {
    "company":   "M1 Data & Analytics",
    "tagline":   "In-Market Auto Shopper Intelligence",
    "website":   "m1-data.com",
    "logo_path": BASE_DIR / "static" / "img" / "m1-logo.png",  # drop your PNG here
    # Palette sampled from the M1 Data logo (indigo-blue gradient + black wordmark)
    "navy":      "#0F1424",   # near-black, matches the wordmark
    "blue":      "#4A5BAE",   # logo indigo-blue (primary)
    "teal":      "#6B7DD4",   # lighter logo blue (secondary / "Used")
    "orange":    "#F5A623",   # accent
    "gray":      "#6B7280",
    "light":     "#F4F5FA",
    "chart":     ["#4A5BAE", "#A7B3E8", "#F5A623", "#0F1424", "#8B5CF6", "#0EA5E9", "#84CC16"],
}

# --------------------------------------------------------------------------
# EMAIL (set as Render environment variables; leave blank to disable)
# --------------------------------------------------------------------------
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM     = os.getenv("MAIL_FROM", "reports@m1-data.com")
MAIL_BCC      = os.getenv("MAIL_BCC", "")   # e.g. sales@m1-data.com to get a copy of every lead
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

# Where generated PDFs and lead records are written (ephemeral on Render
# unless DATA_DIR points at a persistent disk)
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", DATA_DIR / "output"))
LEADS_FILE = OUTPUT_DIR / "leads.csv"

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-render-env")
