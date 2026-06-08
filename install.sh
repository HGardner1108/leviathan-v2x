#!/usr/bin/env bash
# Installer for Razer Leviathan V2 X Linux fixes.
#
#   ./install.sh            — volume bridge + udev rule
#   ./install.sh --rgb      — also install openrgb-python for RGB control
#   ./install.sh --uninstall
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "==> Removing volume bridge service..."
    systemctl --user disable --now razer-leviathan-bridge.service 2>/dev/null || true
    rm -f ~/.config/systemd/user/razer-leviathan-bridge.service
    systemctl --user daemon-reload

    echo "==> Removing udev rule..."
    sudo rm -f /etc/udev/rules.d/99-razer-leviathan.rules
    sudo rm -f /usr/local/bin/razer-leviathan-fix.sh
    sudo udevadm control --reload-rules

    echo "==> Done. Replug the speaker to confirm PCM,1 is no longer auto-reset."
    exit 0
fi

echo "==> Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y alsa-utils pulseaudio-utils

if [[ "${1:-}" == "--rgb" ]]; then
    echo "==> Installing openrgb-python..."
    pip3 install --user openrgb-python
fi

echo "==> Installing volume bridge (systemd user service)..."
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/razer-leviathan-bridge.service << UNIT
[Unit]
Description=Razer Leviathan V2 X volume bridge (PipeWire -> ALSA PCM,1)
After=pipewire.service default.target
Wants=pipewire.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${REPO_DIR}/leviathan_bridge.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now razer-leviathan-bridge.service
echo "    Service started. Check: systemctl --user status razer-leviathan-bridge"

echo "==> Installing udev rule (PCM,1 plug-in failsafe)..."
sudo tee /usr/local/bin/razer-leviathan-fix.sh > /dev/null << 'SCRIPT'
#!/bin/bash
CARD="${1#controlC}"
/usr/bin/amixer -c "$CARD" sset 'PCM',1 100% unmute >/dev/null 2>&1
SCRIPT
sudo chmod 755 /usr/local/bin/razer-leviathan-fix.sh
sudo cp "${REPO_DIR}/99-razer-leviathan.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
echo "    udev rule installed. Replug the speaker to verify."

echo ""
echo "==> Done."
echo "    Volume bridge is running. The desktop volume slider should now work."
echo "    To uninstall: ./install.sh --uninstall"
