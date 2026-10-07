"use strict";
// ---------------------------------------------------------------------------------------------
// azrpg engine — utilities. Everything random in the world is seeded (by tile, cell, burg or
// stage), so the same place always looks and speaks the same way.
// ---------------------------------------------------------------------------------------------
const AZ = (typeof globalThis !== "undefined" ? globalThis : window).AZ = {};

AZ.U = (() => {
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;

  function hash32(a, b = 0, c = 0) {
    let h = (Math.imul(a | 0, 0x27d4eb2d) ^ Math.imul(b | 0, 0x165667b1) ^ Math.imul(c | 0, 0x9e3779b1)) >>> 0;
    h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
    h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
    return (h ^ (h >>> 16)) >>> 0;
  }
  const rnd2 = (x, y, s = 0) => hash32(x, y, s) / 4294967296;

  function strSeed(str) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619) >>> 0;
    return h;
  }
  function rng(seed) {
    let a = (typeof seed === "string" ? strSeed(seed) : seed) >>> 0;
    const f = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    f.pick = arr => arr[Math.floor(f() * arr.length)];
    f.int = (a, b) => a + Math.floor(f() * (b - a + 1));
    f.chance = p => f() < p;
    return f;
  }

  // smooth value noise on the tile lattice, used for decoration and ground variety
  function vnoise(x, y, scale, s) {
    const fx = x / scale, fy = y / scale;
    const x0 = Math.floor(fx), y0 = Math.floor(fy);
    const tx = fx - x0, ty = fy - y0;
    const sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty);
    const a = rnd2(x0, y0, s), b = rnd2(x0 + 1, y0, s), c = rnd2(x0, y0 + 1, s), d = rnd2(x0 + 1, y0 + 1, s);
    return lerp(lerp(a, b, sx), lerp(c, d, sx), sy);
  }

  const rn = (v, d = 0) => { const p = 10 ** d; return Math.round(v * p) / p; };
  function si(n) {
    if (n >= 1e9) return rn(n / 1e9, 1) + "B";
    if (n >= 1e8) return rn(n / 1e6) + "M";
    if (n >= 1e6) return rn(n / 1e6, 1) + "M";
    if (n >= 1e4) return rn(n / 1e3) + "K";
    if (n >= 1e3) return rn(n / 1e3, 1) + "K";
    return String(rn(n));
  }
  const num = (n, d = 0) => Number(rn(n, d)).toLocaleString("en-US");

  function dms(coord, type) {
    const deg = Math.floor(Math.abs(coord));
    const mf = (Math.abs(coord) - deg) * 60;
    const min = Math.floor(mf);
    const card = type === "lat" ? (coord >= 0 ? "N" : "S") : coord >= 0 ? "E" : "W";
    return `${deg}°${String(min).padStart(2, "0")}′${card}`;
  }

  const COMPASS = ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"];
  function compass(dx, dy) {
    if (!dx && !dy) return "here";
    const a = Math.atan2(-dy, dx);
    return COMPASS[(Math.round(a / (Math.PI / 4)) + 8) % 8];
  }
  const ARROWS = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"];
  function arrow(dx, dy) {
    if (!dx && !dy) return "•";
    return ARROWS[(Math.round(Math.atan2(-dy, dx) / (Math.PI / 4)) + 8) % 8];
  }

  function hex2rgb(h) {
    if (!h || h[0] !== "#") return [128, 128, 128];
    if (h.length === 4) h = "#" + h[1] + h[1] + h[2] + h[2] + h[3] + h[3];
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  const rgb2hex = c => "#" + c.map(v => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
  const shade = (c, f) => (f >= 0 ? mix(c, [255, 255, 255], f) : mix(c, [0, 0, 0], -f));
  const css = c => `rgb(${c.map(v => clamp(Math.round(v), 0, 255)).join(",")})`;

  const esc = s => String(s ?? "").replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const plural = (n, w, p) => `${n} ${n === 1 ? w : p || w + "s"}`;
  const article = w => (/^[aeiou]/i.test(w) ? "an " : "a ") + w;

  function ramp(stops, t) {
    // stops: [[t, [r,g,b]], ...] ascending
    if (t <= stops[0][0]) return stops[0][1];
    for (let i = 1; i < stops.length; i++) {
      if (t <= stops[i][0]) {
        const [t0, c0] = stops[i - 1], [t1, c1] = stops[i];
        return mix(c0, c1, (t - t0) / (t1 - t0));
      }
    }
    return stops[stops.length - 1][1];
  }

  return { clamp, lerp, hash32, rnd2, strSeed, rng, vnoise, rn, si, num, dms, compass, arrow, hex2rgb, rgb2hex,
           mix, shade, css, esc, cap, plural, article, ramp };
})();
