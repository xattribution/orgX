/* Groups: exercise cells, teams, distros, saved filters. Shareable as .orgx.json bundles. */
import { $, esc, attr, fmt, copy, say, modal, debounce, dirName, plainName, download, shortOrg, info, menu, icon } from "../ui.js";
import { api, post, apiUrl, settings, state } from "../store.js";
import { ltHtml, dateMil } from "../time.js";
import { go } from "../app.js";
import { openEmailBuilder } from "../email.js";

const PURPOSE = { exercise: "Exercise", team: "Team", distro: "Distro", watch: "Saved filter", other: "Other" };
const CHG = { departed: "left the directory", moved: "moved", promoted: "promoted", retitled: "new title", relocated: "new base", contact: "contact info changed" };
let root, cur = "";

export default {
  id: "groups", label: "Groups", key: "g",
  mount(el, r) {
    root = el;
    cur = r.arg || "";
    el.innerHTML = `<div class="split"><aside id="gside"></aside><section id="gmain"></section></div><input type="file" id="gfile" accept=".json,application/json" hidden>`;
    $("#gfile", el).onchange = importFile;
    render();
  },
};
const nav = (id) => { cur = String(id); history.replaceState(null, "", `#/groups/${cur}`); render(); };

function countdown(g) {
  if (!g.starts) return "";
  const day = 864e5, now = Date.now(), s = Date.parse(g.starts), e = g.ends ? Date.parse(g.ends) + day : s + day;
  if (now < s) return `STARTEX in ${Math.ceil((s - now) / day)} d`;
  if (now < e) return `Day ${Math.floor((now - s) / day) + 1} of ${Math.round((e - s) / day)}`;
  return "ENDEX";
}

async function render() {
  const gs = await api("/api/groups").catch(() => []);
  if (!cur) cur = gs.length ? String(gs[0].id) : "starred";
  const by = (p) => gs.filter((g) => (p === "watch" ? g.kind === "smart" : g.kind !== "smart" && (p === "exercise" ? g.purpose === "exercise" : g.purpose !== "exercise")));
  const li = (g) => `<div class="li ${String(g.id) === cur ? "on" : ""}" data-g="${g.id}"><span class="a ellip">${esc(g.name)}</span><span class="c">${g.kind === "smart" ? "filter" : fmt(g.n)}</span>
    <span class="b ellip">${g.purpose === "exercise" && g.starts ? `<span>${esc(dateMil(g.starts))}</span> ${esc(countdown(g))}` : esc(g.place || PURPOSE[g.purpose] || "")}</span></div>`;
  // headings only when there is more than one kind of group to tell apart
  const kinds = [["Exercises", by("exercise")], ["Teams", by("team")], ["Saved filters", by("watch")]].filter(([, l]) => l.length);
  $("#gside", root).innerHTML = `<div class="gside-top"><button class="btn sm primary" data-new>New group</button><button class="btn sm icon quiet" data-gmore aria-label="More ways to add a group" title="More">${icon("more")}</button></div>
    ${settings.starred.length ? `<div class="li ${cur === "starred" ? "on" : ""}" data-g="starred"><span class="a">Starred</span><span class="c">${settings.starred.length}</span></div>` : ""}
    ${kinds.map(([h, l]) => `${kinds.length > 1 ? `<div class="aside-h">${h}</div>` : ""}${l.map(li).join("")}`).join("") || `<p class="note" style="padding:6px 10px">No groups yet.</p>`}`;
  $("#gside", root).onclick = (e) => {
    if (e.target.closest("[data-new]")) return editGroup();
    const gm = e.target.closest("[data-gmore]");
    if (gm) return menu(gm, [{ label: "Import a share file", run: () => $("#gfile", root).click() }, { label: "Paste a list", run: () => pasteList(null) }]);
    const l = e.target.closest("[data-g]");
    if (l) nav(l.dataset.g);
  };
  const main = $("#gmain", root);
  main.innerHTML = `<div class="loading">Loading group…</div>`;
  if (cur === "starred") return renderStarred(main);
  const g = await api("/api/group", { id: cur }).catch(() => null);
  if (!g || g.error) { main.innerHTML = `<div class="empty"><b>Pick a group on the left</b>or create one for an upcoming exercise.</div>`; return; }
  g.kind === "smart" ? renderSmart(main, g) : renderStatic(main, g);
}

/* ---------------------------------------------------------------- header + actions */
function head(g, extra = "") {
  const cd = countdown(g);
  const links = (g.links || []).map((l) => `<a href="${attr(l.url)}" target="_blank" rel="noopener">${esc(l.label || l.url)}</a>`).join(", ");
  return `<div class="page-title"><h1>${esc(g.name)}</h1><span class="flag plain">${esc(PURPOSE[g.purpose] || "Group")}</span>${cd ? `<span class="countdown">${esc(cd)}</span>` : ""}
      <span class="actions">${extra}<button class="btn sm icon" data-gm="more" aria-label="More" title="More">${icon("more")}</button></span></div>
    <dl class="dl" style="max-width:820px">
      ${g.starts ? `<dt>Dates</dt><dd><span>STARTEX ${esc(dateMil(g.starts))}${g.ends ? `, ENDEX ${esc(dateMil(g.ends))}` : ""}</span></dd>` : ""}
      ${g.place ? `<dt>Where</dt><dd>${esc(g.place)}</dd>` : ""}
      ${g.description ? `<dt>Purpose</dt><dd>${esc(g.description)}</dd>` : ""}
      ${links ? `<dt>Links</dt><dd>${links}</dd>` : ""}
      ${g.origin ? `<dt>Imported from</dt><dd class="mono">${esc(g.origin)}</dd>` : ""}
    </dl>`;
}
function wire(main, g, keys) {
  const smart = g.kind === "smart";
  const more = [
    ...(smart ? [{ label: "Open in directory", run: () => act("open") }, { label: "Freeze as a fixed group", run: () => act("freeze") }]
      : [{ label: "Print roster", run: () => act("print") }, { label: "Download CSV", run: () => act("csv") }, { label: "Download vCards", run: () => act("vcf") }]),
    "-",
    { label: "Copy link", run: () => act("link") },
    { label: "Download share file", href: apiUrl("/api/group/export", { id: g.id, by: settings.me?.name || "" }) },
    "-",
    { label: "Edit details", run: () => act("edit") },
    { label: "Delete group", danger: true, run: () => act("delete") },
  ];
  main.onclick = async (e) => {
    const gm = e.target.closest("[data-gm]");
    if (gm) return menu(gm, more);
    const a = e.target.closest("[data-act]")?.dataset.act;
    const rm = e.target.closest("[data-rm]");
    if (rm) { e.stopPropagation(); await post("/api/group", { id: g.id, remove: [rm.dataset.rm] }); return render(); }
    if (a) act(a);
  };
  async function act(a) {
    if (a === "edit") editGroup(g);
    if (a === "link") copy(`${location.origin}/#/groups/${g.id}`, "Copied link to this group");
    if (a === "delete" && confirm(`Delete “${g.name}” for everyone on this server? Export a share file first if you may need it again.`)) {
      await post("/api/group", { id: g.id, delete: true });
      cur = "";
      history.replaceState(null, "", "#/groups");
      render();
    }
    if (a === "email") openEmailBuilder(g.kind === "smart" ? { q: g.query, label: g.name } : { group: g.id, label: g.name });
    if (a === "print") location.hash = `#/print?group=${g.id}`;
    if (a === "csv") download(apiUrl("/api/group/export", { id: g.id, format: "csv" }));
    if (a === "vcf") download(apiUrl("/api/export", { keys: keys.join(","), format: "vcf" }));
    if (a === "paste") pasteList(g);
    if (a === "external") addExternal(g);
    if (a === "prune") {
      const gone = g.members.filter((m) => m.gone).map((m) => m.key);
      await post("/api/group", { id: g.id, remove: gone });
      say(`Removed ${gone.length} who left the directory`);
      render();
    }
    if (a === "freeze") {
      const res = await api("/api/search", { q: g.query, limit: 1000 });
      const r = await post("/api/group", { name: `${g.name} (${dateMil(new Date().toISOString())})`, purpose: "team", add: res.rows.map((x) => x.key) });
      nav(r.id);
    }
    if (a === "open") go("dir", "", { q: g.query }, { keepDrawer: false });
  }
}

/* ---------------------------------------------------------------- fixed groups */
function renderStatic(main, g) {
  const keys = g.members.filter((m) => !m.external && !m.gone).map((m) => m.key);
  const gone = g.members.filter((m) => m.gone).length;
  const ext = g.members.filter((m) => m.external).length;
  const sections = [...new Set(g.members.map((m) => m.section || ""))].sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
  const changes = g.changes || [];
  main.innerHTML = `<div class="page">${head(g, `<button class="btn sm primary" data-act="email">Email list</button>`)}
    ${changes.length ? `<div class="callout">Since the last snapshot: ${changes.map((c) => `<a data-p="${attr(c.key)}">${esc(c.name)}</a> ${esc(CHG[c.type] || c.type)}${c.after && c.type !== "departed" ? ` (${esc(c.after)})` : ""}`).join("; ")}.</div>` : ""}
    <h2 class="h">Members <span class="n">${fmt(g.members.length)}${ext ? `, ${ext} external` : ""}</span>
      <span class="r">${gone ? `<span class="flag bad">${gone} left the directory</span> <button class="btn link" data-act="prune">remove them</button>` : ""}</span></h2>
    <div class="filterrow" style="margin-bottom:8px;position:relative"><input class="input grow" id="gadd" placeholder="Add a person, email or office" aria-label="Add a person by name, email or office symbol" autocomplete="off">
      <button class="btn sm" data-act="paste">Paste a list</button><button class="btn sm quiet" data-act="external">Someone outside the directory</button>
      <div class="omni-pop hidden" id="gsug" style="top:30px"></div></div>
    <datalist id="sections">${sections.filter(Boolean).map((s) => `<option value="${attr(s)}">`).join("")}<option value="Leadership"><option value="White cell"><option value="Blue cell"><option value="Partners"></datalist>
    <table class="tbl"><thead><tr><th style="width:150px">Role</th><th style="width:130px">Section</th><th>Name</th><th>Rank</th><th>Office</th><th>Base, local time</th><th>DSN</th><th>Email</th><th></th></tr></thead><tbody>
    ${sections.map((s) => {
      const rows = g.members.filter((m) => (m.section || "") === s);
      return `${sections.length > 1 ? `<tr class="grp"><td colspan="9">${esc(s || "No section")} <span class="muted">${rows.length}</span></td></tr>` : ""}` + rows.map((m) => {
        const lv = m.live || {};
        const name = m.external ? `<b>${esc(m.name)}</b> <span class="flag plain">external</span>` : m.gone ? `<b>${esc(m.name)}</b> <span class="flag bad">left the directory</span>` : `<a class="plain" data-p="${attr(m.key)}">${dirName(lv)}</a>`;
        return `<tr><td><input class="cell-input" data-role="${attr(m.key)}" value="${attr(m.role)}" aria-label="Role"></td>
          <td><input class="cell-input" list="sections" data-section="${attr(m.key)}" value="${attr(m.section)}" aria-label="Section"></td>
          <td>${name}</td><td>${esc(lv.rank || m.rank || "")}</td><td>${esc(shortOrg(lv.org_id || m.org).a)}</td>
          <td>${esc(lv.loc_name || "")} ${ltHtml(lv.tz)}</td><td class="ph">${esc(lv.dsn || "")}</td><td>${esc(lv.email || m.email || "")}</td>
          <td><button class="btn sm icon quiet rm" data-rm="${attr(m.key)}" aria-label="Remove from group" title="Remove from group">${icon("x")}</button></td></tr>`;
      }).join("");
    }).join("") || `<tr><td colspan="9" class="muted">No members yet. Add people above, paste an email thread's To: line, or select people in the directory and choose Add to group.</td></tr>`}
    </tbody></table></div>`;
  wire(main, g, keys);
  main.onchange = async (e) => {
    const r = e.target.closest("[data-role],[data-section]");
    if (!r) return;
    const key = r.dataset.role || r.dataset.section;
    await post("/api/group", { id: g.id, update: [{ key, [r.dataset.role ? "role" : "section"]: r.value.trim() }] });
    say(`Saved ${r.dataset.role ? "role" : "section"}`);
    if (r.dataset.section) render();
  };
  const inp = $("#gadd", main), sug = $("#gsug", main);
  inp.addEventListener("input", debounce(async () => {
    const t = inp.value.trim();
    if (t.length < 2) return sug.classList.add("hidden");
    const res = await api("/api/search", { q: t, limit: 8 });
    sug.innerHTML = res.rows.map((r) => `<div class="op-it" data-add="${attr(r.key)}"><div class="a">${dirName(r)} ${esc(r.rank || "")}<div class="b">${esc(r.title || "")}, <span>${esc(r.org_id || "")}</span></div></div><div class="c">${esc(r.loc_name || "")}</div></div>`).join("")
      || `<div class="op-it"><div class="a muted">No match. Use Add external contact for people outside this directory.</div></div>`;
    sug.classList.remove("hidden");
  }, 150));
  sug.addEventListener("click", async (e) => {
    const a = e.target.closest("[data-add]");
    if (!a) return;
    await post("/api/group", { id: g.id, add: [a.dataset.add] });
    say("Added");
    render();
  });
}

/* ---------------------------------------------------------------- saved filters */
async function renderSmart(main, g) {
  const res = await api("/api/search", { q: g.query, limit: 500, sort: "smart" });
  main.innerHTML = `<div class="page">${head(g, `<button class="btn sm primary" data-act="email">Email list</button>`)}
    <p class="factline"><span class="mono">${esc(g.query)}</span> <b>${fmt(res.total)}</b> matches</p>
    <table class="tbl"><thead><tr><th>Name</th><th>Rank</th><th>Title</th><th>Office</th><th>Base, local time</th><th>Email</th></tr></thead><tbody>
    ${res.rows.map((r) => `<tr class="click" data-p="${attr(r.key)}"><td>${dirName(r)}</td><td>${esc(r.rank || "")}</td><td class="dim">${esc(r.title || "")}</td><td>${esc(r.org_id || "")}</td><td>${esc(r.loc_name || "")} ${ltHtml(r.tz)}</td><td>${esc(r.email || "")}</td></tr>`).join("")}
    </tbody></table></div>`;
  wire(main, g, res.rows.map((r) => r.key));
}

async function renderStarred(main) {
  const keys = settings.starred.map((s) => s.key);
  const res = keys.length ? await api("/api/search", { q: `key:${keys.map((k) => k.replace(/[,\s"]/g, "")).join(",")}`, limit: 500 }).catch(() => ({ rows: [] })) : { rows: [] };
  main.innerHTML = `<div class="page"><div class="page-title"><h1>Starred</h1>
      <span class="actions">${res.rows.length ? `<button class="btn sm primary" data-email>Email list</button><button class="btn sm" data-mk>Make a group from these</button>` : ""}</span></div>
    ${res.rows.length ? `<table class="tbl"><thead><tr><th>Name</th><th>Rank</th><th>Title</th><th>Office</th><th>Base, local time</th><th>Email</th></tr></thead><tbody>
      ${res.rows.map((r) => `<tr class="click" data-p="${attr(r.key)}"><td>${dirName(r)}</td><td>${esc(r.rank || "")}</td><td class="dim">${esc(r.title || "")}</td><td>${esc(r.org_id || "")}</td><td>${esc(r.loc_name || "")} ${ltHtml(r.tz)}</td><td>${esc(r.email || "")}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty"><b>Nothing starred</b>Star people from their record or from the star at the end of a directory row.</div>`}</div>`;
  main.onclick = async (e) => {
    if (e.target.closest("[data-email]")) openEmailBuilder({ keys: res.rows.map((r) => r.key), label: "starred" });
    if (e.target.closest("[data-mk]")) { const r = await post("/api/group", { name: "Starred contacts", add: res.rows.map((x) => x.key) }); nav(r.id); }
  };
}

/* ---------------------------------------------------------------- dialogs */
function editGroup(g = null) {
  const v = g || { name: "", purpose: "exercise", starts: "", ends: "", place: "", description: "", links: [] };
  const bases = [...state.locs.values()].map((l) => l.name).sort();
  modal({
    title: g ? `Edit ${g.name}` : "New group",
    body: `<div class="form" style="grid-template-columns:110px 1fr">
      <label>Name</label><input class="input" data-f="name" value="${attr(v.name)}" placeholder="KS27 bilateral planning cell">
      <label>Type</label><select class="input" data-f="purpose">${Object.entries(PURPOSE).filter(([k]) => k !== "watch").map(([k, l]) => `<option value="${k}" ${v.purpose === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label>STARTEX</label><span><input class="input" type="date" data-f="starts" value="${attr(v.starts)}"><span>${v.starts ? " " + esc(dateMil(v.starts)) : ""}</span></span>
      <label>ENDEX</label><span><input class="input" type="date" data-f="ends" value="${attr(v.ends)}"><span>${v.ends ? " " + esc(dateMil(v.ends)) : ""}</span></span>
      <label>Where</label><input class="input" data-f="place" list="gbases" value="${attr(v.place)}" placeholder="Fir"><datalist id="gbases">${bases.map((b) => `<option value="${attr(b)}">`).join("")}</datalist>
      <label>Purpose</label><textarea class="input" rows="2" data-f="description">${esc(v.description)}</textarea>
      <label>Links</label><div><textarea class="input" rows="2" style="width:100%" data-f="links" placeholder="Battle rhythm | https://…">${esc((v.links || []).map((l) => `${l.label} | ${l.url}`).join("\n"))}</textarea><div class="help">One per line: label | address (SharePoint site, MSEL, JEMM, …).</div></div>
    </div>`,
    actions: [{ label: "Cancel" }, { label: g ? "Save" : "Create group", primary: true, run: async (m) => {
      const f = (k) => m.querySelector(`[data-f=${k}]`).value.trim();
      const body = { name: f("name") || "Untitled group", purpose: f("purpose"), starts: f("starts"), ends: f("ends"), place: f("place"), description: f("description"), by: settings.me?.name || "",
        links: f("links").split("\n").map((l) => l.split("|").map((x) => x.trim())).filter(([, u]) => u).map(([label, url]) => ({ label, url })) };
      const r = await post("/api/group", g ? { id: g.id, ...body } : body);
      nav(r.id);
    } }],
  });
  // echo picked dates as DD MMM YY; the native picker shows the browser's locale format
  document.querySelectorAll(".modal input[type=date]").forEach((i) => i.addEventListener("input", () => { i.nextElementSibling.textContent = i.value ? " " + dateMil(i.value) : ""; }));
}

function addExternal(g) {
  modal({
    title: "Add someone outside this directory",
    body: `<div class="form" style="grid-template-columns:90px 1fr"><label>Name ${info("For partner-nation planners, contractors on another network, or anyone without an account here. Kept with the group and included in its share file.")}</label><input class="input" data-f="name" placeholder="Lt Col SATO Kenji">
      <label>Rank</label><input class="input" data-f="rank"><label>Email</label><input class="input" data-f="email"><label>Phone</label><input class="input" data-f="phone">
      <label>Office</label><input class="input" data-f="org" placeholder="Partner HQ/J3"><label>Role</label><input class="input" data-f="role" placeholder="JASDF LNO"></div>`,
    actions: [{ label: "Cancel" }, { label: "Add", primary: true, run: async (m) => {
      const f = (k) => m.querySelector(`[data-f=${k}]`).value.trim();
      if (!f("name") && !f("email")) return true;
      await post("/api/group", { id: g.id, members: [{ name: f("name"), rank: f("rank"), email: f("email"), phone: f("phone"), org: f("org"), role: f("role"), external: true }] });
      render();
    } }],
  });
}

function pasteList(g) {
  modal({
    title: g ? `Paste a list into ${g.name}` : "Make a group from a pasted list",
    wide: true,
    body: `<label><b>Addresses or names</b> ${info("Paste an Outlook To: or Cc: line, a forwarded email header, a column of addresses, or names one per line. Each entry is matched against the directory.")}</label>
      <textarea class="input outbox" data-t rows="6" placeholder='"SMITH, JANE A Capt USSF MERIDIAN GROUP/S6" <jane.smith@…>; DOE, JOHN TSgt USAF HARBOR COMM SQ; k.sato@partner.example'></textarea>
      <div><button class="btn sm" data-resolve>Match against the directory</button></div><div data-res></div>`,
    onMount: (m) => {
      m.querySelector("[data-resolve]").onclick = async () => {
        const r = await post("/api/resolve", { text: m.querySelector("[data-t]").value });
        const host = m.querySelector("[data-res]");
        m._items = r.items;
        host.innerHTML = `<p class="factline"><b>${r.items.filter((i) => i.match).length}</b> matched, <b>${r.items.filter((i) => !i.match && i.candidates.length).length}</b> need a choice, <b>${r.items.filter((i) => !i.match && !i.candidates.length).length}</b> not found.</p>
          <table class="tbl"><thead><tr><th></th><th>Pasted</th><th>Directory match</th></tr></thead><tbody>${r.items.map((it, i) => `<tr><td><input type="checkbox" data-i="${i}" ${it.match || !it.candidates.length ? "checked" : ""}></td>
            <td class="mono">${esc(it.input)}</td><td>${it.match ? `${esc(plainName({ ...it.match, kind: "person" }))}, <span>${esc(it.match.org_id || "")}</span>`
              : it.candidates.length ? `<select class="input" data-c="${i}">${it.candidates.map((c, j) => `<option value="${j}">${esc(plainName({ ...c, kind: "person" }))}, ${esc(c.org_id || "")}</option>`).join("")}</select>`
              : `<span class="muted">not in the directory; added as external</span>`}</td></tr>`).join("")}</tbody></table>`;
      };
    },
    actions: [{ label: "Cancel" }, { label: "Add checked", primary: true, run: async (m) => {
      const items = m._items || [];
      const add = [], members = [];
      m.querySelectorAll("[data-i]:checked").forEach((c) => {
        const it = items[+c.dataset.i];
        const sel = m.querySelector(`[data-c="${c.dataset.i}"]`);
        const hit = it.match || (sel ? it.candidates[+sel.value] : null);
        if (hit) add.push(hit.key);
        else members.push({ name: it.label || it.input, email: it.input.includes("@") ? it.input : "", external: true });
      });
      if (!add.length && !members.length) return true;
      const r = await post("/api/group", g ? { id: g.id, add, members } : { name: "Pasted list", purpose: "team", add, members, by: settings.me?.name || "" });
      say(`Added ${add.length + members.length}`);
      nav(r.id);
    } }],
  });
  // echo picked dates as DD MMM YY; the native picker shows the browser's locale format
  document.querySelectorAll(".modal input[type=date]").forEach((i) => i.addEventListener("input", () => { i.nextElementSibling.textContent = i.value ? " " + dateMil(i.value) : ""; }));
}

async function importFile(e) {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  let bundle;
  try { bundle = JSON.parse(await f.text()); } catch { return say(`${esc(f.name)} is not a share file`); }
  const r = await post("/api/group/import", bundle).catch((err) => ({ error: err.message }));
  if (r.error) return say(esc(r.error));
  say(`Imported ${esc(bundle.name || f.name)}: ${r.matched} matched here, ${r.external} kept as external${r.mode === "merge" ? " (merged into the existing copy)" : ""}`);
  nav(r.id);
}
