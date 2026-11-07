// ---------------------------------------------------------------------------------------------
// What you carry, how tired you are, who travels with you, and how hard the ground is.
//   Carrying limits follow the way you travel: leaving a ship or a boat, you keep only what you
//   can carry; in a town the surplus is sold at the market, elsewhere it is left behind.
//   The journal lists everything you carry. Exhaustion and falling asleep are announced.
//   The company rests, camps and crosses portals with you. The Effort lens shows how hard each
//   tile is to cross on foot, and steep ground is drawn more clearly.
// ---------------------------------------------------------------------------------------------
(() => {
  const U = AZ.U, T = AZ.T, G = AZ.Game.prototype;

  // ------------------------------------------------------------------ carrying limits
  G.enforceCapacity = function () {
    const s = this.s, w = this.w;
    if (!s || this.ui.busy()) return;
    const cap = this.capacity(), b = w.burgAt.get(w.idx(s.c, s.r));
    const extraFood = s.sup.food - cap.food, goods = Object.entries(s.goods || {}).filter(([, n]) => n > 0);
    let extraGoods = this.goodsCount() - cap.goods;
    if (extraFood <= 0 && extraGoods <= 0) return;
    const L = [];
    if (extraFood > 0) {
      s.sup.food = cap.food;
      if (b) { const got = U.rn(extraFood * AZ.Prices.ration(w, b) * 0.5, 2); s.purse = U.rn(s.purse + got, 2); L.push(`${extraFood} rations sold at the market for 🟡 ${got}`); }
      else L.push(`${extraFood} rations left behind`);
    }
    for (const [gid, n] of goods.sort((a, c) => (AZ.Prices.goodPrice(w, b, a[0]) || 0) - (AZ.Prices.goodPrice(w, b, c[0]) || 0))) {
      if (extraGoods <= 0) break;
      const k = Math.min(n, extraGoods), q = b && this.goodQuote ? this.goodQuote(b, gid) : null;
      s.goods[gid] -= k; extraGoods -= k;
      if (q) { s.purse = U.rn(s.purse + q.sell * k, 2); L.push(`${k} ${this.know.good(gid).toLowerCase()} sold for 🟡 ${U.rn(q.sell * k, 2)}`); }
      else L.push(`${k} ${this.know.good(gid).toLowerCase()} left behind`);
    }
    this.log(`More than you can carry: ${L.join("; ")}.`);
    this.ui.say(`<b>More than you can carry.</b> On ${s.aboard ? "this vessel" : "foot"} you can take ${cap.food} rations and ${cap.goods} units of goods: ${L.join("; ")} ${T("mixed")}.`);
  };
  const after0 = G.afterStep;
  G.afterStep = function (...a) { after0.apply(this, a); this.enforceCapacity(); };

  // ------------------------------------------------------------------ what you carry (journal)
  G.carryHtml = function () {
    const s = this.s, tv = this.tv, U2 = U, items = [];
    items.push(`🟡 ${U2.rn(s.purse, 2)}`, `${s.sup.food} rations (you can carry ${this.capacity().food})`);
    const goods = Object.entries(s.goods || {}).filter(([, n]) => n > 0).map(([g, n]) => `${n} ${U2.esc(this.know.good(g).toLowerCase())} (paid 🟡 ${U2.rn((s.basis || {})[g] || 0, 2)} each)`);
    items.push(goods.length ? `Goods: ${goods.join(", ")} (${this.goodsCount()} of ${this.capacity().goods} units)` : `Goods: none (room for ${this.capacity().goods} units)`);
    items.push(U2.cap(U2.esc(tv.token)));
    const f = s.flags || {};
    if (f.relic) items.push("A relic in rotten cloth, for a temple of your faith");
    if (f.inscription) items.push("A copy of an inscription no one has read");
    if (f.flask) items.push("A flask of water from a healing spring");
    for (const th of s.threads.filter(t => !t.done)) {
      const st = th.steps[th.phase];
      if (/letter|message|dispatch|offering|consignment|papers|report|proof/i.test(st.text)) items.push(`For “${U2.esc(th.title)}”: ${U2.esc(st.text.toLowerCase())}`);
    }
    if (s.vessel) items.push(`${U2.esc(s.vessel.kind)} (${s.vessel.mode}) ${s.aboard ? "under you" : "waiting where you left it"}`);
    if (s.voyage) items.push(`A ${s.voyage.mode === "land" ? "seat" : "berth"} on ${U2.esc(s.voyage.ship)}`);
    return `<ul class="carry">${items.map(i => `<li>${i}</li>`).join("")}</ul>`;
  };
  const journal0 = G.journal;
  G.journal = function () {
    journal0.call(this);
    const sheet = this.ui.el.modal.querySelector(".sheet");
    if (!sheet) return;
    const h = document.createElement("div");
    h.innerHTML = `<h3>What you carry</h3>${this.carryHtml()}`;
    const first = sheet.querySelector("h3");
    if (first) sheet.insertBefore(h, first); else sheet.appendChild(h);
  };

  // ------------------------------------------------------------------ exhaustion is an event
  const awake0 = G.awakeTick;
  G.awakeTick = function (h) {
    const s = this.s, wasEx = !!s.cond.exhausted, before = s.awake || 0;
    awake0.call(this, h);
    if (!wasEx && s.cond.exhausted && !this.ui.busy()) this.ui.say(`<b class="late">Exhausted.</b> You have been awake ${Math.round(s.awake)} hours. Everything takes longer (×1.4), and at 44 hours you will fall asleep wherever you are. Camp, take a room, or rest six hours (R).`);
    if (before + h >= 44 && (s.awake || 0) === 0 && !this.ui.busy()) this.ui.say(`<b class="late">You fell asleep where you stood</b> and woke ten hours later${s.vessel && s.aboard && s.vessel.crew ? "; the crew kept the watch, and did not like it" : ""}.`);
  };

  // ------------------------------------------------------------------ the company
  const partyLine = g => (g.s.party && g.s.party.length && !g.s.partyAway ? `${g.s.party.map(p => U.esc(p.name)).join(", ")} ` : "");
  const camp0 = G.campNight;
  G.campNight = async function () {
    const s = this.s, say0 = this.ui.say.bind(this.ui), who = partyLine(this);
    if (who) this.ui.say = (p, w2) => say0(String(p).replace(/^You camp in/, `You and the company (${who.trim()}) camp in`), w2);
    try { return await camp0.call(this); } finally { this.ui.say = say0; }
  };
  const portal0 = AZ.MARKERS.portals.run;
  AZ.MARKERS.portals.run = async (ev, m, head) => {
    const g = ev.g, s = g.s, before = [s.c, s.r], t0 = s.clock;
    await portal0(ev, m, head);
    if (!s.party || !s.party.length || (s.c === before[0] && s.r === before[1])) return;
    const remote = !g.w.near(s.c, s.r, 25).some(n => n.kind === "burg"), lostDays = s.clock - t0 > 24;
    if (remote || lostDays) {
      const meet = g.w.P.markers.find(x => x.type === "portals" && x.i !== m.i && Math.hypot(x.t[0] - s.c, x.t[1] - s.r) > 2) || m;
      s.partyAway = { t: meet.t, name: meet.name };
      g.log(`The crossing split the company; they will wait at the ${U.esc(meet.name)}.`, "hook");
      await g.ui.say(`The company is not with you. The crossing split you; they will make for the ${U.esc(meet.name)} and wait there ${T("mixed")}. Until you find them, you travel alone.`);
    }
  };
  const after1 = G.afterStep;
  G.afterStep = function (...a) {
    after1.apply(this, a);
    const s = this.s;
    if (s && s.partyAway && Math.hypot(s.partyAway.t[0] - s.c, s.partyAway.t[1] - s.r) <= 2) { const n = s.partyAway.name; s.partyAway = null; this.log("The company is together again.", "hook"); this.ui.say(`At the ${U.esc(n)} the company is waiting for you. Together again.`); }
  };
  const advice0 = G.advice;
  G.advice = async function () { if (this.s.partyAway) return this.ui.say(`You are alone: the company waits at the ${U.esc(this.s.partyAway.name)}, ${this.know.dirDist(this.s.c, this.s.r, this.s.partyAway.t).txt}.`); return advice0.call(this); };
  const interact1 = G.interact;
  G.interact = async function () {
    const s = this.s;
    if (s.partyAway && s.party?.length) { const keep = s.party; s.party = []; try { return await interact1.call(this); } finally { s.party = keep; } }
    return interact1.call(this);
  };

  // ------------------------------------------------------------------ the Effort lens: how hard each tile is on foot
  const effort = (w, c, r) => {
    if (!w.isLand(c, r)) return null;
    const B = w.bits(c, r), b = w.P.biomes[w.C.biome[w.cell(c, r)]];
    let f = B.road ? 0.8 : B.trail ? 1 : U.clamp((b.cost || 50) / 50, 1, 4);
    const rel = w.reliefAt(c, r);
    if (rel && !B.road) f *= /mount/i.test(rel.icon) ? 1.6 : 1.2;
    return f;
  };
  AZ.LENSES.splice(3, 0, { id: "effort", name: "Effort on foot", tile: true,
    color: (w, cell, c, r) => { const f = effort(w, c, r); return f == null ? null : U.ramp([[0.8, [70, 170, 90]], [1.2, [200, 210, 90]], [2, [230, 150, 60]], [3.5, [190, 60, 50]], [6.4, [110, 30, 60]]], f); },
    label: (w, cell, c, r) => { const f = effort(w, c, r); return f == null ? "water" : `${U.rn(f, 1)}× the time of open grassland${w.reliefAt(c, r) ? " · " + w.reliefAt(c, r).rule.toLowerCase() : ""}${w.bits(c, r).road ? " · road" : ""}`; } });
})();
