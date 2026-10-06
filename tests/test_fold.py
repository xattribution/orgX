"""Drifted spellings of a unit fold into one; near misses are only suggested."""
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orgx import api, fold  # noqa: E402
from orgx.ingest import ingest  # noqa: E402


class Plan(unittest.TestCase):
    counts = Counter({"MERIDIAN GROUP": 500, "MERIDIAN-GROUP": 12, "Meridian Group": 3, "USMERIDIAN-GROUP": 10,
                      "AU USSF MERIDIAN GROUP": 4, "USA COMMAND": 5, "COMMAND": 50, "ATLAS COMMAND": 9,
                      "ATLAS COMMAND 2": 8, "HARBOR WING": 40, "HARBOR WNG": 2})

    def test_folds(self):
        m = fold.mapping(fold.plan(self.counts))
        for v in ("MERIDIAN-GROUP", "Meridian Group", "USMERIDIAN-GROUP", "AU USSF MERIDIAN GROUP"):
            self.assertEqual(m[v], "MERIDIAN GROUP", v)
        self.assertNotIn("USA COMMAND", m, "a generic bare name is not enough to fold on")
        self.assertNotIn("ATLAS COMMAND 2", m, "numbered sister units stay apart")
        self.assertNotIn("HARBOR WNG", m, "one letter apart is only suggested")

    def test_rules_win(self):
        m = fold.mapping(fold.plan(self.counts, separate=["USMERIDIAN-GROUP"], aliases={"MERIDIAN-GROUP": "X"}))
        self.assertNotIn("USMERIDIAN-GROUP", m)
        self.assertNotIn("MERIDIAN-GROUP", m)

    def test_suggestions(self):
        s = fold.suggest(self.counts, fold.mapping(fold.plan(self.counts)))
        self.assertEqual([(x["from"], x["into"]) for x in s], [("HARBOR WNG", "HARBOR WING")])


class Ingest(unittest.TestCase):
    def test_messy_directory_folds(self):
        tmp = Path(tempfile.mkdtemp(prefix="orgx-fold-"))
        try:
            shutil.copy(ROOT / "data" / "centroids.json", tmp / "centroids.json")
            subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--out", str(tmp / "s"),
                            "--snapshots", "1", "--copies", "2", "--messy", "--scale", "2"], check=True, capture_output=True)
            ingest(next((tmp / "s").glob("*.csv")), tmp, log=lambda m: None)
            conn = sqlite3.connect(tmp / "org.db")
            roots = {r[0] for r in conn.execute("SELECT id FROM orgs WHERE parent IS NULL")}
            depts = {r[0].split("/")[0] for r in conn.execute("SELECT dept FROM objects WHERE dept <> ''")}
            conn.close()
            self.assertTrue(any(d.startswith(("US", "AU ")) or "-" in d for d in depts), "the export has drifted spellings")
            drifted = [r for r in roots if r.startswith(("USATLAS", "USMERIDIAN", "AU ")) or "ATLAS-COMMAND" in r]
            self.assertEqual(drifted, [])
            q = api.quality(api.Ctx(tmp), {}, None)
            self.assertGreater(q["foldCount"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
