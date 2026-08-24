# Alabama — Research & Implementation Notes

Status: **READY FOR IMPLEMENTATION** — implemented as state #35.

## Official source

- **Endpoint**: `https://alison.legislature.state.al.us/graphql`
- **Publisher**: Alabama Legislature / ALISON (Alabama Legislative
  Information System).
- **Source type**: Official GraphQL API (JSON over HTTPS POST).
- **Authentication**: None.
- **API key**: None.
- **Access**: Verified plain-HTTPS POST from this environment (no
  robots/WAF block, no browser/JS requirement at the API layer; the site's
  Next.js front-end is a JS shell, but the GraphQL API it drives is fully
  server-rendered JSON and is directly reachable).

The front-end at `alison.legislature.state.al.us` is a Next.js SPA backed
by this GraphQL endpoint (discovered via the app's
`NEXT_PUBLIC_FE_GRAPHQL_URL` build config). Introspection is disabled, but
the query surface was discovered through error-message probing.

## Discovery

### Query

```graphql
{ codeOfAlabamaTitles }
```

### Response

A single delimited string carrying the entire Code of Alabama table of
contents:

- **Size**: ~4.2 MB, ~59,000 entries, ~10.6 s to retrieve.
- **Entry separator**: `∫`
- **Field separator**: `†`
- **Per-entry format**: `codeId † heading [† sectionRange] [† effectiveDate]`

### Entry shapes (VERIFIED from the full TOC)

| Entry | Shape | Count |
|-------|-------|-------|
| Title | `{codeId}†Title {n}[{letter}] {name}.` | 46 |
| Chapter | `{codeId}†Chapter {n}[{letter}] {name}.†§{range}` | 1,529 |
| Section | `{codeId}†Section {T-C-S} {catchline}.` | 49,271 |
| Article/Division/Part/Subpart | intermediate, folded away | ~8,000 |

- **Titles**: 46 real titles — numeric 1–45 (Title 13 absent; the Criminal
  Code is Title 13A) plus lettered **10A** and **13A**.
- **Chapters**: 1,529, including lettered chapters (**2A**, **2B**, …) and
  ~38 reserved chapters (two-field entries with no section range, e.g.
  `Chapter 6 Reserved.`). A handful of chapters are *named* `Title N …`
  (e.g. `Title 1 Provisions Applicable to Counties Only.` under Title 11)
  and are distinguishable from real titles by their section-range field.
- **Sections**: 49,271, with the full `T-C-S` citation as the leading token
  (e.g. `1-1-1`, `1-1-1.1`, `7-9A-107A`, `31-2A-6a`, `41-9-219-6`,
  `45-57-70.01.`). A trailing sentence period on the citation token is
  stripped. Decimal sections and lettered section suffixes are preserved.
- Sections may carry an effective-date field (a four-field entry with an
  empty third field) or, rarely, a cross-reference field starting with `§`
  (e.g. `Section 45-35A-52 … † §45-35A-51.01`); these must not be confused
  with chapter section ranges.

### Hierarchy

The TOC is **hierarchically ordered**: a title's chapters and their
sections appear before the next title, so parent chains are tracked while
parsing. The framework's three-level model folds the intermediate
Article/Division/Part/Subpart levels away.

**Title 7 (the Uniform Commercial Code) has no Chapter level** — its
hierarchy is `Title → Article → Part → Section`. The adapter exposes one
synthetic chapter equal to the title number (`"7"`, named
`Title 7 sections`), following the same flat-title precedent Oklahoma uses.

## Section retrieval

### Query

```graphql
{ codesOfAlabama(where: { codeId: { eq: <codeId> } }) {
    data { id codeId title content }
  } }
```

### Response

- **Valid codeId**: exactly one record.
  - `id`: the record id.
  - `codeId`: the queried codeId.
  - `title`: `Section {T-C-S} {catchline}.`
  - `content`: the section's HTML text.
- **Invalid codeId**: `data: []` (an empty list, NOT an HTTP error).
- **Wrong-but-valid codeId**: returns a *different* section's record.

### codeId mapping

The TOC codeId for a section equals the queryable `codeId` (verified:
Section 2-1-1 → codeId 17175; Section 1-1-1 → 14515). The adapter builds a
citation → codeId map from the TOC during discovery.

## Error behavior (VERIFIED)

| Source condition | Adapter result |
|---|---|
| Citation absent from TOC (invalid section) | `RefNotFoundError` |
| Invalid codeId → empty `data: []` | `RefNotFoundError` |
| Wrong-but-valid codeId (different section returned) | `RefMismatchError` (mandatory cross-check of returned `codeId` and embedded citation) |
| Network failure / non-2xx / non-JSON | `AdapterUnavailableError` |
| Malformed/unexpected JSON shape | `NormalizationError` |

**Silent fallback**: none observed. An invalid codeId returns an empty
list — never a wrong-but-similar document. The only silent-mismatch risk is
a *mis-specified but valid* codeId, which the cross-check converts into
`RefMismatchError`.

## Repealed sections

A repealed section's `content` is just its repeal note with no substantive
body (verified: Section 4-2-77 →
`Repealed by Act 2000-220, § 48, effective May 13, 2000.`; the `title`
field still carries the (unrepealed-looking) catchline). Following the
Nebraska/North Carolina convention, the repeal note becomes the
`heading` and `text` is empty. `status` remains `UNKNOWN` (the API has no
structural status field; a prose-only signal is not a structural marker).

## Decimal / lettered identifiers

- **Decimal sections**: preserved verbatim (e.g. `1-1-1.1`, `1-1-4.1`,
  11616 present in the full TOC).
- **Lettered titles**: `10A`, `13A`.
- **Lettered chapters**: `2A`, `2B`, … (203 distinct lettered chapter
  identifiers in the full TOC).
- **Lettered section suffixes**: preserved (e.g. `31-2A-6a`; 6 present).
- **Non-`T-C-S` exotic citations**: a handful of local-government sections
  use `T-C-S-X` (4-part) or `T-C.S` (dotted) forms (e.g. `41-9-219-6`,
  `45-82.40`, `45-57-70.01.`); the citation is taken verbatim as the first
  whitespace token after `Section `, so all shapes are preserved without a
  brittle regex.

## Fixture provenance

All `tests/fixtures/al_*` files are **real official captures** of the
ALISON GraphQL API, fetched live on **Aug 24 2026** from this environment:

| Fixture | Content | Source |
|---|---|---|
| `al_toc_trimmed.json` | Real subset of the official TOC string (Titles 1, 4, 7, 10A, 45 + the chapters/sections under them) | `{ codeOfAlabamaTitles }` |
| `al_section_1-1-1.json` | Full API record for Section 1-1-1 (codeId 14515) | `codesOfAlabama` |
| `al_section_1-1-1.1.json` | Full API record for Section 1-1-1.1 (decimal, codeId 60323) | `codesOfAlabama` |
| `al_section_2-1-1.json` | Full API record for Section 2-1-1 (codeId 17175) | `codesOfAlabama` |
| `al_section_4-2-77.json` | Full API record for Section 4-2-77 (**repealed**, codeId 29009) | `codesOfAlabama` |
| `al_section_1-2A-1.json` | Full API record for Section 1-2A-1 (lettered chapter, codeId 30249) | `codesOfAlabama` |
| `al_section_7-1-101.json` | Full API record for Section 7-1-101 (synthetic-chapter title, codeId 15738) | `codesOfAlabama` |
| `al_section_invalid.json` | Real empty response for an invalid codeId (`data: []`) | `codesOfAlabama` |

The full official TOC is ~4.2 MB; the trimmed fixture keeps a real subset
(small enough for the offline test suite). Fixtures are not synthetic, and
production code never references fixture paths.

## Performance

- **Single-section fetch**: ~0.9 s (GraphQL POST).
- **Full TOC**: ~4.2 MB / ~10.6 s.
- **Caching**: the adapter fetches and parses the TOC once per adapter
  instance (instance-local `_toc` cache), so the expensive TOC retrieval is
  not repeated. This is per-instance state (each registry constructs its
  own adapters), not global mutable state.

## Architecture mapping

```
TitleRef = title number (e.g. "1", lettered "10A")
  → ChapterRef = chapter number (e.g. "1", lettered "2A"; Title 7 synthetic "7")
    → SectionRef.identifier = full citation (e.g. "1-1-1", "1-2A-1")
```

- `build_url` returns the single GraphQL endpoint for every ref level (the
  POST body, not the URL, distinguishes the level).
- `list_titles` / `list_chapters` / `list_sections` parse the cached TOC.
- `retrieve_section`: TOC citation → codeId → POST retrieval query →
  cross-check returned codeId + embedded citation → parse HTML `content` →
  normalize.
- `normalize` cross-checks `ref.identifier` against `parsed.raw_citation`
  (`Ala. Code § {T-C-S}`) and raises `RefMismatchError` on disagreement.
- `status` is always `UNKNOWN` (no structural status signal in the source).

## Framework changes

- **No change** to `BaseStateAdapter`, the refs/models, the MCP tool
  contract, the registry, or the PDF/HTML infrastructure.
- **Added** `fetch_graphql` to the shared `adapters/_fetch.py` — the
  framework's first POST transport. It is a pure addition (100% backward
  compatible with the existing `fetch_url`/`fetch_bytes` GET helpers; the
  existing 34 adapters are unaffected), keeps the single network mock
  boundary, and is genuinely reusable for future JSON/GraphQL sources.
- **Added** `mock_urlopen_graphql` to `tests/_mock_network.py` — a pure
  addition that dispatches on the GraphQL query string in the POST body.

## Known limitations

- Only 46 titles / the four targeted sections and the full TOC were
  verified live; the lettered-title and lettered-section structures were
  verified from the TOC string rather than from individual retrieval
  probes (the retrieval cross-check covers them).
- Title 7's synthetic chapter means its chapter identifiers are not
  "real" chapter numbers; the flat mapping is the documented precedent.
- The full TOC is large (~4.2 MB); first discovery per adapter instance
  pays the ~10 s cost once.
- The 8 exotic non-`T-C-S` citations (4-part / dotted forms) are preserved
  verbatim as identifiers; their retrieval is supported (the citation is
  matched verbatim against the returned title).
- A small number of duplicate section citations exist in the full TOC
  (7 confirmed, e.g. `7-10-104`, `45-35A-51.01`): two distinct records can
  share the same `T-C-S` citation. The adapter's `_code_id_for` returns the
  first match, and the retrieval cross-check validates the returned record
  against the requested citation, so a shared citation resolves to the
  first record rather than failing silently.