# Oregon Statute Source Research

Research performed: Aug 16, 2026. The official host
(`oregonlegislature.gov`) could NOT be independently fetched from this
environment, but a Wayback Machine capture of the official host was
successfully obtained (snapshot `20260224045708id_`, serving the Oregon
Revised Statutes pages) and the source mechanics below were verified
against that real capture. The test fixtures in `tests/fixtures/or_*`
are **real trimmed captures** from that Wayback snapshot (headers and
footer stripped, section blocks preserved verbatim), NOT synthetic.
Oregon pages are Windows-1252 (latin-1) encoded; the fixtures preserve
the original bytes.

## Status

**VERIFIED** (against the Wayback capture `20260224045708id_` of
`oregonlegislature.gov`):

- Official source: `https://www.oregonlegislature.gov/bills_laws/ors/` —
  the official publication of the Oregon Revised Statutes (ORS).
- Hierarchy: Chapter → Section. Sections are `{chapter}.{NNN}`
  identifiers (e.g. `1.001`, `1.212`, `72.345`), where the chapter is a
  1–3 digit number with an optional trailing letter and the section is
  three digits.
- Each chapter's page is `ors{NNN}.html` where `{NNN}` is the chapter's
  numeric prefix zero-padded to three digits; lettered chapter suffixes
  are kept (e.g. `ors001.html` for chapter 1, `ors072A.html` for
  chapter 72A).
- Sections are embedded in their chapter document (chapter-document
  based retrieval). Each section is opened by a heading paragraph
  `<p class=MsoNormal ...>...<b><span style='...'>\xa0\xa0\xa0 1.001
  State policy for courts.</span></b>...`.
- The chapter list in each page's header mirrors the sections, but the
  LIST reflects repeals: a repealed section (e.g. `1.100`) is absent
  from the header list while its heading and body remain in the
  document, carrying a bracketed history such as
  `[Repealed by 1983 c.763 §9]` with no body text.
- Section body content lives in `<p class=MsoNormal>` paragraphs
  following the heading. A layout-spacer paragraph (`\xa0`) separates
  the CORE body region from a NOTES region carrying bracketed
  history/notes.
- The section's own amendment history is a bracketed session-law string
  at the end of the core body (e.g. `[1959 c.552 §1; 1973 c.484 §1; ...
  2025 c.256 §6]`); the adapter lifts the final bracket out as
  `amendment_notes` (whitespace collapsed) and removes it from the body.
  Some sections carry no bracketed history (e.g. `1.020`,
  `Contempt punishment.`), making `amendment_notes` optional.
- Part headings inside the body are all-caps lines (e.g. a section
  subdivided by parts); the adapter drops trailing all-caps lines from a
  body that has no bracketed history, and filters all-caps lines out of
  the notes region.
- The document is Windows-1252 (latin-1) encoded with `\xa0`
  non-breaking spaces and `\r\n` line breaks; the adapter decodes the
  raw bytes as `windows-1252` (the shared UTF-8 fetch helper is not used
  for Oregon by design).
- Citation: `ORS {section}`; `raw_citation` is that form and
  `SectionRef.identifier` is `{section}` (e.g. `"1.001"`).

**BLOCKED BY DESIGN (UNVERIFIED)** — title/chapter discovery:

- The Oregon title index is published ONLY as a PDF
  (`ORS_TitlesChapters.pdf`) and the ORS landing page does not
  server-render a title list. There is therefore no HTML page to
  enumerate titles or chapters from, so `list_titles` and
  `list_chapters` raise `AdapterUnavailableError` directly with a clear
  explanation rather than attempting a fetch. This is a deliberate
  design decision, not a verified absence of the content.

**UNVERIFIED**:

- The live HTTP status/404 behavior of the official host (only the
  Wayback capture was fetchable from this environment).
- Any markup drift since the `20260224045708id_` capture.

## Source

- Site: `https://www.oregonlegislature.gov/bills_laws/ors/` — the
  official Oregon Legislature publication of the Oregon Revised Statutes.
  VERIFIED via the Wayback capture.
- The site publishes the ORS as server-rendered HTML, chapter-document
  based. VERIFIED.

## Accessibility

- The official host was not independently reachable from this environment
  in this session; a Wayback capture (`20260224045708id_`) was used for
  verification and for building the fixtures. UNVERIFIED — the lack of
  live reachability is an environmental limitation, not evidence about
  the site.
- No authentication or API key is required to view the ORS. VERIFIED
  from the captured public navigation model.

## Hierarchy

Two structural levels supported by this adapter:

- **Chapter** — the top-level grouping. Chapter identifiers are 1–3
  digit numbers with optional trailing letters (e.g. `1`, `72A`).
  VERIFIED.
- **Section** — the individually retrievable unit, embedded in its
  chapter document. Section identifiers are the `{chapter}.{NNN}`
  citation numbers (e.g. `1.001`, `4.410`). VERIFIED.

There is no enumerable Title level in the HTML source (the title index
is PDF-only) — see BLOCKED BY DESIGN above.

## URL Scheme

- Chapter / section document:
  `https://www.oregonlegislature.gov/bills_laws/ors/ors{NNN}.html`
  where `{NNN}` is the chapter's numeric prefix zero-padded to three
  digits (e.g. `ors001.html` for chapter 1, `ors072A.html` for chapter
  72A). VERIFIED.
- Section: the section's own chapter document — sections are embedded in
  their chapter document, so that document is the closest real resource
  (the same model `NevadaAdapter` uses). VERIFIED.
- Title: no page exists (title index is PDF-only); `build_url` raises
  `UnsupportedRefError` for a `TitleRef`. BLOCKED BY DESIGN.

## Verified Page Structures

### Chapter document (`ors{NNN}.html`)

Contains the chapter's sections, each opened by a heading paragraph and
carrying its body in `<p class=MsoNormal>` paragraphs. VERIFIED
structure (Windows-1252 bytes):

```html
<div class="WordSection1">...TITLE 1...COURTS OF RECORD; ...</div>
...
<p class=MsoNormal style='margin-bottom:0in;line-height:normal;text-autospace:
none'><b><span style='font-family:"Times New Roman",serif'>
\xa0\xa0\xa0\xa0\xa0 1.001 State
policy for courts.</span></b><span style='font-family:"Times New Roman",serif'>
\r\nThe Legislative Assembly hereby declares that, as ...</span></p>
<p class=MsoNormal style='...'>\r\n...</p>
<p class=MsoNormal style='...'>\xa0</p>
<p class=MsoNormal><span style='...'>[1981 s.s. c.3 §1]</span></p>
<p class=MsoNormal style='...'>\xa0</p>
```

- The section's heading number is the first `{chapter}.{NNN}` token in
  the `<b><span>` element (e.g. `1.001`); the caption is the rest of
  that element's text (e.g. `State policy for courts.`).
- The body runs from the heading paragraph's `<p class=MsoNormal>` open
  tag to just before the next section's heading paragraph. The core body
  is split from the notes region at the first layout-spacer paragraph.
- The final bracketed session-law history in the core body is the
  section's own amendment history (e.g. `1.002` carries
  `[1959 c.552 §1; 1973 c.484 §1; 1981 s.s. c.1 §3; 1995 c.221 §1; 1995
  c.781 §2; 1999 c.787 §1; 2001 c.911 §1; 2007 c.129 §1; 2009 c.47 §1;
  2009 c.484 §1; 2009 c.885 §37a; 2013 c.2 §3; 2013 c.685 §1; 2014 c.76
  §1; 2021 c.199 §1; 2022 c.68 §8; 2023 c.133 §1; 2025 c.88 §1; 2025
  c.256 §6]` — note this is the section's OWN history, not the history
  of a note it references).
- The notes region carries bracketed note references (e.g. the note
  `Note: Sections 3 and 4, chapter 88, Oregon Laws 2025, provide:`
  followed by `Sec. 3. ...` and `Sec. 4. ... [2025 c.88 §3] ...`), which
  are preserved as part of the body text after the core body.
- A repealed section (e.g. `1.100`) has an empty body and a bracketed
  history `[Repealed by 1983 c.763 §9]`; `4.410` has an empty body and
  `[Amended by 1967 c.532 §5; 1967 c.533 §15; 1971 c.777 §5; renumbered
  3.238]`. These return with empty `text` and non-empty
  `amendment_notes`. A section whose body is empty AND carries no
  amendment notes raises `NormalizationError`.

## Citation

- Citation form: `ORS {chapter}.{section}` (e.g. `ORS 1.001`).
  VERIFIED.
- `SectionRef.identifier` is the full `{chapter}.{NNN}` number
  (e.g. `"1.001"`), matching the heading number. VERIFIED.

## History

- History is a bracketed session-law string at the end of the core body
  (e.g. `[1959 c.552 §1; ...]`). VERIFIED. The adapter preserves the
  final bracket verbatim (whitespace collapsed) as `amendment_notes` and
  removes it from the body.
- Sections may have no bracketed history (e.g. `1.020`), making
  `amendment_notes` optional. VERIFIED.

## Error Boundary

- The live HTTP 404 behavior of the official host is UNVERIFIED (only
  the Wayback capture was reachable). Convention-based mapping used by
  this adapter and documented here: HTTP 404 maps to `RefNotFoundError`,
  other network failures to `AdapterUnavailableError` (same convention
  as every other adapter).
- A section whose heading number is not present in a fetched chapter
  document raises `RefNotFoundError` — an adapter-level expected
  behavior based on project convention. The live not-found behavior of
  the Oregon source is UNVERIFIED.
- `list_titles` and `list_chapters` raise `AdapterUnavailableError`
  directly (BLOCKED BY DESIGN; see above).

## Known Limitations

- Title/chapter discovery is unsupported (BLOCKED BY DESIGN): the title
  index is PDF-only and no HTML chapter listing exists, so only
  `list_sections` and section retrieval are available for Oregon.
- The fixtures are real trimmed captures from the Wayback snapshot
  `20260224045708id_`; the trimmed `ors001` fixture
  (`tests/fixtures/or_ors001_trimmed.html`) preserves only a subset of
  the chapter's section blocks (and skips the header's chapter-list
  entries that were trimmed), so `list_sections` on that fixture returns
  only the included sections. `tests/fixtures/or_ors004.html` is the
  full real capture.
- Oregon pages are Windows-1252 encoded; the fixtures preserve the raw
  bytes and the adapter decodes them as `windows-1252`.
- The live 404 semantics are UNVERIFIED; the not-found mapping follows
  project convention and is documented as such.