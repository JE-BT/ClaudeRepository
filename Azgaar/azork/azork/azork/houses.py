"""Buildings the generator makes up when no Dwellings export is placed.

Each kind is a short list of (purpose, floor). The ground floor hangs off the entrance room in
seeded compass directions, the upper floor is up the stairs from the entrance, the cellar down
from the kitchen (or the entrance). Rooms take their names from their purpose and are furnished
from data/furnishings.json like any other room. Provenance: new.
"""
from __future__ import annotations

import random

from .engine.model import Exit, Room, World

KINDS = {
    "cottage": [("hall", 0), ("kitchen", 0), ("bedroom", 0)],
    "house": [("hall", 0), ("kitchen", 0), ("living room", 0), ("bedroom", 1), ("children's room", 1), ("cellar", -1)],
    "townhouse": [("hall", 0), ("parlour", 0), ("kitchen", 0), ("dining room", 0), ("study", 1), ("bedroom", 1),
                  ("guest room", 1), ("storage", -1)],
    "inn": [("taproom", 0), ("kitchen", 0), ("guest room", 1), ("bedroom", 1), ("cellar", -1)],
    "temple": [("sanctuary", 0), ("vestry", 0), ("chapel", 0)],
    "hall": [("guild hall", 0), ("clerk's office", 0), ("strongroom", -1)],
    "market": [("market hall", 0), ("storeroom", 0)],
}
GROUND_DIRS = ["north", "east", "west", "northeast", "northwest", "south"]


def add_building(w: World, prefix: str, label: str, kind: str, outside: str, seed: str,
                 door_dir: str = "in") -> str:
    """Add a made-up building to the world, joined to `outside`; returns the entrance room id."""
    rng = random.Random(f"{seed}:{prefix}:{kind}")
    plan = KINDS.get(kind, KINDS["house"])
    rooms = []
    names_used: dict[str, int] = {}
    for k, (purpose, floor) in enumerate(plan):
        n = names_used.get(purpose, 0) + 1
        names_used[purpose] = n
        name = purpose[0].upper() + purpose[1:] + (f" {n}" if n > 1 else "")
        level = "in the cellar" if floor < 0 else "upstairs" if floor > 0 else "on the ground floor"
        rid = f"{prefix}:{k}"
        w.add_room(Room(rid, name, f"The {name.lower()} {level} of {label}.",
                        dark="always" if floor < 0 else "night", area=label, purpose=purpose, provenance="new"))
        rooms.append((rid, purpose, floor))
    entrance = rooms[0][0]
    ground = [r for r in rooms[1:] if r[2] == 0]
    dirs = GROUND_DIRS[:]
    rng.shuffle(dirs)
    for (rid, _, _), d in zip(ground, dirs):
        _join(w, entrance, d, rid)
    upper = [r for r in rooms if r[2] > 0]
    if upper:
        _join(w, entrance, "up", upper[0][0], note="stairs")
        for (rid, _, _), d in zip(upper[1:], dirs):
            _join(w, upper[0][0], d, rid)
    cellar = [r for r in rooms if r[2] < 0]
    if cellar:
        kitchen = next((r[0] for r in rooms if r[1] == "kitchen"), entrance)
        _join(w, kitchen, "down", cellar[0][0], note="stairs")
    door = w.spawn({"name": "door", "nouns": ["door"], "adjectives": label.lower().split(),
                    "description": f"The door of {label}.", "flags": ["door", "openable", "household"],
                    "provenance": "new"}, None, f"{prefix}:door")
    door.props["rooms"] = [entrance, outside]
    w.rooms[outside].exits[door_dir if door_dir not in w.rooms[outside].exits else f"{door_dir}"] = Exit(entrance, door.id)
    w.rooms[entrance].exits["out"] = Exit(outside, door.id)
    return entrance


def _join(w: World, a: str, d: str, b: str, note: str = "") -> None:
    from .engine.model import OPPOSITE
    while d in w.rooms[a].exits:
        d = GROUND_DIRS[(GROUND_DIRS.index(d) + 1) % len(GROUND_DIRS)] if d in GROUND_DIRS else "north"
    w.rooms[a].exits[d] = Exit(b, None, False, note or "doorway")
    back = OPPOSITE[d]
    w.rooms[b].exits.setdefault(back, Exit(a, None, False, note or "doorway"))
