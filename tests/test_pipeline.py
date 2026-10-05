"""End-to-end: synthetic export → two ingests → queries, routing, HTTP API."""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orgx import api, db, route, rules  # noqa: E402
from orgx.ingest import ingest  # noqa: E402
from orgx.query import compile_query  # noqa: E402


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="orgx-test-"))
        shutil.copy(ROOT / "data" / "centroids.json", cls.tmp / "centroids.json")
        out = cls.tmp / "synthetic"
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--out", str(out), "--scale", "1.5"],
                       check=True, capture_output=True)
        shutil.copy(out / "sites.json", cls.tmp / "sites.json")     # the demo's own coordinates
        cls.files = sorted(out.glob("*.csv"))
        cls.first = ingest(cls.files[0], cls.tmp, log=lambda m: None)
        cls.second = ingest(cls.files[1], cls.tmp, log=lambda m: None)
        cls.conn = db.connect(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def q(self, text):
        c = compile_query(self.conn, text, 2)
        w, p = c.sql(has_fts=db.has_fts5())
        return [dict(r) for r in self.conn.execute(f"SELECT o.* FROM objects o WHERE {w}", p)]

    # ---------------------------------------------------------------- ingest
    def test_kinds_and_history(self):
        self.assertEqual(self.first["events"], 0)
        self.assertGreater(self.second["events"], 10)
        kinds = self.second["kinds"]
        for k in ("person", "orgbox", "group", "resource"):
            self.assertGreater(kinds.get(k, 0), 0, k)
        types = dict(self.conn.execute("SELECT type, count(*) FROM events GROUP BY type").fetchall())
        for t in ("joined", "departed"):
            self.assertIn(t, types)
        snaps = self.conn.execute("SELECT as_of FROM snapshots ORDER BY id").fetchall()
        self.assertEqual([s[0] for s in snaps], [f.stem.split("_")[-1] for f in self.files])

    def test_org_inference(self):
        parent = dict(self.conn.execute("SELECT id, parent FROM orgs").fetchall())
        self.assertEqual(parent["HARBOR COMM SQ"], "HARBOR SUPPORT GROUP")       # manager links
        self.assertEqual(parent["HARBOR SUPPORT GROUP"], "HARBOR WING")
        self.assertEqual(parent["BEACON TEAM"], "MERIDIAN GROUP")
        self.assertEqual(parent["HARBOR COMM SQ/SCOO"], "HARBOR COMM SQ/SCO")    # office symbol nesting
        self.assertEqual(parent["MERIDIAN GROUP/S3/S36"], "MERIDIAN GROUP/S3")
        levels = json.loads(self.conn.execute("SELECT v FROM meta WHERE k = 'ou_levels'").fetchone()[0])
        self.assertEqual(levels, {"site": 2, "region": 1})                       # learned from the data

    def test_managers_members_locations(self):
        n = self.conn.execute("SELECT count(*) FROM objects WHERE manager_key IS NOT NULL").fetchone()[0]
        self.assertGreater(n, 100)
        self.assertGreater(self.conn.execute("SELECT count(*) FROM members").fetchone()[0], 100)
        site = self.conn.execute("SELECT site FROM orgs WHERE id = 'HARBOR COMM SQ'").fetchone()[0]
        self.assertEqual(site, "HARBOR WING")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM objects WHERE loc_id = ''").fetchone()[0], 0)

    # ---------------------------------------------------------------- query language
    def test_queries(self):
        alder = self.q("base:Alder kind:person")
        self.assertTrue(alder and all(r["loc_id"] == "Alder" for r in alder))
        sub = self.q('org:"MERIDIAN GROUP/S6"')
        self.assertTrue(sub and all(r["org_id"].startswith("MERIDIAN GROUP/S6") for r in sub))
        direct = self.q('org:"MERIDIAN GROUP/S6!"')
        self.assertTrue(all(r["org_id"] == "MERIDIAN GROUP/S6" for r in direct))
        senior = self.q("grade:>=O-5")
        self.assertTrue(senior and all(r["level"] >= 25 for r in senior))
        self.assertFalse([r for r in self.q("-cat:ctr kind:person") if r["category"] == "ctr"])
        self.assertTrue(self.q("satcom planner"))
        self.assertTrue(self.q("is:new"))
        boss = self.conn.execute("SELECT key FROM objects WHERE org_id = 'ATLAS COMMAND' AND title = 'Commander'").fetchone()[0]
        under = self.q(f"under:{boss}")
        self.assertGreater(len(under), 100)
        self.assertTrue(any(r["org_id"].startswith("HARBOR ") for r in under))

    # ---------------------------------------------------------------- routing
    def test_routing(self):
        topics = rules.topics(rules.load(self.tmp))
        r = route.ask(self.conn, "who do I contact for SATCOM?", topics)
        self.assertEqual(r["topics"][0]["id"], "satcom")
        self.assertIn("satcom", (r["people"][0]["title"] or "").lower())
        self.assertTrue(any(s["orgbox"] for s in r["shops"]))
        r = route.ask(self.conn, "network outage at Cedar", topics)
        self.assertIn("Cedar", r["places"])
        self.assertEqual(r["people"][0]["loc_id"], "Cedar")

    def test_taught_route_wins(self):
        key = self.conn.execute("SELECT key FROM objects WHERE kind = 'person' AND title LIKE '%Historian%' LIMIT 1").fetchone()
        key = key[0] if key else self.conn.execute("SELECT key FROM objects WHERE kind = 'person' LIMIT 1").fetchone()[0]
        ctx = api.Ctx(self.tmp)
        api.save_note(ctx, {}, {"key": key, "contact_for": ["Starlink terminals"], "tags": ["Starlink"]})
        r = route.ask(self.conn, "who handles starlink terminals", rules.topics(rules.load(self.tmp)))
        self.assertEqual(r["people"][0]["key"], key)
        self.assertTrue(self.q("tag:starlink"))
        api.save_note(ctx, {}, {"key": key})

    # ---------------------------------------------------------------- groups / bundles / email
    def test_group_bundle_roundtrip(self):
        from orgx import groups, mail
        ctx = api.Ctx(self.tmp)
        keys = [r["key"] for r in self.q("kind:person base:Alder")][:4]
        r = groups.save(ctx, {}, {"name": "Spring exercise cell", "purpose": "exercise", "starts": "2026-11-02", "ends": "2026-11-14",
                                  "place": "Fir", "add": keys,
                                  "members": [{"name": "Lt Col Sato Kenji", "email": "k.sato@partner.example", "role": "Partner LNO",
                                               "section": "Partners"}]})
        gid = r["id"]
        groups.save(ctx, {}, {"id": gid, "update": [{"key": keys[0], "role": "Lead planner", "section": "Core"}]})
        g = groups.get(ctx, {"id": gid}, None)
        self.assertEqual(len(g["members"]), 5)
        self.assertEqual(sum(m["external"] for m in g["members"]), 1)
        data, ctype, fname = groups.export(ctx, {"id": gid}, None)
        self.assertTrue(fname.endswith(".orgx.json"))
        bundle = json.loads(data)
        self.assertEqual(bundle["format"], "orgx-group")
        # import on "another server": wipe keys so members must be re-resolved by email
        for m in bundle["members"]:
            m["key"] = ""
        bundle["uid"] = "other-server-uid"
        res = groups.import_bundle(ctx, {}, bundle)
        self.assertEqual((res["matched"], res["external"]), (4, 1))
        g2 = groups.get(ctx, {"id": res["id"]}, None)
        self.assertEqual(next(m for m in g2["members"] if m["role"] == "Lead planner")["section"], "Core")
        # re-import same uid merges instead of duplicating
        self.assertEqual(groups.import_bundle(ctx, {}, bundle)["mode"], "merge")
        # email builder from the group
        e = mail.build(ctx, {"group": str(gid), "style": "named", "batch": "3"}, None)
        self.assertEqual(e["count"], 5)
        self.assertEqual([b_["n"] for b_ in e["batches"]], [3, 2])
        self.assertIn("<k.sato@partner.example>", "".join(b_["text"] for b_ in e["batches"]))
        shop = mail.build(ctx, {"q": 'org:"MERIDIAN GROUP/S6"', "pick": "shop"}, None)
        self.assertTrue(any("orgbox" in r_["email"] for r_ in shop["recipients"]))
        self.assertLess(shop["count"], len(self.q('org:"MERIDIAN GROUP/S6"')))

    def test_paste_resolve(self):
        from orgx import groups
        ctx = api.Ctx(self.tmp)
        rows = self.conn.execute("SELECT name, display, email FROM objects WHERE kind = 'person' LIMIT 2").fetchall()
        text = f'"{rows[0]["display"]}" <{rows[0]["email"]}>; {rows[1]["display"]}; nobody@nowhere.example'
        items = groups.resolve_text(ctx, {}, {"text": text})["items"]
        got = {i["input"]: i for i in items}
        self.assertEqual(got[rows[0]["email"].lower()]["match"]["email"], rows[0]["email"])
        self.assertIsNone(got["nobody@nowhere.example"]["match"])
        self.assertTrue(any(i["match"] and i["match"]["email"] == rows[1]["email"] for i in items))
        self.assertEqual(len(items), 3, "a quoted display name with its <address> is one entry")

    # ---------------------------------------------------------------- HTTP
    def test_http_smoke(self):
        import server
        server.Handler.ctx = api.Ctx(self.tmp)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            get = lambda path: json.loads(urllib.request.urlopen(base + path).read())
            self.assertFalse(get("/api/meta")["empty"])
            self.assertGreater(get("/api/search?q=kind:person&limit=5")["total"], 100)
            self.assertIn("org", get("/api/facets?q=org:%22MERIDIAN%20GROUP%22"))
            self.assertTrue(get("/api/orgtree?depth=2")["children"])
            self.assertTrue(get("/api/locations")["locations"])
            self.assertTrue(get("/api/changes")["rows"])
            self.assertTrue(get("/api/quality")["issues"])
            self.assertTrue(get("/api/ask?q=annex%20n")["people"])
            csv_ = urllib.request.urlopen(base + "/api/export?q=base:Alder&format=csv").read().decode("utf-8-sig")
            self.assertTrue(csv_.startswith("kind,rank,name"))
            html = urllib.request.urlopen(base + "/").read().decode()
            self.assertIn("ORGX", html)
            gid = json.loads(urllib.request.urlopen(urllib.request.Request(
                base + "/api/group", data=json.dumps({"name": "t", "add": []}).encode(), method="POST",
                headers={"Content-Type": "application/json"})).read())["id"]
            self.assertEqual(get(f"/api/group?id={gid}")["name"], "t")
            me = get("/api/whoami")
            self.assertTrue(me["available"])          # loopback request
            self.assertIn("available", get("/api/ad"))
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
