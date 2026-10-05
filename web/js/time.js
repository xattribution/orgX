/* Zulu, DTGs, military zone letters, duty status at a location. */
import { settings } from "./store.js";
import { esc } from "./ui.js";

const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const fmtCache = new Map();

function parts(tz, d = new Date()) {
  let f = fmtCache.get(tz);
  if (f === undefined) {
    try {
      f = new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short", hourCycle: "h23" });
    } catch {
      f = null;
    }
    fmtCache.set(tz, f);
  }
  if (!f) return null;
  const o = {};
  for (const p of f.formatToParts(d)) o[p.type] = p.value;
  return { y: +o.year, mo: +o.month, d: +o.day, h: +o.hour, m: +o.minute, wd: o.weekday };
}

/** minutes east of UTC for a zone right now (DST-aware) */
export function offsetMin(tz, d = new Date()) {
  const p = parts(tz, d);
  if (!p) return 0;
  const asUtc = Date.UTC(p.y, p.mo - 1, p.d, p.h, p.m);
  return Math.round((asUtc - Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes())) / 60000);
}

/** ACP 121 zone letter for a whole-hour offset; "" for half-hour zones or beyond ±12 */
export function zoneLetter(min) {
  if (min % 60 !== 0) return "";
  const h = min / 60;
  if (h === 0) return "Z";
  if (h >= 1 && h <= 9) return String.fromCharCode(64 + h);            // A–I
  if (h >= 10 && h <= 12) return String.fromCharCode(65 + h);          // K–M (J is skipped)
  if (h <= -1 && h >= -12) return String.fromCharCode(77 - h);         // N–Y
  return "";
}
export function offsetLabel(min) {
  const s = min < 0 ? "−" : "+";
  const a = Math.abs(min);
  return `${s}${Math.floor(a / 60)}${a % 60 ? ":" + String(a % 60).padStart(2, "0") : ""}`;
}

/** 031452Z OCT 26 */
export function dtg(d = new Date()) {
  return `${String(d.getUTCDate()).padStart(2, "0")}${String(d.getUTCHours()).padStart(2, "0")}${String(d.getUTCMinutes()).padStart(2, "0")}Z ${MON[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
}
export function dateMil(iso) {
  // 2026-11-02 → 02 NOV 26
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]} ${MON[+m[2] - 1]} ${m[1].slice(2)}` : "";
}
export const hhmmZ = (d = new Date()) => `${String(d.getUTCHours()).padStart(2, "0")}${String(d.getUTCMinutes()).padStart(2, "0")}Z`;

const mins = (hhmm) => {
  const d = String(hhmm || "").replace(/\D/g, "").padStart(4, "0").slice(-4);   // "0730" or "07:30"
  return +d.slice(0, 2) * 60 + +d.slice(2);
};

/** status at a local minute-of-day/weekday: duty | edge | off | night | weekend */
export function dutyAt(t, weekend) {
  const s = mins(settings.dutyStart), e = mins(settings.dutyEnd);
  if (!weekend && t >= s && t < e) return "on";
  if (t >= 22 * 60 || t < 6 * 60) return "night";
  if (weekend) return "off";
  if ((t >= s - 60 && t < s) || (t >= e && t < e + 90)) return "edge";
  return "off";
}
const WORD = { on: "duty", edge: "edge", off: "off", night: "night" };

/** {time:'1452', letter:'W', off:-600, day:+1|0|-1, wd, status, word} */
export function localTime(tz, d = new Date()) {
  if (!tz) return null;
  const p = parts(tz, d);
  if (!p) return null;
  const off = offsetMin(tz, d);
  const weekend = p.wd === "Sat" || p.wd === "Sun";
  const status = dutyAt(p.h * 60 + p.m, weekend);
  const zd = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  const ld = Date.UTC(p.y, p.mo - 1, p.d);
  return {
    time: `${String(p.h).padStart(2, "0")}${String(p.m).padStart(2, "0")}`, letter: zoneLetter(off), off,
    day: Math.round((ld - zd) / 864e5), wd: p.wd, status, word: weekend && status !== "night" ? "wknd" : WORD[status],
  };
}

/** compact cell: 1452W duty  (time + letter + word; color is redundant with the word) */
export function ltHtml(tz, { long = false } = {}) {
  const lt = localTime(tz);
  if (!lt) return "";
  const z = lt.letter || offsetLabel(lt.off);
  return `<span class="lt ${lt.status}" title="${esc(tz)} UTC${offsetLabel(lt.off)}">${lt.time}${esc(z)}${lt.day ? (lt.day > 0 ? "+1" : "−1") : ""} <i>${lt.word}${long ? ` ${esc(lt.wd)}` : ""}</i></span>`;
}

/** sub-solar point → night polygon for the map (equirectangular lon/lat) */
export function nightPolygon(d = new Date()) {
  const rad = Math.PI / 180;
  const day = (Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 0)) / 864e5;
  const decl = -23.44 * Math.cos(rad * (360 / 365) * (day + 10));
  const utcH = d.getUTCHours() + d.getUTCMinutes() / 60;
  const subLon = -15 * (utcH - 12);
  const pts = [];
  const tanD = Math.tan(decl * rad);
  for (let lon = -180; lon <= 180; lon += 2) {
    const lat = Math.atan(-Math.cos((lon - subLon) * rad) / (Math.abs(tanD) < 1e-6 ? 1e-6 : tanD)) / rad;
    pts.push([lon, lat]);
  }
  const pole = decl > 0 ? -90 : 90;
  return [...pts, [180, pole], [-180, pole]];
}
