# New Hampshire Statute Source Research

Research performed: Aug 16, 2026. The official host (`gc.nh.gov`) could
NOT be independently fetched from this environment (Wayback retrieval was
unavailable for this session — see Accessibility below). The source
mechanics documented here are the result of Claude's independent
verification of the official source (`gc.nh.gov/rsa/html/`), which is the
research source of truth for this adapter. No Wayback captures were
obtained, so the test fixtures are **synthetic and representative**: they
reproduce ONLY the markup structures listed as VERIFIED below and are
explicitly labeled synthetic in the fixture files, the test module
docstrings, and this document. They are NOT official government captures.

## Status

**VERIFIED** (via independent verification of the official
`gc.nh.gov/rsa/html/` source, reported by the research source of truth
for this batch) for the core discovery and retrieval mechanics:

- Official source: `gc.nh.gov/rsa/html/`.
- Hierarchy: Title → Chapter → Section.
- Title index: `/rsa/html/nhtoc.htm`.
- Chapter document example: `/rsa/html/xvi/201-a/201-a-mrg.htm` (a
  chapter document at `/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm`).
- Source title directories use Roman numerals (e.g. `xvi` for Title 16);
  framework identifiers remain Arabic (e.g. `16`).
- Citation: `RSA {chapter}:{section}` (e.g. `RSA 201-A:1`).
- History: a `Source.` line.
- Repealed sections/ranges appear inline (in the chapter document).
- Lettered chapters are supported (e.g. `201-A`).

**UNVERIFIED** (this environment could not independently fetch or capture
the official source, so these remain unverified):

- The live HTTP status/404 behavior for a missing title, chapter, or
  section.
- The exact HTML markup of `nhtoc.htm` and of the chapter documents
  beyond the VERIFIED structural elements (the `Section {c}:{s}` heading
  marker, the `Source.` line, and the inline repealed sections/ranges).
- The exact markup of an inline repealed section or repealed range.

**INFERENCE** is used where a conclusion is reasoned from the verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://gc.nh.gov/rsa/html/` — the official New Hampshire
  Revised Statutes Annotated (RSA) publication. VERIFIED (path and host).
- The RSA is published as server-rendered HTML, one document per chapter.
  VERIFIED (chapter documents like `/rsa/html/xvi/201-a/201-a-mrg.htm`).

## Accessibility

- The official host could not be independently fetched from this
  environment in this session, and Wayback Machine retrieval was
  unavailable (repeated attempts failed). UNVERIFIED — the lack of live
  capture is an environmental limitation, not evidence about the site.
- No authentication or API key is required to view the RSA. VERIFIED from
  the official source's public navigation model.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — the top level, listed on the title index `nhtoc.htm`.
  Source title directories use Roman numerals (e.g. `xvi` for Title 16);
  framework identifiers remain Arabic (e.g. `16`). VERIFIED.
- **Chapter** — grouping within a title, identified by its chapter number
  (e.g. `201`), with lettered chapters supported (e.g. `201-A`).
  VERIFIED. The chapter URL directory is the chapter identifier
  lower-cased (e.g. `201-a`); the lower-casing is INFERENCE from the
  verified example `/rsa/html/xvi/201-a/201-a-mrg.htm` for a lettered
  chapter that is cited as `201-A`.
- **Section** — the individually retrievable unit, embedded in its
  chapter document. Section identifiers are the full `{chapter}:{section}`
  citation form (e.g. `201-A:1`). VERIFIED.

## URL Scheme

- Title index: `https://gc.nh.gov/rsa/html/nhtoc.htm`. VERIFIED. The
  title index lists the titles (each with its chapter links, per the
  verified Title → Chapter → Section hierarchy — the exact markup is
  UNVERIFIED and the synthetic fixture uses representative markup).
- Chapter document:
  `https://gc.nh.gov/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm` where
  `{roman}` is the title number in Roman numerals (e.g. `xvi` for Title
  16) and `{chapter}` is the chapter identifier lower-cased (e.g.
  `201-a`). VERIFIED (the `xvi/201-a/201-a-mrg.htm` example). The Roman
  numeral conversion (Arabic → Roman) is a documented adapter behavior;
  the lower-casing of the chapter identifier is INFERENCE from the
  verified lettered example.
- Section: the section's own chapter document — sections are embedded in
  their chapter document, so the chapter document is the closest real
  resource (the same model `SouthCarolinaAdapter` uses). VERIFIED
  (chapter documents carry the sections, including repealed sections
  inline).

## Verified Page Structures

### Title index (`/rsa/html/nhtoc.htm`)

VERIFIED that the title index lists titles and supports the Title →
Chapter → Section hierarchy; the exact markup is UNVERIFIED. The
synthetic fixture uses a representative structure: each title is a
heading carrying its Roman numeral (`TITLE XVI`) and name, followed by
one chapter link row per chapter whose href is the
`/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm` form and whose text
carries the chapter identifier in citation form (e.g. `CHAPTER 201-A`)
and name.

### Chapter document (`/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm`)

VERIFIED structural elements (the exact surrounding markup is
UNVERIFIED; the synthetic fixtures use a representative structure):

- Each section is marked by a heading of the form `Section {c}:{s}`
  (e.g. `Section 201-A:1`), followed by the section's own heading
  `{c}:{s} {Caption}.` (e.g. `201-A:1 Definitions.`) and then the body.
- The section's history is a `Source.` line (e.g.
  `Source. 1971, 224:1.`), preserved verbatim as `amendment_notes`.
- Repealed sections and repealed ranges appear inline: a repealed section
  appears in place with its repeal annotation (e.g.
  `201-A:2 [Repealed 2005, 210:1, eff. Jan. 1, 2006.]`), and a repealed
  range appears inline as a section whose heading spans the range (e.g.
  `201-A:3 to 201-A:5 [Repealed.]`). These are preserved verbatim in the
  heading/body text; no structural repealed signal is defined, so
  `status` stays `UNKNOWN` under the framework's no-prose-inference rule.

## Citation

- Citation form: `RSA {chapter}:{section}` (e.g. `RSA 201-A:1`).
  VERIFIED.
- `SectionRef.identifier` is the full `{chapter}:{section}` form
  (e.g. `"201-A:1"`), matching the citation. VERIFIED.
- `ChapterRef.identifier` and `TitleRef.identifier` remain Arabic
  (e.g. `"201-A"`, `"16"`), even though the URL directory uses Roman
  numerals and lower-case letters. VERIFIED.

## History

- History is a `Source.` line following the section body (e.g.
  `Source. 1971, 224:1.`). VERIFIED. The adapter captures the `Source.`
  line verbatim as `amendment_notes` and removes it from the body.
  Repealed sections may have no `Source.` line (INFERENCE — they carry a
  repeal annotation instead), making `amendment_notes` optional.

## Error Boundary

- The live HTTP 404 behavior of a missing title/chapter/section is
  UNVERIFIED (the source could not be fetched from this environment).
  Convention-based mapping used by this adapter and documented here:
  HTTP 404 maps to `RefNotFoundError`, other network failures to
  `AdapterUnavailableError` (same convention as every other adapter).
- A section that is not present in a fetched chapter document raises
  `RefNotFoundError` — an adapter-level expected behavior based on project
  convention (the same signal `SouthCarolinaAdapter` uses for an embedded
  section absent from its chapter page). The live not-found behavior of
  the New Hampshire source is UNVERIFIED.

## Known Limitations

- No real New Hampshire markup was captured in this environment (Wayback
  retrieval unavailable); the fixtures are synthetic and representative,
  reproducing only the VERIFIED structures above. They are NOT official
  government captures.
- The exact HTML markup of `nhtoc.htm` and of the chapter documents
  beyond the VERIFIED structural elements is UNVERIFIED; the adapter
  parses against the representative fixture structure and fails loudly
  (`NormalizationError`) if a real source page diverges.
- The live 404 semantics are UNVERIFIED; the not-found mapping follows
  project convention and is documented as such.
- The lower-casing of the chapter URL directory for a lettered chapter is
  INFERENCE from the verified `201-a` example.