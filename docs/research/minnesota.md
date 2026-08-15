# Minnesota Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://www.revisor.mn.gov`) IS reachable from this environment, so
official markup was captured live and inspected. Every URL below was
executed directly against the live site with plain HTTP GETs; structure
is documented verbatim from those responses, which are the
implementation boundary for this adapter.

## Status

**VERIFIED live** for the core discovery and retrieval paths: part
listing (the statutes root page), chapter listing (the part page),
section listing (the chapter page), section retrieval with heading,
body, and trailing history block, and the per-section-page chapter/
section cross-check anchors. All verified from live HTTP 200 responses
of the official `revisor.mn.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: whether every
part page always renders its chapter table identically, whether every
section page renders identically (sampled `3C.12` and `3E.01`), and the
exact markup of a repealed section page. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://www.revisor.mn.gov/statutes/` — the official Revisor of
  Statutes publication of Minnesota Statutes.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the live HTML contains the
  full content statically, including the 2025 Minnesota Statutes banner).
- The site names itself "Minnesota Statutes" and the current edition is
  "2025 Minnesota Statutes". VERIFIED from the live pages.

## Accessibility

- Fully reachable from this environment: every URL below returned HTTP
  200. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Two structural levels, matching the framework with a synthetic title:

- **Part** — the top level. 105 parts, each identified by its part NAME
  (e.g. `DATA PRACTICES`, `JURISDICTION, CIVIL DIVISIONS`). Each part
  groups a chapter range (e.g. `13 - 13C`). A part has its own official
  page listing its chapters. VERIFIED from the root page (105 rows, 105
  unique names).
- **Chapter** — grouping within a part, e.g. `3C`, `13`, `13A`. Chapters
  may be numeric or lettered. VERIFIED (chapter `3C` under the
  `LEGISLATURE` part; chapters `13`, `13A`, `13B`, `13C` under the
  `DATA PRACTICES` part).
- **Section** — the individually retrievable unit, e.g. `3C.12`, `3E.01`.

The site has NO formal title level: chapters are grouped directly into
parts. To fit the framework's three-level ref model, this adapter maps
the official Part groupings onto the framework's `TitleRef` (the part
name becomes the synthetic title identifier). This is an adapter-internal
mapping, documented here and in the adapter module docstring.

## URL Scheme

- Part (synthetic title) page: `https://www.revisor.mn.gov/statutes/part/{NAME}`
  where `{NAME}` is the part name URL-encoded with `urllib.parse.quote_plus`
  (spaces become `+`, commas become `%2C`). VERIFIED:
  `.../statutes/part/DATA+PRACTICES` (200), `.../statutes/part/JURISDICTION%2C+CIVIL+DIVISIONS`
  (200), `.../statutes/part/JURISDICTION+CIVIL+DIVISIONS` (404 — comma
  MUST be encoded).
- Chapter TOC page: `https://www.revisor.mn.gov/statutes/cite/{chapter}`
  (e.g. `/statutes/cite/3C`, 200). Lists every section of the chapter.
- Section page: `https://www.revisor.mn.gov/statutes/cite/{chapter}.{section}`
  (e.g. `/statutes/cite/3C.12`, 200; `/statutes/cite/3E.01`, 200).
- Statutes root: `https://www.revisor.mn.gov/statutes/` (200) — the part
  listing page.

## Verified Page Structures

### Root page (`/statutes/`) — part listing

A "Table of Chapters" table (`<table id="toc_table">`), one row per
part. Each row:

```html
<tr> <td> <a href="https://www.revisor.mn.gov/statutes/part/DATA+PRACTICES"> 13 - 13C </a> </td> <td>DATA PRACTICES</td> </tr>
```

105 rows, 105 unique part names. The link text is the chapter range
(e.g. `13 - 13C`); the adjacent `<td>` is the part name. VERIFIED.

### Part page (`/statutes/part/{NAME}`) — chapter listing

A "Table of Chapters" table (`<table id="chapters_table">`), one row
per chapter. Each row:

```html
<tr> <td><a href="https://www.revisor.mn.gov/statutes/cite/13">13</a></td> <td>GOVERNMENT DATA PRACTICES</td> </tr>
```

Verified for `DATA PRACTICES` (4 chapters: `13`, `13A`, `13B`, `13C`)
and `LEGISLATURE` (chapter `3C` among others). VERIFIED.

### Chapter TOC page (`/statutes/cite/{chapter}`) — section listing

A "Table of Sections" table, one row per section. Each row:

```html
<tr> <td> <a href="/statutes/cite/3C.01">3C.01</a> </td> <td>APPOINTMENT OF REVISOR.</td> </tr>
```

Verified for chapter `3C`: 18 section rows (`3C.01`, `3C.02`, `3C.03`,
`3C.035`, `3C.04`, ..., `3C.20`). Section identifiers are the full
dotted chapter.section citation. Repealed sections keep their row but the
name cell is `<td class="inactive"> [Repealed, <a ...>...</a>]</td>` (e.g.
`3C.055`, `3C.056`, `3C.057`); the adapter lists them with that annotation.
VERIFIED.

### Section page (`/statutes/cite/{chapter}.{section}`)

Verified for `3C.12` and `3E.01`:

- Cross-check anchors: `<h2>Chapter 3C</h2>` and `<h2>Section 3C.12</h2>`
  appear before the section content. VERIFIED.
- Heading: `<h1 class="shn">3C.12 SALE AND DISTRIBUTION OF STATUTES AND LAWS.</h1>`
  (the leading `{section} ` is stripped for the heading). VERIFIED.
- Body: `<div class="subd" id="stat.3C.12.1">` blocks, each holding a
  `<h2 class="subd_no">Subdivision 1.<span class="headnote">Number of
  copies printed.</span></h2>` and one or more `<p>` paragraphs. Simple
  sections (e.g. `3E.01`) use bare `<p>` paragraphs with no `subd`
  blocks. VERIFIED.
- History: `<div class="history" id="stat.3C.12.history..."> <h2>History: </h2>
  <p class="first">1984 c 480 s 12; ...</p>`. The `<p class="first">`
  holds the session-law citations as links. VERIFIED for `3C.12`
  (18 citations) and `3E.01` (`2013 c 7 s 1,11`).
- No Notes section observed on the sampled sections.

## Citation

- Citation form: `Minn. Stat. § {chapter}.{section}` (e.g. `Minn. Stat. §
  3C.12`), adapter-constructed; `Minn. Stat.` is the standard citation
  abbreviation, INFERENCE from standard Minnesota citation usage (the
  site itself uses "Minnesota Statutes" in its banner). The section
  number is VERIFIED from the site's own headings.
- `SectionRef.identifier` is the full dotted `{chapter}.{section}`
  citation as it appears in the chapter TOC links and section page
  headings (e.g. `"3C.12"`, `"3E.01"`). VERIFIED.

## Error Boundary

- A missing part, chapter, or section returns HTTP 404. VERIFIED live:
  `/statutes/part/DOESNOTEXIST` (404), `/statutes/cite/999.999` (404),
  `/statutes/cite/9999` (404). Mapped to `RefNotFoundError` in the
  adapter.

## Known Limitations

- The synthetic title mapping (Part as `TitleRef`) means titles returned
  by `list_titles` are Minnesota's official Part groupings, not "titles"
  in the traditional sense; this is a documented adapter-level mapping,
  not a framework change.
- Part names that contain characters other than letters/spaces/commas
  (e.g. semicolons in `LOCAL JAIL FACILITIES; LOCKUPS;`) rely on
  `urllib.parse.quote_plus` producing the exact bytes the site expects;
  only the two verified names (comma and space forms) are confirmed.
- Whether every section page renders identically (subd vs. plain `<p>`
  body) has only been sampled; the parser handles both shapes.
