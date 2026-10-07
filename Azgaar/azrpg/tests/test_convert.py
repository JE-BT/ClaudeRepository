"""Converter tests on the Pyeongak test world.

Run from Azgaar/azrpg:  python -m unittest
The world folder is found at ../Pyeongak (the repo layout) or at $AZRPG_REPO/Pyeongak.
"""
import gzip
import json
import os
import struct
import unittest
from pathlib import Path

import numpy as np

from azrpg.build import world_files
from azrpg.cells import CellGeo
from azrpg.mapfile import AzgaarMap
from azrpg.pack import PackBuilder
from azrpg.raster import Raster
from azrpg.tilegrid import TileGrid

REPO = Path(os.environ.get("AZRPG_REPO", Path(__file__).resolve().parents[2]))
HAVE = (REPO / "Pyeongak").is_dir()


@unittest.skipUnless(HAVE, "Pyeongak world files not found")
class TestPyeongak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map_path, cls.cells_path = world_files(REPO, "Pyeongak")
        cls.m = AzgaarMap(cls.map_path)
        cls.geo = CellGeo(cls.cells_path, cls.m)
        cls.g = TileGrid.from_map(cls.m)
        cls.r = Raster(cls.m, cls.geo, cls.g, seed=1).build()

    def test_cells_file_found_by_content(self):
        self.assertIn("Cells", self.cells_path.name)
        self.assertEqual(self.geo.check_against(self.m), [])

    def test_grid_matches_overlay(self):
        self.assertAlmostEqual(self.g.size, 1.25)
        self.assertAlmostEqual(self.g.miles, 6.25)
        self.assertEqual((self.g.cols, self.g.rows), (1537, 754))
        self.assertLessEqual(self.g.ox, 0)
        self.assertGreater(self.g.ox, -self.g.size)

    def test_land_agrees_with_cells(self):
        water = np.array([self.geo.is_water(i) for i in range(len(self.geo))])
        self.assertTrue(np.array_equal(~water[self.r.cell], self.r.land))

    def test_burg_tiles_hold_their_burg(self):
        for b in self.m.live_burgs():
            c, r = self.g.at(b["x"], b["y"])
            self.assertEqual(int(self.r.cell[r, c]), b["cell"], b["name"])

    def test_links_are_symmetric(self):
        for arr, shift in ((self.r.conn_route, 0), (self.r.conn_route, 4), (self.r.conn_water, 0), (self.r.conn_water, 4)):
            b = (arr >> shift) & 15
            e, w_ = (b & 2) > 0, (b & 8) > 0
            s, n = (b & 4) > 0, (b & 1) > 0
            self.assertTrue(np.array_equal(e[:, :-1], w_[:, 1:]))
            self.assertTrue(np.array_equal(s[:-1], n[1:]))

    def test_rivers_and_routes_drawn(self):
        self.assertEqual(self.r.report["rivers drawn"], 186)
        self.assertEqual(self.r.report["routes drawn"], {"roads": 16, "trails": 223, "searoutes": 86})
        self.assertFalse(((self.r.conn_water >> 4) > 0)[~self.r.land].sum() > 400)  # river links stay on land, bar mouths

    def test_pack_round_trip(self):
        blob = PackBuilder(self.map_path, self.cells_path).build()
        raw = gzip.decompress(blob)
        self.assertEqual(raw[:4], b"AZRP")
        n = struct.unpack("<I", raw[4:8])[0]
        meta = json.loads(raw[8:8 + n])
        tiles = meta["grid"]["cols"] * meta["grid"]["rows"]
        for name, r in meta["rasters"].items():
            self.assertEqual(r["length"], tiles * (2 if r["type"] == "u16" else 1), name)
        self.assertEqual(len(meta["journeys"][0]["segments"]), 11)
        self.assertEqual(len(meta["cells"]["biome"]), 3877)
        self.assertLess(len(blob), 2_000_000)


if __name__ == "__main__":
    unittest.main()
