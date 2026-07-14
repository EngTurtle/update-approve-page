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
  `{"app_name": <str>, "host": <str>, "ids": [<id>, ...], "decision": "approved" | "dismissed"}`.
  `app_name` alone doesn't uniquely identify a stack — the same stack name can
  exist on two different hosts (e.g. a test stack deployed to both `nas` and
  `piguard`) — so the page groups pending rows by `app_name` + `host` and
  sends both. Forwards the whole group as a single `POST /webhook/decide-group`
  to n8n, which validates server-side before mutating anything (every id must
  exist for that app_name+host, be `status=pending`, and share one
  `workflow_id`; a stale browser tab re-submitting an already-decided group
  gets rejected here) then marks every id and dispatches **at most one Apply
  Entry execution per stack**, using the validated `workflow_id` — so one
  approval click never fans out into N concurrent stack applies, and a
  rejected group never partially dispatches. Returns
  `{"succeeded": [...], "failed": [...], "reason": <str | null>}` for the
  frontend (`reason` set when n8n's validation rejected the group); the
  grouped call is atomic from the page's view (2xx ⇒ all ids recorded, else
  none). A single-container app is just a one-element `ids` list. Failed rows
  reappear on the next fetch (the page re-fetches after every action).
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
  `{"app_name": <str>, "host": <str>, "ids": [<id>, ...], "decision": "approved" | "dismissed"}`.
  Fetches the candidate rows for that `app_name`+`host`, then rejects with 400
  (`{"error": <reason>}`, nothing mutated) unless every supplied id exists in
  that set, is `status=pending`, and all share one `workflow_id`. On success,
  marks every id's `status`/`decided_at`/`decided_by` (the update itself is
  additionally filtered on `status=pending`, closing the race window between
  the validation read and the write), then on approval dispatches once using
  the validated `workflow_id`. If that dispatch throws (e.g. stale/unpublished
  `workflow_id`), the rows stay approved (the webhook has already responded)
  and a Discord alert fires so the stuck rows don't go unnoticed. This is the
  path the page uses.
- `POST /webhook/decide-update` — legacy single-row path, body
  `{"id": <row id>, "decision": "approved" | "dismissed"}`, updates that row's
  `status` and `decided_at`. Retained for compatibility; the page no longer
  calls it. Its apply dispatch gets the same Discord alert-on-failure as
  `decide-group`.

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
