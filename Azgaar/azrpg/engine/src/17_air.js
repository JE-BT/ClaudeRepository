// ---------------------------------------------------------------------------------------------
// Air travel and journeys that begin in the wilds.
//   Air transports (domain "air" in the map's transport list: dirigibles, aircraft, teleports)
//   fly over any tile, moor at towns, and follow the plan's line directly. A teleport leg is
//   crossed at once. A journey may begin away from any town; it then starts on its first tile,
//   with the nearest town as the traveller's home.
// ---------------------------------------------------------------------------------------------
(() => {
  const U = AZ.U, T = AZ.T, G = AZ.Game.prototype;
  AZ.airNames = new Set();
  const vc0 = AZ.vesselClass;
  AZ.vesselClass = kind => (AZ.airNames.has(kind) || /airship|dirigible|balloon|teleport|aircraft|airplane|helicopter|flying/i.test(kind || "") ? "air" : vc0(kind));
  AZ.isTeleport = kind => /teleport/i.test(kind || "");

  const nav0 = AZ.World.prototype.navigable;
  AZ.World.prototype.navigable = function (c, r, cls = "boat") { return cls === "air" ? this.inb(c, r) : nav0.call(this, c, r, cls); };
  const harb0 = AZ.World.prototype.harbour;
  AZ.World.prototype.harbour = function (b, cls = "boat") { return cls === "air" ? { t: b.t, walk: 0 } : harb0.call(this, b, cls); };

  // the journey learns which transports fly from the map's own list
  const jctor = AZ.Journey;
  AZ.Journey = class extends jctor {
    constructor(w, J) {
      for (const t of w.W.transports || []) if (t.domain === "air") AZ.airNames.add(t.name);
      super(w, J);
      if (!this.origin.burg) { // the wilds: home is the nearest town, wherever it is
        const t = this.origin.tile;
        let best = null, bd = 1e9;
        for (const b of w.P.burgs) if (b) { const d = Math.hypot(b.t[0] - t[0], b.t[1] - t[1]); if (d < bd) { bd = d; best = b; } }
        if (best) this.origin = { ...this.origin, burg: best, name: `the wilds ${AZ.U.compass(t[0] - best.t[0], t[1] - best.t[1])} of ${best.name}`, at: false };
      }
    }
  };
  AZ.OWN_TRANSPORT.add("Airship voyage");
  // air legs are flown in the company's own craft
  const fix0 = AZ.Journey.prototype.fixCourses;
  AZ.Journey.prototype.fixCourses = function () {
    fix0.call(this);
    for (const cp of this.cps) {
      const leg = cp.legOut;
      if (!leg || AZ.vesselClass(leg.transport) !== "air" || leg.own) continue;
      leg.own = true;
      if (!cp.acts.some(a => a.id === "board")) cp.acts.push({ id: "board", label: AZ.isTeleport(leg.transport) ? "Step into the teleport circle" : `Board the company's ${leg.transport.toLowerCase()}`, stay: null });
    }
  };

  // boarding: an air craft moors at the town itself; a teleport crosses the leg at once
  const board0 = G.boardCompany;
  G.boardCompany = async function (b) {
    const cp = this.cpHere(), leg = cp && cp.legOut, s = this.s, w = this.w;
    if (!leg || AZ.vesselClass(leg.transport) !== "air") return board0.call(this, b);
    if (AZ.isTeleport(leg.transport)) {
      const next = this.cpNext(), hours = Math.max(0.5, leg.miles / (leg.speed || 10000));
      this.doAct("board");
      s.aboard = false; s.vessel = null; s.c = next.tile[0]; s.r = next.tile[1]; s.clock += hours; this.anim = null;
      this.log(`Teleported from ${U.esc(b.name)} to ${U.esc(next.place.name)}.`, "hook");
      await this.ui.say([`The circle in ${U.esc(b.name)} flares white${s.party?.length ? ", and the company steps through with you" : ""} ${T("mixed")}.`, `You stand in ${U.esc(next.place.name)}, ${U.num(leg.miles)} miles away ${T("data")}.`]);
      this.afterStep();
      return;
    }
    s.vessel = { mode: "company", kind: leg.transport, cls: "air", speed: leg.speed, hpd: leg.hoursPerDay, crew: Math.max(2, (s.party || []).length), morale: 80, c: b.t[0], r: b.t[1], wage: 0, hire: 0, home: b.i };
    s.aboard = true; s.c = b.t[0]; s.r = b.t[1];
    this.doAct("board");
    this.log(`Boarded the company's ${U.esc(leg.transport.toLowerCase())} at ${U.esc(b.name)}.`, "hook");
    await this.ui.say([`The ${U.esc(leg.transport.toLowerCase())} is moored over ${U.esc(b.name)}${s.party?.length ? `; ${U.esc(s.party.map(p => p.name).join(", "))} are already aboard` : ""} ${T("mixed")}.`,
      `She flies over land and sea alike at ${leg.speed} mph, ${leg.hoursPerDay} hours a day ${T("data")}. Steer with the arrows, or press F to follow the plan's line to ${U.esc(this.cpNext()?.place.name || "")}. She moors at any town you fly over (Space), and you can set down anywhere else.`]);
    this.afterStep();
  };
  // stepping out of an air craft wherever it is
  const interact0 = G.interact;
  G.interact = async function () {
    const s = this.s, w = this.w, v = s.vessel;
    if (s.aboard && v && v.cls === "air" && !this.riding() && !this.burgHere() && w.isLand(s.c, s.r)) {
      const k = await this.ui.choose(`Set down here? The ${U.esc(v.kind.toLowerCase())} waits.`, [{ label: "Set down and step out" }, { label: "Look around" }, { label: "Stay aboard" }], { cancel: 2 });
      if (k === 0) { s.aboard = false; s.auto = false; v.anchored = true; this.afterStep(); return; }
      if (k === 1) return this.ui.say([this.know.describe(s.c, s.r, true).join(" ")], "Look");
      return;
    }
    return interact0.call(this);
  };
  // storms aloft
  const storm0 = G.stormCall;
  G.stormCall = async function () {
    const s = this.s, v = s.vessel;
    if (!v || v.cls !== "air" || this.riding()) return storm0.call(this);
    const until = (Math.floor(s.clock / 12) + 1) * 12;
    const k = await this.ui.choose(`<b>A storm is building ahead.</b> ${U.esc(v.kind)} and storm do not mix ${T("mixed")}.`, [{ label: `Set down and moor until it passes (${AZ.Clock.span(until - s.clock)})` }, { label: "Climb above it (damage 25%)" }], { cancel: 0 });
    if (k === 0) { s.clock = until; this.ui.toast("Moored to the ground, you wait it out."); }
    else if (U.rnd2(s.c, s.r, Math.floor(s.clock) + 17) < 0.25) { this.events.fx({ cond: "damaged" }, "Storm damage aloft."); this.ui.toast("Lightning and hail: the envelope is torn. The craft is damaged."); }
    else this.ui.toast("You ride above the storm in thin, cold air.");
    this.dirty = true;
  };
  // an air craft at a town counts as being in that town
  const bh0 = G.burgHere;
  G.burgHere = function () { const s = this.s; if (s && s.aboard && s.vessel && s.vessel.cls === "air" && !this.riding()) return this.w.burgAt.get(this.w.idx(s.c, s.r)) || null; return bh0.call(this); };
  // airship art: an envelope and a gondola
  const vessel0 = AZ.Art.prototype.vessel;
  AZ.Art.prototype.vessel = function (kind, dir, sailCol) {
    if (kind !== "air") return vessel0.call(this, kind, dir, sailCol);
    return this.get(`vessel:air:${dir === "left" ? "l" : "r"}`, 16, 16, x => {
      const P = AZ.Art.px;
      P(x, 2, 2, 12, 1, "rgb(120,90,70)"); P(x, 1, 3, 14, 4, "rgb(204,178,140)"); P(x, 2, 7, 12, 1, "rgb(150,120,90)");
      P(x, 3, 4, 10, 1, "rgba(255,255,255,0.35)");
      P(x, dir === "left" ? 14 : 0, 3, 2, 4, "rgb(150,60,50)");
      P(x, 5, 8, 1, 3, "rgb(70,50,34)"); P(x, 10, 8, 1, 3, "rgb(70,50,34)");
      P(x, 4, 11, 8, 3, "rgb(110,72,42)"); P(x, 4, 14, 8, 1, "rgb(70,46,28)");
      x.fillStyle = "rgba(0,0,0,0.25)"; x.fillRect(4, 15, 8, 1);
    });
  };
  // the player's sprite and the craft waiting where you left it
  const frame0 = G.frame;
  G.frame = function (now) {
    const s = this.s;
    if (s && s.vessel && s.vessel.cls === "air") {
      const art = this.ren.art, orig = art.vessel.bind(art);
      art.vessel = (kind, dir, col) => orig(kind === "boat" || kind === "ship" ? "air" : kind, dir, col);
      try { return frame0.call(this, now); } finally { art.vessel = orig; }
    }
    return frame0.call(this, now);
  };
  // the start may be in the wilds
  const intro0 = AZ.Know.prototype.intro;
  AZ.Know.prototype.intro = function (g) {
    const pages = intro0.call(this, g);
    if (this.jr && !this.jr.origin.at) {
      const o = this.jr.origin;
      return pages.map(p => p.replace(/^You stand in [^.]*\./, `You stand in ${U.esc(o.name)}, ${U.num(Math.round(Math.hypot(o.burg.t[0] - o.tile[0], o.burg.t[1] - o.tile[1]) * this.w.miles))} miles from the nearest town ${T("data")}.`));
    }
    return pages;
  };
})();
