# Idaho Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://legislature.idaho.gov`) is NOT reachable from this environment
(all requests returned 000 — see Accessibility below), so official markup
was captured from a Wayback Machine snapshot of the official host and
inspected. Every URL below was executed against the official source through
the Wayback Machine; structure is documented verbatim from those responses,
which are the implementation boundary for this adapter.

## Status

**VERIFIED (via Wayback snapshot 20260712203433 of the official
`legislature.idaho.gov` host)** for the core discovery and retrieval paths:
title listing (the statutes index page), chapter listing (the title page),
section listing (the chapter page), section retrieval with heading, body,
and history line, and the HTTP-404 missing-section signal. Section 18-4003
(with subsections) was also inspected to confirm the body structure.

**UNVERIFIED** for a small set of secondary questions: whether every title
page keeps the same chapter-row markup and every chapter page the same
section-list markup (sampled Title 18, Chapter 40), and whether any repealed
section pages use a different layout. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified structure
rather than directly observed (noted inline).

## Source

- Site: `https://legislature.idaho.gov` — the official Idaho State
  Legislature publication of the Idaho Statutes.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the captured HTML contains the
  full content statically; note the Wayback-captured pages are served gzip-
  compressed and must be decompressed).
- The site names itself "Idaho Statutes" and organizes the code into
  Titles, Chapters, and Sections. VERIFIED.

## Accessibility

- The live host `legislature.idaho.gov` is NOT reachable from this
  environment: direct `curl` requests returned 000 with no HTTP response.
  VERIFIED (repeated attempts, browser UA, Aug 15, 2026).
- The same URLs return HTTP 200/404 through the Wayback Machine snapshot
  `20260712203433` of the official host. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.
- Responses are gzip-encoded at the Wayback layer; the shared `fetch_url`
  helper requests without an `Accept-Encoding` header and receives decoded
  content from the real host, so no adapter-side decompression is needed.
  (The gzip only appeared because `curl` sent `Accept-Encoding: gzip`.)

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 74 titles (1 through 74), each identified by its
  number, e.g. `18` ("Crimes and Punishments"). VERIFIED (74 title links on
  the statutes index page).
- **Chapter** — grouping within a title, e.g. Chapter 40 ("Homicide").
  Chapter identifiers are numeric (1, 2, ... 91 within Title 18). No lettered
  chapter ids observed in Title 18. VERIFIED (82 chapter links on Title 18).
- **Section** — the individually retrievable unit, e.g. `18-4001`. Section
  ids are `{title}-{chapter}{local}` (e.g. `18-4001`). Lettered section ids
  exist (e.g. `18-4004A`). VERIFIED.

## URL Scheme

- Title list (statutes index): `https://legislature.idaho.gov/statutesrules/idstat/`
  (200 via Wayback). Lists all 74 titles as flat links.
- Title page: `https://legislature.idaho.gov/statutesrules/idstat/Title{N}`
  (e.g. `/idstat/Title18`, 200; note the trailing-slash form `/Title18/`
  also works). Lists every chapter of the title.
- Chapter page: `https://legislature.idaho.gov/statutesrules/idstat/Title{N}/T{N}CH{CH}`
  (e.g. `/idstat/Title18/T18CH40`, 200). Lists every section of the chapter.
- Section page: `https://legislature.idaho.gov/statutesrules/idstat/Title{N}/T{N}CH{CH}/SECT{sec}`
  (e.g. `/idstat/Title18/T18CH40/SECT18-4001`, 200). One file per section.
- The site's canonical links use `Title18`/`T18CH40`/`SECT18-4001` (capital)
  while the Wayback snapshot resolves to a lowercased URL
  (`title18/t18ch40/sect18-4001/`); both forms fetch successfully through
  Wayback, and the capital form matches the hrefs in the index/title/chapter
  pages.

## Verified Page Structures

### Statutes index page (`/idstat/`) — title listing

A `<table>` with one `<tr>` per title:

```html
<tr>
<td valign="top" nowrap="true"><a href="/statutesrules/idstat/Title1">TITLE 1</a></td>
<td valign="top">&#160;&#160;</td>
<td valign="top"> COURTS AND COURT OFFICIALS  </td>
</tr>
```

VERIFIED (74 titles). The title identifier is the number in the href (`1`);
the name is the third `<td>` text (`COURTS AND COURT OFFICIALS`).

### Title page (`/idstat/Title{N}`) — chapter listing

A `<table>` with one `<tr>` per chapter:

```html
<tr>
<td valign="top" nowrap="true"><a href="/statutesrules/idstat/Title18/T18CH1">CHAPTER 1</a></td>
<td valign="top">&#160;&#160;</td>
<td valign="top"> PRELIMINARY PROVISIONS  </td>
<td valign="top">&#160;&#160;</td>
<td valign="top"><a href=".../T18CH1.pdf" target="_blank"> Download Entire Chapter (PDF)</a></td>
</tr>
```

VERIFIED for Title 18: 82 chapter rows (1 through 91, gaps where chapters
were repealed). The chapter identifier is the number in the href
(`T18CH1` -> `1`); the name is the third `<td>` text (e.g. `PRELIMINARY
PROVISIONS`). The PDF link `<td>` is excluded.

### Chapter page (`/idstat/Title{N}/T{N}CH{CH}`) — section listing

The page opens with `<h1 class="lso-toc">TITLE 18 CRIMES AND
PUNISHMENTS</h1>` and `<h2 class="lso-toc">CHAPTER 40 HOMICIDE</h2>`, then a
`<table>` with one `<tr>` per section:

```html
<tr>
<td valign="top" nowrap="true"><a href="/statutesrules/idstat/Title18/T18CH40/SECT18-4001">18-4001</a></td>
<td valign="top">&#160;&#160;</td>
<td valign="top"> MURDER DEFINED.  </td>
</tr>
```

VERIFIED for Chapter 40: 16 section rows (18-4001 through 18-4014+,
including the lettered `18-4004A`). The section identifier is the href
suffix (`18-4001`); the name is the third `<td>` text (e.g. `MURDER
DEFINED.`).

### Section page (`/idstat/Title{N}/T{N}CH{CH}/SECT{sec}`)

VERIFIED for `18-4001` (plain) and `18-4003` (subsectioned):

- `<title>Section 18-4001 &#8211; Idaho State Legislature</title>`.
- Breadcrumb: `Home / Idaho Laws & Rules / Idaho Statutes / Title 18 /
  Chapter 40 / Section 18-4001`. VERIFIED — usable as cross-check anchors.
- The content region opens with centered title/chapter headers
  (`TITLE 18` / `CRIMES AND PUNISHMENTS` / `CHAPTER 40` / `HOMICIDE`), then
  the section body:
  ```html
  <div style="line-height: 12pt; text-align: justify; text-indent: 5.9%; padding-top: 12pt">
  <span class="f11s" style="font-family: Courier New;">18-4001.&nbsp;&nbsp;<span style="text-transform: uppercase">Murder defined.&nbsp;</span>Murder is the unlawful killing ...</span>
  </div>
  ```
  The heading is the `<span style="text-transform: uppercase">` text
  (`Murder defined.`); the body is the remaining text of the first paragraph
  after the heading. VERIFIED.
- Subsections: each subsequent paragraph is its own `<div>` with
  `text-indent: 5.9%`, text like `(b)&nbsp;&nbsp;Any murder of any peace
  officer...`. For 18-4003 the paragraphs `(a)` through `(g)` follow the
  heading. VERIFIED.
- History: a `History:` label div followed by the session-law line:
  ```html
  <div style="..."><span style="font-size: 11pt; font-family: Courier New;">History:</span></div>
  <div style="...; text-indent: 5.9%"><span class="f11s" style="font-family: Courier New;">[18-4001, added 1972, ch. 336, sec. 1, p. 928; am. 1977, ch. 154, sec. 1, p. 390; ...]</span></div>
  ```
  VERIFIED — preserved verbatim as `amendment_notes`.
- The `How current is this law?` link and `Idaho Statutes are updated to the
  website July 1 following the legislative session.` banner are chrome and
  excluded.

## Citation

- Citation form: `Idaho Code § {title}-{chapter}{local}` (e.g. `Idaho Code §
  18-4001`, `Idaho Code § 18-4004A`), adapter-constructed; the `Idaho Code`
  abbreviation is INFERENCE from standard Idaho citation usage (the site
  itself says "Idaho Statutes" in its header), and the section number is
  VERIFIED from the site's own links and section heading.
- `SectionRef.identifier` is the full `{title}-{chapter}{local}` form exactly
  as the chapter-page links name it (e.g. `"18-4001"`, `"18-4004A"`).

## Error Boundary

- A missing section returns HTTP 404. VERIFIED (via Wayback,
  `/SECT18-9999/` -> 404). Mapped to `RefNotFoundError` in the adapter.
- A missing title/chapter is expected to 404 as well (INFERENCE from the
  section 404 and the consistent resource-per-level scheme); the adapter's
  shared `_fetch_html` maps any HTTP 404 to `RefNotFoundError`.

## Known Limitations

- The live host is unreachable from this environment, so the adapter is
  developed and tested against real Wayback-captured fixtures; live
  verification was not possible at implementation time.
- Whether every title page keeps the same chapter-row markup and every
  chapter page the same section-list markup has only been sampled (Title 18,
  Chapter 40).
- No repealed/reserved section was found in Chapter 40; repealed-section
  markup (if it differs from the current form) is UNVERIFIED.
- The heading for 18-4001 is wrapped in a `text-transform: uppercase` span;
  a section whose heading is NOT so wrapped has not been sampled, so the
  heading regex should fall back to the text following the `{sec}.` prefix
  if the span is absent.
