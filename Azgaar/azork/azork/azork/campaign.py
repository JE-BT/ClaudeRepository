"""A campaign: one playthrough of a world's journey, kept between scenes.

Holds the story state, the party's clock (plan hours since dawn of day 1) and position on the
journey (stage, mile), and what the party carries. Between scenes the party follows the plan's
own pace, so lost time stays lost: the delay is the actual clock minus the plan's time for
the same place. Going back along the road costs the time it takes.
Saved as saves/<World>-<name>.json beside the azork package.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import setup
from .journey import Journey
from .story import arc
from .story.model import StoryState

SAVE_DIR = Path(__file__).resolve().parents[1] / "saves"


class Campaign:
    def __init__(self, files, name: str = "campaign", save_dir: Path | None = None):
        self.files, self.name = files, name
        self.save_dir = Path(save_dir) if save_dir else SAVE_DIR
        self.cfg = setup.world_settings(files)
        self.journey = Journey(files.map, 0, self.cfg["start_day_of_year"])
        self.story = StoryState()
        self.tokens: dict = {}
        self.t = 0.0
        self.pos = [0, 0.0]
        self.inventory: list[dict] | None = None
        self.visited: list[str] = []
        self.scene: str | None = None
        self.speed: dict[str, float] = {}       # stage index -> time factor for booked faster passage
        self.policy: str = "ask"                # dwellings: ask or generate
        self.generated: list[int] = []          # burgs where the player chose made-up interiors
        self._crossings = None
        self.hex: str | None = None             # the party's hex on the road
        self.arrive: str | None = None          # the side of town the party arrives from
        self._wild = None

    @property
    def crossings(self):
        if self._crossings is None:
            self._crossings = self.journey.crossings()
        return self._crossings

    def segment_hours(self, a, b) -> float:
        """Plan time between two positions, scaled by any faster passage booked per stage."""
        lo, hi = sorted([a, b], key=lambda p: (p[0], p[1]))
        total = 0.0
        for st in self.journey.stages[lo[0]:hi[0] + 1]:
            s0 = lo[1] if st.index == lo[0] else 0
            s1 = hi[1] if st.index == hi[0] else (st.miles if not st.is_stay else 0)
            t0, t1 = self.journey.when(st.index, max(s0, 0)), self.journey.when(st.index, max(s1, 0))
            if st.index != hi[0]:
                t1 = st.end_t
            total += (t1 - t0) * self.speed.get(str(st.index), 1.0)
        return max(total, 0.0)

    @property
    def path(self) -> Path:
        return self.save_dir / f"{self.files.name}-{self.name}.json"

    # ------------------------------------------------------------- lifecycle
    @classmethod
    def new(cls, files, name: str = "campaign", save_dir: Path | None = None) -> tuple["Campaign", list[str]]:
        c = cls(files, name, save_dir)
        overlay_path = files.content_dir / "story.json"
        overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.exists() else {}
        c.story, c.tokens = arc.build(files, c.journey, c.cfg, overlay)
        c.story.flags["overlay_topics"] = overlay.get("topics", {})
        msgs = c.story.notify({"type": "start"})
        return c, msgs

    @classmethod
    def load(cls, files, name: str = "campaign", save_dir: Path | None = None) -> "Campaign | None":
        c = cls(files, name, save_dir)
        if not c.path.exists():
            return None
        d = json.loads(c.path.read_text(encoding="utf-8"))
        c.story = StoryState.from_json(d["story"])
        c.tokens, c.t, c.pos = d["tokens"], d["t"], d["pos"]
        c.inventory, c.visited = d.get("inventory"), d.get("visited", [])
        c.speed, c.policy, c.generated = d.get("speed", {}), d.get("policy", "ask"), d.get("generated", [])
        c.hex = d.get("hex")
        return c

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"world": self.files.name, "tokens": self.tokens, "t": self.t, "pos": self.pos,
                                         "inventory": self.inventory, "visited": self.visited,
                                         "speed": self.speed, "policy": self.policy, "generated": self.generated, "hex": self.hex,
                                         "story": self.story.to_json()}, indent=1), encoding="utf-8")
        return self.path

    def leave(self, world) -> None:
        """Back to the road from a scene: the clock, what is carried, and where you have been."""
        from .engine.model import _spec
        self.t = world.plan_t + world.flags.get("offset_h", 0)
        carried = world.carried()
        self.inventory = [dict(_spec(t), id=t.id) for t in carried if t.location == "player"]
        for t in carried:
            if t.location != "player":
                parent = next(x for x in self.inventory if x["id"] == t.location) if any(
                    x["id"] == t.location for x in self.inventory) else None
                if parent is not None:
                    parent.setdefault("contents", []).append(dict(_spec(t), id=t.id))
        if world.scene not in self.visited:
            self.visited.append(world.scene)

    # ---------------------------------------------------------------- travel
    def plan_t(self, pos) -> float:
        return self.journey.when(pos[0], max(pos[1], 0))

    def delay(self, now: float | None = None, pos=None) -> float:
        """Hours behind the plan at a position (negative: ahead)."""
        return (self.t if now is None else now) - self.plan_t(pos or self.pos)

    def travel_to(self, pos, offset_hours: float = 0.0) -> tuple[float, list[str]]:
        """Move along the road to pos; returns the arrival time and story messages."""
        self.t += self.segment_hours(self.pos, pos) + offset_hours
        forward = (pos[0], pos[1]) >= (self.pos[0], self.pos[1])
        self.pos = [pos[0], pos[1]] if forward else self.pos
        msgs = self.story.notify({"type": "pass", "pos": self.pos}) if forward else \
            ["You go back along the road. The time is lost."]
        msgs += self.story.notify({"type": "time", "t": self.t})
        if self.story.delay_change:
            self.t += self.story.delay_change
            self.story.delay_change = 0.0
        return self.t, msgs

    def schedule(self, now: float, pos=None, label=None) -> str:
        pos = pos or self.pos
        late = self.delay(now, pos)
        state = "on the plan" if abs(late) < 1 else f"{abs(late):.0f} hours {'behind' if late > 0 else 'ahead of'} the plan"
        nxt = next((st for st in self.journey.stages if st.is_stay and self.plan_t([st.index, 0]) > self.plan_t(pos)), None)
        lines = [f"You are {state}."]
        if nxt and label:
            due = self.plan_t([nxt.index, 0])
            lines.append(f"The plan has you at \"{nxt.name}\" by {label(due)}; at this pace, {label(due + max(late, 0))}.")
        main = self.story.line("main")
        climax = next((p for p in main.phases if p.deadline_t), None) if main else None
        if climax and label:
            end = self.plan_t([self.journey.stages[-1].index, self.journey.stages[-1].miles]) + max(late, 0)
            spare = climax.deadline_t - end
            lines.append(f"The deadline is {label(climax.deadline_t)}: "
                         f"{'about ' + str(round(spare / 24)) + ' days to spare' if spare > 0 else 'you will be too late unless you make up time'}.")
        return " ".join(lines)
