-- Initial inquiry tables for a dedicated Lending Ezy PostgreSQL database.
CREATE TABLE IF NOT EXISTS contact_inquiries (
 id VARCHAR(36) PRIMARY KEY, kind VARCHAR(32) NOT NULL, name VARCHAR(120) NOT NULL,
 email VARCHAR(254) NOT NULL, country VARCHAR(2) NOT NULL, product_interest VARCHAR(50),
 institution VARCHAR(150), message TEXT, status VARCHAR(32) NOT NULL DEFAULT 'new',
 consent_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_contact_inquiries_kind ON contact_inquiries(kind);
CREATE INDEX IF NOT EXISTS ix_contact_inquiries_email ON contact_inquiries(email);
CREATE INDEX IF NOT EXISTS ix_contact_inquiries_status ON contact_inquiries(status);
CREATE TABLE IF NOT EXISTS inquiry_replies (
 id VARCHAR(36) PRIMARY KEY, inquiry_id VARCHAR(36) NOT NULL REFERENCES contact_inquiries(id),
 body TEXT NOT NULL, delivery_status VARCHAR(20) NOT NULL DEFAULT 'draft',
 created_at TIMESTAMPTZ NOT NULL, sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_inquiry_replies_inquiry_id ON inquiry_replies(inquiry_id);
ALTER TABLE contact_inquiries ENABLE ROW LEVEL SECURITY;
ALTER TABLE inquiry_replies ENABLE ROW LEVEL SECURITY;
