"""Photo straightening and hold detection. Rectified images are 1 px = 1 mm."""
import sys

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

DEFAULTS = {'s_thr': 90, 'v_thr': 70, 'white_contrast': 30, 'dark_contrast': 25, 'dark_min_area': 6000, 'white_s': 60, 'min_area': 1500, 'colour_min_area': 500, 'volume_area': 30000}
# hue bins on OpenCV's 0..180 scale
HUES = [('red', 0, 8), ('orange', 8, 18), ('yellow', 18, 35), ('green', 35, 85), ('blue', 85, 128),
        ('purple', 128, 150), ('pink', 150, 172), ('red', 172, 181)]


def load_image(path, max_side=4000):
    """-> BGR array, EXIF-rotated, downscaled to max_side."""
    im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    im.thumbnail((max_side, max_side))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def rectify(img, main_corners, kicker_corners, width, height, kicker):
    """corners: [[x,y] TL, TR, BR, BL] in image px. -> straight-on image width x (height+kicker), 1 px = 1 mm."""
    def warp(corners, h):
        dst = np.float32([[0, 0], [width, 0], [width, h], [0, h]])
        m = cv2.getPerspectiveTransform(np.float32(corners), dst)
        return cv2.warpPerspective(img, m, (int(width), int(h)), flags=cv2.INTER_AREA)
    parts = [warp(main_corners, height)]
    if kicker and kicker_corners:
        parts.append(warp(kicker_corners, kicker))
    return np.vstack(parts)


def detect(rect, height, params=None):
    """Find holds on a dark wall. height = main panel height (mm); anything below it is kicker.
    -> list of hold dicts in mm."""
    p = {**DEFAULTS, **(params or {})}
    hsv = cv2.cvtColor(cv2.GaussianBlur(rect, (5, 5), 0), cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    H, W = h.shape
    colour = (s > p['s_thr']) & (v > p['v_thr'])
    # local background brightness, so glare on the wall doesn't read as white holds
    small = cv2.resize(v, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.medianBlur(small, 31), (v.shape[1], v.shape[0]))
    white = (cv2.subtract(v, bg) > p['white_contrast']) & (s < p['white_s'])
    dark = (cv2.subtract(bg, v) > p['dark_contrast']) & (s < p['white_s'])  # black holds; T-nut smudges too
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    k15 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    masks = [(name, colour & (h >= lo) & (h < hi)) for name, lo, hi in HUES] + [('white', white), ('black', dark)]
    merged = {}
    for name, m in masks:
        merged[name] = merged.get(name, False) | m
    holds = []
    for name, m in merged.items():
        m = cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_OPEN, k)
        # grey/black holds get split by their bolt and washer; close harder to merge the pieces
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k if name not in ('white', 'black') else k15)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            min_area = {'black': p['dark_min_area'], 'white': p['min_area']}.get(name, p['colour_min_area'])
            if area < min_area:
                continue
            if name == 'black' and area / cv2.contourArea(cv2.convexHull(c)) < .85:
                continue  # smudges are ragged
            bx, by, bw, bh = cv2.boundingRect(c)
            if bx <= 2 or by <= 2 or bx + bw >= W - 2 or by + bh >= H - 2:
                continue  # touches the panel edge: brackets, frame, floor
            if min(cv2.minAreaRect(c)[1]) < 25:
                continue  # slivers: wood edges, cables
            mo = cv2.moments(c)
            x, y = mo['m10'] / mo['m00'], mo['m01'] / mo['m00']
            poly = cv2.approxPolyDP(c, 4, True).reshape(-1, 2)
            holds.append({'x': round(x), 'y': round(y), 'r': round(float(np.sqrt(area / np.pi))),
                          'area': round(area), 'color': name, 'poly': poly.tolist(),
                          'kind': 'volume' if area > p['volume_area'] else 'hold'})
    return with_defaults(merge_fragments(holds), height)


def merge_fragments(holds):
    """One hold split across hue bins (or by its bolt) -> merge pieces whose equivalent circles overlap."""
    holds = sorted(holds, key=lambda h: -h['area'])
    keep = []
    for h in holds:
        k = next((k for k in keep if k['kind'] == 'hold' and h['kind'] == 'hold' and
                  np.hypot(k['x'] - h['x'], k['y'] - h['y']) < k['r'] + h['r']), None)
        if k is None:
            keep.append(h)
            continue
        hull = cv2.convexHull(np.int32(k['poly'] + h['poly']))
        a = k['area'] + h['area']
        k.update(x=round((k['x'] * k['area'] + h['x'] * h['area']) / a), y=round((k['y'] * k['area'] + h['y'] * h['area']) / a),
                 area=a, r=round(float(np.sqrt(a / np.pi))), poly=hull.reshape(-1, 2).tolist())
    return keep


def with_defaults(holds, height):
    """Guess attributes so most holds need no editing: kicker -> foot, size terciles -> easy/medium/hard."""
    areas = sorted(h['area'] for h in holds if h['kind'] == 'hold' and h['y'] <= height)
    t1, t2 = (areas[len(areas) // 3], areas[2 * len(areas) // 3]) if areas else (0, 0)
    for i, h in enumerate(sorted(holds, key=lambda h: (h['y'], h['x']))):
        h['id'] = f'h{i + 1}'
        h['difficulty'] = 200 if h['y'] > height else 96 if h['area'] < t1 else 64 if h['area'] < t2 else 32
        h.setdefault('type', 2)
        h.setdefault('direction', 1)
    return holds


if __name__ == '__main__':
    # python -m app.detect photo.jpg x1,y1,...,x8,y8 W H K out.png   (corners as fractions of image size)
    img = load_image(sys.argv[1])
    ih, iw = img.shape[:2]
    pts = [float(v) for v in sys.argv[2].split(',')]
    pts = [[pts[i] * iw, pts[i + 1] * ih] for i in range(0, 16, 2)]
    W, H, K = (int(v) for v in sys.argv[3:6])
    rect = rectify(img, pts[:4], pts[4:], W, H, K)
    holds = detect(rect, H)
    out = rect.copy()
    for hd in holds:
        col = (0, 0, 255) if hd['kind'] == 'volume' else (255, 255, 255)
        cv2.polylines(out, [np.int32(hd['poly'])], True, col, 4)
        cv2.putText(out, hd['color'][:2], (hd['x'], hd['y']), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    cv2.imwrite(sys.argv[6], out)
    print(len(holds), 'holds,', sum(h['kind'] == 'volume' for h in holds), 'volumes')
