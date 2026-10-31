"""Card data built from the map and the network (no drawing here).

Commissions
  One per market-to-market deal, filed in the seller state's deck (export) and again in the buyer
  state's deck (import); a deal inside one state is filed once (domestic). Decks smaller than
  `min_deck` are padded with numbered copies. Players may never hold two active commissions with
  the same deal code, so a copy is only a second chance to draw that deal.

Income
  income = round(k * stops * tier), clamped to [lo, hi]
  stops: stops on the fewest-stops land/sea route between the two market towns (both ends counted);
         with no land/sea route, the route through air sites; with none at all, the straight-line
         distance divided by the median link length, plus one
  tier:  the deal's value (units x price) by quartile among all market deals:
         small 1.0, standard 1.25, large 1.5, major 2.0
  split: most / second / third stations = about 55 / 30 / 15 percent; ties go to the declaring player
"""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import events as ev
from .network import Network

TIERS = [("Small contract", 1.0), ("Standard contract", 1.25), ("Large contract", 1.5), ("Major contract", 2.0)]


@dataclass
class Commission:
    deal: int
    code: str
    state: int  # deck owner
    role: str  # export | import | domestic
    seller_state: int
    buyer_state: int
    good: dict
    origin: str  # market town names
    dest: str
    stops: int
    stops_source: str  # land-sea | air | distance
    modes: list
    miles: float
    heading: str
    value: float
    tier: int
    income: int
    split: tuple
    copy: int = 1
    index: int = 0
    of: int = 0


def heading(dx: float, dy: float) -> str:
    ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int((ang + 22.5) // 45) % 8]


def split_income(income: int) -> tuple[int, int, int]:
    third = max(1, round(income * 0.15)) if income >= 3 else 0
    second = max(1, round(income * 0.30)) if income >= 2 else 0
    return income - second - third, second, third


def build_commissions(net: Network, k: float = 0.75, lo: int = 2, hi: int = 20, min_deck: int = 6,
                      min_value: float = 0.0, max_per_state: int | None = None,
                      neutral_deck: bool = False) -> tuple[dict[int, list[Commission]], dict]:
    m = net.m
    goods = {g["i"]: g for g in m.live("goods")}
    states = {s["i"]: s for s in m.live("states")}
    mi = m.mi_per_px
    deals = [d for d in m.data["deals"] if d.get("sellerType") == "market" and d.get("buyerType") == "market"
             and d.get("seller") in net.markets and d.get("buyer") in net.markets]
    values = sorted(d["units"] * d["price"] for d in deals)
    q = [values[int(len(values) * f)] for f in (0.25, 0.5, 0.75)] if values else [0, 0, 0]
    hop_len = statistics.median([ln.length for ln in net.links.values()]) if net.links else 50.0
    decks: dict[int, list[Commission]] = defaultdict(list)
    skipped = 0
    for d in deals:
        value = d["units"] * d["price"]
        if value < min_value:
            skipped += 1
            continue
        a = net.markets[d["seller"]]["centerBurgId"]
        b = net.markets[d["buyer"]]["centerBurgId"]
        sa, sb = net.stops[a], net.stops[b]
        p = net.path(a, b)
        source = "land-sea"
        if p is None:
            p = net.path(a, b, use_air=True)
            source = "air"
        if p is not None:
            stops = len(p[0])
            modes = sorted({ln.mode if ln else "air" for ln in p[1]})
            miles = sum((ln.length if ln else math.hypot(net.stops[x].x - net.stops[y].x, net.stops[x].y - net.stops[y].y))
                        for ln, x, y in zip(p[1], p[0], p[0][1:])) * mi
        else:
            straight = math.hypot(sa.x - sb.x, sa.y - sb.y)
            stops = int(straight / hop_len) + 1
            modes, miles, source = [], straight * mi, "distance"
        tier = sum(value >= t for t in q)
        income = max(lo, min(hi, round(k * stops * TIERS[tier][1])))
        st_s, st_b = sa.state, sb.state
        files = [(st_s, "export"), (st_b, "import")] if st_s != st_b else [(st_s, "domestic")]
        for owner, role in files:
            if owner == 0 and not neutral_deck:
                continue
            decks[owner].append(Commission(
                d["i"], f"D{d['i']}", owner, role, st_s, st_b, goods.get(d["good"], {"name": f"good {d['good']}"}),
                sa.name, sb.name, stops, source, modes, miles, heading(sb.x - sa.x, sb.y - sa.y), value, tier,
                income, split_income(income)))
    trimmed = {}
    for owner, cards in decks.items():
        cards.sort(key=lambda c: (-c.value, c.deal))
        if max_per_state and len(cards) > max_per_state:
            trimmed[states[owner]["name"]] = len(cards) - max_per_state
            del cards[max_per_state:]
        cards.sort(key=lambda c: (-c.income, c.deal))
        base = list(cards)
        copy = 2
        while len(cards) < min_deck and base:
            for c in base:
                if len(cards) >= min_deck:
                    break
                cards.append(Commission(**{**c.__dict__, "copy": copy}))
            copy += 1
        for i, c in enumerate(cards, 1):
            c.index, c.of = i, len(cards)
    stats = {"deals": len(deals), "skipped_below_min_value": skipped, "trimmed_by_max_per_state": trimmed, "value_quartiles": [round(x, 2) for x in q],
             "decks": {states[s]["name"]: len(c) for s, c in sorted(decks.items())},
             "income": dict(sorted(Counter(c.income for cs in decks.values() for c in cs if c.copy == 1).items())),
             "no_states": [s["name"] for i, s in states.items() if i and i not in decks],
             "neutral_deck": neutral_deck}
    return dict(decks), stats


# ---------------------------------------------------------------------------------- houses
@dataclass
class House:
    colour: str
    market: int
    town: str
    state: int
    state_name: str
    state_full: str
    goods: list
    charter: tuple  # (title, text)
    favour: str
    notes: list = field(default_factory=list)


def build_houses(net: Network, colours: list[str]) -> list[House]:
    """One merchant house per player colour, rooted in a market town of a different state."""
    m = net.m
    goods = {g["i"]: g for g in m.live("goods")}
    states = {s["i"]: s for s in m.live("states")}
    exports: dict[int, Counter] = defaultdict(Counter)
    for d in m.data["deals"]:
        if d.get("sellerType") == "market":
            exports[d["seller"]][d["good"]] += d["units"] * d["price"]
    ranked = sorted(net.markets, key=lambda i: -sum(exports[i].values()))
    ranked = [i for i in ranked if net.markets[i]["centerBurgId"] in net.stops
              and net.stops[net.markets[i]["centerBurgId"]].state]
    picked, used_states = [], set()
    for i in ranked:  # the richest exporting market of each state first
        st = net.stops[net.markets[i]["centerBurgId"]].state
        if st not in used_states and len(picked) < len(colours):
            picked.append(i)
            used_states.add(st)
    for i in ranked:  # then, if there are more players than states, the next richest markets
        if len(picked) >= len(colours):
            break
        if i not in picked:
            picked.append(i)
    houses, charters = [], Counter()
    for colour, i in zip(colours, picked):
        stop = net.stops[net.markets[i]["centerBurgId"]]
        st = states.get(stop.state, {"name": "the free towns", "fullName": "the free towns"})
        top = [goods[g]["name"] for g, _ in exports[i].most_common(2) if g in goods] or ["local goods"]
        has_sea = any(ln.mode == "sea" for _, ln in net.nbr[stop.burg])
        options = []
        if stop.air:
            options.append(("Sky charter", "Air infrastructure moves your expense marker 4, not 5."))
        if has_sea:
            options.append(("Shipwrights' charter", "Sea infrastructure moves your expense marker 1, not 2."))
        options.append(("Carters' charter", f"Land infrastructure in {st['name']} moves your expense marker 0, not 1."))
        charter = min(options, key=lambda o: charters[o[0]])
        charters[charter[0]] += 1
        houses.append(House(colour, i, stop.name, stop.state, st["name"], st.get("fullName") or st["name"], top, charter,
                            f"When you draw commissions from {st['name']}, draw one extra card."))
    return houses


# ---------------------------------------------------------------------------------- events
@dataclass
class EventText:
    colour: str
    polarity: int
    title: str
    kind: str  # marker type label or "Generic"
    text: str
    source: str  # marker:<i> | generic


@dataclass
class EventCard:
    number: int
    land: EventText
    sea: EventText
    air: EventText


def build_events(net: Network, size: int | None = None, seed: int = 1) -> tuple[list[EventCard], dict]:
    rng = random.Random(seed)
    pools: dict[str, list[EventText]] = {"land": [], "sea": [], "air": []}
    spares: dict[str, list[EventText]] = {"land": [], "sea": [], "air": []}
    counts = {c: Counter() for c in pools}
    for star in net.stars:
        mk = star.marker
        mtype = mk.get("type", "")
        if mtype in ev.SKIP_TYPES:
            continue
        near = min(net.stops.values(), key=lambda s: (s.x - mk["x"]) ** 2 + (s.y - mk["y"]) ** 2).name
        title, name = ev.names_for(mk, near)
        for colour, variants in ev.texts_for(mtype).items():
            target = ev.POSITIVE_SHARE[colour]
            c = counts[colour]
            share = c[+1] / max(1, c[+1] + c[-1])
            pol = +1 if (share < target or (share == target and rng.random() < target)) else -1
            if pol not in variants:
                pol = -pol
            c[pol] += 1
            pools[colour].append(EventText(colour, pol, title, ev.label_of(mtype),
                                           ev.render(variants[pol], name, near), f"marker:{mk['i']}"))
            if -pol in variants:
                spares[colour].append(EventText(colour, -pol, title, ev.label_of(mtype),
                                                ev.render(variants[-pol], name, near), f"marker:{mk['i']}"))
    marker_sizes = {c: len(p) for c, p in pools.items()}
    n = size or max(30, max(marker_sizes.values()))  # default: every marker text is used
    set_aside = {}
    generic_used = Counter()
    for colour in pools:
        target = ev.POSITIVE_SHARE[colour]
        pool = pools[colour]
        rng.shuffle(pool)
        if len(pool) > n:  # keep the best-balanced subset
            pos = [e for e in pool if e.polarity > 0]
            neg = [e for e in pool if e.polarity < 0]
            want = round(n * target)
            keep = pos[:want] + neg[:n - want]
            keep += [e for e in pool if e not in keep][: n - len(keep)]
            set_aside[colour] = len(pool) - len(keep)
            pool[:] = keep
        spare = spares[colour]
        rng.shuffle(spare)
        generic = list(ev.GENERIC[colour])
        rng.shuffle(generic)
        g = 0
        while len(pool) < n:
            share = sum(e.polarity > 0 for e in pool) / max(1, len(pool))
            want = +1 if share < target else -1
            pick = next((e for e in spare if e.polarity == want), None)
            if pick is not None:
                spare.remove(pick)
                pool.append(pick)
                continue
            cands = sorted([x for x in generic if x[0] == want] or generic, key=lambda x: generic_used[x[1]])
            pol, title, text = cands[0]
            generic_used[title] += 1
            pool.append(EventText(colour, pol, title, "Anywhere", text, "generic"))
            g += 1
        rng.shuffle(pool)
    cards = [EventCard(i + 1, pools["land"][i], pools["sea"][i], pools["air"][i]) for i in range(n)]
    stats = {"cards": n, "marker_texts": marker_sizes, "set_aside": set_aside,
             "positive_share": {c: round(sum(e.polarity > 0 for e in pools[c]) / n, 2) for c in pools},
             "generic_uses": dict(generic_used)}
    return cards, stats


# ---------------------------------------------------------------------------------- infrastructure
COSTS = {"land": 1, "sea": 2, "air": 5}


def infrastructure_counts(land: int = 50, wild_share: float = 0.12) -> dict[str, int]:
    """Scarcity proportional to cost: count = land / cost; wilds as a share of the deck."""
    counts = {k: max(1, round(land / c)) for k, c in COSTS.items()}
    counts["wild"] = max(1, round(sum(counts.values()) * wild_share))
    return counts
