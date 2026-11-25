"""Port of the Generator's development field (src/model/society/development-generator.ts, v1.157+).

Used two ways: to check the port against the field saved in the .map, and to predict the field the
Generator will make after the new culture levels and biome offsets are uploaded and Development is
regenerated. The port is exact when the inputs are: same seed, same pack, same levels.
"""
from __future__ import annotations

import math

import numpy as np

from .graph import PackGraph, js_round
from .mapfile import AzgaarMap

SMOOTHING = 2
NOISE = 9
WAVES = 3
RIVER = 1
COAST = 1
MIN_BURG = 5
DEFAULT_DEVELOPMENT = 33
WILDLANDS_DEVELOPMENT = 3
CULTURE_TYPE_DEVELOPMENT = {"Generic": 0, "River": 2, "Naval": 3, "Lake": 1, "Highland": -2, "Nomadic": -3,
                            "Hunting": -4}
TRIBAL_DEVELOPMENT = 12
PRODUCTIVITY_START = 30
U32 = 0xFFFFFFFF


def imul(a: int, b: int) -> int:
    """Math.imul as an unsigned 32-bit result."""
    return ((a & U32) * (b & U32)) & U32


def hash_string(text: str) -> int:
    h = 2166136261
    for ch in text.encode("utf-16-le").decode("utf-16-le"):
        h = imul(h ^ ord(ch), 16777619)
    return h & U32


def culture_level(culture: dict, override: dict[int, int] | None = None) -> float:
    """A culture's level at its center: own level plus its way of life (Development.ofCulture)."""
    if not culture.get("i"):
        return WILDLANDS_DEVELOPMENT
    level = (override or {}).get(culture["i"], culture.get("development", DEFAULT_DEVELOPMENT))
    return level + CULTURE_TYPE_DEVELOPMENT.get(culture.get("type", "Generic"), 0)


class DevelopmentField:
    def __init__(self, m: AzgaarMap, pg: PackGraph):
        self.m, self.pg = m, pg
        self._noise = self._make_noise()

    def _make_noise(self) -> np.ndarray:
        pts = self.pg.p
        min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
        size = max(pts[:, 0].max() - min_x, pts[:, 1].max() - min_y) or 1
        seed = hash_string(str(self.m.seed))

        def lattice(x: int, y: int) -> float:
            h = (seed ^ imul(x, 374761393) ^ imul(y, 668265263)) & U32
            h = imul(h ^ (h >> 13), 1274126177)
            return (((h ^ (h >> 16)) & U32) / 4294967295) * 2 - 1

        def smooth(t: float) -> float:
            return t * t * (3 - 2 * t)

        def value(x: float, y: float) -> float:
            ix, iy = math.floor(x), math.floor(y)
            fx, fy = smooth(x - ix), smooth(y - iy)
            top = lattice(ix, iy) + (lattice(ix + 1, iy) - lattice(ix, iy)) * fx
            bottom = lattice(ix, iy + 1) + (lattice(ix + 1, iy + 1) - lattice(ix, iy + 1)) * fx
            return top + (bottom - top) * fy

        out = np.empty(len(pts))
        for i, (px, py) in enumerate(pts):
            x = (px - min_x) / size * WAVES
            y = (py - min_y) / size * WAVES
            out[i] = NOISE * (0.67 * value(x, y) + 0.33 * value(x * 2 + 17, y * 2 + 17))
        return out

    def offsets(self, biome_offsets: dict[int, int] | None = None) -> np.ndarray:
        """Per cell: biome offset plus river and coast points (everything but the culture level)."""
        m, pg = self.m, self.pg
        biomes = m.data["biomes"]
        boff = np.array([(biome_offsets or {}).get(b["i"], b.get("development", 0) or 0) for b in biomes], float)
        cb = np.asarray(m.cell("biome"))
        water = (np.asarray(m.cell("river")) > 0).astype(float) * RIVER + (pg.harbor > 0).astype(float) * COAST
        return boff[np.minimum(cb, len(boff) - 1)] + water

    def generate(self, levels: dict[int, int] | None = None, biome_offsets: dict[int, int] | None = None
                 ) -> np.ndarray:
        m, pg = self.m, self.pg
        n = pg.n
        cultures = m.data["cultures"]
        lv = np.array([culture_level(c, levels) if isinstance(c, dict) and not c.get("removed") else 0
                       for c in cultures], float)
        cc = np.asarray(m.cell("culture"))
        land = pg.land
        field = np.zeros(n)
        cl = np.where(cc < len(lv), lv[np.minimum(cc, len(lv) - 1)], lv[0])
        field[land] = (cl + self.offsets(biome_offsets))[land]
        current = field
        for _ in range(SMOOTHING):
            nxt = np.zeros(n)
            for i in np.nonzero(land)[0]:
                nb = pg.c[i]
                nb = nb[land[nb]]
                nxt[i] = (current[i] + current[nb].sum()) / (1 + len(nb))
            current = nxt
        pop = np.asarray(m.cell("pop"))
        burg = np.asarray(m.cell("burg"))
        dev = np.zeros(n, dtype=np.int16)
        peopled = land & ((pop > 0) | (burg > 0))
        for i in np.nonzero(peopled)[0]:
            least = MIN_BURG if burg[i] else 1
            dev[i] = max(least, min(100, int(js_round(current[i] + self._noise[i]))))
        return dev


def productivity(level: float) -> float:
    return max(1.0, level / PRODUCTIVITY_START)
