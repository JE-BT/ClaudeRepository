"""azork command line.

  python -m azork worlds                 list worlds in the repository
  python -m azork inspect Lania          what was loaded, and any problems
  python -m azork plan Lania             the journey plan as a travel table
  python -m azork setup Lania            files the story needs (required) and can add later (--all)
  python -m azork validate Lania         load every file of the world and report
  python -m azork play Lania --scene dungeon:5   play a scene (--list shows the scenes)
  python -m azork place Lania house.json --burg Bayfshear [--best | --building N] [--label "Name"]
  python -m azork pick Lania Bayfshear --dwelling house.json   click the house's building on a map
  python -m azork new Lania                       start a campaign: the journey's story and its opening
  python -m azork story Lania                     the campaign's storylines (designer's view, spoilers)
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
    for note in w.notices:
        print(f"  note: {note}")
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
    for note in w.notices:
        print(f"note: {note}")
    return 1 if errors else 0


def cmd_new(args) -> int:
    """Start a campaign: generate the journey's story and show its opening."""
    from .campaign import Campaign
    w = _world(args)
    c, msgs = Campaign.new(w, args.name)
    if c.path.exists() and not args.force:
        print(f"A campaign called '{args.name}' already exists ({c.path.name}); use --force to replace it.")
        return 1
    c.save()
    main = c.story.line("main")
    print(f"{main.title} ({c.journey.type})\n")
    for m in msgs:
        print(m + "\n")
    print(f"Saved {c.path.name}. Play a scene with: python -m azork play {w.name} --scene <scene>")
    return 0


def cmd_story(args) -> int:
    """Designer's view of a campaign's storylines (spoilers)."""
    from .campaign import Campaign
    w = _world(args)
    c = Campaign.load(w, args.name) or Campaign.new(w, args.name)[0]
    label = lambda t: c.journey.label(t)
    print(f"Clock: {label(c.t)}; position stage {c.pos[0]}, mile {c.pos[1]:.0f}; score {c.story.score}/{c.story.max_score}")
    for s_ in c.story.storylines:
        print(f"\n[{s_.kind}] {s_.title} ({s_.status})")
        for p in s_.phases:
            where = f"stage {p.pos[0]}, mile {p.pos[1]:.0f}" if p.pos else ""
            print(f"  {p.status:6} {p.title}: {p.objective} {('(' + where + ')') if where else ''}")
        for e in s_.elements.values():
            print(f"  element {e.role}: {e.spec['name']} at {e.anchor} {'(placed)' if e.placed else ''}")
    return 0


def cmd_play(args) -> int:
    from . import ledger_export, scenes
    from .campaign import Campaign
    from .engine.game import Game
    w = _world(args)
    if args.list or not args.scene:
        print("Scenes: " + ", ".join(scenes.list_scenes(w)))
        return 0
    project = Path(__file__).resolve().parents[1]
    campaign = None if args.no_campaign else Campaign.load(w, args.campaign)
    if campaign is None and not args.no_campaign:
        print(f"(No campaign '{args.campaign}' yet: playing the scene on its own. Start one with: python -m azork new {w.name})")
    game = Game(scenes.build(w, args.scene, campaign), project / "saves", campaign)
    print(game.intro())
    while not game.quit_requested:
        try:
            line = input("\n> ")
        except EOFError:
            break
        print(game.step(line))
    if campaign is not None:
        campaign.leave(game.w)
        print(f"Campaign saved ({campaign.save().name}). {campaign.schedule(campaign.t, None, lambda t: game.w.clock.label(t, game.w.lat))}")
    transcript = project / "saves" / "transcripts" / f"{w.name}-{args.scene.replace(':', '-')}.txt"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n\n".join(f"> {c}\n{o}" for c, o in game.log), encoding="utf-8")
    print(f"Transcript saved to {transcript}.")
    if w.main_ledger and not args.no_export:
        choice = ""
        while choice not in ("keep", "discard", "fork"):
            try:
                choice = input("Export this session to the ledger? keep / discard / fork: ").strip().lower()
            except EOFError:
                choice = "discard"
        branch = input("Branch name: ").strip() if choice == "fork" else None
        target = ledger_export.export(w.main_ledger, game, choice, branch)
        print(f"Session written to {target.name}." if target else "Nothing written to the ledger.")
    return 0


def cmd_place(args) -> int:
    """Rank a town's buildings for a Dwellings export; with --building, record the placement."""
    import json as _json
    from . import placement
    w = _world(args)
    path = w.map_path.parent / args.file
    if not path.exists():
        raise FileNotFoundError(f"{args.file} is not in {w.map_path.parent}")
    burg_name = args.burg or (path.stem.split("--")[0] if "--" in path.stem else None)
    burg = w.map.burg_by_name(burg_name) if burg_name else None
    if not burg:
        raise ValueError("Say which burg the house is in: --burg <name>")
    town = w.towns().get(burg["i"])
    if not town:
        raise FileNotFoundError(f"No town plan for {burg['name']}; add {burg['name'].lower()}.json first")
    ranked = placement.rank(watabou.load(town.path), path, args.top)
    print(f"Best matches for {path.name} in {burg['name']} (shape 1.00 = identical outline):")
    for r in ranked:
        print(f"  building {r['building']:>5}: {r['area']:6.0f} m2, {r['long']:.1f} x {r['short']:.1f} m, "
              f"shape {r['shape'] if r['shape'] is not None else 0:.2f}")
    if ranked and (ranked[0]["shape"] or 0) < 0.95:
        print("  No exact outline match: the house may come from another town or an older plan.")
    if args.building is None and not args.best:
        print("Record one with --building N (or --best), and optionally --label \"Name\".")
        return 0
    building = ranked[0]["building"] if args.best else args.building
    label = args.label or (path.stem.split("--", 1)[1] if "--" in path.stem else path.stem).replace("_", " ")
    manifest = w.content_dir / "manifest.json"
    data = _json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"files": {}}
    data.setdefault("files", {})[path.name] = {"burg": burg["i"], "building": building, "label": label,
                                               "source": "azork place"}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Placed {path.name} as '{label}' in {burg['name']}, building {building} ({manifest.name}).")
    return 0


def cmd_pick(args) -> int:
    from . import pickmap
    w = _world(args)
    burg = w.map.burg_by_name(args.burg)
    if not burg:
        raise ValueError(f"No burg called {args.burg}")
    town = w.towns().get(burg["i"])
    if not town:
        raise FileNotFoundError(f"No town plan for {burg['name']}; add {burg['name'].lower()}.json first")
    dwelling = w.map_path.parent / args.dwelling if args.dwelling else None
    label = args.label or (dwelling.stem.split("--")[-1].replace("_", " ") if dwelling else "")
    html = pickmap.render(town.path, f"{burg['name']} ({w.name})", dwelling, label)

    def on_save(data):
        if not dwelling:
            return "No dwelling given; start with --dwelling <file> to save a placement."
        return pickmap.save_placement(w.content_dir / "manifest.json", dwelling.name, burg["i"],
                                      int(data["building"]), data.get("label") or label)
    server = pickmap.serve(html, on_save, args.port, not args.no_browser)
    print(f"Map of {burg['name']} at http://127.0.0.1:{server.server_address[1]}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _spec_of(t) -> dict:
    from .engine.model import _spec
    spec = _spec(t)
    if t.location not in ("player", None):
        spec["contents_of"] = t.location
    return spec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="azork", description="Azgaar worlds as text adventures")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="folder holding the world files")
    ap.add_argument("--date", default=None, help="use saves from this date (YYYY-MM-DD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("worlds").set_defaults(fn=cmd_worlds)
    for name, fn in (("inspect", cmd_inspect), ("plan", cmd_plan), ("setup", cmd_setup), ("validate", cmd_validate),
                     ("play", cmd_play), ("place", cmd_place), ("new", cmd_new), ("story", cmd_story), ("pick", cmd_pick)):
        p = sub.add_parser(name)
        p.add_argument("world")
        p.add_argument("--journey", type=int, default=0)
        if name == "setup":
            p.add_argument("--all", action="store_true")
        if name == "place":
            p.add_argument("file")
            p.add_argument("--burg")
            p.add_argument("--building", type=int)
            p.add_argument("--best", action="store_true")
            p.add_argument("--label")
            p.add_argument("--top", type=int, default=5)
        if name == "pick":
            p.add_argument("burg")
            p.add_argument("--dwelling")
            p.add_argument("--label")
            p.add_argument("--port", type=int, default=8765)
            p.add_argument("--no-browser", action="store_true")
        if name in ("new", "story", "play"):
            p.add_argument("--campaign" if name == "play" else "--name", default="campaign", dest="campaign" if name == "play" else "name")
        if name == "new":
            p.add_argument("--force", action="store_true")
        if name == "play":
            p.add_argument("--no-campaign", action="store_true")
            p.add_argument("--scene")
            p.add_argument("--list", action="store_true")
            p.add_argument("--no-export", action="store_true")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"azork: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
