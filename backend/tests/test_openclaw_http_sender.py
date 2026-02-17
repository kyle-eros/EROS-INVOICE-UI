from __future__ import annotations

import io
import json
import socket
import urllib.error
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from invoicing_web.openclaw import HttpOpenClawSender, ProviderSendRequest


def _make_payload(
    *,
    contact_channel: str = "email",
    contact_target: str = "creator@example.com",
) -> ProviderSendRequest:
    return ProviderSendRequest(
        invoice_id="INV-001",
        creator_id="creator-001",
        creator_name="Test Creator",
        contact_channel=contact_channel,  # type: ignore[arg-type]
        contact_target=contact_target,
        currency="USD",
        amount_due=500.00,
        balance_due=250.00,
        due_date=date(2026, 3, 15),
    )


def _make_sender(
    *,
    base_url: str = "https://api.openclaw.test",
    api_key: str = "test-api-key-abc123",
    channels: set[str] | None = None,
) -> HttpOpenClawSender:
    return HttpOpenClawSender(
        base_url=base_url,
        api_key=api_key,
        channels=channels or {"email", "sms"},
    )


def _mock_response(body: dict[str, str], status: int = 200) -> MagicMock:
    """Create a mock HTTP response that works as a context manager."""
    response = MagicMock()
    response.status = status
    response.read.return_value = json.dumps(body).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_success(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_response({"message_id": "msg-123"})
    sender = _make_sender()
    payload = _make_payload()

    result = sender.send_friendly_reminder(payload, dry_run=False)

    assert result.status == "sent"
    assert result.provider_message_id == "msg-123"
    assert result.attempted_at.tzinfo == timezone.utc
    assert result.error_code is None
    assert result.error_message is None
    mock_urlopen.assert_called_once()

    # Verify the request was constructed correctly
    request_arg = mock_urlopen.call_args[0][0]
    assert request_arg.full_url == "https://api.openclaw.test/v1/messages/send"
    assert request_arg.get_header("Authorization") == "Bearer test-api-key-abc123"
    assert request_arg.get_header("Content-type") == "application/json"

    sent_body = json.loads(request_arg.data.decode("utf-8"))
    assert sent_body["channel"] == "email"
    assert sent_body["recipient"] == "creator@example.com"
    assert "Test Creator" in sent_body["message"]
    assert "250.00" in sent_body["message"]
    assert "2026-03-15" in sent_body["message"]
    assert sent_body["idempotency_key"].startswith("eros-INV-001-")


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_dry_run(mock_urlopen: MagicMock) -> None:
    sender = _make_sender()
    payload = _make_payload()

    result = sender.send_friendly_reminder(payload, dry_run=True)

    assert result.status == "dry_run"
    assert result.attempted_at.tzinfo == timezone.utc
    assert result.provider_message_id is None
    assert result.error_code is None
    mock_urlopen.assert_not_called()


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_channel_not_configured(mock_urlopen: MagicMock) -> None:
    sender = _make_sender(channels={"email"})
    payload = _make_payload(contact_channel="sms")

    result = sender.send_friendly_reminder(payload, dry_run=False)

    assert result.status == "failed"
    assert result.error_code == "channel_not_configured"
    assert "sms" in (result.error_message or "")
    mock_urlopen.assert_not_called()


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_http_500(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://api.openclaw.test/v1/messages/send",
        code=500,
        msg="Internal Server Error",
        hdrs={},  # type: ignore[arg-type]
        fp=None,
    )
    sender = _make_sender()
    payload = _make_payload()

    result = sender.send_friendly_reminder(payload, dry_run=False)

    assert result.status == "failed"
    assert result.error_code == "http_500"
    assert result.error_message is not None
    assert "500" in result.error_message


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_connection_error(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
    sender = _make_sender()
    payload = _make_payload()

    result = sender.send_friendly_reminder(payload, dry_run=False)

    assert result.status == "failed"
    assert result.error_code == "connection_error"
    assert result.error_message is not None
    assert "Connection" in result.error_message


@patch("invoicing_web.openclaw.urllib.request.urlopen")
def test_http_sender_timeout(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = socket.timeout("timed out")
    sender = _make_sender()
    payload = _make_payload()

    result = sender.send_friendly_reminder(payload, dry_run=False)

    assert result.status == "failed"
    assert result.error_code == "timeout"
    assert result.error_message is not None
    assert "timed out" in result.error_message


def test_http_sender_empty_base_url() -> None:
    with pytest.raises(ValueError, match="base_url must not be empty"):
        HttpOpenClawSender(
            base_url="",
            api_key="test-key",
            channels={"email"},
        )


def test_http_sender_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key must not be empty"):
        HttpOpenClawSender(
            base_url="https://api.openclaw.test",
            api_key="",
            channels={"email"},
        )
