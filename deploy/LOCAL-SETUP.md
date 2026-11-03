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
