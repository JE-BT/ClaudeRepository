// ---------------------------------------------------------------------------------------------
// The game. The map's journey is the plan: a line of checkpoints with par times and the things
// the plan expects done at each (book passage, give alms, rest, anchor). It does not drive play.
// The traveller decides how to get from one checkpoint to the next: on foot, in a boat they hire
// or own (they steer; the crew calls for stops), or as a passenger on a ship they book (the
// captain steers, keeps his own itinerary and does not wait).
// ---------------------------------------------------------------------------------------------
AZ.DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

AZ.Game = class {
  constructor(w, ren, ui, jr, store) {
    this.w = w; this.ren = ren; this.ui = ui; this.jr = jr; this.store = store;
    this.key = `azrpg3:${w.P.world.seed}:${jr ? jr.J.name : "free"}`;
    this.held = []; this.anim = null; this.s = null; this.lensIdx = 0; this.inspectOn = false;
    this.walkSpeed = (w.W.transports.find(t => t.name === "On foot (light)") || { speed: 5 }).speed;
    this.harbourAt = new Map();
    for (const b of w.P.burgs) if (b && b.port) for (const cls of ["boat", "ship"]) { const h = w.harbour(b, cls); if (h) this.harbourAt.set(w.idx(h.t[0], h.t[1]), b); }
    ren.piers = new Set([...this.harbourAt.keys()]);
    ren.cache.clear();
  }
  // ------------------------------------------------------------------ state
  fresh(seed, kindId, doy0 = 80) {
    const w = this.w, jr = this.jr;
    AZ.Clock.doy0 = doy0;
    if (jr) { jr.replan(); jr.fixCourses(); }
    const t0 = jr ? jr.t0 : 6;
    const start = jr ? jr.origin.tile : (w.P.burgs.find(b => b && b.capital) || {}).t || [0, 0];
    this.tv = AZ.makeTraveller(w, jr, seed, kindId);
    this.know = new AZ.Know(w, jr, this.tv);
    this.events = new AZ.Events(this);
    this.s = { seed, kind: this.tv.kind, doy0, c: start[0], r: start[1], dir: "down", aboard: false, vessel: null, voyage: null,
               clock: t0, lastDay: Math.floor(t0 / 24), cp: 1, cpRec: [{ arrive: t0, acts: {} }], log: [],
               seen: { m: [], u: [], b: [], z: [], st: [], cu: [], re: [], bi: [] }, waypoint: null, auto: false, autoPath: null, region: "", done: false };
    this.backfill();
    this.s.purse = this.tv.purse;
    this.s.sup = { food: this.tv.food ?? 3 };
    this.s.goods = {}; this.s.basis = {};
    if (this.tv.cargo != null) { this.s.flags.cargo = true; this.s.goods[this.tv.cargo] = 4; this.s.basis[this.tv.cargo] = AZ.Prices.goodPrice(w, jr.origin.burg, this.tv.cargo) || 1; }
    if (this.tv.boat && jr) {
      const b = jr.origin.burg, h = w.harbour(b, "boat");
      if (h) this.s.vessel = { mode: "owned", kind: "Sailing boat", cls: "boat", speed: 6, hpd: 12, crew: 3, morale: 80, c: h.t[0], r: h.t[1], wage: AZ.Prices.wage(w, b), hire: 0, home: b.i };
    }
    this.explored = new Uint8Array(Math.ceil((w.cols * w.rows) / 8));
    this.reveal();
    if (this.tv.thread) this.startThread(this.tv.thread, true);
  }
  backfill() {
    const s = this.s;
    const def = { purse: 10, stand: { f: {}, s: {} }, cond: {}, flags: {}, threads: [], leads: [], done_m: [], done_z: [], doy0: 80, sup: { food: 3 }, hunger: 0, taken: [], goods: {}, basis: {}, awake: 0 };
    for (const [k, v] of Object.entries(def)) if (s[k] === undefined) s[k] = JSON.parse(JSON.stringify(v));
    s.tvFaith = this.tv.faith;
  }
  saveGame() {
    if (!this.s) return false;
    const runs = [];
    for (let i = 0; i < this.explored.length;) { let j = i; while (j < this.explored.length && this.explored[j] === this.explored[i] && j - i < 65535) j++; runs.push(this.explored[i], j - i); i = j; }
    try { this.store.setItem(this.key, JSON.stringify({ v: 3, s: this.s, ex: runs, lens: this.lensIdx })); return true; } catch (e) { return false; }
  }
  loadGame() {
    let data = null;
    try { data = JSON.parse(this.store.getItem(this.key) || "null"); } catch (e) { data = null; }
    if (!data || !data.s) return false;
    this.s = data.s;
    AZ.Clock.doy0 = this.s.doy0 ?? 80;
    if (this.jr) { this.jr.replan(); this.jr.fixCourses(); }
    this.tv = AZ.makeTraveller(this.w, this.jr, this.s.seed, this.s.kind);
    this.know = new AZ.Know(this.w, this.jr, this.tv);
    this.events = new AZ.Events(this);
    this.backfill();
    this.explored = new Uint8Array(Math.ceil((this.w.cols * this.w.rows) / 8));
    let o = 0;
    for (let k = 0; k < data.ex.length; k += 2) { this.explored.fill(data.ex[k], o, o + data.ex[k + 1]); o += data.ex[k + 1]; }
    this.lensIdx = data.lens || 0;
    return true;
  }
  hasSave() { try { return !!this.store.getItem(this.key); } catch (e) { return false; } }
  log(html, cls = "") { this.s.log.push({ t: this.s.clock, html, cls }); if (this.s.log.length > 500) this.s.log.shift(); }
  lat() { return this.w.latlon(this.s.c, this.s.r)[0]; }
  burgHere() { const id = this.w.idx(this.s.c, this.s.r); return this.w.burgAt.get(id) || (this.s.aboard ? this.harbourAt.get(id) : null) || null; }
  weather() { return AZ.Weather.at(this.w, this.s.c, this.s.r, this.s.clock); }
  // ------------------------------------------------------------------ checkpoints (par)
  cpNext() { return this.jr && !this.s.done ? this.jr.cps[this.s.cp] || null : null; }
  cpHere() {
    if (!this.jr) return null;
    for (let k = this.s.cp - 1; k >= 0; k--) if (this.atCp(this.jr.cps[k], 2)) return this.jr.cps[k];
    return null;
  }
  atCp(cp, rad = 1) {
    const s = this.s, w = this.w;
    if (cp.place.burg && cp.place.at) return this.burgHere() === cp.place.burg;
    return Math.abs(s.c - cp.tile[0]) <= rad && Math.abs(s.r - cp.tile[1]) <= rad && w.isLand(s.c, s.r) === w.isLand(...cp.tile);
  }
  par() { const cp = this.cpNext(); return cp ? cp.parArrive : this.jr ? this.jr.planEnd : this.s.clock; }
  deltaTextAt(d) { return Math.abs(d) < 1 ? "on par" : `${AZ.Clock.span(Math.abs(d))} ${d > 0 ? "over" : "under"} par`; }
  checkCheckpoints() {
    const s = this.s, jr = this.jr, U = AZ.U, w = this.w;
    if (!jr || s.done) return;
    for (let k = s.cp; k < jr.cps.length; k++) {
      const cp = jr.cps[k];
      // the next checkpoint counts when you reach it; a later one only if you go into its town
      // (passing a later anchorage or harbour on the way does not skip the ones between)
      if (k > s.cp && !(cp.place.burg && cp.place.at && (this.inTownOf === cp.place.burg || w.burgAt.get(w.idx(s.c, s.r)) === cp.place.burg))) continue;
      if (!this.atCp(cp, 1)) continue;
      for (let j = s.cp; j < k; j++) { s.cpRec[j] = { skipped: true, acts: {} }; this.log(`Checkpoint skipped: ${U.esc(jr.cps[j].place.name)}.`, "hook"); }
      s.cpRec[k] = { arrive: s.clock, acts: {} };
      s.cp = k + 1;
      s.auto = false; s.autoPath = null;
      const d = s.clock - cp.parArrive;
      this.log(`Checkpoint ${k}: ${U.esc(cp.place.name)}, ${AZ.Clock.fmt(s.clock)} (${this.deltaTextAt(d)}).`, "hook");
      const L = [`<b class="hook">Checkpoint: ${U.esc(cp.place.name)}</b> · ${AZ.Clock.fmt(s.clock)}. Par was ${AZ.Clock.fmt(cp.parArrive)}: ${this.deltaTextAt(d)} ${AZ.T("mixed")}.`];
      if (cp.acts.length) L.push(`The plan has you do here: ${cp.acts.map(a => `<span class="hook">${U.esc(a.label)}</span>`).join("; ")}. ${cp.place.at ? "Go into town with Space." : "Press R here."}`);
      if (k === jr.cps.length - 1) return this.finish(L);
      this.saveGame();
      this.ui.say(L);
      return;
    }
  }
  doAct(id, where) {
    const s = this.s, cp = this.cpHere();
    if (!cp) return null;
    const act = cp.acts.find(a => a.id === id);
    if (!act) return null;
    const rec = s.cpRec[cp.i] = s.cpRec[cp.i] || { acts: {} };
    rec.acts = rec.acts || {};
    if (rec.acts[id]) return null;
    rec.acts[id] = s.clock;
    this.log(`★ ${AZ.U.esc(act.label)} (${AZ.U.esc(cp.place.name)}).`, "hook");
    if (id === "alms" && where) {
      const rel = this.w.C.religion[where.cell], destRel = this.w.C.religion[this.jr.segs[this.jr.segs.length - 1].to];
      if (rel === destRel) this.events.fx({ stand: [["f", rel, 1]] }, "A rite of the pilgrimage.");
    }
    return act;
  }
  pendingActs(b) {
    const cp = this.cpHere();
    if (!cp || (b && cp.place.burg !== b)) return [];
    const rec = this.s.cpRec[cp.i] || { acts: {} };
    return cp.acts.filter(a => !(rec.acts || {})[a.id]);
  }
  async finish(msg) {
    const s = this.s, U = AZ.U, jr = this.jr;
    s.done = true; this.saveGame();
    const acts = jr.cps.reduce((a, cp) => a + cp.acts.length, 0), done = s.cpRec.reduce((a, r) => a + Object.keys(r?.acts || {}).length, 0);
    const skipped = s.cpRec.filter(r => r && r.skipped).length;
    await this.ui.say([...msg, `<b class="hook">The pilgrimage is complete.</b> ${U.esc(this.tv.name)} reaches ${U.esc(jr.dest.name)} on ${AZ.Clock.fmt(s.clock)}: ${this.deltaTextAt(s.clock - jr.planEnd)}.`,
      `Checkpoints skipped: ${skipped}. The plan's tasks done: ${done} of ${acts}. Purse: 🟡 ${U.rn(s.purse, 1)}. Side stories finished: ${s.threads.filter(t => t.outcome === "done").length}. The journal (J) has the full record; you can keep exploring.`]);
  }
  // ------------------------------------------------------------------ movement
  passable(c, r) {
    const w = this.w, s = this.s;
    if (!w.inb(c, r)) return { ok: false, why: "The edge of the known world." };
    if (s.voyage && s.aboard) return { ok: false, why: "You are aboard as a passenger: the captain has the helm. Space to talk; F to let the days pass faster." };
    if (s.aboard && s.vessel) {
      if (w.navigable(c, r, s.vessel.cls)) return { ok: true };
      return { ok: false, why: w.isLand(c, r) ? (w.bits(c, r).river ? `Too shallow for a ${s.vessel.kind.toLowerCase()}.` : "Land ahead. Space to go ashore; the boat waits.") : "Shoal water." };
    }
    const v = s.vessel;
    if (v && v.c === c && v.r === r) return { ok: true, board: true };
    if (!w.isLand(c, r)) return { ok: false, why: "Too deep to wade. You need a boat." };
    return { ok: true };
  }
  legFor(c, r) { // the plan's leg whose course this tile is on (steps along it cost the course's own miles)
    if (!this.jr) return null;
    const i = this.w.idx(c, r);
    return this.jr.segs.find(sg => sg.moving && sg.chainPos && sg.chainPos.has(i)) || null;
  }
  stepHours(c, r, dc, dr) {
    const w = this.w, U = AZ.U, s = this.s, lat = w.latlon(c, r)[0], wx = AZ.Weather.at(w, c, r, s.clock);
    if (s.aboard && (s.vessel || s.voyage)) {
      const v = s.voyage || s.vessel, wd = v.mode === "land" ? null : w.wind(lat);
      let f = 1;
      if (wd != null) { const hd = Math.atan2(dc, -dr), wr = (wd * Math.PI) / 180; f = 1 + 0.1 * Math.cos(hd - wr); }
      let miles = w.miles;
      const seg = this.legFor(c, r);
      if (seg) { const a = seg.chainPos.get(w.idx(s.c, s.r)), b = seg.chainPos.get(w.idx(c, r)); if (a !== undefined && b !== undefined && Math.abs(a - b) === 1) miles = seg.miles / Math.max(1, seg.chain.length - 1); }
      else if (s.auto && s.autoPath && s.autoPath.mps) miles = s.autoPath.mps;
      if (s.voyage) miles = s.voyage.milesPerStep || miles;
      return (miles / v.speed / f) * wx.sail * (s.cond.damaged && !s.voyage ? AZ.COND.damaged.slow : 1);
    }
    const cell = w.cell(c, r), b = w.P.biomes[w.C.biome[cell]], B = w.bits(c, r);
    let f = B.road ? 0.8 : B.trail ? 1 : U.clamp((b.cost || 50) / 50, 1, 4);
    const rel = w.reliefAt(c, r);
    if (rel && !B.road) f *= /mount/i.test(rel.icon) ? 1.6 : 1.2;
    let h = ((s.auto && s.autoPath && s.autoPath.mps ? s.autoPath.mps : w.miles) / this.walkSpeed) * f * wx.walk;
    if (B.river && !B.road && !B.trail) h += 0.5;
    if (AZ.Clock.light(s.clock, lat).phase === "night") h *= 1.5;
    for (const k of Object.keys(s.cond)) if (AZ.COND[k]?.slow && k !== "damaged") h *= AZ.COND[k].slow;
    return h;
  }
  tryMove(dir, forced) {
    if (this.anim || this.ui.busy() || !this.s) return false;
    const [dc, dr] = AZ.DIRS[dir], s = this.s;
    s.dir = dir;
    const c = s.c + dc, r = s.r + dr, p = forced ? { ok: true } : this.passable(c, r);
    if (!p.ok) {
      if (this._lastWhy !== p.why || performance.now() - (this._whyT || 0) > 2500) { this.ui.toast(p.why); this._lastWhy = p.why; this._whyT = performance.now(); }
      if (s.auto) this.setAuto(false);
      return false;
    }
    const hours = this.stepHours(c, r, dc, dr);
    this.anim = { from: [s.c, s.r], to: [c, r], t0: performance.now(), dur: s.auto || forced ? (this.fast ? 24 : 70) : s.aboard ? 110 : 140 };
    s.c = c; s.r = r; s.clock += hours;
    this.awakeTick(hours);
    if (s.aboard && s.vessel && !s.voyage) { s.vessel.c = c; s.vessel.r = r; s.vessel.anchored = false; }
    if (p.board) { s.aboard = true; this.ui.toast(`Aboard the ${s.vessel.kind.toLowerCase()}.`); }
    this.afterStep();
    return true;
  }
  afterStep() {
    const s = this.s, w = this.w, U = AZ.U, T = AZ.T;
    this.reveal();
    const cell = w.cell(s.c, s.r), id = w.idx(s.c, s.r);
    const b = w.burgAt.get(id), hb = s.aboard ? this.harbourAt.get(id) : null;
    let key, title, sub;
    if (b || hb) { const x = b || hb; key = "b" + x.i; title = hb && !b ? `${x.name} harbour` : x.name; sub = `${U.cap(x.group.replace("_", " "))} · ${w.P.states[x.state]?.fullName || "unclaimed"}`; }
    else if (w.isLand(s.c, s.r)) {
      const st = w.C.state[cell], pv = w.C.province[cell];
      key = `l${st}:${pv}`; title = pv ? w.P.provinces[pv].fullName : st ? w.P.states[st].fullName : "Neutral lands";
      sub = `${st ? w.P.states[st].fullName + " · " : ""}${w.P.cultures[w.C.culture[cell]].name} · ${w.P.religions[w.C.religion[cell]].name}`;
    } else { key = "f" + w.C.feature[cell]; title = w.waterName(s.c, s.r); sub = s.voyage && s.aboard ? `aboard the ${s.voyage.ship}` : s.aboard && s.vessel ? s.vessel.kind : ""; }
    if (key !== s.region) { s.region = key; this.ui.banner(U.esc(title), U.esc(sub)); }
    const addSeen = (k, v) => { if (v != null && !s.seen[k].includes(v)) { s.seen[k].push(v); return true; } return false; };
    if (w.isLand(s.c, s.r)) { addSeen("st", w.C.state[cell]); addSeen("cu", w.C.culture[cell]); addSeen("re", w.C.religion[cell]); addSeen("bi", w.C.biome[cell]); }
    if ((b || hb) && addSeen("b", (b || hb).i)) this.log(`Reached ${U.esc((b || hb).name)} (${(b || hb).group}).`);
    let pause = false;
    const sight = this.know.sightTiles(s.c, s.r, s.aboard);
    for (const n of w.near(s.c, s.r, sight)) {
      if (n.kind === "marker" && addSeen("m", n.o.i)) {
        this.addLead({ key: "m" + n.o.i, name: n.o.name, type: n.o.type, t: n.o.t, from: "sighted" });
        const dd = this.know.dirDist(s.c, s.r, n.o.t);
        this.ui.toast(`Sighted <b class="side">${U.esc(n.o.name)}</b>, ${dd.txt} ${T("data")}`, "teal");
        this.log(`Sighted ${U.esc(n.o.name)} (${n.o.type}), ${dd.txt}.`, "side"); pause = pause || n.d <= 3;
      } else if (n.kind === "unit" && addSeen("u", `${n.o.state}:${n.o.i}`)) {
        const dd = this.know.dirDist(s.c, s.r, n.o.t);
        this.ui.toast(`${n.o.naval ? "Sails" : "Tents"}: the ${U.esc(n.o.name)} of ${U.esc(w.P.states[n.o.state].name)}, ${dd.txt} ${T("data")}`, "teal");
        this.log(`Sighted the ${U.esc(n.o.name)} of ${U.esc(w.P.states[n.o.state].name)}.`, "side"); pause = pause || n.d <= 2;
      }
    }
    if (pause && s.auto) { this.setAuto(false); this.ui.toast("Autopilot paused. F to carry on."); }
    if (hb && !b && s.vessel && s.aboard && !s.voyage) this.ui.toast(`In ${U.esc(hb.name)} harbour. Space to go into town.`);
    if (s.waypoint && Math.abs(s.waypoint[0] - s.c) <= 1 && Math.abs(s.waypoint[1] - s.r) <= 1) { s.waypoint = null; this.ui.toast("Waypoint reached."); }
    this.checkCheckpoints();
    this.refill();
    if (this.events) this.events.onStep();
    this.dirty = true;
    this._steps = (this._steps || 0) + 1;
    if (this._steps % 25 === 0) this.saveGame();
  }
  reveal() {
    const s = this.s, w = this.w, R = this.know ? this.know.sightTiles(s.c, s.r, s.aboard) : 4;
    for (let dr = -R; dr <= R; dr++) for (let dc = -R; dc <= R; dc++) {
      if (dc * dc + dr * dr > R * R) continue;
      const c = s.c + dc, r = s.r + dr;
      if (!w.inb(c, r)) continue;
      const i = w.idx(c, r);
      this.explored[i >> 3] |= 1 << (i & 7);
    }
  }
  isExplored(i) { return (this.explored[i >> 3] >> (i & 7)) & 1; }
  // ------------------------------------------------------------------ autopilot (F): follow a path
  setAuto(on) {
    const s = this.s;
    if (on && s.voyage && s.aboard) { this.fast = !this.fast; this.ui.toast(this.fast ? "Days pass quickly." : "Days pass at the usual pace."); return; }
    if (on) {
      const path = this.planAuto();
      if (!path || path.length < 2) { this.ui.toast(s.aboard ? "No course from here. Set a waypoint on the map (M)." : "Set a waypoint on the world map (M) to walk there."); return; }
      s.autoPath = path; this._autoK = 0;
    }
    s.auto = on;
    this.dirty = true;
  }
  planAuto() {
    const s = this.s, w = this.w, here = [s.c, s.r];
    if (s.aboard && s.vessel) {
      const cls = s.vessel.cls;
      if (!s.waypoint) {
        const cp = this.cpNext();
        const seg = this.legFor(s.c, s.r);
        if (seg && cp && seg === cp.legIn) return seg.chain.slice(seg.chainPos.get(w.idx(s.c, s.r)));
        if (!cp) return null;
        const goal = cp.place.burg && cp.place.at ? w.harbour(cp.place.burg, cls)?.t : cp.tile;
        return goal ? w.waterPath(here, goal, cls) : null;
      }
      let goal = s.waypoint;
      if (!w.navigable(...goal, cls)) { const b = w.near(goal[0], goal[1], 8).find(n => n.kind === "burg" && n.o.port); const h = b && w.harbour(b.o, cls); goal = h ? h.t : null; }
      return goal ? w.waterPath(here, goal, cls) : null;
    }
    if (!s.aboard && s.waypoint) {
      const goal = s.waypoint;
      if (!w.isLand(...goal)) return null;
      return w.withMiles(w.path(here, goal, (c, r) => w.isLand(c, r), { limit: 300000, cost: (c, r) => { const B = w.bits(c, r); return B.road ? 0.6 : B.trail ? 0.8 : AZ.U.clamp((w.P.biomes[w.C.biome[w.cell(c, r)]].cost || 50) / 50, 1, 4); } }));
    }
    return null;
  }
  autoDir() {
    const s = this.s, p = s.autoPath;
    if (!p || !p.length) return null;
    let k = -1;
    for (let i = Math.max(0, (this._autoK || 0) - 2); i < Math.min(p.length, (this._autoK || 0) + 6); i++) if (p[i][0] === s.c && p[i][1] === s.r) { k = i; break; }
    if (k < 0) k = p.findIndex(([c, r]) => c === s.c && r === s.r);
    if (k < 0) { s.autoPath = this.planAuto(); this._autoK = 0; return null; }
    this._autoK = k;
    const t = p[k + 1];
    if (!t) return null;
    for (const [d, [dc, dr]] of Object.entries(AZ.DIRS)) if (s.c + dc === t[0] && s.r + dr === t[1]) return d;
    return null;
  }
  // ------------------------------------------------------------------ actions
  async interact() {
    const s = this.s, w = this.w, U = AZ.U;
    const b = this.burgHere();
    if (b) return this.town(b);
    if (s.voyage && s.aboard) return this.shipTalk();
    const [dc, dr] = AZ.DIRS[s.dir];
    const around = [[s.c, s.r], [s.c + dc, s.r + dr], ...[[0, -1], [1, 0], [0, 1], [-1, 0], [1, 1], [-1, -1], [1, -1], [-1, 1]].map(([a, b2]) => [s.c + a, s.r + b2])];
    const reg = this.sim && this.sim.regAt(s.c, s.r, 1.5).find(x => x.a > 200);
    if (reg) { const P2 = w.P; return this.ui.say(`<b class="side">${U.esc(reg.name)}</b> of ${U.esc(P2.states[reg.state].fullName)} ${AZ.T("data")}: about ${U.num(Math.round(reg.a / 100) * 100)} men (${U.num(reg.a0)} when the war began), ${reg.status === "march" ? `marching on ${U.esc(P2.burgs[reg.target]?.name || "?")}` : reg.status === "retreat" ? "falling back to its base" : "in camp"} ${AZ.T("mixed")}.`); }
    for (const [c, r] of around) {
      if (!w.inb(c, r)) continue;
      const ms = w.markersAt.get(w.idx(c, r)), us = w.unitsAt.get(w.idx(c, r));
      if (ms) return this.events.marker(ms[0], false);
      if (us) await this.threadsAt({ unit: `${us[0].state}:${us[0].i}` });
      if (us) return this.ui.say(us.map(u => `<b class="side">${U.esc(u.name)}</b> of ${U.esc(w.P.states[u.state].fullName)} ${AZ.T("data")}<br>${U.esc(u.note).replace(/\n/g, "<br>")}`));
    }
    if (s.aboard && s.vessel) {
      const t = [s.c + dc, s.r + dr];
      if (w.isLand(...t) && !w.navigable(...t, s.vessel.cls)) {
        const k = await this.ui.choose(`Go ashore here? The ${U.esc(s.vessel.kind.toLowerCase())} waits${s.vessel.mode === "hired" ? "; the crew's wages run on" : ""}.`, [{ label: "Go ashore" }, { label: "Stay aboard" }], { cancel: 1 });
        if (k === 0) { s.aboard = false; s.auto = false; s.vessel.anchored = true; s.c = t[0]; s.r = t[1]; this.afterStep(); }
        return;
      }
    } else if (s.vessel && Math.abs(s.vessel.c - s.c) + Math.abs(s.vessel.r - s.r) <= 1) {
      s.aboard = true; s.c = s.vessel.c; s.r = s.vessel.r; this.ui.toast("Back aboard."); this.afterStep(); return;
    }
    return this.ui.say([this.know.describe(s.c, s.r, s.aboard).join(" ")], "Look");
  }
  async town(b) {
    const s = this.s, U = AZ.U, T = AZ.T, w = this.w, P = AZ.Prices;
    const people = this.know.townPeople(b, this);
    const charged = new Set();
    this.inTownOf = b; this.checkCheckpoints(); this.inTownOf = null;
    while (this.ui.active) await new Promise(r => setTimeout(r, 30));
    for (;;) {
      const opts = [];
      for (const a of this.pendingActs(b)) opts.push({ label: `★ ${U.esc(a.label)}`, cls: "hook", act: "do:" + a.id });
      for (const [th, st] of this.threadSteps(b)) opts.push({ label: `◆ ${U.esc(th.title)}: ${U.esc(st.text)}`, cls: "side", act: "thread", th });
      opts.push(...this.boardOptions(b));
      if (b.port || (this.sim && this.sim.lines.some(L => L.from === b.i))) opts.push({ label: b.port ? "Harbour and coach office: sailings, coaches, boats for hire" : "Coach office: coaches and carriers' wagons", act: "harbour" });
      opts.push({ label: `Market: food 🟡 ${P.ration(w, b)} a day; goods to buy and sell`, act: "market" });
      opts.push({ label: `Inn: a room until morning (🟡 ${P.inn(w, b)})${this.shipWarn()}`, act: "inn", disabled: s.purse < P.inn(w, b) });
      opts.push({ label: `Give alms at the ${b.temple ? "temple" : "shrine"} (🟡 ${P.alms(w, b)})`, act: "alms", disabled: s.purse < P.alms(w, b) });
      opts.push({ label: "Notice board: work and errands", act: "board", cls: "side" });
      // marked places in or beside the town can be visited from the town itself
      for (const n of w.near(b.t[0], b.t[1], 2)) if (n.kind === "marker") opts.push({ label: `Visit the ${U.esc(n.o.name)} (${U.esc(n.o.type)}, ${n.d < 0.5 ? "in town" : "just outside"})`, cls: "side", act: { go: () => this.events.marker(n.o, false) } });
      for (const p of people) if (p.role !== "Notice board") opts.push({ label: `${p.role}${p.name ? `: ${U.esc(p.name)}` : ""}`, act: p });
      if (s.cond.fever || s.cond.gravely) opts.push({ label: `Ask the ${b.temple ? "priest" : "shrine-keeper"} to treat your fever (${this.healCost(b) ? "🟡 " + this.healCost(b) : "free"})`, act: "heal", disabled: s.purse < this.healCost(b) });
      if (s.cond.damaged && b.port && s.vessel) opts.push({ label: `Have the boat repaired (🟡 ${P.repair(w, b)}, 12 h)`, act: "repair", disabled: s.purse < P.repair(w, b) });
      opts.push({ label: "Leave", act: "leave" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)}</b> · ${AZ.Clock.fmt(s.clock)} · 🟡 ${U.rn(s.purse, 2)} · food ${s.sup.food} rations${this.voyageLine()}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.act === "leave") break;
      if (typeof o.act === "string" && o.act.startsWith("do:")) o.act = { "do:alms": "alms", "do:rest": "inn", "do:book": "harbour" }[o.act] || o.act;
      if (typeof o.act === "string" && o.act.startsWith("do:")) { await this.doActInTown(o.act.slice(3), b); continue; }
      if (o.act === "thread") { await this.completeStep(o.th, b); continue; }
      if (o.act === "harbour") { await this.harbour(b); if (s.aboard) break; continue; }
      if (o.act === "market") { await this.market(b); continue; }
      if (o.act === "board") { await this.noticeBoard(b); continue; }
      if (o.act === "inn") {
        const t0 = s.clock;
        const out = this.events.fx({ coin: -P.inn(w, b), time: Math.max(1, AZ.Clock.nextDawn(s.clock, this.lat()) - s.clock), cure: ["hurt"] });
        this.slept();
        const act = this.doAct("rest", b);
        await this.ui.say(`You sleep in ${U.esc(b.name)}. ${AZ.Clock.span(s.clock - t0)} pass ${T("mixed")}.${out}${act ? ` <span class="hook">★ ${U.esc(act.label)}</span>` : ""}`); continue;
      }
      if (o.act === "alms") {
        const out = this.events.fx({ coin: -P.alms(w, b), time: 2, stand: [["f", w.C.religion[b.cell], 1]] }, `Alms given in ${U.esc(b.name)}.`);
        const act = this.doAct("alms", b);
        await this.ui.say(`You give alms at the ${b.temple ? "temple" : "shrine"} of the ${U.esc(w.P.religions[w.C.religion[b.cell]].name)}.${out}${act ? ` <span class="hook">★ ${U.esc(act.label)}</span>` : ""}`); continue;
      }
      if (o.act === "heal") { const out = this.events.fx({ coin: -this.healCost(b), time: 6, cure: ["fever", "gravely"] }, `Treated for fever in ${U.esc(b.name)}.`); await this.ui.say(`Bitter tea, cool cloths and a long prayer. By evening the fever breaks.${out}`); continue; }
      if (o.act === "repair") { const out = this.events.fx({ coin: -P.repair(w, b), time: 12, cure: ["damaged"] }, `Repairs in ${U.esc(b.name)}.`); await this.ui.say(`Shipwrights work through the day.${out}`); continue; }
      if (o.act && o.act.go) { await o.act.go(); if (s.aboard) break; continue; }
      const p = o.act;
      if (p.cost && !charged.has(p.role)) { charged.add(p.role); const h = p.cost(); if (h) s.clock += h; }
      await this.ui.say(p.talk(), `${p.role}${p.name ? " · " + U.esc(p.name) : ""}`);
      this.dirty = true;
    }
  }
  async doActInTown(id, b) {
    if (id === "book") return this.harbour(b);
    if (id === "rest") return this.ui.say("Take a room at the inn for the night: that is the rest the plan has in mind.");
    if (id === "alms") return this.ui.say("Give alms at the temple: that is what the plan has in mind.");
    const act = this.doAct(id, b);
    if (act) await this.ui.say(`<span class="hook">★ ${AZ.U.esc(act.label)}</span>`);
  }
  async rest() {
    const s = this.s, U = AZ.U, w = this.w;
    if (s.voyage && s.aboard) return this.shipTalk();
    const sick = s.cond.fever || s.cond.hurt;
    const atSea = s.aboard && !w.isLand(s.c, s.r);
    const opts = [{ label: atSea ? "Anchor until dawn" : "Camp until dawn" }, { label: "Wait 1 hour" }, { label: "Wait 3 hours" }, { label: "Wait 6 hours" }, { label: "Two days, to recover", disabled: !sick }, { label: "Never mind" }];
    const k = await this.ui.choose(atSea ? "Heave to or anchor?" : "Make camp or wait?", opts, { cancel: 5 });
    if (k === 5) return;
    const t0 = s.clock;
    if (k === 4) { this.events.fx({ time: 48, cure: ["fever", "hurt"] }, "Rested two days."); this.ui.toast("Two days' rest. You feel yourself again."); return; }
    if (k === 0) {
      s.clock = AZ.Clock.nextDawn(s.clock, this.lat());
      if (s.vessel) { s.vessel.anchored = true; s.vessel.morale = Math.min(100, (s.vessel.morale || 70) + 4); s.vessel.nightKey = Math.floor(s.clock / 24); }
      const act = this.doAct("anchor");
      if (act) this.ui.toast(`<span class="hook">★ ${U.esc(act.label)}</span>`, "gold");
    } else s.clock += [0, 1, 3, 6][k];
    this.ui.toast(`${AZ.Clock.span(s.clock - t0)} pass. ${AZ.Clock.fmt(s.clock)}.`);
    this.dirty = true;
  }
  cycleLens(d = 1) {
    this.lensIdx = (this.lensIdx + d + AZ.LENSES.length) % AZ.LENSES.length;
    this.ui.toast(`Lens: <b>${AZ.LENSES[this.lensIdx].name}</b>`);
    this.dirty = true;
  }
  toggleInspect() { this.inspectOn = !this.inspectOn; this.ui.el.panel.classList.toggle("on", this.inspectOn); this.dirty = true; }
  started() { this._steps = 0; this.dirty = true; this.s.region = ""; this.afterStep(); }
  // ------------------------------------------------------------------ loop
  frame(now) {
    if (!this.s) return;
    const s = this.s;
    if (this.anim && now - this.anim.t0 >= this.anim.dur) this.anim = null;
    if (!this.anim && !this.ui.busy()) {
      this.tick();
      if (this.ui.busy()) { /* a crew call or a departure opened a window */ }
      else if (s.voyage && s.aboard && s.voyage.state === "sea" && !s.voyPause) this.voyageStep();
      else if (s.auto) { const d = this.autoDir(); if (d) this.tryMove(d); else { this.setAuto(false); s.autoPath = null; } }
      else if (this.held.length) this.tryMove(this.held[this.held.length - 1]);
    }
    let cx = s.c, cy = s.r;
    if (this.anim) { const t = Math.min(1, (now - this.anim.t0) / this.anim.dur); cx = this.anim.from[0] + (this.anim.to[0] - this.anim.from[0]) * t; cy = this.anim.from[1] + (this.anim.to[1] - this.anim.from[1]) * t; }
    const frame = this.anim ? 1 + (Math.floor(now / 120) % 2) : 0;
    const sprites = [];
    if (this.sim) for (const r of this.sim.regs) if (r.a > 200 && Math.abs(r.t[0] - s.c) < 45 && Math.abs(r.t[1] - s.r) < 28) sprites.push({ img: this.ren.art.unit({ state: r.state, naval: false }), c: r.t[0], r: r.t[1] });
    if (s.vessel && !(s.aboard && !s.voyage)) sprites.push({ img: this.ren.art.vessel(s.vessel.cls === "ship" ? "ship" : "boat", "left"), c: s.vessel.c, r: s.vessel.r });
    if (s.voyage && !s.aboard && s.voyage.state === "port" && s.voyage.at) sprites.push({ img: this.ren.art.vessel("ship", "left"), c: s.voyage.at[0], r: s.voyage.at[1] });
    const me = s.aboard && s.voyage && s.voyage.mode === "land" ? this.ren.art.vessel("wagon", s.dir === "left" ? "left" : "right") : s.aboard ? this.ren.art.vessel(s.voyage ? "ship" : s.vessel?.cls === "ship" ? "ship" : "boat", s.dir === "left" ? "left" : "right")
      : this.ren.art.walker(s.dir, frame, this.tv.pal);
    sprites.push({ img: me, c: cx, r: cy });
    const cp = this.cpNext(), leg = cp && cp.legIn;
    this.ren.draw({ camX: cx + 0.5, camY: cy + 0.5, sprites, lens: AZ.LENSES[this.lensIdx], light: AZ.Clock.light(s.clock, this.lat()),
      course: s.voyage && s.voyage.course ? s.voyage.course : leg ? leg.chain : null, goal: cp ? cp.tile : null, waypoint: s.waypoint, time: now,
      weather: this.weather().kind, nights: leg && leg.nights ? leg.nights.map(n => n.tile) : null, path: s.auto && !s.voyage ? s.autoPath : null });
    if (this.dirty) { this.dirty = false; this.hud(); }
    if (now - (this._pf || 0) > 60) { this._pf = now; this.ren.prefetch(cx + 0.5, cy + 0.5); }
  }
};
