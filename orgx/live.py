"""On-the-fly mode: fetch from Active Directory as people search and click, and keep what was fetched.

Instead of exporting the whole directory, ORGX asks AD for what is in front of the user:
  search    a name, email or office as it is typed (ambiguous name resolution)
  person    their manager and the manager above, their peers, their direct reports and the
            reports below those
  unit      everyone whose Department is that unit or under it
  site      everyone under the site's OU
Every row is normalized exactly like an export (ingest.Builder) and written into org.db
straight away, so the database grows as people use it; org tree, sites and the search index
are rebuilt from what is there. A fetch is not repeated within `ad.liveHours`.

Providers
  PowerShellProvider  tools/ADLookup.ps1 kept running (-Serve), one JSON line per request;
                      falls back to one process per request where stdin can't be read
  CsvProvider         answers the same requests from an export file (demo and tests:
                      set ORGX_LIVE_CSV=/path/to/export.csv)
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import adsync
from . import db as dbm
from . import geo
from . import ingest as ing
from . import parse as P
from . import rules as R

ROOT = Path(__file__).resolve().parent.parent
LOOKUP = ROOT / "tools" / "ADLookup.ps1"


# ---------------------------------------------------------------- providers
class Unavailable(Exception):
    pass


class PowerShellProvider:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.proc = None
        self.lines: queue.Queue = queue.Queue()
        self.serve = True
        self.n = 0
        self.lock = threading.Lock()

    def _args(self) -> list[str]:
        a = [adsync.shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(LOOKUP),
             "-Method", self.cfg.get("method", "Auto")]
        if self.cfg.get("server"):
            a += ["-Server", self.cfg["server"]]
        return a

    def _start(self) -> None:
        self.proc = subprocess.Popen(self._args() + ["-Serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.lines = queue.Queue()

        def pump(proc, q):
            for line in proc.stdout:
                q.put(line.rstrip("\n"))
            q.put(None)
        threading.Thread(target=pump, args=(self.proc, self.lines), daemon=True).start()
        while True:
            line = self._next(30)
            if line is None or line.startswith("NOSERVE"):
                self.serve = False
                self.close()
                return
            if line.startswith("READY"):
                return

    def _next(self, timeout: float):
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("Active Directory did not answer in time") from None

    def run(self, ops: list[dict], timeout: float = 30) -> list[list[dict]]:
        if not adsync.shell():
            raise Unavailable("PowerShell isn't available where the server runs")
        with self.lock:
            self.n += 1
            req = {"id": self.n, "ops": ops}
            if self.serve and (self.proc is None or self.proc.poll() is not None):
                self._start()
            if not self.serve:
                return self._once(req, timeout)
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
                while True:
                    line = self._next(timeout)
                    if line is None:
                        raise RuntimeError("the lookup process stopped")
                    if line.startswith("REPLY "):
                        rep = json.loads(line[6:])
                        if rep.get("id") == req["id"]:
                            return self._results(rep)
            except (OSError, TimeoutError, RuntimeError):
                self.close()
                raise

    def _once(self, req: dict, timeout: float) -> list[list[dict]]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(req, f)
        try:
            out = subprocess.run(self._args() + ["-Request", f.name], capture_output=True, text=True, timeout=timeout,
                                 encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            os.unlink(f.name)
        for line in out.stdout.splitlines():
            if line.startswith("REPLY "):
                return self._results(json.loads(line[6:]))
        raise RuntimeError((out.stderr or out.stdout or "no reply").strip()[-400:])

    @staticmethod
    def _results(rep: dict) -> list[list[dict]]:
        if rep.get("error"):
            raise RuntimeError(rep["error"])
        return [list(r or []) for r in rep.get("results") or []]

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None


class CsvProvider:
    """Answers lookups from an export file, as AD would (demo and tests)."""

    def __init__(self, path: Path):
        it = ing.rows(path)
        header = next(it)
        self.rows = [dict(zip(header, r)) for r in it]

    def run(self, ops: list[dict], timeout: float = 30) -> list[list[dict]]:
        return [self._op(op) for op in ops]

    @staticmethod
    def _get(r, *names):
        for n in names:
            if r.get(n):
                return r[n]
        return ""

    def _op(self, op: dict) -> list[dict]:
        kind, limit = op.get("op"), int(op.get("limit") or 0) or 10**9
        if kind == "search":
            t = str(op.get("term", "")).strip().lower()
            words = t.split()

            def hit(r):
                fields = [self._get(r, "DisplayName"), self._get(r, "GivenName"), self._get(r, "Surname"),
                          self._get(r, "WindowsEmailAddress", "Mail"), self._get(r, "SamAccountName"), self._get(r, "Office")]
                low = [f.lower() for f in fields if f]
                if any(f.startswith(t) for f in low) or any(w.startswith(t) for f in low for w in f.replace(",", " ").split()):
                    return True
                if len(words) == 2:      # ANR also matches "first last" and "last first"
                    g, s_ = self._get(r, "GivenName").lower(), self._get(r, "Surname").lower()
                    return (g.startswith(words[0]) and s_.startswith(words[1])) or (s_.startswith(words[0]) and g.startswith(words[1]))
                return False
            out = [r for r in self.rows if hit(r)]
        elif kind == "dn":
            want = {d.lower() for d in op.get("dns") or []}
            out = [r for r in self.rows if self._get(r, "DistinguishedName").lower() in want]
        elif kind == "reports":
            dn = str(op.get("dn", "")).lower()
            out = [r for r in self.rows if self._get(r, "Manager").lower() == dn]
        elif kind == "dept":
            v = str(op.get("value", ""))
            out = [r for r in self.rows if r.get("Department", "") == v or r.get("Department", "").startswith(v + "/")]
        elif kind == "ous":
            t = str(op.get("term", "")).strip().lower()
            seen: dict[str, None] = {}
            for r in self.rows:
                parts = P.split_dn(self._get(r, "DistinguishedName"))
                for i, (k, v) in enumerate(parts):
                    if k == "OU" and v.lower().startswith(t):
                        seen[",".join(f"{a}={_escape_rdn(b)}" for a, b in parts[i:])] = None
            return [{"DistinguishedName": d, "ObjectClass": "organizationalUnit"} for d in seen][:limit]
        elif kind == "ou":
            base = "," + str(op.get("base", "")).lower()
            out = [r for r in self.rows if self._get(r, "DistinguishedName").lower().endswith(base)]
        else:
            raise ValueError(f"unknown op {kind}")
        return out[:limit]


_providers: dict[str, object] = {}
_write = threading.Lock()        # one writer at a time: each upsert rebuilds orgs and the index


def provider(ctx):
    csv_path = os.environ.get("ORGX_LIVE_CSV", "").strip()
    if csv_path:
        key = "csv:" + csv_path
        if key not in _providers:
            _providers[key] = CsvProvider(Path(csv_path))
        return _providers[key]
    if not adsync.shell():
        return None
    cfg = adsync.config(ctx)
    key = f"ps:{cfg.get('server')}:{cfg.get('method')}"
    if key not in _providers:
        for k in [k for k in _providers if k.startswith("ps:")]:
            _providers.pop(k).close()
        _providers[key] = PowerShellProvider(cfg)
    return _providers[key]


def enabled(ctx) -> bool:
    return adsync.config(ctx).get("mode") == "live"


def status(ctx, p=None, b=None) -> dict:
    return {"on": enabled(ctx), "available": provider(ctx) is not None,
            "source": "export file" if os.environ.get("ORGX_LIVE_CSV") else "Active Directory"}


# ---------------------------------------------------------------- store
def ensure_db(ctx) -> None:
    """An empty, ready org.db, so on-the-fly mode can start without any export."""
    path = ctx.data_dir / "org.db"
    if path.exists():
        conn = sqlite3.connect(path)
        conn.executescript("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);"
                           "CREATE TABLE IF NOT EXISTS ou_stats (depth INTEGER, value TEXT, n INTEGER, cities TEXT, PRIMARY KEY (depth, value));"
                           "CREATE TABLE IF NOT EXISTS live_fetch (kind TEXT, ref TEXT, at REAL, n INTEGER, PRIMARY KEY (kind, ref));")
        conn.close()
        return
    conn = sqlite3.connect(path)
    conn.executescript(dbm.SCHEMA)
    conn.executescript(dbm.INDEXES)
    if dbm.has_fts5():
        conn.executescript(dbm.FTS)
    conn.executescript("CREATE TABLE IF NOT EXISTS live_fetch (kind TEXT, ref TEXT, at REAL, n INTEGER, PRIMARY KEY (kind, ref));")
    conn.execute("INSERT INTO snapshots (taken_at, source, rows, objects, people, orgs, locations, as_of) VALUES (?,?,0,0,0,0,0,?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), "on the fly",
                  datetime.now(timezone.utc).date().isoformat()))
    conn.commit()
    conn.close()
    dbm.init_annotations(ctx.data_dir)


def _rw(ctx) -> sqlite3.Connection:
    # rollback journal, not WAL: a full ingest swaps org.db for a new file, and a leftover -wal
    # file from the old one must never be replayed into it
    conn = sqlite3.connect(ctx.data_dir / "org.db", timeout=15)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _learned(conn) -> geo.OuLearner:
    total = int((conn.execute("SELECT v FROM meta WHERE k = 'ou_total'").fetchone() or ["0"])[0] or 0)
    return geo.OuLearner.from_rows(total, conn.execute("SELECT depth, value, n, cities FROM ou_stats"))


def upsert(ctx, raw: list[dict]) -> dict:
    """Normalize rows like an export and write them; then rebuild orgs, sites and the index."""
    if not raw:
        return {"added": 0, "updated": 0}
    rules = R.load(ctx.data_dir)
    conn = _rw(ctx)
    try:
        # learn the OU structure from these rows too
        learner = _learned(conn)
        header = list({k: None for r in raw for k in r})
        cmap = P.map_columns(header)
        for r in raw:
            dn, ou = P.clean(r.get(cmap.get("dn", ""), "")), P.clean(r.get(cmap.get("ou", ""), ""))
            ous, _ = P.ou_path(dn, ou)
            if ous and not (dn and conn.execute("SELECT 1 FROM objects WHERE dn = ?", (dn,)).fetchone()):
                learner.add(ous, str(r.get(cmap.get("city", ""), "") or ""))
        levels = learner.result()
        ing.save_learned(conn, learner, levels)

        b = ing.Builder(ctx.data_dir, rules, levels)
        mapped = set(cmap.values())
        cols = dbm.OBJECT_COLS
        sql = (f"INSERT INTO objects ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
               f"ON CONFLICT(key) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols[1:])}")
        added = updated = 0
        for r in raw:
            row = {f: ("" if r.get(h) is None else str(r.get(h))) for f, h in cmap.items()}
            extras = {h: str(v)[:200] for h, v in r.items() if h not in mapped and v not in (None, "", False)}
            extras.pop("ObjectClass", None)
            if row.get("managedby", "").strip():
                extras["ManagedBy"] = row["managedby"].strip()[:400]
            rec = b.record(row, extras)
            if rec is None:
                continue
            known = conn.execute("SELECT 1 FROM objects WHERE key = ?", (rec[0],)).fetchone()
            conn.execute(sql, rec)
            if known:
                updated += 1
            else:
                added += 1
        for lid, loc in b.locs.items():
            conn.execute("INSERT OR IGNORE INTO locations VALUES (:id,:name,:full,:lat,:lon,:tz,:country,:state,:region,"
                         ":approx,:ou,0,0)", loc)
        rebuild(conn, rules)
        conn.commit()
        return {"added": added, "updated": updated}
    finally:
        conn.close()


def rebuild(conn: sqlite3.Connection, rules: dict) -> None:
    """Managers, org tree, site totals and the search index, from what is in the table."""
    conn.execute("""UPDATE objects SET manager_key = (SELECT m.key FROM objects m WHERE m.dn = objects.manager_dn LIMIT 1)
        WHERE manager_dn <> '' AND instr(manager_dn, '=') > 0""")
    orgs = ing.build_orgs(ing.DbAggregates(conn, rules), ing.manager_links(conn))
    ing.write_orgs(conn, orgs)
    conn.execute("""UPDATE locations SET total = (SELECT count(*) FROM objects o WHERE o.loc_id = locations.id),
        people = (SELECT count(*) FROM objects o WHERE o.loc_id = locations.id AND o.kind = 'person')""")
    n = conn.execute("SELECT count(*), sum(kind = 'person') FROM objects").fetchone()
    conn.execute("UPDATE snapshots SET objects = ?, people = ?, orgs = ?, locations = (SELECT count(*) FROM locations) "
                 "WHERE id = (SELECT max(id) FROM snapshots) AND source = 'on the fly'", (n[0], n[1] or 0, len(orgs)))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'objects_fts'").fetchone():
        conn.execute("INSERT INTO objects_fts(objects_fts) VALUES('rebuild')")


# ---------------------------------------------------------------- what to fetch
def _fresh(conn, kind: str, ref: str, hours: float) -> bool:
    r = conn.execute("SELECT at FROM live_fetch WHERE kind = ? AND ref = ?", (kind, ref.lower())).fetchone()
    return bool(r) and time.time() - r[0] < hours * 3600


def _mark(ctx, kind: str, ref: str, n: int) -> None:
    conn = _rw(ctx)
    conn.execute("INSERT OR REPLACE INTO live_fetch VALUES (?,?,?,?)", (kind, ref.lower(), time.time(), n))
    conn.commit()
    conn.close()


def _fetch(ctx, kind: str, ref: str, plan) -> dict:
    """plan(conn) -> list of op batches (each batch can depend on the rows from the one before)."""
    if not enabled(ctx):
        return {"ok": False, "off": True}
    prov = provider(ctx)
    if prov is None:
        return {"ok": False, "error": "On-the-fly mode needs PowerShell on the server's Windows host."}
    if ctx.job["running"]:
        return {"ok": False, "error": "an export is loading"}
    ensure_db(ctx)
    hours = float(adsync.config(ctx).get("liveHours") or 12)
    conn = sqlite3.connect(ctx.data_dir / "org.db")
    try:
        if _fresh(conn, kind, ref, hours):
            return {"ok": True, "cached": True, "added": 0, "updated": 0}
    finally:
        conn.close()
    t0 = time.time()
    total = {"added": 0, "updated": 0, "fetched": 0}
    rows: list[dict] = []
    gen = plan()
    try:
        ops = next(gen)
        while ops:
            got = [r for batch in prov.run(ops) for r in batch]
            objs = [r for r in got if r.get("ObjectClass") != "organizationalUnit"]
            total["fetched"] += len(objs)
            with _write:
                res = upsert(ctx, objs)
            total["added"] += res["added"]
            total["updated"] += res["updated"]
            rows = got
            ops = gen.send(rows)
    except StopIteration:
        pass
    except (Unavailable, RuntimeError, TimeoutError, OSError, sqlite3.Error) as e:
        return {"ok": False, "error": str(e), **total}
    with _write:
        _mark(ctx, kind, ref, total["fetched"])
    return {"ok": True, "cached": False, "ms": int((time.time() - t0) * 1000), **total}


def _dns(rows, field="DistinguishedName"):
    return [r.get(field) for r in rows if r.get(field)]


def search(ctx, term: str) -> dict:
    term = term.strip()
    if len(term) < 2:
        return {"ok": True, "added": 0, "updated": 0, "cached": True}

    def plan():
        got = yield [{"op": "search", "term": term, "limit": 25}, {"op": "ous", "term": term, "limit": 10}]
        bases = place_bases(ctx, [r["DistinguishedName"] for r in got if r.get("ObjectClass") == "organizationalUnit"])
        if bases:
            yield [{"op": "ou", "base": b, "limit": 400} for b in bases]
    return _fetch(ctx, "search", term, plan)


def _ou_depth(dn: str) -> int:
    return sum(1 for k, _ in P.split_dn(dn) if k == "OU") - 1


def place_bases(ctx, ous: list[str]) -> list[str]:
    """OUs named like the search: the ones at the learned site level, else the two highest."""
    ous = [d for d in ous if not geo.CONTAINER.match((P.split_dn(d) or [("", "")])[0][1].strip())]
    if not ous:
        return []
    conn = dbm.connect(ctx.data_dir)
    try:
        levels = json.loads((conn.execute("SELECT v FROM meta WHERE k = 'ou_levels'").fetchone() or ["{}"])[0]) if conn else {}
    except sqlite3.OperationalError:
        levels = {}
    site = levels.get("site")
    at_site = [d for d in ous if site is not None and _ou_depth(d) == site]
    return (at_site or sorted(ous, key=_ou_depth))[:2]


def person(ctx, key: str) -> dict:
    """Two levels up (manager, their manager), peers, and two levels down (reports, their reports)."""
    conn = dbm.connect(ctx.data_dir)
    row = conn.execute("SELECT dn, manager_dn FROM objects WHERE key = ?", (key,)).fetchone() if conn else None
    if not row or not row["dn"]:
        return {"ok": True, "added": 0, "updated": 0, "cached": True}
    dn, mgr = row["dn"], row["manager_dn"]

    def plan():
        first = [{"op": "reports", "dn": dn, "limit": 100}]
        if mgr:
            first += [{"op": "dn", "dns": [mgr]}, {"op": "reports", "dn": mgr, "limit": 60}]
        got = yield first
        reports = [r for r in got if (r.get("Manager") or "").lower() == dn.lower()]
        boss = next((r for r in got if mgr and (r.get("DistinguishedName") or "").lower() == mgr.lower()), None)
        nxt = [{"op": "reports", "dn": d, "limit": 40} for d in _dns(reports)[:12]]
        if boss and boss.get("Manager"):
            nxt.append({"op": "dn", "dns": [boss["Manager"]]})
        if nxt:
            yield nxt
    return _fetch(ctx, "person", key, plan)


def unit(ctx, org_id: str) -> dict:
    conn = dbm.connect(ctx.data_dir)
    depts = [r[0] for r in conn.execute(
        "SELECT dept FROM objects WHERE (org_id = ? OR org_id LIKE ? ) AND dept <> '' GROUP BY dept ORDER BY count(*) DESC LIMIT 4",
        (org_id, org_id + "/%"))] if conn else []
    depts = depts or [org_id]

    def plan():
        yield [{"op": "dept", "value": d, "limit": 300} for d in depts]
    return _fetch(ctx, "unit", org_id, plan)


def _escape_rdn(v: str) -> str:
    out = v.replace("\\", "\\\\")
    for ch in ',+"<>;=':
        out = out.replace(ch, "\\" + ch)
    return out


def site_base(dn: str, depth: int) -> str:
    """The DN of the OU at `depth` (root-first) on this object's path."""
    parts = P.split_dn(dn)
    ou_idx = [i for i, (k, _) in enumerate(parts) if k == "OU"]
    if depth >= len(ou_idx):
        return ""
    i = ou_idx[len(ou_idx) - 1 - depth]
    return ",".join(f"{k}={_escape_rdn(v)}" for k, v in parts[i:])


def site(ctx, loc_id: str) -> dict:
    conn = dbm.connect(ctx.data_dir)
    if not conn:
        return {"ok": True, "added": 0, "updated": 0, "cached": True}
    levels = json.loads((conn.execute("SELECT v FROM meta WHERE k = 'ou_levels'").fetchone() or ["{}"])[0])
    sample = conn.execute("SELECT dn FROM objects WHERE loc_id = ? AND dn LIKE '%OU=%' LIMIT 1", (loc_id,)).fetchone()
    base = site_base(sample[0], levels["site"]) if sample and levels.get("site") is not None else ""
    if not base:
        return {"ok": True, "added": 0, "updated": 0, "cached": True}

    def plan():
        yield [{"op": "ou", "base": base, "limit": 400}]
    return _fetch(ctx, "site", loc_id, plan)
