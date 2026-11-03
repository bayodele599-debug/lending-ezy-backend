-- Lending Ezy account-based planning + private communication.
-- Apply after 20261103 financing and inquiry migrations. All routes are opt-in.
CREATE TABLE IF NOT EXISTS customers (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(254) NOT NULL UNIQUE,
    full_name VARCHAR(120) NOT NULL,
    country VARCHAR(2) NOT NULL,
    password_digest VARCHAR(250) NOT NULL,
    email_verified_at TIMESTAMPTZ,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_customer_country CHECK (country ~ '^[A-Z]{2}$')
);
CREATE INDEX IF NOT EXISTS ix_customers_email ON customers(email);

CREATE TABLE IF NOT EXISTS customer_sessions (
    id VARCHAR(36) PRIMARY KEY,
    customer_id VARCHAR(36) NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    token_digest VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_customer_sessions_customer_id ON customer_sessions(customer_id);
CREATE INDEX IF NOT EXISTS ix_customer_sessions_token_digest ON customer_sessions(token_digest);

CREATE TABLE IF NOT EXISTS account_tokens (
    id VARCHAR(36) PRIMARY KEY,
    customer_id VARCHAR(36) NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    kind VARCHAR(12) NOT NULL,
    token_digest VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_account_token_kind CHECK (kind IN ('verify','reset'))
);
CREATE INDEX IF NOT EXISTS ix_account_tokens_customer_id ON account_tokens(customer_id);
CREATE INDEX IF NOT EXISTS ix_account_tokens_token_digest ON account_tokens(token_digest);

CREATE TABLE IF NOT EXISTS customer_plans (
    id VARCHAR(36) PRIMARY KEY,
    customer_id VARCHAR(36) NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,
    purpose VARCHAR(80) NOT NULL,
    country VARCHAR(2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    amount NUMERIC(16,2) NOT NULL,
    months INTEGER NOT NULL,
    annual_rate NUMERIC(5,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_customer_plan_type CHECK (type IN ('personal','business')),
    CONSTRAINT chk_customer_plan_amount CHECK (amount >= 500 AND amount <= 10000000),
    CONSTRAINT chk_customer_plan_rate CHECK (annual_rate >= 0 AND annual_rate <= 40)
);
CREATE INDEX IF NOT EXISTS ix_customer_plans_customer_id ON customer_plans(customer_id);

-- Anonymous financing requests are never automatically claimed by matching
-- an email: this association is set only for authenticated submissions.
ALTER TABLE financing_requests ADD COLUMN IF NOT EXISTS customer_id VARCHAR(36) REFERENCES customers(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_financing_requests_customer_id ON financing_requests(customer_id);

CREATE TABLE IF NOT EXISTS financing_request_messages (
    id VARCHAR(36) PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL REFERENCES financing_requests(id) ON DELETE CASCADE,
    author VARCHAR(20) NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_financing_message_author CHECK (author IN ('admin','customer'))
);
CREATE INDEX IF NOT EXISTS ix_financing_request_messages_request_id ON financing_request_messages(request_id);

-- Account and request data are server-owned and never directly exposed via
-- generic PostgREST/Supabase roles.
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE financing_request_messages ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE app_role TEXT;
BEGIN
  FOREACH app_role IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
      EXECUTE format('REVOKE ALL ON TABLE customers,customer_sessions,account_tokens,customer_plans,financing_request_messages FROM %I',app_role);
    END IF;
  END LOOP;
END $$;
