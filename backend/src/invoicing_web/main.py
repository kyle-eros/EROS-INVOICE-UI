from __future__ import annotations

from fastapi import FastAPI

from .api import router
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(router)
    return app


app = create_app()
