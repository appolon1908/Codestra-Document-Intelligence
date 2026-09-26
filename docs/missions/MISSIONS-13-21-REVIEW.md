# Missions 13-21 — API, Logic and Workflow Review

## 13 Ingress ownership — COMPLETE (design)
Only Caddy/Kong/Middleware is public. Document services and workers remain private.

## 14 Authentication context — COMPLETE (design)
Identity/audience/scope validation precedes tenant resolution. Tenant cannot be supplied as an authority by request payload.

## 15 Idempotent job creation — COMPLETE (design)
Mutation requires idempotency and correlation identifiers. A duplicate request maps to the original authoritative job/operation.

## 16 State machine — COMPLETE (design)
queued -> preprocessing -> extracting -> validating -> completed OR review_required/failed/canceled. Invalid transitions fail closed.

## 17 Worker dispatch — COMPLETE (design)
Primary OCR is policy-selected. Fallback is triggered by validation/quality policy, not arbitrary external engine selection.

## 18 Validation/schema boundary — COMPLETE (design)
OCR produces evidence; schemas normalize/validate it. OCR engine code does not own business document schemas.

## 19 Readback/reconciliation — COMPLETE (design)
Durable result state is queryable and correlated to Middleware operation readback. Ambiguous execution is reconciled rather than guessed successful.

## 20 Human review — COMPLETE (design)
Low-confidence/disagreement/regulated cases can enter review_required. Corrections preserve original evidence and reviewer provenance.

## 21 Failure/observability — COMPLETE (design)
Stable error classes distinguish retryable, terminal and reconciliation-required outcomes. Traces/logs/metrics carry correlation without leaking sensitive document content.

## Flow review
The flow is clean when authority remains one-way:
Caddy -> Kong -> Middleware V3 :8095 -> Document Intelligence -> worker -> schema/validation -> durable result -> Middleware readback.

Improvements adopted:
- separate evidence extraction from regulated decisions;
- make fallback policy-driven;
- preserve original and corrected values;
- model ambiguous provider/worker outcomes explicitly;
- keep synchronous health endpoints separate from asynchronous document processing;
- use one authoritative operation/job correlation chain;
- keep SDK and Console as consumers, never alternate control planes.

## Next implementation gate
These missions complete the design review. Runtime code must now prove the state machine, idempotency, tenant isolation, worker routing, validation, reconciliation and review paths with tests before runtime completion is claimed.
