"""Checks that need a 1.157+ save. Point AZDEV_TEST_MAP at one (Batan works):
    AZDEV_TEST_MAP="Azgaar/Batan/Batan 2026-11-11-19-43.map" python -m pytest tests"""
import csv
import os
from pathlib import Path

import numpy as np
import pytest

from azdev import catalogue
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


@needs_map
def test_patch_keeps_every_other_field(tmp_path):
    m = AzgaarMap(MAP)
    out = tmp_path / "patched.map"
    m.write_patched(out, {1: m.fields[1]})
    assert out.read_bytes() == Path(MAP).read_bytes()
