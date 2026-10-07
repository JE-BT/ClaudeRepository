"""Azgaar's namebases (vendored default lists, MIT) with any per-world overrides from the .map.

The engine generates names in the browser with Azgaar's own Markov method (names.js, ported from
src/generators/names-generator.ts), so the pack carries the lists for the cultures in the world.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("data") / "namebases.json"


@lru_cache(maxsize=1)
def default_bases() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["bases"]


class NameBases:
    def __init__(self, overrides: dict[int, dict] | None = None):
        self.bases = [dict(b) for b in default_bases()]
        for i, o in (overrides or {}).items():
            if i < len(self.bases):
                self.bases[i].update({k: v for k, v in o.items() if k != "b" or v})
