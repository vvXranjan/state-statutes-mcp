# Iowa Code — Source Research

**Status: VERIFIED** (live captures of the official host
`legis.iowa.gov` on Aug 23, 2026, from this environment).

## Source

- Official: Iowa Code, published by the Iowa Legislature.
- Host: `https://www.legis.iowa.gov`.
- Base path: `https://www.legis.iowa.gov/law/iowaCode`.
- Live host status: **VERIFIED live** from this environment (plain
  `urllib` GETs, browser User-Agent). No auth, no API key, no JS shell.

## Structure

**Hybrid family (HTML discovery + PDF retrieval), reusing the shared
PDF pipeline established by Kentucky.**

### Hierarchy

The Iowa Code maps cleanly onto the framework's three-level
`TitleRef → ChapterRef → SectionRef` model (no framework change):

- `TitleRef.identifier` = the Roman-numeral title (e.g. `"I"`). The root
  page lists all 16 titles, `Title I` through `Title XVI`.
- `ChapterRef.identifier` = the chapter number (e.g. `"1"`, `"6A"`).
  Chapter identifiers can be numeric or numeric-plus-trailing-uppercase-
  letter.
- `SectionRef.identifier` = the full citation `{chapter}.{local}`
  (e.g. `"1.1"`, `"1.15A"`). Section identifiers can carry a trailing
  uppercase letter.
- The **current Code year** is resolved dynamically from the root page:
  every title/chapter/PDF link embeds `year=YYYY` (VERIFIED: `2026` at
  capture time). The adapter does not hardcode the year.

### URLs

| Resource | URL |
|----------|-----|
| Root (titles) | `https://www.legis.iowa.gov/law/iowaCode` |
| Chapter listing | `https://www.legis.iowa.gov/law/iowaCode/chapters?title={ROMAN}&year={YEAR}` |
| Section listing | `https://www.legis.iowa.gov/law/iowaCode/sections?codeChapter={N}&year={YEAR}` |
| Section PDF | `https://www.legis.iowa.gov/docs/code/{YEAR}/{chapter}.{section}.pdf` |

### Root page

- Lists all 16 titles as table rows
  `Title {ROMAN} - {NAME} (Ch. {lo} - {hi})` with a Chapters link
  `/law/iowaCode/chapters?title={ROMAN}&year={YEAR}`.
- VERIFIED example: `Title I - STATE SOVEREIGNTY AND MANAGEMENT (Ch. 1 - 38D)`.

### Chapter listing page

- Lists each chapter as `Chapter {N} - {NAME}` with a Sections link
  `sections?codeChapter={N}&year={YEAR}` and a PDF link
  `/docs/code/{YEAR}/{N}.pdf`.
- Supports lettered chapters (`1A`, `7G`) — VERIFIED.
- RESERVED chapters (e.g. `Chapter 6 - RESERVED`) are ordinary rows —
  VERIFIED (16 reserved chapters in Title I).

### Section listing page

- Lists each section as `&#167;{section} - {catchline}.` with a PDF link
  `/docs/code/{YEAR}/{chapter}.{section}.pdf` (the raw page uses the
  numeric entity `&#167;` for the section sign).
- Supports lettered sections (VERIFIED: `1.15A` in Chapter 1).
- A RESERVED chapter's section listing is an **empty table body** —
  VERIFIED (Chapter 6).

### Section PDF

- Returns a real PDF (`Content-Type: application/pdf`; VERIFIED on several
  sections). Fetched with the shared `fetch_bytes` (raw bytes, never
  UTF-8-decoded) and extracted with the shared `extract_pdf_text`.
- **PDF text structure (VERIFIED)**:
  - Header line: `{title number} {TITLE NAME}, §{citation}` (e.g.
    `1 SOVEREIGNTY AND JURISDICTION OF THE STATE, §1.1`).
  - Citation + catchline line: `{citation}  {catchline}.` (e.g.
    `1.1  State boundaries.`).
  - Body: the operative statute text (numbered subsections preserved as
    `1.`, `a.`, `(1)`, etc.).
  - Codification history: one or more bracketed lines
    (`[C51, §1; R60, §1; ...]`).
  - Acts amendment lines (e.g. `2009  Acts,  ch  41, §1`).
  - Cross-reference note (e.g. `Referred to in §1.2`).
  - Generated footer (`{date}  Iowa Code {year}, Section {section} ({a}, {b})`).
- **IMPORTANT extraction note (VERIFIED)**: the Iowa Code's section PDFs
  position every word as its own separately-placed text operation, which
  makes pypdf's default extraction collapse to one word per line. The
  shared `extract_pdf_text` was enhanced (in the B14 milestone) to detect
  this fragmentation and re-extract that page in pypdf layout mode,
  restoring the visual line structure (emitted bottom-up, so reversed).
  Kentucky's PDFs are not affected (they extract cleanly in default mode).

### Repealed sections

- **VERIFIED**: a repealed section is simply **absent** — it is omitted
  from the section listing AND its PDF URL returns a genuine **HTTP 404**
  (VERIFIED: `§4.16` and `§4.17`, both historically repealed, return 404
  and are absent from Chapter 4's listing).
- Repealed behavior therefore needs no special stub handling: a
  repealed/absent section maps to `RefNotFoundError`.

### Reserved chapters

- **VERIFIED**: a RESERVED chapter (e.g. Chapter 6) exists in the chapter
  listing but its section listing is EMPTY (an empty table body).
- `list_sections` on a reserved chapter returns an empty sequence (not an
  error).

## Citation

- `Iowa Code § {chapter}.{local}` (e.g. `Iowa Code § 1.1`,
  `Iowa Code § 1.15A`).
- `raw_citation` is that form, adapter-constructed from the verified
  section identifier (which the PDF itself declares).

## Encoding

Discovery pages: UTF-8 HTML (shared `fetch_url`). Section documents: binary
PDFs fetched as raw bytes via `fetch_bytes`.

## Error boundary

- **Repealed/absent section PDF → HTTP 404 (VERIFIED)** → `RefNotFoundError`.
- **Nonexistent chapter PDF → HTTP 404 (VERIFIED)**.
- **Nonexistent chapter's section listing → HTTP 200 with empty table body
  (VERIFIED)** — the adapter validates the chapter exists before listing.
- **Invalid year → HTTP 200 with empty listing (VERIFIED)** — the server
  ignores the invalid year; discovery on an empty listing is handled by the
  caller's empty-result checks.
- Network failures (URLError/Timeout/OSError) → `AdapterUnavailableError`
  via the shared fetch helpers.

## Adapter behavior

- `list_titles` parses the 16 titles from the root page.
- `list_chapters(title_ref)` resolves the year, fetches the chapter listing
  for the title, and returns one chapter per row (including lettered and
  RESERVED chapters).
- `list_sections(chapter_ref)` resolves the year, fetches the section
  listing, and returns one section per `&#167;{citation} - {catchline}`
  row. A RESERVED chapter returns an empty sequence.
- `build_url` resolves the current year where needed: `TitleRef` → the root
  URL, `ChapterRef` → the section-listing page, `SectionRef` → the PDF URL.
- `retrieve_section(ref)` resolves the year, fetches the raw PDF bytes with
  `fetch_bytes`, extracts text with `extract_pdf_text`, cross-checks the
  PDF's declared citation against `ref`, parses the text into a
  `ParsedDocument`, and calls `normalize`.
- `status` is always `UNKNOWN` (repealed sections are absent entirely;
  there is no structural signal to read).

## Fixture provenance

All `tests/fixtures/ia_*` files are **real** verbatim captures of the
official host, fetched live on Aug 23, 2026. They are NOT synthetic.

| Fixture | Page / URL |
|---------|------------|
| `ia_root.html` | `https://www.legis.iowa.gov/law/iowaCode` |
| `ia_chapters_titleI.html` | `chapters?title=I&year=2026` |
| `ia_chapters_titleXV.html` | `chapters?title=XV&year=2026` |
| `ia_sections_ch1.html` | `sections?codeChapter=1&year=2026` |
| `ia_sections_ch633.html` | `sections?codeChapter=633&year=2026` |
| `ia_sections_invalid_chapter.html` | `sections?codeChapter=9999&year=2026` (real bad-chapter fallback) |
| `ia_section_1.1.pdf` | `docs/code/2026/1.1.pdf` (normal section) |
| `ia_section_1.15A.pdf` | `docs/code/2026/1.15A.pdf` (lettered section) |
| `ia_section_656.2.pdf` | `docs/code/2026/656.2.pdf` (multi-page section, 2 pages) |
| `ia_chapter6_reserved.pdf` | `docs/code/2026/6.pdf` (RESERVED chapter) |

## Known limitations

1. **Only a few chapters/sections live-captured** — whether every
   chapter/section page and PDF renders identically is otherwise
   UNVERIFIED.
2. **2026 was the current Code year at capture time** — the dynamic year
   derivation follows the root page; if the site changes the year's
   encoding, discovery will surface it as a parsing failure (documented
   loudly by the adapter's error messages).
3. **Layout-mode extraction artifacts** — the Iowa PDFs' per-word
   positioning means extracted text has double-space artifacts (normalized
   by the adapter) and occasional joined words (e.g. cross-references like
   `Referredtoin§1.2`); parsing is robust to both.
4. **Cross-title retrieval** relies on the chapter number being globally
   sufficient (the section listing is keyed by chapter + year only, which
   is how the official site works).

## Architecture impact

**One shared-utility enhancement, no framework change.** Iowa is the second
PDF-family adapter and reuses the shared binary-fetch (`fetch_bytes`) and
PDF-extraction (`extract_pdf_text`) infrastructure. The B14 milestone
enhanced `extract_pdf_text` with a fragmentation-triggered layout-mode
fallback (see `_pdftext.py`'s module docstring) to handle per-word-positioned
PDFs like Iowa's; existing PDF consumers (Kentucky, the synthetic infra
fixture) are byte-identical because their extraction never triggers the
fallback. No change to `BaseStateAdapter`, the refs, models, registry,
`server_tools.py`, or the exception hierarchy. All Iowa-specific behavior
(discovery, year resolution, PDF parsing) lives inside `IowaAdapter`.