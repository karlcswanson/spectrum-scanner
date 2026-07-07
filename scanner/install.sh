#!/bin/sh
# Spectrum Scanner installer for Linux (Raspberry Pi / arm64, incl. OpenWRT).
#
#   curl -fsSL https://raw.githubusercontent.com/karlcswanson/spectrum-scanner/main/scanner/install.sh | sudo sh
#
# Downloads the release binary, installs it + a service (systemd or procd) and a
# config template. Override the release with VERSION=v1.2.3; the config path with
# CONFIG_DIR=...  Re-running upgrades the binary and leaves an existing config.
set -eu

REPO="karlcswanson/spectrum-scanner"
BIN="spectrum-scanner"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
CONFIG_DIR="${CONFIG_DIR:-/etc/spectrum-scanner}"
VERSION="${VERSION:-latest}"
LISTEN="${LISTEN:-:8080}"

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (e.g. pipe into 'sudo sh')"

fetch_file()   { if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi; }
fetch_stdout() { if command -v curl >/dev/null 2>&1; then curl -fsSL "$1";       else wget -qO- "$1";      fi; }
command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || die "need curl or wget"

# --- Detect target (releases exist for linux/arm64 and darwin/arm64) ---
os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Linux)  goos=linux ;;
  Darwin) goos=darwin ;;
  *) die "unsupported OS: $os" ;;
esac
case "$arch" in
  aarch64|arm64) goarch=arm64 ;;
  *) die "unsupported arch: $arch (releases are built for arm64 — Pi 4/5, GL.iNet)" ;;
esac

# --- Resolve version ---
if [ "$VERSION" = latest ]; then
  VERSION="$(fetch_stdout "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
  [ -n "$VERSION" ] || die "could not resolve latest release (is one published?)"
fi
ver="${VERSION#v}"
archive="${BIN}_${ver}_${goos}_${goarch}.tar.gz"
url="https://github.com/$REPO/releases/download/$VERSION/$archive"

log "Installing $BIN $VERSION ($goos/$goarch)"

# --- Download + install the binary ---
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
log "Downloading $url"
fetch_file "$url" "$tmp/$archive" || die "download failed: $url"
tar -xzf "$tmp/$archive" -C "$tmp" || die "extract failed"
[ -f "$tmp/$BIN" ] || die "binary '$BIN' not found in archive"
mkdir -p "$INSTALL_DIR"
cp "$tmp/$BIN" "$INSTALL_DIR/$BIN"
chmod 0755 "$INSTALL_DIR/$BIN"
log "Installed $INSTALL_DIR/$BIN"

# --- Config template (never overwrite an existing one) ---
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  cat > "$CONFIG_DIR/config.yaml" <<'EOF'
# Spectrum Scanner config — edit before starting.
auto_start: true
dwell_time_ms: 200
mode: Average
rx_gain: 40
rx_gain_mode: manual

bands:
  - name: UHF
    start_mhz: 470
    stop_mhz: 636
    enabled: true

# Point at the ADALM-Pluto (network) or configure another backend.
backend:
  type: pluto
  url: https://192.168.2.1

# Publish to the central server (fill id/token from the server, or enroll).
mqtt:
  enabled: false
  broker: "tcp://your-server:1883"
  id: ""
  token: ""
  name: "My Scanner"
  location: "My Location"
EOF
  log "Wrote config template $CONFIG_DIR/config.yaml (edit it)"
else
  log "Keeping existing $CONFIG_DIR/config.yaml"
fi

# --- Service manager: systemd (Pi) or procd (OpenWRT) ---
if command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/spectrum-scanner.service <<EOF
[Unit]
Description=Spectrum Scanner
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$INSTALL_DIR/$BIN -config $CONFIG_DIR/config.yaml -listen $LISTEN
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable spectrum-scanner >/dev/null 2>&1 || true
  log "systemd service installed. Edit the config, then: systemctl restart spectrum-scanner"
elif [ -d /etc/init.d ] && [ -e /etc/openwrt_release ]; then
  cat > /etc/init.d/spectrum-scanner <<EOF
#!/bin/sh /etc/rc.common
USE_PROCD=1
START=99
start_service() {
  procd_open_instance
  procd_set_param command $INSTALL_DIR/$BIN -config $CONFIG_DIR/config.yaml -listen $LISTEN
  procd_set_param respawn
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
EOF
  chmod +x /etc/init.d/spectrum-scanner
  /etc/init.d/spectrum-scanner enable >/dev/null 2>&1 || true
  log "procd service installed. Edit the config, then: /etc/init.d/spectrum-scanner restart"
else
  log "No systemd/procd detected — run manually: $INSTALL_DIR/$BIN -config $CONFIG_DIR/config.yaml"
fi

log "Done. Web UI on $LISTEN once running."
