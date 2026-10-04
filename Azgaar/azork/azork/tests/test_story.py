"""The story: the main arc from the journey, campaigns between scenes, leads, side stories, endings."""
import shutil
import tempfile
import unittest
from pathlib import Path

from azork import scenes, worlds
from azork.campaign import Campaign
from azork.engine.game import Game
from tests.test_engine import walk
from tests.test_lania import HAVE_LANIA, ROOT


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class StoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = worlds.find("Lania", ROOT)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.camp, self.opening = Campaign.new(self.files, "test", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def play(self, scene):
        if scene not in scenes.list_scenes(self.files):
            self.skipTest(f"scene {scene} needs files not present")
        g = Game(scenes.build(self.files, scene, self.camp), None, self.camp)
        return g, g.intro()

    def test_arc_follows_the_journey(self):
        main = self.camp.story.line("main")
        titles = [p.title for p in main.phases]
        for t in ("The commission", "Into Wolfrontia", "The meeting at Bayfshear", "Camp at Okh-Khog",
                  "Bounty posted in Krusetlev", "Bounty posted in Thalasha", "The burden", "Kaharlale"):
            self.assertIn(t, titles)
        self.assertLess(titles.index("Into Wolfrontia"), titles.index("The meeting at Bayfshear"))
        climax = main.phases[-1]
        self.assertEqual(climax.requires, [["story:main:cargo", "clue"]])
        self.assertEqual(self.camp.tokens["deadline"], 373)
        self.assertIn("Krusetlev and Thalasha", self.opening[0])        # the Lania overlay premise
        self.assertEqual({s.id for s in self.camp.story.storylines if s.kind == "lead"}, {"lead5", "lead6", "lead7"})

    def test_meeting_point_and_border(self):
        g, intro = self.play("dwelling:house_on_the_hill")
        self.assertIn("Into Wolfrontia", intro)
        contact = g.w.things["story:main:contact"]
        self.assertEqual(g.w.rooms[contact.location].name, "Guest room")
        g.w.player = contact.location
        out = g.step("talk to " + contact.name.lower())
        self.assertIn("The meeting at Bayfshear", out)
        self.assertEqual(self.camp.story.score, 15)
        self.assertIn("score is 15", g.step("score"))
        self.assertIn("grave-chains", g.step("goals") + out)

    def test_lost_time_carries_between_scenes(self):
        g, _ = self.play("dwelling:house_on_the_hill")
        g.step("wait. wait. wait. wait. wait. wait")
        self.camp.leave(g.w)
        self.assertGreater(self.camp.delay(), 2)                       # the detour and the waiting
        self.assertIn("behind the plan", g.step("schedule"))
        g.step("drop rope")
        self.camp.leave(g.w)
        g2, _ = self.play("dungeon:5")
        self.assertNotIn("rope", g2.w.things)                          # left in Bayfshear
        self.assertIn("bounty writ", g2.step("i"))

    def test_lead_clue_in_the_heart(self):
        g, intro = self.play("dungeon:5")
        clue = g.w.things["story:lead5:clue"]
        self.assertEqual(g.w.rooms[clue.location].depth, max(r.depth for r in g.w.rooms.values()))
        g.w.player = clue.location
        g.step("light lantern")
        out = g.step("take tablet")
        self.assertIn("What lies deepest", out)
        self.assertTrue(self.camp.story.flags.get("clue"))

    def test_side_story_from_a_dying_man(self):
        g, _ = self.play("dungeon:6")
        halfling = next(t for t in g.w.things.values() if "dying" in t.adjectives)
        g.w.player = halfling.location
        g.step("light lantern")
        out = g.step("talk to halfling")
        self.assertIn("A last request", out)
        self.assertIn("locket", g.step("i"))
        side = next(s for s in self.camp.story.storylines if s.kind == "side")
        kin = side.elements["kin"]
        self.assertIn("burg", kin.anchor)
        n = next(n for n in self.camp.journey.nearby(40) if n.kind == "burg" and n.id == kin.anchor["burg"])
        self.assertGreater((n.stage, n.along_mi), tuple(self.camp.pos))   # ahead on the road

    def test_deadline_ends_the_story(self):
        msgs = self.camp.story.notify({"type": "time", "t": 400 * 24})
        self.assertEqual(self.camp.story.ending["kind"], "failure")
        self.assertTrue(any("worthless" in m for m in msgs))

    def test_thirst_kills(self):
        g, _ = self.play("dwelling:house_on_the_hill")
        g.w.flags["last_drink"] = g.w.plan_t - 73
        self.assertIn("You have died", g.step("wait"))

    def test_campaign_round_trip(self):
        self.camp.save()
        again = Campaign.load(self.files, "test", self.tmp)
        self.assertEqual(again.story.max_score, self.camp.story.max_score)
        self.assertEqual([p.status for p in again.story.line("main").phases],
                         [p.status for p in self.camp.story.line("main").phases])


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class PickMapTests(unittest.TestCase):
    def test_render_and_save(self):
        import json
        import threading
        import urllib.request
        from azork import pickmap
        files = worlds.find("Lania", ROOT)
        house = next(f for f in files.dwellings() if f.burg == 172)
        html = pickmap.render(files.map_path.parent / "bayfshear.json", "Bayfshear", house.path, "Fatewell house")
        self.assertIn('data-i="14"', html)
        tmp = Path(tempfile.mkdtemp())
        try:
            manifest = tmp / "manifest.json"
            srv = pickmap.serve(html, lambda d: pickmap.save_placement(manifest, house.path.name, 172, d["building"],
                                                                      d["label"]), 0, False)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{srv.server_address[1]}/save"
            req = urllib.request.Request(url, data=json.dumps({"building": 14, "label": "Fatewell house"}).encode(),
                                         method="POST")
            self.assertIn("building 14", urllib.request.urlopen(req).read().decode())
            self.assertEqual(json.loads(manifest.read_text())["files"][house.path.name]["building"], 14)
            srv.server_close()
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
