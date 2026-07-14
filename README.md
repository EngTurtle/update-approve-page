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
- `POST /api/updates/decide-group` — body
  `{"app_name": <str>, "ids": [<id>, ...], "decision": "approved" | "dismissed"}`.
  Forwards the whole group as a single `POST /webhook/decide-group` to n8n, which
  marks every id and dispatches **at most one Apply Entry execution per stack** —
  so one approval click never fans out into N concurrent stack applies (the
  applier re-reads and bundles all approved rows for the stack itself). Returns
  `{"succeeded": [...], "failed": [...]}` for the frontend; the grouped call is
  atomic from the page's view (2xx ⇒ all ids recorded, else none). The page
  groups pending rows by `app_name` (stack) and calls this once per group; a
  single-container app is just a one-element `ids` list. Failed rows reappear on
  the next fetch (the page re-fetches after every action).
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

The n8n workflow **`Update Approval API`** exposes three webhooks:

- `GET /webhook/pending-updates` — returns pending rows from the
  `pending_updates` Data Table.
- `POST /webhook/decide-group` — body
  `{"app_name": <str>, "ids": [<id>, ...], "decision": "approved" | "dismissed"}`.
  Marks every id's `status`/`decided_at`/`decided_by`, then (on approval)
  dispatches one Apply Entry execution per distinct `workflow_id` in the group
  (normally one, since a group is one stack). This is the path the page uses.
- `POST /webhook/decide-update` — legacy single-row path, body
  `{"id": <row id>, "decision": "approved" | "dismissed"}`, updates that row's
  `status` and `decided_at`. Retained for compatibility; the page no longer
  calls it.

All endpoints check the same shared-secret `X-Api-Key` header (webhook
header-auth credential). Set the real secret in two places:

1. In the n8n `Update Approval API` workflow's webhook header-auth credential.
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
