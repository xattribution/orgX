"""Location resolution, learned from the data.

ORGX ships no list of real sites or OU layouts. Where people sit is worked out from what
ingest sees:
  1. the site OU level, found by `OuLearner`: the OU depth whose values cover most objects,
     are not container names (Users, Groups…), and each map to one city
  2. an optional local site list (data/sites.json, never in the repository) with exact
     coordinates and aliases, matched against the site OU, Office and City
  3. otherwise an approximate pin at the state / country centroid of the City fields
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ISO2 = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium", "BG": "Bulgaria", "BR": "Brazil",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "FI": "Finland",
    "FR": "France", "GB": "United Kingdom", "GR": "Greece", "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia",
    "IE": "Ireland", "IL": "Israel", "IN": "India", "IS": "Iceland", "IT": "Italy", "JP": "Japan", "KE": "Kenya",
    "KR": "South Korea", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MA": "Morocco", "MX": "Mexico",
    "MY": "Malaysia", "NG": "Nigeria", "NL": "Netherlands", "NO": "Norway", "NZ": "New Zealand", "PE": "Peru",
    "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SA": "Saudi Arabia", "SE": "Sweden",
    "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia", "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan",
    "UA": "Ukraine", "AE": "United Arab Emirates", "US": "United States of America", "VN": "Vietnam",
    "ZA": "South Africa",
}
COUNTRY_ALIAS = {
    "united states": "US", "usa": "US", "u.s.": "US", "america": "US", "korea, republic of": "KR",
    "republic of korea": "KR", "korea": "KR", "uk": "GB", "great britain": "GB", "england": "GB",
    "britain": "GB", "deutschland": "DE", "turkiye": "TR", "türkiye": "TR", "uae": "AE", "holland": "NL",
}
US_STATES = {
    "AL": (32.8, -86.8), "AK": (64.0, -150.0), "AZ": (34.2, -111.6), "AR": (34.9, -92.4), "CA": (37.2, -119.5),
    "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5), "DC": (38.9, -77.0), "FL": (28.6, -82.4),
    "GA": (32.7, -83.4), "HI": (21.3, -157.9), "ID": (44.4, -114.6), "IL": (40.0, -89.2), "IN": (39.9, -86.3),
    "IA": (42.1, -93.5), "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.1, -92.0), "ME": (45.4, -69.2),
    "MD": (39.0, -76.8), "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7),
    "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8), "NV": (39.3, -116.6), "NH": (43.7, -71.6),
    "NJ": (40.2, -74.7), "NM": (34.4, -106.1), "NY": (42.9, -75.5), "NC": (35.6, -79.4), "ND": (47.5, -100.5),
    "OH": (40.3, -82.8), "OK": (35.6, -97.5), "OR": (43.9, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.5),
    "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3), "UT": (39.3, -111.7),
    "VT": (44.1, -72.7), "VA": (37.5, -78.9), "WA": (47.4, -120.5), "WV": (38.6, -80.6), "WI": (44.6, -89.9),
    "WY": (43.0, -107.6), "GU": (13.45, 144.79), "PR": (18.2, -66.5),
}
STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "guam": "GU",
}
# US state → IANA zone (approximate; most-populous zone wins)
STATE_TZ = {
    "HI": "Pacific/Honolulu", "AK": "America/Anchorage", "CA": "America/Los_Angeles", "WA": "America/Los_Angeles",
    "OR": "America/Los_Angeles", "NV": "America/Los_Angeles", "AZ": "America/Phoenix", "CO": "America/Denver",
    "UT": "America/Denver", "NM": "America/Denver", "MT": "America/Denver", "WY": "America/Denver",
    "ID": "America/Boise", "TX": "America/Chicago", "OK": "America/Chicago", "KS": "America/Chicago",
    "NE": "America/Chicago", "SD": "America/Chicago", "ND": "America/Chicago", "MN": "America/Chicago",
    "IA": "America/Chicago", "MO": "America/Chicago", "AR": "America/Chicago", "LA": "America/Chicago",
    "MS": "America/Chicago", "AL": "America/Chicago", "IL": "America/Chicago", "WI": "America/Chicago",
    "TN": "America/Chicago", "GU": "Pacific/Guam", "PR": "America/Puerto_Rico",
}
COUNTRY_TZ = {
    "AR": "America/Argentina/Buenos_Aires", "AT": "Europe/Vienna", "AU": "Australia/Sydney", "BE": "Europe/Brussels",
    "BG": "Europe/Sofia", "BR": "America/Sao_Paulo", "CA": "America/Toronto", "CH": "Europe/Zurich",
    "CL": "America/Santiago", "CN": "Asia/Shanghai", "CO": "America/Bogota", "CZ": "Europe/Prague",
    "DE": "Europe/Berlin", "DK": "Europe/Copenhagen", "EE": "Europe/Tallinn", "EG": "Africa/Cairo",
    "ES": "Europe/Madrid", "FI": "Europe/Helsinki", "FR": "Europe/Paris", "GB": "Europe/London",
    "GR": "Europe/Athens", "HR": "Europe/Zagreb", "HU": "Europe/Budapest", "ID": "Asia/Jakarta",
    "IE": "Europe/Dublin", "IL": "Asia/Jerusalem", "IN": "Asia/Kolkata", "IS": "Atlantic/Reykjavik",
    "IT": "Europe/Rome", "JP": "Asia/Tokyo", "KE": "Africa/Nairobi", "KR": "Asia/Seoul", "LT": "Europe/Vilnius",
    "LU": "Europe/Luxembourg", "LV": "Europe/Riga", "MA": "Africa/Casablanca", "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur", "NG": "Africa/Lagos", "NL": "Europe/Amsterdam", "NO": "Europe/Oslo",
    "NZ": "Pacific/Auckland", "PE": "America/Lima", "PH": "Asia/Manila", "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon", "RO": "Europe/Bucharest", "SA": "Asia/Riyadh", "SE": "Europe/Stockholm",
    "SG": "Asia/Singapore", "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "TH": "Asia/Bangkok",
    "TR": "Europe/Istanbul", "TW": "Asia/Taipei", "UA": "Europe/Kyiv", "AE": "Asia/Dubai", "VN": "Asia/Ho_Chi_Minh",
    "ZA": "Africa/Johannesburg",
}

# generic words that decorate a site name ("Alder Site", "Alder Users"); more can be added in Rules
_STRIP = re.compile(r"\b(users?|accounts?|personnel|people|staff|site|campus|office|building|location)\b")


def core(name: str) -> str:
    s = (name or "").lower().replace("–", "-")
    s = re.sub(r"[.'’()]", "", s)
    s = s.replace("-", " ")
    s = _STRIP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def country_code(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if len(v) == 2 and v.upper() in ISO2:
        return v.upper()
    low = v.lower()
    if low in COUNTRY_ALIAS:
        return COUNTRY_ALIAS[low]
    for code, name in ISO2.items():
        if name.lower() == low:
            return code
    return ""


def state_code(v: str) -> str:
    v = (v or "").strip()
    if len(v) == 2 and v.upper() in US_STATES:
        return v.upper()
    return STATE_NAMES.get(v.lower(), "")


CONTAINER = re.compile(r"^(users?|people|personnel|accounts?|groups?|distribution( lists?)?|dls?|resources?|rooms?|"
                       r"contacts?|computers?|servers?|service accounts?|shared mailboxes|mail ?boxes|org(anizational)? "
                       r"(accounts?|boxes)|disabled|archive|staging|test)$", re.I)


class OuLearner:
    """Finds which OU depth holds sites (and the one above it, regions) from the objects seen.

    Bounded memory: per depth it keeps a count per value and up to three cities per value."""
    MAX_DEPTH = 6

    def __init__(self):
        self.total = 0
        self.vals = [dict() for _ in range(self.MAX_DEPTH)]     # depth -> value -> [count, {city: n}]

    def add(self, ous: list[str], city: str = "") -> None:
        self.total += 1
        c = (city or "").strip().lower()
        for d, v in enumerate(ous[: self.MAX_DEPTH]):
            e = self.vals[d].get(v)
            if e is None:
                if len(self.vals[d]) >= 5000:
                    continue
                e = self.vals[d][v] = [0, {}]
            e[0] += 1
            if c and (c in e[1] or len(e[1]) < 3):
                e[1][c] = e[1].get(c, 0) + 1

    def result(self) -> dict:
        """{'site': depth or None, 'region': depth or None}"""
        best, best_score = None, 0.0
        for d, vals in enumerate(self.vals):
            n = sum(e[0] for e in vals.values())
            if len(vals) < 2 or not self.total or n / self.total < 0.4:
                continue
            boxes = sum(e[0] for v, e in vals.items() if CONTAINER.match(v.strip()))
            if boxes / n > 0.5 or len(vals) > max(2, n / 4):
                continue
            with_city = [e for e in vals.values() if e[1]]
            if with_city:
                consistent = sum(max(e[1].values()) for e in with_city) / max(1, sum(sum(e[1].values()) for e in with_city))
            else:
                consistent = 0.6
            score = (n / self.total) * consistent * (1 + min(len(vals), 50) / 100)
            if score > best_score:
                best, best_score = d, score
        region = None
        if best:
            up = self.vals[best - 1]
            boxes = sum(e[0] for v, e in up.items() if CONTAINER.match(v.strip()))
            total_up = sum(e[0] for e in up.values())
            real = [v for v in up if not CONTAINER.match(v.strip())]
            if 2 <= len(real) < len(self.vals[best]) and boxes / max(1, total_up) < 0.2:
                region = best - 1
        return {"site": best, "region": region}

    def to_rows(self):
        for d, vals in enumerate(self.vals):
            for v, (n, cities) in vals.items():
                yield d, v, n, json.dumps(cities)

    @classmethod
    def from_rows(cls, total: int, rows):
        lr = cls()
        lr.total = total
        for d, v, n, cities in rows:
            if d < cls.MAX_DEPTH:
                lr.vals[d][v] = [n, json.loads(cities or "{}")]
        return lr


def load_sites(data_dir: Path) -> list[dict]:
    """Optional local site list: data/sites.json ({"sites": [...]}), or an older data/bases.json."""
    for name, key in (("sites.json", "sites"), ("bases.json", "bases")):
        p = data_dir / name
        if p.exists():
            try:
                return list(json.loads(p.read_text(encoding="utf-8")).get(key) or [])
            except (OSError, ValueError):
                return []
    return []


class Gazetteer:
    def __init__(self, data_dir: Path, extra_aliases: dict | None = None, levels: dict | None = None):
        self.bases = {b["name"]: b for b in load_sites(data_dir) if b.get("name")}
        self.levels = levels or {"site": None, "region": None}
        cpath = data_dir / "centroids.json"
        self.centroids = json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}
        self.exact: dict[str, str] = {}
        phrases: list[tuple[str, str]] = []
        for b in self.bases.values():
            for n in [b["name"], b.get("full", "")] + list(b.get("aliases", [])):
                if not n:
                    continue
                c = core(n)
                if c:
                    self.exact.setdefault(c, b["name"])
                if len(n) >= 4:
                    phrases.append((n.lower(), b["name"]))
        for raw, base in (extra_aliases or {}).items():
            if base in self.bases:
                self.exact[core(raw)] = base
                phrases.append((raw.lower(), base))
        phrases.sort(key=lambda p: -len(p[0]))
        self.phrase_map = dict(phrases)
        self.phrase_re = re.compile(r"\b(" + "|".join(re.escape(p) for p, _ in phrases) + r")\b") if phrases else None

    def match_exact(self, name: str) -> str:
        return self.exact.get(core(name), "")

    def match_text(self, text: str) -> str:
        if not text or not self.phrase_re:
            return ""
        m = self.phrase_re.search(text.lower())
        return self.phrase_map.get(m.group(1), "") if m else ""

    def installation_ou(self, ous: list[str], anchors: list[str]) -> tuple[str, str]:
        """(region OU, site OU): anchor OUs named in Rules win; otherwise the learned levels."""
        low = [o.lower() for o in ous]
        for a in anchors or []:
            if a.lower() in low:
                i = low.index(a.lower())
                region = ous[i + 1] if i + 1 < len(ous) else ""
                inst = ous[i + 2] if i + 2 < len(ous) else ""
                return region, inst
        site, reg = self.levels.get("site"), self.levels.get("region")
        if site is None or len(ous) <= site or CONTAINER.match(ous[site]):
            return "", ""
        return (ous[reg] if reg is not None and len(ous) > reg else ""), ous[site]

    def place(self, ous: list[str], anchors: list[str], office: str, city: str, state: str, country: str) -> dict:
        region, inst = self.installation_ou(ous, anchors)
        base = self.match_exact(inst) if inst else ""
        if not base:
            for o in reversed(ous):
                base = self.match_exact(o)
                if base:
                    break
        if not base:
            base = self.match_text(office) or self.match_text(city)
        cc = country_code(country)
        st = state_code(state)
        if base:
            b = self.bases[base]
            return {"id": base, "name": base, "full": b.get("full", base), "lat": b["lat"], "lon": b["lon"],
                    "tz": b.get("tz", ""), "country": b.get("country", cc), "state": b.get("state", st),
                    "region": region, "approx": 0, "ou": inst}
        # unknown installation / city → approximate
        label = inst or (city.strip().title() if city else "")
        if not label:
            label = ISO2.get(cc, country) if (cc or country) else ""
        if not label:
            return {"id": "", "name": "", "full": "", "lat": None, "lon": None, "tz": "", "country": cc,
                    "state": st, "region": region, "approx": 1, "ou": ""}
        lat = lon = None
        if st and (cc in ("", "US")):
            lat, lon = US_STATES[st]
            cc = cc or "US"
        elif cc and ISO2.get(cc) in self.centroids:
            lat, lon = self.centroids[ISO2[cc]]
        tz = STATE_TZ.get(st, "America/New_York" if st else COUNTRY_TZ.get(cc, ""))
        suffix = st or cc
        lid = f"ou:{inst}" if inst else f"geo:{label}{', ' + suffix if suffix else ''}"
        return {"id": lid, "name": label, "full": f"{label}{', ' + suffix if suffix and not inst else ''}",
                "lat": lat, "lon": lon, "tz": tz, "country": cc, "state": st, "region": region,
                "approx": 1, "ou": inst}
