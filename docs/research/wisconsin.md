# Wisconsin Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://docs.legis.wisconsin.gov`) is NOT reachable from this environment
(all requests returned 000 — see Accessibility below), so official markup
was captured from a Wayback Machine snapshot of the official host and
inspected. Every URL below was executed against the official source through
the Wayback Machine; structure is documented verbatim from those responses,
which are the implementation boundary for this adapter.

## Status

**VERIFIED (via Wayback snapshot 20260722161219 of the official
`docs.legis.wisconsin.gov` host)** for the core discovery and retrieval
paths: chapter listing (the statutes index page), section listing (the
chapter page), section retrieval with heading and body, and the 404 signal
for missing documents. Section 13.90 was also inspected from a second
snapshot (20250321084416) to confirm the section-page structure and the
history-block placement.

**UNVERIFIED** for a small set of secondary questions: whether the requested
section's own history block is always present on the section page (the
13.92 sample showed none — the history falls on the next scroll chunk, which
is not archived), and whether every chapter page keeps the same section-TOC
markup (sampled Chapter 13). Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified structure
rather than directly observed (noted inline).

## Source

- Site: `https://docs.legis.wisconsin.gov` — the official Wisconsin
  Legislature publication of the Wisconsin Statutes.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically).
- The site names itself "Wisconsin Legislature" and organizes the code into
  Chapters and Sections (there is NO title level). VERIFIED.

## Accessibility

- The live host `docs.legis.wisconsin.gov` is NOT reachable from this
  environment: direct `curl` requests returned 000 with no HTTP response.
  VERIFIED (repeated attempts, browser UA, Aug 15, 2026).
- The same URLs return HTTP 200/404 through the Wayback Machine snapshot
  `20260722161219` of the official host. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Two structural levels, matching the framework with a synthetic title:

- **Chapter** — the top level. 470 chapters, each identified by its number
  (e.g. `13`). Chapter numbers range from 1 to 995 with gaps (repealed
  chapters are absent from the list). Each chapter has a title (e.g. Chapter
  13 = "Legislative Branch"). VERIFIED (470 chapter links on the statutes
  index page).
- **Section** — the individually retrievable unit, e.g. `13.92`. Section ids
  are `{chapter}.{local}` (e.g. `13.01`, `13.035`, `13.92`); three-decimal
  ids like `13.035` exist. No lettered section ids observed in Chapter 13.
  VERIFIED.
- The site has NO formal title/part level: the statutes index page is a flat
  list of chapters. To fit the framework's three-level ref model, this
  adapter maps the entire code onto a single synthetic `TitleRef`
  (identifier `"Wisconsin Statutes"`). This mapping is adapter-internal and
  documented; it is not a framework change.

## URL Scheme

- Chapter list (statutes index): `https://docs.legis.wisconsin.gov/statutes/statutes`
  (200 via Wayback). Lists all 470 chapters as flat links.
- Chapter page: `https://docs.legis.wisconsin.gov/statutes/statutes/{N}` (e.g.
  `/statutes/statutes/13`, 200). Lists every section of the chapter in a
  section TOC. Also reachable as `/document/statutes/{N}` (the index-page
  hrefs use the `/document/statutes/{N}` form).
- Section page: `https://docs.legis.wisconsin.gov/document/statutes/{sec}`
  (e.g. `/document/statutes/13.92`). The live site 302-redirects this to the
  canonical node path `/statutes/statutes/{ch}/{article}/{sec}` (e.g.
  `/statutes/statutes/13/iv/92`). **IMPORTANT: the fetched page renders a
  RANGE of sections** — the requested section plus preceding siblings in the
  same subchapter (the 13.92 page renders sections 13.90, 13.905, 13.91, and
  13.92). The adapter must isolate the requested section's block (see below).

## Verified Page Structures

### Statutes index page (`/statutes/statutes`) — chapter listing

A `<ul class="docLinks">` list, one `<li>` per chapter:

```html
<li><p>
<span class="hasPdfLink" data-pdf-link="..."><a href="/document/statutes/1">Chapter 1</a> <span class="pdfLink">...</span></span> - Sovereignty And Jurisdiction Of The State
</p></li>
```

VERIFIED (470 chapters). The chapter identifier is the number in the href
(`1`); the name is the text after the `- ` separator (e.g. `Sovereignty And
Jurisdiction Of The State`). One chapter (165) has a newline in the name
(`Department Of Justice`), handled by stripping tags and collapsing
whitespace.

### Chapter page (`/statutes/statutes/{N}`) — section listing

The page opens with `qsnum_chap` (`CHAPTER 13`) and `qstitle_chap`
(`LEGISLATIVE BRANCH`), then lists sections as `qstoc_entry` divs:

```html
<div class="qstoc_entry" ... data-path="/statutes/statutes/13/_6" data-cites='[]'>
  <span class="qstr"><a rel="statutes/13.01" href="/document/statutes/13.01" title="Statutes 13.01">13.01</a><span class="qstab"> ... </span>Number of legislators.</span>
</div>
```

VERIFIED for Chapter 13: 55 section entries (13.01 through 13.31+). The
section identifier is the `rel="statutes/{sec}"` (or the href suffix); the
name is the text after the `qstab` span (e.g. `Number of legislators.`).

### Section page (`/document/statutes/{sec}`)

VERIFIED for 13.92 and 13.90:

- `<title>Wisconsin Legislature: 13.92</title>`.
- Main content: `<div id="document" class="statutes">` holding `qsatxt_*`
  divs.
- **The page renders the requested section PLUS preceding siblings.** For
  13.92 the page contains top-level `qsatxt_1sect level3` blocks for 13.90,
  13.905, 13.91, and 13.92. Each top-level block carries its own
  `data-section` attribute; the adapter isolates the block whose
  `data-section` equals the requested identifier.
- Section block for 13.92:
  ```html
  <div class="qsatxt_1sect  level3" data-path="/statutes/statutes/13/iv/92" data-section="13.92" data-cites='["statutes/13.92","statutes/13.92(intro.)"]'>
    <a class="reference" href="/document/statutes/13.92">13.92</a>
    <span class="qsnum_sect">...13.92</span>
    <span class="qstitle_sect"><span class="qstr">Legislative reference bureau.</span></span>
    <span class="qstr">There is created a bureau ...</span>
  </div>
  ```
  The heading is the `qstitle_sect` text (`Legislative reference bureau.`);
  the body is the `qstr` content that follows the heading within the block,
  plus the nested subsections.
- Nested structure: subsections are `qsatxt_2subsect level4` divs (e.g.
  `(1)`), paragraphs `qsatxt_3para level5` (e.g. `(a)`), subdivisions
  `qsatxt_4subdiv level6` (e.g. `1.`), and sub-subdivision paragraphs
  `qsatxt_5subdivpara`. Each carries `data-path` and `data-section` for the
  enclosing section, so all nested blocks for the requested section are the
  descendants of its `qsatxt_1sect` block.
- Navigation: `<div class='navigation'><a href='...?up=1'>Up</a></div>` and a
  `Down` link; these are chrome and excluded.
- History: a `qsnote_history` div appears after the LAST subdivision of a
  section whose history has been rendered, e.g. for 13.90:
  ```html
  <div class="qsnote_history" ... data-path="/statutes/statutes/13/iv/90/9/_1" data-section="13.90" data-cites='[]'>
    <span class="reference">13.90 History</span><span class="qstr">History:</span><span class="qstr"> 1971 c. 215; ...</span>
  </div>
  ```
  The 13.90 and 13.91 samples had history blocks; the 13.92 sample did NOT
  (13.92 is the last section rendered on its page, so its history falls on
  the next scroll chunk, which is not archived). The adapter therefore treats
  `amendment_notes` as optional: it captures the `qsnote_history` block for
  the requested section if present, else `None`.
- Hidden metadata near the end of the page confirms the requested node:
  `<span id="nodePath">/statutes/statutes/13/iv/92</span>` and `<span
  id="nodeCite">statutes/13.92</span>`.
- Footer: a disclaimer block (`2023-24 Wisconsin Statutes updated through
  2025 Wis. Act 16 ...`) that is chrome and excluded.

## Citation

- Citation form: `Wis. Stat. § {chapter}.{section}` (e.g. `Wis. Stat. §
  13.92`), adapter-constructed; the `Wis. Stat.` abbreviation is INFERENCE
  from standard Wisconsin citation usage (the site itself just says
  "Wisconsin Statutes" in its header), and the section number is VERIFIED
  from the site's own `data-section`/`nodeCite` values.
- `SectionRef.identifier` is the full `{chapter}.{local}` form exactly as the
  chapter-page links and section blocks name it (e.g. `"13.92"`, `"13.035"`).

## Error Boundary

- A missing section/document returns HTTP 404 through the Wayback snapshot
  (`/document/statutes/13.999` -> 404), so the adapter's shared `_fetch_html`
  maps HTTP 404 to `RefNotFoundError`. The live host's exact 404 behavior is
  UNVERIFIED (live host unreachable); HTTP 404 is the same signal the
  framework already uses for other HTML sources.
- A missing chapter/title is expected to 404 as well (INFERENCE from the
  section 404 and the consistent resource-per-level scheme).

## Known Limitations

- The live host is unreachable from this environment, so the adapter is
  developed and tested against real Wayback-captured fixtures; live
  verification was not possible at implementation time.
- The section page renders a range of sections; the adapter isolates the
  requested section's block by `data-section`. This is verified for 13.92
  and 13.90 (two distinct Wayback snapshots), but the exact set of siblings
  rendered on a section page may vary.
- The requested section's own `qsnote_history` block may be absent from the
  section page when the section is the last one rendered in its chunk
  (observed for 13.92). `amendment_notes` is therefore optional (`None` when
  absent).
- Whether every chapter page keeps the same `qstoc_entry` section-TOC markup
  has only been sampled (Chapter 13).
- No repealed/reserved section was found in Chapter 13; repealed-section
  markup (if it differs from the current form) is UNVERIFIED.
- The synthetic single title (`"Wisconsin Statutes"`) is an adapter-internal
  mapping required by the framework's three-level ref model; the state itself
  has no title level.
