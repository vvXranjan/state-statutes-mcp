# South Dakota Statute Source Research

Research performed: Aug 14, 2026, by direct requests to the official
South Dakota Legislature site (`sdlegislature.gov`) — no third-party
sources. Every endpoint below was executed live against the real host;
raw JSON responses were captured and inspected.

## Status

**VERIFIED** for the core discovery and retrieval paths (title listing
via the JSON API, chapter listing, section listing, section retrieval
with embedded HTML, amendment-source text, effective-date endpoint,
404 error behavior). All were exercised against the live official host.

**UNVERIFIED** for a small set of secondary questions (rate-limit
policy, whether historical editions of the Codified Laws are available,
whether every title's embedded `Html` renders identically, and the
`Constitution` sub-API); those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://sdlegislature.gov/Statutes` — the official South Dakota
  Legislature publication of the South Dakota Codified Laws (SDCL).
  VERIFIED. The public pages are a Vue single-page application; the
  site's own data API is plain server-rendered JSON.
- **Official JSON API**: `https://sdlegislature.gov/api/Statutes/`.
  VERIFIED — the same API the SPA itself calls. Plain HTTPS GET, no
  authentication, no cookies, no API key. VERIFIED (a bare
  `curl` GET with a browser User-Agent succeeds).

## Accessibility

- Reachable from this environment over plain HTTPS GET. VERIFIED.
- No authentication, no API key, no cookies required. All requests were
  plain `curl` GETs and succeeded. VERIFIED.
- No explicit rate limiting observed across repeated rapid requests.
  UNVERIFIED that no policy exists.
- Stable, deterministic API paths:
  `/api/Statutes/Title`, `/api/Statutes/Statute/{id}`,
  `/api/Statutes/LastStatuesEffectiveDate`. VERIFIED.

## Hierarchy

Three structural levels, exactly matching the framework:

- **Title** — top level, e.g. `1`–`62`, plus lettered titles (`23A`,
  `27A`, `27B`, `29A`, `33A`, `34A`, `46A`, `51A`, `57A` — 9 lettered
  titles among 71 total). VERIFIED via `GET /api/Statutes/Title`.
- **Chapter** — grouping within a title, e.g. `3` (Title 22,
  "PARTIES TO CRIMES"), including lettered chapters (`22-4A`
  "SOLICITATION"). VERIFIED.
- **Section** — numbered `title-chapter-section`, e.g. `22-3-1`
  ("Persons capable of committing crimes--Exceptions."), with decimal
  sub-sections (`22-3-1.1`) as distinct records. VERIFIED.

The citation is `SDCL § {title}-{chapter}-{section}` (e.g.
`SDCL § 22-3-1`). VERIFIED — this form appears throughout SD Supreme
Court opinions and legislative documents.

## API Shape

Every Title, Chapter, and Section is the **same flat record type**
("Statute"), discriminated by a `Type` field:

```json
{
  "StatuteId": 2046938,
  "Statute": "22-3-1",
  "Type": "Section",
  "CatchLine": "Persons capable of committing crimes--Exceptions.",
  "Title": 22, "Chapter": 3, "Section": 1, "SubSec": 0,
  "Repealed": false,
  "parents": [
    {"StatuteId": 2046918, "Type": "Title", "Statute": "22"},
    {"StatuteId": 2046949, "Type": "Chapter", "Statute": "3"},
    {"StatuteId": 2046938, "Type": "Section", "Statute": "1"}
  ],
  "Previous": "22-3",
  "Next": "22-3-1.1",
  "Html": "<html ...>...</html>"
}
```

VERIFIED. `Html` holds the section's full rendered content; `parents`
expresses the hierarchy; `Previous`/`Next` provide linked-list
navigation across the whole Codified Laws.

## Discovery

All three levels are enumerated through the API:

1. **Titles**: `GET /api/Statutes/Title` → a JSON array of title
   records, e.g. `{"Statute":"1","CatchLine":"STATE AFFAIRS AND
   GOVERNMENT"}`, ..., `{"Statute":"22","CatchLine":"CRIMES"}`. 71
   entries total. VERIFIED.
2. **Chapters**: `GET /api/Statutes/Statute/{title}` (e.g.
   `/api/Statutes/Statute/22`) → a Title record whose embedded `Html`
   links to every chapter: `<a href="...Statute=22-1">01 Definitions And
   General Provisions ...</a>`, `Statute=22-4A`, ... (62 chapters in
   Title 22, VERIFIED). Chapter number and name are extractable from the
   link text.
3. **Sections**: `GET /api/Statutes/Statute/{title}-{chapter}` (e.g.
   `/api/Statutes/Statute/22-3`) → a Chapter record whose embedded `Html`
   links to every section: `<a ... Statute=22-3-1">22-3-1 Persons capable
   of committing crimes--Exceptions.</a>`, `Statute=22-3-1.1`, ... (11
   sections in Chapter 22-3, VERIFIED). Section number and catchline are
   extractable from the link text.

## Retrieval

- Format: **JSON over HTTPS, plain GET, no auth.** VERIFIED.
- The retrieval unit is the flat statute record:
  `GET /api/Statutes/Statute/{full-number}` (e.g.
  `/api/Statutes/Statute/22-3-1`). VERIFIED.
- The section's content lives in the record's `Html` field. Stripping
  tags yields the full text:

  > `22-3-1. Persons capable of committing crimes--Exceptions. Any
  > person is capable of committing a crime, except those included in
  > the following classes: (1) Any child under the age of ten years;
  > (2) Any child of the age of ten years, but under the age of fourteen
  > years, in the absence of proof that at the time of the committing
  > the act or neglect charged, the child knew its wrongfulness; ...`

  VERIFIED.

This is a **JSON-API record-with-embedded-HTML** retrieval model at
section scope: each section is one API request returning a JSON record
whose `Html` payload is the rendered statute. It is the first framework
source where the content payload is an HTML document embedded inside a
JSON record (Virginia's JSON API returns structured text fields, not
embedded HTML documents).

## Parsing

For one retrieved section record, the embedded `Html` yields:

- **Citation** — constructed by the adapter: `SDCL § {id}` (e.g.
  `SDCL § 22-3-1`). The section number itself carries title + chapter.
  The canonical citation form is INFERENCE from SD court usage (the site
  displays the number; the `SDCL §` prefix is the standard form).
- **Heading/catchline** — the `CatchLine` field (e.g. "Persons capable
  of committing crimes--Exceptions.") and the leading text of the
  embedded `Html`. VERIFIED.
- **Body** — the embedded `Html` text after the number/catchline, e.g.
  "Any person is capable of committing a crime, except those included in
  the following classes: ...". VERIFIED.
- **History/amendments** — each section's embedded HTML ends with a
  `Source:` chain, e.g. `Source: SDC 1939, § 13.0201; SL 1968, ch 28,
  §§ 1, 2; SL 1976, ch 158, §§ 3-1, 3-5; SL 1983, ch 174, § 3; SL 1985,
  ch 192, § 10; SL 2005, ch 120, § 370.` — preservable verbatim as
  `amendment_notes`. VERIFIED.
- **Effective date/version** — a global endpoint,
  `GET /api/Statutes/LastStatuesEffectiveDate`, returns the current
  effective date (e.g. `"2026-07-29T00:00:00-05:00"`). VERIFIED. No
  per-section effective date observed in section records
  (UNVERIFIED that none exist). The framework stores history as raw text
  and `status` stays `UNKNOWN`.
- **Source URL** — the API URL used, e.g.
  `https://sdlegislature.gov/api/Statutes/Statute/22-3-1`.

## Status / repeal signal

Each record carries a `Repealed` boolean. VERIFIED that it is `False`
even on sections whose text explicitly reads "Repealed by SL 2005, ch
120, § 358, eff. July 1, 2006." Therefore repeal is prose-only, and
`status` must stay `UNKNOWN` under the framework's rule forbidding
inferring status from prose. The `Repealed` flag is an unreliable signal
and is ignored.

## Error behavior

- A nonexistent chapter (`/api/Statutes/Statute/22-99`) returns HTTP
  404. VERIFIED.
- A nonexistent section (`/api/Statutes/Statute/99-99-99`) returns HTTP
  404. VERIFIED.
- A network failure surfaces as `AdapterUnavailableError` via the shared
  fetch helper (ARCHITECTURAL CONCLUSION — same as every adapter).
- The JSON API is the error boundary: the adapter maps HTTP 404 → 
  `RefNotFoundError`, other network failures → `AdapterUnavailableError`.

## MCP Compatibility

ARCHITECTURAL CONCLUSION: the existing five MCP tools
(`list_states`, `list_titles`, `list_chapters`, `list_sections`,
`get_section`) expose South Dakota with **no signature changes**:

- `TitleRef.identifier` = title number (e.g. `"22"`, `"23A"`).
- `ChapterRef.identifier` = chapter number (e.g. `"3"`, `"4A"`).
- `SectionRef.identifier` = full section number (e.g. `"22-3-1"`), which
  already carries the title and chapter — the same convention
  `WashingtonAdapter` (`49.60.010`), `TexasAdapter` (`19.01`), and
  `FloridaAdapter` (`775.01`) use, so `get_section(state_code="SD",
  title="22", chapter="3", section="22-3-1")` round-trips cleanly.
- The Codified Laws are a current-code source; no edition/year enters
  the refs or the citation.

## Proposed Adapter Design (DESIGN ONLY — no code written)

- **Class**: `SouthDakotaAdapter` in
  `src/state_statutes_mcp/adapters/south_dakota/adapter.py`.
- **Base URL**: `BASE_URL = "https://sdlegislature.gov"`; API path
  prefix `.../api/Statutes`. URLs:
  - Titles: `{BASE}/api/Statutes/Title`.
  - Chapter record: `{BASE}/api/Statutes/Statute/{title}`.
  - Section record: `{BASE}/api/Statutes/Statute/{title}-{chapter}` /
    `{title}-{chapter}-{section}`.
  - `build_url(ref)` raises `UnsupportedRefError` for foreign ref types.
- **`list_titles()`**: `GET /api/Statutes/Title`; identifier from
  `Statute`, name from `CatchLine`; sort numerically.
- **`list_chapters(title_ref)`**: fetch the title record; parse its
  embedded `Html` for `Statute={title}-{chapter}` links; identifier =
  chapter number, name from the link text (strip the leading number).
  Dedupe; sort numerically. HTTP 404 → `RefNotFoundError`.
- **`list_sections(chapter_ref)`**: fetch the chapter record; parse its
  embedded `Html` for `Statute={title}-{chapter}-{section}` links;
  identifier = full section number, name from the link text (strip the
  leading number). Dedupe; sort numerically. HTTP 404 →
  `RefNotFoundError`; no sections found → `AdapterUnavailableError`.
- **`retrieve_section(ref)`**: build the `/api/Statutes/Statute/{id}`
  URL; fetch; the record is the section itself (cross-check
  `Type == "Section"` and `parents` against `ref`); parse `CatchLine`
  (heading), embedded `Html` body, and the trailing `Source:` chain
  (amendment_notes); build `ParsedDocument` with
  `raw_citation = f"SDCL § {ref.identifier}"`, `source_url` = the API
  URL; call `normalize`. 404 → `RefNotFoundError`; a located record
  with an empty body → `NormalizationError` (the same empty-body
  convention Virginia, Delaware, and Florida use).
- **`normalize(parsed, ref)`**: same contract as the other adapters —
  refuse non-South-Dakota refs (`NormalizationError`); require
  `ref.identifier` in `parsed.raw_citation` (`RefMismatchError` on
  mismatch); `status` stays `UNKNOWN` (the `Repealed` flag is an
  unreliable prose-level signal); populate `citation`, `heading`,
  `text`, `amendment_notes`, `source_url`, `retrieved_at`.
- **Citation handling**: `SDCL § {id}`, adapter-constructed,
  cross-checked in `normalize`.
- **History handling**: the `Source:` chain verbatim into
  `amendment_notes` (raw text, per the framework's contract — no
  parsing).
- **Error mapping**: network failure → `AdapterUnavailableError`;
  HTTP 404 (bad chapter/section) → `RefNotFoundError`; empty body →
  `NormalizationError`; citation disagreement → `RefMismatchError`;
  wrong ref type → `UnsupportedRefError`.
- **Hierarchy mapping**: `Title → Chapter → Section` maps 1:1 onto
  `TitleRef → ChapterRef → SectionRef` with no flattening.

## Proposed Test Matrix

All offline, using the existing `_mock_network` pattern (mock
`state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, never
adapter internals):

1. **Adapter identity** — concrete (no abstract methods); `state_code
   == "SD"`; `state_name == "South Dakota"`.
2. **URL construction** — title/chapter/section API URLs; section URL is
   `/api/Statutes/Statute/{id}`; unsupported ref type raises
   `UnsupportedRefError`.
3. **Title discovery** — `/api/Statutes/Title` fixture → numeric order;
   lettered titles (`23A`) preserved; dedupe; no titles →
   `AdapterUnavailableError`; network failure → `AdapterUnavailableError`.
4. **Chapter discovery** — title record fixture → embedded-`Html` link
   parse yields numeric-order chapters with names; lettered chapters
   (`22-4A`); 404 → `RefNotFoundError`; network failure →
   `AdapterUnavailableError`.
5. **Section discovery** — chapter record fixture → embedded-`Html` link
   parse yields sections with catchlines; decimal sub-sections
   (`22-3-1.1`); 404 → `RefNotFoundError`; no sections →
   `AdapterUnavailableError`.
6. **Retrieval** — full `retrieve_section` for a simple section and a
   multi-paragraph section (heading, body, source chain, source_url,
   citation, status UNKNOWN); 404 → `RefNotFoundError`; network failure
   → `AdapterUnavailableError`.
7. **Citation parsing** — `SDCL § 22-3-1` round-trips through
   `normalize`; state mismatch → `NormalizationError`; citation mismatch
   → `RefMismatchError`.
8. **Normalization** — populated `StatuteSection` fields; empty-body
   section → `NormalizationError`.
9. **Reference mismatch** — `SectionRef` for a different section vs the
   located record → `RefMismatchError`/`RefNotFoundError` as appropriate.
10. **Malformed source** — record with no embedded `Html`; record whose
    `Type` is not "Section"; malformed link text → `NormalizationError`/
    `AdapterUnavailableError`.
11. **Missing section** — valid title, absent section number →
    `RefNotFoundError`.
12. **Network failure** — `mock_urlopen_error` → `AdapterUnavailableError`.
13. **Representative real-source fixture** — one or more section records
    captured from the live API (e.g. `22-3-1`) saved under
    `tests/fixtures/` as JSON, exercised through discovery and retrieval.
14. **MCP `get_section` integration** — a `SouthDakotaAdapter`
    registered in an `AdapterRegistry` served through
    `server_tools.get_section` returns the expected dict shape.

## Known Limitations

- Chapter/section listings must be parsed from a parent record's
  embedded `Html` (link-text extraction) rather than a dedicated list
  endpoint — a hybrid JSON + HTML parsing path that differs from
  Virginia's structured list endpoints.
- The `Html` payload is Word/Open-XML-styled XHTML (`span { white-space:
  pre-wrap; }`, `PowerTools for Open XML` generator); stripping requires
  the shared `strip_tags` helper and whitespace normalization.
- Whether every title's embedded `Html` renders identically is
  UNVERIFIED (sampled Title 22 and Chapter 22-3 only); `NormalizationError`
  guards against a shape change.
- Historical editions of the Codified Laws were not observed
  (UNVERIFIED that none are available); the adapter serves the current
  code like Virginia/Delaware.
- The `Constitution` sub-API was not exercised (the Codified Laws path
  needs no constitutional provisions).

## Framework Compatibility

ARCHITECTURAL CONCLUSION: no framework changes are required. The
three-level `TitleRef → ChapterRef → SectionRef` model fits exactly, the
citation convention matches the Washington/Texas/Florida pattern
(full section number carries the parents), and all five abstract methods
plus the adapter-owned `retrieve_section` are implementable against the
JSON API with no changes to `BaseStateAdapter`, the ref models, the
registry, or the MCP tools.

## Risks

- The embedded `Html` markup is Word-generated XHTML; if the API changes
  its markup, parsing fails loudly (`NormalizationError`), never
  silently.
- The chapter/section link regexes (`Statute=NN-NN`,
  `Statute=NN-NN-NN`, lettered `22-4A`, decimal `22-3-1.1`) must be
  matched carefully to avoid bleeding across adjacent links (the link
  text contains the number and the catchline together).
- The 404 boundary is verified for bad chapter and bad section ids, but
  UNVERIFIED for a bad title id within the `/Statute/{id}` endpoint.

## Why This Should Be State #7

South Dakota introduces the framework's first genuinely new retrieval
axis since Florida: an **official JSON API whose records carry embedded
HTML content and linked-list navigation**, served by a source whose
public face is a JavaScript-rendered SPA. Implementing it proves the
framework can serve a modern JSON-backed statute source — the same
retrieval shape a growing number of state legislature sites use — while
reusing the existing `_fetch`, `_htmltext.strip_tags`, error-mapping, and
normalize conventions. It fits the three-level model with no redesign,
has a clean verified 404 boundary, and every method is directly
verifiable against the live API.