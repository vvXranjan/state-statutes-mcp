# North Dakota Statute Source Research

Research performed: Aug 15, 2026. The live host (`https://ndlegis.gov`)
IS reachable from this environment, so official API responses were
captured live and inspected. The bulk JSON was downloaded in full once
(~70 MB) and inspected; a trimmed copy (records preserved verbatim) is
kept under `tests/fixtures/nd_century_code_trimmed.json` for the offline
test suite.

## Status

**VERIFIED live** for the core discovery and retrieval paths: the bulk
`century_code.json` structure (titles -> chapters -> sections), title/
chapter/section identity fields, repealed-chapter handling, section
heading/body fields, and the reserved-section empty-text case. All
verified from the live official `ndlegis.gov` JSON response.

**UNVERIFIED** for a small set of secondary questions: whether the full
69-title bulk has any sections whose `text`/`html` diverge from the
sampled patterns, whether any title is missing a `title_name`, and
whether the chapter-level `source_url` (a PDF) is ever the appropriate
retrieval target (this adapter does not fetch PDFs).

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- API: `https://ndlegis.gov/api/data/century_code.json` — a single bulk
  JSON document containing the entire North Dakota Century Code
  (N.D.C.C.), one HTTP GET, no pagination, no authentication. VERIFIED
  live (HTTP 200; ~70 MB body).
- Note: `https://www.ndlegis.gov/...` (with `www.`) responds 301 to the
  canonical host `https://ndlegis.gov/...`; this adapter uses the
  non-`www` canonical URL. VERIFIED.
- The site names the corpus "North Dakota Century Code" / "N.D.C.C." and
  the citation form is `N.D.C.C. § {title}-{chapter}-{section}` (e.g.
  `N.D.C.C. § 4.1-02-16`). INFERENCE from standard North Dakota citation
  usage and the bulk's own section `id` form.

## Accessibility

- Fully reachable from this environment: the bulk URL returned HTTP 200.
  VERIFIED.
- No authentication or API key; a single plain GET. VERIFIED.

## Hierarchy

Three structural levels, matching the framework directly:

- **Title** — top level. The bulk has 69 titles (e.g. `1`, `4.1`,
  `30.1`), each keyed by its `title_num` and carrying a `title_name`.
  VERIFIED (69 titles in the live bulk).
- **Chapter** — grouping within a title, e.g. title 1 has chapters `01`,
  `08`; title 4.1 has chapters `01`, `89`; title 30.1 has chapter `04`.
  Each chapter carries `chapter_num`, `chapter_title`, a `source_url`
  (a per-chapter PDF), a `repealed` boolean, and a `sections` map.
  VERIFIED. **778 chapters are repealed and carry ZERO sections** in the
  live bulk (VERIFIED from the full capture).
- **Section** — the individually retrievable unit, e.g. `1-01-01`,
  `4.1-02-16`, `30.1-04-08`. Section identifiers are the full
  `{title}-{chapter}-{section}` form, carried verbatim in each section's
  `id` field. VERIFIED.

## URL Scheme

- This adapter retrieves ONE URL — the bulk `century_code.json` — for
  every level. `build_url` therefore returns the bulk URL for all three
  ref types; `list_titles`, `list_chapters`, `list_sections`, and
  `retrieve_section` all read from the single fetched document. The
  chapter-level `source_url` field is a PDF link and is NOT used as a
  fetch target. This is an adapter-internal decision, documented here and
  in the adapter module docstring.

## Verified JSON Structure

```json
{
  "last_updated": "2026-07-31T11:12:02",
  "titles": {
    "1": {
      "title_num": "1",
      "title_name": "General Provisions",
      "chapters": {
        "01": {
          "id": "1-01",
          "chapter_num": "01",
          "chapter_title": "General Principles And Definitions",
          "source_url": "https://ndlegis.gov/cencode/t01c01.pdf",
          "repealed": false,
          "sections": {
            "01": {
              "id": "1-01-01",
              "section_num": "01",
              "title": "This act - How referred to",
              "page": 1,
              "text": "This revision, whenever cited, enumerated, ...",
              "html": "This revision, whenever cited, ... &quot;North Dakota Century Code&quot;..."
            }
          }
        }
      }
    }
  }
}
```

- Section keys: `id` (full citation, e.g. `1-01-01`), `section_num`
  (e.g. `01`), `title` (the heading, e.g. `This act - How referred to`),
  `page`, `text` (plain body), `html` (same body with HTML markup such as
  `<ol><li>` for enumerated items and `&quot;` entities). VERIFIED.
- Section `text` is the plain body WITHOUT the citation prefix and
  WITHOUT a history line. It may contain PDF-extraction artifacts such as
  double spaces (e.g. `1.To  receive  a  refund`). VERIFIED.
- Section `html` is the structured equivalent (e.g.
  `<ol><li>The  commissioner  shall  establish  a program...</li></ol>`).
  VERIFIED.
- `last_updated` records when the bulk was generated (e.g.
  `2026-07-31T11:12:02`). VERIFIED.
- Repealed chapters carry `"repealed": true` and an EMPTY `sections`
  object (zero sections). VERIFIED (e.g. title 2, chapter 01).
- **Reserved sections** exist with BOTH `text` and `html` empty, e.g.
  `30.1-04-08` with `title: "(2-108) Reserved"`. VERIFIED. An empty body
  after cleaning raises `NormalizationError` in the adapter.

## Heading / Body / History Parsing

- `heading` = the section's `title` field (e.g. `This act - How
  referred to`, `(2-108) Reserved`). VERIFIED.
- `text` (body) = the section's `text` field, preserved verbatim
  (including any double-space artifacts), since the bulk provides the
  body directly and there is no citation prefix or history line to strip.
  VERIFIED.
- `amendment_notes` = None: sections in the bulk carry no history line.
  VERIFIED on all sampled sections.

## Citation

- Citation form: `N.D.C.C. § {title}-{chapter}-{section}` (e.g. `N.D.C.C.
  § 1-01-01`, `N.D.C.C. § 4.1-02-16`), adapter-constructed from
  `ref.identifier`; `N.D.C.C.` is the standard citation abbreviation,
  INFERENCE from standard North Dakota citation usage. The `{title}-{chapter}-{section}`
  form is VERIFIED from the bulk's own `id` fields.
- `SectionRef.identifier` is the full `id` (e.g. `"1-01-01"`,
  `"4.1-02-16"`). VERIFIED.

## Error Boundary

- Because every level lives in one bulk document, "not found" means the
  ref's key is absent from the fetched structure: a missing title,
  chapter, or section raises `RefNotFoundError`. VERIFIED structure
  supports this distinction.
- A repealed chapter (zero sections) is a valid, present chapter;
  `list_sections` returns an empty tuple rather than raising. INFERENCE
  from the verified `"repealed": true` / empty-`sections` structure.
- Network failures surface as `AdapterUnavailableError` via the shared
  `_fetch` helper.

## Known Limitations

- Retrieving any level requires fetching the entire bulk (~70 MB) on each
  call; there is no per-section endpoint. This is inherent to the source
  and documented.
- The chapter `source_url` is a PDF link; this adapter never fetches it.
- The heading/body split relies on the bulk's clean `title`/`text`
  separation, which is verified for the sampled sections but not
  exhaustively.
- Reserved sections (empty `text`/`html`) are surfaced as
  `NormalizationError` rather than skipped, so callers know the source
  has no content for that section.
