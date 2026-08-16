# North Carolina Statute Source Research

Research performed: Aug 16, 2026. The official host (`ncleg.gov`) could
NOT be independently fetched from this environment (the live host rejects
automated clients with an HTTP 403 bot-block), but Wayback Machine
captures of the official host were successfully obtained and the source
mechanics below were verified against those real captures:

- Chapter discovery page (per chapter): snapshot `20260411200450id_` of
  `https://ncleg.gov/Laws/GeneralStatuteSections/Chapter15`,
  `Chapter15A`, and `Chapter1`.
- Section documents: snapshots `20260120153610id_`
  (`GS_15-1.html`, UTF-8), `20260131002844id_` (`GS_15-9.html`, UTF-8),
  `20260116030802id_` (`GS_15-2_through_15-3.html`, UTF-8),
  `20220529095603id_` (`GS_15-10.1.html`, Windows-1252),
  `20220104180126id_` (`GS_15A-101.html`, Windows-1252), and
  `20190226111421id_` (`GS_15A-1_through_15A-100.html`, Windows-1252).

The test fixtures in `tests/fixtures/nc_*` are **real trimmed captures**
from those Wayback snapshots, NOT synthetic. The chapter-discovery
fixtures keep the real page header plus a contiguous subset of the
real section rows (verbatim); the section-document fixtures are the full
real captures, preserving their original encoding (UTF-8 or
Windows-1252) byte-for-byte.

## Status

**VERIFIED** (against the Wayback captures above of `ncleg.gov`):

- Official source: `https://www.ncleg.gov` — the official North Carolina
  General Assembly publication of the General Statutes of North Carolina
  (G.S.).
- Hierarchy: Chapter → Section. Chapters are the top-level grouping
  (e.g. `15`, `15A`); there is no title level in the modern G.S.
- Chapter discovery: each chapter's section listing is
  `/Laws/GeneralStatuteSections/Chapter{ch}` (e.g. `Chapter15`,
  `Chapter15A`). The page is titled "General Statute Sections - North
  Carolina General Assembly" with an H1 like "Chapter 15 - Criminal
  Procedure." and a line "The General Statutes include changes through
  SL {session}". Each section is a `div.row` block holding an HTML link
  to that section's document, a PDF link, the section's citation
  ("G.S. 15-1"), and the section's catchline ("§ 15-1.  Statute of
  limitations for misdemeanors.").
- Section retrieval: each section has ONE static HTML document at
  `/EnactedLegislation/Statutes/HTML/BySection/Chapter_{ch}/GS_{file}.html`,
  where `{file}` is the citation with spaces replaced by underscores:
  `15-1` → `GS_15-1.html`, `15-10.1` → `GS_15-10.1.html`, and a range
  `15-2 through 15-3` → `GS_15-2_through_15-3.html`. This is the Family A
  model — one static HTML document per section — NOT the CT/OR
  chapter-document model.
- The section document is a Word-generated XHTML page: a `<title>` that
  varies across documents (e.g. "G.S. 15-1" vs "§ 15A-101"), a series of
  chapter/article headings (e.g. `<h3>Chapter 15.</h3>`, `<p>Article
  1.</p>`), then the section's catchline paragraph — the first paragraph
  whose text starts with the section symbol (`§` / `§§`) — followed by
  the body paragraphs. The catchline is `<p ...><span ...>&sect; 15-1.
  &nbsp;Statute of limitations for misdemeanors.</span></p>`. The CSS
  class hashes on those tags are per-document and NOT stable, so parsing
  must not depend on them.
- Section identifiers include decimals (e.g. `15-10.1`, `15A-101.1`) and
  repealed/reserved RANGES (e.g. `15-2 through 15-3`,
  `15A-1 through 15A-100`). A range has ONE document named
  `GS_{a}_through_{b}.html`; there is NO single `GS_15-2.html` (verified:
  that URL has no Wayback capture and would 404). The citation and the
  catchline for a range echo the range (e.g. "G.S. 15-2 through 15-3",
  "§§ 15-2 through 15-3.  Repealed by Session Laws 1973, c. 1286, s. 26.").
- Citation form: `G.S. {ch}-{sec}` (e.g. `G.S. 15-1`, `G.S. 15-10.1`,
  `G.S. 15-2 through 15-3`). VERIFIED from the chapter page's citation
  links and the section documents.
- History: an inline parenthetical at the END of the section's last body
  paragraph, e.g. `(1826, c. 11; R.C., c. 35, s. 8; ... 2019-245, s.
  2(a).)`. VERIFIED on `GS_15-1.html`, `GS_15-10.1.html`, and
  `GS_15A-101.html`. The parenthetical may itself contain nested
  parentheses (e.g. `s. 17.8.(a)`, `s. 2(a).`), so it is extracted by
  balancing parentheses from the end of the body text.
- Repealed and reserved sections are catchline-only documents: the entire
  content is the heading paragraph, e.g. `§ 15-9. Repealed by Session
  Laws 1973, c. 1286, s. 26.` (repealed single), `§§ 15-2 through 15-3.
  Repealed by Session Laws 1973, c. 1286, s. 26.` (repealed range), and
  `§§ 15A-1 through 15A-100. Reserved for future codification purposes.`
  (reserved range). There is NO body and NO trailing history
  parenthetical. These sections are returned with `text == ""` and the
  repeal/reservation note as the `heading` (a structural element of the
  catchline, not inferred from prose); `status` remains `UNKNOWN`. This is
  a deliberate, documented deviation from the blanket "empty text + no
  amendment -> NormalizationError" rule, justified by the verified
  structure: the heading is real content, so a catchline-only section is
  genuinely retrievable. `NormalizationError` is raised only when a
  fetched document yields NO heading AND NO body text.
- Encoding: section documents are served in two encodings — newer
  documents UTF-8 with `&sect;` entities, older Word-generated documents
  Windows-1252 with literal bytes. The adapter detects the declared
  charset from the document's `<meta ... charset=...>` and decodes
  accordingly (defaulting to UTF-8), so the shared UTF-8-only
  `fetch_url` helper is not used for North Carolina by design (same
  pattern as `OregonAdapter`).

**BLOCKED BY DESIGN (UNVERIFIED)** — title/chapter discovery:

- The modern G.S. has no title hierarchy: chapters are the top level.
  `list_titles` raises `AdapterUnavailableError` directly. `list_chapters`
  also raises `AdapterUnavailableError`: the framework contract anchors a
  chapter under a `TitleRef`, and North Carolina has no titles to anchor
  under. (A chapter index page, `/Laws/GeneralStatutesTOC`, exists and
  lists every chapter — VERIFIED — but it cannot satisfy the
  title-anchored `list_chapters` contract, so it is not used.)

**UNVERIFIED**:

- The live HTTP status/404 behavior of the official host (only Wayback
  captures were fetchable; the live host returns 403 to this
  environment). Convention-based mapping is used: HTTP 404 maps to
  `RefNotFoundError`, other network failures to `AdapterUnavailableError`
  (same convention as every other adapter).
- Any markup drift since the 2026 captures.

## Source

- Site: `https://www.ncleg.gov` — the official North Carolina General
  Assembly publication of the General Statutes. VERIFIED via the Wayback
  captures.
- The site publishes the G.S. as server-rendered HTML, one static
  document per section. VERIFIED.

## Accessibility

- The official host was not independently reachable from this environment
  in this session (HTTP 403 bot-block); Wayback captures were used for
  verification and for building the fixtures. UNVERIFIED — the lack of
  live reachability is an environmental limitation, not evidence about
  the site.
- No authentication or API key is required to view the G.S. VERIFIED
  from the captured public navigation model.

## Hierarchy

Two structural levels supported by this adapter:

- **Chapter** — the top-level grouping. Chapter identifiers are numbers
  with optional trailing letters (e.g. `15`, `15A`). VERIFIED.
- **Section** — the individually retrievable unit, one static document
  per section. Section identifiers are the full `{ch}-{sec}` citation
  numbers, including decimals (e.g. `15-10.1`, `15A-101.1`) and repealed/
  reserved ranges (e.g. `15-2 through 15-3`). VERIFIED.

There is no Title level in the modern G.S. — see BLOCKED BY DESIGN above.

## URL Scheme

- Chapter discovery page:
  `https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter{ch}` (e.g.
  `Chapter15`, `Chapter15A`). VERIFIED.
- Section document:
  `https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_{ch}/GS_{file}.html`,
  where `{file}` is the citation with spaces replaced by underscores
  (e.g. `GS_15-1.html`, `GS_15-10.1.html`, `GS_15-2_through_15-3.html`).
  VERIFIED.
- Title: no page exists; `build_url` raises `UnsupportedRefError` for a
  `TitleRef`. BLOCKED BY DESIGN.

## Verified Page Structures

### Chapter discovery page (`/Laws/GeneralStatuteSections/Chapter{ch}`)

Each section is a `div.row` block. VERIFIED structure (UTF-8):

```html
<div class="row" style="padding-top:5px; padding-bottom:2px; ">
    <div class="col-3 col-sm-2 col-lg-1 d-flex text-nowrap justify-content-center pt-2 pt-md-0">
        <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_15/GS_15-1.html" style="...">
            <i class="far fa-file-alt ..." title="Display G.S. 15-1 HTML" ...></i>
        </a>
        <a href="/EnactedLegislation/Statutes/PDF/BySection/Chapter_15/GS_15-1.pdf" style="...">
            <i class="far fa-file-pdf ..." title="Display G.S. 15-1 PDF" ...></i>
        </a>
    </div>
    <div class="col-9 col-sm-10 col-lg-11">
        <div class="row" style="background-color:transparent;">
            <div class="col-12 col-md-3 col-lg-2 d-flex mobile-font-size-large">
                <a href="/EnactedLegislation/Statutes/PDF/BySection/Chapter_15/GS_15-1.pdf">G.S. 15-1</a>
            </div>
            <div class="col-12 col-md-9 col-lg-10">
                <a href="/EnactedLegislation/Statutes/PDF/BySection/Chapter_15/GS_15-1.pdf">
                    &#xA7; 15-1.  Statute of limitations for misdemeanors.</a>
            </div>
        </div>
    </div>
</div>
```

- The section's HTML retrieval link is the first anchor in the row.
- The citation is the text of the "G.S. {id}" link; the catchline is the
  text of the following link ("§ {id}.  {caption}." or "§§ {range}.
  {caption}."). A range row is identical except the citation/catchline
  echo the range (e.g. "G.S. 15-2 through 15-3").
- The page interleaves article group headings (a `div.row` whose only
  link is `.../PDF/ByArticle/Chapter_{ch}/Article_{n}.pdf`) between
  clusters of sections; those rows carry no "G.S." citation link and are
  naturally excluded by the parser.

### Section document (`GS_{file}.html`)

VERIFIED structure (both UTF-8 and Windows-1252 variants):

```html
<h3 class="cs2E44D3A6"><span class="cs72F7C9C5">Chapter 15.</span></h3>
<h3 class="cs2E44D3A6"><span class="cs72F7C9C5">Criminal Procedure.</span></h3>
<p class="cs2E44D3A6"><span class="cs9D249CCB">Article 1.</span></p>
<p class="cs2E44D3A6"><span class="cs9D249CCB">General Provisions.</span></p>
<p class="cs8E357F70"><span class="cs72F7C9C5">&sect; 15-1. &nbsp;Statute of
    limitations for misdemeanors.</span></p>
<p class="cs4817DA29" ...><span class="cs9D249CCB">(a)&nbsp;&nbsp;The crimes of
    deceit ...</span></p>
...
<p class="cs10EB6B29"><span class="cs9D249CCB">(5)&nbsp;&nbsp;G.S.&nbsp;14-318.6.
    (1826, c. 11; R.C., c. 35, s. 8; ... 2019-245, s. 2(a).)</span><a name="_GoBack"></a></p>
```

- The chapter/article headings precede the catchline and are excluded from
  the body.
- The catchline is the FIRST paragraph whose cleaned text starts with the
  section symbol (`§`); its text is `§ {id}. {caption}` (or `§§ {range}.
  {caption}`).
- The body is the cleaned text of every paragraph after the catchline,
  joined with blank lines.
- The history is the trailing balanced parenthetical of the body text
  (may contain nested parentheses), lifted out as `amendment_notes`.
- A repealed/reserved section has NO body paragraphs — the catchline is
  the whole document.

## Citation

- Citation form: `G.S. {ch}-{sec}` (e.g. `G.S. 15-1`, `G.S. 15-10.1`,
  `G.S. 15-2 through 15-3`). VERIFIED.
- `SectionRef.identifier` is the full `{ch}-{sec}` citation (e.g.
  `"15-1"`, `"15-10.1"`, `"15-2 through 15-3"`), matching the citation
  text on the chapter page and in the section document's catchline.
  VERIFIED.

## History

- History is an inline parenthetical at the end of the section's last
  body paragraph (e.g. `(1826, c. 11; ... 2019-245, s. 2(a).)`). VERIFIED
  on `GS_15-1.html`, `GS_15-10.1.html`, and `GS_15A-101.html`. The adapter
  lifts the trailing balanced parenthetical out as `amendment_notes`
  (whitespace collapsed) and removes it from the body.
- Sections may have no trailing parenthetical, making `amendment_notes`
  optional. VERIFIED.
- Repealed/reserved sections carry the repeal/reservation note as their
  `heading`, not as `amendment_notes` (there is no body to carry a
  history parenthetical). VERIFIED.

## Error Boundary

- The live HTTP 404 behavior of the official host is UNVERIFIED (the
  live host returns 403 to this environment). Convention-based mapping
  used by this adapter and documented here: HTTP 404 maps to
  `RefNotFoundError`, other network failures to `AdapterUnavailableError`
  (same convention as every other adapter).
- A fetched section document whose catchline does not begin with the
  requested `ref.identifier` (followed by a period) raises
  `RefMismatchError` — the document parsed but is not the section that
  was asked for.
- A fetched section document with no catchline paragraph, or one that
  yields neither a heading nor body text, raises `NormalizationError`.
- Repealed/reserved sections (catchline-only documents) are returned with
  `text == ""`, the repeal/reservation note as `heading`, and
  `amendment_notes is None` — a deliberate, documented deviation from the
  blanket "empty text + no amendment -> NormalizationError" rule (see
  Status above).
- `list_titles` and `list_chapters` raise `AdapterUnavailableError`
  directly (BLOCKED BY DESIGN; see above).

## Known Limitations

- Title/chapter discovery is unsupported (BLOCKED BY DESIGN): the modern
  G.S. has no title hierarchy, so only `list_sections` (given a chapter)
  and section retrieval are available for North Carolina.
- The live 404 semantics are UNVERIFIED; the not-found mapping follows
  project convention and is documented as such.
- A range section (e.g. `15-2 through 15-3`) is retrievable only by its
  full range citation, exactly as `list_sections` returns it; requesting
  just `15-2` builds `GS_15-2.html`, which does not exist (the range
  lives in `GS_15-2_through_15-3.html`) and therefore 404s.
- The section-document parser assumes paragraphs are `<p>` (or `<h3>`/
  `<h4>`) elements; a future section document embedding a `<p>`-style
  structure inside a paragraph could be mis-split. The verified
  documents do not exhibit this.
- Section documents are decoded per their declared charset (UTF-8 or
  Windows-1252); a document declaring neither defaults to UTF-8.