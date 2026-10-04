"""Place a Dwellings export on a building of its burg's town plan.

The City Generator opens Dwellings with the clicked building's footprint, so a dwelling's
ground floor (a grid of about 2.8 m cells) matches that building's outline. Buildings are
ranked by how well their minimum bounding rectangle and area fit the dwelling's ground floor.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .watabou import Town

CELL_M = 2.8


def footprint(path: str | Path) -> tuple[int, float, float]:
    """(ground-floor cells, long side m, short side m) of a dwelling."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    floor = next(f for f in doc["floors"] if f["level"] == 0)
    cells = {(c["i"], c["j"]) for r in floor["rooms"] for c in r["cells"]}
    rows = max(i for i, _ in cells) - min(i for i, _ in cells) + 1
    cols = max(j for _, j in cells) - min(j for _, j in cells) + 1
    return len(cells), max(rows, cols) * CELL_M, min(rows, cols) * CELL_M


def min_rect(ring: list) -> tuple[float, float]:
    best = None
    n = len(ring)
    for k in range(n):
        (x1, y1), (x2, y2) = ring[k][:2], ring[(k + 1) % n][:2]
        a = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(a), math.sin(a)
        xs = [x * c + y * s for x, y in (p[:2] for p in ring)]
        ys = [-x * s + y * c for x, y in (p[:2] for p in ring)]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if best is None or w * h < best[0]:
            best = (w * h, max(w, h), min(w, h))
    return best[1], best[2]


def _mask(path: str | Path) -> set[tuple[int, int]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    floor = next(f for f in doc["floors"] if f["level"] == 0)
    cells = {(c["i"], c["j"]) for r in floor["rooms"] for c in r["cells"]}
    i0, j0 = min(i for i, _ in cells), min(j for _, j in cells)
    return {(i - i0, j - j0) for i, j in cells}


def _raster(ring: list) -> set[tuple[int, int]]:
    """The building outline sampled on a 2.8 m grid aligned with its minimum rectangle."""
    best = None
    n = len(ring)
    for k in range(n):
        (x1, y1), (x2, y2) = ring[k][:2], ring[(k + 1) % n][:2]
        a = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(a), math.sin(a)
        pts = [(x * c + y * s, -x * s + y * c) for x, y in (p[:2] for p in ring)]
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        if best is None or w * h < best[0]:
            best = (w * h, pts)
    pts = best[1]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    pts = [(x - x0, y - y0) for x, y in pts]
    cols = max(1, round(max(p[0] for p in pts) / CELL_M))
    rows = max(1, round(max(p[1] for p in pts) / CELL_M))
    sx, sy = max(p[0] for p in pts) / cols, max(p[1] for p in pts) / rows

    def inside(x, y):
        hit = False
        for k in range(len(pts)):
            (ax, ay), (bx, by) = pts[k], pts[(k + 1) % len(pts)]
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                hit = not hit
        return hit
    return {(r, q) for r in range(rows) for q in range(cols) if inside((q + 0.5) * sx, (r + 0.5) * sy)}


def _overlap(a: set, b: set) -> float:
    rows = max(i for i, _ in b) if b else 0
    cols = max(j for _, j in b) if b else 0
    variants = [b, {(i, cols - j) for i, j in b}, {(rows - i, j) for i, j in b}, {(rows - i, cols - j) for i, j in b},
                {(j, i) for i, j in b}, {(cols - j, i) for i, j in b}, {(j, rows - i) for i, j in b},
                {(cols - j, rows - i) for i, j in b}]
    return max(len(a & v) / len(a | v) for v in variants) if a and b else 0.0


def rank(town: Town, dwelling: str | Path, top: int = 5) -> list[dict]:
    """Buildings ordered by fit; 'shape' is the overlap of outlines on the 2.8 m grid (1 = identical)."""
    cells, long_m, short_m = footprint(dwelling)
    out = []
    for b in town.buildings:
        L, W = min_rect(b.ring)
        fit = math.hypot(L / long_m - 1, W / short_m - 1) + abs(cells * CELL_M ** 2 / b.area - 1)
        out.append({"building": b.index, "area": b.area, "long": L, "short": W, "score": fit, "shape": None})
    out.sort(key=lambda r: r["score"])
    mask = _mask(dwelling)
    for r in out[:30]:
        r["shape"] = _overlap(mask, _raster(town.buildings[r["building"]].ring))
        r["score"] = r["score"] + (1 - r["shape"])
    out[:30] = sorted(out[:30], key=lambda r: r["score"])
    return out[:top]
