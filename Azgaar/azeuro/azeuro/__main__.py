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


def _freight(spec):
    if not spec:
        return None
    vals = [float(x) for x in spec.split(",")]
    if len(vals) != 3:
        raise SystemExit("--freight takes three numbers: land,sea,air")
    return dict(zip(("land", "sea", "air"), vals))


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
    g.add_argument("--min-value", type=float, default=0.0, help="drop deals worth less (units x price)")
    g.add_argument("--max-per-trade", type=int, help="keep only the N most valuable deals in each trade deck")
    g.add_argument("--no-slaves", action="store_true", help="leave out the slave trade: no Slaves deck, no slave "
                                                           "decrees, five trades on the budget boards")
    g.add_argument("--freight", help="print freight per cargo pip on cards and boards, as land,sea,air (e.g. 0,1,2); "
                                     "off by default")
    g = ap.add_argument_group("decrees")
    g.add_argument("--decrees", type=int, default=30, help="decree deck size")
    g.add_argument("--seed", type=int, default=1)
    g = ap.add_argument_group("houses and budget boards")
    g.add_argument("--players", type=int, default=6)
    g.add_argument("--colours", help="comma list of player colours (hex)")
    g.add_argument("--goal", type=int, default=50, help="income that ends the game (marked dark on the track)")
    g.add_argument("--start-gold", type=int, default=10)
    g.add_argument("--stations", type=int, default=20, help="stations per player, in rows of five")
    g.add_argument("--overhead", type=int, default=30, help="cost of opening a trade")
    g.add_argument("--home-overhead", type=int, default=20, help="cost of opening one of the house's two home trades")
    g.add_argument("--overhead-mode", choices=["gold", "expense"], default="gold",
                   help="gold: pay N gold each time you open the trade; expense: +N on the expense track while open")
    g.add_argument("--debt-rounds", type=int, default=3,
                   help="rounds in a row a player may end below 0 gold; one more and they are out")
    g.add_argument("--petitions", choices=["turn", "round"], default="turn",
                   help="turn: spend stars in the turn you gain them; round: spend them at the start of the next "
                        "round, with decrees and accounts")
    g.add_argument("--draw", type=int, default=3, help="commission cards drawn at the start of a round (keep one)")
    g = ap.add_argument_group("infrastructure")
    g.add_argument("--infra-land", type=int, default=50, help="land cards; sea and air follow cost (50/2, 50/5)")
    g.add_argument("--wild-share", type=float, default=0.12)
    a = ap.parse_args(argv)

    roots = (a.root or []) + [here.parent.parent, Path.cwd()]
    opts = {"map": a.map, "formats": [f.strip() for f in a.formats.split(",") if f.strip()],
            "only": [p.strip() for p in a.only.split(",")] if a.only else None, "dpi": a.dpi,
            "board_width": a.board_width, "jobs": a.jobs, "palette": not a.full_colour, "sheets": not a.no_sheets,
            "sheet_dpi": a.sheet_dpi, "sheet_max": a.sheet_max, "spacing": a.spacing, "neutral": a.neutral, "air": a.air,
            "air_overlap": a.air_overlap, "remote": a.remote, "income_k": a.income_k, "income_min": a.income_min,
            "income_max": a.income_max, "min_value": a.min_value, "max_per_trade": a.max_per_trade,
            "freight": _freight(a.freight), "decrees": a.decrees, "seed": a.seed, "players": a.players,
            "colours": a.colours.split(",") if a.colours else DEFAULT_COLOURS, "goal": a.goal,
            "start_gold": a.start_gold, "stations": a.stations, "overhead": a.overhead, "home_overhead": a.home_overhead,
            "overhead_mode": a.overhead_mode, "draw": a.draw, "debt_rounds": a.debt_rounds, "petitions": a.petitions,
            "slaves": not a.no_slaves, "infra_land": a.infra_land, "wild_share": a.wild_share}
    if a.command == "info":
        opts["only"] = []
        opts["formats"] = []
    s = build(a.world, roots, a.out, opts)
    n, c = s["network"], s["commissions"]
    print(f"{s['world']} ({s['map']}): {n['stops']} stops, {n['links']} links, stars {n['stars']}")
    print(f"  neutral: {', '.join(n['neutral'])}")
    print(f"  air:     {', '.join(n['air'])}")
    print(f"  decks:   {json.dumps(c['decks'])}")
    d = s["decrees"]
    print(f"  decrees: {d['cards']} cards, " + ", ".join(f"{k} {v}" for k, v in d["families"].items()))
    print("  houses:  " + "; ".join(f"{h['town']} ({' + '.join(h['home_trades'])}; {h['patron']})" for h in s["houses"]))
    print(f"  infrastructure: {s['infrastructure']}")
    if a.command == "build":
        print(f"  written to {a.out / s['world']}")


if __name__ == "__main__":
    main()
