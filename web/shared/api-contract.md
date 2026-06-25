# Veritas Web API Contract

This is the stdlib backend contract for the first Web audit flow.

## Cases

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`

## Inputs

- `POST /api/cases/{case_id}/inputs`

Multipart form-data upload (preferred):

```
Content-Type: multipart/form-data
file: <binary>
relative_path: "subdir/paper.pdf"  (optional)
```

Legacy JSON path (deprecated, 50MB limit):

```json
{
  "filename": "paper.pdf",
  "content_base64": "..."
}
```

## Runs

- `POST /api/audit` — submit a new audit job (single entry point)
- `GET /api/audit/{job_id}`
- `DELETE /api/audit/{job_id}` — cancel
- `GET /api/audit/{job_id}/stream` — SSE progress
- `GET /api/audit/queue` — queue status
- `GET /api/cases/{case_id}/runs/{run_id}`
- `GET /api/cases/{case_id}/runs/{run_id}/events`

Submit payload:

```json
{
  "case_id": "...",
  "options": {
    "agent_mode": "review",
    "fresh": true,
    "force": true,
    "no_env_file": false,
    "agent_timeout_seconds": 300,
    "agent_max_retries": 1
  }
}
```

The backend dispatches via Celery (when ``VERITAS_USE_CELERY`` is set) or
the thread-pool ``AuditRunner``.  It does not set fake Agent or fake MinerU
mode.

## Artifacts

- `GET /api/cases/{case_id}/artifacts`
- `GET /api/cases/{case_id}/artifacts/{artifact_id}`
- `GET /api/cases/{case_id}/report/html`

## Visual Evidence

- `GET /api/cases/{case_id}/visual/figures`
- `GET /api/cases/{case_id}/visual/panels`
- `GET /api/cases/{case_id}/visual/relationships`
- `GET /api/cases/{case_id}/visual/findings`
- `GET /api/cases/{case_id}/visual/images/{relative_path}`

## Manual Investigations

- `GET /api/cases/{case_id}/investigations`
- `POST /api/cases/{case_id}/investigations`

Manual investigation payloads are Tool Registry bounded. The first supported Web-triggered tool is `visual.copy_move_dense`; it requires explicit panel selection and enforces `max_panels`.

```json
{
  "tool_id": "visual.copy_move_dense",
  "panel_ids": ["figure-content-0004-01"],
  "params": {
    "min_score": 0.05,
    "max_relationships": 100,
    "max_panels": 20
  },
  "hypothesis": "Manual Web review of selected panels for dense copy-move candidates."
}
```

Results are written under `workdir/investigation/web/`, and a record is appended to `investigation/investigation_rounds.jsonl`.

## Frontend Serving

Development uses Vite under `web/frontend` and proxies `/api` to the stdlib backend.

If `web/frontend/dist/index.html` exists, the Python backend serves the built single-page app for non-`/api` routes.
