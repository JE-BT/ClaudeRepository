"""Engine checks: parser, scenes built from Lania data, puzzles, undo, saves and ledger export."""
import shutil
import tempfile
import unittest
from collections import deque
from pathlib import Path

from azork import ledger, ledger_export, scenes, worlds
from azork.engine.game import Game
from azork.engine.parser import parse
from tests.test_lania import HAVE_LANIA, ROOT


class ParserTests(unittest.TestCase):
    def test_forms(self):
        c = parse("pick up the brass key")
        self.assertEqual((c.verb, c.words), ("take", ["brass", "key"]))
        c = parse("put rope in basket")
        self.assertEqual((c.verb, c.words, c.prep, c.iwords), ("put", ["rope"], "in", ["basket"]))
        self.assertEqual(parse("ne").direction, "northeast")
        self.assertEqual(parse("go up the stairs").direction, "up")
        c = parse("drop all except rope")
        self.assertTrue(c.all)
        self.assertEqual(c.except_words, ["rope"])
        self.assertEqual(parse("look at mirror").verb, "examine")
        self.assertEqual(parse("look in mirror").verb, "lookin")
        self.assertEqual(parse("put down tar").verb, "drop")


def walk(game: Game, target: str) -> None:
    """Drive the player to a room with movement and SEARCH commands only (no teleporting)."""
    w = game.w
    start = w.player
    prev = {start: None}
    todo = deque([start])
    while todo:
        r = todo.popleft()
        for d, e in w.rooms[r].exits.items():
            door = w.things.get(e.door) if e.door else None
            if door and ("barred" in door.flags or "locked" in door.flags or
                         ("portcullis" in door.flags and "raised" not in door.flags)):
                continue
            if e.to in w.rooms and e.to not in prev:
                prev[e.to] = (r, d, e.hidden)
                todo.append(e.to)
    if target not in prev:
        raise AssertionError(f"{target} is not reachable from {start}")
    path, r = [], target
    while prev[r]:
        r0, d, hidden = prev[r]
        path.append((d, hidden))
        r = r0
    for d, hidden in reversed(path):
        if hidden:
            game.step("search")
        game.step(d)
    assert w.player == target, (w.player, target)


@unittest.skipUnless(HAVE_LANIA, f"Lania not found under {ROOT}")
class SceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = worlds.find("Lania", ROOT)

    def game(self, scene, save_dir=None):
        if scene not in scenes.list_scenes(self.files):
            self.skipTest(f"scene {scene} needs files not present")
        return Game(scenes.build(self.files, scene), save_dir)

    def room_named(self, g, name):
        return next(k for k, r in g.w.rooms.items() if r.name == name)

    def test_fatewell_walk(self):
        g = self.game("dwelling:house_on_the_hill")
        self.assertIn("day 13", g.intro())                       # the ledger's journey day
        self.assertIn("travelling light", g.step("i"))            # 14.2 kg starting kit
        self.assertIn("Library", g.step("open door. n. nw"))
        self.assertIn("haven't decided", g.step("talk to swangel"))
        kitchen = g.w.rooms[self.room_named(g, "Kitchen")]
        self.assertEqual({g.w.rooms[e.to].name for d, e in kitchen.exits.items() if d != "down"}, {"Trophy room"})
        self.assertIn("laden", g.step("take book"))
        self.assertIn("light", g.step("drop book"))
        g.step("ne. w. d")
        self.assertIn("pitch dark", g.step("look"))
        self.assertIn("Cellar", g.step("light lantern"))
        self.assertIn("trapper", g.step("s"))

    def test_dungeon_secret_door_and_mirror(self):
        g = self.game("dungeon:5")
        g.step("n. d. light lantern")
        self.assertIn("hidden door to the south", g.step("search"))
        mirror_room = next(t.location for t in g.w.things.values() if t.name == "wall mirror")
        walk(g, mirror_room)
        self.assertIn("tarnished frame", g.step("examine mirror"))
        self.assertIn("You have died", g.step("look in mirror"))
        self.assertIn("You are dead", g.step("n"))
        self.assertIn("undone", g.step("undo"))
        self.assertFalse(g.w.dead)

    def test_key_opens_the_gate(self):
        g = self.game("dungeon:5")
        g.step("light lantern")
        key = next(t for t in g.w.things.values() if t.name == "key")
        gate = next(t for t in g.w.things.values() if "lockable" in t.flags)
        walk(g, key.location)
        self.assertIn("Taken", g.step("take key"))
        walk(g, gate.props["rooms"][0])
        self.assertIn("unlocked", g.step("unlock gate"))
        before = g.w.player
        g.step("e")
        self.assertNotEqual(g.w.player, before)

    def test_barred_door_holds(self):
        g = self.game("dungeon:5")
        barred = next(t for t in g.w.things.values() if "barred" in t.flags)
        g.w.player = barred.props["rooms"][0]
        g.step("light lantern")
        d = next(d for d, e in g.w.rooms[g.w.player].exits.items() if e.door == barred.id)
        self.assertIn("barred", g.step(d))

    def test_placed_key_when_notes_name_none(self):
        g = self.game("dungeon:7")
        key = g.w.things.get("dgn:key")
        self.assertIsNotNone(key)
        self.assertEqual(key.provenance, "new")
        self.assertTrue(key.unlocks)

    def test_lantern_burns_out(self):
        g = self.game("dungeon:5")
        g.step("light lantern")
        g.w.things["lantern"].props["fuel"] = 15
        out = g.step("wait") + g.step("wait")
        self.assertIn("burning low", out)
        self.assertIn("goes out", out)

    def test_save_and_restore(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            g = self.game("dungeon:5", tmp)
            g.step("drop rope. save one")
            g.step("take rope")
            self.assertEqual(g.w.things["rope"].location, "player")
            self.assertIn("Restored", g.step("restore one"))
            self.assertEqual(g.w.things["rope"].location, "outside")
        finally:
            shutil.rmtree(tmp)

    def test_ledger_export_keep_fork_discard(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            main = tmp / self.files.main_ledger.name
            shutil.copy(self.files.main_ledger, main)
            original = main.read_bytes()
            g = self.game("dungeon:5")
            g.step("drop tar. n")
            self.assertIsNone(ledger_export.export(main, g, "discard"))
            self.assertEqual(main.read_bytes(), original)
            fork = ledger_export.export(main, g, "fork", "test")
            self.assertEqual(fork.name, main.stem + ".test.md")
            self.assertEqual(main.read_bytes(), original)
            ledger_export.export(main, g, "keep")
            text = main.read_bytes().decode()
            self.assertEqual("\r\n" in original.decode(), "\r\n" in text)
            entry = ledger.parse(main).entries[-1]
            self.assertEqual(entry.status, "draft")
            self.assertTrue(any("pot of tar" in f for f in entry.facts))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
