"""Turn one Azgaar world into the full component set: board, decks, decrees, budget boards, tokens."""
from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from collections import Counter

from . import budget, cards, decks
from .decrees import GOLD_SHARED, SETTLE_INCOME, SETTLE_INCOME_WIDE, build_decrees
from .board import Board
from .geo import find_cells
from .mapfile import AzgaarMap
from .network import Network
from .sheets import build_sheets
from .svgkit import save, to_png

DEFAULT_COLOURS = ["#6E3B87", "#2C7873", "#A8551E", "#3B4A9C", "#7A5C2E", "#4B5563"]
PARTS = ("board", "commissions", "decrees", "reference", "infrastructure", "budget", "tokens")


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "x"


def resolve_map(world: str, roots: list[Path], map_name: str | None = None) -> Path:
    p = Path(world)
    if p.is_file():
        return p
    folders = [p] if p.is_dir() else []
    for root in roots:
        if root.is_dir():
            folders += [d for d in [root, *root.iterdir()] if d.is_dir() and d.name.casefold() == world.casefold()]
    for f in folders:
        maps = sorted(f.glob("*.map"), key=lambda q: q.name)
        if map_name:
            maps = [q for q in maps if q.name == map_name]
        if maps:
            return maps[-1]  # names carry the save date, so the last sorts newest
    raise FileNotFoundError(f"no .map found for '{world}' under {', '.join(map(str, roots))}")


def _render_png(job):
    svg_path, png_path, dpi, width, palette = job
    to_png(Path(svg_path).read_text(encoding="utf-8"), Path(png_path), dpi=dpi, width_px=width, palette=palette)
    return png_path


def build(world: str, roots: list[Path], out: Path, opts: dict) -> dict:
    path = resolve_map(world, roots, opts.get("map"))
    m = AzgaarMap(path)
    net = Network(m, spacing=opts["spacing"], neutral=opts["neutral"], air=opts["air"],
                  air_overlap=opts["air_overlap"], remote=opts["remote"], skip_marker_types={"party"})
    geo = find_cells(path.parent, m)
    states = {s["i"]: s for s in m.live("states")}
    routes = decks.build_routes(net)
    deck, cstats = decks.build_commissions(net, routes, k=opts["income_k"], lo=opts["income_min"], hi=opts["income_max"],
                                           min_value=opts["min_value"], max_per_trade=opts["max_per_trade"],
                                           slaves=opts["slaves"])
    decree_cards, dstats = build_decrees(net, routes, deck, n=opts["decrees"], seed=opts["seed"])
    colours = (opts["colours"] or DEFAULT_COLOURS)[: opts["players"]]
    houses = decks.build_houses(net, colours)
    decks.assign_patrons(houses, dstats.pop("by_state_family"), dstats["families"])
    infra = decks.infrastructure_counts(opts["infra_land"], opts["wild_share"])
    freight = opts.get("freight")
    board_opts = {k: opts[k] for k in ("goal", "start_gold", "stations", "overhead", "home_overhead", "overhead_mode",
                                       "draw", "debt_rounds", "petitions")}
    board_opts["freight"] = freight
    board_opts["trades"] = list(deck)

    root = out / slug(m.name)
    formats = tuple(opts["formats"])
    parts = set(opts["only"] or PARTS)
    manifest: list[dict] = []
    jobs: list[tuple] = []

    def emit(svg: str, rel: str, component: str, deck_name: str, count: int = 1, note: str = "", width=None):
        stem = root / rel
        files = save(svg, stem, ("svg",) if "svg" in formats or "png" in formats else (), dpi=opts["dpi"])
        if "png" in formats:
            palette = opts.get("palette", True) and component != "board"
            jobs.append((str(stem.with_suffix(".svg")), str(stem.with_suffix(".png")), opts["dpi"], width, palette))
        manifest.append({"component": component, "deck": deck_name, "file": rel, "count": count, "note": note})
        return files

    if "board" in parts:
        emit(Board(net, geo).render(), f"board/{slug(m.name)}_board", "board", "", 1,
             f"{len(net.stops)} stops", width=opts["board_width"])
    if "commissions" in parts:
        for trade, cs in deck.items():
            d = slug(trade)
            goods_list = [g for g, _ in Counter(c.good.get("name") for c in cs).most_common()]
            emit(cards.commission_back(trade, goods_list, len(cs)), f"commissions/{d}/{d}_back", "commission back", trade)
            for c in cs:
                emit(cards.commission_front(c, states, freight), f"commissions/{d}/{d}_{c.index:03d}_{c.code}",
                     "commission", trade, 1, f"{c.good.get('name')} {c.origin} to {c.dest}, {c.stops} stops, "
                                             f"income {c.income}")
    if "decrees" in parts:
        emit(cards.decree_back(m.name), "decrees/decree_back", "decree back", "decrees")
        for dc in sorted(decree_cards, key=lambda x: x.number):
            emit(cards.decree_front(dc, states), f"decrees/decree_{dc.number:03d}_{slug(dc.kind)}", "decree", "decrees",
                 1, f"{dc.family}: {dc.title} ({dc.issuer_name}; {dc.area_label.lower()} {dc.area_text}; "
                    f"{dc.routes} routes)")
    if "reference" in parts:
        emit(cards.reference_decree(GOLD_SHARED[5], SETTLE_INCOME, SETTLE_INCOME_WIDE, opts["petitions"]),
             "reference/reading_a_decree",
             "reference", "reference", max(2, len(houses)), "one per player")
        if decree_cards:
            sample = max(decree_cards, key=lambda x: (bool(x.on_reveal), any(p.shared for p in x.petitions), x.routes))
            emit(cards.decree_anatomy(sample, states, opts["petitions"]), "reference/decree_anatomy", "anatomy", "", 1,
                 f"for the rules: decree {sample.number}")
    if "infrastructure" in parts:
        emit(cards.infra_back(), "infrastructure/infrastructure_back", "infrastructure back", "infrastructure")
        for kind, n in infra.items():
            emit(cards.infra_front(kind, decks.COSTS.get(kind)), f"infrastructure/{kind}", "infrastructure",
                 "infrastructure", n, f"expense +{decks.COSTS[kind]}" if kind in decks.COSTS else "any one type")
    if "budget" in parts:
        for k, h in enumerate(houses, 1):
            emit(budget.budget_board(h, **board_opts), f"budget/house_{k}_{slug(h.town)}", "budget board", "", 1,
                 f"{h.town}, {h.state_name}, {h.charter[0]}, home trades {' and '.join(h.home_trades)}, "
                 f"patron of {h.patron[0]} decrees")
    if "tokens" in parts:
        emit(cards.plus50_marker(), "tokens/plus50_marker", "token", "", max(2, len(houses)) * 2,
             "two per player, one for each lane")

    workers = max(1, min(opts["jobs"] or (os.cpu_count() or 2), 8))
    if jobs:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_render_png, jobs, chunksize=8))
    sheet_records = []
    if opts.get("sheets", True) and formats and manifest:
        sheet_records = build_sheets(root, manifest, dpi=opts.get("sheet_dpi", 200), max_px=opts.get("sheet_max", 4096),
                                     palette=opts.get("palette", True), jobs=workers, world=m.name)
    if jobs and "svg" not in formats:
        for svg_path, *_ in jobs:
            Path(svg_path).unlink(missing_ok=True)

    summary = {"world": m.name, "map": path.name, "cells_geojson": geo.path.name if geo else None,
               "network": net.summary(), "commissions": cstats, "decrees": dstats,
               "houses": [{"colour": h.colour, "town": h.town, "state": h.state_name, "home_trades": h.home_trades,
                           "charter": h.charter[0], "patron": h.patron[0]} for h in houses],
               "infrastructure": infra, "options": opts,
               "sheets": [{k: r[k] for k in ("sheet", "columns", "rows", "cards", "card_width", "card_height")}
                          for r in sheet_records]}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["component", "deck", "file", "count", "note"])
        w.writeheader()
        w.writerows(manifest)
    data = {"commissions": {t: [{**asdict(c), "good": c.good.get("name")} for c in cs] for t, cs in deck.items()},
            "decrees": [asdict(dc) for dc in sorted(decree_cards, key=lambda x: x.number)],
            "stops": [{**{k: v for k, v in asdict(s).items() if k != "roles"}, "roles": sorted(s.roles)}
                      for s in net.stops.values()],
            "links": [{"a": ln.a, "b": ln.b, "mode": ln.mode, "miles": round(ln.length * m.mi_per_px)}
                      for ln in net.links.values()],
            "stars": [{"marker": s.marker.get("i"), "name": s.marker.get("name"), "type": s.marker.get("type"),
                       "mode": s.mode, "x": round(s.x, 1), "y": round(s.y, 1)} for s in net.stars]}
    (root / "cards.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (root / "REPORT.md").write_text(report(summary), encoding="utf-8")
    return summary


def report(s: dict) -> str:
    n, c, d = s["network"], s["commissions"], s["decrees"]
    lines = [f"# {s['world']}: azeuro build report", "",
             f"Map: `{s['map']}`. Cells GeoJSON: `{s['cells_geojson'] or 'none (no biome tint or history zones)'}`.", "",
             "## Network", "",
             f"Stops: {n['stops']} (market towns, capitals and forts always; cities by {n['city_rule']}, kept "
             f"at least {n['spacing_px']} map px apart).",
             "Roles: " + ", ".join(f"{k} {v}" for k, v in sorted(n["roles"].items())) + ".",
             f"Links: {n['links'].get('land', 0)} land, {n['links'].get('sea', 0)} sea. Connected groups: {n['components']}.",
             f"Neutral stations: {', '.join(n['neutral'])}.",
             f"Air sites: {', '.join(n['air'])} ({n['air_rule']}).",
             "Favour stars: " + ", ".join(f"{k} {v}" for k, v in sorted(n["stars"].items())) + ".", ""]
    if n["notes"]:
        lines += ["Notes: " + "; ".join(n["notes"]), ""]
    lines += ["## Commissions", "",
              f"{c['deals']} market-to-market deals, one card each, filed by trade "
              f"({c['free_lands']} have a market in unclaimed land).",
              "Deck sizes: " + ", ".join(f"{k} {v}" for k, v in c["decks"].items()) + ".",
              f"Value quartiles (units x price): {c['value_quartiles']}.",
              "Income spread: " + ", ".join(f"{k}: {v}" for k, v in c["income"].items()) + ".", ""]
    if c.get("trimmed_by_max_per_trade"):
        lines += [f"Trimmed by --max-per-trade: {c['trimmed_by_max_per_trade']}.", ""]
    lines += ["## Decrees", "",
              f"{d['cards']} cards chosen from {d['candidates']} candidates ({d['dropped_small']} touched too few "
              f"routes).",
              "Families: " + ", ".join(f"{k} {v}" for k, v in d["families"].items()) + ".",
              "Issuers: " + ", ".join(f"{k} {v}" for k, v in d["issuers"].items()) + ".",
              "Trades targeted: " + ", ".join(f"{k} {v}" for k, v in d["decks_targeted"].items()) + ".",
              "Treasuries: " + ", ".join(f"{k} {v}" for k, v in d["treasury"].items()) + ".", "",
              "## Houses", ""]
    lines += [f"- {h['town']} ({h['state']}): home trades {' and '.join(h['home_trades'])}; {h['charter']}; "
              f"patron of {h['patron']} decrees" for h in s["houses"]]
    lines += ["", "## Infrastructure deck", "",
              ", ".join(f"{k} {v}" for k, v in s["infrastructure"].items()) + " (scarcity follows cost).", ""]
    if s.get("sheets"):
        lines += ["## Sprite sheets (sheets/)", "", "| Sheet | Columns x rows | Cards | Cell (px) |", "|---|---|---|---|"]
        lines += [f"| {r['sheet']} | {r['columns']} x {r['rows']} | {r['cards']} | {r['card_width']} x {r['card_height']} |"
                  for r in s["sheets"]]
        lines.append("")
    return "\n".join(lines)
