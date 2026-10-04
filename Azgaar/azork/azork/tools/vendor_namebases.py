"""Vendor Azgaar's default namebases into azork/data/namebases.json.

Usage: python tools/vendor_namebases.py path/to/Fantasy-Map-Generator/src/data/name-bases.ts

Azgaar's Fantasy Map Generator is MIT-licensed; the namebase lists are copied
unchanged, with the source commit noted in the output file.
"""
import json
import re
import sys
from pathlib import Path

FIELD = r'\s*{0}:\s*({1}),?'
PATTERN = re.compile(
    r"\{\s*name:\s*\"(?P<name>[^\"]*)\",\s*i:\s*(?P<i>\d+),\s*min:\s*(?P<min>\d+),\s*"
    r"max:\s*(?P<max>\d+),\s*d:\s*\"(?P<d>[^\"]*)\",\s*m:\s*(?P<m>[\d.]+),\s*b:\s*\"(?P<b>[^\"]*)\"",
    re.S,
)


def main(src: str) -> None:
    text = Path(src).read_text(encoding="utf-8")
    bases = []
    for m in PATTERN.finditer(text):
        bases.append({
            "name": m["name"], "i": int(m["i"]), "min": int(m["min"]), "max": int(m["max"]),
            "d": m["d"], "m": float(m["m"]), "b": m["b"],
        })
    if not bases or [b["i"] for b in bases] != list(range(len(bases))):
        sys.exit(f"Parsed {len(bases)} bases with non-sequential indexes; check the source format")
    out = Path(__file__).resolve().parents[1] / "azork" / "data" / "namebases.json"
    out.write_text(json.dumps({
        "source": "Azgaar/Fantasy-Map-Generator src/data/name-bases.ts (MIT licence)",
        "bases": bases,
    }, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(bases)} namebases to {out}")


if __name__ == "__main__":
    main(sys.argv[1])
