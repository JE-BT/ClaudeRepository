// ---------------------------------------------------------------------------------------------
// Navigation, weather and prices.
//   Water is navigable; a river is navigable when its discharge (data) is large enough for the
//   vessel: boats from 40 m³/s, ships from 400 m³/s (mixed rule). Each port gets a harbour: the
//   nearest navigable tile within a few tiles of the town, reached overland. Courses run only on
//   navigable tiles, following the plan's track where it is on water and joining the gaps by
//   search, so no vessel crosses land.
//   Weather is rolled per day and per region from the map's precipitation, the season and the
//   latitude. Prices come from the town's market (cheapest food, sales tax of the state).
// ---------------------------------------------------------------------------------------------
AZ.NAV = { boat: 40, ship: 400 };
AZ.vesselClass = kind => (/ship|steam|modern/i.test(kind || "") ? "ship" : "boat");

Object.assign(AZ.World.prototype, {
  navigable(c, r, cls = "boat") {
    if (!this.inb(c, r)) return false;
    if (!this.isLand(c, r)) return true;
    if (!(this.R.cwater[r * this.cols + c] >> 4)) return false;
    const rv = this.river(c, r);
    return (rv?.discharge || 0) >= AZ.NAV[cls];
  },
  harbour(b, cls = "boat") {
    this._harb = this._harb || new Map();
    const key = `${b.i}:${cls}`;
    if (this._harb.has(key)) return this._harb.get(key);
    let found = null;
    const seen = new Set([this.idx(b.t[0], b.t[1])]), q = [[b.t[0], b.t[1], 0]];
    while (q.length && !found) {
      const [c, r, d] = q.shift();
      for (const [dc, dr] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        const a = c + dc, e = r + dr, k = this.idx(a, e);
        if (!this.inb(a, e) || seen.has(k)) continue;
        seen.add(k);
        if (this.navigable(a, e, cls)) { found = { t: [a, e], walk: d + 1 }; break; }
        if (d < 3 && this.isLand(a, e)) q.push([a, e, d + 1]); // a harbour is within a short walk of the town, never a distant coast
      }
    }
    this._harb.set(key, found);
    return found;
  },
  // A* on the tile grid; ok(c, r) says whether a tile may be entered; cost(c, r) >= 1
  path(from, to, ok, opts = {}) {
    const N = this.cols * this.rows, cols = this.cols;
    if (!this._astar || this._astar.g.length !== N) this._astar = { g: new Float32Array(N), from: new Int32Array(N), stamp: new Uint32Array(N), gen: 0 };
    const A = this._astar; A.gen++;
    const start = this.idx(from[0], from[1]), goal = this.idx(to[0], to[1]);
    const limit = opts.limit || 400000, cost = opts.cost || (() => 1);
    const heap = [], push = (f, i) => { heap.push([f, i]); let k = heap.length - 1; while (k > 0) { const p = (k - 1) >> 1; if (heap[p][0] <= heap[k][0]) break; [heap[p], heap[k]] = [heap[k], heap[p]]; k = p; } };
    const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let k = 0; for (;;) { const l = 2 * k + 1, r = l + 1; let m = k; if (l < heap.length && heap[l][0] < heap[m][0]) m = l; if (r < heap.length && heap[r][0] < heap[m][0]) m = r; if (m === k) break; [heap[m], heap[k]] = [heap[k], heap[m]]; k = m; } } return top; };
    const h = i => Math.abs((i % cols) - to[0]) + Math.abs(Math.floor(i / cols) - to[1]);
    A.stamp[start] = A.gen; A.g[start] = 0; A.from[start] = -1; push(h(start), start);
    let n = 0;
    while (heap.length && n++ < limit) {
      const [, i] = pop();
      if (i === goal) {
        const out = []; for (let k = i; k !== -1; k = A.from[k]) out.push([k % cols, Math.floor(k / cols)]);
        return out.reverse();
      }
      const c = i % cols, r = Math.floor(i / cols), gi = A.g[i];
      for (const [dc, dr] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        const a = c + dc, e = r + dr;
        if (a < 0 || e < 0 || a >= cols || e >= this.rows) continue;
        const j = e * cols + a;
        if (j !== goal && !ok(a, e)) continue;
        const ng = gi + cost(a, e);
        if (A.stamp[j] === A.gen && A.g[j] <= ng) continue;
        A.stamp[j] = A.gen; A.g[j] = ng; A.from[j] = i;
        push(ng + h(j) * (opts.greed || 1), j);
      }
    }
    return null;
  },
  // are two tiles on the same connected body of navigable water? (components labelled once per class)
  sameWater(a, b, cls = "boat") {
    if (!a || !b) return false;
    this._comp = this._comp || {};
    let lab = this._comp[cls];
    if (!lab) {
      const N = this.cols * this.rows, cols = this.cols;
      lab = this._comp[cls] = new Int32Array(N);
      let next = 0;
      const q = new Int32Array(N);
      for (let i = 0; i < N; i++) {
        if (lab[i] || !this.navigable(i % cols, (i / cols) | 0, cls)) continue;
        next++; let h = 0, t = 0; q[t++] = i; lab[i] = next;
        while (h < t) {
          const j = q[h++], c = j % cols, r = (j / cols) | 0;
          for (const [dc, dr] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
            const a2 = c + dc, b2 = r + dr;
            if (a2 < 0 || b2 < 0 || a2 >= cols || b2 >= this.rows) continue;
            const k = b2 * cols + a2;
            if (!lab[k] && this.navigable(a2, b2, cls)) { lab[k] = next; q[t++] = k; }
          }
        }
      }
    }
    const la = lab[this.idx(a[0], a[1])], lb = lab[this.idx(b[0], b[1])];
    return la > 0 && la === lb;
  },
  waterPath(from, to, cls) { return this.withMiles(this.path(from, to, (c, r) => this.navigable(c, r, cls), { limit: 600000, greed: 1.2 })); },
  // a 4-connected path zigzags on diagonals; its true length is the chord length sampled along it
  withMiles(p) {
    if (!p || p.length < 2) return p;
    let L = 0;
    for (let i = 0; i < p.length - 1; i += 8) { const j = Math.min(p.length - 1, i + 8); L += Math.hypot(p[j][0] - p[i][0], p[j][1] - p[i][1]); }
    p.mps = Math.max(0.7, L / (p.length - 1)) * this.miles;
    return p;
  },
});

// The plan's courses, moved onto navigable tiles and run harbour to harbour
AZ.Journey.prototype.fixCourses = function () {
  const w = this.w;
  this.course = new Set();
  for (const seg of this.segs) {
    if (!seg.moving) continue;
    const cls = AZ.vesselClass(seg.transport);
    seg.cls = cls;
    const fromB = w.P.burgs[w.C.burg[seg.from]], toB = seg.place.at ? seg.place.burg : null;
    const fromH = fromB && fromB.port ? w.harbour(fromB, cls) : null, toH = toB && toB.port ? w.harbour(toB, cls) : null;
    seg.fromHarbour = fromH ? fromH.t : null; seg.toHarbour = toH ? toH.t : null;
    const raw = seg.chain;
    const anchors = raw.filter(([c, r]) => w.navigable(c, r, cls));
    if (fromH) anchors.unshift(fromH.t);
    if (toH) anchors.push(toH.t);
    const out = [];
    for (let k = 0; k < anchors.length; k++) {
      const t = anchors[k], last = out[out.length - 1];
      if (!last) { out.push(t); continue; }
      if (last[0] === t[0] && last[1] === t[1]) continue;
      if (Math.abs(last[0] - t[0]) + Math.abs(last[1] - t[1]) === 1) { out.push(t); continue; }
      const p = w.path(last, t, (c, r) => w.navigable(c, r, cls), { limit: 60000 });
      if (p) out.push(...p.slice(1));
    }
    // loop erasure: where the plan's track doubles back over its own water, cut the loop out
    const pos = new Map(), clean = [];
    for (const t of out) {
      const k = w.idx(t[0], t[1]);
      if (pos.has(k)) { for (const u of clean.splice(pos.get(k) + 1)) pos.delete(w.idx(u[0], u[1])); }
      else { pos.set(k, clean.length); clean.push(t); }
    }
    seg.chain = clean.length ? clean : raw;
    seg.chainPos = new Map(seg.chain.map(([c, r], i) => [w.idx(c, r), i]));
    seg.endTile = seg.toHarbour || seg.chain[seg.chain.length - 1];
    seg.chain.forEach(([c, r]) => this.course.add(w.idx(c, r)));
  }
  // checkpoints: the stops, in order, each with its par times and the stays that make it up
  this.cps = [];
  const at = (seg) => (seg.place.burg && seg.place.at ? `b${seg.place.burg.i}` : `t${seg.place.tile.join(",")}`);
  const first = { place: this.origin, key: `b${this.origin.burg?.i}`, stays: [], legIn: null };
  this.cps.push(first);
  for (const seg of this.segs) {
    let cp = this.cps[this.cps.length - 1];
    if (seg.moving) {
      cp.legOut = seg;
      const next = { place: seg.place, key: at(seg), stays: [], legIn: seg, parArrive: seg.planEnd };
      this.cps.push(next);
    } else cp.stays.push(seg);
  }
  this.cps.forEach((cp, i) => {
    cp.i = i;
    if (cp.parArrive == null) cp.parArrive = this.t0;
    cp.parLeave = cp.legOut ? cp.legOut.planStart : cp.stays.length ? cp.stays[cp.stays.length - 1].planEnd : cp.parArrive;
    cp.tile = cp.place.burg && cp.place.at ? cp.place.burg.t : cp.place.tile;
    cp.acts = cp.stays.flatMap(st => AZ.stayActs(st, cp));
  });
  // the plan's own nights at anchor on legs that sail less than a full day (par, mixed)
  for (const seg of this.segs) {
    if (!seg.moving || seg.hoursPerDay >= 24) { if (seg.moving) seg.nights = []; continue; }
    seg.nights = [];
    const lat = w.latlon(...seg.startTile)[0];
    let t = seg.planStart, sailed = 0;
    for (let guard = 0; guard < 400 && sailed < seg.travelHours - 1e-6; guard++) {
      const sun = AZ.Clock.sun(t, lat), dawn = sun.day * 24 + Math.max(0, sun.rise);
      if (t < dawn) t = dawn;
      const use = Math.min(dawn + seg.hoursPerDay - t, seg.travelHours - sailed);
      if (use <= 0) { t = (sun.day + 1) * 24 + Math.max(0, AZ.Clock.sun((sun.day + 1) * 24, lat).rise); continue; }
      t += use; sailed += use;
      if (sailed < seg.travelHours - 1e-6) {
        const k = Math.round((sailed / seg.travelHours) * (seg.chain.length - 1));
        seg.nights.push({ t, tile: seg.chain[k], frac: sailed / seg.travelHours });
      }
    }
  }
};

// activities that make up a stay; the plan's hours are par, the player does the work
AZ.stayActs = function (st, cp) {
  const n = st.name, acts = [];
  if (/book|passage|hire/i.test(n)) acts.push({ id: "book", label: "Book passage or hire a boat at the harbour", stay: st.k });
  if (/alms/i.test(n)) acts.push({ id: "alms", label: "Give alms at the temple", stay: st.k });
  if (/rest|shelter|inn|lodg/i.test(n)) acts.push({ id: "rest", label: `Rest a night${/ at (.+)$/i.test(n) ? " at " + n.match(/ at (.+)$/i)[1] : " ashore"}`, stay: st.k });
  if (/anchor|stopp|night/i.test(n)) acts.push({ id: "anchor", label: `Spend the night at anchor ${cp.place.name}`, stay: st.k });
  if (!acts.length) acts.push({ id: "wait", label: n, stay: st.k });
  return acts;
};

// ------------------------------------------------------------------ weather
AZ.Weather = {
  KINDS: { clear: { label: "clear", walk: 1, sail: 1 }, cloudy: { label: "overcast", walk: 1, sail: 1 }, rain: { label: "rain", walk: 1.15, sail: 1.05 },
           snow: { label: "snow", walk: 1.4, sail: 1.15 }, fog: { label: "fog", walk: 1.1, sail: 1.3 }, storm: { label: "storm", walk: 1.5, sail: 2.2 } },
  at(w, c, r, t) {
    const day = Math.floor(t / 24), half = Math.floor((t % 24) / 12);
    const rx = c >> 5, ry = r >> 5, seed = AZ.U.strSeed(String(w.P.world.seed));
    const roll = AZ.U.rnd2(rx * 7919 + day * 3, ry * 104729 + half, seed);
    const roll2 = AZ.U.rnd2(rx + day * 31, ry + half * 17, seed ^ 0x5bd1e995);
    const lat = w.latlon(c, r)[0], season = AZ.Clock.season(lat, t), sea = !w.isLand(c, r);
    const prec = w.precMM(c, r);
    let pRain = AZ.U.clamp(prec / 2600, 0.06, 0.8);
    if (season === "winter") pRain *= 1.25; else if (season === "summer") pRain *= 0.8;
    else if (season === "wet season") pRain *= 1.5; else if (season === "dry season") pRain *= 0.4;
    let pStorm = sea ? 0.02 + (Math.abs(lat) > 30 && season === "winter" ? 0.06 : 0) + (Math.abs(lat) > 45 ? 0.03 : 0) + (season === "wet season" ? 0.04 : 0) : pRain * 0.08;
    const today = AZ.Clock.today(w.tempC(c, r), lat, t, sea);
    let kind = "clear";
    if (roll < pStorm) kind = "storm";
    else if (roll < pStorm + pRain) kind = today < 0 ? "snow" : "rain";
    else if (roll2 < (sea && today < 8 ? 0.08 : 0.03)) kind = "fog";
    else if (roll2 < 0.4) kind = "cloudy";
    return { kind, ...this.KINDS[kind], key: `${day}:${half}:${rx}:${ry}` };
  },
};

// ------------------------------------------------------------------ prices (🟡, Azgaar's money)
AZ.Prices = {
  tax(w, b) { const s = b && w.P.states[b.state]; return s ? +s.salesTax || 0 : 0; },
  market(w, b) { return b ? w.P.markets.find(m => m.i === b.market) : null; },
  food(w, b) { // cheapest food good on the town's market, with the state's sales tax
    const mk = this.market(w, b);
    let best = 1;
    if (mk) {
      const prices = w.P.goods.filter(g => (g.tags || []).includes("food") && mk.goods[g.i]).map(g => mk.goods[g.i][1]).filter(p => p > 0);
      if (prices.length) best = Math.min(...prices);
    }
    return best * (1 + this.tax(w, b));
  },
  ration(w, b) { return AZ.U.rn(Math.max(0.05, this.food(w, b) * 0.1), 2); },        // one person, one day
  water(w, b) { return AZ.U.rn(0.02 * (1 + this.tax(w, b)), 2); },                    // one cask-day
  inn(w, b) { return AZ.U.rn(0.3 * (1 + this.tax(w, b)) + this.ration(w, b) * 2, 1); },
  alms(w, b) { return AZ.U.rn(0.5 + (b?.population || 1) * 0.01, 1); },
  fare(w, b, miles) { return AZ.U.rn(Math.max(1, miles * 0.004) * (1 + this.tax(w, b)), 1); },
  wage(w, b) { return AZ.U.rn(0.15 * (1 + this.tax(w, b)), 2); },                    // one crew member, one day
  hire(w, b) { return AZ.U.rn(0.1 * (1 + this.tax(w, b)), 2); },                     // the boat, one day
  heal(w, b) { return AZ.U.rn(1 + this.ration(w, b) * 5, 1); },
  repair(w, b) {
    const mk = this.market(w, b), s = w.P.goods.find(g => /sail/i.test(g.name)), rp = w.P.goods.find(g => /rope/i.test(g.name));
    const p = (s && mk?.goods[s.i]?.[1] || 6) * 0.3 + (rp && mk?.goods[rp.i]?.[1] || 3) * 0.3;
    return AZ.U.rn(p * (1 + this.tax(w, b)), 1);
  },
  goodPrice(w, b, gid) { const mk = this.market(w, b); return mk && mk.goods[gid] ? mk.goods[gid][1] * (1 + this.tax(w, b)) : null; },
};
