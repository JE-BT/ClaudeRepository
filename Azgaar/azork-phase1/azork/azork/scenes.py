"""Build playable scenes from a world's files.

Scene ids:
  dwelling:<file stem>   a house placed in a burg (e.g. dwelling:house_on_the_hill)
  dungeon:<marker id>    a One Page Dungeon placed at a map marker (e.g. dungeon:5)
Each scene gets an outside room described from map data, the starting kit and load
limits from content/items.json, and the overlay content/places/<scene>.json if present.
The plan clock starts where the journey passes nearest the scene.
"""
from __future__ import annotations

import json
import math

from . import interiors, setup, watabou
from .engine.model import Room, Thing, World
from .geometry import locate_on_polyline
from .journey import Journey
from .worlds import World as Files


def list_scenes(files: Files) -> list[str]:
    out = [f"dwelling:{f.path.stem}" for f in files.dwellings() if f.burg is not None]
    out += [f"dungeon:{f.marker}" for f in files.watabou if f.kind == "dungeon" and f.marker is not None]
    return out


def _content(files: Files, name: str) -> dict:
    path = files.content_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _place_text(files: Files, burg: dict) -> str:
    m = files.map
    state = m.state(burg.get("state", 0)).get("fullName") or m.state(burg.get("state", 0))["name"]
    culture = m.culture(burg.get("culture", 0))["name"]
    pop = round(burg["population"] * m.settings["units"]["population"]["scale"])
    biome = m.data["biomes"][m.cell("biome")[burg["cell"]]]["name"].lower()
    return (f"{burg['name']} is a {burg.get('group', 'settlement')} of about {pop:,} people in {state}, "
            f"home to {culture} folk, set in {biome} country.")


def _nearest_route(m, x: float, y: float) -> str | None:
    best, name = math.inf, None
    for r in m.live("routes"):
        if r.get("group") == "searoutes":
            continue
        off, _ = locate_on_polyline((x, y), r["points"])
        if off < best:
            best, name = off, r.get("name") or None
    return name if best * m.mi_per_px < 1 else None


def _start_time(j: Journey, kind: str, ident: int) -> tuple[float, float]:
    near = next((n for n in j.nearby(200) if n.kind == kind and n.id == ident), None)
    if not near:
        return 0.0, j.stages[0].lat
    st = j.stages[near.stage]
    t = j.when(near.stage, near.along_mi) + (near.offset_mi / st.speed if st.speed else 0)
    return t, st.lat


def build(files: Files, scene: str) -> World:
    m = files.map
    cfg = setup.world_settings(files)
    j = Journey(m, 0, cfg["start_day_of_year"])
    w = World(files.name, scene)
    w.clock = j.clock
    items = _content(files, "items.json")
    w.load.update(items.get("load", {}))
    kind, _, ident = scene.partition(":")
    if kind == "dwelling":
        f = next((x for x in files.dwellings() if x.path.stem == ident), None)
        if not f or f.burg is None:
            raise ValueError(f"No placed dwelling '{ident}'. Scenes: {', '.join(list_scenes(files))}")
        burg = m.burg(f.burg)
        label = f.label or "the house"
        road = _nearest_route(m, burg["x"], burg["y"])
        w.add_room(Room("outside", f"{road or 'The road'}, {burg['name']}",
                              f"{_place_text(files, burg)} Before you stands {label}.", area=burg["name"],
                              provenance="mixed"))
        w.player = "outside"
        interiors.add_dwelling(w, watabou.load_dwelling(f.path), "house", label, "outside")
        w.flags["title"] = f"{label}, {burg['name']}"
        w.start_t, w.lat = _start_time(j, "burg", f.burg)
    elif kind == "dungeon":
        marker_id = int(ident)
        f = next((x for x in files.watabou if x.kind == "dungeon" and x.marker == marker_id), None)
        if not f:
            raise ValueError(f"No dungeon file for marker {marker_id}. Scenes: {', '.join(list_scenes(files))}")
        mk = next(x for x in m.live("markers") if x["i"] == marker_id)
        d = watabou.load_dungeon(f.path)
        near = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), (mk["x"], mk["y"])))
        miles = math.dist((near["x"], near["y"]), (mk["x"], mk["y"])) * m.mi_per_px
        biome = m.data["biomes"][m.cell("biome")[mk["cell"]]]["name"].lower()
        state = m.state(m.cell("state")[mk["cell"]])["name"]
        story = d.story.split(". ", 1)
        rumour = f" It is said that {story[1][0].lower() + story[1][1:]}" if len(story) > 1 else ""
        w.add_room(Room("outside", f"Before {d.title}",
                        f"Stairs lead down into {d.title}, in {biome} about {miles:.0f} miles from "
                        f"{near['name']}, {state}.{rumour}", area=state, provenance="mixed"))
        rear = None
        if len(d.entrances) > 1:
            rear = w.add_room(Room("rear", f"Behind {d.title}", f"A second stair leads down into {d.title}.",
                                   area=state, provenance="data")).id
            a, b = d.chambers[d.entrances[0]], d.chambers[d.entrances[1]]
            back = interiors.compass(b.x - a.x, b.y - a.y)
            interiors._link(w, "outside", rear, back)
        interiors.add_dungeon(w, d, "dgn", "outside", rear, m.seed)
        w.player = "outside"
        w.flags["title"] = d.title
        w.start_t, w.lat = _start_time(j, "marker", marker_id)
    else:
        raise ValueError(f"Unknown scene '{scene}'. Scenes: {', '.join(list_scenes(files))}")
    w.flags["exit_text"] = "The way on leads back to the journey; the overworld comes in a later phase."
    for spec in items.get("start_inventory", []):
        add_spec(w, spec, "player")
    apply_overlay(w, _content(files, f"places/{scene.replace(':', '-')}.json"))
    return w


def add_spec(w: World, spec: dict, location: str | None) -> Thing:
    t = Thing(spec["id"], spec["name"], spec.get("nouns") or [spec["name"].split()[-1]],
              spec.get("adjectives", []), spec.get("description", ""), location, float(spec.get("weight", 0)),
              set(spec.get("flags", [])), spec.get("text", ""), spec.get("unlocks", []),
              {k: v for k, v in spec.items() if k in ("fuel", "hazard", "hint", "talk", "here", "value", "search")},
              spec.get("provenance", "draft"))
    return w.add_thing(t)


def _room_ref(w: World, ref: str) -> str | None:
    if ref in w.rooms:
        return ref
    if ref.startswith("note:"):
        n = ref.split(":", 1)[1]
        t = next((t for t in w.things.values() if t.props.get("note") == n), None)
        return t.location if t else None
    return next((k for k, r in w.rooms.items() if r.name.lower() == ref.lower()), None)


def apply_overlay(w: World, ov: dict) -> None:
    """Content-pack overlay: room additions, new things, and changes to generated things."""
    for ref, spec in ov.get("rooms", {}).items():
        rid = _room_ref(w, ref)
        if rid and spec.get("add"):
            w.rooms[rid].description += " " + spec["add"]
    for spec in ov.get("things", []):
        where = spec.get("in")
        loc = "player" if where == "player" else (_room_ref(w, where) if where else None)
        if where and where in w.things:
            loc = where
        add_spec(w, spec, loc)
    for ref, change in ov.get("modify", {}).items():
        targets = [t for t in w.things.values()
                   if t.id == ref or (ref.startswith("note:") and t.id.split(":")[-1] == "note" + ref[5:])]
        for t in targets[:1]:
            for k in ("name", "description", "text"):
                if k in change:
                    setattr(t, k, change[k])
            if "nouns" in change:
                t.nouns = change["nouns"]
            if "adjectives" in change:
                t.adjectives = change["adjectives"]
            if "weight" in change:
                t.weight = float(change["weight"])
            t.flags |= set(change.get("add_flags", []))
            t.flags -= set(change.get("remove_flags", []))
            t.props.update({k: v for k, v in change.items() if k in ("hazard", "hint", "talk", "here", "value")})
            t.provenance = change.get("provenance", t.provenance)
