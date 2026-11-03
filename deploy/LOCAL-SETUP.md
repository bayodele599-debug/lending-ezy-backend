# Run Lending Ezy locally (Windows 11)

Prerequisites: Git, Docker Desktop with Docker Engine running, Node.js 22+, and Python 3.12 (or Python 3). Ports 3000, 3001, 8000 and 55432 must be free.

Clone the backend (or update your existing clean main branch), open PowerShell in its repository root, and run:

    powershell -ExecutionPolicy Bypass -File .\deploy\Start-LendingEzy.ps1

The script checks out the frontend/admin alongside the backend when absent, creates a dedicated persistent PostgreSQL Docker volume, applies contact/financing migrations, installs dependencies, writes local-only credentials, starts FastAPI and both Next.js apps, and executes an HTTP/database/admin-status test with synthetic information.

Open:
- Customer: http://127.0.0.1:3000
- Admin review: http://127.0.0.1:3001/requests
- Backend API docs: http://127.0.0.1:8000/docs
- PostgreSQL: localhost:55432 (local-only)

The script prints a newly generated local admin password. Environment files are not committed. It refuses to overwrite existing frontend/admin environment files that it did not generate, and it does not stop or reuse unrelated processes on occupied ports.

To stop services without removing the database volume:

    powershell -ExecutionPolicy Bypass -File .\deploy\Stop-LendingEzy.ps1

To re-run only the synthetic HTTP smoke test when services are already running, open PowerShell in the backend repository and ensure APP_ENV=development and ADMIN_API_TOKEN matches .env.local.test, then run the backend virtual environment's Python executable with tests/live_smoke.py.

Use dummy names and email addresses only in the local development stack. Production credentials and live personal data must never be used in this test environment.

Automated CI runs the same backend HTTP smoke test against a disposable PostgreSQL 16 service. It does not access your Windows files or Contabo host.


## Customer accounts and private case messaging (local only)

The local launcher now also starts **Mailpit**, a private disposable email inbox.
It enables customer account features in local development, while production
feature flags remain disabled by default. No emails are sent to external users.

1. Open http://127.0.0.1:3000/account and register with a synthetic email.
2. Open http://127.0.0.1:8025 to find your verification link.
3. Verify the email, sign in, and create an account plan or explicitly import
   local browser plans. They are stored in PostgreSQL, not browser storage.
4. With the account signed in, submit a plan from My Plans. The same verified
   email must be used to link the request to the account.
5. Sign into the admin at http://127.0.0.1:3001/requests, review that case, and
   send a customer-visible message from the Conversation panel.
6. Open the customer account's Requests section to reply; internal admin notes
   are never shown in the customer's message thread.
7. Test password-reset links through Mailpit.

Anonymous requests submitted before registration do not automatically attach
to an account, even when their email address matches. Use an authenticated
submission to make a linked case.

The Windows launch scripts start and stop only this workspace's own services;
the database volume persists between runs. Never use personal borrower data
for local testing, and never expose Mailpit outside loopback.

Customer account services require SMTP and privacy/retention policy review
before production launch; neither the preview UI nor backend API is production
enabled by merely merging this code.
