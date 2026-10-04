"""Export a play session to the ledger on exit: keep, discard or fork.

keep    append the session (status draft) to <World>_ledger.md
discard write nothing to the ledger
fork    write <World>_ledger.<branch>.md: the main ledger plus the session
The file's own line endings (the repo copy uses CRLF) are preserved.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .engine.game import Game


def session_markdown(game: Game, ledger_names: list[str]) -> str:
    w = game.w
    visited = [r.name for r in w.rooms.values() if r.visited]
    taken = [t.name for t in w.things.values() if t.location == "player" and "start" not in t.flags]
    dropped = [f"{t.name} ({w.rooms[t.location].name})" for t in w.things.values()
               if "dropped" in t.flags and t.location in w.rooms]
    anchors = {"dwelling": "dwelling file", "dungeon": "marker"}
    kind, _, ident = w.scene.partition(":")
    today = dt.date.today().isoformat()
    lines = [f"## Play session ({today}, scene {w.scene})", "",
             f"### Play session: {w.flags.get('title', w.scene)} — event",
             f"- Anchored to: {anchors.get(kind, kind)} {ident}",
             "- Status: draft",
             f"- Connections: {'; '.join(ledger_names) if ledger_names else 'none'}",
             f"- Played from {game.w.time_label()} after {w.moves} moves" + (" (ended in death)" if w.dead else ""),
             f"- Places visited: {', '.join(visited) or 'none'}",
             f"- Carried away: {', '.join(taken) or 'nothing new'}",
             f"- Left behind: {', '.join(dropped) or 'nothing'}", ""]
    return "\n".join(lines)


def export(ledger_path: Path, game: Game, choice: str, branch: str | None = None) -> Path | None:
    choice = choice.strip().lower()
    if choice not in ("keep", "discard", "fork"):
        raise ValueError("choose keep, discard or fork")
    if choice == "discard":
        return None
    raw = ledger_path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    names = re.findall(r"^###\s+(.+?)\s+—", raw, re.M)
    linked = [n for n in names if n.lower() in (game.w.flags.get("title", "").lower(),)
              or any(n.lower() in r.name.lower() or n.lower() in game.w.flags.get("title", "").lower()
                     for r in game.w.rooms.values() if r.visited)]
    body = session_markdown(game, linked).replace("\n", nl)
    text = raw.rstrip() + nl + nl + body
    if choice == "fork":
        if not branch or not re.fullmatch(r"[\w-]+", branch):
            raise ValueError("a fork needs a branch name of letters, digits, - or _")
        target = ledger_path.with_name(f"{ledger_path.stem}.{branch}.md")
    else:
        target = ledger_path
    target.write_bytes(text.encode("utf-8"))
    return target
