/* ORGX shell: router, nav, clock strip, identity, me menu, keyboard. */
import { $, esc, attr, say, modal, plainName, menu, icon } from "./ui.js";
import { api, settings, save, state, loadMeta } from "./store.js";
import { dtg, localTime } from "./time.js";
import * as omni from "./omni.js";
import * as detail from "./detail.js";
import workspace from "./views/workspace.js";
import directory from "./views/directory.js";
import orgView from "./views/org.js";
import mapView from "./views/map.js";
import changesView from "./views/changes.js";
import groupsView from "./views/groups.js";
import timeView from "./views/time.js";
import dataView from "./views/data.js";
import printView from "./views/print.js";

const VIEWS = [workspace, directory, orgView, mapView, changesView, groupsView, timeView, dataView, printView];
const NAV = ["home", "groups", "time", "data"];
const byId = Object.fromEntries(VIEWS.map((v) => [v.id, v]));
let current = null;
let lastDrawer = "";

/* ---------------------------------------------------------------- routing */
export function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const [view, ...rest] = (path || "home").split("/");
  return { view: byId[view] ? view : "home", arg: rest.length ? decodeURIComponent(rest.join("/")) : "", params: new URLSearchParams(qs || "") };
}
export function href(view, arg = "", params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
  const s = p.toString();
  return `#/${view}${arg ? "/" + encodeURIComponent(arg) : ""}${s ? "?" + s : ""}`;
}
export function go(view, arg = "", params = {}, { keepDrawer = true } = {}) {
  const cur = parseHash();
  if (keepDrawer && cur.params.get("d") && !("d" in params)) params = { ...params, d: cur.params.get("d") };
  location.hash = href(view, arg, params);
}
export function setParams(patch, { replace = true } = {}) {
  const cur = parseHash();
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined || v === null || v === "") cur.params.delete(k);
    else cur.params.set(k, v);
  }
  const s = cur.params.toString();
  const h = `#/${cur.view}${cur.arg ? "/" + encodeURIComponent(cur.arg) : ""}${s ? "?" + s : ""}`;
  if (replace) history.replaceState(null, "", h);
  else history.pushState(null, "", h);
  route(true);
}
function route(fromSetParams = false) {
  const r = parseHash();
  const key = `${r.view}|${r.arg}`;
  const view = byId[r.view];
  document.querySelectorAll("#nav a").forEach((a) => { a.classList.toggle("on", a.dataset.view === r.view); a.toggleAttribute("aria-current", a.dataset.view === r.view); });
  document.body.dataset.view = r.view;
  if (!current || current.key !== key) {
    current?.view.unmount?.();
    const el = $("#view");
    el.innerHTML = "";
    current = { view, key };
    view.mount(el, r);
  } else if (view.update) view.update(r, fromSetParams);
  const d = r.params.get("d") || "";
  if (d !== lastDrawer) {
    lastDrawer = d;
    d ? detail.open(d) : detail.close();
  }
}
export const openDrawer = (ref) => setParams({ d: ref }, { replace: false });
export const closeDrawer = () => setParams({ d: "" }, { replace: false });

/* ---------------------------------------------------------------- frame */
function renderNav() {
  $("#nav").innerHTML = NAV.map((id) => byId[id]).map((v) =>
    `<a href="#/${v.id}" data-view="${v.id}" title="${v.key ? `g then ${v.key}` : ""}">${esc(v.label)}</a>`).join("");
}
function applyTheme() {
  document.documentElement.dataset.theme = settings.theme || "dark";
}
/* clock wall: DTG, then the viewer's local time, then home and the largest sites (or the user's pick) */
export function clockSites() {
  const locs = [...state.locs.values()];
  if (settings.clockSites?.length) {
    return settings.clockSites.map((id) => state.locs.get(id) || (id.includes("/") ? { id, name: id.split("/").pop().replace(/_/g, " "), tz: id } : null)).filter(Boolean);
  }
  const out = [];
  const seenTz = new Set([Intl.DateTimeFormat().resolvedOptions().timeZone]);
  const home = state.locs.get(settings.homeLoc);
  for (const l of [home, ...locs.sort((a, b) => (b.np || 0) - (a.np || 0))]) {
    if (!l || !l.tz || seenTz.has(l.tz)) continue;
    seenTz.add(l.tz);
    out.push(l);
    if (out.length >= 7) break;
  }
  return out;
}
/* the header shows the Zulu DTG; the chosen sites open beneath it */
function clockLine(tz) {
  const lt = localTime(tz);
  return lt ? `${lt.time}${lt.letter || ""}${lt.day ? (lt.day > 0 ? " +1" : " −1") : ""}` : "";
}
function renderClocks() {
  $("#clocks").innerHTML = `<span class="t">${dtg()}</span>`;
}
function openClocks(e) {
  const mine = Intl.DateTimeFormat().resolvedOptions().timeZone;
  menu(e.currentTarget, [
    { label: "Local", right: clockLine(mine), run: () => {} },
    ...clockSites().map((l) => ({ label: l.name, right: clockLine(l.tz), run: () => {} })),
    "-",
    { label: "Change clocks", run: () => (location.hash = "#/time") },
  ]);
}

function renderMe() {
  const me = settings.me;
  $("#me").innerHTML = `<button aria-haspopup="menu" id="me-btn" aria-label="Settings" title="Settings">${me ? `<span>${esc(me.name)}</span>` : icon("gear")}</button>`;
  $("#me-btn").onclick = (e) => {
    const t = settings.theme || "dark";
    const setTheme = (v) => { save({ theme: v }); applyTheme(); window.dispatchEvent(new CustomEvent("orgx:theme")); };
    menu(e.currentTarget, [
      ...(me ? [{ label: "Open my record", run: () => openDrawer("p:" + me.key) }] : [{ label: "Find myself", run: () => (location.hash = "#/data/settings") }]),
      { label: "My settings", run: () => (location.hash = "#/data/settings") },
      { label: "Keyboard shortcuts", run: shortcuts },
      "-",
      { label: "Dark", on: t === "dark", run: () => setTheme("dark") },
      { label: "Light", on: t === "light", run: () => setTheme("light") },
      { label: "Match the system", on: t === "auto", run: () => setTheme("auto") },
    ]);
  };
}
export function renderStatus() { /* status is now transient; kept for callers */ }
export function setSelection() { /* the bulk bar shows the count */ }

/* first visit on a workstation: offer the Windows sign-in identity as "me" */
async function identity() {
  if (settings.me || settings.meDismissed || state.meta?.empty) return;
  const who = await api("/api/whoami").catch(() => null);
  const m = who?.match;
  if (!m) return;
  const n = $("#notice");
  n.innerHTML = `<div class="notice-bar">Signed in to Windows as <b>${esc(who.detected.upn || who.detected.dn)}</b>, which is <b>${esc(plainName({ ...m, kind: "person" }))}</b>, ${esc(m.org_id || "")}${m.loc_name ? ", " + esc(m.loc_name) : ""}.
    <button class="btn sm primary" data-yes>Use as me</button> <button class="btn sm" data-no>Not me</button></div>`;
  n.onclick = (e) => {
    if (e.target.closest("[data-yes]")) {
      save({ me: { key: m.key, name: plainName({ ...m, kind: "person" }) }, homeOrg: settings.homeOrg || m.org_id || "", homeLoc: settings.homeLoc || m.loc_id || "" });
      renderMe();
      renderClocks();
      say(`Using ${esc(plainName({ ...m, kind: "person" }))} as you`);
    }
    if (e.target.closest("[data-yes],[data-no]")) {
      if (e.target.closest("[data-no]")) save({ meDismissed: true });
      n.innerHTML = "";
    }
  };
}

function shortcuts() {
  modal({
    title: "Keyboard",
    body: `<div class="keys">
      <kbd>Ctrl K</kbd><span>Find someone, or ask who handles something</span>
      <kbd>/</kbd><span>Search the current list</span>
      <kbd>↑ ↓</kbd><span>Move through results; the card follows</span>
      <kbd>x</kbd><span>Select the current result</span>
      <kbd>c</kbd><span>Copy the current person's email</span>
      <kbd>g p</kbd><span>People</span><kbd>g f</kbd><span>Search as a list</span><kbd>g o</kbd><span>Organization</span><kbd>g m</kbd><span>Map</span>
      <kbd>g c</kbd><span>Changes</span><kbd>g g</kbd><span>Groups</span><kbd>g t</kbd><span>Time</span><kbd>g s</kbd><span>Data and settings</span>
      <kbd>Esc</kbd><span>Close the record or popup</span>
    </div>
    <p class="note">Filter language: <span class="mono">base:Alder fn:cyber grade:&gt;=O-4 under:&lt;email&gt; is:new -cat:ctr "annex n"</span></p>`,
    actions: [{ label: "Close", primary: true }],
  });
}

/* ---------------------------------------------------------------- global actions */
function onGlobalClick(e) {
  const t = e.target.closest("[data-p],[data-org],[data-loc],[data-copy],[data-q],[data-go]");
  if (!t || e.defaultPrevented) return;
  if (t.dataset.copy !== undefined) { e.preventDefault(); import("./ui.js").then((u) => u.copy(t.dataset.copy, t.dataset.copyLabel || "Copied")); }
  else if (t.dataset.p) { e.preventDefault(); openDrawer("p:" + t.dataset.p); }
  else if (t.dataset.org !== undefined) {
    e.preventDefault();
    if (parseHash().view === "home" && !e.metaKey && !e.ctrlKey) setParams({ u: t.dataset.org, d: "o:" + t.dataset.org }, { replace: false });   // stay on People, select the unit
    else if (t.dataset.orgGo !== undefined || e.metaKey || e.ctrlKey) go("org", t.dataset.org, {}, { keepDrawer: false });
    else openDrawer("o:" + t.dataset.org);
  } else if (t.dataset.loc) { e.preventDefault(); openDrawer("l:" + t.dataset.loc); }
  else if (t.dataset.q !== undefined) { e.preventDefault(); go(t.dataset.view || "dir", "", { q: t.dataset.q }, { keepDrawer: false }); }
  else if (t.dataset.go) { e.preventDefault(); location.hash = t.dataset.go; }
}
let gPending = 0;
function onKey(e) {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); focusFind(); return; }
  if (e.key === "Escape") {
    if (omni.isOpen()) return omni.close();
    if (document.querySelector(".modal-back")) return;
    if (parseHash().params.get("d")) return closeDrawer();
    if (typing) document.activeElement.blur();
    return;
  }
  if (typing) return;
  if (e.key === "/") { e.preventDefault(); const f = document.querySelector("[data-filter-input]"); f ? (f.focus(), f.select?.()) : focusFind(); return; }
  if (e.key === "?") return shortcuts();
  if (e.key === "g" && !gPending) { gPending = Date.now(); return; }
  if (Date.now() - gPending < 900) {
    const v = VIEWS.find((x) => x.key === e.key);
    gPending = 0;
    if (v) go(v.id, "", {}, { keepDrawer: false });
  }
  gPending = 0;
}

function focusFind() {
  const f = document.querySelector("#fq");
  if (f) { f.focus(); f.select(); } else omni.focus();
}

/* ---------------------------------------------------------------- boot */
export async function refreshMeta() {
  await loadMeta();
  renderClocks();
  return state.meta;
}
async function boot() {
  applyTheme();
  renderNav();
  renderMe();
  document.addEventListener("click", onGlobalClick);
  document.addEventListener("keydown", onKey);
  detail.init({ close: closeDrawer });
  omni.init();
  try {
    await refreshMeta();
  } catch (e) {
    $("#view").innerHTML = `<div class="empty"><b>Can't reach the ORGX server</b>${esc(e.message)}. Check that server.py is running, then reload.</div>`;
    return;
  }
  if (state.meta.empty && !location.hash.startsWith("#/data")) location.hash = "#/data/sources";
  window.addEventListener("hashchange", () => { omni.close(); route(); });
  $("#clocks").onclick = openClocks;
  window.addEventListener("orgx:settings", () => { renderClocks(); renderMe(); });
  setInterval(renderClocks, 15_000);
  setInterval(async () => {
    try {
      const j = await api("/api/job");
      const was = state.meta?.job?.running;
      if (state.meta) state.meta.job = j;
      if (j.running && !was) say(`Loading ${esc(j.source || "directory")}…`, 0);
      if (was && !j.running) {
        await refreshMeta();
        say(j.error ? `Ingest failed: ${esc(j.error)}` : `Directory updated from ${esc(j.source || "")}`);
        window.dispatchEvent(new CustomEvent("orgx:data"));
      }
    } catch { /* server restarting */ }
  }, 4000);
  route();
  identity();
}
boot();
