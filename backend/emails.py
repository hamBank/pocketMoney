"""SMTP sending. With SMTP_HOST unset (local dev), emails are printed to
stdout instead so cron scripts and tests behave identically."""

import smtplib
from email.message import EmailMessage

from .config import settings


def send_email(to: list[str], subject: str, body: str) -> None:
    if not settings.smtp_host:
        print(f"[email disabled] To: {', '.join(to)}\nSubject: {subject}\n\n{body}")
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
