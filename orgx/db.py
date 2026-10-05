"""SQLite schema + connection helpers. Two files:

  data/org.db          rebuilt by every ingest (objects, orgs, locations, members)
                       plus history carried forward (snapshots, events)
  data/annotations.db  team notes, tags, "go-to for" topics, saved lists —
                       never touched by ingest, so it survives every rebuild
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

OBJECT_COLS = [
    "key", "kind", "display", "name", "sort_name", "first", "last", "mi", "rank", "grade", "level",
    "service", "category", "tier", "title", "org_id", "dept", "office", "phone", "dsn", "mobile",
    "phone_digits", "email", "upn", "sam", "loc_id", "region", "country", "ou_path", "dn", "domain",
    "career", "fn", "fns", "leader", "manager_dn", "disabled", "hidden", "created", "changed",
    "description", "extra",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY, taken_at TEXT, source TEXT, rows INTEGER, objects INTEGER, people INTEGER,
  orgs INTEGER, locations INTEGER, parsed_names INTEGER, unplaced INTEGER, skipped INTEGER,
  sha TEXT, columns TEXT, seconds REAL, as_of TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, snap INTEGER, key TEXT, kind TEXT, type TEXT, name TEXT,
  before TEXT, after TEXT, org_id TEXT, loc_id TEXT, level REAL
);
CREATE INDEX IF NOT EXISTS ev_snap ON events(snap, type);
CREATE INDEX IF NOT EXISTS ev_key ON events(key);

CREATE TABLE objects (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE, kind TEXT, display TEXT, name TEXT, sort_name TEXT, first TEXT, last TEXT, mi TEXT,
  rank TEXT, grade TEXT, level REAL, service TEXT, category TEXT, tier TEXT, title TEXT,
  org_id TEXT, dept TEXT, office TEXT, phone TEXT, dsn TEXT, mobile TEXT, phone_digits TEXT,
  email TEXT, upn TEXT, sam TEXT, loc_id TEXT, region TEXT, country TEXT, ou_path TEXT, dn TEXT,
  domain TEXT, career TEXT, fn TEXT, fns TEXT, leader INTEGER, manager_dn TEXT, disabled INTEGER,
  hidden INTEGER, created TEXT, changed TEXT, description TEXT, extra TEXT,
  manager_key TEXT, org_lft INTEGER
);
CREATE TABLE stage_members (group_key TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS ou_stats (depth INTEGER, value TEXT, n INTEGER, cities TEXT, PRIMARY KEY (depth, value));
CREATE TABLE members (group_id INTEGER, member_id INTEGER, PRIMARY KEY (group_id, member_id)) WITHOUT ROWID;
CREATE TABLE orgs (
  id TEXT PRIMARY KEY, name TEXT, parent TEXT, depth INTEGER, kind TEXT, fn TEXT,
  direct INTEGER, total INTEGER, people INTEGER, leader_key TEXT, leader_by TEXT,
  loc_id TEXT, locs INTEGER, inferred TEXT, lft INTEGER, rgt INTEGER, sort INTEGER, site TEXT
);
CREATE TABLE locations (
  id TEXT PRIMARY KEY, name TEXT, full TEXT, lat REAL, lon REAL, tz TEXT, country TEXT, state TEXT,
  region TEXT, approx INTEGER, ou TEXT, total INTEGER, people INTEGER
);
"""

INDEXES = """
CREATE INDEX ob_kind ON objects(kind, sort_name);
CREATE INDEX ob_org ON objects(org_lft);
CREATE INDEX ob_orgid ON objects(org_id);
CREATE INDEX ob_loc ON objects(loc_id);
CREATE INDEX ob_fn ON objects(fn);
CREATE INDEX ob_level ON objects(level);
CREATE INDEX ob_email ON objects(email);
CREATE INDEX ob_dn ON objects(dn);
CREATE INDEX ob_mgr ON objects(manager_key);
CREATE INDEX ob_region ON objects(region);
CREATE INDEX ob_country ON objects(country);
CREATE INDEX ob_digits ON objects(phone_digits);
CREATE INDEX org_parent ON orgs(parent, sort);
CREATE INDEX org_lft ON orgs(lft);
CREATE INDEX mem_member ON members(member_id);
"""

FTS = """
CREATE VIRTUAL TABLE objects_fts USING fts5(
  name, display, title, dept, office, email, career, loc_id, description, ou_path,
  content='objects', content_rowid='id', tokenize='unicode61 remove_diacritics 2',
  prefix='2 3'
);
INSERT INTO objects_fts(objects_fts) VALUES('rebuild');
"""

ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS notes (
  key TEXT PRIMARY KEY, notes TEXT DEFAULT '', tags TEXT DEFAULT '[]', contact_for TEXT DEFAULT '[]',
  updated_at TEXT, updated_by TEXT
);
CREATE TABLE IF NOT EXISTS lists (
  id INTEGER PRIMARY KEY, name TEXT, description TEXT DEFAULT '', kind TEXT DEFAULT 'static',
  query TEXT DEFAULT '', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS list_members (
  list_id INTEGER, key TEXT, name TEXT, added_at TEXT, PRIMARY KEY (list_id, key)
);
"""


def has_fts5() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def connect(data_dir: Path, readonly: bool = True) -> sqlite3.Connection | None:
    db = data_dir / "org.db"
    if not db.exists():
        return None
    uri = f"file:{db}?mode=ro" if readonly else str(db)
    conn = sqlite3.connect(uri, uri=readonly, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ann = data_dir / "annotations.db"
    init_annotations(data_dir)
    conn.execute("ATTACH DATABASE ? AS ann", (str(ann),))
    return conn


# Columns added after the first release; migrated in place (lists became shareable groups).
MIGRATIONS = {
    "lists": [("uid", "TEXT"), ("purpose", "TEXT DEFAULT 'team'"), ("starts", "TEXT DEFAULT ''"),
              ("ends", "TEXT DEFAULT ''"), ("place", "TEXT DEFAULT ''"), ("links", "TEXT DEFAULT '[]'"),
              ("created_by", "TEXT DEFAULT ''"), ("origin", "TEXT DEFAULT ''")],
    "list_members": [("role", "TEXT DEFAULT ''"), ("section", "TEXT DEFAULT ''"), ("external", "INTEGER DEFAULT 0"),
                     ("email", "TEXT DEFAULT ''"), ("phone", "TEXT DEFAULT ''"), ("rank", "TEXT DEFAULT ''"),
                     ("title", "TEXT DEFAULT ''"), ("org", "TEXT DEFAULT ''"), ("note", "TEXT DEFAULT ''"),
                     ("sort", "INTEGER DEFAULT 0")],
}
_migrated: set[str] = set()


def init_annotations(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = str(data_dir / "annotations.db")
    if path in _migrated and (data_dir / "annotations.db").exists():
        return
    c = sqlite3.connect(path)
    c.executescript(ANNOTATIONS)
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    c.execute("UPDATE lists SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL OR uid = ''")
    c.commit()
    c.close()
    _migrated.add(path)


def annotations(data_dir: Path) -> sqlite3.Connection:
    init_annotations(data_dir)
    c = sqlite3.connect(data_dir / "annotations.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c
