"""Tests for app/main.py: decide-group's per-id success reporting, request
validation, and the /api/updates proxy passthrough.

N8N_BASE_URL / N8N_API_KEY are read into module-level constants at import
time in app.main, so they must be set before that module is imported. See
the `app` fixture below.
"""

import os

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

os.environ["N8N_BASE_URL"] = "http://n8n.test"
os.environ["N8N_API_KEY"] = "test-key"

from app import main  # noqa: E402  (must follow the env var setup above)

N8N_BASE = "http://n8n.test"


@pytest.fixture
def client():
    return TestClient(main.app)


def decide_body(**overrides):
    body = {"app_name": "beszel", "host": "piguard", "ids": [1, 2], "decision": "approved"}
    body.update(overrides)
    return body


# ---- decide-group: success / partial / failure reporting (W2) ----


@respx.mock
def test_decide_group_happy_path_all_updated(client):
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(
        return_value=httpx.Response(200, json={"updated_ids": [1, 2], "decision": "approved"})
    )
    resp = client.post("/api/updates/decide-group", json=decide_body())
    assert resp.status_code == 200
    assert resp.json() == {"succeeded": [1, 2], "failed": []}


@respx.mock
def test_decide_group_partial_updated_ids(client):
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(
        return_value=httpx.Response(200, json={"updated_ids": [1], "decision": "approved"})
    )
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 2, 3]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == [1]
    assert body["failed"] == [2, 3]


@respx.mock
def test_decide_group_2xx_without_updated_ids_falls_back_to_all_succeeded(client):
    # Old n8n workflow, pre-contract-change: 2xx with no updated_ids field at all.
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(return_value=httpx.Response(200, json={"ok": True}))
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 2]))
    assert resp.status_code == 200
    assert resp.json() == {"succeeded": [1, 2], "failed": []}


@respx.mock
def test_decide_group_upstream_400_surfaces_reason_nothing_succeeds(client):
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(
        return_value=httpx.Response(400, json={"error": "row(s) not pending: [2]"})
    )
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 2]))
    assert resp.status_code == 400
    assert resp.json() == {"error": "row(s) not pending: [2]"}


@respx.mock
def test_decide_group_upstream_5xx_normalized_to_502(client):
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(return_value=httpx.Response(500))
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 2]))
    assert resp.status_code == 502
    assert "error" in resp.json()


@respx.mock
def test_decide_group_network_error_all_failed(client):
    respx.post(f"{N8N_BASE}/webhook/decide-group").mock(side_effect=httpx.ConnectError("boom"))
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 2]))
    assert resp.status_code == 200
    assert resp.json() == {"succeeded": [], "failed": [1, 2]}


# ---- request validation (W3) ----


def test_validation_rejects_empty_ids(client):
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[]))
    assert resp.status_code == 422


def test_validation_rejects_bad_decision(client):
    resp = client.post("/api/updates/decide-group", json=decide_body(decision="maybe"))
    assert resp.status_code == 422


def test_validation_rejects_missing_host(client):
    body = decide_body()
    del body["host"]
    resp = client.post("/api/updates/decide-group", json=body)
    assert resp.status_code == 422


def test_validation_rejects_empty_host(client):
    resp = client.post("/api/updates/decide-group", json=decide_body(host=""))
    assert resp.status_code == 422


def test_validation_rejects_extra_fields(client):
    resp = client.post("/api/updates/decide-group", json=decide_body(bogus="field"))
    assert resp.status_code == 422


@respx.mock
def test_validation_dedupes_ids_before_forwarding(client):
    route = respx.post(f"{N8N_BASE}/webhook/decide-group").mock(
        return_value=httpx.Response(200, json={"updated_ids": [1, 2], "decision": "approved"})
    )
    resp = client.post("/api/updates/decide-group", json=decide_body(ids=[1, 1, 2]))
    assert resp.status_code == 200
    forwarded = route.calls.last.request
    import json as _json

    sent_ids = _json.loads(forwarded.content)["ids"]
    assert sent_ids == [1, 2]


# ---- /api/updates proxy passthrough ----


@respx.mock
def test_get_updates_proxies_n8n_response(client):
    respx.get(f"{N8N_BASE}/webhook/pending-updates").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "app_name": "beszel"}])
    )
    resp = client.get("/api/updates")
    assert resp.status_code == 200
    assert resp.json() == [{"id": 1, "app_name": "beszel"}]


@respx.mock
def test_get_updates_passes_through_upstream_status(client):
    respx.get(f"{N8N_BASE}/webhook/pending-updates").mock(return_value=httpx.Response(503, json={"error": "down"}))
    resp = client.get("/api/updates")
    assert resp.status_code == 503
