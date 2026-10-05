/* API client, app-wide state, personal settings (localStorage). */

export async function api(path, params = {}, opts = {}) {
  const u = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, v);
  const r = await fetch(u, opts);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const err = new Error((body && body.error) || r.statusText);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return body;
}
export const post = (path, body) =>
  api(path, {}, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function apiUrl(path, params = {}) {
  const u = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, v);
  return u.pathname + u.search;
}

/* ---------------------------------------------------------------- settings */
const KEY = "orgx.settings";
const DEFAULTS = {
  theme: "dark",
  homeOrg: "",
  homeLoc: "",
  myName: "",
  dutyStart: "0730",
  dutyEnd: "1630",
  clockSites: [],          // location ids / IANA zones on the clock wall ([] = home + largest sites)
  chatTemplate: "",        // e.g. https://teams.microsoft.us/l/chat/0/0?users={email}
  starred: [],             // [{key, name}]
  recent: [],              // [{key, name, kind}]
  mapNight: true,
  mapLabels: true,
  stripOpen: true,
  me: null,                // {key, name, rank} confirmed identity
  meDismissed: false,
};
function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}
export const settings = load();
export function save(patch = {}) {
  Object.assign(settings, patch);
  try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent("orgx:settings"));
}
export function isStarred(key) {
  return settings.starred.some((s) => s.key === key);
}
export function toggleStar(o) {
  const on = isStarred(o.key);
  save({ starred: on ? settings.starred.filter((s) => s.key !== o.key) : [{ key: o.key, name: (o.rank ? o.rank + " " : "") + o.name, kind: o.kind }, ...settings.starred].slice(0, 200) });
  return !on;
}
export function pushRecent(o) {
  const r = settings.recent.filter((x) => x.key !== o.key);
  r.unshift({ key: o.key, name: (o.rank && o.kind === "person" ? o.rank + " " : "") + o.name, kind: o.kind, title: o.title });
  save({ recent: r.slice(0, 12) });
}

/* ---------------------------------------------------------------- shared state */
export const state = {
  meta: null,
  topics: [],
  locs: new Map(),         // id → location (lat/lon/tz/name)
  fnLabel: {},
};

export async function loadMeta() {
  state.meta = await api("/api/meta");
  state.fnLabel = Object.fromEntries(state.meta.functions.map((f) => [f.id, f.label]));
  if (!state.meta.empty) {
    const [topics, locs] = await Promise.all([api("/api/topics").catch(() => []), api("/api/locations").catch(() => ({ locations: [] }))]);
    state.topics = topics;
    state.locs = new Map(locs.locations.map((l) => [l.id, l]));
  }
  return state.meta;
}

/* ---------------------------------------------------------------- on-the-fly mode
   Ask the server to fetch from Active Directory around what's on screen. Resolves to true when
   new or changed records arrived (and announces them with an "orgx:live" event). */
const liveBusy = new Map();
export function liveFetch(kind, body) {
  if (!state.meta?.live?.on) return Promise.resolve(false);
  const k = `${kind}|${JSON.stringify(body)}`;
  if (liveBusy.has(k)) return liveBusy.get(k);
  const p = post(`/api/live/${kind}`, body).then((r) => {
    liveBusy.delete(k);
    if (r?.error) window.dispatchEvent(new CustomEvent("orgx:live-error", { detail: r.error }));
    if (!r || r.cached || (r.added || 0) + (r.updated || 0) === 0) return false;
    // new records can bring new bases; refresh those before anyone redraws
    return api("/api/locations").then((l) => { state.locs = new Map(l.locations.map((x) => [x.id, x])); }).catch(() => {}).then(() => {
      window.dispatchEvent(new CustomEvent("orgx:live", { detail: { kind, ...r } }));
      return true;
    });
  }).catch(() => { liveBusy.delete(k); return false; });
  liveBusy.set(k, p);
  return p;
}
