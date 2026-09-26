"""Public API models (the OpenAPI contract consumed via Middleware V3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

INTAKE_DISCLAIMER = (
    "OCR and QR extraction is an intake aid only. It is not government authenticity "
    "verification and must not be treated as proof that a document is genuine."
)

DocumentType = Literal["national_id", "passport", "driver_license", "residence_permit"]
ScanStatus = Literal["pending_review", "confirmed", "failed"]
Side = Literal["front", "back"]

FIELD_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
# 8 MiB decoded -> ~11.2 MiB base64 plus optional data-URL prefix; the precise byte bound is
# enforced after decoding using MAX_IMAGE_BYTES.
_MAX_B64_CHARS = 12 * 1024 * 1024


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanRequest(Strict):
    document_type: DocumentType
    country: str = Field(pattern=r"^[A-Z]{2,3}$", description="ISO 3166-1 alpha-2 or alpha-3 code")
    front_image_base64: str = Field(min_length=1, max_length=_MAX_B64_CHARS, description="JPEG or PNG")
    back_image_base64: str | None = Field(default=None, max_length=_MAX_B64_CHARS, description="JPEG or PNG")


class ConfirmRequest(Strict):
    corrections: dict[str, str | None] = Field(
        default_factory=dict,
        max_length=64,
        description="Operator-corrected field values keyed by field name. Omitted fields keep the "
        "extracted value. Sensitive numbers are hashed and reduced to last4 before persistence.",
    )


class ImageDescriptor(BaseModel):
    side: Side
    media_type: Literal["image/jpeg", "image/png"]
    width: int
    height: int
    size_bytes: int
    sha256: str


class FieldEvidence(BaseModel):
    side: Side | None = None
    bbox: list[float] | None = None


class ExtractedField(BaseModel):
    value: str | None = Field(
        description="Field value. Always null for redacted fields except in the transient scan response."
    )
    confidence: float
    source: Literal["visual", "mrz", "barcode", "qr", "operator"] | None = None
    evidence: FieldEvidence | None = None
    redacted: bool = False
    masked_value: str | None = None
    last4: str | None = None
    value_persisted: bool = Field(
        default=True, description="False when the value shown is transient and not stored by this service"
    )


class Quality(BaseModel):
    overall_confidence: float
    warnings: list[str] = Field(default_factory=list)


class DocumentIdentity(BaseModel):
    number_last4: str | None
    number_masked: str | None
    document_hash: str | None = Field(description="Tenant-scoped keyed hash of the primary document number")


class WorkerInfo(BaseModel):
    name: str | None = None
    version: str | None = None
    schema_ref: str | None = None


class Verification(BaseModel):
    authenticity_verified: Literal[False] = False
    method: Literal["ocr_intake_aid"] = "ocr_intake_aid"
    disclaimer: str = INTAKE_DISCLAIMER


class SourceLookup(BaseModel):
    """QR source lookup link. Transient: never persisted and never fetched by this service."""

    allowlisted: bool
    url: str | None = Field(description="Present only when the host is allowlisted")
    host: str | None = None
    fetched: Literal[False] = False
    persisted: Literal[False] = False
    note: str = "Operator may open this link manually; this service never fetches it."


class ScanSummary(BaseModel):
    scan_id: str
    document_type: DocumentType
    country: str
    status: ScanStatus
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class ScanListResponse(BaseModel):
    items: list[ScanSummary]
    next_cursor: str | None = None


class ScanResponse(BaseModel):
    scan_id: str
    tenant_id: str
    document_type: DocumentType
    country: str
    status: ScanStatus
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    images: list[ImageDescriptor]
    fields: dict[str, ExtractedField]
    corrected_fields: list[str]
    quality: Quality
    document: DocumentIdentity
    portrait_detected: bool
    qr_present: bool
    worker: WorkerInfo
    verification: Verification = Field(default_factory=Verification)
    source_lookup: SourceLookup | None = Field(
        default=None, description="Only returned in the scan response; never stored"
    )


class FaceIdDocumentRef(BaseModel):
    document_type: DocumentType
    country: str
    number_last4: str | None
    document_hash: str | None


class FaceIdSubjectHint(BaseModel):
    given_names: str | None = None
    surnames: str | None = None
    full_name: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None


class FaceIdHandoff(BaseModel):
    """Client-ready object for the FACE-ID adapter (owned by Middleware V3).

    Document Intelligence never calls FACE-ID. The adapter must fetch the
    portrait image from the caller-held source, matched by ``front_image_sha256``.
    """

    schema_ref: Literal["codestra.document.face-id-handoff/v1"] = "codestra.document.face-id-handoff/v1"
    scan_id: str
    tenant_id: str
    ready: bool
    status: ScanStatus
    confirmed_at: datetime | None
    document: FaceIdDocumentRef
    subject: FaceIdSubjectHint
    portrait_detected: bool
    portrait_side: Side | None
    front_image_sha256: str | None
    back_image_sha256: str | None
    verification: Verification = Field(default_factory=Verification)


class ErrorBody(BaseModel):
    code: str
    message: str
    scan_id: str | None = None
    violations: list[str] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


class ImageLimits(BaseModel):
    max_bytes: int
    min_dimension: int
    max_dimension: int
    max_pixels: int
    media_types: list[str]


class Capabilities(BaseModel):
    service: Literal["codestra-document-intelligence"] = "codestra-document-intelligence"
    api_version: Literal["v1"] = "v1"
    document_types: list[str]
    image_limits: ImageLimits
    ocr_worker_schema_refs: dict[str, str]
    face_id_handoff_schema_ref: str
    raw_image_persistence: Literal[False] = False
    sensitive_number_storage: Literal["keyed_hash_and_last4"] = "keyed_hash_and_last4"
    source_lookup_auto_fetch: Literal[False] = False
    source_lookup_allowlist_configured: bool
    authenticity_verification: Literal[False] = False
    disclaimer: str = INTAKE_DISCLAIMER
    tenant_isolation: Literal["workload_identity_header"] = "workload_identity_header"
