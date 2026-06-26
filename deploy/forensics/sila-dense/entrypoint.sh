#!/usr/bin/env bash
# Entrypoint for the SILA dense detection service.
# Starts uvicorn with the FastAPI app.
set -euo pipefail

exec uvicorn app:app --host 0.0.0.0 --port 8770 --log-level info
