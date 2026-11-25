"""azdev: move an Azgaar world to the full development scale without a ladder.

    python -m azdev build Batan            run the ensemble and write the upload package to out/Batan/
    python -m azdev info Batan             what the world holds, nothing run
See README.md for every option."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import catalogue
from .derive import derive
from .development import DevelopmentField
from .ensemble import run_ensemble
from .graph import PackGraph
from .mapfile import AzgaarMap, MapFormatError, find_map
from .model import Model, draw_params
from .outputs import Package
from .report import html_report, instructions
from .world import World


def world_folder(name: str, root: str | None) -> Path:
    p = Path(name)
    if p.suffix == ".map" and p.exists():
        return p.parent
    if p.is_dir():
        return p
    here = Path(__file__).resolve().parent.parent
    for base in [Path(root)] if root else [Path.cwd(), Path.cwd() / "Azgaar", here.parent, here]:
        if (base / name).is_dir():
            return base / name
    sys.exit(f"no world folder called {name} (looked under {root or 'the current folder, ./Azgaar and beside azdev'})")


def load(args):
    folder = world_folder(args.world, args.root)
    mpath = Path(args.world) if args.world.endswith(".map") else find_map(folder, args.map)
    print(f"world: {folder.name} ({mpath.name})")
    m = AzgaarMap(mpath)
    pg = PackGraph(m)
    cat = catalogue.load(args.catalogue)
    for w_ in cat.warnings:
        print("  catalogue:", w_)
    w = World(m, pg, cat)
    return folder, mpath, m, pg, cat, w


def cmd_info(args):
    folder, mpath, m, pg, cat, w = load(args)
    dev = np.asarray(m.cell("development"))
    port = DevelopmentField(m, pg).generate()
    same = float(np.mean(port == dev))
    print(f"  version {m.version}, {m.cell_count} cells, {len(m.live_burgs())} burgs, {len(m.live('cultures')) - 1} cultures, "
          f"{len(m.goods)} goods")
    print(f"  development port reproduces {same:.1%} of the saved field")
    print(f"  {w.N} communities (culture x province)")
    for c in m.live("cultures"):
        if c.get("i"):
            print(f"    {c['i']:3d} {c['name']:20s} {c.get('type', ''):9s} development {c.get('development')}")


def cmd_build(args):
    t0 = time.time()
    folder, mpath, m, pg, cat, w = load(args)
    model = Model(w, cat, start=args.start)
    scen = args.scenarios.split(",") if args.scenarios else None
    steps = args.steps
    if args.target_max:
        print(f"finding a horizon at which the leading edge reaches {args.target_max} ...")
        probe = steps
        while probe <= args.max_steps:
            r = model.run(draw_params(cat, "S5", np.random.default_rng(1), 1), probe)
            edge = float(np.percentile(r.D, 95))
            print(f"  {probe} steps: leading edge {edge:.0f}")
            if edge >= args.target_max:
                break
            probe *= 2
        steps = min(probe, args.max_steps)
    print(f"running {len(scen or cat.scenarios['scenarios'])} scenarios x {args.seeds} seeds, {steps} steps ...")
    runs = run_ensemble(model, cat, steps, args.seeds, scen, workers=args.workers)
    extra = {}
    if args.diagnose:
        print("diagnostic runs: geography shuffled (F5), attention fixed (F6) ...")
        shuffled = Model(w, cat, start=args.start, shuffle_geography=True)
        extra["shuffled"] = run_ensemble(shuffled, cat, steps, 1, scen, base_seed=7, workers=args.workers, log=None)
        extra["fixed_attention"] = run_ensemble(model, cat, steps, 1, scen, base_seed=7, fixed_attention=True,
                                                workers=args.workers, log=None)
    print("deriving axes, basins and checks ...")
    d = derive(model, runs, cat, extra, depth_stat=args.depth_stat)
    opts = {"biome_offsets": args.biome_offsets, "retitle": args.retitle, "rebase": not args.no_rebase,
            "base_goods": not args.no_base_goods, "eras": not args.keep_eras}
    pkg = Package(m, pg, w, cat, model, d, opts)
    out = Path(args.out) / m.name
    res = pkg.write(out)
    inst = instructions(m.name, res["files"], res, opts)
    (out / "0 Read me first.md").write_text(inst, encoding="utf-8")
    info = {"runs": len(runs), "scenarios": len(scen or cat.scenarios["scenarios"]), "seeds": args.seeds,
            "steps": steps, "start": "present map" if args.start == "present" else "first foragers",
            "depth_stat": args.depth_stat}
    (out / f"{m.name} azdev report.html").write_text(html_report(m.name, mpath.name, opts, cat, d, res, inst, info),
                                                      encoding="utf-8")
    summary = {"world": m.name, "map": mpath.name, **info,
               "cultures": [{k: r[k] for k in ("Id", "Name", "old", "Development", "basin")} | {"target": round(r["target"], 1)}
                            for r in res["cultures"]],
               "basins": [{"name": b["name"], "top": b["top"], "robust": b["robust"]} for b in d.basins],
               "diagnostics": d.diagnostics, "new_goods": [g["name"] for g in res["new_goods"]],
               "states_retitled": [{k: s[k] for k in ("Id", "State", "old", "Form")} for s in res["states"]]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}/ in {time.time() - t0:.0f}s")
    for name in sorted(res["files"]):
        print("  ", name)
    print("   0 Read me first.md")
    print(f"   {m.name} azdev report.html")
    for x in d.diagnostics:
        flag = "FAIL" if x["failed"] else "ok  " if x["failed"] is False else "--  "
        print(f"  {flag} {x['id']} {x['name']}: {x['detail']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="azdev", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "info"):
        p = sub.add_parser(name)
        p.add_argument("world", help="world folder name (Azgaar/<World>), a folder, or a .map file")
        p.add_argument("--map", help="a .map file in the world folder (default: the newest)")
        p.add_argument("--root", help="folder that holds the world folders")
        p.add_argument("--catalogue", help="folder with your own copies of the data/*.json files")
    b = sub.choices["build"]
    b.add_argument("--steps", type=int, default=2500, help="length of each run; one step is a few years (2500)")
    b.add_argument("--seeds", type=int, default=3, help="runs per scenario (3)")
    b.add_argument("--scenarios", help="comma-separated scenario ids (default: all seven)")
    b.add_argument("--start", choices=["present", "origins"], default="present",
                   help="start from the map as it is (present) or from first foragers (origins)")
    b.add_argument("--target-max", type=int, help="lengthen the runs until the leading edge reaches this level")
    b.add_argument("--max-steps", type=int, default=6000, help="cap for --target-max (6000)")
    b.add_argument("--depth-stat", type=float, default=50,
                   help="which history sets each people's level: 50 the median run (default), 75 or 90 more "
                        "favourable ones, where more of the ensemble's deep paths were taken")
    b.add_argument("--biome-offsets", choices=["derived", "keep", "zero"], default="derived",
                   help="biome development offsets: from the run (derived), as they are (keep), or none (zero)")
    b.add_argument("--retitle", choices=["fix", "basin", "none"], default="fix",
                   help="state titles: fix tribal titles that no longer fit (fix), title every state by its "
                        "capital's basin (basin), or leave them (none)")
    b.add_argument("--no-rebase", action="store_true", help="leave the culture multipliers of existing goods alone")
    b.add_argument("--no-base-goods", action="store_true", help="add no goods below tier 36 (root crops, fermented milk)")
    b.add_argument("--keep-eras", action="store_true", help="keep the era names")
    b.add_argument("--diagnose", action="store_true", help="also run failure checks F5 and F6 (more runs)")
    b.add_argument("--workers", type=int, help="parallel processes (default: all cores)")
    b.add_argument("--out", default="out", help="output folder (out)")
    args = ap.parse_args(argv)
    if args.cmd == "build" and args.retitle == "none":
        args.retitle = "never"
    try:
        {"build": cmd_build, "info": cmd_info}[args.cmd](args)
    except MapFormatError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
