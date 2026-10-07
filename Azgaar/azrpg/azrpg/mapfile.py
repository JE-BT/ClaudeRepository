"""Read an Azgaar .map save (formats 1.153.x and 1.154.x).

The file is a CRLF-joined list of 53 fields (Azgaar's src/services/io/save.ts).
Bare LF characters occur inside the embedded SVG, so the file must be split on
CRLF only. Field positions come from the save routine, and every field is then
checked against a content signature before use; a failed check stops loading
with a message instead of silently reading the wrong dataset.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

SUPPORTED = ("1.153", "1.154")

# index -> (key, kind); kinds: json, ints, floats, text, skip
LAYOUT: dict[int, tuple[str, str]] = {
    0: ("params", "text"), 1: ("settings", "json"), 3: ("biomes", "json"), 6: ("grid", "json"),
    7: ("grid_h", "ints"), 8: ("grid_prec", "ints"), 9: ("grid_f", "ints"), 10: ("grid_t", "ints"),
    11: ("grid_temp", "ints"), 12: ("features", "json"), 13: ("cultures", "json"), 14: ("states", "json"),
    15: ("burgs", "json"), 16: ("biome", "ints"), 17: ("burg", "ints"), 18: ("conf", "ints"),
    19: ("culture", "ints"), 20: ("fl", "ints"), 21: ("pop", "floats"), 22: ("river", "ints"),
    24: ("suitability", "ints"), 25: ("state", "ints"), 26: ("religion", "ints"), 27: ("province", "ints"),
    29: ("religions", "json"), 30: ("provinces", "json"), 31: ("namesdata", "text"), 32: ("rivers", "json"),
    35: ("markers", "json"), 36: ("cell_routes", "json"), 37: ("routes", "json"), 38: ("zones", "json"),
    39: ("ice", "json"), 40: ("good", "ints"), 41: ("goods", "json"), 42: ("markets", "json"),
    43: ("deals", "json"), 44: ("market", "ints"), 46: ("measurers", "json"), 52: ("journeys", "json"),
}
PACK_ARRAYS = ("biome", "burg", "conf", "culture", "fl", "pop", "river", "suitability",
               "state", "religion", "province", "good", "market")
GRID_ARRAYS = ("grid_h", "grid_prec", "grid_f", "grid_t", "grid_temp")


def _first(items: list) -> Any:
    """First real record of an Azgaar list (some lists start with a 0 placeholder)."""
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def _has(*keys: str) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        if isinstance(value, dict):
            return all(k in value for k in keys)
        if isinstance(value, list):
            rec = _first(value)
            return rec is None or all(k in rec for k in keys)
        return False
    return check


SIGNATURES: dict[str, Callable[[Any], bool]] = {
    "settings": _has("seed", "units", "transports"), "grid": _has("spacing", "points"),
    "biomes": _has("habitability"), "features": _has("land", "cells"), "cultures": _has("base"),
    "states": _has("neighbors", "diplomacy"), "burgs": _has("population", "cell"),
    "religions": lambda v: isinstance(v, list) and v and v[0].get("name") == "No religion",
    "provinces": _has("formName", "center"), "rivers": _has("source", "mouth"),
    "markers": _has("icon", "cell"), "routes": _has("group", "points"), "zones": _has("cells", "type"),
    "goods": _has("tags"), "markets": _has("centerBurgId"), "deals": _has("seller", "buyer", "good"),
    "journeys": _has("segments"),
    "cell_routes": lambda v: isinstance(v, dict) and all(k.isdigit() for k in list(v)[:20]),
}


class MapFormatError(ValueError):
    pass


class AzgaarMap:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8", newline="") as fh:  # keep CRLF intact
            raw = fh.read()
        fields = raw.split("\r\n")
        if len(fields) != 53:
            raise MapFormatError(f"{self.path.name}: expected 53 CRLF fields, found {len(fields)}")
        self.version = fields[0].split("|")[0]
        if not self.version.startswith(SUPPORTED):
            raise MapFormatError(f"{self.path.name}: format {self.version} not in {SUPPORTED}")
        self.data: dict[str, Any] = {}
        for index, (key, kind) in LAYOUT.items():
            self.data[key] = self._parse(fields[index], kind, key)
        self._verify()

    # ------------------------------------------------------------------ parsing
    def _parse(self, text: str, kind: str, key: str) -> Any:
        if kind == "text":
            return text
        if kind == "json":
            if not text:
                return [] if key != "cell_routes" else {}
            value = json.loads(text)
            check = SIGNATURES.get(key)
            if check and not check(value):
                raise MapFormatError(f"{self.path.name}: field '{key}' does not look like {key}")
            return value
        if not text:
            return []
        conv = float if kind == "floats" else int
        return [conv(x) for x in text.split(",")]

    def _verify(self) -> None:
        """Content checks on the unlabelled numeric arrays."""
        n = len(self.data["biome"])
        for key in PACK_ARRAYS:
            if self.data[key] and len(self.data[key]) != n:
                raise MapFormatError(f"pack array '{key}' has {len(self.data[key])} values, expected {n}")
        g = len(self.data["grid"]["points"])
        for key in GRID_ARRAYS:
            if len(self.data[key]) != g:
                raise MapFormatError(f"grid array '{key}' has {len(self.data[key])} values, expected {g}")
        cells_burg, cells_state = self.data["burg"], self.data["state"]
        for b in self.live_burgs():
            if cells_burg[b["cell"]] != b["i"]:
                raise MapFormatError(f"burg array check failed at burg {b['i']}")
            if cells_state[b["cell"]] != b.get("state", 0):
                raise MapFormatError(f"state array check failed at burg {b['i']}")
        for p in self.data["provinces"]:
            if isinstance(p, dict) and not p.get("removed") and self.data["province"][p["center"]] != p["i"]:
                raise MapFormatError(f"province array check failed at province {p['i']}")

    # ---------------------------------------------------------------- accessors
    @property
    def settings(self) -> dict:
        return self.data["settings"]

    @property
    def name(self) -> str:
        return self.settings.get("lore", {}).get("name") or self.path.stem.split(" ")[0]

    @property
    def seed(self) -> str:
        return str(self.settings["seed"])

    @property
    def mi_per_px(self) -> float:
        return float(self.settings["units"]["distance"]["scale"])

    @property
    def distance_unit(self) -> str:
        return self.settings["units"]["distance"]["unit"]

    @property
    def calendar(self) -> dict:
        return self.settings.get("lore", {}).get("calendar", {})

    @property
    def cell_count(self) -> int:
        return len(self.data["biome"])

    def cell(self, key: str) -> list:
        return self.data[key]

    def transport(self, name: str) -> dict:
        for t in self.settings["transports"]:
            if t["name"] == name:
                return t
        raise KeyError(f"transport '{name}' not defined in settings")

    def live(self, key: str) -> list[dict]:
        return [x for x in self.data[key] if isinstance(x, dict) and not x.get("removed")]

    def live_burgs(self) -> list[dict]:
        return [b for b in self.live("burgs") if b.get("i")]

    def burg(self, i: int) -> dict:
        return self.data["burgs"][i]

    def burg_by_name(self, name: str) -> dict | None:
        key = name.casefold()
        return next((b for b in self.live_burgs() if b["name"].casefold() == key), None)

    def state(self, i: int) -> dict:
        return self.data["states"][i]

    def culture(self, i: int) -> dict:
        return self.data["cultures"][i]

    def religion(self, i: int) -> dict:
        return self.data["religions"][i]

    def zones_of_cell(self, cell: int) -> list[dict]:
        return [z for z in self.live("zones") if cell in set(z["cells"])]

    def namebase_overrides(self) -> dict[int, dict]:
        """Per-world namebase edits; the name list is empty when it equals Azgaar's default."""
        out = {}
        for i, chunk in enumerate(self.data["namesdata"].split("/")):
            parts = chunk.split("|")
            if len(parts) >= 6:
                out[i] = {"name": parts[0], "min": int(parts[1]), "max": int(parts[2]),
                          "d": parts[3], "b": parts[5]}
        return out

    def summary(self) -> dict:
        routes = self.live("routes")
        groups: dict[str, int] = {}
        for r in routes:
            groups[r["group"]] = groups.get(r["group"], 0) + 1
        return {
            "world": self.name, "file": self.path.name, "version": self.version,
            "calendar": f"{self.calendar.get('year')} {self.calendar.get('eraShort', '')}".strip(),
            "scale": f"{self.mi_per_px:g} {self.distance_unit} per px", "pack_cells": self.cell_count,
            "burgs": len(self.live_burgs()), "states": len(self.live("states")) - 1,
            "routes": groups, "markers": len(self.live("markers")), "zones": len(self.live("zones")),
            "journeys": [j["name"] for j in self.data["journeys"]],
        }
