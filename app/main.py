"""FastAPI entry point: API, built frontend and (later) the MCP endpoint in one service."""

import html
import logging
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.middleware import (
    BodySizeLimitMiddleware,
    SameOriginMiddleware,
    SecurityHeadersMiddleware,
)
from app.routers import account, applications, auth, health, meta
from app.services.ratelimit import RateLimiter

STATIC_DIR = Path(__file__).parent / "static"


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Access logs carry query strings (reset tokens); keep them out of production logs.
    if settings.is_production:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        description=f"{settings.app_name}: {settings.app_tagline}",
        # No public schema browser in production.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.state.settings = settings
    app.state.limiter = RateLimiter()

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(account.router)

    _mount_frontend(app, settings)

    # Outermost last: the size cap runs before anything reads the body.
    app.add_middleware(SameOriginMiddleware, allowed_origins=_allowed_origins(settings))
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    return app


def _allowed_origins(settings: Settings) -> frozenset[str]:
    base = urlsplit(settings.base_url)
    origins = {f"{base.scheme}://{base.netloc}"}
    if not settings.is_production:
        # The Vite dev server proxies /api from here.
        origins |= {"http://localhost:5173", "http://127.0.0.1:5173"}
    return frozenset(origins)


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the Vite build from app/static, with index.html for client-side routes."""
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index_path = STATIC_DIR / "index.html"
    index_html = (
        index_path.read_text(encoding="utf-8")
        .replace("__APP_NAME__", html.escape(settings.app_name))
        .replace("__APP_TAGLINE__", html.escape(settings.app_tagline))
        if index_path.is_file()
        else None
    )
    static_root = STATIC_DIR.resolve()

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD"], include_in_schema=False, response_model=None
    )
    async def spa(path: str) -> FileResponse | HTMLResponse:
        if path == "api" or path.startswith(("api/", "mcp")):
            raise HTTPException(status_code=404)
        if path:
            candidate = (STATIC_DIR / path).resolve()
            if candidate.is_relative_to(static_root) and candidate.is_file():
                return FileResponse(candidate)
        if index_html is None:
            raise HTTPException(status_code=404, detail="Frontend not built")
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})


app = create_app()
