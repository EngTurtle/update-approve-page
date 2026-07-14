"""DEV-ONLY stub of the two n8n webhooks, for local end-to-end testing.

Run: uv run --with fastapi --with uvicorn uvicorn tests.stub_n8n:app --port 8099
Then point the real app at it: N8N_BASE_URL=http://127.0.0.1:8099 N8N_API_KEY=dev ...

Implements GET /webhook/pending-updates, POST /webhook/decide-group (the grouped
per-stack path the page uses), and the legacy POST /webhook/decide-update, over
in-memory fixtures with a multi-container group (beszel) and a single-row app
(gotify). id 3 is in FAIL_IDS: a group containing it fails atomically (whole
group 500s and reappears), exercising the group-failure path.

decide-group mirrors the real n8n workflow's server-side validation: every
supplied id must exist for the given app_name+host, be status=pending, and
share one workflow_id, or the call 400s with a reason and mutates nothing
(also covers the "two stacks with the same app_name, different host" case and
the "stale tab re-submits an already-decided group" case).
"""

from fastapi import FastAPI, Request, Response

app = FastAPI()

# id 3 (beszel-agent) always fails, to exercise decide-group partial failure.
FAIL_IDS = {3}

ROWS = [
    {"id": 1, "app_name": "beszel", "service_name": "socket-proxy", "install_type": "portainer",
     "host": "piguard", "update_type": "digest_drift", "current_version": "1.0", "target_version": "1.1",
     "release_notes_source": "", "breaking": False, "severity": "minor", "confidence": 0.9,
     "summary": "socket-proxy digest drift", "reasoning": "new digest", "status": "pending",
     "workflow_id": "wf-beszel"},
    {"id": 2, "app_name": "beszel", "service_name": "beszel", "install_type": "portainer",
     "host": "piguard", "update_type": "tag_bump", "current_version": "0.9", "target_version": "0.10",
     "release_notes_source": "", "breaking": True, "severity": "major", "confidence": 0.8,
     "summary": "beszel core tag bump", "reasoning": "minor release", "status": "pending",
     "workflow_id": "wf-beszel"},
    {"id": 3, "app_name": "beszel", "service_name": "beszel-agent", "install_type": "portainer",
     "host": "piguard", "update_type": "tag_bump", "current_version": "0.9", "target_version": "0.10",
     "release_notes_source": "", "breaking": False, "severity": "none", "confidence": 0.8,
     "summary": "beszel-agent tag bump", "reasoning": "", "status": "pending",
     "workflow_id": "wf-beszel"},
    {"id": 4, "app_name": "gotify", "service_name": "gotify", "install_type": "truenas",
     "host": "nas", "update_type": "catalog", "current_version": "2.5", "target_version": "2.6",
     "release_notes_source": "github", "breaking": False, "severity": "minor", "confidence": 0.95,
     "summary": "gotify catalog update", "reasoning": "routine", "status": "pending",
     "workflow_id": "wf-gotify"},
    # Same app_name as row 4 (gotify) but a different host and workflow_id, to
    # exercise the app_name+host grouping fix (F3a/F3b) — these must never be
    # merged into row 4's group.
    {"id": 5, "app_name": "gotify", "service_name": "gotify", "install_type": "portainer",
     "host": "piguard", "update_type": "digest_drift", "current_version": "2.5", "target_version": "2.6",
     "release_notes_source": "", "breaking": False, "severity": "minor", "confidence": 0.9,
     "summary": "gotify digest drift on piguard", "reasoning": "", "status": "pending",
     "workflow_id": "wf-gotify-piguard"},
]


@app.get("/webhook/pending-updates")
def pending():
    return [r for r in ROWS if r["status"] == "pending"]


@app.post("/webhook/decide-group")
async def decide_group(request: Request):
    """Validate then mark every id in the group atomically, mirroring the real
    n8n workflow: fetch candidate rows for app_name+host, reject (400, mutate
    nothing) unless every supplied id exists in that set, is status=pending,
    and all share one workflow_id. Also preserves the legacy FAIL_IDS 500 path
    (simulates a dispatch failure after rows are already marked)."""
    body = await request.json()
    app_name = body.get("app_name")
    host = body.get("host")
    ids = body.get("ids") or []
    decision = body.get("decision")

    candidates = {r["id"]: r for r in ROWS if r["app_name"] == app_name and r["host"] == host}

    missing = [i for i in ids if i not in candidates]
    if missing:
        return Response(
            status_code=400,
            content=f'{{"error": "unknown id(s) for {app_name}/{host}: {missing}"}}',
            media_type="application/json",
        )

    not_pending = [i for i in ids if candidates[i]["status"] != "pending"]
    if not_pending:
        return Response(
            status_code=400,
            content=f'{{"error": "row(s) not pending: {not_pending}"}}',
            media_type="application/json",
        )

    workflow_ids = {candidates[i]["workflow_id"] for i in ids}
    if len(workflow_ids) != 1:
        return Response(
            status_code=400,
            content=f'{{"error": "rows in group have differing workflow_id: {sorted(workflow_ids)}"}}',
            media_type="application/json",
        )

    if any(i in FAIL_IDS for i in ids):
        return Response(status_code=500)

    for r in ROWS:
        if r["id"] in ids:
            r["status"] = decision
    return {"ok": True, "ids": ids, "decision": decision}


@app.post("/webhook/decide-update")
async def decide(request: Request):
    body = await request.json()
    row_id = body.get("id")
    if row_id in FAIL_IDS:
        return Response(status_code=500)
    for r in ROWS:
        if r["id"] == row_id:
            r["status"] = body.get("decision")
    return {"ok": True, "id": row_id}
