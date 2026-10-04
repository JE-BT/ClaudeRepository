"""The hex grid drawn by the map's grid overlay.

Azgaar draws the overlay from a pattern (src/index.html, pattern_pointyHex: 25 by 43.4 units,
two rows of pointy-top hexes per tile) transformed by the saved style options:
scale(s) translate(dx dy). Hex centres in pattern units are (25k, 14.45 + 43.4j) and
(12.5 + 25k, 36.15 + 43.4j), so in map pixels a hex is 25*s wide and rows are 21.7*s apart,
odd rows shifted half a hex east. Lania's map uses s = 0.1: hexes 2.5 px (5 miles) across.
If a map has no grid style, a 5-mile grid is assumed.
"""
from __future__ import annotations

import json
import math

PAT_W, PAT_ROW, PAT_Y0 = 25.0, 21.7, 14.45
# odd-r offset neighbours: (dcol, drow) for even and odd rows
NEIGH = {
    "east": ((1, 0), (1, 0)), "west": ((-1, 0), (-1, 0)),
    "northeast": ((0, -1), (1, -1)), "northwest": ((-1, -1), (0, -1)),
    "southeast": ((0, 1), (1, 1)), "southwest": ((-1, 1), (0, 1)),
}


class HexGrid:
    def __init__(self, scale: float, dx: float, dy: float, mi_per_px: float):
        self.s, self.dx, self.dy, self.mi_per_px = scale, dx, dy, mi_per_px
        self.w = PAT_W * scale          # hex width (flat side to flat side), px
        self.row = PAT_ROW * scale      # row spacing, px
        self.x0 = dx * scale            # centre of hex (0, 0)
        self.y0 = (PAT_Y0 + dy) * scale

    @classmethod
    def from_map(cls, m) -> "HexGrid":
        opts = {}
        try:
            with open(m.path, encoding="utf-8", newline="") as fh:
                fields = fh.read().split("\r\n")
            opts = json.loads(fields[48]).get("grid", {}).get("options", {})
        except Exception:
            pass
        if opts.get("type", "pointyHex") != "pointyHex" or not opts.get("scale"):
            return cls(5 / (PAT_W * m.mi_per_px), 0, 0, m.mi_per_px)
        return cls(float(opts["scale"]), float(opts.get("dx", 0)), float(opts.get("dy", 0)), m.mi_per_px)

    @property
    def miles(self) -> float:
        return self.w * self.mi_per_px

    def centre(self, h: tuple[int, int]) -> tuple[float, float]:
        col, row = h
        return self.x0 + col * self.w + (self.w / 2 if row % 2 else 0), self.y0 + row * self.row

    def at(self, x: float, y: float) -> tuple[int, int]:
        r0 = round((y - self.y0) / self.row)
        best, bd = None, math.inf
        for row in (r0 - 1, r0, r0 + 1):
            shift = self.w / 2 if row % 2 else 0
            col = round((x - self.x0 - shift) / self.w)
            for c in (col - 1, col, col + 1):
                cx, cy = self.centre((c, row))
                d = (cx - x) ** 2 + (cy - y) ** 2
                if d < bd:
                    best, bd = (c, row), d
        return best

    def neighbour(self, h: tuple[int, int], direction: str) -> tuple[int, int]:
        dc, dr = NEIGH[direction][h[1] % 2]
        return h[0] + dc, h[1] + dr

    def neighbours(self, h) -> dict[str, tuple[int, int]]:
        return {d: self.neighbour(h, d) for d in NEIGH}

    def direction(self, a, b) -> str:
        """The neighbour direction from hex a that best points at hex b."""
        (ax, ay), (bx, by) = self.centre(a), self.centre(b)
        ang = math.degrees(math.atan2(ay - by, bx - ax)) % 360
        dirs = {"east": 0, "northeast": 60, "northwest": 120, "west": 180, "southwest": 240, "southeast": 300}
        return min(dirs, key=lambda d: min(abs(ang - dirs[d]), 360 - abs(ang - dirs[d])))

    def line(self, points) -> list[tuple[int, int]]:
        """Hexes a polyline passes through, in order, without repeats."""
        out = []
        step = self.w / 4
        for a, b in zip(points, points[1:]):
            n = max(1, int(math.dist(a[:2], b[:2]) / step))
            for k in range(n + 1):
                h = self.at(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                if not out or out[-1] != h:
                    out.append(h)
        return out

    @staticmethod
    def key(h) -> str:
        return f"{h[0]},{h[1]}"

    @staticmethod
    def parse(key: str) -> tuple[int, int]:
        c, r = key.split(",")
        return int(c), int(r)
