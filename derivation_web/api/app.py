"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from derivation_web.api.routes import router as api_router
from derivation_web.api.views import router as views_router

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Derivation Web", version="0.1.0")
    app.state.templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    app.include_router(api_router, prefix="/api")
    app.include_router(views_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
