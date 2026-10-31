"""Optional landscape layers from Azgaar's Cells GeoJSON export (biomes, history zones).

The .map stores no pack-cell polygons; the Cells export does (in longitude and latitude, turned
back into map pixels with the inverse of Azgaar's getLongitude/getLatitude, as in azrpg). The file
is matched to the map by content. Without it, or without shapely, the board is still complete;
it just loses its biome tint and history zones.
"""
from __future__ import annotations

import json
from pathlib import Path

from .mapfile import AzgaarMap


class CellGeo:
    def __init__(self, path: Path, m: AzgaarMap):
        co = m.settings["geography"]["coordinates"]
        self.lonW, self.lonT, self.latN, self.latT = co["lonW"], co["lonT"], co["latN"], co["latT"]
        self.width, self.height = m.settings["graph"]["width"], m.settings["graph"]["height"]
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        self.path = Path(path)
        self.props, self.rings = {}, {}
        for f in doc.get("features", []):
            p = f["properties"]
            self.props[p["id"]] = p
            self.rings[p["id"]] = [self.to_px(lon, lat) for lon, lat in f["geometry"]["coordinates"][0]]

    def centroid(self, c):
        ring = self.rings[c]
        xs, ys = zip(*ring)
        return sum(xs) / len(xs), sum(ys) / len(ys)

    def to_px(self, lon, lat):
        return (lon - self.lonW) / self.lonT * self.width, (self.latN - lat) / self.latT * self.height

    def matches(self, m: AzgaarMap) -> bool:
        if len(self.props) != m.cell_count:
            return False
        for key in ("state", "biome", "culture"):
            arr = m.cell(key)
            if sum(1 for i, p in self.props.items() if p.get(key) != arr[i]) > 0:
                return False
        return True

    def union(self, cells, simplify: float = 0.6):
        try:
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
        except ImportError:
            return None
        polys = []
        for c in cells:
            ring = self.rings.get(c)
            if ring and len(ring) >= 4:
                p = Polygon(ring)
                polys.append(p if p.is_valid else p.buffer(0))
        if not polys:
            return None
        return unary_union(polys).buffer(0.25).buffer(-0.25).simplify(simplify)


def find_cells(folder: Path, m: AzgaarMap) -> CellGeo | None:
    for p in sorted(folder.glob("*Cells*.geojson"), key=lambda p: p.name, reverse=True):
        try:
            g = CellGeo(p, m)
            if g.matches(m):
                return g
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    return None


def geom_to_path(geom) -> str:
    """Shapely (Multi)Polygon -> SVG path data (even-odd holes)."""
    if geom is None or geom.is_empty:
        return ""
    polys = getattr(geom, "geoms", [geom])
    parts = []
    for p in polys:
        if p.geom_type != "Polygon":
            continue
        for ring in [p.exterior, *p.interiors]:
            xs = list(ring.coords)
            if len(xs) < 3:
                continue
            parts.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xs) + "Z")
    return "".join(parts)
