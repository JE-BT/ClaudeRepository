"""The game: resolves parsed commands against the world and produces text."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .interact import Interactions
from .model import DIRECTIONS, Thing, World
from .parser import Command, parse, split_commands

MINUTES = {"go": 1, "wait": 10, "search": 5, "raise": 10, "lower": 2, "take": 0.5, "drop": 0.5, "put": 0.5,
           "takeout": 0.5, "open": 0.5, "close": 0.5, "unlock": 1, "lock": 1, "light": 1, "extinguish": 0.2,
           "read": 2, "examine": 0.5, "lookin": 0.5, "talk": 2}
META = {"undo", "save", "restore", "quit", "again", "help", "time", "status", "inventory", "look", "weigh", "journal",
        "score", "goals", "schedule", "recap", "route"}
PORTABLE_PARTS = {"cup", "cups", "mug", "mugs", "book", "books", "notice", "notices", "paper", "papers", "bottle", "bottles",
                  "candle", "candles", "jar", "jars", "stone", "stones", "bone", "bones", "poker", "plate", "plates",
                  "shell", "shells", "rag", "rags", "spoon", "spoons", "ledger", "ledgers", "scroll", "scrolls",
                  "apple", "apples", "fish", "pebble", "pebbles", "feather", "feathers", "nail", "nails"}
HUNGER_H, THIRST_H = 10, 6
THIRST_DEATH_H, HUNGER_DEATH_H = 72, 21 * 24
DEATH = "\n    *** You have died ***\nType UNDO to take back the last move, RESTORE to load a saved game, or QUIT."


def wrap(text: str) -> str:
    return "\n".join(textwrap.fill(p, 78) if p.strip() else "" for p in text.split("\n"))


class Game(Interactions):
    def __init__(self, world: World, save_dir: str | Path | None = None, campaign=None):
        self.w = world
        self.campaign = campaign
        self.building_policy = "generate"
        self.story = campaign.story if campaign is not None else None
        self.extra_minutes = 0.0
        self.w.flags.setdefault("last_meal", self.w.plan_t)
        self.w.flags.setdefault("last_drink", self.w.plan_t)
        self.save_dir = Path(save_dir) if save_dir else None
        self.undo_stack: list[dict] = []
        self.last_line: str | None = None
        self.it: str | None = None
        self.pending: tuple[Command, list[Thing]] | None = None
        self.quit_requested = False
        self.log: list[tuple[str, str]] = []   # (command, output) for the transcript and ledger export

    # ------------------------------------------------------------------ driver
    def intro(self) -> str:
        head = wrap(f"{self.w.flags.get('title', self.w.scene)}\n{self.w.time_label()}\n\n")
        before = "\n".join(wrap(m) for m in self.w.flags.pop("arrival_msgs", []) if m)
        body = self.describe(True)
        after = self.story_event({"type": "enter"})
        return "\n\n".join(x for x in (head.strip(), before, body, after) if x)

    # ----------------------------------------------------------------- story
    def story_event(self, ev: dict, thing: Thing | None = None) -> str:
        if not self.story:
            return ""
        self.story.clock_label = lambda t: self.w.clock.label(t, self.w.lat) if self.w.clock else ""
        self.story.now = self.w.plan_t
        if ev["type"] == "enter":
            ev.update(self.w.flags.get("anchor", {}))
            ev["scene"] = self.w.scene
            ev["purpose"] = self.w.rooms[self.w.player].purpose
            ev["carried"] = [t.id for t in self.w.carried()]
        msgs = self.story.notify(ev)
        if thing is not None and self.campaign is not None:
            from ..story import side
            ctx = {"files": self.campaign.files, "journey": self.campaign.journey, "pos": self.campaign.pos,
                   "seed": self.w.seed, "sites": self.w.flags.get("sites", {}),
                   "corridor_mi": self.campaign.cfg.get("corridor_mi", 40),
                   "scene_burgs": {f.burg for f in self.campaign.files.dwellings() if f.burg is not None}}
            msgs += side.maybe_hook(self.story, ev, thing, ctx)
        for spec in self.story.pending_gifts:
            if spec["id"] not in self.w.things:
                self.w.spawn(spec, "player", spec["id"])
            else:
                self.w.things[spec["id"]].location = "player"
        self.story.pending_gifts.clear()
        if self.story.delay_change:
            self.w.minutes -= self.story.delay_change * 60  # time saved shows on the clock
            self.story.delay_change = 0.0
        if self.story.ending and not self.w.flags.get("ended"):
            self.w.flags["ended"] = True
            msgs.append(f"\n{self.story.ending.get('text', '')}\n\n    *** The End ***\n" + self._score_line())
            self.quit_requested = True
        return "\n".join(wrap(m) for m in msgs if m)

    def _score_line(self) -> str:
        if not self.story:
            return ""
        return f"Your score is {self.story.score} of a possible {self.story.max_score}, in {self.w.moves} moves."

    def do_score(self, cmd):
        return self._score_line() or "There is no story running. Start one with: python -m azork new <World>"

    def do_goals(self, cmd):
        if not self.story:
            return "You have no goals but the road. (Start a story with: python -m azork new <World>)"
        goals = self.story.objectives()
        return "\n".join(goals) if goals else "Nothing is asked of you just now."

    def do_schedule(self, cmd):
        if self.campaign is None:
            plan = self.w.start_t
            late = self.w.plan_t - plan
            return (f"The plan has you passing here at {self.w.time_label() if False else self.w.clock.label(plan, self.w.lat)}. "
                    f"You have spent {late:.1f} hours here, all of it behind the plan.")
        here_plan = self.campaign.plan_t(self.w.flags.get("pos", self.campaign.pos))
        offset = self.w.flags.get("offset_h", 0)
        return self.campaign.schedule(self.w.plan_t - offset, self.w.flags.get("pos"),
                                      lambda t: self.w.clock.label(t, self.w.lat))

    def step(self, line: str) -> str:
        line = line.strip()
        if not line:
            return "Beg pardon?"
        if self.pending:
            out = self._resolve_pending(line)
            if out is not None:
                return out
        outputs = []
        for part in split_commands(line):
            cmd = parse(part)
            if cmd is None:
                continue
            if cmd.verb == "again":
                if not self.last_line:
                    outputs.append("There is nothing to repeat.")
                    continue
                cmd = parse(self.last_line)
            elif cmd.verb not in META:
                self.last_line = part
            outputs.append(self.run(cmd))
            if self.w.dead or self.quit_requested or self.pending:
                break
        text = "\n".join(o for o in outputs if o)
        self.log.append((line, text))
        return text

    def run(self, cmd: Command) -> str:
        if self.w.dead and cmd.verb not in ("undo", "restore", "quit", "help"):
            return "You are dead. Type UNDO, RESTORE or QUIT."
        if cmd.verb not in META:
            self.undo_stack.append(self.w.state())
            self.undo_stack = self.undo_stack[-50:]
        handler = getattr(self, f"do_{cmd.verb}", None)
        if handler is None:
            return "I don't know that verb." if cmd.verb == "unknown" else f"You can't {cmd.verb} here."
        self.extra_minutes = 0.0
        out = handler(cmd)
        if cmd.verb not in META and not self.w.dead:
            self.w.moves += 1
            out = "\n".join(x for x in (out, self.tick(MINUTES.get(cmd.verb, 1) + self.extra_minutes)) if x)
        return out

    def wrap_text(self, text: str) -> str:
        return wrap(text)

    def tick(self, minutes: float) -> str:
        self.w.minutes += minutes
        notes = []
        for t in self.w.things.values():
            if "lit" in t.flags and "fuel" in t.props:
                before = t.props["fuel"]
                t.props["fuel"] = max(0.0, before - minutes)
                if t.props["fuel"] == 0:
                    t.flags.discard("lit")
                    if self._near(t):
                        notes.append(f"The {t.name} sputters and goes out.")
                elif self._near(t):
                    for warn in (30, 10):
                        if before > warn >= t.props["fuel"]:
                            notes.append(f"The {t.name} is burning low.")
        f = self.w.flags
        if not self.w.dead:
            if self.w.plan_t - f.get("last_drink", self.w.plan_t) > THIRST_DEATH_H:
                self.w.dead = True
                return "Your legs fold under you. Three days without water is as far as anyone goes." + DEATH
            if self.w.plan_t - f.get("last_meal", self.w.plan_t) > HUNGER_DEATH_H:
                self.w.dead = True
                return "Hunger finishes what the road began." + DEATH
        for key, limit, text in (("last_meal", HUNGER_H, "Your stomach reminds you that you haven't eaten."),
                                 ("last_drink", THIRST_H, "Your mouth is dry; you should drink something.")):
            due = f.get(key, self.w.plan_t) + limit
            warned = f.get(f"warned:{key}", 0)
            if self.w.plan_t >= due and self.w.plan_t - warned >= 3:
                f[f"warned:{key}"] = self.w.plan_t
                notes.append(text)
        return " ".join(notes)

    # ------------------------------------------------------------- perception
    def _near(self, t: Thing) -> bool:
        return t.location == self.w.player or t in self.w.carried()

    def dark(self) -> bool:
        room = self.w.rooms[self.w.player]
        if room.dark == "never" or (room.dark == "night" and not self.w.is_night()):
            return False
        lights = self.w.carried() + self.w.contents(self.w.player)
        return not any("lit" in t.flags for t in lights)

    def visible(self) -> list[Thing]:
        out = list(self.w.carried())
        if self.dark():
            return out
        todo = [t for t in self.w.contents(self.w.player) if "hidden" not in t.flags]
        while todo:
            t = todo.pop(0)
            out.append(t)
            if "container" in t.flags and ("open" in t.flags or "openable" not in t.flags):
                todo += [c for c in self.w.contents(t.id) if "hidden" not in c.flags]
        out += [d for d in self.w.doors_here(self.w.player) if "hidden" not in d.flags]
        return out

    def describe(self, full: bool = False) -> str:
        room = self.w.rooms[self.w.player]
        if self.dark():
            return wrap(f"{room.name}\nIt is pitch dark. You can't see a thing.")
        lines = [room.name]
        if full or not room.visited:
            lines.append(room.description)
            exits = []
            for d in DIRECTIONS:
                e = room.exits.get(d)
                if d in ("in", "out") and e and any(x.to == e.to for k, x in room.exits.items() if k not in ("in", "out")):
                    continue  # same way as a compass exit already listed
                if e and not e.hidden:
                    label = d
                    if e.door:
                        door = self.w.things[e.door]
                        state = ("barred " if "barred" in door.flags else
                                 "lowered " if "portcullis" in door.flags and "raised" not in door.flags else
                                 "open " if "open" in door.flags else "closed ")
                        label += f" ({'' if state.strip() in door.name else state}{door.name})"
                    elif e.note:
                        label += f" ({e.note})"
                    exits.append(label)
            for d, e in room.exits.items():
                if d not in DIRECTIONS and not e.hidden and e.to != "__exit__":
                    target = self.w.rooms.get(e.to)
                    exits.append(f"{d} ({target.area if target and target.area != room.area else target.name if target else e.note or d})")
            if exits:
                lines.append("Exits: " + ", ".join(exits) + ".")
        room.visited = True
        for t in self.w.contents(self.w.player):
            if "hidden" in t.flags:
                continue
            if "moved" not in t.flags and t.props.get("initial"):
                lines.append(t.props["initial"])
            elif t.props.get("here") and ("moved" not in t.flags or {"scenery", "person", "creature"} & t.flags):
                lines.append(t.props["here"])
            elif not ({"scenery"} & t.flags):
                lines.append(f"There is {t.article_name} here.")
            if "person" in t.flags and self.w.flags.get("barged") and t.props.get("barge") and not t.props.get("barge_said"):
                t.props["barge_said"] = True
                lines.append(t.props["barge"])
        return wrap("\n".join(lines))

    # --------------------------------------------------------------- matching
    def match(self, words: list[str], pool: list[Thing]) -> list[Thing]:
        if words == ["it"] and self.it:
            return [t for t in pool if t.id == self.it]
        hits = []
        for t in pool:
            vocab = set(t.nouns) | set(t.adjectives) | set(t.name.lower().split())
            if words and words[-1] in set(t.nouns) | set(t.name.lower().split()[-1:]) and all(w in vocab for w in words):
                hits.append(t)
        exact = [t for t in hits if " ".join(words) == t.name.lower()]
        return exact or hits

    def resolve(self, cmd: Command, words: list[str], pool: list[Thing] | None = None) -> Thing | str:
        if not words:
            return f"What do you want to {cmd.raw.split()[0] if cmd.raw else cmd.verb}?"
        hits = self.match(words, self.visible() if pool is None else pool)
        if not hits and pool is None and not self.dark():
            detail = self._detail(words)
            if detail:
                hits = [detail]
        if not hits:
            return "It's too dark to find anything." if self.dark() else f"You can't see any {' '.join(words)} here."
        if len(hits) > 1:
            self.pending = (cmd, hits)
            names = [f"the {t.name}" for t in hits]
            return "Which do you mean, " + ", ".join(names[:-1]) + " or " + names[-1] + "?"
        self.it = hits[0].id
        return hits[0]

    def _detail(self, words: list[str]) -> Thing | None:
        """Something mentioned in what you can see (cups ringing a bar, books on shelves) becomes a thing."""
        import re as _re
        noun = words[-1]
        room = self.w.rooms[self.w.player]
        sources = [(room.description, None)] + [(t.props.get("here") or t.props.get("initial") or t.description, t)
                                                for t in self.w.contents(self.w.player) if "hidden" not in t.flags]
        for text, parent in sources:
            if text and _re.search(rf"\b{_re.escape(noun)}\b", text.lower()):
                singular = noun[:-1] if noun.endswith("s") and noun[:-1] in PORTABLE_PARTS else noun
                where = f"part of the {parent.name}" if parent else "part of the place"
                spec = {"name": noun, "nouns": [noun, singular], "flags": ["scenery", "detail"],
                        "description": f"You look closer at the {noun}: {where}, nothing more.", "provenance": "new"}
                if noun in PORTABLE_PARTS:
                    spec["props_portable"] = singular
                t = self.w.spawn(spec, self.w.player)
                if noun in PORTABLE_PARTS:
                    t.props["portable"] = singular
                return t
        return None

    def _resolve_pending(self, line: str) -> str | None:
        cmd, hits = self.pending
        self.pending = None
        words = [w for w in line.lower().split() if w not in ("the", "a", "an")]
        chosen = [t for t in hits if all(w in set(t.nouns) | set(t.adjectives) | set(t.name.lower().split())
                                         for w in words)]
        if len(chosen) != 1:
            return None
        self.it = chosen[0].id
        cmd.words = chosen[0].name.lower().split()
        return self.run(cmd)

    # ----------------------------------------------------------------- verbs
    def do_look(self, cmd):
        return self.describe(True)

    def do_examine(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if (h := self._hazard(t, "examine")) is not None:
            return h
        spec = self.act(t, "examine")
        if spec:
            return spec
        story = self.story_event({"type": "examine", "thing": t.id}, t)
        parts = [t.description or t.props.get("here") or f"You see nothing special about the {t.name}."]
        if "door" in t.flags:
            parts.append(self._door_state(t))
        if "container" in t.flags and ("open" in t.flags or "openable" not in t.flags):
            inside = self.w.contents(t.id)
            parts.append(f"The {t.name} contains " + _list(inside) + "." if inside else f"The {t.name} is empty.")
        if "light" in t.flags:
            parts.append(f"It is {'lit' if 'lit' in t.flags else 'unlit'}" +
                         (f", with about {t.props['fuel'] / 60:.1f} hours of fuel." if "fuel" in t.props else "."))
        if t.props.get("hint"):
            parts.append(t.props["hint"])
        return wrap(" ".join(parts)) + (("\n" + story) if story else "")

    def do_lookin(self, cmd):
        t = self.resolve(cmd, cmd.words or cmd.iwords)
        if isinstance(t, str):
            return t
        if (h := self._hazard(t, "lookin")) is not None:
            return h
        spec = self.act(t, "lookin")
        if spec:
            return spec
        if "container" in t.flags:
            return self.do_examine(cmd)
        return f"You see nothing unusual in the {t.name}."

    def do_read(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        story = self.story_event({"type": "read", "item": t.id}, t)
        text = wrap(t.text) if t.text else f"There is nothing written on the {t.name}."
        return text + (("\n" + story) if story else "")

    def do_inventory(self, cmd):
        top = self.w.contents("player")
        if not top:
            return "You are empty-handed."
        lines = ["You are carrying:"]

        def walk(things, depth):
            for t in things:
                lines.append(f"{'  ' * depth}  {t.name:<32} {t.weight:5.1f} kg" + (" (lit)" if "lit" in t.flags else ""))
                walk(self.w.contents(t.id), depth + 1)
        walk(top, 0)
        w, L = self.w.carried_weight(), self.w.load
        lines.append(f"Total {w:.1f} kg: travelling {self.w.load_status()} "
                     f"(light up to {L['light_kg']:g} kg, limit {L['max_kg']:g} kg).")
        return "\n".join(lines)

    def do_take(self, cmd):
        pool = [t for t in self.visible() if t.location != "player"]
        if cmd.all:
            cands = [t for t in pool if "takeable" in t.flags and t.location == self.w.player
                     and not self.match(cmd.except_words, [t])]
            if not cands:
                return "There is nothing here to take."
            return "\n".join(f"{t.name}: {self._take(t)}" for t in cands)
        t = self.resolve(cmd, cmd.words, pool if cmd.prep != "from" else None)
        return t if isinstance(t, str) else self._take(t)

    def _take(self, t: Thing) -> str:
        if t.location == "player":
            return "You already have that."
        if "person" in t.flags:
            return f"The {t.name} would object."
        if "detail" in t.flags and t.props.get("portable"):
            one = t.props["portable"]
            item = self.w.spawn({"name": one, "nouns": [one], "weight": 0.2, "flags": ["takeable"],
                                 "description": f"Just {('an ' if one[0] in 'aeiou' else 'a ')}{one}."}, "player")
            item.props["_spawned_in_play"] = True
            return f"You take {item.article_name}."
        if "takeable" not in t.flags:
            return "That's fixed in place." if "scenery" in t.flags or "door" in t.flags else "You can't take that."
        if self.w.carried_weight() + t.weight > self.w.load["max_kg"]:
            return (f"Too heavy: that would bring you to {self.w.carried_weight() + t.weight:.1f} kg, "
                    f"over your limit of {self.w.load['max_kg']:g} kg. Drop something first.")
        before = self.w.load_status()
        purse = self._purse()
        if "money" in t.flags and purse and t is not purse:
            purse.props["coins"] = purse.props.get("coins", 0) + int(t.props.get("value", 1))
            t.location = None
            return f"You add {int(t.props.get('value', 1))} coins to your purse."
        t.location = "player"
        t.flags.add("moved")
        story = self.story_event({"type": "take", "item": t.id}, t)
        return "Taken." + self._load_change(before) + (("\n" + story) if story else "")

    def do_drop(self, cmd):
        if cmd.all:
            cands = [t for t in self.w.contents("player") if not self.match(cmd.except_words, [t])]
            if not cands:
                return "You aren't carrying anything."
            return "\n".join(f"{t.name}: {self._drop(t)}" for t in cands)
        t = self.resolve(cmd, cmd.words, self.w.carried())
        return t if isinstance(t, str) else self._drop(t)

    def _drop(self, t: Thing) -> str:
        before = self.w.load_status()
        t.location = self.w.player
        t.flags |= {"dropped", "moved"}
        return "Dropped." + self._load_change(before)

    def _load_change(self, before: str) -> str:
        after = self.w.load_status()
        return "" if after == before else f" You are now travelling {after}."

    def do_put(self, cmd):
        if cmd.prep not in ("in", "into", "inside", "on", "onto"):
            return "Put it where? (try PUT X IN Y)"
        t = self.resolve(cmd, cmd.words, self.w.carried())
        if isinstance(t, str):
            return t
        box = self.resolve(cmd, cmd.iwords)
        if isinstance(box, str):
            return box
        if "container" not in box.flags or box is t:
            return f"You can't put anything in the {box.name}."
        if "openable" in box.flags and "open" not in box.flags:
            return f"The {box.name} is closed."
        t.location = box.id
        return f"You put the {t.name} in the {box.name}."

    def do_takeout(self, cmd):
        t = self.resolve(cmd, cmd.words)
        return t if isinstance(t, str) else self._take(t)

    def do_open(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "openable" not in t.flags:
            if "portcullis" in t.flags:
                return "A portcullis is not opened by hand; try raising it."
            return "It is barred and will not move." if "barred" in t.flags else "You can't open that."
        if "open" in t.flags:
            return "It's already open."
        if "locked" in t.flags:
            return f"The {t.name} is locked."
        t.flags.add("open")
        inside = self.w.contents(t.id) if "container" in t.flags else []
        return "Opened." + (f" Inside you see {_list(inside)}." if inside else "")

    def do_close(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "openable" not in t.flags or "open" not in t.flags:
            return "That isn't open." if "openable" in t.flags else "You can't close that."
        t.flags.discard("open")
        return "Closed."

    def _key_for(self, door: Thing, words: list[str]) -> Thing | str:
        keys = [k for k in self.w.carried() if door.id in k.unlocks]
        if words:
            k = self.resolve(Command("unlock"), words, self.w.carried())
            if isinstance(k, str):
                return k
            return k if k in keys else f"The {k.name} doesn't fit."
        return keys[0] if keys else "You have nothing that fits the lock."

    def do_unlock(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "lockable" not in t.flags:
            return "It has no lock."
        if "locked" not in t.flags:
            return "It isn't locked."
        k = self._key_for(t, cmd.iwords)
        if isinstance(k, str):
            return k
        t.flags.discard("locked")
        return f"You turn the {k.name} in the lock. The {t.name} is unlocked." if not cmd.iwords else "Unlocked."

    def do_lock(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "lockable" not in t.flags or "locked" in t.flags:
            return "You can't lock that." if "lockable" not in t.flags else "It's already locked."
        if "open" in t.flags:
            return "Close it first."
        k = self._key_for(t, cmd.iwords)
        if isinstance(k, str):
            return k
        t.flags.add("locked")
        return "Locked."

    def _custom_exit(self, words: list[str]) -> str | None:
        room = self.w.rooms[self.w.player]
        for d, e in room.exits.items():
            target = self.w.rooms.get(e.to)
            names = {d} | (set(target.area.lower().split()) | set(target.name.lower().split()) if target else set())
            if d not in DIRECTIONS and words and set(words) & names:
                return d
        return None

    def do_go(self, cmd):
        if not cmd.direction and cmd.words:
            cmd.direction = self._custom_exit(cmd.words)
        if not cmd.direction:
            return "Which way?"
        room = self.w.rooms[self.w.player]
        e = room.exits.get(cmd.direction)
        if not e or e.hidden:
            return "You can't go that way."
        if self.w.flags.get("hexes") and self.campaign is not None:
            from .. import wild
            blocked = wild.passable(self, e.to.split(":", 1)[1])
            if blocked:
                return blocked
            wild.ensure(self.w, self.campaign, e.to.split(":", 1)[1])
            self.w.flags["came_from"] = {"east": "west", "west": "east", "northeast": "southwest", "southwest": "northeast",
                                         "northwest": "southeast", "southeast": "northwest"}.get(cmd.direction)
        if e.to.startswith("bldg:") and e.to not in self.w.rooms:
            from .. import towns
            idx = e.to.split(":", 1)[1]
            if towns.open_building(self, idx, self.building_policy) == "ask":
                self.w.flags["need_building"] = idx
                return "[[dim]](This building has no interior yet.)[[/]]"
            e = self.w.rooms[self.w.player].exits[cmd.direction]
        if self.w.load_status() == "overloaded":
            return "You are carrying too much to move. Drop something."
        prefix = ""
        if e.door:
            door = self.w.things[e.door]
            if "barred" in door.flags:
                return f"The {door.name} is barred and will not move."
            if "portcullis" in door.flags and "raised" not in door.flags:
                return f"The {door.name} is down."
            if "openable" in door.flags and "open" not in door.flags:
                if "locked" in door.flags:
                    return f"The {door.name} is locked."
                door.flags.add("open")
                prefix = f"(first opening the {door.name})\n"
        if e.to == "__exit__":
            if self.campaign is not None:
                self.w.flags["transition"] = {"leave": True}
                return prefix + "You leave and take to the road again."
            return prefix + (self.w.flags.get("exit_text") or "That way leads out of this place; it's not ready yet.")
        if e.door and "household" in self.w.things[e.door].flags and self.w.player == "outside" \
                and not self.w.flags.get("knocked"):
            self.w.flags["barged"] = True
        for t in self.w.things.values():
            if "following" in t.flags and t.location == self.w.player:
                t.location = e.to
        src = self.w.player
        self.w.player = e.to
        if self.w.flags.get("hexes") and self.campaign is not None:
            from .. import wild
            travel = wild.move(self, src, e.to)
            return prefix + "\n".join(x for x in (self.describe(True), travel, self.story_event({"type": "enter"})) if x)
        if self.w.flags.get("overworld") and self.campaign is not None:
            from .. import overworld
            travel = overworld.move(self, src, e.to)
            return prefix + "\n".join(x for x in (travel, self.describe(True), self.story_event({"type": "enter"})) if x)
        return prefix + "\n".join(x for x in (self.describe(), self.story_event({"type": "enter"})) if x)

    def do_enter(self, cmd):
        if self.w.flags.get("overworld"):
            return self.do_visit(cmd)
        if cmd.words:
            d = self._custom_exit(cmd.words)
            if d:
                return self.do_go(Command("go", direction=d, raw=cmd.raw))
        return self.do_go(Command("go", direction="in", raw=cmd.raw))

    def do_onward(self, cmd):
        if self.w.flags.get("hexes"):
            from .. import wild
            d = wild.onward(self)
            return self.do_go(Command("go", direction=d, raw=cmd.raw)) if d else "Your route ends here."
        d = (self.w.flags.get("forward") or {}).get(self.w.player)
        return self.do_go(Command("go", direction=d, raw=cmd.raw)) if d else "The road ends here."

    def do_back(self, cmd):
        if self.w.flags.get("hexes"):
            from .. import wild
            d = wild.onward(self, back=True)
            return self.do_go(Command("go", direction=d, raw=cmd.raw)) if d else "There is no going back from here."
        d = (self.w.flags.get("back") or {}).get(self.w.player)
        return self.do_go(Command("go", direction=d, raw=cmd.raw)) if d else "There is no going back from here."

    def do_visit(self, cmd):
        if self.w.flags.get("hexes") and self.campaign is not None:
            from .. import wild
            wd = wild.wild_of(self.campaign)
            key = self.w.rooms[self.w.player].props["hex"]
            burg = wd.burgs.get(key)
            if burg and (not cmd.words or any(x in burg["name"].lower() for x in cmd.words)):
                self.campaign.arrive = self.w.flags.get("came_from")
                self.w.flags["transition"] = {"enter": f"town:{burg['i']}", "detour_mi": 0}
                return f"You make for {burg['name']}."
            for mk in wd.markers.get(key, []):
                if any(f.kind == "dungeon" and f.marker == mk["i"] for f in self.campaign.files.watabou):
                    self.w.flags["transition"] = {"enter": f"dungeon:{mk['i']}", "detour_mi": 0}
                    return f"You go down into {mk.get('name') or 'the dark'}."
            return "There's nothing here to enter. (Towns and sites must be in this hex; see LOOK.)"
        if not self.w.flags.get("overworld") or self.campaign is None:
            return self.do_enter(Command("enter", cmd.words, raw=cmd.raw)) if cmd.words else "Visit what?"
        from .. import overworld
        target = overworld.enter_target(self, cmd.words)
        if isinstance(target, str):
            return self.wrap_text(target)
        self.w.flags["transition"] = {"enter": target["scene"], "detour_mi": target["detour_mi"]}
        return f"You make for {target['place']['name']}."

    # ------------------------------------------------------------------ trade
    def _purse(self):
        return next((t for t in self.w.carried() if "purse" in t.flags), None)

    def do_wares(self, cmd):
        shop = self.w.flags.get("shop")
        if not shop or not any("shop" in t.flags or "person" in t.flags for t in self.visible()):
            return "There is nothing for sale here."
        purse = self._purse()
        lines = [f"  {s['name']:<28} {s['price']:>3} coins" for s in shop]
        return "For sale:\n" + "\n".join(lines) + (f"\nYour purse holds {purse.props.get('coins', 0)} coins." if purse else "")

    def do_buy(self, cmd):
        shop = self.w.flags.get("shop")
        if not shop or not any("shop" in t.flags or "person" in t.flags for t in self.visible()):
            return "There is nothing for sale here."
        spec = next((s for s in shop if cmd.words and (cmd.words[-1] in s["nouns"] or " ".join(cmd.words) in s["name"])), None)
        if not spec:
            return "No one here sells that. (Try WARES.)"
        purse = self._purse()
        if not purse or purse.props.get("coins", 0) < spec["price"]:
            return f"The {spec['name']} costs {spec['price']} coins, which you don't have."
        if self.w.carried_weight() + spec.get("weight", 0) > self.w.load["max_kg"]:
            return "You couldn't carry it."
        purse.props["coins"] -= spec["price"]
        item = self.w.spawn({k: v for k, v in spec.items() if k != "price"}, "player")
        item.props["_spawned_in_play"] = True
        item.props["value"] = spec["price"]
        return f"You buy the {item.name} for {spec['price']} coins."

    def do_sell(self, cmd):
        shop = self.w.flags.get("shop")
        if not shop:
            return "No one here is buying."
        t = self.resolve(cmd, cmd.words, self.w.carried())
        if isinstance(t, str):
            return t
        if "story" in t.flags or "purse" in t.flags:
            return "You'd rather keep that."
        here = next((s for s in shop if t.props.get("good") and s.get("good") == t.props.get("good")), None)
        price = here["price"] if here else max(0, round(t.props.get("value", 0) * 0.6))
        if not price:
            return f"No one will give you anything for the {t.name}."
        t.location = None
        purse = self._purse()
        if purse:
            purse.props["coins"] = purse.props.get("coins", 0) + price
        return f"You sell the {t.name} for {price} coins."

    def do_camp(self, cmd):
        if not self.w.flags.get("hexes"):
            return "Camp here? Find somewhere outside, or a bed."
        from .. import wild
        return wild.camp(self)

    def do_forage(self, cmd):
        if not self.w.flags.get("hexes"):
            return "There's nothing to forage here."
        from .. import wild
        return wild.forage(self)

    def do_hunt(self, cmd):
        if not self.w.flags.get("hexes"):
            return "There's nothing to hunt here."
        from .. import wild
        return wild.forage(self, hunt=True)

    def do_route(self, cmd):
        if not self.w.flags.get("hexes"):
            return "You are off the road; the route resumes when you leave."
        from .. import wild
        return self.wrap_text(wild.route_text(self))

    def do_recap(self, cmd):
        if not self.story or not self.story.record:
            return "Nothing has happened yet worth telling."
        from ..style import mark
        return "\n".join((f"[{r['when']}] " if r["when"] else "") + mark(f"{r['line']}: {r['text']}", "main" if r["kind"] == "main" else "side")
                         for r in self.story.record)

    def do_book(self, cmd):
        carriers = [t for t in self.visible() if "carrier" in t.flags]
        if carriers:
            who = carriers[0]
            if cmd.words:
                named = [t for t in carriers if set(cmd.words) & (set(t.nouns) | {t.name.lower()})]
                who = named[0] if named else who
            offer = who.props["carrier"]
            if offer.get("refuse") and not (self.story and self.story.flags.get("papers")):
                return self.wrap_text(offer["refuse"])
            purse = self._purse()
            if not purse or purse.props.get("coins", 0) < offer["price"]:
                return f"{who.name} wants {offer['price']} coins. You haven't got them."
            purse.props["coins"] -= offer["price"]
            self.w.flags["transition"] = {"ride": offer}
            return self.wrap_text(f"You pay {who.name} {offer['price']} coins and climb aboard, bound for {offer['to_name']}.")
        if not self.w.flags.get("overworld") or self.campaign is None:
            return "Passage is booked on the road, at a port."
        c = self.campaign
        stage = next((st for st in c.journey.stages if not st.is_stay and st.index >= c.pos[0] and
                      "foot" not in st.transport.lower()), None)
        if stage is None:
            return "There is no passage to book on the road ahead."
        alts = c.journey.alternatives(stage.index, c.cfg.get("transports_allowed") or [stage.transport])
        if not alts:
            return f"No faster passage than the {stage.transport.lower()} is to be had."
        if not cmd.words or cmd.words == ["passage"]:
            return f"For \"{stage.name}\" ({stage.transport.lower()}, {(stage.end_t - stage.start_t) / 24:.0f} days): " + \
                "; ".join(f"{a['transport']} {a['days']:.0f} days, difficulty {a['level']}" for a in alts) + \
                ". BOOK <transport> to take one."
        pick = next((a for a in alts if all(wd in a["transport"].lower() for wd in cmd.words if wd != "passage")), None)
        if not pick:
            return "No such passage is offered."
        c.speed[str(stage.index)] = pick["days"] / ((stage.end_t - stage.start_t) / 24)
        import random as _r
        rng = _r.Random(f"{self.w.seed}:{stage.index}:{pick['transport']}")
        if rng.random() < pick["difficulty"] * 0.6:
            c.speed[str(stage.index)] = (pick["days"] + pick["saved"] * 0.5) / ((stage.end_t - stage.start_t) / 24)
            return (f"You book passage by {pick['transport'].lower()}. The captain is cheerful about the weather, "
                    f"which turns out to be a mistake: expect to lose half of what you hoped to gain.")
        return f"You book passage by {pick['transport'].lower()}, {pick['saved']:.0f} days faster than the plan."

    def do_leave(self, cmd):
        return self.do_go(Command("go", direction="out", raw=cmd.raw))

    def do_wait(self, cmd):
        return "Time passes."

    def do_time(self, cmd):
        return f"It is {self.w.time_label()}."

    def do_status(self, cmd):
        return (f"{self.w.rooms[self.w.player].name}, {self.w.time_label()}. Moves: {self.w.moves}. "
                f"Load {self.w.carried_weight():.1f} kg ({self.w.load_status()}).")

    def do_weigh(self, cmd):
        t = self.resolve(cmd, cmd.words)
        return t if isinstance(t, str) else f"The {t.name} weighs about {t.weight:.1f} kg."

    def do_light(self, cmd):
        t = self.resolve(cmd, cmd.words, self.w.carried() + self.w.contents(self.w.player))
        if isinstance(t, str):
            return t
        if "light" not in t.flags:
            return "You can't light that."
        if "lit" in t.flags:
            return "It's already lit."
        if t.props.get("fuel", 1) <= 0:
            return f"The {t.name} has no fuel left."
        if not any("firestarter" in x.flags for x in self.w.carried()):
            return "You have nothing to light it with."
        t.flags.add("lit")
        return f"The {t.name} is now lit.\n" + self.describe()

    def do_extinguish(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "lit" not in t.flags:
            return "It isn't lit."
        t.flags.discard("lit")
        return f"The {t.name} goes out." + ("\nIt is now pitch dark." if self.dark() else "")

    def do_search(self, cmd):
        room = self.w.rooms[self.w.player]
        if not cmd.words and self.w.flags.get("town") and room.purpose in ("street", "market square"):
            from .. import towns
            found = towns.search_street(self.w, room.id)
            self.extra_minutes += 10
            if found:
                return "Looking carefully along the street, you take note of " + ", ".join(found) + ". (ENTER any of them.)"
            return "You know every building here already."
        if cmd.words:
            t = self.resolve(cmd, cmd.words)
            if isinstance(t, str):
                return t
            out = self.act(t, "search")
            hidden = [c for c in self.w.contents(t.id) if "hidden" in c.flags]
            for c in hidden:
                c.flags.discard("hidden")
                c.location = self.w.player
            found = f"You find {_list(hidden)}." if hidden else ""
            if out or found:
                return " ".join(x for x in (out, found) if x)
            inside = self.w.contents(t.id)
            if inside and ("open" in t.flags or "openable" not in t.flags):
                return f"In the {t.name} you find {_list(inside)}."
            return f"You search the {t.name} but find nothing."
        found = []
        for d, e in room.exits.items():
            if e.hidden:
                e.hidden = False
                back = self.w.rooms[e.to].exits
                for e2 in back.values():
                    if e2.to == room.id and e2.door == e.door:
                        e2.hidden = False
                if e.door:
                    self.w.things[e.door].flags.discard("hidden")
                found.append(f"a hidden door to the {d}")
        for t in self.w.contents(room.id):
            if "hidden" in t.flags and t.props.get("search"):
                t.flags.discard("hidden")
                found.append(t.article_name)
        if not found:
            return "You search carefully but find nothing." + (" (It is very dark.)" if self.dark() else "")
        return "Searching the walls and floor, you find " + ", ".join(found) + "!"

    def do_raise(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "portcullis" not in t.flags:
            return "You can't raise that."
        if "raised" in t.flags:
            return "It's already up."
        t.flags.add("raised")
        return f"Straining, you haul the {t.name} up until it catches."

    def do_lower(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        if "portcullis" not in t.flags or "raised" not in t.flags:
            return "You can't lower that."
        t.flags.discard("raised")
        return f"The {t.name} crashes down."

    def do_talk(self, cmd):
        t = self.resolve(cmd, cmd.words or cmd.iwords)
        if isinstance(t, str):
            return t
        if "person" not in t.flags:
            return self.act(t, "talk") or "There is no reply."
        story = self.story_event({"type": "talk", "thing": t.id}, t)
        return wrap(t.props.get("talk") or t.props.get("greet") or f"The {t.name} regards you but says nothing.") + \
            (("\n" + story) if story else "")

    def do_help(self, cmd):
        return wrap("Looking: LOOK, EXAMINE X, LOOK IN/UNDER X, READ X, SEARCH (X), LISTEN, SMELL, TOUCH X. "
                    "Things: TAKE/DROP X (or ALL), PUT X IN Y, OPEN/CLOSE X, UNLOCK X (WITH Y), LIGHT/EXTINGUISH X, "
                    "FILL X, USE X (ON Y), EAT, DRINK, WEAR X, PUSH/PULL X, RAISE/LOWER X, WEIGH X, INVENTORY (I). "
                    "Rest: SIT, SLEEP, PRAY, COOK. People: TALK TO X, ASK X ABOUT Y, TELL X ABOUT Y, GIVE X TO Y, "
                    "SHOW X TO Y, INVITE X, DISMISS X, KNOCK. Journal: WRITE <text>, JOURNAL. "
                    "Moving: N, NE, E, SE, S, SW, W, NW, UP, DOWN, IN, OUT. Game: WAIT (Z), TIME, STATUS, AGAIN (G), "
                    "UNDO, SAVE [name], RESTORE [name], QUIT. Chain commands with periods or THEN.")

    # ------------------------------------------------------------------ meta
    def do_undo(self, cmd):
        if not self.undo_stack:
            return "There is nothing to undo."
        self.w.set_state(self.undo_stack.pop())
        return "[Previous move undone.]\n" + self.describe()

    def _save_path(self, cmd) -> Path | None:
        if not self.save_dir:
            return None
        slot = "-".join(cmd.words) or "quick"
        return self.save_dir / f"{self.w.name}-{slot}.json"

    def do_save(self, cmd):
        path = self._save_path(cmd)
        if not path:
            return "Saving is not available here."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"world": self.w.name, "scene": self.w.scene, "state": self.w.state()}),
                        encoding="utf-8")
        return f"Saved ({path.name})."

    def do_restore(self, cmd):
        path = self._save_path(cmd)
        if not path or not path.exists():
            return "There is no saved game with that name."
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["scene"] != self.w.scene:
            return f"That save belongs to scene {data['scene']}; start it with --scene {data['scene']}."
        self.w.set_state(data["state"])
        return "Restored.\n" + self.describe(True)

    def do_quit(self, cmd):
        self.quit_requested = True
        return "Leaving the game."

    # --------------------------------------------------------------- hazards
    def _hazard(self, t: Thing, verb: str) -> str | None:
        h = t.props.get("hazard")
        if not h or verb not in h.get("on", []):
            return None
        if h.get("fatal"):
            self.w.dead = True
            return wrap(h["text"]) + DEATH
        return wrap(h["text"])

    @staticmethod
    def _door_state(t: Thing) -> str:
        if "barred" in t.flags:
            return "It is barred."
        if "portcullis" in t.flags:
            return "It is raised." if "raised" in t.flags else "It is down."
        state = "open" if "open" in t.flags else "closed"
        return f"It is {state}" + (" and locked." if "locked" in t.flags else ".")


def _list(things: list[Thing]) -> str:
    names = [t.article_name for t in things]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
