/* People: the home screen. Units and bases on the left, the org chart (or map) in the middle,
   the selected person or unit on the right, and the people of the selected unit underneath.
   Search lives in the header and drops results over the canvas; picking someone shows where
   they sit in the chart. */
import { $, esc, attr, fmt, debounce, icon, shortOrg, clearable } from "../ui.js";
import { api, state, settings, save, isStarred, liveFetch } from "../store.js";
import { ltHtml } from "../time.js";
import { setParams, openDrawer } from "../app.js";
import { openEmailBuilder } from "../email.js";
import mapView from "./map.js";

const NW = 200, NH = 66, GX = 22, GY = 14, LV = 56;     // chart node size and gaps
let root, ws, u = "", canvas = "chart", tree = null, view = { x: 0, y: 0, k: 1 }, drag = null, personOrg = "", mapMounted = false;
let reqTree = 0, reqStrip = 0, stripScope = "direct", railTab = "units", syncFilter = () => {};

export default {
  id: "home", label: "People", key: "p",
  mount(el, r) {
    root = el;
    u = r.params.get("u") || settings.homeOrg || "";
    canvas = r.params.get("c") === "map" ? "map" : "chart";
    el.innerHTML = `<div class="ws${settings.stripOpen === false ? " strip-closed" : ""}" id="ws">
      <aside class="rail" id="rail"></aside>
      <section class="canvas">
        <div class="cv-head"><nav class="crumbs" id="crumbs" aria-label="Unit path"></nav><span class="sp"></span>
          <span class="seg" role="group" aria-label="Canvas"><button data-cv="chart" class="${canvas === "chart" ? "on" : ""}">Org chart</button><button data-cv="map" class="${canvas === "map" ? "on" : ""}">Map</button></span>
          <span class="zoom" id="zoom"><button class="btn sm icon quiet" data-z="out" aria-label="Zoom out">${icon("minus")}</button><button class="btn sm icon quiet" data-z="in" aria-label="Zoom in">${icon("plus")}</button><button class="btn sm icon quiet" data-z="fit" aria-label="Fit">${icon("fit")}</button></span></div>
        <div class="cv-body" id="cvbody"><svg class="chart-svg" id="chart" role="img" aria-label="Org chart"></svg><div class="cv-map hidden" id="cvmap"></div></div>
      </section>
      <section class="pstrip" id="strip"></section>
    </div>`;
    ws = $("#ws", el);
    ws.appendChild($("#drawer"));
    el.querySelector(".cv-head").addEventListener("click", onHeadClick);
    $("#rail", el).addEventListener("click", onRailClick);
    $("#rail", el).addEventListener("input", debounce(onRailFilter, 200));
    $("#strip", el).addEventListener("click", onStripClick);
    bindChart();
    window.addEventListener("resize", fitSoon);
    window.addEventListener("orgx:data", reloadAll);
    window.addEventListener("orgx:live", liveArrived);
    renderRail();
    applyCanvas(r);
    loadTree();
    loadStrip();
    syncCard(r);
  },
  update(r) {
    const nu = r.params.get("u") ?? "";
    const nc = r.params.get("c") === "map" ? "map" : "chart";
    if (nc !== canvas) { canvas = nc; applyCanvas(r); }
    if (nu !== u) { u = nu; loadTree(); loadStrip(); markTree(); if (mapMounted) mapView.update(mapParams(r)); }
    else if (mapMounted) mapView.update(mapParams(r));
    syncCard(r);
  },
  unmount() {
    document.body.appendChild($("#drawer"));
    if (mapMounted) mapView.unmount();
    mapMounted = false;
    window.removeEventListener("resize", fitSoon);
    window.removeEventListener("orgx:data", reloadAll);
    window.removeEventListener("orgx:live", liveArrived);
  },
};

function reloadAll() { loadTree(); loadStrip(); renderRail(); }
// on-the-fly mode: records arrived from Active Directory; redraw what shows them (once, after a burst)
const liveArrived = debounce(() => { loadTree(); loadStrip(); if (!root.querySelector("[data-unitfilter]")?.value) (railTab === "bases" ? renderBases() : loadUnits()); }, 300);
const fitSoon = debounce(() => { if (canvas === "chart") drawChart(true); }, 80);

/* ---------------------------------------------------------------- card: person, or the unit when nobody is picked */
async function syncCard(r) {
  const d = r.params.get("d") || "";
  ws.classList.toggle("no-card", !d && !u);
  if (!d && u && matchMedia("(min-width: 1081px)").matches) { setTimeout(() => { if (!new URLSearchParams(location.hash.split("?")[1] || "").get("d")) setParams({ d: "o:" + u }); }, 0); return; }   // after this route finishes
  if (d.startsWith("p:")) {
    // show where the person sits: their unit lights up in the chart
    const key = d.slice(2);
    const res = await api("/api/search", { q: `key:${key}`, limit: 1 }).catch(() => null);
    personOrg = res?.rows?.[0]?.org_id || "";
    const node = lastLayout?.nodes.find((n) => n.n?.id === personOrg);
    if (personOrg && !node && personOrg !== u) return setTimeout(() => setParams({ u: personOrg }), 0);   // move the chart to where they sit
    drawChart(false);
    if (node && canvas === "chart") centerOn(node);
    root.querySelectorAll(".tile.active").forEach((t) => t.classList.remove("active"));
    root.querySelector(`.tile[data-k="${CSS.escape(key)}"]`)?.classList.add("active");
  } else { personOrg = ""; drawChart(false); }
}
const pickUnit = (id) => setParams({ u: id, d: id ? "o:" + id : "" }, { replace: false });

/* ---------------------------------------------------------------- rail: the organization by unit or by base (starred people live in the strip) */
function renderRail() {
  $("#rail", root).innerHTML = `
    <span class="seg sm rail-tabs" role="group" aria-label="Browse by"><button data-rtab="units" class="${railTab === "units" ? "on" : ""}">Units</button><button data-rtab="bases" class="${railTab === "bases" ? "on" : ""}">Bases</button></span>
    <span class="fwrap"><input class="input" data-unitfilter placeholder="Filter" aria-label="Filter units or bases"></span>
    <div class="utree" id="utree"><div class="loading">Loading…</div></div>`;
  const f = root.querySelector("[data-unitfilter]");
  syncFilter = clearable(f, () => (railTab === "bases" ? renderBases() : loadUnits()));
  f.addEventListener("keydown", (e) => { if (e.key === "Escape" && f.value) { e.stopPropagation(); f.value = ""; syncFilter(); railTab === "bases" ? renderBases() : loadUnits(); } });
  railTab === "bases" ? renderBases() : loadUnits();
}
function renderBases(q = "") {
  const needle = q.toLowerCase();
  const locs = [...state.locs.values()].filter((l) => (l.np || 0) > 0 && (!needle || l.name.toLowerCase().includes(needle))).sort((a, b) => (b.np || 0) - (a.np || 0));
  $("#utree", root).innerHTML = locs.map((l) => `<button class="rl" data-base="${attr(l.id)}"><span class="ellip">${esc(l.name)}</span><span class="n">${fmt(l.np || 0)}</span></button>`).join("") || `<p class="note">No base matches.</p>`;
}
async function loadUnits(parent = null, host = null, depth = 0) {
  const rows = await api("/api/orgs", parent ? { parent } : {}).catch(() => []);
  const target = host || $("#utree", root);
  if (!target) return;
  const html = rows.map((o) => `<div class="un" style="--d:${depth}"><button class="tw" data-tw="${attr(o.id)}" aria-label="${o.kids ? "Expand" : ""}" ${o.kids ? "" : "disabled"}>${o.kids ? "+" : ""}</button><button class="ul${o.id === u ? " on" : ""}" data-unit="${attr(o.id)}" title="${attr(o.id)}"><span class="ellip">${esc(o.name)}</span><span class="n">${fmt(o.people)}</span></button></div><div class="kids" data-kids="${attr(o.id)}"></div>`).join("");
  if (host) host.innerHTML = html; else target.innerHTML = html || `<p class="note">No units yet.</p>`;
}
async function onRailFilter(e) {
  if (!e.target.matches("[data-unitfilter]")) return;
  const q = e.target.value.trim();
  if (railTab === "bases") return renderBases(q);
  if (!q) return loadUnits();
  const rows = await api("/api/orgs", { q }).catch(() => []);
  if (e.target.value.trim() !== q) return;            // typed on while this was loading
  // matches grouped under their top unit, so the shared prefix is read once
  const groups = new Map();
  for (const o of rows) {
    const top = o.id.split("/")[0];
    if (!groups.has(top)) groups.set(top, { top, self: null, kids: [] });
    const g = groups.get(top);
    if (o.id === top) g.self = o; else g.kids.push(o);
  }
  const line = (id, label, n, d, kids) => `<div class="un" style="--d:${d}">${kids ? `<button class="tw" data-tw="${attr(id)}" aria-label="Expand">+</button>` : `<span class="tw"></span>`}<button class="ul${id === u ? " on" : ""}" data-unit="${attr(id)}" title="${attr(id)}"><span class="ellip">${esc(label)}</span><span class="n">${n == null ? "" : fmt(n)}</span></button></div>${kids ? `<div class="kids" data-kids="${attr(id)}"></div>` : ""}`;
  const byPath = (a, b) => a.id.localeCompare(b.id, "en", { numeric: true });
  $("#utree", root).innerHTML = [...groups.values()].map((g) =>
    line(g.top, g.top, g.self?.people, 0, g.self?.kids) + g.kids.sort(byPath).map((o) => line(o.id, o.id.slice(g.top.length + 1), o.people, 1, o.kids)).join("")).join("")
    || `<p class="note">No unit matches.</p>`;
}
function markTree() {
  root.querySelectorAll("#utree .ul").forEach((b) => b.classList.toggle("on", b.dataset.unit === u));
}
function onRailClick(e) {
  const rt = e.target.closest("[data-rtab]");
  if (rt) { railTab = rt.dataset.rtab; return renderRail(); }
  const tw = e.target.closest("[data-tw]");
  if (tw) {
    const box = root.querySelector(`[data-kids="${CSS.escape(tw.dataset.tw)}"]`);
    if (box.childElementCount) { box.innerHTML = ""; tw.textContent = "+"; }
    else { tw.textContent = "−"; loadUnits(tw.dataset.tw, box, (+tw.closest(".un").style.getPropertyValue("--d") || 0) + 1); }
    return;
  }
  const un = e.target.closest("[data-unit]");
  if (un) return pickUnit(un.dataset.unit);
  const b = e.target.closest("[data-base]");
  if (b) setParams({ c: "map", d: "l:" + b.dataset.base }, { replace: false });
}

/* ---------------------------------------------------------------- canvas */
function onHeadClick(e) {
  const cv = e.target.closest("[data-cv]");
  if (cv) return setParams({ c: cv.dataset.cv === "map" ? "map" : "" }, { replace: false });
  const z = e.target.closest("[data-z]")?.dataset.z;
  if (z === "fit") fit();
  else if (z) zoomAt(z === "in" ? 1.25 : 0.8);
  const cr = e.target.closest("[data-crumb]");
  if (cr) pickUnit(cr.dataset.crumb);
}
const mapParams = (r) => {
  const p = new URLSearchParams(r.params);
  p.set("q", u ? `org:"${u}"` : "");
  return { params: p };
};
function applyCanvas(r) {
  root.querySelectorAll("[data-cv]").forEach((b) => b.classList.toggle("on", b.dataset.cv === canvas));
  $("#chart", root).classList.toggle("hidden", canvas !== "chart");
  $("#zoom", root).classList.toggle("hidden", canvas !== "chart");
  const m = $("#cvmap", root);
  m.classList.toggle("hidden", canvas !== "map");
  if (canvas === "map" && !mapMounted) { mapView.mount(m, mapParams(r)); mapMounted = true; }
  if (canvas === "chart") requestAnimationFrame(fit);
}

/* ---------------------------------------------------------------- org chart: top-down, children in a row, grandchildren stacked */
async function loadTree() {
  const my = ++reqTree;
  const t = await api("/api/orgtree", u ? { root: u, depth: 2, cap: 30 } : { depth: 2, cap: 30 }).catch(() => null);
  if (my !== reqTree || !t || t.error) return;
  tree = t;
  renderCrumbs();
  drawChart(true);
  if (u) liveFetch("unit", { id: u });      // on-the-fly mode: fill this unit in from Active Directory
}
function renderCrumbs() {
  const chain = [{ id: "", name: "All units" }, ...(tree.chain || []), ...(u ? [{ id: tree.id, name: tree.name }] : [])];
  $("#crumbs", root).innerHTML = chain.map((c, i) => i === chain.length - 1 ? `<b>${esc(c.name)}</b>` : `<a data-crumb="${attr(c.id)}">${esc(c.name)}</a><span class="sep">›</span>`).join("");
}
const SHOW = 6;   // sub-units listed under each unit before "N more"
function layout() {
  // parent on top; its units in rows that fit the canvas at full size; each unit's sub-units stacked beneath it
  const kids = tree.children || [];
  const nodes = [], edges = [];
  const colW = NW + GX, SH = NH - 14;
  const avail = Math.max(colW * 2, ($("#chart", root)?.clientWidth || 1000) - 64);
  const cols = Math.max(2, Math.min(kids.length || 1, Math.floor((avail + GX) / colW)));
  const width = Math.max(NW, Math.min(kids.length, cols) * colW - GX);
  const rx = (width - NW) / 2;
  nodes.push({ n: tree, x: rx, y: 0, root: true });
  let y = NH + LV, lastBus = NH;
  for (let r = 0; r * cols < kids.length; r++) {
    const row = kids.slice(r * cols, (r + 1) * cols);
    const rowW = row.length * colW - GX, x0 = (width - rowW) / 2, bus = y - LV / 2;
    const centers = row.map((_, i) => x0 + i * colW + NW / 2);
    edges.push(`M${Math.min(...centers, rx + NW / 2)},${bus} H${Math.max(...centers, rx + NW / 2)}`);
    lastBus = bus;
    let bottom = y + NH;
    row.forEach((k, i) => {
      const x = x0 + i * colW;
      nodes.push({ n: k, x, y });
      edges.push(`M${centers[i]},${bus} V${y}`);
      const sub = (k.children || []).slice(0, SHOW);
      sub.forEach((g, j) => {
        const gy = y + NH + GY + j * (SH + GY);
        nodes.push({ n: g, x: x + 16, y: gy, small: true });
        edges.push(`M${x + 8},${y + NH} V${gy + SH / 2} H${x + 16}`);
        bottom = Math.max(bottom, gy + SH);
      });
      const more = (k.children || []).length - sub.length + (k.more || 0);
      if (more > 0) { const my = y + NH + GY + sub.length * (SH + GY); nodes.push({ more, x: x + 16, y: my, parent: k.id }); bottom = Math.max(bottom, my + 20); }
    });
    y = bottom + LV;
  }
  if (kids.length) edges.push(`M${rx + NW / 2},${NH} V${lastBus}`);
  const height = Math.max(...nodes.map((p) => p.y + (p.small ? SH : p.more ? 20 : NH)), NH);
  return { nodes, edges, width, height };
}
function nodeSvg(p) {
  if (p.more) return `<g class="cn more-n" data-unit="${attr(p.parent)}" transform="translate(${p.x},${p.y})"><text x="0" y="16">${p.more} more</text></g>`;
  const n = p.n, h = p.small ? NH - 14 : NH;
  const lead = n.leader ? `${n.leader.rank ? n.leader.rank + " " : ""}${n.leader.name}` : n.kind === "root" ? "" : "No lead identified";
  const cls = ["cn", p.root ? "is-root" : "", personOrg && n.id && (personOrg === n.id || personOrg.startsWith(n.id + "/")) && !p.root ? "has-person" : "", personOrg && personOrg === n.id && !p.root ? "person-here" : ""].join(" ");
  const label = n.kind === "root" ? "All units" : n.name;
  return `<g class="${cls}" data-unit="${attr(n.kind === "root" ? "" : n.id)}" transform="translate(${p.x},${p.y})" tabindex="0" role="button" aria-label="${attr(label)}">
    <rect class="box" width="${NW - (p.small ? 16 : 0)}" height="${h}"/>
    <text class="t1" x="12" y="${p.small ? 20 : 24}">${esc(trunc(label, p.small ? 22 : 24))}</text>
    ${lead ? `<text class="t2" x="12" y="${p.small ? 38 : 44}">${esc(trunc(lead, p.small ? 26 : 28))}</text>` : ""}
    <text class="t3" x="${NW - (p.small ? 16 : 0) - 12}" y="${p.small ? 20 : 24}" text-anchor="end">${fmt(n.people)}</text>
    ${!p.small && n.kids ? `<text class="t4" x="12" y="${NH - 8}">${n.kids} sub-unit${n.kids === 1 ? "" : "s"}</text>` : ""}
  </g>`;
}
const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
let lastLayout = null;
function drawChart(refit) {
  if (!tree) return;
  const svg = $("#chart", root);
  if (!svg) return;
  lastLayout = layout();
  svg.innerHTML = `<g class="vp">${lastLayout.edges.map((d) => `<path class="edge" d="${d}"/>`).join("")}${lastLayout.nodes.map(nodeSvg).join("")}</g>`;
  if (refit) fit(); else apply();
}
function apply() {
  $("#chart", root)?.querySelector(".vp")?.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
}
function fit() {
  const svg = $("#chart", root);
  if (!svg || !lastLayout) return;
  const W = svg.clientWidth || 800, H = svg.clientHeight || 500, pad = 32;
  view.k = Math.max(0.8, Math.min(1.1, (W - pad * 2) / lastLayout.width, (H - pad * 2) / lastLayout.height));   // stay readable; pan for the rest
  view.x = Math.max(pad, (W - lastLayout.width * view.k) / 2);
  view.y = pad;
  apply();
}
function centerOn(p) {
  const svg = $("#chart", root);
  const W = svg.clientWidth, H = svg.clientHeight;
  const px = (p.x + NW / 2) * view.k + view.x, py = (p.y + NH / 2) * view.k + view.y;
  if (px > 40 && px < W - 40 && py > 40 && py < H - 40) return;   // already in view
  view.x = W / 2 - (p.x + NW / 2) * view.k;
  view.y = H / 2 - (p.y + NH / 2) * view.k;
  apply();
}
function zoomAt(f, cx, cy) {
  const svg = $("#chart", root);
  const W = svg.clientWidth, H = svg.clientHeight;
  cx ??= W / 2; cy ??= H / 2;
  const k = Math.max(0.3, Math.min(2.5, view.k * f));
  view.x = cx - (cx - view.x) * (k / view.k);
  view.y = cy - (cy - view.y) * (k / view.k);
  view.k = k;
  apply();
}
function bindChart() {
  const svg = $("#chart", root);
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.12 : 0.89, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  svg.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; svg.classList.add("grabbing"); }
    view.x = drag.vx + dx; view.y = drag.vy + dy; apply();
  });
  svg.addEventListener("pointerup", (e) => {
    const moved = drag?.moved;
    drag = null;
    svg.classList.remove("grabbing");
    if (moved) return;
    const g = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-unit]");
    if (g) pickUnit(g.dataset.unit);
  });
  svg.addEventListener("keydown", (e) => { const g = e.target.closest("[data-unit]"); if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pickUnit(g.dataset.unit); } });
}

/* ---------------------------------------------------------------- people strip */
async function loadStrip() {
  const my = ++reqStrip;
  const host = $("#strip", root);
  // top level: your starred and recently opened people; inside a unit: its people
  const mine = [...new Set([...settings.starred.map((s) => s.key), ...settings.recent.map((s) => s.key)])];
  const q = u ? `org:"${u}${stripScope === "direct" ? "!" : ""}" kind:person` : mine.length ? `key:${mine.join(",")}` : "is:leader kind:person";
  const res = await api("/api/search", { q, sort: u || !mine.length ? "seniority" : "", limit: 60 }).catch(() => ({ rows: [], total: 0 }));
  if (my !== reqStrip) return;
  const title = u ? esc(u.split("/").pop()) : mine.length ? "Starred and recent" : "Leaders";
  const active = (new URLSearchParams(location.hash.split("?")[1] || "").get("d") || "").replace(/^p:/, "");
  host.innerHTML = `<div class="st-head"><button class="st-toggle" data-strip-toggle aria-expanded="${settings.stripOpen !== false}">${icon("chev")}</button>
      <b>${u ? `People in ${title}` : title}</b><span class="muted">${fmt(res.total)}</span>
      ${u ? `<span class="seg sm" role="group" aria-label="Scope"><button data-scope="direct" class="${stripScope === "direct" ? "on" : ""}">This office</button><button data-scope="all" class="${stripScope === "all" ? "on" : ""}">Everyone under</button></span>` : ""}
      <span class="sp"></span>
      <button class="btn sm quiet" data-strip-email>Email list</button><a class="btn sm quiet" href="#/dir?q=${encodeURIComponent(q)}">Open as list</a></div>
    <div class="tiles">${res.rows.map((p) => tile(p, active)).join("") || `<p class="note" style="padding:8px 4px">No one is assigned directly; try Everyone under.</p>`}</div>`;
  host._q = q;
}
function tile(p, active) {
  return `<button class="tile${p.key === active ? " active" : ""}" data-k="${attr(p.key)}" data-p="${attr(p.key)}">
    <span class="tn">${esc(p.name)}${p.rank ? ` <span class="rk">${esc(p.rank)}</span>` : ""}${isStarred(p.key) ? ` ${icon("starf", "tiny")}` : ""}</span>
    <span class="tt">${esc(p.title || "")}</span>
    <span class="tm">${esc(shortOrg(p.org_id).a)}${p.loc_name ? `, ${esc(p.loc_name)}` : ""} ${ltHtml(p.tz)}</span></button>`;
}
function onStripClick(e) {
  if (e.target.closest("[data-strip-toggle]")) {
    const open = settings.stripOpen === false;
    save({ stripOpen: open });
    ws.classList.toggle("strip-closed", !open);
    e.target.closest("[data-strip-toggle]").setAttribute("aria-expanded", open);
    return requestAnimationFrame(fit);
  }
  const sc = e.target.closest("[data-scope]");
  if (sc) { stripScope = sc.dataset.scope; return loadStrip(); }
  if (e.target.closest("[data-strip-email]")) openEmailBuilder({ q: $("#strip", root)._q, label: u ? `people in ${u}` : "leaders" });
}
