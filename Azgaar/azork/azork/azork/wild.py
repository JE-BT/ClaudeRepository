"""The overworld on the map's hex grid (5 miles a hex on Lania).

Every hex is a place, built when you reach it, described from its cell (biome phrases, height,
river, zones, state, culture), the roads that cross it, the journey's route and the towns and
sites in or near it. ONWARD and BACK follow the planned route one hex at a time; any compass
direction leaves it. Time per hex depends on how you travel (light or laden, by boat at sea),
the ground (roads and trails are quicker; the biome's movement cost in the map slows you off
them) and the dark. Water is drunk and food eaten when you CAMP; FORAGE, HUNT and FILL from
rivers keep you going. Encounters come from the zones you cross, encounter markers, the road,
and how far behind the plan you are.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .cells import CellGeo
from .clock import daylight
from .engine.model import Exit, Room, World
from .hexgrid import NEIGH, HexGrid
from .people import TEXT

DIRS6 = list(NEIGH)


class Wild:
    def __init__(self, campaign):
        self.c = campaign
        files = campaign.files
        self.m = m = files.map
        self.grid = HexGrid.from_map(m)
        self.geo = CellGeo(files.cells_path, m)
        self.buckets: dict = {}
        for i, (x, y) in self.geo.centroid.items():
            self.buckets.setdefault((int(x // 10), int(y // 10)), []).append(i)
        land = [b.get("cost", 50) for b in m.data["biomes"][1:] if b.get("cost")]
        self.base_cost = min(land) if land else 50
        # the planned route, hex by hex, with its position on the journey
        self.route: list[tuple[str, int, float]] = []
        for st in campaign.journey.moving():
            miles = st.cumulative_miles(m.mi_per_px)
            for k, p in enumerate(st.points):
                h = self.grid.key(self.grid.at(p[0], p[1]))
                if not self.route or self.route[-1][0] != h:
                    if k and self.route:  # fill gaps between distant points
                        prev = self.grid.parse(self.route[-1][0])
                        for g in self.grid.line([self.grid.centre(prev), p])[1:-1]:
                            gk = self.grid.key(g)
                            if gk != self.route[-1][0]:
                                self.route.append((gk, st.index, miles[k]))
                    self.route.append((h, st.index, miles[k]))
        self.route_at = {}
        for n, (h, s, mi) in enumerate(self.route):
            self.route_at.setdefault(h, n)
        self.avoid = {seg["i"]: seg.get("avoidRoads", False) for seg in m.data["journeys"][0]["segments"]}
        self.roads: dict[str, tuple[str, str]] = {}
        for r in m.live("routes"):
            for g in self.grid.line(r["points"]):
                k = self.grid.key(g)
                if k not in self.roads or r["group"] == "roads":
                    self.roads[k] = (r.get("name") or f"the {r['group'][:-1]}", r["group"])
        self.burgs = {self.grid.key(self.grid.at(b["x"], b["y"])): b for b in m.live_burgs()}
        self.markers: dict[str, list] = {}
        for mk in m.live("markers"):
            if mk["type"] != "party":
                self.markers.setdefault(self.grid.key(self.grid.at(mk["x"], mk["y"])), []).append(mk)

    # ----------------------------------------------------------------- data
    def cell(self, key: str) -> int:
        x, y = self.grid.centre(self.grid.parse(key))
        bx, by = int(x // 10), int(y // 10)
        cands = [i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for i in self.buckets.get((bx + dx, by + dy), [])]
        cands = cands or list(self.geo.centroid)
        return min(cands, key=lambda i: (self.geo.centroid[i][0] - x) ** 2 + (self.geo.centroid[i][1] - y) ** 2)

    def water(self, key: str) -> bool:
        return self.geo.is_water(self.cell(key))

    def factor(self, key: str) -> float:
        """Time per hex against the plan's pace: roads are quicker than the plan, the planned route keeps
        its pace (the plan already allowed for its ground), the wild off the route is slower by the biome's cost."""
        road = self.roads.get(key)
        if road and road[1] == "roads":
            return 0.75
        if road and road[1] == "trails":
            return 0.9
        if key in self.route_at:
            return 1.0
        cost = self.m.data["biomes"][self.m.cell("biome")[self.cell(key)]].get("cost", self.base_cost)
        return min(4.0, max(1.3, cost / self.base_cost))

    def describe(self, key: str, t: float, lat: float, doy) -> str:
        m, cell = self.m, self.cell(key)
        rng = random.Random(f"{m.seed}:{key}")
        biome = m.data["biomes"][m.cell("biome")[cell]]["name"]
        bank = TEXT["biomes"].get(biome, {"phrases": [f"{biome}."]})
        height = self.geo.props[cell].get("height", 0)
        land = next(lbl for lim, lbl in reversed(TEXT["height"]) if height >= lim) if height >= 0 else "water"
        state = m.state(m.cell("state")[cell])
        culture = m.culture(m.cell("culture")[cell])["name"]
        parts = [rng.choice(bank["phrases"])]
        if land not in ("water", "low ground"):
            parts.append(f"This is {land}.")
        river_id = m.cell("river")[cell]
        if river_id:
            river = next((r["name"] for r in m.live("rivers") if r["i"] == river_id), "a river")
            parts.append(f"The {river} runs through here.")
        road = self.roads.get(key)
        if road:
            parts.append(f"{road[0][0].upper() + road[0][1:]} crosses this hex ({road[1][:-1]}).")
        if key in self.route_at:
            n = self.route_at[key]
            nxt = self.route[n + 1][0] if n + 1 < len(self.route) else None
            st = self.route[n][1]
            way = self.grid.direction(self.grid.parse(key), self.grid.parse(nxt)) if nxt else None
            plan = " The plan keeps off the roads here, out of sight of the posts." if self.avoid.get(st) else ""
            parts.append(f"Your planned route runs {way} from here.{plan}" if way else "Your route ends here.")
        zones = [z["name"] for z in m.zones_of_cell(cell)]
        if zones:
            parts.append("This is the country of the " + ", ".join(zones) + ".")
        parts.append(f"{state.get('fullName') or state['name']}; {culture} country.")
        h = (t + (self.c.journey.clock.origin if self.c.journey.clock else 6)) % 24
        dawn, dusk = daylight(lat, doy)
        phase = "night" if h < dawn - 0.5 or h > dusk + 0.5 else "dawn" if h < dawn + 1 else "dusk" if h > dusk - 1 else "day"
        if TEXT["time"][phase]:
            parts.append(TEXT["time"][phase])
        return " ".join(parts)

    def nearby(self, key: str, radius: int = 2) -> list[str]:
        h = self.grid.parse(key)
        cx, cy = self.grid.centre(h)
        out = []
        for hk, b in self.burgs.items():
            bx, by = self.grid.centre(self.grid.parse(hk))
            d = math.dist((cx, cy), (bx, by)) / self.grid.w
            if 0.5 < d <= radius + 0.5:
                way = self.grid.direction(h, self.grid.parse(hk))
                road = " by road" if hk in self.roads and key in self.roads else ""
                out.append(f"{b['name']} lies {round(d)} hex{'es' if round(d) > 1 else ''} {way}{road}")
        return out


def wild_of(campaign) -> Wild:
    if getattr(campaign, "_wild", None) is None:
        campaign._wild = Wild(campaign)
    return campaign._wild


def build(campaign) -> World:
    files, j = campaign.files, campaign.journey
    wd = wild_of(campaign)
    w = World(files.name, "overworld")
    w.clock, w.seed = j.clock, f"{files.map.seed}:overworld"
    w.flags.update({"overworld": True, "hexes": True, "title": j.name})
    w.files = files
    key = getattr(campaign, "hex", None)
    if not key:
        n = min(range(len(wd.route)), key=lambda i: (abs(wd.route[i][1] - campaign.pos[0]) * 1e6 +
                                                    abs(wd.route[i][2] - campaign.pos[1])))
        key = wd.route[n][0]
    w.start_t = campaign.t
    w.lat = j.stages[campaign.pos[0]].lat
    ensure(w, campaign, key)
    w.player = f"h:{key}"
    w.flags["anchor"] = {}
    return w


def ensure(w: World, campaign, key: str) -> Room:
    rid = f"h:{key}"
    if rid in w.rooms:
        return w.rooms[rid]
    wd = wild_of(campaign)
    h = wd.grid.parse(key)
    doy = campaign.journey.clock.doy(int((w.plan_t + campaign.journey.clock.origin) // 24))
    desc = wd.describe(key, w.plan_t, w.lat, doy)
    here = []
    if key in wd.burgs:
        here.append(f"{wd.burgs[key]['name']} is here (ENTER {wd.burgs[key]['name'].upper()}).")
    for mk in wd.markers.get(key, []):
        here.append(f"There is something here: {mk.get('name') or mk['type']} (EXAMINE it, or ENTER it if it can be entered).")
    near = wd.nearby(key)
    if near:
        here.append("Nearby: " + "; ".join(near) + ".")
    road = wd.roads.get(key)
    name = (wd.burgs[key]["name"] + " (outskirts)" if key in wd.burgs else
            f"On {road[0]}" if road and road[1] != "searoutes" else
            "At sea" if wd.water(key) else f"{campaign.files.map.data['biomes'][campaign.files.map.cell('biome')[wd.cell(key)]]['name']}")
    room = w.add_room(Room(rid, name, " ".join([desc] + here), area="the road", purpose="road", provenance="data"))
    room.props = {"hex": key, "places": []}
    for d in DIRS6:
        nk = wd.grid.key(wd.grid.neighbour(h, d))
        note = "route" if nk in wd.route_at else (wd.roads[nk][0] if nk in wd.roads else "")
        room.exits[d] = Exit(f"h:{nk}", note=note)
    cell = wd.cell(key)
    if campaign.files.map.data["biomes"][campaign.files.map.cell("biome")[cell]]["name"] == "Wetland" and \
            not campaign.files.map.cell("river")[cell]:
        w.spawn({"name": "black water", "nouns": ["water", "pool", "channel"], "flags": ["scenery", "water_source"],
                 "description": "Brackish, but it will keep you alive."}, rid, f"{rid}:water")
    if campaign.files.map.cell("river")[cell]:
        w.spawn({"name": "river", "nouns": ["river", "water", "stream"], "flags": ["scenery", "water_source"],
                 "description": "Brown water, moving steadily."}, rid, f"{rid}:river")
    for mk in wd.markers.get(key, []):
        w.spawn({"name": mk.get("name") or mk["type"], "nouns": [(mk.get("name") or mk["type"]).lower().split()[-1], mk["type"]],
                 "flags": ["scenery"], "description": mk.get("note") or "Old, and quiet.", "provenance": "data"},
                rid, f"{rid}:marker{mk['i']}")
    return room


def passable(game, key: str) -> str | None:
    wd = wild_of(game.campaign)
    if wd.water(key) and key not in wd.route_at and wd.roads.get(key, ("", ""))[1] != "searoutes":
        return "Open water. You'd need a boat, and someone to take you."
    return None


def hours_for(game, src: str, dst: str) -> float:
    c, w = game.campaign, game.w
    wd = wild_of(c)
    key = dst.split(":", 1)[1]
    if wd.water(key):
        st = next((s for s in c.journey.moving() if c.files.map.transport(s.transport)["domain"] == "water"
                   and s.index >= c.pos[0]), None)
        speed = st.speed if st else 4
        return wd.grid.miles / speed
    mode = "On foot (laden)" if w.load_status() != "light" else "On foot (light)"
    speed = c.files.map.transport(mode)["speed"]
    hours = wd.grid.miles / speed * wd.factor(key)
    hour = (w.plan_t + c.journey.clock.origin) % 24
    dawn, dusk = daylight(w.lat, 80)
    if hour < dawn or hour > dusk:
        hours *= 1.5
    return hours


def move(game, src: str, dst: str) -> str:
    c, w = game.campaign, game.w
    wd = wild_of(c)
    key = dst.split(":", 1)[1]
    hours = hours_for(game, src, dst)
    out = [f"({hours:.1f} hours{' by road' if key in wd.roads else ''})"]
    tick = game.tick(hours * 60)
    w.flags["walked"] = w.flags.get("walked", 0) + hours
    c.t = w.plan_t
    c.hex = key
    story = []
    if key in wd.route_at:
        n = wd.route_at[key]
        _, st, mile = wd.route[n]
        if (st, mile) > (c.pos[0], c.pos[1]):
            c.pos = [st, mile]
            story = c.story.notify({"type": "pass", "pos": c.pos})
    story += c.story.notify({"type": "time", "t": c.t})
    if c.story.delay_change:
        w.minutes += c.story.delay_change * 60
        c.t = w.plan_t
        c.story.delay_change = 0.0
    out += [x for x in (tick,) if x] + story
    enc = encounter(game, key)
    if enc:
        out.append(enc)
    hour = (w.plan_t + c.journey.clock.origin) % 24
    dawn, dusk = daylight(w.lat, 80)
    tired = w.flags["walked"] > c.files.map.transport("On foot (light)")["hoursPerDay"]
    if tired:
        out.append("You have walked a full day. You should CAMP.")
    elif hour > dusk - 1 or hour < dawn:
        out.append("The light is going. You could CAMP here, or press on in the dark (slower).")
    return "\n".join(out)


def onward(game, back: bool = False) -> str | None:
    """The neighbouring hex toward the next (or previous) hex of the planned route."""
    wd = wild_of(game.campaign)
    key = game.w.rooms[game.w.player].props["hex"]
    if key in wd.route_at:
        n = wd.route_at[key] + (-1 if back else 1)
    else:
        here = wd.grid.centre(wd.grid.parse(key))
        n = min(range(len(wd.route)), key=lambda i: math.dist(wd.grid.centre(wd.grid.parse(wd.route[i][0])), here))
    if n < 0 or n >= len(wd.route):
        return None
    target = wd.grid.parse(wd.route[n][0])
    return wd.grid.direction(wd.grid.parse(key), target) if target != wd.grid.parse(key) else None


def route_text(game) -> str:
    c, wd = game.campaign, wild_of(game.campaign)
    key = game.w.rooms[game.w.player].props["hex"]
    lines = []
    if key in wd.route_at:
        n = wd.route_at[key]
        ahead = wd.route[n + 1:n + 7]
        dirs = [wd.grid.direction(wd.grid.parse(a[0]), wd.grid.parse(b[0])) for a, b in zip([wd.route[n]] + ahead, ahead)]
        st = c.journey.stages[wd.route[n][1]]
        lines.append(f"The route ({st.name}) runs {', '.join(dict.fromkeys(dirs)) or 'on'} over the next hexes.")
        if wd.avoid.get(st.index):
            lines.append("This stage keeps off the roads on purpose: slower going, but no posts and no questions. "
                         "A road would be quicker, and seen.")
    else:
        d = onward(game)
        lines.append(f"You are off the route; it lies {d} of here." if d else "You are off the route.")
    road = wd.roads.get(key)
    if road:
        cost = c.files.map.data["biomes"][c.files.map.cell("biome")[wd.cell(key)]].get("cost", wd.base_cost)
        wild_f = min(4.0, max(1.3, cost / wd.base_cost))
        lines.append(f"{road[0]} ({road[1][:-1]}) runs through here: {wd.factor(key):.2f} of the plan's time a hex on it, "
                     f"against {wild_f:.1f} across the wild off the route. Roads are watched.")
    return " ".join(lines)


def camp(game, sleep: bool = True) -> str:
    w = game.w
    good = any("bedroll" in t.nouns for t in w.carried())
    out = []
    food = next((t for t in w.carried() if "food" in t.flags and t.location), None)
    water = next((t for t in w.carried() if "drink" in t.flags and t.props.get("uses", 0) > 0), None)
    hungry = w.plan_t - w.flags.get("last_meal", w.plan_t) >= 6
    thirsty = w.plan_t - w.flags.get("last_drink", w.plan_t) >= 4
    if not hungry:
        food = None
        out.append("You are not hungry yet.")
    if not thirsty:
        water = None
        out.append("You are not thirsty yet.")
    if food:
        game._use_up(food)
        w.flags["last_meal"] = w.plan_t
        out.append("You eat.")
    elif hungry:
        out.append("You have nothing to eat.")
    if water:
        water.props["uses"] -= 1
        w.flags["last_drink"] = w.plan_t
        out.append("You drink.")
    elif thirsty:
        out.append("You have nothing to drink. (FILL a waterskin where a river crosses your way.)")
    hour = (w.plan_t + game.campaign.journey.clock.origin) % 24
    dawn, dusk = daylight(w.lat, 80)
    if dawn <= hour <= dusk - 2:
        out.append(game.tick(60) or "")
        out.append("It is broad day; you rest for an hour and go on.")
    elif good:
        until = (dawn - hour) % 24 or 24
        out.append(game.tick(until * 60) or "")
        out.append("You sleep in your bedroll until dawn.")
    else:
        out.append(game.tick(3 * 60) or "")
        out.append("With nothing to sleep in, you doze fitfully for a few hours.")
    w.flags["walked"] = 0
    game.campaign.t = w.plan_t
    return " ".join(x for x in out if x) + f" It is {w.time_label()}."


def forage(game, hunt: bool = False) -> str:
    w, c = game.w, game.campaign
    wd = wild_of(c)
    key = w.rooms[w.player].props["hex"]
    biome = c.files.map.data["biomes"][c.files.map.cell("biome")[wd.cell(key)]]["name"]
    odds = TEXT["biomes"].get(biome, {}).get("hunt" if hunt else "food", 0.3)
    if hunt and not any("weapon" in t.flags or "knife" in t.nouns for t in w.carried()):
        return "You have nothing to hunt with."
    hours = 3 if hunt else 2
    game.extra_minutes += hours * 60
    rng = random.Random(f"{w.seed}:{key}:{int(w.plan_t // 24)}:{hunt}")
    if rng.random() < odds:
        spec = ({"name": "brace of game birds", "nouns": ["birds", "game", "brace"], "weight": 1.0, "uses": 2,
                 "flags": ["takeable", "food"]} if hunt else
                {"name": "handful of wild food", "nouns": ["food", "berries", "roots"], "weight": 0.3, "uses": 1,
                 "flags": ["takeable", "food"]})
        item = w.spawn(spec, "player")
        item.props["_spawned_in_play"] = True
        return f"After {hours} hours you come back with {item.article_name}."
    return f"You spend {hours} hours {'hunting' if hunt else 'foraging'} and find nothing worth eating."


def encounter(game, key: str) -> str | None:
    c, w = game.campaign, game.w
    wd = wild_of(c)
    rng = random.Random(f"{w.seed}:{key}:{int(w.plan_t)}")
    cell = wd.cell(key)
    late = max(0.0, c.delay())
    tables = []
    for z in c.files.map.zones_of_cell(cell):
        tables.append(z["type"])
    if any(mk["type"] == "encounters" for mk in wd.markers.get(key, [])):
        tables.append("marker")
    chance = 0.05 + 0.08 * len(tables) + min(0.1, late / 240)
    if rng.random() > chance:
        return None
    tables.append("road" if key in wd.roads else "wild")
    pool = [e for t in tables for e in TEXT["encounters"].get(t, [])]
    if not pool:
        return None
    e = rng.choice(pool)
    out = [e["text"]]
    if e.get("delay"):
        lost = rng.uniform(*e["delay"])
        game.tick(lost * 60)
        c.t = w.plan_t
        out.append(f"(You lose {lost:.1f} hours.)")
    if e.get("water"):
        for t in w.carried():
            if "drink" in t.flags:
                t.props["uses"] = t.props.get("max_uses", 6)
        w.flags["last_drink"] = w.plan_t
    if e.get("food"):
        item = w.spawn({"name": "loaf of pilgrim bread", "nouns": ["bread", "loaf"], "weight": 0.5, "uses": 1,
                        "flags": ["takeable", "food"]}, "player")
        item.props["_spawned_in_play"] = True
    if e.get("carrier"):
        from .transport import carrier_spec
        spec = carrier_spec(c, e["carrier"], rng, game.w)
        if spec:
            w.spawn(spec, w.player, f"carrier:{key}")
    return " ".join(out)
