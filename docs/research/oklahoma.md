# Oklahoma Statutes — Source Research

**Status: VERIFIED** (live captures of the official host `oklegislature.gov`
on Aug 23, 2026, from this environment).

## 1. Official source

- Oklahoma Statutes, published by the Oklahoma Legislature.
- Host: `https://www.oklegislature.gov`.
- Title index: `https://www.oklegislature.gov/osStatuesTitle.html`.
- Title PDFs: `https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os{N}.pdf`.
- Live host status: **VERIFIED live** (plain `urllib` GETs, browser
  User-Agent). No auth, no API key, no session.

## 2. Live verification

- **VERIFIED**: the title index lists 90 `os{N}.pdf` links (89 unique
  titles; some numbers are gaps, e.g. 35, 48, 55 are absent). Lettered
  titles exist (`3A`, `74E`, `85A`).
- **VERIFIED**: per-title PDFs are directly retrievable `application/pdf`
  documents, text-based (pypdf extracts cleanly).
- **VERIFIED**: nonexistent title PDFs (`os999.pdf`) return a genuine HTTP
  404 (no silent fallback).

## 3. Title discovery

- **VERIFIED**: titles are discovered dynamically from the official index
  (the `os{N}.pdf` links). Title numbers can be numeric or
  numeric-plus-letter. The adapter does NOT hardcode the title list; it
  parses the index live.
- Names are attached from parsed index rows where available; titles whose
  names have unusual formatting (e.g. Title 1 "Abstracting (See 74,
  State Government)") fall back to a descriptive `Title {N}` label.

## 4. Flat / chaptered hierarchy

- **VERIFIED heterogeneous**: most titles are FLAT (`Title -> Section`),
  e.g. Title 21 uses `§21-701.7` (a dotted section number, not a chapter).
  A minority are CHAPTERED (`Title -> Chapter -> Section`), e.g. Title 2
  uses `§2-1-1`.
- **Approved mapping** (no framework change):
  - FLAT title: one synthetic `ChapterRef` whose identifier equals the
    title number (e.g. `get_section("OK","21","21","21-701.7")`).
  - CHAPTERED title: real `ChapterRef`s (e.g. `get_section("OK","2","1","2-1-1")`).
- The flat-vs-chaptered determination is adapter-local: a title is
  chaptered iff any citation has the form `T-C-S` with a dot-free middle
  part. Flat citations (`T-S`) may themselves be dotted (`21-701.7`) or
  carry a sub-number (`21-701.10-1`).

## 5. Synthetic chapter decision

- For FLAT titles, `list_chapters` returns exactly one synthetic chapter
  whose identifier equals the title number (name `Title {N} sections`),
  so the framework's required `ChapterRef` is always satisfied.
  `list_sections` on that chapter returns every section of the title.
- This is the Minnesota/Nebraska/Wisconsin synthetic-level precedent
  applied at the chapter level.

## 6. PDF structure

- **VERIFIED**: each per-title PDF begins with a table of contents whose
  section lines carry dotted leaders and trailing page numbers (e.g.
  `§21-701.7.  Murder in the first degree. ...... 299`). The body follows.
- **VERIFIED**: body section lines are `§{citation}.  {Catchline}.` with
  NO dotted leader. A section is a body occurrence iff neither the line
  nor its immediate continuation (before the next `§` line) contains a
  dotted leader.
- **VERIFIED**: footers (`Oklahoma Statutes - Title {N}. {NAME} Page {p}`)
  are interleaved in the body and are stripped.
- **VERIFIED**: each body section ends at the next body section citation.

## 7. Parsing

- `_SECTION_START` matches `§{citation}.  {Catchline}` where the citation
  is `[0-9A-Za-z]+(-[0-9A-Za-z.]+)*` (flat and chaptered, lettered and
  dotted).
- The catchline runs from the citation line until the first line that ends
  with a period (handling wrapped catchlines, e.g. `2-1-2. State
  Department of Agriculture - Establishment - Composition.`).
- Body = lines after the catchline until the history block; footers are
  dropped.
- History/notes (`Added by Laws ...`, `Amended by Laws ...`, `Laws {year}
  ...`, `NOTE:`) become `amendment_notes`.

## 8. Normal section

- **VERIFIED** (e.g. `21-701.7` Murder in the first degree): citation,
  catchline, body with subsections (`A.`, `B.`, `(1)`, etc.), history
  (`Added by Laws 1976 ... Amended by Laws ...`), and a `NOTE:` block.

## 9. Repealed

- **VERIFIED** (e.g. `21-12`, `2-2-17`, `2-2-17A`): a repealed section
  renders as `§{citation}.  Repealed by Laws {year} ...` with no
  substantive body. Per the framework prose-only-repeal rule (Nebraska/
  Massachusetts/Kentucky/New Mexico precedent): `heading` = the catchline,
  `text=""`, `status=UNKNOWN`, repeal info in the catchline.

## 10. Renumbered

- **VERIFIED** (e.g. `2-2-19`): `§2-2-19.  Renumbered as § 14-81 of this
  title by Laws 2000, c. 243, ...` with no substantive body. Same
  prose-only convention: heading = catchline, `text=""`, `status=UNKNOWN`.

## 11. Identifier variants

- **VERIFIED**: decimal sections (`2-2-17.1`), lettered sections
  (`2-2-17A`), lettered titles (`3A-201`), dotted flat sections
  (`21-701.7`), sub-numbered sections (`21-701.10-1`), repealed
  (`2-2-17`), renumbered (`2-2-19`).

## 12. Error boundaries

- **VERIFIED**: nonexistent title PDF → genuine HTTP 404 → `RefNotFoundError`.
- Missing section in body → `RefNotFoundError`.
- Non-PDF response → `RefNotFoundError`.
- Malformed PDF → `AdapterUnavailableError` (via shared `extract_pdf_text`).
- Network failure → `AdapterUnavailableError`.
- Citation mismatch at normalize → `RefMismatchError`.
- The PDF's own citation is cross-checked against the requested section
  (a wrong title's PDF would yield a citation that does not match).

## 13. Fixture provenance

All `tests/fixtures/ok_*` files are **real** verbatim captures of the
official host, fetched live on Aug 23, 2026. The PDF fixtures are
page-range subsets of the official per-title PDFs re-saved with pypdf (the
established trimmed-capture pattern). `ok_title_index.html` is the official
title index.

| Fixture | Source | Content |
|---------|--------|---------|
| `ok_title_index.html` | `osStatuesTitle.html` | official title index (89 titles) |
| `ok_title21_section_701.7.pdf` | `os21.pdf` pages 298-302 | flat normal section 21-701.7 |
| `ok_title21_repealed.pdf` | `os21.pdf` pages 33-36 | flat repealed section 21-12 |
| `ok_title2_ch1.pdf` | `os2.pdf` pages 38-41 | chaptered normal 2-1-1 |
| `ok_title2_ch2_sections.pdf` | `os2.pdf` pages 57-61 | decimal 2-2-17.1, lettered 2-2-17A, repealed 2-2-17, renumbered 2-2-19 |
| `ok_title3A_lettered.pdf` | `os3A.pdf` pages 0-8 | lettered-title sections 3A-200..3A-203 |

## 14. Architecture fit

- **No framework change.** `SectionRef.chapter` is always satisfied: the
  synthetic chapter for flat titles is the title number; chaptered titles
  use the real chapter. `SectionRef.identifier` is always the full Oklahoma
  citation.
- Reuses `fetch_bytes()` + `extract_pdf_text()` unchanged.
- No change to `BaseStateAdapter`, refs/models, `server_tools.py`, or the
  registry.

## 15. Performance limitation

- **VERIFIED LIMITATION**: per-title PDFs are large (e.g. Title 21 = 3.5 MB
  / 884 pages; Title 2 = 3.4 MB; Title 11 = 2.8 MB; Title 68 = 5.6 MB).
  Each `get_section` re-fetches and re-extracts the entire title PDF
  (download ~4-17 s, extraction ~7 s). All sampled titles fit within the
  60 s timeout. No caching in B16 (documented as future work).

## 16. Known limitations

1. Only Titles 1, 2, 3A, 21, 11, and 68 were sampled; per-title PDF
   uniformity otherwise UNVERIFIED.
2. The flat/chaptered determination is heuristic (dot-free middle part);
   it is verified for Titles 2 (chaptered) and 21/3A (flat) but not for
   every title.
3. Titles whose names have unusual index formatting (e.g. Title 1) fall
   back to a descriptive `Title {N}` label.
4. Per-title PDF retrieval is heavy (see performance limitation).