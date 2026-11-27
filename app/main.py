"""FastAPI entry point: API, built frontend and (later) the MCP endpoint in one service."""

import html
import logging
import sys
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DBAPIError
from starlette.types import Scope

from app.config import Settings, get_settings
from app.errors import database_error_handler
from app.middleware import (
    BodySizeLimitMiddleware,
    SameOriginMiddleware,
    SecurityHeadersMiddleware,
)
from app.routers import account, admin, applications, auth, board, health, meta
from app.services.ratelimit import RateLimiter

STATIC_DIR = Path(__file__).parent / "static"


def configure_logging(settings: Settings) -> None:
    # stdout: Railway shows stderr lines as errors.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Access logs carry query strings (reset tokens); keep them out of production logs.
    if settings.is_production:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, static_dir: Path = STATIC_DIR) -> FastAPI:
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
    app.add_exception_handler(DBAPIError, database_error_handler)

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(account.router)
    app.include_router(board.router)
    app.include_router(admin.router)

    _mount_frontend(app, settings, static_dir)

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


class HashedAssets(StaticFiles):
    """Vite names every file in /assets after its content, so a URL never
    changes meaning: browsers may keep it for a year without asking again."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _mount_frontend(app: FastAPI, settings: Settings, static_dir: Path) -> None:
    """Serve the Vite build from app/static, with index.html for client-side routes."""
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", HashedAssets(directory=assets), name="assets")

    index_path = static_dir / "index.html"
    index_html = (
        index_path.read_text(encoding="utf-8")
        .replace("__APP_NAME__", html.escape(settings.app_name))
        .replace("__APP_TAGLINE__", html.escape(settings.app_tagline))
        if index_path.is_file()
        else None
    )
    static_root = static_dir.resolve()

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD"], include_in_schema=False, response_model=None
    )
    async def spa(path: str) -> FileResponse | HTMLResponse:
        if path == "api" or path.startswith(("api/", "mcp")):
            raise HTTPException(status_code=404)
        if path:
            candidate = (static_dir / path).resolve()
            if candidate.is_relative_to(static_root) and candidate.is_file():
                # Unhashed names (theme.js): always check for a newer copy.
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        if index_html is None:
            raise HTTPException(status_code=404, detail="Frontend not built")
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})


app = create_app()
