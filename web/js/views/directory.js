/* Find: the main screen. Search as you type, the top match's card opens beside the results,
   arrows move through them. Questions ("who handles SATCOM at Alder?") are answered in place.
   A table mode keeps the dense roster for bulk work. */
import { $, esc, attr, kindShort, shortOrg, debounce, fmt, copy, say, modal, tokens, toggleToken, hasToken, setToken, removeTokenAt, download, icon, menu, info, plainName } from "../ui.js";
import { api, post, apiUrl, state, settings, isStarred, toggleStar } from "../store.js";
import { ltHtml } from "../time.js";
import { setParams, openDrawer } from "../app.js";
import { addToGroup } from "../detail.js";
import { openEmailBuilder } from "../email.js";

const ROW_LIST = 64, ROW_TABLE = 36, PAGE = 150;
const TYPES = [["", "All"], ["person", "People"], ["orgbox", "Org boxes"], ["group", "DLs"], ["resource", "Rooms"]];
const SORTS = [["", "Best match"], ["name", "Name"], ["smart", "Office"], ["seniority", "Grade"], ["location", "Base"], ["title", "Title"]];
const FLAGS = [["is", "new", "New since last update"], ["is", "moved", "Moved"], ["is", "promoted", "Promoted"], ["is", "leader", "Leaders"], ["has", "notes", "Has team notes"], ["missing", "email", "No email"], ["missing", "phone", "No phone"], ["is", "approx", "Approximate base"]];
const QUESTION = /^(who|whom|where|which|poc|need|contact|is there)\b|\?$|\bpoc\b/i;

let root, find, q = "", sort = "", mode = "list", total = 0, pages = new Map(), sel = new Set(), lastIdx = null, reqId = 0;
let scroller, space, activeKey = "", userPicked = false, askData = null, lastFacets = null, homeRows = null;

const rowH = () => (mode === "table" ? ROW_TABLE : ROW_LIST);
const textPart = (s) => tokens(s).filter((t) => !t.field && !t.neg).map((t) => t.raw).join(" ");
const filterPart = (s) => tokens(s).filter((t) => t.field || t.neg).map((t) => t.raw).join(" ");

export default {
  id: "dir", label: "Find", key: "f",
  mount(el, r) {
    root = el;
    q = r.params.get("q") || "";
    sort = r.params.get("sort") || "";
    mode = r.params.get("view") === "table" ? "table" : "list";
    sel = new Set();
    activeKey = (r.params.get("d") || "").replace(/^p:/, "");
    el.innerHTML = `<div class="find" id="find">
      <section class="find-main">
        <div class="find-top">
          <div class="bigsearch">${icon("search")}
            <input id="fq" type="search" data-filter-input spellcheck="false" autocomplete="off" aria-label="Search the directory"
              placeholder="Name, office, email or phone, or ask who handles something" value="${attr(textPart(q))}"><kbd>Ctrl K</kbd></div>
          <div class="fbar" id="fbar"></div>
        </div>
        <div class="rhead" id="rhead"></div>
        <div class="rlist" id="rlist"><div class="vspace" id="vspace"></div></div>
        <div class="bulkbar hidden" id="bulk"></div>
      </section></div>`;
    find = $("#find", el);
    find.appendChild($("#drawer"));            // the card docks beside the results on this screen
    scroller = $("#rlist", el);
    space = $("#vspace", el);
    const input = $("#fq", el);
    input.addEventListener("input", debounce(() => setQ(joinQ(input.value), { typing: true }), 160));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); move(e.key === "ArrowDown" ? 1 : -1); }
      if (e.key === "Enter") { e.preventDefault(); normalizeInput(); }
    });
    scroller.addEventListener("scroll", () => requestAnimationFrame(paint));
    window.addEventListener("resize", paintSoon);
    scroller.addEventListener("click", onRowClick);
    $("#fbar", el).addEventListener("click", onBarClick);
    $("#fbar", el).addEventListener("change", onBarChange);
    document.addEventListener("keydown", onKeys);
    window.addEventListener("orgx:data", reload);
    syncCard(r);
    reload();
    setTimeout(() => input.focus(), 0);
  },
  update(r) {
    syncCard(r);
    const d = r.params.get("d") || "";
    if (d.startsWith("p:")) activeKey = d.slice(2);
    const nq = r.params.get("q") || "", ns = r.params.get("sort") || "", nm = r.params.get("view") === "table" ? "table" : "list";
    if (nq !== q || ns !== sort || nm !== mode) {
      q = nq; sort = ns; mode = nm;
      const input = $("#fq", root);
      if (textPart(q) !== input.value.trim()) input.value = textPart(q);   // came from a link or the address bar, not typing
      reload();
    } else paint();
  },
  unmount() {
    document.body.appendChild($("#drawer"));
    window.removeEventListener("resize", paintSoon);
    window.removeEventListener("orgx:data", reload);
    document.removeEventListener("keydown", onKeys);
  },
};

function syncCard(r) {
  find?.classList.toggle("has-card", !!r.params.get("d"));
}
const paintSoon = debounce(() => paint(), 60);
const joinQ = (text) => [filterPart(q), text.trim()].filter(Boolean).join(" ");
function setQ(v, { typing = false } = {}) {
  q = v.trim();
  if (!typing) userPicked = false;
  setParams({ q });
  reload();
}
function normalizeInput() {
  const input = $("#fq", root);
  const full = joinQ(input.value);
  input.value = textPart(full);       // typed filters such as base:Alder become chips
  setQ(full);
}
const hasFilters = () => !!q.trim();

/* ---------------------------------------------------------------- load */
async function reload() {
  const my = ++reqId;
  pages = new Map();
  total = 0;
  askData = null;
  scroller.scrollTop = 0;
  sel.clear();
  renderBulk();
  const text = textPart(q);
  const facetsP = api("/api/facets", { q }).catch(() => null);
  if (!hasFilters() && sort === "" && (await homeAvailable())) {
    if (my !== reqId) return;
    renderHome();
  } else if (QUESTION.test(text)) {
    renderHead({ question: true });
    space.style.height = "auto";
    space.innerHTML = `<div class="loading">Looking for who handles that…</div>`;
    const a = await api("/api/ask", { q: text, home_org: settings.homeOrg, home_loc: settings.homeLoc }).catch(() => null);
    if (my !== reqId) return;
    askData = a;
    renderAnswer(a);
  } else {
    space.style.height = "0px";
    space.innerHTML = "";
    try {
      const first = await api("/api/search", { q, sort, limit: PAGE, offset: 0 });
      if (my !== reqId) return;
      total = first.total;
      pages.set(0, first.rows);
      renderHead({ res: first });
      paint();
      autoPick(first.rows[0]);
    } catch (e) {
      space.innerHTML = `<div class="empty"><b>The search failed</b>${esc(e.message)}</div>`;
    }
  }
  const f = await facetsP;
  if (my === reqId && f) renderBar(f);
}
function autoPick(row) {
  // as you type, the best match's card opens; once you choose a row yourself, that choice stays
  if (!row || userPicked || mode === "table" || !textPart(q) || !matchMedia("(min-width: 1081px)").matches) return;   // only when the card sits beside the list
  if (activeKey === row.key && new URLSearchParams(location.hash.split("?")[1]).get("d") === "p:" + row.key) return;
  activeKey = row.key;
  setParams({ d: "p:" + row.key });
}
async function ensurePage(p) {
  if (pages.has(p)) return;
  pages.set(p, "loading");
  const my = reqId;
  const res = await api("/api/search", { q, sort, limit: PAGE, offset: p * PAGE }).catch(() => null);
  if (my !== reqId) return;
  pages.set(p, res ? res.rows : []);
  paint();
}
function rowAt(i) {
  const pg = pages.get(Math.floor(i / PAGE));
  return Array.isArray(pg) ? pg[i % PAGE] : null;
}

/* ---------------------------------------------------------------- home: starred, recent, your office */
async function homeAvailable() {
  const keys = [...new Set([...settings.starred.map((s) => s.key), ...settings.recent.map((s) => s.key)])];
  if (!keys.length && !settings.homeOrg) return false;
  const [known, office] = await Promise.all([
    keys.length ? api("/api/search", { q: `key:${keys.join(",")}`, limit: 60 }).catch(() => ({ rows: [] })) : { rows: [] },
    settings.homeOrg ? api("/api/search", { q: `org:"${settings.homeOrg}!" kind:person`, sort: "seniority", limit: 12 }).catch(() => ({ rows: [], total: 0 })) : { rows: [], total: 0 },
  ]);
  const byKey = new Map(known.rows.map((r) => [r.key, r]));
  homeRows = {
    starred: settings.starred.map((s) => byKey.get(s.key)).filter(Boolean),
    recent: settings.recent.map((s) => byKey.get(s.key)).filter((r) => r && !isStarred(r.key)).slice(0, 8),
    office: office.rows, officeTotal: office.total,
  };
  return homeRows.starred.length || homeRows.recent.length || homeRows.office.length;
}
function renderHome() {
  const people = state.meta?.counts?.person || 0;
  $("#rhead", root).innerHTML = `<span class="count"><b>${fmt(people)}</b> people in the directory</span><span class="sp"></span>
    <button class="btn sm" data-browse>Browse everyone</button>`;
  $("#rhead", root).onclick = (e) => { if (e.target.closest("[data-browse]")) { sort = "name"; setParams({ sort: "name", q: "kind:person" }); } };
  const list = (rows) => rows.map((r) => resHtml(r, -1)).join("");
  const h = homeRows;
  space.style.height = "auto";
  space.innerHTML = `<div class="home">
    ${h.starred.length ? `<h3>Starred <span class="n muted">${h.starred.length}</span></h3>${list(h.starred)}` : ""}
    ${h.recent.length ? `<h3>Recently opened</h3>${list(h.recent)}` : ""}
    ${h.office.length ? `<h3>${esc(settings.homeOrg)} <span class="n muted">${fmt(h.officeTotal)}</span><span class="r"><a data-q='org:"${attr(settings.homeOrg)}!"'>Everyone in the office</a></span></h3>${list(h.office)}` : ""}
  </div>`;
}

/* ---------------------------------------------------------------- question answers */
function renderAnswer(a) {
  if (!a || (!a.people.length && !a.shops.length)) {
    space.innerHTML = `<div class="empty"><b>No clear answer for “${esc(textPart(q))}”</b>When you find who owns it, add the topic under Go-to for on their card; the next person who asks gets that answer.</div>`;
    return;
  }
  const basis = [a.topics.length ? a.topics.map((t) => t.label).join(", ") : "", a.places?.length ? `at ${a.places.join(", ")}` : "", a.units?.length ? `in ${a.units.join(", ")}` : ""].filter(Boolean).join(" ");
  let h = `<div class="answer">`;
  if (a.shops.length) {
    h += `<h3>Offices that handle ${esc(basis || "this")}${a.taught ? `<span class="r note">${a.taught} answer${a.taught > 1 ? "s" : ""} taught by your team</span>` : ""}</h3><div class="shops">`;
    for (const s of a.shops.slice(0, 6)) {
      const top = s.top[0] || s.leader;
      h += `<div class="shop" data-org="${attr(s.id)}"><div class="sid">${esc(s.id)}</div>
        ${top ? `<div class="who ellip">${esc(plainName({ ...top, kind: "person" }))}, ${esc(top.title || "")}</div>` : ""}
        <div class="box ellip">${s.orgbox?.email ? `<a href="mailto:${attr(s.orgbox.email)}">${esc(s.orgbox.email)}</a>` : `<span class="muted">No office mailbox</span>`}${s.loc ? ` <span class="muted">${esc(s.loc)}</span>` : ""}</div></div>`;
    }
    h += `</div>`;
  }
  h += `</div>`;
  if (a.people.length) {
    h += `<div class="answer"><h3>People</h3></div><div class="home" style="padding-top:0">${a.people.slice(0, 20).map((p) => resHtml({ ...p, kind: "person", loc_name: p.loc }, -1, p.why)).join("")}</div>`;
  }
  space.innerHTML = h;
  total = 0;
  autoPick(a.people[0]);
}

/* ---------------------------------------------------------------- rows */
function paint() {
  if (!scroller || askData || (!hasFilters() && homeRows && space.querySelector(".home"))) return;
  const H = rowH();
  space.style.height = `${total * H}px`;
  if (!total) {
    space.style.height = "auto";
    space.innerHTML = `<div class="empty"><b>No one matches “${esc(textPart(q) || q)}”</b>${tokens(q).some((t) => t.field) ? "Remove a filter to widen the search." : "Check the spelling, or search by office symbol, base or email."}</div>`;
    return;
  }
  const top = scroller.scrollTop, h = scroller.clientHeight || 600;
  const a = Math.max(0, Math.floor(top / H) - 6), b = Math.min(total - 1, Math.ceil((top + h) / H) + 6);
  for (let p = Math.floor(a / PAGE); p <= Math.floor(b / PAGE); p++) ensurePage(p);
  let html = "";
  for (let i = a; i <= b; i++) {
    const r = rowAt(i);
    if (mode === "table") html += r ? tableRow(r, i) : `<div class="row ph-row" style="top:${i * H}px"><span></span><div class="bone"></div></div>`;
    else html += r ? resHtml(r, i) : `<div class="res bone" style="top:${i * H}px"><span></span><div><div class="l1"></div></div></div>`;
  }
  space.innerHTML = html;
}
function officeShort(id) {
  const o = shortOrg(id);
  return o.b ? `${o.b.split("/").pop()}/${o.a}` : o.a;
}
function resHtml(r, i, why = null) {
  const person = r.kind === "person";
  const star = isStarred(r.key);
  const pos = i >= 0 ? ` style="top:${i * ROW_LIST}px"` : "";
  return `<div class="res${r.key === activeKey ? " active" : ""}${sel.has(r.key) ? " picked" : ""}"${pos} data-k="${attr(r.key)}" data-i="${i}" data-email="${attr(r.email || "")}">
    <input type="checkbox" class="ck" data-ck ${sel.has(r.key) ? "checked" : ""} aria-label="Select ${attr(r.name)}">
    <div><div class="l1"><span class="nm">${esc(r.name)}</span>${person && r.rank ? `<span class="rk">${esc(r.rank)}</span>` : ""}${!person ? `<span class="kind">${esc(kindShort(r.kind))}</span>` : ""}${r.disabled ? `<span class="dis">disabled</span>` : ""}</div>
      <div class="l2">${why ? `Matched on ${esc(why.join("; "))}` : esc(r.title || r.email || "")}</div></div>
    <div><div class="l1">${esc(officeShort(r.org_id))}</div><div class="l2">${esc(r.loc_name || "")}${r.loc_approx ? " (approx.)" : ""}</div></div>
    <div class="c3"><div class="l1">${ltHtml(r.tz)}</div><div class="l2 ph">${esc(r.dsn ? `DSN ${r.dsn}` : r.phone || r.mobile || "")}</div></div>
    <div class="acts">${r.email ? `<button class="btn" data-copyemail title="Copy email address" aria-label="Copy email address">${icon("copy")}</button>` : ""}<button class="btn${star ? " is-on" : ""}" data-star title="${star ? "Unstar" : "Star"}" aria-label="${star ? "Unstar" : "Star"}">${icon(star ? "starf" : "star")}</button></div>
  </div>`;
}
function tableRow(r, i) {
  const on = sel.has(r.key);
  return `<div class="row${on ? " sel" : ""}${r.key === activeKey ? " active" : ""}" style="top:${i * ROW_TABLE}px" data-k="${attr(r.key)}" data-i="${i}" data-email="${attr(r.email || "")}">
    <input type="checkbox" data-ck ${on ? "checked" : ""} aria-label="Select">
    <div><b>${esc(r.name)}</b>${r.kind !== "person" ? ` <span class="muted">${esc(kindShort(r.kind))}</span>` : ""}</div>
    <div>${esc(r.kind === "person" ? r.rank || "" : "")}</div>
    <div class="c-title dim" title="${attr(r.title || "")}">${esc(r.title || "")}</div>
    <div class="c-org" title="${attr(r.org_id || "")}">${esc(officeShort(r.org_id))}</div>
    <div class="c-loc">${esc(r.loc_name || "")} ${ltHtml(r.tz)}</div>
    <div class="c-dsn ph">${esc(r.dsn || "")}</div>
    <div class="c-comm ph">${esc(r.phone || r.mobile || "")}</div>
    <div class="c-email">${esc(r.email || "")}</div>
  </div>`;
}
function onRowClick(e) {
  if (e.target.closest("a")) return;
  const row = e.target.closest("[data-k]");
  if (!row) return;
  const i = +row.dataset.i, key = row.dataset.k;
  if (e.target.closest("[data-copyemail]")) { e.stopPropagation(); return copy(row.dataset.email, `Copied ${row.dataset.email}`); }
  if (e.target.closest("[data-star]")) {
    e.stopPropagation();
    const r = i >= 0 ? rowAt(i) : { key, name: row.querySelector(".nm")?.textContent || key, kind: "person" };
    toggleStar(r);
    return i >= 0 ? paint() : row.querySelector("[data-star]").outerHTML = `<button class="btn${isStarred(key) ? " is-on" : ""}" data-star>${icon(isStarred(key) ? "starf" : "star")}</button>`;
  }
  if (e.target.closest("[data-ck]") || e.shiftKey || e.ctrlKey || e.metaKey) {
    if (e.shiftKey && lastIdx != null && i >= 0) {
      for (let j = Math.min(lastIdx, i); j <= Math.max(lastIdx, i); j++) { const x = rowAt(j); if (x) sel.add(x.key); }
    } else sel.has(key) ? sel.delete(key) : sel.add(key);
    lastIdx = i;
    renderBulk();
    row.classList.toggle("picked", sel.has(key));
    row.classList.toggle("sel", sel.has(key));
    const ck = row.querySelector("[data-ck]");
    if (ck) ck.checked = sel.has(key);
    return;
  }
  pick(key);
}
function pick(key) {
  userPicked = true;
  activeKey = key;
  root.querySelectorAll("[data-k].active").forEach((x) => x.classList.remove("active"));
  root.querySelector(`[data-k="${CSS.escape(key)}"]`)?.classList.add("active");
  openDrawer("p:" + key);
}
function visibleKeys() {
  return [...root.querySelectorAll("#rlist [data-k]")].map((x) => x.dataset.k);
}
function move(d) {
  if (!askData && total && !space.querySelector(".home")) {
    let i = -1;
    for (let j = 0; j < total; j++) { const r = rowAt(j); if (r && r.key === activeKey) { i = j; break; } }
    const n = Math.max(0, Math.min(total - 1, i + d));
    const r = rowAt(n);
    if (!r) return;
    const H = rowH(), y = n * H;
    if (y < scroller.scrollTop || y > scroller.scrollTop + scroller.clientHeight - H) scroller.scrollTop = y - scroller.clientHeight / 2;
    return pick(r.key);
  }
  const keys = visibleKeys();
  if (!keys.length) return;
  const i = keys.indexOf(activeKey);
  pick(keys[Math.max(0, Math.min(keys.length - 1, i + d))]);
  root.querySelector(`[data-k="${CSS.escape(activeKey)}"]`)?.scrollIntoView({ block: "nearest" });
}
function onKeys(e) {
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.querySelector(".modal-back, .menu") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
  else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (e.key === "x" && activeKey) {
    sel.has(activeKey) ? sel.delete(activeKey) : sel.add(activeKey);
    renderBulk();
    mode === "table" || total ? paint() : null;
  } else if (e.key === "c" && activeKey) {
    const email = root.querySelector(`[data-k="${CSS.escape(activeKey)}"]`)?.dataset.email;
    if (email) copy(email, `Copied ${email}`);
  }
}

/* ---------------------------------------------------------------- results header and bulk bar */
function renderHead({ res = null, question = false } = {}) {
  const head = $("#rhead", root);
  head.classList.toggle("hidden", question);
  if (question) return;
  head.innerHTML = `<span class="count"><b>${fmt(total)}</b> result${total === 1 ? "" : "s"}</span><span class="sp"></span>
    <span class="seg" role="group" aria-label="Layout"><button data-mode="list" class="${mode === "list" ? "on" : ""}" aria-pressed="${mode === "list"}">List</button><button data-mode="table" class="${mode === "table" ? "on" : ""}" aria-pressed="${mode === "table"}">Table</button></span>
    <select class="input" id="fsort" aria-label="Sort">${SORTS.map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>Sort: ${l}</option>`).join("")}</select>
    <button class="btn sm" data-email>Email list</button>
    <button class="btn sm icon" data-more aria-label="More actions" title="More actions">${icon("more")}</button>`;
  syncTableHead();
  $("#fsort", head).onchange = (e) => { sort = e.target.value; setParams({ sort }); reload(); };
  head.onclick = (e) => {
    const m = e.target.closest("[data-mode]");
    if (m) { mode = m.dataset.mode; setParams({ view: mode === "table" ? "table" : "" }); return; }
    if (e.target.closest("[data-email]")) openEmailBuilder({ q, label: q ? `this search` : "the whole directory" });
    const more = e.target.closest("[data-more]");
    if (more) menu(more, [
      { label: "Print roster", run: () => (location.hash = `#/print?q=${encodeURIComponent(q)}`) },
      { label: "Download CSV", href: apiUrl("/api/export", { q, format: "csv" }), download: true },
      { label: "Download vCards", href: apiUrl("/api/export", { q, format: "vcf" }), download: true },
      { label: "Show on the map", run: () => (location.hash = `#/map?q=${encodeURIComponent(q)}`) },
      "-",
      { label: "Save this search as a group", run: saveSmart },
    ]);
  };
}
function syncTableHead() {
  root.querySelector(".thead")?.remove();
  root.querySelector(".find-main").style.gridTemplateRows = "";
  if (mode !== "table") return;
  $("#rhead", root).insertAdjacentHTML("afterend", `<div class="thead"><span></span><button data-sort="name">Name</button><button data-sort="seniority">Rank</button><button class="c-title" data-sort="title">Title</button>
    <button class="c-org" data-sort="smart">Office</button><button class="c-loc" data-sort="location">Base and local time</button><span class="c-dsn">DSN</span><span class="c-comm">Commercial</span><span class="c-email">Email</span></div>`);
  root.querySelector(".find-main").style.gridTemplateRows = "auto auto auto minmax(0, 1fr) auto";
  root.querySelector(".thead").onclick = (e) => {
    const b = e.target.closest("[data-sort]");
    if (b) { sort = b.dataset.sort; setParams({ sort }); }
  };
  root.querySelectorAll(".thead [data-sort]").forEach((b) => b.classList.toggle("on", b.dataset.sort === sort));
}
function renderBulk() {
  const b = $("#bulk", root);
  if (!b) return;
  if (!sel.size) return b.classList.add("hidden");
  b.classList.remove("hidden");
  b.innerHTML = `<b>${sel.size} selected</b><span style="flex:1"></span>
    <button class="btn sm" data-b="email">Email list</button><button class="btn sm" data-b="group">Add to group</button>
    <button class="btn sm" data-b="print">Print roster</button><button class="btn sm" data-b="csv">CSV</button><button class="btn sm" data-b="vcf">vCards</button>
    <button class="btn sm" data-b="clear">Clear</button>`;
  b.onclick = (e) => {
    const a = e.target.closest("[data-b]")?.dataset.b;
    const keys = [...sel];
    if (a === "clear") { sel.clear(); renderBulk(); root.querySelectorAll(".picked,.sel").forEach((x) => x.classList.remove("picked", "sel")); root.querySelectorAll("[data-ck]").forEach((c) => (c.checked = false)); }
    if (a === "email") openEmailBuilder({ keys, label: `${keys.length} selected` });
    if (a === "group") addToGroup(keys);
    if (a === "print") location.hash = `#/print?q=${encodeURIComponent("key:" + keys.join(","))}`;
    if (a === "csv" || a === "vcf") download(apiUrl("/api/export", { keys: keys.join(","), format: a }));
  };
}
function saveSmart() {
  if (!q) return say("Search for something first; the group keeps that search");
  modal({
    title: "Save this search as a group",
    body: `<label><b>Name</b> ${info("The group re-runs this search every time the directory updates, so its members stay current.")}</label>
      <input class="input" style="width:100%" data-n value="${attr(textPart(q).length < 48 ? textPart(q) : "")}" placeholder="Pacific cyber leads">
      <div class="note mono">${esc(q)}</div>`,
    actions: [{ label: "Cancel" }, { label: "Save group", primary: true, run: async (m) => {
      const r = await post("/api/group", { name: m.querySelector("[data-n]").value || q, query: q, purpose: "watch" });
      say(`Saved. <a href="#/groups/${r.id}">Open the group</a>`);
    } }],
  });
}

/* ---------------------------------------------------------------- filter bar */
function renderBar(f) {
  lastFacets = f;
  if (QUESTION.test(textPart(q))) { $("#fbar", root).innerHTML = ""; return; }
  const toks = tokens(q);
  const kindTok = toks.find((t) => t.field === "kind" && !t.neg);
  const kinds = Object.fromEntries(f.kind);
  const allN = f.kind.reduce((a, [, n]) => a + n, 0);
  const seg = `<span class="seg" role="group" aria-label="Record type">${TYPES.map(([k, l]) => {
    const on = k ? kindTok?.value === k : !kindTok;
    const n = k ? kinds[k] : allN;
    return k && !n && !on ? "" : `<button data-kind="${k}" class="${on ? "on" : ""}" aria-pressed="${on}">${l}${n != null ? `<b>${fmt(n)}</b>` : ""}</button>`;
  }).join("")}</span>`;
  const val = (field) => toks.find((t) => t.field === field && !t.neg)?.value || "";
  const select = (field, label, items) => {
    const v = val(field);
    if (!items.length && !v) return "";
    const has = items.some(([id]) => id === v);
    return `<select class="input${v ? " set" : ""}" data-fsel="${field}" aria-label="${attr(label)}"><option value="">${esc(label)}</option>${v && !has ? `<option value="${attr(v)}" selected>${esc(v)}</option>` : ""}
      ${items.map(([id, name, n]) => `<option value="${attr(id)}" ${id === v ? "selected" : ""}>${esc(name)}${n != null ? ` (${fmt(n)})` : ""}</option>`).join("")}</select>`;
  };
  const TL = Object.fromEntries((state.meta?.tiers || []).map((t) => [t.id, t.label]));
  const o = f.org;
  const orgItems = [...(o.parent ? [[o.parent.parent || "", "Up one level", null]] : []), ...o.items.map(([id, name, n]) => [id, name, n])];
  const flagOn = FLAGS.filter(([fl, v]) => hasToken(q, fl, v));
  const chips = toks.map((t, i) => ({ t, i })).filter(({ t }) => t.neg || !["kind", "base", "org", "fn", "tier"].includes(t.field) && t.field)
    .map(({ t, i }) => `<span class="tok${t.neg ? " neg" : ""}">${esc(t.raw)}<span class="x" data-rm="${i}" role="button" aria-label="Remove ${attr(t.raw)}">×</span></span>`).join("");
  $("#fbar", root).innerHTML = seg +
    select("base", "Base", f.loc.map(([id, name, n, approx]) => [id, name + (approx ? " (approx.)" : ""), n])) +
    select("org", o.parent ? `In ${o.parent.id}` : "Unit", orgItems) +
    select("fn", "Function", f.fn.map(([k, n]) => [k, state.fnLabel[k] || k, n])) +
    select("tier", "Grade", f.tier.map(([k, n]) => [k, TL[k] || k, n])) +
    `<select class="input${flagOn.length ? " set" : ""}" data-fsel="flag" aria-label="More filters"><option value="">${flagOn.length ? flagOn.map(([, , l]) => l).join(", ") : "More filters"}</option>
      ${FLAGS.map(([fl, v, l]) => `<option value="${fl}:${v}">${hasToken(q, fl, v) ? "✓ " : ""}${esc(l)}</option>`).join("")}</select>` +
    (chips ? `<span class="toks">${chips}</span>` : "") +
    (q ? `<button class="btn link" data-clear>Clear all</button>` : "");
}
function onBarClick(e) {
  const k = e.target.closest("[data-kind]");
  if (k) return setQ(setToken(q, "kind", k.dataset.kind));
  const rm = e.target.closest("[data-rm]");
  if (rm) return setQ(removeTokenAt(q, +rm.dataset.rm));
  if (e.target.closest("[data-clear]")) { $("#fq", root).value = ""; setQ(""); }
}
function onBarChange(e) {
  const s = e.target.closest("[data-fsel]");
  if (!s) return;
  const field = s.dataset.fsel;
  if (field === "flag") {
    if (!s.value) return;
    const [fl, v] = s.value.split(":");
    return setQ(toggleToken(q, fl, v));
  }
  setQ(setToken(q, field, s.value));
}
