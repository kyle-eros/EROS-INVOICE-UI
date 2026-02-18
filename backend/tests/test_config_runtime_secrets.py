from __future__ import annotations

import os

from invoicing_web.config import get_settings, runtime_secret_issues


def _set_env(name: str, value: str | None) -> str | None:
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return previous


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def test_get_settings_defaults_conversation_providers_to_disabled() -> None:
    previous_twilio = _set_env("CONVERSATION_PROVIDER_TWILIO_ENABLED", None)
    previous_sendgrid = _set_env("CONVERSATION_PROVIDER_SENDGRID_ENABLED", None)
    try:
        settings = get_settings()
        assert settings.conversation_provider_twilio_enabled is False
        assert settings.conversation_provider_sendgrid_enabled is False
    finally:
        _restore_env("CONVERSATION_PROVIDER_TWILIO_ENABLED", previous_twilio)
        _restore_env("CONVERSATION_PROVIDER_SENDGRID_ENABLED", previous_sendgrid)


def test_unset_conversation_provider_flags_do_not_require_twilio_or_sendgrid_secrets() -> None:
    previous = {
        "ADMIN_PASSWORD": _set_env("ADMIN_PASSWORD", "prod-admin-password-001"),
        "ADMIN_SESSION_SECRET": _set_env("ADMIN_SESSION_SECRET", "prod-admin-secret-001"),
        "CREATOR_SESSION_SECRET": _set_env("CREATOR_SESSION_SECRET", "prod-creator-secret-001"),
        "BROKER_TOKEN_SECRET": _set_env("BROKER_TOKEN_SECRET", "prod-broker-secret-001"),
        "CREATOR_MAGIC_LINK_SECRET": _set_env("CREATOR_MAGIC_LINK_SECRET", "prod-creator-magic-secret-001"),
        "CONVERSATION_ENABLED": _set_env("CONVERSATION_ENABLED", "true"),
        "CONVERSATION_WEBHOOK_SIGNATURE_MODE": _set_env("CONVERSATION_WEBHOOK_SIGNATURE_MODE", "enforce"),
        "CONVERSATION_PROVIDER_TWILIO_ENABLED": _set_env("CONVERSATION_PROVIDER_TWILIO_ENABLED", None),
        "CONVERSATION_PROVIDER_SENDGRID_ENABLED": _set_env("CONVERSATION_PROVIDER_SENDGRID_ENABLED", None),
        "TWILIO_AUTH_TOKEN": _set_env("TWILIO_AUTH_TOKEN", None),
        "SENDGRID_INBOUND_SECRET": _set_env("SENDGRID_INBOUND_SECRET", None),
    }
    try:
        issues = runtime_secret_issues(get_settings())
        assert not any("TWILIO_AUTH_TOKEN" in issue for issue in issues)
        assert not any("SENDGRID_INBOUND_SECRET" in issue for issue in issues)
    finally:
        for key, value in previous.items():
            _restore_env(key, value)
