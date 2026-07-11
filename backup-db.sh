#!/usr/bin/env bash
#
# Dump the production Postgres database and upload a gzipped snapshot to
# Cloudflare R2. Intended to run from the repo root (where docker-compose.prod.yml
# and .env.prod live), typically from cron:
#
#   0 3 * * *  cd /srv/voocab && ./backup-db.sh >> /var/log/voocab-backup.log 2>&1
#
# Requirements on the host: docker compose and the AWS CLI (`aws`), which talks
# to R2 via its S3-compatible API.
set -euo pipefail

cd "$(dirname "$0")"

# Load DB + R2 credentials from .env.prod into the environment.
set -a
# shellcheck disable=SC1091
source .env.prod
set +a

COMPOSE="docker compose -f docker-compose.prod.yml"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILENAME="voocab-${TIMESTAMP}.sql.gz"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "[backup] dumping database ${POSTGRES_DB}…"
$COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "${TMPDIR}/${FILENAME}"

echo "[backup] uploading ${FILENAME} to R2 bucket ${R2_BUCKET}…"
aws s3 cp "${TMPDIR}/${FILENAME}" "s3://${R2_BUCKET}/db-backups/${FILENAME}" \
  --endpoint-url "$R2_ENDPOINT"

echo "[backup] done: db-backups/${FILENAME}"
