"""Read Azgaar's 'Cells' GeoJSON export.

The .map stores no pack-cell coordinates or adjacency; this export supplies both (a polygon per
cell and a 'neighbors' list). Coordinates are longitude/latitude, converted back to map pixels
with the inverse of Azgaar's getLongitude/getLatitude (src/utils/commonUtils.ts). The export may
be saved on a different day from the .map, or carry a different file name (Pyeongak's is named
after the map's lore name, "Persia"), so it is matched by content: cell count and five cell
attributes must agree with the .map.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .mapfile import AzgaarMap


class CellsFormatError(ValueError):
    pass


def ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        xs, ys = zip(*ring)
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (3 * a), cy / (3 * a)


class CellGeo:
    CHECKED = ("state", "province", "culture", "religion", "biome")

    def __init__(self, path: str | Path, m: AzgaarMap):
        self.path = Path(path)
        co = m.settings["geography"]["coordinates"]
        width, height = m.settings["graph"]["width"], m.settings["graph"]["height"]
        self.lonW, self.lonT, self.latN, self.latT = co["lonW"], co["lonT"], co["latN"], co["latT"]
        self.width, self.height = width, height

        doc = json.loads(self.path.read_text(encoding="utf-8"))
        feats = doc.get("features", [])
        if not feats or "neighbors" not in feats[0].get("properties", {}):
            raise CellsFormatError(f"{self.path.name}: not an Azgaar cells export (no 'neighbors')")
        self.props: dict[int, dict] = {}
        self.neighbors: dict[int, list[int]] = {}
        self.rings: dict[int, list[tuple[float, float]]] = {}
        self.centroid: dict[int, tuple[float, float]] = {}
        for f in feats:
            p = f["properties"]
            i = p["id"]
            self.props[i] = p
            self.neighbors[i] = list(p["neighbors"])
            ring = [self.to_px(lon, lat) for lon, lat in f["geometry"]["coordinates"][0]]
            self.rings[i] = ring
            self.centroid[i] = ring_centroid(ring)

    def to_px(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lonW) / self.lonT * self.width, (self.latN - lat) / self.latT * self.height

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self.lonW + x / self.width * self.lonT, self.latN - y / self.height * self.latT

    def __len__(self) -> int:
        return len(self.props)

    def is_water(self, cell: int) -> bool:
        """Cell 'type' is the Azgaar feature type: ocean, lake, or island (any landmass)."""
        return self.props[cell].get("type") in ("ocean", "lake")

    def nearest(self, x: float, y: float, cells) -> int:
        return min(cells, key=lambda c: (self.centroid[c][0] - x) ** 2 + (self.centroid[c][1] - y) ** 2)

    def check_against(self, m: AzgaarMap) -> list[str]:
        """Return a list of disagreements with the .map (empty when consistent)."""
        if len(self) != m.cell_count:
            return [f"{self.path.name} has {len(self)} cells, the .map has {m.cell_count}"]
        problems = []
        for key in self.CHECKED:
            arr = m.cell(key)
            bad = sum(1 for i, p in self.props.items() if p.get(key) != arr[i])
            if bad:
                problems.append(f"{bad} cells differ on '{key}'")
        return problems

    def ft_to_h(self, ft: float, exponent: float) -> float:
        """Invert Azgaar's getHeight for land (feet): h = 18 + (ft / 3.281) ** (1 / exponent)."""
        if ft <= 0:
            return 20.0
        return 18 + (ft / 3.281) ** (1 / exponent)


def find_cells_file(folder: Path, m: AzgaarMap) -> Path | None:
    """The newest *Cells*.geojson in the folder whose content matches the map."""
    cands = sorted(folder.glob("*Cells*.geojson"), key=lambda p: p.name, reverse=True)
    for p in cands:
        try:
            if not CellGeo(p, m).check_against(m):
                return p
        except (CellsFormatError, json.JSONDecodeError, KeyError):
            continue
    return None


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
