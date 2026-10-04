"""The story framework.

A Storyline is a sequence of Phases. Each phase has an objective, triggers that complete it,
optional requirements (flags set by any storyline), a position on the journey (stage, mile)
and an optional deadline in plan hours. Elements are the things a storyline needs in the
world (people, items, clues), each anchored to a place (a burg, a marker, a scene) or carried.
Scenes ask the state for the elements anchored to them; the game reports events; the state
completes phases, awards points (Zork style), sets flags that other storylines can require,
and ends the story when a phase says so.

Phases are visited in order. A phase that lies behind the party's position on the journey and
is not required is marked missed when the party passes it: you can stop, or pass on by.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Element:
    role: str
    kind: str                  # person, item, clue
    spec: dict                 # thing spec for World.spawn
    anchor: dict               # {"burg": id} | {"marker": id} | {"scene": id} | {"carried": true}; "prefer": [room purposes]
    placed: bool = False


@dataclass
class Phase:
    id: str
    title: str
    objective: str
    text: str = ""                                     # shown when the phase completes
    triggers: list[dict] = field(default_factory=list)  # {"kind": ..., ...}
    mode: str = "all"                                  # all or any
    requires: list[list[str]] = field(default_factory=list)  # any-of groups of flags, all groups needed
    points: int = 10
    pos: list | None = None                            # [stage, mile] on the journey
    required: bool = False                             # cannot be missed by passing
    deadline_t: float | None = None
    on_miss: str = ""
    effects: dict = field(default_factory=dict)        # flags, give (roles), delay_hours, end
    status: str = "open"                               # open, done, missed
    satisfied: list[int] = field(default_factory=list)


@dataclass
class Storyline:
    id: str
    title: str
    kind: str                                          # main, lead, side
    summary: str
    phases: list[Phase]
    elements: dict[str, Element] = field(default_factory=dict)
    status: str = "active"                             # active, done, failed

    def thing_id(self, role: str) -> str:
        return f"story:{self.id}:{role}"

    @property
    def current(self) -> Phase | None:
        return next((p for p in self.phases if p.status == "open"), None)

    @property
    def next_task(self) -> Phase | None:
        """The next open phase that asks something of the player (not just passing a place)."""
        return next((p for p in self.phases if p.status == "open" and
                     not all(t["kind"] == "pass" for t in p.triggers)), None)


def _after(pos_a, pos_b) -> bool:
    """True if pos_a is at or beyond pos_b on the journey."""
    return pos_b is not None and (pos_a[0] > pos_b[0] or (pos_a[0] == pos_b[0] and pos_a[1] >= pos_b[1]))


class StoryState:
    def __init__(self):
        self.storylines: list[Storyline] = []
        self.flags: dict = {}
        self.score = 0
        self.ending: dict | None = None    # {"kind": success|failure, "text": ...}
        self.log: list[str] = []
        self.pending_gifts: list[dict] = []  # specs the game should hand to the player
        self.delay_change = 0.0

    # ---------------------------------------------------------------- queries
    def line(self, sid: str) -> Storyline | None:
        return next((s for s in self.storylines if s.id == sid), None)

    @property
    def max_score(self) -> int:
        return sum(p.points for s in self.storylines for p in s.phases)

    def objectives(self) -> list[str]:
        out = []
        for s in self.storylines:
            p = s.next_task if s.status == "active" else None
            known = s.kind == "main" or any(ph.status == "done" for ph in s.phases)
            if p and known:
                out.append(f"{s.title}: {p.objective}")
        return out

    def elements_for(self, burg: int | None = None, marker: int | None = None, scene: str | None = None) -> list[tuple[Storyline, Element]]:
        out = []
        for s in self.storylines:
            if s.status == "failed":
                continue
            for e in s.elements.values():
                a = e.anchor
                if e.placed or a.get("carried"):
                    continue
                if (burg is not None and a.get("burg") == burg) or (marker is not None and a.get("marker") == marker) \
                        or (scene and a.get("scene") == scene):
                    out.append((s, e))
        return out

    # ----------------------------------------------------------------- events
    def notify(self, event: dict) -> list[str]:
        msgs: list[str] = []
        if event.get("type") == "pass":
            msgs += self._pass(event["pos"])
        if event.get("type") == "time":
            msgs += self._deadlines(event["t"])
        progressed = True
        while progressed and not self.ending:
            progressed = False
            for s in self.storylines:
                p = s.current if s.status == "active" else None
                if not p or not self._requirements(p):
                    continue
                for k, trig in enumerate(p.triggers):
                    if k not in p.satisfied and self._matches(trig, event, s):
                        p.satisfied.append(k)
                done = (p.mode == "any" and p.satisfied) or (p.mode == "all" and len(p.satisfied) == len(p.triggers))
                if done:
                    msgs.append(self._complete(s, p))
                    progressed = True
                    if event.get("type") not in ("pass", "enter", "time", "start"):
                        event = {"type": "none"}  # an action counts once; places and time keep applying
        return [m for m in msgs if m]

    def _requirements(self, p: Phase) -> bool:
        return all(any(self.flags.get(f) for f in group) for group in p.requires)

    def _matches(self, trig: dict, ev: dict, s: Storyline) -> bool:
        kind = trig["kind"]

        def tid(key: str):
            value = trig.get(key)
            return s.thing_id(value) if value in s.elements else value
        if kind == "start":
            return ev.get("type") in ("start", "none", "enter")
        if kind == "flag":
            return bool(self.flags.get(trig["name"]))
        if kind == "pass":
            return ev.get("type") == "pass" and _after(ev["pos"], trig["pos"])
        if kind == "at":
            if ev.get("type") != "enter":
                return False
            return any(trig.get(k) is not None and ev.get(k) == trig.get(k) for k in ("burg", "marker", "scene")) and \
                (not trig.get("purpose") or ev.get("purpose") in trig["purpose"])
        if kind == "have":
            return tid("item") in (ev.get("carried") or [])
        if kind in ("talk", "examine", "read", "take"):
            key = "item" if kind in ("read", "take") else "thing"
            return ev.get("type") == kind and ev.get(key) == tid(key)
        if kind == "ask":
            return ev.get("type") == "ask" and ev.get("thing") == tid("thing") and \
                (not trig.get("topic") or bool(set(trig["topic"]) & set(ev.get("topic") or [])))
        if kind == "give":
            return ev.get("type") == "give" and ev.get("item") == tid("item") and \
                (not trig.get("to") or ev.get("to") == tid("to"))
        return False

    def _complete(self, s: Storyline, p: Phase) -> str:
        p.status = "done"
        self.score += p.points
        fx = p.effects
        self.flags.update(fx.get("flags", {}))
        self.flags[f"story:{s.id}:{p.id}"] = True
        for role in fx.get("give", []):
            e = s.elements[role]
            spec = dict(e.spec, id=s.thing_id(role))
            self.pending_gifts.append(spec)
            e.placed = True
        self.delay_change += fx.get("delay_hours", 0)
        lines = [f"*** {p.title} ***", p.text] if p.text else [f"*** {p.title} ***"]
        if p.points:
            lines.append(f"[Your score has gone up by {p.points}.]")
        if fx.get("end"):
            self.ending = {"kind": fx["end"], "text": fx.get("end_text", "")}
            s.status = "done" if fx["end"] == "success" else "failed"
        elif s.current is None:
            s.status = "done"
        nxt = s.next_task
        if nxt and s.status == "active" and nxt.id != p.id:
            lines.append(f"({s.title}: {nxt.objective})")
        self.log.append(p.title)
        return "\n".join(x for x in lines if x)

    def _pass(self, pos) -> list[str]:
        out = []
        for s in self.storylines:
            for p in s.phases:
                if p.status != "open" or p.pos is None or p.required:
                    continue
                passive = all(t["kind"] == "pass" for t in p.triggers)
                if _after(pos, p.pos) and not passive and pos != p.pos and \
                        (pos[0] > p.pos[0] or pos[1] - p.pos[1] > 15):
                    p.status = "missed"
                    if p.on_miss:
                        out.append(p.on_miss)
        return out

    def _deadlines(self, t: float) -> list[str]:
        out = []
        for s in self.storylines:
            p = next((ph for ph in s.phases if ph.status == "open" and ph.deadline_t is not None and t > ph.deadline_t),
                     None) if s.status == "active" else None
            if p:
                p.status = "missed"
                s.status = "failed"
                out.append(p.on_miss or f"{s.title}: too late.")
                if s.kind == "main":
                    self.ending = {"kind": "failure", "text": p.on_miss}
        return out

    # ---------------------------------------------------------- persistence
    def to_json(self) -> dict:
        return {"storylines": [asdict(s) for s in self.storylines], "flags": self.flags, "score": self.score,
                "ending": self.ending, "log": self.log, "pending_gifts": self.pending_gifts}

    @classmethod
    def from_json(cls, d: dict) -> "StoryState":
        st = cls()
        for s in d["storylines"]:
            phases = [Phase(**p) for p in s["phases"]]
            elements = {k: Element(**e) for k, e in s["elements"].items()}
            st.storylines.append(Storyline(s["id"], s["title"], s["kind"], s["summary"], phases, elements, s["status"]))
        st.flags, st.score, st.ending = d["flags"], d["score"], d["ending"]
        st.log, st.pending_gifts = d.get("log", []), d.get("pending_gifts", [])
        return st
