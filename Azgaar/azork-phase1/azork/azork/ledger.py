"""Parse a <World>_ledger.md into structured entries.

Entry format (see the Project instructions):
    ### Name — type
    - Anchored to: burg 172, cell 1091; culture Dail (13); building 14 in bayfshear.json
    - Status: canon | draft (free text after the first word is kept)
    - Connections: Other entry; Another entry
    - one fact per line ("Draft:" and "Open:" prefixes are recognised)
Headings without " — type" (e.g. "Contradictions and slippage") are kept as notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ENTRY = re.compile(r"^###\s+(?P<name>.+?)\s+[—-]\s+(?P<type>[^—]+?)\s*$")
SESSION = re.compile(r"^##\s+(?P<title>.+?)\s*$")
FIELD = re.compile(r"^-\s+(?P<key>Anchored to|Status|Connections):\s*(?P<value>.*)$", re.I)
ANCHOR = re.compile(
    r"\b(?P<kind>burgs?|cells?|markers?|zones?|religions?|cultures?|provinces?|states?|routes?|"
    r"namebases?|goods?|markets?|buildings?|stages?)\s+(?P<num>\d+)"
    r"(?P<chain>(?:\s*(?:\([^)]*\))?\s*(?:→|->|,)\s*\d+)*)",
    re.I,
)
NAMED_ID = re.compile(r"\b(?P<kind>culture|religion|state|province)\s+[^;,()]+?\((?P<num>\d+)\)", re.I)
IN_FILE = re.compile(r"building\s+(?P<num>\d+)\s+in\s+(?P<file>[\w.\- ]+\.json)", re.I)
FILE = re.compile(r"(?P<file>[\w\-]+\.json)")
JOURNEY = re.compile(r'journey\s+"(?P<name>[^"]+)"', re.I)


@dataclass(frozen=True)
class Anchor:
    kind: str
    id: int | None = None
    file: str | None = None
    name: str | None = None


@dataclass
class Entry:
    name: str
    type: str
    session: str
    anchored_to: str = ""
    status_text: str = ""
    connections: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)

    @property
    def status(self) -> str:
        word = self.status_text.split()[0].strip(";,.").lower() if self.status_text else "draft"
        return word if word in ("canon", "draft") else "draft"

    def facts_by_layer(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"canon": [], "draft": [], "open": []}
        for f in self.facts:
            low = f.lower()
            if low.startswith("open"):
                out["open"].append(f)
            elif low.startswith("draft") or self.status == "draft":
                out["draft"].append(f)
            else:
                out["canon"].append(f)
        return out


@dataclass
class Ledger:
    path: Path
    entries: list[Entry]
    notes: dict[str, list[str]]

    def get(self, name: str) -> Entry | None:
        key = name.casefold()
        return next((e for e in self.entries if e.name.casefold() == key), None)

    def anchored(self, kind: str, id_: int) -> list[Entry]:
        return [e for e in self.entries if any(a.kind == kind and a.id == id_ for a in e.anchors)]


def parse_anchors(text: str) -> list[Anchor]:
    out: list[Anchor] = []
    for m in IN_FILE.finditer(text):
        out.append(Anchor("building", int(m["num"]), m["file"].strip()))
    covered = {a.id for a in out if a.kind == "building"}
    for m in ANCHOR.finditer(text):
        kind = m["kind"].lower().rstrip("s") if m["kind"].lower() != "goods" else "good"
        if kind == "building" and int(m["num"]) in covered:
            continue
        chain = m["chain"] or ""
        if "," in chain and not m["kind"].lower().endswith("s"):
            chain = ""  # comma lists only follow plural words ("cells 1, 2"), not "province 279, 3 cells"
        ids = [int(m["num"])] + [int(x) for x in re.findall(r"(?<![(\w])\d+", re.sub(r"\([^)]*\)", "", chain))]
        out += [Anchor(kind, i) for i in ids]
    for m in NAMED_ID.finditer(text):
        out.append(Anchor(m["kind"].lower(), int(m["num"])))
    for m in JOURNEY.finditer(text):
        out.append(Anchor("journey", name=m["name"]))
    for m in FILE.finditer(text):
        out.append(Anchor("file", file=m["file"]))
    seen, unique = set(), []
    for a in out:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique


def parse(path: str | Path) -> Ledger:
    path = Path(path)
    entries: list[Entry] = []
    notes: dict[str, list[str]] = {}
    session, current, note = "", None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.rstrip()
        if m := SESSION.match(s):
            session, current, note = m["title"], None, None
            continue
        if s.startswith("### "):
            m = ENTRY.match(s)
            if m:
                current, note = Entry(m["name"].strip(), m["type"].strip(), session), None
                entries.append(current)
            else:
                current, note = None, s[4:].strip()
                notes[note] = []
            continue
        if not s.startswith("- "):
            continue
        if current is None:
            if note is not None:
                notes[note].append(s[2:].strip())
            continue
        if m := FIELD.match(s):
            key, value = m["key"].lower(), m["value"].strip()
            if key == "anchored to":
                current.anchored_to = value
                current.anchors = parse_anchors(value)
            elif key == "status":
                current.status_text = value
            else:
                current.connections = [c.strip() for c in re.split(r"[;,]", value) if c.strip()]
        else:
            current.facts.append(s[2:].strip())
    return Ledger(path, entries, notes)
