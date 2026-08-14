# State #5 Candidate Comparison

Research performed Aug 14, 2026, by direct live requests to each
candidate's official source from the working environment. Findings are
labeled VERIFIED (observed live), UNVERIFIED (not yet exercised), or
INFERENCE (reasoned from verified structure).

## Selection Summary

**Selected State #5: Delaware** (`delcode.delaware.gov`).

Delaware is the only candidate that introduces a genuinely new
retrieval model — sections embedded inside a subchapter document and
addressed by explicit `SectionHead` anchor — while still fitting the
existing `TitleRef → ChapterRef → SectionRef` framework contract
without a core-model redesign. Oklahoma requires bulk PDF parsing and a
chapter-derivation step that does not map cleanly onto the framework;
Kansas's discovery path is client-side/JS-driven and does not provide a
stronger new pattern than Delaware.

## Evaluation Criteria

Candidates were evaluated against ten criteria:

- **Official source accessibility** — is the official state source
  reachable and stable from this environment (no auth, no paywall)?
- **Retrieval architecture** — how is a single section fetched? Is it a
  per-section URL, an embedded anchor in a larger document, or a bulk
  download?
- **Discovery architecture** — how are titles/chapters/sections
  enumerated? Server-rendered HTML, JSON API, or client-side JS?
- **Hierarchy** — how many structural levels does the source expose,
  and how many are actually addressable/citable?
- **Citation format** — the state's canonical citation string.
- **Section retrieval** — exact mechanism to obtain one section's text.
- **History/version information** — whether amendment history and
  version/effective-date data are available.
- **Error behavior** — how "not found" is signaled (HTTP status vs
  body semantics).
- **Framework compatibility** — whether the existing
  `TitleRef/ChapterRef/SectionRef` contract is satisfiable without
  changing `BaseStateAdapter`, the ref models, the registry, or the MCP
  tools.
- **Architectural value** — whether the source teaches the framework a
  genuinely new structural/retrieval pattern versus merely adding
  another per-section-HTML adapter.

## Candidate: Oklahoma

**Official source:** `https://www.oklegislature.gov/osstatuestitle.html`
— official Oklahoma Legislature site. VERIFIED reachable.

**Architecture:** Bulk/per-title PDF download. Each title is one PDF,
e.g. `https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf`
(Title 21, "Crimes and Punishments", ~884 pages, 3.6 MB). VERIFIED. The
PDF carries an extractable text layer; TOC pages use citations like
`§21-1`. VERIFIED (pypdf extraction).

**Hierarchy:** Title → Section. The PDF's TOC and body cite sections as
`§21-1` (Title 21, Section 1) with no visible intermediate chapter or
article grouping. VERIFIED in sampled pages; a programmatic scan of
every 25th page found zero `CHAPTER`/`ARTICLE` headings. The OSCN HTML
browse (which does expose Title → Chapter → Article → Section) is
UNREACHABLE from this environment (timeouts), so the only verified
official retrieval surface is the flat per-title PDF.

**Retrieval:** Fetch the entire title PDF, then parse text locally to
locate a section. This is a bulk/binary download pattern — no per-section
URL exists.

**Citation:** `21 O.S. § 1` / `§21-1` (Title.Section). Chapter does not
appear in the citation.

**Limitations:**

- Requires PDF parsing, which needs a new dependency (pypdf/pdfplumber)
  not currently in the project.
- Chapter-level information must be derived from PDF content or omitted,
  which conflicts with the framework's required `ChapterRef` level.
- Downloading a multi-hundred-page PDF per title to fetch one section is
  heavy; no per-section addressing exists.
- The OSCN browse that would have provided a clean hierarchy is not
  reachable from this environment, so the natural fit (HTML browse) is
  unverifiable here.

**Framework fit:** Poor-to-moderate. The missing addressable chapter
level is the core problem. The framework's `ChapterRef` is required in
every `SectionRef`; deriving chapters from PDF text is fragile and would
need to be characterized as INFERENCE, not backed by an official chapter
index. This is the most invasive candidate.

**Architectural value:** High in the abstract (a bulk-binary source is a
genuinely new axis), but the value is undermined by the framework
mismatch and the new-dependency requirement. It would push the framework
toward redesign rather than test the existing contract.

## Candidate: Delaware

**Official source:** `https://delcode.delaware.gov/` — official Delaware
Code site. VERIFIED reachable.

**Architecture:** Server-rendered HTML with dual representations —
per-title HTML browse pages **and** per-title "Authenticated PDF"
(e.g. `https://delcode.delaware.gov/title11/Title11.pdf`, 496 pages,
text-extractable). VERIFIED.

**Hierarchy:** Title → Chapter → Subchapter → Section. VERIFIED:

- Home lists 31 titles (`title{N}/index.html` + `title{N}/title{N}.pdf`).
  VERIFIED.
- Title page lists chapters (`c001`, `c002`, ..., `c084a`, `c087a`).
  VERIFIED.
- Chapter page lists **either** subchapters **or** inline sections:
  - c005 (Crimes and Criminal Procedure) → subchapters `sc01`–`sc07`,
    no inline sections. VERIFIED.
  - c001 → inline sections `id="101"`, `102`, `103`, no subchapters.
    VERIFIED.
- Subchapter page contains sections inline as
  `<div class="SectionHead" id="501">` followed by
  `<p class="subsection">` body paragraphs. VERIFIED.

**Section retrieval:** Sections are **anchors within a subchapter (or
chapter) document** — there is no per-section URL. A direct URL such as
`/title11/c005/sc01/501.html` returns **HTTP 404**. VERIFIED. A
requested section is located by fetching its containing document and
matching the `SectionHead` id anchor.

**Citation:** `11 Del. C. § 501` (Title.Section). The section number
(e.g. `501`) is the anchor id and is unique within the title. VERIFIED.

**History/version:** Each section block ends with an amendment-history
chain with hyperlinks, e.g. `11 Del. C. 1953, § 501; 58 Del. Laws, c.
497, § 1; 67 Del. Laws, c. 130, § 8; 70 Del. Laws, c. 186, § 1`.
VERIFIED for § 501.

**Error behavior:** Invalid chapter → HTTP 404. VERIFIED
(`/title11/c999/index.html` → 404). A section that does not exist in a
valid document simply has no matching anchor — no error page; the
adapter signals `RefNotFoundError` itself. The PDF header also documents
the code version: "includes all acts enacted as of July 21, 2026".
VERIFIED.

**Framework fit:** Good. Subchapter is a presentation/discovery grouping
that carries no number of its own in the citation and can be treated as
an adapter-internal retrieval detail (fetch chapter → resolve subchapter
→ extract anchor), analogous to how Texas's internal title headings and
Virginia's Article/SubPart levels are flattened. `TitleRef.identifier`
= `11`, `ChapterRef.identifier` = `5`, `SectionRef.identifier` = `501`
all fit the existing string-based ref models unchanged.

**Architectural value:** High and achievable. It introduces the first
**document-embedded anchor** retrieval model (section found inside a
larger container by explicit boundary marker) — distinct from
Washington's per-section pages, Texas's range-boundary chapter parsing,
Illinois's static files, and Virginia's JSON API. It also exercises the
**fourth-level flattening** question within the existing three-level
contract.

## Candidate: Kansas

**Official source:** `https://www.kslegislature.org/li/b2025_26/statute/`
— official Kansas Legislature site. VERIFIED reachable.

**Architecture:** Server-rendered per-section HTML pages with rich
structured META tags. Chapter → Article → Section.

**Hierarchy:** Chapter (`021_000_0000_chapter/`) → Article
(`021_009_0000_article/`) → Section (`021_009_0022_section/...`).
VERIFIED.

**Section retrieval:** Per-section pages are directly addressable, e.g.
`/021_000_0000_chapter/021_009_0000_article/021_009_0022_section/021_009_0022_k/`.
VERIFIED. Pages carry META tags (`T_KSASECTEXT_S_KSANUM`,
`T_KSASECTEXT_S_CHAPTERNUM`, `T_KSASECTEXT_S_ARTICLENUM`,
`T_KSASECTEXT_S_SECTIONNUM`), a History line, Prev/Next links, and a
per-section PDF link. VERIFIED.

**Discovery:** The weakness. An article page server-renders **only one
section**; the full section index is client-side/JS-driven (HTMX /
`#statute-toc`). VERIFIED — no server-rendered full section listing was
found. Prev/Next links cross chapter/article boundaries (e.g. prev is
in chapter 020), so they do not provide a clean per-chapter listing.

**Citation:** `21-922` (Chapter-Article-Section, K.S.A.). The citation
format actually encodes all three levels in the section number.

**Framework fit:** Moderate. The three levels map cleanly onto
Title/Chapter/Section, but `list_sections` (the discovery hop) is the
blocker: the framework contract requires server-side enumeration, and
Kansas's only complete listing is JS-driven.

**Architectural value:** Moderate. The META-tag richness is interesting,
but the retrieval model is still fundamentally per-section HTML (similar
in kind to Washington), and the JS-dependent discovery is a regression
versus every other candidate.

## Comparison Table

| State | Source architecture | Hierarchy | Section retrieval | Discovery | Framework fit | New pattern | Main risk | Recommendation |
|-------|---------------------|-----------|-------------------|-----------|---------------|-------------|-----------|----------------|
| Oklahoma | Bulk per-title PDF | Title → Section (flat; chapters absent) | Download whole title PDF + local text search | Per-title PDF TOC; OSCN HTML browse unreachable | Poor — no addressable chapter level | Bulk/binary download | Requires PDF dependency; chapter derivation fragile | No |
| Delaware | Server-rendered HTML + per-title PDF | Title → Chapter → Subchapter → Section | Fetch containing subchapter doc, match `SectionHead` anchor | Home → title → chapter → subchapter, all server-rendered | Good — subchapter flattenable, refs fit as-is | Document-embedded anchor retrieval + 4th-level flattening | Section→container mapping must be resolved at retrieval time | **Yes** |
| Kansas | Per-section HTML with META tags | Chapter → Article → Section | Direct per-section URL | Section index is JS/HTMX-driven; article page renders one section only | Moderate — listing blocker | Rich structured META tags | `list_sections` cannot be enumerated server-side | No |

## Final Recommendation

**Delaware is State #5.**

It is the only candidate that (a) is an official, reachable, stable,
server-rendered HTML source, (b) introduces a genuinely new retrieval
model — sections embedded inside a subchapter document and addressed by
explicit `SectionHead` anchors — rather than another per-section-HTML
adapter, and (c) tests the framework's ability to flatten a deeper
source hierarchy (Title → Chapter → **Subchapter** → Section) through the
existing `TitleRef → ChapterRef → SectionRef` contract without a core
redesign.

Oklahoma offers the most abstractly novel architecture (bulk PDF) but
lacks an addressable chapter level and requires a new PDF-parsing
dependency — it would force framework redesign rather than test it.
Kansas offers rich metadata but its JS-driven section listing breaks the
framework's `list_sections` discovery contract, and its retrieval model
is essentially per-section HTML like Washington's.

Delaware answers the State #5 question the research is designed to ask:
can a four-level source be served through the existing three-level
framework? The evidence says yes, with the subchapter treated as an
adapter-internal retrieval detail.
