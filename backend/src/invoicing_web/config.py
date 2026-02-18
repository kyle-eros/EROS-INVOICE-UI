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


def _as_csv_tuple(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    items = [item.strip() for item in value.split(",")]
    return tuple(item for item in items if item)


@dataclass(frozen=True)
class Settings:
    app_name: str = "EROS Invoicing Web"
    api_prefix: str = "/api/v1"
    # Legacy OpenClaw settings kept for backward compatibility during migration.
    openclaw_enabled: bool = False
    openclaw_dry_run_default: bool = True
    openclaw_channel: str = "email,sms"
    openclaw_api_base_url: str = ""
    openclaw_api_key: str = ""
    openclaw_timeout_seconds: int = 30
    openclaw_sender_type: str = "stub"
    # Internal notifier settings (preferred).
    notifier_enabled: bool = False
    notifier_dry_run_default: bool = True
    notifier_channel: str = "email,sms"
    notifier_api_base_url: str = ""
    notifier_api_key: str = ""
    notifier_timeout_seconds: int = 30
    notifier_sender_type: str = "stub"
    # Payment routing settings.
    payments_provider: str = "stub"
    payments_provider_name: str = "eros_stub"
    agency_settlement_account_label: str = "agency-main"
    auth_store_backend: str = "inmemory"
    database_url: str = ""
    creator_magic_link_secret: str = "dev-creator-secret"
    creator_portal_base_url: str = "http://localhost:3000/creator"
    trust_proxy_headers: bool = False
    trusted_proxy_ips: tuple[str, ...] = ()
    admin_password: str = ""
    admin_session_secret: str = "dev-admin-secret"
    creator_session_secret: str = "dev-session-secret"
    creator_session_ttl_minutes: int = 120
    cookie_secure: bool = True
    broker_token_secret: str = "dev-broker-secret"
    broker_token_default_ttl_minutes: int = 60
    broker_token_max_ttl_minutes: int = 480


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("INVOICING_APP_NAME", "EROS Invoicing Web"),
        api_prefix=os.getenv("INVOICING_API_PREFIX", "/api/v1"),
        openclaw_enabled=_as_bool(os.getenv("OPENCLAW_ENABLED"), False),
        openclaw_dry_run_default=_as_bool(os.getenv("OPENCLAW_DRY_RUN_DEFAULT"), True),
        openclaw_channel=os.getenv("OPENCLAW_CHANNEL", "email,sms"),
        openclaw_api_base_url=os.getenv("OPENCLAW_API_BASE_URL", ""),
        openclaw_api_key=os.getenv("OPENCLAW_API_KEY", ""),
        openclaw_timeout_seconds=int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30")),
        openclaw_sender_type=os.getenv("OPENCLAW_SENDER_TYPE", "stub"),
        notifier_enabled=_as_bool(os.getenv("NOTIFIER_ENABLED", os.getenv("OPENCLAW_ENABLED")), False),
        notifier_dry_run_default=_as_bool(
            os.getenv("NOTIFIER_DRY_RUN_DEFAULT", os.getenv("OPENCLAW_DRY_RUN_DEFAULT")), True
        ),
        notifier_channel=os.getenv("NOTIFIER_CHANNEL", os.getenv("OPENCLAW_CHANNEL", "email,sms")),
        notifier_api_base_url=os.getenv("NOTIFIER_API_BASE_URL", os.getenv("OPENCLAW_API_BASE_URL", "")),
        notifier_api_key=os.getenv("NOTIFIER_API_KEY", os.getenv("OPENCLAW_API_KEY", "")),
        notifier_timeout_seconds=int(os.getenv("NOTIFIER_TIMEOUT_SECONDS", os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30"))),
        notifier_sender_type=os.getenv("NOTIFIER_SENDER_TYPE", os.getenv("OPENCLAW_SENDER_TYPE", "stub")),
        payments_provider=os.getenv("PAYMENTS_PROVIDER", "stub"),
        payments_provider_name=os.getenv("PAYMENTS_PROVIDER_NAME", "eros_stub"),
        agency_settlement_account_label=os.getenv("AGENCY_SETTLEMENT_ACCOUNT_LABEL", "agency-main"),
        auth_store_backend=os.getenv("AUTH_STORE_BACKEND", "inmemory"),
        database_url=os.getenv("DATABASE_URL", ""),
        creator_magic_link_secret=os.getenv("CREATOR_MAGIC_LINK_SECRET", "dev-creator-secret"),
        creator_portal_base_url=os.getenv("CREATOR_PORTAL_BASE_URL", "http://localhost:3000/creator"),
        trust_proxy_headers=_as_bool(os.getenv("TRUST_PROXY_HEADERS"), False),
        trusted_proxy_ips=_as_csv_tuple(os.getenv("TRUSTED_PROXY_IPS")),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        admin_session_secret=os.getenv("ADMIN_SESSION_SECRET", "dev-admin-secret"),
        creator_session_secret=os.getenv("CREATOR_SESSION_SECRET", "dev-session-secret"),
        creator_session_ttl_minutes=int(os.getenv("CREATOR_SESSION_TTL_MINUTES", "120")),
        cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), True),
        broker_token_secret=os.getenv("BROKER_TOKEN_SECRET", "dev-broker-secret"),
        broker_token_default_ttl_minutes=int(os.getenv("BROKER_TOKEN_DEFAULT_TTL_MINUTES", "60")),
        broker_token_max_ttl_minutes=int(os.getenv("BROKER_TOKEN_MAX_TTL_MINUTES", "480")),
    )
