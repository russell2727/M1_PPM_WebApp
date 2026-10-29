"""
Sends the PDF to the prospect over SMTP (SendGrid, Postmark, Google Workspace,
Office 365 — any SMTP relay). Configured entirely by environment variables.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import config

log = logging.getLogger(__name__)


def send_report(to_email: str, prospect: dict, result: dict, pdf_path: Path) -> bool:
    if not config.EMAIL_ENABLED:
        log.info("Email disabled (SMTP env vars not set); skipping send to %s", to_email)
        return False

    c = result["center"]
    msg = EmailMessage()
    msg["Subject"] = f"Your In-Market Auto Shopper Report — {prospect['dealership']} ({int(result['radius_mi'])}-mile radius)"
    msg["From"] = config.MAIL_FROM
    msg["To"] = to_email
    if config.MAIL_BCC:
        msg["Bcc"] = config.MAIL_BCC

    msg.set_content(
        f"Hi {prospect['name'].split()[0]},\n\n"
        f"Attached is your In-Market Auto Shopper Report for {prospect['dealership']} "
        f"({c['city']}, {c['state']} {c['zip']}, {int(result['radius_mi'])}-mile radius).\n\n"
        f"Total in-market shoppers: {result['total_shoppers']:,}\n\n"
        f"Reply to this email to activate this audience across email, SMS, direct mail and programmatic channels.\n\n"
        f"{config.BRAND['company']}\n{config.BRAND['website']}\n"
    )
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        log.info("Report emailed to %s", to_email)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Failed to email report to %s", to_email)
        return False
