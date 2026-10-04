"""World model for the text engine: rooms, exits, things and the mutable state."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

DIRECTIONS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest",
              "up", "down", "in", "out"]
ABBREV = {"n": "north", "ne": "northeast", "e": "east", "se": "southeast", "s": "south", "sw": "southwest",
          "w": "west", "nw": "northwest", "u": "up", "d": "down"}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east", "northeast": "southwest",
            "southwest": "northeast", "northwest": "southeast", "southeast": "northwest", "up": "down",
            "down": "up", "in": "out", "out": "in"}


@dataclass
class Exit:
    to: str
    door: str | None = None      # thing id of the door, if any
    hidden: bool = False         # secret until found
    note: str = ""               # e.g. "an archway", "steps"


@dataclass
class Room:
    id: str
    name: str
    description: str
    exits: dict[str, Exit] = field(default_factory=dict)
    dark: str = "never"          # never, always, night
    area: str = ""               # building or dungeon name
    provenance: str = "data"
    visited: bool = False


@dataclass
class Thing:
    id: str
    name: str
    nouns: list[str]
    adjectives: list[str] = field(default_factory=list)
    description: str = ""
    location: str | None = None  # room id, "player", a container's id, or None (nowhere)
    weight: float = 0.0          # kg
    flags: set[str] = field(default_factory=set)
    text: str = ""               # for READ
    unlocks: list[str] = field(default_factory=list)
    props: dict = field(default_factory=dict)  # fuel, hazard, hint, door rooms, value...
    provenance: str = "new"

    @property
    def article_name(self) -> str:
        if "proper" in self.flags:
            return self.name
        return ("an " if self.name[:1].lower() in "aeiou" else "a ") + self.name


class World:
    """Static content (rooms, things) plus mutable state; state() is what saves store."""

    def __init__(self, name: str, scene: str):
        self.name, self.scene = name, scene
        self.rooms: dict[str, Room] = {}
        self.things: dict[str, Thing] = {}
        self.player = ""
        self.minutes = 0.0           # since the scene began
        self.start_t = 0.0           # plan hours (journey clock) at scene start
        self.moves = 0
        self.dead = False
        self.flags: dict = {}
        self.load = {"light_kg": 15.0, "max_kg": 35.0}
        self.clock = None            # journey PlanClock, set by the scene builder
        self.lat = 0.0

    # ------------------------------------------------------------------ helpers
    def add_room(self, room: Room) -> Room:
        self.rooms[room.id] = room
        return room

    def add_thing(self, thing: Thing) -> Thing:
        self.things[thing.id] = thing
        return thing

    def connect(self, a: str, direction: str, b: str, door: str | None = None, hidden: bool = False,
                note: str = "", back: str | None = None) -> None:
        self.rooms[a].exits[direction] = Exit(b, door, hidden, note)
        back = back or OPPOSITE[direction]
        if back:
            self.rooms[b].exits[back] = Exit(a, door, hidden, note)

    def contents(self, location: str) -> list[Thing]:
        return [t for t in self.things.values() if t.location == location]

    def carried(self) -> list[Thing]:
        out, todo = [], self.contents("player")
        while todo:
            t = todo.pop(0)
            out.append(t)
            todo += self.contents(t.id)
        return out

    def carried_weight(self) -> float:
        return sum(t.weight for t in self.carried())

    def load_status(self) -> str:
        w = self.carried_weight()
        return "light" if w <= self.load["light_kg"] else "laden" if w <= self.load["max_kg"] else "overloaded"

    def doors_here(self, room: str) -> list[Thing]:
        return [t for t in self.things.values() if "door" in t.flags and room in t.props.get("rooms", ())]

    @property
    def plan_t(self) -> float:
        return self.start_t + self.minutes / 60

    def is_night(self) -> bool:
        if not self.clock:
            return False
        from ..clock import daylight
        h = self.clock.abs_hour(self.plan_t)
        dawn, dusk = daylight(self.lat, self.clock.doy(int(h // 24)))
        return not (dawn <= h % 24 < dusk)

    def time_label(self) -> str:
        return self.clock.label(self.plan_t, self.lat) if self.clock else f"{int(self.minutes)} minutes in"

    # -------------------------------------------------------------------- state
    def state(self) -> dict:
        return {
            "player": self.player, "minutes": self.minutes, "moves": self.moves, "dead": self.dead,
            "flags": copy.deepcopy(self.flags),
            "things": {k: {"location": t.location, "flags": sorted(t.flags), "props": copy.deepcopy(t.props)}
                       for k, t in self.things.items()},
            "rooms": {k: {"visited": r.visited, "hidden": {d: e.hidden for d, e in r.exits.items()}}
                      for k, r in self.rooms.items()},
        }

    def set_state(self, s: dict) -> None:
        self.player, self.minutes, self.moves, self.dead = s["player"], s["minutes"], s["moves"], s["dead"]
        self.flags = copy.deepcopy(s["flags"])
        for k, v in s["things"].items():
            if k in self.things:
                t = self.things[k]
                t.location, t.flags, t.props = v["location"], set(v["flags"]), copy.deepcopy(v["props"])
        for k, v in s["rooms"].items():
            if k in self.rooms:
                self.rooms[k].visited = v["visited"]
                for d, hidden in v["hidden"].items():
                    if d in self.rooms[k].exits:
                        self.rooms[k].exits[d].hidden = hidden
