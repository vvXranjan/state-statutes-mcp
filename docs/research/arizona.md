# Arizona Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://www.azleg.gov`) IS reachable from this environment, so official
markup was captured live and inspected. Every URL below was executed
directly against the live site with plain HTTP GETs; structure is
documented verbatim from those responses, which are the implementation
boundary for this adapter.

## Status

**VERIFIED live** for the core discovery and retrieval paths: title
listing (the `/arstitle/` page), chapter listing (the title detail page),
section listing (the same title detail page), section retrieval with
heading and body, and the per-section-page citation number. All verified
from live HTTP 200 responses of the official `azleg.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: whether every
title detail page renders identically, whether every section page renders
identically (sampled `28-101` and the compound `28-622.01`), and whether
title pages beyond Title 28 keep the same accordion markup. Those are
flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://www.azleg.gov` — the official Arizona Legislature
  publication of the Arizona Revised Statutes (A.R.S.).
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the live HTML contains the full
  content statically).
- The site names itself "Arizona Revised Statutes" and uses "ARS" /
  "A.R.S." throughout (e.g. page titles "Title N - General Provision").
  VERIFIED.

## Accessibility

- Fully reachable from this environment: every URL below returned HTTP
  200. VERIFIED.
- `https://www.azleg.gov/arsDetail?title=N` (no trailing slash) returns a
  301 to `/arsDetail/?title=N`; the canonical trailing-slash form returns
  200 directly. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 47 linked titles (Title 1 through 49, minus
  Titles 2 and 24 which are repealed with no page), each identified by
  its number, e.g. `28` ("Motor Vehicle Act"). The `/arstitle/` table
  also lists an "All" row (a search checkbox, not a title). VERIFIED
  (50 rows; 47 linked titles).
- **Chapter** — grouping within a title, e.g. Chapter 1, 3, 7. Chapters
  have no dedicated page of their own (their links have empty `href`).
  VERIFIED.
- **Section** — the individually retrievable unit, e.g. `28-101`,
  `28-622.01`. Compound sections carry a `.NN` suffix (e.g. `28-622.01`).

## URL Scheme

- Title list: `https://www.azleg.gov/arstitle/` (200). Lists every title.
- Title detail: `https://www.azleg.gov/arsDetail/?title={N}` (e.g.
  `/arsDetail/?title=28`, 200). Lists every chapter and section of the
  title.
- Section page: `https://www.azleg.gov/ars/{title}/{file}.htm` (e.g.
  `/ars/28/00101.htm`, 200; `/ars/28/00622-01.htm`, 200). The file name
  rule: the section's local number (after the title dash) is split on the
  dash; the base part is zero-padded to 5 digits and, for compound
  sections, a `-{suffix}` is appended: `28-101` -> `00101.htm`,
  `28-622.01` -> `00622-01.htm`. VERIFIED.

## Verified Page Structures

### Title list page (`/arstitle/`)

A table (`<table id="arsTable">`), one row per title. Each linked-title
row:

```html
<tr><td><input type="checkbox" class="arstitle" name="arstitle" value="1" ...></td>
<td><a href="https://www.azleg.gov/arsDetail?title=1">Title 1</a></td>
<td>General Provision</td></tr>
```

The "All" row has `value="0"` and no `arsDetail` link; repealed Title 2
has no link at all. VERIFIED (47 linked titles, Title 2 marked "THIS
TITLE HAS BEEN REPEALED", no link).

### Title detail page (`/arsDetail/?title={N}`)

One `<div id="chapter{N}" class="accordion">` block per chapter, each
holding a chapter heading and its sections:

```html
<div id="chapter1" class="accordion"><h5 ...>Chapter 1
  <div class="two-thirds">DEFINITIONS, PENALTIES AND GENERAL PROVISIONS</div>
  <div ...>Sec: 28-101-28-145</div></h5> ...
  <li class="colleft"><a class="stat" ... href="/viewdocument/?docName=
    https://www.azleg.gov/ars/28/00101.htm">28-101</a></li>
  <li class="colright"> Definitions </li> ...
</div>
```

Verified for Title 28: 29 chapter accordions (chapters 1-11, 13-27, 30-32;
chapter 12 is not used) and 1674 section `li` pairs. Chapter identifiers
are the accordion's numeric id; the chapter name is the `.two-thirds` div
text. Section identifiers are the full `{title}-{section}` label (e.g.
`28-101`, `28-622.01`); the section name is the `colright` text.

### Section page (`/ars/{title}/{file}.htm`)

Verified for `28-101` and the compound `28-622.01`:

- Heading paragraph: `<p><font color=GREEN>28-101.</font> <font
  color=PURPLE><u>Definitions</u></font></p>` — the citation number is the
  GREEN text (a trailing period may be inside or outside the `<font>`) and
  the heading is the PURPLE underlined text. VERIFIED.
- Body: plain `<p>` paragraphs following the heading paragraph, one
  paragraph per line. VERIFIED (211 `<p>` in 28-101).
- No history/amendment line on the sampled section pages. VERIFIED.
- No cross-check anchors (no title/chapter TOC elements) on the section
  page; the citation number in the heading is the only self-identifier.

## Citation

- Citation form: `A.R.S. § {title}-{section}` (e.g. `A.R.S. § 28-101`,
  `A.R.S. § 28-622.01`), adapter-constructed; `A.R.S.` is the standard
  citation abbreviation, INFERENCE from standard Arizona citation usage
  (the site uses "ARS" in its URLs). The section number is VERIFIED from
  the site's own heading text.
- `SectionRef.identifier` is the full `{title}-{section}` form exactly as
  the title-detail links and section page headings name it (e.g.
  `"28-101"`, `"28-622.01"`).

## Error Boundary

- A missing section file returns HTTP 404. VERIFIED live:
  `/ars/1/99999.htm` (404). Mapped to `RefNotFoundError` in the adapter.
- A missing title returns HTTP 404. VERIFIED live: `/arsDetail/?title=999`
  (404).

## Known Limitations

- Chapter pages do not exist as separate resources; chapters are only
  discoverable from the title detail page, so `build_url(ChapterRef)`
  returns the title detail page (the closest real resource).
- Whether every title detail page keeps the same accordion markup and
  every section page the same heading shape has only been sampled
  (Titles 1 and 28; sections 28-101 and 28-622.01).
- Compound-section file naming (the `-{suffix}` rule) is verified only
  for `28-622.01`; the general rule is INFERENCE from that one example and
  the site's file layout.
