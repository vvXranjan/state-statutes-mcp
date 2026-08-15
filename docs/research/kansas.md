# Kansas Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://www.kslegislature.gov`) IS reachable from this environment, so
official API responses were captured live and inspected. Every URL below
was executed directly against the live site with plain HTTP GETs; the
structure is documented verbatim from those responses, which are the
implementation boundary for this adapter.

## Status

**VERIFIED live** for the core discovery and retrieval paths: the
statutes index (chapter listing), the per-chapter article listing, the
per-article section listing (including its pagination contract), and
single-section retrieval with heading/body/history parsing. All verified
from live HTTP 200 responses of the official `kslegislature.gov` JSON
API.

**UNVERIFIED** for a small set of secondary questions: whether every
chapter/article/section response is paginated identically (sampled
article 1 of chapter 8, which spans two pages), whether every section's
`text` field is formatted identically (sampled `21-5903` and `8-1,208`),
and whether any chapters other than 1-87 exist (the index returns 87
chapters). Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- API base: `https://www.kslegislature.gov/api/v1/statutes/` — the
  official Kansas Legislature JSON API for the Kansas Statutes Annotated
  (K.S.A.).
- The API is a plain JSON-over-HTTP service: no authentication, no API
  key, no JS rendering. VERIFIED (plain GETs returned 200 with JSON
  bodies).
- The site names the corpus "Kansas Statutes Annotated" / "K.S.A." and
  the citation form is `Kan. Stat. Ann. § {chapter}-{section}` (INFERENCE
  from standard Kansas citation usage; the section number form is
  VERIFIED from the API's own `section` field, e.g. `21-5903`).

## Accessibility

- Fully reachable from this environment: every URL below returned HTTP
  200. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, matching the framework directly:

- **Chapter** — the top level. The index (`/api/v1/statutes/`) returns
  87 chapters (e.g. `1` ... `21`, `8`, `60`), each identified by its
  chapter number. VERIFIED (87 results in the index response).
- **Article** — grouping within a chapter, e.g. chapter 21 has articles
  9, 12, 18, 25, 28, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
  64, 65, 66 (and more). VERIFIED (`?chapter=21` returned 24 articles).
- **Section** — the individually retrievable unit, e.g. `21-5903`,
  `8-1,208`. Section identifiers are the full `{chapter}-{number}` form
  (e.g. `21-5903`), where the number part may itself contain a comma used
  as a thousands separator (e.g. `8-1,208`). VERIFIED.

This adapter maps Chapter -> Article -> Section onto the framework's
TitleRef -> ChapterRef -> SectionRef directly (Chapter becomes the
synthetic TitleRef), the same flattening done for other two-level-plus
states. This is an adapter-internal mapping, documented here and in the
adapter module docstring.

## URL Scheme

- Index / chapter listing: `https://www.kslegislature.gov/api/v1/statutes/`
  (200). Returns `{count, results:[{chapter, caption, section_count, href}]}`.
  VERIFIED.
- Article listing: `https://www.kslegislature.gov/api/v1/statutes/?chapter={N}`
  (200). Returns `{chapter, caption, count, results:[{article, caption,
  section_count, href}]}`. VERIFIED.
- Section listing: `https://www.kslegislature.gov/api/v1/statutes/?chapter={N}&article={M}`
  (200). Returns `{chapter, chapter_caption, article, article_caption,
  count, next_offset, previous_offset, results:[{number, caption, url}]}`.
  VERIFIED.
- Section detail: `https://www.kslegislature.gov/api/v1/statutes/{section}/`
  (200). Returns `{section, chapter, rest, text, url}`. VERIFIED.
- **Pagination**: the section listing is paginated at 200 results per
  page via `next_offset`/`previous_offset` and an `offset` query
  parameter. VERIFIED: article 1 of chapter 8 has `count: 219`, first
  page `next_offset: 200`; `?chapter=8&article=1&offset=200` returns the
  remaining 19 with `next_offset: null`. The article listing (`?chapter=`)
  shows NO pagination fields in the verified sample (24 articles).
- **Comma encoding**: a comma inside a section number MUST be URL-encoded
  (`%2C`). VERIFIED: `/api/v1/statutes/8-1,208/` (raw comma) returns HTTP
  404, while `/api/v1/statutes/8-1%2C208/` returns HTTP 200. A bare
  chapter-only path like `/api/v1/statutes/21/` returns HTTP 400.

## Verified JSON Structures

### Index (`/api/v1/statutes/`) — chapter listing

```json
{"count": 87, "results": [{"chapter": 1, "caption": "", "section_count": 26, "href": "/api/v1/statutes/?chapter=1"}, ...]}
```

`chapter` is an int; `caption` is always an empty string in the verified
response. VERIFIED.

### Article listing (`/api/v1/statutes/?chapter=21`)

```json
{"chapter": 21, "caption": "", "count": 24, "results": [{"article": 9, "caption": "", "section_count": 1, "href": "/api/v1/statutes/?chapter=21&article=9"}, ...]}
```

`article` is an int; `caption` is always an empty string in the verified
response. VERIFIED.

### Section listing (`/api/v1/statutes/?chapter=8&article=1`)

```json
{"chapter": 8, "chapter_caption": "", "article": 1, "article_caption": "", "count": 219, "next_offset": 200, "previous_offset": null, "results": [{"number": "8-113a", "caption": "Reporting stored, unclaimed vehicles...", "url": "/laws/008_000_0000_chapter/..."}]}
```

`number` is the full `{chapter}-{number}` identifier (e.g. `8-113a`,
`8-1,208`); `caption` may be empty for some sections (e.g. `21-5901`,
`21-5906`). VERIFIED.

### Section detail (`/api/v1/statutes/21-5903/`)

```json
{"section": "21-5903", "chapter": "21", "rest": "5903", "text": "21-5903. Perjury. (a) Perjury is intentionally and falsely:...(b) Perjury is a:...History: L. 2010, ch. 136, § 128; L. 2013, ch. 3, § 1; L. 2018, ch. 116, § 6; July 1.", "url": "/laws/21_000_0000_chapter/"}
```

- `section` is the full identifier (matches the requested ref).
- `chapter` is the top-level chapter number (matches the flattened
  TitleRef identifier).
- `text` is ONE plain-text string: `"{section}. {heading} {body}History: ..."`.
  The heading is the section's caption (e.g. `Perjury.`, `Daughters of
  the American revolution license plate; requirements.`), the body is the
  statutory text (subsections like `(a)`, `(1)`, `(2)` inline, no
  line breaks), and the trailing `History: ...` block is the amendment
  history. VERIFIED for `21-5903` and `8-1,208` (both end with a
  `History: L. ..., ch. ..., § ...; July 1.` line).
- A nonexistent section returns HTTP 404 with
  `{"detail": "K.S.A. 99-9999 has no archived text."}`. VERIFIED. Mapped
  to `RefNotFoundError` in the adapter.
- The `url` field is a relative path; the adapter uses the fetched URL as
  `source_url` instead.

## Heading / Body / History Parsing

The `text` field has a consistent prefix, verified in both samples:
`{section}. ` then the heading, then a subsection marker (e.g. ` (a)`),
then the body, then `History: ...`. The adapter:

1. Confirms `text` starts with `"{ref.identifier}. "` (cross-checks the
   citation before parsing — a mismatch is a `RefMismatchError`).
2. Strips that prefix.
3. Splits heading from body at the first `(a)`-style subsection marker
   (`\. (?=\()`), giving `heading="Perjury."` and body starting at
   `(a) ...`. (INFERENCE: this is the boundary in both verified samples;
   a section whose heading itself contains `(a)` is not verified.)
4. Splits `History:` (the LAST occurrence) out of the body into
   `amendment_notes`, preserving it verbatim. Both verified samples have
   exactly one trailing `History:` block.
5. If a section has no `History:` block, `amendment_notes` is None.

## Citation

- Citation form: `Kan. Stat. Ann. § {chapter}-{number}` (e.g. `Kan.
  Stat. Ann. § 21-5903`, `Kan. Stat. Ann. § 8-1,208`), adapter-constructed
  from `ref.identifier`; `Kan. Stat. Ann.` is the standard citation
  abbreviation, INFERENCE from standard Kansas citation usage (the API
  itself names the corpus "Kansas Statutes Annotated"). The section
  number form is VERIFIED from the API's own `section` field.
- `SectionRef.identifier` is the full `{chapter}-{number}` identifier as
  it appears in the section listing and section detail (e.g. `"21-5903"`,
  `"8-1,208"`). VERIFIED.

## Error Boundary

- A missing section returns HTTP 404 (VERIFIED), mapped to
  `RefNotFoundError`.
- A raw comma in a section path returns HTTP 404 (VERIFIED); a bare
  chapter-only path returns HTTP 400 (VERIFIED) — both surfaced as
  `AdapterUnavailableError` by the shared fetch helper.
- Network failures surface as `AdapterUnavailableError` via the shared
  `_fetch` helper.

## Known Limitations

- The synthetic title mapping (Chapter as `TitleRef`) means titles
  returned by `list_titles` are Kansas's official chapters, not
  "titles" in the traditional sense; this is a documented adapter-level
  mapping, not a framework change.
- Chapter and article captions are always empty in the verified API
  responses, so `list_titles`/`list_chapters` names fall back to the
  identifier; only sections carry usable captions.
- Section captions are empty for some sections (e.g. `21-5901`,
  `21-5906`); those names also fall back to the identifier.
- The heading/body boundary relies on the first ` (a)`-style marker,
  which is verified for the two sampled sections but not for every
  section; a section whose heading contains a parenthetical that looks
  like a subsection marker would be mis-split (not verified to occur).
- Section listing pagination beyond the two verified pages (200 + 19) is
  inferred from the `next_offset`/`offset` contract, not exhaustively
  observed.
