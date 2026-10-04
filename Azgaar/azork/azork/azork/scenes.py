"""Build playable scenes from a world's files.

Scene ids:
  dwelling:<file stem>   a house placed in a burg (e.g. dwelling:house_on_the_hill)
  dungeon:<marker id>    a One Page Dungeon placed at a map marker (e.g. dungeon:5)
Order: compile rooms from data, apply the overlay's room changes (rename, purpose), furnish
rooms by purpose, add people and story things, then apply the overlay's things and changes.
The starting kit comes from content/items.json (or the package default); the plan clock starts
where the journey passes nearest the scene.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from . import furnish, interiors, npc, setup, towns, watabou
from .engine.model import Room, World
from .geometry import locate_on_polyline
from .interiors import TABLES
from .journey import Journey
from .names import NameGenerator
from .worlds import World as Files

DEFAULT_ITEMS = Path(__file__).with_name("data") / "default_items.json"


def list_scenes(files: Files) -> list[str]:
    out = [f"town:{b}" for b in sorted(files.towns())]
    out += [f"dwelling:{f.path.stem}" for f in files.dwellings() if f.burg is not None]
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
    return j.when(near.stage, near.along_mi) + (near.offset_mi / st.speed if st.speed else 0), st.lat


def _position(j: Journey, kind: str, ident: int) -> tuple[list, float]:
    """[stage, mile] of the nearest track point, and the hours off the track to get there."""
    near = next((n for n in j.nearby(200) if n.kind == kind and n.id == ident), None)
    if not near:
        return [0, 0.0], 0.0
    st = j.stages[near.stage]
    return [near.stage, near.along_mi], (near.offset_mi / st.speed if st.speed else 0.0)


def build(files: Files, scene: str, campaign=None, policy: str | None = None) -> World:
    m = files.map
    cfg = setup.world_settings(files)
    j = Journey(m, 0, cfg["start_day_of_year"])
    w = World(files.name, scene)
    w.clock, w.seed, w.loot = j.clock, f"{m.seed}:{scene}", TABLES["loot"]
    items = _content(files, "items.json") or json.loads(DEFAULT_ITEMS.read_text(encoding="utf-8"))
    w.load.update(items.get("load", {}))
    overlay = _content(files, f"places/{scene.replace(':', '-')}.json")
    kind, _, ident = scene.partition(":")
    context = {}
    if kind == "town":
        burg = m.burg(int(ident))
        plan = files.towns().get(burg["i"])
        people = []
        if campaign is not None:
            for line, e in campaign.story.elements_for(burg["i"], None, scene):
                if e.kind == "person":
                    home = bool(set(e.anchor.get("prefer", [])) & {"living room", "parlour", "library", "study"})
                    people.append((e.spec["name"], home))
        pol = policy or (campaign.policy if campaign is not None else "generate")
        if campaign is not None and burg["i"] in campaign.generated:
            pol = "generate"
        towns.build_town(w, files, burg, plan.path if plan else None, m.seed, people, pol)
        w.flags["title"] = burg["name"] + ("" if plan else " (made up: no town plan yet)")
        w.start_t, w.lat = _start_time(j, "burg", burg["i"])
        w.flags["anchor"] = {"burg": burg["i"]}
        w.flags["pos"], w.flags["offset_h"] = _position(j, "burg", burg["i"])
        topics = npc.lore(files, burg["x"], burg["y"], j)
        culture_base = m.culture(burg.get("culture", 0)).get("base", 0)
        context.update(_town_context(files, burg, j, campaign, cfg, topics))
        w.flags["shop"] = context.pop("shop")
        for f in files.dwellings():  # overlays of houses placed in this town, with their room ids moved
            if f.burg == burg["i"]:
                ov = _content(files, f"places/dwelling-{f.path.stem}.json")
                fix = lambda ref: f"house{f.path.stem}:" + ref[6:] if isinstance(ref, str) and ref.startswith("house:") else ref
                ov["rooms"] = {fix(k): v for k, v in ov.get("rooms", {}).items()}
                ov["things"] = [dict(t, **({"in": fix(t["in"])} if "in" in t else {})) for t in ov.get("things", [])]
                overlay.setdefault("rooms", {}).update(ov["rooms"])
                overlay.setdefault("things", []).extend(ov["things"])
    elif kind == "dwelling":
        f = next((x for x in files.dwellings() if x.path.stem == ident), None)
        if not f or f.burg is None:
            raise ValueError(f"No placed dwelling '{ident}'. Scenes: {', '.join(list_scenes(files))}")
        burg = m.burg(f.burg)
        label = f.label or f.path.stem.split("--")[-1].replace("_", " ")
        if label.strip().isdigit():
            label = "the house"
        road = _nearest_route(m, burg["x"], burg["y"])
        w.add_room(Room("outside", f"{road or 'The street'}, {burg['name']}",
                        f"{_place_text(files, burg)} Before you stands {label}.", area=burg["name"], provenance="mixed"))
        interiors.add_dwelling(w, watabou.load_dwelling(f.path), "house", label, "outside", m.seed)
        w.flags["title"] = f"{label}, {burg['name']}"
        w.start_t, w.lat = _start_time(j, "burg", f.burg)
        w.flags["anchor"] = {"burg": f.burg}
        w.flags["pos"], w.flags["offset_h"] = _position(j, "burg", f.burg)
        topics = npc.lore(files, burg["x"], burg["y"], j)
        culture_base = m.culture(burg.get("culture", 0)).get("base", 0)
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
        w.add_room(Room("outside", f"Before {d.title}", f"Stairs lead down into {d.title}, in {biome} about "
                        f"{miles:.0f} miles from {near['name']}, {state}.{rumour}", area=state, provenance="mixed"))
        rear = None
        if len(d.entrances) > 1:
            rear = w.add_room(Room("rear", f"Behind {d.title}", f"A second stair leads down into {d.title}.",
                                   area=state, provenance="data")).id
            a, b = d.chambers[d.entrances[0]], d.chambers[d.entrances[1]]
            interiors.link(w, "outside", rear, interiors.compass(b.x - a.x, b.y - a.y))
        info = interiors.add_dungeon(w, d, "dgn", "outside", rear, m.seed)
        w.flags.update({"title": d.title, "max_depth": info["max_depth"]})
        hint = f"A rough sketch of {d.title}. A mark is drawn deep to the {info['heart_dir']} of the entrance"
        locked = any("lockable" in t.flags for t in w.things.values())
        w.flags["heart_hint"] = hint + (", beyond a door drawn with a keyhole." if locked else ".")
        w.start_t, w.lat = _start_time(j, "marker", marker_id)
        w.flags["anchor"] = {"marker": marker_id}
        w.flags["pos"], w.flags["offset_h"] = _position(j, "marker", marker_id)
        topics = npc.lore(files, mk["x"], mk["y"], j)
        for subject, name in info["subjects"].items():
            key = "|".join(x.lower() for x in name.split() if len(x) > 2)
            topics[key] = (f"It sleeps in the deepest part, past the {('gate' if locked else 'dark')}. Don't wake it."
                           if subject == "creature" else f"If it's here at all, it's as deep as the place goes.")
        culture_base = m.culture(m.cell("culture")[mk["cell"]]).get("base", 0)
    else:
        raise ValueError(f"Unknown scene '{scene}'. Scenes: {', '.join(list_scenes(files))}")
    w.player = "outside"
    rumours = topics.get("_rumours") or ["Nothing worth repeating."]
    context["rumour"] = random.Random(w.seed).choice(rumours)
    context.setdefault("notices", " ".join(rumours[:3]))
    context["heart"] = w.flags.get("heart_hint", "")
    apply_room_overlay(w, overlay)
    furnish.furnish(w, m.seed, context)
    _people(w, files, overlay, topics, culture_base, kind)
    w.flags["exit_text"] = "The way on leads back to the journey; the overworld comes in a later phase."
    w.flags["sites"] = topics.get("_sites", {})
    if campaign is not None:
        w.start_t, msgs = campaign.travel_to(w.flags["pos"], w.flags["offset_h"])
        w.flags["arrival_msgs"] = msgs
    kit = campaign.inventory if campaign is not None and campaign.inventory is not None else items.get("start_inventory", [])
    for spec in kit:
        w.spawn(spec, "player", spec.get("id"))
    apply_overlay(w, overlay)
    if campaign is not None:
        place_story(w, campaign.story, scene)
    for t in w.things.values():
        if "person" in t.flags:
            t.props["lore"] = npc.as_props(topics)
    return w


CATALOGUE = [
    {"name": "bundle of rations", "nouns": ["rations", "bundle", "food"], "weight": 1.8, "flags": ["takeable", "food"],
     "uses": 6, "price": 6, "description": "Hard bread and dried meat for six days."},
    {"name": "flask of lamp oil", "nouns": ["flask", "oil"], "adjectives": ["lamp"], "weight": 0.5,
     "flags": ["takeable", "fuel_source"], "fuel": 240, "price": 3},
    {"name": "torch", "nouns": ["torch"], "weight": 0.5, "flags": ["takeable", "light"], "fuel": 60, "price": 1},
    {"name": "coil of rope", "nouns": ["rope", "coil"], "weight": 4.0, "flags": ["takeable"], "price": 4},
    {"name": "waterskin", "nouns": ["waterskin", "skin"], "weight": 1.2, "flags": ["takeable", "drink"], "uses": 6,
     "max_uses": 6, "price": 3},
]


def _town_context(files, burg, j, campaign, cfg, topics) -> dict:
    """Prices from the burg's market, notices, bounties and sailings."""
    m = files.map
    market_id = m.cell("market")[burg["cell"]] if m.cell("market") else 0
    markets = [x for x in m.data["markets"] if isinstance(x, dict)]
    mk = next((x for x in markets if x.get("i") == market_id), None)

    def mean(x):
        vals = [g["price"] for g in x["goods"].values()]
        return sum(vals) / len(vals) if vals else 1
    factor = mean(mk) / (sum(mean(x) for x in markets) / len(markets)) if mk and markets else 1.0
    shop = [dict(spec, price=max(1, round(spec["price"] * factor))) for spec in CATALOGUE]
    goods = {g["i"]: g for g in m.data["goods"] if isinstance(g, dict)}
    seen = set()
    for p in burg.get("production", []):
        gid = p.get("goodId")
        if gid and gid not in seen and gid in goods and len(seen) < 3 and "slave" not in goods[gid]["name"].lower():
            seen.add(gid)
            g = goods[gid]
            price = mk["goods"].get(str(gid), {}).get("price", g.get("value", 1)) if mk else g.get("value", 1)
            shop.append({"name": f"parcel of {g['name'].lower()}", "nouns": [g["name"].lower().split()[-1], "parcel"],
                         "weight": 5.0, "flags": ["takeable", "trade_good"], "good": gid,
                         "price": max(1, round(price * 3)), "description": f"Local {g['name'].lower()}, made in {burg['name']}."})
    bounties = "No bounties posted today."
    if campaign is not None:
        main = campaign.story.line("main")
        tok = campaign.tokens
        if j.type == "Monster hunt" and any(p.id.startswith("stop") and "bounty" in p.title.lower() for p in main.phases):
            bounties = (f"BOUNTY: the {tok.get('beast', 'beast')} of {tok.get('destination', 'the east')}. Writs registered "
                        f"here and in other bounty towns. Payable on proof before day {tok.get('deadline')}.")
    sail = []
    for st in j.stages:
        if not st.is_stay and j.clock and st.transport and "foot" not in st.transport.lower():
            alts = j.alternatives(st.index, cfg.get("transports_allowed") or [st.transport])
            sail.append(f"{st.name}: by {st.transport.lower()}, {(st.end_t - st.start_t) / 24:.0f} days"
                        + (" (faster: " + ", ".join(f"{a['transport'].lower()} {a['days']:.0f} days" for a in alts) + ")" if alts else ""))
    return {"shop": shop, "bounties": bounties, "sailings": "; ".join(sail[:3]) or "No sailings posted.",
            "notices": " ".join(topics.get("_rumours", [])[:3]) or "Lost: one goat. Answers to nothing."}


def place_story(w: World, story, scene: str) -> None:
    """Spawn story elements anchored here, hand over pending gifts, and add story topics."""
    for spec in story.pending_gifts:
        if spec["id"] not in w.things:
            w.spawn(spec, "player", spec["id"])
    story.pending_gifts.clear()
    a = w.flags.get("anchor", {})
    rooms = sorted((r for k, r in w.rooms.items() if k not in ("outside", "rear")),
                   key=lambda r: not r.id.startswith("house"))  # placed houses first: canon lives there
    for line, e in story.elements_for(a.get("burg"), a.get("marker"), scene):
        if e.anchor.get("heart"):
            room = max(rooms, key=lambda r: (r.depth, r.id))
        else:
            pref = e.anchor.get("prefer", [])
            room = next((r for p in pref for r in rooms if r.purpose == p), None) or \
                random.Random(f"{w.seed}:{line.id}:{e.role}").choice(rooms)
        w.spawn(dict(e.spec, provenance=e.spec.get("provenance", "new")), room.id, line.thing_id(e.role))
        e.placed = True
    for tid, extra in (story.flags.get("overlay_topics") or {}).items():
        if tid in w.things:
            w.things[tid].props["topics"] = {**(w.things[tid].props.get("topics") or {}), **extra}


def _people(w: World, files: Files, overlay: dict, topics: dict, base: int, kind: str) -> None:
    """A household for dwellings with no people in the overlay."""
    if kind != "dwelling" or any("person" in s.get("flags", []) for s in overlay.get("things", [])):
        return
    name = NameGenerator(files.map.namebase_overrides()).name(base, f"{w.seed}:householder")
    spot = next((k for k, r in w.rooms.items() if r.purpose in ("kitchen", "living room", "hall")),
                next(iter(k for k in w.rooms if k != "outside")))
    w.spawn({"name": name, "nouns": [name.lower(), "householder", "owner"], "flags": ["person", "proper"],
             "description": f"{name}, who lives here.", "here": f"{name} is here, busy with something.",
             "greet": f"{name} looks up. \"Can I help you?\"",
             "barge": f"{name} stares at you. \"Most people knock.\"", "provenance": "new"}, spot, "householder")


def _room_ref(w: World, ref: str) -> str | None:
    if ref in w.rooms:
        return ref
    if ref.startswith("note:"):
        n = ref.split(":", 1)[1]
        t = next((t for t in w.things.values() if t.props.get("note") == n), None)
        return t.location if t else None
    return next((k for k, r in w.rooms.items() if r.name.lower() == ref.lower()), None)


def apply_room_overlay(w: World, ov: dict) -> None:
    for ref, spec in ov.get("rooms", {}).items():
        rid = _room_ref(w, ref)
        if not rid:
            continue
        room = w.rooms[rid]
        if spec.get("rename"):
            old = room.name
            room.name = spec["rename"]
            room.description = room.description.replace(old.lower(), spec["rename"].lower())
        if spec.get("purpose"):
            room.purpose = spec["purpose"]
        if spec.get("add"):
            room.description += " " + spec["add"]


def apply_overlay(w: World, ov: dict) -> None:
    """Content-pack overlay: new things, and changes to generated things."""
    for spec in ov.get("things", []):
        where = spec.get("in")
        loc = "player" if where == "player" else where if where in w.things else _room_ref(w, where) if where else None
        w.spawn(spec, loc, spec.get("id"))
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
            t.props.update({k: v for k, v in change.items() if k in (
                "hazard", "hint", "talk", "here", "initial", "value", "actions", "topics", "accepts", "show",
                "invite", "barge", "greet", "tell", "ask_default")})
            t.provenance = change.get("provenance", t.provenance)
