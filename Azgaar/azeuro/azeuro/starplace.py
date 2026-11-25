"""Where favour stars are drawn.

The network decides what a star belongs to; the board only decides where to draw it.

  link    a marker near a route belongs to that link; any route using the link takes it. Its place
          along the link does not matter to the rules, so the star may slide along its own line to a
          clear spot: off stop symbols, apart from other stars, and away from any other line, so it is
          never unclear which line it is on.
  stop    a marker in a stop's own cell belongs to the stop; any route through the stop takes it. It is
          docked on the stop symbol as a badge, like the air badge, on the side where no line leaves.
  remote  a marker far from every route stays where it is (nudged clear of symbols and lines) and is
          taken by an air route that passes nearby.

Stars on one line keep some line showing between them. When a line cannot show all its stars apart,
or several stars share one stop, they are drawn as one star with a number: it counts as that many
stars. A line with no clear spot at all (a very short link) has its star just beside it, on a short
tether to the line.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

STAR_R = 5.2
STAR_GAP = 2 * STAR_R + 2.0      # centre to centre between two stars
STOP_GAP = 4.0                   # clear gap between a star on a line and any stop symbol
LINE_NEAR = 4.2                  # a star this close to another line looks like it is on that line


def stop_radius(s) -> float:
    if "capital" in s.roles:
        r = 8.6
    elif "market" in s.roles:
        r = 6.4
    elif "fort" in s.roles:
        r = 6.5
    else:
        r = 4.8
    return max(r, 9.9) if s.neutral else r


def obstacles(stops) -> list:
    """(x, y, radius, burg) for every stop symbol and air badge."""
    out = []
    for s in stops:
        out.append((s.x, s.y, stop_radius(s), s.burg))
        if s.air:
            out.append((s.x + 8.5, s.y - 8.5, 6.2, s.burg))
    return out


@dataclass
class Mark:
    x: float
    y: float
    kind: str                     # line | stop | remote
    stars: list = field(default_factory=list)
    key: tuple | None = None
    stop: int | None = None
    anchor: tuple | None = None   # a tethered star: the point on its line the tether runs to

    @property
    def count(self) -> int:
        return len(self.stars)

    @property
    def r(self) -> float:
        return STAR_R if self.count == 1 else STAR_R + 1.4


def _resample(pts, step=1.5):
    out, cum = [pts[0]], [0.0]
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(L / step))
        for i in range(1, n + 1):
            out.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n))
            cum.append(acc + L * i / n)
        acc += L
    return out, cum


class _Grid:
    """Points of every drawn line, bucketed, labelled by link key."""

    def __init__(self, geom: dict, cell=8.0):
        self.cell = cell
        self.b: dict[tuple, list] = {}
        for k, pts in geom.items():
            for x, y in pts:
                self.b.setdefault((int(x // cell), int(y // cell)), []).append((x, y, k))

    def other_line(self, x, y, key, r) -> bool:
        c = self.cell
        for i in range(int((x - r) // c), int((x + r) // c) + 1):
            for j in range(int((y - r) // c), int((y + r) // c) + 1):
                for px, py, k in self.b.get((i, j), ()):
                    if k != key and (px - x) ** 2 + (py - y) ** 2 < r * r:
                        return True
        return False

    def any_line(self, x, y, r) -> bool:
        return self.other_line(x, y, None, r)


def place(stars, geom: dict, stops: list) -> list[Mark]:
    obs = obstacles(stops)
    grid = _Grid(geom)
    marks: list[Mark] = []
    stop_by = {s.burg: s for s in stops}

    def clear_of_stops(x, y, r=STAR_R):
        return all(math.hypot(x - ox, y - oy) >= orad + r + STOP_GAP for ox, oy, orad, _ in obs)

    def clear_of_marks(x, y, r=STAR_R, gap=2.0):
        return all(math.hypot(x - m.x, y - m.y) >= r + m.r + gap for m in marks)

    # 1. stars docked on stops
    at_stop: dict[int, list] = {}
    for st in stars:
        if st.stop is not None:
            at_stop.setdefault(st.stop, []).append(st)
    for burg, group in at_stop.items():
        s = stop_by[burg]
        R = stop_radius(s) + 2.4  # overlaps the symbol's rim: it reads as part of the stop
        r = STAR_R if len(group) == 1 else STAR_R + 1.4
        best = None
        for deg in range(0, 360, 15):
            a = math.radians(deg)
            x, y = s.x + R * math.cos(a), s.y + R * math.sin(a)
            cost = abs(((deg - 135) + 180) % 360 - 180) / 90  # lower left preferred (y points down)
            if s.air and math.hypot(x - (s.x + 8.5), y - (s.y - 8.5)) < 6.2 + r + 1:
                cost += 1e4
            if any(math.hypot(x - ox, y - oy) < orad + r + 1 for ox, oy, orad, b in obs if b != burg):
                cost += 1e4
            if not clear_of_marks(x, y, r):
                cost += 1e3
            if grid.any_line(x, y, r + 1.0):
                cost += 50
            if best is None or cost < best[0]:
                best = (cost, x, y)
        marks.append(Mark(best[1], best[2], "stop", group, stop=burg))

    def tether(cand, cum, sp, key, r=STAR_R):
        """A clear spot 9-16 px off the line, away from every line and symbol: (x, y, anchor) or None."""
        best = None
        n = len(cand)
        for i in range(1, n - 1, 2):
            (x0, y0), (x1, y1) = cand[i - 1], cand[i + 1]
            L = math.hypot(x1 - x0, y1 - y0) or 1.0
            nx, ny = -(y1 - y0) / L, (x1 - x0) / L
            ax, ay = cand[i]
            if not all(math.hypot(ax - ox, ay - oy) >= orad + 1.0 for ox, oy, orad, _ in obs):
                continue  # the tether must meet the line outside every stop symbol
            for d in (10.0, 13.0, 16.0):
                for sgn in (1, -1):
                    x, y = ax + sgn * nx * d, ay + sgn * ny * d
                    if not (clear_of_stops(x, y, r) and clear_of_marks(x, y, r)) or grid.any_line(x, y, r + 1.5):
                        continue
                    cost = d + 0.3 * abs(cum[i] - sp)
                    if best is None or cost < best[0]:
                        best = (cost, x, y, (ax, ay))
        return best[1:] if best else None

    # 2. stars on links: slide along the link's own drawn line
    on_link: dict[tuple, list] = {}
    for st in stars:
        if st.stop is None and st.link is not None:
            on_link.setdefault(st.link, []).append(st)
    for key in sorted(on_link, key=lambda k: -len(on_link[k])):
        pts = geom.get(key)
        if not pts:
            continue
        cand, cum = _resample(pts)

        def pref(st):
            mx, my = st.marker["x"], st.marker["y"]
            i = min(range(len(cand)), key=lambda i: (cand[i][0] - mx) ** 2 + (cand[i][1] - my) ** 2)
            return cum[i]
        group = sorted(on_link[key], key=pref)
        free = [i for i, (x, y) in enumerate(cand) if clear_of_stops(x, y)]
        lone = {i for i in free if not grid.other_line(cand[i][0], cand[i][1], key, LINE_NEAR + STAR_R * 0.6)}
        same_gap = 6.0  # stars on one line leave this much line showing between them

        def spot(sp, r, mine):
            best = None
            for i in free:
                x, y = cand[i]
                if not clear_of_marks(x, y, r):
                    continue
                if any(math.hypot(x - o.x, y - o.y) < r + o.r + same_gap for o in mine):
                    continue
                cost = abs(cum[i] - sp) + (0 if i in lone else 400)
                if best is None or cost < best[0]:
                    best = (cost, x, y)
            return best

        mine: list[Mark] = []
        fits = True
        for st in group:
            best = spot(pref(st), STAR_R, mine)
            if best is None:
                fits = False
                break
            m = Mark(best[1], best[2], "line", [st], key=key)
            marks.append(m)
            mine.append(m)
        if fits:
            continue
        # the line cannot show all its stars apart: one star with a number for the whole line
        for m in mine:
            marks.remove(m)
        r = STAR_R if len(group) == 1 else STAR_R + 1.4
        sp = sorted(pref(st) for st in group)[len(group) // 2]
        best = spot(sp, r, [])
        if best is not None:
            marks.append(Mark(best[1], best[2], "line", list(group), key=key))
            continue
        teth = tether(cand, cum, sp, key, r)
        if teth is not None:  # no room on the line at all: beside it, on a short tether
            marks.append(Mark(teth[0], teth[1], "line", list(group), key=key, anchor=teth[2]))
        else:  # nowhere clear: the line's middle
            x, y = cand[len(cand) // 2]
            marks.append(Mark(x, y, "line", list(group), key=key))

    # 3. remote stars: as close to the marker as is clear
    for st in stars:
        if st.stop is not None or st.link is not None:
            continue
        mx, my = st.marker["x"], st.marker["y"]
        spot = (mx, my)
        for rad in [0] + [2 * k for k in range(1, 14)]:
            found = None
            for deg in range(0, 360, 20 if rad else 360):
                x, y = mx + rad * math.cos(math.radians(deg)), my + rad * math.sin(math.radians(deg))
                if clear_of_stops(x, y) and clear_of_marks(x, y) and not grid.any_line(x, y, STAR_R + 1.5):
                    found = (x, y)
                    break
            if found:
                spot = found
                break
        marks.append(Mark(spot[0], spot[1], "remote", [st]))
    return marks

