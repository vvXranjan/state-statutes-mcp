## Research: Official Washington State Statute Source
### 1. Official source
`app.leg.wa.gov/RCW` (the historical `apps.leg.wa.gov/RCW` alias still resolves) — hosted by the Washington State Legislature, maintained by the Office of the Code Reviser and Statute Law Committee. This is the Revised Code of Washington (RCW), the authoritative compilation of permanent state law. Note the RCW is only refreshed **once a year** (by ~October 1, after that year's session), unlike Texas which updates continuously as sessions close — a data-freshness/versioning difference worth flagging for a caching layer.

### 2. URL structure
One consistent endpoint, `default.aspx`, parameterized by `cite`, confirmed by directly fetching all three levels:
- **Title:** `default.aspx?cite={title}` (e.g. `?cite=49`) — a static HTML page titled "Title 49 RCW" with a `### Chapters` table listing every chapter number, name, and link.
- **Chapter:** `default.aspx?cite={title}.{chapter}` (e.g. `?cite=49.60`), optionally with `&full=true` to render every section's full text concatenated on one page (confirmed via the Consumer Health Data Act chapter, `?cite=19.373&full=true`).
- **Section:** `default.aspx?cite={title}.{chapter}.{section}` (e.g. `?cite=49.60.010`) — its **own standalone page**, not an anchor into a larger document, with breadcrumbs (`Title 49 / Chapter 49.60 / Section 49.60.010`), prev/next section navigation, and a `&pdf=true` variant.

This is a **fundamentally different shape** from Texas: Washington gives one URL per hierarchy level (title, chapter, *and* section), while Texas only gives one URL per chapter and fakes section-level addressing with an in-page anchor.

### 3. Citation structure
`RCW {title}.{chapter}.{section}` (e.g. "RCW 49.60.010"); a bare chapter cites as "Chapter 49.60 RCW"; a bare title as "Title 49 RCW". This is a strict, three-segment dotted numbering scheme baked directly into the URL parameter — citation and locator are effectively the same string, unlike Texas where the two-letter site code (`LA`) is a separate identifier from the Bluebook abbreviation ("Lab. Code").

### 4. Hierarchy
Washington's own help documentation states it plainly: **"There are 3 main parts to state laws: titles, chapters, and sections."** No subtitle or subchapter layer exists as a distinct concept — each of the three levels is independently addressable, discoverable, and URL-resolvable. This is simpler and flatter than Texas's Title → (optional Subtitle) → Chapter → (optional Subchapter) → Section, where only Chapter and (fictively) Section are addressable.

### 5. Search support
Primarily **citation-based lookup** ("search laws by full or partial citation number, e.g. 4.04.010") rather than Texas-style full-text phrase search baked into the statutes site itself. Washington is also mid-migration to a new sitewide "LegSearch" tool (`leg.wa.gov/search`) replacing the older `search.leg.wa.gov`; neither is confirmed to expose full-text statute search as a stable documented endpoint the way Texas's `search.aspx` does.

### 6. HTML or API
Pure HTML, same as Texas — no JSON/XML/REST API for statute content.

### 7. JavaScript requirements
**None, at any level.** Direct `web_fetch` of the title page, and previously the chapter (`&full=true`) and section pages, returned fully populated, server-rendered HTML with no client-side rendering step — including the chapter *listing* table on the title page. This is the single biggest structural divergence from Texas, whose chapter-listing TOC (`?link=CODE`) is JS-driven and unscrapable via plain HTTP.

### 8. Can simple HTTP retrieve statutes?
**Yes — completely**, for discovery *and* content, at all three levels (title, chapter, section). A plain GET is sufficient for the entire adapter surface: `list_titles`-equivalent data isn't even needed as a separate call structure the way Texas needs it, since Washington's title pages already double as both identity and chapter-discovery documents.

---

## Washington vs. Texas: Feature Comparison

| Feature | Same / Different | Detail | Shareable by one adapter framework? |
|---|---|---|---|
| **Official source is a single authoritative .gov-adjacent legislature site** | Same | Both are hosted by the respective legislature's own infrastructure (`statutes.capitol.texas.gov` vs `app.leg.wa.gov`), not a third party | Yes — the *concept* of "one authoritative site, no federal equivalent" is shared; only the base URL differs (adapter config) |
| **URL parameterization style** | Different | TX: path-based (`/Docs/{CODE}/htm/{CODE}.{CH}.htm`); WA: query-param based (`default.aspx?cite=...`) | Yes, if `build_url` is treated as fully opaque per-adapter string construction — which the current `BaseStateAdapter` contract already assumes |
| **One URL per chapter vs. one URL per section** | Different | TX: chapter is the atomic retrievable unit; sections are anchors within it. WA: section is independently retrievable, no anchor needed | Partially — `list_sections`/`normalize` can share a common *shape*, but TX's `normalize` must parse a chapter document and locate a section by heading, while WA's can fetch the section URL directly. The base contract's per-ref `build_url` already accommodates this without a shared implementation, just shared *interface* |
| **Citation format tightly coupled to URL identifier** | Different | WA's `cite` param *is* the citation (`49.60.010`); TX's two-letter code (`LA`) is a separate internal ID from the Bluebook abbreviation ("Lab. Code") | No — this forces each adapter to own its own citation-formatting logic; a shared `Citation` model can hold the result, but not the mapping logic |
| **Hierarchy depth** | Different | WA: strict 3-level (Title/Chapter/Section), officially documented as exactly three. TX: nominally 5-level (Title/Subtitle/Chapter/Subchapter/Section) but only 2 levels (Chapter/Section) are separately addressable | Yes — the base contract's fixed three-level `TITLE`/`CHAPTER`/`SECTION` enum already matches WA exactly and treats TX's Subtitle/Subchapter as non-addressable structural metadata rather than a fourth/fifth hop, so no framework change needed |
| **Title-level page exists as an independent, addressable resource** | Different | WA: yes — `cite=49` is a real page with its own chapter-listing table. TX: no — Title only appears as an in-page header inside a chapter document | No — TX's `list_titles` needs a static/hardcoded per-code table (since there's no real title endpoint to enumerate against), while WA's `list_titles` fetches and parses a real page. The abstract *method signature* is shared; the implementation strategy is not |
| **Chapter-listing discovery mechanism** | Different | WA: static server-rendered HTML table on the title page. TX: JS-rendered tree with no discoverable static equivalent found | No — this is the sharpest technical divergence. TX's `list_chapters` may require a headless browser or reverse-engineered JS data source; WA's is a single static GET + HTML table parse. A shared framework can define the *interface* (`list_chapters(title_ref) -> Sequence[TocNode]`) but cannot share the *fetch strategy* — TX needs a heavier-weight fetcher collaborator than WA |
| **Section-level content retrieval** | Different | WA: dedicated section URL, trivial single-section fetch. TX: must fetch the whole chapter and locate the section by heading text | No — `normalize`'s internal implementation differs meaningfully (a lookup vs. a whole-document parse-and-search), though again the abstract signature (`normalize(parsed, ref) -> StatuteSection`) is identical |
| **HTML-only, no JSON/API** | Same | Neither state exposes a statute API | Yes — both adapters are HTML-scraping adapters at the framework level; no adapter needs an API-client collaborator |
| **JavaScript required for any part of the pipeline** | Different | WA: none, anywhere. TX: required for chapter-discovery (title-level scoped) | No — this determines whether an adapter needs a heavyweight (headless-browser-capable) fetcher or a lightweight HTTP-only one. If the framework's fetcher collaborator is pluggable per adapter (per the "fetcher/parser collaborators" noted as a later milestone in `BaseStateAdapter`), this is absorbed at the collaborator-selection level, not the adapter-interface level |
| **Full-text search availability** | Different (uncertain) | TX has a documented `search.aspx` phrase-search endpoint. WA's is citation-lookup-first, with a sitewide search tool of unclear full-text statute coverage | N/A — the current milestone's `BaseStateAdapter` has no `search` method (explicitly deferred as an `AdapterCapabilities`-gated optional method), so this doesn't affect Phase 0/1 framework design at all |
| **Publication cadence / freshness model** | Different | TX updates on a rolling basis as each session's changes are codified. WA republishes the whole RCW once a year (~Oct 1), plus a post-election refresh if a ballot measure changed law | No direct adapter-interface impact today (no versioning/point-in-time concept exists yet in the base contract), but worth flagging as a future consideration if a `StatusInferenceStrategy` or point-in-time retrieval milestone is added later — the two states' "as of" semantics aren't equivalent |

### Net assessment for the shared framework
The **`BaseStateAdapter` abstract contract holds up well for both states without modification** — five methods, three-level hierarchy, ref-driven `build_url`, all map cleanly onto both TX and WA. What differs is entirely inside each concrete adapter's *implementation*, not the interface:
- **WA is the easier adapter**: every method is a plain HTTP GET + static HTML parse, including discovery at all three levels.
- **TX is harder specifically at `list_chapters`**: it's the one place where a shared "simple HTTP fetch + parse" strategy breaks down and TX will need either a heavier fetcher (headless browser) or a separate reverse-engineered data source, while every other method (including its own `list_sections`/`normalize`, which parse a fetched chapter document) stays within the same lightweight HTTP-only strategy WA uses throughout.

This confirms the original architectural decision to extend the CFR-style shared interface with **one adapter per state** rather than one generic client was the right call — the interface generalizes cleanly, but the fetch/discovery strategy underneath it does not.