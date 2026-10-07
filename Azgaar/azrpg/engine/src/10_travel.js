// ---------------------------------------------------------------------------------------------
// Travel, supplies and money.
//   Booked ship: a captain with his own itinerary (a cargo to land, ports to call at); a fixed
//   departure; the passenger cannot steer and the ship does not wait.
//   Hired or owned boat: the traveller steers; the crew eats from the traveller's stores, draws
//   daily wages, calls for anchor at dusk and for shelter in storms, and can be overruled at a
//   cost to morale. Low morale ends in mutiny.
//   Days: everyone eats once a day; water runs out faster than food. Hunger and thirst slow you;
//   in the end you collapse and wake somewhere else, poorer and later.
// ---------------------------------------------------------------------------------------------
Object.assign(AZ.COND, {
  hungry: { on: "you are hungry", off: "you have eaten", slow: 1.2, label: "hungry" },
  starving: { on: "you are starving", off: "you have eaten", slow: 1.5, label: "starving" },
  thirsty: { on: "you are thirsty", off: "you have drunk", slow: 1.4, label: "thirsty" },
});

Object.assign(AZ.Game.prototype, {
  eaters() { const v = this.s.vessel; return 1 + (v && v.crew && (v.mode === "hired" || v.mode === "owned") && !this.s.voyage ? v.crew : 0); },
  capacity() { const s = this.s; return s.vessel && !s.voyage ? { food: 220, water: 220 } : s.voyage ? { food: 60, water: 0 } : { food: 20, water: 3 }; },
  refill() {
    const s = this.s, w = this.w;
    if (s.aboard) return;
    const c = s.c, r = s.r;
    const fresh = w.burgAt.has(w.idx(c, r)) || w.bits(c, r).river || [[0, 1], [1, 0], [0, -1], [-1, 0]].some(([a, b]) => w.inb(c + a, r + b) && w.ctype(c + a, r + b) === 2);
    if (fresh && s.sup.water < 3) { s.sup.water = 3; if (s.cond.thirsty) { delete s.cond.thirsty; s.thirst = 0; } }
  },
  // ------------------------------------------------------------------ time-driven events
  tick() {
    const s = this.s, w = this.w, U = AZ.U;
    if (!s || this.ui.busy()) return;
    const day = Math.floor(s.clock / 24);
    if (day > s.lastDay) {
      const n = Math.min(day - s.lastDay, 60); s.lastDay = day;
      for (let i = 0; i < n; i++) if (this.newDay()) return;
      if (s.voyage && s.aboard && s.voyage.state === "sea" && this.shipEvent && U.rnd2(day, s.seed % 100003, 41) < AZ.SHIP_EVENTS.rate) return this.shipEvent();
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
    if (v && s.aboard && !s.voyage && v.crew && !this.harbourAt.has(w.idx(s.c, s.r)) && !w.isLand(s.c, s.r)) {
      const sun = AZ.Clock.sun(s.clock, this.lat()), key = Math.floor((s.clock + 12) / 24);
      if (sun.dl < 24 && (sun.hour >= sun.set + 0.75 || sun.hour < sun.rise) && v.nightKey !== key) { v.nightKey = key; return this.crewCall(); }
    }
    void U;
  },
  newDay() {
    const s = this.s, U = AZ.U, v = s.vessel;
    const eat = this.eaters();
    s.sup.food -= eat;
    if (!(s.voyage && s.aboard)) s.sup.water -= s.aboard && v ? eat : 1;
    if (s.voyage && s.aboard && s.voyage.role === "crew") s.sup.food += eat; // crew eat the ship's food
    if (s.sup.food < 0) { s.sup.food = 0; s.hunger++; if (v && v.crew) v.morale -= 15; } else s.hunger = 0;
    if (s.sup.water < 0) { s.sup.water = 0; s.thirst++; } else if (s.sup.water > 0) s.thirst = 0;
    delete s.cond.hungry; delete s.cond.starving;
    if (s.hunger >= 3) s.cond.starving = true; else if (s.hunger >= 1) s.cond.hungry = true;
    if (s.thirst >= 1) s.cond.thirsty = true; else delete s.cond.thirsty;
    if (v && v.crew && (v.mode === "hired" || v.mode === "owned")) {
      const due = U.rn(v.crew * v.wage + (v.hire || 0), 2);
      if (s.purse >= due) { s.purse = U.rn(s.purse - due, 2); v.morale = Math.min(100, v.morale + 1); }
      else { v.morale -= 20; v.owed = U.rn((v.owed || 0) + due, 2); this.ui.toast(`You cannot pay the crew (🟡 ${due} due). They mutter.`); this.log(`Wages unpaid (🟡 ${due}).`); }
    }
    if (s.voyage && s.voyage.role === "crew") s.voyage.earned = U.rn((s.voyage.earned || 0) + AZ.Prices.wage(this.w, null), 2);
    const left = Math.min(s.sup.food / eat, s.aboard && v && !s.voyage ? s.sup.water / eat : 99);
    if (left < 3 && left > 0) { const p = this.nearestPort(v?.cls); this.ui.toast(`Stores low: about ${Math.floor(left)} day${left >= 2 ? "s" : ""} left${p ? `. Nearest harbour: ${U.esc(p.name)}, ${this.know.dirDist(s.c, s.r, p.t).txt}` : ""}.`); }
    if (s.hunger === 1) this.ui.toast("Your food is gone. Buy more at a market.");
    if (s.thirst === 1) this.ui.toast("Your water is gone. Find a river, a lake or a town.");
    if (v && v.crew && v.morale < 20 && s.aboard) { this.mutiny(); return true; }
    if (s.thirst >= 3 || s.hunger >= 7) { this.collapse(); return true; }
    this.dirty = true;
    return false;
  },
  nearestPort(cls) {
    const s = this.s, w = this.w;
    let best = null, bd = 1e9;
    for (const b of w.P.burgs) if (b && b.port) { const h = w.harbour(b, cls || "boat"); if (!h) continue; const d = Math.hypot(h.t[0] - s.c, h.t[1] - s.r); if (d < bd) { bd = d; best = b; } }
    return best;
  },
  async collapse() {
    const s = this.s, w = this.w, U = AZ.U;
    const b = w.near(s.c, s.r, 200).find(n => n.kind === "burg")?.o || this.nearestPort("boat");
    const lost = U.rn(s.purse / 2, 1);
    s.purse = U.rn(s.purse - lost, 1); s.clock += 72; s.hunger = 0; s.thirst = 0; s.sup = { food: 1, water: 3 };
    for (const k of ["hungry", "starving", "thirsty"]) delete s.cond[k];
    s.voyage = null; s.aboard = false; s.auto = false;
    if (s.vessel && s.vessel.mode === "hired") s.vessel = null;
    s.c = b.t[0]; s.r = b.t[1]; this.anim = null;
    this.log(`Collapsed from ${s.thirst ? "thirst" : "hunger"}; woke in ${U.esc(b.name)}.`, "hook");
    await this.ui.say([`You collapse. Days later you wake in ${U.esc(b.name)}, in a stranger's bed. Someone has been paid for your keep: 🟡 ${lost} is gone from your purse ${AZ.T("mixed")}.`]);
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
    else { v.crew = 0; v.c = h.t[0]; v.r = h.t[1]; }
    await this.ui.say([`<b class="hook">Mutiny.</b> The crew has had enough: they turn the ${U.esc(v.kind.toLowerCase())} for ${U.esc(b.name)} and will not hear another word ${AZ.T("mixed")}.`,
      v.mode === "hired" ? "In harbour they walk off with the boat's owner, and your deposit goes with them. You are ashore." : "In harbour they take their wages in silence and leave. Your boat has no crew; hire one at the harbour."]);
    this.afterStep();
  },
  async crewCall() {
    const s = this.s, v = s.vessel, U = AZ.U, w = this.w;
    const port = this.nearestPort(v.cls), h = port && w.harbour(port, v.cls), mi = h ? Math.round(Math.hypot(h.t[0] - s.c, h.t[1] - s.r) * w.miles) : null;
    const nearLand = w.near(s.c, s.r, 3).length > 0 || [[0, 2], [2, 0], [0, -2], [-2, 0]].some(([a, b]) => w.isLand(s.c + a, s.r + b));
    if (v.morale < 20) { s.auto = false; return this.mutiny(); }
    const k = await this.ui.choose(`<b>The crew calls for anchor.</b> Sunset, ${AZ.Clock.fmt(s.clock)}. They have sailed their hours (${v.hpd} a day by custom ${AZ.T("data")}). Morale ${Math.round(v.morale)}.`,
      [{ label: "Anchor here until dawn" }, { label: `Sail on through the night (morale −12${nearLand ? ", and reefs near" : ""})` }, { label: port ? `Make for ${U.esc(port.name)} harbour (${U.num(mi)} mi)` : "No harbour near", disabled: !port }], { cancel: 0 });
    if (k === 0) {
      const t0 = s.clock; s.clock = AZ.Clock.nextDawn(s.clock, this.lat()); v.anchored = true; v.morale = Math.min(100, v.morale + 4);
      const act = this.doAct("anchor");
      this.ui.toast(`At anchor ${AZ.Clock.span(s.clock - t0)}. ${act ? `<span class="hook">★ ${U.esc(act.label)}</span>` : ""}`, act ? "gold" : "");
    } else if (k === 1) {
      v.morale -= 12;
      if (nearLand && AZ.U.rnd2(s.c, s.r, Math.floor(s.clock)) < 0.15) { this.events.fx({ cond: "damaged", time: 3 }, "Struck a reef at night."); this.ui.toast("In the dark you touch a reef. The hull is damaged."); }
      else this.ui.toast(`The crew sails on, sullen. Morale ${Math.round(v.morale)}.`);
    } else { s.waypoint = h.t; v.morale -= 2; this.setAuto(true); }
    this.dirty = true;
  },
  async stormCall() {
    const s = this.s, U = AZ.U, w = this.w;
    const until = (Math.floor(s.clock / 12) + 1) * 12;
    if (s.voyage) {
      const h = Math.max(2, until - s.clock);
      s.clock = until;
      this.log(`Storm: the ${U.esc(s.voyage.ship)} hove to for ${Math.round(h)} h.`);
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
      const between = P.burgs.filter(x => x && x.port && x !== b && x !== dest && w.harbour(x, "ship")).map(x => ({ x, off: AZ.U.clamp(this.offLine(b.t, dest.t, x.t), 0, 1e9) })).filter(o2 => o2.off < 60).sort((a2, b2) => a2.off - b2.off).slice(0, 3).map(o2 => o2.x);
      if (between.length) { const o2 = mk(dest, [rnd.pick(between)], s.clock + 30 + rnd() * 40, false, this.cargoFor(b)); if (o2) { o2.fare = AZ.U.rn(o2.fare * 0.8, 1); out.push(o2); } }
    }
    const sells = Object.keys(P.trade.sell[b.i] || {});
    const ports = P.burgs.filter(x => x && x.port && x !== b && w.harbour(x, "ship"));
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
          `They expect to sail from dawn for twelve hours and anchor at night, as boats do ${AZ.T("data")}. Feed them: they eat from your stores. Buy food and water casks at the market before you sail.`, `Board from town (Space), then steer or press F.`]);
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
  vesselHere(b) { const v = this.s.vessel; if (!v) return false; const h = this.w.harbour(b, v.cls); return h && h.t[0] === v.c && h.t[1] === v.r; },
  boardOptions(b) {
    const s = this.s, U = AZ.U, opts = [];
    const v = s.voyage;
    if (v && v.state === "port" && v.portBurg === b.i) {
      if (!s.aboard) opts.push({ label: `Board ${U.esc(v.ship)} (sails ${AZ.Clock.fmt(v.departAt)}, in ${AZ.Clock.span(v.departAt - s.clock)})`, cls: "hook", act: { go: async () => { s.aboard = true; s.c = v.at[0]; s.r = v.at[1]; this.ui.toast(`Aboard ${U.esc(v.ship)}.`); this.afterStep(); } } });
      opts.push({ label: `Wait aboard until ${U.esc(v.ship)} sails (${AZ.Clock.span(v.departAt - s.clock)})`, act: { go: async () => { s.aboard = true; s.c = v.at[0]; s.r = v.at[1]; s.clock = v.departAt; this.afterStep(); } } });
      if (s.aboard) opts.push({ label: "Go ashore and walk (mind the sailing time)", act: { go: async () => { s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; this.afterStep(); } } });
    }
    if (s.vessel && !s.voyage && this.vesselHere(b)) {
      if (!s.aboard) opts.push({ label: `Board your ${U.esc(s.vessel.kind.toLowerCase())}${s.vessel.crew ? "" : " (no crew!)"}`, act: { go: async () => { s.aboard = true; s.c = s.vessel.c; s.r = s.vessel.r; this.afterStep(); } } });
      else opts.push({ label: `Go ashore and walk (the ${U.esc(s.vessel.kind.toLowerCase())} waits in harbour)`, act: { go: async () => { s.aboard = false; s.c = b.t[0]; s.r = b.t[1]; this.afterStep(); } } });
    }
    return opts;
  },
  shipWarn() { const v = this.s.voyage; return v && v.state === "port" && v.departAt < AZ.Clock.nextDawn(this.s.clock, this.lat()) ? " — the ship sails before morning!" : ""; },
  voyageLine() { const v = this.s.voyage; return v && v.state === "port" ? ` · <span class="hook">${AZ.U.esc(v.ship)} sails ${AZ.Clock.fmt(v.departAt)} (in ${AZ.Clock.span(v.departAt - this.s.clock)})</span>` : ""; },
  // ------------------------------------------------------------------ voyages
  depart() {
    const s = this.s, v = s.voyage, U = AZ.U, w = this.w;
    if (!s.aboard) {
      this.log(`Missed ${U.esc(v.ship)}: she sailed ${AZ.Clock.fmt(v.departAt)} without you.`, "hook");
      s.voyage = null; this.dirty = true;
      return this.ui.say(`<b class="hook">${U.esc(v.ship)} has sailed without you.</b> The fare is gone. Book another ship at the harbour.`);
    }
    const stop = v.stops[v.leg], tb = w.P.burgs[stop.b], th = w.harbour(tb, "ship");
    let course = null;
    const plan = v.planned && this.jr && this.jr.segs.find(sg => sg.moving && sg.fromHarbour && sg.fromHarbour[0] === v.at[0] && sg.fromHarbour[1] === v.at[1] && sg.place.burg === tb);
    if (plan) { course = plan.chain; v.milesPerStep = plan.miles / Math.max(1, plan.chain.length - 1); }
    else { course = th ? w.waterPath(v.at, th.t, "ship") : null; v.milesPerStep = course ? course.mps : w.miles; }
    if (!course) { this.log(`${U.esc(v.ship)} could not find a way to ${U.esc(tb.name)}.`); s.voyage = null; return this.ui.say(`The captain will not risk it: no way by sea to ${U.esc(tb.name)}. The voyage is off; your fare is returned.`).then(() => { s.purse += v.fare; }); }
    v.course = course; v.pos = 0; v.state = "sea"; v.to = th.t;
    s.c = course[0][0]; s.r = course[0][1];
    this.log(`${U.esc(v.ship)} cast off for ${U.esc(tb.name)}.`);
    this.ui.toast(`${U.esc(v.ship)} casts off for ${U.esc(tb.name)}. You are a passenger: watch, talk (Space), or let the days pass faster (F).`);
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
    const next = v.stops[v.leg];
    const k = await this.ui.choose(`Aboard <b>${U.esc(v.ship)}</b>, ${U.esc(v.captain)} master · bound for ${U.esc(next ? next.name : "?")} · ${v.role}`,
      [{ label: "Talk to the captain" }, { label: "Talk to the other passengers" }, { label: v.state === "sea" ? "Let the days pass until the next port" : "Wait aboard until she sails" }, { label: "Back" }], { cancel: 3 });
    if (k === 0) {
      const sh = w.P.states[v.flag];
      return this.ui.say([`${U.esc(v.captain)} sails under the flag of ${U.esc(sh?.fullName || "no state")} ${AZ.T("data")}. ${U.cap(v.why)}.`,
        `Itinerary: ${v.stops.map((x, i) => `${i < v.leg ? "<s>" : ""}${U.esc(x.name)}${x.stay ? ` (${x.stay} h in port)` : ""}${i < v.leg ? "</s>" : ""}`).join(" → ")} ${AZ.T("mixed")}.`]);
    }
    if (k === 1) {
      const rnd = U.rng(`${s.seed}:pax:${Math.floor(s.clock / 24)}`);
      const rm = this.know.rumour(s.c, s.r, rnd, this);
      return this.ui.say(rm ? `A fellow passenger: “${rm}` : "They are seasick and say nothing.");
    }
    if (k === 2) {
      if (v.state === "port") { s.clock = v.departAt; this.dirty = true; return; }
      this.fast = true; this.ui.toast("Days pass quickly; any key to watch.");
    }
  },
  // ------------------------------------------------------------------ market
  async market(b) {
    const s = this.s, w = this.w, U = AZ.U, P = AZ.Prices;
    for (;;) {
      const ration = P.ration(w, b), water = P.water(w, b), cap = this.capacity(), eat = this.eaters();
      const opts = [];
      for (const n of [1, 5, 10, 20, 40]) opts.push({ label: `Food for ${n} day${n > 1 ? "s" : ""}${eat > 1 ? ` for ${eat} people (${n * eat} rations)` : ""}: 🟡 ${U.rn(n * eat * ration, 2)}`, n, kind: "food", disabled: s.purse < n * eat * ration || s.sup.food + n * eat > cap.food });
      if (s.vessel && !s.voyage) for (const n of [5, 10, 20]) opts.push({ label: `Water casks for ${n} days for ${eat} (🟡 ${U.rn(n * eat * water, 2)})`, n, kind: "water", disabled: s.purse < n * eat * water || s.sup.water + n * eat > cap.water });
      if (s.flags.cargo && this.tv.cargo != null) {
        const p = P.goodPrice(w, b, this.tv.cargo);
        if (p) opts.push({ label: `Sell your consignment of ${U.esc(this.know.good(this.tv.cargo).toLowerCase())} here for 🟡 ${U.rn(p * 4, 1)} (local price ${U.rn(p, 2)} a unit) ${AZ.T("data")}`, kind: "cargo", p });
      }
      opts.push({ label: "Back", kind: "back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)} market</b> · 🟡 ${U.rn(s.purse, 1)} · food ${s.sup.food} rations, water ${s.sup.water} · food here: ${U.esc(this.cheapFood(b))} ${AZ.T("data")}`, opts, { cancel: opts.length - 1 });
      const o = opts[k];
      if (o.kind === "back") return;
      if (o.kind === "food") { s.purse = U.rn(s.purse - o.n * eat * ration, 2); s.sup.food += o.n * eat; s.hunger = 0; delete s.cond.hungry; delete s.cond.starving; }
      if (o.kind === "water") { s.purse = U.rn(s.purse - o.n * eat * water, 2); s.sup.water += o.n * eat; s.thirst = 0; delete s.cond.thirsty; }
      if (o.kind === "cargo") { s.purse = U.rn(s.purse + o.p * 4, 2); delete s.flags.cargo; this.log(`Sold the consignment in ${U.esc(b.name)}.`); for (const th of s.threads) if (!th.done && th.steps[th.phase]?.needs === "cargo") { th.done = true; th.outcome = "sold elsewhere"; } }
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
