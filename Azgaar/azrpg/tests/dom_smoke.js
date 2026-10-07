// DOM smoke test: runs the built HTML in jsdom with a real canvas backend, drives the title,
// the intro, the town menu and a few autopilot steps, and fails on any script error.
const fs = require("fs");
const NM = process.env.NODE_MODULES ? process.env.NODE_MODULES + "/" : "";
const { JSDOM } = require(NM + "jsdom");
const { createCanvas } = require(NM + "@napi-rs/canvas");
const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "https://example.org/" });
const { window } = dom;
const realCreate = window.document.createElement.bind(window.document);
const canvases = new WeakMap();
function napiFor(el) { if (!canvases.has(el)) canvases.set(el, createCanvas(el.width || 300, el.height || 150)); const c = canvases.get(el); if (c.width !== el.width) c.width = el.width; if (c.height !== el.height) c.height = el.height; return c; }
window.HTMLCanvasElement.prototype.getContext = function () { return napiFor(this).getContext("2d"); };
window.document.createElement = function (tag, ...a) {
  if (String(tag).toLowerCase() === "canvas") { const c = createCanvas(300, 150); return c; }
  return realCreate(tag, ...a);
};
window.HTMLCanvasElement.prototype.toDataURL = function () { return napiFor(this).toDataURL(); };
window.HTMLCanvasElement.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, width: this.width, height: this.height }; };
for (const k of ["DecompressionStream", "Blob", "Response", "TextDecoder"]) window[k] = globalThis[k];
window.performance = performance;
window.innerWidth = 1280; window.innerHeight = 800;
let rafQ = [];
window.requestAnimationFrame = f => { rafQ.push(f); return rafQ.length; };
window.addEventListener("error", e => errors.push(e.message));
window.addEventListener("unhandledrejection", e => errors.push("rejection: " + (e.reason && e.reason.stack || e.reason)));
process.on("unhandledRejection", e => errors.push("rejection: " + (e && e.stack || e)));
window.console.error = (...a) => errors.push(a.join(" "));
const scripts = [...window.document.querySelectorAll("script")].filter(s => !s.type || s.type === "text/javascript");
const tick = (n = 1) => { for (let i = 0; i < n; i++) { const q = rafQ; rafQ = []; q.forEach(f => { try { f(performance.now()); } catch (e) { errors.push("frame: " + e.stack); } }); } };
const key = (k, extra = {}) => window.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, ...extra }));
const keyup = k => window.dispatchEvent(new window.KeyboardEvent("keyup", { key: k }));
const wait = ms => new Promise(r => setTimeout(r, ms));
const until = async (pred, what, n = 200) => { for (let i = 0; i < n; i++) { if (pred()) return true; await wait(10); tick(1); } throw new Error("timed out waiting for " + what); };
const txt = el => el.textContent.replace(/\s+/g, " ");
// close every open window without opening new ones: Enter pages a message, Escape cancels a menu
const closeAll = async g => { for (let i = 0; i < 40 && g.ui.active; i++) { key(g.ui.active.type === "say" ? "Enter" : "Escape"); await wait(3); } };
(async () => {
  try { window.eval(scripts[scripts.length - 1].textContent); } catch (e) { errors.push("eval: " + e.stack); }
  for (let i = 0; i < 100 && !window.AZ.game; i++) await wait(50);
  const g = window.AZ.game, $ = id => window.document.getElementById(id), AZ = window.AZ;
  if (!g) { console.log("NO GAME", errors, $("status")?.textContent); process.exit(1); }
  try {
    await until(() => /New journey/.test(txt($("modal"))), "title");
    key("Enter");
    await until(() => /Who travels/.test(txt($("modal"))), "kinds");
    console.log("KINDS:", [...$("modal").querySelectorAll("li")].map(li => li.firstChild.textContent.replace("▶ ", "")).join(" | "));
    key("Enter");
    await until(() => /Departure:/.test(txt($("modal"))), "card");
    key("ArrowDown"); key("ArrowDown"); key("ArrowRight");
    await until(() => /Departure: autumn/.test(txt($("modal"))), "season cycled");
    console.log("CARD:", txt($("modal")).slice(txt($("modal")).indexOf("Era") + 3, 420));
    key("ArrowUp"); key("ArrowUp"); key("Enter");
    await until(() => g.s && g.ui.active, "intro");
    console.log("INTRO:", txt($("msg")).slice(0, 160));
    while (g.ui.active) { key("Enter"); await wait(3); }
    tick(2);
    console.log("HUD:", txt($("hud-loc")), "|", txt($("hud-trip")));
    if (AZ.Clock.doy0 !== 172) throw new Error("departure day not applied: " + AZ.Clock.doy0);
    // walk on land
    const start = [g.s.c, g.s.r];
    key("ArrowRight"); for (let i = 0; i < 6; i++) { g.anim = null; tick(1); await closeAll(g); } keyup("ArrowRight");
    console.log("WALKED:", start, "->", [g.s.c, g.s.r], "land", g.w.isLand(g.s.c, g.s.r), AZ.Clock.fmt(g.s.clock));
    if (g.s.c === start[0]) throw new Error("did not walk");
    // back to town: the gold task opens the harbour, the plan's ship is first; book it and wait aboard
    g.s.c = start[0]; g.s.r = start[1]; g.anim = null;
    key(" "); await until(() => g.ui.active && g.ui.active.type === "choose", "town menu");
    console.log("TOWN:", txt($("msg")).slice(0, 260));
    key("Enter"); await until(() => /harbour/i.test(txt($("msg"))), "harbour");
    console.log("HARBOUR:", txt($("msg")).slice(0, 260));
    key("Enter"); await wait(5);
    await closeAll(g);
    console.log("BOOKED:", g.s.voyage && g.s.voyage.ship, "sails", g.s.voyage && AZ.Clock.fmt(g.s.voyage.departAt), "purse", g.s.purse);
    if (!g.s.voyage) throw new Error("no booking");
    g.s.sup.food = 40; g.s.aboard = true; g.s.c = g.s.voyage.at[0]; g.s.r = g.s.voyage.at[1]; g.s.clock = g.s.voyage.departAt;
    for (let i = 0; i < 300; i++) { g.anim = null; tick(1); if (g.ui.active) await closeAll(g); }
    console.log("VOYAGE:", g.s.c, g.s.r, AZ.Clock.fmt(g.s.clock), g.s.voyage && g.s.voyage.state, "HUD:", txt($("hud-trip")).slice(0, 200));
    key("r"); await until(() => g.ui.active, "ship talk"); console.log("ABOARD MENU:", txt($("msg")).slice(0, 160)); key("Escape"); await wait(3);
    key("i"); tick(2); console.log("PANEL chars", $("panel").innerHTML.length);
    key("l"); tick(2); console.log("LEGEND", txt($("legend")));
    key("m"); tick(1); console.log("MAP", !!$("wmap")); key("m");
    key("j"); console.log("JOURNAL:", /Side stories/.test(txt($("modal"))), /The route/.test(txt($("modal"))), txt($("modal")).match(/No land joins[^.]*\./)?.[0]); key("Escape");
    // a marker event: stand on the nearest marker and interact
    const m = g.w.P.markers.find(x => x.type === "ruins");
    g.s.aboard = false; g.s.c = m.t[0]; g.s.r = m.t[1]; g.anim = null;
    console.log("BEFORE MARKER: modalKey", !!g.ui.modalKey, "active", g.ui.active && g.ui.active.type, "at", g.s.c, g.s.r, "markers here", !!g.w.markersAt.get(g.w.idx(g.s.c, g.s.r)));
    await closeAll(g);
    key(" "); await until(() => g.ui.active, "marker scene");
    console.log("MARKER:", txt($("msg")).slice(0, 200));
    key("Enter"); await wait(5); await closeAll(g);
    console.log("AFTER MARKER:", AZ.Clock.fmt(g.s.clock), "purse", g.s.purse, "cond", JSON.stringify(g.s.cond), "flags", Object.keys(g.s.flags).join(","));
  } catch (e) { errors.push(e.stack || String(e)); }
  console.log("saved:", !!window.localStorage.getItem(g.key));
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  process.exit(errors.length ? 1 : 0);
})();
