# Test Strategy
Unit: parsing, normalization, validators, confidence, errors and config.
Contract: API/schema compatibility, error codes, SDK fixtures and Middleware adapters.
Security: tenant isolation, auth denial, upload limits, redaction and cross-tenant denial.
Integration: Middleware command -> job -> worker -> schema -> durable result -> readback.
Reliability: idempotent retry, duplicate delivery, worker failure, timeout and dead-letter behavior.
Quality: golden document fixtures with document-type-specific quality thresholds.
Production: exact SHA, green CI, staging evidence, rollback and observability verification.
