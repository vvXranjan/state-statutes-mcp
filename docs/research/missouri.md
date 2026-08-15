# Missouri Statute Source Research

Research performed: Aug 14-15, 2026. The live host
(`https://revisor.mo.gov`) was NOT reachable from this environment
(HTTPS timed out; HTTP returned 403), so official markup was captured via
the Wayback Machine (`...id_/` snapshot form) and inspected offline. Every
URL below was executed against the captured official pages; structure is
documented verbatim from those captures, which are the implementation
boundary for this adapter.

## Status

**VERIFIED** for the core discovery and retrieval paths: title listing
(the home page's "Chapters in Title" blocks), chapter listing (the
chapter TOC page), section listing (the same chapter TOC page), section
retrieval with heading, body, and foot history block, the per-section-page
title/chapter cross-check anchors, and a repealed-section page. All verified
from Wayback captures of the official `revisor.mo.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: the live HTTP 404
behavior for a missing title/chapter/section (the Wayback capture of a
missing section was Wayback's own 404 page, not the site's), whether
chapter TOC pages always render identically, and the exact markup of
chapter-listing "stub" entries for missing/repealed sections (Chapter 536
happens to contain no stubs). Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://revisor.mo.gov/main/` — the official Revisor of Missouri
  publication of the Revised Statutes of Missouri (RSMo).
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically).
- The site names itself "RSMo" in page `<title>` ("Missouri Revisor of
  Statutes - Revised Statutes of Missouri, RSMo Section 536.050") and in
  its share metadata (twitter text "RSMo 536.050"). VERIFIED.

## Accessibility

- Not reachable from this environment directly: HTTPS times out, HTTP
  returns 403. UNVERIFIED what the live behavior is from other networks.
- Captures were obtained through web.archive.org snapshot URLs in the
  `...id_/` form; the archived pages are byte-faithful official markup.
- No authentication or API key; requests were plain GETs. VERIFIED from
  the captured pages' structure (no auth chrome).

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 41 titles, identified by Roman numeral, e.g.
  `I` ("LAWS AND STATUTES"), `XXXVI` ("STATUTORY ACTIONS AND TORTS").
  Each title block on the home page shows a chapter range ("Chs. 1-3")
  plus the Roman numeral and name. VERIFIED from the home page.
- **Chapter** — grouping within a title, e.g. `536` (Title XXXVI,
  "Administrative Procedure and Review"). VERIFIED.
- **Section** — the individually retrievable unit, e.g. `536.050`
  ("Declaratory judgments respecting the validity of rules — fees and
  expenses — standing, intervention by general assembly."). Section
  identifiers are the dotted `Chapter.NNN` numbers. VERIFIED.

The citation form is `RSMo § {section}` (e.g. `RSMo § 536.050`). The
`RSMo` abbreviation is VERIFIED from the site's own `<title>` and share
metadata; the `§ {section}` shape is the standard Missouri citation form
(INFERENCE for the `§` character).

## URL Structure

VERIFIED (all executed against captured official pages):

- **Home / title list**: `https://revisor.mo.gov/main/Home.aspx`.
  Contains a "Chapters in Title" region of 45 `<details>` blocks, 41 of
  which are title blocks. Each title `<details>` block's `<summary>`
  holds two `<span class="lr-font-emph">` spans: the first is the chapter
  range ("Chs. 1-3" with padded spaces), the second is the title
  identifier and name ("I\u2003LAWS AND STATUTES"). Each block body lists
  the title's chapters as
  `<a href="/main/OneChapter.aspx?chapter=1">\u2003\u20031\u2003Laws in
  Force and Construction of Statutes</a>`. Title blocks together contain
  468 chapter links (every RSMo chapter). A separate "Chapters
  Alphabetically" `<details>` block (`id="CHAPA"`) lists the same 468
  chapters as `PageSelect.aspx?chapter=N` links.
- **Chapter TOC (section list)**:
  `https://revisor.mo.gov/main/PageSelect.aspx?chapter={chapter}` (e.g.
  `...?chapter=536`). Both `PageSelect.aspx?chapter=536` and
  `OneChapter.aspx?chapter=536` return the same 54-section listing.
  VERIFIED. Page heading:
  `<p>\xa0Title XXXVI  STATUTORY ACTIONS AND TORTS</p> Chapter 536\xa0Administrative
  Procedure and Review`. Section rows:
  `<td><a href="/main/PageSelect.aspx?section=536.010&amp;bid=28388&amp;hl=">536.010\u2002\u2002</a></td>
  <td>Definitions. <span>(8/28/2006)</span></td>`.
- **Section**: `https://revisor.mo.gov/main/OneSection.aspx?section={section}`
  (e.g. `...?section=536.050`). One page per section. VERIFIED.

## Discovery

1. **Titles**: fetch `Home.aspx`; parse the 41 title `<details>` blocks;
   identifier = the Roman numeral in the summary's second span (before
   `\u2003`), name = the remainder. VERIFIED: 41 unique titles.
2. **Chapters**: fetch `Home.aspx`; locate the title block whose summary
   matches `title_ref.identifier`; parse its `OneChapter.aspx?chapter=N`
   links. identifier = `{chapter}`, name = link text with the leading
   chapter number and `\u2003` stripped. VERIFIED for Title I (chapters
   1-3), II (7-14), III (18-23), VI (46-70), and the block containing
   chapters 521-538.
3. **Sections**: fetch `PageSelect.aspx?chapter={chapter}`; parse the
   table rows. identifier = the dotted `section=` value (e.g. "536.010"),
   name = the name cell text (e.g. "Definitions." with its effective-date
   parenthetical "(8/28/2006)" preserved verbatim). VERIFIED for Chapter
   536: 54 sections, 536.010 → 536.320.

## Retrieval

- Format: server-rendered HTML over HTTPS, plain GET, no auth. VERIFIED.
- The retrieval unit is the individual section page:
  `OneSection.aspx?section={section}`. VERIFIED.
- Section page structure (VERIFIED for 536.050 and 536.303):
  - **Cross-check anchors**: `<p>Title XXXVI STATUTORY ACTIONS AND
    TORTS</p>` and `<a href="/main/PageSelect.aspx?chapter=536">Chapter
    536</a>` (with `title="Return to section list for Chapter 536"`)
    appear before the section content — a framework-strong title/chapter
    cross-check point. VERIFIED.
  - **Heading**: `<span class="bold"> 536.050.<span> </span>Declaratory
    judgments respecting the validity of rules — fees and expenses —
    standing, intervention by general assembly. — </span>`. The heading is
    the bold-span text with the leading `536.050.` prefix and the
    trailing ` — ` separator stripped (giving "Declaratory judgments ...").
    The page's `og:description` holds the same heading text VERIFIED.
  - **Body**: the `1.`-style text immediately following the bold span,
    inside the `<div class="norm">` container, up to the `<div class="foot">`
    history block.
  - **History**: `<div class="foot" style="background-color:#fffade;">`
    containing a `<p>--------</p>` marker followed by `<p class="norm">(L.
    1945 p. 1504 § 5, A.L. 1978 S.B. 661, ...) </p>` and then editorial
    footnotes (e.g. "*Section 536.303 was repealed by S.B. 894 & 825,
    2024." and case annotations). VERIFIED.
  - **Repealed sections** (e.g. 536.303): the body is just
    `<span class="bold"> 536.303. (Repealed L. 2024 S.B. 894 &amp;
    825)</span>` with an empty foot block. The repeal note is the section's
    entire content — a structural "Repealed" marker in place of body text,
    so `status = REPEALED` is defensible under the framework's rule (see
    Status / repeal signal).
- **Source URL** — the section page URL used, e.g.
  `https://revisor.mo.gov/main/OneSection.aspx?section=536.050`.

## Status / repeal signal

For the repealed 536.303, the "(Repealed ...)" note replaces body text
entirely: there is no body content at all, only the bold repeal marker.
This is a structural signal (a "Repealed" marker in place of body text),
so `status = REPEALED` is used for MO repealed sections — the first
adapter in this codebase to do so. For non-repealed sections `status`
stays `UNKNOWN` (no structural in-force signal is present).

## Error behavior

- Live HTTP 404 for a missing title/chapter/section is UNVERIFIED (see
  Status). By convention, HTTP 404 maps to `RefNotFoundError` and other
  failures to `AdapterUnavailableError` via the shared fetch helper.
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).
- A located section with an empty body is treated as repealed (REPEALED
  marker); a located non-repealed section whose body is unexpectedly empty
  after cleaning raises `NormalizationError`.

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools expose Missouri
with **no signature changes**:

- `TitleRef.identifier` = the Roman numeral (e.g. `"XXXVI"`).
- `ChapterRef.identifier` = the chapter number (e.g. `"536"`).
- `SectionRef.identifier` = the dotted section number (e.g. `"536.050"`).
- `build_url(TitleRef)` returns the home page `Home.aspx` URL (titles
  have no URL of their own; `list_chapters` fetches the home page and
  filters by title block). This is documented rather than hidden.

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `MissouriAdapter` in
  `src/state_statutes_mcp/adapters/missouri/adapter.py`.
- **Base URL**: `BASE_URL = "https://revisor.mo.gov"`; statutory pages
  under `/main/`. URLs:
  - Home/titles: `{BASE}/main/Home.aspx`.
  - Chapter TOC (sections): `{BASE}/main/PageSelect.aspx?chapter={chapter}`.
  - Section: `{BASE}/main/OneSection.aspx?section={section}`.
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: fetch `Home.aspx`; parse the 41 title `<details>`
  blocks; identifier = Roman numeral, name = title name; sort by chapter
  range start.
- **`list_chapters(title_ref)`**: fetch `Home.aspx`; locate the title
  block matching `title_ref.identifier`; parse its `OneChapter.aspx?chapter=N`
  links; identifier = `{N}`, name = link text minus the number prefix;
  sort numerically.
- **`list_sections(chapter_ref)`**: fetch `PageSelect.aspx?chapter={N}`;
  parse section table rows; identifier = dotted `section=` value, name =
  name cell text; sort numerically.
- **`retrieve_section(ref)`**: build the section URL; fetch; cross-check
  the page's Title/Chapter anchors against `ref` (`RefMismatchError` on
  mismatch); parse heading from the bold span, body from the `norm`
  region, history from the foot block; build `ParsedDocument` with
  `raw_citation = f"RSMo § {ref.identifier}"`, `source_url` = the section
  URL; call `normalize`.
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-Missouri refs (`NormalizationError`); require
  `ref.identifier` in `parsed.raw_citation` (`RefMismatchError` on
  mismatch); `status` REPEALED only when the heading is a structural
  repeal marker, else UNKNOWN; populate `citation`, `heading`, `text`,
  `amendment_notes`, `source_url`, `retrieved_at`.
- **Citation handling**: `RSMo § {id}`, adapter-constructed, cross-checked
  in `normalize`.
- **History handling**: the foot block content after the `--------`
  marker, verbatim into `amendment_notes` (raw text, per the framework's
  contract — no parsing).
- **Error mapping**: network failure → `AdapterUnavailableError`;
  HTTP 404 (bad title/chapter/section) → `RefNotFoundError`; empty
  non-repealed body → `NormalizationError`; citation disagreement →
  `RefMismatchError`; wrong ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: `Title → Chapter → Section` maps 1:1 onto
  `TitleRef → ChapterRef → SectionRef`.

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete; `state_code == "MO"`; `state_name
   == "Missouri"`.
2. **URL construction** — home/title, chapter TOC, and section URLs;
   unsupported ref type raises `UnsupportedRefError`.
3. **Title discovery** — real home fixture → 41 titles; Title I name
   "LAWS AND STATUTES"; title XXXVI present.
4. **Chapter discovery** — real home fixture → chapters under a title;
   e.g. title XXXVI yields 536 ... 538; names stripped of the number
   prefix.
5. **Section discovery** — real chapter TOC fixture → 54 sections,
   536.010 → 536.320; names preserve the effective-date parenthetical.
6. **Retrieval** — real 536.050 fixture: citation `RSMo § 536.050`,
   heading, body text, history in `amendment_notes`, `source_url`, status
   UNKNOWN. Real 536.303 (repealed) fixture: heading is the repeal note,
   status REPEALED.
7. **Cross-checks** — Title anchor mismatch → `RefMismatchError`;
   Chapter anchor mismatch → `RefMismatchError`.
8. **Citation parsing** — `RSMo § 536.050` round-trips through `normalize`;
   state mismatch → `NormalizationError`; citation mismatch →
   `RefMismatchError`.
9. **Normalization** — populated `StatuteSection` fields.
10. **Reference mismatch** — `SectionRef` for a different section vs the
    located page → `RefMismatchError`/`RefNotFoundError` as appropriate.
11. **Malformed source** — section page missing the title anchor →
    `NormalizationError`; malformed listing → `AdapterUnavailableError`.
12. **Missing section** — valid chapter, absent section → 404 →
    `RefNotFoundError` (simulated).
13. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
14. **Real-source fixture** — the captured official pages under
    `tests/fixtures/missouri_*` exercised through discovery and retrieval.
15. **MCP `get_section` integration** — a `MissouriAdapter` registered in
    an `AdapterRegistry` served through `server_tools.get_section`
    returns the expected dict shape.

## Known Limitations

- Live HTTP 404 behavior for missing titles/chapters/sections is
  UNVERIFIED (host unreachable from this environment); the not-found
  mapping follows the Maine/other-adapters convention and is simulated in
  tests.
- Whether every chapter TOC page renders identically is UNVERIFIED
  (sampled Chapter 536); `NormalizationError` guards against shape change.
- The exact markup of chapter-listing "stub" entries for missing/repealed
  sections is UNVERIFIED (Chapter 536 contains none). Stub rows are
  skipped gracefully (rows without `section=` links are ignored).
- The citation `§` character is INFERENCE from standard Missouri citation
  usage; `RSMo` is VERIFIED from the site's own metadata.

## Framework Compatibility

ARCHITECTURAL CONCLUSION: no framework changes are required. The
three-level `TitleRef → ChapterRef → SectionRef` model fits exactly, and
all five abstract methods plus the adapter-owned `retrieve_section` are
implementable against the server-rendered HTML with no changes to
`BaseStateAdapter`, the ref models, the registry, or the MCP tools.
The per-section-page HTML retrieval model is the same family as
`MaineAdapter` (one HTML page per section, with a foot history block)
but with Missouri's own markup and identifiers, so no shared parser is
warranted.

## Risks

- If the site changes its `<span class="bold">` heading or `<div
  class="foot">` history markup, parsing fails loudly
  (`NormalizationError`), never silently.
- The title block's "Chapters in Title" structure on the home page is
  the source of truth for both titles and per-title chapters; if the
  home page redesigns, both `list_titles` and `list_chapters` fail
  loudly.
- Repealed-section handling is a deliberate first: `status = REPEALED`
  is set only when the repeal note structurally replaces the body, per
  the framework's own rule ("a 'Repealed' marker in place of body text").
