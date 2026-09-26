import psycopg
import pytest

from .conftest import INBOUND_TOKEN, PG_URL, headers, scan_body


def _scan(client, tenant):
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers(tenant))
    assert r.status_code == 201, r.text
    return r.json()["scan_id"]


def test_no_cross_tenant_read(client):
    scan_a = _scan(client, "tenant-a")
    assert client.get(f"/v1/documents/{scan_a}", headers=headers("tenant-a")).status_code == 200
    r = client.get(f"/v1/documents/{scan_a}", headers=headers("tenant-b"))
    assert r.status_code == 404
    # Indistinguishable from a scan that does not exist.
    missing = client.get("/v1/documents/dscan_missing", headers=headers("tenant-b"))
    assert r.json()["error"] == missing.json()["error"]


def test_no_cross_tenant_confirm_or_handoff(client):
    scan_a = _scan(client, "tenant-a")
    assert client.post(f"/v1/documents/{scan_a}/confirm", json={}, headers=headers("tenant-b")).status_code == 404
    assert client.get(f"/v1/documents/{scan_a}/face-id-handoff", headers=headers("tenant-b")).status_code == 404
    # tenant-a's scan is untouched
    assert client.get(f"/v1/documents/{scan_a}", headers=headers("tenant-a")).json()["status"] == "pending_review"


def test_tenant_from_header_only(client):
    scan = client.post("/v1/documents/scan", json=scan_body(), headers=headers("tenant-z")).json()
    assert scan["tenant_id"] == "tenant-z"
    r = client.get(f"/v1/documents/{scan['scan_id']}?tenant_id=tenant-a", headers=headers("tenant-a"))
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("mutate", "status", "code"),
    [
        (lambda h: h.pop("X-Tenant-ID"), 400, "tenant_required"),
        (lambda h: h.update({"X-Tenant-ID": "../etc"}), 400, "tenant_invalid"),
        (lambda h: h.update({"X-Tenant-ID": "a" * 65}), 400, "tenant_invalid"),
        (lambda h: h.pop("Authorization"), 401, "missing_workload_token"),
        (lambda h: h.update({"Authorization": "Bearer wrong"}), 401, "invalid_workload_token"),
        (lambda h: h.update({"Authorization": f"Basic {INBOUND_TOKEN}"}), 401, "missing_workload_token"),
        (lambda h: h.pop("X-Codestra-Workload"), 403, "workload_not_allowed"),
        (lambda h: h.update({"X-Codestra-Workload": "some-other-service"}), 403, "workload_not_allowed"),
    ],
)
def test_workload_identity_enforced(client, worker_stub, mutate, status, code):
    h = headers()
    mutate(h)
    for method, path, kwargs in (
        ("post", "/v1/documents/scan", {"json": scan_body()}),
        ("get", "/v1/documents/dscan_x", {}),
        ("post", "/v1/documents/dscan_x/confirm", {"json": {}}),
        ("get", "/v1/documents/dscan_x/face-id-handoff", {}),
    ):
        r = getattr(client, method)(path, headers=h, **kwargs)
        assert r.status_code == status, (path, r.text)
        assert r.json()["error"]["code"] == code
    assert worker_stub.requests == []


def test_auth_not_configured_fails_closed(repo, worker_stub):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import make_settings

    s = make_settings(INBOUND_SERVICE_TOKENS="")
    with TestClient(create_app(s, repo, object(), configure_logs=False)) as c:
        r = c.get("/v1/documents/dscan_x", headers=headers())
    assert r.status_code == 503


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set")
def test_postgres_row_level_security_blocks_cross_tenant(client, repo):
    from app.db.repository import PostgresScanRepository

    if not isinstance(repo, PostgresScanRepository):
        pytest.skip("postgres backend only")
    scan_a = _scan(client, "tenant-a")
    with psycopg.connect(PG_URL) as conn:
        # Even a query with no tenant predicate sees nothing for another tenant.
        conn.execute("SELECT set_config('app.tenant_id', 'tenant-b', false)")
        assert conn.execute("SELECT count(*) FROM document_scans").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM document_scan_events").fetchone()[0] == 0
        conn.execute("SELECT set_config('app.tenant_id', 'tenant-a', false)")
        assert conn.execute("SELECT scan_id FROM document_scans").fetchall() == [(scan_a,)]
        # And writes into another tenant are refused.
        conn.execute("SELECT set_config('app.tenant_id', 'tenant-b', false)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO document_scans (scan_id, tenant_id, request_id, document_type, country, status)"
                " VALUES ('dscan_x', 'tenant-a', 'r', 'passport', 'DO', 'failed')"
            )



def test_recent_list_is_tenant_scoped_and_paginated(client):
    a1 = _scan(client, "tenant-a")
    a2 = _scan(client, "tenant-a")
    _scan(client, "tenant-b")

    first = client.get("/v1/documents?limit=1", headers=headers("tenant-a"))
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["scan_id"] in {a1, a2}
    assert body["next_cursor"]

    second = client.get(
        f"/v1/documents?limit=1&cursor={body['next_cursor']}",
        headers=headers("tenant-a"),
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["scan_id"] in {a1, a2}
    assert second_body["items"][0]["scan_id"] != body["items"][0]["scan_id"]
    assert all(item["scan_id"] in {a1, a2} for item in body["items"] + second_body["items"])


def test_recent_list_rejects_cross_tenant_cursor(client):
    cursor = _scan(client, "tenant-a")
    r = client.get(f"/v1/documents?cursor={cursor}", headers=headers("tenant-b"))
    assert r.status_code == 200
    assert r.json() == {"items": [], "next_cursor": None}
