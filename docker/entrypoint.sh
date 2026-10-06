#!/bin/sh
# TourDesk container entrypoint.
#   api        migrations + seed data, optional admin from env, then the web server
#   worker     crawler worker
#   scheduler  crawler scheduler
#   <other>    passed to the "tourdesk" CLI, e.g. "create-admin --username …"
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
  api)
    tourdesk migrate --wait 120
    tourdesk seed --wait 120
    if [ -n "${TOURDESK_ADMIN_USERNAME:-}" ] && [ -n "${TOURDESK_ADMIN_EMAIL:-}" ] && [ -n "${TOURDESK_ADMIN_PASSWORD:-}" ]; then
      printf '%s\n' "$TOURDESK_ADMIN_PASSWORD" | tourdesk create-admin --if-missing \
        --username "$TOURDESK_ADMIN_USERNAME" --email "$TOURDESK_ADMIN_EMAIL" --password-stdin
    fi
    exec tourdesk api
    ;;
  worker)
    exec tourdesk worker
    ;;
  scheduler)
    exec tourdesk scheduler
    ;;
  *)
    exec tourdesk "$role" "$@"
    ;;
esac
