"""Turn one Azgaar world into the full component set: board, decks, budget boards, tokens."""
from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from . import budget, cards, decks
from .board import Board
from .geo import find_cells
from .mapfile import AzgaarMap
from .network import Network
from .sheets import build_sheets
from .svgkit import save, to_png

DEFAULT_COLOURS = ["#6E3B87", "#2C7873", "#A8551E", "#3B4A9C", "#7A5C2E", "#4B5563"]
PARTS = ("board", "commissions", "events", "infrastructure", "budget", "tokens")


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
                  air_overlap=opts["air_overlap"], remote=opts["remote"])
    geo = find_cells(path.parent, m)
    states = {s["i"]: s for s in m.live("states")}
    deck, cstats = decks.build_commissions(net, k=opts["income_k"], lo=opts["income_min"], hi=opts["income_max"],
                                           min_deck=opts["min_deck"], min_value=opts["min_value"],
                                           max_per_state=opts["max_per_state"], neutral_deck=opts["neutral_deck"])
    ev_cards, estats = decks.build_events(net, size=opts["events"], seed=opts["seed"])
    colours = (opts["colours"] or DEFAULT_COLOURS)[: opts["players"]]
    houses = decks.build_houses(net, colours)
    infra = decks.infrastructure_counts(opts["infra_land"], opts["wild_share"])

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
        for sid, cs in sorted(deck.items()):
            st = states[sid]
            d = slug(st["name"])
            emit(cards.commission_back(st), f"commissions/{d}/{d}_back", "commission back", st["name"])
            for c in cs:
                name = f"{d}_{c.index:03d}_{c.code}" + (f"_copy{c.copy}" if c.copy > 1 else "")
                emit(cards.commission_front(c, st, states), f"commissions/{d}/{name}", "commission", st["name"], 1,
                     f"{c.good.get('name')} {c.origin} to {c.dest}, {c.stops} stops, income {c.income}")
    if "events" in parts:
        emit(cards.event_back(), "events/event_back", "event back", "events")
        for e in ev_cards:
            note = "; ".join(f"{t.colour} {'+' if t.polarity > 0 else '-'} {t.title}" for t in (e.land, e.sea, e.air))
            emit(cards.event_front(e), f"events/event_{e.number:03d}", "event", "events", 1, note)
    if "infrastructure" in parts:
        emit(cards.infra_back(), "infrastructure/infrastructure_back", "infrastructure back", "infrastructure")
        for kind, n in infra.items():
            emit(cards.infra_front(kind, decks.COSTS.get(kind)), f"infrastructure/{kind}", "infrastructure",
                 "infrastructure", n, f"expense +{decks.COSTS[kind]}" if kind in decks.COSTS else "any one type")
    if "budget" in parts:
        for k, h in enumerate(houses, 1):
            emit(budget.budget_board(h), f"budget/house_{k}_{slug(h.town)}", "budget board", "", 1,
                 f"{h.town}, {h.state_name}, {h.charter[0]}")
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
               "network": net.summary(), "commissions": cstats, "events": estats,
               "houses": [{"colour": h.colour, "town": h.town, "state": h.state_name, "goods": h.goods,
                           "charter": h.charter[0]} for h in houses],
               "infrastructure": infra, "options": opts,
               "sheets": [{k: r[k] for k in ("sheet", "columns", "rows", "cards", "card_width", "card_height")}
                          for r in sheet_records]}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["component", "deck", "file", "count", "note"])
        w.writeheader()
        w.writerows(manifest)
    data = {"commissions": {states[s]["name"]: [{**asdict(c), "good": c.good.get("name")} for c in cs]
                            for s, cs in deck.items()},
            "events": [asdict(e) for e in ev_cards],
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
    n, c, e = s["network"], s["commissions"], s["events"]
    lines = [f"# {s['world']}: azeuro build report", "",
             f"Map: `{s['map']}`. Cells GeoJSON: `{s['cells_geojson'] or 'none (no biome tint or history zones)'}`.", "",
             "## Network", "",
             f"Stops: {n['stops']} (market towns, capitals and forts always; cities by {n['city_rule']}, kept "
             f"at least {n['spacing_px']} map px apart).",
             "Roles: " + ", ".join(f"{k} {v}" for k, v in sorted(n["roles"].items())) + ".",
             f"Links: {n['links'].get('land', 0)} land, {n['links'].get('sea', 0)} sea. Connected groups: {n['components']}.",
             f"Neutral stations: {', '.join(n['neutral'])}.",
             f"Air sites: {', '.join(n['air'])} ({n['air_rule']}).",
             "Event stars: " + ", ".join(f"{k} {v}" for k, v in sorted(n["stars"].items())) + ".", ""]
    if n["notes"]:
        lines += ["Notes: " + "; ".join(n["notes"]), ""]
    lines += ["## Commissions", "",
              f"{c['deals']} market-to-market deals, filed under the seller's and the buyer's state.",
              "Deck sizes: " + ", ".join(f"{k} {v}" for k, v in c["decks"].items()) + ".",
              f"Value quartiles (units x price): {c['value_quartiles']}.",
              "Income spread (unique deals): " + ", ".join(f"{k}: {v}" for k, v in c["income"].items()) + ".", ""]
    if c.get("trimmed_by_max_per_state"):
        lines += [f"Trimmed by --max-per-state: {c['trimmed_by_max_per_state']}.", ""]
    lines += ["## Events", "",
              f"{e['cards']} cards. Marker texts per colour: {e['marker_texts']}. Set aside to keep the deck even: "
              f"{e['set_aside'] or 'none'}.",
              f"Share of positive events: {e['positive_share']}. Generic fillers used: {e['generic_uses'] or 'none'}.", "",
              "## Houses", ""]
    lines += [f"- {h['town']} ({h['state']}): {', '.join(h['goods'])}; {h['charter']}" for h in s["houses"]]
    lines += ["", "## Infrastructure deck", "",
              ", ".join(f"{k} {v}" for k, v in s["infrastructure"].items()) + " (scarcity follows cost).", ""]
    if s.get("sheets"):
        lines += ["## Sprite sheets (sheets/)", "", "| Sheet | Columns x rows | Cards | Cell (px) |", "|---|---|---|---|"]
        lines += [f"| {r['sheet']} | {r['columns']} x {r['rows']} | {r['cards']} | {r['card_width']} x {r['card_height']} |"
                  for r in s["sheets"]]
        lines.append("")
    return "\n".join(lines)
