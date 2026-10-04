"""Read Watabou exports: City Generator and Village Generator GeoJSON, Dwellings JSON.

Formats confirmed from samples:
  * City Generator (values.generator == "mfcg", 0.11.5): adrer.json
  * Village Generator (values.generator == "vg", 1.6.9): bayfshear.json
  * Dwellings (top-level "floors" and "exit"): house_on_the_hill.json
  * One Page Dungeon (version 1.2.7: title, story, rects, doors, notes, columns, water):
    halls_of_the_diamond_king.json. The export carries no seed, so a dungeon is tied to
    its map marker by filename (dungeon-<marker>.json) or the content manifest.

Watabou units behave as metres. Exports drop marks added by the user, so a chosen
building is identified by geometry (index, area, distance to a road).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .geometry import ring_area, ring_centroid


class SampleNeeded(RuntimeError):
    """Raised for a file type whose structure has not been confirmed from a sample."""


# ---------------------------------------------------------------------- towns
@dataclass
class Building:
    index: int
    ring: list
    area: float
    centroid: tuple[float, float]


@dataclass
class Town:
    path: Path
    generator: str          # "mfcg" (city) or "vg" (village)
    version: str
    buildings: list[Building]
    roads: list[dict]       # {"width": float, "points": [...]}, widest first
    districts: list[dict]   # {"name": str, "ring": [...]}
    squares: list[list]
    temples: list[list]     # "prisms"
    piers: list[dict]       # "planks"
    walls: list[dict]
    fields: int
    trees: int
    water: bool

    @property
    def kind(self) -> str:
        return "city" if self.generator == "mfcg" else "village"

    def main_roads(self) -> list[dict]:
        widest = self.roads[0]["width"] if self.roads else 0
        return [r for r in self.roads if r["width"] >= widest - 1e-6]


def _layers(doc: dict) -> dict:
    return {f.get("id"): f for f in doc.get("features", [])}


def _geoms(layer: dict | None) -> list[dict]:
    return (layer or {}).get("geometries") or []


def _polys(layer: dict | None) -> list:
    return (layer or {}).get("coordinates") or []


def load_town(path: str | Path, doc: dict | None = None) -> Town:
    path = Path(path)
    doc = doc or json.loads(path.read_text(encoding="utf-8"))
    L = _layers(doc)
    values = L.get("values", {})
    gen = values.get("generator")
    if gen not in ("mfcg", "vg"):
        raise ValueError(f"{path.name}: unknown Watabou generator {gen!r}")
    buildings = []
    for i, poly in enumerate(_polys(L.get("buildings"))):
        ring = poly[0]
        buildings.append(Building(i, ring, ring_area(ring), ring_centroid(ring)))
    roads = sorted(({"width": g.get("width", 0), "points": g["coordinates"]} for g in _geoms(L.get("roads"))),
                   key=lambda r: -r["width"])
    districts = [{"name": g.get("name", ""), "ring": g["coordinates"][0]} for g in _geoms(L.get("districts"))]
    return Town(
        path=path, generator=gen, version=values.get("version", ""), buildings=buildings, roads=roads,
        districts=districts, squares=[p[0] for p in _polys(L.get("squares"))],
        temples=[p[0] for p in _polys(L.get("prisms"))],
        piers=[{"width": g.get("width", 0), "points": g["coordinates"]} for g in _geoms(L.get("planks"))],
        walls=[{"width": g.get("width", 0), "ring": g["coordinates"][0]} for g in _geoms(L.get("walls"))],
        fields=len(_polys(L.get("fields"))), trees=len(_polys(L.get("trees"))),
        water=bool(_polys(L.get("water"))),
    )


# ------------------------------------------------------------------ dwellings
STEP = {"n": (-1, 0), "s": (1, 0), "w": (0, -1), "e": (0, 1)}  # (di, dj); i = row, j = column


@dataclass
class Room:
    floor: int
    index: int
    name: str | None
    cells: set

    @property
    def key(self) -> str:
        return f"{self.floor}:{self.index}"


@dataclass
class Dwelling:
    path: Path
    rooms: dict[str, Room]
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (room, room|"outside", kind)
    entrance: str | None = None
    exit_dir: str | None = None   # wall of the entrance room the front door is on (n, s, e, w)
    windows: dict[str, int] = field(default_factory=dict)

    def neighbours(self, key: str) -> list[tuple[str, str]]:
        out = []
        for a, b, kind in self.links:
            if a == key:
                out.append((b, kind))
            elif b == key:
                out.append((a, kind))
        return out


def load_dwelling(path: str | Path, doc: dict | None = None) -> Dwelling:
    path = Path(path)
    doc = doc or json.loads(path.read_text(encoding="utf-8"))
    rooms: dict[str, Room] = {}
    where: dict[tuple[int, int, int], str] = {}  # (floor, i, j) -> room key
    for fl in doc["floors"]:
        lv = fl["level"]
        for k, r in enumerate(fl["rooms"]):
            cells = {(c["i"], c["j"]) for c in r["cells"]}
            room = Room(lv, k, r.get("name"), cells)
            rooms[room.key] = room
            for c in cells:
                where[(lv, *c)] = room.key
    dw = Dwelling(path, rooms)
    for fl in doc["floors"]:
        lv = fl["level"]
        for door in fl.get("doors", []):
            cell, d = door["edge"]["cell"], door["edge"]["dir"]
            a = where.get((lv, cell["i"], cell["j"]))
            di, dj = STEP[d]
            b = where.get((lv, cell["i"] + di, cell["j"] + dj), "outside")
            kind = "door" if door.get("type") == "REGULAR" else "doorway"
            if a:
                dw.links.append((a, b, kind))
        for w in fl.get("windows", []):
            key = where.get((lv, w["cell"]["i"], w["cell"]["j"]))
            if key:
                dw.windows[key] = dw.windows.get(key, 0) + 1
        for st in fl.get("stairs", []):
            if st.get("up"):
                a = where.get((lv, st["cell"]["i"], st["cell"]["j"]))
                b = where.get((lv + 1, st["cell"]["i"], st["cell"]["j"]))
                if a and b:
                    dw.links.append((a, b, "stairs"))
    ex = doc.get("exit")
    if ex:
        dw.entrance = where.get((0, ex["cell"]["i"], ex["cell"]["j"]))
        dw.exit_dir = ex.get("dir")
        if dw.entrance:
            dw.links.append((dw.entrance, "outside", "front door"))
    return dw


# ------------------------------------------------------------------- dungeons
# Each door also appears as a 1x1 rect at the door's own position; those are dropped
# as chambers. Door types 0-9 are interpreted in interiors.py.
@dataclass
class Chamber:
    index: int
    x: int
    y: int
    w: int
    h: int
    rotunda: bool
    notes: list[str] = field(default_factory=list)
    columns: int = 0
    water: int = 0

    @property
    def corridor(self) -> bool:
        return min(self.w, self.h) == 1

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


@dataclass
class Dungeon:
    path: Path
    version: str
    title: str
    story: str
    chambers: list[Chamber]
    links: list[tuple[int, int | str, int]]  # (chamber, chamber or "outside", door type)
    entrances: list[int]
    link_dirs: list[tuple[int, int]] = field(default_factory=list)  # step from first to second chamber

    def neighbours(self, index: int) -> list[tuple[int | str, int]]:
        out = []
        for a, b, t in self.links:
            if a == index:
                out.append((b, t))
            elif b == index:
                out.append((a, t))
        return out


def load_dungeon(path: str | Path, doc: dict | None = None) -> Dungeon:
    path = Path(path)
    doc = doc or json.loads(path.read_text(encoding="utf-8"))
    door_cells = {(d["x"], d["y"]) for d in doc["doors"]}
    rects = [r for r in doc["rects"] if not (r["w"] == 1 and r["h"] == 1 and (r["x"], r["y"]) in door_cells)]
    chambers = [Chamber(i, r["x"], r["y"], r["w"], r["h"], bool(r.get("rotunda"))) for i, r in enumerate(rects)]

    def at(px: float, py: float) -> int | None:
        hits = [c for c in chambers if c.contains(px, py)]
        return min(hits, key=lambda c: c.w * c.h).index if hits else None

    for n in doc.get("notes", []):
        k = at(n["pos"]["x"], n["pos"]["y"])
        if k is not None:
            chambers[k].notes.append(f"{n.get('ref', '')}. {n['text']}".strip(". "))
    for key in ("columns", "water"):
        for c in doc.get(key, []):
            k = at(c["x"], c["y"])
            if k is not None:
                setattr(chambers[k], key, getattr(chambers[k], key) + 1)
    links, entrances, dirs = [], [], []
    for d in doc["doors"]:
        x, y, dx, dy = d["x"], d["y"], d["dir"]["x"], d["dir"]["y"]
        ahead, behind = at(x + dx, y + dy), at(x - dx, y - dy)
        if ahead is not None and behind is not None and ahead != behind:
            links.append((behind, ahead, d["type"]))
            dirs.append((dx, dy))
        elif (ahead is None) != (behind is None):
            inside = ahead if ahead is not None else behind
            links.append((inside, "outside", d["type"]))
            dirs.append((-dx, -dy) if ahead is not None else (dx, dy))
            entrances.append(inside)
    return Dungeon(path, doc.get("version", ""), doc.get("title", ""), doc.get("story", ""),
                   chambers, links, entrances, dirs)


# ------------------------------------------------------------------- dispatch
def sniff(path: str | Path) -> tuple[str, dict]:
    """Return (kind, parsed document); kind is city, village, dwelling or dungeon."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, dict) and "floors" in doc:
        return "dwelling", doc
    if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
        gen = _layers(doc).get("values", {}).get("generator")
        if gen == "mfcg":
            return "city", doc
        if gen == "vg":
            return "village", doc
    if isinstance(doc, dict) and {"rects", "doors", "notes"} <= doc.keys():
        return "dungeon", doc
    return "unknown", doc


def load(path: str | Path):
    kind, doc = sniff(path)
    if kind in ("city", "village"):
        return load_town(path, doc)
    if kind == "dwelling":
        return load_dwelling(path, doc)
    if kind == "dungeon":
        return load_dungeon(path, doc)
    raise ValueError(f"{Path(path).name}: not a recognised Watabou export")
