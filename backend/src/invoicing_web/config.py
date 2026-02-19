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


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _normalize_mode(value: str | None, *, default: str, allowed: set[str]) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized if normalized in allowed else default


def _is_placeholder(value: str, *, defaults: set[str]) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    if normalized in defaults:
        return True
    lower = normalized.lower()
    return lower in {"change-me", "replace-me", "placeholder", "changeme"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "EROS Invoicing Web"
    api_prefix: str = "/api/v1"
    # Legacy OpenClaw settings kept for backward compatibility during migration.
    openclaw_enabled: bool = False
    openclaw_dry_run_default: bool = True
    openclaw_channel: str = "email,sms,imessage"
    openclaw_api_base_url: str = ""
    openclaw_api_key: str = ""
    openclaw_timeout_seconds: int = 30
    openclaw_sender_type: str = "stub"
    # Internal notifier settings (preferred).
    notifier_enabled: bool = False
    notifier_dry_run_default: bool = True
    notifier_channel: str = "email,sms,imessage"
    notifier_api_base_url: str = ""
    notifier_api_key: str = ""
    notifier_timeout_seconds: int = 30
    notifier_sender_type: str = "stub"
    reminder_live_requires_idempotency: bool = True
    reminder_run_limit_max: int = 100
    reminder_allow_live_now_override: bool = False
    reminder_trigger_rate_limit_max: int = 10
    reminder_trigger_rate_limit_window_seconds: int = 60
    reminder_store_backend: str = "inmemory"
    invoice_store_backend: str = "inmemory"
    # Payment routing settings.
    payments_provider: str = "stub"
    payments_provider_name: str = "eros_stub"
    agency_settlement_account_label: str = "agency-main"
    payment_webhook_signature_mode: str = "log_only"
    payment_webhook_signature_max_age_seconds: int = 300
    payment_webhook_secret_default: str = ""
    payment_webhook_secret_stripe: str = ""
    payment_webhook_secret_plaid: str = ""
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
    runtime_secret_guard_mode: str = "warn"
    conversation_enabled: bool = True
    conversation_autoreply_enabled: bool = False
    conversation_store_backend: str = "inmemory"
    conversation_confidence_threshold: float = 0.78
    conversation_max_auto_replies: int = 3
    conversation_webhook_signature_mode: str = "log_only"
    conversation_webhook_max_age_seconds: int = 300
    conversation_provider_twilio_enabled: bool = False
    conversation_provider_sendgrid_enabled: bool = False
    conversation_provider_bluebubbles_enabled: bool = False
    twilio_auth_token: str = ""
    sendgrid_inbound_secret: str = ""
    bluebubbles_webhook_secret: str = ""

    def webhook_secret_for_provider(self, provider: str) -> str:
        normalized = provider.strip().lower()
        if normalized == "stripe":
            return self.payment_webhook_secret_stripe.strip()
        if normalized == "plaid":
            return self.payment_webhook_secret_plaid.strip()
        return self.payment_webhook_secret_default.strip()

    def conversation_provider_enabled(self, provider: str) -> bool:
        normalized = provider.strip().lower()
        if normalized == "twilio":
            return self.conversation_provider_twilio_enabled
        if normalized == "sendgrid":
            return self.conversation_provider_sendgrid_enabled
        if normalized == "bluebubbles":
            return self.conversation_provider_bluebubbles_enabled
        return False


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("INVOICING_APP_NAME", "EROS Invoicing Web"),
        api_prefix=os.getenv("INVOICING_API_PREFIX", "/api/v1"),
        openclaw_enabled=_as_bool(os.getenv("OPENCLAW_ENABLED"), False),
        openclaw_dry_run_default=_as_bool(os.getenv("OPENCLAW_DRY_RUN_DEFAULT"), True),
        openclaw_channel=os.getenv("OPENCLAW_CHANNEL", "email,sms,imessage"),
        openclaw_api_base_url=os.getenv("OPENCLAW_API_BASE_URL", ""),
        openclaw_api_key=os.getenv("OPENCLAW_API_KEY", ""),
        openclaw_timeout_seconds=int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30")),
        openclaw_sender_type=os.getenv("OPENCLAW_SENDER_TYPE", "stub"),
        notifier_enabled=_as_bool(os.getenv("NOTIFIER_ENABLED", os.getenv("OPENCLAW_ENABLED")), False),
        notifier_dry_run_default=_as_bool(
            os.getenv("NOTIFIER_DRY_RUN_DEFAULT", os.getenv("OPENCLAW_DRY_RUN_DEFAULT")), True
        ),
        notifier_channel=os.getenv("NOTIFIER_CHANNEL", os.getenv("OPENCLAW_CHANNEL", "email,sms,imessage")),
        notifier_api_base_url=os.getenv("NOTIFIER_API_BASE_URL", os.getenv("OPENCLAW_API_BASE_URL", "")),
        notifier_api_key=os.getenv("NOTIFIER_API_KEY", os.getenv("OPENCLAW_API_KEY", "")),
        notifier_timeout_seconds=int(os.getenv("NOTIFIER_TIMEOUT_SECONDS", os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30"))),
        notifier_sender_type=os.getenv("NOTIFIER_SENDER_TYPE", os.getenv("OPENCLAW_SENDER_TYPE", "stub")),
        reminder_live_requires_idempotency=_as_bool(os.getenv("REMINDER_LIVE_REQUIRES_IDEMPOTENCY"), True),
        reminder_run_limit_max=int(os.getenv("REMINDER_RUN_LIMIT_MAX", "100")),
        reminder_allow_live_now_override=_as_bool(os.getenv("REMINDER_ALLOW_LIVE_NOW_OVERRIDE"), False),
        reminder_trigger_rate_limit_max=int(os.getenv("REMINDER_TRIGGER_RATE_LIMIT_MAX", "10")),
        reminder_trigger_rate_limit_window_seconds=int(os.getenv("REMINDER_TRIGGER_RATE_LIMIT_WINDOW_SECONDS", "60")),
        reminder_store_backend=os.getenv("REMINDER_STORE_BACKEND", "inmemory"),
        invoice_store_backend=os.getenv("INVOICE_STORE_BACKEND", "inmemory"),
        payments_provider=os.getenv("PAYMENTS_PROVIDER", "stub"),
        payments_provider_name=os.getenv("PAYMENTS_PROVIDER_NAME", "eros_stub"),
        agency_settlement_account_label=os.getenv("AGENCY_SETTLEMENT_ACCOUNT_LABEL", "agency-main"),
        payment_webhook_signature_mode=_normalize_mode(
            os.getenv("PAYMENT_WEBHOOK_SIGNATURE_MODE"),
            default="log_only",
            allowed={"off", "log_only", "enforce"},
        ),
        payment_webhook_signature_max_age_seconds=int(os.getenv("PAYMENT_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS", "300")),
        payment_webhook_secret_default=os.getenv("PAYMENT_WEBHOOK_SECRET_DEFAULT", ""),
        payment_webhook_secret_stripe=os.getenv("PAYMENT_WEBHOOK_SECRET_STRIPE", ""),
        payment_webhook_secret_plaid=os.getenv("PAYMENT_WEBHOOK_SECRET_PLAID", ""),
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
        runtime_secret_guard_mode=_normalize_mode(
            os.getenv("RUNTIME_SECRET_GUARD_MODE"),
            default="warn",
            allowed={"off", "warn", "enforce"},
        ),
        conversation_enabled=_as_bool(os.getenv("CONVERSATION_ENABLED"), True),
        conversation_autoreply_enabled=_as_bool(os.getenv("CONVERSATION_AUTOREPLY_ENABLED"), False),
        conversation_store_backend=os.getenv("CONVERSATION_STORE_BACKEND", "inmemory"),
        conversation_confidence_threshold=_as_float(os.getenv("CONVERSATION_CONFIDENCE_THRESHOLD"), 0.78),
        conversation_max_auto_replies=int(os.getenv("CONVERSATION_MAX_AUTO_REPLIES", "3")),
        conversation_webhook_signature_mode=_normalize_mode(
            os.getenv("CONVERSATION_WEBHOOK_SIGNATURE_MODE"),
            default="log_only",
            allowed={"off", "log_only", "enforce"},
        ),
        conversation_webhook_max_age_seconds=int(os.getenv("CONVERSATION_WEBHOOK_MAX_AGE_SECONDS", "300")),
        conversation_provider_twilio_enabled=_as_bool(os.getenv("CONVERSATION_PROVIDER_TWILIO_ENABLED"), False),
        conversation_provider_sendgrid_enabled=_as_bool(os.getenv("CONVERSATION_PROVIDER_SENDGRID_ENABLED"), False),
        conversation_provider_bluebubbles_enabled=_as_bool(os.getenv("CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED"), False),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        sendgrid_inbound_secret=os.getenv("SENDGRID_INBOUND_SECRET", ""),
        bluebubbles_webhook_secret=os.getenv("BLUEBUBBLES_WEBHOOK_SECRET", ""),
    )


def runtime_secret_issues(settings: Settings) -> tuple[str, ...]:
    issues: list[str] = []
    if _is_placeholder(
        settings.admin_password,
        defaults={"change-me-in-production", "admin", "password", "dev-admin-password"},
    ):
        issues.append("ADMIN_PASSWORD is empty or uses a placeholder value")
    if _is_placeholder(
        settings.admin_session_secret,
        defaults={"dev-admin-secret", "change-me-in-production"},
    ):
        issues.append("ADMIN_SESSION_SECRET is empty or uses a development placeholder")
    if _is_placeholder(
        settings.creator_session_secret,
        defaults={"dev-session-secret", "change-me-in-production"},
    ):
        issues.append("CREATOR_SESSION_SECRET is empty or uses a development placeholder")
    if _is_placeholder(
        settings.broker_token_secret,
        defaults={"dev-broker-secret", "change-me-in-production"},
    ):
        issues.append("BROKER_TOKEN_SECRET is empty or uses a development placeholder")
    if _is_placeholder(
        settings.creator_magic_link_secret,
        defaults={"dev-creator-secret", "change-me-in-production"},
    ):
        issues.append("CREATOR_MAGIC_LINK_SECRET is empty or uses a development placeholder")
    if settings.payment_webhook_signature_mode == "enforce" and not settings.webhook_secret_for_provider("stripe"):
        issues.append("PAYMENT_WEBHOOK_SECRET_STRIPE is required when PAYMENT_WEBHOOK_SIGNATURE_MODE=enforce")
    conversation_enforce = (
        settings.conversation_enabled
        and settings.conversation_webhook_signature_mode == "enforce"
    )
    if (
        conversation_enforce
        and settings.conversation_provider_twilio_enabled
        and not settings.twilio_auth_token.strip()
    ):
        issues.append(
            "TWILIO_AUTH_TOKEN is required when CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce "
            "and CONVERSATION_PROVIDER_TWILIO_ENABLED=true"
        )
    if (
        conversation_enforce
        and settings.conversation_provider_sendgrid_enabled
        and not settings.sendgrid_inbound_secret.strip()
    ):
        issues.append(
            "SENDGRID_INBOUND_SECRET is required when CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce "
            "and CONVERSATION_PROVIDER_SENDGRID_ENABLED=true"
        )
    if (
        conversation_enforce
        and settings.conversation_provider_bluebubbles_enabled
        and not settings.bluebubbles_webhook_secret.strip()
    ):
        issues.append(
            "BLUEBUBBLES_WEBHOOK_SECRET is required when CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce "
            "and CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED=true"
        )
    return tuple(issues)
