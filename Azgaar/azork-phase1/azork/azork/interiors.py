"""Turn Watabou interiors into engine rooms.

Dwellings: one room per Watabou room; doors from the door graph, stairs as up/down.
Cells are about 2.8 m; i is the row (south is +i), j the column (east is +j).

One Page Dungeons (door types from the generator, confirmed by the user):
  0 connection, 2 archway: open passages
  1 door: closed door;  9 steps: a door with a change of level
  3 stairs (entrance), 8 long stairs (exit): lead out of the dungeon
  4 portcullis: down until raised;  5 locked door: the key is somewhere in the dungeon
  6 secret door: hidden until searched for;  7 barred door: impassable
Directions use +x = east and +y = south, confirmed against the notes ("a gate with a keyhole to
the east", "a gate on the southern wall", "a double door to the north").
"""
from __future__ import annotations

import math
import random
import re

from .engine.model import OPPOSITE, Exit, Room, Thing, World
from .watabou import Dungeon, Dwelling

COMPASS8 = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
STEP_DIR = {"n": "north", "s": "south", "e": "east", "w": "west"}


def compass(dx: float, dy: float) -> str:
    """Direction of (dx, dy) with y pointing south."""
    return COMPASS8[int(((math.degrees(math.atan2(-dy, dx)) % 360) + 22.5) // 45) % 8]


def _free_direction(room: Room, preferred: str, fallbacks: list[str]) -> str:
    for d in [preferred] + fallbacks:
        if d not in room.exits:
            return d
    i = COMPASS8.index(preferred) if preferred in COMPASS8 else 0
    return next(COMPASS8[(i + k) % 8] for k in range(1, 8) if COMPASS8[(i + k) % 8] not in room.exits)


def _link(w: World, a: str, b: str, direction: str, door: str | None = None, note: str = "",
          hidden: bool = False, fallbacks: list[str] | None = None) -> None:
    d = _free_direction(w.rooms[a], direction, fallbacks or [])
    back = _free_direction(w.rooms[b], OPPOSITE[d], [])
    w.rooms[a].exits[d] = Exit(b, door, hidden, note)
    w.rooms[b].exits[back] = Exit(a, door, hidden, note)


def _number(n: int) -> str:
    return ["no", "a single", "two", "three", "four", "five", "six", "seven", "eight", "nine"][n] if n < 10 else str(n)


# ------------------------------------------------------------------ dwellings
def add_dwelling(w: World, dw: Dwelling, prefix: str, label: str, outside: str) -> str:
    cells = [(r.floor, i, j) for r in dw.rooms.values() for i, j in r.cells]
    ci = sum(c[1] for c in cells) / len(cells)
    cj = sum(c[2] for c in cells) / len(cells)
    centre = {}
    names: dict[str, str] = {}
    for key, r in dw.rooms.items():
        mi = sum(i for i, _ in r.cells) / len(r.cells)
        mj = sum(j for _, j in r.cells) / len(r.cells)
        centre[key] = (mj, mi)
        where = "central" if math.hypot(mj - cj, mi - ci) < 0.75 else compass(mj - cj, mi - ci)
        generic = r.name in (None, "Room")
        if r.floor < 0:
            name = "Cellar room" if generic else r.name
        elif generic and len(r.cells) <= 2:
            name = "Landing" if r.floor > 0 else "Passage"
        elif generic:
            name = f"{'Upper ' if r.floor > 0 else ''}{where} room".capitalize()
        else:
            name = (f"Upper {r.name.lower()}" if r.floor > 0 and r.name in names.values() else r.name)
        names[key] = name
    for key in names:  # make duplicates unique with their position
        if list(names.values()).count(names[key]) > 1:
            mj, mi = centre[key]
            names[key] = f"{names[key]} ({compass(mj - cj, mi - ci)})"
    for key, r in dw.rooms.items():
        windows = dw.windows.get(key, 0)
        level = "in the cellar" if r.floor < 0 else "upstairs" if r.floor > 0 else "on the ground floor"
        desc = (f"A room {level} of {label}, about {len(r.cells) * 7.84:.0f} square metres. "
                f"{_number(windows).capitalize()} window{'s' if windows != 1 else ''}"
                f"{' lets' if windows == 1 else ' let'} in the light." if windows else
                f"A room {level} of {label}, about {len(r.cells) * 7.84:.0f} square metres, with no windows.")
        w.add_room(Room(f"{prefix}:{key}", names[key], desc, dark="always" if r.floor < 0 else "night",
                        area=label))
    for n, (a, b, kind) in enumerate(dw.links):
        ra = f"{prefix}:{a}"
        if b == "outside":
            if kind != "front door":
                continue
            door = w.add_thing(Thing(f"{prefix}:frontdoor", "front door", ["door"], ["front", "main"],
                                     f"The front door of {label}.", None, 0,
                                     {"door", "openable"}, props={"rooms": [ra, outside]}, provenance="data"))
            d = STEP_DIR.get(dw.exit_dir or "s", "south")
            w.rooms[ra].exits[d] = Exit(outside, door.id)
            w.rooms[ra].exits["out"] = Exit(outside, door.id)
            w.rooms[outside].exits[OPPOSITE[d]] = Exit(ra, door.id)
            w.rooms[outside].exits["in"] = Exit(ra, door.id)
            continue
        rb = f"{prefix}:{b}"
        if kind == "stairs":
            up = dw.rooms[a].floor < dw.rooms[b].floor
            w.rooms[ra].exits["up" if up else "down"] = Exit(rb, None, False, "stairs")
            w.rooms[rb].exits["down" if up else "up"] = Exit(ra, None, False, "stairs")
            continue
        (xa, ya), (xb, yb) = centre[a], centre[b]
        d = compass(xb - xa, yb - ya)
        door_id = None
        if kind == "door":
            words = set(names[a].lower().split()) | set(names[b].lower().split())
            door_id = w.add_thing(Thing(f"{prefix}:door{n}", "door", ["door"], sorted(words), "A plain wooden door.",
                                        None, 0, {"door", "openable"}, props={"rooms": [ra, rb]},
                                        provenance="data")).id
        _link(w, ra, rb, d, door_id, "" if door_id else "doorway")
    return f"{prefix}:{dw.entrance}"


# ------------------------------------------------------------------- dungeons
STOP = {"a", "an", "the", "some", "of", "and"}
CUT = re.compile(r"\s(?:depicting|containing|on|in|into|at|with|among|hides|holds|to the|nearby|turns|resting|"
                 r"hovering|totally|close)\b.*$")


def note_things(text: str) -> list[tuple[str, list[str], list[str]]]:
    """(name, nouns, adjectives) for each noun phrase that opens a clause of a note."""
    out = []
    for clause in re.split(r"[.,]\s*", text):
        clause = clause.strip()
        m = re.match(r"(?:an?|the|some)\s+(.*)", clause, re.I)
        if not m:
            continue
        phrase = CUT.sub("", m.group(1)).strip()
        words = [x for x in re.findall(r"[a-z'-]+", phrase.lower()) if x not in STOP]
        if not words:
            continue
        if " of " in phrase:
            head = phrase.lower().split(" of ")[0].split()[-1]
            nouns, adjs = [head, words[-1]], [x for x in words if x not in (head, words[-1])]
        else:
            nouns, adjs = [words[-1]], words[:-1]
        out.append((phrase.lower(), nouns, adjs))
    return out


def _chamber_name(c, water: int) -> str:
    if c.rotunda:
        return "Rotunda"
    if c.corridor:
        return "Long passage" if max(c.w, c.h) >= 4 else "Short passage"
    area = c.w * c.h
    base = "Great hall" if area >= 36 else "Hall" if area >= 20 else "Chamber" if area >= 9 else "Small chamber"
    if water and water >= area / 3:
        return "Flooded " + base.lower()
    if c.columns:
        return "Pillared " + base.lower()
    return base


def add_dungeon(w: World, d: Dungeon, prefix: str, outside: str, rear_outside: str | None, seed: str) -> list[str]:
    cx = sum(c.x + c.w / 2 for c in d.chambers) / len(d.chambers)
    cy = sum(c.y + c.h / 2 for c in d.chambers) / len(d.chambers)
    names = {c.index: _chamber_name(c, c.water) for c in d.chambers}
    for c in d.chambers:
        if any("entrance" in n.lower() for n in c.notes):
            names[c.index] = "Rear entrance" if any("rear" in n.lower() for n in c.notes) else "Entrance hall"
    for k in names:
        if list(names.values()).count(names[k]) > 1:
            c = d.chambers[k]
            names[k] = f"{names[k]} ({compass(c.x + c.w / 2 - cx, c.y + c.h / 2 - cy)})"
    seen: dict[str, int] = {}
    counts = {v: list(names.values()).count(v) for v in names.values()}
    for k, v in sorted(names.items()):
        if counts[v] > 1:
            seen[v] = seen.get(v, 0) + 1
            names[k] = f"{v} {seen[v]}"
    for c in d.chambers:
        shape = ("a narrow passage" if c.corridor else "a round chamber" if c.rotunda else
                 "a large hall" if c.w * c.h >= 36 else "a chamber" if c.w * c.h >= 9 else "a cramped chamber")
        extra = []
        if c.columns:
            extra.append("Columns stand in two rows." if c.columns > 2 else "A column stands here.")
        if c.water:
            extra.append("Water covers much of the floor." if c.water >= c.w * c.h / 3 else "A small pool lies here.")
        for n in c.notes:
            first = re.split(r"[.,]", n.split(". ", 1)[-1])[0].strip()
            extra.append(f"You notice {first[0].lower() + first[1:]}." if first else "")
        desc = f"This is {shape} in {d.title}. " + " ".join(x for x in extra if x)
        w.add_room(Room(f"{prefix}:{c.index}", names[c.index], desc.strip(), dark="always", area=d.title))
    # note features and keys
    key_rooms = []
    for c in d.chambers:
        for n in c.notes:
            ref = n.split(". ", 1)[0]
            body = n.split(". ", 1)[-1]
            for k, (name, nouns, adjs) in enumerate(note_things(body)):
                if {"gate", "door"} & set(nouns) and _has_locked(d, c.index):
                    continue  # this note describes the locked door; it becomes the door's name below
                tid = f"{prefix}:note{ref}" + (f"-{k}" if k else "")
                is_key = "key" in nouns
                w.add_thing(Thing(tid, name, nouns, adjs, body + ".", f"{prefix}:{c.index}", 0.1 if is_key else 0,
                                  {"takeable"} if is_key else {"scenery"},
                                  props={"note": ref, "here": f"There is {('an ' if name[0] in 'aeiou' else 'a ')}{name} here."}
                                  if is_key else {"note": ref}, provenance="data"))
                if is_key:
                    key_rooms.append(tid)
    # doors and exits
    entrance_dirs: list[tuple[int, str]] = []
    locked = []
    for n, (a, b, t) in enumerate(d.links):
        ra = f"{prefix}:{a}"
        if b == "outside":
            entrance_dirs.append((a, ra))
            continue
        rb = f"{prefix}:{b}"
        dx, dy = d.link_dirs[n]
        direction = compass(dx, dy)
        fallback = compass(*_door_vector(d, a, b))
        door_id, note, hidden = None, "", False
        if t in (0, 2):
            note = "archway" if t == 2 else ""
        else:
            gate, gate_note = None, ""
            if t == 5:
                for c in (d.chambers[a], d.chambers[b]):
                    for nt in c.notes:
                        for name_, nouns_, _ in note_things(nt.split(". ", 1)[-1]):
                            if {"gate", "door"} & set(nouns_):
                                gate, gate_note = name_, nt.split(". ", 1)[-1] + "."
            name = {1: "door", 4: "portcullis", 5: gate or "locked door", 6: "secret door", 7: "barred door",
                    9: "door"}.get(t, "door")
            flags = {"door"} | ({"openable"} if t in (1, 5, 6, 9) else set())
            flags |= {"lockable", "locked"} if t == 5 else set()
            flags |= {"portcullis"} if t == 4 else {"barred"} if t == 7 else set()
            flags |= {"hidden"} if t == 6 else set()
            nouns = [name.split()[-1]] + (["door"] if name.split()[-1] != "door" else [])
            door = w.add_thing(Thing(f"{prefix}:door{n}", name, nouns, [x for x in name.split()[:-1]],
                                     gate_note or {4: "A heavy iron grille.", 5: "A stout door with a keyhole.",
                                      7: "A door barred fast; it will not move.", 9: "A door with a step down beyond it."
                                      }.get(t, "A heavy wooden door."),
                                     None, 0, flags, props={"rooms": [ra, rb], "type": t}, provenance="data"))
            door_id, hidden = door.id, t == 6
            if t == 5:
                locked.append(door)
        _link(w, ra, rb, direction, door_id, note, hidden, [fallback])
    # keys: one per dungeon opens every locked door; place one if the notes name none
    if locked and not key_rooms:
        rng = random.Random(f"{seed}:{prefix}:key")
        deg = {c.index: 0 for c in d.chambers}
        for a, b, _ in d.links:
            if b != "outside":
                deg[a] += 1
                deg[b] += 1
        ends = [k for k, v in sorted(deg.items()) if v == 1 and k not in [e for e, _ in entrance_dirs]]
        spot = rng.choice(ends or sorted(deg))
        w.add_thing(Thing(f"{prefix}:key", "small iron key", ["key"], ["small", "iron"], "A small iron key.",
                          f"{prefix}:{spot}", 0.1, {"takeable"}, provenance="new"))
        key_rooms.append(f"{prefix}:key")
    for k in key_rooms:
        w.things[k].unlocks = [door.id for door in locked]
    # entrances: first to the outside room, second (if any) to the rear outside room
    entry = []
    for k, (a, ra) in enumerate(entrance_dirs):
        out = outside if k == 0 or not rear_outside else rear_outside
        w.rooms[ra].exits["up"] = Exit(out, None, False, "stairs")
        w.rooms[ra].exits.setdefault("out", Exit(out, None, False, "stairs"))
        w.rooms[out].exits["down"] = Exit(ra, None, False, "stairs")
        w.rooms[out].exits.setdefault("in", Exit(ra, None, False, "stairs"))
        entry.append(ra)
    return entry


def _has_locked(d: Dungeon, chamber: int) -> bool:
    return any(t == 5 and chamber in (a, b) for a, b, t in d.links)


def _door_vector(d: Dungeon, a: int, b: int) -> tuple[float, float]:
    ca, cb = d.chambers[a], d.chambers[b]
    return (cb.x + cb.w / 2) - (ca.x + ca.w / 2), (cb.y + cb.h / 2) - (ca.y + ca.h / 2)
