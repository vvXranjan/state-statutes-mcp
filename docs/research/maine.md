# Maine Statute Source Research

Research performed: Aug 15, 2026, by direct requests to the official
Maine Legislature site (`legislature.maine.gov`) — no third-party
sources. Every URL below was executed live against the real host; raw
HTML responses were captured and inspected.

## Status

**VERIFIED** for the core discovery and retrieval paths: title listing
(the statutes homepage), chapter listing (the title contents page),
section listing (the chapter TOC page), section retrieval with heading,
body, and SECTION HISTORY, the per-section-page title/chapter
cross-check anchors, lettered title/chapter/section identifiers, and
HTTP 404 not-found behavior for a missing title, chapter, and section.

**UNVERIFIED** for a small set of secondary questions (formal rate-limit
policy, whether every one of the 64 titles' contents page renders
identically, whether repealed sections always carry a `right_nav_repealed`
class in their chapter listing, and the exact markup of every section
page). Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://legislature.maine.gov/statutes/` — the official Maine
  Legislature publication of the Maine Revised Statutes (M.R.S.).
  VERIFIED.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering, no JavaScript dependency for the content.
  VERIFIED (a bare `curl` GET returns the full statute HTML).

## Accessibility

- Reachable from this environment over plain HTTPS GET. VERIFIED.
- No authentication, no API key, no cookies required. All requests were
  plain `curl` GETs and succeeded. VERIFIED.
- No explicit rate limiting observed across repeated rapid requests.
  UNVERIFIED that no policy exists.
- Stable, deterministic URL paths — one file per title, per chapter, and
  per section (see URL Structure below). VERIFIED.

## Hierarchy

Three structural levels, exactly matching the framework:

- **Title** — top level. 64 titles, e.g. `1` ("GENERAL PROVISIONS"),
  `17-A` ("MAINE CRIMINAL CODE"), `34-B` ("ENERGY"). Lettered titles
  carry a `-A`/`-B`/`-C` suffix (25 of 64 are lettered). VERIFIED from
  the statutes homepage.
- **Chapter** — grouping within a title, e.g. `1` (Title 17-A,
  "PRELIMINARY"). Chapters may carry a letter suffix (Title 17-A lists
  `54-A` … `54-G`). VERIFIED from the Title 17-A contents page (52
  chapters).
- **Section** — the individually retrievable unit, e.g. `2` (Title 17-A,
  "Definitions"). Section identifiers may carry a letter suffix (`4-A`,
  `9-A`, `19-A`) or a numeric dash suffix (`18-1`). VERIFIED from the
  Chapter 1 TOC page (26 sections).

The citation is `{title} M.R.S. § {section}` (e.g. `17-A M.R.S. § 2`).
VERIFIED — this is the standard form used across Maine legal
publications; the site itself renders the number as `17-A §2` and the
page `<title>` as `Title 17-A, §2: Definitions`.

## URL Structure

VERIFIED (all four executed live):

- **Title list (homepage)**: `https://legislature.maine.gov/statutes/homepage.html`.
  Lists all 64 titles as
  `<li class="right_nav"><a href="1/title1ch0sec0.html">TITLE 1: GENERAL PROVISIONS</a></li>`.
  The title identifier is the directory prefix of the href; the label is
  `TITLE {id}: {name}`.
- **Title contents (chapter list)**: `https://legislature.maine.gov/statutes/{title}/title{title}ch0sec0.html`
  (e.g. `.../17-A/title17-Ach0sec0.html`). Lists every chapter of the
  title as
  `<div class="MRSChapter_toclist "><a href="./title17-Ach1sec0.html">Chapter 1: PRELIMINARY</a> §1 - §19-A</div>`,
  grouped under presentation-only
  `<h2 class="heading_part">Part 1: GENERAL PRINCIPLES</h2>` headings
  (flattened; Parts are not a structural level).
- **Chapter TOC (section list)**: `https://legislature.maine.gov/statutes/{title}/title{title}ch{chapter}sec0.html`
  (e.g. `.../17-A/title17-Ach1sec0.html`). Lists every section of the
  chapter as
  `<div class="MRSSection_toclist "><a href="./title17-Asec2.html">17-A §2. Definitions</a> </div>`.
  Repealed sections use `<div class="MRSSection_toclist right_nav_repealed">`
  with `(REPEALED)` in the link text (e.g. §5 "Pleading and proof (REPEALED)").
- **Section**: `https://legislature.maine.gov/statutes/{title}/title{title}sec{section}.html`
  (e.g. `.../17-A/title17-Asec2.html`). One file per section.

The sidebar of every page carries `../homepage.html` and `search.htm`
links plus, on chapter/section pages, `./title{title}ch0sec0.html`
("Title {title} Contents") and per-chapter `Ch. {n} PDF`/`MS-Word`
links (`./title{title}ch{n}.pdf` / `.docx`). The chapter regexes below
are anchored to `ch{n}sec0.html` (never `ch0sec0.html` or `.pdf`) and
the section regexes to `sec{n}.html`, so this chrome is excluded.

## Discovery

1. **Titles**: fetch `homepage.html`; for each `href="{id}/title{id}ch0sec0.html"`
   (backreference ensures the directory prefix equals the file prefix),
   identifier = `{id}`, name = label with the leading `TITLE {id}: `
   stripped. VERIFIED: 64 titles, including 25 lettered (`7-A`, `13-A`,
   `13-B`, `13-C`, `17-A`, `18-A` … `18-C`, `19-A`, `20-A`, `21-A`,
   `22-A`, `24-A`, `28-A`, `28-B`, `29-A`, `30-A`, `34-A`, `34-B`,
   `35-A`, `37-A`, `37-B`, `39-A`, `9-A`, `9-B`).
2. **Chapters**: fetch the title contents page; for each
   `./title{title}ch{chapter}sec0.html` link (excluding `ch0sec0.html`),
   identifier = `{chapter}`, name = label with the leading
   `Chapter {n}: ` stripped. VERIFIED for Title 17-A: 52 chapters,
   including lettered `54-A` … `54-G`.
3. **Sections**: fetch the chapter TOC page; for each
   `./title{title}sec{section}.html` link, identifier = `{section}`,
   name = label with the leading `{title} §{n}. ` stripped. VERIFIED for
   Chapter 1 of Title 17-A: 26 sections, including lettered `4-A`,
   `4-B`, `9-A`, `10-A`, `13-A`, `15-A`, `19-A` and the dashed `18-1`
   (whose label reads `17-A §18.` — the URL file is `sec18-1.html`).
   Repealed sections keep their `(REPEALED)` marker in the link text
   (e.g. §5, §10, §11).

## Retrieval

- Format: **server-rendered HTML over HTTPS, plain GET, no auth.**
  VERIFIED.
- The retrieval unit is the individual section page:
  `.../title{title}sec{section}.html`. VERIFIED.
- Section page structure (VERIFIED for § 2, § 5, and § 18-1):
  - **Cross-check anchors**: `<div class="MRSTitle toc">Title 17-A:
    MAINE CRIMINAL CODE</div>` and `<div class="MRSChapter toc">Chapter
    1: PRELIMINARY</div>` appear before the section content — a
    framework-strong title/chapter cross-check point.
  - **Heading**: `<h3 class="heading_section">§2. Definitions</h3>`
    (whitespace/newlines inside the tag; strip to `§2. Definitions`,
    then strip the leading `§{n}. ` to get `Definitions`).
  - **Body**: one or more `<div class="mrs-text ...">` blocks
    (paragraphs) and `<div class="MRSSubSection">` blocks
    (numbered subsections with `<span class="headnote">` labels),
    ending just before the history block. Inline
    `<span class="bhistory">[PL 1975, c. 499, §1 (NEW).]</span>` spans
    appear inside paragraphs; they are per-paragraph amendment notes and
    are dropped from the body (their content is consolidated in the
    SECTION HISTORY).
  - **History**: `<div class="qhistory">SECTION HISTORY
    <div class="qhistory_list"><span class="hist_chapter">PL 1975, c.
    499, §1 (NEW). PL 1975, c. 740, §11 (AMD). ...</span></div></div>`
    — the consolidated amendment chain, preservable verbatim as
    `amendment_notes`.
  - **Repealed sections** (e.g. § 5) replace the body with
    `<div class="headnote_blip">(REPEALED)</div>` and still carry a
    `qhistory` SECTION HISTORY. The page's `MRSSection status_current`
    class is present even on a repealed section, so repeal is signaled
    only in the listing (`right_nav_repealed`) and in the
    `(REPEALED)` blip/text — prose-level, so `status` stays `UNKNOWN`
    under the framework's rule.
- **Source URL** — the section page URL used, e.g.
  `https://legislature.maine.gov/statutes/17-A/title17-Asec2.html`.

## Status / repeal signal

The framework forbids inferring status from prose. Maine marks repeal in
two prose/class-level places: the chapter-listing link text carries
`(REPEALED)` and the section page body is the text `(REPEALED)` inside a
`headnote_blip` div, while the section page's own `MRSSection` class
reads `status_current` regardless. No reliable structural signal exists
at retrieval scope, so `status` stays `UNKNOWN`. (Same conclusion as
South Dakota, whose `Repealed` boolean proved unreliable.)

## Error behavior

- A nonexistent section (`title17-Asec9999.html`) returns HTTP 404.
  VERIFIED.
- A nonexistent chapter (`title17-Ach999sec0.html`) returns HTTP 404.
  VERIFIED.
- A nonexistent title (`title999ch0sec0.html`) returns HTTP 404.
  VERIFIED.
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).
- HTTP 404 maps to `RefNotFoundError`; other failures to
  `AdapterUnavailableError`.

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools
(`list_states`, `list_titles`, `list_chapters`, `list_sections`,
`get_section`) expose Maine with **no signature changes**:

- `TitleRef.identifier` = the title number including any letter suffix
  (e.g. `"17-A"`).
- `ChapterRef.identifier` = the chapter number (e.g. `"1"`, `"54-A"`).
- `SectionRef.identifier` = the section number as it appears in the URL
  (e.g. `"2"`, `"4-A"`, `"18-1"`). The section page URL carries only
  title + section, so `get_section(state_code="ME", title="17-A",
  chapter="1", section="2")` round-trips cleanly.
- The M.R.S. is a current-code source; no edition/year enters the refs
  or the citation.

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `MaineAdapter` in
  `src/state_statutes_mcp/adapters/maine/adapter.py`.
- **Base URL**: `BASE_URL = "https://legislature.maine.gov"`; statutory
  pages under `/statutes/`. URLs:
  - Titles: `{BASE}/statutes/homepage.html`.
  - Title contents (chapters): `{BASE}/statutes/{title}/title{title}ch0sec0.html`.
  - Chapter TOC (sections): `{BASE}/statutes/{title}/title{title}ch{chapter}sec0.html`.
  - Section: `{BASE}/statutes/{title}/title{title}sec{section}.html`.
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: fetch homepage; parse `{id}/title{id}ch0sec0.html`
  links; identifier = `{id}`, name = label minus `TITLE {id}: ` prefix;
  sort numerically.
- **`list_chapters(title_ref)`**: fetch title contents page; parse
  `./title{title}ch{chapter}sec0.html` links (exclude `ch0sec0.html`);
  identifier = `{chapter}`, name = label minus `Chapter {n}: ` prefix;
  sort numerically. 404 → `RefNotFoundError`.
- **`list_sections(chapter_ref)`**: fetch chapter TOC page; parse
  `./title{title}sec{section}.html` links; identifier = `{section}`,
  name = label minus `{title} §{n}. ` prefix; sort numerically. 404 →
  `RefNotFoundError`.
- **`retrieve_section(ref)`**: build the section URL; fetch; cross-check
  the page's `MRSTitle toc`/`MRSChapter toc` text against `ref`
  (`RefMismatchError` on mismatch); parse heading from `heading_section`,
  body from the region between the heading and the `qhistory` block
  (dropping `bhistory` spans), amendment_notes from `hist_chapter`;
  build `ParsedDocument` with `raw_citation = f"{title} M.R.S. §
  {ref.identifier}"`, `source_url` = the section URL; call `normalize`.
  404 → `RefNotFoundError`; a located section with an empty body →
  `NormalizationError`.
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-Maine refs (`NormalizationError`); require `ref.identifier`
  in `parsed.raw_citation` (`RefMismatchError` on mismatch); `status`
  stays `UNKNOWN`; populate `citation`, `heading`, `text`,
  `amendment_notes`, `source_url`, `retrieved_at`.
- **Citation handling**: `{title} M.R.S. § {id}`, adapter-constructed,
  cross-checked in `normalize`.
- **History handling**: the `hist_chapter` SECTION HISTORY chain verbatim
  into `amendment_notes` (raw text, per the framework's contract — no
  parsing).
- **Error mapping**: network failure → `AdapterUnavailableError`;
  HTTP 404 (bad title/chapter/section) → `RefNotFoundError`; empty body
  → `NormalizationError`; citation disagreement → `RefMismatchError`;
  wrong ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: `Title → Chapter → Section` maps 1:1 onto
  `TitleRef → ChapterRef → SectionRef` with no flattening.

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete (no abstract methods); `state_code
   == "ME"`; `state_name == "Maine"`.
2. **URL construction** — title contents/chapter TOC/section URLs;
   unsupported ref type raises `UnsupportedRefError`.
3. **Title discovery** — real homepage fixture → 64 titles, numeric
   order, lettered titles (`17-A`) preserved, names stripped of the
   `TITLE {id}: ` prefix; no titles → `AdapterUnavailableError`.
4. **Chapter discovery** — real title-contents fixture → numeric-order
   chapters with names; lettered chapters (`54-A`); 404 →
   `RefNotFoundError`; network failure → `AdapterUnavailableError`.
5. **Section discovery** — real chapter TOC fixture → 26 sections with
   names; lettered (`4-A`) and dashed (`18-1`) identifiers; `(REPEALED)`
   preserved in names; 404 → `RefNotFoundError`.
6. **Retrieval** — real § 2 fixture: citation `17-A M.R.S. § 2`, heading
   `Definitions`, body text, SECTION HISTORY in `amendment_notes`,
   `source_url`, status UNKNOWN. Real § 5 (repealed) fixture: body
   `(REPEALED)`, history preserved.
7. **Cross-checks** — `MRSTitle toc` mismatch → `RefMismatchError`;
   `MRSChapter toc` mismatch → `RefMismatchError`.
8. **Citation parsing** — `17-A M.R.S. § 2` round-trips through
   `normalize`; state mismatch → `NormalizationError`; citation mismatch
   → `RefMismatchError`.
9. **Normalization** — populated `StatuteSection` fields; empty-body
   section → `NormalizationError`.
10. **Reference mismatch** — `SectionRef` for a different section vs the
    located page → `RefMismatchError`/`RefNotFoundError` as appropriate.
11. **Malformed source** — section page missing heading/history → parsed
    as far as possible or `NormalizationError`; malformed listing →
    `AdapterUnavailableError`.
12. **Missing section** — valid title/chapter, absent section → 404 →
    `RefNotFoundError`.
13. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
14. **Real-source fixture** — the captured official pages under
    `tests/fixtures/maine_*` exercised through discovery and retrieval.
15. **MCP `get_section` integration** — a `MaineAdapter` registered in an
    `AdapterRegistry` served through `server_tools.get_section` returns
    the expected dict shape.

## Known Limitations

- The body is extracted by slicing between the heading and the history
  block, then tag-stripping with paragraph breaks; inline `bhistory`
  per-paragraph amendment notes are dropped because their content is
  consolidated in the SECTION HISTORY.
- The `18-1` section is identified by its URL file suffix (`18-1`) even
  though its chapter listing label reads `17-A §18.`; the citation
  therefore uses the URL-identifier (`17-A M.R.S. § 18-1`). This is a
  site-file-naming quirk, documented rather than normalized.
- Whether every title's contents page and every section page render
  identically is UNVERIFIED (sampled Title 17-A and its Chapters 1/5/18);
  `NormalizationError` guards against a shape change.
- The citation `M.R.S.` abbreviation is INFERENCE from standard Maine
  citation usage; the number itself (`17-A §2`) is VERIFIED from the
  site's own headings.

## Framework Compatibility

ARCHITECTURAL CONCLUSION: no framework changes are required. The
three-level `TitleRef → ChapterRef → SectionRef` model fits exactly, and
all five abstract methods plus the adapter-owned `retrieve_section` are
implementable against the server-rendered HTML with no changes to
`BaseStateAdapter`, the ref models, the registry, or the MCP tools.
The per-section-page HTML retrieval model is the same family as
`WashingtonAdapter` (one HTML file per section) but with Maine's own
markup and identifiers, so no shared parser is warranted.

## Risks

- If the site changes its `<h3 class="heading_section">` / `qhistory`
  markup, parsing fails loudly (`NormalizationError`), never silently.
- The section/repealed listing markers (`right_nav_repealed`,
  `(REPEALED)`, `(REALLOCATED ...)`) are preserved in listing names but
  not used for status inference, keeping the adapter honest about the
  framework's no-prose-status rule.
- The 404 boundary is verified for missing title/chapter/section; other
  server error codes are UNVERIFIED but map to
  `AdapterUnavailableError` by the shared fetch helper.
