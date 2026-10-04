"""The hex road, towns street by street, buildings on entry, carriers, details, directions, story direction."""
import shutil
import tempfile
import unittest
from pathlib import Path

from azork import hexgrid, ledger, ledger_export, scenes, style, towns, wild, worlds
from azork.campaign import Campaign
from azork.engine.game import Game
from azork.runner import Runner
from tests.test_lania import HAVE_LANIA, ROOT


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = worlds.find("Lania", ROOT)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.camp, _ = Campaign.new(self.files, "t", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_hex_grid_matches_the_overlay(self):
        g = hexgrid.HexGrid.from_map(self.files.map)
        self.assertAlmostEqual(g.miles, 5.0, places=3)          # 5-mile hexes on the new map
        for h in [(0, 0), (10, 7), (123, 45)]:
            self.assertEqual(g.at(*g.centre(h)), h)
        a = (10, 7)
        for d in hexgrid.NEIGH:
            self.assertAlmostEqual(abs(complex(*g.centre(g.neighbour(a, d))) - complex(*g.centre(a))), g.w, places=2)

    def test_onward_is_one_hex_and_costs_terrain_time(self):
        r = Runner(self.files, self.camp)
        r.start(True)
        start = r.game.w.player
        out = r.step("onward")
        self.assertIn("hours", out)
        here = r.game.w.player
        g = wild.wild_of(self.camp).grid
        a, b = g.parse(start[2:]), g.parse(here[2:])
        self.assertIn(b, g.neighbours(a).values())
        self.assertLess(self.camp.t, 5)

    def test_camp_by_day_rests_by_night_sleeps(self):
        r = Runner(self.files, self.camp)
        r.start(True)
        self.assertIn("rest for an hour", r.step("camp"))
        r.game.tick(11 * 60)
        self.assertIn("until dawn", r.step("camp"))

    def test_town_streets_hide_buildings_until_searched(self):
        g = Game(scenes.build(self.files, "town:121", self.camp), None, self.camp)
        g.intro()
        t = g.w.flags["town"]
        self.assertTrue(all(b.get("node") for b in t["buildings"].values()))
        self.assertIn("inn", t["places"])
        street = next(k for k, r in g.w.rooms.items() if r.purpose == "street" and
                      any(b["node"] == k and not b.get("exit") for b in t["buildings"].values()))
        g.w.player = street
        hidden = [i for i, b in t["buildings"].items() if b["node"] == street and not b.get("exit")]
        self.assertIn("take note of", g.step("search"))
        self.assertTrue(all(t["buildings"][i].get("exit") for i in hidden))

    def test_directions_and_entering_a_building(self):
        g = Game(scenes.build(self.files, "town:121", self.camp), None, self.camp)
        g.intro()
        folk = next(x for x in g.w.things.values() if "local" in x.flags)
        g.w.player = folk.location
        out = g.step(f"ask {folk.name.lower()} about the inn")
        self.assertIn("Go ", out)
        inn = g.w.flags["town"]["places"]["inn"]
        g.w.player = g.w.flags["town"]["buildings"][inn]["node"]
        out = g.step("enter " + g.w.flags["town"]["buildings"][inn]["exit"])
        self.assertIn("Taproom", out)
        self.assertTrue(any("innkeeper" in x.nouns for x in g.w.contents(g.w.player)))

    def test_details_become_things(self):
        g = Game(scenes.build(self.files, "town:121", self.camp), None, self.camp)
        g.intro()
        inn = g.w.flags["town"]["places"]["inn"]
        g.w.player = g.w.flags["town"]["buildings"][inn]["node"]
        g.step("enter " + g.w.flags["town"]["buildings"][inn]["exit"])
        self.assertIn("part of the long bar", g.step("examine cups"))
        self.assertIn("You take a cup", g.step("take cups"))

    def test_runner_asks_for_building_interiors(self):
        r = Runner(self.files, self.camp)
        r.start(True)
        out = r.enter("town:121")
        self.assertIn("key buildings have no interiors", out)
        r.step("generate")
        t = r.game.w.flags["town"]
        street = next(k for k, rm in r.game.w.rooms.items() if rm.purpose == "street" and
                      any(b["node"] == k and not b.get("role") for b in t["buildings"].values()))
        r.game.w.player = street
        r.step("search")
        idx = next(i for i, b in t["buildings"].items() if b["node"] == street and b.get("exit") and not b.get("role"))
        out = r.step("enter " + t["buildings"][idx]["exit"])
        self.assertIn("[Paused]", out)
        self.assertIn(f"building {idx}", out)
        out = r.step("generate")
        self.assertTrue(r.game.w.player.startswith(f"b{idx}:"))

    def test_meeting_goal_becomes_concrete_in_town(self):
        g = Game(scenes.build(self.files, "town:172", self.camp), None, self.camp)
        out = " ".join(g.intro().split())
        self.assertIn("Fatewell house", out)               # the contact lodges in the placed house
        self.assertIn("[[goal]]New goal", out)

    def test_carriers_offer_passage(self):
        g = Game(scenes.build(self.files, "town:121", self.camp), None, self.camp)
        g.intro()
        carrier = next((x for x in g.w.things.values() if "carrier" in x.flags), None)
        self.assertIsNotNone(carrier)
        g.w.player = carrier.location
        g.w.things["purse"].props["coins"] = 500
        self.story_papers = self.camp.story.flags.setdefault("papers", True)
        out = g.step("book passage with " + carrier.name.lower())
        self.assertIn("climb aboard", out)
        self.assertIn("ride", g.w.flags["transition"])

    def test_colours_and_recap(self):
        text = style.mark("hook", "main") + " " + style.mark("side", "side")
        self.assertIn("\x1b[38;5;178m", style.render(text, True))
        self.assertEqual(style.render(text, False), "hook side")
        r = Runner(self.files, self.camp)
        out = r.start(True)
        self.assertIn("Goals:", out)
        self.assertIn("The commission", r.step("recap"))

    def test_bounty_registration_gives_papers(self):
        g = Game(scenes.build(self.files, "town:121", self.camp), None, self.camp)
        g.intro()
        hall = g.w.flags["town"]["places"]["hall"]
        g.w.player = g.w.flags["town"]["buildings"][hall]["node"]
        g.step("enter " + g.w.flags["town"]["buildings"][hall]["exit"])
        clerk = g.w.things["clerk"]
        g.w.player = clerk.location
        self.assertIn("Writs are registered", g.step("ask clerk about the writ"))
        self.assertIn("Registered", g.step("give writ to clerk"))
        self.assertTrue(self.camp.story.flags.get("papers"))
        self.assertEqual(g.w.things["story:main:token"].location, "player")

    def test_ledger_links_story_document(self):
        main = self.tmp / self.files.main_ledger.name
        shutil.copy(self.files.main_ledger, main)
        g = Game(scenes.build(self.files, "dungeon:5", self.camp), None, self.camp)
        g.intro()
        ledger_export.export(main, g, "keep", None, self.camp)
        story = self.tmp / main.name.replace("_ledger", "_story")
        entry = ledger.parse(main).entries[-1]
        self.assertTrue(any(f.startswith("Story:") and story.name in f for f in entry.facts))


if __name__ == "__main__":
    unittest.main()
