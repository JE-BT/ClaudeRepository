"""Town scenes (phase 4).

With a Watabou plan: a gate (if walled) or the edge of town, the main street (the widest road),
one room per named district (City Generator), the market square, the waterfront (piers),
fields (Village Generator); directions follow the plan's geometry. Without a plan the
generator makes the same kinds of places up from the burg's flags (walls, plaza, port,
temple, citadel, shanty). Every town gets the buildings a journey needs: an inn, a hall
(bounty office and clerks) in towns, a market, a temple where the burg has one. A placed
Dwellings export becomes a house off its district; a story person who needs a home gets a
made-up house, or the scene builder asks for a dwelling first (policy "ask").
"""
from __future__ import annotations

import math
import random

from . import houses, interiors, watabou
from .engine.model import Exit, Room, World
from .geometry import ring_centroid
from .interiors import compass, link
from .names import NameGenerator

INN_ADJ = ["Golden", "Drowned", "Lucky", "Crooked", "Sleeping", "Red", "Patient", "Hungry", "Blind", "Laughing"]
INN_NOUN = ["Eel", "Heron", "Lantern", "Anchor", "Boar", "Kettle", "Wheel", "Crow", "Barrel", "Ferryman"]


class NeedDwelling(Exception):
    def __init__(self, burg: dict, who: str):
        super().__init__(f"{burg['name']} needs a house for {who}")
        self.burg, self.who = burg, who


def inn_name(m, burg: dict, rng: random.Random) -> tuple[str, str]:
    """An inn marker within 10 miles gives the name and dish; otherwise a made-up name."""
    for mk in m.live("markers"):
        if mk["type"] == "inns" and math.dist((mk["x"], mk["y"]), (burg["x"], burg["y"])) * m.mi_per_px < 10:
            return mk["name"], mk.get("note", "")
    return f"The {rng.choice(INN_ADJ)} {rng.choice(INN_NOUN)}", ""


def build_town(w: World, files, burg: dict, plan_path=None, seed: str = "", story_people: list | None = None,
               policy: str = "generate") -> str:
    """Add the town's rooms to w; returns the entry room id. story_people: [(name, prefers_home)]."""
    m = files.map
    rng = random.Random(f"{seed}:town:{burg['i']}")
    names = NameGenerator(m.namebase_overrides())
    base = m.culture(burg.get("culture", 0)).get("base", 0)
    town = watabou.load(plan_path) if plan_path else None
    pop = round(burg["population"] * m.settings["units"]["population"]["scale"])
    state = m.state(burg.get("state", 0))
    faith = m.religion(m.cell("religion")[burg["cell"]]).get("name", "")
    about = (f"{burg['name']}, a {burg.get('group', 'town')} of about {pop:,} people under "
             f"{state.get('fullName') or state['name']}.")
    walled = bool(burg.get("walls"))
    entry = w.add_room(Room("outside", f"{burg['name']} gate" if walled else f"Edge of {burg['name']}",
                            f"{about} {'The road passes under the gate.' if walled else 'The road runs on into town.'}",
                            area=burg["name"], purpose="street", provenance="mixed")).id
    w.rooms[entry].exits["out"] = Exit("__exit__")
    main = w.add_room(Room("main", "Main street", f"The main street of {burg['name']}.", area=burg["name"],
                           purpose="street", provenance="mixed")).id
    centre = (0.0, 0.0)
    if town and town.roads:
        pts = town.main_roads()[0]["points"]
        centre = tuple(pts[len(pts) // 2][:2])
    link(w, entry, main, "north")
    squares = []
    if town:
        dist_rooms = []
        placed = [(main, centre)]
        order = sorted(enumerate(town.districts), key=lambda kd: math.dist(ring_centroid(kd[1]["ring"]), centre))
        for k, d in order:
            c = ring_centroid(d["ring"])
            count = sum(1 for b in town.buildings if _inside(b.centroid, d["ring"]))
            rid = w.add_room(Room(f"district{k}", d["name"] or f"Quarter {k + 1}",
                                  f"{d['name']}, a quarter of about {count} buildings.", area=burg["name"],
                                  purpose="street", provenance="data")).id
            dist_rooms.append((rid, c, d["ring"]))
            for other, oc in sorted(placed, key=lambda p: math.dist(p[1], c)):  # join to the nearest with room
                if len([e for e in w.rooms[other].exits if e in interiors.COMPASS8]) < 7:
                    link(w, other, rid, compass(c[0] - oc[0], -(c[1] - oc[1])))
                    break
            placed.append((rid, c))
        for k, sq in enumerate(town.squares[:1]):
            c = ring_centroid(sq)
            squares.append(w.add_room(Room("square", "Market square", f"The market square of {burg['name']}.",
                                           area=burg["name"], purpose="market square", provenance="data")).id)
            link(w, main, squares[-1], compass(c[0] - centre[0], -(c[1] - centre[1])))
        if town.piers or burg.get("port"):
            w.add_room(Room("harbour", "Harbour", f"Quays and moored boats; the water smells of tar and salt.",
                            area=burg["name"], purpose="harbour", provenance="data" if town.piers else "new"))
            target = main
            if town.piers and dist_rooms:
                pc = tuple(town.piers[0]["points"][0][:2])
                target = min(dist_rooms, key=lambda r: math.dist(r[1], pc))[0]
            link(w, target, "harbour", "south" if not town.piers else
                 compass(town.piers[0]["points"][0][0] - centre[0], -(town.piers[0]["points"][0][1] - centre[1])))
        if town.kind == "village" and town.fields:
            w.add_room(Room("fields", "Fields", "Fields run out from the last houses.", area=burg["name"],
                            purpose="street", provenance="data"))
            link(w, main, "fields", "east")
    else:
        if burg.get("plaza"):
            squares.append(w.add_room(Room("square", "Market square", f"The market square of {burg['name']}.",
                                           area=burg["name"], purpose="market square", provenance="new")).id)
            link(w, main, "square", "north")
        if burg.get("port"):
            w.add_room(Room("harbour", "Harbour", "Quays and moored boats.", area=burg["name"], purpose="harbour",
                            provenance="new"))
            link(w, main, "harbour", "west")
        for k, label in enumerate(["Old town", "Craftsmen's quarter", "Riverside"][: 1 + (pop > 3000) + (pop > 10000)]):
            w.add_room(Room(f"district{k}", label, f"{label} of {burg['name']}.", area=burg["name"], purpose="street",
                            provenance="new"))
            link(w, main, f"district{k}", ["east", "northeast", "northwest"][k])
    if burg.get("citadel"):
        w.add_room(Room("citadel", "Citadel gate", "The citadel's gate is shut and guarded; it is not for travellers.",
                        area=burg["name"], purpose="street", provenance="data"))
        link(w, squares[0] if squares else main, "citadel", "northwest")
    if burg.get("shanty"):
        w.add_room(Room("shanty", "Shanty town", "Shacks lean against each other outside the walls.", area=burg["name"],
                        purpose="street", provenance="data"))
        link(w, entry, "shanty", "west")
    hub = squares[0] if squares else main
    iname, dish = inn_name(m, burg, rng)
    inn = houses.add_building(w, "inn", iname, "inn", hub, seed, "in" if "in" not in w.rooms[hub].exits else "inn")
    _sign(w, hub, inn, f"{iname} stands here, a painted sign over the door.")
    _person(w, names, base, seed, "innkeeper", inn, f"keeps {iname}",
            {"room|bed|stay": "A bed is four coins a night. The guest room's upstairs.",
             "food|meal|dish|eat": dish or "Stew, bread, whatever the market had."}, "innkeeper")
    if pop > 800:
        hall = houses.add_building(w, "hall", f"the {burg['name']} hall", "hall", hub, seed, "hall")
        clerk_room = next(k for k, r in w.rooms.items() if r.purpose == "clerk's office")
        _sign(w, hub, hall, f"The town hall stands here, its doors open to anyone with business.")
        _person(w, names, base, seed, "clerk", clerk_room, "a clerk of the hall",
                {"bounty|writ|bounties": "Writs are registered here. Show me yours and I'll stamp it.",
                 "road|travel|pass": "Papers in order, you may pass. Out of order, the posts will know."}, "clerk")
    if not squares:
        houses.add_building(w, "market", f"the {burg['name']} market", "market", main, seed, "market")
    if burg.get("temple"):
        tdist = next((k for k in w.rooms if k.startswith("district")), main)
        temple = houses.add_building(w, "temple", f"the temple of the {faith}" if faith else "the temple", "temple",
                                     tdist, seed, "temple")
        _sign(w, tdist, temple, f"A temple{' of the ' + faith if faith else ''} rises over the roofs here.")
        _person(w, names, base, seed, "priest", temple, f"a priest of the {faith}",
                {"faith|god|gods|" + "|".join(faith.lower().split()): f"The {faith} asks little and forgives less."},
                "priest")
    # placed dwellings, then homes for story people
    for f in files.dwellings():
        if f.burg == burg["i"]:
            district = _district_of(w, town, f.building)
            label = f.label or "a house"
            interiors.add_dwelling(w, watabou.load_dwelling(f.path), f"house{f.path.stem}", label,
                                   district or main, seed, label.lower().split()[0].strip("'s") or "house")
    for who, prefers_home in story_people or []:
        if not prefers_home or any(r.purpose in ("living room", "parlour") and r.area != iname for r in w.rooms.values()):
            continue
        if policy == "ask":
            raise NeedDwelling(burg, who)
        houses.add_building(w, f"home{len(w.rooms)}", f"{who}'s house", "townhouse",
                            next((k for k in w.rooms if k.startswith("district")), main), seed,
                            who.lower().split()[0])
    return entry


def _inside(p, ring) -> bool:
    x, y = p
    hit = False
    for k in range(len(ring)):
        (ax, ay), (bx, by) = ring[k][:2], ring[(k + 1) % len(ring)][:2]
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def _district_of(w: World, town, building: int | None) -> str | None:
    if not town or building is None or building >= len(town.buildings):
        return None
    c = town.buildings[building].centroid
    for k, d in enumerate(town.districts):
        if _inside(c, d["ring"]):
            return f"district{k}"
    return None


def _sign(w: World, room: str, building_room: str, text: str) -> None:
    w.spawn({"name": "sign", "nouns": ["sign", "building"], "flags": ["scenery"], "here": text,
             "description": text}, room, f"sign:{building_room}")


def _person(w: World, names, base: int, seed: str, role: str, room: str, what: str, topics: dict, tid: str) -> None:
    name = names.name(base, f"{seed}:{role}")
    w.spawn({"name": name, "nouns": [name.lower(), role], "flags": ["person", "proper"], "description": f"{name}, {what}.",
             "here": f"{name}, {what}, is here.", "greet": f"{name} nods. \"What can I do for you?\"",
             "topics": topics, "provenance": "new"}, room, tid)
