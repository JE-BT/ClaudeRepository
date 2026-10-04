"""A clickable map of a town plan, served locally, to record which building a dwelling belongs to.

python -m azork pick <World> <burg> --dwelling <file.json>
opens the town in your browser. Click the building you generated the house from, give it a
name, and press Save: the placement goes into content/manifest.json and the server stops.
The best outline matches are outlined to help. Watabou exports may be mirrored relative to the
generator's view, so the page has a Flip button. Standard library only; nothing leaves your machine.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import placement, watabou

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{margin:0;font:14px system-ui,sans-serif;background:#f4f1ea;color:#222}}
#bar{{position:fixed;top:0;left:0;right:0;padding:8px 12px;background:#fff;border-bottom:1px solid #ccc;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
svg{{position:fixed;top:48px;left:0;width:100vw;height:calc(100vh - 48px);cursor:grab}}
.b{{fill:#cdbfa6;stroke:#6b5e4b;stroke-width:.3}} .b:hover{{fill:#e8c77a}} .sel{{fill:#d9534f!important}}
.cand{{stroke:#1f77b4;stroke-width:1.2}} .road{{fill:none;stroke:#fff;stroke-linecap:round}} .wall{{fill:none;stroke:#555}}
.water{{fill:#a8c8e8}} button{{padding:4px 10px}} input{{padding:3px 6px}}
</style></head><body>
<div id="bar"><b>{title}</b><span id="info">Click a building.</span>
<input id="label" placeholder="Name of the house" value="{label}" size="24">
<button id="save" disabled>Save</button><button id="flip">Flip</button><span id="msg"></span>
<span style="color:#1f77b4">{hint}</span></div>
<svg id="map" viewBox="{vb}"><g id="g" transform="scale(1,{sy})">{shapes}</g></svg>
<script>
const svg=document.getElementById('map'),g=document.getElementById('g');let sel=null,flip={sy};
let vb=svg.getAttribute('viewBox').split(' ').map(Number);
document.querySelectorAll('.b').forEach(p=>p.addEventListener('click',e=>{{
 if(sel)sel.classList.remove('sel');sel=p;p.classList.add('sel');
 document.getElementById('info').textContent='Building '+p.dataset.i+', '+p.dataset.a+' m\u00b2'+(p.dataset.s?', outline match '+p.dataset.s:'');
 document.getElementById('save').disabled={nosave};}}));
document.getElementById('flip').onclick=()=>{{flip=-flip;g.setAttribute('transform','scale(1,'+flip+')');vb[1]=-vb[1]-vb[3];svg.setAttribute('viewBox',vb.join(' '));}};
document.getElementById('save').onclick=async()=>{{
 const r=await fetch('/save',{{method:'POST',body:JSON.stringify({{building:+sel.dataset.i,label:document.getElementById('label').value}})}});
 document.getElementById('msg').textContent=await r.text();}};
svg.addEventListener('wheel',e=>{{e.preventDefault();const k=e.deltaY>0?1.15:1/1.15;const r=svg.getBoundingClientRect();
 const mx=vb[0]+(e.clientX-r.left)/r.width*vb[2],my=vb[1]+(e.clientY-r.top)/r.height*vb[3];
 vb=[mx-(mx-vb[0])*k,my-(my-vb[1])*k,vb[2]*k,vb[3]*k];svg.setAttribute('viewBox',vb.join(' '));}},{{passive:false}});
let drag=null;svg.addEventListener('mousedown',e=>drag=[e.clientX,e.clientY]);window.addEventListener('mouseup',()=>drag=null);
window.addEventListener('mousemove',e=>{{if(!drag)return;const r=svg.getBoundingClientRect();
 vb[0]-=(e.clientX-drag[0])/r.width*vb[2];vb[1]-=(e.clientY-drag[1])/r.height*vb[3];drag=[e.clientX,e.clientY];svg.setAttribute('viewBox',vb.join(' '));}});
</script></body></html>"""


def _pts(ring) -> str:
    return " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in ring)


def render(town_path: Path, title: str, dwelling: Path | None = None, label: str = "") -> str:
    town = watabou.load(town_path)
    scores = {}
    hint = ""
    if dwelling:
        ranked = placement.rank(town, dwelling, 5)
        scores = {r["building"]: r["shape"] for r in ranked}
        hint = "Outlined in blue: best outline matches (" + ", ".join(str(r["building"]) for r in ranked) + ")"
    xs = [p[0] for b in town.buildings for p in b.ring]
    ys = [p[1] for b in town.buildings for p in b.ring]
    pad = 20
    shapes = []
    for r in town.roads:
        shapes.append(f'<polyline class="road" stroke-width="{max(r["width"], 1):.1f}" points="{_pts(r["points"])}"/>')
    for wl in town.walls:
        shapes.append(f'<polygon class="wall" stroke-width="{max(wl["width"], 1):.1f}" points="{_pts(wl["ring"])}"/>')
    for b in town.buildings:
        cand = " cand" if b.index in scores else ""
        s = f' data-s="{scores[b.index]:.2f}"' if b.index in scores and scores[b.index] is not None else ""
        shapes.append(f'<polygon class="b{cand}" data-i="{b.index}" data-a="{b.area:.0f}"{s} points="{_pts(b.ring)}"/>')
    sy = -1  # GeoJSON y points up; the Flip button switches
    vb = f"{min(xs) - pad:.1f} {-(max(ys) + pad):.1f} {max(xs) - min(xs) + 2 * pad:.1f} {max(ys) - min(ys) + 2 * pad:.1f}"
    return PAGE.format(title=title, label=label, vb=vb, sy=sy, shapes="".join(shapes), hint=hint,
                       nosave="false" if dwelling else "true")


def serve(html: str, on_save, port: int = 8765, open_browser: bool = True, once: bool = True) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = on_save(data)
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if once:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}/")
    return server


def save_placement(manifest: Path, filename: str, burg: int, building: int, label: str, role: str | None = None) -> str:
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"files": {}}
    data.setdefault("files", {})[filename] = {"burg": burg, "building": building, "label": label, "source": "azork pick",
                                              **({"role": role} if role else {})}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Saved: {filename} is '{label}', building {building}. You can close this tab."
