// ---------------------------------------------------------------------------------------------
// The game: one traveller, one journey. The plan (the map's journey) is fixed; the record is
// what happens in play. Everything that costs time is counted against the plan.
// ---------------------------------------------------------------------------------------------
AZ.DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

AZ.Game = class {
  constructor(w, ren, ui, jr, store) {
    this.w = w; this.ren = ren; this.ui = ui; this.jr = jr; this.store = store;
    this.key = `azrpg:${w.P.world.seed}:${jr ? jr.J.name : "free"}`;
    this.held = []; this.anim = null; this.s = null; this.lensIdx = 0; this.inspectOn = false;
    this.walkSpeed = (w.W.transports.find(t => t.name === "On foot (light)") || { speed: 5 }).speed;
  }
  // ------------------------------------------------------------------ state
  fresh(seed) {
    const w = this.w, jr = this.jr;
    const start = jr ? jr.origin.tile : (w.P.burgs.find(b => b && b.capital) || {}).t || [0, 0];
    this.tv = AZ.makeTraveller(w, jr, seed);
    this.know = new AZ.Know(w, jr, this.tv);
    this.s = { seed, c: start[0], r: start[1], dir: "down", aboard: false, vessel: null, clock: 6, stage: 0,
               rec: [], log: [], seen: { m: [], u: [], b: [], z: [], st: [], cu: [], re: [], bi: [] },
               waypoint: null, auto: false, region: "", done: false };
    this.explored = new Uint8Array(Math.ceil((w.cols * w.rows) / 8));
    this.s.rec[0] = { start: 6 };
    this.reveal();
  }
  saveGame() {
    if (!this.s) return;
    const runs = [];
    for (let i = 0; i < this.explored.length;) { let j = i; while (j < this.explored.length && this.explored[j] === this.explored[i] && j - i < 65535) j++; runs.push(this.explored[i], j - i); i = j; }
    const data = { v: 1, s: this.s, ex: runs, lens: this.lensIdx };
    try { this.store.setItem(this.key, JSON.stringify(data)); return true; } catch (e) { return false; }
  }
  loadGame() {
    let data = null;
    try { data = JSON.parse(this.store.getItem(this.key) || "null"); } catch (e) { data = null; }
    if (!data || !data.s) return false;
    this.s = data.s;
    this.tv = AZ.makeTraveller(this.w, this.jr, this.s.seed);
    this.know = new AZ.Know(this.w, this.jr, this.tv);
    this.explored = new Uint8Array(Math.ceil((this.w.cols * this.w.rows) / 8));
    let o = 0;
    for (let k = 0; k < data.ex.length; k += 2) { this.explored.fill(data.ex[k], o, o + data.ex[k + 1]); o += data.ex[k + 1]; }
    this.lensIdx = data.lens || 0;
    return true;
  }
  hasSave() { try { return !!this.store.getItem(this.key); } catch (e) { return false; } }
  seg() { return this.jr && !this.s.done ? this.jr.segs[this.s.stage] || null : null; }
  get clock() { return this.s.clock; }
  log(html, cls = "") { this.s.log.push({ t: this.s.clock, html, cls }); if (this.s.log.length > 400) this.s.log.shift(); }
  lat() { return this.w.latlon(this.s.c, this.s.r)[0]; }
  // ------------------------------------------------------------------ plan versus record
  planNow() {
    const seg = this.seg();
    if (!seg) return this.jr ? this.jr.planEnd : this.s.clock;
    if (!seg.moving) return seg.planStart;
    const pr = this.jr.progress(seg, this.s.c, this.s.r);
    return this.jr.planTimeAt(seg, this.s.aboard ? pr.frac : 0);
  }
  delta() { return this.s.clock - this.planNow(); }
  deltaText() {
    const d = this.delta();
    if (Math.abs(d) < 1) return "on plan";
    return `${AZ.Clock.span(Math.abs(d))} ${d > 0 ? "behind" : "ahead of"} plan`;
  }
  goal() {
    const seg = this.seg();
    if (!seg) return null;
    return seg.moving ? seg.endTile : seg.place.tile;
  }
  // ------------------------------------------------------------------ movement
  passable(c, r) {
    const w = this.w;
    if (!w.inb(c, r)) return { ok: false, why: "The edge of the known world." };
    const id = w.idx(c, r), land = w.isLand(c, r);
    if (this.s.aboard) {
      if (!land) return { ok: true };
      const b = w.burgAt.get(id);
      if (b && b.port) return { ok: true, dock: b };
      if (this.jr && this.jr.course.has(id)) return { ok: true };
      return { ok: false, why: "Land ahead. Press Space to go ashore; the ship will wait." };
    }
    const v = this.s.vessel;
    if (v && v.c === c && v.r === r) return { ok: true, board: true };
    if (!land) return { ok: false, why: "Too deep to wade. You need a boat." };
    return { ok: true };
  }
  stepHours(c, r, dc, dr) {
    const w = this.w, U = AZ.U;
    if (this.s.aboard) {
      const v = this.s.vessel, lat = w.latlon(c, r)[0], wd = w.wind(lat);
      let f = 1;
      if (wd != null) { const hd = Math.atan2(dc, -dr), wr = (wd * Math.PI) / 180; f = 1 + 0.1 * Math.cos(hd - wr); }
      // on the plan's course a step is worth the course's own miles (the track is a polyline;
      // its tile chain zigzags), so following the course costs what the plan says it costs
      const seg = this.seg();
      let miles = w.miles;
      if (seg && seg.moving) {
        const a = seg.chainPos.get(w.idx(this.s.c, this.s.r)), b = seg.chainPos.get(w.idx(c, r));
        if (a !== undefined && b !== undefined && Math.abs(a - b) === 1) miles = seg.miles / Math.max(1, seg.chain.length - 1);
      }
      return miles / v.speed / f;
    }
    const cell = w.cell(c, r), b = w.P.biomes[w.C.biome[cell]], B = w.bits(c, r);
    let f = B.road ? 0.8 : B.trail ? 1 : U.clamp((b.cost || 50) / 50, 1, 4);
    const rel = w.reliefAt(c, r);
    if (rel && !B.road) f *= /mount/i.test(rel.icon) ? 1.6 : 1.2;
    let h = (w.miles / this.walkSpeed) * f;
    if (B.river && !B.road && !B.trail) h += 0.5;
    if (AZ.Clock.light(this.s.clock, lat).phase === "night") h *= 1.5;
    return h;
  }
  tryMove(dir) {
    if (this.anim || this.ui.busy() || !this.s) return false;
    const [dc, dr] = AZ.DIRS[dir], s = this.s;
    s.dir = dir;
    const c = s.c + dc, r = s.r + dr, p = this.passable(c, r);
    if (!p.ok) {
      if (this._lastWhy !== p.why || performance.now() - (this._whyT || 0) > 2500) { this.ui.toast(p.why); this._lastWhy = p.why; this._whyT = performance.now(); }
      if (s.auto) this.setAuto(false);
      return false;
    }
    const hours = this.stepHours(c, r, dc, dr);
    this.anim = { from: [s.c, s.r], to: [c, r], t0: performance.now(), dur: s.auto ? (this.fast ? 28 : 70) : s.aboard ? 110 : 140 };
    s.c = c; s.r = r; s.clock += hours;
    if (s.aboard) { s.vessel.c = c; s.vessel.r = r; }
    if (p.board) { s.aboard = true; this.ui.toast(`Aboard the ${s.vessel.kind.toLowerCase()}.`); }
    this.afterStep(p);
    return true;
  }
  afterStep(p) {
    const s = this.s, w = this.w, U = AZ.U, T = AZ.T;
    // the crew keeps the plan's hours: boats that sail less than a full day anchor at night
    if (s.aboard && s.vessel.hpd < 24) {
      const sun = AZ.Clock.sun(s.clock, this.lat());
      if (sun.hour > sun.rise + s.vessel.hpd || sun.hour < sun.rise) {
        s.clock = AZ.Clock.nextDawn(s.clock, this.lat());
        this.ui.toast(`The crew anchors for the night (${s.vessel.hpd} sailing hours a day). Away at dawn, ${AZ.Clock.fmt(s.clock)}.`);
      }
    }
    this.reveal();
    const cell = w.cell(s.c, s.r), id = w.idx(s.c, s.r);
    // region banner, as RPG Maker shows a map's name on entry
    const b = w.burgAt.get(id);
    let key, title, sub;
    if (b) { key = "b" + b.i; title = b.name; sub = `${U.cap(b.group.replace("_", " "))} · ${w.P.states[b.state]?.fullName || "unclaimed"}`; }
    else if (w.isLand(s.c, s.r)) {
      const st = w.C.state[cell], pv = w.C.province[cell];
      key = `l${st}:${pv}`; title = pv ? w.P.provinces[pv].fullName : st ? w.P.states[st].fullName : "Neutral lands";
      sub = `${st ? w.P.states[st].fullName + " · " : ""}${w.P.cultures[w.C.culture[cell]].name} · ${w.P.religions[w.C.religion[cell]].name}`;
    } else { key = "f" + w.C.feature[cell]; title = w.waterName(s.c, s.r); sub = s.aboard ? `${s.vessel.kind}` : ""; }
    if (key !== s.region) { s.region = key; this.ui.banner(U.esc(title), U.esc(sub)); }
    // discoveries
    const addSeen = (k, v) => { if (v != null && !s.seen[k].includes(v)) { s.seen[k].push(v); return true; } return false; };
    if (w.isLand(s.c, s.r)) { addSeen("st", w.C.state[cell]); addSeen("cu", w.C.culture[cell]); addSeen("re", w.C.religion[cell]); addSeen("bi", w.C.biome[cell]); }
    if (b && addSeen("b", b.i)) this.log(`Reached ${U.esc(b.name)} (${b.group}).`);
    let pause = false;
    for (const z of w.zonesOfCell(cell)) if (addSeen("z", z.i)) {
      this.ui.toast(`<b class="hook">${U.esc(z.name)}</b>: you have entered a ${z.type.toLowerCase()} zone ${T("data")}`, "gold");
      this.log(`Entered the ${U.esc(z.name)} (${z.type}).`, "hook"); pause = true;
    }
    const sight = this.know.sightTiles(s.c, s.r, s.aboard);
    for (const n of w.near(s.c, s.r, sight)) {
      if (n.kind === "marker" && addSeen("m", n.o.i)) {
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
    if (p && p.dock) this.ui.toast(`Docked at ${U.esc(p.dock.name)}. Space to go into town.`);
    this.checkArrival();
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
  // ------------------------------------------------------------------ the journey
  checkArrival() {
    const seg = this.seg(), s = this.s;
    if (!seg || !seg.moving || !s.aboard) return;
    const [ec, er] = seg.endTile, pb = seg.place.burg;
    const atBurg = pb && seg.place.at && s.c === pb.t[0] && s.r === pb.t[1];
    if (!(atBurg || (Math.abs(s.c - ec) <= 1 && Math.abs(s.r - er) <= 1))) return;
    this.setAuto(false);
    const U = AZ.U;
    if (pb && seg.place.at && pb.port && !atBurg) { s.c = pb.t[0]; s.r = pb.t[1]; s.vessel.c = s.c; s.vessel.r = s.r; this.anim = null; }
    s.rec[s.stage].end = s.clock;
    const msg = [`<b class="hook">Arrived: ${U.esc(seg.place.name)}</b> · ${AZ.Clock.fmt(s.clock)}. The plan had you here ${AZ.Clock.fmt(seg.planEnd)}: ${this.deltaTextAt(s.clock - seg.planEnd)}.`];
    this.log(`Arrived ${U.esc(seg.place.name)} at ${AZ.Clock.fmt(s.clock)} (${this.deltaTextAt(s.clock - seg.planEnd)}).`, "hook");
    s.stage++;
    s.rec[s.stage] = { start: s.clock };
    const next = this.seg();
    if (!next) return this.finish(msg);
    this.saveGame();
    if (!next.moving) {
      if (next.place.burg && next.place.at) msg.push(`Next: <b class="hook">${U.esc(next.name)}</b>. Go into ${U.esc(next.place.burg.name)} (Space on the town).`);
      else msg.push(`Next: <b class="hook">${U.esc(next.name)}</b>. Press R here when you are ready.`);
    }
    this.ui.say(msg);
  }
  deltaTextAt(d) { return Math.abs(d) < 1 ? "on plan" : `${AZ.Clock.span(Math.abs(d))} ${d > 0 ? "behind" : "ahead"}`; }
  async performStage() {
    const seg = this.seg(), s = this.s, U = AZ.U;
    if (!seg || seg.moving) return;
    await this.ui.say(this.know.stageScene(seg, this));
    s.clock += seg.duration || 0;
    s.rec[s.stage].end = s.clock;
    this.log(`${U.esc(seg.name)}: done at ${AZ.Clock.fmt(s.clock)} (${this.deltaTextAt(s.clock - seg.planEnd)}).`, "hook");
    s.stage++;
    s.rec[s.stage] = { start: s.clock };
    const next = this.seg();
    if (!next) return this.finish([]);
    if (next.moving) {
      const tr = this.w.W.transports.find(t => t.name === next.transport) || { speed: next.speed, hoursPerDay: next.hoursPerDay };
      s.vessel = { kind: next.transport, speed: next.speed || tr.speed, hpd: next.hoursPerDay || tr.hoursPerDay, c: s.c, r: s.r };
      s.aboard = true;
      if (next.hoursPerDay < 24 && AZ.Clock.light(s.clock, this.lat()).phase === "night") s.clock = AZ.Clock.nextDawn(s.clock, this.lat());
      await this.ui.say([`Aboard the ${U.esc(next.transport.toLowerCase())}: <b class="hook">${U.esc(next.name)}</b>, ${U.num(next.miles)} miles to ${U.esc(next.place.name)} ${AZ.T("data")}.`,
        `Press <b>F</b> to follow the plan's course (it pauses for sightings and arrivals), or steer with the arrow keys. Hold Shift with F to go faster.`]);
    }
    this.saveGame();
    this.dirty = true;
  }
  async finish(msg) {
    const s = this.s, U = AZ.U, jr = this.jr;
    s.done = true;
    this.saveGame();
    const d = s.clock - jr.planEnd;
    await this.ui.say([...msg, `<b class="hook">The pilgrimage is complete.</b> ${U.esc(this.tv.name)} reaches ${U.esc(jr.dest.name)} on ${AZ.Clock.fmt(s.clock)}, ${this.deltaTextAt(d)} the plan.`,
      `You saw ${s.seen.st.length} states, ${s.seen.cu.length} cultures, ${s.seen.re.length} faiths, ${s.seen.m.length} marked places and ${s.seen.b.length} towns. The journal (J) has the full record; you can keep exploring.`]);
  }
  setAuto(on) {
    const s = this.s, seg = this.seg();
    if (on && (!seg || !seg.moving || !s.aboard)) { this.ui.toast(s.aboard ? "No course to follow on this stage." : "Autopilot works aboard, on a sailing stage."); return; }
    s.auto = on;
    this.dirty = true;
  }
  autoDir() {
    const s = this.s, seg = this.seg(), w = this.w;
    if (!seg || !seg.moving) return null;
    const k = seg.chainPos.get(w.idx(s.c, s.r));
    let target;
    if (k !== undefined) target = seg.chain[Math.min(k + 1, seg.chain.length - 1)];
    else { const pr = this.jr.progress(seg, s.c, s.r); target = seg.chain[Math.min(pr.pos + 1, seg.chain.length - 1)]; }
    if (!target || (target[0] === s.c && target[1] === s.r)) return null;
    const opts = Object.entries(AZ.DIRS).map(([d, [dc, dr]]) => ({ d, c: s.c + dc, r: s.r + dr }))
      .filter(o => this.passable(o.c, o.r).ok).map(o => ({ ...o, dist: Math.hypot(o.c - target[0], o.r - target[1]) }))
      .sort((a, b) => a.dist - b.dist);
    return opts.length ? opts[0].d : null;
  }
  // ------------------------------------------------------------------ actions
  async interact() {
    const s = this.s, w = this.w, U = AZ.U, seg = this.seg();
    const b = w.burgAt.get(w.idx(s.c, s.r));
    if (b) return this.town(b);
    const [dc, dr] = AZ.DIRS[s.dir];
    for (const [c, r] of [[s.c, s.r], [s.c + dc, s.r + dr]]) {
      if (!w.inb(c, r)) continue;
      const ms = w.markersAt.get(w.idx(c, r)), us = w.unitsAt.get(w.idx(c, r));
      if (ms) return this.ui.say(ms.map(m => `<b class="side">${U.esc(m.name)}</b> (${m.type}) ${AZ.T("data")}<br>${U.esc(m.note).replace(/\n/g, "<br>")}${m.links.length ? `<br><a href="${U.esc(m.links[0])}" target="_blank" rel="noopener">linked page</a>` : ""}`));
      if (us) return this.ui.say(us.map(u => `<b class="side">${U.esc(u.name)}</b> of ${U.esc(w.P.states[u.state].fullName)} ${AZ.T("data")}<br>${U.esc(u.note).replace(/\n/g, "<br>")}`));
    }
    if (s.aboard) {
      if (seg && !seg.moving && !seg.place.at && Math.hypot(s.c - seg.place.tile[0], s.r - seg.place.tile[1]) <= 2) return this.performStage();
      const t = [s.c + dc, s.r + dr];
      if (w.isLand(...t)) {
        const k = await this.ui.choose(`Go ashore here? The ${U.esc(s.vessel.kind.toLowerCase())} will wait.`, [{ label: "Go ashore" }, { label: "Stay aboard" }], { cancel: 1 });
        if (k === 0) { s.aboard = false; s.auto = false; s.c = t[0]; s.r = t[1]; this.afterStep(); }
        return;
      }
    } else if (s.vessel && Math.abs(s.vessel.c - s.c) + Math.abs(s.vessel.r - s.r) <= 1) {
      s.aboard = true; s.c = s.vessel.c; s.r = s.vessel.r; this.ui.toast("Back aboard."); this.afterStep(); return;
    }
    return this.ui.say([this.know.describe(s.c, s.r, s.aboard).join(" ")], "Look");
  }
  async town(b) {
    const s = this.s, U = AZ.U, T = AZ.T;
    const people = this.know.townPeople(b, this);
    const charged = new Set();
    for (;;) {
      const seg = this.seg();
      const opts = [];
      const stageHere = seg && !seg.moving && seg.place.burg === b;
      if (stageHere) opts.push({ label: `★ ${U.esc(seg.name)} (${seg.duration} h)`, cls: "hook", act: "stage" });
      for (const p of people) opts.push({ label: `${p.role}${p.name ? `: ${U.esc(p.name)}` : ""}`, act: p });
      const v = s.vessel, docked = v && v.c === b.t[0] && v.r === b.t[1];
      if (docked && s.aboard) opts.push({ label: `Go ashore and walk (the ${U.esc(v.kind.toLowerCase())} waits here)`, act: "ashore" });
      if (docked && !s.aboard) opts.push({ label: `Board your ${U.esc(v.kind.toLowerCase())}`, act: "board" });
      opts.push({ label: "Rest until morning", act: "rest" }, { label: "Leave", act: "leave" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)}</b> · ${AZ.Clock.fmt(s.clock)}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.act === "leave") break;
      if (o.act === "ashore") { s.aboard = false; s.auto = false; this.ui.toast("Ashore. Walk back into town and choose Board to sail again."); this.dirty = true; break; }
      if (o.act === "board") { s.aboard = true; this.ui.toast("Aboard."); this.dirty = true; break; }
      if (o.act === "stage") { await this.performStage(); if (!this.seg() || this.seg().moving) break; continue; }
      if (o.act === "rest") {
        const t0 = s.clock; s.clock = AZ.Clock.nextDawn(s.clock, this.lat());
        await this.ui.say(`You sleep in ${U.esc(b.name)}. ${AZ.Clock.span(s.clock - t0)} pass ${T("mixed")}.`); this.dirty = true; continue;
      }
      const p = o.act;
      if (p.cost && !charged.has(p.role)) { charged.add(p.role); const h = p.cost(); if (h) s.clock += h; }
      await this.ui.say(p.talk(), `${p.role}${p.name ? " · " + U.esc(p.name) : ""}`);
      this.dirty = true;
    }
  }
  async rest() {
    const s = this.s, seg = this.seg(), U = AZ.U;
    if (seg && !seg.moving && !seg.place.at && Math.hypot(s.c - seg.place.tile[0], s.r - seg.place.tile[1]) <= 2) return this.performStage();
    const k = await this.ui.choose(s.aboard ? "Heave to and wait?" : "Make camp?", [{ label: "Until dawn" }, { label: "One hour" }, { label: "Never mind" }], { cancel: 2 });
    if (k === 2) return;
    const t0 = s.clock;
    s.clock = k === 0 ? AZ.Clock.nextDawn(s.clock, this.lat()) : s.clock + 1;
    this.ui.toast(`${AZ.Clock.span(s.clock - t0)} pass. ${AZ.Clock.fmt(s.clock)}.`);
    this.dirty = true;
    void U;
  }
  cycleLens(d = 1) {
    this.lensIdx = (this.lensIdx + d + AZ.LENSES.length) % AZ.LENSES.length;
    this.ui.toast(`Lens: <b>${AZ.LENSES[this.lensIdx].name}</b>`);
    this.dirty = true;
  }
  // ------------------------------------------------------------------ HUD
  hud() {
    const s = this.s, w = this.w, U = AZ.U, el = this.ui.el, cell = w.cell(s.c, s.r), seg = this.seg();
    const b = w.burgAt.get(w.idx(s.c, s.r)), land = w.isLand(s.c, s.r);
    const place = b ? b.name : land ? (w.C.province[cell] ? w.P.provinces[w.C.province[cell]].name : w.C.state[cell] ? w.P.states[w.C.state[cell]].name : "Neutral lands") : w.waterName(s.c, s.r);
    const terr = land ? `${w.P.biomes[w.C.biome[cell]].name} · ${w.heightStr(w.h(s.c, s.r))}` : `depth ${w.heightStr(w.h(s.c, s.r), true)}`;
    const light = AZ.Clock.light(s.clock, this.lat());
    el.loc.innerHTML = `<div class="big">${U.esc(place)}</div><div>${U.esc(terr)} · ${w.temp(w.tempC(s.c, s.r))}</div><div>${AZ.Clock.fmt(s.clock)} · ${light.phase} · ${w.W.calendar?.year || ""} ${w.W.calendar?.eraShort || ""}</div>`;
    if (seg) {
      const g = this.goal(), dd = g ? this.know.dirDist(s.c, s.r, g) : null;
      const obj = seg.moving ? `${s.aboard ? "Sail" : "Return to your ship, then sail"} to ${U.esc(seg.place.name)}` : seg.place.at ? `In ${U.esc(seg.place.name)}: Space on the town` : `At the stop (${U.esc(seg.place.name)}): press R`;
      const d = this.delta();
      el.trip.innerHTML = `<div class="hook">Stage ${seg.k + 1}/${this.jr.segs.length}: ${U.esc(seg.name)}</div><div>${obj}</div>` +
        (dd && dd.mi > 1 ? `<div><span class="arrow">${U.arrow(g[0] - s.c, g[1] - s.r)}</span> ${U.num(dd.mi)} mi ${dd.dir}</div>` : "") +
        `<div class="${d > 24 ? "late" : d < -1 ? "early" : ""}">${this.deltaText()}</div>` +
        (s.vessel ? `<div class="dim">${s.aboard ? "Aboard" : "Ashore; ship waits"}: ${U.esc(s.vessel.kind)}${s.auto ? ' · <b class="hook">autopilot</b>' : ""}</div>` : "");
    } else el.trip.innerHTML = this.jr ? `<div class="hook">${U.esc(this.jr.J.name)}: complete</div><div class="dim">Free exploration</div>` : "";
    const lens = AZ.LENSES[this.lensIdx];
    if (lens.id !== "none") { el.legend.style.display = "block"; el.legend.innerHTML = `<b>${lens.name}</b> (L)<br>${U.esc(lens.label(w, cell, s.c, s.r) ?? "")}`; }
    else el.legend.style.display = "none";
    if (this.inspectOn) el.panel.innerHTML = this.know.inspect(s.c, s.r, this) + `<p class="dim">I to close · tags: ${AZ.T("data")} file ${AZ.T("mixed")} rule on data ${AZ.T("new")} invented</p>`;
    this.mini();
  }
  mini() {
    const cv = this.ui.el.mini, ctx = cv.getContext("2d"), s = this.s, w = this.w;
    const W = cv.width, H = cv.height, sc = 1, x0 = s.c - W / 2 / sc, y0 = s.r - H / 2 / sc;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#0a0c18"; ctx.fillRect(0, 0, W, H);
    ctx.drawImage(this.ren.worldImage(), x0, y0, W / sc, H / sc, 0, 0, W, H);
    const lens = AZ.LENSES[this.lensIdx];
    if (lens.id !== "none") { ctx.globalAlpha = 0.45; ctx.drawImage(this.ren.lensWorld(lens), x0, y0, W / sc, H / sc, 0, 0, W, H); ctx.globalAlpha = 1; }
    const seg = this.seg();
    if (seg && seg.moving) { ctx.fillStyle = "rgba(245,197,66,0.9)"; for (const [c, r] of seg.chain) ctx.fillRect((c - x0) * sc, (r - y0) * sc, 1, 1); }
    if (s.vessel && !s.aboard) { ctx.fillStyle = "#fff"; ctx.fillRect((s.vessel.c - x0) * sc - 1, (s.vessel.r - y0) * sc - 1, 3, 3); }
    ctx.fillStyle = "#ff3b3b"; ctx.fillRect(W / 2 - 2, H / 2 - 2, 4, 4);
  }
  // ------------------------------------------------------------------ screens
  worldMap() {
    const w = this.w, s = this.s, U = AZ.U, ui = this.ui;
    const maxW = Math.min(window.innerWidth - 40, 1600), sc = Math.min(maxW / w.cols, (window.innerHeight - 140) / w.rows);
    ui.modal(`<div class="mapwrap"><div class="maphead"><b>World map</b> · ${U.esc(w.P.world.name)} · lens: <span id="mlens">${AZ.LENSES[this.lensIdx].name}</span> · click: set a teal waypoint · L: lens · M/Esc: close</div><canvas id="wmap" width="${Math.round(w.cols * sc)}" height="${Math.round(w.rows * sc)}"></canvas><div id="minfo" class="dim">Brighter ground is ground you have seen.</div></div>`);
    const cv = document.getElementById("wmap"), ctx = cv.getContext("2d");
    const draw = () => {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(this.ren.worldImage(), 0, 0, cv.width, cv.height);
      const lens = AZ.LENSES[this.lensIdx];
      if (lens.id !== "none") { ctx.globalAlpha = 0.5; ctx.drawImage(this.ren.lensWorld(lens), 0, 0, cv.width, cv.height); ctx.globalAlpha = 1; }
      if (!this._fog) {
        this._fog = this.ren.mk(w.cols, w.rows);
      }
      const fctx = this._fog.getContext("2d"), img = fctx.createImageData(w.cols, w.rows);
      for (let i = 0; i < w.cols * w.rows; i++) if (!this.isExplored(i)) img.data[i * 4 + 3] = 110;
      fctx.putImageData(img, 0, 0);
      ctx.drawImage(this._fog, 0, 0, cv.width, cv.height);
      if (this.jr) for (const sg of this.jr.segs) if (sg.moving) {
        ctx.strokeStyle = sg.k === s.stage ? "rgba(245,197,66,1)" : "rgba(245,197,66,0.5)"; ctx.lineWidth = sg.k === s.stage ? 2 : 1;
        ctx.beginPath(); sg.chain.forEach(([c, r], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, (c + 0.5) * sc, (r + 0.5) * sc)); ctx.stroke();
      }
      for (const b of w.P.burgs) if (b) { ctx.fillStyle = b.capital ? "#fff" : "rgba(255,255,255,0.6)"; const z = b.capital ? 3 : 2; ctx.fillRect(b.t[0] * sc - z / 2, b.t[1] * sc - z / 2, z, z); }
      if (this.jr) for (const sg of this.jr.segs) { ctx.fillStyle = "#f5c542"; ctx.fillRect(sg.place.tile[0] * sc - 3, sg.place.tile[1] * sc - 3, 6, 6); }
      if (s.waypoint) { ctx.strokeStyle = "#4fd1c5"; ctx.lineWidth = 2; ctx.strokeRect(s.waypoint[0] * sc - 5, s.waypoint[1] * sc - 5, 10, 10); }
      if (s.vessel && !s.aboard) { ctx.fillStyle = "#fff"; ctx.fillRect(s.vessel.c * sc - 3, s.vessel.r * sc - 3, 6, 6); }
      ctx.fillStyle = "#ff3b3b"; ctx.beginPath(); ctx.arc(s.c * sc, s.r * sc, 5, 0, 7); ctx.fill();
    };
    draw();
    cv.onclick = e => {
      const rect = cv.getBoundingClientRect(), c = Math.floor(((e.clientX - rect.left) / rect.width) * w.cols), r = Math.floor(((e.clientY - rect.top) / rect.height) * w.rows);
      s.waypoint = [c, r];
      const cell = w.cell(c, r), b = w.near(c, r, 3).find(n => n.kind === "burg");
      document.getElementById("minfo").innerHTML = `Waypoint: ${w.isLand(c, r) ? U.esc(w.P.biomes[w.C.biome[cell]].name) + " in " + U.esc(this.know.regionName(cell)) : U.esc(w.waterName(c, r))}${b ? " · near " + U.esc(b.o.name) : ""} · ${this.know.dirDist(s.c, s.r, [c, r]).txt} of you`;
      draw(); this.dirty = true;
    };
    ui.modalKey = e => {
      if (e.key === "l" || e.key === "L") { this.lensIdx = (this.lensIdx + (e.shiftKey ? -1 : 1) + AZ.LENSES.length) % AZ.LENSES.length; document.getElementById("mlens").textContent = AZ.LENSES[this.lensIdx].name; draw(); this.dirty = true; }
      else if (["Escape", "m", "M", "x", "X"].includes(e.key)) ui.closeModal();
    };
  }
  journal() {
    const s = this.s, U = AZ.U, jr = this.jr, tv = this.tv, w = this.w;
    const rows = jr ? jr.segs.map((sg, k) => {
      const rec = s.rec[k] || {};
      const d = rec.end != null ? rec.end - sg.planEnd : null;
      return `<tr class="${k === s.stage && !s.done ? "cur" : ""}"><td>${k + 1}</td><td>${U.esc(sg.name)}</td><td>${U.esc(sg.transport)}</td><td>${sg.moving ? U.num(sg.miles) : sg.duration + " h"}</td><td>${AZ.Clock.fmt(sg.planEnd)}</td><td>${rec.end != null ? AZ.Clock.fmt(rec.end) : "—"}</td><td class="${d > 24 ? "late" : ""}">${d != null ? this.deltaTextAt(d) : ""}</td></tr>`;
    }).join("") : "";
    const cnt = (k, list) => `${s.seen[k].length} of ${w.P[list].filter(x => x && !x.removed).length - (list === "states" || list === "cultures" || list === "religions" ? 1 : 0)}`;
    this.ui.modal(`<div class="sheet"><h2>Journal</h2>
      <h3>The traveller ${AZ.T("new")}</h3><p><b>${U.esc(tv.name)}</b>, ${tv.age}, ${U.esc(tv.trade)}. ${U.cap(U.esc(tv.why))}. ${w.P.cultures[tv.culture].name}; faith: ${w.P.religions[tv.faith]?.name}. Carries ${U.esc(tv.token)}.</p>
      ${jr ? `<h3>Plan and record</h3><p class="dim">Plan: the map's journey ${AZ.T("data")}, timed from Day 1 06:00 with each mode's speed and hours per day ${AZ.T("mixed")}. Record: your play.</p>
      <table class="plan"><tr><th>#</th><th>Stage</th><th>Mode</th><th>Miles / hours</th><th>Plan done</th><th>Record</th><th>Slippage</th></tr>${rows}</table>` : ""}
      <h3>Seen so far</h3><p>States ${cnt("st", "states")} · cultures ${cnt("cu", "cultures")} · faiths ${cnt("re", "religions")} · biomes ${s.seen.bi.length} · towns ${s.seen.b.length} · marked places ${s.seen.m.length} of ${w.P.markers.length} · forces ${s.seen.u.length} · zones ${s.seen.z.length} of ${w.P.zones.length}</p>
      <h3>Log</h3><div class="log">${s.log.slice().reverse().map(e => `<div class="${e.cls}"><span class="dim">${AZ.Clock.fmt(e.t)}</span> ${e.html}</div>`).join("") || "<div class='dim'>Nothing yet.</div>"}</div>
      <p class="dim">J or Esc to close</p></div>`, e => { if (["Escape", "j", "J", "x", "X"].includes(e.key)) this.ui.closeModal(); });
  }
  help() {
    this.ui.modal(`<div class="sheet"><h2>How to play</h2><table class="keys">
      <tr><th>Arrows / WASD</th><td>Walk, or steer the ship</td></tr><tr><th>Space / Enter</th><td>Go into a town · read a marker · hail a unit · go ashore / board · look around</td></tr>
      <tr><th>F</th><td>Autopilot along the plan's course (Shift+F: fast). Any arrow takes the helm.</td></tr>
      <tr><th>R</th><td>Rest or wait; at a sea stop, carry out the stage</td></tr><tr><th>I</th><td>Inspector: every data layer for the tile you stand on</td></tr>
      <tr><th>L / Shift+L</th><td>Lens: tint the map by biome, height, temperature, rain, state, province, culture, religion, population, market, resource, zones</td></tr>
      <tr><th>M</th><td>World map (click to set a waypoint)</td></tr><tr><th>J</th><td>Journal: traveller, plan versus record, log</td></tr>
      <tr><th>+ / −</th><td>Zoom</td></tr><tr><th>Esc</th><td>Menu</td></tr></table>
      <p>Gold is the main journey, teal is everything else worth a detour. Tags: ${AZ.T("data")} read from the map files · ${AZ.T("mixed")} a stated rule applied to data · ${AZ.T("new")} invented for this playthrough.</p>
      <p>One tile is ${AZ.U.num(this.w.miles, 2)} miles, the square of your Azgaar grid overlay. Every step costs time: walking speed and the biome's move cost on land; the vessel's speed and the latitude's wind at sea. Boats that sail fewer than 24 hours a day anchor at night, as the plan does.</p>
      <p class="dim">Esc to close</p></div>`);
  }
  async menu() {
    const k = await this.ui.choose("<b>Menu</b>", [{ label: "Journal (J)" }, { label: "World map (M)" }, { label: "Inspector (I)" }, { label: "Lens (L)" }, { label: "Save now" }, { label: "How to play (H)" }, { label: "New journey" }, { label: "Back" }], { cancel: 7 });
    if (k === 0) this.journal(); else if (k === 1) this.worldMap(); else if (k === 2) this.toggleInspect(); else if (k === 3) this.cycleLens();
    else if (k === 4) this.ui.toast(this.saveGame() ? "Saved in this browser." : "Could not save here.");
    else if (k === 5) this.help(); else if (k === 6) this.title(true);
  }
  toggleInspect() { this.inspectOn = !this.inspectOn; this.ui.el.panel.classList.toggle("on", this.inspectOn); this.dirty = true; }
  title(fromMenu) {
    const U = AZ.U, w = this.w, jr = this.jr, can = this.hasSave() && !fromMenu;
    let seed = (Date.now() ^ Math.floor(Math.random() * 1e9)) >>> 0;
    const show = () => {
      const tv = AZ.makeTraveller(w, jr, seed);
      this.ui.modal(`<div class="title"><div class="logo">${U.esc(jr ? jr.J.name : w.P.world.name)}</div>
        <div class="sub">${U.esc(w.P.world.name)} (${U.esc(w.P.world.folder)}) · year ${w.W.calendar?.year || "?"} ${U.esc(w.W.calendar?.era || "")}</div>
        <div class="card win"><div class="who">Your traveller ${AZ.T("new")}</div><b>${U.esc(tv.name)}</b>, ${tv.age}, ${U.esc(tv.trade)} · ${U.esc(w.P.cultures[tv.culture].name)}<br>${U.cap(U.esc(tv.why))}.</div>
        <ul class="choices big"><li data-a="new">▶ Begin with this traveller</li><li data-a="roll">Another traveller</li>${can ? '<li data-a="cont">Continue saved journey</li>' : ""}<li data-a="help">How to play</li></ul>
        <div class="dim">${U.num(w.cols)} × ${U.num(w.rows)} tiles of ${U.num(w.miles, 2)} mi · ${U.esc(w.P.grid.source)}</div></div>`, e => {
        const items = [...this.ui.el.modal.querySelectorAll("li")];
        let i = items.findIndex(li => li.textContent.startsWith("▶"));
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          items[i].textContent = items[i].textContent.replace(/^▶ /, "");
          i = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
          items[i].textContent = "▶ " + items[i].textContent;
        } else if (e.key === "Enter" || e.key === " ") act(items[i].dataset.a);
      });
      this.ui.el.modal.querySelectorAll("li").forEach(li => (li.onclick = () => act(li.dataset.a)));
    };
    const act = a => {
      if (a === "roll") { seed = (seed * 1664525 + 1013904223) >>> 0; show(); }
      else if (a === "help") { this.help(); this.ui.onModalClose = () => show(); }
      else if (a === "cont") { this.ui.closeModal(); this.loadGame(); this.started(); this.ui.toast(`Welcome back, ${U.esc(this.tv.name)}.`); }
      else if (a === "new") { this.ui.closeModal(); this.fresh(seed); this.started(); this.saveGame(); if (jr) this.ui.say(this.know.intro(this)); }
    };
    show();
  }
  started() { this._steps = 0; this.dirty = true; this.s.region = ""; this.afterStep(); }
  // ------------------------------------------------------------------ loop
  frame(now) {
    if (!this.s) return;
    const s = this.s;
    if (this.anim && now - this.anim.t0 >= this.anim.dur) this.anim = null;
    if (!this.anim && !this.ui.busy()) {
      if (s.auto) { const d = this.autoDir(); if (d) this.tryMove(d); else this.setAuto(false); }
      else if (this.held.length) this.tryMove(this.held[this.held.length - 1]);
    }
    let cx = s.c, cy = s.r;
    if (this.anim) { const t = Math.min(1, (now - this.anim.t0) / this.anim.dur); cx = this.anim.from[0] + (this.anim.to[0] - this.anim.from[0]) * t; cy = this.anim.from[1] + (this.anim.to[1] - this.anim.from[1]) * t; }
    const frame = this.anim ? 1 + (Math.floor(now / 120) % 2) : 0;
    const sprites = [];
    if (s.vessel && !s.aboard) sprites.push({ img: this.ren.art.vessel(s.vessel.kind === "Sailing boat" ? "boat" : "ship", "left"), c: s.vessel.c, r: s.vessel.r });
    const me = s.aboard ? this.ren.art.vessel(/boat|row/i.test(s.vessel.kind) ? "boat" : "ship", s.dir === "left" ? "left" : "right")
      : this.ren.art.walker(s.dir, frame, this.tv.pal);
    sprites.push({ img: me, c: cx, r: cy });
    const seg = this.seg();
    this.ren.draw({ camX: cx + 0.5, camY: cy + 0.5, sprites, lens: AZ.LENSES[this.lensIdx], light: AZ.Clock.light(s.clock, this.lat()),
      course: seg && seg.moving ? seg.chain : null, goal: this.goal(), waypoint: s.waypoint, time: now });
    if (this.dirty) { this.dirty = false; this.hud(); }
    if (now - (this._pf || 0) > 60) { this._pf = now; this.ren.prefetch(cx + 0.5, cy + 0.5); }
  }
};

AZ.boot = async function (packText) {
  const status = document.getElementById("status");
  try {
    const P = await AZ.loadPack(packText);
    const w = new AZ.World(P);
    const mk = (W, H) => { const c = document.createElement("canvas"); c.width = W; c.height = H; return c; };
    const art = new AZ.Art(w, mk);
    const cv = document.getElementById("view");
    const ren = new AZ.Renderer(w, art, cv, mk);
    const jr = P.journeys.length ? new AZ.Journey(w, P.journeys[0]) : null;
    let store;
    try { store = window.localStorage; store.getItem("x"); } catch (e) { store = { getItem: () => null, setItem: () => { throw e; } }; }
    const ui = new AZ.UI();
    const g = new AZ.Game(w, ren, ui, jr, store);
    AZ.game = g;
    const fit = () => { cv.width = window.innerWidth; cv.height = window.innerHeight; g.dirty = true; };
    window.addEventListener("resize", fit); fit();
    status.remove();
    const DK = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", w: "up", s: "down", a: "left", d: "right", W: "up", S: "down", A: "left", D: "right" };
    window.addEventListener("keydown", e => {
      if (e.target && e.target.tagName === "INPUT") return;
      if (ui.key(e)) { e.preventDefault(); return; }
      if (!g.s) return;
      const k = e.key;
      if (DK[k]) { e.preventDefault(); if (g.s.auto) g.setAuto(false); if (!g.held.includes(DK[k])) g.held.push(DK[k]); return; }
      if (k === " " || k === "Enter" || k === "z" || k === "Z") { e.preventDefault(); g.interact(); }
      else if (k === "f" || k === "F") { if (e.shiftKey) { g.fast = true; g.setAuto(true); } else { g.fast = false; g.setAuto(!g.s.auto); } }
      else if (k === "r" || k === "R") g.rest();
      else if (k === "i" || k === "I") g.toggleInspect();
      else if (k === "l" || k === "L") g.cycleLens(e.shiftKey ? -1 : 1);
      else if (k === "m" || k === "M") g.worldMap();
      else if (k === "j" || k === "J") g.journal();
      else if (k === "h" || k === "H" || k === "?") g.help();
      else if (k === "+" || k === "=") { ren.zoom = Math.min(4, ren.zoom + 1); g.dirty = true; }
      else if (k === "-" || k === "_") { ren.zoom = Math.max(1, ren.zoom - 1); g.dirty = true; }
      else if (k === "Escape" || k === "x" || k === "X") g.menu();
    });
    window.addEventListener("keyup", e => { const d = DK[e.key]; if (d) g.held = g.held.filter(x => x !== d); });
    window.addEventListener("blur", () => (g.held = []));
    // touch controls
    document.querySelectorAll("[data-pad]").forEach(btn => {
      const d = btn.dataset.pad;
      const on = e => { e.preventDefault(); if (g.s?.auto) g.setAuto(false); if (!g.held.includes(d)) g.held.push(d); };
      const off = e => { e.preventDefault(); g.held = g.held.filter(x => x !== d); };
      btn.addEventListener("pointerdown", on); btn.addEventListener("pointerup", off); btn.addEventListener("pointerleave", off); btn.addEventListener("pointercancel", off);
    });
    document.querySelectorAll("[data-key]").forEach(btn => btn.addEventListener("click", e => {
      e.preventDefault();
      window.dispatchEvent(new KeyboardEvent("keydown", { key: btn.dataset.key }));
    }));
    g.title();
    const loop = now => { g.frame(now); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  } catch (err) {
    status.textContent = "Could not load the world: " + err.message;
    console.error(err);
  }
};
