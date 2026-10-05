"""Reference tables: functions, ranks, object kinds, routing topics.

Defaults only. data/rules.json (edited from the Data → Rules page) layers on
top; see rules.py.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- functions
FUNCTIONS = [
    ("command", "Command"),
    ("ops", "Operations"),
    ("intel", "Intelligence"),
    ("cyber", "Cyber / Comm"),
    ("plans", "Plans & Strategy"),
    ("exercises", "Exercises & Training"),
    ("personnel", "Personnel"),
    ("logistics", "Logistics"),
    ("resources", "Resources"),
    ("support", "Special staff"),
]
FN_LABEL = dict(FUNCTIONS)

# S/J/A/G/N + digit(s): staff directorates. A10 (nuclear) → ops.
STAFF_DIGIT = {"1": "personnel", "2": "intel", "3": "ops", "4": "logistics", "5": "plans",
               "6": "cyber", "7": "exercises", "8": "resources", "9": "plans"}
SPECIAL_CODES = {
    "CC": "command", "CV": "command", "CD": "command", "CCE": "command", "CCC": "command", "CCS": "command",
    "CMD": "command", "CAG": "command", "CS": "command", "COS": "command", "DS": "command", "CCX": "command",
    "TD": "command", "PROTOCOL": "command", "CCP": "command",
    "JA": "support", "SJA": "support", "PA": "support", "IG": "support", "HO": "support", "SG": "support",
    "HC": "support", "EO": "support", "SARC": "support", "MED": "support",
}

DEFAULT_FN_KEYWORDS = {
    "command": "commander, vice commander, deputy commander, chief of staff, senior enlisted leader, command chief, "
               "executive officer, exec, aide-de-camp, protocol, commander's action group, commander action group, "
               "front office, executive assistant, speechwriter, technical director",
    "ops": "operations, current ops, future ops, space control, space operator, space operations, pnt, navwar, "
           "missile warning, opir, space domain awareness, sda, ssa, electronic warfare, battle captain, "
           "battle watch, watch officer, tasker, fires, effects, orbital warfare, operator",
    "intel": "intelligence, intel, analyst, all-source, isr, threat, collection, targeting, special security, sso, "
             "foreign disclosure, fdo, counterintelligence, security manager, geoint",
    "cyber": "communications, comm, comms, cyber, satcom, network, client systems, spectrum, comsec, knowledge manag, "
             "it specialist, sipr, nipr, information systems, frequency, ciso, cybersecurity, radio, vtc",
    "plans": "plans, planner, strategy, oplan, conplan, campaign, security cooperation, engagement, partnership, "
             "policy, annex, posture, requirements",
    "exercises": "exercise, training, msel, wargame, war game, tabletop, ttx, rehearsal",
    "personnel": "personnel, manpower, awards, decorations, evaluation, epb, opb, orders, commander's support, admin, "
                 "pcs, in-processing, force support, css",
    "logistics": "logistics, supply, vehicle, facilities, transportation, equipment, property, maintenance, "
                 "deployment, mobility, readiness",
    "resources": "resources, resource advisor, budget, finance, financial, fm analyst, gpc, government purchase, "
                 "comptroller, funds, dts",
    "support": "legal, judge advocate, paralegal, public affairs, media, inspector general, historian, chaplain, "
               "medical, flight surgeon, equal opportunity",
}

# AFSC / career-field prefixes (longest prefix wins).
CAREER_PREFIX = [
    ("13S", "ops"), ("1C6", "ops"), ("13N", "ops"), ("1C3", "ops"), ("1C1", "ops"), ("11", "ops"), ("12", "ops"),
    ("14N", "intel"), ("1N", "intel"), ("71S", "intel"),
    ("17", "cyber"), ("1D7", "cyber"), ("3D", "cyber"), ("1B4", "cyber"), ("5C0", "cyber"),
    ("3F", "personnel"), ("38F", "personnel"),
    ("6F", "resources"), ("65F", "resources"), ("62E", "resources"), ("63A", "resources"),
    ("2G", "logistics"), ("2S", "logistics"), ("2T", "logistics"), ("21", "logistics"), ("64P", "logistics"),
    ("51J", "support"), ("5J", "support"), ("35P", "support"), ("3N", "support"), ("4", "support"),
    ("16P", "plans"), ("16R", "plans"),
]
AFSC_RE = re.compile(r"\b(\d{1,2}[A-Z]\d[A-Z0-9]?|[A-Z]\d[A-Z]\d)\b")

# ---------------------------------------------------------------- ranks
# key: lowercase abbreviation with spaces/dots removed → (grade, services or None=any)
_AF = ("USSF", "USAF", "DAF", "ANG", "AFR")
_ARMY = ("USA", "USARMY", "ARNG", "USAR")
_NAVY = ("USN", "USCG", "USNR")
_MC = ("USMC", "USMCR")
RANKS = {
    # USSF / USAF enlisted
    "spc1": [("E-1", None)], "spc2": [("E-2", None)], "spc3": [("E-3", None)], "spc4": [("E-4", None)],
    "ab": [("E-1", None)], "amn": [("E-2", None)], "a1c": [("E-3", None)], "sra": [("E-4", None)],
    "sgt": [("E-5", None)], "ssgt": [("E-6", _MC), ("E-5", None)], "tsgt": [("E-6", None)],
    "msgt": [("E-8", _MC), ("E-7", None)], "smsgt": [("E-8", None)], "cmsgt": [("E-9", None)],
    "cmssf": [("E-9", None)], "cmsaf": [("E-9", None)],
    # officers (DAF / USMC share)
    "2dlt": [("O-1", None)], "2ndlt": [("O-1", None)], "1stlt": [("O-2", None)],
    "capt": [("O-6", _NAVY), ("O-3", None)], "maj": [("O-4", None)],
    "ltcol": [("O-5", None)], "col": [("O-6", None)], "briggen": [("O-7", None)], "bgen": [("O-7", None)],
    "majgen": [("O-8", None)], "ltgen": [("O-9", None)], "gen": [("O-10", None)],
    # Army
    "pvt": [("E-1", None)], "pv2": [("E-2", None)], "pfc": [("E-3", None)], "spc": [("E-4", None)],
    "cpl": [("E-4", None)], "ssg": [("E-6", None)], "sfc": [("E-7", None)], "msg": [("E-8", None)],
    "1sg": [("E-8", None)], "sgm": [("E-9", None)], "csm": [("E-9", None)], "sma": [("E-9", None)],
    "wo1": [("W-1", None)], "cw2": [("W-2", None)], "cw3": [("W-3", None)], "cw4": [("W-4", None)], "cw5": [("W-5", None)],
    "cwo2": [("W-2", None)], "cwo3": [("W-3", None)], "cwo4": [("W-4", None)], "cwo5": [("W-5", None)],
    "2lt": [("O-1", None)], "1lt": [("O-2", None)], "cpt": [("O-3", None)], "ltc": [("O-5", None)],
    "bg": [("O-7", None)], "mg": [("O-8", None)], "ltg": [("O-9", None)],
    # Navy / USCG
    "sr": [("E-1", None)], "sa": [("E-2", None)], "sn": [("E-3", None)], "po3": [("E-4", None)],
    "po2": [("E-5", None)], "po1": [("E-6", None)], "cpo": [("E-7", None)], "scpo": [("E-8", None)],
    "mcpo": [("E-9", None)], "ens": [("O-1", None)], "ltjg": [("O-2", None)], "lt": [("O-3", _NAVY + _ARMY), ("O-2", None)],
    "lcdr": [("O-4", None)], "cdr": [("O-5", None)], "rdml": [("O-7", None)], "radm": [("O-8", None)],
    "vadm": [("O-9", None)], "adm": [("O-10", None)],
    # USMC
    "lcpl": [("E-3", None)], "gysgt": [("E-7", None)], "1stsgt": [("E-8", None)], "mgysgt": [("E-9", None)],
    "sgtmaj": [("E-9", None)],
    # civilians / contractors
    "ses": [("SES", None)], "st": [("ST", None)], "sl": [("SL", None)],
    "civ": [("CIV", None)], "ctr": [("CTR", None)], "ct": [("CTR", None)], "contractor": [("CTR", None)],
}
# Multi-word ranks as they appear in DAF display names.
RANK_PHRASES = ["lt col", "1st lt", "2nd lt", "2d lt", "brig gen", "maj gen", "lt gen"]
CIV_GRADE_RE = re.compile(r"^(GS|GG|GM|WG|WS|WL|NF|NH|DB|DE|DJ|DK|YA|YB|YC|YD|YE|YF|YG|YH|YI|YJ|YK|YL|YN|YP)-?(\d{1,2}|I{1,3}|IV|V)$", re.I)

SERVICES = {
    "USSF": "Space Force", "USAF": "Air Force", "DAF": "Dept of the Air Force", "ANG": "Air National Guard",
    "AFR": "Air Force Reserve", "USA": "Army", "USARMY": "Army", "ARNG": "Army National Guard", "USAR": "Army Reserve",
    "USN": "Navy", "USNR": "Navy Reserve", "USMC": "Marine Corps", "USMCR": "Marine Corps Reserve", "USCG": "Coast Guard",
    "JASDF": "JASDF", "JGSDF": "JGSDF", "JMSDF": "JMSDF", "ROKA": "ROK Army", "ROKAF": "ROKAF", "ROKN": "ROK Navy",
    "RAAF": "RAAF", "RAN": "RAN", "ADF": "ADF", "RNZAF": "RNZAF", "NZDF": "NZDF", "RAF": "RAF", "RCAF": "RCAF",
    "CAF": "Canadian Armed Forces", "BAF": "Bundeswehr", "PAF": "PAF",
}
FOREIGN = {"JASDF", "JGSDF", "JMSDF", "ROKA", "ROKAF", "ROKN", "RAAF", "RAN", "ADF", "RNZAF", "NZDF", "RAF", "RCAF", "CAF", "BAF", "PAF"}


def grade_level(grade: str) -> float:
    """Comparable seniority: E-n → n, W-n → 10+n, O-n → 20+n, civilians mapped to equivalents."""
    if not grade:
        return 0
    m = re.match(r"^([EWO])-(\d+)$", grade)
    if m:
        return {"E": 0, "W": 10, "O": 20}[m.group(1)] + int(m.group(2))
    m = re.match(r"^(GS|GG|GM)-(\d+)$", grade)
    if m:
        n = int(m.group(2))
        return 26 if n >= 15 else (n + 11 if n >= 9 else n)
    m = re.match(r"^NH-(\d+|I{1,3}|IV)$", grade)
    if m:
        v = m.group(1)
        n = {"I": 1, "II": 2, "III": 3, "IV": 4}.get(v) or int(v)
        return {1: 12, 2: 21, 3: 23.5, 4: 25.5}.get(n, 21)
    m = re.match(r"^(WG|WS|WL)-(\d+)$", grade)
    if m:
        return min(9, int(m.group(2)) / 2)
    if grade in ("SES", "ST", "SL"):
        return 28
    if grade == "CTR":
        return 0.5
    return 0


TIERS = [
    ("flag", "General / flag & SES", 27, 99),
    ("field", "Field grade (O-4–O-6)", 24, 27),
    ("company", "Company grade (O-1–O-3)", 21, 24),
    ("warrant", "Warrant", 11, 16),
    ("snco", "Senior NCO (E-7–E-9)", 7, 10),
    ("nco", "NCO (E-4–E-6)", 4, 7),
    ("junior", "Junior enlisted", 1, 4),
]


def tier_of(level: float, category: str) -> str:
    if category == "civ":
        return "flag" if level >= 27 else ("civ-senior" if level >= 24 else "civ")
    if category == "ctr":
        return "ctr"
    for tid, _, lo, hi in TIERS:
        if lo <= level < hi:
            return tid
    return ""


TIER_LABEL = {t[0]: t[1] for t in TIERS} | {"civ-senior": "Senior civilian (GS-13+)", "civ": "Civilian", "ctr": "Contractor"}

# ---------------------------------------------------------------- object kinds
KINDS = [
    ("person", "People"),
    ("orgbox", "Org accounts"),
    ("group", "Distribution lists"),
    ("resource", "Rooms & equipment"),
    ("contact", "External contacts"),
]
KIND_LABEL = dict(KINDS)

# msExchRecipientTypeDetails values
RTD = {
    1: "person", 2: "person", 2147483648: "person",              # User / Linked / RemoteUser
    4: "orgbox", 34359738368: "orgbox",                         # Shared / RemoteShared
    16: "resource", 32: "resource", 8589934592: "resource", 17179869184: "resource",
    64: "contact", 128: "contact",                              # MailContact / MailUser
    256: "group", 512: "group", 1024: "group", 2048: "group", 8: "group",
}
RTD_NAMES = {
    "usermailbox": "person", "linkedmailbox": "person", "remoteusermailbox": "person",
    "sharedmailbox": "orgbox", "remotesharedmailbox": "orgbox",
    "roommailbox": "resource", "equipmentmailbox": "resource", "remoteroommailbox": "resource",
    "remoteequipmentmailbox": "resource",
    "mailcontact": "contact", "mailuser": "contact", "guestmailuser": "contact",
    "mailuniversaldistributiongroup": "group", "mailuniversalsecuritygroup": "group",
    "dynamicdistributiongroup": "group", "mailnonuniversalgroup": "group", "group": "group",
    "user": "person", "contact": "contact", "inetorgperson": "person",
}
# Leaf-OU names that say what an object is.
OU_KIND_HINTS = [
    (re.compile(r"org(anizational)?\s*(accounts?|mail\s*boxes|boxes)|shared\s*mail|functional|workflow", re.I), "orgbox"),
    (re.compile(r"distribution|\bdls?\b|groups?$|mail\s*groups?", re.I), "group"),
    (re.compile(r"resources?|rooms?|conference|equipment|vtc", re.I), "resource"),
    (re.compile(r"contacts?$|external", re.I), "contact"),
    (re.compile(r"service\s*accounts?|computers?|servers?|admin\s*accounts?|privileged", re.I), "service"),
]
# Display-name hints for org accounts / DLs when nothing better exists.
NAME_KIND_HINTS = [
    (re.compile(r"\b(org\s*box|org\s*mailbox|organizational|workflow|functional|mailbox|inbox|helpdesk|help desk|"
                r"front office|orderly room|ops center|ops floor|watch|command post|support desk)\b", re.I), "orgbox"),
    (re.compile(r"\b(dl|distro|distribution|all personnel|all hands|mailing list)\b", re.I), "group"),
    (re.compile(r"\b(conf(erence)? ?(rm|room)|room \w+|vtc|scif|equipment)\b", re.I), "resource"),
]

# ---------------------------------------------------------------- leadership
LEADER_TITLE = [
    (re.compile(r"^(?!.*\b(deputy|vice|support|action|staff|exec)\b).*\b(commander|cc)\b", re.I), 100),
    (re.compile(r"\bcommand chief|senior enlisted (leader|advisor)|\bsel\b", re.I), 86),
    (re.compile(r"\bchief of staff\b", re.I), 88),
    (re.compile(r"\b(director|dir)\b", re.I), 90),
    (re.compile(r"\btechnical director\b", re.I), 84),
    (re.compile(r"\bvice commander|deputy commander\b", re.I), 92),
    (re.compile(r"\bdeputy\b", re.I), 72),
    (re.compile(r"\b(division|branch|section|flight) chief|\bchief\b(?! of staff)", re.I), 78),
    (re.compile(r"\bsuperintendent|\bsupt\b", re.I), 70),
    (re.compile(r"\b(forward|site|team|det(achment)?) (lead|commander|chief)|\blead\b", re.I), 66),
    (re.compile(r"\b(oic|officer in charge)\b", re.I), 68),
    (re.compile(r"\b(ncoic|nco in charge)\b", re.I), 60),
    (re.compile(r"\b(executive officer|xo)\b", re.I), 30),
]


SUPPORT_ROLE = re.compile(r"\b(assistant|asst|aide|admin(istrator|istrative)?|clerk|secretary|support|scheduler)\b", re.I)


def leader_score(title: str) -> int:
    best = 0
    for rx, s in LEADER_TITLE:
        if rx.search(title or ""):
            best = max(best, s)
    # "Command Chief Executive Assistant", "Director's Admin Support" — near a leader, not one
    if best and SUPPORT_ROLE.search(title or ""):
        best = min(best, 25)
    return best


# ---------------------------------------------------------------- routing topics
def _t(tid, label, aliases, fns, codes, terms, countries=()):
    return {"id": tid, "label": label, "aliases": aliases, "fns": fns, "codes": codes,
            "terms": terms, "countries": list(countries)}


_ANNEX = [
    ("A", "Task organization", ["command", "plans"], ["S5", "J5", "A5"], ["task org", "plans"]),
    ("B", "Intelligence", ["intel"], ["S2", "J2", "A2"], ["intelligence"]),
    ("C", "Operations", ["ops"], ["S3", "J3", "A3"], ["operations"]),
    ("D", "Logistics", ["logistics"], ["S4", "J4", "A4"], ["logistics"]),
    ("E", "Personnel", ["personnel"], ["S1", "J1", "A1"], ["personnel"]),
    ("F", "Public affairs", ["support"], ["PA"], ["public affairs"]),
    ("H", "METOC", ["ops"], ["S3", "A3"], ["weather", "metoc"]),
    ("J", "Command relationships", ["command", "plans"], ["S5", "CAG"], ["plans", "command relationships"]),
    ("K", "Communications", ["cyber"], ["S6", "J6", "A6"], ["communications", "satcom", "spectrum"]),
    ("M", "Geospatial", ["intel"], ["S2", "J2"], ["geospatial", "geoint"]),
    ("N", "Space operations", ["plans", "ops"], ["S5", "S3", "J5", "J3"], ["space operations", "planner", "annex n", "space planner"]),
    ("P", "Host-nation support", ["logistics", "plans"], ["S4", "S5"], ["host nation", "security cooperation"]),
    ("Q", "Medical", ["support"], ["SG"], ["medical"]),
    ("R", "Reports", ["ops"], ["S3"], ["reports", "current operations"]),
    ("V", "Interagency", ["plans"], ["S5"], ["interagency", "engagement"]),
    ("W", "Contingency contracting", ["logistics", "resources"], ["S4", "S8"], ["contracting"]),
]

DEFAULT_TOPICS = [
    _t("satcom", "SATCOM", ["satcom", "wgs", "muos", "ehf", "aehf", "milsatcom", "satellite communication", "commercial satcom"],
       ["cyber", "ops"], ["S6", "J6", "A6"], ["satcom", "satellite communications", "spectrum"]),
    _t("pnt", "PNT / GPS / NAVWAR", ["pnt", "gps", "navwar", "gnss", "jamming", "spoofing"], ["ops"], ["S3", "J3", "A3"],
       ["pnt", "navwar", "gps", "space control"]),
    _t("ew", "EW / EMI / spectrum", ["ew", "emi", "electromagnetic", "electronic warfare", "interference", "spectrum", "frequency"],
       ["ops", "cyber"], ["S3", "S6"], ["electronic warfare", "spectrum", "emi"]),
    _t("sda", "Space domain awareness", ["sda", "ssa", "space domain awareness", "space situational awareness", "conjunction", "orbital"],
       ["ops", "intel"], ["S3", "S2"], ["space domain awareness", "sda", "ssa"]),
    _t("mw", "Missile warning", ["missile warning", "opir", "sbirs", "launch detection"], ["ops"], ["S3"], ["missile warning", "opir"]),
    _t("spacecontrol", "Space control / effects", ["space control", "counterspace", "effects", "fires", "targeting", "orbital warfare"],
       ["ops", "intel"], ["S3", "S2"], ["space control", "effects", "targeting", "fires"]),
    _t("intel", "Intelligence support", ["intel", "intelligence", "threat brief", "rfi", "isr", "threat"], ["intel"], ["S2", "J2", "A2"],
       ["intelligence", "analyst", "threat"]),
    _t("fdo", "Foreign disclosure", ["foreign disclosure", "fdo", "releasable", "releasability", "rel to", "fvey", "noforn"],
       ["intel"], ["S2", "J2"], ["foreign disclosure", "fdo"]),
    _t("security", "Security / clearances", ["clearance", "security manager", "diss", "visit request", "sci", "read-in", "indoc", "sso", "badge"],
       ["intel"], ["S2", "IP"], ["security manager", "special security", "sso", "security"]),
    _t("opsec", "OPSEC", ["opsec"], ["ops", "intel"], ["S3", "S2"], ["opsec"]),
    _t("it", "IT / accounts / helpdesk", ["sipr", "nipr", "account", "cac", "pki", "email", "teams", "computer", "laptop", "ticket",
                                          "printer", "network", "vtc", "helpdesk", "help desk"],
       ["cyber"], ["S6", "SC", "A6"], ["client systems", "network", "it specialist", "helpdesk", "help desk", "knowledge manag", "vtc"]),
    _t("comsec", "COMSEC / crypto", ["comsec", "crypto", "key material", "ekms"], ["cyber"], ["S6", "SC"], ["comsec"]),
    _t("cyberdef", "Cyber defense / CISO", ["cyber", "ciso", "rmf", "ato", "cybersecurity", "vulnerability", "dco"],
       ["cyber"], ["S6", "A6"], ["cyber", "ciso", "cybersecurity", "defensive cyber"]),
    _t("km", "Knowledge management / SharePoint", ["sharepoint", "knowledge management", "battle rhythm", "km"],
       ["cyber", "command"], ["S6", "CAG"], ["knowledge manag", "battle rhythm"]),
    _t("tasker", "Taskers / suspenses", ["tasker", "tasking", "suspense", "etms", "task management"], ["ops", "command"],
       ["S3", "CAG", "CCX"], ["tasker", "task management", "current operations"]),
    _t("oplan", "OPLAN / CONPLAN planning", ["oplan", "conplan", "opord", "campaign plan", "jopes", "tpfdd"], ["plans"],
       ["S5", "J5", "A5"], ["planner", "oplan", "campaign", "strategy"]),
    _t("secco", "Security cooperation / partners", ["security cooperation", "partner", "partnership", "engagement", "allies",
                                                     "bilateral", "key leader engagement", "kle", "liaison"],
       ["plans", "command"], ["S5", "J5", "A5"], ["security cooperation", "engagement", "partnership", "liaison"]),
    _t("exercise", "Exercises (general)", ["exercise", "wargame", "war game", "msel", "training event"], ["exercises", "ops"],
       ["S7", "S36", "S3"], ["exercise", "msel", "training"]),
    _t("awards", "Awards & decorations", ["award", "awards", "decoration", "medal", "quarterly awards", "annual awards"],
       ["personnel"], ["S1", "A1", "CSS"], ["awards", "decorations"]),
    _t("evals", "Evaluations (EPB/OPB)", ["epb", "opb", "evaluation", "eval", "oer", "ncoer", "fitrep"], ["personnel"],
       ["S1", "A1", "CSS"], ["evaluation", "personnel"]),
    _t("orders", "Orders / PCS / leave", ["pcs", "orders", "leave", "in-processing", "out-processing", "inprocessing",
                                         "outprocessing", "sponsor"],
       ["personnel"], ["S1", "A1", "CSS"], ["orders", "personnel", "commander's support"]),
    _t("travel", "Travel / DTS", ["dts", "travel", "tdy", "voucher", "per diem"], ["resources", "personnel"], ["S8", "S1"],
       ["dts", "travel", "orders"]),
    _t("budget", "Budget / funding", ["budget", "funding", "funds", "money", "unfunded", "pom", "spend plan", "comptroller", "fm"],
       ["resources"], ["S8", "A8", "FM"], ["budget", "resources", "financial", "fm analyst"]),
    _t("gpc", "Purchases / GPC", ["gpc", "government purchase card", "purchase", "buy"], ["resources", "logistics"], ["S8", "S4"],
       ["gpc", "purchase", "supply"]),
    _t("manpower", "Manpower / UMD", ["manpower", "umd", "billet", "position number"], ["resources", "personnel"], ["S8", "S1", "A1"],
       ["manpower", "requirements"]),
    _t("supply", "Supply / equipment", ["supply", "equipment", "furniture", "property", "hand receipt", "custodian"],
       ["logistics"], ["S4", "A4"], ["supply", "property", "equipment", "logistics"]),
    _t("vehicles", "Vehicles / transportation", ["vehicle", "car", "transportation", "motor pool"], ["logistics"], ["S4"],
       ["vehicle", "transportation"]),
    _t("facilities", "Facilities / building", ["facility", "facilities", "building", "office space", "work order", "keys"],
       ["logistics"], ["S4"], ["facilities", "logistics"]),
    _t("deploy", "Deployments / mobility", ["deployment", "deploy", "mobility", "utc"], ["logistics", "personnel"], ["S4", "S1"],
       ["deployment", "mobility", "readiness"]),
    _t("legal", "Legal", ["legal", "jag", "ethics", "gift", "law", "roe", "rules of engagement", "lawyer"], ["support"],
       ["JA", "SJA"], ["judge advocate", "legal", "paralegal"]),
    _t("pa", "Public affairs / media", ["media", "press", "public affairs", "social media", "photo", "release"], ["support"],
       ["PA"], ["public affairs"]),
    _t("protocol", "Protocol / DV visits", ["protocol", "dv", "distinguished visitor", "ceremony", "change of command", "coin"],
       ["command"], ["CAG", "CCP", "CC"], ["protocol", "commander action group", "executive"]),
    _t("cmdgroup", "Commander's calendar / front office", ["front office", "calendar", "boss", "exec", "action group", "commander"],
       ["command"], ["CAG", "CC", "CCE"], ["executive officer", "executive assistant", "commander action group", "commander's action"]),
    *[_t(f"annex-{L.lower()}", f"Annex {L} — {label}", [f"annex {L.lower()}", f"appendix {L.lower()}"], fns, codes, terms)
      for L, label, fns, codes, terms in _ANNEX],
]
