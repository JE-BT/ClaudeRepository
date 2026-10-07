// Node harness: loads the engine without a browser, with @napi-rs/canvas for drawing.
const fs = require("fs"), path = require("path"), vm = require("vm");
const ROOT = path.resolve(__dirname, "..");
let canvasLib = null;
try { canvasLib = require(process.env.CANVAS_MODULE || "@napi-rs/canvas"); } catch (e) { canvasLib = null; }
function loadEngine() {
  const src = fs.readdirSync(path.join(ROOT, "engine/src")).filter(f => f.endsWith(".js")).sort()
    .map(f => fs.readFileSync(path.join(ROOT, "engine/src", f), "utf8")).join("\n");
  vm.runInThisContext(src, { filename: "engine.js" });
  globalThis.AZ.CONTENT = JSON.parse(fs.readFileSync(path.join(ROOT, "azrpg/data/descriptions_azork.json"), "utf8"));
  return globalThis.AZ;
}
async function loadWorld(htmlPath) {
  const AZ = loadEngine();
  const html = fs.readFileSync(htmlPath, "utf8");
  const b64 = html.match(/<script id="pack" type="application\/octet-stream">([^<]+)<\/script>/)[1];
  const P = await AZ.loadPack(b64);
  const w = new AZ.World(P);
  const mk = canvasLib ? (W, H) => canvasLib.createCanvas(W, H) : null;
  return { AZ, P, w, mk, canvasLib };
}
function stubUI() {
  const said = [];
  return {
    said, el: {}, busy: () => false,
    say: async (pages) => { said.push(...(Array.isArray(pages) ? pages : [pages])); },
    choose: async (prompt, options) => { said.push("CHOOSE " + prompt + " :: " + options.map(o => o.label).join(" | ")); const k = options.findIndex(o => o.act === "stage"); return k >= 0 ? k : options.length - 1; },
    toast: h => said.push("TOAST " + h), banner: (t, s) => said.push("BANNER " + t + " / " + s), modal() {}, closeModal() {},
  };
}
module.exports = { loadEngine, loadWorld, stubUI, ROOT };
