#!/usr/bin/env bash
# =============================================================================
#  TourDesk – Wiederherstellung aus einem Backup von scripts/backup.sh
#
#    scripts/restore.sh backups/tourdesk-20270312-031500.tar.gz
#    scripts/restore.sh <archiv> --with-config     # auch .env zurückspielen
#    scripts/restore.sh <archiv> --yes             # ohne Rückfrage
#
#  Ablauf: Dienste stoppen → Datenbank ersetzen → (Bilder, Konfiguration) →
#  Migrationen → Dienste starten. Die aktuelle .env wird bei --with-config als
#  .env.before-restore aufbewahrt.
# =============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE=""
WITH_CONFIG=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --with-config) WITH_CONFIG=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^#  \{0,1\}//'; exit 0 ;;
    -*) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    *) ARCHIVE="$1" ;;
  esac
  shift
done
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "Bitte ein Backup-Archiv angeben (siehe --help)." >&2; exit 2; }

env_get() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -n1 | cut -d= -f2-; }
MODE="$(cat "$ROOT/.install-mode" 2>/dev/null || echo native)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -C "$WORK" -xzf "$ARCHIVE"
[ -s "$WORK/database.dump" ] || { echo "Archiv enthält keinen Datenbank-Dump." >&2; exit 1; }
echo "Backup: $(tr '\n' ' ' <"$WORK/manifest.txt" 2>/dev/null)"

if [ "$ASSUME_YES" -eq 0 ]; then
  read -r -p "Die aktuelle TourDesk-Datenbank wird ERSETZT. Fortfahren? [j/N] " answer
  case "$answer" in [jJyY]*) ;; *) echo "Abgebrochen."; exit 1 ;; esac
fi

if [ "$WITH_CONFIG" -eq 1 ] && [ -f "$WORK/config/.env" ]; then
  echo "▶ Konfiguration zurückspielen"
  [ -f "$ROOT/.env" ] && cp -p "$ROOT/.env" "$ROOT/.env.before-restore"
  cp -p "$WORK/config/.env" "$ROOT/.env"
fi

if [ "$MODE" = "docker" ]; then
  cd "$ROOT"
  echo "▶ Dienste stoppen"
  docker compose stop app worker scheduler
  docker compose up -d db
  for _ in $(seq 1 30); do docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER"' >/dev/null 2>&1 && break; sleep 2; done
  echo "▶ Datenbank ersetzen"
  docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'
  docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --role="$POSTGRES_USER" --exit-on-error' <"$WORK/database.dump"
  if [ -f "$WORK/media.tar.gz" ]; then
    echo "▶ Bilder zurückspielen"
    docker compose run --rm --no-deps -T --entrypoint sh app -c 'rm -rf /data/media && tar -xzf - -C /data' <"$WORK/media.tar.gz"
  fi
  echo "▶ Dienste starten (Migrationen laufen beim Start)"
  docker compose up -d
else
  DB_URL="$(env_get TOURDESK_DATABASE_URL)"
  [ -n "$DB_URL" ] || { echo "TOURDESK_DATABASE_URL fehlt in $ROOT/.env" >&2; exit 1; }
  DB_NAME="${DB_URL##*/}"; DB_NAME="${DB_NAME%%\?*}"
  DB_USER="${DB_URL#*://}"; DB_USER="${DB_USER%%:*}"
  DATA_DIR="$(env_get TOURDESK_DATA_DIR)"; DATA_DIR="${DATA_DIR:-/var/lib/tourdesk}"
  echo "▶ Dienste stoppen"
  systemctl stop tourdesk-scheduler tourdesk-worker tourdesk-api 2>/dev/null || true
  echo "▶ Datenbank ersetzen ($DB_NAME)"
  runuser -u postgres -- dropdb --if-exists --force "$DB_NAME"
  runuser -u postgres -- createdb -O "$DB_USER" -E UTF8 -T template0 "$DB_NAME"
  pg_restore -d "${DB_URL/+psycopg/}" --no-owner --role="$DB_USER" --exit-on-error "$WORK/database.dump"
  if [ -f "$WORK/media.tar.gz" ]; then
    echo "▶ Bilder zurückspielen"
    rm -rf "${DATA_DIR:?}/media"
    tar -xzf "$WORK/media.tar.gz" -C "$DATA_DIR"
    chown -R tourdesk:tourdesk "$DATA_DIR/media" 2>/dev/null || true
  fi
  echo "▶ Migrationen"
  runuser -u tourdesk -- env TOURDESK_HOME="$ROOT" "$ROOT/.venv/bin/tourdesk" migrate
  echo "▶ Dienste starten"
  systemctl start tourdesk-api tourdesk-worker tourdesk-scheduler
fi
echo "✔ Wiederherstellung abgeschlossen."
