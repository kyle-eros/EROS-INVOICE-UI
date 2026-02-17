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
    openclaw_channel: str = "email"
    openclaw_api_base_url: str = ""
    openclaw_api_key: str = ""


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("INVOICING_APP_NAME", "EROS Invoicing Web"),
        api_prefix=os.getenv("INVOICING_API_PREFIX", "/api/v1"),
        openclaw_enabled=_as_bool(os.getenv("OPENCLAW_ENABLED"), False),
        openclaw_dry_run_default=_as_bool(os.getenv("OPENCLAW_DRY_RUN_DEFAULT"), True),
        openclaw_channel=os.getenv("OPENCLAW_CHANNEL", "email"),
        openclaw_api_base_url=os.getenv("OPENCLAW_API_BASE_URL", ""),
        openclaw_api_key=os.getenv("OPENCLAW_API_KEY", ""),
    )
