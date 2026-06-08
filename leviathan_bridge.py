#!/usr/bin/env python3
"""
Razer Leviathan V2 X — PipeWire → ALSA PCM,1 volume bridge.

Problem
-------
The Leviathan V2 X exposes two ALSA playback controls:
  PCM,0  — the control PipeWire / pactl / desktop sliders bind to. INAUDIBLE.
  PCM,1  — the real hardware attenuator. Nothing in the standard Linux audio
            stack touches it, so the speaker plays at a fixed 29 % (-20 dB)
            regardless of the software volume.

Fix
---
This daemon subscribes to PipeWire events and mirrors every sink-volume /
sink-mute change for the Leviathan to PCM,1 via amixer. With it running the
desktop volume slider, media keys, and per-app volumes all become audible.

Dependencies: pactl (pulseaudio-utils), amixer (alsa-utils) — no Python deps.
"""
import re
import subprocess
import sys
import time


SINK_PATTERN = re.compile(r'razer|leviathan', re.IGNORECASE)
CARD_PATTERN = re.compile(r'razer|leviathan', re.IGNORECASE)
LOG_PREFIX   = "[leviathan-bridge]"


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def find_sink() -> str | None:
    r = _run("pactl list sinks short")
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and SINK_PATTERN.search(parts[1]):
            return parts[1]
    return None


def find_card() -> int | None:
    r = _run("aplay -l")
    for line in r.stdout.splitlines():
        if CARD_PATTERN.search(line):
            m = re.search(r'card\s+(\d+)', line)
            if m:
                return int(m.group(1))
    return None


def get_sink_volume(sink: str) -> int | None:
    r = _run(f"pactl get-sink-volume {sink}")
    pcts = re.findall(r'(\d+)%', r.stdout)
    if not pcts:
        return None
    return round(sum(int(p) for p in pcts) / len(pcts))


def get_sink_mute(sink: str) -> bool:
    r = _run(f"pactl get-sink-mute {sink}")
    return "yes" in r.stdout.lower()


_last_applied: tuple[int, bool] | None = None


def sync(sink: str, card: int) -> None:
    global _last_applied
    vol   = get_sink_volume(sink)
    muted = get_sink_mute(sink)
    if vol is None:
        return
    target = 0 if muted else min(100, vol)
    state  = (target, muted)
    if state == _last_applied:
        return
    _run(f"amixer -c {card} sset 'PCM',1 {target}%")
    _last_applied = state
    print(f"{LOG_PREFIX} PCM,1 → {target}%{' (muted)' if muted else ''}", flush=True)


def discover(prev_sink: str | None, prev_card: int | None):
    sink = find_sink()
    card = find_card()
    if sink != prev_sink or card != prev_card:
        if sink and card is not None:
            print(f"{LOG_PREFIX} sink={sink}  card={card}", flush=True)
        elif prev_sink or prev_card is not None:
            print(f"{LOG_PREFIX} Leviathan disconnected", flush=True)
    return sink, card


def main() -> int:
    print(f"{LOG_PREFIX} starting", flush=True)
    sink, card = None, None

    # Wait up to 2 minutes for the speaker on first launch (covers slow boot).
    for _ in range(60):
        sink, card = discover(sink, card)
        if sink and card is not None:
            sync(sink, card)
            break
        time.sleep(2)

    while True:
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
        except FileNotFoundError:
            print(f"{LOG_PREFIX} pactl not found — install pulseaudio-utils", flush=True)
            return 1

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                s = line.strip()
                if "sink" not in s:
                    continue
                if not any(ev in s for ev in ("change", "new", "remove")):
                    continue
                sink, card = discover(sink, card)
                if sink and card is not None:
                    sync(sink, card)
        except KeyboardInterrupt:
            proc.terminate()
            return 0
        finally:
            proc.terminate()
            proc.wait(timeout=2)

        # pactl subscribe exited (e.g. PipeWire restart) — reconnect.
        print(f"{LOG_PREFIX} pactl subscribe ended; reconnecting in 3 s", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
