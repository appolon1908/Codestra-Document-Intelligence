# Standalone architecture

`Codestra-Document-Intelligence` is an independent software product.

It must build, test, run, deploy, version, scale, and roll back without requiring another Codestra repository to share its process or business database.

## Rules

- Own repository, runtime, configuration, contracts, tests, release, and rollback.
- Own data authority; no shared business database with another application.
- Cross-system communication uses versioned APIs/events.
- Middleware V3 is the cross-system orchestration authority.
- Caddy and Kong provide governed ingress and do not own business logic.
- Keycloak owns identity/authentication; OpenBao owns secrets.
- Observability services observe without becoming business-runtime dependencies.
- No runtime source-code imports from another service repository.
- No provider credentials committed to source control.
- Effectful operations fail closed and use idempotency/readback where relevant.
- Development, testing, staging, and production are separate promotion stages.

Canonical cross-system path:

`Caddy -> Kong -> Middleware V3 :8095 -> Codestra-Document-Intelligence API/control surface`

Private internal worker/helper calls are permitted only through explicit versioned contracts and only when they belong to this product architecture.
