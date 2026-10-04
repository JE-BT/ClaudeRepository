"""Export a play session on exit: keep, discard or fork.

The ledger gets a short entry (places, items, and a link to the story document); the story
details go in <World>_story.md beside it, so neither document is overloaded.
keep    append to <World>_ledger.md and <World>_story.md
discard write nothing
fork    write <World>_ledger.<branch>.md and <World>_story.<branch>.md (main documents plus the session)
The files' own line endings (the repo copies use CRLF) are preserved.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .engine.game import Game


def session_markdown(game: Game, ledger_names: list[str], story_link: str | None = None) -> str:
    w = game.w
    visited = [r.name for r in w.rooms.values() if r.visited]
    taken = [t.name for t in w.things.values() if t.location == "player" and "start" not in t.flags]
    dropped = [f"{t.name} ({w.rooms[t.location].name})" for t in w.things.values()
               if "dropped" in t.flags and t.location in w.rooms]
    kind, _, ident = w.scene.partition(":")
    anchors = {"dwelling": "dwelling file", "dungeon": "marker", "town": "burg"}
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"## Play session ({stamp}, {w.scene})", "",
             f"### Play session: {w.flags.get('title', w.scene)} — event",
             f"- Anchored to: {anchors.get(kind, 'journey')} {ident}".rstrip(),
             "- Status: draft",
             f"- Connections: {'; '.join(ledger_names) if ledger_names else 'none'}",
             f"- Played to {game.w.time_label()} after {w.moves} moves" + (" (ended in death)" if w.dead else ""),
             f"- Places visited: {', '.join(visited) or 'none'}",
             f"- Carried away: {', '.join(taken) or 'nothing new'}",
             f"- Left behind: {', '.join(dropped) or 'nothing'}"]
    if story_link:
        lines.append(f"- Story: {story_link}")
    return "\n".join(lines + [""])


def story_markdown(game: Game, campaign, heading: str) -> str:
    st = campaign.story
    label = lambda t: campaign.journey.label(t)
    lines = [f"## {heading}", "",
             f"Clock {label(campaign.t)}; stage {campaign.pos[0]}, mile {campaign.pos[1]:.0f}; "
             f"{abs(campaign.delay()):.0f} hours {'behind' if campaign.delay() > 0 else 'ahead of'} the plan; "
             f"score {st.score} of {st.max_score}.", ""]
    for s in st.storylines:
        if s.kind == "plant":
            continue
        lines += [f"### {s.title} ({s.kind}, {s.status})", "", s.summary, "", "| Phase | Status | Objective |", "|---|---|---|"]
        lines += [f"| {p.title} | {p.status} | {p.objective} |" for p in s.phases]
        placed = [f"{e.spec['name']} ({'placed' if e.placed else e.anchor})" for e in s.elements.values()]
        if placed:
            lines += ["", "Elements: " + "; ".join(placed)]
        lines.append("")
    if st.ending:
        lines += [f"Ending: {st.ending['kind']}. {st.ending.get('text', '')}", ""]
    return "\n".join(lines)


def _append(path: Path, base: Path | None, text: str, title: str) -> None:
    raw = base.read_bytes().decode("utf-8") if base and base.exists() else (
        path.read_bytes().decode("utf-8") if path.exists() else f"# {title}\r\n")
    nl = "\r\n" if "\r\n" in raw else "\n"
    path.write_bytes((raw.rstrip() + nl + nl + text.replace("\n", nl)).encode("utf-8"))


def export(ledger_path: Path, game: Game, choice: str, branch: str | None = None, campaign=None) -> Path | None:
    choice = choice.strip().lower()
    if choice not in ("keep", "discard", "fork"):
        raise ValueError("choose keep, discard or fork")
    if choice == "discard":
        return None
    if choice == "fork" and (not branch or not re.fullmatch(r"[\w-]+", branch)):
        raise ValueError("a fork needs a branch name of letters, digits, - or _")
    raw = ledger_path.read_bytes().decode("utf-8")
    names = re.findall(r"^###\s+(.+?)\s+—", raw, re.M)
    title = game.w.flags.get("title", "").lower()
    linked = [n for n in names if n.lower() in title or
              any(n.lower() in r.name.lower() for r in game.w.rooms.values() if r.visited)]
    world = ledger_path.stem.replace("_ledger", "")
    suffix = f".{branch}" if choice == "fork" else ""
    story_path = ledger_path.with_name(f"{world}_story{suffix}.md")
    heading = f"Session {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    link = f"{story_path.name}, section \"{heading}\"" if campaign is not None else None
    target = ledger_path.with_name(f"{ledger_path.stem}{suffix}.md")
    _append(target, ledger_path if choice == "fork" else None, session_markdown(game, linked, link), f"{world} ledger")
    if campaign is not None:
        main_story = ledger_path.with_name(f"{world}_story.md")
        _append(story_path, main_story if choice == "fork" else None, story_markdown(game, campaign, heading),
                f"{world} story")
    return target
