"""Sends mail via the Gmail SMTP relay (smtp.gmail.com:587 + STARTTLS),
authenticated with a Gmail App Password — see DEPLOYMENT.md for setup.
Works the same for a plain Gmail account or Google Workspace.

With SMTP_USER unset (local dev / tests), emails are printed to stdout
instead of sent, so nothing needs real credentials to run."""

import smtplib
from email.message import EmailMessage

from .config import settings


def send_email(to: list[str], subject: str, body: str) -> None:
    if not settings.smtp_user:
        print(f"[email disabled] To: {', '.join(to)}\nSubject: {subject}\n\n{body}")
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
