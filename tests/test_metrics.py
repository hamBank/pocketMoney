"""pmoney_external_requests_total and /metrics (fleet spec OBS-2)."""
import re
import smtplib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
from prometheus_client import REGISTRY

import backend.main as main
from backend import auth, metrics
from backend.config import settings
from backend.emails import send_email
from backend.sheets import GoogleSheetsClient, SheetsError

RULES = Path(__file__).resolve().parent.parent / "docs" / "prometheus-alerts.yml"


def count(service, status):
    value = REGISTRY.get_sample_value(
        "pmoney_external_requests_total", {"service": service, "status": status}
    )
    return value or 0


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    # Spy on the logger itself rather than caplog: Alembic's fileConfig() (run by an
    # earlier test in the same process) disables loggers it doesn't know, which makes
    # caplog order-dependent.
    monkeypatch.setattr(metrics._external_logger, "warning", lambda *a, **k: seen.append(a))
    return seen


def test_success_and_error_are_counted_separately(warnings):
    ok, bad = count("t_svc", "success"), count("t_svc", "error")
    metrics.record_external_call("t_svc", ok=True)
    metrics.record_external_call("t_svc", ok=False, error="boom")
    assert count("t_svc", "success") == ok + 1
    assert count("t_svc", "error") == bad + 1


def test_only_failures_are_logged(warnings):
    metrics.record_external_call("t_log", ok=True)
    assert warnings == []
    metrics.record_external_call("t_log", ok=False, error="rate limited")
    assert len(warnings) == 1 and "rate limited" in warnings[0]


# --- Google Sheets: every HTTP call through GoogleSheetsClient._call -------------


class FakeSession:
    def __init__(self, status=200, raises=None):
        self.status, self.raises = status, raises

    def request(self, method, url, timeout, **kwargs):
        if self.raises:
            raise self.raises
        return MagicMock(status_code=self.status, content=b"{}", text="", json=lambda: {})


def test_sheets_success_is_counted():
    before = count("google_sheets", "success")
    GoogleSheetsClient("sheet", FakeSession(200))._call("GET", "")
    assert count("google_sheets", "success") == before + 1


def test_sheets_http_error_is_counted_and_still_raises(warnings):
    before = count("google_sheets", "error")
    with pytest.raises(SheetsError):
        GoogleSheetsClient("sheet", FakeSession(503))._call("GET", "/values/'Kid'!A2")
    assert count("google_sheets", "error") == before + 1
    assert "503" in warnings[0][-1]
    assert "Kid" not in str(warnings), "tab names (children) must stay out of the log line"


def test_sheets_network_failure_is_counted_and_still_raises(warnings):
    before = count("google_sheets", "error")
    with pytest.raises(ConnectionError):
        GoogleSheetsClient("sheet", FakeSession(raises=ConnectionError("down")))._call("GET", "")
    assert count("google_sheets", "error") == before + 1


# --- Google sign-in -------------------------------------------------------------


def test_signin_success_is_counted(monkeypatch):
    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", lambda *a: {"email": "a@b.c"})
    before = count("google_oauth", "success")
    assert auth.verify_google_token("tok") == {"email": "a@b.c"}
    assert count("google_oauth", "success") == before + 1


def test_a_bad_token_is_not_an_upstream_error(monkeypatch):
    """travelCompantion counts every exception as an error; here a user's bad or
    expired token would page us for a Google outage that isn't happening."""

    def reject(*a):
        raise ValueError("Token expired")

    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", reject)
    errors, ok = count("google_oauth", "error"), count("google_oauth", "success")
    with pytest.raises(ValueError):
        auth.verify_google_token("tok")
    assert count("google_oauth", "error") == errors
    assert count("google_oauth", "success") == ok + 1


def test_failing_to_reach_google_is_an_error(monkeypatch, warnings):
    def unreachable(*a):
        raise TransportError("could not fetch certs")

    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", unreachable)
    before = count("google_oauth", "error")
    with pytest.raises(TransportError):
        auth.verify_google_token("tok")
    assert count("google_oauth", "error") == before + 1


# --- SMTP -----------------------------------------------------------------------


def smtp_double(raises=None):
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    if raises:
        smtp.send_message.side_effect = raises
    return smtp


def test_a_sent_email_is_counted(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "family@gmail.com")
    before = count("smtp", "success")
    with patch("smtplib.SMTP", return_value=smtp_double()):
        send_email(["kid@example.com"], "Digest", "Body")
    assert count("smtp", "success") == before + 1


def test_a_failed_email_is_counted_without_the_recipient_in_the_log(monkeypatch, warnings):
    monkeypatch.setattr(settings, "smtp_user", "family@gmail.com")
    before = count("smtp", "error")
    refused = smtplib.SMTPRecipientsRefused({"kid@example.com": (550, b"no")})
    with patch("smtplib.SMTP", return_value=smtp_double(raises=refused)):
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            send_email(["kid@example.com"], "Digest", "Body")
    assert count("smtp", "error") == before + 1
    assert "kid@example.com" not in str(warnings)


def test_email_disabled_mode_counts_nothing(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "")
    before = (count("smtp", "success"), count("smtp", "error"))
    send_email(["kid@example.com"], "Digest", "Body")
    assert (count("smtp", "success"), count("smtp", "error")) == before


# --- /metrics and the alert rules ------------------------------------------------


def test_metrics_endpoint_serves_the_counter(client):
    metrics.record_external_call("t_endpoint", ok=True)
    response = client.get("/metrics")  # no token: scrapers don't carry one
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'pmoney_external_requests_total{service="t_endpoint",status="success"}' in response.text


def test_every_metric_the_alert_rules_use_is_really_exported(client):
    """A renamed counter would leave the alerts silently watching nothing."""
    metrics.record_external_call("t_rules", ok=True)
    exported = client.get("/metrics").text
    used = set(re.findall(r"\bpmoney_[a-z_]+", RULES.read_text()))
    assert "pmoney_external_requests_total" in used
    missing = {name for name in used if name not in exported}
    assert not missing, f"alert rules use metrics that /metrics does not export: {missing}"


def test_metrics_is_not_shadowed_by_the_spa_catch_all(tmp_path, monkeypatch):
    """With the frontend built (as in production) the catch-all matches every GET,
    so /metrics must be registered ahead of it."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SPA SHELL</html>")
    monkeypatch.setattr(main, "STATIC_DIR", static)
    response = TestClient(main.create_app()).get("/metrics")
    assert "SPA SHELL" not in response.text
    assert "pmoney_external_requests_total" in response.text


def test_alerts_are_named_and_labelled_for_this_app():
    """travelCompantion's rules use the same alert names and also count
    `google_oauth`. Without a unique name and an app label, the two apps' alerts
    would share one identity in Alertmanager and overwrite each other."""
    text = RULES.read_text()
    names = re.findall(r"- alert: (\w+)", text)
    assert names and all(name.startswith("Pmoney") for name in names), names
    assert len(re.findall(r"^\s+app: pmoney$", text, re.M)) == len(names)
