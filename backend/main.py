from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text

from .database import engine

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Pocket Money")

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    # Routers must be included above this line — the SPA catch-all matches
    # everything and must be registered last.
    if STATIC_DIR.is_dir():

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str):
            candidate = STATIC_DIR / spa_path
            if spa_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
