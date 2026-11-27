from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta")
async def meta(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "name": settings.app_name,
        "tagline": settings.app_tagline,
        "features": {"dira": settings.dira_enabled},
    }
