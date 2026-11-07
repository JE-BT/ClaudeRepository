"""Budget board (A4 landscape, 1123 x 794 px), one per merchant house.

The outer ring holds two lanes numbered 1-50: income on the outside, expense on the inside; the
goal space is dark. Inside:
  house panel     home trades (cheaper to open), infrastructure charter, decree patronage
  station yard    20 stations in rows of five; the first row is free, each further row ends in a red
                  upkeep disc (1, 2, 3) that its last station covers, so upkeep is the highest disc showing
  round and turn  the round start (settle accounts, reveal a decree, draw commissions) and the five steps
  accounts        income - expense - upkeep = gold, starting gold, goal, the +50 marker, the debt boxes
                  (a round ending below 0 gold covers a box; too many in a row and you are out)
  expense track   infrastructure costs (with the house charter), optional freight
  trades          one slot per trade; opening one costs the overhead, less for home trades
"""
from __future__ import annotations

from .decks import House
from .goods import TRADE_COLOR, TRADES
from .svgkit import (AIR_RIM, COIN, EXPENSE, EXPENSE_LANE, EXPENSE_TEN, INCOME_LANE, INCOME_TEN, INK, LAND, MUTED, PANEL,
                     PAPER, RULE, SEA, doc, fit_size, rrect, text, text_block, text_width, wrap)

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


def _track(goal: int) -> str:
    out = []
    for n in range(1, 51):
        j, i, side = _cell(n)
        x, w = _col_x(j), CW
        y, h = _row(i)
        ten, end, g = n % 10 == 0, n == 50, n == goal
        inc_bg = INK if (end or g) else (INCOME_TEN if ten else INCOME_LANE)
        exp_bg = INK if end else (EXPENSE_TEN if ten else EXPENSE_LANE)
        inc_fg = INCOME_LANE if (end or g) else INK
        exp_fg = EXPENSE_LANE if end else INK
        if side in ("top", "bottom"):
            half = h / 2
            inc = (x, y, w, half) if side == "top" else (x, y + half, w, half)
            exp = (x, y + half, w, half) if side == "top" else (x, y, w, half)
        else:
            half = w / 2
            inc = (x + half, y, half, h) if side == "right" else (x, y, half, h)
            exp = (x, y, half, h) if side == "right" else (x + half, y, half, h)
        size = 18 if (ten or g) else 14
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
    lines = wrap(s, width, size, weight=kw.get("weight", 400), style=kw.get("style", "normal"))
    return text_block(x, y, lines, size, lh, **kw), y + len(lines) * lh


def _mode_chip(x, y, mode, w=30, h=19) -> str:
    fill = {"land": LAND, "sea": SEA, "air": "#FFFFFF"}[mode]
    out = rrect(x, y, w, h, 3, fill, INK, 1.4)
    if mode == "air":
        out += rrect(x + 2.5, y + 2.5, w - 5, h - 5, 2, "none", AIR_RIM, 1)
    return out


def _chip(x, y, label, bg, edge, size=12, h=20) -> tuple[str, float]:
    w = text_width(label, size, weight=700) + 12
    return rrect(x, y, w, h, h / 2, bg, edge, 1.5) + text(x + w / 2, y + h / 2 + size * 0.36, label, size, weight=700,
                                                         anchor="middle"), w


def budget_board(h: House, *, goal: int = 50, start_gold: int = 10, stations: int = 20, overhead: int = 30,
                 home_overhead: int = 20, overhead_mode: str = "gold", draw: int = 3, freight: dict | None = None,
                 debt_rounds: int = 3, petitions: str = "turn", trades: list | None = None) -> str:
    trades = trades or TRADES
    unit = "gold" if overhead_mode == "gold" else "expense"
    cost = (lambda n: f"{n} gold") if overhead_mode == "gold" else (lambda n: f"+{n} expense")
    b = [f'<rect width="{W}" height="{H}" fill="{h.colour}"/>', _track(goal)]
    cx0, cy0 = _col_x(1), _row(1)[0]
    cx1 = _col_x(14) + CW
    cy1 = _row(9)[0] + RH
    b.append(rrect(cx0, cy0, cx1 - cx0, cy1 - cy0, 6, PAPER))
    x0, y0, x1, y1 = cx0 + 14, cy0 + 14, cx1 - 14, cy1 - 14
    right_w = 318
    lw = (x1 - x0) - 14 - right_w
    rx = x0 + lw + 14

    # ---------------------------------------------------------------- house panel
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
    home = " and ".join(h.home_trades)
    blocks = [("Home trades", f"{home} open for {cost(home_overhead)}, not {cost(overhead)}."),
              (h.charter[0], h.charter[1]),
              (f"{h.patron[1]}" if h.patron[1] else "Patronage", h.patron[2])]
    for k, (t, body) in enumerate(blocks):
        bx = x0 + 14 + k * (colw + 16)
        b.append(text(bx, y0 + 66, t, fit_size(t, colw, 14, "Barlow", 700, 10), weight=700))
        para, _ = _para(bx, y0 + 85, body, colw, 13, 17)
        b.append(para)

    # ---------------------------------------------------------------- station yard (rows of five)
    yy = y0 + hp_h + 12
    rows = max(1, (stations + 4) // 5)
    pitch = 33
    yh = 44 + rows * pitch + 6
    b.append(_panel(x0, yy, lw, yh))
    b.append(text(x0 + 14, yy + 30, "Station yard", 22, family="Barlow Condensed", weight=700))
    gx = x0 + 28
    for r in range(rows):
        cy = yy + 54 + r * pitch
        for s in range(5):
            cx = gx + s * 34
            if r and s == 4:
                b.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="14.5" fill="{EXPENSE}"/>')
                b.append(text(cx, cy + 6.3, str(r), 18, family="Barlow Condensed", weight=700, fill="#FFFFFF",
                              anchor="middle"))
            else:
                b.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="13" fill="none" stroke="{RULE}" stroke-width="2" '
                         f'stroke-dasharray="4 3"/>')
        if r == 0:
            b.append(text(gx + 4 * 34 + 22, cy + 4.5, "free", 12, weight=600, fill=MUTED))
    tx = gx + 5 * 34 + 36
    para, _ = _para(tx, yy + 56, f"{stations} stations. Take them from the top row, left to right. Your first five "
                    "cost no upkeep; the last station of each further row covers its red disc.", x0 + lw - 14 - tx, 13, 17)
    b.append(para)
    b.append(text(tx, yy + yh - 16, "Upkeep each round is the highest disc showing.", 13, weight=700))

    # ---------------------------------------------------------------- round and turn
    ty = yy + yh + 12
    th = y1 - ty
    half = (th - 8) / 2
    reveal = "Reveal a decree; a sixth makes the oldest lapse"
    drawc = f"Draw {draw} commissions from one trade, one fewer per discard in it; keep 1"
    if petitions == "round":  # every money matter at the start of the round
        rounds = [("A", reveal), ("B", "Petition with the stars from your last turn, or lose them"),
                  ("C", "Settle accounts"), ("D", drawc)]
        turns = [("1", "Place or remove a station"), ("2", "Draw an infrastructure card"), ("3", "Build infrastructure"),
                 ("4", "Declare and balance routes; keep the stars on them for the next round")]
    else:
        rounds = [("A", "Settle accounts"), ("B", reveal), ("C", drawc)]
        turns = [("1", "Place or remove a station"), ("2", "Draw an infrastructure card"), ("3", "Build infrastructure"),
                 ("4", "Declare and balance routes; take the stars on them"),
                 ("5", "Petition: spend those stars or lose them")]
    for row, (label, items) in enumerate((("Round start, everyone", rounds), ("Your turn", turns))):
        ry = ty + row * (half + 8)
        lab_w = 72
        b.append(rrect(x0, ry, lab_w, half, 6, INK))
        for i, ln in enumerate(wrap(label, lab_w - 14, 13, weight=700)):
            b.append(text(x0 + 8, ry + 22 + i * 16, ln, 13, weight=700, fill=PAPER))
        n = len(items)
        sw = (lw - lab_w - 6 - (n - 1) * 6) / n
        for k, (num, s) in enumerate(items):
            sx = x0 + lab_w + 6 + k * (sw + 6)
            b.append(_panel(sx, ry, sw, half))
            b.append(f'<circle cx="{sx + 15}" cy="{ry + 16}" r="10" fill="{INK}"/>')
            b.append(text(sx + 15, ry + 21, num, 13, family="Barlow Condensed", weight=700, fill=PAPER, anchor="middle"))
            size = 12
            lines = wrap(s, sw - 16, size, weight=600)
            while len(lines) * size * 1.2 > half - 36 and size > 9:
                size -= 0.5
                lines = wrap(s, sw - 16, size, weight=600)
            b.append(text_block(sx + 8, ry + 44, lines, size, size * 1.2, weight=600))

    # ---------------------------------------------------------------- accounts
    ay, ah = y0, 206
    b.append(_panel(rx, ay, right_w, ah))
    b.append(text(rx + 12, ay + 28, "Settle accounts", 22, family="Barlow Condensed", weight=700))
    b.append(text(rx + right_w - 12, ay + 27, "start of each round", 12, fill=MUTED, anchor="end"))
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
    goal_txt = "the dark space" if goal < 50 else "the dark corner"
    para, yline = _para(rx + 12, ay + 88, f"Start with {start_gold} gold. Outer lane: income; inner lane: expense; past "
                        f"50, take a +50 marker. Reach {goal} income ({goal_txt}) and the game ends.", right_w - 24,
                        12.5, 16)
    b.append(para)
    # debt boxes
    dy = yline + 4
    b.append(text(rx + 12, dy + 15, "Rounds in debt", 12.5, weight=700))
    bx = rx + 12 + text_width("Rounds in debt", 12.5, weight=700) + 10
    for k in range(debt_rounds + 1):
        last = k == debt_rounds
        b.append(rrect(bx, dy, 26, 22, 4, EXPENSE if last else PANEL, EXPENSE if last else RULE, 1.6,
                       '' if last else ' stroke-dasharray="3 2"'))
        b.append(text(bx + 13, dy + 16, "out" if last else str(k + 1), 11 if last else 13, family="Barlow Condensed",
                      weight=700, fill="#FFFFFF" if last else MUTED, anchor="middle"))
        bx += 31
    para, _ = _para(rx + 12, dy + 38, "Below 0 gold after settling: cover the next box. At 0 or more: clear them all.",
                    right_w - 24, 11.5, 14.5, fill=MUTED)
    b.append(para)

    # ---------------------------------------------------------------- expense track
    by = ay + ah + 10
    bh = 154 if not freight else 168
    b.append(_panel(rx, by, right_w, bh))
    b.append(text(rx + 12, by + 28, "Expense track", 22, family="Barlow Condensed", weight=700))
    base = {"land": 1, "sea": 2, "air": 5}
    special = {"Sky charter": ("air", 4, ""), "Shipwrights' charter": ("sea", 1, ""),
               "Carters' charter": ("land", 0, f"in {h.state_name}")}.get(h.charter[0])
    b.append(text(rx + 12, by + 50, "Build infrastructure", 12, weight=700, fill=MUTED))
    if freight:
        b.append(text(rx + right_w - 12, by + 50, "Freight per pip", 12, weight=700, fill=MUTED, anchor="end"))
    for k, mode in enumerate(("land", "sea", "air")):
        ry = by + 58 + k * 26
        b.append(_mode_chip(rx + 12, ry, mode))
        b.append(text(rx + 50, ry + 15, mode.capitalize(), 14, weight=600))
        c, w = _chip(rx + 90, ry - 0.5, f"+{base[mode]} expense", EXPENSE_LANE, EXPENSE_TEN, 11.5, 20)
        b.append(c)
        if special and special[0] == mode:
            note = f"you: +{special[1]}" + (f" {special[2]}" if special[2] else "")
            b.append(text(rx + 90 + w + 7, ry + 15, note, fit_size(note, right_w - 110 - w - (40 if freight else 0),
                                                                    12.5, "Barlow", 700, 9), weight=700, fill=EXPENSE))
        if freight:
            b.append(text(rx + right_w - 12, ry + 15, f"+{freight.get(mode, 0):g}", 15, family="Barlow Condensed",
                          weight=700, fill=EXPENSE, anchor="end"))
    yl = by + 58 + 3 * 26
    if not freight:  # with freight the freight note takes this line
        para, yl = _para(rx + 12, yl + 6, "Removing infrastructure moves the marker back down.", right_w - 24, 11.5,
                         14.5, fill=MUTED)
        b.append(para)
    if freight:
        para, _ = _para(rx + 12, yl + 15, "Freight is added when you declare, by the dearest mode on the route.",
                        right_w - 24, 11.5, 14.5, fill=MUTED)
        b.append(para)

    # ---------------------------------------------------------------- trades
    ky = by + bh + 10
    b.append(_panel(rx, ky, right_w, y1 - ky))
    b.append(text(rx + 12, ky + 26, "Trades", 22, family="Barlow Condensed", weight=700))
    label = f"open: {cost(overhead)}"
    if unit == "expense":  # a track move: red chip
        w = text_width(label, 11.5, weight=700) + 12
        b.append(_chip(rx + right_w - 12 - w, ky + 10, label, EXPENSE_LANE, EXPENSE_TEN, 11.5, 20)[0])
    else:  # gold, once: coin mark, as on the decrees
        w = text_width(label, 12, weight=700)
        gx = rx + right_w - 12 - w - 22
        b.append(f'<circle cx="{gx + 9}" cy="{ky + 20}" r="8.5" fill="{COIN}" stroke="{INK}" stroke-width="1.3"/>')
        b.append(text(gx + 9, ky + 23.3, "g", 9.5, family="Barlow Condensed", weight=700, anchor="middle"))
        b.append(text(gx + 22, ky + 24.5, label, 12, weight=700))
    cols = 3
    nrows = (len(trades) + cols - 1) // cols
    sw2, sh2 = (right_w - 24 - (cols - 1) * 6) / cols, 30
    for k, t in enumerate(trades):
        sx = rx + 12 + (k % cols) * (sw2 + 6)
        sy = ky + 36 + (k // cols) * (sh2 + 5)
        home_t = t in h.home_trades
        col = TRADE_COLOR[t]
        b.append(rrect(sx, sy, sw2, sh2, 5, PANEL, col, 2.6 if home_t else 2, '' if home_t else ' stroke-dasharray="4 3"'))
        b.append(text(sx + sw2 / 2, sy + (14 if home_t else 20), t, fit_size(t, sw2 - 10, 13, "Barlow", 600, 9),
                      weight=600, anchor="middle"))
        if home_t:
            b.append(text(sx + sw2 / 2, sy + 25.5, f"HOME \u00b7 {cost(home_overhead)}", 8.5, weight=700, fill=col,
                          anchor="middle"))
    if overhead_mode == "expense":
        rule = (f"Your first commission in a trade opens it: cover its slot, {cost(overhead)} "
                f"({cost(home_overhead)} at home). Hold none and it closes: uncover it, marker back down.")
    else:
        rule = (f"Your first commission in a trade opens it: pay {cost(overhead)} ({cost(home_overhead)} at home) and "
                "cover its slot. Hold none in it and it closes: uncover it; reopening costs again.")
    size, lh = (11.5, 14.5) if not freight else (11, 13.5)
    para, _ = _para(rx + 12, ky + 36 + nrows * (sh2 + 5) + (10 if not freight else 7), rule, right_w - 24, size, lh,
                    fill=MUTED)
    b.append(para)
    return doc(W, H, "".join(b), f"Budget board: House of {h.town}")
