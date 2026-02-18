#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SALES_CSV_DEFAULT="/Users/kylemerriman/EROS-CRM-TUI/eros-of-data/CB Daily Sales Report 2026 - February 2026.csv"
CREATOR_CSV_DEFAULT="/Users/kylemerriman/EROS-CRM-TUI/eros-of-data/Creator statistics report 2026:01:17 to 2026:02:15.csv"

SALES_CSV="${1:-${SALES_CSV_DEFAULT}}"
CREATOR_CSV="${2:-${CREATOR_CSV_DEFAULT}}"
OUTPUT_DIR="${CB_SEED_OUTPUT_DIR:-/tmp/cb-seed-flow}"
NOW_OVERRIDE="${CB_SEED_NOW_OVERRIDE:-2026-03-01T00:00:00Z}"
DISPATCH_EMAIL="${CB_SEED_DISPATCH_EMAIL:-kyle@erosops.com}"
DISPATCH_PHONE="${CB_SEED_DISPATCH_PHONE:-+15555550123}"

if [[ ! -f "${SALES_CSV}" ]]; then
  echo "error: sales csv not found: ${SALES_CSV}" >&2
  exit 1
fi

if [[ ! -f "${CREATOR_CSV}" ]]; then
  echo "error: creator csv not found: ${CREATOR_CSV}" >&2
  exit 1
fi

python3 "${ROOT_DIR}/scripts/seed_from_cb_reports.py" \
  --sales-csv "${SALES_CSV}" \
  --creator-csv "${CREATOR_CSV}" \
  --output-dir "${OUTPUT_DIR}" \
  --creator-override "grace bennett paid=grace bennett" \
  --now-override "${NOW_OVERRIDE}" \
  --dispatch-email "${DISPATCH_EMAIL}" \
  --dispatch-phone "${DISPATCH_PHONE}" \
  --run-live \
  --inject-scenario-pack \
  --simulate-payment-event

echo "cb seed flow completed. Artifacts: ${OUTPUT_DIR}"
