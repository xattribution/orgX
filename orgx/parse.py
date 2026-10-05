"""Row-level parsing: column mapping, DAF display names, DNs/OUs, kinds, functions."""
from __future__ import annotations

import re

from . import reference as ref

# ---------------------------------------------------------------- columns
# canonical field → accepted headers (case/space/underscore-insensitive).
COLUMNS = {
    "display": ["DisplayName", "Name", "cn", "FullName", "Full Name"],
    "first": ["GivenName", "FirstName", "First Name"],
    "last": ["Surname", "sn", "LastName", "Last Name"],
    "initials": ["Initials", "MiddleName", "MiddleInitial"],
    "title": ["Title", "JobTitle", "Job Title"],
    "rank": ["Rank", "Grade", "PayGrade", "personalTitle"],
    "department": ["Department", "DepartmentName"],
    "company": ["Company"],
    "office": ["Office", "physicalDeliveryOfficeName", "OfficeLocation", "OfficeName"],
    "phone": ["Phone", "telephoneNumber", "OfficePhone", "BusinessPhone", "Business Phone"],
    "dsn": ["DSN", "ipPhone", "DSNPhone"],
    "mobile": ["MobilePhone", "mobile", "Mobile"],
    "email": ["WindowsEmailAddress", "PrimarySmtpAddress", "Email", "mail", "EmailAddress", "E-mail Address", "EmailAddresses"],
    "upn": ["UserPrincipalName"],
    "sam": ["SamAccountName", "sAMAccountName", "Alias", "mailNickname"],
    "city": ["City", "l"],
    "state": ["StateOrProvince", "st", "State"],
    "country": ["CountryOrRegion", "co", "Country", "c"],
    "street": ["StreetAddress", "street"],
    "dn": ["DistinguishedName", "DN"],
    "ou": ["OrganizationalUnit", "OU", "ParentOU", "CanonicalName"],
    "manager": ["Manager"],
    "members": ["Members", "member"],
    "memberof": ["MemberOf"],
    "managedby": ["ManagedBy"],
    "guid": ["ObjectGUID", "Guid", "ExternalDirectoryObjectId"],
    "employee_id": ["EmployeeID", "EDIPI", "employeeNumber"],
    "rtd": ["RecipientTypeDetails", "msExchRecipientTypeDetails", "RecipientType"],
    "object_class": ["ObjectClass"],
    "career": ["CareerField", "AFSC", "DutyAFSC"],
    "enabled": ["Enabled"],
    "uac": ["userAccountControl"],
    "hidden": ["HiddenFromAddressListsEnabled", "msExchHideFromAddressLists"],
    "created": ["WhenCreated"],
    "changed": ["WhenChanged"],
    "description": ["Description", "Notes", "info"],
}
_NORM = re.compile(r"[\s_\-]")


def map_columns(header: list[str]) -> dict[str, str]:
    """canonical → actual header. First alias wins; unknown headers are kept as extras."""
    lookup = {_NORM.sub("", h).lower(): h for h in header}
    out = {}
    for field, aliases in COLUMNS.items():
        for a in aliases:
            h = lookup.get(_NORM.sub("", a).lower())
            if h:
                out[field] = h
                break
    return out


def clean(v) -> str:
    if v is None:
        return ""
    v = str(v).strip()
    return "" if v.lower() in ("null", "none", "n/a", "-") else v


# ---------------------------------------------------------------- names
_SUFFIX = {"JR", "SR", "II", "III", "IV", "V"}
_FILLER = {"HQ", "DAF"}


def _rank_key(tok: str) -> str:
    return tok.lower().replace(".", "").replace(" ", "")


def resolve_rank(token: str, service: str = "") -> tuple[str, str]:
    """('Lt Col', 'USSF') → ('Lt Col', 'O-5'). Returns ('', '') if not a rank."""
    t = token.strip()
    if not t:
        return "", ""
    m = ref.CIV_GRADE_RE.match(t.replace(" ", ""))
    if m:
        plan, step = m.group(1).upper(), m.group(2).upper()
        step = step.zfill(2) if step.isdigit() else step
        return f"{plan}-{step}", f"{plan}-{int(step) if step.isdigit() else step}"
    opts = ref.RANKS.get(_rank_key(t))
    if not opts:
        return "", ""
    svc = service.upper()
    for grade, services in opts:
        if services is None or svc in services:
            return t, grade
    return t, opts[-1][0]


def smart_case(s: str) -> str:
    """'MCDONALD-O'BRIEN' → 'McDonald-O'Brien'. Leaves mixed-case input alone."""
    if not s or not s.isupper():
        return s
    out = re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), s.lower())
    out = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    return re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(1).upper(), out)


def parse_display(display: str) -> dict:
    """DAF GAL: 'LAST, FIRST M RANK [SERVICE] [HQ DAF] [ORG/PATH]' — tolerant of most variants."""
    out = {"last": "", "first": "", "mi": "", "rank": "", "grade": "", "service": "", "org": "", "country_tag": ""}
    d = (display or "").strip()
    if not d:
        return out
    m = re.search(r"\s*\(([A-Z]{2,3})\)\s*$", d)
    if m:
        out["country_tag"] = m.group(1)
        d = d[: m.start()]
    if "," not in d:
        return out
    last, rest = d.split(",", 1)
    out["last"] = last.strip()
    toks = rest.split()
    if not toks:
        return out
    out["first"] = toks[0]
    i = 1
    # middle initials / suffixes before the rank
    while i < len(toks):
        t = toks[i].rstrip(".")
        if len(t) == 1 and t.isalpha():
            out["mi"] = (out["mi"] + t).upper()
            i += 1
        elif t.upper() in _SUFFIX:
            out["last"] += " " + t.upper()
            i += 1
        else:
            break
    # service may appear before or after rank; peek ahead for it to disambiguate CAPT/LT
    ahead = {t.upper() for t in toks[i:i + 4]}
    svc_hint = next((s for s in ref.SERVICES if s in ahead), "")
    # rank (try two-token phrases first)
    if i < len(toks):
        two = " ".join(toks[i:i + 2]).lower()
        if two in ref.RANK_PHRASES and i + 1 < len(toks):
            out["rank"], out["grade"] = resolve_rank(" ".join(toks[i:i + 2]), svc_hint)
            i += 2
        else:
            r, g = resolve_rank(toks[i], svc_hint)
            if r:
                out["rank"], out["grade"] = r, g
                i += 1
    # no rank: an org account written "SHOP, FRONT OFFICE USSF ORG" — skip ahead to the service token
    if not out["rank"]:
        j = next((k for k in range(i, min(i + 5, len(toks))) if toks[k].upper() in ref.SERVICES), None)
        if j is not None:
            i = j
    # services / filler
    while i < len(toks) and (toks[i].upper() in ref.SERVICES or toks[i].upper() in _FILLER):
        u = toks[i].upper()
        if u in ref.SERVICES and u != "DAF" and not out["service"]:
            out["service"] = u
        elif u == "DAF" and not out["service"] and (i == 0 or toks[i - 1].upper() != "HQ"):
            out["service"] = "DAF"
        i += 1
    out["org"] = " ".join(toks[i:]).strip()
    return out


# ---------------------------------------------------------------- DN / OU
def split_dn(dn: str) -> list[tuple[str, str]]:
    """'CN=DOE\\, JANE,OU=Users,DC=x' → [('CN','DOE, JANE'), ('OU','Users'), ('DC','x')]."""
    parts, buf, esc = [], [], False
    for ch in dn:
        if esc:
            buf.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    out = []
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out.append((k.strip().upper(), v.strip()))
    return out


def ou_path(dn: str = "", ou: str = "") -> tuple[list[str], str]:
    """Return (OUs root→leaf, domain). Accepts a DN or a canonical 'domain/OU/OU[/CN]' path."""
    if dn and "=" in dn:
        parts = split_dn(dn)
        ous = [v for k, v in parts if k == "OU"][::-1]
        dom = ".".join(v for k, v in parts if k == "DC")
        return ous, dom
    src = ou or dn
    if src and "=" in src:
        return ou_path(src)
    if src and "/" in src:
        segs = [s for s in src.split("/") if s]
        dom = segs[0] if "." in segs[0] else ""
        segs = segs[1:] if dom else segs
        return segs, dom
    return [], ""


def ou_kind(ous: list[str]) -> str:
    for o in reversed(ous[-2:]):
        for rx, kind in ref.OU_KIND_HINTS:
            if rx.search(o):
                return kind
    return ""


# ---------------------------------------------------------------- kind
def classify_kind(row: dict, parsed: dict, ous: list[str]) -> str:
    rtd = clean(row.get("rtd"))
    if rtd:
        if rtd.isdigit():
            k = ref.RTD.get(int(rtd))
            if k:
                return k
        else:
            k = ref.RTD_NAMES.get(rtd.lower().replace(" ", ""))
            if k:
                return k
    oc = clean(row.get("object_class")).lower()
    if "group" in oc:
        return "group"
    if oc == "contact":
        return "contact"
    if clean(row.get("members")):
        return "group"
    k = ou_kind(ous)
    if k:
        return k
    if parsed.get("rank") or (clean(row.get("first")) and clean(row.get("last"))):
        return "person"
    name = clean(row.get("display"))
    for rx, kind in ref.NAME_KIND_HINTS:
        if rx.search(name):
            return kind
    if parsed.get("last") and parsed.get("first"):
        return "person"
    return "orgbox" if name else "person"


# ---------------------------------------------------------------- orgs
_SVC_PREFIX = re.compile(r"^(?:(?:USSF|USAF|DAF|USA|USN|USMC)\s+)+(?:HQ\s+DAF\s+)?", re.I)


def org_path(department: str, parsed_org: str, company: str = "") -> list[str]:
    raw = department or parsed_org or ""
    raw = _SVC_PREFIX.sub("", raw.strip())
    raw = re.sub(r"^HQ\s+DAF\s+", "", raw, flags=re.I)
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"\s*[/\\>]\s*", raw) if p.strip()]
    return [p for p in parts if p.upper() not in ("USSF", "USAF", "DAF", "HQ DAF", "UNKNOWN")]


STAFF_RE = re.compile(r"^([SJAGNC])(\d{1,2})(\d*)([A-Z]*)$")
OFFICE_PREFIX = {"SC": "cyber", "DO": "ops", "OS": "ops", "IN": "intel", "FM": "resources", "LG": "logistics",
                 "LR": "logistics", "XP": "plans", "DP": "personnel", "FS": "personnel", "TR": "exercises"}


CODE_OVERRIDES: dict[str, str] = {}   # from rules.codeFunctions, e.g. {"S36": "exercises"}


def code_function(code: str) -> str:
    c = code.upper().replace(" ", "")
    if c in CODE_OVERRIDES:
        return CODE_OVERRIDES[c]
    if c in ref.SPECIAL_CODES:
        return ref.SPECIAL_CODES[c]
    m = STAFF_RE.match(c)
    if m:
        d = m.group(2)
        if d == "10":
            return "ops"
        return ref.STAFF_DIGIT.get(d[0], "")
    if c.startswith(("FWD", "LNO")):
        return ""
    if 2 <= len(c) <= 6 and c.isalpha():
        if c[:2] in ref.SPECIAL_CODES:
            return ref.SPECIAL_CODES[c[:2]]
        return OFFICE_PREFIX.get(c[:2], "")
    return ""


def org_kind(name: str) -> str:
    u = name.upper()
    if re.match(r"^(FWD|LNO|OL|DET)[-\s]", u) or u.startswith(("FWD", "LNO")):
        return "forward"
    if STAFF_RE.match(u.replace(" ", "")) or u in ref.SPECIAL_CODES:
        return "staff"
    if re.match(r"^\d+\s?[A-Z]{1,6}$", u) or re.search(r"\b(WING|GROUP|SQUADRON|DELTA|GARRISON|SQ|WG|GP)\b", u):
        return "unit"
    if 2 <= len(u) <= 6 and u.isalpha():
        return "office"
    return "unit"


def career_function(career: str) -> str:
    c = (career or "").upper()
    best, blen = "", 0
    for pre, fn in ref.CAREER_PREFIX:
        if c.startswith(pre) and len(pre) > blen:
            best, blen = fn, len(pre)
    return best


def classify_functions(title: str, path: list[str], career: str, keywords: dict[str, list[str]]) -> list[str]:
    score: dict[str, float] = {}
    for depth, seg in enumerate(path):
        fn = code_function(seg)
        if fn:
            score[fn] = score.get(fn, 0) + (1.5 + depth)   # deeper org codes are more specific
    t = f" {(title or '').lower()} "
    for fn, words in keywords.items():
        hits = 0
        for w in words:
            if not w:
                continue
            if (len(w) <= 4 and re.search(rf"\b{re.escape(w)}\b", t)) or (len(w) > 4 and w in t):
                hits += 1
        if hits:
            score[fn] = score.get(fn, 0) + 2 * min(hits, 2)
    cf = career_function(career)
    if cf:
        score[cf] = score.get(cf, 0) + 1.5
    return [fn for fn, s in sorted(score.items(), key=lambda kv: -kv[1]) if s >= 1.5]


# ---------------------------------------------------------------- misc
def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def is_disabled(row: dict) -> bool:
    en = clean(row.get("enabled")).lower()
    if en in ("false", "0", "no"):
        return True
    uac = clean(row.get("uac"))
    if uac.isdigit() and int(uac) & 2:
        return True
    return False


def is_hidden(row: dict) -> bool:
    return clean(row.get("hidden")).lower() in ("true", "1", "yes")


def split_multi(v: str) -> list[str]:
    """Split a multi-valued AD export cell. DNs contain commas, so prefer ';' / '|' / newlines."""
    v = clean(v)
    if not v:
        return []
    if any(sep in v for sep in (";", "|", "\n")):
        parts = re.split(r"[;|\n]", v)
    elif "=" in v and v.count("CN=") > 1:
        parts = re.split(r",(?=CN=)", v)
    else:
        parts = [v]
    return [p.strip() for p in parts if p.strip()]
