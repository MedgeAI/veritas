#!/usr/bin/env bash
# Entrypoint for the ELIS forensic provenance service.
# Runs inside the conda 'provenance' environment.
set -euo pipefail

exec uvicorn api_wrapper:app --host 0.0.0.0 --port 8771 --log-level info
