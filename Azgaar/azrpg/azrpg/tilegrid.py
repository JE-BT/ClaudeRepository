"""The tile grid, taken from the map's grid overlay.

Azgaar does not store a grid as data; the overlay is a pattern (src/index.html) transformed by
the saved style options with patternTransform="scale(s) translate(dx dy)", so a pattern point p
lands at s * (p + d). The square pattern is 25 by 25 units with lines at multiples of 25: on
Pyeongak (s = 0.05, dx = -2, dy = 3) squares are 1.25 px, which at 5 mi per px is 6.25 mi, and
the first lines are at x = -0.1, y = 0.15 px. A hex overlay (Lania's pointyHex) is replaced by
squares as wide as its hexes, on the same origin. Without a usable overlay a 5-mile square is
used. Tiles are numbered from the top-left tile that touches the map.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .mapfile import AzgaarMap

PATTERN_SIZE = {"square": 25.0, "squareTruncated": 25.0, "squareTetrakis": 25.0,
                "pointyHex": 25.0, "trihexagonal": 25.0, "flatHex": 25.0}


@dataclass
class TileGrid:
    size: float          # tile edge in map pixels
    ox: float            # map x of the left edge of tile column 0 (<= 0)
    oy: float            # map y of the top edge of tile row 0 (<= 0)
    cols: int
    rows: int
    mi_per_px: float
    source: str          # how the grid was obtained

    @property
    def miles(self) -> float:
        return self.size * self.mi_per_px

    @classmethod
    def from_map(cls, m: AzgaarMap, fallback_miles: float = 5.0) -> "TileGrid":
        width, height = m.settings["graph"]["width"], m.settings["graph"]["height"]
        mi = m.mi_per_px
        opts = {}
        try:
            with open(m.path, encoding="utf-8", newline="") as fh:
                fields = fh.read().split("\r\n")
            opts = json.loads(fields[48]).get("grid", {}).get("options", {})
        except Exception:
            opts = {}
        gtype = opts.get("type")
        if gtype in PATTERN_SIZE and opts.get("scale"):
            s = float(opts["scale"])
            size = PATTERN_SIZE[gtype] * s
            x0, y0 = s * float(opts.get("dx", 0)), s * float(opts.get("dy", 0))
            source = f"grid overlay '{gtype}' at scale {s:g}, offset ({opts.get('dx', 0)}, {opts.get('dy', 0)})"
            if gtype != "square":
                source += f"; squares as wide as the {gtype} cells"
        else:
            size = fallback_miles / mi
            x0 = y0 = 0.0
            source = f"no usable grid overlay; {fallback_miles:g}-mile squares"
        ox = x0 - math.ceil(x0 / size) * size
        oy = y0 - math.ceil(y0 / size) * size
        cols = math.ceil((width - ox) / size)
        rows = math.ceil((height - oy) / size)
        return cls(size, ox, oy, cols, rows, mi, source)

    def centre(self, c: int, r: int) -> tuple[float, float]:
        return self.ox + (c + 0.5) * self.size, self.oy + (r + 0.5) * self.size

    def at(self, x: float, y: float) -> tuple[int, int]:
        c = int(math.floor((x - self.ox) / self.size))
        r = int(math.floor((y - self.oy) / self.size))
        return min(max(c, 0), self.cols - 1), min(max(r, 0), self.rows - 1)

    def to_dict(self) -> dict:
        return {"size": self.size, "ox": self.ox, "oy": self.oy, "cols": self.cols, "rows": self.rows,
                "miles": self.miles, "source": self.source}
