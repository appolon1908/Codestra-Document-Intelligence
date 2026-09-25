# Codestra-Document-Intelligence

Standalone multi-tenant document intelligence API and orchestrator.

It accepts front/back images of identity documents, delegates OCR to
**Codestra-OCR-Workers** over a private, versioned contract, and stores a
structured, redacted extraction that operators review and confirm.

> **OCR/QR output is an intake aid, not government authenticity verification.**
> Every scan response carries `verification.authenticity_verified: false` and
> this disclaimer. Nothing in this service proves a document is genuine.

## Where it sits

```
Caddy -> Kong -> Middleware V3 :8095 -> Document Intelligence API        (canonical, public path)
                                        Document Intelligence -> OCR Workers   (private network only)
```

* **Middleware V3** is the cross-system integration authority. It authenticates
  users, resolves the tenant, and calls this API with its workload identity.
* This service never calls FACE-ID or any other business system. It exposes a
  client-ready FACE-ID hand-off object that Middleware V3's FACE-ID adapter consumes.
* It owns its own PostgreSQL schema. It never writes to a shared business database.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/STANDALONE_ARCHITECTURE.md](docs/STANDALONE_ARCHITECTURE.md).

## API

The contract is [`openapi.json`](openapi.json). A test fails if the running app's
OpenAPI differs from it in any way; regenerate with `python scripts/export_openapi.py`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Liveness |
| GET | `/readyz`, `/health/ready` | Readiness (database, OCR worker binding, inbound auth configured) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/v1/capabilities` | Document types, image limits, schema refs, privacy guarantees |
| POST | `/v1/documents/scan` | Submit front (+ optional back) image, base64 JPEG/PNG |
| GET | `/v1/documents/{scan_id}` | Read a scan (tenant-scoped) |
| POST | `/v1/documents/{scan_id}/confirm` | Operator confirmation with corrections |
| GET | `/v1/documents/{scan_id}/face-id-handoff` | FACE-ID adapter hand-off object |

### Workload identity (required on `/v1/documents/*`)

| Header | Meaning |
| --- | --- |
| `Authorization: Bearer <token>` | Middleware V3's workload token (one of `INBOUND_SERVICE_TOKENS`) |
| `X-Codestra-Workload` | Calling workload; must be in `ALLOWED_WORKLOADS` (default `middleware-v3`) |
| `X-Tenant-ID` | Tenant resolved by Middleware V3. **The only source of tenant.** Bodies with `tenant_id` are rejected. |
| `X-Codestra-Actor` | Optional opaque operator reference, stored for audit |
| `Idempotency-Key` | Optional on scan; same key + same images returns the original scan (200) |

A scan belonging to another tenant returns the same `404` as a missing scan.

### Scan lifecycle

`pending_review` → (operator `confirm`) → `confirmed`. If the OCR worker is
unavailable (`503`) or returns a response that violates the schema (`502`), the
session is recorded as `failed` with an error code and the `scan_id` is returned.

## Data handling guarantees

* **No raw images persisted.** Images live only in request memory and are forwarded
  to the OCR worker. Only SHA-256 digests, media type, dimensions and byte size are stored.
* **Sensitive numbers are never stored in clear.** `document_number`, `personal_number`,
  `national_id_number`, `tax_id` are stored as a tenant-scoped HMAC-SHA256
  (`DOCUMENT_HASH_PEPPER`) plus last four characters. `mrz*` fields are stored as the
  keyed hash only. The clear value is echoed once in the `POST /scan` response
  (`value_persisted: false`) so the operator can review it; later reads return
  `masked_value` only. Operator corrections to these fields are protected the same way.
* **QR/source lookup URLs are transient.** They are returned in the scan response only
  if `https`, on port 443, without credentials, and the host is in
  `SOURCE_LOOKUP_ALLOWED_HOSTS`. They are never persisted and never fetched by this service.
* **No value echo in errors or logs.** Validation errors report paths and error types only;
  structured logs carry identifiers and outcome codes, never extracted values.

## OCR worker contract

* Request: `POST {OCR_WORKER_URL}/v1/ocr/extract`, schema
  [`codestra.ocr.extract-request/v1`](app/contracts/ocr-extract-request.v1.schema.json).
* Response: [`codestra.ocr.extraction-result/v1`](app/contracts/ocr-extraction-result.v1.schema.json).
  The response must declare that `schema_ref`, validate against the schema, echo the
  `request_id`, and echo the exact image digests that were sent; otherwise it is
  rejected as `ocr_worker_schema_mismatch`.
* Authentication: `Authorization: Bearer` with this service's own token read from
  `OCR_WORKER_TOKEN_FILE`. Caller credentials, cookies and tenant headers are never forwarded.

## Configuration

See [`.env.example`](.env.example). Secrets are provided as `*_FILE` references (OpenBao-
mounted files in staging/production); plain-value variants exist for local tests only.
With `APP_ENV=production`, `DATABASE_URL` and `DOCUMENT_HASH_PEPPER` are mandatory.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                       # in-memory repository

# Against PostgreSQL (non-superuser app role so RLS is enforced):
docker run -d --name docintel-test-pg -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=docintel_owner -e POSTGRES_PASSWORD=ownerpw -e POSTGRES_DB=docintel \
  -e DOCINTEL_APP_PASSWORD=apppw -v "$PWD/deploy/postgres:/docker-entrypoint-initdb.d:ro" postgres:17-alpine
TEST_DATABASE_URL=postgresql://docintel_app:apppw@127.0.0.1:55432/docintel \
TEST_DATABASE_ADMIN_URL=postgresql://docintel_owner:ownerpw@127.0.0.1:55432/docintel \
  .venv/bin/pytest
```

### Compose dev stack

```bash
./scripts/dev-secrets.sh        # throwaway secrets in ./secrets (gitignored)
docker compose up --build       # API on 127.0.0.1:8097
```

The stack runs Postgres and a **development-only OCR worker stub**
(`deploy/dev-ocr-worker-stub`, performs no OCR) on an internal network with no
egress. Set `OCR_WORKER_URL` to point at a real Codestra-OCR-Workers instance.

## Status

Foundation branch. Not deployed to production; activation is gated by Middleware V3
route registration and the platform promotion process.

CI definition: [`deploy/ci/github-actions-ci.yml`](deploy/ci/github-actions-ci.yml) — copy to
`.github/workflows/ci.yml` with a credential that has the GitHub `workflow` scope.
