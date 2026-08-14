# State #6 Candidate Comparison

Research performed Aug 14, 2026, by direct live requests to each
candidate's official source from the working environment. Findings are
labeled VERIFIED (observed live), UNVERIFIED (not yet exercised),
INFERENCE (reasoned from verified structure), or ARCHITECTURAL
CONCLUSION (a framework-fit judgment).

## Selection Summary

**Selected State #6: Florida** (`flsenate.gov/Laws/Statutes/`).

Florida is the only candidate that introduces a genuinely new
architectural axis — the **versioned statute source**. The Florida
Statutes are published as distinct per-year editions (1997–2027 are all
served on the official site; VERIFIED), and every URL carries the
edition year. No existing adapter serves a versioned source, so the
framework must decide, explicitly, which published edition to serve and
how — the same question every earlier adapter answered implicitly by
assuming "the current code". Florida resolves it cleanly by pinning the
current published edition year as an adapter-internal constant,
requiring no ref-model, registry, or MCP-tool change.

California is the runner-up (clean per-section retrieval plus a
5-level hierarchy) but its chapter-level text listing is
client-side/JS-rendered, so the framework's `list_sections` discovery
contract cannot be satisfied server-side — the same flaw that excluded
Kansas from State #5. Oklahoma is unchanged from the State #5 review
(bulk per-title PDF, no addressable chapter level) and remains unfit.

Ohio, New York, Michigan, and Pennsylvania are **UNREACHABLE from this
environment** (documented below) and were excluded on that basis alone.

## Evaluation Criteria

Candidates were evaluated against the ten criteria used for State #5:

- **Official source accessibility** — reachable, stable, no auth/paywall.
- **Retrieval architecture** — how one section is fetched.
- **Discovery architecture** — how titles/chapters/sections are enumerated.
- **Hierarchy** — structural levels and how many are addressable/citable.
- **Citation format** — the state's canonical citation string.
- **Section retrieval** — exact mechanism to obtain one section's text.
- **History/version information** — amendment history and edition/effective data.
- **Error behavior** — how "not found" is signaled.
- **Framework compatibility** — whether `TitleRef/ChapterRef/SectionRef`
  is satisfiable without changing `BaseStateAdapter`, the ref models,
  the registry, or the MCP tools.
- **Architectural value** — whether the source teaches a genuinely new
  structural/retrieval pattern versus another adapter of an existing kind.

## Reachability Screening (all candidates)

The following official sources were probed live; HTTP status / timeout:

| State | Official source | Result |
|-------|-----------------|--------|
| California | `leginfo.legislature.ca.gov` | HTTP 200. VERIFIED reachable. |
| Florida | `flsenate.gov` | HTTP 200. VERIFIED reachable. |
| Oklahoma | `oklegislature.gov` | HTTP 200. VERIFIED reachable. |
| Ohio | `codes.ohio.gov` | Connection timeout (>60 s, https and http). VERIFIED unreachable. |
| New York | `nysenate.gov` / `legislation.nysenate.gov/api/3/` | HTTP 403 (bot protection); API timed out. VERIFIED unreachable. |
| Michigan | `legislature.mi.gov` | HTTP 403 on every route tested. VERIFIED unreachable. |
| Pennsylvania | `legis.state.pa.us` | Connection timeout (>25 s). VERIFIED unreachable. |

ARCHITECTURAL CONCLUSION: the four "big-name" candidates (OH/NY/MI/PA)
cannot be exercised from this environment, so any adapter built for them
would rest on UNVERIFIED source behavior. The reachable set narrows the
research to California, Florida, and Oklahoma.

## Candidate: California

**Official source:** `https://leginfo.legislature.ca.gov/` — official
California Legislative Information portal. VERIFIED reachable.

**Retrieval model:** Per-section server-rendered HTML addressed purely
by `(lawCode, sectionNum)` query parameters:
`/faces/codes_displaySection.xhtml?lawCode=PEN&sectionNum=187`.
VERIFIED — HTTP 200, real body text ("Murder is the unlawful killing of
a human being..."), and a clean per-section history record
("Amended by Stats. 2023, Ch. 260, Sec. 14. (SB 345) Effective
January 1, 2024."). VERIFIED.

**Discovery model:** A JSF tree that is expanded node-by-node via
`codes_displayexpandedbranch.xhtml?tocCode=PEN&division=&title=&part=
&chapter=&article=&nodetreepath=N`. VERIFIED that the tree expansion
endpoints render server-side (HTTP 200 with node links), but the
chapter's full text/listing page (`codes_displayText.xhtml`) is an
**empty shell loaded by client-side JavaScript**. VERIFIED — the page
returns `<h1>Code Section Group</h1><h2>Code Text</h2>` and no statute
text. There is no server-rendered chapter→section listing.

**Hierarchy:** Code (29 codes, e.g. PEN) → Division → Title → Part →
Chapter → Article → Section. The citation is `Penal Code § 187`
(code + number); the chapter is **not** part of the citation and **not**
needed for retrieval. VERIFIED.

**Framework fit:** ARCHITECTURAL CONCLUSION — `list_sections` is the
blocker. The framework contract requires server-side enumeration of a
chapter's sections; California only offers that through a JS-rendered
page or a fragile multi-hop JSF tree walk. This is the same flaw that
excluded Kansas from State #5.

**New pattern:** Moderate. Section-number-only citation/retrieval and a
5-level hierarchy are novel, but "chapter not in the citation /
retrieval" is already covered by Virginia, and deep-level flattening is
already covered by Delaware. The per-section effective date is
interesting but stores as raw `amendment_notes` under the current
contract.

**Main risk:** The JS-driven chapter listing makes `list_sections`
unverifiable server-side; the JSF tree state (`nodetreepath`,
`facelets.ui.DebugOutput` params) is fragile.

**Recommendation:** No — discovery contract cannot be met cleanly.

## Candidate: Florida

**Official source:** `https://www.flsenate.gov/Laws/Statutes/` —
official Florida Senate site; server-rendered HTML, no auth. VERIFIED.

**Retrieval model:** **Chapter-document anchors, versioned by year.**
Each chapter has one `/All` document containing every section inline:
`/Laws/Statutes/2025/Chapter775/All` → 55 `<div class="Section">`
blocks, each with `<span class="SectionNumber">775.01</span>`,
`<span class="Catchline"><span class="CatchlineText">Common law of
England.</span></span>`, `<span class="SectionBody">` body text, and a
trailing `<div class="History"><span class="HistoryText">s. 1, Nov. 6,
1829; ...</span></div>`. VERIFIED. A per-section URL
(`/Laws/Statutes/2025/Chapter775/Section775.01`) **redirects to the
statutes root** — sections have no per-section page. VERIFIED.

**Discovery model:** Fully server-rendered at every level. VERIFIED:
- Titles: 49, from the home page
  (`/Laws/Statutes/2025/Title1` … `/Title49`, `<span class="title">Title
  I</span>` + descript name).
- Chapters: per title page, `<a href="/Laws/Statutes/2025/Chapter775">
  <span class="chTitle">Chapter 775</span><span class="chDescript">-
  GENERAL PENALTIES; ...</span></a>`.
- Sections: per chapter `/All` document (SectionNumber anchors).

**Versioning (the new axis):** The site publishes the Florida Statutes
as distinct per-year editions; the year selector offers **1997 through
2027**, and `Laws/Statutes/2026`, `/2024`, `/2023` all return HTTP 200.
VERIFIED. The site's default edition is 2025. VERIFIED.

**Hierarchy:** Title → Chapter → Section. The citation
(`s. 775.01, Fla. Stat.`) encodes chapter.section, so the full section
number carries the chapter — exactly the Washington/Texas convention.
VERIFIED.

**History/version:** Per-section `HistoryText` amendment chain
VERIFIED; per-year edition VERIFIED; no per-section effective date in
the `/All` document (UNVERIFIED that none exists — none observed).

**Error behavior:** A nonexistent chapter path returns HTTP 404
(INFERENCE from server behavior; only a valid chapter was fetched). A
section with no matching `SectionNumber` anchor is simply absent from
the `/All` document — the adapter signals `RefNotFoundError` itself
(INFERENCE, mirroring the verified Delaware pattern).

**Framework fit:** Good. Three levels, exactly one per ref model, no
flattening needed. The edition year has no ref-model slot, which is the
architectural point: it is resolved as an adapter-internal constant.

**New pattern:** **Versioned statute source** — the first candidate
where "which edition of the statutes" is an explicit, verifiable,
first-class dimension, plus a second, chapter-scoped instance of the
document-embedded-anchor retrieval model.

**Main risk:** Version drift — a new year publishes annually and the
pinned default year must be updated deliberately; `UNVERIFIED` that
every chapter's `/All` document renders in the same structure.

**Recommendation:** **Yes.**

## Candidate: Oklahoma

**Official source:** `https://www.oklegislature.gov/osstatuestitle.html` —
official Oklahoma Legislature site. VERIFIED reachable.

**Retrieval model:** Bulk per-title PDF
(`https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os1.pdf`,
`os3A.pdf` for lettered titles). VERIFIED unchanged from the State #5
review. No per-section URL; one section is located by downloading and
parsing the whole title PDF.

**Hierarchy:** Title → Section. The citation is `21 O.S. § 1`
(title.section); **no addressable chapter level**. VERIFIED (as
documented in `state5_candidate_comparison.md`).

**Framework fit:** ARCHITECTURAL CONCLUSION — `ChapterRef` is required
in every `SectionRef`, and Oklahoma exposes no official chapter index;
chapters would have to be derived from PDF text (fragile) or the model
changed. Requires a new PDF-parsing dependency.

**New pattern:** Bulk/binary download is genuinely novel, but at the
cost of framework redesign and a new dependency.

**Recommendation:** No — unchanged from State #5; requires framework
change.

## Comparison Table

| State | Official source | Retrieval model | Discovery model | Hierarchy fit | New pattern | Risks | Recommendation |
|-------|-----------------|-----------------|-----------------|---------------|-------------|-------|----------------|
| California | leginfo.legislature.ca.gov | Per-section HTML, `(lawCode, sectionNum)` query params | JSF tree-walk; chapter text page is JS-rendered | Fits 3 levels; chapter absent from citation | Section-number-only citation; 5-level flattening; per-section effective date | `list_sections` not server-enumerable; fragile JSF tree | No |
| **Florida** | **flsenate.gov/Laws/Statutes/** | **Chapter `/All` document + SectionNumber anchors, per edition year** | **Server-rendered: home → 49 titles → chapters → sections** | **Perfect 3-level fit; edition year is adapter-internal** | **Versioned statute source (1997–2027 editions)** | Year drift; `UNVERIFIED` every `/All` is identical | **Yes** |
| Oklahoma | oklegislature.gov | Bulk per-title PDF + local search | Per-title PDF TOC | No addressable chapter level | Bulk/binary download | PDF dependency; chapter derivation fragile; framework redesign | No |

## Final Recommendation

**Florida is State #6.**

It is the only reachable candidate that (a) is an official, stable,
fully server-rendered source, (b) introduces a genuinely new
architectural axis — the **versioned statute source**, with 31 published
editions (1997–2027) served on the official site — rather than another
adapter of an existing kind, and (c) fits the existing
`TitleRef → ChapterRef → SectionRef` contract with no redesign,
resolving the version dimension as an adapter-internal constant the same
way Virginia already resolves "the current Code".

California offers the more dramatic hierarchy (five internal levels) and
per-section effective dates, but its chapter→section listing is
JS-rendered, so the framework's `list_sections` discovery contract
cannot be met — the exact flaw that excluded Kansas from State #5.
Oklahoma remains a bulk-PDF source with no addressable chapter level and
would force a framework redesign plus a new dependency.

Florida answers the State #6 question the research is designed to ask:
can the framework serve a source whose statutes genuinely exist in
multiple published editions, without adding a version field to the ref
models? The evidence says yes — by pinning the current published edition
year as an adapter-internal constant and treating the year purely as a
URL component. That is a clean, verifiable, non-speculative handling of
a genuinely new source dimension.
