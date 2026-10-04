"""Interaction verbs, mixed into Game.

Things carry optional `actions` specs (from furnishings, notes, overlays): verb -> {text, time,
once, spawn, loot, reveal, rest, meal, drink, consume, fatal}. Without a spec, each verb has a
sensible default that depends on the thing's flags (food, drink, bed, seat, water_source...).
People carry topics, accepts, show, tell, invite, greet and barge texts.
"""
from __future__ import annotations

import random

from .model import Thing


class Interactions:
    # ------------------------------------------------------------ action specs
    def act(self, t: Thing, verb: str) -> str | None:
        spec = (t.props.get("actions") or {}).get(verb)
        if spec is None:
            return None
        if isinstance(spec, str):
            return spec
        if spec.get("fatal"):
            self.w.dead = True
            from .game import DEATH, wrap
            return wrap(spec["text"]) + DEATH
        done = f"done:{verb}"
        if spec.get("once") and t.props.get(done):
            return spec.get("again") or "You find nothing more."
        out = [spec.get("text", "")]
        if spec.get("spawn"):
            s = self.w.spawn(spec["spawn"], self.w.player)
            s.props["_spawned_in_play"] = True
        if spec.get("loot"):
            item = self.loot(spec["loot"])
            out.append(f"You find {item.article_name}." if item else "You find nothing of value.")
        for thing in self.w.contents(self.w.player) if spec.get("reveal") else []:
            thing.flags.discard("hidden")
        if spec.get("rest"):
            out.append(self.tick(spec["rest"] * 60) or "")
            out.append(f"You wake. It is {self.w.time_label()}.")
        if spec.get("meal"):
            self.w.flags["last_meal"] = self.w.plan_t
        if spec.get("drink"):
            self.w.flags["last_drink"] = self.w.plan_t
        if spec.get("consume"):
            t.location = None
        if spec.get("once"):
            t.props[done] = True
        self.extra_minutes += spec.get("time", 0)
        return " ".join(x for x in out if x)

    def loot(self, tier: str) -> Thing | None:
        room = self.w.rooms[self.w.player]
        deep = room.depth >= 0.66 * max(1, self.w.flags.get("max_depth", 1))
        if tier == "any" and deep:
            tier = "treasure"
        table = self.w.loot.get(tier) or []
        rng = random.Random(f"{self.w.seed}:{room.id}:{tier}")
        if not table or rng.random() < 0.25:
            return None
        spec = dict(rng.choice(table))
        if spec.get("text") == "@heart":
            spec["text"] = self.w.flags.get("heart_hint", "The ink has run; you can make nothing of it.")
        item = self.w.spawn(spec, self.w.player)
        item.props["_spawned_in_play"] = True
        return item

    def _thing(self, cmd, words=None, pool=None):
        return self.resolve(cmd, cmd.words if words is None else words, pool)

    def _generic(self, cmd, verb: str, default) -> str:
        if not cmd.words:
            return default(None)
        t = self._thing(cmd)
        if isinstance(t, str):
            return t
        return self.act(t, verb) or default(t)

    # ------------------------------------------------------------------ needs
    def do_eat(self, cmd):
        def default(t):
            if t is None:
                food = [x for x in self.w.carried() if "food" in x.flags]
                if not food:
                    return "You have nothing to eat."
                t = food[0]
            if "food" not in t.flags:
                return "That's plainly inedible." if "person" not in t.flags else "Steady on."
            self._use_up(t)
            self.w.flags["last_meal"] = self.w.plan_t
            self.extra_minutes += 10
            return f"You eat some of the {t.name}." + ("" if t.location else " That was the last of it.")
        return self._generic(cmd, "eat", default)

    def do_drink(self, cmd):
        def default(t):
            if t is None:
                src = [x for x in self.visible() if "water_source" in x.flags] + \
                      [x for x in self.w.carried() if "drink" in x.flags and x.props.get("uses", 1) > 0]
                if not src:
                    return "You have nothing to drink."
                t = src[0]
                spec_out = self.act(t, "drink")
                if spec_out:
                    return spec_out
            if "water_source" in t.flags:
                self.w.flags["last_drink"] = self.w.plan_t
                return "You drink. Cold, and better than nothing."
            if "drink" not in t.flags:
                return "You can't drink that."
            if t.props.get("uses", 1) <= 0:
                return f"The {t.name} is empty."
            t.props["uses"] = t.props.get("uses", 1) - 1
            self.w.flags["last_drink"] = self.w.plan_t
            return f"You drink from the {t.name}." + (" It's empty now." if t.props["uses"] == 0 else "")
        return self._generic(cmd, "drink", default)

    def _use_up(self, t: Thing) -> None:
        uses = t.props.get("uses", 1) - 1
        t.props["uses"] = uses
        if uses <= 0:
            t.location = None

    def do_fill(self, cmd):
        t = self._thing(cmd, pool=self.w.carried())
        if isinstance(t, str):
            return t
        if "light" in t.flags:
            oil = next((x for x in self.w.carried() if "fuel_source" in x.flags), None)
            if not oil:
                return "You have no oil."
            t.props["fuel"] = t.props.get("fuel", 0) + oil.props.get("fuel", 240)
            oil.location = None
            return f"You fill the {t.name} from the {oil.name}."
        if "drink" not in t.flags:
            return f"You can't fill the {t.name}."
        src = next((x for x in self.visible() if "water_source" in x.flags), None)
        if not src:
            return "There's no water here."
        t.props["uses"] = t.props.get("max_uses", 6)
        self.extra_minutes += 2
        return f"You fill the {t.name} from the {src.name}."

    def do_use(self, cmd):
        t = self._thing(cmd)
        if isinstance(t, str):
            return t
        if cmd.iwords:
            target = self.resolve(cmd, cmd.iwords)
            if isinstance(target, str):
                return target
            if "fuel_source" in t.flags and "light" in target.flags:
                return self.do_fill(type(cmd)("fill", target.name.split(), raw=cmd.raw))
            if target.id in t.unlocks:
                return self.do_unlock(type(cmd)("unlock", target.name.split(), raw=cmd.raw))
            return self.act(target, "use") or "Nothing happens."
        spec = self.act(t, "use")
        if spec:
            return spec
        route = [("food", "eat"), ("drink", "drink"), ("light", "light"), ("bed", "sleep"), ("seat", "sit"),
                 ("readable", "read"), ("wearable", "wear"), ("fuel_source", "fill")]
        for flag, verb in route:
            if flag in t.flags:
                if verb == "fill":
                    lamp = next((x for x in self.w.carried() if "light" in x.flags), None)
                    return self.do_fill(type(cmd)("fill", lamp.name.split(), raw=cmd.raw)) if lamp else "Fill what?"
                return getattr(self, f"do_{verb}")(cmd)
        if t.unlocks:
            door = next((d for d in self.w.doors_here(self.w.player) if d.id in t.unlocks), None)
            if door:
                return self.do_unlock(type(cmd)("unlock", door.name.split(), raw=cmd.raw))
        return f"How do you want to use the {t.name}? Try a more specific verb."

    def do_sleep(self, cmd):
        bed = None
        if cmd.words:
            bed = self._thing(cmd)
            if isinstance(bed, str):
                return bed
        else:
            bed = next((x for x in self.visible() if "bed" in x.flags), None)
        if bed is not None:
            out = self.act(bed, "sleep")
            if out:
                return out
            if "bed" not in bed.flags and bed.id != "bedroll":
                return "You can't sleep on that."
        if bed is None and not any(x.id == "bedroll" or "bedroll" in x.nouns for x in self.w.carried()):
            return "There is nowhere comfortable to sleep, and you have no bedroll."
        rest = self.tick(4 * 60)
        return "You sleep for a few hours." + (f" {rest}" if rest else "") + f" It is {self.w.time_label()}."

    def do_sit(self, cmd):
        def default(t):
            if t is None:
                seat = next((x for x in self.visible() if "seat" in x.flags), None)
                return (self.act(seat, "sit") if seat else None) or "You sit down on the floor for a moment."
            return "You sit on it. Nothing happens." if "seat" in t.flags else "That's not for sitting on."
        return self._generic(cmd, "sit", default)

    def do_wear(self, cmd):
        t = self._thing(cmd, pool=self.w.carried())
        if isinstance(t, str):
            return t
        if "wearable" not in t.flags:
            return "You can't wear that."
        t.flags.add("worn")
        return f"You put on the {t.name}."

    # ----------------------------------------------------------------- senses
    def do_listen(self, cmd):
        def default(t):
            if t is not None:
                return f"The {t.name} makes no sound."
            creature = next((x for x in self.w.things.values() if "creature" in x.flags and x.location), None)
            if creature and self.w.rooms[self.w.player].area == self.w.rooms[creature.location].area:
                if creature.location == self.w.player:
                    return f"The {creature.name} breathes, slow and enormous."
                return "Somewhere deeper in, something breathes slowly."
            people = [x for x in self.w.things.values() if "person" in x.flags and x.location in self.w.rooms
                      and x.location != self.w.player and self.w.rooms[x.location].area == self.w.rooms[self.w.player].area]
            return "Voices, from another room." if people else "Silence."
        return self._generic(cmd, "listen", default)

    def do_smell(self, cmd):
        def default(t):
            if t is not None:
                return f"The {t.name} smells of nothing in particular."
            return "Damp stone and old air." if self.w.rooms[self.w.player].dark == "always" else "Woodsmoke."
        return self._generic(cmd, "smell", default)

    def do_touch(self, cmd):
        return self._generic(cmd, "touch", lambda t: "You feel nothing unexpected." if t else "Touch what?")

    def do_push(self, cmd):
        return self._generic(cmd, "push", lambda t: "It doesn't budge." if t else "Push what?")

    def do_pull(self, cmd):
        return self._generic(cmd, "pull", lambda t: "Nothing happens." if t else "Pull what?")

    def do_pray(self, cmd):
        here = [x for x in self.visible() if (x.props.get("actions") or {}).get("pray")]
        if here and not cmd.words:
            return self.act(here[0], "pray")
        return self._generic(cmd, "pray", lambda t: "You pray. Nothing obvious happens.")

    def do_cook(self, cmd):
        stove = next((x for x in self.visible() if (x.props.get("actions") or {}).get("cook")), None)
        if not stove:
            return "There's nowhere to cook here."
        if not any("food" in x.flags for x in self.w.carried()):
            return "You have nothing to cook."
        return self.act(stove, "cook")

    def do_lookunder(self, cmd):
        return self._generic(cmd, "lookunder", lambda t: f"There's nothing under the {t.name}." if t else "Under what?")

    def do_play(self, cmd):
        return self._generic(cmd, "play", lambda t: "You can't play with that." if t else "Play with what?")

    def do_attack(self, cmd):
        def default(t):
            if t is None:
                return "Attack what?"
            if "person" in t.flags:
                return "Violence isn't the answer to this one."
            return f"Taking out your frustration on the {t.name} achieves nothing."
        return self._generic(cmd, "attack", default)

    def do_wake(self, cmd):
        sleeper = next((x for x in self.w.contents(self.w.player) if (x.props.get("actions") or {}).get("wake")), None)
        if sleeper and not cmd.words:
            return self.act(sleeper, "wake")
        return self._generic(cmd, "wake", lambda t: "They're already awake." if t and "person" in t.flags else
                             "Nothing stirs." if t else "You shout. Your voice comes back to you, smaller.")

    # ---------------------------------------------------------------- journal
    def _journal(self) -> Thing | None:
        return next((x for x in self.w.carried() if "journal" in x.flags), None)

    def do_write(self, cmd):
        book = self._journal()
        if not book:
            return "You have nothing to write in."
        if not any("writer" in x.flags for x in self.w.carried()):
            return "You have nothing to write with."
        raw = cmd.raw.strip()
        text = raw.split(" ", 1)[1] if " " in raw else ""
        for tail in (" in journal", " in my journal", " in the journal", " in diary"):
            if text.lower().endswith(tail):
                text = text[: -len(tail)]
        if not text.strip():
            return "Write what? (WRITE followed by your note)"
        book.props.setdefault("entries", []).append([self.w.time_label(), text.strip()])
        return "You write it down."

    def do_journal(self, cmd):
        book = self._journal()
        if not book:
            return "You have no journal."
        entries = book.props.get("entries", [])
        if not entries:
            return f"The {book.name} is blank."
        return "\n".join(f"[{when}] {text}" for when, text in entries)

    # ------------------------------------------------------------------ people
    def _person(self, cmd, words):
        t = self.resolve(cmd, words)
        if isinstance(t, str):
            return t
        if not ({"person", "creature"} & t.flags):
            return f"The {t.name} isn't listening."
        return t

    def do_knock(self, cmd):
        door = self.resolve(cmd, cmd.words or ["door"], [d for d in self.visible() if "door" in d.flags])
        if isinstance(door, str):
            return "There's nothing here to knock on." if "can't see" in door else door
        if "household" in door.flags:
            inside = [r for r in door.props.get("rooms", []) if r != self.w.player]
            area = self.w.rooms[inside[0]].area if inside else ""
            people = [x for x in self.w.things.values() if "person" in x.flags and x.location in self.w.rooms
                      and self.w.rooms[x.location].area == area]
            self.w.flags["knocked"] = True
            if people:
                return f"You knock. After a moment a voice calls, \"Come in, then.\""
            return "You knock. Nobody answers."
        sleeper = next((x for x in self.w.contents(self.w.player) if (x.props.get("actions") or {}).get("wake")), None)
        if sleeper:
            return self.act(sleeper, "wake")
        if self.w.rooms[self.w.player].dark == "always":
            return "The knock echoes away into the dark. Somewhere, something stops moving."
        return "You knock. Nothing happens."

    def do_give(self, cmd):
        item = self.resolve(cmd, cmd.words, self.w.carried())
        if isinstance(item, str):
            return item
        who = self._person(cmd, cmd.iwords)
        if isinstance(who, str):
            return who
        for key, spec in (who.props.get("accepts") or {}).items():
            if set(key.split("|")) & set(item.nouns + [item.name]):
                if item.props.get("uses", 1) > 1:
                    item.props["uses"] -= 1  # one portion changes hands
                else:
                    item.location = who.id if spec.get("keep", True) else None
                for k, v in (spec.get("flags") or {}).items():
                    self.w.flags[k] = v
                if spec.get("reward"):
                    r = self.w.spawn(spec["reward"], "player")
                    r.props["_spawned_in_play"] = True
                story = self.story_event({"type": "give", "item": item.id, "to": who.id})
                return self.wrap_text(spec.get("text", f"The {who.name} accepts the {item.name}.")) + \
                    (("\n" + story) if story else "")
        if "food" in item.flags and "person" in who.flags:
            item.location = None
            return f"The {who.name} takes the {item.name} with a nod and eats it on the spot."
        if "money" in item.flags and "person" in who.flags:
            item.location = who.id
            self.w.flags[f"tipped:{who.id}"] = True
            return f"The {who.name} pockets the coins and looks at you with new interest."
        story = self.story_event({"type": "give", "item": item.id, "to": who.id})
        if story:
            item.location = who.id
            return f"The {who.name} takes the {item.name}.\n" + story
        return f"The {who.name} looks at the {item.name} and hands it back."

    def do_show(self, cmd):
        item = self.resolve(cmd, cmd.words, self.w.carried())
        if isinstance(item, str):
            return item
        who = self._person(cmd, cmd.iwords)
        if isinstance(who, str):
            return who
        for key, text in (who.props.get("show") or {}).items():
            if set(key.split("|")) & set(item.nouns):
                return self.wrap_text(text)
        return f"The {who.name} glances at the {item.name} without much interest."

    def _topic(self, table: dict, words: list[str]) -> str | None:
        for key, text in (table or {}).items():
            if set(key.split("|")) & set(words):
                return text
        return None

    def do_ask(self, cmd):
        who = self._person(cmd, cmd.words)
        if isinstance(who, str):
            return who
        if not cmd.iwords:
            return f"Ask the {who.name} about what?"
        text = self._topic(who.props.get("topics"), cmd.iwords) or self._topic(who.props.get("lore"), cmd.iwords)
        story = self.story_event({"type": "ask", "thing": who.id, "topic": cmd.iwords}, who)
        if text:
            out = f"The {who.name} says, \"{text}\"" if "proper" not in who.flags else f"{who.name} says, \"{text}\""
        else:
            out = who.props.get("ask_default") or f"The {who.name} has nothing to say about that."
        return self.wrap_text(out) + (("\n" + story) if story else "")

    def do_tell(self, cmd):
        who = self._person(cmd, cmd.words)
        if isinstance(who, str):
            return who
        return self.wrap_text(self._topic(who.props.get("tell"), cmd.iwords) or f"The {who.name} listens politely.")

    def do_invite(self, cmd):
        who = self._person(cmd, cmd.words)
        if isinstance(who, str):
            return who
        spec = who.props.get("invite") or {}
        if spec.get("accept"):
            who.flags.add("following")
            return self.wrap_text(spec.get("text", f"The {who.name} agrees to come along."))
        return self.wrap_text(spec.get("text", f"The {who.name} shakes their head. \"I've work here.\""))

    def do_dismiss(self, cmd):
        who = self._person(cmd, cmd.words)
        if isinstance(who, str):
            return who
        who.flags.discard("following")
        return f"The {who.name} stays behind."
