"""Frame sources: a screen region, whole screen/monitor(s), a window, OBS Virtual Camera, or an image.

Every source returns BGR numpy frames and knows how to map between a pixel in
its frame and a position on the desktop.
"""
import numpy as np


class ScreenSource:
    """monitor=0 is every monitor at once (default), 1 = first monitor, 2 = second..."""

    def __init__(self, monitor=0):
        import mss
        self.sct = mss.mss()
        self.mon = self.sct.monitors[monitor]

    def grab(self):
        f = np.array(self.sct.grab(self.mon))[:, :, :3]
        self.shape = f.shape
        return f

    def to_desktop(self, x, y):
        return self.mon["left"] + x, self.mon["top"] + y

    def from_desktop(self, x, y):
        return x - self.mon["left"], y - self.mon["top"]


class RegionSource:
    """A fixed rectangle of this PC's screen (chosen with the region picker).
    In the two-computer setup it should cover exactly the picture of the game
    computer's screen, e.g. the OBS preview or a fullscreen projector."""

    def __init__(self, region):
        import mss
        if not region:
            raise RuntimeError("No capture region set - run: python bot.py set-region")
        self.sct = mss.mss()
        self.rect = {k: int(region[k]) for k in ("left", "top", "width", "height")}
        self.shape = (self.rect["height"], self.rect["width"], 3)

    def grab(self):
        return np.array(self.sct.grab(self.rect))[:, :, :3]

    def to_desktop(self, x, y):
        return self.rect["left"] + x, self.rect["top"] + y

    def from_desktop(self, x, y):
        return x - self.rect["left"], y - self.rect["top"]


def letterbox(frame):
    """Black bars around a picture (OBS fits the game screen into the projector with bars
    when the shapes differ) -> (x0, y0, x1, y1) of the picture, or None if no clear bars.
    Only trusts bars that are pure black and equal on both sides, like OBS makes them."""
    g = frame.max(axis=2)
    rows = np.where(g.max(axis=1) > 10)[0]
    cols = np.where(g.max(axis=0) > 10)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    h, w = g.shape
    top, bottom = rows[0], h - 1 - rows[-1]
    left, right = cols[0], w - 1 - cols[-1]
    if top + bottom + left + right < 4:
        return None
    if abs(top - bottom) > 3 or abs(left - right) > 3:
        return None          # not centered bars - probably dark game content, don't crop
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


class WindowSource:
    """Captures the inside of one window (e.g. the OBS projector) by its title.
    Follows it if it moves or resizes, and trims OBS's black letterbox bars so the
    picture maps exactly onto the game PC's screen. Windows only."""

    def __init__(self, title, auto_crop=True, method="auto"):
        import mss
        import windows
        self.windows = windows
        # "auto": grab the window's own picture (works when covered), and fall back to
        # photographing the screen if that gives nothing; "screen": always the screen.
        self.method = method
        self.using = None          # "window" or "screen": what the last grab used
        self.title = title
        self.hwnd = windows.find_window(title)
        if not self.hwnd:
            raise RuntimeError(f"No open window called {title!r} - open it, or pick a window again")
        self.sct = mss.mss()
        self.auto_crop = auto_crop
        self.crop = None           # (x0, y0, x1, y1) inside the window
        self.crop_checked = 0.0
        self.offset = (0, 0)
        self.shape = None

    def _rect(self):
        r = self.windows.client_rect(self.hwnd)
        if not r or r[2] <= 0 or r[3] <= 0:   # closed / minimized: try to find it again
            self.hwnd = self.windows.find_window(self.title)
            r = self.windows.client_rect(self.hwnd) if self.hwnd else None
            if not r or r[2] <= 0 or r[3] <= 0:
                raise RuntimeError(f"Window {self.title!r} is closed or minimized")
        return r

    def grab(self):
        import time
        left, top, w, h = self._rect()
        f = None
        if self.method == "auto":
            try:
                f = self.windows.print_window(self.hwnd, w, h)
            except Exception:
                f = None
            if f is not None and f.max() < 8:   # all black: this window can't be captured that way
                f = None
        if f is None:
            f = np.array(self.sct.grab({"left": left, "top": top, "width": w, "height": h}))[:, :, :3]
            if self.using != "screen":
                print("Window capture: using a screen grab (keep the window uncovered)")
            self.using = "screen"
        else:
            if self.using != "window":
                print("Window capture: capturing the window directly (it can be covered)")
            self.using = "window"
        now = time.time()
        if self.auto_crop and (now - self.crop_checked > 2.0 or self.shape is None):
            self.crop = letterbox(f)
            self.crop_checked = now
        if self.crop:
            x0, y0, x1, y1 = self.crop
            if x1 <= f.shape[1] and y1 <= f.shape[0]:
                f = f[y0:y1, x0:x1]
                left, top = left + x0, top + y0
        self.offset = (left, top)
        self.shape = f.shape
        return np.ascontiguousarray(f)

    def to_desktop(self, x, y):
        return self.offset[0] + x, self.offset[1] + y

    def from_desktop(self, x, y):
        return x - self.offset[0], y - self.offset[1]


class OBSSource:
    """Reads the OBS Virtual Camera (OBS -> Start Virtual Camera).

    The OBS canvas should show the game's full screen: a frame pixel is mapped
    onto the Pico's screen by proportion.
    """
    proportional = True

    def __init__(self, camera_index=0, width=1920, height=1080):
        import cv2
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {camera_index} (is OBS Virtual Camera started?)")
        self.shape = None

    def grab(self):
        for _ in range(2):  # drop buffered frames so we see the current picture
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Failed to read frame from OBS Virtual Camera")
        self.shape = frame.shape
        return frame


class ImageSource:
    """A screenshot file, for trying things out without the game."""
    proportional = True

    def __init__(self, path):
        import cv2
        self.frame = cv2.imread(path)
        if self.frame is None:
            raise RuntimeError(f"Can't read image {path}")
        self.shape = self.frame.shape

    def grab(self):
        return self.frame.copy()


def make_source(cfg, image=None):
    if image:
        return ImageSource(image)
    kind = cfg["source"]
    if kind == "region":
        return RegionSource(cfg.get("region"))
    if kind == "screen":
        return ScreenSource(cfg.get("monitor", 0))
    if kind == "window":
        return WindowSource(cfg["window_title"], cfg.get("auto_crop_bars", True),
                            cfg.get("window_capture", "auto"))
    if kind == "obs":
        return OBSSource(cfg.get("obs_camera_index", 0),
                         cfg.get("obs_width", 1920), cfg.get("obs_height", 1080))
    raise ValueError(f"Unknown source {kind!r} (use region, screen, window or obs)")


def normalize(source, cfg, x, y):
    """Frame pixel -> (0..1, 0..1) on the screen the Pico's absolute mouse covers.

    Two computers: the captured picture IS the game computer's screen, so it's a
    straight proportion. One computer: go through this PC's desktop coordinates.
    """
    if cfg.get("setup", "two_pc") == "two_pc" or getattr(source, "proportional", False):
        h, w = source.shape[:2]
        return x / w, y / h
    dx, dy = source.to_desktop(x, y)
    t = cfg["target_screen"]
    return (dx - t["left"]) / t["width"], (dy - t["top"]) / t["height"]
