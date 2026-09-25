"""Scan orchestration: intake -> OCR worker -> protect -> persist."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from . import metrics
from .config import Settings
from .contracts import EXTRACTION_RESULT_SCHEMA_REF, FACE_ID_HANDOFF_SCHEMA_REF
from .db.repository import ConfirmConflict, DuplicateIdempotencyKey, ScanRecord, ScanRepository
from .images import InvalidImage, ValidatedImage, decode_and_validate
from .models import (
    ConfirmRequest,
    DocumentIdentity,
    ExtractedField,
    FaceIdDocumentRef,
    FaceIdHandoff,
    FaceIdSubjectHint,
    ImageDescriptor,
    Quality,
    ScanRequest,
    ScanResponse,
    SourceLookup,
    WorkerInfo,
)
from .protection import (
    is_hash_only_field,
    is_number_field,
    mask,
    primary_number,
    protect_field,
    protect_fields,
)
from .security import WorkloadIdentity
from .worker_client import OcrWorker, WorkerError, WorkerSchemaMismatch, WorkerUnavailable

log = logging.getLogger("docintel.scan")

_FIELD_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def new_scan_id() -> str:
    return "dscan_" + secrets.token_urlsafe(18)


def now() -> datetime:
    return datetime.now(UTC)


def evaluate_source_lookup(url: str | None, allowed_hosts: tuple[str, ...]) -> SourceLookup | None:
    """Allowlist check only. The URL is never fetched and never persisted."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        metrics.SOURCE_LOOKUP.labels(decision="malformed").inc()
        return SourceLookup(allowlisted=False, url=None, host=None)
    ok = (
        parts.scheme == "https"
        and bool(host)
        and host in allowed_hosts
        and parts.username is None
        and parts.password is None
        and port in (None, 443)
    )
    metrics.SOURCE_LOOKUP.labels(decision="allowlisted" if ok else "rejected").inc()
    return SourceLookup(allowlisted=ok, url=url if ok else None, host=host or None)


class ScanService:
    def __init__(self, settings: Settings, repo: ScanRepository, worker: OcrWorker):
        self.settings = settings
        self.repo = repo
        self.worker = worker

    # ---- rendering -------------------------------------------------------

    @staticmethod
    def _render_fields(stored: dict, transient: dict | None = None) -> dict[str, ExtractedField]:
        out: dict[str, ExtractedField] = {}
        for name, f in stored.items():
            redacted = bool(f.get("redacted"))
            value = f.get("value")
            persisted = True
            if redacted:
                value = None
                persisted = False
                if transient is not None and name in transient:
                    value = transient[name].get("value")
            out[name] = ExtractedField(
                value=value,
                confidence=f.get("confidence", 0.0),
                source=f.get("source"),
                evidence=f.get("evidence"),
                redacted=redacted,
                last4=f.get("last4"),
                masked_value=mask(f.get("last4")) if redacted else None,
                value_persisted=persisted,
            )
        return out

    def render(
        self,
        rec: ScanRecord,
        *,
        transient_fields: dict | None = None,
        source_lookup: SourceLookup | None = None,
    ) -> ScanResponse:
        return ScanResponse(
            scan_id=rec.scan_id,
            tenant_id=rec.tenant_id,
            document_type=rec.document_type,
            country=rec.country,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            confirmed_at=rec.confirmed_at,
            images=[ImageDescriptor(**d) for d in rec.images],
            fields=self._render_fields(rec.extraction, transient_fields),
            corrected_fields=list(rec.corrected_fields),
            quality=Quality(**(rec.quality or {"overall_confidence": 0.0})),
            document=DocumentIdentity(
                number_last4=rec.document_number_last4,
                number_masked=mask(rec.document_number_last4),
                document_hash=rec.document_hash,
            ),
            portrait_detected=rec.portrait_detected,
            qr_present=rec.qr_present,
            worker=WorkerInfo(
                name=rec.worker.get("name"), version=rec.worker.get("version"), schema_ref=rec.worker_schema_ref
            ),
            source_lookup=source_lookup,
        )

    # ---- operations ------------------------------------------------------

    def _validate_images(self, req: ScanRequest) -> list[ValidatedImage]:
        images = []
        try:
            images.append(decode_and_validate("front", req.front_image_base64, self.settings))
            if req.back_image_base64:
                images.append(decode_and_validate("back", req.back_image_base64, self.settings))
        except InvalidImage as exc:
            metrics.IMAGE_REJECTIONS.labels(code=exc.code).inc()
            metrics.SCANS.labels(outcome="invalid_image").inc()
            raise ServiceError(422, exc.code, exc.message) from exc
        return images

    def _record_failure(self, base: ScanRecord, code: str, identity: WorkloadIdentity) -> None:
        base.status = "failed"
        base.error_code = code
        self.repo.create(base, identity.actor)

    @staticmethod
    def _fingerprint(req: ScanRequest, images: list[ValidatedImage]) -> str:
        parts = [req.document_type, req.country, *(f"{i.side}:{i.sha256}" for i in images)]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

    def _replay(self, identity: WorkloadIdentity, key: str, fingerprint: str) -> ScanResponse | None:
        existing = self.repo.get_by_idempotency_key(identity.tenant_id, key)
        if existing is None:
            return None
        if existing.request_fingerprint != fingerprint:
            raise ServiceError(409, "idempotency_key_reused", "Idempotency-Key was used for a different request")
        metrics.SCANS.labels(outcome="idempotent_replay").inc()
        return self.render(existing)

    def scan(
        self, req: ScanRequest, identity: WorkloadIdentity, request_id: str, idempotency_key: str | None = None
    ) -> tuple[ScanResponse, bool]:
        """Returns (response, replayed)."""
        images = self._validate_images(req)
        fingerprint = self._fingerprint(req, images)
        if idempotency_key and (replayed := self._replay(identity, idempotency_key, fingerprint)):
            return replayed, True
        ts = now()
        record = ScanRecord(
            scan_id=new_scan_id(),
            tenant_id=identity.tenant_id,
            request_id=request_id,
            document_type=req.document_type,
            country=req.country,
            status="pending_review",
            created_at=ts,
            updated_at=ts,
            images=[img.descriptor() for img in images],
            created_by=identity.actor,
        )
        ctx = {"scan_id": record.scan_id, "tenant_id": record.tenant_id, "request_id": request_id}
        try:
            result = self.worker.extract(
                request_id=request_id,
                tenant_id=identity.tenant_id,
                document_type=req.document_type,
                country=req.country,
                images=images,
            )
        except WorkerUnavailable as exc:
            self._record_failure(record, exc.code, identity)
            metrics.SCANS.labels(outcome="worker_unavailable").inc()
            log.warning("scan_failed", extra={**ctx, "error_code": exc.code})
            raise ServiceError(503, exc.code, "OCR worker unavailable; retry later", scan_id=record.scan_id) from exc
        except WorkerSchemaMismatch as exc:
            self._record_failure(record, exc.code, identity)
            metrics.SCANS.labels(outcome="schema_mismatch").inc()
            log.error("scan_failed", extra={**ctx, "error_code": exc.code, "violations": exc.violations})
            raise ServiceError(502, exc.code, str(exc), scan_id=record.scan_id, violations=exc.violations) from exc
        except WorkerError as exc:
            self._record_failure(record, exc.code, identity)
            metrics.SCANS.labels(outcome="worker_error").inc()
            log.error("scan_failed", extra={**ctx, "error_code": exc.code})
            raise ServiceError(502, exc.code, "OCR worker error", scan_id=record.scan_id) from exc
        finally:
            del images  # drop references to raw image payloads as early as possible

        warnings = list(result["quality"].get("warnings", []))
        if result["document_type"] != req.document_type:
            warnings.append("worker_document_type_mismatch")
        if result["country"] != req.country:
            warnings.append("worker_country_mismatch")

        protected = protect_fields(
            result["fields"],
            pepper=self.settings.document_hash_pepper,
            tenant_id=identity.tenant_id,
            country=req.country,
            document_type=req.document_type,
        )
        doc_hash, doc_last4 = primary_number(protected)
        portrait = result.get("portrait") or {}
        qr = result.get("qr") or {}
        record.extraction = protected
        record.quality = {"overall_confidence": result["quality"]["overall_confidence"], "warnings": warnings}
        record.worker = {k: v for k, v in result["worker"].items() if k in ("name", "version", "engine")}
        if portrait.get("side"):
            record.worker["portrait_side"] = portrait["side"]
        record.worker_schema_ref = EXTRACTION_RESULT_SCHEMA_REF
        record.document_hash = doc_hash
        record.document_number_last4 = doc_last4
        record.portrait_detected = bool(portrait.get("detected"))
        record.qr_present = bool(qr.get("present"))
        record.idempotency_key = idempotency_key
        record.request_fingerprint = fingerprint
        try:
            self.repo.create(record, identity.actor)
        except DuplicateIdempotencyKey:
            # Lost a race with a concurrent identical submission; return the winner.
            if replayed := self._replay(identity, idempotency_key, fingerprint):
                return replayed, True
            raise

        lookup = evaluate_source_lookup(qr.get("source_lookup_url"), self.settings.source_lookup_allowed_hosts)
        metrics.SCANS.labels(outcome="pending_review").inc()
        log.info("scan_created", extra={**ctx, "status": record.status, "field_count": len(protected)})
        # Clear values of protected fields are echoed once, transiently, so the operator can review.
        transient = {n: f for n, f in result["fields"].items() if is_number_field(n) or is_hash_only_field(n)}
        return self.render(record, transient_fields=transient, source_lookup=lookup), False

    def get(self, identity: WorkloadIdentity, scan_id: str) -> ScanResponse:
        rec = self._load(identity, scan_id)
        return self.render(rec)

    def _load(self, identity: WorkloadIdentity, scan_id: str) -> ScanRecord:
        rec = self.repo.get(identity.tenant_id, scan_id) if scan_id.startswith("dscan_") else None
        if rec is None:
            # Identical response for "missing" and "other tenant's" scans.
            raise ServiceError(404, "scan_not_found", "scan not found")
        return rec

    def confirm(self, identity: WorkloadIdentity, scan_id: str, req: ConfirmRequest) -> ScanResponse:
        for name in req.corrections:
            if not name or not name[0].isalpha() or len(name) > 64 or not set(name) <= _FIELD_NAME_CHARS:
                raise ServiceError(422, "invalid_field_name", "correction field names must match ^[a-z][a-z0-9_]*$")
        rec = self._load(identity, scan_id)
        if rec.status != "pending_review":
            metrics.CONFIRMATIONS.labels(outcome="conflict").inc()
            raise ServiceError(409, "scan_not_confirmable", f"scan is {rec.status}")

        extraction = dict(rec.extraction)
        for name, value in req.corrections.items():
            prior = extraction.get(name, {})
            field = {"value": value, "confidence": 1.0, "source": "operator"}
            if prior.get("evidence"):
                field["evidence"] = prior["evidence"]
            extraction[name] = protect_field(
                name,
                field,
                pepper=self.settings.document_hash_pepper,
                tenant_id=rec.tenant_id,
                country=rec.country,
                document_type=rec.document_type,
            )
        doc_hash, doc_last4 = primary_number(extraction)
        corrected = sorted(set(rec.corrected_fields) | set(req.corrections))
        try:
            updated = self.repo.confirm(
                rec.tenant_id,
                scan_id,
                extraction=extraction,
                corrected_fields=corrected,
                document_hash=doc_hash,
                document_number_last4=doc_last4,
                confirmed_by=identity.actor,
                confirmed_at=now(),
            )
        except ConfirmConflict as exc:
            metrics.CONFIRMATIONS.labels(outcome="conflict").inc()
            raise ServiceError(409, "scan_not_confirmable", f"scan is {exc.status}") from exc
        if updated is None:
            raise ServiceError(404, "scan_not_found", "scan not found")
        metrics.CONFIRMATIONS.labels(outcome="confirmed").inc()
        log.info(
            "scan_confirmed",
            extra={"scan_id": scan_id, "tenant_id": rec.tenant_id, "corrected_field_count": len(req.corrections)},
        )
        return self.render(updated)

    def face_id_handoff(self, identity: WorkloadIdentity, scan_id: str) -> FaceIdHandoff:
        rec = self._load(identity, scan_id)
        fields = rec.extraction

        def val(*names: str) -> str | None:
            for n in names:
                f = fields.get(n)
                if f and not f.get("redacted") and f.get("value"):
                    return f["value"]
            return None

        digests = {d["side"]: d["sha256"] for d in rec.images}
        return FaceIdHandoff(
            schema_ref=FACE_ID_HANDOFF_SCHEMA_REF,
            scan_id=rec.scan_id,
            tenant_id=rec.tenant_id,
            ready=rec.status == "confirmed" and rec.portrait_detected,
            status=rec.status,
            confirmed_at=rec.confirmed_at,
            document=FaceIdDocumentRef(
                document_type=rec.document_type,
                country=rec.country,
                number_last4=rec.document_number_last4,
                document_hash=rec.document_hash,
            ),
            subject=FaceIdSubjectHint(
                given_names=val("given_names", "first_name"),
                surnames=val("surnames", "last_name"),
                full_name=val("full_name"),
                date_of_birth=val("date_of_birth"),
                sex=val("sex"),
            ),
            portrait_detected=rec.portrait_detected,
            portrait_side=rec.worker.get("portrait_side"),
            front_image_sha256=digests.get("front"),
            back_image_sha256=digests.get("back"),
        )
