#!/usr/bin/env bash
# Clean scratch Postgres 16 + pgvector on port 5544, roles from docker/postgres-init, every package migrated in CI order.
# This is the DISPOSABLE verification database (metrion-verify-pg). The persistent manual-testing database is `metrion-manual-pg`, also on 5544
# (docs/ci-v3-local-testing.md): only one of the two may run at a time, and `up` refuses while the manual one is running. `down` removes only metrion-verify-pg.
# Usage: bash backend/scripts/scratch_db.sh up|down        (then `source` the env printed by `env`)
set -euo pipefail
export MSYS_NO_PATHCONV=1
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME=metrion-verify-pg
case "${1:-up}" in
  down) docker rm -f "$NAME" >/dev/null 2>&1 || true; exit 0 ;;
  env) cat <<'EOF'
export DATABASE_URL="postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5544/metrion"
export DATABASE_URL_APP="postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5544/metrion"
export CLERK_SECRET_KEY=sk_test_ci_placeholder CLERK_WEBHOOK_SECRET=whsec_ci_placeholder FRONTEND_ORIGIN=http://localhost:3000
export CLERK_JWT_KEY=$'-----BEGIN PUBLIC KEY-----\nCIPLACEHOLDER\n-----END PUBLIC KEY-----'
EOF
  exit 0 ;;
esac
if [ "$(docker ps -q -f name='^metrion-manual-pg$')" ]; then
  echo "metrion-manual-pg (persistent manual-testing DB) is running on 5544. Stop it first: docker stop metrion-manual-pg" >&2; exit 1
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -e POSTGRES_USER=metrion -e POSTGRES_PASSWORD=metrion_dev_password -e POSTGRES_DB=metrion -p 5544:5432 \
  -v "$(cygpath -w "$ROOT/docker/postgres-init"):/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg16 >/dev/null
for i in $(seq 1 60); do docker exec "$NAME" pg_isready -U metrion -d metrion >/dev/null 2>&1 && break; sleep 1; done
sleep 3
eval "$(bash "$0" env)"
for pkg in calc-engine data-foundation competitor-intelligence cfo product-intelligence slim-cmo; do
  (cd "$ROOT/packages/$pkg" && python -m alembic upgrade head >/dev/null)
done
(cd "$ROOT/backend" && python -m alembic upgrade head >/dev/null)
echo "scratch db ready on :5544"
