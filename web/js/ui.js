/* DOM + formatting helpers, a small icon set, the status line, dialogs, query tokens. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export const attr = esc;

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
export const fmt = (n) => (n == null ? "" : Number(n).toLocaleString("en-US"));
export const plural = (n, one, many = one + "s") => `${fmt(n)} ${n === 1 ? one : many}`;

/* ---------------------------------------------------------------- icons: only for repeated, scannable actions */
const P = {
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  copy: '<rect x="9" y="9" width="12" height="12"/><path d="M5 15H3V3h12v2"/>',
  mail: '<rect x="2" y="4" width="20" height="16"/><path d="m22 6-10 7L2 6"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
  starf: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z" fill="currentColor"/>',
  download: '<path d="M21 15v6H3v-6M7 10l5 5 5-5M12 15V3"/>',
  print: '<path d="M6 9V2h12v7M6 18H2v-9h20v9h-4M6 14h12v8H6z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  fit: '<path d="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  chev: '<path d="m6 9 6 6 6-6"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
};
/* A clear button inside a search field: shown while it has text, empties it, keeps focus.
   Returns sync() for callers that set the value themselves. */
export function clearable(input, onClear) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "clr";
  b.title = "Clear (Esc)";
  b.setAttribute("aria-label", "Clear search");
  b.innerHTML = icon("x");
  input.after(b);
  const box = input.parentElement;
  const sync = () => { b.hidden = !input.value; box.classList.toggle("filled", !!input.value); };
  input.addEventListener("input", sync);
  b.addEventListener("mousedown", (e) => e.preventDefault());
  b.addEventListener("click", () => { input.value = ""; sync(); onClear(); input.focus(); });
  sync();
  return sync;
}

export function icon(name, cls = "") {
  return `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ""}</svg>`;
}

/* ---------------------------------------------------------------- names in directory vernacular */
const KIND_SHORT = { orgbox: "org box", group: "DL", resource: "room", contact: "ext" };
export const kindShort = (k) => KIND_SHORT[k] || "";
/** Name in natural order, bold, as people say it ("Jane M. Smith"); mailbox name otherwise */
export function dirName(o) {
  return o.kind && o.kind !== "person" ? esc(o.name) : `<b>${esc(o.name || "")}</b>`;
}
/** "Jane M. Smith" (natural order, no rank) */
export const natName = (o) => esc(o.name || "");
/** "Capt Jane M. Smith" */
export function plainName(o) {
  return o.kind === "person" && o.rank ? `${o.rank} ${o.name}` : o.name;
}
export function shortOrg(id) {
  if (!id) return { a: "", b: "" };
  const p = id.split("/");
  return p.length === 1 ? { a: p[0], b: "" } : { a: p.slice(-1)[0], b: p.slice(0, -1).join("/") };
}
export const FN_CODE = { command: "CMD", ops: "OPS", intel: "INT", cyber: "COM", plans: "PLN", exercises: "EXR", personnel: "PER", logistics: "LOG", resources: "RES", support: "SPT" };

/* ---------------------------------------------------------------- status line: one confirmation at a time */
let sayTimer;
export function say(html, ms = 4500) {
  const el = document.getElementById("status");
  if (!el) return;
  el.innerHTML = html;
  clearTimeout(sayTimer);
  if (ms) sayTimer = setTimeout(() => { el.innerHTML = ""; }, ms);
}

/* ---------------------------------------------------------------- (i) tips: hover or keyboard focus shows, Esc hides */
let tipN = 0;
export function info(text, label = "More about this") {
  const id = `tip${++tipN}`;
  return `<span class="tipwrap"><button type="button" class="info" aria-describedby="${id}" aria-label="${attr(label)}">i</button><span role="tooltip" id="${id}">${esc(text)}</span></span>`;
}
addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".info").forEach((b) => (b.dataset.dismissed = "")); });
for (const ev of ["focusin", "pointerover"]) addEventListener(ev, (e) => { if (e.target.matches?.(".info")) delete e.target.dataset.dismissed; });

/* ---------------------------------------------------------------- small popover menu anchored to a button */
let openMenu = null;
export function menu(anchor, items) {
  closeMenu();
  const m = document.createElement("div");
  m.className = "menu";
  m.setAttribute("role", "menu");
  const radio = items.some((it) => it?.on !== undefined);
  m.innerHTML = items.map((it, i) => it === "-" ? "<hr>" : it.label && it.heading ? `<div class="lab">${esc(it.label)}</div>`
    : it.href ? `<a role="menuitem" href="${attr(it.href)}" data-mi="${i}" ${it.download ? "download" : ""}>${esc(it.label)}</a>`
    : `<button role="${it.on !== undefined ? "menuitemradio" : "menuitem"}" data-mi="${i}" ${it.on !== undefined ? `aria-checked="${!!it.on}"` : ""}${it.danger ? ' class="danger"' : ""}>${radio ? `<span class="ck">${it.on ? icon("check") : ""}</span>` : ""}<span class="lb">${esc(it.label)}</span>${it.right ? `<span class="rt">${esc(it.right)}</span>` : ""}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  const w = Math.max(m.offsetWidth, 200);
  m.style.top = `${Math.min(r.bottom + 4, innerHeight - m.offsetHeight - 8)}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - w, innerWidth - w - 8))}px`;
  m.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mi]");
    if (!b) return;
    const it = items[+b.dataset.mi];
    if (!it.href) { e.preventDefault(); it.run?.(); }
    closeMenu();
  });
  const away = (e) => { if (!m.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) closeMenu(); };
  const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); closeMenu(); anchor.focus(); } };
  setTimeout(() => document.addEventListener("mousedown", away), 0);
  document.addEventListener("keydown", esc_, true);
  openMenu = { m, away, esc_ };
  m.querySelector("[data-mi]")?.focus();
}
export function closeMenu() {
  if (!openMenu) return;
  openMenu.m.remove();
  document.removeEventListener("mousedown", openMenu.away);
  document.removeEventListener("keydown", openMenu.esc_, true);
  openMenu = null;
}
export async function copy(text, label = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  say(esc(label));
}

export function modal({ title, body, actions = [], onMount, wide = false }) {
  const root = document.getElementById("modal-root");
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal${wide ? " wide" : ""}" role="dialog" aria-label="${attr(title)}">
      <div class="mh">${esc(title)}</div><div class="mb">${body}</div>
      ${actions.length ? `<div class="mf">${actions.map((a, i) => `<button class="btn ${a.primary ? "primary" : ""}" data-i="${i}">${esc(a.label)}</button>`).join("")}</div>` : ""}
    </div>`;
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "TEXTAREA") {
      const p = actions.findIndex((a) => a.primary);
      if (p >= 0) { e.preventDefault(); run(p); }
    }
  };
  const run = async (i) => {
    const a = actions[i];
    const keep = a.run ? await a.run(back) : false;
    if (keep !== true) close();
  };
  back.addEventListener("click", (e) => {
    if (e.target === back) close();
    const b = e.target.closest(".mf [data-i]");
    if (b) run(Number(b.dataset.i));
  });
  document.addEventListener("keydown", onKey, true);
  root.appendChild(back);
  onMount?.(back, close);
  setTimeout(() => back.querySelector("input:not([type=checkbox]):not([type=radio]),select,textarea")?.focus(), 30);
  return close;
}

export function download(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
export function saveText(text, filename, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------------------------------------------------------------- query tokens (mirror of server grammar) */
const TOK = /(-)?(?:([a-zA-Z]+):)?("([^"]*)"|\S+)/g;
export function tokens(q) {
  const out = [];
  for (const m of (q || "").matchAll(TOK)) out.push({ neg: !!m[1], field: (m[2] || "").toLowerCase(), value: m[4] ?? m[3], raw: m[0] });
  return out;
}
export const quote = (v) => (/[\s"]/.test(v) ? `"${String(v).replace(/"/g, "")}"` : v);
export function toggleToken(q, field, value) {
  const toks = tokens(q);
  const idx = toks.findIndex((t) => t.field === field && !t.neg);
  if (idx < 0) return [q.trim(), `${field}:${quote(value)}`].filter(Boolean).join(" ");
  const vals = toks[idx].value.split(",").map((s) => s.trim()).filter(Boolean);
  const has = vals.some((v) => v.toLowerCase() === String(value).toLowerCase());
  const next = has ? vals.filter((v) => v.toLowerCase() !== String(value).toLowerCase()) : [...vals, value];
  return toks.map((t, i) => (i !== idx ? t.raw : next.length ? `${field}:${quote(next.join(","))}` : "")).filter(Boolean).join(" ");
}
export function hasToken(q, field, value) {
  return tokens(q).some((t) => t.field === field && !t.neg && t.value.split(",").some((v) => v.trim().toLowerCase() === String(value).toLowerCase()));
}
export const removeTokenAt = (q, i) => tokens(q).filter((_, j) => j !== i).map((t) => t.raw).join(" ");
export function setToken(q, field, value) {
  const rest = tokens(q).filter((t) => t.field !== field).map((t) => t.raw);
  return [...rest, value == null || value === "" ? "" : `${field}:${quote(value)}`].filter(Boolean).join(" ");
}
