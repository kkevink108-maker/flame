"""Reads the "Combat Power Change" numbers (e.g. "+16,953", "-718,815", "0").

The game always uses the same font, so instead of a general OCR engine this
splits the number into glyphs and matches each digit against small reference
images in templates/glyphs/ (made from real screenshots by build_glyphs.py).
Signs and commas are recognized by their shape. Works at any UI scale.
"""
import os
import re

import cv2
import numpy as np

from paths import RESOURCE_DIR

GLYPH_DIR = os.path.join(RESOURCE_DIR, "templates", "glyphs")
GLYPH_SIZE = (20, 26)       # (w, h) every glyph is normalized to
MIN_DIGIT_SCORE = 0.55      # below this a digit is "not sure"
NUMBER_RE = re.compile(r"^([+-]?)(\d{1,3}(?:,\d{3})*)$")

_glyphs = None


def text_mask(crop):
    """Binary mask of the text pixels (text is lighter than the panel)."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    bg = float(np.median(g))
    hi = float(np.percentile(g, 99.5))
    if hi - bg < 45:           # nothing noticeably brighter than the background
        return g, None
    return g, g > (bg + hi) / 2


def segments(mask):
    """Split the mask into glyphs by empty columns -> [(x, y, w, h)]."""
    cols = mask.any(axis=0)
    out, i, n = [], 0, len(cols)
    while i < n:
        if not cols[i]:
            i += 1
            continue
        j = i
        while j < n and cols[j]:
            j += 1
        rows = np.where(mask[:, i:j].any(axis=1))[0]
        out.append((i, int(rows[0]), j - i, int(rows[-1] - rows[0] + 1)))
        i = j
    return out


def normalize_glyph(gray, box, band):
    """Cut a glyph out using the shared digit band (top..bottom of the digit row) so
    every digit is framed the same way, keep its aspect ('1' stays narrow), resize."""
    x, _, w, _ = box
    top, bottom = band
    h = bottom - top
    g = gray[top:bottom, x:x + w].astype(np.float32)
    g = (g - g.min()) / max(1.0, g.max() - g.min())
    cw = max(w, int(round(h * 0.8)))
    canvas = np.zeros((h, cw), np.float32)
    ox = (cw - w) // 2
    canvas[:, ox:ox + w] = g
    return cv2.resize(canvas, GLYPH_SIZE, interpolation=cv2.INTER_AREA)


def load_glyphs():
    global _glyphs
    if _glyphs is None:
        _glyphs = {}
        for d in "0123456789":
            p = os.path.join(GLYPH_DIR, f"{d}.png")
            if os.path.exists(p):
                _glyphs[d] = cv2.imread(p, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
    return _glyphs


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


def classify_digit(norm):
    """Best matching digit, allowing the glyph to be off by a pixel either way."""
    best, best_s = None, -1.0
    padded = np.pad(norm, 1)
    h, w = norm.shape
    for d, t in load_glyphs().items():
        s = max(_ncc(padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w], t)
                for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        if s > best_s:
            best, best_s = d, s
    return best, best_s


def split_wide(box, digit_h):
    """Two digits touching (happens at small scales) -> split evenly."""
    x, y, w, h = box
    pitch = digit_h * 0.75
    n = max(1, int(round(w / pitch)))
    if n == 1 or w < digit_h * 0.95:
        return [box]
    step = w / n
    return [(int(round(x + k * step)), y, int(round(step)), h) for k in range(n)]


def recognize(crop):
    """-> (text, confidence) ; text is '' when the box is empty."""
    gray, mask = text_mask(crop)
    if mask is None:
        return "", 1.0
    segs = [s for s in segments(mask) if s[2] * s[3] >= 2]
    # Drop bits of the panel border touching the crop edge.
    segs = [s for s in segs if s[0] > 0 and s[0] + s[2] < mask.shape[1]]
    if not segs:
        return "", 1.0
    digit_h = max(s[3] for s in segs)
    tall = [s for s in segs if s[3] >= 0.75 * digit_h]
    top = min(s[1] for s in tall)
    bottom = max(s[1] + s[3] for s in tall)
    mid = (top + bottom) / 2

    text, conf = "", 1.0
    for s in segs:
        x, y, w, h = s
        if h >= 0.75 * digit_h:
            for part in split_wide(s, digit_h):
                d, score = classify_digit(normalize_glyph(gray, part, (top, bottom)))
                text += d or "?"
                conf = min(conf, score)
        elif y > mid:                                # low and small -> comma
            text += ","
        elif any(c.isdigit() for c in text):         # a sign can only come first; this is
            continue                                 # a speck of the panel border, skip it
        elif h <= 0.3 * digit_h and w >= 2 * h:      # flat bar in the middle -> minus
            text += "-"
        elif h >= 0.3 * digit_h and w >= 0.3 * digit_h:  # cross in the middle -> plus
            text += "+"
        else:
            text += "?"
            conf = 0.0
    return text, conf


def parse(text):
    """'+16,953' -> ('+', 16953). None if it isn't a well-formed number."""
    m = NUMBER_RE.match(text)
    if not m:
        return None
    return m.group(1), int(m.group(2).replace(",", ""))


def classify(sign, value, require_plus=True):
    """'positive', 'negative', 'zero' or 'unknown'."""
    if value == 0:
        return "zero"
    if sign == "+":
        return "positive"
    if sign == "-":
        return "negative"
    # Nonzero with no sign seen: the game always shows +/-, so the sign was missed.
    return "unknown" if require_plus else "positive"


def read_number(crop, require_plus=True, scale=1.0):
    """OCR one number box -> dict(text, sign, value, kind, conf).

    scale is the UI scale from the detector; the crop is resampled back to the
    size the glyph templates were made at.
    kind is 'positive', 'negative', 'zero', 'empty' (nothing shown) or 'unknown'.
    """
    if crop is None or crop.size == 0:
        return {"text": "", "sign": None, "value": None, "kind": "empty", "conf": 1.0}
    if abs(scale - 1.0) > 0.03:
        crop = cv2.resize(crop, None, fx=1 / scale, fy=1 / scale,
                          interpolation=cv2.INTER_AREA if scale > 1 else cv2.INTER_CUBIC)
    text, conf = recognize(crop)
    if text == "":
        return {"text": "", "sign": None, "value": None, "kind": "empty", "conf": 1.0}
    parsed = parse(text)
    if parsed is None or conf < MIN_DIGIT_SCORE:
        return {"text": text, "sign": None, "value": None, "kind": "unknown", "conf": conf}
    sign, value = parsed
    return {"text": text, "sign": sign, "value": value,
            "kind": classify(sign, value, require_plus), "conf": conf}
