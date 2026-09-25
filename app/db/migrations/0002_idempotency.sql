-- Idempotent scan submission: (tenant_id, idempotency_key) identifies one
-- successful scan. Failed attempts do not hold the key so callers can retry.
ALTER TABLE document_scans ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE document_scans ADD COLUMN IF NOT EXISTS request_fingerprint text;
CREATE UNIQUE INDEX IF NOT EXISTS document_scans_tenant_idempotency_uq
    ON document_scans (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
