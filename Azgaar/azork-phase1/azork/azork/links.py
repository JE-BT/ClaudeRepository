"""Watabou generator links for burgs and markers, ported from Azgaar's
src/generators/burgs-generator.ts (createWatabouCityLinks, createWatabouVillageLinks,
createWatabouDwellingLinks) so that a requested file matches the preview Azgaar shows.

Two inputs are approximations, because the .map does not store them:
  * a cell's haven (nearest water cell) comes from the cells GeoJSON neighbours;
  * island detection uses "every neighbour is water" instead of the feature size.
Both only affect coastal settlements (City 'sea' direction, Village 'estuary'/'island' tags).
Burgs with a custom link set in Azgaar keep that link.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlencode

from .cells import CellGeo
from .mapfile import AzgaarMap

ROUTE_RATE = {"roads": 0.2, "trails": 0.1, "searoutes": 0.2}


def _pop(m: AzgaarMap, burg: dict) -> int:
    u = m.settings["units"]["population"]
    return round(burg["population"] * u["scale"] * u["urbanization"]["rate"])


def _seed(m: AzgaarMap, burg: dict) -> str:
    return str(burg.get("MFCG") or m.seed + str(burg["i"]).zfill(4))


def _connections(m: AzgaarMap, cell: int) -> dict:
    return m.data["cell_routes"].get(str(cell)) or {}


def _route_group(m: AzgaarMap, route_id: int) -> str | None:
    r = next((r for r in m.data["routes"] if r.get("i") == route_id), None)
    return r["group"] if r else None


def is_crossroad(m: AzgaarMap, cell: int) -> bool:
    conn = _connections(m, cell)
    if len(conn) > 3:
        return True
    return sum(1 for rid in conn.values() if _route_group(m, rid) == "roads") > 2


def connectivity_rate(m: AzgaarMap, cell: int) -> float:
    conn = _connections(m, cell)
    if not conn:
        return 0
    return 0.8 + sum(ROUTE_RATE.get(_route_group(m, rid) or "", 0.1) for rid in conn.values())


def _grid_temp(m: AzgaarMap, x: float, y: float) -> int:
    pts = m.data["grid"]["points"]
    k = min(range(len(pts)), key=lambda i: (pts[i][0] - x) ** 2 + (pts[i][1] - y) ** 2)
    return m.data["grid_temp"][k]


def preview_kind(m: AzgaarMap, burg: dict) -> str | None:
    """watabou-city, watabou-village or None, from the burg's group settings."""
    groups = m.settings.get("burgs", {}).get("groups", [])
    g = next((g for g in groups if g["name"] == burg.get("group")), None)
    return g.get("preview") if g else None


def city_link(m: AzgaarMap, geo: CellGeo, burg: dict) -> str:
    cell = burg["cell"]
    dens = m.settings["units"]["population"]["urbanization"]["density"]
    scale = m.settings["units"]["population"]["scale"]
    size = min(max(math.ceil(2.13 * ((burg["population"] * scale) / dens) ** 0.385), 6), 100)
    river = 1 if m.cell("river")[cell] else 0
    coast = 1 if (burg.get("port") or 0) > 0 else 0
    arable = [1, 2, 3, 4, 5, 6, 7, 8] if river else [5, 6, 7, 8]
    citadel = int(burg.get("citadel") or 0)
    plaza = int(burg.get("plaza") or 0)
    params = {
        "name": burg.get("name", ""), "population": _pop(m, burg), "size": size, "seed": _seed(m, burg),
        "river": river, "coast": coast, "farms": int(m.cell("biome")[cell] in arable), "citadel": citadel,
        "urban_castle": int(bool(citadel) and burg["i"] % 2 == 0), "hub": int(is_crossroad(m, cell)),
        "plaza": plaza, "greens": plaza, "temple": int(burg.get("temple") or 0),
        "walls": int(burg.get("walls") or 0), "shantytown": int(burg.get("shanty") or 0), "style": "natural",
    }
    haven = geo.haven(cell) if coast else None
    if haven is not None:
        (x1, y1), (x2, y2) = geo.centroid[cell], geo.centroid[haven]
        deg = math.degrees(math.atan2(y2 - y1, x2 - x1))
        params["sea"] = round(min(abs(deg) / 180, 1), 2) if deg <= 0 else round(2 - min(deg / 180, 1), 2)
    return "https://watabou.github.io/city-generator/?" + urlencode(params)


def village_link(m: AzgaarMap, geo: CellGeo, burg: dict) -> str:
    cell, pop = burg["cell"], _pop(m, burg)
    haven = geo.haven(cell)
    tags = []
    if m.cell("river")[cell] and haven is not None:
        tags.append("estuary")
    elif haven is not None and all(geo.is_water(n) for n in geo.neighbors[cell]):
        tags.append("island,district")
    elif burg.get("port"):
        tags.append("coast")
    elif m.cell("conf")[cell]:
        tags.append("confluence")
    elif m.cell("river")[cell]:
        tags.append("river")
    elif pop < 200 and cell % 4 == 0:
        tags.append("pond")
    rate = connectivity_rate(m, cell)
    tags.append("highway" if rate > 1 else "dead end" if rate == 1 else "isolated")
    biome = m.cell("biome")[cell]
    arable = [1, 2, 3, 4, 5, 6, 7, 8] if m.cell("river")[cell] else [5, 6, 7, 8]
    if biome not in arable:
        tags.append("uncultivated")
    elif cell % 6 == 0:
        tags.append("farmland")
    temp = _grid_temp(m, burg["x"], burg["y"])
    if temp <= 0 or temp > 28 or (temp > 25 and cell % 3 == 0):
        tags.append("no orchards")
    if not burg.get("plaza"):
        tags.append("no square")
    if burg.get("walls"):
        tags.append("palisade")
    if pop < 100:
        tags.append("sparse")
    elif pop > 300:
        tags.append("dense")
    width = next(w for limit, w in ((1500, 1600), (1000, 1400), (500, 1000), (200, 800), (100, 600), (-1, 400))
                 if pop > limit)
    style = "sand" if biome in (1, 2) else "snow" if temp <= 5 or biome in (9, 10, 11) else "default"
    params = {"pop": pop, "name": burg.get("name", ""), "seed": m.seed + str(burg["i"]).zfill(4),
              "width": width, "height": round(width / 2.05), "style": style, "tags": ",".join(tags)}
    return "https://watabou.github.io/village-generator/?" + urlencode(params)


def dwelling_link(m: AzgaarMap, burg: dict) -> str:
    pop = _pop(m, burg)
    tags = (["large", "tall"] if pop > 200 else ["large"] if pop > 100 else ["tall"] if pop > 50
            else ["low"] if pop > 20 else ["small"])
    params = {"pop": pop, "name": "", "seed": m.seed + str(burg["i"]).zfill(4), "tags": ",".join(tags)}
    return "https://watabou.github.io/dwellings/?" + urlencode(params)


def dungeon_seed(m: AzgaarMap, marker: dict) -> str:
    """Seed from the marker note; otherwise Azgaar's pattern, map seed + cell id."""
    found = re.search(r"one-page-dungeon/\?seed=(\d+)", marker.get("note") or "")
    return found.group(1) if found else m.seed + str(marker["cell"])


def dungeon_link(m: AzgaarMap, marker: dict) -> str:
    return f"https://watabou.github.io/one-page-dungeon/?seed={dungeon_seed(m, marker)}"


def burg_link(m: AzgaarMap, geo: CellGeo, burg: dict) -> tuple[str, str | None]:
    """(generator, link) for a burg's town plan."""
    if burg.get("link"):
        return "custom", burg["link"]
    kind = preview_kind(m, burg)
    if kind == "watabou-city":
        return "city", city_link(m, geo, burg)
    if kind == "watabou-village":
        return "village", village_link(m, geo, burg)
    # groups without a preview (forts, monasteries...): Azgaar offers none; use the village tool
    return "village", village_link(m, geo, burg)
