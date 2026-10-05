"""'Who do I contact for …' — topic routing over the directory.

Signals, strongest first:
  team-taught routes (annotations: "go-to for the spring exercise") → 100
  title mentions the topic's terms / the question's own words    → 10–14 each
  org code of the topic (S6, A6, JA…) anywhere on the org path   → 10
  function match (primary / secondary)                           → 10 / 5
  located in the topic's country (when a topic names one)        → 8
  org mailbox of a matching shop                                 → +6 (contact the shop, not a person)
  same unit / location as the asker (scope)                      → +6 / +4
  leadership                                                     → up to +4
Results come back per person *and* rolled up per shop.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

from . import reference as ref
from .query import compile_query

LEAD_IN = re.compile(
    r"^\s*(who\s+(do|should|can)\s+i\s+(contact|call|email|ask|talk to|reach out to)|who('s| is)\s+(the\s+)?(poc|lead|point of contact)|"
    r"who\s+handles|who\s+owns|who\s+runs|poc|point of contact|contact|need|help with|i need)\b\s*(for|about|on|re|regarding|with)?\s*",
    re.I)
STOP = set("a an the for to of on in at about re regarding with and or my our is are who what do i me we need help "
           "contact poc someone person anyone question questions please thanks get can should".split())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-/]", " ", s.lower())).strip()


def match_topics(q: str, topics: list[dict]) -> list[tuple[dict, str]]:
    out = []
    for t in topics:
        best = ""
        for a in t["aliases"] + [t["label"].lower()]:
            a = a.lower()
            if re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", q) and len(a) > len(best):
                best = a
        if best:
            out.append((t, best))
    out.sort(key=lambda x: -len(x[1]))
    # drop generic topics fully covered by a more specific match ("exercise" inside "exercise planning")
    keep, used = [], []
    for t, a in out:
        if any(a in u for u in used) and not t.get("user"):
            continue
        keep.append((t, a))
        used.append(a)
    return keep[:3]


def ask(conn: sqlite3.Connection, question: str, topics: list[dict], scope: str = "", home: dict | None = None,
        limit: int = 12) -> dict:
    home = home or {}
    q = _norm(LEAD_IN.sub("", question or ""))
    if not q:
        return {"question": question, "topics": [], "people": [], "shops": []}
    matched = match_topics(q, topics)
    covered = " ".join(a for _, a in matched)
    words = [w for w in re.findall(r"[\w\-/]+", q) if w not in STOP and w not in covered.split() and len(w) > 1]

    # place / unit names in the question become hints, not search words ("… at Alder", "… in HARBOR COMM SQ")
    places, units = {}, {}
    if words:
        grams = set(words) | {f"{a} {b}" for a, b in zip(words, words[1:])}
        for r in conn.execute(f"SELECT id, name FROM locations WHERE lower(name) IN ({','.join('?' * len(grams))})",
                              list(grams)):
            places[r["id"]] = r["name"]
        for r in conn.execute(f"SELECT id FROM orgs WHERE depth = 0 AND lower(id) IN ({','.join('?' * len(grams))})",
                              list(grams)):
            units[r["id"].upper()] = r["id"]
        used = " ".join(list(places.values()) + list(units.values())).lower().split()
        words = [w for w in words if w not in used]
    specific = set(words) | {a for _, a in matched}

    # taught routes from annotations
    taught: dict[str, str] = {}
    for r in conn.execute("SELECT key, contact_for FROM ann.notes WHERE contact_for <> '[]'"):
        for phrase in json.loads(r["contact_for"] or "[]"):
            p = phrase.lower().strip()
            if p and (re.search(rf"(?<!\w){re.escape(p)}(?!\w)", q) or (len(q) > 3 and q in p)):
                taught[r["key"]] = phrase

    scope_sql, scope_params = "1=1", []
    if scope:
        sc = compile_query(conn, scope)
        scope_sql, scope_params = sc.sql()

    # candidate retrieval (bounded)
    conds, params = [], []
    all_terms = set(words)
    fns, codes, countries = set(), set(), set()
    for t, _ in matched:
        all_terms.update(x.lower() for x in t["terms"])
        fns.update(t["fns"])
        codes.update(c.upper() for c in t["codes"])
        countries.update(t.get("countries", []))
    for term in sorted(all_terms):
        conds.append("o.title LIKE ? OR o.name LIKE ? OR o.dept LIKE ? OR o.description LIKE ?")
        params += [f"%{term}%"] * 4
    for fn in fns:
        conds.append("(',' || o.fns || ',') LIKE ?")
        params.append(f"%,{fn},%")
    for code in codes:
        conds.append("('/' || upper(o.org_id) || '/') LIKE ? OR upper(o.org_id) LIKE ?")
        params += [f"%/{code}%/%", f"%/{code}%"]
    if taught:
        conds.append(f"o.key IN ({','.join('?' * len(taught))})")
        params += list(taught)
    if not conds:
        return {"question": question, "topics": [], "people": [], "shops": [], "words": words}
    sql = (f"SELECT o.*, l.name AS loc_name, l.tz AS tz, l.country AS loc_country FROM objects o "
           f"LEFT JOIN locations l ON l.id = o.loc_id "
           f"WHERE o.kind IN ('person','orgbox','group') AND (o.disabled = 0 OR o.kind <> 'person') AND ({' OR '.join(conds)}) "
           f"AND {scope_sql.replace('o.', 'o.')} LIMIT 4000")
    rows = conn.execute(sql, params + scope_params).fetchall()

    home_root = (home.get("org") or "").split("/")[0].upper()
    home_loc = home.get("loc") or ""
    scored = []
    for r in rows:
        s, why = 0.0, []
        title = (r["title"] or "").lower()
        dept = (r["org_id"] or "").lower()
        name = (r["name"] or "").lower()
        segs = [x.upper() for x in (r["org_id"] or "").split("/")]
        rfns = (r["fns"] or "").split(",")
        if r["key"] in taught:
            s += 100
            why.append(f"team route: go-to for “{taught[r['key']]}”")
        hits = sorted((t for t in all_terms if len(t) > 2 and t in title), key=lambda t: (t not in specific, -len(t)))
        if hits:
            s += sum(18 if h in specific else 8 for h in hits[:2])
            why.append("title: " + ", ".join(f"“{h}”" for h in hits[:2]))
        dhits = [t for t in all_terms if len(t) > 2 and (t in dept or (r["kind"] != "person" and t in name))]
        if dhits and not hits:
            s += 6
            why.append("org/name: " + ", ".join(f"“{h}”" for h in dhits[:2]))
        code_hit = next((c for c in codes for sg in segs if sg == c or (len(c) <= 3 and sg.startswith(c))), None)
        if code_hit:
            s += 10
            why.append(f"{code_hit} shop")
        fn_hit = [f for f in fns if f in rfns]
        if fn_hit:
            primary = rfns[0] in fn_hit
            s += 10 if primary else 5
            if not code_hit:
                why.append(ref.FN_LABEL.get(fn_hit[0], fn_hit[0]))
        if countries and (r["country"] in countries or r["loc_country"] in countries):
            s += 8
            why.append(f"in {r['loc_name'] or r['country']}")
        if r["kind"] == "orgbox" and (code_hit or fn_hit or dhits):
            s += 6
            why.append("shop mailbox")
        elif r["kind"] == "group":
            s -= 4 if not hits and not dhits else 0
        if r["leader"]:
            s += min(r["leader"] / 25, 4)
        if places and r["loc_id"] in places:
            s += 12
            why.append(f"at {places[r['loc_id']]}")
        if units and segs and segs[0] in units:
            s += 10
            why.append(f"in {units[segs[0]]}")
        if home_root and segs and segs[0] == home_root:
            s += 6
        if home_loc and r["loc_id"] == home_loc:
            s += 4
        if s >= 12:
            scored.append((s, r, why))
    scored.sort(key=lambda x: (-x[0], -(x[1]["level"] or 0)))

    if places or units:
        # a named place / unit is a constraint, not a nudge: matching people first
        def here(r):
            segs0 = (r["org_id"] or "").split("/")[0].upper()
            return (not places or r["loc_id"] in places) and (not units or segs0 in units)
        scored.sort(key=lambda x: (not here(x[1]), -x[0], -(x[1]["level"] or 0)))
    people = [_card(r, s, why) for s, r, why in scored[:limit]]
    # roll up by shop
    shops = defaultdict(lambda: {"score": 0.0, "people": [], "orgbox": None})
    for s, r, why in scored[:200]:
        if not r["org_id"]:
            continue
        sh = shops[r["org_id"]]
        if r["kind"] == "orgbox":
            sh["orgbox"] = sh["orgbox"] or _card(r, s, why)
        elif r["kind"] == "person":
            sh["score"] = max(sh["score"], s) + (0.15 * s if sh["people"] else 0)
            if len(sh["people"]) < 3:
                sh["people"].append(_card(r, s, why))
    shop_list = []
    for oid, sh in sorted(shops.items(), key=lambda kv: -kv[1]["score"])[:5]:
        if not sh["people"] and not sh["orgbox"]:
            continue
        org = conn.execute("SELECT o.id, o.name, o.fn, o.people, o.leader_key, l.name AS loc_name FROM orgs o "
                           "LEFT JOIN locations l ON l.id = o.loc_id WHERE o.id = ?", (oid,)).fetchone()
        if org:
            if not sh["orgbox"]:
                ob = conn.execute("SELECT o.*, l.name AS loc_name, l.tz AS tz FROM objects o LEFT JOIN locations l "
                                  "ON l.id = o.loc_id WHERE o.kind = 'orgbox' AND o.org_id = ? LIMIT 1", (oid,)).fetchone()
                sh["orgbox"] = _card(ob, 0, ["shop mailbox"]) if ob else None
            lead = conn.execute("SELECT key, name, rank, title FROM objects WHERE key = ?", (org["leader_key"],)).fetchone()
            shop_list.append({"id": org["id"], "name": org["name"], "fn": org["fn"], "people": org["people"],
                              "loc": org["loc_name"], "score": round(sh["score"], 1), "orgbox": sh["orgbox"],
                              "top": sh["people"], "leader": dict(lead) if lead else None})
    return {
        "question": question,
        "topics": [{"id": t["id"], "label": t["label"], "alias": a} for t, a in matched],
        "words": words,
        "places": list(places.values()),
        "units": list(units.values()),
        "taught": len(taught),
        "people": people,
        "shops": shop_list,
    }


def _card(r, score, why):
    return {"key": r["key"], "kind": r["kind"], "name": r["name"], "rank": r["rank"], "title": r["title"],
            "org_id": r["org_id"], "loc_id": r["loc_id"], "loc": r["loc_name"], "tz": r["tz"], "email": r["email"],
            "phone": r["phone"], "fn": r["fn"], "score": round(score, 1), "why": why[:4]}
