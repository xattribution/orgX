#!/usr/bin/env python3
"""Ingest an AD / GAL CSV export into data/org.db.

    python3 ingest.py export.csv                 # one snapshot
    python3 ingest.py jan.csv feb.csv mar.csv    # several, oldest first → change history
    python3 ingest.py --data /srv/orgx export.csv
    python3 ingest.py --selftest

Each run rebuilds the directory from the CSV, diffs it against the previous
build (joined / departed / moved / promoted / retitled / relocated / contact)
and keeps that history. Team notes and lists live in annotations.db and are
never touched. A running server picks up the new database on its next request.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv", nargs="*", type=Path)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--as-of", help="snapshot date YYYY-MM-DD (default: date in the file name, else today)")
    ap.add_argument("--selftest", action="store_true", help="run the unit tests")
    a = ap.parse_args()
    if a.selftest:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        sys.exit(0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1)
    if not a.csv:
        ap.error("give at least one CSV (or --selftest)")
    from orgx.ingest import ingest
    a.data.mkdir(parents=True, exist_ok=True)
    for f in a.csv:
        if not f.exists():
            sys.exit(f"CSV not found: {f}")
        ingest(f, a.data, as_of=a.as_of if len(a.csv) == 1 else None)


if __name__ == "__main__":
    main()
