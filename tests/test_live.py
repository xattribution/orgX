"""On-the-fly mode: lookups answered from an export file stand in for Active Directory."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orgx import api, live  # noqa: E402
from orgx.ingest import rows  # noqa: E402


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="orgx-live-"))
        shutil.copy(ROOT / "data" / "centroids.json", cls.tmp / "centroids.json")
        out = cls.tmp / "synthetic"
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--out", str(out), "--scale", "1"],
                       check=True, capture_output=True)
        cls.csv = sorted(out.glob("*.csv"))[0]
        it = rows(cls.csv)
        header = next(it)
        cls.source = [dict(zip(header, r)) for r in it]
        os.environ["ORGX_LIVE_CSV"] = str(cls.csv)
        live._providers.clear()
        cls.ctx = api.Ctx(cls.tmp)
        api.save_rules(cls.ctx, {}, {"ad": {"mode": "live", "liveHours": 12}})

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("ORGX_LIVE_CSV", None)
        live._providers.clear()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def db(self):
        conn = sqlite3.connect(self.tmp / "org.db")
        conn.row_factory = sqlite3.Row
        return conn

    def count(self):
        with self.db() as conn:
            return conn.execute("SELECT count(*) FROM objects").fetchone()[0]

    def a_person(self):
        """Someone with a manager, reports and an OU path, so every expansion has something to find."""
        managers = {r["Manager"].lower() for r in self.source if r.get("Manager")}
        for r in self.source:
            dn = r.get("DistinguishedName", "")
            if r.get("Manager") and dn.lower() in managers and "OU=" in dn and r.get("Surname"):
                return r
        self.fail("no suitable person in the synthetic export")

    def test_1_starts_empty_and_on(self):
        self.assertTrue((self.tmp / "org.db").exists())
        self.assertEqual(self.count(), 0)
        st = live.status(self.ctx)
        self.assertTrue(st["on"])
        self.assertTrue(st["available"])

    def test_2_search_then_cached(self):
        p = self.a_person()
        r = live.search(self.ctx, p["Surname"])
        self.assertTrue(r["ok"], r)
        self.assertGreater(r["added"], 0)
        again = live.search(self.ctx, p["Surname"])
        self.assertTrue(again["cached"])
        with self.db() as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM objects WHERE lower(dn) = lower(?)",
                                              (p["DistinguishedName"],)).fetchone())
            hits = conn.execute("SELECT count(*) FROM objects_fts WHERE objects_fts MATCH ?",
                                (p["Surname"].lower() + "*",)).fetchone()[0]
        self.assertGreater(hits, 0)

    def test_2b_search_by_site_name(self):
        from orgx import geo, parse
        dn = self.a_person()["DistinguishedName"]
        site = next(v for k, v in parse.split_dn(dn) if k == "OU" and not geo.CONTAINER.match(v))
        r = live.search(self.ctx, site.lower())
        self.assertTrue(r["ok"], r)
        under = [x for x in self.source if f",ou={site.lower()},".lower() in x["DistinguishedName"].lower()]
        self.assertGreaterEqual(r["fetched"], min(len(under), 400))
        with self.db() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM objects WHERE dn LIKE 'OU=%'").fetchone())

    def test_3_person_expands_up_and_down(self):
        p = self.a_person()
        live.search(self.ctx, p["Surname"])
        with self.db() as conn:
            key = conn.execute("SELECT key FROM objects WHERE lower(dn) = lower(?)", (p["DistinguishedName"],)).fetchone()[0]
        before = self.count()
        r = live.person(self.ctx, key)
        self.assertTrue(r["ok"], r)
        self.assertGreater(self.count(), before)
        with self.db() as conn:
            dns = {d.lower() for (d,) in conn.execute("SELECT dn FROM objects")}
            mgr = conn.execute("SELECT manager_key FROM objects WHERE key = ?", (key,)).fetchone()[0]
        self.assertIn(p["Manager"].lower(), dns)                 # one level up
        self.assertTrue(mgr)                                     # and linked
        reports = [r["DistinguishedName"].lower() for r in self.source if r.get("Manager", "").lower() == p["DistinguishedName"].lower()]
        self.assertTrue(set(reports) <= dns)                     # one level down

    def test_4_unit_and_site(self):
        p = self.a_person()
        live.search(self.ctx, p["Surname"])
        with self.db() as conn:
            org, loc = conn.execute("SELECT org_id, loc_id FROM objects WHERE lower(dn) = lower(?)",
                                    (p["DistinguishedName"],)).fetchone()
        before = self.count()
        r = live.unit(self.ctx, org)
        self.assertTrue(r["ok"], r)
        self.assertGreaterEqual(self.count(), before)
        with self.db() as conn:
            self.assertGreater(conn.execute("SELECT count(*) FROM orgs").fetchone()[0], 0)
        if loc:
            r = live.site(self.ctx, loc)
            self.assertTrue(r["ok"], r)

    def test_5_stale_lookups_run_again(self):
        term = self.a_person()["GivenName"]
        live.search(self.ctx, term)
        self.assertTrue(live.search(self.ctx, term)["cached"])
        with self.db() as conn:
            conn.execute("UPDATE live_fetch SET at = at - 13 * 3600")
        again = live.search(self.ctx, term)
        self.assertFalse(again["cached"])
        self.assertEqual(again["added"], 0)                      # already stored, only refreshed

    def test_6_off_in_export_mode(self):
        api.save_rules(self.ctx, {}, {"ad": {"mode": "export"}})
        try:
            r = live.search(self.ctx, "zz")
            self.assertFalse(r["ok"])
            self.assertTrue(r.get("off"))
        finally:
            api.save_rules(self.ctx, {}, {"ad": {"mode": "live", "liveHours": 12}})


if __name__ == "__main__":
    unittest.main()
