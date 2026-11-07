// ---------------------------------------------------------------------------------------------
// Stops, worked into the journey. Every stay the generator writes is something to do, and the
// company's own vessels: a "Loading at X's quay" stop gives the company a ship or boat of its own
// for the next leg, as raids, campaigns and expeditions have; it is boarded at the quay.
// ---------------------------------------------------------------------------------------------
AZ.OWN_TRANSPORT = new Set(["Raid", "Military campaign", "Expedition", "Mercenary contract", "Royal progress", "Smuggling run"]);
// why the journey goes where it goes, by archetype, from the data
AZ.whyDest = function (w, jr) {
  const U = AZ.U, T = AZ.T, P = w.P, arch = AZ.archOf(jr), noun = AZ.noun(jr);
  const o = jr.origin.burg, d = jr.dest.burg;
  if (!d) return `The ${noun} ends at ${U.esc(jr.dest.name)} ${T("data")}.`;
  const ds = P.states[d.state], os = o && P.states[o.state], stance = os && ds && o.state !== d.state ? os.diplomacy?.[d.state] || "Unknown" : null;
  const relD = P.religions[w.C.religion[d.cell]];
  const end = `${U.esc(d.name)}, ${U.esc(d.group)} of ${U.esc(ds?.fullName || "unclaimed land")}`;
  switch (arch) {
    case "Pilgrimage": return `Its end is ${end}, which keeps the ${U.esc(relD?.name)} ${T("data")}: that is why a pilgrim goes there.`;
    case "Raid": return `Its end is ${end}: a treasury of 🟡 ${U.num(d.treasury || 0, 1)}${d.walls ? ", behind walls" : ", unwalled"}${stance ? `; ${U.esc(os.name)} stands to ${U.esc(ds.name)} as “${stance}”` : ""} ${T("data")}. That is why raiders go there.`;
    case "Caravan": { const g = Object.keys(P.trade.sell[o?.i] || {}).find(x => (P.trade.buy[d.i] || {})[x]); return `Its end is ${end}${g ? `, which buys the ${U.esc(P.goods.find(x => x.i === +g)?.name.toLowerCase())} that ${U.esc(o.name)} sells` : ""} ${T("data")}. That is why the caravan goes there.`; }
    case "Embassy": return `Its end is ${end}${stance ? `; the two courts stand as “${stance}”` : ""} ${T("data")}. That is the embassy's business.`;
    case "Military campaign": { const war = (os?.campaigns || []).find(c => c.end == null && (c.defender === d.state || c.attacker === d.state)); return `Its end is ${end}${war ? `; the ${U.esc(war.name)} has been fought since ${war.start}` : stance ? `; the two stand as “${stance}”` : ""} ${T("data")}.`; }
    case "Monster hunt": { const m = w.near(d.t[0], d.t[1], 40).find(n => n.kind === "marker" && /monster/.test(n.o.type)); return `Its end is ${end}${m ? `; the ${U.esc(m.o.name)} is ${U.esc(m.o.note.split(".")[0].toLowerCase())}` : ""} ${T("data")}. Bounties pay for the hunt.`; }
    case "Treasure hunt": { const m = w.near(d.t[0], d.t[1], 40).find(n => n.kind === "marker" && /ruin|dungeon|cave|burial|necrop/.test(n.o.type)); return `Its end is ${end}${m ? `, near the ${U.esc(m.o.name)}` : ""} ${T("data")}.`; }
    default: return `Its end is ${end} ${T("data")}.`;
  }
};
(() => {
  const G = AZ.Game.prototype, U = AZ.U, T = AZ.T;
  // the company's own vessel for water legs, where the archetype or a loading stop says so
  const fix0 = AZ.Journey.prototype.fixCourses;
  AZ.Journey.prototype.fixCourses = function () {
    fix0.call(this);
    const arch = AZ.archOf(this);
    for (const cp of this.cps) {
      const leg = cp.legOut;
      if (!leg || leg.domain === "land" || AZ.vesselClass(leg.transport) === "air" || !/boat|ship|row|galley|vessel/i.test(leg.transport)) continue;
      const booked = cp.acts.some(a => a.id === "book"), loading = cp.acts.some(a => a.id === "board");
      leg.own = loading || (!booked && AZ.OWN_TRANSPORT.has(arch));
      if (leg.own && !loading) cp.acts.push({ id: "board", label: `Board the company's ${leg.transport.toLowerCase()}`, stay: null });
    }
  };
  const doActIn0 = G.doActInTown;
  G.doActInTown = async function (id, b) {
    if (id === "board") return this.boardCompany(b);
    if (id === "bounty") return this.bounty(b);
    if (id === "stay") return this.spendStay(b);
    return doActIn0.call(this, id, b);
  };
  G.boardCompany = async function (b) {
    const s = this.s, w = this.w, cp = this.cpHere(), leg = cp && cp.legOut;
    if (!leg) return;
    const cls = AZ.vesselClass(leg.transport), h = w.harbour(b, cls) || w.harbour(b, "boat");
    if (!h) return this.ui.say(`There is no water here a ${U.esc(leg.transport.toLowerCase())} can use.`);
    const tr = w.W.transports.find(t => t.name === leg.transport) || { speed: leg.speed, hoursPerDay: leg.hoursPerDay };
    const crew = Math.max(3, (s.party || []).length);
    if (s.vessel && s.vessel.mode === "hired") this.log(`Returned the hired boat in ${U.esc(b.name)}.`);
    s.vessel = { mode: "company", kind: leg.transport, cls, speed: leg.speed || tr.speed, hpd: leg.hoursPerDay || tr.hoursPerDay, crew, morale: 80, c: h.t[0], r: h.t[1], wage: 0, hire: 0, home: b.i };
    s.aboard = true; s.c = h.t[0]; s.r = h.t[1]; if (s.voyage) s.voyage.boarded = false;
    this.doAct("board");
    const raid = AZ.archOf(this.jr) === "Raid";
    this.log(`Boarded the company's ${U.esc(leg.transport.toLowerCase())} at ${U.esc(b.name)}.`, "hook");
    await this.ui.say([`At the quay of ${U.esc(b.name)} the company loads its ${U.esc(leg.transport.toLowerCase())} ${T("mixed")}: ${raid ? "weapons, rope, empty sacks for the plunder" : "stores, gear and the company's chests"} ${T("new")}.`,
      `${(s.party || []).length ? `${U.esc(s.party.map(p => p.name).join(", "))} crew her.` : `A crew of ${crew} sails her.`} No fare and no wages: she is the company's. You feed ${this.eaters() > 1 ? `the ${this.eaters()} aboard who have no stores of their own` : "yourself"}; buy food before you sail.`,
      `The plan: ${U.esc(leg.name)}, ${U.num(leg.miles)} mi to ${U.esc(this.cpNext()?.place.name || "")} ${T("data")}. Steer, or press F to follow the plan's course.`]);
    this.afterStep();
  };
  G.bounty = async function (b) {
    const s = this.s, w = this.w, jr = this.jr, d = jr.dest.burg;
    const m = d && w.near(d.t[0], d.t[1], 40).find(n => n.kind === "marker" && /monster/.test(n.o.type));
    const target = m ? m.o.name : jr.J.name.replace(/^the /i, "");
    const st = w.P.states[b.state], advance = U.rn(Math.min(60, 5 + (b.population || 1) * 0.6), 2);
    this.doAct("bounty");
    s.purse = U.rn(s.purse + advance, 2);
    this.log(`Signed the bounty in ${U.esc(b.name)}: an advance of 🟡 ${advance}.`, "hook");
    this.startThread({ title: `The bounty on ${target}`, steps: [{ text: `Deal with ${target} and bring proof to ${b.name}`, goal: m ? { marker: m.o.i } : { burg: d?.i, role: "Captain of the watch" } }, { text: `Claim the bounty in ${b.name}`, goal: { burg: b.i, role: "Captain of the watch" }, reward: { coin: U.rn(advance * 3, 2), stand: [["s", b.state, 2]] } }], giver: b.i });
    await this.ui.say([`The notice is nailed up by the ${st ? `watch of ${U.esc(st.name)}` : "elders"}: a bounty on <b>${U.esc(target)}</b> ${T(m ? "data" : "mixed")}.`,
      `You sign. They pay 🟡 ${advance} now for the road, and three times that on proof ${T("mixed")}.`]);
  };
  G.spendStay = async function (b) {
    const s = this.s, cp = this.cpHere();
    const act = cp && cp.acts.find(a => a.id === "stay" && !(s.cpRec[cp.i]?.acts || {}).stay);
    if (!act) return;
    const k = await this.ui.choose(`<b>${U.esc(act.label)}</b>: the plan has the company spend this time in ${U.esc(b.name)} ${T("data")}.`, [{ label: `Spend it (${act.hours} h): rest, talk, see to the gear` }, { label: "Not now" }], { cancel: 1 });
    if (k !== 0) return;
    s.clock += act.hours; if (act.hours >= 6) this.slept(); else this.awakeTick(act.hours);
    this.doAct("stay");
    const rnd = U.rng(`${s.seed}:stay:${b.i}`), rm = this.know.rumour(b.t[0], b.t[1], rnd, this);
    await this.ui.say([`${act.hours} hours in ${U.esc(b.name)}.`, rm ? `What you hear: “${rm}` : "", s.party?.length ? "The company is ready when you are." : ""].filter(Boolean));
  };
  // the company's own vessel: no paying off, and the advice knows it
  const adv0 = G.advice;
  G.advice = async function () {
    const next = this.cpNext(), here = this.cpHere();
    if (here && here.legOut && here.legOut.own && !(this.s.vessel && this.s.vessel.mode === "company")) return this.ui.say(`${U.esc(this.s.party?.[0]?.name || "The mate")}: “Our ${U.esc(here.legOut.transport.toLowerCase())} is at the quay. Load her and we sail: no need to book anything.”`, "The company");
    return adv0.call(this);
  };
})();
