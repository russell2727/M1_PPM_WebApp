"""
Lead notifications, fired in a background thread after every report:

  * HubSpot  — create-or-update the contact by email, stamp PPM report fields,
               and log a Note on the contact timeline (private-app token)
  * Email    — internal "new lead" message to NOTIFY_EMAILS with the PDF attached
  * Push     — Pushover and/or Slack incoming webhook

Every channel is independent; a failure in one never blocks the others, and a
channel with no credentials is simply skipped.
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import config

log = logging.getLogger(__name__)

HS = "https://api.hubapi.com"

# Custom contact properties this app writes (created on first run if missing)
HS_PROPERTIES = [
    ("ppm_dealership",      "PPM Dealership",            "string",  "text"),
    ("ppm_dealer_zip",      "PPM Dealer ZIP",            "string",  "text"),
    ("ppm_radius_mi",       "PPM Radius (mi)",           "number",  "number"),
    ("ppm_conditions",      "PPM Inventory",             "string",  "text"),
    ("ppm_total_shoppers",  "PPM In-Market Shoppers",    "number",  "number"),
    ("ppm_top_segment",     "PPM Top Vehicle Type",      "string",  "text"),
    ("ppm_report_url",      "PPM Report URL",            "string",  "text"),
    ("ppm_last_report_at",  "PPM Last Report",           "datetime", "date"),
]
_hs_props_ready = False


# --------------------------------------------------------------------------
def _summary(prospect: dict, result: dict, report_url: str) -> dict:
    c = result["center"]
    top = next(iter(result["by_type"]), "—")
    bc = result["by_condition"]
    return {
        "name": prospect["name"], "email": prospect["email"], "dealership": prospect["dealership"],
        "location": f"{c['city']}, {c['state']} {c['zip']}", "zip": c["zip"],
        "radius": int(result["radius_mi"]),
        "conditions": " & ".join(result["conditions"]) if result["conditions"] else "New & Used",
        "total": result["total_shoppers"], "new": bc.get("New", 0), "used": bc.get("Used", 0),
        "top": f"{top} ({result['by_type'].get(top, 0):,})" if top != "—" else "—",
        "zips": result["zip_count"],
        "url": f"{config.PUBLIC_URL}{report_url}" if config.PUBLIC_URL else report_url,
    }


def notify_all(prospect: dict, result: dict, report_url: str, pdf_path: Path, emailed: bool) -> None:
    s = _summary(prospect, result, report_url)
    s["prospect_emailed"] = emailed
    for fn in (hubspot, internal_email, pushover, slack):
        try:
            fn(s, pdf_path)
        except Exception:  # noqa: BLE001
            log.exception("notification channel %s failed", fn.__name__)


# --------------------------------------------------------------------------
# HubSpot
# --------------------------------------------------------------------------
def _hs(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        HS + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {config.HUBSPOT_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")
        if e.code == 409 and "existing" in payload.lower():
            return {"conflict": payload}
        raise RuntimeError(f"HubSpot {method} {path} -> {e.code}: {payload[:300]}") from None


def _ensure_hs_properties() -> None:
    global _hs_props_ready
    if _hs_props_ready:
        return
    existing = {p["name"] for p in _hs("GET", "/crm/v3/properties/contacts").get("results", [])}
    for name, label, ptype, field in HS_PROPERTIES:
        if name not in existing:
            _hs("POST", "/crm/v3/properties/contacts", {
                "name": name, "label": label, "type": ptype, "fieldType": field,
                "groupName": "contactinformation", "description": "Set by the M1 PPM In-Market Auto Shoppers web app",
            })
            log.info("HubSpot: created contact property %s", name)
    _hs_props_ready = True


def hubspot(s: dict, pdf_path: Path) -> None:
    if not config.HUBSPOT_TOKEN:
        return
    _ensure_hs_properties()
    first, _, last = s["name"].partition(" ")
    props = {
        "email": s["email"], "firstname": first, "lastname": last or "",
        "company": s["dealership"], "zip": s["zip"],
        "ppm_dealership": s["dealership"], "ppm_dealer_zip": s["zip"], "ppm_radius_mi": s["radius"],
        "ppm_conditions": s["conditions"], "ppm_total_shoppers": s["total"], "ppm_top_segment": s["top"],
        "ppm_report_url": s["url"],
        "ppm_last_report_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    if config.HUBSPOT_OWNER_ID:
        props["hubspot_owner_id"] = config.HUBSPOT_OWNER_ID

    # create, or update on conflict (HubSpot returns the existing id in the 409 message)
    r = _hs("POST", "/crm/v3/objects/contacts", {"properties": props})
    if "conflict" in r:
        existing_id = r["conflict"].rstrip(".").split("ID: ")[-1].strip().split('"')[0]
        if not existing_id.isdigit():
            q = _hs("POST", "/crm/v3/objects/contacts/search",
                    {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": s["email"]}]}], "limit": 1})
            existing_id = str(q["results"][0]["id"])
        props.pop("email", None)
        _hs("PATCH", f"/crm/v3/objects/contacts/{existing_id}", {"properties": props})
        contact_id = existing_id
    else:
        contact_id = str(r["id"])

    note = (f"PPM In-Market Auto Shopper report requested\n"
            f"Dealership: {s['dealership']} ({s['location']})\n"
            f"Radius: {s['radius']} mi · {s['conditions']}\n"
            f"In-market shoppers: {s['total']:,} (New {s['new']:,} / Used {s['used']:,}) across {s['zips']} ZIPs\n"
            f"Top vehicle type: {s['top']}\n"
            f"Report: {s['url']}")
    _hs("POST", "/crm/v3/objects/notes", {
        "properties": {"hs_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "hs_note_body": note},
        "associations": [{"to": {"id": contact_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}],
    })
    log.info("HubSpot: contact %s updated + note logged", contact_id)


# --------------------------------------------------------------------------
# Internal email
# --------------------------------------------------------------------------
def internal_email(s: dict, pdf_path: Path) -> None:
    if not (config.EMAIL_ENABLED and config.NOTIFY_EMAILS):
        return
    msg = EmailMessage()
    msg["Subject"] = f"New PPM lead: {s['dealership']} — {s['total']:,} shoppers / {s['radius']} mi"
    msg["From"] = config.MAIL_FROM
    msg["To"] = ", ".join(config.NOTIFY_EMAILS)
    msg.set_content(
        f"New in-market auto shopper report requested.\n\n"
        f"Name:        {s['name']}\nEmail:       {s['email']}\nDealership:  {s['dealership']}\n"
        f"Location:    {s['location']}\nRadius:      {s['radius']} mi · {s['conditions']}\n\n"
        f"Shoppers:    {s['total']:,}  (New {s['new']:,} / Used {s['used']:,})\n"
        f"ZIPs:        {s['zips']}\nTop type:    {s['top']}\n\n"
        f"Report:      {s['url']}\nProspect emailed: {'yes' if s['prospect_emailed'] else 'no (SMTP off)'}\n"
    )
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        smtp.starttls(); smtp.login(config.SMTP_USER, config.SMTP_PASSWORD); smtp.send_message(msg)
    log.info("Internal lead email sent to %s", config.NOTIFY_EMAILS)


# --------------------------------------------------------------------------
# Push
# --------------------------------------------------------------------------
def _push_text(s: dict) -> str:
    return (f"{s['name']} · {s['dealership']}\n{s['location']} · {s['radius']} mi · {s['conditions']}\n"
            f"{s['total']:,} in-market shoppers · top: {s['top']}\n{s['email']}")


def pushover(s: dict, _pdf: Path) -> None:
    if not (config.PUSHOVER_USER and config.PUSHOVER_TOKEN):
        return
    data = urllib.parse.urlencode({
        "token": config.PUSHOVER_TOKEN, "user": config.PUSHOVER_USER,
        "title": f"New PPM lead: {s['dealership']}", "message": _push_text(s),
        "url": s["url"], "url_title": "Open report", "priority": 0,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request("https://api.pushover.net/1/messages.json", data=data), timeout=10):
        pass
    log.info("Pushover sent")


def slack(s: dict, _pdf: Path) -> None:
    if not config.SLACK_WEBHOOK:
        return
    body = {"text": f"*New PPM lead — {s['dealership']}*",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"New PPM lead: {s['dealership']}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Contact*\n{s['name']}\n{s['email']}"},
                    {"type": "mrkdwn", "text": f"*Location*\n{s['location']}\n{s['radius']} mi · {s['conditions']}"},
                    {"type": "mrkdwn", "text": f"*In-market shoppers*\n{s['total']:,}  (New {s['new']:,} / Used {s['used']:,})"},
                    {"type": "mrkdwn", "text": f"*Top vehicle type*\n{s['top']}"},
                ]},
                {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open PDF report"}, "url": s["url"]}]},
            ]}
    req = urllib.request.Request(config.SLACK_WEBHOOK, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10):
        pass
    log.info("Slack sent")
