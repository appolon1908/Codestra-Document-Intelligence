-- Document Intelligence owns this schema exclusively. No shared business
-- database tables are written by this service.
-- No column stores raw images or full document numbers in clear.

CREATE TABLE IF NOT EXISTS document_scans (
    scan_id               text PRIMARY KEY,
    tenant_id             text NOT NULL,
    request_id            text NOT NULL,
    document_type         text NOT NULL,
    country               text NOT NULL,
    status                text NOT NULL CHECK (status IN ('pending_review', 'confirmed', 'failed')),
    error_code            text,
    images                jsonb NOT NULL DEFAULT '[]'::jsonb,
    extraction            jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality               jsonb NOT NULL DEFAULT '{}'::jsonb,
    worker                jsonb NOT NULL DEFAULT '{}'::jsonb,
    worker_schema_ref     text,
    corrected_fields      jsonb NOT NULL DEFAULT '[]'::jsonb,
    document_hash         text,
    document_number_last4 text CHECK (document_number_last4 IS NULL OR length(document_number_last4) <= 4),
    portrait_detected     boolean NOT NULL DEFAULT false,
    qr_present            boolean NOT NULL DEFAULT false,
    created_by            text,
    confirmed_by          text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    confirmed_at          timestamptz
);

CREATE INDEX IF NOT EXISTS document_scans_tenant_created_idx
    ON document_scans (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS document_scans_tenant_hash_idx
    ON document_scans (tenant_id, document_hash) WHERE document_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_scan_events (
    id         bigserial PRIMARY KEY,
    scan_id    text NOT NULL REFERENCES document_scans (scan_id) ON DELETE CASCADE,
    tenant_id  text NOT NULL,
    event      text NOT NULL,
    actor      text,
    details    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS document_scan_events_scan_idx ON document_scan_events (tenant_id, scan_id);

-- Defence in depth for tenant isolation: every statement runs with
-- app.tenant_id set for the transaction; rows of other tenants are invisible.
ALTER TABLE document_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_scans FORCE ROW LEVEL SECURITY;
ALTER TABLE document_scan_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_scan_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_scans_tenant_isolation ON document_scans;
CREATE POLICY document_scans_tenant_isolation ON document_scans
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS document_scan_events_tenant_isolation ON document_scan_events;
CREATE POLICY document_scan_events_tenant_isolation ON document_scan_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
