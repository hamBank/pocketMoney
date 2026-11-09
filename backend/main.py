import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import text

from .config import settings
from .database import engine
from .routers import auth_router, chores, claims, transactions, users
from .version import backend_version, frontend_version

STATIC_DIR = Path(__file__).parent / "static"
STARTED_AT = datetime.now(timezone.utc).isoformat()


def create_app() -> FastAPI:
    app = FastAPI(title="Pocket Money")

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # Fleet spec OBS-1 contract; field meanings in backend/version.py.
        frontend = frontend_version()
        return {
            "status": "ok",
            "backend_sha": backend_version(),
            "frontend_sha": frontend["frontend_sha"],
            "build_sha": frontend["build_sha"],
            "built_at": frontend["built_at"],
            "started_at": STARTED_AT,
        }

    @app.post("/deploy")
    async def deploy(request: Request):
        """GitHub push webhook → touch .deploy-trigger; a systemd path unit
        watching that file runs deploy.sh --update (see DEPLOYMENT.md)."""
        if not settings.deploy_secret:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Deploy webhook not configured"
            )
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.deploy_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad signature")
        try:
            ref = json.loads(body).get("ref")
        except (json.JSONDecodeError, AttributeError):
            ref = None
        # GitHub sends pushes for every branch; only main redeploys.
        if ref is not None and ref != "refs/heads/main":
            return {"status": "ignored", "ref": ref}
        Path(settings.deploy_trigger_path).touch()
        return {"status": "triggered"}

    app.include_router(auth_router.router)
    app.include_router(users.router)
    app.include_router(chores.router)
    app.include_router(claims.router)
    app.include_router(transactions.router)

    # Routers must be included above this line — the SPA catch-all matches
    # everything and must be registered last.
    if STATIC_DIR.is_dir():

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str):
            # The path is attacker-controlled and arrives percent-decoded, so
            # "../" can climb out of STATIC_DIR. Serve only files that resolve
            # to somewhere inside it; everything else gets the app shell.
            root = STATIC_DIR.resolve()
            try:
                candidate = (root / spa_path).resolve()
                inside = spa_path and candidate.is_relative_to(root) and candidate.is_file()
            except (OSError, ValueError):  # e.g. an embedded NUL byte
                inside = False
            if inside:
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app


app = create_app()
