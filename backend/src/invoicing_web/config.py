from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "EROS Invoicing Web"
    api_prefix: str = "/api/v1"


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("INVOICING_APP_NAME", "EROS Invoicing Web"),
        api_prefix=os.getenv("INVOICING_API_PREFIX", "/api/v1"),
    )
