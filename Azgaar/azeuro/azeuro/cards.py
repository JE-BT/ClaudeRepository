"""Card faces as SVG strings (CSS px at 96 px/in).

Sizes: commission 336x240 (landscape poker, 88.9 x 63.5 mm), event 264x456 (tarot, 70 x 121 mm),
infrastructure 240x336 (poker), +50 marker 72x72 (19 mm disc). No bleed is added.
"""
from __future__ import annotations

from .decks import TIERS, Commission, EventCard, EventText
from .svgkit import (AIR_RIM, COIN, EXPENSE, INK, LAND, MODE_COLOR, MUTED, PANEL, PAPER, RULE, SEA, coin,
                     doc, fit_size, icon, rrect, star, text, text_block, text_width, wrap)

CW, CH = 336, 240
EW, EH = 264, 456
IW, IH = 240, 336


def _frame(w, h, fill=PAPER) -> str:
    return rrect(1, 1, w - 2, h - 2, 10, fill, INK, 2)


def _top_band(w, h, fill) -> str:
    return (f'<path d="M1,{h} V11 A10,10 0 0 1 11,1 H{w - 11} A10,10 0 0 1 {w - 1},11 V{h} Z" fill="{fill}"/>'
            f'<line x1="1" y1="{h}" x2="{w - 1}" y2="{h}" stroke="{INK}" stroke-width="2"/>')


def _modes_phrase(modes: list[str]) -> str:
    if not modes:
        return "no route yet"
    words = {"land": "land", "sea": "sea", "air": "air"}
    ms = [words[m] for m in ("land", "sea", "air") if m in modes]
    return "by " + (" and ".join(ms) if len(ms) <= 2 else ", ".join(ms[:-1]) + " and " + ms[-1])


# ------------------------------------------------------------------------------ commissions
def commission_front(c: Commission, state: dict, states: dict) -> str:
    sc = state.get("color") or "#C9D2DC"
    full = state.get("fullName") or state.get("name")
    role_line = {"export": "Export commission from the", "import": "Import commission for the",
                 "domestic": "Domestic commission in the"}[c.role]
    b = [_frame(CW, CH), _top_band(CW, 42, sc)]
    b.append(text(12, 17, role_line, 11, weight=600))
    b.append(text(12, 35, full, fit_size(full, 236, 18, "Barlow Condensed", 700), family="Barlow Condensed", weight=700))
    b.append(text(324, 17, f"Card {c.index} of {c.of}", 11, weight=600, anchor="end"))
    code = c.code + (f", copy {c.copy}" if c.copy > 1 else "")
    b.append(text(324, 35, code, 11, weight=500, anchor="end"))
    # good
    gname = c.good.get("name", "Goods")
    gsize = fit_size(gname, 214, 26, "Barlow Condensed", 700, 16)
    b.append(rrect(12, 58, 16, 16, 3, c.good.get("color") or "#CCCCCC", INK, 1.5))
    b.append(text(34, 74, gname, gsize, family="Barlow Condensed", weight=700))
    pips = "".join(f'<circle cx="{36 + i * 9}" cy="87.5" r="3.2" fill="{COIN if i <= c.tier else PANEL}" '
                   f'stroke="{INK}" stroke-width="1"/>' for i in range(4))
    b.append(pips)
    b.append(text(72, 91, f"{TIERS[c.tier][0]}, {_modes_phrase(c.modes)}", 11, fill=MUTED))
    # route strip
    x0, x1 = 12, 258
    size = 13
    while size > 9 and text_width(c.origin, size, weight=700) + text_width(c.dest, size, weight=700) > (x1 - x0) - 16:
        size -= 0.5
    b.append(text(x0, 112, c.origin, size, weight=700))
    b.append(text(x1, 112, c.dest, size, weight=700, anchor="end"))
    b.append(f'<line x1="{x0 + 12}" y1="121" x2="{x1 - 16}" y2="121" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<path d="M{x1 - 18},115 L{x1 - 9},121 L{x1 - 18},127 Z" fill="{INK}"/>')
    b.append(f'<circle cx="{x0 + 6}" cy="121" r="5.5" fill="{PANEL}" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<circle cx="{x1 - 5}" cy="121" r="5.5" fill="{INK}"/>')
    so = states[c.seller_state]["name"] if c.seller_state else "Free lands"
    sd = states[c.buyer_state]["name"] if c.buyer_state else "Free lands"
    mid = f"{c.stops} stops, {round(c.miles):,} mi" + (" (by distance)" if c.stops_source == "distance" else "")
    b.append(text(x0, 137, so, 11, fill=MUTED))
    b.append(text((x0 + x1) / 2, 137, mid, 11, fill=MUTED, weight=600, anchor="middle"))
    b.append(text(x1, 137, sd, 11, fill=MUTED, anchor="end"))
    # income coin
    b.append(f'<circle cx="294" cy="92" r="31" fill="{COIN}" stroke="{INK}" stroke-width="2.5"/>')
    b.append(text(294, 104, str(c.income), 34, family="Barlow Condensed", weight=700, anchor="middle"))
    b.append(text(294, 137, "income", 11, weight=600, anchor="middle"))
    # split ladder
    label = "Split by stations held (ties: declarer)"
    b.append(text(12, 160, label, fit_size(label, 216, 11, "Barlow", 600), weight=600))
    bw = (216 - 8) / 3
    for k, (rank, share) in enumerate(zip(("Most", "Second", "Third"), c.split)):
        x = 12 + k * (bw + 4)
        b.append(rrect(x, 166, bw, 54, 5, PANEL, INK, 1.5))
        b.append(text(x + 7, 181, rank, 11, weight=600))
        b.append(f'<circle cx="{x + 17}" cy="202" r="10" fill="none" stroke="{RULE}" stroke-width="2" stroke-dasharray="3 2.5"/>')
        if share:
            b.append(coin(x + bw - 17, 202, 11, str(share), sw=1.5, size=14))
        else:
            b.append(text(x + bw - 17, 207, "-", 14, family="Barlow Condensed", weight=700, anchor="middle", fill=MUTED))
    # event stars
    b.append(text(236, 160, "Event stars", 11, weight=600))
    b.append(rrect(236, 166, 88, 54, 5, PANEL, INK, 1.5))
    for k in range(3):
        b.append(star(251 + k * 29, 193, 10.5, "none", RULE, 1.6, "3 2"))
    return doc(CW, CH, "".join(b), f"{gname}: {c.origin} to {c.dest}")


def commission_back(state: dict) -> str:
    sc = state.get("color") or "#C9D2DC"
    name = state.get("name", "")
    full = state.get("fullName") or name
    b = [rrect(1, 1, CW - 2, CH - 2, 10, sc, INK, 2)]
    b.append(f'<path d="M-10 186 H110 L150 146 H346" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>')
    b.append(f'<path d="M-10 206 H130 L170 166 H346" fill="none" stroke="{INK}" stroke-width="2" '
             f'stroke-dasharray="6 5" stroke-linejoin="round" opacity="0.55"/>')
    b.append(f'<circle cx="56" cy="186" r="9" fill="{PANEL}" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<circle cx="214" cy="146" r="9" fill="{PANEL}" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<circle cx="292" cy="146" r="9" fill="{INK}" stroke="{INK}" stroke-width="4"/>')
    b.append(text(22, 38, "Commissions of", 14, weight=600))
    b.append(text(22, 84, name, fit_size(name, 290, 48, "Barlow Condensed", 700), family="Barlow Condensed", weight=700))
    b.append(text(22, 106, full, fit_size(full, 290, 14, "Barlow", 600), weight=600))
    b.append(f'<rect x="1" y="1" width="{CW - 2}" height="{CH - 2}" rx="10" fill="none" stroke="{INK}" stroke-width="2"/>')
    return doc(CW, CH, "".join(b), f"Commissions of {name}")


# ------------------------------------------------------------------------------ events
def _band(e: EventText, y: float, h: float) -> str:
    col = MODE_COLOR[e.colour]
    edge = INK if e.colour == "air" else col
    fg = INK if e.colour == "air" else "#FFFFFF"
    out = [rrect(12, y, 240, h, 6, PANEL, edge, 2)]
    out.append(f'<path d="M18,{y} H58 V{y + h} H18 A6,6 0 0 1 12,{y + h - 6} V{y + 6} A6,6 0 0 1 18,{y} Z" '
               f'fill="{col}"/>')
    if e.colour == "air":
        out.append(f'<line x1="58" y1="{y}" x2="58" y2="{y + h}" stroke="{INK}" stroke-width="2"/>')
    out.append(rrect(12, y, 240, h, 6, "none", edge, 2))
    out.append(icon(e.colour, 23, y + h / 2 - 20, 24, fg))
    out.append(text(35, y + h / 2 + 20, e.colour.capitalize(), 11, weight=700, fill=fg, anchor="middle"))
    tx, tw = 66, 178
    ts = fit_size(e.title, tw, 13.5, "Barlow", 700, 10)
    out.append(text(tx, y + 20, e.title, ts, weight=700))
    out.append(text(tx, y + 34, e.kind, 11, fill=MUTED))
    size, lh = 12.5, 15.5
    lines = wrap(e.text, tw, size)
    while len(lines) * lh > h - 46 and size > 10:
        size -= 0.5
        lh = size * 1.24
        lines = wrap(e.text, tw, size)
    out.append(text_block(tx, y + 52, lines, size, lh))
    return "".join(out)


def event_front(card: EventCard) -> str:
    b = [_frame(EW, EH), _top_band(EW, 52, INK)]
    b.append(text(14, 27, "Event", 22, family="Barlow Condensed", weight=700, fill=PAPER))
    b.append(text(250, 27, f"No. {card.number}", 12, weight=600, fill=COIN, anchor="end"))
    b.append(text(14, 43, "Each star reads the band of its own colour", 11, fill="#C9D0D6"))
    top, gap = 62, 8
    h = (EH - 12 - top - 2 * gap) / 3
    for k, e in enumerate((card.land, card.sea, card.air)):
        b.append(_band(e, top + k * (h + gap), h))
    return doc(EW, EH, "".join(b), f"Event {card.number}")


def event_back() -> str:
    b = [rrect(1, 1, EW - 2, EH - 2, 10, INK, INK, 2)]
    b.append(rrect(10, 10, EW - 20, EH - 20, 6, "none", COIN, 1.5))
    for k, (fill, rim) in enumerate(((LAND, "#FFFFFF"), (SEA, "#FFFFFF"), ("#FFFFFF", AIR_RIM))):
        b.append(star(EW / 2 + (k - 1) * 62, 200, 26, fill, rim, 2.5))
    b.append(text(EW / 2, 290, "Event", 44, family="Barlow Condensed", weight=700, fill=PAPER, anchor="middle"))
    return doc(EW, EH, "".join(b), "Event card back")


# ------------------------------------------------------------------------------ infrastructure
_PATTERNS = {
    "land": ('<pattern id="pat" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
             '<line x1="0" y1="0" x2="0" y2="14" stroke="#FFFFFF" stroke-opacity="0.13" stroke-width="5"/></pattern>'),
    "sea": ('<pattern id="pat" width="28" height="16" patternUnits="userSpaceOnUse"><path d="M0 8 Q7 2 14 8 T28 8" '
            'fill="none" stroke="#FFFFFF" stroke-opacity="0.16" stroke-width="2.5"/></pattern>'),
    "air": ('<pattern id="pat" width="14" height="14" patternUnits="userSpaceOnUse"><circle cx="3.5" cy="3.5" r="1.6" '
            'fill="#9AA8B5"/><circle cx="10.5" cy="10.5" r="1.6" fill="#9AA8B5"/></pattern>'),
}
_CIRCLE = {"land": "#276A3A", "sea": "#23578F", "air": "#EEF1F4", "wild": PANEL}


def _index(kind: str, cost: str | None, fg: str, chip: bool) -> str:
    out = []
    if chip:
        out.append(rrect(0, -18, text_width(kind.capitalize(), 22, "Barlow Condensed", 700) + 14, 26, 5, PANEL, INK, 2))
        out.append(text(7, 1, kind.capitalize(), 22, family="Barlow Condensed", weight=700))
    else:
        out.append(text(0, 0, kind.capitalize(), 24, family="Barlow Condensed", weight=700, fill=fg))
    if cost:
        ring = INK if kind == "air" else "#FFFFFF"
        out.append(f'<circle cx="15" cy="27" r="14" fill="{EXPENSE}" stroke="{ring}" stroke-width="2"/>')
        out.append(text(15, 32, cost, 15, family="Barlow Condensed", weight=700, fill="#FFFFFF", anchor="middle"))
    return "".join(out)


def infra_front(kind: str, cost: int | None) -> str:
    fg = INK if kind in ("air", "wild") else "#FFFFFF"
    b = []
    if kind == "wild":
        b.append('<defs><linearGradient id="wild" x1="0" y1="0" x2="1" y2="1">'
                 f'<stop offset="0.34" stop-color="{LAND}"/><stop offset="0.34" stop-color="{SEA}"/>'
                 f'<stop offset="0.67" stop-color="{SEA}"/><stop offset="0.67" stop-color="#FFFFFF"/></linearGradient></defs>')
        b.append(rrect(1, 1, IW - 2, IH - 2, 10, "url(#wild)", INK, 2))
    else:
        bg = {"land": LAND, "sea": SEA, "air": "#FFFFFF"}[kind]
        b.append(f"<defs>{_PATTERNS[kind]}</defs>")
        b.append(rrect(1, 1, IW - 2, IH - 2, 10, bg, INK, 2))
        b.append(rrect(1, 1, IW - 2, IH - 2, 10, "url(#pat)", "none", 0, ' opacity="0.9"' if kind == "air" else ""))
    rim = "#FFFFFF" if kind in ("land", "sea") else (AIR_RIM if kind == "air" else INK)
    op = ' opacity="0.6"' if kind in ("land", "sea") else (' opacity="0.35"' if kind == "wild" else "")
    b.append(rrect(9, 9, IW - 18, IH - 18, 6, "none", rim, 2, op))
    label = f"+{cost}" if cost else None
    chip = kind == "wild"
    b.append(f'<g transform="translate(18 {38 if not chip else 36})">{_index(kind, label, fg, chip)}</g>')
    b.append(f'<g transform="rotate(180 {IW / 2} {IH / 2}) translate(18 {38 if not chip else 36})">'
             f'{_index(kind, label, fg, chip)}</g>')
    ring = "#FFFFFF" if kind in ("land", "sea") else INK
    b.append(f'<circle cx="{IW / 2}" cy="{IH / 2}" r="66" fill="{_CIRCLE[kind]}" stroke="{ring}" stroke-width="3"/>')
    b.append(icon(kind, IW / 2 - 42, IH / 2 - 42, 84, "#FFFFFF" if kind in ("land", "sea") else INK, 2.2))
    if kind == "wild":
        t = "Any one type, paid as built"
        w = text_width(t, 13, weight=600) + 16
        b.append(rrect(IW / 2 - w / 2, IH / 2 + 76, w, 24, 5, PANEL, INK, 2))
        b.append(text(IW / 2, IH / 2 + 93, t, 13, weight=600, anchor="middle"))
    return doc(IW, IH, "".join(b), f"Infrastructure: {kind}")


def infra_back() -> str:
    b = [rrect(1, 1, IW - 2, IH - 2, 10, INK, INK, 2)]
    b.append(rrect(10, 10, IW - 20, IH - 20, 6, "none", COIN, 1.5))
    for k, col in enumerate((LAND, SEA, "#FFFFFF")):
        b.append(f'<line x1="{40 + k * 22}" y1="{IH - 40}" x2="{IW - 100 + k * 22}" y2="40" stroke="{col}" '
                 f'stroke-width="12" stroke-linecap="round"/>')
    b.append(rrect(IW / 2 - 92, IH / 2 - 26, 184, 52, 6, INK, COIN, 1.5))
    b.append(text(IW / 2, IH / 2 + 10, "Infrastructure", 30, family="Barlow Condensed", weight=700, fill=PAPER,
                  anchor="middle"))
    return doc(IW, IH, "".join(b), "Infrastructure card back")


def plus50_marker() -> str:
    b = [f'<circle cx="36" cy="36" r="34" fill="{INK}" stroke="{COIN}" stroke-width="3"/>',
         f'<circle cx="36" cy="36" r="27" fill="none" stroke="{COIN}" stroke-width="1" stroke-dasharray="2 2"/>',
         text(36, 46, "+50", 28, family="Barlow Condensed", weight=700, fill=COIN, anchor="middle")]
    return doc(72, 72, "".join(b), "+50 marker")
