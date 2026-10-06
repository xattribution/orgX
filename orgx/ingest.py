"""AD/GAL CSV → data/org.db.

Streams the CSV (any size), normalizes every row, builds the org tree and
location table, resolves managers and DL membership by DN, diffs against the
previous build into `events`, then atomically swaps the new database in.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import db as dbm
from . import fold
from . import geo
from . import parse as P
from . import reference as ref
from . import rules as R

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
BATCH = 5000


# ---------------------------------------------------------------- reading
def open_text(path: Path) -> io.TextIOBase:
    """Sniff BOM: PowerShell 5 Out-File writes UTF-16; Export-Csv writes UTF-8 or ASCII."""
    with path.open("rb") as f:
        head = f.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    elif head.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    fh = path.open(encoding=enc, errors="replace", newline="")
    return fh


def rows(path: Path):
    fh = open_text(path)
    first = fh.readline()
    if not first.startswith("#TYPE"):          # Export-Csv without -NoTypeInformation
        fh.seek(0)
    sample = fh.read(8192)
    fh.seek(0)
    if first.startswith("#TYPE"):
        fh.readline()
    try:      # sniff only the delimiter; quoting is always standard ("" inside a quoted field)
        delim = csv.Sniffer().sniff(sample.split("\n", 1)[0], delimiters=",\t;|").delimiter
    except csv.Error:
        delim = ","
    reader = csv.reader(fh, delimiter=delim)
    header = next(reader, [])
    yield header
    for r in reader:
        if r:
            yield r
    fh.close()


# ---------------------------------------------------------------- record build
def category_of(grade: str, service: str, email: str) -> str:
    if service in ref.FOREIGN:
        return "foreign"
    if re.match(r"^[EWO]-\d", grade or ""):
        return "mil"
    if grade == "CTR":
        return "ctr"
    if grade:
        return "civ"
    return ""


def make_key(row: dict, email: str, dn: str, first: str, last: str, mi: str, title: str, display: str) -> str:
    for field, prefix in (("guid", "g"), ("employee_id", "e")):
        v = P.clean(row.get(field))
        if v:
            return f"{prefix}:{v.lower()}"
    if email:
        return f"m:{email.lower()}"
    if dn:
        return f"d:{dn.lower()}"
    return "n:" + "|".join(x.lower() for x in (last, first, mi, title or display))


class Builder:
    def __init__(self, data_dir: Path, rules: dict, levels: dict | None = None, fold: dict | None = None):
        self.data_dir = data_dir
        self.rules = rules
        self.gaz = geo.Gazetteer(data_dir, rules.get("baseAliases"), levels)
        self.kw = R.fn_keywords(rules)
        self.anchors = [a for a in (rules.get("anchors") or []) if a.strip()]
        self.org_alias = {k.upper(): v for k, v in (rules.get("orgAliases") or {}).items()}
        self.fold = fold or {}       # drifted spellings of a unit → the spelling kept (orgx/fold.py)
        self.skip_kinds = set(rules.get("skipKinds") or [])
        P.CODE_OVERRIDES.clear()
        P.CODE_OVERRIDES.update({k.upper().replace(" ", ""): v for k, v in (rules.get("codeFunctions") or {}).items()
                                 if v in ref.FN_LABEL})
        # aggregates
        self.org_direct: Counter = Counter()
        self.org_people: Counter = Counter()
        self.org_best: dict[str, tuple] = {}
        self.org_locs: dict[str, Counter] = defaultdict(Counter)
        self.locs: dict[str, dict] = {}
        self.loc_total: Counter = Counter()
        self.loc_people: Counter = Counter()
        self.keys: set[str] = set()
        self.stats = Counter()
        # titles, org paths, OU paths and cities repeat across a directory: work each out once
        self._places: dict[tuple, dict] = {}
        self._by_path: dict[tuple, dict] = {}
        self._by_title: dict[str, dict] = {}
        self._by_career: dict[str, str] = {}

    def functions(self, text: str, path: tuple, career: str) -> list[str]:
        """P.classify_functions, with each of its three inputs scored once per distinct value."""
        ps = self._by_path.get(path)
        if ps is None:
            ps = self._by_path[path] = P.path_scores(path)
        ts = self._by_title.get(text)
        if ts is None:
            ts = P.title_scores(text, self.kw)
            if len(self._by_title) < 300_000:
                self._by_title[text] = ts
        cf = self._by_career.get(career)
        if cf is None:
            cf = self._by_career[career] = P.career_function(career)
        return P.combine_scores(ps, ts, career_fn=cf)

    def record(self, row: dict, extras: dict) -> tuple | None:
        display = P.clean(row.get("display"))
        dn = P.clean(row.get("dn"))
        ous, domain = P.ou_path(dn, P.clean(row.get("ou")))
        parsed = P.parse_display(display)
        kind = P.classify_kind(row, parsed, ous)
        if kind in self.skip_kinds:
            self.stats["skipped_kind"] += 1
            return None
        disabled = P.is_disabled(row)
        hidden = P.is_hidden(row)
        if (disabled and kind == "person" and self.rules.get("skipDisabled")) or (hidden and self.rules.get("skipHidden")):
            self.stats["skipped_state"] += 1
            return None

        first = P.clean(row.get("first")) or parsed["first"]
        last = P.clean(row.get("last")) or parsed["last"]
        mi = (P.clean(row.get("initials")) or parsed["mi"]).replace(".", "")[:2]
        service = parsed["service"]
        rank_raw = P.clean(row.get("rank"))
        if rank_raw:
            rank, grade = P.resolve_rank(rank_raw, service)
            rank = rank or rank_raw
        else:
            rank, grade = parsed["rank"], parsed["grade"]
        if parsed["last"]:
            self.stats["parsed_names"] += 1
        title = P.clean(row.get("title"))
        dept = P.clean(row.get("department"))
        email = P.clean(row.get("email"))
        if email.lower().startswith("smtp:"):
            email = email[5:]
        if ";" in email or "," in email:
            email = re.split(r"[;,]", email)[0].strip()

        path = P.org_path(dept, parsed["org"])
        if not path and kind != "person" and "/" in display:
            stripped = display
            for rx, _ in ref.NAME_KIND_HINTS:
                stripped = rx.sub("", stripped)
            path = P.org_path(stripped.strip(" -–"), "")
        if path and path[0].upper() in self.org_alias:
            path = [self.org_alias[path[0].upper()]] + path[1:]
        elif path and path[0] in self.fold:
            path = [self.fold[path[0]]] + path[1:]
        org_id = "/".join(path)

        office = P.clean(row.get("office"))
        city, state, country = P.clean(row.get("city")), P.clean(row.get("state")), P.clean(row.get("country"))
        pk = (tuple(ous), office, city, state, country)
        loc = self._places.get(pk)
        if loc is None:
            loc = self.gaz.place(ous, self.anchors, office, city, state, country)
            if len(self._places) < 300_000:
                self._places[pk] = loc
        if loc["id"]:
            if loc["id"] not in self.locs:
                self.locs[loc["id"]] = loc
            elif not self.locs[loc["id"]].get("region") and loc.get("region"):
                self.locs[loc["id"]]["region"] = loc["region"]
            self.loc_total[loc["id"]] += 1
            if kind == "person":
                self.loc_people[loc["id"]] += 1
        else:
            self.stats["unplaced"] += 1

        career = P.clean(row.get("career"))
        if not career and kind == "person":
            m = ref.AFSC_RE.search(f"{title} {P.clean(row.get('description'))}")
            career = m.group(1) if m else ""
        fns = self.functions(f"{title} {display if kind != 'person' else ''}", tuple(path), career)
        lead = ref.leader_score(title) if kind == "person" else 0
        level = ref.grade_level(grade)
        category = category_of(grade, service, email) if kind == "person" else ""
        tier = ref.tier_of(level, category) if kind == "person" else ""

        if kind == "person":
            name = " ".join(x for x in (P.smart_case(first), (mi[:1] + ".") if mi else "", P.smart_case(last)) if x)
            sort_name = f"{P.smart_case(last)}, {P.smart_case(first)}".strip(", ")
            name = name or display
            sort_name = sort_name or display
        else:
            name = display or email
            sort_name = name

        key = make_key(row, email, dn, first, last, mi, title, display)
        if key in self.keys:
            n = 2
            while f"{key}#{n}" in self.keys:
                n += 1
            key = f"{key}#{n}"
            self.stats["duplicate_keys"] += 1
        self.keys.add(key)

        # org aggregates
        if org_id:
            self.org_direct[org_id] += 1
            if loc["id"]:
                self.org_locs[org_id][loc["id"]] += 1
            if kind == "person":
                self.org_people[org_id] += 1
                cand = (lead, level, key)
                if org_id not in self.org_best or cand[:2] > self.org_best[org_id][:2]:
                    self.org_best[org_id] = cand
        self.stats[f"kind_{kind}"] += 1

        phone, dsn, mobile = P.clean(row.get("phone")), P.clean(row.get("dsn")), P.clean(row.get("mobile"))
        return (
            key, kind, display, name, sort_name, P.smart_case(first), P.smart_case(last), mi, rank, grade, level,
            service, category, tier, title, org_id, dept, office, phone, dsn, mobile,
            P.digits(" ".join((phone, dsn, mobile))), email, P.clean(row.get("upn")), P.clean(row.get("sam")),
            loc["id"], loc.get("region", ""), loc.get("country", ""), "/".join(ous), dn, domain, career,
            fns[0] if fns else "", ",".join(fns), lead, P.clean(row.get("manager")), int(disabled), int(hidden),
            P.clean(row.get("created")), P.clean(row.get("changed")), P.clean(row.get("description"))[:500],
            json.dumps(extras, separators=(",", ":")) if extras else "",
        )


# ---------------------------------------------------------------- org tree
STAFF_ORDER = ["CC", "CV", "CD", "CCE", "CCC", "CCS", "CS", "COS", "TD", "CAG", "CCX", "CCP", "DS"]


def sort_key(name: str) -> tuple:
    u = name.upper()
    if u in STAFF_ORDER:
        return (0, STAFF_ORDER.index(u), u)
    m = P.STAFF_RE.match(u.replace(" ", ""))
    if m:
        return (1, m.group(1), int(m.group(2)), u)
    if u.startswith(("FWD", "LNO", "OL", "DET")):
        return (3, u)
    return (2, u)


def build_orgs(b: Builder, mgr_links: dict[str, Counter]) -> dict[str, dict]:
    orgs: dict[str, dict] = {}
    for oid in list(b.org_direct):
        parts = oid.split("/")
        for i in range(len(parts)):
            pid = "/".join(parts[: i + 1])
            if pid not in orgs:
                orgs[pid] = {"id": pid, "name": parts[i], "parent": "/".join(parts[:i]) or None,
                             "kind": P.org_kind(parts[i]), "fn": P.code_function(parts[i]), "inferred": ""}

    # office symbols: SCOO under SCO under SC (siblings only)
    if b.rules.get("nestOfficeSymbols", True):
        by_parent = defaultdict(list)
        for o in orgs.values():
            by_parent[o["parent"]].append(o)
        for sibs in by_parent.values():
            names = {o["name"].upper(): o for o in sibs}
            for o in sibs:
                n = o["name"].upper()
                if not (2 < len(n) <= 8 and re.fullmatch(r"[A-Z0-9]+", n)):
                    continue
                for cut in range(len(n) - 1, 1, -1):
                    p = names.get(n[:cut])
                    if p and p is not o:
                        o["parent"], o["inferred"] = p["id"], "office symbol"
                        break

    tops = {o["id"] for o in orgs.values() if o["parent"] is None}
    upper = {oid.upper(): oid for oid in tops}

    def ancestors(oid):
        seen = set()
        while oid and oid not in seen:
            seen.add(oid)
            oid = orgs[oid]["parent"] if oid in orgs else None
        return seen

    def attach(child, parent, why):
        if parent and parent in orgs and child != parent and child not in ancestors(parent):
            orgs[child]["parent"], orgs[child]["inferred"] = parent, why
            return True
        return False

    # explicit parents from rules
    for child, parent in (b.rules.get("orgParents") or {}).items():
        c = upper.get(child.upper()) or (child if child in orgs else None)
        p = parent if parent in orgs else upper.get(parent.upper())
        if c and p:
            attach(c, p, "rule")

    # manager links first (strongest evidence): top-level org whose people report into another unit
    if b.rules.get("inferFromManagers", True):
        def unit_of(oid):
            cur = oid
            while cur in orgs and orgs[cur]["kind"] in ("staff", "office") and orgs[cur]["parent"]:
                cur = orgs[cur]["parent"]
            return cur
        for oid in sorted(tops):
            if orgs[oid]["parent"] or oid not in mgr_links:
                continue
            votes = Counter()
            for mo, n in mgr_links[oid].items():
                if mo in orgs and oid not in ancestors(mo) and mo.split("/")[0] != oid:
                    votes[unit_of(mo)] += n
            if votes:
                target, n = votes.most_common(1)[0]
                if n >= 2 or sum(votes.values()) == n:
                    attach(oid, target, "managers")

    # depth, sort, nested set, totals
    kids = defaultdict(list)
    for o in orgs.values():
        kids[o["parent"]].append(o["id"])
    for k in kids:
        kids[k].sort(key=lambda i: sort_key(orgs[i]["name"]))
    counter = 0

    def walk(root, depth):
        nonlocal counter
        stack = [(root, depth, False)]
        while stack:
            oid, d, done = stack.pop()
            o = orgs[oid]
            if done:
                counter += 1
                o["rgt"] = counter
                o["total"] = b.org_direct.get(oid, 0) + sum(orgs[c]["total"] for c in kids.get(oid, []))
                o["people"] = b.org_people.get(oid, 0) + sum(orgs[c]["people"] for c in kids.get(oid, []))
                continue
            counter += 1
            o["lft"], o["depth"] = counter, d
            stack.append((oid, d, True))
            for c in reversed(kids.get(oid, [])):
                stack.append((c, d + 1, False))

    subtree: dict[str, int] = {}

    def count(oid):
        if oid not in subtree:
            subtree[oid] = b.org_people.get(oid, 0) + sum(count(c) for c in kids.get(oid, []))
        return subtree[oid]

    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
    for root in sorted(kids[None], key=lambda i: (-count(i), i)):
        walk(root, 0)
    for oid, o in orgs.items():
        o["sort"] = o["lft"]
        o["direct"] = b.org_direct.get(oid, 0)
        best = b.org_best.get(oid)
        o["leader_key"] = best[2] if best else None
        o["leader_by"] = ("title" if best[0] > 0 else "seniority") if best else None
        locs = b.org_locs.get(oid)
        o["loc_id"] = locs.most_common(1)[0][0] if locs else None
        o["locs"] = len(locs) if locs else 0
        if not o["fn"]:
            # inherit from the parent chain
            p = o["parent"]
            while p and not orgs[p]["fn"]:
                p = orgs[p]["parent"]
            o["fn"] = orgs[p]["fn"] if p else ""
    # site unit: highest ancestor based at the same location (the local unit, not a distant headquarters)
    for oid, o in orgs.items():
        cur = oid
        while orgs[cur]["parent"] and orgs[orgs[cur]["parent"]]["loc_id"] == o["loc_id"]:
            cur = orgs[cur]["parent"]
        o["site"] = cur
    return orgs


def manager_links(conn: sqlite3.Connection) -> dict[str, Counter]:
    """top-level org → {org its people's managers sit in: count}"""
    links: dict[str, Counter] = defaultdict(Counter)
    for oid, moid, n in conn.execute("""SELECT o.org_id, m.org_id, count(*) FROM objects o
            JOIN objects m ON m.key = o.manager_key
            WHERE o.org_id <> '' AND m.org_id <> '' AND o.org_id <> m.org_id GROUP BY 1, 2"""):
        links[oid.split("/")[0]][moid] += n
    return links


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Directories built before the root columns existed (on-the-fly stores) get them in place."""
    for table, col in (("orgs", "root"), ("objects", "org_root")):
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def write_fns(conn: sqlite3.Connection) -> None:
    """One row per (function, object): fn: filters become index lookups instead of a LIKE over every row."""
    conn.execute("CREATE TABLE IF NOT EXISTS object_fns (fn TEXT, object_id INTEGER, PRIMARY KEY (fn, object_id)) WITHOUT ROWID")
    conn.execute("DELETE FROM object_fns")
    cur = conn.execute("SELECT id, fns FROM objects WHERE fns <> ''")
    while True:
        chunk = cur.fetchmany(50_000)
        if not chunk:
            break
        conn.executemany("INSERT OR IGNORE INTO object_fns VALUES (?,?)",
                         [(f, oid) for oid, fns in chunk for f in fns.split(",") if f])


def write_orgs(conn: sqlite3.Connection, orgs: dict[str, dict]) -> None:
    _ensure_columns(conn)
    for o in orgs.values():           # top-level unit of each office, for the unit facet
        r, seen = o, set()
        while r.get("parent") and r["parent"] in orgs and r["id"] not in seen:
            seen.add(r["id"])
            r = orgs[r["parent"]]
        o["root"] = r["id"]
    conn.execute("DELETE FROM orgs")
    conn.executemany(
        "INSERT INTO orgs VALUES (:id,:name,:parent,:depth,:kind,:fn,:direct,:total,:people,:leader_key,"
        ":leader_by,:loc_id,:locs,:inferred,:lft,:rgt,:sort,:site,:root)", list(orgs.values()))
    conn.execute("UPDATE objects SET (org_lft, org_root) = (SELECT lft, root FROM orgs WHERE orgs.id = objects.org_id)")


class DbAggregates:
    """The per-org totals build_orgs needs, recomputed from the objects table (on-the-fly mode)."""

    def __init__(self, conn: sqlite3.Connection, rules: dict):
        self.rules = rules
        self.org_direct: Counter = Counter()
        self.org_people: Counter = Counter()
        self.org_best: dict[str, tuple] = {}
        self.org_locs: dict[str, Counter] = defaultdict(Counter)
        for key, kind, org_id, loc_id, lead, level in conn.execute(
                "SELECT key, kind, org_id, loc_id, leader, level FROM objects WHERE org_id <> ''"):
            self.org_direct[org_id] += 1
            if loc_id:
                self.org_locs[org_id][loc_id] += 1
            if kind == "person":
                self.org_people[org_id] += 1
                cand = (lead or 0, level or 0, key)
                if org_id not in self.org_best or cand[:2] > self.org_best[org_id][:2]:
                    self.org_best[org_id] = cand


def upgrade(data_dir: Path, log=print) -> bool:
    """Bring a directory built by an older version up to the current layout in place (unit roots,
    the function table, the current indexes and planner statistics), so it works without a reload."""
    path = data_dir / "org.db"
    if not path.exists():
        return False
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        have = conn.execute("SELECT v FROM meta WHERE k = 'schema'").fetchone()
        if have and int(have[0]) >= dbm.SCHEMA_VERSION:
            return False
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'objects'").fetchone():
            return False
        log("upgrading the directory to the current layout (once) …")
        _ensure_columns(conn)
        parent = dict(conn.execute("SELECT id, parent FROM orgs").fetchall())
        def top(i):
            seen = set()
            while parent.get(i) and parent[i] in parent and i not in seen:
                seen.add(i)
                i = parent[i]
            return i
        conn.executemany("UPDATE orgs SET root = ? WHERE id = ?", [(top(i), i) for i in parent])
        conn.execute("UPDATE objects SET org_root = (SELECT root FROM orgs WHERE orgs.id = objects.org_id)")
        write_fns(conn)
        # indexes whose definition changed are rebuilt; leftovers from older builds go
        want = {}
        for stmt in dbm.INDEXES.split(";"):
            m = re.search(r"CREATE INDEX IF NOT EXISTS (\w+)", stmt)
            if m:
                want[m.group(1)] = re.sub(r"\s+", " ", stmt.strip().replace("IF NOT EXISTS ", ""))
        for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL").fetchall():
            if name in ("tmp_dn", "tmp_em", "tmp_key", "ob_fn") or (name in want and re.sub(r"\s+", " ", sql) != want[name]):
                conn.execute(f"DROP INDEX {name}")
        conn.executescript(dbm.INDEXES)
        conn.execute("PRAGMA analysis_limit = 2000")
        conn.execute("ANALYZE")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(dbm.SCHEMA_VERSION),))
        conn.commit()
        log("upgrade done")
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------- diff
# (type, row source, before, after, where). Rows come from n (new) and/or o (old).
_J = "main.objects n JOIN old.objects o ON o.key = n.key"
DIFF = [
    ("joined", "main.objects n LEFT JOIN old.objects o ON o.key = n.key", "''", "n.org_id", "o.key IS NULL"),
    ("departed", "old.objects o LEFT JOIN main.objects n ON n.key = o.key", "o.org_id", "''", "n.key IS NULL"),
    ("moved", _J, "o.org_id", "n.org_id", "IFNULL(o.org_id,'') <> IFNULL(n.org_id,'')"),
    ("promoted", _J, "o.rank", "n.rank",
     "n.level > o.level AND o.level > 0 AND n.grade <> o.grade AND n.category = o.category"),
    ("regraded", _J, "o.rank", "n.rank",
     "IFNULL(n.grade,'') <> IFNULL(o.grade,'') AND NOT (n.level > o.level AND o.level > 0 AND n.category = o.category)"),
    ("retitled", _J, "o.title", "n.title", "IFNULL(o.title,'') <> IFNULL(n.title,'')"),
    ("relocated", _J, "o.loc_id", "n.loc_id", "IFNULL(o.loc_id,'') <> IFNULL(n.loc_id,'')"),
    ("contact", _J, "o.email || ' · ' || o.phone", "n.email || ' · ' || n.phone",
     "IFNULL(o.email,'') <> IFNULL(n.email,'') OR IFNULL(o.phone,'') <> IFNULL(n.phone,'')"),
]


def diff_sql(snap_id: int, etype: str, src: str, before: str, after: str, where: str) -> str:
    side = "o" if etype == "departed" else "n"
    return (f"INSERT INTO events (snap, key, kind, type, name, before, after, org_id, loc_id, level) "
            f"SELECT {snap_id}, {side}.key, {side}.kind, '{etype}', {side}.name, {before}, {after}, "
            f"{side}.org_id, {side}.loc_id, {side}.level FROM {src} WHERE {where}")


# ---------------------------------------------------------------- learned structure
def learn_ous(csv_path: Path, idx: dict) -> geo.OuLearner:
    return prepass(csv_path, idx)[0]


def prepass(csv_path: Path, idx: dict) -> tuple[geo.OuLearner, Counter]:
    """One read before the build: the OU structure (which depth holds sites, from DN and City) and
    how often each unit root is spelled each way (from Department)."""
    lr = geo.OuLearner()
    roots: Counter = Counter()
    root_of: dict[str, str] = {}
    it = rows(csv_path)
    next(it)
    i_dn, i_ou, i_city, i_dept = idx.get("dn"), idx.get("ou"), idx.get("city"), idx.get("department")
    for r in it:
        dn = r[i_dn] if i_dn is not None and i_dn < len(r) else ""
        ou = r[i_ou] if i_ou is not None and i_ou < len(r) else ""
        ous, _ = P.ou_path(P.clean(dn), P.clean(ou))
        if ous:
            lr.add(ous, r[i_city] if i_city is not None and i_city < len(r) else "")
        dept = r[i_dept] if i_dept is not None and i_dept < len(r) else ""
        if dept:
            root = root_of.get(dept)
            if root is None:
                path = P.org_path(P.clean(dept), "")
                root = root_of[dept] = path[0] if path else ""
            if root:
                roots[root] += 1
    return lr, roots


def plan_folds(roots: Counter, rules: dict) -> tuple[list[dict], list[dict]]:
    if not rules.get("foldSpellings", True):
        return [], []
    folds = fold.plan(roots, rules.get("orgSeparate") or [], rules.get("orgAliases") or {})
    return folds, fold.suggest(roots, fold.mapping(folds))


def save_learned(conn: sqlite3.Connection, learner: geo.OuLearner, levels: dict) -> None:
    conn.execute("DELETE FROM ou_stats")
    conn.executemany("INSERT INTO ou_stats VALUES (?,?,?,?)", learner.to_rows())
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                     [("ou_levels", json.dumps(levels)), ("ou_total", str(learner.total))])


# ---------------------------------------------------------------- main
DATE_IN_NAME = re.compile(r"(20\d\d)-?(0[1-9]|1[0-2])-?(0[1-9]|[12]\d|3[01])")


def as_of_date(csv_path: Path, override: str | None = None) -> str:
    """Snapshot date: explicit --as-of, else a date in the file name (gal_20260915.csv), else today."""
    if override:
        return override
    name = re.sub(r"^\d{8}-\d{6}_", "", csv_path.name)   # archive prefix added by upload / inbox
    m = DATE_IN_NAME.search(name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.now(timezone.utc).date().isoformat()


def ingest(csv_path: Path, data_dir: Path, log=print, as_of: str | None = None, before_swap=None) -> dict:
    t0 = time.time()
    rules = R.load(data_dir)
    final = data_dir / "org.db"
    tmp = data_dir / "org.db.building"
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm"), Path(str(tmp) + "-journal")):
        if p.exists():
            p.unlink()
    sha = hashlib.sha256()
    with csv_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)

    conn = sqlite3.connect(tmp)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(dbm.SCHEMA)
    it = rows(csv_path)
    header = next(it)
    cmap = P.map_columns(header)
    idx = {f: header.index(h) for f, h in cmap.items()}
    mapped = set(cmap.values())
    extra_idx = [(i, h) for i, h in enumerate(header) if h not in mapped][:40]
    if "display" not in idx and not ("first" in idx and "last" in idx) and "email" not in idx:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise ValueError(f"no DisplayName / name / email column found in {csv_path.name}; headers: {header[:12]}")

    # first pass: learn the OU structure (which depth holds sites) from DN/OU and City only
    learner, roots = prepass(csv_path, idx)
    levels = learner.result()
    folds, suggestions = plan_folds(roots, rules)
    if folds:
        log(f"  folding {len(folds):,} drifted unit spellings")
    b = Builder(data_dir, rules, levels, fold.mapping(folds))
    ins = f"INSERT INTO objects ({','.join(dbm.OBJECT_COLS)}) VALUES ({','.join('?' * len(dbm.OBJECT_COLS))})"
    batch, mem_batch, n_rows = [], [], 0
    for r in it:
        n_rows += 1
        row = {f: (r[i] if i < len(r) else "") for f, i in idx.items()}
        extras = {h: r[i][:200] for i, h in extra_idx if i < len(r) and r[i].strip()}
        if row.get("managedby", "").strip():
            extras["ManagedBy"] = row["managedby"].strip()[:400]
        rec = b.record(row, extras)
        if rec is None:
            continue
        batch.append(rec)
        key = rec[0]
        for m in P.split_multi(row.get("members", "")):
            mem_batch.append((key, m.lower()))
        for g in P.split_multi(row.get("memberof", "")):
            mem_batch.append((f"@{g.lower()}", key))   # reversed: resolved below
        if len(batch) >= BATCH:
            conn.executemany(ins, batch)
            batch.clear()
        if len(mem_batch) >= BATCH:
            conn.executemany("INSERT INTO stage_members VALUES (?,?)", mem_batch)
            mem_batch.clear()
        if n_rows % 50000 == 0:
            log(f"  … {n_rows:,} rows")
    if batch:
        conn.executemany(ins, batch)
    if mem_batch:
        conn.executemany("INSERT INTO stage_members VALUES (?,?)", mem_batch)
    conn.commit()

    # managers (by DN, then by email) and members — each join is a separate indexed lookup
    log("  linking managers and members")
    conn.execute("CREATE INDEX ob_dn ON objects(dn COLLATE NOCASE)")
    conn.execute("CREATE INDEX ob_email ON objects(email COLLATE NOCASE)")
    conn.execute("""UPDATE objects SET manager_key = (SELECT m.key FROM objects m WHERE m.dn = objects.manager_dn COLLATE NOCASE LIMIT 1)
        WHERE manager_dn <> '' AND instr(manager_dn, '=') > 0""")
    conn.execute("""UPDATE objects SET manager_key = (SELECT m.key FROM objects m WHERE m.email = objects.manager_dn COLLATE NOCASE LIMIT 1)
        WHERE manager_key IS NULL AND instr(manager_dn, '@') > 0""")
    conn.execute("CREATE INDEX tmp_sm ON stage_members(group_key)")
    for via in ("dn", "email"):
        # Members column: (group key, member DN/email)
        conn.execute(f"""INSERT OR IGNORE INTO members
            SELECT g.id, m.id FROM stage_members s JOIN objects g ON g.key = s.group_key
            JOIN objects m ON m.{via} = s.ref COLLATE NOCASE WHERE substr(s.group_key, 1, 1) <> '@'""")
        # MemberOf column: ('@' + group DN/email, member key)
        conn.execute(f"""INSERT OR IGNORE INTO members
            SELECT g.id, m.id FROM stage_members s JOIN objects m ON m.key = s.ref
            JOIN objects g ON g.{via} = substr(s.group_key, 2) COLLATE NOCASE WHERE substr(s.group_key, 1, 1) = '@'""")
    conn.execute("DROP TABLE stage_members")

    orgs = build_orgs(b, manager_links(conn))
    write_orgs(conn, orgs)
    write_fns(conn)
    conn.executemany(
        "INSERT INTO locations VALUES (:id,:name,:full,:lat,:lon,:tz,:country,:state,:region,:approx,:ou,:total,:people)",
        [{**loc, "total": b.loc_total[lid], "people": b.loc_people[lid]} for lid, loc in b.locs.items()])
    save_learned(conn, learner, levels)
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                     [("folds", json.dumps(folds)), ("fold_suggestions", json.dumps(suggestions)),
                      ("schema", str(dbm.SCHEMA_VERSION))])
    log("  indexing")
    conn.executescript(dbm.INDEXES)
    if dbm.has_fts5():
        conn.executescript(dbm.FTS)
    # statistics, so the query planner knows which indexes narrow a search (without them it
    # guesses, and picks scans over a million rows)
    conn.execute("PRAGMA analysis_limit = 2000")
    conn.execute("ANALYZE")
    conn.commit()

    # history: carry forward + diff against the previous build
    taken = datetime.now(timezone.utc).isoformat(timespec="seconds")
    people = b.stats["kind_person"]
    snap_cols = json.dumps({"mapped": cmap, "extra": [h for _, h in extra_idx]})
    old_objects = False
    if final.exists():
        conn.execute("ATTACH DATABASE ? AS old", (str(final),))
        names = {r[0] for r in conn.execute("SELECT name FROM old.sqlite_master")}
        if "snapshots" in names:
            cols = [r[1] for r in conn.execute("PRAGMA old.table_info(snapshots)")]
            conn.execute(f"INSERT INTO snapshots ({','.join(cols)}) SELECT {','.join(cols)} FROM old.snapshots")
            conn.execute("UPDATE snapshots SET as_of = substr(taken_at, 1, 10) WHERE as_of IS NULL")
            conn.execute("INSERT INTO events SELECT * FROM old.events")
        old_objects = "objects" in names
    conn.execute(
        "INSERT INTO snapshots (taken_at, source, rows, objects, people, orgs, locations, parsed_names, unplaced,"
        " skipped, sha, columns, seconds, as_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (taken, csv_path.name, n_rows, len(b.keys), people, len(orgs), len(b.locs), b.stats["parsed_names"],
         b.stats["unplaced"], b.stats["skipped_kind"] + b.stats["skipped_state"], sha.hexdigest(), snap_cols, 0, as_of_date(csv_path, as_of)))
    snap_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    events = 0
    if old_objects:
        for etype, src, before, after, where in DIFF:
            events += conn.execute(diff_sql(snap_id, etype, src, before, after, where)).rowcount
    conn.commit()
    if final.exists():
        conn.execute("DETACH DATABASE old")
    secs = round(time.time() - t0, 2)
    conn.execute("UPDATE snapshots SET seconds = ? WHERE id = ?", (secs, snap_id))
    conn.commit()
    conn.close()
    if before_swap:
        before_swap()          # let readers close their handles to the old file
    for attempt in range(50):  # Windows refuses to replace a file a reader still holds open
        try:
            os.replace(tmp, final)
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.2)
    dbm.init_annotations(data_dir)

    meta = {
        "snapshot": snap_id, "rows": n_rows, "objects": len(b.keys), "people": people, "orgs": len(orgs),
        "locations": len(b.locs), "parsedNames": b.stats["parsed_names"], "unplaced": b.stats["unplaced"],
        "skipped": b.stats["skipped_kind"] + b.stats["skipped_state"], "events": events, "seconds": secs,
        "kinds": {k[5:]: v for k, v in b.stats.items() if k.startswith("kind_")},
        "columns": cmap,
    }
    log(f"ingested {n_rows:,} rows → {len(b.keys):,} objects ({people:,} people), {len(orgs):,} orgs, "
        f"{len(b.locs):,} locations, {events:,} change events in {secs}s")
    return meta
