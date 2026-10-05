/* Time: clock board for every base, meeting planner across sites, clock-wall setup. */
import { $, esc, attr, fmt, copy, say, info } from "../ui.js";
import { api, settings, save, state } from "../store.js";
import { localTime, offsetLabel, dtg, dateMil } from "../time.js";
import { setParams, clockSites } from "../app.js";

let root, params, timer;

export default {
  id: "time", label: "Time", key: "t",
  mount(el, r) { root = el; params = r.params; render(); timer = setInterval(() => { if (!document.querySelector("#view input:focus")) renderBoard(); }, 30_000); },
  update(r) { params = r.params; render(); },
  unmount() { clearInterval(timer); },
};

const allSites = () => [...state.locs.values()].filter((l) => l.tz).sort((a, b) => (localTime(a.tz)?.off ?? 0) - (localTime(b.tz)?.off ?? 0) || (b.np || 0) - (a.np || 0));

function planSites() {
  const ids = (params.get("sites") || "").split(",").filter(Boolean);
  if (ids.length) return ids.map((id) => state.locs.get(id)).filter(Boolean);
  return clockSites().filter((l) => state.locs.has(l.id)).slice(0, 5);
}

async function render() {
  const groups = (await api("/api/groups").catch(() => [])).filter((g) => g.kind !== "smart");
  root.innerHTML = `<div class="page">
    <div class="toolbar">
      <span class="seg" id="tday"><button data-dd="-1" aria-label="Previous day">‹</button><button data-dd="0" title="Back to today">${esc(dateMil(params.get("day") || new Date().toISOString().slice(0, 10)))}</button><button data-dd="1" aria-label="Next day">›</button></span>
      ${info(`Click an hour to propose a time with every site's local time, ready to paste into an invite. Zone letters follow ACP 121 and change with daylight saving. Duty hours are ${settings.dutyStart.replace(":", "")} to ${settings.dutyEnd.replace(":", "")} local, Monday to Friday.`, "About the planner")}
      <span class="sp"></span>
      <select class="input" id="tgroup" aria-label="Plan for a group's bases"><option value="">Bases from a group</option>${groups.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}</select></div>
    <div id="planner"></div><div id="proposal" style="margin-top:8px"></div>
    <h2 class="h">Clocks<span class="r"><button class="btn sm quiet" id="tauto">Reset to automatic</button></span></h2>
    <div id="board"></div></div>`;
  $("#tday", root).onclick = (e) => {
    const b = e.target.closest("[data-dd]");
    if (!b) return;
    const d = new Date(`${params.get("day") || new Date().toISOString().slice(0, 10)}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + +b.dataset.dd);
    setParams({ day: +b.dataset.dd ? d.toISOString().slice(0, 10) : "", h: "" });
  };
  $("#tgroup", root).onchange = async (e) => {
    if (!e.target.value) return;
    const g = await api("/api/group", { id: e.target.value });
    const ids = [...new Set(g.members.map((m) => m.live?.loc_id).filter(Boolean))];
    setParams({ sites: ids.join(",") });
    say(`Planner set to the ${ids.length} bases where members of ${esc(g.name)} are`);
  };
  $("#tauto", root).onclick = () => { save({ clockSites: [] }); renderBoard(); say("Clock wall set to automatic: your base, then the largest sites"); };
  renderPlanner();
  renderBoard();
}

function renderBoard() {
  const wall = new Set(settings.clockSites?.length ? settings.clockSites : clockSites().map((l) => l.id));
  const plan = new Set(planSites().map((l) => l.id));
  const host = $("#board", root);
  if (!host) return;
  host.innerHTML = `<table class="tbl board"><thead><tr><th>Clock</th><th>Planner</th><th>Base</th><th>Region</th><th>Zone</th><th>Local</th><th>Day</th><th>Status</th><th class="num">People</th></tr></thead><tbody>
    ${allSites().map((l) => {
      const lt = localTime(l.tz);
      return `<tr><td><input type="checkbox" data-wall="${attr(l.id)}" ${wall.has(l.id) ? "checked" : ""} aria-label="Show on clock wall"></td>
        <td><input type="checkbox" data-plan="${attr(l.id)}" ${plan.has(l.id) ? "checked" : ""} aria-label="Include in planner"></td>
        <td><a data-loc="${attr(l.id)}">${esc(l.name)}</a></td><td class="dim">${esc(l.region || l.country || "")}</td>
        <td>${esc(lt.letter || "–")} <span class="muted">UTC${offsetLabel(lt.off)}</span></td><td class="big">${lt.time}${esc(lt.letter)}</td>
        <td>${esc(lt.wd)}${lt.day ? ` <b>${lt.day > 0 ? "+1" : "−1"}</b>` : ""}</td><td><span class="lt ${lt.status}"><i>${esc({ on: "duty hours", edge: "edge of day", off: "off duty", night: "night" }[lt.status])}${lt.word === "wknd" ? ", weekend" : ""}</i></span></td>
        <td class="num">${fmt(l.np || 0)}</td></tr>`;
    }).join("")}</tbody></table>`;
  host.onchange = (e) => {
    const w = e.target.closest("[data-wall]"), p = e.target.closest("[data-plan]");
    if (w) {
      const cur = new Set(settings.clockSites?.length ? settings.clockSites : clockSites().map((l) => l.id));
      w.checked ? cur.add(w.dataset.wall) : cur.delete(w.dataset.wall);
      save({ clockSites: [...cur] });
      say("Clock wall updated");
    }
    if (p) {
      const cur = new Set(planSites().map((l) => l.id));
      p.checked ? cur.add(p.dataset.plan) : cur.delete(p.dataset.plan);
      setParams({ sites: [...cur].join(",") });
    }
  };
}

function renderPlanner() {
  const sites = planSites();
  const host = $("#planner", root);
  if (!sites.length) { host.innerHTML = `<p class="note">Tick Planner on a base below.</p>`; return; }
  const day = params.get("day") || new Date().toISOString().slice(0, 10);
  const at = (h) => new Date(`${day}T${String(h).padStart(2, "0")}:00:00Z`);
  const pick = params.get("h") ?? "";
  const cells = sites.map((l) => Array.from({ length: 24 }, (_, h) => localTime(l.tz, at(h))));
  const onDuty = Array.from({ length: 24 }, (_, h) => cells.filter((row) => row[h].status === "on").length);
  host.innerHTML = `<div class="planner">
    <div class="pr hd"><div class="lab">UTC (Z)</div>${Array.from({ length: 24 }, (_, h) => `<div class="click${String(h) === pick ? " pick" : ""}" data-h="${h}" title="Propose ${String(h).padStart(2, "0")}00Z">${String(h).padStart(2, "0")}</div>`).join("")}</div>
    ${sites.map((l, i) => `<div class="pr"><div class="lab" title="${attr(l.tz)}"><b>${esc(l.name)}</b> <span class="muted">${esc(cells[i][0].letter || offsetLabel(cells[i][0].off))}</span></div>
      ${cells[i].map((c, h) => `<div class="${c.status === "on" ? "duty" : c.status === "edge" ? "edge" : c.status === "night" ? "nite" : ""}${String(h) === pick ? " pick" : ""}" title="${esc(l.name)} ${c.time}${esc(c.letter)} ${c.wd}">${c.time.slice(0, 2)}</div>`).join("")}</div>`).join("")}
    <div class="pr"><div class="lab">Sites in duty hours</div>${onDuty.map((n, h) => `<div class="${n === sites.length ? "all" : ""}${String(h) === pick ? " pick" : ""}">${n}</div>`).join("")}</div>
  </div>`;
  host.querySelector(".hd").onclick = (e) => { const c = e.target.closest("[data-h]"); if (c) setParams({ h: c.dataset.h }); };
  if (pick !== "") {
    const t = at(+pick);
    const lines = sites.map((l, i) => { const c = cells[i][+pick]; return `${l.name} ${c.time}${c.letter || ""}${c.day ? (c.day > 0 ? " (+1 day)" : " (−1 day)") : ""} ${c.wd}, ${({ on: "duty hours", edge: "edge of day", off: "off duty", night: "night" })[c.status]}`; });
    const text = `Proposed: ${dtg(t)}\n${lines.join("\n")}`;
    $("#proposal", root).innerHTML = `<table class="tbl" style="max-width:720px"><thead><tr><th colspan="2">Proposed ${esc(dtg(t))} <button class="btn link" data-cp>copy for an invite</button></th></tr></thead><tbody>
      ${lines.map((x) => `<tr><td class="mono">${esc(x)}</td></tr>`).join("")}</tbody></table>`;
    $("#proposal", root).querySelector("[data-cp]").onclick = () => copy(text, `Copied proposal for ${dtg(t)}`);
  }
}
