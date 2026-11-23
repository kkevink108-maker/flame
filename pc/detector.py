"""Finds the reset window anywhere on screen, at any size.

The "Reset x1" / "Reset x3" buttons are located with multi-scale template
matching. Everything else (the result number boxes) is placed relative to the
Reset x1 button and scaled by the same factor, so it works on any monitor,
resolution or window size without calibration.

All layout numbers are in pixels at scale 1.0 (the size in the sample
screenshots) and measured from the top-left corner of the Reset x1 button.
"""
import os
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from paths import DATA_DIR, RESOURCE_DIR

TEMPLATE_DIR = os.path.join(RESOURCE_DIR, "templates")     # built-in templates
USER_TEMPLATE_DIR = os.path.join(DATA_DIR, "templates")    # templates from `calibrate`

DEFAULT_LAYOUT = {
    "button_size": [184, 30],          # Reset button (w, h)
    "x3_offset": [202, 0],             # Reset x3 top-left, relative to Reset x1 top-left
    "template_rect": [0.2, 0.13, 0.55, 0.74],  # part of a button used as template (fractions)
    "box_centers": [[-173, -94], [70, -94], [314, -94], [558, -94]],  # result numbers
    "box_size": [200, 30],             # OCR box around each number
    # Window with only one wide "Reset x1" button (BEFORE / AFTER, no x3):
    # numbers measured from the middle of the top edge of that button.
    "single_box_centers": [[-132, -99], [120, -99]],         # flame (bonus stats) window
    "single_box_centers_cube": [[-127, -135], [124, -135]],  # cube (potential) window: numbers sit higher
    "single_button_width": 258,
}

SCALES = [round(0.5 * 1.05 ** i, 3) for i in range(38)]   # 0.5x .. 3.0x in 5% steps
MATCH_THRESHOLD = 0.72
COARSE_THRESHOLD = 0.55     # half-size first pass is blurrier; the full-size pass re-checks
HINT_THRESHOLD = 0.6        # at the remembered spot + size we can be more lenient (hovered button, cursor on it)
MIN_SATURATION_RATIO = 0.45  # a greyed-out button has much less color than the template


@dataclass
class Detection:
    scale: float
    x1_tl: tuple                      # Reset x1 top-left (may be virtual if only x3 is seen)
    x1: tuple = None                  # (x, y, w, h) of Reset x1 if usable, else None
    x3: tuple = None                  # (x, y, w, h) of Reset x3 if usable, else None
    x3_seen: bool = False             # x3 button is on screen (maybe greyed out)
    score: float = 0.0
    x1_ghost: tuple = None            # where Reset x1 is / would be
    x3_ghost: tuple = None            # where Reset x3 is / would be
    single: bool = False              # one wide Reset x1 button only (BEFORE / AFTER window)
    boxes: list = field(default_factory=list)

    def region(self, margin=40):
        """Bounding rect of everything we care about (for the live monitor)."""
        rects = list(self.boxes) + [r for r in (self.x1, self.x3) if r]
        if not rects:
            return None
        m = int(margin * self.scale)
        x0 = min(r[0] for r in rects) - m
        y0 = min(r[1] for r in rects) - m
        x1 = max(r[0] + r[2] for r in rects) + m
        y1 = max(r[1] + r[3] for r in rects) + m
        return x0, y0, x1 - x0, y1 - y0


def _load(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    return img


def _saturation(bgr):
    return float(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1].mean())


class Detector:
    def __init__(self, layout=None, template_dir=TEMPLATE_DIR, hint=None):
        self.layout = dict(DEFAULT_LAYOUT, **(layout or {}))
        # User-calibrated templates win over the shipped defaults.
        def pick(name):
            user = os.path.join(USER_TEMPLATE_DIR, f"user_{name}.png")
            return _load(user if os.path.exists(user) else os.path.join(template_dir, f"{name}.png"))
        self.t1 = pick("reset_x1")
        self.t3 = pick("reset_x3")
        self.t1g = cv2.cvtColor(self.t1, cv2.COLOR_BGR2GRAY)
        self.t3g = cv2.cvtColor(self.t3, cv2.COLOR_BGR2GRAY)
        self.sat_ref = (_saturation(self.t1) + _saturation(self.t3)) / 2
        self.hint = hint  # {"scale", "x", "y"}: last known Reset x1 top-left, in frame pixels
        self.last_full_search = False
        self.prev = None  # last detection (to keep buttons the mouse is covering)

    # ------------------------------------------------------------ matching
    def _match(self, gray, tmpl, scale, roi=None):
        t = cv2.resize(tmpl, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        ox = oy = 0
        if roi is not None:
            x, y, w, h = roi
            x, y = max(0, x), max(0, y)
            gray = gray[y:y + h, x:x + w]
            ox, oy = x, y
        if gray.shape[0] < t.shape[0] or gray.shape[1] < t.shape[1]:
            return None, t.shape, (ox, oy)
        return cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED), t.shape, (ox, oy)

    @staticmethod
    def _peaks(res, tshape, n=2):
        """Top-n non-overlapping peaks of a match map: [(score, x, y)]."""
        res = res.copy()
        th, tw = tshape[:2]
        out = []
        for _ in range(n):
            _, s, _, (x, y) = cv2.minMaxLoc(res)
            out.append((float(s), x, y))
            res[max(0, y - th):y + th, max(0, x - tw):x + tw] = -1
        return out

    def _search_scale(self, gray, scale, roi=None, threshold=MATCH_THRESHOLD):
        """Best interpretation at one scale -> (score, x1_tl, x1_score, x3_tl, x3_score) or None."""
        r1, tshape, (ox, oy) = self._match(gray, self.t1g, scale, roi)
        r3, _, _ = self._match(gray, self.t3g, scale, roi)
        if r1 is None:
            return None
        both = np.maximum(r1, r3)
        cands = [p for p in self._peaks(both, tshape) if p[0] >= threshold]
        if not cands:
            return None

        lay = self.layout
        tx, ty = lay["template_rect"][0] * lay["button_size"][0], lay["template_rect"][1] * lay["button_size"][1]
        dx3 = lay["x3_offset"][0] * scale

        def tl(p):  # template match position -> button top-left, frame coords
            return (ox + p[1] - tx * scale, oy + p[2] - ty * scale)

        def s1(p):
            return float(r1[p[2], p[1]])

        def s3(p):
            return float(r3[p[2], p[1]])

        # Two buttons side by side: left is x1, right is x3.
        if len(cands) == 2:
            a, b = sorted(cands, key=lambda p: p[1])
            same_row = abs(a[2] - b[2]) < tshape[0] * 0.5
            right_gap = abs((b[1] - a[1]) - dx3) < dx3 * 0.2
            if same_row and right_gap:
                return (max(a[0], b[0]), tl(a), s1(a), tl(b), s3(b))
        # One button: decide which by which template fits it better.
        p = max(cands, key=lambda q: q[0])
        if s3(p) > s1(p) + 0.02:
            x3_tl = tl(p)
            return (p[0], (x3_tl[0] - dx3, x3_tl[1] - lay["x3_offset"][1] * scale), 0.0, x3_tl, s3(p))
        return (p[0], tl(p), s1(p), None, 0.0)

    def _best(self, gray, scales, roi=None, threshold=MATCH_THRESHOLD):
        best = None
        for s in scales:
            r = self._search_scale(gray, s, roi, threshold)
            if r and (best is None or r[0] > best[1][0]):
                best = (s, r)
        return best

    # ------------------------------------------------------------ public
    def _roi_around(self, hint):
        s = hint["scale"]
        bw, bh = self.layout["button_size"]
        pad = int(40 * s)
        return (int(hint["x"]) - pad, int(hint["y"]) - pad,
                int((self.layout["x3_offset"][0] + bw) * s) + 2 * pad, int(bh * s) + 2 * pad)

    def _full_search(self, gray):
        """Coarse pass on a half-size copy (for big frames), then re-check the best few
        candidates at full size. Small scales are searched at full size directly."""
        f = 0.5 if gray.shape[1] > 1600 else 1.0
        small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gray
        tw = self.t1g.shape[1]
        cands = []
        for s in SCALES:
            if f < 1 and tw * s * f < 60:      # template would be too tiny at half size
                r = self._search_scale(gray, s)
                if r:
                    cands.append((r[0], s, r[1], True))
                continue
            r = self._search_scale(small, s * f, threshold=COARSE_THRESHOLD)
            if r:
                cands.append((r[0], s, (r[1][0] / f, r[1][1] / f), f == 1.0))
        best = None
        for score, s, (x, y), exact in sorted(cands, reverse=True)[:4]:
            if exact:
                r = self._best(gray, [s], self._roi_around({"scale": s, "x": x, "y": y}))
            else:
                r = self._best(gray, [s * k for k in (0.94, 0.97, 1.0, 1.03, 1.06)],
                               self._roi_around({"scale": s, "x": x, "y": y}))
            if r and (best is None or r[1][0] > best[1][0]):
                best = r
        return best

    def find(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found = None
        self.last_full_search = False
        if self.prev is not None and self.prev.single:
            # One wide button: if it's still there unchanged, nothing else to check
            # (the mouse resting on it can make the template or width checks fail).
            det = self._still_there(frame)
            if det is not None:
                self.prev = det
                return det
        if self.hint:  # fast path: look where it was last time, same size
            found = self._best(gray, [self.hint["scale"]], self._roi_around(self.hint),
                               threshold=HINT_THRESHOLD)
        if found is None and self.hint:
            # The mouse resting on the button hides its text: if the buttons are still
            # where they were (same colour, same width), it's still the same window.
            det = self._still_there(frame)
            if det is not None:
                self.prev = det
                return det
        if found is None:
            self.last_full_search = True
            found = self._full_search(gray)
        wide = False
        if found is None:
            found = self._find_wide_button(frame, gray)
            wide = found is not None
        if found is None:
            return None

        scale, (score, x1_tl, x1_score, x3_tl, x3_score) = found
        self.hint = {"scale": scale, "x": x1_tl[0], "y": x1_tl[1]}
        th = 0.5 if wide else MATCH_THRESHOLD if self.last_full_search else HINT_THRESHOLD
        det = self._build(frame, scale, score, x1_tl, x1_score, x3_tl, x3_score, th)
        prev = self.prev
        if prev is not None and prev.single and not det.single and not det.x3 \
                and self._inside(prev.x1_ghost, found[1]):
            # Same single-button window, its button just greyed out for a moment.
            det = replace(prev, boxes=list(prev.boxes), x1=None)
            self.prev = det
            return det
        self._keep_covered_buttons(frame, det)
        self.prev = det
        return det

    def _keep_covered_buttons(self, frame, det):
        """The mouse resting on a button can hide part of its text so it stops matching.
        If that button was there a moment ago, is still in the same place and still in
        colour (not greyed out), it's still there - keep it."""
        prev = getattr(self, "prev", None)
        if prev is None or self.last_full_search or abs(prev.scale - det.scale) > 0.02 * det.scale:
            return
        for name in ("x1", "x3"):
            old, ghost = getattr(prev, name), getattr(det, name + "_ghost")
            if getattr(det, name) is None and old is not None and ghost \
                    and abs(old[0] - ghost[0]) <= 3 and abs(old[1] - ghost[1]) <= 3 \
                    and self._usable(frame, ghost):
                setattr(det, name, ghost)
                if name == "x3":
                    det.x3_seen = True

    def _inside(self, r, hit):
        """The button the template matched lies inside rect r (the old wide button)."""
        _, x1_tl, x1_score, x3_tl, x3_score = hit
        tl = x3_tl if x3_tl is not None and x3_score > x1_score else x1_tl
        x, y, w, h = r
        return x - 0.1 * w <= tl[0] <= x + 0.5 * w and abs(tl[1] - y) <= 0.5 * h

    def _still_there(self, frame):
        """Last detection again, if its button(s) still look the same -> Detection or None."""
        prev = self.prev
        if prev is None:
            return None

        def same(r):
            """Mostly button-coloured inside (the cursor may cover a bit), not outside."""
            if not r or r[2] <= 0:
                return False
            x, y, w, h = r
            fh, fw = frame.shape[:2]
            e = max(3, int(w * 0.03))
            if x - e < 0 or x + w + e > fw:
                return False
            inside, outside = [], []
            for f in (0.15, 0.22, 0.75, 0.82):
                yy = int(round(y + h * f))
                if not 0 <= yy < fh:
                    continue
                on = self._cyan(frame[yy:yy + 1, x - e:x + w + e])
                inside.append(on[2 * e:-2 * e].mean())
                outside += [on[:e - 1].mean(), on[-(e - 1):].mean()]
            return bool(inside) and np.mean(inside) >= 0.7 and np.mean(outside) <= 0.3

        det = replace(prev, boxes=list(prev.boxes))
        det.x1 = prev.x1_ghost if same(prev.x1_ghost) and self._usable(frame, prev.x1_ghost) else None
        det.x3 = prev.x3_ghost if not prev.single and same(prev.x3_ghost) \
            and self._usable(frame, prev.x3_ghost) else None
        if det.x1 is None and det.x3 is None:
            return None
        det.x3_seen = det.x3 is not None or (prev.x3_seen and not prev.single)
        return det

    def _usable(self, frame, r):
        """Button area is in colour (a greyed-out button isn't)."""
        x, y, w, h = r
        if w <= 0 or h <= 0:
            return False
        return _saturation(frame[y:y + h, x:x + w]) >= self.sat_ref * MIN_SATURATION_RATIO

    @staticmethod
    def _cyan(row):
        """One pixel row -> bool per pixel: the Reset button's colour."""
        hsv = cv2.cvtColor(row, cv2.COLOR_BGR2HSV)[0].astype(int)
        return (np.abs(hsv[:, 0] - 95) < 12) & (hsv[:, 1] > 90) & (hsv[:, 2] > 100)

    @staticmethod
    def _button_span(frame, cx, top, bh):
        """Left/right edge of the cyan button around x=cx, measured on the rows above and
        below its text (those are solid colour). -> (x0, x1) or None."""
        fh, fw = frame.shape[:2]
        cx = int(round(cx))
        if not 0 <= cx < fw:
            return None
        best = None
        for f in (0.15, 0.22, 0.75, 0.82):
            y = int(round(top + bh * f))
            if not 0 <= y < fh:
                continue
            on = Detector._cyan(frame[y:y + 1])
            if not on[cx]:
                continue
            x0 = x1 = cx
            gap = 0
            while x0 > 0 and gap <= 2:          # tolerate a stray pixel or two
                x0 -= 1
                gap = 0 if on[x0] else gap + 1
            x0 += gap
            gap = 0
            while x1 < fw - 1 and gap <= 2:
                x1 += 1
                gap = 0 if on[x1] else gap + 1
            x1 -= gap
            if best is None or x1 - x0 > best[1] - best[0]:
                best = (x0, x1 + 1)
        return best

    def _find_wide_button(self, frame, gray):
        """Backup when the text match fails (e.g. the mouse is covering "Reset x1"):
        find the wide cyan BEFORE/AFTER button by its colour and shape, then check the
        text still partly matches there. -> same result shape as _best(), or None."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        on = ((np.abs(hsv[..., 0].astype(int) - 95) < 12) & (hsv[..., 1] > 90)
              & (hsv[..., 2] > 100)).astype(np.uint8)
        on = cv2.morphologyEx(on, cv2.MORPH_CLOSE, np.ones((9, 25), np.uint8))   # fill the text
        n, _, stats, _ = cv2.connectedComponentsWithStats(on)
        lay = self.layout
        ratio = lay["single_button_width"] / lay["button_size"][1]
        tr = lay["template_rect"]
        best = None
        for x, y, w, h, area in stats[1:]:
            if h < 12 or not (0.75 * ratio <= w / h <= 1.3 * ratio) or area < 0.8 * w * h:
                continue
            sc = w / lay["single_button_width"]
            mid = x + w / 2
            # where the template would sit (its centre is a little left of the text centre)
            tx = mid - (0.5 - tr[0]) * lay["button_size"][0] * sc - 4.5 * sc
            roi = (int(tx - 10 * sc), int(y - 6 * sc), int((tr[2] * lay["button_size"][0] + 20) * sc),
                   int((tr[3] * lay["button_size"][1] + 12) * sc) + h)
            r = self._best(gray, [sc * k for k in (0.97, 1.0, 1.03)], roi, threshold=0.5)
            if r and (best is None or r[1][0] > best[1][0]):
                best = r
        return best

    def _pick_row(self, frame, rows, scale):
        """Flame and cube windows put the numbers at different heights. BEFORE always
        reads 0, so use the row whose first box reads 0 (else keep the last choice)."""
        import ocr
        for i, boxes in enumerate(rows):
            x, y, w, h = boxes[0]
            if w > 0 and h > 0 and ocr.read_number(frame[y:y + h, x:x + w], True, scale)["kind"] == "zero":
                self.row = i
                return boxes
        return rows[getattr(self, "row", 0)]

    def _build(self, frame, scale, score, x1_tl, x1_score, x3_tl, x3_score, threshold=MATCH_THRESHOLD):
        lay = self.layout
        bw, bh = lay["button_size"][0] * scale, lay["button_size"][1] * scale
        fh, fw = frame.shape[:2]

        def rect(x, y, w, h):
            x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
            x0, y0 = max(0, x), max(0, y)
            return (x0, y0, max(0, min(fw, x + w) - x0), max(0, min(fh, y + h) - y0))

        def usable(r):
            return self._usable(frame, r)

        det = Detection(scale=scale, x1_tl=x1_tl, score=score)
        det.x1_ghost = rect(x1_tl[0], x1_tl[1], bw, bh)
        det.x3_ghost = rect(x1_tl[0] + lay["x3_offset"][0] * scale,
                            x1_tl[1] + lay["x3_offset"][1] * scale, bw, bh)
        if x1_score >= threshold:
            r = rect(x1_tl[0], x1_tl[1], bw, bh)
            det.x1 = r if usable(r) else None
        if x3_tl is not None and x3_score >= threshold:
            det.x3_seen = True
            r = rect(x3_tl[0], x3_tl[1], bw, bh)
            det.x3 = r if usable(r) else None

        w, h = lay["box_size"][0] * scale, lay["box_size"][1] * scale
        # Only one button and it's much wider than a normal one: the BEFORE / AFTER window.
        one = (x1_score >= threshold) != (x3_tl is not None and x3_score >= threshold)
        if one:
            mt = x1_tl if x1_score >= threshold else x3_tl
            tr = lay["template_rect"]
            span = self._button_span(frame, mt[0] + (tr[0] + tr[2] / 2) * bw, mt[1], bh)
            if span and span[1] - span[0] > 1.2 * bw:
                det.single = True
                r = rect(span[0], mt[1], span[1] - span[0], bh)
                det.x1_tl = (span[0], mt[1])
                det.x1_ghost, det.x3_ghost = r, None
                det.x1 = r if usable(r) else None
                det.x3, det.x3_seen = None, False
                # The wide button gives a finer size estimate than the template search.
                s = det.scale = (span[1] - span[0]) / lay["single_button_width"]
                w, h = lay["box_size"][0] * s, lay["box_size"][1] * s
                mid = (span[0] + span[1]) / 2
                rows = [[rect(mid + cx * s - w / 2, mt[1] + cy * s - h / 2, w, h) for cx, cy in lay[k]]
                        for k in ("single_box_centers", "single_box_centers_cube")]
                det.boxes = self._pick_row(frame, rows, s)
                return det
        for cx, cy in lay["box_centers"]:
            x = x1_tl[0] + cx * scale - w / 2
            y = x1_tl[1] + cy * scale - h / 2
            det.boxes.append(rect(x, y, w, h))
        return det
