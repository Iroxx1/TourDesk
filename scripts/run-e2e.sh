#!/usr/bin/env bash
# Runs the Playwright end-to-end tests against a throw-away database.
#
#   scripts/run-e2e.sh                 # all E2E tests
#   scripts/run-e2e.sh -g "Filter"     # extra arguments are passed to "playwright test"
#
# Requirements: PostgreSQL database for the tests (default tourdesk_e2e, it is wiped!),
# Python venv with TourDesk installed (.venv), Node.js 20+, a Chromium for Playwright
# (installed with "npx playwright install chromium" inside tests/e2e if missing).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_URL="${TOURDESK_E2E_DATABASE_URL:-postgresql+psycopg://tourdesk:tourdesk@127.0.0.1:5432/tourdesk_e2e}"
PORT="${TOURDESK_E2E_PORT:-8090}"
VENV="${TOURDESK_VENV:-$ROOT/.venv}"
WORK="$(mktemp -d)"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

case "$DB_URL" in
  *tourdesk_e2e*|*_test*) ;;
  *) echo "Abbruch: TOURDESK_E2E_DATABASE_URL muss auf eine Testdatenbank zeigen (wird geleert)." >&2; exit 2 ;;
esac

export TOURDESK_DATABASE_URL="$DB_URL"
export TOURDESK_ENV=development
export TOURDESK_DATA_DIR="$WORK/data"
export TOURDESK_HOST=127.0.0.1
export TOURDESK_PORT="$PORT"
export TOURDESK_LOG_TO_FILE=false
export TOURDESK_LOG_LEVEL=WARNING
export TOURDESK_WORKER_THREADS=2

echo "▶ Datenbank zurücksetzen"
"$VENV/bin/python" - <<PY
import sqlalchemy as sa
engine = sa.create_engine("$DB_URL")
with engine.begin() as conn:
    conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(sa.text("CREATE SCHEMA public"))
PY

echo "▶ Migrationen und Seed-Daten"
"$VENV/bin/tourdesk" init >/dev/null

if [ ! -f "$ROOT/frontend/dist/index.html" ] || [ "${TOURDESK_E2E_BUILD:-1}" = "1" ]; then
  echo "▶ Frontend bauen"
  (cd "$ROOT/frontend" && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build >/dev/null)
fi

echo "▶ API und Worker starten (Port $PORT)"
"$VENV/bin/tourdesk" api >"$WORK/api.log" 2>&1 &
PIDS+=($!)
"$VENV/bin/tourdesk" worker >"$WORK/worker.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "API startet nicht:"; cat "$WORK/api.log"; exit 1; }

echo "▶ Playwright"
cd "$ROOT/tests/e2e"
[ -d node_modules ] || npm install --no-audit --no-fund
status=0
TOURDESK_E2E_URL="http://127.0.0.1:$PORT" npx playwright test "$@" || status=$?
if [ "$status" -ne 0 ]; then
  echo "── API-Log ──"; tail -n 60 "$WORK/api.log" || true
  echo "── Worker-Log ──"; tail -n 60 "$WORK/worker.log" || true
fi
exit "$status"
