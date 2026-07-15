"""Human-approval webpage for pending homelab app updates.

Serves a single HTML page listing rows from n8n's `pending_updates` Data Table
and proxies approve/dismiss decisions back to n8n. The n8n webhooks require a
shared-secret header (X-Api-Key); this backend holds that secret so the
browser never sees it.
"""

import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")


class DecideGroupRequest(BaseModel):
    """Body of POST /api/updates/decide-group. Extra fields are rejected so a
    stale/malformed client payload fails loudly instead of silently dropping
    fields n8n never sees."""

    model_config = ConfigDict(extra="forbid")

    app_name: str
    host: str
    ids: list[int]
    decision: Literal["approved", "dismissed"]

    @field_validator("app_name", "host")
    @classmethod
    def _non_empty_str(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("ids")
    @classmethod
    def _non_empty_deduped_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("ids must be a non-empty list")
        deduped = list(dict.fromkeys(v))
        return deduped

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
async def decide_group(payload: DecideGroupRequest) -> Response:
    """Apply one decision to every row in a stack group, in a single call.

    Body: {"app_name": <str>, "host": <str>, "ids": [<int>, ...], "decision": "approved"|"dismissed"}
    (validated by DecideGroupRequest — non-empty app_name/host, non-empty
    deduplicated ids, decision in {approved, dismissed}, no extra fields; a
    violation 422s before this function body runs).
    app_name alone doesn't uniquely identify a stack (the same stack name can
    exist on two different hosts), so host travels alongside it end to end.
    A Portainer stack / TrueNAS app is updated as a whole, so its rows share one
    decision and — critically — one apply. We forward the whole group to n8n's
    `POST /webhook/decide-group`, which validates the group server-side (every
    id exists for that app_name+host, is still `status=pending`, shares one
    workflow_id, has a resolved digest and non-empty target_version when
    approving — dismiss is unconstrained) before mutating anything, then marks
    every id and dispatches at most ONE Apply Entry execution per stack (no
    per-row fan-out, so one approval click can never spawn N concurrent stack
    applies).

    n8n's success contract (2xx) is the *exact* ids it updated:
    `{"updated_ids": [...], "decision": ...}` — not necessarily all requested
    ids, so `succeeded`/`failed` here are computed against that list rather
    than assumed. If `updated_ids` is absent from an otherwise-2xx response
    (the n8n workflow hasn't been redeployed with the new contract yet), we
    fall back to treating every requested id as succeeded — this keeps the
    old all-or-nothing behavior for that transition window, so this page and
    the n8n workflow can be redeployed in either order without breaking.

    On a 4xx (validation rejected — e.g. a stale tab re-submitting an
    already-decided group, or an approve blocked by unresolved digest/version)
    nothing is recorded; the upstream status and `{"error": <reason>}` are
    passed straight through so the page can show n8n's actual reason instead
    of a generic message. A non-4xx error status from n8n is normalized to
    502. On a network-level failure talking to n8n, every id is reported
    failed. Failed rows reappear on the next fetch (the page re-fetches after
    every action).
    """
    _require_config()
    ids = payload.ids

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{N8N_BASE_URL}/webhook/decide-group",
                headers={"X-Api-Key": N8N_API_KEY},
                json={
                    "app_name": payload.app_name,
                    "host": payload.host,
                    "ids": ids,
                    "decision": payload.decision,
                },
                timeout=30,
            )
    except httpx.HTTPError:
        return JSONResponse(content={"succeeded": [], "failed": ids})

    if resp.is_success:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        updated_ids = body.get("updated_ids")
        if updated_ids is None:
            succeeded, failed = ids, []
        else:
            updated = set(updated_ids)
            succeeded = [i for i in ids if i in updated]
            failed = [i for i in ids if i not in updated]
        return JSONResponse(content={"succeeded": succeeded, "failed": failed})

    try:
        reason = resp.json().get("error")
    except ValueError:
        reason = None
    status_code = resp.status_code if 400 <= resp.status_code < 500 else 502
    return JSONResponse(
        content={"error": reason or "n8n rejected the request"},
        status_code=status_code,
    )
