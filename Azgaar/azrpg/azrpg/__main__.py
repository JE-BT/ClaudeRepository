"""azrpg command line.

    python -m azrpg build <World> [--repo PATH] [--out DIR] [--map FILE]
    python -m azrpg pack  <World> [--repo PATH] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import build_html, world_files
from .pack import PackBuilder


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="azrpg")
    ap.add_argument("cmd", choices=["build", "pack"])
    ap.add_argument("world")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]), help="folder holding world folders (default: Azgaar/)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--map", default=None)
    a = ap.parse_args(argv)
    mp, cells = world_files(Path(a.repo), a.world, a.map)
    if a.cmd == "build":
        out = Path(a.out or "out") / f"{a.world}_rpg.html"
        print(json.dumps(build_html(mp, cells, out, a.world), indent=1))
    else:
        out = Path(a.out or f"{a.world}.azrpg")
        out.write_bytes(PackBuilder(mp, cells, a.world).build())
        print(out)


if __name__ == "__main__":
    main()
