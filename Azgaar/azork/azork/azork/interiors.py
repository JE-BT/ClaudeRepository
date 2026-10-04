"""Turn Watabou interiors into engine rooms with purposes.

Dwellings: one room per Watabou room; doors from the door graph; stairs and the spiral stair
as up/down. A named Watabou room keeps its name as its purpose; a generic room gets a purpose
for its floor (seeded), which content packs can override. Cells are about 2.8 m; i is the row
(south is +i), j the column (east is +j).

One Page Dungeons (door types confirmed by the user):
  0 connection, 2 archway: open;  9 steps: open, with a change of level
  1 door: closed door;  3 stairs (entrance), 8 long stairs (exit): lead out of the dungeon
  4 portcullis: down until raised;  5 locked door: the key is somewhere in the dungeon
  6 secret door: hidden until searched for;  7 barred door: impassable
Directions: +x east, +y south (checked against the notes of three dungeons).
Chambers get purposes from the dungeon's theme (title and story), size and features. The
deepest chamber (locked and secret doors count extra) is the heart: it holds what the story
names (a lair's creature, a hidden treasure).
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import deque
from pathlib import Path

from .engine.model import OPPOSITE, Exit, Room, World
from .watabou import Dungeon, Dwelling

COMPASS8 = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]
STEP_DIR = {"n": "north", "s": "south", "e": "east", "w": "west"}
TABLES = json.loads((Path(__file__).with_name("data") / "furnishings.json").read_text(encoding="utf-8"))


def compass(dx: float, dy: float) -> str:
    """Direction of (dx, dy) with y pointing south."""
    return COMPASS8[int(((math.degrees(math.atan2(-dy, dx)) % 360) + 22.5) // 45) % 8]


def _free(room: Room, preferred: str, fallbacks: list[str]) -> str:
    for d in [preferred] + fallbacks:
        if d not in room.exits:
            return d
    i = COMPASS8.index(preferred) if preferred in COMPASS8 else 0
    return next(COMPASS8[(i + k) % 8] for k in range(1, 8) if COMPASS8[(i + k) % 8] not in room.exits)


def link(w: World, a: str, b: str, direction: str, door: str | None = None, note: str = "",
         hidden: bool = False, fallbacks: list[str] | None = None) -> None:
    d = _free(w.rooms[a], direction, fallbacks or [])
    back = _free(w.rooms[b], OPPOSITE[d], [])
    w.rooms[a].exits[d] = Exit(b, door, hidden, note)
    w.rooms[b].exits[back] = Exit(a, door, hidden, note)


def _number(n: int) -> str:
    return ["no", "a single", "two", "three", "four", "five", "six", "seven", "eight", "nine"][n] if n < 10 else str(n)


def _unique(names: dict, where: dict) -> dict:
    for key in names:
        if list(names.values()).count(names[key]) > 1:
            names[key] = f"{names[key]} ({where[key]})"
    seen, counts = {}, {v: list(names.values()).count(v) for v in names.values()}
    for key in sorted(names):
        if counts[names[key]] > 1:
            seen[names[key]] = seen.get(names[key], 0) + 1
            names[key] = f"{names[key]} {seen[names[key]]}"
    return names


# ------------------------------------------------------------------ dwellings
def add_dwelling(w: World, dw: Dwelling, prefix: str, label: str, outside: str, seed: str,
                 door_name: str | None = None) -> str:
    rng = random.Random(f"{seed}:{prefix}:{label}")
    cells = [(r.floor, i, j) for r in dw.rooms.values() for i, j in r.cells]
    ci, cj = sum(c[1] for c in cells) / len(cells), sum(c[2] for c in cells) / len(cells)
    centre, names, where, purposes = {}, {}, {}, {}
    generic_pool = {k: list(v) for k, v in TABLES["dwelling_generic"].items()}
    for key, r in sorted(dw.rooms.items()):
        mi, mj = sum(i for i, _ in r.cells) / len(r.cells), sum(j for _, j in r.cells) / len(r.cells)
        centre[key] = (mj, mi)
        where[key] = "middle" if math.hypot(mj - cj, mi - ci) < 0.75 else compass(mj - cj, mi - ci)
        if r.name not in (None, "Room"):
            purpose = r.name.lower()
        elif len(r.cells) <= 2:
            purpose = "landing" if r.floor != 0 else "passage"
        else:
            pool = generic_pool["cellar" if r.floor < 0 else "upper" if r.floor > 0 else "ground"]
            purpose = pool.pop(rng.randrange(len(pool))) if pool else "store room"
        purposes[key] = purpose
        names[key] = purpose[0].upper() + purpose[1:]
    names = _unique(names, where)
    for key, r in dw.rooms.items():
        windows = dw.windows.get(key, 0)
        level = "in the cellar" if r.floor < 0 else "upstairs" if r.floor > 0 else "on the ground floor"
        light = (f"{_number(windows).capitalize()} window{'s' if windows != 1 else ''} "
                 f"{'lets' if windows == 1 else 'let'} in the light." if windows else "There are no windows.")
        desc = f"The {names[key].lower()} {level} of {label}, about {len(r.cells) * 7.84:.0f} square metres. {light}"
        w.add_room(Room(f"{prefix}:{key}", names[key], desc, dark="always" if r.floor < 0 else "night",
                        area=label, purpose=purposes[key]))
    for n, (a, b, kind) in enumerate(dw.links):
        ra = f"{prefix}:{a}"
        if b == "outside":
            if kind != "front door":
                continue
            door = w.spawn({"name": "front door", "nouns": ["door"], "adjectives": ["front", "main"],
                            "description": f"The front door of {label}.", "flags": ["door", "openable", "household"],
                            "provenance": "data"}, None, f"{prefix}:frontdoor")
            door.props["rooms"] = [ra, outside]
            d = STEP_DIR.get(dw.exit_dir or "s", "south")
            w.rooms[ra].exits[d] = Exit(outside, door.id)
            w.rooms[ra].exits["out"] = Exit(outside, door.id)
            out_exits = w.rooms[outside].exits
            if OPPOSITE[d] not in out_exits:
                out_exits[OPPOSITE[d]] = Exit(ra, door.id)
            key = "in" if "in" not in out_exits else (door_name or re.sub(r"[^a-z]", "", label.lower().split()[0]) or "house")
            out_exits[key] = Exit(ra, door.id)
            continue
        rb = f"{prefix}:{b}"
        if kind in ("stairs", "spiral"):
            up = dw.rooms[a].floor < dw.rooms[b].floor
            note = "spiral stair" if kind == "spiral" else "stairs"
            w.rooms[ra].exits["up" if up else "down"] = Exit(rb, None, False, note)
            w.rooms[rb].exits["down" if up else "up"] = Exit(ra, None, False, note)
            continue
        (xa, ya), (xb, yb) = centre[a], centre[b]
        door_id = None
        if kind == "door":
            words = set(re.findall(r"[a-z']+", names[a].lower())) | set(re.findall(r"[a-z']+", names[b].lower()))
            door = w.spawn({"name": "door", "nouns": ["door"], "adjectives": sorted(words),
                            "description": "A plain wooden door.", "flags": ["door", "openable"], "provenance": "data"},
                           None, f"{prefix}:door{n}")
            door.props["rooms"] = [ra, rb]
            door_id = door.id
        link(w, ra, rb, compass(xb - xa, yb - ya), door_id, "" if door_id else "doorway")
    return f"{prefix}:{dw.entrance}"


# ---------------------------------------------------------------- note things
PEOPLE = {"druid", "halfling", "dwarf", "elf", "man", "woman", "priest", "hermit", "monk", "witch", "wizard",
          "child", "girl", "boy", "beggar", "pilgrim", "merchant", "soldier", "guard", "prisoner", "orc", "goblin"}
PORTABLE = {"key", "piece", "relic", "staff", "lantern", "torch", "gold", "coins", "arrows", "crown", "ring", "amulet",
            "book", "scroll", "dagger", "sword", "gem", "cube", "orb", "idol", "chalice", "skull", "map", "bow", "wand",
            "mirror"}
CLOSED = {"trunk", "chest", "sarcophagus", "coffin", "box", "casket"}
CONTAIN = re.compile(r"^(?P<a>.+?)\s+(?P<rel>containing|holds|hides|full of)\s+(?P<b>.+)$")
PLACE = re.compile(r"^(?P<a>.+?)\s+(?P<rel>at the bottom of|in the middle of|on top of|among|inside|under|on|in)\s+(?P<b>.+)$")
TAIL = re.compile(r"\s(?:depicting|turns|resting|hovering|totally|close|nearby|into|to the|with a|of an eye)\b.*$")
STOP = {"a", "an", "the", "some", "of", "and", "his", "her", "its", "their"}
SPARE = ["storeroom", "cell", "guard room", "collapsed chamber", "kitchen ruin", "well room"]
PASSAGES = ["narrow", "dusty", "damp", "crumbling", "low", "winding", "echoing", "cold"]


def _np(phrase: str) -> tuple[str, list[str], list[str]]:
    phrase = re.sub(r"^(?:an?|the|some|his|her|its|their)\s+", "", phrase.strip(), flags=re.I)
    core = TAIL.sub("", phrase).strip().rstrip(",")
    words = [x for x in re.findall(r"[a-z'-]+", core.lower()) if x not in STOP]
    if not words:
        return core.lower(), [], []
    if " of " in core:
        head = core.lower().split(" of ")[0].split()[-1]
        return core.lower(), [head, words[-1]], [x for x in words if x not in (head, words[-1])]
    return core.lower(), [words[-1]], words[:-1]


def _kind(nouns: list[str], adjs: list[str]) -> set[str]:
    flags = set()
    if set(nouns) & PEOPLE and not {"corpse", "body", "statue"} & set(nouns):
        flags.add("person")
    elif set(nouns) & PORTABLE and "wall" not in adjs:
        flags.add("takeable")
        if set(nouns) & {"lantern", "torch"}:
            flags.add("light")
        if set(adjs) & {"silver", "gold", "golden", "magic", "legendary", "jewelled"} or \
                set(nouns) & {"gold", "gem", "relic", "crown", "cube"}:
            flags.add("treasure")
    else:
        flags.add("scenery")
    if set(nouns) & CLOSED:
        flags |= {"container", "openable"}
    return flags


def _article(name: str) -> str:
    return ("an " if name[:1] in "aeiou" else "a ") + name


def note_specs(text: str) -> list[dict]:
    """Things named by a One Page Dungeon note, with initial descriptions and relations."""
    out: list[dict] = []
    text = re.sub(r"\s+and\s+(?=(?:an?|some|the)\s)", ", ", text)
    for clause in [c.strip() for c in re.split(r"[.,]\s+|[.]$", text) if c.strip()]:
        if not re.match(r"(?:an?|the|some)\s", clause, re.I):
            continue
        sentence = clause[0].upper() + clause[1:]
        if set(_np(clause)[1]) & {"entrance", "exit"}:
            continue  # the room itself (its purpose says so), not a thing in it
        cm, pm = CONTAIN.match(clause), PLACE.match(clause)
        if cm:
            name, nouns, adjs = _np(cm["a"])
            holder = {"name": name, "nouns": nouns, "adjectives": adjs,
                      "flags": sorted(_kind(nouns, adjs) | {"container"}), "here": f"There is {_article(name)} here."}
            iname, inouns, iadjs = _np(cm["b"])
            inner = {"name": iname, "nouns": inouns, "adjectives": iadjs, "flags": sorted(_kind(inouns, iadjs)),
                     "_in": len(out)}
            if cm["rel"] == "hides":
                inner["flags"] = sorted(set(inner["flags"]) | {"hidden"})
                inner["search"] = True
            out += [holder, inner]
        elif pm and not set(_np(pm["a"])[1]) & {"gate", "door"}:
            name, nouns, adjs = _np(pm["a"])
            sname, snouns, sadjs = _np(pm["b"])
            verb = "rests" if pm["rel"] in ("on", "on top of") else "lies"
            sflags = (_kind(snouns, sadjs) - {"takeable", "treasure", "light", "person"}) | {"scenery"}
            if pm["rel"] in ("in", "inside", "at the bottom of"):
                sflags.add("container")
            if set(snouns) & {"pool", "well", "fountain", "spring", "basin", "stream"}:
                sflags.add("water_source")
            support = {"name": sname, "nouns": snouns, "adjectives": sadjs, "flags": sorted(sflags),
                       "here": f"There is {_article(sname)} here."}
            main = {"name": name, "nouns": nouns, "adjectives": adjs, "flags": sorted(_kind(nouns, adjs)),
                    "initial": f"{sentence.split(' ' + pm['rel'])[0]} {verb} {pm['rel']} {pm['b']}."}
            out += [support, main]
        else:
            name, nouns, adjs = _np(clause)
            flags = _kind(nouns, adjs)
            near = " nearby" in clause or "close to" in clause
            spec = {"name": name, "nouns": nouns, "adjectives": adjs, "flags": sorted(flags)}
            if "takeable" in flags:
                spec["initial"] = f"{sentence.replace(' nearby', '').split(' close to')[0]} lies {'nearby' if near else 'here'}."
            elif "person" in flags:
                spec["here"] = sentence + "."
            else:
                spec["here"] = f"There is {clause[0].lower() + clause[1:]} here."
            out.append(spec)
    for spec in out:
        if "light" in spec["flags"]:
            spec["fuel"] = 240 if "lantern" in spec["nouns"] else 60
    return out


# ------------------------------------------------------------------- dungeons
def theme_of(title: str, story: str) -> dict:
    text = f"{title} {story}".lower()
    for name, th in TABLES["dungeon_themes"].items():
        if name != "default" and any(re.search(rf"\b{k}\b", text) for k in th["keywords"]):
            return {"name": name, **th}
    return {"name": "default", **TABLES["dungeon_themes"]["default"]}


def story_subjects(story: str) -> dict:
    """What a One Page Dungeon story says lives or lies here."""
    out = {}
    if m := re.search(r"(?:an?|the)\s+([^.]+?)\s+(?:has|have)\s+made\s+(?:its|their)\s+lair here", story, re.I):
        out["creature"] = m.group(1)
    if m := re.search(r"(?:an?|the)\s+(?:legendary\s+)?([^.]+?)\s+(?:is|was|are)\s+hidden here", story, re.I):
        out["treasure"] = m.group(1)
    if m := re.search(r"(?:an?|the)\s+((?:gang|pack|band|tribe|swarm|flock|clan) of \w+)", story, re.I):
        out.setdefault("creature", m.group(1))
    return out


def add_dungeon(w: World, d: Dungeon, prefix: str, outside: str, rear_outside: str | None, seed: str) -> dict:
    rng = random.Random(f"{seed}:{prefix}:{d.title}")
    theme = theme_of(d.title, d.story)
    cx = sum(c.x + c.w / 2 for c in d.chambers) / len(d.chambers)
    cy = sum(c.y + c.h / 2 for c in d.chambers) / len(d.chambers)
    where = {c.index: compass(c.x + c.w / 2 - cx, c.y + c.h / 2 - cy) for c in d.chambers}
    cost = {0: 1, 1: 1, 2: 1, 9: 1, 4: 2, 6: 2, 5: 3}  # depth: locked doors cost 3 steps, secret doors 2
    adj: dict[int, list[tuple[int, int]]] = {c.index: [] for c in d.chambers}
    for a, b, t in d.links:
        if b != "outside" and t in cost:
            adj[a].append((b, cost[t]))
            adj[b].append((a, cost[t]))
    depth = {e: 0 for e in d.entrances}
    todo = deque(d.entrances)
    while todo:
        a = todo.popleft()
        for b, c in adj[a]:
            if depth.get(b, 1e9) > depth[a] + c:
                depth[b] = depth[a] + c
                todo.append(b)
    rooms_only = [c for c in d.chambers if not c.corridor and c.index not in d.entrances and c.index in depth]
    heart = max(rooms_only or d.chambers, key=lambda c: (depth.get(c.index, 0), c.w * c.h)).index
    subjects = story_subjects(d.story)
    heart_purpose = ("vault" if "treasure" in subjects else "lair" if "creature" in subjects else theme["heart"])
    pools = {k: list(theme[k]) for k in ("big", "medium", "small")}
    spare = [p for k in ("big", "medium", "small") for p in theme[k]] + list(SPARE)
    rng.shuffle(spare)
    used: dict[str, int] = {}
    purposes: dict[int, str] = {}
    labels: dict[int, str] = {}

    def pick(size: str) -> str:
        pool = pools[size]
        if pool:
            return pool.pop(rng.randrange(len(pool)))
        choice = min(spare, key=lambda p: (used.get(p, 0), spare.index(p)))
        return choice

    for c in sorted(d.chambers, key=lambda c: (-c.w * c.h, c.index)):
        flooded = bool(c.water and c.water >= c.w * c.h / 3)
        if c.index == heart:
            p = heart_purpose
        elif any("entrance" in n.lower() for n in c.notes) or c.index in d.entrances:
            p = "rear entrance" if any("rear" in n.lower() for n in c.notes) else "entrance hall"
        elif c.corridor:
            p = "passage"
            labels[c.index] = f"{rng.choice(PASSAGES)} passage"
        elif c.rotunda and theme["rotunda"] not in used:
            p = theme["rotunda"]
        elif flooded and theme["water"] not in used:
            p = theme["water"]
        else:
            p = pick("big" if c.w * c.h >= 30 else "medium" if c.w * c.h >= 9 else "small")
            if flooded:
                labels[c.index] = f"flooded {p}"
        used[p] = used.get(p, 0) + 1
        purposes[c.index] = p
    names = _unique({k: (labels.get(k) or v)[0].upper() + (labels.get(k) or v)[1:] for k, v in purposes.items()}, where)
    for c in d.chambers:
        shape = ("a narrow passage" if c.corridor else "a round chamber" if c.rotunda else
                 "a large hall" if c.w * c.h >= 36 else "a chamber" if c.w * c.h >= 9 else "a cramped chamber")
        extra = []
        if c.columns:
            extra.append("Columns stand in two rows." if c.columns > 2 else "A column stands here.")
        if c.water:
            extra.append("Water covers much of the floor." if c.water >= c.w * c.h / 3 else "Water has pooled on the floor.")
        once = purposes[c.index] not in ("passage", "entrance hall", "rear entrance", "lair", "vault")
        desc = f"This is {shape} in {d.title}" + (f", once {_article(purposes[c.index])}." if once else ".")
        w.add_room(Room(f"{prefix}:{c.index}", names[c.index], " ".join([desc] + extra), dark="always", area=d.title,
                        purpose=purposes[c.index], depth=depth.get(c.index, 0)))
    # things named in the notes
    key_ids, locked = [], []
    for c in d.chambers:
        for n in c.notes:
            ref, body = n.split(". ", 1) if ". " in n else ("", n)
            made = []
            for k, spec in enumerate(note_specs(body)):
                if {"gate", "door"} & set(spec["nouns"]) and _has_locked(d, c.index):
                    made.append(None)
                    continue
                spec = dict(spec, description=body + ".", provenance="data")
                inside = spec.pop("_in", None)
                loc = made[inside].id if inside is not None and made[inside] else f"{prefix}:{c.index}"
                if "key" in spec["nouns"]:
                    spec["flags"] = sorted((set(spec["flags"]) | {"takeable"}) - {"scenery"})
                    spec["weight"] = 0.1
                t = w.spawn(spec, loc, f"{prefix}:note{ref}" + (f"-{k}" if k else ""))
                t.props["note"] = ref
                made.append(t)
                if "key" in t.nouns:
                    key_ids.append(t.id)
    # doors and exits
    entrance_dirs = []
    for n, (a, b, t) in enumerate(d.links):
        ra = f"{prefix}:{a}"
        if b == "outside":
            entrance_dirs.append((a, ra))
            continue
        rb = f"{prefix}:{b}"
        dx, dy = d.link_dirs[n]
        door_id, note, hidden = None, "", False
        if t in (0, 2, 9):
            note = {2: "archway", 9: "steps"}.get(t, "")
        else:
            gate, gate_note = None, ""
            if t == 5:
                for c in (d.chambers[a], d.chambers[b]):
                    for nt in c.notes:
                        body = nt.split(". ", 1)[-1]
                        for spec in note_specs(body):
                            if {"gate", "door"} & set(spec["nouns"]):
                                gate, gate_note = spec["name"], body + "."
            name = {1: "door", 4: "portcullis", 5: gate or "locked door", 6: "secret door", 7: "barred door"}.get(t, "door")
            flags = {"door"} | ({"openable"} if t in (1, 5, 6) else set())
            flags |= {"lockable", "locked"} if t == 5 else set()
            flags |= {"portcullis"} if t == 4 else {"barred"} if t == 7 else set()
            flags |= {"hidden"} if t == 6 else set()
            nouns = [name.split()[-1]] + (["door"] if name.split()[-1] != "door" else [])
            door = w.spawn({"name": name, "nouns": nouns, "adjectives": name.split()[:-1], "flags": sorted(flags),
                            "description": gate_note or {4: "A heavy iron grille.", 5: "A stout door with a keyhole.",
                                                         7: "A door barred fast; it will not move."}.get(t, "A heavy wooden door."),
                            "provenance": "data"}, None, f"{prefix}:door{n}")
            door.props.update({"rooms": [ra, rb], "type": t})
            door_id, hidden = door.id, t == 6
            if t == 5:
                locked.append(door)
        link(w, ra, rb, compass(dx, dy), door_id, note, hidden, [compass(*_vector(d, a, b))])
    if locked and not key_ids:
        ends = [c.index for c in d.chambers if len(adj[c.index]) == 1 and c.index not in d.entrances]
        spot = rng.choice(sorted(ends) or [c.index for c in d.chambers])
        key_ids.append(w.spawn({"name": "small iron key", "nouns": ["key"], "adjectives": ["small", "iron"],
                                "description": "A small iron key.", "weight": 0.1, "flags": ["takeable"],
                                "initial": "A small iron key lies in the dust.", "provenance": "new"},
                               f"{prefix}:{spot}", f"{prefix}:key").id)
    for k in key_ids:
        w.things[k].unlocks = [door.id for door in locked]
    # the heart holds what the story names
    hroom = f"{prefix}:{heart}"
    if "treasure" in subjects:
        name = subjects["treasure"]
        w.spawn({"name": name, "nouns": list(dict.fromkeys(x.lower() for x in name.split()[::-1])), "adjectives": [],
                 "description": f"The {name} the stories speak of, smaller and heavier than you imagined.",
                 "weight": 1.0, "flags": ["takeable", "treasure", "story", "proper"], "value": 100,
                 "initial": f"On a plinth at the centre of the room sits the {name}.", "provenance": "data"},
                hroom, f"{prefix}:heart-treasure")
    if "creature" in subjects:
        name = subjects["creature"]
        group = " of " in name
        w.spawn({"name": name, "nouns": [name.split()[-1].lower(), name.split()[0].lower()],
                 "adjectives": [x.lower() for x in name.split()[1:-1]],
                 "description": f"The {name} the stories speak of.", "flags": ["creature"],
                 "here": f"A {name} {'mill about here, restless' if group else 'lies coiled here, asleep'}.",
                 "actions": {"attack": {"fatal": True, "text": f"You attack the {name}. It is the last thing you do."},
                             "wake": {"fatal": True, "text": f"The {name} wakes. Briefly, so do you."}},
                 "provenance": "data"}, hroom if heart_purpose == "lair" else _middle(d, depth, prefix),
                f"{prefix}:heart-creature")
    for k, (a, ra) in enumerate(entrance_dirs):
        out = outside if k == 0 or not rear_outside else rear_outside
        w.rooms[ra].exits["up"] = Exit(out, None, False, "stairs")
        w.rooms[ra].exits.setdefault("out", Exit(out, None, False, "stairs"))
        w.rooms[out].exits["down"] = Exit(ra, None, False, "stairs")
        w.rooms[out].exits.setdefault("in", Exit(ra, None, False, "stairs"))
    hc = d.chambers[heart]
    start = d.chambers[d.entrances[0]] if d.entrances else d.chambers[0]
    return {"heart": hroom, "heart_dir": compass(hc.x - start.x, hc.y - start.y), "theme": theme["name"],
            "subjects": subjects, "max_depth": max(depth.values() or [0])}


def _middle(d: Dungeon, depth: dict, prefix: str) -> str:
    mid = max(depth.values() or [0]) / 2
    c = min((c for c in d.chambers if not c.corridor), key=lambda c: abs(depth.get(c.index, 0) - mid))
    return f"{prefix}:{c.index}"


def _has_locked(d: Dungeon, chamber: int) -> bool:
    return any(t == 5 and chamber in (a, b) for a, b, t in d.links)


def _vector(d: Dungeon, a: int, b: int) -> tuple[float, float]:
    ca, cb = d.chambers[a], d.chambers[b]
    return (cb.x + cb.w / 2) - (ca.x + ca.w / 2), (cb.y + cb.h / 2) - (ca.y + ca.h / 2)
