"""The dynamics of 'Development without a ladder' v0.1, run over a world's communities.

One step is a few years. Every term of the spec's equations is here, each marked by its name:
  practices  dp = p(1-p) g [J p + a.B - c(1-m)] + g sum_j kappa (p_j - p) + g (nu0 + nu_m m)(1-p) + noise
  stocks     ds = production - inputs - decay - consumption + trade + capture in - capture out
  land       de = r (e_bar - e) - practices that run it down + practices that build it up
  population dn = r_n n (1 - stress) - captives taken
  attention  da = eta (phi - a) + theta [z - z*]+ (1 - a),   z* = z0 + z1 (1 - a), within a budget
  memory     dm = mu [p - m]+ - delta0 / (1 + psi sum_mem p) m + what is heard from neighbours
  capture    C(i<-j,h) = chi sigma_h lambda_h s_jh exp(-d_ij / r_i) [M_i - M_j]+/(M_i + M_j) (1 - X_j)
Simplifications are listed in README 'What the model leaves out'.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .catalogue import AFFORDANCES, GROUPS, KINDS, LAND, Catalogue
from .world import World

GAMMA = 8.0          # smooth minimum for feasibility (Liebig)
LAND_RATE = 0.25     # the catalogue's build and degrade rates per step, scaled against recovery r = 0.02
UPKEEP = (0.02, 0.12)  # every practice must keep earning: base + per tier/100, paid whatever is remembered
TAINTER = 0.08       # overhead of complexity: food per person = TAINTER * (sum p * tier/100) ** 1.5 (Tainter 1988)
WANTS = 2.0          # an attended stock's target rises to (1 + WANTS * attention) times its norm
REACH_MEMORY = 0.25  # benefit per unit of a practice's mobility, communication and memory weights (before beta)
BUDGET = 7.0         # attention budget A-bar, out of ~26 stocks
DT = 1.0
S_MAX = 8.0


@dataclass
class Params:
    scenario: dict
    nu0: float; nu_m: float; kappa0: float; mu: float; delta0: float; eta: float; theta: float
    z0: float; z1: float; sigma: float; trade: float; J_scale: float
    seed: int


def draw_params(cat: Catalogue, scenario_id: str, rng: np.random.Generator, seed: int,
                fixed_attention: bool = False) -> Params:
    base = dict(cat.scenarios["base"])
    sc = next(s for s in cat.scenarios["scenarios"] if s["id"] == scenario_id)
    merged = {**base, **{k: v for k, v in sc.items() if k not in ("w",)}}
    merged["w"] = {**base["w"], **sc.get("w", {})}
    merged["J"] = base.get("J", []) + sc.get("J", [])
    merged["fixed_attention"] = fixed_attention
    vals = {}
    for key, spec in cat.scenarios["ranges"].items():
        lo, hi = spec[0], spec[1]
        if len(spec) > 2 and spec[2] == "log":
            vals[key] = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
        else:
            vals[key] = float(rng.uniform(lo, hi))
    return Params(scenario=merged, seed=seed, **vals)


@dataclass
class RunResult:
    scenario: str
    seed: int
    P: np.ndarray          # final practice intensities N x K
    Mem: np.ndarray        # final memory
    A: np.ndarray          # final attention N x H
    S: np.ndarray          # final stocks N x H
    n: np.ndarray          # final population
    E: np.ndarray          # final dynamic land N x L
    D: np.ndarray          # final depth (scalar projection) N
    traj: np.ndarray       # sampled P, T x N x K
    Strj: np.ndarray       # sampled S, T x N x H
    Dtraj: np.ndarray      # sampled depth T x N
    Mcap: np.ndarray       # mobilisable capacity N
    cap_out: np.ndarray    # capture exercised, by form: N x forms
    cap_in: np.ndarray     # capture suffered, by form
    exit: np.ndarray       # exit X
    reach: np.ndarray


FORMS = ["tribute", "raiding", "debt", "ritual monopoly", "household", "displacement"]


class Model:
    def __init__(self, world: World, cat: Catalogue, start: str = "present", shuffle_geography: bool = False,
                 rng_seed: int = 0):
        self.w, self.c = world, cat
        n, aff, dev, cult, urban = world.arrays()
        if shuffle_geography:
            # failure check F5: each affordance is dealt out to communities at random, so what goes together on
            # the map (coast with fishery, steppe with pasture) no longer does
            rng = np.random.default_rng(rng_seed + 999)
            aff = aff.copy()
            for j in range(aff.shape[1]):
                aff[:, j] = aff[rng.permutation(len(aff)), j]
        self.n0, self.aff0, self.dev0, self.cult, self.urban = n, aff, dev, cult, urban
        self.start = start
        self.debug = None
        self.N, self.K, self.H = world.N, len(cat.K), len(cat.H)
        c = cat
        self.land_cols = np.array([c.ai[a] for a in LAND])
        self.food = np.array([g == "food" for g in c.group])
        self.nonderived = ~c.derived
        self.hidx = c.hi
        # one unit of benefit = meeting a need: food against 1 per person, other stocks against their small norms
        self.scale_h = np.full(self.H, 0.08)
        self.scale_h[[g in ("warmth", "shelter", "cloth") for g in cat.group]] = 0.25
        self.scale_h[self.food] = 1.0
        sig, lam = c.pi[:, 0], c.pi[:, 2]
        self.approp = sig * lam
        self.approp[c.derived] = 0
        wear = np.array([c.stocks[h].get("wear", 0.0) for h in c.H])
        self.decay = np.maximum(c.decay_base * (1 - sig), wear)
        self.decay[c.derived] = 0
        self.beta = np.clip(c.pi[:, 1], 0.05, 1)
        # requirement structures for feasibility
        self.req_aff_mask = c.req_aff > 0
        self.req_stock_mask = c.req_stock > 0
        alt_l, alt_min, group_of_alt, group_k = [], [], [], []
        gid = 0
        for k, groups in enumerate(c.req_prac):
            for idx, mins in groups:
                alt_l.extend(idx.tolist()); alt_min.extend(mins.tolist())
                group_of_alt.extend([gid] * len(idx)); group_k.append(k); gid += 1
        self.alt_l = np.array(alt_l, int); self.alt_min = np.array(alt_min, float)
        self.alt_start = np.r_[0, np.nonzero(np.diff(np.array(group_of_alt)))[0] + 1] if gid else np.array([], int)
        self.group_k = np.array(group_k, int)
        self.nogroups = np.bincount(self.group_k, minlength=self.K) == 0 if len(group_k) else np.ones(self.K, bool)
        self.nterms = self.req_aff_mask.sum(1) + self.req_stock_mask.sum(1) + np.bincount(self.group_k, minlength=self.K) \
            + (cat.surplus > 0)
        # special practices
        k = c.ki
        self.k_storage, self.k_office, self.k_reg = k["storage"], k["office"], k["registers"]
        self.k_markets, self.k_exchange, self.k_raid, self.k_bond = k["markets"], k["exchange"], k["raiding"], k["bondage"]
        self.k_bank, self.k_priest = k["banking"], k["priesthood"]
        self.maritime = np.array(["maritime" in h for h in c.hints], float)
        self.landmob = np.array([("maritime" not in h) for h in c.hints], float) * c.mob
        self.seamob = self.maritime * c.mob
        self.landhungry = (c.land[:, [c.ai["arable"], c.ai["pasture"]]].sum(1) > 0).astype(float)
        self.cold = aff[:, c.ai["cold"]]
        area = np.array([len(cm.cells) for cm in world.communities], float)
        self.area = area
        self.zone_epidemic = self._zones()
        # yields of derived stocks
        self.Yhealth = c.Y[:, c.hi["health"]]
        self.grp_mask_any = np.array([g in GROUPS for g in c.group])
        self.makes = (c.Y > 0).astype(float)
        # attention attaches to needs as a whole (food, warmth, shelter, cloth) and to each other stock
        items = list(GROUPS) + [h for h in c.H if c.stocks[h].get("group") not in GROUPS]
        self.items = items
        G = np.zeros((self.H, len(items)))
        for h, name in enumerate(c.H):
            grp = c.group[h]
            G[h, items.index(grp if grp in GROUPS else name)] = 1
        self.G = G
        self.item_is_group = np.array([x in GROUPS for x in items])
        self.target_h = np.where(self.food, 1.0, 0.3)
        self.Gland = c.build_ * LAND_RATE; self.Dland = c.degrade * LAND_RATE

    def _zones(self) -> np.ndarray:
        bad = np.zeros(self.N)
        kinds = ("disease", "plague", "epidemic", "famine", "drought", "eruption", "flood", "avalanche", "fault")
        for z in self.w.m.live("zones"):
            t = str(z.get("type", "")).lower()
            if not any(x in t for x in kinds):
                continue
            cells = np.asarray(z.get("cells", []), int)
            cells = cells[(cells >= 0) & (cells < len(self.w.cell_comm))]
            for ci in self.w.cell_comm[cells]:
                if ci >= 0:
                    bad[ci] += 1
        return np.clip(bad / np.maximum(self.area if hasattr(self, "area") else 1, 1) * 3, 0, 1)

    # ------------------------------------------------------------------ helpers
    def group_level(self, S, need_w, need_c) -> np.ndarray:
        """Each group stock's level as the group's supply over its need."""
        c = self.c
        out = np.zeros_like(S)
        for gname in GROUPS:
            mask = np.array([g == gname for g in c.group])
            need = {"food": 1.0, "warmth": need_w, "shelter": 0.2, "cloth": need_c}[gname]
            sup = S[:, mask].sum(1) / np.maximum(need, 1e-9)
            out[:, mask] = sup[:, None]
        return out

    def _yfac(self, aff: np.ndarray, n: np.ndarray) -> np.ndarray:
        la = np.log(np.clip(aff, 1e-4, None))
        y = np.exp(la @ self.c.yaff.T)
        # per-person yields from land fall as people crowd the same land
        crowd = np.clip(self.n0 / np.maximum(n, 1e-6), 0.01, 3.0) ** 0.6
        uses_land = (self.c.land.sum(1) > 0) | (np.abs(self.c.yaff[:, self.land_cols]).sum(1) > 0)
        y[:, uses_land] *= crowd[:, None]
        return y

    def _feasibility(self, aff, avail, P, food_level=None) -> np.ndarray:
        c = self.c
        tot = np.zeros((self.N, self.K))
        if food_level is not None:
            sur = c.surplus > 0
            qf = np.clip((food_level[:, None] - 1.0) / c.surplus[None, sur], 1e-6, 1)
            tot[:, sur] += qf ** -GAMMA - 1
        R = c.req_aff
        q = np.clip(aff[:, None, :] / np.where(self.req_aff_mask, R, 1)[None], 1e-6, 1) ** 2  # minima are firm
        tot += np.where(self.req_aff_mask[None], q ** -GAMMA - 1, 0).sum(2)
        Rs = c.req_stock
        qs = np.clip(avail[:, None, :] / np.where(self.req_stock_mask, Rs, 1)[None], 1e-6, 1)
        tot += np.where(self.req_stock_mask[None], qs ** -GAMMA - 1, 0).sum(2)
        if len(self.alt_l):
            ratio = np.clip(P[:, self.alt_l] / self.alt_min, 1e-6, 1)
            gq = np.maximum.reduceat(ratio, self.alt_start, axis=1)
            add = np.zeros((self.N, self.K))
            np.add.at(add.T, self.group_k, (gq ** -GAMMA - 1).T)
            tot += add
        # smooth minimum (Liebig): equals the scarcest requirement when the others are met
        with np.errstate(divide="ignore", over="ignore"):
            g = (1 + tot) ** (-1 / GAMMA)
        return np.clip(g, 0, 1)

    def ripeness(self, P: np.ndarray) -> np.ndarray:
        """How mature a practice's prerequisites are: 1 when every group is held at twice its minimum."""
        r = np.ones((self.N, self.K))
        if len(self.alt_l):
            ratio = np.clip(P[:, self.alt_l] / (2 * self.alt_min), 0, 1)
            gq = np.maximum.reduceat(ratio, self.alt_start, axis=1)
            for j, k in enumerate(self.group_k):
                r[:, k] = np.minimum(r[:, k], gq[:, j])
            r[:, self.nogroups] = 0.0  # practices with no prerequisites gain nothing from ripeness
        return r

    def depth(self, P: np.ndarray) -> np.ndarray:
        """The scalar Azgaar reads: the tier of the most elaborate practice a community sustains.
        Held at 0.3 or more a practice counts in full; held at 0.1 to 0.3 it lifts the depth part of the way
        from what is fully sustained toward its own tier; below 0.1 it is not practised. (Specialist crafts and
        institutions settle at low intensities, because a few people meet the small need for what they make.)"""
        return depth_of(P, self.c.tier)

    # ------------------------------------------------------------------ initial state
    def initial(self, rng) -> tuple:
        c, N, K, H = self.c, self.N, self.K, self.H
        aff = self.aff0.copy()
        S = np.zeros((N, H))
        S[:, self.food] = 1.0 / self.food.sum()
        for h, v in (("wood", 0.3), ("stone", 0.1), ("fibre", 0.2), ("wares", 0.1), ("bonds", 0.1), ("ritual", 0.1)):
            S[:, c.hi[h]] = v
        P = np.zeros((N, K))
        if self.start == "origins":
            for kk in ("forage", "fishing", "burning", "oral", "woodcraft", "leather", "canoes", "assembly",
                       "aggregation"):
                P[:, c.ki[kk]] = 0.3
            L = np.full(N, 3.0)
        else:
            L = self.dev0
            P = self._present_priors(aff, rng)
            for h, v in (("metal", 0.2), ("fuel", 0.2), ("coin", 0.1), ("records", 0.1), ("luxury", 0.1),
                         ("arms", 0.05), ("prestige", 0.1)):
                S[:, c.hi[h]] = v
        g = self._feasibility(aff, S + 0.5, P + 0.5)
        reached = c.tier[None, :] <= L[:, None] + 2
        P = np.clip(P * np.clip(g * 1.5, 0, 1) * reached, 0, 0.9)
        if self.start != "origins":
            # the present: what a people already does near its own level is fully established
            near = reached & (c.tier[None, :] >= L[:, None] - 9) & (P > 0.15) & (g > 0.3)
            P = np.where(near, np.maximum(P, 0.4), P)
        # fit labour: the big subsistence practices give way first, then everything
        big = c.lab >= 0.1
        spec = P[:, ~big] @ c.lab[~big]
        sub = P[:, big] @ c.lab[big]
        f = np.clip((0.95 - spec) / np.maximum(sub, 1e-9), 0.4, 1)
        P[:, big] *= f[:, None]
        lab = P @ c.lab
        P *= np.minimum(1, 0.95 / np.maximum(lab, 1e-9))[:, None]
        Mem = np.maximum(P, 0.3 * (c.tier[None, :] <= L[:, None] - 6) * (g > 0.2))
        return P, Mem, S, aff

    def _present_priors(self, aff, rng) -> np.ndarray:
        c, w = self.c, self.w
        N, K = self.N, self.K
        P = np.full((N, K), 0.0)
        ki = c.ki
        yf = self._yfac(aff, self.n0)
        subs = [ki[k] for k in ("forage", "fishing", "garden", "cereal", "herding", "treecrops", "forestgarden",
                                "pastoral")]
        best = yf[:, subs].max(1, keepdims=True) + 1e-9
        P[:, subs] = 0.15 + 0.55 * yf[:, subs] / best
        universal = {"oral": .4, "woodcraft": .4, "leather": .2, "weaving": .3, "pottery": .3, "preserving": .3,
                     "quarrying": .2, "mining": .3, "coalmining": .2, "charcoal": .2, "ironwork": .3, "bronze": .2,
                     "writing": .3, "storage": .3, "copying": .2, "papermaking": .2, "markets": .3, "guilds": .2,
                     "banking": .15, "scholarship": .15, "distilling": .1, "gunpowder": .15, "cannon": .1,
                     "plough": .3, "lineage": .3, "dairy": .2, "saltmaking": .2, "jewellery": .1, "fineware": .15,
                     "minting": .15, "canoes": .2, "assembly": .2, "aggregation": .15, "priesthood": .2,
                     "glass": .1, "riding": .15, "army": .15, "office": .2}
        for k, v in universal.items():
            P[:, ki[k]] = np.maximum(P[:, ki[k]], v)
        type_prior = {"Nomadic": {"pastoral": .6, "riding": .6, "herding": .5, "raiding": .2},
                      "Naval": {"navigation": .5, "shipbuilding": .5, "fishing": .5, "canoes": .4, "exchange": .2},
                      "Hunting": {"forage": .6, "burning": .3}, "River": {"fishing": .35, "irrigation": .3, "cereal": .5},
                      "Lake": {"fishing": .5, "canoes": .4}, "Highland": {"terracing": .3, "mining": .4, "herding": .4},
                      "Generic": {"cereal": .5, "storage": .4}}
        gov_prior = {"Monarchy": {"lineage": .4, "office": .3, "army": .3}, "Republic": {"markets": .45, "assembly": .3, "office": .3},
                     "Union": {"league": .4, "assembly": .35}, "Theocracy": {"priesthood": .5, "office": .2},
                     "Anarchy": {"assembly": .5}}
        rel_prior = {"Organized": {"priesthood": .4, "writing": .3}, "Folk": {"oral": .5, "aggregation": .3},
                     "Cult": {"priesthood": .35}, "Heresy": {"assembly": .25}}
        cultures = w.m.data["cultures"]
        states = w.m.data["states"]
        burg_goods = {}
        for b in w.m.live_burgs():
            burg_goods[b["i"]] = b.get("production", [])
        goods = {g["i"]: g["name"] for g in w.m.goods}
        for i, cm in enumerate(w.communities):
            cu = cultures[cm.culture]
            for k, v in type_prior.get(cu.get("type", "Generic"), {}).items():
                P[i, ki[k]] = max(P[i, ki[k]], v)
            st = states[cm.state] if cm.state < len(states) and isinstance(states[cm.state], dict) else {}
            for k, v in gov_prior.get(st.get("form", ""), {}).items():
                P[i, ki[k]] = max(P[i, ki[k]], v)
            for k, v in rel_prior.get(cm.religion_type, {}).items():
                P[i, ki[k]] = max(P[i, ki[k]], v)
            f = cm.features
            P[i, ki["priesthood"]] = max(P[i, ki["priesthood"]], 0.5 * f["temple"])
            P[i, ki["army"]] = max(P[i, ki["army"]], 0.4 * max(f["walls"], f["citadel"]))
            P[i, ki["office"]] = max(P[i, ki["office"]], 0.3 * max(f["walls"], f["citadel"]) + 0.2 * min(f["capital"], 1))
            P[i, ki["markets"]] = max(P[i, ki["markets"]], 0.5 * f["plaza"])
            P[i, ki["shipbuilding"]] = max(P[i, ki["shipbuilding"]], 0.5 * f["port"])
            P[i, ki["navigation"]] = max(P[i, ki["navigation"]], 0.4 * f["port"])
            made = defaultdict_float()
            for bi in cm.burgs:
                for gid, units in burg_goods.get(bi, []):
                    made[goods.get(gid, "")] += units
            total = sum(made.values()) or 1
            for gname, units in made.items():
                for k in c.practices_of_good(gname):
                    P[i, k] = max(P[i, k], min(0.8, 0.25 + 2.0 * units / total))
        P += rng.normal(0, 0.03, P.shape)
        return np.clip(P, 0, 0.9)

    # ------------------------------------------------------------------ run
    def run(self, prm: Params, steps: int, sample_every: int = 10) -> RunResult:
        c, N, K, H = self.c, self.N, self.K, self.H
        rng = np.random.default_rng(prm.seed)
        sc = prm.scenario
        P, Mem, S, aff = self.initial(rng)
        n = self.n0.copy()
        E = aff[:, self.land_cols].copy()
        Ebar = E.copy() + 1e-3
        I = len(self.items)
        Ai = np.zeros((N, I))
        A = Ai @ self.G.T
        J = c.J_mech * prm.J_scale
        for a_list, b_list, val in sc.get("J", []):
            ia = [c.ki[x] for x in a_list if x in c.ki]
            ib = [c.ki[x] for x in b_list if x in c.ki]
            v = val / np.sqrt(max(1, len(ia) * len(ib)))
            for x in ia:
                for y in ib:
                    if x != y:
                        J[x, y] += v; J[y, x] += v
        cost = c.cost.copy()
        cost[c.coord] *= sc.get("coord_cost", 1.0)
        wk = np.array([sc["w"].get(kd, 0) for kd in KINDS])
        Wcap = c.w @ wk
        # affinity: S3 sets some cross-culture pairs against each other
        alpha = np.ones((N, N))
        if sc.get("alpha_neg", 0) > 0:
            diff = self.cult[:, None] != self.cult[None, :]
            pick = rng.random((N, N)) < sc["alpha_neg"]
            pick = np.triu(pick, 1); pick = pick | pick.T
            alpha[diff & pick] = -0.5
        np.fill_diagonal(alpha, 0)
        scale = self.w.scale
        r0, l0 = scale * 1.2, scale * 1.0
        z = np.zeros((N, H))
        cap_out = np.zeros((N, len(FORMS))); cap_in = np.zeros((N, len(FORMS)))
        traj, strj, dtraj = [], [], []
        dmat = W = None
        X = np.zeros(N); reach = np.full(N, r0)
        health_i = c.hi["health"]; leisure_i = c.hi["leisure"]; ecology_i = c.hi["ecology"]
        captives_i = c.hi["captives"]
        food = self.food
        groups = {gname: np.array([g == gname for g in c.group]) for gname in GROUPS}
        need_w = 0.15 + 0.45 * self.cold
        need_c = 0.1 + 0.2 * self.cold
        norm = c.needs["norm"]
        dens = np.clip((n / self.area) / np.median(n / self.area), 0.3, 3.0)

        for t in range(steps):
            aff[:, self.land_cols] = E
            # --- distances and reach, every 10 steps
            if t % 10 == 0:
                boat = np.clip(P @ self.seamob, 0, 2.5)
                lm = np.clip(P @ self.landmob, 0, 3)
                bij = 0.7 * np.maximum(boat[:, None], boat[None]) + 0.3 * np.minimum(boat[:, None], boat[None])
                seafac = 1 + 8 * np.clip(1 - bij, 0, 1) ** 2
                lmij = 0.5 * (lm[:, None] + lm[None])
                dmat = np.minimum(self.w.d_land / (1 + 0.5 * lmij), self.w.d_sea * seafac / (1 + 0.3 * bij))
                comm = P @ c.com
                ell = l0 * (1 + 0.4 * 0.5 * (comm[:, None] + comm[None]))
                kappa = prm.kappa0 * alpha * np.exp(-dmat / ell)
                mk = 0.2 + P[:, self.k_markets] + P[:, self.k_exchange] + 0.5 * P[:, self.k_bank]
                popw = 2 * n[None, :] / (n[:, None] + n[None, :])
                Wbase = np.exp(-dmat[:, :, None] / (2.0 * scale * self.beta[None, None, :]))
                for i in range(N):
                    Wbase[i, i, :] = 0
                W = Wbase * (0.5 * (mk[:, None] + mk[None]) * popw)[:, :, None]
                reach = r0 * (1 + P @ c.mob)
                ex = (self.w.free_compat * np.exp(-self.w.free_dist / reach[:, None])).sum(1) / 25.0
                X = 1 - np.exp(-sc["zeta"] * ex)
            # --- production
            yf = self._yfac(aff, n)
            PY = P * yf
            prod = PY @ c.Y
            use = P @ c.U
            avail = S + prod + np.einsum("ijh,jh->ih", Wbase, S + prod) * 0.5
            food_level = (S[:, food].sum(1) + prod[:, food].sum(1)) / (1.0 + TAINTER * (P @ (c.tier / 100.0)) ** 1.5)
            g = self._feasibility(aff, avail, P, food_level)
            # --- mobilisable capacity and capture
            Mc = n * (P @ Wcap + 0.05)
            asym = np.clip(Mc[:, None] - Mc[None, :], 0, None) / (Mc[:, None] + Mc[None, :])
            R = np.exp(-dmat / reach[:, None])
            np.fill_diagonal(R, 0)
            legib = 1 + 0.6 * (P[:, self.k_office] + P[:, self.k_reg])
            RA = sc["chi"] * R * asym * (1 - X)[None, :] * legib[:, None]
            take = RA[:, :, None] * (self.approp[None, None, :] * S[None, :, :])
            lost = take.sum(0)
            limit = np.minimum(1, 0.1 * S / np.maximum(lost, 1e-9))
            take *= limit[None, :, :]
            lost = take.sum(0)
            gained = np.einsum("ijh,j->ih", take, n) / n[:, None]
            capshare = np.clip(lost / (prod + 1e-6), 0, 1)
            # captives and displacement
            raid = P[:, self.k_raid] + 0.3 * (P @ c.w[:, KINDS.index("arms")]) / 4
            cp = 0.02 * sc["chi"] * R * asym * (1 - X)[None, :] * raid[:, None]
            people = cp.sum(0)
            gained[:, captives_i] += (cp * n[None, :]).sum(1) / n * 0.5
            land_take = 0.02 * sc["chi"] * R * asym * (1 - X)[None, :] * (P @ self.landhungry)[:, None]
            lt = np.clip(land_take.sum(0), 0, 0.05)
            # --- trade
            if sc.get("worldsystem"):
                tilt = 1 + 0.6 * (Mc[:, None] - Mc[None, :]) / (Mc[:, None] + Mc[None, :])
                Wt = W * tilt[:, :, None]
            else:
                Wt = W
            T = prm.trade * (np.einsum("ijh,jh->ih", Wt, S) - S * Wt.sum(1))
            T[:, c.derived] = 0
            # --- stocks
            S = np.clip(S + prod - use + T + gained - lost, 0, None)
            # consumption by need group; holding many elaborate practices costs food (complexity overhead)
            Cx = P @ (c.tier / 100.0)
            overhead = TAINTER * Cx ** 1.5
            zg = {}
            for gname, mask in groups.items():
                need = {"food": 1.0 + overhead, "warmth": need_w, "shelter": 0.2, "cloth": need_c}[gname]
                need = np.broadcast_to(need, (N,))
                sup = S[:, mask].sum(1)
                used = np.minimum(sup, need)
                share = S[:, mask] / np.maximum(sup, 1e-9)[:, None]
                S[:, mask] -= share * used[:, None]
                zg[gname] = np.clip(1 - sup / np.maximum(need, 1e-9), 0, 1)
            # what is left after eating decays: unstorable food does not keep
            d = np.tile(self.decay, (N, 1))
            st = P[:, self.k_storage]
            for h in ("grain", "stores"):
                d[:, c.hi[h]] *= 1 - 0.6 * st
            S -= d * S
            S = np.clip(S, 0, S_MAX)
            # derived stocks
            fsup = S[:, food]
            breadth = (fsup / np.maximum(fsup.sum(1, keepdims=True), 1e-9) > 0.1).sum(1)
            crowd = np.clip(self.urban * (0.5 + 0.5 * n / np.median(n)), 0, 1)
            S[:, health_i] = np.clip(0.35 + 0.08 * breadth + P @ self.Yhealth - 0.35 * crowd
                                     - 0.25 * self.zone_epidemic - 0.3 * zg["food"], 0, 1.5)
            labour = P @ c.lab
            capacity = 1 + 0.5 * np.clip(S[:, captives_i], 0, 1) * P[:, self.k_bond]
            S[:, leisure_i] = np.clip(1 - labour / capacity, 0, 1)
            S[:, ecology_i] = np.clip((E / Ebar).mean(1), 0, 1.5)
            # stress
            for h in range(H):
                grp = c.group[h]
                if grp in zg:
                    z[:, h] = zg[grp]
                elif not c.derived[h]:
                    # a norm is felt for what a people makes or remembers making (dormant pathways)
                    nh = norm * np.max(np.maximum(P, Mem) * self.makes[:, h][None, :], axis=1)
                    z[:, h] = np.where(nh > 0.005, np.clip(1 - S[:, h] / np.maximum(nh, 1e-9), 0, 1), 0)
            z[:, health_i] = np.clip(0.8 - S[:, health_i], 0, 1)
            z[:, ecology_i] = np.clip(0.9 - S[:, ecology_i], 0, 1)
            z[:, leisure_i] = np.clip(0.2 - S[:, leisure_i], 0, 1) * 3
            zbar = np.mean([zg[x] for x in GROUPS], axis=0)
            # --- attention (over needs and stocks)
            phi = np.zeros((N, H))
            phi[:, self.nonderived] = (prod / self.scale_h)[:, self.nonderived]
            phi[:, health_i] = (P @ self.Yhealth) * 2 + 0.05
            phi[:, ecology_i] = (P @ self.Gland.sum(1)) * 10
            phi[:, leisure_i] = 0.05
            phi_i = phi @ self.G
            phi_i = np.clip(phi_i / np.maximum(phi_i.sum(1, keepdims=True), 1e-9) * BUDGET, 0, 1)
            z_i = np.zeros((N, I))
            for j, name in enumerate(self.items):
                z_i[:, j] = zg[name] if name in zg else z[:, c.hi[name]]
            if t == 0:
                Ai = phi_i.copy()  # a people starts by watching what it makes
            elif not sc.get("fixed_attention"):
                zstar = prm.z0 + prm.z1 * (1 - Ai) * ~self.item_is_group[None, :]  # hunger and cold are always felt
                Ai = Ai + prm.eta * (phi_i - Ai) + prm.theta * np.clip(z_i - zstar, 0, None) * (1 - Ai)
                Ai = np.clip(Ai, 0, 1)
                tot = Ai.sum(1, keepdims=True)
                Ai = np.where(tot > BUDGET, Ai * BUDGET / tot, Ai)
            A = Ai @ self.G.T
            # --- practices
            # marginal value: a stock short of its norm is worth more, a full one less
            # wants grow with attention: what a people watches, it wants more of (the engine of elaboration)
            target = self.target_h[None, :] * (1 + WANTS * A)
            level = np.where(self.grp_mask_any[None, :], self.group_level(S, need_w, need_c), S / target)
            value = (1 + z) / (1 + level ** 2)
            att = (0.15 + 0.85 * A) * value / self.scale_h  # some awareness of everything usable (an addition)
            benefit = yf * ((att * (1 - capshare)) @ c.Y.T) - att @ c.U.T
            benefit += A[:, [ecology_i]] * ((c.build_ - c.degrade).sum(1)[None, :] * 20)
            # what the stock accounts miss: reach (getting to others) and memory (keeping what is known) are worth
            # something in themselves (an addition to the spec, scaled by REACH_MEMORY)
            benefit += REACH_MEMORY * (c.mob + 0.5 * c.com + 0.5 * c.mem)[None, :]
            benefit -= (0.3 + 1.5 * A[:, [leisure_i]]) * c.lab[None, :]
            vfood = (value[:, self.food] * A[:, self.food]).mean(1)
            benefit -= (vfood * TAINTER * 1.5 * np.sqrt(Cx) * 3)[:, None] * (c.tier / 100.0)[None, :]
            over = np.clip(P @ c.lab - 0.85 * capacity, 0, None)
            benefit -= 4.0 * over[:, None] * c.lab[None, :]
            upkeep = UPKEEP[0] + UPKEEP[1] * c.tier / 100.0
            learn = 1 + 0.4 * np.clip(P @ c.mem, 0, 3)
            if t == 0:
                # calibrate the scale of benefits so the present world is near balance (pattern-oriented)
                active = P > 0.3
                need_ = (cst_raw := np.tile(cost, (N, 1))) * (1 - Mem) / learn[:, None] + upkeep[None, :] - P @ J.T
                b = benefit[active]; y = need_[active]
                beta = float(np.clip(np.median(y) / max(np.median(b[b > 0]) if (b > 0).any() else 1, 1e-6), 0.3, 3.0))
                self.beta_last = beta
            benefit *= beta
            cst = np.tile(cost, (N, 1))
            if sc.get("boserup"):
                cst[:, c.intensive] *= (1 - 0.7 * zbar)[:, None]
            # what a people already knows how to keep makes new things cheaper to learn (an addition to the spec)
            # the adjacent possible: once a practice's prerequisites are mature it is cheap to start (Kauffman)
            ripe = self.ripeness(P)
            barrier = cst * (1 - Mem) * (1 - 0.7 * ripe) / learn[:, None]
            internal = P * (1 - P) * g * (P @ J.T + benefit - barrier - upkeep[None, :])
            if self.debug is not None and t == self.debug[0]:
                self.debug_out = dict(J=P @ J.T, benefit=benefit, cost=barrier, upkeep=upkeep,
                                      g=g, P=P.copy(), A=A.copy(), S=S.copy(), value=value)
            imit = g * (kappa @ P - P * kappa.sum(1, keepdims=True))
            # captured communities are pushed toward their captors' practices
            frac = np.clip(lost.sum(1) / np.maximum(S.sum(1) + prod.sum(1), 1e-9), 0, 1)
            force = (0.5 * frac)[:, None] * ((RA.T @ P) / np.maximum(RA.sum(0), 1e-9)[:, None] - P)
            innov = g * (prm.nu0 + prm.nu_m * Mem) * (1 - P)
            abandon = -0.05 * (1 - g) * P  # what can no longer be supplied is given up (an addition to the spec)
            noise = prm.sigma * rng.normal(0, 1, (N, K)) * np.sqrt(P * (1 - P) + 0.01) * (g > 0.05)
            P = np.clip(P + DT * (internal + imit + 0.5 * force + innov + abandon) + noise, 0, 1)
            labour = P @ c.lab
            P *= np.minimum(1, 1.05 * capacity / np.maximum(labour, 1e-9))[:, None]
            # --- memory
            mem_strength = P @ c.mem
            hear = 0.02 * np.clip(kappa, 0, None) @ P
            Mem = Mem + prm.mu * np.clip(P - Mem, 0, None) - prm.delta0 / (1 + 2.0 * mem_strength)[:, None] * Mem \
                + np.clip(hear - Mem, 0, None) * 0.05
            Mem = np.clip(Mem, 0, 1)
            # --- land
            E = E + 0.02 * (Ebar - E) - dens[:, None] * (P @ self.Dland) + P @ self.Gland
            E[:, [LAND.index("soil"), LAND.index("pasture")]] *= (1 - lt)[:, None]
            E = np.clip(E, 0, 1.5 * Ebar + 0.2)
            # --- population
            # people multiply while food runs well ahead of need, and dwindle when it does not
            n = n * (1 + 0.004 * np.clip(food_level - 1.4, -0.4, 0.4) - 0.01 * zbar) * (1 - np.clip(people, 0, 0.02))
            n = np.clip(n, 0.8 * self.n0, 1.25 * self.n0)  # Azgaar keeps its population; here it moves within bounds
            dens = np.clip((n / self.area) / np.median(n / self.area), 0.3, 3.0)
            # --- capture bookkeeping by form (last third of the run)
            if t >= steps * 2 // 3:
                tk = take.sum(2)
                hidx = c.hi
                gr = (take[:, :, [hidx["grain"], hidx["stores"], hidx["coin"]]].sum(2))
                mobile = (P @ c.mob > 0.8).astype(float)
                credit = (P[:, self.k_bank] + P[:, self.k_markets] > 0.6).astype(float)
                tribute = gr * (1 - mobile)[:, None] * (1 - credit)[:, None]
                raidf = tk * mobile[:, None]
                debt = tk * credit[:, None]
                for arr, f in ((tribute, 0), (raidf, 1), (debt, 2)):
                    cap_out[:, f] += (arr * n[None, :]).sum(1)
                    cap_in[:, f] += (arr * n[None, :]).sum(0)
                cap_out[:, 5] += (land_take * n[None, :]).sum(1)
                cap_in[:, 5] += (land_take * n[None, :]).sum(0)
                # within communities: excludable knowledge held by few, and immobile inheritance
                cap_in[:, 3] += P[:, self.k_priest] * S[:, c.hi["ritual"]] * c.pi[c.hi["ritual"], 4] * n * 0.01
                house = (P[:, c.ki["plough"]] + P[:, c.ki["storage"]] + P[:, c.ki["lineage"]]) / 3
                cap_in[:, 4] += house * (1 - X) * n * 0.01
            if t % sample_every == 0 or t == steps - 1:
                traj.append(P.copy()); strj.append(S.copy()); dtraj.append(self.depth(P))
        Mc = n * (P @ Wcap + 0.05)
        return RunResult(scenario=sc["id"], seed=prm.seed, P=P, Mem=Mem, A=A, S=S, n=n, E=E, D=self.depth(P),
                         traj=np.array(traj), Strj=np.array(strj), Dtraj=np.array(dtraj), Mcap=Mc,
                         cap_out=cap_out, cap_in=cap_in, exit=X, reach=reach)


def depth_of(P: np.ndarray, tier: np.ndarray, lo: float = 0.1, hi: float = 0.3) -> np.ndarray:
    f = np.clip((P - lo) / (hi - lo), 0, 1)
    full = np.where(f >= 0.999, tier[None, :], 1.0).max(-1)
    part = (full[..., None] + (tier[None, :] - full[..., None]) * f).max(-1)
    return np.clip(np.maximum(full, part), 1, 100)


def defaultdict_float():
    from collections import defaultdict
    return defaultdict(float)


def ensemble(model: Model, cat: Catalogue, steps: int, seeds: int, scenarios: list[str] | None = None,
             base_seed: int = 1, fixed_attention: bool = False, log=print) -> list[RunResult]:
    ids = scenarios or [s["id"] for s in cat.scenarios["scenarios"]]
    out = []
    for si, sid in enumerate(ids):
        for r in range(seeds):
            seed = base_seed + 1000 * si + r
            rng = np.random.default_rng(seed)
            prm = draw_params(cat, sid, rng, seed, fixed_attention)
            res = model.run(prm, steps)
            out.append(res)
            if log:
                log(f"  {sid} seed {r + 1}/{seeds}: depth median {np.median(res.D):.0f}, max {res.D.max():.0f}")
    return out
