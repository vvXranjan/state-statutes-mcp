### 1. Official source
`statutes.capitol.texas.gov` — hosted by the Texas Legislative Council (the same body that runs `capitol.texas.gov` for bill text). This is the authoritative, government-published source; there is no separate Texas "statutes API." The Secretary of State separately maintains the Texas Administrative Code, which is out of scope for a statutes adapter.

### 2. URL structure
Confirmed via the site's own `LinksFAQ.aspx` page, three stable, documented patterns:
- **Code table of contents:** `https://statutes.capitol.texas.gov/?link={CODE}` (e.g. `?link=LA` for the Labor Code)
- **Chapter document:** `https://statutes.capitol.texas.gov/Docs/{CODE}/{TYPE}/{CODE}.{CHAPTER}.{ext}` where `TYPE`/`ext` is `htm`, `pdf`, or `doc` (e.g. `/Docs/LA/htm/LA.61.htm`)
- **Section-within-chapter anchor:** same chapter URL with a `#{chapter}.{section}` fragment (e.g. `/Docs/LA/htm/LA.61.htm#61.001`) — note this is a same-document anchor, not a separate retrievable resource
- **Single-section ad hoc lookup:** `GetStatute.aspx?Code={CODE}&Value={SECTION}&Date={date}` — used in bill-text cross-references; also supports `DocumentType=Word`
- **Full code list:** `StatuteCodes.aspx` gives the canonical two-letter code ↔ full code name mapping (30 codes + Vernon's Civil Statutes)

There is **no chapter-listing JSON/XML endpoint** — the in-page TOC tree at `?link=CODE` is populated client-side by JavaScript and the raw HTML doesn't contain the chapter list.

### 3. Citation structure
Texas statutes cite as `{Code Name} § {chapter}.{section}` (e.g. "Labor Code § 61.001"; Bluebook form: "Tex. Lab. Code Ann. § 61.001"). The two-letter site code (`LA`, `GV`, `TX`, etc.) is Texas's own internal identifier, distinct from the citation abbreviation used in legal writing — the adapter needs a mapping between the two if it wants to emit Bluebook-style citations, but the internal `CODE.CHAPTER.SECTION` triple is sufficient for addressing.

### 4. Title hierarchy
Above chapter, most codes use **Title → (optional Subtitle) → Chapter**. Titles are not separately retrievable documents — they only appear as headers inside chapter HTML pages (confirmed in the Labor Code Ch. 61 fetch: "TITLE 2. PROTECTION OF LABORERS" / "SUBTITLE C. WAGES" precede "CHAPTER 61"). There's no per-title URL or page.

### 5. Chapter hierarchy
Chapter is the actual retrievable unit — one HTML/PDF/Word document per chapter, addressed by `{CODE}.{CHAPTER}`. Chapters may contain **Subchapters** (e.g. "SUBCHAPTER A. GENERAL PROVISIONS") as sub-headers within the same document; subchapters are not separately addressable.

### 6. Section hierarchy
Sections (`Sec. 61.001`, `Sec. 61.0031`, etc.) live inside the chapter document as sequential blocks: a caption, body text (often with lettered/numbered subsections), and trailing amendment history ("Acts 1993... Amended by..."). No separate URL per section — only the in-page anchor.

### 7. Search support
`search.aspx` supports full-text phrase/word search against statute and constitution text, returning matching chapters grouped by code — this is a **chapter-granularity** search UI (HTML form + results page), not a documented public API, and results still resolve to the same chapter HTML documents.

### 8. HTML or API
Pure HTML. No REST/JSON/XML API exists for statute content.

### 9. JavaScript required?
**Depends on the operation:**
- Chapter/section content pages (`/Docs/{CODE}/htm/{CODE}.{CHAPTER}.htm`) are **fully static server-rendered HTML** — confirmed by directly fetching `LA.61.htm` and getting complete section text with no JS execution.
- The code TOC page (`?link={CODE}`) **is JS-driven** — a plain fetch returns only the search widget shell, not the expandable chapter tree; the chapter list is built client-side (likely from an embedded/loaded XML or JS data structure not exposed as a separate flat endpoint).

### 10. Can simple HTTP retrieve statutes?
Yes for chapter/section **content** (a GET request is sufficient). No for chapter/title **discovery** via the official TOC UI — that needs either a headless browser or reverse-engineering whatever the tree widget loads client-side.

One operational note: the TLC's file-downloads page explicitly asks "legislative data services companies stop data mining the capitol.texas.gov site" and threatens to block persistent scrapers, offering an FTP alternative — but that FTP mirror is documented only for **bill text**, not statute text. There's no statutes-specific bulk-download channel, so a TexasAdapter should be conservative about request volume/rate against `statutes.capitol.texas.gov` even though it isn't strictly forbidden.

---

## TexasAdapter implementation plan

**Constructor/collaborators (per current milestone scope):** none required by the base contract yet; internally the adapter will need an HTML parser capable of walking the chapter document's heading levels (Title/Subtitle/Chapter/Subchapter/Section), but that's an implementation detail behind `list_*`/`normalize`, not part of this plan's four methods' *contracts*.

### `build_url(ref)`
- Dispatch on the concrete type of `ref`:
  - **`TitleRef`**: Texas has no addressable title-level page. Per `BaseStateAdapter`'s documented contract, this case must raise `UnsupportedRefError` rather than return a URL.
  - **`ChapterRef`**: build `https://statutes.capitol.texas.gov/Docs/{code}/htm/{code}.{chapter_identifier}.htm`, where `code` comes from `ref.state_code`-independent internal Texas code letters (this needs a small static lookup table from `TitleRef.identifier`/adapter config to the two-letter site code, e.g. Labor → `LA`, since Texas's own code letters aren't the state's USPS code and aren't derivable from `state_code`).
  - **`SectionRef`**: build the *parent chapter's* URL exactly as above, then append `#{chapter_identifier}.{section_identifier}` as a fragment — since sections have no standalone document, `build_url` for a `SectionRef` necessarily returns a same-document anchor into its chapter's HTML, not a unique resource.
- No HTTP call happens inside `build_url` itself — it's pure string construction from the ref, consistent with the base contract.

### `list_titles()`
- Texas titles aren't separately published, so this can't be driven by a title-listing page the way `list_chapters`/`list_sections` are driven by chapter/section listings.
- Plan: maintain a **static, versioned reference table** (shipped with the adapter, not fetched at runtime) mapping each of the ~30 codes' internal two-letter site code (from `StatuteCodes.aspx`, which *is* fetchable and stable) to a `TocNode(level=TITLE, ...)`. Since "Title" in Texas's own numbering is a sub-level *within* a code rather than the code itself, this adapter should treat **each Code** (Labor Code, Government Code, etc.) as the `TITLE`-level `TocNode` for this adapter's purposes — the top of what's independently addressable — and surface the code's true internal "Title N" divisions as informational grouping inside `list_chapters`/chapter headings rather than as a separate discovery hop, since they carry no unique URL of their own.
- Each returned `TocNode.ref` is a `TitleRef(identifier=<two-letter code>, ...)`, sourced from the `StatuteCodes.aspx` table.
- Since this list is effectively static (new codes are created rarely, only by legislative action), the adapter can hardcode it and treat `AdapterUnavailableError` as unreachable in normal operation, or optionally re-validate it against `StatuteCodes.aspx` on a slow cadence.

### `list_chapters(title_ref)`
- Given the code-level `TitleRef` from above, this method needs the set of chapter numbers that exist under that code.
- Two viable strategies, in preference order:
  1. **Reverse-engineer the TOC widget's data source** on `?link={code}`: inspect what asset the JS tree actually loads (likely a small embedded JSON/XML chapter index) and fetch that directly — if it exists as a separate resource, this avoids a headless browser entirely and keeps discovery cheap.
  2. **Fallback (if no separate JS data source exists):** render `?link={code}` with a headless browser to let the tree populate, then scrape the rendered chapter list. This is heavier and should be the last resort given the site's stated concern about scraping load.
- Each resulting chapter becomes a `TocNode(level=CHAPTER, identifier=<chapter number>, ref=ChapterRef(title=title_ref, identifier=<chapter number>))`.
- Chapter numbering gaps (repealed chapters, e.g. "CHAPTER 5. [Repealed]") should still be listed as `TocNode`s if the source lists them — completeness of enumeration matters more than filtering, per `list_chapters`' documented contract; status filtering is `normalize`'s concern, not discovery's.

### `list_sections(chapter_ref)`
- Given a `ChapterRef`, this fetches the single chapter HTML document (`build_url(chapter_ref)`, stripped of any fragment) and parses out each `Sec. {chapter}.{section}` heading in document order.
- Because the whole chapter is one HTML page, this method's real work is **client-side parsing, not additional HTTP calls**: one GET for the chapter document yields every section for that chapter in a single request, which is efficient relative to states with a per-section endpoint.
- For each heading found, emit `TocNode(level=SECTION, identifier=<section id, e.g. "61.001">, ref=SectionRef(chapter=chapter_ref, identifier=<section id>))`.
- Subchapter headers ("SUBCHAPTER A...") encountered while walking the document are not separately addressable and should not produce their own `TocNode`s at this milestone — they're structural context that can inform a `name`/grouping label on the section nodes rather than a fourth hierarchy level, since the base contract only defines three enumerable levels.
- Partial-parse failures (e.g. an unexpected markup change mid-document) should surface as `PartialListingError` per the base contract, carrying whatever sections were successfully parsed before the failure, rather than silently truncating the list.