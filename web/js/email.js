/* Email list builder: any filter / selection / group / DL → paste-ready recipient lists. */
import { esc, attr, copy, modal, saveText, fmt, say, info } from "./ui.js";
import { api, settings } from "./store.js";

const PREFS = "orgx.emailPrefs";
function prefs() {
  try { return { pick: "all", exclude: "", style: "plain", sep: ";", batch: "0", field: "bcc", ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; }
  catch { return { pick: "all", exclude: "", style: "plain", sep: ";", batch: "0", field: "bcc" }; }
}

/** source: {q} | {keys:[...]} | {group:id}; label describes it in the dialog title */
export function openEmailBuilder(source) {
  const p = prefs();
  const radio = (name, val, label, help = "") => `<label class="chk"><input type="radio" name="${name}" value="${val}" ${p[name] === val ? "checked" : ""}>${label}${help ? info(help) : ""}</label>`;
  modal({
    title: `Email list: ${source.label || "current filter"}`,
    wide: true,
    body: `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px 18px">
        <div><b>Who</b>
          ${radio("pick", "all", "Everyone")}
          ${radio("pick", "leaders", "Leaders only", "Commanders, directors and chiefs.")}
          ${radio("pick", "shop", "One per office", "The office mailbox, or its lead when there is none.")}
          <div style="margin-top:6px"><b>Leave out</b></div>
          <label class="chk"><input type="checkbox" data-ex="ctr" ${p.exclude.includes("ctr") ? "checked" : ""}>Contractors</label>
          <label class="chk"><input type="checkbox" data-ex="civ" ${p.exclude.includes("civ") ? "checked" : ""}>Civilians</label>
          <label class="chk"><input type="checkbox" data-ex="foreign" ${p.exclude.includes("foreign") ? "checked" : ""}>Partner-nation accounts</label></div>
        <div><b>Format</b>
          ${radio("style", "plain", "Addresses only")}
          ${radio("style", "named", "Name &lt;address&gt;")}
          <div style="margin-top:6px"><b>Separator</b></div>
          ${radio("sep", ";", "Semicolon (Outlook)")}${radio("sep", ",", "Comma (most other clients)")}${radio("sep", "nl", "One per line")}</div>
        <div><b>Field for the mail link</b>
          ${radio("field", "bcc", "Bcc", "Use Bcc for large lists so replies don't go to everyone.")}${radio("field", "to", "To")}${radio("field", "cc", "Cc")}
          <div style="margin-top:6px"><b>Split into batches of</b></div>
          <select class="input" data-batch>${["0", "50", "100", "250", "500"].map((b) => `<option value="${b}" ${p.batch === b ? "selected" : ""}>${b === "0" ? "One list" : b}</option>`).join("")}</select></div>
      </div>
      <div data-out><div class="loading">Building the list…</div></div>`,
    onMount: (m) => {
      const build = async () => {
        const opts = {
          pick: m.querySelector("[name=pick]:checked").value,
          style: m.querySelector("[name=style]:checked").value,
          sep: m.querySelector("[name=sep]:checked").value,
          field: m.querySelector("[name=field]:checked").value,
          batch: m.querySelector("[data-batch]").value,
          exclude: [...m.querySelectorAll("[data-ex]:checked")].map((c) => c.dataset.ex).join(","),
        };
        try { localStorage.setItem(PREFS, JSON.stringify(opts)); } catch { /* private mode */ }
        const src = source.group ? { group: source.group } : source.keys ? { keys: source.keys.join(",") } : { q: source.q || "" };
        const r = await api("/api/emails", { ...src, ...opts });
        const out = m.querySelector("[data-out]");
        if (r.error) { out.innerHTML = `<p class="note">${esc(r.error)}</p>`; return; }
        const skipped = [r.skipped.no_email && `${fmt(r.skipped.no_email)} have no email`, r.skipped.excluded && `${fmt(r.skipped.excluded)} left out by category`, r.skipped.disabled && `${fmt(r.skipped.disabled)} disabled accounts`].filter(Boolean);
        out.innerHTML = `<p class="factline"><b>${fmt(r.count)}</b> addresses${r.batches.length > 1 ? ` in ${r.batches.length} batches` : ""}.${skipped.length ? ` ${skipped.join(", ")}.` : ""}</p>
          ${r.batches.map((b, i) => `<div style="margin-top:6px"><div style="display:flex;gap:6px;align-items:center;margin-bottom:3px">
              <b>${r.batches.length > 1 ? `Batch ${i + 1}` : "List"}</b><span class="note">${b.n} addresses</span><span style="flex:1"></span>
              <button class="btn sm" data-copy-batch="${i}">Copy</button>
              ${b.mailto_ok ? `<a class="btn sm" href="${attr(b.mailto)}">Open in mail (${opts.field})</a>` : `<span class="note">Too long for a mail link; copy and paste instead</span>`}</div>
            <textarea class="input outbox" readonly rows="${Math.min(6, 2 + Math.ceil(b.text.length / 160))}">${esc(b.text)}</textarea></div>`).join("")}
          <div style="display:flex;gap:6px;margin-top:8px"><button class="btn sm" data-txt>Save as .txt</button><button class="btn sm" data-csv>Save for Outlook contacts (.csv)</button></div>`;
        out.onclick = (e) => {
          const cb = e.target.closest("[data-copy-batch]");
          if (cb) copy(r.batches[+cb.dataset.copyBatch].text, `Copied ${r.batches[+cb.dataset.copyBatch].n} addresses`);
          if (e.target.closest("[data-txt]")) saveText(r.batches.map((b) => b.text).join("\n\n"), "recipients.txt");
          if (e.target.closest("[data-csv]")) {
            const rows = [["Name", "E-mail Address", "Company"], ...r.recipients.map((x) => [x.kind === "person" && x.rank ? `${x.rank} ${x.name}` : x.name, x.email, x.org])];
            saveText(rows.map((row) => row.map((c) => `"${String(c || "").replace(/"/g, '""')}"`).join(",")).join("\r\n"), "recipients.csv", "text/csv");
            say("Saved recipients.csv. In Outlook: File, Open and Export, Import from a file, Comma separated values");
          }
        };
      };
      m.querySelector(".mb").addEventListener("change", (e) => { if (!e.target.closest("[data-out]")) build(); });
      build();
    },
    actions: [{ label: "Done", primary: true }],
  });
}
