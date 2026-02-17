from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal, Protocol

from .models import ContactChannel

ProviderResultStatus = Literal["sent", "failed", "dry_run"]


@dataclass(frozen=True)
class ProviderSendRequest:
    invoice_id: str
    creator_id: str
    creator_name: str
    contact_channel: ContactChannel
    contact_target: str
    currency: str
    amount_due: float
    balance_due: float
    due_date: date


@dataclass(frozen=True)
class ProviderSendResult:
    status: ProviderResultStatus
    attempted_at: datetime
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class OpenClawSender(Protocol):
    def send_friendly_reminder(self, payload: ProviderSendRequest, *, dry_run: bool) -> ProviderSendResult: ...


class StubOpenClawSender:
    def __init__(self, *, enabled: bool, channel: str = "email") -> None:
        self._enabled = enabled
        self._channel = channel

    def send_friendly_reminder(self, payload: ProviderSendRequest, *, dry_run: bool) -> ProviderSendResult:
        attempted_at = datetime.now(timezone.utc)

        if dry_run:
            return ProviderSendResult(status="dry_run", attempted_at=attempted_at)

        if not self._enabled:
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code="openclaw_disabled",
                error_message="OpenClaw live delivery is disabled",
            )

        if payload.contact_channel != self._channel:
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code="channel_mismatch",
                error_message=f"Configured channel is {self._channel}",
            )

        if "fail" in payload.contact_target.lower():
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code="stub_delivery_failed",
                error_message="Stub sender forced failure for contact target",
            )

        message_id = f"stub-{payload.invoice_id}-{int(attempted_at.timestamp())}"
        return ProviderSendResult(status="sent", attempted_at=attempted_at, provider_message_id=message_id)


def mask_contact_target(contact_target: str, channel: ContactChannel) -> str:
    normalized = contact_target.strip()
    if not normalized:
        return "***"

    if channel == "email" and "@" in normalized:
        local, domain = normalized.split("@", 1)
        if len(local) <= 1:
            return f"*@{domain}"
        return f"{local[0]}***@{domain}"

    if channel == "sms":
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if len(digits) >= 4:
            return f"***{digits[-4:]}"

    if len(normalized) <= 4:
        return "*" * len(normalized)

    return f"{normalized[:2]}***{normalized[-2:]}"
