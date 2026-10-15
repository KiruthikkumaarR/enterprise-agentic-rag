#!/usr/bin/env bash
# Start the Halvorsen Intelligence Portal (local only: http://127.0.0.1:8100).
# First run generates the company data, the user database and the search index (~1 minute).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f data/portal/portal.db ] || .venv/bin/python scripts/build_portal.py
echo "Portal: http://127.0.0.1:8100   (demo accounts: data/portal/demo_accounts.csv)"
exec .venv/bin/uvicorn portal.app:app --host 127.0.0.1 --port 8100
