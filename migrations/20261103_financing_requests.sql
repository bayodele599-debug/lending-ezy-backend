-- Apply to the Lending Ezy PostgreSQL database before enabling public financing intake.
-- Schema-only, repeatable migration. No existing application/inquiry rows are changed.
CREATE TABLE IF NOT EXISTS financing_requests (
    id VARCHAR(36) PRIMARY KEY,
    client_token VARCHAR(36) UNIQUE NOT NULL,
    payload_digest VARCHAR(64) NOT NULL,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(254) NOT NULL,
    country VARCHAR(2) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    purpose VARCHAR(80) NOT NULL,
    business_name VARCHAR(150),
    currency VARCHAR(3) NOT NULL,
    amount NUMERIC(16,2) NOT NULL,
    term_months INTEGER NOT NULL,
    assumed_annual_rate NUMERIC(5,2) NOT NULL,
    message TEXT,
    consent_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT chk_financing_amount CHECK (amount >= 500 AND amount <= 10000000),
    CONSTRAINT chk_financing_rate CHECK (assumed_annual_rate >= 0 AND assumed_annual_rate <= 40),
    CONSTRAINT chk_financing_kind CHECK (kind IN ('personal','business')),
    CONSTRAINT chk_financing_status CHECK (status IN ('submitted','in_review','needs_information','proceed_to_next_stage','not_proceeding','closed'))
);
CREATE INDEX IF NOT EXISTS ix_financing_requests_email ON financing_requests(email);
CREATE INDEX IF NOT EXISTS ix_financing_requests_status ON financing_requests(status);
CREATE INDEX IF NOT EXISTS ix_financing_requests_created_at ON financing_requests(created_at);
CREATE INDEX IF NOT EXISTS ix_financing_request_status_created ON financing_requests(status,created_at);

CREATE TABLE IF NOT EXISTS financing_request_events (
    id VARCHAR(36) PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL REFERENCES financing_requests(id) ON DELETE CASCADE,
    old_status VARCHAR(32),
    new_status VARCHAR(32) NOT NULL,
    actor VARCHAR(50) NOT NULL,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_financing_request_events_request_id ON financing_request_events(request_id);


-- Defense in depth for managed Postgres installations that expose the public schema
-- through a Data API. The server-side database owner can still access these tables.
ALTER TABLE financing_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE financing_request_events ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE app_role TEXT;
BEGIN
  FOREACH app_role IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
      EXECUTE format('REVOKE ALL ON TABLE financing_requests,financing_request_events FROM %I', app_role);
    END IF;
  END LOOP;
END $$;
