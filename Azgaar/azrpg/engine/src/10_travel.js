// ---------------------------------------------------------------------------------------------
// Travel, supplies and money.
//   Booked ship: a captain with his own itinerary (a cargo to land, ports to call at); a fixed
//   departure; the passenger cannot steer and the ship does not wait.
//   Hired or owned boat: the traveller steers; the crew eats from the traveller's stores, draws
//   daily wages, calls for anchor at dusk and for shelter in storms, and can be overruled at a
//   cost to morale. Low morale ends in mutiny.
//   Days: everyone eats once a day (water is not tracked for now). Hunger slows you;
//   in the end you collapse and wake somewhere else, poorer and later.
// ---------------------------------------------------------------------------------------------
Object.assign(AZ.COND, {
  hungry: { on: "you are hungry", off: "you have eaten", slow: 1.2, label: "hungry" },
  starving: { on: "you are starving", off: "you have eaten", slow: 1.5, label: "starving" },
  thirsty: { on: "you are thirsty", off: "you have drunk", slow: 1.4, label: "thirsty" },
});

Object.assign(AZ.Game.prototype, {
  eaters() { const v = this.s.vessel; return 1 + (v && v.crew && (v.mode === "hired" || v.mode === "owned") && !this.riding() ? v.crew : 0); },
  capacity() { const s = this.s, ride = this.riding(); return { food: s.vessel && !ride ? 220 : ride || s.voyage ? 60 : 20, goods: s.vessel && !ride ? 30 : ride || s.voyage ? 10 : 6 }; },
  refill() { /* water is not tracked for now */ },
  tick() {
    const s = this.s, w = this.w, U = AZ.U;
    if (!s || this.ui.busy()) return;
    const day = Math.floor(s.clock / 24);
    if (day > s.lastDay) {
      const n = Math.min(day - s.lastDay, 60); s.lastDay = day;
      for (let i = 0; i < n; i++) if (this.newDay()) return;
      if (this.riding() && s.voyage.state === "sea" && this.shipEvent && U.rnd2(day, s.seed % 100003, 41) < AZ.SHIP_EVENTS.rate) return this.shipEvent();
    }
    if (s.voyage && s.voyage.state === "port" && s.clock >= s.voyage.departAt) return this.depart();
    const wx = this.weather();
    if (wx.key !== s.wxKey) {
      s.wxKey = wx.key;
      if (wx.kind === "storm" && s.aboard && !w.isLand(s.c, s.r)) return this.stormCall();
      if (wx.kind !== s.wxKind && ["storm", "snow", "fog", "rain"].includes(wx.kind)) this.ui.toast(`Weather: ${wx.label} ${AZ.T("mixed")}`);
      s.wxKind = wx.kind;
    }
    const v = s.vessel;
    if (v && s.aboard && !this.riding() && v.crew && !this.harbourAt.has(w.idx(s.c, s.r)) && w.navigable(s.c, s.r, v.cls)) {
      const sun = AZ.Clock.sun(s.clock, this.lat()), key = Math.floor((s.clock + 12) / 24);
      if (sun.dl < 24 && (sun.hour >= sun.set + 0.75 || sun.hour < sun.rise) && v.nightKey !== key) { v.nightKey = key; return this.crewCall(); }
    }
    void U;
  },
  newDay() {
    const s = this.s, U = AZ.U, v = s.vessel;
    const eat = this.eaters();
    s.sup.food -= eat;
    if (this.riding()) { if (s.voyage.role === "crew") s.sup.food += eat; this.slept(); } // the ship feeds its crew; passengers sleep aboard
    if (s.sup.food < 0) { s.sup.food = 0; s.hunger++; if (v && v.crew) v.morale -= 15; } else s.hunger = 0;
    delete s.cond.hungry; delete s.cond.starving; delete s.cond.thirsty;
    if (s.hunger >= 3) s.cond.starving = true; else if (s.hunger >= 1) s.cond.hungry = true;
    if (v && v.crew && (v.mode === "hired" || v.mode === "owned")) {
      const due = U.rn(v.crew * v.wage + (v.hire || 0), 2);
      if (s.purse >= due) { s.purse = U.rn(s.purse - due, 2); v.morale = Math.min(100, v.morale + 1); }
      else { v.morale -= 20; v.owed = U.rn((v.owed || 0) + due, 2); this.ui.toast(`You cannot pay the crew (🟡 ${due} due). They mutter.`); this.log(`Wages unpaid (🟡 ${due}).`); }
      if (v.promise && s.clock > v.promise.by) { v.morale -= 10; this.ui.toast(`You promised the crew ${U.esc(v.promise.name)} and have not made it.`); v.promise = null; }
      if ((v.strikes || 0) > 0 && v.morale > 60) { v.calm = (v.calm || 0) + 1; if (v.calm >= 10) { v.strikes--; v.calm = 0; this.ui.toast("The crew's grievances fade. One strike forgiven."); } } else v.calm = 0;
    }
    if (s.voyage && s.voyage.role === "crew") s.voyage.earned = U.rn((s.voyage.earned || 0) + AZ.Prices.wage(this.w, null), 2);
    // fever runs its course unless treated: gravely ill on the third day, collapse on the sixth
    if (s.cond.fever || s.cond.gravely) {
      s.feverDays = (s.feverDays || 0) + 1;
      if (s.feverDays === 3) { delete s.cond.fever; s.cond.gravely = true; this.ui.toast("The fever is worse. You are gravely ill: find a priest, a healing spring, or rest two days."); }
      if (s.feverDays >= 6) { this.collapse("fever"); return true; }
    } else s.feverDays = 0;
    for (const [g0, rec] of Object.entries(s.mk || {})) for (const r of Object.values(rec)) { r.f = 1 + (r.f - 1) * 0.92; r.taken = Math.max(0, (r.taken || 0) * 0.85); void g0; }
    const left = s.sup.food / eat;
    if (left < 3 && left > 0) { const p = this.nearestPort(v?.cls); this.ui.toast(`Food low: about ${Math.floor(left)} day${left >= 2 ? "s" : ""} left${p && s.aboard ? `. Nearest harbour: ${U.esc(p.name)}, ${this.know.dirDist(s.c, s.r, p.t).txt}` : ""}.`); }
    if (s.hunger === 1) this.ui.toast("Your food is gone. Buy more at a market, fish, or forage.");
    if (v && v.crew && v.morale < 20 && s.aboard && !s.voyage) { this._ultimatum = true; }
    if (s.hunger >= 7) { this.collapse("hunger"); return true; }
    this.dirty = true;
    return false;
  },
  // ------------------------------------------------------------------ sleep
  awakeTick(h) {
    const s = this.s;
    s.awake = (s.awake || 0) + h;
    if (s.awake >= 44 && !this.ui.busy()) {
      this.ui.toast("You fall asleep where you stand, and wake ten hours later.");
      s.clock += 10; this.slept();
      if (s.vessel && s.aboard && s.vessel.crew) s.vessel.morale -= 5;
      this.log("Fell asleep from exhaustion.");
      return;
    }
    if (s.awake >= 30) { delete s.cond.tired; if (!s.cond.exhausted) this.ui.toast("You are exhausted. Sleep (R, or a room at an inn)."); s.cond.exhausted = true; }
    else if (s.awake >= 18) { if (!s.cond.tired) this.ui.toast("You are tired."); s.cond.tired = true; }
  },
  slept() { const s = this.s; s.awake = 0; delete s.cond.tired; delete s.cond.exhausted; },
  nearestPort(cls) {
    const s = this.s, w = this.w;
    let best = null, bd = 1e9;
    for (const b of w.P.burgs) if (b && b.port) { const h = w.harbour(b, cls || "boat"); if (!h) continue; const d = Math.hypot(h.t[0] - s.c, h.t[1] - s.r); if (d < bd) { bd = d; best = b; } }
    return best;
  },
  async collapse(cause) {
    const s = this.s, w = this.w, U = AZ.U;
    const b = w.near(s.c, s.r, 200).find(n => n.kind === "burg")?.o || this.nearestPort("boat");
    const lost = U.rn(s.purse / 2, 2);
    s.purse = U.rn(s.purse - lost, 2); s.clock += 72; s.hunger = 0; s.feverDays = 0; s.sup.food = Math.max(s.sup.food, 1);
    for (const k of ["hungry", "starving", "thirsty", "fever", "gravely"]) delete s.cond[k];
    this.slept();
    s.voyage = null; s.aboard = false; s.auto = false;
    if (s.vessel && s.vessel.mode === "hired") s.vessel = null;
    s.c = b.t[0]; s.r = b.t[1]; this.anim = null;
    this.log(`Collapsed from ${cause || "hunger"}; woke in ${U.esc(b.name)}.`, "hook");
    await this.ui.say([`You collapse${cause === "fever" ? " in the fever" : ""}. Days later you wake in ${U.esc(b.name)}, in a stranger's bed. Someone has been paid for your keep: 🟡 ${lost} is gone from your purse ${AZ.T("mixed")}.`]);
    this.afterStep();
  },
  async mutiny() {
    const s = this.s, w = this.w, U = AZ.U, v = s.vessel;
    const b = this.nearestPort(v.cls) || w.P.burgs.find(x => x && x.port);
    const h = w.harbour(b, v.cls);
    const miles = Math.hypot(h.t[0] - s.c, h.t[1] - s.r) * w.miles;
    s.clock += miles / v.speed;
    s.c = h.t[0]; s.r = h.t[1]; s.auto = false; this.anim = null;
    this.log(`Mutiny: the crew took the boat into ${U.esc(b.name)}.`, "hook");
    if (v.mode === "hired") { s.vessel = null; s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; }
    else { v.crew = 0; v.strikes = 0; v.c = h.t[0]; v.r = h.t[1]; }
    await this.ui.say([`<b class="hook">Mutiny.</b> Third strike: the crew turns the ${U.esc(v.kind.toLowerCase())} for ${U.esc(b.name)} and will not hear another word ${AZ.T("mixed")}.`,
      v.mode === "hired" ? "In harbour they walk off with the boat's owner, and your deposit goes with them. You are ashore." : "In harbour they take their wages in silence and leave. Your boat has no crew; hire one at the harbour."]);
    this.afterStep();
  },
  async crewCall() {
    const s = this.s, v = s.vessel, U = AZ.U, w = this.w;
    if (v.morale < 20) return this.ultimatum();
    const port = this.nearestPort(v.cls), h = port && w.harbour(port, v.cls), mi = h ? Math.round(Math.hypot(h.t[0] - s.c, h.t[1] - s.r) * w.miles) : null;
    const nearLand = w.near(s.c, s.r, 3).length > 0 || [[0, 2], [2, 0], [0, -2], [-2, 0]].some(([a, b]) => w.isLand(s.c + a, s.r + b));
    const k = await this.ui.choose(`<b>The crew calls for anchor.</b> Sunset, ${AZ.Clock.fmt(s.clock)}. They have sailed their hours (${v.hpd} a day by custom ${AZ.T("data")}). Morale ${Math.round(v.morale)}${v.strikes ? `, strikes ${v.strikes}/3` : ""}.`,
      [{ label: "Anchor here until dawn" }, { label: `Sail on through the night (morale −12${nearLand ? ", and reefs near" : ""})` }, { label: port ? `Make for ${U.esc(port.name)} harbour (${U.num(mi)} mi)` : "No harbour near", disabled: !port }], { cancel: 0 });
    if (k === 0) {
      const t0 = s.clock; s.clock = AZ.Clock.nextDawn(s.clock, this.lat()); v.anchored = true; v.morale = Math.min(100, v.morale + 4); this.slept();
      const act = this.doAct("anchor");
      this.ui.toast(`At anchor ${AZ.Clock.span(s.clock - t0)}. ${act ? `<span class="hook">★ ${U.esc(act.label)}</span>` : ""}`, act ? "gold" : "");
    } else if (k === 1) {
      v.morale -= 12;
      if (nearLand && AZ.U.rnd2(s.c, s.r, Math.floor(s.clock)) < 0.15) { this.events.fx({ cond: "damaged", time: 3 }, "Struck a reef at night."); this.ui.toast("In the dark you touch a reef. The hull is damaged."); }
      else this.ui.toast(`The crew sails on, sullen. Morale ${Math.round(v.morale)}.`);
    } else { s.waypoint = h.t; v.morale -= 2; this.setAuto(true); }
    this.dirty = true;
  },
  // three strikes: each time morale breaks, the crew states its terms; the third time they take the boat
  async ultimatum() {
    const s = this.s, v = s.vessel, U = AZ.U, w = this.w, P = AZ.Prices;
    s.auto = false;
    v.strikes = (v.strikes || 0) + 1;
    this.log(`The crew's ultimatum (strike ${v.strikes}).`, "hook");
    if (v.strikes >= 3) return this.mutiny();
    const port = this.nearestPort(v.cls), h = port && w.harbour(port, v.cls);
    const days = h ? Math.ceil((Math.hypot(h.t[0] - s.c, h.t[1] - s.r) * w.miles) / (v.speed * v.hpd)) + 2 : 0;
    const bonus = U.rn(v.crew * (v.wage || 0.2) * 5, 2);
    const k = await this.ui.choose(`<b>The crew has had enough</b> (strike ${v.strikes} of 3). The mate speaks for them: better pay, or a port, or they will take matters into their own hands ${AZ.T("mixed")}.`,
      [{ label: `Pay a bonus of 🟡 ${bonus} (morale +30)`, disabled: s.purse < bonus }, { label: port ? `Promise ${U.esc(port.name)} within ${days} days (morale +15)` : "No port to promise", disabled: !port }, { label: "Refuse, and face them down" }], { cancel: 2 });
    if (k === 0) { s.purse = U.rn(s.purse - bonus, 2); v.morale = Math.min(100, v.morale + 30); this.ui.toast("The money goes round the forecastle. They go back to work."); }
    else if (k === 1) { v.morale += 15; v.promise = { name: port.name, b: port.i, by: s.clock + days * 24 }; s.waypoint = h.t; this.setAuto(true); this.ui.toast(`You give your word: ${U.esc(port.name)}.`); }
    else { v.morale += 5; this.ui.toast("They back down, for now. Nobody meets your eye."); }
    this.dirty = true;
    void P;
  },
  async stormCall() {
    const s = this.s, U = AZ.U, w = this.w;
    const until = (Math.floor(s.clock / 12) + 1) * 12;
    if (s.voyage) {
      const h = Math.max(2, until - s.clock);
      s.clock = until;
      this.log(`Storm: ${U.esc(s.voyage.ship)} hove to for ${Math.round(h)} h.`);
      return this.ui.say(`<b>Storm.</b> The captain of the ${U.esc(s.voyage.ship)} heaves to and rides it out: ${Math.round(h)} hours lost ${AZ.T("mixed")}.`);
    }
    const v = s.vessel;
    if (!v) return;
    const port = this.nearestPort(v.cls), h = port && w.harbour(port, v.cls);
    const k = await this.ui.choose(`<b>A storm is coming up.</b> ${v.crew ? `The crew wants to run for shelter. Morale ${Math.round(v.morale)}.` : ""}`,
      [{ label: `Heave to until it passes (${Math.round(until - s.clock)} h)` }, { label: port ? `Run for ${U.esc(port.name)} harbour` : "No harbour near", disabled: !port }, { label: "Ride it out under sail (morale −10, risk of damage)" }], { cancel: 0 });
    if (k === 0) { s.clock = until; this.ui.toast("The storm blows itself out."); }
    else if (k === 1) { s.waypoint = h.t; this.setAuto(true); }
    else { v.morale -= 10; if (AZ.U.rnd2(s.c, s.r, Math.floor(s.clock) + 5) < 0.3) this.events.fx({ cond: "damaged" }, "Storm damage."), this.ui.toast("A spar carries away. The boat is damaged."); }
    this.dirty = true;
  },
  // ------------------------------------------------------------------ harbour
  canCrew() { return /deck|net|sail|fish|cook|supercargo|shipmaster/i.test(this.tv.trade) || this.tv.kind === "shipmaster"; },
  shipOffers(b) {
    const s = this.s, w = this.w, U = AZ.U, P = w.P, day = Math.floor(s.clock / 24);
    s.taken = s.taken || [];
    const rnd = U.rng(`${s.seed}:ships:${b.i}:${Math.floor(day / 3)}`);
    const out = [];
    const flagOf = st => P.states[st]?.name || "no flag";
    const mk = (dest, stops, departAt, planned, cargo) => {
      const bh = w.harbour(b, "ship");
      if (!bh) return null;
      const legs = [b, ...stops, dest];
      let miles = 0;
      for (let i = 0; i < legs.length - 1; i++) miles += Math.hypot(legs[i + 1].t[0] - legs[i].t[0], legs[i + 1].t[1] - legs[i].t[1]) * w.miles * 1.15;
      const id = `${b.i}:${dest.i}:${Math.round(departAt)}`;
      const captain = this.know.person(`cap:${id}`, b.culture);
      const ship = `the ${U.cap(w.names.get(P.cultures[b.culture].base, U.rng(`ship:${id}`), 4, 9))}`;
      if (!legs.every(x => w.harbour(x, "ship") && w.sameWater(bh.t, w.harbour(x, "ship").t, "ship"))) return null;
      return { id, planned, dest, stops, departAt, miles: Math.round(miles), fare: AZ.Prices.fare(w, b, miles), captain, ship, flag: b.state, cargo,
        why: cargo ? `${captain} carries ${cargo.toLowerCase()} for the markets of ${[...stops, dest].map(x => x.name).join(" and ")} ${AZ.T("data")}` : `${captain} has a cargo for ${dest.name}` };
    };
    const cp = this.cpHere();
    if (cp && cp.place.burg === b && cp.legOut && AZ.vesselClass(cp.legOut.transport) === "ship" && cp.legOut.place.burg) {
      const arrive = s.cpRec[cp.i]?.arrive ?? cp.parArrive;
      const departAt = arrive + (cp.parLeave - cp.parArrive);
      const o = mk(cp.legOut.place.burg, [], departAt, true, null);
      if (o && departAt > s.clock) { o.miles = Math.round(cp.legOut.miles); o.fare = AZ.Prices.fare(w, b, cp.legOut.miles); o.why = `the plan's ship: ${o.captain} sails direct ${AZ.T("data")}`; out.push(o); }
      // a slower ship to the same port, calling on the way where the trade takes it
      const dest = cp.legOut.place.burg;
      const between = P.burgs.filter(x => x && x.port && x !== b && x !== dest && w.harbour(x, "ship") && w.sameWater(w.harbour(b, "ship")?.t, w.harbour(x, "ship").t, "ship")).map(x => ({ x, off: AZ.U.clamp(this.offLine(b.t, dest.t, x.t), 0, 1e9) })).filter(o2 => o2.off < 60).sort((a2, b2) => a2.off - b2.off).slice(0, 3).map(o2 => o2.x);
      if (between.length) { const o2 = mk(dest, [rnd.pick(between)], s.clock + 30 + rnd() * 40, false, this.cargoFor(b)); if (o2) { o2.fare = AZ.U.rn(o2.fare * 0.8, 1); out.push(o2); } }
    }
    const sells = Object.keys(P.trade.sell[b.i] || {});
    const ports = P.burgs.filter(x => x && x.port && x !== b && w.harbour(x, "ship") && w.sameWater(w.harbour(b, "ship")?.t, w.harbour(x, "ship").t, "ship"));
    const buyers = ports.filter(x => sells.some(g => (P.trade.buy[x.i] || {})[g])).sort((a, c) => Math.hypot(a.t[0] - b.t[0], a.t[1] - b.t[1]) - Math.hypot(c.t[0] - b.t[0], c.t[1] - b.t[1]));
    for (const dest of [...buyers.slice(0, 2), ...ports.filter(x => x.capital).sort(() => rnd() - 0.5).slice(0, 1)]) {
      const g = sells.find(gg => (P.trade.buy[dest.i] || {})[gg]);
      const o = mk(dest, [], s.clock + 6 + rnd() * 60, false, g ? P.goods.find(x => x.i === +g)?.name : null);
      if (o && !out.some(x => x.dest === dest)) out.push(o);
    }
    return out.filter(o => !s.taken.includes(o.id) && o.departAt > s.clock).slice(0, 5);
  },
  offLine(a, b, p) { // distance (tiles) from p to segment ab, infinite beyond the ends
    const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
    const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (L || 1);
    if (t < 0.1 || t > 0.9) return 1e9;
    return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
  },
  cargoFor(b) { const g = Object.keys(this.w.P.trade.sell[b.i] || {})[0]; return g ? this.w.P.goods.find(x => x.i === +g)?.name : null; },
  async harbour(b) {
    const s = this.s, w = this.w, U = AZ.U, P = AZ.Prices;
    if (s.vessel && s.vessel.crew && this.vesselHere(b) && this.doAct("book")) this.ui.toast(`<span class="hook">★ Your ${U.esc(s.vessel.kind.toLowerCase())} and crew are ready: passage arranged.</span>`, "gold");
    for (;;) {
      const offers = this.shipOffers(b);
      const opts = [];
      for (const o of offers) {
        const crew = this.canCrew();
        opts.push({ label: `${o.planned ? "★ " : ""}${U.esc(o.ship)} (${U.esc(w.P.states[o.flag]?.name || "")}) to ${U.esc(o.dest.name)}${o.stops.length ? ` via ${o.stops.map(x => U.esc(x.name)).join(", ")}` : ", direct"} · sails ${AZ.Clock.fmt(o.departAt)} (in ${AZ.Clock.span(o.departAt - s.clock)}) · fare 🟡 ${o.fare}`, cls: o.planned ? "hook" : "", act: "book", o, disabled: s.purse < o.fare || !!s.voyage });
        if (crew) opts.push({ label: `   … or sign on as crew aboard ${U.esc(o.ship)} (no fare; work the passage)`, act: "crew", o, disabled: !!s.voyage });
      }
      const boatH = w.harbour(b, "boat");
      if (boatH && !s.vessel) {
        const crew = 3, day = U.rn(crew * (P.wage(w, b) + P.ration(w, b)) + P.hire(w, b), 2);
        opts.push({ label: `Hire a sailing boat with a crew of ${crew}: 🟡 ${U.rn(P.hire(w, b) + crew * P.wage(w, b), 2)} a day in wages and hire, three days paid now; you feed the crew (about 🟡 ${day} a day in all)`, act: "hire", disabled: s.purse < 3 * (P.hire(w, b) + crew * P.wage(w, b)) });
      }
      if (s.vessel && s.vessel.mode === "owned" && !s.vessel.crew) opts.push({ label: `Hire a crew of 3 for your boat (🟡 ${U.rn(3 * P.wage(w, b) * 3, 2)} for three days)`, act: "crewup", disabled: s.purse < 3 * P.wage(w, b) * 3 });
      if (s.vessel && s.vessel.mode === "hired" && this.vesselHere(b)) opts.push({ label: `Pay off the crew and return the boat${s.vessel.owed ? ` (owed 🟡 ${s.vessel.owed})` : ""}`, act: "payoff" });
      if (!opts.length) opts.push({ label: "No ships are taking passengers this week", act: "none", disabled: true });
      opts.push({ label: "Back", act: "back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)} harbour</b> · 🟡 ${U.rn(s.purse, 1)}${this.voyageLine()}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.act === "back" || o.act === "none") return;
      if (o.act === "book" || o.act === "crew") {
        const crew = o.act === "crew";
        if (!crew) s.purse = U.rn(s.purse - o.o.fare, 2);
        s.taken.push(o.o.id);
        const h = w.harbour(b, "ship").t;
        s.voyage = { ship: o.o.ship, captain: o.o.captain, flag: o.o.flag, role: crew ? "crew" : "passenger", fare: crew ? 0 : o.o.fare, cls: "ship", speed: 10, hpd: 24,
          stops: [...o.o.stops, o.o.dest].map((x, i, a) => ({ b: x.i, name: x.name, stay: i === a.length - 1 ? 0 : 8 + Math.round(AZ.U.rnd2(x.i, b.i, 3) * 16) })),
          leg: 0, state: "port", at: h, portBurg: b.i, departAt: o.o.departAt, planned: o.o.planned, from: b.i, why: o.o.why, course: null, pos: 0 };
        this.doAct("book");
        this.log(`${crew ? "Signed on" : "Booked passage"} aboard ${U.esc(o.o.ship)} to ${U.esc(o.o.dest.name)}, sailing ${AZ.Clock.fmt(o.o.departAt)}.`, "hook");
        await this.ui.say([`${crew ? "You sign the ship's articles" : `🟡 ${o.o.fare} buys a berth`} aboard ${U.esc(o.o.ship)}, ${U.esc(o.o.captain)} master. ${U.cap(o.o.why)}.`,
          `She sails <b>${AZ.Clock.fmt(o.o.departAt)}</b>, in ${AZ.Clock.span(o.o.departAt - s.clock)}, and will not wait. Bring your own food: you have ${s.sup.food} days' worth. Board from town (Space) before she sails.`]);
        return;
      }
      if (o.act === "hire") {
        const crew = 3, h = boatH.t;
        const first = U.rn(3 * (P.hire(w, b) + crew * P.wage(w, b)), 2);
        s.purse = U.rn(s.purse - first, 2);
        s.vessel = { mode: "hired", kind: "Sailing boat", cls: "boat", speed: 6, hpd: 12, crew, morale: 70, c: h[0], r: h[1], wage: P.wage(w, b), hire: P.hire(w, b), home: b.i, prepaid: 2 };
        this.doAct("book");
        this.log(`Hired a sailing boat in ${U.esc(b.name)}.`, "hook");
        await this.ui.say([`The boat is yours to command, with ${crew} hands: a mate, a deckhand and a boy ${AZ.T("new")}. You pay 🟡 ${first} now; after that, wages and hire come due each dawn.`,
          `They expect to sail from dawn for twelve hours and anchor at night, as boats do ${AZ.T("data")}. Feed them: they eat from your stores. Buy food at the market before you sail; fishing helps.`, `Board from town (Space), then steer or press F.`]);
        continue;
      }
      if (o.act === "crewup") { const cost = U.rn(3 * P.wage(w, b) * 3, 2); s.purse = U.rn(s.purse - cost, 2); s.vessel.crew = 3; s.vessel.morale = 70; this.ui.toast("Three hands sign on."); continue; }
      if (o.act === "payoff") {
        const owed = s.vessel.owed || 0;
        s.purse = U.rn(Math.max(0, s.purse - owed), 2);
        this.log(`Returned the hired boat in ${U.esc(b.name)}.`);
        s.vessel = null; s.aboard = false; s.c = b.t[0]; s.r = b.t[1];
        this.ui.toast("The crew is paid off and the boat returned."); this.dirty = true; return;
      }
    }
  },
  vesselHere(b) { const v = this.s.vessel; if (!v) return false; return ["boat", "ship"].some(cls => { const h = this.w.harbour(b, cls); return h && h.t[0] === v.c && h.t[1] === v.r; }); },
  boardOptions(b) {
    const s = this.s, U = AZ.U, opts = [];
    const v = s.voyage;
    if (v && v.state === "port" && v.portBurg === b.i) {
      if (!this.riding()) opts.push({ label: `Board ${U.esc(v.ship)} (sails ${AZ.Clock.fmt(v.departAt)}, in ${AZ.Clock.span(v.departAt - s.clock)})`, cls: "hook", act: { go: async () => { s.aboard = true; v.boarded = true; s.c = v.at[0]; s.r = v.at[1]; this.ui.toast(`Aboard ${U.esc(v.ship)}.`); this.afterStep(); } } });
      opts.push({ label: `Wait aboard until ${U.esc(v.ship)} sails (${AZ.Clock.span(v.departAt - s.clock)})`, act: { go: async () => { s.aboard = true; v.boarded = true; s.c = v.at[0]; s.r = v.at[1]; s.clock = v.departAt; this.afterStep(); } } });
      if (this.riding()) opts.push({ label: "Go ashore and walk (mind the sailing time)", act: { go: async () => { s.aboard = false; v.boarded = false; s.c = b.t[0]; s.r = b.t[1]; this.afterStep(); } } });
    }
    if (s.vessel && this.vesselHere(b)) {
      if (!s.aboard || this.riding()) opts.push({ label: `Board your ${U.esc(s.vessel.kind.toLowerCase())}${s.vessel.crew ? "" : " (no crew!)"}`, act: { go: async () => { if (s.voyage) s.voyage.boarded = false; s.aboard = true; s.c = s.vessel.c; s.r = s.vessel.r; this.afterStep(); } } });
      else opts.push({ label: `Go ashore and walk (the ${U.esc(s.vessel.kind.toLowerCase())} waits in harbour)`, act: { go: async () => { s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; this.afterStep(); } } });
    }
    return opts;
  },
  shipWarn() { const v = this.s.voyage; return v && v.state === "port" && v.departAt < AZ.Clock.nextDawn(this.s.clock, this.lat()) ? " — the ship sails before morning!" : ""; },
  voyageLine() { const v = this.s.voyage; return v && v.state === "port" ? ` · <span class="hook">${AZ.U.esc(v.ship)} sails ${AZ.Clock.fmt(v.departAt)} (in ${AZ.Clock.span(v.departAt - this.s.clock)})</span>` : ""; },
  // ------------------------------------------------------------------ voyages
  depart() {
    const s = this.s, v = s.voyage, U = AZ.U, w = this.w;
    if (!this.riding()) {
      this.log(`Missed ${U.esc(v.ship)}: she sailed ${AZ.Clock.fmt(v.departAt)} without you.`, "hook");
      s.voyage = null; this.dirty = true;
      return this.ui.say(`<b class="hook">${U.esc(v.ship)} has sailed without you.</b> The fare is gone. Book another ship at the harbour.`);
    }
    const stop = v.stops[v.leg], tb = w.P.burgs[stop.b], th = w.harbour(tb, "ship");
    let course = null;
    const plan = v.planned && this.jr && this.jr.segs.find(sg => sg.moving && sg.fromHarbour && sg.fromHarbour[0] === v.at[0] && sg.fromHarbour[1] === v.at[1] && sg.place.burg === tb);
    if (plan) { course = plan.chain; v.milesPerStep = plan.miles / Math.max(1, plan.chain.length - 1); }
    else { course = th ? w.waterPath(v.at, th.t, "ship") : null; v.milesPerStep = course ? course.mps : w.miles; }
    if (!course) {
      const port = w.P.burgs[v.portBurg];
      this.log(`${U.esc(v.ship)} could not find a way to ${U.esc(tb.name)}.`);
      s.voyage = null; s.aboard = false; s.purse = U.rn(s.purse + (v.leg === 0 ? v.fare : 0), 2);
      if (port) { s.c = port.t[0]; s.r = port.t[1]; }
      this.anim = null; this.afterStep();
      return this.ui.say(`The captain will not risk it: there is no way by sea to ${U.esc(tb.name)} from here. The voyage is off${v.leg === 0 ? " and your fare is returned" : ""}; you are put ashore.`);
    }
    v.course = course; v.pos = 0; v.state = "sea"; v.to = th.t;
    s.c = course[0][0]; s.r = course[0][1];
    this.log(`${U.esc(v.ship)} cast off for ${U.esc(tb.name)}.`);
    this.ui.toast(`${U.esc(v.ship)} casts off for ${U.esc(tb.name)}. You are a passenger: Space for the ship, F for faster days, P to pause.`);
    this.dirty = true;
  },
  voyageStep() {
    const s = this.s, v = s.voyage, U = AZ.U, w = this.w;
    const next = v.course[v.pos + 1];
    if (!next) return this.dock();
    const dc = next[0] - s.c, dr = next[1] - s.r;
    s.dir = dc < 0 ? "left" : dc > 0 ? "right" : s.dir;
    const hours = this.stepHours(next[0], next[1], dc, dr);
    this.anim = { from: [s.c, s.r], to: [next[0], next[1]], t0: performance.now(), dur: this.fast ? 22 : 70 };
    s.c = next[0]; s.r = next[1]; s.clock += hours; v.pos++;
    this.afterStep();
    void U; void w;
  },
  async dock() {
    const s = this.s, v = s.voyage, U = AZ.U, w = this.w;
    const stop = v.stops[v.leg], b = w.P.burgs[stop.b];
    v.state = "port"; v.at = [s.c, s.r]; v.portBurg = b.i; v.course = null;
    if (this._toPort) { this._toPort = false; this.fast = false; }
    v.leg++;
    this.log(`${U.esc(v.ship)} docked at ${U.esc(b.name)}.`);
    if (v.leg >= v.stops.length) {
      s.voyage = null; s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; this.anim = null;
      if (v.role === "crew" && v.earned) { s.purse = U.rn(s.purse + v.earned, 2); }
      await this.ui.say(`<b>${U.esc(v.ship)}</b> makes fast in ${U.esc(b.name)}. You go ashore${v.role === "crew" ? ` with your pay, 🟡 ${v.earned || 0}` : ""}.`);
      this.afterStep();
      return;
    }
    v.departAt = s.clock + stop.stay;
    await this.ui.say(`<b>${U.esc(v.ship)}</b> calls at ${U.esc(b.name)} and sails again <b>${AZ.Clock.fmt(v.departAt)}</b>, in ${stop.stay} hours. Go ashore if you like (Space), but be back aboard in time.`);
    this.afterStep();
  },
  async shipTalk() {
    const s = this.s, v = s.voyage, U = AZ.U, w = this.w;
    const next = v.stops[v.leg], atSea = v.state === "sea";
    const opts = [{ id: "cap", label: "Talk to the captain" }, { id: "pax", label: "Talk to the other passengers" }];
    if (atSea) opts.push({ id: 3, label: "Rest 3 hours (the ship sails on)" }, { id: 6, label: "Rest 6 hours" }, { id: "dawn", label: "Sleep until dawn" },
      { id: "watch", label: `Watch from the deck (normal pace)${!s.voyPause && !this.fast ? " ✓" : ""}` }, { id: "fast", label: `Let the days pass quickly${this.fast && !s.voyPause ? " ✓" : ""}` },
      { id: "pause", label: `Hold here and look around (time stops until you act)${s.voyPause ? " ✓" : ""}` }, { id: "port", label: "Let the days pass until the next port" });
    else opts.push({ id: "wait", label: "Wait aboard until she sails" });
    opts.push({ id: "back", label: "Back" });
    const k = await this.ui.choose(`Aboard <b>${U.esc(v.ship)}</b>, ${U.esc(v.captain)} master · bound for ${U.esc(next ? next.name : "?")} · ${v.role} · ${AZ.Clock.fmt(s.clock)}`, opts, { cancel: opts.length - 1 });
    const o = opts[k];
    if (o.id === "cap") {
      const sh = w.P.states[v.flag];
      return this.ui.say([`${U.esc(v.captain)} sails under the flag of ${U.esc(sh?.fullName || "no state")} ${AZ.T("data")}. ${U.cap(v.why)}.`,
        `Itinerary: ${v.stops.map((x, i) => `${i < v.leg ? "<s>" : ""}${U.esc(x.name)}${x.stay ? ` (${x.stay} h in port)` : ""}${i < v.leg ? "</s>" : ""}`).join(" → ")} ${AZ.T("mixed")}.`]);
    }
    if (o.id === "pax") { const rm = this.know.rumour(s.c, s.r, U.rng(`${s.seed}:pax:${Math.floor(s.clock / 24)}`), this); s.clock += 1; this.advanceVoyage(0); return this.ui.say(rm ? `A fellow passenger: “${rm}` : "They are seasick and say nothing."); }
    if (o.id === "wait") { s.clock = v.departAt; this.dirty = true; return; }
    if (o.id === 3 || o.id === 6) { this.advanceVoyage(o.id); this.slept(); return; }
    if (o.id === "dawn") { this.advanceVoyage(Math.max(1, AZ.Clock.nextDawn(s.clock, this.lat()) - s.clock)); this.slept(); return; }
    if (o.id === "watch") { s.voyPause = false; this.fast = false; }
    if (o.id === "fast") { s.voyPause = false; this.fast = true; }
    if (o.id === "pause") { s.voyPause = true; this.ui.toast("Holding. The ship moves only while time passes: rest, talk, or press F."); }
    if (o.id === "port") { s.voyPause = false; this.fast = true; this._toPort = true; }
    this.dirty = true;
  },
  // let a number of hours pass aboard: the ship sails on without drawing every step
  advanceVoyage(hours) {
    const s = this.s, v = s.voyage;
    if (!v || v.state !== "sea") return;
    const until = s.clock + hours;
    let guard = 0;
    while (s.voyage === v && v.state === "sea" && guard++ < 5000) {
      if (!v.course[v.pos + 1]) { this.dock(); break; }
      if (s.clock >= until && hours > 0) break;
      this.anim = null; this.voyageStep(); this.anim = null;
      if (this.ui.busy()) break;
      if (hours === 0) break;
    }
    this.dirty = true;
  },
  async market(b) {
    const s = this.s, w = this.w, U = AZ.U, P = AZ.Prices;
    for (;;) {
      const ration = P.ration(w, b), cap = this.capacity(), eat = this.eaters();
      const opts = [];
      for (const n of [1, 5, 10, 20, 40]) opts.push({ label: `Food for ${n} day${n > 1 ? "s" : ""}${eat > 1 ? ` for ${eat} people (${n * eat} rations)` : ""}: 🟡 ${U.rn(n * eat * ration, 2)}`, n, kind: "food", disabled: s.purse < n * eat * ration || s.sup.food + n * eat > cap.food });
      opts.push({ label: `Trade goods (you carry ${this.goodsCount()} of ${cap.goods} units)`, kind: "goods" });
      opts.push({ label: "Back", kind: "back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)} market</b> · 🟡 ${U.rn(s.purse, 2)} · food ${s.sup.food} rations · food here: ${U.esc(this.cheapFood(b))} ${AZ.T("data")}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.kind === "back") return;
      if (o.kind === "goods") { await this.tradeGoods(b); continue; }
      if (o.kind === "food") { s.purse = U.rn(s.purse - o.n * eat * ration, 2); s.sup.food += o.n * eat; s.hunger = 0; delete s.cond.hungry; delete s.cond.starving; }
      this.dirty = true;
    }
  },
  // ------------------------------------------------------------------ trading goods between markets
  goodsCount() { return Object.values(this.s.goods || {}).reduce((a, n) => a + n, 0); },
  mkRec(mk, gid) { const s = this.s; s.mk = s.mk || {}; const m = s.mk[mk.i] = s.mk[mk.i] || {}; return (m[gid] = m[gid] || { f: 1, taken: 0 }); },
  goodQuote(b, gid) {
    const w = this.w, mk = AZ.Prices.market(w, b);
    if (!mk || !mk.goods[gid]) return null;
    const [stock, price] = mk.goods[gid], rec = this.mkRec(mk, gid), tax = AZ.Prices.tax(w, b);
    const p = price * rec.f;
    const makes = (b.production || {})[gid] > 0 || mk.centerBurgId === b.i;
    return { buy: AZ.U.rn(p * (1 + tax), 2), sell: AZ.U.rn(p * 0.85, 2), stock: Math.max(0, Math.floor(stock - rec.taken)), canBuy: makes && stock - rec.taken >= 1, mk, rec };
  },
  async tradeGoods(b) {
    const s = this.s, w = this.w, U = AZ.U;
    s.goods = s.goods || {}; s.basis = s.basis || {};
    for (;;) {
      const cap = this.capacity().goods, opts = [];
      const held = Object.entries(s.goods).filter(([, n]) => n > 0);
      for (const [gid, n] of held) {
        const q = this.goodQuote(b, gid), g = this.know.good(gid);
        opts.push(q ? { label: `Sell 1 ${U.esc(g.toLowerCase())} for 🟡 ${q.sell} (you have ${n}; paid ${U.rn(s.basis[gid] || 0, 2)} each)`, gid, kind: "sell", q } : { label: `${U.esc(g)}: nobody here buys it (you have ${n})`, disabled: true });
      }
      const mk = AZ.Prices.market(w, b);
      const here = mk ? Object.keys(mk.goods).map(gid => [gid, this.goodQuote(b, gid)]).filter(([, q]) => q && q.canBuy).sort((a, c) => c[1].stock - a[1].stock).slice(0, 10) : [];
      for (const [gid, q] of here) opts.push({ label: `Buy 1 ${U.esc(this.know.good(gid).toLowerCase())} for 🟡 ${q.buy} (${q.stock} in stock)`, gid, kind: "buy", q, disabled: s.purse < q.buy || this.goodsCount() >= cap });
      if (!here.length) opts.push({ label: `${U.esc(b.name)} makes nothing for sale on its market`, disabled: true });
      opts.push({ label: "Back", kind: "back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)}: goods</b> · 🟡 ${U.rn(s.purse, 2)} · carrying ${this.goodsCount()}/${cap} units · prices from the ${U.esc(w.P.burgs[mk?.centerBurgId]?.name || "")} market, with ${Math.round(AZ.Prices.tax(w, b) * 100)}% sales tax; merchants buy at 85% ${AZ.T("data")}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (!o || o.kind === "back") return;
      if (o.kind === "buy") {
        const n0 = s.goods[o.gid] || 0;
        s.basis[o.gid] = U.rn(((s.basis[o.gid] || 0) * n0 + o.q.buy) / (n0 + 1), 2);
        s.goods[o.gid] = n0 + 1; s.purse = U.rn(s.purse - o.q.buy, 2); o.q.rec.f *= 1.04; o.q.rec.taken += 1;
      } else if (o.kind === "sell") {
        s.goods[o.gid]--; s.purse = U.rn(s.purse + o.q.sell, 2); o.q.rec.f *= 0.96;
        const profit = U.rn(o.q.sell - (s.basis[o.gid] || 0), 2);
        this.log(`Sold ${U.esc(this.know.good(o.gid).toLowerCase())} in ${U.esc(b.name)} for 🟡 ${o.q.sell} (${profit >= 0 ? "+" : ""}${profit}).`);
      }
      this.dirty = true;
    }
  },
  cheapFood(b) {
    const w = this.w, mk = AZ.Prices.market(w, b);
    if (!mk) return "no market";
    const f = w.P.goods.filter(g => (g.tags || []).includes("food") && mk.goods[g.i]).sort((a, c) => mk.goods[a.i][1] - mk.goods[c.i][1])[0];
    return f ? `${f.name.toLowerCase()} at ${mk.goods[f.i][1]} a unit, ${Math.round((this.w.P.states[b.state]?.salesTax || 0) * 100)}% tax` : "no food on the market";
  },
});
