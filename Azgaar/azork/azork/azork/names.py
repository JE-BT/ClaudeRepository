"""Names from Azgaar's namebases, generated with Azgaar's own Markov method.

Ported from src/generators/names-generator.ts (calculateChain, getBase). The
random source is Python's, seeded per call, so a name is reproducible from
(world seed, entity key) but will not match names Azgaar itself produced.
Name lists: azork/data/namebases.json (vendored, MIT), overridden by any custom
lists stored in the .map.
"""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

VOWELS = set("aeiouyɑ'əøɛœæɶɒɨɪɔɐʊɤɯаоиеёэыуюяàèìòùỳẁȁȅȉȍȕáéíóúýẃőűâêîôûŷŵäëïöüÿẅãẽĩõũỹąęįǫųāēīōūȳăĕĭŏŭǎěǐǒǔȧėȯẏẇạẹịọụỵẉḛḭṵṳ")
DATA = Path(__file__).with_name("data") / "namebases.json"


def is_vowel(c: str | None) -> bool:
    return c is not None and c in VOWELS


@lru_cache(maxsize=1)
def default_bases() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["bases"]


def calculate_chain(names: str) -> dict[str, list[str]]:
    chain: dict[str, list[str]] = {}
    for raw in names.split(","):
        name = raw.strip().lower()
        basic = all(0x20 <= ord(ch) <= 0x7E for ch in name)
        i = -1
        while i < len(name):
            prev = name[i] if i >= 0 else ""
            syllable, v, c = "", 0, i + 1
            while c < len(name) and len(syllable) < 5:
                that = name[c]
                nxt = name[c + 1] if c + 1 < len(name) else None
                syllable += that
                if syllable in (" ", "-"):
                    break
                if not nxt or nxt in (" ", "-"):
                    break
                if is_vowel(that):
                    v = 1
                if that == "y" and nxt == "e":
                    c += 1
                    continue
                if basic and (that, nxt) in (("o", "o"), ("e", "e"), ("a", "e"), ("c", "h")):
                    c += 1
                    continue
                # Azgaar's line 'isVowel(that) === next' compares a boolean with a string: never true
                if v and is_vowel(name[c + 2] if c + 2 < len(name) else None):
                    break
                c += 1
            chain.setdefault(prev, []).append(syllable)
            i += len(syllable) or 1
    return chain


class NameGenerator:
    def __init__(self, overrides: dict[int, dict] | None = None):
        self.bases = [dict(b) for b in default_bases()]
        for i, o in (overrides or {}).items():
            if i < len(self.bases):
                self.bases[i].update({k: v for k, v in o.items() if k != "b" or v})
        self._chains: dict[int, dict] = {}

    def chain(self, base: int) -> dict[str, list[str]]:
        if base not in self._chains:
            self._chains[base] = calculate_chain(self.bases[base]["b"])
        return self._chains[base]

    def name(self, base: int, seed: str, min_len: int | None = None, max_len: int | None = None) -> str:
        rng = random.Random(seed)
        b = self.bases[base]
        data = self.chain(base)
        lo, hi, dupl = min_len or b["min"], max_len or b["max"], b["d"]
        v = data[""]
        cur, w = rng.choice(v), ""
        for _ in range(20):
            if cur == "":
                if len(w) < lo:
                    cur, w, v = "", "", data[""]
                else:
                    break
            elif len(w) + len(cur) > hi:
                if len(w) < lo:
                    w += cur
                break
            else:
                v = data.get(cur[-1]) or data[""]
            w += cur
            cur = rng.choice(v)
        if w and w[-1] in "' -":
            w = w[:-1]
        out = ""
        for k, ch in enumerate(w):
            nxt = w[k + 1] if k + 1 < len(w) else None
            if ch == nxt and ch not in dupl:
                continue
            if not out:
                out = ch.upper()
            elif out[-1] == "-" and ch == " ":
                continue
            elif out[-1] in " -":
                out += ch.upper()
            elif ch == "a" and nxt == "e":
                continue
            elif k + 2 < len(w) and ch == nxt == w[k + 2]:
                continue
            else:
                out += ch
        parts = out.split(" ")
        if any(len(p) < 2 for p in parts):
            out = "".join(p if k == 0 else p.lower() for k, p in enumerate(parts))
        if len(out) < 2:
            out = rng.choice(b["b"].split(","))
        return out
