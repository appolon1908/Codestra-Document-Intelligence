import hashlib

import httpx
import pytest

from .conftest import (
    ALLOWED_HOST,
    CALLER_USER_TOKEN,
    DOC_NUMBER,
    WORKER_TOKEN,
    b64,
    dump_persisted,
    headers,
    make_jpeg,
    make_png,
    scan_body,
    worker_result,
)


def test_scan_happy_path(client, worker_stub):
    body = scan_body()
    r = client.post("/v1/documents/scan", json=body, headers=headers())
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["scan_id"].startswith("dscan_")
    assert data["tenant_id"] == "tenant-a"
    assert data["status"] == "pending_review"
    assert data["document_type"] == "national_id"
    assert data["country"] == "DO"
    assert data["created_at"] and data["confirmed_at"] is None
    assert data["verification"]["authenticity_verified"] is False
    assert "not government authenticity verification" in data["verification"]["disclaimer"]
    assert r.headers["Cache-Control"] == "no-store"

    front_sha = hashlib.sha256(make_jpeg()).hexdigest()
    back_sha = hashlib.sha256(make_png()).hexdigest()
    assert {i["side"]: i["sha256"] for i in data["images"]} == {"front": front_sha, "back": back_sha}
    assert data["images"][0]["media_type"] == "image/jpeg"
    assert data["images"][0]["width"] == 1200 and data["images"][0]["height"] == 800

    assert data["fields"]["given_names"]["value"] == "MARIA ELENA"
    assert data["fields"]["given_names"]["evidence"]["bbox"] == [0.1, 0.2, 0.5, 0.25]
    num = data["fields"]["document_number"]
    assert num["redacted"] is True and num["value_persisted"] is False
    assert num["value"] == DOC_NUMBER  # transient echo for operator review only
    assert num["last4"] == "5678" and num["masked_value"] == "****5678"
    assert data["document"]["number_last4"] == "5678"
    assert data["document"]["document_hash"].startswith("hmac-sha256:")
    assert data["portrait_detected"] is True
    assert data["worker"] == {
        "name": "codestra-ocr-workers",
        "version": "1.0.0",
        "schema_ref": "codestra.ocr.extraction-result/v1",
    }

    sent = worker_stub.last_json
    assert sent["schema_ref"] == "codestra.ocr.extract-request/v1"
    assert sent["expected_response_schema_ref"] == "codestra.ocr.extraction-result/v1"
    assert sent["tenant_id"] == "tenant-a"
    assert [i["sha256"] for i in sent["images"]] == [front_sha, back_sha]


def test_front_only_scan(client, worker_stub):
    r = client.post("/v1/documents/scan", json=scan_body(back_image_base64=None), headers=headers())
    assert r.status_code == 201, r.text
    assert [i["side"] for i in r.json()["images"]] == ["front"]


def test_data_url_prefix_accepted(client):
    body = scan_body(front_image_base64="data:image/jpeg;base64," + b64(make_jpeg()))
    assert client.post("/v1/documents/scan", json=body, headers=headers()).status_code == 201


def test_worker_receives_service_token_not_caller_token(client, worker_stub):
    h = headers(Authorization=f"Bearer {CALLER_USER_TOKEN}")
    # Caller credentials that are not a valid workload token are rejected outright ...
    assert client.post("/v1/documents/scan", json=scan_body(), headers=h).status_code == 401
    assert worker_stub.requests == []
    # ... and valid calls reach the worker with this service's own token only.
    extra = {"X-Forwarded-Authorization": f"Bearer {CALLER_USER_TOKEN}", "Cookie": "session=abc"}
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers(**extra))
    assert r.status_code == 201
    req = worker_stub.requests[-1]
    assert req.headers["Authorization"] == f"Bearer {WORKER_TOKEN}"
    assert CALLER_USER_TOKEN not in str(req.headers)
    assert "cookie" not in req.headers
    assert "x-tenant-id" not in req.headers
    assert str(req.url) == "http://ocr-workers.internal:8080/v1/ocr/extract"


@pytest.mark.parametrize(
    ("front", "code"),
    [
        ("not base64!!", "image_not_base64"),
        (b64(b"GIF89a" + b"\x00" * 100), "image_unsupported_format"),
        (b64(make_jpeg(100, 80)), "image_too_small"),
        (b64(make_png(9000, 1000)), "image_dimensions_exceeded"),
        (b64(make_png(7000, 7000)), "image_dimensions_exceeded"),
        (b64(b"\xff\xd8\xff\xe0garbage"), "image_unsupported_format"),
    ],
)
def test_invalid_image_rejected(client, worker_stub, repo, front, code):
    r = client.post("/v1/documents/scan", json=scan_body(front_image_base64=front), headers=headers())
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == code
    assert worker_stub.requests == []
    assert "dscan_" not in dump_persisted(repo)


def test_image_byte_limit(settings, repo, worker_stub):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.worker_client import HttpOcrWorker

    from .conftest import make_settings

    small = make_settings(MAX_IMAGE_BYTES="50")
    worker = HttpOcrWorker(
        small.ocr_worker_url, small.ocr_worker_token, 5, transport=httpx.MockTransport(worker_stub.handler)
    )
    with TestClient(create_app(small, repo, worker, configure_logs=False)) as c:
        r = c.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "image_too_large"


def test_invalid_back_image(client, worker_stub):
    r = client.post("/v1/documents/scan", json=scan_body(back_image_base64=b64(b"nope")), headers=headers())
    assert r.status_code == 422
    assert "back" in r.json()["error"]["message"]


def test_validation_errors_never_echo_input(client):
    r = client.post("/v1/documents/scan", json=scan_body(country="dominican"), headers=headers())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "request_invalid"
    assert b64(make_jpeg()) not in r.text
    assert "dominican" not in r.text


def test_tenant_in_body_is_rejected(client):
    r = client.post("/v1/documents/scan", json=scan_body(tenant_id="tenant-b"), headers=headers())
    assert r.status_code == 422


def test_unsupported_document_type(client):
    r = client.post("/v1/documents/scan", json=scan_body(document_type="library_card"), headers=headers())
    assert r.status_code == 422


@pytest.mark.parametrize(
    "responder",
    [
        lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda req: httpx.Response(503, json={"error": "overloaded"}),
        lambda req: httpx.Response(500),
        lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
    ids=["connect-error", "503", "500", "timeout"],
)
def test_worker_unavailable(client, worker_stub, repo, responder):
    worker_stub.responder = responder
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 503, r.text
    err = r.json()["error"]
    assert err["code"] == "ocr_worker_unavailable"
    scan_id = err["scan_id"]
    got = client.get(f"/v1/documents/{scan_id}", headers=headers())
    assert got.status_code == 200
    assert got.json()["status"] == "failed"
    assert got.json()["fields"] == {}


def test_worker_not_configured(repo):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.worker_client import HttpOcrWorker

    from .conftest import make_settings

    s = make_settings(OCR_WORKER_URL="")
    with TestClient(create_app(s, repo, HttpOcrWorker(None, None, 1), configure_logs=False)) as c:
        r = c.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 503


@pytest.mark.parametrize(
    "mutate",
    [
        lambda req: worker_result(req, schema_ref="codestra.ocr.extraction-result/v2"),
        lambda req: {k: v for k, v in worker_result(req).items() if k != "fields"},
        lambda req: worker_result(req, unexpected="x"),
        lambda req: worker_result(req, quality={"overall_confidence": 1.7}),
        lambda req: worker_result(req, fields={"Bad-Name": {"value": "x", "confidence": 0.5}}),
        lambda req: worker_result(req, request_id="someone-elses-request"),
        lambda req: worker_result(req, image_digests={"front": "0" * 64}),
        lambda req: ["not", "an", "object"],
    ],
    ids=[
        "wrong-version",
        "missing-fields",
        "extra-prop",
        "confidence-range",
        "bad-field-name",
        "request-id-mismatch",
        "digest-mismatch",
        "not-object",
    ],
)
def test_worker_schema_mismatch(client, worker_stub, mutate):
    worker_stub.responder = lambda req: httpx.Response(200, json=mutate(req))
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 502, r.text
    err = r.json()["error"]
    assert err["code"] == "ocr_worker_schema_mismatch"
    assert err["scan_id"]
    assert client.get(f"/v1/documents/{err['scan_id']}", headers=headers()).json()["status"] == "failed"


def test_worker_non_json(client, worker_stub):
    worker_stub.responder = lambda req: httpx.Response(200, content=b"<html>")
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "ocr_worker_schema_mismatch"


def test_worker_rejects_request(client, worker_stub):
    worker_stub.responder = lambda req: httpx.Response(400, json={"error": "bad"})
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "ocr_worker_error"


def test_source_lookup_allowlisted_transient_never_fetched(client, worker_stub, repo):
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    lookup = r.json()["source_lookup"]
    assert lookup["allowlisted"] is True
    assert lookup["url"] == f"https://{ALLOWED_HOST}/verify?c=abc"
    assert lookup["fetched"] is False and lookup["persisted"] is False
    assert len(worker_stub.requests) == 1  # only the OCR call; the QR URL was never fetched
    assert "verify?c=abc" not in dump_persisted(repo)
    got = client.get(f"/v1/documents/{r.json()['scan_id']}", headers=headers()).json()
    assert got["source_lookup"] is None
    assert got["qr_present"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/verify",
        f"http://{ALLOWED_HOST}/verify",
        f"https://user:pw@{ALLOWED_HOST}/verify",
        f"https://{ALLOWED_HOST}:8443/verify",
        f"https://{ALLOWED_HOST}.evil.com/verify",
        "javascript:alert(1)",
    ],
)
def test_source_lookup_not_allowlisted_dropped(client, worker_stub, url):
    worker_stub.responder = lambda req: httpx.Response(
        200, json=worker_result(req, qr={"present": True, "source_lookup_url": url})
    )
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 201
    assert r.json()["source_lookup"]["allowlisted"] is False
    assert r.json()["source_lookup"]["url"] is None
    assert len(worker_stub.requests) == 1


def test_document_type_mismatch_warning(client, worker_stub):
    worker_stub.responder = lambda req: httpx.Response(200, json=worker_result(req, document_type="passport"))
    r = client.post("/v1/documents/scan", json=scan_body(), headers=headers())
    assert r.status_code == 201
    assert "worker_document_type_mismatch" in r.json()["quality"]["warnings"]


def test_idempotent_scan_replay(client, worker_stub):
    h = headers(**{"Idempotency-Key": "client-key-0001"})
    first = client.post("/v1/documents/scan", json=scan_body(), headers=h)
    assert first.status_code == 201
    replay = client.post("/v1/documents/scan", json=scan_body(), headers=h)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["scan_id"] == first.json()["scan_id"]
    assert replay.json()["fields"]["document_number"]["value"] is None  # no transient echo on replay
    assert len(worker_stub.requests) == 1
    # Same key, different images -> conflict. Same key in another tenant -> independent.
    other = client.post("/v1/documents/scan", json=scan_body(back_image_base64=None), headers=h)
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "idempotency_key_reused"
    tb = client.post("/v1/documents/scan", json=scan_body(), headers={**h, "X-Tenant-ID": "tenant-b"})
    assert tb.status_code == 201 and tb.json()["scan_id"] != first.json()["scan_id"]


def test_failed_scan_does_not_hold_idempotency_key(client, worker_stub):
    h = headers(**{"Idempotency-Key": "client-key-0002"})
    worker_stub.responder = lambda req: httpx.Response(503)
    assert client.post("/v1/documents/scan", json=scan_body(), headers=h).status_code == 503
    worker_stub.responder = lambda req: httpx.Response(200, json=worker_result(req))
    assert client.post("/v1/documents/scan", json=scan_body(), headers=h).status_code == 201
