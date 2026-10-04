"""Interactions, people, room purposes, the dungeon's heart, spiral stairs and placement."""
import unittest

from azork import placement, scenes, watabou, worlds
from azork.engine.game import Game
from tests.test_engine import walk
from tests.test_lania import HAVE_LANIA, ROOT


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = worlds.find("Lania", ROOT)

    def game(self, scene):
        if scene not in scenes.list_scenes(self.files):
            self.skipTest(f"scene {scene} needs files not present")
        g = Game(scenes.build(self.files, scene))
        g.intro()
        return g

    def thing(self, g, name):
        return next(t for t in g.w.things.values() if t.name == name)

    def test_taking_updates_the_room(self):
        g = self.game("dungeon:5")
        g.step("light lantern")
        walk(g, self.thing(g, "silver chess piece").location)
        self.assertIn("chess piece lies nearby", g.step("look"))
        g.step("take chess piece")
        after = g.step("look")
        self.assertNotIn("chess piece", after)
        self.assertIn("corpse of a knight", after)

    def test_needs_sleep_and_journal(self):
        g = self.game("dwelling:house_on_the_hill")
        rations = g.w.things["rations"]
        before = rations.props["uses"]
        g.step("eat")
        self.assertEqual(rations.props["uses"], before - 1)
        water = g.w.things["waterskin"].props["uses"]
        g.step("drink")
        self.assertEqual(g.w.things["waterskin"].props["uses"], water - 1)
        g.step("write Swangel KNOWS. Ask about Cryspell.")
        self.assertIn("Swangel KNOWS. Ask about Cryspell.", g.step("journal"))
        t0 = g.w.minutes
        g.step("knock. n. nw. w. sleep")
        self.assertGreater(g.w.minutes - t0, 6 * 60)

    def test_barging_in_is_noticed(self):
        g = self.game("dwelling:house_on_the_hill")
        out = g.step("open door. n. nw")
        self.assertIn("travellers knock", out)
        g2 = self.game("dwelling:house_on_the_hill")
        self.assertNotIn("travellers knock", g2.step("knock on door. open door. n. nw"))

    def test_people_topics_and_gifts(self):
        g = self.game("dwelling:house_on_the_hill")
        g.step("knock. n")
        self.assertIn("coins", g.step("search pegs"))
        g.step("take coins. nw")
        self.assertIn("Thin, quiet", g.step("ask swangel about the follower"))
        self.assertIn("room paid", g.step("give coins to swangel"))
        self.assertTrue(g.w.flags.get("room_paid"))
        self.assertIn("No.", g.step("invite swangel"))

    def test_rooms_have_purposes_and_furnishings(self):
        g = self.game("dwelling:house_on_the_hill")
        names = {r.name for r in g.w.rooms.values()}
        self.assertTrue({"Guest room", "Trapper's room", "Children's room", "Kitchen"} <= names)
        kitchen = next(r for r in g.w.rooms.values() if r.name == "Kitchen")
        here = {t.name for t in g.w.contents(kitchen.id)}
        self.assertTrue(here & {"iron stove", "absence"})

    def test_dungeon_heart_and_hints(self):
        g = self.game("dungeon:5")
        wyrm = self.thing(g, "giant wyrm")
        lair = g.w.rooms[wyrm.location]
        self.assertEqual(lair.purpose, "lair")
        self.assertEqual(lair.depth, max(r.depth for r in g.w.rooms.values()))
        g.step("n. d. light lantern")
        self.assertIn("scorched gate", g.step("ask druid about the wyrm"))
        g.w.player = wyrm.location
        self.assertIn("You have died", g.step("knock"))
        shrine = self.game("dungeon:6")
        cube = next(t for t in shrine.w.things.values() if "story" in t.flags)
        self.assertEqual(shrine.w.rooms[cube.location].purpose, "vault")

    def test_drink_from_pool(self):
        g = self.game("dungeon:5")
        g.step("light lantern")
        walk(g, self.thing(g, "key").location)
        self.assertIn("drink", g.step("drink from pool").lower())

    def test_placement_finds_fatewell(self):
        town = watabou.load(self.files.map_path.parent / "bayfshear.json")
        house = next(f for f in self.files.dwellings() if f.burg == 172)
        best = placement.rank(town, house.path, 3)[0]
        self.assertEqual(best["building"], 14)
        self.assertGreater(best["shape"], 0.95)


@unittest.skipUnless((ROOT / "Presia").is_dir(), "Presia not present")
class PresiaTests(unittest.TestCase):
    def test_spiral_stair_and_default_kit(self):
        files = worlds.find("Presia", ROOT)
        scene = next((s for s in scenes.list_scenes(files) if s.startswith("dwelling:")), None)
        if not scene:
            self.skipTest("no placed Presia dwelling")
        g = Game(scenes.build(files, scene))
        self.assertIn("journal", g.step("i"))
        notes = {e.note for r in g.w.rooms.values() for e in r.exits.values()}
        self.assertIn("spiral stair", notes)


if __name__ == "__main__":
    unittest.main()
