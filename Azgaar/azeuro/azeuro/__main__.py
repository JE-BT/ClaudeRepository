"""azeuro: a merchant-commission Eurogame from an Azgaar world.

    python -m azeuro build Batan                  # everything, SVG, PNG and sprite sheets, into out/Batan/
    python -m azeuro build Batan --formats svg    # vector only
    python -m azeuro build Lania --only board,budget
    python -m azeuro info Batan                   # network and deck summary, no drawing
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import DEFAULT_COLOURS, PARTS, build


def main(argv=None):
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(prog="azeuro", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "info"])
    ap.add_argument("world", help="world name (a folder under the Azgaar folder), a folder, or a .map file")
    ap.add_argument("--map", help="use this .map file name inside the world folder (default: newest)")
    ap.add_argument("--root", action="append", type=Path, help="folder holding world folders (repeatable)")
    ap.add_argument("--out", type=Path, default=here.parent / "out")
    ap.add_argument("--formats", default="svg,png", help="svg, png or svg,png")
    ap.add_argument("--only", help="comma list of: " + ",".join(PARTS))
    ap.add_argument("--dpi", type=int, default=300, help="PNG resolution for cards and budget boards")
    ap.add_argument("--board-width", type=int, default=7200, help="board PNG width in pixels")
    ap.add_argument("--jobs", type=int, default=0, help="parallel PNG workers (default: CPU count, max 8)")
    ap.add_argument("--full-colour", action="store_true", help="store card PNGs in full colour, not 256-colour")
    ap.add_argument("--no-sheets", action="store_true", help="skip the screentop.gg sprite sheets")
    ap.add_argument("--sheet-dpi", type=int, default=200, help="card resolution on sprite sheets")
    ap.add_argument("--sheet-max", type=int, default=4096, help="largest sprite sheet side in pixels")
    g = ap.add_argument_group("network")
    g.add_argument("--spacing", type=float, default=0.016, help="minimum gap between city stops, x map width")
    g.add_argument("--neutral", type=int, help="number of neutral stations (default: half the states, 3-6)")
    g.add_argument("--air", type=int, help="number of air sites when the map names none (default: states/2 + 2, 4-7)")
    g.add_argument("--air-overlap", type=int, default=1, help="air sites that may also be neutral stations")
    g.add_argument("--remote", type=float, default=0.015, help="marker distance beyond which a star is remote (air), x map width")
    g = ap.add_argument_group("commissions")
    g.add_argument("--income-k", type=float, default=0.75, help="income = k x stops x value tier")
    g.add_argument("--income-min", type=int, default=2)
    g.add_argument("--income-max", type=int, default=20)
    g.add_argument("--min-deck", type=int, default=6, help="pad smaller state decks with copies")
    g.add_argument("--min-value", type=float, default=0.0, help="drop deals worth less (units x price)")
    g.add_argument("--max-per-state", type=int, help="keep only the N most valuable deals in each deck")
    g.add_argument("--neutral-deck", action="store_true", help="also make a deck for unclaimed land")
    g = ap.add_argument_group("events, houses, infrastructure")
    g.add_argument("--events", type=int, help="event deck size (default: the largest colour pool, so every marker text is used; at least 30)")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--players", type=int, default=6)
    g.add_argument("--colours", help="comma list of player colours (hex)")
    g.add_argument("--infra-land", type=int, default=50, help="land cards; sea and air follow cost (50/2, 50/5)")
    g.add_argument("--wild-share", type=float, default=0.12)
    a = ap.parse_args(argv)

    roots = (a.root or []) + [here.parent.parent, Path.cwd()]
    opts = {"map": a.map, "formats": [f.strip() for f in a.formats.split(",") if f.strip()],
            "only": [p.strip() for p in a.only.split(",")] if a.only else None, "dpi": a.dpi,
            "board_width": a.board_width, "jobs": a.jobs, "palette": not a.full_colour, "sheets": not a.no_sheets,
            "sheet_dpi": a.sheet_dpi, "sheet_max": a.sheet_max, "spacing": a.spacing, "neutral": a.neutral, "air": a.air,
            "air_overlap": a.air_overlap, "remote": a.remote, "income_k": a.income_k, "income_min": a.income_min,
            "income_max": a.income_max, "min_deck": a.min_deck, "min_value": a.min_value,
            "max_per_state": a.max_per_state, "neutral_deck": a.neutral_deck, "events": a.events, "seed": a.seed,
            "players": a.players, "colours": a.colours.split(",") if a.colours else DEFAULT_COLOURS,
            "infra_land": a.infra_land, "wild_share": a.wild_share}
    if a.command == "info":
        opts["only"] = []
        opts["formats"] = []
    s = build(a.world, roots, a.out, opts)
    n, c = s["network"], s["commissions"]
    print(f"{s['world']} ({s['map']}): {n['stops']} stops, {n['links']} links, stars {n['stars']}")
    print(f"  neutral: {', '.join(n['neutral'])}")
    print(f"  air:     {', '.join(n['air'])}")
    print(f"  decks:   {json.dumps(c['decks'])}")
    print(f"  events:  {s['events']['cards']} cards, positive share {s['events']['positive_share']}")
    print(f"  infrastructure: {s['infrastructure']}")
    if a.command == "build":
        print(f"  written to {a.out / s['world']}")


if __name__ == "__main__":
    main()
