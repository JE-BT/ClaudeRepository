"""Sprite sheets for screentop.gg.

Screentop slices a sheet into equal cells, so every sheet holds faces of one size on a plain grid:
no margins, no gutters, row by row from the top left, unused cells transparent. A sheet is at
most `max_px` (default 4096) on each side. Each card is rasterised from its SVG straight to its
cell size (`dpi`, default 200), so nothing is resampled twice.

Sheets made, per build:
  commissions_<State>_N   every front of that state's deck, in deck order
  events_N                every event front
  infrastructure_N        the infrastructure deck with every copy laid out (counts from the manifest)
  infrastructure_faces    the four faces once each
  tokens_plus50           one +50 marker per copy
  *_back                  each deck's back as a single image of the same cell size
  <World>_board           the board scaled to fit max_px
  budget_house_N_<Town>   each budget board scaled to fit max_px
A sheets.csv lists every sheet with its columns, rows, card count, cell size and card order.
"""
from __future__ import annotations

import csv
import io
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from .svgkit import register_fonts


def _raster(job) -> bytes:
    """(svg_path, width, height) -> PNG bytes at exactly that size."""
    import cairosvg
    register_fonts()
    path, w, h = job
    return cairosvg.svg2png(bytestring=Path(path).read_bytes(), output_width=w, output_height=h)


def _svg_size(path: Path) -> tuple[float, float]:
    head = path.read_text(encoding="utf-8")[:400]
    import re
    w = float(re.search(r'width="([\d.]+)"', head).group(1))
    h = float(re.search(r'height="([\d.]+)"', head).group(1))
    return w, h


def _save(im: Image.Image, path: Path, palette: bool) -> None:
    if palette:
        im = im.quantize(256, method=Image.Quantize.FASTOCTREE)
    im.save(path, optimize=True)


def build_sheets(root: Path, manifest: list[dict], dpi: int = 200, max_px: int = 4096, palette: bool = True,
                 jobs: int = 4, world: str = "") -> list[dict]:
    out_dir = root / "sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[tuple[Path, str]]] = {}
    singles: list[tuple[str, Path, int | None]] = []  # (name, svg, long-side px or None for card dpi)
    for row in manifest:
        svg = root / (row["file"] + ".svg")
        if not svg.exists():
            continue
        comp, deck = row["component"], row["deck"]
        name = Path(row["file"]).name
        if comp == "commission":
            groups.setdefault(f"commissions_{_slug(deck)}", []).append((svg, name))
        elif comp == "event":
            groups.setdefault("events", []).append((svg, name))
        elif comp == "infrastructure":
            groups.setdefault("infrastructure", []).extend([(svg, name)] * int(row["count"]))
            groups.setdefault("infrastructure_faces", []).append((svg, name))
        elif comp == "token":
            groups.setdefault("tokens_plus50", []).extend([(svg, name)] * int(row["count"]))
        elif comp == "commission back":
            singles.append((f"commissions_{_slug(deck)}_back", svg, None))
        elif comp in ("event back", "infrastructure back"):
            singles.append((name, svg, None))
        elif comp == "board":
            singles.append((f"{_slug(world)}_board" if world else "board", svg, max_px))
        elif comp == "budget board":
            singles.append((f"budget_{name}", svg, max_px))

    # every distinct card face is rasterised once
    scale = dpi / 96.0
    sizes: dict[Path, tuple[int, int]] = {}
    for items in groups.values():
        for svg, _ in items:
            if svg not in sizes:
                w, h = _svg_size(svg)
                sizes[svg] = (max(1, round(w * scale)), max(1, round(h * scale)))
    for _, svg, long_side in singles:
        w, h = _svg_size(svg)
        if long_side:
            k = min(long_side / max(w, h), 300 / 96.0)  # never above 300 dpi
            sizes[svg] = (round(w * k), round(h * k))
        else:
            sizes[svg] = (round(w * scale), round(h * scale))
    order = list(sizes)
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
        pngs = dict(zip(order, ex.map(_raster, [(str(p), *sizes[p]) for p in order], chunksize=8)))

    records = []
    for gname, items in groups.items():
        cw, ch = sizes[items[0][0]]
        cols = max(1, min(max_px // cw, len(items)))
        rows_max = max(1, max_px // ch)
        per = cols * rows_max
        n_sheets = math.ceil(len(items) / per)
        for k in range(n_sheets):
            chunk = items[k * per:(k + 1) * per]
            c = min(cols, len(chunk)) if n_sheets == 1 else cols
            r = math.ceil(len(chunk) / c)
            sheet = Image.new("RGBA", (c * cw, r * ch), (0, 0, 0, 0))
            for i, (svg, _) in enumerate(chunk):
                tile = Image.open(io.BytesIO(pngs[svg])).convert("RGBA")
                sheet.paste(tile, ((i % c) * cw, (i // c) * ch))
            fname = f"{gname}_{k + 1}.png" if n_sheets > 1 else f"{gname}.png"
            _save(sheet, out_dir / fname, palette)
            records.append({"sheet": fname, "set": gname, "columns": c, "rows": r, "cards": len(chunk),
                            "card_width": cw, "card_height": ch, "sheet_width": c * cw, "sheet_height": r * ch,
                            "order": " ".join(nm for _, nm in chunk)})
    for name, svg, long_side in singles:
        im = Image.open(io.BytesIO(pngs[svg])).convert("RGBA")
        fname = f"{name}.png"
        _save(im, out_dir / fname, palette and not name.endswith("_board"))
        records.append({"sheet": fname, "set": name, "columns": 1, "rows": 1, "cards": 1, "card_width": im.width,
                        "card_height": im.height, "sheet_width": im.width, "sheet_height": im.height,
                        "order": svg.stem})
    with open(out_dir / "sheets.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(records[0].keys()) if records else ["sheet"])
        w.writeheader()
        w.writerows(records)
    return records


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "x"
