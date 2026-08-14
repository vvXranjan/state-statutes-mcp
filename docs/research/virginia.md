# Virginia Statute Source Research

Research performed: Aug 14, 2026, by direct requests to the official
Virginia Law portal (`law.lis.virginia.gov`) — no third-party sources.
Every endpoint below was executed live against the real host; raw JSON
responses were captured and inspected.

## Status

**VERIFIED** for the core retrieval path (titles, chapters, sections,
section details) — all four endpoints were exercised against the live
official host and returned real, well-formed JSON.

**PARTIALLY VERIFIED** for a small number of secondary questions
(exact semantics of `SectionText`, version-parameter behavior, whether
the duplicate-title rows are stale); those are flagged below and were
not resolved.

## Official Source

- Portal: `https://law.lis.virginia.gov/` — official Code of Virginia
  site, run by the Division of Legislative Automated Systems (DLAS).
- Developers page: `https://law.lis.virginia.gov/developers/` — VERIFIED
  to state that "RESTful web services are available in both JSON and
  XML" for the Code of Virginia, Constitution, and related documents.
- Operations documentation (JSON): `https://law.lis.virginia.gov/jsonapi/` —
  VERIFIED. This page lists the operations for the Code of Virginia
  (among others) but its listed URIs are relative; the real working
  base path is `/api/` (see Retrieval Mechanism).
- An XML equivalent exists (`/xmlapi/`), not exercised — the JSON API
  is sufficient.

No authentication is required: **all requests below succeeded with a
plain GET and no API key.** VERIFIED. (The separately-advertised LIS
API-key registration on `lis.virginia.gov` gates the session/bill-data
APIs, not the law portal's Code endpoints.)

## Retrieval Mechanism

- Format: **JSON over HTTPS, plain GET, no auth.** VERIFIED.
- Base URL: `https://law.lis.virginia.gov/api/`. VERIFIED — the
  operations page at `/jsonapi/` renders `href` targets under `/api/`
  (e.g. `/api/CoVTitlesGetListOfJson`), and those resolve to real JSON.
- **Trailing slash is required.** VERIFIED — a path without a trailing
  slash returns HTTP 301 to the same path with a slash; with the slash
  it returns `application/json`.
- Content-Type: `application/json; charset=utf-8`. VERIFIED.
- One request returns one logical unit (all titles; all chapters of one
  title; all sections of one chapter; one section). VERIFIED — no
  streaming, no chunking observed.
- **No pagination.** VERIFIED — a large chapter (Title 18.2, Chapter 4,
  129 sections) returned in a single 24 KB response with no paging or
  truncation fields.
- HTTP status is not a reliable error signal for "section not found":
  a nonexistent or malformed section number returns **HTTP 200** with
  `{"TitleNumber":null,"TitleName":null,"ChapterList":[]}`. VERIFIED.
- A `?version=YYYY` query parameter was tested but the response payload
  was byte-identical in size to the no-parameter request; whether
  versioning is actually honored is **UNVERIFIED**. Assume the default
  response is the current Code.

## Hierarchy

The Code of Virginia has more than three structural levels, but only
three are addressable by the API, and the deeper ones are presentation
grouping only:

- **Title** — the top level, `TitleNumber` (e.g. `1`, `18.2`, `2.2`,
  `8.01`, `8.1A`). Dotted and lettered title numbers exist. VERIFIED.
- **Chapter** — a grouping *within* a title, `ChapterNum` (e.g. `1`,
  `4`). Chapters are listed per title. VERIFIED.
- **Section** — the addressable unit, `SectionNumber`. VERIFIED.
- **Below chapter the API nests `Article` → `SubPart` → `SectionList`**
  in the section-listing response (plus `Subtitle`/`Part` fields that
  are empty in observed responses). VERIFIED — these intermediate
  levels carry no number of their own in the flat section records and
  are **not** part of any section's address or citation. They are
  presentation grouping only, comparable to Texas's unmodeled internal
  "TITLE 5" heading. Sections remain directly addressable by their flat
  `SectionNumber`.

## Listing / Discovery

### Titles

- `GET /api/CoVTitlesGetListOfJson/`
- Response: a JSON array of `{"TitleNumber", "TitleName", "ChapterList":null}`.
  VERIFIED.
- **80 titles** returned; `TitleName` examples: `1` → "General
  Provisions", `66` → "Juvenile Justice". VERIFIED.
- **Data quirk: duplicate `TitleNumber` rows.** VERIFIED — four title
  numbers appear twice each (`8.2`, `8.2A`, `8.4A`, `54.1`), with
  cosmetically different `TitleName` values (e.g. "Commercial Code —
  Sales" vs "Commercial Code - Sales"; em-dash vs hyphen). The titles
  list therefore cannot be returned verbatim; an adapter must
  deduplicate on `TitleNumber`.

### Chapters

- `GET /api/CoVChaptersGetListOfJson/{titleNumber}/`
- Response: `{"TitleNumber", "TitleName", "ChapterList":[{"ChapterNum","ChapterName"}]}`.
  VERIFIED.
- Chapter numbers can themselves be dotted (e.g. Title 1 lists chapters
  `1`, `2`, `2.1`, `3`, ...). VERIFIED.
- **Order is lexicographic, not numeric.** VERIFIED — Title 18.2's
  chapters come back as `1, 10, 11, 12, 13, 2, 3, ... 9`. An adapter
  that wants numeric order must re-sort (as `IllinoisAdapter` already
  does for its section listing).

### Sections

- `GET /api/CoVSectionsGetListOfJson/{titleNumber}/{chapterNumber}/`
- Response: a nested object
  `{"TitleNumber","TitleName","SubtitleNum","SubtitleName","PartNum","PartName","ChapterNum","ChapterName","ArticleList":[{"ArticleNum","ArticleName","SubPartList":[{"SubPartNum","SubPartName","SectionList":[{"SectionRange","SectionNumber","SectionTitle"}]}]}]}`.
  VERIFIED.
- One request returns **every section in the chapter** (129 sections for
  Title 18.2 Chapter 4). VERIFIED. No pagination.
- An adapter must flatten all three nesting levels (Article → SubPart →
  Section) into a flat sequence of `TocNode`.

## Section Retrieval

- `GET /api/CoVSectionsGetSectionDetailsJson/{sectionNumber}/`
- Response: `{"TitleNumber","TitleName","ChapterList":[{"SubtitleNum","SubtitleName","PartNum","PartName","ChapterNum","ChapterName","SubPartNum","SubPartName","ArticleNum","ArticleName","SectionRange","SectionNumber","SectionTitle","SectionText","Body"}]}`.
  VERIFIED.
- **One request returns exactly one section** (the `ChapterList` array
  contains a single element). VERIFIED.
- The section is keyed by `SectionNumber` alone (the flat citation such
  as `1-1` or `18.2-51`) — **title and chapter are not needed to fetch
  a section**, and chapter does not appear in the section number.
  VERIFIED.
- "Not found" is signaled by an empty `ChapterList` with HTTP 200, not
  by an HTTP 404. VERIFIED.

## Citation Format

- Virginia's citation is `Va. Code Ann. § {TitleNumber}-{SectionWithinTitle}`,
  e.g. `§ 18.2-51` = Title 18.2, section 51; `§ 1-1` = Title 1, section 1.
  VERIFIED — matches the API's `SectionRange` field verbatim
  (`§ 1-1`, `§ 18.2-51`).
- **Chapter is not part of the citation.** The section number embeds the
  title but not the chapter. VERIFIED.
- Section numbers may carry a decimal suffix (e.g. `18.2-76.2`).
  VERIFIED.

## Body / History Format

- `Body` is **HTML** containing one `<p>` per paragraph. VERIFIED.
- Observed `Body` layout (identical for both representative sections):
  1. The statute text (one or more `<p>`).
  2. A final history/citation paragraph, e.g. `Code 1950, § 18.1-65;
     1960, c. 358; 1975, cc. 14, 15.` or `Code 1919, § 1; R. P. 1948,
     § 1-1.` — VERIFIED. This is the raw amendment-history text the
     framework's `ParsedDocument.amendment_notes` expects.
  3. A recurring `<p class='sidenote'>` caveat ("The chapters of the
     acts of assembly referenced in the historical citation ... may not
     constitute a comprehensive list of such chapters ..."). VERIFIED in
     both samples.
- `SectionText` was `null` in every observed section detail response.
  VERIFIED as observed; whether it is ever populated is **UNVERIFIED**.
  `Body` is authoritative.
- There is **no structured history field**; history lives in prose at
  the end of `Body`. VERIFIED.
- The framework's `strip_tags` helper with `preserve_block_breaks=True`
  turns the `<p>`-delimited HTML into `\n\n`-separated paragraphs,
  which is enough to split text vs history via a content pattern
  (e.g. a paragraph beginning `Code \d+` / `Acts \d+` / `R. P. \d+`).

## Representative Section

Full trace, all steps executed live against the official host:

1. **Title** — `GET /api/CoVTitlesGetListOfJson/` →
   `{"TitleNumber":"1","TitleName":"General Provisions",...}`. VERIFIED.
2. **Chapter** — `GET /api/CoVChaptersGetListOfJson/1/` →
   `{"ChapterNum":"1","ChapterName":"CODE OF VIRGINIA",...}`. VERIFIED.
3. **Section listing** — `GET /api/CoVSectionsGetListOfJson/1/1/` →
   `SectionRange` `§ 1-1`, `SectionNumber` `1-1`, `SectionTitle`
   "Contents and designation of Code". VERIFIED.
4. **Section detail** — `GET /api/CoVSectionsGetSectionDetailsJson/1-1/`
   →
   `{"TitleNumber":"1","ChapterList":[{"ChapterNum":"1",...,"SectionNumber":"1-1","SectionRange":"§ 1-1","SectionTitle":"Contents and designation of Code","Body":"<p>The laws embraced in this and the following titles, chapters, articles and sections ...</p><p>Code 1919, § 1; R. P. 1948, § 1-1.&nbsp;</p><p class='sidenote'>The chapters of the acts of assembly ...</p>"}]}`.
   VERIFIED.

Second representative section confirmed: `18.2-51` (Title 18.2
"Crimes and Offenses Generally", Chapter 4 "Crimes Against the Person",
heading "Shooting, stabbing, etc., with intent to maim, kill, etc",
Body opening "If any person maliciously shoot, stab, cut, or wound any
person ..."). VERIFIED.

## Existing Model Compatibility

Mapping onto the framework's three-level ref model — VERIFIED to fit:

- `TitleRef.identifier` = `TitleNumber` (e.g. `1`, `18.2`).
- `ChapterRef.identifier` = `ChapterNum` (e.g. `1`, `4`).
- `SectionRef.identifier` = `SectionNumber` (e.g. `1-1`, `18.2-51`) —
  already the full citation, used directly by the section-detail
  endpoint (mirrors how `WashingtonAdapter` treats
  `SectionRef.identifier` as the full citation).
- `TocNode.name` = `TitleName` / `ChapterName` / `SectionTitle` — real
  display names available at every level (unlike Illinois's
  placeholders).
- The intermediate Article/SubPart levels do **not** need a model slot:
  they carry no addressable number and are flattened away during
  `list_sections`, exactly as Texas's internal title grouping is.

## Verified Findings

- Official, documented, public JSON API at `law.lis.virginia.gov/api/`
  (operations documented at `/jsonapi/`, developers page at
  `/developers/`). No auth.
- Four operations cover the full framework surface:
  `CoVTitlesGetListOfJson`, `CoVChaptersGetListOfJson/{title}`,
  `CoVSectionsGetListOfJson/{title}/{chapter}`,
  `CoVSectionsGetSectionDetailsJson/{section}`.
- Trailing slash required; JSON responses are flat and pagination-free.
- Section fetch is a single request returning exactly one section, keyed
  by the flat citation; title/chapter not needed for retrieval.
- Citation format `§ {title}-{section}`; chapter excluded from citations.
- Body is HTML `<p>` paragraphs; history is a trailing prose paragraph.
- Real display names available at all three levels.
- Not-found (and malformed) section numbers return HTTP 200 with an
  empty `ChapterList`.

## Unverified Findings

- Whether `SectionText` is ever populated (null in all observed samples).
- Whether `?version=` is honored (request returned an identical-size
  payload); assume current Code.
- Whether the four duplicate `TitleNumber` rows are stale-data artifacts
  (both values observed were cosmetically identical; dedup-on-number is
  safe either way).
- Exact behavior of the chapters/sections endpoints for a chapter or
  title that does not exist (observed only for a nonexistent *section*).
- Whether every `Body`'s final paragraph is the history line with no
  exceptions (two samples verified; section bodies that are entirely
  repealed/blank were not checked).

## Risks

- **Empty-list-on-200 pattern:** the adapter must not treat HTTP 200 as
  success for section retrieval — it must check `ChapterList` and raise
  `RefNotFoundError` (semantically: the section no longer resolves) on
  an empty list. `NormalizationError` is the alternative for consistency
  with existing adapters' `retrieve_section`; the implementation task
  should pick one and document it.
- **Duplicate title rows:** returning the titles list verbatim would
  produce duplicate `TocNode` identifiers. Must dedup on `TitleNumber`.
- **Lexicographic chapter ordering:** listings are not numeric-sorted;
  tests must not assume a sorted order, and the adapter may re-sort.
- **Version drift:** the API serves the current Code; a future Code
  edition could change `TitleNumber`/`SectionNumber` addressing. This is
  inherent to any live source and matches how the other adapters behave.
- **No 404 semantics:** any error-mapping logic keyed on HTTP status will
  silently misbehave; the response body is the source of truth.

## Adapter Design Implications

- `build_url` for a `SectionRef` uses `ref.identifier` directly →
  `/api/CoVSectionsGetSectionDetailsJson/{identifier}/`; for a
  `ChapterRef` → `/api/CoVSectionsGetListOfJson/{title}/{chapter}/`;
  for a `TitleRef` → `/api/CoVChaptersGetListOfJson/{title}/` (the
  per-title chapters listing). Titles listing has its own endpoint.
- `list_titles` must dedup duplicate `TitleNumber` rows (keep-first,
  mirroring `IllinoisAdapter`'s `seen` dict).
- `list_chapters` returns `ChapterList` items as `TocNode`; optionally
  numeric-sort `ChapterNum` (lexicographic by default from the API).
- `list_sections` must flatten `ArticleList[] → SubPartList[] →
  SectionList[]` into a flat `TocNode` sequence.
- `retrieve_section`:
  - fetch the section-detail JSON,
  - treat an empty `ChapterList` as not-found (raise `RefNotFoundError`
    or `NormalizationError`),
  - use `SectionTitle` as heading, `SectionRange` as the citation raw,
  - clean `Body` with `strip_tags(preserve_block_breaks=True)` and split
    the last history paragraph (content pattern `Code \d+` / `Acts \d+` /
    `R. P. \d+`) into `amendment_notes`.
- `normalize` can cross-check the ref chain against the response's
  `TitleNumber` and `ChapterNum` (stronger than a substring check,
  analogous to `IllinoisAdapter`'s three-part cross-check) plus the
  `SectionNumber` ↔ `ref.identifier` agreement.
- This is the framework's **first JSON-consuming adapter** — a new
  structural axis (JSON parse instead of HTML scrape) exercised through
  the exact same `BaseStateAdapter` contract.

## Recommendation

**Virginia is a strong State #4 candidate — proceed.** It is the first
adapter that consumes a documented public **JSON API** rather than
scraped HTML, which is a genuinely new source pattern for the framework,
and it does so through the existing `TitleRef → ChapterRef → SectionRef`
model with **no additional hierarchy level required**. Section retrieval
is a single clean request returning exactly one section. The only
verification-sensitive details (empty-list-on-200, duplicate titles,
lexicographic ordering) are fully characterized above and are adapter
implementation concerns, not framework blockers.