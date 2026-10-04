"""The game: resolves parsed commands against the world and produces text."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .model import DIRECTIONS, Thing, World
from .parser import Command, parse, split_commands

MINUTES = {"go": 1, "wait": 10, "search": 5, "raise": 10, "lower": 2, "take": 0.5, "drop": 0.5, "put": 0.5,
           "takeout": 0.5, "open": 0.5, "close": 0.5, "unlock": 1, "lock": 1, "light": 1, "extinguish": 0.2,
           "read": 2, "examine": 0.5, "lookin": 0.5, "talk": 2}
META = {"undo", "save", "restore", "quit", "again", "help", "time", "status", "inventory", "look", "weigh"}
DEATH = "\n    *** You have died ***\nType UNDO to take back the last move, RESTORE to load a saved game, or QUIT."


def wrap(text: str) -> str:
    return "\n".join(textwrap.fill(p, 78) if p.strip() else "" for p in text.split("\n"))


class Game:
    def __init__(self, world: World, save_dir: str | Path | None = None):
        self.w = world
        self.save_dir = Path(save_dir) if save_dir else None
        self.undo_stack: list[dict] = []
        self.last_line: str | None = None
        self.it: str | None = None
        self.pending: tuple[Command, list[Thing]] | None = None
        self.quit_requested = False
        self.log: list[tuple[str, str]] = []   # (command, output) for the transcript and ledger export

    # ------------------------------------------------------------------ driver
    def intro(self) -> str:
        return wrap(f"{self.w.flags.get('title', self.w.scene)}\n{self.w.time_label()}\n\n") + self.describe(True)

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
        out = handler(cmd)
        if cmd.verb not in META and not self.w.dead:
            self.w.moves += 1
            out = "\n".join(x for x in (out, self.tick(MINUTES.get(cmd.verb, 1))) if x)
        return out

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
                        label += f" ({state}{door.name})"
                    elif e.note:
                        label += f" ({e.note})"
                    exits.append(label)
            if exits:
                lines.append("Exits: " + ", ".join(exits) + ".")
        room.visited = True
        items = [t for t in self.w.contents(self.w.player)
                 if "hidden" not in t.flags and "scenery" not in t.flags]
        for t in items:
            lines.append(t.props.get("here") or f"There is {t.article_name} here.")
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
        if not hits:
            return "It's too dark to find anything." if self.dark() else f"You can't see any {' '.join(words)} here."
        if len(hits) > 1:
            self.pending = (cmd, hits)
            names = [f"the {t.name}" for t in hits]
            return "Which do you mean, " + ", ".join(names[:-1]) + " or " + names[-1] + "?"
        self.it = hits[0].id
        return hits[0]

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
        parts = [t.description or f"You see nothing special about the {t.name}."]
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
        return wrap(" ".join(parts))

    def do_lookin(self, cmd):
        t = self.resolve(cmd, cmd.words or cmd.iwords)
        if isinstance(t, str):
            return t
        if (h := self._hazard(t, "lookin")) is not None:
            return h
        if "container" in t.flags:
            return self.do_examine(cmd)
        return f"You see nothing unusual in the {t.name}."

    def do_read(self, cmd):
        t = self.resolve(cmd, cmd.words)
        if isinstance(t, str):
            return t
        return wrap(t.text) if t.text else f"There is nothing written on the {t.name}."

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
        if "takeable" not in t.flags:
            return "That's fixed in place." if "scenery" in t.flags or "door" in t.flags else "You can't take that."
        if self.w.carried_weight() + t.weight > self.w.load["max_kg"]:
            return (f"Too heavy: that would bring you to {self.w.carried_weight() + t.weight:.1f} kg, "
                    f"over your limit of {self.w.load['max_kg']:g} kg. Drop something first.")
        before = self.w.load_status()
        t.location = "player"
        return "Taken." + self._load_change(before)

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
        t.flags.add("dropped")
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

    def do_go(self, cmd):
        if not cmd.direction:
            return "Which way?"
        room = self.w.rooms[self.w.player]
        e = room.exits.get(cmd.direction)
        if not e or e.hidden:
            return "You can't go that way."
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
            return prefix + (self.w.flags.get("exit_text") or "That way leads out of this place; it's not ready yet.")
        self.w.player = e.to
        return prefix + self.describe()

    def do_enter(self, cmd):
        return self.do_go(Command("go", direction="in", raw=cmd.raw))

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
            return "There is no reply."
        return wrap(t.props.get("talk") or f"The {t.name} regards you but says nothing.")

    def do_help(self, cmd):
        return wrap("Commands: LOOK, EXAMINE X, LOOK IN X, READ X, TAKE X / TAKE ALL, DROP X / DROP ALL, "
                    "PUT X IN Y, OPEN/CLOSE X, UNLOCK X (WITH Y), LIGHT/EXTINGUISH X, SEARCH, RAISE/LOWER X, "
                    "WEIGH X, INVENTORY (I), directions (N, NE, E, SE, S, SW, W, NW, UP, DOWN, IN, OUT), "
                    "WAIT (Z), TIME, STATUS, AGAIN (G), UNDO, SAVE [name], RESTORE [name], QUIT. "
                    "Chain commands with periods or THEN.")

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
