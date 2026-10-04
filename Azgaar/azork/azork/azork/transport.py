"""People who carry travellers: carters, boatmen, caravan masters.

A carrier is bound somewhere ahead on the journey (the next town on the route, or the next
port for boats). The price follows the distance; a carrier of another faith charges more; one
whose realm counts the party's homeland as an enemy or rival will not take them without papers
(a registered writ). BOOK PASSAGE WITH <name> pays and goes.
"""
from __future__ import annotations

import random

from .names import NameGenerator
from .people import bio, looks

HOSTILE = {"Enemy", "Rival"}


def _home_state(campaign) -> dict:
    j, m = campaign.journey, campaign.files.map
    first = j.stages[0].points[0]
    return m.state(m.cell("state")[first[2]])


def carrier_spec(campaign, transport: str, rng: random.Random, w, at_burg: dict | None = None) -> dict | None:
    m, j = campaign.files.map, campaign.journey
    water = m.transport(transport)["domain"] == "water"
    ahead = [n for n in j.nearby(campaign.cfg.get("strict_mi", 2.0) + 3)
             if n.kind == "burg" and (n.stage, n.along_mi) > (campaign.pos[0], campaign.pos[1] + 10)
             and (not water or m.burg(n.id).get("port"))]
    if not ahead:
        return None
    dest = min(ahead, key=lambda n: (n.stage, n.along_mi))
    if not water:
        dest = ahead[min(len(ahead) - 1, rng.randrange(1, 4))]
    miles = abs(j.when(dest.stage, dest.along_mi) - j.when(*campaign.pos)) / 24 * 40  # plan days -> rough miles
    t = m.transport(transport)
    hours = miles / t["speed"] * 24 / t["hoursPerDay"]
    cell = at_burg["cell"] if at_burg else campaign.files.map.burg(dest.id)["cell"]
    culture, religion, state = m.cell("culture")[cell], m.cell("religion")[cell], m.state(m.cell("state")[cell])
    home = _home_state(campaign)
    price = max(3, round(miles / 12))
    party_faith = m.cell("religion")[j.stages[0].points[0][2]]
    if religion != party_faith:
        price *= 2
    rel = state.get("diplomacy", [])[home["i"]] if home["i"] < len(state.get("diplomacy", [])) else ""
    name = NameGenerator(m.namebase_overrides()).name(m.culture(culture).get("base", 0), f"{w.seed}:{transport}:{dest.id}")
    role = "boatman" if water else "carter"
    refuse = (f"{name} spits. \"{home['name']}? Not without papers, I don't. Get your writ registered and come back.\""
              if rel in HOSTILE else None)
    temp = 20
    return {"name": name, "nouns": [name.lower(), role, "carrier"], "flags": ["person", "proper", "carrier"],
            "description": looks(m, culture, temp, f"{w.seed}:{name}", role) + " " +
            bio(m, culture, religion, m.burg(dest.id)["name"] if not at_burg else at_burg["name"], f"{w.seed}:{name}"),
            "here": f"{name}, a {role}, is here, bound for {dest.name}.",
            "greet": f"{name} looks you over. \"Bound for {dest.name}. {price} coins, about {hours / 24:.1f} days. "
                     f"BOOK PASSAGE WITH {name.upper()} if you want it.\"",
            "topics": {"passage|ride|boat|ship|wagon|cart|travel|price|cost":
                       f"{dest.name}, {price} coins, about {hours / 24:.1f} days by {transport.lower()}."},
            "carrier": {"transport": transport, "to": dest.id, "to_name": dest.name, "pos": [dest.stage, dest.along_mi],
                        "price": price, "hours": hours, "refuse": refuse},
            "provenance": "new"}
