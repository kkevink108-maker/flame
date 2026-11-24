"""Live monitor window: shows what the bot sees and lets you control it.

Boxes:  green = positive, red = negative, grey = zero/empty, yellow = can't read.
Buttons: blue = found, orange = the one it will press next, dark red X = not available.
"""
import threading

import cv2
import numpy as np

WIN = "Flame bot - live monitor"
BAR_H = 228
MIN_W = 800
MAX_W, MAX_H = 1000, 520
MODES = ["auto", "x1", "x3"]

COLORS = {
    "positive": (80, 220, 80),
    "negative": (70, 70, 230),
    "zero": (170, 170, 170),
    "empty": (110, 110, 110),
    "unknown": (0, 220, 255),
}


class State:
    """Everything shared between the bot thread and the monitor window."""

    def __init__(self, mode="auto", running=False, max_resets=200, limit_on=True,
                 line_target="off", cp_also=True):
        self.lock = threading.Lock()
        self.frame = None
        self.det = None
        self.results = []
        self.next_button = None       # "x1" / "x3" / None
        self.mode = mode
        self.running = running
        self.quit = False
        self.resets = 0               # total resets since the program started
        self.run_resets = 0           # resets since the last START
        self.max_resets = max_resets  # pause after this many resets per run
        self.limit_on = limit_on      # False = no max, keep going until a positive
        self.line_target = line_target  # cube lines to stop on (see lines.TARGETS)
        self.cp_also = cp_also        # with a line target: also stop on a Combat Power gain
        self.lines_seen = ""          # last AFTER lines read, for the info line
        self.n_x1 = self.n_x3 = 0     # total resets by button
        self.spent_run = 0            # mesos spent since the last START
        self.spent_total = 0          # mesos spent since the program started
        self.run_finished = True      # next START begins a new run (counters from 0)
        self.status = "Starting..."
        self.message = ""
        self.exclude = None           # monitor window rect on the desktop (x, y, w, h)
        self.capture_name = ""        # what's being captured, for the info line
        self.capture_using = None     # window capture: "window" (direct) or "screen" (grab)
        self.new_source = None        # a new capture source for the bot thread to switch to

    def set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def toggle_running(self):
        with self.lock:
            self.running = not self.running
            self.message = "Started" if self.running else "Paused"

    def toggle_limit(self):
        with self.lock:
            self.limit_on = not self.limit_on
            self.message = "Max resets ON" if self.limit_on else "Max resets OFF - runs until a positive"

    def cycle_target(self):
        import lines
        with self.lock:
            self.line_target = lines.ORDER[(lines.ORDER.index(self.line_target) + 1) % len(lines.ORDER)]
            self.message = f"Line target: {lines.TARGETS[self.line_target][0]}"

    def toggle_cp_also(self):
        with self.lock:
            self.cp_also = not self.cp_also
            self.message = ("Also stops on a Combat Power gain" if self.cp_also
                            else "Combat Power gains ignored - only the line target stops it")

    def change_max(self, delta):
        with self.lock:
            self.max_resets = max(1, self.max_resets + delta)

    def new_run(self):
        with self.lock:
            self.run_resets = 0
            self.spent_run = 0

    def add_reset(self, which, cost):
        with self.lock:
            self.resets += 1
            self.run_resets += 1
            self.spent_run += cost
            self.spent_total += cost
            if which == "x3":
                self.n_x3 += 1
            else:
                self.n_x1 += 1

    def cycle_mode(self):
        with self.lock:
            self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
            self.message = f"Mode: {self.mode.upper()}"


def _label(img, text, org, color, scale=0.5, thick=1):
    """Text on a solid dark tag so it's readable over the game."""
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x, y = int(org[0]), int(org[1])
    pad = max(2, int(3 * scale))
    cv2.rectangle(img, (x, y - th - pad), (x + tw + 2 * pad, y + base + pad), (15, 15, 15), -1)
    cv2.rectangle(img, (x, y - th - pad), (x + tw + 2 * pad, y + base + pad), color, 1)
    cv2.putText(img, text, (x + pad, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def fmt_result(r):
    if r["kind"] == "empty":
        return "-"
    if r["value"] is None:
        return f"? {r['text']}"
    return f"{r['sign'] or ''}{r['value']:,}"


class Monitor:
    def __init__(self, state, can_act=True, on_pick_window=None):
        self.state = state
        self.can_act = can_act
        self.on_pick_window = on_pick_window   # opens the window list (runs in pump, not in a click)
        self.pick_requested = False
        self.buttons = []  # (x0, y0, x1, y1, action)
        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WIN, self._on_mouse)

    # ------------------------------------------------------------ input
    def _on_mouse(self, event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONUP:
            return
        for x0, y0, x1, y1, action in self.buttons:
            if x0 <= x <= x1 and y0 <= y <= y1:
                action()

    def _set_mode(self, m):
        self.state.set(mode=m, message=f"Mode: {m.upper()}")

    def pump(self):
        """Draw one frame and handle keys. Returns False when the user closes it."""
        self.draw()
        key = cv2.waitKey(30) & 0xFF
        if self.pick_requested:
            self.pick_requested = False
            if self.on_pick_window:
                self.on_pick_window()
        if key in (ord("q"), 27):
            self.state.set(quit=True)
        elif key == ord(" ") and self.can_act:
            self.state.toggle_running()
        elif key == ord("m"):
            self.state.cycle_mode()
        elif key in (ord("1"), ord("3"), ord("a")):
            self._set_mode({ord("1"): "x1", ord("3"): "x3", ord("a"): "auto"}[key])
        try:
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                self.state.set(quit=True)
            rect = cv2.getWindowImageRect(WIN)
            self.state.set(exclude=rect if rect[2] > 0 else None)
        except cv2.error:
            pass
        return not self.state.quit

    # ------------------------------------------------------------ drawing
    def draw(self):
        st = self.state
        with st.lock:
            frame, det, results = st.frame, st.det, list(st.results)
            nxt, mode, running = st.next_button, st.mode, st.running
            status, message, capture_name = st.status, st.message, st.capture_name
            using = st.capture_using
            run_resets, max_resets, limit_on = st.run_resets, st.max_resets, st.limit_on
            spent_run, spent_total, n_x1, n_x3 = st.spent_run, st.spent_total, st.n_x1, st.n_x3
            line_target, cp_also, lines_seen = st.line_target, st.cp_also, st.lines_seen

        if frame is None:
            view = np.zeros((200, MIN_W, 3), np.uint8)
        else:
            img = frame.copy()
            region = None
            if det is not None:
                t = max(1, int(round(2 * det.scale)))
                fs = 0.5 * max(det.scale, 0.8)
                for i, b in enumerate(det.boxes):
                    r = results[i] if i < len(results) else None
                    col = COLORS[r["kind"]] if r else (200, 200, 200)
                    x, y, w, h = b
                    cv2.rectangle(img, (x, y), (x + w, y + h), col, t)
                    if r:
                        _label(img, fmt_result(r), (x, y + h + int(18 * det.scale)), col, fs, t)
                for name, rect in (("x1", det.x1), ("x3", det.x3)):
                    if rect is None:
                        continue
                    x, y, w, h = rect
                    col = (0, 165, 255) if nxt == name else (255, 160, 60)
                    cv2.rectangle(img, (x, y), (x + w, y + h), col, t * (2 if nxt == name else 1))
                    if nxt == name:
                        _label(img, "NEXT", (x + w - int(50 * det.scale), y - int(6 * det.scale)), col, fs, t)
                for rect, ghost in ((det.x1, det.x1_ghost), (det.x3, det.x3_ghost)):
                    if rect is None and ghost:  # button missing / greyed out: cross it out
                        x, y, w, h = ghost
                        cv2.line(img, (x, y), (x + w, y + h), (40, 40, 200), t)
                        cv2.line(img, (x + w, y), (x, y + h), (40, 40, 200), t)
                region = det.region(margin=60)
                if region and getattr(det, "cube", False):   # show the potential lines too
                    up = int(110 * det.scale)
                    region = (region[0], region[1] - up, region[2], region[3] + up)
            if region:
                x, y, w, h = region
                x0, y0 = max(0, x), max(0, y)
                img = img[y0:y + h, x0:x + w]
            k = min(MAX_W / img.shape[1], MAX_H / img.shape[0])
            if region and k > 1.6:
                k = 1.6
            view = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
            if view.shape[1] < MIN_W:
                view = cv2.copyMakeBorder(view, 0, 0, 0, MIN_W - view.shape[1], cv2.BORDER_CONSTANT, value=(20, 20, 20))

        bar = np.full((BAR_H, view.shape[1], 3), 32, np.uint8)
        self.buttons = []
        oy = view.shape[0]

        def button(x, row, text, active, action, w=None):
            w = w or (16 + 11 * len(text))
            y0 = 10 + row * 42
            y1 = y0 + 32
            bg = (70, 140, 60) if active else (70, 70, 70)
            cv2.rectangle(bar, (x, y0), (x + w, y1), bg, -1)
            cv2.rectangle(bar, (x, y0), (x + w, y1), (150, 150, 150), 1)
            cv2.putText(bar, text, (x + 8, y0 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
            self.buttons.append((x, oy + y0, x + w, oy + y1, action))
            return x + w + 8

        def text(x, y, s, color=(200, 200, 200), scale=0.55):
            cv2.putText(bar, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)

        # Row 1: start/pause, reset mode, quit
        x = 10
        if self.can_act:
            x = button(x, 0, "PAUSE" if running else "START", running, st.toggle_running, 80)
        else:
            text(x, 32, "VIEW ONLY", (0, 200, 255))
            x += 110
        x += 10
        text(x, 32, "Reset:")
        x += 60
        for m, label in (("auto", "AUTO"), ("x1", "x1"), ("x3", "x3")):
            x = button(x, 0, label, mode == m, lambda m=m: self._set_mode(m))
        x += 10
        if self.on_pick_window:
            x = button(x, 0, "WINDOW...", False, lambda: setattr(self, "pick_requested", True), 100)
        button(x, 0, "QUIT", False, lambda: st.set(quit=True), 60)

        # Row 2: max resets
        x = 10
        text(x, 74, "Max resets:")
        x += 110
        for label, d in (("-100", -100), ("-10", -10), ("-1", -1)):
            x = button(x, 1, label, False, lambda d=d: st.change_max(d), 50)
        count = f"{run_resets} / {max_resets}" if limit_on else f"{run_resets} / no limit"
        text(x + 6, 74, count, (255, 255, 255) if limit_on else (150, 150, 150), 0.6)
        x += 150
        for label, d in (("+1", 1), ("+10", 10), ("+100", 100)):
            x = button(x, 1, label, False, lambda d=d: st.change_max(d), 50)
        x += 6
        button(x, 1, "LIMIT ON" if limit_on else "NO LIMIT", limit_on, st.toggle_limit, 96)

        # Row 3: cube line target
        import lines
        x = 10
        text(x, 116, "Cube lines:")
        x += 110
        x = button(x, 2, lines.TARGETS[line_target][0], line_target != "off", st.cycle_target, 150)
        if lines.needs_cp(line_target):          # the target itself needs the CP gain
            x = button(x, 2, "CP+ NEEDED", True, lambda: None, 110)
        else:
            x = button(x, 2, "CP+ ALSO" if cp_also or line_target == "off" else "CP+ OFF",
                       cp_also or line_target == "off", st.toggle_cp_also, 110)
        if line_target != "off":
            text(x + 6, 116, lines_seen[:60], (170, 170, 170), 0.45)

        # Info lines
        state_txt = "RUNNING" if running else ("VIEW ONLY" if not self.can_act else "PAUSED")
        text(10, 150, f"Mesos spent: {spent_run:,} this run  |  {spent_total:,} total"
                      f"  ({n_x3} x3, {n_x1} x1)", (120, 220, 255), 0.5)
        how = {"window": "  (direct - OK to cover it)",
               "screen": "  (screen grab - keep it uncovered)"}.get(using, "")
        text(10, 172, f"Capturing: {capture_name}{how}"[:120], (170, 170, 170), 0.5)
        text(10, 194, f"{state_txt} | {status}"[:110], (230, 230, 230), 0.5)
        text(10, 216, message[:110], (0, 220, 255), 0.5)
        cv2.imshow(WIN, np.vstack([view, bar]))

    def close(self):
        cv2.destroyAllWindows()
