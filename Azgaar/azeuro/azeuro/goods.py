"""The six trades: Azgaar's goods grouped into the commission decks.

Rule-based on Azgaar's own good fields (unit and tags), so it works on any world:
  Slaves         unit "slave" or the good named Slaves
  Livestock      unit "head" (cattle, horses, camels, elephants, sheep)
  Metals & arms  ore, military or naval tags, or minerals and preservatives that are not food or luxury
  Building       construction, fuel or storage tags
  Luxuries       luxury, ritual, currency, educational or clothing tags
  Provisions     everything else (food)
"""
from __future__ import annotations

import re

TRADES = ["Provisions", "Luxuries", "Metals & arms", "Building", "Livestock", "Slaves"]
TRADE_COLOR = {"Provisions": "#B07A22", "Luxuries": "#7E4AA6", "Metals & arms": "#3F6496",
               "Building": "#7E5235", "Livestock": "#3F8A4A", "Slaves": "#A8342A"}


def trade_of(g: dict) -> str:
    name, tags, unit = g.get("name", ""), set(g.get("tags") or []), g.get("unit")
    if unit == "slave" or name == "Slaves":
        return "Slaves"
    if unit == "head":
        return "Livestock"
    if tags & {"ore", "military", "naval"} or (tags & {"mineral", "preservative"} and "luxury" not in tags
                                                 and "food" not in tags):
        return "Metals & arms"
    if tags & {"construction", "fuel", "storage"}:
        return "Building"
    if tags & {"luxury", "ritual", "currency", "educational", "clothing"}:
        return "Luxuries"
    return "Provisions"


def goods_named_in(text: str, goods: list[dict]) -> list[dict]:
    """Goods whose name appears as a word in a marker note (e.g. 'near the saltpeter mine')."""
    t = (text or "").casefold()
    out = []
    for g in sorted(goods, key=lambda g: -len(g["name"])):
        n = g["name"].casefold()
        if re.search(rf"\b{re.escape(n)}\b", t) and not any(n in o["name"].casefold() for o in out):
            out.append(g)
    return out
