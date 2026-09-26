# Document Intelligence — architecture

## Context

```
 Operator console / client apps
            │ HTTPS
            ▼
 Caddy ──► Kong ──► Middleware V3 :8095 ──────────────► Document Intelligence API :8080
                     (authn, tenant resolution,           │  (this repo)
                      FACE-ID adapter, routing)           │
                                                          ├──► PostgreSQL (schema `docintel`, owned)
                                                          │
                                                          └──► Codestra-OCR-Workers  (private network,
                                                                 POST /v1/ocr/extract, service token)
```

* Middleware V3 is the only caller. It is the cross-system integration authority;
  this service integrates with nothing else.
* OCR runs in Codestra-OCR-Workers. This repository contains no OCR engine. The
  compose dev stack ships a stub worker that returns canned, contract-valid data.
* FACE-ID is not called. `GET /v1/documents/{scan_id}/face-id-handoff` returns a
  `codestra.document.face-id-handoff/v1` object for Middleware V3's FACE-ID adapter.
  It carries subject hints (names, date of birth), document last4 + keyed hash, portrait
  detection, and image digests so the adapter can match the portrait image it holds.
  It becomes `ready: true` only after operator confirmation and portrait detection.

## Components (`app/`)

| Module | Responsibility |
| --- | --- |
| `main.py` | FastAPI app factory, routes, error envelope, request-id/metrics/logging middleware |
| `security.py` | Workload identity: bearer token (constant-time), workload allowlist, `X-Tenant-ID` |
| `images.py` | Base64 decode, size bound, JPEG/PNG header parse for dimensions, SHA-256 |
| `worker_client.py` | Outbound OCR worker binding, response validation (schema, request_id, digests) |
| `contracts/` | Pinned JSON Schemas for worker request/response (`$id` = wire schema ref) |
| `protection.py` | Keyed hashing + last4 for sensitive numbers; MRZ hash-only |
| `service.py` | Orchestration: intake → worker → protect → persist; confirm; FACE-ID hand-off |
| `db/repository.py` | Tenant-scoped repository (PostgreSQL + in-memory), migrations runner |
| `db/migrations/` | Forward-only, idempotent SQL applied at startup under an advisory lock |

## Scan flow

1. Middleware V3 calls `POST /v1/documents/scan` with workload identity headers.
2. Images are decoded in memory, bounded (bytes, min/max dimension, pixel count), and digested.
3. A `codestra.ocr.extract-request/v1` request goes to the worker with this service's token.
4. The response must match `codestra.ocr.extraction-result/v1`, echo the `request_id`, and
   echo the sent image digests. Failures persist a `failed` session (`503` unavailable,
   `502` mismatch) and never store partial worker output.
5. Sensitive fields are replaced by keyed hash + last4, then the session is stored as
   `pending_review`. The response echoes clear sensitive values once (transient) and the
   allowlisted QR source link, if any (transient, never fetched).
6. The operator reviews and calls `confirm` with corrections; corrected sensitive values are
   protected identically before the row is updated to `confirmed`.

## Tenant isolation

* Tenant comes only from `X-Tenant-ID` injected by Middleware V3 after authenticating the
  workload token; request bodies with `tenant_id` are rejected (`extra="forbid"`).
* Every repository query filters on `tenant_id`.
* PostgreSQL row-level security (`FORCE ROW LEVEL SECURITY`) restricts rows to
  `current_setting('app.tenant_id')`, set per transaction. The API connects as the
  non-superuser, `NOBYPASSRLS` role `docintel_app`, so a query missing its tenant predicate
  still cannot see or write another tenant's rows. Tests prove both layers.
* Cross-tenant reads return the same `404` as missing scans (no existence oracle).
* Document hashes are keyed per tenant, so hashes cannot be correlated across tenants.

## Persistence

Tables: `document_scans`, `document_scan_events` (audit: created/confirmed, actor),
`schema_migrations`. Stored: document type, country, status, timestamps, image descriptors
(digest, type, dimensions, bytes), protected extraction with confidence/source/evidence,
quality, worker name/version, schema ref, document hash + last4, idempotency key and
request fingerprint. Not stored: images, full sensitive numbers, MRZ text, QR URLs,
caller credentials.

## Security notes

* Inbound: workload token compared in constant time; workload allowlist; fails closed with
  `503` if no inbound tokens are configured.
* Outbound: worker URL from environment, token from a secret file reference; redirects are
  not followed; caller `Authorization`/cookies are never forwarded.
* Container: non-root UID 10001, read-only root filesystem, all capabilities dropped,
  loopback-only port publication in compose, internal network for DB/worker.
* Responses on `/v1/documents/*` are `Cache-Control: no-store`.

## Observability

* `/metrics`: `docintel_http_requests_total`, `docintel_http_request_duration_seconds`,
  `docintel_scans_total{outcome}`, `docintel_confirmations_total`,
  `docintel_image_rejections_total{code}`, `docintel_ocr_worker_requests_total{outcome}`,
  `docintel_ocr_worker_duration_seconds`, `docintel_auth_failures_total{reason}`,
  `docintel_source_lookup_urls_total{decision}`.
* JSON logs on stdout with `request_id`, `tenant_id`, `scan_id`, outcome codes. `X-Request-ID`
  is accepted from Middleware V3 and propagated to the worker.

## Not in scope (this branch)

Production activation, Kong/Middleware route registration, retention/purge jobs, and the
real OCR worker implementation (Codestra-OCR-Workers) are owned elsewhere.
