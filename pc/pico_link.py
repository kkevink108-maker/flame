"""Talks to the Pico through a USB-serial adapter (CP2102) on this PC.

The adapter is wired to the Pico's UART1 pins (GP4/GP5); the Pico itself is
plugged into the game computer and runs the Flame HID firmware (firmware/).
"""
import math
import random
import time

import serial
from serial.tools import list_ports

# USB-serial adapter chips: Silicon Labs CP210x first, then CH340, FTDI, Prolific.
ADAPTER_VIDS = [0x10C4, 0x1A86, 0x0403, 0x067B]
HID_MAX = 32767
BAUD = 115200


def probe(device):
    try:
        with serial.Serial(device, BAUD, timeout=0.5) as s:
            time.sleep(0.05)
            s.reset_input_buffer()
            s.write(b"\nPING\n")
            for _ in range(3):
                line = s.readline().strip()
                if line == b"PONG":
                    return True
                if not line:
                    break
    except serial.SerialException:
        pass
    return False


def find_port():
    """First USB-serial adapter port where the Pico answers PING."""
    ports = list_ports.comports()
    ordered = [p for vid in ADAPTER_VIDS for p in ports if p.vid == vid]
    for p in ordered:
        if probe(p.device):
            return p.device
    return None


def describe_ports():
    return "\n".join(f"  {p.device}: {p.description}" for p in list_ports.comports()) or "  (none)"


class Pico:
    def __init__(self, port=None):
        port = port or find_port()
        if not port:
            raise RuntimeError(
                "Pico not found. Check the CP2102 wiring (TX->GP5, RX->GP4, GND->GND), that the Pico is"
                " plugged into the laptop with flame_hid.uf2 flashed, or set \"pico_port\" in config.json."
                "\nSerial ports on this PC:\n" + describe_ports())
        self.ser = serial.Serial(port, BAUD, timeout=2)
        self.port = port
        self.pos = None          # last position we moved to (normalized)
        self.ser.reset_input_buffer()

    def cmd(self, line):
        self.ser.write((line + "\n").encode())
        resp = self.ser.readline().decode(errors="replace").strip()
        if not resp.startswith(("OK", "PONG")):
            raise RuntimeError(f"Pico said {resp!r} to {line!r}")
        return resp

    def move(self, nx, ny):
        """Jump straight to a normalized (0..1) position on the game computer's screen."""
        nx, ny = min(max(nx, 0.0), 1.0), min(max(ny, 0.0), 1.0)
        self.cmd(f"MOVE {round(nx * HID_MAX)} {round(ny * HID_MAX)}")
        self.pos = (nx, ny)

    def glide(self, nx, ny, min_time=0.18, max_time=0.45):
        """Move there smoothly like a hand would: a slightly curved path that speeds up
        and slows down, taking longer for longer distances. Returns False if the mouse
        was already there (nothing moved)."""
        start = getattr(self, "pos", None)
        if start is None:        # first move: the real cursor position is unknown
            self.move(nx, ny)
            return True
        x0, y0 = start
        dx, dy = nx - x0, ny - y0
        dist = math.hypot(dx, dy)
        if dist < 1e-4:
            return False         # already there
        duration = min(max_time, min_time + dist * 0.6) * random.uniform(0.9, 1.15)
        # Bend the path a little to one side.
        bend = random.uniform(-0.18, 0.18)
        cx, cy = x0 + dx / 2 - dy * bend, y0 + dy / 2 + dx * bend
        t0 = time.perf_counter()
        while True:
            t = (time.perf_counter() - t0) / duration
            if t >= 1:
                break
            e = t * t * (3 - 2 * t)  # ease in / ease out
            bx = (1 - e) ** 2 * x0 + 2 * (1 - e) * e * cx + e * e * nx
            by = (1 - e) ** 2 * y0 + 2 * (1 - e) * e * cy + e * e * ny
            self.move(bx, by)
            time.sleep(0.008)
        self.move(nx, ny)
        return True

    def click(self):
        """Click wherever the mouse is now."""
        self.cmd("CLICK")

    def key(self, name):
        self.cmd(f"KEY {name.upper()}")
