# Security Baseline
- Default deny; tenant comes from trusted authenticated context.
- Validate Keycloak identity, audience and scopes at platform boundaries.
- Use OpenBao/runtime secret references; no secrets in Git.
- Public path is Caddy -> Kong -> Middleware V3.
- Workers, DB, queue, metrics and internal admin stay private.
- Tenant-scoped document access, retention/deletion and audited review.
- Redact document content, credentials, tokens and sensitive fields from logs by default.
- Validate uploads for allowed type/size and hostile/unexpected content.
- Production requires security tests and staging evidence.
