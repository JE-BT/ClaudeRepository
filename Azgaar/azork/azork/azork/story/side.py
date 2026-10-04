"""Side stories, hooked by what the player does and dispersed along the road ahead.

Templates:
  last_request  a dying person asks you to take a token to their kin in a burg ahead
  heirloom      a treasure bears the crest of a family in a burg ahead
  site_rumour   someone wants proof from a site (a dungeon marker) they mention; a buyer waits ahead
Elements go where they make sense: the token in your hand, kin and buyers in burgs ahead on the
route (preferring places that already have scenes), proof in the deepest room of the site.
Reward for side stories can be time: someone who knows the country shows you a shorter way.
"""
from __future__ import annotations

import random

from ..names import NameGenerator
from .model import Element, Phase, Storyline

MAX_ACTIVE = 3


def _ahead(ctx: dict, rng: random.Random) -> dict | None:
    """A burg ahead of the party on the route, within two days of plan time, preferring scenes."""
    j, pos = ctx["journey"], ctx["pos"]
    here_t = j.when(pos[0], max(pos[1], 0))
    cands = []
    for n in j.nearby(ctx.get("corridor_mi", 40)):
        if n.kind != "burg" or (n.stage, n.along_mi) <= (pos[0], pos[1] + 5):
            continue
        dt = j.when(n.stage, n.along_mi) - here_t
        if 0 < dt <= 48 * 3:
            cands.append((n.id not in ctx.get("scene_burgs", set()), dt, n))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]))
    pick = rng.choice(cands[:4])[2]
    return {"burg": pick.id, "stage": pick.stage, "mile": pick.along_mi}


def maybe_hook(state, event: dict, thing, ctx: dict) -> list[str]:
    plant = thing.props.get("plant") if thing is not None else None
    if thing is None or state.flags.get(f"hooked:{thing.id}") or (thing.id.startswith("story:") and not plant):
        return []
    active = [s for s in state.storylines if s.kind == "side" and s.status == "active"]
    if len(active) >= MAX_ACTIVE:
        return []
    rng = random.Random(f"{ctx['seed']}:{thing.id}")
    m = ctx["files"].map
    names = NameGenerator(m.namebase_overrides())
    line = None
    if plant == "letter" and event["type"] in ("examine", "take", "read"):
        line = _letter(thing, ctx, rng, names)
    elif plant == "heirloom" and event["type"] in ("examine", "take"):
        line = _heirloom(thing, ctx, rng, names)
    elif event["type"] in ("talk", "ask") and "person" in thing.flags and "dying" in thing.adjectives:
        line = _last_request(thing, ctx, rng, names)
    elif event["type"] in ("examine", "take") and "treasure" in thing.flags and "story" not in thing.flags \
            and rng.random() < 0.6:
        line = _heirloom(thing, ctx, rng, names)
    elif event["type"] == "ask" and "person" in thing.flags:
        site = next((mid for kw, mid in ctx.get("sites", {}).items() if kw in (event.get("topic") or [])), None)
        if site is not None and not state.line(f"rumour{site}") and rng.random() < 0.7:
            line = _site_rumour(thing, site, ctx, rng, names)
    if not line:
        return []
    state.flags[f"hooked:{thing.id}"] = True
    state.storylines.append(line)
    return state.notify({"type": "start"})


def _kin(m, names, burg: int, seed: str) -> str:
    b = m.burg(burg)
    return names.name(m.culture(b.get("culture", 0)).get("base", 0), seed)


def _last_request(thing, ctx, rng, names):
    m = ctx["files"].map
    where = _ahead(ctx, rng)
    if not where:
        return None
    burg = m.burg(where["burg"])
    kin = _kin(m, names, burg["i"], f"{ctx['seed']}:{thing.id}:kin")
    sid = f"side-{thing.id.replace(':', '-')}"
    line = Storyline(sid, f"A last request", "side", f"Take a token from the {thing.name} to {kin} in {burg['name']}.", [], {})
    line.elements["token"] = Element("token", "item", {
        "name": "tarnished locket", "nouns": ["locket"], "adjectives": ["tarnished"], "weight": 0.05,
        "flags": ["takeable", "story"], "description": f"A tarnished locket. It belongs with {kin} in {burg['name']}.",
        "provenance": "new"}, {"carried": True})
    line.elements["kin"] = Element("kin", "person", {
        "name": kin, "nouns": [kin.lower(), "kin"], "flags": ["person", "proper"], "description": f"{kin} of {burg['name']}.",
        "here": f"{kin} is here.", "talk": f"{kin} looks at you warily. \"Do I know you?\"",
        "topics": {"locket|halfling|token": "Where did you get that? Tell me. Tell me all of it."}, "provenance": "new"},
        {"burg": burg["i"], "prefer": ["living room", "kitchen", "hall", "parlour"]})
    line.phases = [
        Phase("ask", "A last request", f"Take the locket to {kin} in {burg['name']}.",
              f"The {thing.name} presses a tarnished locket into your hand. \"{kin}. {burg['name']}. Tell them I tried.\"",
              [{"kind": "start"}], points=0, effects={"give": ["token"]}),
        Phase("deliver", f"{kin} of {burg['name']}", f"Give the locket to {kin} in {burg['name']}.",
              f"{kin} holds the locket a long time. \"You came out of your way for this. Take the drovers' track past "
              f"the ford; it will save you half a day.\"", [{"kind": "give", "item": "token", "to": "kin"}], points=15,
              pos=[where["stage"], where["mile"]], on_miss=f"You have passed {burg['name']}. The locket stays with you.",
              effects={"delay_hours": -6})]
    return line


def _heirloom(thing, ctx, rng, names):
    m = ctx["files"].map
    where = _ahead(ctx, rng)
    if not where:
        return None
    burg = m.burg(where["burg"])
    owner = _kin(m, names, burg["i"], f"{ctx['seed']}:{thing.id}:owner")
    sid = f"side-{thing.id.replace(':', '-')}"
    line = Storyline(sid, f"The crest on the {thing.name}", "side", f"Return the {thing.name} to {owner} in {burg['name']}.", [], {})
    line.elements["owner"] = Element("owner", "person", {
        "name": owner, "nouns": [owner.lower(), "owner"], "flags": ["person", "proper"],
        "description": f"{owner} of {burg['name']}, of an old and impoverished house.", "here": f"{owner} is here.",
        "topics": {thing.nouns[0]: f"My grandfather's. It went into the dark with him. If you have it, name your price."},
        "accepts": {"|".join(thing.nouns): {"text": f"{owner} weeps, briefly and with dignity, and pays you well.",
                                            "reward": {"name": "purse of silver", "nouns": ["purse", "silver"],
                                                       "weight": 0.3, "flags": ["takeable", "money"], "value": 40}}},
        "provenance": "new"}, {"burg": burg["i"], "prefer": ["library", "living room", "hall", "parlour"]})
    line.phases = [
        Phase("crest", "A crest", f"Return the {thing.name} to {owner} in {burg['name']}, or keep it.",
              f"Turning the {thing.name} over, you find a crest, and a name: {owner}, of {burg['name']}.",
              [{"kind": "start"}], points=0),
        Phase("return", f"Home to {burg['name']}", f"Give the {thing.name} to {owner} in {burg['name']}.",
              f"The {thing.name} is home.", [{"kind": "give", "item": thing.id, "to": "owner"}], points=10,
              pos=[where["stage"], where["mile"]], on_miss=f"You have passed {burg['name']}; the {thing.name} stays yours.")]
    return line


def _site_rumour(thing, site, ctx, rng, names):
    m = ctx["files"].map
    where = _ahead(ctx, rng)
    if not where:
        return None
    burg = m.burg(where["burg"])
    buyer = _kin(m, names, burg["i"], f"{ctx['seed']}:{site}:buyer")
    mk = next(x for x in m.live("markers") if x["i"] == site)
    sid = f"rumour{site}"
    line = Storyline(sid, f"Proof from the {mk['type'].rstrip('s')}", "side",
                     f"Bring proof from the {mk['type'].rstrip('s')} to {buyer} in {burg['name']}.", [], {})
    line.elements["proof"] = Element("proof", "item", {
        "name": "carved token", "nouns": ["token"], "adjectives": ["carved", "bone"], "weight": 0.2,
        "flags": ["takeable", "story"], "initial": "A carved bone token lies where no one has disturbed it in years.",
        "description": "A carved bone token, old as the stones.", "provenance": "new"}, {"marker": site, "heart": True})
    line.elements["buyer"] = Element("buyer", "person", {
        "name": buyer, "nouns": [buyer.lower(), "buyer", "collector"], "flags": ["person", "proper"],
        "description": f"{buyer}, a collector of old things.", "here": f"{buyer} is here, turning over a coin.",
        "accepts": {"token": {"text": f"{buyer} pays without haggling, which worries you more than haggling would.",
                              "reward": {"name": "purse of silver", "nouns": ["purse", "silver"], "weight": 0.3,
                                         "flags": ["takeable", "money"], "value": 40}}}, "provenance": "new"},
        {"burg": burg["i"], "prefer": ["library", "study", "living room", "hall"]})
    line.phases = [
        Phase("rumour", "A rumour", f"Find proof in the {mk['type'].rstrip('s')} and take it to {buyer} in {burg['name']}.",
              f"The {thing.name} lowers their voice. \"A collector in {burg['name']}, {buyer}, pays for anything out of that place.\"",
              [{"kind": "start"}], points=0),
        Phase("proof", "Proof", "Find the oldest thing in the deepest room.", "You have your proof.",
              [{"kind": "take", "item": "proof"}], points=10),
        Phase("sell", f"A buyer in {burg['name']}", f"Give the token to {buyer} in {burg['name']}.", "Sold.",
              [{"kind": "give", "item": "proof", "to": "buyer"}], points=10, pos=[where["stage"], where["mile"]],
              on_miss=f"You have passed {burg['name']}; the collector will have to wait.")]
    return line


def _letter(thing, ctx, rng, names):
    m = ctx["files"].map
    where = _ahead(ctx, rng)
    if not where:
        return None
    burg = m.burg(where["burg"])
    to = _kin(m, names, burg["i"], f"{ctx['seed']}:{thing.id}:to")
    sid = f"side-{thing.id.replace(':', '-')}"
    thing.text = f"To {to}, {burg['name']}. Sealed; the wax is unbroken."
    line = Storyline(sid, "An unsent letter", "side", f"Deliver the letter to {to} in {burg['name']}.", [], {})
    line.elements["to"] = Element("to", "person", {
        "name": to, "nouns": [to.lower(), "recipient"], "flags": ["person", "proper"],
        "description": f"{to} of {burg['name']}.", "here": f"{to} is here.",
        "topics": {"letter|seal": "A letter for me? From whom? Give it here."}, "provenance": "new"},
        {"burg": burg["i"], "prefer": ["living room", "parlour", "taproom", "hall"]})
    line.phases = [
        Phase("found", "An unsent letter", f"Deliver the letter to {to} in {burg['name']}.",
              f"The letter is addressed to {to}, in {burg['name']}, further along your road.",
              [{"kind": "start"}], points=0),
        Phase("deliver", f"A letter for {to}", f"Give the letter to {to} in {burg['name']}.",
              f"{to} reads it twice, then looks at you differently. \"You'll want to avoid the low road past the next "
              f"river; it floods. Go by the ridge.\"", [{"kind": "give", "item": thing.id, "to": "to"}], points=10,
              pos=[where["stage"], where["mile"]], on_miss=f"You have passed {burg['name']}; the letter stays sealed.",
              effects={"delay_hours": -4})]
    return line
