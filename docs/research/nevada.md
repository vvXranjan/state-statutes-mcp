# Nevada Statute Source Research

Research performed: Aug 16, 2026. The official host
(`leg.state.nv.us`) could NOT be independently fetched from this
environment (Wayback retrieval was unavailable for this session — see
Accessibility below). The source mechanics documented here are the result
of Claude's independent verification of the official source
(`leg.state.nv.us/nrs/`), which is the research source of truth for this
adapter. No Wayback captures were obtained, so the test fixtures are
**synthetic and representative**: they reproduce ONLY the markup
structures listed as VERIFIED below and are explicitly labeled synthetic
in the fixture files, the test module docstrings, and this document. They
are NOT official government captures.

## Status

**VERIFIED** (via independent verification of the official
`leg.state.nv.us/nrs/` source, reported by the research source of truth
for this batch) for the core discovery and retrieval mechanics:

- Official source: `leg.state.nv.us/nrs/`.
- Hierarchy: Title → Chapter → Section.
- The root lists titles and chapter links.
- Chapter documents contain section anchors and section bodies.
- Chapter URL form: `/nrs//NRS-{chapter}.html` (note the literal double
  slash after `/nrs/`).
- Section anchor example: `#NRS220Sec040` (a per-chapter anchor id of the
  form `NRS{chapter}Sec{seq}`).
- Citation: `NRS {chapter}.{section}` (e.g. `NRS 220.170`).
- History: bracketed session-law text appears after the section body.
- Lettered chapters are supported (e.g. a `220A`-style chapter).
- Section retrieval is chapter-document based (sections are embedded in
  their chapter document, not one page per section).

**UNVERIFIED** (this environment could not independently fetch or capture
the official source, so these remain unverified):

- The live HTTP status/404 behavior for a missing chapter or section.
- The exact HTML markup of the root title list, of a chapter document's
  section headings, and of the anchor elements (only the anchor id form
  `#NRS{chapter}Sec{seq}` and the citation form `NRS {c}.{s}` are known).
- The exact relationship between the anchor sequence number (`040`) and
  the section's citation number (`170`).

**INFERENCE** is used where a conclusion is reasoned from the verified
structure rather than directly observed (noted inline).

## Source

- Site: `https://www.leg.state.nv.us/nrs/` — the official Nevada
  Legislature publication of the Nevada Revised Statutes (NRS).
  VERIFIED the path (`/nrs/`) and host (`leg.state.nv.us`); the canonical
  `www.` subdomain prefix is INFERENCE.
- The site publishes the NRS as server-rendered HTML. VERIFIED it is
  chapter-document based (each chapter is one document with embedded
  sections).

## Accessibility

- The official host could not be independently fetched from this
  environment in this session, and Wayback Machine retrieval was
  unavailable (repeated attempts failed). UNVERIFIED — the lack of live
  capture is an environmental limitation, not evidence about the site.
- No authentication or API key is required to view the NRS. VERIFIED from
  the official source's public navigation model.

## Hierarchy

Three structural levels, matching the framework:

- **Title** — the top level. The root lists the titles, each with its
  chapter links. VERIFIED.
- **Chapter** — grouping within a title. Chapter identifiers are numbers
  (e.g. `220`), with lettered chapters supported (e.g. `220A`). VERIFIED.
- **Section** — the individually retrievable unit, embedded in its
  chapter document. Section identifiers are the full `{chapter}.{section}`
  citation numbers (e.g. `220.170`). VERIFIED.

## URL Scheme

- Root (title + chapter list): `https://www.leg.state.nv.us/nrs/`.
  VERIFIED (the root lists titles and chapter links).
- Chapter document: `https://www.leg.state.nv.us/nrs//NRS-{chapter}.html`
  (e.g. `/nrs//NRS-220.html`). VERIFIED — the double slash is part of the
  documented form and is preserved exactly. Lettered chapters use the
  letter in the file name (e.g. `/nrs//NRS-220A.html`); the lettered file
  name form is INFERENCE from the lettered-chapter support.
- Section: the section's own chapter document — sections are embedded in
  their chapter document, so the chapter document is the closest real
  resource (the same model `SouthCarolinaAdapter` uses). VERIFIED
  (section retrieval is chapter-document based).

## Section anchors

- Each section in a chapter document carries an anchor id of the form
  `NRS{chapter}Sec{seq}`, e.g. `#NRS220Sec040`. VERIFIED (the anchor
  example).
- The anchor id is a per-chapter identifier and is distinct from the
  section's citation number (`NRS 220.170` in the example has anchor
  `NRS220Sec040`). The exact arithmetic between `seq` and the citation
  number is UNVERIFIED; the adapter therefore does NOT derive the anchor
  from a citation — it uses the anchors only as section-boundary markers
  and reads each section's citation from its own heading text
  (`NRS {chapter}.{section}`), which is VERIFIED.
- Lettered-chapter anchor form (`NRS220ASec001`-style) is INFERENCE from
  the verified anchor pattern plus verified lettered-chapter support.

## Verified Page Structures

### Root (`/nrs/`) — title + chapter listing

The root lists titles and, under each title, that title's chapter links
(the chapter links point at the chapter documents `/nrs//NRS-{chapter}.html`).
VERIFIED. The exact markup of the title headings and chapter link rows is
UNVERIFIED, so the synthetic fixtures use representative markup (see
`tests/fixtures/nv_*`): each title is a heading carrying its number and
name, followed by one chapter link row per chapter whose href is the
`/nrs//NRS-{chapter}.html` form and whose text carries the chapter number
and name.

### Chapter document (`/nrs//NRS-{chapter}.html`)

VERIFIED that a chapter document contains the chapter's sections, each
anchored (`NRS{chapter}Sec{seq}`) and each carrying its citation heading
(`NRS {chapter}.{section}`) and body, with bracketed session-law history
text after the section body. The exact heading/body markup is UNVERIFIED;
the synthetic fixtures use a representative structure:

- Each section opens with an anchor element
  `<a name="NRS220Sec040"></a>` (the `#NRS220Sec040` form).
- The heading line is the citation plus caption, e.g.
  `NRS 220.170 Authority to acquire property.`. The adapter strips the
  leading citation and keeps the caption as the heading.
- The body runs from after the heading to the next section's anchor.
- The history is a bracketed session-law string at the end of the body,
  e.g. `[1:21:1955]`, preserved verbatim as `amendment_notes` and removed
  from the body.

## Citation

- Citation form: `NRS {chapter}.{section}` (e.g. `NRS 220.170`).
  VERIFIED.
- `SectionRef.identifier` is the full `{chapter}.{section}` number
  (e.g. `"220.170"`), matching the citation. VERIFIED.

## History

- History is bracketed session-law text that follows the section body
  (e.g. `[1:21:1955]`). VERIFIED. The adapter captures the bracketed text
  verbatim as `amendment_notes` and removes it from the body. Whether a
  section can have no history (making `amendment_notes` optional) is
  INFERENCE from the framework's optional-history convention; the tests
  exercise both present and absent history.

## Error Boundary

- The live HTTP 404 behavior of a missing chapter/section is UNVERIFIED
  (the source could not be fetched from this environment).
  Convention-based mapping used by this adapter and documented here:
  HTTP 404 maps to `RefNotFoundError`, other network failures to
  `AdapterUnavailableError` (same convention as every other adapter).
- A section that is not present in a fetched chapter document raises
  `RefNotFoundError` — this is an adapter-level expected behavior based on
  project convention (the same signal `SouthCarolinaAdapter` uses for an
  embedded section absent from its chapter page). The live not-found
  behavior of the Nevada source is UNVERIFIED.

## Known Limitations

- No real Nevada markup was captured in this environment (Wayback
  retrieval unavailable); the fixtures are synthetic and representative,
  reproducing only the VERIFIED structures above. They are NOT official
  government captures.
- The exact HTML markup of the root and of the chapter documents beyond
  the VERIFIED structures is UNVERIFIED; the adapter parses against the
  representative fixture structure and fails loudly (`NormalizationError`)
  if a real source page diverges.
- The live 404 semantics are UNVERIFIED; the not-found mapping follows
  project convention and is documented as such.