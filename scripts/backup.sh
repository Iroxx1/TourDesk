#!/usr/bin/env bash
# =============================================================================
#  TourDesk – Backup
#
#    scripts/backup.sh                    # Datenbank + Konfiguration
#    scripts/backup.sh --with-media       # zusätzlich gecachte Künstlerbilder/Avatare
#    scripts/backup.sh --output /mnt/nas/tourdesk --keep 30
#
#  Ergebnis: <output>/tourdesk-JJJJMMTT-HHMMSS.tar.gz mit
#    database.dump   PostgreSQL-Dump (pg_dump --format=custom)
#    config/.env     Konfiguration inkl. Secrets  → Archiv sicher aufbewahren!
#    media.tar.gz    (optional) Bilder
#    manifest.txt    Version, Datum, Modus
#
#  Für automatische Backups z. B. per cron:
#    15 3 * * *  root  /opt/tourdesk/scripts/backup.sh --keep 14 >/var/log/tourdesk-backup.log 2>&1
# =============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="$ROOT/backups"
KEEP=14
WITH_MEDIA=0

while [ $# -gt 0 ]; do
  case "$1" in
    --with-media) WITH_MEDIA=1 ;;
    --output) OUTPUT="${2:?}"; shift ;;
    --keep) KEEP="${2:?}"; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^#  \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done

env_get() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -n1 | cut -d= -f2-; }
MODE="$(cat "$ROOT/.install-mode" 2>/dev/null || echo native)"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
umask 077
mkdir -p "$OUTPUT" "$WORK/config"

echo "▶ Datenbank sichern ($MODE)"
if [ "$MODE" = "docker" ]; then
  cd "$ROOT"
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' >"$WORK/database.dump"
else
  DB_URL="$(env_get TOURDESK_DATABASE_URL)"
  [ -n "$DB_URL" ] || { echo "TOURDESK_DATABASE_URL fehlt in $ROOT/.env" >&2; exit 1; }
  pg_dump "${DB_URL/+psycopg/}" --format=custom --no-owner -f "$WORK/database.dump"
fi
[ -s "$WORK/database.dump" ] || { echo "Datenbank-Dump ist leer" >&2; exit 1; }

echo "▶ Konfiguration sichern"
[ -f "$ROOT/.env" ] && cp -p "$ROOT/.env" "$WORK/config/.env"
[ -f "$ROOT/.install-mode" ] && cp -p "$ROOT/.install-mode" "$WORK/config/.install-mode"
[ -f "$ROOT/docker-compose.override.yml" ] && cp -p "$ROOT/docker-compose.override.yml" "$WORK/config/"
for unit in /etc/systemd/system/tourdesk-*.service; do
  [ -f "$unit" ] && cp -p "$unit" "$WORK/config/"
done

if [ "$WITH_MEDIA" -eq 1 ]; then
  echo "▶ Bilder sichern"
  if [ "$MODE" = "docker" ]; then
    docker compose exec -T app sh -c 'cd /data && tar -czf - media 2>/dev/null || true' >"$WORK/media.tar.gz"
  else
    DATA_DIR="$(env_get TOURDESK_DATA_DIR)"
    DATA_DIR="${DATA_DIR:-/var/lib/tourdesk}"
    [ -d "$DATA_DIR/media" ] && tar -C "$DATA_DIR" -czf "$WORK/media.tar.gz" media
  fi
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/tourdesk/__init__.py" 2>/dev/null || true)"
{
  echo "tourdesk_version=${VERSION:-unbekannt}"
  echo "created_at=$(date -Iseconds)"
  echo "mode=$MODE"
  echo "media=$WITH_MEDIA"
  echo "host=$(hostname)"
} >"$WORK/manifest.txt"

ARCHIVE="$OUTPUT/tourdesk-$STAMP.tar.gz"
tar -C "$WORK" -czf "$ARCHIVE" .
chmod 600 "$ARCHIVE"
echo "✔ Backup erstellt: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

if [ "$KEEP" -gt 0 ] 2>/dev/null; then
  mapfile -t old < <(ls -1t "$OUTPUT"/tourdesk-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)))
  for f in "${old[@]}"; do rm -f -- "$f" && echo "  alte Sicherung entfernt: $(basename "$f")"; done
fi
