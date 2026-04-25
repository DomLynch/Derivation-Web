"""FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from derivation_web.api.audit import AuditMiddleware
from derivation_web.api.routes import router as api_router
from derivation_web.api.views import router as views_router
from derivation_web.db.session import make_session

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

# Make sure the audit logger emits at INFO regardless of root config.
logging.getLogger("derivation_web.audit").setLevel(logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(title="Derivation Web", version="0.1.0")
    app.state.templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    app.add_middleware(AuditMiddleware)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    app.include_router(api_router, prefix="/api")
    app.include_router(views_router)

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        """Liveness + DB connectivity. Returns 200 even if DB is down,
        with `db: false` so external probes can distinguish.
        """
        db_ok = False
        try:
            with make_session() as session:
                session.execute(text("SELECT 1"))
                db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok", "db": db_ok}

    return app


app = create_app()
