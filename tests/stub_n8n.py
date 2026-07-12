"""DEV-ONLY stub of the two n8n webhooks, for local end-to-end testing.

Run: uv run --with fastapi --with uvicorn uvicorn tests.stub_n8n:app --port 8099
Then point the real app at it: N8N_BASE_URL=http://127.0.0.1:8099 N8N_API_KEY=dev ...

Implements GET /webhook/pending-updates and POST /webhook/decide-update over
in-memory fixtures, including a multi-container group (beszel) and a single-row
app (gotify). Set fail id 3 to exercise the partial-failure path.
"""

from fastapi import FastAPI, Request, Response

app = FastAPI()

# id 3 (beszel-agent) always fails, to exercise decide-group partial failure.
FAIL_IDS = {3}

ROWS = [
    {"id": 1, "app_name": "beszel", "service_name": "socket-proxy", "install_type": "portainer",
     "host": "piguard", "update_type": "digest_drift", "current_version": "1.0", "target_version": "1.1",
     "release_notes_source": "", "breaking": False, "severity": "minor", "confidence": 0.9,
     "summary": "socket-proxy digest drift", "reasoning": "new digest", "status": "pending"},
    {"id": 2, "app_name": "beszel", "service_name": "beszel", "install_type": "portainer",
     "host": "piguard", "update_type": "tag_bump", "current_version": "0.9", "target_version": "0.10",
     "release_notes_source": "", "breaking": True, "severity": "major", "confidence": 0.8,
     "summary": "beszel core tag bump", "reasoning": "minor release", "status": "pending"},
    {"id": 3, "app_name": "beszel", "service_name": "beszel-agent", "install_type": "portainer",
     "host": "piguard", "update_type": "tag_bump", "current_version": "0.9", "target_version": "0.10",
     "release_notes_source": "", "breaking": False, "severity": "none", "confidence": 0.8,
     "summary": "beszel-agent tag bump", "reasoning": "", "status": "pending"},
    {"id": 4, "app_name": "gotify", "service_name": "gotify", "install_type": "truenas",
     "host": "nas", "update_type": "catalog", "current_version": "2.5", "target_version": "2.6",
     "release_notes_source": "github", "breaking": False, "severity": "minor", "confidence": 0.95,
     "summary": "gotify catalog update", "reasoning": "routine", "status": "pending"},
]


@app.get("/webhook/pending-updates")
def pending():
    return [r for r in ROWS if r["status"] == "pending"]


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
