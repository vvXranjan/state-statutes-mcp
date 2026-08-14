# Florida Statute Source Research

Research performed: Aug 14, 2026, by direct requests to the official
Florida Senate site (`flsenate.gov`) — no third-party sources. Every
endpoint below was executed live against the real host; raw HTML
responses were captured and inspected.

## Status

**VERIFIED** for the core discovery and retrieval paths (title listing,
chapter listing, chapter `/All` section document, section-anchor
structure, history text, edition-year availability, no-per-section-URL
behavior). All were exercised against the live official host.

**UNVERIFIED** for a small set of secondary questions (rate-limit
policy, exact 404 markup for a nonexistent chapter, whether every
chapter's `/All` document renders identically, per-section effective
dates in the `/All` document); those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://www.flsenate.gov/Laws/Statutes/` — the official
  Florida Senate publication of the Florida Statutes (the site
  redirects `https://www.flsenate.gov/Statutes` here). VERIFIED.
- Server-rendered HTML throughout (jQuery for presentation only; no SPA
  framework, no client-side statute rendering). VERIFIED.
- The Florida Statutes are published as distinct **per-year editions**;
  the site's edition selector offers 1997–2027, and
  `/Laws/Statutes/2026`, `/2025`, `/2024`, `/2023` all return HTTP 200.
  The site's default edition is 2025. VERIFIED.

## Accessibility

- Reachable from this environment over plain HTTPS GET. VERIFIED.
- **No authentication, no API key, no cookies required.** All requests
  were plain `curl` GETs with a browser User-Agent and succeeded.
  VERIFIED.
- No explicit rate limiting observed across repeated rapid requests.
  UNVERIFIED that no policy exists.
- Stable, deterministic paths: `/Laws/Statutes/{year}/Title{N}`,
  `/Laws/Statutes/{year}/Chapter{N}`, `/Laws/Statutes/{year}/Chapter{N}/All`.
  VERIFIED.

## Hierarchy

Three structural levels, exactly matching the framework:

- **Title** — top level, e.g. `1`–`49`. Addressable as
  `/Laws/Statutes/{year}/Title{N}` (e.g. `/Title46`, whose name is
  "CRIMES"). VERIFIED. Display markup:
  `<span id="Title1" class="title">Title I</span><span class="descript">CONSTRUCTION OF STATUTES </span>`.
- **Chapter** — grouping within a title, e.g. `775` (Title 46,
  "GENERAL PENALTIES; REGISTRATION OF CRIMINALS"). Addressable as
  `/Laws/Statutes/{year}/Chapter{N}`. VERIFIED. Display markup:
  `<a href=".../Chapter775"><span class="chTitle">Chapter 775</span>
  <span class="chDescript">- GENERAL PENALTIES; ...</span></a>`.
  Chapter numbers are plain integers (no letter suffixes observed).
- **Section** — the addressable unit, numbered `chapter.section`, e.g.
  `775.01`, `775.011`, `775.012`. Addressable **only as an anchor**
  inside the chapter's `/All` document — there is no per-section page.
  VERIFIED: a request to
  `/Laws/Statutes/2025/Chapter775/Section775.01` **redirects to the
  statutes root** (`/Laws/Statutes/2025`), and the fetched body is a
  navigation shell with no statute text.

The **edition year** is a fourth dimension, but it is a publication
dimension, not a structural level: it does not appear in the citation
and carries no citable identity, so it is resolved as an adapter-internal
constant rather than mapped onto any ref level (see Design).

## Discovery

All three levels are enumerated from server-rendered HTML — no
JavaScript, no API:

1. **Titles**: the home page (`/Laws/Statutes/`) lists 49 titles as
   `/Laws/Statutes/{year}/Title{N}` links, sorted numerically. VERIFIED.
2. **Chapters**: a title page (e.g. `/Laws/Statutes/2025/Title46`) lists
   that title's chapters as `/Laws/Statutes/{year}/Chapter{N}` links with
   names. VERIFIED (49 chapter links observed on the Title 46 page).
3. **Sections**: a chapter page (e.g. `/Laws/Statutes/2025/Chapter775`)
   is a navigation shell linking to the chapter's `/All` document
   (`<a class="wholeChp" href=".../Chapter775/All">`). The `/All`
   document contains every section inline. VERIFIED.

## Retrieval

- Format: **HTML over HTTPS, plain GET, no auth.** VERIFIED.
- The retrieval unit is the **chapter `/All` document**:
  `/Laws/Statutes/{year}/Chapter{chapter}/All`. VERIFIED.
- Sections are matched as anchors within that document. Each section is
  one `<div class="Section">` block (55 such blocks in Chapter 775's
  `/All`, VERIFIED):

  ```html
  <div class="Section">
    <span class="SectionNumber">775.01&#x2003;</span>
    <span class="Catchline"><span class="CatchlineText">Common law of England.</span><span class="EmDash">&#x2014;</span></span>
    <span class="SectionBody"><span class="Text Intro Justify">The common law of England ...</span></span>
    <div class="History"><span class="HistoryTitle">History.</span><span class="EmDash">&#x2014;</span><span class="HistoryText">s. 1, Nov. 6, 1829; s. 1, Feb. 10, 1832; RS 2369; GS 3194; RGS 5024; CGL 7126.</span></div>
  </div>
  ```

  VERIFIED. Multi-paragraph sections carry `<div class="Subsection">`
  blocks inside `SectionBody`. VERIFIED.

This is a **document-embedded-anchor** retrieval model at chapter scope:
the second instance of that pattern in the framework (Delaware embeds
sections in chapter/subchapter documents and matches `SectionHead`
anchors; Florida embeds sections in the chapter `/All` document and
matches `SectionNumber` spans). The block-splitting approach proven by
`DelawareAdapter._block_for_section` (split on `<div class="Section">`)
applies directly.

## Parsing

For one retrieved chapter `/All` document, each section block yields:

- **Citation** — constructed by the adapter, `s. {chapter.section},
  Fla. Stat.` (e.g. `s. 775.01, Fla. Stat.`). The `/All` document itself
  prints cross-references as `s. 775.082`; the canonical citation form
  is `s. N, Fla. Stat.`. VERIFIED for the cross-reference form; the
  full canonical form is INFERENCE (the site's own index/PDF uses
  `775.01 Fla. Stat.`).
- **Heading/catchline** — `CatchlineText`, e.g. "Common law of England."
  VERIFIED.
- **Body** — `SectionBody` (strip tags; subsections joined), e.g. "The
  common law of England in relation to crimes, ... shall be of full
  force in this state ...". VERIFIED.
- **History/amendments** — `HistoryText`, e.g. "s. 1, Nov. 6, 1829;
  s. 1, Feb. 10, 1832; RS 2369; ..." — preserved verbatim as
  `amendment_notes`. VERIFIED.
- **Effective date/version** — the edition year is present in the URL
  but not printed per section. Per-section effective dates were not
  observed in the `/All` document (UNVERIFIED that none exist); the
  framework stores history as raw text and `status` stays `UNKNOWN`
  (no repealed/amended structural marker observed).
- **Source URL** — the chapter `/All` URL.

## Error behavior

- A nonexistent chapter returns HTTP 404 (INFERENCE — only valid
  chapters were fetched; the Delaware site's analogous 404 was VERIFIED,
  and Florida's router returns 200-shells for valid-but-empty routes).
- A section number with no matching `SectionNumber` anchor in the
  chapter `/All` document is simply absent — the adapter raises
  `RefNotFoundError` itself (INFERENCE, mirroring the verified Delaware
  anchor-absence behavior).
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools
(`list_states`, `list_titles`, `list_chapters`, `list_sections`,
`get_section`) expose Florida with **no signature changes**:

- `TitleRef.identifier` = title number (`"1"`…`"49"`).
- `ChapterRef.identifier` = chapter number (`"775"`).
- `SectionRef.identifier` = full section number (`"775.01"`), which
  already carries the chapter — the same convention
  `WashingtonAdapter` (`49.60.010`) and `TexasAdapter` (`19.01`) use,
  so `get_section(state_code="FL", title="46", chapter="775",
  section="775.01")` round-trips cleanly.
- The edition year never enters the refs or the citation; it is an
  adapter-internal URL constant.

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `FloridaAdapter` in
  `src/state_statutes_mcp/adapters/florida/adapter.py`.
- **URL strategy**: `BASE_URL = "https://www.flsenate.gov"`; a
  `DEFAULT_YEAR` constant pinned to the site's current published edition
  (VERIFIED default `"2025"`; `"2026"` also serves). URLs:
  - Title: `/Laws/Statutes/{year}/Title{title}`.
  - Chapter: `/Laws/Statutes/{year}/Chapter{chapter}`.
  - Section: `/Laws/Statutes/{year}/Chapter{chapter}/All` — the chapter
    document that holds the section anchor (mirrors Delaware: no
    per-section URL).
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: fetch the home page; parse `/Title{N}` links;
  identifier = `N`; name from `descript` (strip trailing space) with
  `Title {roman}` fallback; dedupe keep-first; sort numerically.
- **`list_chapters(title_ref)`**: fetch `/Title{title}`; parse
  `/Chapter{N}` links; identifier = chapter number; name =
  `chDescript` with leading `- ` stripped; dedupe; sort numerically.
  HTTP 404 → `RefNotFoundError`.
- **`list_sections(chapter_ref)`**: fetch the chapter `/All` document;
  split on `<div class="Section">`; for each block take the
  `SectionNumber` as identifier and `CatchlineText` as name; dedupe on
  `SectionNumber`; sort numerically. HTTP 404 → `RefNotFoundError`;
  no blocks found → `AdapterUnavailableError`.
- **`retrieve_section(ref)`**: build the chapter `/All` URL; fetch;
  split into blocks; locate the block whose `SectionNumber` equals
  `ref.identifier`; parse `CatchlineText` (heading), `SectionBody`
  (body), `HistoryText` (amendment_notes); build `ParsedDocument` with
  `raw_citation = f"s. {ref.identifier}, Fla. Stat."`, `source_url` =
  the `/All` URL; call `normalize`. Anchor absent → `RefNotFoundError`;
  located block with an empty body (e.g. a repealed/struck section that
  renders no body) → `NormalizationError` (the same empty-body
  convention Virginia and Delaware use).
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-Florida refs (`NormalizationError`); require
  `ref.identifier` in `parsed.raw_citation` (`RefMismatchError` on
  mismatch); `status` stays `UNKNOWN` (no structural status marker
  observed); populate `citation`, `heading`, `text`,
  `amendment_notes`, `source_url`, `retrieved_at`.
- **Citation handling**: `s. {chapter.section}, Fla. Stat.`,
  adapter-constructed, cross-checked in `normalize`.
- **History handling**: `HistoryText` verbatim into `amendment_notes`
  (raw text, per the framework's contract — no parsing).
- **Error mapping**: network failure / invalid-JSON-in-HTML →
  `AdapterUnavailableError`; chapter 404 → `RefNotFoundError`;
  section anchor absent → `RefNotFoundError`; empty body →
  `NormalizationError`; citation disagreement → `RefMismatchError`;
  wrong ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: year is adapter-internal (URL-only);
  `Title → Chapter → Section` maps 1:1 onto
  `TitleRef → ChapterRef → SectionRef` with no flattening.

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete (no abstract methods); `state_code
   == "FL"`; `state_name == "Florida"`.
2. **URL construction** — title/chapter/section URLs including the
   pinned year; section URL is the chapter `/All` page; unsupported ref
   type raises `UnsupportedRefError`.
3. **Title discovery** — home page fixture → 49-title-style numeric
   order; dedupe; name extraction; no-title-links →
   `AdapterUnavailableError`; network failure → `AdapterUnavailableError`.
4. **Chapter discovery** — title fixture → numeric chapter order;
   name extraction (leading `- ` stripped); chapter 404 →
   `RefNotFoundError`; network failure → `AdapterUnavailableError`.
5. **Section discovery** — chapter `/All` fixture → ordered
   `SectionNumber` identifiers; multi-subsection sections; 404 →
   `RefNotFoundError`; no blocks → `AdapterUnavailableError`.
6. **Retrieval** — full `retrieve_section` for a simple section and a
   multi-subsection section (heading, body, history, source_url,
   citation, status UNKNOWN); chapter 404 → `RefNotFoundError`; missing
   anchor → `RefNotFoundError`; network failure → `AdapterUnavailableError`.
7. **Citation parsing** — `s. 775.01, Fla. Stat.` round-trips through
   `normalize`; state mismatch → `NormalizationError`; citation
   mismatch → `RefMismatchError`.
8. **Normalization** — populated `StatuteSection` fields; empty-body
   section → `NormalizationError`.
9. **Reference mismatch** — `SectionRef` for a different section vs the
   located block → `RefMismatchError`/`RefNotFoundError` as appropriate.
10. **Malformed source** — chapter page without `/All` link; `/All`
    with no `<div class="Section">`; malformed block without
    `SectionNumber` → `NormalizationError`/`AdapterUnavailableError`.
11. **Missing section** — valid chapter, absent section number →
    `RefNotFoundError`.
12. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
13. **Representative real-source fixture** — one chapter `/All`
    document captured from the live host (e.g. Chapter 775) saved under
    `tests/fixtures/`, exercised through discovery and retrieval.
14. **MCP `get_section` integration** — a `FloridaAdapter` registered
    in an `AdapterRegistry` served through `server_tools.get_section`
    returns the expected dict shape.

## Known Limitations

- The adapter must be updated deliberately when a new edition year is
  published (pinned `DEFAULT_YEAR`), mirroring how Virginia assumes "the
  current Code".
- Chapter `/All` documents are large (Chapter 775 ≈ 440 KB) and are
  fetched whole to reach one section — the same whole-document cost
  Delaware accepts.
- Section-number uniqueness within a chapter is INFERENCE beyond the
  sampled Chapter 775 (no duplicates observed).
- Whether every chapter's `/All` document renders identically is
  UNVERIFIED (sampled Chapter 775 only); `NormalizationError` guards
  against a shape change.