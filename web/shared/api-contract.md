# Veritas Web API Contract

This is the stdlib backend contract for the first Web audit flow.

## Cases

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`

## Inputs

- `POST /api/cases/{case_id}/inputs`

Payload:

```json
{
  "filename": "paper.pdf",
  "content_base64": "..."
}
```

## Runs

- `POST /api/cases/{case_id}/runs`
- `GET /api/cases/{case_id}/runs/{run_id}`
- `GET /api/cases/{case_id}/runs/{run_id}/events`

Run payload defaults to the real `audit-paper` path:

```json
{
  "agent_mode": "review",
  "fresh": true,
  "force": true,
  "no_env_file": false,
  "agent_timeout_seconds": 300,
  "agent_max_retries": 1
}
```

The backend calls `engine.static_audit.orchestrator.run_static_audit()` directly.
It does not set fake Agent or fake MinerU mode.

## Artifacts

- `GET /api/cases/{case_id}/artifacts`
- `GET /api/cases/{case_id}/artifacts/{artifact_id}`
- `GET /api/cases/{case_id}/report/html`

## Frontend Serving

Development uses Vite under `web/frontend` and proxies `/api` to the stdlib backend.

If `web/frontend/dist/index.html` exists, the Python backend serves the built single-page app for non-`/api` routes.
