"""The upload instructions (markdown) and a self-contained HTML report of the run."""
from __future__ import annotations

import html
import re
from datetime import date

import numpy as np

PALETTE = ["#2f6f8f", "#c0603a", "#5b8c3a", "#8a5aa8", "#c9a227", "#3a8c80", "#a83a5b", "#6b6b6b", "#4a5fc1",
           "#9c6b30"]


def instructions(world: str, files: dict, res: dict, opts: dict) -> str:
    has = lambda prefix: any(n.startswith(prefix) for n in files)
    steps = [
        "Save the map you have open (**Save → Save to machine**). Uploads change the map at once and cannot be "
        "undone.",
        f"**Load** `1 {world} azdev.map` (**Load → Load from machine**). It is your map with only its settings record "
        f"changed: {len(res['new_goods'])} goods added, every good's culture multipliers set from the run, and the "
        "era names from 40 up renamed. Your goods now also carry over to new maps in this browser; "
        "*Tools → Regenerate → Economy → Restore goods* brings the defaults back.",
    ]
    if has("2 "):
        steps.append(f"**Tools → Biomes**, upload `2 {world} Biomes.csv` (the upload button beside the download "
                     "button). Check the preview: only the Development column changes. Apply.")
    steps += [
        f"**Tools → Cultures**, upload `3 {world} Cultures.csv`. The preview lists each culture's new Development "
        "level and its tags. Apply.",
        "**Tools → Development** (Shift + X), press **Regenerate**. Culture levels and biome offsets do nothing until "
        "this is pressed. Painted development is replaced.",
    ]
    if has("5 "):
        steps.append(f"**Tools → States**, upload `5 {world} States.csv`. Only the Form column changes (full names "
                     "are rebuilt); listed forms keep each state's government. Skip this step to keep your titles.")
    steps += [
        f"**Tools → Notes → Upload notes from PC**, `6 {world} Notes.csv`. Each culture gets its profile from the "
        "run, added below any note it already has.",
        "**Tools → Regenerate → Economy**. Leave **Restore goods** unticked (it would remove the new goods); keep "
        "**Production** ticked. Tick **Deposits** too only if you want deposits re-placed.",
        "Check the result: *Tools → Development* for the eras, the *Goods* layer for who makes the new goods, "
        "a culture's note for its profile. Then save the map.",
    ]
    out = [f"# {world}: moving to the full development scale", "",
           f"Made by azdev on {date.today().isoformat()}. Do the steps in this order: development must be "
           "regenerated before the economy, and the goods must be in the map before production runs.", ""]
    for i, s in enumerate(steps, 1):
        out.append(f"{i}. {s}")
    out += ["", "## What each file changes", "",
            "| File | Changes | How |", "| --- | --- | --- |",
            f"| `1 {world} azdev.map` | goods catalogue, culture multipliers on goods, era names | Load |"]
    if has("2 "):
        out.append(f"| `2 {world} Biomes.csv` | biome Development offsets | Biomes editor upload |")
    out.append(f"| `3 {world} Cultures.csv` | culture Development levels, tags | Cultures editor upload |")
    if has("5 "):
        out.append(f"| `5 {world} States.csv` | state form names | States editor upload |")
    out += [f"| `6 {world} Notes.csv` | culture (and retitled state) notes | Notes editor upload |",
            f"| `{world} azdev report.html` | what the run found and why | open in a browser |", ""]
    if res["skipped_goods"]:
        out += ["## Goods left out", ""] + [f"- {s}" for s in res["skipped_goods"]] + [""]
    return "\n".join(out)


def _bar_svg(rows: list[tuple[str, float, float]], width=640, title_a="now", title_b="after") -> str:
    h = 22 * len(rows) + 30
    mx = max([max(a, b) for _, a, b in rows] + [1])
    lab_w = 170
    sc = (width - lab_w - 110) / mx
    parts = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for i, (name, a, b) in enumerate(rows):
        y = 20 + i * 22
        parts.append(f'<text x="{lab_w - 8}" y="{y + 12}" text-anchor="end" class="lab">{html.escape(name)}</text>')
        parts.append(f'<rect x="{lab_w}" y="{y + 1}" width="{a * sc:.1f}" height="8" class="a"/>')
        parts.append(f'<rect x="{lab_w}" y="{y + 10}" width="{b * sc:.1f}" height="8" class="b"/>')
        parts.append(f'<text x="{lab_w + max(a, b) * sc + 6:.1f}" y="{y + 15}" class="num">{a:.0f} → {b:.0f}</text>')
    parts.append(f'<text x="{lab_w}" y="12" class="key"><tspan class="ka">■</tspan> {title_a}   '
                 f'<tspan class="kb">■</tspan> {title_b}</text></svg>')
    return "".join(parts)


def short(label: str) -> str:
    return " · ".join(label.split(" · ")[:2])


def _md(text: str) -> str:
    """The few markdown marks the instructions use, as HTML."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def _scatter_svg(d, cat, width=640, height=380) -> str:
    if len(d.axes) < 2:
        return ""
    # positions: median axis scores reconstructed from held practices
    H = d.H
    S = d.P_med @ H.T
    xs, ys = S[:, 0], S[:, 1]
    pad = 40
    fx = lambda v: pad + (v - xs.min()) / (np.ptp(xs) or 1) * (width - 2 * pad)
    fy = lambda v: height - pad - (v - ys.min()) / (np.ptp(ys) or 1) * (height - 2 * pad)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">',
             f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" class="ax"/>',
             f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" class="ax"/>',
             f'<text x="{width / 2}" y="{height - 8}" text-anchor="middle" class="lab">axis 1: '
             f'{html.escape(short(d.axes[0]["label"]))}</text>',
             f'<text x="14" y="{height / 2}" transform="rotate(-90 14 {height / 2})" text-anchor="middle" '
             f'class="lab">axis 2: {html.escape(short(d.axes[1]["label"]))}</text>']
    for c in d.community:
        i = c["i"]
        r = 3 + 6 * np.sqrt(c["n"] / max(x["n"] for x in d.community))
        col = PALETTE[c["basin"] % len(PALETTE)]
        vx, vy = c["velocity"][0], c["velocity"][1]
        parts.append(f'<circle cx="{fx(xs[i]):.1f}" cy="{fy(ys[i]):.1f}" r="{r:.1f}" fill="{col}" fill-opacity="0.7">'
                     f'<title>{html.escape(d.basins[c["basin"]]["name"])}, depth {c["depth"]:.0f}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def html_report(world: str, mapfile: str, opts: dict, cat, d, res: dict, inst_md: str, runs_info: dict) -> str:
    esc = html.escape
    cults = res["cultures"]
    rows = [(r["Name"], r["old"], r["Development"]) for r in cults]
    eras = [e["name"] for e in res["eras"]]
    era_rows = [(e, res["eras_now"].get(e, 0), res["eras_pred"].get(e, 0)) for e in eras
                if res["eras_now"].get(e, 0) or res["eras_pred"].get(e, 0)]
    basin_rows = []
    for b in d.basins:
        held = sum(1 for c in d.community if c["basin"] == b["i"])
        rd = b.get("reading", {})
        basin_rows.append(
            f"<tr><td><span class='dot' style='background:{PALETTE[b['i'] % len(PALETTE)]}'></span>{esc(b['name'])}"
            f"{' <i>(addition)</i>' if rd.get('addition') else ''}</td><td>{held}</td>"
            f"<td>{esc(', '.join(cat.practices[cat.ki[k]]['name'].lower() for k in b['top'][:4]))}</td>"
            f"<td>{b['scenarios_present']}/7{'' if b['robust'] else ' · theory-dependent'}</td>"
            f"<td>{esc(rd.get('ignores', ''))}</td></tr>")
    scen_ids = sorted({sid for row in d.scenario_table.values() for sid in row})
    sc_names = {s["id"]: s["name"] for s in cat.scenarios["scenarios"]}
    scen_head = "".join(f"<th title='{esc(sc_names.get(s, s))}'>{s}</th>" for s in scen_ids)
    scen_rows = "".join(
        f"<tr><td>{esc(name)}</td>" + "".join(
            f"<td style='background:rgba(47,111,143,{v:.2f})'>{v:.0%}</td>" for v in (row[s] for s in scen_ids))
        + "</tr>" for name, row in d.scenario_table.items())
    diag_rows = "".join(
        f"<tr><td>{x['id']}</td><td>{esc(x['name'])}</td><td class='{'bad' if x['failed'] else 'ok' if x['failed'] is False else 'na'}'>"
        f"{'fails' if x['failed'] else 'passes' if x['failed'] is False else 'not run'}</td><td>{esc(x['detail'])}</td></tr>"
        for x in d.diagnostics)
    axes_rows = "".join(f"<tr><td>{a['i'] + 1}</td><td>{esc(a['label'])}</td><td>{a['share']:.0%}</td>"
                        f"<td>{esc(', '.join(a['top']))}</td></tr>" for a in d.axes)
    cult_rows = []
    for r in cults:
        mem = [c for c in d.community if c["culture"] == r["Id"]]
        top = max(mem, key=lambda c: c["n"])
        cult_rows.append(
            f"<tr><td>{esc(r['Name'])}</td><td>{r['old']}</td><td><b>{r['Development']}</b></td>"
            f"<td>{r['target']:.0f} ({top['depth_lo']:.0f}–{top['depth_hi']:.0f})</td><td>{esc(r['basin'])}</td>"
            f"<td>{esc(', '.join(cat.stocks[h]['name'].lower() for h in top['shadow']) or '—')}</td>"
            f"<td>{esc(', '.join(cat.practices[cat.ki[k]]['name'].lower() for k in top['dormant'][:3]) or '—')}</td></tr>")
    goods_rows = []
    mult = res["multipliers"]
    for g in sorted(res["new_goods"], key=lambda g: g["development"]):
        makers = [r["Name"] for r in cults if mult.get(g["i"], {}).get(str(r["Id"]), 0) >= 0.5]
        goods_rows.append(f"<tr><td>{esc(g['name'])}</td><td>{g['development']}</td><td>{g['value']}</td>"
                          f"<td>{esc(', '.join(f'{k} {v}' for k, v in g.get('demandCoverage', {}).items()))}</td>"
                          f"<td>{esc(', '.join(makers) or '—')}</td></tr>")
    biome_rows = "".join(f"<tr><td>{esc(b['Biome'])}</td><td>{b['old']:+d}</td><td><b>{b['Development']:+d}</b></td></tr>"
                         for b in res["biomes"] if b["Development"] != b["old"])
    state_rows = "".join(f"<tr><td>{esc(s['State'])}</td><td>{esc(s['old'] or '—')}</td><td><b>{esc(s['Form'])}</b></td>"
                         f"<td>{esc(s['why'])}</td></tr>" for s in res["states"])
    steps_html = "".join(f"<li>{_md(line.split('. ', 1)[1])}</li>"
                         for line in inst_md.splitlines() if re.match(r"^\d+\. ", line))
    fails = [x for x in d.diagnostics if x["failed"]]
    sc_claim = {s["id"]: s["claim"] for s in cat.scenarios["scenarios"]}
    layer_rows = "".join(
        f"<tr><td>{sid} {esc(sc_names.get(sid, ''))}</td><td>{esc(sc_claim.get(sid, ''))}</td>"
        f"<td>{esc(', '.join(cat.practices[cat.ki[k]]['name'].lower() for k in ks))}</td></tr>"
        for sid, ks in d.layers.items())
    stat = runs_info.get("depth_stat", 50)
    which = "the median run" if stat == 50 else f"the {stat:.0f}th percentile of runs (a more favourable history)"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{esc(world)} · azdev report</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--ink:#1f2328;--mute:#5d6670;--line:#d9dde2;--bg:#fbfaf7;--a:#b8c4cc;--b:#2f6f8f}}
body{{font:15px/1.55 Georgia,'Iowan Old Style',serif;color:var(--ink);background:var(--bg);margin:0}}
main{{max-width:980px;margin:0 auto;padding:32px 24px 80px}}
h1{{font-size:30px;margin:0 0 4px}} h2{{font-size:21px;margin:36px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}}
.sub{{color:var(--mute);font-family:system-ui,sans-serif;font-size:13px}}
table{{border-collapse:collapse;width:100%;font:13px/1.4 system-ui,sans-serif;margin:8px 0}}
th,td{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}} th{{color:var(--mute);font-weight:600}}
.lab{{font:12px system-ui,sans-serif;fill:var(--ink)}} .num,.key{{font:11px system-ui,sans-serif;fill:var(--mute)}}
.a{{fill:var(--a)}} .b{{fill:var(--b)}} .ka{{fill:var(--a)}} .kb{{fill:var(--b)}} .ax{{stroke:var(--line)}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
.bad{{color:#a32020;font-weight:600}} .ok{{color:#2f6b2f}} .na{{color:var(--mute)}}
ol li{{margin:4px 0}} .note{{background:#f1efe8;border-left:3px solid #c9a227;padding:8px 12px;font-size:14px}}
</style></head><body><main>
<h1>{esc(world)}: development without a ladder</h1>
<div class="sub">{esc(mapfile)} · {runs_info['runs']} runs ({runs_info['scenarios']} scenarios × {runs_info['seeds']} seeds) ·
{runs_info['steps']} steps from the {esc(runs_info['start'])} · {len(d.community)} communities · azdev {date.today().isoformat()}</div>
<p>The Generator reads one number per cell. Here that number is the <b>depth of elaboration</b> a people sustains along
its own path: the tier of the most elaborate practice it keeps up. Two peoples at 60 can be at 60 in different ways,
and the goods each can make, how much it makes of each, and what its state is called follow the path, not the number.</p>
{('<p class="note">Failure checks that did not pass: ' + esc(', '.join(f"{x['id']} {x['name']}" for x in fails)) + '. See below.</p>') if fails else ''}
<h2>Upload order</h2><ol>{steps_html}</ol>
<h2>Cultures</h2>{_bar_svg(rows, title_a='level now', title_b='new level')}
<table><tr><th>Culture</th><th>Now</th><th>New</th><th>People's depth (range)</th><th>Main basin</th><th>Shadow</th><th>Dormant pathways</th></tr>{''.join(cult_rows)}</table>
<h2>Eras on the land</h2><p class="sub">Peopled cells by era, now and after Development is regenerated (predicted by an exact port of the Generator's field).</p>
{_bar_svg(era_rows, title_a='cells now', title_b='cells after')}
<h2>Basins found</h2><p class="sub">Clusters of the states communities came to rest in, named after the fact by their practices. None was placed.</p>
<table><tr><th>Basin</th><th>Communities</th><th>Held together by</th><th>Scenarios</th><th>Tends to ignore (spec reading)</th></tr>{''.join(basin_rows)}</table>
<h3>Where the communities sit</h3>{_scatter_svg(d, cat)}
<h3>Which theories produce which basins</h3><table><tr><th>Basin</th>{scen_head}</tr>{scen_rows}</table>
<h3>What each theory gives the whole world</h3><p class="sub">Institutions held across most of a run's communities: the theory's layer, shared by every basin.</p>
<table><tr><th>Scenario</th><th>Claim</th><th>Institutions everywhere</th></tr>{layer_rows}</table>
<h2>Axes of this world</h2><p class="sub">Found by non-negative factorisation of the communities' practice intensities. Axes overlap, so the variance each carries alone does not add up to 100%.</p>
<table><tr><th>#</th><th>Axis</th><th>Variance alone</th><th>Loads on</th></tr>{axes_rows}</table>
<h2>Failure checks</h2><table><tr><th></th><th>Check</th><th>Result</th><th>Detail</th></tr>{diag_rows}</table>
<h2>New goods</h2><table><tr><th>Good</th><th>Tier</th><th>Value</th><th>Covers</th><th>Cultures that make it (multiplier ≥ 0.5)</th></tr>{''.join(goods_rows)}</table>
{('<h2>Biome offsets</h2><table><tr><th>Biome</th><th>Now</th><th>New</th></tr>' + biome_rows + '</table>') if biome_rows else ''}
{('<h2>State titles</h2><table><tr><th>State</th><th>Now</th><th>New</th><th>Why</th></tr>' + state_rows + '</table>') if state_rows else ''}
<h2>Reading this</h2>
<p>The run is a thinking tool, not a forecast. Basins marked theory-dependent appear only under some of the seven rival
accounts of how practices couple; each people's level is taken from {which} across all of them. The catalogue of
practices, goods and their properties is where the remaining value judgements sit; it is in <code>azdev/data</code>
and can be changed.</p>
{('<p class="note">F6 failed: fixing attention barely changed where communities ended up, so in this world the basins are '
  'carried by geography and coupling and the attention feedback does little work. Read the attention and shadow '
  'columns with that in mind.</p>') if any(x['id'] == 'F6' and x['failed'] for x in d.diagnostics) else ''}
</main></body></html>"""
