from __future__ import annotations

import os

import pytest

from invoicing_web.main import create_app


def _set_env(overrides: dict[str, str | None]) -> dict[str, str | None]:
    previous: dict[str, str | None] = {}
    for key, value in overrides.items():
        previous[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _base_runtime_secret_env() -> dict[str, str]:
    return {
        "ADMIN_PASSWORD": "prod-admin-password-001",
        "ADMIN_SESSION_SECRET": "prod-admin-secret-001",
        "CREATOR_SESSION_SECRET": "prod-creator-secret-001",
        "BROKER_TOKEN_SECRET": "prod-broker-secret-001",
        "CREATOR_MAGIC_LINK_SECRET": "prod-creator-magic-secret-001",
        "RUNTIME_SECRET_GUARD_MODE": "enforce",
        "PAYMENT_WEBHOOK_SIGNATURE_MODE": "off",
        "CONVERSATION_ENABLED": "true",
        "CONVERSATION_WEBHOOK_SIGNATURE_MODE": "enforce",
    }


def test_create_app_starts_when_conversation_provider_flags_are_unset() -> None:
    previous = _set_env(
        {
            **_base_runtime_secret_env(),
            "CONVERSATION_PROVIDER_TWILIO_ENABLED": None,
            "CONVERSATION_PROVIDER_SENDGRID_ENABLED": None,
            "CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED": None,
            "TWILIO_AUTH_TOKEN": None,
            "SENDGRID_INBOUND_SECRET": None,
            "BLUEBUBBLES_WEBHOOK_SECRET": None,
        }
    )
    try:
        app = create_app()
        assert app.title == "EROS Invoicing Web"
    finally:
        _restore_env(previous)


def test_create_app_blocks_when_twilio_enabled_without_auth_token() -> None:
    previous = _set_env(
        {
            **_base_runtime_secret_env(),
            "CONVERSATION_PROVIDER_TWILIO_ENABLED": "true",
            "CONVERSATION_PROVIDER_SENDGRID_ENABLED": "false",
            "TWILIO_AUTH_TOKEN": None,
            "SENDGRID_INBOUND_SECRET": None,
            "BLUEBUBBLES_WEBHOOK_SECRET": None,
        }
    )
    try:
        with pytest.raises(RuntimeError) as exc_info:
            create_app()
        message = str(exc_info.value)
        assert "TWILIO_AUTH_TOKEN is required" in message
        assert "CONVERSATION_PROVIDER_*_ENABLED=false" in message
    finally:
        _restore_env(previous)
