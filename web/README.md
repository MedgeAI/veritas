# Veritas Web

This is the first Web audit flow. The backend is stdlib Python. The frontend reuses the Vite/React/Tailwind infrastructure pattern from `third_party/elis/system_modules/elis-frontend`, but uses Veritas-specific product flows and visual language.

## Backend

```bash
PYTHONPATH=. python3 -m web.backend.veritas_web.app
```

Default URL:

```text
http://127.0.0.1:8765
```

## Frontend

```bash
cd web/frontend
npm install
npm run dev
```

Default frontend URL:

```text
http://127.0.0.1:5173
```

Vite proxies `/api` to `http://127.0.0.1:8765`. For a one-process demo, run `npm run build` in `web/frontend`; the Python backend will serve `web/frontend/dist` if it exists.

## Real Audit Path

The backend calls `engine.static_audit.orchestrator.run_static_audit()` directly. It does not enable fake MinerU or fake LLM behavior.

Current runner mode is `thread`:

- Closing the browser tab does not stop a running audit as long as the backend process stays alive.
- Stopping the backend process interrupts the running audit thread.
- On backend startup, stale `queued` / `running` runs are marked `failed` with `error=interrupted_by_backend_restart`, and a `runner_interrupted` event is appended.
- The frontend polls `/api/health` and shows an offline banner when the backend is unreachable.

Required local environment:

```bash
MINERU_API_TOKEN=...
DASHSCOPE_API_KEY=...
opencode --version
```

## Minimal API Flow

Create a case:

```bash
curl -s -X POST http://127.0.0.1:8765/api/cases \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"paper-web-demo","paper_title":"Paper Web Demo"}'
```

Upload a PDF as base64 JSON:

```bash
PDF_B64=$(base64 -w 0 input/paper1/*.pdf)
curl -s -X POST http://127.0.0.1:8765/api/cases/paper-web-demo/inputs \
  -H 'Content-Type: application/json' \
  -d "{\"filename\":\"paper.pdf\",\"content_base64\":\"$PDF_B64\"}"
```

Start a real audit:

```bash
curl -s -X POST http://127.0.0.1:8765/api/cases/paper-web-demo/runs \
  -H 'Content-Type: application/json' \
  -d '{"agent_mode":"review","fresh":true,"force":true,"agent_timeout_seconds":300,"agent_max_retries":1}'
```

Poll events:

```bash
curl -s http://127.0.0.1:8765/api/cases/paper-web-demo/runs/<run_id>/events
```

Open the final report:

```text
http://127.0.0.1:8765/api/cases/paper-web-demo/report/html
```
