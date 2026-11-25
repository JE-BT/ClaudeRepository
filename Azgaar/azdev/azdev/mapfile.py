"""Read and patch an Azgaar .map save (format 1.157 and later). Adapted from azeuro.mapfile.

The file is a CRLF-joined list of 56 fields (Azgaar's src/services/io/save.ts). Bare LF characters
occur inside the embedded SVG, so the file is split on CRLF only. Field positions come from the
save routine, and every field is then checked against a content signature before use.

Patching rewrites whole fields and leaves every other byte of the file as it was.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

MIN_VERSION = (1, 157, 0)  # cells.development and culture/biome/good development first saved here

# index -> (key, kind); kinds: json, ints, floats, text
LAYOUT: dict[int, tuple[str, str]] = {
    0: ("params", "text"), 1: ("settings", "json"), 3: ("biomes", "json"), 6: ("grid", "json"),
    7: ("grid_h", "ints"), 8: ("grid_prec", "ints"), 9: ("grid_f", "ints"), 10: ("grid_t", "ints"),
    11: ("grid_temp", "ints"), 12: ("features", "json"), 13: ("cultures", "json"), 14: ("states", "json"),
    15: ("burgs", "json"), 16: ("biome", "ints"), 17: ("burg", "ints"), 19: ("culture", "ints"),
    20: ("fl", "ints"), 21: ("pop", "floats"), 22: ("river", "ints"), 25: ("state", "ints"),
    26: ("religion", "ints"), 27: ("province", "ints"), 29: ("religions", "json"), 30: ("provinces", "json"),
    31: ("namesdata", "text"), 35: ("markers", "json"), 36: ("cell_routes", "json"), 37: ("routes", "json"),
    38: ("zones", "json"), 40: ("good", "ints"), 42: ("markets", "json"), 43: ("deals", "json"),
    44: ("market", "ints"), 51: ("override", "json"), 55: ("development", "ints"),
}
PACK_ARRAYS = ("biome", "burg", "culture", "fl", "pop", "river", "state", "religion", "province", "good",
               "market", "development")
GRID_ARRAYS = ("grid_h", "grid_prec", "grid_f", "grid_t", "grid_temp")


def _first(items: list) -> Any:
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
    "settings": _has("seed", "units", "goods", "eras"), "grid": _has("spacing", "points", "boundary"),
    "biomes": _has("habitability"), "features": _has("land", "cells"), "cultures": _has("base"),
    "states": _has("neighbors", "diplomacy"), "burgs": _has("population", "cell"),
    "religions": lambda v: isinstance(v, list) and bool(v) and v[0].get("name") == "No religion",
    "provinces": _has("formName", "center"), "markers": _has("icon", "cell"),
    "routes": _has("group", "points"), "zones": _has("cells", "type"), "markets": _has("centerBurgId"),
}


def split_fields(raw: str) -> list[str]:
    """Fields are joined by CRLF. A file that lost its CRs (git normalisation) is rejoined around the SVG."""
    if "\r\n" in raw:
        return raw.split("\r\n")
    lines = raw.split("\n")
    try:
        s = next(i for i, l in enumerate(lines) if l.startswith("<svg"))
        e = next(i for i, l in enumerate(lines) if i >= s and l.rstrip().endswith("</svg>"))
    except StopIteration:
        return lines
    return lines[:s] + ["\n".join(lines[s:e + 1])] + lines[e + 1:]


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split(".")[:3] if x.isdigit())


class MapFormatError(ValueError):
    pass


class AzgaarMap:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8", newline="") as fh:
            raw = fh.read()
        self.crlf = "\r\n" in raw
        self.fields = split_fields(raw)
        self.version = self.fields[0].split("|")[0]
        if version_tuple(self.version) < MIN_VERSION:
            raise MapFormatError(
                f"{self.path.name} is format {self.version}. azdev needs 1.157 or later, where development is "
                "saved: open the map in the current Generator, save it, and run again.")
        if len(self.fields) < 56:
            raise MapFormatError(f"{self.path.name}: expected 56 CRLF fields, found {len(self.fields)}")
        self.data: dict[str, Any] = {}
        for index, (key, kind) in LAYOUT.items():
            self.data[key] = self._parse(self.fields[index], kind, key)
        self._verify()

    def _parse(self, text: str, kind: str, key: str) -> Any:
        if kind == "text":
            return text
        if kind == "json":
            if not text:
                return {} if key in ("cell_routes", "override") else []
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
        n = len(self.data["biome"])
        for key in PACK_ARRAYS:
            if self.data[key] and len(self.data[key]) != n:
                raise MapFormatError(f"pack array '{key}' has {len(self.data[key])} values, expected {n}")
        g = len(self.data["grid"]["points"])
        for key in GRID_ARRAYS:
            if len(self.data[key]) != g:
                raise MapFormatError(f"grid array '{key}' has {len(self.data[key])} values, expected {g}")
        for b in self.live_burgs():
            if self.data["burg"][b["cell"]] != b["i"]:
                raise MapFormatError(f"burg array check failed at burg {b['i']}")
            if self.data["state"][b["cell"]] != b.get("state", 0):
                raise MapFormatError(f"state array check failed at burg {b['i']}")
        for c in self.live("cultures"):
            if c.get("i") and c.get("center") is not None and self.data["culture"][c["center"]] != c["i"]:
                # a culture center can drift after edits; only warn through the summary
                c["_center_drift"] = True

    # ------------------------------------------------------------------ accessors
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
    def cell_count(self) -> int:
        return len(self.data["biome"])

    @property
    def goods(self) -> list[dict]:
        return self.settings["goods"]

    def cell(self, key: str) -> list:
        return self.data[key]

    def live(self, key: str) -> list[dict]:
        return [x for x in self.data[key] if isinstance(x, dict) and not x.get("removed")]

    def live_burgs(self) -> list[dict]:
        return [b for b in self.live("burgs") if b.get("i")]

    def good_by_name(self) -> dict[str, dict]:
        return {g["name"]: g for g in self.goods}

    # ------------------------------------------------------------------ patching
    def write_patched(self, out: Path, replace: dict[int, str]) -> None:
        """Write a copy of the file with whole fields replaced; every other field is kept byte for byte."""
        fields = list(self.fields)
        for index, text in replace.items():
            fields[index] = text
        sep = "\r\n" if self.crlf else "\n"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            fh.write(sep.join(fields))


def compact_json(value: Any) -> str:
    """JSON as the Generator writes it (JSON.stringify: no spaces)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def find_map(folder: Path, explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() or p.exists() else folder / explicit
    maps = sorted(folder.glob("*.map"))
    if not maps:
        raise FileNotFoundError(f"no .map file in {folder}")
    return maps[-1]  # names end in the save date, so the last sorts newest
