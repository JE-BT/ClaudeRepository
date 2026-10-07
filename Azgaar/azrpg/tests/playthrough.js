// Plays the whole pilgrimage the way a player would: buy food, book the plan's ship, wait aboard,
// go ashore, give alms, take a room, hire a boat with a crew, stock it, follow the course with F,
// let the crew anchor at dusk, keep the anchor stops, and finish. Exits non-zero if it stalls.
const { loadWorld, stubUI } = require("./harness.js");
(async () => {
  const { AZ, P, w, mk } = await loadWorld(process.argv[2] || require("path").join(__dirname, "../out/Pyeongak_rpg.html"));
  const ren = new AZ.Renderer(w, new AZ.Art(w, mk), mk(10, 10), mk), jr = new AZ.Journey(w, P.journeys[0]);
  const ui = stubUI(); const mem = {}; const store = { getItem: k => mem[k] || null, setItem: (k, v) => (mem[k] = v) };
  const g = new AZ.Game(w, ren, ui, jr, store); AZ.game = g;
  g.fresh(7, process.argv[3] || "returning", 80); g.started();
  const s = g.s, F = t => AZ.Clock.fmt(t);
  console.log("traveller", g.tv.name, g.tv.kindLabel, "purse", s.purse);
  // walk a little on land first
  const home = [s.c, s.r];
  for (const d of ["right", "right", "down", "left", "up"]) { g.anim = null; g.tryMove(d); }
  s.c = home[0]; s.r = home[1];
  const run = async (n) => { for (let i = 0; i < n; i++) { g.anim = null; g.tick(); await new Promise(r => setImmediate(r)); if (s.voyage && s.aboard && s.voyage.state === "sea") g.voyageStep(); else if (s.auto) { const d = g.autoDir(); if (d) g.tryMove(d); else { g.setAuto(false); return "stopped"; } } else return "idle"; if (s.done) return "done"; } return "limit"; };
  const town = async (script) => { ui.script = script.slice(); const b = g.burgHere(); if (!b) throw new Error("not in a town at " + s.c + "," + s.r); await g.town(b); };
  // Oxbreak: food, the plan's ship, wait aboard
  await town([/Harbour/, /★/, /Market/, /Food for 40 days/, /Back/, /Wait aboard/]);
  console.log("booked", s.voyage && s.voyage.ship, "aboard", s.aboard, F(s.clock), "purse", AZ.U.rn(s.purse, 1), "food", s.sup.food);
  console.log("voyage:", await run(4000), "at", F(s.clock), "cp", s.cp, "here", g.burgHere()?.name);
  // Durcojhler: alms, a room, hire a boat, stock it, board
  await town([/Give alms/, /Inn/, /Harbour/, /Hire a sailing boat/, /Back/, /Market/, /Food for 20 days/, /Food for 20 days/, /Food for 10 days/, /Water casks for 20/, /Water casks for 20/, /Water casks for 10/, /Back/, /Board your/]);
  console.log("Durcojhler done", F(s.clock), "acts", JSON.stringify(s.cpRec[1]?.acts), "vessel", s.vessel && s.vessel.mode, "aboard", s.aboard, "purse", AZ.U.rn(s.purse, 1), "food", s.sup.food, "water", s.sup.water);
  for (let leg = 0; leg < 8 && !s.done; leg++) {
    const cp0 = s.cp;
    let r;
    for (let tries = 0; tries < 400 && s.cp === cp0 && !s.done; tries++) {
      if (s.vessel && s.aboard && Math.min(s.sup.food, s.sup.water) / g.eaters() < 12) { // low stores: put in at the nearest harbour
        const p = g.nearestPort("boat"); s.waypoint = w.harbour(p, "boat").t;
        for (let k = 0; k < 20 && s.waypoint; k++) { g.setAuto(true); await run(2000); }
        console.log("   restocking at", p.name, F(s.clock), "food", s.sup.food, "water", s.sup.water);
        await town([/Market/, /Food for 20 days/, /Food for 20 days/, /Food for 10 days/, /Water casks for 20/, /Water casks for 20/, /Water casks for 10/, /Back/, /Board your/]);
        if (s.cp !== cp0) break;
      }
      g.setAuto(true); r = await run(60);
    }
    const here = g.cpHere();
    console.log(` leg -> cp ${s.cp - 1} ${here ? here.place.name : "?"} [${r}] ${F(s.clock)} par ${F(jr.cps[s.cp - 1].parArrive)} purse ${AZ.U.rn(s.purse, 1)} food ${s.sup.food} water ${s.sup.water} morale ${s.vessel && Math.round(s.vessel.morale)} cond ${Object.keys(s.cond).join(",")}`);
    if (s.done) break;
    if (s.cp === cp0) { console.error("no progress"); break; }
    const stock = [/Market/, /Food for 20 days/, /Food for 20 days/, /Food for 10 days/, /Water casks for 20/, /Water casks for 20/, /Water casks for 10/, /Back/, /Board your/];
    if (here && here.place.at) await town([/Inn/, /Harbour/, /Back/, ...stock]);
    else if (here) {
      ui.script = [/Anchor until dawn/]; await g.rest();
      if (s.sup.water < 120 || s.sup.food < 120) { // put in at the nearest port to restock, as a careful skipper would
        const p = g.nearestPort("boat"); s.waypoint = w.harbour(p, "boat").t;
        for (let tries = 0; tries < 20 && s.waypoint; tries++) { g.setAuto(true); await run(2000); }
        console.log("   restocking at", p.name, F(s.clock), "food", s.sup.food, "water", s.sup.water);
        await town(stock);
      }
    }
  }
  if (!s.done) { console.error("playthrough did not finish"); process.exit(1); }
  console.log("threads", JSON.stringify(s.threads.map(x => [x.title, x.phase, x.outcome])), "leads", s.leads.length, "stand", JSON.stringify(s.stand));
  console.log("cpRec", JSON.stringify(s.cpRec.map(r => r && { a: r.arrive && F(r.arrive), acts: Object.keys(r.acts || {}), sk: r.skipped })));
  console.log("events", ui.said.filter(x => /^CHOOSE <b class="(hook|side)|crew calls|storm/i.test(x)).map(x => x.replace(/<[^>]+>/g, "").slice(7, 50)).slice(0, 12).join(" || "));
  console.log("done", s.done, "log", s.log.length, "save bytes", JSON.stringify(mem).length);
})().catch(e => { console.error(e); process.exit(1); });
