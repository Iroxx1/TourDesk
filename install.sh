#!/usr/bin/env bash
# =============================================================================
#  TourDesk – Installation (Debian 12+/Ubuntu 22.04+, z. B. Proxmox-LXC)
#
#    sudo ./install.sh                  # native Installation (systemd) – empfohlen im LXC
#    sudo ./install.sh --docker         # Docker-Compose-Variante
#
#  Optionen:
#    --docker | --native          Installationsart (Standard: native bzw. wie zuvor installiert)
#    --port 8080                  HTTP-Port im LAN (Standard: 8080 bzw. bisheriger Port)
#    --public-url URL             spätere öffentliche Adresse (Cloudflare Tunnel)
#    --admin-user NAME            Admin-Benutzer anlegen (sonst Abfrage bzw. Web-Einrichtung)
#    --admin-email MAIL
#    --admin-password-stdin       Admin-Passwort von stdin lesen
#    --generate-admin-password    Admin-Passwort erzeugen und anzeigen
#    --no-admin                   keinen Admin anlegen (Ersteinrichtung im Browser)
#    --data-dir DIR               Datenverzeichnis (nativ, Standard /var/lib/tourdesk)
#    --yes                        keine Rückfragen
#
#  Das Skript ist idempotent: erneutes Ausführen aktualisiert die Installation,
#  vorhandene Secrets und Daten bleiben erhalten.
# =============================================================================
# shellcheck disable=SC1111  # German quotation marks in messages are intentional
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=""
PORT=""
PUBLIC_URL=""
ADMIN_USER=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
ADMIN_PW_STDIN=0
ADMIN_GENERATE=0
NO_ADMIN=0
ASSUME_YES=0
DATA_DIR=""
SERVICE_USER="tourdesk"
DB_NAME="${TOURDESK_DB_NAME:-tourdesk}"
DB_USER="${TOURDESK_DB_USER:-tourdesk}"
NODE_MIN_MAJOR=20
NODE_MIN_MINOR=19
NODE_DIST_VERSION="v22.12.0"

# ----------------------------------------------------------------------------- helpers
c_blue=$'\033[1;34m'; c_green=$'\033[1;32m'; c_yellow=$'\033[1;33m'; c_red=$'\033[1;31m'; c_off=$'\033[0m'
step() { printf '\n%s▶ %s%s\n' "$c_blue" "$*" "$c_off"; }
ok()   { printf '%s✔ %s%s\n' "$c_green" "$*" "$c_off"; }
warn() { printf '%s! %s%s\n' "$c_yellow" "$*" "$c_off" >&2; }
die()  { printf '%s✘ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }
trap 'die "Abbruch in Zeile $LINENO (Befehl: $BASH_COMMAND)"' ERR

usage() { sed -n '2,24p' "$0" | sed 's/^#  \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --docker) MODE="docker" ;;
    --native) MODE="native" ;;
    --port) PORT="${2:?}"; shift ;;
    --public-url) PUBLIC_URL="${2:?}"; shift ;;
    --admin-user) ADMIN_USER="${2:?}"; shift ;;
    --admin-email) ADMIN_EMAIL="${2:?}"; shift ;;
    --admin-password-stdin) ADMIN_PW_STDIN=1 ;;
    --generate-admin-password) ADMIN_GENERATE=1 ;;
    --no-admin) NO_ADMIN=1 ;;
    --data-dir) DATA_DIR="${2:?}"; shift ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage ;;
    *) die "Unbekannte Option: $1 (siehe --help)" ;;
  esac
  shift
done

# defaults: previous installation (re-run / update) → otherwise native, port 8080
# (must not fail: a first install has no .env yet, older ones may lack a key)
prev_env() { [ -f "$APP_DIR/.env" ] || return 0; grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true; }
[ -n "$MODE" ] || MODE="$(cat "$APP_DIR/.install-mode" 2>/dev/null || true)"
[ -n "$MODE" ] || MODE="native"
[ -n "$PORT" ] || PORT="$(prev_env TOURDESK_HTTP_PORT)"
[ -n "$PORT" ] || PORT="8080"
if [ -z "$DATA_DIR" ]; then
  DATA_DIR="$(prev_env TOURDESK_DATA_DIR)"
  case "$DATA_DIR" in /*) ;; *) DATA_DIR="/var/lib/tourdesk" ;; esac
fi
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "Ungültiger Port: $PORT"
[ "$(id -u)" -eq 0 ] || die "Bitte als root ausführen (z. B. sudo ./install.sh)."
[ -f "$APP_DIR/backend/pyproject.toml" ] || die "install.sh muss im TourDesk-Verzeichnis liegen."
command -v apt-get >/dev/null || die "Dieses Skript unterstützt Debian/Ubuntu (apt). Siehe README für andere Systeme."

if [ "$ADMIN_PW_STDIN" -eq 1 ]; then
  IFS= read -r ADMIN_PASSWORD || true
fi

interactive() { [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; }

random_secret() { python3 -c 'import secrets, sys; print(secrets.token_urlsafe(int(sys.argv[1])))' "${1:-48}"; }

lan_ip() { hostname -I 2>/dev/null | awk '{print $1}'; }

# set KEY=VALUE in .env (replace or append; keeps permissions of the file)
env_set() {
  local key="$1" value="$2" file="$APP_DIR/.env" tmp
  if grep -qE "^${key}=" "$file"; then
    tmp="$(mktemp)"
    KEY="$key" VALUE="$value" awk 'BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VALUE"] }
      index($0, k "=") == 1 { print k "=" v; next } { print }' "$file" >"$tmp"
    cat "$tmp" >"$file"
    rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}
env_get() { [ -f "$APP_DIR/.env" ] || return 0; grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true; }

wait_for_health() {
  local url="http://127.0.0.1:${PORT}/api/health"
  for _ in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

ask_admin() {
  [ "$NO_ADMIN" -eq 1 ] && return 0
  if [ -z "$ADMIN_USER" ] && interactive; then
    echo
    echo "Administrator anlegen (leer lassen = später im Browser über die Ersteinrichtung):"
    read -r -p "  Benutzername [admin]: " ADMIN_USER || true
    [ -n "$ADMIN_USER" ] || { read -r -p "  Admin jetzt anlegen? [J/n] " yn || true; case "${yn:-j}" in [nN]*) NO_ADMIN=1; return 0 ;; esac; ADMIN_USER="admin"; }
  fi
  [ -n "$ADMIN_USER" ] || { NO_ADMIN=1; return 0; }
  if [ -z "$ADMIN_EMAIL" ]; then
    if interactive; then read -r -p "  E-Mail: " ADMIN_EMAIL || true; fi
    [ -n "$ADMIN_EMAIL" ] || die "Für den Admin wird eine E-Mail-Adresse benötigt (--admin-email)."
  fi
  if [ -z "$ADMIN_PASSWORD" ] && [ "$ADMIN_GENERATE" -eq 0 ]; then
    if interactive; then
      local p1 p2
      read -r -s -p "  Passwort (mind. 10 Zeichen, leer = erzeugen): " p1 || true; echo
      if [ -z "$p1" ]; then
        ADMIN_GENERATE=1
      else
        read -r -s -p "  Passwort wiederholen: " p2 || true; echo
        [ "$p1" = "$p2" ] || die "Die Passwörter stimmen nicht überein."
        ADMIN_PASSWORD="$p1"
      fi
    else
      ADMIN_GENERATE=1
    fi
  fi
  if [ "$ADMIN_GENERATE" -eq 1 ] && [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(random_secret 18)"
    ADMIN_PASSWORD_GENERATED=1
  fi
  [ "${#ADMIN_PASSWORD}" -ge 10 ] || die "Das Admin-Passwort muss mindestens 10 Zeichen lang sein."
}

prepare_env() {
  step "Konfiguration (.env)"
  if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    env_set TOURDESK_SECRET_KEY "$(random_secret 48)"
    env_set POSTGRES_PASSWORD "$(random_secret 32)"
    ok ".env mit zufälligen Secrets erzeugt"
  else
    ok ".env vorhanden – Secrets bleiben unverändert"
    [ "$(env_get TOURDESK_SECRET_KEY)" != "bitte-ersetzen" ] || env_set TOURDESK_SECRET_KEY "$(random_secret 48)"
    [ "$(env_get POSTGRES_PASSWORD)" != "bitte-ersetzen" ] || env_set POSTGRES_PASSWORD "$(random_secret 32)"
  fi
  env_set TOURDESK_HTTP_PORT "$PORT"
  env_set TOURDESK_PORT "$PORT"
  if [ -n "$PUBLIC_URL" ]; then env_set TOURDESK_PUBLIC_URL "$PUBLIC_URL"; fi
  chmod 640 "$APP_DIR/.env"
}

print_summary() {
  local ip; ip="$(lan_ip)"
  echo
  printf '%s══════════════════════════════════════════════════════════════════%s\n' "$c_green" "$c_off"
  printf '%s  TourDesk läuft.%s\n' "$c_green" "$c_off"
  printf '  Im Browser öffnen:  http://%s:%s\n' "${ip:-<IP-des-Servers>}" "$PORT"
  if [ "$NO_ADMIN" -eq 1 ]; then
    echo   "  Ersteinrichtung:    beim ersten Aufruf im LAN den Admin anlegen"
  elif [ "${ADMIN_EXISTED:-0}" -eq 1 ]; then
    echo   "  Admin-Benutzer:     $ADMIN_USER (bestand bereits – Passwort unverändert)"
  else
    echo   "  Admin-Benutzer:     $ADMIN_USER"
    if [ "${ADMIN_PASSWORD_GENERATED:-0}" -eq 1 ]; then
      echo "  Admin-Passwort:     $ADMIN_PASSWORD   (bitte notieren/ändern)"
    fi
  fi
  echo   "  Modus:              $MODE"
  if [ "$MODE" = "docker" ]; then
    echo "  Logs:               docker compose logs -f app worker scheduler"
    echo "  Status:             docker compose ps"
  else
    echo "  Logs:               journalctl -u 'tourdesk-*' -f   bzw. $DATA_DIR/logs/"
    echo "  Status:             systemctl status tourdesk-api tourdesk-worker tourdesk-scheduler"
  fi
  echo   "  Backup:             ./scripts/backup.sh      Update: ./scripts/update.sh"
  echo   "  Cloudflare Tunnel:  siehe README.md, Abschnitt „Cloudflare Tunnel“"
  printf '%s══════════════════════════════════════════════════════════════════%s\n' "$c_green" "$c_off"
}

# ----------------------------------------------------------------------------- native
python_ok() {
  command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
}

node_ok() {
  command -v node >/dev/null || return 1
  local v major minor
  v="$(node -v | tr -d v)"; major="${v%%.*}"; minor="$(echo "$v" | cut -d. -f2)"
  [ "$major" -gt "$NODE_MIN_MAJOR" ] || { [ "$major" -eq "$NODE_MIN_MAJOR" ] && [ "$minor" -ge "$NODE_MIN_MINOR" ]; }
}

install_node_tarball() {
  # Node.js is only needed to build the frontend; installed to /opt/tourdesk-node
  local arch dist url base
  case "$(uname -m)" in
    x86_64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) die "Keine Node.js-Binärversion für $(uname -m). Bitte Node.js >= 20.19 manuell installieren." ;;
  esac
  dist="node-${NODE_DIST_VERSION}-linux-${arch}"
  base="https://nodejs.org/dist/${NODE_DIST_VERSION}"
  url="${base}/${dist}.tar.xz"
  local tmp; tmp="$(mktemp -d)"
  curl -fsSL "$url" -o "$tmp/node.tar.xz"
  curl -fsSL "${base}/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
  (cd "$tmp" && grep " ${dist}.tar.xz\$" SHASUMS256.txt | sed "s#${dist}.tar.xz#node.tar.xz#" | sha256sum -c -) >/dev/null \
    || die "Prüfsumme des Node.js-Downloads stimmt nicht."
  rm -rf /opt/tourdesk-node && mkdir -p /opt/tourdesk-node
  tar -xJf "$tmp/node.tar.xz" -C /opt/tourdesk-node --strip-components=1
  rm -rf "$tmp"
  export PATH="/opt/tourdesk-node/bin:$PATH"
}

native_install() {
  step "Pakete installieren"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates curl xz-utils git python3 python3-venv python3-pip postgresql postgresql-contrib >/dev/null
  python_ok || die "Python 3.11 oder neuer wird benötigt (Debian 12+, Ubuntu 24.04+)."
  ok "Python $(python3 -V | cut -d' ' -f2), PostgreSQL $(psql -V | awk '{print $3}')"

  if [ -x /opt/tourdesk-node/bin/node ]; then export PATH="/opt/tourdesk-node/bin:$PATH"; fi
  if ! node_ok; then
    step "Node.js ${NODE_DIST_VERSION} für den Frontend-Build"
    install_node_tarball
  fi
  ok "Node.js $(node -v)"

  step "Systembenutzer und Verzeichnisse"
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 750 "$DATA_DIR" "$DATA_DIR/logs" "$DATA_DIR/media"
  chgrp "$SERVICE_USER" "$APP_DIR/.env"
  runuser -u "$SERVICE_USER" -- test -r "$APP_DIR/backend/pyproject.toml" \
    || die "Der Dienstbenutzer kann $APP_DIR nicht lesen. Bitte TourDesk z. B. nach /opt/tourdesk klonen."
  ok "Benutzer $SERVICE_USER, Daten in $DATA_DIR"

  step "Datenbank"
  systemctl enable --now postgresql >/dev/null 2>&1 || service postgresql start >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do runuser -u postgres -- pg_isready -q && break; sleep 1; done
  local db_pw; db_pw="$(env_get POSTGRES_PASSWORD)"
  local role_exists db_exists
  role_exists="$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")"
  if [ "$role_exists" != "1" ]; then
    runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -v role="$DB_USER" -v pw="$db_pw" <<'SQL'
CREATE ROLE :"role" LOGIN PASSWORD :'pw';
SQL
  else
    runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -v role="$DB_USER" -v pw="$db_pw" <<'SQL'
ALTER ROLE :"role" WITH LOGIN PASSWORD :'pw';
SQL
  fi
  db_exists="$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")"
  [ "$db_exists" = "1" ] || runuser -u postgres -- createdb -O "$DB_USER" -E UTF8 -T template0 "$DB_NAME"
  env_set TOURDESK_DATABASE_URL "postgresql+psycopg://${DB_USER}:${db_pw}@127.0.0.1:5432/${DB_NAME}"
  env_set TOURDESK_DATA_DIR "$DATA_DIR"
  ok "PostgreSQL-Datenbank „${DB_NAME}“ bereit"

  step "Python-Umgebung"
  if [ ! -x "$APP_DIR/.venv/bin/python" ]; then python3 -m venv "$APP_DIR/.venv"; fi
  "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR/backend" -e "$APP_DIR/crawler"
  ok "Backend und Crawler installiert"

  step "Frontend bauen"
  (cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund --ignore-scripts --loglevel=error && npm run build --silent)
  ok "Frontend gebaut ($APP_DIR/frontend/dist)"

  step "Migrationen und Stammdaten"
  run_as_service() { runuser -u "$SERVICE_USER" -- env TOURDESK_HOME="$APP_DIR" "$APP_DIR/.venv/bin/tourdesk" "$@"; }
  run_as_service migrate --wait 60
  run_as_service seed --wait 60
  ok "Datenbank migriert, Geodaten/Venues/Festivals geladen"

  if [ "$NO_ADMIN" -eq 0 ]; then
    step "Administrator"
    admin_out="$(printf '%s\n' "$ADMIN_PASSWORD" | run_as_service create-admin --if-missing --username "$ADMIN_USER" --email "$ADMIN_EMAIL" --password-stdin)"
    echo "$admin_out"
    case "$admin_out" in *übersprungen*) ADMIN_EXISTED=1 ;; esac
  fi

  # CLI wrapper: "tourdesk <befehl>" runs as the service user with the right environment
  cat >/usr/local/bin/tourdesk <<WRAP
#!/bin/sh
# TourDesk-CLI als Dienstbenutzer (erzeugt von install.sh)
exec runuser -u ${SERVICE_USER} -- env TOURDESK_HOME=${APP_DIR} ${APP_DIR}/.venv/bin/tourdesk "\$@"
WRAP
  chmod 0755 /usr/local/bin/tourdesk

  step "systemd-Dienste"
  write_unit tourdesk-api "TourDesk Web/API" api
  write_unit tourdesk-worker "TourDesk Crawler-Worker" worker
  write_unit tourdesk-scheduler "TourDesk Scheduler" scheduler
  systemctl daemon-reload
  systemctl enable tourdesk-api tourdesk-worker tourdesk-scheduler >/dev/null
  systemctl restart tourdesk-api
  wait_for_health || { journalctl -u tourdesk-api -n 50 --no-pager || true; die "Die API startet nicht."; }
  systemctl restart tourdesk-worker tourdesk-scheduler
  ok "Dienste laufen: tourdesk-api, tourdesk-worker, tourdesk-scheduler"
  echo "native" >"$APP_DIR/.install-mode"
}

write_unit() {
  local name="$1" description="$2" role="$3"
  cat >"/etc/systemd/system/${name}.service" <<UNIT
[Unit]
Description=${description}
After=network-online.target postgresql.service
Wants=network-online.target
$( [ "$role" = "api" ] || echo "After=tourdesk-api.service" )

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=TOURDESK_HOME=${APP_DIR}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${APP_DIR}/.venv/bin/tourdesk ${role}
Restart=always
RestartSec=5
TimeoutStopSec=30
# Härtung
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${DATA_DIR}
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
UNIT
}

# ----------------------------------------------------------------------------- docker
docker_install() {
  step "Docker"
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends ca-certificates curl gnupg >/dev/null
    . /etc/os-release
    local distro="${ID}"
    case "$distro" in debian|ubuntu) ;; *) distro="debian" ;; esac
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} ${VERSION_CODENAME} stable" \
      >/etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
  if ! docker info >/dev/null 2>&1; then
    if [ "$(systemd-detect-virt -c 2>/dev/null || true)" = "lxc" ]; then
      die "Docker läuft im LXC nicht. In Proxmox beim Container „nesting=1,keyctl=1“ aktivieren (Optionen → Features) oder ohne --docker installieren."
    fi
    die "Docker-Daemon ist nicht erreichbar."
  fi
  ok "$(docker --version)"

  step "Container bauen und starten"
  (cd "$APP_DIR" && docker compose up -d --build)
  wait_for_health || { (cd "$APP_DIR" && docker compose logs --tail=80 app) || true; die "Die API startet nicht."; }
  ok "Container laufen"

  if [ "$NO_ADMIN" -eq 0 ]; then
    step "Administrator"
    admin_out="$(printf '%s\n' "$ADMIN_PASSWORD" | (cd "$APP_DIR" && docker compose exec -T app tourdesk create-admin --if-missing \
      --username "$ADMIN_USER" --email "$ADMIN_EMAIL" --password-stdin))"
    echo "$admin_out"
    case "$admin_out" in *übersprungen*) ADMIN_EXISTED=1 ;; esac
  fi
  echo "docker" >"$APP_DIR/.install-mode"
}

# ----------------------------------------------------------------------------- main
echo "${c_blue}TourDesk-Installation${c_off} – Modus: ${MODE}, Port: ${PORT}"
if ! command -v python3 >/dev/null || ! command -v curl >/dev/null; then
  step "Basispakete"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends ca-certificates curl python3 >/dev/null
fi
if [ "$MODE" = "native" ] && [ "$(systemd-detect-virt -c 2>/dev/null || true)" = "lxc" ]; then
  ok "Proxmox-/LXC-Container erkannt – native Installation ist hier die schlankste Variante"
fi
ask_admin
prepare_env
if [ "$MODE" = "docker" ]; then docker_install; else native_install; fi
print_summary
