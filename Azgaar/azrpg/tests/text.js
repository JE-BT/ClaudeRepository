// Text check: builds every screen and scene text the game can show for a world and fails on
// writing faults: contrast constructions ("X, not Y"), leftover development wording, broken
// placeholders (undefined, NaN, [object Object]), double words and unrounded money.
const { loadWorld, stubUI } = require("./harness.js");
(async () => {
  const file = process.argv[2] || require("path").join(__dirname, "../out/Pyeongak_rpg.html");
  const { AZ, P, w, mk } = await loadWorld(file);
  const fs = require("fs"), path = require("path");
  const src = fs.readdirSync(path.join(__dirname, "../engine/src")).map(f => fs.readFileSync(path.join(__dirname, "../engine/src", f), "utf8")).join("\n");
  const problems = [];
  const BAD = [
    [/\b\w+, not (a |an |the )?\w+/i, "contrast construction (X, not Y)"],
    [/\b(rather than|instead of|no longer)\b/i, "contrast construction"],
    [/\b(alpha 1|phase \d|playtest|TODO|FIXME|for now)\b/i, "development wording"],
    [/\b(undefined|NaN|\[object Object\]|null)\b/, "broken placeholder"],
    [/\b(\w+) \1\b/i, "double word"],
    [/🟡 -?\d+\.\d{3,}/, "unrounded money"],
  ];
  const check = (where, html) => {
    const t = String(html).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
    for (const [re, why] of BAD) { const m = t.match(re); if (m && !/(\bthe the\b)/.test("")) problems.push(`${where}: ${why}: “…${t.slice(Math.max(0, m.index - 40), m.index + 60)}…”`); }
  };
  // 1. strings in the source that reach the player
  for (const m of src.matchAll(/(["`])((?:(?!\1)[^\\]|\\.){25,}?)\1/g)) {
    const s = m[2];
    if (!/[a-z] [a-z]/i.test(s) || /^\s*(\/|\.|#|rgba?|M |data:)/.test(s)) continue;
    for (const [re, why] of BAD.slice(0, 2)) if (re.test(s.replace(/\$\{[^}]*\}/g, "X"))) problems.push(`source: ${why}: “${s.slice(0, 110)}”`);
  }
  // 2. generated text in play
  const jr = P.journeys.length ? new AZ.Journey(w, P.journeys[0]) : null, ui = stubUI();
  const g = new AZ.Game(w, new AZ.Renderer(w, new AZ.Art(w, mk), mk(10, 10), mk), ui, jr, { getItem: () => null, setItem: () => {} }); AZ.game = g; g.jr0 = jr;
  const shown = [];
  const say0 = ui.say; ui.say = async p => { shown.push(...(Array.isArray(p) ? p : [p])); };
  ui.choose = async (prompt, opts) => { shown.push(prompt, ...opts.map(o => o.label)); return opts.length - 1; };
  ui.modal = html => shown.push(html); ui.el = { modal: { querySelector: () => null, querySelectorAll: () => [] }, panel: { classList: { toggle() {} } } };
  for (const mode of jr ? ["journey", "sandbox"] : ["sandbox"]) {
    const start = jr ? undefined : P.burgs.find(b => b && b.capital).i;
    g.fresh(11, null, 80, { mode, start: mode === "sandbox" ? (start ?? jr.origin.burg.i) : undefined }); g.started();
    if (g.jr) shown.push(...g.know.intro(g));
    const b = g.burgHere() || P.burgs.find(x => x && x.capital);
    for (const p of g.know.townPeople(b, g)) shown.push(...p.talk());
    shown.push(...g.questOffers(b).map(o => `${o.title}. ${o.why}`));
    shown.push(g.know.inspect(b.t[0], b.t[1], g), g.know.describe(b.t[0], b.t[1], false).join(" "));
    if (g.jr) for (const cp of g.jr.cps) shown.push(...g.legReasons(cp), ...cp.acts.map(a => a.label));
    g.help(); g.journal && (() => { try { g.journal(); } catch (e) { /* the journal needs a DOM; its text is checked in the browser test */ } })();
    for (const k of (g.jr ? AZ.travellerKinds(w, g.jr) : AZ.sandboxKinds(w, b))) { const tv = AZ.makeTraveller(w, g.jr, 3, k.id, b.i); shown.push(k.label, k.blurb, tv.why); }
  }
  shown.forEach((h, i) => check(`screen ${i}`, h));
  const uniq = [...new Set(problems)];
  console.log(`${path.basename(file)}: ${shown.length} texts and the engine source checked; ${uniq.length} problems`);
  uniq.slice(0, 40).forEach(p => console.log("  " + p));
  process.exit(uniq.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
