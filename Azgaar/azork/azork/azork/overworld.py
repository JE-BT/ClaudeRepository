"""The overworld (phase 3): the journey as a chain of waypoints.

Waypoints are the planned stops, the burgs and sites within strict_mi of the track, and each
stage's end. Moving ONWARD or BACK takes the plan's own time (with any faster passage booked),
passes story beats, and spends food and water day by day; water is refilled where the road
crosses a river or passes a burg. At a waypoint you can ENTER a place (a town, a dungeon) or
DETOUR to one nearby in the corridor, at the cost of the walk there and back.
"""
from __future__ import annotations

import math

from . import setup
from .engine.model import Exit, Room, World
from .interiors import compass


def waypoints(campaign) -> list[dict]:
    j, m, cfg = campaign.journey, campaign.files.map, campaign.cfg
    pts: list[dict] = []
    for st in j.stages:
        x, y, cell = st.points[0] if st.is_stay else st.points[-1]
        pos = [st.index, 0.0] if st.is_stay else [st.index, st.miles]
        pts.append({"pos": pos, "name": st.name if st.is_stay else f"End of \"{st.name}\"", "xy": (x, y), "cell": cell,
                    "places": []})
    titles = {}
    for f in campaign.files.watabou:
        if f.kind == "dungeon" and f.marker is not None:
            try:
                from .watabou import load_dungeon
                titles[f.marker] = load_dungeon(f.path).title
            except Exception:
                pass
    for n in j.nearby(cfg.get("corridor_mi", 40)):
        if n.kind == "marker" and n.subtype == "party":
            continue  # the meeting point lives in its burg's story, not on the road
        name = titles.get(n.id) if n.kind == "marker" else None
        place = {"kind": n.kind, "id": n.id, "name": name or n.name or n.subtype, "offset_mi": n.offset_mi,
                 "subtype": n.subtype, "pos": [n.stage, n.along_mi]}
        if n.offset_mi <= cfg.get("strict_mi", 2.0):
            near = next((p for p in pts if p["pos"][0] == n.stage and abs(p["pos"][1] - n.along_mi) < 1.5), None)
            if near:
                near["places"].append(place)
            else:
                xy = (n.extra.get("x", 0), n.extra.get("y", 0))
                pts.append({"pos": [n.stage, n.along_mi], "name": place["name"].capitalize() if place["name"] == n.subtype
                            else place["name"], "xy": xy,
                            "cell": n.cell, "places": [place]})
        else:
            place["detour"] = True
            pts.append({"pos": [n.stage, n.along_mi], "name": None, "xy": None, "cell": None, "places": [place]})
    # camps on long empty stretches, about every three days of travel
    for st in j.moving():
        here = sorted(p["pos"][1] for p in pts if p["pos"][0] == st.index and p["name"] is not None)
        marks = [0.0] + here + [st.miles]
        per_day = st.speed * st.hours_per_day
        water = campaign.files.map.transport(st.transport).get("domain") == "water"
        spacing = 10 if water else 3
        for a, b in zip(marks, marks[1:]):
            n_camps = int((b - a) / (per_day * spacing))
            for k in range(1, n_camps + 1):
                mile = a + (b - a) * k / (n_camps + 1)
                miles = st.cumulative_miles(m.mi_per_px)
                idx = min(range(len(miles)), key=lambda i: abs(miles[i] - mile))
                x, y, cell = st.points[idx]
                biome = m.data["biomes"][m.cell("biome")[cell]]["name"].lower()
                label = f"At sea, day {round((mile - a) / per_day) + 1} of the crossing" if water else f"Camp in the {biome}"
                pts.append({"pos": [st.index, mile], "name": label, "xy": (x, y), "cell": cell,
                            "places": []})
    merged: list[dict] = []
    for p in sorted(pts, key=lambda p: (p["pos"][0], p["pos"][1])):
        if p["name"] is None:  # detour-only: attach to the nearest real waypoint before it
            if merged:
                merged[-1]["places"].append(p["places"][0])
            continue
        merged.append(p)
    return merged


def _terrain(m, cell: int) -> str:
    biome = m.data["biomes"][m.cell("biome")[cell]]["name"].lower()
    state = m.state(m.cell("state")[cell])
    prov = m.data["provinces"][m.cell("province")[cell]] if m.cell("province")[cell] else None
    culture = m.culture(m.cell("culture")[cell])["name"]
    river = next((r["name"] for r in m.live("rivers") if r["i"] == m.cell("river")[cell]), None) if m.cell("river")[cell] else None
    zones = [z["name"] for z in m.zones_of_cell(cell)]
    bits = [f"The road runs through {biome}", f"in {(prov or {}).get('name', '') + ', ' if prov else ''}"
            f"{state.get('fullName') or state['name']}", f"where {culture} folk live"]
    text = ", ".join(bits) + "."
    if river:
        text += f" The {river} runs near."
    if zones:
        text += " Hereabouts: " + ", ".join(zones) + "."
    return text


def build(campaign) -> World:
    files, m, j = campaign.files, campaign.files.map, campaign.journey
    w = World(files.name, "overworld")
    w.clock, w.seed = j.clock, f"{m.seed}:overworld"
    w.flags.update({"overworld": True, "title": j.name})
    pts = waypoints(campaign)
    forward, back = {}, {}
    for k, p in enumerate(pts):
        places = [pl for pl in p["places"] if not pl.get("detour")]
        near = [pl for pl in p["places"] if pl.get("detour")]
        desc = _terrain(m, p["cell"])
        if places:
            desc += " Here: " + ", ".join(f"{pl['name']} ({'town' if pl['kind'] == 'burg' else pl['subtype']})" for pl in places) + "."
        if near:
            desc += " Off the road: " + ", ".join(f"{pl['name']} ({pl['offset_mi']:.0f} mi)" for pl in near[:5]) + "."
        r = w.add_room(Room(f"wp{k}", p["name"], desc, area="the road", purpose="road", provenance="data"))
        r.props = {"pos": p["pos"], "places": p["places"], "xy": p["xy"]}
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        d = compass(b["xy"][0] - a["xy"][0], b["xy"][1] - a["xy"][1]) if a["xy"] and b["xy"] else "north"
        w.rooms[f"wp{k}"].exits[d] = Exit(f"wp{k + 1}", note=f"onward, toward {b['name']}")
        back_d = {"north": "south", "south": "north", "east": "west", "west": "east", "northeast": "southwest",
                  "southwest": "northeast", "northwest": "southeast", "southeast": "northwest"}[d]
        if back_d in w.rooms[f"wp{k + 1}"].exits:
            back_d = "back"
        w.rooms[f"wp{k + 1}"].exits[back_d] = Exit(f"wp{k}", note=f"back, toward {a['name']}")
        forward[f"wp{k}"], back[f"wp{k + 1}"] = d, back_d
    w.flags.update({"forward": forward, "back": back})
    here = min(range(len(pts)), key=lambda k: (abs(pts[k]["pos"][0] - campaign.pos[0]) * 1e6 +
                                               abs(pts[k]["pos"][1] - campaign.pos[1])))
    w.player = f"wp{here}"
    w.start_t = campaign.t
    w.lat = j.stages[pts[here]["pos"][0]].lat
    w.flags["anchor"] = {}
    return w


def move(game, src: str, dst: str) -> str:
    """Called by the game after a move on the overworld: time, food, water, story."""
    c, w = game.campaign, game.w
    a, b = w.rooms[src].props["pos"], w.rooms[dst].props["pos"]
    hours = c.segment_hours(a, b)
    out = [f"You travel for {hours / 24:.1f} days." if hours >= 24 else f"You travel for {hours:.0f} hours."]
    days = int(hours // 24)
    rations = next((t for t in w.carried() if "food" in t.flags and t.props.get("uses", 1) > 0), None)
    water = next((t for t in w.carried() if "drink" in t.flags), None)
    ate = drank = 0
    for d in range(days):
        if rations and rations.location:
            game._use_up(rations)
            ate += 1
            w.flags["last_meal"] = w.plan_t + (d + 1) * 24
        if water and water.props.get("uses", 0) > 0:
            water.props["uses"] -= 1
            drank += 1
            w.flags["last_drink"] = w.plan_t + (d + 1) * 24
    rivers = any(cr.kind == "river" and cr.after != "none" and
                 (a[0], a[1]) <= (cr.stage, cr.mile) <= (b[0], b[1]) for cr in c.crossings)
    town = any(pl["kind"] == "burg" for pl in w.rooms[dst].props["places"])
    if water and (rivers or town):
        water.props["uses"] = water.props.get("max_uses", 6)
        w.flags["last_drink"] = w.plan_t + hours
    if days:
        out.append(f"On the way you eat {ate} of {days} days' food and drink {drank} days' water."
                   + (" You refill your water on the way." if water and (rivers or town) else ""))
    msgs = game.tick(hours * 60) or ""
    forward = (b[0], b[1]) >= (a[0], a[1])
    c.t = w.plan_t
    if forward:
        c.pos = [b[0], b[1]]
        story = c.story.notify({"type": "pass", "pos": c.pos}) + c.story.notify({"type": "time", "t": c.t})
    else:
        story = ["You go back along the road; the time is lost."]
    if c.story.delay_change:
        w.minutes += c.story.delay_change * 60
        c.t = w.plan_t
        c.story.delay_change = 0.0
    return "\n".join(x for x in [" ".join(out), msgs] + story if x)


def enter_target(game, words: list[str]) -> dict | str:
    """Find the place named here (or a detour nearby) and say which scene it is."""
    room = game.w.rooms[game.w.player]
    places = room.props.get("places", [])
    cands = [p for p in places if not words or all(wd in p["name"].lower() or wd in p["subtype"] for wd in words)]
    if not cands:
        return "There's no such place here. " + ("Here: " + ", ".join(p["name"] for p in places) if places else "")
    p = cands[0]
    files = game.campaign.files
    if p["kind"] == "burg":
        return {"scene": f"town:{p['id']}", "detour_mi": p["offset_mi"] if p.get("detour") else 0, "place": p}
    has_dungeon = any(f.kind == "dungeon" and f.marker == p["id"] for f in files.watabou)
    mk = next(x for x in files.map.live("markers") if x["i"] == p["id"])
    if has_dungeon:
        return {"scene": f"dungeon:{p['id']}", "detour_mi": p["offset_mi"] if p.get("detour") else 0, "place": p}
    if "one-page-dungeon" in (mk.get("note") or ""):
        from . import links
        return (f"[Paused] The way into {p['name']} has not been generated. Open One Page Dungeon at "
                f"{links.dungeon_link(files.map, mk)}, export JSON, save it as "
                f"{files.map_path.parent.name}/dungeon-{p['id']}.json, and enter again.")
    return f"{mk.get('name', p['name'])}: {mk.get('note') or 'Nothing more to find here.'}"
