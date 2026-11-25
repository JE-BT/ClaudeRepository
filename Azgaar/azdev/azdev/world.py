"""Read a world into communities: who lives where, on what land, how far from whom.

Communities are culture x province (culture x state where there is no province). Each has
affordances on 0-1 read from its cells (spec 'Affordances'), a population, a centroid, the burg
features and present development, and least-cost distances to every other community over land
and over land and sea (spec 'Space and friction').
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from .catalogue import AFFORDANCES, Catalogue
from .graph import PackGraph
from .mapfile import AzgaarMap

# default biome ids 0-12 (Azgaar). Columns: arable, pasture, forest, game, soil, perennial
BIOME_TABLE = {
    0: (0, 0, 0, 0, 0, 0),          # marine
    1: (0.05, 0.3, 0, 0.1, 0.15, 0.3),   # hot desert (oases)
    2: (0.1, 0.5, 0, 0.2, 0.2, 0),       # cold desert
    3: (0.5, 0.8, 0.15, 0.8, 0.6, 0.5),  # savanna
    4: (1.0, 1.0, 0.05, 0.5, 1.0, 0.4),  # grassland
    5: (0.6, 0.3, 0.8, 0.7, 0.6, 0.5),   # tropical seasonal forest
    6: (0.8, 0.3, 1.0, 0.8, 0.9, 0.6),   # temperate deciduous forest
    7: (0.3, 0.1, 1.0, 0.8, 0.4, 0.4),   # tropical rainforest
    8: (0.5, 0.2, 1.0, 0.8, 0.7, 0.2),   # temperate rainforest
    9: (0.2, 0.3, 1.0, 1.0, 0.35, 0),    # taiga
    10: (0, 0.5, 0, 0.8, 0.1, 0),        # tundra
    11: (0, 0, 0, 0.1, 0, 0),            # glacier
    12: (0.3, 0.4, 0.3, 0.6, 0.7, 0.1),  # wetland
}
BY_NAME = {"desert": 1, "steppe": 4, "savanna": 3, "grass": 4, "jungle": 7, "rainforest": 7, "forest": 6,
           "taiga": 9, "tundra": 10, "ice": 11, "glacier": 11, "swamp": 12, "marsh": 12, "wetland": 12,
           "mangrove": 12}
METALS = {"Iron", "Copper", "Tin", "Silver", "Gold", "Gemstones"}
FUELS = {"Coal", "Oil"}
STONES = {"Stone", "Marble"}
CLAYS = {"Clay", "White sand"}
SALTS = {"Salt"}
TREES = {"Wine", "Olives", "Dates"}


def biome_row(b: dict) -> tuple:
    if b["i"] in BIOME_TABLE and b["i"] <= 12:
        return BIOME_TABLE[b["i"]]
    name = b.get("name", "").lower()
    for key, i in BY_NAME.items():
        if key in name:
            return BIOME_TABLE[i]
    h = min(1.0, (b.get("habitability") or 0) / 100)
    return (0.6 * h, 0.5 * h, 0.4 * h, 0.5 * h, 0.7 * h, 0.2 * h)


@dataclass
class Community:
    i: int
    culture: int
    province: int
    state: int
    cells: np.ndarray
    rural: float
    urban: float
    centroid: int
    dev_now: float
    aff: np.ndarray
    burgs: list[int] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    religion_type: str = ""
    biome_share: dict = field(default_factory=dict)

    @property
    def n(self) -> float:
        return self.rural + self.urban


class World:
    def __init__(self, m: AzgaarMap, pg: PackGraph, cat: Catalogue, min_share: float = 0.004):
        self.m, self.pg, self.cat = m, pg, cat
        n = pg.n
        cells = {k: np.asarray(m.cell(k)) for k in ("biome", "culture", "province", "state", "pop", "burg", "river",
                                                    "religion", "good", "fl", "development")}
        self.cells = cells
        self.temp = np.asarray(m.cell("grid_temp"))[pg.g]
        self.prec = np.asarray(m.cell("grid_prec"))[pg.g]
        self.h = pg.h.astype(float)
        biomes = m.data["biomes"]
        self.btab = np.array([biome_row(b) for b in biomes], float)
        goods = {g["i"]: g["name"] for g in m.goods}
        self.deposit = np.array([goods.get(int(x), "") for x in cells["good"]], dtype=object)
        burgs = {b["i"]: b for b in m.live_burgs()}
        rate = m.settings.get("units", {}).get("population", {}).get("urbanization", {}).get("rate", 1) or 1

        # land components (islands) for insularity
        rows, cols = pg.edges
        land = pg.land
        keep = land[rows] & land[cols]
        adj = coo_matrix((np.ones(keep.sum()), (rows[keep], cols[keep])), shape=(n, n))
        ncomp, comp = connected_components(adj, directed=False)
        comp_size = np.bincount(comp[land], minlength=ncomp)
        total_land = land.sum()

        # roughness: height difference to neighbours
        rough = np.zeros(n)
        for i in np.nonzero(land)[0]:
            nb = pg.c[i]
            rough[i] = np.abs(self.h[nb] - self.h[i]).mean() if len(nb) else 0
        ecotone = np.zeros(n)
        for i in np.nonzero(land)[0]:
            nb = pg.c[i]
            ecotone[i] = float(np.any(cells["biome"][nb] != cells["biome"][i]))
        lake_near = np.zeros(n)
        water = ~land
        for i in np.nonzero(land & (pg.harbor > 0))[0]:
            lake_near[i] = 1.0

        # group cells
        peopled = land & ((cells["pop"] > 0) | (cells["burg"] > 0)) & (cells["culture"] > 0)
        groups: dict[tuple, list[int]] = defaultdict(list)
        for i in np.nonzero(peopled)[0]:
            prov = int(cells["province"][i])
            key = (int(cells["culture"][i]), prov if prov else -int(cells["state"][i]))
            groups[key].append(i)
        total_pop = cells["pop"][peopled].sum() + sum(b.get("population", 0) * rate for b in burgs.values())
        # merge small groups into the nearest group of the same culture
        def pop_of(idx):
            idx = np.asarray(idx)
            return cells["pop"][idx].sum() + sum(burgs[b].get("population", 0) * rate
                                                  for b in cells["burg"][idx] if b in burgs)
        keys = sorted(groups, key=lambda k: -pop_of(groups[k]))
        big = [k for k in keys if pop_of(groups[k]) >= min_share * total_pop]
        small = [k for k in keys if k not in set(big)]
        cent = {k: pg.p[np.asarray(groups[k])].mean(0) for k in keys}
        for k in small:
            same = [b for b in big if b[0] == k[0]] or big
            if not same:
                big.append(k)
                continue
            d = [np.sum((cent[b] - cent[k]) ** 2) for b in same]
            groups[same[int(np.argmin(d))]].extend(groups[k])
            del groups[k]
        self.communities: list[Community] = []
        for idx_key in big:
            idx = np.asarray(sorted(groups[idx_key]))
            self.communities.append(self._community(len(self.communities), idx_key, idx, burgs, rate, rough, ecotone,
                                                    lake_near, comp, comp_size, total_land))
        self.N = len(self.communities)
        self.cell_comm = np.full(n, -1, dtype=int)
        for c in self.communities:
            self.cell_comm[c.cells] = c.i
        self._distances(burgs)
        self._free_land()

    # ------------------------------------------------------------------ one community
    def _community(self, i, key, idx, burgs, rate, rough, ecotone, lake_near, comp, comp_size, total_land):
        cells, m = self.cells, self.m
        pop = cells["pop"][idx].astype(float)
        w = pop + 0.05
        w = w / w.sum()
        b = cells["biome"][idx]
        bt = self.btab[np.minimum(b, len(self.btab) - 1)]
        moist = 0.6 + 0.4 * np.clip(self.prec[idx] / 20.0, 0, 1)  # the biome already reflects moisture
        flat = np.clip(1.2 - (self.h[idx] - 20) / 50.0, 0.1, 1.0)
        river = (cells["river"][idx] > 0).astype(float)
        harbor = (self.pg.harbor[idx] > 0).astype(float)
        temp = self.temp[idx].astype(float)
        dep = self.deposit[idx]
        ndep = lambda names: float(sum(1 for x in dep if x in names))
        share = lambda arr: float(np.sum(w * arr))
        area = len(idx)
        warm = share(np.clip((temp - 2) / 22.0, 0, 1))
        cold = share(np.clip((12 - temp) / 22.0, 0, 1))
        coast = min(1.0, 2.0 * share(harbor))
        wet = share((b == 12).astype(float))
        a = dict.fromkeys(AFFORDANCES, 0.0)
        a["arable"] = share(bt[:, 0] * flat * moist)
        a["pasture"] = share(bt[:, 1])
        a["forest"] = share(bt[:, 2])
        a["game"] = share(bt[:, 3])
        a["soil"] = share(bt[:, 4] * (0.5 + 0.5 * moist))
        a["perennial"] = min(1.0, share(bt[:, 5] * np.clip((temp - 8) / 12.0, 0, 1)) + 0.3 * ndep(TREES) / area * 10)
        a["alluvial"] = min(1.0, 1.6 * share(river * flat))
        a["wetland"] = wet
        a["coast"] = coast
        main_comp = np.bincount(comp[idx]).argmax()
        insular = 1 - min(1.0, comp_size[main_comp] / max(1, total_land) * 3)
        a["island"] = min(1.0, coast * (0.3 + insular))
        a["fishery"] = min(1.0, coast + 0.6 * share(river) + 0.4 * wet)
        a["ore"] = min(1.0, 0.35 * ndep(METALS) + 0.8 * share((self.h[idx] >= 50).astype(float)))
        a["fuelmin"] = min(1.0, 0.45 * ndep(FUELS))
        a["quarry"] = min(1.0, 0.25 * ndep(STONES) + share((self.h[idx] >= 40).astype(float)))
        a["clay"] = min(1.0, 0.3 * ndep(CLAYS) + 0.8 * share(river) + 0.5 * wet + 0.1)
        a["warm"] = warm
        a["cold"] = cold
        a["rough"] = min(1.0, share(rough[idx]) / 8.0)
        a["seasonal"] = min(1.0, 0.35 * share(ecotone[idx]) + 0.5 * share(river) + 0.6 * wet + 0.25 * coast)
        a["saltsrc"] = min(1.0, 0.5 * coast + 0.5 * ndep(SALTS) + 0.4 * share(((b == 1) | (b == 2)).astype(float)))
        aff = np.array([a[x] for x in AFFORDANCES])
        bidx = [int(x) for x in cells["burg"][idx] if x and int(x) in self._live_burgs(burgs)]
        urban = sum(burgs[x].get("population", 0) * rate for x in bidx)
        feats = {k: (sum(1 for x in bidx if burgs[x].get(k)) / len(bidx) if bidx else 0.0)
                 for k in ("temple", "walls", "citadel", "plaza", "port", "shanty")}
        feats["capital"] = sum(1 for x in bidx if burgs[x].get("capital"))
        dev = cells["development"][idx].astype(float)
        dev_now = float(np.sum(w * dev)) if dev.size else 0.0
        rel = np.bincount(cells["religion"][idx]).argmax()
        religions = self.m.data["religions"]
        rtype = religions[rel].get("type", "") if rel < len(religions) and isinstance(religions[rel], dict) else ""
        cent_pt = self.pg.p[idx].T @ w
        centroid = int(idx[np.argmin(np.sum((self.pg.p[idx] - cent_pt) ** 2, 1))])
        bs = defaultdict(float)
        for bb, ww in zip(b, w):
            bs[int(bb)] += float(ww)
        state = int(np.bincount(cells["state"][idx]).argmax())
        return Community(i=i, culture=key[0], province=key[1], state=state, cells=idx, rural=float(pop.sum()),
                         urban=float(urban), centroid=centroid, dev_now=dev_now, aff=aff, burgs=bidx, features=feats,
                         religion_type=rtype or "", biome_share=dict(bs))

    @staticmethod
    def _live_burgs(burgs):
        return burgs

    # ------------------------------------------------------------------ distances
    def _distances(self, burgs) -> None:
        pg, m = self.pg, self.m
        n = pg.n
        biomes = m.data["biomes"]
        bcost = np.array([b.get("cost", 50) or 50 for b in biomes], float)
        cb = np.minimum(self.cells["biome"], len(bcost) - 1)
        cost = bcost[cb] / 50.0
        road = np.zeros(n)
        for r in m.live("routes"):
            factor = 0.35 if r.get("group") == "roads" else 0.6 if r.get("group") == "trails" else 1.0
            for pt in r.get("points", []):
                c = int(pt[2])
                if c < n and pg.land[c]:
                    road[c] = factor if road[c] == 0 else min(road[c], factor)
        cost = np.where(road > 0, cost * road, cost)
        cost = np.where(self.cells["river"] > 0, cost * 0.8, cost)
        rows, cols = pg.edges
        dist = np.sqrt(np.sum((pg.p[rows] - pg.p[cols]) ** 2, 1))
        dh = np.abs(self.h[rows] - self.h[cols])
        land_r, land_c = pg.land[rows], pg.land[cols]
        both_land = land_r & land_c
        w_land = dist * (cost[rows] + cost[cols]) / 2 * (1 + dh / 15.0)
        # land only
        A = coo_matrix((w_land[both_land], (rows[both_land], cols[both_land])), shape=(n, n)).tocsr()
        src = np.array([c.centroid for c in self.communities])
        dl = dijkstra(A, directed=True, indices=src)
        # land and sea: water is fast, getting on and off a boat costs
        sea = np.where(both_land, w_land, np.where(~land_r & ~land_c, dist * 0.25, dist * 0.25 + 30.0))
        B = coo_matrix((sea, (rows, cols)), shape=(n, n)).tocsr()
        ds = dijkstra(B, directed=True, indices=src)
        tgt = src
        self.d_land = dl[:, tgt]
        self.d_sea = ds[:, tgt]
        finite = np.isfinite(self.d_land)
        big = np.nanmax(np.where(np.isfinite(self.d_sea), self.d_sea, np.nan)) * 3 + 1
        self.d_land = np.where(finite, self.d_land, big)
        self.d_sea = np.where(np.isfinite(self.d_sea), self.d_sea, big)
        np.fill_diagonal(self.d_land, 0)
        np.fill_diagonal(self.d_sea, 0)
        off = self.d_sea + np.eye(self.N) * 1e12
        self.scale = float(np.median(off.min(1)))  # typical distance to the nearest neighbour
        self._dl_cells, self._ds_cells = dl, ds

    def _free_land(self) -> None:
        """Habitable land nobody lives on, as patches: where a community could walk away to (exit)."""
        pg, cells = self.pg, self.cells
        hab = np.array([(b.get("habitability") or 0) > 0 for b in self.m.data["biomes"]])
        free = pg.land & hab[np.minimum(cells["biome"], len(hab) - 1)] & (
            ((cells["pop"] <= 0) & (cells["burg"] == 0)) | (cells["culture"] == 0))
        idx = np.nonzero(free)[0]
        self.free_cells = idx
        if not len(idx):
            self.free_access = np.zeros((self.N, 1))
            self.free_size = np.zeros(1)
            return
        # distance from each community to each free cell, by land or sea
        d = np.minimum(self._dl_cells[:, idx], self._ds_cells[:, idx] * 1.5)
        d = np.where(np.isfinite(d), d, 1e9)
        # compatibility: share of the community's biomes in the free cell's biome
        fb = cells["biome"][idx]
        compat = np.array([[c.biome_share.get(int(x), 0.0) for x in fb] for c in self.communities])
        self.free_dist = d
        self.free_compat = 0.3 + 0.7 * np.clip(compat * 3, 0, 1)
        self.free_size = np.ones(len(idx))

    # ------------------------------------------------------------------ helpers
    def arrays(self):
        n = np.array([c.n for c in self.communities])
        aff = np.array([c.aff for c in self.communities])
        dev = np.array([c.dev_now for c in self.communities])
        cult = np.array([c.culture for c in self.communities])
        urban = np.array([c.urban / max(c.n, 1e-9) for c in self.communities])
        return n, aff, dev, cult, urban
