# Maryland Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://mgaleg.maryland.gov`) IS reachable from this environment, so
official markup was captured live and inspected. Every URL below was
executed directly against the live site with plain HTTP GETs; structure is
documented verbatim from those responses, which are the implementation
boundary for this adapter.

## Status

**VERIFIED live** for the core discovery and retrieval paths: article
listing (the statute browser page), section listing (the `GetSections`
JSON API), section retrieval with heading and body, and the per-section
citation number. All verified from live HTTP 200 responses of the official
`mgaleg.maryland.gov` site.

**UNVERIFIED** for a small set of secondary questions: whether every
article's `GetSections` response and every section page render identically
(sampled the `gtr` and `gag` article listings and sections `1-101`,
`2-103.1`, `5-4A-01`), and whether the `enactments` query parameter changes
the section text for enacted-law views. Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://mgaleg.maryland.gov` — the official Maryland General
  Assembly publication of the Annotated Code of Maryland.
- The statute browser is a plain ASP.NET MVC site with server-rendered
  HTML: no SPA framework, no client-side statute rendering, and a small
  JSON API used only for section discovery. VERIFIED (the live HTML
  contains the full content statically).
- The site names itself "Annotated Code of Maryland" and organizes the
  code into articles (e.g. "Transportation"). VERIFIED.

## Accessibility

- Fully reachable from this environment: every URL below returned HTTP
  200. VERIFIED.
- The section-discovery API requires the `/api/` URL prefix. The
  non-API form `/mgawebsite/Laws/GetSections?articleCode=gtr` returns an
  "Object moved" 404 redirect page; the canonical form
  `/mgawebsite/api/Laws/GetSections?articleCode=gtr&enactments=false`
  returns 200 with JSON. VERIFIED.
- The `enactments` query parameter is REQUIRED for the `GetSections` API:
  without it (e.g. `?articleCode=gag`) the API returns a JSON error body
  `{"message": "No HTTP resource was found ..."}`, and with
  `&enactments=false` it returns the section list (771 sections for
  `gag`). VERIFIED. The section-text page (`StatuteText`) does NOT require
  the parameter.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, mapped onto the framework by flattening the
article's subtitle level onto the chapter slot:

- **Article** (top level, maps to the framework's Title) — the Annotated
  Code articles, each identified by a three-letter code, e.g. `gtr`
  ("Transportation"). The statute browser page lists 36 Annotated Code
  articles, all with codes beginning with `g` (e.g. `gag` Agriculture,
  `gab` Alcoholic Beverages and Cannabis). The page also lists other
  options -- the Constitution (`c*` codes), county/local codes (`l*`
  codes), and charters (`acts`, `baltc`, `municc`) -- which are NOT
  Annotated Code articles and are excluded. VERIFIED (66 options total;
  36 `g`-prefixed).
- **Subtitle** (grouping within an article, maps to the framework's
  Chapter) — Maryland sections carry a leading subtitle segment in their
  citation (e.g. `1-101` is in subtitle 1; `18.5-101` is in subtitle
  18.5). Subtitles have no page of their own; they exist only as the
  leading segment of each section id. VERIFIED (28 subtitles in `gtr`,
  including dotted ones like `18.5` and `18.7`).
- **Section** — the individually retrievable unit, e.g. `1-101`,
  `2-103.1`, `5-4A-01`. Dotted sections (`2-103.1`) and lettered/double-
  dash sections (`5-4A-01`) occur throughout.

## URL Scheme

- Statute browser: `https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes`
  (200). Holds the `#Articles` select listing every article.
- Section listing (JSON API):
  `https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetSections?articleCode={code}&enactments=false`
  (200 for `gtr` and `gag`). Returns a JSON array of
  `{"DisplayText": "1-101", "Value": "100"}` records, one per section, in
  citation order.
- Section page:
  `https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article={code}&section={sec}`
  (e.g. `?article=gtr&section=1-101`, 200). The section's own HTML page.

## Verified Page Structures

### Statute browser page (`/mgawebsite/Laws/Statutes`)

A `<select id="Articles">` whose options are the articles, each
`<option value="{code}">{Name} - ({code})</option>`:

```html
<select class="laws-dropdown form-control" id="Articles" name="Articles">
  <option value=""></option>
  <option value="gag">Agriculture - (gag)</option>
  <option value="gab">Alcoholic Beverages and Cannabis - (gab)</option>
  ...
  <option value="gtr">Transportation - (gtr)</option>
  ...
  <option value="l22">Washington County - (l22)</option>
  <option value="municc">Municipal Charter - (municc)</option>
</select>
```

The same article options are repeated inside the `#StatutesAffected`
select further down the page, so the parse is scoped to the `#Articles`
select. VERIFIED (36 `g`-prefixed article options; the `c*`, `l*`,
`acts`, `baltc`, and `municc` options are Constitution/local/charter
codes, not Annotated Code articles).

### Section listing (`/mgawebsite/api/Laws/GetSections`)

A JSON array in citation order:

```json
[{"DisplayText": "1-101", "Value": "100"},
 {"DisplayText": "1-102", "Value": "200"},
 ...]
```

Verified for `gtr`: 1744 sections across 28 subtitles; the first record
is `{"DisplayText": "1-101", "Value": "100"}` and the last is
`{"DisplayText": "27-106", "Value": "..."}`. Dotted and lettered section
ids (e.g. `2-103.1`, `5-4A-01`) appear among them. The records carry no
section names -- the identifier is the only label, so `list_sections`
uses the citation as the display name.

### Section page (`/mgawebsite/Laws/StatuteText?article={code}&section={sec}`)

The full page holds the section document inside
`<div id="StatuteText">` as an embedded `<html>` fragment (VERIFIED for
`1-101`, `2-103.1`, and `5-4A-01`):

```html
<div id="StatuteText">
<html><div style="text-align: center;"><span style="font-weight: bold;">
Article - Transportation</span></div><br><br>
<div class="row">...<button class="btn sub-navbar-button Next">Next</button>...</div>
<br><br>&sect;1&ndash;101.<br><br>
&nbsp;&nbsp;&nbsp;&nbsp;(a)&nbsp;&nbsp;&nbsp;&nbsp;In this article the
following words have the meanings indicated.<br><br>
... body ...
<br><br><div class="row">...Next...</div><br></html>
</div>
```

- The article banner (`Article - Transportation`) names the parent
  article; the section heading is `&sect;{number}.` with the dash rendered
  as the entity `&ndash;` (e.g. `&sect;2&ndash;103.1.`), and the body
  follows. VERIFIED.
- There is NO catchline/heading on Maryland section pages: the heading
  text is the citation number only, so `heading` is `None`. VERIFIED.
- The body uses `&nbsp;` indentation for subdivisions and `<br><br>`
  paragraph breaks; it renders cleanly with
  `strip_tags(..., preserve_block_breaks=True)` after the banner, nav
  buttons, and heading are excluded. VERIFIED.
- No history/amendment line on the sampled section pages. VERIFIED.
- The citation number in the heading is the only self-identifier; it is
  cross-checked against the requested `SectionRef` in the adapter.

## Citation

- Citation form: `Md. Code, {ArticleName} § {section}` (e.g. `Md. Code,
  Transportation § 1-101`), adapter-constructed; the `Md. Code`
  abbreviation is INFERENCE from standard Maryland citation usage, and
  the article display name + section number are VERIFIED from the site's
  own page text.
- `SectionRef.identifier` is the full `{subtitle}-{section}` citation
  exactly as the section page headings name it (e.g. `"1-101"`,
  `"2-103.1"`, `"5-4A-01"`), with any `&ndash;` normalized to an ASCII
  hyphen.

## Error Boundary

- A section that does not exist returns HTTP 200 with
  `<Label>File Not Found</Label>` inside the `StatuteText` div. VERIFIED
  live (`?article=gtr&section=1-999`). Mapped to `RefNotFoundError`.
- An invalid `GetSections` article code returns a 200 JSON body
  `{"message": "No HTTP resource was found ..."}`. VERIFIED live
  (`?articleCode=zzz`). Mapped to `RefNotFoundError` in listing paths.

## Known Limitations

- Subtitle/chapter groupings have no page of their own; they are derived
  from the article's flat section list, so `build_url(ChapterRef)`
  returns the article's `GetSections` API URL (the closest real
  resource).
- The `GetSections` JSON API is required for discovery and depends on the
  `enactments=false` query parameter; if the API shape or parameter
  contract changes, listing breaks (the adapter treats a non-array
  response as an error).
- Whether every article's section list and every section page keep the
  same shape has only been sampled (articles `gtr`, `gag`; sections
  `1-101`, `2-103.1`, `5-4A-01`, and a not-found page).
