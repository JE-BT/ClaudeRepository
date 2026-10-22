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

TOOL_VERSION = "1.1"
LAYERS = ["tiles", "centres", "blocks", "squares", "land", "zones", "borders", "rivers", "routes", "journeys", "stops",
          "burgs", "markers", "units", "markets", "deals", "traffic"]
LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
UNIT_ABBR = {"kilometre": "km", "mile": "mi", "league": "lg", "verst": "vr", "nautical mile": "nmi", "nautical league": "nlg"}
KM_PER_UNIT = {"km": 1.0, "mi": 1.609344, "lg": 4.828032, "vr": 1.0668, "nmi": 1.852, "nlg": 5.556}
ROUTE_COST = {"roads": 1.0, "trails": 1.3, "searoutes": 0.5}   # as azgaar_tiles' SURFACE_RULES["route_cost"]
OFF_ROUTE_COST = 2.0                                            # as SURFACE_RULES["off_route_cost"]
NAN = float("nan")
U16_NULL = 65535


# ====================================================================== icons and pixel art
_GLYPH = re.compile(r"(?:glyph|emoji)[-_]((?:[0-9a-f]{2,6})(?:[-_][0-9a-f]{2,6})*)", re.I)


def icon_text(icon):
    """A marker's or regiment's icon as text. Azgaar 1.154 and newer store the emoji as its code points
    ('glyph-1f333', 'glyph-1f3f4-200d-2620-fe0f'); older maps, and azgaar_tiles 1.1 exports, the emoji itself."""
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


# Pixel-art sprites for the page: rows of palette letters, '.' clear. The page adds a one-pixel outline
# in a darker shade of whatever each sprite borders. LEAF and GRASS recolour the leaf (L l m) and grass
# (h H) letters; g and G are recoloured to the state's colour on flags.
BASE = {
    "w": "#9a6a3e", "W": "#5e3c22",                      # trunk
    "c": "#8fd06a", "C": "#55a042", "e": "#2f6e30",      # cactus
    "r": "#c4bfb3", "R": "#918b80", "q": "#605b55",      # rock
    "s": "#f6fafc", "S": "#c6d8e6",                      # snow
    "y": "#f3dd96", "Y": "#d9b764", "z": "#b38f4a",      # sand, wheat
    "h": "#a9db5c", "H": "#64a83c",                      # grass
    "f": "#e8525a", "F": "#f4d04a", "v": "#fbfbf2",      # flowers
    "u": "#a8dcf6", "U": "#5a9fd8",                      # water
    "i": "#eef9fd", "I": "#a6d2ea",                      # ice
    "o": "#d8684a", "O": "#9c3f2c",                      # red roof
    "p": "#7d8bab", "P": "#525d7c",                      # slate roof
    "a": "#e2bb5e", "A": "#a8823a",                      # thatch
    "x": "#f1e5c9", "X": "#c8b48e",                      # plaster
    "t": "#cfcbc2", "T": "#97928a",                      # stone
    "n": "#3c2b22", "j": "#ffd86a",                      # door, lit window
    "g": "#d23c3c", "G": "#8e2424",                      # flag (recoloured by state)
    "d": "#b07b4c", "D": "#74502f",                      # wood
    "b": "#f7f2e4", "B": "#d4cbb5",                      # cloth, sail
    "M": "#52525c",                                      # pole
    "L": "#8fd14f", "l": "#57a83a", "m": "#2f7330",      # leaves (recoloured by variant)
}
LEAF = {
    "temperate": ("#8fd14f", "#57a83a", "#2f7330"),
    "tropical": ("#aadf3e", "#66b42c", "#2f7d26"),
    "jungle": ("#7fd046", "#3e9a35", "#1e6430"),
    "conifer": ("#63a56c", "#3a7a4f", "#22543a"),
    "taiga": ("#729f80", "#46735c", "#29493f"),
    "savanna": ("#bcc75c", "#8c9c38", "#5c6b24"),
    "dry": ("#b9a76c", "#8e7e4d", "#5f5235"),
    "wet": ("#82b96c", "#4f8a50", "#2c5e3a"),
    "palm": ("#9ed84a", "#5aa337", "#2e7a2c"),
    "autumn": ("#f0b04a", "#d0702e", "#8f3f24"),
}
GRASS = {
    "temperate": ("#a9db5c", "#64a83c"),
    "savanna": ("#dad36c", "#aca23f"),
    "tundra": ("#c2c194", "#8e8d64"),
    "wet": ("#93cc7c", "#4f8f55"),
    "dry": ("#d6c98a", "#a6965a"),
}

SPRITES = {
    # ------------------------------------------------------------------ trees
    "oak": [
        "...lll...",
        "..lLLLl..",
        ".lLLLLll.",
        "lLLLllllm",
        "lLLllllmm",
        "lllllllmm",
        ".llllmmm.",
        "..mmmmm..",
        "....wW...",
        "....wW...",
        "...wwWW..",
    ],
    "oak_small": [
        "..lll..",
        ".lLLll.",
        "lLLlllm",
        "llllmmm",
        ".lmmmm.",
        "...wW..",
        "...wW..",
    ],
    "pine": [
        "...L...",
        "..LLl..",
        "..Llm..",
        ".LLllm.",
        "..Llm..",
        ".LLllm.",
        "LLlllmm",
        ".Llllm.",
        "LLlllmm",
        "Lllllmm",
        "...W...",
        "...W...",
    ],
    "pine_snow": [
        "...s...",
        "..ssl..",
        "..Llm..",
        ".sslmm.",
        "..Llm..",
        ".ssllm.",
        "LLlllmm",
        ".sslllm",
        "Lllllmm",
        "...W...",
        "...W...",
    ],
    "fir": [
        "...L...",
        "..LLl..",
        "..Llm..",
        ".LLlm..",
        "..Llmm.",
        ".LLllm.",
        "..Llmm.",
        ".LLlllm",
        "LLllmm.",
        ".Llllmm",
        "LLlllmm",
        "Llllmmm",
        "...W...",
        "...W...",
    ],
    "palm": [
        "...LLlll...",
        ".LLlLLlllm.",
        "LL.lLlLlmmm",
        "L..l.w.m..m",
        ".....w.....",
        ".....w.....",
        "....w......",
        "....w......",
        "....W......",
        "....W......",
        "...wW......",
    ],
    "jungle": [
        "...lLLl.ll.",
        ".llLLLllLll",
        "lLLLLlllllm",
        "lLLllllllmm",
        "lllllmmlmmm",
        ".lllmmmmmm.",
        "..mm.wWmm..",
        ".....wW....",
        ".....wW....",
        "....wwWW...",
    ],
    "acacia": [
        "..lLLLLlll...",
        ".lLLLlllllmm.",
        "lLLlllllmmmmm",
        "..mmmwmmWm...",
        ".....w.W.....",
        "......wW.....",
        "......wW.....",
        ".....wwWW....",
    ],
    "bush": [
        "..ll..",
        ".lLllm",
        "lLlllm",
        ".lmmm.",
    ],
    "dead_tree": [
        "w...w..",
        ".w.w..W",
        "..ww.W.",
        "...wW..",
        "...wW..",
        "..wwWW.",
    ],
    # ------------------------------------------------------------------ ground cover
    "grass": [
        "h.h.h",
        "hHhHh",
        ".HHH.",
    ],
    "flowers": [
        "f.F.v",
        "hHhHh",
        ".HHH.",
    ],
    "reeds": [
        "W...W",
        "W.W.W",
        "h.W.h",
        "h.h.h",
        "hHhHh",
        ".HHH.",
    ],
    "puddle": [
        "..uuU..",
        ".uUUUU.",
    ],
    "dry_shrub": [
        "..h..",
        "h.H.h",
        ".hHH.",
    ],
    # ------------------------------------------------------------------ desert
    "cactus": [
        "...C...",
        "..cCe..",
        "c.cCe..",
        "c.cCe.e",
        "ccCCe.e",
        ".ecCeee",
        "..cCe..",
        "..cCe..",
        "..cCe..",
    ],
    "cactus_small": [
        ".cfe.",
        "cCCee",
        "cCCee",
        ".eee.",
    ],
    "dune": [
        ".....yyY....",
        "...yyyYYzz..",
        ".yyyYYYzzzz.",
        "yyYYYzzzzzzz",
    ],
    # ------------------------------------------------------------------ rocks, snow and ice
    "rock": [
        ".rrR..",
        "rrRRq.",
        "rRRqqq",
        ".qqqq.",
    ],
    "rock_snow": [
        ".ssS..",
        "ssSSR.",
        "rRRqqq",
        ".qqqq.",
    ],
    "ice": [
        "..ii....",
        ".iiIi...",
        ".iIIIi.i",
        "iiIIIIiI",
        "iIIIIIII",
    ],
    "peak": [
        "........r........",
        ".......rrR.......",
        "......rrRRq......",
        ".....rrrRRqq.....",
        "....rrrRRRqqq....",
        "...rrRrRRqqqqq...",
        "..rrRRRRRRqqqqq..",
        ".rrRRRRRqqqqqqqq.",
        "rrRRRRRRqqqqqqqqq",
    ],
    "peak_snow": [
        "........s........",
        ".......ssS.......",
        "......ssSSS......",
        ".....sssSSqq.....",
        "....rsrRSRqqq....",
        "...rrRrRRqqqqq...",
        "..rrRRRRRRqqqqq..",
        ".rrRRRRRqqqqqqqq.",
        "rrRRRRRRqqqqqqqqq",
    ],
    "peak_small": [
        ".....r.....",
        "....rrR....",
        "...rrRRq...",
        "..rrRRRqq..",
        ".rrRRRqqqq.",
        "rrRRRqqqqqq",
    ],
    "hill": [
        "...lLLl....",
        ".lLLllllm..",
        "lLlllllmmmm",
    ],
    # ------------------------------------------------------------------ water
    "wave": [
        ".vv..",
        "v..vv",
    ],
    "iceberg": [
        "...ii...",
        "..iiIi..",
        ".iiIIIi.",
        "uUUUUUUu",
    ],
    # ------------------------------------------------------------------ farms
    "haystack": [
        ".yY..",
        "yyYz.",
        "yYYzz",
    ],
    # ------------------------------------------------------------------ buildings (for town icons)
    "hut": [
        "...a...",
        "..aaA..",
        ".aaaAA.",
        "aaaaAAA",
        ".xxnxX.",
        ".xxnxX.",
    ],
    "tent": [
        "...b...",
        "..bbB..",
        ".bbbBB.",
        "bbbnBBB",
        "bbbnBBB",
    ],
    "house": [
        "...oo...",
        "..oooO..",
        ".ooooOO.",
        "ooooooOO",
        ".xjxxXX.",
        ".xnxjXX.",
        ".xnxxXX.",
    ],
    "house_slate": [
        "...pp...",
        "..pppP..",
        ".ppppPP.",
        "ppppppPP",
        ".xjxxXX.",
        ".xxxnXX.",
        ".xjxnXX.",
    ],
    "house_long": [
        "..oooooooO..",
        ".ooooooooOO.",
        "ooooooooooOO",
        ".xjxxjxxnxX.",
        ".xxxxxxxnxX.",
    ],
    "shack": [
        ".dDd..",
        "dddDD.",
        ".xnX..",
        ".xnX..",
    ],
    "church": [
        "....n....",
        "...pPP...",
        "...pPP...",
        "...tjT...",
        "...ttT...",
        "..oooOO..",
        ".ooooOOO.",
        "oooooOOOO",
        ".ttjttjT.",
        ".tttnntT.",
        ".tttnntT.",
    ],
    "temple": [
        "....F....",
        "..FFFFF..",
        ".FFFFFFz.",
        "xxxxxxxxX",
        ".x.x.x.X.",
        ".x.x.x.X.",
        ".x.x.x.X.",
        "ttttttttT",
    ],
    "tower": [
        "t.t.T",
        "tttTT",
        ".tjT.",
        ".tTT.",
        ".tjT.",
        ".tTT.",
        ".tTT.",
        ".tnT.",
    ],
    "wall": [
        "t.t.t.t.t.t.t.t.t.t.t",
        "tttttttttttttttttttTT",
        "tTtTtTtTtTtTtTtTtTtTT",
    ],
    "castle": [
        "........Mgg......",
        "........Mggg.....",
        "........M........",
        ".......t.t.T.....",
        "t.t.T..tttTT.t.tT",
        "tttTT..tjjTT.tttT",
        "tjtTT.ttttTTTtjTT",
        "tttTTttttttTTtttT",
        "tttTTtttnnttTtttT",
        "tttTTtttnnttTtttT",
    ],
    "boat": [
        "...M.....",
        "...bb....",
        "...bbB...",
        "...bbbB..",
        "dDdDdDdDd",
        ".dDDDDDD.",
    ],
    "crates": [
        "dDdD.",
        "dDdDd",
        "DDDDD",
    ],
    # ------------------------------------------------------------------ regiments and fleets
    "banner": [
        "Mggg...",
        "MgGgg..",
        "Mggg...",
        "M..tt..",
        "M.tttT.",
        "M.xxX..",
        "MggggG.",
        "M.gggG.",
        "M.d.D..",
        "M.d.D..",
    ],
    "ship": [
        "....M....",
        "...gggG..",
        "...gggG..",
        "...bbbB..",
        "dDdDdDdDd",
        ".dDDDDDD.",
    ],
}

# which leaf/grass variants each sprite can take (the first is the default)
VARIANTS = {
    "oak": list(LEAF), "oak_small": list(LEAF), "pine": ["conifer", "taiga", "temperate"], "pine_snow": ["taiga", "conifer"],
    "fir": ["conifer", "jungle"], "palm": ["palm"], "jungle": ["jungle", "tropical"], "acacia": ["savanna"],
    "bush": list(LEAF), "hill": ["temperate", "savanna", "dry", "taiga", "tropical", "wet"],
    "grass": list(GRASS), "flowers": list(GRASS), "reeds": ["wet"], "dry_shrub": ["dry", "tundra"],
}


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
    markers = [{"id": p.get("marker"), "name": p.get("name"), "type": p.get("type"), "icon": icon_text(p.get("icon")), "ref": p.get("ref"),
                "pref": p.get("point_ref"), "note": p.get("note"), "xy": B.flat([B.P(g["coordinates"])])}
               for g, p in feats("markers") if g]
    units_ = [{"name": p.get("name"), "state": p.get("state"), "men": p.get("men"), "naval": bool(p.get("naval")), "icon": icon_text(p.get("icon")),
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
    sprites = json.dumps({"base": BASE, "leaf": LEAF, "grass": GRASS, "sprites": SPRITES}, separators=(",", ":"))
    html = PAGE.replace("<!--PAYLOAD-->", payload).replace("/*SPRITES*/null", sprites)
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
          f"{sum(1 for f in meta['fields'] if f['paint'])} paint layers, {len(meta['burgs'])} burgs, {len(meta['deals']):,} deals; "
          f"pixel-art style with {len(SPRITES)} sprites")
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
#ov, #fx, #ovl { pointer-events: none; }
#ovl { inset: auto; left: 0; top: 0; image-rendering: crisp-edges; image-rendering: pixelated; }
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
<canvas id="ovl" class="layer" aria-hidden="true"></canvas>
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
      <div id="style-slot"></div>
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
const SPRITE_DEFS = /*SPRITES*/null;
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
  if (f.ramp === "biome") { const b = S.style === "pixel" ? BIOME_PX[name] : BIOME[name]; if (b) return hex(b); }
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
  exag: EXAG0, steps: 0, shade: true, outlines: true, style: "pixel", px: 2, detail: 1,
  cam: { x: 0, y: 0, zoom: 1, yaw: 0, pitch: 38 },
  show: { burgs: true, labels: true, markets: true, markers: true, units: false, rivers: true, routes: true, coast: true,
          borders: true, states: true, zones: false, journeys: true, squares: false, blocks: false, decor: true },
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
// Positions are worked out in CSS pixels from the middle of the screen and mapped to the target by uNdcS
// and uNdcO, so the same shader draws to the screen, the picking image and the low-resolution art-pixel target.
const VS = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
layout(location=0) in vec2 aOff; layout(location=1) in vec3 aInfo; layout(location=2) in vec2 aPos;
uniform sampler2D uTop, uCol, uMask, uInfo; uniform int uTW, uPixel;
uniform vec2 uTarget, uRot, uPitch, uNdcS, uNdcO; uniform float uZoom, uDepth, uBase, uShadeTop, uDim; uniform vec3 uLight;
out vec3 vCol; out float vEdge; out vec2 vWorld; flat out int vId; flat out float vTop; flat out float vWater; flat out float vPat; flat out float vDim; flat out float vSh;
void main(){
  int id = gl_InstanceID; ivec2 tc = ivec2(id % uTW, id / uTW);
  float top = texelFetch(uTop, tc, 0).r; vec4 c = texelFetch(uCol, tc, 0); vec2 mk = texelFetch(uMask, tc, 0).rg;
  float kind = aInfo.x; float z = kind < 2.5 ? top : uBase;
  vec2 w = aPos + aOff; vec2 p = w - uTarget;
  float xr = uRot.x * p.x - uRot.y * p.y, yr = uRot.y * p.x + uRot.x * p.y;
  vec2 s = vec2(xr, yr * uPitch.x + z * uPitch.y) * uZoom;
  gl_Position = vec4(s * uNdcS + uNdcO, (yr * uPitch.y - z * uPitch.x) / uDepth, 1.0);
  float k;
  if (kind < 1.5) { k = mix(1.0, c.a * 2.0, uShadeTop); if (uPixel == 1) k = floor(k * 9.0 + 0.5) / 9.0; vTop = 1.0; }
  else { float diff = max(dot(vec3(aInfo.yz, 0.0), uLight), 0.0); k = 0.5 + 0.44 * diff; if (uPixel == 1) k = floor(k * 5.0 + 0.5) / 5.0; if (kind > 2.5) k *= 0.62; vTop = 0.0; }
  vCol = c.rgb * k; vSh = k;
  vDim = max(uDim, (1.0 - mk.r) * 0.82);
  vEdge = kind < 0.5 ? 1.0 : 0.0; vId = id; vWater = mk.g; vWorld = w;
  vPat = texelFetch(uInfo, tc, 0).r * 255.0;
}`;
// Ground patterns for the pixel-art style, on a grid fixed to the map (so they do not swim when the view
// moves): 1 grass, 2 forest floor, 3 sand, 4 snow, 5 tundra and cold desert, 6 wetland, 7 water, 8 rock, 9 fields.
const FS = `#version 300 es
precision highp float; precision highp int;
in vec3 vCol; in float vEdge; in vec2 vWorld; flat in int vId; flat in float vTop; flat in float vWater; flat in float vPat; flat in float vDim; flat in float vSh;
uniform int uPick, uPixel; uniform float uOutline, uPatK, uFieldT; uniform vec3 uDimTo; out vec4 o;
float hsh(ivec2 q) { uint h = uint(q.x) * 1597334677u ^ uint(q.y) * 3812015801u; h ^= h >> 16; h *= 2246822519u; h ^= h >> 13; h *= 3266489917u; h ^= h >> 16; return float(h & 65535u) / 65535.0; }
vec3 pattern(vec3 c) {
  int p = int(vPat + 0.5);
  vec2 g = vWorld * uPatK; ivec2 q = ivec2(floor(g)); float n = hsh(q);
  if (p == 1) { if (n > 0.93) return c * 1.14; if (n < 0.06) return c * 0.86; return c; }
  if (p == 2) { if (n < 0.24) return c * 0.83; if (n > 0.96) return c * 1.12; return c; }
  if (p == 3) { float r = hsh(ivec2(q.x >> 2, q.y)); int row = q.y & 3; if (row == 0 && r > 0.45) return c * 1.08; if (row == 1 && r > 0.45) return c * 0.92; if (n < 0.03) return c * 0.84; return c; }
  if (p == 4) { if (n < 0.06) return c * vec3(0.86, 0.9, 0.97); if (n > 0.97) return min(c * 1.06, vec3(1.0)); return c; }
  if (p == 5) { if (n < 0.13) return c * 0.84; if (n > 0.93) return c * 1.1; return c; }
  if (p == 6) { if (hsh(q >> 1) > 0.86) return mix(c, vec3(0.36, 0.56, 0.74) * vSh, 0.7); if (n < 0.12) return c * 0.82; return c; }
  if (p == 7) { if (hsh(ivec2(q.x >> 1, q.y)) > 0.972) return min(c * 1.32 + 0.05, vec3(1.0)); if (n < 0.05) return c * 0.92; return c; }
  if (p == 8) { if (n < 0.16) return c * 0.84; if (n > 0.93) return c * 1.12; return c; }
  if (p == 9) {
    ivec2 f = ivec2(floor(g / uFieldT)); float a = hsh(f + ivec2(7, 131)), b = hsh(f + ivec2(91, 17));
    vec3 crop = a < 0.34 ? vec3(0.86, 0.76, 0.4) : (a < 0.72 ? vec3(0.52, 0.71, 0.31) : vec3(0.62, 0.48, 0.31));
    vec3 col = crop * vSh;
    if ((((b > 0.5) ? q.x : q.y) & 1) == 0) col *= 0.88;
    vec2 lf = g - vec2(f) * uFieldT;
    if ((lf.x < 1.0 && b > 0.3) || (lf.y < 1.0 && a > 0.25)) col = vec3(0.27, 0.43, 0.22) * vSh;
    return mix(c, col, 0.85);
  }
  return c;
}
void main(){
  if (uPick == 1) { int k = vId + 1; o = vec4(float(k & 255) / 255.0, float((k >> 8) & 255) / 255.0, float((k >> 16) & 255) / 255.0, 1.0); return; }
  vec3 c = vCol;
  if (uPixel == 1 && vTop > 0.5 && uPatK > 0.0 && vPat > 0.5) c = pattern(c);
  if (vTop > 0.5 && uOutline > 0.0) {
    float w = fwidth(vEdge); float e = 1.0 - smoothstep(0.0, w * 1.15, vEdge);
    if (uPixel == 1) e = step(0.5, e);
    c = mix(c, c * 0.66, e * uOutline * (1.0 - 0.7 * vWater));
  }
  float gr = dot(c, vec3(0.299, 0.587, 0.114));
  o = vec4(mix(c, mix(vec3(gr), uDimTo, 0.78), vDim), 1.0);
}`;
function shader(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}
function program(vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, shader(gl.VERTEX_SHADER, vs)); gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  return p;
}
const uniformsOf = (p, names) => Object.fromEntries(names.map((n) => [n, gl.getUniformLocation(p, n)]));
let prog;
try { prog = program(VS, FS); } catch (e) { fail("The tile shader did not compile: " + e.message); return; }
const U = uniformsOf(prog, ["uTop", "uCol", "uMask", "uInfo", "uTW", "uPixel", "uTarget", "uRot", "uPitch", "uNdcS", "uNdcO", "uZoom", "uDepth", "uBase",
  "uShadeTop", "uDim", "uLight", "uDimTo", "uPick", "uOutline", "uPatK", "uFieldT"]);

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
function makeTex(unit, ifmt, fmt, type, data, w = TW, h = TH) {
  const t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, ifmt, w, h, 0, fmt, type, data);
  return t;
}
gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
const topData = new Float32Array(TW * TH), colData = new Uint8Array(TW * TH * 4), maskData = new Uint8Array(TW * TH * 2), infoData = new Uint8Array(TW * TH);
const texTop = makeTex(0, gl.R32F, gl.RED, gl.FLOAT, topData);
const texCol = makeTex(1, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, colData);
const texMask = makeTex(2, gl.RG8, gl.RG, gl.UNSIGNED_BYTE, maskData);
const texInfo = makeTex(4, gl.R8, gl.RED, gl.UNSIGNED_BYTE, infoData);
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

// the pixel-art style draws the tiles and their details into a target 1/P of the screen's size, then
// scales it up with every art pixel P device pixels square
let lowFB = null, lowTex = null, lowDepth = null, lowW = 0, lowH = 0;
function ensureLow() {
  if (lowFB && lowW === RT.w && lowH === RT.h) return;
  if (lowFB) { gl.deleteFramebuffer(lowFB); gl.deleteTexture(lowTex); gl.deleteRenderbuffer(lowDepth); }
  lowW = RT.w; lowH = RT.h;
  lowTex = gl.createTexture(); gl.activeTexture(gl.TEXTURE6); gl.bindTexture(gl.TEXTURE_2D, lowTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, lowW, lowH, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  lowDepth = gl.createRenderbuffer(); gl.bindRenderbuffer(gl.RENDERBUFFER, lowDepth); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, lowW, lowH);
  lowFB = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, lowFB);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, lowTex, 0);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, lowDepth);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}
const BVS = `#version 300 es
void main(){ gl_Position = vec4(float((gl_VertexID & 1) * 4 - 1), float((gl_VertexID >> 1) * 4 - 1), 0.0, 1.0); }`;
const BFS = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
uniform sampler2D uTex; uniform vec2 uOff; uniform float uP; out vec4 o;
void main(){ o = texelFetch(uTex, ivec2(floor((gl_FragCoord.xy + uOff) / uP)), 0); }`;
let blitProg;
try { blitProg = program(BVS, BFS); } catch (e) { fail("The pixel shader did not compile: " + e.message); return; }
const UB = uniformsOf(blitProg, ["uTex", "uOff", "uP"]);
const blitVao = gl.createVertexArray();

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
  sizeLines();
  dirty.terrain = dirty.overlay = true; pickDirty = true;
}
const ovl = $("#ovl"), ov = $("#ov"), fx = $("#fx"), lctx = ovl.getContext("2d"), octx = ov.getContext("2d"), fctx = fx.getContext("2d");
const dirty = { terrain: true, overlay: true, fx: true };
const groundColor = () => hex(getComputedStyle(document.documentElement).getPropertyValue("--ground").trim() || "#d9dfe5");
let GROUND = groundColor();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { GROUND = groundColor(); dirty.terrain = dirty.overlay = true; });

// The art-pixel grid. In the pixel-art style one art pixel is P device pixels (P from the pixel size and the
// screen's density); the tiles, their details and the line layers are drawn at that resolution and scaled up
// without smoothing. The grid is centred on the screen, so a part of a pixel may be cut at each edge.
const RT = { pdev: 1, w: 1, h: 1, offX: 0, offY: 0, top: 0 };
function rtDims() {
  const W = glc.width, H = glc.height, a = S.style === "pixel" ? Math.max(1, Math.round(S.px * DPR)) : 1;
  RT.pdev = a; RT.w = Math.ceil(W / a); RT.h = Math.ceil(H / a);
  RT.offX = Math.floor((RT.w * a - W) / 2); RT.offY = Math.floor((RT.h * a - H) / 2); RT.top = RT.h * a - H - RT.offY;
}
const ART = () => (S.style === "pixel" ? RT.pdev / DPR : 1);   // CSS pixels per art pixel
function sizeLines() {
  rtDims();
  ovl.width = RT.w; ovl.height = RT.h;
  Object.assign(ovl.style, { left: `${-RT.offX / DPR}px`, top: `${-RT.top / DPR}px`, width: `${(RT.w * RT.pdev) / DPR}px`, height: `${(RT.h * RT.pdev) / DPR}px` });
  lctx.setTransform(DPR / RT.pdev, 0, 0, DPR / RT.pdev, RT.offX / RT.pdev, RT.top / RT.pdev);
}
// where CSS pixels from the middle of the screen land in a target, and how many target pixels make an art pixel
function mapScreen() { return { sx: 2 / VW, sy: 2 / VH, ox: 0, oy: 0, tw: glc.width, th: glc.height, pxCss: 1 / DPR, art: Math.max(1, Math.round(DPR)) }; }
function mapLow() {
  const W = glc.width, H = glc.height, a = RT.pdev;
  return { sx: (2 * DPR) / (a * RT.w), sy: (2 * DPR) / (a * RT.h), ox: (W + 2 * RT.offX) / (a * RT.w) - 1, oy: (H + 2 * RT.offY) / (a * RT.h) - 1,
           tw: RT.w, th: RT.h, pxCss: a / DPR, art: 1 };
}

function lightVec() {
  // light from the upper left of the screen, whatever the heading
  const hx = cv.s, hy = cv.c, lx = -cv.c, ly = cv.s;      // screen up and screen left, in map axes
  let x = hx + lx, y = hy + ly; const L = Math.hypot(x, y); x /= L; y /= L;
  return [x, y];
}
const depthRange = () => (RADIUS + Math.hypot(S.cam.x, S.cam.y) + ZMAX + Math.abs(BASE)) * 1.05;
function drawTiles(M, pick) {
  gl.useProgram(prog);
  gl.bindVertexArray(vao);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texTop);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texCol);
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, texMask);
  gl.activeTexture(gl.TEXTURE4); gl.bindTexture(gl.TEXTURE_2D, texInfo);
  gl.uniform1i(U.uTop, 0); gl.uniform1i(U.uCol, 1); gl.uniform1i(U.uMask, 2); gl.uniform1i(U.uInfo, 4); gl.uniform1i(U.uTW, TW);
  gl.uniform2f(U.uTarget, S.cam.x, S.cam.y); gl.uniform2f(U.uRot, cv.c, cv.s); gl.uniform2f(U.uPitch, cv.sp, cv.cp);
  gl.uniform2f(U.uNdcS, M.sx, M.sy); gl.uniform2f(U.uNdcO, M.ox, M.oy); gl.uniform1f(U.uZoom, S.cam.zoom);
  gl.uniform1f(U.uDepth, depthRange());
  gl.uniform1f(U.uBase, BASE); gl.uniform1f(U.uShadeTop, S.shade ? 1 : 0);
  const [lx, ly] = lightVec(); gl.uniform3f(U.uLight, lx, ly, 0);
  gl.uniform1f(U.uDim, S.trade.on ? S.trade.dim : 0);
  gl.uniform3f(U.uDimTo, GROUND[0] / 255, GROUND[1] / 255, GROUND[2] / 255);
  gl.uniform1i(U.uPick, pick ? 1 : 0);
  const px = !pick && S.style === "pixel";
  gl.uniform1i(U.uPixel, px ? 1 : 0);
  const tileA = (SPACING * S.cam.zoom) / (px ? ART() : 1);           // a tile's width in art pixels (CSS pixels when smooth)
  gl.uniform1f(U.uOutline, S.outlines ? Math.max(0, Math.min(1, (tileA - 7) / 10)) : 0);
  if (px && tileA >= 6) {
    const K = 2 ** Math.min(6, Math.max(2, Math.floor(Math.log2(tileA))));   // pattern texels across a tile, never finer than an art pixel
    gl.uniform1f(U.uPatK, K / SPACING); gl.uniform1f(U.uFieldT, Math.max(2, Math.round(K / 6)));
  } else { gl.uniform1f(U.uPatK, 0); gl.uniform1f(U.uFieldT, 2); }
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
  gl.drawElementsInstanced(gl.TRIANGLES, ti.length, gl.UNSIGNED_SHORT, 0, N);
  gl.bindVertexArray(null);
}
function drawTerrain(pick = false) {
  if (pick) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, pickFB); gl.viewport(0, 0, pickW, pickH); gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    drawTiles(mapScreen(), true);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return;
  }
  // tiles smaller than a few art pixels only alias in the low-resolution target, so they are drawn smooth
  const px = S.style === "pixel" && (SPACING * S.cam.zoom) / ART() >= 2.5;
  let M;
  if (px) { rtDims(); ensureLow(); gl.bindFramebuffer(gl.FRAMEBUFFER, lowFB); gl.viewport(0, 0, RT.w, RT.h); M = mapLow(); }
  else { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, glc.width, glc.height); M = mapScreen(); }
  gl.clearColor(GROUND[0] / 255, GROUND[1] / 255, GROUND[2] / 255, 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  drawTiles(M, false);
  drawSprites(M);
  if (px) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, glc.width, glc.height);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
    gl.useProgram(blitProg); gl.bindVertexArray(blitVao);
    gl.activeTexture(gl.TEXTURE6); gl.bindTexture(gl.TEXTURE_2D, lowTex);
    gl.uniform1i(UB.uTex, 6); gl.uniform2f(UB.uOff, RT.offX, RT.offY); gl.uniform1f(UB.uP, RT.pdev);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
  }
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
// the pixel-art landscape: a game palette for the biomes, the land banded by height and the sea by depth
const BIOME_PX = { "Marine": "#2f63a8", "Hot desert": "#ecd38a", "Cold desert": "#c6bc92", "Savanna": "#cfc165", "Grassland": "#96c95a",
  "Tropical seasonal forest": "#7db84a", "Temperate deciduous forest": "#58a243", "Tropical rainforest": "#3f9437",
  "Temperate rainforest": "#3d8248", "Taiga": "#4c7550", "Tundra": "#a6a382", "Glacier": "#e9f2f5", "Wetland": "#5a9061" };
const BIOME_PAT = { "Hot desert": 3, "Cold desert": 5, "Savanna": 1, "Grassland": 1, "Tropical seasonal forest": 2, "Temperate deciduous forest": 2,
  "Tropical rainforest": 2, "Temperate rainforest": 2, "Taiga": 2, "Tundra": 5, "Glacier": 4, "Wetland": 6 };
const SNOWLINE = 2600, ROCKLINE = 1200;
const snowy = (i) => ELEV[i] >= SNOWLINE || (ELEV[i] >= ROCKLINE && tempC(i) < -6);
function landscapePx(i) {
  const e = ELEV[i];
  if (!LAND[i]) {
    if (e > 0) return [90, 159, 214];
    return e > -60 ? [79, 143, 208] : e > -250 ? [63, 121, 191] : e > -1000 ? [48, 100, 168] : e > -3000 ? [39, 81, 144] : [30, 64, 119];
  }
  const c = hex(BIOME_PX[biomeOf(i)] || "#96c95a");
  if (snowy(i)) return [236, 243, 246];
  if (e >= 1800) return mixc(c, [143, 138, 133], 0.8);
  if (e >= ROCKLINE) return mixc(c, [154, 140, 120], 0.55);
  if (e >= 700) return mixc(c, [181, 154, 106], 0.28);
  if (e >= 300) return mixc(c, [255, 255, 235], 0.07);
  return c;
}
function patternOf(i) {
  if (!LAND[i]) return 7;
  if (snowy(i)) return 4;
  if (ELEV[i] >= ROCKLINE) return 8;
  if (FARM[i]) return 9;
  return BIOME_PAT[biomeOf(i)] || 1;
}
function paint() {
  const key = S.paint, shade = shadeTops(), px = S.style === "pixel";
  const put = (i, c) => { colData[4 * i] = c[0]; colData[4 * i + 1] = c[1]; colData[4 * i + 2] = c[2]; colData[4 * i + 3] = shade[i]; };
  if (key === "@landscape") {
    const bio = F["biome"];
    for (let i = 0; i < N; i++) {
      if (px) { put(i, landscapePx(i)); continue; }
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
  // ground patterns: the full set on the landscape, only the water's on a painted value
  const land = px && key === "@landscape";
  for (let i = 0; i < N; i++) infoData[i] = !px ? 0 : land ? patternOf(i) : (LAND[i] ? 0 : 7);
  upload(4, texInfo, gl.RED, gl.UNSIGNED_BYTE, infoData);
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
// The tiles are the cells of a lattice, so a point lies in the tile whose centre is nearest, if that tile
// exists. On a sheet the outer tiles' edges are the sheet's edge; layers that run past it are cut there.
const SHAPE_SIGN = (() => { let a = 0; for (let k = 0; k < NV; k++) { const p = SHAPE[k], q = SHAPE[(k + 1) % NV]; a += p[0] * q[1] - q[0] * p[1]; } return a >= 0 ? 1 : -1; })();
const SHAPE_EDGES = SHAPE.map((a, k) => { const b = SHAPE[(k + 1) % NV]; return [a[0], a[1], b[0] - a[0], b[1] - a[1], Math.hypot(b[0] - a[0], b[1] - a[1])]; });
const EDGE_EPS = SPACING * 0.02;
function insideTile(t, x, y, eps = EDGE_EPS) {
  const dx = x - POS[2 * t], dy = y - POS[2 * t + 1];
  for (const [ax, ay, ex, ey, len] of SHAPE_EDGES) if (SHAPE_SIGN * (ex * (dy - ay) - ey * (dx - ax)) < -eps * len) return false;
  return true;
}
const tileOf = (x, y) => { const t = tileAt(x, y, SPACING * 0.8); return t >= 0 && insideTile(t, x, y) ? t : -1; };
function lineObj(xyArr, tiles) {
  const n = xyArr.length / 2, xy = new Float32Array(xyArr), tile = new Int32Array(tiles), z = new Float32Array(n);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let k = 0; k < n; k++) { const x = xy[2 * k], y = xy[2 * k + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return { xy, n, tile, z, bb: [x0, y0, x1, y1] };
}
// a line's pieces over the tiles: on a sheet, a line leaving the tiles is cut where it crosses the edge
function prepLine(flat, onWater = false, clip = true) {
  const pieces = []; let xy = [], tl = [];
  const flush = () => { if (xy.length >= 4) pieces.push(lineObj(xy, tl)); xy = []; tl = []; };
  let px = 0, py = 0, pt = -1;
  for (let k = 0; k < flat.length; k += 2) {
    const x = flat[k], y = flat[k + 1];
    if (!clip) { const t = tileAt(x, y, SPACING * 1.05); xy.push(x, y); tl.push(onWater ? -1 : t); continue; }
    const t = tileOf(x, y);
    if (k > 0 && (t >= 0) !== (pt >= 0)) {          // the edge lies between this point and the last
      const fromIn = pt >= 0;
      let ax = px, ay = py, bx = x, by = y;
      for (let it = 0; it < 14; it++) { const mx = (ax + bx) / 2, my = (ay + by) / 2; if ((tileOf(mx, my) >= 0) === fromIn) { ax = mx; ay = my; } else { bx = mx; by = my; } }
      const ex = fromIn ? ax : bx, ey = fromIn ? ay : by, et = tileOf(ex, ey);
      xy.push(ex, ey); tl.push(onWater ? -1 : (et >= 0 ? et : (fromIn ? pt : t)));
      if (fromIn) flush();
    }
    if (t >= 0) { xy.push(x, y); tl.push(onWater ? -1 : t); }
    px = x; py = y; pt = t;
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

// Zone fills, tile by tile. A zone's outline is cut to each tile it crosses (Sutherland-Hodgman against the
// tile's convex outline) and every tile wholly inside is filled whole, each piece at its own tile's height.
// So a zone that runs off a sheet is filled only over the sheet's tiles, holes stay open, and the fill sits
// on the blocks instead of stretching between their heights. Worked out the first time zones are shown.
let ZFILL = null;
function clipToTile(ring, t) {
  const cx = POS[2 * t], cy = POS[2 * t + 1];
  let pts = ring;
  for (const [ax0, ay0, ex, ey] of SHAPE_EDGES) {
    if (pts.length < 6) return null;
    const ax = ax0 + cx, ay = ay0 + cy, out = [];
    const side = (x, y) => SHAPE_SIGN * (ex * (y - ay) - ey * (x - ax));
    const n = pts.length / 2;
    let sx = pts[2 * n - 2], sy = pts[2 * n - 1], ss = side(sx, sy);
    for (let k = 0; k < n; k++) {
      const x = pts[2 * k], y = pts[2 * k + 1], s = side(x, y);
      if (s >= 0) {
        if (ss < 0) { const u = ss / (ss - s); out.push(sx + (x - sx) * u, sy + (y - sy) * u); }
        out.push(x, y);
      } else if (ss >= 0) { const u = ss / (ss - s); out.push(sx + (x - sx) * u, sy + (y - sy) * u); }
      sx = x; sy = y; ss = s;
    }
    pts = out;
  }
  return pts.length >= 6 ? pts : null;
}
function ringArea(p) { let a = 0; const n = p.length / 2; for (let k = 0; k < n; k++) { const j = (k + 1) % n; a += p[2 * k] * p[2 * j + 1] - p[2 * j] * p[2 * k + 1]; } return a / 2; }
function buildZoneFill(z) {
  const rings = [];
  for (const poly of z.polys) for (const r of poly) if (r.length >= 6) rings.push(r);
  const out = { full: [], parts: [] };
  if (!rings.length) return out;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of rings) for (let k = 0; k < r.length; k += 2) { x0 = Math.min(x0, r[k]); x1 = Math.max(x1, r[k]); y0 = Math.min(y0, r[k + 1]); y1 = Math.max(y1, r[k + 1]); }
  // edges by horizontal band, for even-odd point tests; and the tiles the outline passes through
  const band = SPACING, bands = new Map(), edge = new Set(), step = SPACING / 6;
  for (const r of rings) {
    const n = r.length / 2;
    for (let k = 0; k < n; k++) {
      const j = (k + 1) % n, ax = r[2 * k], ay = r[2 * k + 1], bx = r[2 * j], by = r[2 * j + 1];
      if (ay !== by) {
        const b0 = Math.floor((Math.min(ay, by) - y0) / band), b1 = Math.floor((Math.max(ay, by) - y0) / band);
        for (let b = b0; b <= b1; b++) { if (!bands.has(b)) bands.set(b, []); bands.get(b).push(ax, ay, bx, by); }
      }
      const m = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / step));
      for (let s = 0; s <= m; s++) { const t = tileAt(ax + ((bx - ax) * s) / m, ay + ((by - ay) * s) / m, SPACING * 0.8); if (t >= 0) edge.add(t); }
    }
  }
  const inside = (x, y) => {
    const e = bands.get(Math.floor((y - y0) / band)); if (!e) return false;
    let c = false;
    for (let k = 0; k < e.length; k += 4) { const ay = e[k + 1], by = e[k + 3]; if ((ay > y) !== (by > y) && e[k] + ((y - ay) * (e[k + 2] - e[k])) / (by - ay) > x) c = !c; }
    return c;
  };
  const gx0 = Math.max(0, Math.floor((x0 - BX0) / BK)), gx1 = Math.min(BW - 1, Math.floor((x1 - BX0) / BK));
  const gy0 = Math.max(0, Math.floor((y0 - BY0) / BK)), gy1 = Math.min(BH - 1, Math.floor((y1 - BY0) / BK));
  for (let gy = gy0; gy <= gy1; gy++) for (let gx = gx0; gx <= gx1; gx++) {
    const k = gy * BW + gx;
    for (let q = bucketStart[k]; q < bucketStart[k + 1]; q++) { const i = bucketItems[q]; if (!edge.has(i) && inside(POS[2 * i], POS[2 * i + 1])) out.full.push(i); }
  }
  const tiny = SPACING * SPACING * 1e-4;
  for (const t of edge) {
    const rs = [];
    for (const r of rings) { const c = clipToTile(r, t); if (c && Math.abs(ringArea(c)) > tiny) rs.push(Float32Array.from(c)); }
    if (rs.length) out.parts.push({ t, rs });
  }
  out.full = Int32Array.from(out.full);
  return out;
}
// fills a zone's tiles one by one (even-odd only within a tile, so its holes stay open while tiles whose
// tops overlap on screen do not cancel out)
function zoneFill(c, zf, lift) {
  const m = SPACING * S.cam.zoom * 1.5 + 30;
  const vis = (t) => { const [sx, sy] = project(POS[2 * t], POS[2 * t + 1], TOP[t]); return sx > -m && sy > -m && sx < VW + m && sy < VH + m; };
  for (const t of zf.full) {
    if (!vis(t)) continue;
    const x = POS[2 * t], y = POS[2 * t + 1], z = TOP[t] + lift;
    c.beginPath();
    for (let k = 0; k < NV; k++) { const [sx, sy] = project(x + SHAPE[k][0], y + SHAPE[k][1], z); if (k) c.lineTo(sx, sy); else c.moveTo(sx, sy); }
    c.fill();
  }
  for (const p of zf.parts) {
    if (!vis(p.t)) continue;
    const z = TOP[p.t] + lift;
    c.beginPath();
    for (const r of p.rs) {
      for (let k = 0; k < r.length; k += 2) { const [sx, sy] = project(r[k], r[k + 1], z); if (k) c.lineTo(sx, sy); else c.moveTo(sx, sy); }
      c.closePath();
    }
    c.fill("evenodd");
  }
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

// ====================================================================== pixel art: sprites
// SPRITE_DEFS holds the art: each sprite is rows of palette letters ('.' is clear). Baking adds a one-pixel
// outline in a darker shade of whatever it borders, and swaps in the leaf, grass or flag colours asked for.
const SPRITE_CACHE = new Map();
function bakeSprite(name, variant = null, recolor = null) {
  const key = `${name}:${variant || ""}:${recolor ? Object.values(recolor).join("") : ""}`;
  let s = SPRITE_CACHE.get(key);
  if (s) return s;
  const D = SPRITE_DEFS, rows = D.sprites[name];
  const pal = Object.assign({}, D.base);
  if (variant && D.leaf[variant]) [pal.L, pal.l, pal.m] = D.leaf[variant];
  if (variant && D.grass[variant]) [pal.h, pal.H] = D.grass[variant];
  if (recolor) Object.assign(pal, recolor);
  const rgb = {}; for (const k in pal) rgb[k] = hex(pal[k]);
  const w = rows[0].length + 2, h = rows.length + 2, px = new Uint8ClampedArray(w * h * 4), on = new Uint8Array(w * h);
  rows.forEach((r, y) => { for (let x = 0; x < r.length; x++) { const ch = r[x]; if (ch === ".") continue; const c = rgb[ch] || [255, 0, 255], o = ((y + 1) * w + x + 1); px.set([c[0], c[1], c[2], 255], o * 4); on[o] = 1; } });
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const o = y * w + x; if (on[o]) continue;
    let best = null, bs = Infinity;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const X = x + dx, Y = y + dy; if (X < 0 || Y < 0 || X >= w || Y >= h || !on[Y * w + X]) continue;
      const q = (Y * w + X) * 4, sum = px[q] + px[q + 1] + px[q + 2]; if (sum < bs) { bs = sum; best = q; }
    }
    if (best !== null) px.set([px[best] * 0.42, px[best + 1] * 0.42, px[best + 2] * 0.42, 255], o * 4);
  }
  s = { w, h, px };
  SPRITE_CACHE.set(key, s);
  return s;
}
function spriteCanvas(name, variant = null, recolor = null) {
  const s = bakeSprite(name, variant, recolor);
  if (!s.cv) { s.cv = document.createElement("canvas"); s.cv.width = s.w; s.cv.height = s.h; s.cv.getContext("2d").putImageData(new ImageData(s.px, s.w, s.h), 0, 0); }
  return s.cv;
}

// ---- what grows where: per placement slot, the chance of nothing and the weights of each sprite
// ('name:variant'); "big" sprites (peaks, hills, dunes, icebergs) stay visible further out
const DECOR_BIOME = {
  "Hot desert": [0.55, [["cactus", 12], ["cactus_small", 10], ["dune", 13], ["rock", 6], ["dry_shrub:dry", 4]]],
  "Cold desert": [0.58, [["rock", 18], ["dry_shrub:dry", 14], ["dune", 6], ["dead_tree", 4]]],
  "Savanna": [0.35, [["acacia:savanna", 18], ["grass:savanna", 32], ["bush:savanna", 15]]],
  "Grassland": [0.32, [["grass:temperate", 38], ["flowers:temperate", 14], ["bush:temperate", 10], ["oak_small:temperate", 6]]],
  "Tropical seasonal forest": [0.1, [["jungle:tropical", 22], ["palm:palm", 18], ["oak:tropical", 30], ["bush:tropical", 20]]],
  "Temperate deciduous forest": [0.06, [["oak:temperate", 50], ["oak_small:temperate", 30], ["pine:temperate", 8], ["bush:temperate", 6]]],
  "Tropical rainforest": [0.03, [["jungle:jungle", 55], ["palm:palm", 20], ["bush:jungle", 22]]],
  "Temperate rainforest": [0.05, [["fir:conifer", 50], ["pine:conifer", 30], ["oak:wet", 10], ["bush:wet", 5]]],
  "Taiga": [0.1, [["pine:taiga", 55], ["pine_snow:taiga", 15], ["rock", 5], ["bush:taiga", 10], ["pine:conifer", 5]]],
  "Tundra": [0.5, [["rock", 18], ["grass:tundra", 20], ["dry_shrub:tundra", 12]]],
  "Glacier": [0.62, [["ice", 23], ["rock_snow", 15]]],
  "Wetland": [0.2, [["reeds:wet", 45], ["puddle", 20], ["bush:wet", 10], ["oak_small:wet", 5]]],
};
const HILL_LEAF = { "Savanna": "savanna", "Hot desert": "dry", "Cold desert": "dry", "Tundra": "dry", "Taiga": "taiga", "Tropical seasonal forest": "tropical",
  "Tropical rainforest": "tropical", "Wetland": "wet" };
const FARMABLE = new Set(["Grassland", "Savanna", "Temperate deciduous forest", "Tropical seasonal forest", "Temperate rainforest", "Taiga", "Tropical rainforest"]);
const BIG = new Set(["peak", "peak_snow", "peak_small", "dune", "iceberg"]);

// ---- the climate at a tile, and its biome (worked out from temperature and rain when the export has none)
const fTempC = F["temp_c"], fTempD = F["temp"], fPrec = F["prec_mm"];
function tempC(i) {
  if (fTempC) return numOf(fTempC, i);
  if (fTempD) { const t = numOf(fTempD, i); return TU === "°F" ? ((t - 32) * 5) / 9 : TU === "K" ? t - 273.15 : t; }
  return NaN;
}
function guessBiome(i) {
  if (!LAND[i]) return "Marine";
  const t = tempC(i), p = fPrec ? numOf(fPrec, i) : NaN;
  if (Number.isNaN(t)) return "Grassland";
  if (t < -5) return "Glacier"; if (t < 0) return "Tundra"; if (t < 5) return "Taiga";
  if (Number.isNaN(p)) return t > 20 ? "Savanna" : "Grassland";
  if (t > 22 && p < 250) return "Hot desert"; if (p < 200) return "Cold desert";
  if (t > 20) return p > 1600 ? "Tropical rainforest" : p > 900 ? "Tropical seasonal forest" : "Savanna";
  return p > 1500 ? "Temperate rainforest" : p > 700 ? "Temperate deciduous forest" : "Grassland";
}
const fBiome = F["biome"];
const biomeOf = (i) => (fBiome && catOf(fBiome, i)) || guessBiome(i);

// ---- placement. Each tile has a few slots scattered over it; what fills a slot follows the biome, the
// height (hills, peaks and snow), the people (fields where the countryside is crowded) and the sea (waves,
// icebergs). Slots near towns, roads, trails and rivers are left clear.
function h32(a, b) {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul((b + 0x632be5ab) | 0, 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
const FARM = new Uint8Array(N);
const DECOR = { n: 0, keys: [], index: new Map(), data: null };
const KEEP = new Set(), KC = SPACING / 7;
const keepKey = (x, y) => Math.floor((y - BY0) / KC) * 1048576 + Math.floor((x - BX0) / KC);
function keepLine(flat, r) {
  for (let k = 0; k + 3 < flat.length; k += 2) {
    const ax = flat[k], ay = flat[k + 1], bx = flat[k + 2], by = flat[k + 3], m = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / (KC * 0.5)));
    for (let s = 0; s <= m; s++) {
      const x = ax + ((bx - ax) * s) / m, y = ay + ((by - ay) * s) / m;
      for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) KEEP.add(keepKey(x + dx * KC, y + dy * KC));
    }
  }
}
function buildDecor() {
  for (const r of META.rivers) keepLine(r.pts, 1);
  for (const r of META.routes) if (r.group !== "searoutes") keepLine(r.pts, 1);
  const clear = new Map();
  for (const B of BURGS) { if (B.tile < 0) continue; const t = { capital: 0.62, city: 0.55, town: 0.42 }[B.b.group] || 0.3; addTo(clear, B.tile, [B.x, B.y, t * SPACING]); }
  for (const s of STOPS) if (s.tile >= 0) addTo(clear, s.tile, [s.x, s.y, 0.18 * SPACING]);
  // crowded countryside: the share of land tiles with fewer people
  const fDen = F["density"] || F["rural"] || F["people"], dv = values(fDen);
  let q80 = Infinity, q92 = Infinity;
  if (dv) {
    const a = []; for (let i = 0; i < N; i++) if (LAND[i] && dv[i] > 0) a.push(dv[i]);
    a.sort((x, y) => x - y);
    if (a.length > 20) { q80 = a[Math.floor(0.8 * (a.length - 1))]; q92 = a[Math.floor(0.92 * (a.length - 1))]; }
  }
  const slots = N > 150000 ? 5 : 7, inr = Math.min(...SHAPE_EDGES.map(([ax, ay, ex, ey, len]) => Math.abs(ax * ey - ay * ex) / len));
  const out = [], idx = DECOR.index;
  const sprite = (key) => { let k = idx.get(key); if (k === undefined) { k = DECOR.keys.length; DECOR.keys.push(key); idx.set(key, k); } return k; };
  const pick = (table, r) => { let tot = 0; for (const [, w] of table) tot += w; let u = r * tot; for (const [k, w] of table) { u -= w; if (u <= 0) return k; } return table[table.length - 1][0]; };
  const emit = (x, y, i, key, rank, flip) => {
    const big = BIG.has(key.split(":")[0]);
    out.push(x, y, i, sprite(key) + 256 * Math.min(255, Math.floor(rank * 256)) + 65536 * (flip ? 1 : 0) + 131072 * (big ? 1 : 0));
  };
  for (let i = 0; i < N; i++) {
    const cx = POS[2 * i], cy = POS[2 * i + 1], e = ELEV[i], t = tempC(i), rot = h32(i, 1) * Math.PI * 2;
    const cl = clear.get(i);
    const free = (x, y) => !KEEP.has(keepKey(x, y)) && !(cl && cl.some(([bx, by, r]) => Math.hypot(x - bx, y - by) < r));
    const at = (k, spread = 1) => {
      const r = inr * 0.78 * spread * Math.sqrt((k + 0.5) / slots), a = rot + k * 2.39996;
      return [cx + Math.cos(a) * r + (h32(i, 40 + k) - 0.5) * inr * 0.16, cy + Math.sin(a) * r + (h32(i, 60 + k) - 0.5) * inr * 0.16];
    };
    if (!LAND[i]) {
      const lake = e > 0, cold = t < -3;
      for (let k = 0; k < 3; k++) {
        const r = h32(i, 100 + k), p = lake ? 0.06 : cold ? 0.12 : e > -150 ? 0.14 : 0.07;
        if (r >= p) continue;
        const [x, y] = at(k * 2, 1.1); if (!free(x, y)) continue;
        emit(x, y, i, cold && !lake ? "iceberg" : "wave", h32(i, 120 + k), h32(i, 140 + k) > 0.5);
      }
      continue;
    }
    const b = biomeOf(i), spec = DECOR_BIOME[b] || DECOR_BIOME.Grassland;
    let empty = spec[0], table = spec[1], first = 0;
    // hills and mountains take the middle of the tile
    if (e >= 1500) {
      const [x, y] = at(0, 0.25);
      emit(x, y, i, e >= SNOWLINE || t < -4 ? "peak_snow" : "peak", h32(i, 7) * 0.1, h32(i, 8) > 0.5);
      first = 1; empty = Math.min(0.92, empty + 0.5);
      if (e >= 2200) table = [["rock_snow", 4], ["rock", 3]];
      else table = t < 0 ? [["pine_snow:taiga", 5], ["rock", 3]] : [["pine:conifer", 5], ["rock", 3], ["bush:" + (HILL_LEAF[b] || "temperate"), 2]];
    } else if (e >= 700 && h32(i, 9) < 0.65) {
      const [x, y] = at(0, 0.35);
      emit(x, y, i, e >= 1100 ? "peak_small" : `hill:${HILL_LEAF[b] || "temperate"}`, h32(i, 7) * 0.12, h32(i, 8) > 0.5);
      first = 1; empty = Math.min(0.9, empty + 0.15);
    }
    // fields where the countryside is crowded
    if (dv && FARMABLE.has(b) && e < ROCKLINE && dv[i] >= q80) {
      FARM[i] = 1;
      empty = 1 - (1 - empty) * (dv[i] >= q92 ? 0.12 : 0.35);
      table = table.concat([["haystack", 40 * (1 - empty)]]);
    }
    if (t < -2) table = table.map(([k, w]) => [k.startsWith("pine:") ? "pine_snow:taiga" : k, w]);
    for (let k = first; k < slots; k++) {
      const r = h32(i, 200 + k);
      if (r < empty) continue;
      const [x, y] = at(k); if (!free(x, y)) continue;
      emit(x, y, i, pick(table, (r - empty) / (1 - empty)), h32(i, 300 + k), h32(i, 400 + k) > 0.5);
    }
  }
  DECOR.data = new Float32Array(out);
  DECOR.n = out.length / 4;
}
buildDecor();

// ---- the atlas: every sprite the decorations use, baked once and packed in shelves
const ATLAS = { w: 256, h: 1, rects: [] };
{
  const baked = DECOR.keys.map((key) => { const [n, v] = key.split(":"); return bakeSprite(n, v || null); });
  const order = baked.map((_, k) => k).sort((a, b) => baked[b].h - baked[a].h);
  let x = 0, y = 0, rowH = 0;
  for (const k of order) {
    const s = baked[k];
    if (x + s.w > ATLAS.w) { x = 0; y += rowH; rowH = 0; }
    ATLAS.rects[k] = [x, y, s.w, s.h]; x += s.w; rowH = Math.max(rowH, s.h);
  }
  ATLAS.h = Math.max(1, y + rowH);
  const img = new Uint8Array(ATLAS.w * ATLAS.h * 4);
  baked.forEach((s, k) => { const [ax, ay] = ATLAS.rects[k]; for (let r = 0; r < s.h; r++) img.set(s.px.subarray(r * s.w * 4, (r + 1) * s.w * 4), ((ay + r) * ATLAS.w + ax) * 4); });
  ATLAS.tex = makeTex(5, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, img, ATLAS.w, ATLAS.h);
}
// Each decoration is a billboard standing on its tile, snapped to the art-pixel grid and scaled by whole
// pixels. Its depth rises up the sprite as a standing object's would, so taller tiles in front hide it.
const NR = Math.max(1, ATLAS.rects.length);
const SVS = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
layout(location=0) in vec2 aCorner; layout(location=1) in vec4 aInst;
uniform sampler2D uTop, uMask; uniform int uTW;
uniform vec2 uTarget, uRot, uPitch, uNdcS, uNdcO, uTgt; uniform float uZoom, uDepth, uScale, uFrac, uBigOn, uPxCss, uDim;
uniform vec4 uRect[${NR}];
out vec2 vUV; flat out vec4 vR; flat out float vDim;
void main(){
  float pk = aInst.w; int spr = int(mod(pk, 256.0)); float rank = mod(floor(pk / 256.0), 256.0) / 255.0;
  float fl = mod(floor(pk / 65536.0), 2.0); float big = floor(pk / 131072.0);
  if (big > 0.5 ? uBigOn < 0.5 : rank >= uFrac) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  int tile = int(aInst.z + 0.5); ivec2 tc = ivec2(tile % uTW, tile / uTW);
  float top = texelFetch(uTop, tc, 0).r; vec2 mk = texelFetch(uMask, tc, 0).rg;
  vec2 p = aInst.xy - uTarget;
  float xr = uRot.x * p.x - uRot.y * p.y, yr = uRot.y * p.x + uRot.x * p.y;
  vec2 s = vec2(xr, yr * uPitch.x + top * uPitch.y) * uZoom;
  vec2 px = ((s * uNdcS + uNdcO) * 0.5 + 0.5) * uTgt;
  vec4 r = uRect[spr]; vec2 sz = r.zw * uScale;
  vec2 org = floor(vec2(px.x - sz.x * 0.5, px.y - uScale) + 0.5);
  vec2 q = org + aCorner * sz;
  float lift = aCorner.y * sz.y * uPxCss / (uZoom * max(uPitch.y, 0.22));
  gl_Position = vec4(q / uTgt * 2.0 - 1.0, clamp((yr * uPitch.y - (top + lift) * uPitch.x) / uDepth - 0.0004, -0.999, 0.999), 1.0);
  vUV = vec2(fl > 0.5 ? 1.0 - aCorner.x : aCorner.x, 1.0 - aCorner.y) * r.zw;
  vR = r; vDim = max(uDim, (1.0 - mk.r) * 0.82);
}`;
const SFS = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
in vec2 vUV; flat in vec4 vR; flat in float vDim; uniform sampler2D uAtlas; uniform vec3 uDimTo; uniform float uMute; out vec4 o;
void main(){
  vec4 c = texelFetch(uAtlas, ivec2(vR.xy) + ivec2(clamp(floor(vUV), vec2(0.0), vR.zw - 1.0)), 0);
  if (c.a < 0.5) discard;
  vec3 col = c.rgb; float g = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(col, vec3(g * 0.85 + 0.1), uMute);
  o = vec4(mix(col, mix(vec3(g), uDimTo, 0.78), vDim), 1.0);
}`;
let sprog = null, US = null, svao = null;
try {
  sprog = program(SVS, SFS);
  US = uniformsOf(sprog, ["uTop", "uMask", "uAtlas", "uTW", "uTarget", "uRot", "uPitch", "uNdcS", "uNdcO", "uTgt", "uZoom", "uDepth", "uScale", "uFrac",
    "uBigOn", "uPxCss", "uDim", "uDimTo", "uMute", "uRect"]);
  svao = gl.createVertexArray(); gl.bindVertexArray(svao);
  const cb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, cb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 8, 0);
  const ibf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, ibf); gl.bufferData(gl.ARRAY_BUFFER, DECOR.data, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 16, 0); gl.vertexAttribDivisor(1, 1);
  gl.bindVertexArray(null);
} catch (e) { console.warn("Decorations are off: " + e.message); sprog = null; }
const RECTS = new Float32Array(NR * 4); ATLAS.rects.forEach((r, k) => RECTS.set(r, k * 4));
// how big the decorations are drawn, and how many, at the current zoom
function decorScale(M) {
  const tileArt = (SPACING * S.cam.zoom) / (M.pxCss * M.art);
  const k = Math.max(1, Math.min(6, Math.round(tileArt / 30)));
  return { tileArt, scale: k * M.art, frac: Math.min(1, S.detail * Math.max(0, Math.min(1, (tileArt - 10) / 30)) ** 1.5), big: S.detail > 0 && tileArt >= 5 };
}
function drawSprites(M) {
  if (!sprog || !S.show.decor || !DECOR.n) return;
  const d = decorScale(M);
  if (d.frac <= 0 && !d.big) return;
  gl.useProgram(sprog); gl.bindVertexArray(svao);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texTop);
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, texMask);
  gl.activeTexture(gl.TEXTURE5); gl.bindTexture(gl.TEXTURE_2D, ATLAS.tex);
  gl.uniform1i(US.uTop, 0); gl.uniform1i(US.uMask, 2); gl.uniform1i(US.uAtlas, 5); gl.uniform1i(US.uTW, TW);
  gl.uniform2f(US.uTarget, S.cam.x, S.cam.y); gl.uniform2f(US.uRot, cv.c, cv.s); gl.uniform2f(US.uPitch, cv.sp, cv.cp);
  gl.uniform2f(US.uNdcS, M.sx, M.sy); gl.uniform2f(US.uNdcO, M.ox, M.oy); gl.uniform2f(US.uTgt, M.tw, M.th);
  gl.uniform1f(US.uZoom, S.cam.zoom); gl.uniform1f(US.uDepth, depthRange()); gl.uniform1f(US.uScale, d.scale);
  gl.uniform1f(US.uFrac, d.frac); gl.uniform1f(US.uBigOn, d.big ? 1 : 0); gl.uniform1f(US.uPxCss, M.pxCss);
  gl.uniform1f(US.uDim, S.trade.on ? S.trade.dim : 0); gl.uniform3f(US.uDimTo, GROUND[0] / 255, GROUND[1] / 255, GROUND[2] / 255);
  gl.uniform1f(US.uMute, S.paint === "@landscape" ? 0 : 0.45); gl.uniform4fv(US.uRect, RECTS);
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.disable(gl.CULL_FACE);
  gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, DECOR.n);
  gl.bindVertexArray(null);
}

// ---- town icons: buildings put together by the town's size, its features and its people's way of life
const ICONS = new Map();
const stateColor = (name) => { const f = F["state"] || F["t:state"]; const k = f ? f.dict.indexOf(name) : -1; return k >= 0 ? PALETTE[k % PALETTE.length] : [120, 120, 130]; };
const cssHex = (c) => "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
const flagOf = (state) => { const c = stateColor(state); return { g: cssHex(c), G: cssHex(c.map((v) => v * 0.62)) }; };
function tierOf(b) {
  const g = (b.group || "").toLowerCase();
  if (g === "capital" || (b.flags || []).includes("capital")) return 4;
  if (g === "city") return 3; if (g === "town") return 2; if (g === "village") return 1; if (g === "hamlet") return 0;
  const p = b.people || 0; return p >= 20000 ? 3 : p >= 5000 ? 2 : p >= 1000 ? 1 : 0;
}
function burgParts(b) {
  const f = new Set(b.flags || []), g = (b.group || "").toLowerCase().replace(/[\s-]+/g, "_"), nomad = b.type === "Nomadic", t = tierOf(b);
  const hut = nomad ? "tent" : "hut", house = nomad ? "tent" : "house", slate = nomad ? "tent" : "house_slate";
  let P;
  if (g === "fort") P = [["tower", 0, 1], ["wall", 0, -1]];
  else if (g === "monastery") P = [["church", 0, 1], [hut, 7, 0]];
  else if (g === "caravanserai") P = [["tent", -5, 0], ["house_long", 3, 1]];
  else if (g === "trading_post") P = [[house, 0, 1], ["crates", 6, -1]];
  else P = [[[hut, 0, 0]], [[house, -3, 1], [hut, 4, 0]], [[slate, -5, 3], [house, 4, 3], [hut, -1, 0]],
    [["house_long", 0, 5], [slate, -8, 2], [house, 8, 2], [house, 0, 0]], [["castle", 0, 4], [house, -11, 1], [slate, 11, 1]]][t].slice();
  if (f.has("temple") && g !== "monastery") P.push(["church", t >= 3 ? -5 : 0, t >= 2 ? 6 : 3]);
  if (f.has("citadel") && t < 4 && g !== "fort") P.push(["tower", t >= 3 ? 10 : 6, 4]);
  if (f.has("walls") && g !== "fort") P.push(["wall", 0, -2]);
  if (f.has("port")) P.push(["boat", t >= 3 ? 15 : t >= 2 ? 11 : 8, -3]);
  if (f.has("shanty")) P.push(["shack", t >= 3 ? -15 : -9, -1]);
  if (f.has("plaza") && t >= 2) P.push(["crates", 3, -2]);
  return P;
}
function burgIcon(b) {
  const parts = burgParts(b), flag = flagOf(b.state);
  const key = parts.map((p) => p.join(",")).join(";") + (tierOf(b) === 4 ? flag.g : "");
  let ic = ICONS.get(key);
  if (ic) return ic;
  const placed = parts.map(([n, cx, by]) => { const s = bakeSprite(n, null, n === "castle" ? flag : null); return { n, s, x: cx - Math.floor(s.w / 2), y: -by - s.h, by }; });
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of placed) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + p.s.w); y1 = Math.max(y1, p.y + p.s.h); }
  const cv = document.createElement("canvas"); cv.width = x1 - x0; cv.height = y1 - y0;
  const c = cv.getContext("2d");
  placed.sort((a, b) => b.by - a.by);
  for (const p of placed) c.drawImage(spriteCanvas(p.n, null, p.n === "castle" ? flag : null), p.x - x0, p.y - y0);
  ic = { cv, w: cv.width, h: cv.height, ax: -x0, ay: -y0 };   // (ax, ay): the ground point under the town, in icon pixels
  ICONS.set(key, ic);
  return ic;
}
const unitIcon = (u) => spriteCanvas(u.naval ? "ship" : "banner", null, flagOf(u.state));

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
// Each zone is filled as an opaque mask of its tiles, then laid on the map once: a light tint when smooth,
// a hatch of whole art pixels (the pixel-art way of showing something see-through) in the pixel-art style.
let ZBUF = null;
function zoneLayer(cl, z, zf, alpha) {
  if (!ZBUF) ZBUF = document.createElement("canvas");
  if (ZBUF.width !== ovl.width || ZBUF.height !== ovl.height) { ZBUF.width = ovl.width; ZBUF.height = ovl.height; }
  const zc = ZBUF.getContext("2d"), col = ZONE_HUE(z.type), px = S.style === "pixel";
  zc.globalCompositeOperation = "source-over"; zc.setTransform(1, 0, 0, 1, 0, 0); zc.clearRect(0, 0, ZBUF.width, ZBUF.height);
  zc.setTransform(cl.getTransform()); zc.fillStyle = "#000"; zoneFill(zc, zf, 0.002);
  zc.setTransform(1, 0, 0, 1, 0, 0); zc.globalCompositeOperation = "source-in";
  if (px) {
    const t = document.createElement("canvas"); t.width = t.height = 4; const x = t.getContext("2d");
    x.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},.18)`; x.fillRect(0, 0, 4, 4);
    x.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},.7)`; for (let k = 0; k < 4; k++) x.fillRect(k, 3 - k, 1, 1);
    zc.fillStyle = zc.createPattern(t, "repeat");
  } else zc.fillStyle = css(col);
  zc.fillRect(0, 0, ZBUF.width, ZBUF.height);
  zc.globalCompositeOperation = "source-over";
  cl.save(); cl.setTransform(1, 0, 0, 1, 0, 0); cl.globalAlpha = alpha * (px ? 1 : 0.22); cl.drawImage(ZBUF, 0, 0); cl.restore();
}
function drawOverlay() {
  const c = octx, cl = lctx; c.clearRect(0, 0, VW, VH); HITS = [];
  cl.save(); cl.setTransform(1, 0, 0, 1, 0, 0); cl.clearRect(0, 0, ovl.width, ovl.height); cl.restore();
  const tilePx = SPACING * S.cam.zoom, ink = DARK() ? "#e4e9ef" : "#1b2430";
  const sh = S.show, px = S.style === "pixel", art = ART();
  // line widths in CSS pixels; the pixel-art style keeps every line at least one art pixel wide
  const lw = (w) => Math.max(px ? art : 0.6, Math.min(w, w * (tilePx / 8)));
  const fixed = (w) => (px ? Math.max(art, Math.round(w / art) * art) : w);
  const dash = (a) => (px ? a.map((v) => Math.max(1, Math.round(v / art)) * art) : a);
  cl.globalAlpha = S.trade.on ? 0.45 : 1;
  cl.lineCap = px ? "butt" : "round"; cl.lineJoin = px ? "miter" : "round";
  if (sh.zones && META.zones.length) {
    if (!ZFILL) ZFILL = META.zones.map(buildZoneFill);
    META.zones.forEach((z, k) => zoneLayer(cl, z, ZFILL[k], cl.globalAlpha));
    for (const o of L.zones) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const col = ZONE_HUE(o.f.type); pathOf(cl, o, false, 0.002);
      cl.setLineDash(dash([5, 4])); cl.lineWidth = fixed(1.4); cl.strokeStyle = css(col); cl.stroke(); cl.setLineDash([]);
    }
  }
  if (sh.coast) { cl.lineWidth = lw(1.1); cl.strokeStyle = DARK() ? "rgba(200,220,240,.55)" : "rgba(30,50,80,.55)"; for (const o of L.land) { if (!onScreen(o.bb, 0)) continue; pathOf(cl, o, false); cl.stroke(); } }
  if (sh.squares) {
    cl.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--grid"); cl.lineWidth = fixed(1.3);
    for (const o of L.squares) { if (!onScreen(o.bb, ZMAX)) continue; pathOf(cl, o, false); cl.stroke(); }
  }
  if (sh.blocks && tilePx > 2.5) {
    const ga = cl.globalAlpha;
    cl.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--grid"); cl.globalAlpha = ga * 0.45; cl.lineWidth = fixed(0.8);
    for (const o of L.blocks) { if (!onScreen(o.bb, ZMAX)) continue; pathOf(cl, o, false); cl.stroke(); }
    cl.globalAlpha = ga;
  }
  if (sh.rivers) {
    cl.strokeStyle = px ? "#3f86cf" : "#3d7fc4";
    for (const o of L.rivers) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const w = Math.max(0.8, Math.min(5, Math.sqrt(o.f.discharge || 1) / 6 * Math.min(1.5, tilePx / 6)));
      cl.lineWidth = fixed(w); pathOf(cl, o, false, SPACING * 0.01); cl.stroke();
    }
  }
  if (sh.borders) {
    for (const o of L.borders) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const st = worstStance(o.f);
      pathOf(cl, o, false, SPACING * 0.02);
      cl.lineWidth = fixed(4); cl.strokeStyle = DARK() ? "rgba(14,19,26,.6)" : "rgba(255,255,255,.65)"; cl.stroke();
      cl.setLineDash(dash([7, 4])); cl.lineWidth = fixed(1.8); cl.strokeStyle = STANCE[st] || STANCE.Neutral; cl.stroke(); cl.setLineDash([]);
    }
  }
  if (sh.routes) {
    for (const o of L.routes) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const g = o.f.group;
      if (g === "trails" && tilePx < 1.5) continue;
      pathOf(cl, o, false, SPACING * 0.015);
      if (g === "searoutes") { cl.setLineDash(dash([2, 5])); cl.lineWidth = fixed(1.2); cl.strokeStyle = DARK() ? "rgba(170,205,240,.75)" : "rgba(30,70,120,.6)"; }
      else if (g === "roads") { cl.setLineDash([]); cl.lineWidth = px ? fixed(lw(2.2)) : lw(2.2); cl.strokeStyle = px ? "#a8743f" : "#9b3b25"; }
      else { cl.setLineDash(dash([5, 3])); cl.lineWidth = px ? fixed(lw(1.3)) : lw(1.3); cl.strokeStyle = DARK() ? "#c49a6c" : "#7a5536"; }
      cl.stroke(); cl.setLineDash([]);
    }
  }
  if (S.trade.traffic && L.traffic.length) {
    let maxv = 0; for (const o of L.traffic) maxv = Math.max(maxv, o.f.value || 0);
    for (const o of L.traffic) {
      if (!onScreen(o.bb, ZMAX)) continue;
      const gi = GOODS.indexOf(o.f.top); const col = gi >= 0 ? GOOD_COLOR[gi] : [120, 120, 120];
      cl.lineWidth = fixed(1 + 9 * Math.sqrt((o.f.value || 0) / (maxv || 1)));
      cl.strokeStyle = `rgba(${col[0]},${col[1]},${col[2]},.55)`; pathOf(cl, o, false, SPACING * 0.03); cl.stroke();
    }
  }
  cl.globalAlpha = 1;
  c.lineCap = "round"; c.lineJoin = "round";
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
    if (px) {
      const cvs = unitIcon(u.u), k = iconScale(tilePx), w = cvs.width * k, h = cvs.height * k;
      const left = snap(x - w / 2), top = snap(y - h + k);
      c.imageSmoothingEnabled = false; c.drawImage(cvs, left, top, w, h);
      HITS.push({ x, y: y - h / 2, r: Math.max(8, h / 2), kind: "unit", o: u });
      continue;
    }
    const col = stateColor(u.u.state);
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
    const icon = markerIcon(m.m);
    if (px) {   // a square badge of whole art pixels
      const a = Math.max(1, Math.round(art)), s = 9 * a, l = snap(x - s), t = snap(y - 10 - s);
      c.fillStyle = DARK() ? "#2a3240" : "#fbf8ef"; c.fillRect(l, t, 2 * s, 2 * s);
      c.fillStyle = DARK() ? "#c9d2dd" : "#3b3226"; c.fillRect(l, t, 2 * s, a); c.fillRect(l, t + 2 * s - a, 2 * s, a); c.fillRect(l, t, a, 2 * s); c.fillRect(l + 2 * s - a, t, a, 2 * s);
      c.fillRect(snap(x - a), t + 2 * s, 2 * a, 3 * a);
    } else {
      c.beginPath(); c.arc(x, y - 10, 9, 0, Math.PI * 2); c.fillStyle = DARK() ? "rgba(20,26,34,.9)" : "rgba(255,255,255,.92)"; c.fill();
      c.lineWidth = 1; c.strokeStyle = "rgba(0,0,0,.25)"; c.stroke();
    }
    c.font = "12px system-ui, 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillStyle = ink; c.fillText(icon, x, y - 9.5);
    HITS.push({ x, y: y - 10, r: 10, kind: "marker", o: m });
  }
  if (S.sel >= 0) outlineTile(c, S.sel, getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(), 2.6);
  dirty.overlay = false;
}
const snap = (v) => Math.round(v * DPR) / DPR;
// icons are drawn in whole art pixels, and a size up when the tiles are large
const iconScale = (tilePx) => ART() * Math.max(1, Math.min(4, Math.round(tilePx / ART() / 40)));
function drawBurgs(c, tilePx, ink) {
  const order = BURGS.slice().sort((a, b) => (b.b.people || 0) - (a.b.people || 0));
  const grid = new Map(), cellSz = 60;
  const free = (b) => {
    for (let gx = Math.floor(b[0] / cellSz); gx <= Math.floor(b[2] / cellSz); gx++) for (let gy = Math.floor(b[1] / cellSz); gy <= Math.floor(b[3] / cellSz); gy++) {
      for (const o of grid.get(gx + "," + gy) || []) if (!(b[2] < o[0] || b[0] > o[2] || b[3] < o[1] || b[1] > o[3])) return false;
    }
    return true;
  };
  const occupy = (b) => { for (let gx = Math.floor(b[0] / cellSz); gx <= Math.floor(b[2] / cellSz); gx++) for (let gy = Math.floor(b[1] / cellSz); gy <= Math.floor(b[3] / cellSz); gy++) { const k = gx + "," + gy; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(b); } };
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const icons = S.style === "pixel", k = iconScale(tilePx);
  const iconBoxes = [];
  const freeIcon = (b) => !iconBoxes.some((o) => !(b[2] < o[0] || b[0] > o[2] || b[3] < o[1] || b[1] > o[3]));
  const takeIcon = (b) => iconBoxes.push(b);
  const pins = [];
  for (const B of order) {
    const [x, y] = project(B.x, B.y, B.z); if (x < -60 || y < -60 || x > VW + 60 || y > VH + 60) continue;
    const t = Math.max(1, tierOf(B.b));
    if (icons ? (t === 1 && tilePx < 6) || (t === 2 && tilePx < 2.5) || (t === 3 && tilePx < 1.2) : (t === 1 && tilePx < 3) || (t === 2 && tilePx < 1.2)) continue;
    if (icons) {
      // larger towns first; a smaller town whose buildings would sit mostly on another's waits for a closer zoom
      const ic = burgIcon(B.b), w = ic.w * k, h = ic.h * k, left = x - ic.ax * k, top = y - ic.ay * k;
      const core = [left + w * 0.25, top + h * 0.3, left + w * 0.75, top + h];
      if (S.selBurg !== B.k && !freeIcon(core)) continue;
      takeIcon(core);
      pins.push({ B, x, y, t, ic, top, h, w });
    }
    else { const stem = 7 + t * 3.5, r = 1.8 + t * 0.9; pins.push({ B, x, y, t, stem, r, top: y - stem - r }); }
  }
  for (const p of pins.slice().reverse()) {   // small ones first, so large ones sit on top
    const { B, x, y } = p; const sel = S.selBurg === B.k;
    if (icons) {
      const left = snap(x - p.ic.ax * k), top = snap(p.top);
      c.imageSmoothingEnabled = false; c.drawImage(p.ic.cv, left, top, p.w, p.h);
      if (sel) { c.fillStyle = accent; const a = Math.max(1, Math.round(ART())); c.fillRect(left - a, snap(y) + a, p.w + 2 * a, 2 * a); }
      if (S.show.markets && marketOfBurg.has(B.k)) diamond(c, x, p.top - 7, ink);
      HITS.push({ x, y: p.top + p.h / 2, r: Math.max(8, Math.min(p.w, p.h) / 2 + 2), kind: "burg", o: B });
      continue;
    }
    const { stem, r } = p;
    c.strokeStyle = sel ? accent : ink; c.lineWidth = sel ? 1.8 : 1; c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - stem); c.stroke();
    const flags = B.b.flags || [];
    c.beginPath();
    if (flags.includes("walls")) c.rect(x - r, y - stem - r, 2 * r, 2 * r); else c.arc(x, y - stem, r, 0, Math.PI * 2);
    c.fillStyle = sel ? accent : (DARK() ? "#f0f3f6" : "#ffffff"); c.fill();
    c.lineWidth = flags.includes("port") ? 2 : 1.3; c.strokeStyle = sel ? accent : (flags.includes("port") ? "#2b6cb0" : ink); c.stroke();
    if (flags.includes("capital")) { c.beginPath(); c.arc(x, y - stem, r * 0.45, 0, Math.PI * 2); c.fillStyle = ink; c.fill(); }
    if (S.show.markets && marketOfBurg.has(B.k)) diamond(c, x, y - stem - r - 6, ink);
    HITS.push({ x, y: y - stem, r: Math.max(7, r + 4), kind: "burg", o: B });
  }
  if (!S.show.labels) return;
  const need = { 4: 0, 3: 1.2, 2: 4, 1: 10 };
  for (const p of pins) {
    const { B, x, y, t } = p;
    if (tilePx < need[t] && S.selBurg !== B.k) continue;
    const size = 10.5 + t * 1.4, font = `${t >= 3 ? 700 : 500} ${size}px Alegreya, serif`;
    c.font = font; const w = c.measureText(B.b.name).width;
    const bx = icons ? x + p.w - p.ic.ax * k + 3 : x + 6, by = icons ? p.top + p.h / 2 : y - p.stem;
    const box = [bx - 2, by - size / 2 - 1, bx + w + 2, by + size / 2 + 1];
    if (!free(box)) continue;
    occupy(box);
    halo(c, B.b.name, bx, by, font, S.selBurg === B.k ? accent : ink, "left");
  }
}
function diamond(c, x, yy, ink) {
  c.beginPath(); c.moveTo(x, yy - 4.5); c.lineTo(x + 4.5, yy); c.lineTo(x, yy + 4.5); c.lineTo(x - 4.5, yy); c.closePath();
  c.fillStyle = "#e0a526"; c.fill(); c.lineWidth = 1; c.strokeStyle = ink; c.stroke();
}
// a marker's emoji; image icons and anything unreadable fall back to a dot
const markerIcon = (m) => { const s = m.icon || ""; return !s || /^(https?:|data:|glyph-|\.?\/)/.test(s) ? "•" : s; };
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
    box.append(ul, el("p", { class: "about", text: S.style === "pixel"
      ? `Biome of the cell under each tile centre. The land is banded by height, with bare rock from ${fmtNum(ROCKLINE * hRatio)} ${HU} and snow from ${fmtNum(SNOWLINE * hRatio)} ${HU}; crowded countryside is drawn as fields, and the sea darkens in steps with depth.`
      : "Biome of the cell under each tile centre, lightened with height; the sea darkens with depth." }));
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
  if (DECOR.n) T.append(toggleRow("Trees, rocks and fields", () => sh.decor, (v) => { sh.decor = v; dirty.terrain = true; }));
  T.append(toggleRow("Tile outlines", () => S.outlines, (v) => { S.outlines = v; dirty.terrain = true; }));
  if (META.borders.length) {
    const used = [...new Set(META.borders.map(worstStance))].sort((a, b) => STANCE_RANK.indexOf(a) - STANCE_RANK.indexOf(b));
    T.append(el("p", { class: "sub", text: "Borders by the cooler of the two stances" }),
      el("div", { style: "display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.88rem" },
        used.map((s) => el("span", { style: "display:inline-flex;align-items:center;gap:5px" }, el("span", { class: "sw", style: `background:${STANCE[s] || STANCE.Neutral}` }), s))));
  }
  if (META.burgs.length) T.append(el("p", { class: "sub", id: "burg-key" }));
}
function burgKey() {
  const k = $("#burg-key"); if (!k) return;
  k.textContent = S.style === "pixel"
    ? "Towns: a hut or tent for a hamlet, more houses for villages and towns, a castle flying the state’s colour for a capital; a church for a temple, a tower for a citadel, walls, a boat for a port, shacks for a shanty town, a gold diamond for a market centre."
    : "Pins: taller for capitals and cities, a square head for walls, a blue ring for ports, a dark centre for capitals, a gold diamond for market centres.";
}
burgKey();
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
  $("#style-slot").append(el("p", { class: "sub", text: "Style" }), seg([["pixel", "Pixel art"], ["smooth", "Smooth"]], () => S.style, (v) => { S.style = v; setStyle(); }));
  const V = $("#view");
  const pxRow = el("div", {}, el("p", { class: "sub", text: "Pixel size" }),
    seg([[1, "1"], [2, "2"], [3, "3"], [4, "4"]], () => S.px, (v) => { S.px = v; setStyle(); }));
  V.append(pxRow);
  if (DECOR.n) V.append(slider("Trees and details", 0, 2, 0.1, () => S.detail, (v) => { S.detail = v; dirty.terrain = true; },
    (v) => (v ? `× ${fmtNum(v)}` : "none")).node);
  function setStyle() {
    pxRow.hidden = S.style !== "pixel"; sizeLines(); paint(); burgKey();
    dirty.terrain = dirty.overlay = dirty.fx = true; pickDirty = true;
  }
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
  for (const m of tileMarkers.get(i) || []) ibody.append(el("div", { class: "card" }, el("h4", {}, `${markerIcon(m.m)} ${m.m.name || "Marker"}`, el("small", { text: m.m.type })), m.m.note ? el("p", { class: "note", text: m.m.note }) : null));
  for (const u of tileUnits.get(i) || []) ibody.append(el("div", { class: "card" }, el("h4", {}, `${u.u.icon && !/^(https?:|data:)/.test(u.u.icon) ? u.u.icon + " " : ""}${u.u.name}`, el("small", { text: u.u.state })), el("p", { text: `${fmtNum(u.u.men, true)} ${u.u.naval ? "ships" : "men"}${u.u.comp ? `: ${u.u.comp}` : ""}` })));
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
window.__iso = { S, META, F, inspect, flyTo, paint, focusTrade, filterDeals, pickTile, project, dirty, DECOR, ZFILL: () => ZFILL, sizeLines, ATLAS };
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
