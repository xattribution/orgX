"""Email list builder: any filter / selection / group → paste-ready recipient lists.

Options (query params):
  q | keys | group            source
  style   plain | named       "a@x; b@y"  or  "Capt Jane Doe <a@x>"
  sep     ; | , | nl
  exclude ctr,civ,mil,foreign categories to drop
  pick    all | leaders | shop          everyone · leaders only · one per office (its org box, else its lead)
  disabled 0|1                include disabled accounts
  batch   N                   split into batches of N (Outlook / mail-relay recipient caps)
"""
from __future__ import annotations

import re
import urllib.parse

from . import db as dbm
from . import groups
from .query import compile_query

MAILTO_LIMIT = 2000   # Windows shell / many clients truncate longer mailto: URLs


def build(ctx, p, b):
    conn = ctx.conn()
    if conn is None:
        return {"error": "no data"}
    rows, group_extra = _source(ctx, conn, p)
    exclude = {x.strip() for x in (p.get("exclude") or "").split(",") if x.strip()}
    pick = p.get("pick", "all")
    keep_disabled = p.get("disabled") == "1"
    skipped = {"no_email": 0, "excluded": 0, "disabled": 0}
    people = []
    for r in rows:
        if r["category"] in exclude and r["kind"] == "person":
            skipped["excluded"] += 1
            continue
        if r["disabled"] and r["kind"] == "person" and not keep_disabled:
            skipped["disabled"] += 1
            continue
        people.append(r)
    if pick == "leaders":
        people = [r for r in people if r["kind"] != "person" or (r["leader"] or 0) >= 60]
    elif pick == "shop":
        people = _per_shop(conn, people)
    recips, seen = [], set()
    for r in people + group_extra:
        e = (r.get("email") or "").strip()
        if not e:
            skipped["no_email"] += 1
            continue
        if e.lower() in seen:
            continue
        seen.add(e.lower())
        recips.append({"key": r.get("key", ""), "name": r.get("name", ""), "rank": r.get("rank", ""), "email": e,
                       "org": r.get("org_id") or r.get("org", ""), "kind": r.get("kind", "person")})
    style = p.get("style", "plain")
    sep = {"nl": "\n", ",": ", "}.get(p.get("sep", ";"), "; ")
    fmt = (lambda x: f"{_q((x['rank'] + ' ' + x['name']).strip() if x['kind'] == 'person' else x['name'])} <{x['email']}>") \
        if style == "named" else (lambda x: x["email"])
    size = _int(p.get("batch"), 0)
    chunks = [recips[i:i + size] for i in range(0, len(recips), size)] if size > 0 else [recips]
    field = p.get("field", "bcc") if p.get("field") in ("to", "cc", "bcc") else "bcc"
    batches = []
    for ch in chunks:
        if not ch:
            continue
        text = sep.join(fmt(x) for x in ch)
        url = f"mailto:?{field}=" + urllib.parse.quote(";".join(x["email"] for x in ch), safe="@;")
        batches.append({"n": len(ch), "text": text, "mailto": url, "mailto_ok": len(url) <= MAILTO_LIMIT})
    return {"count": len(recips), "skipped": skipped, "batches": batches, "recipients": recips[:2000]}


def _q(name: str) -> str:
    return f'"{name}"' if re.search(r"[,;<>@\"]", name) else name


def _int(v, d=0):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return d


COLS = "o.key, o.kind, o.name, o.rank, o.email, o.org_id, o.category, o.disabled, o.leader, o.level"


def _source(ctx, conn, p):
    if p.get("group"):
        g = groups.get(ctx, {"id": p["group"]}, None)
        if g.get("error"):
            return [], []
        keys = [m["key"] for m in g["members"] if not m["external"]]
        ext = [{"key": m["key"], "name": m["name"], "rank": m["rank"], "email": m["email"], "org": m["org"], "kind": "person"}
               for m in g["members"] if m["external"]]
        return _by_keys(conn, keys), ext
    if p.get("keys"):
        return _by_keys(conn, [k for k in p["keys"].split(",") if k]), []
    c = compile_query(conn, p.get("q", ""), conn.execute("SELECT max(id) FROM snapshots").fetchone()[0])
    w, prm = c.sql(has_fts=dbm.has_fts5())
    return [dict(r) for r in conn.execute(f"SELECT {COLS} FROM objects o WHERE {w} ORDER BY o.org_lft, o.leader DESC, o.level DESC "
                                          f"LIMIT 50000", prm)], []


def _by_keys(conn, keys):
    out = []
    for i in range(0, len(keys), 500):
        ch = keys[i:i + 500]
        out += [dict(r) for r in conn.execute(f"SELECT {COLS} FROM objects o WHERE o.key IN ({','.join('?' * len(ch))})", ch)]
    return out


def _per_shop(conn, rows):
    """One address per office: its org mailbox if it has one, else the office lead (or most senior selected)."""
    by_org: dict[str, list] = {}
    out = []
    for r in rows:
        if r["kind"] != "person" or not r["org_id"]:
            out.append(r)
        else:
            by_org.setdefault(r["org_id"], []).append(r)
    for oid, members in by_org.items():
        box = conn.execute("SELECT key, kind, name, rank, email, org_id, category, disabled, leader, level FROM objects "
                           "WHERE kind = 'orgbox' AND org_id = ? AND email <> '' LIMIT 1", (oid,)).fetchone()
        if box:
            out.append(dict(box))
        else:
            out.append(max(members, key=lambda r: ((r["leader"] or 0), (r["level"] or 0))))
    return out
