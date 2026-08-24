# Wyoming — Research & Implementation Notes

Status: **READY FOR IMPLEMENTATION** — implemented as state #36.

## Official source

- **Endpoint**: `https://wyoleg.gov/statutes/compress/title{NN:02d}.pdf`
- **Publisher**: Wyoming Legislature / Wyoming Legislative Service Office.
- **Source type**: Official per-title statute PDFs.
- **Authentication**: None.
- **API key**: None.
- **Access**: Verified plain-HTTPS GET from this environment (no
  robots/WAF block). The general `wyoleg.gov` site is a JS SPA, but the
  per-title PDF corpus under `/statutes/compress/` is served as plain
  static PDFs.

## Source accessibility (VERIFIED)

The per-title PDFs are directly reachable. Valid titles return
`Content-Type: application/pdf`; nonexistent titles return HTTP 200 with
an HTML SPA shell page (`text/html`), so the `%PDF` magic check cleanly
distinguishes valid from invalid titles.

## Valid title set (VERIFIED)

Probing the deterministic `title{NN:02d}.pdf` pattern over the bounded
range 00–99 yields exactly:

- **Titles 01–42** — the numbered statutes.
- **Title 97** — the Wyoming Constitution.
- **Title 99** — Noncodified Statutes.

No valid PDFs exist for titles 43–96, 98, or 100+. The set is
deterministic and small (44 documents), so title discovery is a bounded
probe (HEAD request checking `Content-Type`).

## Deterministic URL pattern

```
https://wyoleg.gov/statutes/compress/title{NN:02d}.pdf
```

The title number is zero-padded to two digits. The adapter validates the
title number (`int()`) before building the URL; the URL is always the
constant trusted pattern — no user-controlled URL is ever fetched.

## Hierarchy

`Title -> Chapter -> [Article] -> Section`:

- **Title** — e.g. `TITLE 1 - CODE OF CIVIL PROCEDURE`.
- **Chapter** — e.g. `CHAPTER 1 - GENERAL PROVISIONS AS TO CIVIL ACTIONS`.
- **Article** — an intermediate grouping (e.g. `ARTICLE 1 - DEFINITIONS`)
  that carries no section-address information; the section citation
  `T-C-S` does not encode the article, so it is **folded away** and not
  exposed as a framework level.
- **Section** — e.g. `1-1-101.  Provisions to be liberally construed.`.

Verified in Title 1: 43 chapters, 64 articles, 1,038 sections.

## Section format

A section citation line is `{T-C-S}.  {Catchline}.` followed by the body;
the next `T-C-S.` line starts the next section. The full citation is used
as `SectionRef.identifier` (e.g. `1-1-101`).

- **Decimal sections** (VERIFIED): `1-1-123.1` through `1-1-123.5`
  (5 in Title 1).
- **Lettered chapters/sections**: none observed in Titles 1, 7, 31, 97, 99;
  the citation regex accepts an optional trailing letter per part
  defensively (no false positives observed).

## Repealed / renumbered sections (VERIFIED)

A repealed or renumbered section's catchline IS the note, with an empty
body:

- `1-1-110.  Repealed by Laws 1986, ch. 24, § 2.`
- `1-12-502.  Renumbered by Laws 1979, ch. 142, § 3.`

Following the Nebraska/North Carolina/Oklahoma convention, the note becomes
the `heading` and `text` is empty. `status` remains `UNKNOWN` (a prose-only
signal is not a structural status marker).

## Invalid-title behavior (VERIFIED)

A nonexistent title number (e.g. 43, 44, 45, 50, 90–96, 98, 100+) returns
HTTP 200 with the 11KB HTML SPA shell (NOT a PDF). The `%PDF` magic check
detects this and maps it to `RefNotFoundError`. No wrong-title PDF, no
redirect, no silent fallback document was observed — title 99 is a real
(noncodified) title, not a fallback.

## Error mapping

| Source condition | Adapter result |
|---|---|
| Nonexistent title (HTML shell, non-PDF) | `RefNotFoundError` |
| Nonexistent section (citation absent from PDF body) | `RefNotFoundError` |
| Wrong-title PDF (PDF self-identifies a different title) | `RefMismatchError` |
| Network failure | `AdapterUnavailableError` |
| Malformed/truncated PDF | `AdapterUnavailableError` |
| Malformed section structure | `NormalizationError` |

## Fixture provenance

All `tests/fixtures/wy_*` files are **real official captures** of the
Wyoming per-title PDFs, fetched live on **Aug 24 2026** from this
environment, re-saved as page-range subsets with pypdf (the established
trimmed-capture pattern used by Oklahoma):

| Fixture | Content | Source |
|---|---|---|
| `wy_title01_ch1.pdf` | Title 1, pages 1–5: CHAPTER 1 + sections 1-1-101..1-1-116 (normal + repealed) | `title01.pdf` |
| `wy_title01_ch1_decimal.pdf` | Title 1, pages 10–14: sections 1-1-123..1-1-124 (decimal 1-1-123.1..5) | `title01.pdf` |
| `wy_title01_renumbered.pdf` | Title 1, page 72: section 1-12-502 (renumbered) | `title01.pdf` |
| `wy_title31_ch1.pdf` | Title 31, pages 1–2: CHAPTER 1 + section 31-1-101 (wrong-title cross-check) | `title31.pdf` |
| `wy_title99_p1.pdf` | Title 99, page 1: `TITLE 99 - NONCODIFIED STATUTES` header (title discovery) | `title99.pdf` |
| `wy_invalid_title.html` | The real HTML SPA shell served for a nonexistent title | `title43.pdf` |

Fixtures are not synthetic, and production code never references fixture
paths.

## Performance

- **Title 1 PDF**: 718 KB / 366 pages; download ~4s, extraction ~1.1s,
  total ~5s (measured live). Larger titles up to ~3 MB.
- **Title discovery**: HEAD probe over 01–99 (one request per title;
  valid titles then need one GET + extract for the name). Cached per
  adapter instance after the first call.
- **Caching**: the adapter fetches and parses a title PDF at most once per
  adapter instance (instance-local `_title_cache`), so repeated section
  retrievals within a title do not re-download. This is per-instance state
  (each registry constructs its own adapters), not global mutable state.
- The existing 60-second timeout is more than adequate (measured retrievals
  are ~5s).

## Architecture mapping

```
TitleRef = title number (zero-padded, e.g. "1", "97", "99")
  → ChapterRef = chapter number (e.g. "1")
    → SectionRef.identifier = full citation (e.g. "1-1-101", "1-1-123.1")
```

Article is folded away. `build_url` returns the per-title PDF URL. The
adapter reuses the existing Oklahoma PDF pipeline unchanged:
`fetch_bytes` → `%PDF` check → `extract_pdf_text` → Wyoming-local parser →
`ParsedDocument` → `normalize`.

## Framework changes

- **None.** `BaseStateAdapter`, the refs/models, the MCP contract, the
  registry, and the shared PDF infrastructure (`_fetch.py`, `_pdftext.py`)
  are all unchanged. Wyoming is a clean, isolated adapter following the
  proven Oklahoma per-title PDF architecture.

## Known limitations

- Per-title PDFs are re-fetched and re-extracted for discovery (one time
  per instance, cached); single-section retrieval fetches the whole title
  PDF (up to ~3 MB / ~5s), the same accepted P2 pattern as Oklahoma.
- Lettered chapters/sections were not observed in the sampled titles; the
  citation regex accepts an optional trailing letter defensively but that
  support is not fixture-verified.
- Title discovery probes 01–99 (bounded); the result is cached per adapter
  instance.
- The sampled PDFs carry no separate session-law history footnotes (this
  "compress" edition is an uncertified printout), so `amendment_notes` is
  `None` for normal sections.