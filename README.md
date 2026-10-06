# ORGX — Directory Explorer

A self-hosted explorer for a whole Active Directory / GAL. People, org mailboxes,
distribution lists and rooms are all first-class objects. It answers three
questions quickly:

1. **Who is this, and where do they sit?** Rank, title, unit, chain, base, local time.
2. **Who do I contact for X?** Ask in plain words: *"who handles SATCOM at Alder?"*
3. **What changed?** Arrivals, departures, moves, promotions and new titles between exports.

It also does the work around those questions: exercise and team **groups** you can share as
a file, **email lists** sized for mail relays, a **DTG clock** with ACP 121 zone letters,
a cross-site **meeting planner**, and printable **recall rosters**.

One container, Python standard library + SQLite (FTS5), no pip installs, no
external calls. The data never leaves the server.

```
PowerShell (AD) ──► CSV ──► inbox/ or upload ──► ingest ──► org.db ──► server.py ──► browser
                                                    │                     ▲
                                                    └── history (events) ─┘   annotations.db (team notes, groups)
```

## Run it

```bash
docker compose up -d            # http://localhost:48750
```

or without Docker (Python 3.10+):

```bash
python3 server.py               # http://127.0.0.1:48750
python3 server.py --host 0.0.0.0 --port 48750 --data /srv/orgx
```

The first visit opens **Data → Sources**. Drop an export there, or click
**Load synthetic demo data** to try every view. Fictional names; emails use a
`.example` domain. **Reset directory** clears the demo data again and keeps notes and groups.

| Env (Docker) | Default | |
|---|---|---|
| `ORGX_PORT` | `48750` | |
| `ORGX_DATA` | `/data` | database, notes, rules, `inbox/`, `sources/` |
| `ORGX_INBOX_SECONDS` | `20` | inbox poll interval; `0` disables |
| `ORGX_UPLOAD` | `1` | `0` = no browser uploads (inbox / CLI only) |
| `ORGX_DEMO` | `0` | `1` = seed demo data when the database is empty |
| `ORGX_WHOAMI` | `local` | `any` = answer *Who am I* for remote clients too (only when the server process runs as a meaningful identity) |
| `ORGX_USER` | unset | force the identity *Who am I* reports (UPN, email or DN), for testing or a service account |

## Getting AD data in

### Direct connector (Windows, logged-in user)

Run the server on a domain-joined Windows workstation with Python 3.10+ and open
**Data → Sources → Active Directory**. By default it talks to your own domain (the one you
signed in to); name another domain controller there if you need to.

- **Test connection** binds as you (Kerberos, the same way AD Explorer does), reports
  who it bound as, the method that works, and how many objects the search base holds.
- **Sync now** exports and ingests in one step. Progress appears in the job log. The
  CSV is kept under `sources/` like any upload.
- **Schedule** re-syncs every N hours while the server runs.

The connector runs `tools/Export-ADDirectory.ps1`, which uses **RSAT** (`Get-ADObject`)
when installed and plain **ADSI** (`System.DirectoryServices`) otherwise. ADSI needs no
modules or admin rights. If PowerShell runs in *Constrained Language* mode (common under
AppLocker/WDAC), ADSI is blocked and the script says so. Install RSAT, or run it where
policy allows.

Try it from a terminal first:

```powershell
.\tools\Export-ADDirectory.ps1 -Test        # who am I bound as, which method, object count
.\tools\Export-ADDirectory.ps1 -Server dc01.corp.example -SearchBase "OU=Sites,DC=corp,DC=example" -OutFile .\gal.csv
# nightly, straight into a server's inbox (ingested within a minute, then archived to sources/):
.\tools\Export-ADDirectory.ps1 -Inbox \\fileserver\orgx\data\inbox
```

It pulls every mail-enabled object (users, org boxes, groups, contacts, rooms) with
OU path, manager, membership (ranged, so large DLs are complete) and the Exchange
recipient type. Each object is written to the CSV as it arrives (the directory searcher's
result cache is off), so memory stays flat and the file grows steadily on very large
directories.
`-SearchBase` takes several bases separated by `;`. `-SkipMembers` makes a quick pass.

### On the fly

Set **Mode** to *On the fly* to skip the full export. ORGX then looks things up as you
go and keeps what it finds, so the local directory grows around what you actually use:

- **Search**: the words are resolved the way the Outlook address book does (`anr`), and
  an OU whose name starts with them (a site) brings that OU's objects in.
- **Open a person**: their manager and the manager's manager, their peers, their reports
  and their reports' reports.
- **Open a unit**: everyone whose department is that unit or below it.
- **Open a base**: the site OU it was learned from.

Results land in `data/org.db` with the same normalization as an export, and org trees,
bases and the search index are rebuilt after each lookup. A lookup isn't repeated until
**Look up again after** has passed. Scheduled full syncs pause in this mode; **Sync now**
still runs one.

The server keeps `tools/ADLookup.ps1 -Serve` running and sends it one JSON line per
request (`search`, `dn`, `reports`, `dept`, `ous`, `ou`). Where PowerShell can't read
stdin line by line, it runs the script once per request with `-Request <file>`. Both
scripts share `tools/ADCommon.ps1`. To try the mode without a domain, point
`ORGX_LIVE_CSV` at an export file; lookups are then answered from it.

### Who am I

On the user's own workstation the server process *is* the logged-in user, so
`whoami /fqdn` and `whoami /upn` identify them. This is the same identity `net use` and
AD Explorer present, read with no prompt. ORGX matches it to their directory entry and
offers **Use as me**, which sets *my unit* and *my base* for routing, clocks and
`under:me`. A shared server (Docker, Linux) only answers requests from its own machine,
so it never claims every visitor is the service account. There, people pick themselves
under **My settings**.

### Files

You can also load files from the command line. Several files at once are
ingested oldest first, which builds history:

```bash
python3 ingest.py gal_20260801.csv gal_20260901.csv gal_20261001.csv
```

The snapshot date is taken from a date in the file name (`gal_20260915.csv`,
`…_2026-09-15.csv`), or from `--as-of`, or defaults to today.

### Columns

Headers are matched case- and punctuation-insensitively. Both the Exchange/PowerShell
names and raw LDAP names work. Columns it doesn't recognize are kept and shown
under **All directory attributes**.

| Field | Accepted headers |
|---|---|
| name | `DisplayName`, `GivenName`/`Surname`/`Initials` |
| rank | `Rank`, `personalTitle`, else parsed from the DAF display name |
| org | `Department`, else the org path in the display name |
| location | `DistinguishedName` / `CanonicalName` / `OrganizationalUnit`, `Office`, `City` (`l`), `StateOrProvince` (`st`), `CountryOrRegion` (`co`/`c`) |
| contact | `WindowsEmailAddress`/`PrimarySmtpAddress`/`mail`, `Phone`/`telephoneNumber`, `DSN`/`ipPhone`, `MobilePhone` |
| structure | `Manager`, `Members`/`member`, `MemberOf`, `ManagedBy` (DNs or emails, `;`-separated) |
| type | `RecipientTypeDetails` / `msExchRecipientTypeDetails` (name or number), `ObjectClass` |
| identity | `ObjectGUID` → `EmployeeID` → email → DN (stable key across snapshots) |
| other | `Title`, `Company`, `CareerField`/`AFSC`, `Enabled`/`userAccountControl`, `HiddenFromAddressListsEnabled`, `WhenCreated`, `Description` |

The minimum is `DisplayName` plus `Department`. Every additional column makes
the result richer.

## How it reads the directory

**Display names.** DAF format, `LAST, FIRST M RANK SERVICE [HQ DAF] ORG/PATH`, with
multi-word ranks (`Lt Col`, `Brig Gen`), civilian plans (`GS-13`, `NH-04`, `SES`), `CIV`/`CTR`,
suffixes (`JR`, `III`), country tags (`(USA)`), and service context (`CAPT USN` = O-6,
`Capt USAF` = O-3; `SSgt USMC` = E-6). Every grade maps to a comparable seniority
level, so GS-15 sorts with O-6.

**Object kinds.** `msExchRecipientTypeDetails` is used first: shared mailbox → org account,
room/equipment → resource, distribution/security groups → list, mail contact →
external. Then the leaf OU (`… Organizational Accounts`, `Distribution Lists`, `Resources`),
then the name. Shared and room mailboxes are disabled accounts in AD by design, so
they're kept even with "skip disabled" on. Service accounts are dropped.

**Locations are learned from your directory.** ORGX ships no list of sites and assumes no
OU layout. On every ingest it reads the OU paths once and finds the level that holds sites:
the depth whose values cover most objects, aren't container names (`Users`, `Groups`,
`Resources`…) and each line up with one city. The level above becomes the region. Rules
can pin the level instead. Every OU at the site level is its own place; its coordinates come
from, in order: a matching entry (name or alias) in an optional local `data/sites.json` (your own
coordinates, time zones and aliases; it never leaves your server) → a listed site named in the
OU, `Office` or `City` text, whose coordinates it borrows without merging into it → its state or
country centroid, approximately (dashed on the map and listed under **Quality**).

**Unit spellings.** A unit typed by many hands drifts: `MERIDIAN GROUP`, `MERIDIAN-GROUP`,
`USMERIDIAN-GROUP`, `AU USSF MERIDIAN GROUP`. Before building, ORGX counts how each unit root is
written and files spellings together when they differ only in case, spacing and punctuation,
or when one is the other behind country or service tags and the bare name exists on its own
(bare names under eight letters, such as `COMMAND`, never match). The spelling most people use
is kept. Numbered sister units (`GROUP 2`, `GROUP 3`) stay apart. Spellings one letter apart
are only suggested. **Quality** lists every merge with *Keep separate*, and the suggestions
with *Merge*; both are saved as rules (`orgSeparate`, `orgAliases`) and applied on reload.

**Org tree.** AD `Department` strings don't say who owns whom, so ORGX infers it,
strongest evidence first:

1. explicit rules (`Rules → Org parents`)
2. `Manager` links: a top-level unit whose people report into another unit is placed under it
3. office symbols nest by prefix: `SCOO` under `SCO` under `SC`

Inferred links show as dashed edges and are listed under **Quality**. Each org gets a
**leader** from titles (Commander > Vice/Deputy > Director > Chief > Superintendent > OIC/NCOIC…,
ignoring "Executive Assistant"-type roles), falling back to the most senior member.
Each org also gets a **site unit**: the highest ancestor based at the same place, so a
squadron reads as part of its local wing, not of a distant headquarters.

**Functions** (Command, Ops, Intel, Cyber/Comm, Plans, Exercises, Personnel, Logistics,
Resources, Special staff) come from the org codes (`S6`, `A6X`, `J2`, `SC…`), title keywords
and AFSC prefixes. All three are editable under Rules; an org code can be forced (`S36 → Exercises`).

## Using it

- **People** (the home screen): the org chart in the middle, the unit tree and bases on the
  left, the selected person or unit's card on the right, and the people of the selected unit
  as tiles underneath (this office, or everyone under it). Click a box to move down the chart;
  the path above it is a link back up. Switch the canvas to **Map** to see where people are.
- **Search** (`Ctrl K`, in the header everywhere): names, office symbols, emails, phone
  numbers and bases. Pick a person and the chart moves to their office and lights it up.
  "Show every match as a list" opens a search screen with filters and a **Table** layout for
  bulk work: select rows for an email list, a group, a print roster, CSV or vCards, or save
  the search as a group.
- **Questions**: type "who handles SATCOM at Alder?" in the same box. The answer lists the
  offices that handle it (with their office mailbox and lead) and the people who match, each
  with the reason it matched. Naming a place or unit ranks matches there first.
- **The card**: name and rank, title and office, then the contact strip (email, DSN and
  commercial as large values you click to copy), base and local time, a note when it's
  outside their duty hours with the office mailbox to try instead, the reporting line (from
  `Manager`, or from office leads when AD has none), direct reports and **everyone under**
  them, the office mailbox, the same office, distribution lists, history across snapshots and
  **team notes**. The More menu copies a signature block or downloads a vCard.
- **Clock**: the current DTG (`030134Z OCT 26`) sits in the header; click it for your local time and the bases you choose,
  each with its ACP 121 zone letter worked out from the live UTC offset (so it follows
  daylight saving: US Eastern is R in winter and Q in summer). Half-hour zones show the offset
  instead. A day marker (`-1`) shows when a base is on another date. Pick bases under **Time**.
- **Organization**: lazy tree, overview (leadership, shop mailboxes and DLs, composition by
  category/function/seniority, locations, last-snapshot changes), a pan/zoom chart that
  expands on demand, and a members tab. **Set as my unit** biases routing toward your chain
  and adds an "only my unit" toggle.
- **Map**: world map that wraps east–west (the Pacific isn't split at the date line), clusters
  that split as you zoom, rings showing each site's function mix, a live **day/night** terminator,
  and a ranked list of sites with local time. It takes the same filter language as the directory.
- **Change history** (under Data): pick a snapshot to see joined / departed / moved / promoted / retitled /
  relocated / contact changes, a headcount trend, and net change by unit.
- **Groups**: exercise cells, teams and distros, with STARTEX/ENDEX, place, links, and a
  role and section per member ("Lead planner", "White cell"). Add people by search, from a
  directory selection, or by **pasting an Outlook To: line** (each entry is matched by
  address, then by name; anyone not found is kept as an external contact). Members who
  have left or moved since the last snapshot are flagged. **Share** as a link on the
  same server, or download a `.orgx.json` file that imports on another ORGX server, where
  members are matched by email. Saved filters re-run on every snapshot and can be frozen
  into a fixed group.
- **Email lists**: from any filter, selection, group or unit. Choose everyone, leaders only
  or one address per office (its org box, else its lead). Leave out contractors, civilians
  or partner-nation accounts. Use `;` for Outlook or `,` for other clients, with or without
  names. Lists are split into batches for relay limits, with a **Copy** button for each batch
  and a mail link (with a Bcc/To/Cc choice) when it fits. Save as `.txt` or an Outlook contacts CSV.
- **Time**: every base's zone, local time, day and duty status. The **planner** lays the
  chosen sites (or the bases of a group's members) across 24 UTC hours with duty,
  edge-of-day and night shading. Click an hour to get a proposal you can copy, giving the
  DTG and each site's local time.
- **Print**: directory or **recall roster** (numbered call-down order, lead first, a
  "Reached" column), grouped by office or group section, stamped with the DTG and snapshot.
  Opens from any filter, unit or group.
- **Data**: sources and ingest log, quality report (missing email/org/location,
  approximate pins, unread ranks, shared emails, unresolved managers, leaderless orgs,
  inferred parents, detected columns), rules, and personal settings (your name, unit,
  base, duty hours, chat-link template, light or dark theme). Theme and keyboard shortcuts are also in the menu at the top right.

### Teaching it

Open anyone and add **Go-to for** topics ("spring exercise", "tokens", "Starlink").
These routes are shared with everyone on the server, survive every re-ingest, and
outrank any inferred match. Tags work the same way (`tag:spring-exercise`). Built-in topics
cover SATCOM, PNT/NAVWAR, EW/EMI, SDA, missile warning, intel/FDO/security, IT/COMSEC,
taskers, OPLAN/annexes A–W, exercises in general, awards/evals/PCS, travel/budget/purchases/manpower,
supply/vehicles/facilities, legal, PA and protocol. Add your own, including named exercises,
under **Rules → Routing topics**.

### Query language

Directory, map, saved filters and exports all share one syntax:

```
satcom planner                 words (prefix match, all must hit)    "annex n"  phrase
base:Alder,Birch               location (site, OU or place name)     region:Europe  country:JP
org:"MERIDIAN GROUP/S6"        org subtree      org:"HARBOR COMM SQ!"  direct members only
fn:cyber   kind:orgbox   cat:civ   tier:field   rank:Capt   grade:>=O-4   afsc:13S
title:director  email:…  phone:4021 (any digits)  ou:"Alder"  service:USSF
under:<email|key>              everyone in someone's reporting chain   reports:<…> direct reports
member:<DL email|name>         members of a distribution list
is:leader|new|moved|promoted|disabled|approx|noted   has:/missing:email|phone|manager|title|org|loc
tag:spring-exercise  list:"Exercise planners"      -anything   negates
```

Keyboard: `Ctrl K` search/ask · `/` filter · `j`/`k` or `↑`/`↓` move through rows · `x` select ·
`g d|o|m|c|l|s` switch views · `Esc` close · `?` help.

## API

Everything the UI does is a JSON call. Useful for scripts and bots:

| | |
|---|---|
| `GET /api/search?q=&sort=&offset=&limit=` | rows + total (`sort`: relevance, smart, name, seniority, org, location, title) |
| `GET /api/facets?q=` | counts per facet (excluding each facet's own filter); org facet drills |
| `GET /api/object?key=` | full detail: chain, reports, peers, groups, members, history, notes |
| `GET /api/org?id=` · `/api/orgtree?root=&depth=` · `/api/orgs?parent=\|q=` | org detail, chart tree, tree nodes |
| `GET /api/locations?q=` · `/api/location?id=` | map aggregates, place detail |
| `GET /api/ask?q=&scope=&home_org=&home_loc=` | routing answer (topics, shops, people with reasons) |
| `GET /api/changes?snap=&type=&org=&kind=` | events + summary + net change by unit |
| `GET /api/quality` · `/api/meta` · `/api/job` · `/api/sources` | health, counts, ingest status |
| `GET /api/export?q=\|keys=&format=csv\|vcf\|emails` | downloads |
| `POST /api/upload?name=` (CSV body) · `/api/reingest` · `/api/demo` · `/api/reset` | data |
| `GET /api/groups` · `/api/group?id=` · `/api/group/export?id=&format=json\|csv` | groups, members with live status and changes, share file |
| `POST /api/group` · `/api/group/import` · `/api/resolve` | create/update/delete groups and members, import a share file, match a pasted list |
| `GET /api/emails?q=\|keys=\|group=&style=&sep=&pick=&exclude=&batch=&field=` | email list batches, mail links, recipients |
| `GET /api/whoami` · `/api/ad` · `POST /api/ad/test` · `/api/ad/sync` | identity, AD connector status, test bind, sync |
| `GET /api/live` · `POST /api/live/search\|person\|unit\|site` (`{q}`, `{key}`, `{id}`) | on-the-fly status and lookups; each returns added/updated counts or `cached` |
| `POST /api/note` · `/api/rules` | team notes, rules |

## Layout

```
server.py              HTTP server (stdlib), static web/, inbox watcher
ingest.py              CLI: CSV → data/org.db (+ --selftest)
orgx/
  parse.py             columns, DAF names, ranks, DN/OU, kinds, org paths, functions
  geo.py               site-level learning, optional site list, coordinates
  ingest.py            streaming build, org inference, history diff, atomic swap
  query.py             query language → SQL (FTS5 with LIKE fallback)
  route.py             "who do I contact" scoring
  groups.py            groups, share files, paste matching
  mail.py              email list builder
  adsync.py            whoami + AD connector (runs the PowerShell export)
  live.py              on-the-fly lookups: lookup worker, upsert, rebuild
  fold.py              drifted spellings of one unit folded together; near misses suggested
  api.py               JSON handlers
  reference.py         ranks, functions, kinds, topics, leadership
  rules.py · db.py     data/rules.json overlay · schema
web/                   index.html, css/app.css, js/ (ES modules, no build step), fonts/ (Public Sans, IBM Plex Sans Condensed, Atkinson Hyperlegible Mono; OFL)
tools/
  Export-ADDirectory.ps1   AD → CSV, streamed (RSAT or ADSI, -Test)
  ADLookup.ps1             targeted lookups for on-the-fly mode (-Serve, -Request)
  ADCommon.ps1             shared searcher, columns and CSV writer
  make_synthetic.py        fictional AD-shaped demo data with churn (--scale, --snapshots, --copies, --messy)
  build_geo.py             regenerates web/js/geo-data.js + data/centroids.json
data/centroids.json    country centroids · data/sites.json (optional, local only) your site coordinates
tests/                 python3 -m unittest discover -s tests   (or: python3 ingest.py --selftest)
DESIGN.md              design decisions, tokens and the reason for each visual element
```

**Design.** ORGX is built to replace the Outlook global address list with a comfortable way to
find people: the organization drawn as a chart, the person's card beside it, and search that
shows where someone sits. It's dark by default, with a light theme available. The palette comes
from the U.S. Web Design System and the Air Force's colors: neutral grays almost everywhere,
one primary blue for the main action and what's selected, green for on duty and red for
failures. Text is set in Public Sans, the federal typeface; unit names and office symbols in IBM
Plex Sans Condensed so long paths fit; phone numbers, DSN and Zulu times in Atkinson
Hyperlegible Mono, whose zero is slashed. Names read in natural order. Classification banners
are left to the operating system.
Every visual element has a reason in `DESIGN.md`.

**Scale.** Measured on a synthetic 875k-object directory (13k units, 226 sites, two snapshots):

- **Ingest** takes about 2 minutes, with memory flat near 220 MB. Rows stream from the file in
  batches. Values that repeat across a directory (titles, unit paths, OU paths, cities) are worked
  out once. The build goes to a temporary file that replaces the live one atomically, so the UI
  keeps serving during an import.
- **Queries** read from indexes shaped to what each screen asks: unit ranges, sites, seniority,
  the default order, function membership (a small side table) and a covering index for facets.
  Each object stores its top-level unit for the unit facet. After every load, ORGX runs
  `ANALYZE` so SQLite picks the narrow index instead of walking a million rows.
- **Connections** are pooled and memory-map the file, so each request starts warm.
- **Answers** are cached until the directory, notes or rules change. The first screens are worked
  out in the background right after each load. Measured there: every call the UI makes is under
  250 ms once warm; repeats take a few milliseconds; a broad filter seen for the first time
  (all civilians, a function across every unit) takes up to about a second.
- A directory built by an older version is upgraded in place the first time the server starts
  (new columns, indexes and statistics), so it works without a reload.

**Security.** There is no authentication built in. Run it on a trusted network, or put it
behind a reverse proxy that handles CAC/SSO. Set `ORGX_UPLOAD=0` to restrict imports to
the inbox and CLI. Team notes and groups are visible to everyone who can reach the server.
The AD connector runs with the credentials of whoever started the server, and reads only.

Map data: Natural Earth (public domain) via world-atlas.
