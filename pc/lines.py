"""Reads the potential lines of the cube window's AFTER result and checks them
against a line target (e.g. 2 lines of item drop / mesos).

Uses RapidOCR (pip install rapidocr-onnxruntime), loaded the first time it's needed.
"""
import re

import cv2

# name -> (label, kinds that count, lines needed)
TARGETS = {
    "off": ("OFF", (), 0),
    "drop2": ("2 DROP", ("drop",), 2),
    "meso2": ("2 MESO", ("meso",), 2),
    "dropmeso2": ("2 DROP/MESO", ("drop", "meso"), 2),
    "dropmeso3": ("3 DROP/MESO", ("drop", "meso"), 3),
}
ORDER = list(TARGETS)

_ocr = None


def available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def lines_box(det, which=-1):
    """Where the potential lines are: above the number box (cube window only)."""
    x, y, w, h = det.boxes[which]
    s = det.scale
    return int(x - 12 * s), int(y - 125 * s), int(w + 27 * s), int(73 * s)


def read_lines(frame, det, which=-1):
    """Text of each potential line of a result, top to bottom."""
    x, y, w, h = lines_box(det, which)
    crop = frame[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return []
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    res, _ = _engine()(big)
    res = sorted(res or [], key=lambda r: r[0][0][1])     # by the top edge of each line
    return [r[1] for r in res]


def kind(text):
    """'drop', 'meso' or None. Lenient: the reader sometimes mixes up 0/o and similar."""
    t = re.sub(r"[^a-z]", "", text.lower().replace("0", "o"))
    if "drop" in t or "itemdr" in t:
        return "drop"
    if "meso" in t or "obtained" in t or "btained" in t:
        return "meso"
    return None


def check(target, texts):
    """-> (met, count, kinds of each line)."""
    _, wanted, need = TARGETS[target]
    kinds = [kind(t) for t in texts]
    count = sum(k in wanted for k in kinds)
    return need > 0 and count >= need, count, kinds
