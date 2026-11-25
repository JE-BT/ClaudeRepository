"""How links are drawn on the board, so that every line visibly runs from one stop to the next.

The network contracts Azgaar's route graph with a network Voronoi: each stop owns the route cells
nearest to it, and a link runs from one stop through its own cells, across the boundary, and through
the other stop's cells. Two links from the same stop therefore share water near that stop and then
fork. Drawn as they are, a fork at sea looks like a junction where a ship could turn, and the short
branch looks like a detour, although the rules (and every commission's stop count) say the voyage
calls at the stop. Two drawing styles:

  offset     (default) each link keeps its own line: where links share water they run side by side,
             ordered so that they never cross, and they meet only at their stops
  geo        the shared paths as they are (the older boards)

In the offset style a line that passes a stop it does not serve bows around that stop's symbol.
"""
from __future__ import annotations

import math


def _k(p):
    return (round(p[0], 1), round(p[1], 1))


def densify(pts, step=2.5):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.dist((x0, y0), (x1, y1)) / step))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return out


def chaikin(pts, rounds=2):
    for _ in range(rounds):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        out.append(pts[-1])
        pts = out
    return pts


def _unit(dx, dy):
    L = math.hypot(dx, dy)
    return (dx / L, dy / L) if L else (0.0, 0.0)


# ---------------------------------------------------------------------- offset bundles
def smooth(pts, w: int = 2, rounds: int = 2):
    """Moving average over +-w vertices, ends fixed. Two links that share a stretch of cells get the
    same smoothed points along it (up to w vertices before they part), so bundles still line up."""
    pts = list(pts)
    for _ in range(rounds):
        n = len(pts)
        if n < 3:
            return pts
        out = [pts[0]]
        for i in range(1, n - 1):
            lo, hi = max(0, i - w), min(n, i + w + 1)
            out.append((sum(p[0] for p in pts[lo:hi]) / (hi - lo), sum(p[1] for p in pts[lo:hi]) / (hi - lo)))
        out.append(pts[-1])
        pts = out
    return pts


def offset_paths(links: dict, gap: float = 3.0, taper: float = 14.0) -> dict:
    """links: key -> Link (points from a to b). Returns key -> offset polyline (same vertices).

    For each stop, the paths of its sea links, read outwards from the stop, form a tree. Every edge of
    the tree carries the links below it; they are laid side by side in the left-to-right order of
    where they branch off, so lines never cross inside a bundle. Offsets are measured to the right of
    the direction of travel away from the root stop."""
    base = {k: smooth(ln.points) for k, ln in links.items()}  # cell-to-cell zigzags would knot the bundles
    seq = {k: [_k(p) for p in base[k]] for k, ln in links.items()}
    seg_off: dict[tuple, dict[int, float]] = {k: {} for k in links}  # key -> segment index (a->b) -> offset
    by_stop: dict[int, list] = {}
    for k, ln in links.items():
        by_stop.setdefault(ln.a, []).append(k)
        by_stop.setdefault(ln.b, []).append(k)
    for root, keys in by_stop.items():
        if len(keys) < 2:
            continue
        # orient each path away from the root
        paths = {}
        for k in keys:
            s = seq[k]
            paths[k] = s if links[k].a == root else s[::-1]
        # trie of point sequences: node = (depth, point); children by next point
        children: dict[tuple, dict] = {}
        through: dict[tuple, list] = {}  # edge (parent node, child node) -> links
        for k, s in paths.items():
            node = (0, s[0])
            for d in range(1, len(s)):
                child = (d, s[d])
                children.setdefault(node, {})[child] = True
                through.setdefault((node, child), []).append(k)
                node = child

        memo: dict[tuple, list] = {}

        def order(node, din):
            """Links below a node, left to right (a trie node has one parent, so the node fixes din)."""
            if node in memo:
                return list(memo[node])
            memo[node] = _order(node, din)
            return list(memo[node])

        def _order(node, din):
            kids = list(children.get(node, {}))
            if not kids:
                return []
            p = node[1]

            def turn(c):
                dc = _unit(c[1][0] - p[0], c[1][1] - p[1])
                if din is None:
                    return math.atan2(dc[1], dc[0])
                return math.atan2(din[0] * dc[1] - din[1] * dc[0], din[0] * dc[0] + din[1] * dc[1])
            out = []
            for c in sorted(kids, key=turn):
                below = order(c, _unit(c[1][0] - p[0], c[1][1] - p[1]))
                for k in through[(node, c)]:  # links that end exactly here (none in practice) keep their place
                    if k not in below:
                        below.append(k)
                out += below
            return out

        cache: dict[tuple, list] = {}

        def lineup(parent, child):
            key = (parent, child)
            if key not in cache:
                din = _unit(child[1][0] - parent[1][0], child[1][1] - parent[1][1])
                below = order(child, din)
                ks = [k for k in below if k in through[key]] or list(through[key])
                for k in through[key]:
                    if k not in ks:
                        ks.append(k)
                cache[key] = ks
            return cache[key]

        for (parent, child), ks in through.items():
            if len(ks) < 2:
                continue
            ks = lineup(parent, child)
            n = len(ks)
            for j, k in enumerate(ks):
                o = (j - (n - 1) / 2) * gap
                d = child[0] - 1  # segment index counted from the root
                L = len(seq[k]) - 1
                if links[k].a == root:
                    i, sign = d, 1.0
                else:
                    i, sign = L - 1 - d, -1.0  # reversed: the right of travel flips
                cur = seg_off[k].get(i)
                if cur is None or abs(o) > abs(cur):
                    seg_off[k][i] = sign * o
    out = {}
    for k, ln in links.items():
        pts = list(base[k])
        offs = seg_off[k]
        if not offs:
            out[k] = pts
            continue
        cum = [0.0]
        for p, q in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.dist(p, q))
        res = [pts[0]]
        for j in range(1, len(pts) - 1):
            # lines fan out of the stop over `taper` map px, so the tight turns of a harbour mouth stay clean
            f = min(1.0, cum[j] / taper, (cum[-1] - cum[j]) / taper)
            o1, o2 = offs.get(j - 1, 0.0), offs.get(j, 0.0)
            n1 = _unit(-(pts[j][1] - pts[j - 1][1]), pts[j][0] - pts[j - 1][0])
            n2 = _unit(-(pts[j + 1][1] - pts[j][1]), pts[j + 1][0] - pts[j][0])
            if abs(o1 - o2) < 1e-6:
                nx, ny = _unit(n1[0] + n2[0], n1[1] + n2[1])
                cos = max(0.5, nx * n1[0] + ny * n1[1])
                o = o1 / cos
            else:
                nx, ny = _unit(n1[0] + n2[0], n1[1] + n2[1])
                o = (o1 + o2) / 2
            res.append((pts[j][0] + nx * o * f, pts[j][1] + ny * o * f))
        res.append(pts[-1])
        out[k] = res
    return out


# ---------------------------------------------------------------------- bypass
def bypass(pts, ends: tuple, obstacles: list, margin: float = 3.0):
    """Bow a dense polyline around stop symbols it passes but does not serve.
    obstacles: [(x, y, radius, burg)]; ends: burg ids of the link's two stops."""
    pts = list(pts)
    near = [(x, y, r + margin) for x, y, r, b in obstacles if b not in ends]
    if not near:
        return pts
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bx0, bx1, by0, by1 = min(xs) - 15, max(xs) + 15, min(ys) - 15, max(ys) + 15
    near = [o for o in near if bx0 < o[0] < bx1 and by0 < o[1] < by1]
    if not near:
        return pts
    for _ in range(3):
        moved = False
        for i in range(1, len(pts) - 1):
            x, y = pts[i]
            for ox, oy, R in near:
                d = math.hypot(x - ox, y - oy)
                if d < R:
                    if d < 1e-6:
                        px, py = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
                        ux, uy = _unit(-py, px)
                    else:
                        ux, uy = (x - ox) / d, (y - oy) / d
                    x, y = ox + ux * R, oy + uy * R
                    moved = True
            pts[i] = (x, y)
        if not moved:
            break
        pts = chaikin(pts, 1)
    return pts
