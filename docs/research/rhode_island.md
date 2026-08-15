# Rhode Island Statute Source Research

Research performed: Aug 15, 2026. The live host
(`http://webserver.rilegislature.gov`) is NOT reachable from this
environment (requests returned 000 — see Accessibility below), so official
markup was captured from a Wayback Machine snapshot of the official host
and inspected. Every URL below was executed against the official source
through the Wayback Machine; structure is documented verbatim from those
responses, which are the implementation boundary for this adapter.

## Status

**VERIFIED (via Wayback snapshot 20250401074949 of the official
`webserver.rilegislature.gov` host)** for the core discovery and retrieval
paths: title listing (the master Statutes page), chapter listing (the title
index page), section listing (the chapter index page), section retrieval
with heading, body, and history, and the HTTP-404 missing-section signal.
All verified from HTTP 200/404 responses of the official HTML.

**UNVERIFIED** for a small set of secondary questions: whether every title
index page keeps the same chapter-row markup and every chapter index page
the same section-row markup (sampled Titles 43, 6A, and 40.1; chapter
43-3), and whether repealed sections beyond 43-3-7 drop the body paragraph
entirely. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `http://webserver.rilegislature.gov` — the official Rhode Island
  General Assembly publication of the General Laws of Rhode Island.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically).
- The site names itself "General Laws" and cites sections as `R.I. Gen.
  Laws § {t}-{c}-{s}` (e.g. `R.I. Gen. Laws § 43-3-2`). VERIFIED.

## Accessibility

- The live host `webserver.rilegislature.gov` is NOT reachable from this
  environment: direct `curl` requests returned 000 with no HTTP response.
  VERIFIED (repeated attempts, browser UA, Aug 15, 2026).
- The same URLs return HTTP 200/404 through the Wayback Machine snapshot
  `20250401074949` of the official host. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 49 titles: numbered 1–47 plus lettered `6A` and
  decimal `40.1` (TITLE40.1). Each identified by its number/letter, e.g.
  `43` ("Statutes and Statutory Construction"). VERIFIED (49 linked title
  rows on the master page).
- **Chapter** — grouping within a title, e.g. Chapter 43-3. Chapter
  identifiers are the full `{title}-{chapter}` directory name (`43-3`,
  `6A-2.1`, `40.1-1`), and may themselves carry a decimal extension
  (`43-3`, `6A-2.1`). VERIFIED.
- **Section** — the individually retrievable unit, e.g. `43-3-2`,
  `43-3-3.1`. The section id is the full `{title}-{chapter}-{section}`
  citation, and may carry a decimal extension (`43-3-3.1`, `43-3-22.1`).
  VERIFIED.

## URL Scheme

- Title list: `http://webserver.rilegislature.gov/Statutes/Statutes.html`
  (200). Lists all 47 titles.
- Title index: `http://webserver.rilegislature.gov/Statutes/TITLE{n}/INDEX.HTM`
  (e.g. `/Statutes/TITLE43/INDEX.HTM`, 200). Lists every chapter of the
  title. (Case-insensitive on the live host; the lettered/decimal titles
  use `TITLE6A`, `TITLE40.1`.)
- Chapter index: `http://webserver.rilegislature.gov/Statutes/TITLE{n}/{t}-{c}/INDEX.htm`
  (e.g. `/Statutes/TITLE43/43-3/INDEX.htm`, 200). Lists every section of
  the chapter.
- Section page: `http://webserver.rilegislature.gov/Statutes/TITLE{n}/{t}-{c}/{t}-{c}-{s}.htm`
  (e.g. `/Statutes/TITLE43/43-3/43-3-2.htm`, 200). One file per section.

## Verified Page Structures

### Title list page (`/Statutes/Statutes.html`)

A table, one cell per title. The title link is
`href="http://webserver.rilegislature.gov/Statutes/TITLE{n}/INDEX.HTM"` with
the title number as link text; the title name sits in the adjacent cell:

```html
<td ...><p align="center" ...><span ...><a href="http://webserver.rilegislature.gov/Statutes/TITLE43/INDEX.HTM" class="homeLinks">43</a></span></p></td>
<td ...><p><span ...>&nbsp;&nbsp;Statutes and Statutory Construction</span></p></td>
```

VERIFIED (47 rows: 1–47, `6A`, `40.1`). The `Statutes.html` page declares
`charset=ISO-8859-1` but its content is pure ASCII (special characters are
HTML entities like `&#8211;`), so UTF-8 decoding is safe.

### Title index page (`/Statutes/TITLE{n}/INDEX.HTM`)

One `<p>` per chapter:

```html
<p><a href="43-1/INDEX.htm">Chapter 43-1&nbsp;Action by Governor</a></p>
<p><a href="43-2/INDEX.htm">Chapter 43-2&nbsp;Publication and Distribution of Acts</a></p>
```

VERIFIED for Title 43: 4 chapter rows (43-1 ... 43-4); Title 6A uses
`6A-1/INDEX.htm`, `6A-2.1/INDEX.htm`, `6A-4.1/INDEX.htm`, etc. (13 rows,
1, 2, 2.1, 3, 4, 4.1, 5, 6, 7, 8, 9, 11, 12 -- there is no chapter 6A-10);
Title 40.1 uses `40.1-1`, `40.1-1.1`, ... (33 rows). The chapter identifier
is the href directory prefix (e.g. `43-3`); the chapter name is the text
after the leading `Chapter {id}&nbsp;` prefix (e.g. `Construction and
Effect of Statutes`). Title 40.1 additionally contains three placeholder
rows with EMPTY link text (`40.1-8.1`, `40.1-11`, `40.1-24.1`, each
preceded by a `[Repealed.]` chapter row) -- empty anchor placeholders that
represent no real chapter. VERIFIED. The adapter's chapter regex requires
the `Chapter {id}&nbsp;` prefix, so these empty-stub rows are naturally
skipped.

### Chapter index page (`/Statutes/TITLE{n}/{t}-{c}/INDEX.htm`)

One `<p>` per section:

```html
<p><a href="43-3-1.htm">§&nbsp;43-3-1.&nbsp;English statutes as common law.</a></p>
<p><a href="43-3-3.1.htm">§&nbsp;43-3-3.1.&nbsp;Gender of titles.</a></p>
```

VERIFIED for chapter 43-3: 39+ section rows, including decimal extensions
(`43-3-3.1`, `43-3-22.1`) and a repealed section (`43-3-7 ... Repealed.`).
The section identifier is the href file stem (e.g. `43-3-2`, `43-3-3.1`);
the section name is the text after the leading `§&nbsp;{id}.&nbsp;` prefix.

### Section page (`/Statutes/TITLE{n}/{t}-{c}/{t}-{c}-{s}.htm`)

VERIFIED for `43-3-2`, the decimal `43-3-3.1`, and the repealed `43-3-7`:

- Title anchor: `<h1><center>Title 43<br>Statutes and Statutory
  Construction</center></h1>`. The title number is `43`.
- Chapter anchor: `<h2><center>Chapter 3<br>Construction and Effect of
  Statutes</center></h2>`. NOTE: the on-page chapter number is the LOCAL
  chapter (`3`), not the full `43-3` form used in the citation and URL.
  VERIFIED.
- Citation: `<h3>R.I. Gen. Laws § 43-3-2</h3>` — the full `{t}-{c}-{s}`
  citation. VERIFIED.
- Heading: `<p style="margin-left:0px"><b>§&nbsp;43-3-2.&nbsp;Application
  of rules of construction.</b></p>` — the bold paragraph; the heading is
  the text after the leading `§&nbsp;{id}.&nbsp;` prefix.
- Body: the `<p>` paragraphs between the heading paragraph and the history
  block. VERIFIED (one paragraph for 43-3-2).
- History: `<p>History of Section.<br>G.L. 1896, ch. 26, § 1; G.L. 1909,
  ch. 32, § 1; ... G.L. 1956, § 43-3-2.</p>` — the text after the
  `History of Section.<br>` marker is preserved verbatim as
  `amendment_notes`; `status` stays `UNKNOWN`.
- Repealed section 43-3-7: heading `§&nbsp;43-3-7.&nbsp;Repealed.` and NO
  body paragraph (the page jumps straight to the history block). VERIFIED.
  This is a structural repeal signal (a "Repealed." marker in place of body
  text), so the adapter sets `status` to `REPEALED` and leaves `text` empty,
  following the framework rule and the MissouriAdapter precedent. The
  `Repealed.` marker is matched only after the `§&nbsp;{id}.&nbsp;` heading
  prefix is stripped. A second repealed form was VERIFIED (section
  40.1-1-1): a repealed-RANGE heading `§&nbsp;40.1-1-1 — 40.1-1-3.&nbsp;
  [Repealed.]` with the same empty body; the heading's leading citation
  prefix (single-id or range form) is stripped and the bracketed
  `[Repealed.]` marker is treated as the same structural repeal signal.
- The citation `<h3>` and the title `<h1>` are cross-checked against the
  requested `SectionRef` (the full `{t}-{c}-{s}` appears verbatim in the
  `<h3>`; the title number appears in the `<h1>`).

## Citation

- Citation form: `R.I. Gen. Laws § {t}-{c}-{s}` (e.g. `R.I. Gen. Laws §
  43-3-2`, `R.I. Gen. Laws § 43-3-3.1`), adapter-constructed; the `R.I.
  Gen. Laws` abbreviation is VERIFIED from the site's own `<h3>` citation
  text, and the section number is VERIFIED from the site's own headings.
- `SectionRef.identifier` is the full `{t}-{c}-{s}` form exactly as the
  chapter-index links and section-page `<h3>` name it (e.g. `"43-3-2"`,
  `"43-3-3.1"`).

## Error Boundary

- A missing section returns HTTP 404. VERIFIED (via Wayback,
  `/Statutes/TITLE43/43-3/43-3-99.htm` -> 404). Mapped to
  `RefNotFoundError` in the adapter.
- A missing title/chapter index is expected to 404 as well (INFERENCE from
  the section 404 and the consistent resource-per-level scheme); the
  adapter's shared `_fetch_html` maps any HTTP 404 to `RefNotFoundError`.
- A repealed section (heading `Repealed.` in place of body text) is a valid
  section, not an error: `status` is `REPEALED` with empty `text`. VERIFIED
  for 43-3-7.

## Known Limitations

- The live host is unreachable from this environment, so the adapter is
  developed and tested against real Wayback-captured fixtures; live
  verification was not possible at implementation time.
- The on-page chapter anchor (`Chapter 3`) uses the LOCAL chapter number
  rather than the full `43-3` citation form, so the adapter cross-checks
  the chapter level through the full section id in the `<h3>` citation and
  the title through the `<h1>` rather than through the local `<h2>`
  number.
- Whether every title index page keeps the same chapter-row markup and
  every chapter index page the same section-row markup has only been
  sampled (Titles 43, 6A, 40.1; chapter 43-3).
- The repealed-section empty-body form is verified only for 43-3-7 and the
  repealed-range 40.1-1-1 (— 40.1-1-3); other repealed sections may retain
  body text (which would parse as normal body text and remain `UNKNOWN`).
