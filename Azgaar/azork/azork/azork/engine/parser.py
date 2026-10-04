"""Turn a typed line into commands: VERB [OBJECT] [PREPOSITION OBJECT].

Several commands can be chained with '.', ' then ' or ' and then '. Noun phrases
drop articles; 'all'/'everything' (optionally 'except X') and 'it' are recognised.
Object resolution against the world happens in the game, not here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import ABBREV, DIRECTIONS

# canonical verb -> phrases (longest match wins)
VERBS: dict[str, list[str]] = {
    "look": ["look", "l", "look around"],
    "examine": ["examine", "x", "inspect", "look at", "check", "describe", "study"],
    "lookin": ["look in", "look into", "peer into", "gaze into", "look through"],
    "read": ["read"],
    "inventory": ["inventory", "inv", "i"],
    "take": ["take", "get", "pick up", "grab", "carry", "lift up"],
    "drop": ["drop", "put down", "discard", "throw away", "abandon"],
    "put": ["put", "place", "insert", "stow", "pack"],
    "takeout": ["take out", "remove", "unpack"],
    "open": ["open"], "close": ["close", "shut"],
    "unlock": ["unlock"], "lock": ["lock"],
    "go": ["go", "walk", "run", "head", "climb", "travel"],
    "enter": ["enter", "go inside"], "leave": ["exit", "leave", "go outside"],
    "wait": ["wait", "z", "rest"],
    "again": ["again", "g"], "undo": ["undo"],
    "save": ["save"], "restore": ["restore", "load"], "quit": ["quit", "q"],
    "time": ["time"], "status": ["status"], "score": ["score", "points"],
    "goals": ["goals", "objectives", "quests", "tasks", "think"],
    "schedule": ["schedule", "on track", "timetable", "how late", "progress", "am i late", "how far behind"],
    "light": ["light", "turn on", "ignite", "kindle"],
    "extinguish": ["extinguish", "turn off", "douse", "snuff", "put out", "blow out"],
    "search": ["search", "probe", "rummage", "rummage through", "search through"],
    "raise": ["raise", "hoist", "lift"], "lower": ["lower", "drop down"],
    "weigh": ["weigh", "heft"],
    "talk": ["talk to", "talk", "greet", "speak to", "hello", "hi"],
    "onward": ["onward", "onwards", "continue", "go on", "press on", "move on", "keep going", "travel on", "travel"],
    "camp": ["camp", "make camp", "pitch camp"], "forage": ["forage", "gather food"], "hunt": ["hunt"],
    "route": ["route", "where now", "which way", "show route", "mark route"],
    "recap": ["recap", "story so far", "notes", "summary", "story"],
    "back": ["back", "go back", "turn back", "return"],
    "visit": ["visit", "detour to", "go to", "head to"],
    "buy": ["buy", "purchase"], "sell": ["sell"], "wares": ["wares", "prices", "browse", "shop", "trade"],
    "book": ["book passage", "book", "hire passage", "take passage"],
    "eat": ["eat", "consume", "devour", "taste"], "drink": ["drink", "sip", "quaff", "drink from"],
    "fill": ["fill", "refill", "top up"], "use": ["use", "apply"],
    "sleep": ["sleep", "lie down", "nap", "sleep on", "sleep in", "lie on"], "sit": ["sit on", "sit in", "sit down", "sit"],
    "wear": ["wear", "put on", "don"], "knock": ["knock on", "knock at", "knock", "rap on"],
    "give": ["give", "offer", "hand"], "ask": ["ask"], "tell": ["tell"], "show": ["show"],
    "invite": ["invite", "ask along", "recruit"], "dismiss": ["dismiss", "send away"],
    "listen": ["listen to", "listen", "hear"], "smell": ["smell", "sniff"],
    "touch": ["touch", "feel", "pat", "stroke", "rub"], "push": ["push", "press", "shove"],
    "pull": ["pull", "tug", "yank"], "pray": ["pray at", "pray to", "pray"], "cook": ["cook", "roast", "heat up"],
    "lookunder": ["look under", "look beneath", "check under"], "play": ["play with", "play"],
    "write": ["write", "note", "jot", "jot down"], "journal": ["journal", "read journal", "read my journal", "diary"],
    "attack": ["attack", "kill", "hit", "fight", "strike", "stab", "punch"], "wake": ["wake up", "wake", "rouse", "shout", "yell"],
    "help": ["help", "?", "commands"],
}
PREPOSITIONS = ["with", "into", "in", "inside", "onto", "on", "from", "to", "at", "about", "under", "using"]
ARTICLES = {"the", "a", "an", "some", "my", "this", "that"}
ALL_WORDS = {"all", "everything"}
EXCEPT_WORDS = {"except", "but"}

_PHRASES = sorted(((p.split(), v) for v, ps in VERBS.items() for p in ps), key=lambda x: -len(x[0]))


@dataclass
class Command:
    verb: str
    words: list[str] = field(default_factory=list)       # direct object words
    prep: str | None = None
    iwords: list[str] = field(default_factory=list)      # indirect object words
    direction: str | None = None
    all: bool = False
    except_words: list[str] = field(default_factory=list)
    raw: str = ""


def split_commands(line: str) -> list[str]:
    """Split on '.', ';' and 'then', keeping case; a WRITE/NOTE line is kept whole."""
    if re.match(r"\s*(write|note|jot)\b", line, re.I):
        return [line.strip()]
    parts = re.split(r"\.|;|\bthen\b", line, flags=re.I)
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def _direction(word: str) -> str | None:
    word = ABBREV.get(word, word)
    return word if word in DIRECTIONS else None


def _phrase(words: list[str]) -> list[str]:
    return [w for w in words if w not in ARTICLES]


def parse(text: str) -> Command | None:
    words = re.findall(r"[a-z0-9'?-]+", text.lower())
    if not words:
        return None
    # bare direction, or "go <direction>"
    if len(words) == 1 and _direction(words[0]):
        return Command("go", direction=_direction(words[0]), raw=text)
    verb, rest = None, words
    for phrase, v in _PHRASES:
        if words[:len(phrase)] == phrase:
            verb, rest = v, words[len(phrase):]
            break
    if verb is None:
        return Command("unknown", words, raw=text)
    if verb in ("go", "enter", "leave") and rest:
        d = _direction(rest[-1]) if rest[-1] not in ("stairs", "steps") else None
        if rest[0] in ("up", "down") and (len(rest) == 1 or rest[-1] in ("stairs", "steps", "staircase")):
            d = rest[0]
        if d:
            return Command("go", direction=d, raw=text)
        if verb == "go" and rest[0] in ("in", "into", "inside"):
            return Command("enter", _phrase(rest[1:]), raw=text)
    cmd = Command(verb, raw=text)
    split = next((k for k, w in enumerate(rest) if w in PREPOSITIONS and k > 0), None)
    dobj, iobj = (rest, []) if split is None else (rest[:split], rest[split + 1:])
    if split is not None:
        cmd.prep = rest[split]
    dobj = _phrase(dobj)
    if dobj and dobj[0] in ALL_WORDS:
        cmd.all = True
        k = next((i for i, w in enumerate(dobj) if w in EXCEPT_WORDS), None)
        cmd.except_words = dobj[k + 1:] if k is not None else []
        dobj = []
    cmd.words, cmd.iwords = dobj, _phrase(iobj)
    if verb == "go" and not cmd.words and not cmd.direction:
        cmd.verb = "go"
    return cmd
