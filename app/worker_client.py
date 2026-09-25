"""Outbound binding to Codestra-OCR-Workers (private network only).

The worker is authenticated with this service's own token, loaded from a
secret file reference. The caller's credentials are never forwarded.
"""

from __future__ import annotations

import time
from typing import Protocol

import httpx

from . import metrics
from .contracts import EXTRACT_REQUEST_SCHEMA_REF, EXTRACTION_RESULT_SCHEMA_REF, schema_errors
from .images import ValidatedImage


class WorkerError(RuntimeError):
    code = "ocr_worker_error"


class WorkerUnavailable(WorkerError):
    code = "ocr_worker_unavailable"


class WorkerSchemaMismatch(WorkerError):
    code = "ocr_worker_schema_mismatch"

    def __init__(self, message: str, violations: list[str] | None = None):
        super().__init__(message)
        self.violations = violations or []


class OcrWorker(Protocol):
    def extract(
        self,
        *,
        request_id: str,
        tenant_id: str,
        document_type: str,
        country: str,
        images: list[ValidatedImage],
    ) -> dict: ...

    def ready(self) -> bool: ...


def build_extract_request(
    *, request_id: str, tenant_id: str, document_type: str, country: str, images: list[ValidatedImage]
) -> dict:
    return {
        "schema_ref": EXTRACT_REQUEST_SCHEMA_REF,
        "request_id": request_id,
        "tenant_id": tenant_id,
        "document_type": document_type,
        "country": country,
        "expected_response_schema_ref": EXTRACTION_RESULT_SCHEMA_REF,
        "images": [
            {
                "side": img.side,
                "media_type": img.media_type,
                "sha256": img.sha256,
                "content_base64": img.content_base64,
            }
            for img in images
        ],
    }


def validate_worker_response(body: object, *, request_id: str, images: list[ValidatedImage]) -> dict:
    if not isinstance(body, dict):
        raise WorkerSchemaMismatch("worker response is not a JSON object")
    ref = body.get("schema_ref")
    if ref != EXTRACTION_RESULT_SCHEMA_REF:
        raise WorkerSchemaMismatch(
            f"unsupported worker schema_ref; expected {EXTRACTION_RESULT_SCHEMA_REF}", ["/schema_ref: const"]
        )
    violations = schema_errors(EXTRACTION_RESULT_SCHEMA_REF, body)
    if violations:
        raise WorkerSchemaMismatch("worker response failed schema validation", violations)
    if body["request_id"] != request_id:
        raise WorkerSchemaMismatch("worker response request_id mismatch", ["/request_id: binding"])
    sent = {img.side: img.sha256 for img in images}
    if body["image_digests"] != sent:
        raise WorkerSchemaMismatch("worker response image digests do not match request", ["/image_digests"])
    return body


class HttpOcrWorker:
    def __init__(self, base_url: str | None, token: str | None, timeout: float, transport=None):
        self._base_url = base_url
        self._token = token
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def ready(self) -> bool:
        return bool(self._base_url and self._token)

    def extract(self, *, request_id, tenant_id, document_type, country, images) -> dict:
        if not self._base_url or not self._token:
            raise WorkerUnavailable("OCR worker binding is not configured")
        payload = build_extract_request(
            request_id=request_id,
            tenant_id=tenant_id,
            document_type=document_type,
            country=country,
            images=images,
        )
        started = time.perf_counter()
        outcome = "error"
        try:
            try:
                resp = self._client.post(
                    f"{self._base_url}/v1/ocr/extract", json=payload, headers=self._headers(request_id)
                )
            except httpx.HTTPError as exc:
                outcome = "unavailable"
                raise WorkerUnavailable("OCR worker unreachable") from exc
            if resp.status_code >= 500 or resp.status_code in (408, 429):
                outcome = "unavailable"
                raise WorkerUnavailable(f"OCR worker returned HTTP {resp.status_code}")
            if resp.status_code != 200:
                outcome = "rejected"
                raise WorkerError(f"OCR worker rejected request with HTTP {resp.status_code}")
            try:
                body = resp.json()
            except ValueError as exc:
                outcome = "schema_mismatch"
                raise WorkerSchemaMismatch("worker response is not JSON") from exc
            try:
                result = validate_worker_response(body, request_id=request_id, images=images)
            except WorkerSchemaMismatch:
                outcome = "schema_mismatch"
                raise
            outcome = "ok"
            return result
        finally:
            metrics.WORKER_REQUESTS.labels(outcome=outcome).inc()
            metrics.WORKER_LATENCY.observe(time.perf_counter() - started)

    def close(self) -> None:
        self._client.close()
