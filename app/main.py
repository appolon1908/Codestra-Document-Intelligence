"""FastAPI application: Codestra Document Intelligence API."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import metrics
from .config import ConfigError, Settings
from .contracts import EXTRACT_REQUEST_SCHEMA_REF, EXTRACTION_RESULT_SCHEMA_REF, FACE_ID_HANDOFF_SCHEMA_REF
from .db.repository import InMemoryScanRepository, PostgresScanRepository, ScanRepository
from .logging_setup import configure_logging
from .models import (
    Capabilities,
    ConfirmRequest,
    ErrorResponse,
    FaceIdHandoff,
    HealthResponse,
    ImageLimits,
    ReadyResponse,
    ScanRequest,
    ScanResponse,
)
from .security import Identity, WorkloadIdentity
from .service import ScanService, ServiceError
from .worker_client import HttpOcrWorker, OcrWorker

log = logging.getLogger("docintel.http")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

API_DESCRIPTION = (
    "Standalone multi-tenant document intelligence API. Reachable only via "
    "Caddy -> Kong -> Middleware V3 -> Document Intelligence. OCR runs in Codestra-OCR-Workers.\n\n"
    "**OCR/QR output is an intake aid, not government authenticity verification.** "
    "Raw document images are never persisted; sensitive document numbers are stored only as a "
    "tenant-scoped keyed hash plus last four characters."
)

_ERRORS = {
    400: {"model": ErrorResponse, "description": "Missing or malformed tenant identity"},
    401: {"model": ErrorResponse, "description": "Missing or invalid workload token"},
    403: {"model": ErrorResponse, "description": "Calling workload not allowlisted"},
}


def _error(status: int, code: str, message: str, request: Request, **extra) -> JSONResponse:
    body = {"code": code, "message": message}
    body.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(
        status_code=status,
        content={"error": body, "request_id": getattr(request.state, "request_id", None)},
        headers={"Cache-Control": "no-store"},
    )


def create_app(
    settings: Settings | None = None,
    repo: ScanRepository | None = None,
    worker: OcrWorker | None = None,
    *,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if configure_logs:
        configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = []
        if app.state.repo is None:
            if settings.database_url:
                pg = PostgresScanRepository(settings.database_url)
                applied = pg.migrate()
                log.info("migrations_applied", extra={"versions": applied})
                app.state.repo = pg
                owned.append(pg)
            elif settings.environment == "production":
                raise ConfigError("DATABASE_URL is required")
            else:
                log.warning("using_in_memory_store", extra={"reason": "DATABASE_URL unset (development)"})
                app.state.repo = InMemoryScanRepository()
        if app.state.worker is None:
            w = HttpOcrWorker(settings.ocr_worker_url, settings.ocr_worker_token, settings.ocr_worker_timeout_seconds)
            app.state.worker = w
            owned.append(w)
        app.state.service = ScanService(settings, app.state.repo, app.state.worker)
        yield
        for resource in owned:
            resource.close()

    app = FastAPI(
        title="Codestra Document Intelligence API",
        version="1.0.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.repo = repo
    app.state.worker = worker
    if repo is not None and worker is not None:
        app.state.service = ScanService(settings, repo, worker)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            elapsed = time.perf_counter() - started
            metrics.HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
            metrics.HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
            log.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "route": route_path,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                    "tenant_id": getattr(request.state, "tenant_id", None),
                },
            )
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/v1/documents"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return _error(exc.status, exc.code, exc.message, request, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            return _error(exc.status_code, exc.detail.get("code", "error"), exc.detail.get("message", ""), request)
        return _error(exc.status_code, "http_error", str(exc.detail), request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo submitted values (images, document numbers) back in errors.
        violations = [
            "/" + "/".join(str(p) for p in err.get("loc", ())) + f": {err.get('type')}" for err in exc.errors()
        ][:20]
        return _error(422, "request_invalid", "request validation failed", request, violations=violations)

    # ---- operational endpoints ------------------------------------------

    @app.get("/healthz", response_model=HealthResponse, tags=["operations"])
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    def _ready(request: Request, response: Response) -> ReadyResponse:
        repo_ = request.app.state.repo
        worker_ = request.app.state.worker
        checks = {
            "database": bool(repo_ and repo_.ping()),
            "ocr_worker_binding": bool(worker_ and worker_.ready()),
            "workload_auth": bool(request.app.state.settings.inbound_service_tokens),
        }
        ok = all(checks.values())
        if not ok:
            response.status_code = 503
        return ReadyResponse(status="ready" if ok else "not_ready", checks=checks)

    @app.get(
        "/readyz",
        response_model=ReadyResponse,
        tags=["operations"],
        responses={503: {"model": ReadyResponse, "description": "Not ready"}},
    )
    def readyz(request: Request, response: Response) -> ReadyResponse:
        return _ready(request, response)

    @app.get(
        "/health/ready",
        response_model=ReadyResponse,
        tags=["operations"],
        responses={503: {"model": ReadyResponse, "description": "Not ready"}},
    )
    def health_ready(request: Request, response: Response) -> ReadyResponse:
        return _ready(request, response)

    @app.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/capabilities", response_model=Capabilities, tags=["capabilities"])
    def capabilities() -> Capabilities:
        return Capabilities(
            document_types=list(settings.supported_document_types),
            image_limits=ImageLimits(
                max_bytes=settings.max_image_bytes,
                min_dimension=settings.min_image_dimension,
                max_dimension=settings.max_image_dimension,
                max_pixels=settings.max_image_pixels,
                media_types=["image/jpeg", "image/png"],
            ),
            ocr_worker_schema_refs={"request": EXTRACT_REQUEST_SCHEMA_REF, "response": EXTRACTION_RESULT_SCHEMA_REF},
            face_id_handoff_schema_ref=FACE_ID_HANDOFF_SCHEMA_REF,
            source_lookup_allowlist_configured=bool(settings.source_lookup_allowed_hosts),
        )

    # ---- document scan API ----------------------------------------------

    def _svc(request: Request) -> ScanService:
        return request.app.state.service

    @app.post(
        "/v1/documents/scan",
        response_model=ScanResponse,
        status_code=201,
        tags=["documents"],
        summary="Scan a document (front/back images) via the OCR worker",
        responses={
            **_ERRORS,
            200: {"model": ScanResponse, "description": "Idempotent replay of an earlier scan"},
            409: {"model": ErrorResponse, "description": "Idempotency-Key reused for a different request"},
            422: {"model": ErrorResponse, "description": "Invalid request or image"},
            502: {"model": ErrorResponse, "description": "OCR worker schema mismatch or error"},
            503: {"model": ErrorResponse, "description": "OCR worker unavailable"},
        },
    )
    def scan_document(
        body: ScanRequest,
        request: Request,
        response: Response,
        identity: WorkloadIdentity = Identity,
        idempotency_key: str | None = Header(
            default=None,
            pattern=r"^[A-Za-z0-9._:-]{8,128}$",
            description="Optional. Replaying the same key with the same images returns the original scan (200).",
        ),
    ) -> ScanResponse:
        result, replayed = _svc(request).scan(body, identity, request.state.request_id, idempotency_key)
        if replayed:
            response.status_code = 200
            response.headers["Idempotent-Replayed"] = "true"
        return result

    @app.get(
        "/v1/documents/{scan_id}",
        response_model=ScanResponse,
        response_model_exclude_none=False,
        tags=["documents"],
        summary="Get a scan session (tenant-scoped)",
        responses={**_ERRORS, 404: {"model": ErrorResponse, "description": "Scan not found"}},
    )
    def get_document(scan_id: str, request: Request, identity: WorkloadIdentity = Identity) -> ScanResponse:
        return _svc(request).get(identity, scan_id)

    @app.post(
        "/v1/documents/{scan_id}/confirm",
        response_model=ScanResponse,
        tags=["documents"],
        summary="Confirm a scan with operator corrections",
        responses={
            **_ERRORS,
            404: {"model": ErrorResponse, "description": "Scan not found"},
            409: {"model": ErrorResponse, "description": "Scan not in pending_review"},
            422: {"model": ErrorResponse, "description": "Invalid corrections"},
        },
    )
    def confirm_document(
        scan_id: str, body: ConfirmRequest, request: Request, identity: WorkloadIdentity = Identity
    ) -> ScanResponse:
        return _svc(request).confirm(identity, scan_id, body)

    @app.get(
        "/v1/documents/{scan_id}/face-id-handoff",
        response_model=FaceIdHandoff,
        tags=["documents"],
        summary="Client-ready result object for the FACE-ID adapter (this service never calls FACE-ID)",
        responses={**_ERRORS, 404: {"model": ErrorResponse, "description": "Scan not found"}},
    )
    def face_id_handoff(scan_id: str, request: Request, identity: WorkloadIdentity = Identity) -> FaceIdHandoff:
        return _svc(request).face_id_handoff(identity, scan_id)

    return app


def build_default_app() -> FastAPI:  # pragma: no cover - uvicorn entrypoint
    return create_app()
