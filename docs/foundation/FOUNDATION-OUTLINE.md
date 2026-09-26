# Foundation Outline

## Product goal
Build a standalone, multi-tenant document-intelligence product that can serve Odoo campaigns, identity/KYC workflows, banking integrations and independent customers through stable APIs while preserving the Codestra platform control boundary.

## Authority model
Public client -> Caddy -> Kong -> Middleware V3 :8095 -> Document Intelligence -> OCR workers.
Middleware V3 owns tenant context, policy, idempotency, durable command/audit semantics, connector ownership and operation readback.

## Foundation workstreams
1. Contracts: OpenAPI, job/result/error models, versioning and idempotency.
2. Runtime: service skeletons, configuration, health/readiness, Docker and local compose.
3. OCR: engine adapter interface, primary/fallback routing, preprocessing and confidence.
4. Schemas: versioned document types, validators, provenance and normalization.
5. Security: Keycloak scopes/audiences, OpenBao references, tenant isolation, encryption, retention and audit.
6. Storage: metadata authority, object references, migrations and lifecycle.
7. Integration: Middleware service/connector catalog, Kong/Caddy route contract, Odoo/SDK consumers.
8. Review: human-review queue, corrections and immutable reviewer audit.
9. Observability: traces, metrics, structured logs, SLOs and alerts.
10. Delivery: CI, dependency/security scans, staging certification, exact-SHA production gate and rollback.

## Initial document types
- identity card
- passport
- invoice/receipt
- contract
- bank statement
- generic document/text

## Non-functional requirements
- asynchronous jobs for expensive processing
- tenant-scoped authorization and storage
- deterministic API contracts
- retry-safe/idempotent commands
- no secrets in repositories
- engine/model provenance on every result
- configurable retention/deletion
- horizontal worker scaling
- CPU/GPU worker separation
- human review for low-confidence/regulated flows
- no OCR-only automated regulated decision

## Definition of foundation-ready
A repository is foundation-ready when its ownership is explicit, interfaces are versioned, runtime/configuration boundary is documented, health/readiness behavior is specified, security/tenant assumptions are explicit, tests are planned, CI gates are specified, and integration dependencies are named.
