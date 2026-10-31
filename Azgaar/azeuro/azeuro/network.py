"""The playable network: stops, land and sea links between them, neutral hubs, air sites, stars.

Stops (the filter)
  Always a stop: every market's central burg (commissions run between markets), every capital,
  every fort (burg group "fort"), and every burg named as an air site (air journeys, portals).
  Candidates: burgs of Azgaar's size class "city" (or, in maps without that group, the top
  decile by population). Candidates are taken largest first and kept only if they are at least
  `spacing` x map width from every stop already kept, which keeps the board readable.

Links
  Azgaar's route graph (cell -> neighbour -> route) is split by mode: searoutes are sea, roads and
  trails are land. Each mode is contracted with a network Voronoi: every route cell belongs to its
  nearest stop along the routes, and two stops are linked where their territories touch. Links
  therefore never pass through a third stop, and the graph stays sparse. A mode can only change
  at a stop. If some stops cannot reach the rest, the cheapest connection through the full route
  graph is found and the burgs where it changes mode are added as stops.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field

from .mapfile import AzgaarMap


@dataclass
class Stop:
    burg: int
    cell: int
    x: float
    y: float
    name: str
    state: int
    population: float
    roles: set = field(default_factory=set)  # market, capital, fort, city, port, link
    market: int | None = None
    neutral: bool = False
    air: bool = False


@dataclass
class Link:
    a: int  # burg ids
    b: int
    mode: str  # land | sea
    length: float  # map px along the route
    points: list  # [(x, y), ...] from a to b


@dataclass
class Star:
    marker: dict
    x: float
    y: float
    mode: str  # land | sea | air (air = remote from every link)
    link: tuple | None  # (a, b, mode) of the link it sits on


class Network:
    def __init__(self, m: AzgaarMap, spacing: float = 0.016, neutral: int | None = None,
                 air: int | None = None, air_overlap: int = 1, remote: float = 0.015,
                 skip_marker_types: set | None = None):
        self.m = m
        self.width = m.settings["graph"]["width"]
        self.height = m.settings["graph"]["height"]
        self.burgs = {b["i"]: b for b in m.live_burgs()}
        self.routes = {r["i"]: r for r in m.live("routes")}
        self.notes: list[str] = []
        self._cell_graph()
        n_states = len([s for s in m.live("states") if s.get("i")])
        self.n_neutral = neutral if neutral is not None else max(3, min(6, int(n_states / 2 + 0.5)))
        self.n_air = air if air is not None else max(4, min(7, n_states // 2 + 2))
        self._select_stops(spacing)
        self._build_links()
        self._repair()
        self._hubs(air_overlap)
        self._stars(remote, skip_marker_types or set())

    # ------------------------------------------------------------------ route graph
    def _cell_graph(self):
        self.xy: dict[int, tuple[float, float]] = {}
        for r in self.routes.values():
            for x, y, c in r["points"]:
                self.xy[c] = (x, y)
        for b in self.burgs.values():
            self.xy[b["cell"]] = (b["x"], b["y"])
        raw = self.m.data.get("cell_routes") or {}
        self.adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for c, nb in raw.items():
            for n, rid in nb.items():
                r = self.routes.get(rid)
                if not r:
                    continue
                c_, n_ = int(c), int(n)
                if c_ in self.xy and n_ in self.xy:
                    self.adj[c_].append((n_, "sea" if r["group"] == "searoutes" else "land"))
        if not self.adj:  # older saves without cell_routes: rebuild from route point lists
            for r in self.routes.values():
                md = "sea" if r["group"] == "searoutes" else "land"
                pts = r["points"]
                for (x0, y0, c0), (x1, y1, c1) in zip(pts, pts[1:]):
                    self.adj[c0].append((c1, md))
                    self.adj[c1].append((c0, md))
        self.cell_burg = {b["cell"]: b["i"] for b in self.burgs.values()}

    def _d(self, a, b) -> float:
        return math.dist(self.xy[a], self.xy[b])

    # ------------------------------------------------------------------ stops
    def _make_stop(self, bid: int, role: str) -> Stop:
        b = self.burgs[bid]
        if bid in self.stops:
            self.stops[bid].roles.add(role)
            return self.stops[bid]
        s = Stop(bid, b["cell"], b["x"], b["y"], b["name"], b.get("state", 0), b.get("population", 0), {role})
        if b.get("port"):
            s.roles.add("port")
        self.stops[bid] = s
        return s

    def _air_requests(self) -> list[int]:
        """Burgs named as air sites by the map: air-domain journey legs and portal markers."""
        domain = {t["name"]: t.get("domain") for t in self.m.settings.get("transports", [])}
        out = []
        for j in self.m.data.get("journeys") or []:
            for seg in j.get("segments", []):
                if domain.get(seg.get("transport")) == "air":
                    for c in (seg.get("from"), seg.get("to")):
                        if c in self.cell_burg:
                            out.append(self.cell_burg[c])
        for mk in self.m.live("markers"):
            if mk.get("type") == "portals":
                near = min(self.burgs.values(), key=lambda b: (b["x"] - mk["x"]) ** 2 + (b["y"] - mk["y"]) ** 2)
                if math.hypot(near["x"] - mk["x"], near["y"] - mk["y"]) < 0.02 * self.width:
                    out.append(near["i"])
        return list(dict.fromkeys(out))

    def _select_stops(self, spacing: float):
        self.stops: dict[int, Stop] = {}
        self.markets = {mk["i"]: mk for mk in self.m.live("markets")}
        for mk in self.markets.values():
            bid = mk["centerBurgId"]
            if bid in self.burgs:
                self._make_stop(bid, "market").market = mk["i"]
        for b in self.burgs.values():
            if b.get("capital"):
                self._make_stop(b["i"], "capital")
            if b.get("group") == "fort":
                self._make_stop(b["i"], "fort")
        self.air_requested = self._air_requests()
        for bid in self.air_requested:
            self._make_stop(bid, "air-request")
        groups = {b.get("group") for b in self.burgs.values()}
        if "city" in groups:
            cand = [b for b in self.burgs.values() if b.get("group") == "city"]
            self.city_rule = "burg group 'city'"
        else:
            pops = sorted(b["population"] for b in self.burgs.values())
            cut = pops[int(len(pops) * 0.9)]
            cand = [b for b in self.burgs.values() if b["population"] >= cut]
            self.city_rule = f"population >= {cut:.2f} (top decile)"
        gap = spacing * self.width
        for b in sorted(cand, key=lambda b: -b["population"]):
            if b["i"] in self.stops:
                self.stops[b["i"]].roles.add("city")
                continue
            if all(math.hypot(b["x"] - s.x, b["y"] - s.y) >= gap for s in self.stops.values()):
                self._make_stop(b["i"], "city")
        self.spacing_px = gap

    # ------------------------------------------------------------------ links
    def _contract(self, mode: str) -> dict:
        stop_cells = {s.cell: s.burg for s in self.stops.values()}
        dist, owner, prev, pq = {}, {}, {}, []
        for c in stop_cells:
            dist[c], owner[c] = 0.0, c
            heapq.heappush(pq, (0.0, c))
        while pq:
            dd, c = heapq.heappop(pq)
            if dd > dist[c]:
                continue
            for n, md in self.adj.get(c, ()):
                if md != mode:
                    continue
                nd = dd + self._d(c, n)
                if nd < dist.get(n, math.inf):
                    dist[n], owner[n], prev[n] = nd, owner[c], c
                    heapq.heappush(pq, (nd, n))

        def back(c):
            p = [c]
            while p[-1] in prev:
                p.append(prev[p[-1]])
            return p

        best: dict[tuple, tuple] = {}
        for c in dist:
            for n, md in self.adj.get(c, ()):
                if md != mode or n not in dist or owner[c] == owner[n]:
                    continue
                a, b = owner[c], owner[n]
                length = dist[c] + self._d(c, n) + dist[n]
                key = (a, b) if a < b else (b, a)
                if key not in best or best[key][0] > length:
                    path = back(c)[::-1] + back(n)
                    if path[0] != key[0]:
                        path = path[::-1]
                    best[key] = (length, path)
        links = {}
        for (ca, cb), (length, path) in best.items():
            a, b = stop_cells[ca], stop_cells[cb]
            links[(a, b, mode)] = Link(a, b, mode, length, [self.xy[c] for c in path])
        return links

    def _build_links(self):
        self.links: dict[tuple, Link] = {}
        self.links.update(self._contract("land"))
        self.links.update(self._contract("sea"))
        self.nbr: dict[int, list[tuple[int, Link]]] = defaultdict(list)
        for ln in self.links.values():
            self.nbr[ln.a].append((ln.b, ln))
            self.nbr[ln.b].append((ln.a, ln))

    def components(self) -> list[set]:
        seen, comps = set(), []
        for s in self.stops:
            if s in seen:
                continue
            comp, todo = set(), [s]
            while todo:
                c = todo.pop()
                if c in comp:
                    continue
                comp.add(c)
                todo.extend(n for n, _ in self.nbr[c] if n not in comp)
            seen |= comp
            comps.append(comp)
        return sorted(comps, key=len, reverse=True)

    def _repair(self, rounds: int = 12):
        for _ in range(rounds):
            comps = self.components()
            if len(comps) <= 1:
                return
            main = {self.stops[b].cell for b in comps[0]}
            added = False
            for comp in comps[1:]:
                start = [self.stops[b].cell for b in comp]
                path = self._layered_path(start, main)
                if not path:
                    names = ", ".join(sorted(self.stops[b].name for b in comp))
                    self.notes.append(f"No land or sea connection for: {names} (air only)")
                    continue
                for (c0, m0), (c1, m1) in zip(path, path[1:]):
                    if m0 != m1 and c0 in self.cell_burg and self.cell_burg[c0] not in self.stops:
                        self._make_stop(self.cell_burg[c0], "link")
                        added = True
            if not added:
                return
            self._build_links()

    def _layered_path(self, starts, targets):
        """Cheapest path over (cell, mode) states; the mode may change only at a burg."""
        dist, prev, pq = {}, {}, []
        for c in starts:
            for md in ("land", "sea"):
                dist[(c, md)] = 0.0
                heapq.heappush(pq, (0.0, c, md))
        while pq:
            dd, c, md = heapq.heappop(pq)
            if dd > dist.get((c, md), math.inf):
                continue
            if c in targets and dd > 0:
                p = [(c, md)]
                while p[-1] in prev:
                    p.append(prev[p[-1]])
                return p[::-1]
            moves = [(n, m2, self._d(c, n)) for n, m2 in self.adj.get(c, ()) if m2 == md]
            if c in self.cell_burg:
                other = "sea" if md == "land" else "land"
                moves.append((c, other, 0.0))
            for n, m2, w in moves:
                nd = dd + w
                if nd < dist.get((n, m2), math.inf):
                    dist[(n, m2)] = nd
                    prev[(n, m2)] = (c, md)
                    heapq.heappush(pq, (nd, n, m2))
        return None

    # ------------------------------------------------------------------ hubs
    def _spread(self, ranked: list[Stop], n: int, gap: float, skip=lambda s: False) -> list[Stop]:
        out: list[Stop] = []
        for s in ranked:
            if len(out) >= n:
                break
            if skip(s):
                continue
            if all(math.hypot(s.x - o.x, s.y - o.y) >= gap for o in out):
                out.append(s)
        return out

    def _hubs(self, air_overlap: int):
        ranked = sorted(self.stops.values(), key=lambda s: -s.population)
        for s in self._spread(ranked, self.n_neutral, 0.15 * self.width):
            s.neutral = True
        req = [self.stops[b] for b in self.air_requested if b in self.stops]
        if len(req) >= 2:
            chosen = req
            self.air_rule = "air journeys and portal markers in the map"
        else:
            used = {"overlap": 0}

            def skip(s):
                if s.neutral:
                    if used["overlap"] >= air_overlap:
                        return True
                    used["overlap"] += 1
                return False
            chosen = self._spread(ranked, self.n_air, 0.12 * self.width, skip)
            self.air_rule = (f"none in the map; the {len(chosen)} largest stops, spread out, "
                             f"sharing at most {air_overlap} with the neutral hubs")
        for s in chosen:
            s.air = True

    # ------------------------------------------------------------------ stars
    def _stars(self, remote: float, skip_types: set):
        self.stars: list[Star] = []
        lim = remote * self.width
        segs = []
        for key, ln in self.links.items():
            for p, q in zip(ln.points, ln.points[1:]):
                segs.append((p, q, key))
        placed: list[tuple[float, float]] = [(s.x, s.y) for s in self.stops.values()]
        for mk in self.m.live("markers"):
            if mk.get("type") in skip_types:
                continue
            px, py = mk["x"], mk["y"]
            best = (math.inf, None, None)
            for p, q, key in segs:
                dx, dy = q[0] - p[0], q[1] - p[1]
                L2 = dx * dx + dy * dy
                t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - p[0]) * dx + (py - p[1]) * dy) / L2))
                cx, cy = p[0] + t * dx, p[1] + t * dy
                dd = math.hypot(px - cx, py - cy)
                if dd < best[0]:
                    best = (dd, (cx, cy), key)
            if best[0] <= lim:
                x, y = best[1]
                star = Star(mk, x, y, best[2][2], best[2])
            else:
                star = Star(mk, px, py, "air", None)
            # nudge off stops and other stars
            for _ in range(6):
                close = [(ox, oy) for ox, oy in placed if math.hypot(star.x - ox, star.y - oy) < 7]
                if not close:
                    break
                ox, oy = close[0]
                ang = math.atan2(star.y - oy, star.x - ox) if (star.x, star.y) != (ox, oy) else 0.7
                star.x, star.y = ox + 8 * math.cos(ang), oy + 8 * math.sin(ang)
            placed.append((star.x, star.y))
            self.stars.append(star)

    # ------------------------------------------------------------------ paths
    def path(self, a: int, b: int, use_air: bool = False):
        """Fewest-stops path (ties by length) between two stops: (stops, links) or None."""
        if a == b:
            return [a], []
        dist, prev, pq = {a: (0, 0.0)}, {}, [(0, 0.0, a)]
        air_sites = [s.burg for s in self.stops.values() if s.air] if use_air else []
        while pq:
            h, L, c = heapq.heappop(pq)
            if (h, L) > dist.get(c, (math.inf, math.inf)):
                continue
            if c == b:
                break
            moves = [(n, ln) for n, ln in self.nbr[c]]
            if use_air and self.stops[c].air:
                moves += [(n, None) for n in air_sites if n != c]
            for n, ln in moves:
                w = ln.length if ln else math.hypot(self.stops[c].x - self.stops[n].x, self.stops[c].y - self.stops[n].y)
                nd = (h + 1, L + w)
                if nd < dist.get(n, (math.inf, math.inf)):
                    dist[n] = nd
                    prev[n] = (c, ln)
                    heapq.heappush(pq, (nd[0], nd[1], n))
        if b not in dist:
            return None
        stops, links, c = [b], [], b
        while c != a:
            c, ln = prev[c]
            stops.append(c)
            links.append(ln)
        return stops[::-1], links[::-1]

    def summary(self) -> dict:
        roles = defaultdict(int)
        for s in self.stops.values():
            for r in s.roles:
                roles[r] += 1
        modes = defaultdict(int)
        for k in self.links:
            modes[k[2]] += 1
        stars = defaultdict(int)
        for s in self.stars:
            stars[s.mode] += 1
        return {"stops": len(self.stops), "roles": dict(roles), "links": dict(modes),
                "neutral": [s.name for s in self.stops.values() if s.neutral],
                "air": [s.name for s in self.stops.values() if s.air], "stars": dict(stars),
                "components": [len(c) for c in self.components()], "notes": self.notes,
                "city_rule": self.city_rule, "air_rule": self.air_rule,
                "spacing_px": round(self.spacing_px, 1)}
