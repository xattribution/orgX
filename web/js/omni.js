/* Search box: jump to a person, office or base — or ask who the POC is for something. */
import { $, esc, attr, debounce, dirName, kindShort, plainName } from "./ui.js";
import { api, settings, state, liveFetch } from "./store.js";
import { ltHtml } from "./time.js";
import { go, openDrawer } from "./app.js";

let input, pop, items = [], sel = -1, seq = 0, answer = null, lastQ = "", scopeMine = false, ctx = null;
const QUESTION = /^(who|whom|where|which|poc|need|contact|is there)\b|\?$|\bpoc\b/i;

export function init() {
  input = $("#omni-input");
  pop = $("#omni-pop");
  input.addEventListener("input", debounce(() => run(), 130));
  input.addEventListener("focus", () => run());
  input.addEventListener("keydown", onKey);
  document.addEventListener("mousedown", (e) => { if (!$("#omni").contains(e.target)) close(); });
  pop.addEventListener("click", (e) => {
    const sc = e.target.closest("[data-scope]");
    if (sc) { e.preventDefault(); scopeMine = sc.dataset.scope === "mine"; lastQ = ""; return run(); }
    const it = e.target.closest("[data-i]");
    if (it && !e.target.closest("a[href^=mailto], [data-copy]")) { e.preventDefault(); e.stopPropagation(); activate(+it.dataset.i); }
  });
}
export function focus() { input.focus(); input.select(); }
export const isOpen = () => !pop.classList.contains("hidden");
export function close() { pop.classList.add("hidden"); }

function topicHits(q) {
  const s = q.toLowerCase().trim();
  if (s.length < 3) return [];
  return state.topics.filter((t) => [t.label.toLowerCase(), ...t.aliases].some((a) => a.startsWith(s) || (s.includes(a) && a.length > 3))).slice(0, 3);
}

async function run() {
  const q = input.value.trim();
  const my = ++seq;
  if (!q) return renderIdle();
  const topics = topicHits(q);
  const ask = QUESTION.test(q) || topics.some((t) => q.toLowerCase().includes(t.aliases[0] || "~"));
  const [res, orgs] = await Promise.all([
    api("/api/search", { q, limit: 8 }).catch(() => ({ rows: [], total: 0 })),
    /[:"]/.test(q) ? [] : api("/api/orgs", { q }).catch(() => []),
  ]);
  if (my !== seq) return;
  const places = [...state.locs.values()].filter((l) => `${l.name} ${l.full || ""}`.toLowerCase().includes(q.toLowerCase())).slice(0, 4);
  ctx = { q, res, orgs: orgs.slice(0, 5), places, topics };
  if ((ask || topics.length) && q !== lastQ) {
    lastQ = q;
    answer = { q, loading: true };
    render();
    const scope = scopeMine && settings.homeOrg ? `org:"${settings.homeOrg.split("/")[0]}"` : "";
    const a = await api("/api/ask", { q, scope, home_org: settings.homeOrg, home_loc: settings.homeLoc }).catch(() => null);
    if (input.value.trim() !== q) return;
    answer = a ? { q, data: a } : null;
  } else if (!ask && !topics.length) {
    answer = null;
    lastQ = "";
  }
  render();
  // on-the-fly mode: look the words up in Active Directory too, then show what arrived
  if (state.meta?.live?.on && !ask && q.length >= 2 && !/[:"]/.test(q)) {
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => liveFetch("search", { q }).then((ch) => { if (ch && input.value.trim() === q) run(); }), 350);
  }
}
let liveTimer;

function render() {
  if (!ctx) return;
  items = [];
  const { q, res, orgs, places, topics } = ctx;
  let h = answerHtml();
  if (!answer && topics.length) {
    h += sec("Ask");
    for (const t of topics) h += item(`<div class="a">Who is the POC for ${esc(t.label)}?</div>`, "", () => { input.value = `who is the POC for ${t.label}`; run(); });
  }
  if (res.rows.length) {
    h += sec(`Directory`, `${res.total.toLocaleString("en-US")} match${res.total === 1 ? "" : "es"}`);
    for (const r of res.rows) {
      h += item(`<div class="a ellip">${dirName(r)} ${r.kind === "person" ? esc(r.rank || "") : `<span class="code">${esc(kindShort(r.kind))}</span>`}</div><div class="b ellip">${esc(r.title || "")}${r.title && r.org_id ? ", " : ""}${esc(r.org_id || "")}</div>`,
        `${r.loc_name ? esc(r.loc_name) + "<br>" : ""}${ltHtml(r.tz)}`, () => openDrawer("p:" + r.key));
    }
  }
  if (orgs.length) {
    h += sec("Units and offices");
    for (const o of orgs) h += item(`<div class="a">${esc(o.id)}</div>`, `${o.people.toLocaleString("en-US")} assigned`, () => go("home", "", { u: o.id, d: "o:" + o.id }, { keepDrawer: false }));
  }
  if (places.length) {
    h += sec("Bases");
    for (const l of places) h += item(`<div class="a">${esc(l.name)}</div><div class="b">${esc(l.full || "")}${l.region ? ", " + esc(l.region) : ""}</div>`, `${ltHtml(l.tz)}<br>${(l.np || 0).toLocaleString("en-US")} assigned`, () => openDrawer("l:" + l.id));
  }
  h += sec("Go to");
  h += item(`<div class="a">Show every match as a list</div>`, "<kbd>Ctrl Enter</kbd>", () => go("dir", "", { q }, { keepDrawer: false }));
  h += item(`<div class="a">Show on the map</div>`, "", () => go("map", "", { q }, { keepDrawer: false }));
  h += `<div class="op-foot"><span><kbd>↑ ↓</kbd> move</span><span><kbd>Enter</kbd> open</span></div>`;
  pop.innerHTML = h;
  pop.classList.remove("hidden");
  highlight(answer?.data?.people?.length ? -1 : 0);
}

function answerHtml() {
  if (!answer) return "";
  if (answer.loading) return `<div class="op-ans">Looking for POCs for “${esc(answer.q)}”…</div>`;
  const a = answer.data;
  if (!a || (!a.people.length && !a.shops.length)) {
    return `<div class="op-ans">No clear POC for “${esc(answer.q)}”. Try the directory results below. If you know who owns it, open their record and add it under <b>Go-to for</b>; the next person who asks will get that answer.</div>`;
  }
  const basis = [
    a.topics.length ? `topic ${a.topics.map((t) => `<b>${esc(t.label)}</b>`).join(", ")}` : "",
    a.places?.length ? `at <b>${a.places.map(esc).join(", ")}</b>` : "",
    a.units?.length ? `in <b>${a.units.map(esc).join(", ")}</b>` : "",
    a.taught ? `${a.taught} route${a.taught > 1 ? "s" : ""} taught by your team` : "",
  ].filter(Boolean).join("; ");
  const scope = settings.homeOrg
    ? `<span class="seg" style="margin-left:auto"><button data-scope="all" class="${scopeMine ? "" : "on"}">Anywhere</button><button data-scope="mine" class="${scopeMine ? "on" : ""}">Only ${esc(settings.homeOrg.split("/")[0])}</button></span>`
    : "";
  let h = `<div class="op-ans"><div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap"><span>POCs by ${basis || "title and office match"}</span>${scope}</div>`;
  if (a.shops.length) {
    h += `<table class="tbl" style="background:none"><thead><tr><th>Office</th><th>Org box</th><th>Lead / best match</th><th>Base</th></tr></thead><tbody>`;
    for (const s of a.shops.slice(0, 4)) {
      const i = items.length;
      items.push(() => go("home", "", { u: s.id, d: "o:" + s.id }, { keepDrawer: false }));
      const top = s.top[0] || s.leader;
      h += `<tr class="click" data-i="${i}"><td>${esc(s.id)}</td>
        <td>${s.orgbox?.email ? `<a href="mailto:${attr(s.orgbox.email)}">${esc(s.orgbox.email)}</a>` : `<span class="muted">none</span>`}</td>
        <td>${top ? `${esc(plainName({ ...top, kind: "person" }))}<div class="muted">${esc(top.title || "")}</div>` : ""}</td><td>${esc(s.loc || "")}</td></tr>`;
    }
    h += `</tbody></table>`;
  }
  h += `</div>`;
  if (a.people.length) {
    h += sec("People", "best match first");
    for (const p of a.people.slice(0, 6)) {
      h += item(`<div class="a ellip">${dirName(p)} ${esc(p.rank || "")} <span class="dim" style="font-weight:400">${esc(p.title || "")}</span></div>
        <div class="b ellip"><span>${esc(p.org_id || "")}</span>. Matched on ${p.why.map(esc).join("; ")}</div>`,
        `${p.loc ? esc(p.loc) + "<br>" : ""}${ltHtml(p.tz)}`, () => openDrawer("p:" + p.key));
    }
  }
  return h;
}

function renderIdle() {
  items = [];
  answer = null;
  lastQ = "";
  ctx = null;
  let h = "";
  if (settings.starred.length) {
    h += sec("Starred");
    for (const s of settings.starred.slice(0, 6)) h += item(`<div class="a">${esc(s.name)}</div>`, "", () => openDrawer("p:" + s.key));
  }
  if (settings.recent.length) {
    h += sec("Recently opened");
    for (const s of settings.recent.slice(0, 6)) h += item(`<div class="a ellip">${esc(s.name)}</div><div class="b ellip">${esc(s.title || "")}</div>`, "", () => openDrawer("p:" + s.key));
  }
  h += sec("Examples");
  for (const ex of ["who is the SATCOM POC at Alder", "exercise planner", "annex n", "base:Birch fn:cyber", "under:me", "is:new org:\"ATLAS COMMAND\""]) {
    h += item(`<div class="a mono">${esc(ex)}</div>`, "", () => { input.value = ex.replace("under:me", settings.me ? `under:${settings.me.key}` : "is:leader"); run(); });
  }
  pop.innerHTML = h;
  pop.classList.remove("hidden");
  highlight(-1);
}

const sec = (t, n = "") => `<div class="op-sec">${t}${n ? ` <span class="n">${n}</span>` : ""}</div>`;
function item(a, c, action) {
  const i = items.length;
  items.push(action);
  return `<div class="op-it" data-i="${i}" role="option"><div class="a">${a}</div>${c ? `<div class="c">${c}</div>` : ""}</div>`;
}
function highlight(i) {
  sel = i;
  pop.querySelectorAll("[data-i]").forEach((el) => el.classList.toggle("sel", +el.dataset.i === i));
  pop.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
}
function activate(i) {
  const fn = items[i];
  if (!fn) return;
  close();
  input.blur();
  fn();
}
function onKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!isOpen()) run();
    if (!items.length) return;
    highlight(e.key === "ArrowDown" ? (sel + 1) % items.length : (sel - 1 + items.length) % items.length);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const q = input.value.trim();
    if (e.ctrlKey || e.metaKey) { close(); input.blur(); return go("dir", "", { q }, { keepDrawer: false }); }
    activate(sel >= 0 ? sel : 0);
  } else if (e.key === "Escape") { close(); input.blur(); }
}
