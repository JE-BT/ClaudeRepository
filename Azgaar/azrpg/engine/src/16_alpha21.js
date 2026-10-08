// ---------------------------------------------------------------------------------------------
// Alpha 2.1
//   Journeys by archetype (the map's journey type: Quest, Caravan, Pilgrimage ...): the framing,
//   the travellers and the companions met at a Gathering follow it; new stop types (Gathering,
//   Rumours, Waiting for a ship, Resupply, Camp) are things to do, with people to do them with.
//   Sandbox: the same world without a journey, dynamic or static.
//   Moving targets are found by their last known position and by tracks, not by magic.
//   Camping depends on where you camp; storms on how far you are from land; portals cost.
// ---------------------------------------------------------------------------------------------
AZ.ARCH = {
  Pilgrimage: { noun: "pilgrimage", party: 2, roles: ["fellow pilgrim", "guide"], role: "Pilgrim" },
  Quest: { noun: "quest", party: 3, roles: ["sword-for-hire", "guide", "healer"], role: "Questing adventurer" },
  Caravan: { noun: "caravan", party: 4, roles: ["caravan master", "guard", "drover", "cook"], role: "Caravan hand" },
  "Military campaign": { noun: "campaign", party: 4, roles: ["sergeant", "scout", "surgeon", "quartermaster"], role: "Soldier on campaign" },
  Embassy: { noun: "embassy", party: 3, roles: ["ambassador", "secretary", "guard"], role: "Member of the embassy" },
  Raid: { noun: "raid", party: 4, roles: ["raider", "scout", "steersman"], role: "Raider" },
  "Smuggling run": { noun: "smuggling run", party: 2, roles: ["fence", "lookout"], role: "Smuggler" },
  "Courier ride": { noun: "ride", party: 0, roles: [], role: "Courier" },
  Expedition: { noun: "expedition", party: 3, roles: ["surveyor", "naturalist", "porter"], role: "Expedition member" },
  "Refugee flight": { noun: "flight", party: 3, roles: ["elder", "neighbour", "child"], role: "Refugee" },
  "Treasure hunt": { noun: "treasure hunt", party: 2, roles: ["map-reader", "digger"], role: "Treasure hunter" },
  "Monster hunt": { noun: "hunt", party: 3, roles: ["tracker", "hunter", "trapper"], role: "Monster hunter" },
  "Exile's flight": { noun: "exile", party: 1, roles: ["loyal servant"], role: "Exile" },
  "Royal progress": { noun: "progress", party: 4, roles: ["courtier", "herald", "guard", "chamberlain"], role: "Courtier" },
  "Airship voyage": { noun: "voyage", party: 3, roles: ["aeronaut", "rigger", "navigator"], role: "Aeronaut" },
  "Arcane errand": { noun: "errand", party: 1, roles: ["apprentice"], role: "Apprentice of the arcane" },
  "Mercenary contract": { noun: "contract", party: 4, roles: ["captain of the company", "sergeant", "archer"], role: "Mercenary" },
  Wandering: { noun: "wandering", party: 0, roles: [], role: "Wanderer" },
};
AZ.archOf = jr => {
  if (!jr) return "Wandering";
  const t = jr.J.type;
  if (t && AZ.ARCH[t]) return t;
  return Object.keys(AZ.ARCH).find(k => new RegExp(`\\b${k.split(" ")[0]}`, "i").test(jr.J.name)) || "Quest";
};
AZ.noun = jr => AZ.ARCH[AZ.archOf(jr)].noun;
// "Culzan and the road through the forest": a name that is no place, state or culture is the leader
AZ.journeyLeader = (w, jr) => {
  const m = jr && jr.J.name.match(/^([\p{Lu}][\p{L}'’-]+)\s+(and|with|of)\s/u);
  if (!m) return null;
  const n = m[1].toLowerCase(), P = w.P;
  const taken = [...P.burgs, ...P.states, ...P.cultures, ...P.religions, ...P.provinces].some(x => x && x.name && x.name.toLowerCase() === n);
  return taken ? null : m[1];
};
AZ.TRAITS = {
  "long-legged": { label: "long-legged", text: "you walk faster than most (+15%)" },
  haggler: { label: "a haggler", text: "you buy 10% cheaper and sell 10% dearer" },
  "sea legs": { label: "sea legs", text: "you can work a passage, and you fish better" },
  hardy: { label: "hardy", text: "hunger and fever bite less" },
  "well-connected": { label: "well-connected", text: "news reaches you faster, and errands pay a fifth more" },
};

(() => {
  const G = AZ.Game.prototype, U = AZ.U, T = AZ.T;
  // ------------------------------------------------------------------ riding a booked vessel vs your own
  G.riding = function () { const s = this.s, v = s && s.voyage; return !!(v && s.aboard && (v.state === "sea" || v.boarded)); };

  // ------------------------------------------------------------------ travellers: archetype, sandbox, traits
  const kinds0 = AZ.travellerKinds;
  AZ.travellerKinds = function (w, jr) {
    const kinds = kinds0(w, jr);
    const arch = AZ.archOf(jr);
    if (!jr || arch === "Pilgrimage") return kinds;
    const A = AZ.ARCH[arch], noun = A.noun, oB = jr.origin.burg, dB = jr.dest.burg, C = w.C;
    const leader = AZ.journeyLeader(w, jr);
    const out = kinds.filter(k => k.id !== "convert").map(k => {
      const why0 = k.why;
      const k2 = { ...k, why: h => (why0 ? why0(h) : k.blurb).replace(/pilgrimage/g, noun).replace(/you are going home to make the \w+ you were promised as a child/, `the ${noun} takes you home`) };
      if (k.id === "returning") { k2.label = `Native of ${w.P.states[dB.state]?.name || dB.name}`; k2.blurb = `Born in ${w.P.states[dB.state]?.name || dB.name}; the ${noun} takes you home.`; k2.why = h => `you were born in ${h.name}, and the ${noun} takes you home`; k2.thread = null; }
      return k2;
    });
    out.unshift({ id: "arch", label: A.role, wt: 5, culture: C.culture[oB.cell], faith: C.religion[oB.cell], homes: [oB],
      blurb: `${leader ? `${leader}'s ${noun}` : `The ${noun}`}: ${jr.J.name} ${"(the map's journey)"}.`,
      trades: A.roles.length ? A.roles : ["traveller"],
      why: () => `you have joined ${leader ? `${leader}'s` : "the"} ${noun}, “${jr.J.name}”, from ${oB.name} to ${dB.name}`, thread: null });
    return out;
  };
  AZ.sandboxKinds = function (w, b) {
    const P = w.P, C = w.C, out = [], cul = b.culture, rel = C.religion[b.cell];
    out.push({ id: "native", label: `Native of ${b.name}`, wt: 3, culture: cul, faith: rel, homes: [b], blurb: `${P.cultures[cul].name}, of the ${P.religions[rel]?.name}.`, trades: ["farmhand", "clerk", "carter", "weaver"], why: () => `you grew up in ${b.name}, and everything beyond it is rumour`, purse: 40 });
    const sells = Object.keys(P.trade.sell[b.i] || {});
    if (sells.length) out.push({ id: "merchant", label: `Merchant of ${b.name}`, wt: 2, culture: cul, faith: rel, homes: [b], cargo: +sells[0], blurb: `You deal in what ${b.name} makes.`, trades: ["merchant", "pedlar", "factor"], why: () => `you deal in what ${b.name} makes, and the world is your market`, purse: 80 });
    const st = P.states[b.state];
    if (st && (st.campaigns || []).some(c => c.end == null)) out.push({ id: `soldier:${b.state}`, label: `Soldier of ${st.name}`, wt: 1.5, culture: cul, faith: rel, homes: [b], homeState: b.state, blurb: `${st.name} is at war.`, trades: ["archer", "sergeant", "scout"], why: () => `you serve ${st.fullName}, which is at war`, purse: 30 });
    const R = P.religions[rel], seat = R && P.burgs.find(x => x && x.cell === R.center);
    if (seat && seat !== b) out.push({ id: "pilgrim", label: `Pilgrim bound for ${seat.name}`, wt: 1.5, culture: cul, faith: rel, homes: [b], blurb: `${seat.name} is the seat of your faith.`, trades: ["pilgrim", "lay brother", "widow"], why: () => `you keep the ${R.name}, and you have always meant to see ${seat.name}`, thread: { title: `To ${seat.name}`, steps: [{ text: `Pray at the temple in ${seat.name}`, goal: { burg: seat.i, role: "Priest" }, reward: { stand: [["f", rel, 2]] } }] }, purse: 30 });
    if (b.port) out.push({ id: "shipmaster", label: `Shipmaster of ${b.name}`, wt: 1, culture: cul, faith: rel, homes: [b], boat: true, blurb: "You own a sailing boat.", trades: ["shipmaster", "coasting skipper"], why: () => `you own a sailing boat in ${b.name}`, purse: 25 });
    out.push({ id: "wanderer", label: "Wanderer", wt: 1, culture: cul, faith: rel, homes: [b], blurb: "No ties, no plan.", trades: ["tinker", "minstrel", "beggar", "tracker"], why: () => `you left home long ago and have not stopped since`, purse: 20 });
    return out;
  };
  const make0 = AZ.makeTraveller;
  AZ.makeTraveller = function (w, jr, seed, kindId, start) {
    let tv;
    if (!jr) {
      const b = w.P.burgs[start] || w.P.burgs.find(x => x && x.capital);
      const kinds = AZ.sandboxKinds(w, b), rnd = U.rng(seed);
      let K = kinds.find(k => k.id === kindId);
      if (!K) { let roll = rnd() * kinds.reduce((a, k) => a + k.wt, 0); K = kinds[0]; for (const k of kinds) if ((roll -= k.wt) <= 0) { K = k; break; } } else rnd();
      const cul = w.P.cultures[K.culture], rel = w.P.religions[K.faith];
      const cloak = U.shade(U.hex2rgb(cul.color || "#806040"), -0.35), deity = (rel?.deity || "").split(",")[0];
      tv = { seed, kind: K.id, kindLabel: K.label, name: w.names.get(cul.base, rnd), age: 18 + Math.floor(rnd() * 44), culture: K.culture, faith: K.faith, home: b.i, homeState: K.homeState ?? b.state,
        trade: rnd.pick(K.trades), why: K.why(b), token: deity ? `a small icon of ${deity}` : "a keepsake from home", purse: K.purse, thread: K.thread || null, cargo: K.cargo ?? null, boat: !!K.boat, food: 3, kindId: K.id,
        pal: { cloak: U.css(cloak), cloakDark: U.css(U.shade(cloak, -0.35)), skin: rnd.pick(["rgb(240,204,170)", "rgb(214,170,130)", "rgb(176,124,88)", "rgb(124,84,58)"]), belt: "rgb(150,110,60)" } };
    } else tv = make0(w, jr, seed, kindId);
    // variety: purse and one trait, seeded with the traveller
    const r2 = U.rng(`${seed}:trait`);
    tv.purse = Math.max(5, Math.round(tv.purse * (0.6 + 0.8 * r2())));
    const pool = Object.keys(AZ.TRAITS);
    tv.trait = /deck|net|fish|cook|shipmaster|skipper|steersman/i.test(tv.trade) ? "sea legs" : /soldier|archer|sergeant|scout|raider|mercenary/i.test(tv.kindLabel + tv.trade) && r2() < 0.5 ? "hardy" : pool[Math.floor(r2() * pool.length)];
    return tv;
  };
  const canCrew0 = G.canCrew;
  G.canCrew = function () { return this.tv.trait === "sea legs" || canCrew0.call(this); };

  // ------------------------------------------------------------------ modes, saves, sandbox
  Object.defineProperty(G, "key", { get() { return `azrpg3:${this.w.P.world.seed}:${this.mode === "sandbox" ? "sandbox" : this.jr0 ? this.jr0.J.name : "free"}`; }, set() {}, configurable: true });
  const fresh15 = G.fresh;
  G.fresh = function (seed, kindId, doy0, opts = {}) {
    this.jr0 = this.jr0 || this.jr;
    this.mode = opts.mode || "journey";
    this.jr = this.mode === "sandbox" ? null : this.jr0;
    this._start = opts.start;
    fresh15.call(this, seed, kindId, doy0);
    Object.assign(this.s, { mode: this.mode, start: opts.start ?? null, static: !!opts.static, party: [], foodTaken: {} });
    if (opts.static) { this.sim = AZ.sim = null; }
    if (this.mode === "sandbox" && opts.start != null) { const b = this.w.P.burgs[opts.start]; this.s.c = b.t[0]; this.s.r = b.t[1]; this.s.cp = 0; this.reveal(); }
    if (this.tv.boat && this.mode === "sandbox") { const b = this.w.P.burgs[opts.start], h = b && this.w.harbour(b, "boat"); if (h) this.s.vessel = { mode: "owned", kind: "Sailing boat", cls: "boat", speed: 6, hpd: 12, crew: 3, morale: 80, c: h.t[0], r: h.t[1], wage: AZ.Prices.wage(this.w, b), hire: 0, home: b.i }; }
  };
  const load15 = G.loadGame;
  G.loadGame = function (mode) {
    this.jr0 = this.jr0 || this.jr;
    this.mode = mode || "journey";
    this.jr = this.mode === "sandbox" ? null : this.jr0;
    const ok = load15.call(this);
    if (!ok) return false;
    if (this.s.static) this.sim = AZ.sim = null;
    this.tv = AZ.makeTraveller(this.w, this.jr, this.s.seed, this.s.kind, this.s.start);
    this.know = new AZ.Know(this.w, this.jr, this.tv);
    this.s.party = this.s.party || []; this.s.foodTaken = this.s.foodTaken || {};
    return true;
  };
  G.hasSaveFor = function (mode) { const m0 = this.mode; this.mode = mode; const k = this.key; this.mode = m0; try { return !!this.store.getItem(k); } catch (e) { return false; } };

  G.title = async function (fromMenu) {
    const w = this.w, jr = this.jr0 || this.jr;
    this.jr0 = jr;
    const head = `<div class="logo">${U.esc(jr ? jr.J.name : w.P.world.name)}</div><div class="sub">${U.esc(w.P.world.name)} (${U.esc(w.P.world.folder)}) · year ${w.W.calendar?.year || "?"} ${U.esc(w.W.calendar?.era || "")}</div>`;
    const foot = `<div class="dim">${U.num(w.cols)} × ${U.num(w.rows)} tiles of ${U.num(w.miles, 2)} mi · ${U.esc(w.P.grid.source)}</div>`;
    for (;;) {
      const a = await this.pickList(head, [
        { id: "journey", html: jr ? `Journey: ${U.esc(jr.J.name)}<div class="dim small">${U.esc(AZ.archOf(jr))}, from ${U.esc(jr.origin.name)} to ${U.esc(jr.dest.name)}, with checkpoints and par</div>` : `Journey <span class="dim small">(no journey in this map)</span>`, disabled: !jr },
        { id: "sandbox", html: `Sandbox<div class="dim small">The same world without a journey: trade, errands, wandering</div>` },
        { id: "cont-j", html: "Continue the saved journey", disabled: !jr || !this.hasSaveFor("journey") },
        { id: "cont-s", html: "Continue the saved sandbox", disabled: !this.hasSaveFor("sandbox") },
        { id: "help", html: "How to play" }], foot);
      if (a === "help") { await new Promise(r => { this.help(); this.ui.onModalClose = r; }); continue; }
      if (a === "cont-j" || a === "cont-s") { this.ui.closeModal(); if (this.loadGame(a === "cont-j" ? "journey" : "sandbox")) { this.started(); this.ui.toast(`Welcome back, ${U.esc(this.tv.name)}.`); return; } continue; }
      if (a !== "journey" && a !== "sandbox") continue;
      const opts = { mode: a };
      if (a === "sandbox") {
        const world = await this.pickList(`${head}<div class="sub">The world</div>`, [{ id: "dyn", html: `Moving<div class="dim small">markets, lines, disease and war run on</div>` }, { id: "static", html: `Still<div class="dim small">the map as saved, as in alpha 1</div>` }, { id: "back", html: "Back" }]);
        if (world === "back" || world === null) continue;
        opts.static = world === "static";
        const towns = w.P.burgs.filter(b => b && !b.removed).sort((x, y) => y.population - x.population).slice(0, 8);
        const st = await this.pickList(`${head}<div class="sub">Where do you start?</div>`, [{ id: "rnd", html: "Let chance decide" }, ...towns.map(b => ({ id: b.i, html: `${U.esc(b.name)} <span class="dim small">${U.esc(b.group)}, ${U.esc(w.P.states[b.state]?.name || "unclaimed")}, ${U.si(b.population * 1000)}</span>` })), { id: "back", html: "Back" }]);
        if (st === "back" || st === null) continue;
        const pool = w.P.burgs.filter(b => b && !b.removed && b.population > 1);
        opts.start = st === "rnd" ? pool[Math.floor(Math.random() * pool.length)].i : st;
      }
      const jrX = a === "sandbox" ? null : jr;
      const kinds = jrX ? AZ.travellerKinds(w, jrX) : AZ.sandboxKinds(w, w.P.burgs[opts.start]);
      const kind = await this.pickList(`${head}<div class="sub">Who travels? ${T("mixed")} Each kind is found in this map's data.</div>`,
        [{ id: "__random", html: "Let chance decide" }, ...kinds.map(k => ({ id: k.id, html: `${U.esc(k.label)}<div class="dim small">${U.esc(k.blurb)}</div>` })), { id: "__back", html: "Back" }]);
      if (kind === null || kind === "__back") continue;
      let seed = (Date.now() ^ Math.floor(Math.random() * 1e9)) >>> 0;
      const doys = [80, 172, 266, 355]; let di = 0;
      const lat0 = jrX ? w.latlon(...jrX.origin.tile)[0] : w.latlon(...w.P.burgs[opts.start].t)[0];
      for (;;) {
        const tv = AZ.makeTraveller(w, jrX, seed, kind === "__random" ? null : kind, opts.start);
        AZ.Clock.doy0 = doys[di];
        const card = `<div class="card win"><div class="who">${U.esc(tv.kindLabel)} ${T("new")}</div><b>${U.esc(tv.name)}</b>, ${tv.age}, ${U.esc(tv.trade)} · ${U.esc(w.P.cultures[tv.culture].name)} · ${U.esc(w.P.religions[tv.faith]?.name || "no faith")}<br>${U.cap(U.esc(tv.why))}.<br><span class="dim">Purse 🟡 ${tv.purse} · ${U.esc(AZ.TRAITS[tv.trait].label)}: ${U.esc(AZ.TRAITS[tv.trait].text)}${tv.thread ? ` · side story: <span class="side">${U.esc(tv.thread.title)}</span>` : ""}${a === "sandbox" ? ` · ${opts.static ? "still world" : "moving world"}` : ""}</span></div>`;
        const items = [{ id: "begin", html: "Begin" }, { id: "roll", html: "Another traveller like this" },
          { id: "season", html: `Start: ${AZ.Clock.season(lat0, 6)} (${Math.round(AZ.Clock.dayLength(lat0, doys[di]))} h of daylight) ◀ ▶`, cycle: d => { di = (di + d + 4) % 4; } }, { id: "back", html: "Back" }];
        const r = await this.pickList(head + card, items, "", this._sel || 0);
        this._sel = r === "__cycle" || r === "season" ? 2 : 0;
        if (r === "roll") { seed = (seed * 1664525 + 1013904223) >>> 0; continue; }
        if (r === "__cycle") continue;
        if (r === "season") { di = (di + 1) % 4; continue; }
        if (r === "begin") {
          this.ui.closeModal(); this.fresh(seed, tv.kind, doys[di], opts); this.started(); this.saveGame();
          if (this.jr) await this.ui.say(this.know.intro(this));
          else await this.ui.say([`<b>Sandbox</b> · ${opts.static ? "a still world" : "a moving world"} ${T("mixed")}`, `You are ${U.esc(this.tv.name)}, ${this.tv.age}, ${U.esc(this.tv.trade)}. ${U.cap(U.esc(this.tv.why))} ${T("new")}.`, `You stand in ${U.esc(w.P.burgs[opts.start].name)}. Notice boards, markets, harbours and coach offices are in every town (Space). Nothing is required of you.`]);
          if (this.tv.thread) this.ui.toast(`Side story: <b class="side">${U.esc(this.tv.thread.title)}</b>`, "teal");
          return;
        }
        if (r === "back" || r === null) break;
      }
    }
  };

  // ------------------------------------------------------------------ the journey's framing and stops
  const intro0 = AZ.Know.prototype.intro;
  AZ.Know.prototype.intro = function (g) {
    const jr = this.jr, arch = AZ.archOf(jr);
    if (arch === "Pilgrimage") return intro0.call(this, g);
    const w = this.w, P = w.P, tv = this.tv, o = jr.origin.burg, d = jr.dest.burg, leader = AZ.journeyLeader(w, jr);
    const first = jr.cps[0].acts[0];
    return [`<b class="hook">${U.esc(jr.J.name)}</b> · ${U.esc(arch)} ${T("data")}`,
      `You are ${U.esc(tv.name)}, ${tv.age}, ${U.esc(tv.trade)} ${T("new")}. ${U.cap(U.esc(tv.why))} ${T("mixed")}.`,
      o ? `You stand in ${U.esc(o.name)}, ${U.esc(o.group)} of ${U.esc(P.states[o.state]?.fullName || "unclaimed land")} ${T("data")}.` : "",
      d ? `The road ends in ${U.esc(d.name)}, ${U.num(jr.totalMiles)} miles by the plan in ${Math.round((jr.planEnd - jr.t0) / 24)} days ${T("mixed")}${leader ? `. ${U.esc(leader)} leads; the name is the journey's own ${T("data")}` : ""}.` : "",
      first ? `<b class="hook">First: ${U.esc(first.label)}.</b> Press Space on the town.` : ""].filter(Boolean);
  };
  const fin0 = G.finish;
  G.finish = async function (msg) {
    const say0 = this.ui.say.bind(this.ui), noun = AZ.noun(this.jr);
    this.ui.say = (pages, who) => say0((Array.isArray(pages) ? pages : [pages]).map(p => p.replace("The pilgrimage is complete.", `The ${noun} is complete.`)), who);
    try { await fin0.call(this, msg); } finally { this.ui.say = say0; }
  };
  const doActIn0 = G.doActInTown;
  G.doActInTown = async function (id, b) {
    if (id === "gather") return this.gather(b);
    if (id === "rumours") return this.rumoursHere(b);
    if (id === "resupply") return this.market(b);
    return doActIn0.call(this, id, b);
  };
  G.gather = async function (b) {
    const s = this.s, w = this.w, jr = this.jr, arch = AZ.archOf(jr), A = AZ.ARCH[arch], noun = A.noun;
    const leader = AZ.journeyLeader(w, jr), rnd = U.rng(`${s.seed}:party`);
    if (!s.party.length) {
      if (leader) s.party.push({ name: leader, role: "leader" });
      for (let i = 0; i < A.party; i++) s.party.push({ name: this.know.person(`party:${s.seed}:${i}`, rnd() < 0.7 ? b.culture : this.tv.culture), role: A.roles[i % A.roles.length] });
    }
    this.doAct("gather");
    const next = this.cpNext(), leg = next && next.legIn;
    const who = s.party.map(p => `<b>${U.esc(p.name)}</b> (${U.esc(p.role)})`).join(", ");
    await this.ui.say([`In ${U.esc(b.name)} the company gathers: ${who || "no one but you"} ${T("new")}.`,
      `${leader ? `${U.esc(leader)} leads the ${noun}` : `The ${noun} is yours to lead`}: “${U.esc(jr.J.name)}” ${T("data")}. ${U.esc(jr.dest.name)} is the end of it ${T("data")}.`,
      leg ? `The plan from here: ${U.esc(leg.name)}, by ${U.esc(leg.transport.toLowerCase())}, to ${U.esc(next.place.name)} ${T("data")}. ${leg.transport.match(/boat/i) ? "Hire it together at the harbour: the company will crew it, so you pay one hand's wage, not three." : ""}` : "",
      `They travel with you and carry their own food. Ask them for advice any time: Space where there is nothing else to do.`].filter(Boolean));
  };
  G.rumoursHere = async function (b) {
    const s = this.s, next = this.cpNext();
    this.doAct("rumours");
    const rnd = U.rng(`${s.seed}:rum:${b.i}:${Math.floor(s.clock / 24)}`);
    const L = [`You spend the evening listening in ${U.esc(b.name)} ${T("new")}.`];
    for (let i = 0; i < 2; i++) { const r = this.know.rumour(b.t[0], b.t[1], rnd, this); if (r) L.push(`“${r}`); }
    if (next) { const why = this.legReasons(next).slice(0, 2); if (why.length) L.push(`About the road to ${U.esc(next.place.name)}: ${why.join(" ")}`); }
    await this.ui.say(L);
  };
  // the company's advice: Space where there is nothing else
  const interact0 = G.interact;
  G.interact = async function () {
    const s = this.s, w = this.w;
    if (!this.burgHere() && !this.riding() && s.party && s.party.length) {
      const [dc, dr] = AZ.DIRS[s.dir];
      const busy = [[s.c, s.r], [s.c + dc, s.r + dr]].some(([c, r]) => w.inb(c, r) && (w.markersAt.get(w.idx(c, r)) || w.unitsAt.get(w.idx(c, r)))) || (this.sim && this.sim.regAt(s.c, s.r, 1.5).length);
      if (!busy && !(s.aboard && s.vessel && w.isLand(s.c + dc, s.r + dr))) {
        const k = await this.ui.choose("", [{ label: "Look around" }, { label: `Ask ${U.esc(s.party[0].name)} and the others what next` }, { label: "Back" }], { cancel: 2 });
        if (k === 1) return this.advice();
        if (k === 2) return;
        return this.ui.say([this.know.describe(s.c, s.r, s.aboard).join(" ")], "Look");
      }
    }
    return interact0.call(this);
  };
  G.advice = async function () {
    const s = this.s, w = this.w, next = this.cpNext(), p = s.party, lead = p[0];
    if (!next) return this.ui.say(`${U.esc(lead.name)}: “We are done. The world is still out there.”`);
    const leg = next.legIn, dd = this.know.dirDist(s.c, s.r, next.tile), L = [];
    L.push(`${U.esc(lead.name)} (${U.esc(lead.role)}): “${U.esc(next.place.name)} next, ${dd.txt}. The plan has us go by ${U.esc((leg?.transport || "road").toLowerCase())}: ${U.esc(leg?.name || "")}.” ${T("data")}`);
    const days = leg ? (leg.hoursPerDay >= 24 ? leg.travelHours / 24 : leg.travelHours / leg.hoursPerDay) : dd.mi / 40;
    const need = Math.ceil(days * this.eaters() * 1.2);
    L.push(`${U.esc((p[1] || lead).name)}: “That is about ${Math.round(days)} days. We need some ${need} rations; we have ${s.sup.food}.${s.sup.food < need ? " Buy before we go, or plan where to buy on the way." : ""}” ${T("mixed")}`);
    if (leg && AZ.vesselClass(leg.transport) === "ship" && this.sim) {
      const here = this.burgHere() || w.near(s.c, s.r, 20).find(n => n.kind === "burg" && n.o.port)?.o;
      const deps = here ? this.sim.departures(here, s.clock, 14).filter(d => d.L.to === next.place.burg?.i || (d.L.via || []).includes(next.place.burg?.i)) : [];
      L.push(deps.length ? `${U.esc((p[2] || lead).name)}: “${U.esc(deps[0].L.ship)} sails from ${U.esc(here.name)} on ${AZ.Clock.fmt(deps[0].t)} and calls there. That is our ship.” ${T("mixed")}` : `${U.esc((p[2] || lead).name)}: “No ship I know of runs straight there from here. Ask at the harbour, or find one that goes close.”`);
    } else if (leg && /boat/i.test(leg.transport)) L.push(`${U.esc((p[2] || lead).name)}: “We'll need a boat of our own. Hire one at a harbour; we'll crew it.”`);
    const why = this.legReasons(next).find(x => /seat|capital|lane|crosses|clear of|Hazards/.test(x));
    if (why) L.push(`${U.esc(lead.name)}: “${why.replace(/<[^>]+>/g, "").replace(/ (data|mixed|new)\./g, ".")}”`);
    return this.ui.say(L, "The company");
  };
  // companions crew a hired boat
  const harbour15 = G.harbour;
  G.harbour = async function (b) {
    const s = this.s, P0 = AZ.Prices.wage, helpers = Math.min(2, (s.party || []).length);
    if (helpers) AZ.Prices.wage = (w, bb) => U.rn(P0.call(AZ.Prices, w, bb) * (3 - helpers) / 3, 2);
    try { return await harbour15.call(this, b); } finally { AZ.Prices.wage = P0; }
  };

  // ------------------------------------------------------------------ moving targets: last known position, tracks, news
  AZ.Sim.prototype.knownPos = function (id, from, clock) {
    const r = this.regs.find(x => x.id === id);
    if (!r) return null;
    const delayDays = (Math.hypot(r.t[0] - from[0], r.t[1] - from[1]) * this.w.miles) / AZ.SIM.newsMilesPerDay;
    const day = Math.floor(clock / 24 - delayDays), tr = r.trail || [];
    let pos = tr.length ? tr[0] : [this.day, r.base[0], r.base[1]];
    for (const e of tr) if (e[0] <= day) pos = e;
    return { tile: [pos[1], pos[2]], day: pos[0] };
  };
  const step0 = AZ.Sim.prototype.step;
  AZ.Sim.prototype.step = function () { step0.call(this); for (const r of this.regs) { r.trail = r.trail || [[0, r.base[0], r.base[1]]]; const l = r.trail[r.trail.length - 1]; if (l[1] !== r.t[0] || l[2] !== r.t[1]) r.trail.push([this.day, r.t[0], r.t[1]]); if (r.trail.length > 120) r.trail.shift(); } };
  const tracked = (g, goal) => g.sim && (goal.observe || (goal.unit && g.sim.regs.some(r => r.id === goal.unit)));
  const start0 = G.startThread;
  G.startThread = function (def, quiet) {
    start0.call(this, def, quiet);
    const th = this.s.threads[this.s.threads.length - 1];
    if (th && th.title === def.title) this.refreshKnown(th, def.giver != null ? this.w.P.burgs[def.giver].t : [this.s.c, this.s.r]);
  };
  G.refreshKnown = function (th, from) {
    if (th.done) return;
    const st = th.steps[th.phase], g = st.goal || {};
    if (!tracked(this, g)) return;
    const k = this.sim.knownPos(g.observe || g.unit, from, this.s.clock);
    if (k) st.known = { tile: k.tile, day: k.day };
  };
  const tile15 = G.stepTile;
  G.stepTile = function (st) { const g = st.goal || {}; if (tracked(this, g)) return st.known ? st.known.tile : null; return tile15.call(this, st); };
  const after15 = G.afterStep;
  G.afterStep = function (...a) {
    after15.apply(this, a);
    const s = this.s, w = this.w;
    if (!this.sim || !s) return;
    for (const th of s.threads) {
      if (th.done) continue;
      const st = th.steps[th.phase], g = st.goal || {};
      if (!tracked(this, g) || !st.known) continue;
      const id = g.observe || g.unit, r = this.sim.regs.find(x => x.id === id);
      if (!r) continue;
      const see = this.know.sightTiles(s.c, s.r, s.aboard);
      if (Math.hypot(r.t[0] - s.c, r.t[1] - s.r) <= see) { st.known = { tile: r.t.slice(), day: Math.floor(s.clock / 24) }; continue; }
      if (Math.hypot(st.known.tile[0] - s.c, st.known.tile[1] - s.r) <= 2) {
        const k = this.sim.knownPos(id, r.t, s.clock - 24 * (1 + Math.floor(U.rnd2(s.c, s.r, 5) * 2)));
        if (k && (k.tile[0] !== st.known.tile[0] || k.tile[1] !== st.known.tile[1])) {
          st.known = { tile: k.tile, day: k.day };
          this.ui.toast(`Tracks: the ${U.esc(r.name)} came through here and went on ${this.know.dirDist(s.c, s.r, k.tile).txt.replace(/^[\d,]+ mi /, "")}, about ${Math.max(1, Math.floor(s.clock / 24) - k.day)} days ago ${T("mixed")}`, "teal");
        }
      }
    }
  };
  const news15 = G.learnNews;
  G.learnNews = function (b) {
    const before = (this.s.known || []).length;
    news15.call(this, b);
    if ((this.s.known || []).length === before) return;
    for (const th of this.s.threads) {
      if (th.done) continue;
      const g = th.steps[th.phase].goal || {};
      if (tracked(this, g)) this.refreshKnown(th, b.t);
    }
  };

  // ------------------------------------------------------------------ food: a town spares only so much each week
  G.foodLeft = function (b, f) {
    const rec = (this.s.foodTaken || {})[b.i];
    const recent = rec ? rec.n * Math.max(0, 1 - (this.s.clock - rec.t) / 168) : 0;
    return Math.max(0, Math.floor(f.rations - recent));
  };
  G.foodTook = function (b, n) {
    const s = this.s; s.foodTaken = s.foodTaken || {};
    const rec = s.foodTaken[b.i], recent = rec ? rec.n * Math.max(0, 1 - (s.clock - rec.t) / 168) : 0;
    s.foodTaken[b.i] = { t: s.clock, n: recent + n };
    this.doAct("resupply");
  };

  // ------------------------------------------------------------------ camping depends on the place
  G.campNight = async function () {
    const s = this.s, w = this.w, c = s.c, r = s.r, cell = w.cell(c, r), lat = this.lat();
    const b = w.P.biomes[w.C.biome[cell]], look = w.biomeLook[w.C.biome[cell]];
    const today = AZ.Clock.today(w.tempC(c, r), lat, s.clock, false), wx = this.weather();
    const t0 = s.clock, L = [];
    s.clock = AZ.Clock.nextDawn(s.clock, lat);
    let rest = 0; // hours of sleep lost
    const water = w.bits(c, r).river || [[0, 1], [1, 0], [0, -1], [-1, 0]].some(([a, b2]) => w.inb(c + a, r + b2) && !w.isLand(c + a, r + b2));
    const fuel = /grass|lush|needle|meadow|dry/.test(look.kind) || /forest|taiga|savann/i.test(b.name);
    const danger = w.near(c, r, 3).find(n => n.kind === "marker" && /brigand|monster|burial|pirate/.test(n.o.type)) || w.zonesOfCell(cell).find(z => /Rebels|Invasion/.test(z.type));
    const rnd = U.rng(`${s.seed}:camp:${c}:${r}:${Math.floor(t0 / 24)}`);
    L.push(`You camp in the ${b.name.toLowerCase()} ${T("data")}.`);
    if (/forest|rainforest|taiga/i.test(b.name)) { s.sup.food += 1; L.push("The trees give shelter, and you find nuts and roots for breakfast (+1 ration)."); }
    if (water) { s.sup.food += rnd() < 0.5 ? 1 : 0; L.push("Water close by; a line in it overnight."); }
    if (today < 0) { if (fuel) L.push(`A cold night (about ${w.temp(today)}), but there is wood for a fire.`); else { rest += 6; s.sup.food = Math.max(0, s.sup.food - 1); L.push(`A cold night (about ${w.temp(today)}) with nothing to burn: you eat more and sleep little.`); } }
    if (/wetland|swamp|marsh/i.test(b.name)) { rest += 3; if (rnd() < 0.2 && this.tv.trait !== "hardy") { s.cond.fever = true; L.push("Insects all night; by morning you are feverish."); } else L.push("Insects all night."); }
    if (/desert/i.test(b.name)) L.push("The desert gives back its heat fast; the night is cold and clear.");
    if (["rain", "snow", "storm"].includes(wx.kind)) { rest += wx.kind === "storm" ? 5 : 2; L.push(`The ${wx.label} keeps you awake.`); }
    if (danger) {
      const name = danger.o ? danger.o.name : danger.name;
      if (rnd() < 0.35) { const lost = U.rn(s.purse * 0.2, 2); s.purse = U.rn(s.purse - lost, 2); s.sup.food = Math.max(0, s.sup.food - 2); rest += 4; L.push(`<b class="late">In the night they come: ${U.esc(name)}.</b> You lose 🟡 ${lost} and some food.`); this.log(`Robbed in camp near ${U.esc(name)}.`); }
      else L.push(`You sleep with a hand on your knife: ${U.esc(name)} is near.`);
    }
    this.slept(); if (rest) this.awakeTick(rest);
    const act = this.doAct("camp") || this.doAct("anchor");
    if (act) L.push(`<span class="hook">★ ${U.esc(act.label)}</span>`);
    this.dirty = true;
    return this.ui.say(`${L.join(" ")} <span class="dim">(${AZ.Clock.span(s.clock - t0)})</span> ${T("mixed")}`);
  };

  // ------------------------------------------------------------------ crews on rivers; storms that sink
  G.landDistance = function (c, r, max = 14) {
    const w = this.w;
    for (let d = 0; d <= max; d++) for (let a = -d; a <= d; a++) for (const b2 of [-d, d]) if (w.isLand(c + a, r + b2) && !w.navigable(c + a, r + b2, "boat")) return d; else if (w.isLand(c + b2, r + a) && !w.navigable(c + b2, r + a, "boat")) return d;
    return max + 1;
  };
  G.crewCall = async function () {
    const s = this.s, v = s.vessel, w = this.w;
    if (v.morale < 20) return this.ultimatum();
    const river = w.isLand(s.c, s.r);
    const port = this.nearestPort(v.cls), h = port && w.harbour(port, v.cls), mi = h ? Math.round(Math.hypot(h.t[0] - s.c, h.t[1] - s.r) * w.miles) : null;
    const reachable = h && w.sameWater([s.c, s.r], h.t, v.cls);
    const k = await this.ui.choose(`<b>The crew calls for a stop.</b> Sunset, ${AZ.Clock.fmt(s.clock)}. They have sailed their hours (${v.hpd} a day by custom ${T("data")}). Morale ${Math.round(v.morale)}${v.strikes ? `, strikes ${v.strikes}/3` : ""}.`,
      [{ label: river ? "Tie up at the bank until dawn" : "Anchor here until dawn" }, { label: river ? "Push on in the dark (morale −12; snags and sandbars)" : "Sail on through the night (morale −12)" },
       { label: reachable ? `Make for ${U.esc(port.name)} (${U.num(mi)} mi)` : "No town you can reach by water", disabled: !reachable }], { cancel: 0 });
    if (k === 0) {
      const t0 = s.clock; s.clock = AZ.Clock.nextDawn(s.clock, this.lat()); v.anchored = true; v.morale = Math.min(100, v.morale + 4); this.slept();
      const act = this.doAct("anchor") || this.doAct("camp");
      this.ui.toast(`${river ? "Tied up" : "At anchor"} ${AZ.Clock.span(s.clock - t0)}. ${act ? `<span class="hook">★ ${U.esc(act.label)}</span>` : ""}`, act ? "gold" : "");
    } else if (k === 1) {
      v.morale -= 12;
      const nearLand = river || this.landDistance(s.c, s.r, 3) <= 2;
      if (nearLand && U.rnd2(s.c, s.r, Math.floor(s.clock)) < (river ? 0.2 : 0.15)) { this.events.fx({ cond: "damaged", time: 3 }, river ? "Ran onto a snag in the dark." : "Struck a reef at night."); this.ui.toast(river ? "In the dark you run onto a snag. The hull is damaged." : "In the dark you touch a reef. The hull is damaged."); }
      else this.ui.toast(`The crew goes on, sullen. Morale ${Math.round(v.morale)}.`);
    } else { s.waypoint = h.t; v.morale -= 2; this.setAuto(true); }
    this.dirty = true;
  };
  const storm0 = G.stormCall;
  G.stormCall = async function () {
    const s = this.s, w = this.w, v = s.vessel;
    if (this.riding() || !v) return storm0.call(this);
    const until = (Math.floor(s.clock / 12) + 1) * 12, river = w.isLand(s.c, s.r);
    if (river) { s.clock = until; this.ui.toast("A storm: you tie up under the bank until it passes."); this.dirty = true; return; }
    const d = this.landDistance(s.c, s.r), mi = Math.round(d * w.miles);
    const pDamage = U.clamp(0.04 * d, 0.04, 0.6), pSink = U.clamp(0.025 * d, 0, 0.4);
    const k = await this.ui.choose(`<b>A storm is coming up.</b> ${d > 14 ? "Open water, no land in sight" : `Land about ${U.num(mi)} mi off`} ${T("mixed")}.${v.crew ? ` The crew wants shelter. Morale ${Math.round(v.morale)}.` : ""}`,
      [{ label: d <= 2 ? "Run for the shore and beach the boat until it passes (safe)" : "Too far to beach the boat", disabled: d > 2 },
       { label: `Heave to and ride it out (${AZ.Clock.span(until - s.clock)}; damage ${Math.round(pDamage * 100)}%, worse if already damaged)` },
       { label: `Run before it under sail (morale −10; damage ${Math.round(Math.min(0.9, pDamage + 0.25) * 100)}%)` }], { cancel: 1 });
    const roll = U.rnd2(s.c, s.r, Math.floor(s.clock) + 11), roll2 = U.rnd2(s.r, s.c, Math.floor(s.clock) + 13);
    if (k === 0) { s.clock = until + 2; v.morale = Math.min(100, v.morale + 2); this.ui.toast("You beach the boat and wait out the storm in the lee of the dunes."); this.dirty = true; return; }
    if (k === 2) { v.morale -= 10; }
    else s.clock = until;
    const pd = k === 2 ? Math.min(0.9, pDamage + 0.25) : pDamage;
    if (roll < pd) {
      if (s.cond.damaged && roll2 < pSink * 2 || roll2 < pSink * 0.5) return this.shipwreck();
      this.events.fx({ cond: "damaged" }, "Storm damage."); this.ui.toast("A spar carries away and the seams open. The boat is damaged.");
    } else this.ui.toast("The storm blows itself out.");
    this.dirty = true;
  };
  G.shipwreck = async function () {
    const s = this.s, w = this.w, v = s.vessel;
    // wash ashore on the nearest land
    let best = null, bd = 1e9;
    for (let dr = -20; dr <= 20; dr++) for (let dc = -20; dc <= 20; dc++) { const c = s.c + dc, r = s.r + dr; if (w.isLand(c, r) && !w.navigable(c, r, "boat") && dc * dc + dr * dr < bd) { bd = dc * dc + dr * dr; best = [c, r]; } }
    const lostFood = Math.ceil(s.sup.food / 2), goods = this.goodsCount();
    s.sup.food -= lostFood; s.goods = {}; s.vessel = null; s.aboard = false; s.auto = false; delete s.cond.damaged;
    if (best) { s.c = best[0]; s.r = best[1]; }
    s.clock += 12; this.anim = null;
    this.log(`Shipwrecked: the ${U.esc(v.kind.toLowerCase())} went down; washed ashore.`, "hook");
    await this.ui.say([`<b class="late">The ${U.esc(v.kind.toLowerCase())} goes down.</b> You come ashore on wreckage hours later ${T("mixed")}.`,
      `Lost: the boat${v.mode === "hired" ? " (and the deposit)" : ""}, half your food (${lostFood} rations)${goods ? `, all your goods (${goods} units)` : ""}. ${v.crew ? "Of the crew there is no sign." : ""} You keep your purse.`]);
    this.afterStep();
  };

  // ------------------------------------------------------------------ portals cost, and sometimes misfire
  AZ.MARKERS.portals = { run: async (ev, m, head) => {
    const g = ev.g, s = ev.s, w = g.w, others = w.P.markers.filter(x => x.type === "portals" && x.i !== m.i);
    const town = w.near(m.t[0], m.t[1], 4).find(n => n.kind === "burg")?.o;
    const fee = U.rn(1 + (town ? town.population * 0.15 : 0) + (town && w.P.cultures[town.culture]?.type === "Naval" ? 1 : 0), 2);
    const k = await g.ui.choose(`${head}<br>${U.esc(m.note)}<br><span class="dim">The keepers${town ? ` of ${U.esc(town.name)}` : ""} ask 🟡 ${fee} ${T("mixed")}. Whatever you carry goes with you; your ${s.vessel ? U.esc(s.vessel.kind.toLowerCase()) : "baggage train"} stays. Not every crossing goes as planned.</span>`,
      [...others.map(o => ({ label: `Step through to the ${U.esc(o.name)} (${U.num(g.know.dirDist(s.c, s.r, o.t).mi)} mi)`, disabled: s.purse < fee })), { label: "Stay on this side" }], { cancel: others.length });
    if (k >= others.length) return;
    const o = others[k];
    s.purse = U.rn(s.purse - fee, 2);
    s.portalUses = (s.portalUses || 0) + 1;
    const rnd = U.rng(`${w.P.world.seed}:portal:${s.seed}:${s.portalUses}`), roll = rnd();
    let hours = 1 + Math.floor(rnd() * 6), dest = o.t, text;
    if (roll < 0.06) { text = "The air hums, and nothing happens. The keepers do not return fees."; hours = 2; dest = null; }
    else if (roll < 0.14) { hours = 24 * (1 + Math.floor(rnd() * 14)); text = `You step through and out, and it is ${Math.round(hours / 24)} days later. No one can tell you where the time went.`; }
    else if (roll < 0.2) {
      let t = null;
      for (let i = 0; i < 400 && !t; i++) { const c = Math.floor(rnd() * w.cols), r = Math.floor(rnd() * w.rows); if (w.isLand(c, r) && !w.near(c, r, 25).some(n => n.kind === "burg")) t = [c, r]; }
      dest = t || o.t; text = "The crossing tears. You fall out somewhere else entirely: no road, no town, no one.";
    } else text = `The world folds. You stand at the ${U.esc(o.name)}.`;
    if (dest) { s.aboard = false; s.auto = false; s.c = dest[0]; s.r = dest[1]; if (!w.isLand(s.c, s.r)) { const l = w.near(s.c, s.r, 3).find(n => n.kind === "burg"); if (l) { s.c = l.o.t[0]; s.r = l.o.t[1]; } } }
    s.clock += hours; g.awakeTick(Math.min(hours, 30));
    ev.fx(null, `Portal from the ${U.esc(m.name)}: ${text}`);
    g.anim = null; g.afterStep();
    await g.ui.say(`${text} <span class="dim">(🟡 −${fee}; ${AZ.Clock.span(hours)})</span> ${T("mixed")}`);
  } };
})();
