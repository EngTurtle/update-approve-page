"""Human-approval webpage for pending homelab app updates.

Serves a single HTML page listing rows from n8n's `pending_updates` Data Table
and proxies approve/dismiss decisions back to n8n. The n8n webhooks require a
shared-secret header (X-Api-Key); this backend holds that secret so the
browser never sees it.
"""

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Update Approval Page")


def _require_config() -> None:
    if not N8N_BASE_URL or not N8N_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="N8N_BASE_URL and N8N_API_KEY must be set",
        )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/updates")
async def get_updates() -> Response:
    _require_config()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{N8N_BASE_URL}/webhook/pending-updates",
            headers={"X-Api-Key": N8N_API_KEY},
            timeout=15,
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


async def _decide_one(client: httpx.AsyncClient, row_id: int, decision: str) -> bool:
    """POST a single decision to n8n. Returns True on success (2xx), else False."""
    try:
        resp = await client.post(
            f"{N8N_BASE_URL}/webhook/decide-update",
            headers={"X-Api-Key": N8N_API_KEY},
            json={"id": row_id, "decision": decision},
            timeout=15,
        )
        return resp.is_success
    except httpx.HTTPError:
        return False


@app.post("/api/updates/decide-group")
async def decide_group(payload: dict) -> Response:
    """Apply one decision to every row in a stack group.

    Body: {"app_name": <str>, "ids": [<int>, ...], "decision": "approved"|"dismissed"}.
    n8n decides one row per POST (fixed contract), so we fan out sequential POSTs
    here in Python and report which ids failed. A single-container group is just a
    one-element `ids` list. The page re-fetches after any action, so any rows whose
    decision failed simply reappear.
    """
    _require_config()
    decision = payload.get("decision")
    if decision not in ("approved", "dismissed"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'dismissed'")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")

    succeeded: list[int] = []
    failed: list[int] = []
    async with httpx.AsyncClient() as client:
        for row_id in ids:
            if await _decide_one(client, row_id, decision):
                succeeded.append(row_id)
            else:
                failed.append(row_id)

    return JSONResponse(content={"succeeded": succeeded, "failed": failed})
