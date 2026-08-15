# Vermont Statute Source Research

Research performed: Apr-May 2026 and Aug 15, 2026. The live host
(`https://legislature.vermont.gov`) was NOT reachable from this
environment (HTTPS timed out), so official markup was captured via the
Wayback Machine (`...id_/` snapshot form) and inspected offline. Every
URL below was executed against the captured official pages; structure is
documented verbatim from those captures, which are the implementation
boundary for this adapter.

## Status

**VERIFIED** for the core discovery and retrieval paths: title listing
(the statutes index page), chapter listing (the title page), section
listing (the chapter page, including subchapter markers, lettered
sections, and repealed-section annotations), section retrieval with
heading, body, trailing amendment history, and the per-section-page
title/chapter/subchapter cross-check anchors. All verified from Wayback
captures of the official `legislature.vermont.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: the live HTTP 404
behavior for a missing title/chapter/section, whether title and chapter
pages always render identically, and the exact markup of every section
page. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://legislature.vermont.gov/statutes/` — the official
  Vermont General Assembly publication of the Vermont Statutes Annotated
  (V.S.A.).
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically).
- Each page carries an explicit disclaimer: "The Vermont Statutes Online
  is an unofficial copy of the Vermont Statutes Annotated that is
  provided as a convenience." VERIFIED — this is the official source's
  own caveat and is preserved here as a known limitation.

## Accessibility

- Not reachable from this environment directly (HTTPS timeout).
  UNVERIFIED what the live behavior is from other networks.
- Captures were obtained through web.archive.org snapshot URLs in the
  `...id_/` form; the archived pages are byte-faithful official markup.
- No authentication or API key; requests were plain GETs. VERIFIED from
  the captured pages' structure.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 46 titles, e.g. `1` ("General Provisions"),
  `21` ("Labor"), `33` ("Human Services"). Titles 1-3 use zero-padded URL
  segments (`01`-`03`); titles may carry letter suffixes (`9A`, `11A`,
  `11B`, `15C`, `27A`) or an `APPENDIX` suffix (`3APPENDIX`, `10APPENDIX`,
  `16APPENDIX`, `24APPENDIX`). VERIFIED from the statutes index page.
- **Chapter** — grouping within a title, e.g. `017` (Title 21,
  "Unemployment Compensation"). Chapter URL segments are zero-padded to
  three digits. VERIFIED.
- **Section** — the individually retrievable unit, e.g. `1344` (Title 21,
  Chapter 17, "Disqualifications"). Section identifiers may carry a letter
  suffix (`1301a`, `1301b`, `1305a`, `1305b`). Section URL segments are
  zero-padded to five digits plus any letter suffix (e.g. `01301`,
  `01301a`). VERIFIED from the chapter page and section pages.

The citation form is `{title} V.S.A. § {section}` (e.g. `21 V.S.A.
§ 1344`). VERIFIED — the section page itself renders "(Cite as: 21 V.S.A.
§ 1344)".

## URL Structure

VERIFIED (all executed against captured official pages):

- **Title list**: `https://legislature.vermont.gov/statutes/`. Lists all
  46 titles as `<li><a href="statutes/title/01">Title 1: General
  Provisions</a></li>` (relative hrefs for titles 1-3, absolute `/statutes/title/...`
  for the rest). Each is `Title {n}: {name}`.
- **Title page (chapter list)**: `https://legislature.vermont.gov/statutes/title/{title}`
  (e.g. `/statutes/title/01`). Contains an `<h2 class="statute-title">`
  heading and lists every chapter as
  `<li><a href="/statutes/chapter/01/001">Chapter  <span class="dirty">001</span>: <span class="caps">Vermont Statutes Annotated</span></a></li>`
  plus a "Contains: §§ X - Y" sub-list. VERIFIED for Title 1 (13 chapters).
- **Chapter page (section list)**: `https://legislature.vermont.gov/statutes/chapter/{title}/{chapter}`
  (e.g. `/statutes/chapter/21/017`). Contains `<h2 class="statute-title">`
  and `<h3 class="statute-chapter">` headings and a flat
  `<ul class="item-list statutes-list">` mixing subchapter markers and
  section links:
  - Subchapter markers: `<li><strong>Subchapter <span class="dirty">001</span>: <span class="caps">GENERAL BENEFITS</span></strong></li>`
    (presentation-only, flattened, NOT a ref level). VERIFIED.
  - Section links: `<li>\xa0\xa0<a href="/statutes/section/21/017/01301">§ 1301.  Definitions</a></li>`.
    Lettered sections use `01301a`-style hrefs. Repealed sections keep
    their annotation verbatim, e.g. `§ 1301b.  Repealed. 2001, No. 142,
    § 302c.` VERIFIED for Chapter 21/017 (123 section links).
- **Section**: `https://legislature.vermont.gov/statutes/section/{title}/{chapter}/{section}`
  (e.g. `/statutes/section/21/017/01344`). One page per section. VERIFIED.

## Discovery

1. **Titles**: fetch `/statutes/`; parse the 46 `statutes/title/{n}`
   links. identifier = the URL segment (e.g. `"1"`, `"21"`, `"9A"`,
   `"3APPENDIX"` — note 1-3 are zero-padded in the URL, the rest are not),
   name = the `Title {n}: ` label prefix stripped. VERIFIED.
2. **Chapters**: fetch `/statutes/title/{title}`; parse the
   `/statutes/chapter/{title}/{chapter}` links. identifier = the chapter
   URL segment (e.g. `"001"`), name = the `Chapter {n}: ` label prefix
   stripped. VERIFIED for Title 1: 13 chapters (001, 003, ..., 025).
3. **Sections**: fetch `/statutes/chapter/{title}/{chapter}`; parse the
   `/statutes/section/{title}/{chapter}/{section}` links. identifier =
   the section URL segment (e.g. `"01301"`, `"01301a"`), name = the
   `§ {n}. ` prefix stripped. VERIFIED for Chapter 21/017: 123 section
   links, including lettered `1301a`/`1301b` and the `(REPEALED)`-style
   annotations preserved in names.

## Retrieval

- Format: server-rendered HTML over HTTPS, plain GET, no auth. VERIFIED.
- The retrieval unit is the individual section page:
  `/statutes/section/{title}/{chapter}/{section}`. VERIFIED.
- Section page structure (VERIFIED for 21/017/01344):
  - **Cross-check anchors**: `<h2 class="statute-title"><a
    href="/statutes/title/21">Title 21: Labor</a></h2>` and `<h3
    class="statute-chapter"><a href="/statutes/chapter/21/017">Chapter
    017: Unemployment Compensation</a></h3>`, plus an `<h4
    class="statute-section">` subchapter heading — a framework-strong
    title/chapter cross-check point (the h4 subchapter is informational).
  - **Citation**: `<b>(Cite as: 21 V.S.A. § 1344)</b>` immediately before
    the body. VERIFIED.
  - **Heading**: `<b>§ 1344. Disqualifications</b>` — the first `<b>`
    inside the `<ul class="item-list statutes-detail">`. The leading
    `§ {n}. ` is stripped for the heading.
  - **Body**: the `<p>` paragraphs following the heading `<b>` inside the
    `<ul class="item-list statutes-detail">` (indented subsection
    paragraphs). The last body paragraph ends with the trailing amendment
    history parenthetical, e.g. `... (Amended 1959, No. 236; ... 2023,
    No. 6, § 252, eff. July 1, 2023.)`.
  - **History**: the trailing parenthetical in the final body paragraph —
    the raw amendment chain "(Amended ...)" — preservable verbatim as
    `amendment_notes` and removable from the body. VERIFIED.
- **Source URL** — the section page URL used, e.g.
  `https://legislature.vermont.gov/statutes/section/21/017/01344`.

## Status / repeal signal

Repealed sections (e.g. § 1301b) carry their annotation in the chapter
listing name ("§ 1301b. Repealed. 2001, No. 142, § 302c.") and, on the
section page, would render a repeal note in place of a body. The listing
annotation is prose-level, so `status` stays `UNKNOWN` in listing names
(annotation preserved verbatim). A structural repeal marker on a section
page would be treated like Missouri's (REPEALED in place of body), but no
repealed section page was captured for Vermont — UNVERIFIED.

## Error behavior

- Live HTTP 404 for a missing title/chapter/section is UNVERIFIED (see
  Status). By convention, HTTP 404 maps to `RefNotFoundError` and other
  failures to `AdapterUnavailableError` via the shared fetch helper.
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).
- A located section with an empty body raises `NormalizationError`.

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools expose Vermont with
**no signature changes**:

- `TitleRef.identifier` = the title URL segment (e.g. `"21"`, `"9A"`,
  `"3APPENDIX"`).
- `ChapterRef.identifier` = the chapter URL segment (e.g. `"017"`).
- `SectionRef.identifier` = the section URL segment (e.g. `"01344"`,
  `"01301a"`).
- Zero-padding is inherent in the URL segments and carries through the
  identifiers (e.g. `get_section(state_code="VT", title="21",
  chapter="017", section="01344")` round-trips cleanly).

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `VermontAdapter` in
  `src/state_statutes_mcp/adapters/vermont/adapter.py`.
- **Base URL**: `BASE_URL = "https://legislature.vermont.gov"`; statutory
  pages under `/statutes/`. URLs:
  - Titles: `{BASE}/statutes/`.
  - Title page (chapters): `{BASE}/statutes/title/{title}`.
  - Chapter page (sections): `{BASE}/statutes/chapter/{title}/{chapter}`.
  - Section: `{BASE}/statutes/section/{title}/{chapter}/{section}`.
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: fetch `/statutes/`; parse title links; identifier =
  URL segment, name = label minus `Title {n}: ` prefix; sort numerically.
- **`list_chapters(title_ref)`**: fetch `/statutes/title/{title}`; parse
  chapter links; identifier = chapter URL segment, name = label minus
  `Chapter {n}: ` prefix; sort numerically.
- **`list_sections(chapter_ref)`**: fetch `/statutes/chapter/{title}/{chapter}`;
  parse section links (ignoring subchapter `<strong>` markers);
  identifier = section URL segment, name = label minus `§ {n}. ` prefix;
  sort numerically.
- **`retrieve_section(ref)`**: build the section URL; fetch; cross-check
  the page's Title/Chapter anchors against `ref` (`RefMismatchError` on
  mismatch); parse heading from the heading `<b>`, body from the
  `statutes-detail` paragraphs, amendment history from the trailing
  parenthetical; build `ParsedDocument` with `raw_citation = f"{title}
  V.S.A. § {section}"` (using the cite-as form's title/section numbers),
  `source_url` = the section URL; call `normalize`.
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-Vermont refs (`NormalizationError`); require the section
  number in `parsed.raw_citation` (`RefMismatchError` on mismatch);
  `status` stays `UNKNOWN`; populate `citation`, `heading`, `text`,
  `amendment_notes`, `source_url`, `retrieved_at`.
- **Citation handling**: `{title} V.S.A. § {section}`, adapter-constructed
  (the "V.S.A." abbreviation is VERIFIED from the site's own "(Cite as:)"
  line), cross-checked in `normalize`.
- **History handling**: the trailing "(Amended ...)" parenthetical,
  verbatim into `amendment_notes` (raw text, per the framework's contract
  — no parsing), and removed from the body.
- **Error mapping**: network failure → `AdapterUnavailableError`; HTTP
  404 (bad title/chapter/section) → `RefNotFoundError`; empty body →
  `NormalizationError`; citation disagreement → `RefMismatchError`; wrong
  ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: `Title → Chapter → Section` maps 1:1 onto
  `TitleRef → ChapterRef → SectionRef`; subchapters are flattened
  (presentation-only, not a ref level).

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete; `state_code == "VT"`; `state_name
   == "Vermont"`.
2. **URL construction** — title/chapter/section URLs; unsupported ref
   type raises `UnsupportedRefError`.
3. **Title discovery** — real index fixture → 46 titles, including
   zero-padded `01` and lettered/appendix titles.
4. **Chapter discovery** — real Title 1 fixture → 13 chapters with names.
5. **Section discovery** — real Chapter 21/017 fixture → 123 section
   links; lettered `01301a`; repealed annotation preserved in names.
6. **Retrieval** — real 21/017/01344 fixture: citation `21 V.S.A.
   § 1344`, heading `Disqualifications`, body text without the trailing
   amendment parenthetical, amendment history in `amendment_notes`,
   `source_url`, status UNKNOWN.
7. **Cross-checks** — Title anchor mismatch → `RefMismatchError`;
   Chapter anchor mismatch → `RefMismatchError`.
8. **Citation parsing** — `21 V.S.A. § 1344` round-trips through
   `normalize`; state mismatch → `NormalizationError`; citation mismatch
   → `RefMismatchError`.
9. **Normalization** — populated `StatuteSection` fields; empty-body
   section → `NormalizationError`.
10. **Reference mismatch** — `SectionRef` for a different section vs the
    located page → `RefMismatchError`/`RefNotFoundError` as appropriate.
11. **Malformed source** — section page missing heading → `NormalizationError`;
    malformed listing → `AdapterUnavailableError`.
12. **Missing section** — valid title/chapter, absent section → 404 →
    `RefNotFoundError` (simulated).
13. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
14. **Real-source fixture** — the captured official pages under
    `tests/fixtures/vermont_*` exercised through discovery and retrieval.
15. **MCP `get_section` integration** — a `VermontAdapter` registered in
    an `AdapterRegistry` served through `server_tools.get_section`
    returns the expected dict shape.

## Known Limitations

- Live HTTP 404 behavior for missing titles/chapters/sections is
  UNVERIFIED (host unreachable from this environment); the not-found
  mapping follows the other-adapters convention and is simulated in tests.
- Subchapters exist on both chapter and section pages but are flattened
  into the section listing and treated as informational only — they are
  not a ref level, per the research boundary.
- Repealed-section section-page markup is UNVERIFIED (no repealed section
  page was captured); the listing annotation is preserved verbatim in
  names.
- The "unofficial copy" disclaimer on every page is the source's own
  caveat; it does not block implementation.

## Framework Compatibility

ARCHITECTURAL CONCLUSION: no framework changes are required. The
three-level `TitleRef → ChapterRef → SectionRef` model fits exactly, and
all five abstract methods plus the adapter-owned `retrieve_section` are
implementable against the server-rendered HTML with no changes to
`BaseStateAdapter`, the ref models, the registry, or the MCP tools.
The per-section-page HTML retrieval model is the same family as
`MaineAdapter` and `MissouriAdapter` (one HTML page per section) but with
Vermont's own markup and identifiers, so no shared parser is warranted.

## Risks

- If the site changes its `<h2 class="statute-title">` / `<h3
  class="statute-chapter">` / `statutes-detail` markup, parsing fails
  loudly (`NormalizationError`), never silently.
- Section identifiers carry zero-padding in the URL segments; if a future
  section number exceeds the padding width, the round-trip still works
  (padding is only applied when below the width).
- The trailing-parenthetical history extraction could in principle match a
  non-history final parenthetical; the "(Amended ...)" / "(Added ...)"
  prefix anchor mitigates this (see adapter).
