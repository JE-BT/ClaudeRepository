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
window.console.error = (...a) => errors.push(a.join(" "));
const scripts = [...window.document.querySelectorAll("script")].filter(s => !s.type || s.type === "text/javascript");
const tick = (n = 1) => { for (let i = 0; i < n; i++) { const q = rafQ; rafQ = []; q.forEach(f => { try { f(performance.now()); } catch (e) { errors.push("frame: " + e.stack); } }); } };
const key = (k, extra = {}) => window.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, ...extra }));
const keyup = k => window.dispatchEvent(new window.KeyboardEvent("keyup", { key: k }));
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  try { window.eval(scripts[scripts.length - 1].textContent); } catch (e) { errors.push("eval: " + e.stack); }
  for (let i = 0; i < 100 && !window.AZ.game; i++) await wait(50);
  const g = window.AZ.game, $ = id => window.document.getElementById(id);
  if (!g) { console.log("NO GAME", errors, $("status")?.textContent); process.exit(1); }
  tick(2);
  console.log("TITLE:", $("modal").textContent.replace(/\s+/g, " ").slice(0, 300));
  key("ArrowDown"); key("ArrowUp"); key("Enter"); await wait(10); tick(3);
  console.log("INTRO page:", $("msg").textContent.replace(/\s+/g, " ").slice(0, 200));
  for (let i = 0; i < 12 && g.ui.active; i++) { key("Enter"); await wait(5); }
  tick(3);
  console.log("HUD loc:", $("hud-loc").textContent, "| trip:", $("hud-trip").textContent);
  key(" "); await wait(10); tick(1);
  console.log("TOWN menu:", $("msg").textContent.replace(/\s+/g, " ").slice(0, 300));
  key("Enter"); await wait(10);  // the gold stage option is first
  for (let i = 0; i < 10 && g.ui.active && g.ui.active.type === "say"; i++) { key("Enter"); await wait(5); }
  // leave the town menu if still open
  for (let i = 0; i < 5 && g.ui.active; i++) { key("Escape"); await wait(5); }
  for (let i = 0; i < 6 && g.ui.active; i++) { key("Enter"); await wait(5); }
  tick(2);
  console.log("AFTER booking: stage", g.s.stage, "aboard", g.s.aboard, g.s.vessel && g.s.vessel.kind, "clock", window.AZ.Clock.fmt(g.s.clock));
  key("f"); for (let i = 0; i < 400; i++) { g.anim = null; tick(1); if (g.ui.active) key("Enter"); }
  console.log("AUTOPILOT: at", g.s.c, g.s.r, "clock", window.AZ.Clock.fmt(g.s.clock), "auto", g.s.auto, g.deltaText());
  key("i"); tick(2); console.log("PANEL chars", $("panel").innerHTML.length, $("panel").classList.contains("on"));
  key("l"); key("l"); tick(2); console.log("LEGEND", $("legend").textContent);
  key("m"); tick(1); console.log("MAP modal", !!$("wmap"), $("modal").classList.contains("on")); key("m");
  key("j"); console.log("JOURNAL", $("modal").textContent.replace(/\s+/g, " ").slice(0, 400)); key("Escape");
  key("h"); key("Escape");
  key("Escape"); await wait(5); console.log("MENU", $("msg").textContent.replace(/\s+/g, " ").slice(0, 160)); key("Escape"); await wait(5);
  key(" "); await wait(5); console.log("SPACE at sea:", $("msg").textContent.replace(/\s+/g, " ").slice(0, 240)); key("Escape"); key("Enter"); await wait(5);
  key("ArrowLeft"); for (let i = 0; i < 5; i++) { g.anim = null; tick(1); } keyup("ArrowLeft");
  key("+"); tick(1); key("-"); tick(1);
  key("r"); await wait(5); key("Enter"); await wait(5); tick(1);
  console.log("saved:", !!window.localStorage.getItem(g.key));
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  process.exit(errors.length ? 1 : 0);
})();
