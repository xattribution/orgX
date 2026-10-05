"""Groups: exercise cells, teams, distros, smart (saved-query) groups.

Stored in annotations.db so they survive every re-ingest. Members are either
directory objects (by key) or *external* contacts the directory doesn't hold
(partner-nation planners, contractors on another network). Groups travel
between servers as `.orgx.json` bundles; on import every member is re-resolved
against the local directory by key → email → UPN → name.
"""
from __future__ import annotations

import csv
import io
import json
import re
import socket
import uuid
from datetime import datetime, timezone

from . import db as dbm

PURPOSES = {"exercise": "Exercise", "team": "Team", "distro": "Distro", "watch": "Watch list", "other": "Other"}
MEMBER_FIELDS = ("role", "section", "note", "email", "phone", "rank", "title", "org", "name")
LIVE_COLS = ("o.key, o.kind, o.name, o.first, o.last, o.mi, o.rank, o.grade, o.title, o.org_id, o.loc_id, o.phone, o.dsn, o.mobile, o.email, "
             "o.fn, o.leader, o.category, o.disabled, o.upn, l.name AS loc_name, l.tz AS tz")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rowdict(r) -> dict:
    return {k: r[k] for k in r.keys()}


def _live(conn, keys: list[str]) -> dict[str, dict]:
    out = {}
    if conn is None:
        return out
    keys = [k for k in keys if k and not k.startswith("x:")]
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        for r in conn.execute(f"SELECT {LIVE_COLS} FROM objects o LEFT JOIN locations l ON l.id = o.loc_id "
                              f"WHERE o.key IN ({','.join('?' * len(chunk))})", chunk):
            out[r["key"]] = rowdict(r)
    return out


# ---------------------------------------------------------------- read
def list_all(ctx, p, b):
    c = dbm.annotations(ctx.data_dir)
    rows = [rowdict(r) for r in c.execute(
        "SELECT l.*, (SELECT count(*) FROM list_members m WHERE m.list_id = l.id) AS n FROM lists l "
        "ORDER BY CASE WHEN l.starts >= date('now') THEN 0 ELSE 1 END, l.starts, l.updated_at DESC")]
    for r in rows:
        r["links"] = json.loads(r.get("links") or "[]")
    return rows


def get(ctx, p, b):
    c = dbm.annotations(ctx.data_dir)
    lid = _int(p.get("id"))
    row = c.execute("SELECT * FROM lists WHERE id = ? OR uid = ?", (lid, p.get("id", ""))).fetchone()
    if not row:
        return {"error": "not found"}
    out = rowdict(row)
    out["links"] = json.loads(out.get("links") or "[]")
    members = [rowdict(r) for r in c.execute(
        "SELECT * FROM list_members WHERE list_id = ? ORDER BY section, sort, name", (row["id"],))]
    conn = ctx.conn()
    live = _live(conn, [m["key"] for m in members])
    for m in members:
        m["live"] = live.get(m["key"]) if not m["external"] else None
        m["gone"] = bool(not m["external"] and m["key"] not in live)
    out["members"] = members
    # what changed for these people in the latest snapshot (moves, departures, promotions)
    out["changes"] = []
    if conn is not None and members:
        snap = conn.execute("SELECT max(id) FROM snapshots").fetchone()[0]
        keys = [m["key"] for m in members if not m["external"]]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            out["changes"] += [rowdict(r) for r in conn.execute(
                f"SELECT key, type, name, before, after FROM events WHERE snap = ? AND type IN "
                f"('departed','moved','promoted','retitled','relocated','contact') AND key IN ({','.join('?' * len(chunk))})",
                [snap] + chunk)]
    return out


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------- write
def save(ctx, p, b):
    """Create/update a group. Body fields: id?, name, description, purpose, starts, ends, place, links, query,
    add:[keys], members:[{key?|email?, name, role, section, …}], update:[{key, role, section, note…}], remove:[keys], delete."""
    b = b or {}
    c = dbm.annotations(ctx.data_dir)
    ts = now()
    lid = b.get("id")
    if b.get("delete") and lid:
        c.execute("DELETE FROM list_members WHERE list_id = ?", (lid,))
        c.execute("DELETE FROM lists WHERE id = ?", (lid,))
        c.commit()
        return {"ok": True}
    meta = {k: b[k] for k in ("name", "description", "purpose", "starts", "ends", "place", "query") if k in b}
    if "links" in b:
        meta["links"] = json.dumps([{"label": str(x.get("label", ""))[:80], "url": str(x.get("url", ""))[:500]}
                                    for x in b["links"] if isinstance(x, dict) and x.get("url")][:20])
    if meta.get("purpose") and meta["purpose"] not in PURPOSES:
        meta["purpose"] = "other"
    if not lid:
        cur = c.execute(
            "INSERT INTO lists (uid, name, description, kind, query, purpose, starts, ends, place, links, created_at,"
            " updated_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.get("uid") or uuid.uuid4().hex, str(meta.get("name") or "Untitled group")[:120],
             str(meta.get("description", ""))[:2000], "smart" if meta.get("query") else "static",
             str(meta.get("query", ""))[:1000], meta.get("purpose", "team"), meta.get("starts", ""),
             meta.get("ends", ""), str(meta.get("place", ""))[:120], meta.get("links", "[]"), ts, ts,
             str(b.get("by", ""))[:60]))
        lid = cur.lastrowid
    else:
        for k, v in meta.items():
            c.execute(f"UPDATE lists SET {k} = ? WHERE id = ?", (str(v)[:2000], lid))
        if "query" in meta:
            c.execute("UPDATE lists SET kind = ? WHERE id = ?", ("smart" if meta["query"] else "static", lid))
    add_keys = list(b.get("add") or [])
    members = list(b.get("members") or [])
    if add_keys:
        live = _live(ctx.conn(), add_keys)
        for k in add_keys:
            o = live.get(k, {})
            members.append({"key": k, "name": o.get("name", k), "rank": o.get("rank", ""), "title": o.get("title", ""),
                            "org": o.get("org_id", ""), "email": o.get("email", ""), "phone": o.get("phone", "")})
    for m in members:
        _upsert_member(c, lid, m, ts)
    for u in b.get("update") or []:
        sets = {k: str(u[k])[:300] for k in ("role", "section", "note", "sort", "email", "phone", "name", "rank", "title", "org")
                if k in u}
        if sets and u.get("key"):
            c.execute(f"UPDATE list_members SET {', '.join(f'{k} = ?' for k in sets)} WHERE list_id = ? AND key = ?",
                      list(sets.values()) + [lid, u["key"]])
    rem = b.get("remove") or []
    if rem:
        c.executemany("DELETE FROM list_members WHERE list_id = ? AND key = ?", [(lid, k) for k in rem])
    c.execute("UPDATE lists SET updated_at = ? WHERE id = ?", (ts, lid))
    c.commit()
    return {"ok": True, "id": lid}


def _upsert_member(c, lid, m, ts):
    key = m.get("key") or ""
    external = 0
    if not key:
        external = 1
        key = "x:" + (m.get("email") or m.get("name") or uuid.uuid4().hex).lower()[:120]
    vals = {f: str(m.get(f) or "")[:300] for f in MEMBER_FIELDS}
    c.execute(
        "INSERT INTO list_members (list_id, key, name, added_at, role, section, external, email, phone, rank, title, org, note, sort)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(list_id, key) DO UPDATE SET "
        "role = CASE WHEN excluded.role <> '' THEN excluded.role ELSE role END, "
        "section = CASE WHEN excluded.section <> '' THEN excluded.section ELSE section END, "
        "note = CASE WHEN excluded.note <> '' THEN excluded.note ELSE note END",
        (lid, key, vals["name"] or key, ts, vals["role"], vals["section"], external or int(bool(m.get("external"))),
         vals["email"], vals["phone"], vals["rank"], vals["title"], vals["org"], vals["note"], _int(m.get("sort"))))


# ---------------------------------------------------------------- bundles (share between servers)
def export(ctx, p, b):
    g = get(ctx, p, b)
    if g.get("error"):
        return g
    fmt = p.get("format", "json")
    slug = re.sub(r"[^\w\-]+", "-", g["name"]).strip("-").lower()[:60] or "group"
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["section", "role", "rank", "name", "title", "org", "email", "phone", "dsn", "location", "external", "note"])
        for m in g["members"]:
            lv = m["live"] or {}
            w.writerow([m["section"], m["role"], lv.get("rank", m["rank"]), lv.get("name", m["name"]), lv.get("title", m["title"]),
                        lv.get("org_id", m["org"]), lv.get("email", m["email"]), lv.get("phone", m["phone"]), lv.get("dsn", ""),
                        lv.get("loc_name", ""), "yes" if m["external"] else "", m["note"]])
        return (out.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"{slug}.csv")
    bundle = {
        "format": "orgx-group", "version": 1, "uid": g["uid"], "name": g["name"], "purpose": g["purpose"],
        "description": g["description"], "starts": g["starts"], "ends": g["ends"], "place": g["place"],
        "links": g["links"], "query": g["query"], "exported_at": now(), "exported_by": p.get("by", ""),
        "origin": socket.gethostname(),
        "members": [],
    }
    for m in g["members"]:
        lv = m["live"] or {}
        bundle["members"].append({
            "key": "" if m["external"] else m["key"], "upn": lv.get("upn", ""), "email": lv.get("email") or m["email"],
            "name": lv.get("name") or m["name"], "rank": lv.get("rank") or m["rank"], "title": lv.get("title") or m["title"],
            "org": lv.get("org_id") or m["org"], "phone": lv.get("phone") or m["phone"], "role": m["role"],
            "section": m["section"], "note": m["note"], "external": bool(m["external"]),
        })
    data = json.dumps(bundle, indent=1, ensure_ascii=False).encode()
    return (data, "application/json; charset=utf-8", f"{slug}.orgx.json")


def import_bundle(ctx, p, b):
    """Body: an orgx-group bundle. ?mode=merge (default when the uid exists) | copy."""
    b = b or {}
    if b.get("format") != "orgx-group" or not isinstance(b.get("members"), list):
        return {"error": "not an ORGX group bundle (.orgx.json)"}
    c = dbm.annotations(ctx.data_dir)
    existing = c.execute("SELECT id FROM lists WHERE uid = ?", (b.get("uid", ""),)).fetchone()
    mode = p.get("mode") or ("merge" if existing else "copy")
    conn = ctx.conn()
    members, matched, external = [], 0, 0
    for m in b["members"][:5000]:
        key = resolve_one(conn, m) if conn is not None else ""
        if key:
            matched += 1
        else:
            external += 1
        members.append({**{f: m.get(f, "") for f in MEMBER_FIELDS}, "key": key, "external": not key})
    body = {k: b.get(k, "") for k in ("name", "description", "purpose", "starts", "ends", "place", "query")}
    body["links"] = b.get("links") or []
    body["members"] = members
    if existing and mode == "merge":
        body["id"] = existing["id"]
    else:
        body["uid"] = b.get("uid") if not existing else uuid.uuid4().hex
        if existing:
            body["name"] = f"{body['name']} (copy)"
    r = save(ctx, {}, body)
    c.execute("UPDATE lists SET origin = ? WHERE id = ?", (str(b.get("origin", ""))[:120], r["id"]))
    c.commit()
    return {"ok": True, "id": r["id"], "mode": mode, "matched": matched, "external": external}


def resolve_one(conn, m: dict) -> str:
    """Find a bundle member in this directory: key → email → UPN → exact name (+rank)."""
    if m.get("key"):
        r = conn.execute("SELECT key FROM objects WHERE key = ?", (m["key"],)).fetchone()
        if r:
            return r[0]
    for field in ("email", "upn"):
        v = (m.get(field) or "").strip()
        if v:
            r = conn.execute(f"SELECT key FROM objects WHERE lower({field}) = lower(?) LIMIT 1", (v,)).fetchone()
            if r:
                return r[0]
    name = (m.get("name") or "").strip()
    if name:
        rows = conn.execute("SELECT key, rank FROM objects WHERE name = ? COLLATE NOCASE LIMIT 3", (name,)).fetchall()
        if len(rows) == 1 or (rows and m.get("rank") and sum(r["rank"] == m["rank"] for r in rows) == 1):
            return rows[0]["key"] if len(rows) == 1 else next(r["key"] for r in rows if r["rank"] == m["rank"])
    return ""


# ---------------------------------------------------------------- paste-to-resolve
def resolve_text(ctx, p, b):
    """Turn a pasted Outlook To: line, email thread header or list of names into directory matches."""
    text = str((b or {}).get("text", ""))[:200000]
    conn = ctx.conn()
    if conn is None:
        return {"items": []}
    items, seen = [], set()
    # "Doe, Jane A Capt USSF … <jane.doe@x>" or bare emails
    addr = re.compile(r"(?:\"?([^\"<;,\n]*(?:,[^\"<;\n]*)?)\"?\s*)?<\s*(" + EMAIL_RE.pattern + r")\s*>|(" + EMAIL_RE.pattern + ")")
    for m in addr.finditer(text):
        email = (m.group(2) or m.group(3)).lower()
        if email in seen:
            continue
        seen.add(email)
        r = conn.execute(f"SELECT {LIVE_COLS} FROM objects o LEFT JOIN locations l ON l.id = o.loc_id "
                         f"WHERE lower(o.email) = ? OR lower(o.upn) = ? LIMIT 1", (email, email)).fetchone()
        items.append({"input": email, "label": (m.group(1) or "").strip(), "match": rowdict(r) if r else None, "candidates": []})
    rest = addr.sub(" ", text)   # what is left is names without addresses
    for line in re.split(r"[;\n]+", rest):
        name = line.strip(" \t,\"'")
        if len(name) < 4 or not re.search(r"[A-Za-z]{2}", name) or name.lower() in seen:
            continue
        seen.add(name.lower())
        cands = _by_name(conn, name)
        items.append({"input": name, "label": "", "match": cands[0] if len(cands) == 1 else None,
                      "candidates": cands if len(cands) > 1 else []})
    return {"items": items[:1000]}


def _by_name(conn, text: str) -> list[dict]:
    from .parse import parse_display
    d = parse_display(text) if "," in text else {"last": "", "first": ""}
    if d["last"]:
        last, first = d["last"], d["first"]
    else:
        parts = text.replace(".", " ").split()
        parts = [x for x in parts if len(x) > 1]
        if len(parts) < 2:
            return []
        first, last = parts[-2], parts[-1]
    rows = conn.execute(f"SELECT {LIVE_COLS} FROM objects o LEFT JOIN locations l ON l.id = o.loc_id "
                        f"WHERE o.kind = 'person' AND o.last = ? COLLATE NOCASE AND o.first LIKE ? LIMIT 6",
                        (last.title() if last.isupper() else last, f"{first[:3]}%")).fetchall()
    if not rows:
        rows = conn.execute(f"SELECT {LIVE_COLS} FROM objects o LEFT JOIN locations l ON l.id = o.loc_id "
                            f"WHERE o.kind = 'person' AND o.last = ? COLLATE NOCASE AND o.first LIKE ? LIMIT 6",
                            (last, f"{first[:3]}%")).fetchall()
    return [rowdict(r) for r in rows]
