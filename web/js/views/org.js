/* Organization: lazy unit tree, overview, line-and-block chart, people. */
import { $, esc, attr, debounce, fmt, plainName, dirName, icon, FN_CODE, info } from "../ui.js";
import { api, state, settings, save } from "../store.js";
import { ltHtml } from "../time.js";
import { go, setParams } from "../app.js";
import { openEmailBuilder } from "../email.js";

let root, orgId = "", tab = "overview", expanded = new Set(), treeCache = new Map(), chart = null;
const CAT = [["mil", "Military"], ["civ", "Civilian"], ["ctr", "Contractor"], ["foreign", "Partner nation"], ["", "Unknown"]];

export default {
  id: "org", label: "Organization", key: "o",
  async mount(el, r) {
    root = el;
    orgId = r.arg || "";
    tab = r.params.get("tab") || "overview";
    el.innerHTML = `<div class="orgv">
      <aside class="tree"><div class="tree-head"><input class="input" id="tq" data-filter-input placeholder="Find a unit or office symbol" autocomplete="off"></div><div class="tree-body" id="tbody"></div></aside>
      <section class="orgmain" id="omain"></section></div>`;
    $("#tq", el).addEventListener("input", debounce((e) => renderTree(e.target.value.trim()), 180));
    $("#tbody", el).addEventListener("click", onTreeClick);
    if (orgId) orgId.split("/").forEach((_, i, a) => i < a.length - 1 && expanded.add(a.slice(0, i + 1).join("/")));
    window.addEventListener("orgx:data", reset);
    await renderTree("");
    renderMain();
  },
  update(r) {
    const t = r.params.get("tab") || "overview";
    if (t !== tab) { tab = t; renderMain(); }
  },
  unmount() { chart?.destroy(); chart = null; window.removeEventListener("orgx:data", reset); },
};
function reset() { treeCache.clear(); renderTree(""); renderMain(); }

/* ---------------------------------------------------------------- tree */
async function children(pid) {
  if (!treeCache.has(pid)) treeCache.set(pid, await api("/api/orgs", { parent: pid || "" }));
  return treeCache.get(pid);
}
async function renderTree(filter) {
  const host = $("#tbody", root);
  if (filter) {
    const rows = await api("/api/orgs", { q: filter });
    host.innerHTML = rows.map((o) => node(o, 0, false, true)).join("") || `<div class="empty">No unit or office matches “${esc(filter)}”.</div>`;
    return;
  }
  const html = [];
  const walk = async (pid, depth) => {
    for (const o of await children(pid)) {
      const open = expanded.has(o.id);
      html.push(node(o, depth, open));
      if (open && o.kids) await walk(o.id, depth + 1);
    }
  };
  await walk("", 0);
  host.innerHTML = html.join("");
  host.querySelector(".tn.on")?.scrollIntoView({ block: "nearest" });
}
function node(o, depth, open, full = false) {
  return `<div class="tn${o.id === orgId ? " on" : ""}" data-id="${attr(o.id)}" style="padding-left:${depth * 14}px" title="${attr(o.id)}">
    <span class="tw" ${o.kids ? "data-tw" : ""}>${o.kids ? (open ? "−" : "+") : ""}</span>
    <span class="ellip">${esc(full || (depth === 0 && !o.parent) ? o.id : o.name)}</span><span class="n">${fmt(o.people)}</span></div>`;
}
async function onTreeClick(e) {
  const n = e.target.closest(".tn");
  if (!n) return;
  const id = n.dataset.id;
  if (e.target.closest("[data-tw]")) {
    expanded.has(id) ? expanded.delete(id) : expanded.add(id);
    return renderTree($("#tq", root).value.trim());
  }
  expanded.add(id);
  go("org", id, { tab }, { keepDrawer: false });
}

/* ---------------------------------------------------------------- main */
async function renderMain() {
  const host = $("#omain", root);
  chart?.destroy();
  chart = null;
  if (!orgId) return renderTop(host);
  host.innerHTML = `<div class="loading">Loading ${esc(orgId)}…</div>`;
  const o = await api("/api/org", { id: orgId });
  if (o.error) {
    host.innerHTML = `<div class="empty"><b>${esc(orgId)} is not in the current snapshot</b>It may have been renamed or merged. Search for it in the tree on the left.</div>`;
    return;
  }
  const isHome = settings.homeOrg === o.id;
  host.innerHTML = `<div class="org-hero">
      ${o.chain.length ? `<div class="path">${o.chain.map((c) => `<a data-nav-org="${attr(c.id)}">${esc(c.name)}</a><span class="sep">›</span>`).join("")}${esc(o.name)}</div>` : ""}
      <h1><span>${esc(o.id)}</span>${o.fn ? `<span class="flag plain">${esc(state.fnLabel[o.fn] || o.fn)}</span>` : ""}
        ${o.inferred ? `<span class="flag caution">Parent inferred ${info(`Active Directory doesn't state this unit's parent; it was inferred from ${o.inferred}.`)}</span>` : ""}</h1>
      <p class="factline"><b>${fmt(o.people)}</b> people, <b>${fmt(o.children.length)}</b> sub-offices, <b>${o.by_loc.length}</b> base${o.by_loc.length === 1 ? "" : "s"}</p>
    </div>
    <div class="subnav">${[["overview", "Overview"], ["chart", "Chart"], ["people", "People"]].map(([id, l]) => `<button data-tab="${id}" class="${tab === id ? "on" : ""}">${l}</button>`).join("")}
      <span class="r"><button class="btn link" data-home>${isHome ? "Unset as my unit" : "Set as my unit"}</button><button class="btn sm" data-email>Email list</button>
        <a class="btn sm" href="#/print?q=${encodeURIComponent(`org:"${o.id}"`)}">Print roster</a><button class="btn sm" data-q='org:"${attr(o.id)}"'>Open in directory</button></span></div>
    <div class="org-body" id="obody"></div>`;
  host.querySelector(".subnav").addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (t) setParams({ tab: t.dataset.tab });
    if (e.target.closest("[data-home]")) {
      save({ homeOrg: isHome ? "" : o.id, homeLoc: isHome ? settings.homeLoc : o.loc_id || settings.homeLoc });
      renderMain();
    }
    if (e.target.closest("[data-email]")) openEmailBuilder({ q: `org:"${o.id}"`, label: `everyone in ${o.id}` });
  });
  host.querySelector(".org-hero").addEventListener("click", (e) => {
    const a = e.target.closest("[data-nav-org]");
    if (a) go("org", a.dataset.navOrg, { tab }, { keepDrawer: false });
  });
  const body = $("#obody", host);
  if (tab === "chart") return renderChart(body, o.id);
  if (tab === "people") return renderPeople(body, o);
  renderOverview(body, o);
}

function renderTop(host) {
  host.innerHTML = `<div class="page"><div class="page-title"><h1>Organization</h1></div>
    <div id="tops"><div class="loading">Loading units…</div></div><h2 class="h">Chart</h2><div id="topchart"></div></div>`;
  api("/api/orgtree", { depth: 1, cap: 80 }).then((t) => { $("#tops", host).innerHTML = officesTable(t.children); });
  host.addEventListener("click", (e) => { const s = e.target.closest("[data-nav]"); if (s) go("org", s.dataset.nav, {}, { keepDrawer: false }); });
  renderChart($("#topchart", host), "");
}
function officesTable(rows) {
  return `<table class="tbl"><thead><tr><th>Office</th><th>Lead</th><th class="num">Assigned</th><th class="num">Sub</th><th>Base</th><th>Parent link</th></tr></thead><tbody>
    ${rows.map((c) => {
      const lead = c.leader || (c.leader_name ? { name: c.leader_name, rank: c.leader_rank, title: c.leader_title } : null);
      return `<tr class="click" data-nav="${attr(c.id)}"><td><b>${esc(c.name)}</b></td>
        <td>${lead ? `${esc(plainName({ ...lead, kind: "person" }))}<div class="muted">${esc(lead.title || "")}</div>` : `<span class="muted">none identified</span>`}</td>
        <td class="num">${fmt(c.people)}</td><td class="num">${c.kids || ""}</td><td>${esc(c.loc_name || c.loc_id || "")}</td>
        <td>${c.inferred && c.inferred !== "office symbol" ? `<span class="flag caution">inferred: ${esc(c.inferred)}</span>` : ""}</td></tr>`;
    }).join("")}</tbody></table>`;
}
function renderOverview(body, o) {
  const tot = Object.values(o.by_cat).reduce((a, b) => a + b, 0) || 1;
  const fns = Object.entries(o.by_fn).filter(([k]) => k).sort((a, b) => b[1] - a[1]);
  const fmax = Math.max(1, ...fns.map(([, n]) => n));
  const TL = Object.fromEntries((state.meta?.tiers || []).map((t) => [t.id, t.label]));
  const tiers = Object.entries(o.by_tier).filter(([k]) => k).sort((a, b) => b[1] - a[1]);
  const tmax = Math.max(1, ...tiers.map(([, n]) => n));
  const leaders = [o.leader, ...o.leadership.filter((p) => p.key !== o.leader?.key)].filter(Boolean);
  body.innerHTML = `<div class="cols"><div>
      <h2 class="h">Leadership</h2>
      ${leaders.length ? `<table class="tbl"><tbody>${leaders.map((p) => `<tr class="click" data-p="${attr(p.key)}"><td>${esc(p.rank || "")}</td><td>${dirName({ ...p, kind: "person" })}</td><td class="dim">${esc(p.title || "")}</td><td>${p.email ? `<a href="mailto:${attr(p.email)}">email</a>` : ""}</td></tr>`).join("")}</tbody></table>`
        : `<p class="note">No one in this office has a leadership title in AD.</p>`}
      ${o.children.length ? `<h2 class="h">Sub-offices <span class="n">${o.children.length}</span></h2>${officesTable(o.children)}` : ""}
    </div><div>
      <h2 class="h">Contact the office</h2>
      ${o.orgboxes.length ? `<table class="tbl"><tbody>${o.orgboxes.map((b) => `<tr><td><a data-p="${attr(b.key)}">${esc(b.name)}</a></td><td>${b.email ? `<a href="mailto:${attr(b.email)}">${esc(b.email)}</a> <button class="btn link" data-copy="${attr(b.email)}">copy</button>` : ""}</td></tr>`).join("")}</tbody></table>`
        : `<p class="note">No org box (shared mailbox) is assigned to this office in AD.</p>`}
      ${o.groups.length ? `<h2 class="h">Distribution lists</h2><table class="tbl"><tbody>${o.groups.map((g) => `<tr class="click" data-p="${attr(g.key)}"><td>${esc(g.name)}</td><td class="num">${fmt(g.n)}</td></tr>`).join("")}</tbody></table>` : ""}
      <h2 class="h">Composition</h2>
      <div class="bars">${CAT.filter(([k]) => o.by_cat[k]).map(([k, l]) => `<span>${l}</span><span class="t"><span style="width:${(o.by_cat[k] / tot) * 100}%"></span></span><span class="r">${o.by_cat[k]}</span>`).join("")}</div>
      ${tiers.length ? `<h3 style="margin:12px 0 4px;font-size:13px">By grade</h3><div class="bars">${tiers.map(([k, n]) => `<span>${esc(TL[k] || k)}</span><span class="t"><span style="width:${(n / tmax) * 100}%"></span></span><span class="r">${n}</span>`).join("")}</div>` : ""}
      ${fns.length ? `<h3 style="margin:12px 0 4px;font-size:13px">By function</h3><div class="bars">${fns.slice(0, 8).map(([k, n]) => `<span>${esc(state.fnLabel[k] || k)}</span><span class="t"><span style="width:${(n / fmax) * 100}%"></span></span><span class="r">${n}</span>`).join("")}</div>` : ""}
      ${o.by_loc.length ? `<h2 class="h">Bases</h2><table class="tbl"><tbody>${o.by_loc.map((l) => `<tr class="click" data-loc="${attr(l.id || "")}"><td>${esc(l.name || "Unplaced")}${l.approx ? " (approx.)" : ""}</td><td>${ltHtml(l.tz)}</td><td class="num">${fmt(l.n)}</td></tr>`).join("")}</tbody></table>` : ""}
    </div></div>`;
  body.addEventListener("click", (e) => {
    const s = e.target.closest("[data-nav]");
    if (s) go("org", s.dataset.nav, { tab: "overview" }, { keepDrawer: false });
  });
}
function renderPeople(body, o) {
  body.innerHTML = `<p class="factline"><b>${fmt(o.members.length)}</b> assigned directly to ${esc(o.id)}${o.people > o.members.length ? `; <a data-q='org:"${attr(o.id)}"'>all ${fmt(o.people)} including sub-offices</a>` : ""}.</p>
    <table class="tbl"><thead><tr><th>Rank</th><th>Name</th><th>Title</th><th>Base, local time</th><th>DSN</th><th>Commercial</th><th>Email</th></tr></thead><tbody>
    ${o.members.map((r) => `<tr class="click" data-p="${attr(r.key)}"><td>${esc(r.kind === "person" ? r.rank || "" : "")}</td><td>${dirName(r)}</td><td class="dim">${esc(r.title || "")}</td>
      <td>${esc(r.loc_name || "")} ${ltHtml(r.tz)}</td><td class="ph">${esc(r.dsn || "")}</td><td class="ph">${esc(r.phone || "")}</td><td>${esc(r.email || "")}</td></tr>`).join("")}
    </tbody></table>`;
}

/* ---------------------------------------------------------------- line-and-block chart */
const NW = 210, NH = 58, GX = 56, GY = 12;
async function renderChart(host, rootId) {
  host.innerHTML = `<div class="chart-wrap"><div class="zoomctl"><button class="btn sm icon" data-z="in" title="Zoom in">${icon("plus")}</button><button class="btn sm icon" data-z="out" title="Zoom out">${icon("minus")}</button><button class="btn sm icon" data-z="fit" title="Fit">${icon("fit")}</button></div><svg class="chart-svg"></svg></div>
    <p class="note">Solid lines come from Active Directory, dashed lines are inferred ${info("Inferred from Manager links or unit numbering. Click a block to open it, click + at its edge to expand, drag to pan, scroll to zoom.")}</p>`;
  const data = await api("/api/orgtree", { root: rootId, depth: rootId ? 2 : 1, cap: 60 });
  if (!data.error) chart = makeChart(host.querySelector("svg.chart-svg"), data, host.querySelector(".zoomctl"));
}
function makeChart(svg, tree, ctl) {
  const view = { x: 20, y: 20, k: 1 };
  let drag = null;
  const layout = () => {
    let y = 0;
    const walk = (n, d) => {
      n._d = d;
      const kids = n.children || [];
      if (!kids.length) { n._y = y; y += NH + GY; }
      else { kids.forEach((k) => walk(k, d + 1)); n._y = kids[0]._y; }   // parent level with its first child keeps the root in view on tall charts
      n._x = d * (NW + GX);
    };
    walk(tree, 0);
    return y;
  };
  const draw = () => {
    layout();
    let edges = "", nodes = "";
    const visit = (n) => {
      for (const k of n.children || []) {
        // orthogonal connectors, as on a wire diagram
        const x1 = n._x + NW, y1 = n._y + NH / 2, x2 = k._x, y2 = k._y + NH / 2, mx = x1 + GX / 2;
        edges += `<path class="edge${k.inferred && k.inferred !== "office symbol" ? " inf" : ""}" d="M${x1},${y1} H${mx} V${y2} H${x2}"><title>${k.inferred ? "inferred from " + esc(k.inferred) : "stated in AD"}</title></path>`;
        visit(k);
      }
      const lead = n.leader ? plainName({ ...n.leader, kind: "person" }) : n.kind === "root" ? `${fmt(n.people)} assigned` : "no lead identified";
      const more = n.kids > (n.children?.length || 0);
      nodes += `<g class="cn" data-id="${attr(n.id)}" transform="translate(${n._x},${n._y})"><rect class="box" width="${NW}" height="${NH}"/>
        <text x="8" y="18">${esc(trunc(n.name, 26))}</text><text class="l2" x="8" y="34">${esc(trunc(lead, 31))}</text>
        <text class="l3" x="8" y="49">${n.kind === "root" ? "" : `${fmt(n.people)} assigned${n.kids ? `, ${n.kids} sub` : ""}`}</text>
        ${more ? `<g data-expand="${attr(n.id)}" style="cursor:pointer"><rect x="${NW - 1}" y="${NH / 2 - 9}" width="18" height="18" fill="var(--surface)" stroke="var(--ink)"/><text class="more" x="${NW + 8}" y="${NH / 2 + 4}" text-anchor="middle">+</text></g>` : ""}
        ${n.more ? `<text class="l3" x="${NW + 24}" y="${NH + 6}">${n.more} more not shown</text>` : ""}</g>`;
    };
    visit(tree);
    svg.innerHTML = `<g class="vp" transform="translate(${view.x},${view.y}) scale(${view.k})">${edges}${nodes}</g>`;
  };
  const apply = () => svg.querySelector(".vp")?.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  const fit = () => {
    const h = layout();
    let maxD = 0;
    const md = (n) => { maxD = Math.max(maxD, n._d); (n.children || []).forEach(md); };
    md(tree);
    const W = svg.clientWidth || 900, H = svg.clientHeight || 500, w = (maxD + 1) * (NW + GX);
    view.k = Math.max(0.9, Math.min(1, W / (w + 40), H / (h + 40)));   // stay readable; pan for the rest
    view.x = 20;
    view.y = 10;
    draw();
  };
  const find = (id, n = tree) => (n.id === id ? n : (n.children || []).reduce((f, k) => f || find(id, k), null));
  svg.addEventListener("click", async (e) => {
    if (drag?.moved) return;
    const ex = e.target.closest("[data-expand]");
    if (ex) {
      e.stopPropagation();
      const n = find(ex.dataset.expand);
      const sub = await api("/api/orgtree", { root: n.id, depth: 1, cap: 60 });
      n.children = sub.children;
      n.more = sub.more;
      return draw();
    }
    const g = e.target.closest(".cn");
    if (g?.dataset.id) go("org", g.dataset.id, { tab: "chart" }, { keepDrawer: false });
  });
  svg.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; svg.classList.add("grabbing"); });
  const move = (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    view.x = drag.vx + dx;
    view.y = drag.vy + dy;
    apply();
  };
  const up = () => { svg.classList.remove("grabbing"); setTimeout(() => (drag = null), 0); };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  const zoom = (f, cx = svg.clientWidth / 2, cy = svg.clientHeight / 2) => {
    const k = Math.max(0.2, Math.min(2.5, view.k * f));
    view.x = cx - ((cx - view.x) * k) / view.k;
    view.y = cy - ((cy - view.y) * k) / view.k;
    view.k = k;
    apply();
  };
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  ctl.addEventListener("click", (e) => {
    const z = e.target.closest("[data-z]")?.dataset.z;
    if (z === "in") zoom(1.2);
    if (z === "out") zoom(1 / 1.2);
    if (z === "fit") fit();
  });
  fit();
  return { destroy() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); } };
}
const trunc = (s, n) => (String(s || "").length > n ? String(s).slice(0, n - 1) + "…" : String(s || ""));
