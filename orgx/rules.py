"""User-editable rules (data/rules.json) merged over built-in defaults."""
from __future__ import annotations

import json
from pathlib import Path

from . import reference as ref

DEFAULTS = {
    # OU names that sit directly above <region>/<site>; empty = learn the site level from the data
    "anchors": [],
    # raw text → site name from data/sites.json (e.g. "North Campus": "Alder")
    "baseAliases": {},
    # first org segment rewrites (e.g. "ATLAS CMD": "ATLAS COMMAND")
    "orgAliases": {},
    # fold drifted spellings of one unit ("X", "X-Y", "USX", "AU USSF X"); orgSeparate keeps a spelling apart
    "foldSpellings": True,
    "orgSeparate": [],
    # explicit org parents: "HARBOR COMM SQ": "HARBOR SUPPORT GROUP"
    "orgParents": {},
    # org code → function where the default (by staff digit) is wrong for you: {"S36": "exercises"}
    "codeFunctions": {},
    # per-function keyword overrides (comma-separated); missing → built-in
    "fnKeywords": {},
    # extra routing topics, same shape as reference.DEFAULT_TOPICS
    "topics": [],
    # direct AD sync (Windows host with PowerShell): see orgx/adsync.py
    # server "" = the signed-in user's own domain; mode "export" (scheduled full export) or "live" (on the fly)
    "ad": {"server": "", "bases": [], "method": "Auto", "members": True, "hours": 0, "mode": "export", "liveHours": 12},
    "inferFromManagers": True,   # parent a top-level org under the unit its people report to
    "nestOfficeSymbols": True,   # SCOO under SCO under SC when those exist
    "skipDisabled": True,
    "skipHidden": False,
    "skipKinds": ["service"],
}


def path(data_dir: Path) -> Path:
    return data_dir / "rules.json"


def load(data_dir: Path) -> dict:
    out = json.loads(json.dumps(DEFAULTS))
    p = path(data_dir)
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            for k, v in user.items():
                if k in out:
                    out[k] = v
        except (OSError, ValueError):
            pass
    return out


def save(data_dir: Path, rules: dict) -> dict:
    clean = {k: rules[k] for k in DEFAULTS if k in rules}
    path(data_dir).write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return load(data_dir)


def fn_keywords(rules: dict) -> dict[str, list[str]]:
    src = dict(ref.DEFAULT_FN_KEYWORDS)
    src.update({k: v for k, v in (rules.get("fnKeywords") or {}).items() if k in src and isinstance(v, str)})
    return {fn: [w.strip().lower() for w in s.split(",") if w.strip()] for fn, s in src.items()}


def topics(rules: dict) -> list[dict]:
    user = [t for t in (rules.get("topics") or []) if isinstance(t, dict) and t.get("label")]
    for i, t in enumerate(user):
        t.setdefault("id", f"user-{i}")
        for k in ("aliases", "fns", "codes", "terms", "countries"):
            t.setdefault(k, [])
        t["user"] = True
    return user + ref.DEFAULT_TOPICS
