import unittest
from pathlib import Path

from orgx import parse as P
from orgx import reference as ref
from orgx.geo import Gazetteer

DATA = Path(__file__).resolve().parent.parent / "data"


class DisplayNames(unittest.TestCase):
    def check(self, raw, **want):
        got = P.parse_display(raw)
        for k, v in want.items():
            self.assertEqual(got[k], v, f"{raw!r} → {k}")

    def test_daf_formats(self):
        self.check("DOE, JANE M TSgt USSF HQ DAF MERIDIAN GROUP/S36", last="DOE", first="JANE", mi="M",
                   rank="TSgt", grade="E-6", service="USSF", org="MERIDIAN GROUP/S36")
        self.check("PARK, ELENA Lt Col USSF HQ DAF MERIDIAN GROUP/S5", rank="Lt Col", grade="O-5", mi="", org="MERIDIAN GROUP/S5")
        self.check("SMITH, JOHN A CIV USAF HQ DAF AC/S6", rank="CIV", service="USAF", org="AC/S6")
        self.check("REED, HANNAH GS-12 USSF MERIDIAN GROUP/S1", rank="GS-12", grade="GS-12")
        self.check("ITO, SASHA NH-04 USSF HQ DAF MERIDIAN GROUP", grade="NH-4", org="MERIDIAN GROUP")
        self.check("DOE, JOHN A SSgt USAF ATLAS HARBOR COMM SQ/SCOO", grade="E-5", org="ATLAS HARBOR COMM SQ/SCOO")

    def test_service_disambiguates_rank(self):
        self.check("KIM, YUNA CAPT USN FLEET STAFF/N6 (USA)", grade="O-6", country_tag="USA")
        self.check("LEE, AL Capt USAF HARBOR WING/CC", grade="O-3")
        self.check("RAY, ZED SSgt USMC MARINE STAFF/G6", grade="E-6")

    def test_suffix_and_no_rank(self):
        self.check("JONES, BOB A JR MAJ USA ARMY STAFF/G3", last="JONES JR", grade="O-4")
        self.check("SHOP, FRONT OFFICE USSF MERIDIAN GROUP", rank="", org="MERIDIAN GROUP")
        self.assertEqual(P.parse_display("HARBOR COMM SQ Workflow")["last"], "")

    def test_smart_case(self):
        self.assertEqual(P.smart_case("MCDONALD-O'BRIEN"), "McDonald-O'Brien")
        self.assertEqual(P.smart_case("van der Berg"), "van der Berg")


class Directory(unittest.TestCase):
    def test_dn_with_escaped_comma(self):
        ous, dom = P.ou_path("CN=DOE\\, JANE M,OU=Alder Users,OU=Alder,OU=North America,OU=Sites,DC=corp,DC=example")
        self.assertEqual(ous, ["Sites", "North America", "Alder", "Alder Users"])
        self.assertEqual(dom, "corp.example")

    def test_canonical_ou(self):
        ous, dom = P.ou_path(ou="corp.example/Sites/Europe/Fir/Fir Users")
        self.assertEqual(ous[-2:], ["Fir", "Fir Users"])
        self.assertEqual(dom, "corp.example")

    def test_kinds(self):
        k = lambda row, ous=(): P.classify_kind(row, P.parse_display(row.get("display", "")), list(ous))
        self.assertEqual(k({"rtd": "4", "display": "S6 Org Box"}), "orgbox")
        self.assertEqual(k({"rtd": "34359738368"}), "orgbox")
        self.assertEqual(k({"rtd": "RoomMailbox"}), "resource")
        self.assertEqual(k({"rtd": "MailUniversalDistributionGroup"}), "group")
        self.assertEqual(k({"object_class": "group"}), "group")
        self.assertEqual(k({"display": "X"}, ["Sites", "Europe", "Fir", "Fir Organizational Accounts"]), "orgbox")
        self.assertEqual(k({"display": "DOE, JANE Capt USSF X"}), "person")
        self.assertEqual(k({"display": "Bldg 1102 Conf Rm 210 (VTC)"}), "resource")

    def test_multi_valued(self):
        self.assertEqual(len(P.split_multi("CN=A\\, B,OU=X,DC=Y;CN=C\\, D,OU=X,DC=Y")), 2)
        self.assertEqual(len(P.split_multi("CN=A,OU=X,DC=Y,CN=C,OU=X,DC=Y")), 2)

    def test_columns(self):
        m = P.map_columns(["displayName", "telephoneNumber", "l", "physicalDeliveryOfficeName", "WindowsEmailAddress", "msExchRecipientTypeDetails"])
        self.assertEqual(m["display"], "displayName")
        self.assertEqual(m["phone"], "telephoneNumber")
        self.assertEqual(m["city"], "l")
        self.assertEqual(m["rtd"], "msExchRecipientTypeDetails")


class Orgs(unittest.TestCase):
    def test_org_path(self):
        self.assertEqual(P.org_path("USSF MERIDIAN GROUP/S3/S36", ""), ["MERIDIAN GROUP", "S3", "S36"])
        self.assertEqual(P.org_path("", "HQ DAF MERIDIAN GROUP/S6"), ["MERIDIAN GROUP", "S6"])
        self.assertEqual(P.org_path("HARBOR COMM SQ\\SCOO", ""), ["HARBOR COMM SQ", "SCOO"])

    def test_codes(self):
        self.assertEqual(P.code_function("S36"), "ops")
        self.assertEqual(P.code_function("A6X"), "cyber")
        self.assertEqual(P.code_function("SCOO"), "cyber")
        self.assertEqual(P.code_function("JA"), "support")
        self.assertEqual(P.org_kind("FWD-FIR"), "forward")
        self.assertEqual(P.org_kind("HARBOR COMM SQ"), "unit")

    def test_functions(self):
        kw = {fn: [w.strip() for w in s.split(",")] for fn, s in ref.DEFAULT_FN_KEYWORDS.items()}
        self.assertEqual(P.classify_functions("SATCOM Planner", ["MERIDIAN GROUP", "S6", "S62"], "17C", kw)[0], "cyber")
        self.assertIn("exercises", P.classify_functions("Exercise Lead Planner", ["MERIDIAN GROUP", "S3", "S36"], "13S", kw))
        P.CODE_OVERRIDES["S36"] = "exercises"
        try:
            self.assertEqual(P.classify_functions("MSEL Manager", ["MERIDIAN GROUP", "S3", "S36"], "1C6", kw)[0], "exercises")
        finally:
            P.CODE_OVERRIDES.clear()

    def test_leader_scores(self):
        self.assertGreater(ref.leader_score("Commander"), ref.leader_score("Deputy Commander"))
        self.assertEqual(ref.leader_score("Commander Action Group"), 0)
        self.assertLess(ref.leader_score("Command Chief Executive Assistant"), ref.leader_score("Superintendent"))
        self.assertGreater(ref.leader_score("Chief, Current Operations (S33)"), ref.leader_score("Executive Officer"))

    def test_grade_levels(self):
        self.assertGreater(ref.grade_level("O-4"), ref.grade_level("E-9"))
        self.assertEqual(ref.grade_level("GS-15"), ref.grade_level("O-6"))
        self.assertEqual(ref.grade_level("NH-4"), 25.5)


class SnapshotDates(unittest.TestCase):
    def test_as_of(self):
        from orgx.ingest import as_of_date
        self.assertEqual(as_of_date(Path("gal_20260801.csv")), "2026-08-01")
        self.assertEqual(as_of_date(Path("20261003-005855_gal_2026-08-01.csv")), "2026-08-01")
        self.assertEqual(as_of_date(Path("x.csv"), "2025-01-02"), "2025-01-02")


class Places(unittest.TestCase):
    """No real sites ship with ORGX: the site level is learned and coordinates come from a local list."""
    @classmethod
    def setUpClass(cls):
        import json
        import shutil
        import tempfile
        cls.tmp = Path(tempfile.mkdtemp(prefix="orgx-geo-"))
        shutil.copy(DATA / "centroids.json", cls.tmp / "centroids.json")
        (cls.tmp / "sites.json").write_text(json.dumps({"sites": [
            {"name": "Alder", "full": "Alder (Portland)", "lat": 45.5, "lon": -122.7, "tz": "America/Los_Angeles",
             "country": "US", "state": "OR", "aliases": ["Portland"]},
            {"name": "Fir", "lat": 45.8, "lon": 4.8, "tz": "Europe/Paris", "country": "FR"}]}))
        cls.g = Gazetteer(cls.tmp, None, {"site": 2, "region": 1})

    def test_learned_site_level_wins(self):
        loc = self.g.place(["Sites", "North America", "Alder", "Users"], [], "Bldg 1", "Lyon", "", "FR")
        self.assertEqual(loc["id"], "Alder")
        self.assertEqual(loc["region"], "North America")
        self.assertFalse(loc["approx"])

    def test_office_city_and_anchor(self):
        self.assertEqual(self.g.place([], [], "Bldg 1", "Portland", "OR", "US")["id"], "Alder")
        self.assertEqual(self.g.place(["Corp", "Sites", "Europe", "Fir"], ["Sites"], "", "", "", "")["id"], "Fir")

    def test_unknown_is_approximate(self):
        loc = self.g.place(["Sites", "Europe", "Oak", "Users"], [], "", "Graz", "", "Austria")
        self.assertEqual(loc["id"], "ou:Oak")
        self.assertTrue(loc["approx"])
        self.assertIsNotNone(loc["lat"])
        loc = self.g.place([], [], "", "Madison", "WI", "United States")
        self.assertEqual(loc["state"], "WI")
        self.assertEqual(loc["tz"], "America/Chicago")

    def test_no_site_list(self):
        g = Gazetteer(Path(self.tmp / "missing"), None, {"site": 2, "region": None})
        self.assertEqual(g.place(["Sites", "Europe", "Fir", "Users"], [], "", "", "", "")["id"], "ou:Fir")

    def test_learner(self):
        from orgx.geo import OuLearner
        lr = OuLearner()
        for site, region, city in [("Alder", "North America", "Portland"), ("Birch", "North America", "Denver"),
                                   ("Fir", "Europe", "Lyon"), ("Ginkgo", "Europe", "Utrecht")]:
            for box in ("Users", "Users", "Users", "Resources"):
                lr.add(["Sites", region, site, box], city)
        lr.add(["Remote", "Users"], "Madison")
        self.assertEqual(lr.result(), {"site": 2, "region": 1})


if __name__ == "__main__":
    unittest.main()
