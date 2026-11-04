# Razer Leviathan V2 X — Linux fixes

Two independent fixes for the Razer Leviathan V2 X on Linux: volume control and RGB lighting.

Built by directing Claude Code, then testing and verifying the fixes on my own hardware.

---

## The volume problem

The Leviathan V2 X exposes **two ALSA playback controls**:

| Control | What it is | Who uses it |
|---------|-----------|-------------|
| `PCM,0` | Software phantom — changing it has no audible effect | PipeWire, pactl, GNOME slider, media keys |
| `PCM,1` | Real hardware attenuator | Nothing in the standard Linux audio stack |

Because PipeWire binds to `PCM,0`, the speaker plays at a **fixed hardware volume regardless of the software slider**. `PCM,1` also resets to 29% (−20 dB) on every plug-in, so even a direct `amixer` fix doesn't survive a reconnect.

### Fix 1 — Volume bridge (recommended)

`leviathan_bridge.py` runs as a systemd user service. It subscribes to PipeWire events and mirrors every sink-volume and mute change to `PCM,1` via `amixer`. After installing it, the desktop volume slider, media keys, and per-app volumes all work as expected.

**Dependencies:** `pactl` (pulseaudio-utils), `amixer` (alsa-utils) — no Python packages required.

**Install:**
```bash
./install.sh
```

**Verify it's running:**
```bash
systemctl --user status razer-leviathan-bridge
```

**Uninstall:**
```bash
./install.sh --uninstall
```

### Fix 2 — udev rule (fallback)

`99-razer-leviathan.rules` resets `PCM,1` to 100% every time the speaker is plugged in. This alone won't make the volume slider work, but it prevents the hardware from silently capping output when the bridge is not active. The install script sets up both fixes together.

**Manual install (without the install script):**
```bash
sudo tee /usr/local/bin/razer-leviathan-fix.sh > /dev/null << 'SCRIPT'
#!/bin/bash
CARD="${1#controlC}"
/usr/bin/amixer -c "$CARD" sset 'PCM',1 100% unmute >/dev/null 2>&1
SCRIPT
sudo chmod 755 /usr/local/bin/razer-leviathan-fix.sh
sudo cp 99-razer-leviathan.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

### Running the bridge manually (without systemd)

```bash
python3 leviathan_bridge.py
```

Or as a desktop autostart entry:
```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/razer-leviathan-bridge.desktop << EOF
[Desktop Entry]
Type=Application
Name=Razer Leviathan Bridge
Exec=/usr/bin/python3 /path/to/leviathan_bridge.py
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
```

---

## RGB lighting

The Leviathan V2 X is not supported by OpenRazer. `leviathan_speaker.py` controls its 14-LED underglow strip via the [OpenRGB](https://openrgb.org) SDK instead.

**Dependencies:**
```bash
pip install openrgb-python
# or:
./install.sh --rgb
```

OpenRGB must be running with its SDK server enabled: **Settings → SDK Server → Enable.**

**CLI usage:**
```bash
# List devices detected by OpenRGB
python3 leviathan_speaker.py list

# Set a static colour (R G B, 0–255)
python3 leviathan_speaker.py static 255 0 128

# Turn off
python3 leviathan_speaker.py off
```

**Ambient / reactive use:**

Import `SpeakerRunner` to drive the LEDs from a live colour buffer (e.g. screen-sampled colours):

```python
import threading
from leviathan_speaker import SpeakerRunner

# top_avgs_ref[0] is a list of (r, g, b) tuples — one per screen column.
# Update it from your capture thread; SpeakerRunner reads it under `lock`.
top_avgs_ref = [[(128, 0, 255)] * 5]
lock = threading.Lock()

runner = SpeakerRunner()
err = runner.start(top_avgs_ref, lock, fps=20)
if err:
    print(f"Error: {err}")

# ... later:
runner.stop()
```

The runner interpolates however many colour samples you provide across all 14 LEDs and applies an exponential moving average between frames to prevent flickering.

---

## Files

| File | Purpose |
|------|---------|
| `leviathan_bridge.py` | Volume bridge daemon — mirrors PipeWire volume to ALSA PCM,1 |
| `leviathan_speaker.py` | RGB control via OpenRGB — CLI and importable `SpeakerRunner` |
| `99-razer-leviathan.rules` | udev rule — resets PCM,1 to 100% on plug-in |
| `install.sh` | One-shot installer for the bridge, udev rule, and optional RGB dep |

## Tested on

- Ubuntu 24.04, kernel 6.8, PipeWire 1.x
- Razer Leviathan V2 X (USB ID `1532:054a`)
