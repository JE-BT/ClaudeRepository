"""Run the scenario ensemble, in parallel where the machine allows."""
from __future__ import annotations

import multiprocessing as mp
import os

import numpy as np

from .catalogue import Catalogue
from .model import Model, RunResult, draw_params

_MODEL: Model | None = None
_CAT: Catalogue | None = None


def _one(job):
    sid, seed, steps, fixed = job
    rng = np.random.default_rng(seed)
    prm = draw_params(_CAT, sid, rng, seed, fixed)
    res = _MODEL.run(prm, steps)
    res.traj = res.traj[::2] if len(res.traj) > 40 else res.traj  # keep memory modest
    return res


def run_ensemble(model: Model, cat: Catalogue, steps: int, seeds: int, scenarios: list[str] | None = None,
                 base_seed: int = 1, fixed_attention: bool = False, workers: int | None = None,
                 log=print) -> list[RunResult]:
    global _MODEL, _CAT
    _MODEL, _CAT = model, cat
    ids = scenarios or [s["id"] for s in cat.scenarios["scenarios"]]
    jobs = [(sid, base_seed + 1000 * si + r, steps, fixed_attention) for si, sid in enumerate(ids) for r in range(seeds)]
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 1)))
    out: list[RunResult] = []
    if workers > 1 and "fork" in mp.get_all_start_methods():
        with mp.get_context("fork").Pool(workers) as pool:
            for i, res in enumerate(pool.imap(_one, jobs)):
                out.append(res)
                if log:
                    log(f"  run {i + 1}/{len(jobs)} ({res.scenario}): depth median {np.median(res.D):.0f}, "
                        f"leading edge {np.percentile(res.D, 95):.0f}")
    else:
        for i, job in enumerate(jobs):
            res = _one(job)
            out.append(res)
            if log:
                log(f"  run {i + 1}/{len(jobs)} ({res.scenario}): depth median {np.median(res.D):.0f}, "
                    f"leading edge {np.percentile(res.D, 95):.0f}")
    return out
