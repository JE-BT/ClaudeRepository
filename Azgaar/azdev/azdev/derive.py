"""What is computed after the runs (spec 'What is computed from the simulation'): axes, basins, depth,
velocity, flourishing profiles and shadows, capture forms, dormant pathways, and the failure checks."""
from __future__ import annotations

import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF
from sklearn.metrics import silhouette_score

from .catalogue import Catalogue
from .model import FORMS, Model, RunResult, depth_of

warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class Derived:
    axes: list[dict]
    H: np.ndarray                 # axis loadings k x K
    basins: list[dict]
    member: np.ndarray            # run x community -> basin index
    community: list[dict]
    scenario_table: dict
    layers: dict
    diagnostics: list[dict]
    flourish_dims: list[str]
    depth: np.ndarray             # median depth per community (the scalar)
    depth_lo: np.ndarray
    depth_hi: np.ndarray
    P_med: np.ndarray
    M_med: np.ndarray
    Mem_med: np.ndarray
    notes: list[str] = field(default_factory=list)


def _axes(X: np.ndarray, cat: Catalogue, kmax: int = 7) -> tuple[NMF, np.ndarray, list[dict]]:
    errs = []
    models = {}
    for k in range(2, kmax + 1):
        nmf = NMF(n_components=k, init="nndsvda", max_iter=600, random_state=0)
        W = nmf.fit_transform(X)
        errs.append(nmf.reconstruction_err_)
        models[k] = (nmf, W)
    # smallest k after which adding an axis improves the fit by less than 8%
    pick = kmax
    for i in range(1, len(errs)):
        if (errs[i - 1] - errs[i]) / errs[i - 1] < 0.08:
            pick = i + 1
            break
    nmf, W = models[pick]
    H = nmf.components_
    total = np.sum((X - X.mean(0)) ** 2)
    axes = []
    for j in range(pick):
        part = np.outer(W[:, j], H[j])
        share = float(np.sum((part - part.mean(0)) ** 2) / total)
        top = np.argsort(-H[j])[:4]
        axes.append({"i": j, "share": share, "top": [cat.K[k] for k in top],
                     "label": " · ".join(cat.practices[k]["name"].split(" and ")[0].split(",")[0] for k in top[:3])})
    order = np.argsort([-a["share"] for a in axes])
    axes = [axes[i] | {"i": n} for n, i in enumerate(order)]
    return nmf, H[order], axes


def _label(centroid: np.ndarray, cat: Catalogue, top: int = 8) -> tuple[str, float]:
    """The stylised basin whose hint words best match the practices the cluster holds most of."""
    weight = centroid * (1 + cat.tier / 50)
    keep = np.argsort(-weight)[:top]
    tags = defaultdict(float)
    for k in keep:
        for t in cat.hints[k]:
            tags[t] += weight[k]
    tagscore = dict(tags)
    best, score = None, -1
    for b in cat.basins:
        s = sum(w * tagscore.get(t, 0) for t, w in b["tags"].items()) / sum(b["tags"].values())
        if s > score:
            best, score = b["name"], s
    return best, score


def derive(model: Model, runs: list[RunResult], cat: Catalogue, extra_runs: dict | None = None, log=print,
           depth_stat: float = 50) -> Derived:
    N, K = model.N, model.K
    R = len(runs)
    Pf = np.stack([r.P for r in runs])               # R x N x K
    X = Pf.reshape(R * N, K)
    nmf, Hax, axes = _axes(X, cat)
    W = nmf.transform(X)
    # reorder W columns to match sorted axes
    comp = nmf.components_
    idx = [int(np.argmin([np.abs(comp[j] - h).sum() for j in range(len(comp))])) for h in Hax]
    W = W[:, idx]

    # ---- basins: cluster how each community differs from the rest of its world in the same run. What a whole
    # run shares is the scenario's institutional layer (reported apart); what differs within it is the basin.
    Pr = Pf - Pf.mean(1, keepdims=True)
    Xc = Pr.reshape(R * N, K)
    sd = np.maximum(Xc.std(0), 0.05)
    Z = Xc / sd
    best = (-1, 3, None, 0)
    for k in range(3, 9):
        km_ = KMeans(k, n_init=6, random_state=0).fit(Z)
        sil = silhouette_score(Z, km_.labels_, sample_size=min(2000, len(Z)), random_state=0)
        lab_ = km_.labels_.reshape(R, N)
        stab = np.mean([Counter(lab_[:, i]).most_common(1)[0][1] / R for i in range(N)])
        score = sil + 0.3 * stab
        if score > best[0] + 0.005:
            best = (score, k, km_, stab)
    km = best[2]
    lab = km.labels_.reshape(R, N)
    basins = []
    for b in range(best[1]):
        m_ = km.labels_ == b
        dev = Xc[m_].mean(0)
        cen = X[m_].mean(0)
        name, score = _label(np.clip(dev, 0, None), cat)
        top = np.argsort(-dev * (1 + cat.tier / 50))[:5]
        basins.append({"i": b, "name": name, "score": score, "centroid": cen, "deviation": dev,
                       "top": [cat.K[k] for k in top], "size": int(m_.sum())})
    flat_out = np.concatenate([r.cap_out.sum(1) for r in runs])
    flat_in = np.concatenate([r.cap_in[:, :3].sum(1) for r in runs])
    for b in basins:
        if b["name"].startswith("Maritime exchange"):
            m_ = km.labels_ == b["i"]
            net = (flat_out[m_] - flat_in[m_]).mean() if m_.any() else 0
            b["name"] = "Maritime exchange, extractive" if net > 0 else "Maritime exchange, reciprocal"
    seen = Counter(b["name"] for b in basins)
    for name, count in seen.items():
        if count > 1:
            for b in [b for b in basins if b["name"] == name]:
                b["name"] = f"{name} ({cat.practices[cat.ki[b['top'][0]]]['name'].split(' and ')[0].lower()})"
    for b in basins:
        ref = next((x for x in cat.basins if b["name"].startswith(x["name"])), None)
        b["reading"] = ref or {}
    # the institutional layer each scenario gives its whole world
    layers = {}
    for sid in sorted({r.scenario for r in runs}):
        rs = [i for i, r in enumerate(runs) if r.scenario == sid]
        mean = Pf[rs].mean((0, 1))
        inst = [k for k in np.argsort(-mean) if mean[k] > 0.5 and cat.lab[k] < 0.1][:6]
        layers[sid] = [cat.K[k] for k in inst]

    # ---- per scenario: which basins appear
    scen = [r.scenario for r in runs]
    sids = sorted(set(scen))
    table = {}
    for b in basins:
        row = {}
        for sid in sids:
            rs = [i for i, s in enumerate(scen) if s == sid]
            share = float(np.mean([np.mean(lab[i] == b["i"]) for i in rs]))
            row[sid] = share
        b["scenarios_present"] = sum(1 for v in row.values() if v >= 0.02)
        b["robust"] = b["scenarios_present"] >= max(1, round(len(sids) * 5 / 7))
        table[b["name"]] = row

    # ---- per community
    D = np.stack([r.D for r in runs])
    depth = np.percentile(D, depth_stat, 0)  # the median history, or a more favourable one
    lo, hi = np.percentile(D, 10, 0), np.percentile(D, 90, 0)
    P_med = np.median(Pf, 0)
    Mem_med = np.median(np.stack([r.Mem for r in runs]), 0)
    S_med = np.median(np.stack([r.S for r in runs]), 0)
    A_med = np.median(np.stack([r.A for r in runs]), 0)
    M_med = np.median(np.stack([r.Mcap for r in runs]), 0)
    cap_in = np.median(np.stack([r.cap_in for r in runs]), 0)
    cap_out = np.median(np.stack([r.cap_out for r in runs]), 0)
    # velocity: change of axis scores and depth over the last third
    vel = np.zeros((N, len(axes)))
    dvel = np.zeros(N)
    for r in runs:
        T = len(r.traj)
        a, b_ = int(T * 2 / 3), T - 1
        if b_ <= a:
            continue
        Wa = nmf.transform(r.traj[a])[:, idx]
        Wb = nmf.transform(r.traj[b_])[:, idx]
        vel += (Wb - Wa) / (b_ - a)
        dvel += (r.Dtraj[b_] - r.Dtraj[a]) / (b_ - a)
    vel /= R; dvel /= R
    # flourishing dimensions: stocks somebody attends to
    attended = A_med > 0.15
    dims = [h for j, h in enumerate(cat.H) if attended[:, j].any()]
    # shadow: unattended stocks falling over the last third
    shadows = []
    for i in range(N):
        sh = []
        for j, h in enumerate(cat.H):
            if attended[i, j]:
                continue
            trend = np.median([r.Strj[-1][i, j] - r.Strj[int(len(r.Strj) * 2 / 3)][i, j] for r in runs])
            if trend < -0.01:
                sh.append(h)
        shadows.append(sh)
    comm = []
    for i, cm in enumerate(model.w.communities):
        counts = Counter(lab[:, i])
        modal, n_modal = counts.most_common(1)[0]
        second = counts.most_common(2)[1] if len(counts) > 1 else None
        dormant = [cat.K[k] for k in np.argsort(-Mem_med[i]) if Mem_med[i, k] > 0.15 and P_med[i, k] < 0.1][:5]
        held = [cat.K[k] for k in np.argsort(-(P_med[i] * (1 + cat.tier / 50))) if P_med[i, k] > 0.1][:8]
        forms_in = [FORMS[f] for f in np.argsort(-cap_in[i]) if cap_in[i, f] > 1e-3][:2]
        forms_out = [FORMS[f] for f in np.argsort(-cap_out[i]) if cap_out[i, f] > 1e-3][:2]
        comm.append({"i": i, "culture": cm.culture, "province": cm.province, "state": cm.state, "n": cm.n,
                     "basin": int(modal), "basin_share": n_modal / R,
                     "second": (int(second[0]), second[1] / R) if second else None,
                     "depth": float(depth[i]), "depth_lo": float(lo[i]), "depth_hi": float(hi[i]),
                     "dev_now": cm.dev_now, "velocity": vel[i].tolist(), "dvel": float(dvel[i]),
                     "held": held, "dormant": dormant, "shadow": shadows[i][:4],
                     "attends": [h for j, h in enumerate(cat.H) if attended[i, j]],
                     "capture_in": forms_in, "capture_out": forms_out, "profile": S_med[i].tolist()})

    extra = {}
    for key, rr in (extra_runs or {}).items():
        labels, deps = [], []
        for r in rr:
            labels.extend(km.predict((r.P - r.P.mean(0)) / sd).tolist())
            deps.append(r.D)
        lab_x = np.array(labels).reshape(len(rr), N)
        modal_x = [Counter(lab_x[:, i]).most_common(1)[0][0] for i in range(N)]
        extra[key] = {"labels": labels, "depth": np.median(np.stack(deps), 0), "modal": modal_x}
    diags = diagnostics(model, runs, cat, axes, W.reshape(R, N, -1), basins, lab, S_med, A_med, dims, depth,
                        M_med, cap_in, cap_out, extra)
    return Derived(axes=axes, H=Hax, basins=basins, member=lab, community=comm, scenario_table=table, layers=layers,
                   diagnostics=diags, flourish_dims=dims, depth=depth, depth_lo=lo, depth_hi=hi, P_med=P_med,
                   M_med=M_med, Mem_med=Mem_med)


def _tvd(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    ta, tb = sum(a.values()) or 1, sum(b.values()) or 1
    return 0.5 * sum(abs(a[k] / ta - b[k] / tb) for k in keys)


def diagnostics(model, runs, cat, axes, Wr, basins, lab, S_med, A_med, dims, depth, M_med, cap_in, cap_out, extra):
    out = []
    N = model.N
    R = len(runs)
    score1 = np.median(Wr[:, :, 0], 0)
    # F1 a ladder
    share1 = axes[0]["share"]
    signs = []
    for h in dims:
        x = S_med[:, cat.hi[h]]
        if np.std(x) > 1e-9:
            signs.append(np.sign(spearmanr(score1, x)[0]))
    same = len(signs) > 0 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))
    out.append({"id": "F1", "name": "A ladder has re-emerged", "failed": bool(share1 > 0.6 and same),
                "detail": f"first axis carries {share1:.0%} of the variance; flourishing dimensions load with "
                          f"{'one sign' if same else 'mixed signs'} on it"})
    # F2 a monopoly on violence
    worst = (0, None)
    cin = cap_in[:, :3].sum(1)
    for j in range(Wr.shape[2]):
        s = np.median(Wr[:, :, j], 0)
        for name, v in (("capacity", M_med), ("capture suffered", cin)):
            if np.std(v) > 1e-9 and np.std(s) > 1e-9:
                rho = abs(spearmanr(s, v)[0])
                if rho > worst[0]:
                    worst = (rho, f"{name} on axis {j + 1}")
    out.append({"id": "F2", "name": "A monopoly on violence", "failed": bool(worst[0] > 0.8),
                "detail": f"strongest rank correlation {worst[0]:.2f} ({worst[1]})"})
    # F3 a best society
    prof = {}
    for b in basins:
        m = np.array([c for c in range(N) if np.argmax(np.bincount(lab[:, c], minlength=len(basins))) == b["i"]])
        if len(m):
            prof[b["name"]] = np.array([S_med[m, cat.hi[h]].mean() for h in dims])
    dominant = []
    for a, pa in prof.items():
        if all(np.all(pa >= pb) and np.any(pa > pb) for b_, pb in prof.items() if b_ != a) and len(prof) > 1:
            dominant.append(a)
    out.append({"id": "F3", "name": "A best society", "failed": bool(dominant),
                "detail": ("Pareto-dominant: " + ", ".join(dominant)) if dominant else
                f"no basin dominates the others on {len(dims)} flourishing dimensions"})
    # F4 no content
    robust = sum(1 for b in basins if b["robust"])
    out.append({"id": "F4", "name": "No content", "failed": bool(robust < len(basins) / 2),
                "detail": f"{robust} of {len(basins)} basins appear in at least 5 of 7 scenarios"})
    # F5, F6 from the extra ensembles
    base_counts = Counter(lab.ravel().tolist())
    modal = [Counter(lab[:, i]).most_common(1)[0][0] for i in range(N)]
    for fid, name, key in (("F5", "Geography is idle", "shuffled"), ("F6", "No feedback", "fixed_attention")):
        if key in extra:
            other = extra[key]
            tvd = _tvd(base_counts, Counter(other["labels"]))
            moved = float(np.mean([a != b for a, b in zip(modal, other["modal"])]))
            dd = float(np.median(np.abs(other["depth"] - depth)))
            failed = tvd < 0.1 and moved < 0.1 and dd < 2
            out.append({"id": fid, "name": name, "failed": bool(failed),
                        "detail": f"when {'each affordance is dealt out at random' if key == 'shuffled' else 'attention is fixed'}, "
                                  f"{moved:.0%} of communities change basin, basin shares move by {tvd:.0%} and depth "
                                  f"by {dd:.1f} points"})
        else:
            out.append({"id": fid, "name": name, "failed": None, "detail": "not run (use --diagnose)"})
    # projection checks on the scalar Azgaar will read
    rho = spearmanr(depth, M_med)[0] if np.std(depth) > 1e-9 else 0.0
    out.append({"id": "P1", "name": "The scalar orders violence", "failed": bool(abs(rho) > 0.8),
                "detail": f"rank correlation of development with mobilisable capacity {rho:+.2f} "
                          "(development also decides who trades first in Azgaar)"})
    signs = []
    for h in dims:
        x = S_med[:, cat.hi[h]]
        if np.std(x) > 1e-9 and np.std(depth) > 1e-9:
            signs.append(spearmanr(depth, x)[0])
    ladder = len(signs) > 0 and all(s > 0.3 for s in signs)
    out.append({"id": "P2", "name": "The scalar is a ladder", "failed": bool(ladder),
                "detail": f"development correlates positively with {sum(1 for s in signs if s > 0.3)} of "
                          f"{len(signs)} flourishing dimensions and negatively with "
                          f"{sum(1 for s in signs if s < -0.3)}"})
    # expected results that are cheap to check
    forms = Counter()
    for f in range(len(FORMS)):
        if (cap_in[:, f] > 1e-3).sum() >= 2:
            forms[FORMS[f]] += 1
    out.append({"id": "R3", "name": "Capture in several forms", "failed": bool(len(forms) < 3),
                "detail": f"forms present: {', '.join(forms) or 'none'}"})
    nb = len({np.argmax(np.bincount(lab[:, c], minlength=len(basins))) for c in range(N)})
    out.append({"id": "R2", "name": "Several basins coexist", "failed": bool(nb < 3),
                "detail": f"{nb} basins hold at least one community as its most frequent home"})
    return out
