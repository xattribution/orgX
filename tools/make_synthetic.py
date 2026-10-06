#!/usr/bin/env python3
"""Write synthetic AD/GAL exports shaped like tools/Export-ADDirectory.ps1 output.

Everything is fictional: the organization, its units, sites and people are invented,
emails use the reserved corp.example domain, and the OU tree is a neutral
OU=Sites/<region>/<site> layout. Org mailboxes, distribution lists (with members),
rooms, manager links, and N monthly snapshots with churn (moves, promotions,
retitles, arrivals and departures) so the Changes view has something to show.

    python3 tools/make_synthetic.py                    # 2 snapshots, ~1.4k people
    python3 tools/make_synthetic.py --scale 20 --snapshots 3   # ~28k people
    python3 tools/make_synthetic.py --copies 300 --scale 7 --snapshots 1 --messy   # ~900k objects

--copies repeats the whole organization under numbered names and spreads the copies over
numbered sites, for directories with thousands of units. --messy writes a few people's
department the way hand-kept directories drift: hyphenated, with a country prefix, or as a
partner's liaison ("AU USSF …").
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import uuid
import zlib
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DC = "DC=corp,DC=example"
DOMAIN = "corp.example"

FIRST = """Morgan Avery Drew Sasha Keoni Priya Miles Hannah Sam Elena Noah Lila Owen Mei Victor Hayden Taylor Jordan
Riley Chris Casey Amina Brett Robin Dana Luis Greta Ivy Marcus Jonah Nadia Philip Wren Quinn Tessa Omar Paige Felix
Yuna Ben Nora Kai Amy Leo Hana Seth Rin Cole Aiko Daniel Sora Minjun Grace Luke Maya Pilar Erin Tom Holly Nate Yuki
Claire Adrian Imani Reed Grant Marc Helen Ana Diego Sofia Mateo Isabel Kenji Haruto Ji-woo Seo-yeon Arjun Kavya
Tariq Layla Kwame Ama Tobias Freya Lars Ingrid Mateus Bianca Rafael Camila Ethan Olivia Liam Emma Mason Ava Lucas Mia
Elijah Harper James Evelyn Henry Abigail Jack Ella Owen Scarlett Wyatt Aria Julian Chloe Ezra Nova Theo Zoe Malik
Aisha Jamal Keisha Andre Talia Dmitri Katya Nikolai Anya Omar Fatima Hiro Akane Pita Moana Kalani Leilani""".split()
LAST = """Voss Quinn Lang Ito Hale Nair Okafor Reed Okonkwo Varga Park Rahman Briggs Chen Daly Brooks Kim Ellis Cho Pena
Nguyen Hassan Olsen Adler Singh Moreno Walsh Delgado Patel Bell Keller Ross Grant Sato Farouk Lindstrom Ortiz Caldwell
West Matsuda Foster Bennett Fujimoto Warren Takeda Ramirez Morita Han Lee Yoon Santos Cruz Reyes Gomez Blake Oshima Abe
Dunn Tan Cole Nolan Nash Villanueva Alvarez Bauer Castillo Dubois Eriksen Fischer Garcia Hoffman Ivanova Jensen
Kowalski Larsen Muller Novak Oconnor Petrov Rossi Schmidt Tanaka Ueda Vasquez Weber Yamamoto Zhang Achebe Banda
Carvalho Diallo Edwards Flores Gonzalez Hughes Iqbal Johnson Kapoor Lopez Mensah Nakamura Owusu Pham Quispe Rivera
Suzuki Thompson Uddin Vargas Williams Xu Yilmaz Zimmerman Mcdonald Obrien Kahananui Kealoha Makoa""".split()

# site key → (site OU, region OU, city, state, country, phone area)
SITES = {
    "alder": ("Alder", "North America", "Portland", "OR", "United States", "503"),
    "birch": ("Birch", "North America", "Denver", "CO", "United States", "720"),
    "cedar": ("Cedar", "North America", "Austin", "TX", "United States", "512"),
    "dogwood": ("Dogwood", "North America", "Raleigh", "NC", "United States", "919"),
    "elm": ("Elm", "North America", "Toronto", "ON", "Canada", "416"),
    "fir": ("Fir", "Europe", "Lyon", "", "France", "04"),
    "ginkgo": ("Ginkgo", "Europe", "Utrecht", "", "Netherlands", "030"),
    "hazel": ("Hazel", "Asia Pacific", "Brisbane", "QLD", "Australia", "07"),
    "iris": ("Iris", "Asia Pacific", "Sendai", "Miyagi", "Japan", "022"),
    "juniper": ("", "", "Madison", "WI", "United States", "608"),   # no OU: placed by city/state
}
CC = {"Canada": "1", "France": "33", "Netherlands": "31", "Australia": "61", "Japan": "81"}
# demo-only coordinates for the invented sites (written next to the exports as sites.json)
COORDS = {"alder": (45.52, -122.68, "America/Los_Angeles", "US", "OR"), "birch": (39.74, -104.99, "America/Denver", "US", "CO"),
          "cedar": (30.27, -97.74, "America/Chicago", "US", "TX"), "dogwood": (35.78, -78.64, "America/New_York", "US", "NC"),
          "elm": (43.65, -79.38, "America/Toronto", "CA", ""), "fir": (45.76, 4.84, "Europe/Paris", "FR", ""),
          "ginkgo": (52.09, 5.12, "Europe/Amsterdam", "NL", ""), "hazel": (-27.47, 153.03, "Australia/Brisbane", "AU", ""),
          "iris": (38.27, 140.87, "Asia/Tokyo", "JP", "")}

GRADES = {
    "o6": ["Col"], "o5": ["Lt Col"], "o4": ["Maj"], "o3": ["Capt"], "o2": ["1st Lt", "2d Lt"],
    "e9": ["CMSgt"], "e8": ["SMSgt"], "e7": ["MSgt"], "e6": ["TSgt"], "e5": ["SSgt", "Sgt"], "e4": ["SrA", "Spc4"],
    "civ": ["GS-15", "GS-14", "GS-13", "GS-12", "GS-11", "NH-04", "NH-03"], "ctr": ["CTR"],
}
PROMO = {"2d Lt": "1st Lt", "1st Lt": "Capt", "Capt": "Maj", "Maj": "Lt Col", "Lt Col": "Col", "SrA": "SSgt",
         "Spc4": "Sgt", "Sgt": "TSgt", "SSgt": "TSgt", "TSgt": "MSgt", "MSgt": "SMSgt", "SMSgt": "CMSgt",
         "GS-11": "GS-12", "GS-12": "GS-13", "GS-13": "GS-14"}
AFSC = {"ops": ["13S", "1C6"], "intel": ["14N", "1N0", "1N8"], "cyber": ["17S", "17D", "1D7", "3D1", "1B4"],
        "plans": ["13S", "16R"], "exercises": ["13S", "1C6"], "personnel": ["38F", "3F0"],
        "logistics": ["21R", "2S0", "2G0"], "resources": ["65F", "6F0", "62E"], "command": ["13S", "1C6"],
        "support": ["51J", "5J0", "35P", "3N0"]}

# title pools
POOL = {
    "command": ["Executive Officer", "Executive Assistant", "Protocol Officer", "Commander's Action Group",
                "Speechwriter", "Aide-de-Camp", "Command Chief Executive Assistant"],
    "personnel": ["Personnel Craftsman", "Awards & Decorations Manager", "Evaluations Manager", "Orders Technician",
                  "Commander's Support Staff", "Manpower Analyst", "Sponsor Program Manager"],
    "intel": ["Threat Analyst", "All-Source Analyst", "Collection Manager", "Targeting Analyst",
              "Security Manager", "Intel Analyst", "Foreign Disclosure Officer"],
    "ops": ["Battle Captain", "Current Operations Officer", "Operations Planner", "Navigation Officer",
            "Tasker Manager", "OPSEC Program Manager", "Weather Officer", "Watch Officer"],
    "plans": ["Joint Planner", "Strategy Analyst", "Annex N Planner", "Campaign Planner",
              "Security Cooperation Planner", "Partner Engagement Officer", "Plans Integrator"],
    "exercises": ["Exercise Planner", "MSEL Manager", "Training NCO", "Exercise Lead Planner",
                  "Wargame Planner", "Exercise Control Lead"],
    "cyber": ["SATCOM Planner", "Spectrum Manager", "Cyber Defense NCO", "Network Operations", "Client Systems Technician",
              "Knowledge Manager", "COMSEC Manager", "CISO Support", "Defensive Cyber Operator", "VTC Administrator",
              "Cybersecurity Liaison"],
    "logistics": ["Logistics Craftsman", "Supply Technician", "Vehicle Control Officer", "Facilities Manager",
                  "Equipment Custodian", "Deployment Manager"],
    "resources": ["Budget Analyst", "FM Analyst", "Purchase Card Approving Official", "Resource Advisor",
                  "Requirements Manager", "Travel Approving Official"],
    "support": ["Staff Judge Advocate", "Paralegal", "Public Affairs Officer", "Historian", "Inspector General"],
}

# path, site, size, function, leader title, leader grade, sub-leader grade
ORGS = [
    # a headquarters with staff directorates and offices nested by office symbol
    ("ATLAS COMMAND", "alder", 6, "command", "Commander", "o6", None),
    ("ATLAS COMMAND/CAG", "alder", 5, "command", "Director, Commander's Action Group", "o4", None),
    ("ATLAS COMMAND/A1", "alder", 8, "personnel", "Director of Personnel", "o5", None),
    ("ATLAS COMMAND/A2", "alder", 12, "intel", "Director of Intelligence", "o6", None),
    ("ATLAS COMMAND/A3", "alder", 14, "ops", "Director of Operations", "o6", None),
    ("ATLAS COMMAND/A3/A33", "alder", 12, "ops", "Chief, Current Operations", "o5", None),
    ("ATLAS COMMAND/A3/A36", "alder", 8, "exercises", "Chief, Exercises", "o4", None),
    ("ATLAS COMMAND/A5", "alder", 11, "plans", "Director of Strategy & Plans", "o6", None),
    ("ATLAS COMMAND/A6", "alder", 8, "cyber", "Director of Communications", "o6", None),
    ("ATLAS COMMAND/A6/A6X", "alder", 6, "cyber", "Chief, Cyberspace Operations", "o5", None),
    ("ATLAS COMMAND/A6/A6XP", "alder", 5, "cyber", "Chief, Cyber Plans", "o4", None),
    ("ATLAS COMMAND/A8", "alder", 6, "resources", "Director of Resources", "civ", None),
    ("ATLAS COMMAND/JA", "alder", 3, "support", "Staff Judge Advocate", "o4", None),
    ("ATLAS COMMAND/FWD-FIR", "fir", 6, "ops", "Forward Lead, Fir", "o5", None),
    ("ATLAS COMMAND/FWD-HAZEL", "hazel", 5, "plans", "Forward Lead, Hazel", "o4", None),
    # a second headquarters with S-staff and a liaison office
    ("MERIDIAN GROUP", "birch", 4, "command", "Commander", "o6", None),
    ("MERIDIAN GROUP/S2", "birch", 10, "intel", "Director of Intelligence (S2)", "o5", None),
    ("MERIDIAN GROUP/S3", "birch", 6, "ops", "Director of Operations (S3)", "o5", None),
    ("MERIDIAN GROUP/S3/S33", "birch", 12, "ops", "Chief, Current Operations (S33)", "o4", None),
    ("MERIDIAN GROUP/S3/S36", "birch", 8, "exercises", "Chief, Exercises (S36)", "o4", None),
    ("MERIDIAN GROUP/S5", "birch", 9, "plans", "Director of Plans (S5)", "o5", None),
    ("MERIDIAN GROUP/S6", "birch", 6, "cyber", "Director of Communications (S6)", "o5", None),
    ("MERIDIAN GROUP/S6/S62", "birch", 8, "cyber", "Chief, SATCOM & Spectrum (S62)", "o4", None),
    ("MERIDIAN GROUP/FWD-GINKGO", "ginkgo", 6, "ops", "Forward Lead, Ginkgo", "o4", None),
    ("MERIDIAN GROUP/LNO-ELM", "elm", 3, "plans", "Liaison Officer, Elm", "o5", None),
    # a wing whose squadrons are separate top-level units, tied together only by manager links
    ("HARBOR WING", "cedar", 5, "command", "Commander", "o6", None),
    ("HARBOR SUPPORT GROUP", "cedar", 4, "command", "Commander", "o6", None),
    ("HARBOR OPERATIONS GROUP", "cedar", 4, "command", "Commander", "o6", None),
    ("HARBOR COMM SQ", "cedar", 6, "cyber", "Commander", "o5", None),
    ("HARBOR COMM SQ/SCO", "cedar", 6, "cyber", "Operations Flight Commander", "o3", None),
    ("HARBOR COMM SQ/SCOO", "cedar", 12, "cyber", "Superintendent, Network Operations", "e8", None),
    ("HARBOR COMM SQ/SCOS", "cedar", 9, "cyber", "Section Chief, Spectrum Management", "e7", None),
    ("HARBOR COMM SQ/SCX", "cedar", 6, "cyber", "Chief, Plans & Resources", "o3", None),
    ("HARBOR OPS SUPPORT SQ", "cedar", 22, "ops", "Commander", "o5", None),
    ("HARBOR FORCE SUPPORT SQ", "cedar", 20, "personnel", "Commander", "o5", None),
    ("HARBOR LOGISTICS SQ", "dogwood", 20, "logistics", "Commander", "o5", None),
    # a field center with labs, and a team spread across sites
    ("SUMMIT CENTER", "dogwood", 6, "command", "Director", "civ", None),
    ("SUMMIT CENTER/LAB-1", "dogwood", 18, "cyber", "Lab Chief", "civ", None),
    ("SUMMIT CENTER/LAB-2", "iris", 14, "intel", "Lab Chief", "civ", None),
    ("SUMMIT CENTER/DET-JUNIPER", "juniper", 8, "resources", "Detachment Chief", "civ", None),
    ("BEACON TEAM", "elm", 5, "command", "Commander", "o5", None),
    ("BEACON TEAM/OPS", "elm", 14, "ops", "Chief, Operations", "o4", None),
    ("BEACON TEAM/CYBER", "ginkgo", 12, "cyber", "Chief, Cyber", "o4", None),
]
# units whose commander reports to another unit (drives manager-based parent inference)
REPORTS_TO = {"HARBOR SUPPORT GROUP": "HARBOR WING", "HARBOR OPERATIONS GROUP": "HARBOR WING",
              "HARBOR COMM SQ": "HARBOR SUPPORT GROUP", "HARBOR FORCE SUPPORT SQ": "HARBOR SUPPORT GROUP",
              "HARBOR LOGISTICS SQ": "HARBOR SUPPORT GROUP", "HARBOR OPS SUPPORT SQ": "HARBOR OPERATIONS GROUP",
              "HARBOR WING": "ATLAS COMMAND", "BEACON TEAM": "MERIDIAN GROUP"}
SERVICE = {"ATLAS COMMAND": "USAF", "HARBOR": "USAF", "MERIDIAN GROUP": "USSF", "BEACON TEAM": "USSF", "SUMMIT CENTER": "USAF"}


def service_of(org: str) -> str:
    root = org.split("/")[0]
    return next((v for k, v in SERVICE.items() if root.startswith(k)), "USAF")


ORG_LEAD = {o[0]: o[4] for o in ORGS}


class Gen:
    def __init__(self, seed: int, scale: float):
        self.rng = random.Random(seed)
        self.scale = scale
        self.used = set()
        self.people = []      # dicts
        self.serial = 0

    def name(self):
        for _ in range(200):
            f, l = self.rng.choice(FIRST), self.rng.choice(LAST)
            if (f, l) not in self.used:
                self.used.add((f, l))
                return f, l
        self.serial += 1
        return self.rng.choice(FIRST), f"{self.rng.choice(LAST)}{self.serial}"

    def grade_for(self, fn):
        r = self.rng.random()
        if r < 0.18:
            return self.rng.choice(["o3", "o3", "o4", "o2"])
        if r < 0.62:
            return self.rng.choice(["e4", "e5", "e5", "e6", "e6", "e7"])
        if r < 0.86:
            return "civ"
        return "ctr"

    messy = False

    def dept_of(self, org):
        """The department as typed: usually the org path, sometimes a drifted spelling of its root."""
        if not self.messy or self.rng.random() > 0.05:
            return org
        root, _, rest = org.partition("/")
        joined = root.replace(" ", "-")
        variant = self.rng.choice([joined, "US" + joined, f"AU {service_of(org)} {root}"])
        return variant + ("/" + rest if rest and self.rng.random() < 0.6 else "")

    def person(self, org, base, fn, title, gk, now_id=None):
        f, l = self.name()
        rank = self.rng.choice(GRADES[gk])
        mi = self.rng.choice("ABCDEFGHJKLMNPRSTW") if self.rng.random() < 0.8 else ""
        return {
            "guid": now_id or str(uuid.UUID(int=self.rng.getrandbits(128))),
            "first": f, "last": l, "mi": mi, "rank": rank, "org": org, "dept": self.dept_of(org), "base": base, "fn": fn, "title": title,
            "career": self.rng.choice(AFSC[fn]) if gk not in ("civ", "ctr") else "",
            "ext": self.rng.randint(1000, 9999),
        }

    def build(self):
        for path, base, size, fn, lead_title, lead_gk, _ in ORGS:
            n = max(1, round(size * self.scale))
            self.people.append(self.person(path, base, fn, lead_title, lead_gk))
            if "/" not in path and lead_title == "Commander":
                self.people.append(self.person(path, base, fn, "Deputy Commander" if lead_gk == "o6" else "Director of Operations",
                                               "o5" if lead_gk == "o6" else "o4"))
                self.people.append(self.person(path, base, fn, "Senior Enlisted Leader", "e9" if lead_gk == "o6" else "e8"))
            for _ in range(n - 1):
                gk = self.grade_for(fn)
                pool = POOL[fn] if self.rng.random() < 0.8 else POOL[self.rng.choice(list(POOL))]
                t = self.rng.choice(pool)
                if gk == "ctr":
                    t = f"{t} (Contractor Support)"
                self.people.append(self.person(path, base, fn, t, gk))


def dn_for(p, kind="person"):
    ou, region = SITES[p["base"]][0], SITES[p["base"]][1]
    cn = f"{p['last'].upper()}\\, {p['first'].upper()} {p['mi']}".strip() if kind == "person" else p["display"].replace(",", "\\,")
    if not ou:
        return f"CN={cn},OU=Users,OU=Remote,{DC}"
    sub = {"person": "Users", "orgbox": "Shared Mailboxes", "group": "Distribution Lists", "resource": "Resources"}[kind]
    return f"CN={cn},OU={sub},OU={ou},OU={region},OU=Sites,{DC}"


def email_of(p):
    return f"{p['first'].lower()}.{p['last'].lower()}@{DOMAIN}"


def display_of(p):
    return f"{p['last'].upper()}, {p['first'].upper()} {p['mi']} {p['rank']} {service_of(p['org'])} {p.get('dept') or p['org']}".replace("  ", " ")


def phone_of(p):
    area, country = SITES[p["base"]][5], SITES[p["base"]][4]
    cc = CC.get(country)
    if not cc or cc == "1":
        return f"+1 ({area}) 555-{p['ext']:04d}"
    return f"+{cc} {area.lstrip('0')} 555-{p['ext']:04d}"


def churn(g: Gen, people: list[dict], month: int) -> list[dict]:
    rng = g.rng
    out = []
    for p in people:
        r = rng.random()
        if r < 0.035 and "Commander" not in p["title"]:
            continue                                   # departed (PCS / separation)
        q = dict(p)
        if rng.random() < 0.03 and p["title"] != ORG_LEAD.get(p["org"]):   # internal move (not the boss)
            same_root = [o for o in ORGS if o[0].split("/")[0] == p["org"].split("/")[0] and o[0] != p["org"]]
            if same_root:
                o = rng.choice(same_root)
                q["org"], q["base"], q["fn"] = o[0], o[1], o[3]
                q["dept"] = g.dept_of(o[0])
                q["title"] = rng.choice(POOL[o[3]])
        if rng.random() < 0.025 and q["rank"] in PROMO:
            q["rank"] = PROMO[q["rank"]]
        if rng.random() < 0.02 and q["title"] != ORG_LEAD.get(q["org"]) and "Commander" not in q["title"]:
            q["title"] = rng.choice(POOL[q["fn"]])
        if rng.random() < 0.01:
            q["ext"] = rng.randint(1000, 9999)
        out.append(q)
    # arrivals
    for _ in range(round(len(people) * 0.035)):
        path, base, size, fn, *_ = rng.choice(ORGS)
        out.append(g.person(path, base, fn, rng.choice(POOL[fn]), g.grade_for(fn)))
    return out


FIELDS = ["DisplayName", "GivenName", "Surname", "Initials", "Title", "Department", "Company", "Office", "Phone",
          "MobilePhone", "WindowsEmailAddress", "UserPrincipalName", "SamAccountName", "City", "StateOrProvince",
          "CountryOrRegion", "DistinguishedName", "Manager", "Members", "ManagedBy", "RecipientTypeDetails",
          "ObjectGUID", "CareerField", "WhenCreated", "Enabled"]


def stable_guid(text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "synthetic:" + text))


def write(people: list[dict], out: Path, rng: random.Random):
    by_org = {}
    for p in people:
        by_org.setdefault(p["org"], []).append(p)
    lead = {}
    for org, ps in by_org.items():
        lead[org] = next((p for p in ps if p["title"] in ("Commander",) or p["title"].startswith(("Director", "Chief", "Forward Lead", "Superintendent", "Section Chief", "Liaison", "Lab Chief", "Staff Judge", "Operations Flight", "Detachment"))), ps[0])

    def manager(p):
        org = p["org"]
        if lead.get(org) is not p:
            return lead[org]
        parts = org.split("/")
        while len(parts) > 1:
            parts = parts[:-1]
            if "/".join(parts) in lead:
                return lead["/".join(parts)]
        up = REPORTS_TO.get(org)
        return lead.get(up) if up else None

    rows = []
    for p in people:
        b = SITES[p["base"]]
        m = manager(p)
        rows.append({
            "DisplayName": display_of(p), "GivenName": p["first"].upper(), "Surname": p["last"].upper(),
            "Initials": p["mi"], "Title": p["title"],
            "Department": p.get("dept") or p["org"], "Company": p["org"].split("/")[0].title(),
            "Office": f"Bldg {1000 + zlib.crc32(p['org'].encode()) % 900}" if b[0] else "Research Park",
            "Phone": phone_of(p), "MobilePhone": "", "WindowsEmailAddress": email_of(p),
            "UserPrincipalName": f"{zlib.crc32(p['guid'].encode()) * 7 % 10**10:010d}@{DOMAIN}",
            "SamAccountName": f"{p['first'][:1].lower()}{p['last'].lower()}"[:20],
            "City": b[2], "StateOrProvince": b[3], "CountryOrRegion": b[4],
            "DistinguishedName": dn_for(p), "Manager": dn_for(m) if m else "", "Members": "", "ManagedBy": "",
            "RecipientTypeDetails": "UserMailbox", "ObjectGUID": p["guid"], "CareerField": p["career"],
            "WhenCreated": "", "Enabled": "True",
        })
    # org mailboxes (every org with 5+), DLs per top-level unit, a few topical DLs, rooms per site
    for org, ps in sorted(by_org.items()):
        if len(ps) < 5:
            continue
        base = ps[0]["base"]
        disp = f"{org} Org Box" if "/" in org else f"{org} Workflow"
        ob = {"display": disp, "base": base}
        slug = org.lower().replace("/", ".").replace(" ", "").replace("-", "")
        rows.append({**{k: "" for k in FIELDS}, "DisplayName": disp, "Title": "Organizational Mailbox",
                     "Department": org,
                     "WindowsEmailAddress": f"{slug}.orgbox@{DOMAIN}", "Phone": phone_of(ps[0]),
                     "City": SITES[base][2], "StateOrProvince": SITES[base][3], "CountryOrRegion": SITES[base][4],
                     "DistinguishedName": dn_for(ob, "orgbox"), "RecipientTypeDetails": "SharedMailbox",
                     "ObjectGUID": stable_guid(disp), "Enabled": "False"})
    roots = {}
    for p in people:
        roots.setdefault(p["org"].split("/")[0], []).append(p)
    for root, ps in sorted(roots.items()):
        base = ps[0]["base"]
        disp = f"{root} All Personnel"
        g = {"display": disp, "base": base}
        rows.append({**{k: "" for k in FIELDS}, "DisplayName": disp, "Department": root,
                     "WindowsEmailAddress": f"{root.lower().replace(' ', '').replace('-', '')}.all@{DOMAIN}",
                     "DistinguishedName": dn_for(g, "group"), "RecipientTypeDetails": "MailUniversalDistributionGroup",
                     "Members": ";".join(dn_for(p) for p in ps), "ManagedBy": dn_for(lead[ps[0]["org"]]),
                     "City": SITES[base][2], "CountryOrRegion": SITES[base][4],
                     "ObjectGUID": stable_guid(disp)})
    topical = [("MERIDIAN GROUP Exercise Planners", ["exercise", "wargame", "s36"]),
               ("MERIDIAN GROUP SATCOM Working Group", ["satcom", "spectrum", "s62"]),
               ("Atlas Cyber Defense", ["cyber", "network"]),
               ("Annex N Writers", ["annex n", "planner", "s5"])]
    for disp, words in topical:
        ms = [p for p in people if any(w in (p["title"] + " " + p["org"]).lower() for w in words)][:25]
        g = {"display": disp, "base": "birch"}
        rows.append({**{k: "" for k in FIELDS}, "DisplayName": disp, "Department": "MERIDIAN GROUP",
                     "WindowsEmailAddress": f"{disp.lower().replace(' ', '.')}@{DOMAIN}",
                     "DistinguishedName": dn_for(g, "group"), "RecipientTypeDetails": "MailUniversalDistributionGroup",
                     "Members": ";".join(dn_for(p) for p in ms), "City": "Denver", "CountryOrRegion": "United States",
                     "ObjectGUID": stable_guid(disp)})
    for key, b in SITES.items():
        if not b[0]:
            continue
        for room in ("Conf Rm 210 (VTC)", "Conf Rm 118"):
            disp = f"{b[0]} Bldg 1102 {room}"
            r = {"display": disp, "base": key}
            rows.append({**{k: "" for k in FIELDS}, "DisplayName": disp, "City": b[2], "StateOrProvince": b[3],
                         "CountryOrRegion": b[4], "DistinguishedName": dn_for(r, "resource"),
                         "WindowsEmailAddress": f"{key}.{room.split()[0].lower()}{len(room)}@{DOMAIN}",
                         "RecipientTypeDetails": "RoomMailbox", "ObjectGUID": stable_guid(disp)})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def expand(copies: int) -> None:
    """Repeat the organization `copies` times: copy k renames every root to "<root> k" and moves
    to numbered sites, so a big run has thousands of units and a few hundred sites."""
    global ORGS, REPORTS_TO, ORG_LEAD
    orgs, reports = list(ORGS), dict(REPORTS_TO)
    for k in range(2, copies + 1):
        grp = k % 25

        def rn(path):
            root, sep, rest = path.partition("/")
            return f"{root} {k}{sep}{rest}"
        for path, base, *rest in ORGS:
            key = f"{base}{grp}" if grp and SITES[base][0] else base
            if key not in SITES:
                ou, region, *more = SITES[base]
                SITES[key] = (f"{ou} {grp}", region, *more)
            orgs.append((rn(path), key, *rest))
        reports.update({rn(a): rn(b) for a, b in REPORTS_TO.items()})
    ORGS, REPORTS_TO = orgs, reports
    ORG_LEAD = {o[0]: o[4] for o in ORGS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--snapshots", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--copies", type=int, default=1)
    ap.add_argument("--messy", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "synthetic"))
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sites = [{"name": SITES[k][0], "full": f"{SITES[k][0]} ({SITES[k][2]})", "lat": c[0], "lon": c[1], "tz": c[2],
              "country": c[3], "state": c[4], "aliases": [SITES[k][2]]} for k, c in COORDS.items()]
    (out_dir / "sites.json").write_text(json.dumps({"sites": sites}, indent=1), encoding="utf-8")
    if a.copies > 1:
        expand(a.copies)
    g = Gen(a.seed, a.scale)
    g.messy = a.messy
    g.build()
    people = g.people
    start = date.today() - timedelta(days=30 * (a.snapshots - 1))
    for i in range(a.snapshots):
        if i:
            people = churn(g, people, i)
        d = start + timedelta(days=30 * i)
        path = Path(a.out) / f"synthetic_gal_{d.isoformat()}.csv"
        n = write(people, path, g.rng)
        print(f"wrote {n:,} rows ({len(people):,} people) -> {path}")


if __name__ == "__main__":
    main()
