"""What a journey corridor needs before its story is generated, and what can wait.

Required (strict) - the story is anchored on these, so all must be present:
  * stops: burgs where a stage starts, ends or stays (or the nearest burg within strict_mi);
  * canon: burgs the ledger anchors to (by burg id, or by a cell that holds a burg) inside the corridor;
  * sites: markers within strict_mi of the track whose note carries a Watabou generator (dungeons).
Expansion (on demand) - every other burg and marker within corridor_mi. The engine
describes these from map data while passing; entering one pauses play and asks for
its file, then the area is generated before play continues.
Dwellings are never required: the engine builds interiors from building size and
uses a Dwellings export where one has been assigned.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from . import ledger as ledger_mod
from . import links
from .cells import CellGeo
from .journey import Journey
from .worlds import World

DEFAULTS = {"strict_mi": 2.0, "corridor_mi": 40.0, "start_day_of_year": 80, "transports_allowed": None}


@dataclass
class Request:
    tier: str          # required or expansion
    kind: str          # town or dungeon
    id: int            # burg id or marker id
    name: str
    reasons: list[str]
    generator: str     # city, village, dungeon
    link: str
    filename: str
    present: str | None = None
    stage: int | None = None
    along_mi: float | None = None
    offset_mi: float | None = None


def world_settings(world: World) -> dict:
    path = world.content_dir / "world.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**DEFAULTS, **data}


def town_filename(name: str) -> str:
    return "".join(c for c in name.lower().replace(" ", "_") if c.isalnum() or c in "_-") + ".json"


def plan(world: World, journey_index: int = 0) -> tuple[Journey, list[Request]]:
    cfg = world_settings(world)
    m = world.map
    if not world.cells_path:
        raise FileNotFoundError("The cells GeoJSON export is required (Azgaar: Tools > Export > GeoJSON > Cells)")
    geo = CellGeo(world.cells_path, m)
    j = Journey(m, journey_index, cfg["start_day_of_year"])
    near = {(n.kind, n.id): n for n in j.nearby(cfg["corridor_mi"])}
    reasons: dict[tuple[str, int], list[str]] = {}

    # stops
    burg_at = {b["cell"]: b for b in m.live_burgs()}
    for st in j.stages:
        for p in (st.points[0], st.points[-1]):
            b = burg_at.get(p[2])
            if not b:
                cand = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), p[:2]))
                if math.dist((cand["x"], cand["y"]), p[:2]) * m.mi_per_px <= cfg["strict_mi"]:
                    b = cand
            if b:
                why = f"stop: stage {st.index} {st.name}"
                reasons.setdefault(("burg", b["i"]), [])
                if why not in reasons[("burg", b["i"])]:
                    reasons[("burg", b["i"])].append(why)
    # canon
    if world.main_ledger:
        led = ledger_mod.parse(world.main_ledger)
        for e in led.entries:
            for a in e.anchors:
                bid = a.id if a.kind == "burg" else burg_at[a.id]["i"] if a.kind == "cell" and a.id in burg_at else None
                why = f"canon: {e.name}"
                if bid is not None and ("burg", bid) in near and why not in reasons.get(("burg", bid), []):
                    reasons.setdefault(("burg", bid), []).append(why)
    # sites
    for key, n in near.items():
        if n.kind == "marker" and n.offset_mi <= cfg["strict_mi"] and "one-page-dungeon" in (n.extra.get("note") or ""):
            reasons.setdefault(key, []).append(f"site on the track, stage {n.stage}")

    towns = world.towns()
    dungeons = {w.marker: w for w in world.watabou if w.kind == "dungeon" and w.marker is not None}
    out: list[Request] = []
    keys = set(reasons) | set(near)
    for key in keys:
        kind, i = key
        n = near.get(key)
        tier = "required" if key in reasons else "expansion"
        if kind == "burg":
            b = m.burg(i)
            gen, link = links.burg_link(m, geo, b)
            have = towns.get(i)
            out.append(Request(tier, "town", i, b["name"], reasons.get(key, []), gen, link,
                               town_filename(b["name"]), have.path.name if have else None,
                               n.stage if n else None, n.along_mi if n else None, n.offset_mi if n else None))
        else:
            mk = next(x for x in m.live("markers") if x["i"] == i)
            if "one-page-dungeon" not in (mk.get("note") or "") and tier == "expansion":
                continue  # data-only site; the engine describes it from the marker
            have = dungeons.get(i)
            out.append(Request(tier, "dungeon", i, mk.get("name") or mk["type"], reasons.get(key, []), "dungeon",
                               links.dungeon_link(m, mk), f"dungeon-{i}.json", have.path.name if have else None,
                               n.stage if n else None, n.along_mi if n else None, n.offset_mi if n else None))
    out.sort(key=lambda r: (r.tier != "required", r.stage if r.stage is not None else -1, r.along_mi or 0))
    return j, out


def expansion_message(world: World, r: Request) -> str:
    """What the engine shows when play reaches a place whose file is missing."""
    what = {"city": "City Generator", "village": "Village Generator", "dungeon": "One Page Dungeon",
            "custom": "the burg's custom link"}[r.generator]
    return (f"[Paused] {r.name} has not been generated yet.\n"
            f"  1. Open {what}: {r.link}\n"
            f"  2. Export as JSON and save it as {world.map_path.parent.name}/{r.filename} in the repository.\n"
            f"  3. Run: python -m azork setup {world.name}\n"
            f"Then resume your saved game.")
