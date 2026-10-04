"""Journeys as plans: stages, timetable, what the track crosses and passes.

Journey data is the plan. What actually happens in play (detours, delays) is
recorded elsewhere (save files, ledger), never written back here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .clock import EQUINOX, PlanClock, latitude
from .geometry import locate_on_polyline
from .mapfile import AzgaarMap


@dataclass
class Stage:
    index: int
    name: str
    transport: str
    speed: float            # mph from the segment
    hours_per_day: float    # from the transport definition
    miles: float
    stay_hours: float
    points: list            # [x, y, cell]
    lat: float = 0.0        # latitude at the stage's first point
    start_t: float = 0.0    # plan hours since dawn of journey day 1
    end_t: float = 0.0

    @property
    def is_stay(self) -> bool:
        return self.speed == 0

    @property
    def travel_hours(self) -> float:
        return 0.0 if self.is_stay else self.miles / self.speed

    @property
    def travel_days(self) -> float:
        """Days of travel at this mode's hours per day (stays: days of stay)."""
        if self.is_stay:
            return self.stay_hours / 24
        return self.travel_hours / self.hours_per_day

    def cumulative_miles(self, mi_per_px: float) -> list[float]:
        run, out = 0.0, [0.0]
        for a, b in zip(self.points, self.points[1:]):
            run += math.dist(a[:2], b[:2]) * mi_per_px
            out.append(run)
        return out


@dataclass
class Crossing:
    stage: int
    mile: float
    kind: str        # state, province, culture, religion, river, zone
    before: str
    after: str
    cell: int


@dataclass
class Nearby:
    kind: str        # burg or marker
    id: int
    name: str
    subtype: str     # burg type or marker type
    stage: int
    along_mi: float
    offset_mi: float
    cell: int
    extra: dict = field(default_factory=dict)


class Journey:
    def __init__(self, m: AzgaarMap, index: int = 0, start_day_of_year: int = EQUINOX):
        self.m = m
        raw = m.data["journeys"][index]
        self.name, self.type = raw["name"], raw.get("type", "")
        scale = m.mi_per_px
        self.stages: list[Stage] = []
        for seg in raw["segments"]:
            t = m.transport(seg["transport"])
            self.stages.append(Stage(seg["i"], seg.get("name", f"Stage {seg['i']}"), seg["transport"],
                                     float(seg["speed"]), float(t["hoursPerDay"]) or 24.0,
                                     seg["distance"] * scale, float(seg.get("duration") or 0), seg["points"],
                                     latitude(m, seg["points"][0][1])))
        self.clock = PlanClock(self.stages[0].lat if self.stages else 0.0, start_day_of_year)
        t = 0.0
        for st in self.stages:
            st.start_t = t if st.is_stay else (t if st.hours_per_day >= 24 else self.clock.next_dawn(t, st.lat))
            t = st.start_t + st.stay_hours if st.is_stay else self.clock.travel(t, st.travel_hours,
                                                                                 st.hours_per_day, st.lat)
            st.end_t = t

    def when(self, stage: int, mile: float) -> float:
        """Plan time at a given mile of a stage."""
        st = self.stages[stage]
        if st.is_stay or st.miles == 0:
            return st.start_t
        return self.clock.travel(st.start_t, mile / st.speed, st.hours_per_day, st.lat)

    def label(self, t: float, lat: float | None = None) -> str:
        return self.clock.label(t, self.stages[0].lat if lat is None else lat)

    def alternatives(self, stage: int, allowed: list[str]) -> list[dict]:
        """Faster modes in the same domain, with days saved and a difficulty that scales with it."""
        st = self.stages[stage]
        if st.is_stay:
            return []
        domain = self.m.transport(st.transport)["domain"]
        plan_days = (st.end_t - st.start_t) / 24
        out = []
        for name in allowed:
            try:
                tr = self.m.transport(name)
            except KeyError:
                continue
            if tr["domain"] != domain or name == st.transport or tr["speed"] <= 0:
                continue
            hpd = float(tr["hoursPerDay"]) or 24.0
            days = st.miles / tr["speed"] / hpd
            saved = plan_days - days
            if saved <= 0:
                continue
            share = saved / plan_days
            level = ("light" if share < 0.25 else "moderate" if share < 0.5 else
                     "hard" if share < 0.75 else "severe")
            out.append({"transport": name, "days": days, "saved": saved, "difficulty": round(share, 2),
                        "level": level})
        return sorted(out, key=lambda a: a["days"])

    @property
    def total_days(self) -> float:
        return self.stages[-1].end_t / 24 if self.stages else 0.0

    def moving(self) -> list[Stage]:
        return [s for s in self.stages if not s.is_stay]

    # ---------------------------------------------------------------- crossings
    def crossings(self) -> list[Crossing]:
        m, out = self.m, []
        names = {
            "state": lambda i: m.state(i).get("name", str(i)),
            "province": lambda i: (m.data["provinces"][i] or {}).get("name", "none") if i else "none",
            "culture": lambda i: m.culture(i).get("name", str(i)),
            "religion": lambda i: m.religion(i).get("name", str(i)),
            "river": lambda i: next((r["name"] for r in m.live("rivers") if r["i"] == i), "none") if i else "none",
        }
        zone_cells = [(z, set(z["cells"])) for z in m.live("zones")]
        for st in self.moving():
            miles = st.cumulative_miles(m.mi_per_px)
            prev = None
            for k, p in enumerate(st.points):
                cell = p[2]
                now = {key: m.cell(key)[cell] for key in names}
                now["zone"] = tuple(z["i"] for z, cells in zone_cells if cell in cells)
                if prev:
                    for key, fn in names.items():
                        if now[key] != prev[key]:
                            out.append(Crossing(st.index, miles[k], key, fn(prev[key]), fn(now[key]), cell))
                    if now["zone"] != prev["zone"]:
                        label = lambda ids: ", ".join(m.data["zones"][i]["name"] for i in ids) or "none"
                        out.append(Crossing(st.index, miles[k], "zone", label(prev["zone"]), label(now["zone"]), cell))
                prev = now
        return out

    # ------------------------------------------------------------------- nearby
    def nearby(self, width_mi: float) -> list[Nearby]:
        """Burgs and markers within width_mi of a moving stage, nearest stage wins."""
        m, scale, best = self.m, self.m.mi_per_px, {}
        cands = [("burg", b["i"], b["name"], b.get("type", ""), (b["x"], b["y"]), b["cell"], b)
                 for b in m.live_burgs()]
        cands += [("marker", mk["i"], mk.get("name", ""), mk["type"], (mk["x"], mk["y"]), mk["cell"], mk)
                  for mk in m.live("markers")]
        for kind, i, name, sub, xy, cell, rec in cands:
            for st in self.moving():
                offset, along = locate_on_polyline(xy, st.points)
                offset, along = offset * scale, along * scale
                if offset <= width_mi and ((kind, i) not in best or offset < best[(kind, i)].offset_mi):
                    best[(kind, i)] = Nearby(kind, i, name, sub, st.index, along, offset, cell, rec)
        return sorted(best.values(), key=lambda n: (n.stage, n.along_mi))

    def endpoints(self) -> dict[int, list[int]]:
        """Cells where the journey starts, stops or stays, with the stage indexes."""
        out: dict[int, list[int]] = {}
        for st in self.stages:
            for cell in {st.points[0][2], st.points[-1][2]}:
                out.setdefault(cell, []).append(st.index)
        return out
