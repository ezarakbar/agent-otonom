#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cp "$ROOT/systemd/agent-otonom.service" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now agent-otonom.service
systemctl --user status agent-otonom.service --no-pager || true
echo "Installed. Logs: journalctl --user -u agent-otonom -f"
