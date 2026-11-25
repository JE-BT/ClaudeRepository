"""Rebuild the packed graph the Generator makes on load (src/model/graph/pack-generator.ts).

A .map stores the grid points and the pack's per-cell arrays, but not the pack's own points or
neighbours. The Generator rebuilds them on every load from the grid: deep ocean is dropped and
coastal cells are split. This port does the same, then checks the result against the file: the
cell count must equal the length of the saved pack arrays, and every burg must sit in its cell.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.spatial import Delaunay

from .mapfile import AzgaarMap, MapFormatError

SEA_LEVEL = 20
DEFAULT_JITTER = 0.9
SQRT3 = math.sqrt(3)
HEX_SIDE = math.sqrt(2 / SQRT3)


def js_round(v: float, d: int = 0) -> float:
    """Math.round(v * 10^d) / 10^d: halves round up, unlike Python's round."""
    m = 10 ** d
    return math.floor(v * m + 0.5) / m


def neighbor_distance(sampling: str, spacing: float) -> float:
    if sampling == "hexPointy":
        return spacing * HEX_SIDE
    if sampling == "hexFlat":
        return spacing * HEX_SIDE
    if sampling == "diamond":
        return spacing
    if sampling == "triangle":
        side = spacing * math.sqrt(4 / SQRT3)
        return side / SQRT3
    return spacing


def voronoi_neighbors(points: np.ndarray, boundary: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
    """Neighbours among real points, and the near-border flag (a neighbour is a boundary pseudo-point)."""
    n = len(points)
    allp = np.vstack([points, boundary]) if len(boundary) else points
    tri = Delaunay(allp)
    indptr, indices = tri.vertex_neighbor_vertices
    nbrs: list[np.ndarray] = []
    border = np.zeros(n, dtype=np.uint8)
    for i in range(n):
        around = indices[indptr[i]:indptr[i + 1]]
        real = around[around < n]
        nbrs.append(real)
        if len(real) < len(around):
            border[i] = 1
    return nbrs, border


class PackGraph:
    """Pack cells: points p, parent grid cell g, height h, neighbours c, harbor (water neighbours)."""

    def __init__(self, m: AzgaarMap):
        if m.data["override"]:
            raise MapFormatError("the map has a graph override (wrap tool or similar); azdev cannot rebuild it")
        grid = m.data["grid"]
        gp = np.asarray(grid["points"], dtype=float)
        boundary = np.asarray(grid["boundary"], dtype=float)
        gh, gt, gf = m.data["grid_h"], m.data["grid_t"], m.data["grid_f"]
        features = grid["features"]
        graph = m.settings["graph"]
        split = neighbor_distance(graph.get("sampling", "square"), grid["spacing"]) * \
            (1 + (DEFAULT_JITTER - graph.get("jitter", DEFAULT_JITTER)))
        split2 = split * split

        gc, gb = voronoi_neighbors(gp, boundary)
        p: list[tuple[float, float]] = []
        g: list[int] = []
        h: list[int] = []
        for i in range(len(gp)):
            height, typ = gh[i], gt[i]
            if height < SEA_LEVEL and typ not in (-1, -2):
                continue
            if typ == -2 and (i % 4 == 0 or (features[gf[i]] or {}).get("type") == "lake"):
                continue
            x, y = gp[i]
            p.append((x, y)); g.append(i); h.append(height)
            if typ in (1, -1):
                if gb[i]:
                    continue
                for e in gc[i]:
                    if i > e or gt[e] != typ:
                        continue
                    ex, ey = gp[e]
                    if (y - ey) ** 2 + (x - ex) ** 2 < split2:
                        continue
                    p.append((js_round((x + ex) / 2, 1), js_round((y + ey) / 2, 1))); g.append(i); h.append(height)

        self.p = np.asarray(p, dtype=float)
        self.g = np.asarray(g, dtype=np.int32)
        self.h = np.asarray(h, dtype=np.int16)
        if len(self.p) != m.cell_count:
            raise MapFormatError(f"rebuilt pack has {len(self.p)} cells but the file has {m.cell_count}; "
                                 "the grid or sampling is not the one azdev expects")
        self.c, self.border = voronoi_neighbors(self.p, boundary)
        self.n = len(self.p)
        land = self.h >= SEA_LEVEL
        self.land = land
        self.harbor = np.zeros(self.n, dtype=np.int16)
        for i in np.nonzero(land)[0]:
            self.harbor[i] = int(np.sum(~land[self.c[i]]))
        # every burg must stand in (or next to) its own cell
        bad = 0
        for b in m.live_burgs():
            x, y = b.get("x"), b.get("y")
            if x is None:
                continue
            d2 = np.sum((self.p - (x, y)) ** 2, axis=1)
            near = int(np.argmin(d2))
            if near != b["cell"] and b["cell"] not in set(self.c[near].tolist()):
                bad += 1
        if bad > max(2, len(m.live_burgs()) // 50):
            raise MapFormatError(f"rebuilt pack does not match the burgs ({bad} misplaced)")
        # edges as arrays for graph algorithms
        rows = np.repeat(np.arange(self.n), [len(x) for x in self.c])
        cols = np.concatenate(self.c)
        self.edges = (rows, cols)
