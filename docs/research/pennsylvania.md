# Pennsylvania — Research & Implementation Notes

Status: **IMPLEMENTED** — state #41.

## Official source

- **Endpoint**: `https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/{TT}/00.{chapter}.{local}.{decimal}..HTM`
- **Publisher**: Pennsylvania General Assembly / Legislative Data Processing
  Center (LDPC). The consolidated statutes are served as static,
  server-rendered HTML — one page per section. The current front-end is
  `www.palegis.us` (which references `www.legis.state.pa.us` as its content
  server and navigates to the legacy pages with a `?{n}` cache-buster), so
  the legacy host is the same official statute system.
- **Source type**: Official server-rendered HTML over ordinary HTTP GETs.
- **Authentication**: None.
- **API key**: None.

## Source accessibility (ARCHIVED)

The live hosts (`www.legis.state.pa.us` and `www.palegis.us`, both resolving
to `216.157.112.153`) are **TCP-blocked** from this environment (connection
timeouts on ports 80 and 443; the block is specific to that IP — `www.pa.gov`
and `www.pacode.com` are reachable). Save-Page-Now is rate-limited/blocked.
All structure verification and all fixtures below are based on **real
archived official captures** of the official host, retrieved via the Wayback
Machine in **Aug 2026** — they are archived captures, NOT live captures (the
Colorado/Michigan/Alaska precedent).

## Encoding (VERIFIED)

The official pages declare and are served as **UTF-8** (the shared
`fetch_url` is used directly). The `§` markers are ASCII-safe entities
(`&#167;`).

## Discovery (VERIFIED via archived captures)

| Level | Endpoint | Contents |
|-------|----------|----------|
| Titles | `{TT}/00.001..HTM` (probing 0-87) | title document; `<title>` = `Chapter 1[.] - [Title {t} - ]{NAME}` (e.g. `Chapter 1. - Title 15 - CORPORATIONS AND UNINCORPORATED ASSOCIATIONS`; title 0 = `Chapter 1. - CONSTITUTION OF PENNSYLVANIA`) |
| Chapters | `{TT}/00.{c}.001.000..HTM` (probing 1-99) | chapter index; `CHAPTER {c}` header + chapter name (e.g. `CHAPTER 27` / `ASSAULT`), followed by the section list |
| Sections | `{TT}/00.{c}.001.000..HTM` | the chapter index lists every section as `{n}. {catchline}.` rows (decimal sections included, e.g. `2702.1. Assault of law enforcement officer.`) |

Title discovery probes titles 0-87 (title pages verified to serve the title
name for titles 0, 15, 18, 42; titles 19/21/41/55/56 are repealed and simply
probe as absent). Chapter discovery probes chapters 1-99 and validates each
page's `CHAPTER {c}` header against the probed number (valid chapter-index
pages verified current, e.g. title 18 chapter 27 on 2024-05-31). Both
mechanisms filter every non-valid response by identity parsing (a probe that
returns the official "Page Not Found" page, HTTP 404, or a cross-chapter
fallback yields no matching identity and is skipped) — the Colorado probing
precedent. The exact terminal response of an invalid *chapter* probe (vs.
the verified invalid-*section* 302 -> 404 behavior) is unobservable from the
archive; the mechanisms are correct-by-design regardless.

## Section retrieval (VERIFIED via archived captures)

The per-section URL is fully deterministic from the citation:

```
citation {S} (e.g. '2707', '2702.1', '2109.1')
chapter = int(S) // 100
local   = int(S) % 100
decimal = the decimal component (0 if absent)
URL     = {TT}/00.{chapter:03d}.{local:03d}.{decimal:03d}..HTM
```

Verified against 10+ citations across titles 18/20/42 (e.g. `18 § 2707` ->
`18/00.027.007.000..HTM`, `18 § 1102.1` -> `18/00.011.002.001..HTM`,
`20 § 2101` -> `20/00.021.001.000..HTM`, `42 § 321` -> `42/00.003.021.000..HTM`).

The section page self-identifies in its `<title>` as
`Section {n}[.{d}] - Title {t} - {NAME}` (current pages render
`Section 2707.0 - Title 18 - CRIMES AND OFFENSES`; older captures and the
Constitution omit the `.0` / the `Title {t}`), carries a
`§ {n}. {catchline}.` heading followed by the body, and closes with the
legislative history (`(July 16, 1975, P.L.62, No.37; ...)` and
`{Year} Amendment.` notes). Anchor comments (`18c2707s` / `18c2707v`) carry
no readable text.

## Hierarchy

`Title -> Part -> Chapter -> Subchapter -> Section`. The citation encodes
its chapter directly (`chapter = int(section) // 100`). Part and Subchapter
are structural groupings NOT encoded in the citation, so they are folded
away. Maps directly onto the framework:
- **TitleRef = title number** (0-87, as the site numbers them; 0 is the
  Constitution). The URL path zero-pads the title to two digits (`0` ->
  `00`, `1` -> `01`).
- **ChapterRef = chapter number** (e.g. `"27"`).
- **SectionRef.identifier = full section citation** (e.g. `"2707"` or
  `"2702.1"`), preserving the decimal component.

## Special cases (VERIFIED via archived captures)

- **Decimal sections** (VERIFIED): `18 § 1102.1` ->
  `18/00.011.002.001..HTM` (identity `Section 1102.1 - Title 18`), and the
  chapter indexes list decimals (`2702.1.`, `2707.1.`, `2109.1.`). The
  fourth URL component is the zero-padded decimal (`1` -> `001`).
- **Repealed sections** (VERIFIED): a repealed section (e.g. `18 § 4321`,
  "Nonsupport", repealed 1985) returns **HTTP 200** with the identity
  `Section 4321 - Title 18 - CRIMES AND OFFENSES` and a structural repeal
  stub — `SUBCHAPTER B NONSUPPORT (Repealed)` plus a `1985 Repeal Note.`
  block giving the history and the relocation of the subject matter. The
  adapter preserves the repeal note as the text, leaves the heading empty,
  and sets `status = REPEALED` (a structural signal, not prose inference).
- **Invalid sections** (VERIFIED): a nonexistent citation (e.g. `18 § 5003`
  -> `18/00.050.003.000..HTM`, chapter 50 does not exist) returns **HTTP 302
  -> `/cfdocs/Errors/404.html`**, which serves the official "Page Not Found
  - PA General Assembly" page with HTTP 200 (captured 2024-03-28). The
  adapter content-detects that page and maps it to `RefNotFoundError`, and
  also maps a direct HTTP 404 via the Iowa/Michigan `HTTPError.__cause__`
  pattern.
- **Silent fallback**: none observed in the archived corpus. The adapter
  ALWAYS content-verifies the returned page's `Section {n}[.{d}]` identity
  and (when present) `Title {t}` against the request — a chapter-index page
  (whose identity is the chapter's first section) or a neighboring section
  can never be silently accepted (`RefMismatchError`). HTTP 200 alone is
  never treated as success.
- **Lettered citations/chapters**: lettered section citations were not
  observed and are rejected. Lettered chapters (e.g. Title 53 Chapter 57A)
  are not enumerated by the numeric probing, and their legacy URL encoding
  is unverified (the palegis side uses `chpt=57A`); this is a documented
  limitation.

## Error mapping

| Condition | Exception |
|-----------|-----------|
| Invalid citation / chapter / title format | `RefNotFoundError` |
| HTTP 404 on a section citation (nonexistent) | `RefNotFoundError` |
| Official "Page Not Found - PA General Assembly" page | `RefNotFoundError` |
| Page with no `Section {n}` identity | `RefNotFoundError` |
| Declared section identity != requested | `RefMismatchError` |
| Declared title (when present) != requested title | `RefMismatchError` |
| Ref chapter != citation's chapter | `RefMismatchError` |
| Network failure / non-404 HTTP error | `AdapterUnavailableError` |
| Declared section but no heading and no repeal marker | `NormalizationError` |
| Declared section but empty body (non-repealed) | `NormalizationError` |

## Fixture provenance

All `tests/fixtures/pa_*` files are **real archived official captures** of
legis.state.pa.us retrieved via the Wayback Machine in **Aug 2026** (the
`id_` replay bytes, gunzipped). They are NOT synthetic and NOT live
captures. The set:

| Fixture | Capture timestamp | Content |
|---------|-------------------|---------|
| `pa_title_00.html` | 2023-10-04 | Constitution title page (`00/00.001..HTM?78`) |
| `pa_title_18.html` | 2010-08-13 | Title 18 title page (`18/00.001..HTM`) |
| `pa_chapter_index.html` | 2024-05-31 | Title 18 chapter 27 index (`18/00.027.001.000..HTM?88`), 25 sections incl. decimals |
| `pa_section_2707.html` | 2026-03-07 | `18 § 2707` normal section (`18/00.027.007.000..HTM`) |
| `pa_section_1102_1.html` | 2017-04-03 | `18 § 1102.1` decimal section (`18/00.011.002.001..HTM`) |
| `pa_section_4321.html` | 2012-02-20 | `18 § 4321` repealed stub (`18/00.043.021.000..HTM`) |
| `pa_404.html` | 2024-03-27 | official "Page Not Found - PA General Assembly" page (`/cfdocs/Errors/404.html`) |

No statute text was fabricated.

## Performance

- Section pages: ~4-11 KB (light).
- Chapter index pages: ~15 KB.
- Title pages: 27-350 KB.
- Discovery: `list_titles` probes titles 0-87 (cached per instance);
  `list_chapters` probes chapters 1-99 per title (cached per title);
  `list_sections` 1 request; `get_section` 1 request. The probing is a P2
  performance note (88 / 99 sequential GETs on first call), mirroring the
  Colorado 99-probe `list_titles`.

## Security

Fixed official host; the only user-driven inputs are validated title /
chapter / citation values flowing into the URL path components
(`{TT:02d}`, `00.{chapter:03d}.{local:03d}.{decimal:03d}`). No path
traversal, no query injection, no arbitrary hosts, no subprocess/shell/
eval/exec.

## Known limitations

- Live hosts cannot be exercised from this environment (TCP-blocked); the
  adapter is verified through archived official fixtures only.
- `list_titles` / `list_chapters` probe bounded numeric ranges; lettered
  chapters (e.g. Title 53 Chapter 57A) are not enumerated and lettered
  citations are rejected.
- The exact terminal response of an invalid *chapter* probe and the
  single-section-repeal per-section page (observed for the subchapter-repeal
  case, `18 § 4321`) are unobservable from the archive; the adapter's
  identity-verification and 404-page detection make it correct regardless.
- The probing discovery (88 / 99 GETs, cached) is heavier than the
  single-request discovery of some other adapters (P2).

## Architecture decision

A single new adapter, `src/state_statutes_mcp/adapters/pennsylvania/
adapter.py`, using the shared UTF-8 `fetch_url` and `strip_tags` helpers.
No changes to `BaseStateAdapter`, models, registry, MCP schema, `_fetch`,
`_htmltext`, or `_pdftext`. Pennsylvania-specific parsing (the citation ->
URL encoding, the `Section {n}[.{d}] - Title {t} - {NAME}` identity, the
`CHAPTER {c}` chapter header, the `Sec.` section rows, the repeal-note
detection) lives entirely in the adapter. Registration is explicit in
`server.py` (the registry pattern used by every other state).