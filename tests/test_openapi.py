import json
from pathlib import Path

from app.db.repository import InMemoryScanRepository
from app.main import create_app

from .conftest import make_settings

SNAPSHOT = Path(__file__).resolve().parent.parent / "openapi.json"


def current_openapi() -> dict:
    return create_app(make_settings(), InMemoryScanRepository(), object(), configure_logs=False).openapi()


def test_openapi_exact_match():
    """The committed contract must match the implementation exactly.

    Regenerate with: python scripts/export_openapi.py
    """
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current_openapi() == expected


def test_openapi_required_paths():
    paths = set(current_openapi()["paths"])
    assert {
        "/healthz",
        "/readyz",
        "/health/ready",
        "/metrics",
        "/v1/capabilities",
        "/v1/documents/scan",
        "/v1/documents/{scan_id}",
        "/v1/documents/{scan_id}/confirm",
        "/v1/documents/{scan_id}/face-id-handoff",
    } <= paths
