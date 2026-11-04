#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
mkdir -p "$UNIT_DIR"

for unit in agent-otonom.service agent-otonom-comfyui.service agent-otonom-gpt-sovits.service; do
  if [[ -f "$ROOT/systemd/$unit" ]]; then
    cp "$ROOT/systemd/$unit" "$UNIT_DIR/"
  fi
done

systemctl --user daemon-reload
systemctl --user enable --now agent-otonom-comfyui.service agent-otonom-gpt-sovits.service agent-otonom.service
systemctl --user --no-pager --lines=0 status \
  agent-otonom-comfyui.service \
  agent-otonom-gpt-sovits.service \
  agent-otonom.service || true

echo "Installed media engines + agent."
echo "  journalctl --user -u agent-otonom-comfyui -f"
echo "  journalctl --user -u agent-otonom-gpt-sovits -f"
echo "  journalctl --user -u agent-otonom -f"
