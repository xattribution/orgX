"""SQLite schema + connection helpers. Two files:

  data/org.db          rebuilt by every ingest (objects, orgs, locations, members)
                       plus history carried forward (snapshots, events)
  data/annotations.db  team notes, tags, "go-to for" topics, saved lists —
                       never touched by ingest, so it survives every rebuild
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 2       # bump when a directory built by an older version needs upgrade() before use

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
  manager_key TEXT, org_lft INTEGER, org_root TEXT
);
CREATE TABLE stage_members (group_key TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS ou_stats (depth INTEGER, value TEXT, n INTEGER, cities TEXT, PRIMARY KEY (depth, value));
CREATE TABLE members (group_id INTEGER, member_id INTEGER, PRIMARY KEY (group_id, member_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS object_fns (fn TEXT, object_id INTEGER, PRIMARY KEY (fn, object_id)) WITHOUT ROWID;
CREATE TABLE orgs (
  id TEXT PRIMARY KEY, name TEXT, parent TEXT, depth INTEGER, kind TEXT, fn TEXT,
  direct INTEGER, total INTEGER, people INTEGER, leader_key TEXT, leader_by TEXT,
  loc_id TEXT, locs INTEGER, inferred TEXT, lft INTEGER, rgt INTEGER, sort INTEGER, site TEXT, root TEXT
);
CREATE TABLE locations (
  id TEXT PRIMARY KEY, name TEXT, full TEXT, lat REAL, lon REAL, tz TEXT, country TEXT, state TEXT,
  region TEXT, approx INTEGER, ou TEXT, total INTEGER, people INTEGER
);
"""

# Each index serves a query the UI makes on every visit; the covering ones let SQLite answer
# counts and group-bys from the index alone instead of visiting a million rows.
INDEXES = """
CREATE INDEX IF NOT EXISTS ob_kind ON objects(kind, sort_name);
CREATE INDEX IF NOT EXISTS ob_org ON objects(org_lft, kind, category, tier, fn, loc_id);
CREATE INDEX IF NOT EXISTS ob_orgid ON objects(org_id, kind);
CREATE INDEX IF NOT EXISTS ob_root ON objects(org_root, kind);
CREATE INDEX IF NOT EXISTS ob_loc ON objects(loc_id, kind, fn, category, org_id);
CREATE INDEX IF NOT EXISTS ob_kfn ON objects(kind, fn);
CREATE INDEX IF NOT EXISTS ob_facet ON objects(kind, category, tier, fn, region, loc_id, org_root, level, org_lft, country, fns);
CREATE INDEX IF NOT EXISTS ob_ktier ON objects(kind, tier);
CREATE INDEX IF NOT EXISTS ob_senior ON objects(kind, level DESC, leader DESC, sort_name);
CREATE INDEX IF NOT EXISTS ob_leader ON objects(kind, leader) WHERE leader > 0;
CREATE INDEX IF NOT EXISTS ob_smart ON objects(CASE kind WHEN 'person' THEN 0 WHEN 'orgbox' THEN 1 WHEN 'group' THEN 2 ELSE 3 END,
  org_lft, leader DESC, level DESC, sort_name);
CREATE INDEX IF NOT EXISTS ob_level ON objects(level);
CREATE INDEX IF NOT EXISTS ob_email ON objects(email COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ob_dn ON objects(dn COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ob_mgr ON objects(manager_key);
CREATE INDEX IF NOT EXISTS ob_region ON objects(region);
CREATE INDEX IF NOT EXISTS ob_country ON objects(country);
CREATE INDEX IF NOT EXISTS ob_digits ON objects(phone_digits);
CREATE INDEX IF NOT EXISTS org_parent ON orgs(parent, sort);
CREATE INDEX IF NOT EXISTS org_lft ON orgs(lft);
CREATE INDEX IF NOT EXISTS mem_member ON members(member_id);
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


def tune(conn: sqlite3.Connection) -> None:
    """Read settings for a large directory: map the file instead of copying pages through a 2 MB
    cache, keep sorts in memory."""
    conn.execute("PRAGMA mmap_size = 4294967296")
    conn.execute("PRAGMA cache_size = -131072")
    conn.execute("PRAGMA temp_store = MEMORY")


def connect(data_dir: Path, readonly: bool = True) -> sqlite3.Connection | None:
    db = data_dir / "org.db"
    if not db.exists():
        return None
    uri = f"file:{db}?mode=ro" if readonly else str(db)
    conn = sqlite3.connect(uri, uri=readonly, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    tune(conn)
    ann = data_dir / "annotations.db"
    init_annotations(data_dir)
    conn.execute("ATTACH DATABASE ? AS ann", (str(ann),))
    return conn


def identity(path: Path) -> tuple:
    """Changes when the file is replaced (a new ingest) or written (on-the-fly lookups, notes)."""
    try:
        st = path.stat()
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return ()


class Pool:
    """Open read connections kept between requests, so each one starts with a warm page cache and
    parsed schema. A connection belongs to one file: when an ingest replaces org.db, connections
    to the old file are closed as they come back (and drain() closes idle ones before the swap,
    which Windows needs before it will replace an open file)."""

    def __init__(self, data_dir: Path, size: int = 8):
        self.data_dir = data_dir
        self.size = size
        self.idle: list[tuple[int, sqlite3.Connection]] = []
        self.lock = threading.Lock()

    def _ino(self) -> int:
        try:
            return (self.data_dir / "org.db").stat().st_ino
        except OSError:
            return -1

    def get(self) -> tuple[int, sqlite3.Connection] | None:
        ino = self._ino()
        with self.lock:
            while self.idle:
                i, c = self.idle.pop()
                if i == ino:
                    return i, c
                c.close()
        c = connect(self.data_dir)
        return (ino, c) if c else None

    def put(self, item: tuple[int, sqlite3.Connection]) -> None:
        ino, c = item
        with self.lock:
            if ino == self._ino() and len(self.idle) < self.size:
                self.idle.append(item)
                return
        c.close()

    def drain(self) -> None:
        with self.lock:
            for _, c in self.idle:
                c.close()
            self.idle.clear()


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
