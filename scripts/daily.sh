#!/usr/bin/env bash
# Daily pipeline run. Intended for cron/systemd; see README.md ("Corrida diaria").
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

{
  echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) run_pipeline start ---"
  .venv/bin/python run_pipeline.py
  exit_code=$?
  echo "--- exit code: ${exit_code} ---"
} >> logs/daily.log 2>&1

exit "${exit_code}"
