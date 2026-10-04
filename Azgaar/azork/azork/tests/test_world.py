"""Phases 3 and 4: the road, towns, trade, the whole-game runner, prompts, and the story documents."""
import shutil
import tempfile
import unittest
from pathlib import Path

from azork import ledger, ledger_export, overworld, scenes, worlds
from azork.campaign import Campaign
from azork.engine.game import Game
from azork.runner import Runner
from tests.test_lania import HAVE_LANIA, ROOT


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
def walk_until(r, test, limit=15):
    out = ""
    for _ in range(limit):
        if test(r.game.w.rooms[r.game.w.player]):
            return out
        out += r.step("onward") + "\n"
    raise AssertionError("never got there")


def walk_to(r, name, limit=12):
    out = ""
    for _ in range(limit):
        if r.game.w.rooms[r.game.w.player].name == name:
            return out
        out += r.step("onward") + "\n"
    raise AssertionError(f"never reached {name}")


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = worlds.find("Lania", ROOT)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.camp, _ = Campaign.new(self.files, "t", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_waypoints_follow_the_journey(self):
        pts = overworld.waypoints(self.camp)
        order = [(p["pos"][0], p["pos"][1]) for p in pts]
        self.assertEqual(order, sorted(order))
        names = [p["name"] for p in pts]
        self.assertIn("Khara", names)
        self.assertIn("Halls of the Diamond King", names)
        detour = [p for p in pts if "Bayfshear" in [pl["name"] for pl in p["places"] if pl.get("detour")]]
        self.assertEqual(len(detour), 1)

    def test_travel_costs_time_food_and_passes_beats(self):
        r = Runner(self.files, self.camp)
        r.road()
        out = walk_to(r, "Birad")
        self.assertIn("You travel for", out)
        self.assertIn("Into Wolfrontia", out)
        self.assertGreater(self.camp.t, 24)
        self.assertLess(r.game.w.things["rations"].props["uses"], 14)

    def test_town_scene_and_trade(self):
        g = Game(scenes.build(self.files, "town:121"))
        g.intro()
        names = {r.name for r in g.w.rooms.values()}
        self.assertTrue({"Main street", "Taproom", "Guild hall"} <= names)
        g.w.player = next(k for k, r in g.w.rooms.items() if r.name == "Taproom")
        self.assertIn("coins", g.step("wares"))
        purse = g.w.things["purse"].props["coins"]
        self.assertIn("You buy", g.step("buy torch"))
        self.assertLess(g.w.things["purse"].props["coins"], purse)
        self.assertIn("You sell", g.step("sell torch"))

    def test_custom_exits_into_buildings(self):
        g = Game(scenes.build(self.files, "town:172"))
        g.intro()
        g.w.player = "main"
        self.assertIn("Taproom", g.step("enter inn"))
        house = [r for r in g.w.rooms.values() if r.area == "Fatewell house"]
        self.assertTrue(house)  # the placed dwelling is part of Bayfshear

    def test_runner_enters_and_leaves_places(self):
        r = Runner(self.files, self.camp)
        r.road()
        walk_until(r, lambda room: any(p["name"] == "Bayfshear" for p in room.props.get("places", [])))
        out = r.step("visit bayfshear")       # a detour off the road
        self.assertIn("Bayfshear", out)
        self.assertEqual(r.game.w.scene, "town:172")
        self.assertIn("road", r.step("out"))
        self.assertTrue(r.game.w.flags.get("overworld"))
        self.assertGreater(self.camp.delay(), 1)   # the detour cost time

    def test_dwelling_prompt_or_generate(self):
        self.camp.policy = "ask"
        side = scenes.towns.NeedDwelling({"name": "Okh-Khog", "i": 121}, "someone")
        self.assertIn("Okh-Khog", str(side))
        r = Runner(self.files, self.camp)
        r.road()
        # an unplanned town asks first; GENERATE makes it up
        unplanned = next(b for b in self.files.map.live_burgs() if b["i"] not in self.files.towns())
        out = r.enter(f"town:{unplanned['i']}")
        self.assertIn("[Paused]", out)
        out = r.step("generate")
        self.assertIn(unplanned["name"], out)
        self.assertIn(unplanned["i"], self.camp.generated)

    def test_missed_stop_means_no_warning(self):
        main = self.camp.story.line("main")
        stop = next(p for p in main.phases if p.id == "stop2")
        hazard = next(p for p in main.phases[main.phases.index(stop):] if p.id.startswith(("border", "zone")))
        self.assertIn(f"warned:{hazard.id}", stop.effects.get("flags", {}))
        self.assertIn("luck", hazard.effects)

    def test_planted_hooks(self):
        plants = self.camp.story.line("plants")
        self.assertEqual({e.spec["plant"] for e in plants.elements.values()}, {"heirloom", "letter"})

    def test_ledger_links_story_document(self):
        main = self.tmp / self.files.main_ledger.name
        shutil.copy(self.files.main_ledger, main)
        g = Game(scenes.build(self.files, "dungeon:5", self.camp), None, self.camp)
        g.intro()
        ledger_export.export(main, g, "keep", None, self.camp)
        story = self.tmp / main.name.replace("_ledger", "_story")
        self.assertTrue(story.exists())
        entry = ledger.parse(main).entries[-1]
        self.assertTrue(any(f.startswith("Story:") and story.name in f for f in entry.facts))
        self.assertIn("| The commission | done |", story.read_text())
        self.assertNotIn("| The commission |", main.read_text())   # details stay out of the ledger


if __name__ == "__main__":
    unittest.main()
