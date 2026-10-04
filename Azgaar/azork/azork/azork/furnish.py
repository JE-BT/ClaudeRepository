"""Furnish rooms from their purpose (data/furnishings.json), with the odd joke where something is missing."""
from __future__ import annotations

import copy
import random

from .engine.model import World
from .interiors import TABLES

ABSENT_CHANCE = 0.12


def _fill(value, context: dict):
    if isinstance(value, str) and value.startswith("@"):
        return context.get(value[1:], "")
    if isinstance(value, dict):
        return {k: _fill(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, context) for v in value]
    return value


def furnish(w: World, seed: str, context: dict, tables: dict | None = None, only: str | None = None) -> None:
    purposes = (tables or TABLES)["purposes"]
    for room in list(w.rooms.values()):
        if only is not None and not room.id.startswith(only):
            continue
        if room.props.get("furnished") if hasattr(room, "props") else False:
            continue
        spec = purposes.get(room.purpose)
        if not spec:
            continue
        rng = random.Random(f"{seed}:{room.id}:furnish")
        if spec.get("absent") and rng.random() < ABSENT_CHANCE:
            w.spawn({"name": "absence", "nouns": ["absence"], "flags": ["scenery"], "here": spec["absent"]}, room.id,
                    f"{room.id}:absent")
            continue
        for k, item in enumerate(spec["items"]):
            if f"{room.id}:f{k}" not in w.things:
                w.spawn(_fill(copy.deepcopy(item), context), room.id, f"{room.id}:f{k}")
