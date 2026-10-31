"""Small SVG toolkit shared by the card, board and budget renderers.

SVG has no automatic line breaking, so text is measured with the bundled Barlow fonts (via
Pillow) and wrapped here. The same fonts are registered with fontconfig before PNG export, so
the raster output matches the vector output. Sizes are CSS px at 96 px per inch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import ImageFont

FONT_DIR = Path(__file__).parent / "fonts"
FONT_FILES = {
    ("Barlow", 400, "normal"): "Barlow-Regular.ttf",
    ("Barlow", 500, "normal"): "Barlow-Medium.ttf",
    ("Barlow", 600, "normal"): "Barlow-SemiBold.ttf",
    ("Barlow", 700, "normal"): "Barlow-Bold.ttf",
    ("Barlow", 400, "italic"): "Barlow-Italic.ttf",
    ("Barlow Condensed", 500, "normal"): "BarlowCondensed-Medium.ttf",
    ("Barlow Condensed", 600, "normal"): "BarlowCondensed-SemiBold.ttf",
    ("Barlow Condensed", 700, "normal"): "BarlowCondensed-Bold.ttf",
}

# Palette shared by every component (named for what it does in the game).
INK = "#1F2A33"
PAPER = "#E7EAE1"
PANEL = "#F6F7F3"
MUTED = "#4A5560"
RULE = "#6B7680"
COIN = "#D3A23A"
EXPENSE = "#B23A2E"
LAND = "#2E7A44"
SEA = "#2A64A8"
AIR = "#FFFFFF"
AIR_RIM = "#9AA8B5"
INCOME_LANE, INCOME_TEN = "#F3E4B4", "#D9AE45"
EXPENSE_LANE, EXPENSE_TEN = "#F2D2CB", "#D98C80"
MODE_COLOR = {"land": LAND, "sea": SEA, "air": AIR}

SANS = "Barlow, 'Helvetica Neue', Arial, sans-serif"
COND = "'Barlow Condensed', 'Arial Narrow', sans-serif"


def esc(text) -> str:
    return escape(str(text), {'"': "&quot;"})


@lru_cache(maxsize=None)
def _font(family: str, weight: int, style: str, size: float) -> ImageFont.FreeTypeFont:
    key = (family, weight, style)
    if key not in FONT_FILES:  # nearest weight of the family
        cands = [k for k in FONT_FILES if k[0] == family and k[2] == style] or \
                [k for k in FONT_FILES if k[0] == family]
        key = min(cands, key=lambda k: abs(k[1] - weight))
    # Pillow measures in whole pixels; measure at 10x and scale for sub-pixel accuracy.
    return ImageFont.truetype(str(FONT_DIR / FONT_FILES[key]), int(round(size * 10)))


def text_width(text: str, size: float, family: str = "Barlow", weight: int = 400, style: str = "normal") -> float:
    return _font(family, weight, style, size).getlength(text) / 10.0


def wrap(text: str, width: float, size: float, family: str = "Barlow", weight: int = 400,
         style: str = "normal") -> list[str]:
    words, lines, line = str(text).split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if line and text_width(trial, size, family, weight, style) > width:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def fit_size(text: str, width: float, size: float, family: str, weight: int, min_size: float = 8) -> float:
    """Largest size <= size at which one line of text fits the width."""
    while size > min_size and text_width(text, size, family, weight) > width:
        size -= 0.5
    return size


def text(x, y, s, size, *, family="Barlow", weight=400, fill=INK, anchor="start", style="normal",
         extra="") -> str:
    fam = COND if family == "Barlow Condensed" else SANS
    st = ' font-style="italic"' if style == "italic" else ""
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{fam}" font-weight="{weight}" font-size="{size:g}"'
            f'{st} fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def text_block(x, y, lines, size, lh, **kw) -> str:
    """Lines laid out top-down; y is the first baseline."""
    return "".join(text(x, y + i * lh, ln, size, **kw) for i, ln in enumerate(lines))


def doc(width: float, height: float, body: str, title: str = "") -> str:
    t = f"<title>{esc(title)}</title>" if title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
            f'viewBox="0 0 {width:g} {height:g}">{t}{body}</svg>')


STAR = "12,2.5 14.9,8.9 21.8,9.3 16.4,13.7 18.2,20.5 12,16.8 5.8,20.5 7.6,13.7 2.2,9.3 9.1,8.9"

ICONS = {  # 24x24 stroke icons
    "land": '<path d="M3 14c0-6 12-6 12 0"/><path d="M2 14h15"/><circle cx="6" cy="17.5" r="2"/>'
            '<circle cx="13" cy="17.5" r="2"/><path d="M17 14l5-1.5"/>',
    "sea": '<path d="M3 16h18l-2.5 4h-13z"/><path d="M12 3v13"/><path d="M12 4l6 9h-6"/><path d="M12 6l-5 7h5"/>',
    "air": '<ellipse cx="11" cy="8" rx="8" ry="4"/><path d="M19 8l3-2.5v5z"/><path d="M8 12l1 4"/>'
           '<path d="M14 12l-1 4"/><path d="M8 16h6v2.5H8z"/>',
    "wild": '<circle cx="12" cy="12" r="9.5"/><path d="M12 4.5l2.2 7.5-2.2 7.5-2.2-7.5z"/>'
            '<path d="M4.5 12l7.5-2.2 7.5 2.2-7.5 2.2z"/>',
    "star": f'<polygon points="{STAR}"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 9.5h4.5a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3H15"/>',
}


def icon(name: str, x: float, y: float, size: float, stroke: str = INK, width: float = 2.0) -> str:
    s = size / 24.0
    return (f'<g transform="translate({x:.2f} {y:.2f}) scale({s:.4f})" fill="none" stroke="{stroke}" '
            f'stroke-width="{width / s:.2f}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def star(cx, cy, r, fill, stroke=INK, sw=1.0, dash="") -> str:
    s = r / 9.5
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<polygon transform="translate({cx - 12 * s:.2f} {cy - 12 * s:.2f}) scale({s:.4f})" points="{STAR}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw / s:.2f}" stroke-linejoin="round"{d}/>')


def coin(cx, cy, r, label, *, fill=COIN, fg=INK, stroke=INK, sw=1.5, size=None, weight=700) -> str:
    size = size or r * 1.15
    return (f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
            + text(cx, cy + size * 0.35, label, size, family="Barlow Condensed", weight=weight, fill=fg,
                   anchor="middle"))


def rrect(x, y, w, h, r, fill, stroke="none", sw=0, extra="") -> str:
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{extra}/>')


# --------------------------------------------------------------------------- PNG export
_fonts_ready = False


def register_fonts() -> None:
    """Make the bundled fonts visible to fontconfig (used by cairo when rasterising)."""
    global _fonts_ready
    if _fonts_ready:
        return
    target = Path(os.path.expanduser("~/.local/share/fonts/azeuro"))
    target.mkdir(parents=True, exist_ok=True)
    changed = False
    for f in FONT_DIR.glob("*.ttf"):
        dst = target / f.name
        if not dst.exists():
            shutil.copy(f, dst)
            changed = True
    if changed and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", str(target)], check=False, capture_output=True)
    _fonts_ready = True


def to_png(svg: str, path: Path, dpi: int = 300, width_px: int | None = None, palette: bool = False) -> None:
    """Rasterise with cairo. palette=True stores a 256-colour PNG (about a third of the size; the
    flat-colour cards lose nothing visible)."""
    import cairosvg  # imported lazily: SVG-only runs need no cairo
    register_fonts()
    kw = {"output_width": width_px} if width_px else {"scale": dpi / 96.0}
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(path), **kw)
    if palette:
        from PIL import Image
        with Image.open(path) as im:
            q = im.convert("RGBA").quantize(256, method=Image.Quantize.FASTOCTREE)
        q.save(path, optimize=True)


def save(svg: str, stem: Path, formats: tuple[str, ...], dpi: int = 300, width_px: int | None = None) -> list[Path]:
    stem.parent.mkdir(parents=True, exist_ok=True)
    out = []
    if "svg" in formats:
        p = stem.with_suffix(".svg")
        p.write_text(svg, encoding="utf-8")
        out.append(p)
    if "png" in formats:
        p = stem.with_suffix(".png")
        to_png(svg, p, dpi=dpi, width_px=width_px)
        out.append(p)
    return out
