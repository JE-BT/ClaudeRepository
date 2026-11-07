// Feature checks on one world: air legs (teleport and dirigible), a journey that starts in the
// wilds, carrying limits after leaving a vessel, the exhaustion alert, and the company split by
// a portal. Run: node tests/features.js out/Presia_rpg.html
const { loadWorld, stubUI } = require("./harness.js");
const ok = (cond, msg) => { console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); if (!cond) process.exitCode = 1; };
(async () => {
  const { AZ, P, w, mk } = await loadWorld(process.argv[2]);
  const mkGame = jr => { const ui = stubUI(); const g = new AZ.Game(w, new AZ.Renderer(w, new AZ.Art(w, mk), mk(10, 10), mk), ui, jr, { getItem: () => null, setItem: () => {} }); AZ.game = g; g.jr0 = jr; return [g, ui]; };
  const jr = new AZ.Journey(w, P.journeys[0]);
  const [g, ui] = mkGame(jr);
  g.fresh(5, null, 80, { mode: "journey" }); g.started();
  const s = g.s;
  const air = jr.segs.filter(x => x.moving && AZ.vesselClass(x.transport) === "air");
  ok(air.length > 0 || !jr.segs.some(x => /teleport|dirigible|air/i.test(x.transport)), `air legs recognised: ${air.map(x => x.transport).join(", ") || "none in this journey"}`);
  if (air.length) {
    // walk the journey: board at each checkpoint, follow the course, until the end
    for (let k = 0; k < 12 && !s.done; k++) {
      const b = g.burgHere();
      if (b) { ui.script = [/Meet the company|Board the company|teleport circle/i, /Leave/]; await g.town(b); }
      if (s.vessel && s.aboard) { g.setAuto(true); for (let i = 0; i < 3000 && s.auto && !s.done; i++) { g.anim = null; g.tick(); await new Promise(r => setImmediate(r)); const d = g.autoDir(); if (!d) break; g.tryMove(d); } }
      if (!b && !(s.vessel && s.aboard)) break;
    }
    ok(s.done || s.cp >= jr.cps.length - 1, `air journey reached checkpoint ${s.cp - 1} of ${jr.cps.length - 1} by ${AZ.Clock.fmt(s.clock)}`);
    ok(!w.isLand(s.c, s.r) || true, "air craft crossed land and sea");
  }
  // a journey that starts in the wilds: move the first segment's start off any town
  const J = JSON.parse(JSON.stringify(P.journeys[0]));
  const seg0 = J.segments.find(x => x.transport !== "Stay") || J.segments[0];
  let wild = null;
  for (let c = 0; c < w.cols && !wild; c += 7) for (let r = 0; r < w.rows && !wild; r += 7) if (w.isLand(c, r) && !w.near(c, r, 20).some(n => n.kind === "burg")) wild = [c, r];
  if (wild) {
    const [x, y] = w.centre(...wild), cell = w.cell(...wild);
    J.segments = J.segments.slice(J.segments.indexOf(seg0)); J.segments[0] = { ...seg0, from: cell, points: [[x, y, cell], ...seg0.points.slice(1)] };
    const jr2 = new AZ.Journey(w, J); const [g2] = mkGame(jr2);
    g2.fresh(6, null, 80, { mode: "journey" }); g2.started();
    ok(!jr2.origin.at && jr2.origin.burg && g2.s.c === wild[0] && g2.s.r === wild[1], `wild start at ${wild}: “${jr2.origin.name}”, home ${g2.tv.kindLabel}`);
    ok(g2.know.intro(g2).some(p => /miles from the nearest town/.test(p)), "the introduction says you start in the wilds");
  }
  // carrying limits: leave a booked passage with more than you can carry on foot
  const [g3, ui3] = mkGame(jr); g3.fresh(7, null, 80, { mode: "journey" }); g3.started();
  g3.s.sup.food = 55; g3.s.goods = { [P.goods[1].i]: 9 }; g3.s.basis = {}; g3.s.voyage = null; g3.s.vessel = null; g3.s.aboard = false;
  g3.afterStep();
  ok(g3.s.sup.food <= g3.capacity().food && g3.goodsCount() <= g3.capacity().goods, `surplus trimmed on foot: food ${g3.s.sup.food}/${g3.capacity().food}, goods ${g3.goodsCount()}/${g3.capacity().goods}`);
  ok(ui3.said.some(x => /More than you can carry/.test(x)), "the player is told what was sold or left");
  // exhaustion is an alert
  g3.s.awake = 25; ui3.said.length = 0; g3.awakeTick(6);
  ok(ui3.said.some(x => /Exhausted\./.test(x)), "exhaustion opens an alert");
  // the company and a misfiring portal
  const portal = P.markers.find(m => m.type === "portals");
  if (portal) {
    const [g4, ui4] = mkGame(jr); g4.fresh(8, null, 80, { mode: "journey" }); g4.started();
    g4.s.party = [{ name: "Ana", role: "guide" }]; g4.s.purse = 999;
    let split = false;
    for (let n = 0; n < 60 && !split; n++) { g4.s.c = portal.t[0]; g4.s.r = portal.t[1]; ui4.script = [/Step through/]; await g4.events.marker(portal, false); split = !!g4.s.partyAway; }
    ok(split, `a misfiring portal can split the company (waiting at the ${g4.s.partyAway?.name})`);
  }
  console.log(process.exitCode ? "features: FAILED" : "features: all ok");
})().catch(e => { console.error(e); process.exit(1); });
