"""Build a playable world: one standalone HTML file (engine + world pack, no other files needed).

    python -m azrpg build Pyeongak --repo ../ClaudeRepository/Azgaar --out out/

The world's folder must hold a .map and a Cells GeoJSON export; the newest .map is used unless
--map is given, and the Cells export is matched to the map by content.
"""
from __future__ import annotations

import json
from pathlib import Path

from .cells import find_cells_file
from .mapfile import AzgaarMap
from .pack import PackBuilder

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT.parent / "engine"


def world_files(repo: Path, world: str, map_name: str | None = None) -> tuple[Path, Path]:
    folder = repo / world
    if not folder.is_dir():
        hits = [p for p in repo.iterdir() if p.is_dir() and p.name.lower() == world.lower()]
        if not hits:
            raise FileNotFoundError(f"no folder {world} in {repo}")
        folder = hits[0]
    maps = sorted(folder.glob("*.map"), key=lambda p: p.name)
    if map_name:
        maps = [p for p in maps if p.name == map_name]
    if not maps:
        raise FileNotFoundError(f"no .map in {folder}")
    mp = maps[-1]
    cells = find_cells_file(folder, AzgaarMap(mp))
    if not cells:
        raise FileNotFoundError(f"no Cells GeoJSON in {folder} matches {mp.name}; export one from Azgaar (Export > GeoJSON > Cells)")
    return mp, cells


def engine_js() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((ENGINE / "src").glob("*.js")))


def build_html(map_path: Path, cells_path: Path, out: Path, folder_name: str | None = None) -> dict:
    pb = PackBuilder(map_path, cells_path, folder_name)
    b64 = pb.build_b64()
    content = json.loads((ROOT / "data" / "descriptions_azork.json").read_text(encoding="utf-8"))
    content = {k: content[k] for k in ("biomes", "height") if k in content}
    title = (pb.m.data["journeys"][0]["name"] if pb.m.data["journeys"] else pb.m.name) + " · azrpg"
    shell = (ENGINE / "shell.html").read_text(encoding="utf-8")
    html = (shell.replace("__TITLE__", title).replace("__CONTENT__", json.dumps(content, ensure_ascii=False))
            .replace("__ENGINE__", engine_js()).replace("__PACK__", b64))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return {"html": str(out), "bytes": len(html.encode("utf-8")), "pack_b64": len(b64), "grid": pb.grid.to_dict(),
            "report": pb.raster.report, "map": map_path.name, "cells": cells_path.name}
