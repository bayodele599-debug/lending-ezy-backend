#!/usr/bin/env bash
set -euo pipefail
umask 077
if [ -z "${AGE_RECIPIENT:-}" ] || [ -z "${BACKUP_DIR:-}" ]; then
  echo "Set AGE_RECIPIENT and BACKUP_DIR" >&2
  exit 1
fi
command -v age >/dev/null
command -v docker >/dev/null
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/lending-ezy-$stamp.pgdump.age"
docker compose --env-file .env.contabo -f deploy/compose.contabo.yml exec -T db \
  sh -ec 'pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  | age -r "$AGE_RECIPIENT" > "$target"
test -s "$target" || { rm -f "$target"; exit 1; }
echo "Encrypted dump created: $target"
echo "Transfer off-host and verify restore in an isolated database."
