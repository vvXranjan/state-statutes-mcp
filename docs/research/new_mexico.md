# New Mexico Statutes Annotated (NMSA) — Source Research

**Status: VERIFIED** (live captures of the official host `nmonesource.com`
on Aug 23, 2026, from this environment).

## 1. Official source

- New Mexico Statutes Annotated (NMSA) 1978, published by the New Mexico
  Compilation Commission.
- Host: `https://nmonesource.com` (the "NMOneSource" legal research portal,
  a Decisia/Lexum platform).
- Base path: `https://nmonesource.com/nmos/nmsa/en`.
- Live host status: **VERIFIED live** from this environment (plain
  `urllib` GETs, browser User-Agent). No auth, no API key, no session.

## 2. Access method

- **VERIFIED**: the outer navigation pages (`nav_date.do`, `nav_alpha.do`)
  are JavaScript shells, but the `?iframe=true` variant serves the real
  chapter listing as static HTML.
- **VERIFIED**: chapter documents are directly retrievable PDFs.
- The Legislature's own site (`nmlegis.gov`) returned HTTP 403 (bot-block)
  and was not used; nmonesource.com is the authoritative publisher.

## 3. Hierarchy

- The NMSA's real structure is **Chapter → Article → Section**.
- **VERIFIED: there is NO Title level** in the official navigation (both
  the "Date" and "Alpha" nav views list chapters directly).
- Mapped onto the framework's `TitleRef → ChapterRef → SectionRef` model
  with a single **synthetic `TitleRef`** (identifier `"NMSA"`), the
  Minnesota/Nebraska/Wisconsin synthetic-title precedent.
- `ChapterRef.identifier` = chapter number (`"1"`, `"22A"`).
- `SectionRef.identifier` = full `{chapter}-{article}-{section}` citation
  (`"1-2-1"`, `"1-1-1.1"`), with the Article level folded into the section
  identifier (Montana-Part / Kentucky-full-citation precedent).

## 4. Synthetic title rationale

- The NMSA has no native title grouping; the official navigation is
  chapter-first. A single synthetic title preserves the framework's
  three-level contract without a framework change. INFERENCE (from the
  absence of any title links), consistent with the established precedent.

## 5. Chapter discovery

- **VERIFIED**: `https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true&page={1..4}`
  lists all **84 chapters** (page 1: 25, page 2: 25, page 3: 25, page 4: 9)
  as `Chapter {N} - {NAME}` rows.
- Lettered chapters exist (`22A`). VERIFIED.

## 6. Opaque ID behavior

- **VERIFIED**: each chapter row links to an **opaque item ID**
  (`/nmos/nmsa/en/item/{id}/index.do`). The IDs are **NON-sequential**
  (1→4351, 2→4359, 3→4362, 37→4366, 77→4427).
- The adapter discovers the `chapter_number → item_id` mapping live from
  the four navigation pages on every call. **No IDs are hardcoded.**
- LIMITATION: a navigation-format change would break discovery (same risk
  as Kentucky's index / Iowa's root page).

## 7. PDF URL construction

- **VERIFIED**: `https://nmonesource.com/nmos/nmsa/en/{item_id}/1/document.do`.
  The `/1/` segment is required; `/2/` returns HTTP 404.

## 8. PDF extraction

- **VERIFIED**: chapter documents are text-based PDFs. pypdf extracts them
  cleanly in default mode — **no fragmentation fallback triggered** (0
  fragmented pages in Chapters 1, 30, 77).
- Sizes vary widely: Chapter 1 = 3.78 MB / 657 pages; Chapter 30 = 5.84 MB
  / 1138 pages; Chapter 77 = 1.4 MB / 233 pages. VERIFIED.
- The existing shared `fetch_bytes` + `extract_pdf_text` infrastructure is
  sufficient; no shared change required.

## 9. Section parsing

- **VERIFIED** section structure in the extracted chapter text:
  - Section start: `{citation}. {Catchline}.` at a **line start** (e.g.
    `1-2-1. Secretary of state; chief election officer; rules.`).
  - Body: operative statute text (subsections `A.`/`B.`/`(1)`/`(2)`).
  - `History: {history}` block.
  - `ANNOTATIONS` block (case law / Am. Jur. / C.J.S. references).
  - The **next section citation** at a line start is the section boundary.
- **VERIFIED**: section citations are ordered monotonically within a
  chapter PDF (737 in ch1, 525 in ch30), so the next-citation boundary is
  deterministic.
- The parser is anchored to a line start and requires the trailing `. `
  so inline citations in the body ("Section 1-1-13 NMSA 1978") are never
  mistaken for boundaries.

## 10. History

- **VERIFIED**: `History: {history}` is captured as `amendment_notes`,
  following the Kentucky/Iowa convention. The `History:` prefix is
  stripped; the history text is preserved verbatim.

## 11. Annotations

- **VERIFIED**: the `ANNOTATIONS` block (case law, Am. Jur. 2d, A.L.R.,
  C.J.S. references) is **excluded** from the statutory body. It is
  commentary, not statute text. Following the NebraskaAdapter precedent
  (which excludes its `Annotations` block), the annotations are dropped
  rather than stored — `amendment_notes` holds only the `History:` block.

## 12. Repealed handling

- **VERIFIED** (e.g. `1-2-8`): a repealed section renders as
  `1-2-8. Repealed.` with **no body**, then `History:` (containing
  `repealed by Laws 2019, ch. 212, § 284`) and `ANNOTATIONS`.
- Per the framework's prose-only-repeal rule (Nebraska/Massachusetts/
  Kentucky precedent): `heading` = the catchline, `text=""`,
  `status=UNKNOWN`, history preserved in `amendment_notes`.

## 13. Decimal identifiers

- **VERIFIED**: decimal sections exist (e.g. `1-1-1.1`, `1-1-2.1`) and are
  captured by the section-start regex (`\d{1,3}(?:\.\d+)?`).
- Lettered **chapter** identifiers verified (`22A`); lettered **section**
  identifiers **UNVERIFIED** (not claimed).

## 14. Error behavior

- **VERIFIED**: invalid chapter item ID → genuine HTTP 404 → `RefNotFoundError`.
- **VERIFIED**: nonexistent chapter number (not in nav) → `RefNotFoundError`.
- **VERIFIED**: section absent from a chapter PDF → `RefNotFoundError`.
- **VERIFIED**: requesting a section whose chapter prefix does not match
  the served chapter's PDF → `RefNotFoundError` (defensive chapter check;
  the PDF's own section citations must begin with the requested chapter).
- Citation mismatch at normalize → `RefMismatchError`.
- Non-PDF response → `RefNotFoundError`; malformed PDF → `AdapterUnavailableError`;
  network failure → `AdapterUnavailableError`.

## 15. Fixture provenance

All `tests/fixtures/nm_*` files are **real** verbatim captures of the
official host, fetched live on Aug 23, 2026. They are NOT synthetic.

| Fixture | Source | Content |
|---------|--------|---------|
| `nm_nav_page1..4.html` | `nav_date.do?iframe=true&page={1..4}` | the four official navigation pages (84 chapters) |
| `nm_ch1_sections.pdf` | `.../en/4351/1/document.do` (pages 0–45) | trimmed Chapter 1 slice: sections 1-1-1 (normal), 1-1-1.1 (decimal), 1-2-1 (multi-subsection), 1-2-8 (repealed) |
| `nm_ch2_sections.pdf` | `.../en/4359/1/document.do` (pages 0–25) | trimmed Chapter 2 slice: sections 2-1-x |

The trimmed PDFs are page-range subsets of the official chapter PDFs
re-saved with pypdf (the established trimmed-capture pattern used by
Nebraska/Montana/etc.).

## 16. Performance limitation

- **VERIFIED LIMITATION**: per-section retrieval re-fetches and re-extracts
  the entire chapter PDF (up to 5.84 MB / 1138 pages, ~16 s extraction).
  This is the heaviest per-request cost in the project but within the
  adapter's 60 s timeout. No caching is introduced in B15; future
  optimization (caching) is out of scope.

## 17. Architecture fit

- **No framework change.** New Mexico is the third PDF-family adapter,
  reusing the shared `fetch_bytes` → `extract_pdf_text` pipeline and the
  synthetic-title precedent. All New Mexico-specific behavior (nav parsing,
  opaque-ID resolution, chapter-PDF parsing) lives inside
  `NewMexicoAdapter`. No change to `_fetch.py`, `_pdftext.py`,
  `_htmltext.py`, `BaseStateAdapter`, models, or the registry.

## 18. Known limitations

1. Only Chapters 1, 2, 30, and 77 were sampled; per-chapter PDF uniformity
   otherwise UNVERIFIED.
2. Lettered section identifiers UNVERIFIED.
3. Chapter-level PDFs make each request heavy (see performance limitation).
4. The synthetic-title mapping is a documented deviation from the official
   structure (no Title level exists).
5. Opaque item IDs must be discovered live; a nav change would surface as a
   discovery failure.