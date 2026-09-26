# ADR-001 — Middleware V3 is the control authority

Status: Accepted

Document Intelligence is independently deployable but does not create a second public integration control plane. Public platform requests traverse Caddy and Kong into Middleware V3 :8095. Middleware applies tenant, identity, policy, idempotency, ledger/outbox and readback semantics before internal document processing.

OCR workers are implementation details and are never directly public.

This preserves one authoritative integration path while allowing the document product and SDK to evolve independently.
