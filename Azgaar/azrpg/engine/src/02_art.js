// ---------------------------------------------------------------------------------------------
// Art. Everything is drawn in code on a 16-pixel tile, RPG Maker 2000 style. Colours come from
// the data where the data has them: ground from biome colours, roofs from culture colours,
// flags and sails from state colours.
// ---------------------------------------------------------------------------------------------
AZ.Art = class {
  constructor(world, mk) {
    this.w = world;
    this.mk = mk; // (w, h) => canvas
    this.cache = new Map();
  }
  get(key, w, h, draw) {
    let c = this.cache.get(key);
    if (!c) {
      c = this.mk(w, h);
      const x = c.getContext("2d");
      x.imageSmoothingEnabled = false;
      draw(x, w, h);
      this.cache.set(key, c);
    }
    return c;
  }
  static px(x, X, Y, W, H, col) { x.fillStyle = col; x.fillRect(X, Y, W, H); }
  ascii(key, rows, pal) {
    const h = rows.length, w = Math.max(...rows.map(r => r.length));
    return this.get(key, w, h, x => {
      rows.forEach((row, y) => [...row].forEach((ch, X) => { if (pal[ch]) AZ.Art.px(x, X, y, 1, 1, pal[ch]); }));
    });
  }

  // ------------------------------------------------------------------ vegetation (biome icons)
  plant(type, v = 0) {
    const dark = v ? 0.85 : 1;
    const g = (r, gg, b) => `rgb(${Math.round(r * dark)},${Math.round(gg * dark)},${Math.round(b * dark)})`;
    const P = {
      conifer: [["...k...", "..kgk..", "..kGk..", ".kgggk.", ".kgGgk.", "kgggggk", ".kgGgk.", "kgggggk", "kkgggkk", "...t...", "...t..."],
        { k: g(24, 54, 34), g: g(44, 100, 56), G: g(74, 136, 70), t: "#5a3a24" }],
      coniferSnow: [["...w...", "..wgw..", "..kGk..", ".wwgww.", ".kgGgk.", "wwgggww", ".kgGgk.", "kgwggwk", "kkgggkk", "...t...", "...t..."],
        { k: g(24, 54, 40), g: g(44, 96, 62), G: g(70, 126, 80), t: "#5a3a24", w: "#f1f5f8" }],
      deciduous: [["..kkkk..", ".kgggGk.", "kggGGggk", "kgGgggGk", "kggggggk", ".kgggkk.", "..kkkk..", "...tt...", "...tt..."],
        { k: g(30, 70, 30), g: g(60, 125, 50), G: g(104, 168, 78), t: "#6a4428" }],
      palm: [["kk...kk", "kggkggk", "..kgk..", ".kgGgk.", "kg.t.gk", "...t...", "...t...", "..t....", "..t....", ".tt...."],
        { k: g(30, 80, 30), g: g(64, 140, 56), G: g(110, 180, 80), t: "#8a6238" }],
      acacia: [[".kkkkkkk.", "kgGGgggGk", ".kkggggk.", "...tt....", "....t....", "....t....", "...t....."],
        { k: g(60, 80, 30), g: g(104, 128, 52), G: g(140, 160, 72), t: "#6e4e30" }],
      deadTree: [["t.....t", ".t.t.t.", "..ttt..", "...t.t.", "...t...", "...t...", "..tt..."], { t: "#6b5137" }],
      cactus: [["..c..", "..c.c", "c.c.c", "c.ccc", "ccc..", "..c..", "..c.."], { c: g(62, 125, 58) }],
      grass: [["G...G", ".gGg.", "ggggg"], { g: g(84, 130, 52), G: g(128, 170, 76) }],
      dune: [["...dddd...", "..dDDDDd..", ".dDDDDDDd.", "dddddddddd"], { d: "#c7a86a", D: "#ecd59a" }],
      swamp: [[".r..r.r.", ".r.rr.r.", "rr.r..rr", ".bbbbbb.", "bBBBBBBb"], { r: g(70, 110, 50), b: "#3b6b7a", B: "#5a91a3" }],
    };
    const def = P[type] || (/conifer|pine|fir/i.test(type) ? P.conifer : /grass|reed/i.test(type) ? P.grass : P.deciduous);
    return this.ascii(`plant:${type}:${v}`, def[0], def[1]);
  }

  // ------------------------------------------------------------------ relief (map's relief rules)
  relief(icon, ground, v = 0) {
    const key = `relief:${icon}:${v}:${ground.join(",")}`;
    if (icon === "hill") {
      return this.get(key, 16, 10, x => {
        const U = AZ.U, lit = U.css(U.shade(ground, 0.18)), mid = U.css(U.shade(ground, -0.06)), sh = U.css(U.shade(ground, -0.28)), ol = U.css(U.shade(ground, -0.5));
        const a = 7 - v * 0.5, cx = 7.5 + (v - 1), H = 9;
        for (let y = 0; y < 10; y++) for (let X = 0; X < 16; X++) {
          const q = ((X - cx) / a) ** 2 + ((y - H) / (H - 1)) ** 2;
          if (q > 1) continue;
          const edge = q > 0.78;
          AZ.Art.px(x, X, y, 1, 1, edge ? ol : X < cx - 1 ? lit : X > cx + 2 ? sh : mid);
        }
      });
    }
    const snowy = icon === "mountSnow", volc = icon === "vulcan";
    return this.get(key, 16, 20, x => {
      const rnd = AZ.U.rng(`${icon}${v}`);
      const H = [15, 19, 12][v % 3], peak = [7, 8, 6][v % 3];
      const lit = [158, 148, 134], sh = [100, 92, 88], ol = "rgb(56,50,48)";
      for (let y = 20 - H; y < 20; y++) {
        const t = (y - (20 - H)) / H;
        const hwL = 1 + t * (peak + 0.5) + (rnd() - 0.5) * 0.8, hwR = 1 + t * (15 - peak) + (rnd() - 0.5) * 0.8;
        const sc = [0.95, 1, 0.75][v % 3];
        const L = Math.max(0, Math.round(peak - hwL * sc)), R = Math.min(15, Math.round(peak + hwR * sc));
        if (volc && t < 0.12) continue;
        for (let X = L; X <= R; X++) {
          let col = X <= peak ? lit : sh;
          if (t > 0.6) col = AZ.U.mix(col, ground, (t - 0.6) * 1.2);
          if ((snowy && t < 0.42) || (!snowy && !volc && t < 0.12)) col = X <= peak ? [240, 244, 248] : [192, 204, 220];
          if (volc && t < 0.22 && Math.abs(X - peak) < 2) col = [200, 60, 30];
          AZ.Art.px(x, X, y, 1, 1, X === L || X === R ? ol : AZ.U.css(col));
        }
      }
      if (volc) for (let i = 0; i < 6; i++) AZ.Art.px(x, peak - 1 + (i % 3), 2 - (i >> 1), 2, 1, "rgba(120,120,120,0.8)");
    });
  }

  // ------------------------------------------------------------------ settlements
  house(x, X, Y, roof, wall, wide = 6) {
    const P = AZ.Art.px, dk = "rgb(52,40,36)";
    P(x, X + 2, Y, wide - 4, 1, roof); P(x, X + 1, Y + 1, wide - 2, 1, roof); P(x, X, Y + 2, wide, 1, roof);
    P(x, X, Y + 3, wide, 3, wall); P(x, X, Y + 6, wide, 1, dk);
    P(x, X + 1, Y + 4, 1, 2, dk); P(x, X + wide - 2, Y + 4, 1, 1, "rgb(250,230,140)");
  }
  tower(x, X, Y, w, h, stone) {
    const P = AZ.Art.px;
    for (let i = 0; i < w; i += 2) P(x, X + i, Y, 1, 1, stone);
    P(x, X, Y + 1, w, h - 1, stone); P(x, X, Y + h, w, 1, "rgb(70,64,60)");
    P(x, X + (w >> 1), Y + 3, 1, 2, "rgb(40,36,34)");
  }
  burg(b) {
    const w = this.w, U = AZ.U;
    const culture = w.P.cultures[b.culture] || {}, state = w.P.states[b.state] || {};
    const roof = U.css(U.shade(U.hex2rgb(culture.color || "#a05a40"), -0.35));
    const flag = state.color || "#dddddd", wall = "rgb(222,204,166)", stone = "rgb(160,156,150)";
    const group = b.group || "town";
    return this.get(`burg:${b.i}`, 16, 18, x => {
      const P = AZ.Art.px;
      const walls = b.walls && group !== "hamlet" && group !== "village";
      const flagAt = (X, Y) => { P(x, X, Y, 1, 6, "rgb(60,50,40)"); P(x, X + 1, Y, 3, 2, flag); };
      if (group === "capital") {
        this.tower(x, 1, 7, 3, 9, stone); this.tower(x, 12, 7, 3, 9, stone);
        this.tower(x, 6, 3, 5, 13, stone); flagAt(8, 0);
        this.house(x, 3, 10, roof, wall, 4); this.house(x, 9, 11, roof, wall, 4);
        if (walls) { P(x, 0, 15, 16, 2, stone); for (let i = 0; i < 16; i += 2) P(x, i, 14, 1, 1, stone); }
      } else if (group === "city") {
        this.tower(x, 7, 2, 3, 10, stone); flagAt(9, 0);
        this.house(x, 0, 6, roof, wall); this.house(x, 10, 6, roof, wall); this.house(x, 2, 10, roof, wall); this.house(x, 9, 10, roof, wall);
        if (walls) { P(x, 0, 16, 16, 2, stone); for (let i = 0; i < 16; i += 2) P(x, i, 15, 1, 1, stone); }
      } else if (group === "fort") {
        P(x, 1, 12, 14, 4, stone); for (let i = 1; i < 15; i += 2) P(x, i, 11, 1, 1, stone);
        this.tower(x, 5, 3, 6, 12, stone); flagAt(8, 0); P(x, 7, 13, 2, 3, "rgb(40,36,34)");
      } else if (group === "monastery") {
        const P2 = AZ.Art.px;
        P2(x, 7, 0, 1, 3, "rgb(240,220,120)"); P2(x, 6, 1, 3, 1, "rgb(240,220,120)");
        for (let i = 0; i < 5; i++) P2(x, 7 - (i >> 1), 3 + i, 2 + (i & ~1), 1, roof);
        P2(x, 5, 8, 6, 7, wall); P2(x, 7, 11, 2, 4, "rgb(52,40,36)"); P2(x, 5, 15, 6, 1, "rgb(52,40,36)");
        this.house(x, 10, 9, roof, wall, 5);
      } else if (group === "caravanserai") {
        P(x, 1, 7, 14, 9, "rgb(206,180,130)"); P(x, 3, 9, 10, 5, "rgb(232,212,166)"); P(x, 7, 14, 2, 2, "rgb(52,40,36)");
        for (const X of [3, 9]) { P(x, X + 1, 4, 2, 1, roof); P(x, X, 5, 4, 1, roof); P(x, X - 1, 6, 6, 1, roof); }
        flagAt(14, 1);
      } else if (group === "trading_post") {
        this.house(x, 2, 8, roof, wall, 7); P(x, 10, 12, 3, 3, "rgb(140,98,58)"); P(x, 12, 10, 3, 3, "rgb(164,118,70)"); flagAt(13, 3);
      } else if (group === "hamlet") {
        this.house(x, 5, 9, roof, wall, 6);
      } else if (group === "village") {
        this.house(x, 1, 8, roof, wall, 6); this.house(x, 9, 10, roof, wall, 6);
      } else { // town and anything else
        this.house(x, 0, 8, roof, wall); this.house(x, 10, 7, roof, wall); this.house(x, 5, 10, roof, wall);
        if (b.temple) { P(x, 7, 2, 1, 6, "rgb(200,190,170)"); P(x, 6, 4, 3, 1, "rgb(200,190,170)"); }
        if (walls) { P(x, 0, 16, 16, 2, stone); for (let i = 0; i < 16; i += 2) P(x, i, 15, 1, 1, stone); }
      }
      if (b.shanty && group !== "hamlet") { P(x, 13, 15, 3, 2, "rgb(120,96,70)"); P(x, 0, 15, 2, 2, "rgb(120,96,70)"); }
    });
  }
  pier() {
    return this.get("pier", 16, 16, x => {
      const P = AZ.Art.px;
      P(x, 6, 0, 4, 11, "rgb(138,100,62)"); for (let y = 1; y < 11; y += 2) P(x, 6, y, 4, 1, "rgb(110,78,48)");
      P(x, 5, 10, 1, 2, "rgb(80,56,36)"); P(x, 10, 10, 1, 2, "rgb(80,56,36)");
    });
  }

  // ------------------------------------------------------------------ markers by type
  marker(type) {
    const k = "rgb(40,34,32)";
    const D = {
      caves: [["...kkkkkk...", "..kssssssk..", ".kssKKKKssk.", "kssKKKKKKssk", "ksKKKKKKKKsk", "ksKKKKKKKKsk", "kkkkkkkkkkkk"], { k, s: "#8a837a", K: "#14110f" }],
      ruins: [["..w.........", ".www....w...", ".wsw...www..", ".wsw...wsw..", ".wsw...wsw.w", ".wsw.s.wsw.s", "wwwwwwwwwwww"], { w: "#d8d2c4", s: "#a49c8c" }],
      statues: [["..k..", ".kwk.", ".kwk.", ".kwk.", ".kwk.", "kwwwk", "kwswk", "kwwwk", "kkkkk"], { k, w: "#cfc8b8", s: "#8f877a" }],
      portals: [["..pppp..", ".pPPPPp.", "pP.ww.Pp", "pPw..wPp", "pPw..wPp", "pP.ww.Pp", ".pPPPPp.", "..pppp.."], { p: "#5a2a8a", P: "#a35ee0", w: "#e8d4ff" }],
      mines: [["..tttttt..", ".t......t.", "t..KKKK..t", "t.KKKKKK.t", "t.KKKKKK.t", "sssssssss."], { t: "#7a5634", K: "#14110f", s: "#8a837a" }],
      "hot-springs": [[".w..w..w.", "..w..w...", ".w..w..w.", "..bbbbb..", ".bBBBBBb.", "bBBwBBBBb", ".bbbbbbb."], { w: "rgba(240,240,240,0.8)", b: "#2f6f8f", B: "#6ec4e0" }],
      "water-sources": [["....w....", "...wBw...", "..bbbbb..", ".bBBwBBb.", "bBBBBBBBb", ".bbbbbbb."], { w: "#ffffff", b: "#2f6f8f", B: "#7fd0f0" }],
      waterfalls: [["sssBBsss", "sssBBsss", "ss.BB.ss", "s..BB..s", "...BB...", "..wBBw..", ".wwwwww."], { s: "#7d756c", B: "#9fd8f4", w: "#ffffff" }],
      battlefields: [["r.......r", ".k.....k.", "..k...k..", "...k.k...", "....k....", "...k.k...", "..k...k..", ".w.....w.", "www...www"], { k: "#c8c8c8", r: "#a03030", w: "#e8e0d0" }],
      "sea-monsters": [["............", "..gg....gg..", ".gGGg..gGGg.", "gG..Gg.G..Gg", "..........e."], { g: "#2e6b4f", G: "#4f9f73", e: "#ffffff" }],
      "lake-monsters": [["............", "..gg....gg..", ".gGGg..gGGg.", "gG..Gg.G..Gg", "..........e."], { g: "#2e6b4f", G: "#4f9f73", e: "#ffffff" }],
      "hill-monsters": [["r.........r.", "rr..rrr..rr.", ".rrrrRrrrr..", "..rrRRRrr...", "...rrrrrr.y.", "..rr...rrrr.", ".rr.....r..."], { r: "#8a1f1f", R: "#c94040", y: "#f2d24a" }],
      "sacred-forests": [["..y..y..", ".ykkkky.", "kgggGggk", "kgGgggGk", ".kgggk..", "y.ktk..y", "...t...."], { k: "#1f4a24", g: "#3f8a44", G: "#7ac06a", t: "#6a4428", y: "#f5d65a" }],
      "sacred-pineries": [["y..k..y", "..kgk..", ".kgGgk.", "kgggggk", ".kgGgk.", "kgggggk", "y..t..y"], { k: "#1f4a24", g: "#3f7a4a", G: "#6aa86a", t: "#6a4428", y: "#f5d65a" }],
      brigands: [["....w.....", "...wrw....", "..wwrww...", ".wwwrwww..", "wwwwrwwww.", "......o...", ".....oOo..", "......t..."], { w: "#c8b48c", r: "#7a5a3a", o: "#f08a2a", O: "#ffd23f", t: "#5a3a24" }],
      pirates: [["....k.....", "...KKK....", "..KKKKK...", ".KKKKKKK..", "....k.....", "hhhhhhhhh.", ".hhhhhhh.."], { k: "#3a2a1a", K: "#18181a", h: "#5a3a24" }],
      libraries: [["...kkkk...", "..kwwwwk..", ".kkkkkkkk.", ".w.w.w.w..", ".w.w.w.w..", ".w.w.w.w..", "kkkkkkkkk."], { k: "#6a5a4a", w: "#e6dcc8" }],
      circuses: [["....r.....", "...rwr....", "..rwrwr...", ".rwrwrwr..", "rwrwrwrwr.", ".w.....w..", ".w..k..w.."], { r: "#c83a3a", w: "#f4ecd8", k: "#3a2a2a" }],
      canoes: [["tttttt....", "t....t....", "t....t....", "..........", ".bbbbbbb..", "..bbbbb..."], { t: "#8a6238", b: "#6a4428" }],
      migration: [[".g...g.", "g.g.g.g", "...g...", ".g...g.", "g.g...."], { g: "#4f9f3f" }],
      rifts: [["...p.....", "...pP....", "....pP...", "...pPp...", "..pP.....", "..pPp....", "...pP....", "....p...."], { p: "#4a1a6a", P: "#c070ff" }],
      "disturbed-burials": [[".kk...kk.", "kwwk.kwwk", "kwwk.kwwk", "kwwk.kwwk", "ddddddddd"], { k: "#5a5650", w: "#b8b2a6", d: "#5a4630" }],
      necropolises: [["k...k...k", "kk.kkk.kk", "kwkwwwkwk", "kwkwKwkwk", "kwwwKwwwk", "kkkkkkkkk"], { k: "#3a3640", w: "#8a8496", K: "#141218" }],
      encounters: [["..yy..", "..yy..", "..yy..", "......", "..yy..", "......", ".kkkk.", "kSSSSk", ".kccK.", ".kccK.", ".k..k."], { y: "#f5d65a", k: "#2a2420", S: "#e0b890", c: "#5a6aa0", K: "#2a2420" }],
      party: [[".k....", ".krrr.", ".krrrr", ".krrr.", ".k....", ".k....", ".k....", "kkk..."], { k: "#3a2a1a", r: "#d4351c" }],
      bridges: [["..........", "k.k.k.k.k.", "tttttttttt", "t..t..t..t"], { k: "#5a3a24", t: "#8a6238" }],
      inns: [["...ss.....", "..rrrrr...", ".rrrrrrr..", "rrrrrrrrr.", "wwwwwwwwy.", "wkwwwwwwy.", "wkwwyyww..", "kkkkkkkk.."], { r: "#8a3a2a", w: "#e0cfa8", k: "#4a3428", y: "#f6d667", s: "#888" }],
    };
    D.dungeons = D.caves; D.jousts = D.circuses; D.fairs = D.circuses;
    const def = D[type] || [["..kk..", ".kyyk.", ".kyyk.", "..kk..", "..t...", "..t...", ".ttt.."], { k: "#3a2a1a", y: "#f5d65a", t: "#7a5634" }];
    return this.ascii(`marker:${type}`, def[0], def[1]);
  }

  unit(u) {
    const st = this.w.P.states[u.state] || {}, col = st.color || "#cccccc";
    if (u.naval) return this.vessel("fleet", "left", col);
    return this.get(`unit:${u.state}`, 16, 14, x => {
      const P = AZ.Art.px, cl = "rgb(236,230,214)", sh = "rgb(178,168,150)";
      for (const X of [1, 8]) for (let i = 0; i < 5; i++) { P(x, X + 3 - i, 6 + i, 1 + i * 2, 1, i % 2 ? sh : cl); }
      P(x, 13, 1, 1, 12, "rgb(60,50,40)"); P(x, 9, 1, 4, 3, col);
    });
  }

  // ------------------------------------------------------------------ people and vessels
  walker(dir, frame, pal) {
    const key = `walk:${dir}:${frame}:${pal.cloak}:${pal.skin}`;
    return this.get(key, 16, 16, x => {
      const P = AZ.Art.px, k = "rgb(34,28,30)", cl = pal.cloak, cd = pal.cloakDark, sk = pal.skin;
      P(x, 4, 14, 8, 2, "rgba(0,0,0,0.25)");
      const lf = frame === 1 ? -1 : 0, rf = frame === 2 ? -1 : 0;
      P(x, 5, 12 + lf, 2, 3, k); P(x, 9, 12 + rf, 2, 3, k);
      P(x, 4, 7, 8, 6, cl); P(x, 4, 12, 8, 1, cd); P(x, 4, 7, 1, 6, cd); P(x, 11, 7, 1, 6, cd);
      P(x, 4, 9, 8, 1, pal.belt);
      P(x, 4, 1, 8, 7, cl); P(x, 4, 1, 8, 1, cd);
      if (dir === "down") { P(x, 5, 3, 6, 4, sk); P(x, 6, 4, 1, 1, k); P(x, 9, 4, 1, 1, k); }
      else if (dir === "left") { P(x, 4, 3, 4, 4, sk); P(x, 5, 4, 1, 1, k); }
      else if (dir === "right") { P(x, 8, 3, 4, 4, sk); P(x, 10, 4, 1, 1, k); }
      const sx = dir === "left" ? 2 : 13;
      P(x, sx, 2, 1, 13, "rgb(120,84,50)"); P(x, sx, 2, 1, 1, "rgb(230,200,90)");
      P(x, dir === "left" ? 3 : 12, 8, 1, 2, sk);
    });
  }
  vessel(kind, dir, sailCol) {
    const facing = dir === "left" ? "left" : dir === "right" ? "right" : "right";
    const key = `vessel:${kind}:${facing}:${sailCol || ""}`;
    return this.get(key, 16, 16, x => {
      const P = AZ.Art.px, hull = "rgb(110,72,42)", hullD = "rgb(70,46,28)", sail = sailCol || "rgb(244,238,222)", sailD = "rgba(0,0,0,0.18)";
      const big = kind !== "boat";
      const flip = facing === "left";
      const fx = X => (flip ? 15 - X : X);
      const R = (X, Y, W, H, c) => P(x, flip ? 16 - X - W : X, Y, W, H, c);
      R(1, 11, 14, 1, hullD); R(2, 12, 12, 2, hull); R(3, 14, 10, 1, hullD);
      if (big) {
        R(5, 2, 1, 9, "rgb(70,50,34)"); R(10, 4, 1, 7, "rgb(70,50,34)");
        R(2, 3, 7, 6, sail); R(2, 8, 7, 1, sailD); R(8, 5, 5, 5, sail); R(8, 9, 5, 1, sailD);
        R(5, 1, 3, 1, kind === "fleet" ? sail : "rgb(200,60,50)");
      } else {
        R(7, 3, 1, 8, "rgb(70,50,34)"); R(3, 4, 4, 6, sail); R(3, 9, 4, 1, sailD);
      }
      x.fillStyle = "rgba(255,255,255,0.7)"; x.fillRect(fx(0), 13, 1, 1);
    });
  }
};
