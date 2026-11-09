# Plan: `/metrics` and an alert-rules file (fleet spec OBS-2)

Status: **built, in the travelCompantion shape (see "Outcome" at the end).** The sections between are the
original plan. Rule (SHOULD): `/metrics` (Prometheus) with a
`<app>_external_requests_total{service=…}` counter, and an alert-rules file in `docs/`.
pocketMoney is ✗ today; travelCompantion has it.

## What pocketMoney calls out to

| `service` | Choke point | Runs in | Volume |
|---|---|---|---|
| `google_sheets` | `GoogleSheetsClient._call` (`backend/sheets.py`) | the web process (a background task after every money-changing request) **and** the timer jobs (`sync_sheet.py` every 10 min, `apply_weekly_allowance.py`) | a steady-state sync makes **N + 3** HTTP calls (1 spreadsheet read, 1 column read per child, 1 clear + 1 write on the totals tab). With 4 children that is 7 per tick, about 1,000 a day from the timer alone |
| `smtp` | `emails.send_email` | the digest timer job | 1 a day |
| `google_oauth` | `auth.verify_google_token` | the web process | 1 per sign-in. The library fetches and caches Google's signing certs itself, so this counts verifications, an upper bound on HTTP requests |

Google's documented default Sheets limit is 60 requests per minute per user and project, with no
monthly cap (re-check the figure in the Cloud console). A 7-call burst every 10 minutes is far
inside it. The counter below turns that estimate into a measurement, which is also the missing
evidence for OBS-3.

## The design problem: two kinds of process

The calls above happen in uvicorn **and** in short-lived timer processes. A counter held in the
web process's memory would miss every timer call, which is most of the Sheets traffic, and would
reset on each restart. So the counts have to live somewhere all the processes share: the database.

## Design

1. **Counts in Postgres.** Table `external_call_counts(service, outcome, count)`, primary key
   `(service, outcome)`. `backend/metrics.py: record_external(service, outcome)` runs
   `UPDATE … SET count = count + 1` and inserts the row if none exists (retrying once if two
   processes race on the insert). It uses its own short session and **swallows and logs its own
   errors**: recording must never fail or slow the call it describes. One Alembic migration that
   runs on SQLite and Postgres, whose `downgrade()` drops the table. Not the ledger, so the
   append-only invariant is untouched.
2. **Instrument only the three choke points** above, recording `ok` or `error`.
3. **`GET /metrics`** renders the text exposition format by hand, with no new dependency. Three
   counters don't need `prometheus_client`, and `CLAUDE.md`'s incident log is a history of
   dependency drift.
   ```
   # TYPE pmoney_external_requests_total counter
   pmoney_external_requests_total{service="google_sheets",outcome="ok"} 1234
   ```
4. **Protect it with a bearer token** (`METRICS_TOKEN` in `.env`; unset means 404, so it fails
   closed). Not an Apache rule: since DEP-8 the live vhost belongs to certbot, so a change to
   the repo's vhost file no longer reaches the server without a manual merge. A missing or wrong
   token answers 401, so the AUTH-6 route-protection test needs no allowlist entry. The route must
   stay in the OpenAPI schema, because that test enumerates `app.openapi()`.
5. **Alert rules** in `docs/alerts/pocketmoney.rules.yml`, plus a test that parses the file
   (every rule has `alert`, `expr`, `for`, labels and annotations), because `promtool` isn't in CI:
   - `PocketMoneyDown`: `up{job="pocketmoney"} == 0` for 5m.
   - `PocketMoneyExternalErrors`: `increase(pmoney_external_requests_total{outcome="error"}[1h]) > 5`.
   - `PocketMoneySheetsBurst`: Sheets calls per minute above 40, guarding the per-minute quota.
   - `PocketMoneySheetsSilent`: no Sheets calls for an hour means the 10-minute sync timer has
     stopped. A heartbeat from the same counter. Only valid while the sheet is configured, so it
     ships commented out with that condition spelled out.

## Naming choices

- Prefix `pmoney_`, matching the units (`pmoney-*`) and the service name.
- An extra `outcome` label next to the spec's `service`, because "errors rising" needs it.

## Delivery: four small PRs, each CI-gated and deployable alone

1. **Counter plumbing**: model, migration, `record_external`, the three call sites, tests. No
   endpoint yet, so nothing is exposed.
2. **`/metrics` + `METRICS_TOKEN`**: route, config, `.env.example`, tests (format, 404 when
   unset, 401 on a bad token, 200 on a good one, route-protection test still green), docs.
3. **Alert rules file + parse test + a scrape-config snippet** in `DEPLOYMENT.md`. The spec cell
   can flip to ✓ here.
4. *(Optional)* **Job heartbeats**: each script records its last success, exposed as
   `pmoney_job_last_success_timestamp_seconds{job}`, with an alert when stale. Skip it if
   node_exporter's systemd collector already watches the timers.

## Decisions needed before PR 2

1. **Is there a Prometheus (and Alertmanager) already scraping travelCompantion?** Where, and can
   it reach `pmoney.hups.club` over HTTPS with a bearer token? Without a scraper, the endpoint and
   the rules have no consumer and OBS-2 becomes box-ticking. Standing one up is its own decision.
2. **Names:** is `pmoney_` plus the extra `outcome` label fine, or should it match travelCompantion's
   exact names? (I can't see that repo.)
3. **Scrape path:** token over HTTPS, or is the scraper on this box (then bind to localhost and
   block `/metrics` in Apache by hand)?
4. **Phase 4:** want job heartbeats, or does node_exporter cover the timers?

## Not doing

`prometheus_client`, a Pushgateway, a per-request HTTP metrics middleware (not what OBS-2 asks),
or an Apache change.

## Unverified

Google's quota figure (above), TC's conventions, and whether a scraper exists.

## Outcome (2026-11-09)

Built by copying travelCompantion's setup, which answered the open decisions:

- **Prometheus exists** (travelCompantion's). Rules are copied by hand into
  `/etc/prometheus/rules/`; the scrape config is not in either repo.
- **Names:** `pmoney_external_requests_total{service, status}`. The label is `status`
  (`success | error`), matching travelCompantion's, not the `outcome` proposed above.
- **`/metrics` is unauthenticated**, like travelCompantion's, so there is no `METRICS_TOKEN`.
  `tests/test_route_protection.py` lists it as public, with the reason.
- **Counters are in-process** (`prometheus_client`), not the database table proposed above.
- **One deliberate difference:** a `ValueError` from Google sign-in (a bad or expired user
  token) counts as a successful call to Google. travelCompantion counts every exception as
  an error, which would page on someone mistyping a login.
- Only `docs/prometheus-alerts.yml` (two rules) was copied; no Grafana dashboard and no
  `prometheus-fastapi-instrumentator` HTTP metrics.

**Still open: the blind spot this plan identified.** Because the counters are per-process,
the timer jobs are not counted: the every-10-minute sheet sync (the bulk of the Sheets traffic),
the weekly allowance and the digest. A sync that fails only from its timer trips nothing here.
travelCompantion has the same limit. If that matters, the options are the database-backed
counter described under "Design" above, or a heartbeat per job (phase 4).

