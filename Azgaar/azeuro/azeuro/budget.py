"""Budget board (A4 landscape, 1123 x 794 px), one per merchant house.

The outer ring holds two lanes numbered 1-50: income on the outside, expense on the inside.
The station yard keeps the player's 50 stations in 10 columns of 5; the bottom spot of each
column is a red upkeep disc that the fifth station covers. Building from the top of the leftmost
column uncovers the discs in order, so upkeep is always the highest number showing.
"""
from __future__ import annotations

from .decks import House
from .svgkit import (COIN, EXPENSE, EXPENSE_LANE, EXPENSE_TEN, INCOME_LANE, INCOME_TEN, INK, LAND, MUTED,
                     PANEL, PAPER, RULE, SEA, doc, fit_size, rrect, text, text_block, text_width, wrap)

W, H, M, GAP = 1123, 794, 28, 4
CW = (W - 2 * M - 15 * GAP) / 16
EDGE = 76
RH = (H - 2 * M - 2 * EDGE - 10 * GAP) / 9


def _col_x(j: int) -> float:
    return M + j * (CW + GAP)


def _row(i: int) -> tuple[float, float]:
    if i == 0:
        return M, EDGE
    if i == 10:
        return H - M - EDGE, EDGE
    return M + EDGE + GAP + (i - 1) * (RH + GAP), RH


def _cell(n: int) -> tuple[int, int, str]:
    if n <= 15:
        return n, 0, "top"
    if n <= 24:
        return 15, n - 15, "right"
    if n <= 40:
        return 40 - n, 10, "bottom"
    if n <= 49:
        return 0, 50 - n, "left"
    return 0, 0, "top"


def _track() -> str:
    out = []
    for n in range(1, 51):
        j, i, side = _cell(n)
        x, w = _col_x(j), CW
        y, h = _row(i)
        ten, end = n % 10 == 0, n == 50
        inc_bg = INK if end else (INCOME_TEN if ten else INCOME_LANE)
        exp_bg = INK if end else (EXPENSE_TEN if ten else EXPENSE_LANE)
        inc_fg = INCOME_LANE if end else INK
        exp_fg = EXPENSE_LANE if end else INK
        if side in ("top", "bottom"):
            half = h / 2
            inc = (x, y, w, half) if side == "top" else (x, y + half, w, half)
            exp = (x, y + half, w, half) if side == "top" else (x, y, w, half)
        else:
            half = w / 2
            inc = (x + half, y, half, h) if side == "right" else (x, y, half, h)
            exp = (x, y, half, h) if side == "right" else (x + half, y, half, h)
        size = 18 if ten else 14
        weight = 700 if n % 5 == 0 else 500
        for (rx, ry, rw, rh), bg, fg in ((inc, inc_bg, inc_fg), (exp, exp_bg, exp_fg)):
            out.append(f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{rw:.2f}" height="{rh:.2f}" fill="{bg}"/>')
            out.append(text(rx + rw / 2, ry + rh / 2 + size * 0.35, str(n), size, family="Barlow Condensed",
                            weight=weight, fill=fg, anchor="middle"))
        if side in ("top", "bottom"):
            out.append(f'<line x1="{x:.2f}" y1="{y + h / 2:.2f}" x2="{x + w:.2f}" y2="{y + h / 2:.2f}" stroke="{INK}" stroke-width="1"/>')
        else:
            out.append(f'<line x1="{x + w / 2:.2f}" y1="{y:.2f}" x2="{x + w / 2:.2f}" y2="{y + h:.2f}" stroke="{INK}" stroke-width="1"/>')
        out.append(rrect(x, y, w, h, 4, "none", INK, 1.5))
    return "".join(out)


def _panel(x, y, w, h) -> str:
    return rrect(x, y, w, h, 6, PANEL, INK, 2)


def _para(x, y, s, width, size=13, lh=17, **kw) -> tuple[str, float]:
    lines = wrap(s, width, size, weight=kw.get("weight", 400))
    return text_block(x, y, lines, size, lh, **kw), y + len(lines) * lh


def budget_board(h: House) -> str:
    b = [f'<rect width="{W}" height="{H}" fill="{h.colour}"/>', _track()]
    cx0, cy0 = _col_x(1), _row(1)[0]
    cx1 = _col_x(14) + CW
    cy1 = _row(9)[0] + RH
    b.append(rrect(cx0, cy0, cx1 - cx0, cy1 - cy0, 6, PAPER))
    x0, y0, x1, y1 = cx0 + 14, cy0 + 14, cx1 - 14, cy1 - 14
    right_w = 318
    lw = (x1 - x0) - 14 - right_w
    rx = x0 + lw + 14

    # house panel
    hp_h = 150
    b.append(_panel(x0, y0, lw, hp_h))
    b.append(f'<path d="M{x0 + 6},{y0} H{x0 + lw - 6} A6,6 0 0 1 {x0 + lw},{y0 + 6} V{y0 + 44} H{x0} V{y0 + 6} '
             f'A6,6 0 0 1 {x0 + 6},{y0} Z" fill="{h.colour}"/>')
    b.append(rrect(x0, y0, lw, hp_h, 6, "none", INK, 2))
    title = f"House of {h.town}"
    b.append(text(x0 + 14, y0 + 32, title, 30, family="Barlow Condensed", weight=700, fill="#FFFFFF"))
    sub = f"Merchant house of the {h.state_full}"
    room = lw - 42 - text_width(title, 30, "Barlow Condensed", 700)
    b.append(text(x0 + lw - 14, y0 + 30, sub, fit_size(sub, room, 13, "Barlow", 500, 9), weight=500,
                  fill="#FFFFFF", anchor="end"))
    colw = (lw - 28 - 32) / 3
    goods = " or ".join(h.goods[:2])
    blocks = [("Specialty goods", f"Gain 1 extra income when you complete a commission for {goods}."),
              (h.charter[0], h.charter[1]),
              (f"Rooted in {h.state_name}", h.favour)]
    for k, (t, body) in enumerate(blocks):
        bx = x0 + 14 + k * (colw + 16)
        b.append(text(bx, y0 + 66, t, fit_size(t, colw, 14, "Barlow", 700, 10), weight=700))
        para, _ = _para(bx, y0 + 85, body, colw, 13, 17)
        b.append(para)

    # station yard
    yy = y0 + hp_h + 12
    yh = 286
    b.append(_panel(x0, yy, lw, yh))
    b.append(text(x0 + 14, yy + 30, "Station yard", 22, family="Barlow Condensed", weight=700))
    b.append(text(x0 + lw - 14, yy + 29, "Upkeep each turn is the highest number showing", 13, fill=MUTED, anchor="end"))
    gx0, gw = x0 + 14, lw - 28
    colw2 = (gw - 9 * 6) / 10
    top = yy + 42
    col_h = 8 + 4 * 36 + 30 + 8
    for k in range(10):
        cx = gx0 + k * (colw2 + 6)
        b.append(rrect(cx, top, colw2, col_h, 6, PAPER))
        mx = cx + colw2 / 2
        for s in range(4):
            b.append(f'<circle cx="{mx:.2f}" cy="{top + 23 + s * 36:.2f}" r="14" fill="none" stroke="{RULE}" '
                     f'stroke-width="2" stroke-dasharray="4 3"/>')
        cy = top + 23 + 4 * 36
        b.append(f'<circle cx="{mx:.2f}" cy="{cy:.2f}" r="15" fill="{EXPENSE}"/>')
        b.append(text(mx, cy + 6.3, str(k + 1), 18, family="Barlow Condensed", weight=700, fill="#FFFFFF", anchor="middle"))
    para, _ = _para(x0 + 14, top + col_h + 22,
                    "Build from the top of the leftmost column. The fifth station in each column covers its red "
                    "disc. A removed station goes back into the rightmost column with room.", lw - 28, 13, 17)
    b.append(para)

    # turn summary
    ty = yy + yh + 12
    th = y1 - ty
    steps = ["Place or remove a station", "Draw an infrastructure card", "Build infrastructure",
             "Declare commissions and show routes", "Settle accounts"]
    sw = (lw - 4 * 8) / 5
    for k, s in enumerate(steps):
        sx = x0 + k * (sw + 8)
        b.append(_panel(sx, ty, sw, th))
        b.append(f'<circle cx="{sx + 18}" cy="{ty + 20}" r="11" fill="{INK}"/>')
        b.append(text(sx + 18, ty + 25, str(k + 1), 14, family="Barlow Condensed", weight=700, fill=PAPER, anchor="middle"))
        para, _ = _para(sx + 10, ty + 48, s, sw - 18, 12.5, 15.5, weight=600)
        b.append(para)

    # accounts
    ay, ah = y0, 214
    b.append(_panel(rx, ay, right_w, ah))
    b.append(text(rx + 12, ay + 28, "Each turn", 22, family="Barlow Condensed", weight=700))
    chips = [("Income", INCOME_LANE, INK), ("\u2212", None, INK), ("Expense", EXPENSE_LANE, INK), ("\u2212", None, INK),
             ("Upkeep", EXPENSE, "#FFFFFF"), ("=", None, INK), ("Gold", INK, PANEL)]
    cx = rx + 12
    for label, bg, fg in chips:
        if bg is None:
            b.append(text(cx + 5, ay + 61, label, 16, weight=600, anchor="middle"))
            cx += 12
            continue
        w = text_width(label, 13, weight=600) + 12
        b.append(rrect(cx, ay + 42, w, 26, 4, bg, INK, 1.5))
        b.append(text(cx + w / 2, ay + 60, label, 13, weight=600, fill=fg, anchor="middle"))
        cx += w + 6
    yline = ay + 92
    for s in ("Outer lane: income. Inner lane: expense. Both markers start off the track at 0.",
              "Pass 50 on either lane: take a +50 marker and carry on from 1.",
              "Reach 50 income (the dark corner) and the game ends. Run out of gold and you are out."):
        para, yline = _para(rx + 12, yline, s, right_w - 24, 13, 17)
        b.append(para)
        yline += 6

    # building
    by, bh = ay + ah + 10, 150
    b.append(_panel(rx, by, right_w, bh))
    b.append(text(rx + 12, by + 28, "Building infrastructure", 22, family="Barlow Condensed", weight=700))
    base = {"Land": 1, "Sea": 2, "Air": 5}
    special = {"Sky charter": ("Air", 4, ""), "Shipwrights' charter": ("Sea", 1, ""),
               "Carters' charter": ("Land", 0, f"in {h.state_name}")}.get(h.charter[0])
    for k, (name, fill) in enumerate((("Land", LAND), ("Sea", SEA), ("Air", "#FFFFFF"))):
        ry = by + 44 + k * 28
        b.append(rrect(rx + 12, ry, 30, 20, 3, fill, INK, 1.5))
        b.append(text(rx + 52, ry + 15, name, 15, weight=600))
        val = f"+{base[name]}"
        if special and special[0] == name:
            note = f"you: +{special[1]}" + (f" {special[2]}" if special[2] else "")
            b.append(text(rx + right_w - 12, ry + 15, note, 13, weight=600, fill=EXPENSE, anchor="end"))
            nx = rx + right_w - 22 - text_width(note, 13, weight=600)
            b.append(text(nx, ry + 16, val, 18, family="Barlow Condensed", weight=700, fill=EXPENSE, anchor="end"))
        else:
            b.append(text(rx + right_w - 12, ry + 16, val, 18, family="Barlow Condensed", weight=700, fill=EXPENSE,
                          anchor="end"))
    b.append(text(rx + 12, by + bh - 14, "Removing it moves the marker back down.", 13, fill=MUTED))

    # broken contracts
    ky = by + bh + 10
    kh = y1 - ky
    b.append(_panel(rx, ky, right_w, kh))
    b.append(text(rx + 12, ky + 28, "Broken contracts", 22, family="Barlow Condensed", weight=700))
    para, yl = _para(rx + 12, ky + 48, "Place a state\u2019s breach marker here when its commission fails on your "
                     "watch. When you draw from that state, draw one fewer card.", right_w - 24, 13, 17)
    b.append(para)
    slot_w = (right_w - 24 - 5 * 6) / 6
    sy = max(yl + 2, ky + kh - 50)
    for k in range(6):
        b.append(rrect(rx + 12 + k * (slot_w + 6), sy, slot_w, 38, 5, "none", RULE, 2, ' stroke-dasharray="4 3"'))
    return doc(W, H, "".join(b), f"Budget board: House of {h.town}")
