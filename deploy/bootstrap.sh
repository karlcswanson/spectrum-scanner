#!/usr/bin/env bash
# deploy/bootstrap.sh — configure .env and bring up the Spectrum Scanner stack.
#
# Run this ON the server after cloning the repo (Docker must already be present —
# the cloud-init in this dir handles that). Idempotent: existing secrets in .env
# are preserved on re-run, so it won't rotate them and break your database.
#
# Usage:
#   ./deploy/bootstrap.sh                # LAN mode: auto-detect this host's IP + self-signed TLS
#   ./deploy/bootstrap.sh --ip 10.0.0.5  # LAN mode with an explicit IP
#   ./deploy/bootstrap.sh --domain x.com # PUBLIC mode: real domain + automatic Let's Encrypt
#   ./deploy/bootstrap.sh --pull         # use prebuilt GHCR images instead of building from source
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/../server" && pwd)"
COMPOSE=(docker compose -f docker-compose.prod.yml)

# ── args ──────────────────────────────────────────────────────────────────────
DOMAIN=""; IP=""; MODE_BUILD=1
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --ip)     IP="$2"; shift 2 ;;
    --pull)   MODE_BUILD=0; shift ;;
    --build)  MODE_BUILD=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

cd "$SERVER_DIR"

# ── env-safe random secret (no openssl/python dependency; URL-safe chars only) ─
gen() { ( set +o pipefail; LC_ALL=C tr -dc 'A-Za-z0-9_' </dev/urandom | head -c "${1:-50}" ); }

# ── set KEY=VALUE in .env (replace in place if present, else append) ──────────
set_kv() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env   # values here are env-safe (no |)
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}

# ── generate a secret only if it's still a placeholder/empty (idempotent) ─────
ensure_secret() {
  local key="$1" len="${2:-50}" cur
  cur="$(grep -E "^${key}=" .env | head -1 | cut -d= -f2-)"
  case "$cur" in
    ""|change-me*|change-this*|your-*) set_kv "$key" "$(gen "$len")"; echo "  generated $key" ;;
    *) echo "  $key already set — keeping" ;;
  esac
}

# ── create .env from the example on first run ─────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

# ── network / TLS mode ────────────────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
  echo "network: PUBLIC ($DOMAIN, automatic Let's Encrypt)"
  set_kv DOMAIN "$DOMAIN"
  set_kv SITE_TLS ""
  set_kv ALLOWED_HOSTS "$DOMAIN,localhost,127.0.0.1,server"
  set_kv CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  set_kv CORS_ALLOWED_ORIGINS "https://$DOMAIN"
else
  [ -n "$IP" ] || IP="$(hostname -I | awk '{print $1}')"
  echo "network: LAN ($IP, self-signed internal CA)"
  set_kv DOMAIN "$IP"
  set_kv SITE_TLS "tls internal"
  set_kv ALLOWED_HOSTS "*"
  set_kv CSRF_TRUSTED_ORIGINS "https://$IP"
  set_kv CORS_ALLOWED_ORIGINS "https://$IP"
fi

# ── secrets ───────────────────────────────────────────────────────────────────
echo "secrets:"
ensure_secret DJANGO_SECRET_KEY        64
ensure_secret DB_PASSWORD              32
ensure_secret MOSQUITTO_DYNSEC_PASSWORD 32
ensure_secret MQTT_BRIDGE_PASSWORD     32
chmod 600 .env

# ── bring the stack up ────────────────────────────────────────────────────────
if [ "$MODE_BUILD" -eq 1 ]; then
  echo "building from source and starting…"
  "${COMPOSE[@]}" up -d --build
else
  echo "pulling prebuilt images and starting…"
  "${COMPOSE[@]}" pull
  "${COMPOSE[@]}" up -d
fi

echo
"${COMPOSE[@]}" ps
TARGET="${DOMAIN:-$IP}"
cat <<EOF

Done. Open:  https://$TARGET
${DOMAIN:+ }$( [ -z "$DOMAIN" ] && echo "(LAN mode uses a self-signed cert — trust Caddy's root, in the caddy_data volume, or click through the browser warning)")

Create an admin login:
  ${COMPOSE[*]} exec server uv run python manage.py createsuperuser
EOF
