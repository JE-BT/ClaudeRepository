// ---------------------------------------------------------------------------------------------
// Stretching stores, and life aboard.
//   Fishing (mixed rule on data): a catch per fisher per six hours, better in coastal shallows
//   than open water, up to two and a half times better where the cell or a neighbour holds an aquatic resource
//   (Fish, Whales, Pearls in the map's goods), worse in rain, impossible in a storm. A boat's crew
//   fish too.
//   Foraging (mixed rule on data): the biome's habitability, the cell's own food output (the
//   rural production the converter computed with Azgaar's formula), the season and the weather.
//   Shipboard events: on a booked ship, now and then, drawn from the captain's flag and culture,
//   the ports on the itinerary and the faiths aboard. AZ.SHIP_EVENTS.rate is the daily chance.
// ---------------------------------------------------------------------------------------------
AZ.SHIP_EVENTS = { rate: 0.18 };

Object.assign(AZ.Game.prototype, {
  aquaticNear(cell) {
    const w = this.w, aq = new Set(w.P.goods.filter(g => (g.tags || []).includes("aquatic")).map(g => g.i));
    const has = c => aq.has(w.C.good[c]) || Object.keys(w.C.prod[String(c)] || {}).some(g => aq.has(+g) && w.C.type[c]);
    if (has(cell)) return 2;
    const x = w.C.cx[cell], y = w.C.cy[cell];
    // neighbouring cells: the cells under the 8 surrounding tiles at a cell's distance
    const [c0, r0] = w.tileAt(x, y);
    for (const [dc, dr] of [[10, 0], [-10, 0], [0, 10], [0, -10], [7, 7], [-7, -7], [7, -7], [-7, 7]]) {
      if (!w.inb(c0 + dc, r0 + dr)) continue;
      if (has(w.cell(c0 + dc, r0 + dr))) return 1;
    }
    return 0;
  },
  fishYield(c, r) {
    const w = this.w, s = this.s, U = AZ.U;
    const wx = AZ.Weather.at(w, c, r, s.clock);
    if (wx.kind === "storm") return { n: 0, why: "no one fishes in a storm" };
    const cell = w.cell(c, r), land = w.isLand(c, r);
    const waterHere = !land || w.bits(c, r).river;
    const adjWater = [[0, 1], [1, 0], [0, -1], [-1, 0]].some(([a, b]) => w.inb(c + a, r + b) && !w.isLand(c + a, r + b));
    if (!waterHere && !adjWater) return { n: 0, why: "no water to fish here" };
    const fishCell = !land ? cell : adjWater ? w.cell(...[[0, 1], [1, 0], [0, -1], [-1, 0]].map(([a, b]) => [c + a, r + b]).find(t => w.inb(...t) && !w.isLand(...t))) : cell;
    const shallow = land || w.h(c, r) >= 15 || [[0, 2], [2, 0], [0, -2], [-2, 0]].some(([a, b]) => w.isLand(c + a, r + b));
    const aq = this.aquaticNear(fishCell);
    const fishers = 1 + (s.aboard && s.vessel && !this.riding() ? s.vessel.crew || 0 : 0) + (this.tv.trait === "sea legs" ? 1 : 0);
    let per = (shallow ? 0.6 : 0.3) * (aq === 2 ? 2.5 : aq === 1 ? 1.6 : 1) * (land && w.bits(c, r).river ? 0.8 : 1) * (wx.kind === "rain" ? 0.8 : wx.kind === "snow" ? 0.6 : 1);
    const luck = 0.5 + U.rnd2(c, r, Math.floor(s.clock / 6));
    const n = Math.round(per * fishers * luck);
    const where = `${shallow ? "coastal shallows" : "open water"}${aq ? `, ${aq === 2 ? "rich" : "good"} grounds (the map's ${aq === 2 ? "resource here" : "resource nearby"})` : ""}`;
    return { n, fishers, where, why: "" };
  },
  forageYield(c, r) {
    const w = this.w, s = this.s, U = AZ.U;
    if (!w.isLand(c, r)) return { n: 0, why: "nothing to forage at sea" };
    const wx = AZ.Weather.at(w, c, r, s.clock);
    if (wx.kind === "storm") return { n: 0, why: "not in a storm" };
    const cell = w.cell(c, r), b = w.P.biomes[w.C.biome[cell]];
    const prod = w.C.prod[String(cell)] || {};
    let food = 0, game = false;
    for (const [g, u] of Object.entries(prod)) { const G = w.P.goods.find(x => x.i === +g); if ((G?.tags || []).includes("food")) { food += u; if (/game/i.test(G.name)) game = true; } }
    const season = AZ.Clock.season(w.latlon(c, r)[0], s.clock);
    const sf = { winter: 0.4, autumn: 0.8, spring: 0.9, summer: 1, "wet season": 1, "dry season": 0.6 }[season] ?? 1;
    const wf = { rain: 0.8, snow: 0.3, fog: 0.9 }[wx.kind] ?? 1;
    const per = ((b.habitability || 0) / 100) * 1.5 * (1 + Math.min(food, 8) / 3) * sf * wf + (game ? 0.5 : 0);
    const luck = 0.5 + U.rnd2(c, r, Math.floor(s.clock / 6) + 7);
    return { n: Math.round(per * luck), where: `${b.name}, habitability ${b.habitability}${food ? `, local food output ${U.rn(food, 1)}` : ""}${game ? ", game" : ""}; ${season}`, why: "" };
  },
  async provide(kind) {
    const s = this.s, U = AZ.U;
    const y = kind === "fish" ? this.fishYield(s.c, s.r) : this.forageYield(s.c, s.r);
    if (y.why) return this.ui.say(`You cannot: ${y.why}.`);
    s.clock += 6;
    this.awakeTick(6);
    s.sup.food += y.n;
    if (y.n > 0) { s.hunger = 0; delete s.cond.hungry; delete s.cond.starving; }
    this.log(`${kind === "fish" ? "Fished" : "Foraged"} six hours: ${y.n} ration${y.n === 1 ? "" : "s"}.`);
    this.dirty = true;
    return this.ui.say(`${kind === "fish" ? `Six hours with lines and nets${y.fishers > 1 ? `, ${y.fishers} of you` : ""}` : "Six hours of gathering, snaring and digging"}: <b>${y.n} ration${y.n === 1 ? "" : "s"}</b>. ${U.cap(y.where)} ${AZ.T("mixed")}.`);
  },
  // ------------------------------------------------------------------ life aboard a booked ship
  async shipEvent() {
    const s = this.s, v = s.voyage, w = this.w, U = AZ.U, T = AZ.T, P = w.P;
    if (!v || !s.aboard || v.state !== "sea") return;
    const day = Math.floor(s.clock / 24), rnd = U.rng(`${s.seed}:aboard:${day}`);
    const flag = P.states[v.flag], capCul = P.cultures[w.C.culture[P.burgs[v.from]?.cell]] || P.cultures[1];
    const ports = v.stops.map(x => P.burgs[x.b]).filter(Boolean);
    const paxPort = rnd.pick([P.burgs[v.from], ...ports].filter(Boolean));
    const paxCul = paxPort.culture, paxRel = w.C.religion[paxPort.cell];
    const pax = this.know.person(`pax:${day}:${v.ship}`, paxCul);
    const stance = flag ? this.know.rel(this.tv.homeState, flag.i) : "Unknown";
    const home = P.burgs[v.from], galley = U.rn(AZ.Prices.ration(w, home) * 1.6, 2);
    const kinds = [
      { wt: 2, run: () => this.events.scene(`<b>The cook</b> of ${U.esc(v.ship)}`, `He has hard tack and salt fish to spare, at sea prices: 🟡 ${galley} a ration, half again what ${U.esc(home?.name || "port")} charged ${T("mixed")}.`,
        [{ label: `Buy 5 rations (🟡 ${U.rn(galley * 5, 1)})`, disabled: s.purse < galley * 5, fx: { coin: -U.rn(galley * 5, 2) }, text: "Dry, salty, and enough." }, { label: "No, thank you", fx: null, text: "" }], `cook${day}`).then(k => { if (k === 0) s.sup.food += 5; }) },
      { wt: 2, run: async () => { const rm = this.know.rumour(s.c, s.r, rnd, this); await this.ui.say(`<b class="side">${U.esc(pax)}</b>, a passenger from ${U.esc(paxPort.name)} (${U.esc(P.cultures[paxCul].name)}, of the ${U.esc(P.religions[paxRel]?.name || "old ways")}) ${T("data")}, talks the evening away.${rm ? ` “${rm}` : ""}`); } },
      { wt: paxRel === this.tv.faith ? 2 : 0.5, run: () => this.events.scene(`<b class="side">${U.esc(pax)}</b> keeps the ${U.esc(P.religions[paxRel]?.name || "old ways")}`, paxRel === this.tv.faith ? "You find you share a faith, and the evening prayers." : "They pray at dawn on the open deck and ask if you will join.",
        [{ label: "Pray with them", fx: { stand: [["f", paxRel, 1]] }, text: "It costs nothing, and someone remembers it." }, { label: "Keep to yourself", fx: null, text: "" }], `pray${day}`) },
      { wt: 1.5, run: () => this.events.scene("<b>Dice on the main deck</b>", `${U.esc(capCul.name)} sailors' rules ${T("data")}; nobody explains them twice.`,
        [{ label: "Stake 🟡 1", disabled: s.purse < 1, roll: { p: 0.45, ok: "You win, to some grumbling.", okFx: { coin: 1 }, bad: "You lose, to some laughter.", badFx: { coin: -1 } } },
         { label: "Stake 🟡 5", disabled: s.purse < 5, roll: { p: 0.45, ok: "You win, and the deck goes quiet.", okFx: { coin: 5 }, bad: "You lose. They are kinder about it than you expect.", badFx: { coin: -5 } } }, { label: "Watch", fx: null, text: "" }], `dice${day}`) },
      { wt: 1, run: () => this.events.scene("<b>Fever in the forecastle</b>", "Two of the crew are down with it, and the passengers sleep close.",
        [{ label: `Pay the surgeon for a draught (🟡 ${AZ.Prices.heal(w, home)})`, disabled: s.purse < AZ.Prices.heal(w, home), fx: { coin: -AZ.Prices.heal(w, home) }, text: "It tastes of iron and you stay well." },
         { label: "Take your chances", roll: { p: 0.65, ok: "You stay well.", okFx: null, bad: "By the next port you are fevered.", badFx: { cond: "fever" } } }], `fever${day}`) },
      { wt: flag ? 1.5 : 0, run: async () => {
        const friendly = /Ally|Friendly/.test(stance), hostile = /Enemy|Rival|Suspicion/.test(stance);
        const text = friendly ? `${U.esc(v.captain)} learns where you are from and asks you to his table: your people and ${U.esc(flag.name)} stand as “${stance}” ${T("data")}. Three days of his stores.` :
          hostile ? `${U.esc(v.captain)} learns where you are from and does not like it: your people and ${U.esc(flag.name)} stand as “${stance}” ${T("data")}. You are watched, and the cook forgets you.` :
          `${U.esc(v.captain)} drinks to ${U.esc(flag.fullName)} ${T("data")} and does not ask where you are from.`;
        if (friendly) s.sup.food += 3; else if (hostile) s.sup.food = Math.max(0, s.sup.food - 1);
        await this.ui.say(text);
      } },
      { wt: 1, run: async () => { const h = 3 + Math.round(rnd() * 5); s.clock += h; await this.ui.say(`A squall comes over the sea and the ship lies to for ${h} hours ${T("mixed")}.`); } },
      { wt: this.canCrew() && v.role === "passenger" ? 1.5 : 0, run: () => this.events.scene("<b>The mate is short-handed</b>", "He has seen you handle a line. Stand a watch for the rest of the voyage, and draw a hand's pay?",
        [{ label: "Stand a watch", fx: null, text: "You sleep less and are paid for it." }, { label: "You paid for your passage", fx: null, text: "" }], `mate${day}`).then(k => { if (k === 0) v.role = "crew"; }) },
    ];
    let roll = rnd() * kinds.reduce((a, k) => a + k.wt, 0);
    for (const k of kinds) if ((roll -= k.wt) <= 0) { await k.run(); break; }
    this.dirty = true;
  },
});

// R: rest, wait, fish or forage
AZ.Game.prototype.rest = async function () {
  const s = this.s, U = AZ.U, w = this.w;
  if (this.riding()) return this.shipTalk();
  const sick = s.cond.fever || s.cond.gravely || s.cond.hurt;
  const atSea = s.aboard && !w.isLand(s.c, s.r);
  const fy = this.fishYield(s.c, s.r), fo = !s.aboard ? this.forageYield(s.c, s.r) : { why: "aboard" };
  const opts = [
    { id: "dawn", label: atSea ? "Anchor until dawn" : "Camp until dawn" },
    { id: "fish", label: fy.why ? `Fish (${fy.why})` : `Fish for six hours (${fy.fishers > 1 ? `${fy.fishers} of you, ` : ""}${fy.where})`, disabled: !!fy.why },
    { id: "forage", label: fo.why ? "Forage (only on land)" : `Forage and hunt for six hours (${fo.where})`, disabled: !!fo.why },
    { id: 1, label: "Wait 1 hour" }, { id: 3, label: "Wait 3 hours" }, { id: 6, label: "Wait 6 hours" },
    { id: "two", label: "Two days, to recover", disabled: !sick }, { id: "no", label: "Never mind" }];
  const k = await this.ui.choose(atSea ? "Heave to, anchor, or put lines over?" : "Make camp, wait, or look for food?", opts, { cancel: opts.length - 1 });
  const o = opts[k];
  if (o.id === "no") return;
  if (o.id === "fish" || o.id === "forage") return this.provide(o.id);
  const t0 = s.clock;
  if (o.id === "two") { this.events.fx({ time: 48, cure: ["fever", "gravely", "hurt"] }, "Rested two days."); this.slept(); this.ui.toast("Two days' rest. You feel yourself again."); return; }
  if (o.id === "dawn" && !s.aboard) return this.campNight();
  if (o.id === "dawn") {
    s.clock = AZ.Clock.nextDawn(s.clock, this.lat());
    this.slept();
    if (s.vessel) { s.vessel.anchored = true; s.vessel.morale = Math.min(100, (s.vessel.morale || 70) + 4); s.vessel.nightKey = Math.floor((s.clock + 12) / 24); }
    const act = this.doAct("anchor");
    if (act) this.ui.toast(`<span class="hook">★ ${U.esc(act.label)}</span>`, "gold");
  } else { s.clock += o.id; if (o.id >= 6) this.slept(); }
  this.ui.toast(`${AZ.Clock.span(s.clock - t0)} pass. ${AZ.Clock.fmt(s.clock)}.`);
  this.dirty = true;
};
