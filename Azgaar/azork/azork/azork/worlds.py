"""Find a world's files in the repository's Azgaar folder.

Rules (from the Project instructions):
  * a world's files start with the world name, or sit in a subfolder of that name;
  * with several saves of one type, the newest date in the filename wins unless a date is given;
  * unprefixed Watabou files are matched to burgs by name; dwellings and dungeons are
    assigned by naming convention, the content manifest, or ledger anchors.
Naming conventions for new uploads:
  <burg>.json                 town or village plan (City or Village Generator export)
  <burg>--<label>.json        dwelling inside that burg (Dwellings export)
  dungeon-<marker id>.json    One Page Dungeon export for that marker
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ledger as ledger_mod
from . import watabou
from .mapfile import AzgaarMap

DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def file_date(path: Path) -> str:
    m = DATE.search(path.name)
    return "-".join(m.groups()) if m else ""


@dataclass
class WatabouFile:
    path: Path
    kind: str                     # city, village, dwelling, dungeon, unknown
    burg: int | None = None
    marker: int | None = None
    building: int | None = None   # index in the burg's town file (dwellings)
    label: str = ""
    assigned_by: str = ""         # filename, manifest, ledger


@dataclass
class World:
    name: str
    root: Path
    map_path: Path
    cells_path: Path | None
    ledger_paths: list[Path]
    watabou: list[WatabouFile]
    other: list[Path]
    problems: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    _map: AzgaarMap | None = None

    @property
    def map(self) -> AzgaarMap:
        if self._map is None:
            self._map = AzgaarMap(self.map_path)
        return self._map

    @property
    def content_dir(self) -> Path:
        return self.map_path.parent / "content"

    @property
    def main_ledger(self) -> Path | None:
        mains = [p for p in self.ledger_paths if p.stem.casefold() == f"{self.name}_ledger".casefold()]
        return mains[0] if mains else None

    def towns(self) -> dict[int, WatabouFile]:
        return {w.burg: w for w in self.watabou if w.kind in ("city", "village") and w.burg}

    def dwellings(self) -> list[WatabouFile]:
        return [w for w in self.watabou if w.kind == "dwelling"]


def _candidates(root: Path, world: str) -> list[Path]:
    key = world.casefold()
    out = [p for p in root.iterdir() if p.is_file() and p.name.strip().casefold().startswith(key)]
    sub = next((d for d in root.iterdir() if d.is_dir() and d.name.casefold() == key), None)
    if sub:
        out += [p for p in sub.rglob("*") if p.is_file() and "content" not in p.relative_to(sub).parts[:1]]
    return out


def _newest(paths: list[Path], date: str | None) -> Path | None:
    if date:
        paths = [p for p in paths if file_date(p).startswith(date)]
    return max(paths, key=file_date) if paths else None


def available(root: Path) -> list[str]:
    names = {p.name.split(" ")[0] for p in root.glob("*.map")}
    names |= {d.name for d in root.iterdir() if d.is_dir() and any(d.glob("*.map"))}
    return sorted(names)


def find(world: str, root: str | Path, date: str | None = None) -> World:
    root = Path(root)
    files = _candidates(root, world)
    maps = [p for p in files if p.suffix == ".map" and p.stat().st_size > 100]
    map_path = _newest(maps, date)
    if not map_path:
        raise FileNotFoundError(f"No usable .map for '{world}' under {root}")
    cells = _newest([p for p in files if p.suffix == ".geojson" and "cells" in p.name.casefold()], date)
    ledgers = [p for p in files if p.suffix == ".md" and "_ledger" in p.name.casefold()]
    w = World(world, root, map_path, cells, ledgers, [], [])
    used = {map_path, cells, *ledgers}
    for p in files:
        if p in used or p.suffix == ".map" or "cells" in p.name.casefold():
            continue
        if p.suffix == ".json":
            kind, _ = watabou.sniff(p)
            w.watabou.append(WatabouFile(p, kind))
        else:
            w.other.append(p)
    _assign(w)
    return w


def _assign(w: World) -> None:
    m = w.map
    by_name = {norm(b["name"]): b["i"] for b in m.live_burgs()}
    for f in w.watabou:
        stem = f.path.stem
        if f.kind in ("city", "village"):
            f.burg, f.assigned_by = by_name.get(norm(stem)), "filename"
            if f.burg is None:
                w.problems.append(f"{f.path.name}: town plan matches no burg name")
        elif f.kind == "dwelling" and "--" in stem:
            burg, label = stem.split("--", 1)
            f.burg, f.label, f.assigned_by = by_name.get(norm(burg)), label.replace("-", " "), "filename"
        elif f.kind == "dungeon" and (mm := re.match(r"dungeon-(\d+)$", stem)):
            f.marker, f.assigned_by = int(mm.group(1)), "filename"
    manifest = w.content_dir / "manifest.json"
    if manifest.exists():
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        for f in w.watabou:
            entry = spec.get("files", {}).get(f.path.name)
            if entry:
                f.burg = entry.get("burg", f.burg)
                f.building = entry.get("building", f.building)
                f.marker = entry.get("marker", f.marker)
                f.label = entry.get("label", f.label)
                f.assigned_by = "manifest"
    if w.main_ledger:
        _assign_from_ledger(w, ledger_mod.parse(w.main_ledger), by_name)
    for f in w.watabou:
        if f.kind == "dwelling" and f.burg is None:
            w.problems.append(f"{f.path.name}: dwelling not assigned to a burg")
        if f.kind == "unknown":
            w.problems.append(f"{f.path.name}: unrecognised JSON (a One Page Dungeon export would be the first sample)")


def _assign_from_ledger(w: World, led: ledger_mod.Ledger, by_name: dict[str, int]) -> None:
    """A ledger entry anchored to 'building N in town.json' and 'house.json' places the dwelling."""
    files = {f.path.name.casefold(): f for f in w.watabou}
    for e in led.entries:
        for a in e.anchors:
            if a.kind == "file" and a.file.casefold() not in files:
                w.notices.append(f"ledger entry '{e.name}' names {a.file}, which is not in {w.map_path.parent.name}/")
        b = next((a for a in e.anchors if a.kind == "building" and a.file), None)
        if not b:
            continue
        town = files.get(b.file.casefold())
        for a in e.anchors:
            f = files.get((a.file or "").casefold()) if a.kind == "file" else None
            if f and f.kind == "dwelling" and f.burg is None and town and town.burg:
                f.burg, f.building, f.label, f.assigned_by = town.burg, b.id, e.name, "ledger"
