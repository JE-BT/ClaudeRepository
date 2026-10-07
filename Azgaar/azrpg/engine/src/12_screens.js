// ---------------------------------------------------------------------------------------------
// Screens: HUD, minimap, world map, journal (with the route and its reasons), help, menu, title.
// ---------------------------------------------------------------------------------------------
Object.assign(AZ.Game.prototype, {

  hud() {
    const s = this.s, w = this.w, U = AZ.U, el = this.ui.el, cell = w.cell(s.c, s.r);
    const b = this.burgHere(), land = w.isLand(s.c, s.r);
    const place = b ? (w.burgAt.get(w.idx(s.c, s.r)) ? b.name : `${b.name} harbour`) : land ? (w.C.province[cell] ? w.P.provinces[w.C.province[cell]].name : w.C.state[cell] ? w.P.states[w.C.state[cell]].name : "Neutral lands") : w.waterName(s.c, s.r);
    const terr = land ? `${w.P.biomes[w.C.biome[cell]].name} · ${w.heightStr(w.h(s.c, s.r))}` : `depth ${w.heightStr(w.h(s.c, s.r), true)}`;
    const lat = this.lat(), light = AZ.Clock.light(s.clock, lat), season = AZ.Clock.season(lat, s.clock), today = AZ.Clock.today(w.tempC(s.c, s.r), lat, s.clock, !land);
    const wx = this.weather();
    const conds = Object.keys(s.cond).map(k => AZ.COND[k]?.label || k).join(", ");
    el.loc.innerHTML = `<div class="big">${U.esc(place)}</div><div>${U.esc(terr)} · ${w.temp(today)} · ${wx.label}</div><div>${AZ.Clock.fmt(s.clock)} · ${light.phase} · ${season}</div>` +
      `<div class="dim">🟡 ${U.rn(s.purse, 1)} · food ${s.sup.food} · water ${s.sup.water}${conds ? ` · <span class="late">${conds}</span>` : ""}</div>`;
    let trip = "";
    const here = this.cpHere(), next = this.cpNext();
    if (this.jr) {
      if (here) {
        const pend = this.pendingActs(here.place.burg && here.place.at ? here.place.burg : null);
        trip += `<div class="hook">At checkpoint ${here.i}: ${U.esc(here.place.name)}</div>` + (pend.length ? `<div>★ ${pend.map(a => U.esc(a.label)).join("; ")}</div>` : "");
      }
      if (next) {
        const t = next.tile, dd = this.know.dirDist(s.c, s.r, t);
        trip += `<div class="hook">Next ${next.i}/${this.jr.cps.length - 1}: ${U.esc(next.place.name)} <span class="arrow">${U.arrow(t[0] - s.c, t[1] - s.r)}</span> ${U.num(dd.mi)} mi</div>` +
          `<div class="dim">par ${AZ.Clock.fmt(next.parArrive)} (${s.clock > next.parArrive ? `${AZ.Clock.span(s.clock - next.parArrive)} past` : `${AZ.Clock.span(next.parArrive - s.clock)} left`})${next.legIn ? ` · plan: ${U.esc(next.legIn.transport)}` : ""}</div>`;
      } else if (s.done) trip += `<div class="hook">${U.esc(this.jr.J.name)}: complete</div>`;
    }
    const v = s.voyage, bo = s.vessel;
    if (v) trip += `<div>${s.aboard ? "Aboard" : "Booked on"} ${U.esc(v.ship)} (${v.role}) → ${U.esc(v.stops[v.leg]?.name || "")}${v.state === "port" ? ` · sails ${AZ.Clock.fmt(v.departAt)}` : ""}${this.fast ? " · ⏩" : ""}</div>`;
    else if (bo) trip += `<div>${s.aboard ? "Aboard" : "Ashore; your boat waits"}: ${U.esc(bo.kind)} (${bo.mode})${bo.crew ? ` · crew ${bo.crew}, morale ${Math.round(bo.morale)}` : " · no crew"}${s.auto ? ' · <b class="hook">autopilot</b>' : ""}</div>`;
    else if (s.auto) trip += `<div class="dim">walking to the waypoint · F to stop</div>`;
    el.trip.innerHTML = trip + this.threadLine();
    const lens = AZ.LENSES[this.lensIdx];
    if (lens.id !== "none") { el.legend.style.display = "block"; el.legend.innerHTML = `<b>${lens.name}</b> (L)<br>${U.esc(lens.label(w, cell, s.c, s.r) ?? "")}`; }
    else el.legend.style.display = "none";
    if (this.inspectOn) el.panel.innerHTML = this.know.inspect(s.c, s.r, this) + `<p class="dim">I to close · tags: ${AZ.T("data")} file ${AZ.T("mixed")} rule on data ${AZ.T("new")} invented</p>`;
    this.mini();
  },
  threadLine() {
    const th = this.activeThread(), U = AZ.U, s = this.s;
    if (!th) return "";
    const st = th.steps[th.phase], t = this.stepTile(st);
    const dd = t ? this.know.dirDist(s.c, s.r, t) : null;
    const due = th.deadline ? ` · ${s.clock > th.deadline ? "late" : `${Math.ceil((th.deadline - s.clock) / 24)} d left`}` : "";
    return `<div class="side">◆ ${U.esc(th.title)}</div><div class="dim">${U.esc(st.text)}${dd && dd.mi > 1 ? ` · <span class="side">${U.arrow(t[0] - s.c, t[1] - s.r)}</span> ${U.num(dd.mi)} mi` : ""}${due}</div>`;
  },
  journal() {
    const s = this.s, U = AZ.U, jr = this.jr, tv = this.tv, w = this.w;
    const cpRows = jr ? jr.cps.map(cp => {
      const rec = s.cpRec[cp.i] || {};
      const acts = cp.acts.map(a => `${(rec.acts || {})[a.id] ? "✓" : "·"} ${U.esc(a.label)}`).join("<br>");
      const d = rec.arrive != null ? rec.arrive - cp.parArrive : null;
      const nights = cp.legIn && cp.legIn.nights && cp.legIn.nights.length ? `<div class="dim">${cp.legIn.nights.length} nights at anchor by the plan</div>` : "";
      return `<tr class="${cp.i === s.cp ? "cur" : ""}"><td>${cp.i}</td><td>${U.esc(cp.place.name)}${cp.legIn ? `<div class="dim">${U.esc(cp.legIn.name)} · ${U.esc(cp.legIn.transport)} · ${U.num(cp.legIn.miles)} mi</div>` : ""}${nights}</td><td>${AZ.Clock.fmt(cp.parArrive)}</td><td>${rec.skipped ? "skipped" : rec.arrive != null ? AZ.Clock.fmt(rec.arrive) : "—"}</td><td class="${d > 24 ? "late" : ""}">${d != null ? this.deltaTextAt(d) : ""}</td><td>${acts}</td></tr>` +
        `<tr><td></td><td colspan="5" class="why">${this.legReasons(cp).join(" ")}</td></tr>`;
    }).join("") : "";
    const leads = s.leads.filter(l => typeof l === "object" && !(l.key.startsWith("m") && s.done_m.includes(+l.key.slice(1))));
    const cnt = (k, list) => `${s.seen[k].length} of ${w.P[list].filter(x => x && !x.removed).length - (list === "states" || list === "cultures" || list === "religions" ? 1 : 0)}`;
    const v = s.vessel;
    this.ui.modal(`<div class="sheet"><h2>Journal</h2>
      <h3>The traveller ${AZ.T("new")}</h3><p><b>${U.esc(tv.name)}</b>, ${tv.age}, ${U.esc(tv.trade)} (${U.esc(tv.kindLabel || "")}). ${U.cap(U.esc(tv.why))}. ${w.P.cultures[tv.culture].name}; faith: ${w.P.religions[tv.faith]?.name}. Carries ${U.esc(tv.token)}.</p>
      <h3>Purse, stores, condition, standing</h3><p>🟡 ${U.rn(s.purse, 1)} · food ${s.sup.food} rations · water ${s.sup.water} · ${Object.keys(s.cond).map(k => AZ.COND[k]?.label || k).join(", ") || "well"}${v ? ` · ${U.esc(v.kind)} (${v.mode}), crew ${v.crew}, morale ${Math.round(v.morale)}` : ""} · ${[...Object.entries(s.stand.f).map(([i, n]) => `${U.esc(w.P.religions[i]?.name)} ${n > 0 ? "+" : ""}${n}`), ...Object.entries(s.stand.s).map(([i, n]) => `${U.esc(w.P.states[i]?.name)} ${n > 0 ? "+" : ""}${n}`)].join(" · ") || "no standing earned or lost yet"} ${AZ.T("mixed")}</p>
      ${jr ? `<h3>The route: checkpoints, par and the reasons ${AZ.T("mixed")}</h3><p class="dim">The map's journey is the plan: par times from dawn on Day 1 with each mode's speed and hours a day. It is not a rule: take another ship, hire a boat, walk, skip a checkpoint. Reaching ${U.esc(jr.dest.name)} ends the pilgrimage.</p>
      <table class="plan"><tr><th>#</th><th>Checkpoint and leg</th><th>Par</th><th>Record</th><th>Against par</th><th>The plan's tasks</th></tr>${cpRows}</table>` : ""}
      <h3>Side stories</h3>${s.threads.length ? s.threads.map(th => `<div class="${th.done ? "dim" : "side"}">◆ ${U.esc(th.title)}: ${th.done ? th.outcome : U.esc(th.steps[th.phase].text)}${th.deadline && !th.done ? ` (by ${AZ.Clock.fmt(th.deadline)})` : ""}</div>`).join("") : '<p class="dim">None yet. Look at notice boards in towns.</p>'}
      <h3>Leads (click to set a waypoint)</h3><div class="leads">${leads.map(l => `<div class="lead side" data-c="${l.t[0]}" data-r="${l.t[1]}">${U.esc(l.name)} (${U.esc(l.type || "")}, ${l.from}) · ${this.know.dirDist(s.c, s.r, l.t).txt}</div>`).join("") || '<p class="dim">Nothing yet: rumours, sightings and libraries add leads.</p>'}</div>
      <h3>Seen so far</h3><p>States ${cnt("st", "states")} · cultures ${cnt("cu", "cultures")} · faiths ${cnt("re", "religions")} · biomes ${s.seen.bi.length} · towns ${s.seen.b.length} · marked places ${s.seen.m.length} of ${w.P.markers.length} · forces ${s.seen.u.length} · zones ${s.seen.z.length} of ${w.P.zones.length}</p>
      <h3>Log</h3><div class="log">${s.log.slice().reverse().map(e => `<div class="${e.cls}"><span class="dim">${AZ.Clock.fmt(e.t)}</span> ${e.html}</div>`).join("") || "<div class='dim'>Nothing yet.</div>"}</div>
      <p class="dim">J or Esc to close</p></div>`, e => { if (["Escape", "j", "J", "x", "X"].includes(e.key)) this.ui.closeModal(); });
    this.ui.el.modal.querySelectorAll(".lead").forEach(d => (d.onclick = () => { s.waypoint = [+d.dataset.c, +d.dataset.r]; this.ui.closeModal(); this.ui.toast("Waypoint set. F follows it."); this.dirty = true; }));
  },
  help() {
    this.ui.modal(`<div class="sheet"><h2>How to play</h2><table class="keys">
      <tr><th>Arrows / WASD</th><td>Walk, or steer your own or hired boat</td></tr>
      <tr><th>Space / Enter</th><td>Go into a town (also from its harbour) · read a marker · hail a unit · go ashore or board · talk aboard a ship · look around</td></tr>
      <tr><th>F</th><td>Follow a path: to your waypoint if you set one (map click, or a lead in the journal), otherwise along the plan's course to the next checkpoint (boats); on foot, to the waypoint. As a passenger, F lets the days pass faster. Any arrow takes over.</td></tr>
      <tr><th>R</th><td>Anchor, camp or wait (dawn, 1, 3 or 6 hours, or two days to recover); fish where there is water, forage and hunt on land (six hours each)</td></tr>
      <tr><th>I · L · M · J</th><td>Inspector · lens · world map (click for a waypoint) · journal (route, reasons, side stories, leads)</td></tr>
      <tr><th>+ / − · Esc · H</th><td>Zoom · menu · help</td></tr></table>
      <h3>The plan is par, not a rule</h3><p>The map's journey gives checkpoints, par times and tasks (★, gold). Do the tasks yourself: book passage, give alms, take a room, anchor for the night. Take another ship, hire a boat, walk, or skip a checkpoint; reaching the last one ends the pilgrimage.</p>
      <h3>Ships and boats</h3><p>A <b>booked ship</b> has a captain with his own itinerary and a sailing time; it does not wait. Bring your own food. If you work the passage (some trades can), you pay no fare and are paid at the end. A <b>hired boat</b> is yours to steer: you pay wages and hire each dawn and feed the crew. They call for anchor at dusk and shelter in storms; overrule them and morale falls; low morale ends in mutiny.</p>
      <h3>Money and stores</h3><p>Prices come from each town's market (cheapest food, the state's sales tax). Everyone eats once a day; water runs out in three days on foot unless you pass a river, lake or town. Hunger and thirst slow you, then you collapse. Fishing is best in coastal shallows and on the map's fish and whale grounds; a boat's crew fishes with you. Foraging depends on the biome, the land's own food output, the season and the weather.</p>
      <h3>Side stories</h3><p>Notice boards post errands from the map: trade, relief for stricken towns, letters along alliances and enmities, dispatches for armies at war, strange places, offerings for faith seats. Rumours and sightings become leads (teal) in the journal.</p>
      <p>Tags: ${AZ.T("data")} read from the map files · ${AZ.T("mixed")} a stated rule applied to data · ${AZ.T("new")} invented for this playthrough. One tile is ${AZ.U.num(this.w.miles, 2)} miles.</p>
      <p class="dim">Esc to close</p></div>`);
  },
  async menu() {
    const k = await this.ui.choose("<b>Menu</b>", [{ label: "Journal: route, reasons, side stories (J)" }, { label: "World map (M)" }, { label: "Inspector (I)" }, { label: "Lens (L)" }, { label: "Save now" }, { label: "How to play (H)" }, { label: "New journey" }, { label: "Back" }], { cancel: 7 });
    if (k === 0) this.journal(); else if (k === 1) this.worldMap(); else if (k === 2) this.toggleInspect(); else if (k === 3) this.cycleLens();
    else if (k === 4) this.ui.toast(this.saveGame() ? "Saved in this browser." : "Could not save here.");
    else if (k === 5) this.help(); else if (k === 6) this.title(true);
  },
  mini() {
    const cv = this.ui.el.mini, ctx = cv.getContext("2d"), s = this.s, w = this.w;
    const W = cv.width, H = cv.height, sc = 1, x0 = s.c - W / 2 / sc, y0 = s.r - H / 2 / sc;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#0a0c18"; ctx.fillRect(0, 0, W, H);
    ctx.drawImage(this.ren.worldImage(), x0, y0, W / sc, H / sc, 0, 0, W, H);
    const lens = AZ.LENSES[this.lensIdx];
    if (lens.id !== "none") { ctx.globalAlpha = 0.45; ctx.drawImage(this.ren.lensWorld(lens), x0, y0, W / sc, H / sc, 0, 0, W, H); ctx.globalAlpha = 1; }
    const cpn = this.cpNext(), seg = cpn && cpn.legIn;
    if (seg) { ctx.fillStyle = "rgba(245,197,66,0.9)"; for (const [c, r] of seg.chain) ctx.fillRect((c - x0) * sc, (r - y0) * sc, 1, 1); }
    if (s.voyage && s.voyage.course) { ctx.fillStyle = "rgba(255,255,255,0.8)"; for (const [c, r] of s.voyage.course) ctx.fillRect((c - x0) * sc, (r - y0) * sc, 1, 1); }
    if (s.vessel && !s.aboard) { ctx.fillStyle = "#fff"; ctx.fillRect((s.vessel.c - x0) * sc - 1, (s.vessel.r - y0) * sc - 1, 3, 3); }
    ctx.fillStyle = "#ff3b3b"; ctx.fillRect(W / 2 - 2, H / 2 - 2, 4, 4);
  },
  worldMap() {
    const w = this.w, s = this.s, U = AZ.U, ui = this.ui;
    const maxW = Math.min(window.innerWidth - 40, 1600), sc = Math.min(maxW / w.cols, (window.innerHeight - 140) / w.rows);
    ui.modal(`<div class="mapwrap"><div class="maphead"><b>World map</b> · ${U.esc(w.P.world.name)} · lens: <span id="mlens">${AZ.LENSES[this.lensIdx].name}</span> · click: set a teal waypoint · L: lens · M/Esc: close</div><canvas id="wmap" width="${Math.round(w.cols * sc)}" height="${Math.round(w.rows * sc)}"></canvas><div id="minfo" class="dim">Brighter ground is ground you have seen.</div></div>`);
    const cv = document.getElementById("wmap"), ctx = cv.getContext("2d");
    const draw = () => {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(this.ren.worldImage(), 0, 0, cv.width, cv.height);
      const lens = AZ.LENSES[this.lensIdx];
      if (lens.id !== "none") { ctx.globalAlpha = 0.5; ctx.drawImage(this.ren.lensWorld(lens), 0, 0, cv.width, cv.height); ctx.globalAlpha = 1; }
      if (!this._fog) {
        this._fog = this.ren.mk(w.cols, w.rows);
      }
      const fctx = this._fog.getContext("2d"), img = fctx.createImageData(w.cols, w.rows);
      for (let i = 0; i < w.cols * w.rows; i++) if (!this.isExplored(i)) img.data[i * 4 + 3] = 110;
      fctx.putImageData(img, 0, 0);
      ctx.drawImage(this._fog, 0, 0, cv.width, cv.height);
      if (this.jr) for (const sg of this.jr.segs) if (sg.moving) {
        const cur = this.cpNext() && this.cpNext().legIn === sg; ctx.strokeStyle = cur ? "rgba(245,197,66,1)" : "rgba(245,197,66,0.5)"; ctx.lineWidth = cur ? 2 : 1;
        ctx.beginPath(); sg.chain.forEach(([c, r], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, (c + 0.5) * sc, (r + 0.5) * sc)); ctx.stroke();
      }
      for (const b of w.P.burgs) if (b) { ctx.fillStyle = b.capital ? "#fff" : "rgba(255,255,255,0.6)"; const z = b.capital ? 3 : 2; ctx.fillRect(b.t[0] * sc - z / 2, b.t[1] * sc - z / 2, z, z); }
      if (this.jr) for (const sg of this.jr.segs) { ctx.fillStyle = "#f5c542"; ctx.fillRect(sg.place.tile[0] * sc - 3, sg.place.tile[1] * sc - 3, 6, 6); }
      for (const l of s.leads) if (l && l.t) { ctx.fillStyle = "#4fd1c5"; ctx.fillRect(l.t[0] * sc - 2, l.t[1] * sc - 2, 4, 4); }
      if (s.waypoint) { ctx.strokeStyle = "#4fd1c5"; ctx.lineWidth = 2; ctx.strokeRect(s.waypoint[0] * sc - 5, s.waypoint[1] * sc - 5, 10, 10); }
      if (s.vessel && !s.aboard) { ctx.fillStyle = "#fff"; ctx.fillRect(s.vessel.c * sc - 3, s.vessel.r * sc - 3, 6, 6); }
      ctx.fillStyle = "#ff3b3b"; ctx.beginPath(); ctx.arc(s.c * sc, s.r * sc, 5, 0, 7); ctx.fill();
    };
    draw();
    cv.onclick = e => {
      const rect = cv.getBoundingClientRect(), c = Math.floor(((e.clientX - rect.left) / rect.width) * w.cols), r = Math.floor(((e.clientY - rect.top) / rect.height) * w.rows);
      s.waypoint = [c, r];
      const cell = w.cell(c, r), b = w.near(c, r, 3).find(n => n.kind === "burg");
      document.getElementById("minfo").innerHTML = `Waypoint: ${w.isLand(c, r) ? U.esc(w.P.biomes[w.C.biome[cell]].name) + " in " + U.esc(this.know.regionName(cell)) : U.esc(w.waterName(c, r))}${b ? " · near " + U.esc(b.o.name) : ""} · ${this.know.dirDist(s.c, s.r, [c, r]).txt} of you`;
      draw(); this.dirty = true;
    };
    ui.modalKey = e => {
      if (e.key === "l" || e.key === "L") { this.lensIdx = (this.lensIdx + (e.shiftKey ? -1 : 1) + AZ.LENSES.length) % AZ.LENSES.length; document.getElementById("mlens").textContent = AZ.LENSES[this.lensIdx].name; draw(); this.dirty = true; }
      else if (["Escape", "m", "M", "x", "X"].includes(e.key)) ui.closeModal();
    };
  },
  pickList(head, items, foot = "", start = 0) {
    return new Promise(res => {
      let i = items[start] && !items[start].disabled ? start : Math.max(0, items.findIndex(x => !x.disabled));
      const render = () => {
        this.ui.el.modal.innerHTML = `<div class="title">${head}<ul class="choices big">${items.map((x, k) => `<li data-k="${k}" class="${k === i ? "sel" : ""}${x.disabled ? " dis" : ""}">${k === i ? "▶ " : ""}${x.html}</li>`).join("")}</ul>${foot}</div>`;
        this.ui.el.modal.querySelectorAll("li").forEach(li => (li.onclick = () => { const k = +li.dataset.k; if (!items[k].disabled) done(items[k].id); }));
        const sel = this.ui.el.modal.querySelector("li.sel"); if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
      };
      const done = id => { this.ui.modalKey = null; res(id); };
      this.ui.el.modal.classList.add("on");
      this.ui.modalKey = e => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { do { i = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; } while (items[i].disabled); render(); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { if (items[i].cycle) { items[i].cycle(e.key === "ArrowRight" ? 1 : -1); done("__cycle"); } }
        else if (e.key === "Enter" || e.key === " ") done(items[i].id);
        else if (e.key === "Escape") done(null);
      };
      render();
    });
  },
  async title(fromMenu) {
    const U = AZ.U, w = this.w, jr = this.jr, can = this.hasSave() && !fromMenu;
    const head = `<div class="logo">${U.esc(jr ? jr.J.name : w.P.world.name)}</div><div class="sub">${U.esc(w.P.world.name)} (${U.esc(w.P.world.folder)}) · year ${w.W.calendar?.year || "?"} ${U.esc(w.W.calendar?.era || "")}</div>`;
    const foot = `<div class="dim">${U.num(w.cols)} × ${U.num(w.rows)} tiles of ${U.num(w.miles, 2)} mi · ${U.esc(w.P.grid.source)}</div>`;
    for (;;) {
      const a = await this.pickList(head, [{ id: "new", html: "New journey" }, ...(can ? [{ id: "cont", html: "Continue saved journey" }] : []), { id: "help", html: "How to play" }], foot);
      if (a === "help") { await new Promise(r => { this.help(); this.ui.onModalClose = r; }); continue; }
      if (a === "cont") { this.ui.closeModal(); this.loadGame(); this.started(); this.ui.toast(`Welcome back, ${U.esc(this.tv.name)}.`); return; }
      if (a !== "new") continue;
      const kinds = AZ.travellerKinds(w, jr);
      const kind = await this.pickList(`${head}<div class="sub">Who travels? ${AZ.T("mixed")} Each kind is found in this map's data.</div>`,
        [{ id: "__random", html: "Let chance decide" }, ...kinds.map(k => ({ id: k.id, html: `${U.esc(k.label)}<div class="dim small">${U.esc(k.blurb)}</div>` })), { id: "__back", html: "Back" }]);
      if (kind === null || kind === "__back") continue;
      let seed = (Date.now() ^ Math.floor(Math.random() * 1e9)) >>> 0, doys = [80, 172, 266, 355], di = 0;
      const lat0 = jr ? w.latlon(...jr.origin.tile)[0] : 0;
      for (;;) {
        const tv = AZ.makeTraveller(w, jr, seed, kind === "__random" ? null : kind);
        AZ.Clock.doy0 = doys[di];
        const seasonHere = AZ.Clock.season(lat0, 6), dl = AZ.Clock.dayLength(lat0, doys[di]);
        const card = `<div class="card win"><div class="who">${U.esc(tv.kindLabel)} ${AZ.T("new")}</div><b>${U.esc(tv.name)}</b>, ${tv.age}, ${U.esc(tv.trade)} · ${U.esc(w.P.cultures[tv.culture].name)} · ${U.esc(w.P.religions[tv.faith]?.name || "no faith")}<br>${U.cap(U.esc(tv.why))}.<br><span class="dim">Purse 🟡 ${tv.purse}${tv.thread ? ` · side story: <span class="side">${U.esc(tv.thread.title)}</span>` : ""}</span></div>`;
        const items = [{ id: "begin", html: "Begin" }, { id: "roll", html: "Another traveller like this" },
          { id: "season", html: `Departure: ${seasonHere} in ${U.esc(jr ? jr.origin.name : "the start")} (${Math.round(dl)} h of daylight) ◀ ▶`, cycle: d => { di = (di + d + 4) % 4; } },
          { id: "back", html: "Back" }];
        const r = await this.pickList(head + card, items, "", this._sel || 0);
        this._sel = r === "__cycle" || r === "season" ? 2 : 0;
        if (r === "roll") { seed = (seed * 1664525 + 1013904223) >>> 0; continue; }
        if (r === "__cycle") continue;
        if (r === "season") { di = (di + 1) % 4; continue; }
        if (r === "begin") {
          this.ui.closeModal(); this.fresh(seed, tv.kind, doys[di]); this.started(); this.saveGame();
          if (jr) await this.ui.say(this.know.intro(this));
          if (this.tv.thread) this.ui.toast(`Side story: <b class="side">${U.esc(this.tv.thread.title)}</b>. ${U.esc(this.tv.thread.steps[0].text)}`, "teal");
          return;
        }
        if (r === "back" || r === null) break;
        if (r === "season") continue;
      }
    }
  }
});

AZ.boot = async function (packText) {
  const status = document.getElementById("status");
  try {
    const P = await AZ.loadPack(packText);
    const w = new AZ.World(P);
    const mk = (W, H) => { const c = document.createElement("canvas"); c.width = W; c.height = H; return c; };
    const art = new AZ.Art(w, mk);
    const cv = document.getElementById("view");
    const ren = new AZ.Renderer(w, art, cv, mk);
    const jr = P.journeys.length ? new AZ.Journey(w, P.journeys[0]) : null;
    let store;
    try { store = window.localStorage; store.getItem("x"); } catch (e) { store = { getItem: () => null, setItem: () => { throw e; } }; }
    const ui = new AZ.UI();
    const g = new AZ.Game(w, ren, ui, jr, store);
    AZ.game = g;
    const fit = () => { cv.width = window.innerWidth; cv.height = window.innerHeight; g.dirty = true; };
    window.addEventListener("resize", fit); fit();
    status.remove();
    const DK = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", w: "up", s: "down", a: "left", d: "right", W: "up", S: "down", A: "left", D: "right" };
    window.addEventListener("keydown", e => {
      if (e.target && e.target.tagName === "INPUT") return;
      if (ui.key(e)) { e.preventDefault(); return; }
      if (!g.s) return;
      const k = e.key;
      if (DK[k]) { e.preventDefault(); if (g.s.auto) g.setAuto(false); if (!g.held.includes(DK[k])) g.held.push(DK[k]); return; }
      if (k === " " || k === "Enter" || k === "z" || k === "Z") { e.preventDefault(); g.interact(); }
      else if (k === "f" || k === "F") { if (e.shiftKey) { g.fast = true; g.setAuto(true); } else { g.fast = false; g.setAuto(!g.s.auto); } }
      else if (k === "r" || k === "R") g.rest();
      else if (k === "i" || k === "I") g.toggleInspect();
      else if (k === "l" || k === "L") g.cycleLens(e.shiftKey ? -1 : 1);
      else if (k === "m" || k === "M") g.worldMap();
      else if (k === "j" || k === "J") g.journal();
      else if (k === "h" || k === "H" || k === "?") g.help();
      else if (k === "+" || k === "=") { ren.zoom = Math.min(4, ren.zoom + 1); g.dirty = true; }
      else if (k === "-" || k === "_") { ren.zoom = Math.max(1, ren.zoom - 1); g.dirty = true; }
      else if (k === "Escape" || k === "x" || k === "X") g.menu();
    });
    window.addEventListener("keyup", e => { const d = DK[e.key]; if (d) g.held = g.held.filter(x => x !== d); });
    window.addEventListener("blur", () => (g.held = []));
    // touch controls
    document.querySelectorAll("[data-pad]").forEach(btn => {
      const d = btn.dataset.pad;
      const on = e => { e.preventDefault(); if (g.s?.auto) g.setAuto(false); if (!g.held.includes(d)) g.held.push(d); };
      const off = e => { e.preventDefault(); g.held = g.held.filter(x => x !== d); };
      btn.addEventListener("pointerdown", on); btn.addEventListener("pointerup", off); btn.addEventListener("pointerleave", off); btn.addEventListener("pointercancel", off);
    });
    document.querySelectorAll("[data-key]").forEach(btn => btn.addEventListener("click", e => {
      e.preventDefault();
      window.dispatchEvent(new KeyboardEvent("keydown", { key: btn.dataset.key }));
    }));
    g.title();
    const loop = now => { g.frame(now); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  } catch (err) {
    status.textContent = "Could not load the world: " + err.message;
    console.error(err);
  }
};
