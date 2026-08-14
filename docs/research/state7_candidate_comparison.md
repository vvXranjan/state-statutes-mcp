# State #7 Candidate Comparison

Research performed Aug 14, 2026, by direct live requests to each
candidate's official source from the working environment. Findings are
labeled VERIFIED (observed live), UNVERIFIED (not yet exercised),
INFERENCE (reasoned from verified structure), or ARCHITECTURAL
CONCLUSION (a framework-fit judgment).

## Selection Summary

**Selected State #7: South Dakota** (`sdlegislature.gov/api/Statutes/`).

South Dakota is the only reachable candidate that introduces a genuinely
new architectural axis — the **official JSON API with flat records,
embedded HTML content, and linked-list navigation**. The Codified Laws
are served through a REST API (`/api/Statutes/*`) whose records are flat
"Statute" objects carrying a `Type` discriminator (Title / Chapter /
Section), a `parents` hierarchy array, `Next`/`Previous` navigation
pointers, and the section's full rendered HTML embedded directly in the
JSON. No existing adapter retrieves statute text from a JSON API record
whose content payload is embedded HTML — Virginia's JSON API returns
structured text fields, not embedded HTML documents, and all other
adapters parse raw HTML pages or a JSON API of text fields.

Iowa (official HTML, per-section pages, year-versioned) fits the model
cleanly but is architecturally a Washington-style HTML source — it tests
nothing new. South Carolina (official static HTML, sections embedded in
chapter pages) is a Delaware/Florida-style document-embedded source —
also not new. Minnesota exposes **no title level** (chapter → section
only) and no XML endpoint, breaking the three-level model. California,
Maryland, and Georgia were excluded for discovery/reachability flaws.
Ohio, New York, Michigan, Pennsylvania, Utah, and West Virginia are
UNREACHABLE from this environment.

## Evaluation Criteria

Candidates were evaluated against the ten criteria used for State #6:

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
| South Dakota | `sdlegislature.gov` | HTTP 200. VERIFIED reachable. |
| Iowa | `legis.iowa.gov` | HTTP 200. VERIFIED reachable. |
| South Carolina | `scstatehouse.gov` | HTTP 200. VERIFIED reachable. |
| Minnesota | `revisor.mn.gov` | HTTP 200. VERIFIED reachable. |
| California | `leginfo.legislature.ca.gov` | HTTP 200 (codes pages); some routes 403. VERIFIED reachable. |
| Maryland | `mgaleg.maryland.gov` | HTTP 200 shell; statute browser is an opaque SPA with no server-rendered statute data. VERIFIED reachable, UNVERIFIED usable. |
| Georgia | `legis.ga.gov` | HTTP 200 SPA; statute API returns HTTP 401 (auth required). VERIFIED reachable, VERIFIED unusable. |
| West Virginia | `wvlegislature.gov` | HTTP 301 → redirects to an unrelated external host; code path blocked. VERIFIED unusable. |
| Oklahoma | `oklegislature.gov` | HTTP 200 but statutes path 404s / has no addressable chapter index (unchanged from State #5/#6). VERIFIED. |
| Ohio | `codes.ohio.gov` | Connection timeout. VERIFIED unreachable. |
| New York | `nysenate.gov` / `legislation.nysenate.gov/api/3/` | HTTP 403 / timeout. VERIFIED unreachable. |
| Utah | `le.utah.gov` | Connection timeout. VERIFIED unreachable. |
| Michigan | `legislature.mi.gov` | HTTP 403 on every route tested. VERIFIED unreachable. |
| Pennsylvania | `legis.state.pa.us` | Connection timeout. VERIFIED unreachable. |

ARCHITECTURAL CONCLUSION: the "big-name" candidates (OH/NY/UT/MI/PA) and
WV cannot be exercised from this environment, so any adapter built for
them would rest on UNVERIFIED source behavior. The reachable and usable
set narrows the research to South Dakota, Iowa, South Carolina,
Minnesota, and California.

## Candidate: South Dakota

**Official source:** `https://sdlegislature.gov/Statutes` — official
South Dakota Legislature site. The public pages are a Vue SPA, but the
site's own data API is plain server-rendered JSON under
`https://sdlegislature.gov/api/Statutes/`. VERIFIED reachable, no auth,
no cookies, works with a plain browser User-Agent.

**Retrieval model:** **JSON API, flat records, embedded HTML.**
One section is retrieved with `GET /api/Statutes/Statute/{id}` where
`{id}` is the full citation number, e.g.
`GET /api/Statutes/Statute/22-3-1`. VERIFIED — HTTP 200 with a JSON
record whose `Html` field contains the section's full rendered text:

> `22-3-1. Persons capable of committing crimes--Exceptions. Any person
> is capable of committing a crime, except those included in the
> following classes: (1) Any child under the age of ten years; ...`

The record carries `parents` (e.g. `Title:22`, `Chapter:3`,
`Section:1`), `Next`/`Previous` navigation pointers (e.g. `22-3-1.1` /
`22-3`), `Type` ("Section"), `CatchLine`, `Repealed`, and the
`LastStatuesEffectiveDate` global. VERIFIED.

**Discovery model:** Three separate JSON calls, all VERIFIED:
- Titles: `GET /api/Statutes/Title` → JSON array of title records (71
  titles, including lettered titles like `23A`, `27A`), each with
  `Statute` id and `CatchLine` name.
- Chapters of a title: `GET /api/Statutes/Statute/{title}` (e.g. `/22`)
  → a record whose embedded `Html` links to every chapter
  (`Statute=22-1`, `22-4A`, ...) with the chapter name inline
  ("01 Definitions And General Provisions ...").
- Sections of a chapter: `GET /api/Statutes/Statute/{title}-{chapter}`
  (e.g. `/22-3`) → a record whose embedded `Html` links to every section
  (`Statute=22-3-1`, `22-3-1.1`, ...) with the catchline inline.

**Hierarchy:** Title → Chapter → Section, exactly three levels.
Citations are `SDCL § 22-3-1` (Title 22, Chapter 3, Section 1) — the
section number carries both title and chapter. VERIFIED (citation form
confirmed in SD Supreme Court and legislative documents).

**History/version:** Each section's embedded HTML ends with a `Source:`
amendment chain (e.g. `Source: SDC 1939, § 13.0201; SL 1968, ch 28,
§§ 1, 2; ...`) — preservable verbatim as `amendment_notes`. VERIFIED.
The API exposes a global `LastStatuesEffectiveDate`
(`"2026-07-29T00:00:00-05:00"`). VERIFIED. The site serves the current
Codified Laws; no per-year edition URLs were observed (a current-code
source, like Virginia/Delaware — not a versioned-edition source like
Florida). UNVERIFIED whether historical editions are available.

**Status signal:** Each record has a `Repealed` boolean, but it is
`False` even on sections whose text reads "Repealed by SL 2005, ch 120,
§ 358, eff. July 1, 2006." VERIFIED — so repeal is prose-only and
`status` stays `UNKNOWN` under the framework's no-prose-inference rule.

**Error behavior:** A nonexistent chapter (`/Statute/22-99`) and a
nonexistent section (`/Statute/99-99-99`) both return HTTP 404. VERIFIED.
The API is the error boundary — clean, consistent mapping to
`RefNotFoundError`.

**Framework fit:** Good. Three levels, one per ref model:
- `TitleRef.identifier` = title number (e.g. `"22"`, `"23A"`).
- `ChapterRef.identifier` = chapter number (e.g. `"3"`, `"4A"`).
- `SectionRef.identifier` = full section number (e.g. `"22-3-1"`).

**New pattern:** **Official JSON API with flat records, embedded HTML,
and linked-list navigation.** This is the framework's first adapter
where (a) the source is a genuine REST API (not scraped HTML), (b) the
content payload is an HTML document embedded inside the JSON record
(rather than structured text fields like Virginia), and (c) hierarchy is
expressed through a `parents` array plus `Next`/`Previous` pointers
rather than nested listings. It also demonstrates the framework serving
a JavaScript-rendered source through the source's own official API.

**Main risk:** The chapter/section listings must be parsed from the
embedded `Html` of a parent record (link-text extraction), not from a
dedicated list endpoint. This is a hybrid JSON + HTML parsing path
(parse JSON envelope, then strip-tags the embedded HTML). VERIFIED that
the link structure is regular (`Statute=NN-NN` / `Statute=NN-NN-NN`).

**Recommendation:** **Yes.**

## Candidate: Iowa

**Official source:** `https://www.legis.iowa.gov/law/iowaCode` — official
Iowa Legislature. VERIFIED reachable.

**Retrieval model:** Per-section HTML pages, year-parameterized
(`/law/iowaCode/sections?codeChapter=321&year=2026`). Each chapter page
lists its sections. VERIFIED that title → chapter → section navigation
is fully server-rendered HTML with `year=` on every URL.

**Hierarchy:** Title (Roman numeral I–XVI) → Chapter → Section.
Citations are `Iowa Code § 321.1` (chapter.section). VERIFIED.

**Framework fit:** Good — three levels, one per ref model.

**New pattern:** None materially. This is a server-rendered HTML,
section-listing source — architecturally a Washington-style HTML
adapter (though year-parameterized). Iowa's per-page year parameter is
interesting but Florida already established the versioned-source axis.

**Main risk:** Low. The year must be pinned (like Florida) and the HTML
table structure re-verified.

**Recommendation:** Alternative (fits cleanly but tests nothing new).

## Candidate: South Carolina

**Official source:** `https://www.scstatehouse.gov/code/` — official SC
Code of Laws. VERIFIED reachable.

**Retrieval model:** Static HTML. Title index
(`/code/title16.php`), chapter pages (`/code/t16c003.php`), sections
embedded inline in chapter pages (e.g. `SECTION 16-3-20. Punishment for
murder; ...`). VERIFIED.

**Hierarchy:** Title → Chapter → Section. Citations are
`S.C. Code § 16-3-20`. VERIFIED.

**Framework fit:** Good — three levels, one per ref model.

**New pattern:** None — this is the Delaware/Florida
document-embedded-anchor model (sections embedded in a chapter
document) in static HTML.

**Main risk:** Low.

**Recommendation:** Alternative (fits cleanly but tests nothing new).

## Candidate: Minnesota

**Official source:** `https://www.revisor.mn.gov/statutes/` — official
Minnesota Revisor of Statutes. VERIFIED reachable.

**Hierarchy:** Chapter → Section only. Citations are
`Minn. Stat. § 13.01` (chapter.section). VERIFIED — **no title level**.
The site's topical "parts" are navigation groupings, not structural
levels in the citation.

**Framework fit:** ARCHITECTURAL CONCLUSION — `TitleRef` is required in
every ref and the Minnesota Statutes expose no title level. Mapping
would require either a synthetic title level or a framework change, both
of which violate the "no framework changes" constraint.

**New pattern:** N/A — broken by the hierarchy mismatch. (No XML
endpoint was found either: XML-suffixed URLs return HTML. VERIFIED.)

**Recommendation:** No — hierarchy mismatch.

## Candidate: California

**Official source:** `https://leginfo.legislature.ca.gov/` — official CA
Legislative Information. VERIFIED reachable.

**Retrieval model:** Per-section server-rendered HTML addressed by
`(lawCode, sectionNum)` query parameters — unchanged from the State #6
review (VERIFIED in prior research; a code TOC fetch returned HTTP 200
here).

**Discovery model:** Unchanged from State #6 — the chapter text/listing
page is JS-rendered; there is no server-rendered chapter→section
listing. This is the same flaw that excluded California from State #6
and Kansas from State #5.

**Framework fit:** ARCHITECTURAL CONCLUSION — `list_sections` cannot be
satisfied server-side.

**Recommendation:** No — unchanged from State #6.

## Comparison Table

| State | Official source | Retrieval model | Discovery model | Hierarchy fit | New pattern | Risks | Recommendation |
|-------|-----------------|-----------------|-----------------|---------------|-------------|-------|----------------|
| **South Dakota** | **sdlegislature.gov/api/Statutes/** | **Official JSON API; flat records with embedded HTML; linked-list Next/Previous** | **JSON API: titles endpoint, chapters/sections parsed from parent record Html** | **Perfect 3-level fit (Title 22 → Ch 3 → § 22-3-1)** | **Official JSON API + embedded-HTML payloads (first of its kind)** | Hybrid JSON+HTML parsing; listings live inside embedded Html | **Yes** |
| Iowa | legis.iowa.gov | Per-section HTML, year-parameterized | Server-rendered HTML title/chapter/section pages | Perfect 3-level fit | None (Washington-style HTML) | Year pinning; table structure re-verify | Alternative |
| South Carolina | scstatehouse.gov/code/ | Static HTML; sections embedded in chapter pages | Static HTML title/chapter pages | Perfect 3-level fit | None (Delaware/Florida-style) | Low | Alternative |
| Minnesota | revisor.mn.gov | Per-section HTML | Chapter/section pages; no title level | **No title level — mismatch** | N/A | Framework change required | No |
| California | leginfo.legislature.ca.gov | Per-section HTML `(lawCode, sectionNum)` | JS-rendered chapter listing | Fits 3 levels; chapter absent from citation | None new beyond prior review | `list_sections` not server-enumerable | No |

## Final Recommendation

**South Dakota is State #7.**

It is the only reachable candidate that (a) is an official, stable,
auth-free source, (b) introduces a genuinely new architectural axis —
the **official JSON API whose records carry embedded HTML content and
linked-list navigation** — rather than another adapter of an existing
kind, and (c) fits the existing `TitleRef → ChapterRef → SectionRef`
contract with no redesign.

The State #7 question this research answers is: can the framework serve
a source that is a JavaScript-rendered public site but that exposes a
real server-side JSON API — and whose content payload is an HTML
document embedded inside each JSON record? The evidence says yes. Every
framework method maps onto the API: `list_titles` → the `/Title`
endpoint; `list_chapters`/`list_sections` → parse the parent record's
embedded `Html` for `Statute=` links; `retrieve_section` → fetch the
flat record by citation number and strip the embedded HTML; `build_url`
→ construct the `/api/Statutes/Statute/{id}` URL; `normalize` →
cross-check `ref.identifier` against the `SDCL § {id}` citation. Error
behavior is a clean 404 boundary. No framework, registry, model, or MCP
change is required.

Iowa and South Carolina fit the model but replicate existing
architectures. Minnesota breaks the three-level model. California,
Maryland, and Georgia fail discovery or access requirements. The
remaining "big-name" candidates are unreachable from this environment.