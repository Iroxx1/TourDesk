#!/usr/bin/env bash
# =============================================================================
#  TourDesk – Update
#
#    scripts/update.sh              # Backup → git pull → neu bauen → Migrationen → Neustart
#    scripts/update.sh --no-backup
#    scripts/update.sh --no-pull    # lokalen Stand neu bauen (z. B. nach manuellem Checkout)
#
#  Die Installationsart (native/docker) wird aus .install-mode übernommen.
# =============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP=1
PULL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-backup) BACKUP=0 ;;
    --no-pull) PULL=0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^#  \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done

MODE="$(cat "$ROOT/.install-mode" 2>/dev/null || echo native)"
cd "$ROOT"

if [ "$BACKUP" -eq 1 ]; then
  echo "▶ Backup vor dem Update"
  "$ROOT/scripts/backup.sh"
fi

if [ "$PULL" -eq 1 ] && [ -d "$ROOT/.git" ]; then
  echo "▶ Neue Version holen"
  git -C "$ROOT" pull --ff-only
fi

if [ "$MODE" = "docker" ]; then
  echo "▶ Container neu bauen und starten (Migrationen laufen beim Start der API)"
  docker compose build --pull
  docker compose up -d
  docker image prune -f >/dev/null 2>&1 || true
else
  echo "▶ Native Installation aktualisieren"
  "$ROOT/install.sh" --native --yes --no-admin
fi

PORT="$(grep -E '^TOURDESK_HTTP_PORT=' "$ROOT/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
PORT="${PORT:-8080}"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo "✔ Update abgeschlossen – TourDesk läuft ($(curl -fsS "http://127.0.0.1:${PORT}/api/health"))"
    exit 0
  fi
  sleep 2
done
echo "✘ TourDesk antwortet nach dem Update nicht. Logs prüfen (README → Fehlerbehebung)." >&2
exit 1
