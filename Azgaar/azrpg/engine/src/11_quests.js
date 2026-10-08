// ---------------------------------------------------------------------------------------------
// Side stories (teal), leads, errands and the reasoning behind the route.
//   Errands are posted on town notice boards and come from the map: what a town makes and who
//   buys it (trade), towns stricken by zones (relief), the state's friends and enemies
//   (letters), its wars (dispatches), strange places nearby (investigations) and faith seats
//   (offerings). Rumours, sightings and libraries add leads you can follow.
// ---------------------------------------------------------------------------------------------
Object.assign(AZ.Game.prototype, {
  startThread(def, quiet) {
    if (!def) return;
    const s = this.s;
    if (s.threads.some(t => t.title === def.title && !t.done)) return;
    const th = { id: s.threads.length, title: def.title, steps: def.steps, phase: 0, done: false, outcome: "", deadline: def.deadline || null, giver: def.giver || null, why: def.why || "" };
    s.threads.push(th);
    this.log(`New side story: ${AZ.U.esc(th.title)}.`, "side");
    if (!quiet) this.ui.toast(`New side story: <b class="side">${AZ.U.esc(th.title)}</b>. ${AZ.U.esc(th.steps[0].text)}`, "teal");
  },
  stepTile(st) {
    const P = this.w.P, g = st.goal || {}, s = this.s;
    if (g.burg) return P.burgs[g.burg]?.t || null;
    if (g.marker != null) return P.markers.find(m => m.i === g.marker)?.t || null;
    if (g.unit) { const [st0, i] = g.unit.split(":").map(Number); return P.military.find(u => u.state === st0 && u.i === i)?.t || null; }
    if (g.temple != null) {
      const c = P.burgs.filter(b => b && b.temple && this.w.C.religion[b.cell] === g.temple).sort((a, b) => Math.hypot(a.t[0] - s.c, a.t[1] - s.r) - Math.hypot(b.t[0] - s.c, b.t[1] - s.r));
      return c[0]?.t || null;
    }
    return null;
  },
  threadSteps(b) {
    const out = [], w = this.w;
    const roles = new Set(this.know.townPeople(b, this).map(p => p.role));
    for (const th of this.s.threads) {
      if (th.done) continue;
      const st = th.steps[th.phase], g = st.goal || {};
      const roleHere = !g.role || roles.has(g.role) || (g.role === "Priest" && roles.has("Shrine-keeper")) || (g.role === "Captain of the watch" && roles.has("Elder"));
      if (!roleHere) continue;
      if (g.burg && g.burg === b.i) out.push([th, st]);
      else if (g.temple != null && b.temple && w.C.religion[b.cell] === g.temple) out.push([th, st]);
      else if (g.marker != null && (() => { const m = w.P.markers.find(x => x.i === g.marker); return m && Math.hypot(m.t[0] - b.t[0], m.t[1] - b.t[1]) <= 2; })()) out.push([th, st]);
      else if (g.farFrom && b.port && Math.hypot(b.t[0] - g.farFrom[0], b.t[1] - g.farFrom[1]) * w.miles >= g.mi) out.push([th, st]);
    }
    return out;
  },
  async completeStep(th, where) {
    const s = this.s, U = AZ.U, st = th.steps[th.phase];
    if (st.needs === "cargo" && ((s.goods || {})[this.tv.cargo] || 0) < 4) {
      th.done = true; th.outcome = "failed";
      this.log(`${U.esc(th.title)}: the consignment is gone.`, "side");
      return this.ui.say(`<b class="side">${U.esc(th.title)}</b>: there is nothing to deliver. ${s.flags.boarded ? "The pirates who boarded you took it" : "You sold some of it elsewhere"} ${AZ.T("mixed")}.`);
    }
    if (st.risk && U.rnd2(th.id, th.phase, s.seed % 9973) < st.risk) {
      th.done = true; th.outcome = "caught";
      const out = this.events.fx({ time: 24, stand: st.riskStand || [] }, `${U.esc(th.title)}: caught.`);
      return this.ui.say(`<b class="side">${U.esc(th.title)}</b>: the watch finds the letter sewn into your coat. A day in a cell, and your name in their book ${AZ.T("mixed")}.${out}`);
    }
    let reward = st.reward ? { ...st.reward } : null;
    let late = "";
    if (th.deadline && s.clock > th.deadline && reward) { if (reward.coin > 0) reward.coin = U.rn(reward.coin / 2, 1); delete reward.stand; late = " You are late: half the pay, and no thanks."; }
    if (st.needs === "cargo") { s.goods[this.tv.cargo] -= 4; delete s.flags.cargo; }
    const out = this.events.fx(reward, `${U.esc(th.title)}: ${U.esc(st.text)}${where ? " (" + U.esc(where.name || "") + ")" : ""}.`);
    th.phase++;
    if (th.phase >= th.steps.length) { th.done = true; th.outcome = "done"; }
    await this.ui.say(`<b class="side">${U.esc(th.title)}</b>: ${U.esc(st.text)}. ${th.done ? "Done." : "Next: " + U.esc(th.steps[th.phase].text) + "."}${late}${out}`);
  },
  async threadsAt(goal) {
    let hit = false;
    for (const th of this.s.threads) {
      if (th.done) continue;
      const g = th.steps[th.phase].goal || {};
      if ((goal.marker != null && g.marker === goal.marker) || (goal.unit && g.unit === goal.unit)) { await this.completeStep(th); hit = true; }
    }
    return hit;
  },
  healCost(b) { const rel = this.w.C.religion[b.cell]; return rel === this.tv.faith || (this.s.stand.f[rel] || 0) >= 2 ? 0 : AZ.Prices.heal(this.w, b); },
  addLead(l) {
    const s = this.s;
    if (!l || s.leads.some(x => x.key === l.key)) return false;
    if (l.key.startsWith("m") && s.done_m.includes(+l.key.slice(1))) return false;
    s.leads.push(l);
    if (l.from === "rumour") this.ui.toast(`New lead: <b class="side">${AZ.U.esc(l.name)}</b> (${l.from})`, "teal");
    return true;
  },
  revealLeads(radiusTiles) {
    const s = this.s; let n = 0;
    for (const x of this.w.near(s.c, s.r, radiusTiles)) {
      if (x.kind !== "marker" || s.seen.m.includes(x.o.i)) continue;
      s.seen.m.push(x.o.i);
      if (this.addLead({ key: "m" + x.o.i, name: x.o.name, type: x.o.type, t: x.o.t, from: "read" })) n++;
    }
    return n;
  },
  activeThread() { return this.s.threads.find(t => !t.done && this.stepTile(t.steps[t.phase])) || this.s.threads.find(t => !t.done) || null; },
  // ------------------------------------------------------------------ the notice board
  questOffers(b) {
    const s = this.s, w = this.w, P = w.P, U = AZ.U, T = AZ.T, out = [];
    const week = Math.floor(s.clock / 168), rnd = U.rng(`${s.seed}:q:${b.i}:${week}`);
    const d = x => Math.hypot(x.t[0] - b.t[0], x.t[1] - b.t[1]);
    const mi = x => Math.round(d(x) * w.miles);
    const days = x => Math.ceil(mi(x) / 40) + 6;
    const near = (lo, hi) => P.burgs.filter(x => x && x !== b && d(x) >= lo && d(x) <= hi).sort((a, c) => d(a) - d(c));
    const gname = g => P.goods.find(x => x.i === +g)?.name || "goods";
    // trade: what this town makes, for a town that buys it
    for (const [g] of Object.entries(b.production || {}).sort((a, c) => c[1] - a[1]).slice(0, 4)) {
      const dest = near(8, 160).find(x => (P.trade.buy[x.i] || {})[g]);
      if (!dest) continue;
      const here = AZ.Prices.goodPrice(w, b, g) || 1, there = AZ.Prices.goodPrice(w, dest, g) || here * 1.2, units = 4;
      const cost = U.rn(here * units, 1), pay = U.rn(Math.max(there, here * 1.1) * units * 1.1 + mi(dest) * 0.003, 1);
      out.push({ title: `${gname(g)} for ${dest.name}`, cost, pay, why: `${b.name} makes ${gname(g).toLowerCase()}; ${dest.name} buys it on its market ${T("data")}. You buy ${units} units here at ${U.rn(here, 2)} and sell there at about ${U.rn(there, 2)} ${T("data")}.`,
        dist: mi(dest), deadline: s.clock + days(dest) * 24, giver: b.i,
        steps: [{ text: `Deliver ${units} ${gname(g).toLowerCase()} to the merchant in ${dest.name}`, goal: { burg: dest.i, role: "Merchant" }, reward: { coin: pay } }] });
      break;
    }
    // relief for a town in a zone
    for (const z of (this.sim ? [...this.sim.zones.values()].filter(z0 => !z0.over).map(z0 => ({ ...z0, cells: [...z0.cells] })) : P.zones)) {
      if (!/Disease|Disaster|Flood|Tsunami|Eruption|Avalanche/.test(z.type)) continue;
      const tb = P.burgs.filter(x => x && z.cells.includes(x.cell) && d(x) < 220).sort((a, c) => d(a) - d(c))[0];
      if (!tb || tb === b) continue;
      const need = z.type === "Disease" ? P.goods.find(x => /salt/i.test(x.name)) : P.goods.find(x => /grain/i.test(x.name));
      const price = need ? AZ.Prices.goodPrice(w, b, need.i) || 1 : 1, cost = U.rn(price * 2, 1);
      out.push({ title: `Relief for ${tb.name}`, cost, pay: U.rn(cost * 0.6 + 1, 1), why: `${tb.name} lies in the ${z.name} (${z.type.toLowerCase()}) ${T("data")}. The temple here gathers ${need ? need.name.toLowerCase() : "supplies"} for it.`,
        dist: mi(tb), deadline: s.clock + days(tb) * 24, giver: b.i,
        steps: [{ text: `Bring ${need ? need.name.toLowerCase() : "supplies"} to the priests of ${tb.name}`, goal: { burg: tb.i, role: "Priest" }, reward: { coin: U.rn(cost * 0.6 + 1, 1), stand: [["s", tb.state, 2], ["f", w.C.religion[tb.cell], 1]] } }] });
      break;
    }
    // letters along the state's friendships and enmities
    const st = P.states[b.state];
    if (st && st.diplomacy) {
      const rels = st.diplomacy.map((r, i) => ({ r, i })).filter(o => P.states[o.i] && o.i && o.i !== b.state && /Ally|Friendly|Enemy|Suspicion|Rival/.test(o.r));
      for (const o of rels.sort(() => rnd() - 0.5).slice(0, 2)) {
        const cap = P.burgs[P.states[o.i].capital];
        if (!cap || d(cap) > 400) continue;
        const enemy = /Enemy|Rival/.test(o.r);
        const pay = U.rn(1 + mi(cap) * (enemy ? 0.008 : 0.004), 1);
        out.push({ title: `${enemy ? "A letter smuggled into" : "A letter for"} ${cap.name}`, pay, cost: 0,
          why: `${st.name} stands to ${P.states[o.i].name} as “${o.r}” ${T("data")}. ${enemy ? "Their watch searches strangers." : "The chancery wants it carried by someone without a uniform."}`,
          dist: mi(cap), deadline: s.clock + days(cap) * 24, giver: b.i,
          steps: [{ text: `Hand the letter to the watch in ${cap.name}`, goal: { burg: cap.i, role: "Captain of the watch" }, reward: { coin: pay, stand: [["s", b.state, 1]] }, risk: enemy ? 0.4 : 0, riskStand: [["s", o.i, -2]] }] });
      }
      // dispatches to the state's army in a war
      const war = (st.campaigns || []).find(c => c.end == null);
      const reg = war && P.military.filter(u => u.state === b.state && !u.naval).sort((a, c) => d(a) - d(c)).find(u => d(u) > 6 && d(u) < 300);
      if (reg) out.push({ title: `Dispatches for the ${reg.name}`, pay: U.rn(1 + mi(reg) * 0.005, 1), cost: 0, why: `${st.name} is at war: the ${war.name}, since ${war.start} ${T("data")}. The ${reg.name} is ${this.know.dirDist(b.t[0], b.t[1], reg.t).txt} ${T("data")}.`,
        dist: mi(reg), deadline: s.clock + days(reg) * 24, giver: b.i, steps: [{ text: `Carry dispatches to the ${reg.name}`, goal: { unit: `${reg.state}:${reg.i}` }, reward: { coin: U.rn(1 + mi(reg) * 0.005, 1), stand: [["s", b.state, 1]] } }] });
    }
    // strange places nearby
    const m = w.near(b.t[0], b.t[1], 80).filter(n => n.kind === "marker" && /monster|ruin|dungeon|necrop|burial|rift|cave|portal|statue/.test(n.o.type) && !s.done_m.includes(n.o.i)).sort(() => rnd() - 0.5)[0];
    if (m) out.push({ title: `The truth about the ${m.o.name}`, pay: U.rn(1.5 + m.d * w.miles * 0.004, 1), cost: 0, why: `${b.name} wants to know what is at the ${m.o.name}, ${this.know.dirDist(b.t[0], b.t[1], m.o.t).txt} ${T("data")}.`,
      dist: Math.round(m.d * w.miles), deadline: s.clock + (Math.ceil((m.d * w.miles * 2) / 30) + 6) * 24, giver: b.i,
      steps: [{ text: `See the ${m.o.name} for yourself (walk there and press Space beside it)`, goal: { marker: m.o.i } }, { text: `Tell them in ${b.name} what you found`, goal: { burg: b.i, role: "Townsfolk" }, reward: { coin: U.rn(1.5 + m.d * w.miles * 0.004, 1) } }] });
    // an offering for the faith's seat
    const rel = P.religions[w.C.religion[b.cell]], seat = rel && P.burgs.find(x => x && x.cell === rel.center);
    if (seat && seat !== b && d(seat) < 300) out.push({ title: `An offering for ${seat.name}`, pay: 0, cost: 0, why: `${b.name} keeps the ${rel.name}; its seat is ${seat.name} ${T("data")}.`,
      dist: mi(seat), deadline: null, giver: b.i, steps: [{ text: `Carry the offering to the temple in ${seat.name}`, goal: { burg: seat.i, role: "Priest" }, reward: { stand: [["f", rel.i, 2]] } }] });
    if (this.tv.trait === "well-connected") for (const o of out) { if (o.pay) o.pay = U.rn(o.pay * 1.2, 2); for (const st of o.steps) if (st.reward && st.reward.coin > 0) st.reward.coin = U.rn(st.reward.coin * 1.2, 2); }
    return out.filter(o => !s.threads.some(t => t.title === o.title));
  },
  async noticeBoard(b) {
    const s = this.s, U = AZ.U;
    for (;;) {
      const offers = this.questOffers(b);
      const opts = offers.map(o => ({ label: `◆ ${U.esc(o.title)} · ${U.num(o.dist)} mi${o.pay ? ` · pays 🟡 ${o.pay}` : ""}${o.cost ? ` · costs 🟡 ${o.cost} now` : ""}${o.deadline ? ` · within ${Math.round((o.deadline - s.clock) / 24)} days` : ""}`, cls: "side", o, disabled: s.purse < (o.cost || 0) }));
      if (!opts.length) opts.push({ label: "Nothing posted but tax notices", disabled: true });
      opts.push({ label: "Back" });
      const k = await this.ui.choose(`<b>${U.esc(b.name)}: notice board</b> · 🟡 ${U.rn(s.purse, 1)}`, opts, { cancel: opts.length - 1 });
      const o = opts[k].o;
      if (!o) return;
      const k2 = await this.ui.choose(`<b class="side">${U.esc(o.title)}</b><br>${o.why}<br>${U.esc(o.steps.map(x => x.text).join(", then "))}.`, [{ label: `Take it${o.cost ? ` (pay 🟡 ${o.cost} now)` : ""}` }, { label: "Leave it" }], { cancel: 1 });
      if (k2 !== 0) continue;
      if (o.cost) s.purse = U.rn(s.purse - o.cost, 2);
      this.startThread({ title: o.title, steps: o.steps, deadline: o.deadline, giver: o.giver, why: o.why });
    }
  },
  // ------------------------------------------------------------------ why the plan goes this way
  legReasons(cp) {
    const w = this.w, P = w.P, U = AZ.U, T = AZ.T, jr = this.jr, out = [];
    const seg = cp.legIn;
    if (!seg) {
      const o = cp.place.burg;
      const destRel = w.C.religion[jr.segs[jr.segs.length - 1].to];
      out.push(`The road starts in ${U.esc(o.name)}, capital and port of ${U.esc(P.states[o.state]?.fullName)} ${T("data")}. Its end is ${U.esc(jr.dest.name)}, which keeps the ${U.esc(P.religions[destRel]?.name)} ${T("data")}: that is why a pilgrim goes there.`);
      return out;
    }
    const from = jr.cps[cp.i - 1].place, to = cp.place;
    const fb = from.burg, tb = to.burg;
    const fFeat = fb ? w.C.feature[fb.cell] : null, tFeat = tb ? w.C.feature[tb.cell] : null;
    if (fb && tb && to.at) {
      if (fFeat !== tFeat) out.push(`No land joins ${U.esc(fb.name)} (${U.esc(P.features[fFeat]?.name || "")}) and ${U.esc(tb.name)} (${U.esc(P.features[tFeat]?.name || "")}): it has to be by water ${T("data")}.`);
      else out.push(`${U.esc(fb.name)} and ${U.esc(tb.name)} share ${U.esc(P.features[tFeat]?.name || "one landmass")}; ${U.num(Math.round(Math.hypot(fb.t[0] - tb.t[0], fb.t[1] - tb.t[1]) * w.miles))} mi as the crow flies, but the plan goes by water ${T("mixed")}.`);
    }
    const days = seg.hoursPerDay >= 24 ? seg.travelHours / 24 : seg.travelHours / seg.hoursPerDay;
    out.push(`${U.esc(seg.transport)}: ${seg.speed} mph for ${seg.hoursPerDay} hours a day, ${U.num(seg.miles)} mi, about ${Math.round(days)} days ${T("data")}. ${AZ.vesselClass(seg.transport) === "ship" ? "A ship keeps the sea day and night and is booked as a passenger." : "A boat is hired with its crew; it sails by day and anchors at night, and goes where ships do not."}`);
    if (tb && to.at) {
      const lanes = new Set();
      const h = w.harbour(tb, seg.cls || "boat");
      if (h) for (let dr = -3; dr <= 3; dr++) for (let dc = -3; dc <= 3; dc++) { const rt = w.inb(h.t[0] + dc, h.t[1] + dr) && w.route(h.t[0] + dc, h.t[1] + dr); if (rt && rt.group === "searoutes") lanes.add(rt.name); }
      out.push(lanes.size ? `${U.esc(tb.name)} lies on ${[...lanes].slice(0, 2).map(U.esc).join(" and ")} ${T("data")}.` : `No named sea lane reaches ${U.esc(tb.name)} ${T("data")}: ships on regular runs will not call there, which is why the plan hires its own boat.`);
      const rel = P.religions.find(r => r && r.center === tb.cell);
      if (rel) out.push(`${U.esc(tb.name)} is the seat of the ${U.esc(rel.name)} (${rel.type.toLowerCase()}) ${T("data")}.`);
      if (tb.capital) out.push(`It is the capital of ${U.esc(P.states[tb.state]?.fullName)}: markets, a temple${tb.walls ? ", walls" : ""} ${T("data")}.`);
      const stance = tb.state ? this.know.rel(this.tv.homeState, tb.state) : null;
      if (stance) out.push(`${U.esc(P.states[tb.state].name)} stands to your people as “${stance}” ${T("data")}.`);
    } else {
      const near = to.burg;
      if (near) out.push(`The plan stops at sea ${U.esc(to.name)}: by its own timing the boat's sailing hours run out about here ${T("mixed")}; ${U.esc(near.name)} (${U.esc(P.states[near.state]?.name || "unclaimed")}) gives a lee and lights ${T("data")}.`);
    }
    if (seg.nights?.length) out.push(`The plan anchors ${seg.nights.length} times on the way (shown as small gold marks on the course) ${T("mixed")}.`);
    const hz = new Map();
    for (const [c, r] of seg.chain) for (const n of w.near(c, r, 3)) if (n.kind === "marker" && /pirate|monster/.test(n.o.type)) hz.set(n.o.i, n.o);
    if (hz.size) out.push(`Hazards on the course: ${[...hz.values()].map(m => U.esc(m.name)).join(", ")} ${T("data")}.`);
    const crossed = new Set(), avoided = new Set();
    for (const [c, r] of seg.chain) for (const z of w.zonesOfCell(w.cell(c, r))) crossed.add(z.name);
    for (const z of P.zones) {
      if (crossed.has(z.name)) continue;
      const zc = z.cells[0];
      if (zc != null && seg.chain.some(([c, r], k) => k % 8 === 0 && Math.hypot(w.C.cx[zc] - w.centre(c, r)[0], w.C.cy[zc] - w.centre(c, r)[1]) < 40)) avoided.add(z.name);
    }
    if (crossed.size) out.push(`The course crosses the ${[...crossed].map(U.esc).join(", ")} ${T("data")}.`);
    if (avoided.size) out.push(`It keeps clear of the ${[...avoided].map(U.esc).join(", ")} ${T("data")}.`);
    const others = P.burgs.filter(x => x && x.port && x !== fb && x !== tb && seg.chain.some(([c, r], k) => k % 6 === 0 && Math.hypot(x.t[0] - c, x.t[1] - r) < 20)).slice(0, 4);
    if (others.length) out.push(`Other harbours near the way, if you choose differently: ${others.map(x => U.esc(x.name)).join(", ")} ${T("data")}.`);
    return out;
  },
});

// rumours become leads when the thing is near enough to follow
AZ.Know.prototype.rumourLead = function (g, f, d) {
  if (!g || d > 1500) return;
  const key = f.kind === "marker" ? `m${this.P.markers.find(m => m.name === f.name && m.t === f.t)?.i ?? f.name}` : `r:${f.kind}:${f.name}`;
  g.addLead({ key, name: f.kind === "war" ? `${f.name} (${f.a} against ${f.d})` : f.name, type: f.type || f.kind, t: f.t, from: "rumour" });
};
