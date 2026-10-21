#!/usr/bin/env python3
"""azgaar_iso.py: an isometric tile view of a world exported by azgaar_tiles.py, as one HTML file.

    python azgaar_iso.py EXPORT [-o FILE.html] [--title TEXT]

EXPORT is what `azgaar_tiles.py export` wrote: the base name of its GeoJSON layers ("Lania sheet CC4841",
for the files "Lania sheet CC4841 tiles.geojson", "... centres.geojson" and so on), one of those files,
the folder that holds them, or a GeoPackage written with --format gpkg.

The page draws every tile as a block raised to its interpolated height, in a rotatable isometric view.
Tiles can be painted with any value the export carries (height, temperature, people, each good, prices,
trade, state, culture, faith, biome, market...), clicked for everything known about them, and overlaid
with towns, markers, rivers, routes, borders, zones, journeys, regiments and the lettered grid. Trade
deals are drawn as moving goods from seller to buyer, routed along the route network, and can be
filtered by good, by kind of deal and by town or market.

Best input: a sheet export (tiles and centres are written by default), or a whole-map export with
--tiles light --surfaces. The centres layer carries the interpolated surfaces; the tiles layer adds
biome, province, culture and faith and gives the tile outline. Either layer works alone.

Python 3.9 or newer, standard library only. The page needs a browser with WebGL 2.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import heapq
import json
import math
import re
import sqlite3
import struct
import sys
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

TOOL_VERSION = "1.0"
LAYERS = ["tiles", "centres", "blocks", "squares", "land", "zones", "borders", "rivers", "routes", "journeys", "stops",
          "burgs", "markers", "units", "markets", "deals", "traffic"]
LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
UNIT_ABBR = {"kilometre": "km", "mile": "mi", "league": "lg", "verst": "vr", "nautical mile": "nmi", "nautical league": "nlg"}
KM_PER_UNIT = {"km": 1.0, "mi": 1.609344, "lg": 4.828032, "vr": 1.0668, "nmi": 1.852, "nlg": 5.556}
ROUTE_COST = {"roads": 1.0, "trails": 1.3, "searoutes": 0.5}   # as azgaar_tiles' SURFACE_RULES["route_cost"]
OFF_ROUTE_COST = 2.0                                            # as SURFACE_RULES["off_route_cost"]
NAN = float("nan")
U16_NULL = 65535


def log(*a):
    print(*a, file=sys.stderr)


# ====================================================================== reading the export
class ExportError(Exception):
    pass


_LAYER_RE = re.compile(r"^(.*) (" + "|".join(LAYERS) + r")\.geojson$", re.I)


def _wkb(buf, off=0):
    """Well-known binary -> (GeoJSON-like geometry, next offset)."""
    le = buf[off] == 1
    e = "<" if le else ">"
    t = struct.unpack_from(e + "I", buf, off + 1)[0] % 1000
    off += 5

    def pts(o):
        n = struct.unpack_from(e + "I", buf, o)[0]
        o += 4
        flat = struct.unpack_from(e + "%dd" % (2 * n), buf, o)
        return [[flat[2 * k], flat[2 * k + 1]] for k in range(n)], o + 16 * n

    if t == 1:
        x, y = struct.unpack_from(e + "dd", buf, off)
        return {"type": "Point", "coordinates": [x, y]}, off + 16
    if t == 2:
        c, off = pts(off)
        return {"type": "LineString", "coordinates": c}, off
    if t == 3:
        n = struct.unpack_from(e + "I", buf, off)[0]
        off += 4
        rings = []
        for _ in range(n):
            r, off = pts(off)
            rings.append(r)
        return {"type": "Polygon", "coordinates": rings}, off
    if t in (4, 5, 6):
        n = struct.unpack_from(e + "I", buf, off)[0]
        off += 4
        parts = []
        for _ in range(n):
            g, off = _wkb(buf, off)
            parts.append(g["coordinates"])
        return {"type": {4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}[t], "coordinates": parts}, off
    raise ExportError(f"unsupported WKB geometry type {t}")


def _gpkg_geom(blob):
    if blob is None:
        return None
    b = bytes(blob)
    if b[:2] != b"GP":
        return _wkb(b)[0]
    env = (b[3] >> 1) & 7
    head = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    return _wkb(b, head)[0]


def _geojson_features(path, stream_over=48 << 20, chunk=1 << 22):
    """Features of a GeoJSON file. Large files are read feature by feature, so a whole-map tiles
    layer (hundreds of MB) never sits in memory as one document."""
    if path.stat().st_size <= stream_over:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        for f in doc.get("features") or []:
            yield f.get("geometry"), f.get("properties") or {}
        return
    dec = json.JSONDecoder()
    with open(path, encoding="utf-8") as fh:
        buf, eof = "", False
        while '"features"' not in buf and not eof:
            more = fh.read(chunk)
            eof = not more
            buf += more
        start = buf.find('"features"')
        if start < 0:
            return
        pos = buf.index("[", start) + 1
        while True:
            while True:
                while pos < len(buf) and buf[pos] in " \t\r\n,":
                    pos += 1
                if pos < len(buf) or eof:
                    break
                more = fh.read(chunk)
                eof = not more
                buf, pos = buf[pos:] + more, 0
            if pos >= len(buf) or buf[pos] == "]":
                return
            try:
                obj, end = dec.raw_decode(buf, pos)
            except json.JSONDecodeError:
                if eof:
                    raise
                more = fh.read(chunk)
                eof = not more
                buf, pos = buf[pos:] + more, 0
                continue
            yield obj.get("geometry"), obj.get("properties") or {}
            pos = end
            if pos > chunk:
                buf, pos = buf[pos:], 0


def _crs_note(path):
    """azgaar_tiles writes crs_note after the features when coordinates are map units."""
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(max(0, size - 8192))
        tail = fh.read().decode("utf-8", "ignore")
    m = re.search(r'"crs_note"\s*:\s*("(?:[^"\\]|\\.)*")', tail)
    return json.loads(m.group(1)) if m else None


class Export:
    """The layers written by one `azgaar_tiles.py export` run."""

    def __init__(self, arg):
        p = Path(arg)
        self.files, self.gpkg, self.con = {}, None, None
        if p.is_file() and p.suffix.lower() == ".gpkg":
            self._open_gpkg(p)
        elif p.is_file() and p.suffix.lower() == ".geojson":
            m = _LAYER_RE.match(p.name)
            if not m:
                raise ExportError(f"{p.name} is not named like an azgaar_tiles layer ('<name> <layer>.geojson')")
            self._collect(p.parent, m.group(1))
        elif p.is_dir():
            bases = defaultdict(list)
            for f in p.glob("*.geojson"):
                m = _LAYER_RE.match(f.name)
                if m:
                    bases[m.group(1)].append(f)
            gpkgs = sorted(p.glob("*.gpkg"), key=lambda f: f.stat().st_mtime)
            if bases:
                base = max(bases, key=lambda b: max(f.stat().st_mtime for f in bases[b]))
                if len(bases) > 1:
                    log(f"Several exports in {p}: using '{base}' (newest). Others: " + ", ".join(sorted(b for b in bases if b != base)))
                self._collect(p, base)
            elif gpkgs:
                self._open_gpkg(gpkgs[-1])
            else:
                raise ExportError(f"no azgaar_tiles export (layer GeoJSON files or a .gpkg) in {p}")
        else:
            parent = p.parent if str(p.parent) else Path(".")
            self._collect(parent, p.name)
        if not self.layers():
            raise ExportError(f"no layers found for '{arg}'")

    def _collect(self, folder, base):
        self.base = base
        self.name = base
        for layer in LAYERS:
            f = folder / f"{base} {layer}.geojson"
            if f.exists():
                self.files[layer] = f

    def _open_gpkg(self, p):
        self.gpkg = p
        self.base = self.name = p.stem
        self.con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        self.tables = {r[0] for r in self.con.execute("SELECT table_name FROM gpkg_contents")}

    def layers(self):
        return [l for l in LAYERS if (l in self.files if not self.con else l in self.tables)]

    def has(self, layer):
        return layer in self.layers()

    def features(self, layer):
        if not self.has(layer):
            return iter(())
        if not self.con:
            return _geojson_features(self.files[layer])
        return self._gpkg_rows(layer)

    def _gpkg_rows(self, layer):
        gcol = self.con.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (layer,)).fetchone()
        gcol = gcol[0] if gcol else "geom"
        cur = self.con.execute(f'SELECT * FROM "{layer}"')
        cols = [c[0] for c in cur.description]
        gi = cols.index(gcol)
        for row in cur:
            props = {c: v for k, (c, v) in enumerate(zip(cols, row)) if k != gi and c != "fid"}
            yield _gpkg_geom(row[gi]), props

    def all(self, layer):
        return list(self.features(layer))

    def crs(self):
        """('lonlat', None) or ('units', unit abbreviation)."""
        if self.con:
            r = self.con.execute("SELECT s.srs_id, s.definition FROM gpkg_geometry_columns g JOIN gpkg_spatial_ref_sys s "
                                 "ON g.srs_id = s.srs_id LIMIT 1").fetchone()
            if not r or r[0] == 4326:
                return "lonlat", None
            return "units", _unit_from_wkt(r[1])
        smallest = min(self.files.values(), key=lambda f: f.stat().st_size)
        note = _crs_note(smallest)
        return ("units", _unit_from_wkt(note)) if note else ("lonlat", None)


def _unit_from_wkt(wkt):
    m = re.search(r'UNIT\["([^"]+)"', wkt or "")
    return UNIT_ABBR.get(m.group(1), m.group(1)) if m else None


# ====================================================================== geometry helpers
def _ring_area(r):
    a = 0.0
    for k in range(len(r)):
        x1, y1 = r[k]
        x2, y2 = r[(k + 1) % len(r)]
        a += x1 * y2 - x2 * y1
    return a / 2


def _plen(pts):
    return sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))


def simplify(pts, tol):
    """Douglas-Peucker, iterative."""
    if len(pts) < 3 or tol <= 0:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    t2 = tol * tol
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for k in range(a + 1, b):
            px, py = pts[k]
            if L2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best:
                best, bi = d2, k
        if best > t2:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def lattice_cell(vectors):
    """Voronoi cell of a lattice given the vectors to a tile's neighbours: the tile shape when the
    export has no tiles layer to read it from."""
    r = max(math.hypot(*v) for v in vectors) * 2
    poly = [(-r, -r), (r, -r), (r, r), (-r, r)]
    for vx, vy in vectors:
        c = (vx * vx + vy * vy) / 2      # keep points p with p.v <= |v|^2 / 2
        out = []
        for k in range(len(poly)):
            p, q = poly[k], poly[(k + 1) % len(poly)]
            fp, fq = p[0] * vx + p[1] * vy - c, q[0] * vx + q[1] * vy - c
            if fp <= 0:
                out.append(p)
            if (fp < 0 < fq) or (fq < 0 < fp):
                t = fp / (fp - fq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        poly = out
    clean = []
    for p in poly:
        if not clean or math.dist(p, clean[-1]) > 1e-9 * r:
            clean.append(p)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) <= 1e-9 * r:
        clean.pop()
    return clean


# ====================================================================== the tiles table
class Column:
    __slots__ = ("name", "layer", "vals", "text", "codes", "words")

    def __init__(self, name, layer):
        self.name, self.layer = name, layer
        self.vals = array("d")
        self.text = False
        self.codes, self.words = {}, [None]

    def set(self, row, v):
        vals = self.vals
        if len(vals) <= row:
            vals.extend([0.0 if self.text else NAN] * (row + 1 - len(vals)))
        if v is None:
            vals[row] = 0.0 if self.text else NAN
            return
        if isinstance(v, str):
            if not self.text:
                self._to_text()
            vals[row] = float(self._code(v))
            return
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        if self.text:
            vals[row] = float(self._code(_fmt_num(v)))
        else:
            vals[row] = float(v)

    def _code(self, s):
        c = self.codes.get(s)
        if c is None:
            c = self.codes[s] = len(self.words)
            self.words.append(s)
        return c

    def _to_text(self):
        old = self.vals
        self.text = True
        self.vals = array("d", [0.0 if v != v else float(self._code(_fmt_num(v))) for v in old])

    def pad(self, n):
        if len(self.vals) < n:
            self.vals.extend([0.0 if self.text else NAN] * (n - len(self.vals)))


def _fmt_num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


class Tiles:
    def __init__(self):
        self.rows = {}
        self.x, self.y = array("d"), array("d")
        self.cols = {}
        self.shape = None

    def __len__(self):
        return len(self.x)

    def row(self, ref, x, y):
        r = self.rows.get(ref)
        if r is None:
            r = self.rows[ref] = len(self.x)
            self.x.append(x)
            self.y.append(y)
        return r

    def col(self, name, layer):
        c = self.cols.get(name)
        if c is None:
            c = self.cols[name] = Column(name, layer)
        return c


# ====================================================================== what each field means
# label, group, unit, scale (lin/log), ramp, paint?, source. Units: {h} height, {t} temperature, {d}
# distance, {a} area; the page fills them in.
I, A, C, T = "interpolated", "as read at the tile centre", "the cell under the tile centre", "clipped from the cells"
FIELD_INFO = {
    "elevation": ("Elevation", "Land", "{h}", "lin", "elevation", True, I),
    "elev_m": ("Elevation in metres", "Land", "m", "lin", "elevation", False, I),
    "h": ("Azgaar height (0 to 100)", "Land", "", "lin", "elevation", True, I),
    "temp": ("Temperature", "Land", "{t}", "lin", "thermal", True, I),
    "temp_c": ("Temperature in °C", "Land", "°C", "lin", "thermal", False, I),
    "prec_mm": ("Precipitation", "Land", "mm", "lin", "wet", True, I),
    "suitability": ("Habitability", "Land", "", "lin", "growth", True, I),
    "biome": ("Biome", "Land", "", "cat", "biome", True, C),
    "height": ("Cell height", "Land", "{h}", "lin", "elevation", False, C),
    "density": ("People per {a}", "People", "", "log", "people", True, I),
    "rural": ("Rural people", "People", "", "log", "people", True, I),
    "urban": ("Town people", "People", "", "log", "people", True, I),
    "people": ("People", "People", "", "log", "people", True, I),
    "state": ("State", "Realm", "", "cat", "cat", True, A),
    "province": ("Province", "Realm", "", "cat", "cat", True, C),
    "culture": ("Culture", "Realm", "", "cat", "cat", True, C),
    "religion": ("Faith", "Realm", "", "cat", "cat", True, C),
    "zone": ("Zone at the centre", "Realm", "", "cat", "cat", True, "zone outlines at the tile centre"),
    "sales_tax": ("Sales tax", "Realm", "%", "lin", "tax", True, A),
    "poll_tax": ("Poll tax", "Realm", "%", "lin", "tax", True, A),
    "treasury": ("State treasury", "Realm", "coin", "lin", "tax", True, A),
    "alert": ("State alert", "Realm", "", "lin", "tax", True, A),
    "output_value": ("Output value", "Economy", "coin", "log", "value", True, I),
    "rural_value": ("Rural output value", "Economy", "coin", "log", "value", True, I),
    "urban_value": ("Town output value", "Economy", "coin", "log", "value", True, I),
    "top_good": ("Top good", "Economy", "", "cat", "cat", True, I),
    "market": ("Market", "Economy", "", "cat", "cat", True, A),
    "market_dist": ("Distance to the market centre", "Economy", "{d}", "lin", "growth", True, A),
    "price_index": ("Price index", "Economy", "", "lin", "index", True, I),
    "food_index": ("Food price index", "Economy", "", "lin", "index", True, I),
    "trade_value": ("Trade passing through", "Trade", "coin", "log", "trade", True, I),
    "trade_deals": ("Deals passing through", "Trade", "", "log", "trade", True, I),
    "trade_top": ("Main good passing through", "Trade", "", "cat", "cat", True, I),
    "land": ("Land", "Land", "", "lin", "growth", False, A),
    "cell": ("Azgaar cell", "Reference", "", "lin", "growth", False, A),
    "block10": ("10 by 10 block", "Reference", "", "cat", "cat", False, A),
    "square": ("Lettered square", "Reference", "", "cat", "cat", True, A),
}
FULL_INFO = {   # the tiles layer's clipped figures (--tiles full)
    "land_share": ("Land share", "Land", "%", "lin", "growth", True),
    "drawn_land": ("Drawn land share", "Land", "%", "lin", "growth", False),
    "state_share": ("Main state's share", "Realm", "%", "lin", "growth", False),
    "states": ("States in the tile", "Realm", "", "cat", "cat", False),
    "culture_share": ("Main culture's share", "Realm", "%", "lin", "growth", False),
    "biome_share": ("Main biome's share", "Land", "%", "lin", "growth", False),
    "zones": ("Zones in the tile", "Realm", "", "cat", "cat", True),
    "burgs": ("Burgs", "Places", "", "cat", "cat", False),
    "markers": ("Markers", "Places", "", "cat", "cat", False),
    "rivers": ("Rivers", "Places", "", "cat", "cat", False),
    "river_len": ("River length", "Places", "{d}", "lin", "wet", True),
    "routes": ("Routes", "Places", "", "cat", "cat", False),
    "route_len": ("Route length", "Places", "{d}", "lin", "trade", True),
    "journeys": ("Journeys", "Places", "", "cat", "cat", False),
    "border_len": ("State border length", "Realm", "{d}", "lin", "tax", True),
    "border_with": ("Borders with", "Realm", "", "cat", "cat", False),
    "cells": ("Cells overlapping", "Reference", "", "lin", "growth", False),
}
SKIP = {"ref", "east", "north", "east_all", "north_all", "lon", "lat"}


def field_info(key, layer, full_tiles):
    base = key[2:] if key.startswith("t:") else key
    if base.startswith("g_"):
        return (None, "Goods", "units", "log", "good", True, I)
    if layer == "tiles" and full_tiles and base in FULL_INFO:
        return FULL_INFO[base] + (T,)
    if base in FIELD_INFO:
        lab, grp, unit, scale, ramp, paint, src = FIELD_INFO[base]
        if key.startswith("t:"):
            src = T if full_tiles else C
            lab = lab + (" (clipped)" if full_tiles else " (cell)")
        return lab, grp, unit, scale, ramp, paint, src
    lab = base.replace("_", " ").capitalize()
    return lab, "Other", "", "lin", "growth", True, T if layer == "tiles" else I


# ====================================================================== building the page data
class Builder:
    def __init__(self, ex: Export, title=None, unit=None, scale=None, decimals=None):
        self.ex = ex
        self.title = title
        self.notes = []
        self.crs, crs_unit = ex.crs()
        self.unit = unit or crs_unit or "mi"
        self.k = 1.0
        if self.crs == "lonlat":
            self.k = scale or self._estimate_scale()
        elif scale:
            self.k = scale
        self.tiles = Tiles()
        self._read_tiles()
        n = len(self.tiles)
        if not n:
            raise ExportError("the export has no tiles or centres layer: re-export with --tiles light and --surfaces")
        xs, ys = self.tiles.x, self.tiles.y
        self.x0 = (min(xs) + max(xs)) / 2
        self.y0 = (min(ys) + max(ys)) / 2
        self._lattice()
        self.dec = decimals if decimals is not None else max(1, min(5, math.ceil(-math.log10(self.spacing / 400))))

    # ---- coordinates: the export's lon/lat (linear in map pixels) or map units, to map units
    def _estimate_scale(self):
        """Map units per degree, from layers that carry both a length and its line."""
        for layer, key in (("routes", "length"), ("borders", "length"), ("journeys", "length"), ("rivers", "length")):
            tot_len = tot_deg = 0.0
            for geom, p in self.ex.features(layer):
                L = p.get(key)
                if not L or not geom:
                    continue
                if geom["type"] == "LineString":
                    d = _plen(geom["coordinates"])
                elif geom["type"] == "MultiLineString":
                    d = sum(_plen(l) for l in geom["coordinates"])
                else:
                    continue
                if d > 0:
                    tot_len += L
                    tot_deg += d
            if tot_deg > 0 and tot_len > 0:
                k = tot_len / tot_deg
                self.notes.append(f"distances: {k:.3f} {self.unit} per degree, from the {layer} layer's lengths" + (" (approximate: Azgaar measures rivers its own way)" if layer == "rivers" else ""))
                return k
        self.notes.append("distances: no layer with lengths, so 1 unit = 1 degree (give --scale)")
        self.unit = "deg"
        return 1.0

    def P(self, c):
        return ((c[0] - self.x0) * self.k, (c[1] - self.y0) * self.k)

    def pts(self, coords, tol=0.0):
        out = [self.P(c) for c in coords]
        if tol:
            out = simplify(out, tol)
        return out

    def flat(self, pts):
        d = self.dec
        o = []
        for x, y in pts:
            o.append(round(x, d))
            o.append(round(y, d))
        return o

    # ---- tiles and centres, joined by grid reference
    def _read_tiles(self):
        T_ = self.tiles
        have_c, have_t = self.ex.has("centres"), self.ex.has("tiles")
        self.full_tiles = False
        shape_src = None
        CELL_FIELDS = ("province", "culture", "religion", "biome", "height", "block10")
        for layer in ("centres", "tiles"):
            if not self.ex.has(layer):
                continue
            log(f"  reading {layer}")
            first = True
            ibase = set()
            for geom, p in self.ex.features(layer):
                ref = p.get("ref")
                if ref is None or not geom:
                    continue
                if layer == "centres":
                    x, y = geom["coordinates"][:2]
                elif ref in T_.rows:
                    x = y = None
                else:
                    ring = geom["coordinates"][0][:-1] if geom["type"] == "Polygon" else geom["coordinates"][0][0][:-1]
                    x = sum(c[0] for c in ring) / len(ring)
                    y = sum(c[1] for c in ring) / len(ring)
                r = T_.row(ref, x, y)
                if layer == "tiles" and shape_src is None and geom["type"] == "Polygon":
                    shape_src = (r, geom["coordinates"][0])
                if first and layer == "tiles":
                    self.full_tiles = "land_share" in p
                    ibase = {k[2:] for k in p if k.startswith("i_")} if not have_c else set()
                    first = False
                for key, v in p.items():
                    if key in SKIP:
                        continue
                    if layer == "tiles":
                        if key.startswith("i_"):
                            if have_c:
                                continue
                            key = key[2:]
                        elif (have_c and key in FIELD_INFO and key not in CELL_FIELDS) or key in ibase:
                            key = "t:" + key
                    T_.col(key, layer).set(r, v)
        n = len(T_)
        for c in T_.cols.values():
            c.pad(n)
        # drop clipped/cell copies that only repeat what the centres say
        for key in [k for k in T_.cols if k.startswith("t:")]:
            base = T_.cols.get(key[2:])
            c = T_.cols[key]
            if base is not None and base.text == c.text and (
                    (c.text and [base.words[int(v)] for v in base.vals] == [c.words[int(v)] for v in c.vals])
                    or (not c.text and all((a == b) or (a != a and b != b) for a, b in zip(base.vals, c.vals)))):
                del T_.cols[key]
        if shape_src:
            r, ring = shape_src
            ring = ring[:-1] if ring[0] == ring[-1] else ring
            cx, cy = T_.x[r], T_.y[r]
            self.shape = [((x - cx) * self.k, (y - cy) * self.k) for x, y in ring]
            if _ring_area(self.shape) < 0:
                self.shape.reverse()
        else:
            self.shape = None

    def _lattice(self):
        """Tile spacing and, if the export has no outlines, the tile shape from the lattice."""
        T_ = self.tiles
        n = len(T_)
        xs = [(T_.x[i] - self.x0) * self.k for i in range(n)]
        ys = [(T_.y[i] - self.y0) * self.k for i in range(n)]
        self.px, self.py = xs, ys
        if self.shape:
            sh = self.shape
            # spacing: twice the distance from the centre to the nearest edge midpoint
            mids = [((sh[k][0] + sh[(k + 1) % len(sh)][0]) / 2, (sh[k][1] + sh[(k + 1) % len(sh)][1]) / 2) for k in range(len(sh))]
            self.spacing = 2 * min(math.hypot(*m) for m in mids)
            self.kind = {6: "hex", 4: "square"}.get(len(sh), "polygon")
            return
        if n < 2:
            raise ExportError("one tile and no tiles layer: the tile shape cannot be worked out")
        # nearest-neighbour vectors of a tile near the middle, via a coarse bucket search
        order = sorted(range(n), key=lambda i: xs[i] ** 2 + ys[i] ** 2)
        mid = order[0]
        near = sorted(((xs[i] - xs[mid], ys[i] - ys[mid]) for i in order[1:200]), key=lambda v: math.hypot(*v))
        d0 = math.hypot(*near[0])
        vecs = [v for v in near if math.hypot(*v) < d0 * 1.6]
        self.shape = lattice_cell(vecs)
        if _ring_area(self.shape) < 0:
            self.shape.reverse()
        self.spacing = d0
        self.kind = {6: "hex", 4: "square"}.get(len(self.shape), "polygon")
        self.notes.append(f"tile shape: worked out from the spacing of the centres ({len(self.shape)} sides)")

    # ---- fields: quantised to 16 bits (log for counts and values), dictionary codes for text
    def fields(self, blob):
        T_ = self.tiles
        n = len(T_)
        out = []
        goods_names = self._goods_names()
        for key, c in T_.cols.items():
            lab, grp, unit, scale, ramp, paint, src = field_info(key, c.layer, self.full_tiles)
            if key.startswith("g_"):
                lab = goods_names.get(key, key[2:].replace("_", " ").capitalize())
            if c.text:
                words = c.words
                counts = Counter(int(v) for v in c.vals)
                used = sorted((k for k in counts if k), key=lambda k: -counts[k])
                if not used:
                    continue
                remap = {old: new + 1 for new, old in enumerate(used)}
                codes = [remap.get(int(v), 0) for v in c.vals]
                big = len(used) >= U16_NULL
                arr = array("I" if big else "H", codes)
                off = blob.add(arr)
                out.append({"key": key, "label": lab, "group": grp, "src": src, "kind": "cat", "type": "u32" if big else "u16",
                            "off": off, "dict": [words[k] for k in used], "counts": [counts[k] for k in used],
                            "paint": bool(paint and 1 < len(used) < 4000), "ramp": ramp if ramp in ("biome",) else "cat"})
                continue
            vals = list(c.vals)
            if key in ("elevation", "elev_m", "h", "t:elevation") or key.endswith("elevation"):
                lim = -11000 if key in ("elev_m",) else (-11000 * self._hratio() if key.endswith("elevation") else -1e9)
                bad = sum(1 for v in vals if v == v and v < lim)
                if bad:
                    vals = [NAN if (v == v and v < lim) else v for v in vals]
                    note = (f"heights: {bad:,} sea tiles deeper than 11 km set aside as out of range and drawn as the deepest sea "
                            f"(azgaar_tiles' depth formula at an interpolated height near 0)")
                    if note not in self.notes:
                        self.notes.append(note)
            fin = [v for v in vals if v == v and not math.isinf(v)]
            if not fin:
                continue
            lo, hi = min(fin), max(fin)
            if unit == "%" and hi <= 1.0001:
                pass
            if scale == "log" and lo < 0:
                scale = "lin"
            q = array("H", [U16_NULL] * n)
            if hi == lo:
                for i, v in enumerate(vals):
                    if v == v and not math.isinf(v):
                        q[i] = 0
                eps = 0.0
            elif scale == "log":
                eps = hi * 1e-6 if hi > 0 else 1.0
                L = math.log1p(hi / eps)
                for i, v in enumerate(vals):
                    if v == v and not math.isinf(v):
                        q[i] = int(round(math.log1p(max(v, 0.0) / eps) / L * 65534))
            else:
                eps = 0.0
                span = hi - lo
                for i, v in enumerate(vals):
                    if v == v and not math.isinf(v):
                        q[i] = int(round((v - lo) / span * 65534))
            off = blob.add(q)
            srt = sorted(fin)
            pos = [v for v in srt if v > 0]
            r0 = srt[int(0.01 * (len(srt) - 1))] if scale == "lin" else (pos[int(0.02 * (len(pos) - 1))] if pos else lo)
            r1 = srt[int(0.99 * (len(srt) - 1))] if scale == "lin" else (pos[int(0.995 * (len(pos) - 1))] if pos else hi)
            if r1 <= r0:
                r0, r1 = lo, hi
            out.append({"key": key, "label": lab, "group": grp, "src": src, "kind": "num", "type": "u16", "off": off,
                        "scale": scale, "lo": lo, "hi": hi, "eps": eps, "r0": r0, "r1": r1, "unit": unit, "ramp": ramp,
                        "paint": bool(paint and hi > lo and key not in ("cell",)),
                        "int": all(float(v).is_integer() for v in fin[:2000])})
        return out

    def _hratio(self):
        """Display height units per metre, from the centres' elevation and elev_m."""
        e, m = self.tiles.cols.get("elevation"), self.tiles.cols.get("elev_m")
        if not e or not m or e.text or m.text:
            return 3.281
        for a, b in zip(e.vals, m.vals):
            if a == a and b == b and abs(b) > 50 and abs(b) < 5000:
                return a / b
        return 3.281

    def _goods_names(self):
        names = {}
        for _, p in self.ex.features("deals"):
            g = p.get("good")
            if g:
                names["g_" + re.sub(r"[^a-z0-9]+", "_", g.lower()).strip("_")] = g
        return names

    def units(self):
        """Height and temperature display units, from the pairs the centres carry."""
        hu, tu = "ft", "°C"
        r = self._hratio()
        hu = {1: "m", 3: "ft"}.get(round(r), "ft" if r > 2 else ("m" if r > 0.8 else "fathoms"))
        t, tc = self.tiles.cols.get("temp"), self.tiles.cols.get("temp_c")
        if t and tc and not t.text and not tc.text:
            for a, b in zip(t.vals, tc.vals):
                if a == a and b == b and abs(b) > 3:
                    if abs(a - (b * 9 / 5 + 32)) < 0.2:
                        tu = "°F"
                    elif abs(a - (b + 273.15)) < 0.2:
                        tu = "K"
                    elif abs(a - b) < 0.05:
                        tu = "°C"
                    else:
                        tu = "°"
                    break
        return hu, tu

    # ---- zones at tile centres, by scanline over the tile rows
    def zone_field(self, zones):
        if not zones:
            return
        T_ = self.tiles
        n = len(T_)
        rows = defaultdict(list)
        q = self.spacing / 1000
        for i in range(n):
            rows[round(self.py[i] / q)].append(i)
        row_keys = sorted(rows)
        row_x = {k: sorted(rows[k], key=lambda i: self.px[i]) for k in row_keys}
        row_xs = {k: [self.px[i] for i in row_x[k]] for k in row_keys}
        member = defaultdict(list)
        for zi, z in enumerate(zones):
            for poly in z["polys"]:
                edges = []
                for ring in poly:
                    for k in range(len(ring)):
                        a, b = ring[k], ring[(k + 1) % len(ring)]
                        if a[1] != b[1]:
                            edges.append((a, b))
                if not edges:
                    continue
                ylo = min(min(a[1], b[1]) for a, b in edges)
                yhi = max(max(a[1], b[1]) for a, b in edges)
                for rk in row_keys[bisect_left(row_keys, ylo / q - 1):bisect_right(row_keys, yhi / q + 1)]:
                    y = row_x[rk] and self.py[row_x[rk][0]]
                    xs_ = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                                 for a, b in edges if (a[1] <= y < b[1]) or (b[1] <= y < a[1]))
                    for s in range(0, len(xs_) - 1, 2):
                        lo_, hi_ = bisect_left(row_xs[rk], xs_[s]), bisect_right(row_xs[rk], xs_[s + 1])
                        for t in range(lo_, hi_):
                            member[row_x[rk][t]].append(zi)
        if not member:
            return
        c = T_.col("zone", "zones")
        for i in range(n):
            zs = member.get(i)
            c.set(i, "; ".join(zones[z]["name"] or zones[z]["type"] or f"zone {z}" for z in sorted(set(zs))) if zs else None)
        c.pad(n)


class Blob:
    """Typed arrays laid end to end, each on a 4-byte boundary."""

    def __init__(self):
        self.parts, self.size = [], 0

    def add(self, arr):
        b = arr.tobytes() if sys.byteorder == "little" else _swap(arr)
        off = self.size
        pad = (-len(b)) % 4
        self.parts.append(b + b"\0" * pad)
        self.size += len(b) + pad
        return off

    def bytes(self):
        return b"".join(self.parts)


def _swap(arr):
    a = array(arr.typecode, arr)
    a.byteswap()
    return a.tobytes()


# ====================================================================== trade routed over the routes
class Router:
    """Deals routed along the routes layer by least cost, as azgaar_tiles does: roads cost 1, trails 1.3,
    sea routes 0.5 per unit length, and reaching the network from a burg off it costs 2."""

    def __init__(self, routes, extent):
        self.pos, self.adj = [], defaultdict(dict)
        key_of = {}

        def node(p):
            k = (round(p[0], 4), round(p[1], 4))
            i = key_of.get(k)
            if i is None:
                i = key_of[k] = len(self.pos)
                self.pos.append(p)
            return i

        for r in routes:
            mult = ROUTE_COST.get(r["group"], 1.2)
            pts = r["pts"]
            for a in range(len(pts) - 1):
                u, v = node(pts[a]), node(pts[a + 1])
                if u == v:
                    continue
                c = math.dist(pts[a], pts[a + 1]) * mult
                if c < self.adj[u].get(v, float("inf")):
                    self.adj[u][v] = self.adj[v][u] = c
        self.cell = max(extent / 60, 1e-9)
        self.buckets = defaultdict(list)
        for i, p in enumerate(self.pos):
            if i in self.adj:
                self.buckets[(int(p[0] // self.cell), int(p[1] // self.cell))].append(i)
        self.extent = extent

    def attach(self, p):
        bx, by = int(p[0] // self.cell), int(p[1] // self.cell)
        for rad in (1, 3, 9, 27):
            best, bd = None, float("inf")
            for gx in range(bx - rad, bx + rad + 1):
                for gy in range(by - rad, by + rad + 1):
                    for i in self.buckets.get((gx, gy), ()):
                        d = math.dist(p, self.pos[i])
                        if d < bd:
                            best, bd = i, d
            if best is not None and bd <= rad * self.cell:
                return best
        return None

    def route(self, pairs):
        """pairs: list of (a, b) points -> list of paths (point lists) or None where unreachable."""
        att = {}
        for a, b in pairs:
            for p in (a, b):
                if p not in att:
                    att[p] = self.attach(p)
        by_src = defaultdict(list)
        for k, (a, b) in enumerate(pairs):
            by_src[att[a]].append(k)
        out = [None] * len(pairs)
        for src, ks in by_src.items():
            if src is None:
                continue
            targets = {att[pairs[k][1]] for k in ks} - {None}
            dist, prev, heap = {src: 0.0}, {}, [(0.0, src)]
            left = set(targets)
            while heap and left:
                d, u = heapq.heappop(heap)
                if d > dist.get(u, float("inf")):
                    continue
                left.discard(u)
                for v, c in self.adj[u].items():
                    nd = d + c
                    if nd < dist.get(v, float("inf")):
                        dist[v], prev[v] = nd, u
                        heapq.heappush(heap, (nd, v))
            for k in ks:
                a, b = pairs[k]
                t = att[b]
                if t is None or (t != src and t not in prev):
                    continue
                path = [t]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                path.reverse()
                pts = [a] + [self.pos[i] for i in path] + [b]
                clean = [pts[0]]
                for p in pts[1:]:
                    if math.dist(p, clean[-1]) > 1e-9:
                        clean.append(p)
                out[k] = clean
        return out


# ====================================================================== assembling the page
def build(ex: Export, title=None, unit=None, scale=None, compress=True, max_deals=None):
    B = Builder(ex, title=title, unit=unit, scale=scale)
    tol = B.spacing / 6
    log(f"  {len(B.tiles):,} tiles, {B.kind}, {B.spacing:.3g} {B.unit} apart")

    def feats(layer):
        return ex.features(layer)

    # zones first: their outlines also give a per-tile zone field
    zones = []
    for g, p in feats("zones"):
        if not g:
            continue
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        zones.append({"name": p.get("name"), "type": p.get("type"), "cells": p.get("cells"), "area": p.get("area"),
                      "people": p.get("people"), "states": p.get("states"),
                      "polys": [[B.pts(r[:-1] if r and r[0] == r[-1] else r) for r in poly] for poly in polys]})
    B.zone_field(zones)

    blob = Blob()
    pos = array("f")
    for i in range(len(B.tiles)):
        pos.append(B.px[i])
        pos.append(B.py[i])
    pos_off = blob.add(pos)
    fields = B.fields(blob)
    hu, tu = B.units()

    land = []
    for g, p in feats("land"):
        if not g:
            continue
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = []
        for poly in polys:
            for r in poly:
                s = B.pts(r, tol)
                if len(s) >= 4:
                    rings.append(B.flat(s))
        land.append({"name": p.get("name"), "type": p.get("type"), "subtype": p.get("subtype"), "rings": rings})

    def lines(g):
        if not g:
            return []
        if g["type"] == "LineString":
            return [g["coordinates"]]
        if g["type"] == "MultiLineString":
            return g["coordinates"]
        if g["type"] == "Polygon":
            return [g["coordinates"][0]]
        return []

    rivers = [{"id": p.get("river"), "name": p.get("name"), "type": p.get("type"), "discharge": p.get("discharge"),
               "width": p.get("width"), "length": p.get("length"), "parent": p.get("parent"),
               "pts": B.flat(B.pts(l, tol / 3))} for g, p in feats("rivers") for l in lines(g)]
    routes_raw = [{"id": p.get("route"), "name": p.get("name"), "group": p.get("group"), "length": p.get("length"),
                   "burgs": p.get("burgs"), "pts_full": B.pts(l)} for g, p in feats("routes") for l in lines(g)]
    routes = [{k: v for k, v in r.items() if k != "pts_full"} | {"pts": B.flat(r["pts_full"])} for r in routes_raw]
    borders = [{"a": p.get("state_a"), "b": p.get("state_b"), "ab": p.get("a_to_b"), "ba": p.get("b_to_a"),
                "length": p.get("length"), "wars": p.get("wars"), "lines": [B.flat(B.pts(l, tol / 2)) for l in lines(g)]}
               for g, p in feats("borders")]
    journeys = [{"journey": p.get("journey"), "type": p.get("type"), "seg": p.get("segment"), "name": p.get("name"),
                 "transport": p.get("transport"), "speed_kmh": p.get("speed_kmh"), "hpd": p.get("hours_a_day"),
                 "length": p.get("length"), "start": p.get("start"), "end": p.get("end"), "along": p.get("along_from"),
                 "avoid": p.get("avoid_roads"), "pts": B.flat(B.pts(l))} for g, p in feats("journeys") for l in lines(g)]
    stops = [{"journey": p.get("journey"), "seg": p.get("segment"), "name": p.get("name"), "hours": p.get("hours"),
              "start": p.get("start"), "along": p.get("along"), "ref": p.get("ref"), "xy": B.flat([B.P(g["coordinates"])])}
             for g, p in feats("stops") if g]
    squares = [{"name": p.get("square"), "pts": B.flat(B.pts(l))} for g, p in feats("squares") for l in lines(g)]
    blocks = [{"name": p.get("block"), "pts": B.flat(B.pts(l))} for g, p in feats("blocks") for l in lines(g)]
    traffic = [{"group": p.get("group"), "value": p.get("value"), "units": p.get("units"), "deals": p.get("deals"),
                "top": p.get("top_good"), "top_value": p.get("top_value"), "pts": B.flat(B.pts(l))}
               for g, p in feats("traffic") for l in lines(g)]

    burgs = []
    burg_at = {}
    for g, p in feats("burgs"):
        if not g:
            continue
        x, y = B.P(g["coordinates"])
        b = {"id": p.get("burg"), "name": p.get("name"), "ref": p.get("ref"), "pref": p.get("point_ref"),
             "people": p.get("people"), "group": p.get("group"), "type": p.get("type"),
             "flags": [k for k in ("capital", "port", "citadel", "walls", "plaza", "temple", "shanty") if p.get(k)],
             "state": p.get("state"), "province": p.get("province"), "culture": p.get("culture"),
             "religion": p.get("religion"), "market": p.get("market"), "xy": [round(x, B.dec), round(y, B.dec)]}
        burg_at[(p.get("name"), tuple(g["coordinates"][:2]))] = len(burgs)
        burgs.append(b)
    markets = []
    market_at = {}
    for g, p in feats("markets"):
        if not g:
            continue
        x, y = B.P(g["coordinates"])
        market_at[(f"{p.get('centre')} market", tuple(g["coordinates"][:2]))] = len(markets)
        markets.append({"id": p.get("market"), "centre": p.get("centre"), "ref": p.get("ref"), "burgs": p.get("burgs"),
                        "cells": p.get("cells"), "export": p.get("export_value"), "import": p.get("import_value"),
                        "pi": p.get("price_index"), "fi": p.get("food_index"), "xy": [round(x, B.dec), round(y, B.dec)]})
    markers = [{"id": p.get("marker"), "name": p.get("name"), "type": p.get("type"), "icon": p.get("icon"), "ref": p.get("ref"),
                "pref": p.get("point_ref"), "note": p.get("note"), "xy": B.flat([B.P(g["coordinates"])])}
               for g, p in feats("markers") if g]
    units_ = [{"name": p.get("name"), "state": p.get("state"), "men": p.get("men"), "naval": bool(p.get("naval")),
               "comp": p.get("composition"), "ref": p.get("ref"), "base": p.get("base_ref"), "xy": B.flat([B.P(g["coordinates"])])}
              for g, p in feats("units") if g]

    # ---- deals: places at both ends, routed paths
    deals_raw = [(g, p) for g, p in feats("deals") if g and g["type"] == "LineString" and len(g["coordinates"]) >= 2]
    if max_deals and len(deals_raw) > max_deals:
        deals_raw.sort(key=lambda gp: -(gp[1].get("value") or 0))
        B.notes.append(f"trade: the {max_deals:,} largest of {len(deals_raw):,} deals kept (--max-deals)")
        deals_raw = deals_raw[:max_deals]
    places, place_at = [], {}

    def place(kind, name, c):
        key = (kind, name, tuple(c[:2]))
        k = place_at.get(key)
        if k is None:
            x, y = B.P(c)
            pl = {"kind": kind, "name": name, "xy": [round(x, B.dec), round(y, B.dec)]}
            if kind == "burg":
                pl["burg"] = burg_at.get((name, tuple(c[:2])))
            else:
                pl["market"] = market_at.get((name, tuple(c[:2])))
            k = place_at[key] = len(places)
            places.append(pl)
        return k

    goods = Counter()
    for _, p in deals_raw:
        goods[p.get("good")] += p.get("value") or 0
    good_list = [g for g, _ in goods.most_common()]
    good_ix = {g: k for k, g in enumerate(good_list)}
    pair_ix, pairs = {}, []
    deals = []
    for g, p in deals_raw:
        a, b = g["coordinates"][0], g["coordinates"][-1]
        sp = place(p.get("seller_type") or "burg", p.get("seller"), a)
        bp = place(p.get("buyer_type") or "burg", p.get("buyer"), b)
        key = (sp, bp)
        if key not in pair_ix:
            pair_ix[key] = len(pairs)
            pairs.append((tuple(B.P(a)), tuple(B.P(b))))
        kind = {("market", "burg"): 0, ("burg", "market"): 1, ("market", "market"): 2}.get(
            (p.get("seller_type"), p.get("buyer_type")), 3)
        deals.append([p.get("deal"), good_ix.get(p.get("good"), 0), p.get("units"), p.get("price"), p.get("value"),
                      p.get("tax"), kind, sp, bp, pair_ix[key], p.get("routed_len")])
    paths, routed = [], 0
    if pairs:
        xs, ys = B.px, B.py
        extent = max(max(xs) - min(xs), max(ys) - min(ys)) + 4 * B.spacing
        rt = Router([{"group": r["group"], "pts": r["pts_full"]} for r in routes_raw], extent) if routes_raw else None
        found = rt.route(pairs) if rt else [None] * len(pairs)
        for (a, b), path in zip(pairs, found):
            if path:
                routed += 1
                paths.append({"r": 1, "pts": B.flat(path)})
            else:
                paths.append({"r": 0, "pts": B.flat([a, b])})
        B.notes.append(f"trade: {len(deals):,} deals between {len(pairs):,} pairs of places; {routed:,} pairs routed "
                       f"along the routes, {len(pairs) - routed:,} drawn straight")

    meta = {
        "tool": f"azgaar_iso {TOOL_VERSION}", "title": title or _world_title(ex.name), "source": ex.name,
        "crs": B.crs, "unit": B.unit, "hunit": hu, "tunit": tu, "km_per_unit": KM_PER_UNIT.get(B.unit),
        "tiles": {"n": len(B.tiles), "kind": B.kind, "spacing": B.spacing, "shape": [[round(x, 6), round(y, 6)] for x, y in B.shape],
                  "pos": pos_off, "full": B.full_tiles},
        "fields": fields, "notes": B.notes,
        "land": land, "rivers": rivers, "routes": routes, "borders": borders, "zones": [
            {k: v for k, v in z.items() if k != "polys"} | {"polys": [[B.flat(simplify(r, tol / 2)) for r in poly] for poly in z["polys"]]}
            for z in zones],
        "journeys": journeys, "stops": stops, "squares": squares, "blocks": blocks, "traffic": traffic,
        "burgs": burgs, "markets": markets, "markers": markers, "units": units_,
        "goods": good_list, "places": places, "deals": deals, "paths": paths,
    }
    refs = [None] * len(B.tiles)
    for ref, r in B.tiles.rows.items():
        refs[r] = ref
    meta["refs"] = "\n".join(r or "" for r in refs)
    raw_meta = json.dumps(_clean_json(meta), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    raw_blob = blob.bytes()
    return B, meta, raw_meta, raw_blob


def _world_title(base):
    w = re.split(r"\s+(?:sheet|map)\b", base, maxsplit=1)[0].strip()
    return w or base


def _clean_json(obj):
    """NaN and infinities have no JSON form: write them as null."""
    if isinstance(obj, float):
        return None if (obj != obj or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    return obj


def write_html(out_path, meta_bytes, blob_bytes, compress=True):
    enc = "gzip" if compress else "raw"
    pack = (lambda b: gzip.compress(b, 9, mtime=0)) if compress else (lambda b: b)
    m64 = base64.b64encode(pack(meta_bytes)).decode("ascii")
    b64 = base64.b64encode(pack(blob_bytes)).decode("ascii")
    payload = (f'<script type="application/octet-stream" id="iso-meta" data-enc="{enc}">{m64}</script>\n'
               f'<script type="application/octet-stream" id="iso-blob" data-enc="{enc}">{b64}</script>')
    html = PAGE.replace("<!--PAYLOAD-->", payload)
    Path(out_path).write_text(html, encoding="utf-8")
    return len(html.encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="azgaar_iso.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("export", help="an azgaar_tiles export: base name, one of its layer files, its folder, or a .gpkg")
    ap.add_argument("-o", "--out", help="output HTML file (default: '<export name> iso.html' beside the export)")
    ap.add_argument("--title", help="world name shown on the page (default: from the export's name)")
    ap.add_argument("--unit", help="distance unit of the map (default: from the export, else mi)")
    ap.add_argument("--scale", type=float, help="map units per degree for lon/lat exports (default: worked out from route lengths)")
    ap.add_argument("--max-deals", type=int, help="keep only the largest N deals by value")
    ap.add_argument("--no-compress", action="store_true", help="store the data uncompressed (larger file; for browsers "
                                                                     "without DecompressionStream)")
    args = ap.parse_args(argv)
    try:
        ex = Export(args.export)
        log(f"Export '{ex.name}': " + ", ".join(ex.layers()))
        B, meta, raw_meta, raw_blob = build(ex, title=args.title, unit=args.unit, scale=args.scale, max_deals=args.max_deals)
    except ExportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.out:
        out = Path(args.out)
    else:
        folder = ex.gpkg.parent if ex.gpkg else (next(iter(ex.files.values())).parent if ex.files else Path("."))
        out = folder / f"{ex.name} iso.html"
    size = write_html(out, raw_meta, raw_blob, compress=not args.no_compress)
    print(f"Wrote {out} ({size / 1e6:.1f} MB): {meta['tiles']['n']:,} tiles, "
          f"{sum(1 for f in meta['fields'] if f['paint'])} paint layers, {len(meta['burgs'])} burgs, {len(meta['deals']):,} deals")
    for n in B.notes:
        print(f"  {n}")
    return 0


# ====================================================================== the page
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Isometric world</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,500;0,700;1,500&family=Alegreya+Sans:ital,wght@0,400;0,500;0,700;1,400&family=Alegreya+Sans+SC:wght@500;700&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: light;
  --ground: #d9dfe5;
  --panel: rgba(246, 248, 250, 0.94);
  --panel-solid: #f6f8fa;
  --ink: #1b2430;
  --ink-2: #4b5768;
  --ink-3: #7a8494;
  --rule: rgba(27, 36, 48, 0.13);
  --well: rgba(27, 36, 48, 0.06);
  --grid: #1f6fb2;
  --accent: #c3006b;
  --accent-ink: #ffffff;
  --shadow: 0 8px 28px rgba(20, 30, 45, 0.16);
  --serif: "Alegreya", "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --sans: "Alegreya Sans", "Gill Sans", "Gill Sans MT", "Segoe UI", Candara, sans-serif;
  --caps: "Alegreya Sans SC", "Alegreya Sans", "Gill Sans", "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #0e131a;
    --panel: rgba(20, 26, 34, 0.93);
    --panel-solid: #141a22;
    --ink: #e4e9ef;
    --ink-2: #a5b1bf;
    --ink-3: #758190;
    --rule: rgba(228, 233, 239, 0.13);
    --well: rgba(228, 233, 239, 0.06);
    --grid: #63a8e6;
    --accent: #ff4fa5;
    --accent-ink: #1b0b14;
    --shadow: 0 8px 30px rgba(0, 0, 0, 0.45);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #0e131a;
  --panel: rgba(20, 26, 34, 0.93);
  --panel-solid: #141a22;
  --ink: #e4e9ef;
  --ink-2: #a5b1bf;
  --ink-3: #758190;
  --rule: rgba(228, 233, 239, 0.13);
  --well: rgba(228, 233, 239, 0.06);
  --grid: #63a8e6;
  --accent: #ff4fa5;
  --accent-ink: #1b0b14;
  --shadow: 0 8px 30px rgba(0, 0, 0, 0.45);
}
:root { box-sizing: border-box; padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
*, *::before, *::after { box-sizing: inherit; }
html, body { height: 100%; margin: 0; }
html { scroll-padding-top: env(safe-area-inset-top, 0px); }
body {
  background: var(--ground); color: var(--ink);
  font: 15px/1.4 var(--sans); overflow: hidden;
  -webkit-font-smoothing: antialiased; font-variant-numeric: tabular-nums;
}
canvas.layer { position: fixed; inset: 0; width: 100%; height: 100%; display: block; }
#gl { touch-action: none; }
#ov, #fx { pointer-events: none; }
button, input, select { font: inherit; color: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* ---- title and search */
.masthead {
  position: fixed; top: calc(14px + env(safe-area-inset-top, 0px)); left: 16px; right: 16px;
  display: flex; align-items: flex-start; gap: 16px; pointer-events: none;
}
.masthead > * { pointer-events: auto; }
.title { min-width: 0; text-shadow: 0 0 6px var(--ground), 0 0 2px var(--ground); }
.title h1 { font: 700 2rem/1 var(--serif); margin: 0; letter-spacing: 0.01em; }
.title p { margin: 4px 0 0; color: var(--ink-2); font-size: 0.93rem; }
.search { margin-left: auto; position: relative; width: min(330px, 46vw); }
.search input {
  width: 100%; padding: 9px 12px 9px 34px; border-radius: 8px; border: 1px solid var(--rule);
  background: var(--panel); box-shadow: var(--shadow); backdrop-filter: blur(10px);
}
.search svg { position: absolute; left: 11px; top: 11px; width: 15px; height: 15px; color: var(--ink-3); z-index: 1; pointer-events: none; }
.results {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0; list-style: none; margin: 0; padding: 4px;
  background: var(--panel-solid); border: 1px solid var(--rule); border-radius: 8px; box-shadow: var(--shadow);
  max-height: 50vh; overflow: auto;
}
.results li { padding: 6px 9px; border-radius: 5px; cursor: pointer; display: flex; gap: 10px; align-items: baseline; }
.results li[aria-selected="true"], .results li:hover { background: var(--well); }
.results small { color: var(--ink-3); margin-left: auto; white-space: nowrap; }

/* ---- control rail */
.rail {
  position: fixed; left: 16px; top: calc(92px + env(safe-area-inset-top, 0px)); width: 292px;
  max-height: calc(100% - 200px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px));
  overflow: auto; background: var(--panel); border: 1px solid var(--rule); border-radius: 12px;
  box-shadow: var(--shadow); backdrop-filter: blur(10px); padding: 4px 0;
  scrollbar-width: thin;
}
.rail details { border-bottom: 1px solid var(--rule); }
.rail details:last-child { border-bottom: 0; }
.rail summary {
  list-style: none; cursor: pointer; padding: 11px 16px; display: flex; align-items: baseline; gap: 8px;
  font: 700 1.04rem/1.2 var(--serif);
}
.rail summary::-webkit-details-marker { display: none; }
.rail summary::after { content: ""; margin-left: auto; width: 7px; height: 7px; border-right: 1.5px solid var(--ink-3);
  border-bottom: 1.5px solid var(--ink-3); transform: rotate(45deg); translate: 0 -3px; transition: transform .15s; }
.rail details[open] summary::after { transform: rotate(-135deg); translate: 0 1px; }
.rail summary .hint { font: 400 0.84rem var(--sans); color: var(--ink-3); }
.sec { padding: 0 16px 14px; }
.sec select, .sec input[type="search"] {
  width: 100%; padding: 7px 9px; border-radius: 6px; border: 1px solid var(--rule); background: var(--well);
}
.sec label.row { display: flex; align-items: center; gap: 9px; padding: 3px 0; cursor: pointer; }
.sec label.row input { accent-color: var(--accent); margin: 0; }
.sec .key { margin-left: auto; display: inline-flex; gap: 4px; align-items: center; }
.sec .slider { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; align-items: center; margin: 8px 0 2px; }
.sec .slider span { color: var(--ink-2); font-size: 0.9rem; }
.sec .slider output { font-size: 0.9rem; color: var(--ink); }
.sec .slider input { grid-column: 1 / -1; width: 100%; accent-color: var(--accent); }
.sub { font: 500 0.86rem var(--sans); color: var(--ink-3); margin: 12px 0 4px; }
.seg { display: flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; margin: 4px 0; }
.seg button { flex: 1; border: 0; background: transparent; padding: 6px 4px; font-size: 0.9rem; }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--panel-solid); }
.linkbtn { border: 0; background: none; padding: 0; color: var(--grid); text-decoration: underline; text-underline-offset: 2px; font-size: 0.9rem; }
.plainbtn { border: 1px solid var(--rule); background: var(--well); border-radius: 6px; padding: 6px 10px; }

/* legend */
.legend { margin-top: 10px; }
.ramp { height: 12px; border-radius: 3px; border: 1px solid var(--rule); }
.ramp-labels { display: flex; justify-content: space-between; font-size: 0.86rem; color: var(--ink-2); margin-top: 3px; }
.legend .about { font-size: 0.85rem; color: var(--ink-3); margin-top: 6px; }
.cats { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow: auto; }
.cats li { display: flex; align-items: center; gap: 8px; padding: 2px 4px; border-radius: 4px; cursor: pointer; font-size: 0.93rem; }
.cats li:hover { background: var(--well); }
.cats li.off { opacity: 0.38; }
.cats li small { margin-left: auto; color: var(--ink-3); }
.sw { width: 12px; height: 12px; border-radius: 2px; flex: none; box-shadow: inset 0 0 0 1px rgba(0,0,0,.18); }
.goods { list-style: none; margin: 6px 0 0; padding: 0; max-height: 240px; overflow: auto; }
.goods li { display: grid; grid-template-columns: auto 12px 1fr auto; gap: 7px; align-items: center; padding: 2px 2px; font-size: 0.93rem; }
.goods li input { accent-color: var(--accent); margin: 0; }
.goods .bar { grid-column: 3 / 5; height: 3px; border-radius: 2px; background: var(--rule); margin-top: -3px; }
.goods .bar i { display: block; height: 100%; border-radius: 2px; background: var(--ink-3); }
.goods small { color: var(--ink-3); }
.focus-chip { display: flex; align-items: center; gap: 8px; margin: 6px 0 2px; padding: 6px 8px; border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 14%, transparent); }
.focus-chip button { margin-left: auto; border: 0; background: none; font-size: 1.1rem; line-height: 1; padding: 0 2px; }

/* ---- inspector */
.inspector {
  position: fixed; right: 16px; top: calc(70px + env(safe-area-inset-top, 0px)); width: 352px;
  max-height: calc(100% - 210px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px));
  overflow: auto; background: var(--panel); border: 1px solid var(--rule); border-radius: 12px;
  box-shadow: var(--shadow); backdrop-filter: blur(10px); scrollbar-width: thin;
}
.inspector[hidden] { display: none; }
.insp-head { position: sticky; top: 0; background: var(--panel-solid); padding: 14px 16px 10px; border-bottom: 1px solid var(--rule); z-index: 1; }
.insp-head .ref { font: 700 1.55rem/1 var(--sans); color: var(--grid); letter-spacing: 0.02em; }
.insp-head h2 { font: 700 1.3rem/1.15 var(--serif); margin: 0; }
.insp-head p { margin: 5px 0 0; color: var(--ink-2); }
.insp-head .close { position: absolute; right: 10px; top: 10px; border: 0; background: none; width: 30px; height: 30px; border-radius: 6px; font-size: 1.3rem; color: var(--ink-2); }
.insp-head .close:hover { background: var(--well); }
.insp-body { padding: 4px 16px 16px; }
.insp-body h3 { font: 700 1rem/1.2 var(--serif); margin: 16px 0 6px; display: flex; align-items: baseline; gap: 8px; }
.insp-body h3 small { font: 400 0.84rem var(--sans); color: var(--ink-3); }
.card { border: 1px solid var(--rule); border-radius: 8px; padding: 10px 12px; margin: 8px 0; }
.card h4 { margin: 0; font: 700 1.08rem/1.2 var(--serif); display: flex; align-items: baseline; gap: 8px; }
.card h4 small { font: 400 0.86rem var(--sans); color: var(--ink-3); }
.card p { margin: 4px 0 0; color: var(--ink-2); }
.card .actions { margin-top: 8px; display: flex; gap: 12px; flex-wrap: wrap; }
dl.kv { display: grid; grid-template-columns: 1fr auto; gap: 3px 12px; margin: 0; }
dl.kv dt { color: var(--ink-2); }
dl.kv dd { margin: 0; text-align: right; }
dl.kv dd small { color: var(--ink-3); margin-left: 5px; font-size: 0.78rem; }
dl.kv .painted { color: var(--accent); }
.flows { list-style: none; margin: 4px 0 0; padding: 0; }
.flows li { display: grid; grid-template-columns: 12px 1fr auto; gap: 4px 8px; align-items: center; padding: 3px 0; }
.flows li .who { grid-column: 2 / 4; color: var(--ink-3); font-size: 0.86rem; margin-top: -3px; }
.flows .bar { grid-column: 2 / 4; height: 4px; border-radius: 2px; background: var(--well); }
.flows .bar i { display: block; height: 100%; border-radius: 2px; }
.note { color: var(--ink-2); font-style: italic; }

/* ---- readout, dial and zoom */
.readout {
  position: fixed; left: 16px; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); padding: 9px 14px;
  background: var(--panel); border: 1px solid var(--rule); border-radius: 10px; box-shadow: var(--shadow);
  backdrop-filter: blur(10px); min-width: 230px; max-width: min(520px, calc(100% - 200px));
}
.readout .ref { font: 700 1.25rem/1.1 var(--sans); color: var(--grid); letter-spacing: 0.02em; }
.readout .val { color: var(--ink-2); font-size: 0.92rem; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.compass {
  position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); display: flex; align-items: flex-end; gap: 10px;
}
.zoom { display: flex; flex-direction: column; gap: 6px; }
.zoom button {
  width: 38px; height: 38px; border-radius: 8px; border: 1px solid var(--rule); background: var(--panel);
  box-shadow: var(--shadow); font-size: 1.15rem; line-height: 1; backdrop-filter: blur(10px);
}
.dial { width: 132px; height: 132px; touch-action: none; cursor: grab; filter: drop-shadow(0 6px 14px rgba(15, 25, 40, .22)); }
.dial:active { cursor: grabbing; }
.dial .face { fill: var(--panel-solid); stroke: var(--rule); }
.dial .tick { stroke: var(--ink-3); }
.dial .tick.major { stroke: var(--ink); stroke-width: 1.6; }
.dial text { font: 700 11px var(--sans); fill: var(--ink-2); text-anchor: middle; dominant-baseline: central; }
.dial text.north { fill: var(--accent); font-size: 13px; }
.dial .heading { font: 700 17px var(--sans); fill: var(--ink); }
.dial .heading-sub { font: 400 9.5px var(--sans); fill: var(--ink-3); }
.dial .needle { fill: var(--accent); }

/* ---- loading */
.loading { position: fixed; inset: 0; display: grid; place-items: center; background: var(--ground); z-index: 10; }
.loading div { text-align: center; max-width: 420px; padding: 20px; }
.loading h1 { font: 700 1.6rem var(--serif); margin: 0 0 6px; }
.loading p { color: var(--ink-2); margin: 0; }
.loading.error p { color: var(--accent); }
.mobile-toggle { display: none; }

@media (max-width: 760px) {
  .title h1 { font-size: 1.5rem; }
  .title p { display: none; }
  .search { width: 52vw; }
  .mobile-toggle {
    display: block; position: fixed; left: 16px; top: calc(62px + env(safe-area-inset-top, 0px)); padding: 7px 12px; border-radius: 8px;
    border: 1px solid var(--rule); background: var(--panel); box-shadow: var(--shadow);
  }
  .rail { top: calc(104px + env(safe-area-inset-top, 0px)); width: calc(100% - 32px); max-height: 52vh; }
  .rail.collapsed { display: none; }
  .inspector { left: 8px; right: 8px; width: auto; top: auto; bottom: calc(8px + env(safe-area-inset-bottom, 0px)); max-height: 52vh; z-index: 3; }
  .readout { min-width: 0; max-width: calc(100% - 190px); padding: 7px 10px; }
  .readout .val { white-space: normal; }
  .dial { width: 104px; height: 104px; }
}
@media (prefers-reduced-motion: reduce) {
  .rail summary::after { transition: none; }
}
</style>
</head>
<body>
<canvas id="gl" class="layer" aria-label="Isometric map of the world's tiles"></canvas>
<canvas id="ov" class="layer" aria-hidden="true"></canvas>
<canvas id="fx" class="layer" aria-hidden="true"></canvas>

<header class="masthead">
  <div class="title"><h1 id="world-name">World</h1><p id="world-meta"></p></div>
  <div class="search" role="search">
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="7" cy="7" r="5"/><path d="M11 11l4 4"/></svg>
    <input id="q" type="search" placeholder="Find a town, marker, state or grid reference" autocomplete="off" aria-label="Find a place" aria-controls="results" aria-expanded="false">
    <ul id="results" class="results" role="listbox" hidden></ul>
  </div>
</header>

<button class="mobile-toggle" id="rail-toggle" aria-controls="rail" aria-expanded="false">Layers</button>
<aside class="rail collapsed" id="rail" aria-label="Map controls">
  <details open id="sec-paint">
    <summary>Paint the tiles</summary>
    <div class="sec">
      <select id="paint" aria-label="Value to paint the tiles with"></select>
      <div class="legend" id="legend"></div>
    </div>
  </details>
  <details open id="sec-show">
    <summary>Show on the map</summary>
    <div class="sec" id="toggles"></div>
  </details>
  <details id="sec-trade">
    <summary>Trade <span class="hint" id="trade-hint"></span></summary>
    <div class="sec" id="trade"></div>
  </details>
  <details id="sec-view">
    <summary>View</summary>
    <div class="sec" id="view"></div>
  </details>
</aside>

<aside class="inspector" id="inspector" hidden aria-live="polite" aria-label="Selected tile">
  <div class="insp-head" id="insp-head"></div>
  <div class="insp-body" id="insp-body"></div>
</aside>

<div class="readout" id="readout" aria-live="off">
  <div class="ref" id="ro-ref">&nbsp;</div>
  <div class="val" id="ro-val">Drag to move, scroll to zoom, right-drag to turn and tilt.</div>
</div>

<div class="compass">
  <div class="zoom">
    <button id="zoom-in" aria-label="Zoom in">+</button>
    <button id="zoom-out" aria-label="Zoom out">&minus;</button>
    <button id="zoom-fit" aria-label="Show the whole map" title="Show the whole map">
      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/></svg>
    </button>
  </div>
  <svg class="dial" id="dial" viewBox="-66 -66 132 132" role="slider" aria-label="View heading" aria-valuemin="0" aria-valuemax="359" tabindex="0"></svg>
</div>

<div class="loading" id="loading"><div><h1>Unpacking the world</h1><p id="loading-msg">Reading the tiles…</p></div></div>
<!--PAYLOAD-->
<script>
"use strict";
(async () => {
const $ = (s, el = document) => el.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
};
const loadMsg = (t) => { $("#loading-msg").textContent = t; };
const fail = (t) => { $("#loading").classList.add("error"); $("#loading h1").textContent = "The map could not be shown"; loadMsg(t); };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ====================================================================== unpacking
async function unpack(id) {
  const node = document.getElementById(id);
  const raw = atob(node.textContent.trim());
  const u8 = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) u8[i] = raw.charCodeAt(i);
  if (node.dataset.enc !== "gzip") return u8.buffer;
  if (!("DecompressionStream" in window)) throw new Error("This browser cannot unpack compressed data. Open the page in a current Chrome, Edge, Firefox or Safari, or rebuild it with --no-compress.");
  const stream = new Blob([u8]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}
let META, BLOB;
try {
  await new Promise((r) => setTimeout(r, 30));
  META = JSON.parse(new TextDecoder().decode(await unpack("iso-meta")));
  loadMsg(`Unpacking ${META.tiles.n.toLocaleString("en")} tiles…`);
  await new Promise((r) => setTimeout(r, 10));
  BLOB = await unpack("iso-blob");
} catch (e) { fail(e.message || String(e)); return; }

const N = META.tiles.n;
const SPACING = META.tiles.spacing;
const SHAPE = META.tiles.shape;
const POS = new Float32Array(BLOB, META.tiles.pos, N * 2);
const DU = META.unit, HU = META.hunit, TU = META.tunit;
const KMU = META.km_per_unit || (DU === "deg" ? 111.32 : 1.609344);
const FIELDS = META.fields;
const F = Object.fromEntries(FIELDS.map((f) => [f.key, f]));
document.title = `${META.title}: isometric tiles`;
$("#world-name").textContent = META.title;
const kindName = { hex: "hex", square: "square", polygon: "" }[META.tiles.kind] ?? "";
$("#world-meta").textContent = `${N.toLocaleString("en")} ${kindName} tiles, ${fmtNum(Math.round(SPACING * 10) / 10)} ${DU} across`;

function unitText(u) {
  return (u || "").replaceAll("{h}", HU).replaceAll("{t}", TU).replaceAll("{d}", DU).replaceAll("{a}", `sq ${DU}`);
}
for (const f of FIELDS) { f.label = unitText(f.label); f.unitText = unitText(f.unit); }

function values(f) {
  if (!f) return null;
  if (f._v) return f._v;
  if (f.kind === "cat") { f._v = f.type === "u32" ? new Uint32Array(BLOB, f.off, N) : new Uint16Array(BLOB, f.off, N); return f._v; }
  const q = new Uint16Array(BLOB, f.off, N), v = new Float32Array(N);
  if (f.hi === f.lo) for (let i = 0; i < N; i++) v[i] = q[i] === 65535 ? NaN : f.lo;
  else if (f.scale === "log") { const L = Math.log1p(f.hi / f.eps); for (let i = 0; i < N; i++) v[i] = q[i] === 65535 ? NaN : f.eps * Math.expm1((q[i] / 65534) * L); }
  else { const s = (f.hi - f.lo) / 65534; for (let i = 0; i < N; i++) v[i] = q[i] === 65535 ? NaN : f.lo + q[i] * s; }
  f._v = v;
  return v;
}
const catOf = (f, i) => { if (!f) return null; const c = values(f)[i]; return c ? f.dict[c - 1] : null; };
const numOf = (f, i) => (f ? values(f)[i] : NaN);
const REFS = (META.refs || "").split("\n");

// ====================================================================== numbers
function fmtNum(v, intish = false) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (intish && a >= 1) return Math.round(v).toLocaleString("en");
  if (a >= 1000) return Math.round(v).toLocaleString("en");
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1).replace(/\.0$/, "");
  if (a >= 1) return v.toFixed(2).replace(/\.?0+$/, "");
  if (a === 0) return "0";
  return v.toPrecision(2);
}
function fmtField(f, v) {
  if (f.kind === "cat") return v ?? "–";
  if (Number.isNaN(v)) return "–";
  if (f.unit === "%") return `${fmtNum(v * 100)}%`;
  if (f.key === "land" || f.key === "t:land") return v ? "yes" : "no";
  const u = f.unitText;
  const s = fmtNum(v, f.int);
  return u ? (u === "coin" ? `${s} coin` : `${s} ${u}`) : s;
}

// ====================================================================== colour
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const mixc = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
function rampFn(stops) {
  const S = stops.map(([t, c]) => [t, hex(c)]);
  return (t) => {
    if (t <= S[0][0]) return S[0][1];
    for (let k = 1; k < S.length; k++) if (t <= S[k][0]) { const [t0, c0] = S[k - 1], [t1, c1] = S[k]; return mixc(c0, c1, (t - t0) / (t1 - t0)); }
    return S[S.length - 1][1];
  };
}
const even = (cs) => cs.map((c, k) => [k / (cs.length - 1), c]);
const RAMPS = {
  wet: rampFn(even(["#efe9d6", "#cfe1bd", "#8fc6b3", "#4b9dbd", "#2d68a5", "#243c78"])),
  growth: rampFn(even(["#f1efe4", "#d3e3a5", "#94c67a", "#4f9a5a", "#23663f"])),
  people: rampFn(even(["#f5ede6", "#efc79c", "#e1925c", "#c1563a", "#8a2b3b", "#4a193c"])),
  value: rampFn(even(["#f3f0e6", "#e8d189", "#d2983b", "#a6602a", "#69321f"])),
  trade: rampFn(even(["#eceff5", "#b7c4e3", "#7893ce", "#4960ae", "#2a2e7b"])),
  good: rampFn(even(["#f1f2ec", "#cde0b6", "#8cbe88", "#4d8e71", "#235859"])),
  tax: rampFn(even(["#f0eff4", "#d2c3de", "#a686bf", "#754e98", "#442665"])),
  index: rampFn([[-1, "#2a63aa"], [-0.4, "#8db8de"], [0, "#f0efea"], [0.4, "#eeae84"], [1, "#b9452a"]]),
  thermal: rampFn([[-30, "#26397f"], [-15, "#4a78c0"], [-5, "#99c1e2"], [0, "#e6eef0"], [8, "#f2e1a2"], [16, "#efb267"], [24, "#dc7143"], [32, "#b12f29"], [42, "#69131f"]]),
  land: rampFn([[0, "#5e9a5b"], [150, "#9dbe6c"], [500, "#d6c681"], [1000, "#c59961"], [1800, "#987157"], [2800, "#8b8784"], [3800, "#f1f3f4"]]),
  sea: rampFn([[-4000, "#203b6e"], [-1000, "#36639f"], [-200, "#5b8cc0"], [0, "#8bb3d7"]]),
};
const RAMP_CSS = {
  wet: ["#efe9d6", "#cfe1bd", "#8fc6b3", "#4b9dbd", "#2d68a5", "#243c78"], growth: ["#f1efe4", "#d3e3a5", "#94c67a", "#4f9a5a", "#23663f"],
  people: ["#f5ede6", "#efc79c", "#e1925c", "#c1563a", "#8a2b3b", "#4a193c"], value: ["#f3f0e6", "#e8d189", "#d2983b", "#a6602a", "#69321f"],
  trade: ["#eceff5", "#b7c4e3", "#7893ce", "#4960ae", "#2a2e7b"], good: ["#f1f2ec", "#cde0b6", "#8cbe88", "#4d8e71", "#235859"],
  tax: ["#f0eff4", "#d2c3de", "#a686bf", "#754e98", "#442665"], index: ["#2a63aa", "#8db8de", "#f0efea", "#eeae84", "#b9452a"],
};
const PALETTE = ["#4e79a7", "#e8853a", "#d9534f", "#5fb0a9", "#5a9e4b", "#e3c33f", "#a874a0", "#f294a3", "#94705a", "#9d9690",
  "#3f8f8a", "#c8648d", "#89b5dd", "#f3b06f", "#7fc172", "#ad8f2a", "#7e5fa8", "#e8a7c8", "#6f6a66", "#c94f2b",
  "#2f5d87", "#b5c96a", "#d98f5a", "#6fa3b9"].map(hex);
const BIOME = { "Marine": "#466eab", "Hot desert": "#fbe79f", "Cold desert": "#b5b887", "Savanna": "#d2d082", "Grassland": "#c8d68f",
  "Tropical seasonal forest": "#b6d95d", "Temperate deciduous forest": "#29bc56", "Tropical rainforest": "#7dcb35",
  "Temperate rainforest": "#409c43", "Taiga": "#4b6b32", "Tundra": "#96784b", "Glacier": "#d5e7eb", "Wetland": "#0b9131" };
const WATER = hex("#7fa7cc"), LANDNULL = hex("#c9c6bd");
function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
function catColor(f, code) {
  if (!code) return null;
  const name = f.dict[code - 1];
  if (f.ramp === "biome" && BIOME[name]) return hex(BIOME[name]);
  return PALETTE[(code - 1) % PALETTE.length];
}
const css = (c) => `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;

// ====================================================================== heights and land
const fElevM = F["elev_m"], fElev = F["elevation"] || F["t:elevation"], fCellH = F["height"];
const hRatio = HU === "m" ? 1 : HU === "ft" ? 3.281 : 0.5468;
const ELEV = new Float32Array(N);
{
  const a = values(fElevM), b = values(fElev), c = values(fCellH);
  for (let i = 0; i < N; i++) {
    let v = a ? a[i] : NaN;
    if (Number.isNaN(v) && b) v = b[i] / hRatio;
    if (Number.isNaN(v) && c) v = c[i] / hRatio;
    ELEV[i] = v;
  }
}
{ // tiles whose height was set aside as out of range: the sea there is at its deepest
  let lo = 0; for (let i = 0; i < N; i++) if (ELEV[i] < lo) lo = ELEV[i];
  for (let i = 0; i < N; i++) if (Number.isNaN(ELEV[i])) ELEV[i] = 0;
  const fl = values(F["land"] || F["t:land"]);
  if (fl) for (let i = 0; i < N; i++) if (fl[i] < 0.5 && Number.isNaN(values(fElevM || fElev || fCellH)?.[i])) ELEV[i] = lo;
}
const LAND = new Uint8Array(N);
{
  const fl = F["land"] || F["t:land"];
  const lv = values(fl), bio = F["biome"];
  for (let i = 0; i < N; i++) {
    if (lv) LAND[i] = lv[i] > 0.5 ? 1 : 0;
    else if (bio) LAND[i] = catOf(bio, i) !== "Marine" ? 1 : 0;
    else LAND[i] = ELEV[i] > 0 ? 1 : 0;
  }
}
const landElev = []; for (let i = 0; i < N; i++) if (LAND[i]) landElev.push(ELEV[i]);
landElev.sort((x, y) => x - y);
const ELEV99 = landElev.length ? landElev[Math.floor(0.99 * (landElev.length - 1))] : 1000;
const ZM = 1 / 1000 / KMU;                       // metres -> map units
const EXAG0 = Math.min(400, Math.max(1, (1.6 * SPACING) / Math.max(ELEV99 * ZM, 1e-6)));

// lattice neighbours, for slope shading and for finding the tile under a point
let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
for (let i = 0; i < N; i++) { const x = POS[2 * i], y = POS[2 * i + 1]; if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; }
const RADIUS = Math.hypot(maxX - minX, maxY - minY) / 2 + SPACING;
const BK = SPACING, BX0 = minX - BK, BY0 = minY - BK;
const BW = Math.ceil((maxX - minX) / BK) + 3, BH = Math.ceil((maxY - minY) / BK) + 3;
const bucketStart = new Int32Array(BW * BH + 1), bucketItems = new Int32Array(N);
{
  const cell = new Int32Array(N);
  for (let i = 0; i < N; i++) { const bx = Math.floor((POS[2 * i] - BX0) / BK), by = Math.floor((POS[2 * i + 1] - BY0) / BK); cell[i] = by * BW + bx; bucketStart[cell[i] + 1]++; }
  for (let k = 0; k < BW * BH; k++) bucketStart[k + 1] += bucketStart[k];
  const fill = bucketStart.slice(0, BW * BH);
  for (let i = 0; i < N; i++) bucketItems[fill[cell[i]]++] = i;
}
function tileAt(x, y, maxD = SPACING * 0.75) {
  const bx = Math.floor((x - BX0) / BK), by = Math.floor((y - BY0) / BK);
  let best = -1, bd = maxD * maxD;
  for (let gy = by - 1; gy <= by + 1; gy++) {
    if (gy < 0 || gy >= BH) continue;
    for (let gx = bx - 1; gx <= bx + 1; gx++) {
      if (gx < 0 || gx >= BW) continue;
      const k = gy * BW + gx;
      for (let t = bucketStart[k]; t < bucketStart[k + 1]; t++) {
        const i = bucketItems[t], dx = POS[2 * i] - x, dy = POS[2 * i + 1] - y, d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = i; }
      }
    }
  }
  return best;
}
// slope of the land surface at each tile (least squares over the neighbours), in metres per map unit
const GX = new Float32Array(N), GY = new Float32Array(N);
{
  const r2 = (SPACING * 1.25) ** 2;
  for (let i = 0; i < N; i++) {
    if (!LAND[i]) continue;
    const x = POS[2 * i], y = POS[2 * i + 1];
    const bx = Math.floor((x - BX0) / BK), by = Math.floor((y - BY0) / BK);
    let sxx = 0, sxy = 0, syy = 0, sxz = 0, syz = 0;
    for (let gy = by - 1; gy <= by + 1; gy++) for (let gx = bx - 1; gx <= bx + 1; gx++) {
      if (gx < 0 || gy < 0 || gx >= BW || gy >= BH) continue;
      const k = gy * BW + gx;
      for (let t = bucketStart[k]; t < bucketStart[k + 1]; t++) {
        const j = bucketItems[t]; if (j === i) continue;
        const dx = POS[2 * j] - x, dy = POS[2 * j + 1] - y; if (dx * dx + dy * dy > r2) continue;
        const dz = (LAND[j] ? ELEV[j] : 0) - ELEV[i];
        sxx += dx * dx; sxy += dx * dy; syy += dy * dy; sxz += dx * dz; syz += dy * dz;
      }
    }
    const det = sxx * syy - sxy * sxy;
    if (det > 1e-12) { GX[i] = (syy * sxz - sxy * syz) / det; GY[i] = (sxx * syz - sxy * sxz) / det; }
  }
}

// ====================================================================== state
const S = {
  paint: F["biome"] ? "@landscape" : (F["elevation"] ? "elevation" : (FIELDS.find((f) => f.paint) || {}).key),
  exag: EXAG0, steps: 0, shade: true, outlines: true,
  cam: { x: 0, y: 0, zoom: 1, yaw: 0, pitch: 38 },
  show: { burgs: true, labels: true, markets: true, markers: true, units: false, rivers: true, routes: true, coast: true,
          borders: true, states: true, zones: false, journeys: true, squares: false, blocks: false },
  trade: { on: false, kinds: [true, true, true], straight: false, traffic: false, speed: 60, goods: null, focus: null, dim: 0.6 },
  isolate: null, sel: -1, selBurg: -1, hover: -1,
};
const TOP = new Float32Array(N);
let BASE = -0.6 * SPACING, ZMAX = 0;
function computeTops() {
  const e = S.exag, st = S.steps, lift = SPACING * 0.035;
  ZMAX = 0;
  for (let i = 0; i < N; i++) {
    let h = ELEV[i];
    if (LAND[i]) {
      if (st > 0) h = Math.max(st, Math.ceil(h / st) * st);
      TOP[i] = Math.max(h * ZM * e, 0) + lift;
    } else TOP[i] = h > 0 ? h * ZM * e : 0;
    if (TOP[i] > ZMAX) ZMAX = TOP[i];
  }
  BASE = -0.6 * SPACING - Math.min(SPACING * 2, ZMAX * 0.05);
}
computeTops();

// ====================================================================== WebGL terrain
const glc = $("#gl");
const gl = glc.getContext("webgl2", { antialias: true, alpha: false, depth: true, preserveDrawingBuffer: false, powerPreference: "high-performance" });
if (!gl) { fail("This page draws the tiles with WebGL 2, which this browser or device has switched off."); return; }
const VS = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
layout(location=0) in vec2 aOff; layout(location=1) in vec3 aInfo; layout(location=2) in vec2 aPos;
uniform sampler2D uTop, uCol, uMask; uniform int uTW;
uniform vec2 uTarget, uRot, uPitch, uView; uniform float uZoom, uDepth, uBase, uShadeTop, uDim; uniform vec3 uLight, uDimTo;
out vec3 vCol; out float vEdge; flat out int vId; flat out float vTop; flat out float vWater;
void main(){
  int id = gl_InstanceID; ivec2 tc = ivec2(id % uTW, id / uTW);
  float top = texelFetch(uTop, tc, 0).r; vec4 c = texelFetch(uCol, tc, 0); vec2 mk = texelFetch(uMask, tc, 0).rg; float m = mk.r;
  float kind = aInfo.x; float z = kind < 2.5 ? top : uBase;
  vec2 p = aPos + aOff - uTarget;
  float xr = uRot.x * p.x - uRot.y * p.y, yr = uRot.y * p.x + uRot.x * p.y;
  gl_Position = vec4(xr * uZoom / (uView.x * 0.5), (yr * uPitch.x + z * uPitch.y) * uZoom / (uView.y * 0.5), (yr * uPitch.y - z * uPitch.x) / uDepth, 1.0);
  vec3 col = c.rgb;
  if (kind < 1.5) { col *= mix(1.0, c.a * 2.0, uShadeTop); vTop = 1.0; }
  else { float diff = max(dot(vec3(aInfo.yz, 0.0), uLight), 0.0); col *= 0.5 + 0.44 * diff; if (kind > 2.5) col *= 0.62; vTop = 0.0; }
  float g = dot(col, vec3(0.299, 0.587, 0.114));
  float d = max(uDim, (1.0 - m) * 0.82);
  vCol = mix(col, mix(vec3(g), uDimTo, 0.78), d);
  vEdge = kind < 0.5 ? 1.0 : 0.0; vId = id; vWater = mk.g;
}`;
const FS = `#version 300 es
precision highp float; precision highp int;
in vec3 vCol; in float vEdge; flat in int vId; flat in float vTop; flat in float vWater;
uniform int uPick; uniform float uOutline; out vec4 o;
void main(){
  if (uPick == 1) { int k = vId + 1; o = vec4(float(k & 255) / 255.0, float((k >> 8) & 255) / 255.0, float((k >> 16) & 255) / 255.0, 1.0); return; }
  vec3 c = vCol;
  if (vTop > 0.5 && uOutline > 0.0) { float w = fwidth(vEdge); float e = 1.0 - smoothstep(0.0, w * 1.15, vEdge); c = mix(c, c * 0.66, e * uOutline * (1.0 - 0.7 * vWater)); }
  o = vec4(c, 1.0);
}`;
function shader(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}
const prog = gl.createProgram();
try {
  gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
} catch (e) { fail("The tile shader did not compile: " + e.message); return; }
const U = {};
for (const n of ["uTop", "uCol", "uMask", "uTW", "uTarget", "uRot", "uPitch", "uView", "uZoom", "uDepth", "uBase", "uShadeTop", "uDim", "uLight", "uDimTo", "uPick", "uOutline"]) U[n] = gl.getUniformLocation(prog, n);

// template prism: top fan (centre + ring) and one wall quad per edge
const NV = SHAPE.length, tv = [], ti = [];
tv.push(0, 0, 0, 0, 0);
for (let k = 0; k < NV; k++) tv.push(SHAPE[k][0], SHAPE[k][1], 1, 0, 0);
for (let k = 0; k < NV; k++) ti.push(0, 1 + k, 1 + ((k + 1) % NV));
for (let k = 0; k < NV; k++) {
  const a = SHAPE[k], b = SHAPE[(k + 1) % NV], ex = b[0] - a[0], ey = b[1] - a[1], L = Math.hypot(ex, ey), nx = ey / L, ny = -ex / L;
  const base = tv.length / 5;
  tv.push(a[0], a[1], 2, nx, ny, b[0], b[1], 2, nx, ny, a[0], a[1], 3, nx, ny, b[0], b[1], 3, nx, ny);
  ti.push(base + 2, base + 3, base + 1, base + 2, base + 1, base);
}
const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
const vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(tv), gl.STATIC_DRAW);
gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 20, 0);
gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 20, 8);
const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(ti), gl.STATIC_DRAW);
const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, POS, gl.STATIC_DRAW);
gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 2, gl.FLOAT, false, 8, 0); gl.vertexAttribDivisor(2, 1);
gl.bindVertexArray(null);
const TW = Math.min(2048, Math.max(1, Math.ceil(Math.sqrt(N)))), TH = Math.ceil(N / TW);
function makeTex(unit, ifmt, fmt, type, data) {
  const t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, ifmt, TW, TH, 0, fmt, type, data);
  return t;
}
gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
const topData = new Float32Array(TW * TH), colData = new Uint8Array(TW * TH * 4), maskData = new Uint8Array(TW * TH * 2);
const texTop = makeTex(0, gl.R32F, gl.RED, gl.FLOAT, topData);
const texCol = makeTex(1, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, colData);
const texMask = makeTex(2, gl.RG8, gl.RG, gl.UNSIGNED_BYTE, maskData);
function upload(unit, tex, fmt, type, data) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, tex); gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, TW, TH, fmt, type, data); }
function uploadTops() { topData.set(TOP); upload(0, texTop, gl.RED, gl.FLOAT, topData); }
uploadTops();

// picking framebuffer, redrawn only when something on screen changed
let pickFB = null, pickTex = null, pickDepth = null, pickW = 0, pickH = 0, pickDirty = true;
function ensurePick(w, h) {
  if (pickFB && pickW === w && pickH === h) return;
  if (pickFB) { gl.deleteFramebuffer(pickFB); gl.deleteTexture(pickTex); gl.deleteRenderbuffer(pickDepth); }
  pickW = w; pickH = h;
  pickTex = gl.createTexture(); gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, pickTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  pickDepth = gl.createRenderbuffer(); gl.bindRenderbuffer(gl.RENDERBUFFER, pickDepth); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
  pickFB = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, pickFB);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, pickTex, 0);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, pickDepth);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  pickDirty = true;
}

// ====================================================================== camera
let VW = 1, VH = 1, DPR = 1;
const cv = { c: 1, s: 0, sp: 0.6, cp: 0.8 };
function camVecs() {
  const a = (S.cam.yaw * Math.PI) / 180, p = (S.cam.pitch * Math.PI) / 180;
  cv.c = Math.cos(a); cv.s = Math.sin(a); cv.sp = Math.sin(p); cv.cp = Math.cos(p);
}
function project(x, y, z) {
  const dx = x - S.cam.x, dy = y - S.cam.y;
  const xr = cv.c * dx - cv.s * dy, yr = cv.s * dx + cv.c * dy;
  return [VW / 2 + xr * S.cam.zoom, VH / 2 - (yr * cv.sp + z * cv.cp) * S.cam.zoom];
}
function ground(sx, sy, z = 0) {   // screen point -> map point on the plane at height z
  const xr = (sx - VW / 2) / S.cam.zoom, yr = ((VH / 2 - sy) / S.cam.zoom - z * cv.cp) / cv.sp;
  return [S.cam.x + cv.c * xr + cv.s * yr, S.cam.y - cv.s * xr + cv.c * yr];
}
function fit() {
  camVecs();
  S.cam.x = (minX + maxX) / 2; S.cam.y = (minY + maxY) / 2;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  const z0 = S.cam.zoom; S.cam.zoom = 1;
  for (const [x, y] of [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]]) for (const z of [BASE, ZMAX]) {
    const [sx, sy] = project(x, y, z); x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
  }
  const padL = innerWidth > 760 ? 330 : 20, padR = innerWidth > 760 ? 40 : 20;
  S.cam.zoom = Math.max(1e-6, Math.min((VW - padL - padR) / (x1 - x0), (VH - 190) / (y1 - y0))) || z0;
  camVecs();
  const [cx, cy] = ground(VW / 2 - (padL - padR) / 2, VH / 2 + 20);
  S.cam.x = cx; S.cam.y = cy;
}

function resize() {
  DPR = Math.min(devicePixelRatio || 1, 2);
  VW = innerWidth; VH = innerHeight;
  for (const c of [glc, ov, fx]) { c.width = Math.round(VW * DPR); c.height = Math.round(VH * DPR); }
  octx.setTransform(DPR, 0, 0, DPR, 0, 0); fctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  dirty.terrain = dirty.overlay = true; pickDirty = true;
}
const ov = $("#ov"), fx = $("#fx"), octx = ov.getContext("2d"), fctx = fx.getContext("2d");
const dirty = { terrain: true, overlay: true, fx: true };
const groundColor = () => hex(getComputedStyle(document.documentElement).getPropertyValue("--ground").trim() || "#d9dfe5");
let GROUND = groundColor();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { GROUND = groundColor(); dirty.terrain = dirty.overlay = true; });

function lightVec() {
  // light from the upper left of the screen, whatever the heading
  const hx = cv.s, hy = cv.c, lx = -cv.c, ly = cv.s;      // screen up and screen left, in map axes
  let x = hx + lx, y = hy + ly; const L = Math.hypot(x, y); x /= L; y /= L;
  return [x, y];
}
function drawTerrain(pick = false) {
  gl.useProgram(prog);
  gl.bindVertexArray(vao);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texTop);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texCol);
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, texMask);
  gl.uniform1i(U.uTop, 0); gl.uniform1i(U.uCol, 1); gl.uniform1i(U.uMask, 2); gl.uniform1i(U.uTW, TW);
  gl.uniform2f(U.uTarget, S.cam.x, S.cam.y); gl.uniform2f(U.uRot, cv.c, cv.s); gl.uniform2f(U.uPitch, cv.sp, cv.cp);
  gl.uniform2f(U.uView, VW, VH); gl.uniform1f(U.uZoom, S.cam.zoom);
  gl.uniform1f(U.uDepth, (RADIUS + Math.hypot(S.cam.x, S.cam.y) + ZMAX + Math.abs(BASE)) * 1.05);
  gl.uniform1f(U.uBase, BASE); gl.uniform1f(U.uShadeTop, S.shade ? 1 : 0);
  const [lx, ly] = lightVec(); gl.uniform3f(U.uLight, lx, ly, 0);
  gl.uniform1f(U.uDim, S.trade.on ? S.trade.dim : 0);
  gl.uniform3f(U.uDimTo, GROUND[0] / 255, GROUND[1] / 255, GROUND[2] / 255);
  gl.uniform1i(U.uPick, pick ? 1 : 0);
  const tilePx = SPACING * S.cam.zoom;
  gl.uniform1f(U.uOutline, S.outlines ? Math.max(0, Math.min(1, (tilePx - 7) / 10)) : 0);
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
  if (pick) { gl.bindFramebuffer(gl.FRAMEBUFFER, pickFB); gl.viewport(0, 0, pickW, pickH); gl.clearColor(0, 0, 0, 0); }
  else { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, glc.width, glc.height); gl.clearColor(GROUND[0] / 255, GROUND[1] / 255, GROUND[2] / 255, 1); }
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.drawElementsInstanced(gl.TRIANGLES, ti.length, gl.UNSIGNED_SHORT, 0, N);
  gl.bindVertexArray(null);
  if (pick) gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}
const pickPx = new Uint8Array(4);
function pickTile(sx, sy) {
  ensurePick(glc.width, glc.height);
  if (pickDirty) { drawTerrain(true); pickDirty = false; }
  gl.bindFramebuffer(gl.FRAMEBUFFER, pickFB);
  gl.readPixels(Math.round(sx * DPR), Math.round((VH - sy) * DPR), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pickPx);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  const k = pickPx[0] | (pickPx[1] << 8) | (pickPx[2] << 16);
  return k ? k - 1 : -1;
}

// ====================================================================== painting
let LEG = null;     // what the legend shows for the current paint
function shadeTops() {
  const [lx, ly] = lightVec(), lz = 1, e = S.exag * ZM;
  const Ll = Math.hypot(lx, ly, lz), Lx = lx / Ll, Ly = ly / Ll, Lz = lz / Ll;
  const out = new Uint8Array(N);
  for (let i = 0; i < N; i++) {
    if (!LAND[i]) { out[i] = 128; continue; }
    const nx = -GX[i] * e, ny = -GY[i] * e, nl = Math.hypot(nx, ny, 1);
    const s = (nx * Lx + ny * Ly + Lz) / nl / Lz;
    out[i] = Math.max(70, Math.min(160, Math.round(128 * (0.35 + 0.65 * s))));
  }
  return out;
}
function paint() {
  const key = S.paint, shade = shadeTops();
  const put = (i, c) => { colData[4 * i] = c[0]; colData[4 * i + 1] = c[1]; colData[4 * i + 2] = c[2]; colData[4 * i + 3] = shade[i]; };
  if (key === "@landscape") {
    const bio = F["biome"];
    for (let i = 0; i < N; i++) {
      if (!LAND[i]) { put(i, RAMPS.sea(Math.max(-4000, ELEV[i]))); continue; }
      let c = bio ? catColor(bio, values(bio)[i]) : null;
      if (!c) c = RAMPS.land(ELEV[i]);
      const t = Math.min(1, Math.max(0, ELEV[i] / 3000));
      c = t > 0.55 ? mixc(c, [244, 246, 247], (t - 0.55) * 1.6) : mixc(c, [40, 50, 40], (0.55 - t) * 0.12);
      put(i, c);
    }
    LEG = { kind: "landscape" };
  } else {
    const f = F[key];
    const v = values(f);
    if (f.kind === "cat") {
      for (let i = 0; i < N; i++) {
        const c = catColor(f, v[i]);
        put(i, c || (LAND[i] ? LANDNULL : WATER));
      }
      LEG = { kind: "cat", f };
    } else {
      let fn, t0 = f.r0, t1 = f.r1, conv = (x) => x;
      if (f.ramp === "elevation") {
        const k = key === "h" ? null : (f.unit === "m" ? 1 : 1 / hRatio);
        fn = (x, i) => {
          if (k === null) return LAND[i] ? RAMPS.land(Math.max(0, (x - 20) / 80) * 3800) : RAMPS.sea(-Math.max(0, 20 - x) * 200);
          const m = x * k; return LAND[i] ? RAMPS.land(m) : RAMPS.sea(Math.max(-4000, m));
        };
      } else if (f.ramp === "thermal") {
        conv = TU === "°F" ? (x) => ((x - 32) * 5) / 9 : TU === "K" ? (x) => x - 273.15 : (x) => x;
        fn = (x) => RAMPS.thermal(conv(x));
      } else if (f.ramp === "index") {
        const d = Math.max(Math.abs(t0 - 1), Math.abs(t1 - 1), 0.02);
        fn = (x) => RAMPS.index(Math.max(-1, Math.min(1, (x - 1) / d)));
        t0 = 1 - d; t1 = 1 + d;
      } else {
        const R = RAMPS[f.ramp] || RAMPS.growth;
        if (f.scale === "log") {
          const a = Math.log(Math.max(t0, f.eps || 1e-9)), b = Math.log(Math.max(t1, (f.eps || 1e-9) * 10));
          fn = (x) => R(Math.max(0, Math.min(1, (Math.log(x) - a) / (b - a || 1))));
        } else fn = (x) => R(Math.max(0, Math.min(1, (x - t0) / (t1 - t0 || 1))));
      }
      for (let i = 0; i < N; i++) {
        const x = v[i];
        if (Number.isNaN(x) || (f.scale === "log" && x <= 0)) { put(i, LAND[i] ? LANDNULL : WATER); continue; }
        let c = fn(x, i);
        if (!LAND[i] && f.ramp !== "elevation") c = mixc(c, WATER, 0.45);
        put(i, c);
      }
      LEG = { kind: "num", f, t0, t1, conv };
    }
  }
  upload(1, texCol, gl.RGBA, gl.UNSIGNED_BYTE, colData);
  applyMask();
  renderLegend();
  dirty.terrain = true;
}
function applyMask() {
  const iso = S.isolate, v = iso && F[iso.key] ? values(F[iso.key]) : null;
  for (let i = 0; i < N; i++) { maskData[2 * i] = v && !iso.codes.has(v[i]) ? 0 : 255; maskData[2 * i + 1] = LAND[i] ? 0 : 255; }
  upload(2, texMask, gl.RG, gl.UNSIGNED_BYTE, maskData);
  dirty.terrain = true;
}

// ====================================================================== vector layers
function lineObj(xyArr, tiles) {
  const n = xyArr.length / 2, xy = new Float32Array(xyArr), tile = new Int32Array(tiles), z = new Float32Array(n);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let k = 0; k < n; k++) { const x = xy[2 * k], y = xy[2 * k + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return { xy, n, tile, z, bb: [x0, y0, x1, y1] };
}
// a line's pieces over the tiles: on a sheet, layers run on past its edge and are cut there
function prepLine(flat, onWater = false, clip = true) {
  const pieces = []; let xy = [], tl = [];
  const flush = () => { if (xy.length >= 4) pieces.push(lineObj(xy, tl)); xy = []; tl = []; };
  for (let k = 0; k < flat.length; k += 2) {
    const x = flat[k], y = flat[k + 1], t = tileAt(x, y, SPACING * 1.05);
    if (t < 0 && clip) { flush(); continue; }
    xy.push(x, y); tl.push(onWater ? -1 : t);
  }
  flush();
  return pieces;
}
const addLines = (arr, flat, f, onWater = false, clip = true) => { for (const o of prepLine(flat, onWater, clip)) { o.f = f; arr.push(o); } };
const L = { land: [], rivers: [], routes: [], borders: [], zones: [], journeys: [], squares: [], blocks: [], traffic: [], paths: [] };
for (const f of META.land) for (const r of f.rings) addLines(L.land, r.concat(r.slice(0, 2)), f, true);
for (const r of META.rivers) addLines(L.rivers, r.pts, r);
for (const r of META.routes) addLines(L.routes, r.pts, r, r.group === "searoutes");
for (const b of META.borders) for (const l of b.lines) addLines(L.borders, l, b);
for (const z of META.zones) for (const poly of z.polys) for (const r of poly) addLines(L.zones, r.concat(r.slice(0, 2)), z);
for (const j of META.journeys) addLines(L.journeys, j.pts, j);
for (const s of META.squares) addLines(L.squares, s.pts, s);
for (const s of META.blocks) addLines(L.blocks, s.pts, s);
for (const t of META.traffic) addLines(L.traffic, t.pts, t);
for (const p of META.paths) {
  const o = prepLine(p.pts, false, false)[0] || lineObj(p.pts.concat(p.pts), [-1, -1]); o.f = p; o.cum = new Float32Array(o.n);
  for (let k = 1; k < o.n; k++) o.cum[k] = o.cum[k - 1] + Math.hypot(o.xy[2 * k] - o.xy[2 * k - 2], o.xy[2 * k + 1] - o.xy[2 * k - 1]);
  o.len = o.cum[o.n - 1] || 1e-9; L.paths.push(o);
}
const PT = (xy) => { const t = tileAt(xy[0], xy[1], SPACING * 1.5); return { x: xy[0], y: xy[1], tile: t }; };
const BURGS = META.burgs.map((b, k) => Object.assign(PT(b.xy), { b, k }));
const MARKETS = META.markets.map((m, k) => Object.assign(PT(m.xy), { m, k }));
const MARKERS = META.markers.map((m, k) => Object.assign(PT(m.xy), { m, k }));
const UNITS = META.units.map((u, k) => Object.assign(PT(u.xy), { u, k }));
const STOPS = META.stops.map((s, k) => Object.assign(PT(s.xy), { s, k }));
const PLACES = META.places.map((p, k) => Object.assign(PT(p.xy), { p, k }));
const tileBurgs = new Map(), tileMarkers = new Map(), tileUnits = new Map(), tileStops = new Map();
const addTo = (m, t, v) => { if (t < 0) return; if (!m.has(t)) m.set(t, []); m.get(t).push(v); };
BURGS.forEach((b) => addTo(tileBurgs, b.tile, b)); MARKERS.forEach((m) => addTo(tileMarkers, m.tile, m));
UNITS.forEach((u) => addTo(tileUnits, u.tile, u)); STOPS.forEach((s) => addTo(tileStops, s.tile, s));
const marketOfBurg = new Map();
for (const m of MARKETS) { const b = BURGS.find((x) => x.b.name === m.m.centre && Math.hypot(x.x - m.x, x.y - m.y) < SPACING); if (b) marketOfBurg.set(b.k, m.k); }
const zOf = (t) => (t >= 0 ? TOP[t] : 0);
function updateZ() {
  for (const k in L) for (const o of L[k]) for (let i = 0; i < o.n; i++) o.z[i] = zOf(o.tile[i]);
  for (const arr of [BURGS, MARKETS, MARKERS, UNITS, STOPS, PLACES]) for (const p of arr) p.z = zOf(p.tile);
}
updateZ();

// state labels: weighted centre of each state's land tiles
const STATE_LABELS = [];
{
  const fs = F["state"] || F["t:state"];
  if (fs) {
    const v = values(fs), acc = new Map();
    for (let i = 0; i < N; i++) {
      if (!v[i] || !LAND[i]) continue;
      const a = acc.get(v[i]) || { x: 0, y: 0, n: 0 }; a.x += POS[2 * i]; a.y += POS[2 * i + 1]; a.n++; acc.set(v[i], a);
    }
    for (const [code, a] of acc) {
      const x = a.x / a.n, y = a.y / a.n;
      STATE_LABELS.push({ name: fs.dict[code - 1], x, y, n: a.n, tile: tileAt(x, y, SPACING * 3) });
    }
    STATE_LABELS.sort((p, q) => q.n - p.n);
  }
}

// ====================================================================== trade
const GOODS = META.goods;
const GOOD_COLOR = GOODS.map((g, k) => PALETTE[(k * 7) % PALETTE.length]);
const DEALS = META.deals.map((d) => ({ id: d[0], good: d[1], units: d[2], price: d[3], value: d[4] || 0, tax: d[5], kind: d[6], seller: d[7], buyer: d[8], path: d[9], routed: d[10] }));
const KIND_NAMES = ["Markets selling to towns", "Towns stocking markets", "Between markets"];
const goodTotals = GOODS.map(() => 0); for (const d of DEALS) goodTotals[d.good] += d.value;
S.trade.goods = new Set(GOODS.map((_, k) => k));
const medianValue = (() => { const v = DEALS.map((d) => d.value).sort((a, b) => a - b); return v.length ? Math.max(1e-6, v[Math.floor(v.length / 2)]) : 1; })();
let ACTIVE = [], STREAMS = [];
function placesOfFocus() {
  const f = S.trade.focus; if (!f) return null;
  const set = new Set();
  PLACES.forEach((p) => { if ((f.burg !== undefined && p.p.burg === f.burg) || (f.market !== undefined && p.p.market === f.market)) set.add(p.k); });
  return set;
}
function filterDeals() {
  const g = S.trade.goods, k = S.trade.kinds, foc = placesOfFocus();
  ACTIVE = DEALS.filter((d) => g.has(d.good) && (d.kind > 2 || k[d.kind]) && (!foc || foc.has(d.seller) || foc.has(d.buyer)));
  // deals of one good over one path move as a single stream
  const m = new Map();
  for (const d of ACTIVE) {
    const key = d.path * 4096 + d.good;
    const s = m.get(key) || { path: d.path, good: d.good, value: 0, deals: 0 };
    s.value += d.value; s.deals++; m.set(key, s);
  }
  STREAMS = [...m.values()];
  for (const s of STREAMS) {
    s.n = 1 + (s.value > medianValue * 10 ? 1 : 0) + (s.value > medianValue * 60 ? 1 : 0);
    s.phase = (hash(`${s.path}:${s.good}`) % 1000) / 1000;
  }
  const hint = $("#trade-hint"); if (hint) hint.textContent = S.trade.on ? `${ACTIVE.length.toLocaleString("en")} deals` : "";
  dirty.overlay = true;
}
const SPRITES = GOOD_COLOR.map((c) => {
  const s = document.createElement("canvas"), r = 4.2, d = Math.ceil((r + 2) * 2 * 2);
  s.width = s.height = d; const x = s.getContext("2d"); x.scale(2, 2);
  x.beginPath(); x.arc(d / 4, d / 4, r, 0, Math.PI * 2); x.fillStyle = css(c); x.fill();
  x.lineWidth = 1; x.strokeStyle = "rgba(255,255,255,.75)"; x.stroke();
  x.beginPath(); x.arc(d / 4, d / 4, r + 1, 0, Math.PI * 2); x.lineWidth = 0.8; x.strokeStyle = "rgba(10,15,25,.35)"; x.stroke();
  return s;
});

// ====================================================================== drawing the overlay
function onScreen(bb, zmax) {
  const pad = 40 + zmax * cv.cp * S.cam.zoom;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const [x, y] of [[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]]]) {
    const [sx, sy] = project(x, y, 0); if (sx < x0) x0 = sx; if (sx > x1) x1 = sx; if (sy < y0) y0 = sy; if (sy > y1) y1 = sy;
  }
  return x1 > -pad && x0 < VW + pad && y1 > -pad && y0 < VH + pad;
}
function pathOf(ctx, o, close = false, lift = 0) {
  ctx.beginPath();
  for (let k = 0; k < o.n; k++) {
    const [sx, sy] = project(o.xy[2 * k], o.xy[2 * k + 1], o.z[k] + lift);
    if (k) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy);
  }
  if (close) ctx.closePath();
}
const STANCE = { Enemy: "#c0392b", Rival: "#d35400", Suspicion: "#c99a1e", Unknown: "#8a8f98", Neutral: "#6d7480", Friendly: "#3f8f5a", Ally: "#2c7a4b", Vassal: "#5b6fb3", Suzerain: "#5b6fb3" };
const STANCE_RANK = ["Enemy", "Rival", "Suspicion", "Unknown", "Neutral", "Friendly", "Vassal", "Suzerain", "Ally"];
function worstStance(b) { const a = [b.ab, b.ba].filter(Boolean); a.sort((p, q) => STANCE_RANK.indexOf(p) - STANCE_RANK.indexOf(q)); return a[0] || "Neutral"; }
const ZONE_HUE = (t) => PALETTE[hash(t || "zone") % PALETTE.length];
let HITS = [];   // clickable pins drawn this frame
const DARK = () => matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light";
function halo(ctx, text, x, y, font, fill, align = "center") {
  ctx.font = font; ctx.textAlign = align; ctx.textBaseline = "middle";
  ctx.lineJoin = "round"; ctx.lineWidth = 3.2; ctx.strokeStyle = DARK() ? "rgba(14,19,26,.85)" : "rgba(247,248,250,.9)";
  ctx.strokeText(text, x, y); ctx.fillStyle = fill; ctx.fillText(text, x, y);
}
function drawOverlay() {
  const c = octx; c.clearRect(0, 0, VW, VH); HITS = [];
  const tilePx = SPACING * S.cam.zoom, ink = DARK() ? "#e4e9ef" : "#1b2430";
  const sh = S.show;
  const lw = (w) => Math.max(0.6, Math.min(w, w * (tilePx / 8)));
  c.globalAlpha = S.trade.on ? 0.45 : 1;
  if (sh.zones) for (const o of L.zones) {
    if (!onScreen(o.bb, ZMAX)) continue;
    const col = ZONE_HUE(o.f.type); pathOf(c, o, false, 0.002);
    c.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},.22)`; c.fill();
    c.setLineDash([5, 4]); c.lineWidth = 1.4; c.strokeStyle = css(col); c.stroke(); c.setLineDash([]);
  }
  if (sh.coast) { c.lineWidth = lw(1.1); c.strokeStyle = DARK() ? "rgba(200,220,240,.55)" : "rgba(30,50,80,.55)"; for (const o of L.land) { if (!onScreen(o.bb, 0)) continue; pathOf(c, o, false); c.stroke(); } }
  if (sh.squares) {
    c.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--grid"); c.lineWidth = 1.3;
    for (const o of L.squares) { if (!onScreen(o.bb, ZMAX)) continue; pathOf(c, o, false); c.stroke(); }
  }
  if (sh.blocks && tilePx > 2.5) {
    const ga = c.globalAlpha;
    c.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--grid"); c.globalAlpha = ga * 0.45; c.lineWidth = 0.8;
    for (const o of L.blocks) { if (!onScreen(o.bb, ZMAX)) continue; pathOf(c, o, false); c.stroke(); }
    c.globalAlpha = ga;
  }
  if (sh.rivers) {
    c.strokeStyle = "#3d7fc4"; c.lineCap = "round"; c.lineJoin = "round";
    for (const o of L.rivers) {
      if (!onScreen(o.bb, ZMAX)) continue;
      c.lineWidth = Math.max(0.8, Math.min(5, Math.sqrt(o.f.discharge || 1) / 6 * Math.min(1.5, tilePx / 6)));
      pathOf(c, o, false, SPACING * 0.01); c.stroke();
    }
  }
  if (sh.borders) {
    for (const o of L.borders) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const st = worstStance(o.f);
      pathOf(c, o, false, SPACING * 0.02);
      c.lineWidth = 4; c.strokeStyle = DARK() ? "rgba(14,19,26,.6)" : "rgba(255,255,255,.65)"; c.stroke();
      c.setLineDash([7, 4]); c.lineWidth = 1.8; c.strokeStyle = STANCE[st] || STANCE.Neutral; c.stroke(); c.setLineDash([]);
    }
  }
  if (sh.routes) {
    for (const o of L.routes) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const g = o.f.group;
      if (g === "trails" && tilePx < 1.5) continue;
      pathOf(c, o, false, SPACING * 0.015);
      if (g === "searoutes") { c.setLineDash([2, 5]); c.lineWidth = 1.2; c.strokeStyle = DARK() ? "rgba(170,205,240,.75)" : "rgba(30,70,120,.6)"; }
      else if (g === "roads") { c.setLineDash([]); c.lineWidth = lw(2.2); c.strokeStyle = "#9b3b25"; }
      else { c.setLineDash([5, 3]); c.lineWidth = lw(1.3); c.strokeStyle = DARK() ? "#c49a6c" : "#7a5536"; }
      c.stroke(); c.setLineDash([]);
    }
  }
  if (S.trade.traffic && L.traffic.length) {
    let maxv = 0; for (const o of L.traffic) maxv = Math.max(maxv, o.f.value || 0);
    c.lineCap = "round";
    for (const o of L.traffic) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const gi = GOODS.indexOf(o.f.top); const col = gi >= 0 ? GOOD_COLOR[gi] : [120, 120, 120];
      c.lineWidth = 1 + 9 * Math.sqrt((o.f.value || 0) / (maxv || 1));
      c.strokeStyle = `rgba(${col[0]},${col[1]},${col[2]},.55)`; pathOf(c, o, false, SPACING * 0.03); c.stroke();
    }
  }
  c.globalAlpha = 1;
  if (S.trade.on) drawTradePaths(c);
  if (sh.journeys) {
    for (const o of L.journeys) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const col = PALETTE[hash(o.f.journey || "") % PALETTE.length];
      pathOf(c, o, false, SPACING * 0.05);
      c.lineWidth = 5; c.strokeStyle = DARK() ? "rgba(14,19,26,.7)" : "rgba(255,255,255,.75)"; c.stroke();
      c.setLineDash([9, 5]); c.lineWidth = 2.6; c.strokeStyle = css(col); c.stroke(); c.setLineDash([]);
    }
    for (const s of STOPS) {
      const [x, y] = project(s.x, s.y, s.z); if (x < -20 || y < -20 || x > VW + 20 || y > VH + 20) continue;
      c.beginPath(); c.arc(x, y, 5, 0, Math.PI * 2); c.fillStyle = DARK() ? "#141a22" : "#fff"; c.fill(); c.lineWidth = 2; c.strokeStyle = ink; c.stroke();
      if (tilePx > 3) halo(c, s.s.name, x + 9, y, "italic 500 12px Alegreya, serif", ink, "left");
      HITS.push({ x, y, r: 7, kind: "stop", o: s });
    }
  }
  if (sh.states && STATE_LABELS.length) {
    const taken = [];
    for (const s of STATE_LABELS) {
      const [x, y] = project(s.x, s.y, zOf(s.tile) + SPACING * 0.4);
      const size = Math.max(11, Math.min(26, Math.sqrt(s.n) * tilePx * 0.12));
      if (size < 11.5 && s.n * tilePx * tilePx < 2500) continue;
      c.font = `700 ${size}px "Alegreya Sans SC", "Alegreya Sans", sans-serif`;
      const label = s.name.split("").join(String.fromCharCode(8202)), w = c.measureText(label).width;
      const box = [x - w / 2, y - size / 2, x + w / 2, y + size / 2];
      if (taken.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
      taken.push(box);
      halo(c, label, x, y, c.font, DARK() ? "rgba(228,233,239,.82)" : "rgba(27,36,48,.72)");
    }
  }
  if (sh.units) for (const u of UNITS) {
    const [x, y] = project(u.x, u.y, u.z); if (x < -20 || y < -20 || x > VW + 20 || y > VH + 20) continue;
    const st = F["state"] ? F["state"].dict.indexOf(u.u.state) : -1;
    const col = st >= 0 ? PALETTE[st % PALETTE.length] : [120, 120, 130];
    c.strokeStyle = ink; c.lineWidth = 1.2; c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - 16); c.stroke();
    c.fillStyle = css(col); c.beginPath();
    if (u.u.naval) { c.moveTo(x, y - 16); c.lineTo(x + 10, y - 12); c.lineTo(x, y - 8); } else c.rect(x, y - 16, 10, 7);
    c.fill(); c.stroke();
    HITS.push({ x: x + 4, y: y - 12, r: 8, kind: "unit", o: u });
  }
  if (sh.burgs) drawBurgs(c, tilePx, ink);
  if (sh.markers) for (const m of MARKERS) {
    const [x, y] = project(m.x, m.y, m.z); if (x < -20 || y < -20 || x > VW + 20 || y > VH + 20) continue;
    if (tilePx < 3) {
      c.beginPath(); c.arc(x, y - 3, 2.6, 0, Math.PI * 2); c.fillStyle = DARK() ? "#f0f3f6" : "#fff"; c.fill();
      c.lineWidth = 1; c.strokeStyle = "#8a4b9e"; c.stroke(); HITS.push({ x, y: y - 3, r: 6, kind: "marker", o: m }); continue;
    }
    c.beginPath(); c.arc(x, y - 10, 9, 0, Math.PI * 2); c.fillStyle = DARK() ? "rgba(20,26,34,.9)" : "rgba(255,255,255,.92)"; c.fill();
    c.lineWidth = 1; c.strokeStyle = "rgba(0,0,0,.25)"; c.stroke();
    c.font = "12px system-ui, 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillStyle = ink; c.fillText(m.m.icon || "•", x, y - 9.5);
    HITS.push({ x, y: y - 10, r: 10, kind: "marker", o: m });
  }
  if (S.sel >= 0) outlineTile(c, S.sel, getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(), 2.6);
  dirty.overlay = false;
}
function drawBurgs(c, tilePx, ink) {
  const order = BURGS.slice().sort((a, b) => (b.b.people || 0) - (a.b.people || 0));
  const taken = [], grid = new Map(), cellSz = 60;
  const free = (b) => {
    for (let gx = Math.floor(b[0] / cellSz); gx <= Math.floor(b[2] / cellSz); gx++) for (let gy = Math.floor(b[1] / cellSz); gy <= Math.floor(b[3] / cellSz); gy++) {
      for (const o of grid.get(gx + "," + gy) || []) if (!(b[2] < o[0] || b[0] > o[2] || b[3] < o[1] || b[1] > o[3])) return false;
    }
    return true;
  };
  const occupy = (b) => { for (let gx = Math.floor(b[0] / cellSz); gx <= Math.floor(b[2] / cellSz); gx++) for (let gy = Math.floor(b[1] / cellSz); gy <= Math.floor(b[3] / cellSz); gy++) { const k = gx + "," + gy; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(b); } };
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const tierOf = (b) => (b.group === "capital" ? 4 : b.group === "city" ? 3 : b.group === "town" ? 2 : 1);
  const pins = [];
  for (const B of order) {
    const [x, y] = project(B.x, B.y, B.z); if (x < -40 || y < -40 || x > VW + 40 || y > VH + 40) continue;
    const t = tierOf(B.b);
    if ((t === 1 && tilePx < 3) || (t === 2 && tilePx < 1.2)) continue;
    const stem = 7 + t * 3.5, r = 1.8 + t * 0.9;
    pins.push({ B, x, y, t, stem, r });
  }
  for (const p of pins.slice().reverse()) {   // small ones first, so large pins sit on top
    const { B, x, y, t, stem, r } = p; const sel = S.selBurg === B.k;
    c.strokeStyle = sel ? accent : ink; c.lineWidth = sel ? 1.8 : 1; c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - stem); c.stroke();
    const flags = B.b.flags || [];
    c.beginPath();
    if (flags.includes("walls")) c.rect(x - r, y - stem - r, 2 * r, 2 * r); else c.arc(x, y - stem, r, 0, Math.PI * 2);
    c.fillStyle = sel ? accent : (DARK() ? "#f0f3f6" : "#ffffff"); c.fill();
    c.lineWidth = flags.includes("port") ? 2 : 1.3; c.strokeStyle = sel ? accent : (flags.includes("port") ? "#2b6cb0" : ink); c.stroke();
    if (flags.includes("capital")) { c.beginPath(); c.arc(x, y - stem, r * 0.45, 0, Math.PI * 2); c.fillStyle = ink; c.fill(); }
    if (S.show.markets && marketOfBurg.has(B.k)) {
      const yy = y - stem - r - 6; c.beginPath(); c.moveTo(x, yy - 4.5); c.lineTo(x + 4.5, yy); c.lineTo(x, yy + 4.5); c.lineTo(x - 4.5, yy); c.closePath();
      c.fillStyle = "#e0a526"; c.fill(); c.lineWidth = 1; c.strokeStyle = ink; c.stroke();
    }
    HITS.push({ x, y: y - stem, r: Math.max(7, r + 4), kind: "burg", o: B });
  }
  if (!S.show.labels) return;
  const need = { 4: 0, 3: 1.2, 2: 4, 1: 10 };
  for (const p of pins) {
    const { B, x, y, t, stem } = p;
    if (tilePx < need[t] && S.selBurg !== B.k) continue;
    const size = 10.5 + t * 1.4, font = `${t >= 3 ? 700 : 500} ${size}px Alegreya, serif`;
    c.font = font; const w = c.measureText(B.b.name).width;
    const bx = x + 6, by = y - stem;
    const box = [bx - 2, by - size / 2 - 1, bx + w + 2, by + size / 2 + 1];
    if (!free(box)) continue;
    occupy(box);
    halo(c, B.b.name, bx, by, font, S.selBurg === B.k ? accent : ink, "left");
  }
}
function outlineTile(c, i, color, w) {
  const x = POS[2 * i], y = POS[2 * i + 1], z = TOP[i];
  c.beginPath();
  for (let k = 0; k <= NV; k++) { const v = SHAPE[k % NV]; const [sx, sy] = project(x + v[0], y + v[1], z); if (k) c.lineTo(sx, sy); else c.moveTo(sx, sy); }
  c.lineWidth = w; c.strokeStyle = color; c.lineJoin = "round"; c.stroke();
}
function drawTradePaths(c) {
  const seen = new Map();
  for (const d of ACTIVE) seen.set(d.path, (seen.get(d.path) || 0) + d.value);
  let maxv = 0; for (const v of seen.values()) maxv = Math.max(maxv, v);
  c.lineCap = "round"; c.lineJoin = "round";
  for (const [pi, v] of seen) {
    const o = L.paths[pi]; if (!onScreen(o.bb, ZMAX + o.len * 0.2)) continue;
    c.lineWidth = 0.8 + 2.4 * Math.sqrt(v / (maxv || 1));
    c.strokeStyle = DARK() ? "rgba(235,240,245,.28)" : "rgba(25,32,45,.28)";
    if (S.trade.straight || !o.f.r) arcPath(c, o); else pathOf(c, o, false, SPACING * 0.04);
    c.stroke();
  }
}
function arcAt(o, t) {
  const n = o.n - 1, x = o.xy[0] + (o.xy[2 * n] - o.xy[0]) * t, y = o.xy[1] + (o.xy[2 * n + 1] - o.xy[1]) * t;
  const L0 = Math.hypot(o.xy[2 * n] - o.xy[0], o.xy[2 * n + 1] - o.xy[1]);
  return [x, y, o.z[0] + (o.z[n] - o.z[0]) * t + 4 * Math.min(L0 * 0.18, SPACING * 30) * t * (1 - t) + SPACING * 0.05];
}
function arcPath(c, o) {
  c.beginPath();
  for (let k = 0; k <= 24; k++) { const [x, y, z] = arcAt(o, k / 24); const [sx, sy] = project(x, y, z); if (k) c.lineTo(sx, sy); else c.moveTo(sx, sy); }
}
function pathPoint(o, s) {
  let lo = 0, hi = o.n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (o.cum[m] <= s) lo = m; else hi = m; }
  const seg = o.cum[hi] - o.cum[lo] || 1e-9, t = (s - o.cum[lo]) / seg;
  return [o.xy[2 * lo] + (o.xy[2 * hi] - o.xy[2 * lo]) * t, o.xy[2 * lo + 1] + (o.xy[2 * hi + 1] - o.xy[2 * lo + 1]) * t,
    o.z[lo] + (o.z[hi] - o.z[lo]) * t + SPACING * 0.06];
}
let T0 = performance.now();
function drawFx(now) {
  const c = fctx; c.clearRect(0, 0, VW, VH);
  if (S.hover >= 0 && S.hover !== S.sel) outlineTile(c, S.hover, DARK() ? "rgba(255,255,255,.85)" : "rgba(20,28,40,.8)", 1.6);
  if (!S.trade.on || !STREAMS.length) return;
  const t = (now - T0) / 1000, v = S.trade.speed / S.cam.zoom;
  const size = SPRITES[0].width / 2, tilePx = SPACING * S.cam.zoom;
  const zoomSc = Math.max(0.55, Math.min(1, 0.45 + tilePx / 30)), tail = 14 / S.cam.zoom;
  c.lineCap = "round";
  for (const d of STREAMS) {
    const o = L.paths[d.path]; if (!o) continue;
    const straight = S.trade.straight || !o.f.r;
    const len = straight ? Math.hypot(o.xy[2 * o.n - 2] - o.xy[0], o.xy[2 * o.n - 1] - o.xy[1]) || 1e-9 : o.len;
    for (let k = 0; k < d.n; k++) {
      const s = (((t * v) / len + d.phase + k / d.n) % 1);
      const p = straight ? arcAt(o, s) : pathPoint(o, s * len);
      const [sx, sy] = project(p[0], p[1], p[2]);
      if (sx < -10 || sy < -10 || sx > VW + 10 || sy > VH + 10) continue;
      const s0 = Math.max(0, s - tail / len), q = straight ? arcAt(o, s0) : pathPoint(o, s0 * len);
      const [tx, ty] = project(q[0], q[1], q[2]), col = GOOD_COLOR[d.good % GOOD_COLOR.length];
      const sc = zoomSc * (0.55 + 0.45 * Math.min(1, Math.sqrt(d.value / medianValue) / 5));
      const g = c.createLinearGradient(tx, ty, sx, sy);
      g.addColorStop(0, `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},0)`); g.addColorStop(1, `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},.9)`);
      c.strokeStyle = g; c.lineWidth = 3 * sc; c.beginPath(); c.moveTo(tx, ty); c.lineTo(sx, sy); c.stroke();
      const w = size * sc; c.drawImage(SPRITES[d.good % SPRITES.length], sx - w / 2, sy - w / 2, w, w);
    }
  }
  if (S.trade.focus) {
    const fp = PLACES.filter((p) => (S.trade.focus.burg !== undefined && p.p.burg === S.trade.focus.burg) || (S.trade.focus.market !== undefined && p.p.market === S.trade.focus.market));
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    for (const p of fp) {
      const [x, y] = project(p.x, p.y, p.z), r = 11 + 3 * Math.sin(t * 3);
      c.beginPath(); c.arc(x, y, REDUCED ? 12 : r, 0, Math.PI * 2); c.lineWidth = 2; c.strokeStyle = accent; c.stroke();
    }
  }
}

// ====================================================================== the frame loop
let lastCam = "";
function frame(now) {
  const key = `${S.cam.x},${S.cam.y},${S.cam.zoom},${S.cam.yaw},${S.cam.pitch},${VW},${VH}`;
  if (key !== lastCam) { lastCam = key; camVecs(); syncDial(); syncTilt(); dirty.terrain = dirty.overlay = dirty.fx = true; pickDirty = true; }
  if (dirty.terrain) { drawTerrain(false); dirty.terrain = false; pickDirty = true; }
  if (dirty.overlay) drawOverlay();
  if (S.trade.on || dirty.fx) { drawFx(now); dirty.fx = false; }
  if (fly) stepFly(now);
  requestAnimationFrame(frame);
}

// ====================================================================== controls: paint
const paintSel = $("#paint");
{
  if (F["biome"]) paintSel.append(el("option", { value: "@landscape", text: "Landscape (biome and relief)" }));
  const groups = {};
  for (const f of FIELDS) if (f.paint) (groups[f.group] = groups[f.group] || []).push(f);
  const ordered = ["Land", "People", "Realm", "Economy", "Trade", "Goods", "Places", "Reference", "Other"];
  for (const g of ordered) {
    if (!groups[g]) continue;
    const og = el("optgroup", { label: g });
    for (const f of groups[g].sort((a, b) => (g === "Goods" ? a.label.localeCompare(b.label) : 0))) og.append(el("option", { value: f.key, text: f.label }));
    paintSel.append(og);
  }
  paintSel.value = S.paint;
  paintSel.addEventListener("change", () => { S.paint = paintSel.value; S.isolate = null; paint(); if (S.sel >= 0) inspect(S.sel); });
}
function renderLegend() {
  const box = $("#legend"); box.replaceChildren();
  if (!LEG) return;
  if (LEG.kind === "landscape") {
    const bio = F["biome"]; const ul = el("ul", { class: "cats" });
    if (bio) bio.dict.forEach((name, k) => ul.append(el("li", {}, el("span", { class: "sw", style: `background:${css(catColor(bio, k + 1))}` }), name, el("small", { text: bio.counts[k].toLocaleString("en") }))));
    box.append(ul, el("p", { class: "about", text: "Biome of the cell under each tile centre, lightened with height; the sea darkens with depth." }));
    return;
  }
  const f = LEG.f;
  if (LEG.kind === "cat") {
    const ul = el("ul", { class: "cats" });
    f.dict.slice(0, 400).forEach((name, k) => {
      const code = k + 1, on = !S.isolate || S.isolate.codes.has(code);
      const li = el("li", { class: on ? "" : "off", title: "Click to show only this; click again to show all" },
        el("span", { class: "sw", style: `background:${css(catColor(f, code))}` }), name, el("small", { text: f.counts[k].toLocaleString("en") }));
      li.addEventListener("click", () => {
        if (S.isolate && S.isolate.key === f.key && S.isolate.codes.size === 1 && S.isolate.codes.has(code)) S.isolate = null;
        else S.isolate = { key: f.key, codes: new Set([code]) };
        applyMask(); renderLegend();
      });
      ul.append(li);
    });
    box.append(ul, el("p", { class: "about", text: `${f.dict.length.toLocaleString("en")} values, counted in tiles. Click one to pick it out.` }));
    return;
  }
  let stops;
  if (f.ramp === "elevation") stops = ["#203b6e", "#5b8cc0", "#8bb3d7", "#5e9a5b", "#d6c681", "#987157", "#f1f3f4"];
  else if (f.ramp === "thermal") stops = ["#26397f", "#99c1e2", "#e6eef0", "#f2e1a2", "#efb267", "#b12f29"];
  else stops = RAMP_CSS[f.ramp] || RAMP_CSS.growth;
  const fmt = (x) => fmtField(f, x);
  box.append(el("div", { class: "ramp", style: `background:linear-gradient(90deg,${stops.join(",")})` }),
    el("div", { class: "ramp-labels" }, el("span", { text: f.ramp === "elevation" ? `${fmt(f.lo)}` : fmt(LEG.t0) }),
      f.ramp === "elevation" && f.lo < 0 && f.hi > 0 && f.key !== "h" ? el("span", { text: "sea level" }) : (f.ramp === "index" ? el("span", { text: "average" }) : null),
      el("span", { text: f.ramp === "elevation" ? fmt(f.hi) : fmt(LEG.t1) })),
    el("p", { class: "about", text: `${f.scale === "log" ? "Log scale. " : ""}${srcText(f.src)}. Full range ${fmt(f.lo)} to ${fmt(f.hi)}.${f.scale === "log" ? " Grey land has none." : ""}` }));
}
const srcText = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

// ====================================================================== controls: show, trade, view
function toggleRow(label, get, set, key) {
  const id = "t-" + label.replace(/\W+/g, "-").toLowerCase();
  const inp = el("input", { type: "checkbox", id }); inp.checked = get();
  inp.addEventListener("change", () => { set(inp.checked); dirty.overlay = true; });
  return el("label", { class: "row", for: id }, inp, label, key || null);
}
{
  const T = $("#toggles"), sh = S.show;
  const rows = [
    ["Towns", "burgs", META.burgs.length], ["Town names", "labels", META.burgs.length], ["Markets", "markets", META.markets.length],
    ["Markers", "markers", META.markers.length], ["Regiments and fleets", "units", META.units.length],
    ["Rivers", "rivers", META.rivers.length], ["Roads, trails and sea routes", "routes", META.routes.length],
    ["Coastline", "coast", META.land.length], ["State borders", "borders", META.borders.length], ["State names", "states", STATE_LABELS.length],
    ["Zones", "zones", META.zones.length], ["Journeys", "journeys", META.journeys.length + META.stops.length],
    ["Lettered squares", "squares", META.squares.length], ["10 by 10 blocks", "blocks", META.blocks.length],
  ];
  for (const [label, k, n] of rows) if (n) T.append(toggleRow(label, () => sh[k], (v) => { sh[k] = v; }));
  T.append(toggleRow("Tile outlines", () => S.outlines, (v) => { S.outlines = v; dirty.terrain = true; }));
  if (META.borders.length) {
    const used = [...new Set(META.borders.map(worstStance))].sort((a, b) => STANCE_RANK.indexOf(a) - STANCE_RANK.indexOf(b));
    T.append(el("p", { class: "sub", text: "Borders by the cooler of the two stances" }),
      el("div", { style: "display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.88rem" },
        used.map((s) => el("span", { style: "display:inline-flex;align-items:center;gap:5px" }, el("span", { class: "sw", style: `background:${STANCE[s] || STANCE.Neutral}` }), s))));
  }
  if (META.burgs.length) T.append(el("p", { class: "sub", text: "Pins: taller for capitals and cities, a square head for walls, a blue ring for ports, a dark centre for capitals, a gold diamond for market centres." }));
}
function seg(options, get, set) {
  const box = el("div", { class: "seg", role: "group" });
  const btns = options.map(([v, label]) => {
    const b = el("button", { type: "button", "aria-pressed": String(get() === v), text: label });
    b.addEventListener("click", () => { set(v); btns.forEach((x, k) => x.setAttribute("aria-pressed", String(options[k][0] === get()))); });
    return b;
  });
  box.append(...btns); return box;
}
function slider(label, min, max, step, get, set, show) {
  const id = "s-" + label.replace(/\W+/g, "-").toLowerCase();
  const inp = el("input", { type: "range", id, min, max, step }); inp.value = get();
  const out = el("output", { for: id, text: show(get()) });
  inp.addEventListener("input", () => { set(+inp.value); out.textContent = show(+inp.value); });
  return { node: el("div", { class: "slider" }, el("span", {}, el("label", { for: id, text: label })), out, inp), inp, out };
}
const tradeBox = $("#trade");
let goodsList;
function buildTrade() {
  tradeBox.replaceChildren();
  if (!DEALS.length) { tradeBox.append(el("p", { class: "about", text: "This export has no deals layer." })); return; }
  tradeBox.append(toggleRow("Animate trade", () => S.trade.on, (v) => { S.trade.on = v; filterDeals(); dirty.terrain = true; dirty.fx = true; }));
  tradeBox.append(toggleRow("Load on each route segment", () => S.trade.traffic, (v) => { S.trade.traffic = v; }));
  const focusSlot = el("div", { id: "focus-slot" }); tradeBox.append(focusSlot);
  tradeBox.append(el("p", { class: "sub", text: "Kinds of deal" }));
  KIND_NAMES.forEach((name, k) => {
    const n = DEALS.filter((d) => d.kind === k).length; if (!n) return;
    tradeBox.append(toggleRow(name, () => S.trade.kinds[k], (v) => { S.trade.kinds[k] = v; filterDeals(); }, el("small", { class: "key", style: "color:var(--ink-3)", text: n.toLocaleString("en") })));
  });
  tradeBox.append(el("p", { class: "sub", text: "Goods travel" }),
    seg([[false, "Along the routes"], [true, "As the crow flies"]], () => S.trade.straight, (v) => { S.trade.straight = v; dirty.overlay = true; }));
  tradeBox.append(slider("Speed", 15, 220, 5, () => S.trade.speed, (v) => { S.trade.speed = v; }, (v) => `${v} px/s`).node);
  tradeBox.append(slider("Fade the tiles", 0, 0.9, 0.05, () => S.trade.dim, (v) => { S.trade.dim = v; dirty.terrain = true; }, (v) => `${Math.round(v * 100)}%`).node);
  const q = el("input", { type: "search", placeholder: "Filter goods", "aria-label": "Filter the goods list" });
  const all = el("button", { class: "linkbtn", type: "button", text: "All" }), none = el("button", { class: "linkbtn", type: "button", text: "None" });
  tradeBox.append(el("p", { class: "sub", style: "display:flex;gap:10px;align-items:baseline" }, "Goods", el("span", { style: "margin-left:auto;display:flex;gap:10px" }, all, none)), q);
  goodsList = el("ul", { class: "goods" }); tradeBox.append(goodsList);
  const maxT = Math.max(...goodTotals, 1e-9);
  const rows = GOODS.map((g, k) => {
    const cb = el("input", { type: "checkbox", id: `g-${k}`, "aria-label": g }); cb.checked = S.trade.goods.has(k);
    cb.addEventListener("change", () => { if (cb.checked) S.trade.goods.add(k); else S.trade.goods.delete(k); filterDeals(); });
    const li = el("li", { "data-name": g.toLowerCase() }, cb, el("span", { class: "sw", style: `background:${css(GOOD_COLOR[k])}` }),
      el("label", { for: `g-${k}`, text: g }), el("small", { text: fmtNum(goodTotals[k]) }),
      el("div", { class: "bar" }, el("i", { style: `width:${(100 * goodTotals[k]) / maxT}%` })));
    goodsList.append(li); return { li, cb, k };
  });
  q.addEventListener("input", () => { const s = q.value.trim().toLowerCase(); rows.forEach((r) => { r.li.hidden = s && !r.li.dataset.name.includes(s); }); });
  all.addEventListener("click", () => { rows.forEach((r) => { if (!r.li.hidden) { r.cb.checked = true; S.trade.goods.add(r.k); } }); filterDeals(); });
  none.addEventListener("click", () => { rows.forEach((r) => { if (!r.li.hidden) { r.cb.checked = false; S.trade.goods.delete(r.k); } }); filterDeals(); });
  tradeBox.append(el("p", { class: "about", style: "font-size:.85rem;color:var(--ink-3);margin-top:8px", text: "Values are units times price, in coin. Click a town pin or a market’s gold diamond to follow its trade." }));
}
function renderFocus() {
  const slot = $("#focus-slot"); if (!slot) return; slot.replaceChildren();
  const f = S.trade.focus; if (!f) return;
  const x = el("button", { type: "button", "aria-label": "Show every place’s trade", text: "×" });
  x.addEventListener("click", () => { S.trade.focus = null; renderFocus(); filterDeals(); });
  slot.append(el("div", { class: "focus-chip" }, el("span", { text: `Only ${f.name}` }), x));
}
buildTrade();
{
  const V = $("#view");
  V.append(slider("Relief", 0, Math.round(EXAG0 * 4 * 10) / 10, Math.max(0.1, Math.round(EXAG0 / 20 * 10) / 10), () => S.exag,
    (v) => { S.exag = v; retop(); }, (v) => `× ${fmtNum(v)}`).node);
  const stepOpts = [[0, "Smooth"], [50, "50 m"], [100, "100 m"], [250, "250 m"], [500, "500 m"]];
  V.append(el("p", { class: "sub", text: "Height steps" }), seg(stepOpts, () => S.steps, (v) => { S.steps = v; retop(); }));
  V.append(slider("Tilt", 15, 90, 1, () => S.cam.pitch, (v) => { S.cam.pitch = v; }, (v) => `${v}°`).node);
  V.append(toggleRow("Shade slopes", () => S.shade, (v) => { S.shade = v; dirty.terrain = true; }));
  const themes = [["auto", "Device"], ["light", "Light"], ["dark", "Dark"]];
  V.append(el("p", { class: "sub", text: "Colours" }), seg(themes, () => document.documentElement.dataset.theme || "auto", (v) => {
    if (v === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
    GROUND = groundColor(); dirty.terrain = dirty.overlay = true;
  }));
  if (META.notes.length) V.append(el("p", { class: "sub", text: "About this export" }), el("ul", { style: "margin:0;padding-left:18px;font-size:.85rem;color:var(--ink-2)" }, META.notes.map((n) => el("li", { text: n }))));
}
function retop() { computeTops(); uploadTops(); updateZ(); paint(); dirty.overlay = true; }

// ====================================================================== inspector
const insp = $("#inspector"), ihead = $("#insp-head"), ibody = $("#insp-body");
const TAG = { "interpolated": "mixed", "clipped from the cells": "mixed", "zone outlines at the tile centre": "mixed" };
const tagOf = (src) => TAG[src] || "data";
function closeInspector() { insp.hidden = true; S.sel = -1; S.selBurg = -1; dirty.overlay = true; }
function kv(rows) { const dl = el("dl", { class: "kv" }); for (const r of rows) if (r) dl.append(el("dt", {}, r[0]), el("dd", { class: r[3] ? "painted" : "" }, r[1], r[2] ? el("small", { text: r[2] }) : null)); return dl; }
function fieldRows(i, group) {
  return FIELDS.filter((f) => f.group === group && !(f.kind === "num" && f.key.startsWith("g_"))).map((f) => {
    const v = f.kind === "cat" ? catOf(f, i) : numOf(f, i);
    if (v === null || (typeof v === "number" && Number.isNaN(v))) return null;
    return [el("span", { title: srcText(f.src), text: f.label }), fmtField(f, v), tagOf(f.src), S.paint === f.key];
  }).filter(Boolean);
}
function flowList(groups, total, colorOf, whoOf) {
  const ul = el("ul", { class: "flows" });
  for (const g of groups.slice(0, 10)) {
    ul.append(el("li", {}, el("span", { class: "sw", style: `background:${css(colorOf(g))}` }), el("span", { text: g.name }),
      el("span", { text: `${fmtNum(g.value)} coin` }), el("div", { class: "bar" }, el("i", { style: `width:${Math.max(2, (100 * g.value) / (total || 1))}%;background:${css(colorOf(g))}` })),
      whoOf ? el("span", { class: "who", text: whoOf(g) }) : null));
  }
  if (groups.length > 10) ul.append(el("li", {}, el("span"), el("span", { class: "who", style: "grid-column:2/4;margin:0", text: `and ${groups.length - 10} more goods` })));
  return ul;
}
function groupByGood(deals, other) {
  const m = new Map();
  for (const d of deals) {
    const g = m.get(d.good) || { good: d.good, name: GOODS[d.good], value: 0, who: new Map() };
    g.value += d.value; const w = PLACES[other(d)].p.name; g.who.set(w, (g.who.get(w) || 0) + d.value); m.set(d.good, g);
  }
  return [...m.values()].sort((a, b) => b.value - a.value);
}
const whoText = (g, verb) => { const w = [...g.who.entries()].sort((a, b) => b[1] - a[1]); return `${verb} ${w.slice(0, 3).map((x) => x[0]).join(", ")}${w.length > 3 ? ` and ${w.length - 3} more` : ""}`; };
function tradeSection(placeSet, isMarket) {
  const sells = DEALS.filter((d) => placeSet.has(d.seller)), buys = DEALS.filter((d) => placeSet.has(d.buyer));
  if (!sells.length && !buys.length) return null;
  const box = el("div");
  const sum = (a) => a.reduce((s, d) => s + d.value, 0);
  const col = (g) => GOOD_COLOR[g.good];
  if (isMarket) {
    const inBurg = buys.filter((d) => d.kind === 1), inMkt = buys.filter((d) => d.kind === 2);
    const outBurg = sells.filter((d) => d.kind === 0), outMkt = sells.filter((d) => d.kind === 2);
    const stock = [...inBurg, ...inMkt];
    if (stock.length) box.append(el("h3", {}, "Where the stock comes from", el("small", { text: `${fmtNum(sum(stock))} coin` })),
      flowList(groupByGood(stock, (d) => d.seller), sum(stock), col, (g) => whoText(g, "from")));
    if (inMkt.length) box.append(el("p", { class: "about", style: "font-size:.86rem;color:var(--ink-3)", text: `${fmtNum(sum(inMkt))} coin of it from other markets.` }));
    if (outBurg.length) box.append(el("h3", {}, "Sold to towns", el("small", { text: `${fmtNum(sum(outBurg))} coin` })),
      flowList(groupByGood(outBurg, (d) => d.buyer), sum(outBurg), col, (g) => whoText(g, "to")));
    if (outMkt.length) box.append(el("h3", {}, "Sent to other markets", el("small", { text: `${fmtNum(sum(outMkt))} coin` })),
      flowList(groupByGood(outMkt, (d) => d.buyer), sum(outMkt), col, (g) => whoText(g, "to")));
  } else {
    if (sells.length) box.append(el("h3", {}, "Sells", el("small", { text: `${fmtNum(sum(sells))} coin` })),
      flowList(groupByGood(sells, (d) => d.buyer), sum(sells), col, (g) => whoText(g, "to")));
    if (buys.length) box.append(el("h3", {}, "Buys", el("small", { text: `${fmtNum(sum(buys))} coin` })),
      flowList(groupByGood(buys, (d) => d.seller), sum(buys), col, (g) => whoText(g, "from")));
  }
  return box;
}
function focusTrade(f) {
  S.trade.focus = f; S.trade.on = true; $("#sec-trade").open = true;
  buildTrade(); renderFocus(); filterDeals(); dirty.terrain = true; dirty.fx = true;
}
function burgCard(B) {
  const b = B.b, flags = (b.flags || []).join(", ");
  const card = el("div", { class: "card" }, el("h4", {}, b.name, el("small", { text: [b.group, b.type].filter(Boolean).join(", ") })),
    el("p", { text: `${fmtNum(b.people, true)} people${flags ? `; ${flags}` : ""}` }),
    kv([["State", b.state], ["Province", b.province], ["Culture", b.culture], ["Faith", b.religion], ["Market", b.market], ["Point", b.pref]].filter((r) => r[1])));
  const placeSet = new Set(PLACES.filter((p) => p.p.burg === B.k).map((p) => p.k));
  const mk = marketOfBurg.get(B.k);
  const actions = el("div", { class: "actions" });
  if (placeSet.size) { const a = el("button", { class: "linkbtn", type: "button", text: `Show ${b.name}’s trade` }); a.addEventListener("click", () => focusTrade({ burg: B.k, name: b.name })); actions.append(a); }
  if (mk !== undefined) { const a = el("button", { class: "linkbtn", type: "button", text: `Show ${MARKETS[mk].m.centre} market’s trade` }); a.addEventListener("click", () => focusTrade({ market: mk, name: `${MARKETS[mk].m.centre} market` })); actions.append(a); }
  if (actions.childNodes.length) card.append(actions);
  if (mk !== undefined) {
    const m = MARKETS[mk].m;
    card.append(el("h3", {}, `${m.centre} market`, el("small", { text: `${m.burgs} towns, ${m.cells} cells` })),
      kv([["Bought from other markets", `${fmtNum(m.import)} coin`], ["Sold to other markets", `${fmtNum(m.export)} coin`], ["Price index", fmtNum(m.pi)], ["Food price index", fmtNum(m.fi)]]));
    const ms = tradeSection(new Set(PLACES.filter((p) => p.p.market === mk).map((p) => p.k)), true); if (ms) card.append(ms);
  }
  const ts = tradeSection(placeSet, false);
  if (ts) { if (mk !== undefined) card.append(el("h3", { text: `${b.name} as a town` })); card.append(ts); }
  return card;
}
function inspect(i, focusBurg = -1) {
  S.sel = i; S.selBurg = focusBurg; insp.hidden = false; dirty.overlay = true;
  const ref = REFS[i] || "", bio = catOf(F["biome"], i), st = catOf(F["state"] || F["t:state"], i);
  const x = el("button", { class: "close", type: "button", "aria-label": "Close", text: "×" }); x.addEventListener("click", closeInspector);
  const burgs = (tileBurgs.get(i) || []).slice().sort((a, b) => (b.b.people || 0) - (a.b.people || 0));
  const lead = focusBurg >= 0 ? BURGS[focusBurg] : burgs[0];
  ihead.replaceChildren(...[x, el("div", { class: "ref", text: ref }), lead ? el("h2", { text: lead.b.name }) : null,
    el("p", { text: [LAND[i] ? bio : (ELEV[i] > 0 ? "Lake" : "Sea"), st].filter(Boolean).join(", ") || "\u00a0" })].filter(Boolean));
  ibody.replaceChildren();
  const ordered = focusBurg >= 0 ? [BURGS[focusBurg], ...burgs.filter((b) => b.k !== focusBurg)] : burgs;
  for (const B of ordered) ibody.append(burgCard(B));
  for (const m of tileMarkers.get(i) || []) ibody.append(el("div", { class: "card" }, el("h4", {}, `${m.m.icon || ""} ${m.m.name || "Marker"}`, el("small", { text: m.m.type })), m.m.note ? el("p", { class: "note", text: m.m.note }) : null));
  for (const u of tileUnits.get(i) || []) ibody.append(el("div", { class: "card" }, el("h4", {}, u.u.name, el("small", { text: u.u.state })), el("p", { text: `${fmtNum(u.u.men, true)} ${u.u.naval ? "ships" : "men"}${u.u.comp ? `: ${u.u.comp}` : ""}` })));
  for (const s of tileStops.get(i) || []) ibody.append(el("div", { class: "card" }, el("h4", {}, s.s.name, el("small", { text: "journey stop" })), el("p", { text: `${s.s.journey}; starts ${s.s.start}, ${fmtNum(s.s.hours)} hours` })));
  for (const g of ["Land", "People", "Realm", "Economy", "Trade", "Places", "Reference", "Other"]) {
    const rows = fieldRows(i, g); if (!rows.length) continue;
    ibody.append(el("h3", { text: g }), kv(rows));
  }
  const goods = FIELDS.filter((f) => f.key.startsWith("g_")).map((f) => ({ f, v: numOf(f, i) })).filter((g) => g.v > 0).sort((a, b) => b.v - a.v);
  if (goods.length) {
    const max = goods[0].v;
    const ul = el("ul", { class: "flows" });
    for (const g of goods.slice(0, 14)) {
      const gi = GOODS.indexOf(g.f.label), col = gi >= 0 ? GOOD_COLOR[gi] : [130, 140, 150];
      ul.append(el("li", {}, el("span", { class: "sw", style: `background:${css(col)}` }), el("span", { class: S.paint === g.f.key ? "painted" : "", text: g.f.label }),
        el("span", { text: `${fmtNum(g.v)} units` }), el("div", { class: "bar" }, el("i", { style: `width:${(100 * g.v) / max}%;background:${css(col)}` }))));
    }
    ibody.append(el("h3", {}, "Rural goods made here", el("small", { text: "mixed" })), ul);
  }
  const zs = META.zones.filter((z) => (catOf(F["zone"], i) || "").split("; ").includes(z.name));
  for (const z of zs) ibody.append(el("div", { class: "card" }, el("h4", {}, z.name, el("small", { text: z.type })), el("p", { text: `${z.cells} cells, ${fmtNum(z.people, true)} people; ${z.states || ""}` })));
  updateReadout(i);
}

// ====================================================================== readout
function updateReadout(i) {
  if (i < 0) { $("#ro-ref").innerHTML = "&nbsp;"; $("#ro-val").textContent = LAND.length ? "Off the map" : ""; return; }
  $("#ro-ref").textContent = REFS[i] || "";
  let val = "";
  if (S.paint === "@landscape") val = `${LAND[i] ? catOf(F["biome"], i) || "Land" : (ELEV[i] > 0 ? "Lake" : "Sea")}, ${fmtNum(ELEV[i] * hRatio)} ${HU}`;
  else { const f = F[S.paint]; val = `${f.label}: ${fmtField(f, f.kind === "cat" ? catOf(f, i) : numOf(f, i))}`; }
  const bs = tileBurgs.get(i); if (bs && bs.length) val = `${bs.map((b) => b.b.name).join(", ")}. ${val}`;
  $("#ro-val").textContent = val;
}

// ====================================================================== pointer, wheel, keys
const ptrs = new Map();
let drag = null, moved = false, hoverQueued = null;
function hit(sx, sy) {
  let best = null, bd = Infinity;
  for (const h of HITS) { const d = Math.hypot(h.x - sx, h.y - sy); if (d < h.r && d < bd) { best = h; bd = d; } }
  return best;
}
glc.addEventListener("contextmenu", (e) => e.preventDefault());
glc.addEventListener("pointerdown", (e) => {
  glc.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  moved = false; stopFly();
  if (ptrs.size === 1) drag = { mode: e.button === 2 || e.altKey || e.ctrlKey ? "turn" : "pan", x: e.clientX, y: e.clientY, cam: { ...S.cam } };
  else if (ptrs.size === 2) {
    const [a, b] = [...ptrs.values()];
    drag = { mode: "pinch", d: Math.hypot(a.x - b.x, a.y - b.y), ang: Math.atan2(b.y - a.y, b.x - a.x), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, cam: { ...S.cam } };
  }
});
glc.addEventListener("pointermove", (e) => {
  if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    if (drag.mode === "pan") {
      const c0 = drag.cam; const a = (c0.yaw * Math.PI) / 180, sp = Math.sin((c0.pitch * Math.PI) / 180);
      const xr = -dx / c0.zoom, yr = dy / c0.zoom / sp;
      S.cam.x = c0.x + Math.cos(a) * xr + Math.sin(a) * yr; S.cam.y = c0.y - Math.sin(a) * xr + Math.cos(a) * yr;
    } else if (drag.mode === "turn") {
      S.cam.yaw = ((drag.cam.yaw - dx * 0.35) % 360 + 360) % 360; S.cam.pitch = Math.max(15, Math.min(90, drag.cam.pitch + dy * 0.25));
      syncDial(); syncTilt();
    } else if (drag.mode === "pinch" && ptrs.size === 2) {
      const [a, b] = [...ptrs.values()]; const d = Math.hypot(a.x - b.x, a.y - b.y), ang = Math.atan2(b.y - a.y, b.x - a.x);
      const c0 = drag.cam; S.cam = { ...c0 }; camVecs();
      const anchor = ground(drag.mx, drag.my);
      S.cam.zoom = clampZoom(c0.zoom * (d / drag.d)); S.cam.yaw = ((c0.yaw - ((ang - drag.ang) * 180) / Math.PI) % 360 + 360) % 360; camVecs();
      const now = ground((a.x + b.x) / 2, (a.y + b.y) / 2); S.cam.x += anchor[0] - now[0]; S.cam.y += anchor[1] - now[1];
      syncDial();
    }
    return;
  }
  if (!hoverQueued) {
    hoverQueued = requestAnimationFrame(() => {
      hoverQueued = null;
      const i = pickTile(e.clientX, e.clientY);
      if (i !== S.hover) { S.hover = i; dirty.fx = true; }
      updateReadout(i);
      glc.style.cursor = hit(e.clientX, e.clientY) ? "pointer" : "default";
    });
  }
});
const endPtr = (e) => {
  const was = drag; ptrs.delete(e.pointerId);
  if (ptrs.size === 0) {
    drag = null;
    if (was && !moved && was.mode !== "pinch" && e.type === "pointerup" && e.button === 0) click(e.clientX, e.clientY);
  } else if (ptrs.size === 1) { const [p] = [...ptrs.values()]; drag = { mode: "pan", x: p.x, y: p.y, cam: { ...S.cam } }; }
};
glc.addEventListener("pointerup", endPtr); glc.addEventListener("pointercancel", endPtr);
glc.addEventListener("pointerleave", () => { if (!drag) { S.hover = -1; dirty.fx = true; } });
function click(sx, sy) {
  const h = hit(sx, sy);
  if (h && h.kind === "burg") { const B = h.o; inspect(B.tile >= 0 ? B.tile : pickTile(sx, sy), B.k); if (S.trade.on && PLACES.some((p) => p.p.burg === B.k)) { S.trade.focus = { burg: B.k, name: B.b.name }; renderFocus(); filterDeals(); } return; }
  if (h && (h.kind === "marker" || h.kind === "unit" || h.kind === "stop")) { if (h.o.tile >= 0) inspect(h.o.tile); return; }
  const i = pickTile(sx, sy);
  if (i >= 0) inspect(i); else closeInspector();
}
const ZMIN = () => 0.15 * Math.min(VW, VH) / (RADIUS * 2), ZMAXZ = () => 160 / SPACING;
const clampZoom = (z) => Math.max(ZMIN(), Math.min(ZMAXZ(), z));
function zoomAt(sx, sy, f) {
  camVecs(); const before = ground(sx, sy); S.cam.zoom = clampZoom(S.cam.zoom * f); camVecs();
  const after = ground(sx, sy); S.cam.x += before[0] - after[0]; S.cam.y += before[1] - after[1];
}
glc.addEventListener("wheel", (e) => { e.preventDefault(); stopFly(); zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0016))); }, { passive: false });
$("#zoom-in").addEventListener("click", () => zoomAt(VW / 2, VH / 2, 1.5));
$("#zoom-out").addEventListener("click", () => zoomAt(VW / 2, VH / 2, 1 / 1.5));
$("#zoom-fit").addEventListener("click", () => { stopFly(); fit(); });
addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea")) { if (e.key === "Escape") e.target.blur(); return; }
  const step = 80 / S.cam.zoom, a = (S.cam.yaw * Math.PI) / 180;
  const mv = (fx_, fy_) => { S.cam.x += (Math.cos(a) * fx_ + Math.sin(a) * fy_) * step; S.cam.y += (-Math.sin(a) * fx_ + Math.cos(a) * fy_) * step; };
  const k = e.key;
  if (k === "ArrowLeft" || k === "a") mv(-1, 0); else if (k === "ArrowRight" || k === "d") mv(1, 0);
  else if (k === "ArrowUp" || k === "w") mv(0, 1); else if (k === "ArrowDown" || k === "s") mv(0, -1);
  else if (k === "+" || k === "=") zoomAt(VW / 2, VH / 2, 1.3); else if (k === "-" || k === "_") zoomAt(VW / 2, VH / 2, 1 / 1.3);
  else if (k === "q" || k === "e") { const d = e.shiftKey ? turnStep() : 15; S.cam.yaw = (((S.cam.yaw + (k === "q" ? -d : d)) % 360) + 360) % 360; syncDial(); }
  else if (k === "[" || k === "]") { S.cam.pitch = Math.max(15, Math.min(90, S.cam.pitch + (k === "[" ? -5 : 5))); syncTilt(); }
  else if (k === "Escape") closeInspector();
  else if (k === "/") { e.preventDefault(); $("#q").focus(); }
  else return;
  e.preventDefault();
});
const turnStep = () => (META.tiles.kind === "hex" ? 60 : 90);
function syncTilt() { const s = $("#s-tilt"); if (s) { s.value = S.cam.pitch; const o = $("output[for='s-tilt']"); if (o) o.textContent = `${Math.round(S.cam.pitch)}°`; } }

// ====================================================================== the dial
const dial = $("#dial");
{
  const NS = "http://www.w3.org/2000/svg", mk = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
  dial.append(mk("circle", { class: "face", r: 63 }));
  const ring = mk("g", { id: "dial-ring" });
  for (let d = 0; d < 360; d += 5) {
    const major = d % 30 === 0, r0 = major ? 49 : 53, a = (d * Math.PI) / 180;
    ring.append(mk("line", { class: major ? "tick major" : "tick", x1: Math.sin(a) * r0, y1: -Math.cos(a) * r0, x2: Math.sin(a) * 58, y2: -Math.cos(a) * 58 }));
  }
  for (const [d, t] of [[0, "N"], [90, "E"], [180, "S"], [270, "W"]]) {
    const a = (d * Math.PI) / 180, tx = mk("text", { x: Math.sin(a) * 40, y: -Math.cos(a) * 40, class: d === 0 ? "north" : "" }); tx.textContent = t; ring.append(tx);
  }
  ring.append(mk("path", { class: "needle", d: "M0 -63 L5 -55 L-5 -55 Z" }));
  dial.append(ring);
  const h = mk("text", { class: "heading", x: 0, y: -3, id: "dial-heading" }); dial.append(h);
  const hs = mk("text", { class: "heading-sub", x: 0, y: 13 }); hs.textContent = "heading"; dial.append(hs);
}
function syncDial() {
  $("#dial-ring").setAttribute("transform", `rotate(${-S.cam.yaw})`);
  $("#dial-heading").textContent = `${Math.round(S.cam.yaw) % 360}°`;
  dial.setAttribute("aria-valuenow", Math.round(S.cam.yaw));
}
{
  let d0 = null;
  const ang = (e) => { const r = dial.getBoundingClientRect(); return (Math.atan2(e.clientX - (r.left + r.width / 2), -(e.clientY - (r.top + r.height / 2))) * 180) / Math.PI; };
  dial.addEventListener("pointerdown", (e) => { dial.setPointerCapture(e.pointerId); d0 = { a: ang(e), yaw: S.cam.yaw, moved: false }; stopFly(); });
  dial.addEventListener("pointermove", (e) => { if (!d0) return; const da = ang(e) - d0.a; if (Math.abs(da) > 1) d0.moved = true; S.cam.yaw = (((d0.yaw - da) % 360) + 360) % 360; syncDial(); });
  dial.addEventListener("pointerup", () => { if (d0 && !d0.moved) { const st = turnStep(); S.cam.yaw = ((Math.round(S.cam.yaw / st) * st + st) % 360); syncDial(); } d0 = null; });
  dial.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") S.cam.yaw = (S.cam.yaw + 345) % 360;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") S.cam.yaw = (S.cam.yaw + 15) % 360;
    else if (e.key === "Home") S.cam.yaw = 0; else return;
    e.preventDefault(); syncDial();
  });
  dial.setAttribute("title", "Drag to turn the view; click to turn one step");
}

// ====================================================================== search and fly
let fly = null;
function stopFly() { fly = null; }
function flyTo(x, y, zoom) {
  const to = { x, y, zoom: clampZoom(zoom ?? Math.max(S.cam.zoom, 14 / SPACING)) };
  if (REDUCED) { Object.assign(S.cam, to); return; }
  fly = { t0: performance.now(), from: { x: S.cam.x, y: S.cam.y, zoom: S.cam.zoom }, to };
}
function stepFly(now) {
  const t = Math.min(1, (now - fly.t0) / 650), e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
  const f = fly.from, g = fly.to;
  S.cam.x = f.x + (g.x - f.x) * e; S.cam.y = f.y + (g.y - f.y) * e; S.cam.zoom = Math.exp(Math.log(f.zoom) + (Math.log(g.zoom) - Math.log(f.zoom)) * e);
  if (t >= 1) fly = null;
}
const SEARCH = [];
BURGS.forEach((B) => SEARCH.push({ name: B.b.name, kind: B.b.group || "burg", go: () => { flyTo(B.x, B.y); if (B.tile >= 0) inspect(B.tile, B.k); } }));
MARKERS.forEach((M) => M.m.name && SEARCH.push({ name: M.m.name, kind: M.m.type || "marker", go: () => { flyTo(M.x, M.y); if (M.tile >= 0) inspect(M.tile); } }));
UNITS.forEach((u) => SEARCH.push({ name: u.u.name, kind: u.u.naval ? "fleet" : "regiment", go: () => { flyTo(u.x, u.y); if (u.tile >= 0) inspect(u.tile); } }));
for (const key of ["state", "province", "culture", "religion", "zone"]) {
  const f = F[key]; if (!f) continue;
  f.dict.forEach((name, k) => SEARCH.push({ name, kind: f.label.toLowerCase(), go: () => {
    const v = values(f); let sx = 0, sy = 0, n = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = 0; i < N; i++) if (v[i] === k + 1) { const x = POS[2 * i], y = POS[2 * i + 1]; sx += x; sy += y; n++; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    if (!n) return;
    const span = Math.max(x1 - x0, y1 - y0, SPACING * 6);
    flyTo(sx / n, sy / n, (Math.min(VW, VH) * 0.6) / span);
    if (S.paint !== key && f.paint) { S.paint = key; paintSel.value = key; paint(); }
    S.isolate = { key, codes: new Set([k + 1]) }; applyMask(); renderLegend();
  } }));
}
const REF_INDEX = new Map(REFS.map((r, i) => [r.replace(/\s+/g, ""), i]));
const qi = $("#q"), res = $("#results");
let hits = [], cursor = 0;
function runSearch() {
  const s = qi.value.trim(); res.replaceChildren(); hits = [];
  if (!s) { res.hidden = true; qi.setAttribute("aria-expanded", "false"); return; }
  const compact = s.toUpperCase().replace(/\s+/g, "");
  let ri = REF_INDEX.get(compact);
  if (ri === undefined && /^[A-Z]{2}\d+$/.test(compact) && (compact.length - 2) % 2 === 0) {
    const h = (compact.length - 2) / 2, e = compact.slice(2, 2 + h), n = compact.slice(2 + h);
    const dg = (REFS[0] || "").split(" ")[1]?.length || 2;
    if (h === dg + 1) ri = REF_INDEX.get(compact.slice(0, 2) + e.slice(0, dg) + n.slice(0, dg));
  }
  if (ri !== undefined) hits.push({ name: REFS[ri], kind: "grid reference", go: () => { flyTo(POS[2 * ri], POS[2 * ri + 1]); inspect(ri); } });
  const low = s.toLowerCase();
  const scored = SEARCH.map((x) => { const n = (x.name || "").toLowerCase(); const p = n.indexOf(low); return p < 0 ? null : [p === 0 ? 0 : 1, n.length, x]; }).filter(Boolean);
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  hits.push(...scored.slice(0, 9).map((x) => x[2]));
  hits = hits.slice(0, 10); cursor = 0;
  hits.forEach((h, k) => { const li = el("li", { role: "option", "aria-selected": String(k === 0) }, el("span", { text: h.name }), el("small", { text: h.kind })); li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(k); }); res.append(li); });
  if (!hits.length) res.append(el("li", { "aria-disabled": "true" }, el("span", { style: "color:var(--ink-3)", text: "Nothing by that name. Try a town, a state or a reference such as " + (REFS[Math.floor(N / 2)] || "AA 00 00") })));
  res.hidden = false; qi.setAttribute("aria-expanded", "true");
}
function choose(k) { const h = hits[k]; if (!h) return; h.go(); res.hidden = true; qi.blur(); }
qi.addEventListener("input", runSearch);
qi.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); cursor = (cursor + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % Math.max(1, hits.length); [...res.children].forEach((li, k) => li.setAttribute("aria-selected", String(k === cursor))); }
  else if (e.key === "Enter") { e.preventDefault(); choose(cursor); }
  else if (e.key === "Escape") { res.hidden = true; }
});
qi.addEventListener("blur", () => setTimeout(() => { res.hidden = true; }, 120));
$("#rail-toggle").addEventListener("click", () => { const r = $("#rail"); const c = r.classList.toggle("collapsed"); $("#rail-toggle").setAttribute("aria-expanded", String(!c)); });
if (innerWidth > 760) $("#rail").classList.remove("collapsed");

// ====================================================================== start
addEventListener("resize", () => { resize(); });
try { await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 1500))]); } catch (e) { /* fonts are optional */ }
resize(); camVecs(); paint(); fit(); syncDial(); filterDeals();
$("#loading").remove();
requestAnimationFrame(frame);
window.__iso = { S, META, F, inspect, flyTo, paint, focusTrade, filterDeals, pickTile, project, dirty };
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
