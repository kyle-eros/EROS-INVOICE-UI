from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
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
        normalized = channel.strip().lower()
        if not normalized:
            self._channels = {"email", "sms", "imessage"}
        else:
            parsed = {item.strip() for item in normalized.split(",") if item.strip()}
            self._channels = parsed or {"email", "sms", "imessage"}

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

        if payload.contact_channel not in self._channels:
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code="channel_mismatch",
                error_message=f"Configured channels are {', '.join(sorted(self._channels))}",
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


class _OpenClawSendError(Exception):
    """Internal error raised when an OpenClaw HTTP request fails."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class HttpOpenClawSender:
    """Production OpenClaw sender that delivers messages via HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        channels: set[str],
        timeout_seconds: int = 30,
    ) -> None:
        stripped_url = base_url.strip().rstrip("/")
        stripped_key = api_key.strip()
        if not stripped_url:
            raise ValueError("base_url must not be empty")
        if not stripped_key:
            raise ValueError("api_key must not be empty")
        self._base_url = stripped_url
        self._api_key = stripped_key
        self._channels: frozenset[str] = frozenset(channels)
        self._timeout_seconds = timeout_seconds

    def send_friendly_reminder(
        self, payload: ProviderSendRequest, *, dry_run: bool
    ) -> ProviderSendResult:
        attempted_at = datetime.now(timezone.utc)

        if dry_run:
            return ProviderSendResult(status="dry_run", attempted_at=attempted_at)

        if payload.contact_channel not in self._channels:
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code="channel_not_configured",
                error_message=(
                    f"Channel '{payload.contact_channel}' is not configured; "
                    f"available channels: {', '.join(sorted(self._channels))}"
                ),
            )

        message_body = (
            f"Hi {payload.creator_name}, this is a friendly reminder that your "
            f"{payload.currency} {payload.balance_due:.2f} balance is due on "
            f"{payload.due_date.isoformat()}. Please submit payment at your earliest "
            f"convenience."
        )

        idempotency_key = f"eros-{payload.invoice_id}-{int(attempted_at.timestamp())}"

        request_payload = {
            "channel": payload.contact_channel,
            "recipient": payload.contact_target,
            "message": message_body,
            "idempotency_key": idempotency_key,
        }

        try:
            response_data = self._post(request_payload)
            message_id = response_data.get("message_id")
            return ProviderSendResult(
                status="sent",
                attempted_at=attempted_at,
                provider_message_id=message_id,
            )
        except _OpenClawSendError as exc:
            masked = mask_contact_target(
                payload.contact_target, payload.contact_channel
            )
            return ProviderSendResult(
                status="failed",
                attempted_at=attempted_at,
                error_code=exc.error_code,
                error_message=f"{exc.message} (recipient: {masked})",
            )

    def _post(self, body: dict[str, str]) -> dict[str, str]:
        """Send a POST request to the OpenClaw messages endpoint."""
        url = f"{self._base_url}/v1/messages/send"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            raise _OpenClawSendError(
                error_code=f"http_{exc.code}",
                message=f"HTTP {exc.code}: {exc.reason}",
            ) from exc
        except urllib.error.URLError as exc:
            raise _OpenClawSendError(
                error_code="connection_error",
                message=f"Connection error: {exc.reason}",
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise _OpenClawSendError(
                error_code="timeout",
                message=f"Request timed out: {exc}",
            ) from exc


def mask_contact_target(contact_target: str, channel: ContactChannel) -> str:
    normalized = contact_target.strip()
    if not normalized:
        return "***"

    if channel == "email" and "@" in normalized:
        local, domain = normalized.split("@", 1)
        if len(local) <= 1:
            return f"*@{domain}"
        return f"{local[0]}***@{domain}"

    if channel in {"sms", "imessage"}:
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if len(digits) >= 4:
            return f"***{digits[-4:]}"

    if len(normalized) <= 4:
        return "*" * len(normalized)

    return f"{normalized[:2]}***{normalized[-2:]}"
