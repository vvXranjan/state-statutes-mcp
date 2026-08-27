# Michigan — Research & Implementation Notes

Status: **IMPLEMENTED** — state #39.

## Official source

- **Endpoint**: `https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-{chapter}-{section}`
- **Publisher**: Michigan Legislature / Michigan Compiled Laws (MCL),
  Legislative Service Bureau in cooperation with the Legislative Council.
- **Source type**: Official server-rendered HTML of the Michigan Compiled
  Laws.
- **Authentication**: None.
- **API key**: None.

## Source accessibility (ARCHIVED)

The live host (`legislature.mi.gov`) returns an **HTTP 403 bot-challenge
wall** (an ASP.NET/UserCheck `/UserCheck/` challenge page) to this
environment for every path, including the homepage. This is environment/
infrastructure blocking, NOT statute-level behavior. All structure
verification and all fixtures below are based on **real archived official
captures** of the official host, retrieved via the Wayback Machine in
**Aug 2026** — they are archived captures, NOT live captures (the Colorado
precedent). A valid section (`MCL-712A-2D`, upper or lower case) was
verified to return HTTP 200 with full content in archive captures, so the
invalid-section 400/404 findings are not a case-sensitivity artifact.

## Hierarchy (folded)

Real structure: `Chapter-group -> Act -> Division -> Section`, with the
citation `{chapter}.{section}` encoding Chapter -> Section (e.g. `712A.2d`
= chapter 712A, section 2d). Folded onto the framework's three-level model
with NO framework changes (the Minnesota/Wisconsin synthetic-title
precedent):

- **TitleRef = synthetic `"MCL"`** (single code-wide title; the state has
  no formal title level).
- **ChapterRef = MCL chapter** (e.g. `"701"`, `"712A"`, `"750"`) — 227
  chapters from the `/Laws/ChapterIndex` page.
- **SectionRef.identifier = full citation** (e.g. `"712A.2d"`,
  `"750.82"`, `"257.1"`).

Act/Division/chapter-group are folded into discovery and retrieval and are
not framework levels.

## Discovery (VERIFIED via archived captures)

| Page | objectName / URL | Contents |
|------|------------------|----------|
| Chapter index | `/Laws/ChapterIndex` | every chapter as a `<tr>`: `mcl-chap{n}` link + name (227 rows) |
| Chapter | `mcl-chap{n}` | chapter name + table of Acts (`mcl-Act-{n}-of-{year}`) with section ranges |
| Act | `mcl-Act-{n}-of-{year}` | either `Section` rows (direct sections, e.g. Act 62 of 1872 -> 6.1-6.16) or `Division` rows (e.g. Act 288 of 1939 -> divisions I-XIII) |
| Division | `mcl-{act}-{year}-{ROMAN}` | `Section` rows of one chapter (e.g. division XIIA -> sections 712A.1-712A.91) |
| Section | `mcl-{chapter}-{section}` | one complete section |

`list_sections(chapter)` is a bounded walk over the chapter's Acts
(chapter -> Acts -> Act page sections/Divisions -> Division pages), because
the source exposes no single chapter->sections page. Repealed Acts render
only a repeal note (e.g. `5.1-5.5 Repealed.`) and contribute no sections.

## Section retrieval (VERIFIED via archived captures)

Direct and deterministic: `{chapter}.{section}` -> `mcl-{chapter}-{section}`
(replace the single `.` with `-`). The `GetObject?objectName=` endpoint is
a 302 redirect wrapper; the adapter uses the canonical `/Laws/MCL?objectName=`
form directly.

Section page structure:
- `<title>MCL - Section {citation} - Michigan Legislature</title>` (the
  canonical citation).
- `<B>{citation} {catchline.}</B>` — the section heading/catchline.
- `<P>Sec. {n}.</P>` marker, then `<div>` body paragraphs.
- `<font size="2">` block with `History:` / `Former Law:` lines.

Verified sections: **750.82** (Penal Code), **257.1** (Vehicle Code),
**712A.2a** (lettered), **712A.2d** (subsection-heavy).

## Special cases (VERIFIED via archived captures)

- **Lettered sections**: `712A.2a`, `712A.2b`, `712A.2d`; `257.25b`,
  `247.660b` — all work through the generic citation mapping.
- **Subsection-heavy sections**: 712A.2d, 750.82 — full body preserved.
- **Repealed sections**: a section of a repealed Act (e.g. `10.31`, in
  repealed Act 302 of 1945) returns **HTTP 400 with an "Error - Michigan
  Legislature" page** — removed from the code, no content, no "Repealed"
  text. Repealed behaves exactly like nonexistent -> `RefNotFoundError`
  (the Iowa/California "repealed = absent" convention).
- **Invalid sections**: a well-formed but unresolvable objectName returns
  HTTP 400 (Error page); a malformed objectName (`MCL-`) returns HTTP 404
  ("The specified URL cannot be found."); a missing objectName returns HTTP
  400. No valid section is ever returned -> `RefNotFoundError`.
- **Silent fallback**: none. The adapter content-verifies the page title
  (`MCL - Section {citation}`) and the declared section head before
  accepting a result, so a wrong page cannot be silently accepted.
- **Decimal sections**: none observed in the ~5,000 archived captures;
  treated as uncommon (the citation split handles a decimal generically).
- **Versioning**: every page header carries a global `MCL Complete Through
  PA {n} of {year}` banner — a site-wide stamp, ignored.

## Error mapping

| Condition | Exception |
|-----------|-----------|
| Invalid citation / chapter / title format | `RefNotFoundError` |
| HTTP 400/404 on a section objectName (invalid or repealed) | `RefNotFoundError` |
| Page with no `MCL - Section` title (Error page served as 200) | `RefNotFoundError` |
| Declared citation on the page != requested | `RefMismatchError` |
| Ref chapter != citation's chapter | `RefMismatchError` |
| Network failure | `AdapterUnavailableError` |
| Declared section but malformed body/heading | `NormalizationError` |

HTTP 200 alone is never treated as success; the title + declared section
head are always verified.

## Fixture provenance

All `tests/fixtures/mi_*` files are **real archived official captures** of
legislature.mi.gov retrieved via the Wayback Machine in **Aug 2026** (HTTP
200 text/html captures). They are NOT synthetic and NOT live captures. The
set covers: the chapter index, chapter pages (6, 5), Act pages (62 of 1872,
120 of 1937, 288 of 1939), a Division page (288-1939-XIIA), normal sections
(750.82, 257.1), lettered/subsection-heavy sections (712A.2a, 712A.2d), and
the archived HTTP-400 "Error" page for `MCL-10-31` (used to test
invalid/repealed behavior). No statute content was fabricated.

## Performance

- Section pages: ~18-27 KB each — light (far smaller than California's
  ~160 KB pages).
- Chapter index: ~90 KB (one request, cached per adapter instance).
- `list_sections(chapter)`: a bounded walk — 1 chapter page + N Act pages +
  M Division pages (N = Acts in the chapter, M = their Divisions). Large
  multi-Act chapters are heavier; single-Act chapters are 2 requests.

## Security

Fixed official host; the only user-driven input is the validated
`mcl-{chapter}-{section}` objectName derived from a canonical
`{chapter}.{section}` citation (chapter `\d+[A-Z]?`, section
`\d+(\.\d+)?[a-zA-Z]?`), a chapter identifier, and the fixed synthetic
title. No path traversal, no query injection, no arbitrary hosts, no
arbitrary URLs.

## Known limitations

- Live host cannot be exercised from this environment (bot-challenge 403);
  the adapter is verified through archived official fixtures only.
- The archived chapter-index capture contains no lettered chapters, so
  `list_chapters` lettered-chapter parsing is not exercised by that
  fixture (lettered sections are exercised via 712A.2a/712A.2d retrieval).
- `list_sections` is a multi-request walk for chapters with many Acts.
- Repealed sections are indistinguishable from nonexistent ones (both ->
  `RefNotFoundError`), matching the Iowa/California convention.
- Decimal section citations were not observed; treated as uncommon.

## Architecture decision

A single new adapter, `src/state_statutes_mcp/adapters/michigan/adapter.py`,
using the shared `fetch_url`/`strip_tags` helpers. No changes to
`BaseStateAdapter`, models, registry, MCP schema, `_fetch`, `_htmltext`, or
`_pdftext`. Michigan-specific parsing (the synthetic title, the citation ->
objectName mapping, and the Act/Division walk) lives entirely inside the
adapter.