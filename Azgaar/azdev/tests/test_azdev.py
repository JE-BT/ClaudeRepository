"""Checks that need a 1.157+ save. Point AZDEV_TEST_MAP at one (Batan works):
    AZDEV_TEST_MAP="Azgaar/Batan/Batan 2026-11-11-19-43.map" python -m pytest tests"""
import csv
import os
from pathlib import Path

import numpy as np
import pytest

from azdev import catalogue
from azdev.delaunator import Delaunator, voronoi_cells
from azdev.development import DevelopmentField
from azdev.graph import PackGraph
from azdev.mapfile import AzgaarMap

MAP = os.environ.get("AZDEV_TEST_MAP")
needs_map = pytest.mark.skipif(not MAP, reason="set AZDEV_TEST_MAP to a .map file")


def test_catalogue_loads_clean():
    cat = catalogue.load()
    assert not cat.warnings
    assert len(set(cat.K)) == len(cat.K)
    for g in cat.new_goods:
        assert g["practice"] in cat.ki


@needs_map
def test_pack_and_development_port():
    m = AzgaarMap(MAP)
    pg = PackGraph(m)
    assert pg.n == m.cell_count
    dev = DevelopmentField(m, pg).generate()
    saved = np.asarray(m.cell("development"))
    assert np.mean(dev == saved) > 0.98
    assert np.abs(dev - saved).max() <= 3


def test_delaunator_port_matches_javascript():
    """Reference output from delaunator 5.1.0 (node) and the Generator's Voronoi walk on the same points:
    16 jittered lattice points as real cells, then a duplicate pair and a far point as pseudo-points."""
    pts = [[float(x * 10 + ((x * 7 + y * 3) % 5) * 0.7), float(y * 10 + ((x * 5 + y * 11) % 7) * 0.6)]
           for y in range(4) for x in range(4)] + [[2.5, 2.5], [2.5, 2.5], [40.0, 40.0]]
    d = Delaunator.from_points(pts)
    assert d.triangles == [10, 9, 14, 9, 13, 14, 13, 15, 14, 14, 11, 10, 9, 12, 13, 13, 18, 15, 15, 11, 14, 5, 8, 9,
                           9, 8, 12, 5, 9, 10, 6, 5, 10, 11, 6, 10, 5, 4, 8, 11, 7, 6, 18, 7, 11, 2, 1, 6, 6, 1, 5,
                           5, 16, 4, 12, 18, 13, 15, 18, 11, 3, 2, 6, 0, 16, 1, 1, 16, 5, 4, 0, 8, 7, 3, 6, 2, 0, 1,
                           18, 3, 7, 3, 0, 2, 16, 0, 4]
    assert d.halfedges == [28, 5, 11, 14, 8, 1, 17, 20, 4, 19, 35, 2, 26, 56, 3, 55, 57, 6, 59, 9, 7, 38, 24, 27, 22,
                           -1, 12, 23, 0, 31, 50, 29, 34, 41, 32, 10, 53, 71, 21, 43, 74, 33, 80, 39, 58, 77, 48, 61,
                           46, 68, 30, 67, 86, 36, -1, 15, 13, 16, 44, 18, 83, 47, 73, 84, 66, 76, 64, 51, 49, 85, -1,
                           37, 79, 62, 40, 82, 65, 45, -1, 72, 42, -1, 75, 60, 63, 69, 52]
    c, b = voronoi_cells(d, 16)
    assert c == [[1, 4], [2, 6, 5, 0], [6, 1, 0, 3], [6, 2], [5, 8, 0], [9, 8, 4, 1, 6, 10], [10, 5, 1, 2, 3, 7, 11],
                 [11, 6, 3], [5, 9], [10, 14, 13, 12, 8, 5], [14, 9, 5, 6, 11], [14, 10, 6, 7, 15], [9, 13],
                 [9, 14, 15, 12], [9, 10, 11, 15, 13], [13, 14, 11]]
    assert b == [1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1]


@needs_map
def test_pack_matches_cells_geojson():
    """The Cells GeoJSON export lists each pack cell's neighbours as the Generator holds them. The rebuilt
    pack must have the same neighbours in the same order (the order decides how coastal cells split)."""
    import json
    world = Path(MAP).name.split(" ")[0]
    exports = sorted(Path(MAP).parent.glob(f"{world} Cells *.geojson"))
    if not exports:
        pytest.skip("no Cells GeoJSON beside the map")
    features = json.loads(exports[-1].read_text(encoding="utf-8"))["features"]
    m = AzgaarMap(MAP)
    if len(features) != m.cell_count:
        pytest.skip("the newest Cells GeoJSON was exported from a different save")
    pg = PackGraph(m)
    neighbours = {f["properties"]["id"]: f["properties"]["neighbors"] for f in features}
    wrong = [i for i in range(pg.n) if pg.c[i].tolist() != neighbours[i]]
    assert not wrong, f"{len(wrong)} cells differ, first {wrong[:10]}"


@needs_map
def test_patch_keeps_every_other_field(tmp_path):
    m = AzgaarMap(MAP)
    out = tmp_path / "patched.map"
    m.write_patched(out, {1: m.fields[1]})
    assert out.read_bytes() == Path(MAP).read_bytes()
