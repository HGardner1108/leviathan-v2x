#!/usr/bin/env python3
"""
Razer Leviathan V2 X — RGB underglow via OpenRGB SDK.

The Leviathan V2 X is not supported by OpenRazer. This module controls its
14-LED underglow strip via OpenRGB's SDK server instead.

Standalone usage:
    python3 leviathan_speaker.py list
    python3 leviathan_speaker.py static 255 0 128
    python3 leviathan_speaker.py off

Programmatic usage:
    from leviathan_speaker import SpeakerRunner
    runner = SpeakerRunner()
    err = runner.start(top_avgs_ref, lock, fps=20)
    ...
    runner.stop()

OpenRGB must be running with its SDK server enabled:
    Settings → SDK Server → Enable   (default port 6742)

Dependencies:
    pip install openrgb-python
"""
import shutil
import subprocess
import sys
import time
import threading

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


_openrgb_proc = None


def _ensure_openrgb_server(host: str = "127.0.0.1", port: int = 6742) -> bool:
    global _openrgb_proc

    def _reachable():
        import socket
        try:
            s = socket.create_connection((host, port), timeout=1.5)
            s.close()
            return True
        except OSError:
            return False

    if _reachable():
        return True

    binary = shutil.which("openrgb") or shutil.which("OpenRGB")
    if not binary:
        print("[speaker] OpenRGB binary not found in PATH.")
        print("[speaker] Install it from https://openrgb.org then re-enable speaker lighting.")
        return False

    if _openrgb_proc is None or _openrgb_proc.poll() is not None:
        print(f"[speaker] Launching {binary} --server --noautoconnect ...")
        _openrgb_proc = subprocess.Popen(
            [binary, "--server", "--noautoconnect"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    for _ in range(10):
        time.sleep(0.5)
        if _reachable():
            print("[speaker] OpenRGB server is up.")
            return True

    print("[speaker] OpenRGB started but SDK port is not reachable — "
          "open OpenRGB → Settings → SDK Server → Enable.")
    return False


def _find_speaker_zone(client: OpenRGBClient):
    """Return (device, zone) for the Leviathan V2 X, or (None, None)."""
    for dev in client.devices:
        nl = dev.name.lower()
        if "leviathan" in nl or str(getattr(dev, "type", "")).lower() == "speaker":
            if dev.zones:
                zone = next(
                    (z for z in dev.zones if "underglow" in z.name.lower()),
                    dev.zones[0],
                )
                return dev, zone
    return None, None


def map_cols_to_leds(col_avgs: list, n_leds: int) -> list:
    """Interpolate N screen-column averages into n_leds LED colours."""
    if not col_avgs:
        return [(0, 0, 0)] * n_leds
    n = len(col_avgs)
    out = []
    for i in range(n_leds):
        f  = i * (n - 1) / max(1, n_leds - 1)
        lo = int(f)
        hi = min(lo + 1, n - 1)
        t  = f - lo
        c0, c1 = col_avgs[lo], col_avgs[hi]
        out.append((
            int(c0[0] + (c1[0] - c0[0]) * t),
            int(c0[1] + (c1[1] - c0[1]) * t),
            int(c0[2] + (c1[2] - c0[2]) * t),
        ))
    return out


class SpeakerRunner:
    """Background thread that drives Leviathan V2 X underglow from a shared colour buffer.

    top_avgs_ref: list of length 1 containing a list of (r, g, b) tuples — one
                  per screen column. Updated externally (e.g. by a screen-capture
                  thread). SpeakerRunner reads it under `lock` each frame.
    """

    def __init__(self):
        self._thread = None
        self._stop   = threading.Event()
        self._client = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, top_avgs_ref: list, lock,
              host: str = "127.0.0.1", port: int = 6742, fps: float = 20) -> str | None:
        """Connect to OpenRGB, find the speaker, start the render thread.

        Returns None on success, or an error string on failure.
        """
        self.stop()
        self._stop.clear()

        if not _ensure_openrgb_server(host, port):
            return "OpenRGB server not reachable and could not be auto-launched."

        try:
            client = OpenRGBClient(host, port, name="leviathan-speaker")
        except Exception as e:
            return f"Cannot connect to OpenRGB at {host}:{port}: {e}"

        self._client = client

        dev, zone = _find_speaker_zone(client)
        if dev is None:
            return (
                "Leviathan V2 X not detected by OpenRGB. "
                "Ensure OpenRGB is running and the speaker is connected."
            )

        try:
            dev.set_mode("direct")
        except Exception as e:
            print(f"[speaker] Could not set Direct mode: {e}")

        n_leds = len(zone.leds)
        try:
            zone.resize(n_leds)
        except Exception as e:
            print(f"[speaker] Could not resize zone: {e}")

        print(f"[speaker] {dev.name} / '{zone.name}'  ({n_leds} LEDs)  @ {fps} fps")

        self._thread = threading.Thread(
            target=self._render_loop,
            args=(zone, n_leds, top_avgs_ref, lock, fps),
            daemon=True,
            name="leviathan-speaker",
        )
        self._thread.start()
        return None

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def _render_loop(self, zone, n_leds: int, top_avgs_ref: list, lock, fps: float):
        interval = 1.0 / max(1, fps)
        prev_rgb = None
        alpha    = 0.35   # EMA weight for new frame; lower = smoother, higher = snappier

        while not self._stop.is_set():
            with lock:
                col_avgs = list(top_avgs_ref[0])
            if col_avgs:
                rgb_list = map_cols_to_leds(col_avgs, n_leds)
                if prev_rgb is not None:
                    rgb_list = [
                        (
                            int(alpha * n[0] + (1 - alpha) * p[0]),
                            int(alpha * n[1] + (1 - alpha) * p[1]),
                            int(alpha * n[2] + (1 - alpha) * p[2]),
                        )
                        for n, p in zip(rgb_list, prev_rgb)
                    ]
                prev_rgb = rgb_list
                try:
                    zone.set_colors([RGBColor(*c) for c in rgb_list], fast=True)
                except Exception as e:
                    print(f"[speaker] LED update error: {e}")
                    break
            time.sleep(interval)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli_list(client):
    for dev in client.devices:
        zone_names = [z.name for z in dev.zones]
        n_leds = sum(len(z.leds) for z in dev.zones)
        print(f"  [{getattr(dev, 'type', '?')}] {dev.name}")
        print(f"    Zones : {', '.join(zone_names) or '(none)'}")
        print(f"    LEDs  : {n_leds} total")


def _cli_static(client, r, g, b):
    dev, zone = _find_speaker_zone(client)
    if dev is None:
        print("Leviathan V2 X not found by OpenRGB.")
        return
    try:
        dev.set_mode("direct")
    except Exception:
        pass
    n = len(zone.leds)
    try:
        zone.resize(n)
    except Exception:
        pass
    zone.set_colors([RGBColor(r, g, b)] * n, fast=True)
    print(f"Set {dev.name} / '{zone.name}' ({n} LEDs) → rgb({r}, {g}, {b})")


def _cli_off(client):
    _cli_static(client, 0, 0, 0)


def main():
    usage = (
        "Usage:\n"
        "  python3 leviathan_speaker.py list\n"
        "  python3 leviathan_speaker.py static <R> <G> <B>\n"
        "  python3 leviathan_speaker.py off\n"
    )
    args = sys.argv[1:]
    if not args:
        print(usage)
        sys.exit(1)

    if not _ensure_openrgb_server():
        sys.exit(1)

    try:
        client = OpenRGBClient("127.0.0.1", 6742, name="leviathan-cli")
    except Exception as e:
        print(f"Cannot connect to OpenRGB: {e}")
        sys.exit(1)

    cmd = args[0].lower()
    if cmd == "list":
        _cli_list(client)
    elif cmd == "static" and len(args) == 4:
        _cli_static(client, int(args[1]), int(args[2]), int(args[3]))
    elif cmd == "off":
        _cli_off(client)
    else:
        print(usage)
        client.disconnect()
        sys.exit(1)

    client.disconnect()


if __name__ == "__main__":
    main()
