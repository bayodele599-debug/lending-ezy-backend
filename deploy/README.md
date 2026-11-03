# Lending Ezy on Contabo

This deployment profile targets an existing Ubuntu 24.04 VPS with Docker Compose and an existing HTTPS proxy or Coolify. It does not purchase a server, change DNS, or affect other projects.

Architecture: customer and admin Next.js apps remain on Vercel; an isolated FastAPI service and private PostgreSQL 16 run on Contabo. The API listens only at 127.0.0.1:18080 on the VPS; PostgreSQL has no published port. Connect an existing HTTPS proxy to the loopback API listener.

## Initial deployment

1. Provision and harden Ubuntu 24.04 with SSH keys, automatic security updates, firewall and a restricted deploy user. Install Docker Engine and Compose.
2. Clone the approved Lending Ezy backend main branch.
3. Copy deploy/contabo.env.example to .env.contabo in the repository root; chmod 600 .env.contabo. Supply unique secrets, actual hostnames, and a URL-encoded database password in DATABASE_URL.
4. Start the dedicated DB: docker compose --env-file .env.contabo -f deploy/compose.contabo.yml up -d db
5. Run both SQL migrations: docker compose --env-file .env.contabo -f deploy/compose.contabo.yml --profile ops run --rm migrate
6. Start the API: docker compose --env-file .env.contabo -f deploy/compose.contabo.yml up -d --build api
7. Verify: curl --fail http://127.0.0.1:18080/health
8. Configure HTTPS for the selected API hostname through an existing reverse proxy/Coolify. Expose only SSH, HTTP and HTTPS; keep 5432 and 18080 private.
9. On Vercel customer frontend configure NEXT_PUBLIC_API_URL, NEXT_PUBLIC_TURNSTILE_SITE_KEY and later NEXT_PUBLIC_FINANCING_REQUESTS_ENABLED=true.
10. On Vercel admin configure private INTERNAL_API_URL, ADMIN_API_TOKEN, ADMIN_PASSWORD and ADMIN_SESSION_SECRET. The backend ADMIN_API_TOKEN must match the admin's value, but never expose it as NEXT_PUBLIC_.
11. Configure exact CORS_ORIGINS and private TURNSTILE_SECRET_KEY on Contabo. Verify database migrations, auth, frontend-to-API intake and admin reviews, then set PUBLIC_FINANCING_REQUESTS_ENABLED=true and restart API. Keep intake off during maintenance.

## Backups and operations

Install age encryption on the VPS. Set AGE_RECIPIENT to an off-server recipient's public key and BACKUP_DIR to a private directory; run deploy/backup.sh from the repository root on a regular schedule. Copy encrypted dumps off-server and perform separate isolated restore tests. Monitor API health, PostgreSQL, storage, TLS expiry, backup freshness and audit events.

A named-operator admin system, retention/deletion controls and local licensing review should precede regulated lending. The manual status proceed_to_next_stage is not a binding credit approval. No payment or disbursement is implemented.

If the VPS runs Coolify, deploy the API using that existing controller instead of launching duplicate services with this Compose profile. Do not install a second competing reverse proxy.
