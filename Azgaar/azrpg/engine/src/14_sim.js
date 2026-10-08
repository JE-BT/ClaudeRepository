// ---------------------------------------------------------------------------------------------
// The moving world (alpha 2). One seeded simulation, advanced day by day with the game clock.
// The map is the starting point and the momentum: production and trade flows (deals) drive the
// markets; the flows and the sea lanes become shipping lines; roads between friendly towns become
// coach lines; disease zones spread along the lines and burn out; famine follows empty granaries;
// the wars already under way in the map move their regiments, fight and occupy. Everything that
// happens is news, and news travels: the player learns of it in towns, when it has had time to
// arrive (60 miles a day). Fully seeded from the world seed: the same choices give the same world.
// ---------------------------------------------------------------------------------------------
AZ.SIM = { newsMilesPerDay: 60, armyTilesPerDay: 2, lineHorizonDays: 12 };

AZ.Sim = class {
  constructor(w, jr) {
    this.w = w; this.jr = jr;
    this.seed = AZ.U.strSeed(String(w.P.world.seed));
    this.day = 0;
    const P = w.P, U = AZ.U;
    this.food = new Set(P.goods.filter(g => (g.tags || []).includes("food")).map(g => g.i));
    // ---- markets: supply from production (burgs) and rural output (cells), per day
    this.mk = new Map();
    for (const m of P.markets) this.mk.set(m.i, { i: m.i, centre: m.centerBurgId, supply: {}, demand: {}, stock: {}, base: {}, target: {}, members: [] });
    for (const b of P.burgs) if (b && this.mk.has(b.market)) { const M = this.mk.get(b.market); M.members.push(b.i); for (const [g, u] of Object.entries(b.production || {})) M.supply[g] = (M.supply[g] || 0) + u / 30; }
    for (const [c, prod] of Object.entries(w.C.prod)) { const M = this.mk.get(w.C.market[+c]); if (!M) continue; for (const [g, u] of Object.entries(prod)) M.supply[g] = (M.supply[g] || 0) + u / 30; }
    for (const [key, goods] of Object.entries(P.trade.flows)) {
      const [a, b] = key.split(">").map(Number), A = this.mk.get(a), B = this.mk.get(b);
      if (!A || !B) continue;
      for (const [g, [u]] of Object.entries(goods)) { A.demand[g] = (A.demand[g] || 0) + u / 30; B.supply[g] = (B.supply[g] || 0) + u / 30; }
    }
    for (const M of this.mk.values()) {
      const m = P.markets.find(x => x.i === M.i);
      for (const g of new Set([...Object.keys(M.supply), ...Object.keys(m.goods)])) {
        // local equilibrium: over a year the market neither fills nor empties; the seasons swing it
        const s0 = M.supply[g] || 0, d0 = Math.max(0.01, s0 * (this.food.has(+g) ? 0.99 : 1));
        M.demand[g] = d0;
        M.target[g] = d0 * 20;
        M.stock[g] = d0 * 20;
        M.base[g] = m.goods[g] ? m.goods[g][1] : P.goods.find(x => x.i === +g)?.value || 1;
      }
    }
    this.flows = Object.entries(P.trade.flows).map(([k, goods]) => { const [a, b] = k.split(">").map(Number); return { a, b, goods: Object.entries(goods).map(([g, [u, v]]) => ({ g: +g, u: u / 30, v })) }; });
    // ---- wars already under way in the map
    this.wars = [];
    for (const s of P.states) if (s && s.campaigns) for (const c of s.campaigns) if (c.end == null && c.attacker === s.i && !this.wars.some(x => x.name === c.name)) this.wars.push({ name: c.name, a: c.attacker, d: c.defender, start: c.start, over: false });
    const atWar = new Set(this.wars.flatMap(x => [x.a, x.d]));
    this.regs = P.military.filter(u => !u.naval && atWar.has(u.state)).map(u => ({ id: `${u.state}:${u.i}`, state: u.state, name: u.name, t: u.t.slice(), base: u.t.slice(), a: u.a, a0: u.a, u: { ...u.u }, status: "hold", target: null, path: null, pos: 0, wait: 0 }));
    this.occupied = {};   // burg id -> occupying state
    // ---- zones (copies, so they can change)
    this.zones = new Map(P.zones.map(z => [z.i, { i: z.i, name: z.name, type: z.type, color: z.color, cells: new Set(z.cells), orig: new Set(z.cells), dyn: false, over: false }]));
    this.rebuildCellZones();
    this.news = [];
    this.lines = this.buildLines();
  }
  // ---------------------------------------------------------------- helpers
  rnd(...k) { return AZ.U.rnd2(AZ.U.strSeed(k.join(":")) & 0xffffff, this.day, this.seed); }
  rebuildCellZones() { this.cellZones = new Map(); for (const z of this.zones.values()) if (!z.over) for (const c of z.cells) { const a = this.cellZones.get(c); if (a) a.push(z.i); else this.cellZones.set(c, [z.i]); } }
  zonesOfCell(cell) { return (this.cellZones.get(cell) || []).map(i => this.zones.get(i)).filter(z => z && !z.over); }
  cellsAround(t, rad) { const w = this.w, out = new Set(); for (let dr = -rad; dr <= rad; dr += 2) for (let dc = -rad; dc <= rad; dc += 2) { if (dc * dc + dr * dr > rad * rad) continue; const c = t[0] + dc, r = t[1] + dr; if (w.inb(c, r) && w.isLand(c, r)) out.add(w.cell(c, r)); } return out; }
  burgZones(b) { return this.zonesOfCell(b.cell); }
  stateOf(b) { return this.occupied[b.i] ?? b.state; }
  atWar(a, b) { return this.wars.some(x => !x.over && ((x.a === a && x.d === b) || (x.a === b && x.d === a))); }
  rel(a, b) { if (a === b) return "Self"; if (this.atWar(a, b)) return "Enemy"; return this.w.P.states[a]?.diplomacy?.[b] || "Unknown"; }
  report(t, tile, text, kind) { this.news.push({ id: this.news.length, t, tile, text, kind }); }
  season(b) { return AZ.Clock.season(this.w.latlon(...b.t)[0], this.day * 24); }
  // ---------------------------------------------------------------- lines (the passenger network)
  buildLines() {
    const w = this.w, P = w.P, U = AZ.U, out = [], have = new Set();
    const port = b => b && b.port && w.harbour(b, "ship");
    const add = (L) => { const k = `${L.mode}:${L.from}>${L.to}`; if (have.has(k)) return; have.add(k); L.id = out.length; L.key = k; out.push(L); };
    const mkName = (k, cul) => `the ${U.cap(w.names.get(P.cultures[cul]?.base ?? 0, U.rng(`line:${k}`), 4, 9))}`;
    const shipLine = (A, B, period, why, cargo, fixed) => {
      if (!port(A) || !port(B) || !w.sameWater(w.harbour(A, "ship").t, w.harbour(B, "ship").t, "ship")) return;
      const k = `${A.i}>${B.i}`, rnd = U.rng(`${this.seed}:line:${k}`);
      add({ mode: "sea", from: A.i, to: B.i, period, phase: fixed ?? Math.floor(rnd() * period * 24) + 6, hour: 0, why, cargo,
        ship: mkName(k, A.culture), captain: null, flag: A.state, transport: "Sailing Ship", speed: 10, hpd: 24, cul: A.culture });
    };
    // trade runs between market centres, from the deals
    for (const f of this.flows) {
      const A = P.burgs[this.mk.get(f.a)?.centre], B = P.burgs[this.mk.get(f.b)?.centre];
      const v = f.goods.reduce((s, g) => s + g.v, 0), top = f.goods.sort((x, y) => y.v - x.v)[0];
      const per = U.clamp(Math.round(30 / Math.sqrt(1 + v / 5)), 5, 21);
      shipLine(A, B, per, `the ${P.goods.find(g => g.i === top?.g)?.name.toLowerCase() || "goods"} trade between the ${A?.name} and ${B?.name} markets`, top?.g, null);
      shipLine(B, A, per, `the return run of the same trade`, null, null);
    }
    // the plan's own ships: a packet whose timetable has a sailing at the plan's time
    if (this.jr) for (const cp of this.jr.cps) {
      const seg = cp.legOut; if (!seg || AZ.vesselClass(seg.transport) !== "ship" || !seg.place.burg) continue;
      shipLine(cp.place.burg, seg.place.burg, 7, `the packet between ${cp.place.burg.name} and ${seg.place.burg.name}, which pilgrims use`, null, Math.round(cp.parLeave));
    }
    // coastal packets: every port to its two nearest ports on the same water
    const ports = P.burgs.filter(port);
    for (const A of ports) {
      const near = ports.filter(B => B !== A && w.sameWater(w.harbour(A, "ship").t, w.harbour(B, "ship").t, "ship")).map(B => ({ B, d: Math.hypot(B.t[0] - A.t[0], B.t[1] - A.t[1]) })).filter(o => o.d < 140).sort((x, y) => x.d - y.d).slice(0, 2);
      for (const { B } of near) shipLine(A, B, 6 + Math.floor(U.rnd2(A.i, B.i, 5) * 6), `the coastal packet`, null, null);
    }
    // coaches and carriers between towns joined by road, where the states are on good terms
    const towns = P.burgs.filter(b => b && (b.population >= 3 || b.capital));
    for (const A of towns) {
      const near = towns.filter(B => B !== A && w.C.feature[B.cell] === w.C.feature[A.cell]).map(B => ({ B, d: Math.hypot(B.t[0] - A.t[0], B.t[1] - A.t[1]) })).filter(o => o.d < 55).sort((x, y) => x.d - y.d).slice(0, 3);
      for (const { B, d } of near) {
        const big = A.population >= 10 && B.population >= 10;
        const k = `${A.i}>${B.i}`, rnd = U.rng(`${this.seed}:coach:${k}`);
        add({ mode: "land", from: A.i, to: B.i, period: big ? 3 : 5 + Math.floor(rnd() * 3), phase: Math.floor(rnd() * 72) + 7, why: big ? "a stagecoach run between two cities" : "a carrier's wagon that takes passengers",
          ship: big ? `the ${A.name}–${B.name} stage` : `${w.names.get(P.cultures[A.culture]?.base ?? 0, rnd, 4, 8)}'s wagon`, flag: A.state, transport: big ? "Stagecoach" : "Carriage",
          speed: big ? 10 : 6, hpd: big ? 12 : 10, cul: A.culture, miles: Math.round(d * w.miles * 1.25) });
      }
    }
    return out;
  }
  lineStatus(L) {
    const P = this.w.P, A = P.burgs[L.from], B = P.burgs[L.to];
    const sa = this.stateOf(A), sb = this.stateOf(B);
    if (L.mode === "land") { const r = this.rel(sa, sb); if (!/Self|Ally|Friendly|Neutral|Unknown|Vassal|Suzerain/.test(r)) return { ok: false, why: `${P.states[sa]?.name} and ${P.states[sb]?.name} are on bad terms (${r})` }; }
    else if (this.atWar(sa, sb)) return { ok: false, why: `war between ${P.states[sa]?.name} and ${P.states[sb]?.name}` };
    for (const X of [A, B]) {
      if (this.occupied[X.i] != null && this.occupied[X.i] !== X.state) return { ok: false, why: `${X.name} is occupied by ${P.states[this.occupied[X.i]]?.name}` };
      const z = this.burgZones(X).find(z0 => /Disease|Tsunami|Flood|Eruption/.test(z0.type));
      if (z) return { ok: false, why: z.type === "Disease" ? `${X.name} is under quarantine (${z.name})` : `${X.name} is struck by the ${z.name}` };
    }
    return { ok: true };
  }
  departures(b, from, days = AZ.SIM.lineHorizonDays) {
    const out = [];
    for (const L of this.lines) {
      if (L.from !== b.i) continue;
      const per = L.period * 24;
      let k = Math.ceil((from - L.phase) / per);
      for (let t = L.phase + k * per; t < from + days * 24; t += per) {
        const st = this.lineStatusAt(L, t);
        out.push({ L, t, ok: st.ok, why: st.why });
      }
    }
    return out.sort((x, y) => x.t - y.t);
  }
  lineStatusAt(L, t) { return t <= (this.day + 1) * 24 ? this.lineStatus(L) : { ...this.lineStatus(L), forecast: true }; }
  // ---------------------------------------------------------------- the daily step
  advanceTo(clock) {
    const target = Math.floor(clock / 24);
    let n = 0;
    while (this.day < target && n++ < 400) { this.day++; this.step(); }
  }
  step() {
    this.economy();
    if (this.day % 7 === 0) this.hazards();
    this.war();
  }
  economy() {
    const P = this.w.P;
    for (const M of this.mk.values()) {
      const centre = P.burgs[M.centre]; if (!centre) continue;
      const se = this.season(centre);
      const sf = { winter: 0.6, spring: 0.85, summer: 1.15, autumn: 1.35, "wet season": 1.1, "dry season": 0.88 }[se] ?? 1;
      const zs = this.burgZones(centre);
      const dearth = zs.some(z => z.type === "Disaster"), sick = zs.some(z => z.type === "Disease"), occ = this.occupied[centre.i] != null && this.occupied[centre.i] !== centre.state;
      for (const g of Object.keys(M.demand)) {
        let sup = M.supply[g] || 0;
        if (this.food.has(+g)) sup *= sf * (dearth ? 0.5 : 1);
        if (sick) sup *= 0.8;
        if (occ) sup *= 0.6;
        M.stock[g] = Math.max(0, Math.min(M.target[g] * 3, (M.stock[g] || 0) + sup - M.demand[g] * (sick ? 0.85 : 1)));
      }
    }
    // the flows run only while a line between the two markets is open
    for (const f of this.flows) {
      const A = this.mk.get(f.a), B = this.mk.get(f.b);
      const L = this.lines.find(x => x.from === A?.centre && x.to === B?.centre);
      const open = L ? this.lineStatus(L).ok : true;
      if (open) continue;
      for (const g of f.goods) { A.stock[g.g] = (A.stock[g.g] || 0) + g.u; B.stock[g.g] = Math.max(0, (B.stock[g.g] || 0) - g.u); }
    }
  }
  price(M, g) { const s = M.stock[g] ?? 0, T = M.target[g] || 1; return (M.base[g] || 1) * AZ.U.clamp(Math.sqrt(T / Math.max(s, T * 0.05)), 0.5, 3); }
  foodFor(b) { // rations for sale in a town this week: the market's food stock, a share for strangers
    const M = this.mk.get(b.market); if (!M) return { rations: 0, price: 1 };
    let units = 0, cheap = null;
    for (const g of this.food) { if (M.base[g] == null) continue; units += M.stock[g] || 0; const p = this.price(M, g); if (!cheap || p < cheap.p) cheap = { g, p }; }
    const share = Math.min(1, 0.04 + (b.population || 1) * 0.01);
    return { rations: Math.floor(units * 10 * 0.15 * share), price: cheap ? cheap.p : 1, good: cheap?.g, season: this.season(P_burg(this.w, M.centre)) };
  }
  takeFood(b, rations) { const M = this.mk.get(b.market); if (!M) return; let need = rations / 10; for (const g of [...this.food].sort((x, y) => this.price(M, x) - this.price(M, y))) { const take = Math.min(need, M.stock[g] || 0); M.stock[g] -= take; need -= take; if (need <= 0) break; } }
  // ---------------------------------------------------------------- hazards (weekly)
  hazards() {
    const w = this.w, P = w.P;
    for (const z of this.zones.values()) {
      if (z.over) continue;
      if (z.type === "Disease") {
        const sick = P.burgs.filter(b => b && z.cells.has(b.cell));
        for (const b of sick) for (const L of this.lines) {
          if (L.from !== b.i && L.to !== b.i) continue;
          const other = P.burgs[L.from === b.i ? L.to : L.from];
          if (z.cells.has(other.cell) || this.rnd("spread", z.i, other.i) > 0.05) continue;
          for (const c of this.cellsAround(other.t, 5)) z.cells.add(c);
          this.report(this.day * 24, other.t, `The ${z.name} has reached ${other.name}, carried by ${L.mode === "sea" ? "ship" : "road"} from ${b.name}.`, "hazard");
        }
        if (this.rnd("burnout", z.i) < 0.04 + (z.cells.size > z.orig.size * 2 ? 0.12 : 0)) { z.over = true; this.report(this.day * 24, w.tileAt(w.C.cx[[...z.cells][0]], w.C.cy[[...z.cells][0]]), `The ${z.name} is over.`, "hazard"); }
      } else if (/Eruption|Avalanche|Fault|Flood|Tsunami/.test(z.type)) {
        if (this.rnd("end", z.i) < 0.08) { z.over = true; const c0 = [...z.cells][0]; this.report(this.day * 24, w.tileAt(w.C.cx[c0], w.C.cy[c0]), `The ${z.name} is over; the ${z.type === "Tsunami" ? "coast is" : "roads are"} open again.`, "hazard"); }
      }
    }
    // famine follows empty granaries
    for (const M of this.mk.values()) {
      const centre = P.burgs[M.centre]; if (!centre) continue;
      let s = 0, T = 0; for (const g of this.food) { s += M.stock[g] || 0; T += M.target[g] || 0; }
      const ratio = T ? s / T : 1, key = `dearth:${M.i}`;
      const z = [...this.zones.values()].find(x => x.key === key && !x.over);
      if (!z && ratio < 0.15) {
        const id = 1000 + this.zones.size;
        this.zones.set(id, { i: id, key, name: `${centre.name} Dearth`, type: "Disaster", color: "#b08040", cells: this.cellsAround(centre.t, 6), orig: new Set(), dyn: true, over: false });
        this.report(this.day * 24, centre.t, `Dearth around ${centre.name}: the granaries are empty and bread is dear.`, "hazard");
      } else if (z && ratio > 0.5) { z.over = true; this.report(this.day * 24, centre.t, `The dearth around ${centre.name} has eased.`, "hazard"); }
    }
    this.rebuildCellZones();
    this.changed = true;
  }
  // ---------------------------------------------------------------- war (daily)
  war() {
    const w = this.w, P = w.P, U = AZ.U;
    for (const war of this.wars) {
      if (war.over) continue;
      const att = this.regs.filter(r => r.state === war.a && r.a > 200), def = this.regs.filter(r => r.state === war.d && r.a > 200);
      const a0 = this.regs.filter(r => r.state === war.a).reduce((s, r) => s + r.a0, 0) || 1, a1 = att.reduce((s, r) => s + r.a, 0);
      war.days = (war.days || 0) + 1;
      const held = Object.values(this.occupied).filter(x => x === war.a).length;
      if (a1 < a0 * 0.4 || war.days > 300 || (this.day % 7 === 0 && this.rnd("peace", war.name) < 0.01 + 0.02 * held)) {
        war.over = true;
        for (const [b, st] of Object.entries(this.occupied)) if (st === war.a && P.burgs[b].state === war.d) delete this.occupied[b];
        const cap = P.burgs[P.states[war.d]?.capital];
        this.report(this.day * 24, cap ? cap.t : [0, 0], `Peace: the ${war.name} is over. ${P.states[war.a].name} withdraws.`, "war");
        this.changed = true;
        continue;
      }
      // the attacker marches on the defender's nearest town on the same land; the defender guards what is threatened
      let budget = 1;
      for (const r of att) {
        if (r.status === "retreat") { this.moveAlong(r, r.base); if (r.t[0] === r.base[0] && r.t[1] === r.base[1]) { r.status = "hold"; r.a = Math.min(r.a0, r.a * 1.1); } continue; }
        if (r.garrison > 0) { r.garrison--; continue; }
        if (!r.target || this.occupied[r.target] === war.a) {
          const targets = P.burgs.filter(b => b && b.state === war.d && this.occupied[b.i] !== war.a && w.C.feature[b.cell] === w.C.feature[r.cellLand ?? w.cell(...r.t)]);
          const tb = targets.sort((x, y) => Math.hypot(x.t[0] - r.t[0], x.t[1] - r.t[1]) - Math.hypot(y.t[0] - r.t[0], y.t[1] - r.t[1]))[0];
          r.target = tb ? tb.i : null; r.path = null;
          if (!tb) { r.status = "hold"; continue; }
        }
        const tb = P.burgs[r.target];
        if (!r.path && budget-- > 0) { r.path = w.path(r.t, tb.t, (c, rr) => w.isLand(c, rr), { limit: 80000, greed: 1.5 }) || []; r.pos = 0; r.status = r.path.length ? "march" : "hold"; }
        if (r.status === "march") this.stepPath(r);
        if (r.t[0] === tb.t[0] && r.t[1] === tb.t[1]) {
          const guard = def.find(d => Math.hypot(d.t[0] - tb.t[0], d.t[1] - tb.t[1]) <= 3);
          // a siege: a week for an open town, three for walls, a month for a capital with a citadel
          const need = tb.capital && tb.citadel ? 30 : tb.walls ? 21 : 7;
          if (r.garrison > 0) { r.garrison--; continue; }
          if (!guard && ++r.wait >= need) {
            this.occupied[tb.i] = war.a; r.wait = 0; r.target = null; r.garrison = 14;
            const zid = `inv:${war.a}`;
            let z = [...this.zones.values()].find(x => x.key === zid && !x.over);
            if (!z) { const id = 2000 + this.zones.size; z = { i: id, key: zid, name: `${P.states[war.a].name} Invasion`, type: "Invasion", color: P.states[war.a].color, cells: new Set(), orig: new Set(), dyn: true, over: false }; this.zones.set(id, z); }
            for (const c of this.cellsAround(tb.t, 4)) z.cells.add(c);
            this.rebuildCellZones(); this.changed = true;
            this.report(this.day * 24, tb.t, `${tb.name} has fallen to the ${r.name} of ${P.states[war.a].name}.`, "war");
          }
        }
      }
      for (const d of def) {
        const threat = att.find(a => a.target != null && Math.hypot(a.t[0] - P.burgs[a.target].t[0], a.t[1] - P.burgs[a.target].t[1]) < 45);
        if (threat && d.status !== "retreat") { const tb = P.burgs[threat.target]; if (!d.goal || d.goal[0] !== tb.t[0] || d.goal[1] !== tb.t[1]) { d.goal = tb.t.slice(); d.path = null; } this.moveAlong(d, d.goal); }
        // battle when within a tile
        for (const a of att) {
          if (a.a <= 200 || d.a <= 200 || Math.abs(a.t[0] - d.t[0]) > 1 || Math.abs(a.t[1] - d.t[1]) > 1) continue;
          const odds = a.a / (a.a + d.a), roll = this.rnd("battle", a.id, d.id);
          const [win, lose] = roll < odds ? [a, d] : [d, a];
          lose.a = Math.round(lose.a * (0.5 + this.rnd("l", lose.id) * 0.2)); win.a = Math.round(win.a * (0.82 + this.rnd("w", win.id) * 0.1));
          lose.status = "retreat"; lose.path = null;
          const near = w.near(win.t[0], win.t[1], 20).find(n => n.kind === "burg");
          this.report(this.day * 24, win.t.slice(), `Battle${near ? ` near ${near.o.name}` : ""}: the ${win.name} of ${P.states[win.state].name} beat the ${lose.name} of ${P.states[lose.state].name}, who fall back.`, "war");
          this.changed = true;
        }
      }
    }
    void U;
  }
  moveAlong(r, goal) {
    const w = this.w;
    if (r.t[0] === goal[0] && r.t[1] === goal[1]) return;
    if (!r.path || !r.path.length || r.pathGoal !== goal.join(",")) { r.path = w.path(r.t, goal, (c, rr) => w.isLand(c, rr), { limit: 60000, greed: 1.5 }) || []; r.pos = 0; r.pathGoal = goal.join(","); }
    this.stepPath(r);
  }
  stepPath(r) { if (!r.path || !r.path.length) return; r.pos = Math.min(r.path.length - 1, r.pos + AZ.SIM.armyTilesPerDay); r.t = r.path[r.pos].slice(); }
  regAt(c, r0, rad) { return this.regs.filter(r => Math.hypot(r.t[0] - c, r.t[1] - r0) <= rad); }
  // ---------------------------------------------------------------- save
  save() {
    const mk = {}; for (const [i, M] of this.mk) mk[i] = M.stock;
    return { day: this.day, mk, regs: this.regs.map(r => ({ id: r.id, t: r.t, a: r.a, status: r.status, target: r.target })), occupied: this.occupied, wars: this.wars.map(x => ({ over: x.over, days: x.days })),
      zones: [...this.zones.values()].map(z => ({ i: z.i, key: z.key, name: z.name, type: z.type, color: z.color, cells: [...z.cells], dyn: z.dyn, over: z.over })), news: this.news };
  }
  load(d) {
    if (!d) return;
    this.day = d.day;
    for (const [i, st] of Object.entries(d.mk || {})) if (this.mk.has(+i)) this.mk.get(+i).stock = st;
    for (const r of d.regs || []) { const x = this.regs.find(y => y.id === r.id); if (x) Object.assign(x, r, { path: null }); }
    this.occupied = d.occupied || {};
    (d.wars || []).forEach((x, k) => this.wars[k] && Object.assign(this.wars[k], x));
    for (const z of d.zones || []) this.zones.set(z.i, { ...z, cells: new Set(z.cells), orig: this.zones.get(z.i)?.orig || new Set() });
    this.news = d.news || [];
    this.rebuildCellZones();
  }
};
function P_burg(w, i) { return w.P.burgs[i] || w.P.burgs.find(Boolean); }
