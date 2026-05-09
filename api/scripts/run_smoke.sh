#!/bin/bash
# Phase G.4 smoke test wrapper.
# .env is loaded by python-dotenv inside the script itself
# (avoids `*` cron lines being interpreted by the shell).
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
cd api
PYTHONPATH=. python scripts/smoke_estimate_pipeline.py "$@"
