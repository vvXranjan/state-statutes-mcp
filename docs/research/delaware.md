# Delaware Statute Source Research

Research performed: Aug 14, 2026, by direct requests to the official
Delaware Code site (`delcode.delaware.gov`) — no third-party sources.
Every endpoint below was executed live against the real host; raw HTML
responses were captured and inspected.

## Status

**VERIFIED** for the core discovery and retrieval paths (home/title
listing, chapter listing, subchapter listing, section retrieval by
anchor, not-found behavior, PDF availability, history text). All were
exercised against the live official host.

**UNVERIFIED** for a small set of secondary questions (rate-limit
policy, exact reserved/range-section markup, title-level chapter counts
outside Title 11); those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://delcode.delaware.gov/` — the official Delaware Code,
  maintained by the Delaware Code Revisors with the editorial staff of
  LexisNexis in cooperation with the Division of Legislative Services of
  the General Assembly. The Title 11 PDF explicitly describes itself as
  "an official version of the State of Delaware statutory code."
  VERIFIED.
- Both an HTML browse and per-title "Authenticated PDF" are served.
  VERIFIED.

## Accessibility

- Reachable from this environment over plain HTTPS GET. VERIFIED.
- **No authentication, no API key, no cookies required.** All requests
  below were plain `curl` GETs with no headers and succeeded. VERIFIED.
- Stable numeric/alpha-addressable paths (`title11/c005/sc01/index.html`).
  VERIFIED.
- No `robots.txt` exclusion relevant to the paths used was observed.
  UNVERIFIED (not specifically checked).

## Hierarchy

Four structural levels exist, but only three are addressable/citable:

- **Title** — top level, e.g. `11` (Crimes and Criminal Procedure).
  VERIFIED.
- **Chapter** — grouping within a title, e.g. `5`. Addressable as
  `/title{N}/cXXX/index.html` (padded, `c005`). Chapters can carry a
  letter suffix (e.g. `c084a`, `c087a`). VERIFIED.
- **Subchapter** — grouping within a chapter, e.g. `sc01`–`sc07` under
  c005. Addressable as `/title{N}/cXXX/scYY/index.html`. Carries no
  number of its own in the citation. VERIFIED.
- **Section** — the addressable unit. Addressable only as an anchor
  (`id="501"`) inside a subchapter or chapter document — there is no
  per-section URL. VERIFIED.

Note: **not every chapter has subchapters.** c001 renders sections
directly on the chapter page (`id="101"`, `102`, `103`) with no
subchapters, while c005 splits into `sc01`–`sc07`. VERIFIED. An adapter
must handle both shapes.

## Title Listing

- `GET /` (or `/index.shtml`) returns the home page listing all titles.
  VERIFIED.
- **31 titles** are listed. VERIFIED.
- Each title entry has two links:
  - `https://delcode.delaware.gov/title{N}/index.html` (HTML browse).
  - `https://delcode.delaware.gov/title{N}/title{N}.pdf` (Authenticated
    PDF). VERIFIED.
- Title numbering is not fully contiguous in URL form (e.g. `c084a`,
  `c087a` under Title 11) but titles themselves are sequential 1–31.
  VERIFIED for the home listing.

## Chapter Listing

- `GET /title{N}/index.html` lists the chapters of a title. VERIFIED for
  Title 11.
- Chapter links are of the form `/title11/c001/index.html` ... `/title11/c087a/index.html`.
  VERIFIED. Note the **zero-padded three-digit** chapter id, with letter
  suffixes for inserted chapters.
- Title 11 page also links the "Authenticated PDF" (`../Title11.pdf`).
  VERIFIED.

## Subchapter Structure

- `GET /title{N}/cXXX/index.html` lists either subchapters **or**
  sections directly:
  - c005 → links `sc01/index.html` … `sc07/index.html`; **no inline
    sections**. VERIFIED.
  - c001 → no subchapter links; sections `id="101"`, `102`, `103`
    rendered inline. VERIFIED.
- A chapter's subchapters are addressed as `/title11/c005/scYY/index.html`.
  VERIFIED.

## Section Retrieval

- **Sections are NOT individually addressable by URL.** A direct request
  such as `/title11/c005/sc01/501.html` returns **HTTP 404**. VERIFIED.
- The retrieval unit is the **subchapter document** (or the chapter
  document when the chapter has no subchapters). Sections appear inline
  as:
  ```html
  <div class="SectionHead" id="501">
            §
          501. Criminal solicitation in the third degree; class A misdemeanor.</div>
            <p class="subsection">A person is guilty of criminal solicitation ...</p>
            <p class="subsection">Criminal solicitation in the third degree is a class A misdemeanor.</p>
  11 Del. C. 1953, § 501; <a href="...">58 Del. Laws, c. 497, § 1</a>; ...
  ```
  VERIFIED for § 501.
- To retrieve one section, an adapter must: resolve which containing
  document (chapter vs subchapter page) holds the section, fetch that
  document, and match the `SectionHead` id anchor. The anchor id is the
  bare section number. VERIFIED.
- Section numbers are **unique within a title** (observed `101`–`103`,
  `201`–`284`, `301`–`308`, `401`–`477`, `501`–`542`, `601`–`613`
  across several Title 11 chapters with no collisions). VERIFIED for the
  sampled chapters; treating `SectionRef.identifier` as the bare section
  number is therefore safe. INFERENCE that this holds for all chapters.

## Citation Format

- Delaware's citation is `11 Del. C. § 501` — Title, "Del. C.", section
  number. The section number is the anchor id. VERIFIED.
- **Subchapter is not part of the citation.** The section number embeds
  the title but not the chapter or subchapter. VERIFIED for § 501.

## Body Structure

- Each section is headed by a `SectionHead` div containing the section
  number and title.
- Body paragraphs are `<p class="subsection">` elements — one per
  subsection. VERIFIED.
- Section blocks are wrapped in a `Section` div; a `<br>` separates
  adjacent sections. VERIFIED.
- There is **no separate heading/title field distinct from the
  `SectionHead` text**; heading = the `SectionHead` inner text with the
  `§` and number removed. INFERENCE from observed markup.

## History / Amendment Information

- Each section block ends with an inline amendment-history chain whose
  entries are hyperlinks to the General Assembly session laws, e.g.:
  `11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1; 67 Del. Laws, c. 130, § 8; 70 Del. Laws, c. 186, § 1;`
  VERIFIED for § 501.
- The history lives in **plain text within the section document**, not a
  structured field. VERIFIED.
- This maps naturally onto the framework's `ParsedDocument.amendment_notes`
  (raw history text). The distinguishing prefix pattern
  (`\d+ Del. Laws, c. \d+`) or the leading `11 Del. C. 1953, § 501;`
  can be used to separate history from body. INFERENCE on the exact
  regex; the trailing-history layout itself is VERIFIED.

## Version / Current-Code Behavior

- The Title 11 PDF front matter states: "This version includes all acts
  enacted as of July 21, 2026, up to and including ...". VERIFIED.
- The HTML browse and PDF are assumed to track the same current code.
  INFERENCE — the two were not cross-diffed section-by-section.
- No explicit per-section version/effective-date field was observed
  beyond the amendment chain. VERIFIED as observed; a structured
  effective-date field is UNVERIFIED to exist.

## Not-Found Behavior

- **Invalid chapter:** `/title11/c999/index.html` → **HTTP 404**.
  VERIFIED.
- **Direct section URL:** `/title11/c005/sc01/501.html` → **HTTP 404**
  (because sections have no URL). VERIFIED.
- A section number that does not exist inside a valid subchapter/chapter
  document simply has **no matching `SectionHead` id** — HTTP 200 with no
  match, so the adapter must raise `RefNotFoundError` itself when no
  anchor matches. INFERENCE from the 404-absent design (no per-section
  error page exists by construction).
- Reserved/range sections: earlier probing noted id values that are
  ranges (e.g. `id="504-510"` with `[Reserved.]` body). UNVERIFIED in
  this session's samples; should be handled defensively (a range id is
  not a retrievable section).

## Pagination

- **No pagination observed.** Each listing (home, title, chapter,
  subchapter) is a single self-contained HTML page. VERIFIED for all
  pages fetched.

## Authentication

- None. All requests are anonymous GETs. VERIFIED.

## Rate Limits

- No rate-limit headers or 429 responses were observed during this
  session. UNVERIFIED whether a formal policy exists; treat as an
  unknown with a polite default (small delay, caching).

## Representative Verified URLs

- Home: `https://delcode.delaware.gov/` — 31 titles. VERIFIED.
- Title 11: `https://delcode.delaware.gov/title11/index.html` — chapter
  list incl. `c001`, `c005`, `c084a`, `c087a`. VERIFIED.
- Title 11 PDF: `https://delcode.delaware.gov/title11/Title11.pdf` — 496
  pages, text-extractable, PDF 1.4. VERIFIED.
- Chapter 5 (with subchapters): `https://delcode.delaware.gov/title11/c005/index.html`
  — `sc01`–`sc07`, no inline sections. VERIFIED.
- Chapter 1 (no subchapters): `https://delcode.delaware.gov/title11/c001/index.html`
  — sections `101`, `102`, `103` inline. VERIFIED.
- Subchapter 1 of Chapter 5: `https://delcode.delaware.gov/title11/c005/sc01/index.html`
  — sections `501`–`542` inline. VERIFIED.
- Subchapter 2 of Chapter 5: `https://delcode.delaware.gov/title11/c005/sc02/index.html`
  — sections `601`–`613`. VERIFIED.
- Not-found chapter: `https://delcode.delaware.gov/title11/c999/index.html` → 404.
  VERIFIED.

## Verified Findings

- Official, anonymous, server-rendered HTML; no auth. VERIFIED.
- Hierarchy Title → Chapter → (Subchapter) → Section, with sections
  embedded as `SectionHead` anchors inside a subchapter or chapter
  document. VERIFIED.
- No per-section URL exists; sections are retrieved by fetching the
  containing document and matching the anchor id. VERIFIED.
- Citation `11 Del. C. § NNN`, section number = anchor id, unique within
  a title. VERIFIED for sampled chapters.
- Chapters may or may not have subchapters; both shapes observed.
  VERIFIED.
- Dual representation: HTML browse + per-title Authenticated PDF
  (text-extractable). VERIFIED.
- Amendment history is an inline trailing chain with session-law links.
  VERIFIED.
- Invalid chapter → HTTP 404. VERIFIED.
- No pagination, no auth, no API key. VERIFIED.

## Unverified Findings

- Whether a formal rate-limit policy exists.
- Exact reserved/range-section markup (`id="504-510"` `[Reserved.]`)
  across all chapters; only the earlier probe indicated it.
- Whether section-number uniqueness within a title holds for *every*
  chapter (sampled chapters only).
- Whether the HTML and PDF representations are byte-identical in content.
- Chapter-name display strings on the title page (not extracted in this
  session).

## Architectural Inference

- Section retrieval requires a two-step resolution: (1) find the
  containing document for a section number, (2) extract by anchor. Since
  subchapter membership is not part of the citation, the adapter must
  either walk the chapter's subchapter pages (list subchapters → fetch
  each → match anchor) or maintain a section→container index. For the
  small subchapter counts observed (≤7) the walk is cheap. INFERENCE.
- The subchapter level is a **presentation/discovery grouping with no
  citable identity**, directly comparable to Virginia's Article/SubPart
  levels (which are also flattened) and Texas's internal title headings.
  INFERENCE.

## Framework Compatibility

**Question: Can Delaware be implemented without modifying the existing
core framework?**

**Answer: Yes.** No change to `BaseStateAdapter`, the ref models, the
registry, or the MCP tools is required. Analysis:

- **`BaseStateAdapter`** — the five abstract methods are all
  implementable:
  - `list_titles` → parse home page title links.
  - `list_chapters(title_ref)` → parse `/title{N}/index.html` chapter
    links.
  - `list_sections(chapter_ref)` → parse the chapter page; if it lists
    subchapters, walk each subchapter page collecting `SectionHead` ids;
    if it has inline sections, collect them directly.
  - `build_url(ref)` → return the containing document URL for
    section/chapter/title refs (the anchor is applied post-fetch).
  - `normalize(parsed, ref)` → map heading/body/history into
    `StatuteSection`.
  - `retrieve_section(ref)` (required by the MCP `get_section` tool, not
    by the base class) → resolve containing document, fetch, extract the
    anchor block.
- **`TitleRef`/`ChapterRef`/`SectionRef`** — identifiers are opaque
  strings. `TitleRef.identifier="11"`, `ChapterRef.identifier="5"` (from
  `c005`; letter suffix retained, e.g. `"84a"`), `SectionRef.identifier="501"`.
  VERIFIED that the models place no format constraint beyond non-empty
  strings.
- **Registry / MCP tools** — `get_section` and the listing tools only
  call the contract methods; they need no changes. The registry gains a
  `"DE"` → `DelawareAdapter` entry exactly as Virginia's was added.

The fourth level (Subchapter) is fully absorbed as an **adapter-internal
discovery/retrieval detail**; no model slot is needed because the
subchapter carries no citable identity. This is the same flattening
pattern already proven by Virginia (Article/SubPart) and Texas (internal
title headings), now exercised over a genuine four-level source.

## Proposed Adapter Design

- `DelawareAdapter` in `src/state_statutes_mcp/adapters/delaware/adapter.py`,
  implementing the two identity properties and five abstract methods plus
  `retrieve_section`.
- `build_url`:
  - `TitleRef` → `https://delcode.delaware.gov/title{N}/index.html`.
  - `ChapterRef` → `https://delcode.delaware.gov/title{N}/c{NNN}/index.html`
    (zero-pad to 3 digits; preserve letter suffix).
  - `SectionRef` → the chapter page URL of its parent chapter (retrieval
    then walks subchapters if present). Anchor matching is applied to the
    fetched document, not the URL.
- `list_titles` → parse home page `title{N}/index.html` links.
- `list_chapters` → parse title page `cNNN.../index.html` links; strip
  leading zeros and lowercase the letter suffix for the identifier.
- `list_sections` → fetch the chapter page; if subchapter links exist,
  fetch each and collect `SectionHead` id anchors; else collect them from
  the chapter page directly.
- `retrieve_section` → fetch the parent chapter page; if it lists
  subchapters, fetch each subchapter page until the section's
  `SectionHead` id is found; parse the block (heading + `p.subsection`
  body + trailing history chain); raise `RefNotFoundError` if no
  containing document has the anchor.
- `normalize` → heading from `SectionHead` text; body joined from
  `p.subsection` elements; `amendment_notes` from the trailing
  `\d+ Del. Laws, c. \d+` / `Del. C. \d+, §` chain; `status` left
  default (source provides no structural status) or inferred from
  `[Repealed]`/`[Reserved]` markers if present (UNVERIFIED markup).
- Listing helpers (`parse_sections_from_document`) shared between
  `list_sections` and `retrieve_section` to avoid duplicated parsing
  logic.

## Risks

- **Section→container resolution:** subchapter membership is not in the
  citation; retrieval must walk subchapter pages. Small counts make this
  cheap, but a pathological chapter with many subchapters would multiply
  requests. Mitigation: document order, small fetch set, later caching.
- **Mixed chapter shapes:** some chapters inline sections, others use
  subchapters; `list_sections`/`retrieve_section` must branch on shape.
- **Reserved/range ids:** an `id="504-510"` `[Reserved.]` block is not a
  retrievable section; the adapter must exclude range ids from listings
  and treat them as not-found on retrieval.
- **Zero-padding and letter suffixes:** chapter URL ids are padded
  (`c005`) and may carry suffixes (`c084a`); identifier↔URL conversion
  must be exact in both directions.
- **Duplicate/malformed markup** across titles is plausible; `normalize`
  must raise `NormalizationError` on unexpected structure rather than
  silently emit garbage.
- **Live-source drift:** the site is current as of July 21, 2026;
  section numbers and URLs could change with future revisor activity.
  Inherent to any live source.

## Test Strategy

- Live-fixture tests for `list_titles` (31 entries), `list_chapters`
  (Title 11 chapter links incl. `c084a`/`c087a`), `list_sections` for a
  subchapter-based chapter (c005) and an inline chapter (c001).
- Retrieval test for § 501 (heading "Criminal solicitation in the third
  degree; class A misdemeanor", 2 subsections, history chain starting
  `11 Del. C. 1953, § 501;`).
- `build_url` round-trip tests incl. padding (`5` ↔ `c005`) and letter
  suffix (`84a` ↔ `c084a`).
- Not-found: `RefNotFoundError` for a valid chapter with no matching
  anchor; HTTP-404 surfaced as the appropriate adapter error for a bad
  chapter.
- Reserved-range id exclusion test.
- `normalize` tests for heading extraction, body joining, history split.
- Mirror the existing suite's real-source mock pattern used by
  Washington/Texas/Illinois/Virginia tests.

## Acceptance Criteria

1. `DelawareAdapter` implements all five abstract methods + identity
   properties + `retrieve_section`, matching the contract of the other
   four adapters.
2. `list_titles` returns 31 titles with real names.
3. `list_chapters("11")` returns Title 11 chapters including lettered
   ones.
4. `list_sections` handles both chapter shapes (inline vs subchapter).
5. `retrieve_section("11","5","501")` returns heading, body, and history
   matching the verified § 501 content.
6. `RefNotFoundError` on missing sections; HTTP 404 mapped to the
   adapter's error contract.
7. `build_url` round-trips padding and letter suffixes.
8. Full suite remains green (existing 82 passed / 1 skipped), with new
   Delaware tests added following the established mock pattern.
9. No changes to `BaseStateAdapter`, refs, registry, server, or MCP
   tools.

## Recommendation

**Proceed with Delaware as State #5.** It is the first adapter whose
sections live inside a container document and are addressed by explicit
anchor boundaries — a genuinely new retrieval model for the framework —
and it does so through the existing three-level contract with the
fourth level flattened as an adapter-internal detail. Every core finding
above is VERIFIED against the live official source, and the remaining
UNVERIFIED items are implementation-level details, not framework
blockers.