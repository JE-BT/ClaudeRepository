"""Decree cards: proclamations by the rulers of states, built from the world's history and markers.

Every decree has the same anatomy:
  issuer       the state and its ruler (title from the state's form), and the state's treasury class
  cause        the map object it comes from: a war, a tariff, a zone, a marker, the slave trade
  affected     an area visible on the board: a state, named stops, or named links
  on reveal    (optional) a one-shot effect when the decree is drawn
  edict        one ongoing effect on routes through the affected area
  petitions    1, 3 and 5 stars: personal and this round / personal while the decree stands /
               settle the decree (it leaves the row; the petitioner keeps the card)
  lapse        what happens if the decree is pushed out of the row unsettled

Effects name their target exactly: "gold" is paid or gained once, "income" and "expense" move the
tracks. Rule of thumb for gold: a petition costs gold only when its benefit is shared by every
player (it ends a burden for all), and the issuer's treasury sets the price (rich 2, modest 4, poor
6 at five stars).

Sources, each kept only if its affected area lies on at least one commission route:
  ongoing campaigns (no end, or ending this year)  War, one card per belligerent
  campaigns ended in the last two years           Aftermath (rebuilding)
  embargo tariffs                                 Embargo (closure, or a levy at a chokepoint)
  tariffs of 30% or more                          Customs
  zones                                           Invasion, Rebels, Proselytism, Crusade, Disease, disasters
  markers                                         Disorder, Faith, Enterprise, Court & festival, by type
  the slave trade                                 a league of the states that do not trade slaves, and a
                                                  revolt in the state with the most slave routes
  theocracies                                     sumptuary law on luxuries
"""
from __future__ import annotations

import heapq
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .decks import Route
from .goods import TRADES, goods_named_in, trade_of
from .network import Network

FAMILIES = ["War", "Disaster", "Disorder", "Faith", "Enterprise", "Court & festival", "Law"]
FAMILY_COLOR = {"War": "#8E2F25", "Disaster": "#9A5B12", "Disorder": "#4F3A63", "Faith": "#2F5D7A",
                "Enterprise": "#2E6B4F", "Court & festival": "#8A6A12", "Law": "#3C4650"}
GOLD_SHARED = {5: {"rich": 2, "modest": 4, "poor": 6}, 3: {"rich": 1, "modest": 2, "poor": 3}}
SETTLE_INCOME, SETTLE_INCOME_WIDE, WIDE_SHARE = 2, 3, 0.2
TOKEN = "(put a token of yours on this card)"


@dataclass
class Petition:
    stars: int
    title: str
    text: str
    shared: bool = False  # benefit shared by every player: costs gold
    gold: int = 0
    income: int = 0  # income-track reward
    settles: bool = False


@dataclass
class Decree:
    family: str
    kind: str  # template key
    title: str
    issuer: int
    issuer_name: str
    ruler: str
    treasury: str
    cause: str
    area_kind: str  # state | states | stops | links
    area_label: str
    area_text: str
    on_reveal: str
    edict: str
    petitions: list
    lapse: str
    routes: int  # reference routes affected
    share: float
    deck: str | None = None
    source: str = ""
    number: int = 0
    priority: int = 2
    area_key: tuple = field(default_factory=tuple)


# ------------------------------------------------------------------------------ titles and classes
RULER = {
    "Empire": "Emperor", "Kingdom": "King", "Grand Duchy": "Grand Duke", "Duchy": "Duke", "Principality": "Prince",
    "Marches": "Margrave", "Khaganate": "Khagan", "Khanate": "Khan", "Horde": "Khan", "Ulus": "Khan",
    "Sultanate": "Sultan", "Emirate": "Emir", "Beylik": "Bey", "Tsardom": "Tsar", "Shogunate": "Shogun",
    "Satrapy": "Satrap", "Despotate": "Despot", "Viceroyalty": "Viceroy", "Dominion": "Sovereign",
    "Heptarchy": "High King", "Caliphate": "Caliph", "Diocese": "Bishop", "Bishopric": "Bishop",
    "Archbishopric": "Archbishop", "Patriarchate": "Patriarch", "Exarchate": "Exarch", "Eparchy": "Eparch",
    "Imamah": "Imam", "Theocracy": "High Priest", "Holy State": "High Priest", "Brotherhood": "Grand Master",
    "Divine Duchy": "Duke", "Divine Grand Duchy": "Grand Duke", "Divine Principality": "Prince",
    "Divine Kingdom": "King", "Divine Empire": "Emperor", "Most Serene Republic": "Doge", "Free City": "Council",
    "City-state": "Council", "Trade Company": "Directors", "Chancellery": "Chancellor",
}


def ruler_of(st: dict) -> str:
    form, name = st.get("formName") or "", st.get("name", "")
    t = RULER.get(form)
    if t:
        return f"the {t} of {name}"
    if st.get("form") in ("Republic", "Union", "Anarchy"):
        return f"the Council of {name}"
    return f"the ruler of {name}"


def treasury_classes(states: dict) -> dict[int, str]:
    live = sorted((s for i, s in states.items() if i), key=lambda s: s.get("treasury") or 0)
    n = len(live)
    out = {}
    for k, s in enumerate(live):
        out[s["i"]] = "poor" if k < n / 3 else ("modest" if k < 2 * n / 3 else "rich")
    return out


def _list(names: list[str], conj: str = "and") -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {conj} " + names[-1]


# ------------------------------------------------------------------------------ the builder
class DecreeBuilder:
    def __init__(self, net: Network, routes: dict[int, Route], commissions: dict, seed: int = 1):
        self.net, self.m = net, net.m
        self.rng = random.Random(seed)
        self.states = {s["i"]: s for s in self.m.live("states")}
        self.sname = {i: s["name"] for i, s in self.states.items()}
        self.tclass = treasury_classes(self.states)
        self.year = self.m.calendar.get("year") or 0
        self.era = self.m.calendar.get("eraShort") or ""
        self.goods = self.m.live("goods")
        self.trade_by_deal = {c.deal: c.trade for cs in commissions.values() for c in cs}
        self.routes = {d: r for d, r in routes.items() if d in self.trade_by_deal}
        self.total = max(1, len(self.routes))
        self.rstops = {d: set(r.stops) for d, r in self.routes.items()}
        self.rlinks = {d: {self.norm(k) for k in r.links if k} for d, r in self.routes.items()}
        self.rstates = {d: {net.stops[b].state for b in r.stops} for d, r in self.routes.items()}
        self.ends = {d: (net.stops[r.stops[0]].state, net.stops[r.stops[-1]].state) for d, r in self.routes.items()}
        xy2c = {v: k for k, v in net.xy.items()}
        self.linkcells = {self.norm(k): {xy2c.get(tuple(p)) for p in ln.points} for k, ln in net.links.items()}
        self.out: list[Decree] = []
        self.polarity = Counter()  # enterprise opportunities vs failures, kept near 60 / 40

    @staticmethod
    def norm(k):
        a, b, md = k
        return (a, b, md) if a < b else (b, a, md)

    # ---------------------------------------------------------------- route sets
    def through_states(self, sids, trade=None):
        return {d for d, s in self.rstates.items() if s & set(sids) and (trade is None or self.trade_by_deal[d] == trade)}

    def through_stops(self, stops, trade=None):
        return {d for d, s in self.rstops.items() if s & set(stops) and (trade is None or self.trade_by_deal[d] == trade)}

    def using_links(self, links, trade=None):
        links = {self.norm(k) for k in links}
        return {d for d, s in self.rlinks.items() if s & links and (trade is None or self.trade_by_deal[d] == trade)}

    def detour_share(self, deals, avoid_stops=(), avoid_links=()) -> float:
        """Share of the given routes that still have a land/sea route avoiding the stops or links."""
        avoid_stops, avoid_links = set(avoid_stops), {self.norm(k) for k in avoid_links}
        if not deals:
            return 1.0
        ok = 0
        for d in deals:
            r = self.routes[d]
            a, b = r.stops[0], r.stops[-1]
            if a in avoid_stops or b in avoid_stops:
                continue
            dist, pq, found = {a: 0}, [(0, a)], False
            while pq:
                h, c = heapq.heappop(pq)
                if c == b:
                    found = True
                    break
                if h > dist.get(c, 1e9):
                    continue
                for n, ln in self.net.nbr[c]:
                    if n in avoid_stops or self.norm((ln.a, ln.b, ln.mode)) in avoid_links:
                        continue
                    if h + 1 < dist.get(n, 1e9):
                        dist[n] = h + 1
                        heapq.heappush(pq, (h + 1, n))
            ok += found
        return ok / len(deals)

    # ---------------------------------------------------------------- areas
    def link_name(self, k) -> str:
        a, b, md = k
        return f"{self.net.stops[a].name} \u2013 {self.net.stops[b].name}" + (" (sea)" if md == "sea" else "")

    def area_links(self, links, max_links=3):
        """('links' | 'stops', label, text, key, stop set) for a set of links; long lists become stops."""
        links = sorted({self.norm(k) for k in links})
        if len(links) <= max_links:
            lab = "Affected link" if len(links) == 1 else "Affected links"
            return "links", lab, "; ".join(self.link_name(k) for k in links), tuple(links), set()
        deg = Counter()
        for a, b, _ in links:
            deg[a] += 1
            deg[b] += 1
        stops = [s for s, n in deg.most_common() if n >= 2][:4] or [s for s, _ in deg.most_common(3)]
        return "stops", "Affected stops", _list([self.net.stops[s].name for s in stops]), tuple(sorted(stops)), set(stops)

    def area_state(self, sid):
        return "state", "Affected state", f"{self.sname[sid]}: every stop in the state", (sid,)

    def issuer_for(self, cells=(), stops=()):
        c = Counter(self.m.data["state"][x] for x in cells if self.m.data["state"][x])
        if not c:
            c = Counter(self.net.stops[s].state for s in stops if self.net.stops[s].state)
        return c.most_common(1)[0][0] if c else 0

    # ---------------------------------------------------------------- petition helpers
    def settle(self, title, text, issuer, share, shared=True):
        inc = SETTLE_INCOME_WIDE if share >= WIDE_SHARE else SETTLE_INCOME
        gold = GOLD_SHARED[5][self.tclass.get(issuer, "modest")] if shared else 0
        return Petition(5, title, text, shared, gold, inc, True)

    def add(self, family, kind, title, issuer, cause, area, on_reveal, edict, petitions, lapse, deals, deck=None,
            source="", priority=2):
        if not issuer or not deals:
            return None
        st = self.states[issuer]
        kind_, label, text, key = area[:4]
        d = Decree(family, kind, title, issuer, st["name"], ruler_of(st), self.tclass.get(issuer, "modest"), cause,
                   kind_, label, text, on_reveal, edict, petitions, lapse, len(deals), round(len(deals) / self.total, 3),
                   deck, source, 0, priority, (kind_, key))
        self.out.append(d)
        return d

    # ---------------------------------------------------------------- sources
    def wars(self):
        seen = set()
        for s in self.states.values():
            for c in s.get("campaigns") or []:
                end, start = c.get("end"), c.get("start")
                if end is not None and end < self.year:
                    if end >= self.year - 2:
                        self._aftermath(s, c)
                    continue
                key = (c.get("name"), s["i"])
                if key in seen:
                    continue
                seen.add(key)
                self._war(s, c)

    def _war(self, s, c):
        sid = s["i"]
        att, dfn = c.get("attacker"), c.get("defender")
        enemy = dfn if att == sid else att
        ename = self.sname.get(enemy, "its enemies")
        deals = self.through_states([sid])
        side = "attacks" if att == sid else "defends against"
        cause = f"{c['name']}, begun {c.get('start')} {self.era}: {s['name']} {side} {ename}."
        sh = len(deals) / self.total
        edict = (f"When you settle accounts, pay 1 gold for each of your routes through {s['name']}, "
                 f"and gain 2 gold for each of your Metals & arms routes through {s['name']}.")
        pets = [Petition(1, "Safe-conduct", "Ignore this edict this round."),
                Petition(3, "Army contractor", f"Ignore the payment while this decree stands {TOKEN}."),
                self.settle("Broker the peace", "The decree ends. Keep this card.", sid, sh)]
        lapse = f"The war drags on: each player pays 1 gold for each of their routes through {s['name']}."
        self.add("War", "war", f"The {c['name']}", sid, cause, self.area_state(sid), "", edict, pets, lapse, deals,
                 "Metals & arms", f"campaign:{c['name']}", 0)

    def _aftermath(self, s, c):
        sid = s["i"]
        if c.get("defender") not in (None, sid) and c.get("attacker") == sid:
            return  # the defender's land carries the damage; one card per campaign
        deals = self.through_states([sid], "Building")
        if not deals:
            return
        cause = f"The {c['name']} ended in {c.get('end')} {self.era}; {s['name']} is rebuilding."
        edict = f"When you settle accounts, gain 1 gold for each of your Building routes through {s['name']}."
        pets = [Petition(1, "Sell supplies", "Gain 2 gold."),
                Petition(3, "Contractor", f"Your Building routes through {s['name']} earn 2 gold each, not 1, while "
                                          f"this decree stands {TOKEN}."),
                self.settle("Royal contractor", "The decree ends. Keep this card.", sid, len(deals) / self.total, False)]
        self.add("War", "aftermath", f"Rebuilding after the {c['name']}", sid, cause, self.area_state(sid), "", edict,
                 pets, "The work is done: no effect.", deals, "Building", f"campaign:{c['name']}", 2)

    def tariffs(self):
        for s in self.states.values():
            sid = s["i"]
            if not sid:
                continue
            emb, high = set(), set()
            for t in s.get("tariffs") or []:
                tgt = t.get("states")
                if tgt == "all" or t.get("goods") not in ("all", None):
                    continue
                if t.get("rate") == "embargo":
                    emb |= set(tgt)
                elif isinstance(t.get("rate"), (int, float)) and t["rate"] >= 0.3:
                    high |= set(tgt)
            if emb:
                self._embargo(s, sorted(emb))
            if high:
                self._customs(s, sorted(high))

    def _embargo(self, s, enemies):
        sid, name = s["i"], s["name"]
        en = [self.sname[e] for e in enemies if e in self.sname]
        deals = {d for d in self.through_states([sid]) if set(self.ends[d]) & set(enemies)}
        if not deals:
            return
        stops = [b for b, st in self.net.stops.items() if st.state == sid]
        detour = self.detour_share(deals, avoid_stops=stops)
        cause = f"{name} keeps an embargo on {_list(en)}."
        if detour >= 0.75:
            edict = f"No route that starts or ends in {_list(en, 'or')} may pass through {name}."
            lapse = "The embargo holds: no effect."
        else:  # a chokepoint: shutting it would strand the routes, so the guards take bribes instead
            edict = (f"When you settle accounts, pay 2 gold for each of your routes through {name} that starts or "
                     f"ends in {_list(en, 'or')}.")
            lapse = "The embargo holds: no effect."
        pets = [Petition(1, "Smuggle", "One of your routes ignores this edict this round."),
                Petition(3, "Licence", f"Your routes ignore this edict while this decree stands {TOKEN}."),
                self.settle("Lift the embargo", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("War", "embargo", f"{name} enforces its embargo", sid, cause, self.area_state(sid), "", edict, pets,
                 lapse, deals, None, "tariff:embargo", 1)

    def _customs(self, s, targets):
        sid, name = s["i"], s["name"]
        tn = [self.sname[e] for e in targets if e in self.sname]
        deals = {d for d in self.through_states([sid]) if self.ends[d][0] in targets}
        if not deals:
            return
        cause = f"{name} sets a tariff of 30% on goods from {_list(tn)}."
        edict = (f"When you settle accounts, pay 1 gold for each of your routes through {name} that starts in "
                 f"{_list(tn, 'or')}.")
        pets = [Petition(1, "Bribe the clerk", "Ignore this edict this round."),
                Petition(3, "Bonded warehouse", f"Ignore this edict while this decree stands {TOKEN}."),
                self.settle("Trade treaty", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("War", "customs", f"The customs houses of {name}", sid, cause, self.area_state(sid), "", edict, pets,
                 "The tariff stays: no effect.", deals, None, "tariff:high", 2)

    def theocracies(self):
        for s in self.states.values():
            if s.get("form") != "Theocracy":
                continue
            sid, name = s["i"], s["name"]
            deals = self.through_states([sid], "Luxuries")
            if not deals:
                continue
            cause = f"The {s.get('fullName') or name} condemns display and excess."
            edict = f"When you settle accounts, pay 1 gold for each of your Luxuries routes through {name}."
            pets = [Petition(1, "Plain wrapping", "Ignore this edict this round."),
                    Petition(3, "Dispensation", f"Ignore this edict while this decree stands {TOKEN}."),
                    self.settle("Indulgence", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
            self.add("Faith", "sumptuary", f"Sumptuary law of {name}", sid, cause, self.area_state(sid), "", edict, pets,
                     "The preachers move on: no effect.", deals, "Luxuries", "form:theocracy", 2)

    # ---------------------------------------------------------------- zones
    ZONE_KIND = [(("invasion", "occupation", "conquest"), "invasion"), (("rebel", "revolt", "insurrection"), "rebels"),
                 (("proselyt", "mission"), "proselytism"), (("crusade", "holy war", "jihad"), "crusade"),
                 (("disease", "plague", "fever", "pox", "epidemic", "pestilence"), "disease"),
                 (("flood",), "flood"), (("tsunami",), "tsunami"), (("avalanche",), "avalanche"),
                 (("eruption", "volcan"), "eruption"), (("fault", "earthquake", "quake"), "fault"),
                 (("disaster", "storm", "fire", "drought", "famine", "landslide"), "disaster")]

    def zones(self):
        for z in self.m.live("zones"):
            zt = f"{z.get('type', '')} {z.get('name', '')}".lower()
            kind = next((k for keys, k in self.ZONE_KIND if any(w in zt for w in keys)), None)
            if not kind:
                continue
            zc = set(z.get("cells") or [])
            links = [k for k, cl in self.linkcells.items() if cl & zc]
            if not links:
                continue
            area = self.area_links(links)
            stops_area = area[4] if area[0] == "stops" else {x for k in links for x in k[:2]}
            deals = self.through_stops(area[4]) if area[0] == "stops" else self.using_links(links)
            issuer = self.issuer_for(zc, stops_area)
            getattr(self, f"_z_{kind}" if kind in ("invasion", "rebels", "proselytism", "crusade", "disease")
                    else "_z_disaster")(z, kind, area, links, deals, issuer)

    def _z_invasion(self, z, kind, area, links, deals, sid):
        name = z.get("name", "Invasion")
        pets = [Petition(1, "Run the lines", "Ignore this edict this round."),
                Petition(3, "Supply the defenders", f"Ignore this edict while this decree stands {TOKEN}."),
                self.settle("Drive them out", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        where = "links" if area[0] == "links" else "stops"
        self.add("War", "invasion", name, sid, f"{name}: foreign troops hold the country around the affected {where}.",
                 area[:4], "", "When you settle accounts, pay 2 gold for each of your routes through the affected area.",
                 pets, "The occupation hardens: each player removes one land infrastructure from a station of theirs "
                       "in the affected area.", deals, None, f"zone:{z.get('i')}", 0)

    def _z_rebels(self, z, kind, area, links, deals, sid):
        name = z.get("name", "Rebels")
        pets = [Petition(1, "Pay them off", "Ignore this edict this round."),
                Petition(3, "Hire guards", f"Ignore this edict while this decree stands {TOKEN}."),
                self.settle("Put down the revolt", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("Disorder", "rebels", name, sid, f"{name} hold the roads of the affected area.", area[:4],
                 "Metals & arms commissions routed through the affected area go to the bottom of their deck (not a "
                 "breach).", "When you settle accounts, pay 1 gold for each of your routes through the affected area.",
                 pets, "The rebels take the roads: each player removes one land infrastructure from a station of "
                       "theirs in the affected area.", deals, "Metals & arms", f"zone:{z.get('i')}", 0)

    def _z_proselytism(self, z, kind, area, links, deals, sid):
        name = z.get("name", "Mission")
        pets = [Petition(1, "Carry missionaries", "Gain 2 gold."),
                Petition(3, "Convert", f"Ignore the tithe while this decree stands {TOKEN}."),
                self.settle("Patron of the mission", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("Faith", "proselytism", name, sid, f"{name}: missionaries ask a tithe of every caravan.", area[:4], "",
                 "When you settle accounts, pay 1 gold for each of your routes through the affected area.", pets,
                 "The mission moves on: no effect.", deals, None, f"zone:{z.get('i')}", 1)

    def _z_crusade(self, z, kind, area, links, deals, sid):
        name = z.get("name", "Crusade")
        pets = [Petition(1, "Take the cross", "Ignore this edict this round."),
                Petition(3, "Supply the host", f"Ignore the payment while this decree stands {TOKEN}."),
                self.settle("Negotiate a truce", "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("Faith", "crusade", name, sid, f"{name}: a holy army marches through the affected area.", area[:4], "",
                 "When you settle accounts, pay 1 gold for each of your routes through the affected area, and gain 2 "
                 "gold for each of your Metals & arms routes there.", pets,
                 "The host marches on: each player pays 1 gold for each of their routes through the affected area.",
                 deals, "Metals & arms", f"zone:{z.get('i')}", 0)

    def _z_disease(self, z, kind, area, links, deals, sid):
        name = z.get("name", "Plague")
        stops = area[4] if area[0] == "stops" else {x for k in links for x in k[:2]}
        q = {d for d in deals if self.trade_by_deal[d] in ("Provisions", "Livestock")}
        if not q:
            return
        pets = [Petition(1, "Carry physicians", "Gain 2 gold."),
                Petition(3, "Clean papers", f"Your routes ignore the quarantine while this decree stands {TOKEN}."),
                self.settle("Fund the hospitals", "The decree ends. Keep this card.", sid, len(q) / self.total)]
        self.add("Disaster", "disease", name, sid, f"{name}: the affected area is under quarantine.", area[:4], "",
                 "No Provisions or Livestock route may pass through the affected area.", pets,
                 "The sickness burns out: no effect.", q, "Provisions", f"zone:{z.get('i')}", 0)

    LAPSE = {"flood": "The waters recede", "tsunami": "The coast is cleared", "avalanche": "The pass is dug out",
             "eruption": "The ash settles", "fault": "The roads are mended", "disaster": "The damage is repaired"}

    def _z_disaster(self, z, kind, area, links, deals, sid):
        name = z.get("name", kind.capitalize())
        modes = {k[2] for k in links}
        mode = "sea" if kind == "tsunami" and "sea" in modes else "land"
        if area[0] == "links":
            reveal = (f"Each player removes one {mode} infrastructure from each of their stations at either end of an "
                      f"affected link (move your expense marker down as usual).")
            edict = "The affected links cannot be used." if mode in modes else "The affected links cannot be used."
            closed = {self.norm(k) for k in links}
        else:
            reveal = (f"Each player removes one {mode} infrastructure from each of their stations at an affected stop "
                      f"(move your expense marker down as usual).")
            edict = f"No {mode} link into or out of an affected stop can be used."
            closed = {k for k in links if k[2] == mode}
        hit = self.using_links(closed) if closed else deals
        if not hit:
            hit = deals
        pets = [Petition(1, "Relief convoy", "If you hold a Provisions commission, gain 3 gold."),
                Petition(3, "Rebuild your own", f"Your routes ignore the closure while this decree stands {TOKEN}."),
                self.settle("Restore the country", "The decree ends. Keep this card.", sid, len(hit) / self.total)]
        self.add("Disaster", kind, name, sid, f"{name} strikes the affected area.", area[:4], reveal, edict, pets,
                 f"{self.LAPSE[kind]}: the decree ends with no further effect.", hit, "Provisions", f"zone:{z.get('i')}", 0)

    # ---------------------------------------------------------------- markers
    DISORDER = {  # type: (title, 1-star, 3-star, 5-star, sea only)
        "brigands": ("Brigands on the road", "Pay them off", "Hire outriders", "Claim the bounty", False),
        "pirates": ("Pirates in the lanes", "Pay the toll", "Sail in convoy", "Hunt them down", True),
        "hill-monsters": ("A beast in the hills", "Leave an offering", "Hire hunters", "Claim the bounty", False),
        "lake-monsters": ("Something in the water", "Leave an offering", "Hire boatmen", "Claim the bounty", False),
        "sea-monsters": ("A monster at sea", "Throw a cask overboard", "Sail in convoy", "Claim the bounty", True),
        "dungeons": ("Raiders from the deep", "Pay them off", "Hire guards", "Clear the depths", False),
        "necropolises": ("The dead walk", "Pay the priests", "Travel by day", "Lay them to rest", False),
        "disturbed-burials": ("Graves disturbed", "Pay the priests", "Travel by day", "Lay them to rest", False),
        "encounters": ("Strangers on the road", "Pay them off", "Hire guards", "Learn what they want", False),
        "rifts": ("A rift in the world", "Pay a guide", "Hire guides", "Seal the rift", False),
        "battlefields": ("Deserters on the old field", "Pay them off", "Hire guards", "Hang the ringleaders", False),
        "mirage": ("Caravans lost in the haze", "Hire a guide", "Hire a caravan master", "Map the safe road", False),
    }
    FAITH = {"sacred-mountains": "Pilgrims to the mountain", "sacred-forests": "Pilgrims to the forest",
             "sacred-pineries": "Pilgrims to the pinery", "sacred-palm-groves": "Pilgrims to the grove"}
    ENTERPRISE = {  # type: (opportunity title, collapse title, default trade or None for any, site noun)
        "mines": ("Investors wanted for the mine", "The mine has collapsed", "Metals & arms", "mine"),
        "bridges": ("Tolls let for the bridge", "The bridge has fallen", "Building", "bridge"),
        "tunnels": ("Tolls let for the tunnel", "The tunnel has flooded", "Building", "tunnel"),
        "lighthouses": ("The beacon is relit", "The beacon is dark", None, "lighthouse"),
        "inns": ("A new coaching inn", "The inn has burned", "Provisions", "inn"),
        "libraries": ("The library seeks patrons", "The library is closed", "Luxuries", "library"),
        "caves": ("Cold stores in the caves", "The caves are flooded", "Provisions", "caves"),
        "waterfalls": ("Mills below the falls", "The mill race has failed", "Building", "mills"),
        "water-sources": ("Fresh water for sale", "The spring has run dry", "Provisions", "spring"),
        "springs": ("Fresh water for sale", "The spring has run dry", "Provisions", "spring"),
        "hot-springs": ("The baths reopen", "The baths are closed", "Luxuries", "baths"),
        "ruins": ("Stone from the ruins", "The ruins are fenced off", "Building", "ruins"),
        "canoes": ("Lightermen for hire", "The lightermen strike", "Provisions", "landing"),
        "portals": ("The portal opens for trade", "The portal misfires", None, "portal"),
        "volcanoes": ("Sulphur from the volcano", "The volcano stirs", "Metals & arms", "volcano"),
    }
    COURT = {  # type: (event, trade, 1-star, 3-star, 5-star)
        "fairs": ("fair", "Luxuries", "Sell at the fair", "Supply the fair", "Patron of the fair"),
        "jousts": ("joust", "Livestock", "Sell at the joust", "Supply the joust", "Patron of the joust"),
        "circuses": ("circus", "Provisions", "Sell at the circus", "Supply the circus", "Patron of the circus"),
        "dances": ("festival", "Provisions", "Sell at the festival", "Supply the festival", "Patron of the festival"),
        "statues": ("works", "Building", "Sell stone to the masons", "Supply the masons", "Patron of the monument"),
        "migration": ("drove", "Livestock", "Sell at the drovers' fair", "Supply the drovers", "Patron of the drove")}

    LABEL = {"mines": "Mine", "inns": "Inn", "libraries": "Library", "lighthouses": "Lighthouse", "bridges": "Bridge",
             "tunnels": "Tunnel", "caves": "Caves", "waterfalls": "Waterfall", "water-sources": "Spring",
             "springs": "Spring", "hot-springs": "Hot springs", "ruins": "Ruins", "canoes": "Canoes", "portals": "Portal",
             "volcanoes": "Volcano", "brigands": "Brigands", "pirates": "Pirates", "hill-monsters": "Hill monster",
             "lake-monsters": "Lake monster", "sea-monsters": "Sea monster", "dungeons": "Dungeon",
             "necropolises": "Necropolis", "disturbed-burials": "Disturbed burial", "encounters": "Encounter",
             "rifts": "Rift", "battlefields": "Battlefield", "mirage": "Mirage", "fairs": "Fair", "jousts": "Joust",
             "circuses": "Circus", "dances": "Dance", "statues": "Statue", "migration": "Migration",
             "sacred-mountains": "Sacred mountain", "sacred-forests": "Sacred forest",
             "sacred-pineries": "Sacred pinery", "sacred-palm-groves": "Sacred grove"}

    def markers(self):
        net = self.net
        air_sites = [s for s in net.stops.values() if s.air]
        for star in net.stars:
            mk = star.marker
            t = mk.get("type", "")
            if star.link:
                key = self.norm(star.link)
                area = self.area_links([key])
                links = [key]
                deals_all = self.using_links(links)
                stops = set(key[:2])
            else:  # remote star: only near an air site does it touch play
                if not air_sites:
                    continue
                site = min(air_sites, key=lambda s: math.hypot(s.x - star.x, s.y - star.y))
                if math.hypot(site.x - star.x, site.y - star.y) > 0.05 * net.width:
                    continue
                area = ("stops", "Affected stop", site.name, (site.burg,), {site.burg})
                links, stops = [], {site.burg}
                deals_all = self.through_stops(stops)
            sid = self.m.data["state"][mk["cell"]] or self.issuer_for((), stops)
            if not deals_all or not sid:
                continue
            name = mk.get("name") or t
            label = self.LABEL.get(t, t.replace("-", " ").capitalize())
            if len(name.split()) == 1 or name.casefold().startswith("random "):  # generic: place it by its stops
                near = min(net.stops.values(), key=lambda q: (q.x - mk["x"]) ** 2 + (q.y - mk["y"]) ** 2).name
                name = f"{name} near {near}"
            elif label.split()[-1].casefold().rstrip("s") not in name.casefold():
                name = f"{label}: {name}"
            src = f"marker:{mk.get('i')}"
            if t in self.DISORDER:
                self._m_disorder(t, name, sid, area, links, deals_all, src)
            elif t in self.FAITH:
                self._m_pilgrims(t, name, sid, area, deals_all, src)
            elif t in self.ENTERPRISE:
                self._m_enterprise(t, mk, name, sid, area, links, deals_all, src)
            elif t in self.COURT:
                self._m_court(t, name, sid, area, deals_all, src)

    def _m_disorder(self, t, name, sid, area, links, deals, src):
        title, p1, p3, p5, sea = self.DISORDER[t]
        if sea and not any(k[2] == "sea" for k in links):
            sea = False
        what = "sea routes" if sea else "routes"
        if sea:
            deals = {d for d in deals if any(k[2] == "sea" for k in self.rlinks[d])} or deals
        pets = [Petition(1, p1, "Ignore this edict this round."),
                Petition(3, p3, f"Ignore this edict while this decree stands {TOKEN}."),
                self.settle(p5, "The decree ends. Keep this card.", sid, len(deals) / self.total)]
        self.add("Disorder", t, title, sid, f"{name}.", area[:4], "",
                 f"When you settle accounts, pay 1 gold for each of your {what} through the affected area.", pets,
                 f"It strikes once more before it ends: each player pays 1 gold for each of their {what} through the "
                 f"affected area.", deals, None, src, 3)

    def _m_pilgrims(self, t, name, sid, area, deals_all, src):
        deals = {d for d in deals_all if self.trade_by_deal[d] == "Provisions"}
        if not deals:
            return
        pets = [Petition(1, "Carry pilgrims", "Gain 2 gold."),
                Petition(3, "Pilgrim hostels", f"Your Provisions routes through the affected area earn 2 gold each, "
                                               f"not 1, while this decree stands {TOKEN}."),
                self.settle("Endow the shrine", "The decree ends. Keep this card.", sid, len(deals) / self.total, False)]
        self.add("Faith", t, self.FAITH[t], sid, f"{name}: the pilgrim season begins.", area[:4], "",
                 "When you settle accounts, gain 1 gold for each of your Provisions routes through the affected area.",
                 pets, "The season ends: no effect.", deals, "Provisions", src, 3)

    def _m_enterprise(self, t, mk, name, sid, area, links, deals_all, src):
        opp_title, col_title, trade, noun = self.ENTERPRISE[t]
        named = goods_named_in(mk.get("note", "") + " " + (mk.get("name") or ""), self.goods)
        if named and t in ("mines", "volcanoes", "caves", "ruins"):
            trade = trade_of(named[0])
        if t == "lighthouses":
            deals = {d for d in deals_all if any(k[2] == "sea" for k in self.rlinks[d])}
            what, tw = "sea routes", None
        elif t == "portals":
            deals, what, tw = deals_all, "routes", None
        else:
            deals = {d for d in deals_all if self.trade_by_deal[d] == trade}
            what, tw = f"{trade} routes", trade
        if len(deals) < 4:  # too few routes of that trade pass: the site matters to all traffic
            deals, what, tw = deals_all, "routes", None
        sh = len(deals) / self.total
        opportunity = self.polarity[True] < 0.6 * (sum(self.polarity.values()) + 1)
        self.polarity[opportunity] += 1
        if opportunity:
            if t == "libraries":
                p5 = Petition(5, "Charter of learning", "Open one trade with no overhead, now or later. The decree "
                                                        "ends. Keep this card.", False, 0, 0, True)
            else:
                p5 = self.settle("Concession", "The decree ends. Keep this card.", sid, sh, False)
            pets = [Petition(1, "Buy a share", "Gain 2 gold."),
                    Petition(3, "Partnership", f"Your {what} through the affected area earn 2 gold each, not 1, while "
                                               f"this decree stands {TOKEN}."), p5]
            self.add("Enterprise", t, opp_title, sid, f"{name}.", area[:4], "",
                     f"When you settle accounts, gain 1 gold for each of your {what} through the affected area.", pets,
                     "The chance passes: no effect.", deals, tw, src, 3)
        else:
            closable = t in ("bridges", "tunnels") and area[0] == "links"
            if closable and self.detour_share(self.using_links(links), avoid_links=links) >= 0.75:
                edict, hit = "The affected link cannot be used.", self.using_links(links)
            else:
                edict, hit = (f"When you settle accounts, pay 1 gold for each of your {what} through the affected "
                              f"area."), deals
            pets = [Petition(1, "Lend a hand", "Gain 2 gold."),
                    Petition(3, "Work around it", f"Ignore this edict while this decree stands {TOKEN}."),
                    self.settle(f"Rebuild the {noun}", "The decree ends. Keep this card.", sid, len(hit) / self.total)]
            self.add("Enterprise", t, col_title, sid, f"{name}.", area[:4], "", edict, pets,
                     f"The {noun} is abandoned: no effect.", hit, tw, src, 3)

    def _m_court(self, t, name, sid, area, deals_all, src):
        """Festivals are proclaimed by the court, so they draw trade across the whole issuing state."""
        ev, trade, p1, p3, p5 = self.COURT[t]
        deals = self.through_states([sid], trade)
        if not deals:
            return
        st = self.sname[sid]
        pets = [Petition(1, p1, "Gain 2 gold."),
                Petition(3, p3, f"Your {trade} routes through {st} earn 2 gold each, not 1, while this decree stands "
                                f"{TOKEN}."),
                self.settle(p5, "The decree ends. Keep this card.", sid, len(deals) / self.total, False)]
        title = {"statues": "A monument is raised", "migration": "The great herds pass"}.get(t, f"The {ev} is proclaimed")
        near = " and ".join(self.net.stops[x].name for x in (area[3] if area[0] == "stops" else area[3][0][:2]))
        lapse = {"statues": "The monument is finished", "migration": "The herds move on"}.get(t, f"The {ev} ends")
        self.add("Court & festival", t, title, sid, f"{name}, near {near}.", self.area_state(sid), "",
                 f"When you settle accounts, gain 1 gold for each of your {trade} routes through {st}.",
                 pets, f"{lapse}: no effect.", deals, trade, src, 3)

    # ---------------------------------------------------------------- the slave trade
    def slaves(self):
        slave_deals = {d for d, t in self.trade_by_deal.items() if t == "Slaves" and d in self.routes}
        if not slave_deals:
            return
        traders = Counter()
        for d in slave_deals:
            for s in set(self.ends[d]):
                traders[s] += 1
        # a league: the largest state that trades no slaves, with its allies
        clean = [s for i, s in self.states.items() if i and i not in traders]
        best = None
        for s in sorted(clean, key=lambda s: -(s.get("cells") or 0)):
            allies = [j for j, rel in enumerate(s.get("diplomacy") or []) if rel == "Ally" and j in self.states and j]
            members = [s["i"]] + allies
            hit = {d for d in slave_deals if self.rstates[d] & set(members)}
            if hit and (best is None or len(hit) > len(best[2])):
                best = (s, members, hit)
        if best:
            s, members, hit = best
            sid = s["i"]
            names = [self.sname[x] for x in members]
            pets = [Petition(1, "Look away", "One of your Slaves routes is spared this round."),
                    Petition(3, "Manumission", "Discard one of your Slaves commissions and gain gold equal to its "
                                               "income. This is not a breach."),
                    Petition(5, "Oath of abolition", "Close your Slaves trade for good and open another trade with no "
                                                     "overhead. The league becomes law: keep this card face up; its "
                                                     "edict lasts the rest of the game.", False, 0, 1, True)]
            area = ("states", "Affected states" if len(members) > 1 else "Affected state",
                    _list(names) + ": every stop in " + ("these states" if len(members) > 1 else "the state"),
                    tuple(sorted(members)))
            self.add("Law", "league", f"The {s['name']} league against slavers", sid,
                     f"{s['name']} trades no slaves and presses its allies to close their roads to slavers.", area, "",
                     "When you settle accounts, discard each Slaves commission whose route passes through the affected "
                     "area. This is a breach.", pets, "The league breaks up: no effect.", hit, "Slaves", "slaves:league", 0)
        # a revolt where most slave routes run
        sid = max(traders, key=lambda s: (traders[s], s)) if traders else 0
        if sid:
            hit = {d for d in slave_deals if sid in self.rstates[d]}
            name = self.sname[sid]
            pets = [Petition(1, "Hire overseers", "Ignore this edict this round."),
                    Petition(3, "Free them", "Discard one of your Slaves commissions and gain 3 gold. This is not a "
                                             "breach."),
                    self.settle("Broker a settlement", "The decree ends. Keep this card.", sid, len(hit) / self.total)]
            self.add("Disorder", "revolt", f"Revolt in the slave pens of {name}", sid,
                     f"{name} has the busiest slave markets of the world, and the slaves have risen.",
                     self.area_state(sid), "",
                     f"When you settle accounts, pay 2 gold for each of your Slaves routes through {name}.", pets,
                     f"The revolt spreads: discard each Slaves commission whose route passes through {name}. This is a "
                     f"breach.", hit, "Slaves", "slaves:revolt", 0)

    # ---------------------------------------------------------------- selection
    def build(self, n: int = 30) -> tuple[list[Decree], dict]:
        self.wars()
        self.tariffs()
        self.theocracies()
        self.zones()
        self.markers()
        self.slaves()
        floor = max(4, round(0.01 * self.total))  # small sources must touch a few routes to be worth a card
        cands = [d for d in self.out if d.routes > 0 and (d.priority < 2 or d.routes >= floor)]
        # one card per kind and issuer on a state, and one card per link or stop area
        seen, uniq = set(), []
        for d in sorted(cands, key=lambda d: (d.priority, -d.routes)):
            if d.area_kind in ("state", "states"):
                k = (d.family if d.family == "Court & festival" else d.kind, d.area_key, d.issuer)
            else:
                k = d.area_key
            if k not in seen:
                seen.add(k)
                uniq.append(d)
        n_states = len([i for i in self.states if i])
        per_state = max(3, math.ceil(1.6 * n / max(1, n_states)))
        per_family = math.ceil(0.3 * n)
        per_type = 2
        chosen: list[Decree] = []
        cnt_s, cnt_f, cnt_t, cnt_deck = Counter(), Counter(), Counter(), Counter()

        def ok(d):
            return (cnt_s[d.issuer] < per_state and cnt_f[d.family] < per_family
                    and (cnt_t[d.kind] < per_type or d.priority == 0) and d not in chosen)

        def take(d):
            chosen.append(d)
            cnt_s[d.issuer] += 1
            cnt_f[d.family] += 1
            cnt_t[d.kind] += 1
            if d.deck:
                cnt_deck[d.deck] += 1

        def score(d):
            s = math.log1p(d.routes) - 0.6 * d.priority
            s -= 0.5 * cnt_deck[d.deck] if d.deck else 0
            s -= 0.4 * cnt_f[d.family]
            s -= 1.5 * max(0.0, d.share - 0.3)  # very wide decrees crowd out the rest
            return s + self.rng.random() * 0.3

        for d in [d for d in uniq if d.priority == 0][: max(1, n // 3)]:
            if ok(d):
                take(d)
        for sid in sorted(i for i in self.states if i):  # every state speaks at least once if it can
            if len(chosen) >= n or cnt_s[sid]:
                continue
            opts = [d for d in uniq if d.issuer == sid and ok(d)]
            if opts:
                take(max(opts, key=score))
        while len(chosen) < n:
            opts = [d for d in uniq if ok(d)]
            if not opts:
                break
            take(max(opts, key=score))
        self.rng.shuffle(chosen)
        for i, d in enumerate(chosen, 1):
            d.number = i
        stats = {"candidates": len(self.out), "with_routes": len(cands), "cards": len(chosen),
                 "families": dict(Counter(d.family for d in chosen)),
                 "issuers": {self.sname[s]: c for s, c in Counter(d.issuer for d in chosen).most_common()},
                 "decks_targeted": dict(Counter(d.deck for d in chosen if d.deck)),
                 "dropped_small": len(self.out) - len(cands),
                 "by_state_family": {sid: dict(Counter(d.family for d in cands if d.issuer == sid))
                                     for sid in sorted({d.issuer for d in cands})},
                 "treasury": {self.sname[s]: c for s, c in self.tclass.items()}}
        return chosen, stats


def build_decrees(net: Network, routes: dict, commissions: dict, n: int = 30, seed: int = 1):
    return DecreeBuilder(net, routes, commissions, seed).build(n)
