# South Carolina Statute Source Research

Research performed: Aug 15, 2026. The live host
(`https://www.scstatehouse.gov`) IS reachable from this environment, so
official markup was captured live and inspected. Every URL below was
executed directly against the live site with plain HTTP GETs; structure is
documented verbatim from those responses, which are the implementation
boundary for this adapter.

## Status

**VERIFIED live** for the core discovery and retrieval paths: title
listing (the master title page), chapter listing (the title page), section
listing and section retrieval (the chapter page, which embeds every
section), and the per-section `SECTION {id}.` header. All verified from
live HTTP 200 responses of the official `scstatehouse.gov` HTML.

**UNVERIFIED** for a small set of secondary questions: whether every title
page keeps the same chapter-row markup and every chapter page the same
section markup (sampled Titles 1 and 63; chapters 1 and 3), and whether the
lettered-section plain-text form appears in chapters beyond chapter 1.
Those are flagged below.

**INFERENCE** is used where a conclusion is reasoned from verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://www.scstatehouse.gov` — the official South Carolina
  Legislature publication of the Code of Laws of South Carolina.
- The statutory text is plain server-rendered HTML: no SPA framework, no
  client-side statute rendering. VERIFIED (the live HTML contains the full
  content statically).
- The site names itself "Code of Laws of South Carolina" and organizes the
  code into Titles, Chapters, and Sections. VERIFIED.

## Accessibility

- Fully reachable from this environment: every URL below returned HTTP
  200. VERIFIED.
- No authentication or API key; requests were plain GETs. VERIFIED.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — top level. 63 titles (1 through 63, no gaps), each
  identified by its number, e.g. `1` ("Administration of the Government").
  VERIFIED (63 linked title rows on the master page).
- **Chapter** — grouping within a title, e.g. Chapter 1, 3, 5. Chapter
  numbers are not contiguous (e.g. Title 1 uses chapters 1-34 with gaps).
  VERIFIED.
- **Section** — the individually retrievable unit, e.g. `1-1-10`,
  `1-3-10`, and lettered sections like `1-1-714A`. The section id is the
  full `{title}-{chapter}-{section}` citation.

## URL Scheme

- Title list: `https://www.scstatehouse.gov/code/statmast.php` (200).
  Lists all 63 titles.
- Title page: `https://www.scstatehouse.gov/code/title{N}.php` (e.g.
  `/code/title1.php`, 200). Lists every chapter of the title.
- Chapter page: `https://www.scstatehouse.gov/code/t{NN}c{NNN}.php` (e.g.
  `/code/t01c001.php`, 200). The URL zero-pads the title to 2 digits and
  the chapter to 3 digits regardless of the plain numbers used in the
  row text (e.g. Title 63 Chapter 1 -> `t63c001.php`). The chapter page
  contains ALL of the chapter's sections embedded in it.

## Verified Page Structures

### Title list page (`/code/statmast.php`)

One linked title per row:

```html
<a href="/code/title1.php">Title 1</a> - Administration of the Government</span><br />
<a href="/code/title2.php">Title 2</a> - General Assembly</span><br />
...
<a href="/code/title63.php">Title 63</a> - South Carolina Children&#39;s Code</span><br />
```

VERIFIED (63 rows, Titles 1-63 complete with no gaps). Title names may
contain HTML entities (e.g. `&#39;` in "South Carolina Children&#39;s
Code"), decoded by `strip_tags`.

### Title page (`/code/title{N}.php`)

One table row per chapter, e.g.:

```html
<tr>
<td>CHAPTER 1 - GENERAL PROVISIONS</td>
<td><a href="/code/t01c001.php">HTML</a></td>
<td><a href="/getfile.php?TYPE=CODEOFLAWS&TITLE=1&CHAPTER=1">Word</a></td>
</tr>
<tr>
<td>CHAPTER 3 - GOVERNOR AND LIEUTENANT GOVERNOR</td>
<td><a href="/code/t01c003.php">HTML</a></td>
...
```

Verified for Title 1: 21 chapter rows. The chapter identifier is the
number in `CHAPTER {N} -`; the chapter name is the heading after the dash
(e.g. `GENERAL PROVISIONS`). The Word links are ignored.

### Chapter page (`/code/t{NN}c{NNN}.php`)

Every section of the chapter, one after another. Regular sections:

```html
<span style="font-weight: bold;"> SECTION 1-1-10.</span> Jurisdiction and
boundaries of the State.<br /><br />
	The sovereignty and jurisdiction of this State extends to all places
within its bounds ...<br /><br />
HISTORY: 1962 Code SECTION 39-1; 1952 Code SECTION 39-1; ...<br /><br />
```

Verified for `t01c001.php`: 85 section headers in the bold-span form and 2
lettered sections (`1-1-713A`, `1-1-714A`) in the same shape but WITHOUT
the bold `span` wrapper:

```html
SECTION 1-1-714A. Official state heritage work animal.<br /><br />
	The mule is hereby designated as the official State Heritage Work
Animal of South Carolina.<br /><br />
HISTORY: 2010 Act No. 240, SECTION 3, eff June 11, 2010.<br /><br />
```

- The section heading is the text between the `SECTION {id}.` marker and
  the following `<br />` (e.g. `Jurisdiction and boundaries of the
  State.`). VERIFIED.
- The body runs from the heading's `<br />` to the `HISTORY:` line.
  VERIFIED.
- Every section ends with a `HISTORY:` line (raw amendment/history text,
  e.g. `HISTORY: 2020 Act No. 113 (S.11), SECTION 1, eff February 3,
  2020.`), preserved verbatim as `amendment_notes`. VERIFIED (85/85 in
  chapter 1, 32/32 in chapter 3).
- Larger chapters are split by article dividers
  `<div style="text-align: center;">ARTICLE {N}</div>` (e.g. `ARTICLE 3`
  after section 1-1-30 in chapter 1), which are excluded from section
  parsing. VERIFIED.
- One source quirk: section `1-1-1210` appears TWICE on the chapter page
  (the second occurrence is an amended re-issue of the same section id);
  the adapter deduplicates by identifier. VERIFIED.
- The section's own `SECTION {id}.` header is the only self-identifier; it
  is cross-checked against the requested `SectionRef` in the adapter.

## Citation

- Citation form: `S.C. Code § {title}-{chapter}-{section}` (e.g. `S.C.
  Code § 1-1-10`, `S.C. Code § 16-3-20`), adapter-constructed; the
  `S.C. Code` abbreviation is INFERENCE from standard South Carolina
  citation usage, and the section number is VERIFIED from the site's own
  `SECTION` header text.
- `SectionRef.identifier` is the full `{t}-{c}-{s}` form exactly as the
  chapter page headers name it (e.g. `"1-1-10"`, `"1-1-714A"`).

## Error Boundary

- A missing title or chapter page returns HTTP 404. VERIFIED live
  (e.g. `/code/title99.php`). Mapped to `RefNotFoundError` in the
  adapter.
- A section that is not present on its chapter page is detected by
  searching for its `SECTION {id}.` header; if absent, `RefNotFoundError`
  is raised. VERIFIED (a number not present in chapter 1, e.g. `1-1-21`,
  is not found).

## Known Limitations

- Sections are embedded in their chapter page, so `build_url(SectionRef)`
  returns the chapter page that contains the section -- the same
  chapter-document pattern Delaware and Florida use. A whole chapter page
  (up to 96 KB, 85 sections in chapter 1) is fetched and scanned for one
  section.
- Whether every title page keeps the same chapter-row markup and every
  chapter page the same section markup has only been sampled (Titles 1
  and 63; chapters 1 and 3).
- The lettered-section plain-text form is verified only for chapter 1
  (`1-1-713A`, `1-1-714A`); other chapters may use only the bold-span
  form.
