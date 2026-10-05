/* Data and settings: sources and AD connector, quality, rules, personal settings. */
import { $, esc, attr, fmt, say, debounce, dirName, plainName, info } from "../ui.js";
import { api, post, settings, save, state } from "../store.js";
import { dateMil } from "../time.js";
import { go, refreshMeta } from "../app.js";

const TABS = [["sources", "Sources"], ["quality", "Quality"], ["rules", "Rules"], ["settings", "My settings"]];
const FN_IDS = ["command", "ops", "intel", "cyber", "plans", "exercises", "personnel", "logistics", "resources", "support"];
let root, tab = "sources", poll = null;

export default {
  id: "data", label: "Data", key: "s",
  mount(el, r) { root = el; tab = r.arg || "sources"; render(); window.addEventListener("orgx:data", render); },
  unmount() { clearInterval(poll); window.removeEventListener("orgx:data", render); },
};

function render() {
  clearInterval(poll);
  root.innerHTML = `<div class="page"><div class="filters-row">${TABS.map(([id, l]) => `<button data-tab="${id}" class="${tab === id ? "on" : ""}">${l}</button>`).join("")}</div><div id="dbody"><div class="loading">Loading…</div></div></div>`;
  root.querySelector(".filters-row").onclick = (e) => { const t = e.target.closest("[data-tab]"); if (t) go("data", t.dataset.tab, {}, { keepDrawer: false }); };
  ({ sources, quality, rules, settings: mySettings })[tab]?.($("#dbody", root));
}

/* ---------------------------------------------------------------- sources and AD */
async function sources(body) {
  const [meta, src, ad] = await Promise.all([api("/api/meta"), api("/api/sources").catch(() => ({ files: [], inbox: "" })), api("/api/ad").catch(() => null)]);
  const job = meta.job;
  const st = ad?.state || {};
  body.innerHTML = `
    ${meta.empty ? `<div class="callout" style="margin:0 0 14px">No directory is loaded. Sync from AD, drop an export below, or <button class="btn sm" data-demo>load synthetic demo data</button> to look around first.</div>` : ""}
    <div class="cols"><div>
      <h2 class="h">Active Directory <span class="n">${ad?.available ? "PowerShell available on this host" : "not available on this host"}</span></h2>
      ${ad?.available ? `
        <div class="form" style="grid-template-columns:130px 1fr">
          <label>Domain</label><input class="input mono" data-ad="server" value="${attr(ad.config.server)}" placeholder="Your own domain">
          <label>Search bases</label><div><textarea class="input mono" rows="2" style="width:100%" data-ad="bases" placeholder="Blank: the whole domain. One DN per line, e.g. OU=Sites,DC=corp,DC=example">${esc((ad.config.bases || []).join("\n"))}</textarea></div>
          <label>Method ${info('ADSI uses the .NET directory searcher built into Windows with your Kerberos sign-in, the same way AD Explorer connects. RSAT uses the ActiveDirectory module and is needed if PowerShell runs in Constrained Language mode.')}</label><div><select class="input" data-ad="method">${["Auto", "ADSI", "RSAT"].map((m) => `<option ${ad.config.method === m ? "selected" : ""}>${m}</option>`).join("")}</select></div>
          <label data-for="export">Group members</label><label class="chk" data-for="export"><input type="checkbox" data-ad="members" ${ad.config.members ? "checked" : ""}>Export DL membership (slower on large domains)</label>
          <label>Mode ${info("Full export reads the whole directory into ORGX on a schedule. On the fly looks up only what you search for or open, with a couple of levels above and below it, and keeps it.")}</label><div><select class="input" data-ad="mode">${[["export", "Full export"], ["live", "On the fly"]].map(([v, l]) => `<option value="${v}" ${(ad.config.mode || "export") === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <label data-for="live">Look up again after</label><div data-for="live"><select class="input" data-ad="liveHours">${[[1, "1 hour"], [4, "4 hours"], [12, "12 hours"], [24, "1 day"], [168, "1 week"]].map(([h, l]) => `<option value="${h}" ${+(ad.config.liveHours || 12) === h ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <label data-for="export">Schedule</label><div data-for="export"><select class="input" data-ad="hours">${[[0, "Manual only"], [6, "Every 6 hours"], [12, "Every 12 hours"], [24, "Daily"], [168, "Weekly"]].map(([h, l]) => `<option value="${h}" ${+ad.config.hours === h ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        </div>
        <div style="display:flex;gap:6px;margin:10px 0"><button class="btn" data-adsave>Save</button><button class="btn" data-adtest>Test connection</button><button class="btn primary" data-adsync ${job.running ? "disabled" : ""}>Sync now</button></div>
        <div data-adout>${st.test ? testHtml(st.test, st.last_test) : ""}${st.last_sync ? `<p class="note">Last sync ${esc(st.last_sync.replace("T", " ").slice(0, 16))}Z${st.sync?.count ? `, ${fmt(st.sync.count)} objects in ${st.sync.seconds} s by ${esc(st.sync.method)}` : ""}.</p>` : ""}</div>`
      : `<p>${esc(ad?.hint || "")}</p>
        <div class="log">.\\tools\\Export-ADDirectory.ps1 -Test
.\\tools\\Export-ADDirectory.ps1 -Inbox "${esc(src.inbox)}"</div>
`}
      <label class="drop" id="drop"><input type="file" accept=".csv,.tsv,.txt,text/csv" hidden id="file">
        <b>Drop a CSV export here, or click to choose</b></label>
      <p class="note">Or copy it into <span class="mono">${esc(src.inbox)}</span> ${info("Files in this folder load within a minute and are then archived. Each file becomes a snapshot; differences from the previous one become the change history.")}</p>
      ${job.running || job.result || job.error ? `<h2 class="h">${job.running ? `Loading ${esc(job.source || "")}` : job.error ? "Last load failed" : "Last load"}</h2>
        ${job.result ? `<p class="factline"><b>${fmt(job.result.objects)}</b> records, <b>${fmt(job.result.people)}</b> people, <b>${fmt(job.result.orgs)}</b> offices, <b>${fmt(job.result.locations)}</b> bases, <b>${fmt(job.result.events)}</b> changes in ${job.result.seconds} s.</p>` : ""}
        ${job.error ? `<p style="color:var(--bad)">${esc(job.error)}</p>` : ""}<div class="log" id="joblog">${esc((job.log || []).join("\n") || "…")}</div>` : ""}
    </div><div>
      <h2 class="h">Snapshots<span class="r"><a href="#/changes">Change history</a></span></h2>
      ${meta.snapshots?.length ? `<table class="tbl"><thead><tr><th>#</th><th>As of</th><th>Source</th><th class="num">People</th><th class="num">Offices</th><th class="num">Bases</th><th class="num">Unplaced</th></tr></thead><tbody>
        ${meta.snapshots.slice().reverse().map((s) => `<tr><td>${s.id}</td><td class="nw">${esc(dateMil(s.as_of))}</td><td class="ellip" style="max-width:220px" title="${attr(s.source)}">${esc(s.source)}</td><td class="num">${fmt(s.people)}</td><td class="num">${fmt(s.orgs)}</td><td class="num">${fmt(s.locations)}</td><td class="num">${fmt(s.unplaced)}</td></tr>`).join("")}</tbody></table>` : `<p class="note">None yet.</p>`}
      ${src.files.length ? `<h2 class="h">Source files<span class="r"><button class="btn sm quiet" data-reingest>Reload with current rules</button></span></h2><table class="tbl"><tbody>${src.files.slice(0, 8).map((f) => `<tr><td class="mono ellip" style="max-width:300px">${esc(f.name)}</td><td class="num">${(f.bytes / 1048576).toFixed(1)} MB</td></tr>`).join("")}</tbody></table>` : ""}
      ${!meta.empty ? `<div style="margin-top:24px"><button class="btn sm danger" data-reset title="Drops the directory and its change history. Team notes and groups are kept.">Reset directory</button></div>` : ""}
    </div></div>`;
  const drop = $("#drop", body), file = $("#file", body);
  file.onchange = () => file.files[0] && upload(file.files[0]);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  body.querySelector("[data-demo]")?.addEventListener("click", async () => { await post("/api/demo", {}); watchJob(); });
  body.querySelector("[data-reingest]")?.addEventListener("click", async () => { const r = await post("/api/reingest", {}); if (r.error) say(esc(r.error)); watchJob(); });
  body.querySelector("[data-reset]")?.addEventListener("click", async () => {
    if (!confirm("Drop the directory and all change history? Team notes and groups are kept.")) return;
    await post("/api/reset", { demo_files: true });
    await refreshMeta();
    render();
  });
  const adcfg = () => ({
    server: body.querySelector("[data-ad=server]").value.trim(), method: body.querySelector("[data-ad=method]").value,
    bases: body.querySelector("[data-ad=bases]").value.split("\n").map((s) => s.trim()).filter(Boolean),
    members: body.querySelector("[data-ad=members]").checked, hours: +body.querySelector("[data-ad=hours]").value,
    mode: body.querySelector("[data-ad=mode]").value, liveHours: +body.querySelector("[data-ad=liveHours]").value,
  });
  const modeSel = body.querySelector("[data-ad=mode]");
  const showMode = () => body.querySelectorAll("[data-for]").forEach((el) => { el.hidden = el.dataset.for !== modeSel.value; });
  if (modeSel) { modeSel.onchange = showMode; showMode(); }
  body.querySelector("[data-adsave]")?.addEventListener("click", async () => { await post("/api/rules", { ad: adcfg() }); await refreshMeta(); say("AD settings saved"); });
  body.querySelector("[data-adtest]")?.addEventListener("click", async (e) => {
    await post("/api/rules", { ad: adcfg() });
    e.target.disabled = true;
    body.querySelector("[data-adout]").innerHTML = `<p class="note">Binding to ${esc(adcfg().server)} as you…</p>`;
    const r = await post("/api/ad/test", {});
    e.target.disabled = false;
    body.querySelector("[data-adout]").innerHTML = testHtml(r, new Date().toISOString());
  });
  body.querySelector("[data-adsync]")?.addEventListener("click", async () => {
    await post("/api/rules", { ad: adcfg() });
    const r = await post("/api/ad/sync", {});
    if (r.error) return say(esc(r.error));
    watchJob();
  });
  if (job.running) watchJob(false);
}
function testHtml(r, when) {
  return r.ok
    ? `<table class="tbl"><tbody><tr><td>Result</td><td><span class="flag ok">connected</span> ${when ? `<span class="muted mono">${esc(String(when).replace("T", " ").slice(0, 16))}Z</span>` : ""}</td></tr>
       <tr><td>Bound as</td><td>${esc(r.user)}</td></tr>${r.userDN ? `<tr><td>Your DN</td><td>${esc(r.userDN)}</td></tr>` : ""}
       <tr><td>Method</td><td>${esc(r.method)}, PowerShell ${esc(r.languageMode)}${r.rsat ? ", RSAT installed" : ""}</td></tr><tr><td>Sample</td><td>${fmt(r.sample)} objects read from ${esc((r.bases || [])[0] || "")}</td></tr></tbody></table>`
    : `<p><span class="flag bad">not connected</span> ${esc(r.error || "unknown error")}</p>${r.languageMode ? `<p class="note">Method ${esc(r.method)}, PowerShell ${esc(r.languageMode)}${r.rsat ? ", RSAT installed" : ", no RSAT"}.</p>` : ""}`;
}
async function upload(f) {
  say(`Uploading ${esc(f.name)}, ${(f.size / 1048576).toFixed(1)} MB`);
  const r = await fetch(`/api/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body: f }).then((r) => r.json());
  if (r.error) return say(esc(r.error));
  watchJob();
}
function watchJob(rerender = true) {
  if (rerender) render();
  clearInterval(poll);
  poll = setInterval(async () => {
    const j = await api("/api/job");
    const log = root.querySelector("#joblog");
    if (log) log.textContent = (j.log || []).join("\n");
    if (!j.running) { clearInterval(poll); await refreshMeta(); window.dispatchEvent(new CustomEvent("orgx:data")); }
  }, 1200);
}

/* ---------------------------------------------------------------- quality */
async function quality(body) {
  const [q, rr] = await Promise.all([api("/api/quality"), api("/api/rules")]);
  const cols = q.columns || {};
  body.innerHTML = `<div class="cols"><div>
      <h2 class="h">Checks</h2>
      <table class="tbl"><tbody>${q.issues.map((i) => `<tr><td>${i.count ? `<span class="flag ${i.severity === "warn" ? "caution" : "plain"}">${i.severity === "warn" ? "check" : "note"}</span>` : `<span class="flag ok">ok</span>`}</td>
        <td>${esc(i.label)}${i.help ? info(i.help) : ""}</td><td class="num"><b>${fmt(i.count)}</b></td>
        <td>${i.query && i.count ? `<a data-q="${attr(i.query)}">list them</a>` : ""}</td></tr>`).join("")}</tbody></table>
      ${q.approx.length ? `<h2 class="h">Sites without coordinates ${info("Pinned at a state or country center. Map each one to a known site (saved as a rule), or add it to data/sites.json with coordinates.")}</h2>
        <table class="tbl"><thead><tr><th>OU or place</th><th>Region</th><th class="num">Records</th><th>Same as</th></tr></thead><tbody>
        ${q.approx.map((a) => `<tr><td><b>${esc(a.name)}</b><div class="note">${esc(a.full || "")}</div></td><td>${esc(a.region || a.country || "")}</td><td class="num">${fmt(a.total)}</td>
          <td><select class="input" data-alias="${attr(a.ou || a.name)}"><option value="">(none)</option>${rr.bases.map((b) => `<option ${rr.rules.baseAliases?.[a.ou || a.name] === b ? "selected" : ""}>${esc(b)}</option>`).join("")}</select></td></tr>`).join("")}
        </tbody></table><div style="margin-top:8px"><button class="btn primary sm" data-save-alias>Save and reload</button></div>` : ""}
      ${q.leaderless.length ? `<h2 class="h">Offices with no leadership title ${info("The lead falls back to the most senior member.")}</h2>
        <table class="tbl"><tbody>${q.leaderless.map((o) => `<tr class="click" data-org="${attr(o.id)}"><td>${esc(o.id)}</td><td class="dim">${o.senior ? esc((o.rank || "") + " " + o.senior) : ""}</td><td class="num">${o.people}</td></tr>`).join("")}</tbody></table>` : ""}
    </div><div>
      <h2 class="h">Columns detected in the last export</h2>
      <dl class="attrs">${Object.entries(cols.mapped || {}).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${cols.extra?.length ? `<p class="note">Kept as extra attributes: ${cols.extra.map(esc).join(", ")}</p>` : ""}
      ${q.inferred.length ? `<h2 class="h">Inferred parents ${info("Override them under Rules, Org parents.")}</h2>
        <table class="tbl"><tbody>${q.inferred.map((o) => `<tr><td><a data-org="${attr(o.id)}">${esc(o.id)}</a></td><td>under <a data-org="${attr(o.parent)}">${esc(o.parent)}</a></td><td class="dim">${esc(o.inferred)}</td></tr>`).join("")}</tbody></table>` : ""}
      ${q.dups.length ? `<h2 class="h">Shared email addresses</h2><table class="tbl"><tbody>${q.dups.map((d) => `<tr><td><a data-q="email:${attr(d.email)}">${esc(d.email)}</a></td><td class="num">${d.n}</td><td class="dim">${esc(d.names)}</td></tr>`).join("")}</tbody></table>` : ""}
    </div></div>`;
  body.querySelector("[data-save-alias]")?.addEventListener("click", async () => {
    const aliases = { ...(rr.rules.baseAliases || {}) };
    body.querySelectorAll("[data-alias]").forEach((s) => { if (s.value) aliases[s.dataset.alias] = s.value; else delete aliases[s.dataset.alias]; });
    await post("/api/rules", { baseAliases: aliases });
    const r = await post("/api/reingest", {});
    say(r.error ? esc(r.error) : "Reloading with the new base aliases");
  });
}

/* ---------------------------------------------------------------- rules */
async function rules(body) {
  const { rules: r, defaults, bases, learned } = await api("/api/rules");
  const kv = (name, obj, lp, rp, list) => `<div class="kvedit" data-kv="${name}">${Object.entries(obj || {}).map(([a, b]) => kvRow(a, b, lp, rp, list)).join("")}${kvRow("", "", lp, rp, list)}</div>`;
  body.innerHTML = `<div class="form">
    <label>Site OU ${info('Blank: ORGX finds the OU level that holds sites in your directory. To pin it instead, name the OU that sits above region and site.')}</label><div><input class="input mono" style="width:100%" data-anchors value="${attr((r.anchors || []).join(", "))}" placeholder="Found in the data">${learnedNote(learned)}</div>
    <label>Inference</label><div style="display:flex;flex-direction:column;gap:4px">
      ${[["inferFromManagers", "Place a top-level unit under the unit its people report to (Manager attribute)"], ["nestOfficeSymbols", "Office symbols: SCOO under SCO under SC"], ["skipDisabled", "Skip disabled people (shared and room mailboxes are always kept)"], ["skipHidden", "Skip records hidden from the address book"]]
        .map(([k, l]) => `<label class="chk"><input type="checkbox" data-flag="${k}" ${r[k] ? "checked" : ""}>${l}</label>`).join("")}</div>
    <label>Site aliases ${info('Text in an OU, office or city that means a site in data/sites.json.')}</label><div>${kv("baseAliases", r.baseAliases, "Text in OU, office or city", "Site", bases)}</div>
    <label>Org aliases ${info('Merge two spellings of the same unit into one.')}</label><div>${kv("orgAliases", r.orgAliases, "First org segment as written", "Canonical name")}</div>
    <label>Org parents ${info('Overrides what ORGX inferred about which unit belongs under which.')}</label><div>${kv("orgParents", r.orgParents, "Unit", "Belongs under")}</div>
    <label>Office functions ${info('When an office number misleads: S36 is Exercises in your shop, not Ops.')}</label><div>${kv("codeFunctions", r.codeFunctions, "Org code, e.g. S36", "Function", FN_IDS)}</div>
    <label>Function keywords ${info('Blank uses the built-in list (shown greyed). Comma-separated; matched against titles.')}</label><div style="display:flex;flex-direction:column;gap:6px">${FN_IDS.map((f) => `<div><div class="note">${esc(state.fnLabel[f] || f)}</div>
      <textarea class="input" rows="1" style="width:100%" data-fnkw="${f}" placeholder="${attr(defaults.fnKeywords[f])}">${esc(r.fnKeywords?.[f] || "")}</textarea></div>`).join("")}</div>
    <label>POC topics ${info("Extends “who is the POC for …”. Example: Starlink; aliases starlink, pltv; codes S6, A6; title terms satcom, commercial. A person's Go-to for note always wins.")}</label><div><div data-topics style="display:flex;flex-direction:column;gap:6px">${(r.topics || []).map(topicRow).join("")}</div>
      <button class="btn sm" data-addtopic style="margin-top:6px">Add topic</button></div>
  </div>
  <div style="display:flex;gap:6px;margin-top:16px"><button class="btn" data-save>Save rules</button><button class="btn primary" data-save-run>Save and reload the latest file</button></div>`;
  body.addEventListener("click", (e) => {
    if (e.target.closest("[data-kvdel]")) e.target.closest(".kvrow").remove();
    if (e.target.closest("[data-addtopic]")) body.querySelector("[data-topics]").insertAdjacentHTML("beforeend", topicRow({}));
    if (e.target.closest("[data-topicdel]")) e.target.closest("[data-topic]").remove();
  });
  body.addEventListener("input", (e) => {
    const box = e.target.closest("[data-kv]");
    if (!box) return;
    const rows = box.querySelectorAll(".kvrow"), last = rows[rows.length - 1];
    const list = box.dataset.kv === "baseAliases" ? bases : box.dataset.kv === "codeFunctions" ? FN_IDS : null;
    if ([...last.querySelectorAll("input,select")].some((i) => i.value)) last.insertAdjacentHTML("afterend", kvRow("", "", last.querySelector("input").placeholder, "", list));
  });
  const collect = () => {
    const out = { anchors: body.querySelector("[data-anchors]").value.split(",").map((s) => s.trim()).filter(Boolean), fnKeywords: {}, topics: [] };
    body.querySelectorAll("[data-flag]").forEach((c) => (out[c.dataset.flag] = c.checked));
    body.querySelectorAll("[data-kv]").forEach((box) => {
      out[box.dataset.kv] = {};
      box.querySelectorAll(".kvrow").forEach((row) => { const [a, b] = row.querySelectorAll("input,select"); if (a.value.trim() && b.value.trim()) out[box.dataset.kv][a.value.trim()] = b.value.trim(); });
    });
    body.querySelectorAll("[data-fnkw]").forEach((t) => { if (t.value.trim()) out.fnKeywords[t.dataset.fnkw] = t.value.trim(); });
    body.querySelectorAll("[data-topic]").forEach((t) => {
      const g = (n) => t.querySelector(`[data-t=${n}]`).value.split(",").map((s) => s.trim()).filter(Boolean);
      const label = t.querySelector("[data-t=label]").value.trim();
      if (label) out.topics.push({ label, aliases: g("aliases").map((s) => s.toLowerCase()), fns: g("fns"), codes: g("codes"), terms: g("terms").map((s) => s.toLowerCase()), countries: g("countries").map((s) => s.toUpperCase()) });
    });
    return out;
  };
  body.querySelector("[data-save]").onclick = async () => { await post("/api/rules", collect()); say("Rules saved. They apply on the next load."); };
  body.querySelector("[data-save-run]").onclick = async () => { await post("/api/rules", collect()); const r = await post("/api/reingest", {}); say(r.error ? esc(r.error) : "Reloading with the new rules"); };
}
function learnedNote(l) {
  if (!l?.site) return "";
  const ex = (x) => x.examples.map((v) => `“${esc(v)}”`).join(", ");
  return `<div class="note">Found in the data: sites ${ex(l.site)}${l.region ? `; regions ${ex(l.region)}` : ""}</div>`;
}
function kvRow(a, b, lp, rp, list) {
  const right = list ? `<select class="input"><option value="">${esc(rp || "choose")}</option>${list.map((x) => `<option ${x === b ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : `<input class="input" placeholder="${attr(rp)}" value="${attr(b)}">`;
  return `<div class="kvrow"><input class="input" placeholder="${attr(lp)}" value="${attr(a)}"><span class="muted">to</span>${right}<button class="btn sm" data-kvdel title="Remove">×</button></div>`;
}
function topicRow(t) {
  const f = (k, ph) => `<input class="input" data-t="${k}" placeholder="${ph}" value="${attr((Array.isArray(t[k]) ? t[k].join(", ") : t[k]) || "")}">`;
  return `<div data-topic style="display:grid;grid-template-columns:1.1fr 1.4fr 1fr .8fr 1.2fr .6fr 26px;gap:4px">${f("label", "Label")}${f("aliases", "aliases")}${f("fns", "functions: cyber, ops")}${f("codes", "codes: S6, A6")}${f("terms", "title terms")}${f("countries", "JP, KR")}<button class="btn sm" data-topicdel>×</button></div>`;
}

/* ---------------------------------------------------------------- personal */
function mySettings(body) {
  const locs = [...state.locs.values()].sort((a, b) => a.name.localeCompare(b.name));
  body.innerHTML = `<div class="form">
    <label>You ${info('When ORGX runs on your own workstation it recognizes your Windows sign-in (whoami) and offers this automatically.')}</label><div>${settings.me ? `<b>${esc(settings.me.name)}</b> <button class="btn link" data-p="${attr(settings.me.key)}">open record</button> <button class="btn link" data-unme>not me</button>` : `<span class="muted">Not set.</span>`}
      <div style="position:relative;margin-top:4px"><input class="input" style="width:100%" data-findme placeholder="Find yourself: name or email"><div class="omni-pop hidden" data-mesug style="top:30px"></div></div></div>
    <label>Name on notes</label><input class="input" data-s="myName" value="${attr(settings.myName)}" placeholder="Shown on team notes you edit">
    <label>My unit ${info('Biases POC answers toward your chain and adds an “only my unit” choice.')}</label><div><input class="input" style="width:100%" data-s="homeOrg" value="${attr(settings.homeOrg)}" placeholder="MERIDIAN GROUP/S6"></div>
    <label>My base</label><select class="input" data-s="homeLoc"><option value="">(none)</option>${locs.map((l) => `<option value="${attr(l.id)}" ${settings.homeLoc === l.id ? "selected" : ""}>${esc(l.name)}${l.region ? ", " + esc(l.region) : ""}</option>`).join("")}</select>
    <label>Duty hours</label><div style="display:flex;gap:6px;align-items:center"><input class="input mono" style="width:64px" inputmode="numeric" pattern="[0-2][0-9][0-5][0-9]" maxlength="4" data-s="dutyStart" value="${attr(settings.dutyStart.replace(":", ""))}" aria-label="Duty start, 24-hour"> to <input class="input mono" style="width:64px" inputmode="numeric" pattern="[0-2][0-9][0-5][0-9]" maxlength="4" data-s="dutyEnd" value="${attr(settings.dutyEnd.replace(":", ""))}" aria-label="Duty end, 24-hour">${info("24-hour clock, Monday to Friday, in each person's own local time.")}</div>
    <label>Chat link ${info('Adds a Chat button to each person; {email} is replaced.')}</label><div><input class="input mono" style="width:100%" data-s="chatTemplate" value="${attr(settings.chatTemplate)}" placeholder="https://dod.teams.microsoft.us/l/chat/0/0?users={email}"></div>
    <label>Theme</label><div><span class="seg">${[["light", "Light"], ["dark", "Dark"], ["auto", "Match the system"]].map(([t, l]) => `<button data-theme="${t}" class="${settings.theme === t ? "on" : ""}">${l}</button>`).join("")}</span></div>
  </div><div style="margin-top:14px"><button class="btn primary" data-savesettings>Save</button> ${info("Saved in this browser only.")}</div>`;
  body.querySelector(".seg").onclick = (e) => {
    const b = e.target.closest("[data-theme]");
    if (!b) return;
    save({ theme: b.dataset.theme });
    document.documentElement.dataset.theme = b.dataset.theme;
    body.querySelectorAll("[data-theme]").forEach((x) => x.classList.toggle("on", x === b));
  };
  body.querySelector("[data-unme]")?.addEventListener("click", () => { save({ me: null, meDismissed: true }); render(); });
  const fi = body.querySelector("[data-findme]"), sug = body.querySelector("[data-mesug]");
  fi.addEventListener("input", debounce(async () => {
    if (fi.value.trim().length < 2) return sug.classList.add("hidden");
    const r = await api("/api/search", { q: `${fi.value.trim()} kind:person`, limit: 8 });
    sug.innerHTML = r.rows.map((x) => `<div class="op-it" data-me="${attr(x.key)}" data-name="${attr(plainName(x))}" data-org="${attr(x.org_id || "")}" data-locid="${attr(x.loc_id || "")}"><div class="a">${dirName(x)} ${esc(x.rank || "")}<div class="b">${esc(x.org_id || "")}</div></div></div>`).join("");
    sug.classList.remove("hidden");
  }, 150));
  sug.addEventListener("click", (e) => {
    const it = e.target.closest("[data-me]");
    if (!it) return;
    e.stopPropagation();
    save({ me: { key: it.dataset.me, name: it.dataset.name }, homeOrg: it.dataset.org, homeLoc: it.dataset.locid });
    say(`You are ${esc(it.dataset.name)}`);
    render();
  });
  body.querySelector("[data-savesettings]").onclick = () => {
    const patch = {};
    body.querySelectorAll("[data-s]").forEach((i) => (patch[i.dataset.s] = i.value.trim()));
    save(patch);
    say("Settings saved");
  };
}
