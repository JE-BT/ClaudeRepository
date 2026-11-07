"""Card data built from the map and the network (no drawing here).

Commissions
  One card per market-to-market deal, filed in the deck of its trade (goods.py): Provisions,
  Luxuries, Metals & arms, Building, Livestock, Slaves. Every deal appears once, so active
  commissions are unique by construction. Deals with a market in unclaimed land are kept and
  show "Free lands" as that side's state.

Income
  income = round(k * stops * tier), clamped to [lo, hi]
  stops: stops on the fewest-stops land/sea route between the two market towns (both ends counted);
         with no land/sea route, the route through air sites; with none at all, the straight-line
         distance divided by the median link length, plus one
  tier:  the deal's value (units x price) by quartile among all market deals:
         small 1.0, standard 1.25, large 1.5, major 2.0
  split: most / second / third stations = about 55 / 30 / 15 percent; ties go to the controller,
         neutral stations always lose ties

Houses
  One per player colour, rooted in the richest exporting market of a different state. A house has
  two home trades (cheaper to open), an infrastructure charter, and the patronage of one decree
  family (its petitions to decrees of that family cost one star less). Patronages are dealt so that
  no two houses share one, matching each house to the families its home state issues most.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .goods import TRADES, trade_of
from .network import Network

TIERS = [("Small contract", 1.0), ("Standard contract", 1.25), ("Large contract", 1.5), ("Major contract", 2.0)]


@dataclass
class Route:
    """The reference route of a deal: the one its income is computed from."""
    stops: list  # burg ids, origin first
    links: list  # (a, b, mode) keys; None for an air hop
    source: str  # land-sea | air | distance


@dataclass
class Commission:
    deal: int
    code: str
    trade: str
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
    index: int = 0
    of: int = 0


def heading(dx: float, dy: float) -> str:
    ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int((ang + 22.5) // 45) % 8]


def split_income(income: int) -> tuple[int, int, int]:
    third = round(income * 0.15)
    second = round(income * 0.30)
    return income - second - third, second, third


def market_deals(net: Network) -> list[dict]:
    return [d for d in net.m.data["deals"] if d.get("sellerType") == "market" and d.get("buyerType") == "market"
            and d.get("seller") in net.markets and d.get("buyer") in net.markets]


def build_routes(net: Network) -> dict[int, Route]:
    routes = {}
    for d in market_deals(net):
        a = net.markets[d["seller"]]["centerBurgId"]
        b = net.markets[d["buyer"]]["centerBurgId"]
        p, source = net.path(a, b), "land-sea"
        if p is None:
            p, source = net.path(a, b, use_air=True), "air"
        if p is None:
            routes[d["i"]] = Route([a, b], [], "distance")
        else:
            routes[d["i"]] = Route(p[0], [(ln.a, ln.b, ln.mode) if ln else None for ln in p[1]], source)
    return routes


def build_commissions(net: Network, routes: dict[int, Route], k: float = 0.75, lo: int = 2, hi: int = 20,
                      min_value: float = 0.0, max_per_trade: int | None = None,
                      slaves: bool = True) -> tuple[dict[str, list[Commission]], dict]:
    m = net.m
    goods = {g["i"]: g for g in m.live("goods")}
    mi = m.mi_per_px
    deals = market_deals(net)
    values = sorted(d["units"] * d["price"] for d in deals)
    q = [values[int(len(values) * f)] for f in (0.25, 0.5, 0.75)] if values else [0, 0, 0]
    hop_len = statistics.median([ln.length for ln in net.links.values()]) if net.links else 50.0
    decks: dict[str, list[Commission]] = defaultdict(list)
    skipped = 0
    for d in deals:
        value = d["units"] * d["price"]
        if value < min_value:
            skipped += 1
            continue
        good = goods.get(d["good"], {"name": f"good {d['good']}", "tags": []})
        if not slaves and trade_of(good) == "Slaves":
            continue
        r = routes[d["i"]]
        a, b = r.stops[0], r.stops[-1]
        sa, sb = net.stops[a], net.stops[b]
        if r.source == "distance":
            straight = math.hypot(sa.x - sb.x, sa.y - sb.y)
            stops, modes, miles = int(straight / hop_len) + 1, [], straight * mi
        else:
            stops = len(r.stops)
            modes = sorted({key[2] if key else "air" for key in r.links})
            miles = 0.0
            for key, x, y in zip(r.links, r.stops, r.stops[1:]):
                miles += net.links[key].length if key else math.hypot(net.stops[x].x - net.stops[y].x,
                                                                       net.stops[x].y - net.stops[y].y)
            miles *= mi
        tier = sum(value >= t for t in q)
        income = max(lo, min(hi, round(k * stops * TIERS[tier][1])))
        trade = trade_of(good)
        decks[trade].append(Commission(d["i"], f"D{d['i']}", trade, sa.state, sb.state, good, sa.name, sb.name, stops,
                                       r.source, modes, miles, heading(sb.x - sa.x, sb.y - sa.y), value, tier, income,
                                       split_income(income)))
    trimmed = {}
    for trade, cards in decks.items():
        cards.sort(key=lambda c: (-c.value, c.deal))
        if max_per_trade and len(cards) > max_per_trade:
            trimmed[trade] = len(cards) - max_per_trade
            del cards[max_per_trade:]
        cards.sort(key=lambda c: (-c.income, c.deal))
        for i, c in enumerate(cards, 1):
            c.index, c.of = i, len(cards)
    ordered = {t: decks[t] for t in TRADES if t in decks}
    stats = {"deals": len(deals), "skipped_below_min_value": skipped, "trimmed_by_max_per_trade": trimmed,
             "value_quartiles": [round(x, 2) for x in q], "decks": {t: len(c) for t, c in ordered.items()},
             "income": dict(sorted(Counter(c.income for cs in ordered.values() for c in cs).items())),
             "free_lands": sum(1 for cs in ordered.values() for c in cs if not c.seller_state or not c.buyer_state)}
    return ordered, stats


# ---------------------------------------------------------------------------------- houses
@dataclass
class House:
    colour: str
    market: int
    town: str
    state: int
    state_name: str
    state_full: str
    home_trades: list
    charter: tuple  # (title, text)
    patron: tuple = ("", "", "")  # (family, title, text)
    exports: dict = field(default_factory=dict)  # trade -> export value of the home market


def build_houses(net: Network, colours: list[str]) -> list[House]:
    """One merchant house per player colour, rooted in a market town of a different state.

    Home trades are the market's two largest export trades, never Slaves (that trade always carries
    its overhead), with no trade given to more than ceil(2 x players / 5) houses so the table differs.
    """
    m = net.m
    goods = {g["i"]: g for g in m.live("goods")}
    states = {s["i"]: s for s in m.live("states")}
    exports: dict[int, Counter] = defaultdict(Counter)
    for d in m.data["deals"]:
        if d.get("sellerType") == "market" and d["good"] in goods:
            exports[d["seller"]][trade_of(goods[d["good"]])] += d["units"] * d["price"]
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
    cap = math.ceil(2 * len(colours) / 5)
    used = Counter()
    homes = {}
    for i in picked:
        pref = [t for t, _ in exports[i].most_common() if t != "Slaves"]
        pref += [t for t in sorted(TRADES[:5], key=lambda t: used[t]) if t not in pref]
        chosen = [t for t in pref if used[t] < cap][:2]
        chosen += [t for t in pref if t not in chosen][: 2 - len(chosen)]
        chosen.sort(key=TRADES.index)
        for t in chosen:
            used[t] += 1
        homes[i] = chosen
    houses, charters = [], Counter()
    for colour, i in zip(colours, picked):
        stop = net.stops[net.markets[i]["centerBurgId"]]
        st = states.get(stop.state, {"name": "the free towns", "fullName": "the free towns"})
        has_sea = any(ln.mode == "sea" for _, ln in net.nbr[stop.burg])
        options = []
        if stop.air:
            options.append(("Sky charter", "Air infrastructure: +4 expense, not +5."))
        if has_sea:
            options.append(("Shipwrights' charter", "Sea infrastructure: +1 expense, not +2."))
        options.append(("Carters' charter", f"Land infrastructure in {st['name']}: +0 expense, not +1."))
        charter = min(options, key=lambda o: charters[o[0]])
        charters[charter[0]] += 1
        houses.append(House(colour, i, stop.name, stop.state, st["name"], st.get("fullName") or st["name"],
                            homes[i], charter, ("", "", ""), {t: round(v, 1) for t, v in exports[i].most_common()}))
    return houses


PATRONS = {"War": "Army purveyors", "Disaster": "Relief brokers", "Disorder": "Caravan guards",
           "Faith": "Pilgrim carriers", "Enterprise": "Investors", "Court & festival": "Court suppliers"}


def assign_patrons(houses: list[House], by_state: dict, deck_families: dict) -> None:
    """Give each house the patronage of one decree family, all different while families last.

    by_state: state id -> {family: candidate decrees that state issues}; deck_families: family -> cards
    in the decree deck. A house scores a family by its home state's candidates in it, plus a quarter
    of that family's cards in the deck, and the deal maximises the total.
    """
    from itertools import permutations
    fams = [f for f in PATRONS if deck_families.get(f)] or list(PATRONS)
    def score(h, f):
        return by_state.get(h.state, {}).get(f, 0) + 0.25 * deck_families.get(f, 0)
    best, best_s = None, -1.0
    k = min(len(houses), len(fams))
    for perm in permutations(fams, k):
        sc = sum(score(h, f) for h, f in zip(houses, perm))
        if sc > best_s:
            best, best_s = perm, sc
    for n, h in enumerate(houses):
        f = best[n] if n < k else max(fams, key=lambda f: score(h, f))
        h.patron = (f, PATRONS[f], f"Your petitions to {f} decrees cost one star less (never below one).")


# ---------------------------------------------------------------------------------- infrastructure
COSTS = {"land": 1, "sea": 2, "air": 5}


def infrastructure_counts(land: int = 50, wild_share: float = 0.12) -> dict[str, int]:
    """Scarcity proportional to cost: count = land / cost; wilds as a share of the deck."""
    counts = {k: max(1, round(land / c)) for k, c in COSTS.items()}
    counts["wild"] = max(1, round(sum(counts.values()) * wild_share))
    return counts
