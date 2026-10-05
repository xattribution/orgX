"""JSON API. Every handler takes (ctx, params, body) and returns a JSON-able value
or a (bytes, content_type, filename) tuple for downloads."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import threading
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import db as dbm
from . import ingest as ing
from . import reference as ref
from . import adsync, groups, mail, route
from . import rules as R
from .query import ORDER, compile_query

ROW_COLS = ("o.key, o.kind, o.name, o.first, o.last, o.mi, o.display, o.rank, o.grade, o.title, o.org_id, o.loc_id, o.phone, o.dsn, "
            "o.mobile, o.email, o.fn, o.fns, o.leader, o.category, o.tier, o.disabled, o.office, o.career, "
            "o.service, o.region, o.country, o.level, o.manager_key, l.name AS loc_name, l.tz AS tz, l.approx AS loc_approx, "
            "CASE WHEN n.key IS NULL THEN 0 ELSE 1 END AS noted")
ROW_FROM = "objects o LEFT JOIN locations l ON l.id = o.loc_id LEFT JOIN ann.notes n ON n.key = o.key"


class Ctx:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.job = {"running": False, "log": [], "result": None, "error": None, "started": None, "source": None}
        self.lock = threading.Lock()

    def conn(self) -> sqlite3.Connection | None:
        return dbm.connect(self.data_dir)

    def rules(self):
        return R.load(self.data_dir)

    def latest_snap(self, conn) -> int:
        r = conn.execute("SELECT max(id) FROM snapshots").fetchone()
        return r[0] or 0


class NoData(Exception):
    pass


def need(ctx: Ctx) -> sqlite3.Connection:
    c = ctx.conn()
    if c is None:
        raise NoData()
    return c


def _int(v, d, lo=0, hi=10**9):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return d


def rowdict(r) -> dict:
    return {k: r[k] for k in r.keys()}


# ---------------------------------------------------------------- meta
def meta(ctx, p, b):
    conn = ctx.conn()
    base = {
        "functions": [{"id": k, "label": v} for k, v in ref.FUNCTIONS],
        "kinds": [{"id": k, "label": v} for k, v in ref.KINDS],
        "tiers": [{"id": k, "label": v} for k, v in ref.TIER_LABEL.items()],
        "job": job_status(ctx, p, b),
        "fts": dbm.has_fts5(),
    }
    if conn is None:
        return {**base, "empty": True}
    snaps = [rowdict(r) for r in conn.execute(
        "SELECT id, taken_at, as_of, source, rows, objects, people, orgs, locations, unplaced, seconds FROM snapshots ORDER BY id")]
    kinds = dict(conn.execute("SELECT kind, count(*) FROM objects GROUP BY kind").fetchall())
    regions = [rowdict(r) for r in conn.execute(
        "SELECT region AS id, count(*) AS n FROM objects WHERE region <> '' GROUP BY region ORDER BY n DESC")]
    return {**base, "empty": False, "snapshots": snaps, "latest": snaps[-1] if snaps else None, "counts": kinds,
            "regions": regions,
            "orgs": conn.execute("SELECT count(*) FROM orgs").fetchone()[0],
            "locations": conn.execute("SELECT count(*) FROM locations").fetchone()[0]}


# ---------------------------------------------------------------- search & facets
def search(ctx, p, b):
    conn = need(ctx)
    q = p.get("q", "")
    c = compile_query(conn, q, ctx.latest_snap(conn))
    has_fts = dbm.has_fts5()
    limit = _int(p.get("limit"), 100, 1, 1000)
    offset = _int(p.get("offset"), 0)
    sort = p.get("sort") or ("relevance" if c.fts else "smart")
    where, params = c.sql(has_fts=has_fts)
    total = conn.execute(f"SELECT count(*) FROM objects o WHERE {where}", params).fetchone()[0]
    if sort == "relevance" and c.fts and has_fts:
        w2, p2 = Compiled_no_fts(c, has_fts)
        match = " AND ".join(c.fts) + ("".join(f" NOT {t}" for t in c.fts_neg))
        sql = (f"SELECT {ROW_COLS} FROM {ROW_FROM} JOIN (SELECT rowid, bm25(objects_fts, {_W}) AS score "
               f"FROM objects_fts WHERE objects_fts MATCH ?) f ON f.rowid = o.id WHERE {w2} "
               f"ORDER BY CASE o.kind WHEN 'person' THEN 0 WHEN 'orgbox' THEN 0 ELSE 1 END, "
               f"f.score - o.leader / 40.0 LIMIT ? OFFSET ?")
        rows = conn.execute(sql, [match] + p2 + [limit, offset]).fetchall()
    else:
        order = ORDER.get(sort, ORDER["smart"])
        rows = conn.execute(f"SELECT {ROW_COLS} FROM {ROW_FROM} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                            params + [limit, offset]).fetchall()
    return {"total": total, "offset": offset, "rows": [rowdict(r) for r in rows], "chips": c.chips,
            "orgs": c.org_ids, "sort": sort}


_W = "10.0, 3.0, 5.0, 3.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0"


def Compiled_no_fts(c, has_fts):
    saved, saved_neg = c.fts, c.fts_neg
    c.fts, c.fts_neg = [], []
    try:
        return c.sql(has_fts=has_fts)
    finally:
        c.fts, c.fts_neg = saved, saved_neg


def facets(ctx, p, b):
    conn = need(ctx)
    q = p.get("q", "")
    c = compile_query(conn, q, ctx.latest_snap(conn))
    has_fts = dbm.has_fts5()
    out = {}

    def counts(field, expr, extra_join="", limit=40, where_extra=""):
        w, prm = c.sql(skip_field=field, has_fts=has_fts)
        sql = (f"SELECT {expr} AS v, count(*) AS n FROM objects o {extra_join} WHERE {w} {where_extra} "
               f"GROUP BY v ORDER BY n DESC LIMIT {limit}")
        return [[r["v"], r["n"]] for r in conn.execute(sql, prm) if r["v"] not in (None, "")]

    out["kind"] = counts("kind", "o.kind")
    out["fn"] = counts("fn", "o.fn", where_extra="AND o.kind = 'person'")
    out["tier"] = counts("tier", "o.tier", where_extra="AND o.kind = 'person'")
    out["region"] = counts("region", "o.region")
    out["loc"] = [[v, n] for v, n in counts("loc", "o.loc_id", limit=60)]
    names = {r["id"]: (r["name"], r["approx"]) for r in conn.execute("SELECT id, name, approx FROM locations")}
    out["loc"] = [[v, names.get(v, (v, 0))[0], n, names.get(v, (v, 0))[1]] for v, n in out["loc"]]
    # org facet drills: children of the selected org, else top-level units
    parent = c.org_ids[0] if len(c.org_ids) == 1 else None
    w, prm = c.sql(skip_field="org", has_fts=has_fts)
    if parent:
        kids = conn.execute("SELECT id, name, lft, rgt FROM orgs WHERE parent = ? ORDER BY sort", (parent,)).fetchall()
        prow = conn.execute("SELECT id, name, parent, lft FROM orgs WHERE id = ?", (parent,)).fetchone()
        w2, prm2 = c.sql(has_fts=has_fts)
        items = []
        for k in kids:
            n = conn.execute(f"SELECT count(*) FROM objects o WHERE {w2} AND o.org_lft BETWEEN ? AND ?",
                             prm2 + [k["lft"], k["rgt"]]).fetchone()[0]
            if n:
                items.append([k["id"], k["name"], n])
        direct = conn.execute(f"SELECT count(*) FROM objects o WHERE {w2} AND o.org_lft = ?", prm2 + [prow["lft"]]).fetchone()[0]
        out["org"] = {"parent": dict(prow), "items": items, "direct": direct}
    else:
        rows = conn.execute(
            f"SELECT r.id, r.name, count(*) AS n FROM objects o JOIN orgs r ON r.depth = 0 AND o.org_lft BETWEEN r.lft AND r.rgt "
            f"WHERE {w} GROUP BY r.id ORDER BY n DESC LIMIT 60", prm).fetchall()
        out["org"] = {"parent": None, "items": [[r["id"], r["name"], r["n"]] for r in rows]}
    return out


# ---------------------------------------------------------------- object detail
def obj(ctx, p, b):
    conn = need(ctx)
    key = p.get("key", "")
    r = conn.execute(f"SELECT o.*, l.name AS loc_name, l.full AS loc_full, l.tz AS tz, l.lat, l.lon, l.approx AS loc_approx, "
                     f"l.region AS loc_region FROM objects o LEFT JOIN locations l ON l.id = o.loc_id WHERE o.key = ?",
                     (key,)).fetchone()
    if not r:
        return {"error": "not found"}
    o = rowdict(r)
    o["extra"] = json.loads(o["extra"]) if o.get("extra") else {}
    # org ancestry with leaders
    org = conn.execute("SELECT * FROM orgs WHERE id = ?", (o["org_id"],)).fetchone() if o["org_id"] else None
    chain = []
    if org:
        for a in conn.execute("SELECT a.id, a.name, a.kind, a.fn, a.people, a.leader_key, a.inferred, ob.name AS leader_name, "
                              "ob.rank AS leader_rank, ob.title AS leader_title FROM orgs a LEFT JOIN objects ob ON ob.key = a.leader_key "
                              "WHERE a.lft <= ? AND a.rgt >= ? ORDER BY a.lft", (org["lft"], org["rgt"])):
            chain.append(rowdict(a))
    o["org_chain"] = chain
    # manager chain
    mgrs, seen, cur = [], {key}, o.get("manager_key")
    while cur and cur not in seen and len(mgrs) < 12:
        seen.add(cur)
        m = conn.execute("SELECT key, name, rank, title, org_id, manager_key FROM objects WHERE key = ?", (cur,)).fetchone()
        if not m:
            break
        mgrs.append(rowdict(m))
        cur = m["manager_key"]
    o["managers"] = mgrs
    o["reports"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, rank, title, org_id, kind, (SELECT count(*) FROM objects z WHERE z.manager_key = objects.key) AS n "
        "FROM objects WHERE manager_key = ? ORDER BY leader DESC, level DESC, sort_name LIMIT 150", (key,))]
    o["rollup"] = conn.execute(
        "WITH RECURSIVE chain(k, d) AS (SELECT key, 0 FROM objects WHERE manager_key = ? UNION "
        "SELECT x.key, d + 1 FROM objects x JOIN chain ON x.manager_key = chain.k WHERE d < 25) SELECT count(*) FROM chain",
        (key,)).fetchone()[0] if o["reports"] else 0
    if o["org_id"]:
        o["peers"] = [rowdict(x) for x in conn.execute(
            "SELECT key, name, rank, title, kind FROM objects WHERE org_id = ? AND key <> ? AND kind = 'person' "
            "ORDER BY leader DESC, level DESC, sort_name LIMIT 40", (o["org_id"], key))]
        ids = [c["id"] for c in chain][::-1]
        o["orgboxes"] = []
        for oid in ids:
            for x in conn.execute("SELECT key, name, email, phone, org_id FROM objects WHERE kind = 'orgbox' AND org_id = ? "
                                  "AND key <> ? LIMIT 3", (oid, key)):
                o["orgboxes"].append(rowdict(x))
            if len(o["orgboxes"]) >= 3:
                break
    o["groups"] = [rowdict(x) for x in conn.execute(
        "SELECT g.key, g.name, g.email, (SELECT count(*) FROM members m2 WHERE m2.group_id = g.id) AS n FROM members m "
        "JOIN objects g ON g.id = m.group_id WHERE m.member_id = ? ORDER BY g.name LIMIT 200", (o["id"],))]
    if o["kind"] == "group":
        o["member_count"] = conn.execute("SELECT count(*) FROM members WHERE group_id = ?", (o["id"],)).fetchone()[0]
        o["members"] = [rowdict(x) for x in conn.execute(
            "SELECT x.key, x.name, x.rank, x.title, x.org_id, x.kind FROM members m JOIN objects x ON x.id = m.member_id "
            "WHERE m.group_id = ? ORDER BY x.org_lft, x.leader DESC, x.level DESC LIMIT 400", (o["id"],))]
        mb = o["extra"].get("ManagedBy")
        if mb:
            owner = conn.execute("SELECT key, name, rank, title FROM objects WHERE lower(dn) = lower(?) OR lower(email) = lower(?)",
                                 (mb, mb)).fetchone()
            o["owner"] = rowdict(owner) if owner else {"name": mb}
    o["history"] = [rowdict(x) for x in conn.execute(
        "SELECT e.type, e.before, e.after, s.as_of AS taken_at, s.id AS snap FROM events e JOIN snapshots s ON s.id = e.snap "
        "WHERE e.key = ? ORDER BY e.snap DESC, e.id", (key,))]
    first = conn.execute("SELECT min(s.as_of) FROM events e JOIN snapshots s ON s.id = e.snap WHERE e.key = ? AND e.type = 'joined'",
                         (key,)).fetchone()[0]
    o["first_seen"] = first
    n = conn.execute("SELECT * FROM ann.notes WHERE key = ?", (key,)).fetchone()
    o["note"] = {"notes": n["notes"], "tags": json.loads(n["tags"]), "contact_for": json.loads(n["contact_for"]),
                 "updated_at": n["updated_at"], "updated_by": n["updated_by"]} if n else None
    o["lists"] = [rowdict(x) for x in conn.execute(
        "SELECT l.id, l.name FROM ann.list_members m JOIN ann.lists l ON l.id = m.list_id WHERE m.key = ?", (key,))]
    o.pop("phone_digits", None)
    return o


# ---------------------------------------------------------------- orgs
def org(ctx, p, b):
    conn = need(ctx)
    oid = p.get("id", "")
    r = conn.execute("SELECT * FROM orgs WHERE id = ?", (oid,)).fetchone()
    if not r:
        return {"error": "not found"}
    o = rowdict(r)
    lft, rgt = o["lft"], o["rgt"]
    o["chain"] = [rowdict(a) for a in conn.execute("SELECT id, name, kind FROM orgs WHERE lft < ? AND rgt > ? ORDER BY lft", (lft, rgt))]
    if o["leader_key"]:
        lr = conn.execute("SELECT key, name, rank, title, email, phone, loc_id FROM objects WHERE key = ?", (o["leader_key"],)).fetchone()
        o["leader"] = rowdict(lr) if lr else None
    o["leadership"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, rank, title, leader FROM objects WHERE org_id = ? AND kind = 'person' AND leader > 0 "
        "ORDER BY leader DESC, level DESC LIMIT 6", (oid,))]
    o["children"] = [rowdict(x) for x in conn.execute(
        "SELECT c.id, c.name, c.kind, c.fn, c.people, c.total, c.inferred, c.locs, l.name AS loc_name, "
        "ob.name AS leader_name, ob.rank AS leader_rank, ob.title AS leader_title, ob.key AS leader_key, "
        "(SELECT count(*) FROM orgs g WHERE g.parent = c.id) AS kids FROM orgs c LEFT JOIN objects ob ON ob.key = c.leader_key "
        "LEFT JOIN locations l ON l.id = c.loc_id WHERE c.parent = ? ORDER BY c.sort", (oid,))]
    o["orgboxes"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, email, phone FROM objects WHERE kind = 'orgbox' AND org_id = ? ORDER BY name LIMIT 10", (oid,))]
    o["groups"] = [rowdict(x) for x in conn.execute(
        "SELECT g.key, g.name, g.email, (SELECT count(*) FROM members m WHERE m.group_id = g.id) AS n FROM objects g "
        "WHERE g.kind = 'group' AND g.org_lft BETWEEN ? AND ? ORDER BY n DESC LIMIT 12", (lft, rgt))]
    sub = "o.org_lft BETWEEN ? AND ?"
    o["by_loc"] = [rowdict(x) for x in conn.execute(
        f"SELECT o.loc_id AS id, l.name, l.tz, l.approx, count(*) AS n FROM objects o LEFT JOIN locations l ON l.id = o.loc_id "
        f"WHERE {sub} AND o.kind = 'person' GROUP BY o.loc_id ORDER BY n DESC LIMIT 20", (lft, rgt))]
    o["by_cat"] = dict(conn.execute(f"SELECT category, count(*) FROM objects o WHERE {sub} AND kind = 'person' GROUP BY 1", (lft, rgt)).fetchall())
    o["by_tier"] = dict(conn.execute(f"SELECT tier, count(*) FROM objects o WHERE {sub} AND kind = 'person' GROUP BY 1", (lft, rgt)).fetchall())
    o["by_fn"] = dict(conn.execute(f"SELECT fn, count(*) FROM objects o WHERE {sub} AND kind = 'person' GROUP BY 1", (lft, rgt)).fetchall())
    snap = ctx.latest_snap(conn)
    o["changes"] = dict(conn.execute(
        "SELECT type, count(*) FROM events WHERE snap = ? AND kind = 'person' AND (org_id = ? OR org_id LIKE ?) GROUP BY type",
        (snap, oid, oid + "/%")).fetchall())
    o["members"] = [rowdict(x) for x in conn.execute(
        f"SELECT {ROW_COLS} FROM {ROW_FROM} WHERE o.org_id = ? ORDER BY CASE o.kind WHEN 'person' THEN 0 ELSE 1 END, "
        f"o.leader DESC, o.level DESC, o.sort_name LIMIT 300", (oid,))]
    return o


def orgtree(ctx, p, b):
    """Nested tree for the chart. root='' → top-level units."""
    conn = need(ctx)
    root = p.get("root") or None
    depth = _int(p.get("depth"), 3, 1, 8)
    cap = _int(p.get("cap"), 40, 5, 200)
    nodes = {}

    def load_children(pid, d):
        if pid is None:
            rows = conn.execute("SELECT * FROM orgs WHERE parent IS NULL ORDER BY people DESC LIMIT ?", (cap,)).fetchall()
            total = conn.execute("SELECT count(*) FROM orgs WHERE parent IS NULL").fetchone()[0]
        else:
            rows = conn.execute("SELECT * FROM orgs WHERE parent = ? ORDER BY sort LIMIT ?", (pid, cap)).fetchall()
            total = conn.execute("SELECT count(*) FROM orgs WHERE parent = ?", (pid,)).fetchone()[0]
        out = []
        for r in rows:
            n = node(r)
            if d < depth:
                n["children"], n["more"] = load_children(r["id"], d + 1)
            else:
                n["children"], n["more"] = [], 0
            out.append(n)
        return out, max(0, total - len(rows))

    def node(r):
        lead = conn.execute("SELECT key, name, rank, title FROM objects WHERE key = ?", (r["leader_key"],)).fetchone() if r["leader_key"] else None
        kids = conn.execute("SELECT count(*) FROM orgs WHERE parent = ?", (r["id"],)).fetchone()[0]
        return {"id": r["id"], "name": r["name"], "kind": r["kind"], "fn": r["fn"], "people": r["people"], "total": r["total"],
                "inferred": r["inferred"], "kids": kids, "loc_id": r["loc_id"], "leader": rowdict(lead) if lead else None,
                "leader_by": r["leader_by"]}

    if root:
        r = conn.execute("SELECT * FROM orgs WHERE id = ?", (root,)).fetchone()
        if not r:
            return {"error": "not found"}
        n = node(r)
        n["children"], n["more"] = load_children(root, 1)
        n["chain"] = [rowdict(a) for a in conn.execute("SELECT id, name FROM orgs WHERE lft < ? AND rgt > ? ORDER BY lft", (r["lft"], r["rgt"]))]
        return n
    kids, more = load_children(None, 1)
    return {"id": "", "name": "All units", "kind": "root", "people": sum(k["people"] for k in kids), "children": kids,
            "more": more, "kids": len(kids) + more, "chain": []}


def orgs_children(ctx, p, b):
    conn = need(ctx)
    pid = p.get("parent") or None
    q = (p.get("q") or "").strip()
    if q:
        rows = conn.execute("SELECT id, name, parent, kind, fn, people, depth, (SELECT count(*) FROM orgs g WHERE g.parent = orgs.id) AS kids "
                            "FROM orgs WHERE id LIKE ? OR name LIKE ? ORDER BY people DESC LIMIT 60", (f"%{q}%", f"{q}%")).fetchall()
    elif pid is None:
        rows = conn.execute("SELECT id, name, parent, kind, fn, people, depth, (SELECT count(*) FROM orgs g WHERE g.parent = orgs.id) AS kids "
                            "FROM orgs WHERE parent IS NULL ORDER BY people DESC").fetchall()
    else:
        rows = conn.execute("SELECT id, name, parent, kind, fn, people, depth, (SELECT count(*) FROM orgs g WHERE g.parent = orgs.id) AS kids "
                            "FROM orgs WHERE parent = ? ORDER BY sort", (pid,)).fetchall()
    return [rowdict(r) for r in rows]


# ---------------------------------------------------------------- map
def locations(ctx, p, b):
    conn = need(ctx)
    c = compile_query(conn, p.get("q", ""), ctx.latest_snap(conn))
    w, prm = c.sql(has_fts=dbm.has_fts5())
    rows = conn.execute(
        f"SELECT l.*, count(o.id) AS n, sum(o.kind = 'person') AS np FROM objects o JOIN locations l ON l.id = o.loc_id "
        f"WHERE {w} GROUP BY l.id ORDER BY n DESC", prm).fetchall()
    mix = defaultdict(dict)
    for r in conn.execute(f"SELECT o.loc_id, o.fn, count(*) FROM objects o WHERE {w} AND o.kind = 'person' GROUP BY 1, 2", prm):
        mix[r[0]][r[1] or ""] = r[2]
    units = defaultdict(list)
    for r in conn.execute(
            f"SELECT o.loc_id, g.site, count(*) AS n FROM objects o JOIN orgs g ON g.id = o.org_id "
            f"WHERE {w} GROUP BY 1, 2 ORDER BY n DESC", prm):
        if len(units[r[0]]) < 5:
            units[r[0]].append([r[1], r[2]])
    out = []
    for r in rows:
        d = rowdict(r)
        d["mix"] = mix.get(r["id"], {})
        d["units"] = units.get(r["id"], [])
        out.append(d)
    unplaced = conn.execute(f"SELECT count(*) FROM objects o WHERE {w} AND (o.loc_id = '' OR o.loc_id IS NULL)", prm).fetchone()[0]
    return {"locations": out, "unplaced": unplaced}


def location(ctx, p, b):
    conn = need(ctx)
    lid = p.get("id", "")
    r = conn.execute("SELECT * FROM locations WHERE id = ?", (lid,)).fetchone()
    if not r:
        return {"error": "not found"}
    o = rowdict(r)
    o["units"] = [rowdict(x) for x in conn.execute(
        "SELECT s.id, s.name, s.fn, s.parent, count(*) AS n FROM objects ob JOIN orgs g ON g.id = ob.org_id "
        "JOIN orgs s ON s.id = g.site WHERE ob.loc_id = ? AND ob.kind = 'person' GROUP BY s.id ORDER BY n DESC LIMIT 30", (lid,))]
    o["by_fn"] = dict(conn.execute("SELECT fn, count(*) FROM objects WHERE loc_id = ? AND kind = 'person' GROUP BY 1", (lid,)).fetchall())
    o["by_cat"] = dict(conn.execute("SELECT category, count(*) FROM objects WHERE loc_id = ? AND kind = 'person' GROUP BY 1", (lid,)).fetchall())
    o["leaders"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, rank, title, org_id FROM objects WHERE loc_id = ? AND kind = 'person' AND leader >= 90 "
        "ORDER BY level DESC, leader DESC LIMIT 12", (lid,))]
    o["orgboxes"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, email FROM objects WHERE loc_id = ? AND kind = 'orgbox' ORDER BY name LIMIT 30", (lid,))]
    o["resources"] = [rowdict(x) for x in conn.execute(
        "SELECT key, name, email FROM objects WHERE loc_id = ? AND kind = 'resource' ORDER BY name LIMIT 30", (lid,))]
    o["ous"] = [rowdict(x) for x in conn.execute(
        "SELECT ou_path AS ou, count(*) AS n FROM objects WHERE loc_id = ? GROUP BY ou_path ORDER BY n DESC LIMIT 10", (lid,))]
    return o


# ---------------------------------------------------------------- ask
def ask(ctx, p, b):
    conn = need(ctx)
    home = {"org": p.get("home_org", ""), "loc": p.get("home_loc", "")}
    return route.ask(conn, p.get("q", ""), R.topics(ctx.rules()), scope=p.get("scope", ""), home=home,
                     limit=_int(p.get("limit"), 12, 1, 50))


def topics(ctx, p, b):
    return [{"id": t["id"], "label": t["label"], "aliases": t["aliases"], "fns": t["fns"], "codes": t["codes"],
             "user": bool(t.get("user"))} for t in R.topics(ctx.rules())]


# ---------------------------------------------------------------- changes
def changes(ctx, p, b):
    conn = need(ctx)
    snaps = [rowdict(r) for r in conn.execute("SELECT id, taken_at, as_of, source, people, objects FROM snapshots ORDER BY id")]
    if not snaps:
        return {"snapshots": [], "summary": {}, "rows": []}
    snap = _int(p.get("snap"), snaps[-1]["id"])
    kind = p.get("kind", "person")
    etype = p.get("type", "")
    org = p.get("org", "")
    cond, prm = ["e.snap = ?"], [snap]
    if kind:
        cond.append("e.kind = ?")
        prm.append(kind)
    if org:
        cond.append("(e.org_id = ? OR e.org_id LIKE ? OR e.before = ? OR e.before LIKE ?)")
        prm += [org, org + "/%", org, org + "/%"]
    w = " AND ".join(cond)
    summary = dict(conn.execute(f"SELECT e.type, count(*) FROM events e WHERE {w} GROUP BY e.type", prm).fetchall())
    rcond, rprm = w, list(prm)
    if etype:
        rcond += " AND e.type = ?"
        rprm.append(etype)
    rows = [rowdict(r) for r in conn.execute(
        f"SELECT e.*, l.name AS loc_name FROM events e LEFT JOIN locations l ON l.id = e.loc_id WHERE {rcond} "
        f"ORDER BY CASE e.type WHEN 'joined' THEN 0 WHEN 'departed' THEN 1 WHEN 'moved' THEN 2 WHEN 'promoted' THEN 3 ELSE 4 END, "
        f"e.org_id, e.level DESC LIMIT ?", rprm + [_int(p.get("limit"), 500, 1, 5000)])]
    by_org = defaultdict(Counter)
    for r in conn.execute(f"SELECT e.type, e.org_id, e.before FROM events e WHERE {w} AND e.type IN ('joined','departed','moved')", prm):
        if r["type"] == "joined":
            by_org[(r["org_id"] or "").split("/")[0]]["in"] += 1
        elif r["type"] == "departed":
            by_org[(r["before"] or r["org_id"] or "").split("/")[0]]["out"] += 1
        else:
            by_org[(r["before"] or "").split("/")[0]]["out_moved"] += 1
            by_org[(r["org_id"] or "").split("/")[0]]["in_moved"] += 1
    by_org_list = sorted(([k or "(no org)", v["in"], v["out"], v["in_moved"], v["out_moved"]] for k, v in by_org.items()),
                         key=lambda x: -(x[1] + x[2] + x[3] + x[4]))[:40]
    return {"snapshots": snaps, "snap": snap, "summary": summary, "rows": rows, "by_org": by_org_list}


# ---------------------------------------------------------------- quality
def quality(ctx, p, b):
    conn = need(ctx)
    P = "kind = 'person'"
    issues = []

    def add(iid, label, n, query, sev, help_=""):
        issues.append({"id": iid, "label": label, "count": n, "query": query, "severity": sev, "help": help_})

    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    add("no-email", "People without an email address", one(f"SELECT count(*) FROM objects WHERE {P} AND email = ''"),
        "kind:person missing:email", "warn")
    add("no-phone", "People without a phone", one(f"SELECT count(*) FROM objects WHERE {P} AND phone = '' AND dsn = '' AND mobile = ''"),
        "kind:person missing:phone", "info")
    add("no-org", "People with no Department / org", one(f"SELECT count(*) FROM objects WHERE {P} AND org_id = ''"),
        "kind:person missing:org", "warn", "Department is empty and the display name carries no org path.")
    add("no-loc", "Objects with no location at all", one("SELECT count(*) FROM objects WHERE loc_id = ''"), "missing:loc", "warn",
        "No installation OU, office, city or country matched anything.")
    add("approx", "Objects placed approximately (state / country centroid)",
        one("SELECT count(*) FROM objects WHERE loc_id IN (SELECT id FROM locations WHERE approx = 1)"), "is:approx", "info",
        "Add the site to data/sites.json with coordinates, or alias it to a known site under Rules.")
    add("no-rank", "People whose rank / grade could not be read", one(f"SELECT count(*) FROM objects WHERE {P} AND grade = ''"),
        "kind:person missing:rank", "info")
    add("dup-email", "Email addresses shared by more than one object",
        one("SELECT count(*) FROM (SELECT email FROM objects WHERE email <> '' GROUP BY lower(email) HAVING count(*) > 1)"),
        "", "warn")
    add("mgr-unresolved", "Manager set but not found in this export",
        one("SELECT count(*) FROM objects WHERE manager_dn <> '' AND manager_key IS NULL"), "", "info",
        "The manager's account is outside the exported scope.")
    add("no-leader", "Orgs (3+ people) with no title-based leader",
        one("SELECT count(*) FROM orgs WHERE people >= 3 AND IFNULL(leader_by, '') <> 'title' AND direct > 0"), "", "info",
        "Leader falls back to the most senior member.")
    add("disabled", "Disabled accounts included", one(f"SELECT count(*) FROM objects WHERE {P} AND disabled = 1"), "is:disabled", "info")
    approx = [rowdict(r) for r in conn.execute(
        "SELECT id, name, full, region, country, state, people, total, ou FROM locations WHERE approx = 1 ORDER BY total DESC LIMIT 50")]
    dups = [rowdict(r) for r in conn.execute(
        "SELECT lower(email) AS email, count(*) AS n, group_concat(name, ' · ') AS names FROM objects WHERE email <> '' "
        "GROUP BY lower(email) HAVING count(*) > 1 ORDER BY n DESC LIMIT 30")]
    leaderless = [rowdict(r) for r in conn.execute(
        "SELECT o.id, o.people, ob.name AS senior, ob.rank FROM orgs o LEFT JOIN objects ob ON ob.key = o.leader_key "
        "WHERE o.people >= 3 AND IFNULL(o.leader_by, '') <> 'title' AND o.direct > 0 ORDER BY o.people DESC LIMIT 30")]
    inferred = [rowdict(r) for r in conn.execute(
        "SELECT id, parent, inferred FROM orgs WHERE inferred <> '' AND inferred <> 'office symbol' ORDER BY inferred, id LIMIT 100")]
    snap = conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    cols = json.loads(snap["columns"]) if snap and snap["columns"] else {}
    return {"issues": issues, "approx": approx, "dups": dups, "leaderless": leaderless, "inferred": inferred,
            "columns": cols, "snapshot": rowdict(snap) if snap else None}


# ---------------------------------------------------------------- export
def export(ctx, p, b):
    conn = need(ctx)
    c = compile_query(conn, p.get("q", ""), ctx.latest_snap(conn))
    w, prm = c.sql(has_fts=dbm.has_fts5())
    keys = [k for k in (p.get("keys") or "").split(",") if k]
    if keys:
        w, prm = f"o.key IN ({','.join('?' * len(keys))})", keys
    fmt = p.get("format", "csv")
    rows = conn.execute(f"SELECT {ROW_COLS} FROM {ROW_FROM} WHERE {w} ORDER BY {ORDER['org']} LIMIT 100000", prm).fetchall()
    stamp = datetime.now().strftime("%Y%m%d")
    if fmt == "emails":
        emails = sorted({r["email"] for r in rows if r["email"]}, key=str.lower)
        return ("; ".join(emails).encode(), "text/plain; charset=utf-8", None)
    if fmt == "vcf":
        out = io.StringIO()
        for r in rows:
            n = conn.execute("SELECT first, last FROM objects WHERE key = ?", (r["key"],)).fetchone()
            out.write("BEGIN:VCARD\r\nVERSION:3.0\r\n")
            out.write(f"N:{_v(n['last'])};{_v(n['first'])};;{_v(r['rank'])};\r\n" if r["kind"] == "person" else f"N:{_v(r['name'])};;;;\r\n")
            out.write(f"FN:{_v(((r['rank'] or '') + ' ' + r['name']).strip())}\r\n")
            if r["title"]:
                out.write(f"TITLE:{_v(r['title'])}\r\n")
            if r["org_id"]:
                out.write(f"ORG:{_v(r['org_id'].replace('/', ';'))}\r\n")
            if r["email"]:
                out.write(f"EMAIL;TYPE=WORK:{r['email']}\r\n")
            for ph, t in ((r["phone"], "WORK"), (r["dsn"], "WORK,DSN"), (r["mobile"], "CELL")):
                if ph:
                    out.write(f"TEL;TYPE={t}:{ph}\r\n")
            if r["loc_name"]:
                out.write(f"ADR;TYPE=WORK:;;;{_v(r['loc_name'])};;;\r\n")
            out.write("END:VCARD\r\n")
        return (out.getvalue().encode(), "text/vcard; charset=utf-8", f"contacts-{stamp}.vcf")
    out = io.StringIO()
    w_ = csv.writer(out)
    cols = ["kind", "rank", "name", "title", "org_id", "loc_name", "region", "email", "phone", "dsn", "mobile", "office",
            "career", "category", "fn"]
    w_.writerow(cols)
    for r in rows:
        w_.writerow([r[k] or "" for k in cols])
    return (out.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"directory-{stamp}.csv")


def _v(s):
    return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


# ---------------------------------------------------------------- annotations
def get_note(ctx, p, b):
    c = dbm.annotations(ctx.data_dir)
    r = c.execute("SELECT * FROM notes WHERE key = ?", (p.get("key", ""),)).fetchone()
    return rowdict(r) if r else None


def save_note(ctx, p, b):
    key = (b or {}).get("key")
    if not key:
        return {"error": "key required"}
    notes = str(b.get("notes", ""))[:5000]
    tags = sorted({re.sub(r"\s+", "-", t.strip().lower())[:40] for t in b.get("tags", []) if t.strip()})
    cf = [t.strip()[:80] for t in b.get("contact_for", []) if t.strip()][:20]
    c = dbm.annotations(ctx.data_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not notes and not tags and not cf:
        c.execute("DELETE FROM notes WHERE key = ?", (key,))
    else:
        c.execute("INSERT INTO notes (key, notes, tags, contact_for, updated_at, updated_by) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET notes=excluded.notes, tags=excluded.tags, contact_for=excluded.contact_for, "
                  "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                  (key, notes, json.dumps(tags), json.dumps(cf), now, str(b.get("by", ""))[:60]))
    c.commit()
    return {"ok": True}


def tags(ctx, p, b):
    c = dbm.annotations(ctx.data_dir)
    cnt = Counter()
    for r in c.execute("SELECT tags FROM notes WHERE tags <> '[]'"):
        cnt.update(json.loads(r[0]))
    routes = []
    for r in c.execute("SELECT key, contact_for FROM notes WHERE contact_for <> '[]'"):
        for t in json.loads(r[1]):
            routes.append({"key": r[0], "topic": t})
    return {"tags": cnt.most_common(), "routes": routes}


# ---------------------------------------------------------------- rules & ingest
def get_rules(ctx, p, b):
    r = ctx.rules()
    return {"rules": r, "defaults": {"fnKeywords": ref.DEFAULT_FN_KEYWORDS}, "bases": _bases(ctx), "learned": _learned(ctx)}


def _learned(ctx):
    """The site and region OU levels ingest found in the data, with a few example values."""
    conn = ctx.conn()
    if conn is None:
        return None
    try:
        levels = json.loads((conn.execute("SELECT v FROM meta WHERE k = 'ou_levels'").fetchone() or ["{}"])[0])
    except sqlite3.OperationalError:
        return None
    out = {}
    for role in ("site", "region"):
        d = levels.get(role)
        if d is not None:
            out[role] = {"depth": d, "examples": [r[0] for r in conn.execute(
                "SELECT value FROM ou_stats WHERE depth = ? ORDER BY n DESC LIMIT 3", (d,))]}
    return out


def _bases(ctx):
    from .geo import load_sites
    return [x["name"] for x in load_sites(ctx.data_dir) if x.get("name")]


def save_rules(ctx, p, b):
    cur = ctx.rules()
    cur.update({k: v for k, v in (b or {}).items() if k in R.DEFAULTS})
    return {"rules": R.save(ctx.data_dir, cur)}


def job_status(ctx, p, b):
    j = ctx.job
    return {k: j[k] for k in ("running", "result", "error", "started", "source")} | {"log": j["log"][-30:]}


def run_ingest_job(ctx: Ctx, source: str, work) -> bool:
    """Run `work(log) -> Path | [Path]` in a thread, then ingest what it returns (oldest first)."""
    with ctx.lock:
        if ctx.job["running"]:
            return False
        ctx.job.update(running=True, log=[], result=None, error=None,
                       started=datetime.now(timezone.utc).isoformat(timespec="seconds"), source=source)
    log = lambda m: ctx.job["log"].append(m)

    def go():
        try:
            paths = work(log)
            for path in paths if isinstance(paths, list) else [paths]:
                ctx.job["result"] = ing.ingest(path, ctx.data_dir, log=log)
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            ctx.job["error"] = f"{type(e).__name__}: {e}"
            log(traceback.format_exc(limit=3))
        finally:
            ctx.job["running"] = False

    threading.Thread(target=go, daemon=True).start()
    return True


def run_ingest(ctx: Ctx, path: Path) -> bool:
    return run_ingest_job(ctx, path.name, lambda log: path)


def demo(ctx, p, b):
    """Generate + ingest synthetic snapshots (oldest first) so every view has data to show."""
    import subprocess
    import sys

    def work(log):
        out = ctx.data_dir / "synthetic"
        tool = Path(__file__).resolve().parent.parent / "tools" / "make_synthetic.py"
        log("generating synthetic directory…")
        subprocess.run([sys.executable, str(tool), "--out", str(out)], check=True, capture_output=True)
        demo_sites, sites = out / "sites.json", ctx.data_dir / "sites.json"
        if demo_sites.exists() and not sites.exists():
            sites.write_bytes(demo_sites.read_bytes())     # demo coordinates; removed again on reset
        return sorted(out.glob("*.csv"))

    ok = run_ingest_job(ctx, "synthetic demo", work)
    return {"ok": ok, "error": None if ok else "an ingest is already running"}


def upload(ctx, p, b, raw: bytes = b"", filename: str = "upload.csv"):
    if not raw:
        return {"error": "empty upload"}
    src = ctx.data_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", filename)[-80:] or "upload.csv"
    path = src / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe}"
    path.write_bytes(raw)
    ok = run_ingest(ctx, path)
    return {"ok": ok, "source": path.name, "error": None if ok else "an ingest is already running"}


def reingest(ctx, p, b):
    src = ctx.data_dir / "sources"
    files = sorted(src.glob("*.csv"), key=lambda f: f.stat().st_mtime) if src.exists() else []
    if not files:
        return {"error": "no saved source to re-run; upload a CSV first"}
    return {"ok": run_ingest(ctx, files[-1]), "source": files[-1].name}


def reset(ctx, p, b):
    """Drop the directory and its history (e.g. after trying demo data). Team notes & lists are kept."""
    if ctx.job["running"]:
        return {"error": "an ingest is running"}
    for name in ("org.db", "org.db-wal", "org.db-shm"):
        f = ctx.data_dir / name
        if f.exists():
            f.unlink()
    demo_sites, sites = ctx.data_dir / "synthetic" / "sites.json", ctx.data_dir / "sites.json"
    if demo_sites.exists() and sites.exists() and sites.read_bytes() == demo_sites.read_bytes():
        sites.unlink()
    if (b or {}).get("demo_files"):
        import shutil
        shutil.rmtree(ctx.data_dir / "synthetic", ignore_errors=True)
    return {"ok": True}


def sources(ctx, p, b):
    out = {"inbox": str(ctx.data_dir / "inbox"), "files": []}
    src = ctx.data_dir / "sources"
    files = sorted(src.glob("*.csv"), key=lambda f: -f.stat().st_mtime) if src.exists() else []
    out["files"] = [{"name": f.name, "bytes": f.stat().st_size,
                     "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
                    for f in files[:50]]
    return out


GET = {
    "/api/meta": meta, "/api/search": search, "/api/facets": facets, "/api/object": obj, "/api/org": org,
    "/api/orgtree": orgtree, "/api/orgs": orgs_children, "/api/locations": locations, "/api/location": location,
    "/api/ask": ask, "/api/topics": topics, "/api/changes": changes, "/api/quality": quality, "/api/export": export,
    "/api/note": get_note, "/api/tags": tags, "/api/rules": get_rules, "/api/job": job_status, "/api/sources": sources,
    "/api/groups": groups.list_all, "/api/group": groups.get, "/api/group/export": groups.export,
    "/api/emails": mail.build, "/api/whoami": adsync.whoami, "/api/ad": adsync.status,
}
POST = {
    "/api/demo": demo, "/api/reset": reset, "/api/note": save_note, "/api/rules": save_rules, "/api/reingest": reingest,
    "/api/group": groups.save, "/api/group/import": groups.import_bundle, "/api/resolve": groups.resolve_text,
    "/api/ad/test": adsync.test, "/api/ad/sync": adsync.sync,
}
