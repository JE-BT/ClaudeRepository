"""People drawn from the map: how they look (kin from the culture's namebase, clothes from the
climate), who they are (origin, faith, tradition), what they can explain about named things
(burgs, states, faiths, cultures, rivers, routes, zones), and how they give directions."""
from __future__ import annotations

import json
import math
import random
import re
from collections import deque
from pathlib import Path

from .interiors import compass

TEXT = json.loads((Path(__file__).with_name("data") / "descriptions.json").read_text(encoding="utf-8"))


def kin_of(m, culture_id: int) -> dict:
    c = m.culture(culture_id)
    base = (c.get("name", "") + " " + str(c.get("base", ""))).lower()
    from .names import default_bases
    bases = default_bases()
    bname = bases[c.get("base", 0)]["name"].lower() if c.get("base", 0) < len(bases) else ""
    for key in ("dwarven", "orc", "elven", "goblin", "giant", "drak"):
        if key in base or key in bname:
            return TEXT["kin"][key]
    return TEXT["kin"]["human"]


def looks(m, culture_id: int, temp: float, seed: str, role: str = "") -> str:
    rng = random.Random(seed)
    k = kin_of(m, culture_id)
    climate = "hot" if temp >= 22 else "cold" if temp <= 5 else "mild"
    age = rng.choice(["young", "middle-aged", "old", "grizzled", "youthful"])
    return (f"A {rng.choice(k['build'])} {age} {k['kin']} with {rng.choice(k['feature'])}, "
            f"in {rng.choice(TEXT['clothes'][climate])}" + (f", plainly a {role}" if role else "") + ".")


def bio(m, culture_id: int, religion_id: int, home: str, seed: str) -> str:
    c = m.culture(culture_id)
    r = m.religion(religion_id) if religion_id else {}
    trad = TEXT["traditions"].get(c.get("type", "Generic"), TEXT["traditions"]["Generic"]).format(culture=c["name"])
    faith = ""
    if r.get("name"):
        deity = f", whose god is {r['deity']}" if r.get("deity") else ""
        faith = f" Keeps to the {r['name']} ({(r.get('form') or r.get('type') or 'faith').lower()}{deity})."
    return f"Born in {home}; {trad}.{faith}"


# ---------------------------------------------------------------- knowledge
def explain(m, words: list[str]) -> str | None:
    """What a local would say about a named thing in the map."""
    text = " ".join(words).lower()

    def hit(name: str) -> bool:
        return bool(name) and any(len(w) > 3 and w in text for w in re.findall(r"[a-z']+", name.lower()))
    for b in m.live_burgs():
        if hit(b["name"]):
            st = m.state(b.get("state", 0))
            return (f"{b['name']}? A {b.get('group', 'place')} of the {st.get('fullName') or st['name']}, "
                    f"{m.culture(b.get('culture', 0))['name']} folk mostly.")
    for s in m.live("states")[1:]:
        if hit(s.get("name", "")):
            return f"The {s.get('fullName') or s['name']}. A {s.get('form', 'realm').lower()}, ruled from " \
                   f"{m.burg(s['capital'])['name'] if s.get('capital') else 'somewhere'}."
    for r in m.live("religions")[1:]:
        if hit(r.get("name", "")):
            return f"The {r['name']}: {(r.get('type') or '').lower()} {(r.get('form') or '').lower()}" + \
                   (f", worshipping {r['deity']}" if r.get("deity") else "") + "."
    for z in m.live("zones"):
        if hit(z.get("name", "")):
            return f"The {z['name']}. {z['type']}; folk talk of little else."
    for r in m.live("routes"):
        if hit(r.get("name") or ""):
            return f"The {r['name']} is a {r['group'][:-1]} between the towns; quicker than the wild ground."
    for rv in m.live("rivers"):
        if hit(rv.get("name", "")):
            return f"The {rv['name']}. A {rv.get('type', 'river').lower()}; you'll cross it or follow it, one or the other."
    return None


# ---------------------------------------------------------------- directions
def route(w, start: str, goal: str) -> list[str] | None:
    """Exits to take from start to goal, by breadth-first search over the world's rooms."""
    prev = {start: None}
    todo = deque([start])
    while todo:
        r = todo.popleft()
        if r == goal:
            break
        for d, e in w.rooms[r].exits.items():
            if e.to in w.rooms and e.to not in prev and not e.hidden:
                prev[e.to] = (r, d)
                todo.append(e.to)
    if goal not in prev:
        return None
    steps, r = [], goal
    while prev[r]:
        r0, d = prev[r]
        steps.append((d, r))
        r = r0
    return list(reversed(steps))


def say_directions(w, steps) -> str:
    if not steps:
        return "You're there already."
    parts, last, run = [], None, 0
    for d, r in steps:
        if d == last:
            run += 1
            continue
        if last:
            parts.append(f"{last}{' a way' if run > 1 else ''}")
        last, run = d, 1
    parts.append(f"{last}{' a way' if run > 1 else ''}")
    goal = w.rooms[steps[-1][1]]
    return f"Go {', then '.join(parts)}, and you'll find {goal.area if goal.area and goal.area != w.rooms[steps[0][1]].area else goal.name}."
