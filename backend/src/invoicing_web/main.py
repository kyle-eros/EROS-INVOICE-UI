from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import get_settings, runtime_secret_issues

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    secret_issues = runtime_secret_issues(settings)
    if secret_issues:
        if settings.runtime_secret_guard_mode == "enforce":
            raise RuntimeError(
                "runtime secret guard blocked startup: "
                + "; ".join(secret_issues)
                + ". Remediation: disable unused providers via CONVERSATION_PROVIDER_*_ENABLED=false "
                + "or set the required provider secrets."
            )
        if settings.runtime_secret_guard_mode == "warn":
            for issue in secret_issues:
                logger.warning("runtime secret guard warning: %s", issue)

    app = FastAPI(title=settings.app_name, version="0.1.0")

    portal_origin = settings.creator_portal_base_url.rstrip("/")
    if portal_origin.startswith("http://localhost:3000"):
        portal_origin = "http://localhost:3000"
    elif "://" in portal_origin:
        parts = portal_origin.split("/")
        portal_origin = "/".join(parts[:3])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[portal_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
