from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_smtp() -> smtplib.SMTP:
    load_env_file()
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()

    if not host or not user or not password:
        raise RuntimeError("SMTP configuration is incomplete.")
    if not password.isascii() or "입력" in password or "password" in password.lower():
        raise RuntimeError("SMTP_PASSWORD is still a placeholder. Replace it with a real app password.")

    smtp = smtplib.SMTP(host, port, timeout=20)
    smtp.ehlo()
    smtp.starttls()
    smtp.login(user, password)
    return smtp


def send_email_message(
    *,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    to_email: str,
    attachment_paths: list[Path] | None = None,
) -> None:
    load_env_file()
    from_email = os.environ.get("SMTP_USER", "").strip()
    if not from_email:
        raise RuntimeError("SMTP_USER is not configured.")

    message = MIMEMultipart("mixed")
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        alternative.attach(MIMEText(body_html, "html", "utf-8"))
    message.attach(alternative)

    for attachment_path in attachment_paths or []:
        if not attachment_path.exists() or not attachment_path.is_file():
            continue
        attachment = MIMEApplication(attachment_path.read_bytes(), Name=attachment_path.name)
        attachment["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
        message.attach(attachment)

    smtp = build_smtp()
    try:
        smtp.sendmail(from_email, [to_email], message.as_string())
    finally:
        smtp.quit()


def send_slack_message(text: str, blocks: list | None = None) -> None:
    load_env_file()
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


def send_alert_email(
    *,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    to_email: str,
) -> None:
    send_email_message(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        to_email=to_email,
    )
