"""Rebuilds templates/glyphs/*.png (the digit shapes the OCR compares against).

Give it screenshots of the reset window and the numbers shown in them, left to
right. Every digit 0-9 must appear at least once across all screenshots.

  python build_glyphs.py samples/all_negative.png 0 -24,608,869 -21,740,446 -22,568,758 \
                         samples/one_positive.png 0 +16,953 -718,815 -57,641
"""
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

import ocr
from detector import Detector


def main(argv):
    groups, cur = [], None
    for a in argv:
        if a.lower().endswith((".png", ".jpg", ".bmp")):
            cur = (a, [])
            groups.append(cur)
        else:
            cur[1].append(a)

    samples = defaultdict(list)
    for path, truths in groups:
        img = cv2.imread(path)
        det = Detector().find(img)
        if det is None:
            sys.exit(f"Reset buttons not found in {path}")
        for (x, y, w, h), truth in zip(det.boxes, truths):
            crop = img[y:y + h, x:x + w]
            gray, mask = ocr.text_mask(crop)
            segs = [s for s in ocr.segments(mask) if s[2] * s[3] >= 2]
            digit_h = max(s[3] for s in segs)
            tall = [s for s in segs if s[3] >= 0.75 * digit_h]
            band = (min(s[1] for s in tall), max(s[1] + s[3] for s in tall))
            digits = [p for s in tall for p in ocr.split_wide(s, digit_h)]
            want = [c for c in truth if c.isdigit()]
            if len(digits) != len(want):
                print(f"skip {truth!r} in {path}: found {len(digits)} digits")
                continue
            for box, ch in zip(digits, want):
                samples[ch].append(ocr.normalize_glyph(gray, box, band))

    missing = [d for d in "0123456789" if d not in samples]
    if missing:
        sys.exit(f"No examples of digits {missing}")
    os.makedirs(ocr.GLYPH_DIR, exist_ok=True)
    for d, imgs in sorted(samples.items()):
        avg = np.mean(imgs, axis=0)
        cv2.imwrite(os.path.join(ocr.GLYPH_DIR, f"{d}.png"), (avg * 255).astype(np.uint8))
        print(f"{d}: {len(imgs)} examples")


if __name__ == "__main__":
    main(sys.argv[1:])
