# Colorado — Research & Implementation Notes

Status: **IMPLEMENTED** — state #37.

## Official source

- **Endpoint**: `https://content.leg.colorado.gov/sites/default/files/images/olls/crs2024-title-{NN}.pdf`
- **Publisher**: Colorado Office of Legislative Legal Services (OLLS).
- **Source type**: Official per-title PDFs of the Colorado Revised Statutes (CRS) 2024.
- **Authentication**: None.
- **API key**: None.

## Source accessibility (ARCHIVED)

The live host (`content.leg.colorado.gov`) returns an **AWS WAF HTTP 403** to
this environment for BOTH valid and invalid title URLs (identical 118-byte
HTML response, `awselb/2.0`). The real source-level invalid-title HTTP
behavior is therefore **UNVERIFIED** from this environment. All structure
verification and all fixtures below are based on **real archived official
captures** of the per-title PDFs, retrieved via the Wayback Machine on
**Aug 24 2026** — they are archived captures, NOT live captures.

## Valid title set (VERIFIED via archived captures)

The deterministic `crs2024-title-{NN}.pdf` pattern serves genuine CRS title
PDFs. Titles 1, 8, and 42 were verified as genuine CRS documents (Title 1 =
561 pages / ~3.3 MB; Title 8 = 795 pages / ~4.45 MB; Title 42 = 834 pages /
~4.67 MB). The published CRS title range is 01-42, 97, 99 (per archived
OLLS material); only the sampled titles were individually verified.

## Hierarchy

`Title -> Article -> Part -> Section`:

- **Title** — e.g. `TITLE 42` / `VEHICLES AND TRAFFIC`.
- **Article** — e.g. `ARTICLE 1 / General and Administrative`. Articles can
  be decimal (e.g. `ARTICLE 1.5`), which is preserved in the ChapterRef
  identifier (e.g. `"1.5"`).
- **Part** — e.g. `PART 1 / DEFINITIONS AND CITATION`. Part is a structural
  grouping that is NOT encoded in the section citation, so it is folded away
  (not exposed as a framework level).
- **Section** — e.g. `42-1-101.  Short title.`.

The section citation `T-A-S` **encodes the Article** as its middle component
(e.g. `42-1-102` = Title 42, Article 1, Section 102). This is the
adapter's ChapterRef mapping: `ChapterRef = Article` (decimal articles
preserved).

## Section format

A section citation line is `{T-A-S}.  {Catchline}.` followed by the body;
the next section citation starts the next section. Verified forms:

- **Normal**: `42-1-101.  Short title.` / `1-1-101.  Short title.`
- **Decimal section**: `42-1-218.5.  Electronic hearings.` / `1-1-105.5.`
- **Decimal article**: `1-1.5-101.  Legislative declaration.`
- **Range repeal**: `1-1-401 to 1-1-403. (Repealed)`
- **History**: `Source: L. 92: ...` and `Editor's note: ...` lines follow
  the body; captured as `amendment_notes`.
- **Repealed**: catchline ends with `(Repealed)` (e.g.
  `1-1-112.  Powers and duties of election commission. (Repealed)`) with a
  Source/Editor's-note block and no substantive body.

## Merged page footer (VERIFIED)

Every page ends with `Colorado Revised Statutes 2024 Page {n} of {m}
Uncertified Printout` which is **concatenated onto the start of the next
text line** (no newline). The parser strips this prefix from any line that
begins with it (834 occurrences in Title 42).

## Error mapping

| Source condition | Adapter result |
|---|---|
| Nonexistent title / non-PDF response (HTML shell) | `RefNotFoundError` |
| Nonexistent section (citation absent from PDF body) | `RefNotFoundError` |
| Wrong-title PDF (PDF self-identifies a different title) | `RefMismatchError` |
| Network failure | `AdapterUnavailableError` |
| Malformed/truncated PDF | `AdapterUnavailableError` |
| Malformed section structure | `NormalizationError` |

The invalid-title gate (live 404/redirect/fallback for a nonexistent title)
remains **UNVERIFIED** behind the AWS WAF. The adapter's `%PDF` magic check
handles any non-PDF response as `RefNotFoundError` regardless of the exact
live HTTP status.

## Fixture provenance

All `tests/fixtures/co_*` files are **real archived official captures** of
the official CRS per-title PDFs (and the real WAF HTML response), retrieved
via the Wayback Machine on **Aug 24 2026** from this environment, re-saved
as page-range subsets with pypdf:

| Fixture | Content | Source |
|---|---|---|
| `co_title01_p1.pdf` | Title 1 page 1: `TITLE 1 / ELECTIONS` header | archived title01 |
| `co_title01_ch1.pdf` | Title 1 pages 2-4: ARTICLE 1, PART 1, 1-1-101.. | archived title01 |
| `co_title01_decimal.pdf` | Title 1 pages 13-15: 1-1-105.5 | archived title01 |
| `co_title01_repealed.pdf` | Title 1 pages 19-21: 1-1-112 (Repealed) | archived title01 |
| `co_title01_range.pdf` | Title 1 pages 25-27: 1-1-401..403 (range), 1-1.5-101 | archived title01 |
| `co_title42_ch1.pdf` | Title 42 pages 1-3: ARTICLE 1, 42-1-101, 42-1-102 | archived title42 |
| `co_title42_decimal.pdf` | Title 42 pages 29-31: 42-1-218.5 | archived title42 |
| `co_invalid_title.html` | The real 118-byte AWS WAF 403 HTML response | live WAF |

Fixtures are not synthetic, and production code never references fixture
paths.

## Performance

- **Title 1**: 561 pages / ~3.3 MB; extraction ~8s (measured on the
  archived capture).
- **Title 42**: 834 pages / ~4.67 MB; extraction ~12s (measured on the
  archived capture).
- **Title 8**: 795 pages / ~4.45 MB; extraction ~11s.
- These are within the existing 60-second timeout used by the PDF-family
  adapters. The adapter caches extracted title text per adapter instance.

## Architecture mapping

```
TitleRef = title number (zero-padded, e.g. "1", "42")
  → ChapterRef = Article (e.g. "1", decimal "1.5")
    → SectionRef.identifier = full citation (e.g. "42-1-101", "42-1-218.5",
                                 "1-1.5-101")
```

Part is folded away. `build_url` returns the per-title PDF URL. The adapter
reuses the existing PDF pipeline unchanged: `fetch_bytes` → `%PDF` check →
`extract_pdf_text` → Colorado-local parser → `ParsedDocument` → `normalize`.

## Framework changes

- **None.** `BaseStateAdapter`, the refs/models, the MCP contract, the
  registry, and the shared PDF infrastructure are all unchanged. Colorado
  is a clean, isolated adapter following the proven per-title PDF
  architecture.

## Known limitations

- The live invalid-title HTTP behavior is UNVERIFIED (AWS WAF blocks this
  environment for both valid and invalid URLs). The adapter treats any
  non-PDF response as `RefNotFoundError`, which is correct regardless of the
  exact live status.
- Per-title PDFs are re-fetched and re-extracted per retrieval (up to
  ~4.7 MB / ~12s), the same accepted P2 pattern as Oklahoma/Wyoming; title
  text is cached per adapter instance.
- Only Titles 1, 8, 42 (and trimmed page-range slices) were sampled;
  per-title PDF uniformity is otherwise UNVERIFIED.