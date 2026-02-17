from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    app_name: str = "EROS Invoicing Web"
    api_prefix: str = "/api/v1"
    openclaw_enabled: bool = False
    openclaw_dry_run_default: bool = True
    openclaw_channel: str = "email,sms"
    openclaw_api_base_url: str = ""
    openclaw_api_key: str = ""
    creator_magic_link_secret: str = "dev-creator-secret"
    creator_portal_base_url: str = "http://localhost:3000/creator"
    admin_password: str = ""
    admin_session_secret: str = "dev-admin-secret"
    creator_session_secret: str = "dev-session-secret"
    creator_session_ttl_minutes: int = 120
    cookie_secure: bool = True
    broker_token_secret: str = "dev-broker-secret"
    broker_token_default_ttl_minutes: int = 60
    broker_token_max_ttl_minutes: int = 480
    openclaw_timeout_seconds: int = 30
    openclaw_sender_type: str = "stub"


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("INVOICING_APP_NAME", "EROS Invoicing Web"),
        api_prefix=os.getenv("INVOICING_API_PREFIX", "/api/v1"),
        openclaw_enabled=_as_bool(os.getenv("OPENCLAW_ENABLED"), False),
        openclaw_dry_run_default=_as_bool(os.getenv("OPENCLAW_DRY_RUN_DEFAULT"), True),
        openclaw_channel=os.getenv("OPENCLAW_CHANNEL", "email,sms"),
        openclaw_api_base_url=os.getenv("OPENCLAW_API_BASE_URL", ""),
        openclaw_api_key=os.getenv("OPENCLAW_API_KEY", ""),
        creator_magic_link_secret=os.getenv("CREATOR_MAGIC_LINK_SECRET", "dev-creator-secret"),
        creator_portal_base_url=os.getenv("CREATOR_PORTAL_BASE_URL", "http://localhost:3000/creator"),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        admin_session_secret=os.getenv("ADMIN_SESSION_SECRET", "dev-admin-secret"),
        creator_session_secret=os.getenv("CREATOR_SESSION_SECRET", "dev-session-secret"),
        creator_session_ttl_minutes=int(os.getenv("CREATOR_SESSION_TTL_MINUTES", "120")),
        cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), True),
        broker_token_secret=os.getenv("BROKER_TOKEN_SECRET", "dev-broker-secret"),
        broker_token_default_ttl_minutes=int(os.getenv("BROKER_TOKEN_DEFAULT_TTL_MINUTES", "60")),
        broker_token_max_ttl_minutes=int(os.getenv("BROKER_TOKEN_MAX_TTL_MINUTES", "480")),
        openclaw_timeout_seconds=int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30")),
        openclaw_sender_type=os.getenv("OPENCLAW_SENDER_TYPE", "stub"),
    )
