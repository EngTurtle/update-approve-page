# update-approve-page

A small FastAPI page for approving/dismissing pending homelab app updates. It
lists rows from the n8n `pending_updates` Data Table (populated by an n8n
pipeline that detects and LLM-reviews app updates) and lets a human approve or
dismiss each one. A separate n8n applier picks up `approved` rows later — this
page only records the decision.

## How it works

- `GET /` serves a single static HTML page (`app/static/index.html`, plain
  JS `fetch()`, no framework/build step).
- `GET /api/updates` proxies to the n8n webhook `GET /webhook/pending-updates`.
- `POST /api/updates/{id}/decide` proxies to `POST /webhook/decide-update`
  with `{"id": <id>, "decision": "approved" | "dismissed"}`.
- The n8n webhooks require a shared-secret `X-Api-Key` header. This backend
  holds that secret server-side (env var) so the browser never sees it and
  CORS never comes up.
- No auth on this page itself — it's expected to sit behind an existing
  reverse proxy that handles access control.

## Env vars

| Var | Description |
|---|---|
| `N8N_BASE_URL` | Base URL of the n8n instance, e.g. `https://n8n.piguard.engturtle.com` (no trailing slash, no `/webhook` suffix). |
| `N8N_API_KEY` | Shared-secret value matching the `X-Api-Key` check in the n8n `Update Approval API` workflow. |

## Run locally

```sh
uv sync
N8N_BASE_URL=https://n8n.piguard.engturtle.com N8N_API_KEY=your-key \
  uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/.

## n8n side

The n8n workflow **`Update Approval API`** exposes two webhooks:

- `GET /webhook/pending-updates` — returns pending rows from the
  `pending_updates` Data Table.
- `POST /webhook/decide-update` — body `{"id": <row id>, "decision": "approved" | "dismissed"}`,
  updates that row's `status` and `decided_at`.

Both endpoints check the same shared-secret `X-Api-Key` header via an IF node
inside the workflow. Set the real secret in two places:

1. In the n8n workflow's two "Check API Key" IF nodes (replace the
   `CHANGE_ME_API_KEY` placeholder with a real value).
2. In this app's `N8N_API_KEY` env var — must match exactly.

## Docker

```sh
docker build -t update-approve-page .
docker run -p 8000:8000 \
  -e N8N_BASE_URL=https://n8n.piguard.engturtle.com \
  -e N8N_API_KEY=your-key \
  update-approve-page
```

CI (`.github/workflows/build.yml`) builds and pushes the image to
`ghcr.io/<owner>/<repo>` on every push to `main`.
