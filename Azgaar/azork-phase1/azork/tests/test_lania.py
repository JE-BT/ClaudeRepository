"""Checks against the Lania world files and its ledger canon.

Run from the azork folder:  python -m unittest -v
Set AZORK_WORLDS to the Azgaar folder if it is not beside this project.
"""
import os
import unittest
from collections import defaultdict
from pathlib import Path

from azork import ledger, setup, watabou, worlds
from azork.cells import CellGeo
from azork.clock import daylight
from azork.journey import Journey
from azork.names import NameGenerator

ROOT = Path(os.environ.get("AZORK_WORLDS", Path(__file__).resolve().parents[2] / "Azgaar"))
HAVE_LANIA = (ROOT / "Lania").is_dir()


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class LaniaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = worlds.find("Lania", ROOT)
        cls.m = cls.w.map
        cls.j = Journey(cls.m)
        cls.dir = cls.w.map_path.parent

    # .map and cells ---------------------------------------------------------
    def test_map_loads_and_verifies(self):
        s = self.m.summary()
        self.assertEqual((s["pack_cells"], s["burgs"], s["version"]), (3022, 306, "1.153.1"))
        self.assertEqual(self.m.burg(172)["name"], "Bayfshear")
        self.assertEqual(self.m.burg(172)["cell"], 1091)

    def test_cells_geojson_agrees_with_map(self):
        geo = CellGeo(self.w.cells_path, self.m)
        self.assertEqual(geo.check_against(self.m), [])
        b = self.m.burg(172)
        cx, cy = geo.centroid[b["cell"]]
        self.assertLess(abs(cx - b["x"]) + abs(cy - b["y"]), 4)

    # journey plan against canon -----------------------------------------------
    def test_stage_lengths(self):
        self.assertEqual(len(self.j.stages), 13)
        self.assertAlmostEqual(self.j.stages[1].miles, 2587.1, delta=1)

    def test_border_crossing_canon(self):
        hits = [c for c in self.j.crossings()
                if c.stage == 1 and c.kind == "state" and c.before == "Adrer" and c.after == "Wolfrontia"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(268 <= hits[0].mile <= 373)
        self.assertEqual(hits[0].cell, 1024)

    def test_party_marker_canon(self):
        party = next(n for n in self.j.nearby(10) if n.kind == "marker" and n.id == 37)
        self.assertEqual(party.stage, 1)
        self.assertAlmostEqual(party.along_mi, 466, delta=2)
        self.assertAlmostEqual(party.offset_mi, 7, delta=0.5)

    def test_plan_clock_matches_journey_days(self):
        st = self.j.stages[1]
        self.assertTrue(self.j.label(self.j.when(1, 466), st.lat).startswith("day 13,"))  # Bayfshear
        birad = self.j.label(self.j.when(1, 356.5), st.lat)  # walking day 9, near dusk
        self.assertTrue(birad.startswith("day 10, 16") or birad.startswith("day 10, 17"), birad)

    def test_faster_sea_options_scale_difficulty(self):
        alts = {a["transport"]: a for a in self.j.alternatives(9, ["Rowboat", "Sailing boat", "Sailing Ship"])}
        self.assertEqual(alts["Sailing Ship"]["level"], "severe")
        self.assertLess(alts["Sailing boat"]["difficulty"], alts["Sailing Ship"]["difficulty"])

    def test_daylight_model(self):
        self.assertEqual(tuple(round(x) for x in daylight(0, 80)), (6, 18))
        dawn, dusk = daylight(51, 172)
        self.assertTrue(3.5 < dawn < 4.2 and 19.8 < dusk < 20.5)

    # Watabou files ------------------------------------------------------------
    def test_village_and_city(self):
        v = watabou.load(self.dir / "bayfshear.json")
        self.assertEqual(v.kind, "village")
        self.assertAlmostEqual(v.buildings[14].area, 279.0, delta=0.5)  # Fatewell house
        c = watabou.load(self.dir / "adrer.json")
        names = {d["name"] for d in c.districts}
        self.assertTrue({"Night Reach", "Clay Court", "Greyrise Town"} <= names)

    def _fatewell(self):
        """The dwelling the ledger places in Bayfshear building 14; skip if its file is absent."""
        f = next((f for f in self.w.dwellings() if f.burg == 172 and f.building == 14), None)
        if f is None:
            self.skipTest(f"No dwelling placed at Bayfshear building 14 in {self.dir} "
                          "(the ledger names house_on_the_hill.json)")
        return f

    def test_fatewell_house_canon(self):
        d = watabou.load(self._fatewell().path)
        by_name = {r.name: k for k, r in d.rooms.items() if r.floor == 0}
        lib = {d.rooms[k].name for k, kind in d.neighbours(by_name["Library"]) if k != "outside"}
        self.assertEqual(lib, {"Trophy room", "Room", "Hall"})  # the library is the hub
        kitchen = d.neighbours(by_name["Kitchen"])
        self.assertEqual([d.rooms[k].name for k, kind in kitchen if kind != "stairs"], ["Trophy room"])
        self.assertEqual(d.entrance, by_name["Hall"])

    def test_dungeon_sample(self):
        d = watabou.load(self.dir / "halls_of_the_diamond_king.json")
        self.assertEqual(d.title, "Halls of the Diamond King")
        adj = defaultdict(set)
        for a, b, _ in d.links:
            if b != "outside":
                adj[a].add(b)
                adj[b].add(a)
        seen, todo = {d.entrances[0]}, [d.entrances[0]]
        while todo:
            for n in adj[todo.pop()] - seen:
                seen.add(n)
                todo.append(n)
        self.assertEqual(len(seen), len(d.chambers))
        self.assertEqual(sum(len(c.notes) for c in d.chambers), 8)
        self.assertTrue(all(t == 3 for _, b, t in d.links if b == "outside"))

    # ledger, discovery, names, setup -------------------------------------------------
    def test_ledger_anchors(self):
        led = ledger.parse(self.w.main_ledger)
        self.assertEqual(len(led.entries), 10)
        cross = led.get("The border crossing")
        self.assertEqual([a.id for a in cross.anchors if a.kind == "cell"], [1025, 1024, 1023])
        fatewell = led.get("Fatewell house")
        self.assertIn(ledger.Anchor("building", 14, "bayfshear.json"), fatewell.anchors)
        self.assertEqual(fatewell.status, "draft")

    def test_discovery_assigns_files(self):
        house = self._fatewell()
        self.assertEqual(house.assigned_by in ("ledger", "manifest", "filename"), True)
        dungeons = {f.marker for f in self.w.watabou if f.kind == "dungeon"}
        self.assertIn(5, dungeons)
        self.assertEqual(self.w.problems, [])

    def test_names_are_reproducible(self):
        g = NameGenerator(self.m.namebase_overrides())
        a, b = g.name(35, "lania:barakhur"), g.name(35, "lania:barakhur")
        self.assertEqual(a, b)
        self.assertTrue(2 <= len(a) <= g.bases[35]["max"] + 3)

    def test_setup_requires_stops_canon_and_sites(self):
        _, reqs = setup.plan(self.w)
        req = {(r.kind, r.id): r for r in reqs if r.tier == "required"}
        for key in [("town", 5), ("town", 172), ("town", 4), ("town", 34), ("dungeon", 5), ("town", 195)]:
            self.assertIn(key, req)
        self.assertTrue(req[("town", 5)].present and req[("dungeon", 5)].present)
        msg = setup.expansion_message(self.w, req[("town", 4)])
        self.assertIn("krusetlev.json", msg)


if __name__ == "__main__":
    unittest.main()
