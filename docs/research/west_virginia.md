# West Virginia Statute Source Research

Research performed: Mar-May 2026 and Aug 15, 2026. The live host
(`https://code.wvlegislature.gov`) was NOT reachable from this
environment (it returned a 302 to a blocked page, then 403), so official
markup was captured via the Wayback Machine (`...id_/` snapshot form)
and inspected offline. Every URL below was executed against the captured
official pages; structure is documented verbatim from those captures,
which are the implementation boundary for this adapter.

## Status

**VERIFIED** for the core discovery and retrieval paths: top-level
chapter enumeration (the chapter `<select>` dropdown present on code
pages), article listing (the chapter page), section listing (the article
page), section retrieval with heading, body, and the per-section-page
chapter/article cross-check anchors. All verified from Wayback captures
of the official `code.wvlegislature.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: the live HTTP 404
behavior for a missing chapter/article/section, whether chapter and
article pages always render identically, and whether the home page's
chapter `<select>` is always present (the home capture lists only
Chapter 1's articles as content). Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://code.wvlegislature.gov/` — the official West Virginia
  Legislature publication of the West Virginia Code.
- The statutory text is plain server-rendered HTML (WordPress-based):
  no SPA framework, no client-side statute rendering. VERIFIED.
- Pages carry the site's own citation-style headings, e.g. `<h4>§11-21-12.
  West Virginia adjusted gross income of resident individual.</h4>` and
  meta description `§11-21-12. West Virginia adjusted gross income of
  resident individual.` VERIFIED.

## Accessibility

- Not reachable from this environment directly (302 redirect to a blocked
  page, then 403). UNVERIFIED what the live behavior is from other
  networks.
- Captures were obtained through web.archive.org snapshot URLs in the
  `...id_/` form; the archived pages are byte-faithful official markup.
- No authentication or API key; requests were plain GETs. VERIFIED from
  the captured pages' structure.

## Hierarchy

The West Virginia Code has NO title level: its structural hierarchy is
**Chapter → Article → Section**.

- **Chapter** — the top-level unit, e.g. `11` ("TAXATION"), `1` ("THE
  STATE AND ITS SUBDIVISIONS"), `5A` ("DEPARTMENT OF ADMINISTRATION").
  Chapters may carry a letter suffix (`5A`, `11B`, `60B`). VERIFIED from
  the chapter `<select>` dropdown (137/139 options).
- **Article** — grouping within a chapter, e.g. `21` (Chapter 11,
  "PERSONAL INCOME TAX"). Articles may carry a letter suffix (`1A`,
  `21A`). VERIFIED from the Chapter 11 page (102 article links).
- **Section** — the individually retrievable unit, e.g. `11-21-12`
  ("West Virginia adjusted gross income of resident individual").
  Section identifiers are the dotted `chapter-article-number` form
  (`11-21-12`), may carry a letter suffix (`11-21-3a`, `11-21-12a`),
  and match the URL path exactly. VERIFIED.

### Hierarchy mapping (MCP compatibility)

The framework models three levels (`Title → Chapter → Section`). West
Virginia has only two statutory levels above the section. To preserve the
MCP contract without inventing a fake title, the mapping is adapter-internal
and documented:

- **`TitleRef` ← WV Chapter** (the top-level code unit). Precedent:
  Texas's `TitleRef` maps to a code; the framework's refs docstring
  explicitly allows "top-level code/division".
- **`ChapterRef` ← WV Article** (the mid-level grouping).
- **`SectionRef` ← WV Section** (full dotted `11-21-12`).

Concretely: `get_section(state_code="WV", title="11", chapter="21",
section="11-21-12")` retrieves WV Chapter 11, Article 21, Section
11-21-12. `list_chapters(title_ref="11")` lists WV Articles of Chapter
11; `list_sections(chapter_ref="21")` lists the sections of Article 21.
This is honest to the source (no fabricated level) and requires no
framework change.

The citation form is `W. Va. Code § {section}` (e.g. `W. Va. Code §
11-21-12`). The `W. Va. Code` abbreviation is INFERENCE from standard West
Virginia citation usage (the site itself renders `§11-21-12.` in headings
and metadata); the `{section}` number is VERIFIED from the site's own
headings.

## URL Structure

VERIFIED (all executed against captured official pages):

- **Home / top-level enumeration**:
  `https://code.wvlegislature.gov/`. The page (a WordPress landing page
  listing Chapter 1's articles as content) carries a `<select
  id='sel-chapter'>` dropdown with all chapters, e.g.
  `<option value='1' selected>CHAPTER 1. THE STATE AND ITS
  SUBDIVISIONS.</option>` (139 options on the home capture). The chapter
  `<select>` is also present on every chapter/article/section page.
- **Chapter page (article list)**: `https://code.wvlegislature.gov/{chapter}/`
  (e.g. `/11/`). Contains a `<select id='sel-chapter'>` and a
  `results-box` listing articles as
  `<div class='art-head' id='ah-1'><a href='/11-1/'>ARTICLE 1. SUPERVISION.</a></div>`
  (102 article links for Chapter 11). Heading `<h3>CHAPTER 11. TAXATION.</h3>`.
- **Article page (section list)**:
  `https://code.wvlegislature.gov/{chapter}-{article}/` (e.g.
  `/11-21/`). Contains the chapter select, `<h3>CHAPTER 11. TAXATION.</h3>`,
  prev/next article links, an `art-head` div, and section links:
  `<div class='sec-head' data-id='ah-21'><a href='/11-21-1/'>§11-21-1.
  Legislative findings.</a></div>` (143 section links for Article 21,
  including lettered `11-21-3a` and `11-21-12a`).
- **Section**: `https://code.wvlegislature.gov/{section}/` (e.g.
  `/11-21-12/`). One page per section. VERIFIED.

## Discovery

1. **Chapters (top level)**: fetch the home page `/` (or any code page);
   parse the `<select id='sel-chapter'>` options. identifier = the option
   value (e.g. `"11"`, `"5A"`), name = the label with the `CHAPTER {n}. `
   prefix stripped. VERIFIED: 139 options on the home capture (including
   `1`, lettered `5A`-`5H`, `60A`, `60B`, and `49A`).
2. **Articles**: fetch `/{chapter}/`; parse the `art-head` links.
   identifier = the article URL segment (e.g. `"1"`, `"21"`, `"1A"`),
   name = the label with the `ARTICLE {n}. ` prefix stripped. VERIFIED for
   Chapter 11: 102 articles, including lettered `1A`, `1B`, `1C`.
3. **Sections**: fetch `/{chapter}-{article}/`; parse the `sec-head`
   links. identifier = the section URL segment (e.g. `"11-21-1"`,
   `"11-21-3a"`), name = the label with the `§{id}. ` prefix stripped.
   VERIFIED for Article 11-21: 143 sections, including lettered
   `11-21-3a` and `11-21-12a`.

## Retrieval

- Format: server-rendered HTML over HTTPS, plain GET, no auth. VERIFIED.
- The retrieval unit is the individual section page:
  `https://code.wvlegislature.gov/{section}/`. VERIFIED.
- Section page structure (VERIFIED for 11-21-12):
  - **Cross-check anchors**: the page carries a
    `<div id='chpsel-container' data-m='home' data-c='11' data-a='21' data-s='12' ...>`
    container exposing chapter/article/section codes, plus prev/next
    section divs carrying the same `data-c`/`data-a`/`data-s` attributes —
    a framework-strong chapter/article cross-check point. VERIFIED.
  - **Heading**: `<h4>§11-21-12. West Virginia adjusted gross income of
    resident individual.</h4>` — the first `<h4>` in the
    `<div class='sectiontext hid'>` body container. The leading `§{id}. `
    is stripped for the heading.
  - **Body**: the `<p>` paragraphs following the `<h4>` inside the
    `<div class='sectiontext hid'>` container (subsections `(a)`, `(b)`,
    ..., each with an em-dash lead-in). VERIFIED.
  - **History**: the site renders Bill History and Signed Bills as
    separate linked-out widgets (a `codeaffected` widget linking to
    `wvlegislature.gov` bill-status pages), NOT in the section body.
    VERIFIED. No in-body amendment history exists to capture.
- **Source URL** — the section page URL used, e.g.
  `https://code.wvlegislature.gov/11-21-12/`.

## Status / repeal signal

No structural status signal exists in the captured section pages (the
body container is plain text). `status` stays `UNKNOWN` under the
framework's rule. Repealed sections, if any, would render their repeal
annotation in the section listing name (like Vermont); UNVERIFIED for the
captured samples.

## Error behavior

- Live HTTP 404 for a missing chapter/article/section is UNVERIFIED (see
  Status). By convention, HTTP 404 maps to `RefNotFoundError` and other
  failures to `AdapterUnavailableError` via the shared fetch helper.
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).
- A located section with an empty body raises `NormalizationError`.

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools expose West Virginia
with **no signature changes**, using the Chapter→Title, Article→Chapter,
Section→Section mapping above. No framework changes are required.

- `TitleRef.identifier` = the WV chapter (e.g. `"11"`).
- `ChapterRef.identifier` = the WV article (e.g. `"21"`).
- `SectionRef.identifier` = the full WV section (e.g. `"11-21-12"`).

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `WestVirginiaAdapter` in
  `src/state_statutes_mcp/adapters/west_virginia/adapter.py`.
- **Base URL**: `BASE_URL = "https://code.wvlegislature.gov"`. URLs:
  - Home/chapters: `{BASE}/`.
  - Chapter page (articles): `{BASE}/{title}/`.
  - Article page (sections): `{BASE}/{title}-{chapter}/`.
  - Section: `{BASE}/{section}/`.
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: fetch `{BASE}/`; parse the `sel-chapter` options;
  identifier = option value, name = label minus `CHAPTER {n}. ` prefix;
  sort numerically.
- **`list_chapters(title_ref)`**: fetch `{BASE}/{title}/`; parse `art-head`
  links; identifier = article URL segment, name = label minus `ARTICLE {n}. `
  prefix; sort numerically.
- **`list_sections(chapter_ref)`**: fetch `{BASE}/{title}-{chapter}/`;
  parse `sec-head` links; identifier = section URL segment, name = label
  minus `§{id}. ` prefix; sort numerically.
- **`retrieve_section(ref)`**: build the section URL; fetch; cross-check
  the page's `data-c`/`data-a` container attributes against `ref`
  (`RefMismatchError` on mismatch); parse heading from the body `<h4>`,
  body from the `sectiontext hid` paragraphs (Bill History widget
  excluded); build `ParsedDocument` with `raw_citation = f"W. Va. Code §
  {ref.identifier}"`, `source_url` = the section URL; call `normalize`.
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-WV refs (`NormalizationError`); require `ref.identifier` in
  `parsed.raw_citation` (`RefMismatchError` on mismatch); `status` stays
  `UNKNOWN`; populate `citation`, `heading`, `text`, `amendment_notes`,
  `source_url`, `retrieved_at`.
- **Citation handling**: `W. Va. Code § {id}`, adapter-constructed
  (`W. Va. Code` INFERENCE; `{id}` VERIFIED from the site's headings),
  cross-checked in `normalize`.
- **History handling**: `amendment_notes` stays `None` — the source
  renders bill history as separate linked-out widgets, not in the body.
- **Error mapping**: network failure → `AdapterUnavailableError`; HTTP
  404 (bad chapter/article/section) → `RefNotFoundError`; empty body →
  `NormalizationError`; citation disagreement → `RefMismatchError`; wrong
  ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: WV `Chapter → Article → Section` maps onto
  framework `Title → Chapter → Section` as documented above.

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete; `state_code == "WV"`; `state_name
   == "West Virginia"`.
2. **URL construction** — home, chapter, article, and section URLs;
   unsupported ref type raises `UnsupportedRefError`.
3. **Chapter discovery (list_titles)** — real home fixture → all chapters
   from the select (139), names stripped of `CHAPTER {n}. `.
4. **Article discovery (list_chapters)** — real Chapter 11 fixture → 102
   articles with names; lettered `1A`.
5. **Section discovery (list_sections)** — real Article 11-21 fixture →
   143 sections; lettered `11-21-3a`; names stripped of `§{id}. `.
6. **Retrieval** — real 11-21-12 fixture: citation `W. Va. Code §
   11-21-12`, heading, body text, `amendment_notes is None`, `source_url`,
   status UNKNOWN.
7. **Cross-checks** — `data-c` mismatch → `RefMismatchError`; `data-a`
   mismatch → `RefMismatchError`.
8. **Citation parsing** — `W. Va. Code § 11-21-12` round-trips through
   `normalize`; state mismatch → `NormalizationError`; citation mismatch
   → `RefMismatchError`.
9. **Normalization** — populated `StatuteSection` fields; empty-body
   section → `NormalizationError`.
10. **Reference mismatch** — `SectionRef` for a different section vs the
    located page → `RefMismatchError`/`RefNotFoundError` as appropriate.
11. **Malformed source** — section page missing the container →
    `NormalizationError`; malformed listing → `AdapterUnavailableError`.
12. **Missing section** — valid chapter/article, absent section → 404 →
    `RefNotFoundError` (simulated).
13. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
14. **Real-source fixture** — the captured official pages under
    `tests/fixtures/west_virginia_*` exercised through discovery and
    retrieval.
15. **MCP `get_section` integration** — a `WestVirginiaAdapter` registered
    in an `AdapterRegistry` served through `server_tools.get_section`
    returns the expected dict shape.

## Known Limitations

- Live HTTP 404 behavior for missing chapters/articles/sections is
  UNVERIFIED (host unreachable from this environment); the not-found
  mapping follows the other-adapters convention and is simulated in tests.
- The home page's content is Chapter 1's articles; the top-level
  enumeration relies on the `sel-chapter` dropdown present on code pages
  (139 options captured on the home page).
- Whether every chapter/article/section page renders identically is
  UNVERIFIED (sampled Chapters 1/11 and Articles 11-21); `NormalizationError`
  guards against shape change.
- Bill history and signed bills are separate linked-out widgets and are
  intentionally not captured in `amendment_notes` (none exists in-body).

## Framework Compatibility

ARCHITECTURAL CONCLUSION: no framework changes are required. The
Chapter→Title / Article→Chapter / Section→Section mapping preserves the
MCP contract with the existing five tools, and all abstract methods plus
the adapter-owned `retrieve_section` are implementable against the
server-rendered HTML with no changes to `BaseStateAdapter`, the ref
models, the registry, or the MCP tools. This follows the Texas precedent
of mapping a top-level code onto `TitleRef`.

## Risks

- If the site changes its `sel-chapter` / `art-head` / `sec-head` /
  `sectiontext hid` markup, parsing fails loudly (`NormalizationError`),
  never silently.
- The `data-c`/`data-a`/`data-s` container attributes are the section
  page's cross-check anchor; if they are removed by a redesign, the
  adapter degrades to the body-heading-based cross-check.
- The citation `W. Va. Code` abbreviation is INFERENCE (standard West
  Virginia citation usage); the section number is VERIFIED from the
  site's own headings.
