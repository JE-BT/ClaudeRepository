const { loadWorld, stubUI } = require("./harness.js");
(async () => {
  const { AZ, P, w, mk } = await loadWorld(process.argv[2] || require("path").join(__dirname, "../out/Pyeongak_rpg.html"));
  const art = new AZ.Art(w, mk), ren = new AZ.Renderer(w, art, mk(10, 10), mk);
  const jr = new AZ.Journey(w, P.journeys[0]);
  const ui = stubUI();
  const mem = {}; const store = { getItem: k => mem[k] || null, setItem: (k, v) => (mem[k] = v) };
  const g = new AZ.Game(w, ren, ui, jr, store);
  g.fresh(7); g.started();
  console.log("traveller", g.tv.name, g.tv.kind);
  let guard = 0;
  while (!g.s.done && guard++ < 40) {
    const seg = g.seg();
    if (!seg.moving) {
      const b = w.burgAt.get(w.idx(g.s.c, g.s.r));
      if (seg.place.at) { if (!b) { console.log("NOT IN TOWN for", seg.name, g.s.c, g.s.r, seg.place.tile); break; } await g.town(b); }
      else await g.rest();
      console.log(`stay ${seg.k} ${seg.name}: clock ${AZ.Clock.fmt(g.s.clock)} plan ${AZ.Clock.fmt(seg.planEnd)}`);
      continue;
    }
    let steps = 0;
    const k0 = g.s.stage;
    while (g.s.stage === k0 && steps < seg.chain.length * 3) {
      const d = g.autoDir(); if (!d) { console.log("autoDir null at", g.s.c, g.s.r, "end", seg.endTile); break; }
      g.anim = null; if (!g.tryMove(d)) { console.log("blocked", d, g.s.c, g.s.r); break; }
      g.anim = null; steps++;
    }
    console.log(`move ${seg.k} ${seg.name}: ${steps} steps (chain ${seg.chain.length}) clock ${AZ.Clock.fmt(g.s.clock)} plan ${AZ.Clock.fmt(seg.planEnd)} stage now ${g.s.stage}`);
    if (g.s.stage === k0) break;
  }
  if (!g.s.done) { console.error("playthrough did not finish"); process.exit(1); }
  console.log("done", g.s.done, "log", g.s.log.length, "seen", JSON.stringify(Object.fromEntries(Object.entries(g.s.seen).map(([k, v]) => [k, v.length]))));
  console.log(ui.said.filter(x => /Arrived|complete|ANCHOR|anchors/.test(x)).slice(0, 8).map(x => x.replace(/<[^>]+>/g, "")).join("\n"));
  console.log("save bytes", JSON.stringify(mem).length);
  const g2 = new AZ.Game(w, ren, ui, jr, store); console.log("load", g2.loadGame(), g2.s.stage, g2.tv.name);
  console.log(g.know.stageScene(jr.segs[2]).join("\n").replace(/<[^>]+>/g, ""));
  console.log(g.know.stageScene(jr.segs[4]).join("\n").replace(/<[^>]+>/g, ""));
})().catch(e => { console.error(e); process.exit(1); });
