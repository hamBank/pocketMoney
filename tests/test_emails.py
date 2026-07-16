from unittest.mock import MagicMock, patch

from backend.config import settings
from backend.emails import send_email


def test_defaults_to_gmail_smtp():
    assert settings.smtp_host == "smtp.gmail.com"
    assert settings.smtp_port == 587


def test_unconfigured_logs_to_stdout_and_sends_nothing(monkeypatch, capsys):
    monkeypatch.setattr(settings, "smtp_user", "")
    with patch("smtplib.SMTP") as smtp_cls:
        send_email(["parent@example.com"], "Subject line", "Body text")
    smtp_cls.assert_not_called()
    out = capsys.readouterr().out
    assert "[email disabled]" in out
    assert "parent@example.com" in out
    assert "Subject line" in out
    assert "Body text" in out


def test_configured_sends_via_gmail_relay(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "family@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "smtp_from", "")
    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    with patch("smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
        send_email(["kid@example.com"], "Digest", "Pending claims: 2")

    smtp_cls.assert_called_once_with("smtp.gmail.com", 587)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("family@gmail.com", "app-password")
    smtp_instance.send_message.assert_called_once()
    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["From"] == "family@gmail.com"
    assert sent["To"] == "kid@example.com"
    assert sent["Subject"] == "Digest"
    assert sent.get_content().strip() == "Pending claims: 2"


def test_smtp_from_overrides_smtp_user(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "family@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "smtp_from", "Pocket Money <family@gmail.com>")
    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    with patch("smtplib.SMTP", return_value=smtp_instance):
        send_email(["kid@example.com"], "Digest", "body")
    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["From"] == "Pocket Money <family@gmail.com>"
