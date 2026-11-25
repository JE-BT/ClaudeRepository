"""Exact port of Delaunator 5.1.0 and of the Generator's Voronoi neighbour lists.

The Generator (1.158) triangulates with delaunator 5.1.0, whose orientation test is robust-predicates
3.0.3's orient2d, and then reads each cell's neighbours by walking the half-edges around its point
(src/model/graph/voronoi.ts). The order of those neighbours decides how coastal grid cells are split
into pack cells, so a different triangulation library (scipy, Qhull) numbers some pack cells
differently. This port does every floating-point operation in the same order as the JavaScript, so it
returns the same triangles, half-edges and neighbour order.

orient2d is used only by its sign. Where the double-precision estimate is not certain, the sign is
taken from exact rational arithmetic, which is what robust-predicates' adaptive stage returns.

Delaunator: ISC License, Copyright (c) 2021, Mapbox.
Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is
hereby granted, provided that the above copyright notice and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE
INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF
USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
robust-predicates: public domain (Unlicense).
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Sequence

EPSILON = 2.0 ** -52
EDGE_STACK_SIZE = 512

_EPS = 1.1102230246251565e-16  # robust-predicates util.epsilon
_CCW_ERRBOUND_A = (3 + 16 * _EPS) * _EPS


def orient2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    """robust-predicates orient2d: same sign as (ay - cy)(bx - cx) - (ax - cx)(by - cy), exactly."""
    detleft = (ay - cy) * (bx - cx)
    detright = (ax - cx) * (by - cy)
    det = detleft - detright
    detsum = abs(detleft + detright)
    if abs(det) >= _CCW_ERRBOUND_A * detsum:
        return det
    fax, fay, fbx, fby, fcx, fcy = (Fraction(v) for v in (ax, ay, bx, by, cx, cy))
    exact = (fay - fcy) * (fbx - fcx) - (fax - fcx) * (fby - fcy)
    return 1.0 if exact > 0 else -1.0 if exact < 0 else 0.0


def _pseudo_angle(dx: float, dy: float) -> float:
    p = dx / (abs(dx) + abs(dy))
    return (3 - p if dy > 0 else 1 + p) / 4


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    dx = ax - bx
    dy = ay - by
    return dx * dx + dy * dy


def _in_circle(ax, ay, bx, by, cx, cy, px, py) -> bool:
    dx = ax - px
    dy = ay - py
    ex = bx - px
    ey = by - py
    fx = cx - px
    fy = cy - py
    ap = dx * dx + dy * dy
    bp = ex * ex + ey * ey
    cp = fx * fx + fy * fy
    return dx * (ey * cp - bp * fy) - dy * (ex * cp - bp * fx) + ap * (ex * fy - ey * fx) < 0


def _circumradius(ax, ay, bx, by, cx, cy) -> float:
    dx = bx - ax
    dy = by - ay
    ex = cx - ax
    ey = cy - ay
    bl = dx * dx + dy * dy
    cl = ex * ex + ey * ey
    den = dx * ey - dy * ex
    if den == 0:
        return math.inf  # JS gives Infinity or NaN here; neither is ever a new minimum
    d = 0.5 / den
    x = (ey * bl - dy * cl) * d
    y = (dx * cl - ex * bl) * d
    return x * x + y * y


def _circumcenter(ax, ay, bx, by, cx, cy) -> tuple[float, float]:
    dx = bx - ax
    dy = by - ay
    ex = cx - ax
    ey = cy - ay
    bl = dx * dx + dy * dy
    cl = ex * ex + ey * ey
    d = 0.5 / (dx * ey - dy * ex)
    return ax + (ey * bl - dy * cl) * d, ay + (dx * cl - ex * bl) * d


def _quicksort(ids: list[int], dists: list[float], left: int, right: int) -> None:
    if right - left <= 20:
        for i in range(left + 1, right + 1):
            temp = ids[i]
            temp_dist = dists[temp]
            j = i - 1
            while j >= left and dists[ids[j]] > temp_dist:
                ids[j + 1] = ids[j]
                j -= 1
            ids[j + 1] = temp
        return
    median = (left + right) >> 1
    i = left + 1
    j = right
    ids[median], ids[i] = ids[i], ids[median]
    if dists[ids[left]] > dists[ids[right]]:
        ids[left], ids[right] = ids[right], ids[left]
    if dists[ids[i]] > dists[ids[right]]:
        ids[i], ids[right] = ids[right], ids[i]
    if dists[ids[left]] > dists[ids[i]]:
        ids[left], ids[i] = ids[i], ids[left]
    temp = ids[i]
    temp_dist = dists[temp]
    while True:
        i += 1
        while dists[ids[i]] < temp_dist:
            i += 1
        j -= 1
        while dists[ids[j]] > temp_dist:
            j -= 1
        if j < i:
            break
        ids[i], ids[j] = ids[j], ids[i]
    ids[left + 1] = ids[j]
    ids[j] = temp
    if right - i + 1 >= j - left:
        _quicksort(ids, dists, i, right)
        _quicksort(ids, dists, left, j - 1)
    else:
        _quicksort(ids, dists, left, j - 1)
        _quicksort(ids, dists, i, right)


class Delaunator:
    """Delaunator 5.1.0. `triangles` and `halfedges` are plain lists, as long as JS's trimmed arrays."""

    @classmethod
    def from_points(cls, points: Sequence[Sequence[float]]) -> "Delaunator":
        coords: list[float] = []
        for x, y in points:
            coords.append(float(x))
            coords.append(float(y))
        return cls(coords)

    def __init__(self, coords: list[float]):
        n = len(coords) >> 1
        self.coords = coords
        max_triangles = max(2 * n - 5, 0)
        self._triangles = [0] * (max_triangles * 3)
        self._halfedges = [0] * (max_triangles * 3)
        self._hash_size = math.ceil(math.sqrt(n))
        self._hull_prev = [0] * n
        self._hull_next = [0] * n
        self._hull_tri = [0] * n
        self._hull_hash = [-1] * self._hash_size
        self._ids = [0] * n
        self._dists = [0.0] * n
        self._edge_stack = [0] * EDGE_STACK_SIZE
        self.triangles_len = 0
        self._cx = 0.0
        self._cy = 0.0
        self._hull_start = 0
        self.hull: list[int] = []
        self.triangles: list[int] = []
        self.halfedges: list[int] = []
        self._update()

    def _hash_key(self, x: float, y: float) -> int:
        return math.floor(_pseudo_angle(x - self._cx, y - self._cy) * self._hash_size) % self._hash_size

    def _update(self) -> None:
        coords = self.coords
        hull_prev, hull_next, hull_tri, hull_hash = self._hull_prev, self._hull_next, self._hull_tri, self._hull_hash
        n = len(coords) >> 1
        ids, dists = self._ids, self._dists

        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        for i in range(n):
            x = coords[2 * i]
            y = coords[2 * i + 1]
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
            ids[i] = i
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2

        i0 = i1 = i2 = 0
        min_dist = math.inf
        for i in range(n):
            d = _dist(cx, cy, coords[2 * i], coords[2 * i + 1])
            if d < min_dist:
                i0 = i
                min_dist = d
        i0x = coords[2 * i0]
        i0y = coords[2 * i0 + 1]

        min_dist = math.inf
        for i in range(n):
            if i == i0:
                continue
            d = _dist(i0x, i0y, coords[2 * i], coords[2 * i + 1])
            if d < min_dist and d > 0:
                i1 = i
                min_dist = d
        i1x = coords[2 * i1]
        i1y = coords[2 * i1 + 1]

        min_radius = math.inf
        for i in range(n):
            if i == i0 or i == i1:
                continue
            r = _circumradius(i0x, i0y, i1x, i1y, coords[2 * i], coords[2 * i + 1])
            if r < min_radius:
                i2 = i
                min_radius = r
        i2x = coords[2 * i2]
        i2y = coords[2 * i2 + 1]

        if min_radius == math.inf:
            # collinear input: the hull is the points ordered along the line, and there are no triangles
            for i in range(n):
                dists[i] = (coords[2 * i] - coords[0]) or (coords[2 * i + 1] - coords[1])
            _quicksort(ids, dists, 0, n - 1)
            hull = []
            d0 = -math.inf
            for i in range(n):
                pid = ids[i]
                d = dists[pid]
                if d > d0:
                    hull.append(pid)
                    d0 = d
            self.hull = hull
            self.triangles = []
            self.halfedges = []
            return

        if orient2d(i0x, i0y, i1x, i1y, i2x, i2y) < 0:
            i1, i2 = i2, i1
            i1x, i2x = i2x, i1x
            i1y, i2y = i2y, i1y

        ccx, ccy = _circumcenter(i0x, i0y, i1x, i1y, i2x, i2y)
        self._cx = ccx
        self._cy = ccy
        for i in range(n):
            dists[i] = _dist(coords[2 * i], coords[2 * i + 1], ccx, ccy)
        _quicksort(ids, dists, 0, n - 1)

        self._hull_start = i0
        hull_size = 3
        hull_next[i0] = hull_prev[i2] = i1
        hull_next[i1] = hull_prev[i0] = i2
        hull_next[i2] = hull_prev[i1] = i0
        hull_tri[i0] = 0
        hull_tri[i1] = 1
        hull_tri[i2] = 2
        for k in range(self._hash_size):
            hull_hash[k] = -1
        hull_hash[self._hash_key(i0x, i0y)] = i0
        hull_hash[self._hash_key(i1x, i1y)] = i1
        hull_hash[self._hash_key(i2x, i2y)] = i2

        self.triangles_len = 0
        self._add_triangle(i0, i1, i2, -1, -1, -1)

        hash_size = self._hash_size
        add_triangle = self._add_triangle
        legalize = self._legalize
        xp = yp = 0.0
        for k in range(n):
            i = ids[k]
            x = coords[2 * i]
            y = coords[2 * i + 1]

            # skip near-duplicate points
            if k > 0 and abs(x - xp) <= EPSILON and abs(y - yp) <= EPSILON:
                continue
            xp = x
            yp = y

            # skip seed triangle points
            if i == i0 or i == i1 or i == i2:
                continue

            # find a visible edge on the convex hull using edge hash
            start = 0
            key = self._hash_key(x, y)
            for j in range(hash_size):
                start = hull_hash[(key + j) % hash_size]
                if start != -1 and start != hull_next[start]:
                    break

            start = hull_prev[start]
            e = start
            while True:
                q = hull_next[e]
                if not orient2d(x, y, coords[2 * e], coords[2 * e + 1], coords[2 * q], coords[2 * q + 1]) >= 0:
                    break
                e = q
                if e == start:
                    e = -1
                    break
            if e == -1:
                continue  # likely a near-duplicate point; skip it

            # add the first triangle from the point
            t = add_triangle(e, i, hull_next[e], -1, -1, hull_tri[e])

            # recursively flip triangles from the point until they satisfy the Delaunay condition
            hull_tri[i] = legalize(t + 2)
            hull_tri[e] = t
            hull_size += 1

            # walk forward through the hull, adding more triangles and flipping recursively
            nn = hull_next[e]
            while True:
                q = hull_next[nn]
                if not orient2d(x, y, coords[2 * nn], coords[2 * nn + 1], coords[2 * q], coords[2 * q + 1]) < 0:
                    break
                t = add_triangle(nn, i, q, hull_tri[i], -1, hull_tri[nn])
                hull_tri[i] = legalize(t + 2)
                hull_next[nn] = nn  # mark as removed
                hull_size -= 1
                nn = q

            # walk backward from the other side, adding more triangles and flipping
            if e == start:
                while True:
                    q = hull_prev[e]
                    if not orient2d(x, y, coords[2 * q], coords[2 * q + 1], coords[2 * e], coords[2 * e + 1]) < 0:
                        break
                    t = add_triangle(q, i, e, -1, hull_tri[e], hull_tri[q])
                    legalize(t + 2)
                    hull_tri[q] = t
                    hull_next[e] = e  # mark as removed
                    hull_size -= 1
                    e = q

            # update the hull indices
            self._hull_start = hull_prev[i] = e
            hull_next[e] = hull_prev[nn] = i
            hull_next[i] = nn

            # save the two new edges in the hash table
            hull_hash[self._hash_key(x, y)] = i
            hull_hash[self._hash_key(coords[2 * e], coords[2 * e + 1])] = e

        hull = []
        e = self._hull_start
        for _ in range(hull_size):
            hull.append(e)
            e = hull_next[e]
        self.hull = hull
        self.triangles = self._triangles[:self.triangles_len]
        self.halfedges = self._halfedges[:self.triangles_len]

    def _legalize(self, a: int) -> int:
        triangles, halfedges, coords = self._triangles, self._halfedges, self.coords
        stack = self._edge_stack
        link = self._link
        i = 0
        ar = 0
        while True:
            b = halfedges[a]
            a0 = a - a % 3
            ar = a0 + (a + 2) % 3

            if b == -1:  # convex hull edge
                if i == 0:
                    break
                i -= 1
                a = stack[i]
                continue

            b0 = b - b % 3
            al = a0 + (a + 1) % 3
            bl = b0 + (b + 2) % 3

            p0 = triangles[ar]
            pr = triangles[a]
            pl = triangles[al]
            p1 = triangles[bl]

            illegal = _in_circle(
                coords[2 * p0], coords[2 * p0 + 1],
                coords[2 * pr], coords[2 * pr + 1],
                coords[2 * pl], coords[2 * pl + 1],
                coords[2 * p1], coords[2 * p1 + 1])

            if illegal:
                triangles[a] = p1
                triangles[b] = p0

                hbl = halfedges[bl]

                # edge swapped on the other side of the hull (rare); fix the half-edge reference
                if hbl == -1:
                    e = self._hull_start
                    while True:
                        if self._hull_tri[e] == bl:
                            self._hull_tri[e] = a
                            break
                        e = self._hull_prev[e]
                        if e == self._hull_start:
                            break
                link(a, hbl)
                link(b, halfedges[ar])
                link(ar, bl)

                br = b0 + (b + 1) % 3
                if i < EDGE_STACK_SIZE:
                    stack[i] = br
                    i += 1
            else:
                if i == 0:
                    break
                i -= 1
                a = stack[i]
        return ar

    def _link(self, a: int, b: int) -> None:
        self._halfedges[a] = b
        if b != -1:
            self._halfedges[b] = a

    def _add_triangle(self, i0: int, i1: int, i2: int, a: int, b: int, c: int) -> int:
        t = self.triangles_len
        self._triangles[t] = i0
        self._triangles[t + 1] = i1
        self._triangles[t + 2] = i2
        self._link(t, a)
        self._link(t + 1, b)
        self._link(t + 2, c)
        self.triangles_len += 3
        return t


def voronoi_cells(delaunay: Delaunator, points_n: int) -> tuple[list[list[int]], list[int]]:
    """Neighbours and near-border flags as the Generator's Voronoi class makes them (voronoi.ts).

    For each point, the first incoming half-edge in index order starts a walk round the point; the
    neighbours are the walk's start vertices that are real points (not boundary pseudo-points), in walk
    order, capped at 20 edges. A cell is near-border when the walk met a pseudo-point or the hull.
    """
    triangles, halfedges = delaunay.triangles, delaunay.halfedges
    c: list[list[int] | None] = [None] * points_n
    b = [0] * points_n
    for e in range(len(triangles)):
        p = triangles[e - 2 if e % 3 == 2 else e + 1]
        if p < points_n and c[p] is None:
            edges = []
            incoming = e
            while True:
                edges.append(incoming)
                outgoing = incoming - 2 if incoming % 3 == 2 else incoming + 1
                incoming = halfedges[outgoing]
                if incoming == -1 or incoming == e or len(edges) >= 20:
                    break
            real = [triangles[x] for x in edges if triangles[x] < points_n]
            c[p] = real
            b[p] = 1 if len(edges) > len(real) else 0
    return [x if x is not None else [] for x in c], b
