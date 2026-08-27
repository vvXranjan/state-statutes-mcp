# California — Research & Implementation Notes

Status: **IMPLEMENTED** — state #38.

## Official source

- **Endpoint**: `https://leginfo.legislature.ca.gov/faces/…`
- **Publisher**: California Legislative Information (California Legislature).
- **Source type**: Official server-rendered HTML of the California Codes
  (Business and Professions, Civil, Code of Civil Procedure, Commercial,
  Corporations, Education, Elections, Evidence, Family, Financial, Fish and
  Game, Food and Agricultural, Government, Harbors and Navigation, Health
  and Safety, Insurance, Labor, Military and Veterans, Penal, Probate,
  Public Contract, Public Resources, Public Utilities, Revenue and
  Taxation, Streets and Highways, Unemployment Insurance, Vehicle, Water,
  Welfare and Institutions — 29 statute codes).
- **Authentication**: None.
- **API key**: None.
- **Bulk archive**: NOT required — the site exposes deterministic
  per-section pages; the 1.1 GB bulk archive is never touched.

## Source accessibility (LIVE)

The host is reachable from this environment (HTTP 200). All structures were
verified against real live captures taken **Aug 27 2026** from this
environment. `robots.txt` disallows bulk crawling (`Disallow: /`,
`Crawl-Delay: 10`); the adapter performs targeted single-document requests
only.

## Discovery mechanism (VERIFIED live)

| Level | Endpoint | Result |
|-------|----------|--------|
| Codes | `faces/codesTOC.xhtml` | 30 codes (`tocCode={CODE}&tocTitle={NAME}`); CONS (Constitution) excluded from statutes |
| Full code tree | `faces/codedisplayexpand.xhtml?tocCode=BPC` | Entire tree in ONE request: 992 fetchable `codes_displayText` documents for BPC |
| Document | `faces/codes_displayText.xhtml?lawCode={CODE}&division={D}&part={P}&chapter={C}&article={A}` | Full server-rendered text of one article / chapter / part / division / General Provisions; sections listed as `submitCodesValues('{N}.', …)` anchors |
| Section | `faces/codes_displaySection.xhtml?lawCode={CODE}&sectionNum={N}` | One complete section, server-rendered |

The site's own dotted hrefs (`division=3.&chapter=1.&article=1.`) and
dotless forms (`division=3&chapter=1&article=1`) return identical pages;
the adapter uses the clean dotless canonical form.

## Hierarchy mapping (folded)

Real structure: `Code -> Division -> Chapter -> Article -> Section`, plus an
optional `Part` level and a top-level `General Provisions` node. Folded
onto the framework's three-level model with NO framework changes:

- **TitleRef = Code** (e.g. `"BPC"`, `"CIV"`, `"PEN"`, `"VEH"`, `"GOV"`,
  `"WIC"`). 29 statute codes; `CONS` is excluded and rejected.
- **ChapterRef = one fetchable document**, identifier =
  `"{division}/{part}/{chapter}/{article}"` (e.g. `"3//1/1"` for Division 3,
  Chapter 1, Article 1; `"///"` for the General Provisions; `"4/3//"` for
  Division 4, Part 3; `"3//2.7/"` for a no-article chapter). Decimal
  components preserved (`1.5`, `10.7`, `2.7`).
- **SectionRef.identifier = section number** (e.g. `"5000"`, `"5025.3"`).

Division/Part/Chapter/Article are folded into the ChapterRef identifier;
none becomes a new framework level.

## Section retrieval (VERIFIED live)

`codes_displaySection.xhtml?lawCode={CODE}&sectionNum={N}` returns one
complete section in `<div id="codeLawSectionNoHead">`:

- Breadcrumb `<h4><b>` lines: code name (`… - BPC`), `DIVISION`, `CHAPTER`,
  `ARTICLE`.
- Section heading `<h6 style="float:left;"><b>{N}.  </b></h6>` (the declared
  section number).
- Body `<p>` paragraphs.
- Trailing `<i>` legislative history (e.g. `(Amended by Stats. 2024, Ch.
  586, Sec. 1. (AB 3251) …)`), captured as `amendment_notes`. The
  breadcrumb `<i>` notes (division/chapter/article history) are excluded.

Verified sections: BPC 5000, BPC 5025.3, CIV 43.3, CIV 1624, PEN 187, VEH
23152, GOV 12940, WIC 5325. California sections carry **no catchline/short
title**, so `heading` is `None`.

## Special cases (VERIFIED live)

- **Decimal sections**: `5025.3`, `43.3`, `5000.1`, `5009.5` — all work.
- **Decimal hierarchy**: `article=1.5.`, `chapter=2.7.` — work.
- **No-article chapters** (`3//2.7/` → section 5499.30), **part-level
  documents** (`4/3//` → 11300–11301), **General Provisions** (`///` →
  43 sections), **division-level documents** — all fetchable.
- **Empty intermediate documents** (e.g. BPC Division 6, or a nonexistent
  segment combination) render HTTP 200 with **no section content** —
  `list_sections` returns an empty listing, not an error.
- **Invalid section** (BPC 999999) / **repealed-and-removed section** (PEN
  12020): HTTP 200 with no `codeLawSectionNoHead` block → `RefNotFoundError`
  (identical to the Iowa "repealed = absent" convention).
- **Invalid code** (or lowercase code): the site 302-redirects to
  `codes.xhtml` (followed by the shared fetch helper) → no content →
  `RefNotFoundError`. Codes are validated and upper-cased before any
  request.
- **Leading zeros**: `sectionNum=05000` is NOT `5000` to the site, so the
  adapter canonicalizes (`05000` → `5000`) before requesting and uses the
  canonical form in the returned section ref/citation.
- **Wrong code / wrong section**: the page self-identifies its code
  (breadcrumb) and section (heading); a mismatch → `RefMismatchError`.

## Error mapping

| Condition | Exception |
|-----------|-----------|
| Invalid code / section format / CONS | `RefNotFoundError` |
| Empty section page (no content block) | `RefNotFoundError` |
| Declared section ≠ requested | `RefMismatchError` |
| Declared code ≠ requested | `RefMismatchError` |
| Network failure | `AdapterUnavailableError` |
| Content block malformed (no font block / no declared section / empty body) | `NormalizationError` |

HTTP 200 alone is never treated as success; the content block + declared
code/section are always verified.

## Fixture provenance

All `tests/fixtures/ca_*` files are **real official live captures** of
leginfo.legislature.ca.gov taken **Aug 27 2026** from this environment
(HTTP 200, verbatim HTML). The only modification is that the JSF
`javax.faces.ViewState` hidden-field value is stubbed to reduce size; the
statute HTML is preserved verbatim. They are NOT synthetic. Section pages
include BPC 5000/5025.3, CIV 43.3/1624, PEN 187, VEH 23152, GOV 12940, WIC
5325, an invalid section (BPC 999999, empty), and a repealed section (PEN
12020, empty); the codes index, the full BPC code tree, and document pages
for article 3/1/1, no-article chapter 3/2.7, part 4/3, the General
Provisions, and the empty Division 6 are also captured.

## Performance

- Section fetch: ~160 KB per request (mostly JSF chrome); fine for
  single-document retrieval.
- Full code tree: ~650 KB **once per code** (cached per adapter instance).
- `list_chapters(BPC)` returns 992 document nodes (large JSON response,
  acceptable).
- No rate limiting observed over the verification session.

## Security

- Fixed official host; all input flows through query parameters on known
  endpoint paths only.
- Input validation: code → `[A-Z]{2,4}` uppercase (CONS rejected); section →
  numeric (leading zeros canonicalized); hierarchy segments → numeric/empty.
  No arbitrary hosts, no path traversal, no injected URLs.
- No secrets, credentials, or session tokens.

## Known limitations

- Only BPC (fully) plus representative sections of CIV/PEN/VEH/GOV/WIC were
  live-captured; uniformity across all 29 codes is otherwise UNVERIFIED.
- Some intermediate documents are legitimately empty (e.g. BPC Division 6).
- `robots.txt` disallows crawling; targeted per-document requests only.
- No section catchlines → `heading` is always `None`.
- `list_chapters` returns the full set of fetchable documents (992 for BPC),
  which is large.
- Repealed/removed sections are indistinguishable from never-existent ones
  (both → `RefNotFoundError`), matching the Iowa convention.

## Architecture decision

A single new adapter, `src/state_statutes_mcp/adapters/california/adapter.py`,
using the shared `fetch_url`/`strip_tags` helpers. No changes to
`BaseStateAdapter`, models, registry, MCP schema, `_fetch`, `_htmltext`, or
`_pdftext`. California-specific parsing (the folded document identifiers and
the section-page structure) lives entirely inside the adapter.