# Alaska — Research & Implementation Notes

Status: **IMPLEMENTED** — state #40.

## Official source

- **Endpoint**: `https://www.akleg.gov/basis/statutes.asp`
- **Publisher**: Alaska State Legislature / Legislative Affairs Agency
  ("Alaska Statutes").
- **Source type**: Official server-rendered HTML (title index, TOC pages,
  per-section print pages).
- **Authentication**: None.
- **API key**: None.

## Source accessibility (ARCHIVED)

The live host (`akleg.gov`) returns an **HTTP 403 bot-challenge wall** to
this environment for every path, including the section print endpoint. This
is environment/infrastructure blocking, NOT statute-level behavior. All
structure verification and all fixtures below are based on **real archived
official captures** of the official host, retrieved via the Wayback Machine
in **Aug 2026** — they are archived captures, NOT live captures (the
Colorado/Michigan precedent).

## Encoding (VERIFIED)

The official pages are **ISO-8859-1** (verified via the index's charset
declaration and a literal `§` byte (0xA7) in a repealed-note capture), so
the adapter performs its own `urllib` fetch and decodes `windows-1252` (the
Oregon precedent) rather than the shared UTF-8 `fetch_url`.

## Discovery (VERIFIED via archived captures)

| Level | Endpoint | Contents |
|-------|----------|----------|
| Titles | `statutes.asp` | all 47 titles server-rendered as `loadTOC(N)` rows (`Title {NN}. {NAME}`) |
| Chapters | `statutes.asp?media=js&type=TOC&title={T}` | `Chapter {T.C} {NAME}` rows (e.g. title 11 -> 30 chapters) |
| Sections | `statutes.asp?media=js&type=TOC&title={T.C}` | `Sec. {T.C.S}. {NAME}` rows (e.g. chapter 01.10 -> 13 sections) |

## Section retrieval (VERIFIED via archived captures)

`statutes.asp?media=print&secStart={T.C.S}&secEnd=` returns one complete
section in a `<div class="statute">` block:
`<b><a name="{citation}"></a>Sec. {citation}. {catchline.}</b>` followed by
the body. **Citation-derived and deterministic.**

## Hierarchy

`Title -> Chapter -> Section`, citation `{T}.{C}.{S}` (e.g. `AS 11.41.100`
= Title 11, Chapter 41, Section 100). Maps directly onto the framework:
- **TitleRef = title number** (1-47, as the index numbers them).
- **ChapterRef = zero-padded `T.C`** (e.g. `"11.41"`).
- **SectionRef.identifier = full zero-padded citation** (e.g.
  `"11.41.100"`).

The site zero-pads every component (`01.10.070`); user input is
canonicalized (`1.10.70` -> `01.10.070`).

## Special cases (VERIFIED via archived captures)

- **Repealed sections render their text** with an inline bracketed note
  (e.g. `[Repealed, § 3 ch 6 SLA 1978.]`) and are NOT absent. The adapter
  preserves the text and moves the bracketed note to `amendment_notes`.
  `status` stays `UNKNOWN` (prose-only signals are never treated as a
  structural status, per the framework rule).
- **Renumbered sections render a stub**: `Sec. {a}. - {b}. [Renumbered as
  AS …].` with a `Repealed or Renumbered` body marker. The adapter
  preserves the renumber note as the heading, leaves the body empty, and
  keeps the note in `amendment_notes`.
- **Invalid sections**: a nonexistent citation returns **HTTP 404**
  (verified via multiple archived 404 captures, e.g. `11.71`, `26.23`,
  `34.35`) -> `RefNotFoundError`.
- **Silent fallback**: none. The 404 confirms nonexistent citations never
  return a nearby section; the adapter additionally content-verifies the
  page's `<a name="{citation}">` anchor and the `Sec. {citation}.` heading
  against the request.
- **Lettered/decimal citations**: none observed in the archived corpus; the
  citation format is strictly numeric `T.CC.SSS`, and non-numeric forms are
  rejected.

## Error mapping

| Condition | Exception |
|-----------|-----------|
| Invalid citation / chapter / title format | `RefNotFoundError` |
| HTTP 404 on a section citation (nonexistent) | `RefNotFoundError` |
| Page with no statute block / no section head | `RefNotFoundError` |
| Declared citation anchor or heading != requested | `RefMismatchError` |
| Ref chapter != citation's chapter | `RefMismatchError` |
| Network failure / non-404 HTTP error | `AdapterUnavailableError` |
| Declared section but empty, non-stub body | `NormalizationError` |

HTTP 200 alone is never treated as success; the anchor + declared heading
are always verified.

## Fixture provenance

All `tests/fixtures/ak_*` files are **real archived official captures** of
akleg.gov retrieved via the Wayback Machine in **Aug 2026**. They are NOT
synthetic and NOT live captures. The set covers: the title index, a title
TOC (title 11), a chapter TOC (chapter 01.10), a normal section (01.10.070),
a renumbered stub (11.05.070), a repealed-with-note section (18.65.010,
with its literal `§` preserved — stored as windows-1252 bytes), and the
archived HTTP-404 page. The 18.65.010 fixture is a trimmed real capture of
that single section (the surrounding sections of the archived range page
are removed; the section's own HTML is verbatim). No statute text was
fabricated.

## Performance

- Title index: ~18 KB (one request, cached per adapter instance).
- Title TOC / chapter TOC: 2-4 KB each (small).
- Section pages: 1-4 KB each (very light).
- Discovery: `list_titles` 1 request (cached); `list_chapters` 1 request;
  `list_sections` 1 request; `get_section` 1 request.

## Security

Fixed official host; the only user-driven inputs are validated citation /
chapter / title values flowing into `secStart`, `title`, and `type` query
parameters. No path traversal, no query injection, no arbitrary hosts, no
subprocess/shell/eval/exec.

## Known limitations

- Live host cannot be exercised from this environment (bot-challenge 403);
  the adapter is verified through archived official fixtures only.
- Repealed sections render their text with an inline note (not the
  Iowa/California "absent" convention) and are handled deliberately.
- No lettered/decimal section citations were verified; such input is
  rejected.
- The 404 invalid-section behavior is verified via archived captures but
  not live (same environment limitation as Michigan/Colorado).

## Architecture decision

A single new adapter, `src/state_statutes_mcp/adapters/alaska/adapter.py`,
with an adapter-local windows-1252 fetch (the pages are ISO-8859-1). No
changes to `BaseStateAdapter`, models, registry, MCP schema, `_fetch`,
`_htmltext`, or `_pdftext`. Alaska-specific parsing (the citation
canonicalization and the section-page structure) lives entirely inside the
adapter.