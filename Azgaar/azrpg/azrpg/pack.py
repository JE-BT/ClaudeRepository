"""Assemble the world pack the browser engine loads.

Layout (then gzip, then base64 when embedded in HTML):
    b"AZRP" | uint32 json length | JSON (utf-8) | raster blobs back to back
The JSON lists each raster with its byte offset, length, element type and encoding. Rasters are
row-major over the tile grid. 'height' is delta-encoded along rows (uint8, wrapping) because a
smooth field compresses much better that way.

Everything in the JSON is either copied from the .map/GeoJSON (data) or computed from it by a
stated rule: rural production (Azgaar's getCellProduction), trade summaries (deals grouped by
burg and good), journey plan times (miles / speed, spread over hoursPerDay).
"""
from __future__ import annotations

import base64
import gzip
import html
import json
import re
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .cells import CellGeo
from .mapfile import AzgaarMap
from .names import NameBases
from .raster import Raster
from .tilegrid import TileGrid

FORMAT = "azrpg-pack/1"
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r'href="([^"]+)"')


def r2(v, n=2):
    return round(float(v), n) if v is not None else None


def clean_note(note: str) -> tuple[str, list[str]]:
    """Marker and unit notes may hold HTML (links, iframes); keep text and the links."""
    links = _LINK.findall(note or "")
    text = _TAG.sub(" ", note or "")
    text = html.unescape(re.sub(r"[ \t]+", " ", text)).replace("\r", "")
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text, links


class PackBuilder:
    def __init__(self, map_path: Path, cells_path: Path, folder_name: str | None = None):
        self.m = AzgaarMap(map_path)
        self.geo = CellGeo(cells_path, self.m)
        problems = self.geo.check_against(self.m)
        if problems:
            raise ValueError(f"{cells_path.name} does not match {map_path.name}: {problems}")
        self.grid = TileGrid.from_map(self.m)
        self.raster = Raster(self.m, self.geo, self.grid, seed=int(self.m.seed) % 2**31).build()
        self.folder = folder_name or map_path.parent.name
        self.cells_path = cells_path

    # ------------------------------------------------------------------ tables
    def _cells(self) -> dict:
        m, geo = self.m, self.geo
        n = m.cell_count
        typ = []
        for i in range(n):
            t = geo.props[i].get("type")
            typ.append(1 if t == "ocean" else 2 if t == "lake" else 0)
        zones = defaultdict(list)
        for z in m.live("zones"):
            for c in z["cells"]:
                zones[c].append(z["i"])
        return {
            "biome": m.cell("biome"), "burg": m.cell("burg"), "culture": m.cell("culture"),
            "religion": m.cell("religion"), "state": m.cell("state"), "province": m.cell("province"),
            "river": m.cell("river"), "pop": [r2(p, 3) for p in m.cell("pop")], "good": m.cell("good"),
            "market": m.cell("market") or [0] * n, "flux": m.cell("fl"),
            "feature": self.raster.cell_feature, "type": typ,
            "hft": [geo.props[i].get("height", 0) for i in range(n)],
            "cx": [r2(geo.centroid[i][0], 1) for i in range(n)],
            "cy": [r2(geo.centroid[i][1], 1) for i in range(n)],
            "zones": {str(k): v for k, v in zones.items()},
            "prod": self._rural_production(typ, zones),
        }

    def _rural_production(self, typ, zones) -> dict:
        """Azgaar's getCellProduction: biome output times population (water cells use the
        population of their neighbours), plus the cell's bonus good, times the good's modifiers."""
        m, geo = self.m, self.geo
        goods = {g["i"]: g for g in m.data["goods"]}
        by_biome = defaultdict(list)
        for g in goods.values():
            for b, p in (g.get("biomeOutput") or {}).items():
                if p:
                    by_biome[int(b)].append((g["i"], p))
        pop, biome, good = m.cell("pop"), m.cell("biome"), m.cell("good")
        culture, state, religion, burg = m.cell("culture"), m.cell("state"), m.cell("religion"), m.cell("burg")
        burgs, cultures = m.data["burgs"], m.data["cultures"]

        def modifier(g, c):
            mult = g.get("multipliers")
            if not mult:
                return 1.0
            b = burg[c]
            ctype = (burgs[b].get("type") if b else cultures[culture[c]].get("type")) or "Generic"
            v = ((mult.get("cultureType") or {}).get(ctype, 1) * (mult.get("culture") or {}).get(str(culture[c]), 1)
                 * (mult.get("state") or {}).get(str(state[c]), 1) * (mult.get("religion") or {}).get(str(religion[c]), 1)
                 * (mult.get("biome") or {}).get(str(biome[c]), 1))
            for zid, val in (mult.get("zone") or {}).items():
                if int(zid) in zones.get(c, ()):
                    v *= val
            return v

        out = {}
        for c in range(m.cell_count):
            water = typ[c] != 0
            p = sum(pop[n] for n in geo.neighbors[c]) if water else pop[c]
            if p <= 0:
                continue
            made = defaultdict(float)
            for gid, rate in by_biome.get(biome[c], ()):
                made[gid] += p * rate * modifier(goods[gid], c)
            if good[c] and good[c] in goods:
                made[good[c]] += min(p * 0.25, 5) * modifier(goods[good[c]], c)
            made = {str(k): round(v, 2) for k, v in made.items() if round(v, 2) > 0}
            if made:
                out[str(c)] = made
        return out

    def _trade(self) -> dict:
        """Deals grouped per burg (bought/sold by good) and per market (flows between markets)."""
        m = self.m
        markets = {mk["i"]: mk for mk in m.data["markets"] if isinstance(mk, dict)}
        burg_buy = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        burg_sell = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        mk_flow = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        for d in m.data["deals"]:
            u, val = d.get("units", 0), d.get("units", 0) * d.get("price", 0)
            g = str(d["good"])
            if d["buyerType"] == "burg":
                rec = burg_buy[d["buyer"]][g]
                rec[0] += u
                rec[1] += val
            if d["sellerType"] == "burg":
                rec = burg_sell[d["seller"]][g]
                rec[0] += u
                rec[1] += val
            if d["sellerType"] == "market" and d["buyerType"] == "market":
                rec = mk_flow[f'{d["seller"]}>{d["buyer"]}'][g]
                rec[0] += u
                rec[1] += val

        def fmt(dd):
            return {g: [round(a, 2), round(b, 2)] for g, (a, b) in sorted(dd.items(), key=lambda kv: -kv[1][1])}
        return {
            "buy": {str(b): fmt(v) for b, v in burg_buy.items()},
            "sell": {str(b): fmt(v) for b, v in burg_sell.items()},
            "flows": {k: fmt(v) for k, v in mk_flow.items()},
            "deals": len(m.data["deals"]),
        }

    def _burgs(self) -> list:
        out = [None]
        for b in self.m.data["burgs"][1:]:
            if not isinstance(b, dict) or b.get("removed"):
                out.append(None)
                continue
            prod = defaultdict(float)
            recipes = {}
            for rec in b.get("production") or []:
                if "goodId" in rec:
                    prod[str(rec["goodId"])] += rec.get("units", 0)
                    if rec.get("recipe"):
                        recipes[str(rec["goodId"])] = [[x["goodId"], x["units"]] for x in rec["recipe"]]
            keep = {k: b.get(k) for k in ("i", "name", "cell", "x", "y", "state", "culture", "feature", "capital",
                                          "port", "type", "group", "citadel", "walls", "shanty", "temple", "plaza",
                                          "market", "treasury", "product") if b.get(k) is not None}
            keep["population"] = r2(b.get("population", 0), 3)
            keep["production"] = {k: round(v, 2) for k, v in prod.items()}
            keep["recipes"] = recipes
            c, r = self.grid.at(b["x"], b["y"])
            keep["t"] = [c, r]
            out.append(keep)
        return out

    def _states(self) -> list:
        out = []
        for s in self.m.data["states"]:
            if not isinstance(s, dict):
                out.append(None)
                continue
            keep = {k: s.get(k) for k in ("i", "name", "fullName", "form", "formName", "type", "capital", "center",
                                          "culture", "color", "salesTax", "pollTax", "treasury", "neighbors",
                                          "diplomacy", "campaigns", "urban", "rural", "burgs", "area", "cells",
                                          "provinces", "alert", "expansionism", "removed") if s.get(k) is not None}
            out.append(keep)
        return out

    def _military(self) -> list:
        units = []
        for s in self.m.live("states"):
            for u in s.get("military") or []:
                note, _ = clean_note(u.get("note", ""))
                c, r = self.grid.at(u["x"], u["y"])
                units.append({"state": s["i"], "i": u.get("i"), "name": u.get("name"), "x": u["x"], "y": u["y"],
                              "t": [c, r], "cell": u.get("cell"), "a": u.get("a"), "u": u.get("u"),
                              "naval": bool(u.get("n")), "icon": u.get("icon"), "note": note,
                              "base": [u.get("bx"), u.get("by")]})
        return units

    def _markers(self) -> list:
        out = []
        for mk in self.m.live("markers"):
            note, links = clean_note(mk.get("note", ""))
            c, r = self.grid.at(mk["x"], mk["y"])
            out.append({"i": mk["i"], "type": mk.get("type"), "name": mk.get("name", ""), "icon": mk.get("icon", ""),
                        "x": mk["x"], "y": mk["y"], "cell": mk["cell"], "t": [c, r], "note": note, "links": links})
        return out

    def _journeys(self) -> list:
        tr = {t["name"]: t for t in self.m.settings.get("transports", [])}
        out = []
        for j in self.m.data["journeys"]:
            segs = []
            for s in j["segments"]:
                t = tr.get(s["transport"], {"speed": s.get("speed", 0), "hoursPerDay": 24, "domain": "land"})
                miles = s.get("distance", 0) * self.m.mi_per_px
                pts = [[r2(p[0], 2), r2(p[1], 2), p[2] if len(p) > 2 else None] for p in s.get("points", [])]
                segs.append({"i": s["i"], "name": s["name"], "from": s["from"], "to": s["to"],
                             "transport": s["transport"], "speed": s.get("speed") or t.get("speed", 0),
                             "hoursPerDay": t.get("hoursPerDay", 24), "domain": t.get("domain", "land"),
                             "miles": round(miles, 1), "duration": s.get("duration"), "points": pts})
            out.append({"name": j["name"], "type": j.get("type"), "color": j.get("color"), "segments": segs})
        return out

    def _ice(self) -> np.ndarray:
        g = self.grid
        img = Image.new("L", (g.cols, g.rows), 0)
        dr = ImageDraw.Draw(img)
        for ice in self.m.data.get("ice") or []:
            pts = [((x - g.ox) / g.size - 0.5, (y - g.oy) / g.size - 0.5) for x, y in ice.get("points", [])]
            if len(pts) >= 3:
                dr.polygon(pts, fill=2 if ice.get("type") == "glacier" else 1)
        return np.array(img, dtype=np.uint8)

    def tables(self) -> dict:
        m = self.m
        st = m.settings
        cultures = [c for c in m.data["cultures"]]
        nb = NameBases(m.namebase_overrides())
        used = sorted({c.get("base", 0) for c in cultures if isinstance(c, dict)})
        feats = [None] + [{k: f.get(k) for k in ("i", "type", "subtype", "group", "name", "land", "border", "cells",
                                                   "area", "height")} for f in m.data["features"][1:] if isinstance(f, dict)]
        rivers = {str(r["i"]): {k: r.get(k) for k in ("i", "name", "type", "length", "width", "discharge", "source",
                                                      "mouth", "parent", "basin")} for r in m.data["rivers"]}
        routes = [{"i": r.get("i", k), "name": r.get("name", ""), "group": r.get("group"), "feature": r.get("feature"),
                   "length": round(sum(((r["points"][q + 1][0] - r["points"][q][0]) ** 2 +
                                        (r["points"][q + 1][1] - r["points"][q][1]) ** 2) ** 0.5
                                       for q in range(len(r["points"]) - 1)) * m.mi_per_px, 1)}
                  for k, r in enumerate(m.data["routes"]) if isinstance(r, dict)]
        markets = []
        for mk in m.data["markets"]:
            if isinstance(mk, dict):
                markets.append({"i": mk["i"], "centerBurgId": mk.get("centerBurgId"), "color": mk.get("color"),
                                "goods": {g: [r2(v.get("stock", 0)), r2(v.get("price", 0))] for g, v in (mk.get("goods") or {}).items()}})
        return {
            "format": FORMAT,
            "world": {"name": m.name, "folder": self.folder, "file": m.path.name, "cells_file": self.cells_path.name,
                      "version": m.version, "seed": m.seed, "width": st["graph"]["width"], "height": st["graph"]["height"],
                      "coords": st["geography"]["coordinates"], "climate": st.get("climate"),
                      "calendar": m.calendar, "units": st["units"], "transports": st.get("transports", []),
                      "relief": (st.get("relief") or {}).get("rules"), "military": st.get("military"),
                      "burgGroups": [g.get("name") for g in (st.get("burgs") or {}).get("groups", [])]},
            "grid": self.grid.to_dict(),
            "gridcells": {"spacing": m.data["grid"]["spacing"], "cellsX": m.data["grid"]["cellsX"],
                          "cellsY": m.data["grid"]["cellsY"], "h": m.data["grid_h"], "temp": m.data["grid_temp"],
                          "prec": m.data["grid_prec"]},
            "cells": self._cells(),
            "biomes": [{k: b.get(k) for k in ("i", "name", "color", "habitability", "cost", "icons", "iconsDensity")}
                       for b in m.data["biomes"]],
            "features": feats,
            "states": self._states(),
            "provinces": [None if not isinstance(p, dict) else {k: p.get(k) for k in ("i", "state", "center", "burg", "name", "formName", "fullName", "color", "removed")} for p in m.data["provinces"]],
            "cultures": [{k: c.get(k) for k in ("i", "name", "base", "type", "color", "center", "expansionism", "origins", "shield", "code", "removed")} for c in cultures],
            "religions": [{k: r.get(k) for k in ("i", "name", "type", "form", "culture", "center", "deity", "expansion", "color", "origins", "code", "removed")} for r in m.data["religions"]],
            "burgs": self._burgs(),
            "rivers": rivers,
            "routes": routes,
            "markers": self._markers(),
            "zones": [{k: z.get(k) for k in ("i", "name", "type", "color", "cells")} for z in m.live("zones")],
            "goods": [{k: g.get(k) for k in ("i", "name", "tags", "icon", "color", "value", "unit", "recipes", "demandCoverage", "biomeOutput")} for g in m.data["goods"]],
            "markets": markets,
            "trade": self._trade(),
            "military": self._military(),
            "journeys": self._journeys(),
            "namebases": {str(i): nb.bases[i] for i in used if i < len(nb.bases)},
            "report": self.raster.report,
        }

    # ------------------------------------------------------------------ binary
    def build(self) -> bytes:
        rs = self.raster
        h = rs.height.astype(np.int16)
        hdelta = np.empty_like(rs.height)
        hdelta[:, 0] = rs.height[:, 0]
        hdelta[:, 1:] = ((h[:, 1:] - h[:, :-1]) % 256).astype(np.uint8)
        blobs = [("cell", "u16", "raw", rs.cell), ("height", "u8", "rowdelta", hdelta),
                 ("croute", "u8", "raw", rs.conn_route), ("cwater", "u8", "raw", rs.conn_water),
                 ("river", "u16", "raw", rs.river), ("route", "u16", "raw", rs.route), ("ice", "u8", "raw", self._ice())]
        meta = self.tables()
        meta["rasters"] = {}
        body = bytearray()
        for name, kind, enc, arr in blobs:
            data = np.ascontiguousarray(arr).astype("<u2" if kind == "u16" else "u1").tobytes()
            if len(body) % 2:
                body += b"\0"
            meta["rasters"][name] = {"offset": len(body), "length": len(data), "type": kind, "encoding": enc}
            body += data
        js = json.dumps(meta, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        raw = b"AZRP" + struct.pack("<I", len(js)) + js + bytes(body)
        return gzip.compress(raw, 9)

    def build_b64(self) -> str:
        return base64.b64encode(self.build()).decode("ascii")
