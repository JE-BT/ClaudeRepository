"""Read Azgaar's 'Cells' GeoJSON export.

The .map stores no pack-cell coordinates or adjacency; this export supplies both
(polygon per cell and a 'neighbors' list). Coordinates are longitude/latitude,
converted back to map pixels with the inverse of Azgaar's getLongitude/getLatitude
(src/utils/commonUtils.ts). The export can be saved on a different day from the
.map, so it is checked against the map's own cell arrays before use.
"""
from __future__ import annotations

import json
from pathlib import Path

from .geometry import ring_centroid
from .mapfile import AzgaarMap


class CellsFormatError(ValueError):
    pass


class CellGeo:
    CHECKED = ("state", "province", "culture", "religion", "biome")

    def __init__(self, path: str | Path, m: AzgaarMap):
        self.path = Path(path)
        co = m.settings["geography"]["coordinates"]
        width, height = m.settings["graph"]["width"], m.settings["graph"]["height"]

        def to_px(lon: float, lat: float) -> tuple[float, float]:
            return (lon - co["lonW"]) / co["lonT"] * width, (co["latN"] - lat) / co["latT"] * height

        doc = json.loads(self.path.read_text(encoding="utf-8"))
        feats = doc.get("features", [])
        if not feats or "neighbors" not in feats[0].get("properties", {}):
            raise CellsFormatError(f"{self.path.name}: not an Azgaar cells export (no 'neighbors')")
        self.props: dict[int, dict] = {}
        self.neighbors: dict[int, list[int]] = {}
        self.centroid: dict[int, tuple[float, float]] = {}
        for f in feats:
            p = f["properties"]
            i = p["id"]
            self.props[i] = p
            self.neighbors[i] = list(p["neighbors"])
            ring = [to_px(lon, lat) for lon, lat in f["geometry"]["coordinates"][0]]
            self.centroid[i] = ring_centroid(ring)

    def __len__(self) -> int:
        return len(self.props)

    def is_water(self, cell: int) -> bool:
        """Cell 'type' is the Azgaar feature type: ocean, lake, or island (any landmass)."""
        return self.props[cell].get("type") in ("ocean", "lake")

    def haven(self, cell: int) -> int | None:
        """Closest water neighbour, as Azgaar's features generator defines a haven."""
        x, y = self.centroid[cell]
        water = [n for n in self.neighbors[cell] if self.is_water(n)]
        return min(water, key=lambda n: (self.centroid[n][0] - x) ** 2 + (self.centroid[n][1] - y) ** 2) if water else None

    def check_against(self, m: AzgaarMap) -> list[str]:
        """Return a list of disagreements with the .map (empty when consistent)."""
        problems = []
        if len(self) != m.cell_count:
            return [f"{self.path.name} has {len(self)} cells, the .map has {m.cell_count}"]
        for key in self.CHECKED:
            arr = m.cell(key)
            bad = sum(1 for i, p in self.props.items() if p.get(key) != arr[i])
            if bad:
                problems.append(f"{bad} cells differ on '{key}'")
        asym = sum(1 for a, ns in self.neighbors.items() for b in ns if a not in self.neighbors.get(b, ()))
        if asym:
            problems.append(f"{asym} one-way neighbour links")
        return problems
