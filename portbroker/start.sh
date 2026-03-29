#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="portbroker"
SERVER="$SCRIPT_DIR/server.py"
LOG="$SCRIPT_DIR/portbroker.log"

has_systemd() {
  systemctl --user status >/dev/null 2>&1
}

install_systemd() {
  local service_dir="$HOME/.config/systemd/user"
  mkdir -p "$service_dir"
  cp "$SCRIPT_DIR/portbroker.service" "$service_dir/$SERVICE_NAME.service"
  systemctl --user daemon-reload
  systemctl --user enable "$SERVICE_NAME"
  systemctl --user start "$SERVICE_NAME"
  echo "portbroker installed as systemd user service."
  echo "It will start automatically on login."
  echo "Manage with: systemctl --user {status,stop,restart} portbroker"
}

install_zshrc() {
  local zshrc="$HOME/.zshrc"
  local marker="# portbroker auto-start"
  if grep -q "$marker" "$zshrc" 2>/dev/null; then
    echo "portbroker .zshrc guard already present."
    return
  fi
  cat >> "$zshrc" <<ZSHEOF

$marker
if ! curl -sf http://localhost:9876/health >/dev/null 2>&1; then
  nohup python3 $SERVER > $LOG 2>&1 &
fi
ZSHEOF
  echo "portbroker .zshrc guard added."
  echo "It will start automatically with each new shell session."
  echo "Start now with: python3 $SERVER &"
}

echo "Installing portbroker auto-start..."
if has_systemd; then
  install_systemd
else
  echo "systemd not available — using .zshrc fallback."
  install_zshrc
fi
