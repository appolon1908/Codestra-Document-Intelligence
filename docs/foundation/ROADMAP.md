# Delivery Roadmap

## Phase A — Foundation
Architecture, repository ownership, API schemas, threat model, ADRs, local topology and CI contract.

## Phase B — Executable skeleton
FastAPI/service runtime where applicable, health/readiness, config validation, Docker, migrations, unit tests and local compose.

## Phase C — OCR vertical slice
One sample document -> ingest -> primary OCR -> normalized schema -> confidence -> durable result -> Middleware operation readback.

## Phase D — Fallback and review
Fallback OCR, disagreement policy, human-review queue, correction provenance and console workflow.

## Phase E — Platform integration
Keycloak scopes, Kong/Caddy route, OpenBao references, Middleware service/connector catalog, SDK and Odoo integration.

## Phase F — Scale and certification
Queue autoscaling, GPU scheduling, load tests, SLOs, security tests, retention/deletion verification, staging evidence and production certification.
