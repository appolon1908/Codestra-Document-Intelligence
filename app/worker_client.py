"""Outbound binding to Codestra-OCR-Workers (private network only).

The worker is authenticated with this service's own token, loaded from a
secret file reference. The caller's credentials are never forwarded.
"""

from __future__ import annotations

import time
from typing import Protocol

import httpx

from . import metrics
from .contracts import EXTRACTION_RESULT_SCHEMA_REF, schema_errors
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
    # OCR Workers is a private, standalone execution service. Tenant identity remains
    # owned by Document Intelligence and is intentionally not forwarded to the worker.
    return {
        "request_id": request_id,
        "document_type": document_type,
        "country": country,
        "schema_version": "1.0.0",
        "images": [
            {
                "side": img.side,
                "media_type": img.media_type,
                "content_base64": img.content_base64,
            }
            for img in images
        ],
        "options": {"decode_qr": True},
    }


def _normalise_native_worker_response(
    body: dict, *, request_id: str, images: list[ValidatedImage]
) -> dict:
    if body.get("request_id") != request_id:
        raise WorkerSchemaMismatch("worker response request_id mismatch", ["/request_id: binding"])
    if body.get("status") not in {"succeeded", "partial"}:
        raise WorkerSchemaMismatch("worker response status is invalid", ["/status"])

    engine = body.get("engine")
    fields = body.get("fields")
    if not isinstance(engine, dict) or not isinstance(fields, dict):
        raise WorkerSchemaMismatch("worker response is missing engine/fields")

    normalised_fields: dict[str, dict] = {}
    confidences: list[float] = []
    for name, item in fields.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise WorkerSchemaMismatch("worker field payload is invalid", [f"/fields/{name}"])
        value = item.get("value")
        if value is not None and not isinstance(value, str):
            value = str(value)
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        confidence = max(0.0, min(float(confidence), 1.0))
        if item.get("status") != "missing":
            confidences.append(confidence)
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else None
        source = "qr" if evidence and evidence.get("method") == "qr" else "visual"
        field = {"value": value, "confidence": confidence, "source": source}
        if evidence and evidence.get("side") in {"front", "back"}:
            field["evidence"] = {"side": evidence["side"]}
        normalised_fields[name] = field

    sent = {img.side: img.sha256 for img in images}
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    warning_codes = [
        str(w.get("code"))
        for w in warnings
        if isinstance(w, dict) and isinstance(w.get("code"), str)
    ]
    qr = body.get("qr") if isinstance(body.get("qr"), dict) else {}
    native_schema = body.get("schema") if isinstance(body.get("schema"), dict) else {}
    worker_version = str(native_schema.get("version") or "1.0.0")
    engine_name = str(engine.get("name") or "unknown")
    engine_version = str(engine.get("version") or "unknown")
    normalised = {
        "schema_ref": EXTRACTION_RESULT_SCHEMA_REF,
        "request_id": request_id,
        "worker": {
            "name": "codestra-ocr-workers",
            "version": worker_version,
            "engine": f"{engine_name}:{engine_version}",
        },
        "document_type": body.get("document_type"),
        "country": body.get("country"),
        "fields": normalised_fields,
        "image_digests": sent,
        "quality": {
            "overall_confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
            "warnings": warning_codes,
        },
        "qr": {
            "present": bool(qr.get("detected")),
            "source_lookup_url": qr.get("authority_url") if qr.get("allowlisted") else None,
        },
        "portrait": {"detected": False},
    }
    return normalised


def validate_worker_response(body: object, *, request_id: str, images: list[ValidatedImage]) -> dict:
    if not isinstance(body, dict):
        raise WorkerSchemaMismatch("worker response is not a JSON object")

    # Accept the repository's canonical native OCR Worker contract and normalise it
    # into Document Intelligence's private persistence contract. The legacy internal
    # shape remains accepted temporarily for compatibility with existing test fixtures.
    if "schema_ref" not in body and "schema" in body:
        body = _normalise_native_worker_response(body, request_id=request_id, images=images)

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
                    f"{self._base_url}/internal/v1/ocr/extract", json=payload, headers=self._headers(request_id)
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
