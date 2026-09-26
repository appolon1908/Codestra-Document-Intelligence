from fastapi.testclient import TestClient

from app.config import Settings
from app.db.repository import InMemoryScanRepository
from app.main import create_app
from app.worker_client import HttpOcrWorker

from .conftest import make_settings


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Request-ID"]


def test_ready_endpoints(client):
    for path in ("/readyz", "/health/ready"):
        r = client.get(path)
        assert r.status_code == 200, r.text
        assert r.json() == {
            "status": "ready",
            "checks": {"database": True, "ocr_worker_binding": True, "workload_auth": True},
        }


def test_not_ready_without_worker_binding():
    settings = Settings.from_env({"INBOUND_SERVICE_TOKENS": "x"})
    app = create_app(settings, InMemoryScanRepository(), HttpOcrWorker(None, None, 1), configure_logs=False)
    with TestClient(app) as c:
        r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["ocr_worker_binding"] is False


def test_metrics_exposed(client):
    client.get("/healthz")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "docintel_http_requests_total" in r.text
    assert "docintel_ocr_worker_requests_total" in r.text


def test_capabilities_states_intake_aid_only(client):
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticity_verification"] is False
    assert "not government authenticity verification" in body["disclaimer"]
    assert body["raw_image_persistence"] is False
    assert body["source_lookup_auto_fetch"] is False
    assert body["ocr_worker_schema_refs"]["response"] == "codestra.ocr.extraction-result/v1"
    assert body["face_id_handoff_schema_ref"] == "codestra.document.face-id-handoff/v1"


def test_request_id_propagated(client):
    r = client.get("/healthz", headers={"X-Request-ID": "req-123"})
    assert r.headers["X-Request-ID"] == "req-123"


def test_production_requires_pepper():
    import pytest

    from app.config import ConfigError

    with pytest.raises(ConfigError):
        Settings.from_env({"APP_ENV": "production"})
    assert make_settings().document_hash_pepper == "test-pepper"


def test_secret_file_reference(tmp_path):
    token_file = tmp_path / "worker-token"
    token_file.write_text("from-file\n")
    s = Settings.from_env({"OCR_WORKER_TOKEN_FILE": str(token_file), "OCR_WORKER_TOKEN": "ignored"})
    assert s.ocr_worker_token == "from-file"
