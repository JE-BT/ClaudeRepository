"""What people know: topics built from map data around a place, distorted by distance.

Near places get directions and times; far places arrive as hearsay. Markers nearby become
rumours (hints to dungeons and sites); the journey's stops become things people have heard of.
"""
from __future__ import annotations

import math
import re

from .interiors import compass


def _words(name: str) -> str:
    return "|".join(w for w in re.findall(r"[a-z']+", name.lower()) if len(w) > 2)


def _distance_phrase(miles: float) -> str:
    return ("just down the road" if miles < 15 else "a day's walk" if miles < 45 else
            "two or three days on foot" if miles < 120 else "a long way off")


def lore(files, x: float, y: float, journey=None) -> dict:
    m = files.map
    topics: dict[str, str] = {}
    here = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), (x, y)))
    state = m.state(here.get("state", 0))
    rel = m.religion(m.cell("religion")[here["cell"]])
    topics[_words(here["name"]) + "|town|village|place|here"] = (
        f"{here['name']}? You're standing in it, near enough. {here.get('group', 'settlement').capitalize()}, "
        f"about {round(here['population'] * 1000):,} souls, under {state.get('fullName') or state['name']}.")
    topics[_words(state["name"]) + "|king|queen|ruler|crown|state"] = (
        f"{state.get('fullName') or state['name']}. Taxes, mostly; that's what we see of it.")
    if rel.get("name"):
        topics[_words(rel["name"]) + "|faith|god|gods|church|temple|religion"] = (
            f"Most folk here keep to the {rel['name']}.")
    for b in m.live_burgs():
        miles = math.dist((b["x"], b["y"]), (x, y)) * m.mi_per_px
        if b["i"] == here["i"] or miles > 120:
            continue
        d = compass(b["x"] - x, b["y"] - y)
        topics.setdefault(_words(b["name"]), f"{b['name']}? {_distance_phrase(miles).capitalize()}, {d} of here.")
    rumours = []
    for mk in m.live("markers"):
        miles = math.dist((mk["x"], mk["y"]), (x, y)) * m.mi_per_px
        if miles > 60 or mk["type"] in ("party",):
            continue
        near = min(m.live_burgs(), key=lambda b: math.dist((b["x"], b["y"]), (mk["x"], mk["y"])))
        kind = mk["type"].rstrip("s").replace("-", " ")
        text = f"There's an old {kind} out past {near['name']}, {_distance_phrase(miles)}. Folk keep clear."
        topics.setdefault(_words(mk.get("name", "")) + f"|{kind}", text)
        rumours.append(text)
    if journey:
        for st in journey.stages:
            for name in re.findall(r"[A-Z][a-z'-]+", st.name):
                b = m.burg_by_name(name)
                if b and _words(b["name"]) not in topics:
                    topics[_words(b["name"])] = f"{b['name']}? Only heard of it. Far away; folk tell stories."
        lead = journey.name.split(" of ")[0].replace("The ", "").lower()
        dest = journey.name.split(" of ")[-1]
        topics[_words(dest) + f"|{lead}"] = (
            f"{dest}? They say something walks there that ought to lie still. I'd not go, myself.")
        rumours.append(f"A traveller swore that in {dest} the dead do not stay buried.")
    topics["_rumours"] = rumours
    return topics


def as_props(topics: dict) -> dict:
    return {k: v for k, v in topics.items() if not k.startswith("_")}
