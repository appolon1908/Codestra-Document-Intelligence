# Codestra Document Intelligence Platform Architecture

## Authority and request path

Canonical request path:

Client systems (Odoo, Klyrow, banking/KYC, apps)
-> Caddy public TLS edge
-> Kong API gateway
-> Middleware V3 canonical integration API on :8095
-> Codestra Document Intelligence internal API
-> OCR orchestration/workers
-> schema validation/confidence
-> result/readback through Middleware V3.

Middleware V3 remains command authority. OCR services do not bypass policy, tenant, idempotency, audit, ledger/outbox, safety, or operation readback.

## Existing platform services reused

- Caddy: public TLS/domain edge only.
- Kong: routing, authentication prerequisites, rate limits, request limits, correlation and method/path enforcement.
- Keycloak: JWT identity, clients, scopes, audiences, MFA and workload identity.
- Middleware V3 (:8095): tenant/policy authority, command kernel, idempotency, durable ledger/outbox, connector registry, execution/readback/reconciliation.
- OpenBao: secret references, credentials, PKI, leases and rotation.
- PostgreSQL: durable metadata/job/result authority.
- Redis: bounded cache/queue coordination where the owning service contract permits it.
- Alloy/OpenTelemetry -> Prometheus/Loki/Tempo -> Alertmanager/Grafana: metrics, logs, traces and alerts.

Do not duplicate these components inside Document Intelligence.

## Document Intelligence components

1. Codestra-Document-Intelligence
   Internal API/controller, tenant context, job lifecycle, classification, orchestration, confidence policy, result model and Middleware adapter boundary.
2. Codestra-OCR-Workers
   Isolated OCR execution workers. Primary PaddleOCR family adapter plus pluggable fallback adapter. GPU/CPU worker boundaries stay internal.
3. Codestra-Document-Schemas
   Versioned schemas and validation rules for IDs, passports, invoices, contracts, bank statements and future document types.
4. Codestra-Document-SDK
   Typed client surface and integration examples. External consumers use stable API contracts rather than worker internals.
5. Codestra-Document-Console
   Administration, job inspection and human-review workflow. It never becomes command authority.

## API boundary

Public clients should call the platform path through Caddy/Kong/Middleware. Suggested platform contract:

- POST /platform/v1/document-intelligence/jobs
- GET /platform/v1/document-intelligence/jobs/{job_id}
- GET /platform/v1/document-intelligence/documents/{document_id}/result
- POST /platform/v1/document-intelligence/extractions/validate

Long OCR work returns an operation/job identifier. Middleware operation readback remains authoritative for command status.

Internal Document Intelligence endpoints may expose /healthz, /readyz and service-to-service job operations, but workers, /metrics, PostgreSQL, Redis, OpenBao and internal control endpoints are not public.

## Processing flow

Ingest -> malware/file/type/size validation -> encrypted object reference -> classify -> preprocess -> primary OCR -> schema extraction -> confidence/validation -> optional fallback OCR -> compare -> accept or human review -> durable result -> Middleware readback/reconciliation.

The original document is preserved according to tenant retention policy. Results include provenance, engine/version, schema/version, confidence and audit correlation identifiers.

## Multi-tenant/security requirements

- tenant_id is derived from authenticated platform context, never trusted from arbitrary client input.
- deny-by-default authorization and document-type permissions.
- encrypted transport and encrypted storage.
- OpenBao secret references; no secrets committed to Git.
- tenant-scoped storage/database access and retention/deletion policy.
- immutable audit events for ingestion, extraction, review, export and deletion.
- purpose/consent metadata where required by the consuming workflow.
- no live banking/KYC decision is made solely from OCR confidence; consuming systems own their regulated decision policy.

## Repository independence

Every repository must remain independently buildable/testable/deployable and have its own CI, Dockerfile/runtime definition where applicable, health/readiness contract, tests, security checks and versioning. Shared contracts belong in schemas/SDK rather than copied implementations.

## Environments

development -> staging -> production

Production activation requires exact-SHA certification, green CI, security checks, staging evidence, readback/reconciliation evidence and rollback readiness. No direct provider or downstream bypass.

## Local workspace

Expected Appolon root:
C:\Users\agent\Documents\GitHub

The combined workspace is:
Codestra-Document-Platform.code-workspace

Local development preserves the same boundary:
Caddy -> Kong -> Middleware V3 :8095 -> Document Intelligence -> OCR workers.

## Git publishing rule

Never auto-push main. Before publishing a feature branch: verify exact branch and remote SHA, fetch the exact branch, require a clean/non-stale/non-divergent worktree, run applicable tests, use only a normal non-force push to the intended non-main branch, then verify the remote SHA. Stop if the remote changed or local work is dirty/stale/divergent.
