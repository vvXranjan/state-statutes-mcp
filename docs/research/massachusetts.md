# Massachusetts General Laws — Source Research

**Status: VERIFIED** (live captures of the official host through the
r.jina.ai fetch proxy on Aug 20, 2026; `malegislature.gov` does not accept
direct sockets from this environment).

## Source

- Official: Massachusetts General Laws, published by the General Court of
  the Commonwealth of Massachusetts.
- Host: `https://malegislature.gov`.
- Live host status: **VERIFIED live** via the `r.jina.ai` proxy with
  `X-Return-Format: html`. Every URL tried returned real content on the
  first request — no JS shell, no bot-block, no CAPTCHA. The proxy returns
  the upstream HTML verbatim (re-fetches are byte-identical); it reports
  the upstream HTTP status, so soft-404s (HTTP 200 with a `404 - Page Not
  Found` body) were observed directly.

## Structure

**Family A — one static HTML document per section.** Server-rendered HTML,
no JS-dependent statute rendering.

### Hierarchy

The General Laws have a real **Part → Title → Chapter → Section**
hierarchy (4 levels), mapped onto the framework's three-level
`TitleRef → ChapterRef → SectionRef` model **entirely inside the adapter**
(no framework change):

- `TitleRef.identifier` is the site-independent `"Part {part} Title
  {title}"` form (e.g. `"Part I Title I"`), unique across parts and
  parseable. This absorbs Massachusetts's extra (Title) level the same way
  Montana absorbs its Part level and Minnesota/Nebraska/Wisconsin absorb a
  missing level.
- `ChapterRef.identifier` is the chapter number (e.g. `"4"`, `"6A"`,
  `"186"`).
- `SectionRef.identifier` is the section number exactly as the chapter page
  lists it (e.g. `"7"`, `"7A"`, `"6 1/2"`, `"160 to 168A"`, `"44K, 44L"`).
- The General Laws index page (`/Laws/GeneralLaws`) lists the five Parts;
  each Part page statically lists its titles as accordion panels. The Part
  pages use a single **GLOBAL `titleId` counter across all five Parts**
  (VERIFIED on all 34 titles): Part I holds titleIds 1–22, Part II 23–25,
  Part III 26–31, Part IV 32–33, Part V 34.

### URLs

| Resource | URL |
|----------|-----|
| General Laws index | `https://malegislature.gov/Laws/GeneralLaws` |
| Part page | `https://malegislature.gov/Laws/GeneralLaws/Part{roman}` |
| Chapter AJAX listing | `https://malegislature.gov/Laws/GeneralLaws/GetChaptersForTitle?partId={n}&titleId={m}&code={roman}` |
| Chapter (section listing) | `https://malegislature.gov/Laws/GeneralLaws/Part{part}/Title{title}/Chapter{n}` |
| Section | `https://malegislature.gov/Laws/GeneralLaws/Part{part}/Title{title}/Chapter{n}/Section{slug}` |

Section URL encoding (all VERIFIED against real captures):

- `"7"` → `Section7`; `"7A"` → `Section7A`; `"6 1/2"` →
  `Section6%201~2`; `"160 to 168A"` → `Section160%20to%20168A`;
  `"44K, 44L"` → `Section44K,%2044L`.
- The `/` is encoded as `~` **before** URL-quoting (so `"6 1/2"` becomes
  `Section6%201~2`, not `Section6%201/2`).

### General Laws index page

- `https://malegislature.gov/Laws/GeneralLaws` lists the five Parts, one
  row per part:
  ```html
  <li><a href="/Laws/GeneralLaws/PartI">
      <span class="part">Part I</span>
      <span class="partTitle">ADMINISTRATION OF THE GOVERNMENT</span>
      <span class="chapters">Ch...apters. 1-182</span>
  </a></li>
  ```

### Part page (title discovery)

- Each Part page (e.g. `PartI`) lists its titles as accordion panels:
  ```html
  <div id="Ititle" class="panel panel-default">
      <h4 class="glTitle panel-title">
          <a ... onclick="accordionAjaxLoad('1', '1', 'I')">Title I</a>
      </h4>
      <h4 class="panel-title">
          <a ... onclick="accordionAjaxLoad('1', '1', 'I')">JURISDICTION AND EMBLEMS OF THE COMMONWEALTH, ...</a>
      </h4>
  </div>
  ```
- The descriptive-name anchor is uniquely the one inside
  `<h4 class="panel-title">` (not the `glTitle panel-title` short label);
  the `onclick` carries `(partId, global titleId, roman title code)`.
- The adapter derives each title's `"Part {part} Title {roman}"` identifier
  from the part page, cross-checking that `int_to_roman(partId) == part`.

### Chapter AJAX listing (`GetChaptersForTitle`)

- Chapters are lazy-loaded through an internal AJAX endpoint keyed by the
  numeric Part id, the GLOBAL titleId, and the title's Roman numeral
  (VERIFIED against real responses for Part I Titles I and II):
  `https://malegislature.gov/Laws/GeneralLaws/GetChaptersForTitle?partId=1&titleId=1&code=I`.
- Each response is one `<li>` per chapter:
  ```html
  <span class="chapter">Chapter 6A</span>
  <span class="chapterTitle">EXECUTIVE OFFICES</span>
  ```
- Repealed chapters are **not** marked specially; every row is a normal
  chapter link.

### Chapter page (section listing)

- Each chapter page (e.g. `.../PartI/TitleI/Chapter4`) lists its sections
  statically, one row per section:
  ```html
  <span class="section">Section 7</span>
  <span class="sectionTitle">Definitions of statutory terms;  statutory construction</span>
  ```
- The TOC treats ALL entries uniformly, including repealed individual
  sections (Chapter 186, `Section 1` → `Repealed, 2008, 521, Sec. 5`),
  repealed ranges (`Section 160 to 168A` → `Repealed, 2011, 3, Sec. 131`),
  fractions (`Section 6 1/2`), and multi-part entries (`Section 44K, 44L`).
  Every one of these entries was VERIFIED to resolve to a working section
  page — this deliberately supersedes the B12 brief's claim that range
  entries have no normal section page.

### Section page

VERIFIED structure (Section 7 of Chapter 4, and several others):

```html
<h2 id="skipTo" class="h3 genLawHeading hidden-print">Section 7:
    <small>Definitions of statutory terms;  statutory construction</small>
</h2>
<p></p>  <!-- empty spacer, excluded -->
<p>&#160;&#160;Section 7. In construing statutes the following words
shall have the meanings herein given, unless a contrary intention clearly
appears:</p>
<p>...more body paragraphs...</p>
```

- The operative heading `<h2 class="genLawHeading">Section {id}:
  <small>{caption}</small></h2>` provides both the cross-check identifier
  and the caption.
- The caption becomes `heading`; the cleaned body `<p>` blocks (excluding
  the empty spacer) become `text`.
- **There is NO history/amendment text anywhere on the section pages**
  (VERIFIED on several pages), so `amendment_notes` is always `None`.

### Repealed / amended-into-a-special-act sections

A repealed or amended-into-a-special-act section renders its status only as
prose in the caption, with an **empty body**:

- `Section 7A` (ch. 4): caption `Amended by 1931, 394, Sec. 182 into a
  special act`, empty body.
- `Section 1` (ch. 186): caption `Repealed, 2008, 521, Sec. 5`, empty body.
- `Section 160 to 168A` (ch. 149): caption `Repealed, 2011, 3, Sec. 131`,
  empty body.

Per the framework rule (a prose-only repeal signal with an empty body, the
same decision as NebraskaAdapter), such sections are returned with
`status=UNKNOWN`, the caption as `heading`, `text=""`, and
`amendment_notes=None` — an empty body is a legitimate stub, not a
normalization error.

### Lettered / fractional / range sections

All handled by the uniform TOC pattern and the `~`-for-`/` URL encoding:

- Lettered: `7A`, `160 to 168A`, `44K, 44L` (kept verbatim as the
  identifier).
- Fractional: `6 1/2` (the space and `1/2` are preserved; the URL encodes
  the `/` as `~`).
- Range: `160 to 168A`, `44K, 44L`.

## Citation

- `G.L. c. {chapter}, § {section}` (e.g. `G.L. c. 4, § 7`,
  `G.L. c. 4, § 7A`, `G.L. c. 149, § 6 1/2`). Formally
  `Mass. Gen. Laws ch. {chapter}, § {section}`.
- `raw_citation` is that form; `SectionRef.identifier` is the section
  number. The short-form `G.L. c. {n}, § {s}` convention is
  **INFERENCE** from standard Massachusetts legal citation usage (not
  independently confirmed against an official citation-style guide); the
  numbers are VERIFIED from the site's own headings.

## Encoding

UTF-8 throughout (`charset=utf-8` reported in fetch metadata — VERIFIED).
The shared UTF-8 `fetch_url` helper is used directly.

## Error boundary

- **Soft-404 (VERIFIED)**: a nonexistent chapter (`Chapter9999`), section
  (`Section9999`) or title returns HTTP 200 whose body carries
  `404 - Page Not Found` in both `<title>` and `<h1>`. The adapter detects
  this content marker and maps it to `RefNotFoundError`.
- **Hard 404 (VERIFIED)** maps to `RefNotFoundError` through the shared
  `fetch_url` helper (HTTP 404 → `RefNotFoundError`; all other network
  failures → `AdapterUnavailableError`).
- **Out-of-range title**: a title beyond a Part's verified title count
  (e.g. `Part I Title XXIII`) is rejected up front with `RefNotFoundError`
  by the `_title_id` helper; a Part outside I–V is rejected with
  `UnsupportedRefError` at the chapter-listing path.
- Section identifier mismatch between the page's own heading and
  `ref.identifier` → `RefMismatchError`.
- Missing `genLawHeading` (genuinely malformed page) → `NormalizationError`.
- Empty body with a caption → returned with empty text (documented
  deviation, per the repealed-section rule above).

## Adapter behavior

- `list_titles` fetches the General Laws index (5 Parts) then one page per
  Part (6 fetches in all), returning 34 titles.
- `list_chapters(title_ref)` calls the AJAX `GetChaptersForTitle` endpoint
  (the Part pages lazy-load their chapter lists) and returns one `TocNode`
  per chapter.
- `list_sections(chapter_ref)` fetches the chapter's section-listing page
  and returns one `TocNode` per section, including repealed/range/fraction/
  multi-part entries.
- `retrieve_section(ref)` fetches the section page, cross-checks the page's
  own heading identifier against `ref`, parses heading / body, and calls
  `normalize`.
- `build_url(TitleRef)` returns the Part page that contains the title (the
  closest real document); `ChapterRef` → the chapter's section-listing
  page; `SectionRef` → the section page.
- `status` is always `UNKNOWN` (no structural signal; prose inference is
  forbidden by the contract).

## Fixture provenance

All `tests/fixtures/ma_*` files are **real** verbatim slices of the
official malegislature.gov pages, captured Aug 20, 2026 through the
`r.jina.ai` proxy with `X-Return-Format: html`. They are NOT synthetic.

| Fixture | Page |
|---------|------|
| `ma_gl.html` | `/Laws/GeneralLaws` (5 Parts) |
| `ma_part_i.html` … `ma_part_v.html` | Part I–V pages (34 titles) |
| `ma_ajax_title_i.html`, `ma_ajax_title_ii.html` | `GetChaptersForTitle` for Part I Titles I and II |
| `ma_ch4.html` | Chapter 4 (Part I Title I) section listing |
| `ma_ch6a.html` | Chapter 6A (Part I Title II) section listing |
| `ma_ch149.html` | Chapter 149 (Part I Title XXI) section listing |
| `ma_ch186.html` | Chapter 186 (Part II Title I) section listing |
| `ma_sec7.html` | Section 7 of Chapter 4 (normal) |
| `ma_sec7a.html` | Section 7A of Chapter 4 (amended into special act) |
| `ma_sec6_12.html` | Section 6 1/2 of Chapter 149 (fractional) |
| `ma_sec160to168a.html` | Section 160 to 168A of Chapter 149 (repealed range) |
| `ma_sec186_1.html` | Section 1 of Chapter 186 (repealed) |
| `ma_404.html` | Soft-404 body (HTTP 200 with `404 - Page Not Found`) |

## Known limitations

1. **Proxy-based retrieval** — `malegislature.gov` does not accept direct
   sockets from this environment; all captures were made through the
   `r.jina.ai` proxy. The upstream status is reported by the proxy, so the
   soft-404 marker (a 200-with-404-body) was observed directly, but a
   hard-404 network round-trip was not captured from a raw client.
2. **34 titles verified** (Part I: 22, II: 3, III: 6, IV: 2, V: 1) — the
   global titleId arithmetic is verified against all of them.
3. **Sampled sections** — normal, lettered, fractional, repealed, repealed-
   range, and amended-into-special-act pages were captured; whether every
   section page renders identically is otherwise UNVERIFIED.
4. **No history text on the site** — `amendment_notes` is always `None`;
   Massachusetts may publish editorial history elsewhere, but the section
   pages themselves carry none.
5. **4-level hierarchy folded into 3-level refs** — Part and Title are
   absorbed inside the adapter (Part via the Part-page fetch, Title via the
   `"Part {part} Title {title}"` identifier), with no framework change.

## Architecture impact

**None.** Massachusetts fits the existing `BaseStateAdapter` contract with
a single adapter-local design decision (the Part/Title absorption), the
same category of decision Montana's Part arithmetic and Minnesota/
Nebraska/Wisconsin's synthetic-title mappings already required. No change
to `BaseStateAdapter`, the ref models, the registry, `server_tools.py`, or
the exception hierarchy.