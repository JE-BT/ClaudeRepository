"""Feature outlines (coasts and lake shores) from the SVG embedded in a .map.

Azgaar keeps one smoothed outline per feature in <defs><g id="featurePaths"> as
<path id="feature_N" d="...">, and the coastline and lakes layers <use> them. These are the
shapes the user sees, so the tile grid takes land and water from them rather than from the raw
Voronoi polygons. Paths use absolute M, L, H, V, Q, C and Z commands (relative forms are also
handled); curves are flattened into short line segments.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[MmLlHhVvQqCcZzTtSs]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")
_PATH = re.compile(r"<path\b([^>]*)>")
_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')


def feature_paths(svg: str) -> dict[int, str]:
    """Map feature id -> path data, from the featurePaths group."""
    start = svg.find('id="featurePaths"')
    if start < 0:
        return {}
    end = svg.find("</g>", start)
    out = {}
    for m in _PATH.finditer(svg, start, end):
        attrs = dict(_ATTR.findall(m.group(1)))
        fid = attrs.get("id", "")
        if fid.startswith("feature_") and attrs.get("d"):
            out[int(fid[8:])] = attrs["d"]
    return out


def flatten(d: str, steps: int = 6) -> list[list[tuple[float, float]]]:
    """Flatten SVG path data into closed polylines (one per subpath)."""
    toks = _TOKEN.findall(d)
    rings: list[list[tuple[float, float]]] = []
    ring: list[tuple[float, float]] = []
    i, cmd = 0, None
    x = y = sx = sy = 0.0

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if ring:
                    rings.append(ring)
                ring, x, y = [], sx, sy
                continue
        if cmd is None:
            i += 1
            continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            if ring:
                rings.append(ring)
            x, y = num() + ox, num() + oy
            sx, sy = x, y
            ring = [(x, y)]
            cmd = "l" if rel else "L"  # implicit lineto after moveto
        elif c == "L":
            x, y = num() + ox, num() + oy
            ring.append((x, y))
        elif c == "H":
            x = num() + (x if rel else 0)
            ring.append((x, y))
        elif c == "V":
            y = num() + (y if rel else 0)
            ring.append((x, y))
        elif c in "QT":
            if c == "Q":
                qx, qy = num() + ox, num() + oy
            else:
                qx, qy = x, y
            ex, ey = num() + ox, num() + oy
            for k in range(1, steps + 1):
                u = k / steps
                a, b, cc = (1 - u) ** 2, 2 * (1 - u) * u, u * u
                ring.append((a * x + b * qx + cc * ex, a * y + b * qy + cc * ey))
            x, y = ex, ey
        elif c in "CS":
            if c == "C":
                c1x, c1y = num() + ox, num() + oy
            else:
                c1x, c1y = x, y
            c2x, c2y = num() + ox, num() + oy
            ex, ey = num() + ox, num() + oy
            for k in range(1, steps + 1):
                u = k / steps
                a, b, cc, dd = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3
                ring.append((a * x + b * c1x + cc * c2x + dd * ex, a * y + b * c1y + cc * c2y + dd * ey))
            x, y = ex, ey
        else:  # unsupported command: skip a number to avoid an endless loop
            i += 1
    if ring:
        rings.append(ring)
    return [r for r in rings if len(r) >= 3]
