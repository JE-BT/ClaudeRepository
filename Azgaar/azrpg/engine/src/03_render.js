// ---------------------------------------------------------------------------------------------
// Rendering. The world is painted in 32x32-tile chunks when they first come into view and kept
// in a cache: ground pixels (biome colour, relief shading, coast, rivers, roads, sea lanes, ice)
// and a decor layer (relief icons, biome plants, settlements, markers, units, piers).
// ---------------------------------------------------------------------------------------------
AZ.LENSES = (() => {
  const U = AZ.U;
  const cat = (key, list) => (w, cell) => { const id = w.C[key][cell]; const o = id && w.P[list][id]; return o && !o.removed ? U.hex2rgb(o.color) : null; };
  const name = (key, list, f = "name") => (w, cell) => { const id = w.C[key][cell]; const o = id && w.P[list][id]; return o ? o[f] || o.name : "none"; };
  const H = [[0, [20, 60, 140]], [0.19, [70, 140, 200]], [0.2, [40, 130, 60]], [0.45, [200, 190, 90]], [0.7, [150, 90, 50]], [1, [250, 250, 250]]];
  const T = [[-30, [80, 40, 160]], [-10, [60, 120, 220]], [0, [160, 220, 240]], [10, [130, 210, 120]], [20, [240, 210, 80]], [30, [220, 70, 40]]];
  const Pp = [[0, [230, 210, 160]], [500, [200, 220, 140]], [1500, [90, 180, 160]], [3000, [40, 90, 200]], [6000, [40, 30, 140]]];
  return [
    { id: "none", name: "No lens" },
    { id: "biome", name: "Biome", tile: false, color: (w, cell) => U.hex2rgb(w.P.biomes[w.C.biome[cell]]?.color), label: (w, cell) => w.P.biomes[w.C.biome[cell]]?.name },
    { id: "height", name: "Height", tile: true, color: (w, cell, c, r) => U.ramp(H, w.h(c, r) / 100), label: (w, cell, c, r) => (w.isLand(c, r) ? w.heightStr(w.h(c, r)) : "depth " + w.heightStr(w.h(c, r), true)) + " (tile, mixed)" },
    { id: "temperature", name: "Temperature", tile: true, color: (w, cell, c, r) => U.ramp(T, w.tempC(c, r)), label: (w, cell, c, r) => w.temp(w.tempC(c, r)) + " mean" },
    { id: "precipitation", name: "Precipitation", tile: true, color: (w, cell, c, r) => (w.isLand(c, r) ? U.ramp(Pp, w.precMM(c, r)) : null), label: (w, cell, c, r) => U.num(w.precMM(c, r)) + " mm" },
    { id: "state", name: "State", color: cat("state", "states"), label: (w, cell) => { const s = w.P.states[w.C.state[cell]]; return w.C.state[cell] ? s.fullName || s.name : "neutral lands"; } },
    { id: "province", name: "Province", color: cat("province", "provinces"), label: name("province", "provinces", "fullName") },
    { id: "culture", name: "Culture", color: cat("culture", "cultures"), label: name("culture", "cultures") },
    { id: "religion", name: "Religion", color: cat("religion", "religions"), label: name("religion", "religions") },
    { id: "population", name: "Population", color: (w, cell) => (w.C.type[cell] ? null : U.ramp([[0, [250, 245, 220]], [2, [240, 180, 90]], [8, [200, 60, 40]], [20, [90, 0, 30]]], w.C.pop[cell])), label: (w, cell) => U.si(w.population(cell)[0]) + " rural in this cell" },
    { id: "market", name: "Market region", color: (w, cell) => { const m = w.P.markets.find(k => k.i === w.C.market[cell]); return m ? U.hex2rgb(m.color) : null; }, label: (w, cell) => { const m = w.P.markets.find(k => k.i === w.C.market[cell]); return m ? `${w.P.burgs[m.centerBurgId]?.name} market` : "no market"; } },
    { id: "resource", name: "Resource", color: (w, cell) => { const g = w.P.goods.find(x => x.i === w.C.good[cell]); return g ? U.hex2rgb(g.color) : null; }, label: (w, cell) => w.P.goods.find(x => x.i === w.C.good[cell])?.name || "none" },
    { id: "zones", name: "Zones", color: (w, cell) => { const z = w.zonesOfCell(cell)[0]; return z ? U.hex2rgb(z.color || "#ff0000") : null; }, label: (w, cell) => w.zonesOfCell(cell).map(z => `${z.name} (${z.type})`).join(", ") || "none" },
  ];
})();

AZ.Renderer = class {
  constructor(world, art, canvas, mk) {
    this.w = world; this.art = art; this.cv = canvas; this.mk = mk;
    this.CH = 32; this.zoom = 2;
    this.cache = new Map(); this.lensCache = new Map();
    this.piers = new Set([...world.ports.values()].map(([c, r]) => world.idx(c, r)));
    this.shadeK = 0.025;
  }
  // ------------------------------------------------------------------ ground
  paintGround(cx, cy) {
    const w = this.w, U = AZ.U, CH = this.CH, N = CH * 16, rnd2 = U.rnd2, clamp = U.clamp;
    const cv = this.mk(N, N), ctx = cv.getContext("2d"), img = ctx.createImageData(N, N);
    const d32 = new Uint32Array(img.data.buffer, img.data.byteOffset, N * N);
    const px32 = (o, R, G, B) => { d32[o] = 0xff000000 | ((B < 0 ? 0 : B > 255 ? 255 : B | 0) << 16) | ((G < 0 ? 0 : G > 255 ? 255 : G | 0) << 8) | (R < 0 ? 0 : R > 255 ? 255 : R | 0); };
    const land = (c, r) => (w.inb(c, r) ? w.isLand(c, r) : false);
    const shade = (c, r) => (land(c, r) ? clamp(((w.h(c - 1, r) - w.h(c + 1, r)) + (w.h(c, r - 1) - w.h(c, r + 1))) * this.shadeK, -0.3, 0.3) : 0);
    const DEEP = [[0, [28, 58, 122]], [10, [42, 86, 158]], [19, [66, 122, 190]]];
    const waterCol = (c, r) => (!w.inb(c, r) ? [28, 58, 122] : w.isLand(c, r) ? [66, 122, 190] : w.ctype(c, r) === 2 ? [84, 144, 202] : U.ramp(DEEP, w.h(c, r)));
    const lookOf = (c, r) => w.biomeLook[w.C.biome[w.cell(c, r)]];
    const ROCK = [138, 128, 116], SNOW = [236, 242, 246];
    this._gc = this._gc || new Map();
    const groundCol = (c, r) => {
      const look = lookOf(c, r), rel = w.reliefAt(c, r);
      if (!(rel && /mount/i.test(rel.icon))) return look.col;
      let v = this._gc.get(look);
      if (!v) { v = U.mix(look.col, ROCK, 0.5); this._gc.set(look, v); }
      return v;
    };
    const armTest = (bits, px, py, hw) => {
      const ax = Math.abs(px - 7.5), ay = Math.abs(py - 7.5);
      if (ax < hw && ay < hw) return true;
      return ((bits & 1) && ax < hw && py < 8) || ((bits & 4) && ax < hw && py >= 8) || ((bits & 8) && ay < hw && px < 8) || ((bits & 2) && ay < hw && px >= 8);
    };
    for (let ty = 0; ty < CH; ty++) for (let tx = 0; tx < CH; tx++) {
      const c = cx * CH + tx, r = cy * CH + ty;
      const o0 = ty * 16 * N + tx * 16;
      if (!w.inb(c, r)) {
        for (let py = 0; py < 16; py++) for (let px = 0; px < 16; px++) px32(o0 + py * N + px, 10, 12, 24);
        continue;
      }
      const L = land(c, r);
      const nl = [land(c, r - 1), land(c + 1, r), land(c, r + 1), land(c - 1, r)];
      const dl = [land(c - 1, r - 1), land(c + 1, r - 1), land(c + 1, r + 1), land(c - 1, r + 1)];
      const anyLandNb = nl[0] || nl[1] || nl[2] || nl[3] || dl[0] || dl[1] || dl[2] || dl[3];
      const B = w.bits(c, r), ice = w.ice(c, r);
      let base, nbCol = null, snowP = 0, sc = null, rw = 0, corners = null;
      if (L) {
        base = groundCol(c, r);
        const nb = [[c, r - 1], [c + 1, r], [c, r + 1], [c - 1, r]].map(([a, b]) => (land(a, b) ? groundCol(a, b) : null));
        if (nb.some(x => x && x !== base)) nbCol = nb.map(x => (x && x !== base ? x : null));
        const tc = w.tempC(c, r), look = lookOf(c, r);
        snowP = look.kind === "snow" ? 0 : tc < -2 ? clamp((-2 - tc) / 14, 0, 0.8) : 0;
        if (ice === 2) snowP = 0.92;
        const s0 = shade(c, r);
        const sA = (a, b) => (s0 + shade(c + a, r) + shade(c, r + b) + shade(c + a, r + b)) / 4;
        sc = [sA(-1, -1), sA(1, -1), sA(1, 1), sA(-1, 1)];
        if (B.river) { const q = w.river(c, r)?.discharge || 0; rw = q >= 1500 ? 3 : q >= 300 ? 2 : q >= 40 ? 1.5 : 1; }
        const cf = [[!nl[0] && !nl[3], 0, 0], [!nl[0] && !nl[1], 16, 0], [!nl[2] && !nl[1], 16, 16], [!nl[2] && !nl[3], 0, 16]].filter(x => x[0]);
        if (cf.length) corners = cf;
      }
      // water colour at the four corners, for a smooth depth gradient
      let wc = null;
      if (!L || corners) {
        const wA = (a, b) => { const t = [waterCol(c, r), waterCol(c + a, r), waterCol(c, r + b), waterCol(c + a, r + b)]; return [0, 1, 2].map(k => (t[0][k] + t[1][k] + t[2][k] + t[3][k]) / 4); };
        wc = [wA(-1, -1), wA(1, -1), wA(1, 1), wA(-1, 1)];
      }
      for (let py = 0; py < 16; py++) for (let px = 0; px < 16; px++) {
        const gx = c * 16 + px, gy = r * 16 + py;
        let R, G, Bl, water = !L, shoreD = 99;
        const fx = (px + 0.5) / 16, fy = (py + 0.5) / 16;
        if (corners) for (let k = 0; k < corners.length; k++) {
          const dx = px + 0.5 - corners[k][1], dy = py + 0.5 - corners[k][2];
          if (dx * dx + dy * dy > 30) continue;
          const q = Math.sqrt(dx * dx + dy * dy) - 3.2 - 1.2 * rnd2(gx, gy, 41);
          if (q < 0) { water = true; shoreD = Math.min(shoreD, 3 + q); }
        }
        if (!water) {
          let col = base;
          if (nbCol && (py < 3 || py > 12 || px < 3 || px > 12)) for (let k = 0; k < 4; k++) if (nbCol[k]) {
            const dd = k === 0 ? py : k === 1 ? 15 - px : k === 2 ? 15 - py : px;
            if (dd < 3 && rnd2(gx, gy, 7 + k) < (3 - dd) * 0.22) col = nbCol[k];
          }
          if (snowP && rnd2(gx, gy, 5) < snowP) col = SNOW;
          const s = (sc[0] * (1 - fx) + sc[1] * fx) * (1 - fy) + (sc[3] * (1 - fx) + sc[2] * fx) * fy;
          const f = 1 + s + (rnd2(gx, gy, 3) - 0.5) * 0.1;
          R = col[0] * f; G = col[1] * f; Bl = col[2] * f;
          if (rw) {
            if (armTest(B.river, px, py, rw)) { if (rnd2(gx, gy, 8) < 0.04) { R = 150; G = 200; Bl = 240; } else { R = 62; G = 122; Bl = 196; } }
            else if (armTest(B.river, px, py, rw + 1)) { R *= 0.78; G *= 0.78; Bl *= 0.78; }
          }
          if (B.road || B.trail) {
            const onRoad = B.road && armTest(B.road, px, py, 1), onTrail = !onRoad && B.trail && armTest(B.trail, px, py, 0.6) && (px + py) % 3 !== 0;
            if (onRoad || onTrail) {
              if (rw && armTest(B.river, px, py, rw + 1)) { R = 126; G = 88; Bl = 52; }
              else if (onRoad) { R = 166; G = 128; Bl = 86; } else { R = 190; G = 160; Bl = 112; }
            }
          }
        } else {
          R = (wc[0][0] * (1 - fx) + wc[1][0] * fx) * (1 - fy) + (wc[3][0] * (1 - fx) + wc[2][0] * fx) * fy;
          G = (wc[0][1] * (1 - fx) + wc[1][1] * fx) * (1 - fy) + (wc[3][1] * (1 - fx) + wc[2][1] * fx) * fy;
          Bl = (wc[0][2] * (1 - fx) + wc[1][2] * fx) * (1 - fy) + (wc[3][2] * (1 - fx) + wc[2][2] * fx) * fy;
          if (shoreD === 99 && anyLandNb) {
            if (nl[0]) shoreD = Math.min(shoreD, py + 0.5);
            if (nl[1]) shoreD = Math.min(shoreD, 15.5 - px);
            if (nl[2]) shoreD = Math.min(shoreD, 15.5 - py);
            if (nl[3]) shoreD = Math.min(shoreD, px + 0.5);
            if (dl[0]) shoreD = Math.min(shoreD, Math.sqrt((px + 0.5) ** 2 + (py + 0.5) ** 2));
            if (dl[1]) shoreD = Math.min(shoreD, Math.sqrt((15.5 - px) ** 2 + (py + 0.5) ** 2));
            if (dl[2]) shoreD = Math.min(shoreD, Math.sqrt((15.5 - px) ** 2 + (15.5 - py) ** 2));
            if (dl[3]) shoreD = Math.min(shoreD, Math.sqrt((px + 0.5) ** 2 + (15.5 - py) ** 2));
          }
          const sandT = shoreD < 9 ? 1.4 + 1.4 * U.vnoise(gx, gy, 5, 9) : 0;
          if (shoreD < sandT) { R = 222; G = 204; Bl = 150; }
          else if (shoreD < sandT + 1.1) { R = 214; G = 232; Bl = 242; }
          else {
            if (shoreD < sandT + 6) { const t = (1 - (shoreD - sandT) / 6) * 0.45; R += (120 - R) * t; G += (180 - G) * t; Bl += (220 - Bl) * t; }
            if (rnd2(gx, gy, 77) < 0.012) { R += (255 - R) * 0.3; G += (255 - G) * 0.3; Bl += (255 - Bl) * 0.3; }
            if (B.sea && (px + py + c + r) % 4 < 2 && armTest(B.sea, px, py, 0.6)) { R += (255 - R) * 0.28; G += (255 - G) * 0.28; Bl += (255 - Bl) * 0.28; }
            if (ice === 1) { const v = U.vnoise(gx, gy, 4, 21); if (v > 0.58) { R = 232; G = 240; Bl = 246; } else if (v > 0.55) { R = 196; G = 212; Bl = 226; } }
          }
        }
        px32(o0 + py * N + px, R, G, Bl);
      }
    }
    ctx.putImageData(img, 0, 0);
    return cv;
  }
  // ------------------------------------------------------------------ decor
  paintDecor(cx, cy) {
    const w = this.w, U = AZ.U, CH = this.CH, N = CH * 16, art = this.art;
    const cv = this.mk(N, N + 16), x = cv.getContext("2d");
    x.imageSmoothingEnabled = false;
    const POS = [[[4, 14]], [[1, 11], [8, 15]], [[0, 10], [8, 12], [3, 16]], [[6, 12], [1, 16], [10, 16]]];
    for (let ty = 0; ty < CH; ty++) for (let tx = 0; tx < CH; tx++) {
      const c = cx * CH + tx, r = cy * CH + ty;
      if (!w.inb(c, r)) continue;
      const X = tx * 16, Y = ty * 16 + 16, id = w.idx(c, r), L = w.isLand(c, r);
      if (this.piers.has(id)) x.drawImage(art.pier(), X, Y);
      const b = w.burgAt.get(id);
      if (b) { const s = art.burg(b); x.drawImage(s, X, Y + 16 - s.height); continue; }
      const ms = w.markersAt.get(id);
      if (ms) {
        const m = ms[0];
        const s = m.type === "volcanoes" ? art.relief("vulcan", [120, 110, 100], 1) : art.marker(m.type);
        x.drawImage(s, X + ((16 - s.width) >> 1), Y + 16 - s.height);
        continue;
      }
      const us = (w.unitsAt.get(id) || []).filter(u => !(AZ.sim && AZ.sim.regs.some(r => r.id === `${u.state}:${u.i}`)));
      if (us.length) { const s = art.unit(us[0]); x.drawImage(s, X, Y + 16 - s.height); continue; }
      if (!L) continue;
      const B = w.bits(c, r);
      if (B.road || B.trail || B.river) continue;
      const look = w.biomeLook[w.C.biome[w.cell(c, r)]];
      const rel = w.reliefAt(c, r);
      if (rel) {
        const icon = /snow/i.test(rel.icon) ? "mountSnow" : /mount|vulcan/i.test(rel.icon) ? "mount" : "hill";
        const hl = icon === "hill";
        if (U.rnd2(c, r, 31) > (hl ? 0.42 : 0.6)) continue;
        const s = art.relief(icon, look.col, U.hash32(c, r, 3) % 3);
        const ox = Math.round((U.rnd2(c, r, 32) - 0.5) * 6), oy = Math.round(U.rnd2(c, r, 33) * 3);
        x.drawImage(s, X + ox, Y + 16 - s.height + oy - (hl ? 2 : 0));
        continue;
      }
      if (!look.icons.length || !look.density) continue;
      if (U.rnd2(c, r, 11) > U.clamp(look.density / 140, 0.02, 0.92)) continue;
      const tot = look.icons.reduce((a, [, wt]) => a + wt, 0);
      let pick = U.rnd2(c, r, 12) * tot, icon = look.icons[0][0];
      for (const [t, wt] of look.icons) { if ((pick -= wt) <= 0) { icon = t; break; } }
      const tree = !/grass|dune|cactus|swamp|dead/i.test(icon);
      const n = tree ? (look.density >= 110 ? 2 + (U.rnd2(c, r, 13) < 0.5 ? 1 : 0) : 1) : 1 + (U.rnd2(c, r, 13) < 0.35 ? 1 : 0);
      const set = n === 3 && U.rnd2(c, r, 14) < 0.5 ? POS[3] : POS[Math.min(n, 3) - 1];
      for (const [ox, bot] of set) {
        const s = art.plant(icon, U.hash32(c, r, ox) & 1);
        x.drawImage(s, X + Math.min(ox, 16 - s.width), Y + bot - s.height);
      }
    }
    return cv;
  }
  chunk(cx, cy) {
    const k = cy * 4096 + cx;
    let ch = this.cache.get(k);
    if (!ch) {
      ch = { g: this.paintGround(cx, cy), d: this.paintDecor(cx, cy) };
      this.cache.set(k, ch);
      if (this.cache.size > 90) this.cache.delete(this.cache.keys().next().value);
    }
    return ch;
  }
  lensChunk(lens, cx, cy) {
    const k = `${lens.id}:${cy * 4096 + cx}`;
    let cv = this.lensCache.get(k);
    if (!cv) {
      const w = this.w, CH = this.CH;
      cv = this.mk(CH, CH);
      const ctx = cv.getContext("2d"), img = ctx.createImageData(CH, CH);
      for (let ty = 0; ty < CH; ty++) for (let tx = 0; tx < CH; tx++) {
        const c = cx * CH + tx, r = cy * CH + ty;
        if (!w.inb(c, r)) continue;
        const col = lens.color(w, w.cell(c, r), c, r);
        if (!col) continue;
        const o = (ty * CH + tx) * 4;
        img.data[o] = col[0]; img.data[o + 1] = col[1]; img.data[o + 2] = col[2]; img.data[o + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
      this.lensCache.set(k, cv);
      if (this.lensCache.size > 200) this.lensCache.delete(this.lensCache.keys().next().value);
    }
    return cv;
  }
  // ------------------------------------------------------------------ whole world image (maps)
  worldImage() {
    if (this._world) return this._world;
    const w = this.w, U = AZ.U, cv = this.mk(w.cols, w.rows), ctx = cv.getContext("2d");
    const img = ctx.createImageData(w.cols, w.rows), d = img.data;
    const DEEP = [[0, [28, 58, 122]], [10, [42, 86, 158]], [19, [66, 122, 190]]];
    for (let r = 0; r < w.rows; r++) for (let c = 0; c < w.cols; c++) {
      let col;
      if (w.isLand(c, r)) {
        const look = w.biomeLook[w.C.biome[w.cell(c, r)]];
        const s = U.clamp(((w.h(c - 1, r) - w.h(c + 1, r)) + (w.h(c, r - 1) - w.h(c, r + 1))) * 0.03, -0.35, 0.35);
        col = U.shade(look.col, s);
        const rel = w.reliefAt(c, r);
        if (rel && /mount/i.test(rel.icon)) col = U.mix(col, /Snow/.test(rel.icon) ? [240, 244, 248] : [150, 140, 128], 0.5);
        const B = w.bits(c, r);
        if (B.river) col = [70, 128, 196];
        if (B.road) col = [150, 100, 60];
      } else col = w.ctype(c, r) === 2 ? [84, 144, 202] : U.ramp(DEEP, w.h(c, r));
      const o = (r * w.cols + c) * 4;
      d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    return (this._world = cv);
  }
  lensWorld(lens) {
    this._lensW = this._lensW || {};
    if (this._lensW[lens.id]) return this._lensW[lens.id];
    const w = this.w, cv = this.mk(w.cols, w.rows), ctx = cv.getContext("2d"), img = ctx.createImageData(w.cols, w.rows);
    const cache = new Map();
    for (let r = 0; r < w.rows; r++) for (let c = 0; c < w.cols; c++) {
      const cell = w.cell(c, r);
      let col;
      if (lens.tile) col = lens.color(w, cell, c, r);
      else { if (!cache.has(cell)) cache.set(cell, lens.color(w, cell, c, r)); col = cache.get(cell); }
      if (!col) continue;
      const o = (r * w.cols + c) * 4;
      img.data[o] = col[0]; img.data[o + 1] = col[1]; img.data[o + 2] = col[2]; img.data[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    return (this._lensW[lens.id] = cv);
  }
  // paint one missing chunk just outside the view, so walking and sailing do not stall
  prefetch(camX, camY) {
    const S = 16 * this.zoom, W = this.cv.width, H = this.cv.height, CH = this.CH, w = this.w;
    const left = camX - W / S / 2, top = camY - H / S / 2;
    const c0 = Math.floor(left / CH) - 1, c1 = Math.floor((left + W / S) / CH) + 1, r0 = Math.floor(top / CH) - 1, r1 = Math.floor((top + H / S) / CH) + 1;
    for (let cy = r0; cy <= r1; cy++) for (let cx = c0; cx <= c1; cx++) {
      if (cx < 0 || cy < 0 || cx * CH >= w.cols || cy * CH >= w.rows) continue;
      if (!this.cache.has(cy * 4096 + cx)) { this.chunk(cx, cy); return true; }
    }
    return false;
  }
  // ------------------------------------------------------------------ frame
  draw(v) {
    const cv = this.cv, ctx = cv.getContext("2d"), w = this.w, CH = this.CH;
    ctx.imageSmoothingEnabled = false;
    const S = 16 * this.zoom, W = cv.width, H = cv.height;
    const left = v.camX - W / S / 2, top = v.camY - H / S / 2;
    const toX = c => Math.round((c - left) * S), toY = r => Math.round((r - top) * S);
    ctx.fillStyle = "#0a0c18"; ctx.fillRect(0, 0, W, H);
    const c0 = Math.floor(left / CH), c1 = Math.floor((left + W / S) / CH), r0 = Math.floor(top / CH), r1 = Math.floor((top + H / S) / CH);
    const CS = CH * S;
    for (let cy = r0; cy <= r1; cy++) for (let cx = c0; cx <= c1; cx++) {
      if (cx < 0 || cy < 0 || cx * CH >= w.cols || cy * CH >= w.rows) continue;
      ctx.drawImage(this.chunk(cx, cy).g, toX(cx * CH), toY(cy * CH), CS, CS);
    }
    // course of the current stage, gold
    if (v.course) {
      ctx.fillStyle = "rgba(245,197,66,0.85)";
      const sz = Math.max(2, this.zoom * 2);
      for (const [c, r] of v.course) {
        if (c < left - 1 || c > left + W / S + 1 || r < top - 1 || r > top + H / S + 1) continue;
        ctx.fillRect(toX(c + 0.5) - sz / 2, toY(r + 0.5) - sz / 2, sz, sz);
      }
    }
    const sprites = (v.sprites || []).slice().sort((a, b) => a.r - b.r);
    for (let cy = r0; cy <= r1; cy++) {
      for (let cx = c0; cx <= c1; cx++) {
        if (cx < 0 || cy < 0 || cx * CH >= w.cols || cy * CH >= w.rows) continue;
        ctx.drawImage(this.chunk(cx, cy).d, toX(cx * CH), toY(cy * CH) - 16 * this.zoom, CS, CS + 16 * this.zoom);
      }
    }
    for (const s of sprites) ctx.drawImage(s.img, toX(s.c) + ((16 - s.img.width) * this.zoom) / 2, toY(s.r + 1) - s.img.height * this.zoom, s.img.width * this.zoom, s.img.height * this.zoom);
    // targets: next stop gold, waypoint teal
    const t = (v.time || 0) / 400;
    for (const [tile, col] of [[v.goal, "245,197,66"], [v.waypoint, "79,209,197"]]) {
      if (!tile) continue;
      const a = 0.55 + 0.45 * Math.sin(t);
      ctx.strokeStyle = `rgba(${col},${a})`; ctx.lineWidth = Math.max(2, this.zoom);
      const X = toX(tile[0] + 0.5), Y = toY(tile[1] + 0.5), R = S * (0.7 + 0.15 * Math.sin(t));
      ctx.beginPath(); ctx.moveTo(X, Y - R); ctx.lineTo(X + R, Y); ctx.lineTo(X, Y + R); ctx.lineTo(X - R, Y); ctx.closePath(); ctx.stroke();
    }
    if (v.lens && v.lens.id !== "none") {
      ctx.globalAlpha = 0.45;
      for (let cy = r0; cy <= r1; cy++) for (let cx = c0; cx <= c1; cx++) {
        if (cx < 0 || cy < 0 || cx * CH >= w.cols || cy * CH >= w.rows) continue;
        ctx.drawImage(this.lensChunk(v.lens, cx, cy), toX(cx * CH), toY(cy * CH), CS, CS);
      }
      ctx.globalAlpha = 1;
    }
    // the plan's nights at anchor (small gold rings) and the autopilot's path (teal)
    if (v.nights) { ctx.strokeStyle = "rgba(245,197,66,0.9)"; ctx.lineWidth = 1; for (const [c, r] of v.nights) { if (c < left - 1 || c > left + W / S + 1 || r < top - 1 || r > top + H / S + 1) continue; ctx.beginPath(); ctx.arc(toX(c + 0.5), toY(r + 0.5), S * 0.35, 0, 7); ctx.stroke(); } }
    if (v.path) { ctx.fillStyle = "rgba(79,209,197,0.8)"; const sz = Math.max(2, this.zoom * 1.5); for (const [c, r] of v.path) { if (c < left - 1 || c > left + W / S + 1 || r < top - 1 || r > top + H / S + 1) continue; ctx.fillRect(toX(c + 0.5) - sz / 2, toY(r + 0.5) - sz / 2, sz, sz); } }
    if (v.light && v.light.a > 0) {
      ctx.globalCompositeOperation = "multiply";
      ctx.fillStyle = `rgba(${v.light.rgb.join(",")},${v.light.a})`;
      ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = "source-over";
    }
    // weather from the map's precipitation, the season and the latitude
    const wk = v.weather, ts = (v.time || 0) / 1000;
    if (wk === "fog") { ctx.fillStyle = "rgba(220,226,232,0.35)"; ctx.fillRect(0, 0, W, H); }
    if (wk === "storm") { ctx.fillStyle = "rgba(20,24,40,0.28)"; ctx.fillRect(0, 0, W, H); }
    if (wk === "rain" || wk === "storm" || wk === "snow") {
      const n = wk === "storm" ? 260 : 140, snow = wk === "snow";
      ctx.strokeStyle = snow ? "rgba(255,255,255,0.85)" : "rgba(190,210,240,0.55)"; ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const sp = snow ? 40 : 600, x = (AZ.U.rnd2(i, 1, 7) * W + ts * (snow ? 15 : 160)) % W, y = (AZ.U.rnd2(i, 2, 7) * H + ts * sp) % H;
        if (snow) ctx.rect(x, y, 2, 2); else { ctx.moveTo(x, y); ctx.lineTo(x - 3, y + 10); }
      }
      if (snow) ctx.fill(); else ctx.stroke();
    }
  }
};
