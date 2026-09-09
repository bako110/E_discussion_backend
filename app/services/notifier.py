"""Envoi de SMS (Twilio) et d'e-mails (SMTP) — degrade en mode 'console' si
les credentials ne sont pas configures (dev local).

En mode console, le code OTP est extrait du corps du message et affiche dans
un encadre bien visible dans les logs, pour le copier facilement en dev.
"""
from __future__ import annotations

import re
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_CODE_RE = re.compile(r"\b(\d{4,8})\b")


def _print_dev_code(channel: str, to: str, body: str) -> None:
    m = _CODE_RE.search(body)
    code = m.group(1) if m else "??????"
    banner = (
        "\n"
        "  ┌─────────────────────────────────────────────┐\n"
        f"  │  CODE {channel.upper():<4}  ->  {code:<10}                 │\n"
        f"  │  destinataire : {to:<28}│\n"
        "  │  (mode dev : aucun SMS/e-mail reellement envoye)  \n"
        "  └─────────────────────────────────────────────┘\n"
    )
    print(banner, flush=True)  # noqa: T201 — intentionnel en dev
    log.info("otp.dev_code", channel=channel, to=to, code=code)


async def send_sms(to_e164: str, body: str) -> None:
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER):
        _print_dev_code("sms", to_e164, body)
        return
    from twilio.rest import Client  # type: ignore

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(to=to_e164, from_=settings.TWILIO_FROM_NUMBER, body=body)
    log.info("sms.sent", to=to_e164)


async def send_email(to: str, subject: str, body: str) -> None:
    if not (settings.SMTP_HOST and settings.SMTP_USER):
        _print_dev_code("mail", to, body)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to], msg.as_string())
    log.info("email.sent", to=to)
