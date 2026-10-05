/* Changes between snapshots: joined, departed, moved, promoted, retitled — by unit. */
import { $, esc, attr, fmt, tokens, info } from "../ui.js";
import { api } from "../store.js";
import { setParams } from "../app.js";
import { dateMil } from "../time.js";

const TYPES = [["joined", "Joined"], ["departed", "Departed"], ["moved", "Moved"], ["promoted", "Promoted"], ["retitled", "New title"], ["relocated", "New base"], ["regraded", "Grade change"], ["contact", "Contact info"]];
const TL = Object.fromEntries(TYPES);
const FLAG = { joined: "ok", departed: "bad", promoted: "ok", moved: "caution" };
let root, params;

export default {
  id: "changes", label: "Changes", key: "c",
  mount(el, r) { root = el; params = r.params; render(); },
  update(r) { params = r.params; render(); },
};

function orgFilter() {
  if (params.get("org")) return params.get("org");
  const t = tokens(params.get("q") || "").find((t) => t.field === "org");
  return t ? t.value.replace(/!$/, "") : "";
}
async function render() {
  const org = orgFilter(), snap = params.get("snap") || "", type = params.get("type") || "";
  const kraw = params.get("kind") || "person", kind = kraw === "all" ? "" : kraw;
  root.innerHTML = `<div class="page"><div class="loading">Comparing snapshots…</div></div>`;
  const d = await api("/api/changes", { snap, type, org, kind, limit: 2000 });
  if (!d.snapshots.length) {
    root.innerHTML = `<div class="page"><div class="empty"><b>No history yet</b>Load a second export. ORGX compares each snapshot with the one before it.</div></div>`;
    return;
  }
  const snaps = d.snapshots, i = snaps.findIndex((s) => s.id === d.snap), cur = snaps[i], prev = snaps[i - 1];
  const sum = d.summary, total = Object.values(sum).reduce((a, b) => a + b, 0);
  const peak = Math.max(1, ...d.by_org.map((r) => Math.max(r[1] + r[3], r[2] + r[4])));
  root.innerHTML = `<div class="page">
    <div class="page-title"><h1>Changes</h1>
      <span class="sub">${prev ? `<span>${esc(dateMil(prev.as_of))}</span> to <span>${esc(dateMil(cur.as_of))}</span>, from ${esc(cur.source)}` : "First snapshot. Changes are listed from the next export on."}</span>
      <span class="actions">${org ? `<span class="tok">org:${esc(org)}<span class="x" data-clear-org>×</span></span>` : ""}
        <select class="input" id="ckind" aria-label="Record type"><option value="person">People</option><option value="all">All records</option><option value="orgbox">Org boxes</option><option value="group">Distribution lists</option></select>
        <select class="input" id="csnap" aria-label="Snapshot">${snaps.slice().reverse().map((s) => `<option value="${s.id}" ${s.id === d.snap ? "selected" : ""}>Snapshot ${s.id}, ${esc(dateMil(s.as_of))}, ${fmt(s.people)} people</option>`).join("")}</select></span></div>
    ${snaps.length > 1 ? `<p class="factline">Headcount by snapshot: ${snaps.map((s) => `<span>${esc(dateMil(s.as_of))}</span> <b>${fmt(s.people)}</b>`).join(", ")}.</p>` : ""}
    <div class="filters-row">${[["", "All", total], ...TYPES.filter(([k]) => sum[k]).map(([k, l]) => [k, l, sum[k]])].map(([k, l, n]) => `<button data-type="${k}" class="${type === k ? "on" : ""}">${l}<b>${fmt(n)}</b></button>`).join("")}</div>
    <div class="cols">
      <div><table class="tbl"><thead><tr><th>Change</th><th>Who</th><th>Office</th><th>Before</th><th>After</th></tr></thead><tbody>
        ${d.rows.map((r) => `<tr class="click" data-p="${attr(r.key)}"><td><span class="flag ${FLAG[r.type] || "plain"}">${esc(TL[r.type] || r.type)}</span></td>
          <td class="nw"><b>${esc(r.name)}</b></td><td class="nw">${esc(r.type === "moved" ? "" : r.org_id || "")}</td><td class="dim">${esc(r.before || "")}</td><td>${esc(r.after || "")}</td></tr>`).join("")
          || `<tr><td colspan="5" class="muted">Nothing changed${type ? " of this kind" : ""}.</td></tr>`}
      </tbody></table>${d.rows.length >= 2000 ? `<p class="note">First 2,000 shown. Filter by office or type to narrow.</p>` : ""}</div>
      <div><h2 class="h">Net change by unit ${info("In counts people who joined or moved in; out counts people who left or moved out.")}</h2>
        <table class="tbl"><thead><tr><th>Unit</th><th class="num">Out</th><th></th><th></th><th class="num">In</th><th class="num">Net</th></tr></thead><tbody>
        ${d.by_org.map(([o, inn, out, mi, mo]) => { const a = inn + mi, b = out + mo, net = a - b; return `<tr class="click" data-org="${attr(o)}"><td>${esc(o)}</td>
          <td class="num">${b}</td><td style="width:70px"><div style="margin-left:auto;height:8px;background:var(--bad);width:${(b / peak) * 100}%"></div></td>
          <td style="width:70px"><div style="height:8px;background:var(--ok);width:${(a / peak) * 100}%"></div></td><td class="num">${a}</td>
          <td class="num"><b>${net > 0 ? "+" : ""}${net}</b></td></tr>`; }).join("") || `<tr><td colspan="6" class="muted">No movement.</td></tr>`}
        </tbody></table></div>
    </div></div>`;
  $("#ckind", root).value = kraw;
  $("#ckind", root).onchange = (e) => setParams({ kind: e.target.value === "person" ? "" : e.target.value });
  $("#csnap", root).onchange = (e) => setParams({ snap: e.target.value });
  root.querySelector(".filters-row").onclick = (e) => { const b = e.target.closest("[data-type]"); if (b) setParams({ type: b.dataset.type }); };
  root.querySelector("[data-clear-org]")?.addEventListener("click", () => setParams({ org: "", q: "" }));
}
