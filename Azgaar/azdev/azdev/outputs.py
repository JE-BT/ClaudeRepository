"""Turn the derived world into files the Generator takes: CSV uploads, a notes file and a .map whose
settings record (goods and era names) is patched. Every other byte of the map is left alone."""
from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path

import numpy as np

from .catalogue import Catalogue
from .derive import Derived
from .development import (CULTURE_TYPE_DEVELOPMENT, DEFAULT_DEVELOPMENT, TRIBAL_DEVELOPMENT, DevelopmentField,
                          productivity)
from .graph import PackGraph
from .mapfile import AzgaarMap, compact_json
from .model import Model
from .world import World

STATE_FORMS = {
    "Monarchy": ["Beylik", "Chiefdom", "Despotate", "Dominion", "Duchy", "Emirate", "Empire", "Horde", "Grand Duchy",
                 "Heptarchy", "Khaganate", "Khanate", "Kingdom", "Marches", "Paramount Chiefdom", "Principality",
                 "Satrapy", "Shogunate", "Sultanate", "Tsardom", "Tribe", "Ulus", "Viceroyalty"],
    "Republic": ["Chancellery", "City-state", "Diarchy", "Federation", "Free City", "Junta", "Most Serene Republic",
                 "Oligarchy", "Protectorate", "Republic", "Tetrarchy", "Trade Company", "Tribal Council",
                 "Triumvirate"],
    "Union": ["Clans Union", "Confederacy", "Confederation", "Conglomerate", "Commonwealth", "League", "Union",
              "United Hordes", "United Kingdom", "United Provinces", "United Republic", "United States",
              "United Tribes"],
    "Theocracy": ["Bishopric", "Brotherhood", "Caliphate", "Diocese", "Divine Duchy", "Divine Grand Duchy",
                  "Divine Principality", "Divine Kingdom", "Divine Empire", "Eparchy", "Exarchate", "Holy State",
                  "Imamah", "Patriarchate", "See", "Shamanate", "Thearchy", "Theocracy", "Priesthood"],
    "Anarchy": ["Commune", "Community", "Council", "Free Territory", "Tribes"],
}
TRIBAL = {"Tribe", "Chiefdom", "Paramount Chiefdom", "Horde", "Tribal Council", "Clans Union", "Shamanate"}
NOTE_MARK = '<div title="azdev">'
NOTE_RE = re.compile(r'<div title="azdev">.*?</div><!--/azdev-->', re.S)


def listed_government(name: str) -> str | None:
    return next((g for g, names in STATE_FORMS.items() if name in names), None)


def glyph(text: str) -> str:
    return "glyph-" + "-".join(format(ord(ch), "x") for ch in text)


def tagword(name: str) -> str:
    return re.sub(r"[^\w\s'.-]", "", name, flags=re.U).strip().lower()


class Package:
    def __init__(self, m: AzgaarMap, pg: PackGraph, world: World, cat: Catalogue, model: Model, d: Derived,
                 opts: dict):
        self.m, self.pg, self.w, self.cat, self.model, self.d, self.o = m, pg, world, cat, model, d, opts
        self.field = DevelopmentField(m, pg)
        self.log: list[str] = []

    # ------------------------------------------------------------------ development
    def biome_offsets(self) -> dict[int, int]:
        mode = self.o.get("biome_offsets", "derived")
        biomes = self.m.data["biomes"]
        current = {b["i"]: int(b.get("development", 0) or 0) for b in biomes}
        if mode == "keep":
            return current
        if mode == "zero":
            return {i: 0 for i in current}
        # derived: how much more or less elaborate a culture's communities are by the biomes they live in
        comm = self.d.community
        cult_mean = {}
        for c in {x["culture"] for x in comm}:
            mem = [x for x in comm if x["culture"] == c]
            w = np.array([x["n"] for x in mem])
            cult_mean[c] = float(np.sum(w * [x["depth"] for x in mem]) / w.sum())
        bids = sorted({b for cm in self.w.communities for b in cm.biome_share})
        X = np.array([[cm.biome_share.get(b, 0.0) for b in bids] for cm in self.w.communities])
        y = np.array([x["depth"] - cult_mean[x["culture"]] for x in comm])
        w = np.sqrt(np.array([x["n"] for x in comm]))
        lam = 6.0
        A = (X * w[:, None]).T @ (X * w[:, None]) + lam * np.eye(len(bids))
        coef = np.linalg.solve(A, (X * w[:, None]).T @ (y * w))
        out = dict(current)
        support = X.sum(0)
        for b, v, s in zip(bids, coef, support):
            if b == 0 or s < 2.0:
                continue  # marine, and biomes too rare in peopled land to say anything about
            out[b] = int(np.clip(round(v), -6, 6))
        return out

    def culture_levels(self, boff: dict[int, int]) -> tuple[dict[int, int], dict[int, float], np.ndarray]:
        """Each culture's level such that the Generator's regenerated field averages the culture's depth."""
        m, comm = self.m, self.d.community
        cultures = m.data["cultures"]
        cc = np.asarray(m.cell("culture"))
        pop = np.asarray(m.cell("pop"))
        target = {}
        for c in sorted({x["culture"] for x in comm}):
            mem = [x for x in comm if x["culture"] == c]
            w = np.array([x["n"] for x in mem])
            target[c] = float(np.sum(w * [x["depth"] for x in mem]) / w.sum())
        offs = self.field.offsets(boff)
        levels = {}
        for c, t in target.items():
            cu = cultures[c]
            cells = np.nonzero((cc == c) & self.pg.land & (pop > 0))[0]
            mo = float(np.average(offs[cells], weights=pop[cells] + 1e-3)) if len(cells) else 0.0
            levels[c] = int(np.clip(round(t - mo - CULTURE_TYPE_DEVELOPMENT.get(cu.get("type", "Generic"), 0)), 1, 100))
        # correct for smoothing across borders and the noise, twice
        for _ in range(2):
            field = self.field.generate(levels, boff)
            for c, t in target.items():
                cells = np.nonzero((cc == c) & (field > 0))[0]
                if not len(cells):
                    continue
                got = float(np.average(field[cells], weights=pop[cells] + 1e-3))
                levels[c] = int(np.clip(round(levels[c] + (t - got)), 1, 100))
        field = self.field.generate(levels, boff)
        return levels, target, field

    # ------------------------------------------------------------------ states
    def state_titles(self, field: np.ndarray) -> list[dict]:
        mode = self.o.get("retitle", "fix")
        if mode == "never":
            return []
        names = self.cat.names
        states = self.m.live("states")
        burgs = {b["i"]: b for b in self.m.live_burgs()}
        sizes = sorted(len([b for b in burgs.values() if b.get("state") == s["i"]]) for s in states if s["i"])
        big = sizes[int(len(sizes) * 0.75)] if sizes else 0
        basin_of_cell = {}
        for x in self.d.community:
            for cell in self.w.communities[x["i"]].cells:
                basin_of_cell[int(cell)] = self.d.basins[x["basin"]]["name"]
        rows = []
        for s in states:
            if not s.get("i"):
                continue
            cap = burgs.get(s.get("capital"))
            if not cap:
                continue
            dev = int(field[cap["cell"]])
            gov = s.get("form", "Monarchy")
            cur = s.get("formName", "")
            basin = basin_of_cell.get(cap["cell"], "")
            base = next((k for k in names["titles"] if basin.startswith(k)), None)
            nburgs = len([b for b in burgs.values() if b.get("state") == s["i"]])
            new, why = None, ""
            if dev < TRIBAL_DEVELOPMENT and cur not in TRIBAL:
                t = names["tribal"]
                if gov == "Monarchy":
                    new = t["NomadicMonarchy"] if s.get("type") == "Nomadic" else t["Monarchy"][min(2, nburgs // 8)]
                else:
                    new = t.get(gov)
                why = f"capital at development {dev}, before the Bronze Age"
            elif dev >= TRIBAL_DEVELOPMENT and (cur in TRIBAL or mode == "basin"):
                pick = None
                if base:
                    tb = names["titles"][base]
                    pick = tb.get("large") if (gov == "Monarchy" and nburgs >= big and "large" in tb) else tb.get(gov)
                if not pick:
                    u = names["untribal"].get(gov)
                    pick = u[min(2, nburgs // 8)] if isinstance(u, list) else u
                gov_of = listed_government(pick) if pick else None
                if pick and (gov_of is None or gov_of == gov) and pick != cur:
                    new = pick
                    why = (f"capital at development {dev} in the {basin} basin" if base else
                           f"capital at development {dev}")
            if new and new != cur:
                rows.append({"Id": s["i"], "State": s["name"], "Form": new, "old": cur, "why": why})
        return rows

    # ------------------------------------------------------------------ goods
    def new_goods(self) -> tuple[list[dict], list[str]]:
        cat, m = self.cat, self.m
        goods = m.goods
        by_name = {g["name"]: g for g in goods}
        skipped = []
        specs = [g for g in cat.new_goods if self.o.get("base_goods", True) or not g.get("base")]
        specs = sorted(specs, key=lambda g: g["tier"])
        next_id = max(g["i"] for g in goods) + 1
        made: dict[str, dict] = {}
        known = {**{n: g for n, g in by_name.items()}}

        def resolve(name: str):
            for alt in cat.aliases.get(name, [name]):
                if alt in known:
                    return known[alt]
            return None

        for spec in specs:
            existing = by_name.get(spec["name"])
            recipes = []
            for r in spec.get("recipes", []):
                ids = {}
                ok = True
                for ing, q in r.items():
                    g = resolve(ing)
                    if g is None:
                        ok = False
                        break
                    ids[str(g["i"])] = q
                if ok:
                    recipes.append(ids)
            raw = spec.get("raw")
            if not recipes and not raw:
                skipped.append(f"{spec['name']}: none of its recipes can be made from this map's goods")
                continue
            if raw:
                value = spec["value"]
            else:
                vals = []
                id_to_good = {g["i"]: g for g in list(known.values())}
                for r in recipes:
                    vals.append(sum(id_to_good[int(i)]["value"] * q for i, q in r.items()))
                value = min(120.0, round(1.15 * min(vals) + 4 + spec["tier"] / 10, 1))
            gid = existing["i"] if existing else next_id
            if not existing:
                next_id += 1
            k = cat.ki[spec["practice"]]
            p = cat.practices[k]
            note = (f"{NOTE_MARK}<p><b>{html.escape(spec['name'])}</b> is made by the practice "
                    f"<i>{html.escape(p['name'])}</i> (tier {spec['tier']}). Each culture's multiplier follows how "
                    f"fully its people carry out that practice in the azdev run: 0 where it is unknown, low where it "
                    f"is only remembered.</p></div><!--/azdev-->")
            good = {"i": gid, "name": spec["name"], "tags": spec.get("tags", []), "icon": glyph(spec["icon"]),
                    "color": spec["color"], "value": value, "unit": spec["unit"],
                    "demandCoverage": spec.get("demand", {}), "carriage": spec["carriage"],
                    "development": int(spec["tier"]),
                    "multipliers": {"cultureType": dict(spec.get("multipliers", {}).get("cultureType", {}))},
                    "note": note}
            if recipes:
                good["recipes"] = recipes
            if raw:
                good["biomeOutput"] = {str(b): v for b, v in spec.get("biomeOutput", {}).items()}
            if existing:
                keep = {k_: v for k_, v in existing.items() if k_ in ("deposits", "distribution", "depositYield",
                                                                      "clustering", "visible")}
                good.update(keep)
            made[spec["name"]] = good
            known[spec["name"]] = good
        return list(made.values()), skipped

    def multipliers(self, levels: dict[int, int], field: np.ndarray, new: list[dict]) -> dict[int, dict[str, float]]:
        """Per good, per culture: productivity follows the practices that make the good, not the scalar."""
        if not self.o.get("rebase", True):
            return {}
        cat, comm = self.cat, self.d.community
        cc = np.asarray(self.m.cell("culture"))
        pop = np.asarray(self.m.cell("pop"))
        Pm = self.d.P_med
        out: dict[int, dict[str, float]] = {}
        new_names = {g["name"] for g in new}
        all_goods = [g for g in self.m.goods if g["name"] not in new_names] + new
        cult_P, cult_base = {}, {}
        for c in levels:
            idx = [x["i"] for x in comm if x["culture"] == c]
            w = np.array([comm[i]["n"] for i in idx])
            cult_P[c] = (Pm[idx] * w[:, None]).sum(0) / w.sum()
            cells = np.nonzero((cc == c) & (field > 0))[0]
            avg = float(np.average(field[cells], weights=pop[cells] + 1e-3)) if len(cells) else levels[c]
            cult_base[c] = productivity(avg)
        mem = {}
        for c in levels:
            idx = [x["i"] for x in comm if x["culture"] == c]
            w = np.array([comm[i]["n"] for i in idx])
            mem[c] = (self.d.Mem_med[idx] * w[:, None]).sum(0) / w.sum()
        for g in all_goods:
            is_new = g["name"] in new_names
            if is_new:
                spec = next(s for s in cat.new_goods if s["name"] == g["name"])
                ks = [cat.ki[spec["practice"]]]
            else:
                ks = cat.practices_of_good(g["name"])
            if not ks:
                continue
            row = {}
            for c in levels:
                p = cult_P[c][ks]
                intensity = float(p.max())
                held = [cat.tier[k] for k, v in zip(ks, p) if v >= 0.1]
                remembered = mem[c] is not None and float(mem[c][ks].max()) > 0.3
                if is_new:
                    # a new good is made only by peoples who carry out, or remember, its practice
                    f = 1.0 if intensity >= 0.3 else 0.7 if intensity >= 0.1 else 0.25 if remembered else 0.0
                    lo_, hi_ = 0.0, 2.5
                else:
                    # the default economy stays whole: off-path goods lose the scalar's generic gain, on-path gain
                    f = 1.0 if intensity >= 0.3 else 0.85 if intensity >= 0.1 else 0.7 if remembered else 0.6
                    lo_, hi_ = 0.4, 2.0
                target = productivity(max(held) if held else 0) * (0.8 + 0.4 * min(1.0, intensity / 0.6))
                v = round(float(np.clip(target / cult_base[c] * f, lo_, hi_)), 2)
                if is_new or abs(v - 1) > 0.05:
                    row[str(c)] = v
            if row:
                out[g["i"]] = row
        return out

    # ------------------------------------------------------------------ notes
    def culture_note(self, c: int, level: int, target: float, old: int) -> str:
        d, cat = self.d, self.cat
        mem = [x for x in d.community if x["culture"] == c]
        w = np.array([x["n"] for x in mem])
        basins = {}
        for x, ww in zip(mem, w):
            basins[d.basins[x["basin"]]["name"]] = basins.get(d.basins[x["basin"]]["name"], 0) + ww
        tot = sum(basins.values())
        lines = [f"<p><b>azdev</b>: development {old} → {level} (people's average about {target:.0f}; "
                 f"the scale reads as depth of elaboration along this people's own paths, not as rank).</p>"]
        lines.append("<p>Basins: " + ", ".join(f"{html.escape(k)} {v / tot:.0%}" for k, v in
                                               sorted(basins.items(), key=lambda kv: -kv[1])) + "</p>")
        top = max(mem, key=lambda x: x["n"])
        P = lambda ids: ", ".join(cat.practices[cat.ki[k]]["name"].lower() for k in ids)
        S = lambda ids: ", ".join(cat.stocks[h]["name"].lower() for h in ids)
        lines.append(f"<p>Practices held: {P(top['held'][:6])}.</p>")
        if top["attends"]:
            lines.append(f"<p>Attends to: {S([h for h in top['attends'] if h in cat.stocks][:6])}.</p>")
        if top["shadow"]:
            lines.append(f"<p>Shadow (unwatched and declining): {S(top['shadow'])}.</p>")
        if top["dormant"]:
            lines.append(f"<p>Remembered, not practised (dormant pathways): {P(top['dormant'])}.</p>")
        cin, cout = top["capture_in"], top["capture_out"]
        if cin or cout:
            lines.append(f"<p>Capture: suffers {', '.join(cin) or 'little'}; exercises {', '.join(cout) or 'little'}.</p>")
        sp = top["depth_hi"] - top["depth_lo"]
        lines.append(f"<p>Across the ensemble this people's depth ranges {top['depth_lo']:.0f}–{top['depth_hi']:.0f}"
                     f"{' (theory-dependent)' if sp > 15 else ''}; its home basin holds in "
                     f"{top['basin_share']:.0%} of runs.</p>")
        return NOTE_MARK + "".join(lines) + "</div><!--/azdev-->"

    @staticmethod
    def merge_note(existing: str | None, ours: str) -> str:
        base = NOTE_RE.sub("", existing or "").strip()
        return (base + ours) if base else ours

    # ------------------------------------------------------------------ write
    def write(self, outdir: Path) -> dict:
        m, cat, d = self.m, self.cat, self.d
        outdir.mkdir(parents=True, exist_ok=True)
        world = m.name
        boff = self.biome_offsets()
        levels, target, field = self.culture_levels(boff)
        cultures = m.data["cultures"]
        old_field = np.asarray(m.cell("development"))

        # 2: biomes
        biomes_rows = []
        for b in m.data["biomes"]:
            if b.get("removed"):
                continue
            new = boff.get(b["i"], int(b.get("development", 0) or 0))
            biomes_rows.append({"Id": b["i"], "Biome": b["name"], "Development": new,
                                "old": int(b.get("development", 0) or 0)})
        # 3: cultures
        cult_rows = []
        for c, lv in sorted(levels.items()):
            cu = cultures[c]
            mem = [x for x in d.community if x["culture"] == c]
            w = np.array([x["n"] for x in mem])
            share = {}
            for x, ww in zip(mem, w):
                share[x["basin"]] = share.get(x["basin"], 0) + ww
            main = max(share, key=share.get)
            tags = [t for t in (cu.get("tags") or []) if not t.startswith("azdev")]
            tags += ["azdev", tagword(f"azdev {d.basins[main]['name']}")]
            cult_rows.append({"Id": c, "Name": cu["name"], "Development": lv, "Tags": "; ".join(tags),
                              "old": int(cu.get("development", DEFAULT_DEVELOPMENT)), "target": target[c],
                              "basin": d.basins[main]["name"]})
        # 4: states
        state_rows = self.state_titles(field)
        # goods and settings
        new, skipped = self.new_goods()
        mult = self.multipliers(levels, field, new)
        settings = json.loads(compact_json(m.settings))
        goods = settings["goods"]
        names_new = {g["name"] for g in new}
        goods = [g for g in goods if g["name"] not in names_new] + new
        for g in goods:
            if g["i"] in mult:
                g.setdefault("multipliers", {})
                cur = g["multipliers"].get("culture", {}) or {}
                merged = {k: v for k, v in cur.items()}
                for k, v in mult[g["i"]].items():
                    merged[k] = round(float(merged.get(k, 1)) * v, 2) if k in cur and g["name"] not in names_new else v
                g["multipliers"]["culture"] = merged
        settings["goods"] = goods
        era_names = cat.names["eras"]
        if self.o.get("eras", True):
            for era in settings.get("eras", []):
                if str(era["level"]) in era_names:
                    era["name"] = era_names[str(era["level"])]
        # notes
        note_rows = []
        for r in cult_rows:
            note = self.culture_note(r["Id"], r["Development"], r["target"], r["old"])
            note_rows.append(["culture", str(r["Id"]), self.merge_note(cultures[r["Id"]].get("note"), note)])
        states = m.data["states"]
        for r in state_rows:
            note = f'{NOTE_MARK}<p><b>azdev</b>: retitled {html.escape(r["old"] or "—")} → {html.escape(r["Form"])}, ' \
                   f'{html.escape(r["why"])}.</p></div><!--/azdev-->'
            note_rows.append(["state", str(r["Id"]), self.merge_note(states[r["Id"]].get("note"), note)])

        files = {}

        def write_csv(name, header, rows):
            path = outdir / name
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                wr = csv.writer(fh)
                wr.writerow(header)
                for row in rows:
                    wr.writerow(row)
            files[name] = path

        mapname = f"1 {world} azdev.map"
        m.write_patched(outdir / mapname, {1: compact_json(settings)})
        files[mapname] = outdir / mapname
        changed_biomes = [r for r in biomes_rows if r["Development"] != r["old"]]
        if changed_biomes:
            write_csv(f"2 {world} Biomes.csv", ["Id", "Biome", "Development"],
                      [[r["Id"], r["Biome"], r["Development"]] for r in changed_biomes])
        write_csv(f"3 {world} Cultures.csv", ["Id", "Name", "Development", "Tags"],
                  [[r["Id"], r["Name"], r["Development"], r["Tags"]] for r in cult_rows])
        if state_rows:
            write_csv(f"5 {world} States.csv", ["Id", "State", "Form"],
                      [[r["Id"], r["State"], r["Form"]] for r in state_rows])
        write_csv(f"6 {world} Notes.csv", ["type", "id", "note"], note_rows)

        # predicted eras after regeneration
        eras = settings.get("eras", [])
        def era_of(level):
            name = eras[0]["name"] if eras else ""
            for e in eras:
                if level >= e["level"]:
                    name = e["name"]
            return name
        pop = np.asarray(m.cell("pop"))
        pred = {}
        for lv in field[field > 0]:
            pred[era_of(int(lv))] = pred.get(era_of(int(lv)), 0) + 1
        now = {}
        for lv in old_field[old_field > 0]:
            now[era_of(int(lv))] = now.get(era_of(int(lv)), 0) + 1
        return {"files": files, "biomes": biomes_rows, "cultures": cult_rows, "states": state_rows, "new_goods": new,
                "skipped_goods": skipped, "multipliers": mult, "field": field, "old_field": old_field,
                "eras_pred": pred, "eras_now": now, "eras": eras, "biome_offsets": boff, "levels": levels}
