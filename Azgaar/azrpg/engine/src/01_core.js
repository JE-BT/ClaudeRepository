// ---------------------------------------------------------------------------------------------
// Pack decoding, names and the World: every question about a tile goes through here.
// ---------------------------------------------------------------------------------------------
AZ.loadPack = async function (src) {
  let bin = src;
  if (typeof src === "string") {
    const s = atob(src.replace(/\s+/g, ""));
    bin = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) bin[i] = s.charCodeAt(i);
  }
  const stream = new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));
  const buf = new Uint8Array(await new Response(stream).arrayBuffer());
  if (String.fromCharCode(buf[0], buf[1], buf[2], buf[3]) !== "AZRP") throw new Error("Not an azrpg world pack");
  const n = (buf[4] | (buf[5] << 8) | (buf[6] << 16) | (buf[7] << 24)) >>> 0;
  const P = JSON.parse(new TextDecoder().decode(buf.subarray(8, 8 + n)));
  const base = 8 + n;
  P.R = {};
  for (const [name, r] of Object.entries(P.rasters)) {
    const bytes = buf.slice(base + r.offset, base + r.offset + r.length);
    let arr = r.type === "u16" ? new Uint16Array(bytes.buffer, 0, r.length / 2) : bytes;
    if (r.encoding === "rowdelta") {
      const { cols, rows } = P.grid;
      for (let y = 0; y < rows; y++) {
        const o = y * cols;
        for (let x = 1; x < cols; x++) arr[o + x] = (arr[o + x - 1] + arr[o + x]) & 255;
      }
    }
    P.R[name] = arr;
  }
  return P;
};

// Azgaar's Markov name generator (src/generators/names-generator.ts), with a seeded random source
AZ.Names = class {
  constructor(bases) {
    this.bases = bases;
    this.chains = {};
    this.V = new Set("aeiouyɑ'əøɛœæɶɒɨɪɔɐʊɤɯаоиеёэыуюяàèìòùỳẁȁȅȉȍȕáéíóúýẃőűâêîôûŷŵäëïöüÿẅãẽĩõũỹąęįǫųāēīōūȳăĕĭŏŭǎěǐǒǔȧėȯẏẇạẹịọụỵẉḛḭṵṳ");
  }
  chain(i) {
    if (this.chains[i]) return this.chains[i];
    const chain = {};
    const isV = c => c !== undefined && this.V.has(c);
    for (const n of (this.bases[i]?.b || "").split(",")) {
      const name = n.trim().toLowerCase();
      const basic = !/[^\x20-\x7e]/.test(name);
      for (let k = -1, syl = ""; k < name.length; k += syl.length || 1, syl = "") {
        const prev = name[k] || "";
        let v = 0;
        for (let c = k + 1; name[c] && syl.length < 5; c++) {
          const that = name[c], next = name[c + 1];
          syl += that;
          if (syl === " " || syl === "-") break;
          if (!next || next === " " || next === "-") break;
          if (isV(that)) v = 1;
          if (that === "y" && next === "e") continue;
          if (basic && ((that === "o" && next === "o") || (that === "e" && next === "e") || (that === "a" && next === "e") || (that === "c" && next === "h"))) continue;
          if (v && isV(name[c + 2])) break;
        }
        (chain[prev] = chain[prev] || []).push(syl);
      }
    }
    return (this.chains[i] = chain);
  }
  get(base, rand, min, max) {
    const b = this.bases[base] || Object.values(this.bases)[0];
    if (!b) return "Nameless";
    const data = this.chain(this.bases[base] ? base : Object.keys(this.bases)[0]);
    if (!data[""]) return "Nameless";
    const ra = a => a[Math.floor(rand() * a.length)];
    min = min || b.min; max = max || b.max;
    const dupl = b.d || "";
    let v = data[""], cur = ra(v), w = "";
    for (let i = 0; i < 20; i++) {
      if (cur === "") {
        if (w.length < min) { cur = ""; w = ""; v = data[""]; } else break;
      } else {
        if (w.length + cur.length > max) { if (w.length < min) w += cur; break; }
        else v = data[cur[cur.length - 1]] || data[""];
      }
      w += cur;
      cur = ra(v);
    }
    const l = w[w.length - 1];
    if (l === "'" || l === " " || l === "-") w = w.slice(0, -1);
    let name = [...w].reduce((r, c, i, d) => {
      if (c === d[i + 1] && !dupl.includes(c)) return r;
      if (!r.length) return c.toUpperCase();
      if (r.slice(-1) === "-" && c === " ") return r;
      if (r.slice(-1) === " " || r.slice(-1) === "-") return r + c.toUpperCase();
      if (c === "a" && d[i + 1] === "e") return r;
      if (i + 2 < d.length && c === d[i + 1] && c === d[i + 2]) return r;
      return r + c;
    }, "");
    if (name.split(" ").some(p => p.length < 2)) name = name.split(" ").map((p, i) => (i ? p.toLowerCase() : p)).join("");
    if (name.length < 2) name = ra(b.b.split(",")).trim();
    return name;
  }
};

AZ.GROUNDS = {
  sand: [228, 206, 146], gravel: [180, 174, 140], dry: [198, 190, 116], meadow: [140, 186, 88],
  grass: [106, 164, 78], lush: [74, 146, 60], needle: [86, 120, 70], tundra: [154, 140, 100],
  snow: [234, 242, 246], marsh: [88, 124, 80],
};

AZ.World = class {
  constructor(P) {
    const U = AZ.U, g = P.grid;
    this.P = P;
    Object.assign(this, { cols: g.cols, rows: g.rows, size: g.size, ox: g.ox, oy: g.oy, miles: g.miles });
    this.R = P.R;
    this.C = P.cells;
    this.W = P.world;
    this.names = new AZ.Names(P.namebases);
    const units = P.world.units || {};
    this.hexp = units.height?.exponent || 2;
    this.hunit = units.height?.unit || "ft";
    this.tunit = units.temperature?.unit || "°C";
    this.dunit = units.distance?.unit || "mi";
    // biome look: ground class from the name, colour pulled towards the biome's own colour (data)
    this.biomeLook = P.biomes.map(b => {
      const n = (b.name || "").toLowerCase();
      let k = "grass";
      if (/marine/.test(n)) k = "water";
      else if (/glacier|ice/.test(n)) k = "snow";
      else if (/hot desert/.test(n)) k = "sand";
      else if (/cold desert/.test(n)) k = "gravel";
      else if (/desert/.test(n)) k = "sand";
      else if (/savann/.test(n)) k = "dry";
      else if (/tundra/.test(n)) k = "tundra";
      else if (/taiga|boreal/.test(n)) k = "needle";
      else if (/wetland|swamp|marsh|bog/.test(n)) k = "marsh";
      else if (/rainforest|jungle/.test(n)) k = "lush";
      else if (/forest|wood/.test(n)) k = "grass";
      else if (/grass|steppe|prairie|meadow/.test(n)) k = "meadow";
      const base = AZ.GROUNDS[k] || AZ.GROUNDS.grass;
      const col = k === "water" ? U.hex2rgb(b.color) : U.mix(base, U.hex2rgb(b.color), k === "snow" ? 0.15 : 0.28);
      const icons = Object.entries(b.icons || {}).filter(([, v]) => (v.weight || 0) > 0).map(([t, v]) => [t, v.weight]);
      return { kind: k, col, icons, density: b.iconsDensity || 0 };
    });
    this.relief = P.world.relief || [
      { name: "Snowy mountains", height: { min: 71, max: 100 }, temperature: { min: null, max: -1 }, icons: { mountSnow: { weight: 1 } } },
      { name: "Mountains", height: { min: 71, max: 100 }, temperature: { min: null, max: null }, icons: { mount: { weight: 1 } } },
      { name: "Hills", height: { min: 50, max: 70 }, temperature: { min: null, max: null }, icons: { hill: { weight: 1 } } },
    ];
    // lookups by tile
    this.burgAt = new Map();
    for (const b of P.burgs) if (b) this.burgAt.set(this.idx(b.t[0], b.t[1]), b);
    this.markersAt = new Map();
    for (const m of P.markers) this.push(this.markersAt, this.idx(m.t[0], m.t[1]), m);
    this.unitsAt = new Map();
    for (const u of P.military) this.push(this.unitsAt, this.idx(u.t[0], u.t[1]), u);
    this.bucket = new Map();
    const put = (kind, o) => this.push(this.bucket, ((o.t[1] >> 4) << 16) | (o.t[0] >> 4), [kind, o]);
    P.burgs.forEach(b => b && put("burg", b));
    P.markers.forEach(m => put("marker", m));
    P.military.forEach(u => put("unit", u));
    this.zoneById = new Map(P.zones.map(z => [z.i, z]));
    this.ports = new Map(); // burg tile -> water tile for its pier
    for (const b of P.burgs) {
      if (!b || !b.port) continue;
      let best = null, bd = 1e9;
      for (const [dc, dr] of [[0, -1], [1, 0], [0, 1], [-1, 0], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
        const c = b.t[0] + dc, r = b.t[1] + dr;
        if (!this.inb(c, r) || this.isLand(c, r)) continue;
        const d = Math.abs(dc) + Math.abs(dr);
        if (d < bd) { bd = d; best = [c, r]; }
      }
      if (best) this.ports.set(this.idx(b.t[0], b.t[1]), best);
    }
  }
  push(map, k, v) { const a = map.get(k); if (a) a.push(v); else map.set(k, [v]); }
  idx(c, r) { return r * this.cols + c; }
  inb(c, r) { return c >= 0 && r >= 0 && c < this.cols && r < this.rows; }
  cell(c, r) { return this.R.cell[r * this.cols + c]; }
  ctype(c, r) { return this.C.type[this.cell(c, r)]; } // 0 land, 1 ocean, 2 lake
  isLand(c, r) { return this.inb(c, r) && this.C.type[this.cell(c, r)] === 0; }
  h(c, r) {
    c = Math.max(0, Math.min(this.cols - 1, c)); r = Math.max(0, Math.min(this.rows - 1, r));
    return this.R.height[r * this.cols + c];
  }
  centre(c, r) { return [this.ox + (c + 0.5) * this.size, this.oy + (r + 0.5) * this.size]; }
  tileAt(x, y) {
    return [Math.max(0, Math.min(this.cols - 1, Math.floor((x - this.ox) / this.size))),
            Math.max(0, Math.min(this.rows - 1, Math.floor((y - this.oy) / this.size)))];
  }
  gridCell(x, y) { // Azgaar's findGridCell
    const g = this.P.gridcells;
    return Math.floor(Math.min(y / g.spacing, g.cellsY - 1)) * g.cellsX + Math.floor(Math.min(x / g.spacing, g.cellsX - 1));
  }
  tempC(c, r) { const [x, y] = this.centre(c, r); return this.P.gridcells.temp[this.gridCell(Math.max(0, x), Math.max(0, y))]; }
  precMM(c, r) { const [x, y] = this.centre(c, r); return this.P.gridcells.prec[this.gridCell(Math.max(0, x), Math.max(0, y))] * 100; }
  latlon(c, r) {
    const [x, y] = this.centre(c, r), co = this.W.coords;
    return [co.latN - (y / this.W.height) * co.latT, co.lonW + (x / this.W.width) * co.lonT];
  }
  geozone(lat) {
    if (lat > 66.5) return "Arctic"; if (lat > 35) return "Temperate North"; if (lat > 23.5) return "Subtropical North";
    if (lat > 1) return "Tropical North"; if (lat > -1) return "Equatorial"; if (lat > -23.5) return "Tropical South";
    if (lat > -35) return "Subtropical South"; if (lat > -66.5) return "Temperate South"; return "Antarctic";
  }
  // Azgaar's getHeight, in the map's unit
  heightVal(h) {
    let v = -990;
    if (h >= 20) v = (h - 18) ** this.hexp; else if (h > 0) v = ((h - 20) / h) * 50;
    const ratio = this.hunit === "m" ? 1 : this.hunit === "f" ? 0.5468 : 3.281;
    return v * ratio;
  }
  heightStr(h, abs = false) { const v = this.heightVal(h); return `${AZ.U.num(abs ? Math.abs(v) : v)} ${this.hunit}`; }
  temp(tc) {
    const u = this.tunit;
    if (u === "°F") return `${Math.round(tc * 9 / 5 + 32)}°F`;
    if (u === "K") return `${Math.round(tc + 273.15)}K`;
    return `${Math.round(tc)}°C`;
  }
  bits(c, r) {
    const i = r * this.cols + c, a = this.R.croute[i], w = this.R.cwater[i];
    return { road: a & 15, trail: a >> 4, sea: w & 15, river: w >> 4 };
  }
  river(c, r) { const id = this.R.river[r * this.cols + c]; return id ? this.P.rivers[String(id)] : null; }
  route(c, r) { const id = this.R.route[r * this.cols + c]; return id ? this.P.routes[id - 1] : null; }
  ice(c, r) { return this.R.ice[r * this.cols + c]; }
  reliefAt(c, r) {
    if (!this._rel) { this._rel = new Int8Array(this.cols * this.rows).fill(-1); this._relOut = []; }
    const i = r * this.cols + c, v = this._rel[i];
    if (v >= 0) return v ? this._relOut[v - 1] : null;
    const out = this._reliefAt(c, r);
    if (!out) this._rel[i] = 0;
    else {
      let k = this._relOut.findIndex(o => o.rule === out.rule);
      if (k < 0) { this._relOut.push(out); k = this._relOut.length - 1; }
      this._rel[i] = k + 1;
    }
    return out ? this._relOut[this._rel[i] - 1] : null;
  }
  _reliefAt(c, r) {
    if (!this.isLand(c, r)) return null;
    const h = this.h(c, r), t = this.tempC(c, r);
    for (const rule of this.relief) {
      const H = rule.height || {}, T = rule.temperature || {};
      if ((H.min ?? -1e9) <= h && h <= (H.max ?? 1e9) && (T.min ?? -1e9) <= t && t <= (T.max ?? 1e9)) {
        return { rule: rule.name, icon: Object.keys(rule.icons || {})[0] || "hill" };
      }
    }
    return null;
  }
  zonesOfCell(cell) { return (this.C.zones[String(cell)] || []).map(i => this.zoneById.get(i)).filter(Boolean); }
  near(c, r, rad) {
    const out = [];
    for (let by = (r - rad) >> 4; by <= (r + rad) >> 4; by++)
      for (let bx = (c - rad) >> 4; bx <= (c + rad) >> 4; bx++)
        for (const [kind, o] of this.bucket.get((by << 16) | bx) || []) {
          const d = Math.hypot(o.t[0] - c, o.t[1] - r);
          if (d <= rad) out.push({ kind, o, d, dc: o.t[0] - c, dr: o.t[1] - r });
        }
    return out.sort((a, b) => a.d - b.d);
  }
  feature(cell) { return this.P.features[this.C.feature[cell]] || null; }
  waterName(c, r) {
    const f = this.feature(this.cell(c, r));
    if (!f) return "open water";
    const kind = f.type === "lake" ? "Lake" : f.subtype && f.subtype !== "ocean" ? AZ.U.cap(f.subtype) : "Ocean";
    return f.name ? `${f.name} ${kind}` : kind;
  }
  population(cell) { // Azgaar's getCellPopulation: [rural, urban]
    const u = this.W.units.population || { scale: 1000, urbanization: { rate: 1 } };
    const rural = this.C.pop[cell] * u.scale;
    const b = this.C.burg[cell] ? this.P.burgs[this.C.burg[cell]] : null;
    const urban = b ? b.population * u.scale * (u.urbanization?.rate ?? 1) : 0;
    return [rural, urban];
  }
  wind(lat) { // Azgaar winds: degrees the wind blows towards, clockwise from north, per 30° band
    const w = this.W.climate?.winds;
    if (!w) return null;
    const tier = Math.max(0, Math.min(5, Math.floor((90 - lat) / 30)));
    return w[tier];
  }
  milesBetween(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1]) * this.miles; }
};
