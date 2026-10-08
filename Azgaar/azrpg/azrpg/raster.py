"""Put the world on the tile grid.

Every tile gets one pack cell, read from the cell polygons at the tile centre. Land and water are
taken from the smoothed coast and lake outlines the user sees in Azgaar (svgpaths); where a tile's
polygon cell disagrees (a land tile whose cell is sea, or the reverse), the tile is given the
nearest cell of the right kind among the cell's neighbours, so the data shown for a tile always
matches what it looks like. Burg tiles are pinned to their burg's cell.

Elevation per tile is interpolated (bilinear) from the 10,000-odd grid heights, with a little
seeded noise on land, and clamped to agree with land and water: this is mixed data (the heights
are the map's, the values between grid points are not). Temperature and precipitation are read
per tile from the grid cell under it, which is how Azgaar's own cell panel reads them.

Rivers follow their cell sequence (source to mouth) through cell centroids, smoothed; routes
follow their stored point lists. Both are drawn as 4-connected tile chains, and every step
records a connection (N=1, E=2, S=4, W=8) on both tiles, so the renderer draws exactly the links
the data implies and parallel routes do not merge.
"""
from __future__ import annotations

import math
import random
from collections import deque

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from .cells import CellGeo
from .mapfile import AzgaarMap, split_fields
from .svgpaths import feature_paths, flatten
from .tilegrid import TileGrid

N, E, S, W = 1, 2, 4, 8
DIRS = ((0, -1, N, S), (1, 0, E, W), (0, 1, S, N), (-1, 0, W, E))


class Raster:
    def __init__(self, m: AzgaarMap, geo: CellGeo, grid: TileGrid, seed: int = 0):
        self.m, self.geo, self.g = m, geo, grid
        self.seed = seed
        self.report: dict = {}
        shape = (grid.rows, grid.cols)
        self.cell = np.zeros(shape, np.uint16)
        self.land = np.zeros(shape, bool)
        self.height = np.zeros(shape, np.uint8)
        self.conn_route = np.zeros(shape, np.uint8)   # roads bits 0-3, trails bits 4-7
        self.conn_water = np.zeros(shape, np.uint8)   # sea routes bits 0-3, rivers bits 4-7
        self.river = np.zeros(shape, np.uint16)       # river id
        self.route = np.zeros(shape, np.uint16)       # primary route index + 1
        self.cell_feature: list[int] = []

    # ------------------------------------------------------------------ helpers
    def _tc(self, x: float, y: float) -> tuple[float, float]:
        """Map pixels to tile-space coordinates with tile centres on integers (for PIL)."""
        g = self.g
        return (x - g.ox) / g.size - 0.5, (y - g.oy) / g.size - 0.5

    def build(self) -> "Raster":
        self._cells()
        self._features()
        self._landmask()
        self._reconcile()
        self._heights()
        self._rivers()
        self._routes()
        return self

    # ------------------------------------------------------------------ cells
    def _cells(self) -> None:
        g = self.g
        img = Image.new("I", (g.cols, g.rows), 0)
        dr = ImageDraw.Draw(img)
        for i, ring in self.geo.rings.items():
            dr.polygon([self._tc(x, y) for x, y in ring], fill=i + 1)
        arr = np.array(img, dtype=np.int64)
        missing = arr == 0
        if missing.any():  # map edges or slivers: nearest filled tile
            idx = ndimage.distance_transform_edt(missing, return_distances=False, return_indices=True)
            arr = arr[idx[0], idx[1]]
        self.cell = (arr - 1).astype(np.uint16)
        self.report["tiles"] = int(g.cols * g.rows)

    def _features(self) -> None:
        """Feature id per pack cell, flood-filled from each feature's first cell."""
        n = len(self.geo)
        fid = [0] * n
        typ = [self.geo.props[i].get("type") for i in range(n)]
        for f in self.m.live("features"):
            start = f.get("firstCell")
            if start is None or start >= n:
                continue
            want = typ[start]
            q = deque([start])
            fid[start] = f["i"]
            while q:
                c = q.popleft()
                for nb in self.geo.neighbors[c]:
                    if not fid[nb] and typ[nb] == want:
                        fid[nb] = f["i"]
                        q.append(nb)
        self.cell_feature = fid

    def _landmask(self) -> None:
        g = self.g
        svg = self.m_fields()[5]
        paths = feature_paths(svg)
        feats = {f["i"]: f for f in self.m.live("features")}
        img = Image.new("L", (g.cols, g.rows), 0)
        dr = ImageDraw.Draw(img)
        used = 0
        # islands, then lakes, then islands inside lakes
        def order(f):
            if f.get("land"):
                return 2 if f.get("subtype") == "lake_island" or f.get("group") == "lake_island" else 0
            return 1
        for f in sorted(feats.values(), key=order):
            d = paths.get(f["i"])
            if not d or f.get("type") == "ocean":
                continue
            fill = 1 if f.get("land") else 0
            for ring in flatten(d):
                dr.polygon([self._tc(x, y) for x, y in ring], fill=fill)
            used += 1
        if used:
            self.land = np.array(img, dtype=np.uint8) > 0
            self.report["coast"] = f"smoothed outlines of {used} features"
        else:  # no outlines: fall back to the polygons
            water = np.array([self.geo.is_water(i) for i in range(len(self.geo))])
            self.land = ~water[self.cell]
            self.report["coast"] = "cell polygons (no feature outlines found)"

    def m_fields(self) -> list[str]:
        if not hasattr(self, "_fields"):
            with open(self.m.path, encoding="utf-8", newline="") as fh:
                self._fields = split_fields(fh.read())
        return self._fields

    def _reconcile(self) -> None:
        g, geo = self.g, self.geo
        water = np.array([geo.is_water(i) for i in range(len(geo))])
        cell_land = ~water[self.cell]
        bad = np.argwhere(cell_land != self.land)
        moved = flipped = 0
        for r, c in bad:
            want_land = bool(self.land[r, c])
            x, y = g.centre(c, r)
            here = int(self.cell[r, c])
            ring1 = geo.neighbors[here]
            cands = [n for n in ring1 if water[n] != want_land]
            if not cands:
                ring2 = {nn for n in ring1 for nn in geo.neighbors[n]}
                cands = [n for n in ring2 if water[n] != want_land]
            if cands:
                self.cell[r, c] = geo.nearest(x, y, cands)
                moved += 1
            else:
                self.land[r, c] = not want_land
                flipped += 1
        # burgs sit on their own cell, on land
        pinned = 0
        for b in self.m.live_burgs():
            c, r = g.at(b["x"], b["y"])
            if self.cell[r, c] != b["cell"] or not self.land[r, c]:
                pinned += 1
            self.cell[r, c] = b["cell"]
            self.land[r, c] = True
        self.report["reconciled"] = {"coast tiles given a neighbouring cell": moved,
                                     "tiles flipped to match their cell": flipped,
                                     "burg tiles pinned": pinned}

    # ------------------------------------------------------------------ heights
    def _heights(self) -> None:
        g = self.g
        gd = self.m.data["grid"]
        sp, cx, cy = gd["spacing"], gd["cellsX"], gd["cellsY"]
        gh = np.array(self.m.data["grid_h"], dtype=np.float32).reshape(cy, cx)
        cols, rows = np.meshgrid(np.arange(g.cols), np.arange(g.rows))
        x = g.ox + (cols + 0.5) * g.size
        y = g.oy + (rows + 0.5) * g.size
        fx = np.clip(x / sp - 0.5, 0, cx - 1.001)
        fy = np.clip(y / sp - 0.5, 0, cy - 1.001)
        x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
        tx, ty = fx - x0, fy - y0
        h = (gh[y0, x0] * (1 - tx) * (1 - ty) + gh[y0, x0 + 1] * tx * (1 - ty)
             + gh[y0 + 1, x0] * (1 - tx) * ty + gh[y0 + 1, x0 + 1] * tx * ty)
        noise = self._value_noise(g.rows, g.cols, scale=4.0) * 2.5 + self._value_noise(g.rows, g.cols, scale=1.6) * 1.2
        h = np.where(self.land, h + noise * np.clip((h - 20) / 10, 0.3, 1.0), h)
        h = np.where(self.land, np.clip(h, 20, 100), np.clip(h, 0, 19))
        self.height = np.round(h).astype(np.uint8)

    def _value_noise(self, rows: int, cols: int, scale: float) -> np.ndarray:
        rng = np.random.default_rng(self.seed + int(scale * 1000))
        gr, gc = int(rows / scale) + 3, int(cols / scale) + 3
        base = rng.uniform(-1, 1, (gr, gc)).astype(np.float32)
        return ndimage.zoom(base, (rows / (gr - 2), cols / (gc - 2)), order=3)[:rows, :cols]

    # ------------------------------------------------------------------ lines
    def _chain(self, pts: list[tuple[float, float]]) -> list[tuple[int, int]]:
        """Tiles along a polyline, 4-connected, without repeats in a row."""
        g = self.g
        out: list[tuple[int, int]] = []
        for k in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            steps = max(1, int(math.dist((x0, y0), (x1, y1)) / (g.size * 0.25)))
            for s in range(steps + 1):
                t = s / steps
                tile = g.at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
                if not out:
                    out.append(tile)
                elif tile != out[-1]:
                    pc, pr = out[-1]
                    if tile[0] != pc and tile[1] != pr:  # diagonal step: go round a corner
                        out.append((tile[0], pr))
                    out.append(tile)
        # drop immediate back-and-forth
        clean: list[tuple[int, int]] = []
        for t in out:
            if len(clean) >= 2 and clean[-2] == t:
                clean.pop()
                continue
            if not clean or clean[-1] != t:
                clean.append(t)
        return clean

    def _link(self, arr: np.ndarray, chain, shift: int) -> None:
        for (c0, r0), (c1, r1) in zip(chain, chain[1:]):
            for dc, dr, a, b in DIRS:
                if c1 - c0 == dc and r1 - r0 == dr:
                    arr[r0, c0] |= a << shift
                    arr[r1, c1] |= b << shift

    @staticmethod
    def _chaikin(pts, rounds=2):
        for _ in range(rounds):
            if len(pts) < 3:
                return pts
            new = [pts[0]]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                new += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
            new.append(pts[-1])
            pts = new
        return pts

    @staticmethod
    def _meander(pts, rnd, levels=2, amp=0.22):
        """Midpoint displacement across each segment: bends between the cell centroids."""
        for _ in range(levels):
            new = [pts[0]]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                dx, dy = x1 - x0, y1 - y0
                off = rnd.uniform(-amp, amp)
                new.append(((x0 + x1) / 2 - dy * off, (y0 + y1) / 2 + dx * off))
                new.append((x1, y1))
            pts = new
            amp *= 0.6
        return pts

    def _rivers(self) -> None:
        geo, n = self.geo, 0
        rivers = sorted(self.m.data["rivers"], key=lambda r: r.get("discharge", 0))
        for rv in rivers:  # small first, so the larger river owns shared tiles
            cells = [c for c in rv.get("cells", []) if 0 <= c < len(geo)]
            if len(cells) < 2:
                continue
            rnd = random.Random(f"{self.seed}-river-{rv['i']}")
            pts = []
            for k, c in enumerate(cells):
                x, y = geo.centroid[c]
                if 0 < k < len(cells) - 1:  # a little meander, never at the ends
                    j = self.g.size * 1.2
                    x += rnd.uniform(-j, j)
                    y += rnd.uniform(-j, j)
                pts.append((x, y))
            chain = self._chain(self._chaikin(self._meander(pts, rnd)))
            # stop where the river reaches the sea; a river runs on through a lake and out the
            # other side (Azgaar keeps one river id across lakes, e.g. Nouileland's Whitfall)
            cut = len(chain)
            for k, (c, r) in enumerate(chain):
                if k > 0 and not self.land[r, c] and self.geo.props[int(self.cell[r, c])].get("type") == "ocean":
                    cut = k + 1
                    break
            chain = chain[:cut]
            self._link(self.conn_water, chain, 4)
            for c, r in chain:
                if self.land[r, c]:
                    self.river[r, c] = rv["i"]
            n += 1
        self.report["rivers drawn"] = n

    def _routes(self) -> None:
        rank = {"roads": 3, "trails": 2, "searoutes": 1}
        prio = np.zeros_like(self.route, dtype=np.uint8)
        counts: dict[str, int] = {}
        for idx, rt in enumerate(self.m.data["routes"]):
            if not isinstance(rt, dict) or rt.get("removed") or len(rt.get("points", [])) < 2:
                continue
            group = rt.get("group", "roads")
            chain = self._chain([(p[0], p[1]) for p in rt["points"]])
            if group == "searoutes":
                self._link(self.conn_water, chain, 0)
            else:
                self._link(self.conn_route, chain, 0 if group == "roads" else 4)
            pr = rank.get(group, 1)
            for c, r in chain:
                if pr > prio[r, c]:
                    prio[r, c] = pr
                    self.route[r, c] = idx + 1
            counts[group] = counts.get(group, 0) + 1
        self.report["routes drawn"] = counts
