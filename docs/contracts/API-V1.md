# API Contract v1
Middleware V3 owns the platform-facing API:
POST /platform/v1/document-intelligence/jobs
GET /platform/v1/document-intelligence/jobs/{job_id}
GET /platform/v1/document-intelligence/documents/{document_id}/result
POST /platform/v1/document-intelligence/extractions/validate

Mutations require authenticated identity, trusted tenant context, idempotency key and correlation/trace ID.
Job states: queued, preprocessing, extracting, validating, review_required, completed, failed, canceled.
Long processing is asynchronous and results are versioned with provenance.
