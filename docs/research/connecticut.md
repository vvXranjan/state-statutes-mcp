# Connecticut Statute Source Research

Research performed: Aug 16, 2026. The official host
(`cga.ct.gov`) could NOT be independently fetched from this environment,
but a Wayback Machine capture of the official host was successfully
obtained (snapshot `20260811192527id_`, serving the "current" General
Statutes publication) and the source mechanics below were verified
against that real capture. The test fixtures in `tests/fixtures/ct_*`
are **real trimmed captures** from that Wayback snapshot (headers and
footer stripped, section blocks preserved verbatim), NOT synthetic.

## Status

**VERIFIED** (against the Wayback capture `20260811192527id_` of
`cga.ct.gov`):

- Official source: `https://www.cga.ct.gov/current/pub/` — the
  Connecticut General Statutes "current" publication.
- Hierarchy: Title → Chapter → Section.
- The title index is `titles.htm`; it lists the titles, each row
  carrying a `toc_ttl_desig` link (href stem = title id, e.g. `01`,
  `42a`, `53a`) and a `toc_ttl_name` span (title name).
- Each title's page is `title_{id}.htm` and lists that title's chapters.
- Chapter pages are `chap_{id}.htm` for nearly all titles. Title 42a
  (the Uniform Commercial Code) is article-based: its "chapter" pages
  are `art_{id}.htm` (e.g. `art_001.htm`) and its title page lists
  articles. 42a is the ONLY article-based title (verified on the title
  index).
- Chapter rows carry one or more `toc_ch_link` links; the last link's
  text is the chapter/article name.
- Sections are embedded in their chapter document (chapter-document
  based retrieval). Each section is opened by a catchline span
  `<span class="catchln" id="sec_{id}">Sec. {id}. {Caption}.</span>`.
- Section identifiers are the citation form `{chapter}-{section}`
  (e.g. `53a-24`) or, for the UCC articles, `{article}-{part}-{section}`
  (e.g. `42a-1-101`). Lettered suffixes are supported (e.g. `53a-117l`).
- Repealed ranges appear as interleaved range catchline blocks whose id
  is `secs_...` (e.g. `secs_53a-53_and_53a-54`,
  `secs_53a-61b_to_53a-61z`, `secs_42a-1-207_and_42a-1-208`). These are
  genuine block boundaries but are NOT individually retrievable sections.
- History: each section block carries optional
  `<p class="source-first">` (session-law history) and
  `<p class="history-first">` (narrative history) paragraphs, joined with
  a newline as `amendment_notes`.
- Body-excluded regions: `<p class="annotation...">`,
  `<p class="cross-ref...">`, `<p class="front-note...">` paragraphs, and
  a trailing `<table class="nav_tbl">` navigation table.
- No-caption sections exist (e.g. `53a-90`, transferred to Chapter 961,
  whose heading is just `Sec. 53a-90.` and whose body is the transfer
  note); the caption is then `None`.
- Citation: `Conn. Gen. Stat. § {chapter}-{section}`; the adapter's
  `raw_citation` is the page's own `Sec. {id}` form and
  `SectionRef.identifier` is `{id}`.
- The lettered-section heading renders the italic digit with spaces
  around it (e.g. `Sec. 53a-117 l . Damage...`); the adapter's caption
  prefix-strip allows whitespace between identifier characters.

**UNVERIFIED**:

- The live HTTP status/404 behavior of the official host (only the
  Wayback capture was fetchable from this environment).
- Any markup drift since the `20260811192527id_` capture.

## Source

- Site: `https://www.cga.ct.gov/current/pub/` — the official Connecticut
  General Statutes "current" publication. VERIFIED via the Wayback
  capture.
- The site publishes the statutes as server-rendered HTML, chapter-
  document based. VERIFIED.

## Accessibility

- The official host was not independently reachable from this environment
  in this session; a Wayback capture (`20260811192527id_`) was used for
  verification and for building the fixtures. UNVERIFIED — the lack of
  live reachability is an environmental limitation, not evidence about
  the site.
- No authentication or API key is required to view the statutes. VERIFIED
  from the captured public navigation model.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — the top level. The title index (`titles.htm`) lists the
  titles. VERIFIED.
- **Chapter** — grouping within a title. Chapter identifiers are numbers
  (e.g. `950`, `952`), with lettered titles supported. Title 42a is
  article-based (its "chapters" are UCC articles such as `001`). VERIFIED.
- **Section** — the individually retrievable unit, embedded in its
  chapter document. Section identifiers are the `{chapter}-{section}`
  citation numbers (e.g. `53a-24`) or the UCC `{article}-{part}-{section}`
  form (e.g. `42a-1-101`). VERIFIED.

## URL Scheme

- Title index: `https://www.cga.ct.gov/current/pub/titles.htm`. VERIFIED.
- Title page: `https://www.cga.ct.gov/current/pub/title_{id}.htm`
  (e.g. `title_53a.htm`, `title_42a.htm`). VERIFIED.
- Chapter page: `https://www.cga.ct.gov/current/pub/chap_{id}.htm`,
  EXCEPT under Title 42a (UCC) whose pages are
  `https://www.cga.ct.gov/current/pub/art_{id}.htm` (e.g.
  `art_001.htm`). The article-based mapping is VERIFIED: 42a is the only
  article-based title.
- Section: the section's own chapter (or article) document — sections are
  embedded in their chapter document, so that document is the closest
  real resource (the same model `NevadaAdapter` uses). VERIFIED.

## Verified Page Structures

### Title index (`titles.htm`)

A flat list of title rows. Each row carries a designation link and a
name link, e.g.:

```html
<tr style="vertical-align:top">
  <td class="left_38pct">
    <a href="title_53a.htm"><span class="toc_ttl_desig">Title 53a</span></a>
  </td>
  <td><a href="title_53a.htm"><span class="toc_ttl_name">Penal Code</span></a></td>
</tr>
```

VERIFIED. Rows without a usable designation/name pair (e.g. the reserved
Title 2a row, which has no links) are skipped.

### Title page (`title_{id}.htm`)

Lists the title's chapters, one row per chapter, e.g.:

```html
<tr style="vertical-align:top">
  <td class="left_40pct">
    <a class="toc_ch_link" href="chap_950.htm">Chapter 950</a>
  </td>
  <td><a class="toc_ch_link" href="chap_950.htm">Penal Code: General Provisions</a></td>
</tr>
```

VERIFIED (e.g. title 53a lists chapters 950–968; title 42a lists
articles 001–002a, 003, …). The identifier is the first link's href
stem; the name is the last link's text.

### Chapter / article document (`chap_{id}.htm` / `art_{id}.htm`)

Contains the chapter's sections, each opened by a catchline span and
carrying optional history, annotations, cross-references, front-notes,
and a navigation table. VERIFIED structure:

```html
<span class="catchln" id="sec_53a-24">Sec. 53a-24. Offense defined.
  Application of sentencing provisions to motor vehicle and drug
  selling violators.</span>
<p>(a) The term &#x201C;offense&#x201D; means any crime or violation ...</p>
<p class="source-first">(1969, P.A. 828, S. 24; ...)</p>
<p class="history-first">History: ...</p>
<p class="cross-ref-first">See Secs. 53a-35 and 53a-35a re sentences
  for felonies.</p>
<table class="nav_tbl">...</table>
```

The `secs_` range catchlines (e.g. `<span class="catchln" id="secs_53a-53_and_53a-54">Secs. 53a-53 and 53a-54. Homicide defined. ...</span>`)
are genuine block boundaries but excluded from section listings.

## Citation

- Citation form: `Conn. Gen. Stat. § {chapter}-{section}` (e.g.
  `Conn. Gen. Stat. § 53a-24`). The adapter's `raw_citation` is the
  page's own `Sec. {id}` form. VERIFIED.
- `SectionRef.identifier` is the full `{chapter}-{section}` number
  (e.g. `"53a-24"`), matching the catchline id without the `sec_` prefix.
  VERIFIED.

## History

- History is carried in two optional paragraph types: `source-first`
  (session-law history, e.g. `(1969, P.A. 828, S. 24; ...)`) and
  `history-first` (narrative history, e.g. `History: ...`). VERIFIED.
  The adapter preserves both verbatim as `amendment_notes`, joined with
  a newline, and removes them from the body text.
- Sections may have no history at all (e.g. a transferred section such
  as `53a-90`), making `amendment_notes` optional. VERIFIED.

## Error Boundary

- The live HTTP 404 behavior of the official host is UNVERIFIED (only
  the Wayback capture was reachable). Convention-based mapping used by
  this adapter and documented here: HTTP 404 maps to `RefNotFoundError`,
  other network failures to `AdapterUnavailableError` (same convention
  as every other adapter).
- A section whose catchline id is not present in a fetched chapter
  document raises `RefNotFoundError` — an adapter-level expected
  behavior based on project convention. The live not-found behavior of
  the Connecticut source is UNVERIFIED.

## Known Limitations

- The fixtures are real trimmed captures from the Wayback snapshot
  `20260811192527id_`; the trimmed chapter fixtures (`ct_chap952_trimmed.html`,
  `ct_art001_trimmed.html`) preserve only a subset of each chapter's
  section blocks, so `list_sections` on those fixtures returns only the
  included sections. The title-index fixture (`ct_titles.html`) is the
  full real capture.
- The live 404 semantics are UNVERIFIED; the not-found mapping follows
  project convention and is documented as such.