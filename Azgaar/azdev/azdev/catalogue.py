"""The catalogue: stocks, practices, new goods, scenarios, basin names. Loaded from azdev/data/*.json
(or a folder given with --catalogue), checked, and turned into arrays for the dynamics."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data"

AFFORDANCES = ["arable", "alluvial", "pasture", "forest", "wetland", "coast", "island", "fishery", "game", "ore",
               "fuelmin", "quarry", "clay", "warm", "cold", "rough", "seasonal", "perennial", "saltsrc", "soil"]
LAND = ["soil", "forest", "pasture", "fishery", "game"]  # affordances that practices build up or run down
KINDS = ["arms", "org", "ritual", "credit", "ships", "allies"]
GROUPS = ["food", "warmth", "shelter", "cloth"]
ELABORATION = 40.0  # yields x (1 + tier / ELABORATION)


class CatalogueError(ValueError):
    pass


@dataclass
class Catalogue:
    folder: Path
    stocks: dict
    needs: dict
    decay_base: float
    practices: list[dict]
    new_goods: list[dict]
    aliases: dict[str, list[str]]
    scenarios: dict
    basins: list[dict]
    names: dict
    warnings: list[str] = field(default_factory=list)

    # arrays, filled by build()
    def build(self) -> "Catalogue":
        self.H = list(self.stocks)
        self.hi = {h: i for i, h in enumerate(self.H)}
        self.derived = np.array([bool(self.stocks[h].get("derived")) for h in self.H])
        self.pi = np.array([self.stocks[h].get("pi", [0, 0, 0, 0, 0, 0]) for h in self.H], float)
        self.group = [self.stocks[h].get("group") for h in self.H]
        self.K = [p["id"] for p in self.practices]
        self.ki = {k: i for i, k in enumerate(self.K)}
        if len(self.ki) != len(self.K):
            raise CatalogueError("practice ids are not unique")
        nk, nh, na, nl = len(self.K), len(self.H), len(AFFORDANCES), len(LAND)
        ai = {a: i for i, a in enumerate(AFFORDANCES)}
        li = {a: i for i, a in enumerate(LAND)}
        self.ai, self.li = ai, li
        self.tier = np.zeros(nk); self.lab = np.zeros(nk)
        self.Y = np.zeros((nk, nh)); self.U = np.zeros((nk, nh))
        self.yaff = np.zeros((nk, na)); self.req_aff = np.zeros((nk, na)); self.req_stock = np.zeros((nk, nh))
        self.build_ = np.zeros((nk, nl)); self.degrade = np.zeros((nk, nl)); self.land = np.zeros((nk, na))
        self.mem = np.zeros(nk); self.com = np.zeros(nk); self.mob = np.zeros(nk)
        self.w = np.zeros((nk, len(KINDS)))
        self.req_prac: list[list[tuple[np.ndarray, np.ndarray]]] = []
        self.surplus = np.zeros(nk)
        self.hints: list[set[str]] = []
        self.goods_of: list[list[str]] = []

        def check(name, table, where):
            if name not in table:
                raise CatalogueError(f"{where}: unknown '{name}'")
            return table[name]

        for k, p in enumerate(self.practices):
            where = f"practice {p['id']}"
            self.tier[k] = p["tier"]; self.lab[k] = p.get("lab", 0.05)
            for h, v in p.get("yield", {}).items(): self.Y[k, check(h, self.hi, where)] = v
            for h, v in p.get("use", {}).items(): self.U[k, check(h, self.hi, where)] = v
            for a, v in p.get("yaff", {}).items(): self.yaff[k, check(a, ai, where)] = v
            req = p.get("req", {})
            for a, v in req.get("aff", {}).items(): self.req_aff[k, check(a, ai, where)] = v
            for h, v in req.get("stock", {}).items(): self.req_stock[k, check(h, self.hi, where)] = v
            self.surplus[k] = req.get("surplus", 0)
            for a, v in p.get("build", {}).items(): self.build_[k, check(a, li, where)] = v
            for a, v in p.get("degrade", {}).items(): self.degrade[k, check(a, li, where)] = v
            for a, v in p.get("land", {}).items(): self.land[k, check(a, ai, where)] = v
            self.mem[k] = p.get("mem", 0); self.com[k] = p.get("com", 0); self.mob[k] = p.get("mob", 0)
            for kind, v in p.get("w", {}).items(): self.w[k, KINDS.index(check(kind, {x: x for x in KINDS}, where))] = v
            self.hints.append(set(p.get("hint", "").split()))
            self.goods_of.append(list(p.get("goods", [])))
        ys = np.array([self.stocks[h].get("yield_scale", 1.0) for h in self.H])
        self.Y *= ys[None, :]
        # elaboration pays: a deeper practice yields more of what it makes (as Azgaar's productivity, but per path)
        self.Y *= (1 + self.tier / ELABORATION)[:, None]
        self.U *= ys[None, :]
        for k, p in enumerate(self.practices):
            groups = []
            for group in p.get("req", {}).get("prac", []):
                idx = np.array([check(a, self.ki, f"practice {p['id']} requirement") for a, _ in group], int)
                mins = np.array([m for _, m in group], float)
                groups.append((idx, mins))
                lowest = min(self.tier[i] for i in idx)
                if lowest > self.tier[k]:
                    self.warnings.append(f"{p['id']} (tier {self.tier[k]:g}) requires practices of tier {lowest:g} or more")
            self.req_prac.append(groups)
        # adoption cost: deeper practices cost more to start, steeply (spec range 0.1-0.8, here to 0.9)
        self.cost = 0.1 + 0.6 * (self.tier / 100.0) ** 1.2
        self.coord = np.array([bool(self.hints[k] & {"commons", "ceremonial"}) or self.K[k] in
                               ("assembly", "league", "aggregation", "lineage") for k in range(nk)])
        self.intensive = np.array([self.K[k] in ("plough", "irrigation", "terracing", "darkearth", "hydraulics",
                                                  "agroforestry", "biochar", "seafarming", "chemicals")
                                   for k in range(nk)])
        # mechanical coupling: l produces what k needs or uses; k and l compete for land and labour
        need = self.U + self.req_stock
        out = np.where(self.derived[None, :], 0, self.Y)
        J = (need / (need.sum(1, keepdims=True) + 1e-9)) @ (out / (out.sum(1, keepdims=True) + 1e-9)).T
        J = 0.15 * J  # prerequisites act through feasibility only, not as support
        compete = self.land @ self.land.T
        np.fill_diagonal(compete, 0)
        J -= 0.6 * compete
        np.fill_diagonal(J, 0)
        self.J_mech = J
        return self

    # ------------------------------------------------------------------ goods names
    def canonical(self, map_names: set[str]) -> dict[str, str | None]:
        """canonical good name -> the name the map uses (or None)."""
        out = {}
        names = set()
        for gl in self.goods_of:
            names.update(gl)
        for g in self.new_goods:
            for r in g.get("recipes", []):
                names.update(r)
        for c in names:
            alts = self.aliases.get(c, [c])
            out[c] = next((a for a in alts if a in map_names), None)
        return out

    def practices_of_good(self, map_name: str) -> list[int]:
        canon = {map_name}
        for c, alts in self.aliases.items():
            if map_name in alts:
                canon.add(c)
        return [k for k, gl in enumerate(self.goods_of) if canon & set(gl)]


def _load(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        path = DATA / name
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load(folder: str | Path | None = None) -> Catalogue:
    folder = Path(folder) if folder else DATA
    st = _load(folder, "stocks.json")
    pr = _load(folder, "practices.json")
    gn = _load(folder, "goods_new.json")
    sc = _load(folder, "scenarios.json")
    bs = _load(folder, "basins.json")
    nm = _load(folder, "names.json")
    cat = Catalogue(folder=folder, stocks=st["stocks"], needs=st["needs"], decay_base=st["decay"]["base"],
                    practices=pr["practices"], new_goods=gn["goods"], aliases=gn.get("aliases", {}),
                    scenarios=sc, basins=bs["basins"], names=nm)
    cat.build()
    known = set(cat.K)
    for g in cat.new_goods:
        if g["practice"] not in known:
            raise CatalogueError(f"new good {g['name']}: unknown practice {g['practice']}")
        tier = cat.tier[cat.ki[g["practice"]]]
        if tier != g["tier"]:
            cat.warnings.append(f"new good {g['name']} has tier {g['tier']} but its practice has {tier:g}")
    return cat
