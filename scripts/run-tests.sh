#!/usr/bin/env bash
# Runs all automated checks: lint, backend/crawler tests, frontend typecheck + build.
#
#   scripts/run-tests.sh          # lint + pytest + frontend
#   scripts/run-tests.sh --e2e    # additionally the Playwright end-to-end tests
#
# The Python tests need a PostgreSQL test database (default: tourdesk_test, it is wiped).
# Override with TOURDESK_TEST_DATABASE_URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${TOURDESK_VENV:-$ROOT/.venv}"
cd "$ROOT"

echo "▶ Ruff"
"$VENV/bin/ruff" check backend crawler tests scripts migrations

echo "▶ Pytest"
"$VENV/bin/python" -m pytest tests -q

echo "▶ Frontend (Typecheck + Build)"
(cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)

if [ "${1:-}" = "--e2e" ]; then
  shift
  "$ROOT/scripts/run-e2e.sh" "$@"
fi
echo "✔ Alle Prüfungen erfolgreich"
