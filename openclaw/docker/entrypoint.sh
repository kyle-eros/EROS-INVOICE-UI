#!/bin/sh
set -eu

OPENCLAW_HOME_DIR="${OPENCLAW_HOME_DIR:-/home/openclaw/.openclaw}"
OPENCLAW_CONFIG_SOURCE="${OPENCLAW_CONFIG:-/app/config/openclaw.json}"
OPENCLAW_CONFIG_TARGET="$OPENCLAW_HOME_DIR/openclaw.json"

mkdir -p "$OPENCLAW_HOME_DIR"
if [ -f "$OPENCLAW_CONFIG_SOURCE" ]; then
  cp "$OPENCLAW_CONFIG_SOURCE" "$OPENCLAW_CONFIG_TARGET"
fi

exec /bin/sh -lc "${OPENCLAW_GATEWAY_CMD:-openclaw gateway --allow-unconfigured --bind loopback --port 8080}"
