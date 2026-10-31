"""The game board as one SVG in map pixels, with a legend strip under the map.

Layers, bottom to top: sea, coastal shallows, land, biome tint (Cells GeoJSON), lakes, ice, relief
(grid heights), rivers, history zones (Cells GeoJSON), state territory bands, state and sea names,
land and sea links, event stars, stops, stop names. Everything comes from the .map except the
biome and zone shapes, which need the Cells export.
"""
from __future__ import annotations

import math
import re

from .geo import CellGeo, geom_to_path
from .network import Network
from .svgkit import (AIR, COIN, INK, LAND, MUTED, PANEL, PAPER, SEA, esc, icon, star, text, text_width)

OCEAN = "#BCD3E0"
SHALLOW = "#D3E3EC"
LAND_BASE = "#E2E3D3"
LAKE = "#C3D8E4"
RIVER = "#8FB4CB"
RELIEF = "#8A7A63"

BIOME_TINTS = [("glacier", "#E6EDF0"), ("tundra", "#DCDFD8"), ("taiga", "#C9D5C1"), ("wetland", "#C9D6C6"),
               ("rainforest", "#BBD0A6"), ("deciduous", "#C9D8B0"), ("seasonal", "#CEDBAA"),
               ("savanna", "#E2DDB0"), ("grassland", "#DCE2BC"), ("hot desert", "#EADFBE"),
               ("cold desert", "#DEDCD2"), ("desert", "#E8DEC0"), ("forest", "#C9D8B0")]

ZONE_STYLE = [  # (keywords, colour, label)
    (("invasion", "rebels", "crusade", "conquest", "war", "occupation", "insurrection"), "#A33A2E", "conflict"),
    (("proselytism", "convert", "heresy", "religious"), "#6E3B87", "faith"),
    (("eruption", "avalanche", "flood", "tsunami", "fault", "earthquake", "fire", "drought", "disease",
      "plague", "epidemic", "famine", "storm"), "#6B5B3E", "disaster"),
]

_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')


def _group_paths(svg: str, gid: str) -> list[dict]:
    i = svg.find(f'id="{gid}"')
    if i < 0:
        return []
    j = svg.find("</g>", i)
    return [dict(_ATTR.findall(m.group(1))) for m in re.finditer(r"<path\b([^>]*)>", svg[i:j])]


def _chaikin(pts, rounds=2):
    for _ in range(rounds):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        out.append(pts[-1])
        pts = out
    return pts


def _poly(pts) -> str:
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _darken(hexcol: str, amount: float = 0.55) -> str:
    h = hexcol.lstrip("#")
    if len(h) != 6:
        return INK
    r, g, b = (int(h[k:k + 2], 16) for k in (0, 2, 4))
    ir, ig, ib = 0x1F, 0x2A, 0x33
    mix = lambda c, i: round(c * (1 - amount) + i * amount)
    return f"#{mix(r, ir):02x}{mix(g, ig):02x}{mix(b, ib):02x}"


class Board:
    def __init__(self, net: Network, geo: CellGeo | None):
        self.net, self.m, self.geo = net, net.m, geo
        self.W, self.H = net.width, net.height
        self.svg = self.m.svg
        self.features = {f["i"]: f for f in self.m.data["features"] if isinstance(f, dict)}
        self.fpaths = {}
        fp = self.svg.find('id="featurePaths"')
        if fp >= 0:
            for a in _group_paths(self.svg, "featurePaths"):
                if a.get("id", "").startswith("feature_") and a.get("d"):
                    self.fpaths[int(a["id"][8:])] = a["d"]
        self.boxes: list[tuple] = []  # placed name boxes (x0, y0, x1, y1)
        self.view = (0, 0, self.W, self.H)

    # ------------------------------------------------------------------ landscape
    def _land(self) -> str:
        land = [d for i, d in self.fpaths.items() if self.features.get(i, {}).get("land")
                and self.features[i].get("group") != "lake_island"]
        lakes = [(d, self.features[i].get("group")) for i, d in self.fpaths.items()
                 if self.features.get(i, {}).get("type") == "lake"]
        lake_isles = [d for i, d in self.fpaths.items() if self.features.get(i, {}).get("group") == "lake_island"]
        out = [f'<rect width="{self.W}" height="{self.H}" fill="{OCEAN}"/>']
        out.append(f'<defs><clipPath id="landclip"><path d="{" ".join(land)}"/></clipPath></defs>')
        out.append(f'<path d="{" ".join(land)}" fill="none" stroke="{SHALLOW}" stroke-width="9" stroke-linejoin="round"/>')
        out.append(f'<path d="{" ".join(land)}" fill="{LAND_BASE}"/>')
        out.append(self._biomes())
        for d, grp in lakes:
            fill = "#E3DCC4" if grp == "dry" else LAKE
            out.append(f'<path d="{d}" fill="{fill}" stroke="{INK}" stroke-width="0.4" stroke-opacity="0.4"/>')
        for d in lake_isles:
            out.append(f'<path d="{d}" fill="{LAND_BASE}"/>')
        out.append(self._ice())
        out.append(self._relief())
        out.append(self._rivers())
        out.append(f'<path d="{" ".join(land)}" fill="none" stroke="{INK}" stroke-width="0.7" stroke-opacity="0.55"/>')
        return "".join(out)

    def _biomes(self) -> str:
        if not self.geo:
            return ""
        names = {b["i"]: b["name"].lower() for b in self.m.data["biomes"]} if isinstance(self.m.data["biomes"], list) \
            else {i: n.lower() for i, n in enumerate(self.m.data["biomes"].get("name", []))}
        by_biome: dict[int, list[int]] = {}
        for c, p in self.geo.props.items():
            if p.get("type") in ("ocean", "lake"):
                continue
            by_biome.setdefault(p.get("biome", 0), []).append(c)
        out = ['<g clip-path="url(#landclip)">']
        for bid, cells in by_biome.items():
            name = names.get(bid, "")
            tint = next((col for key, col in BIOME_TINTS if key in name), None)
            if not tint:
                continue
            d = geom_to_path(self.geo.union(cells, 0.8))
            if d:
                out.append(f'<path d="{d}" fill="{tint}" fill-rule="evenodd"/>')
        out.append("</g>")
        return "".join(out)

    def _ice(self) -> str:
        out = []
        for ice in self.m.data.get("ice") or []:
            pts = ice.get("points") if isinstance(ice, dict) else None
            if pts:
                out.append(f'<path d="{_poly(pts)}Z" fill="#EEF3F6" stroke="#FFFFFF" stroke-width="0.6"/>')
        return "".join(out)

    def _occupancy(self, cell=6.0):
        occ = set()
        for ln in self.net.links.values():
            for x, y in ln.points:
                occ.add((int(x // cell), int(y // cell)))
        for s in self.net.stops.values():
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    occ.add((int(s.x // cell) + dx, int(s.y // cell) + dy))
        return occ, cell

    def _relief(self) -> str:
        grid = self.m.data["grid"]
        pts, hs = grid["points"], self.m.data["grid_h"]
        occ, cs = self._occupancy()
        out = [f'<g fill="none" stroke="{RELIEF}" stroke-width="0.8" stroke-linecap="round" stroke-linejoin="round" '
               f'opacity="0.6">']
        for k, ((x, y), h) in enumerate(zip(pts, hs)):
            if h < 45 or (k + (k // grid.get("cellsX", 1))) % 2:
                continue
            if (int(x // cs), int(y // cs)) in occ:
                continue
            if h >= 62:
                out.append(f'<path d="M{x - 4.5:.1f},{y + 2:.1f} L{x - 0.5:.1f},{y - 3.5:.1f} L{x + 3.5:.1f},{y + 2:.1f} '
                           f'M{x + 1.5:.1f},{y - 0.6:.1f} L{x + 3:.1f},{y - 2.4:.1f} L{x + 6:.1f},{y + 2:.1f}"/>')
            else:
                out.append(f'<path d="M{x - 4:.1f},{y + 1.5:.1f} Q{x:.1f},{y - 2.5:.1f} {x + 4:.1f},{y + 1.5:.1f}"/>')
        out.append("</g>")
        return "".join(out)

    def _rivers(self) -> str:
        out = []
        for a in _group_paths(self.svg, "rivers"):
            if a.get("d"):
                out.append(f'<path d="{a["d"]}" fill="{RIVER}"/>')
        return "".join(out)

    # ------------------------------------------------------------------ history and states
    def _zones(self) -> tuple[str, str]:
        if not self.geo:
            return "", ""
        shapes, labels = [], []
        for k, z in enumerate(self.m.live("zones")):
            ztype = (z.get("type") or "").lower()
            style = next(((col, lab) for keys, col, lab in ZONE_STYLE if any(w in ztype for w in keys)), None)
            if not style:
                continue
            geom = self.geo.union(z.get("cells", []), 0.6)
            d = geom_to_path(geom)
            if not d:
                continue
            col = style[0]
            shapes.append(f'<defs><pattern id="z{k}" width="5" height="5" patternUnits="userSpaceOnUse" '
                          f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="{col}" '
                          f'stroke-width="1.1" stroke-opacity="0.55"/></pattern></defs>'
                          f'<path d="{d}" fill="url(#z{k})" fill-rule="evenodd" stroke="{col}" stroke-width="0.6" '
                          f'stroke-opacity="0.6" stroke-dasharray="2 1.5"/>')
            if len(z.get("cells", [])) < 3:
                continue
            p = geom.representative_point()
            name = z.get("name", "")
            w = text_width(name, 8.5, "Barlow", 500, "italic")
            for dx, dy in ((0, 0), (0, -10), (0, 10), (12, 0), (-12, 0)):
                box = (p.x + dx - w / 2, p.y + dy - 6, p.x + dx + w / 2, p.y + dy + 3)
                if not any(self._hit(box, b) for b in self.boxes):
                    self.boxes.append(box)
                    labels.append(self._halo(p.x + dx, p.y + dy + 3, name, 8.5, col, style_italic=True, weight=500,
                                             anchor="middle"))
                    break
        return "".join(shapes), "".join(labels)

    @staticmethod
    def _hit(a, b) -> bool:
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    def _state_spot(self, sid, x, y, w, h):
        """A spot for a state's name: near its pole, clear of stops, stars and links."""
        if not self.geo:
            return x, y
        pts = [(s.x, s.y, 12) for s in self.net.stops.values()] + [(t.x, t.y, 8) for t in self.net.stars]
        link_pts = [p for ln in self.net.links.values() for p in ln.points[::2]]
        cands = [(x, y)] + [self.geo.centroid(c) for c, p in self.geo.props.items()
                            if p.get("state") == sid and p.get("type") == "island"][::3]
        best = None
        for cx, cy in cands:
            vx0, vy0, vx1, vy1 = self.view
            if cx - w / 2 < vx0 + 6 or cx + w / 2 > vx1 - 6 or cy - h < vy0 + 6 or cy + 4 > vy1 - 6:
                continue
            box = (cx - w / 2, cy - h * 0.75, cx + w / 2, cy + h * 0.3)
            score = 10 * sum(1 for px, py, r in pts if box[0] - r < px < box[2] + r and box[1] - r < py < box[3] + r)
            score += sum(1 for px, py in link_pts if box[0] < px < box[2] and box[1] < py < box[3])
            score += math.hypot(cx - x, cy - y) / 40
            if best is None or score < best[0]:
                best = (score, cx, cy)
        return (best[1], best[2]) if best else (x, y)

    def _states(self) -> tuple[str, str]:
        states = {s["i"]: s for s in self.m.live("states")}
        bodies, labels = [], []
        shapes = [(int(a["id"][5:]), a["d"]) for a in _group_paths(self.svg, "statesBody")
                  if re.fullmatch(r"state\d+", a.get("id", "")) and a.get("d")]
        if not shapes and self.geo:  # states layer not saved in the SVG: rebuild from the cells
            by_state: dict[int, list[int]] = {}
            for c, p in self.geo.props.items():
                if p.get("state") and p.get("type") not in ("ocean", "lake"):
                    by_state.setdefault(p["state"], []).append(c)
            shapes = [(n, geom_to_path(self.geo.union(cells, 0.8))) for n, cells in by_state.items()]
        for n, d in shapes:
            a = {"d": d}
            st = states.get(n)
            if not st or not st.get("color"):
                continue
            col = st["color"]
            bodies.append(f'<defs><clipPath id="sc{n}"><path d="{a["d"]}"/></clipPath></defs>'
                          f'<path d="{a["d"]}" fill="{col}" fill-opacity="0.10"/>'
                          f'<path d="{a["d"]}" fill="none" stroke="{col}" stroke-width="7" stroke-opacity="0.75" '
                          f'clip-path="url(#sc{n})" stroke-linejoin="round"/>')
        for n, st in states.items():
            if not n or not st.get("pole"):
                continue
            x, y = st["pole"]
            size = max(14.0, min(30.0, 12 + math.sqrt(st.get("area", 0) or 0) / 18))
            name = st["name"].upper()
            w = text_width(name, size, "Barlow Condensed", 700) + len(name) * size * 0.12
            x, y = self._state_spot(n, x, y + size * 0.35, w, size)
            self.boxes.append((x - w / 2, y - size * 0.75, x + w / 2, y + size * 0.3))
            labels.append(self._halo(x, y, name, size, _darken(st.get("color", "#888888")),
                                     family="Barlow Condensed", weight=700, anchor="middle", spacing=size * 0.12,
                                     opacity=0.85, occupy=False))
        return "".join(bodies), "".join(labels)

    def _seas(self) -> str:
        try:
            from scipy.spatial import cKDTree
        except ImportError:
            return ""
        grid = self.m.data["grid"]
        pts, hs, fs = grid["points"], self.m.data["grid_h"], self.m.data["grid_f"]
        land = [p for p, h in zip(pts, hs) if h >= 20]
        if not land:
            return ""
        tree = cKDTree(land)
        out = []
        for f in self.features.values():
            if f.get("type") != "ocean" or not f.get("name"):
                continue
            half = text_width(f"{f['name']} Sea", 13, "Barlow", 500, "italic") / 2 + 12
            vx0, vy0, vx1, vy1 = self.view
            cand = [p for p, fid in zip(pts, fs) if fid == f["i"] and vx0 + half < p[0] < vx1 - half
                    and vy0 + 30 < p[1] < vy1 - 30]
            if not cand:
                continue
            dist, _ = tree.query(cand)
            k = max(range(len(cand)), key=lambda i: dist[i])
            if dist[k] < 25:
                continue
            x, y = cand[k]
            out.append(self._halo(x, y, f"{f['name']} Sea", 13, "#3F6E8E", style_italic=True, weight=500,
                                  anchor="middle", spacing=1.2, halo=OCEAN))
        return "".join(out)

    # ------------------------------------------------------------------ network
    def _links(self) -> str:
        casing, lines = [], []
        for ln in self.net.links.values():
            d = _poly(_chaikin(list(ln.points)))
            if ln.mode == "land":
                casing.append(f'<path d="{d}" stroke="{PANEL}" stroke-width="3.6"/>')
                lines.append(f'<path d="{d}" stroke="{LAND}" stroke-width="1.8"/>')
            else:
                casing.append(f'<path d="{d}" stroke="#E6F0F5" stroke-width="3.2"/>')
                lines.append(f'<path d="{d}" stroke="{SEA}" stroke-width="1.6" stroke-dasharray="5 3"/>')
        g = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'
        return f'<g {g}>{"".join(casing)}</g><g {g}>{"".join(lines)}</g>'

    def _stars(self) -> str:
        out = []
        for s in self.net.stars:
            fill = {"land": LAND, "sea": SEA, "air": AIR}[s.mode]
            out.append(star(s.x, s.y, 5.2, fill, INK, 0.9))
        return "".join(out)

    def _stop_mark(self, s) -> str:
        out = []
        if "capital" in s.roles:
            out.append(f'<circle cx="{s.x:.1f}" cy="{s.y:.1f}" r="8.6" fill="{PANEL}" stroke="{INK}" stroke-width="1.2"/>')
        if "fort" in s.roles and "market" not in s.roles and "capital" not in s.roles:
            out.append(f'<rect x="{s.x - 4.6:.1f}" y="{s.y - 4.6:.1f}" width="9.2" height="9.2" fill="{PANEL}" '
                       f'stroke="{INK}" stroke-width="1.4"/>')
        elif "market" in s.roles:
            out.append(f'<circle cx="{s.x:.1f}" cy="{s.y:.1f}" r="6.4" fill="{COIN}" stroke="{INK}" stroke-width="0.9"/>')
            out.append(f'<circle cx="{s.x:.1f}" cy="{s.y:.1f}" r="3.6" fill="{PANEL}" stroke="{INK}" stroke-width="0.9"/>')
        else:
            out.append(f'<circle cx="{s.x:.1f}" cy="{s.y:.1f}" r="4.8" fill="{PANEL}" stroke="{INK}" stroke-width="1.4"/>')
        if s.neutral:
            for k in (1, -1):
                out.append(f'<line x1="{s.x - 7:.1f}" y1="{s.y - 7 * k:.1f}" x2="{s.x + 7:.1f}" y2="{s.y + 7 * k:.1f}" '
                           f'stroke="{PANEL}" stroke-width="4" stroke-linecap="round"/>')
            for k in (1, -1):
                out.append(f'<line x1="{s.x - 7:.1f}" y1="{s.y - 7 * k:.1f}" x2="{s.x + 7:.1f}" y2="{s.y + 7 * k:.1f}" '
                           f'stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>')
        if s.air:
            bx, by = s.x + 8.5, s.y - 8.5
            out.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="6.2" fill="#FFFFFF" stroke="{INK}" stroke-width="1"/>')
            out.append(icon("air", bx - 4.6, by - 4.6, 9.2, INK, 1.3))
        return "".join(out)

    def _stops(self) -> str:
        order = sorted(self.net.stops.values(), key=lambda s: ("market" in s.roles, "capital" in s.roles))
        return "".join(self._stop_mark(s) for s in order)

    # ------------------------------------------------------------------ labels
    def _halo(self, x, y, s, size, fill, *, family="Barlow", weight=600, anchor="start", style_italic=False,
              spacing=0.0, opacity=1.0, halo=PANEL, occupy=True) -> str:
        fam = "'Barlow Condensed', 'Arial Narrow', sans-serif" if family == "Barlow Condensed" else \
            "Barlow, 'Helvetica Neue', Arial, sans-serif"
        it = ' font-style="italic"' if style_italic else ""
        ls = f' letter-spacing="{spacing:.1f}"' if spacing else ""
        common = (f'x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-weight="{weight}" font-size="{size:g}"{it}{ls} '
                  f'text-anchor="{anchor}"')
        return (f'<g opacity="{opacity}"><text {common} fill="none" stroke="{halo}" stroke-width="{size * 0.28:.2f}" '
                f'stroke-linejoin="round">{esc(s)}</text><text {common} fill="{fill}">{esc(s)}</text></g>')

    def _stop_labels(self) -> str:
        boxes = list(self.boxes)
        for s in self.net.stops.values():
            r = 9 if ("capital" in s.roles or s.neutral) else 7
            boxes.append((s.x - r, s.y - r, s.x + r, s.y + r))
        for st in self.net.stars:
            boxes.append((st.x - 5, st.y - 5, st.x + 5, st.y + 5))
        out = []
        ranked = sorted(self.net.stops.values(),
                        key=lambda s: (-("capital" in s.roles), -("market" in s.roles), -s.population))
        for s in ranked:
            big = "capital" in s.roles or "market" in s.roles
            size = 10.5 if "capital" in s.roles else (9.5 if big else 8.5)
            weight = 700 if big else 600
            w = text_width(s.name, size, "Barlow Condensed", weight) + (size * 0.5 if "capital" in s.roles else 0)
            h = size * 0.95
            gap = 9 if ("capital" in s.roles or s.neutral or s.air) else 7
            cands = [("start", s.x + gap, s.y + h * 0.35), ("end", s.x - gap, s.y + h * 0.35),
                     ("middle", s.x, s.y - gap - 1), ("middle", s.x, s.y + gap + h * 0.8),
                     ("start", s.x + gap * 0.8, s.y - gap * 0.8), ("end", s.x - gap * 0.8, s.y - gap * 0.8),
                     ("start", s.x + gap * 0.8, s.y + gap + h * 0.5), ("end", s.x - gap * 0.8, s.y + gap + h * 0.5)]
            best = None
            for k, (anchor, tx, ty) in enumerate(cands):
                x0 = tx if anchor == "start" else (tx - w if anchor == "end" else tx - w / 2)
                box = (x0 - 1, ty - h, x0 + w + 1, ty + h * 0.28)
                over = sum(max(0, min(box[2], b[2]) - max(box[0], b[0])) * max(0, min(box[3], b[3]) - max(box[1], b[1]))
                           for b in boxes)
                vx0, vy0, vx1, vy1 = self.view
                if box[0] < vx0 + 2 or box[2] > vx1 - 2 or box[1] < vy0 + 2 or box[3] > vy1 - 2:
                    over += 1e4
                score = over + k * 0.5
                if best is None or score < best[0]:
                    best = (score, anchor, tx, ty, box)
            _, anchor, tx, ty, box = best
            boxes.append(box)
            label = s.name.upper() if "capital" in s.roles else s.name
            out.append(self._halo(tx, ty, label, size, INK, family="Barlow Condensed", weight=weight, anchor=anchor,
                                  spacing=size * 0.05 if "capital" in s.roles else 0))
        return "".join(out)

    # ------------------------------------------------------------------ legend
    def _legend(self, y0: float, h: float, width: float) -> str:
        world = self.m.name
        cal = self.m.calendar
        era = f"Year {cal.get('year')} of the {cal.get('era')}" if cal.get("year") else ""
        s = width / 1863.0
        L = [f'<rect x="0" y="{y0}" width="{width}" height="{h}" fill="{PAPER}"/>',
             f'<line x1="0" y1="{y0}" x2="{width}" y2="{y0}" stroke="{INK}" stroke-width="2"/>',
             f'<g transform="translate(0 {y0}) scale({s:.4f})">']
        L.append(text(28, 58, world, 48, family="Barlow Condensed", weight=700))
        if era:
            L.append(text(30, 84, era, 15, weight=500))
        # scale bar
        mi = self.m.mi_per_px
        target = 100 * mi
        step = 10 ** math.floor(math.log10(target))
        nice = max((v for v in (step, 2 * step, 5 * step) if v <= target), default=step)
        bar = nice / mi / s
        L.append(f'<rect x="30" y="112" width="{bar:.1f}" height="7" fill="{INK}"/>')
        L.append(f'<rect x="{30 + bar / 2:.1f}" y="112" width="{bar / 2:.1f}" height="7" fill="{PANEL}" stroke="{INK}" stroke-width="1"/>')
        L.append(text(30, 140, "0", 12, weight=600))
        L.append(text(30 + bar, 140, f"{nice:g} {self.m.distance_unit}", 12, weight=600, anchor="middle"))
        # routes and stops
        x = 360
        L.append(text(x, 32, "Routes and stops", 17, family="Barlow Condensed", weight=700))
        items = [
            ("Land route", lambda cx, cy: f'<line x1="{cx - 14}" y1="{cy}" x2="{cx + 14}" y2="{cy}" stroke="{PANEL}" '
                                         f'stroke-width="6"/><line x1="{cx - 14}" y1="{cy}" x2="{cx + 14}" y2="{cy}" '
                                         f'stroke="{LAND}" stroke-width="3"/>'),
            ("Sea route", lambda cx, cy: f'<line x1="{cx - 14}" y1="{cy}" x2="{cx + 14}" y2="{cy}" stroke="{SEA}" '
                                        f'stroke-width="3" stroke-dasharray="7 4"/>'),
            ("Stop", lambda cx, cy: f'<circle cx="{cx}" cy="{cy}" r="7" fill="{PANEL}" stroke="{INK}" stroke-width="2"/>'),
            ("Market town",
             lambda cx, cy: f'<circle cx="{cx}" cy="{cy}" r="9" fill="{COIN}" stroke="{INK}" stroke-width="1.3"/>'
                            f'<circle cx="{cx}" cy="{cy}" r="5" fill="{PANEL}" stroke="{INK}" stroke-width="1.3"/>'),
            ("Capital", lambda cx, cy: f'<circle cx="{cx}" cy="{cy}" r="11" fill="{PANEL}" stroke="{INK}" stroke-width="1.6"/>'
                                      f'<circle cx="{cx}" cy="{cy}" r="6" fill="{PANEL}" stroke="{INK}" stroke-width="2"/>'),
            ("Fort", lambda cx, cy: f'<rect x="{cx - 6.5}" y="{cy - 6.5}" width="13" height="13" fill="{PANEL}" '
                                   f'stroke="{INK}" stroke-width="2"/>'),
            ("Neutral station (built at setup)",
             lambda cx, cy: f'<circle cx="{cx}" cy="{cy}" r="7" fill="{PANEL}" stroke="{INK}" stroke-width="2"/>'
                            f'<path d="M{cx - 9},{cy - 9} L{cx + 9},{cy + 9} M{cx - 9},{cy + 9} L{cx + 9},{cy - 9}" '
                            f'stroke="{INK}" stroke-width="3" stroke-linecap="round"/>'),
            ("Air infrastructure allowed",
             lambda cx, cy: f'<circle cx="{cx}" cy="{cy}" r="10" fill="#FFFFFF" stroke="{INK}" stroke-width="1.4"/>'
                            + icon("air", cx - 7, cy - 7, 14, INK, 1.6)),
        ]
        for k, (label, draw) in enumerate(items):
            col, row = divmod(k, 4)
            cx, cy = x + 16 + col * 250, 58 + row * 30
            L.append(draw(cx, cy))
            L.append(text(cx + 24, cy + 5, label, 13, weight=500))
        # stars
        x = 900
        L.append(text(x, 32, "Event stars", 17, family="Barlow Condensed", weight=700))
        for k, (label, fill) in enumerate((("On a land route", LAND), ("On a sea route", SEA),
                                           ("Remote: read by air", "#FFFFFF"))):
            cy = 58 + k * 30
            L.append(star(x + 14, cy, 9, fill, INK, 1.4))
            L.append(text(x + 32, cy + 5, label, 13, weight=500))
        # decks
        x = 1110
        L.append(text(x, 32, "Commission decks", 17, family="Barlow Condensed", weight=700))
        sts = [s for s in self.m.live("states") if s.get("i")]
        cols = max(1, math.ceil(len(sts) / 4))
        cw = min(200, (1863 - x - 20) / cols)
        for k, st in enumerate(sts):
            col, row = divmod(k, 4)
            cx, cy = x + col * cw, 46 + row * 30
            L.append(f'<rect x="{cx}" y="{cy}" width="22" height="22" rx="4" fill="{st.get("color", "#ccc")}" '
                     f'stroke="{INK}" stroke-width="1.4"/>')
            L.append(text(cx + 30, cy + 16, st["name"], 13, weight=600))
        L.append("</g>")
        return "".join(L)

    # ------------------------------------------------------------------ assemble
    def crop_box(self, margin: float = 0.03) -> tuple[float, float, float, float]:
        """Map area worth printing: the land and every stop, plus a margin; the whole map when
        that is most of it anyway."""
        grid = self.m.data["grid"]
        xs = [p[0] for p, h in zip(grid["points"], self.m.data["grid_h"]) if h >= 20] + [s.x for s in self.net.stops.values()]
        ys = [p[1] for p, h in zip(grid["points"], self.m.data["grid_h"]) if h >= 20] + [s.y for s in self.net.stops.values()]
        if not xs:
            return 0, 0, self.W, self.H
        pad = margin * max(self.W, self.H)
        x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
        x1, y1 = min(self.W, max(xs) + pad), min(self.H, max(ys) + pad)
        if (x1 - x0) * (y1 - y0) > 0.85 * self.W * self.H:
            return 0, 0, self.W, self.H
        return x0, y0, x1, y1

    def render(self, crop: bool = True) -> str:
        x0, y0, x1, y1 = self.crop_box() if crop else (0, 0, self.W, self.H)
        cw, ch = x1 - x0, y1 - y0
        self.view = (x0, y0, x1, y1)
        legend_h = 175 * cw / 1863.0
        bodies, state_labels = self._states()
        zones, zone_labels = self._zones()
        parts = [self._land(), zones, bodies, state_labels, zone_labels, self._seas(), self._links(),
                 self._stars(), self._stops(), self._stop_labels()]
        H = ch + legend_h
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{cw:.0f}" height="{H:.0f}" '
                f'viewBox="0 0 {cw:.1f} {H:.1f}"><title>{esc(self.m.name)} board</title>'
                f'<clipPath id="mapclip"><rect width="{cw:.1f}" height="{ch:.1f}"/></clipPath>'
                f'<g clip-path="url(#mapclip)"><g transform="translate({-x0:.1f} {-y0:.1f})">{"".join(parts)}</g>'
                f'<rect x="1" y="1" width="{cw - 2:.1f}" height="{ch - 2:.1f}" fill="none" stroke="{INK}" stroke-width="2"/></g>'
                f'{self._legend(ch, legend_h, cw)}</svg>')
