# Lending Ezy Backend

FastAPI platform API for consent-based financing enquiries, a human-administered review desk, and repayment estimates. This is separate from regulated credit origination.

## What works

- Public \`POST /api/v1/financing-requests\` accepts a consented personal/business financing request with an idempotency key, bounded country/currency/amount/term and an assumed rate. No ID documents or bank credentials are accepted.
- Secured administrator \`GET /api/v1/admin/financing-requests\` (filters, pagination), \`GET /api/v1/admin/financing-requests/{id}\` (financial estimate and review history), and \`PATCH .../{id}\` (manual status transitions with mandatory note and optimistic concurrency).
- Case statuses: submitted, in_review, needs_information, proceed_to_next_stage, not_proceeding, closed. These are internal reviews, not binding approvals or loan offers.
- Every change writes an auditable event. The current shared-key authentication identifies the actor as "admin"; individual operator attribution needs named accounts/roles.
- Existing consent-based contact enquiries and secured inbox remain unchanged.
- Existing isolated development sandbox endpoints remain disabled in production.

## Run locally

\`\`\`bash
python -m venv .venv
pip install -r requirements-dev.txt
python -m pytest -q
uvicorn app.main:app --reload
\`\`\`

Development creates tables automatically. Use a dedicated development database. API schema: \`/docs\`.

## Deploy safely

1. Provision a dedicated PostgreSQL database and persistent API host; do not share the DB with another project.
2. Apply \`migrations/20261103_financing_requests.sql\` to the production database and ensure the original inquiry tables have been deployed.
3. Set \`APP_ENV=production\`, \`ENABLE_SANDBOX=false\`, \`PUBLIC_FINANCING_REQUESTS_ENABLED=false\`, \`DATABASE_URL\`, \`CORS_ORIGINS\` (exact frontend origins), and a random \`ADMIN_API_TOKEN\` of at least 32 characters (same secret on admin server).
4. Configure \`TURNSTILE_SECRET_KEY\` on API and the matching site key on the public frontend. Public intake refuses unverified submissions in production.
5. Connect the admin \`INTERNAL_API_URL\` and auth env vars, verify the admin inbox and financing review desk with no PII leakage, then enable \`PUBLIC_FINANCING_REQUESTS_ENABLED=true\` and \`NEXT_PUBLIC_FINANCING_REQUESTS_ENABLED=true\`.
6. Configure optional SMTP notification/reply settings and document retention, data subject rights, backups, access controls, key rotation and incident procedures before collecting real names/emails.

This application does **not** implement credit scoring, KYC, a binding credit decision, payments, disbursements, instalment collection, or lender authorisation. Internal status \`proceed_to_next_stage\` is not credit approval.
