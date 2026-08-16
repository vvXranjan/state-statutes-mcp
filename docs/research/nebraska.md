# Nebraska Revised Statutes — Source Research

**Status: VERIFIED** (Wayback Machine captures of the official host; the
live host is not reachable from this environment).

## Source

- Official: Nebraska Legislature Revised Statutes.
- Host: `https://nebraskalegislature.gov`.
- Live host status: **UNREACHABLE from this environment** (network egress
  blocked; `curl` returns `000`). All structural claims below were verified
  against Wayback Machine captures.

### Verified Wayback captures

| Page | Snapshot |
|------|----------|
| Section `statutes.php?statute=77-1801` | `20251215062931` |
| Section `statutes.php?statute=77-202.12` (decimal) | `20251213200139` |
| Section `statutes.php?statute=77-202.13` (repealed) | `20251210152021` |
| Chapter index `browse-chapters.php?chapter=77` | `20251215071544` |
| Chapter browse `browse-statutes.php` | `20260107210216` |

## Structure

**Family A — one static HTML document per section.** No JS-driven statute
rendering; plain server-rendered HTML.

### Hierarchy

The Revised Statutes have **NO title level**. The official site groups the
entire code into **chapters 1–90 only**, listed flat on
`browse-statutes.php` ("Browse Statutes by Chapter"). Hierarchy is
**Chapter → Section**.

Mapping onto the framework's three-level `TitleRef → ChapterRef →
SectionRef` model (no framework change):

- A single **synthetic** `TitleRef` (identifier `"REVISED STATUTES"`,
  name `"Nebraska Revised Statutes"`) stands in for the absent title level.
  This mirrors the MinnesotaAdapter synthetic-title precedent (MN maps each
  official Part onto a `TitleRef`).
- `ChapterRef.identifier` is the chapter number (`"77"`, `"1"`, … `"90"`).
- `SectionRef.identifier` is the full `{ch}-{sec}` citation, e.g.
  `"77-1801"`, `"77-202.12"` (decimal subsection identifiers are
  preserved).

### URLs

| Resource | URL |
|----------|-----|
| Section | `https://nebraskalegislature.gov/laws/statutes.php?statute={ch}-{sec}` |
| Chapter index (section listing) | `https://nebraskalegislature.gov/laws/browse-chapters.php?chapter={n}` |
| Chapter browse (chapter listing) | `https://nebraskalegislature.gov/laws/browse-statutes.php` |
| Title | none (no title page exists) |

### Chapter browse page (`browse-statutes.php`)

- `<h1>Nebraska Legislature - Browse Statutes by Chapter</h1>`.
- Each chapter is a table row:
  ```html
  <tr>
      <td class="row">
          <span class="col-md-2 col-sm-3 my-auto"><a href="/laws/browse-chapters.php?chapter=36">Ch<span class="d-none d-md-inline">apter</span> 36</a></span>
          <span class="col-md-9 col-sm-8 my-auto"> FRAUD AND VOIDABLE TRANSACTIONS</span>
          ...
      </td>
  </tr>
  ```
- Chapter identifier = `browse-chapters.php?chapter={n}` value; name = the
  second span's text (e.g. `"FRAUD AND VOIDABLE TRANSACTIONS"`).

### Chapter index page (`browse-chapters.php?chapter={n}`)

- `<h1>Nebraska Revised Statutes Chapters</h1>`; card header
  `Revised Statutes Chapter {n} - {NAME}` (e.g. `77 - REVENUE AND
  TAXATION`).
- Each section is a table row:
  ```html
  <tr>
      <td class="row">
          <span class="col-md-2 col-sm-3 my-auto"><a href="/laws/statutes.php?statute=77-202.12"><span class="sr-only">View Statute </span>77-202.12</a></span>
          <span class="col-lg-9 col-md-8 col-sm-7 my-auto">Public property; taxation status; county assessor; duties; appeal.</span>
          ...
      </td>
  </tr>
  ```
- Section identifier = `statutes.php?statute={sec}` value (the full
  `{ch}-{sec}` citation); name = the second span's text. Repealed sections
  carry the repeal note as the name (e.g. `Repealed. Laws 2008, LB 965,
  § 27.`).

### Section page (`statutes.php?statute={ch}-{sec}`)

Verified structure (77-1801, 77-202.12, 77-202.13):

```html
<h1>Nebraska Revised Statute 77-1801</h1>
...breadcrumb / pagination chrome...
<div class="card mb-4" id="stat_panel">
  <div class="card-header leg-header">Chapter 77</div>
  <div class="card-body">
    <div class="statute">
      <h2>77-1801.</h2>
      <h3>Real property taxes; collection by sale; when.</h3>
      <p class="text-justify">Except for delinquent taxes ...</p>
      ...
      <div>
        <h2>Source</h2>
        <ul class="fa-ul">
          <li><i class="fa fa-li fa-book"></i>Laws 1903, c. 73, § 193, p. 459; </li>
          ...
          <li><a href="...LB968.pdf"><i class="fa fa-li fa-book"></i>Laws 2000, LB 968, § 70. </a></li>
        </ul>
      </div>
    </div>
    <div class="statute_source">
      <h2>Annotations</h2>
      <ul class="fa-ul">...case annotations...</ul>
    </div>
  </div>
</div>
```

- **Section number**: `<h2>{ch}-{sec}.</h2>` (trailing period). Used as the
  cross-check against `SectionRef.identifier`.
- **Heading**: the `<h3>` caption following the number.
- **Body**: the `<p class="text-justify">` paragraphs between the caption
  and the `Source` block (multiple paragraphs separated as blocks).
- **History**: the `Source` block's `<ul class="fa-ul"><li>` items
  (session-law citations; the final item ends with `.`, the rest with `;`).
  Lifted verbatim as `amendment_notes` (items joined with a space).
- **Annotations**: a trailing `<div class="statute_source">` block of case
  annotations — editorial, **excluded** from `text`.

### Repealed sections

A repealed section (77-202.13) renders the number `<h2>77-202.13.</h2>`
with the heading `<h3>Repealed. Laws 2008, LB 965, § 27.</h3>`, **no body
paragraphs**, and **no `Source` block**.

Per the documented deviation for repealed sections (the same decision as
NorthCarolinaAdapter), the adapter returns such a section with the repeal
note as its heading and **empty text**; `amendment_notes` is `None`.
`NormalizationError` is reserved for genuinely malformed documents with no
heading at all.

## Citation

- `Neb. Rev. Stat. § {ch}-{sec}` (e.g. `Neb. Rev. Stat. § 77-1801`).
- `raw_citation` is that form; `SectionRef.identifier` is `{ch}-{sec}`.
- The abbreviation is standard Nebraska citation usage (INFERENCE); the
  number is VERIFIED from the site's own headings and URLs.

## Encoding

UTF-8 (`<meta charset="utf-8">`). The shared UTF-8 `fetch_url` helper is
used directly.

## Error boundary

- **Live 404 semantics UNVERIFIED** (host unreachable). Project
  convention: HTTP 404 → `RefNotFoundError` (the source was reached but
  the addressed document does not resolve); all other network failures →
  `AdapterUnavailableError`.
- Section number `{ch}-{sec}` mismatch with `ref.identifier` →
  `RefMismatchError`.
- Missing section number / heading element (genuinely malformed page) →
  `NormalizationError`.
- Empty body with no amendment and no heading → `NormalizationError`.
- Empty body with a repeal/other heading → returned with empty text
  (documented deviation).

## Adapter behavior

- `list_titles` returns the single synthetic `"REVISED STATUTES"` title
  (a fixed adapter-internal mapping, no fetch).
- `list_chapters(title_ref)` requires the synthetic title identifier (any
  other → `RefNotFoundError`) and enumerates chapters 1–90 from
  `browse-statutes.php`.
- `list_sections(chapter_ref)` enumerates every section of the chapter
  from `browse-chapters.php?chapter={n}`.
- `retrieve_section(ref)` fetches the section page, cross-checks the
  `<h2>` number, and parses heading / body / history.
- `build_url(TitleRef)` raises `UnsupportedRefError` (no title page);
  `ChapterRef` → chapter index; `SectionRef` → section page.
- `status` is always `UNKNOWN` (no structural signal; prose inference is
  forbidden by the contract).

## Known limitations

1. **Live host unreachable** — everything verified via Wayback captures;
   404 semantics UNVERIFIED.
2. **Three section pages sampled** (normal, decimal, repealed); whether
   every section page renders identically is UNVERIFIED.
3. **Annotations excluded** — the case-law `Annotations` block is not
   statute text and is deliberately dropped from `text`.
4. **Chapter 77 is very large** (~2,800 sections, ~2.1 MB page); the
   fixture is a trimmed slice of the real capture.
5. **No title level** — handled with a single synthetic title
   (MinnesotaAdapter precedent), adapter-internal, no framework change.