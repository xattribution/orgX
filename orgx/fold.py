"""Spellings of one unit that drifted apart in a hand-kept directory, folded back together.

The first segment of a Department (the unit) is typed by many hands, so one unit shows up as
"MERIDIAN GROUP", "MERIDIAN-GROUP", "USMERIDIAN-GROUP" and "AU USSF MERIDIAN GROUP". Two roots are
folded into one when

  1. they differ only in case, spacing and punctuation, or
  2. one is the other behind country or service tags ("US", "AU USSF", or "US" glued on), and the
     bare name exists as a unit of its own.

Within a group the spelling most people use is kept. Anything less certain, such as a one-letter
difference, is only suggested. Rules win over both: orgAliases maps a spelling explicitly and
orgSeparate keeps one apart.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import geo
from . import reference as ref

TAGS = set(geo.ISO2) | {"USA", "UK", "GBR", "AUS", "CAN", "NZL", "JPN", "KOR", "ROK", "DEU", "FRA", "ITA"} | set(ref.SERVICES)
MIN_KEY = 8          # bare names shorter than this ("COMMAND") are too generic to match on


def key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def bare(root: str) -> str:
    """The name behind leading country/service tags, or "" if there are none."""
    toks = [t for t in re.split(r"[\s_]+", root.strip()) if t]
    i = 0
    while i < len(toks) - 1 and toks[i].upper().strip(".") in TAGS:
        i += 1
    if i:
        return " ".join(toks[i:])
    if root[:2].upper() == "US" and len(key(root)) >= MIN_KEY + 2 and not root[2:3].isspace():
        return root[2:]
    return ""


def plan(counts: Counter, separate=(), aliases=None) -> list[dict]:
    """counts: unit root as written → records. Returns one entry per spelling that is folded:
    {"from", "into", "n", "why"}."""
    aliases = {k.upper() for k in (aliases or {})}
    keep = {key(s) for s in separate}
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for root, n in counts.items():
        if root and root.upper() not in aliases:
            groups[key(root)].append((root, n))
    # spelling kept for each group: most records, then the one with separators as typed, then shortest
    canon = {k: max(v, key=lambda t: (t[1], bool(re.search(r"[\s\-]", t[0])), -len(t[0])))[0] for k, v in groups.items() if k}
    out = []
    for k, members in groups.items():
        if not k:
            continue
        target, why = canon[k], "spelling"
        b = key(bare(canon[k]))
        if len(b) >= MIN_KEY and b != k and b in canon and k not in keep:
            target, why = canon[b], "prefix"
        for root, n in members:
            if root != target and key(root) not in keep:
                out.append({"from": root, "into": target, "n": n, "why": why})
    return out


def mapping(folds: list[dict]) -> dict[str, str]:
    return {f["from"]: f["into"] for f in folds}


def suggest(counts: Counter, folded: dict[str, str], limit: int = 40) -> list[dict]:
    """Roots one character apart (typos, a dropped letter), for a person to confirm. Uses
    single-deletion keys, so it is linear in the number of roots."""
    roots = {}
    for root, n in counts.items():
        if not root or root in folded:
            continue
        k = key(root)
        if len(k) >= 8:
            roots.setdefault(k, (root, 0))
            roots[k] = (roots[k][0], roots[k][1] + n)
    dels: dict[str, set[str]] = defaultdict(set)
    for k in roots:
        dels[k].add(k)
        for i in range(len(k)):
            dels[k[:i] + k[i + 1:]].add(k)
    pairs = set()
    for ks in dels.values():
        if 1 < len(ks) <= 4:
            ks = sorted(ks)
            for i, a in enumerate(ks):
                for b in ks[i + 1:]:
                    if re.sub(r"\d", "", a) == re.sub(r"\d", "", b):
                        continue        # numbered sister units (GROUP 2 / GROUP 3) are different units
                    pairs.add((a, b))
    out = []
    for a, b in pairs:
        (ra, na), (rb, nb) = roots[a], roots[b]
        big, small = ((ra, na), (rb, nb)) if na >= nb else ((rb, nb), (ra, na))
        out.append({"from": small[0], "into": big[0], "n": small[1], "into_n": big[1]})
    out.sort(key=lambda s: -s["n"])
    return out[:limit]
