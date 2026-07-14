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


@app.post("/api/updates/decide-group")
async def decide_group(payload: dict) -> Response:
    """Apply one decision to every row in a stack group, in a single call.

    Body: {"app_name": <str>, "ids": [<int>, ...], "decision": "approved"|"dismissed"}.
    A Portainer stack / TrueNAS app is updated as a whole, so its rows share one
    decision and — critically — one apply. We forward the whole group to n8n's
    `POST /webhook/decide-group`, which marks every id and dispatches at most ONE
    Apply Entry execution per stack (no per-row fan-out, so one approval click can
    never spawn N concurrent stack applies). The grouped call is atomic from the
    page's view: 2xx ⇒ all ids recorded, otherwise none. Failed rows reappear on
    the next fetch (the page re-fetches after every action). `{succeeded, failed}`
    response shape is kept for the frontend.
    """
    _require_config()
    decision = payload.get("decision")
    if decision not in ("approved", "dismissed"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'dismissed'")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")
    app_name = payload.get("app_name")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{N8N_BASE_URL}/webhook/decide-group",
                headers={"X-Api-Key": N8N_API_KEY},
                json={"app_name": app_name, "ids": ids, "decision": decision},
                timeout=30,
            )
        ok = resp.is_success
    except httpx.HTTPError:
        ok = False

    if ok:
        return JSONResponse(content={"succeeded": ids, "failed": []})
    return JSONResponse(content={"succeeded": [], "failed": ids})
