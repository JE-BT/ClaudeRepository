"""azork command line.

  python -m azork worlds                 list worlds in the repository
  python -m azork inspect Lania          what was loaded, and any problems
  python -m azork plan Lania             the journey plan as a travel table
  python -m azork setup Lania            files the story needs (required) and can add later (--all)
  python -m azork validate Lania         load every file of the world and report
Options: --root PATH (default: the Azgaar folder beside this project), --date YYYY-MM-DD
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ledger as ledger_mod
from . import setup as setup_mod
from . import watabou, worlds
from .cells import CellGeo
from .journey import Journey

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "Azgaar"


def _world(args) -> worlds.World:
    return worlds.find(args.world, args.root, args.date)


def cmd_worlds(args) -> int:
    for name in worlds.available(Path(args.root)):
        print(name)
    return 0


def cmd_inspect(args) -> int:
    w = _world(args)
    s = w.map.summary()
    print(f"{s['world']}: {s['file']} (format {s['version']}), {s['calendar']}, {s['scale']}")
    print(f"  {s['pack_cells']} cells, {s['burgs']} burgs, {s['states']} states, markers {s['markers']}, "
          f"zones {s['zones']}, routes {s['routes']}")
    print(f"  journeys: {', '.join(s['journeys']) or 'none'}")
    print(f"  cells GeoJSON: {w.cells_path.name if w.cells_path else 'MISSING'}")
    print(f"  ledgers: {', '.join(p.name for p in w.ledger_paths) or 'none'}")
    for f in sorted(w.watabou, key=lambda f: f.kind):
        where = (f"burg {f.burg} {w.map.burg(f.burg)['name']}" if f.burg else
                 f"marker {f.marker}" if f.marker is not None else "unassigned")
        extra = f", building {f.building}" if f.building is not None else ""
        print(f"  {f.kind:8} {f.path.name}: {where}{extra} (by {f.assigned_by or '-'})")
    for p in w.other:
        print(f"  other    {p.name}")
    for problem in w.problems:
        print(f"  ! {problem}")
    return 0


def cmd_plan(args) -> int:
    w = _world(args)
    cfg = setup_mod.world_settings(w)
    j = Journey(w.map, args.journey, cfg["start_day_of_year"])
    print(f"{j.name} ({j.type}): plan, {j.total_days:.1f} days")
    print(f"{'#':>2}  {'stage':34} {'mode':18} {'miles':>6} {'start':28} end")
    for st in j.stages:
        miles = "" if st.is_stay else f"{st.miles:,.0f}"
        print(f"{st.index:>2}  {st.name[:34]:34} {st.transport[:18]:18} {miles:>6} "
              f"{j.label(st.start_t, st.lat):28} {j.label(st.end_t, st.lat)}")
    allowed = cfg["transports_allowed"] or sorted({s.transport for s in j.stages})
    faster = [(st, j.alternatives(st.index, allowed)) for st in j.moving()]
    if any(a for _, a in faster):
        print("\nFaster options (difficulty scales with the share of plan time saved):")
        for st, alts in faster:
            for a in alts:
                print(f"  stage {st.index}: {a['transport']:16} {a['days']:6.1f} days, saves {a['saved']:5.1f} "
                      f"({a['difficulty']:.0%}, {a['level']})")
    return 0


def cmd_setup(args) -> int:
    w = _world(args)
    _, reqs = setup_mod.plan(w, args.journey)
    req = [r for r in reqs if r.tier == "required"]
    missing = [r for r in req if not r.present]
    print(f"{w.name}: {len(req)} files required before the story is generated, {len(missing)} missing")
    for r in req:
        state = f"present ({r.present})" if r.present else "MISSING"
        print(f"  [{state}] {r.kind} {r.id} {r.name}: {'; '.join(r.reasons)}")
        if not r.present:
            print(f"      save as {w.map_path.parent.name}/{r.filename}  <- {r.generator}: {r.link}")
    exp = [r for r in reqs if r.tier == "expansion"]
    print(f"\n{len(exp)} more places in the {setup_mod.world_settings(w)['corridor_mi']:g} mi corridor can be "
          f"generated on demand during play" + ("" if args.all else " (--all lists them)"))
    if args.all:
        for r in exp:
            print(f"  [{'present' if r.present else 'later'}] {r.kind} {r.id} {r.name}, stage {r.stage}, "
                  f"{r.along_mi:,.0f} mi along, {r.offset_mi:.0f} mi off")
    print("\nDwellings are optional: the engine builds interiors itself and uses an assigned Dwellings export "
          "where there is one.")
    return 1 if missing else 0


def cmd_validate(args) -> int:
    w = _world(args)
    errors = 0
    print(f"map: {w.map_path.name} ok ({w.map.version})")
    if w.cells_path:
        problems = CellGeo(w.cells_path, w.map).check_against(w.map)
        print(f"cells: {w.cells_path.name} {'ok' if not problems else '; '.join(problems)}")
        errors += bool(problems)
    for p in w.ledger_paths:
        led = ledger_mod.parse(p)
        print(f"ledger: {p.name} ok ({len(led.entries)} entries)")
    for f in w.watabou:
        try:
            obj = watabou.load(f.path)
            print(f"{f.kind}: {f.path.name} ok ({type(obj).__name__})")
        except Exception as exc:  # report every file, then fail
            errors += 1
            print(f"{f.kind}: {f.path.name} FAILED: {exc}")
    for problem in w.problems:
        errors += 1
        print(f"! {problem}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="azork", description="Azgaar worlds as text adventures")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="folder holding the world files")
    ap.add_argument("--date", default=None, help="use saves from this date (YYYY-MM-DD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worlds").set_defaults(fn=cmd_worlds)
    for name, fn in (("inspect", cmd_inspect), ("plan", cmd_plan), ("setup", cmd_setup), ("validate", cmd_validate)):
        p = sub.add_parser(name)
        p.add_argument("world")
        p.add_argument("--journey", type=int, default=0)
        if name == "setup":
            p.add_argument("--all", action="store_true")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"azork: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
