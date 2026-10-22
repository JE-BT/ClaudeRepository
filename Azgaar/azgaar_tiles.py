#!/usr/bin/env python3
"""azgaar_tiles.py: grid references and tile data reports for Azgaar's Fantasy Map Generator.

Commands
  info    WORLD                   what was loaded, and how the grid is referenced
  map     WORLD                   overview reference map (SVG): coastline, lettered squares, grid lines
  sheet   WORLD REF|PLACE         zoomed reference sheet (SVG) with every tile outlined and numbered
  find    WORLD TEXT              look places up by name and print their grid references
  report  WORLD REF|PLACE         every piece of data for one tile, as a LaTeX file (dndbook class)
  export  WORLD [REF|PLACE]       GIS layers of the whole map or of a sheet, as GeoJSON or a GeoPackage

WORLD is a .map file, a folder that holds one, or a world name looked up under --worlds (default:
./Azgaar and the current folder). The newest .map is used unless --map is given. The tool also needs
the world's Cells GeoJSON export (Azgaar: Menu > Export > GeoJSON > Cells), because the .map stores
no cell outlines; it is found in the same folder and matched by content.

Grid references
  The grid is Azgaar's own grid overlay (Style > Grid: type, scale, shift), rebuilt from the saved
  style so the tiles line up with the lines Azgaar draws. Square, pointy-top hex, flat-top hex and
  45-degree square overlays are supported; --grid and --size set a grid of your own instead.
  References follow the Ordnance Survey pattern. Two letters name a square of 100 x 100 tiles (the
  first letter counts squares eastward, the second northward, from the south-west corner of the
  map; I is not used). Digits then give eastings before northings inside the square:
      CB 12 47     the tile 12 columns east and 47 rows north of square CB's south-west corner
      CB 1 4       the 10 x 10 block that holds tiles CB 10 40 to CB 19 49
      CB 123 474   a point, to a tenth of a tile width and of a row
  Places can be given by name (a burg, marker, province, state, river, route, zone or regiment),
  as px:X,Y (map pixels) or as ll:LON,LAT.

Reports
  The report is a .tex file for the dndbook class (github.com/rpgtex/DND-5e-LaTeX-Template). Each
  value is tagged: (data) read from the files, (mixed) a stated rule applied to the data. --pdf runs
  pdflatex when it is installed. --json writes the same content as JSON.

Python 3.9 or newer, standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

TOOL_VERSION = "1.1"
LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"  # the Ordnance Survey alphabet: no I
COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
KM_PER_UNIT = {"km": 1.0, "mi": 1.609344, "lg": 4.828032, "vr": 1.0668, "nmi": 1.852, "nlg": 5.556}
OFF_ROAD_SPEED_FACTOR = 0.5  # Azgaar halves a segment's speed when it avoids roads
ROUTE_KIND = {"roads": "road", "trails": "trail", "searoutes": "sea route"}


# ====================================================================== small helpers
def fnum(v, d=1):
    """Number with thousands separators and d decimals, trailing zeros trimmed."""
    if v is None:
        return "n/a"
    if isinstance(v, float) and not math.isfinite(v):
        return "n/a"
    if d == 0 or abs(v) >= 1000:
        return f"{round(v):,}"
    s = f"{v:,.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fpct(v, d=0):
    if v is None:
        return "n/a"
    p = 100 * v
    if 0 < p < 0.5 and d == 0:
        return f"{p:.1f}%" if p >= 0.05 else "<0.1%"
    if 0 < p < 10 ** -d:
        return f"<{10 ** -d:g}%"
    return f"{p:.{d}f}%"


def bearing(dx, dy):
    """Degrees clockwise from north for a map-pixel offset (y grows southward)."""
    return (math.degrees(math.atan2(dx, -dy)) + 360) % 360


def compass(deg, points=8):
    names = COMPASS8 if points == 8 else COMPASS16
    step = 360 / len(names)
    return names[int((deg + step / 2) // step) % len(names)]


def split_camel(s):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s or "").lower()


def clean_note(text):
    """Notes may hold HTML (links, iframes): keep the readable text."""
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\r", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def percentile_rank(value, values):
    """Share of values at or below value (0..1)."""
    if not values:
        return None
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + 0.5 * equal) / len(values)


def mean(vals):
    vals = list(vals)
    return sum(vals) / len(vals) if vals else None


def date_key(path: Path):
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:-(\d{1,2})-(\d{1,2}))?", path.name)
    if m:
        return tuple(int(x or 0) for x in m.groups()), path.stat().st_mtime
    return (0, 0, 0, 0, 0), path.stat().st_mtime


# ====================================================================== geometry
def signed_area(p):
    a = 0.0
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2


def chain_segments(segs):
    """Join segments that share end points into polylines."""
    key = lambda p: (round(p[0], 3), round(p[1], 3))
    adj = defaultdict(list)
    for k, (p, q) in enumerate(segs):
        adj[key(p)].append(k)
        adj[key(q)].append(k)
    used = [False] * len(segs)
    out = []
    for k in range(len(segs)):
        if used[k]:
            continue
        used[k] = True
        line = [segs[k][0], segs[k][1]]
        for forward in (True, False):
            while True:
                end = line[-1] if forward else line[0]
                nxt = next((m for m in adj[key(end)] if not used[m]), None)
                if nxt is None:
                    break
                used[nxt] = True
                p, q = segs[nxt]
                other = q if key(p) == key(end) else p
                if forward:
                    line.append(other)
                else:
                    line.insert(0, other)
        out.append(line)
    return out


def split_ring(ring):
    """Split a closed ring that passes through the same vertex twice into simple loops."""
    key = lambda q: (round(q[0], 6), round(q[1], 6))
    pts = ring[:-1] if len(ring) > 1 and key(ring[0]) == key(ring[-1]) else ring
    out, stack, seen = [], [], {}
    for q in pts:
        k = key(q)
        if k in seen:
            start = seen[k]
            loop = stack[start:]
            for x in loop[1:]:
                seen.pop(key(x), None)
            del stack[start + 1:]
            if len(loop) >= 3:
                out.append(loop)
        else:
            seen[k] = len(stack)
            stack.append(q)
    if len(stack) >= 3:
        out.append(stack)
    return out


def nest_rings(rings):
    """Group simple rings into polygons: a ring inside an odd number of others is a hole of the
    smallest ring that holds it. Returns [(exterior, [holes])]."""
    simple = [r for ring in rings for r in split_ring(ring) if poly_area(r) > 0]
    simple.sort(key=lambda r: -poly_area(r))
    boxes = [bbox_of(r) for r in simple]
    parent = [None] * len(simple)
    depth = [0] * len(simple)
    for k, r in enumerate(simple):
        # a vertex can sit on the parent's edge, so test the centroid of a small triangle inside r
        x, y = poly_centroid(r)
        if not point_in_poly(x, y, r):
            x, y = r[0]
        for m in range(k - 1, -1, -1):
            b = boxes[m]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3] and point_in_poly(x, y, simple[m]):
                parent[k] = m
                depth[k] = depth[m] + 1
                break
    polys = {k: (simple[k], []) for k in range(len(simple)) if depth[k] % 2 == 0}
    for k in range(len(simple)):
        if depth[k] % 2 == 1 and parent[k] in polys:
            polys[parent[k]][1].append(simple[k])
    return list(polys.values())


def poly_area(p):
    return abs(signed_area(p)) if len(p) >= 3 else 0.0


def poly_centroid(p):
    a = cx = cy = 0.0
    n = len(p)
    for i in range(n):
        x0, y0 = p[i]
        x1, y1 = p[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-12:
        return sum(q[0] for q in p) / n, sum(q[1] for q in p) / n
    return cx / (3 * a), cy / (3 * a)


def bbox_of(p):
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_hit(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def point_in_poly(x, y, p):
    inside = False
    n = len(p)
    j = n - 1
    for i in range(n):
        xi, yi = p[i]
        xj, yj = p[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def clip_convex(subject, clip):
    """Sutherland-Hodgman: subject polygon clipped by a convex polygon (any orientation)."""
    if len(subject) < 3:
        return []
    o = 1.0 if signed_area(clip) > 0 else -1.0
    out = list(subject)
    n = len(clip)
    for k in range(n):
        if not out:
            break
        ax, ay = clip[k]
        bx, by = clip[(k + 1) % n]
        ex, ey = bx - ax, by - ay

        def side(q):
            return o * (ex * (q[1] - ay) - ey * (q[0] - ax))

        inp = out
        out = []
        m = len(inp)
        for i in range(m):
            cur = inp[i]
            prev = inp[i - 1]
            sc, sp = side(cur), side(prev)
            if sc >= 0:
                if sp < 0:
                    t = sp / (sp - sc)
                    out.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
                out.append(cur)
            elif sp >= 0:
                t = sp / (sp - sc)
                out.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
    return out


def clip_segment(a, b, clip):
    """Cyrus-Beck: parameter range (t0, t1) of segment a-b inside a convex polygon, or None."""
    o = 1.0 if signed_area(clip) > 0 else -1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    n = len(clip)
    for k in range(n):
        cx, cy = clip[k]
        ex, ey = clip[(k + 1) % n][0] - cx, clip[(k + 1) % n][1] - cy
        num = o * (ex * (a[1] - cy) - ey * (a[0] - cx))
        den = o * (ex * dy - ey * dx)
        if abs(den) < 1e-15:
            if num < 0:
                return None
            continue
        t = -num / den
        if den > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return t0, t1


def polyline_pieces(pts, clip):
    """Pieces of a polyline inside a convex polygon: [(start_dist, end_dist, entry_pt, exit_pt)]."""
    pieces = []
    run = 0.0
    cur = None
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.dist(a, b)
        r = clip_segment(a, b, clip) if seg > 0 else None
        if r and r[1] - r[0] > 1e-9:
            s0, s1 = run + r[0] * seg, run + r[1] * seg
            p0 = (a[0] + r[0] * (b[0] - a[0]), a[1] + r[0] * (b[1] - a[1]))
            p1 = (a[0] + r[1] * (b[0] - a[0]), a[1] + r[1] * (b[1] - a[1]))
            if cur and abs(cur[1] - s0) < 1e-6:
                cur = (cur[0], s1, cur[2], p1)
            else:
                if cur:
                    pieces.append(cur)
                cur = (s0, s1, p0, p1)
        run += seg
    if cur:
        pieces.append(cur)
    return pieces


def polyline_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + t * dx, a[1] + t * dy)
    return math.dist(p, q), q


def polyline_nearest(p, pts):
    best = (float("inf"), None)
    for i in range(len(pts) - 1):
        d, q = point_seg_dist(p, pts[i], pts[i + 1])
        if d < best[0]:
            best = (d, q)
    if len(pts) == 1:
        best = (math.dist(p, pts[0]), pts[0])
    return best


def clip_polygon_rect(ring, x0, y0, x1, y1):
    return clip_convex(ring, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


class Buckets:
    """Uniform bucket index for bounding boxes."""

    def __init__(self, size):
        self.size = size
        self.b = defaultdict(list)

    def add(self, idx, bb):
        s = self.size
        for gx in range(int(bb[0] // s), int(bb[2] // s) + 1):
            for gy in range(int(bb[1] // s), int(bb[3] // s) + 1):
                self.b[(gx, gy)].append(idx)

    def query(self, bb):
        s = self.size
        out = set()
        for gx in range(int(bb[0] // s), int(bb[2] // s) + 1):
            for gy in range(int(bb[1] // s), int(bb[3] // s) + 1):
                out.update(self.b.get((gx, gy), ()))
        return out


_PATH_TOKEN = re.compile(r"[MmLlHhVvQqCcSsTtZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def flatten_path(d, steps=4):
    """Flatten SVG path data (M L H V Q C S T Z, absolute or relative) into point lists."""
    toks = _PATH_TOKEN.findall(d or "")
    rings, ring = [], []
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    lcx = lcy = None

    def nums(k):
        nonlocal i
        v = [float(t) for t in toks[i:i + k]]
        i += k
        return v

    while i < len(toks):
        t = toks[i]
        if t[0].isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if ring:
                    rings.append(ring)
                ring, x, y = [], sx, sy
                continue
            continue
        if cmd is None:
            i += 1
            continue
        rel = cmd.islower()
        c = cmd.upper()
        try:
            if c == "M":
                px, py = nums(2)
                if rel:
                    px, py = px + x, py + y
                if ring:
                    rings.append(ring)
                ring = [(px, py)]
                x, y, sx, sy = px, py, px, py
                cmd = "l" if rel else "L"
            elif c == "L":
                px, py = nums(2)
                if rel:
                    px, py = px + x, py + y
                ring.append((px, py))
                x, y = px, py
            elif c == "H":
                (px,) = nums(1)
                x = px + x if rel else px
                ring.append((x, y))
            elif c == "V":
                (py,) = nums(1)
                y = py + y if rel else py
                ring.append((x, y))
            elif c in "QT":
                if c == "Q":
                    qx, qy, px, py = nums(4)
                    if rel:
                        qx, qy, px, py = qx + x, qy + y, px + x, py + y
                else:
                    px, py = nums(2)
                    if rel:
                        px, py = px + x, py + y
                    qx, qy = (2 * x - lcx, 2 * y - lcy) if lcx is not None else (x, y)
                for s in range(1, steps + 1):
                    u = s / steps
                    ring.append(((1 - u) ** 2 * x + 2 * (1 - u) * u * qx + u * u * px,
                                 (1 - u) ** 2 * y + 2 * (1 - u) * u * qy + u * u * py))
                lcx, lcy = qx, qy
                x, y = px, py
                continue
            elif c in "CS":
                if c == "C":
                    c1x, c1y, c2x, c2y, px, py = nums(6)
                    if rel:
                        c1x, c1y, c2x, c2y, px, py = c1x + x, c1y + y, c2x + x, c2y + y, px + x, py + y
                else:
                    c2x, c2y, px, py = nums(4)
                    if rel:
                        c2x, c2y, px, py = c2x + x, c2y + y, px + x, py + y
                    c1x, c1y = (2 * x - lcx, 2 * y - lcy) if lcx is not None else (x, y)
                for s in range(1, steps + 1):
                    u = s / steps
                    m = 1 - u
                    ring.append((m ** 3 * x + 3 * m * m * u * c1x + 3 * m * u * u * c2x + u ** 3 * px,
                                 m ** 3 * y + 3 * m * m * u * c1y + 3 * m * u * u * c2y + u ** 3 * py))
                lcx, lcy = c2x, c2y
                x, y = px, py
                continue
            else:
                i += 1
        except ValueError:
            i += 1
        lcx = lcy = None
    if ring:
        rings.append(ring)
    return rings


def path_endpoints(d):
    """End points of each path command (curves reduced to their end points)."""
    pts = []
    for r in flatten_path(d, steps=1):
        pts.extend(r)
    return pts


# ====================================================================== the .map file
class MapError(Exception):
    pass


def split_fields(raw):
    """Fields are joined by CRLF. A file whose line endings were normalised to LF (e.g. by git)
    has LF only, and the SVG's own newlines then look like separators: rejoin the SVG block."""
    if "\r\n" in raw:
        return raw.split("\r\n")
    lines = raw.split("\n")
    try:
        s = next(i for i, l in enumerate(lines) if l.startswith("<svg"))
        e = next(i for i, l in enumerate(lines) if i >= s and l.rstrip().endswith("</svg>"))
    except StopIteration:
        return lines
    return lines[:s] + ["\n".join(lines[s:e + 1])] + lines[e + 1:]


def fix_surrogates(v):
    """JSON in some saves holds broken emoji (lone UTF-16 surrogates); rejoin pairs, replace the rest."""
    if isinstance(v, str):
        try:
            v.encode("utf-8")
            return v
        except UnicodeEncodeError:
            return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(v, list):
        return [fix_surrogates(x) for x in v]
    if isinstance(v, dict):
        return {fix_surrogates(k): fix_surrogates(x) for k, x in v.items()}
    return v


def _rec(value):
    if isinstance(value, list):
        return next((x for x in value if isinstance(x, dict)), None)
    return value if isinstance(value, dict) else None


def _has(*keys):
    def check(v):
        r = _rec(v)
        return r is not None and all(k in r for k in keys)
    return check


# field index in Azgaar's save routine (src/services/io/save.ts, formats 1.152 to 1.154), kind,
# content signature. Every JSON field is checked against its signature; a field that fails is
# looked for elsewhere in the file by content.
LAYOUT = {
    "settings": (1, "json", _has("seed", "units")), "biomes": (3, "json", _has("habitability")),
    "grid": (6, "json", _has("spacing", "points")), "grid_h": (7, "ints", None), "grid_prec": (8, "ints", None),
    "grid_f": (9, "ints", None), "grid_t": (10, "ints", None), "grid_temp": (11, "ints", None),
    "features": (12, "json", _has("land", "cells")), "cultures": (13, "json", _has("base")),
    "states": (14, "json", _has("diplomacy")), "burgs": (15, "json", _has("population", "cell")),
    "biome": (16, "ints", None), "burg": (17, "ints", None), "conf": (18, "ints", None),
    "culture": (19, "ints", None), "fl": (20, "ints", None), "pop": (21, "floats", None),
    "r": (22, "ints", None), "s": (24, "ints", None), "state": (25, "ints", None),
    "religion": (26, "ints", None), "province": (27, "ints", None),
    "religions": (29, "json", lambda v: isinstance(v, list) and bool(v) and isinstance(v[0], dict)
                  and v[0].get("name") == "No religion"),
    "provinces": (30, "json", _has("formName", "center")), "namesdata": (31, "text", None),
    "rivers": (32, "json", _has("source", "mouth")), "markers": (35, "json", _has("icon", "cell")),
    "routes": (37, "json", _has("group", "points")), "zones": (38, "json", _has("cells", "type")),
    "ice": (39, "json", None), "good": (40, "ints", None), "goods": (41, "json", _has("tags")),
    "markets": (42, "json", _has("centerBurgId")), "deals": (43, "json", _has("seller", "buyer", "good")),
    "market": (44, "ints", None), "styles": (48, "json", _has("grid")), "journeys": (52, "json", _has("segments")),
}


def resolve_world(arg, roots, map_name=None):
    """A .map path, a folder holding .map files, or a world name under the roots."""
    p = Path(arg)
    if p.is_file():
        return p
    folders = []
    if p.is_dir():
        folders.append(p)
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for sub in [root] + [d for d in root.iterdir() if d.is_dir()]:
            if sub.name.casefold() == arg.casefold():
                folders.append(sub)
    cands = []
    for f in folders:
        cands += list(f.glob("*.map"))
    if not cands:  # files named after the world anywhere under the roots
        for root in roots:
            root = Path(root)
            if root.is_dir():
                cands += [m for m in root.rglob("*.map") if m.name.casefold().startswith(arg.casefold())]
    if map_name:
        named = [c for c in cands if c.name == map_name or str(c) == map_name]
        if not named and Path(map_name).is_file():
            return Path(map_name)
        if not named:
            raise MapError(f"no map named '{map_name}' for '{arg}'")
        return named[0]
    if not cands:
        raise MapError(f"no .map file found for '{arg}' (looked in: {', '.join(map(str, roots))})")
    return max(cands, key=date_key)


_GLYPH = re.compile(r"(?:glyph|emoji)[-_]((?:[0-9a-f]{2,6})(?:[-_][0-9a-f]{2,6})*)", re.I)


def icon_text(icon):
    """A marker's or regiment's icon as text. Azgaar 1.154 and newer store the emoji as its code points
    ('glyph-1f333', 'glyph-1f3f4-200d-2620-fe0f'); older maps store the emoji itself. Image icons (a URL
    or data URI) are kept as they are."""
    if not isinstance(icon, str):
        return icon
    s = icon.strip()
    m = _GLYPH.fullmatch(s)
    if m:
        try:
            return "".join(chr(int(h, 16)) for h in re.split(r"[-_]", m.group(1)))
        except (ValueError, OverflowError):
            return s
    return s


def icon_is_image(icon):
    return isinstance(icon, str) and icon.startswith(("http://", "https://", "data:", "./", "/"))


class World:
    def __init__(self, map_path, cells_path=None, quiet=False):
        self.map_path = Path(map_path)
        self.folder = self.map_path.parent
        self.notes = []          # loading notes shown by 'info' and in report appendices
        with open(self.map_path, encoding="utf-8", errors="replace", newline="") as fh:
            raw = fh.read()
        self.fields = split_fields(raw)
        if len(self.fields) < 53:
            raise MapError(f"{self.map_path.name}: {len(self.fields)} fields, expected 53 "
                           "(re-save the map in Azgaar 1.153 or newer)")
        self.params = self.fields[0].split("|")
        self.version = self.params[0]
        d = {}
        for key, (idx, kind, check) in LAYOUT.items():
            d[key] = self._parse(key, idx, kind, check)
        if not isinstance(d["settings"], dict):
            raise MapError(f"{self.map_path.name}: settings are not JSON (format {self.version}); "
                           "re-save the map in Azgaar 1.153 or newer")
        self.d = d
        self.svg = self.fields[5] if len(self.fields) > 5 else ""
        self._settings()
        self._pack_checks()
        self.cells_path = Path(cells_path) if cells_path else self._find_cells_file()
        if not self.cells_path:
            raise MapError(f"no Cells GeoJSON matching {self.map_path.name} in {self.folder}. "
                           "Export it in Azgaar (Menu > Export > GeoJSON > Cells) and put it next to the .map")
        self._load_cells(self.cells_path, strict=False)
        self._derive()

    # ------------------------------------------------------------------ parsing
    def _parse(self, key, idx, kind, check):
        txt = self.fields[idx] if idx < len(self.fields) else ""
        if kind == "text":
            return txt
        if kind in ("ints", "floats"):
            if not txt:
                return []
            conv = float if kind == "floats" else int
            try:
                return [conv(x) if x != "" else 0 for x in txt.split(",")]
            except ValueError:
                return [conv(float(x)) if x not in ("", "NaN") else 0 for x in txt.split(",")]
        empty = {} if key == "styles" else []
        if not txt:
            return empty
        try:
            val = json.loads(txt)
            if "\\ud" in txt or "\\uD" in txt:
                val = fix_surrogates(val)
        except json.JSONDecodeError:
            val = None
        if val is not None and (check is None or check(val) or val in ([], {})):
            return val
        for k, t in enumerate(self.fields):  # identify the dataset by content
            if k == 5 or not t or t[0] not in "[{":
                continue
            try:
                v = json.loads(t)
            except json.JSONDecodeError:
                continue
            if check and check(v):
                self.notes.append(f"'{key}' found in field {k}, not {idx}")
                return fix_surrogates(v)
        self.notes.append(f"'{key}' not found; treated as empty")
        return empty

    def _settings(self):
        s = self.d["settings"]
        self.settings = s
        g = s.get("graph", {})
        self.W = float(g.get("width") or self.params[4])
        self.H = float(g.get("height") or self.params[5])
        u = s.get("units", {})
        self.scale = float(u.get("distance", {}).get("scale", 1))
        self.unit = u.get("distance", {}).get("unit", "km")
        self.area_unit = u.get("area", {}).get("unit", "square")
        self.h_unit = u.get("height", {}).get("unit", "m")
        self.h_exp = float(u.get("height", {}).get("exponent", 2))
        self.t_unit = u.get("temperature", {}).get("unit", "°C")
        pop = u.get("population", {})
        self.pop_scale = float(pop.get("scale", 1000))
        self.urb_rate = float((pop.get("urbanization") or {}).get("rate", 1))
        co = s.get("geography", {}).get("coordinates") or {}
        self.lonW, self.lonT = float(co.get("lonW", -180)), float(co.get("lonT", 360))
        self.latN, self.latT = float(co.get("latN", 90)), float(co.get("latT", 180))
        lore = s.get("lore", {})
        self.name = lore.get("name") or self.map_path.stem.split(" ")[0]
        cal = lore.get("calendar", {})
        self.year = cal.get("year")
        self.era = cal.get("era", "")
        self.era_short = cal.get("eraShort", "")
        self.winds = (s.get("climate") or {}).get("winds") or []
        self.transports = {t.get("name"): t for t in s.get("transports", []) if isinstance(t, dict)}
        self.km_per_unit = KM_PER_UNIT.get(self.unit, 1.0)

    def _pack_checks(self):
        d = self.d
        self.n = len(d["biome"])
        for key in ("burg", "culture", "pop", "state", "religion", "province", "r", "fl", "conf", "s", "good", "market"):
            if not d[key]:
                d[key] = [0] * self.n
            elif len(d[key]) != self.n:
                raise MapError(f"pack array '{key}' has {len(d[key])} values, expected {self.n}")
        self.burgs = d["burgs"]
        self.states = d["states"]
        bad = [b["i"] for b in self.live(self.burgs) if b.get("i") and d["burg"][b["cell"]] != b["i"]]
        if bad:
            raise MapError(f"burg array does not match burg cells (burgs {bad[:5]})")
        bad = [b["i"] for b in self.live(self.burgs) if b.get("i") and d["state"][b["cell"]] != b.get("state", 0)]
        if bad:
            self.notes.append(f"{len(bad)} burgs lie outside their state's cells")

    @staticmethod
    def live(items):
        return [x for x in items if isinstance(x, dict) and not x.get("removed")]

    # ------------------------------------------------------------------ cells GeoJSON
    def _find_cells_file(self):
        cands = sorted(self.folder.glob("*.geojson"), key=lambda p: ("cells" in p.name.casefold(), date_key(p)),
                       reverse=True)
        for p in cands:
            try:
                if self._load_cells(p, strict=True):
                    return p
            except (MapError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return None

    def to_px(self, lon, lat):
        return (lon - self.lonW) / self.lonT * self.W, (self.latN - lat) / self.latT * self.H

    def to_lonlat(self, x, y):
        return self.lonW + x / self.W * self.lonT, self.latN - y / self.H * self.latT

    def _load_cells(self, path, strict):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        feats = doc.get("features", [])
        if not feats or "neighbors" not in (feats[0].get("properties") or {}):
            raise MapError("not an Azgaar cells export")
        if len(feats) != self.n:
            raise MapError(f"{Path(path).name} has {len(feats)} cells, the map has {self.n}")
        poly, keys, props = [None] * self.n, [None] * self.n, [None] * self.n
        for ft in feats:
            p = ft["properties"]
            i = int(p["id"])
            geom = ft["geometry"]
            rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else \
                [max((pg[0] for pg in geom["coordinates"]), key=len)]
            ring = rings[0]
            keys[i] = [(c[0], c[1]) for c in ring]
            pts = [self.to_px(c[0], c[1]) for c in ring]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            poly[i] = pts
            props[i] = p
        live = [b for b in self.live(self.burgs) if b.get("i")]
        inside = sum(1 for b in live if poly[b["cell"]] and point_in_poly(b["x"], b["y"], poly[b["cell"]]))
        if live and inside < 0.85 * len(live):
            raise MapError(f"{Path(path).name}: only {inside} of {len(live)} burgs lie in their cells")
        if strict:
            return True
        self.cell_poly, self.cell_keys, self.cell_props = poly, keys, props
        diffs = []
        for key in ("state", "province", "culture", "religion", "biome"):
            arr = self.d[key]
            bad = sum(1 for i in range(self.n) if props[i].get(key) is not None and props[i].get(key) != arr[i])
            if bad:
                diffs.append(f"{bad} on {key}")
        if diffs:
            self.notes.append(f"{Path(path).name} differs from the .map in cell attributes ({', '.join(diffs)}); "
                              "outlines are taken from the export, attributes from the .map")
        return True

    # ------------------------------------------------------------------ derived tables
    def _derive(self):
        d = self.d
        n = self.n
        self.water = [(self.cell_props[i].get("type") in ("ocean", "lake")) for i in range(n)]
        self.cell_type = [self.cell_props[i].get("type") for i in range(n)]
        self.cell_height_disp = [self.cell_props[i].get("height") for i in range(n)]
        self.nbrs = [list(self.cell_props[i].get("neighbors") or []) for i in range(n)]
        self.cell_area = [poly_area(p) for p in self.cell_poly]
        self.cell_centroid = [poly_centroid(p) for p in self.cell_poly]
        self.cell_bbox = [bbox_of(p) for p in self.cell_poly]
        mean_size = math.sqrt(sum(self.cell_area) / max(n, 1))
        self.cell_index = Buckets(max(mean_size * 1.5, 1.0))
        for i in range(n):
            self.cell_index.add(i, self.cell_bbox[i])

        # cell sites: route points carry [x, y, cell] at the cell's generator point
        counts = defaultdict(Counter)
        for r in self.live(d["routes"]):
            for p in r.get("points", []):
                if len(p) > 2 and p[2] is not None and 0 <= p[2] < n:
                    counts[p[2]][(p[0], p[1])] += 1
        self.site = list(self.cell_centroid)
        self.site_known = [False] * n
        for c, cnt in counts.items():
            self.site[c] = cnt.most_common(1)[0][0]
            self.site_known[c] = True
        for b in self.live(self.burgs):
            if b.get("i") and not self.site_known[b["cell"]]:
                self.site[b["cell"]] = (b["x"], b["y"])

        # shared cell edges, from identical vertices in the export
        edge_cells = defaultdict(list)
        for c in range(n):
            ks = self.cell_keys[c]
            for k in range(len(ks) - 1):
                a, b = ks[k], ks[k + 1]
                if a != b:
                    edge_cells[(a, b) if a < b else (b, a)].append(c)
        self.edges = []
        self.outer_edges = []   # cell edges on the map's outer boundary (shared with no other cell)
        for (a, b), cs in edge_cells.items():
            if len(cs) == 2 and cs[0] != cs[1]:
                self.edges.append((cs[0], cs[1], self.to_px(*a), self.to_px(*b)))
            elif len(cs) == 1:
                self.outer_edges.append((cs[0], self.to_px(*a), self.to_px(*b)))
        self.edge_index = Buckets(max(mean_size * 1.5, 1.0))
        for k, (_, _, p, q) in enumerate(self.edges):
            self.edge_index.add(k, (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])))

        # feature (ocean, lake, landmass) of each cell, by flood fill from each feature's first cell
        self.features = d["features"]
        self.cell_feature = [0] * n
        for f in self.live(self.features):
            start = f.get("firstCell")
            if start is None or not (0 <= start < n) or self.cell_feature[start]:
                continue
            kind = self.cell_type[start]
            stack = [start]
            self.cell_feature[start] = f["i"]
            while stack:
                c = stack.pop()
                for m in self.nbrs[c]:
                    if 0 <= m < n and not self.cell_feature[m] and self.cell_type[m] == kind:
                        self.cell_feature[m] = f["i"]
                        stack.append(m)

        # grid (the climate and height grid of ~10,000 points)
        g = d["grid"]
        self.grid_points = g.get("points", [])
        self.grid_spacing = float(g.get("spacing", 10))
        self.cellsX, self.cellsY = int(g.get("cellsX", 1)), int(g.get("cellsY", 1))
        self._grid_pack = None

        # names
        self.namebases = {}
        for k, chunk in enumerate((d["namesdata"] or "").split("/")):
            parts = chunk.split("|")
            if parts and parts[0]:
                self.namebases[k] = parts[0]

        # lookups
        self.cultures = d["cultures"]
        self.religions = d["religions"]
        self.provinces = d["provinces"]
        self.biomes = d["biomes"]
        self.goods = {g["i"]: g for g in self.live(d["goods"])}
        self.markets = {m["i"]: m for m in self.live(d["markets"])}
        self.zones = self.live(d["zones"])
        self.zone_cells = {z["i"]: set(z.get("cells", [])) for z in self.zones}
        self.cell_zones = defaultdict(list)
        for z in self.zones:
            for c in z.get("cells", []):
                self.cell_zones[c].append(z["i"])
        self.markers = [dict(m, icon=icon_text(m.get("icon"))) for m in self.live(d["markers"])]
        self.routes = [r for r in d["routes"] if isinstance(r, dict) and r.get("points")]
        self.rivers = {r["i"]: r for r in self.live(d["rivers"])}
        self.journeys = [j for j in d["journeys"] if isinstance(j, dict)]
        self.deals = d["deals"] if isinstance(d["deals"], list) else []
        self.units = []
        for s in self.live(self.states):
            for u in s.get("military") or []:
                if isinstance(u, dict):
                    self.units.append(dict(u, state=s["i"], icon=icon_text(u.get("icon"))))
        self._feature_rings = None
        self._river_courses = None
        self._production = None

    # ------------------------------------------------------------------ accessors
    def burg(self, i):
        b = self.burgs[i] if 0 < i < len(self.burgs) else None
        return b if isinstance(b, dict) and not b.get("removed") else None

    def state(self, i):
        s = self.states[i] if 0 <= i < len(self.states) else None
        return s if isinstance(s, dict) else None

    def state_name(self, i):
        s = self.state(i)
        return (s.get("name") if s else None) or ("Neutral lands" if i == 0 else f"state {i}")

    def culture(self, i):
        c = self.cultures[i] if 0 <= i < len(self.cultures) else None
        return c if isinstance(c, dict) else {}

    def religion(self, i):
        r = self.religions[i] if 0 <= i < len(self.religions) else None
        return r if isinstance(r, dict) else {}

    def province(self, i):
        p = self.provinces[i] if 0 < i < len(self.provinces) else None
        return p if isinstance(p, dict) and not p.get("removed") else None

    def biome_name(self, i):
        b = self.biomes[i] if 0 <= i < len(self.biomes) else None
        return b.get("name", f"biome {i}") if isinstance(b, dict) else f"biome {i}"

    def feature(self, i):
        f = self.features[i] if 0 < i < len(self.features) else None
        return f if isinstance(f, dict) else None

    def feature_label(self, i):
        f = self.feature(i)
        if not f:
            return "unknown"
        kind = f.get("subtype") or f.get("type")
        name = f.get("name")
        return f"{name} ({split_camel(kind)})" if name else split_camel(kind)

    def miles(self, px):
        return px * self.scale

    def sq(self, px2):
        return px2 * self.scale ** 2

    def area_label(self):
        return f"{self.unit}²" if self.area_unit == "square" else self.area_unit

    def people(self, rural=0.0, urban=0.0):
        return rural * self.pop_scale + urban * self.pop_scale * self.urb_rate

    def burg_people(self, b):
        return (b.get("population") or 0) * self.pop_scale * self.urb_rate

    def height_m(self, h):
        """Azgaar's getHeight in metres: (h - 18) ** exponent on land, a shallow ramp at sea."""
        if h >= 20:
            return (h - 18) ** self.h_exp
        if h >= 1:
            return (h - 20) / h * 50
        return -990.0

    def height_disp(self, metres):
        ratio = {"m": 1.0, "f": 0.5468}.get(self.h_unit, 3.281)
        return metres * ratio

    def temp_disp(self, c):
        u = self.t_unit
        conv = {"°C": lambda t: t, "°F": lambda t: t * 9 / 5 + 32, "K": lambda t: t + 273.15,
                "°R": lambda t: (t + 273.15) * 9 / 5, "°De": lambda t: (100 - t) * 3 / 2,
                "°N": lambda t: t * 33 / 100, "°Ré": lambda t: t * 4 / 5, "°Rø": lambda t: t * 21 / 40 + 7.5}
        return conv.get(u, conv["°C"])(c)

    def temp_text(self, c):
        if c is None:
            return "n/a"
        if self.t_unit == "°C":
            return f"{c:.0f}°C"
        return f"{self.temp_disp(c):.0f}{self.t_unit} ({c:.0f}°C)"

    def grid_index(self, x, y):
        """Azgaar's Grid.findCell: the lattice square under the point, not the nearest point."""
        sp = self.grid_spacing
        gy = int(math.floor(min(max(y, 0) / sp, self.cellsY - 1)))
        gx = int(math.floor(min(max(x, 0) / sp, self.cellsX - 1)))
        return gy * self.cellsX + gx

    def grid_value(self, key, g):
        arr = self.d[key]
        return arr[g] if 0 <= g < len(arr) else None

    def cell_at(self, x, y, among=None):
        cands = among if among is not None else self.cell_index.query((x, y, x, y))
        best, bd = None, float("inf")
        for c in cands:
            bb = self.cell_bbox[c]
            if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and point_in_poly(x, y, self.cell_poly[c]):
                return c
            dd = math.dist((x, y), self.cell_centroid[c])
            if dd < bd:
                best, bd = c, dd
        if best is None:
            best = min(range(self.n), key=lambda c: math.dist((x, y), self.cell_centroid[c]))
        return best

    @property
    def grid_pack(self):
        """Pack cell under each grid point (used to compare a tile with its province and state)."""
        if self._grid_pack is None:
            self._grid_pack = [self.cell_at(p[0], p[1]) if 0 <= p[0] <= self.W and 0 <= p[1] <= self.H else -1
                               for p in self.grid_points]
        return self._grid_pack

    # ------------------------------------------------------------------ outlines from the SVG
    @property
    def feature_rings(self):
        """Azgaar's smoothed coast and lake outlines (<defs><g id="featurePaths">), flattened."""
        if self._feature_rings is None:
            out = {}
            start = self.svg.find('id="featurePaths"')
            if start >= 0:
                end = self.svg.find("</g>", start)
                for m in re.finditer(r"<path\b([^>]*)>", self.svg[start:end]):
                    attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))
                    fid = attrs.get("id", "")
                    if fid.startswith("feature_") and attrs.get("d"):
                        try:
                            rings = [r for r in flatten_path(attrs["d"], steps=3) if len(r) >= 3]
                            out[int(fid[8:])] = [(r, bbox_of(r)) for r in rings]
                        except ValueError:
                            continue
            self._feature_rings = out
        return self._feature_rings

    def drawn_kind(self, x, y):
        """'land' or 'water' at a point by Azgaar's drawn outlines (crossing count on a banded edge index)."""
        if not hasattr(self, "_ring_bands"):
            self._ring_bands = None
            rings = self.feature_rings
            if rings:
                self._band_h = max(self.H / 1500, 1e-6)
                bands = defaultdict(list)
                for fid, rs in rings.items():
                    f = self.feature(fid) or {}
                    kind = "lake" if f.get("type") == "lake" else ("isle" if f.get("subtype") == "lake_island" else
                                                                  "land" if f.get("land") else "water")
                    for k, (r, _) in enumerate(rs):
                        key = (fid, k, kind)
                        n = len(r)
                        for a in range(n):
                            x0, y0 = r[a]
                            x1, y1 = r[(a + 1) % n]
                            if y0 == y1:
                                continue
                            for band in range(int(min(y0, y1) // self._band_h), int(max(y0, y1) // self._band_h) + 1):
                                bands[band].append((x0, y0, x1, y1, key))
                self._ring_bands = bands
        if not self._ring_bands:
            return None
        hits = Counter()
        for x0, y0, x1, y1, key in self._ring_bands.get(int(y // self._band_h), ()):
            if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
                hits[key] += 1
        inside = {key[2] for key, c in hits.items() if c % 2}
        if "isle" in inside:
            return "land"
        return "land" if "land" in inside and "lake" not in inside else "water"

    @property
    def river_courses(self):
        """River lines: the drawn course where the SVG keeps the river's outline (the centre of its
        two banks), otherwise a line through the river's cells (sites where known)."""
        if self._river_courses is None:
            drawn = {}
            start = self.svg.find('id="rivers"')
            if start >= 0:
                end = self.svg.find("</g>", start)
                for m in re.finditer(r'<path\b[^>]*id="river(\d+)"[^>]*\bd="([^"]+)"', self.svg[start:end]):
                    pts = path_endpoints(m.group(2))
                    k = len(pts)
                    if k >= 5:
                        half = k // 2
                        centre = [((pts[i][0] + pts[k - 1 - i][0]) / 2, (pts[i][1] + pts[k - 1 - i][1]) / 2)
                                  for i in range(half)] + [pts[half]]
                        widths = [math.dist(pts[i], pts[k - 1 - i]) for i in range(half)] + [0.0]
                        drawn[int(m.group(1))] = (centre, widths)
            out = {}
            for i, r in self.rivers.items():
                if i in drawn:
                    out[i] = {"points": drawn[i][0], "widths": drawn[i][1], "source": "drawn course"}
                else:
                    cells = [c for c in r.get("cells", []) if 0 <= c < self.n]
                    out[i] = {"points": [self.site[c] for c in cells], "widths": None, "source": "cell line"}
            self._river_courses = out
        return self._river_courses

    def grid_overlay(self):
        """Grid overlay options from the saved style (or the SVG's gridOverlay attributes)."""
        st = self.d.get("styles") or {}
        opts = (st.get("grid") or {}).get("options") if isinstance(st, dict) else None
        if not opts:
            m = re.search(r'<g\b[^>]*id="gridOverlay"[^>]*>', self.svg)
            if m:
                attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(0)))
                opts = {k: attrs.get(k) for k in ("type", "scale", "dx", "dy") if attrs.get(k) is not None}
        return opts or {}


# ====================================================================== production and trade
class Economy:
    """Rural output per cell (Azgaar's getCellProduction), urban output per burg (its production
    records), totals by state, province, market region and world, and the deals between them."""

    BONUS_RURAL = 0.25
    MAX_BONUS = 5

    def __init__(self, w: World):
        self.w = w
        d = w.d
        by_biome = defaultdict(list)
        for g in w.goods.values():
            for b, rate in (g.get("biomeOutput") or {}).items():
                if rate:
                    by_biome[int(b)].append((g["i"], rate))
        self.rural = [{} for _ in range(w.n)]
        for c in range(w.n):
            pop = sum(d["pop"][m] for m in w.nbrs[c] if 0 <= m < w.n) if w.water[c] else d["pop"][c]
            if pop <= 0:
                continue
            out = self.rural[c]
            for gid, rate in by_biome.get(d["biome"][c], ()):
                v = round(pop * rate * self.modifier(gid, c), 2)
                if v:
                    out[gid] = round(out.get(gid, 0) + v, 2)
            bonus = d["good"][c]
            if bonus and bonus in w.goods:
                v = round(min(pop * self.BONUS_RURAL, self.MAX_BONUS) * self.modifier(bonus, c), 2)
                if v:
                    out[bonus] = round(out.get(bonus, 0) + v, 2)
        self.urban = {}
        self.recipes = {}
        for b in w.live(w.burgs):
            if not b.get("i"):
                continue
            made = defaultdict(float)
            rec = defaultdict(lambda: defaultdict(float))
            for r in b.get("production") or []:
                if "goodId" in r:
                    made[r["goodId"]] += r.get("units", 0)
                    for x in r.get("recipe") or []:
                        rec[r["goodId"]][x["goodId"]] += x.get("units", 0)
            self.urban[b["i"]] = dict(made)
            self.recipes[b["i"]] = {k: dict(v) for k, v in rec.items()}
        self.world = defaultdict(float)
        self.by_state = defaultdict(lambda: defaultdict(float))
        self.by_province = defaultdict(lambda: defaultdict(float))
        self.by_market = defaultdict(lambda: defaultdict(float))
        self.rural_world = defaultdict(float)
        for c in range(w.n):
            for gid, v in self.rural[c].items():
                self.world[gid] += v
                self.rural_world[gid] += v
                self.by_state[d["state"][c]][gid] += v
                self.by_province[d["province"][c]][gid] += v
                if d["market"][c]:
                    self.by_market[d["market"][c]][gid] += v
        for bid, made in self.urban.items():
            b = w.burg(bid)
            for gid, v in made.items():
                self.world[gid] += v
                self.by_state[b.get("state", 0)][gid] += v
                self.by_province[d["province"][b["cell"]]][gid] += v
                if b.get("market"):
                    self.by_market[b["market"]][gid] += v
        self.buys = defaultdict(list)    # burg -> deals where it buys
        self.sells = defaultdict(list)   # burg -> deals where it sells
        self.flows = defaultdict(list)   # market -> market-to-market deals it is part of
        for dl in w.deals:
            if dl.get("buyerType") == "burg":
                self.buys[dl["buyer"]].append(dl)
            if dl.get("sellerType") == "burg":
                self.sells[dl["seller"]].append(dl)
            if dl.get("sellerType") == "market" and dl.get("buyerType") == "market":
                self.flows[dl["seller"]].append(dl)
                self.flows[dl["buyer"]].append(dl)
        prices = defaultdict(list)
        for m in w.markets.values():
            for gid, rec in (m.get("goods") or {}).items():
                if rec.get("price") is not None:
                    prices[int(gid)].append(rec["price"])
        self.mean_price = {g: mean(v) for g, v in prices.items()}

    def modifier(self, gid, c):
        w, d = self.w, self.w.d
        g = w.goods.get(gid) or {}
        mult = g.get("multipliers")
        if not mult:
            return 1.0
        b = d["burg"][c]
        burg = w.burg(b) if b else None
        ctype = (burg.get("type") if burg else w.culture(d["culture"][c]).get("type")) or "Generic"
        v = ((mult.get("cultureType") or {}).get(ctype, 1) * (mult.get("culture") or {}).get(str(d["culture"][c]), 1)
             * (mult.get("state") or {}).get(str(d["state"][c]), 1)
             * (mult.get("religion") or {}).get(str(d["religion"][c]), 1)
             * (mult.get("biome") or {}).get(str(d["biome"][c]), 1))
        for zid, val in (mult.get("zone") or {}).items():
            if val not in (None, 1) and c in w.zone_cells.get(int(zid), ()):
                v *= val
        return v

    def good_name(self, gid):
        g = self.w.goods.get(gid)
        return g.get("name", f"good {gid}") if g else f"good {gid}"


# ====================================================================== journeys
FALLBACK_HOURS = {"land": 8, "water": 12, "air": 8, "stay": 24}


def elapsed_hours(hours, per_day):
    """Azgaar's getElapsedHours: each full travel day costs 24 h, the hours left over only themselves."""
    if hours <= 0:
        return 0.0
    rate = per_day if per_day and per_day > 0 else 24
    days = math.floor(hours / rate)
    return days * 24 + (hours - days * rate)


class JourneyPlan:
    def __init__(self, w: World, j, legacy_speeds=False):
        self.w = w
        self.j = j
        self.name = j.get("name", "journey")
        self.type = j.get("type", "")
        self.segments = []
        clock = 0.0
        for k, s in enumerate(j.get("segments", [])):
            t = w.transports.get(s.get("transport"), {})
            domain = t.get("domain") or ("stay" if (s.get("transport") or "").lower() == "stay" else "land")
            hpd = t.get("hoursPerDay") or FALLBACK_HOURS.get(domain, 8)
            pts = [(p[0], p[1], p[2] if len(p) > 2 else None) for p in s.get("points", [])]
            xy = [(p[0], p[1]) for p in pts]
            dist_px = s.get("distance") if s.get("distance") is not None else polyline_length(xy)
            stay = domain == "stay"
            miles = 0.0 if stay else dist_px * w.scale
            speed_kmh = s.get("speed") if s.get("speed") is not None else t.get("speed", 0)
            eff = (speed_kmh or 0) * (OFF_ROAD_SPEED_FACTOR if s.get("avoidRoads") else 1)
            speed_units = eff if legacy_speeds else eff / w.km_per_unit
            if s.get("duration") is not None:
                hours = float(s["duration"])
            else:
                hours = miles / speed_units if speed_units > 0 else 0.0
            el = hours if stay else elapsed_hours(hours, hpd)
            visible = s.get("visible", True) is not False
            seg = {"i": s.get("i", k), "name": s.get("name", f"segment {k}"), "transport": s.get("transport"),
                   "domain": domain, "hpd": 24 if stay else hpd, "points": pts, "xy": xy, "dist_px": dist_px,
                   "line_px": polyline_length(xy), "miles": miles, "speed_kmh": speed_kmh, "speed_units": speed_units,
                   "avoid_roads": bool(s.get("avoidRoads")), "hours": hours, "elapsed": el, "start": clock,
                   "stay": stay, "visible": visible, "from": s.get("from"), "to": s.get("to"),
                   "duration_set": s.get("duration") is not None}
            self.segments.append(seg)
            if visible:
                clock += el
        self.total_elapsed = clock

    def clock_at(self, seg, along_px):
        """Journey clock (elapsed hours since departure) at a distance along a moving segment."""
        if seg["stay"]:
            return seg["start"]
        frac = along_px / seg["line_px"] if seg["line_px"] else 0
        hours = seg["hours"] * frac
        return seg["start"] + elapsed_hours(hours, seg["hpd"])

    @staticmethod
    def clock_text(t):
        day = int(t // 24) + 1
        return f"day {day}, +{t - 24 * (day - 1):.1f} h"


# ====================================================================== the tile grid
PATTERNS = {
    # pattern-space centre of tile (i, j) and vertex offsets, from Azgaar's src/index.html patterns
    "pointyHex": {"step": (25.0, 21.7), "verts": [(0, -14.45), (12.5, -7.25), (12.5, 7.25), (0, 14.45),
                                                  (-12.5, 7.25), (-12.5, -7.25)], "width": 25.0},
    "flatHex": {"step": (21.7, 25.0), "verts": [(-14.45, 0), (-7.25, -12.5), (7.25, -12.5), (14.45, 0),
                                                (7.25, 12.5), (-7.25, 12.5)], "width": 25.0},
    "square": {"step": (25.0, 25.0), "verts": [(-12.5, -12.5), (12.5, -12.5), (12.5, 12.5), (-12.5, 12.5)],
               "width": 25.0},
    "square45deg": {"step": (35.355, 17.6775), "verts": [(0, -17.6775), (17.6775, 0), (0, 17.6775), (-17.6775, 0)],
                    "width": 25.0},
}
STAND_INS = {"squareTruncated": "square", "squareTetrakis": "square", "trihexagonal": "pointyHex",
             "triangleHorizontal": "pointyHex", "triangleVertical": "flatHex", "rhombille": "pointyHex"}
KIND_NAMES = {"pointyHex": "pointy-top hex", "flatHex": "flat-top hex", "square": "square",
              "square45deg": "diamond (45-degree square)"}


class TileGrid:
    def __init__(self, w: World, kind=None, size=None, origin=None):
        self.w = w
        opts = w.grid_overlay()
        notes = []
        if kind and kind != "map":
            k = {"hex": "pointyHex", "pointyhex": "pointyHex", "flathex": "flatHex", "square": "square",
                 "diamond": "square45deg", "square45deg": "square45deg"}.get(kind.lower(), kind)
            if k not in PATTERNS:
                raise MapError(f"unknown grid type '{kind}'")
            size_mi = float(size) if size else float(opts.get("scale", 1)) * 25 * w.scale
            s = size_mi / w.scale / 25
            ox, oy = origin if origin else (0.0, 0.0)
            dx, dy = ox / s, oy / s
            source = f"custom {KIND_NAMES[k]} grid, {size_mi:g} {w.unit} across"
        else:
            k = opts.get("type") or "pointyHex"
            if k in STAND_INS:
                notes.append(f"Azgaar overlay '{k}' is stood in for by '{STAND_INS[k]}' tiles of the same period")
                k = STAND_INS[k]
            if k not in PATTERNS:
                notes.append(f"unknown overlay '{k}'; using pointy-top hexes")
                k = "pointyHex"
            s = float(opts.get("scale") or 1)
            dx, dy = float(opts.get("dx") or 0), float(opts.get("dy") or 0)
            if size:
                s = float(size) / w.scale / 25
                notes.append("tile size set by --size, so tiles no longer match Azgaar's overlay")
            source = f"Azgaar grid overlay '{opts.get('type') or 'pointyHex'}', scale {s:g}, shift ({dx:g}, {dy:g})"
        self.kind, self.s, self.dx, self.dy = k, s, dx, dy
        self.pat = PATTERNS[k]
        self.source = source
        self.notes = notes
        self.verts = [(s * a, s * b) for a, b in self.pat["verts"]]
        self.hw = max(abs(v[0]) for v in self.verts)
        self.hh = max(abs(v[1]) for v in self.verts)
        self.step_x = s * self.pat["step"][0]
        self.step_y = s * self.pat["step"][1]
        self.width_px = s * self.pat["width"]          # flat-to-flat (hex) or edge (square)
        self.width_mi = self.width_px * w.scale
        self.area_px = poly_area(self.verts)
        self._ranges()

    # ------------------------------------------------------------ lattice
    def center(self, i, j):
        s, dx, dy, k = self.s, self.dx, self.dy, self.kind
        if k == "pointyHex":
            return s * (25 * i + 12.5 * (j % 2) + dx), s * (14.45 + 21.7 * j + dy)
        if k == "flatHex":
            return s * (7.25 + 21.7 * i + dx), s * (12.5 + 25 * j - 12.5 * (i % 2) + dy)
        if k == "square":
            return s * (12.5 + 25 * i + dx), s * (12.5 + 25 * j + dy)
        h = 17.6775
        return s * (h * (2 * i + (j + 1) % 2) + dx), s * (h * j + dy)

    def poly(self, i, j):
        cx, cy = self.center(i, j)
        return [(cx + a, cy + b) for a, b in self.verts]

    def exists(self, i, j):
        cx, cy = self.center(i, j)
        return cx + self.hw > 0 and cx - self.hw < self.w.W and cy + self.hh > 0 and cy - self.hh < self.w.H

    def _ranges(self):
        W, H = self.w.W, self.w.H
        x0, y0 = self.center(0, 0)
        ilo = math.floor((-self.hw - x0) / self.step_x) - 3
        ihi = math.ceil((W + self.hw - x0) / self.step_x) + 3
        jlo = math.floor((-self.hh - y0) / self.step_y) - 3
        jhi = math.ceil((H + self.hh - y0) / self.step_y) + 3
        jm = (jlo + jhi) // 2
        im = (ilo + ihi) // 2

        def xs_ok(i):
            return any(self.center(i, jj)[0] + self.hw > 0 and self.center(i, jj)[0] - self.hw < W for jj in (jm, jm + 1))

        def ys_ok(j):
            return any(self.center(ii, j)[1] + self.hh > 0 and self.center(ii, j)[1] - self.hh < H for ii in (im, im + 1))

        cols = [i for i in range(ilo, ihi + 1) if xs_ok(i)]
        rows = [j for j in range(jlo, jhi + 1) if ys_ok(j)]
        self.imin, self.imax = cols[0], cols[-1]
        self.jmin, self.jmax = rows[0], rows[-1]
        self.ncols = self.imax - self.imin + 1
        self.nrows = self.jmax - self.jmin + 1
        block = 100
        while math.ceil(self.ncols / block) > len(LETTERS) or math.ceil(self.nrows / block) > len(LETTERS):
            block *= 10
        self.block = block
        self.digits = len(str(block)) - 1
        self.blocks_e = math.ceil(self.ncols / block)
        self.blocks_n = math.ceil(self.nrows / block)
        # continuous easting/northing for point references
        self.x_origin = self.center(self.imin, 0 if self.kind != "flatHex" else 0)[0] - self.step_x / 2
        if self.kind == "pointyHex":
            self.x_origin = min(self.center(self.imin, 0)[0], self.center(self.imin, 1)[0]) - self.step_x / 2
        self.y_origin = max(self.center(0, self.jmax)[1], self.center(1, self.jmax)[1]) + self.step_y / 2

    def locate(self, x, y):
        s, dx, dy, k = self.s, self.dx, self.dy, self.kind
        if k == "pointyHex":
            j0 = round((y / s - dy - 14.45) / 21.7)
            i0 = round((x / s - dx - 12.5 * (j0 % 2)) / 25)
        elif k == "flatHex":
            i0 = round((x / s - dx - 7.25) / 21.7)
            j0 = round((y / s - dy - 12.5 + 12.5 * (i0 % 2)) / 25)
        elif k == "square":
            i0 = math.floor((x / s - dx) / 25)
            j0 = math.floor((y / s - dy) / 25)
        else:
            h = 17.6775
            j0 = round((y / s - dy) / h)
            i0 = round(((x / s - dx) / h - (j0 + 1) % 2) / 2)
        best, bd = (i0, j0), float("inf")
        for di in (0, -1, 1, -2, 2):
            for dj in (0, -1, 1, -2, 2):
                i, j = i0 + di, j0 + dj
                if point_in_poly(x, y, self.poly(i, j)):
                    return i, j
                dd = math.dist((x, y), self.center(i, j))
                if dd < bd:
                    best, bd = (i, j), dd
        return best

    def neighbours(self, i, j):
        cx, cy = self.center(i, j)
        p = self.poly(i, j)
        out = []
        for a in range(len(p)):
            mx = (p[a][0] + p[(a + 1) % len(p)][0]) / 2
            my = (p[a][1] + p[(a + 1) % len(p)][1]) / 2
            vx, vy = mx - cx, my - cy
            ni, nj = self.locate(cx + 2 * vx, cy + 2 * vy)
            out.append((compass(bearing(vx, vy)), ni, nj))
        if self.kind in ("square", "square45deg"):  # corner neighbours too
            for a in range(len(p)):
                vx, vy = p[a][0] - cx, p[a][1] - cy
                ni, nj = self.locate(cx + 2 * vx, cy + 2 * vy)
                out.append((compass(bearing(vx, vy)), ni, nj))
        order = {d: k for k, d in enumerate(COMPASS8)}
        return sorted(out, key=lambda t: order.get(t[0], 9))

    # ------------------------------------------------------------ references
    def en(self, i, j):
        return i - self.imin, self.jmax - j

    def ij(self, e, n):
        return e + self.imin, self.jmax - n

    def square_letters(self, e, n):
        be, bn = e // self.block, n // self.block
        if not (0 <= be < len(LETTERS) and 0 <= bn < len(LETTERS)):
            return "??"
        return LETTERS[be] + LETTERS[bn]

    def ref(self, i, j, compact=False):
        e, n = self.en(i, j)
        dg, b = self.digits, self.block
        sep = "" if compact else " "
        return f"{self.square_letters(e, n)}{sep}{e % b:0{dg}d}{sep}{n % b:0{dg}d}"

    def point_ref(self, x, y):
        e = (x - self.x_origin) / self.step_x
        n = (self.y_origin - y) / self.step_y
        ei, ni = int(math.floor(e * 10)), int(math.floor(n * 10))
        b10 = self.block * 10
        dg = self.digits + 1
        return f"{self.square_letters(ei // 10, ni // 10)} {ei % b10:0{dg}d} {ni % b10:0{dg}d}"

    def parse(self, text):
        """'CB 12 47' -> ('tile', i, j); 'CB 1 4' -> ('block', ...); 'CB 123 474' -> ('point', x, y)."""
        t = text.strip().upper().replace("/", " ").replace(",", " ").replace(".", " ")
        m = re.fullmatch(r"([A-Z])\s*([A-Z])\s*([0-9 ]*)", t)
        if not m:
            return None
        l1, l2, digits = m.group(1), m.group(2), re.sub(r"\s+", " ", m.group(3).strip())
        if l1 not in LETTERS or l2 not in LETTERS:
            return None
        be, bn = LETTERS.index(l1), LETTERS.index(l2)
        parts = digits.split(" ") if digits else []
        if len(parts) == 2:
            es, ns = parts
        elif len(parts) == 1 and len(parts[0]) % 2 == 0:
            es, ns = parts[0][:len(parts[0]) // 2], parts[0][len(parts[0]) // 2:]
        elif not parts:
            es = ns = ""
        else:
            return None
        if len(es) != len(ns):
            return None
        L = len(es)
        b = self.block
        if L == 0:
            return ("block", be * b, bn * b, b)
        if L == self.digits:
            return ("tile",) + self.ij(be * b + int(es), bn * b + int(ns))
        if L < self.digits:
            unit = 10 ** (self.digits - L)
            return ("block", be * b + int(es) * unit, bn * b + int(ns) * unit, unit)
        if L == self.digits + 1:
            e = be * b + int(es) / 10 + 0.05
            n = bn * b + int(ns) / 10 + 0.05
            return ("point", self.x_origin + e * self.step_x, self.y_origin - n * self.step_y)
        return None

    def block_tiles(self, e0, n0, size):
        out = []
        for e in range(e0, min(e0 + size, self.ncols)):
            for n in range(n0, min(n0 + size, self.nrows)):
                i, j = self.ij(e, n)
                if self.exists(i, j):
                    out.append((i, j))
        return out

    def describe(self):
        return (f"{KIND_NAMES[self.kind]} tiles {fnum(self.width_mi, 2)} {self.w.unit} across "
                f"({fnum(self.width_px, 3)} px), {self.ncols} columns by {self.nrows} rows; "
                f"lettered squares of {self.block} x {self.block} tiles, {self.blocks_e} east by {self.blocks_n} north")


# ====================================================================== tile analysis
TEMP_LIKENESS = {-5: "Snag (Yukon)", -4: "Yellowknife (Canada)", -3: "Okhotsk (Russia)", -2: "Fairbanks (Alaska)",
                 -1: "Nuuk (Greenland)", 0: "Murmansk (Russia)", 1: "Arkhangelsk (Russia)", 2: "Anchorage (Alaska)",
                 3: "Tromsø (Norway)", 4: "Reykjavik (Iceland)", 5: "Harbin (China)", 6: "Stockholm (Sweden)",
                 7: "Montreal (Canada)", 8: "Prague (Czechia)", 9: "Copenhagen (Denmark)", 10: "London (England)",
                 11: "Antwerp (Belgium)", 12: "Paris (France)", 13: "Milan (Italy)", 14: "Washington (D.C.)",
                 15: "Rome (Italy)", 16: "Dubrovnik (Croatia)", 17: "Lisbon (Portugal)", 18: "Barcelona (Spain)",
                 19: "Marrakesh (Morocco)", 20: "Alexandria (Egypt)", 21: "Tegucigalpa (Honduras)",
                 22: "Guangzhou (China)", 23: "Rio de Janeiro (Brazil)", 24: "Dakar (Senegal)", 25: "Miami (USA)",
                 26: "Jakarta (Indonesia)", 27: "Mogadishu (Somalia)", 28: "Bangkok (Thailand)", 29: "Niamey (Niger)",
                 30: "Khartoum (Sudan)"}


def temperature_likeness(t):
    """Azgaar's getTemperatureLikeness."""
    if t < -5:
        return "Yakutsk (Russia)"
    if t > 30:
        return "Mecca (Saudi Arabia)"
    return TEMP_LIKENESS.get(int(round(t)))


def day_length(lat, decl):
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(decl))
    if x <= -1:
        return 24.0
    if x >= 1:
        return 0.0
    return 2 * math.degrees(math.acos(x)) / 15


class Tile:
    """Everything the files say about one tile, with the derived figures."""

    def __init__(self, w: World, grid: TileGrid, i, j, legacy_speeds=False, near_tiles=10):
        self.w, self.g, self.i, self.j = w, grid, i, j
        self.legacy = legacy_speeds
        self.poly = grid.poly(i, j)
        self.bbox = bbox_of(self.poly)
        self.cx, self.cy = grid.center(i, j)
        self.area_px = poly_area(self.poly)
        self.ref = grid.ref(i, j)
        self.near_px = max(near_tiles * grid.width_px, 3 * w.grid_spacing)
        self.R = {}
        self.eco = None

    # ------------------------------------------------------------------ helpers
    def where(self, x, y):
        """Distance (in map units), compass bearing and grid reference of a point from the tile centre."""
        dist = math.dist((self.cx, self.cy), (x, y)) * self.w.scale
        i, j = self.g.locate(x, y)
        return {"dist": dist, "dir": compass(bearing(x - self.cx, y - self.cy), 16), "ref": self.g.ref(i, j)}

    def inside(self, x, y):
        return bbox_hit(self.bbox, (x, y, x, y)) and point_in_poly(x, y, self.poly)

    # ------------------------------------------------------------------ run
    def analyse(self):
        w, d = self.w, self.w.d
        self.eco = Economy(w)
        self._overlap()
        self._samples()
        self._location()
        self._terrain_climate()
        self._people()
        self._polity()
        self._borders()
        self._zones()
        self._places()
        self._lines()
        self._trade()
        self._cells_table()
        return self.R

    def _overlap(self):
        w = self.w
        self.ov = []
        for c in w.cell_index.query(self.bbox):
            if not bbox_hit(self.bbox, w.cell_bbox[c]):
                continue
            part = clip_convex(w.cell_poly[c], self.poly)
            a = poly_area(part)
            if a > 1e-9:
                self.ov.append({"cell": c, "area": a, "of_tile": a / self.area_px,
                                "of_cell": a / w.cell_area[c] if w.cell_area[c] else 0})
        self.ov.sort(key=lambda o: -o["area"])
        self.ov_cells = [o["cell"] for o in self.ov]
        self.on_map = sum(o["area"] for o in self.ov) / self.area_px
        self.land_area = sum(o["area"] for o in self.ov if not w.water[o["cell"]])
        self.water_area = sum(o["area"] for o in self.ov if w.water[o["cell"]])

    def _samples(self):
        w = self.w
        x0, y0, x1, y1 = self.bbox
        k = 9
        pts = []
        for a in range(k + 1):
            for b in range(k + 1):
                x = x0 + (x1 - x0) * (a + 0.5) / (k + 1)
                y = y0 + (y1 - y0) * (b + 0.5) / (k + 1)
                if 0 <= x <= w.W and 0 <= y <= w.H and point_in_poly(x, y, self.poly):
                    pts.append((x, y))
        if not pts:
            pts = [(min(max(self.cx, 0), w.W), min(max(self.cy, 0), w.H))]
        self.samples = []
        for x, y in pts:
            c = w.cell_at(x, y, self.ov_cells or None)
            self.samples.append({"x": x, "y": y, "g": w.grid_index(x, y), "cell": c})
        # land or water as drawn (Azgaar's smoothed outlines), where the SVG keeps them
        if w.feature_rings:
            for s in self.samples:
                s["drawn"] = w.drawn_kind(s["x"], s["y"])
            self.drawn_land = sum(1 for s in self.samples if s["drawn"] == "land") / len(self.samples)
        else:
            self.drawn_land = None

    # ------------------------------------------------------------------ location
    def _location(self):
        w, g = self.w, self.g
        lon, lat = w.to_lonlat(self.cx, self.cy)
        e, n = g.en(self.i, self.j)
        feats = defaultdict(float)
        for o in self.ov:
            feats[w.cell_feature[o["cell"]]] += o["of_tile"]
        flist = []
        for fid, share in sorted(feats.items(), key=lambda kv: -kv[1]):
            f = w.feature(fid) or {}
            flist.append({"id": fid, "label": w.feature_label(fid), "type": f.get("type"), "share": share,
                          "area": w.sq(f.get("area") or 0), "cells": f.get("cells")})
        # coastline inside the tile and nearest coast
        coast_len = 0.0
        nearest = (float("inf"), None, None)
        for k in w.edge_index.query(self.bbox):
            a, b, p, q = w.edges[k]
            if w.water[a] != w.water[b]:
                r = clip_segment(p, q, self.poly)
                if r:
                    coast_len += (r[1] - r[0]) * math.dist(p, q)
        for a, b, p, q in w.edges:
            if w.water[a] != w.water[b]:
                dd, pt = point_seg_dist((self.cx, self.cy), p, q)
                if dd < nearest[0]:
                    nearest = (dd, pt, a if w.water[a] else b)
        coast = None
        if nearest[1]:
            wc = nearest[2]
            coast = dict(self.where(*nearest[1]), water=w.feature_label(w.cell_feature[wc]))
        self.R["location"] = {
            "ref": self.ref, "ref_compact": g.ref(self.i, self.j, True), "kind": KIND_NAMES[g.kind],
            "width": g.width_mi, "area": w.sq(self.area_px), "on_map": self.on_map,
            "easting": e, "northing": n, "square": g.square_letters(e, n), "center_px": (self.cx, self.cy),
            "lon": lon, "lat": lat, "point_ref": g.point_ref(self.cx, self.cy),
            "pos": (self.cx / w.W, self.cy / w.H),
            "neighbours": [{"dir": dd, "ref": g.ref(ni, nj), "exists": g.exists(ni, nj)} for dd, ni, nj in g.neighbours(self.i, self.j)],
            "land_share": self.land_area / self.area_px, "water_share": self.water_area / self.area_px,
            "drawn_land": self.drawn_land, "features": flist, "coast_len": w.miles(coast_len), "coast": coast,
        }

    # ------------------------------------------------------------------ terrain and climate
    def _ctx_sets(self):
        w = self.w
        gp = w.grid_points
        h = w.d["grid_h"]
        gpack = w.grid_pack
        land = [k for k in range(len(gp)) if k < len(h) and h[k] >= 20 and gpack[k] >= 0]
        water = [k for k in range(len(gp)) if k < len(h) and h[k] < 20 and gpack[k] >= 0]
        states = Counter(w.d["state"][o["cell"]] for o in self.ov for _ in [0] if not w.water[o["cell"]])
        provs = Counter(w.d["province"][o["cell"]] for o in self.ov if not w.water[o["cell"]])
        main_state = max(states, key=states.get) if states else None
        main_prov = max(provs, key=provs.get) if provs else None
        band = 1.5 * w.grid_spacing
        near = self.near_px
        return land, water, main_state, main_prov, band, near

    def _terrain_climate(self):
        w, d = self.w, self.w.d
        gh, gt, gpr = d["grid_h"], d["grid_temp"], d["grid_prec"]
        sh = [gh[s["g"]] for s in self.samples]
        st = [gt[s["g"]] for s in self.samples]
        sp = [gpr[s["g"]] for s in self.samples]
        land_samples = [s for s in self.samples if gh[s["g"]] >= 20]
        elev_m = [w.height_m(gh[s["g"]]) for s in self.samples]
        gcells = Counter(s["g"] for s in self.samples)
        # interpolated (mixed): inverse-distance weighting over the 3 x 3 grid points round the centre
        g0 = w.grid_index(self.cx, self.cy)
        gx, gy = g0 % w.cellsX, g0 // w.cellsX
        num = den = tnum = 0.0
        for ax in (-1, 0, 1):
            for ay in (-1, 0, 1):
                xx, yy = gx + ax, gy + ay
                if 0 <= xx < w.cellsX and 0 <= yy < w.cellsY:
                    k = yy * w.cellsX + xx
                    p = w.grid_points[k]
                    dd = max(math.dist(p, (self.cx, self.cy)), 1e-6)
                    wt = 1 / dd ** 2
                    num += wt * gh[k]
                    tnum += wt * gt[k]
                    den += wt
        h_idw = num / den if den else None
        t_idw = tnum / den if den else None
        land, water, main_state, main_prov, band, near = self._ctx_sets()
        is_land = len(land_samples) >= len(self.samples) / 2
        pool = land if is_land else water
        gp, gpack = w.grid_points, w.grid_pack
        sets = {
            "surroundings": [k for k in pool if math.dist(gp[k], (self.cx, self.cy)) <= near],
            "province": [k for k in pool if main_prov and d["province"][gpack[k]] == main_prov],
            "state": [k for k in pool if main_state and d["state"][gpack[k]] == main_state],
            "latitude": [k for k in pool if abs(gp[k][1] - self.cy) <= band],
            "world": pool,
        }
        metric_vals = {"elevation": lambda k: w.height_m(gh[k]), "temperature": lambda k: gt[k],
                       "precipitation": lambda k: gpr[k] * 100}
        tile_vals = {"elevation": mean(elev_m), "temperature": mean(st), "precipitation": mean(v * 100 for v in sp)}
        ctx = {}
        for mname, fn in metric_vals.items():
            ctx[mname] = {}
            for sname, ks in sets.items():
                vals = [fn(k) for k in ks]
                if vals:
                    ctx[mname][sname] = {"mean": mean(vals), "min": min(vals), "max": max(vals), "n": len(vals),
                                         "rank": percentile_rank(tile_vals[mname], vals)}
        # highest and lowest ground nearby
        extremes = {}
        sur = [k for k in land if math.dist(gp[k], (self.cx, self.cy)) <= near]
        if sur:
            hi = max(sur, key=lambda k: gh[k])
            lo = min(sur, key=lambda k: gh[k])
            extremes = {"high": dict(self.where(*gp[hi]), h=w.height_m(gh[hi])),
                        "low": dict(self.where(*gp[lo]), h=w.height_m(gh[lo]))}
        lon, lat = w.to_lonlat(self.cx, self.cy)
        wind = None
        if w.winds:
            tier = min(int(abs(lat - 89) / 30), len(w.winds) - 1)
            ang = float(w.winds[tier])
            wind = {"setting": ang, "from": compass((ang + 180) % 360, 16), "tier": tier}
        biomes = defaultdict(float)
        for o in self.ov:
            biomes[d["biome"][o["cell"]]] += o["of_tile"]
        blist = []
        for b, share in sorted(biomes.items(), key=lambda kv: -kv[1]):
            bi = w.biomes[b] if b < len(w.biomes) else {}
            st_share = None
            if main_state:
                tot = sum(w.cell_area[c] for c in range(w.n) if d["state"][c] == main_state and not w.water[c])
                bb = sum(w.cell_area[c] for c in range(w.n) if d["state"][c] == main_state and d["biome"][c] == b)
                st_share = bb / tot if tot else None
            blist.append({"id": b, "name": w.biome_name(b), "share": share, "habitability": bi.get("habitability"),
                          "cost": bi.get("cost"), "color": bi.get("color"), "state_share": st_share})
        pack_h = [(w.cell_height_disp[o["cell"]], o["of_tile"]) for o in self.ov if w.cell_height_disp[o["cell"]] is not None]
        ice = []
        for k, ic in enumerate(d.get("ice") or []):
            if isinstance(ic, dict) and len(ic.get("points") or []) >= 3:
                part = clip_convex([tuple(p[:2]) for p in ic["points"]], self.poly)
                a = poly_area(part)
                if a > 1e-9:
                    ice.append({"type": ic.get("type", "ice"), "share": a / self.area_px})
        self.R["terrain"] = {
            "elev_mean": mean(elev_m), "elev_min": min(elev_m), "elev_max": max(elev_m),
            "h_samples": (min(sh), max(sh)), "h_idw": h_idw, "elev_idw": w.height_m(h_idw) if h_idw is not None else None,
            "grid_cells": len(gcells), "pack_height": (sum(v * s for v, s in pack_h) / sum(s for _, s in pack_h)) if pack_h else None,
            "is_land": is_land, "biomes": blist, "extremes": extremes, "ice": ice,
        }
        self.R["climate"] = {
            "temp_mean": mean(st), "temp_min": min(st), "temp_max": max(st), "temp_idw": t_idw,
            "prec_mean": mean(v * 100 for v in sp), "likeness": temperature_likeness(mean(st)) if st else None,
            "lat": lat, "lon": lon, "wind": wind,
            "day_long": day_length(lat, 23.44 if lat >= 0 else -23.44),
            "day_short": day_length(lat, -23.44 if lat >= 0 else 23.44),
        }
        self.R["context"] = {"tile": tile_vals, "sets": ctx, "radius": w.miles(near),
                             "band": w.miles(band), "main_state": main_state, "main_province": main_prov,
                             "domain": "land" if is_land else "water"}

    # ------------------------------------------------------------------ people
    def _area_pop(self, key, value):
        """Land area (px²) and rural, urban population points of every cell with d[key] == value."""
        w, d = self.w, self.w.d
        area = rural = urban = 0.0
        for c in range(w.n):
            if d[key][c] == value and not w.water[c]:
                area += w.cell_area[c]
                rural += d["pop"][c]
                b = d["burg"][c]
                if b and w.burg(b):
                    urban += w.burg(b).get("population", 0)
        return area, rural, urban

    def _people(self):
        w, d = self.w, self.w.d
        rural_pts = sum(d["pop"][o["cell"]] * o["of_cell"] for o in self.ov)
        self.tile_burgs = [b for b in w.live(w.burgs) if b.get("i") and self.inside(b["x"], b["y"])]
        urban_pts = sum(b.get("population", 0) for b in self.tile_burgs)
        rural = rural_pts * w.pop_scale
        urban = urban_pts * w.pop_scale * w.urb_rate
        land_sq = w.sq(self.land_area)
        # smoothed rural density (mixed): inverse-distance weighting of the densities of nearby land cells
        near_cells = set(self.ov_cells)
        for c in list(near_cells):
            near_cells.update(m for m in w.nbrs[c] if 0 <= m < w.n)
        land_cells = [c for c in near_cells if not w.water[c] and w.cell_area[c] > 0]
        dens = []
        for s in self.samples:
            if w.water[s["cell"]]:
                continue
            num = den = 0.0
            for c in land_cells:
                dd = max(math.dist((s["x"], s["y"]), w.site[c]), 1e-6)
                wt = 1 / dd ** 2
                num += wt * d["pop"][c] / w.cell_area[c]
                den += wt
            if den:
                dens.append(num / den)
        smooth = mean(dens) * self.land_area * w.pop_scale if dens else 0.0
        ctx = {}
        for label, key, val in (("province", "province", self.R["context"]["main_province"]),
                                ("state", "state", self.R["context"]["main_state"])):
            if val:
                a, r, u = self._area_pop(key, val)
                if a:
                    ctx[label] = w.people(r, u) / w.sq(a)
        tot_a = sum(w.cell_area[c] for c in range(w.n) if not w.water[c])
        tot_p = w.people(sum(d["pop"]), sum(b.get("population", 0) for b in w.live(w.burgs) if b.get("i")))
        ctx["world"] = tot_p / w.sq(tot_a) if tot_a else None
        under = [c for c in self.ov_cells if not w.water[c]]
        ua = sum(w.cell_area[c] for c in under)
        if ua:
            ctx["cells"] = w.people(sum(d["pop"][c] for c in under)) / w.sq(ua)
        cult = defaultdict(lambda: [0.0, 0.0])
        rel = defaultdict(lambda: [0.0, 0.0])
        for o in self.ov:
            c = o["cell"]
            if w.water[c]:
                continue
            cult[d["culture"][c]][0] += o["of_tile"]
            cult[d["culture"][c]][1] += d["pop"][c] * o["of_cell"]
            rel[d["religion"][c]][0] += o["of_tile"]
            rel[d["religion"][c]][1] += d["pop"][c] * o["of_cell"]
        for b in self.tile_burgs:
            cult[b.get("culture", 0)][1] += b.get("population", 0) * w.urb_rate
            rel[d["religion"][b["cell"]]][1] += b.get("population", 0) * w.urb_rate
        tot_people_pts = sum(v[1] for v in cult.values()) or 1
        cultures = []
        for cid, (ash, pp) in sorted(cult.items(), key=lambda kv: -kv[1][0]):
            cu = w.culture(cid)
            centre = cu.get("center")
            cultures.append({
                "id": cid, "name": cu.get("name", f"culture {cid}"), "type": cu.get("type"),
                "namebase": w.namebases.get(cu.get("base")), "base": cu.get("base"),
                "expansionism": cu.get("expansionism"), "lineage": self._lineage(w.cultures, cid),
                "hearth": self.where(*w.site[centre]) if centre is not None and 0 <= centre < w.n else None,
                "area_share": ash, "pop_share": pp / tot_people_pts, "shield": cu.get("shield"), "code": cu.get("code"),
                "state_culture_of": [s["name"] for s in w.live(w.states) if s.get("i") and s.get("culture") == cid],
            })
        tot_rel = sum(v[1] for v in rel.values()) or 1
        religions = []
        for rid, (ash, pp) in sorted(rel.items(), key=lambda kv: -kv[1][0]):
            r = w.religion(rid)
            centre = r.get("center")
            religions.append({
                "id": rid, "name": r.get("name", f"religion {rid}"), "type": r.get("type"), "form": r.get("form"),
                "deity": r.get("deity"), "expansion": r.get("expansion"), "expansionism": r.get("expansionism"),
                "culture": w.culture(r["culture"]).get("name") if r.get("culture") is not None else None,
                "lineage": self._lineage(w.religions, rid),
                "seat": self.where(*w.site[centre]) if centre is not None and 0 <= centre < w.n else None,
                "area_share": ash, "pop_share": pp / tot_rel, "code": r.get("code"),
            })
        self.R["people"] = {"rural": rural, "urban": urban, "total": rural + urban, "land_area": land_sq,
                            "density": (rural + urban) / land_sq if land_sq else None,
                            "rural_density": rural / land_sq if land_sq else None,
                            "smooth_rural": smooth, "context": ctx, "burg_count": len(self.tile_burgs)}
        self.R["cultures"] = cultures
        self.R["religions"] = religions

    def _lineage(self, items, i, depth=0):
        """Names along the 'origins' chain (parents first found), without cycles."""
        out, seen, cur = [], {i}, i
        while depth < 12:
            rec = items[cur] if 0 <= cur < len(items) and isinstance(items[cur], dict) else None
            origins = [o for o in (rec.get("origins") or []) if o is not None] if rec else []
            if not origins:
                break
            parent = origins[0]
            if parent == 0 or parent in seen or not (0 <= parent < len(items)) or not isinstance(items[parent], dict):
                break  # 0 is the root record (Wildlands, No religion)
            out.append(items[parent].get("name", str(parent)))
            seen.add(parent)
            cur = parent
            depth += 1
        return out

    def _ancestors(self, items, i):
        out, stack = set(), [i]
        while stack:
            c = stack.pop()
            rec = items[c] if 0 <= c < len(items) and isinstance(items[c], dict) else None
            for o in (rec.get("origins") or []) if rec else []:
                if o is not None and o not in out and o != i:
                    out.add(o)
                    stack.append(o)
        return out

    # ------------------------------------------------------------------ polity
    def _state_card(self, sid):
        w, d = self.w, self.w.d
        s = w.state(sid) or {}
        live_states = [x for x in w.live(w.states) if x.get("i")]
        def rank(key):
            vals = sorted((x.get(key) or 0 for x in live_states), reverse=True)
            v = s.get(key) or 0
            return vals.index(v) + 1 if v in vals else None
        cap = w.burg(s.get("capital") or 0)
        mil = sum(u.get("a", 0) for u in w.units if u["state"] == sid)
        rels = Counter(r for k, r in enumerate(s.get("diplomacy") or []) if isinstance(r, str) and k != sid and r != "x")
        return {
            "id": sid, "name": w.state_name(sid), "full": s.get("fullName") or w.state_name(sid),
            "form": s.get("form"), "formName": s.get("formName"), "type": s.get("type"),
            "capital": {"name": cap["name"], **self.where(cap["x"], cap["y"])} if cap else None,
            "culture": w.culture(s.get("culture", 0)).get("name") if s.get("culture") is not None else None,
            "culture_id": s.get("culture"),
            "salesTax": s.get("salesTax"), "pollTax": s.get("pollTax"), "treasury": s.get("treasury"),
            "rank_sales": rank("salesTax"), "rank_poll": rank("pollTax"), "rank_treasury": rank("treasury"),
            "n_states": len(live_states), "alert": s.get("alert"), "expansionism": s.get("expansionism"),
            "people": w.people(s.get("rural") or 0, s.get("urban") or 0), "area": w.sq(s.get("area") or 0),
            "burgs": s.get("burgs"), "provinces": len(s.get("provinces") or []), "military": mil,
            "units": sum(1 for u in w.units if u["state"] == sid),
            "neighbors": [w.state_name(x) for x in s.get("neighbors") or []], "relations": dict(rels),
            "note": clean_note(s.get("note", "")), "color": s.get("color"),
            "campaigns": [c for c in s.get("campaigns") or [] if isinstance(c, dict)],
        }

    def _polity(self):
        w, d = self.w, self.w.d
        st = defaultdict(lambda: [0.0, 0.0])
        pv = defaultdict(lambda: [0.0, 0.0])
        for o in self.ov:
            c = o["cell"]
            if w.water[c]:
                continue
            st[d["state"][c]][0] += o["of_tile"]
            st[d["state"][c]][1] += d["pop"][c] * o["of_cell"]
            pv[d["province"][c]][0] += o["of_tile"]
            pv[d["province"][c]][1] += d["pop"][c] * o["of_cell"]
        states = []
        for sid, (a, p) in sorted(st.items(), key=lambda kv: -kv[1][0]):
            card = self._state_card(sid) if sid else {"id": 0, "name": "Neutral lands", "full": "Neutral (unclaimed) lands"}
            card.update(area_share=a)
            # dominant religion of the state, by rural population
            if sid:
                rc = Counter()
                for c in range(w.n):
                    if d["state"][c] == sid:
                        rc[d["religion"][c]] += d["pop"][c]
                top = rc.most_common(1)
                card["main_religion"] = w.religion(top[0][0]).get("name") if top else None
                card["main_religion_id"] = top[0][0] if top else None
            states.append(card)
        provinces = []
        for pid, (a, p) in sorted(pv.items(), key=lambda kv: -kv[1][0]):
            pr = w.province(pid)
            if not pr:
                continue
            ar, ru, ur = self._area_pop("province", pid)
            cap = w.burg(pr.get("burg") or 0)
            provinces.append({"id": pid, "name": pr.get("name"), "full": pr.get("fullName") or pr.get("name"),
                              "form": pr.get("formName"), "state": w.state_name(pr.get("state", 0)),
                              "capital": {"name": cap["name"], **self.where(cap["x"], cap["y"])} if cap else None,
                              "area": w.sq(ar), "people": w.people(ru, ur), "area_share": a,
                              "note": clean_note(pr.get("note", ""))})
        # mismatches between the tile and its rulers (tension signals, all data)
        flags = []
        cults = self.R.get("cultures", [])
        rels = self.R.get("religions", [])
        for s in states:
            if not s.get("id"):
                continue
            if cults and s.get("culture_id") is not None and cults[0]["id"] != s["culture_id"]:
                flags.append(f"Most of the tile's people are {cults[0]['name']}; {s['name']}'s state culture is {s['culture']}.")
            if rels and s.get("main_religion_id") is not None and rels[0]["id"] != s["main_religion_id"]:
                flags.append(f"The tile's main faith is {rels[0]['name']}; most of {s['name']} follows {s['main_religion']}.")
        for pr in provinces:
            pass
        self.R["states"] = states
        self.R["provinces"] = provinces
        self.R["flags"] = flags

    # ------------------------------------------------------------------ borders
    def _relation_story(self, a, b):
        w = self.w
        sa, sb = w.state(a) or {}, w.state(b) or {}
        da, db = sa.get("diplomacy") or [], sb.get("diplomacy") or []
        rel_ab = da[b] if b < len(da) and isinstance(da[b], str) else None
        rel_ba = db[a] if a < len(db) and isinstance(db[a], str) else None
        camps = []
        for s in (sa, sb):
            for c in s.get("campaigns") or []:
                if isinstance(c, dict) and {c.get("attacker"), c.get("defender")} == {a, b}:
                    if c not in camps:
                        camps.append(c)
        camps.sort(key=lambda c: c.get("start") or 0)
        na, nb = w.state_name(a), w.state_name(b)
        chron = []
        neutral = w.state(0) or {}
        for war in neutral.get("diplomacy") or []:
            if isinstance(war, list) and war:
                lines = [str(x) for x in war]
                text = " ".join(lines)
                if na in text and nb in text:
                    chron.append(lines)
        return {"a": na, "b": nb, "a_to_b": rel_ab, "b_to_a": rel_ba,
                "campaigns": [{"name": c.get("name"), "start": c.get("start"), "end": c.get("end"),
                               "attacker": w.state_name(c.get("attacker", 0)), "defender": w.state_name(c.get("defender", 0)),
                               "ongoing": c.get("end") is None or (self.w.year is not None and c.get("end") >= self.w.year)}
                              for c in camps], "chronicle": chron}

    def _borders(self):
        w, d = self.w, self.w.d
        groups = {"state": d["state"], "province": d["province"], "culture": d["culture"],
                  "religion": d["religion"], "market": d["market"], "biome": d["biome"]}
        found = {k: defaultdict(float) for k in groups}
        for k in w.edge_index.query(self.bbox):
            a, b, p, q = w.edges[k]
            if w.water[a] or w.water[b]:
                continue
            r = None
            for gk, arr in groups.items():
                if arr[a] != arr[b]:
                    if r is None:
                        r = clip_segment(p, q, self.poly) or False
                    if r:
                        key = tuple(sorted((arr[a], arr[b])))
                        found[gk][key] += (r[1] - r[0]) * math.dist(p, q)
        out = {}
        for gk, pairs in found.items():
            items = []
            for (x, y), L in sorted(pairs.items(), key=lambda kv: -kv[1]):
                item = {"pair": (x, y), "length": w.miles(L)}
                if gk == "state":
                    item.update(self._relation_story(x, y) if x and y else
                                {"a": w.state_name(x), "b": w.state_name(y), "a_to_b": None, "b_to_a": None,
                                 "campaigns": [], "chronicle": []})
                elif gk == "province":
                    px, py = w.province(x), w.province(y)
                    item.update(a=(px or {}).get("fullName") or "no province", b=(py or {}).get("fullName") or "no province",
                                same_state=(px or {}).get("state") == (py or {}).get("state"))
                elif gk in ("culture", "religion"):
                    items_list = w.cultures if gk == "culture" else w.religions
                    ax, ay = self._ancestors(items_list, x), self._ancestors(items_list, y)
                    ra = w.culture(x) if gk == "culture" else w.religion(x)
                    rb = w.culture(y) if gk == "culture" else w.religion(y)
                    if y in ax:
                        rel = f"{ra.get('name')} descends from {rb.get('name')}"
                    elif x in ay:
                        rel = f"{rb.get('name')} descends from {ra.get('name')}"
                    else:
                        common = (ax & ay) - {0}
                        rel = ("both descend from " + ", ".join(sorted((items_list[c] or {}).get("name", str(c)) for c in common))
                               if common else "no shared lineage on record")
                    item.update(a=ra.get("name"), b=rb.get("name"), a_type=ra.get("type"), b_type=rb.get("type"),
                                lineage=rel)
                    if gk == "culture":
                        item.update(a_lang=w.namebases.get(ra.get("base")), b_lang=w.namebases.get(rb.get("base")))
                    else:
                        item.update(a_form=ra.get("form"), b_form=rb.get("form"))
                elif gk == "market":
                    ma, mb = w.markets.get(x), w.markets.get(y)
                    ca = w.burg(ma.get("centerBurgId")) if ma else None
                    cb = w.burg(mb.get("centerBurgId")) if mb else None
                    trade = defaultdict(float)
                    for dl in self.eco.flows.get(x, []):
                        if {dl["seller"], dl["buyer"]} == {x, y}:
                            trade[(dl["seller"], dl["good"])] += dl["units"] * dl["price"]
                    item.update(a=f"{ca['name']} market" if ca else f"market {x}",
                                b=f"{cb['name']} market" if cb else f"market {y}",
                                a_to_b=sum(v for (s_, g_), v in trade.items() if s_ == x),
                                b_to_a=sum(v for (s_, g_), v in trade.items() if s_ == y),
                                top=[(self.eco.good_name(g_), "a" if s_ == x else "b", v)
                                     for (s_, g_), v in sorted(trade.items(), key=lambda kv: -kv[1])[:4]])
                elif gk == "biome":
                    item.update(a=w.biome_name(x), b=w.biome_name(y))
                items.append(item)
            out[gk] = items
        # nearest state border when none crosses the tile
        nearest = None
        if not out["state"]:
            best = (float("inf"), None, None)
            for a, b, p, q in w.edges:
                if not w.water[a] and not w.water[b] and d["state"][a] != d["state"][b]:
                    dd, pt = point_seg_dist((self.cx, self.cy), p, q)
                    if dd < best[0]:
                        best = (dd, pt, (d["state"][a], d["state"][b]))
            if best[1]:
                x, y = sorted(best[2])
                nearest = dict(self.where(*best[1]), **(self._relation_story(x, y) if x and y else
                                                       {"a": w.state_name(x), "b": w.state_name(y), "a_to_b": None,
                                                        "b_to_a": None, "campaigns": [], "chronicle": []}))
        self.R["borders"] = out
        self.R["nearest_border"] = nearest

    def _zones(self):
        w = self.w
        zs = []
        for z in w.zones:
            cells = w.zone_cells[z["i"]]
            share = sum(o["of_tile"] for o in self.ov if o["cell"] in cells)
            if share <= 0:
                continue
            states = Counter(w.d["state"][c] for c in cells if 0 <= c < w.n)
            zs.append({"name": z.get("name"), "type": z.get("type"), "share": share, "cells": len(cells),
                       "area": w.sq(sum(w.cell_area[c] for c in cells if 0 <= c < w.n)),
                       "states": [w.state_name(s) for s, _ in states.most_common()],
                       "people": w.people(sum(w.d["pop"][c] for c in cells if 0 <= c < w.n))})
        self.R["zones"] = zs

    # ------------------------------------------------------------------ places
    def _town_plan(self, name):
        slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("_")
        for p in self.w.folder.glob("*.json"):
            stem = re.sub(r"[^a-z0-9]+", "_", p.stem.lower()).strip("_")
            if stem == slug:
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return None
                if not isinstance(doc, dict) or "features" not in doc:
                    return None
                counts, info = {}, {}
                for f in doc["features"]:
                    fid = f.get("id")
                    if fid == "values":
                        info = {k: v for k, v in f.items() if k not in ("type", "id")}
                        continue
                    n = len(f.get("coordinates") or f.get("geometries") or [])
                    counts[fid] = n
                return {"file": p.name, "counts": counts, "info": info}
        return None

    def _emblem(self, name):
        for p in sorted(self.w.folder.glob("*.png")):
            if re.search(r"emblem", p.name, re.I) and re.search(r"\b" + re.escape(name) + r"\b", p.name, re.I):
                return p
        return None

    def _deal_summary(self, deals, partner_key):
        agg = defaultdict(lambda: {"units": 0.0, "value": 0.0, "tax": 0.0, "partners": Counter()})
        for dl in deals:
            a = agg[dl["good"]]
            a["units"] += dl.get("units", 0)
            a["value"] += dl.get("units", 0) * dl.get("price", 0)
            a["tax"] += dl.get("tax", 0)
            a["partners"][(dl.get(partner_key + "Type"), dl.get(partner_key))] += 1
        out = []
        for gid, a in sorted(agg.items(), key=lambda kv: -kv[1]["value"]):
            partners = []
            for (ptype, pid), _ in a["partners"].most_common(3):
                if ptype == "market":
                    m = self.w.markets.get(pid)
                    cb = self.w.burg(m.get("centerBurgId")) if m else None
                    partners.append(f"{cb['name']} market" if cb else f"market {pid}")
                else:
                    b = self.w.burg(pid)
                    partners.append(b["name"] if b else f"burg {pid}")
            out.append({"good": self.eco.good_name(gid), "units": a["units"], "value": a["value"], "tax": a["tax"],
                        "partners": partners})
        return out

    def _burg_card(self, b):
        w, d = self.w, self.w.d
        c = b["cell"]
        feats = []
        if b.get("capital"):
            feats.append("capital")
        if b.get("port"):
            feats.append(f"port on {w.feature_label(b['port'])}")
        for k in ("citadel", "walls", "plaza", "temple", "shanty"):
            if b.get(k):
                feats.append({"plaza": "market square", "shanty": "shanty town"}.get(k, k))
        st = w.state(b.get("state", 0)) or {}
        cap = w.burg(st.get("capital") or 0)
        made = self.eco.urban.get(b["i"], {})
        rec = self.eco.recipes.get(b["i"], {})
        market = w.markets.get(b.get("market"))
        mc = w.burg(market.get("centerBurgId")) if market else None
        return {
            "i": b["i"], "name": b["name"], "people": w.burg_people(b), "points": b.get("population"),
            "group": b.get("group"), "type": b.get("type"), "features": feats,
            "state": w.state_name(b.get("state", 0)), "province": (w.province(d["province"][c]) or {}).get("fullName"),
            "culture": w.culture(b.get("culture", 0)).get("name"), "religion": w.religion(d["religion"][c]).get("name"),
            "cell": c, "x": b["x"], "y": b["y"], "point_ref": self.g.point_ref(b["x"], b["y"]),
            "biome": w.biome_name(d["biome"][c]), "river": (w.rivers.get(d["r"][c]) or {}).get("name") if d["r"][c] else None,
            "to_capital": (math.dist((b["x"], b["y"]), (cap["x"], cap["y"])) * w.scale) if cap and cap is not b else None,
            "capital_name": cap["name"] if cap else None,
            "market": f"{mc['name']} market" if mc else None, "treasury": b.get("treasury"), "product": b.get("product"),
            "produces": [{"good": self.eco.good_name(g), "units": u, "inputs": {self.eco.good_name(k): v for k, v in rec.get(g, {}).items()},
                          "unit": (w.goods.get(g) or {}).get("unit")} for g, u in sorted(made.items(), key=lambda kv: -kv[1])],
            "buys": self._deal_summary(self.eco.buys.get(b["i"], []), "seller"),
            "sells": self._deal_summary(self.eco.sells.get(b["i"], []), "buyer"),
            "coa": self._blazon(b.get("coa")), "note": clean_note(b.get("note", "")),
            "emblem": self._emblem(b["name"]), "plan": self._town_plan(b["name"]),
        }

    @staticmethod
    def _blazon(coa):
        """A plain-words reading of Azgaar's coat-of-arms record."""
        if not isinstance(coa, dict) or not coa.get("t1"):
            return None
        parts = [coa["t1"]]
        div = coa.get("division")
        if isinstance(div, dict) and div.get("division"):
            parts.append(f"{split_camel(div['division'])} {div.get('t', '')}".strip()
                         + (f" ({div['line']})" if div.get("line") and div.get("line") != "straight" else ""))
        for o in coa.get("ordinaries") or []:
            if isinstance(o, dict):
                parts.append(f"{split_camel(o.get('ordinary', ''))} {o.get('t', '')}".strip())
        for ch in coa.get("charges") or []:
            if isinstance(ch, dict):
                parts.append(f"{split_camel(ch.get('charge', ''))} {ch.get('t', '')}".strip())
        return "; ".join(p for p in parts if p) + (f" (shield: {coa['shield']})" if coa.get("shield") else "")

    def _places(self):
        w = self.w
        self.R["burgs"] = [self._burg_card(b) for b in sorted(self.tile_burgs, key=lambda b: -(b.get("population") or 0))]
        markers = []
        for m in w.markers:
            if self.inside(m["x"], m["y"]):
                markers.append({"name": m.get("name") or split_camel(m.get("type", "")), "type": m.get("type"),
                                "note": clean_note(m.get("note", "")), "cell": m.get("cell"),
                                "point_ref": self.g.point_ref(m["x"], m["y"]), "x": m["x"], "y": m["y"],
                                "icon": m.get("icon")})
        self.R["markers"] = markers
        units = []
        for u in w.units:
            here = self.inside(u["x"], u["y"])
            base = u.get("bx") is not None and self.inside(u["bx"], u["by"])
            if here or base:
                units.append(self._unit_card(u, here, base))
        self.R["units"] = units
        near = self.near_px
        nb = []
        for b in w.live(w.burgs):
            if b.get("i") and b not in self.tile_burgs:
                dd = math.dist((self.cx, self.cy), (b["x"], b["y"]))
                if dd <= near:
                    nb.append((dd, b))
        nb.sort(key=lambda t: t[0])
        if len(nb) < 3:  # always give the closest few
            allb = sorted(((math.dist((self.cx, self.cy), (b["x"], b["y"])), b) for b in w.live(w.burgs)
                           if b.get("i") and b not in self.tile_burgs), key=lambda t: t[0])
            nb = allb[:5]
        self.R["near_burgs"] = [dict(self.where(b["x"], b["y"]), name=b["name"], people=w.burg_people(b),
                                     state=w.state_name(b.get("state", 0)), group=b.get("group"),
                                     capital=bool(b.get("capital")), port=bool(b.get("port")))
                                for _, b in nb[:12]]
        caps = sorted(((math.dist((self.cx, self.cy), (b["x"], b["y"])), b) for b in w.live(w.burgs)
                       if b.get("i") and b.get("capital")), key=lambda t: t[0])
        self.R["near_capital"] = dict(self.where(caps[0][1]["x"], caps[0][1]["y"]), name=caps[0][1]["name"],
                                      state=w.state_name(caps[0][1].get("state", 0))) if caps else None
        self.R["near_markers"] = [dict(self.where(m["x"], m["y"]), name=m.get("name") or split_camel(m.get("type", "")),
                                       type=m.get("type"))
                                  for m in sorted(w.markers, key=lambda m: math.dist((self.cx, self.cy), (m["x"], m["y"])))
                                  if not self.inside(m["x"], m["y"]) and math.dist((self.cx, self.cy), (m["x"], m["y"])) <= near * 2][:8]
        self.R["near_units"] = [dict(self.where(u["x"], u["y"]), name=u.get("name"), state=w.state_name(u["state"]),
                                     men=u.get("a"), naval=bool(u.get("n")))
                                for u in sorted(w.units, key=lambda u: math.dist((self.cx, self.cy), (u["x"], u["y"])))
                                if not self.inside(u["x"], u["y"]) and math.dist((self.cx, self.cy), (u["x"], u["y"])) <= near * 2][:8]

    def _unit_card(self, u, here, base):
        w = self.w
        return {"name": u.get("name"), "state": w.state_name(u["state"]), "men": u.get("a"),
                "naval": bool(u.get("n")), "composition": u.get("u") or {}, "here": here, "based_here": base,
                "note": clean_note(u.get("note", "")), "point_ref": self.g.point_ref(u["x"], u["y"]),
                "base_ref": self.g.point_ref(u["bx"], u["by"]) if u.get("bx") is not None else None}

    # ------------------------------------------------------------------ lines
    def _lines(self):
        w, d = self.w, self.w.d
        near = self.near_px
        big = (self.bbox[0] - near, self.bbox[1] - near, self.bbox[2] + near, self.bbox[3] + near)
        rivers, near_rivers = [], []
        names = {i: r.get("name") for i, r in w.rivers.items()}
        for rid, course in w.river_courses.items():
            pts = course["points"]
            if len(pts) < 2 or not bbox_hit(bbox_of(pts), big):
                continue
            r = w.rivers[rid]
            pieces = polyline_pieces(pts, self.poly)
            total = polyline_length(pts)
            if pieces:
                inside = sum(p[1] - p[0] for p in pieces)
                ent, ext = pieces[0][2], pieces[-1][3]
                widths = []
                if course["widths"]:
                    cum = 0.0
                    for k in range(len(pts) - 1):
                        if any(p[0] - 1e-9 <= cum <= p[1] + 1e-9 for p in pieces):
                            widths.append(course["widths"][k])
                        cum += math.dist(pts[k], pts[k + 1])
                src = r.get("source")
                mouth = r.get("mouth")
                burgs_on = [w.burg(d["burg"][c])["name"] for c in r.get("cells", []) if 0 <= c < w.n and d["burg"][c] and w.burg(d["burg"][c])]
                rivers.append({
                    "id": rid, "name": r.get("name"), "type": r.get("type"), "discharge": r.get("discharge"),
                    "width": (r.get("width") or 0) * w.scale, "length": (r.get("length") or 0) * w.scale,
                    "course": w.miles(total), "inside": w.miles(inside), "share": inside / total if total else 0,
                    "flows": compass(bearing(ext[0] - ent[0], ext[1] - ent[1]), 16) if math.dist(ent, ext) > 1e-6 else None,
                    "basin": names.get(r.get("basin")) if r.get("basin") not in (None, rid) else None,
                    "parent": names.get(r.get("parent")) if r.get("parent") not in (None, rid) else None,
                    "tributaries": [names.get(o) for o, rr in w.rivers.items() if rr.get("parent") == rid and o != rid],
                    "source": self.where(*w.site[src]) if src is not None and 0 <= src < w.n else None,
                    "mouth": dict(self.where(*w.site[mouth]), into=w.feature_label(w.cell_feature[r["cells"][-1]])
                                  if r.get("cells") and 0 <= r["cells"][-1] < w.n else None) if mouth is not None and 0 <= mouth < w.n else None,
                    "burgs": burgs_on, "drawn_width": w.miles(mean(widths)) if widths else None,
                    "course_source": course["source"]})
            else:
                dd, q = polyline_nearest((self.cx, self.cy), pts)
                if dd <= near:
                    near_rivers.append(dict(self.where(*q), name=r.get("name"), type=r.get("type"),
                                            discharge=r.get("discharge")))
        # cells under the tile that carry a river the line misses
        cell_rivers = sorted({d["r"][o["cell"]] for o in self.ov if d["r"][o["cell"]]} - {r["id"] for r in rivers})
        routes, near_routes = [], []
        for r in w.routes:
            pts = [(p[0], p[1]) for p in r["points"]]
            if len(pts) < 2 or not bbox_hit(bbox_of(pts), big):
                continue
            pieces = polyline_pieces(pts, self.poly)
            total = polyline_length(pts)
            label = r.get("name") or f"unnamed {ROUTE_KIND.get(r.get('group'), 'route')} (route {r.get('i')})"
            if pieces:
                cum, along = 0.0, []
                for k, p in enumerate(r["points"]):
                    if k:
                        cum += math.dist(pts[k - 1], pts[k])
                    cell = p[2] if len(p) > 2 else None
                    if cell is not None and 0 <= cell < w.n and d["burg"][cell] and w.burg(d["burg"][cell]):
                        along.append((cum, w.burg(d["burg"][cell])["name"]))
                s0, s1 = pieces[0][0], pieces[-1][1]
                prev = max((a for a in along if a[0] <= s0 + 1e-6), default=None, key=lambda a: a[0])
                nxt = min((a for a in along if a[0] >= s1 - 1e-6), default=None, key=lambda a: a[0])
                inside = sum(p[1] - p[0] for p in pieces)
                routes.append({"name": label, "group": r.get("group"), "length": w.miles(total), "inside": w.miles(inside),
                               "share": inside / total if total else 0,
                               "feature": w.feature_label(r["feature"]) if r.get("feature") else None,
                               "ends": (along[0][1] if along and along[0][0] < 1e-6 else None,
                                        along[-1][1] if along and abs(along[-1][0] - total) < 1e-6 else None),
                               "prev": {"name": prev[1], "dist": w.miles(s0 - prev[0])} if prev else None,
                               "next": {"name": nxt[1], "dist": w.miles(nxt[0] - s1)} if nxt else None,
                               "burgs": len({a[1] for a in along}),
                               "heading": compass(bearing(pieces[-1][3][0] - pieces[0][2][0], pieces[-1][3][1] - pieces[0][2][1]), 16)})
            else:
                dd, q = polyline_nearest((self.cx, self.cy), pts)
                if dd <= near:
                    near_routes.append(dict(self.where(*q), name=label, group=r.get("group"), length=w.miles(total)))
        near_routes.sort(key=lambda r: r["dist"])
        journeys, near_journeys = [], []
        for j in w.journeys:
            plan = JourneyPlan(w, j, self.legacy)
            miles_before = 0.0
            closest = None
            for seg in plan.segments:
                if not seg["visible"]:
                    continue
                if seg["stay"]:
                    if seg["xy"] and self.inside(*seg["xy"][0]):
                        journeys.append({"journey": plan.name, "jtype": plan.type, "segment": seg["name"], "seg_i": seg["i"],
                                         "stay": True, "hours": seg["hours"], "clock": seg["start"],
                                         "clock_text": JourneyPlan.clock_text(seg["start"]), "along": miles_before})
                    continue
                xy = seg["xy"]
                if len(xy) >= 2 and bbox_hit(bbox_of(xy), big):
                    pieces = polyline_pieces(xy, self.poly)
                    for p in pieces:
                        t0, t1 = plan.clock_at(seg, p[0]), plan.clock_at(seg, p[1])
                        inside_mi = w.miles(p[1] - p[0])
                        journeys.append({
                            "journey": plan.name, "jtype": plan.type, "segment": seg["name"], "seg_i": seg["i"],
                            "stay": False, "transport": seg["transport"], "speed_kmh": seg["speed_kmh"],
                            "speed_units": seg["speed_units"], "avoid_roads": seg["avoid_roads"], "hpd": seg["hpd"],
                            "inside": inside_mi, "seg_miles": seg["miles"], "along_in": miles_before + w.miles(p[0]),
                            "along_out": miles_before + w.miles(p[1]), "clock_in": t0, "clock_out": t1,
                            "clock_in_text": JourneyPlan.clock_text(t0), "clock_out_text": JourneyPlan.clock_text(t1),
                            "travel_hours": inside_mi / seg["speed_units"] if seg["speed_units"] else None,
                            "heading": compass(bearing(p[3][0] - p[2][0], p[3][1] - p[2][1]), 16),
                            "duration_set": seg["duration_set"]})
                    if not pieces:
                        dd, q = polyline_nearest((self.cx, self.cy), xy)
                        if dd <= near and (closest is None or dd < closest[0]):
                            closest = (dd, q, seg)
                miles_before += seg["miles"]
            if closest and not any(x["journey"] == plan.name for x in journeys):
                near_journeys.append(dict(self.where(*closest[1]), journey=plan.name, segment=closest[2]["name"]))
        self.R["rivers"], self.R["near_rivers"], self.R["cell_rivers"] = rivers, near_rivers, [
            {"name": w.rivers.get(r, {}).get("name"), "id": r} for r in cell_rivers]
        self.R["routes"], self.R["near_routes"] = routes, near_routes[:8]
        self.R["journeys"], self.R["near_journeys"] = journeys, near_journeys

    # ------------------------------------------------------------------ trade
    def _trade(self):
        w, d, eco = self.w, self.w.d, self.eco
        rural = defaultdict(float)
        urban = defaultdict(float)
        st_attr = defaultdict(lambda: defaultdict(float))
        mk_attr = defaultdict(lambda: defaultdict(float))
        for o in self.ov:
            c = o["cell"]
            for g, v in eco.rural[c].items():
                val = v * o["of_cell"]
                rural[g] += val
                st_attr[d["state"][c]][g] += val
                if d["market"][c]:
                    mk_attr[d["market"][c]][g] += val
        for b in self.tile_burgs:
            for g, v in eco.urban.get(b["i"], {}).items():
                urban[g] += v
                st_attr[b.get("state", 0)][g] += v
                if b.get("market"):
                    mk_attr[b["market"]][g] += v
        mk_share = defaultdict(float)
        for o in self.ov:
            if d["market"][o["cell"]]:
                mk_share[d["market"][o["cell"]]] += o["of_tile"]
        main_market = max(mk_share, key=mk_share.get) if mk_share else None
        goods = []
        for g in sorted(set(rural) | set(urban), key=lambda g: -((rural[g] + urban[g]) * (w.goods.get(g, {}).get("value") or 1))):
            total = rural[g] + urban[g]
            if total < 0.005:
                continue
            gd = w.goods.get(g, {})
            shares = []
            for sid, made in st_attr.items():
                if made.get(g) and eco.by_state[sid].get(g):
                    shares.append({"of": w.state_name(sid), "kind": "state", "share": made[g] / eco.by_state[sid][g]})
            for mid, made in mk_attr.items():
                if made.get(g) and eco.by_market[mid].get(g):
                    m = w.markets.get(mid)
                    cb = w.burg(m.get("centerBurgId")) if m else None
                    shares.append({"of": f"{cb['name']} market" if cb else f"market {mid}", "kind": "market",
                                   "share": made[g] / eco.by_market[mid][g]})
            price = stock = None
            if main_market and main_market in w.markets:
                rec = (w.markets[main_market].get("goods") or {}).get(str(g)) or {}
                price, stock = rec.get("price"), rec.get("stock")
            exports = Counter()
            if main_market:
                for dl in eco.flows.get(main_market, []):
                    if dl["good"] == g and dl["seller"] == main_market:
                        m = w.markets.get(dl["buyer"])
                        cb = w.burg(m.get("centerBurgId")) if m else None
                        exports[cb["name"] if cb else f"market {dl['buyer']}"] += dl["units"]
            goods.append({"id": g, "name": gd.get("name", f"good {g}"), "unit": gd.get("unit"), "tags": gd.get("tags") or [],
                          "value": gd.get("value"), "rural": rural[g], "urban": urban[g], "total": total,
                          "world_share": total / eco.world[g] if eco.world.get(g) else None, "shares": shares,
                          "price": price, "stock": stock, "mean_price": eco.mean_price.get(g),
                          "exports": exports.most_common(4), "distribution": gd.get("distribution")})
        deposits = defaultdict(float)
        for o in self.ov:
            gid = d["good"][o["cell"]]
            if gid:
                deposits[gid] += o["of_tile"]
        markets = []
        for mid, share in sorted(mk_share.items(), key=lambda kv: -kv[1]):
            m = w.markets.get(mid)
            if not m:
                continue
            cb = w.burg(m.get("centerBurgId"))
            ex, im = Counter(), Counter()
            partners_ex, partners_im = defaultdict(Counter), defaultdict(Counter)
            for dl in eco.flows.get(mid, []):
                v = dl["units"] * dl["price"]
                if dl["seller"] == mid:
                    ex[dl["good"]] += v
                    pm = w.markets.get(dl["buyer"])
                    pb = w.burg(pm.get("centerBurgId")) if pm else None
                    partners_ex[dl["good"]][pb["name"] if pb else str(dl["buyer"])] += v
                else:
                    im[dl["good"]] += v
                    pm = w.markets.get(dl["seller"])
                    pb = w.burg(pm.get("centerBurgId")) if pm else None
                    partners_im[dl["good"]][pb["name"] if pb else str(dl["seller"])] += v
            nburgs = sum(1 for b in w.live(w.burgs) if b.get("i") and b.get("market") == mid)
            markets.append({"id": mid, "share": share, "centre": dict(self.where(cb["x"], cb["y"]), name=cb["name"]) if cb else None,
                            "burgs": nburgs, "cells": sum(1 for c in range(w.n) if d["market"][c] == mid),
                            "exports": [(eco.good_name(g), v, partners_ex[g].most_common(1)[0][0]) for g, v in ex.most_common(6)],
                            "imports": [(eco.good_name(g), v, partners_im[g].most_common(1)[0][0]) for g, v in im.most_common(6)],
                            "export_value": sum(ex.values()), "import_value": sum(im.values())})
        buys, sells = [], []
        for b in self.tile_burgs:
            buys += self.eco.buys.get(b["i"], [])
            sells += self.eco.sells.get(b["i"], [])
        self.R["trade"] = {"goods": goods, "deposits": [{"good": eco.good_name(g), "share": s} for g, s in deposits.items()],
                           "markets": markets, "main_market": main_market,
                           "buys": self._deal_summary(buys, "seller"), "sells": self._deal_summary(sells, "buyer"),
                           "value": sum((x["total"]) * (x["value"] or 0) for x in goods)}

    # ------------------------------------------------------------------ cells
    def _cells_table(self):
        w, d = self.w, self.w.d
        rows = []
        for o in self.ov:
            c = o["cell"]
            rows.append({"cell": c, "of_tile": o["of_tile"], "of_cell": o["of_cell"], "type": w.cell_type[c],
                         "rural": d["pop"][c] * o["of_cell"] * w.pop_scale, "cell_rural": d["pop"][c] * w.pop_scale,
                         "biome": w.biome_name(d["biome"][c]), "state": w.state_name(d["state"][c]) if not w.water[c] else "",
                         "province": ((w.province(d["province"][c]) or {}).get("name") or "") if not w.water[c] else "",
                         "culture": w.culture(d["culture"][c]).get("name", "") if not w.water[c] else "",
                         "religion": w.religion(d["religion"][c]).get("name", "") if not w.water[c] else "",
                         "market": d["market"][c], "feature": w.feature_label(w.cell_feature[c]),
                         "height": w.cell_height_disp[c], "river": d["r"][c], "flux": d["fl"][c], "conf": d["conf"][c],
                         "suit": d["s"][c], "good": self.eco.good_name(d["good"][c]) if d["good"][c] else "",
                         "zones": [z.get("name") for z in w.zones if c in w.zone_cells[z["i"]]],
                         "area": w.sq(w.cell_area[c])})
        self.R["cells"] = rows


# ====================================================================== LaTeX output
_LATEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                  "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
_LATEX_UNICODE = {"°": r"\textdegree{}", "²": r"\textsuperscript{2}", "³": r"\textsuperscript{3}", "—": "---",
                  "–": "--", "’": "'", "‘": "`", "“": "``", "”": "''", "×": r"$\times$", "…": r"\ldots{}",
                  "·": r"\textperiodcentered{}", "→": r"$\rightarrow$", "←": r"$\leftarrow$", "±": r"$\pm$",
                  "≈": r"$\approx$", "½": r"\textonehalf{}", "¼": r"\textonequarter{}", "¾": r"\textthreequarters{}",
                  "\u00a0": "~", "ø": r"\o{}", "Ø": r"\O{}", "æ": r"\ae{}", "Æ": r"\AE{}", "ß": r"\ss{}",
                  "œ": r"\oe{}", "Œ": r"\OE{}", "ð": r"\dh{}", "þ": r"\th{}", "Þ": r"\TH{}", "Ð": r"\DH{}",
                  "ı": r"\i{}", "ł": r"\l{}", "Ł": r"\L{}", "đ": r"\dj{}", "Đ": r"\DJ{}"}


def tex(s):
    """Escape text for pdfLaTeX (T1 + utf8). Characters outside Latin-1 and Latin Extended-A are
    reduced to their base letters, and symbols such as emoji are dropped."""
    if s is None:
        return ""
    out = []
    for ch in str(s):
        if ch in _LATEX_SPECIAL:
            out.append(_LATEX_SPECIAL[ch])
        elif ch in _LATEX_UNICODE:
            out.append(_LATEX_UNICODE[ch])
        elif ord(ch) < 128:
            out.append(ch)
        elif 0xC0 <= ord(ch) <= 0x17F and unicodedata.category(ch).startswith("L"):
            out.append(ch)
        elif ch in "¡¿«»":
            out.append(ch)
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch) if ord(c) < 128 and not unicodedata.combining(c))
            out.append(base)
    return re.sub(r"\s+", " ", "".join(out)).strip() if "\n" not in str(s) else "".join(out)


def texp(s):
    """Escape a multi-line note, keeping its paragraphs."""
    return "\n\n".join(tex(p) for p in str(s).split("\n") if p.strip())


DATA, MIXED = r"\tagdata{}", r"\tagmixed{}"


class LatexReport:
    def __init__(self, tile: Tile, title_page=False, paper="letterpaper"):
        self.t, self.w, self.g, self.R = tile, tile.w, tile.g, tile.R
        self.title_page = title_page
        self.paper = paper
        self.lines = []
        self.area_no = {}

    # ------------------------------------------------------------ formatting
    def d(self, mi, dec=1):
        return f"{fnum(mi, dec)} {tex(self.w.unit)}"

    def a(self, sq, dec=1):
        unit = self.w.area_label()
        return f"{fnum(sq, dec)} {tex(unit)}"

    def h(self, metres):
        if metres is None:
            return "n/a"
        v = self.w.height_disp(metres)
        return f"{fnum(v, 0)} {tex(self.w.h_unit)}"

    def t_(self, c):
        return tex(self.w.temp_text(c))

    def ts(self, c):
        """Short temperature in the map's unit only."""
        return "n/a" if c is None else tex(f"{self.w.temp_disp(c):.0f}{self.w.t_unit}")

    def where(self, wd):
        return f"{self.d(wd['dist'])} {wd['dir']} (\\textsf{{{tex(wd['ref'])}}})"

    def ref(self, r):
        return f"\\textsf{{{tex(r)}}}"

    def add(self, *s):
        self.lines.extend(re.sub(r"(?<!\\)%", r"\\%", x) for x in s)

    def table(self, header, spec, rows, chunk=22, plain=False):
        """A DndTable. Its first row takes the header style; plain=True sets it back to body text."""
        if not rows:
            return
        for k in range(0, len(rows), chunk):
            part = list(rows[k:k + chunk])
            if plain:
                part[0] = r"\rowstyle{\mdseries\DndFontTableBody}" + part[0]
            h = header if k == 0 else header + " (cont.)"
            self.add(f"\\begin{{DndTable}}[header={{{h}}}]{{{spec}}}")
            self.add(" \\\\\n".join(part))
            self.add("\\end{DndTable}", "")

    def kv(self, header, pairs, chunk=24):
        rows = [f"\\textbf{{{k}}} & {v}" for k, v in pairs if v not in (None, "")]
        self.table(header, "lX", rows, chunk, plain=True)

    def comment(self, title, text):
        self.add(f"\\begin{{DndComment}}{{{title}}}", text, "\\end{DndComment}", "")

    # ------------------------------------------------------------ maps (TikZ)
    def _win(self, half_tiles):
        g, w = self.g, self.w
        r = half_tiles * max(g.step_x, g.step_y) + g.hw
        x0, x1 = self.t.cx - r, self.t.cx + r
        y0, y1 = self.t.cy - r * 0.8, self.t.cy + r * 0.8
        if x1 - x0 > w.W:
            x0, x1 = 0, w.W
        else:
            x0, x1 = max(0, min(x0, w.W - (x1 - x0))), min(w.W, max(x1, x1 - x0))
        if y1 - y0 > w.H:
            y0, y1 = 0, w.H
        else:
            hgt = y1 - y0
            y0 = max(0, min(y0, w.H - hgt))
            y1 = y0 + hgt
        return x0, y0, x1, y1

    def tikz(self, win, width_cm, local=True):
        w, g, t, d = self.w, self.g, self.t, self.w.d
        x0, y0, x1, y1 = win
        k = width_cm / (x1 - x0)
        hcm = (y1 - y0) * k

        def P(x, y):
            return f"({(x - x0) * k:.2f},{(y1 - y) * k:.2f})"

        def ring_path(pts):
            out, last = [], None
            for x, y in pts:
                q = ((x - x0) * k, (y1 - y) * k)
                if last is None or abs(q[0] - last[0]) + abs(q[1] - last[1]) > 0.025:
                    out.append(f"({q[0]:.2f},{q[1]:.2f})")
                    last = q
            return " -- ".join(out) + " -- cycle" if len(out) >= 3 else ""

        def simple(pts, tol=0.03):
            out, last = [], None
            for n_, (x, y) in enumerate(pts):
                q = ((x - x0) * k, (y1 - y) * k)
                if last is None or n_ == len(pts) - 1 or abs(q[0] - last[0]) + abs(q[1] - last[1]) > tol:
                    out.append(f"({q[0]:.2f},{q[1]:.2f})")
                    last = q
            return out

        def runs(pts):
            res, cur = [], []
            for a in range(len(pts) - 1):
                p, q = pts[a], pts[a + 1]
                bb = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
                if bbox_hit(bb, win):
                    if not cur:
                        cur = [p]
                    cur.append(q)
                elif cur:
                    res.append(cur)
                    cur = []
            if cur:
                res.append(cur)
            out = []
            for r in res:
                sp = simple(r)
                if len(sp) >= 2:
                    out.append(" -- ".join(sp))
            return out

        L = [r"\begin{tikzpicture}[x=1cm,y=1cm,font=\sffamily]"]
        L.append(r"\begin{scope}")
        L.append(f"\\clip (0,0) rectangle ({width_cm:.2f},{hcm:.2f});")
        L.append(f"\\fill[mapwater] (0,0) rectangle ({width_cm:.2f},{hcm:.2f});")
        rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        land_paths, lake_paths, lakeisle_paths = [], [], []
        for fid, rings in w.feature_rings.items():
            f = w.feature(fid) or {}
            for r, bb in rings:
                if not bbox_hit(bb, win):
                    continue
                cl = clip_convex(r, rect)
                if poly_area(cl) <= 0:
                    continue
                pth = ring_path(cl)
                if not pth:
                    continue
                if f.get("type") == "lake":
                    lake_paths.append(pth)
                elif f.get("subtype") == "lake_island":
                    lakeisle_paths.append(pth)
                elif f.get("land"):
                    land_paths.append(pth)
        cells = [c for c in w.cell_index.query(win) if not w.water[c] and bbox_hit(w.cell_bbox[c], win)]
        colors = {}
        for c in cells:
            colors.setdefault(d["biome"][c], (w.biomes[d["biome"][c]] or {}).get("color", "#cccccc"))
        for bid, col in colors.items():
            L.append(f"\\definecolor{{biome{bid}}}{{HTML}}{{{col.lstrip('#').upper()[:6]}}}")
        if land_paths:
            L.append(r"\begin{scope}")
            L.append("\\clip " + " ".join(land_paths) + ";")
        by_biome = defaultdict(list)
        if len(cells) <= 350:  # above that the picture grows too large for TeX: plain land instead
            for c in cells:
                pth = ring_path(clip_convex(w.cell_poly[c], rect))
                if pth:
                    by_biome[d["biome"][c]].append(pth)
        else:
            L.append(f"\\fill[mapland] (0,0) rectangle ({width_cm:.2f},{hcm:.2f});")
        for bid, paths in by_biome.items():
            L.append(f"\\fill[biome{bid}!55!white] " + " ".join(paths) + ";")
        if land_paths:
            L.append(r"\end{scope}")
            for pth in land_paths:
                L.append(f"\\draw[mapcoast,line width=0.35pt] {pth};")
        for pth in lake_paths:
            L.append(f"\\filldraw[fill=mapwater,draw=mapcoast,line width=0.3pt] {pth};")
        for pth in lakeisle_paths:
            L.append(f"\\fill[biome{next(iter(colors), 0)}] {pth};" if colors else "")
        # state and province borders, chained into lines
        st_segs, pv_segs = [], []
        for a, b, p, q in w.edges:
            if w.water[a] or w.water[b]:
                continue
            bb = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
            if not bbox_hit(bb, win):
                continue
            if d["state"][a] != d["state"][b]:
                st_segs.append((p, q))
            elif local and d["province"][a] != d["province"][b]:
                pv_segs.append((p, q))
        for segs, style in ((pv_segs, "mapstate,line width=0.3pt,dash pattern=on 1pt off 1pt"),
                            (st_segs, "mapstate,line width=0.9pt,dash pattern=on 2pt off 1pt")):
            lines_ = [" -- ".join(simple(ch)) for ch in chain_segments(segs)]
            lines_ = [x for x in lines_ if "--" in x]
            if lines_:
                L.append(f"\\draw[{style}] " + " ".join(lines_) + ";")
        # rivers, routes, journeys
        for rid, course in w.river_courses.items():
            pts = course["points"]
            if len(pts) >= 2 and bbox_hit(bbox_of(pts), win):
                disc = (w.rivers[rid].get("discharge") or 10)
                lw = min(1.4, 0.3 + 0.12 * math.log10(max(disc, 1)) * 2)
                for r in runs(pts):
                    L.append(f"\\draw[mapriver,line width={lw:.2f}pt] {r};")
        for r in w.routes:
            pts = [(p[0], p[1]) for p in r["points"]]
            if len(pts) >= 2 and bbox_hit(bbox_of(pts), win):
                style = {"roads": "maproad,line width=0.7pt", "trails": "maproad,line width=0.4pt,dash pattern=on 1.5pt off 1pt",
                         "searoutes": "mapsea,line width=0.4pt,dash pattern=on 0.5pt off 1pt"}.get(r.get("group"), "maproad,line width=0.4pt")
                for rr in runs(pts):
                    L.append(f"\\draw[{style}] {rr};")
        for j in w.journeys:
            for s in j.get("segments", []):
                pts = [(p[0], p[1]) for p in s.get("points", [])]
                if len(pts) >= 2 and bbox_hit(bbox_of(pts), win) and s.get("visible", True) is not False:
                    for rr in runs(pts):
                        L.append(f"\\draw[mapjourney,line width=1.1pt,opacity=0.85] {rr};")
        # the tile grid
        if local:
            span_i = int((x1 - x0) / g.step_x) + 3
            span_j = int((y1 - y0) / g.step_y) + 3
            ci, cj = t.i, t.j
            for ii in range(ci - span_i, ci + span_i + 1):
                for jj in range(cj - span_j, cj + span_j + 1):
                    cx, cy = g.center(ii, jj)
                    if not (x0 - g.hw <= cx <= x1 + g.hw and y0 - g.hh <= cy <= y1 + g.hh) or not g.exists(ii, jj):
                        continue
                    L.append(f"\\draw[mapgrid,line width=0.25pt] {ring_path(g.poly(ii, jj))};")
                    e, n = g.en(ii, jj)
                    if g.width_px * k >= 0.55:
                        lab = f"{e % g.block:0{g.digits}d}\\,{n % g.block:0{g.digits}d}"
                        L.append(f"\\node[mapgridtext,font=\\sffamily\\fontsize{{3.6}}{{4}}\\selectfont] at {P(cx, cy + g.hh * 0.55)} {{{lab}}};")
        else:
            self._tikz_os_lines(L, win, k, P, hcm, width_cm)
        L.append(f"\\draw[maptarget,line width=1.2pt] {ring_path(t.poly)};")
        if not local:
            L.append(f"\\draw[maptarget,line width=0.8pt] {P(t.cx, t.cy)} circle (0.16);")
        # burgs and markers
        burgs = [b for b in w.live(w.burgs) if b.get("i") and x0 <= b["x"] <= x1 and y0 <= b["y"] <= y1]
        burgs = sorted(burgs, key=lambda b: (-(b.get("capital") or 0), -(b.get("population") or 0)))
        labelled = {b["i"] for b in burgs[:14 if local else 18]}
        if not local:
            burgs = burgs[:18]
        for b in burgs:
            num = self.area_no.get(("burg", b["i"]))
            r = 0.07 if b.get("capital") else 0.045
            L.append(f"\\filldraw[fill=white,draw=black,line width=0.4pt] {P(b['x'], b['y'])} circle ({r});")
            if b["i"] not in labelled:
                continue
            label = tex(b["name"]) + (f" [{num}]" if num else "")
            L.append(f"\\node[anchor=west,font=\\sffamily\\fontsize{{4.5}}{{5}}\\selectfont,inner sep=1pt,fill=white,"
                     f"fill opacity=0.6,text opacity=1] at {P(b['x'] + 3 / k * 0.02, b['y'])} {{{label}}};")
        if local:
            for m in w.markers:
                if x0 <= m["x"] <= x1 and y0 <= m["y"] <= y1:
                    num = self.area_no.get(("marker", m.get("i")))
                    L.append(f"\\node[mapmarker,regular polygon,regular polygon sides=3,inner sep=0.7pt,fill=mapmarker,draw=black,line width=0.2pt] at {P(m['x'], m['y'])} {{}};")
                    if num and len(self.R["markers"]) <= 12:
                        L.append(f"\\node[anchor=south,font=\\sffamily\\bfseries\\fontsize{{4.5}}{{5}}\\selectfont] at {P(m['x'], m['y'])} {{[{num}]}};")
        L.append(r"\end{scope}")
        L.append(f"\\draw[line width=0.5pt] (0,0) rectangle ({width_cm:.2f},{hcm:.2f});")
        # scale bar
        target = (x1 - x0) * w.scale / 4
        mag = 10 ** math.floor(math.log10(target)) if target > 0 else 1
        bar = max(v * mag for v in (1, 2, 5) if v * mag <= target) if target >= mag else mag
        bl = bar / w.scale * k
        L.append(f"\\fill[white,opacity=0.7] (0.15,0.12) rectangle ({0.35 + bl:.2f},0.42);")
        L.append(f"\\draw[line width=0.6pt] (0.25,0.2) -- ({0.25 + bl:.2f},0.2);")
        L.append(f"\\node[font=\\sffamily\\fontsize{{4.5}}{{5}}\\selectfont,anchor=south] at ({0.25 + bl / 2:.2f},0.2) {{{fnum(bar, 0)} {tex(w.unit)}}};")
        L.append(r"\end{tikzpicture}")
        return "\n".join(x for x in L if x)

    def _tikz_os_lines(self, L, win, k, P, hcm, wcm):
        g = self.g
        x0, y0, x1, y1 = win
        eo = 0.25 if g.kind == "pointyHex" else 0.0
        no = 0.25 if g.kind == "flatHex" else 0.0
        step = 10 if g.block >= 100 else 1
        e_lo = math.floor((x0 - g.x_origin) / g.step_x / step) * step
        e_hi = math.ceil((x1 - g.x_origin) / g.step_x / step) * step
        n_lo = math.floor((g.y_origin - y1) / g.step_y / step) * step
        n_hi = math.ceil((g.y_origin - y0) / g.step_y / step) * step
        for e in range(e_lo, e_hi + 1, step):
            x = g.x_origin + (e + eo) * g.step_x
            if x0 <= x <= x1:
                major = e % g.block == 0
                L.append(f"\\draw[mapos,line width={0.6 if major else 0.2}pt] {P(x, y0)} -- {P(x, y1)};")
                L.append(f"\\node[font=\\sffamily\\fontsize{{4}}{{4}}\\selectfont,anchor=north,inner sep=1pt] at {P(x, y0)} {{{e % g.block:0{g.digits}d}}};")
        for n in range(n_lo, n_hi + 1, step):
            y = g.y_origin - (n + no) * g.step_y
            if y0 <= y <= y1:
                major = n % g.block == 0
                L.append(f"\\draw[mapos,line width={0.6 if major else 0.2}pt] {P(x0, y)} -- {P(x1, y)};")
                L.append(f"\\node[font=\\sffamily\\fontsize{{4}}{{4}}\\selectfont,anchor=west,inner sep=1pt] at {P(x0, y)} {{{n % g.block:0{g.digits}d}}};")
        for be in range(max(0, e_lo // g.block), e_hi // g.block + 1):
            for bn in range(max(0, n_lo // g.block), n_hi // g.block + 1):
                if be >= len(LETTERS) or bn >= len(LETTERS):
                    continue
                xc = g.x_origin + (be * g.block + g.block / 2) * g.step_x
                yc = g.y_origin - (bn * g.block + g.block / 2) * g.step_y
                xc, yc = min(max(xc, x0 + 0.08 * (x1 - x0)), x1 - 0.08 * (x1 - x0)), min(max(yc, y0 + 0.08 * (y1 - y0)), y1 - 0.08 * (y1 - y0))
                inside_x = g.x_origin + be * g.block * g.step_x <= xc <= g.x_origin + (be + 1) * g.block * g.step_x
                inside_y = g.y_origin - (bn + 1) * g.block * g.step_y <= yc <= g.y_origin - bn * g.block * g.step_y
                if inside_x and inside_y:
                    L.append(f"\\node[mapos,font=\\sffamily\\bfseries\\fontsize{{14}}{{14}}\\selectfont,opacity=0.45] at {P(xc, yc)} {{{LETTERS[be]}{LETTERS[bn]}}};")

    # ------------------------------------------------------------ document
    def render(self):
        R, w, g, t = self.R, self.w, self.g, self.t
        loc = R["location"]
        no = 0
        for b in R["burgs"]:
            no += 1
            self.area_no[("burg", b["i"])] = no
        for m in R["markers"]:
            no += 1
            mk = next((x for x in w.markers if x.get("name") == m["name"] and x.get("cell") == m["cell"]), None)
            if mk is not None:
                self.area_no[("marker", mk.get("i"))] = no
        self.add(r"\documentclass[" + self.paper + r",twocolumn,openany,nodeprecatedcode]{dndbook}",
                 r"\usepackage[english]{babel}", r"\usepackage[utf8]{inputenc}",
                 r"\usepackage[singlelinecheck=false]{caption}", r"\usepackage{stfloats}", r"\usepackage{graphicx}",
                 r"\usepackage{textcomp}", r"\usepackage{tikz}", r"\usetikzlibrary{shapes.geometric}",
                 r"\captionsetup[table]{labelformat=empty,font={sf,sc,bf,},skip=0pt}",
                 r"\newcommand{\tagdata}{\textsc{\footnotesize(data)}}",
                 r"\newcommand{\tagmixed}{\textsc{\footnotesize(mixed)}}",
                 r"\definecolor{mapwater}{HTML}{C8DDEB}", r"\definecolor{mapcoast}{HTML}{4A6B80}",
                 r"\definecolor{mapriver}{HTML}{2B7BB9}", r"\definecolor{maproad}{HTML}{8B3A1A}",
                 r"\definecolor{mapsea}{HTML}{1F4E79}", r"\definecolor{mapstate}{HTML}{6A1B4D}",
                 r"\definecolor{mapjourney}{HTML}{E07B00}", r"\definecolor{mapgrid}{HTML}{555555}",
                 r"\definecolor{mapgridtext}{HTML}{333333}", r"\definecolor{maptarget}{HTML}{C0141B}",
                 r"\definecolor{mapos}{HTML}{1A3A6B}", r"\definecolor{mapmarker}{HTML}{F2C200}",
                 r"\definecolor{mapland}{HTML}{E4E9C8}",
                 r"\tikzset{mapgridtext/.style={text=mapgridtext}, mapmarker/.style={}}",
                 f"\\title{{{tex(loc['ref'])} \\\\ \\large A {tex(loc['kind'])} of {tex(w.name)}"
                 + (f", {w.year} {tex(w.era_short)}" if w.year is not None else "") + "}",
                 f"\\author{{azgaar\\_tiles.py {TOOL_VERSION}, from {tex(w.map_path.name)}}}", r"\date{}",
                 r"\begin{document}")
        if self.title_page:
            self.add(r"\frontmatter", r"\maketitle", r"\tableofcontents", r"\mainmatter")
        self._intro()
        self._maps()
        self._location()
        self._land()
        self._people()
        self._rulers()
        self._places()
        self._lines()
        self._trade()
        self._appendix()
        self.add(r"\end{document}")
        return "\n".join(self.lines) + "\n"

    def _intro(self):
        R, w = self.R, self.w
        loc = R["location"]
        st = next((s for s in R["states"] if s.get("id")), None)
        pr = R["provinces"][0] if R["provinces"] else None
        biome = R["terrain"]["biomes"][0]["name"] if R["terrain"]["biomes"] else None
        land = loc["land_share"]
        self.add(f"\\chapter{{{tex(loc['ref'])}}}")
        first = (f"he {tex(loc['kind'])} \\textsf{{{tex(loc['ref'])}}}")
        rest = (f" is {self.d(loc['width'])} across and covers {self.a(loc['area'])} of {tex(w.name)}"
                + (f", read for the year {w.year} {tex(w.era)}" if w.year is not None else "") + ". ")
        where = []
        if pr:
            where.append(f"It lies in the {tex(pr['full'])}")
            if st:
                where[-1] += f" of the {tex(st['full'])}"
        elif st:
            where.append(f"It lies in the {tex(st['full'])}")
        elif land < 0.5:
            water = next((f["label"] for f in loc["features"] if f["type"] in ("ocean", "lake")), "open water")
            where.append(f"It lies on {tex(water)}")
        if loc["features"]:
            land_f = next((f["label"] for f in loc["features"] if f["type"] == "island"), None)
            if land_f and land >= 0.5:
                where.append(f"on {tex(land_f)}")
        sentence = ", ".join(where) + "." if where else ""
        tail = []
        if biome and land > 0:
            tail.append(f"Most of its land is {tex(biome.lower())}")
        ppl = R["people"]["total"]
        tail.append(f"about {fnum(ppl, 0)} people live here")
        if R["burgs"]:
            names = [tex(b["name"]) for b in R["burgs"]]
            if len(names) <= 4:
                tail.append("it holds " + ", ".join(names))
            else:
                tail.append(f"it holds {len(names)} burgs, the largest {', '.join(names[:3])}")
        self.add(f"\\DndDropCapLine{{T}}{{{first}}}{rest}{sentence} " + "; ".join(tail) + ".", "")
        # at a glance
        pairs = [("Reference", self.ref(loc["ref"])), ("Square", f"{loc['square']} (100 x 100 tiles)" if self.g.block == 100 else loc["square"]),
                 ("Centre", f"{fnum(abs(loc['lat']), 2)}\\textdegree{{}} {'N' if loc['lat'] >= 0 else 'S'}, "
                            f"{fnum(abs(loc['lon']), 2)}\\textdegree{{}} {'E' if loc['lon'] >= 0 else 'W'}"),
                 ("Land", fpct(loc["land_share"])), ("State", tex(st["name"]) if st else "none"),
                 ("Province", tex(pr["name"]) if pr else "none"),
                 ("People", fnum(R["people"]["total"], 0)),
                 ("Culture", tex(R["cultures"][0]["name"]) if R["cultures"] else "none"),
                 ("Faith", tex(R["religions"][0]["name"]) if R["religions"] else "none"),
                 ("Elevation", self.h(R["terrain"]["elev_mean"])), ("Temperature", self.t_(R["climate"]["temp_mean"])),
                 ("Zones", tex(", ".join(z["name"] for z in R["zones"])) or "none")]
        body = " \\\\\n".join(f"\\textbf{{{k}:}} {v}" for k, v in pairs)
        self.add(r"\begin{DndSidebar}[float=!b]{At a Glance}", body, r"\end{DndSidebar}", "")

    def _maps(self):
        g = self.g
        self.add(r"\section{Maps}")
        lw, rw = self._win(4.5), self._win(28)
        local = self.tikz(lw, 8.2, local=True)
        self.add(r"\begin{center}", local, r"\end{center}",
                 f"\\textit{{The tile (red) and its neighbours, each labelled with its eastings and northings in "
                 f"square {tex(self.R['location']['square'])}. Burgs and markers in the tile carry their area numbers.}}", "")
        if (rw[2] - rw[0]) > 1.5 * (lw[2] - lw[0]):
            region = self.tikz(rw, 8.2, local=False)
            self.add(r"\begin{center}", region, r"\end{center}",
                     f"\\textit{{The region, with grid lines every 10 tiles and the lettered squares of the reference system.}} {DATA}", "")

    def _location(self):
        R, w, g = self.R, self.w, self.g
        loc = R["location"]
        self.add(r"\section{Location}")
        nb = ", ".join(f"{n['dir']} {self.ref(n['ref'])}" for n in loc["neighbours"] if n["exists"])
        self.kv(f"The Tile {DATA}", [
            ("Grid reference", self.ref(loc["ref"])), ("Typed short", self.ref(loc["ref_compact"])),
            ("Centre as a point", self.ref(loc["point_ref"])),
            ("Easting, northing", f"{loc['easting']}, {loc['northing']} tiles from the south-west corner"),
            ("Shape", f"{tex(loc['kind'])}, {self.d(loc['width'], 2)} across, {self.a(loc['area'])}"),
            ("On the map", fpct(loc["on_map"]) if loc["on_map"] < 0.999 else None),
            ("Centre (map px)", f"{fnum(loc['center_px'][0], 1)}, {fnum(loc['center_px'][1], 1)}"),
            ("Latitude", f"{fnum(abs(loc['lat']), 3)}\\textdegree{{}} {'N' if loc['lat'] >= 0 else 'S'}"),
            ("Longitude", f"{fnum(abs(loc['lon']), 3)}\\textdegree{{}} {'E' if loc['lon'] >= 0 else 'W'}"),
            ("Place on the map", f"{fpct(loc['pos'][0])} from the west edge, {fpct(loc['pos'][1])} from the north"),
            ("Neighbours", nb)])
        rows = [f"{tex(f['label'])} & {fpct(f['share'])} & {self.a(f['area'], 0)}" for f in loc["features"]]
        self.table(f"Land and Water {DATA}", "Xrr", ["\\textbf{Feature} & \\textbf{Tile} & \\textbf{Feature area}"] + rows)
        lines = [f"Land covers {fpct(loc['land_share'])} of the tile by cell outlines"]
        if loc["drawn_land"] is not None:
            lines[-1] += f" and {fpct(loc['drawn_land'])} by Azgaar's drawn coastline {MIXED}"
        lines[-1] += "."
        if loc["coast_len"] > 0:
            lines.append(f"About {self.d(loc['coast_len'])} of coastline (cell edges) runs through it {DATA}.")
        elif loc["coast"]:
            lines.append(f"The nearest coast, on {tex(loc['coast']['water'])}, is {self.where(loc['coast'])} {DATA}.")
        cap = R.get("near_capital")
        if cap:
            lines.append(f"The nearest capital is {tex(cap['name'])} ({tex(cap['state'])}), {self.where(cap)} {DATA}.")
        self.add(" ".join(lines), "")

    def _land(self):
        R, w = self.R, self.w
        te, cl, cx = R["terrain"], R["climate"], R["context"]
        self.add(r"\section{Land and Climate}")
        hs = te["h_samples"]
        self.kv("Terrain", [
            ("Elevation", (f"{self.h(te['elev_mean'])} mean, {self.h(te['elev_min'])} to {self.h(te['elev_max'])} {DATA}"
                           if te['elev_min'] != te['elev_max'] else f"{self.h(te['elev_mean'])} {DATA}")),
            ("Grid cells sampled", f"{te['grid_cells']} (height{'s ' + str(hs[0]) + ' to ' + str(hs[1]) if hs[0] != hs[1] else ' ' + str(hs[0])} "
                                   f"on Azgaar's 0--100 scale) {DATA}"),
            ("At the centre", f"{self.h(te['elev_idw'])}, weighted from nearby grid points {MIXED}" if te["elev_idw"] is not None else None),
            ("Cell height", f"{fnum(te['pack_height'], 0)} {tex(w.h_unit)} (cells under the tile, by area) {DATA}" if te["pack_height"] is not None else None),
            ("Ice", ", ".join(f"{tex(i['type'])} {fpct(i['share'])}" for i in te["ice"]) if te["ice"] else None)])
        rows = ["\\textbf{Biome} & \\textbf{Tile} & \\textbf{State} & \\textbf{Hab.} & \\textbf{Cost}"]
        for b in te["biomes"]:
            rows.append(f"{tex(b['name'])} & {fpct(b['share'])} & {fpct(b['state_share']) if b['state_share'] is not None else '--'} & "
                        f"{b['habitability'] if b['habitability'] is not None else '--'} & {b['cost'] if b['cost'] is not None else '--'}")
        self.table(f"Biomes {DATA}", "Xrrrr", rows)
        wind = cl["wind"]
        self.kv("Climate", [
            ("Mean temperature", f"{self.t_(cl['temp_mean'])} (grid cells: {self.t_(cl['temp_min'])} to {self.t_(cl['temp_max'])}) {DATA}"),
            ("At the centre", f"{self.t_(cl['temp_idw'])} {MIXED}" if cl["temp_idw"] is not None else None),
            ("Feels like", f"{tex(cl['likeness'])} (Azgaar's likeness table) {DATA}" if cl["likeness"] else None),
            ("Precipitation", f"{fnum(cl['prec_mean'], 0)} mm a year (Azgaar's display rule) {DATA}"),
            ("Prevailing wind", f"from the {wind['from']} (setting {fnum(wind['setting'], 0)}\\textdegree{{}} for this latitude band) {DATA}" if wind else None),
            ("Day length", f"{fnum(cl['day_long'], 1)} h at midsummer, {fnum(cl['day_short'], 1)} h at midwinter, for an Earth-like tilt {MIXED}")])
        sets = cx["sets"]
        labels = [("surroundings", f"Within {self.d(cx['radius'], 0)}"), ("province", "Province"), ("state", "State"),
                  ("latitude", f"Same latitude ($\\pm${self.d(cx['band'], 0)})"), ("world", "World")]
        rows = ["\\textbf{Compared with} & \\textbf{Elevation} & \\textbf{Temp.} & \\textbf{Precip.}",
                f"This tile & {self.h(cx['tile']['elevation'])} & {self.ts(cx['tile']['temperature'])} & {fnum(cx['tile']['precipitation'], 0)} mm"]
        for key, lab in labels:
            e, tt, pp = sets["elevation"].get(key), sets["temperature"].get(key), sets["precipitation"].get(key)
            if not e:
                continue
            rows.append(f"{lab} & {self.h(e['mean'])} ({fpct(e['rank'])}) & {self.ts(tt['mean'])} ({fpct(tt['rank'])}) & "
                        f"{fnum(pp['mean'], 0)} ({fpct(pp['rank'])})")
        self.table(f"In Context {DATA}", "Xlll", rows)
        tl = sets["temperature"].get("latitude")
        notes = [f"Means of the {cx['domain']} grid points in each area; in brackets, the share of those points "
                 f"that are lower than or level with this tile."]
        if tl:
            diff = cx["tile"]["temperature"] - tl["mean"]
            notes.append(f"The tile is {fnum(abs(diff), 1)}\\textdegree{{}}C {'warmer' if diff >= 0 else 'colder'} than the mean at its latitude.")
        ex = te["extremes"]
        if ex:
            notes.append(f"The highest ground within {self.d(cx['radius'], 0)} is {self.h(ex['high']['h'])}, {self.where(ex['high'])}; "
                         f"the lowest is {self.h(ex['low']['h'])}, {self.where(ex['low'])}.")
        self.add(" ".join(notes), "")

    def _people(self):
        R, w = self.R, self.w
        p = R["people"]
        self.add(r"\section{People}")
        ctx = p["context"]
        self.kv("Population", [
            ("Rural", f"{fnum(p['rural'], 0)}: each cell's people spread over its area and counted by the part inside {MIXED}"),
            ("Urban", f"{fnum(p['urban'], 0)} in {p['burg_count']} burg{'s' if p['burg_count'] != 1 else ''} {DATA}"),
            ("Total", fnum(p["total"], 0)),
            ("Density", f"{fnum(p['density'], 1)} per {tex(w.area_label())} of land" if p["density"] is not None else None),
            ("Rural, smoothed", f"{fnum(p['smooth_rural'], 0)}, densities blended across neighbouring cells {MIXED}"),
            ("Cells under the tile", f"{fnum(ctx.get('cells'), 1)} per {tex(w.area_label())}" if ctx.get("cells") else None),
            ("Province", f"{fnum(ctx.get('province'), 1)} per {tex(w.area_label())}" if ctx.get("province") else None),
            ("State", f"{fnum(ctx.get('state'), 1)} per {tex(w.area_label())}" if ctx.get("state") else None),
            ("World", f"{fnum(ctx.get('world'), 1)} per {tex(w.area_label())} of land" if ctx.get("world") else None)])
        if R["cultures"]:
            rows = ["\\textbf{Culture} & \\textbf{Land} & \\textbf{People} & \\textbf{Type}"]
            rows += [f"{tex(c['name'])} & {fpct(c['area_share'])} & {fpct(c['pop_share'])} & {tex(c['type'])}" for c in R["cultures"]]
            self.table(f"Cultures {DATA}", "Xrrl", rows)
            for c in R["cultures"]:
                bits = [f"names in the {tex(c['namebase'])} tradition" if c["namebase"] else None,
                        f"descends from {tex(' < '.join(c['lineage']))}" if c["lineage"] else None,
                        f"hearth {self.where(c['hearth'])}" if c["hearth"] else None,
                        f"expansionism {fnum(c['expansionism'], 1)}" if c["expansionism"] is not None else None,
                        f"state culture of {tex(', '.join(c['state_culture_of']))}" if c["state_culture_of"] else "no state's culture"]
                self.add(f"\\textbf{{{tex(c['name'])}}}: " + "; ".join(b for b in bits if b) + ".", "")
        if R["religions"]:
            rows = ["\\textbf{Faith} & \\textbf{Land} & \\textbf{People} & \\textbf{Type}"]
            rows += [f"{tex(r['name'])} & {fpct(r['area_share'])} & {fpct(r['pop_share'])} & {tex(r['type'])}" for r in R["religions"]]
            self.table(f"Faiths {DATA}", "Xrrl", rows)
            for r in R["religions"]:
                bits = [f"{tex(r['form'])}" if r["form"] else None,
                        f"worships {tex(r['deity'])}" if r["deity"] else None,
                        f"spreads by {tex(r['expansion'])}" if r["expansion"] else None,
                        f"of the {tex(r['culture'])} culture" if r["culture"] else None,
                        f"comes from {tex(' < '.join(r['lineage']))}" if r["lineage"] else None,
                        f"centre {self.where(r['seat'])}" if r["seat"] else None]
                self.add(f"\\textbf{{{tex(r['name'])}}}: " + "; ".join(b for b in bits if b) + ".", "")

    def _relation_text(self, it):
        txt = []
        if it.get("a_to_b") or it.get("b_to_a"):
            txt.append(f"{tex(it['a'])} regards {tex(it['b'])} as \\textbf{{{tex(it.get('a_to_b') or 'n/a')}}}; "
                       f"{tex(it['b'])} regards {tex(it['a'])} as \\textbf{{{tex(it.get('b_to_a') or 'n/a')}}}.")
        for c in it.get("campaigns", []):
            when = f"{c['start']}--{c['end']}" if c.get("end") is not None else f"from {c['start']}"
            txt.append(f"{tex(c['name'])} ({when}{', still running' if c['ongoing'] else ''}): {tex(c['attacker'])} attacked {tex(c['defender'])}.")
        if not it.get("campaigns"):
            txt.append("No campaigns between them are on record.")
        return " ".join(txt)

    def _rulers(self):
        R, w = self.R, self.w
        self.add(r"\section{Rulers and Borders}")
        for s in R["states"]:
            self.add(f"\\subsection{{{tex(s['full'])}}}")
            if not s.get("id"):
                self.add(f"Unclaimed land, {fpct(s['area_share'])} of the tile {DATA}.", "")
                continue
            rel = ", ".join(f"{v} {tex(k.lower())}" for k, v in sorted(s["relations"].items(), key=lambda kv: -kv[1]))
            self.kv(f"{tex(s['name'])} {DATA}", [
                ("Share of tile", fpct(s["area_share"])),
                ("Form", f"{tex(s['form'])} ({tex(s['formName'])}), {tex(s['type'])} state" if s.get("form") else None),
                ("Capital", f"{tex(s['capital']['name'])}, {self.where(s['capital'])}" if s.get("capital") else None),
                ("State culture", tex(s.get("culture"))), ("Main faith", tex(s.get("main_religion"))),
                ("People", fnum(s["people"], 0)), ("Area", self.a(s["area"], 0)),
                ("Burgs, provinces", f"{s['burgs']}, {s['provinces']}"),
                ("Sales tax", f"{fpct(s['salesTax'])} (rank {s['rank_sales']} of {s['n_states']})" if s.get("salesTax") is not None else None),
                ("Poll tax", f"{fpct(s['pollTax'])} (rank {s['rank_poll']} of {s['n_states']})" if s.get("pollTax") is not None else None),
                ("Treasury", f"{fnum(s['treasury'], 1)} (rank {s['rank_treasury']} of {s['n_states']})" if s.get("treasury") is not None else None),
                ("Army and fleet", f"{fnum(s['military'], 0)} in {s['units']} units, alert {fnum(s['alert'], 2)}"),
                ("Neighbours", tex(", ".join(s["neighbors"]))), ("Stances", rel)])
            if s.get("campaigns"):
                rows = [f"{tex(c.get('name'))} & {c.get('start')}--{c.get('end') if c.get('end') is not None else ''} & "
                        f"{tex(w.state_name(c.get('attacker', 0)))} v {tex(w.state_name(c.get('defender', 0)))}" for c in s["campaigns"]]
                self.table(f"Campaigns of {tex(s['name'])} {DATA}", "Xll", ["\\textbf{Campaign} & \\textbf{Years} & \\textbf{Sides}"] + rows)
            if s.get("note"):
                self.add(r"\begin{DndReadAloud}", texp(s["note"]), r"\end{DndReadAloud}", "")
        for p in R["provinces"]:
            self.add(f"\\subsection{{{tex(p['full'])}}}")
            self.kv(f"Province {DATA}", [("Share of tile", fpct(p["area_share"])), ("Form", tex(p["form"])), ("State", tex(p["state"])),
                                         ("Seat", f"{tex(p['capital']['name'])}, {self.where(p['capital'])}" if p.get("capital") else None),
                                         ("People", fnum(p["people"], 0)), ("Land area", self.a(p["area"], 0))])
            if p.get("note"):
                self.add(r"\begin{DndReadAloud}", texp(p["note"]), r"\end{DndReadAloud}", "")
        if R["flags"]:
            self.comment("Mismatches", " ".join(tex(f) for f in R["flags"]) + f" {DATA}")
        self.add(r"\subsection{Borders}")
        B = R["borders"]
        any_border = False
        names = {"state": "States", "province": "Provinces", "culture": "Cultures", "religion": "Faiths",
                 "market": "Market regions", "biome": "Biomes"}
        for key in ("state", "province", "culture", "religion", "market", "biome"):
            items = B.get(key) or []
            if not items:
                continue
            any_border = True
            self.add(f"\\paragraph{{{names[key]}}}")
            for it in items:
                head = f"{tex(it['a'])} | {tex(it['b'])}, {self.d(it['length'], 2)} of border in the tile {DATA}."
                body = ""
                if key == "state":
                    body = self._relation_text(it)
                    if it.get("chronicle"):
                        body += " The war chronicle: " + " ".join(tex(" ".join(c)) for c in it["chronicle"][:3])
                elif key == "province":
                    body = "Both in the same state." if it.get("same_state") else "The provinces belong to different states."
                elif key == "culture":
                    body = (f"{tex(it['a'])} ({tex(it.get('a_type'))}, {tex(it.get('a_lang'))} names) and {tex(it['b'])} "
                            f"({tex(it.get('b_type'))}, {tex(it.get('b_lang'))} names): {tex(it['lineage'])}.")
                elif key == "religion":
                    body = (f"{tex(it['a'])} ({tex(it.get('a_type'))}, {tex(it.get('a_form'))}) and {tex(it['b'])} "
                            f"({tex(it.get('b_type'))}, {tex(it.get('b_form'))}): {tex(it['lineage'])}.")
                elif key == "market":
                    top = "; ".join(f"{tex(g)} {'to' if side == 'a' else 'from'} {tex(it['b'])} ({fnum(v, 1)})" for g, side, v in it["top"])
                    body = (f"Trade between them: {fnum(it['a_to_b'], 1)} coin from {tex(it['a'])} to {tex(it['b'])}, "
                            f"{fnum(it['b_to_a'], 1)} back" + (f"; largest: {top}" if top else "") + ".")
                self.add(f"{head} {body}", "")
        if not any_border:
            self.add(f"No border of any kind crosses the tile {DATA}.", "")
        nb = R.get("nearest_border")
        if nb:
            self.add(f"The nearest state border, {tex(nb['a'])} | {tex(nb['b'])}, is {self.where(nb)}. "
                     + self._relation_text(nb) + f" {DATA}", "")
        if R["zones"]:
            self.add(r"\subsection{Zones}")
            for z in R["zones"]:
                self.add(f"\\textbf{{{tex(z['name'])}}} ({tex(z['type'])}) covers {fpct(z['share'])} of the tile. "
                         f"The whole zone spans {z['cells']} cells, {self.a(z['area'], 0)} with {fnum(z['people'], 0)} rural people, "
                         f"in {tex(', '.join(z['states']))} {DATA}.", "")

    def _places(self):
        R, w = self.R, self.w
        self.add(r"\section{Places}")
        if not R["burgs"] and not R["markers"]:
            self.add(f"No burg or marker lies in the tile {DATA}.", "")
        for b in R["burgs"]:
            self.add(f"\\DndArea{{{tex(b['name'])}}}")
            if b.get("emblem"):
                self.add(r"\begin{center}" + f"\\includegraphics[width=2.2cm]{{{b['emblem'].resolve().as_posix()}}}" + r"\end{center}")
            self.kv(f"{tex(b['name'])} {DATA}", [
                ("People", f"{fnum(b['people'], 0)} ({fnum(b['points'], 3)} population points)"),
                ("Kind", f"{tex(split_camel(b['group'] or ''))}, {tex(b['type'])} type"),
                ("Has", tex(", ".join(b["features"])) or "no walls, temple, citadel or market square"),
                ("Point reference", self.ref(b["point_ref"])), ("State", tex(b["state"])), ("Province", tex(b["province"])),
                ("Culture", tex(b["culture"])), ("Faith", tex(b["religion"])), ("Biome", tex(b["biome"])),
                ("River", tex(b["river"])),
                ("To the capital", f"{self.d(b['to_capital'], 0)} to {tex(b['capital_name'])} (straight line)" if b.get("to_capital") else None),
                ("Market", tex(b["market"])), ("Treasury", fnum(b["treasury"], 2)), ("Product value", fnum(b["product"], 2)),
                ("Arms", tex(b["coa"]))])
            if b["produces"]:
                rows = [f"{tex(p['good'])} & {fnum(p['units'], 2)} {tex(p['unit'] or '')} & "
                        + (tex(", ".join(f"{fnum(v, 2)} {k}" for k, v in p["inputs"].items())) or "local bonus") for p in b["produces"]]
                self.table(f"Made in {tex(b['name'])} {DATA}", "lrX", ["\\textbf{Good} & \\textbf{Units} & \\textbf{From}"] + rows)
            for label, items in (("Bought", b["buys"]), ("Sold", b["sells"])):
                if items:
                    rows = [f"{tex(x['good'])} & {fnum(x['units'], 2)} & {fnum(x['value'], 2)} & {tex(', '.join(x['partners']))}" for x in items[:12]]
                    if len(items) > 12:
                        rows.append(f"{len(items) - 12} more goods & {fnum(sum(x['units'] for x in items[12:]), 2)} & "
                                    f"{fnum(sum(x['value'] for x in items[12:]), 2)} & ")
                    self.table(f"{label} by {tex(b['name'])} {DATA}", "lrrX",
                               ["\\textbf{Good} & \\textbf{Units} & \\textbf{Coin} & \\textbf{With}"] + rows)
            if b.get("plan"):
                pl = b["plan"]
                cnt = ", ".join(f"{v} {k}" for k, v in pl["counts"].items() if v)
                self.add(f"A Watabou plan of {tex(b['name'])} is in the world folder ({tex(pl['file'])}"
                         + (f", generator {tex(pl['info'].get('generator'))}" if pl["info"].get("generator") else "")
                         + f"): {tex(cnt)} {DATA}.", "")
            if b.get("note"):
                self.add(r"\begin{DndReadAloud}", texp(b["note"]), r"\end{DndReadAloud}", "")
        for m in R["markers"]:
            self.add(f"\\DndArea{{{tex(m['name'])}}}")
            self.add(f"A marker of type \\textit{{{tex(split_camel(m['type'] or ''))}}} at {self.ref(m['point_ref'])}, cell {m['cell']} {DATA}.", "")
            if m["note"]:
                self.add(r"\begin{DndReadAloud}", texp(m["note"]), r"\end{DndReadAloud}", "")
        if R["units"]:
            self.add(r"\subsection{Military Units}")
            for u in R["units"]:
                comp = ", ".join(f"{fnum(v, 0)} {k}" for k, v in sorted(u["composition"].items(), key=lambda kv: -kv[1]))
                where = "in the tile" if u["here"] else "away"
                self.kv(f"{tex(u['name'])} {DATA}", [("State", tex(u["state"])), ("Strength", fnum(u["men"], 0)),
                                                     ("Kind", "fleet" if u["naval"] else "regiment"), ("Composition", tex(comp)),
                                                     ("Position", f"{where}, {self.ref(u['point_ref'])}"),
                                                     ("Base", (self.ref(u["base_ref"]) + (" (this tile)" if u["based_here"] else "")) if u.get("base_ref") else None)])
                if u["note"]:
                    self.add(r"\begin{DndReadAloud}", texp(u["note"]), r"\end{DndReadAloud}", "")
        self.add(r"\subsection{Nearby}")
        if R["near_burgs"]:
            rows = ["\\textbf{Burg} & \\textbf{Where} & \\textbf{People}"]
            rows += [f"{tex(b['name'])}{' (capital)' if b['capital'] else ''} & {self.d(b['dist'], 0)} {b['dir']}, {self.ref(b['ref'])} & {fnum(b['people'], 0)}"
                     for b in R["near_burgs"]]
            self.table(f"Burgs Nearby {DATA}", "Xlr", rows)
        if R["near_markers"]:
            rows = [f"{tex(m['name'])} & {tex(split_camel(m['type'] or ''))} & {self.d(m['dist'], 0)} {m['dir']}, {self.ref(m['ref'])}" for m in R["near_markers"]]
            self.table(f"Markers Nearby {DATA}", "Xll", ["\\textbf{Marker} & \\textbf{Type} & \\textbf{Where}"] + rows)
        if R["near_units"]:
            rows = [f"{tex(u['name'])} ({tex(u['state'])}) & {fnum(u['men'], 0)} & {self.d(u['dist'], 0)} {u['dir']}, {self.ref(u['ref'])}" for u in R["near_units"]]
            self.table(f"Units Nearby {DATA}", "Xrl", ["\\textbf{Unit} & \\textbf{Men} & \\textbf{Where}"] + rows)

    def _lines(self):
        R, w = self.R, self.w
        self.add(r"\section{Rivers, Routes and Journeys}")
        if not (R["rivers"] or R["routes"] or R["journeys"]):
            self.add(f"No river, route or journey crosses the tile {DATA}.", "")
        for r in R["rivers"]:
            self.add(f"\\DndItemHeader{{{tex(r['name'])}}}{{{tex(r['type'])}, {fnum(r['discharge'], 0)} m\\textsuperscript{{3}}/s at the mouth}}")
            bits = [f"{self.d(r['inside'], 2)} of its course ({fpct(r['share'], 1)}) lies in the tile, flowing {r['flows']}" if r["flows"] else
                    f"{self.d(r['inside'], 2)} of its course lies in the tile",
                    f"length {self.d(r['length'], 0)} ({tex(r['course_source'])} {self.d(r['course'], 0)})",
                    f"width at the mouth {self.d(r['width'], 2)}"]
            if r.get("source"):
                bits.append(f"source {self.where(r['source'])}")
            if r.get("mouth"):
                bits.append(f"mouth {self.where(r['mouth'])}" + (f" into {tex(r['mouth']['into'])}" if r['mouth'].get("into") else ""))
            if r.get("parent"):
                bits.append(f"feeds the {tex(r['parent'])}")
            if r.get("basin") and r.get("basin") != r.get("parent"):
                bits.append(f"basin of the {tex(r['basin'])}")
            if r["tributaries"]:
                bits.append("tributaries: " + tex(", ".join(x for x in r["tributaries"] if x)))
            if r["burgs"]:
                bits.append("burgs on it: " + tex(", ".join(r["burgs"])))
            self.add("; ".join(bits) + f" {DATA}.", "")
        if R["cell_rivers"]:
            self.add("Cells under the tile also carry " + tex(", ".join(x["name"] or str(x["id"]) for x in R["cell_rivers"]))
                     + f", whose line passes outside the tile {DATA}.", "")
        if R["routes"]:
            rows = ["\\textbf{Route} & \\textbf{Here} & \\textbf{Nearest burgs along it}"]
            for r in R["routes"]:
                between = []
                for side in ("prev", "next"):
                    if r[side]:
                        dist = r[side]["dist"]
                        between.append(f"{tex(r[side]['name'])} " + ("(here)" if dist < 0.05 else self.d(dist, 0)))
                rows.append(f"{tex(r['name'])} ({tex(r['group'])}, {self.d(r['length'], 0)}) & {self.d(r['inside'], 1)} {r['heading']} & {', '.join(between) or '--'}")
            self.table(f"Routes {DATA}", "XlX", rows)
            ends = [f"{tex(r['name'])} runs {tex(r['ends'][0] or 'open country')} to {tex(r['ends'][1] or 'open country')}, through {r['burgs']} burgs"
                    for r in R["routes"] if r["burgs"]]
            if ends:
                self.add("; ".join(ends) + ". Distances under \\textit{Between} run along the route to the nearest burg on each side.", "")
        for jn in R["journeys"]:
            self.add(f"\\DndItemHeader{{{tex(jn['journey'])}}}{{{tex(jn['jtype'] or 'journey')}: {tex(jn['segment'])} (segment {jn['seg_i']})}}")
            if jn["stay"]:
                self.add(f"The plan stops here for {fnum(jn['hours'], 1)} h from {tex(jn['clock_text'])} of the journey, "
                         f"{self.d(jn['along'], 0)} along it {DATA}.", "")
                continue
            sp = f"{fnum(jn['speed_kmh'], 1)} km/h" + (", halved off road" if jn["avoid_roads"] else "")
            self.kv(f"Plan in this tile {DATA}", [
                ("Transport", f"{tex(jn['transport'])}: {sp} = {fnum(jn['speed_units'], 2)} {tex(w.unit)}/h, {jn['hpd']} h of travel a day"),
                ("Enters", f"{self.d(jn['along_in'], 1)} along the journey, {tex(jn['clock_in_text'])}"),
                ("Leaves", f"{self.d(jn['along_out'], 1)} along, {tex(jn['clock_out_text'])}"),
                ("In the tile", f"{self.d(jn['inside'], 2)} heading {jn['heading']}, {fnum(jn['travel_hours'], 1)} h of travel" if jn["travel_hours"] else None),
                ("Timing", "the segment's own duration is set in the map" if jn["duration_set"] else "Azgaar's rule: distance over speed, full travel days counted as 24 h")])
        near = []
        for r in R["near_rivers"]:
            near.append(f"{tex(r['name'])} ({tex(r['type'])}) & {self.d(r['dist'], 1)} {r['dir']}")
        for r in R["near_routes"]:
            near.append(f"{tex(r['name'])} ({tex(r['group'])}) & {self.d(r['dist'], 1)} {r['dir']}")
        for j in R["near_journeys"]:
            near.append(f"{tex(j['journey'])}: {tex(j['segment'])} & {self.d(j['dist'], 1)} {j['dir']}")
        if near:
            self.table(f"Lines Nearby {DATA}", "Xl", ["\\textbf{Line} & \\textbf{Closest approach}"] + near)

    def _trade(self):
        R, w = self.R, self.w
        tr = R["trade"]
        self.add(r"\section{Production and Trade}")
        if tr["goods"]:
            rows = ["\\textbf{Good} & \\textbf{Here} & \\textbf{State} & \\textbf{Market} & \\textbf{World}"]
            for gd in tr["goods"]:
                st = next((s["share"] for s in gd["shares"] if s["kind"] == "state"), None)
                mk = next((s["share"] for s in gd["shares"] if s["kind"] == "market"), None)
                rows.append(f"{tex(gd['name'])} & {fnum(gd['total'], 2)} & {fpct(st, 1) if st is not None else '--'} & "
                            f"{fpct(mk, 1) if mk is not None else '--'} & {fpct(gd['world_share'], 2) if gd['world_share'] is not None else '--'}")
            self.table(f"Output and Its Share {MIXED}", "Xrrrr", rows)
            self.add("Units a year. Rural output follows Azgaar's cell production (biome yield times people, the cell's bonus good, "
                     "and the good's modifiers) counted by the part of each cell inside the tile; urban output is the production "
                     "record of the burgs in the tile. Shares compare it with the whole state, market region and world.", "")
            for gd in tr["goods"][:8]:
                self.add(f"\\DndItemHeader{{{tex(gd['name'])}}}{{{tex(', '.join(gd['tags']) or 'good')}; base value {fnum(gd['value'], 2)} a {tex(gd['unit'] or 'unit')}}}")
                bits = [f"made here: {fnum(gd['rural'], 2)} rural, {fnum(gd['urban'], 2)} urban {MIXED}"]
                for s in gd["shares"]:
                    bits.append(f"{fpct(s['share'], 1)} of {tex(s['of'])}'s output")
                if gd["price"] is not None:
                    rel = gd["price"] / gd["mean_price"] if gd.get("mean_price") else None
                    bits.append(f"price at the tile's market {fnum(gd['price'], 2)}" + (f" ({fnum(rel, 2)} times the mean of all markets)" if rel else "")
                                + (f", stock {fnum(gd['stock'], 2)}" if gd.get("stock") is not None else "") + f" {DATA}")
                if gd["exports"]:
                    bits.append("the market sends it to " + tex(", ".join(f"{n} ({fnum(u, 2)})" for n, u in gd["exports"])) + f" {DATA}")
                if gd.get("distribution"):
                    bits.append(f"found where \\texttt{{{tex(gd['distribution'])}}}")
                self.add("; ".join(bits) + ".", "")
        else:
            self.add(f"Nothing is produced in the tile {MIXED}.", "")
        if tr["deposits"]:
            self.add("Bonus goods in the cells under the tile: " + ", ".join(f"{tex(x['good'])} ({fpct(x['share'])} of the tile)" for x in tr["deposits"])
                     + f" {DATA}.", "")
        for m in tr["markets"]:
            c = m["centre"]
            self.add(f"\\subsection{{{tex(c['name']) if c else 'Market ' + str(m['id'])} Market}}")
            self.add(f"The market region covers {fpct(m['share'])} of the tile; its centre is {self.where(c) if c else 'unknown'}. "
                     f"It serves {m['burgs']} burgs over {m['cells']} cells and trades {fnum(m['export_value'], 1)} coin out, "
                     f"{fnum(m['import_value'], 1)} in, with other markets {DATA}.", "")
            rows = [f"Out & {tex(g)} & {fnum(v, 1)} & {tex(p)}" for g, v, p in m["exports"]]
            rows += [f"In & {tex(g)} & {fnum(v, 1)} & {tex(p)}" for g, v, p in m["imports"]]
            if rows:
                self.table(f"Largest Flows {DATA}", "llrX", ["\\textbf{} & \\textbf{Good} & \\textbf{Coin} & \\textbf{Market}"] + rows)
        for label, items in (("Bought by the Tile's Burgs", tr["buys"]), ("Sold by the Tile's Burgs", tr["sells"])):
            if items:
                rows = [f"{tex(x['good'])} & {fnum(x['units'], 2)} & {fnum(x['value'], 2)} & {fnum(x['tax'], 2)}" for x in items]
                self.table(f"{label} {DATA}", "Xrrr", ["\\textbf{Good} & \\textbf{Units} & \\textbf{Coin} & \\textbf{Tax}"] + rows)

    def _appendix(self):
        R, w, g = self.R, self.w, self.g
        self.add(r"\section{Cells and Method}")
        rows = ["\\textbf{Cell} & \\textbf{Tile} & \\textbf{Cell in tile} & \\textbf{Rural here}"]
        rows += [f"{c['cell']} & {fpct(c['of_tile'], 1)} & {fpct(c['of_cell'], 1)} & {fnum(c['rural'], 0)}" for c in R["cells"][:66]]
        self.table(f"Cells Under the Tile {DATA}", "lrrr", rows)
        if len(R["cells"]) > 66:
            self.add(f"{len(R['cells']) - 66} smaller cells are left out here; the JSON output (--json) lists them all.", "")
        for c in R["cells"][:24]:
            bits = [tex(c["type"]), tex(c["biome"]), self.a(c["area"], 1)]
            if c["state"]:
                bits += [tex(c["state"]) + (f" / {tex(c['province'])}" if c["province"] else ""), tex(c["culture"]), tex(c["religion"])]
            bits += [f"height {c['height']} {tex(w.h_unit)}" if c["height"] is not None else None, f"market {c['market']}" if c["market"] else None,
                     f"river {c['river']}" if c["river"] else None, f"flux {c['flux']}", f"confluence {c['conf']}" if c["conf"] else None,
                     f"suitability {c['suit']}", f"{fnum(c['cell_rural'], 0)} rural people in the whole cell",
                     f"bonus good {tex(c['good'])}" if c["good"] else None,
                     ("zones " + tex(", ".join(c["zones"]))) if c["zones"] else None, tex(c["feature"])]
            self.add(f"\\textbf{{Cell {c['cell']}}}: " + "; ".join(b for b in bits if b) + ".", "")
        method = (
            f"Grid: {tex(g.source)}; {tex(g.describe())}. References follow the Ordnance Survey pattern: letters for "
            f"the {g.block} x {g.block} square (eastward, then northward, from the south-west corner; no I), then eastings "
            f"and northings within it. Areal figures clip each cell outline from the Cells export against the tile and count "
            f"the cell's value by the part inside. Heights, temperatures and precipitation come from Azgaar's climate grid "
            f"(spacing {self.d(w.grid_spacing * w.scale, 0)}), read under each of {len(self.t.samples)} sample points the "
            f"way Azgaar's own cell panel reads them. Rivers follow their drawn course where the map's SVG keeps it, "
            f"otherwise a line through their cells. Journey times follow Azgaar: speeds are stored in km/h"
            + (", here read as map units per hour (--speeds-as-map-units)" if self.t.legacy else "")
            + ", halved off road, and every full travel day costs 24 hours.")
        self.comment("How the Figures Were Made", method)
        files = [f"Map: {tex(w.map_path.name)} (Azgaar {tex(w.version)})", f"Cells: {tex(w.cells_path.name)}"]
        files += [tex(n) for n in w.notes + g.notes]
        self.comment("Files", " \\\\ ".join(files))


# ====================================================================== SVG reference maps
def _feature_d(w: World):
    out = {}
    start = w.svg.find('id="featurePaths"')
    if start >= 0:
        end = w.svg.find("</g>", start)
        for m in re.finditer(r"<path\b([^>]*)>", w.svg[start:end]):
            attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))
            if attrs.get("id", "").startswith("feature_") and attrs.get("d"):
                out[int(attrs["id"][8:])] = attrs["d"]
    return out


def _xml(s):
    return html.escape(str(s), quote=True)


def _svg_base(w: World, win, fs, biomes=True, extras=True):
    """Shared layers: water, land (biome cells clipped to Azgaar's coastline), lakes, borders, rivers, routes."""
    d = w.d
    x0, y0, x1, y1 = win
    fd = _feature_d(w)
    L = [f'<rect x="{x0 - 1000}" y="{y0 - 1000}" width="{x1 - x0 + 2000}" height="{y1 - y0 + 2000}" fill="#c8ddeb"/>']
    land_ids = [fid for fid in fd if (w.feature(fid) or {}).get("land") and (w.feature(fid) or {}).get("subtype") != "lake_island"]
    lake_ids = [fid for fid in fd if (w.feature(fid) or {}).get("type") == "lake"]
    isle_ids = [fid for fid in fd if (w.feature(fid) or {}).get("subtype") == "lake_island"]
    if land_ids:
        L.append('<defs><clipPath id="land">' + "".join(f'<path d="{fd[f]}"/>' for f in land_ids + isle_ids) + "</clipPath></defs>")
        L.append('<g>' + "".join(f'<path d="{fd[f]}" fill="#efe9d6"/>' for f in land_ids) + "</g>")
    if biomes:
        L.append('<g clip-path="url(#land)" stroke="none">' if land_ids else "<g>")
        for c in w.cell_index.query(win):
            if w.water[c] or not bbox_hit(w.cell_bbox[c], win):
                continue
            col = (w.biomes[d["biome"][c]] or {}).get("color", "#cccccc")
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in w.cell_poly[c])
            L.append(f'<polygon points="{pts}" fill="{col}" opacity="0.55"/>')
        L.append("</g>")
    if land_ids:
        L.append('<g fill="none" stroke="#4a6b80" stroke-width="%.3f">' % (fs * 0.08) + "".join(f'<path d="{fd[f]}"/>' for f in land_ids) + "</g>")
    L.append('<g fill="#c8ddeb" stroke="#4a6b80" stroke-width="%.3f">' % (fs * 0.06) + "".join(f'<path d="{fd[f]}"/>' for f in lake_ids) + "</g>")
    if isle_ids:
        L.append('<g fill="#efe9d6">' + "".join(f'<path d="{fd[f]}"/>' for f in isle_ids) + "</g>")
    st, pv = [], []
    for a, b, p, q in w.edges:
        if w.water[a] or w.water[b]:
            continue
        bb = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
        if not bbox_hit(bb, win):
            continue
        seg = f"M{p[0]:.2f},{p[1]:.2f}L{q[0]:.2f},{q[1]:.2f}"
        if d["state"][a] != d["state"][b]:
            st.append(seg)
        elif extras and d["province"][a] != d["province"][b]:
            pv.append(seg)
    if pv:
        L.append(f'<path d="{"".join(pv)}" fill="none" stroke="#6a1b4d" stroke-width="{fs * 0.05:.3f}" stroke-dasharray="{fs * 0.2:.2f} {fs * 0.2:.2f}" opacity="0.6"/>')
    if st:
        L.append(f'<path d="{"".join(st)}" fill="none" stroke="#6a1b4d" stroke-width="{fs * 0.14:.3f}" stroke-dasharray="{fs * 0.5:.2f} {fs * 0.25:.2f}"/>')
    for rid, course in w.river_courses.items():
        pts = course["points"]
        if len(pts) >= 2 and bbox_hit(bbox_of(pts), win):
            disc = w.rivers[rid].get("discharge") or 10
            sw = fs * (0.04 + 0.03 * math.log10(max(disc, 1)))
            L.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in pts)}" fill="none" stroke="#2b7bb9" stroke-width="{sw:.3f}" stroke-linejoin="round"><title>{_xml(w.rivers[rid].get("name"))}</title></polyline>')
    for r in w.routes:
        pts = [(p[0], p[1]) for p in r["points"]]
        if len(pts) < 2 or not bbox_hit(bbox_of(pts), win):
            continue
        grp = r.get("group")
        if not extras and grp != "roads":
            continue
        style = {"roads": ("#8b3a1a", 0.12, ""), "trails": ("#8b3a1a", 0.07, f"{fs * 0.3:.2f} {fs * 0.2:.2f}"),
                 "searoutes": ("#1f4e79", 0.06, f"{fs * 0.1:.2f} {fs * 0.25:.2f}")}.get(grp, ("#8b3a1a", 0.07, ""))
        dash = f' stroke-dasharray="{style[2]}"' if style[2] else ""
        L.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in pts)}" fill="none" stroke="{style[0]}" stroke-width="{fs * style[1]:.3f}"{dash}><title>{_xml(r.get("name") or grp)}</title></polyline>')
    if extras:
        for z in w.zones:
            for c in z.get("cells", []):
                if 0 <= c < w.n and bbox_hit(w.cell_bbox[c], win):
                    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in w.cell_poly[c])
                    L.append(f'<polygon points="{pts}" fill="#b03030" fill-opacity="0.08" stroke="#b03030" stroke-width="{fs * 0.03:.3f}" stroke-dasharray="{fs * 0.15:.2f}"><title>{_xml(z.get("name"))} ({_xml(z.get("type"))})</title></polygon>')
        for j in w.journeys:
            for s in j.get("segments", []):
                pts = [(p[0], p[1]) for p in s.get("points", [])]
                if len(pts) >= 2 and bbox_hit(bbox_of(pts), win) and s.get("visible", True) is not False:
                    L.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in pts)}" fill="none" stroke="#e07b00" stroke-width="{fs * 0.16:.3f}" opacity="0.8"><title>{_xml(j.get("name"))}: {_xml(s.get("name"))}</title></polyline>')
    return L


def svg_overview(w: World, g: TileGrid, out_path):
    W, H = w.W, w.H
    fs = max(W, H) / 170  # base font size in map units
    m = fs * 3.2
    win = (0, 0, W, H)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-m:.1f} {-m:.1f} {W + 2 * m:.1f} {H + 2 * m:.1f}" '
         f'width="{(W + 2 * m) * 1.2:.0f}" height="{(H + 2 * m) * 1.2:.0f}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect x="{-m}" y="{-m}" width="{W + 2 * m}" height="{H + 2 * m}" fill="white"/>',
         f'<svg x="0" y="0" width="{W}" height="{H}" viewBox="0 0 {W} {H}" overflow="hidden">']
    L += _svg_base(w, win, fs, biomes=True, extras=False)
    tiles = g.ncols * g.nrows
    eo = 0.25 if g.kind == "pointyHex" else 0.0
    no = 0.25 if g.kind == "flatHex" else 0.0
    if tiles <= 6000:
        for ii in range(g.imin, g.imax + 1):
            for jj in range(g.jmin, g.jmax + 1):
                if not g.exists(ii, jj):
                    continue
                pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in g.poly(ii, jj))
                L.append(f'<polygon points="{pts}" fill="none" stroke="#333" stroke-width="{fs * 0.04:.3f}"/>')
                if g.width_px >= fs * 2.2:
                    cx, cy = g.center(ii, jj)
                    L.append(f'<text x="{cx:.2f}" y="{cy:.2f}" font-size="{min(fs * 0.7, g.width_px * 0.2):.2f}" text-anchor="middle" '
                             f'fill="#222">{_xml(g.ref(ii, jj))}</text>')
    step = 10 if g.block >= 100 and g.ncols > 30 else 1
    for e in range(0, g.ncols + 1, step):
        x = g.x_origin + (e + eo) * g.step_x
        if 0 <= x <= W:
            major = e % g.block == 0
            L.append(f'<line x1="{x:.2f}" y1="0" x2="{x:.2f}" y2="{H}" stroke="#1a3a6b" stroke-width="{fs * (0.16 if major else 0.04):.3f}" opacity="{0.9 if major else 0.6}"/>')
    for n in range(0, g.nrows + 1, step):
        y = g.y_origin - (n + no) * g.step_y
        if 0 <= y <= H:
            major = n % g.block == 0
            L.append(f'<line x1="0" y1="{y:.2f}" x2="{W}" y2="{y:.2f}" stroke="#1a3a6b" stroke-width="{fs * (0.16 if major else 0.04):.3f}" opacity="{0.9 if major else 0.6}"/>')
    for be in range(g.blocks_e):
        for bn in range(g.blocks_n):
            xa = max(0, g.x_origin + be * g.block * g.step_x)
            xb = min(W, g.x_origin + (be + 1) * g.block * g.step_x)
            ya = max(0, g.y_origin - (bn + 1) * g.block * g.step_y)
            yb = min(H, g.y_origin - bn * g.block * g.step_y)
            if xb - xa > fs * 3 and yb - ya > fs * 3:
                L.append(f'<text x="{(xa + xb) / 2:.1f}" y="{(ya + yb) / 2 + fs * 2:.1f}" font-size="{fs * 5.5:.1f}" font-weight="bold" '
                         f'text-anchor="middle" fill="#1a3a6b" opacity="0.28">{LETTERS[be]}{LETTERS[bn]}</text>')
    for b in w.live(w.burgs):
        if not b.get("i"):
            continue
        big = b.get("capital") or b.get("group") in ("city", "capital")
        r = fs * (0.32 if b.get("capital") else 0.18 if big else 0.09)
        L.append(f'<circle cx="{b["x"]:.2f}" cy="{b["y"]:.2f}" r="{r:.2f}" fill="white" stroke="black" stroke-width="{fs * 0.05:.3f}">'
                 f'<title>{_xml(b["name"])}: {_xml(g.ref(*g.locate(b["x"], b["y"])))}</title></circle>')
        if big:
            L.append(f'<text x="{b["x"] + r * 1.4:.2f}" y="{b["y"] + fs * 0.3:.2f}" font-size="{fs * (0.95 if b.get("capital") else 0.7):.2f}" '
                     f'fill="black" stroke="white" stroke-width="{fs * 0.12:.2f}" paint-order="stroke">{_xml(b["name"])}</text>')
    L.append("</svg>")
    # margins: OS-style figures for each grid line, letters at the corners of each square
    for e in range(0, g.ncols + 1, step):
        x = g.x_origin + (e + eo) * g.step_x
        if 0 <= x <= W:
            lab = f"{e % g.block:0{g.digits}d}" if e % g.block else (LETTERS[e // g.block] if e // g.block < len(LETTERS) else "")
            for y, base in ((-fs * 0.8, "auto"), (H + fs * 1.6, "auto")):
                L.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{fs * 0.85:.2f}" text-anchor="middle" fill="#1a3a6b"'
                         f'{" font-weight=\"bold\"" if not e % g.block else ""}>{lab}</text>')
    for n in range(0, g.nrows + 1, step):
        y = g.y_origin - (n + no) * g.step_y
        if 0 <= y <= H:
            lab = f"{n % g.block:0{g.digits}d}" if n % g.block else (LETTERS[n // g.block] if n // g.block < len(LETTERS) else "")
            for x, anchor in ((-fs * 0.6, "end"), (W + fs * 0.6, "start")):
                L.append(f'<text x="{x:.2f}" y="{y + fs * 0.3:.2f}" font-size="{fs * 0.85:.2f}" text-anchor="{anchor}" fill="#1a3a6b"'
                         f'{" font-weight=\"bold\"" if not n % g.block else ""}>{lab}</text>')
    L.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="black" stroke-width="{fs * 0.1:.2f}"/>')
    L.append(f'<text x="{-m + fs * 0.5:.1f}" y="{-m + fs * 1.4:.1f}" font-size="{fs * 1.1:.2f}" font-weight="bold">{_xml(w.name)}: grid reference overview</text>')
    L.append(f'<text x="{-m + fs * 0.5:.1f}" y="{H + m - fs * 0.6:.1f}" font-size="{fs * 0.75:.2f}">{_xml(g.describe())}. '
             f'Letters name each square (eastward, then northward); figures count tiles east and north inside it. '
             f'Lines every {step} tiles. Hover a burg for its reference.</text>')
    L.append("</svg>")
    Path(out_path).write_text("\n".join(L), encoding="utf-8")


def svg_sheet(w: World, g: TileGrid, ci, cj, radius, out_path, mark=None):
    """A zoomed sheet: every tile outlined and numbered, with 10-tile and square boundaries."""
    d = w.d
    tiles = []
    for ii in range(ci - radius - 1, ci + radius + 2):
        for jj in range(cj - radius - 1, cj + radius + 2):
            cx, cy = g.center(ii, jj)
            c0x, c0y = g.center(ci, cj)
            if abs(cx - c0x) <= radius * g.step_x + 1e-6 and abs(cy - c0y) <= radius * g.step_y + 1e-6 and g.exists(ii, jj):
                tiles.append((ii, jj))
    allpts = [p for t in tiles for p in g.poly(*t)]
    x0, y0, x1, y1 = bbox_of(allpts)
    fs = g.width_px * 0.2
    m = fs * 4
    win = (x0, y0, x1, y1)
    scale = 1400 / (x1 - x0 + 2 * m)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - m:.3f} {y0 - m:.3f} {x1 - x0 + 2 * m:.3f} {y1 - y0 + 2 * m:.3f}" '
         f'width="{(x1 - x0 + 2 * m) * scale:.0f}" height="{(y1 - y0 + 2 * m) * scale:.0f}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect x="{x0 - m}" y="{y0 - m}" width="{x1 - x0 + 2 * m}" height="{y1 - y0 + 2 * m}" fill="white"/>',
         f'<svg x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" overflow="hidden">']
    L += _svg_base(w, win, fs * 2.2, biomes=True, extras=True)
    tset = set(tiles)
    for (ii, jj) in tiles:
        pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in g.poly(ii, jj))
        L.append(f'<polygon points="{pts}" fill="none" stroke="#444" stroke-width="{fs * 0.04:.3f}"/>')
    # 10-tile and square boundaries along tile edges
    for (ii, jj) in tiles:
        e, n = g.en(ii, jj)
        p = g.poly(ii, jj)
        cx, cy = g.center(ii, jj)
        for a in range(len(p)):
            q0, q1 = p[a], p[(a + 1) % len(p)]
            mx, my = (q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2
            ni, nj = g.locate(cx + 2 * (mx - cx), cy + 2 * (my - cy))
            e2, n2 = g.en(ni, nj)
            if (e // g.block, n // g.block) != (e2 // g.block, n2 // g.block):
                sw = 0.22
            elif (e // 10, n // 10) != (e2 // 10, n2 // 10):
                sw = 0.11
            else:
                continue
            L.append(f'<line x1="{q0[0]:.3f}" y1="{q0[1]:.3f}" x2="{q1[0]:.3f}" y2="{q1[1]:.3f}" stroke="#1a3a6b" stroke-width="{fs * sw:.3f}"/>')
    for (ii, jj) in tiles:
        e, n = g.en(ii, jj)
        cx, cy = g.center(ii, jj)
        L.append(f'<text x="{cx:.3f}" y="{cy + fs * 0.35:.3f}" font-size="{fs:.3f}" text-anchor="middle" fill="#111" '
                 f'stroke="white" stroke-width="{fs * 0.18:.3f}" paint-order="stroke">{e % g.block:0{g.digits}d} {n % g.block:0{g.digits}d}</text>')
    L.append(f'<polygon points="{" ".join(f"{x:.3f},{y:.3f}" for x, y in g.poly(ci, cj))}" fill="none" stroke="#c0141b" stroke-width="{fs * 0.25:.3f}"/>')
    for b in w.live(w.burgs):
        if b.get("i") and x0 <= b["x"] <= x1 and y0 <= b["y"] <= y1:
            r = fs * (0.5 if b.get("capital") else 0.32)
            L.append(f'<circle cx="{b["x"]:.3f}" cy="{b["y"]:.3f}" r="{r:.3f}" fill="white" stroke="black" stroke-width="{fs * 0.08:.3f}"/>')
            L.append(f'<text x="{b["x"] + r * 1.3:.3f}" y="{b["y"] - r * 0.6:.3f}" font-size="{fs * 1.1:.3f}" font-weight="bold" fill="black" '
                     f'stroke="white" stroke-width="{fs * 0.2:.3f}" paint-order="stroke">{_xml(b["name"])}</text>')
    for mk in w.markers:
        if x0 <= mk["x"] <= x1 and y0 <= mk["y"] <= y1:
            L.append(f'<text x="{mk["x"]:.3f}" y="{mk["y"] + fs * 0.4:.3f}" font-size="{fs * 1.3:.3f}" text-anchor="middle">{_xml("*" if icon_is_image(mk.get("icon")) else (mk.get("icon") or "*"))}'
                     f'<title>{_xml(mk.get("name") or mk.get("type"))}</title></text>')
    for u in w.units:
        if x0 <= u["x"] <= x1 and y0 <= u["y"] <= y1:
            L.append(f'<rect x="{u["x"] - fs * 0.35:.3f}" y="{u["y"] - fs * 0.25:.3f}" width="{fs * 0.7:.3f}" height="{fs * 0.5:.3f}" '
                     f'fill="#{(w.state(u["state"]) or {}).get("color", "#999999").lstrip("#")}" stroke="black" stroke-width="{fs * 0.05:.3f}">'
                     f'<title>{_xml(u.get("name"))} ({_xml(u.get("a"))})</title></rect>')
    if mark:
        L.append(f'<circle cx="{mark[0]:.3f}" cy="{mark[1]:.3f}" r="{fs * 0.35:.3f}" fill="#c0141b"/>')
    L.append("</svg>")
    # margin figures: eastings along the top and bottom, northings along the sides
    seen_e, seen_n = {}, {}
    for (ii, jj) in tiles:
        e, n = g.en(ii, jj)
        cx, cy = g.center(ii, jj)
        if e not in seen_e or cy < seen_e[e][1]:
            seen_e[e] = (cx, cy)
        if n not in seen_n:
            seen_n[n] = cy
    for e, (cx, _) in seen_e.items():
        lab = f"{e % g.block:0{g.digits}d}"
        L.append(f'<text x="{cx:.3f}" y="{y0 - fs * 0.6:.3f}" font-size="{fs * 1.1:.3f}" text-anchor="middle" fill="#1a3a6b">{lab}</text>')
        L.append(f'<text x="{cx:.3f}" y="{y1 + fs * 1.5:.3f}" font-size="{fs * 1.1:.3f}" text-anchor="middle" fill="#1a3a6b">{lab}</text>')
    for n, cy in seen_n.items():
        lab = f"{n % g.block:0{g.digits}d}"
        L.append(f'<text x="{x0 - fs * 0.5:.3f}" y="{cy + fs * 0.4:.3f}" font-size="{fs * 1.1:.3f}" text-anchor="end" fill="#1a3a6b">{lab}</text>')
        L.append(f'<text x="{x1 + fs * 0.5:.3f}" y="{cy + fs * 0.4:.3f}" font-size="{fs * 1.1:.3f}" fill="#1a3a6b">{lab}</text>')
    e0, n0 = g.en(ci, cj)
    L.append(f'<text x="{x0 - m + fs * 0.4:.3f}" y="{y0 - m + fs * 1.6:.3f}" font-size="{fs * 1.5:.3f}" font-weight="bold">'
             f'{_xml(w.name)}: sheet round {_xml(g.ref(ci, cj))} (square {g.square_letters(e0, n0)})</text>')
    L.append(f'<text x="{x0 - m + fs * 0.4:.3f}" y="{y1 + m - fs * 0.5:.3f}" font-size="{fs * 0.9:.3f}">'
             f'{_xml(g.describe())}. Each tile shows its eastings and northings within the square. '
             f'Thicker lines: every 10 tiles; thickest: square boundaries.</text>')
    L.append("</svg>")
    Path(out_path).write_text("\n".join(L), encoding="utf-8")


# ====================================================================== finding places
def find_places(w: World, g: TileGrid, text):
    q = text.strip().casefold()
    hits = []

    def score(name):
        n = (name or "").casefold()
        if not n or not q:
            return 0
        return 3 if n == q else 2 if n.startswith(q) else 1 if q in n else 0

    def at(x, y):
        i, j = g.locate(x, y)
        return g.ref(i, j), g.point_ref(x, y), (x, y)

    for b in w.live(w.burgs):
        if b.get("i") and score(b["name"]):
            hits.append((score(b["name"]), "burg", f"{b['name']} ({b.get('group') or 'burg'}, {w.state_name(b.get('state', 0))})", at(b["x"], b["y"])))
    for m in w.markers:
        s = max(score(m.get("name")), score(m.get("type")))
        if s:
            hits.append((s, "marker", f"{m.get('name') or m.get('type')} ({m.get('type')})", at(m["x"], m["y"])))
    for s in w.live(w.states):
        sc = max(score(s.get("name")), score(s.get("fullName")))
        cap = w.burg(s.get("capital") or 0)
        if sc and cap:
            hits.append((sc, "state", f"{s.get('fullName') or s['name']} (capital {cap['name']})", at(cap["x"], cap["y"])))
    for p in w.live(w.provinces):
        sc = max(score(p.get("name")), score(p.get("fullName")))
        if sc:
            seat = w.burg(p.get("burg") or 0)
            xy = (seat["x"], seat["y"]) if seat else w.site[p["center"]]
            hits.append((sc, "province", f"{p.get('fullName') or p['name']} ({w.state_name(p.get('state', 0))})", at(*xy)))
    for rid, r in w.rivers.items():
        if score(r.get("name")):
            pts = w.river_courses[rid]["points"]
            if pts:
                tiles = {g.locate(*p) for p in _resample(pts, g.width_px / 3)}
                src, mouth = at(*pts[0]), at(*pts[-1])
                hits.append((score(r["name"]), "river", f"{r['name']} ({r.get('type')}, crosses about {len(tiles)} tiles; "
                             f"source {src[0]}, mouth {mouth[0]})", mouth))
    for r in w.routes:
        if score(r.get("name")):
            pts = [(p[0], p[1]) for p in r["points"]]
            tiles = {g.locate(*p) for p in _resample(pts, g.width_px / 3)}
            a, b = at(*pts[0]), at(*pts[-1])
            hits.append((score(r["name"]), "route", f"{r['name']} ({r.get('group')}, about {len(tiles)} tiles, {a[0]} to {b[0]})", a))
    for z in w.zones:
        if score(z.get("name")) or score(z.get("type")):
            cells = [c for c in z.get("cells", []) if 0 <= c < w.n]
            if cells:
                c = max(cells, key=lambda c: w.cell_area[c])
                hits.append((max(score(z.get("name")), score(z.get("type"))), "zone",
                             f"{z.get('name')} ({z.get('type')}, {len(cells)} cells)", at(*w.cell_centroid[c])))
    for u in w.units:
        if score(u.get("name")):
            hits.append((score(u["name"]), "unit", f"{u['name']} ({w.state_name(u['state'])}, {u.get('a')})", at(u["x"], u["y"])))
    for j in w.journeys:
        if score(j.get("name")):
            segs = [s for s in j.get("segments", []) if s.get("points")]
            if segs:
                p0, p1 = segs[0]["points"][0], segs[-1]["points"][-1]
                hits.append((score(j["name"]), "journey", f"{j['name']} (starts {at(p0[0], p0[1])[0]}, ends {at(p1[0], p1[1])[0]})", at(p0[0], p0[1])))
    for c in w.live(w.cultures):
        if score(c.get("name")) and c.get("center") is not None and 0 <= c["center"] < w.n:
            hits.append((score(c["name"]), "culture", f"{c['name']} (hearth)", at(*w.site[c["center"]])))
    for r in w.live(w.religions):
        if score(r.get("name")) and r.get("center") is not None and 0 <= r["center"] < w.n:
            hits.append((score(r["name"]), "faith", f"{r['name']} (centre)", at(*w.site[r["center"]])))
    hits.sort(key=lambda h: (-h[0], h[1], h[2]))
    return hits


def _resample(pts, step):
    out = [pts[0]] if pts else []
    for a in range(len(pts) - 1):
        p, q = pts[a], pts[a + 1]
        L = math.dist(p, q)
        k = max(1, int(L / step))
        for s in range(1, k + 1):
            out.append((p[0] + (q[0] - p[0]) * s / k, p[1] + (q[1] - p[1]) * s / k))
    return out


def resolve_place(w: World, g: TileGrid, text):
    """Return (i, j, point or None, label) for a grid reference, px:/ll: coordinates or a place name."""
    t = text.strip()
    parsed = g.parse(t)
    if parsed:
        if parsed[0] == "tile":
            return parsed[1], parsed[2], None, g.ref(parsed[1], parsed[2])
        if parsed[0] == "point":
            i, j = g.locate(parsed[1], parsed[2])
            return i, j, (parsed[1], parsed[2]), f"point {t.upper()}"
        e0, n0, size = parsed[1], parsed[2], parsed[3]
        i, j = g.ij(e0 + size // 2, n0 + size // 2)
        return i, j, None, f"block {t.upper()}"
    m = re.fullmatch(r"(px|ll):\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", t, re.I)
    if m:
        a, b = float(m.group(2)), float(m.group(3))
        x, y = (a, b) if m.group(1).lower() == "px" else w.to_px(a, b)
        i, j = g.locate(x, y)
        return i, j, (x, y), f"{m.group(1)}:{a},{b}"
    hits = find_places(w, g, t)
    if not hits:
        raise MapError(f"'{text}' is not a grid reference (e.g. {g.ref((g.imin + g.imax) // 2, (g.jmin + g.jmax) // 2)}) "
                       f"and matches no place name")
    x, y = hits[0][3][2]
    i, j = g.locate(x, y)
    return i, j, (x, y), hits[0][2]


# ====================================================================== interpolated surfaces
# Rules and constants of the interpolation. Distances are in widths of an average land cell, so the
# same rules hold on any map; the coefficients marked "Azgaar" are Azgaar's own.
SURFACE_RULES = {
    "grid_sigma": 0.75,           # Gaussian kernel width for the climate grid, in grid spacings
    "grid_passes": 6,             # residual passes that pull each grid cell's mean back to its value
    "cell_sigma": 1.0,            # kernel width for blending neighbouring cells, in land-cell widths
    "reach": 0.35,                # distance scale of road, river and coast effects, in land-cell widths
    "road_bonus": {"roads": 0.6, "trails": 0.25},   # extra share of people at a road, fading with distance
    "lapse_c_per_km": 6.5,        # Azgaar: temperature drop per km of height
    "route_cost": {"roads": 1.0, "trails": 1.3, "searoutes": 0.5},   # relative cost per unit length
    "off_route_cost": 2.0,        # cost per unit length to reach the network from a burg off it
    "own_market_weight": 1.0,     # extra weight of a point's own market in the price blend (1 = distance only, smooth)
    "smoothing_passes": 3,        # passes that smooth people and goods across cell borders, keeping cell totals
}
COAST_SCORES = {"estuary": 15, "ocean_coast": 5, "save_harbor": 20, "freshwater": 30, "salt": 10, "frozen": 1,
                "dry": -5, "sinkhole": -5, "lava": -30}   # Azgaar's suitability bonus by what a coast faces


class SegIndex:
    """Bucketed line segments with a payload, for nearest-segment queries."""

    def __init__(self, size):
        self.b = Buckets(max(size, 1e-6))
        self.segs = []

    def add(self, p, q, payload=None):
        self.segs.append((p, q, payload))
        self.b.add(len(self.segs) - 1, (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])))

    def nearest(self, x, y, r):
        best_d, best = float("inf"), None
        for k in self.b.query((x - r, y - r, x + r, y + r)):
            p, q, pl = self.segs[k]
            d, _ = point_seg_dist((x, y), p, q)
            if d < best_d:
                best_d, best = d, pl
        return best_d, best


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return 0 if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()).strip("_")
    return s[:40] or "x"


def market_indexes(w: World, eco: Economy):
    """Per market: (id, x, y, centre name, price index, food price index). The price index is the
    market's prices over the mean of all markets, weighted by each good's world output value;
    the food index is the plain mean of that ratio over goods tagged food."""
    weights = {g: v * ((w.goods.get(g) or {}).get("value") or 0) for g, v in eco.world.items()}
    food = {g for g, gd in w.goods.items() if "food" in (gd.get("tags") or [])}
    out = []
    for m in w.markets.values():
        cb = w.burg(m.get("centerBurgId"))
        if not cb:
            continue
        idx = num = fnum_ = fden = 0.0
        for gs, rec in (m.get("goods") or {}).items():
            g = int(gs)
            mp = eco.mean_price.get(g)
            if rec.get("price") is None or not mp:
                continue
            if weights.get(g):
                num += weights[g] * rec["price"] / mp
                idx += weights[g]
            if g in food:
                fnum_ += rec["price"] / mp
                fden += 1
        out.append((m["i"], cb["x"], cb["y"], cb["name"], num / idx if idx else None, fnum_ / fden if fden else None))
    return out


class Surfaces:
    """Continuous estimates of the map's values, evaluated at any point.

    Averages (grid height, temperature, precipitation) are kernel-interpolated, then corrected so the
    mean of the surface over each grid cell returns to the cell's value. Temperature is interpolated as
    sea-level temperature and brought back down with Azgaar's lapse rate at the interpolated height.
    Sums (rural people, rural output of each good) are spread inside their cell by weights built from
    Azgaar's own suitability rule (habitability, rivers, height, coast) plus road proximity, smoothed
    across cell borders, and rescaled so every cell keeps its total exactly."""

    def __init__(self, w: World, eco: Economy):
        self.w, self.eco = w, eco
        d = w.d
        R = SURFACE_RULES
        self.land_cells = [c for c in range(w.n) if not w.water[c] and w.cell_area[c] > 0]
        self.cw = math.sqrt(sum(w.cell_area[c] for c in self.land_cells) / len(self.land_cells)) if self.land_cells else w.grid_spacing
        self.sig_c = R["cell_sigma"] * self.cw
        self.lam = R["reach"] * self.cw
        sp = w.grid_spacing
        self.sig_g = R["grid_sigma"] * sp
        self.sig_mean = math.sqrt(self.sig_g ** 2 + sp ** 2 / 6)  # a cell's mean: the kernel widened by a box of one spacing
        self.r_g = int(math.ceil(2.2 * self.sig_mean / sp)) + 1
        gh, gt, gp = d["grid_h"], d["grid_temp"], d["grid_prec"]
        n = len(w.grid_points)
        # heights: land and sea are fitted apart, so the coast stays a hard edge
        self.land_mask = [1.0 if gh[k] >= 20 else 0.0 for k in range(n)]
        self.sea_mask = [1.0 - v for v in self.land_mask]
        self.coef_hl = self._fit([float(gh[k]) for k in range(n)], self.land_mask)
        self.coef_hs = self._fit([float(gh[k]) for k in range(n)], self.sea_mask)
        self.coef_h = self._fit([float(gh[k]) for k in range(n)])
        self.coef_t = self._fit([gt[k] + self.drop(gh[k]) for k in range(n)])
        self.coef_p = self._fit([float(gp[k]) for k in range(n)])
        # cells
        self.cell_index = Buckets(self.sig_c)
        for c in self.land_cells:
            sx, sy = w.site[c]
            self.cell_index.add(c, (sx, sy, sx, sy))
        self.rho = {c: d["pop"][c] / w.cell_area[c] for c in self.land_cells}
        self.hab = [(w.biomes[b] or {}).get("habitability", 0) if b < len(w.biomes) else 0 for b in range(len(w.biomes))]
        self.rates = defaultdict(dict)   # biome -> {good: rate}
        for g in w.goods.values():
            for b, rate in (g.get("biomeOutput") or {}).items():
                if rate:
                    self.rates[int(b)][g["i"]] = rate
        fl = [f for f in d["fl"] if f]
        self.flux_mean = _median(fl)
        self.flux_max = (max(d["fl"]) + max(d["conf"])) if d["fl"] else 1
        # lines
        reach = 3 * self.lam
        self.roads = {grp: SegIndex(reach) for grp in R["road_bonus"]}
        for r in w.routes:
            grp = r.get("group")
            if grp in self.roads:
                pts = [(p[0], p[1]) for p in r["points"]]
                for a in range(len(pts) - 1):
                    self.roads[grp].add(pts[a], pts[a + 1])
        self.rivers = SegIndex(reach)
        for rid, course in w.river_courses.items():
            pts = course["points"]
            cells = [c for c in w.rivers[rid].get("cells", []) if 0 <= c < w.n]
            for a in range(len(pts) - 1):
                c = cells[min(a, len(cells) - 1)] if cells else None
                term = 0.0
                if c is not None and self.flux_mean and self.flux_max > self.flux_mean:
                    term = min(max((d["fl"][c] + d["conf"][c] - self.flux_mean) / (self.flux_max - self.flux_mean), 0), 1) * 250
                self.rivers.add(pts[a], pts[a + 1], term)
        self.coast = SegIndex(reach)
        for a, b, p, q in w.edges:
            if w.water[a] != w.water[b]:
                wc = a if w.water[a] else b
                f = w.feature(w.cell_feature[wc]) or {}
                score = COAST_SCORES.get(f.get("subtype"), 0) if f.get("type") == "lake" else COAST_SCORES["ocean_coast"]
                self.coast.add(p, q, score)
        # markets: price indexes, blended by distance
        self.mk = market_indexes(w, eco)
        if len(self.mk) > 1:
            nn = [min(math.dist((a[1], a[2]), (b[1], b[2])) for b in self.mk if b is not a) for a in self.mk]
            self.mk_reach = mean(nn)
        else:
            self.mk_reach = max(w.W, w.H)
        self._norms = {}
        self._first_cache = {}
        self._sample_cache = {}
        self._fcache = {}

    # ------------------------------------------------------------ the climate grid
    def drop(self, h):
        return ((h - 18) ** self.w.h_exp / 1000 * SURFACE_RULES["lapse_c_per_km"]) if h >= 20 else 0.0

    def _kernel(self, arrays, x, y, sigma, mask=None):
        """Normalised Gaussian kernel over the grid points near (x, y); mask limits it to some points."""
        w = self.w
        sp = w.grid_spacing
        gx, gy = int(x // sp), int(y // sp)
        r = self.r_g
        s2 = sigma * sigma
        den = 0.0
        nums = [0.0] * len(arrays)
        pts = w.grid_points
        for yy in range(max(0, gy - r), min(w.cellsY, gy + r + 1)):
            base = yy * w.cellsX
            for xx in range(max(0, gx - r), min(w.cellsX, gx + r + 1)):
                k = base + xx
                if mask is not None and not mask[k]:
                    continue
                px, py = pts[k]
                wt = math.exp(-((px - x) ** 2 + (py - y) ** 2) / s2)
                den += wt
                for a, arr in enumerate(arrays):
                    nums[a] += wt * arr[k]
        return [v / den for v in nums] if den > 1e-12 else [None] * len(arrays)

    def _fit(self, values, mask=None):
        """Coefficients whose kernel surface keeps each grid cell's mean at its value (residual passes)."""
        a = list(values)
        pts = self.w.grid_points
        idx = [k for k in range(len(a)) if mask is None or mask[k]]
        for _ in range(SURFACE_RULES["grid_passes"]):
            fitted = {k: self._kernel([a], pts[k][0], pts[k][1], self.sig_mean, mask)[0] for k in idx}
            for k in idx:
                if fitted[k] is not None:
                    a[k] = a[k] + (values[k] - fitted[k])
        return a

    def climate(self, x, y, land):
        """Height (Azgaar's 0-100 scale), temperature (°C) and precipitation (mm) at a point."""
        w = self.w
        sp = w.grid_spacing
        gx, gy = int(x // sp), int(y // sp)
        r = self.r_g
        s2 = self.sig_g ** 2
        den = dl = ds = t = p = hl = hs = h = 0.0
        pts = w.grid_points
        lm = self.land_mask
        for yy in range(max(0, gy - r), min(w.cellsY, gy + r + 1)):
            base = yy * w.cellsX
            for xx in range(max(0, gx - r), min(w.cellsX, gx + r + 1)):
                k = base + xx
                px, py = pts[k]
                wt = math.exp(-((px - x) ** 2 + (py - y) ** 2) / s2)
                den += wt
                t += wt * self.coef_t[k]
                p += wt * self.coef_p[k]
                h += wt * self.coef_h[k]
                if lm[k]:
                    dl += wt
                    hl += wt * self.coef_hl[k]
                else:
                    ds += wt
                    hs += wt * self.coef_hs[k]
        if den <= 1e-12:
            return None
        if land:
            hh = hl / dl if dl > 1e-9 else h / den
            hh = max(hh, 20.0)
        else:
            hh = hs / ds if ds > 1e-9 else h / den
            hh = min(hh, 19.9)
        return {"h": hh, "temp": t / den - self.drop(hh), "prec": max(p / den, 0.0) * 100}

    # ------------------------------------------------------------ people and goods
    def _near_cells(self, x, y):
        r = 2.2 * self.sig_c
        s2 = self.sig_c ** 2
        out = []
        for c in self.cell_index.query((x - r, y - r, x + r, y + r)):
            sx, sy = self.w.site[c]
            d2 = (sx - x) ** 2 + (sy - y) ** 2
            if d2 <= r * r:
                out.append((c, math.exp(-d2 / s2)))
        return out

    def _context(self, x, y, h):
        """Local terms at a point: blended density, Azgaar's suitability terms, and roads."""
        w, d = self.w, self.w.d
        near = self._near_cells(x, y)
        den = sum(wt for _, wt in near) or 1.0
        hab = sum(wt * self.hab[d["biome"][c]] for c, wt in near) / den if near else 0.0
        base = sum(wt * self.rho[c] for c, wt in near) / den if near else 0.0
        reach = 3 * self.lam
        L2 = self.lam ** 2
        dr, term = self.rivers.nearest(x, y, reach)
        river = (term or 0.0) * math.exp(-dr * dr / L2) if term else 0.0
        dc, score = self.coast.nearest(x, y, reach)
        coast = (score or 0.0) * math.exp(-dc * dc / L2) if score else 0.0
        T = hab + river + coast - (h - 50) / 5
        road = 1.0
        for grp, idx in self.roads.items():
            dd, _ = idx.nearest(x, y, reach)
            if dd < float("inf"):
                road = max(road, 1 + SURFACE_RULES["road_bonus"][grp] * math.exp(-dd * dd / L2))
        return {"near": near, "den": den, "T": T, "base": base, "road": road}

    def _rate(self, near, den, g):
        d = self.w.d
        return sum(wt * self.rates[d["biome"][c]].get(g, 0) for c, wt in near) / den if near else 0.0

    def _is_land(self, x, y, c):
        k = self.w.drawn_kind(x, y)
        return (not self.w.water[c]) if k is None else k == "land"

    def _cell_samples(self, c):
        """Sample points inside a cell with their local terms (None where the drawn coast says water)."""
        if c in self._sample_cache:
            return self._sample_cache[c]
        w = self.w
        poly, bb, area = w.cell_poly[c], w.cell_bbox[c], w.cell_area[c]
        step = max(math.sqrt(area) / 7, 1e-6)
        pts = []
        y = bb[1] + step / 2
        while y < bb[3]:
            x = bb[0] + step / 2
            while x < bb[2]:
                if point_in_poly(x, y, poly):
                    pts.append((x, y))
                x += step
            y += step
        if not pts:
            pts = [w.site[c]]
        terms = []
        if not w.water[c]:
            for x, y in pts:
                if self._is_land(x, y, c):
                    cl = self.climate(x, y, True)
                    ctx = self._context(x, y, cl["h"])
                    terms.append((ctx["T"], ctx["base"], ctx["road"]))
                else:
                    terms.append(None)
            if not any(terms):   # the drawn coast leaves no land in the cell: spread it over the cell
                terms = []
                for x, y in pts:
                    ctx = self._context(x, y, 20.0)
                    terms.append((ctx["T"], ctx["base"], ctx["road"]))
        live = [t_[0] for t_ in terms if t_]
        rec = {"pts": pts, "a_s": area / len(pts), "terms": terms, "Tbar": mean(live) if live else 0.0}
        self._sample_cache[c] = rec
        return rec

    def _local(self, x, y, near, den, T, base, road):
        """Weight for people at a point: the blended density, times local suitability against the
        blended suitability of the cells around (continuous across cell borders), times roads."""
        d = self.w.d
        Tm = sum(wt * self._cell_samples(c)["Tbar"] for c, wt in near) / den if near else T
        Sm = sum(wt * d["s"][c] for c, wt in near) / den if near else 0.0
        suit = Sm + (T - Tm) / 5
        factor = max(suit, 0.05 * max(Sm, 1.0)) / max(Sm, 1.0) if Sm > 0 else 0.0
        return base * factor * road, max(suit, 0.0)

    def _first(self, c):
        """First pass: factors that make a cell's own samples add up to its totals."""
        if c in self._first_cache:
            return self._first_cache[c]
        w, d, eco = self.w, self.w.d, self.eco
        S_ = self._cell_samples(c)
        pts, a_s, terms = S_["pts"], S_["a_s"], S_["terms"]
        rural = eco.rural[c]
        out = {"k_pop": 0.0, "k_bio": {}, "bio": {}, "k_bonus": {}, "k_water": {}, "wp": [], "near": []}
        if w.water[c]:
            ws = [math.exp(-(self.coast.nearest(x, y, 6 * self.lam)[0] ** 2) / self.lam ** 2) for x, y in pts]
            tot = sum(ws) * a_s
            for g, q in rural.items():
                out["k_water"][g] = q / tot if tot else q / w.cell_area[c]
            self._first_cache[c] = out
            return out
        tot = 0.0
        per_g = defaultdict(float)
        for (x, y), t_ in zip(pts, terms):
            if not t_:
                out["wp"].append(0.0)
                out["near"].append(None)
                continue
            near = self._near_cells(x, y)
            den = sum(wt for _, wt in near) or 1.0
            wp, _ = self._local(x, y, near, den, *t_)
            out["wp"].append(wp)
            out["near"].append((near, den))
            tot += wp
        n_land = sum(1 for t_ in terms if t_)
        out["k_pop"] = d["pop"][c] * w.pop_scale / (tot * a_s) if tot else 0.0
        bonus_g = d["good"][c]
        for g, q in rural.items():
            bonus = 0.0
            if g == bonus_g:
                bonus = min(round(min(d["pop"][c] * Economy.BONUS_RURAL, Economy.MAX_BONUS) * eco.modifier(g, c), 2), q)
                # Azgaar scales a cell's bonus good with its people, so it follows the people inside the cell
                out["k_bonus"][g] = bonus / (tot * a_s) if tot else (bonus / (n_land * a_s) if n_land else 0.0)
                out["bonus_by_weight"] = bool(tot)
            if q - bonus > 0:
                out["bio"][g] = q - bonus
                tg = sum(wp * self._rate(nd[0], nd[1], g) for wp, nd in zip(out["wp"], out["near"]) if nd)
                out["k_bio"][g] = (q - bonus) / (tg * a_s) if tg else 0.0
        self._first_cache[c] = out
        return out

    def _factor(self, c, it, g=None):
        """Scaling of cell c after `it` smoothing passes (Tobler's pycnophylactic idea): each pass
        blends the factors of neighbouring cells, then rescales so the cell keeps its total."""
        key = (c, it, g)
        if key in self._fcache:
            return self._fcache[key]
        f = self._first(c)
        if it == 0 or self.w.water[c]:
            v = f["k_pop"] if g is None else f["k_bio"].get(g, 0.0)
        else:
            prev = self._factor(c, it - 1, g)
            target = self.w.d["pop"][c] * self.w.pop_scale if g is None else f["bio"].get(g, 0.0)
            integral = 0.0
            for wp, nd in zip(f["wp"], f["near"]):
                if wp and nd:
                    near, den = nd
                    b = self._blend_k(near, c, it - 1, g)
                    integral += b * wp * (self._rate(near, den, g) if g is not None else 1.0)
            integral *= self._cell_samples(c)["a_s"]
            v = prev * target / integral if integral else prev
        self._fcache[key] = v
        return v

    def _blend_k(self, near, c, it=None, g=None):
        """Factors of the cells round a point, blended by the kernel weights."""
        it = SURFACE_RULES["smoothing_passes"] if it is None else it
        num = den = 0.0
        for k, wt in near:
            if self.w.water[k]:
                continue
            v = self._factor(k, it, g)
            if v:
                num += wt * v
                den += wt
        return num / den if den else self._factor(c, it, g)

    def norm(self, c):
        """Final per-cell rescale after the smoothing passes, so each cell keeps its totals exactly."""
        if c in self._norms:
            return self._norms[c]
        f = self._first(c)
        N = SURFACE_RULES["smoothing_passes"]
        out = {"r_pop": 0.0, "r_bio": {}, "k_bonus": f["k_bonus"], "k_water": f["k_water"]}
        if not self.w.water[c] and f["wp"]:
            a_s = self._cell_samples(c)["a_s"]
            tot = 0.0
            per_g = defaultdict(float)
            for wp, nd in zip(f["wp"], f["near"]):
                if not wp or not nd:
                    continue
                near, den = nd
                tot += self._blend_k(near, c, N) * wp
                for g in f["bio"]:
                    per_g[g] += self._blend_k(near, c, N, g) * wp * self._rate(near, den, g)
            P = self.w.d["pop"][c] * self.w.pop_scale
            out["r_pop"] = P / (tot * a_s) if tot else 0.0
            for g, q in f["bio"].items():
                out["r_bio"][g] = q / (per_g[g] * a_s) if per_g.get(g) else 0.0
        self._norms[c] = out
        return out

    # ------------------------------------------------------------ evaluation
    def at(self, x, y, c=None):
        """Every surface at one point. Densities are per square map unit."""
        w, d = self.w, self.w.d
        c = w.cell_at(min(max(x, 0), w.W), min(max(y, 0), w.H)) if c is None else c
        land = self._is_land(x, y, c)
        cl = self.climate(x, y, land) or {"h": 0, "temp": None, "prec": None}
        res = {"cell": c, "land": land, "h": cl["h"], "elev_m": w.height_m(cl["h"]), "temp_c": cl["temp"],
               "prec_mm": cl["prec"], "suitability": None, "density": 0.0, "goods": {}}
        nm = self.norm(c)
        sq = w.scale ** 2
        if not w.water[c] and land:
            ctx = self._context(x, y, cl["h"])
            near, den = ctx["near"], ctx["den"]
            wp, suit = self._local(x, y, near, den, ctx["T"], ctx["base"], ctx["road"])
            res["suitability"] = suit
            res["density"] = nm["r_pop"] * self._blend_k(near, c) * wp / sq
            for g, r in nm["r_bio"].items():
                res["goods"][g] = res["goods"].get(g, 0.0) + r * self._blend_k(near, c, g=g) * wp * self._rate(near, den, g) / sq
            own = self._first(c)
            for g, k in nm["k_bonus"].items():
                res["goods"][g] = res["goods"].get(g, 0.0) + k * (wp if own.get("bonus_by_weight") else 1.0) / sq
        elif w.water[c]:
            dc = self.coast.nearest(x, y, 6 * self.lam)[0]
            wt = math.exp(-dc * dc / self.lam ** 2)
            for g, k in nm["k_water"].items():
                res["goods"][g] = k * wt / sq
        # prices: blend the market indexes by distance, a point's own market weighted up
        own = d["market"][c]
        num = den = fnum_ = fden = 0.0
        best = None
        for mid, mx, my, name, idx, fidx in self.mk:
            dist = math.dist((x, y), (mx, my))
            wt = math.exp(-dist / self.mk_reach) * (SURFACE_RULES["own_market_weight"] if mid == own else 1.0)
            if idx is not None:
                num += wt * idx
                den += wt
            if fidx is not None:
                fnum_ += wt * fidx
                fden += wt
            if mid == own:
                best = (name, dist)
        res["price_index"] = num / den if den else None
        res["food_index"] = fnum_ / fden if fden else None
        res["market"] = best[0] if best else None
        res["market_dist"] = w.miles(best[1]) if best else None
        return res


# ====================================================================== trade over the route network
class TradeNetwork:
    """Every deal routed along Azgaar's routes by least cost, and the load on each route segment."""

    def __init__(self, w: World, eco: Economy):
        import heapq
        self.w = w
        d = w.d
        R = SURFACE_RULES
        self.pos = {}
        adj = defaultdict(dict)
        self.edge_geom = {}
        for r in w.routes:
            mult = R["route_cost"].get(r.get("group"), 1.2)
            pts = r["points"]
            for a in range(len(pts) - 1):
                p, q = pts[a], pts[a + 1]
                ca = p[2] if len(p) > 2 else None
                cb = q[2] if len(q) > 2 else None
                if ca is None or cb is None or ca == cb:
                    continue
                self.pos.setdefault(ca, (p[0], p[1]))
                self.pos.setdefault(cb, (q[0], q[1]))
                cost = math.dist(p[:2], q[:2]) * mult
                if cost < adj[ca].get(cb, float("inf")):
                    adj[ca][cb] = adj[cb][ca] = cost
                    self.edge_geom[(min(ca, cb), max(ca, cb))] = ((p[0], p[1]), (q[0], q[1]), r.get("group"))
        self.adj = adj
        nodes = list(self.pos)
        node_index = Buckets(max(w.W, w.H) / 60)
        for nd in nodes:
            x, y = self.pos[nd]
            node_index.add(nd, (x, y, x, y))

        def attach(cell, xy):
            if cell in self.pos:
                return cell, 0.0
            for rad in (1, 3, 9, 27):
                r = rad * max(w.W, w.H) / 60
                cand = node_index.query((xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r))
                if cand:
                    nd = min(cand, key=lambda n_: math.dist(xy, self.pos[n_]))
                    return nd, math.dist(xy, self.pos[nd]) * R["off_route_cost"]
            return None, 0.0

        def place(kind, ident):
            if kind == "burg":
                b = w.burg(ident)
                return (b["cell"], (b["x"], b["y"]), b["name"]) if b else (None, None, None)
            m = w.markets.get(ident)
            cb = w.burg(m.get("centerBurgId")) if m else None
            return (cb["cell"], (cb["x"], cb["y"]), f"{cb['name']} market") if cb else (None, None, None)

        self.deals = []
        sources = defaultdict(list)
        for k, dl in enumerate(w.deals):
            sc, sxy, sname = place(dl.get("sellerType"), dl.get("seller"))
            bc, bxy, bname = place(dl.get("buyerType"), dl.get("buyer"))
            if sxy is None or bxy is None:
                continue
            value = dl.get("units", 0) * dl.get("price", 0)
            rec = {"i": dl.get("i", k), "good": eco.good_name(dl["good"]), "good_id": dl["good"], "units": dl.get("units", 0),
                   "price": dl.get("price"), "value": value, "tax": dl.get("tax", 0), "seller_type": dl.get("sellerType"),
                   "seller": sname, "buyer_type": dl.get("buyerType"), "buyer": bname, "from": sxy, "to": bxy,
                   "path": [], "routed": None}
            self.deals.append(rec)
            if sc == bc:
                rec["routed"] = 0.0
                continue
            sn, sextra = attach(sc, sxy)
            bn, bextra = attach(bc, bxy)
            if sn is None or bn is None:
                continue
            rec["_s"], rec["_b"], rec["_extra"] = sn, bn, sextra + bextra
            sources[sn].append(rec)
        for src, recs in sources.items():
            dist = {src: 0.0}
            prev = {}
            heap = [(0.0, src)]
            targets = {r["_b"] for r in recs}
            while heap and targets:
                dd, u = heapq.heappop(heap)
                if dd > dist.get(u, float("inf")):
                    continue
                targets.discard(u)
                for v, cost in adj[u].items():
                    nd = dd + cost
                    if nd < dist.get(v, float("inf")):
                        dist[v] = nd
                        prev[v] = u
                        heapq.heappush(heap, (nd, v))
            for rec in recs:
                t = rec["_b"]
                if t != src and t not in prev:
                    continue
                path = [t]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                path.reverse()
                rec["path"] = path
                rec["routed"] = w.miles(sum(math.dist(self.pos[path[a]], self.pos[path[a + 1]]) for a in range(len(path) - 1)))
        self.load = defaultdict(lambda: {"value": 0.0, "units": 0.0, "deals": set(), "goods": Counter()})
        for k, rec in enumerate(self.deals):
            p = rec["path"]
            for a in range(len(p) - 1):
                key = (min(p[a], p[a + 1]), max(p[a], p[a + 1]))
                L = self.load[key]
                L["value"] += rec["value"]
                L["units"] += rec["units"]
                L["deals"].add(k)
                L["goods"][rec["good"]] += rec["value"]
        self.load_index = Buckets(max(w.W, w.H) / 200)
        self.load_keys = list(self.load)
        for k, key in enumerate(self.load_keys):
            p, q, _ = self.edge_geom[key]
            self.load_index.add(k, (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])))

    def through(self, poly, bb):
        """Value and number of the distinct deals whose route crosses a polygon."""
        deals, goods = set(), Counter()
        for k in self.load_index.query(bb):
            key = self.load_keys[k]
            p, q, _ = self.edge_geom[key]
            if clip_segment(p, q, poly):
                deals |= self.load[key]["deals"]
        value = sum(self.deals[k]["value"] for k in deals)
        for k in deals:
            goods[self.deals[k]["good"]] += self.deals[k]["value"]
        return value, len(deals), goods.most_common(1)[0][0] if goods else None


# ====================================================================== GIS export (GeoJSON, GeoPackage)
WGS84_WKT = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
             'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
             'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]')
UNIT_NAMES = {"km": "kilometre", "mi": "mile", "lg": "league", "vr": "verst", "nmi": "nautical mile", "nlg": "nautical league"}
LOCAL_SRS_ID = 990001


class Projector:
    """Map pixels to the export's coordinates.
    lonlat: the longitude and latitude Azgaar writes in its own GeoJSON exports, so these layers lie
            on top of the Cells, Burgs, Routes, Rivers and Markers exports (EPSG:4326 axes).
    units:  eastings and northings in the map's distance unit from the map's south-west corner,
            so lengths and areas in a GIS come out in the world's own miles (or km, leagues...)."""

    def __init__(self, w: World, crs):
        self.w, self.crs = w, crs
        if crs == "lonlat":
            self.srs_id, self.wkt = 4326, WGS84_WKT
            self.srs_name = "WGS 84 (Azgaar map coordinates)"
        else:
            metres = KM_PER_UNIT.get(w.unit, 1.0) * 1000
            self.srs_id = LOCAL_SRS_ID
            self.srs_name = f"{w.name} map grid ({w.unit})"
            self.wkt = (f'LOCAL_CS["{w.name} map grid ({w.unit})",LOCAL_DATUM["Azgaar map",32767],'
                        f'UNIT["{UNIT_NAMES.get(w.unit, w.unit)}",{metres}],AXIS["Easting",EAST],AXIS["Northing",NORTH]]')

    def __call__(self, x, y):
        if self.crs == "lonlat":
            lon, lat = self.w.to_lonlat(x, y)
            return (round(lon, 7), round(lat, 7))
        return (round(x * self.w.scale, 4), round((self.w.H - y) * self.w.scale, 4))

    def ring(self, pts):
        r = [self(x, y) for x, y in pts]
        if r and r[0] != r[-1]:
            r.append(r[0])
        if signed_area(r[:-1]) < 0:   # exterior rings counter-clockwise (RFC 7946)
            r.reverse()
        return r

    def point(self, x, y):
        return {"type": "Point", "coordinates": self(x, y)}

    def line(self, pts):
        return {"type": "LineString", "coordinates": [self(x, y) for x, y in pts]}

    def polygon(self, pts):
        return {"type": "Polygon", "coordinates": [self.ring(pts)]}

    def multipolygon(self, rings):
        return {"type": "MultiPolygon", "coordinates": [[self.ring(r)] for r in rings if len(r) >= 3]}

    def nested(self, polys):
        """[(exterior, [holes])] -> MultiPolygon, exteriors counter-clockwise and holes clockwise."""
        coords = []
        for ext, holes in polys:
            rr = [self.ring(ext)]
            for h in holes:
                hr = self.ring(h)
                hr.reverse()
                rr.append(hr)
            coords.append(rr)
        return {"type": "MultiPolygon", "coordinates": coords}

    def multiline(self, lines):
        return {"type": "MultiLineString", "coordinates": [[self(x, y) for x, y in l] for l in lines if len(l) >= 2]}


class GeoJSONOut:
    """One GeoJSON file per layer: '<base> <layer>.geojson'."""

    def __init__(self, base, proj):
        self.base, self.proj = base, proj
        self.layers = {}

    def layer(self, name, gtype, fields):
        self.layers[name] = []

    def add(self, name, geom, props):
        self.layers[name].append({"type": "Feature", "geometry": geom, "properties": props})

    def close(self):
        written = []
        for name, feats in self.layers.items():
            if not feats:
                continue
            path = Path(f"{self.base} {name}.geojson")
            doc = {"type": "FeatureCollection", "name": name, "features": feats}
            if self.proj.crs != "lonlat":
                doc["crs_note"] = self.proj.wkt  # GeoJSON has no slot for a local grid; GIS users set it by hand
            path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            written.append(path)
        return written


def _wkb(geom):
    import struct
    t, c = geom["type"], geom["coordinates"]
    pts = lambda seq: b"".join(struct.pack("<dd", p[0], p[1]) for p in seq)
    if t == "Point":
        return struct.pack("<BIdd", 1, 1, c[0], c[1])
    if t == "LineString":
        return struct.pack("<BII", 1, 2, len(c)) + pts(c)
    if t == "Polygon":
        return struct.pack("<BII", 1, 3, len(c)) + b"".join(struct.pack("<I", len(r)) + pts(r) for r in c)
    if t == "MultiLineString":
        return struct.pack("<BII", 1, 5, len(c)) + b"".join(_wkb({"type": "LineString", "coordinates": l}) for l in c)
    if t == "MultiPolygon":
        return struct.pack("<BII", 1, 6, len(c)) + b"".join(_wkb({"type": "Polygon", "coordinates": p}) for p in c)
    raise ValueError(t)


def _flat_coords(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        return [c]
    if t == "LineString":
        return c
    if t in ("Polygon", "MultiLineString"):
        return [p for part in c for p in part]
    return [p for poly in c for ring in poly for p in ring]


class GpkgOut:
    """A GeoPackage (OGC 12-128r18) written with sqlite3: every layer in one file."""

    GTYPES = {"Point": "POINT", "LineString": "LINESTRING", "Polygon": "POLYGON",
              "MultiLineString": "MULTILINESTRING", "MultiPolygon": "MULTIPOLYGON"}

    def __init__(self, path, proj):
        import sqlite3
        self.path, self.proj = Path(path), proj
        if self.path.exists():
            self.path.unlink()
        self.con = sqlite3.connect(str(self.path))
        c = self.con
        c.execute("PRAGMA application_id = 1196444487")
        c.execute("PRAGMA user_version = 10200")
        c.execute("CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY, "
                  "organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT)")
        rows = [("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
                ("WGS 84 geodetic", 4326, "EPSG", 4326, WGS84_WKT, "longitude/latitude coordinates in decimal degrees")]
        if proj.srs_id not in (4326, 0, -1):
            rows.append((proj.srs_name, proj.srs_id, "NONE", proj.srs_id, proj.wkt, "Azgaar map, eastings and northings"))
        c.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", rows)
        c.execute("CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, "
                  "identifier TEXT UNIQUE, description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT "
                  "(strftime('%Y-%m-%dT%H:%M:%fZ','now')), min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, "
                  "srs_id INTEGER, CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id))")
        c.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL, "
                  "geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL, "
                  "CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name), "
                  "CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name), "
                  "CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id))")
        self.layers = {}

    def layer(self, name, gtype, fields):
        self.layers[name] = {"gtype": gtype, "fields": [f for f, _ in fields], "types": fields, "rows": [], "env": None}

    def add(self, name, geom, props):
        import struct
        L = self.layers[name]
        xy = _flat_coords(geom)
        if not xy:
            return
        minx, maxx = min(p[0] for p in xy), max(p[0] for p in xy)
        miny, maxy = min(p[1] for p in xy), max(p[1] for p in xy)
        blob = b"GP" + bytes([0, 0b00000011]) + struct.pack("<i", self.proj.srs_id) + \
            struct.pack("<dddd", minx, maxx, miny, maxy) + _wkb(geom)
        e = L["env"]
        L["env"] = (minx, miny, maxx, maxy) if e is None else (min(e[0], minx), min(e[1], miny), max(e[2], maxx), max(e[3], maxy))
        vals = []
        for f in L["fields"]:
            v = props.get(f)
            vals.append(int(v) if isinstance(v, bool) else v)
        L["rows"].append([blob] + vals)

    def close(self):
        c = self.con
        for name, L in self.layers.items():
            if not L["rows"]:
                continue
            decl = ", ".join(f'"{f}" {t}' for f, t in L["types"])
            c.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, geom {self.GTYPES[L["gtype"]]}'
                      + (f", {decl}" if decl else "") + ")")
            cols = ", ".join(["geom"] + [f'"{f}"' for f in L["fields"]])
            marks = ", ".join("?" * (1 + len(L["fields"])))
            c.executemany(f'INSERT INTO "{name}" ({cols}) VALUES ({marks})', L["rows"])
            env = L["env"] or (0, 0, 0, 0)
            c.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, min_x, min_y, max_x, max_y, srs_id) "
                      "VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?)", (name, name, f"{name} ({len(L['rows'])} features)", *env, self.proj.srs_id))
            c.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)", (name, self.GTYPES[L["gtype"]], self.proj.srs_id))
        c.commit()
        c.close()
        return [self.path]


def _neighbour_offsets(g: TileGrid):
    """Lattice offset of the neighbour across each edge, for each row (or column) parity."""
    def parity(i, j):
        return (i % 2) if g.kind == "flatHex" else (0 if g.kind == "square" else j % 2)
    ci, cj = (g.imin + g.imax) // 2, (g.jmin + g.jmax) // 2
    offs = {}
    for di in (0, 1):
        for dj in (0, 1):
            i, j = ci + di, cj + dj
            key = parity(i, j)
            if key in offs:
                continue
            cx, cy = g.center(i, j)
            p = g.poly(i, j)
            row = []
            for a in range(len(p)):
                mx, my = (p[a][0] + p[(a + 1) % len(p)][0]) / 2, (p[a][1] + p[(a + 1) % len(p)][1]) / 2
                ni, nj = g.locate(cx + 2 * (mx - cx), cy + 2 * (my - cy))
                row.append((ni - i, nj - j))
            offs[key] = row
    return offs, parity


def group_outline(g: TileGrid, offs, parity, e0, n0, size):
    """Outline of a block of tiles (a lettered square or a 10 x 10 block), along the tile edges."""
    e1, n1 = min(e0 + size, g.ncols) - 1, min(n0 + size, g.nrows) - 1
    if e1 < e0 or n1 < n0:
        return []
    edge_group = e0 == 0 or n0 == 0 or e1 == g.ncols - 1 or n1 == g.nrows - 1

    def inside(i, j):
        e, n = g.en(i, j)
        return e0 <= e <= e1 and n0 <= n <= n1 and g.exists(i, j)

    segs = []
    for e in range(e0, e1 + 1):
        for n in range(n0, n1 + 1):
            if not edge_group and e not in (e0, e1) and n not in (n0, n1):
                continue
            i, j = g.ij(e, n)
            if not g.exists(i, j):
                continue
            p = g.poly(i, j)
            for a, (di, dj) in enumerate(offs[parity(i, j)]):
                if not inside(i + di, j + dj):
                    segs.append((p[a], p[(a + 1) % len(p)]))
    rings = [r for r in chain_segments(segs) if len(r) >= 4]
    rings.sort(key=lambda r: -poly_area(r))
    return rings


def tile_summary(w: World, g: TileGrid, i, j, eco: Economy, idx, full=True):
    """One row of the tiles layer. Light rows read the cell under the centre; full rows clip cells
    against the tile (as the report does) and add the lines and points inside it."""
    cx, cy = g.center(i, j)
    e, n = g.en(i, j)
    b, dg = g.block, g.digits
    lon, lat = w.to_lonlat(cx, cy)
    row = {"ref": g.ref(i, j), "square": g.square_letters(e, n), "east": e % b, "north": n % b,
           "east_all": e, "north_all": n, "block10": f"{g.square_letters(e, n)} {(e % b) // 10} {(n % b) // 10}" if b >= 100 else None,
           "lon": round(lon, 5), "lat": round(lat, 5)}
    d = w.d
    if not full:
        c = w.cell_at(min(max(cx, 0), w.W), min(max(cy, 0), w.H))
        land = not w.water[c]
        row.update(cell=c, land=land, state=w.state_name(d["state"][c]) if land else None,
                   province=(w.province(d["province"][c]) or {}).get("name") if land else None,
                   culture=w.culture(d["culture"][c]).get("name") if land else None,
                   religion=w.religion(d["religion"][c]).get("name") if land else None,
                   biome=w.biome_name(d["biome"][c]), height=w.cell_height_disp[c])
        return row
    t = Tile(w, g, i, j)
    t._overlap()
    t._samples()
    land_ov = [o for o in t.ov if not w.water[o["cell"]]]

    def dominant(key, pool, namer):
        acc = defaultdict(float)
        for o in pool:
            acc[d[key][o["cell"]]] += o["of_tile"]
        if not acc:
            return None, 0.0, []
        top = max(acc, key=acc.get)
        return namer(top), acc[top], [namer(k) for k, _ in sorted(acc.items(), key=lambda kv: -kv[1])]

    st, st_share, st_all = dominant("state", land_ov, w.state_name)
    pv, _, _ = dominant("province", land_ov, lambda p: (w.province(p) or {}).get("name"))
    cu, cu_share, _ = dominant("culture", land_ov, lambda c: w.culture(c).get("name"))
    rl, _, _ = dominant("religion", land_ov, lambda r: w.religion(r).get("name"))
    bi, bi_share, _ = dominant("biome", t.ov, w.biome_name)
    burgs = [w.burg(k) for k in idx["burgs"].query(t.bbox)]
    burgs = [x for x in burgs if x and t.inside(x["x"], x["y"])]
    rural = sum(d["pop"][o["cell"]] * o["of_cell"] for o in t.ov) * w.pop_scale
    urban = sum(w.burg_people(x) for x in burgs)
    land_sq = w.sq(t.land_area)
    gh, gt, gp = d["grid_h"], d["grid_temp"], d["grid_prec"]
    elev = mean(w.height_disp(w.height_m(gh[s["g"]])) for s in t.samples)
    temp = mean(gt[s["g"]] for s in t.samples)
    prec = mean(gp[s["g"]] * 100 for s in t.samples)
    zones = sorted({z.get("name") for z in w.zones for o in t.ov if o["cell"] in w.zone_cells[z["i"]]})
    markers = [m.get("name") or m.get("type") for m in w.markers if t.inside(m["x"], m["y"])]

    def crossing(kind):
        names, length = [], 0.0
        for k in idx[kind].query(t.bbox):
            name, pts = idx[kind + "_lines"][k]
            pieces = polyline_pieces(pts, t.poly)
            if pieces:
                names.append(name)
                length += sum(p[1] - p[0] for p in pieces)
        return sorted(set(n for n in names if n)), w.miles(length)

    rivers, river_len = crossing("rivers")
    routes, route_len = crossing("routes")
    journeys, _ = crossing("journeys")
    border_len, border_with = 0.0, set()
    for k in w.edge_index.query(t.bbox):
        a, bb, p, q = w.edges[k]
        if not w.water[a] and not w.water[bb] and d["state"][a] != d["state"][bb]:
            r = clip_segment(p, q, t.poly)
            if r:
                border_len += (r[1] - r[0]) * math.dist(p, q)
                border_with.update({w.state_name(d["state"][a]), w.state_name(d["state"][bb])})
    value, by_good = 0.0, defaultdict(float)
    for o in t.ov:
        for gid, v in eco.rural[o["cell"]].items():
            by_good[gid] += v * o["of_cell"]
    for x in burgs:
        for gid, v in eco.urban.get(x["i"], {}).items():
            by_good[gid] += v
    for gid, v in by_good.items():
        value += v * ((w.goods.get(gid) or {}).get("value") or 0)
    top_good = max(by_good, key=lambda gid: by_good[gid] * ((w.goods.get(gid) or {}).get("value") or 0)) if by_good else None
    row.update(land_share=round(t.land_area / t.area_px, 4),
               drawn_land=round(t.drawn_land, 4) if t.drawn_land is not None else None,
               rural=round(rural, 1), urban=round(urban, 1), people=round(rural + urban, 1),
               density=round((rural + urban) / land_sq, 2) if land_sq else None,
               state=st, state_share=round(st_share, 4), states="; ".join(x for x in st_all if x) or None,
               province=pv, culture=cu, culture_share=round(cu_share, 4), religion=rl, biome=bi,
               biome_share=round(bi_share, 4), elevation=round(elev, 1), temp_c=round(temp, 1), prec_mm=round(prec),
               zones="; ".join(z for z in zones if z) or None, burgs="; ".join(x["name"] for x in burgs) or None,
               markers="; ".join(x for x in markers if x) or None, rivers="; ".join(rivers) or None,
               river_len=round(river_len, 3), routes="; ".join(routes) or None, route_len=round(route_len, 3),
               journeys="; ".join(journeys) or None, border_len=round(w.miles(border_len), 3),
               border_with="; ".join(sorted(x for x in border_with if x and x != st)) or None,
               output_value=round(value, 3), top_good=eco.good_name(top_good) if top_good else None,
               cells=len(t.ov))
    return row


TILE_FIELDS_LIGHT = [("ref", "TEXT"), ("square", "TEXT"), ("east", "INTEGER"), ("north", "INTEGER"), ("east_all", "INTEGER"),
                     ("north_all", "INTEGER"), ("block10", "TEXT"), ("lon", "REAL"), ("lat", "REAL"), ("cell", "INTEGER"),
                     ("land", "INTEGER"), ("state", "TEXT"), ("province", "TEXT"), ("culture", "TEXT"), ("religion", "TEXT"),
                     ("biome", "TEXT"), ("height", "REAL")]
TILE_FIELDS_FULL = TILE_FIELDS_LIGHT[:9] + [
    ("land_share", "REAL"), ("drawn_land", "REAL"), ("rural", "REAL"), ("urban", "REAL"), ("people", "REAL"), ("density", "REAL"),
    ("state", "TEXT"), ("state_share", "REAL"), ("states", "TEXT"), ("province", "TEXT"), ("culture", "TEXT"),
    ("culture_share", "REAL"), ("religion", "TEXT"), ("biome", "TEXT"), ("biome_share", "REAL"), ("elevation", "REAL"),
    ("temp_c", "REAL"), ("prec_mm", "INTEGER"), ("zones", "TEXT"), ("burgs", "TEXT"), ("markers", "TEXT"), ("rivers", "TEXT"),
    ("river_len", "REAL"), ("routes", "TEXT"), ("route_len", "REAL"), ("journeys", "TEXT"), ("border_len", "REAL"),
    ("border_with", "TEXT"), ("output_value", "REAL"), ("top_good", "TEXT"), ("cells", "INTEGER")]

LAYERS = ["tiles", "centres", "blocks", "squares", "land", "zones", "borders", "rivers", "routes", "journeys", "stops",
          "burgs", "markers", "units", "markets", "deals", "traffic"]

SURFACE_FIELDS = [("ref", "TEXT"), ("square", "TEXT"), ("east", "INTEGER"), ("north", "INTEGER"), ("lon", "REAL"),
                  ("lat", "REAL"), ("cell", "INTEGER"), ("land", "INTEGER"), ("state", "TEXT"), ("h", "REAL"),
                  ("elevation", "REAL"), ("elev_m", "REAL"), ("temp_c", "REAL"), ("temp", "REAL"), ("prec_mm", "REAL"),
                  ("suitability", "REAL"), ("density", "REAL"), ("rural", "REAL"), ("urban", "REAL"), ("people", "REAL"),
                  ("output_value", "REAL"), ("rural_value", "REAL"), ("urban_value", "REAL"), ("top_good", "TEXT"), ("sales_tax", "REAL"), ("poll_tax", "REAL"),
                  ("treasury", "REAL"), ("alert", "REAL"), ("market", "TEXT"), ("market_dist", "REAL"),
                  ("price_index", "REAL"), ("food_index", "REAL"), ("trade_value", "REAL"), ("trade_deals", "INTEGER"),
                  ("trade_top", "TEXT")]


def surface_row(w: World, g: TileGrid, S: Surfaces, net, i, j, burg_idx):
    """Interpolated values at a tile's centre, scaled to the tile (midpoint rule), plus the
    as-is values of the cell, state and market there."""
    d = w.d
    cx, cy = g.center(i, j)
    e, n = g.en(i, j)
    lon, lat = w.to_lonlat(cx, cy)
    s = S.at(cx, cy)
    c = s["cell"]
    area = w.sq(g.area_px)
    poly = g.poly(i, j)
    bb = bbox_of(poly)
    burgs = [w.burg(k) for k in burg_idx.query(bb)]
    burgs = [b for b in burgs if b and point_in_poly(b["x"], b["y"], poly)]
    urban = sum(w.burg_people(b) for b in burgs)
    rural = s["density"] * area
    goods = {gid: v * area for gid, v in s["goods"].items() if v > 0}
    price = lambda gid: (w.goods.get(gid) or {}).get("value") or 0
    rural_value = sum(u * price(gid) for gid, u in goods.items())
    town = defaultdict(float)
    for b in burgs:   # town output stays where the data puts it
        for gid, u in S.eco.urban.get(b["i"], {}).items():
            town[gid] += u
    urban_value = sum(u * price(gid) for gid, u in town.items())
    value = rural_value + urban_value
    allg = defaultdict(float, goods)
    for gid, u in town.items():
        allg[gid] += u
    top = max(allg, key=lambda gid: allg[gid] * price(gid)) if allg else None
    st = w.state(d["state"][c]) if not w.water[c] else None
    tv, tn, tt = net.through(poly, bb) if net else (None, None, None)
    row = {"ref": g.ref(i, j), "square": g.square_letters(e, n), "east": e % g.block, "north": n % g.block,
           "lon": round(lon, 5), "lat": round(lat, 5), "cell": c, "land": s["land"],
           "state": w.state_name(d["state"][c]) if st else None, "h": round(s["h"], 2),
           "elevation": round(w.height_disp(s["elev_m"]), 1), "elev_m": round(s["elev_m"], 1),
           "temp_c": round(s["temp_c"], 2) if s["temp_c"] is not None else None,
           "temp": round(w.temp_disp(s["temp_c"]), 2) if s["temp_c"] is not None else None,
           "prec_mm": round(s["prec_mm"], 1) if s["prec_mm"] is not None else None,
           "suitability": round(s["suitability"], 2) if s["suitability"] is not None else None,
           "density": round(s["density"], 3), "rural": round(rural, 1), "urban": round(urban, 1),
           "people": round(rural + urban, 1), "output_value": round(value, 4), "rural_value": round(rural_value, 4),
           "urban_value": round(urban_value, 4),
           "top_good": S.eco.good_name(top) if top else None,
           "sales_tax": st.get("salesTax") if st else None, "poll_tax": st.get("pollTax") if st else None,
           "treasury": st.get("treasury") if st else None, "alert": st.get("alert") if st else None,
           "market": s["market"], "market_dist": round(s["market_dist"], 2) if s["market_dist"] is not None else None,
           "price_index": round(s["price_index"], 4) if s["price_index"] is not None else None,
           "food_index": round(s["food_index"], 4) if s["food_index"] is not None else None,
           "trade_value": round(tv, 3) if tv is not None else None, "trade_deals": tn, "trade_top": tt}
    return row, goods


def export_gis(w: World, g: TileGrid, out_base, fmt="geojson", crs="lonlat", window=None, tile_list=None,
               tiles="full", layers=None, legacy_speeds=False, log=print, surfaces=True):
    """Write the grid and the map's layers. window=None exports the whole map."""
    proj = Projector(w, crs)
    out = GpkgOut(f"{out_base}.gpkg", proj) if fmt == "gpkg" else GeoJSONOut(out_base, proj)
    want = set(layers or LAYERS)
    if not surfaces:
        want.discard("centres")
    win = window or (0.0, 0.0, w.W, w.H)
    d = w.d
    eco = Economy(w)
    unit = w.unit

    # line and point indexes shared by the tile rows
    idx = {"burgs": Buckets(max(g.width_px, 1)), "rivers": Buckets(max(g.width_px * 4, 1)),
           "routes": Buckets(max(g.width_px * 4, 1)), "journeys": Buckets(max(g.width_px * 4, 1)),
           "rivers_lines": [], "routes_lines": [], "journeys_lines": []}
    for b in w.live(w.burgs):
        if b.get("i"):
            idx["burgs"].add(b["i"], (b["x"], b["y"], b["x"], b["y"]))
    for rid, c in w.river_courses.items():
        if len(c["points"]) >= 2:
            idx["rivers_lines"].append((w.rivers[rid].get("name"), c["points"]))
            idx["rivers"].add(len(idx["rivers_lines"]) - 1, bbox_of(c["points"]))
    for r in w.routes:
        pts = [(p[0], p[1]) for p in r["points"]]
        if len(pts) >= 2:
            idx["routes_lines"].append((r.get("name") or f"unnamed {ROUTE_KIND.get(r.get('group'), 'route')} (route {r.get('i')})", pts))
            idx["routes"].add(len(idx["routes_lines"]) - 1, bbox_of(pts))
    plans = [JourneyPlan(w, j, legacy_speeds) for j in w.journeys]
    for plan in plans:
        for s in plan.segments:
            if s["visible"] and not s["stay"] and len(s["xy"]) >= 2:
                idx["journeys_lines"].append((plan.name, s["xy"]))
                idx["journeys"].add(len(idx["journeys_lines"]) - 1, bbox_of(s["xy"]))

    def in_win(x, y):
        return win[0] <= x <= win[2] and win[1] <= y <= win[3]

    def all_tiles():
        return [(i, j) for i in range(g.imin, g.imax + 1) for j in range(g.jmin, g.jmax + 1) if g.exists(i, j)]

    # ---- interpolated surfaces at tile centres, and the trade network
    S = net = None
    if "centres" in want or "traffic" in want or "deals" in want or "markets" in want:
        net = TradeNetwork(w, eco)
    surf_rows = {}
    goods_seen = {}
    if "centres" in want:
        S = Surfaces(w, eco)
        if tile_list is None:
            tile_list = all_tiles()
        for k, (i, j) in enumerate(tile_list):
            row, goods = surface_row(w, g, S, net, i, j, idx["burgs"])
            for gid, u in goods.items():
                goods_seen[gid] = goods_seen.get(gid, 0) + u
            surf_rows[(i, j)] = (row, goods)
            if log and len(tile_list) > 2000 and k and k % 20000 == 0:
                log(f"  surfaces: {k:,} of {len(tile_list):,}")
        good_cols = []
        used = set()
        for gid in sorted(goods_seen, key=lambda x: -goods_seen[x]):
            col = "g_" + slug(eco.good_name(gid))
            while col in used:
                col += "_"
            used.add(col)
            good_cols.append((gid, col))
        out.layer("centres", "Point", SURFACE_FIELDS + [(col, "REAL") for _, col in good_cols])
        for (i, j), (row, goods) in surf_rows.items():
            for gid, col in good_cols:
                row[col] = round(goods.get(gid, 0.0), 5)
            out.add("centres", proj.point(*g.center(i, j)), row)
    # ---- tiles
    if "tiles" in want and tiles != "none":
        full = tiles == "full"
        fields = list(TILE_FIELDS_FULL if full else TILE_FIELDS_LIGHT)
        extra = [("i_" + f, t) for f, t in SURFACE_FIELDS[6:]] if surf_rows else []
        out.layer("tiles", "Polygon", fields + extra)
        if tile_list is None:
            tile_list = all_tiles()
        for k, (i, j) in enumerate(tile_list):
            row = tile_summary(w, g, i, j, eco, idx, full)
            if (i, j) in surf_rows:
                sr = surf_rows[(i, j)][0]
                for f, _ in SURFACE_FIELDS[6:]:
                    row["i_" + f] = sr.get(f)
            out.add("tiles", proj.polygon(g.poly(i, j)), row)
            if log and len(tile_list) > 2000 and k and k % 20000 == 0:
                log(f"  tiles: {k:,} of {len(tile_list):,}")
    # ---- trade as it is in the data, and its load on the routes
    if "deals" in want and net:
        out.layer("deals", "LineString", [("deal", "INTEGER"), ("good", "TEXT"), ("units", "REAL"), ("price", "REAL"),
                                          ("value", "REAL"), ("tax", "REAL"), ("seller_type", "TEXT"), ("seller", "TEXT"),
                                          ("buyer_type", "TEXT"), ("buyer", "TEXT"), ("routed_len", "REAL")])
        for rec in net.deals:
            a_, b_ = rec["from"], rec["to"]
            if a_ == b_:
                b_ = (b_[0] + 1e-6, b_[1] + 1e-6)
            bb = (min(a_[0], b_[0]), min(a_[1], b_[1]), max(a_[0], b_[0]), max(a_[1], b_[1]))
            if bbox_hit(bb, win):
                out.add("deals", proj.line([a_, b_]), {
                    "deal": rec["i"], "good": rec["good"], "units": rec["units"], "price": rec["price"],
                    "value": round(rec["value"], 4), "tax": rec["tax"], "seller_type": rec["seller_type"], "seller": rec["seller"],
                    "buyer_type": rec["buyer_type"], "buyer": rec["buyer"],
                    "routed_len": round(rec["routed"], 2) if rec["routed"] is not None else None})
    if "traffic" in want and net:
        out.layer("traffic", "LineString", [("group", "TEXT"), ("value", "REAL"), ("units", "REAL"), ("deals", "INTEGER"),
                                            ("top_good", "TEXT"), ("top_value", "REAL")])
        for key, L in net.load.items():
            p, q, grp = net.edge_geom[key]
            if bbox_hit((min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])), win):
                tg = L["goods"].most_common(1)[0] if L["goods"] else (None, None)
                out.add("traffic", proj.line([p, q]), {"group": grp, "value": round(L["value"], 3), "units": round(L["units"], 3),
                                                       "deals": len(L["deals"]), "top_good": tg[0],
                                                       "top_value": round(tg[1], 3) if tg[1] is not None else None})
    if "markets" in want:
        out.layer("markets", "Point", [("market", "INTEGER"), ("centre", "TEXT"), ("ref", "TEXT"), ("burgs", "INTEGER"),
                                       ("cells", "INTEGER"), ("export_value", "REAL"), ("import_value", "REAL"),
                                       ("price_index", "REAL"), ("food_index", "REAL")])
        mk = {m[0]: m for m in (S.mk if S else market_indexes(w, eco))}
        for m in w.markets.values():
            cb = w.burg(m.get("centerBurgId"))
            if not cb or not in_win(cb["x"], cb["y"]):
                continue
            ex = sum(dl["units"] * dl["price"] for dl in eco.flows.get(m["i"], []) if dl["seller"] == m["i"])
            im = sum(dl["units"] * dl["price"] for dl in eco.flows.get(m["i"], []) if dl["buyer"] == m["i"])
            out.add("markets", proj.point(cb["x"], cb["y"]), {
                "market": m["i"], "centre": cb["name"], "ref": g.ref(*g.locate(cb["x"], cb["y"])),
                "burgs": sum(1 for b in w.live(w.burgs) if b.get("i") and b.get("market") == m["i"]),
                "cells": sum(1 for c in range(w.n) if d["market"][c] == m["i"]),
                "export_value": round(ex, 3), "import_value": round(im, 3),
                "price_index": round(mk[m["i"]][4], 4) if m["i"] in mk and mk[m["i"]][4] is not None else None,
                "food_index": round(mk[m["i"]][5], 4) if m["i"] in mk and mk[m["i"]][5] is not None else None})
    # ---- lettered squares and 10 x 10 blocks, along the tile edges
    if "squares" in want or "blocks" in want:
        offs, parity = _neighbour_offsets(g)
        e_lo = max(0, int((win[0] - g.x_origin) / g.step_x) - 1)
        e_hi = min(g.ncols - 1, int((win[2] - g.x_origin) / g.step_x) + 1)
        n_lo = max(0, int((g.y_origin - win[3]) / g.step_y) - 1)
        n_hi = min(g.nrows - 1, int((g.y_origin - win[1]) / g.step_y) + 1)
        if "squares" in want:
            out.layer("squares", "Polygon", [("square", "TEXT"), ("east_from", "INTEGER"), ("north_from", "INTEGER"),
                                             ("tiles_across", "INTEGER")])
            for be in range(e_lo // g.block, e_hi // g.block + 1):
                for bn in range(n_lo // g.block, n_hi // g.block + 1):
                    rings = group_outline(g, offs, parity, be * g.block, bn * g.block, g.block)
                    if rings:
                        out.add("squares", proj.polygon(rings[0]), {"square": LETTERS[be] + LETTERS[bn], "east_from": be * g.block,
                                                                    "north_from": bn * g.block, "tiles_across": g.block})
        if "blocks" in want and g.block >= 100:
            out.layer("blocks", "Polygon", [("block", "TEXT"), ("square", "TEXT"), ("east", "INTEGER"), ("north", "INTEGER")])
            for e10 in range(e_lo // 10, e_hi // 10 + 1):
                for n10 in range(n_lo // 10, n_hi // 10 + 1):
                    rings = group_outline(g, offs, parity, e10 * 10, n10 * 10, 10)
                    if rings:
                        sq = g.square_letters(e10 * 10, n10 * 10)
                        e_in, n_in = (e10 * 10) % g.block // 10, (n10 * 10) % g.block // 10
                        out.add("blocks", proj.polygon(rings[0]), {"block": f"{sq} {e_in} {n_in}", "square": sq,
                                                                   "east": e_in * 10, "north": n_in * 10})
    # ---- Azgaar's drawn land and lakes
    if "land" in want and w.feature_rings:
        out.layer("land", "MultiPolygon", [("feature", "INTEGER"), ("name", "TEXT"), ("type", "TEXT"), ("subtype", "TEXT"),
                                           ("area", "REAL"), ("cells", "INTEGER")])
        for fid, rings in w.feature_rings.items():
            f = w.feature(fid) or {}
            rs = [r for r, bb in rings if bbox_hit(bb, win)]
            if rs:
                out.add("land", proj.nested(nest_rings(rs)), {"feature": fid, "name": f.get("name"), "type": f.get("type"),
                                                        "subtype": f.get("subtype"), "area": round(w.sq(f.get("area") or 0), 2),
                                                        "cells": f.get("cells")})
    # ---- zones, dissolved along cell edges
    if "zones" in want and w.zones:
        out.layer("zones", "MultiPolygon", [("name", "TEXT"), ("type", "TEXT"), ("cells", "INTEGER"), ("area", "REAL"),
                                            ("people", "REAL"), ("states", "TEXT")])
        zone_edges = defaultdict(list)
        for a, b2, p, q in w.edges:
            for zid in set(w.cell_zones.get(a, [])) ^ set(w.cell_zones.get(b2, [])):
                zone_edges[zid].append((p, q))
        for a, p, q in w.outer_edges:
            for zid in set(w.cell_zones.get(a, [])):
                zone_edges[zid].append((p, q))
        for z in w.zones:
            cells = sorted({c for c in z.get("cells", []) if 0 <= c < w.n})
            if not cells or not any(bbox_hit(w.cell_bbox[c], win) for c in cells):
                continue
            rings = [r for r in chain_segments(zone_edges.get(z["i"], [])) if len(r) >= 4 and math.dist(r[0], r[-1]) < 1e-3]
            polys = nest_rings(rings)
            covered = sum(poly_area(e) - sum(poly_area(h) for h in hs) for e, hs in polys)
            total = sum(w.cell_area[c] for c in cells)
            if not polys or abs(covered - total) > 0.02 * total:  # dissolve failed: fall back to the cells themselves
                polys = [(w.cell_poly[c], []) for c in cells]
            states = Counter(d["state"][c] for c in cells)
            out.add("zones", proj.nested(polys), {"name": z.get("name"), "type": z.get("type"), "cells": len(cells),
                                                        "area": round(w.sq(sum(w.cell_area[c] for c in cells)), 2),
                                                        "people": round(w.people(sum(d["pop"][c] for c in cells)), 1),
                                                        "states": "; ".join(w.state_name(s) for s, _ in states.most_common())})
    # ---- state borders with both sides' stances
    if "borders" in want:
        out.layer("borders", "MultiLineString", [("state_a", "TEXT"), ("state_b", "TEXT"), ("a_to_b", "TEXT"),
                                                 ("b_to_a", "TEXT"), ("length", "REAL"), ("wars", "TEXT")])
        pairs = defaultdict(list)
        for a, b2, p, q in w.edges:
            if not w.water[a] and not w.water[b2] and d["state"][a] != d["state"][b2]:
                bb = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
                if bbox_hit(bb, win):
                    pairs[tuple(sorted((d["state"][a], d["state"][b2])))].append((p, q))
        for (sa, sb), segs in pairs.items():
            A, B = w.state(sa) or {}, w.state(sb) or {}
            da, db = A.get("diplomacy") or [], B.get("diplomacy") or []
            camps = {c.get("name") + f" ({c.get('start')}-{c.get('end') if c.get('end') is not None else ''})"
                     for s in (A, B) for c in (s.get("campaigns") or [])
                     if isinstance(c, dict) and {c.get("attacker"), c.get("defender")} == {sa, sb}}
            out.add("borders", proj.multiline(chain_segments(segs)), {
                "state_a": w.state_name(sa), "state_b": w.state_name(sb),
                "a_to_b": da[sb] if sb < len(da) and isinstance(da[sb], str) else None,
                "b_to_a": db[sa] if sa < len(db) and isinstance(db[sa], str) else None,
                "length": round(w.miles(sum(math.dist(p, q) for p, q in segs)), 3), "wars": "; ".join(sorted(camps)) or None})
    # ---- rivers, routes, journeys
    if "rivers" in want:
        out.layer("rivers", "LineString", [("river", "INTEGER"), ("name", "TEXT"), ("type", "TEXT"), ("discharge", "REAL"),
                                           ("width", "REAL"), ("length", "REAL"), ("parent", "TEXT"), ("basin", "TEXT"),
                                           ("course", "TEXT")])
        names = {i: r.get("name") for i, r in w.rivers.items()}
        for rid, c in w.river_courses.items():
            if len(c["points"]) >= 2 and bbox_hit(bbox_of(c["points"]), win):
                r = w.rivers[rid]
                out.add("rivers", proj.line(c["points"]), {
                    "river": rid, "name": r.get("name"), "type": r.get("type"), "discharge": r.get("discharge"),
                    "width": round((r.get("width") or 0) * w.scale, 3), "length": round((r.get("length") or 0) * w.scale, 2),
                    "parent": names.get(r.get("parent")) if r.get("parent") not in (None, rid) else None,
                    "basin": names.get(r.get("basin")) if r.get("basin") not in (None, rid) else None, "course": c["source"]})
    if "routes" in want:
        out.layer("routes", "LineString", [("route", "INTEGER"), ("name", "TEXT"), ("group", "TEXT"), ("length", "REAL"),
                                           ("feature", "TEXT"), ("burgs", "TEXT")])
        for r in w.routes:
            pts = [(p[0], p[1]) for p in r["points"]]
            if len(pts) >= 2 and bbox_hit(bbox_of(pts), win):
                along = []
                for p in r["points"]:
                    cell = p[2] if len(p) > 2 else None
                    if cell is not None and 0 <= cell < w.n and d["burg"][cell] and w.burg(d["burg"][cell]):
                        nm = w.burg(d["burg"][cell])["name"]
                        if not along or along[-1] != nm:
                            along.append(nm)
                out.add("routes", proj.line(pts), {
                    "route": r.get("i"), "name": r.get("name") or f"unnamed {ROUTE_KIND.get(r.get('group'), 'route')} (route {r.get('i')})",
                    "group": r.get("group"), "length": round(w.miles(polyline_length(pts)), 2),
                    "feature": w.feature_label(r["feature"]) if r.get("feature") else None, "burgs": " - ".join(along) or None})
    if "journeys" in want or "stops" in want:
        out.layer("journeys", "LineString", [("journey", "TEXT"), ("type", "TEXT"), ("segment", "INTEGER"), ("name", "TEXT"),
                                             ("transport", "TEXT"), ("speed_kmh", "REAL"), ("speed", "REAL"),
                                             ("avoid_roads", "INTEGER"), ("hours_a_day", "REAL"), ("length", "REAL"),
                                             ("start_h", "REAL"), ("end_h", "REAL"), ("start", "TEXT"), ("end", "TEXT"),
                                             ("along_from", "REAL")])
        out.layer("stops", "Point", [("journey", "TEXT"), ("segment", "INTEGER"), ("name", "TEXT"), ("hours", "REAL"),
                                     ("start_h", "REAL"), ("start", "TEXT"), ("along", "REAL"), ("ref", "TEXT")])
        for plan in plans:
            miles = 0.0
            for s in plan.segments:
                if not s["visible"]:
                    continue
                if s["stay"]:
                    if s["xy"] and in_win(*s["xy"][0]) and "stops" in want:
                        x, y = s["xy"][0]
                        out.add("stops", proj.point(x, y), {"journey": plan.name, "segment": s["i"], "name": s["name"],
                                                            "hours": round(s["hours"], 2), "start_h": round(s["start"], 2),
                                                            "start": JourneyPlan.clock_text(s["start"]), "along": round(miles, 2),
                                                            "ref": g.ref(*g.locate(x, y))})
                elif len(s["xy"]) >= 2 and bbox_hit(bbox_of(s["xy"]), win) and "journeys" in want:
                    end = s["start"] + s["elapsed"]
                    out.add("journeys", proj.line(s["xy"]), {
                        "journey": plan.name, "type": plan.type, "segment": s["i"], "name": s["name"], "transport": s["transport"],
                        "speed_kmh": s["speed_kmh"], "speed": round(s["speed_units"], 3), "avoid_roads": s["avoid_roads"],
                        "hours_a_day": s["hpd"], "length": round(s["miles"], 2), "start_h": round(s["start"], 2),
                        "end_h": round(end, 2), "start": JourneyPlan.clock_text(s["start"]), "end": JourneyPlan.clock_text(end),
                        "along_from": round(miles, 2)})
                miles += s["miles"]
    # ---- points
    if "burgs" in want:
        out.layer("burgs", "Point", [("burg", "INTEGER"), ("name", "TEXT"), ("ref", "TEXT"), ("point_ref", "TEXT"),
                                     ("people", "REAL"), ("group", "TEXT"), ("type", "TEXT"), ("capital", "INTEGER"),
                                     ("port", "INTEGER"), ("citadel", "INTEGER"), ("walls", "INTEGER"), ("plaza", "INTEGER"),
                                     ("temple", "INTEGER"), ("shanty", "INTEGER"), ("state", "TEXT"), ("province", "TEXT"),
                                     ("culture", "TEXT"), ("religion", "TEXT"), ("market", "TEXT")])
        for b in w.live(w.burgs):
            if b.get("i") and in_win(b["x"], b["y"]):
                m = w.markets.get(b.get("market"))
                mc = w.burg(m.get("centerBurgId")) if m else None
                out.add("burgs", proj.point(b["x"], b["y"]), {
                    "burg": b["i"], "name": b["name"], "ref": g.ref(*g.locate(b["x"], b["y"])), "point_ref": g.point_ref(b["x"], b["y"]),
                    "people": round(w.burg_people(b), 1), "group": b.get("group"), "type": b.get("type"),
                    **{k: bool(b.get(k)) for k in ("capital", "port", "citadel", "walls", "plaza", "temple", "shanty")},
                    "state": w.state_name(b.get("state", 0)), "province": (w.province(d["province"][b["cell"]]) or {}).get("name"),
                    "culture": w.culture(b.get("culture", 0)).get("name"), "religion": w.religion(d["religion"][b["cell"]]).get("name"),
                    "market": f"{mc['name']} market" if mc else None})
    if "markers" in want:
        out.layer("markers", "Point", [("marker", "INTEGER"), ("name", "TEXT"), ("type", "TEXT"), ("icon", "TEXT"),
                                       ("ref", "TEXT"), ("point_ref", "TEXT"), ("note", "TEXT")])
        for m in w.markers:
            if in_win(m["x"], m["y"]):
                out.add("markers", proj.point(m["x"], m["y"]), {
                    "marker": m.get("i"), "name": m.get("name"), "type": m.get("type"), "icon": m.get("icon"),
                    "ref": g.ref(*g.locate(m["x"], m["y"])), "point_ref": g.point_ref(m["x"], m["y"]), "note": clean_note(m.get("note", "")) or None})
    if "units" in want:
        out.layer("units", "Point", [("name", "TEXT"), ("state", "TEXT"), ("men", "INTEGER"), ("naval", "INTEGER"),
                                     ("icon", "TEXT"), ("composition", "TEXT"), ("ref", "TEXT"), ("base_ref", "TEXT")])
        for u in w.units:
            if in_win(u["x"], u["y"]):
                comp = ", ".join(f"{v} {k}" for k, v in sorted((u.get("u") or {}).items(), key=lambda kv: -kv[1]))
                out.add("units", proj.point(u["x"], u["y"]), {
                    "name": u.get("name"), "state": w.state_name(u["state"]), "men": u.get("a"), "naval": bool(u.get("n")),
                    "icon": u.get("icon"), "composition": comp or None, "ref": g.ref(*g.locate(u["x"], u["y"])),
                    "base_ref": g.ref(*g.locate(u["bx"], u["by"])) if u.get("bx") is not None else None})
    return out.close()


# ====================================================================== command line
def world_and_grid(args):
    roots = args.worlds or [str(Path.cwd() / "Azgaar"), str(Path.cwd())]
    mp = resolve_world(args.world, roots, args.map)
    w = World(mp, args.cells)
    origin = None
    if args.origin:
        a, b = args.origin.split(",")
        origin = (float(a), float(b))
    g = TileGrid(w, args.grid, args.size, origin)
    return w, g


def cmd_info(args):
    w, g = world_and_grid(args)
    print(f"World      {w.name}" + (f", year {w.year} {w.era}" if w.year is not None else ""))
    print(f"Map        {w.map_path} (Azgaar {w.version}, {w.n} cells)")
    print(f"Cells      {w.cells_path.name}")
    others = sorted(p.name for p in w.folder.iterdir() if p.is_file() and p != w.map_path and p != w.cells_path)
    if others:
        print("Also here  " + ", ".join(others))
    print(f"Scale      {w.scale:g} {w.unit} per map pixel; map {w.W:g} x {w.H:g} px")
    print(f"Grid       {g.source}")
    print(f"           {g.describe()}")
    print(f"Squares    {', '.join(LETTERS[e] + '·' for e in range(g.blocks_e))} eastward; "
          f"{', '.join('·' + LETTERS[n] for n in range(g.blocks_n))} northward")
    print(f"Speeds     Azgaar stores transport speeds in km/h" + (" (read here as map units/h)" if args.speeds_as_map_units else ""))
    for n in w.notes + g.notes:
        print(f"Note       {n}")
    caps = [b for b in w.live(w.burgs) if b.get("i") and b.get("capital")][:6]
    if caps:
        print("Examples   " + "; ".join(f"{b['name']} {g.ref(*g.locate(b['x'], b['y']))}" for b in caps))


def cmd_find(args):
    w, g = world_and_grid(args)
    hits = find_places(w, g, " ".join(args.text))
    if not hits:
        print("No matches.")
        return
    for s, kind, label, (ref, pref, _) in hits[:args.limit]:
        print(f"{ref:<14} {pref:<16} {kind:<9} {label}")


def cmd_map(args):
    w, g = world_and_grid(args)
    out = args.out or f"{w.name} grid overview.svg"
    svg_overview(w, g, out)
    print(f"Wrote {out}  ({g.describe()})")


def cmd_sheet(args):
    w, g = world_and_grid(args)
    i, j, pt, label = resolve_place(w, g, " ".join(args.place))
    out = args.out or f"{w.name} sheet {g.ref(i, j, True)}.svg"
    svg_sheet(w, g, i, j, args.radius, out, mark=pt)
    print(f"Wrote {out}: {label} is in {g.ref(i, j)}" + (f" (point {g.point_ref(*pt)})" if pt else ""))


def cmd_report(args):
    w, g = world_and_grid(args)
    i, j, pt, label = resolve_place(w, g, " ".join(args.place))
    if not g.exists(i, j):
        raise MapError(f"{g.ref(i, j)} lies outside the map")
    tile = Tile(w, g, i, j, legacy_speeds=args.speeds_as_map_units, near_tiles=args.near)
    R = tile.analyse()
    out = Path(args.out or f"{w.name} {g.ref(i, j, True)}.tex")
    if args.json:
        jp = out.with_suffix(".json")
        jp.write_text(json.dumps(R, default=str, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Wrote {jp}")
    text = LatexReport(tile, title_page=args.title_page, paper="a4paper" if args.a4 else "letterpaper").render()
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}: {label} -> {g.ref(i, j)}")
    if args.pdf:
        exe = shutil.which("pdflatex")
        if not exe:
            print("pdflatex not found; the .tex file is ready to compile with the dndbook class.")
            return
        for _ in range(2):
            res = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", out.name], cwd=out.parent.resolve(),
                                 capture_output=True, text=True, encoding="latin-1")
        pdf = out.with_suffix(".pdf")
        if res.returncode == 0 and pdf.exists():
            print(f"Wrote {pdf}")
        else:
            tail = "\n".join(l for l in res.stdout.splitlines() if l.startswith("!") or "Error" in l)[:1500]
            print("pdflatex failed (is the dndbook class installed?):\n" + tail)


def cmd_export(args):
    w, g = world_and_grid(args)
    layers = [x.strip() for x in args.layers.split(",")] if args.layers else None
    if layers:
        bad = [x for x in layers if x not in LAYERS]
        if bad:
            raise MapError(f"unknown layer(s) {', '.join(bad)}; choose from {', '.join(LAYERS)}")
    if args.place:
        i, j, pt, label = resolve_place(w, g, " ".join(args.place))
        r = args.radius
        c0x, c0y = g.center(i, j)
        tiles = [(ii, jj) for ii in range(i - r - 1, i + r + 2) for jj in range(j - r - 1, j + r + 2)
                 if g.exists(ii, jj) and abs(g.center(ii, jj)[0] - c0x) <= r * g.step_x + 1e-6
                 and abs(g.center(ii, jj)[1] - c0y) <= r * g.step_y + 1e-6]
        window = bbox_of([p for t in tiles for p in g.poly(*t)])
        base = args.out or f"{w.name} sheet {g.ref(i, j, True)}"
        mode = args.tiles or "full"
        what = f"sheet round {g.ref(i, j)}" + (f" ({label})" if label != g.ref(i, j) else "") + f", {len(tiles)} tiles"
    else:
        tiles, window = None, None
        base = args.out or f"{w.name} map"
        mode = args.tiles or "none"
        what = f"whole map, {g.ncols * g.nrows:,} tile positions"
        if mode == "full":
            print(f"Note: full attributes for every tile of the map take a while ({g.ncols * g.nrows:,} tiles).")
    base = str(Path(base).with_suffix("")) if base.endswith((".gpkg", ".geojson")) else base
    surfaces = args.surfaces if args.surfaces is not None else bool(args.place)
    if surfaces and not args.place:
        print(f"Note: interpolating at all {g.ncols * g.nrows:,} tile centres takes a few minutes.")
    files = export_gis(w, g, base, fmt=args.format, crs=args.crs, window=window, tile_list=tiles, tiles=mode,
                       layers=layers, legacy_speeds=args.speeds_as_map_units, surfaces=surfaces)
    crs = "longitude/latitude as in Azgaar's own GeoJSON exports" if args.crs == "lonlat" else \
        f"{w.unit} east and north of the map's south-west corner"
    print(f"Exported the {what}; coordinates in {crs}.")
    for f in files:
        print(f"  {f}")
    if not args.place and mode == "none":
        print("  (no tiles layer: add --tiles light, or --tiles full for the report's figures per tile)")


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("world", help="a .map file, a folder holding one, or a world name")
    common.add_argument("--worlds", action="append", help="folder to look for worlds in (repeatable; default ./Azgaar and .)")
    common.add_argument("--map", help="use this .map (file name or path) instead of the newest")
    common.add_argument("--cells", help="use this Cells GeoJSON instead of the one matched by content")
    common.add_argument("--grid", default="map", help="map (Azgaar's overlay, default), square, hex (pointy-top), flathex or diamond")
    common.add_argument("--size", type=float, help="tile size in map distance units (hex: flat-to-flat; square: edge)")
    common.add_argument("--origin", help="X,Y in map pixels where a custom grid starts")
    common.add_argument("--speeds-as-map-units", action="store_true",
                        help="read journey speeds as map units per hour (Azgaar stores km/h)")
    p = argparse.ArgumentParser(prog="azgaar_tiles.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info", parents=[common], help="what was loaded and how references work")
    s.set_defaults(fn=cmd_info)
    s = sub.add_parser("find", parents=[common], help="grid references of places by name")
    s.add_argument("text", nargs="+")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(fn=cmd_find)
    s = sub.add_parser("map", parents=[common], help="overview reference map (SVG)")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_map)
    s = sub.add_parser("sheet", parents=[common], help="zoomed sheet with every tile numbered (SVG)")
    s.add_argument("place", nargs="+", help="grid reference, px:X,Y, ll:LON,LAT or a place name")
    s.add_argument("--radius", type=int, default=12, help="tiles each side of the centre (default 12)")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_sheet)
    s = sub.add_parser("export", parents=[common], help="GIS layers of the map or a sheet (GeoJSON or GeoPackage)")
    s.add_argument("place", nargs="*", help="centre of a sheet (as for 'sheet'); leave out for the whole map")
    s.add_argument("--radius", type=int, default=12, help="tiles each side of the centre (default 12)")
    s.add_argument("--format", choices=["geojson", "gpkg"], default="geojson",
                   help="geojson: one file per layer (default); gpkg: one GeoPackage with every layer")
    s.add_argument("--crs", choices=["lonlat", "units"], default="lonlat",
                   help="lonlat: Azgaar's longitude and latitude (default); units: map distance units east and north")
    s.add_argument("--tiles", choices=["none", "light", "full"],
                   help="tiles layer: none, light (cell under the centre) or full (clipped figures, as in the report); "
                        "default full for a sheet, none for the whole map")
    s.add_argument("--layers", help="comma-separated subset of: " + ", ".join(LAYERS))
    s.add_argument("--surfaces", action=argparse.BooleanOptionalAction, default=None,
                   help="interpolated values at every tile centre (layer 'centres', and i_ columns on 'tiles'); "
                        "default on for a sheet, off for the whole map")
    s.add_argument("-o", "--out", help="output name without extension")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("report", parents=[common], help="LaTeX data report for one tile")
    s.add_argument("place", nargs="+", help="grid reference, px:X,Y, ll:LON,LAT or a place name")
    s.add_argument("-o", "--out", help="output .tex path")
    s.add_argument("--json", action="store_true", help="also write the report data as JSON")
    s.add_argument("--pdf", action="store_true", help="run pdflatex on the result")
    s.add_argument("--title-page", action="store_true", help="add the dndbook title page and contents")
    s.add_argument("--a4", action="store_true", help="A4 paper instead of US letter")
    s.add_argument("--near", type=float, default=10, help="radius for 'nearby' lists, in tile widths (default 10)")
    s.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    try:
        args.fn(args)
    except MapError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
