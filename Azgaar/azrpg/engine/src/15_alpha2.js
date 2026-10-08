// ---------------------------------------------------------------------------------------------
// Alpha 2 wiring: the simulation drives markets, lines, zones and armies; the game reads it.
// What the player knows is what has reached them: news (heard in towns), timetables (read at
// harbours and coach offices) and prices (seen at markets) are kept in the journal with dates.
// ---------------------------------------------------------------------------------------------
(() => {
  const G = AZ.Game.prototype, U = AZ.U;
  // zones come from the simulation once it runs
  const zonesOfCell0 = AZ.World.prototype.zonesOfCell;
  AZ.World.prototype.zonesOfCell = function (cell) { return AZ.sim ? AZ.sim.zonesOfCell(cell) : zonesOfCell0.call(this, cell); };
  const ration0 = AZ.Prices.ration;
  AZ.Prices.ration = function (w, b) {
    if (AZ.sim && b && AZ.sim.mk.get(b.market)) return U.rn(Math.max(0.05, AZ.sim.foodFor(b).price * 0.1 * (1 + AZ.Prices.tax(w, b))), 2);
    return ration0.call(this, w, b);
  };
  AZ.Prices.goodPrice = function (w, b, gid) { const M = AZ.sim && AZ.sim.mk.get(b.market); return M && M.base[gid] != null ? AZ.sim.price(M, gid) * (1 + AZ.Prices.tax(w, b)) : null; };

  const fresh0 = G.fresh, load0 = G.loadGame, save0 = G.saveGame, tick0 = G.tick, after0 = G.afterStep, depart0 = G.depart, step0 = G.voyageStep, quest0 = G.questOffers, tile0 = G.stepTile;
  G.fresh = function (...a) { fresh0.apply(this, a); this.sim = AZ.sim = new AZ.Sim(this.w, this.jr); Object.assign(this.s, { known: [], lineSeen: {}, priceBook: {} }); this.sim.advanceTo(this.s.clock); };
  G.loadGame = function () { const ok = load0.call(this); if (!ok) return false; this.sim = AZ.sim = new AZ.Sim(this.w, this.jr); this.sim.load(this.s.simState); for (const k of ["known", "lineSeen", "priceBook"]) this.s[k] = this.s[k] || (k === "known" ? [] : {}); return true; };
  G.saveGame = function () { if (this.sim && this.s) this.s.simState = this.sim.save(); return save0.call(this); };
  G.tick = function () {
    if (this.sim && this.s) {
      this.sim.advanceTo(this.s.clock);
      if (this.sim.changed) { this.sim.changed = false; this.ren.lensCache.clear(); this.ren._lensW = {}; this.dirty = true; }
    }
    return tick0.call(this);
  };
  G.afterStep = function (...a) {
    after0.apply(this, a);
    const s = this.s, w = this.w;
    if (!this.sim || !s) return;
    const b = this.burgHere();
    if (b) { this.learnNews(b); this.noteLines(b); }
    // armies on the move: sightings, and the errands that ask you to count them
    const sight = this.know.sightTiles(s.c, s.r, s.aboard);
    for (const r of this.sim.regAt(s.c, s.r, sight)) {
      if (r.a <= 200) continue;
      const key = `sim:${r.id}:${Math.floor(s.clock / 72)}`;
      if (!s.seen.u.includes(key)) { s.seen.u.push(key); this.ui.toast(`On the move: the ${U.esc(r.name)} of ${U.esc(w.P.states[r.state].name)}, ${this.know.dirDist(s.c, s.r, r.t).txt} ${AZ.T("data")}`, "teal"); }
      for (const th of s.threads) if (!th.done && th.steps[th.phase].goal?.observe === r.id && Math.hypot(r.t[0] - s.c, r.t[1] - s.r) <= 2) {
        th.steps[th.phase].text += `: about ${U.num(Math.round(r.a / 100) * 100)} men, ${r.status === "march" ? `marching on ${w.P.burgs[r.target]?.name || "?"}` : r.status === "retreat" ? "falling back" : "in camp"}, seen ${AZ.Clock.fmt(s.clock)}`;
        this.completeStep(th);
      }
    }
  };
  // ---------------------------------------------------------------- news
  G.learnNews = function (b) {
    const s = this.s, w = this.w, fresh = [];
    for (const n of this.sim.news) {
      if (s.known.includes(n.id)) continue;
      const mi = Math.hypot(n.tile[0] - b.t[0], n.tile[1] - b.t[1]) * w.miles;
      if (s.clock >= n.t + (mi / (AZ.SIM.newsMilesPerDay * (this.tv.trait === "well-connected" ? 1.5 : 1))) * 24) { s.known.push(n.id); fresh.push(n); }
    }
    if (!fresh.length) return;
    for (const n of fresh) {
      this.log(`News in ${U.esc(b.name)}: ${U.esc(n.text)} <span class="dim">(happened ${AZ.Clock.fmt(n.t)})</span>`, "news");
      if (Math.hypot(n.tile[0] - s.c, n.tile[1] - s.r) * w.miles < 1500) this.addLead({ key: `n${n.id}`, name: n.text.slice(0, 60), type: n.kind, t: n.tile, from: "news" });
    }
    this.ui.toast(`News in ${U.esc(b.name)}: ${U.esc(fresh[fresh.length - 1].text)}${fresh.length > 1 ? ` (and ${fresh.length - 1} more; J)` : ""}`, "teal");
  };
  G.noteLines = function (b) {
    const s = this.s;
    for (const d of this.sim.departures(b, s.clock, 1)) s.lineSeen[d.L.id] = { t: s.clock, ok: d.ok, why: d.why || "" };
    for (const L of this.sim.lines) if (L.to === b.i && !s.lineSeen[L.id]) s.lineSeen[L.id] = { t: s.clock, ok: this.sim.lineStatus(L).ok, why: this.sim.lineStatus(L).why || "", heard: true };
  };
  G.notePrices = function (b) {
    const M = this.sim.mk.get(b.market); if (!M) return;
    const f = this.sim.foodFor(b);
    this.s.priceBook[M.i] = { t: this.s.clock, at: b.name, ration: AZ.Prices.ration(this.w, b), rations: f.rations, season: this.sim.season(b) };
  };
  // ---------------------------------------------------------------- harbour and coach office
  G.fareFor = function (L, b) { const w = this.w; const A = w.P.burgs[L.from], B = w.P.burgs[L.to]; const miles = L.mode === "sea" ? Math.hypot(B.t[0] - A.t[0], B.t[1] - A.t[1]) * w.miles * 1.15 : L.miles; return L.mode === "sea" ? AZ.Prices.fare(w, b, miles) : U.rn(Math.max(0.5, miles * 0.006) * (1 + AZ.Prices.tax(w, b)), 2); };
  G.harbour = async function (b) {
    const s = this.s, w = this.w, P = AZ.Prices, sim = this.sim;
    if (s.vessel && s.vessel.crew && this.vesselHere(b) && this.doAct("book")) this.ui.toast(`<span class="hook">★ Your ${U.esc(s.vessel.kind.toLowerCase())} and crew are ready: passage arranged.</span>`, "gold");
    for (;;) {
      this.noteLines(b);
      const cp = this.cpHere(), planDest = cp && cp.place.burg === b && cp.legOut ? cp.legOut.place.burg : null;
      const deps = sim.departures(b, s.clock).filter(d => d.t > s.clock).slice(0, 12);
      const opts = [];
      for (const d of deps) {
        const L = d.L, dest = w.P.burgs[L.to], stance = sim.rel(this.tv.homeState, L.flag), refuse = stance === "Enemy", dear = /Suspicion|Rival/.test(stance);
        const fare = U.rn(this.fareFor(L, b) * (dear ? 1.5 : 1), 2), planned = L.mode === "sea" && (planDest === dest || (L.via || []).includes(planDest?.i));
        opts.push({ label: `${planned ? "★ " : ""}${L.mode === "sea" ? "⛵" : "🐎"} ${U.esc(L.ship)} to ${U.esc(dest.name)} · ${AZ.Clock.fmt(d.t)} (in ${AZ.Clock.span(d.t - s.clock)}) · every ${L.period} days · 🟡 ${fare}${(L.via || []).length ? ` · via ${L.via.map(i => U.esc(w.P.burgs[i].name)).join(", ")}` : ""}${d.ok ? "" : ` · <span class="late">not running: ${U.esc(d.why)}</span>`}${refuse ? ` · <span class="late">will not carry people from ${U.esc(w.P.states[this.tv.homeState]?.name)} (${stance})</span>` : dear ? ` · dearer for people from ${U.esc(w.P.states[this.tv.homeState]?.name)}` : ""}`, cls: planned ? "hook" : "", act: "book", d, fare, disabled: !d.ok || refuse || s.purse < fare || !!s.voyage });
        if (L.mode === "sea" && d.ok && this.canCrew()) opts.push({ label: `   … or sign on as crew aboard ${U.esc(L.ship)} (no fare; work the passage)`, act: "crew", d, fare: 0, disabled: !!s.voyage });
      }
      if (!deps.length) opts.push({ label: "No sailings or coaches from here in the next twelve days", disabled: true });
      const boatH = b.port ? w.harbour(b, "boat") : null;
      if (boatH && !s.vessel) {
        const crew = 3;
        opts.push({ label: `Hire a sailing boat with a crew of ${crew}: 🟡 ${U.rn(P.hire(w, b) + crew * P.wage(w, b), 2)} a day, three days paid now; you feed the crew`, act: "hire", disabled: s.purse < 3 * (P.hire(w, b) + crew * P.wage(w, b)) });
      }
      if (s.vessel && s.vessel.mode === "owned" && !s.vessel.crew && this.vesselHere(b)) opts.push({ label: `Hire a crew of 3 for your boat (🟡 ${U.rn(3 * P.wage(w, b) * 3, 2)} for three days)`, act: "crewup", disabled: s.purse < 3 * P.wage(w, b) * 3 });
      if (s.vessel && s.vessel.mode === "hired" && this.vesselHere(b)) opts.push({ label: `Pay off the crew and return the boat${s.vessel.owed ? ` (owed 🟡 ${s.vessel.owed})` : ""}`, act: "payoff" });
      opts.push({ label: "Back", act: "back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)}: ${b.port ? "harbour and coach office" : "coach office"}</b> · 🟡 ${U.rn(s.purse, 2)}${this.voyageLine()}<br><span class="dim">Timetables are fixed; what runs depends on war, quarantine and the weather of the world ${AZ.T("mixed")}</span>`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.act === "back") return;
      if (o.act === "book" || o.act === "crew") {
        const L = o.d.L, dest = w.P.burgs[L.to], crew = o.act === "crew";
        if (!crew) s.purse = U.rn(s.purse - o.fare, 2);
        const at = L.mode === "sea" ? w.harbour(b, "ship").t : b.t.slice();
        const captain = this.know.person(`cap:line:${L.key}`, L.cul);
        s.voyage = { ship: L.ship, captain, flag: L.flag, role: crew ? "crew" : "passenger", fare: crew ? 0 : o.fare, cls: L.mode === "sea" ? "ship" : "land", mode: L.mode, speed: L.speed, hpd: L.hpd,
          stops: [...(L.via || []).map(i => ({ b: i, name: w.P.burgs[i].name, stay: 6 + Math.round(U.rnd2(i, L.id, 3) * 10) })), { b: dest.i, name: dest.name, stay: 0 }], boarded: false, leg: 0, state: "port", at, portBurg: b.i, departAt: o.d.t, planned: planDest === dest && L.mode === "sea", from: b.i, why: L.why, line: L.id, course: null, pos: 0, transport: L.transport };
        this.doAct("book");
        this.log(`${crew ? "Signed on" : "Booked"} ${U.esc(L.ship)} to ${U.esc(dest.name)}, leaving ${AZ.Clock.fmt(o.d.t)}.`, "hook");
        await this.ui.say([`${crew ? "You sign the articles" : `🟡 ${o.fare} buys a place`} on ${U.esc(L.ship)} (${U.esc(L.transport)}), ${U.esc(captain)} ${L.mode === "sea" ? "master" : "driving"}: ${U.esc(L.why)} ${AZ.T("mixed")}.`,
          `It leaves <b>${AZ.Clock.fmt(o.d.t)}</b>, in ${AZ.Clock.span(o.d.t - s.clock)}, and does not wait. Bring your own food. Board from town (Space) before it leaves.`]);
        return;
      }
      if (o.act === "hire") {
        const crew = 3, first = U.rn(3 * (P.hire(w, b) + crew * P.wage(w, b)), 2);
        s.purse = U.rn(s.purse - first, 2);
        s.vessel = { mode: "hired", kind: "Sailing boat", cls: "boat", speed: 6, hpd: 12, crew, morale: 70, c: boatH.t[0], r: boatH.t[1], wage: P.wage(w, b), hire: P.hire(w, b), home: b.i };
        this.doAct("book"); this.log(`Hired a sailing boat in ${U.esc(b.name)}.`, "hook");
        await this.ui.say([`The boat is yours to command, with ${crew} hands ${AZ.T("new")}. You pay 🟡 ${first} now; wages and hire come due each dawn.`, `They sail from dawn and anchor at night, as boats do ${AZ.T("data")}. They eat from your stores. Board from town (Space), then steer or press F.`]);
        continue;
      }
      if (o.act === "crewup") { const cost = U.rn(3 * P.wage(w, b) * 3, 2); s.purse = U.rn(s.purse - cost, 2); s.vessel.crew = 3; s.vessel.morale = 70; s.vessel.strikes = 0; this.ui.toast("Three hands sign on."); continue; }
      if (o.act === "payoff") { s.purse = U.rn(Math.max(0, s.purse - (s.vessel.owed || 0)), 2); this.log(`Returned the hired boat in ${U.esc(b.name)}.`); s.vessel = null; s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; this.ui.toast("The crew is paid off and the boat returned."); this.dirty = true; return; }
    }
  };
  // a booked passage may be cancelled at the last moment; a coach takes the roads
  G.depart = function () {
    const s = this.s, v = s.voyage, w = this.w;
    if (v && v.line != null && v.leg === 0 && this.sim) {
      const st = this.sim.lineStatus(this.sim.lines[v.line]);
      if (!st.ok) {
        const port = w.P.burgs[v.portBurg];
        s.purse = U.rn(s.purse + (v.fare || 0), 2); s.voyage = null;
        if (this.riding() || s.aboard && !s.vessel) { s.aboard = false; s.c = port.t[0]; s.r = port.t[1]; this.anim = null; }
        this.log(`${U.esc(v.ship)} did not leave: ${U.esc(st.why)}.`, "hook");
        return this.ui.say(`<b>${U.esc(v.ship)} does not leave.</b> ${U.cap(U.esc(st.why))}. Your fare is returned ${AZ.T("mixed")}.`);
      }
    }
    if (!v || v.mode !== "land") return depart0.call(this);
    if (!this.riding()) { this.log(`Missed ${U.esc(v.ship)}.`, "hook"); s.voyage = null; this.dirty = true; return this.ui.say(`<b>${U.esc(v.ship)} has left without you.</b> The fare is gone.`); }
    const tb = w.P.burgs[v.stops[v.leg].b];
    const course = w.withMiles(w.path(v.at, tb.t, (c, r) => w.isLand(c, r), { limit: 200000, cost: (c, r) => { const B = w.bits(c, r); return B.road ? 0.4 : B.trail ? 0.7 : 3; } }));
    if (!course) { s.voyage = null; s.aboard = false; s.purse = U.rn(s.purse + (v.fare || 0), 2); return this.ui.say("There is no road. The fare is returned."); }
    v.course = course; v.pos = 0; v.state = "sea"; v.milesPerStep = course.mps;
    this.log(`${U.esc(v.ship)} left for ${U.esc(tb.name)}.`);
    this.ui.toast(`${U.esc(v.ship)} sets off for ${U.esc(tb.name)}. Space for the coach, F for faster days, P to pause.`);
    this.dirty = true;
  };
  G.voyageStep = function () {
    const s = this.s, v = s.voyage;
    if (v && v.mode === "land" && v.hpd < 24) {
      const sun = AZ.Clock.sun(s.clock, this.lat());
      if (sun.hour >= sun.rise + v.hpd || sun.hour < sun.rise) { s.clock = AZ.Clock.nextDawn(s.clock, this.lat()); this.slept(); this.ui.toast(`${U.esc(v.ship)} halts for the night; on again at dawn.`); this.dirty = true; return; }
    }
    return step0.call(this);
  };
  // ---------------------------------------------------------------- markets from the simulation
  G.goodQuote = function (b, gid) {
    const sim = this.sim, M = sim && sim.mk.get(b.market);
    if (!M || M.base[gid] == null) return null;
    const p = sim.price(M, gid), tax = AZ.Prices.tax(this.w, b), stock = Math.floor(M.stock[gid] || 0);
    const makes = (b.production || {})[gid] > 0 || M.centre === b.i;
    const rec = { taken: 0, get f() { return 1; }, set f(v) { if (v > 1) M.stock[gid] = Math.max(0, (M.stock[gid] || 0) - 1); else M.stock[gid] = (M.stock[gid] || 0) + 1; } };
    const hg = this.tv.trait === "haggler";
    return { buy: U.rn(p * (1 + tax) * (hg ? 0.9 : 1), 2), sell: U.rn(p * 0.85 * (hg ? 1.1 : 1), 2), stock, canBuy: makes && stock >= 1, mk: M, rec };
  };
  G.market = async function (b) {
    const s = this.s, w = this.w, sim = this.sim;
    for (;;) {
      this.notePrices(b);
      const f = sim.foodFor(b), ration = AZ.Prices.ration(w, b), cap = this.capacity(), eat = this.eaters();
      const opts = [];
      for (const n of [1, 5, 10, 20, 40]) {
        const need = n * eat;
        opts.push({ label: `Food for ${n} day${n > 1 ? "s" : ""}${eat > 1 ? ` for ${eat} (${need} rations)` : ""}: 🟡 ${U.rn(need * ration, 2)}`, n, kind: "food", disabled: s.purse < need * ration || s.sup.food + need > cap.food || need > this.foodLeft(b, f) });
      }
      opts.push({ label: `Trade goods (you carry ${this.goodsCount()} of ${cap.goods} units)`, kind: "goods" }, { label: "Back", kind: "back" });
      const head = `<b>${U.esc(b.name)} market</b> · 🟡 ${U.rn(s.purse, 2)} · you have ${s.sup.food} rations<br>For sale to travellers this week: <b>${this.foodLeft(b, f)}</b> rations at 🟡 ${ration} (${sim.season(b)}; the market's food stock, of which a town this size spares a share) ${AZ.T("mixed")}`;
      const k = await this.ui.choose(head, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.kind === "back") return;
      if (o.kind === "goods") { await this.tradeGoods(b); continue; }
      if (o.kind === "food") { const need = o.n * eat; s.purse = U.rn(s.purse - need * ration, 2); s.sup.food += need; sim.takeFood(b, need); this.foodTook(b, need); s.hunger = 0; delete s.cond.hungry; delete s.cond.starving; }
      this.dirty = true;
    }
  };
  // ---------------------------------------------------------------- errands about armies
  G.questOffers = function (b) {
    const out = quest0.call(this, b), sim = this.sim, s = this.s, w = this.w, P = w.P;
    if (!sim) return out;
    const st = sim.stateOf(b);
    for (const war of sim.wars.filter(x => !x.over && (x.a === st || x.d === st))) {
      const enemy = war.a === st ? war.d : war.a;
      const reg = sim.regs.filter(r => r.state === enemy && r.a > 200).map(r => ({ r, d: Math.hypot(r.t[0] - b.t[0], r.t[1] - b.t[1]) })).filter(o => o.d > 3 && o.d < 160).sort((x, y) => x.d - y.d)[0];
      if (!reg) continue;
      const mi = Math.round(reg.d * w.miles), pay = U.rn(2 + mi * 0.006, 2);
      out.push({ title: `Eyes on the ${reg.r.name}`, pay, cost: 0, why: `${P.states[st].name} is at war with ${P.states[enemy].name} (the ${war.name}) ${AZ.T("data")}. The watch's last word puts the ${reg.r.name} ${this.know.dirDist(b.t[0], b.t[1], reg.r.t).txt}; armies move, and news is slow.`,
        dist: mi, deadline: s.clock + (Math.ceil((mi * 2) / 40) + 6) * 24, giver: b.i,
        steps: [{ text: `Find the ${reg.r.name} and count them (within two tiles)`, goal: { observe: reg.r.id } }, { text: `Report to the watch in ${b.name}`, goal: { burg: b.i, role: "Captain of the watch" }, reward: { coin: pay, stand: [["s", st, 2]] } }] });
    }
    return out.filter(o => !s.threads.some(t => t.title === o.title));
  };
  G.stepTile = function (st) { const g = st.goal || {}; if (g.observe && this.sim) { const r = this.sim.regs.find(x => x.id === g.observe); return r ? r.t : null; } return tile0.call(this, st); };
  // ---------------------------------------------------------------- journal sections
  G.newsHtml = function () {
    const s = this.s, items = (s.known || []).map(i => this.sim.news[i]).filter(Boolean).slice(-25).reverse();
    return `<h3>News, as it reached you</h3>${items.length ? items.map(n => `<div><span class="dim">${AZ.Clock.fmt(n.t)}</span> ${U.esc(n.text)}</div>`).join("") : '<p class="dim">None yet. News travels about 60 miles a day and is heard in towns.</p>'}`;
  };
  G.timetableHtml = function () {
    const s = this.s, w = this.w, rows = Object.entries(s.lineSeen || {}).map(([id, seen]) => [this.sim.lines[+id], seen]).filter(([L]) => L).sort((a, b) => b[1].t - a[1].t).slice(0, 40);
    if (!rows.length) return `<h3>Timetables you know</h3><p class="dim">Read them at harbours and coach offices.</p>`;
    return `<h3>Timetables you know</h3><table class="plan"><tr><th>Line</th><th>From → to</th><th>Every</th><th>Next</th><th>Last known</th></tr>${rows.map(([L, seen]) => {
      const per = L.period * 24, next = L.phase + Math.ceil((s.clock - L.phase) / per) * per;
      return `<tr><td>${L.mode === "sea" ? "⛵" : "🐎"} ${U.esc(L.ship)}</td><td>${U.esc(w.P.burgs[L.from].name)} → ${U.esc(w.P.burgs[L.to].name)}</td><td>${L.period} d</td><td>${AZ.Clock.fmt(next)}</td><td class="${seen.ok ? "" : "late"}">${seen.ok ? "running" : U.esc(seen.why)} <span class="dim">(${seen.heard ? "heard" : "seen"} ${AZ.Clock.fmt(seen.t)})</span></td></tr>`;
    }).join("")}</table>`;
  };
})();
