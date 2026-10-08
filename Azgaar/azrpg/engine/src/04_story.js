// ---------------------------------------------------------------------------------------------
// Story: the plan clock, the journey (plan versus record), the traveller generated for each
// playthrough, and every piece of text the world speaks. Text is assembled from data and tagged:
// (data) read from the files, (mixed) a stated rule applied to data, (new) invented here.
// ---------------------------------------------------------------------------------------------
AZ.T = k => `<span class="tag t-${k}">${k}</span>`;

AZ.Clock = {
  doy0: 80, // spring equinox by default
  dayLength(lat, doy) {
    const decl = (23.44 * Math.sin((2 * Math.PI * (284 + doy)) / 365) * Math.PI) / 180;
    const x = -Math.tan((lat * Math.PI) / 180) * Math.tan(decl);
    if (x >= 1) return 0;
    if (x <= -1) return 24;
    return (2 * Math.acos(x) * 180) / Math.PI / 15;
  },
  sun(t, lat) {
    const day = Math.floor(t / 24), hour = t - day * 24, dl = this.dayLength(lat, (this.doy0 + day) % 365);
    return { day, hour, dl, rise: 12 - dl / 2, set: 12 + dl / 2 };
  },
  light(t, lat) {
    const s = this.sun(t, lat);
    if (s.dl >= 24) return { a: 0, phase: "day" };
    if (s.dl <= 0) return { a: 0.55, rgb: [70, 84, 150], phase: "night" };
    const h = s.hour;
    const dist = h < s.rise ? s.rise - h : h > s.set ? h - s.set : -Math.min(h - s.rise, s.set - h);
    if (dist <= -1) return { a: 0, phase: "day" };
    if (dist <= 0) return { a: 0.25 * (1 + dist), rgb: [255, 190, 140], phase: h < 12 ? "dawn" : "dusk" };
    if (dist <= 1) return { a: 0.25 + 0.3 * dist, rgb: AZ.U.mix([255, 190, 140], [70, 84, 150], dist).map(Math.round), phase: h < 12 ? "dawn" : "dusk" };
    return { a: 0.55, rgb: [70, 84, 150], phase: "night" };
  },
  nextDawn(t, lat) {
    const s = this.sun(t, lat);
    let dawn = s.day * 24 + Math.max(0, s.rise);
    if (dawn <= t) dawn = (s.day + 1) * 24 + Math.max(0, this.sun((s.day + 1) * 24, lat).rise);
    return dawn;
  },
  fmt(t) {
    const day = Math.floor(t / 24), h = t - day * 24, hh = Math.floor(h), mm = Math.floor((h - hh) * 60);
    return `Day ${day + 1}, ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  },
  span(h) {
    const neg = h < 0; h = Math.abs(h);
    const d = Math.floor(h / 24), r = Math.round(h - d * 24);
    const s = d ? `${d} d ${r} h` : `${r} h`;
    return neg ? "-" + s : s;
  },
};

AZ.Journey = class {
  constructor(w, J) {
    this.w = w; this.J = J;
    const U = AZ.U;
    let t = 6; // Day 1, 06:00: the plan departs at dawn
    this.course = new Set();
    this.segs = J.segments.map((s, k) => {
      const seg = { ...s, k, moving: (s.transport !== "Stay" && s.domain !== "stay" && s.speed > 0) };
      const pts = s.points.length ? s.points : [[0, 0, s.from]];
      seg.startTile = w.tileAt(pts[0][0], pts[0][1]);
      seg.endTile = w.tileAt(pts[pts.length - 1][0], pts[pts.length - 1][1]);
      seg.planStart = t;
      if (!seg.moving) t += s.duration || 0;
      else {
        let rem = s.miles / s.speed;
        seg.travelHours = rem;
        if (s.hoursPerDay >= 24) t += rem;
        else {
          const lat = w.latlon(...seg.startTile)[0];
          let guard = 0;
          while (rem > 1e-6 && guard++ < 5000) {
            const sun = AZ.Clock.sun(t, lat), dawn = sun.day * 24 + Math.max(0, sun.rise);
            if (t < dawn) t = dawn;
            const end = dawn + s.hoursPerDay, avail = end - t;
            if (avail <= 1e-6) { t = (sun.day + 1) * 24 + Math.max(0, AZ.Clock.sun((sun.day + 1) * 24, lat).rise); continue; }
            const use = Math.min(avail, rem);
            t += use; rem -= use;
          }
        }
        seg.chain = this.chain(pts);
        seg.chainPos = new Map(seg.chain.map(([c, r], i) => [w.idx(c, r), i]));
        seg.chain.forEach(([c, r]) => this.course.add(w.idx(c, r)));
      }
      seg.planEnd = t;
      seg.place = this.placeFor(seg);
      seg.verb = /book|passage|hire/i.test(s.name) ? "booking" : /alms|rest|shelter|inn|lodg|pray/i.test(s.name) ? "rest" : /anchor|stopp|night|wait/i.test(s.name) ? "anchor" : "stay";
      return seg;
    });
    this.planEnd = t;
    this.replan();
    this.totalMiles = this.segs.reduce((a, s) => a + (s.moving ? s.miles : 0), 0);
    this.origin = this.segs[0].place;
    this.dest = this.segs[this.segs.length - 1].place;
    void U;
  }
  // the plan's times for the current departure day: Day 1 starts at dawn at the origin, and modes
  // with fewer than 24 hours a day sail from dawn for their hours each day
  replan() {
    const w = this.w, lat0 = w.latlon(...this.segs[0].startTile)[0];
    let t = AZ.Clock.sun(0, lat0).rise;
    if (!isFinite(t) || t < 0 || t > 12) t = 6;
    this.t0 = t;
    for (const seg of this.segs) {
      seg.planStart = t;
      if (!seg.moving) t += seg.duration || 0;
      else if (seg.hoursPerDay >= 24) t += seg.travelHours;
      else {
        const lat = w.latlon(...seg.startTile)[0];
        let rem = seg.travelHours, guard = 0;
        while (rem > 1e-6 && guard++ < 5000) {
          const sun = AZ.Clock.sun(t, lat), dawn = sun.day * 24 + Math.max(0, sun.rise);
          if (t < dawn) t = dawn;
          const avail = dawn + seg.hoursPerDay - t;
          if (avail <= 1e-6) { t = (sun.day + 1) * 24 + Math.max(0, AZ.Clock.sun((sun.day + 1) * 24, lat).rise); continue; }
          const use = Math.min(avail, rem);
          t += use; rem -= use;
        }
      }
      seg.planEnd = t;
    }
    this.planEnd = t;
  }
  chain(pts) {
    const w = this.w, out = [];
    for (let k = 0; k < pts.length - 1; k++) {
      const [x0, y0] = pts[k], [x1, y1] = pts[k + 1];
      const steps = Math.max(1, Math.floor(Math.hypot(x1 - x0, y1 - y0) / (w.size * 0.25)));
      for (let s = 0; s <= steps; s++) {
        const t = s / steps, tile = w.tileAt(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t);
        const last = out[out.length - 1];
        if (!last) out.push(tile);
        else if (tile[0] !== last[0] || tile[1] !== last[1]) {
          if (tile[0] !== last[0] && tile[1] !== last[1]) {
            const a = [tile[0], last[1]], b = [last[0], tile[1]];
            out.push(!w.isLand(...a) ? a : b);
          }
          out.push(tile);
        }
      }
    }
    const clean = [];
    for (const t of out) {
      if (clean.length >= 2 && clean[clean.length - 2][0] === t[0] && clean[clean.length - 2][1] === t[1]) { clean.pop(); continue; }
      const l = clean[clean.length - 1];
      if (!l || l[0] !== t[0] || l[1] !== t[1]) clean.push(t);
    }
    return clean;
  }
  placeFor(seg) {
    const w = this.w, cell = seg.to, bid = w.C.burg[cell];
    if (bid) return { burg: w.P.burgs[bid], name: w.P.burgs[bid].name, tile: w.P.burgs[bid].t, at: true };
    const tile = seg.endTile;
    // a burg named in this stage or in the stay that follows at the same spot ("A night at anchor near Slof")
    const next = this.J.segments[seg.k + 1];
    const texts = [next && next.from === seg.to ? next.name : "", seg.name];
    for (const text of texts) {
      const words = ` ${text.toLowerCase().replace(/[^\p{L}\p{N}'-]+/gu, " ")} `;
      const named = w.P.burgs.filter(b => b && b.name && words.includes(` ${b.name.toLowerCase()} `));
      if (named.length) {
        const b = named.sort((a, c) => Math.hypot(a.t[0] - tile[0], a.t[1] - tile[1]) - Math.hypot(c.t[0] - tile[0], c.t[1] - tile[1]))[0];
        if (Math.hypot(b.t[0] - tile[0], b.t[1] - tile[1]) < 60) return { burg: b, name: `near ${b.name}`, tile, at: false };
      }
    }
    const near = w.near(tile[0], tile[1], 30).find(n => n.kind === "burg");
    if (near) return { burg: near.o, name: `near ${near.o.name}`, tile, at: false };
    return { burg: null, name: w.isLand(...tile) ? "the wilds" : w.waterName(...tile), tile, at: false };
  }
  // where is (c, r) along a moving stage? returns {pos, frac, off}
  progress(seg, c, r) {
    if (!seg.moving) return null;
    const k = seg.chainPos.get(this.w.idx(c, r));
    if (k !== undefined) return { pos: k, frac: k / Math.max(1, seg.chain.length - 1), off: 0 };
    let best = 0, bd = 1e9;
    seg.chain.forEach(([a, b], i) => { const d = Math.hypot(a - c, b - r); if (d < bd) { bd = d; best = i; } });
    return { pos: best, frac: best / Math.max(1, seg.chain.length - 1), off: bd };
  }
  planTimeAt(seg, frac) { return seg.planStart + (seg.planEnd - seg.planStart) * (frac ?? 0); }
};

// ---------------------------------------------------------------------------------------------
// Knowledge: the text layer
// ---------------------------------------------------------------------------------------------
AZ.Know = class {
  constructor(w, jr, tv) {
    this.w = w; this.jr = jr; this.tv = tv;
    this.C = AZ.CONTENT || {};
    this.facts = this.buildFacts();
  }
  get P() { return this.w.P; }
  year() { return this.w.W.calendar?.year || 0; }
  era() { return this.w.W.calendar?.eraShort || ""; }
  st(i) { return this.P.states[i]; }
  rel(a, b) { const s = this.st(a); return a === b ? "Self" : s?.diplomacy?.[b] || "Unknown"; }
  sightTiles(c, r, aboard) { if (aboard || !this.w.isLand(c, r)) return 4; return Math.min(10, 4 + Math.floor(Math.max(0, this.w.heightVal(this.w.h(c, r))) / 1500)); }
  dirDist(c, r, t) {
    const U = AZ.U, mi = Math.hypot(t[0] - c, t[1] - r) * this.w.miles;
    return { dir: U.compass(t[0] - c, t[1] - r), mi, txt: `${U.num(Math.round(mi / 5) * 5)} mi ${U.compass(t[0] - c, t[1] - r)}` };
  }
  person(seedKey, cultureId) {
    const rnd = AZ.U.rng(`${this.w.P.world.seed}:${seedKey}`);
    const cul = this.P.cultures[cultureId] || this.P.cultures[1];
    return this.w.names.get(cul.base, rnd);
  }
  heightBand(ft) {
    const bands = this.C.height || [[0, "low ground"], [300, "rolling country"], [1200, "hills"], [3000, "highlands"], [6000, "mountains"]];
    let b = bands[0][1];
    for (const [v, n] of bands) if (ft >= v) b = n;
    return b;
  }
  feel(tc) { return tc < -10 ? "bitter" : tc < 0 ? "freezing" : tc < 8 ? "cold" : tc < 15 ? "cool" : tc < 22 ? "mild" : tc < 28 ? "warm" : "hot"; }
  wet(mm) { return mm < 250 ? "arid" : mm < 600 ? "dry" : mm < 1200 ? "moist" : mm < 2500 ? "wet" : "drenched"; }

  // ------------------------------------------------------------------ look
  describe(c, r, aboard) {
    const w = this.w, U = AZ.U, T = AZ.T, cell = w.cell(c, r), out = [];
    const rnd = U.rng(U.hash32(c, r, 99));
    if (w.isLand(c, r)) {
      const biome = this.P.biomes[w.C.biome[cell]];
      const bank = this.C.biomes?.[biome.name]?.phrases;
      if (bank) out.push(`${rnd.pick(bank)} ${T("new")}`);
      const ft = w.heightVal(w.h(c, r));
      const rel = w.reliefAt(c, r);
      out.push(`${biome.name}, ${this.heightBand(ft)} about ${U.num(ft < 1000 ? Math.round(ft / 10) * 10 : Math.round(ft / 50) * 50)} ${w.hunit} up${rel ? ` (${rel.rule.toLowerCase()})` : ""} ${T("mixed")}.`);
    } else {
      out.push(`${w.waterName(c, r)}, about ${w.heightStr(w.h(c, r), true)} deep ${T("data")}.`);
      const lat = w.latlon(c, r)[0], wd = w.wind(lat);
      if (wd != null) out.push(`The prevailing wind of this latitude blows towards the ${U.compass(Math.sin(wd * Math.PI / 180), -Math.cos(wd * Math.PI / 180))} ${T("mixed")}.`);
    }
    const tc = w.tempC(c, r), g = AZ.game, lat = w.latlon(c, r)[0], tt = g && g.s ? g.s.clock : 6;
    out.push(`The year here runs ${this.feel(tc)} (mean ${w.temp(tc)})${w.isLand(c, r) ? ` and ${this.wet(w.precMM(c, r))} (${U.num(w.precMM(c, r))} mm a year)` : ""} ${T("data")}.`);
    const today = AZ.Clock.today(tc, lat, tt, !w.isLand(c, r)), dl = AZ.Clock.dayLength(lat, AZ.Clock.doyAt(tt));
    out.push(`It is ${AZ.Clock.season(lat, tt)}: about ${w.temp(today)} today, with ${Math.round(dl)} hours of daylight${today < 0 && w.isLand(c, r) ? "; snow lies on the ground" : ""} ${T("mixed")}.`);
    const rv = w.river(c, r);
    if (rv) out.push(`The ${rv.name} ${rv.type || "River"} runs through here ${T("data")}.`);
    const rt = w.route(c, r);
    if (rt) out.push(`${rt.group === "searoutes" ? "You are on a sea lane" : rt.group === "trails" ? "A trail passes" : "A road passes"}: the ${rt.name || "unnamed way"}, ${U.num(rt.length)} mi end to end ${T("data")}.`);
    if (w.isLand(c, r)) {
      const s = w.C.state[cell], pv = w.C.province[cell];
      const realm = s ? this.st(s).fullName : "neutral lands";
      out.push(`${pv ? this.P.provinces[pv].fullName + ", " : ""}${realm}; ${this.P.cultures[w.C.culture[cell]].name} country, keeping the ${this.P.religions[w.C.religion[cell]].name} ${T("data")}.`);
    }
    for (const z of w.zonesOfCell(cell)) out.push(`<b class="hook">${z.name}</b>: this ground lies in a ${z.type.toLowerCase()} zone ${T("data")}.`);
    const sight = this.sightTiles(c, r, aboard);
    const seen = w.near(c, r, sight).filter(n => n.d > 0.5).slice(0, 5);
    if (seen.length) {
      out.push("In sight: " + seen.map(n => `${n.o.name || n.o.type} (${this.dirDist(c, r, n.o.t).txt})`).join("; ") + ` ${T("data")}.`);
    }
    return out;
  }

  // ------------------------------------------------------------------ inspector
  inspect(c, r, g) {
    const w = this.w, U = AZ.U, T = AZ.T, P = this.P, cell = w.cell(c, r), land = w.isLand(c, r);
    const row = (k, v, t = "data") => `<tr><th>${k}</th><td>${v} ${T(t)}</td></tr>`;
    const sec = (title, rows) => (rows.length ? `<h4>${title}</h4><table>${rows.join("")}</table>` : "");
    const [lat, lon] = w.latlon(c, r);
    const f = w.feature(cell);
    const here = [
      row("Tile", `${c}, ${r} · ${U.num(w.miles, 2)} mi square`, "mixed"),
      row("Cell", `${cell}${f ? ` · ${f.name || ""} ${f.subtype || f.type}` : ""}`),
      row("Position", `${U.dms(lat, "lat")} ${U.dms(lon, "lon")} · ${w.geozone(lat)}`),
    ];
    const land1 = [];
    if (land) {
      const b = P.biomes[w.C.biome[cell]];
      land1.push(row("Biome", `${b.name} · habitability ${b.habitability} · move cost ${b.cost}`));
      land1.push(row("Elevation", `${U.num(w.C.hft[cell])} ${w.hunit} (cell)`));
      land1.push(row("Here", `${w.heightStr(w.h(c, r))}${w.reliefAt(c, r) ? " · " + w.reliefAt(c, r).rule : ""}`, "mixed"));
      land1.push(row("Precipitation", `${U.num(w.precMM(c, r))} mm`));
    } else {
      land1.push(row("Water", w.waterName(c, r)));
      land1.push(row("Depth", w.heightStr(w.h(c, r), true), "mixed"));
      const wd = w.wind(lat);
      if (wd != null) land1.push(row("Wind band", `towards ${U.compass(Math.sin(wd * Math.PI / 180), -Math.cos(wd * Math.PI / 180))} (${wd}°)`));
    }
    land1.push(row("Temperature", `${w.temp(w.tempC(c, r))} mean`));
    const tt = g && g.s ? g.s.clock : 6;
    land1.push(row("Season", `${AZ.Clock.season(lat, tt)} · about ${w.temp(AZ.Clock.today(w.tempC(c, r), lat, tt, !land))} today · ${Math.round(AZ.Clock.dayLength(lat, AZ.Clock.doyAt(tt)))} h daylight`, "mixed"));
    const rv = w.river(c, r);
    if (rv) land1.push(row("River", `${rv.name} ${rv.type} · ${U.num(rv.length)} km · discharge ${U.num(rv.discharge)} m³/s`));
    const rt = w.route(c, r);
    if (rt) land1.push(row("Route", `${rt.name || "unnamed"} (${rt.group}) · ${U.num(rt.length)} mi`));
    const realm = [];
    if (land || w.C.state[cell]) {
      const s = this.st(w.C.state[cell]);
      realm.push(row("State", w.C.state[cell] ? `${s.fullName} · ${s.form} · taxes ${Math.round(s.salesTax * 100)}% sales, ${Math.round(s.pollTax * 100)}% poll · treasury ${U.num(s.treasury)}` : "neutral lands"));
      const pv = w.C.province[cell];
      if (pv) realm.push(row("Province", P.provinces[pv].fullName));
    }
    const cu = P.cultures[w.C.culture[cell]], re = P.religions[w.C.religion[cell]];
    if (w.C.culture[cell]) realm.push(row("Culture", `${cu.name} · ${cu.type}`));
    if (w.C.religion[cell]) realm.push(row("Religion", `${re.name} · ${re.type}${re.form ? ", " + re.form : ""}${re.deity ? " · " + re.deity : ""}`));
    const [ru, ur] = w.population(cell);
    if (land) realm.push(row("Population", `${U.si(ru + ur)} (${U.si(ru)} rural, ${U.si(ur)} urban)`));
    const b = w.burgAt.get(w.idx(c, r));
    const burg = [];
    if (b) {
      const feats = ["capital", "port", "walls", "citadel", "plaza", "temple", "shanty"].filter(k => b[k]).join(", ");
      burg.push(row("Burg", `${b.name} · ${b.group}, ${b.type} · ${U.si(b.population * (w.W.units.population?.scale || 1000))}`));
      if (feats) burg.push(row("Has", feats));
      burg.push(row("Treasury", `${U.num(b.treasury, 2)} · product ${U.num(b.product, 2)}`));
      const goods = Object.entries(b.production || {}).sort((a, bb) => bb[1] - a[1]).slice(0, 6).map(([g, u]) => `${this.good(g)} ${u}`).join(", ");
      if (goods) burg.push(row("Makes", goods));
      const sells = this.tradeList(P.trade.sell[b.i]), buys = this.tradeList(P.trade.buy[b.i]);
      if (sells) burg.push(row("Sells to market", sells));
      if (buys) burg.push(row("Buys from market", buys));
    }
    const eco = [];
    if (w.C.good[cell]) eco.push(row("Resource", this.good(w.C.good[cell])));
    const prod = w.C.prod[String(cell)];
    if (prod) eco.push(row("Rural output", Object.entries(prod).sort((a, bb) => bb[1] - a[1]).slice(0, 6).map(([g, u]) => `${this.good(g)} ${u}`).join(", "), "mixed"));
    const mk = P.markets.find(m => m.i === w.C.market[cell]);
    if (mk) {
      const local = Object.keys(prod || {}).slice(0, 4).map(g => mk.goods[g] ? `${this.good(g)} ${mk.goods[g][1]}` : null).filter(Boolean).join(", ");
      eco.push(row("Market", `${P.burgs[mk.centerBurgId]?.name} market${local ? " · prices: " + local : ""}`));
    }
    const lore = [];
    for (const z of w.zonesOfCell(cell)) lore.push(row("Zone", `<b class="hook">${z.name}</b> (${z.type})`));
    for (const n of w.near(c, r, 4)) {
      if (n.kind === "burg" && n.d < 0.5) continue;
      if (n.kind === "marker") lore.push(row(n.d < 0.5 ? "Here" : this.dirDist(c, r, n.o.t).txt, `<b class="side">${U.esc(n.o.name)}</b>: ${U.esc((n.o.note || "").slice(0, 160))}`));
      else if (n.kind === "unit") lore.push(row(n.d < 0.5 ? "Here" : this.dirDist(c, r, n.o.t).txt, `${U.esc(n.o.name)} of ${this.st(n.o.state).name}, ${U.num(n.o.a)} ${n.o.naval ? "crew" : "troops"}`));
      else if (n.kind === "burg") lore.push(row(this.dirDist(c, r, n.o.t).txt, `${n.o.name} (${n.o.group})`));
    }
    const jr = [];
    if (g && g.cpNext) {
      const cp = g.cpNext();
      if (cp) {
        jr.push(row("Next checkpoint", `<b class="hook">${cp.i}. ${U.esc(cp.place.name)}</b> · par ${AZ.Clock.fmt(cp.parArrive)}${cp.legIn ? " · plan: " + U.esc(cp.legIn.transport) : ""}`, "mixed"));
        const pr = cp.legIn ? this.jr.progress(cp.legIn, c, r) : null;
        if (pr) jr.push(row("Plan's course", `${Math.round(pr.frac * 100)}% of the leg${pr.off ? `, ${U.num(pr.off * w.miles)} mi off it` : ", on it"}`, "mixed"));
      }
      if (g.fishYield) {
        const fy = g.fishYield(c, r), fo = g.forageYield(c, r);
        jr.push(row("Provisions", `fishing: ${fy.why || `about ${fy.n} rations in 6 h (${fy.where})`}; foraging: ${fo.why || `about ${fo.n} in 6 h (${fo.where})`}`, "mixed"));
      }
      const wx = g.weather();
      jr.push(row("Weather", `${wx.label} (from ${U.num(w.precMM(c, r))} mm a year, ${AZ.Clock.season(lat, g.s.clock)})`, "mixed"));
    }
    return `<div class="insp-head">${U.esc(b ? b.name : land ? (w.C.province[cell] ? P.provinces[w.C.province[cell]].name : "Wilds") : w.waterName(c, r))}</div>` +
      sec("Here", here) + sec(land ? "Land" : "Water", land1) + sec("Realm", realm) + sec("Settlement", burg) + sec("Economy", eco) + sec("Nearby (4 tiles)", lore) + sec("Journey", jr);
  }
  good(id) { const g = this.P.goods.find(x => x.i === +id); return g ? g.name : `good ${id}`; }
  tradeList(t) { if (!t) return ""; return Object.entries(t).slice(0, 4).map(([g, [u]]) => `${this.good(g)} ${u}`).join(", "); }

  // ------------------------------------------------------------------ rumours of distant things
  buildFacts() {
    const w = this.w, P = this.P, out = [], yr = this.year();
    for (const z of P.zones) {
      if (!z.cells?.length) continue;
      let x = 0, y = 0;
      for (const cc of z.cells) { x += w.C.cx[cc]; y += w.C.cy[cc]; }
      const t = w.tileAt(x / z.cells.length, y / z.cells.length);
      out.push({ t, kind: "zone", name: z.name, type: z.type, region: this.regionName(z.cells[0]) });
    }
    for (const s of P.states) {
      if (!s || !s.campaigns) continue;
      for (const cp of s.campaigns) if (cp.end == null && cp.attacker === s.i && cp.start >= yr - 3) {
        const cap = P.burgs[s.capital];
        if (cap) out.push({ t: cap.t, kind: "war", name: cp.name, a: s.name, d: P.states[cp.defender]?.name, start: cp.start });
      }
    }
    for (const m of P.markers) if (/monster|volcano|dungeon|ruins|portal|rift|necrop|burial|pirate|brigand|circus|fair|joust|librar/.test(m.type)) out.push({ t: m.t, kind: "marker", name: m.name, type: m.type, region: this.regionName(m.cell) });
    return out;
  }
  regionName(cell) { const s = this.w.C.state[cell], pv = this.w.C.province[cell]; return pv ? this.P.provinces[pv].name : s ? this.P.states[s].name : "the wild lands"; }
  rumour(c, r, rnd, g) {
    const U = AZ.U, T = AZ.T, w = this.w;
    if (!this.facts.length) return null;
    const scored = this.facts.map(f => ({ f, d: Math.hypot(f.t[0] - c, f.t[1] - r) * w.miles })).map(o => ({ ...o, wt: 1 / (1 + o.d / 400) }));
    let roll = rnd() * scored.reduce((a, o) => a + o.wt, 0), pick = scored[0];
    for (const o of scored) if ((roll -= o.wt) <= 0) { pick = o; break; }
    const { f, d } = pick, dir = U.compass(f.t[0] - c, f.t[1] - r);
    const near = d < 300, mid = d < 1500;
    const where = near ? `${U.num(Math.round(d / 10) * 10)} miles ${dir}` : mid ? `somewhere ${dir}, ${U.num(Math.round(d / 250) * 250)} miles off or so` : `far to the ${dir}, past where anyone here has been`;
    let s;
    if (f.kind === "war") s = near || mid ? `${f.a} has been at war with ${f.d} since ${f.start}, ${where}.` : `There is a war ${where}; the names change with each sailor who tells it.`;
    else if (f.kind === "zone") {
      const what = { Disease: "a sickness", Invasion: "an invading army", Rebels: "rebels in arms", Proselytism: "missionaries working the villages", Crusade: "a crusade", Disaster: "a dearth, and hungry people", Eruption: "a mountain breathing fire", Avalanche: "an avalanche that buried a valley", Fault: "the ground splitting open", Flood: "a great flood", Tsunami: "a wave that came out of the sea" }[f.type] || `trouble (${f.type})`;
      s = near ? `${U.cap(what)} in ${f.region}: they call it the ${f.name}, ${where}.` : mid ? `${U.cap(what)}, ${where}, in ${f.region}.` : `${U.cap(what)}, ${where}.`;
    } else {
      const thing = f.type.replace(/s$/, "").replace(/-/g, " ");
      s = near ? `${f.name}: ${where}. Ask about it if you go that way.` : mid ? `People speak of ${U.article(thing)} ${where}, in ${f.region}.` : `There are stories of ${U.article(thing)} ${where}. Bigger with every telling.`;
    }
    if (g && this.rumourLead) this.rumourLead(g, f, d);
    return `${s} ${T("mixed")}`;
  }

  // ------------------------------------------------------------------ people in a town
  townPeople(b, g) {
    const w = this.w, P = this.P, U = AZ.U, T = AZ.T, tv = this.tv;
    const cell = b.cell, s = this.st(b.state), cu = P.cultures[b.culture], re = P.religions[w.C.religion[cell]];
    const kin = b.culture === tv.culture, faith = w.C.religion[cell] === tv.faith;
    const occ = AZ.sim && AZ.sim.occupied[b.i] != null && AZ.sim.occupied[b.i] !== b.state ? AZ.sim.occupied[b.i] : null;
    let rel = (occ ?? b.state) ? (AZ.sim ? AZ.sim.rel(tv.homeState, occ ?? b.state) : this.rel(tv.homeState, b.state)) : "Unknown";
    const sst = (g.s?.stand?.s || {})[b.state] || 0;
    if (sst <= -2 && rel !== "Enemy") rel = "Suspicion";
    if (sst >= 2 && (rel === "Suspicion" || rel === "Rival")) rel = "Neutral";
    const people = [];
    const nm = role => this.person(`${b.i}:${role}`, b.culture);
    const greet = kin ? `speaks to you in your own ${cu.name} tongue` : `takes you in: a ${P.cultures[tv.culture].name} stranger`;
    if (b.port) people.push({ role: "Harbourmaster", name: nm("harbour"), talk: () => {
      const lanes = new Set();
      for (let dr = -2; dr <= 2; dr++) for (let dc = -2; dc <= 2; dc++) {
        const cc = b.t[0] + dc, rr = b.t[1] + dr;
        if (!w.inb(cc, rr)) continue;
        const rt = w.route(cc, rr);
        if (rt && rt.group === "searoutes" && rt.name) lanes.add(rt.name);
      }
      const fleets = P.military.filter(u => u.naval && u.state === b.state && Math.hypot(u.t[0] - b.t[0], u.t[1] - b.t[1]) < 6);
      const pir = w.near(b.t[0], b.t[1], 60).filter(n => n.kind === "marker" && /pirate|sea-monster/.test(n.o.type));
      const L = [`${nm("harbour")}, harbourmaster of ${b.name}, ${greet} ${T("new")}.`];
      L.push(lanes.size ? `Ships out of here keep to: ${[...lanes].slice(0, 3).join(", ")} ${T("data")}.` : `Few named sea lanes touch ${b.name} ${T("data")}.`);
      if (fleets.length) L.push(`The ${fleets.map(f => f.name).join(" and ")} ${fleets.length > 1 ? "lie" : "lies"} here: ${fleets.map(f => `${f.u?.fleet || "?"} ships`).join(", ")} ${T("data")}.`);
      if (pir.length) L.push(`“Mind the water ${pir[0].dir || U.compass(pir[0].dc, pir[0].dr)}: ${pir[0].o.name.toLowerCase().includes("pirate") ? "pirate sails have been seen" : pir[0].o.name + ", the old sailors say"}, ${U.num(Math.round(pir[0].d * w.miles / 10) * 10)} miles off.” ${T("data")}`);
      return L;
    } });
    people.push({ role: b.group === "hamlet" || b.group === "village" ? "Host at the hearth" : "Innkeeper", name: nm("inn"), talk: () => {
      const L = [`${nm("inn")} keeps the ${b.group === "hamlet" || b.group === "village" ? "only hearth that takes guests" : "inn"} ${T("new")}, and ${greet}.`];
      const inn = w.near(b.t[0], b.t[1], 8).find(n => n.kind === "marker" && n.o.type === "inns");
      if (inn) L.push(`${inn.o.name} is ${this.dirDist(b.t[0], b.t[1], inn.o.t).txt}: ${U.esc(inn.o.note)} ${T("data")}`);
      const food = Object.keys(b.production || {}).map(g => P.goods.find(x => x.i === +g)).filter(g => g && (g.tags || []).some(t => /food|drink/.test(t)));
      if (food.length) L.push(`On the table: ${food.slice(0, 3).map(g => g.name.toLowerCase()).join(", ")}, all made here ${T("data")}.`);
      const rnd = U.rng(`${b.i}:${Math.floor(g.clock / 24)}`);
      const rm = this.rumour(b.t[0], b.t[1], rnd, g);
      if (rm) L.push(`“${rm}`.replace(/ <span/, "” <span"));
      return L;
    } });
    if (Object.keys(b.production || {}).length) people.push({ role: "Merchant", name: nm("market"), talk: () => {
      const mk = P.markets.find(m => m.i === b.market);
      const top = Object.entries(b.production).sort((a, bb) => bb[1] - a[1]).slice(0, 4);
      const L = [`${nm("market")} trades in ${b.name}${mk ? `, which buys and sells through the ${P.burgs[mk.centerBurgId]?.name} market` : ""} ${T("data")}.`];
      L.push(`Made here: ${top.map(([g, u]) => `${this.good(g)} (${u} units)`).join(", ")} ${T("data")}.`);
      const sells = this.tradeList(P.trade.sell[b.i]), buys = this.tradeList(P.trade.buy[b.i]);
      if (sells) L.push(`Sold on: ${sells} ${T("data")}.`);
      if (buys) L.push(`Brought in: ${buys} ${T("data")}.`);
      if (mk) {
        const p = top.map(([g]) => mk.goods[g] ? `${this.good(g)} at ${mk.goods[g][1]}` : null).filter(Boolean);
        if (p.length) L.push(`Market prices: ${p.join(", ")} ${T("data")}.`);
      }
      L.push(`The town's treasury stands at ${U.num(b.treasury, 2)}; its trade earned ${U.num(b.product, 2)} ${T("data")}.`);
      return L;
    } });
    people.push({ role: b.temple ? "Priest" : "Shrine-keeper", name: nm("temple"), talk: () => {
      const L = [`${nm("temple")} keeps the ${b.temple ? "temple" : "shrine"} of the ${re.name}: ${re.type}${re.form ? ", " + re.form : ""}${re.deity ? `; they pray to ${re.deity}` : ""} ${T("data")}.`];
      if (re.center === cell) L.push(`<b class="hook">This is the seat of the ${re.name}.</b> ${T("data")}`);
      const destRel = w.C.religion[this.jr.segs[this.jr.segs.length - 1].to];
      const st = (g.s?.stand?.f || {})[w.C.religion[cell]] || 0;
      if (st <= -2) L.push(`${nm("temple")} knows your name, and not kindly. The door stays shut ${T("mixed")}.`);
      else if (st >= 2 && !faith) L.push(`Word of your kindness to the faith has come ahead of you. You are welcome here ${T("mixed")}.`);
      if (faith) L.push(`You share the faith. ${nm("temple")} blesses ${tv.token} and asks you to carry a prayer to ${this.jr.dest.name} ${T("new")}.`);
      else if (w.C.religion[cell] === destRel) L.push(`You are not of this faith, but your road ends in ${this.jr.dest.name}, and that is enough to be welcome ${T("mixed")}.`);
      else L.push(`You are not of this faith. You are given water and courtesy, no more ${T("mixed")}.`);
      if (w.C.religion[cell] === destRel && re.center !== cell) {
        const seat = P.burgs.find(x => x && x.cell === re.center);
        if (seat) L.push(`The faith's seat is ${seat.name}, ${this.dirDist(b.t[0], b.t[1], seat.t).txt} ${T("data")}.`);
      }
      return L;
    } });
    people.push({ role: b.walls || b.citadel || b.capital ? "Captain of the watch" : "Elder", name: nm("watch"), talk: () => {
      const L = [];
      if (b.state) {
        if (occ) L.push(`<b class="hook">${b.name} is held by ${this.st(occ).fullName}</b> ${T("mixed")}; their officer keeps the gate.`);
        L.push(`${nm("watch")} speaks for ${(occ ? this.st(occ) : s).fullName}, a ${(occ ? this.st(occ) : s).form.toLowerCase()} ${T("data")}. Your people stand to theirs as: <b>${rel}</b> ${T(occ || (AZ.sim && AZ.sim.atWar(tv.homeState, b.state)) ? "mixed" : "data")}.`);
        if (rel === "Enemy") L.push(`You are held and questioned for six hours before they let you go ${T("mixed")}.`);
        else if (rel === "Suspicion" || rel === "Rival") L.push(`They ask your business twice and write your name down ${T("mixed")}.`);
        const wars = (s.campaigns || []).filter(cp => cp.end == null);
        if (wars.length) L.push(`At war: ${wars.map(cp => `${cp.name} (since ${cp.start})`).join("; ")} ${T("data")}.`);
        const allies = (s.diplomacy || []).map((d, i) => (d === "Ally" ? this.st(i)?.name : null)).filter(Boolean);
        if (allies.length) L.push(`Allies: ${allies.join(", ")} ${T("data")}.`);
        const regs = P.military.filter(u => u.state === b.state && !u.naval && Math.hypot(u.t[0] - b.t[0], u.t[1] - b.t[1]) < 8);
        if (regs.length) L.push(`Garrison nearby: ${regs.map(u => `${u.name} (${U.num(u.a)})`).join(", ")} ${T("data")}.`);
        L.push(`Taxes: ${Math.round(s.salesTax * 100)}% on sales, ${Math.round(s.pollTax * 100)}% poll ${T("data")}.`);
      } else L.push(`${nm("watch")} is the eldest here. No state claims ${b.name} ${T("data")}.`);
      return L;
    }, cost: () => (rel === "Enemy" ? 6 : rel === "Suspicion" || rel === "Rival" ? 1 : 0) });
    people.push({ role: "Townsfolk", name: nm("folk"), talk: () => {
      const feats = ["walls", "citadel", "plaza", "temple", "shanty", "port"].filter(k => b[k]);
      const L = [`${b.name}: ${U.article(b.group.replace("_", " "))} of ${U.num(b.population * (w.W.units.population?.scale || 1000))} ${cu.name} people (${b.type}) ${T("data")}${feats.length ? `, with ${feats.join(", ")}` : ""}.`];
      for (const z of w.zonesOfCell(cell)) L.push(`<b class="hook">${z.name}</b> is here: a ${z.type.toLowerCase()} ${T("data")}.`);
      const rnd = U.rng(`${b.i}:folk:${Math.floor(g.clock / 24)}`);
      const rm = this.rumour(b.t[0], b.t[1], rnd, g);
      if (rm) L.push(`Someone says: ${rm}`);
      return L;
    } });
    people.push({ role: "Notice board", name: "", talk: () => {
      const L = [];
      const near = w.near(b.t[0], b.t[1], 24).filter(n => n.kind === "marker");
      for (const n of near.slice(0, 4)) L.push(`<b class="side">${U.esc(n.o.name)}</b>, ${this.dirDist(b.t[0], b.t[1], n.o.t).txt}: ${U.esc((n.o.note || "").slice(0, 140))} ${T("data")}`);
      return L.length ? L : [`Nothing posted but tax notices ${T("new")}.`];
    } });
    return people;
  }

  // ------------------------------------------------------------------ the journey's scenes
  intro(g) {
    const U = AZ.U, T = AZ.T, P = this.P, w = this.w, tv = this.tv, jr = this.jr;
    const o = jr.origin.burg, d = jr.dest.burg;
    const L = [];
    L.push(`<b class="hook">${U.esc(jr.J.name)}</b> ${T("data")}`);
    L.push(`You are ${tv.name}, ${tv.age}, a ${tv.trade} ${T("new")}. ${U.cap(tv.why)} ${T("mixed")}.`);
    if (o) L.push(`You stand in ${o.name}, capital of ${this.st(o.state).fullName}: a ${o.type.toLowerCase()} port of ${U.si(o.population * 1000)} ${P.cultures[o.culture].name} people who keep the ${P.religions[w.C.religion[o.cell]].name} ${T("data")}.`);
    if (d) L.push(`Your goal is ${d.name}, a small capital of ${this.st(d.state).fullName}, ${U.num(jr.totalMiles)} miles away by sea ${T("data")}. The plan gives the voyage ${Math.round((jr.planEnd - jr.t0) / 24)} days ${T("mixed")}.`);
    const destRel = w.C.religion[jr.segs[jr.segs.length - 1].to];
    const seat = P.burgs.find(b => b && b.cell === P.religions[destRel].center);
    if (seat && seat !== d) L.push(`The first port of call is ${seat.name}: the seat of the ${P.religions[destRel].name} itself ${T("data")}.`);
    for (const s of jr.segs) {
      const b = s.place.burg;
      if (b && s.place.at) {
        const r = P.religions.find(x => x && x.center === b.cell && x !== P.religions[destRel]);
        if (r) L.push(`The route also calls at ${b.name}, where the ${r.name} (${r.type.toLowerCase()}) has its seat ${T("data")}.`);
      }
    }
    L.push(`You carry ${tv.token} ${T("new")}. <b class="hook">First: book passage at the harbour of ${jr.origin.name}.</b> Press Space on the town to go in.`);
    void g;
    return [...new Set(L)];
  }
  stageScene(seg, g) {
    const U = AZ.U, T = AZ.T, w = this.w, P = this.P, jr = this.jr;
    const next = jr.segs[seg.k + 1], place = seg.place;
    const b = place.burg, cul = b ? b.culture : w.C.culture[seg.to];
    const L = [`<b class="hook">${U.esc(seg.name)}</b> ${T("data")} · ${seg.duration} h by the plan`];
    if (seg.verb === "booking" && next) {
      const who = this.person(`${b?.i}:harbour`, cul);
      const days = next.hoursPerDay >= 24 ? next.travelHours / 24 : next.travelHours / next.hoursPerDay;
      L.push(`${who}, harbourmaster, finds you a berth on a ${next.transport.toLowerCase()} bound for ${next.place.name}: ${U.num(next.miles)} miles, about ${Math.round(days)} days at ${next.speed} mph and ${next.hoursPerDay} hours' sailing a day ${T("mixed")}.`);
      L.push(`The master will not sail before the tide and the cargo are right. ${seg.duration} hours pass in waiting ${T("new")}.`);
    } else if (seg.verb === "rest") {
      const m = seg.name.match(/\bat (.+)$/i);
      const host = this.person(`${b?.i}:inn`, cul);
      if (m) L.push(`${m[1]} is ${U.article("inn")} in ${b?.name || place.name}; it appears in no record but this journey's ${T("new")}. ${host} keeps it.`);
      if (/alms/i.test(seg.name)) {
        const re = P.religions[w.C.religion[seg.to]];
        L.push(`You give alms at the ${re.center === seg.to ? "seat" : "temple"} of the ${re.name} ${T(re.center === seg.to ? "data" : "mixed")}.`);
      }
      if (/shelter/i.test(seg.name)) L.push(`Weather keeps you ashore; ${host} finds you a corner by the fire ${T("new")}.`);
      L.push(`${seg.duration} hours of rest ${T("data")}.`);
    } else if (seg.verb === "anchor") {
      L.push(`The crew drops anchor ${place.name} for ${seg.duration} hours ${T("data")}.`);
      if (place.burg) L.push(`${place.burg.name} shows as a few lights on the shore: ${U.article(place.burg.group)} of ${U.si(place.burg.population * 1000)} in ${this.st(place.burg.state)?.name || "unclaimed land"} ${T("data")}.`);
    } else L.push(`${seg.duration} hours pass ${T("data")}.`);
    if (next) L.push(`<b class="hook">Next: ${U.esc(next.name)}</b> → ${next.place.name}.`);
    void g;
    return L;
  }
};
