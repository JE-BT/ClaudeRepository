"""The main storyline, generated from the journey and the map.

Genre (premise, the reason for the deadline, the commission token, the contact, the cargo,
climax and failure) comes from the journey type. Beats are placed along the journey:
  the commission at the start; each planned stay at a burg (a stop); borders into hostile
  states and zones the track enters (passive beats that explain the road); the meeting point
  (Azgaar's Party marker, if near the route); the cargo before the first laden stage; the
  climax at the destination, with a deadline the plan's own length explains.
Dungeons on the track become leads: optional storylines whose clue is another way to the
climax. A content pack's story.json can replace texts (canon first) and add topics.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..interiors import compass
from ..names import NameGenerator
from .model import Element, Phase, StoryState, Storyline

GENRES = json.loads((Path(__file__).with_name("genres.json")).read_text(encoding="utf-8"))
HOSTILE = {"Enemy", "Rival", "Suspicion"}
ZONE_TEXT = {
    "Proselytism": "Missionaries of the {name} work the road here, and they remember faces.",
    "Crusade": "The {name} has made the road a march; soldiers question everyone.",
    "Invasion": "The {name} holds this country; foreign patrols watch the road.",
    "Rebels": "The {name} hold the back roads; strangers are suspects to both sides.",
    "Disease": "The {name} is abroad here; villages bar their gates.",
    "Disaster": "The {name} has left the country thin; food and water cost dearly.",
    "Flood": "The {name} has torn up the low roads.",
}


def genre(journey_type: str) -> dict:
    g = dict(GENRES["default"])
    g.update(GENRES.get(journey_type, {}))
    g["stops"] = {**GENRES["default"]["stops"], **g.get("stops", {})}
    return g


def title_tokens(title: str, fallback_dest: str) -> dict:
    for pat in (r"^The (?P<beast>[\w' -]+?) of (?P<destination>[A-Z][\w'-]+(?: [A-Z][\w'-]+)*)$",
                r"^The Hunt for the (?:[\w'-]+ )?(?P<beast>[\w'-]+)$", r"^Bounty on the (?P<beast>[\w' -]+)$",
                r"hunts the (?P<beast>[\w' -]+)$"):
        if m := re.search(pat, title):
            return {"beast": m.groupdict().get("beast", "quarry").lower(),
                    "destination": m.groupdict().get("destination") or fallback_dest}
    return {"beast": "quarry", "destination": fallback_dest}


def _fill(text: str, tokens: dict) -> str:
    return re.sub(r"{(\w+)}", lambda m: str(tokens.get(m.group(1), m.group(0))), text or "")


def _burg_at(m, point, strict_mi: float):
    cell = point[2]
    b = next((b for b in m.live_burgs() if b["cell"] == cell), None)
    if b:
        return b
    near = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), point[:2]))
    return near if math.dist((near["x"], near["y"]), point[:2]) * m.mi_per_px <= strict_mi else None


def _stop_kind(name: str) -> str:
    low = name.lower()
    for key, words in (("bounty", ("bounty", "report", "register", "muster")), ("port", ("anchor", "port", "harbour", "harbor")),
                       ("tavern", ("night at", "tankard", "inn", "tavern")), ("camp", ("camp", "bivouac"))):
        if any(w in low for w in words):
            return key
    return "stay"


def build(files, journey, cfg: dict, overlay: dict | None = None) -> tuple[StoryState, dict]:
    m, j = files.map, journey
    overlay = overlay or {}
    g = genre(j.type)
    first, last = j.stages[0], j.stages[-1]
    origin = _burg_at(m, first.points[0], 50) or m.live_burgs()[0]
    dest = _burg_at(m, last.points[-1], 50) or origin
    tok = title_tokens(j.name, dest["name"])
    deadline_day = int(math.ceil(j.total_days * 1.1)) + 1
    tok.update({"origin": origin["name"], "deadline": deadline_day,
                "faith": m.religion(m.cell("religion")[dest["cell"]]).get("name", ""),
                "dest_state": m.state(dest.get("state", 0)).get("name", ""), "cargo": g["cargo"]["name"]})
    for k in ("premise", "why_time", "goal", "climax", "failure"):
        if overlay.get(k):
            g[k] = overlay[k]
    names = NameGenerator(m.namebase_overrides())
    main = Storyline("main", j.name, "main", _fill(g["premise"], tok), [], {})
    main.elements["token"] = Element("token", "item", {
        "name": g["token"]["name"], "nouns": g["token"]["nouns"], "weight": 0.05,
        "flags": ["takeable", "readable", "story"], "text": _fill(g["token"]["text"], tok),
        "description": f"Your {g['token']['name']}.", "provenance": "new"}, {"carried": True})
    beats: list[Phase] = [Phase("commission", "The commission", _fill(g["goal"], tok),
                                _fill(g["premise"] + " " + g["why_time"], tok), [{"kind": "start"}], points=0,
                                pos=[0, 0], required=True, effects={"give": ["token"]}, source="your commission")]
    # stops
    for st in j.stages[1:-1]:
        if not st.is_stay:
            continue
        b = _burg_at(m, st.points[0], cfg.get("strict_mi", 2.0))
        kind = _stop_kind(st.name)
        named = next((m.burg_by_name(w) for w in re.findall(r"[A-Z][\w'-]+", st.name) if m.burg_by_name(w)), None)
        place = b["name"] if b else (named["name"] if named else "the anchorage")
        trig = [{"kind": "at", "burg": b["i"]}] if b else [{"kind": "pass", "pos": [st.index, 0]}]
        beats.append(Phase(f"stop{st.index}", st.name, _fill(g["stops"][kind], {**tok, "place": place}),
                           _fill(g["stops"][kind], {**tok, "place": place}), trig, points=10 if b else 0,
                           pos=[st.index, 0], on_miss=f"You pass {place} by without stopping.",
                           source=f"the plan agreed in {origin['name']}"))
    # borders and zones the track enters
    origin_state = m.state(origin.get("state", 0))
    seen_zones = set()
    for c in j.crossings():
        if c.kind == "state" and c.after != c.before:
            target = next((s for s in m.live("states") if s.get("name") == c.after), None)
            rel = origin_state.get("diplomacy", [])[target["i"]] if target and target["i"] < len(origin_state.get("diplomacy", [])) else ""
            if rel in HOSTILE:
                beats.append(Phase(f"border{c.stage}-{int(c.mile)}", f"Into {c.after}",
                                   f"Get across the border into {c.after}.",
                                   f"{c.after} counts {origin_state['name']} as {rel.lower()}; the border posts will not "
                                   f"pass a party out of {origin['name']}. You keep to the wild ground and cross where no one watches.",
                                   [{"kind": "pass", "pos": [c.stage, c.mile]}], points=5, pos=[c.stage, c.mile]))
        if c.kind == "zone" and c.after != "none":
            for zname in c.after.split(", "):
                z = next((z for z in m.live("zones") if z["name"] == zname), None)
                if z and zname not in seen_zones and z["type"] in ZONE_TEXT:
                    seen_zones.add(zname)
                    beats.append(Phase(f"zone{z['i']}", zname, f"Pass through the country of the {zname}.",
                                       _fill(ZONE_TEXT[z["type"]], {"name": zname}),
                                       [{"kind": "pass", "pos": [c.stage, c.mile]}], points=0, pos=[c.stage, c.mile]))
    # meeting point: Azgaar's Party marker near the route
    near = {(n.kind, n.id): n for n in j.nearby(cfg.get("corridor_mi", 40))}
    party = next((mk for mk in m.live("markers") if mk["type"] == "party" and ("marker", mk["i"]) in near), None)
    if party:
        n = near[("marker", party["i"])]
        mb = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), (party["x"], party["y"])))
        cname = names.name(m.culture(mb.get("culture", 0)).get("base", 0), f"{m.seed}:contact")
        cargo_hint = (f"Whatever you do, get the {g['cargo']['name']} before the last of the road: "
                      f"{_fill(g['cargo']['why'], tok)}")
        spec = {"name": cname, "nouns": [cname.lower(), "contact", "stranger", "traveller"], "flags": ["person", "proper"],
                "description": f"{cname}, {_fill(g['contact'], tok)}.", "here": f"{cname} is here, waiting for someone. You, it seems.",
                "talk": f"{cname} looks you over. \"You're the ones out of {origin['name']}. I was told to wait.\"",
                "topics": {"beast|" + tok["beast"]: f"I've seen what the {tok['beast']} leaves. {cargo_hint}",
                           "road|route|way": "The road ahead is longer than your plan admits. Don't dawdle where you needn't.",
                           "deadline|time|day": f"Day {deadline_day}. After that you might as well go home."},
                "provenance": "new"}
        spec.update(overlay.get("contact", {}))
        main.elements["contact"] = Element("contact", "person", spec,
                                           {"burg": mb["i"], "prefer": ["guest room", "hall", "living room", "kitchen", "parlour"]})
        beats.append(Phase("meeting", f"The meeting at {mb['name']}", f"Find your contact in {mb['name']}.",
                           f"{cname} tells you what lies ahead. {cargo_hint}",
                           [{"kind": "talk", "thing": "contact"}, {"kind": "ask", "thing": "contact"}], mode="any",
                           points=10, pos=[n.stage, n.along_mi], on_miss=f"You never met your contact in {mb['name']}.",
                           effects={"flags": {"met_contact": True}, "burg": mb["i"]},
                           source=f"your commission names a contact who will wait in {mb['name']}"))
    # the cargo before the first laden stage
    laden = next((st for st in j.stages[1:] if not st.is_stay and "laden" in st.transport.lower()), None)
    if laden:
        b = _burg_at(m, laden.points[0], 50) or dest
        main.elements["cargo"] = Element("cargo", "item", {
            "name": g["cargo"]["name"], "nouns": g["cargo"]["nouns"], "weight": 12.0, "flags": ["takeable", "story", "cargo"],
            "description": f"The {g['cargo']['name']}. {_fill(g['cargo']['why'], tok)}",
            "initial": f"The {g['cargo']['name']} wait here, ready for you.", "hint": "Heavy. It will slow you; that is the price.",
            "provenance": "new"}, {"burg": b["i"], "prefer": ["storeroom", "storage", "store room", "cellar", "hall"]})
        beats.append(Phase("cargo", "The burden", f"Collect the {g['cargo']['name']} in {b['name']}.",
                           _fill(g["cargo"]["why"], tok), [{"kind": "have", "item": "cargo"}], points=10,
                           pos=[laden.index, -1], required=True, effects={"burg": b["i"]},
                           source="the last stretch is planned laden: something heavy must be carried"))
    # climax
    beats.append(Phase("climax", f"{dest['name']}", _fill(g["goal"], tok), _fill(g["climax"], tok),
                       [{"kind": "at", "burg": dest["i"]}],
                       requires=[["story:main:cargo", "clue"]] if laden else [], points=50,
                       pos=[last.index, last.miles], required=True, deadline_t=(deadline_day - 1) * 24 + 12,
                       on_miss=_fill(g["failure"], tok), source=f"the {g['token']['name']}",
                       effects={"end": "success", "end_text": _fill(g["climax"], tok)}))
    beats.sort(key=lambda p: (p.pos[0], p.pos[1], p.id != "commission"))
    # warnings: a stop (or the commission) warns of the hazards before the next stop; miss it and luck decides
    warner = beats[0]
    for p in beats[1:]:
        hazard = p.id.startswith(("border", "zone"))
        if hazard:
            p.effects["luck"] = {"flag": f"warned:{p.id}", "hours": [12, 72] if p.id.startswith("zone") else [24, 96]}
            warner.effects.setdefault("flags", {})[f"warned:{p.id}"] = True
            if warner.id != "commission":
                warner.text += f" Word here warns of what lies ahead: {p.title}."
        elif p.id.startswith("stop") and p.triggers[0]["kind"] == "at":
            warner = p
    main.phases = beats
    state = StoryState()
    state.seed = f"{m.seed}:{j.name}"
    state.storylines.append(main)
    # leads: dungeons on the track
    strict = cfg.get("strict_mi", 2.0)
    for (kind, mid), n in sorted(near.items(), key=lambda kv: (kv[1].stage, kv[1].along_mi)):
        if kind != "marker" or n.offset_mi > strict or "one-page-dungeon" not in (n.extra.get("note") or ""):
            continue
        place = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), (n.extra["x"], n.extra["y"])))
        lead = Storyline(f"lead{mid}", f"A lead near {place['name']}", "lead",
                         f"Something in the old place near {place['name']} may matter to the hunt.", [], {})
        lead.elements["clue"] = Element("clue", "clue", {
            "name": "inscribed tablet", "nouns": ["tablet", "inscription"], "adjectives": ["inscribed", "stone"],
            "weight": 2.0, "flags": ["takeable", "readable", "story"],
            "text": f"Old letters, cut deep: what walks in {tok['destination']} answers to its name, and what answers can be bound.",
            "initial": "An inscribed stone tablet leans against the wall.", "provenance": "new"},
            {"marker": mid, "heart": True})
        lead.phases = [
            Phase("rumour", "A rumour", f"Look into the old place near {place['name']}.",
                  f"Word on the road: the old place near {place['name']} holds something that bears on the {tok['beast']}.",
                  [{"kind": "pass", "pos": [n.stage, max(0, n.along_mi - 40)]}], points=0, pos=[n.stage, max(0, n.along_mi - 40)]),
            Phase("enter", "Into the dark", f"Find what lies deepest in the old place near {place['name']}.",
                  "You have found the old place.", [{"kind": "at", "marker": mid}], points=5, pos=[n.stage, n.along_mi],
                  source="a rumour on the road"),
            Phase("heart", "What lies deepest", "Take what you came for, and get out.",
                  "You have it: a way to bind the quarry that does not depend on what you carry.",
                  [{"kind": "take", "item": "clue"}], points=15, pos=[n.stage, n.along_mi],
                  effects={"flags": {"clue": True}})]
        state.storylines.append(lead)
    # planted on purpose: an heirloom in the first lead dungeon, an unsent letter at the first town stop
    plants = Storyline("plants", "Planted", "plant", "Things placed on purpose to start side stories.", [], {}, "dormant")
    first_lead = next((s_ for s_ in state.storylines if s_.kind == "lead"), None)
    if first_lead:
        mid = first_lead.elements["clue"].anchor["marker"]
        plants.elements["ring"] = Element("ring", "item", {
            "name": "signet ring", "nouns": ["ring", "signet"], "adjectives": ["signet", "gold"], "weight": 0.02,
            "flags": ["takeable", "treasure"], "value": 30, "plant": "heirloom",
            "initial": "A signet ring glints in the dust.", "description": "A heavy gold signet ring, worn smooth.",
            "provenance": "new"}, {"marker": mid, "prefer": ["treasury", "guard room", "storeroom", "barracks", "cell"]})
    first_stop = next((p for p in beats if p.id.startswith("stop") and p.triggers[0]["kind"] == "at"), None)
    if first_stop:
        plants.elements["letter"] = Element("letter", "item", {
            "name": "unsent letter", "nouns": ["letter"], "adjectives": ["unsent", "sealed"], "weight": 0.02,
            "flags": ["takeable", "readable"], "plant": "letter", "initial": "A sealed letter lies forgotten on a table.",
            "description": "A sealed letter, addressed in a careful hand.", "provenance": "new"},
            {"burg": first_stop.triggers[0]["burg"], "prefer": ["taproom", "guest room", "guild hall"]})
    if plants.elements:
        state.storylines.append(plants)
    return state, tok
