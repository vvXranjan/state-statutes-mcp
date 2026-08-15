# Ohio Statute Source Research

Research performed: Aug 15, 2026. The live host (`https://codes.ohio.gov`)
is NOT reachable from this environment (all requests returned 000 — see
Accessibility below), so official markup was captured from a Wayback
Machine snapshot of the official host and inspected. Every URL below was
executed against the official source through the Wayback Machine; structure
is documented verbatim from those responses, which are the implementation
boundary for this adapter.

## Status

**VERIFIED (via Wayback snapshot 20260812050041 of the official
`codes.ohio.gov` host)** for the core discovery and retrieval paths: title
listing (the ORC index page), chapter listing (the title page), section
listing (the chapter page), section retrieval with heading, body, and
version history, and the HTTP-404 missing-section signal. All verified
from HTTP 200/404 responses of the official HTML.

**UNVERIFIED** for a small set of secondary questions: whether every title
page keeps the same chapter-row markup and every chapter page the same
section-list markup (sampled Title 29 and Chapter 2901), and whether any
other title uses the `General Provisions` unnumbered entry seen on the
index page. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://codes.ohio.gov` — the official Ohio Laws publication of
  the Ohio Revised Code (ORC), run by the Ohio Legislative Service
  Commission.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically).
- The site names itself "Ohio Revised Code" and organizes the code into
  Titles, Chapters, and Sections. VERIFIED.

## Accessibility

- The live host `codes.ohio.gov` is NOT reachable from this environment:
  direct `curl` requests (both `http://` and `https://`) returned 000 with
  no HTTP response. VERIFIED (repeated attempts, browser UA, Aug 15, 2026).
- The same URLs return HTTP 200/404 through the Wayback Machine snapshot
  `20260812050041` of the official host. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 33 numbered titles (1, 3, 5, ..., 63 — all odd
  numbers, no gaps), each identified by its number, e.g. `29`
  ("Crimes-Procedure"). The index page also lists one unnumbered
  `General Provisions` entry (a non-title page) which is excluded from the
  adapter's `list_titles`. VERIFIED (33 numbered title links).
- **Chapter** — grouping within a title, e.g. Chapter 2901. Chapter
  numbers are the 4-digit prefix of the section numbers in that title
  (e.g. Title 29 -> Chapter 2901, 2903, ... 2981). VERIFIED (36 chapter
  links on Title 29).
- **Section** — the individually retrievable unit, e.g. `2901.01`,
  `2901.011`. Section ids are `{chapter}.{local}` where the chapter is the
  4-digit prefix. Decimal-extension sections (`2901.011`) are new sections
  inserted after a base section. VERIFIED. No lettered section ids observed.

## URL Scheme

- Title list: `https://codes.ohio.gov/ohio-revised-code` (200 via
  Wayback). Lists all 33 titles plus the unnumbered General Provisions
  entry.
- Title page: `https://codes.ohio.gov/ohio-revised-code/title-{N}` (e.g.
  `/title-29`, 200). Lists every chapter of the title.
- Chapter page: `https://codes.ohio.gov/ohio-revised-code/chapter-{NNNN}`
  (e.g. `/chapter-2901`, 200). Lists every section of the chapter.
- Section page: `https://codes.ohio.gov/ohio-revised-code/section-{NNNN.NN}`
  (e.g. `/section-2901.01`, 200). One file per section. The page also
  supports dated version URLs (`/section-2901.01/10-3-2023`) for prior
  versions, not used by this adapter.

## Verified Page Structures

### Title list page (`/ohio-revised-code`)

A table (`<table class="data-grid laws-table">`), one `td.name-cell` row
per title:

```html
<td class="name-cell">
    <a href="ohio-revised-code/title-29">Title 29 <span class='codes-separator'>|</span> Crimes-Procedure</a>
</td>
```

VERIFIED (33 numbered titles; the `General Provisions` entry has an
`ohio-revised-code/general-provisions` href with no `title-{N}` number and
is excluded by the `title-(\d+)` href anchor).

### Title page (`/ohio-revised-code/title-{N}`)

A table (`<table class="data-grid laws-table">`), one `td.name-cell` row
per chapter:

```html
<td class="name-cell">
    <a href="chapter-2901">Chapter 2901 <span class='codes-separator'>|</span> General Provisions</a>
</td>
```

VERIFIED for Title 29: 36 chapter rows (2901, 2903, ..., 2981). The chapter
identifier is the number in the href (`2901`); the name is the text after
the `|` separator (e.g. `General Provisions`).

### Chapter page (`/ohio-revised-code/chapter-{NNNN}`)

Two parts:

1. A discovery table (`<table class="data-grid laws-table">`) with one
   `td.name-cell` row per section:
   ```html
   <td class="name-cell">
       <a href="section-2901.01">Section 2901.01 <span class='codes-separator'>|</span> General provisions definitions.</a>
   </td>
   ```
   VERIFIED for Chapter 2901: 26 section rows (2901.01, 2901.011, 2901.02,
   ..., 2901.431). The section identifier is the number in the href
   (`2901.01`); the name is the text after the `|` separator.
2. The full text of every section is also embedded in the page below the
   table (each with its own `laws-section-info` / `laws-body` block). The
   adapter parses only the discovery table for `list_sections`; the
   embedded copies are ignored.

### Section page (`/ohio-revised-code/section-{NNNN.NN}`)

VERIFIED for `2901.01` and the decimal-extension `2901.011`:

- Heading: `<h1>Section 2901.01 <span class='codes-separator'>|</span>
  General provisions definitions.</h1>` — the heading is the text after the
  `|` separator. VERIFIED.
- Breadcrumbs cross-check anchors (inside `div.breadcrumbs`):
  `<a href="/ohio-revised-code/title-29">Title 29 Crimes-Procedure</a>`
  and `<a href="/ohio-revised-code/chapter-2901">Chapter 2901 General
  Provisions</a>`. VERIFIED.
- Effective / latest-legislation info block (`div.laws-section-info`):
  `Effective: October 3, 2023` and `Latest Legislation: House Bill 33 -
  135th General Assembly`. VERIFIED.
- Body: `<section class="laws-body">` containing `<span><p>...</p></span>`
  (one `<p>` per paragraph). VERIFIED (13,351 chars of cleaned text for
  2901.01). A separate `div.laws-notice` ("Last updated ...") sits inside
  the `laws-body` section AFTER the closing `</span>` and is excluded.
- History: `<section class="laws-history">` "Available Versions of this
  Section" listing each prior version as `<li><span>{date} &ndash;
  {legislation}</span></li>` (e.g. `October 3, 2023 &ndash; Amended  by
  House Bill 33 - 135th General Assembly`). VERIFIED (5 versions for
  2901.01, 2 for 2901.011). The version list is preserved verbatim as
  `amendment_notes`; `status` stays `UNKNOWN` (the page carries no
  structural repealed/reserved signal for current sections).
- The section's own h1 is the only self-identifier; it is cross-checked
  against the requested `SectionRef`, and the breadcrumb title/chapter
  links are cross-checked against `ref.chapter.title`/`ref.chapter`.

## Citation

- Citation form: `Ohio Rev. Code § {section}` (e.g. `Ohio Rev. Code §
  2901.01`, `Ohio Rev. Code § 2901.011`), adapter-constructed; the `Ohio
  Rev. Code` abbreviation is INFERENCE from standard Ohio citation usage
  (the site itself just says "Ohio Revised Code" in its header), and the
  section number is VERIFIED from the site's own h1 text.
- `SectionRef.identifier` is the full `{chapter}.{local}` form exactly as
  the chapter-page links and section-page h1 name it (e.g. `"2901.01"`,
  `"2901.011"`).

## Error Boundary

- A missing section returns HTTP 404. VERIFIED (via Wayback, `/section-9999.99`
  -> 404). Mapped to `RefNotFoundError` in the adapter.
- A missing title/chapter is expected to 404 as well (INFERENCE from the
  section 404 and the consistent resource-per-level scheme); the adapter's
  shared `_fetch_html` maps any HTTP 404 to `RefNotFoundError`.

## Known Limitations

- The live host is unreachable from this environment, so the adapter is
  developed and tested against real Wayback-captured fixtures; live
  verification was not possible at implementation time.
- Whether every title page keeps the same chapter-row markup and every
  chapter page the same section-list markup has only been sampled (Title
  29, Chapter 2901).
- The `General Provisions` unnumbered index entry is excluded from
  `list_titles`; its contents are not addressable as a title.
- No repealed/reserved section was found in Chapter 2901; repealed-section
  markup (if it differs from the current form) is UNVERIFIED.
