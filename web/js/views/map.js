/* World map: wrap-around equirectangular, monochrome headcount markers, day/night terminator. */
import { $, esc, attr, icon, debounce, fmt } from "../ui.js";
import { api, state, settings, save } from "../store.js";
import { ltHtml, nightPolygon } from "../time.js";
import { setParams, openDrawer } from "../app.js";
import { LAND, BORDERS } from "../geo-data.js";

const W0 = 3600, H0 = 1800;               // world units: 10 per degree
const wx = (lon) => (lon + 180) * 10;
const wy = (lat) => (90 - lat) * 10;
let worldPaths = null;
let root, svg, stage, q = "", locs = [], view = null, drag = null, hoverId = "", selId = "", nightTimer = null, tip;

export default {
  id: "map", label: "Map", key: "m",
  mount(el, r) {
    root = el;
    q = r.params.get("q") || "";
    const d = r.params.get("d") || "";
    selId = d.startsWith("l:") ? d.slice(2) : "";
    el.innerHTML = `<div class="mapv">
      <div class="map-panel">
        <div class="ph"><input class="input mono" id="mq" data-filter-input placeholder='fn:cyber   org:"ATLAS COMMAND"' value="${attr(q)}" spellcheck="false" aria-label="Filter">
          <div class="countline" id="msum"></div></div>
        <div class="pb" id="mlist"></div>
      </div>
      <div class="map-stage" id="mstage"><svg class="map" id="msvg" role="img" aria-label="Where people are"></svg>
        <div class="map-tools"><button class="btn sm quiet ${settings.mapNight ? "on" : ""}" data-t="night" aria-pressed="${!!settings.mapNight}">Night</button><button class="btn sm quiet ${settings.mapLabels ? "on" : ""}" data-t="labels" aria-pressed="${!!settings.mapLabels}">Labels</button>
          <button class="btn sm icon quiet" data-z="out" aria-label="Zoom out">${icon("minus")}</button><button class="btn sm icon quiet" data-z="in" aria-label="Zoom in">${icon("plus")}</button><button class="btn sm icon quiet" data-z="fit" aria-label="Fit">${icon("fit")}</button></div>
        <div class="map-tip hidden" id="mtip"></div></div></div>`;
    svg = $("#msvg", el);
    stage = $("#mstage", el);
    tip = $("#mtip", el);
    $("#mq", el).addEventListener("input", debounce((e) => { q = e.target.value.trim(); setParams({ q }); load(); }, 300));
    el.querySelector(".map-tools").addEventListener("click", onTools);
    $("#mlist", el).addEventListener("click", (e) => { const it = e.target.closest("[data-id]"); if (it) focusLoc(it.dataset.id, true); });
    $("#mlist", el).addEventListener("mouseover", (e) => { const it = e.target.closest("[data-id]"); hoverId = it ? it.dataset.id : ""; drawMarkers(); });
    bindPanZoom();
    window.addEventListener("resize", onResize);
    window.addEventListener("orgx:data", load);
    nightTimer = setInterval(drawNight, 60_000);
    drawBase();
    load();
  },
  update(r) {
    const nq = r.params.get("q") || "";
    const d = r.params.get("d") || "";
    selId = d.startsWith("l:") ? d.slice(2) : "";
    if (nq !== q) { q = nq; $("#mq", root).value = q; load(); }
    else { drawMarkers(); renderList(); }
  },
  unmount() {
    window.removeEventListener("resize", onResize);
    window.removeEventListener("orgx:data", load);
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    clearInterval(nightTimer);
  },
};
const onResize = debounce(() => { if (view) { clampView(); apply(); } }, 80);

async function load() {
  const res = await api("/api/locations", { q }).catch(() => ({ locations: [], unplaced: 0 }));
  locs = res.locations.filter((l) => l.lat != null);
  const n = res.locations.reduce((a, l) => a + (l.np || 0), 0);
  $("#msum", root).innerHTML = `<span><b>${fmt(n)}</b> people at <b>${locs.length}</b> bases${res.unplaced ? `, ${fmt(res.unplaced)} records with no base` : ""}</span>`;
  if (!view) fitAll();
  renderList();
  drawMarkers();
}
function renderList() {
  $("#mlist", root).innerHTML = [...locs].sort((a, b) => (b.np || 0) - (a.np || 0)).map((l) => `<div class="loc-row${l.id === selId ? " on" : ""}" data-id="${attr(l.id)}">
      <span class="nm ellip">${esc(l.name)}${l.approx ? " (approx.)" : ""}</span><span class="n">${fmt(l.np || 0)}</span>
      <span class="s ellip">${esc(l.region || l.country || "")}${l.units?.[0] ? ", " + esc(l.units[0][0]) : ""}</span><span>${ltHtml(l.tz)}</span></div>`).join("")
    || `<div class="empty">No mapped bases for this filter.</div>`;
}

/* ---------------------------------------------------------------- base layers */
function ringPath(arr) {
  let d = "";
  for (let i = 0; i < arr.length; i += 2) d += (i ? "L" : "M") + wx(arr[i]).toFixed(1) + "," + wy(arr[i + 1]).toFixed(1);
  return d;
}
function drawBase() {
  if (!worldPaths) {
    let g = "";
    for (let lon = -180; lon <= 180; lon += 30) g += `M${wx(lon)},${wy(80)}L${wx(lon)},${wy(-60)}`;
    for (let lat = -60; lat <= 60; lat += 30) g += `M0,${wy(lat)}L${W0},${wy(lat)}`;
    worldPaths = { land: LAND.map((r) => ringPath(r) + "Z").join(""), borders: BORDERS.map(ringPath).join(""), grat: g };
  }
  svg.innerHTML = `<defs><g id="world"><path class="grat" d="${worldPaths.grat}"/><path class="land" d="${worldPaths.land}"/><path class="borders" d="${worldPaths.borders}"/><path class="night" id="night"/></g></defs>
    <g id="vp"><use href="#world" x="${-W0}"/><use href="#world"/><use href="#world" x="${W0}"/></g><g id="marks"></g>`;
  drawNight();
}
function drawNight() {
  const n = svg?.querySelector("#night");
  if (!n) return;
  if (!settings.mapNight) return n.setAttribute("d", "");
  n.setAttribute("d", nightPolygon().map(([lo, la], i) => `${i ? "L" : "M"}${wx(lo).toFixed(1)},${wy(Math.max(-89.9, Math.min(89.9, la))).toFixed(1)}`).join("") + "Z");
}

/* ---------------------------------------------------------------- view */
const size = () => ({ w: stage.clientWidth || 1000, h: stage.clientHeight || 600 });
function fitAll() {
  const { w, h } = size();
  if (!locs.length) { view = { k: w / W0, x: 0, y: 0 }; clampView(); return apply(); }
  const lons = locs.map((l) => ((l.lon % 360) + 360) % 360).sort((a, b) => a - b);
  let gap = 0, gapAt = 0;
  for (let i = 0; i < lons.length; i++) {
    const g = (i === lons.length - 1 ? lons[0] + 360 : lons[i + 1]) - lons[i];
    if (g > gap) { gap = g; gapAt = i; }
  }
  const start = lons[(gapAt + 1) % lons.length], span = Math.max(20, 360 - gap);
  const lats = locs.map((l) => l.lat), lat0 = Math.max(...lats), lat1 = Math.min(...lats);
  const k = Math.max(w / W0, Math.min((w - 80) / (span * 10), (h - 90) / (Math.max(15, lat0 - lat1) * 10), 2.2));
  const cLon = ((start + span / 2 + 180) % 360) - 180;
  view = { k, x: w / 2 - wx(cLon) * k, y: h / 2 - wy((lat0 + lat1) / 2) * k };
  clampView();
  apply();
}
function clampView() {
  const { w, h } = size();
  view.k = Math.max(w / W0, view.k);
  const Wk = W0 * view.k;
  view.x = (((view.x % Wk) + Wk) % Wk) - Wk;
  const top = wy(84) * view.k, bot = wy(-60) * view.k;
  if (bot - top <= h) view.y = (h - (bot - top)) / 2 - top;
  else view.y = Math.min(-top, Math.max(h - bot, view.y));
}
function apply() {
  svg.querySelector("#vp")?.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  drawMarkers();
}
function zoomAt(f, cx, cy) {
  const k = Math.max(size().w / W0, Math.min(60, view.k * f));
  view.x = cx - ((cx - view.x) * k) / view.k;
  view.y = cy - ((cy - view.y) * k) / view.k;
  view.k = k;
  clampView();
  apply();
}
function focusLoc(id, open) {
  const l = locs.find((x) => x.id === id);
  if (!l) return;
  const { w, h } = size();
  view.k = Math.max(view.k, 3.2);
  view.x = w / 2 - wx(l.lon) * view.k;
  view.y = h / 2 - wy(l.lat) * view.k;
  clampView();
  apply();
  if (open) openDrawer("l:" + id);
}
function bindPanZoom() {
  svg.addEventListener("pointerdown", (e) => { if (e.button === 0) { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; svg.classList.add("grabbing"); } });
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  svg.addEventListener("dblclick", (e) => { const r = svg.getBoundingClientRect(); zoomAt(2, e.clientX - r.left, e.clientY - r.top); });
  svg.addEventListener("click", (e) => {
    if (drag?.moved) return;
    const m = e.target.closest(".mk");
    if (!m) return;
    if (m.dataset.cluster) { const r = svg.getBoundingClientRect(); return zoomAt(2.6, e.clientX - r.left, e.clientY - r.top); }
    openDrawer("l:" + m.dataset.id);
  });
  svg.addEventListener("mousemove", (e) => { const m = e.target.closest(".mk"); if (!m || drag) return tip.classList.add("hidden"); showTip(m, e); });
  svg.addEventListener("mouseleave", () => tip.classList.add("hidden"));
}
function onMove(e) {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  view.x = drag.vx + dx;
  view.y = drag.vy + dy;
  clampView();
  apply();
}
function onUp() { svg?.classList.remove("grabbing"); setTimeout(() => (drag = null), 0); }
function onTools(e) {
  const z = e.target.closest("[data-z]")?.dataset.z;
  const { w, h } = size();
  if (z === "in") zoomAt(1.5, w / 2, h / 2);
  if (z === "out") zoomAt(1 / 1.5, w / 2, h / 2);
  if (z === "fit") fitAll();
  const t = e.target.closest("[data-t]");
  if (t?.dataset.t === "night") { save({ mapNight: !settings.mapNight }); t.classList.toggle("on", settings.mapNight); drawNight(); }
  if (t?.dataset.t === "labels") { save({ mapLabels: !settings.mapLabels }); t.classList.toggle("on", settings.mapLabels); drawMarkers(); }
}

/* ---------------------------------------------------------------- markers */
function screen(l) {
  const Wk = W0 * view.k, { w } = size();
  let x = (((wx(l.lon) * view.k + view.x) % Wk) + Wk) % Wk;
  if (x > w + 30 && x - Wk > -30) x -= Wk;
  return [x, wy(l.lat) * view.k + view.y];
}
const radius = (n) => Math.min(30, 4 + Math.sqrt(n) * 1.4);
function drawMarkers() {
  const host = svg?.querySelector("#marks");
  if (!host || !view) return;
  const { w, h } = size();
  const pts = locs.map((l) => { const [x, y] = screen(l); const n = l.np || l.n; return { l, x, y, r: radius(n), n }; })
    .filter((p) => p.x > -60 && p.x < w + 60 && p.y > -60 && p.y < h + 60).sort((a, b) => b.n - a.n);
  const clusters = [];
  for (const p of pts) {
    const c = clusters.find((c) => Math.hypot(c.x - p.x, c.y - p.y) < (c.r + p.r) * 0.75);
    if (c && p.l.id !== selId && c.members[0].l.id !== selId) { c.members.push(p); c.n += p.n; c.r = radius(c.n); }
    else clusters.push({ x: p.x, y: p.y, r: p.r, n: p.n, members: [p] });
  }
  let html = "";
  const labels = [];
  for (const c of clusters) {
    const single = c.members.length === 1, l = c.members[0].l;
    const on = single && (l.id === selId || l.id === hoverId);
    html += `<g class="mk${on ? " on" : ""}${single && l.approx ? " approx" : ""}" ${single ? `data-id="${attr(l.id)}"` : `data-cluster="1" data-ids="${attr(c.members.map((m) => m.l.id).join("|"))}"`} transform="translate(${c.x.toFixed(1)},${c.y.toFixed(1)})">
      <circle class="dot" r="${c.r.toFixed(1)}"/>${c.r >= 11 ? `<text class="c">${c.n >= 1000 ? (c.n / 1000).toFixed(1) + "k" : c.n}</text>` : ""}</g>`;
    if (settings.mapLabels) labels.push({ x: c.x + c.r + 4, y: c.y + 4, t: single ? l.name : `${l.name} and ${c.members.length - 1} more`, n: c.n, on });
  }
  const placed = [];
  for (const lb of labels.sort((a, b) => (b.on - a.on) || b.n - a.n)) {
    const box = [lb.x, lb.y - 11, lb.x + lb.t.length * 6.6, lb.y + 3];
    if (placed.some((p) => !(box[2] < p[0] || box[0] > p[2] || box[3] < p[1] || box[1] > p[3]))) continue;
    placed.push(box);
    html += `<g class="mk" style="pointer-events:none"><text x="${lb.x.toFixed(1)}" y="${lb.y.toFixed(1)}">${esc(lb.t)}</text></g>`;
  }
  host.innerHTML = html;
}
function showTip(m, e) {
  const ids = m.dataset.id ? [m.dataset.id] : (m.dataset.ids || "").split("|");
  const ls = ids.map((id) => locs.find((l) => l.id === id)).filter(Boolean);
  if (!ls.length) return;
  const r = stage.getBoundingClientRect();
  let h;
  if (ls.length === 1) {
    const l = ls[0];
    h = `<b>${esc(l.name)}</b>${l.approx ? " (approximate)" : ""}<div class="muted">${esc(l.full || "")}${l.region ? ", " + esc(l.region) : ""}</div>
      <div style="margin:4px 0">${ltHtml(l.tz, { long: true })}</div><div><b>${fmt(l.np || 0)}</b> people, ${fmt(l.n)} records</div>
      <table class="tbl" style="margin-top:4px"><tbody>${l.units.map(([u, n]) => `<tr><td>${esc(u)}</td><td class="num">${n}</td></tr>`).join("")}</tbody></table>`;
  } else {
    h = `<b>${ls.length} bases</b> <span class="muted">click to zoom in</span><table class="tbl"><tbody>${ls.slice(0, 8).map((l) => `<tr><td>${esc(l.name)}</td><td class="num">${fmt(l.np || l.n)}</td></tr>`).join("")}</tbody></table>`;
  }
  tip.innerHTML = h;
  tip.classList.remove("hidden");
  tip.style.left = Math.min(e.clientX - r.left + 16, r.width - 310) + "px";
  tip.style.top = Math.min(e.clientY - r.top + 12, r.height - tip.offsetHeight - 10) + "px";
}
