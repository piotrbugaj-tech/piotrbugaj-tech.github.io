"""Virtual twilight: deterministic dusk relight of a daytime photo.

Exterior (sky found):
  * sky -> twilight gradient (blue / pink / golden) with sky.py compositing,
  * foreground darkened (~1.6 EV), cooled and slightly desaturated (ambient dusk light),
  * the sky mask is first extended to daytime sky the detector left out (behind/below tree
    crowns, cut off by branches); if a lot of daytime sky would still remain, the sky is not
    swapped (uniform dusk grade, no seam) and the reason is reported,
  * facade windows lit with a warm glow that keeps frames/mullions, plus a soft light spill on
    the surrounding facade/ground.  Windows are rectangular, framed panes on the facade (dark
    glass, or glass reflecting the sky inside a frame): not on the lawn, in shadows under stairs
    or signs, next to the sky, and repeated across the facade (see find_facade_windows).
Interior (no sky): window views are turned into dusk (darker, bluer), the room keeps its lamps
and gets slightly warmer and darker, like an evening interior.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from ..imgutil import LUMA, linear_to_srgb, resize_max, resize_rows, row_strips, srgb_to_linear
from . import sky as skymod

log = logging.getLogger(__name__)

WARM = np.array([1.0, 0.56, 0.20], np.float32)  # window glow (linear, ~2800 K lamp light)
MAX_SKY_LEFTOVER = 0.25   # daytime sky left outside the (extended) sky mask, relative to it


# --------------------------------------------------------------------------------------------
# facade windows
# --------------------------------------------------------------------------------------------

DARK_LEVELS = np.arange(0.05, 0.72, 0.05)   # luminance thresholds (display sRGB) for dark panes
COLOUR_LEVELS = (12.0, 18.0, 26.0, 36.0)   # Lab distance to the local surroundings (glass, curtains)


def _vegetation(img: np.ndarray) -> np.ndarray:
    """Green / yellow-green, saturated: lawn, shrubs, foliage (also dry lawn)."""
    hsv = cv2.cvtColor(np.ascontiguousarray(img, np.float32), cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (hue >= 50) & (hue <= 170) & (sat > 0.18) & (val > 0.04)


def _ground_line(veg: np.ndarray) -> np.ndarray:
    """Per column: top row of the vegetation (lawn, beds) that reaches up from the bottom edge
    without interruption; h where the bottom is not vegetation.  Running median over 5 % of the
    width bridges paths and thin posts."""
    h, w = veg.shape
    v = cv2.morphologyEx(veg.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    run = np.flip(np.minimum.accumulate(np.flip(v, 0), 0), 0)
    top = np.where(run.any(0), run.argmax(0), h).astype(np.float32)
    k = max(3, int(0.05 * w)) | 1
    pad = np.pad(top, k // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1).astype(np.float32)


def _colour_distance(img: np.ndarray, side: int, fracs=(0.06, 0.15)) -> tuple[np.ndarray, list]:
    """Lab image and the Lab distance of every pixel to the median of its surroundings, for
    windows of 6 % (the facade around a window, not the window itself) and 15 % of the frame
    (the dominant facade material: brick, stucco, siding)."""
    lab = cv2.cvtColor(np.ascontiguousarray(img, np.float32), cv2.COLOR_RGB2Lab)
    off = np.array([0.0, 128.0, 128.0], np.float32)
    sc = np.array([2.55, 1.0, 1.0], np.float32)
    u8 = np.clip((lab + off) * sc, 0, 255).astype(np.uint8)
    out = []
    for f in fracs:
        k = max(15, int(f * side)) | 1
        med = np.stack([cv2.medianBlur(np.ascontiguousarray(u8[..., c]), k) for c in range(3)], -1)
        med = med.astype(np.float32) / sc - off
        out.append(np.sqrt(((lab - med) ** 2).sum(-1)))
    return lab, out


def _fill_holes(m: np.ndarray) -> np.ndarray:
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros(m.shape, np.uint8)
    cv2.drawContours(out, cs, -1, 1, -1)
    return out > 0


def _straightness(f: np.ndarray) -> tuple[float, float, float, float]:
    """How well the region's left/right/top/bottom outline follows its bounding box (fraction of
    the central 80 % of each side within a small tolerance): frames are straight, blobs not."""
    hh, ww = f.shape
    tol = max(1.5, 0.06 * min(ww, hh))
    rows, cols = f.any(1), f.any(0)
    left = np.where(rows, f.argmax(1), ww)
    right = np.where(rows, ww - 1 - np.flip(f, 1).argmax(1), -1)
    top = np.where(cols, f.argmax(0), hh)
    bot = np.where(cols, hh - 1 - np.flip(f, 0).argmax(0), -1)
    a, b = int(0.1 * hh), max(int(0.1 * hh) + 1, int(0.9 * hh))
    c, d = int(0.1 * ww), max(int(0.1 * ww) + 1, int(0.9 * ww))
    return (float(np.mean(left[a:b] <= tol)), float(np.mean(right[a:b] >= ww - 1 - tol)),
            float(np.mean(top[c:d] <= tol)), float(np.mean(bot[c:d] >= hh - 1 - tol)))


def _sides(x0, y0, ww, hh, H, W):
    """Outer and inner strips (row/col slices) along the 4 sides of a box, central 70 %."""
    s = max(2, int(round(0.15 * min(ww, hh))))
    ra, rb = y0 + int(0.15 * hh), y0 + max(int(0.15 * hh) + 1, int(0.85 * hh))
    ca, cb = x0 + int(0.15 * ww), x0 + max(int(0.15 * ww) + 1, int(0.85 * ww))
    outer = ((slice(ra, rb), slice(max(0, x0 - 1 - s), max(0, x0 - 1))),
             (slice(ra, rb), slice(min(W, x0 + ww + 1), min(W, x0 + ww + 1 + s))),
             (slice(max(0, y0 - 1 - s), max(0, y0 - 1)), slice(ca, cb)),
             (slice(min(H, y0 + hh + 1), min(H, y0 + hh + 1 + s)), slice(ca, cb)))
    inner = ((slice(ra, rb), slice(x0, x0 + s)), (slice(ra, rb), slice(x0 + ww - s, x0 + ww)),
             (slice(y0, y0 + s), slice(ca, cb)), (slice(y0 + hh - s, y0 + hh), slice(ca, cb)))
    return outer, inner


def _candidate(kind, comp, box, ctx) -> dict | None:
    """Features of one component (bool crop at box); None when it is clearly not a pane."""
    x0, y0, ww, hh = box
    H, W = ctx["shape"]
    f = _fill_holes(comp)
    area = int(f.sum())
    fill = area / float(ww * hh)
    c = {"kind": kind, "box": box, "mask": f, "area": area, "fill": fill, "aspect": ww / float(hh)}
    rej = []
    if fill < 0.8:
        rej.append("shape")
    st = _straightness(f)
    c["straight"] = st
    if min(st[0], st[1], st[3]) < 0.7 or st[2] < 0.35:   # top may be an arch
        rej.append("shape")
    outer, inner = _sides(x0, y0, ww, hh, H, W)
    y, lab = ctx["y"], ctx["lab"]
    o_y, i_y, o_lab, i_lab = [], [], [], []
    for (orow, ocol), (irow, icol) in zip(outer, inner):
        oy = y[orow, ocol]
        im = f[irow.start - y0:irow.stop - y0, icol.start - x0:icol.stop - x0]
        if oy.size == 0 or not im.any():
            return None
        o_y.append(float(np.median(oy)))
        i_y.append(float(np.median(y[irow, icol][im])))
        o_lab.append(np.median(lab[orow, ocol].reshape(-1, 3), 0))
        i_lab.append(np.median(lab[irow, icol][im], 0))
    ratio = [(o + 0.02) / (i + 0.02) for o, i in zip(o_y, i_y)]
    de = [float(np.linalg.norm(o - i)) for o, i in zip(o_lab, i_lab)]
    c["ratio"], c["de"] = min(ratio), min(de)
    if kind == "dark" and c["ratio"] < 1.4:
        rej.append("contrast")
    if kind == "colour" and c["de"] < 10.0:
        rej.append("contrast")
    # the same facade on both sides (a cast shadow / gap is often bounded by different things)
    c["surround"] = float(np.linalg.norm(o_lab[0] - o_lab[1]))
    if c["surround"] > 22.0:
        rej.append("surround")
    # ring: vegetation / sky around it
    py, px = max(2, hh // 2), max(2, ww // 2)
    r0, r1, c0, c1 = max(0, y0 - py), min(H, y0 + hh + py), max(0, x0 - px), min(W, x0 + ww + px)
    ring = np.ones((r1 - r0, c1 - c0), bool)
    ring[y0 - r0:y0 - r0 + hh, x0 - c0:x0 - c0 + ww] = ~f
    c["veg"] = float(ctx["veg"][y0:y0 + hh, x0:x0 + ww][f].mean())
    c["veg_ring"] = float(ctx["veg"][r0:r1, c0:c1][ring].mean())
    c["sky_ring"] = float(ctx["sky"][r0:r1, c0:c1][ring].mean())
    if c["veg"] > 0.25 or c["veg_ring"] > 0.35:
        rej.append("vegetation")
    if c["sky_ring"] > 0.02 or _sky_above(x0, y0, ww, hh, ctx):
        rej.append("sky")
    cx, cy = x0 + ww // 2, y0 + hh / 2.0
    if cy > ctx["ground"][cx] or y0 + hh > ctx["ground"][cx] + 0.03 * H:
        rej.append("ground")
    # lettering / ornament inside (signs)
    mx, my = max(1, int(0.15 * ww)), max(1, int(0.15 * hh))
    ins = (slice(y0 + my, y0 + hh - my), slice(x0 + mx, x0 + ww - mx))
    c["edges"] = _oblique(ctx, ins)
    c["material_de"] = float(np.median(ctx["de"][ins]))
    if kind == "colour" and (c["material_de"] < 10.0 or min(ww, hh) < 0.018 * max(H, W)):
        rej.append("facade-like")   # an infill panel of the facade material / small ornament
    c["rej"] = rej
    return c


def _sky_above(x0, y0, ww, hh, ctx) -> bool:
    """Sky right above the box (eaves, parapets, gaps between buildings): not a facade window."""
    H = ctx["shape"][0]
    d = int(max(0.8 * hh, 0.03 * H))
    return bool(ctx["sky"][max(0, y0 - d):y0, x0:x0 + ww].any())


def _snap(box, eh, ev, H, W):
    """Move each side of a box to the row/column with the most edge support nearby."""
    x0, y0, ww, hh = box
    x1, y1 = x0 + ww, y0 + hh
    for _ in range(2):
        ww, hh = x1 - x0, y1 - y0
        if ww < 6 or hh < 6:
            break
        r, c = max(2, int(0.2 * hh)), max(2, int(0.2 * ww))
        cs = slice(x0 + ww // 10, x1 - ww // 10)
        rs = slice(y0 + hh // 10, y1 - hh // 10)
        a0, a1 = max(1, y0 - r), min(H - 1, y0 + r + 1)
        y0n = a0 + int(np.argmax(eh[a0:a1, cs].mean(1))) if a1 > a0 else y0
        a0, a1 = max(1, y1 - 1 - r), min(H - 1, y1 + r)
        y1n = a0 + int(np.argmax(eh[a0:a1, cs].mean(1))) + 1 if a1 > a0 else y1
        a0, a1 = max(1, x0 - c), min(W - 1, x0 + c + 1)
        x0n = a0 + int(np.argmax(ev[rs, a0:a1].mean(0))) if a1 > a0 else x0
        a0, a1 = max(1, x1 - 1 - c), min(W - 1, x1 + c)
        x1n = a0 + int(np.argmax(ev[rs, a0:a1].mean(0))) + 1 if a1 > a0 else x1
        x0, y0, x1, y1 = x0n, y0n, x1n, y1n
    return x0, y0, x1 - x0, y1 - y0


def _frame_candidate(box, ctx) -> dict | None:
    """A window found by its frame: four straight edges around a box whose inside differs from
    the facade (glass reflecting the sky, curtains, blinds), whatever its brightness."""
    H, W = ctx["shape"]
    N = H * W
    x0, y0, ww, hh = _snap(box, ctx["eh"], ctx["ev"], H, W)
    if (min(ww, hh) < max(8, 0.018 * max(H, W)) or ww * hh > 0.03 * N or not 0.25 <= ww / float(hh) <= 3.0 or x0 <= 1 or y0 <= 1
            or x0 + ww >= W - 1 or y0 + hh >= H - 1):
        return None
    eh, ev = ctx["eh"], ctx["ev"]
    cs, rs = slice(x0 + ww // 10, x0 + ww - ww // 10), slice(y0 + hh // 10, y0 + hh - hh // 10)
    sup = (float(eh[y0, cs].mean()), float(eh[y0 + hh - 1, cs].mean()),
           float(ev[rs, x0].mean()), float(ev[rs, x0 + ww - 1].mean()))
    f = np.ones((hh, ww), bool)   # the frame itself is excluded by colour when the glass map is built
    c = {"kind": "frame", "box": (x0, y0, ww, hh), "mask": f, "area": ww * hh, "fill": 1.0,
         "aspect": ww / float(hh), "support": min(sup), "straight": (1.0,) * 4}
    rej = []
    if c["support"] < 0.6:
        rej.append("frame")
    # the inside (without the frame) differs from the facade and is not lettering
    mx, my = max(1, int(0.15 * ww)), max(1, int(0.15 * hh))
    ins = (slice(y0 + my, y0 + hh - my), slice(x0 + mx, x0 + ww - mx))
    lab = ctx["lab"]
    e0, e1 = max(2, int(0.1 * min(ww, hh))), max(4, int(0.4 * min(ww, hh)))
    r0, r1, c0, c1 = max(0, y0 - e1), min(H, y0 + hh + e1), max(0, x0 - e1), min(W, x0 + ww + e1)
    ring = np.ones((r1 - r0, c1 - c0), bool)
    ring[max(0, y0 - e0 - r0):y0 + hh + e0 - r0, max(0, x0 - e0 - c0):x0 + ww + e0 - c0] = False
    facade = np.median(lab[r0:r1, c0:c1][ring], 0)
    inside = lab[ins].reshape(-1, 3)
    c["inside_de"] = float(np.linalg.norm(np.median(inside, 0) - facade))
    # a box that overshoots the window onto the wall has much facade colour inside
    c["facade_frac"] = float((np.linalg.norm(inside - facade, axis=1) < 8.0).mean())
    c["material_de"] = float(np.median(ctx["de"][ins]))   # vs the dominant facade material
    if c["facade_frac"] > 0.3 or c["material_de"] < 10.0:
        rej.append("facade-like")
    c["edges"] = _oblique(ctx, ins)
    if c["inside_de"] < 12.0:
        rej.append("facade-like")
    if c["edges"] > 0.09:
        rej.append("texture")
    outer, _ = _sides(x0, y0, ww, hh, H, W)
    o_lab = [np.median(ctx["lab"][rr, cc].reshape(-1, 3), 0) for rr, cc in outer[:2]]
    c["surround"] = float(np.linalg.norm(o_lab[0] - o_lab[1]))
    if c["surround"] > 22.0:
        rej.append("surround")
    py, px = max(2, hh // 2), max(2, ww // 2)
    r0, r1, c0, c1 = max(0, y0 - py), min(H, y0 + hh + py), max(0, x0 - px), min(W, x0 + ww + px)
    ring = np.ones((r1 - r0, c1 - c0), bool)
    ring[y0 - r0:y0 - r0 + hh, x0 - c0:x0 - c0 + ww] = False
    c["veg"] = float(ctx["veg"][y0:y0 + hh, x0:x0 + ww].mean())
    c["veg_ring"] = float(ctx["veg"][r0:r1, c0:c1][ring].mean())
    c["sky_ring"] = float(ctx["sky"][r0:r1, c0:c1][ring].mean())
    if c["veg"] > 0.25 or c["veg_ring"] > 0.35:
        rej.append("vegetation")
    if c["sky_ring"] > 0.02 or _sky_above(x0, y0, ww, hh, ctx):
        rej.append("sky")
    cx = x0 + ww // 2
    if y0 + hh / 2.0 > ctx["ground"][cx] or y0 + hh > ctx["ground"][cx] + 0.03 * H or y0 + hh / 2.0 > 0.92 * H:
        rej.append("ground")
    c["rej"] = rej
    return c


def _oblique(ctx, ins) -> float:
    """Share of the inside with strong edges that are neither horizontal nor vertical: lettering,
    ornaments, lace, foliage -- but not frames, muntins or blinds."""
    ax, ay = np.abs(ctx["gx"][ins]), np.abs(ctx["gy"][ins])
    strong = ax * ax + ay * ay > 0.25 ** 2
    return float((strong & (np.minimum(ax, ay) > 0.4 * np.maximum(ax, ay))).mean()) if ax.size else 1.0


def _similar(a, b) -> bool:
    """Same-size panes in one row or one column (windows repeat across a facade)."""
    xa, ya, wa, ha = a["box"]
    xb, yb, wb, hb = b["box"]
    if abs(wa - wb) > 0.25 * max(wa, wb) or abs(ha - hb) > 0.25 * max(ha, hb):
        return False
    if xa < xb + wb and xb < xa + wa and ya < yb + hb and yb < ya + ha:
        return False  # overlapping boxes are the same window
    row = abs(ya - yb) <= 0.3 * max(ha, hb) and abs(ya + ha - yb - hb) <= 0.3 * max(ha, hb)
    col = abs(xa - xb) <= 0.3 * max(wa, wb) and abs(xa + wa - xb - wb) <= 0.3 * max(wa, wb)
    return row or col


def find_facade_windows(img_small: np.ndarray, sky_mask: np.ndarray | None, stats: dict | None = None
                        ) -> tuple[np.ndarray, list]:
    """Window panes (and glazed doors) of a daytime facade.  Returns (glass weight 0..1, boxes).

    Candidates, at several levels: connected regions darker than a luminance level (dark glass)
    or differing in colour from the local facade (glass reflecting the sky, blinds), and boxes
    snapped to four straight frame edges around such regions (framed panes whose glass is not one
    uniform region).  A window must be
      * rectangular: a region fills >= 80 % of its box with straight left/right/bottom outline
        (the top may be an arch); a frame has edge support on all four sides,
      * framed: a contrast step on all four sides (luminance ratio for dark glass, Lab distance
        otherwise), the same facade on its left and right (not a shadow/gap between different
        things), its inside not the facade material (stucco panel, stone block) and without
        oblique edges (lettering, ornaments, lace, foliage),
      * on the facade: not touching the frame border, no sky next to or right above it (eaves,
        parapets), not vegetation and not surrounded by it, above the ground line (top of the
        lawn/beds reaching up from the bottom edge) and not in the bottom 8 % of the frame,
      * and either a large, strongly framed dark pane, or repeated: another valid pane of about
        the same size in the same row or column (facades repeat windows; lawn patches, shadows
        and signs rarely do).
    The glass weight keeps only the pane's own colour inside each window (frames, trims and
    muntins stay unlit).  ``stats`` (optional dict) receives candidate/rejection counts."""
    h, w = img_small.shape[:2]
    N = h * w
    y = (img_small @ LUMA).astype(np.float32)
    lab, (de, de_wide) = _colour_distance(img_small, max(h, w))
    veg = _vegetation(img_small)
    sky = (sky_mask > 0.5) if sky_mask is not None else np.zeros((h, w), bool)
    skyd = cv2.dilate(sky.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    g = cv2.GaussianBlur(y, (0, 0), 1.0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    # oriented edges with 1 px tolerance across the edge (slightly tilted frames)
    eh = cv2.dilate(((np.abs(gy) > 0.12) & (np.abs(gy) > 1.5 * np.abs(gx))).astype(np.uint8), np.ones((3, 1), np.uint8)) > 0
    ev = cv2.dilate(((np.abs(gx) > 0.12) & (np.abs(gx) > 1.5 * np.abs(gy))).astype(np.uint8), np.ones((1, 3), np.uint8)) > 0
    ctx = {"shape": (h, w), "y": y, "lab": lab, "de": de_wide, "veg": veg, "sky": skyd, "ground": _ground_line(veg),
           "gx": gx, "gy": gy, "eh": eh, "ev": ev}
    amin, amax = max(40, 0.0001 * N), 0.03 * N
    levels = [("dark", y < t) for t in DARK_LEVELS] + [("colour", de > t) for t in COLOUR_LEVELS]
    cands, nrej = [], {}
    seen = set()
    for kind, m in levels:
        m = (m & ~skyd).astype(np.uint8)
        n, lb, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
        x0, y0, ww, hh, area = (st[:, i] for i in range(5))
        loose = (area >= amin / 4) & (ww * hh <= amax) & (np.minimum(ww, hh) >= 8) & (ww <= 3 * hh) & (hh <= 4 * ww)
        loose &= (x0 > 1) & (y0 > 1) & (x0 + ww < w - 1) & (y0 + hh < h - 1) & ((y0 + hh / 2.0) < 0.92 * h)
        loose[0] = False
        ok = loose & (area >= amin) & (area <= amax) & (np.minimum(ww, hh) >= 6) & (area >= 0.7 * ww * hh)
        for i in np.nonzero(loose)[0]:
            bx = (int(x0[i]), int(y0[i]), int(ww[i]), int(hh[i]))
            if ok[i]:
                c = _candidate(kind, lb[bx[1]:bx[1] + bx[3], bx[0]:bx[0] + bx[2]] == i, bx, ctx)
                if c is not None and not c["rej"]:
                    cands.append(c)
                    continue
                for r in set(c["rej"] if c is not None else ()):
                    nrej[r] = nrej.get(r, 0) + 1
            # framed window whose glass is not one uniform region (reflections, curtains, blinds)
            key = tuple(v // 3 for v in bx)
            if key in seen:
                continue
            seen.add(key)
            c = _frame_candidate(bx, ctx)
            if c is None:
                continue
            if c["rej"]:
                for r in set(c["rej"]):
                    nrej["frame:" + r] = nrej.get("frame:" + r, 0) + 1
                continue
            cands.append(c)
    # repetition: a pane of the same size in the same row/column (any valid candidate)
    acc = []
    for c in cands:
        okshape = 0.25 <= c["aspect"] <= 3.0
        partner = okshape and any(_similar(c, o) for o in cands if o is not c and 0.25 <= o["aspect"] <= 3.0)
        strong = (c["kind"] == "dark" and c["area"] >= 0.0006 * N and c["ratio"] >= 1.8
                  and min(c["straight"]) >= 0.85 and okshape)
        if partner and (c["kind"] == "dark" or c["edges"] <= 0.09) or strong:
            acc.append(c)
        else:
            nrej["isolated"] = nrej.get("isolated", 0) + 1
    # one region per window: the largest accepted one (whole window rather than single panes)
    acc.sort(key=lambda c: -c["area"])
    kept = []
    for c in acc:
        x0, y0, ww, hh = c["box"]
        dup = False
        for k in kept:
            kx, ky, kw, kh = k["box"]
            ix0, iy0, ix1, iy1 = max(x0, kx), max(y0, ky), min(x0 + ww, kx + kw), min(y0 + hh, ky + kh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (c["mask"][iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] & k["mask"][iy0 - ky:iy1 - ky, ix0 - kx:ix1 - kx]).sum()
            if inter > 0.3 * min(c["area"], k["area"]):
                dup = True
                break
        if not dup:
            kept.append(c)
    acc = kept
    glass = np.zeros((h, w), np.float32)
    boxes = []
    for c in acc:
        x0, y0, ww, hh = c["box"]
        # glass = pixels of the pane's own colour; frames, trims and muntins stay unlit
        mx, my = max(1, int(0.2 * ww)), max(1, int(0.2 * hh))
        core = lab[y0 + my:y0 + hh - my, x0 + mx:x0 + ww - mx].reshape(-1, 3)
        ref = np.median(core, 0)
        d = np.linalg.norm(lab[y0:y0 + hh, x0:x0 + ww] - ref, axis=-1)
        wgt = np.clip(1.0 - (d - 12.0) / 20.0, 0.0, 1.0) * c["mask"]
        glass[y0:y0 + hh, x0:x0 + ww] = np.maximum(glass[y0:y0 + hh, x0:x0 + ww], wgt)
        boxes.append(c["box"])
    if stats is not None:
        if stats.get("debug"):
            stats["accepted"] = acc
        stats.update(candidates=len(cands), rejected=nrej, dark=sum(c["kind"] == "dark" for c in acc),
                     colour=sum(c["kind"] == "colour" for c in acc), frame=sum(c["kind"] == "frame" for c in acc))
    return glass, boxes


def twilight(img: np.ndarray, cfg: dict, name: str, win=None, sky_mask_small: np.ndarray | None = None
             ) -> tuple[np.ndarray, dict]:
    tcfg = cfg.get("modules", {}).get("twilight", {})
    style = str(tcfg.get("style", "pink"))
    ev = float(tcfg.get("darken_ev", 2.0))
    glow = float(tcfg.get("window_glow", 1.0))
    H, W = img.shape[:2]
    small, _ = resize_max(img, 1000)
    hs, ws = small.shape[:2]
    if sky_mask_small is None:
        sky_mask_small, sinfo = skymod.detect_sky(small)
    else:
        sinfo = {}
    info = {"style": style, "exterior": sky_mask_small is not None}
    rng = np.random.default_rng(skymod.seed_of(name))
    if sky_mask_small is not None:
        # ---- exterior ------------------------------------------------------------------------
        # all of the daytime sky must go: add sky the detector left out (behind tree crowns,
        # cut off by branches); if a lot of daytime sky would still stay next to the twilight
        # gradient, do not swap the sky at all (uniform dusk grade instead of a visible seam)
        sky_mask_small, einfo = skymod.extend_sky_mask(small, sky_mask_small)
        info["sky_extension"] = einfo
        swap = float(einfo.get("leftover", 0.0)) <= MAX_SKY_LEFTOVER
        if not swap:
            info["sky_swap"] = False
            info["sky_swap_reason"] = (f"daytime sky outside the detected sky ({einfo['leftover']:.0%} of it) "
                                       "would stay next to the twilight sky: sky kept, only darkened")
        wstats: dict = {}
        glass, boxes = find_facade_windows(small, sky_mask_small, wstats)
        info["windows_lit"] = len(boxes)
        info["windows"] = wstats
        # per-window brightness variation + top-to-bottom falloff inside each pane
        gmap = np.zeros((hs, ws), np.float32)
        for (x0, y0, ww, hh) in boxes:
            v = float(rng.uniform(0.75, 1.15))
            ramp = np.linspace(1.0, 0.7, hh, dtype=np.float32)[:, None]
            gmap[y0:y0 + hh, x0:x0 + ww] = np.maximum(gmap[y0:y0 + hh, x0:x0 + ww], v * ramp)
        gmap *= glass   # glass weight already excludes frames, trims and muntins
        spill = cv2.GaussianBlur(gmap, (0, 0), max(3.0, 0.012 * ws)) * 0.9 + \
            cv2.GaussianBlur(gmap, (0, 0), max(1.0, 0.003 * ws)) * 0.4
        sky_soft = cv2.GaussianBlur(sky_mask_small.astype(np.float32), (0, 0), 1.0) if swap else None
        k = 2.0 ** -ev
        cool = np.array([0.74, 0.90, 1.30], np.float32)
        cool /= float(cool @ LUMA)
        g_int = 0.95 * glow
        for r0, r1 in row_strips(H, W):
            lin = srgb_to_linear(img[r0:r1])
            yv = (lin @ LUMA)[..., None]
            fg = (yv + (lin - yv) * 0.7) * k * cool          # darker, cooler, less saturated
            gm = resize_rows(gmap, W, H, r0, r1)[..., None]
            sp = resize_rows(spill, W, H, r0, r1)[..., None]
            # lit panes: warm, brighter in the middle of the pane, a hint of the original detail
            fg = fg * (1 - gm) + WARM * g_int * gm * (0.8 + 0.4 * np.clip(yv * 4, 0, 1))
            fg = fg + WARM * sp * 0.18 * glow + fg * sp * 0.6 * WARM  # light spill on the facade
            if sky_soft is None:
                img[r0:r1] = linear_to_srgb(np.clip(fg, 0, 1))
                continue
            s = resize_rows(sky_soft, W, H, r0, r1)[..., None]
            # sky pixels are replaced afterwards; keep them unchanged here to preserve the matte
            img[r0:r1] = linear_to_srgb(np.clip(lin * s + fg * (1 - s), 0, 1))
        if swap:
            img, cinfo = skymod.replace_sky(img, cfg, name, style=style, twilight=True, mask_small=sky_mask_small)
            info["sky"] = {k2: v for k2, v in cinfo.items() if k2 != "mask_small"}
    else:
        # ---- interior: dusk through the windows ---------------------------------------------
        info["reason"] = sinfo.get("reason")
        wm = None
        if win is not None and win.mask.max() > 0.5:
            wm = cv2.resize(np.clip(win.mask, 0, 1).astype(np.float32), (ws, hs))
            wm = cv2.GaussianBlur(wm, (0, 0), 1.0)
        stops = skymod.TWILIGHT_STYLES.get(style, skymod.TWILIGHT_STYLES["pink"])
        dusk = srgb_to_linear(np.array(stops[1], np.float32))
        dusk = dusk / max(float(dusk @ LUMA), 1e-4)
        for r0, r1 in row_strips(H, W):
            lin = srgb_to_linear(img[r0:r1])
            yv = (lin @ LUMA)[..., None]
            room = lin * 2.0 ** -0.35 * np.array([1.04, 1.0, 0.94], np.float32)  # evening, warmer
            if wm is not None:
                m = resize_rows(wm, W, H, r0, r1)[..., None]
                f = 2.0 ** -1.8
                view = yv * f * dusk + (lin - yv) * 0.15 * f  # dark, dusk-tinted view keeping shapes
                room = room * (1 - m) + view * m
            img[r0:r1] = linear_to_srgb(np.clip(room, 0, 1))
        info["window_views"] = wm is not None
    return img, info
