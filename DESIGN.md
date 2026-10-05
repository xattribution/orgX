# ORGX design notes

Every visual element in `web/` should trace to a line in section 4. If it doesn't, it goes.

## 1. Who uses it and where

- **Who**: staff officers, NCOs, civilians and exercise planners across a global DAF/USSF
  footprint. Many lookups a day, each a few seconds long, usually in the middle of writing an
  email, building a distro or setting up a call.
- **What it replaces**: the Outlook global address list. That means an alphabetical list of
  `SMITH, JOHN A CIV USAF HARBOR/A3O` strings, a properties dialog with tabs, and no idea who
  actually handles what. The job is to make that lookup faster and more pleasant, not to
  reproduce it.
- **Where**: NIPR desktops in bright offices, 1080p to 1440p, Edge or Chrome. Sometimes a
  laptop. The operating system already shows the classification banners, so the app doesn't.
- **What they already read fluently**: the Outlook contact card (name, title, office, phone,
  email, manager, direct reports), the email signature block, office symbols, rank
  abbreviations, DSN beside commercial numbers, DTGs and Zulu time.
- **The first screen's job**: a comfortable way to find people at work. Type a few letters or
  move through the chart, see the person's whole card and where they sit, and act (email, copy,
  call, chat) without opening anything else. Second job: "who handles X?"
- **What binds it**: Section 508 / WCAG 2.2 AA. Red only for failures, yellow only for
  caution, and color never the only cue. Offline: NIPR desktops often can't reach CDNs, so
  everything is self-hosted.

## 2. Plan

**Color.** Dark is the default; light is a set of overrides on the same names. The values come
from the U.S. Web Design System (the federal design system) and the Air Force's own colors, not
from a framework's default steps. Almost every pixel is a neutral gray. Color has three jobs:

- **Primary**, the USWDS blue-warm family, marks the one main action on a screen (Email, Email
  list) and the outline of what's selected or focused. In light mode it is Air Force Blue.
- **Secondary**, the same family as a quiet solid fill, marks the selected row, tab segment,
  unit or tile. Text on it stays near-white (dark) or deep blue (light).
- **Status**: green means on duty and red means failed, departed or destructive. Both always
  come with a word.

There are no gradients, glows, colored shadows or category colors. In the dark theme depth
comes from slightly lighter surfaces, not shadows.

| Token | Dark | Light | Role |
|---|---|---|---|
| `--paper` / `--surface` / `--raised` | `#1c1d1f` gray-cool-90 / `#232528` / `#2d2e2f` gray-cool-80 | `#f5f6f7` / `#ffffff` / `#ffffff` | base and canvas; panels, chart boxes, tiles; menus and dialogs |
| `--ink` / `--ink-2` / `--muted` | `#edeff0` / `#c6cace` / `#a9aeb1` (gray-cool 5/20/30) | `#1b1b1b` / `#3d4551` / `#565c65` | text; secondary text is at least 6.8:1 |
| `--rule` / `--rule-strong` | `#2d2e2f` / `#3d4551` | `#dfe1e2` / `#a9aeb1` | separators, chart lines and box edges |
| `--primary` / `--on-primary` | `#345d96` blue-warm-60 / white (6.7:1) | `#00308f` Air Force Blue / white (11.5:1) | the one main action |
| `--accent` | `#98afd2` blue-warm-30 | `#00308f` | focus ring, selected outline, the person's path in the chart |
| `--sel` / `--on-sel` | `#2f4668` blue-warm-70 / `#edeff0` (8.3:1) | `#e1e7f1` blue-warm-10 / `#162e51` | selected fill |
| `--ok` / `--bad` | `#86b98e` green-cool-30 / `#ed8c84` | `#4d8055` / `#b02b27` | on duty; failed, departed, destructive. Always with a word |

**Type.** Three faces, each with a job:

- **Public Sans** (USWDS, OFL) for interface text and names. It's the typeface of federal
  websites, so it reads as a government tool without imitating any one office.
- **IBM Plex Sans Condensed** (OFL) for unit names, office symbols and the unit list, where width
  is tight. "MERIDIAN GROUP/S3/S36" fits a chart box, and its I, l and 1 can't be confused.
- **Atkinson Hyperlegible Mono** (Braille Institute, OFL) for DSN, phone numbers, Zulu times and
  counts, which people read digit by digit. Its zero is slashed.

Sizes 12 / 13 / 14 / 16 / 22 px; weights 400, 500 and 600; sentence case; tabular figures. All
files are self-hosted with their licenses in `web/fonts/`.

**Primary screen**: People. The org chart is the center of the screen; finding someone means
seeing where they sit.

```
[ ORGX  (People) Groups Time Data   [ Search people, offices, bases ]  031452Z OCT 26  ⚙ ]
[ (Units) Bases | All units › MERIDIAN GROUP    (Org chart) Map  − + ⤢ | Col Pilar Cole  ]
[ Filter        |              ┌───────────────┐                       | Commander       ]
[ + ATLAS   246 |              │ MERIDIAN GROUP│                       | Email ✉  DSN ☎   ]
[ − MERID   108 |      ┌───────┴──┬───────────┬┴──────┐                | Reports to …    ]
[ + SUMMIT   46 |    ┌─┴─┐      ┌─┴─┐       ┌─┴─┐   ┌─┴─┐              | Direct reports  ]
[               |    │S1 │      │S3 │       │S6 │   │JA │              |                 ]
[           |------------------------------------------------------|                 ]
[           | People in S6 (21)  [This office|Everyone under]       |                 ]
[           | [tile] [tile] [tile] [tile]                           |                 ]
```

**The one standout element**: the org chart canvas. Units are line-and-block boxes with the
lead and headcount; picking a person from search lights up their office (filled) and the
units above it (outlined), and moves the chart to it. Everything else frames it.

## 3. What a generic people directory would have done instead

Each of these is removed or replaced:

- An alphabetical list as the first screen, the GAL's own failure.
- Inter, slate with an indigo accent, rounded cards with soft shadows, initials avatars in
  colored circles.
- KPI tiles ("1,020 people · 85 offices"), a change-tracking dashboard, toasts for every action.
- Explainer paragraphs under every heading, a title on every region, a row of six buttons.
- Framework default shades (Tailwind blue-500, slate-900), a bright accent on near-black,
  colored stripes on cards, one hue per category.

What ORGX does instead: the organization drawn as a chart you move through; the selected
person's card always beside it; the people of the selected unit underneath; questions answered
in the same search box; help in small (i) tips only where a term needs it. Change history
lives under Data, out of the way.

## 4. Why each visual element exists

| Element | Encodes | Reason |
|---|---|---|
| Org chart canvas, line-and-block boxes with lead and headcount | Who belongs where | The chart people already draw; standout element |
| Secondary fill in the chart | The selected person's office | Where they sit, at a glance |
| Accent outline on chart boxes | The selected unit, and the units above the person's office | The path down to them |
| Unit tree in the left rail, with a Units / Bases switch | The same organization as a list, by unit or by base | Two ways in to one structure; starred people live in the strip, not twice |
| Person tiles under the chart | The people in the selected unit | Who's in this box; click for their card |
| Secondary fill on the selected segment, tree item and tile; a neutral step on the current tab | Where you are, what's on | Selected states are solid with contrasting text, never a tint |
| Neutral step plus a 1px accent ring on the selected list row | The record shown in the card | Survives grayscale and color-vision deficiency |
| Primary fill on one button per screen | The main action (Email, Email list, New group) | Everything else is a quiet button or sits in the More menu |
| Contact strip with large values in the card | Email, DSN and commercial, click to copy | What people open the directory for |
| Mono on phone numbers, DSN, times and chart counts | Values read out digit by digit | Character comparison |
| Condensed face on unit names, office symbols and the unit list | Long office paths in narrow places | Fits a chart box without truncating |
| 4px radius on controls, tiles and chart boxes; 6px on menus and dialogs; regions flush | Things you can press versus where things are | Boxes only for things you act on |
| Floating layers are a lighter surface with a hairline edge in dark; a soft shadow in light | Something above the page | Depth only where there really is a layer |
| Green word for duty hours; gray words for edge of day, off and night | Whether they're at work now | Status always paired with a word; no amber |
| Red text | Departed, disabled, failed, destructive | Red only for failure |
| Zulu DTG in the header; the chosen bases open beneath it | The time staff coordinate in, with local time and zone letters on demand | Always visible, one line, no strip of clocks on every page |
| More menu (⋯) | Exports, sharing, edit and delete | Frequent actions visible, the rest one click away |
| Dark theme default, light available | Long sessions at a desk; light for bright offices | Setting |
| Short status line at the bottom when something happens ("Copied DSN 315-…") | Confirmation of an invisible action | Feedback without dialogs |
| (i) tips | The few terms that need explaining | No explainer text printed on pages |
| On-the-fly results fill in place, with no spinner | Records that arrived from AD after the first draw | Lookups take well under a second; a loader would flash |
| AD settings show only the current mode's fields | Export settings or lookup settings, never both | No disabled or irrelevant controls |
| Dashed outline on map markers | Approximate placement | Position confidence, shown without color |
