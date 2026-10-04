"""Play the whole game from a campaign: the hex road, and the places along it.

The runner moves the party between the road and scenes (towns, dungeons, houses), keeps the
campaign up to date at each change, opens with the hook (new game) or a recap (saved game), and
pauses to ask when a place needs a file the repository does not have: a town plan, a key
building's interior, or any building you walk into. PROVIDE it (and click its building with
azork pick), GENERATE one that fits, or ALWAYS generate from now on.
"""
from __future__ import annotations

import json

from . import scenes, towns, wild, worlds
from .engine.game import Game
from .style import mark


class Runner:
    def __init__(self, files, campaign, save_dir=None):
        self.files, self.campaign, self.save_dir = files, campaign, save_dir
        self.game: Game | None = None
        self.prompt: dict | None = None

    def _kit(self, w):
        c = self.campaign
        specs = c.inventory if c.inventory is not None else (
            scenes._content(self.files, "items.json") or json.loads(scenes.DEFAULT_ITEMS.read_text()))["start_inventory"]
        for spec in specs:
            w.spawn(spec, "player", spec.get("id"))
        for spec in c.story.pending_gifts:
            if spec["id"] not in w.things:
                w.spawn(spec, "player", spec["id"])
        c.story.pending_gifts.clear()

    def _game(self, w) -> Game:
        g = Game(w, self.save_dir, self.campaign)
        g.building_policy = "generate" if self.campaign.policy == "generate" else "ask"
        return g

    def start(self, fresh: bool) -> str:
        st = self.campaign.story
        if fresh:
            main = st.line("main")
            opening = mark(main.phases[0].text, "main")
        else:
            last = st.record[-6:]
            opening = "Previously:\n" + "\n".join(
                "  " + (f"[{r['when']}] " if r["when"] else "") + mark(f"{r['line']}: {r['text']}", "main" if r["kind"] == "main" else "side") for r in last)
        goals = st.objectives()
        return opening + ("\n\nGoals:\n  " + "\n  ".join(goals) if goals else "") + "\n\n" + self.road()

    def road(self) -> str:
        w = wild.build(self.campaign)
        self._kit(w)
        self.game = self._game(w)
        return self.game.intro()

    def enter(self, scene: str, policy: str | None = None) -> str:
        kind, _, ident = scene.partition(":")
        c = self.campaign
        if kind == "town" and int(ident) not in self.files.towns() and int(ident) not in c.generated \
                and c.policy != "generate" and policy is None:
            burg = self.files.map.burg(int(ident))
            from . import cells, links
            _, link = links.burg_link(self.files.map, cells.CellGeo(self.files.cells_path, self.files.map), burg)
            self.prompt = {"kind": "town", "scene": scene, "burg": burg}
            return (f"[Paused] {burg['name']} has no town plan yet.\n"
                    f"  PROVIDE: open {link}, export JSON, save it as {self.files.map_path.parent.name}/"
                    f"{burg['name'].lower()}.json, then type DONE.\n"
                    f"  GENERATE: make {burg['name']} up for now.   ALWAYS: make places up from now on.")
        w = scenes.build(self.files, scene, c, policy)
        self.game = self._game(w)
        intro = self.game.intro()
        if kind == "town" and int(ident) not in c.generated and c.policy != "generate" and policy is None:
            t = w.flags["town"]
            missing = [(role, idx) for role, idx in t["places"].items() if not t["buildings"][idx].get("file")]
            if missing:
                burg = self.files.map.burg(int(ident))
                lines = [f"  {role}: {t['buildings'][idx]['label']}, building {idx} on {w.rooms[t['buildings'][idx]['node']].name}"
                         for role, idx in missing]
                self.prompt = {"kind": "key", "scene": scene, "burg": burg, "intro": intro}
                return (f"[Paused] {burg['name']}'s key buildings have no interiors yet:\n" + "\n".join(lines) +
                        f"\n  PROVIDE: in the {burg['name']} plan, click each building to open Dwellings (pick one that looks "
                        f"the part: a tavern, a hall, a temple), export JSON, then run  python -m azork pick {self.files.name} "
                        f"{burg['name']} --dwelling <file> --role <role>  and click the same building; then type DONE.\n"
                        f"  GENERATE: make interiors up to fit these buildings.   ALWAYS: make interiors up from now on.")
        return intro

    def step(self, line: str) -> str:
        if self.prompt:
            return self._answer(line.strip().lower())
        out = self.game.step(line)
        w = self.game.w
        need = w.flags.pop("need_building", None)
        if need:
            t = w.flags["town"]
            info = t["buildings"][need]
            burg = self.files.map.burg(t["burg"])
            self.prompt = {"kind": "building", "idx": need, "burg": burg}
            return (out + f"\n[Paused] {info['label'][0].upper() + info['label'][1:]} (building {need}, on "
                    f"{w.rooms[info['node']].name}) has no interior yet.\n"
                    f"  PROVIDE: click building {need} in the {burg['name']} plan to open Dwellings, export JSON, run  "
                    f"python -m azork pick {self.files.name} {burg['name']} --dwelling <file>  and click it; then DONE.\n"
                    f"  GENERATE: make this one up.   ALWAYS: make interiors up from now on.")
        tr = w.flags.pop("transition", None)
        if tr and "enter" in tr:
            self.campaign.leave(w)
            out += "\n\n" + self.enter(tr["enter"])
        elif tr and tr.get("leave"):
            self.campaign.leave(w)
            self.campaign.save()
            out += "\n\n" + self.road()
        elif tr and tr.get("ride"):
            r = tr["ride"]
            self.campaign.leave(w)
            self.campaign.t += r["hours"]
            dest = self.files.map.burg(r["to"])
            wd = wild.wild_of(self.campaign)
            self.campaign.hex = wd.grid.key(wd.grid.at(dest["x"], dest["y"]))
            msgs = []
            if (r["pos"][0], r["pos"][1]) > tuple(self.campaign.pos):
                self.campaign.pos = list(r["pos"])
                msgs = self.campaign.story.notify({"type": "pass", "pos": self.campaign.pos})
            self.campaign.save()
            out += f"\n\nAfter {r['hours'] / 24:.1f} days you reach {r['to_name']}.\n" + "\n".join(msgs) + "\n" + self.road()
        return out

    def _answer(self, word: str) -> str:
        p, c = self.prompt, self.campaign
        if word in ("always", "a"):
            c.policy = "generate"
            self.game.building_policy = "generate" if self.game else "generate"
            word = "generate"
        if word in ("generate", "g"):
            self.prompt = None
            if p["kind"] == "town":
                c.generated.append(p["burg"]["i"])
                return self.enter(p["scene"], "generate")
            if p["kind"] == "key":
                c.generated.append(p["burg"]["i"])
                return p["intro"]
            towns.open_building(self.game, p["idx"], "generate")
            return self.game.step(self._exit_to(p["idx"]))
        if word in ("done", "provide", "d"):
            self.files = worlds.find(self.files.name, self.files.root)
            c.files = self.files
            if p["kind"] == "town" and p["burg"]["i"] in self.files.towns():
                self.prompt = None
                return self.enter(p["scene"])
            if p["kind"] == "key":
                self.prompt = None
                return self.enter(p["scene"], "generate")
            if p["kind"] == "building":
                f = next((f for f in self.files.dwellings() if f.burg == p["burg"]["i"] and str(f.building) == p["idx"]), None)
                if f:
                    self.prompt = None
                    info = self.game.w.flags["town"]["buildings"][p["idx"]]
                    info.update({"file": str(f.path), "label": f.label or info["label"]})
                    towns.open_building(self.game, p["idx"], "generate")
                    return self.game.step(self._exit_to(p["idx"]))
            return "The file isn't placed yet. Type DONE when it is, or GENERATE."
        return "Type PROVIDE/DONE, GENERATE or ALWAYS."

    def _exit_to(self, idx: str) -> str:
        info = self.game.w.flags["town"]["buildings"][idx]
        return f"go {info['exit']}"

    @property
    def finished(self) -> bool:
        return bool(self.game and self.game.quit_requested and not self.prompt)

    def finish(self) -> None:
        self.campaign.leave(self.game.w)
        self.campaign.save()
