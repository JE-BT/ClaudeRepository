"""Town scenes, street by street (phase 4, second version).

With a Watabou plan, the town is its roads: each road is cut into stretches of about 40 m,
stretches that meet become junctions, and you walk from stretch to stretch. Every building in
the plan belongs to its nearest stretch and stays unknown until you SEARCH that stretch, someone
gives you directions, or a story tells you of it; then you can ENTER it. Key buildings (the
inn, the hall, the temple, the storehouse by the square, the harbour office, the citadel's keep,
the shanty town) are real buildings chosen by fit: the inn near where travellers arrive, the
hall the largest building on the square, the temple at the plan's temple, and so on. You come in
by the road on the side you arrived from. Interiors are built when first entered: from a placed
Dwellings export if there is one, otherwise made up to fit the building (or the game asks).
Without a plan the generator makes a simple town of crossing streets.
"""
from __future__ import annotations

import math
import random

from . import houses, interiors, watabou
from .engine.model import Exit, Room, World
from .geometry import ring_centroid
from .interiors import compass
from .names import NameGenerator
from .people import TEXT, looks

STEP_M = 40.0
STREET_WORDS = ["Eel", "Tanners'", "Bell", "Salt", "Mill", "Chapel", "Rope", "Smoke", "Fish", "Cooper", "Well", "Weavers'",
                "Lantern", "Ash", "Gull", "Cart", "Tallow", "Net", "Reed", "Copper", "Crow", "Bridge", "Ferry", "Hide"]
STREET_KINDS = ["Street", "Lane", "Row", "Way", "Walk", "Alley"]
HOUSE_ADJ = ["crooked", "narrow", "tall", "whitewashed", "tarred", "stone", "timbered", "green-shuttered", "sagging",
             "new", "old", "red-doored", "blue", "squat", "long", "corner", "gabled", "thatched"]
INN_ADJ = ["Golden", "Drowned", "Lucky", "Crooked", "Sleeping", "Red", "Patient", "Hungry", "Blind", "Laughing"]
INN_NOUN = ["Eel", "Heron", "Lantern", "Anchor", "Boar", "Kettle", "Wheel", "Crow", "Barrel", "Ferryman"]
KIND_OF_ROLE = {"inn": "inn", "hall": "hall", "temple": "temple", "storehouse": "market", "harbour office": "market",
                "keep": "hall"}


class NeedDwelling(Exception):
    def __init__(self, burg: dict, who: str, building: int | None = None):
        super().__init__(f"{burg['name']} needs a house for {who}")
        self.burg, self.who, self.building = burg, who, building


def _inside(p, ring) -> bool:
    x, y = p
    hit = False
    for k in range(len(ring)):
        (ax, ay), (bx, by) = ring[k][:2], ring[(k + 1) % len(ring)][:2]
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def inn_name(m, burg: dict, rng: random.Random) -> str:
    for mk in m.live("markers"):
        if mk["type"] == "inns" and math.dist((mk["x"], mk["y"]), (burg["x"], burg["y"])) * m.mi_per_px < 10:
            return mk["name"]
    return f"The {rng.choice(INN_ADJ)} {rng.choice(INN_NOUN)}"


def _dir(a, b) -> str:
    return compass(b[0] - a[0], -(b[1] - a[1]))  # Watabou y points up


def build_town(w: World, files, burg: dict, plan_path=None, seed: str = "", story_people=None,
               policy: str = "generate", arrive: str | None = None) -> str:
    m = files.map
    rng = random.Random(f"{seed}:town:{burg['i']}")
    town = watabou.load(plan_path) if plan_path else None
    pop = round(burg["population"] * m.settings["units"]["population"]["scale"])
    state = m.state(burg.get("state", 0))
    w.flags["town"] = tplan = {"burg": burg["i"], "buildings": {}, "places": {}}
    about = f"{burg['name']}, a {burg.get('group', 'town')} of about {pop:,} under {state.get('fullName') or state['name']}."
    step = STEP_M * max(1.0, (pop / 6000) ** 0.5)  # bigger towns, longer stretches
    nodes = _nodes_from_plan(town, rng, step) if town and town.roads else _nodes_made_up(rng)
    # rooms for stretches of street
    squares = [ring_centroid(sq) for sq in (town.squares if town else [])]
    for k, n in enumerate(nodes):
        district = next((d["name"] for d in (town.districts if town else []) if _inside(n["pt"], d["ring"])), None)
        on_square = any(math.dist(n["pt"], sq) < 25 for sq in squares) or n.get("square")
        name = "Market square" if on_square else n["street"]
        desc = (f"{'The market square' if on_square else n['street']}" + (f", in {district}" if district else "") + ". "
                + rng.choice(["Buildings crowd close on both sides.", "Doors and shutters line the way.",
                              "Washing hangs between the upper windows.", "The street narrows between leaning houses.",
                              "Gutters run down the middle of the way."]))
        rid = "outside" if k == n.get("entry_k", -1) else f"st{k}"
        w.add_room(Room(rid, name, desc, area=burg["name"], purpose="market square" if on_square else "street",
                        provenance="data" if town else "new"))
        n["rid"] = rid
    _pick_entry(nodes, arrive, w, burg, about)
    for n in nodes:
        for j in n["links"]:
            a, b = n["rid"], nodes[j]["rid"]
            d = _dir(n["pt"], nodes[j]["pt"])
            ex = w.rooms[a].exits
            while d in ex and ex[d].to != b:
                d = interiors.COMPASS8[(interiors.COMPASS8.index(d) + 1) % 8]
            ex[d] = Exit(b, note=nodes[j]["street"] if nodes[j]["street"] != n["street"] else "")
    # buildings
    blds = town.buildings if town else []
    by_node: dict[int, list] = {}
    for b in blds:
        k = min(range(len(nodes)), key=lambda i: math.dist(nodes[i]["pt"], b.centroid))
        by_node.setdefault(k, []).append(b)
        tplan["buildings"][str(b.index)] = {"node": nodes[k]["rid"], "area": b.area, "known": False, "role": None,
                                            "label": None}
    if not town:  # a made-up town: a handful of made-up buildings per stretch
        for k, n in enumerate(nodes):
            for q in range(3):
                idx = f"v{k}-{q}"
                tplan["buildings"][idx] = {"node": n["rid"], "area": rng.choice([60, 90, 140, 220]), "known": False,
                                           "role": None, "label": None}
    for k, n in enumerate(nodes):
        used = set()
        for idx, info in tplan["buildings"].items():
            if info["node"] == n["rid"]:
                adj = next(a for a in HOUSE_ADJ + [f"house {i}" for i in range(99)] if a not in used)
                used.add(adj)
                size = "cottage" if info["area"] < 80 else "house" if info["area"] < 200 else "large house"
                info["label"] = (f"the {adj} {size}" if size != "large house" else f"the {adj} house (large)") \
                    if not adj.startswith("house ") else f"{size} {adj[6:]}"
                info["key"] = adj.split()[0] if not adj.startswith("house ") else adj.replace(" ", "")
    for f in files.dwellings():  # placed houses keep their own names and are not key buildings
        if f.burg == burg["i"] and str(f.building) in tplan["buildings"]:
            info = tplan["buildings"][str(f.building)]
            info.update({"label": f.label or info["label"], "file": str(f.path), "placed": True,
                         "key": (f.label or "house").split()[0].lower()})
    _key_buildings(w, files, burg, town, nodes, tplan, rng)
    for f in files.dwellings():  # a house placed for a key role takes that role
        if f.burg == burg["i"] and f.role and str(f.building) in tplan["buildings"]:
            old = tplan["places"].get(f.role)
            if old and old != str(f.building):
                tplan["buildings"][old]["role"] = None
            tplan["buildings"][str(f.building)]["role"] = f.role
            tplan["places"][f.role] = str(f.building)
            if not tplan["buildings"][str(f.building)].get("exit"):
                _link_building(w, tplan["buildings"][str(f.building)]["node"], str(f.building), tplan["buildings"][str(f.building)])
    # people on the streets
    names = NameGenerator(m.namebase_overrides())
    base = m.culture(burg.get("culture", 0)).get("base", 0)
    from . import npc
    for k in range(0, len(nodes), 4):
        role = rng.choice(TEXT["professions"])
        nm = names.name(base, f"{seed}:folk:{burg['i']}:{k}")
        w.spawn({"name": nm, "nouns": [nm.lower(), role.split()[-1], "person", "local"], "flags": ["person", "proper", "local"],
                 "description": looks(m, burg.get("culture", 0), 20, f"{seed}:{nm}", role),
                 "here": f"{nm}, a {role}, is about {rng.choice(['their business', 'nothing in particular', 'the day'])} here.",
                 "greet": f"{nm} stops. \"Lost? Ask me the way, if you like.\"", "provenance": "new"},
                nodes[k]["rid"], f"folk:{k}")
    return "outside"


def _nodes_from_plan(town, rng, STEP_M=STEP_M) -> list[dict]:
    nodes: list[dict] = []
    words = rng.sample(STREET_WORDS, len(STREET_WORDS))
    main = town.roads[0]
    for r_i, road in enumerate(town.roads):
        street = "Main street" if road is main else f"{words[r_i % len(words)]} {rng.choice(STREET_KINDS)}"
        pts = [tuple(p[:2]) for p in road["points"]]
        samples = [pts[0]]
        acc = 0.0
        for a, b in zip(pts, pts[1:]):
            seg = math.dist(a, b)
            t = STEP_M - acc
            while t <= seg:
                samples.append((a[0] + (b[0] - a[0]) * t / seg, a[1] + (b[1] - a[1]) * t / seg))
                t += STEP_M
            acc = (acc + seg) % STEP_M
        if math.dist(samples[-1], pts[-1]) > STEP_M / 3:
            samples.append(pts[-1])
        prev = None
        for p in samples:
            k = next((i for i, n in enumerate(nodes) if math.dist(n["pt"], p) < 12), None)
            if k is None:
                nodes.append({"pt": p, "street": street, "links": set()})
                k = len(nodes) - 1
            if prev is not None and prev != k:
                nodes[prev]["links"].add(k)
                nodes[k]["links"].add(prev)
            prev = k
    return nodes


def _nodes_made_up(rng) -> list[dict]:
    nodes = []
    for k in range(6):  # main street, south to north
        nodes.append({"pt": (0.0, k * 40.0), "street": "Main street", "links": set(), "square": k == 3})
    for k in range(1, 3):
        nodes.append({"pt": (k * 40.0, 120.0), "street": f"{rng.choice(STREET_WORDS)} Lane", "links": set()})
        nodes.append({"pt": (-k * 40.0, 120.0), "street": f"{rng.choice(STREET_WORDS)} Row", "links": set()})
    for a, b in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (3, 6), (6, 8), (3, 7), (7, 9)]:
        nodes[a]["links"].add(b)
        nodes[b]["links"].add(a)
    return nodes


def _pick_entry(nodes, arrive, w, burg, about) -> None:
    """Enter by the road end on the side the party arrives from."""
    cx = sum(n["pt"][0] for n in nodes) / len(nodes)
    cy = sum(n["pt"][1] for n in nodes) / len(nodes)
    ends = [i for i, n in enumerate(nodes) if len(n["links"]) <= 1] or list(range(len(nodes)))
    want = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0), "northeast": (1, 1),
            "northwest": (-1, 1), "southeast": (1, -1), "southwest": (-1, -1)}.get(arrive or "south", (0, -1))
    k = max(ends, key=lambda i: (nodes[i]["pt"][0] - cx) * want[0] + (nodes[i]["pt"][1] - cy) * want[1])
    old = nodes[k]["rid"]
    room = w.rooms.pop(old)
    room.id = "outside"
    walls = bool(burg.get("walls"))
    room.name = f"{burg['name']} gate" if walls else f"{room.name}, edge of {burg['name']}"
    room.description = f"{about} {'You pass in under the gate. ' if walls else ''}{room.description}"
    w.rooms["outside"] = room
    nodes[k]["rid"] = "outside"
    room.exits["out"] = Exit("__exit__")


def _key_buildings(w, files, burg, town, nodes, tplan, rng) -> None:
    m = files.map
    B = tplan["buildings"]
    if not B:
        return
    entry = next(n for n in nodes if n["rid"] == "outside")["pt"]
    centre = (ring_centroid(town.squares[0]) if town and town.squares else
              (sum(n["pt"][0] for n in nodes) / len(nodes), sum(n["pt"][1] for n in nodes) / len(nodes)))
    pos = {idx: (town.buildings[int(idx)].centroid if town and idx.isdigit() else
                 next(n["pt"] for n in nodes if n["rid"] == info["node"])) for idx, info in B.items()}
    free = {i for i in B if not B[i].get("placed")}

    def take(role, idx, label):
        if idx is None:
            return
        B[idx].update({"role": role, "label": label, "known": role in ("inn", "hall", "temple"),
                       "key": role.split()[0]})
        free.discard(idx)
        tplan["places"][role] = idx

    near = lambda p, pool, r=80: sorted((i for i in pool if math.dist(pos[i], p) < r), key=lambda i: math.dist(pos[i], p))
    mid = [i for i in free if 120 <= B[i]["area"] <= 700]
    take("inn", (near(entry, mid, 400) or sorted(free, key=lambda i: math.dist(pos[i], entry)))[0],
         inn_name(m, burg, rng))
    if burg["population"] * 1000 > 800:
        big = sorted(near(centre, free, 120), key=lambda i: -B[i]["area"])
        take("hall", big[0] if big else None, f"the {burg['name']} hall")
    if burg.get("temple"):
        spot = ring_centroid(town.temples[0]) if town and town.temples else centre
        faith = m.religion(m.cell("religion")[burg["cell"]]).get("name", "")
        take("temple", (near(spot, free, 300) or [None])[0], f"the temple{' of the ' + faith if faith else ''}")
    take("storehouse", (near(centre, free, 200) or [None])[0], "the market storehouse")
    if town and town.piers:
        take("harbour office", (near(tuple(town.piers[0]["points"][0][:2]), free, 300) or [None])[0], "the harbour office")
    if burg.get("citadel") and town:
        castle = next((d for d in town.districts if any(x in d["name"].lower() for x in ("castle", "citadel", "keep"))), None)
        pool = [i for i in free if castle and _inside(pos[i], castle["ring"])]
        take("keep", max(pool, key=lambda i: B[i]["area"]) if pool else None, "the citadel keep")
    for role, idx in tplan["places"].items():
        node = B[idx]["node"]
        _link_building(w, node, idx, B[idx])


def _link_building(w: World, node: str, idx: str, info: dict) -> None:
    key = info["key"]
    while key in w.rooms[node].exits:
        key += "'"
    w.rooms[node].exits[key] = Exit(f"bldg:{idx}", note=info["label"])
    info["exit"] = key


def reveal(w: World, idx: str) -> str:
    info = w.flags["town"]["buildings"][idx]
    if not info.get("exit"):
        _link_building(w, info["node"], idx, info)
    info["known"] = True
    return info["label"]


def search_street(w: World, room_id: str) -> list[str]:
    found = []
    for idx, info in w.flags["town"]["buildings"].items():
        if info["node"] == room_id and not info.get("exit"):
            found.append(reveal(w, idx))
    return found


def open_building(game, idx: str, policy: str = "generate") -> str | None:
    """Build a building's interior on first entry. Returns None when built, or a reason to pause."""
    w = game.w
    t = w.flags["town"]
    info = t["buildings"][idx]
    node = info["node"]
    if info.get("file"):
        interiors.add_dwelling(w, watabou.load_dwelling(info["file"]), f"b{idx}", info["label"], node, w.seed,
                               f"b{idx}-door")
        entry = next(k for k, r in w.rooms.items() if k.startswith(f"b{idx}:") and "out" in r.exits)
    else:
        if policy == "ask":
            return "ask"
        kind = KIND_OF_ROLE.get(info.get("role"), "cottage" if info["area"] < 80 else "house" if info["area"] < 200 else "townhouse")
        entry = houses.add_building(w, f"b{idx}", info["label"], kind, node, w.seed, f"b{idx}-door")
    w.rooms[node].exits[info["exit"]] = Exit(entry, f"b{idx}:door" if f"b{idx}:door" in w.things else None,
                                              note=info["label"])
    w.rooms[node].exits.pop(f"b{idx}-door", None)
    info["entry"] = entry
    from .scenes import after_building
    after_building(game, idx, entry)
    return None
