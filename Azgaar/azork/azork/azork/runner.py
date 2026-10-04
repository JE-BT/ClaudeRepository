"""Play the whole game from a campaign: the road, and the places along it.

The runner moves the party between the overworld and scenes (towns, dungeons, houses), keeps
the campaign up to date at each change, and pauses to ask when a place needs a file the
repository does not have yet: provide it (and click its building on the map), let the game make
one up here, or always make them up.
"""
from __future__ import annotations

from . import overworld, scenes, towns, worlds
from .engine.game import Game


class Runner:
    def __init__(self, files, campaign, save_dir=None):
        self.files, self.campaign, self.save_dir = files, campaign, save_dir
        self.game: Game | None = None
        self.prompt: dict | None = None

    # -------------------------------------------------------------- worlds
    def _kit(self, w):
        c = self.campaign
        specs = c.inventory if c.inventory is not None else (scenes._content(self.files, "items.json") or
                                                             __import__("json").loads(scenes.DEFAULT_ITEMS.read_text()))["start_inventory"]
        for spec in specs:
            w.spawn(spec, "player", spec.get("id"))
        for spec in c.story.pending_gifts:
            if spec["id"] not in w.things:
                w.spawn(spec, "player", spec["id"])
        c.story.pending_gifts.clear()

    def road(self) -> str:
        w = overworld.build(self.campaign)
        self._kit(w)
        self.game = Game(w, self.save_dir, self.campaign)
        return self.game.intro()

    def enter(self, scene: str, policy: str | None = None) -> str:
        kind, _, ident = scene.partition(":")
        if kind == "town" and int(ident) not in self.files.towns() and int(ident) not in self.campaign.generated \
                and self.campaign.policy != "generate" and policy is None:
            burg = self.files.map.burg(int(ident))
            self.prompt = {"kind": "town", "scene": scene, "burg": burg}
            from . import cells, links
            gen, link = links.burg_link(self.files.map, cells.CellGeo(self.files.cells_path, self.files.map), burg)
            return (f"[Paused] {burg['name']} has no town plan yet.\n"
                    f"  PROVIDE: open {link}, export JSON, save it as {self.files.map_path.parent.name}/"
                    f"{burg['name'].lower()}.json, then type DONE.\n"
                    f"  GENERATE: make {burg['name']} up for now.   ALWAYS: make places up from now on.")
        try:
            w = scenes.build(self.files, scene, self.campaign, policy)
        except towns.NeedDwelling as need:
            self.prompt = {"kind": "dwelling", "scene": scene, "burg": need.burg}
            b = need.burg["name"]
            return (f"[Paused] {b} needs a house for {need.who}.\n"
                    f"  PROVIDE: in the {b} City Generator plan, click a building to open Dwellings, export JSON, save it "
                    f"in {self.files.map_path.parent.name}/, run  python -m azork pick {self.files.name} {b} --dwelling "
                    f"<file>  and click the same building; then type DONE.\n"
                    f"  GENERATE: make the house up.   ALWAYS: make houses up from now on.")
        self.game = Game(w, self.save_dir, self.campaign)
        return self.game.intro()

    # ---------------------------------------------------------------- input
    def step(self, line: str) -> str:
        if self.prompt:
            return self._answer(line.strip().lower())
        out = self.game.step(line)
        tr = self.game.w.flags.pop("transition", None)
        if tr and "enter" in tr:
            self.campaign.leave(self.game.w)
            out += "\n\n" + self.enter(tr["enter"])
        elif tr and tr.get("leave"):
            self.campaign.leave(self.game.w)
            self.campaign.save()
            out += "\n\n" + self.road()
        return out

    def _answer(self, word: str) -> str:
        p = self.prompt
        if word in ("generate", "g"):
            self.prompt = None
            self.campaign.generated.append(p["burg"]["i"])
            return self.enter(p["scene"], "generate")
        if word in ("always", "a"):
            self.prompt = None
            self.campaign.policy = "generate"
            return self.enter(p["scene"], "generate")
        if word in ("done", "provide", "d"):
            self.files = worlds.find(self.files.name, self.files.root)
            self.campaign.files = self.files
            ready = (p["kind"] == "town" and p["burg"]["i"] in self.files.towns()) or \
                    (p["kind"] == "dwelling" and any(f.burg == p["burg"]["i"] for f in self.files.dwellings()))
            if ready:
                self.prompt = None
                return self.enter(p["scene"])
            return "The file isn't there yet. Type DONE when it is, or GENERATE."
        return "Type PROVIDE/DONE, GENERATE or ALWAYS."

    @property
    def finished(self) -> bool:
        return bool(self.game and self.game.quit_requested and not self.prompt)

    def finish(self) -> None:
        self.campaign.leave(self.game.w)
        self.campaign.save()
