import base64
import logging

import httpx

from .conftest import DOC_NUMBER, MRZ_LINE, b64, dump_persisted, headers, make_jpeg, make_png, scan_body


def _scan(client, **kw):
    r = client.post("/v1/documents/scan", json=scan_body(**kw), headers=headers())
    assert r.status_code == 201, r.text
    return r.json()


def test_get_scan_masks_sensitive_number(client):
    created = _scan(client)
    r = client.get(f"/v1/documents/{created['scan_id']}", headers=headers())
    assert r.status_code == 200
    data = r.json()
    assert data["fields"]["document_number"]["value"] is None
    assert data["fields"]["document_number"]["masked_value"] == "****5678"
    assert data["fields"]["mrz_line_1"]["value"] is None
    assert data["fields"]["mrz_line_1"]["redacted"] is True
    assert data["fields"]["given_names"]["value"] == "MARIA ELENA"
    assert DOC_NUMBER not in r.text and "12345678" not in r.text and MRZ_LINE not in r.text


def test_operator_confirm_with_corrections(client, repo):
    created = _scan(client)
    scan_id = created["scan_id"]
    corrected_number = "402-9876543-1"
    r = client.post(
        f"/v1/documents/{scan_id}/confirm",
        json={
            "corrections": {
                "given_names": "MARIA ELENA",
                "surnames": "PÉREZ GÓMEZ",
                "document_number": corrected_number,
                "nationality": "DOM",
            }
        },
        headers=headers(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "confirmed"
    assert data["confirmed_at"] is not None
    assert data["corrected_fields"] == ["document_number", "given_names", "nationality", "surnames"]
    assert data["fields"]["surnames"] == {
        "value": "PÉREZ GÓMEZ",
        "confidence": 1.0,
        "source": "operator",
        "evidence": None,
        "redacted": False,
        "masked_value": None,
        "last4": None,
        "value_persisted": True,
    }
    assert data["fields"]["nationality"]["value"] == "DOM"
    num = data["fields"]["document_number"]
    assert num["value"] is None and num["last4"] == "5431" and num["source"] == "operator"
    assert num["evidence"]["side"] == "front"  # original evidence retained
    assert data["document"]["number_last4"] == "5431"
    assert data["document"]["document_hash"] != created["document"]["document_hash"]
    assert corrected_number not in r.text and "98765431" not in r.text

    persisted = dump_persisted(repo)
    assert corrected_number not in persisted and "98765431" not in persisted
    assert DOC_NUMBER not in persisted and "00112345678" not in persisted

    again = client.get(f"/v1/documents/{scan_id}", headers=headers()).json()
    assert again["status"] == "confirmed"
    assert again["fields"]["surnames"]["value"] == "PÉREZ GÓMEZ"


def test_confirm_without_corrections(client):
    created = _scan(client)
    r = client.post(f"/v1/documents/{created['scan_id']}/confirm", json={}, headers=headers())
    assert r.status_code == 200
    assert r.json()["corrected_fields"] == []
    assert r.json()["document"]["document_hash"] == created["document"]["document_hash"]


def test_confirm_twice_conflicts(client):
    scan_id = _scan(client)["scan_id"]
    assert client.post(f"/v1/documents/{scan_id}/confirm", json={}, headers=headers()).status_code == 200
    r = client.post(f"/v1/documents/{scan_id}/confirm", json={}, headers=headers())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "scan_not_confirmable"


def test_failed_scan_not_confirmable(client, worker_stub):
    worker_stub.responder = lambda req: httpx.Response(503)
    scan_id = client.post("/v1/documents/scan", json=scan_body(), headers=headers()).json()["error"]["scan_id"]
    r = client.post(f"/v1/documents/{scan_id}/confirm", json={}, headers=headers())
    assert r.status_code == 409


def test_confirm_rejects_bad_field_names(client):
    scan_id = _scan(client)["scan_id"]
    r = client.post(f"/v1/documents/{scan_id}/confirm", json={"corrections": {"Bad Name": "x"}}, headers=headers())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_field_name"


def test_confirm_unknown_scan(client):
    r = client.post("/v1/documents/dscan_doesnotexist/confirm", json={}, headers=headers())
    assert r.status_code == 404


def test_no_raw_image_persistence(client, repo):
    front, back = make_jpeg(1600, 1000), make_png(1600, 1000)
    created = _scan(client, front_image_base64=b64(front), back_image_base64=b64(back))
    client.post(f"/v1/documents/{created['scan_id']}/confirm", json={}, headers=headers())
    persisted = dump_persisted(repo)
    for raw in (front, back):
        encoded = base64.b64encode(raw).decode()
        # Neither the base64 payload nor any sizeable slice of it is stored.
        assert encoded not in persisted
        assert encoded[16:80] not in persisted
        assert raw.hex()[:64] not in persisted
    assert "content_base64" not in persisted
    # Only digests and descriptors are kept.
    assert created["images"][0]["sha256"] in persisted


def test_sensitive_values_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    created = _scan(client)
    client.post(
        f"/v1/documents/{created['scan_id']}/confirm",
        json={"corrections": {"document_number": "402-9876543-1"}},
        headers=headers(),
    )
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "scan_created" in text and "scan_confirmed" in text
    for secret in (DOC_NUMBER, "402-9876543-1", MRZ_LINE, "MARIA ELENA", b64(make_jpeg())[:40]):
        assert secret not in text


def test_hash_is_tenant_scoped(client):
    a = _scan(client)["document"]["document_hash"]
    b = client.post("/v1/documents/scan", json=scan_body(), headers=headers("tenant-b")).json()
    assert b["document"]["number_last4"] == "5678"
    assert b["document"]["document_hash"] != a
