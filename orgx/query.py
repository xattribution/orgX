"""Query language → SQL.

    satcom planner                    free text (prefix match, all words)
    "annex n"                         phrase
    base:Alder,Birch  loc:…           location (name, site, or OU)
    org:"MERIDIAN GROUP/S6"           org subtree   org:S6!  direct members only
    region:Europe  country:JP         region OU / ISO country
    fn:cyber  kind:orgbox  cat:civ  tier:field  rank:Capt  grade:>=O-4
    title:director  email:…  phone:4021  afsc:13S  ou:"Alder"  service:USSF
    under:<key|email>  reports:<key|email>  member:<group key|email|name>
    is:leader|new|moved|promoted|disabled|hidden|noted   has:/missing:email|phone|manager|title|org|loc
    tag:exercise-cell  list:"Exercise planners"
    -base:Cedar                       negate any term
"""
from __future__ import annotations

import re
import sqlite3

from . import reference as ref

TOKEN = re.compile(r'(-)?(?:([a-zA-Z]+):)?("([^"]*)"|\S+)')
FIELDS = {"kind", "org", "in", "base", "loc", "location", "region", "country", "fn", "function", "rank", "grade",
          "cat", "category", "tier", "title", "email", "phone", "office", "afsc", "career", "service", "ou",
          "dn", "under", "reports", "member", "is", "has", "missing", "no", "tag", "list", "name", "key"}
KIND_ALIAS = {"people": "person", "persons": "person", "user": "person", "users": "person", "org": "orgbox",
              "orgboxes": "orgbox", "shared": "orgbox", "mailbox": "orgbox", "dl": "group", "dls": "group",
              "groups": "group", "list": "group", "room": "resource", "rooms": "resource", "resources": "resource",
              "contacts": "contact"}
FN_ALIAS = {v.lower(): k for k, v in ref.FUNCTIONS} | {"comm": "cyber", "comms": "cyber", "intelligence": "intel",
            "operations": "ops", "exercise": "exercises", "training": "exercises", "log": "logistics",
            "finance": "resources", "fm": "resources", "legal": "support", "cmd": "command", "plans": "plans",
            "strategy": "plans"}
CAT_ALIAS = {"military": "mil", "civilian": "civ", "contractor": "ctr", "contractors": "ctr", "civilians": "civ"}
FTS_WEIGHTS = "10.0, 3.0, 5.0, 3.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0"


def parse(q: str) -> list[dict]:
    terms = []
    for m in TOKEN.finditer(q or ""):
        neg, field, raw, quoted = m.group(1), m.group(2), m.group(3), m.group(4)
        if field and field.lower() not in FIELDS:
            # not a field we know (e.g. a URL or 'S6:'), treat whole thing as text
            raw, field, quoted = m.group(0).lstrip("-"), None, None
        value = quoted if quoted is not None else raw
        if not value:
            continue
        terms.append({"neg": bool(neg), "field": (field or "").lower(), "value": value, "phrase": quoted is not None})
    return terms


def _fts_term(word: str, phrase: bool) -> str:
    w = word.replace('"', " ").strip()
    if not w:
        return ""
    return f'"{w}"' if phrase else f'"{w}"*'


class Compiled:
    def __init__(self):
        self.where: list[tuple[str, list, str]] = []   # (sql, params, field)
        self.fts: list[str] = []
        self.fts_neg: list[str] = []
        self.chips: list[dict] = []
        self.org_ids: list[str] = []

    def sql(self, skip_field: str | None = None, has_fts: bool = True) -> tuple[str, list]:
        parts, params = [], []
        for s, p, f in self.where:
            if skip_field and _facet_field(f) == skip_field:
                continue
            parts.append(s)
            params += p
        if self.fts and has_fts:
            match = " AND ".join(self.fts)
            if self.fts_neg:
                match += " NOT " + " NOT ".join(self.fts_neg)
            parts.append("o.id IN (SELECT rowid FROM objects_fts WHERE objects_fts MATCH ?)")
            params.append(match)
        elif self.fts or self.fts_neg:
            for t, neg in [(t, False) for t in self.fts] + [(t, True) for t in self.fts_neg]:
                w = t.strip('"*')
                like = ("(o.name LIKE ? OR o.display LIKE ? OR o.title LIKE ? OR o.dept LIKE ? OR o.email LIKE ? "
                        "OR o.office LIKE ? OR o.career LIKE ?)")
                parts.append(f"NOT {like}" if neg else like)
                params += [f"%{w}%"] * 7
        return (" AND ".join(parts) or "1=1"), params


def _facet_field(f: str) -> str:
    return {"base": "loc", "location": "loc", "in": "org", "function": "fn", "category": "cat"}.get(f, f)


def compile_query(conn: sqlite3.Connection, q: str, latest_snap: int | None = None) -> Compiled:
    c = Compiled()
    for t in parse(q):
        f, v, neg = t["field"], t["value"], t["neg"]
        vals = [x.strip() for x in v.split(",") if x.strip()] if not t["phrase"] else [v]
        sql, params, label = "", [], f"{f}:{v}" if f else v

        if not f or f == "name":
            if f == "name":
                sql, params = "(o.name LIKE ? OR o.display LIKE ?)", [f"%{v}%", f"%{v}%"]
            else:
                d = re.sub(r"\D", "", v)
                if len(d) >= 3 and len(d) == len(re.sub(r"[\s\-().+]", "", v)):
                    sql, params = "o.phone_digits LIKE ?", [f"%{d}%"]
                else:
                    words = [v] if t["phrase"] else re.findall(r"[\w'@.]+", v)
                    for w in words:
                        for piece in re.split(r"[^\w]+", w) if not t["phrase"] else [w]:
                            term = _fts_term(piece, t["phrase"])
                            if term:
                                (c.fts_neg if neg else c.fts).append(term)
                    c.chips.append({"field": "", "value": v, "neg": neg, "label": ("-" if neg else "") + v})
                    continue
        elif f == "kind":
            ks = [KIND_ALIAS.get(x.lower(), x.lower()) for x in vals]
            sql, params = f"o.kind IN ({','.join('?' * len(ks))})", ks
        elif f in ("org", "in"):
            direct = v.endswith("!")
            ors = []
            for x in vals:
                x = x.rstrip("!")
                rows = conn.execute(
                    "SELECT id, lft, rgt FROM orgs WHERE id = ? COLLATE NOCASE OR (name = ? COLLATE NOCASE AND "
                    "NOT EXISTS (SELECT 1 FROM orgs WHERE id = ? COLLATE NOCASE)) ORDER BY people DESC LIMIT 8",
                    (x, x, x)).fetchall()
                for r in rows:
                    c.org_ids.append(r["id"])
                    if direct:
                        ors.append("o.org_id = ?")
                        params.append(r["id"])
                    else:
                        ors.append("o.org_lft BETWEEN ? AND ?")
                        params += [r["lft"], r["rgt"]]
            sql = "(" + " OR ".join(ors) + ")" if ors else "0"
        elif f in ("base", "loc", "location"):
            ors = []
            for x in vals:
                ors.append("o.loc_id IN (SELECT id FROM locations WHERE id = ? COLLATE NOCASE OR name = ? COLLATE NOCASE "
                           "OR full = ? COLLATE NOCASE OR ou = ? COLLATE NOCASE)")
                params += [x] * 4
            sql = "(" + " OR ".join(ors) + ")"
        elif f == "region":
            sql, params = f"o.region COLLATE NOCASE IN ({','.join('?' * len(vals))})", vals
        elif f == "country":
            from .geo import country_code
            cs = [country_code(x) or x.upper() for x in vals]
            sql, params = f"o.country IN ({','.join('?' * len(cs))})", cs
        elif f in ("fn", "function"):
            fs = [FN_ALIAS.get(x.lower(), x.lower()) for x in vals]
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'object_fns'").fetchone():
                sql, params = f"o.id IN (SELECT object_id FROM object_fns WHERE fn IN ({','.join('?' * len(fs))}))", fs
            else:      # a directory built before the table existed
                sql = "(" + " OR ".join("(',' || o.fns || ',') LIKE ?" for _ in fs) + ")"
                params = [f"%,{x},%" for x in fs]
        elif f == "rank":
            sql, params = f"o.rank COLLATE NOCASE IN ({','.join('?' * len(vals))})", vals
        elif f == "grade":
            m = re.match(r"^(>=|<=|>|<|=)?\s*(.+)$", v)
            op, g = (m.group(1) or "="), m.group(2).upper().replace(" ", "")
            g = re.sub(r"^([EWO])(\d)", r"\1-\2", g)
            if op == "=":
                gs = [re.sub(r"^([EWO])(\d)", r"\1-\2", x.upper()) for x in vals]
                sql, params = f"o.grade IN ({','.join('?' * len(gs))})", gs
            else:
                sql, params = f"o.level {op} ? AND o.level > 0", [ref.grade_level(g)]
        elif f in ("cat", "category"):
            cs = [CAT_ALIAS.get(x.lower(), x.lower()) for x in vals]
            sql, params = f"o.category IN ({','.join('?' * len(cs))})", cs
        elif f == "tier":
            sql, params = f"o.tier IN ({','.join('?' * len(vals))})", [x.lower() for x in vals]
        elif f in ("title", "email", "office", "dn"):
            col = {"dn": "dn"}.get(f, f)
            sql = "(" + " OR ".join(f"o.{col} LIKE ?" for _ in vals) + ")"
            params = [f"%{x}%" for x in vals]
        elif f == "phone":
            sql, params = "o.phone_digits LIKE ?", [f"%{re.sub(r'[^0-9]', '', v)}%"]
        elif f in ("afsc", "career"):
            sql = "(" + " OR ".join("o.career LIKE ?" for _ in vals) + ")"
            params = [f"{x}%" for x in vals]
        elif f == "service":
            sql, params = f"o.service COLLATE NOCASE IN ({','.join('?' * len(vals))})", vals
        elif f == "ou":
            sql = "(" + " OR ".join("o.ou_path LIKE ?" for _ in vals) + ")"
            params = [f"%{x}%" for x in vals]
        elif f == "key":
            sql, params = f"o.key IN ({','.join('?' * len(vals))})", vals
        elif f in ("under", "reports"):
            root = _resolve_key(conn, v)
            if f == "reports":
                sql, params = "o.manager_key = ?", [root]
            else:
                sql = ("o.key IN (WITH RECURSIVE chain(k, d) AS (SELECT key, 0 FROM objects WHERE manager_key = ? "
                       "UNION SELECT x.key, d + 1 FROM objects x JOIN chain ON x.manager_key = chain.k WHERE d < 25) "
                       "SELECT k FROM chain)")
                params = [root]
            label = f"{f}:{_label_for(conn, root) or v}"
        elif f == "member":
            gk = _resolve_key(conn, v, kind="group")
            sql = "o.id IN (SELECT member_id FROM members WHERE group_id = (SELECT id FROM objects WHERE key = ?))"
            params = [gk]
            label = f"member:{_label_for(conn, gk) or v}"
        elif f == "is":
            ors = []
            for x in vals:
                x = x.lower()
                if x == "leader":
                    ors.append("o.leader > 0")
                elif x in ("disabled", "hidden"):
                    ors.append(f"o.{x} = 1")
                elif x in ("new", "joined", "moved", "promoted", "retitled", "relocated"):
                    et = "joined" if x == "new" else x
                    ors.append("o.key IN (SELECT key FROM events WHERE snap = ? AND type = ?)")
                    params += [latest_snap or 0, et]
                elif x in ("noted", "annotated"):
                    ors.append("o.key IN (SELECT key FROM ann.notes WHERE notes <> '' OR tags <> '[]' OR contact_for <> '[]')")
                elif x in KIND_ALIAS or x in ref.KIND_LABEL:
                    ors.append("o.kind = ?")
                    params.append(KIND_ALIAS.get(x, x))
                elif x in ("mil", "civ", "ctr", "foreign"):
                    ors.append("o.category = ?")
                    params.append(x)
                elif x == "approx":
                    ors.append("o.loc_id IN (SELECT id FROM locations WHERE approx = 1)")
            sql = "(" + " OR ".join(ors) + ")" if ors else "1=1"
        elif f in ("has", "missing", "no"):
            col = {"email": "o.email", "phone": "o.phone", "mobile": "o.mobile", "manager": "o.manager_key",
                   "title": "o.title", "org": "o.org_id", "loc": "o.loc_id", "location": "o.loc_id",
                   "base": "o.loc_id", "career": "o.career", "afsc": "o.career", "rank": "o.grade"}
            ors = []
            for x in vals:
                x = x.lower()
                if x in ("notes", "tags"):
                    cond = ("o.key IN (SELECT key FROM ann.notes WHERE notes <> '')" if x == "notes"
                            else "o.key IN (SELECT key FROM ann.notes WHERE tags <> '[]')")
                elif x in ("members",):
                    cond = "o.id IN (SELECT group_id FROM members)"
                elif x in col:
                    cond = f"IFNULL({col[x]}, '') <> ''"
                else:
                    continue
                ors.append(cond if f == "has" else f"NOT ({cond})")
            sql = "(" + (" OR " if f == "has" else " AND ").join(ors) + ")" if ors else "1=1"
        elif f == "tag":
            sql = "(" + " OR ".join("o.key IN (SELECT key FROM ann.notes WHERE tags LIKE ?)" for _ in vals) + ")"
            params = [f'%"{x.lower()}"%' for x in vals]
        elif f == "list":
            sql = ("o.key IN (SELECT key FROM ann.list_members WHERE list_id IN "
                   "(SELECT id FROM ann.lists WHERE name = ? COLLATE NOCASE OR CAST(id AS TEXT) = ?))")
            params = [v, v]
        if not sql:
            continue
        c.where.append((f"NOT ({sql})" if neg else sql, params, f))
        c.chips.append({"field": f, "value": v, "neg": neg, "label": ("-" if neg else "") + label})
    return c


def _resolve_key(conn, v: str, kind: str | None = None) -> str:
    v = v.strip()
    row = conn.execute("SELECT key FROM objects WHERE key = ? OR email = ? COLLATE NOCASE LIMIT 1", (v, v)).fetchone()
    if row:
        return row[0]
    sql = "SELECT key FROM objects WHERE (name = ? COLLATE NOCASE OR display = ? COLLATE NOCASE)"
    args = [v, v]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    row = conn.execute(sql + " LIMIT 1", args).fetchone()
    return row[0] if row else v


def _label_for(conn, key: str) -> str:
    row = conn.execute("SELECT name, rank FROM objects WHERE key = ?", (key,)).fetchone()
    return f"{row['rank']} {row['name']}".strip() if row else ""


ORDER = {
    "smart": "CASE o.kind WHEN 'person' THEN 0 WHEN 'orgbox' THEN 1 WHEN 'group' THEN 2 ELSE 3 END, "
             "o.org_lft, o.leader DESC, o.level DESC, o.sort_name",
    "name": "o.sort_name COLLATE NOCASE",
    "seniority": "o.level DESC, o.leader DESC, o.sort_name",
    "org": "o.org_lft, o.leader DESC, o.level DESC, o.sort_name",
    "location": "o.loc_id, o.org_lft, o.level DESC",
    "title": "o.title COLLATE NOCASE, o.sort_name",
}
