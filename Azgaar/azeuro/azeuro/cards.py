"""Card faces as SVG strings (CSS px at 96 px/in).

Sizes: commission 336x240 (landscape poker, 88.9 x 63.5 mm), decree and reference 264x456 (tarot,
70 x 121 mm), infrastructure 240x336 (poker), +50 marker 72x72 (19 mm disc). No bleed is added.

One visual language for money on every card, explained on the reference card:
  gold coin (dark gold disc)        gold, paid or gained once
  pale yellow chip, "income"        moves the income track
  pale red chip, "expense"          moves the expense track
"""
from __future__ import annotations

from .decks import TIERS, Commission
from .decrees import FAMILY_COLOR, Decree, Petition
from .goods import TRADE_COLOR
from .svgkit import (AIR_RIM, COIN, EXPENSE, EXPENSE_LANE, EXPENSE_TEN, INCOME_LANE, INCOME_TEN, INK, LAND, MUTED,
                     PANEL, PAPER, RULE, SEA, coin, doc, fit_size, icon, rrect, star, text, text_block, text_width, wrap)

CW, CH = 336, 240
EW, EH = 264, 456
IW, IH = 240, 336
MODE_FILL = {"land": LAND, "sea": SEA, "air": "#FFFFFF"}


def _frame(w, h, fill=PAPER) -> str:
    return rrect(1, 1, w - 2, h - 2, 10, fill, INK, 2)


def _top_band(w, h, fill) -> str:
    return (f'<path d="M1,{h} V11 A10,10 0 0 1 11,1 H{w - 11} A10,10 0 0 1 {w - 1},11 V{h} Z" fill="{fill}"/>'
            f'<line x1="1" y1="{h}" x2="{w - 1}" y2="{h}" stroke="{INK}" stroke-width="2"/>')


def _modes_phrase(modes: list[str]) -> str:
    if not modes:
        return "no route yet"
    ms = [m for m in ("land", "sea", "air") if m in modes]
    return "by " + (" and ".join(ms) if len(ms) <= 2 else ", ".join(ms[:-1]) + " and " + ms[-1])


def _mode_chip(x, y, mode, w=24, h=15) -> str:
    out = rrect(x, y, w, h, 3, MODE_FILL[mode], INK, 1.3)
    if mode == "air":
        out += rrect(x + 2, y + 2, w - 4, h - 4, 2, "none", AIR_RIM, 1)
    return out


# ------------------------------------------------------------------------------ money marks
def income_chip(x, y, label, size=10.5, h=16) -> tuple[str, float]:
    w = text_width(label, size, weight=700) + 12
    return (rrect(x, y, w, h, h / 2, INCOME_LANE, INCOME_TEN, 1.5)
            + text(x + w / 2, y + h / 2 + size * 0.36, label, size, weight=700, anchor="middle")), w


def expense_chip(x, y, label, size=10.5, h=16) -> tuple[str, float]:
    w = text_width(label, size, weight=700) + 12
    return (rrect(x, y, w, h, h / 2, EXPENSE_LANE, EXPENSE_TEN, 1.5)
            + text(x + w / 2, y + h / 2 + size * 0.36, label, size, weight=700, anchor="middle")), w


def gold_mark(x, y, label, size=10.5, h=16) -> tuple[str, float]:
    r = h / 2
    w = 2 * r + 4 + text_width(label, size, weight=700)
    return (f'<circle cx="{x + r:.2f}" cy="{y + r:.2f}" r="{r - 0.5:.2f}" fill="{COIN}" stroke="{INK}" stroke-width="1.3"/>'
            + text(x + r, y + r + 3.2, "g", 9, family="Barlow Condensed", weight=700, anchor="middle")
            + text(x + 2 * r + 4, y + r + size * 0.36, label, size, weight=700)), w


# ------------------------------------------------------------------------------ commissions
def commission_front(c: Commission, states: dict, freight: dict | None = None) -> str:
    """The original commission layout; only the header changes, from the state deck to the trade deck."""
    tc = TRADE_COLOR.get(c.trade, INK)
    b = [_frame(CW, CH), _top_band(CW, 42, tc)]
    b.append(text(12, 17, "Commission in", 11, weight=600, fill="#FFFFFF"))
    b.append(text(12, 35, c.trade, fit_size(c.trade, 236, 18, "Barlow Condensed", 700), family="Barlow Condensed",
                  weight=700, fill="#FFFFFF"))
    b.append(text(324, 17, f"Card {c.index} of {c.of}", 11, weight=600, anchor="end", fill="#FFFFFF"))
    b.append(text(324, 35, c.code, 11, weight=500, anchor="end", fill="#FFFFFF"))
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
    top, box_h = 160, 54
    if freight:  # optional row; the ladder below gets shorter to make room
        tp = c.tier + 1
        b.append(text(12, 157, "Freight", 11, weight=600))
        fx = 58
        for mode in ("land", "sea", "air"):
            v = round(freight.get(mode, 0) * tp)
            b.append(_mode_chip(fx, 146, mode))
            chip, _ = expense_chip(fx + 28, 146, f"+{v}", 10, 15)
            b.append(chip)
            fx += 66
        b.append(text(324, 157, "expense", 11, fill=MUTED, anchor="end"))
        top, box_h = 178, 40
    # split ladder
    label = "Split by stations held (ties: declarer)"
    b.append(text(12, top, label, fit_size(label, 216, 11, "Barlow", 600), weight=600))
    bw = (216 - 8) / 3
    cy = top + 6 + box_h / 2 + (9 if box_h > 45 else 5)
    for k, (rank, share) in enumerate(zip(("Most", "Second", "Third"), c.split)):
        x = 12 + k * (bw + 4)
        b.append(rrect(x, top + 6, bw, box_h, 5, PANEL, INK, 1.5))
        b.append(text(x + 7, top + 21, rank, 11, weight=600))
        b.append(f'<circle cx="{x + 17}" cy="{cy}" r="10" fill="none" stroke="{RULE}" stroke-width="2" stroke-dasharray="3 2.5"/>')
        if share:
            b.append(coin(x + bw - 17, cy, 11, str(share), sw=1.5, size=14))
        else:
            b.append(text(x + bw - 17, cy + 5, "-", 14, family="Barlow Condensed", weight=700, anchor="middle", fill=MUTED))
    # favour stars (formerly event stars)
    b.append(text(236, top, "Favour stars", 11, weight=600))
    b.append(rrect(236, top + 6, 88, box_h, 5, PANEL, INK, 1.5))
    for k in range(3):
        b.append(star(251 + k * 29, top + 6 + box_h / 2, 10.5 if box_h > 45 else 9, "none", RULE, 1.6, "3 2"))
    return doc(CW, CH, "".join(b), f"{gname}: {c.origin} to {c.dest}")


def commission_back(trade: str, goods: list[str], count: int) -> str:
    """The original back design in the trade's colour."""
    fill = TRADE_COLOR.get(trade, PANEL)
    b = [rrect(1, 1, CW - 2, CH - 2, 10, fill, INK, 2)]
    b.append(f'<path d="M-10 186 H110 L150 146 H346" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>')
    b.append(f'<path d="M-10 206 H130 L170 166 H346" fill="none" stroke="{INK}" stroke-width="2" '
             f'stroke-dasharray="6 5" stroke-linejoin="round" opacity="0.55"/>')
    b.append(f'<circle cx="56" cy="186" r="9" fill="{PANEL}" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<circle cx="214" cy="146" r="9" fill="{PANEL}" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<circle cx="292" cy="146" r="9" fill="{INK}" stroke="{INK}" stroke-width="4"/>')
    b.append(text(22, 38, "Commissions in", 14, weight=600, fill="#FFFFFF"))
    b.append(text(22, 84, trade, fit_size(trade, 290, 48, "Barlow Condensed", 700), family="Barlow Condensed",
                  weight=700, fill="#FFFFFF"))
    sub = ", ".join(goods[:6]) + (", and more" if len(goods) > 6 else "")
    b.append(text(22, 106, sub, fit_size(sub, 290, 14, "Barlow", 600, 9), weight=600, fill="#FFFFFF"))
    b.append(text(CW - 16, CH - 12, f"{count} cards", 11, weight=600, fill="#FFFFFF", anchor="end"))
    b.append(f'<rect x="1" y="1" width="{CW - 2}" height="{CH - 2}" rx="10" fill="none" stroke="{INK}" stroke-width="2"/>')
    return doc(CW, CH, "".join(b), f"Commissions in {trade}")


# ------------------------------------------------------------------------------ decrees
AREA_TAG = {"state": "AFFECTED STATE", "states": "AFFECTED STATES", "stops": "AFFECTED STOPS", "links": "AFFECTED LINKS"}


def _tag(x, y, label, fill=INK, fg=PAPER, size=8.5) -> tuple[str, float]:
    w = text_width(label, size, weight=700) + 10
    return rrect(x, y, w, 13, 3, fill, "none", 0) + text(x + 5, y + 9.6, label, size, weight=700, fill=fg), w


class _Layout:
    """Measures every block of a decree at one body size, so the card can shrink until it fits."""

    def __init__(self, d: Decree, size: float):
        self.d, self.s = d, size
        self.lh = size * 1.22
        self.w = EW - 24

    def lines(self, s, width, weight=400, style="normal", size=None):
        return wrap(s, width, size or self.s, weight=weight, style=style)

    def area_label(self):
        d = self.d
        n = d.area_text.count(";") + 1 if d.area_kind == "links" else (d.area_text.count(",") + d.area_text.count(" and ") + 1)
        lab = AREA_TAG[d.area_kind]
        if n == 1 and lab.endswith("S") and d.area_kind in ("stops", "links"):
            lab = lab[:-1]
        return lab

    def heights(self):
        d, s, lh = self.d, self.s, self.lh
        title = self.lines(d.title, self.w, 700, size=s + 7.5)
        cause = self.lines(d.cause, self.w, 400, "italic", size=s - 0.5)
        area = self.lines(d.area_text, self.w - 14, 600)
        reveal = self.lines(d.on_reveal, self.w - 14) if d.on_reveal else []
        edict = self.lines(d.edict, self.w - 14)
        pets = []
        for p in d.petitions:
            body = self.lines(p.text, self.w - 48)
            chips = 1 if (p.shared or p.income) else 0
            pets.append((body, chips))
        lapse = self.lines("If it lapses: " + d.lapse, self.w - 14, 400, "italic", size=s - 0.5)
        return title, cause, area, reveal, edict, pets, lapse

    def total(self):
        title, cause, area, reveal, edict, pets, lapse = self.heights()
        s, lh = self.s, self.lh
        h = 60 + len(title) * (s + 9) + len(cause) * (lh - 0.5) + 6
        h += 22 + len(area) * lh + 8
        if reveal:
            h += 22 + len(reveal) * lh + 6
        h += 22 + len(edict) * lh + 8
        for body, chips in pets:
            h += 22 + len(body) * lh + (19 if chips else 0) + 6
        h += 10 + len(lapse) * (lh - 0.5) + 8
        return h


def decree_layout(d: Decree, states: dict) -> tuple[str, dict]:
    size = 11.0
    while size > 8.5 and _Layout(d, size).total() > EH - 4:
        size -= 0.25
    L = _Layout(d, size)
    title, cause, area, reveal, edict, pets, lapse = L.heights()
    lh = L.lh
    pos = {}
    st = states.get(d.issuer, {})
    band = st.get("color") or "#C9D2DC"
    fam = FAMILY_COLOR.get(d.family, INK)
    b = [_frame(EW, EH), _top_band(EW, 50, band)]
    tag, tw = _tag(12, 9, f"DECREE \u00b7 {d.family.upper()}", fam, "#FFFFFF")
    b.append(tag)
    # treasury: coins filled by class, top right
    full = {"rich": 3, "modest": 2, "poor": 1}[d.treasury]
    tx = EW - 12 - 3 * 12
    b.append(text(tx - 3, 19.5, f"Treasury: {d.treasury}", 9, weight=600, anchor="end"))
    for k in range(3):
        b.append(f'<circle cx="{tx + 6 + k * 12}" cy="16" r="4.8" fill="{COIN if k < full else PANEL}" stroke="{INK}" '
                 f'stroke-width="1.1"/>')
    ruler = d.ruler[0].upper() + d.ruler[1:]
    b.append(text(12, 41, ruler, fit_size(ruler, EW - 64, 16, "Barlow Condensed", 700, 10), family="Barlow Condensed",
                  weight=700))
    b.append(text(EW - 12, 41, f"No. {d.number}", 9, weight=600, anchor="end"))
    pos["issuer"] = (0, 50)
    y = 50 + 6
    y0 = y
    for i, ln in enumerate(title):
        y += size + 9
        b.append(text(12, y - 2, ln, size + 7.5, family="Barlow Condensed", weight=700))
    for ln in cause:
        y += lh - 0.5
        b.append(text(12, y, ln, size - 0.5, style="italic", fill=MUTED))
    pos["cause"] = (y0, y + 3)
    y += 6

    def block(label, lines, y, weight=400, fill=PANEL, edge=INK, tagfill=INK):
        h = 22 + len(lines) * lh
        out = [rrect(12, y, EW - 24, h, 5, fill, edge, 1.4)]
        t, _ = _tag(18, y - 6, label, tagfill, "#FFFFFF" if tagfill != INCOME_LANE else INK)
        out.append(t)
        out.append(text_block(19, y + 13 + size * 0.85, lines, size, lh, weight=weight))
        return "".join(out), y + h + 8

    s_, y1 = block(L.area_label(), area, y + 4, 600, "#FFFFFF", INK, INK)
    pos["area"] = (y + 4 - 6, y1 - 8)
    b.append(s_)
    y = y1
    if reveal:
        s_, y1 = block("ON REVEAL", reveal, y + 4, 400, PANEL, EXPENSE, EXPENSE)
        pos["reveal"] = (y + 4 - 6, y1 - 8)
        b.append(s_)
        y = y1 - 2
    s_, y1 = block("EDICT", edict, y + 4, 400, PANEL, fam, fam)
    pos["edict"] = (y + 4 - 6, y1 - 8)
    b.append(s_)
    y = y1 + 2
    pos["petitions"] = (y - 2, None)
    for p, (body, chips) in zip(d.petitions, pets):
        h = 22 + len(body) * lh + (19 if chips else 0)
        b.append(rrect(12, y, EW - 24, h, 5, "#FFFFFF", INK, 1.2))
        cx, cy = 28, y + 17
        b.append(star(cx, cy, 13.5, COIN, INK, 1.3))
        b.append(text(cx, cy + 4.6, str(p.stars), 12.5, family="Barlow Condensed", weight=700, anchor="middle"))
        b.append(text(46, y + 15, p.title, fit_size(p.title, EW - 70, size + 1, "Barlow", 700, 8), weight=700))
        b.append(text_block(46, y + 15 + lh + 1, body, size, lh))
        if chips:
            yy, xx = y + 22 + len(body) * lh, 46
            if p.shared:
                t, w = _tag(xx, yy + 1.5, "SHARED", fam, "#FFFFFF", 8)
                b.append(t)
                xx += w + 5
                g, w = gold_mark(xx, yy, f"pay {p.gold} gold", 10, 15)
                b.append(g)
                xx += w + 8
            if p.income:
                c, w = income_chip(xx, yy, f"+{p.income} income", 10, 15)
                b.append(c)
        y += h + 6
    pos["petitions"] = (pos["petitions"][0], y - 6)
    # lapse footer
    fh = 10 + len(lapse) * (lh - 0.5)
    fy = max(y + 2, EH - 8 - fh)
    b.append(rrect(12, fy, EW - 24, fh, 5, PAPER, RULE, 1, ' stroke-dasharray="3 2"'))
    b.append(text_block(19, fy + 4 + (size - 0.5) * 0.95, lapse, size - 0.5, lh - 0.5, style="italic", fill=MUTED))
    pos["lapse"] = (fy, fy + fh)
    return "".join(b), pos


def decree_front(d: Decree, states: dict) -> str:
    body, _ = decree_layout(d, states)
    return doc(EW, EH, body, f"Decree {d.number}: {d.title}")


def _seal(cx, cy, r, fill=COIN, ink=INK) -> str:
    pts = []
    import math
    for k in range(24):
        a = math.pi * 2 * k / 24
        rr = r if k % 2 == 0 else r * 0.88
        pts.append(f"{cx + rr * math.cos(a):.2f},{cy + rr * math.sin(a):.2f}")
    return (f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{ink}" stroke-width="2"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r * 0.66:.2f}" fill="none" stroke="{ink}" stroke-width="1.5"/>')


def decree_back(world: str = "") -> str:
    b = [rrect(1, 1, EW - 2, EH - 2, 10, "#3B2A1F", INK, 2)]
    b.append(rrect(10, 10, EW - 20, EH - 20, 6, "none", COIN, 1.5))
    b.append(rrect(16, 16, EW - 32, EH - 32, 4, "none", COIN, 0.8, ' stroke-dasharray="2 3"'))
    # a rolled proclamation with a seal
    b.append(rrect(EW / 2 - 70, 120, 140, 150, 4, "#EFE6CF", INK, 2))
    for k in range(6):
        b.append(f'<line x1="{EW / 2 - 52}" y1="{148 + k * 16}" x2="{EW / 2 + 52 - (k % 3) * 14}" y2="{148 + k * 16}" '
                 f'stroke="{RULE}" stroke-width="3" stroke-linecap="round"/>')
    b.append(_seal(EW / 2 + 44, 262, 24, "#A8342A", INK))
    b.append(text(EW / 2, 340, "Decree", 46, family="Barlow Condensed", weight=700, fill=PAPER, anchor="middle"))
    if world:
        b.append(text(EW / 2, 364, f"of the rulers of {world}", 13, weight=500, fill=COIN, anchor="middle"))
    return doc(EW, EH, "".join(b), "Decree card back")


# ------------------------------------------------------------------------------ reference
def reference_decree(gold: dict, settle: int, wide: int, petitions: str = "turn") -> str:
    """Table reference: how to read a decree and its money marks."""
    b = [_frame(EW, EH), _top_band(EW, 44, INK)]
    b.append(text(14, 29, "Reading a decree", 21, family="Barlow Condensed", weight=700, fill=PAPER))
    y = 62
    items = [
        ("ISSUER", f"The ruler and the state's treasury. A shared petition costs rich {gold['rich']}, modest "
                   f"{gold['modest']}, poor {gold['poor']} gold at five stars."),
        ("AFFECTED", "A state, stops or links on the board. A route is affected if it passes through them."),
        ("ON REVEAL  ·  EDICT", "On reveal: once, when drawn. Edict: every round while the decree is in the row."),
        ("PETITIONS", ("Spend stars gained this turn or lose them. " if petitions == "turn" else
                       "At the start of the round, spend the stars from your last turn or lose them. ")
                      + "1: you, this round. 3: you, while it stands. 5: it ends, and you keep the card."),
        ("LAPSE", "A new decree each round, five at most. A sixth pushes out the oldest, which lapses."),
    ]
    for label, body in items:
        t, w = _tag(14, y - 10, label)
        b.append(t)
        lines = wrap(body, EW - 28, 10.5)
        b.append(text_block(14, y + 15, lines, 10.5, 13))
        y += 15 + len(lines) * 13 + 9
    b.append(f'<line x1="14" y1="{y - 4}" x2="{EW - 14}" y2="{y - 4}" stroke="{RULE}" stroke-width="1"/>')
    y += 12
    b.append(text(14, y, "Money marks", 15, family="Barlow Condensed", weight=700))
    y += 9
    for draw, label, note in ((gold_mark, "pay 2 gold", "gold, once"), (income_chip, "+2 income", "the income track"),
                              (expense_chip, "+3 expense", "the expense track")):
        g, _ = draw(14, y, label, 10.5, 16)
        b.append(g)
        b.append(text(112, y + 12, note, 10.5))
        y += 20
    lines = wrap("A petition costs gold only when its benefit is shared by every player. Edict gold is paid or "
                 "gained when you settle accounts.", EW - 28, 10, style="italic")
    b.append(text_block(14, y + 10, lines, 10, 12.5, style="italic", fill=MUTED))
    return doc(EW, EH, "".join(b), "Reference: reading a decree")


def decree_anatomy(d: Decree, states: dict, petitions: str = "turn") -> str:
    """A wide diagram for the rules: one decree with numbered callouts for each part."""
    body, pos = decree_layout(d, states)
    k = 1.55
    W, H = 1180, int(EH * k + 60)
    cx0, cy0 = 30, 30
    b = [f'<rect width="{W}" height="{H}" fill="{PANEL}"/>',
         f'<g transform="translate({cx0} {cy0}) scale({k})">{body}</g>']
    notes = [
        ("issuer", "Issuer and treasury", "The ruler proclaiming the decree, with the state's colour. The treasury "
                                          "(rich, modest or poor) sets the gold price of shared petitions."),
        ("cause", "Title and cause", "What happened in the world, and the map object it comes from: a war, a tariff, "
                                     "a zone, a marker or the slave trade."),
        ("area", "Affected area", "A state, stops or links you can see on the board. A route is affected if it "
                                  "passes through them."),
        ("reveal", "On reveal", "Happens once, when the decree is drawn. Not every decree has one."),
        ("edict", "Edict", "Applies every round while the decree is in the row. Gold in an edict is paid or gained "
                           "when you settle accounts at the start of the round."),
        ("petitions", "Petitions", ("Spend the stars you gained this turn, or lose them. " if petitions == "turn" else
                                    "At the start of the round, spend the stars from your last turn, or lose them. ")
                                   + "One star: for you, this round. "
                                   "Three: for you, while the decree stands (leave a token on it). Five: the decree "
                                   "ends, and you keep the card. A SHARED petition helps every player, so it costs "
                                   "gold. A yellow chip moves your income track; a coin is gold, once."),
        ("lapse", "If it lapses", "A new decree arrives each round, five at most. When a sixth arrives, the oldest "
                                  "lapses and this line happens."),
    ]
    tx = cx0 + EW * k + 70
    tw = W - tx - 30
    y_text = 46
    for n, (key, head, body_t) in enumerate([nt for nt in notes if nt[0] in pos], 1):
        a, bb = pos[key]
        mid = cy0 + ((a + (bb if bb else a + 30)) / 2) * k
        lines = wrap(body_t, tw - 40, 14)
        block_h = 26 + len(lines) * 18
        ty = max(y_text, min(mid - 14, H - block_h - 10))
        # bracket on the card and a leader line
        bx = cx0 + EW * k + 8
        b.append(f'<path d="M{bx},{cy0 + a * k + 3} h8 V{cy0 + (bb or a + 30) * k - 3} h-8" fill="none" '
                 f'stroke="{EXPENSE}" stroke-width="2"/>')
        b.append(f'<path d="M{bx + 8},{mid:.1f} C{bx + 30},{mid:.1f} {tx - 30},{ty + 12:.1f} {tx - 6},{ty + 12:.1f}" '
                 f'fill="none" stroke="{EXPENSE}" stroke-width="1.5"/>')
        b.append(f'<circle cx="{tx + 12}" cy="{ty + 12}" r="12" fill="{EXPENSE}"/>')
        b.append(text(tx + 12, ty + 17, str(n), 14, family="Barlow Condensed", weight=700, fill="#FFFFFF", anchor="middle"))
        b.append(text(tx + 32, ty + 17, head, 17, family="Barlow Condensed", weight=700))
        b.append(text_block(tx + 32, ty + 38, lines, 14, 18))
        y_text = ty + block_h + 10
    return doc(W, H, "".join(b), "Anatomy of a decree")


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
