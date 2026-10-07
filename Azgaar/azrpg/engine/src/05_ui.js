// ---------------------------------------------------------------------------------------------
// UI: windows in the RPG Maker manner. say() and choose() return promises, so scenes can be
// written as straight-line scripts.
// ---------------------------------------------------------------------------------------------
AZ.UI = class {
  constructor() {
    const $ = id => document.getElementById(id);
    this.el = { msg: $("msg"), modal: $("modal"), toasts: $("toasts"), banner: $("banner"), panel: $("panel"),
                loc: $("hud-loc"), trip: $("hud-trip"), legend: $("legend"), mini: $("mini") };
    this.active = null; // {type, ...}
    this.modalKey = null;
  }
  busy() { return !!this.active || !!this.modalKey; }
  say(pages, who) {
    pages = (Array.isArray(pages) ? pages : [pages]).filter(Boolean);
    if (!pages.length) return Promise.resolve();
    return new Promise(res => {
      let i = 0;
      const show = () => {
        this.el.msg.innerHTML = `${who ? `<div class="who">${who}</div>` : ""}<div class="page">${pages[i]}</div><div class="more">${i < pages.length - 1 ? "▼" : "■"}</div>`;
        this.el.msg.classList.add("on");
        this.el.msg.scrollTop = 0;
      };
      const next = () => {
        i++;
        if (i >= pages.length) { this.close(); res(); } else show();
      };
      this.active = { type: "say", next };
      this.el.msg.onclick = next;
      show();
    });
  }
  choose(prompt, options, opts = {}) {
    return new Promise(res => {
      let sel = options.findIndex(o => !o.disabled);
      const render = () => {
        this.el.msg.innerHTML = `${opts.who ? `<div class="who">${opts.who}</div>` : ""}${prompt ? `<div class="page">${prompt}</div>` : ""}<ul class="choices">${options.map((o, k) =>
          `<li data-k="${k}" class="${k === sel ? "sel " : ""}${o.cls || ""}${o.disabled ? " dis" : ""}">${k === sel ? "▶ " : "&nbsp;&nbsp;"}${o.label}</li>`).join("")}</ul>`;
        this.el.msg.classList.add("on");
        this.el.msg.querySelectorAll("li").forEach(li => {
          li.onclick = e => { e.stopPropagation(); const k = +li.dataset.k; if (!options[k].disabled) { this.close(); res(k); } };
        });
        const s = this.el.msg.querySelector("li.sel");
        if (s && s.scrollIntoView) s.scrollIntoView({ block: "nearest" });
      };
      const move = d => {
        for (let t = 0; t < options.length; t++) { sel = (sel + d + options.length) % options.length; if (!options[sel].disabled) break; }
        render();
      };
      this.active = { type: "choose", move, pick: () => { this.close(); res(sel); }, cancel: () => { if (opts.cancel != null) { this.close(); res(opts.cancel); } } };
      this.el.msg.onclick = null;
      render();
    });
  }
  close() { this.el.msg.classList.remove("on"); this.el.msg.innerHTML = ""; this.active = null; }
  key(e) {
    const a = this.active, k = e.key;
    if (this.modalKey) { this.modalKey(e); return true; }
    if (!a) return false;
    if (a.type === "say") { if ([" ", "Enter", "z", "Z", "Escape", "x", "X"].includes(k)) a.next(); return true; }
    if (a.type === "choose") {
      if (k === "ArrowUp" || k === "w" || k === "W") a.move(-1);
      else if (k === "ArrowDown" || k === "s" || k === "S") a.move(1);
      else if (k === "Enter" || k === " " || k === "z" || k === "Z") a.pick();
      else if (k === "Escape" || k === "x" || k === "X") a.cancel();
      return true;
    }
    return false;
  }
  toast(html, cls = "") {
    const d = document.createElement("div");
    d.className = "toast win " + cls;
    d.innerHTML = html;
    this.el.toasts.prepend(d);
    while (this.el.toasts.children.length > 5) this.el.toasts.lastChild.remove();
    setTimeout(() => d.classList.add("fade"), 5200);
    setTimeout(() => d.remove(), 6200);
  }
  banner(title, sub) {
    const b = this.el.banner;
    b.innerHTML = `<div class="t">${title}</div>${sub ? `<div class="s">${sub}</div>` : ""}`;
    b.classList.remove("on"); void b.offsetWidth; b.classList.add("on");
    clearTimeout(this._bt); this._bt = setTimeout(() => b.classList.remove("on"), 3200);
  }
  modal(html, onKey) {
    this.el.modal.innerHTML = html;
    this.el.modal.classList.add("on");
    this.modalKey = onKey || (e => { if (["Escape", "x", "X", "Enter", " "].includes(e.key)) this.closeModal(); });
  }
  closeModal() { this.el.modal.classList.remove("on"); this.el.modal.innerHTML = ""; this.modalKey = null; if (this.onModalClose) { const f = this.onModalClose; this.onModalClose = null; f(); } }
};
