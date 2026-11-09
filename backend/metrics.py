"""Prometheus metrics (fleet spec OBS-2), in the same shape as travelCompantion's
backend/metrics.py: one counter, one helper, called around every outbound call.

    pmoney_external_requests_total{service, status}    status: success | error

Services: google_sheets (the ledger mirror), google_oauth (sign-in) and smtp
(the digest email). Failures are otherwise invisible: the Sheets mirror runs as
a background task and the app carries on, so nothing shows up in HTTP status
codes or the UI.

LIMIT, shared with travelCompantion: counters live in this process's memory (and
reset on restart, which Prometheus' rate()/increase() allow for). The timer jobs
(the 10-minute sheet sync, the weekly allowance, the digest) run in their own
short-lived processes, which serve no /metrics, so calls made there are NOT
counted. What is counted: sign-ins, and the Sheets sync that runs as a
background task in the web process after a money-changing request.
"""
import logging

from prometheus_client import Counter

_external_logger = logging.getLogger("pmoney.external")

external_requests = Counter(
    "pmoney_external_requests_total",
    "Outbound calls to third-party services",
    ["service", "status"],  # status: success | error
)


def record_external_call(service: str, ok: bool, error: str = "") -> None:
    """Count one outbound call. Call it once the outcome is known, from a
    try/except around the request. Always increments the counter; logs only
    failures, at warning level, so one incident can be found in the app log
    without routine successes flooding it. Keep `error` short and free of
    personal data (a status code or an exception class, not a message body)."""
    external_requests.labels(service=service, status="success" if ok else "error").inc()
    if not ok:
        _external_logger.warning("external call failed: service=%s error=%s", service, error)
