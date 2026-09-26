# Missions 06-10 — API Department
06 API domain model: jobs/documents/results/validation/operation correlation.
07 Lifecycle logic: queued -> preprocessing -> extracting -> validating -> review_required/completed/failed/canceled.
08 Idempotency: mutating job creation requires idempotency key; duplicate key returns original authoritative operation.
09 Tenant/policy: tenant is injected from trusted Middleware identity context and cannot be overridden by payload.
10 Readback: API exposes deterministic job/result state while Middleware V3 remains platform operation authority.

Implementation branch target after architecture baseline is committed: feature/api-foundation-v1.
