#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        parsed = value.strip()
        if parsed and (parsed[0] == parsed[-1]) and parsed[0] in {'"', "'"}:
            parsed = parsed[1:-1]
        os.environ[key] = parsed


def _resolve_api_base_url(explicit_value: str | None) -> str:
    if explicit_value:
        candidate = explicit_value.strip()
    else:
        candidate = (
            os.getenv("DEMO_API_BASE_URL", "").strip()
            or os.getenv("INVOICING_API_BASE_URL", "").strip()
            or "http://localhost:8000"
        )
    if candidate.endswith("/api/v1/invoicing"):
        return candidate
    return f"{candidate.rstrip('/')}/api/v1/invoicing"


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        f"{base_url}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate creator passkeys via backend admin API, save results to DB, "
            "and export raw passkeys to a JSON file."
        )
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help=(
            "Backend base URL. Accepts either host root (e.g. http://localhost:8000) "
            "or full API prefix (e.g. http://localhost:8000/api/v1/invoicing)."
        ),
    )
    parser.add_argument(
        "--focus-year",
        type=int,
        default=int(os.getenv("DEMO_FOCUS_YEAR", datetime.now().year)),
        help="Year passed to /admin/creators?focus_year=YYYY (default: DEMO_FOCUS_YEAR or current year).",
    )
    parser.add_argument(
        "--only-ready",
        action="store_true",
        help="Generate passkeys only for creators where ready_for_portal=true.",
    )
    parser.add_argument(
        "--admin-password",
        default=None,
        help="Admin password. Defaults to ADMIN_PASSWORD from environment/.env.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Where to write JSON export. Defaults to ~/Desktop/creator_passkeys_<utc timestamp>.json.",
    )
    return parser.parse_args()


def main() -> int:
    root_dir = Path(__file__).resolve().parents[1]
    _load_dotenv(root_dir / ".env")
    args = parse_args()

    if args.focus_year < 2000 or args.focus_year > 2100:
        raise SystemExit("--focus-year must be between 2000 and 2100")

    api_base_url = _resolve_api_base_url(args.api_base_url)
    admin_password = (args.admin_password or os.getenv("ADMIN_PASSWORD", "")).strip()
    if not admin_password:
        raise SystemExit("ADMIN_PASSWORD is required (set .env or pass --admin-password)")

    login = _request_json(
        "POST",
        api_base_url,
        "admin/login",
        payload={"password": admin_password},
    )
    admin_token = str(login.get("session_token") or "")
    if not admin_token:
        raise SystemExit("admin login failed: missing session_token")

    directory = _request_json(
        "GET",
        api_base_url,
        f"admin/creators?focus_year={args.focus_year}",
        token=admin_token,
    )
    creators = directory.get("creators")
    if not isinstance(creators, list):
        raise SystemExit("invalid /admin/creators response: missing creators[]")

    selected_creators = creators
    if args.only_ready:
        selected_creators = [item for item in creators if bool(item.get("ready_for_portal"))]

    if not selected_creators:
        raise SystemExit("no creators selected for passkey generation")

    generated: list[dict[str, Any]] = []
    for creator in selected_creators:
        creator_id = str(creator.get("creator_id") or "").strip()
        creator_name = str(creator.get("creator_name") or "").strip()
        if not creator_id or not creator_name:
            continue

        response = _request_json(
            "POST",
            api_base_url,
            "passkeys/generate",
            payload={"creator_id": creator_id, "creator_name": creator_name},
            token=admin_token,
        )
        generated.append(
            {
                "creator_id": response["creator_id"],
                "creator_name": response["creator_name"],
                "passkey": response["passkey"],
                "display_prefix": response["display_prefix"],
                "created_at": response["created_at"],
                "ready_for_portal": bool(creator.get("ready_for_portal")),
            }
        )

    if not generated:
        raise SystemExit("no passkeys generated (creators were missing creator_id/creator_name)")

    if args.output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = Path.home() / "Desktop" / f"creator_passkeys_{timestamp}.json"
    else:
        output_path = args.output_path.expanduser().resolve()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "api_base_url": api_base_url,
        "focus_year": args.focus_year,
        "only_ready": args.only_ready,
        "count": len(generated),
        "creators": generated,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(output_path, 0o600)

    print(f"Generated {len(generated)} passkeys and saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
