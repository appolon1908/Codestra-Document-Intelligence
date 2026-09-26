from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import zlib
from collections.abc import Callable

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import Settings
from app.db.repository import InMemoryScanRepository, PostgresScanRepository
from app.main import create_app
from app.worker_client import HttpOcrWorker

INBOUND_TOKEN = "mw-v3-workload-token"
WORKER_TOKEN = "docintel-to-ocr-worker-token"
CALLER_USER_TOKEN = "end-user-jwt-should-never-be-forwarded"
DOC_NUMBER = "001-1234567-8"
MRZ_LINE = "IDDOM0011234567<<<<<<<<<<<<<<<"
ALLOWED_HOST = "consulta.jce.gob.do"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def make_png(width: int = 1200, height: int = 800) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 16)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def make_jpeg(width: int = 1200, height: int = 800) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xda" + struct.pack(">H", 2) + b"\x00" * 32 + b"\xff\xd9"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def worker_result(request: dict, **overrides) -> dict:
    digests = {
        img["side"]: hashlib.sha256(base64.b64decode(img["content_base64"])).hexdigest()
        for img in request["images"]
    }
    body = {
        "schema_ref": "codestra.ocr.extraction-result/v1",
        "request_id": request["request_id"],
        "worker": {"name": "codestra-ocr-workers", "version": "1.0.0", "engine": "test"},
        "document_type": request["document_type"],
        "country": request["country"],
        "fields": {
            "given_names": {
                "value": "MARIA ELENA",
                "confidence": 0.97,
                "source": "visual",
                "evidence": {"side": "front", "bbox": [0.1, 0.2, 0.5, 0.25]},
            },
            "surnames": {"value": "PEREZ GOMEZ", "confidence": 0.95, "source": "visual"},
            "date_of_birth": {"value": "1990-04-12", "confidence": 0.91, "source": "visual"},
            "document_number": {
                "value": DOC_NUMBER,
                "confidence": 0.88,
                "source": "visual",
                "evidence": {"side": "front", "bbox": [0.6, 0.1, 0.9, 0.15]},
            },
            "mrz_line_1": {"value": MRZ_LINE, "confidence": 0.8, "source": "mrz"},
        },
        "image_digests": digests,
        "quality": {"overall_confidence": 0.9, "warnings": []},
        "qr": {"present": True, "source_lookup_url": f"https://{ALLOWED_HOST}/verify?c=abc"},
        "portrait": {"detected": True, "side": "front"},
    }
    body.update(overrides)
    return body


class WorkerStub:
    """Programmable OCR worker behind a real httpx transport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responder: Callable[[dict], httpx.Response] = lambda req: httpx.Response(200, json=worker_result(req))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path != "/internal/v1/ocr/extract":
            # Any other outbound call (e.g. fetching a QR URL) is a test failure.
            raise AssertionError(f"unexpected outbound request to {request.url}")
        return self.responder(json.loads(request.content))

    @property
    def last_json(self) -> dict:
        return json.loads(self.requests[-1].content)


def make_settings(**overrides) -> Settings:
    env = {
        "INBOUND_SERVICE_TOKENS": INBOUND_TOKEN,
        "ALLOWED_WORKLOADS": "middleware-v3",
        "OCR_WORKER_URL": "http://ocr-workers.internal:8080",
        "OCR_WORKER_TOKEN": WORKER_TOKEN,
        "DOCUMENT_HASH_PEPPER": "test-pepper",
        "SOURCE_LOOKUP_ALLOWED_HOSTS": ALLOWED_HOST,
    }
    env.update(overrides)
    return Settings.from_env(env)


PG_URL = os.environ.get("TEST_DATABASE_URL")  # non-superuser app role (RLS enforced)
PG_ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", PG_URL)  # superuser, bypasses RLS for inspection
_BACKENDS = ["memory"] + (["postgres"] if PG_URL else [])


@pytest.fixture(scope="session")
def pg_repo():
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    repo = PostgresScanRepository(PG_URL)
    repo.migrate()
    repo.migrate()  # idempotent
    yield repo
    repo.close()


@pytest.fixture(params=_BACKENDS)
def repo(request):
    if request.param == "memory":
        return InMemoryScanRepository()
    pg = request.getfixturevalue("pg_repo")
    with pg._pool.connection() as conn:
        conn.execute("TRUNCATE document_scan_events, document_scans")
    return pg


@pytest.fixture
def worker_stub() -> WorkerStub:
    return WorkerStub()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings, repo, worker_stub):
    worker = HttpOcrWorker(
        settings.ocr_worker_url, settings.ocr_worker_token, 5, transport=httpx.MockTransport(worker_stub.handler)
    )
    app = create_app(settings, repo, worker, configure_logs=False)
    with TestClient(app) as c:
        yield c


def headers(tenant: str = "tenant-a", **extra) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {INBOUND_TOKEN}",
        "X-Codestra-Workload": "middleware-v3",
        "X-Tenant-ID": tenant,
        "X-Codestra-Actor": "operator:42",
    }
    h.update(extra)
    return h


def scan_body(**overrides) -> dict:
    body = {
        "document_type": "national_id",
        "country": "DO",
        "front_image_base64": b64(make_jpeg()),
        "back_image_base64": b64(make_png()),
    }
    body.update(overrides)
    return body


def dump_persisted(repo) -> str:
    """Everything this service has persisted, as one string."""
    if isinstance(repo, InMemoryScanRepository):
        return json.dumps({"rows": repo.all_rows(), "events": repo.events}, default=str)
    with psycopg.connect(PG_ADMIN_URL, row_factory=dict_row) as conn:
        conn.execute("SET search_path = docintel, public")
        rows = conn.execute(
            "SELECT (SELECT coalesce(json_agg(s), '[]') FROM document_scans s)::text AS scans,"
            " (SELECT coalesce(json_agg(e), '[]') FROM document_scan_events e)::text AS events"
        ).fetchone()
    return rows["scans"] + rows["events"]
