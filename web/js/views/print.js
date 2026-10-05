/* Print rosters: directory-style and recall (call-down order), grouped by office or section. */
import { $, esc, attr, fmt, info } from "../ui.js";
import { api, state } from "../store.js";
import { dtg, dateMil } from "../time.js";
import { setParams } from "../app.js";

let root;

export default {
  id: "print",            // not in the nav; opened from Print roster buttons
  mount(el, r) { root = el; render(r.params); },
  update(r) { render(r.params); },
};

async function render(p) {
  const mode = p.get("mode") || "directory";
  let rows = [], title = "", groupBy = "office";
  if (p.get("group")) {
    const g = await api("/api/group", { id: p.get("group") });
    title = g.name;
    groupBy = "section";
    rows = g.members.map((m) => ({ ...(m.live || {}), key: m.key, name: m.live?.name || m.name, rank: m.live?.rank || m.rank, title: m.live?.title || m.title,
      org_id: m.live?.org_id || m.org, email: m.live?.email || m.email, phone: m.live?.phone || m.phone, role: m.role, section: m.section, external: m.external, kind: "person" }));
  } else {
    const q = p.get("q") || "kind:person";
    let total = 0;
    do {   // the API pages at 1,000; a roster stops at 5,000
      const res = await api("/api/search", { q, limit: 1000, offset: rows.length, sort: "org" });
      total = res.total;
      rows = rows.concat(res.rows);
      if (!res.rows.length) break;
    } while (rows.length < Math.min(total, 5000));
    title = q === "kind:person" ? "Directory" : `Filter ${q}`;
    if (total > rows.length) title += ` (first ${fmt(rows.length)} of ${fmt(total)})`;
  }
  const keyOf = (r) => (groupBy === "section" ? r.section || "No section" : r.org_id || "No office");
  const groups = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  const snap = state.meta?.latest;
  root.innerHTML = `<div class="page">
    <div class="page-title no-print"><h1>Print roster</h1>
      <span class="actions"><span class="seg"><button data-mode="directory" class="${mode === "directory" ? "on" : ""}">Directory</button><button data-mode="recall" class="${mode === "recall" ? "on" : ""}">Recall roster</button></span>
      ${info(mode === "recall" ? "Within each block the lead is called first, then everyone else by grade. Numbers are the call-down order. Landscape fits best." : "Grouped by office, leads first, then by grade. Landscape fits best.")}<button class="btn primary" data-print>Print</button><button class="btn" onclick="history.back()">Back</button></span></div>
    <div style="display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--ink);margin-bottom:6px">
      <h2 style="margin:0;font-size:15px">${esc(title)}</h2>
      <span class="note">Printed ${esc(dtg())}${snap ? `, directory snapshot ${snap.id} as of ${esc(dateMil(snap.as_of))}` : ""}, ${fmt(rows.length)} entries</span></div>
    <table class="tbl"><thead><tr>${mode === "recall" ? "<th>#</th>" : ""}${groupBy === "section" ? "<th>Role</th>" : ""}<th>Rank</th><th>Name</th><th>Title</th>${groupBy === "section" ? "<th>Office</th>" : ""}<th>DSN</th><th>Commercial</th><th>Mobile</th><th>Email</th>${mode === "recall" ? "<th>Reached</th>" : ""}</tr></thead><tbody>
    ${[...groups.entries()].sort((a, b) => (a[0].startsWith("No ") ? 1 : 0) - (b[0].startsWith("No ") ? 1 : 0)).map(([k, rs]) => {
      rs.sort((a, b) => (b.leader || 0) - (a.leader || 0) || (b.level || 0) - (a.level || 0));
      return `<tr class="grp"><td colspan="11">${esc(k)} <span class="muted">${rs.length}</span></td></tr>` + rs.map((r, i) =>
        `<tr>${mode === "recall" ? `<td>${i + 1}</td>` : ""}${groupBy === "section" ? `<td>${esc(r.role || "")}</td>` : ""}<td>${esc(r.rank || "")}</td>
          <td><b>${esc(r.name || "")}</b>${r.external ? " (external)" : ""}</td><td>${esc(r.title || "")}</td>${groupBy === "section" ? `<td>${esc(r.org_id || "")}</td>` : ""}
          <td class="ph">${esc(r.dsn || "")}</td><td class="ph">${esc(r.phone || "")}</td><td class="ph">${esc(r.mobile || "")}</td><td>${esc(r.email || "")}</td>${mode === "recall" ? "<td style='width:70px'></td>" : ""}</tr>`).join("");
    }).join("")}</tbody></table></div>`;
  root.querySelector("[data-print]").onclick = () => window.print();
  root.querySelector(".seg").onclick = (e) => { const b = e.target.closest("[data-mode]"); if (b) setParams({ mode: b.dataset.mode }); };
}
