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


@app.post("/api/updates/{row_id}/decide")
async def decide_update(row_id: int, payload: dict) -> Response:
    _require_config()
    decision = payload.get("decision")
    if decision not in ("approved", "dismissed"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'dismissed'")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{N8N_BASE_URL}/webhook/decide-update",
            headers={"X-Api-Key": N8N_API_KEY},
            json={"id": row_id, "decision": decision},
            timeout=15,
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)
