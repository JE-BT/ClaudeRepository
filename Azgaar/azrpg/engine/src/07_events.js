// ---------------------------------------------------------------------------------------------
// Seasons, travellers and events.
//   Seasons: the plan clock carries a day of the year; each latitude gets its own season, day
//   length and a seasonal swing around the map's annual mean temperature (mixed).
//   Travellers: kinds are found in the data (stops, faith seats, wars, trade, zones, libraries);
//   the player picks one or lets chance pick, and the details are generated.
//   Events: markers and zones have scenes with choices; choices cost time and coin, change
//   standing with faiths and states, leave conditions, and open side stories (teal).
// ---------------------------------------------------------------------------------------------
Object.assign(AZ.Clock, {
  doyAt(t) { return (((this.doy0 + Math.floor(t / 24)) % 365) + 365) % 365; },
  season(lat, t) {
    const doy = this.doyAt(t);
    if (Math.abs(lat) < 23.5) {
      const northWet = doy >= 120 && doy < 300;
      return (lat >= 0) === northWet ? "wet season" : "dry season";
    }
    const d = lat >= 0 ? doy : (doy + 186) % 365; // southern seasons: autumn from the March equinox
    return d >= 80 && d < 172 ? "spring" : d >= 172 && d < 266 ? "summer" : d >= 266 && d < 355 ? "autumn" : "winter";
  },
  // the map's temperature is an annual mean; the swing grows with latitude and shrinks at sea
  today(meanC, lat, t, sea) {
    const doy = this.doyAt(t), peak = lat >= 0 ? 200 : 17;
    const amp = AZ.U.clamp(Math.abs(lat) * 0.3, 1, 18) * (sea ? 0.55 : 1);
    return meanC + amp * Math.cos((2 * Math.PI * (doy - peak)) / 365);
  },
  dateStr(t) { return `day ${this.doyAt(t) + 1} of the year`; },
});

// ------------------------------------------------------------------ traveller kinds
AZ.travellerKinds = function (w, jr) {
  const P = w.P, C = w.C, kinds = [];
  if (!jr) return [{ id: "wanderer", label: "Wanderer", blurb: "No journey on this map; you go where you please.", wt: 1, culture: C.culture[P.burgs.find(b => b && b.capital).cell], faith: 0, home: P.burgs.find(b => b && b.capital) }];
  const first = jr.segs[0], last = jr.segs[jr.segs.length - 1];
  const oB = jr.origin.burg, dB = jr.dest.burg;
  const oCul = C.culture[first.from], dCul = C.culture[last.to], oRel = C.religion[first.from], dRel = C.religion[last.to];
  const relName = i => P.religions[i]?.name || "no faith";
  const seatOf = r => P.burgs.find(b => b && b.cell === P.religions[r]?.center);
  const dSeat = seatOf(dRel);
  const homesIn = (state, cul) => P.burgs.filter(b => b && b.state === state && (cul == null || b.culture === cul));
  const stops = jr.segs.map(s => s.place.burg).filter(Boolean).filter((b, i, a) => a.indexOf(b) === i && b !== oB && b !== dB);
  kinds.push({ id: "returning", label: `Returning ${P.cultures[dCul].name}`, wt: 4, culture: dCul, faith: dRel, homes: homesIn(dB.state, dCul).length ? homesIn(dB.state, dCul) : [dB],
    blurb: `Born to the ${relName(dRel)} in ${P.states[dB.state]?.name}; going home.`,
    trades: ["deckhand", "clerk of a trading house", "released hostage of an old treaty", "journeyman scribe", "widowed net-mender"],
    why: h => `born to the ${relName(dRel)} among the ${P.cultures[dCul].name} of ${P.states[h.state]?.name || "the far shore"}, you are going home to make the pilgrimage you were promised as a child`,
    thread: h => (h !== dB ? { title: `Home to ${h.name}`, steps: [{ text: `Visit your family in ${h.name}`, goal: { burg: h.i, role: "Townsfolk" }, reward: { coin: 5, stand: [["f", dRel, 1]] } }] }
      : { title: "A promise kept", steps: [{ text: `Pray at the temple of ${dB.name}`, goal: { burg: dB.i, role: "Priest" }, reward: { stand: [["f", dRel, 2]] } }] }), purse: 12 });
  if (dRel !== oRel) kinds.push({ id: "convert", label: `${P.cultures[oCul].name} convert`, wt: 3.5, culture: oCul, faith: dRel, homes: [oB], family: oRel,
    blurb: `Raised in the ${relName(oRel)} of ${oB.name}; took the ${relName(dRel)} as an adult.`,
    trades: ["chandler", "harbour clerk", "schoolmaster", "cooper", "temple sweeper"],
    why: () => `raised in the ${relName(oRel)} of ${oB.name}, you took the ${relName(dRel)} as an adult; your family has not forgiven it`,
    thread: () => (dSeat && dSeat !== oB ? { title: "A letter home", steps: [{ text: `Have the priests at ${dSeat.name}, seat of your new faith, bless a letter to your family`, goal: { burg: dSeat.i, role: "Priest" }, reward: { stand: [["f", dRel, 1]], coin: -1 } }] } : null), purse: 10 });
  for (const b of stops) {
    const rel = C.religion[b.cell], cul = C.culture[b.cell];
    if (rel === dRel && cul === dCul) continue;
    kinds.push({ id: `stranger:${b.i}`, label: `Stranger from ${b.name}`, wt: 2.5 / stops.length, culture: cul, faith: rel, homes: [b],
      blurb: `${P.cultures[cul].name}, of the ${relName(rel)}; an errand to ${dB.name}.`,
      trades: ["envoy's secretary", "travelling physician", "apprentice cartographer", "copyist", "ship's cook"],
      why: h => `you keep the ${relName(rel)} of ${h.name}, and you travel to ${dB.name} on an errand you have told no one`,
      thread: h => (dSeat ? { title: `A message for ${dSeat.name}`, steps: [{ text: `Carry a sealed message from ${h.name} to the clergy of ${dSeat.name}`, goal: { burg: dSeat.i, role: "Priest" }, reward: { coin: 6 } }] } : null), purse: 8 });
  }
  const warStates = [...new Set([oB, ...stops, dB].map(b => b.state))].filter(st => (P.states[st]?.campaigns || []).some(c => c.end == null));
  for (const st of warStates) {
    const S = P.states[st], war = S.campaigns.find(c => c.end == null), cap = P.burgs[S.capital];
    const regs = P.military.filter(u => u.state === st && !u.naval);
    kinds.push({ id: `soldier:${st}`, label: `Soldier of ${S.name}`, wt: 1.5, culture: cap.culture, faith: C.religion[cap.cell], homes: homesIn(st, cap.culture).slice(0, 12), homeState: st,
      blurb: `On leave from the ${war.name} (since ${war.start}).`,
      trades: ["archer", "cavalry groom", "sapper", "quartermaster's clerk", "infantry sergeant"],
      why: () => `you serve ${S.fullName} in the ${war.name}, which began in ${war.start}; your leave is a pilgrimage, or so your papers say`,
      thread: () => (regs.length ? { title: "Papers to sign", steps: [{ text: `Report to the ${regs[0].name}`, goal: { unit: `${st}:${regs[0].i}` }, reward: { coin: 5, stand: [["s", st, 1]] } }] } : null), purse: 15 });
  }
  if (oB.state && dB.state && oB.state !== dB.state) {
    const rel = P.states[oB.state].diplomacy?.[dB.state] || "Unknown";
    kinds.push({ id: "envoy", label: `Envoy of ${P.states[oB.state].name}`, wt: 1.2, culture: oCul, faith: oRel, homes: [oB],
      blurb: `Letters for ${P.states[dB.state].name}; the two stand as “${rel}”.`,
      trades: ["junior envoy", "herald", "secretary to the chancery"],
      why: () => `you carry sealed letters from ${P.states[oB.state].fullName} to ${P.states[dB.state].fullName}, which it regards as “${rel}”; pilgrimage is your cover and your comfort`,
      thread: () => ({ title: "Sealed letters", steps: [{ text: `Present the letters to the watch in ${dB.name}`, goal: { burg: dB.i, role: "Captain of the watch" }, reward: { coin: 10, stand: [["s", dB.state, 2]] } }] }), purse: 30 });
  }
  const sells = P.trade.sell[oB.i] || {}, buys = P.trade.buy[dB.i] || {};
  const portable = g => { const x = P.goods.find(y => y.i === +g); return x && !/ship|boat|house|building/i.test(x.name); };
  const val = g => P.goods.find(y => y.i === +g)?.value || 0;
  const cargo = Object.keys(sells).filter(g => buys[g] && portable(g)).sort((a, b) => val(b) - val(a))[0] || Object.keys(sells).filter(portable).sort((a, b) => val(b) - val(a))[0];
  if (cargo) {
    const gName = P.goods.find(g => g.i === +cargo)?.name || "goods";
    kinds.push({ id: "factor", label: "Trading factor", wt: 1.2, culture: oCul, faith: oRel, homes: [oB], cargo: +cargo,
      blurb: `${gName} from ${oB.name} for the market of ${dB.name}.`,
      trades: ["factor of a trading house", "supercargo", "merchant's son"],
      why: () => `you travel with a consignment of ${gName.toLowerCase()}, which ${oB.name} sells and ${buys[cargo] ? `${dB.name} buys` : "you hope to sell"}; the pilgrimage is real, and so is the profit`,
      thread: () => ({ title: `${gName} for ${dB.name}`, steps: [{ text: `Deliver the ${gName.toLowerCase()} to the merchant in ${dB.name}`, goal: { burg: dB.i, role: "Merchant" }, reward: { coin: 15 }, needs: "cargo" }] }), purse: 20 });
  }
  if (oB.port && (P.military.some(u => u.naval && u.state === oB.state) || (oB.production || {})[P.goods.find(g => /ship/i.test(g.name))?.i])) {
    kinds.push({ id: "shipmaster", label: `Shipmaster of ${oB.name}`, wt: 1, culture: oCul, faith: oRel, homes: [oB], boat: true, purseF: 0.6,
      blurb: `You own a sailing boat in ${oB.name}; you need only a crew and stores.`,
      trades: ["shipmaster", "coasting skipper", "boat-owner"],
      why: () => `you own a sailing boat in ${oB.name} and have sailed these waters for years; this time the cargo is yourself`,
      thread: null, purse: 12 });
  }
  const lib = P.markers.find(m => m.type === "libraries"), stat = P.markers.find(m => m.type === "statues");
  if (lib) {
    const near = w.near(lib.t[0], lib.t[1], 80).find(n => n.kind === "burg");
    const home = near ? near.o : oB;
    kinds.push({ id: "scholar", label: `Scholar of the ${lib.name}`, wt: 1, culture: home.culture, faith: C.religion[home.cell], homes: [home],
      blurb: `Sent to copy the rites of the ${relName(dRel)}.`,
      trades: ["copyist", "archivist", "student of tongues"],
      why: () => `the ${lib.name} sent you to copy the rites of the ${relName(dRel)}; you will be expected to bring back more than that`,
      thread: () => (stat ? { title: "An inscription no one can read", steps: [
        { text: `Copy the inscription on the ${stat.name}`, goal: { marker: stat.i }, reward: { flag: "inscription" } },
        { text: `Bring the copy to the ${lib.name}`, goal: { marker: lib.i }, reward: { coin: 8, reveal: 160 } }] } : null), purse: 10 });
  }
  for (const z of P.zones) {
    if (!/Disease|Disaster|Tsunami|Flood|Invasion|Rebels|Eruption/.test(z.type)) continue;
    const home = P.burgs.find(b => b && z.cells.includes(b.cell));
    if (!home || Math.hypot(home.t[0] - oB.t[0], home.t[1] - oB.t[1]) * w.miles > 1200) continue;
    kinds.push({ id: `fugitive:${z.i}`, label: `Fled the ${z.name}`, wt: 0.8, culture: home.culture, faith: C.religion[home.cell], homes: [home],
      blurb: `From ${home.name}; you left with little.`,
      trades: ["fisher", "weaver", "gravedigger", "baker's apprentice"],
      why: h => `you fled ${h.name} when the ${z.name} came, and you have been walking towards something ever since`,
      thread: h => ({ title: "Word home", steps: [{ text: `Send word to ${h.name} from a harbour far away (any harbourmaster over 1,000 miles from home)`, goal: { role: "Harbourmaster", farFrom: h.t, mi: 1000 }, reward: { stand: [["f", C.religion[h.cell], 1]] } }] }), purse: 3 });
  }
  return kinds;
};

// what the plan would cost at local prices: fares, boat hire and wages, food for everyone, rooms
AZ.planCost = function (w, jr) {
  if (!jr || !AZ.Prices) return 20;
  let cost = 0;
  for (const seg of jr.segs) {
    const from = w.P.burgs[w.C.burg[seg.from]] || jr.origin.burg, days = (seg.planEnd - seg.planStart) / 24;
    if (!seg.moving) cost += Math.ceil(days) * (AZ.Prices.inn(w, from) + AZ.Prices.ration(w, from));
    else if (AZ.vesselClass(seg.transport) === "ship") cost += AZ.Prices.fare(w, from, seg.miles) + days * AZ.Prices.ration(w, from);
    else cost += days * (3 * (AZ.Prices.wage(w, from) + AZ.Prices.ration(w, from)) + AZ.Prices.hire(w, from) + AZ.Prices.ration(w, from) + 4 * AZ.Prices.water(w, from));
  }
  return cost * 1.15;
};
AZ.makeTraveller = function (w, jr, seed, kindId) {
  const U = AZ.U, rnd = U.rng(seed), P = w.P;
  const kinds = AZ.travellerKinds(w, jr);
  let K = kinds.find(k => k.id === kindId);
  if (!K) {
    let roll = rnd() * kinds.reduce((a, k) => a + k.wt, 0); K = kinds[0];
    for (const k of kinds) if ((roll -= k.wt) <= 0) { K = k; break; }
  } else rnd();
  const home = rnd.pick(K.homes && K.homes.length ? K.homes : [jr ? jr.origin.burg : P.burgs[1]]);
  const cul = P.cultures[K.culture] || P.cultures[1], rel = P.religions[K.faith];
  const name = w.names.get(cul.base, rnd);
  const age = 18 + Math.floor(rnd() * 44);
  const deity = ((rel && rel.deity) || "").split(",")[0];
  const skin = rnd.pick(["rgb(240,204,170)", "rgb(214,170,130)", "rgb(176,124,88)", "rgb(124,84,58)"]);
  const cloak = U.shade(U.hex2rgb(cul.color || "#806040"), -0.35);
  return {
    seed, kind: K.id, kindLabel: K.label, name, age, culture: K.culture, faith: K.faith, home: home?.i, homeState: K.homeState ?? home?.state ?? 0,
    trade: rnd.pick(K.trades || ["traveller"]), why: K.why ? K.why(home) : K.blurb, token: deity ? `a small icon of ${deity}` : "a pilgrim's token",
    purse: Math.round(AZ.planCost(w, jr) * (K.purseF ?? ({ returning: 1, convert: 1, envoy: 1.5, factor: 1.2, scholar: 0.9 }[K.id] ?? (/^stranger/.test(K.id) ? 0.9 : /^soldier/.test(K.id) ? 0.8 : /^fugitive/.test(K.id) ? 0.45 : 1)))),
    thread: K.thread ? K.thread(home) : null, cargo: K.cargo ?? null, boat: !!K.boat, food: 3, kindId: K.id,
    pal: { cloak: U.css(cloak), cloakDark: U.css(U.shade(cloak, -0.35)), skin, belt: "rgb(150,110,60)" },
  };
};

// ------------------------------------------------------------------ events
AZ.Events = class {
  constructor(g) { this.g = g; }
  get w() { return this.g.w; }
  get s() { return this.g.s; }
  rnd(key) { return AZ.U.rng(`${this.s.seed}:${key}`); }
  relByName(text) {
    const P = this.w.P;
    return P.religions.filter(r => r && r.i && text.includes(r.name)).sort((a, b) => b.name.length - a.name.length)[0] || null;
  }
  stateByPrefix(name) {
    const word = (name || "").split(" ")[0].toLowerCase();
    return this.w.P.states.filter(s => s && s.i && word.startsWith(s.name.toLowerCase().slice(0, Math.max(4, s.name.length - 1)))).sort((a, b) => b.name.length - a.name.length)[0] || null;
  }
  // effects ------------------------------------------------------------------------------
  fx(e, note) {
    const g = this.g, s = this.s, U = AZ.U, bits = [];
    if (!e) return "";
    if (e.time) { s.clock += e.time; bits.push(`${AZ.Clock.span(e.time)} pass`); }
    if (e.coin) { const before = s.purse; s.purse = Math.max(0, s.purse + e.coin); bits.push(`🟡 ${s.purse - before >= 0 ? "+" : ""}${s.purse - before}`); }
    for (const [k, id, n] of e.stand || []) {
      const tab = k === "f" ? s.stand.f : s.stand.s;
      tab[id] = (tab[id] || 0) + n;
      const nm = k === "f" ? this.w.P.religions[id]?.name : this.w.P.states[id]?.name;
      bits.push(`standing with ${nm} ${n > 0 ? "+" : ""}${n}`);
    }
    if (e.cond) { s.cond[e.cond] = true; bits.push(AZ.COND[e.cond].on); }
    for (const c of e.cure || []) if (s.cond[c]) { delete s.cond[c]; bits.push(AZ.COND[c].off); }
    if (e.flag) { s.flags[e.flag] = true; }
    if (e.unflag) delete s.flags[e.unflag];
    if (e.reveal) { const n = g.revealLeads(e.reveal); bits.push(`${n} new places entered in your journal`); }
    if (e.thread) g.startThread(e.thread);
    const out = bits.length ? ` <span class="dim">(${bits.join("; ")})</span>` : "";
    if (note) g.log(`${note}${out}`, "side");
    g.dirty = true;
    return out;
  }
  // triggers --------------------------------------------------------------------------------
  async onStep() {
    const g = this.g, s = this.s, w = this.w;
    if (g.ui.busy()) return;
    const cell = w.cell(s.c, s.r);
    for (const z of w.zonesOfCell(cell)) if (!s.done_z.includes(z.i)) { s.done_z.push(z.i); g.setAuto(false); await this.zone(z); return; }
    for (const n of w.near(s.c, s.r, 3)) {
      if (n.kind !== "marker") continue;
      const T = AZ.MARKERS[n.o.type];
      if (!T || !T.auto || s.done_m.includes(n.o.i)) continue;
      if (n.d > (T.radius ?? 2)) continue;
      if (T.sea && !s.aboard) continue;
      if (T.land && s.aboard) continue;
      s.done_m.push(n.o.i); g.setAuto(false);
      await this.marker(n.o, true);
      return;
    }
  }
  async marker(m, auto) {
    const g = this.g, U = AZ.U, T = AZ.MARKERS[m.type] || AZ.MARKERS._default;
    const head = `<b class="side">${U.esc(m.name)}</b> (${m.type}) ${AZ.T("data")}`;
    await g.threadsAt({ marker: m.i });
    const first = !this.s.done_m.includes(m.i);
    if (first) this.s.done_m.push(m.i);
    this.s.leads = this.s.leads.filter(i => i !== m.i);
    if (T.auto && !auto && !first) return g.ui.say(head + "<br>" + U.esc(m.note).replace(/\n/g, "<br>"));
    if (T.auto && T.sea && this.s.voyage && this.s.aboard) return this.captainDecides(m, head);
    await T.run(this, m, head);
  }
  async captainDecides(m, head) {
    const g = this.g, v = this.s.voyage, U = AZ.U, r = this.rnd(`cap${m.i}`)();
    let text, fx;
    if (r < 0.5) { text = `${U.esc(v.captain)} puts the helm over and keeps clear. Most of a day lost.`; fx = { time: 10 }; }
    else if (r < 0.8 || !/pirate/.test(m.type)) { text = `${U.esc(v.captain)} holds his course, and nothing comes of it.`; fx = null; }
    else { text = "Pirates board her at dusk. They take the passengers' purses as well as the cargo."; fx = { coin: -Math.min(this.s.purse, U.rn(this.s.purse * 0.4, 1)), time: 12, flag: "boarded" }; }
    const out = this.fx(fx, `${U.esc(m.name)}: the captain's choice.`);
    return g.ui.say(`${head}<br>You are a passenger; the captain decides. ${text}${out} ${AZ.T("mixed")}`);
  }
  async zone(z) { const T = AZ.ZONES[z.type] || AZ.ZONES._default; await T(this, z, `<b class="hook">${AZ.U.esc(z.name)}</b> (${z.type.toLowerCase()} zone) ${AZ.T("data")}`); }
  // a choice scene: options [{label, fx, text, if}]
  async scene(head, body, options, key) {
    const g = this.g, U = AZ.U;
    const opts = options.filter(o => o.if === undefined || o.if);
    const k = await g.ui.choose(`${head}<br>${body}`, opts.map(o => ({ label: o.label, disabled: o.disabled })), { cancel: opts.length - 1 });
    const o = opts[k];
    let text = typeof o.text === "function" ? o.text() : o.text;
    let eff = typeof o.fx === "function" ? o.fx() : o.fx;
    if (o.roll) { const r = this.rnd(`${key}:${k}`)(); const good = r < o.roll.p; text = good ? o.roll.ok : o.roll.bad; eff = good ? o.roll.okFx : o.roll.badFx; }
    const out = this.fx(eff, `${U.esc(head.replace(/<[^>]+>/g, "").replace(/ (data|mixed|new)$/, ""))}: ${U.esc(o.label)}.`);
    if (text) await g.ui.say(text + out + ` ${AZ.T("mixed")}`);
    return k;
  }
};

AZ.COND = {
  fever: { on: "you are fevered", off: "the fever breaks", slow: 1.3, label: "fevered" },
  hurt: { on: "you are hurt", off: "you are mended", slow: 1.2, label: "hurt" },
  damaged: { on: "the vessel is damaged", off: "the vessel is repaired", slow: 1.25, label: "vessel damaged" },
};

// marker scenes (type -> {auto, radius, sea, land, run})
AZ.MARKERS = (() => {
  const U = AZ.U, esc = U.esc;
  const lore = (ev, m, head, extra = []) => ev.g.ui.say([head + "<br>" + esc(m.note).replace(/\n/g, "<br>"), ...extra]);
  const explore = (hours, label) => async (ev, m, head) => {
    const s = ev.s, r = ev.rnd(`m${m.i}`)();
    if (s.flags[`ex${m.i}`]) return ev.g.ui.say(head + "<br>You have already been through it.");
    const link = m.links?.find(l => /dungeon/.test(l));
    await ev.scene(head, esc(m.note.split("\n")[0]) + (link ? `<br><span class="dim">The map links this place to a One Page Dungeon: <a href="${esc(link)}" target="_blank" rel="noopener">open it</a> ${AZ.T("data")}</span>` : ""), [
      { label: `${label} (${hours} h)`, fx: () => (s.flags[`ex${m.i}`] = true) && (r < 0.35 ? { time: hours, flag: "relic", thread: { title: `A relic from the ${m.name}`, steps: [{ text: "Take the relic to a temple of your own faith", goal: { temple: s.tvFaith, role: "Priest" }, reward: { stand: [["f", s.tvFaith, 2]], unflag: "relic" } }] } } : r < 0.65 ? { time: hours, coin: 4 + Math.floor(r * 10) } : r < 0.85 ? { time: hours } : { time: hours + 6, cond: "hurt" }),
        text: () => (r < 0.35 ? "Deep inside you find something old and holy, wrapped in rotten cloth. It wants to be carried home." : r < 0.65 ? "Someone hid coins here and did not come back for them." : r < 0.85 ? "Dust, bones, and the feeling of being watched. Nothing to carry away." : "A floor gives way. You climb out bruised and slow.") },
      { label: "Leave it be", fx: null, text: "" }], `m${m.i}`);
  };
  const hazardSea = (label) => ({ auto: true, radius: 3, sea: true, run: async (ev, m, head) => {
    const s = ev.s, dir = AZ.U.compass(m.t[0] - s.c, m.t[1] - s.r);
    await ev.scene(head, `${label} off to the ${dir}.`, [
      { label: "Steer wide (about 8 hours lost)", fx: { time: 8 }, text: "The master puts the helm over and keeps the danger hull-down until dark." },
      { label: "Pay them off (🟡 8)", if: /pirate/.test(m.type), disabled: s.purse < 8, fx: { coin: -8, time: 1 }, text: "A boat comes over; coins go across; the black sails fall away." },
      { label: "Hold course", roll: { p: 0.55, ok: "Nothing comes of it. The crew talks of nothing else for a day.", okFx: null,
        bad: /pirate/.test(m.type) ? "They board at dusk and take what they like. The hull is holed in the struggle." : "Something huge rises under the bow. Timbers crack.", badFx: /pirate/.test(m.type) ? { coin: -Math.min(s.purse, 10), time: 12, cond: "damaged", flag: "boarded" } : { time: 6, cond: "damaged" } } }], `m${m.i}`);
  } });
  const hazardLand = (label, toll) => ({ auto: true, radius: 2, land: true, run: async (ev, m, head) => {
    const s = ev.s, soldier = /^soldier/.test(ev.g.tv.kind);
    await ev.scene(head, label, [
      { label: "Go round (about 6 hours)", fx: { time: 6 } , text: "You take the long way through rough ground." },
      { label: `Pay (🟡 ${toll})`, if: toll > 0, disabled: s.purse < toll, fx: { coin: -toll }, text: "They count the coins twice and let you by." },
      { label: soldier ? "Show your papers and your sword" : "Bluff your way past", roll: { p: soldier ? 0.85 : 0.45, ok: "They decide you are not worth it.", okFx: null, bad: "It goes badly. You lose your purse's top layer and some blood.", badFx: { coin: -Math.min(s.purse, 6), time: 8, cond: "hurt" } } }], `m${m.i}`);
  } });
  const T = {
    pirates: hazardSea("Black sails"),
    "sea-monsters": hazardSea("The water heaves where the old sailors said it would"),
    brigands: hazardLand("A gang watches the road from cover.", 5),
    "hill-monsters": hazardLand("Scorched trees, and a smell of sulphur on the wind. Something lairs in these hills.", 0),
    "lake-monsters": { run: (ev, m, head) => lore(ev, m, head, ["You do not fish here."]) },
    ruins: { run: explore(10, "Search the ruins") }, dungeons: { run: explore(16, "Go down into it") }, caves: { run: explore(8, "Explore the chasm") },
    necropolises: { run: explore(14, "Walk among the tombs") }, "disturbed-burials": hazardLand("The dead are walking here. You hear them before you see them.", 0),
    rifts: { run: explore(6, "Go to the rift") },
    inns: { run: async (ev, m, head) => {
      const s = ev.s, g = ev.g;
      await ev.scene(head, esc(m.note), [
        { label: `Take a room until morning (🟡 ${AZ.Prices.inn(g.w, null)})`, disabled: s.purse < AZ.Prices.inn(g.w, null), fx: () => ({ coin: -AZ.Prices.inn(g.w, null), time: Math.max(1, AZ.Clock.nextDawn(s.clock, g.lat()) - s.clock), cure: ["hurt"] }), text: () => "You sleep under a roof. Over supper: " + (g.know.rumour(m.t[0], m.t[1], ev.rnd(`inn${m.i}:${Math.floor(s.clock / 24)}`), g) || "nothing worth repeating.") },
        { label: "Just a meal (🟡 1)", disabled: s.purse < 1, fx: { coin: -1, time: 1 }, text: "The food is as good as they say." },
        { label: "Move on", fx: null, text: "" }], `m${m.i}`);
    } },
    "hot-springs": { run: async (ev, m, head) => ev.scene(head, esc(m.note), [{ label: "Bathe (3 h)", fx: { time: 3, cure: ["fever", "hurt"] }, text: "The heat goes into your bones and takes the ache with it." }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    "water-sources": { run: async (ev, m, head) => ev.scene(head, esc(m.note), [{ label: "Drink, and fill a flask (2 h)", fx: { time: 2, cure: ["fever"], flag: "flask" }, text: "Cold, clean water. You fill a flask for the road; it may help later." }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    "sacred-forests": { run: async (ev, m, head) => { const r = ev.relByName(m.note); return ev.scene(head, esc(m.note), [{ label: "Leave an offering (🟡 2)", disabled: ev.s.purse < 2, fx: r ? { coin: -2, time: 1, stand: [["f", r.i, 1]] } : { coin: -2 }, text: `You leave something at the oldest tree${r ? ` for the ${esc(r.name)}` : ""}.` }, { label: "Pass through quietly", fx: { time: 1 }, text: "" }], `m${m.i}`); } },
    statues: { run: async (ev, m, head) => ev.scene(head, esc(m.note.split("\n")[0]), [{ label: "Copy the inscription (2 h)", fx: { time: 2, flag: "inscription" }, text: "You copy every mark as well as you can. Someone, somewhere, may read it." }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    libraries: { run: async (ev, m, head) => {
      const s = ev.s;
      await ev.scene(head, esc(m.note), [
        { label: "Read in the stacks (12 h, 🟡 2 to the copyists)", disabled: s.purse < 2, fx: { time: 12, coin: -2, reveal: 160 }, text: "Old charts and travellers' letters: you note every marked place within a hundred and sixty leagues." },
        { label: "Ask after the inscription you copied", if: !!s.flags.inscription, fx: { time: 4, unflag: "inscription", coin: 3 }, text: "An old archivist reads it aloud, slowly. It is a list of names, and one of them is a place on your route." },
        { label: "Move on", fx: null, text: "" }], `m${m.i}`);
    } },
    battlefields: { run: async (ev, m, head) => ev.scene(head, esc(m.note), [{ label: "Walk the field (4 h)", fx: { time: 4 }, text: "Rusted iron, a broken standard, too many small mounds." }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    mines: { run: async (ev, m, head) => ev.scene(head, esc(m.note), [{ label: "Work a shift for pay (12 h)", fx: { time: 12, coin: 4 }, text: "Hard work, honest pay, and dust in every seam of your clothes." }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    circuses: { run: async (ev, m, head) => ev.scene(head, esc(m.note), [{ label: "Spend an afternoon (4 h, 🟡 1)", disabled: ev.s.purse < 1, fx: { time: 4, coin: -1 }, text: () => "Lights, music, and the crowd's talk: " + (ev.g.know.rumour(m.t[0], m.t[1], ev.rnd(`c${m.i}`), ev.g) || "") }, { label: "Move on", fx: null, text: "" }], `m${m.i}`) },
    portals: { run: async (ev, m, head) => {
      const g = ev.g, s = ev.s, others = g.w.P.markers.filter(x => x.type === "portals" && x.i !== m.i);
      const k = await g.ui.choose(`${head}<br>${esc(m.note)}<br><span class="dim">Stepping through leaves your ${s.vessel ? esc(s.vessel.kind.toLowerCase()) : "baggage"} behind. You will have to come back the same way.</span>`,
        [...others.map(o => ({ label: `Step through to the ${esc(o.name)} (${AZ.U.num(g.know.dirDist(s.c, s.r, o.t).mi)} mi)` })), { label: "Stay on this side" }], { cancel: others.length });
      if (k >= others.length) return;
      const o = others[k];
      s.aboard = false; s.auto = false; s.c = o.t[0]; s.r = o.t[1];
      if (!g.w.isLand(s.c, s.r)) { const l = g.w.near(s.c, s.r, 2).find(n => n.kind === "burg"); if (l) { s.c = l.o.t[0]; s.r = l.o.t[1]; } }
      ev.fx({ time: 1 }, `Stepped through the portal to the ${esc(o.name)}.`);
      g.anim = null; g.afterStep();
      await g.ui.say(`The world folds. You stand at the ${esc(o.name)}, ${AZ.U.num(g.know.dirDist(s.c, s.r, m.t).mi)} miles from where you were ${AZ.T("data")}.`);
    } },
    party: { run: async (ev, m, head) => {
      const g = ev.g, s = ev.s;
      const lead = g.w.P.markers.filter(x => !s.done_m.includes(x.i) && x.type !== "party").map(x => ({ x, d: Math.hypot(x.t[0] - s.c, x.t[1] - s.r) })).sort((a, b) => a.d - b.d)[0];
      await ev.scene(head, `${esc(m.note)} Four of them, road-worn, arguing over a map.`, [
        { label: "Share a fire and swap news (3 h)", fx: () => ({ time: 3, thread: lead ? { title: `The party's lead: ${lead.x.name}`, steps: [{ text: `See the ${lead.x.name} for yourself`, goal: { marker: lead.x.i }, reward: { coin: 3 } }] } : null }), text: () => (lead ? `They tell you about the ${esc(lead.x.name)}, ${g.know.dirDist(s.c, s.r, lead.x.t).txt}, and mark it on your map.` : "They have nothing new.") },
        { label: "Move on", fx: null, text: "" }], `m${m.i}`);
    } },
    encounters: { run: async (ev, m, head) => {
      const g = ev.g, nm = g.know.person(`enc${m.i}`, g.w.C.culture[m.cell]);
      await ev.scene(`<b class="side">${esc(nm)}</b>, a stranger on the road ${AZ.T("new")}`, `The map marks a chance meeting here ${AZ.T("data")}.`, [
        { label: "Talk", fx: { time: 1 }, text: () => g.know.rumour(m.t[0], m.t[1], ev.rnd(`enc${m.i}`), g) || "They have little to say." }, { label: "Nod and pass", fx: null, text: "" }], `m${m.i}`);
    } },
    _default: { run: (ev, m, head) => lore(ev, m, head) },
  };
  T.jousts = T.circuses; T.fairs = T.circuses; T["sacred-pineries"] = T["sacred-forests"];
  return T;
})();

// zone scenes (type -> fn)
AZ.ZONES = (() => {
  const esc = AZ.U.esc;
  const blocked = (what, h) => async (ev, z, head) => ev.scene(head, what, [{ label: `Find another way (about ${h} hours)`, fx: { time: h }, text: "It takes most of a day to get round." }, { label: "Wait it out (twice that)", fx: { time: h * 2 }, text: "You wait, and watch others try their luck." }], `z${z.i}`);
  return {
    Disease: async (ev, z, head) => ev.scene(head, "Sickness in these parts: shuttered doors, smoke from burning bedding.", [
      { label: "Keep away from people (about 6 hours lost)", fx: { time: 6 }, text: "You skirt every village and drink only what you carry." },
      { label: "Use the flask from the spring", if: !!ev.s.flags.flask, fx: { unflag: "flask" }, text: "You drink nothing else until you are clear of it." },
      { label: "Go on as you are", roll: { p: 0.5, ok: "You pass through and feel nothing worse than worry.", okFx: null, bad: "Two days on, the fever finds you. A priest, a healing spring or two days' rest will break it.", badFx: { cond: "fever" } } }], `z${z.i}`),
    Invasion: async (ev, z, head) => {
      const g = ev.g, inv = ev.stateByPrefix(z.name), rel = inv ? g.know.rel(g.tv.homeState, inv.i) : "Unknown";
      const enemy = rel === "Enemy" || rel === "Rival";
      return ev.scene(head, `${inv ? `Soldiers of ${esc(inv.fullName)}` : "An army"} hold this ground. Your people stand to theirs as: <b>${rel}</b> ${AZ.T("data")}.`, [
        { label: "Go round their pickets (about 8 hours)", fx: { time: 8 }, text: "You move by night and by the long way." },
        { label: "Present yourself and your papers", fx: enemy ? { time: 12, coin: -Math.min(ev.s.purse, 4), stand: inv ? [["s", inv.i, -1]] : [] } : { time: 2 }, text: enemy ? "They hold you half a day and keep some of your coin for their trouble." : "Questions, a stamp, and a wave onward." }], `z${z.i}`);
    },
    Rebels: async (ev, z, head) => ev.scene(head, "Rebels have closed the roads and levy their own toll.", [{ label: "Pay the toll (🟡 4)", disabled: ev.s.purse < 4, fx: { coin: -4 }, text: "They give you a token to show at the next barricade." }, { label: "Go round (about 6 hours)", fx: { time: 6 }, text: "" }], `z${z.i}`),
    Proselytism: async (ev, z, head) => {
      const r = ev.relByName(z.name) || ev.w.P.religions.find(x => x && x.name.split(" ")[0] === z.name.split(" ")[0]);
      return ev.scene(head, `Missionaries${r ? ` of the ${esc(r.name)}` : ""} are working these parts, with bread for anyone who will listen.`, [
        { label: "Take their bread and blessing", fx: r ? { stand: [["f", r.i, 1]], flag: `debt:${r.i}`, time: 1 } : { time: 1 }, text: "You owe them now, and they will remember it." },
        { label: "Politely refuse", fx: null, text: "They let you go, with a look." }], `z${z.i}`);
    },
    Crusade: async (ev, z, head) => ev.scene(head, "Armed pilgrims and recruiters for a crusade crowd the way.", [{ label: "Join a prayer and move on (2 h)", fx: { time: 2 }, text: "No one asks what you believe, as long as you kneel." }, { label: "Avoid them (about 4 hours)", fx: { time: 4 }, text: "" }], `z${z.i}`),
    Disaster: async (ev, z, head) => {
      const cell = ev.w.cell(ev.s.c, ev.s.r), rel = ev.w.C.religion[cell];
      return ev.scene(head, "Dearth: empty granaries, thin children, prices no one can pay.", [{ label: "Give alms (🟡 2)", disabled: ev.s.purse < 2, fx: { coin: -2, stand: rel ? [["f", rel, 1]] : [] }, text: "It is not much, and it is noticed." }, { label: "Pass by", fx: null, text: "" }], `z${z.i}`);
    },
    Eruption: async (ev, z, head) => ev.scene(head, "Ash falls like grey snow; the sky glows red at night.", [{ label: ev.s.aboard ? "Stand out to sea (about 6 hours)" : "Cover your face and push on (about 10 hours)", fx: { time: ev.s.aboard ? 6 : 10 }, text: "" }, { label: "Shelter until it eases (a day)", fx: { time: 24 }, text: "" }], `z${z.i}`),
    Avalanche: blocked("The pass is buried under a slide of snow and rock.", 10),
    Fault: blocked("The ground has split; the road ends in a raw cliff.", 6),
    Flood: blocked("The rivers are over their banks; fords and bridges are gone.", 12),
    Tsunami: async (ev, z, head) => ev.scene(head, ev.s.aboard ? "A great swell runs in from the open sea; wreckage floats everywhere." : "The wave came in and went out again. The shore is wreckage and mud.", [
      { label: ev.s.aboard ? "Ride it out (about 4 hours)" : "Help dig out survivors (8 h)", fx: () => (ev.s.aboard ? { time: 4 } : { time: 8, stand: ev.w.C.state[ev.w.cell(ev.s.c, ev.s.r)] ? [["s", ev.w.C.state[ev.w.cell(ev.s.c, ev.s.r)], 1]] : [] }), text: "" },
      { label: "Keep going", fx: null, text: "" }], `z${z.i}`),
    _default: async (ev, z, head) => ev.g.ui.say(head),
  };
})();
