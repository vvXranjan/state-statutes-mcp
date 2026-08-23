# Kentucky Revised Statutes — Source Research

**Status: VERIFIED** (live captures of the official host
`apps.legislature.ky.gov` on Aug 23, 2026, from this environment).

## Source

- Official: Kentucky Revised Statutes (KRS), published by the Kentucky
  Legislative Research Commission.
- Host: `https://apps.legislature.ky.gov`.
- Base path: `https://apps.legislature.ky.gov/LAW/STATUTES`.
- Live host status: **VERIFIED live** from this environment (plain
  `urllib` GETs, browser User-Agent). No auth, no API key, no JS shell.

## Structure

**Hybrid family (new to this project): HTML discovery + PDF retrieval.**
The statutes index page and each chapter page are server-rendered HTML;
each individual section is a real PDF document.

### Hierarchy

The KRS map cleanly onto the framework's three-level
`TitleRef → ChapterRef → SectionRef` model (no framework change):

- `TitleRef.identifier` = the Roman-numeral title (e.g. `"XVII"`). The
  index page lists 44 titles, `TITLE I` through `TITLE LI`.
- `ChapterRef.identifier` = the chapter number (e.g. `"205"`, `"367"`).
  Chapter numbers are **globally unique** across the whole code (548
  chapters, VERIFIED: no duplicates).
- `SectionRef.identifier` = the full KRS citation `{chapter}.{local}`
  (e.g. `"205.010"`), matching the citation the section PDF itself
  declares.
- The site's **opaque** per-chapter and per-section IDs (e.g. chapter 205
  = `38124`, section 205.010 = `7624`) are resolved adapter-internally and
  never leak into the refs.

### URLs

| Resource | URL |
|----------|-----|
| Statutes index (titles + chapters) | `https://apps.legislature.ky.gov/LAW/STATUTES/` |
| Chapter page | `https://apps.legislature.ky.gov/LAW/STATUTES/chapter.aspx?id={opaque}` |
| Section PDF | `https://apps.legislature.ky.gov/LAW/STATUTES/statute.aspx?id={opaque}` |

### Statutes index page (`/LAW/STATUTES/`)

- Lists all 44 titles as
  `<span id="title">TITLE {roman} {name}</span>`, each followed by its
  chapters as
  `<a class="chapter" href="chapter.aspx?id={opaque}">CHAPTER {n} {name}</a>`.
- Example rows (VERIFIED):
  - `TITLE XVII ECONOMIC SECURITY AND PUBLIC WELFARE` contains
    `CHAPTER 205 PUBLIC ASSISTANCE AND MEDICAL ASSISTANCE` (id `38124`).
  - `TITLE XXIX COMMERCE AND TRADE` contains `CHAPTER 367` (id `39092`).

### Chapter page (`chapter.aspx?id={opaque}`)

- Declares its own chapter in
  `<span id="Banner1_lblPageTitle">KRS Chapter {n}</span>`.
- Lists every section as
  `<a class="statute" href="statute.aspx?id={opaque}">.{local}  {catchline}</a>`,
  e.g. `.010  Definitions for chapter.` (VERIFIED: 342 sections in chapter
  205, 324 in chapter 367).
- **Dangerous behavior (VERIFIED)**: an invalid/incorrect chapter ID does
  NOT return a clean HTTP 404 — it returns HTTP 200 with the full index
  page (whose `Banner1_lblPageTitle` reads `Kentucky Revised Statutes`,
  not `KRS Chapter {n}`). This is why the adapter never trusts the
  requested chapter number: after fetching, it requires the page to declare
  the requested chapter (missing declaration → `RefNotFoundError`; a
  different declaration → `RefMismatchError`).
- Sections are grouped under subchapter headings
  (`<div class="heading_text">`), which are presentation-only and ignored.
- A few sections render **twice** on their chapter page (VERIFIED:
  `205.522`, `205.536`, `205.6485` — the same section listed under two
  subchapter headings). The adapter keeps the first occurrence.

### Section PDF (`statute.aspx?id={opaque}`)

- Returns a real PDF (`Content-Type: application/pdf`; VERIFIED on four
  sections). Fetched with the shared `fetch_bytes` (raw bytes, never
  UTF-8-decoded) and extracted with the shared `extract_pdf_text`.
- **PDF text structure (VERIFIED)**:
  - First line: `{citation}   {catchline}` (two or more spaces separate
    them), e.g. `205.010   Definitions for chapter.`.
  - Body: the operative statute text follows, one paragraph per line,
    numbered subsections preserved as `(1)`, `(a)`, `1.`, etc.
  - `Effective: {date}` — an effective-date metadata line.
  - `History: {history}` — the legislative-history block (may span several
    lines).
- **Repealed sections (VERIFIED, 205.020)**:
  - `205.020   Repealed, 1950.`
  - `Catchline at repeal:  Persons eligible for state assistance.`
  - `History: Repealed 1950 Ky. Acts ch. 110, sec. 12. -- ...`
  - Represented per the framework's prose-only-repeal rule (same decision
    as NebraskaAdapter/MassachusettsAdapter): `status=UNKNOWN`, the
    catchline as `heading`, `text=""`, and the repeal/history prose
    preserved in `amendment_notes`.
- **Renumbered sections (VERIFIED, 205.045)**:
  - `205.045   Renumbered as 45.235, effective 1948.`
  - `Note:  1948 Ky. Acts ch. 236 created three new sections ...`
  - Same representation as repealed (heading = catchline, `text=""`,
    note in `amendment_notes`).

## Citation

- `KRS {chapter}.{local}` (e.g. `KRS 205.010`, `KRS 367.110`).
- `raw_citation` is that form, adapter-constructed from the verified
  section identifier (which the PDF itself declares). `KRS` is the
  standard Kentucky abbreviation (INFERENCE from universal usage; the
  numbers are VERIFIED from the site's own pages and PDFs).

## Encoding

Discovery pages: UTF-8 HTML (shared `fetch_url`). Section documents: binary
PDFs fetched as raw bytes via `fetch_bytes`.

## Error boundary

- **HTTP 404 never observed from this host (VERIFIED).** Bad chapter and
  bad section IDs both return HTTP 200 with a fallback page. The adapter's
  defenses are therefore structural, not status-code-based:
  - A chapter fetch whose page does not declare `KRS Chapter {n}` →
    `RefNotFoundError` (the index/fallback page for a bad ID).
  - A chapter fetch whose page declares a *different* chapter →
    `RefMismatchError`.
  - A section fetch that does not return a PDF (`%PDF` magic bytes absent)
    → `RefNotFoundError` (the section does not resolve).
  - A PDF that cannot be extracted → `AdapterUnavailableError` (via the
    shared `extract_pdf_text`).
  - A section PDF whose own declared citation disagrees with the requested
    identifier → `RefMismatchError`.
- Network failures (URLError/Timeout/OSError) → `AdapterUnavailableError`
  via the shared fetch helpers.

## Adapter behavior

- `list_titles` parses the 44 titles from the index page.
- `list_chapters(title_ref)` parses the index, attributing chapters to
  their title by walking the page's title spans; an unknown title →
  `RefNotFoundError`.
- `list_sections(chapter_ref)` resolves the chapter's opaque ID from the
  index, fetches the chapter page (enforcing the chapter-ID safety), and
  returns one section per `.{local} {catchline}` row (deduplicated).
- `build_url` resolves opaque IDs where needed: `TitleRef` → the index URL,
  `ChapterRef` → `chapter.aspx?id={opaque}`, `SectionRef` →
  `statute.aspx?id={opaque}`.
- `retrieve_section(ref)` resolves the section's opaque ID, fetches the raw
  PDF bytes with `fetch_bytes`, extracts text with `extract_pdf_text`,
  cross-checks the PDF's declared citation against `ref`, parses the text
  into a `ParsedDocument`, and calls `normalize`.
- `status` is always `UNKNOWN` (no structural signal; prose inference is
  forbidden by the contract).

## Fixture provenance

All `tests/fixtures/ky_*` files are **real** verbatim captures of the
official host, fetched live on Aug 23, 2026. They are NOT synthetic.

| Fixture | Page / URL |
|---------|------------|
| `ky_index.html` | `https://apps.legislature.ky.gov/LAW/STATUTES/` |
| `ky_chapter205.html` | `chapter.aspx?id=38124` (Chapter 205) |
| `ky_chapter367.html` | `chapter.aspx?id=39092` (Chapter 367) |
| `ky_section_205-010.pdf` | `statute.aspx?id=7624` (205.010, normal) |
| `ky_section_205-020.pdf` | `statute.aspx?id=7625` (205.020, repealed) |
| `ky_section_205-045.pdf` | `statute.aspx?id=7628` (205.045, renumbered) |
| `ky_section_367-110.pdf` | `statute.aspx?id=34907` (367.110, cross-chapter) |
| `ky_invalid_section.html` | `statute.aspx?id=999999` (real bad-ID fallback) |

## Known limitations

1. **Only two chapters live-captured** (205, 367) and four sections —
   whether every chapter/section page renders identically is otherwise
   UNVERIFIED.
2. **No genuine HTTP 404 observed** — this host returns HTTP 200 with
   fallback pages for bad IDs; the adapter's structural defenses are
   verified, but a true 404 path cannot be exercised.
3. **Duplicate section rows** exist on chapter pages (205.522, 205.536,
   205.6485); the adapter keeps the first occurrence — the second is
   identical, so this is safe but was only observed in one chapter.
4. **`KRS` abbreviation is INFERENCE**; the citation numbers are VERIFIED.

## Architecture impact

**None to the framework; new shared infrastructure reused.** Kentucky is
the first PDF-family adapter but requires no change to `BaseStateAdapter`,
the refs, models, registry, `server_tools.py`, or the exception hierarchy.
It uses the shared binary-fetch (`fetch_bytes`) and PDF-extraction
(`extract_pdf_text`) infrastructure added in the PDF-infrastructure
milestone. All Kentucky-specific behavior (opaque-ID resolution, PDF text
parsing, the dangerous-chapter-ID defense) lives inside
`KentuckyAdapter`. The test helper
`tests/_mock_network.py::mock_urlopen_serving_bytes` was added to serve
binary fixtures; no adapter or framework code was modified.