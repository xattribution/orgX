/* Record panel: person / org box / DL / room, office summary, base summary. */
import { $, esc, attr, plainName, copy, say, modal, shortOrg, fmt, icon, info, menu } from "./ui.js";
import { api, post, apiUrl, settings, state, isStarred, toggleStar, pushRecent } from "./store.js";
import { ltHtml, localTime, dateMil, offsetLabel } from "./time.js";
import { openEmailBuilder } from "./email.js";

let el, body, closeFn, current = "";
const KIND = { person: "Person", orgbox: "Org box (shared mailbox)", group: "Distribution list", resource: "Room / equipment", contact: "External contact" };
const EV = { joined: "Appeared in directory", departed: "Left directory", moved: "Moved", promoted: "Promoted", regraded: "Grade changed", retitled: "New title", relocated: "Relocated", contact: "Contact info changed" };
const CAT = { civ: "Civilian", ctr: "Contractor", foreign: "Partner nation" };

export function init({ close }) {
  el = $("#drawer");
  closeFn = close;
}
export function close() {
  el.hidden = true;
  current = "";
}
export async function open(ref) {
  current = ref;
  el.hidden = false;
  const [type, ...rest] = ref.split(":");
  const id = rest.join(":");
  el.innerHTML = `<div class="dr-top"><span class="sp"></span><button class="btn sm icon quiet" data-close aria-label="Close" title="Close (Esc)">${icon("x")}</button></div><div class="dr-body"><div class="loading">Loading…</div></div>`;
  el.querySelector("[data-close]").onclick = closeFn;
  try {
    if (type === "p") await person(id);
    else if (type === "o") await office(id);
    else if (type === "l") await base(id);
  } catch (e) {
    if (current === ref) el.querySelector(".dr-body").innerHTML = `<div class="empty"><b>Couldn't load this record</b>${esc(e.message)}</div>`;
  }
}
function frame(kind, html) {
  el.innerHTML = `<div class="dr-top"><span>${esc(kind)}</span><span class="sp"></span><button class="btn sm icon quiet" data-close aria-label="Close" title="Close (Esc)">${icon("x")}</button></div><div class="dr-body card">${html}</div>`;
  el.querySelector("[data-close]").onclick = closeFn;
  body = el.querySelector(".dr-body");
}
const pi = (p, right = "", kind = "person") =>
  `<div class="pi" data-p="${attr(p.key)}"><div class="a ellip">${esc(p.name)}${p.rank && kind === "person" ? ` <span class="rk">${esc(p.rank)}</span>` : ""}</div>${right !== null ? `<div class="c">${right}</div>` : ""}<div class="b ellip">${esc(p.title || p.email || "")}</div></div>`;
const orgPath = (id) => id ? `<div class="path">${id.split("/").map((p, i, a) => `<a data-org="${attr(a.slice(0, i + 1).join("/"))}">${esc(p)}</a>`).join('<span class="sep">/</span>')}</div>` : "";
const sec = (title, body, { n = "", right = "" } = {}) => `<section class="card-sec"><h3>${title}${n !== "" ? ` <span class="n">${n}</span>` : ""}${right ? `<span class="r">${right}</span>` : ""}</h3>${body}</section>`;
const stripCell = (label, value, copyLabel, cls = "") => value
  ? `<button type="button" data-copy="${attr(value)}" data-copy-label="${attr(copyLabel)}" title="Copy"><span class="k">${esc(label)} ${icon("copy")}</span><span class="v ${cls}">${esc(value)}</span></button>` : "";

/* ---------------------------------------------------------------- person and mailboxes */
async function person(key) {
  const o = await api("/api/object", { key });
  if (o.error) throw new Error(o.error);
  if (current !== "p:" + key) return;
  pushRecent(o);
  const lt = localTime(o.tz);
  const starred = isStarred(o.key);
  const chat = settings.chatTemplate && o.email ? settings.chatTemplate.replace("{email}", encodeURIComponent(o.email)) : "";
  const sig = () => copy([plainName(o).toUpperCase(), [o.rank, o.service].filter(Boolean).join(", "), o.title, o.org_id,
    o.dsn ? `DSN ${o.dsn}` : "", o.phone ? `Comm ${o.phone}` : "", o.email].filter(Boolean).join("\n"), "Copied signature block");
  const latest = state.meta?.latest?.id;
  const recent = new Set(o.history.filter((h) => h.snap === latest).map((h) => h.type));
  const flags = [
    CAT[o.category] ? `<span class="flag plain">${CAT[o.category]}</span>` : "",
    o.fn ? `<span class="flag plain">${esc(state.fnLabel[o.fn] || o.fn)}</span>` : "",
    recent.has("joined") ? `<span class="flag ok">New since last update</span>` : "",
    recent.has("moved") ? `<span class="flag caution">Moved since last update</span>` : "",
    recent.has("promoted") ? `<span class="flag ok">Promoted</span>` : "",
    o.disabled ? `<span class="flag bad">Account disabled</span>` : "",
    o.hidden ? `<span class="flag plain">Hidden from the GAL</span>` : "",
    ...(o.note?.tags || []).map((t) => `<a class="flag info" data-q="tag:${attr(t)}">#${esc(t)}</a>`),
  ].join("");
  const strip = [
    stripCell("Email", o.email, `Copied ${o.email}`),
    stripCell("DSN", o.dsn, `Copied DSN ${o.dsn}`, "ph"),
    stripCell("Commercial", o.phone, `Copied ${o.phone}`, "ph"),
    !o.dsn || !o.phone ? stripCell("Mobile", o.mobile, `Copied ${o.mobile}`, "ph") : "",
  ].join("");
  const rows = [
    o.mobile && o.dsn && o.phone ? `<dt>Mobile</dt><dd class="ph" data-copy="${attr(o.mobile)}" style="cursor:copy">${esc(o.mobile)}</dd>` : "",
    o.loc_id ? `<dt>Base</dt><dd><a data-loc="${attr(o.loc_id)}">${esc(o.loc_full || o.loc_name)}</a>${o.loc_approx ? ` <span class="flag caution" title="Placed at a state or country centroid">approximate</span>` : ""}</dd>` : "",
    lt ? `<dt>Local time</dt><dd>${ltHtml(o.tz, { long: true })} <span class="muted">UTC${offsetLabel(lt.off)}</span></dd>` : "",
    o.office ? `<dt>Office</dt><dd>${esc(o.office)}</dd>` : "",
    o.career ? `<dt>AFSC</dt><dd><a data-q="afsc:${attr(o.career)}">${esc(o.career)}</a></dd>` : "",
    o.grade && o.grade !== o.rank ? `<dt>Grade</dt><dd>${esc(o.grade)}</dd>` : "",
    o.first_seen ? `<dt>In the directory since</dt><dd>${esc(dateMil(o.first_seen))}</dd>` : "",
  ].join("");
  let h = `<div class="card-head"><h2>${o.kind === "person" && o.rank ? `<span class="rk">${esc(o.rank)}</span>` : ""}${esc(o.name)}</h2>
      ${o.title ? `<div class="ti">${esc(o.title)}</div>` : ""}${orgPath(o.org_id)}<div class="flags">${flags}</div></div>
    <div class="actions-row">
      ${o.email ? `<a class="btn primary" href="mailto:${attr(o.email)}">${icon("mail")} Email</a>` : ""}
      ${chat ? `<a class="btn" href="${attr(chat)}" target="_blank" rel="noopener">${icon("chat")} Chat</a>` : ""}
      <button class="btn icon${starred ? " is-on" : ""}" data-act="star" aria-pressed="${starred}" aria-label="Star" title="${starred ? "Starred" : "Star"}">${icon(starred ? "starf" : "star")}</button>
      <button class="btn" data-act="group">Add to group</button>
      <button class="btn icon" data-act="more" aria-label="More" title="More">${icon("more")}</button>
    </div>
    ${strip ? `<div class="strip">${strip}</div>` : ""}
    <dl class="dl">${rows}</dl>`;
  if (lt && lt.status !== "on" && o.kind === "person") {
    h += `<div class="callout">It's ${lt.time}${esc(lt.letter)} there, ${esc(lt.word === "wknd" ? "the weekend" : lt.word === "edge" ? "just outside duty hours" : lt.word === "night" ? "night" : "off duty")}.${o.orgboxes?.length ? ` Try the office box: <a href="mailto:${attr(o.orgboxes[0].email)}">${esc(o.orgboxes[0].email)}</a>` : ""}</div>`;
  }
  const orgShort = (id) => esc(shortOrg(id).a);
  if (o.kind === "group") {
    h += sec("Members", `${o.owner ? `<div class="pi" ${o.owner.key ? `data-p="${attr(o.owner.key)}"` : ""}><div class="a">${esc(plainName({ ...o.owner, kind: "person" }))}</div><div class="b">Owner</div></div>` : ""}
      <div class="plist">${o.members.slice(0, 60).map((m) => pi(m, orgShort(m.org_id), m.kind)).join("")}</div>
      ${o.member_count > 60 ? `<p><a data-q="member:${attr(o.key)}">${fmt(o.member_count - 60)} more</a></p>` : ""}`,
      { n: fmt(o.member_count), right: `<a data-q="member:${attr(o.key)}">Show all</a><a data-act="dl-email">Email list</a>` });
  }
  if (o.managers?.length) {
    h += sec("Reports to", `<div class="plist chain">${o.managers.slice(0, 6).map((m) => pi(m, orgShort(m.org_id))).join("")}</div>`);
  } else if (o.org_chain?.length && o.kind === "person") {
    const leads = o.org_chain.filter((c) => c.leader_key && c.leader_key !== o.key).slice(-4).reverse();
    if (leads.length) h += sec("Leadership above",
      `<div class="plist chain">${leads.map((c) => pi({ key: c.leader_key, name: c.leader_name, rank: c.leader_rank, title: c.leader_title }, esc(c.name))).join("")}</div>`);
  }
  if (o.reports?.length) {
    h += sec("Direct reports", `<div class="plist">${o.reports.slice(0, 25).map((r) => pi(r, r.n ? `${r.n} under` : "", r.kind)).join("")}</div>`,
      { n: o.reports.length, right: o.rollup > o.reports.length ? `<a data-q="under:${attr(o.key)}">Everyone under them (${fmt(o.rollup)})</a>` : "" });
  }
  if (o.orgboxes?.length && o.kind === "person") {
    h += sec("Office mailbox", `<div class="plist">${o.orgboxes.map((b) => `<div class="pi" data-p="${attr(b.key)}"><div class="a ellip">${esc(b.email || b.name)}</div><div class="c"><button class="btn sm icon quiet" data-copy="${attr(b.email)}" data-copy-label="Copied ${attr(b.email)}" aria-label="Copy">${icon("copy")}</button></div><div class="b ellip">${esc(b.name)}</div></div>`).join("")}</div>`);
  }
  if (o.peers?.length) {
    h += sec("Same office", `<div class="plist">${o.peers.slice(0, 8).map((p) => pi(p, null)).join("")}</div>`,
      { n: `${o.peers.length}${o.peers.length >= 40 ? "+" : ""}`, right: `<a data-q='org:"${attr(o.org_id)}!"'>Show all</a>` });
  }
  if (o.groups?.length) {
    h += sec("Distribution lists", `<div class="plist">${o.groups.slice(0, 12).map((g) => pi({ ...g, title: g.email }, `${fmt(g.n)} members`, "group")).join("")}</div>`, { n: o.groups.length });
  }
  if (o.lists?.length) h += sec("Groups", `<div class="plist">${o.lists.map((l) => `<div class="pi" data-go="#/groups/${l.id}"><div class="a">${esc(l.name)}</div></div>`).join("")}</div>`);
  if (o.history?.length) {
    h += sec("History", o.history.slice(0, 20).map((e) => `<div class="tl"><span class="when">${esc(dateMil(e.taken_at))}</span><div><b>${esc(EV[e.type] || e.type)}</b>${e.before || e.after ? `<div class="dim">${esc(e.before || "none")} to ${esc(e.after || "none")}</div>` : ""}</div></div>`).join(""));
  }
  const n = o.note || { notes: "", tags: [], contact_for: [] };
  h += sec(`Team notes ${info("Shared with everyone who uses this ORGX server, and kept when the directory updates.")}`, `
    <div style="display:flex;flex-direction:column;gap:8px">
      <label><b>Go-to for</b> ${info("Topics this person handles. Questions such as “who handles the spring exercise?” answer with them first.")}</label>
      ${tagInput("cf", n.contact_for, "Spring exercise, tokens, Annex N")}
      <label><b>Tags</b></label>${tagInput("tg", n.tags, "Add a tag")}
      <textarea class="input" rows="3" data-notes placeholder="Prefers Teams. Covers S62 when the chief is TDY.">${esc(n.notes)}</textarea>
      <div style="display:flex;gap:10px;align-items:center"><button class="btn sm primary" data-act="save-notes">Save notes</button><span class="note" data-saved>${n.updated_at ? `Edited ${esc(dateMil(n.updated_at))}${n.updated_by ? " by " + esc(n.updated_by) : ""}` : ""}</span></div>
    </div>`, { n: "" });
  const attrs = [["Key", o.key], ["DN", o.dn], ["OU path", o.ou_path], ["Domain", o.domain], ["UPN", o.upn], ["SAM", o.sam], ["Display", o.display],
    ["Department", o.dept], ["Region OU", o.region], ["Country", o.country], ...Object.entries(o.extra || {})].filter(([, v]) => v);
  h += `<details class="more"><summary>All directory fields</summary><dl class="attrs">${attrs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></details>`;
  frame(o.kind === "person" ? "" : KIND[o.kind] || "Record", h);
  wireTags(body);
  body.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]"), act = btn?.dataset.act;
    if (act === "star") {
      const on = toggleStar(o);
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-pressed", on);
      btn.title = on ? "Starred" : "Star";
      btn.innerHTML = icon(on ? "starf" : "star");
    }
    if (act === "more") menu(btn, [
      { label: "Copy signature block", run: () => sig() },
      { label: "Download vCard", href: apiUrl("/api/export", { keys: o.key, format: "vcf" }), download: true },
      ...(o.org_id ? [{ label: `Open ${o.org_id}`, run: () => (location.hash = `#/org/${encodeURIComponent(o.org_id)}`) }] : []),
      { label: "Show everyone under them", run: () => (location.hash = `#/dir?q=${encodeURIComponent("under:" + o.key)}`) },
    ]);
    if (act === "group") addToGroup([o.key]);
    if (act === "dl-email") openEmailBuilder({ q: `member:${o.key}`, label: `members of ${o.name}` });

    if (act === "save-notes") {
      await post("/api/note", { key: o.key, notes: body.querySelector("[data-notes]").value, tags: readTags(body, "tg"), contact_for: readTags(body, "cf"), by: settings.myName || settings.me?.name || "" });
      const t = new Date();
      body.querySelector("[data-saved]").textContent = `Saved ${String(t.getHours()).padStart(2, "0")}${String(t.getMinutes()).padStart(2, "0")}`;
    }
  });
}

function tagInput(name, vals, ph) {
  return `<div class="taginput" data-tags="${name}">${(vals || []).map(tagTok).join("")}<input placeholder="${attr(ph)}" ${name === "cf" ? 'list="topic-dl"' : ""}></div>
    ${name === "cf" ? `<datalist id="topic-dl">${state.topics.slice(0, 200).map((t) => `<option value="${attr(t.label)}">`).join("")}</datalist>` : ""}`;
}
const tagTok = (v) => `<span class="tok" data-v="${attr(v)}">${esc(v)}<span class="x" data-rm title="Remove">×</span></span>`;
function wireTags(root) {
  root.querySelectorAll("[data-tags]").forEach((box) => {
    const inp = box.querySelector("input");
    const add = () => {
      const v = inp.value.trim().replace(/,$/, "");
      if (v && ![...box.querySelectorAll("[data-v]")].some((c) => c.dataset.v.toLowerCase() === v.toLowerCase())) inp.insertAdjacentHTML("beforebegin", tagTok(v));
      inp.value = "";
    };
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
      if (e.key === "Backspace" && !inp.value) [...box.querySelectorAll("[data-v]")].pop()?.remove();
    });
    inp.addEventListener("blur", add);
    box.addEventListener("click", (e) => { e.target.closest("[data-rm]") ? e.target.closest("[data-v]").remove() : inp.focus(); });
  });
}
const readTags = (root, name) => [...root.querySelectorAll(`[data-tags="${name}"] [data-v]`)].map((c) => c.dataset.v);

export async function addToGroup(keys) {
  const gs = (await api("/api/groups")).filter((g) => g.kind !== "smart");
  modal({
    title: `Add ${keys.length === 1 ? "this record" : keys.length + " records"} to a group`,
    body: `<label><b>Group</b></label><select class="input" data-g>${gs.map((g) => `<option value="${g.id}">${esc(g.name)} (${g.n})</option>`).join("")}<option value="new">New group…</option></select>
      <div data-newbox ${gs.length ? "hidden" : ""}><label><b>Name</b></label><input class="input" style="width:100%" data-n placeholder="KS27 bilateral planning cell"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div><label><b>Role</b> <span class="note">optional</span></label><input class="input" style="width:100%" data-role placeholder="Lead planner"></div>
      <div><label><b>Section</b> <span class="note">optional</span></label><input class="input" style="width:100%" data-sec placeholder="White cell"></div></div>`,
    onMount: (m) => {
      const s = m.querySelector("[data-g]");
      if (!gs.length) s.value = "new";
      s.onchange = () => { m.querySelector("[data-newbox]").hidden = s.value !== "new"; };
    },
    actions: [{ label: "Cancel" }, {
      label: "Add", primary: true, run: async (m) => {
        const v = m.querySelector("[data-g]").value;
        const role = m.querySelector("[data-role]").value.trim(), section = m.querySelector("[data-sec]").value.trim();
        const r = await post("/api/group", v === "new" ? { name: m.querySelector("[data-n]").value || "New group", add: keys, by: settings.me?.name || "" } : { id: +v, add: keys });
        if (role || section) await post("/api/group", { id: r.id, update: keys.map((k) => ({ key: k, role, section })) });
        say(`Added to group. <a href="#/groups/${r.id}">Open it</a>`);
      },
    }],
  });
}

/* ---------------------------------------------------------------- office summary */
async function office(id) {
  const o = await api("/api/org", { id });
  if (o.error) throw new Error(o.error);
  if (current !== "o:" + id) return;
  const tot = Object.values(o.by_cat).reduce((a, b) => a + b, 0) || 1;
  const cat = [["mil", "Military"], ["civ", "Civilian"], ["ctr", "Contractor"], ["foreign", "Partner"], ["", "Unknown"]].filter(([k]) => o.by_cat[k]);
  let h = `<div class="card-head"><h2>${esc(o.id)}</h2>
      ${o.chain.length ? `<div class="path">${o.chain.map((c) => `<a data-org="${attr(c.id)}">${esc(c.name)}</a>`).join('<span class="sep">›</span>')}<span class="sep">›</span>${esc(o.name)}${o.inferred ? info(`Parent inferred from ${o.inferred}.`) : ""}</div>` : ""}</div>
    <p class="factline" style="margin-top:10px"><b>${fmt(o.people)}</b> people, <b>${o.children.length}</b> sub-offices${o.by_loc.length ? `, <b>${o.by_loc.length}</b> base${o.by_loc.length === 1 ? "" : "s"}` : ""}</p>
    <div class="actions-row"><button class="btn primary" data-org="${attr(o.id)}" data-org-go>Open the office</button>
      <button class="btn" data-q='org:"${attr(o.id)}"'>List everyone</button><button class="btn" data-act="email">Email list</button></div>`;
  if (o.orgboxes.length) h += `<div class="strip">${o.orgboxes.slice(0, 2).map((b) => stripCell(b.name, b.email, `Copied ${b.email}`)).join("")}</div>`;
  if (o.leader) h += sec("Lead", `<div class="plist">${pi(o.leader, null)}</div>`);
  h += sec("Who's in it", `<div class="bars">${cat.map(([k, l]) => `<span>${l}</span><span class="t"><span style="width:${(o.by_cat[k] / tot) * 100}%"></span></span><span class="r">${o.by_cat[k]}</span>`).join("")}</div>`);
  if (o.by_loc.length) h += sec("Bases", `<div class="plist">${o.by_loc.slice(0, 6).map((l) => `<div class="pi" data-loc="${attr(l.id || "")}"><div class="a">${esc(l.name || "Unplaced")}</div><div class="c">${fmt(l.n)}</div><div class="b">${ltHtml(l.tz)}</div></div>`).join("")}</div>`);
  if (o.children.length) h += sec("Sub-offices", `<div class="plist">${o.children.slice(0, 16).map((c) => `<div class="pi" data-org="${attr(c.id)}"><div class="a">${esc(c.name)}</div><div class="c">${fmt(c.people)}</div><div class="b ellip">${c.leader_name ? esc((c.leader_rank || "") + " " + c.leader_name) : "No lead identified"}</div></div>`).join("")}</div>`, { n: o.children.length });
  frame("", h);
  body.querySelector("[data-act=email]").onclick = () => openEmailBuilder({ q: `org:"${o.id}"`, label: `everyone in ${o.id}` });
}

/* ---------------------------------------------------------------- base summary */
async function base(id) {
  const l = await api("/api/location", { id });
  if (l.error) throw new Error(l.error);
  if (current !== "l:" + id) return;
  const lt = localTime(l.tz);
  const fns = Object.entries(l.by_fn).filter(([k]) => k).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...fns.map(([, n]) => n));
  let h = `<div class="card-head"><h2>${esc(l.name)}</h2><div class="ti">${esc(l.full || "")}${l.region ? `, <a data-q="region:${attr(l.region)}">${esc(l.region)}</a>` : ""}</div></div>
    <dl class="dl" style="margin-top:14px">${lt ? `<dt>Local time</dt><dd>${ltHtml(l.tz, { long: true })} <span class="muted">UTC${offsetLabel(lt.off)}</span></dd>` : ""}
    <dt>In the directory</dt><dd>${fmt(l.people)} people, ${fmt(l.total)} records</dd>
    ${l.approx ? `<dt>Position</dt><dd><span class="flag caution">Approximate</span>${info("Placed at the state or country center. Add the site to data/sites.json for an exact position.")}</dd>` : ""}</dl>
    <div class="actions-row"><button class="btn primary" data-q='base:"${attr(l.id)}"'>List everyone here</button><button class="btn" data-q='base:"${attr(l.id)}" is:leader'>Leaders here</button></div>`;
  if (l.leaders.length) h += sec("Leaders on site", `<div class="plist">${l.leaders.map((p) => pi(p, esc(shortOrg(p.org_id).a))).join("")}</div>`);
  if (l.units.length) h += sec("Units here", `<div class="plist">${l.units.map((u) => `<div class="pi" data-org="${attr(u.id)}"><div class="a">${esc(u.id)}</div><div class="c">${fmt(u.n)}</div><div class="b">${u.parent ? "Under " + esc(u.parent) : ""}</div></div>`).join("")}</div>`, { n: l.units.length });
  if (fns.length) h += sec("By function", `<div class="bars">${fns.slice(0, 8).map(([k, n]) => `<span>${esc(state.fnLabel[k] || k)}</span><span class="t"><span style="width:${(n / max) * 100}%"></span></span><span class="r">${n}</span>`).join("")}</div>`);
  if (l.orgboxes.length) h += sec("Office mailboxes", `<div class="plist">${l.orgboxes.slice(0, 10).map((b) => pi({ ...b, title: b.email }, null, "orgbox")).join("")}</div>`, { n: l.orgboxes.length });
  if (l.resources.length) h += sec("Rooms and equipment", `<div class="plist">${l.resources.map((b) => pi({ ...b, title: b.email }, null, "resource")).join("")}</div>`);
  if (l.ous.length) h += `<details class="more"><summary>Active Directory containers</summary><dl class="attrs">${l.ous.map((x) => `<dt>${fmt(x.n)}</dt><dd>${esc(x.ou || "(none)")}</dd>`).join("")}</dl></details>`;
  frame("", h);
}
