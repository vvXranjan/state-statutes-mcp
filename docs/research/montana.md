# Montana Research — B10

**Research performed:** August 16, 2026, live against the official host from this
environment. The first pass used `web_fetch`/`web_search`; the previously-blocking
items (HTTP 404 behavior, encoding) were later confirmed with real `curl` from this
environment's bash shell (direct egress to `mca.legmt.gov` works), so the entire
error contract is now live-verified.

**Scope note:** Montana had **zero prior references** anywhere in the
repository. It does not appear in `docs/research/state_family_matrix.md`'s
"Implemented" table, its "Remaining 33 States" groups, or anywhere else —
of the 50 states, Montana is the one state the matrix simply never
accounted for (17 implemented + 32 catalogued in the 6 groups = 49). This
report is the first research pass on Montana for this project.

---

## 1. Official source

- **Official host:** `https://mca.legmt.gov` (current Montana Code
  Annotated, "2025" edition banner). `VERIFIED` — live `web_fetch`.
- A parallel/legacy host, `https://archive.legmt.gov`, serves prior-year
  MCA snapshots (e.g. `archive.legmt.gov/bills/2015/mca/...`) and general
  legislative content (session laws, search). `mca.legmt.gov` is the
  current, canonical statute host and is what this report targets.
  `VERIFIED`.
- Do not confuse with `leg.mt.gov` / `legmt.gov` root domains, which
  redirect to or link into these hosts but were not used directly.

## 2. Accessibility

**Live, directly reachable, no bot-block observed** across ~15 fetches in
this session (index, chapter, part, and section pages across 4 different
titles). `VERIFIED` for GET requests via this environment's fetch tool.

- **404 / missing-document behavior:** `VERIFIED` (live `curl`, Aug 16
  2026). Deliberately nonexistent URLs built with the verified arithmetic
  (§5) all returned **plain HTTP 404 with zero redirects** — no soft-404
  HTTP 200, no 301/302 redirect. Cases probed on `mca.legmt.gov`:
  nonexistent section `1-11-199` (valid title 1 / ch 11 / part 1, URL
  `.../title_0010/chapter_0110/part_0010/section_0990/0010-0110-0010-0990.html`)
  → HTTP 404, `Content-Type: text/html`, 49,280-byte error page whose
  `<title>` is exactly `404`; nonexistent chapter `1-99`
  (`.../title_0010/chapter_0990/parts_index.html`) → HTTP 404;
  nonexistent part `11-99`
  (`.../title_0010/chapter_0110/part_0990/sections_index.html`) → HTTP 404;
  nonexistent title `91` (`.../title_0910/chapters_index.html`) → HTTP 404.
  This confirms the project's 404 → `RefNotFoundError` mapping is
  live-observable on Montana, and that `build_url` + fetch alone reaches
  `RefNotFoundError` for missing sections (no `list_sections` validation
  pre-check needed).
- **Network failure / timeout behavior:** `UNVERIFIED` — no connection
  failures were induced this session (the live host is reachable), so the
  project convention (non-404 non-2xx / connection error →
  `AdapterUnavailableError`) remains unobserved on Montana specifically.
- **Bot protection / auth:** No CAPTCHA, JS challenge, or auth wall
  encountered on any of the ~15 fetches. `VERIFIED` (as far as exercised);
  whether higher request volume would trigger a rate limit is
  `UNVERIFIED`.

## 3. Retrieval family

**Family A — one static HTML document per section**, server-rendered,
no JavaScript dependency. `VERIFIED`.

Every section observed (`1-11-103`, `1-11-101`, `1-13-101` repealed,
`1-13-106` reserved-range, `2-6-1001`, `2-6-1030`) rendered as a complete,
self-contained server-rendered HTML page at a stable, GET-able URL with no
client-side rendering step. This is the same family as Washington,
Minnesota, Arizona, Maine, Maryland, Idaho, Nebraska, etc.

Montana does **not** belong to a new family. It is Family A, but with a
distinguishing wrinkle not seen in the other Family-A states studied so
far: the per-section URL is **not a direct restatement of the citation
string** (contrast Washington's `?cite=49.60.010`, Nebraska's
`?statute=77-1801`). Instead the URL encodes a **derived positional code**
for each of title/chapter/part/section, per §5 below. This is still
Family A (the retrieval mechanism is "fetch one static HTML doc"), but
`build_url` is arithmetic rather than a literal citation substitution —
worth calling out explicitly since "family" alone doesn't fully describe
the URL-construction risk.

## 4. Hierarchy

**Legal/citation hierarchy is Title → Chapter → Part → Section, but the
*published citation* only ever shows three hyphenated numbers**
(`{title}-{chapter}-{section}`, e.g. `45-5-511`). This is confirmed by
Montana's own numbering-system documentation:

> "The code uses a three-element numbering system. The number to the far
> left designates the title number, the number between the hyphens
> designates the chapter number, and the number to the right designates
> the **part and section number**. Thus 1-2-305 indicates Title 1,
> chapter 2, part 3, section 5." (`mca.legmt.gov/bills/mca/help.html`,
> `VERIFIED`)

In other words: **Part is not a separate citation segment** — it's folded
into the third number. For a section number *N*, `part = N // 100` and
`section-within-part = N % 100` (verified arithmetically against every
sample below). This is functionally different from Massachusetts's
4-level hierarchy (Part → Title → Chapter → Section) noted in the family
matrix, where Part is a *real, separately-cited* level requiring
flattening. Montana's Part is a **pure URL-routing artifact with no
citation presence at all**.

**Framework fit: `TitleRef → ChapterRef → SectionRef` holds without any
flattening or synthetic title.**

- `TitleRef.identifier` = the title number as a string (`"45"`).
- `ChapterRef.identifier` = the chapter number as a string (`"5"`).
- `SectionRef.identifier` = the full three-number citation
  (`"45-5-511"`), exactly as Montana itself cites it. Part is never
  exposed as a ref field; it's derived internally by `build_url` from the
  section number's arithmetic, the same way an adapter derives a URL path
  segment from any other internal encoding.

No framework change, no synthetic title (Montana has a real title level,
unlike Nebraska/Minnesota/Wisconsin), no 4-level ref needed.

**One exclusion, matching prior-adapter precedent of excluding
constitutions:** Title `0000` in the TOC is *"THE CONSTITUTION OF THE
STATE OF MONTANA"*, and its URL scheme uses `article_XXXX` segments in
place of `chapter_XXXX` (`VERIFIED`:
`mca.legmt.gov/bills/mca/title_0000/article_0110/parts_index.html`).
This breaks the chapter-segment convention used by all 90 numbered
statute titles. Recommend explicitly **excluding Title 0 / the
Constitution from `MontanaAdapter`'s scope** (`list_titles` should start
at Title 1), the same way other adapters in this project don't attempt to
serve state constitutions.

## 5. URL / API structure

No API; plain HTML paths. Every numeric path segment is the **real
number × 10, zero-padded to 4 digits**:

```
{code} = (number * 10) formatted as %04d
```

| Level | Path segment | Formula | Verified example |
|-------|-------------|---------|-------------------|
| Title | `title_{TTTT}` | title_number × 10 | Title 45 → `title_0450` |
| Chapter | `chapter_{CCCC}` | chapter_number × 10 | Chapter 5 → `chapter_0050` |
| Part | `part_{PPPP}` | part_number × 10 | Part 10 → `part_0100` |
| Section | `section_{SSSS}` | (section_number % 100) × 10 | 511 → `section_0110`; 1001 → `section_0010` |

Where `part_number = section_number // 100` and the "section-within-part"
used for the section-segment formula is `section_number % 100`.

**Full URL templates** (all `VERIFIED` against `mca.legmt.gov`):

```
Title chapters index:
  https://mca.legmt.gov/bills/mca/title_{TTTT}/chapters_index.html

Chapter parts index:
  https://mca.legmt.gov/bills/mca/title_{TTTT}/chapter_{CCCC}/parts_index.html

Part sections index:
  https://mca.legmt.gov/bills/mca/title_{TTTT}/chapter_{CCCC}/part_{PPPP}/sections_index.html

Section document:
  https://mca.legmt.gov/bills/mca/title_{TTTT}/chapter_{CCCC}/part_{PPPP}/section_{SSSS}/{TTTT}-{CCCC}-{PPPP}-{SSSS}.html
```

The section document's filename repeats all four zero-padded codes,
dash-joined, e.g. `0450-0050-0050-0110.html` for `45-5-511`.

**Arithmetic verified against 3 independent chapters/parts** (18 distinct
section rows cross-checked): Title 1 Ch 11 Part 1 (`1-11-101..103`),
Title 1 Ch 13 Part 1 (`1-13-101..111`, includes a repealed run and two
reserved-range rows), Title 45 Ch 5 Part 5 (`45-5-501..513`, includes a
renumbered pair and a reserved pair), Title 2 Ch 6 Part 10 (`2-6-1001..
1033`, includes four reserved spans and a part-number ≥ 10 case). All 18
matched the formula exactly with no exceptions. Labeled `INFERENCE` at
the *generalizes-to-all-90-titles* level (only 4 parts across 3 titles
sampled) but `VERIFIED` for every sampled row.

**Practical consequence for `build_url`:** because the arithmetic is
confirmed deterministic, `build_url(SectionRef)` can compute the target
URL directly from `title.identifier`, `chapter.identifier`, and
`section.identifier` (by parsing the section number into part/section
components) **without a network round-trip**, unlike a typical
directory-listing family where the filename must be discovered first.
This is a meaningfully better position than most recent batches (Nebraska
needed no arithmetic since its citation *is* the query string directly;
Montana needs arithmetic but is still a pure function of the ref, not a
lookup).

## 6. Discovery mechanism

Three discovery hops, all static HTML link-scraping, no pagination, no JS:

- `list_titles()` — scrape `title_0000/index.html`'s parent
  (`bills/mca/index.html`) top-level `<ul>`: each `<li>` is either a
  linked title (`<a href="title_{TTTT}/chapters_index.html">TITLE {n}.
  {NAME}</a>`) or plain text for a reserved title/title-range (`"TITLE 4.
  Reserved"`, `"TITLES 8 AND 9. Reserved"`) with **no href at all** —
  reserved titles are simply absent from the crawlable set, not an
  error. `VERIFIED`.
- `list_chapters(title_ref)` — scrape
  `title_{TTTT}/chapters_index.html`: same linked/plain-text pattern for
  reserved chapters (`"CHAPTERS 7 THROUGH 10 RESERVED"` observed as plain
  text in Title 1). `VERIFIED`.
- `list_sections(chapter_ref)` — **two-step**, since sections sit under
  Parts, not directly under Chapters: (1) fetch
  `title_{TTTT}/chapter_{CCCC}/parts_index.html` to enumerate Parts (every
  chapter sampled had at least one Part; no chapter observed skips
  straight to sections), then (2) fetch each
  `.../part_{PPPP}/sections_index.html` and flatten all parts' section
  rows into one `Sequence[TocNode]` for the chapter. This mirrors how
  other two-hop-discovery adapters in this project already handle an
  extra internal level without exposing it as a ref field. `VERIFIED`
  structurally; the *aggregation* behavior (concatenating multiple parts'
  listings into one `list_sections` result) is this adapter's own design
  choice, consistent with the framework contract (`list_sections` returns
  "every individually retrievable section under `chapter_ref`", not
  "every section in one HTML page").

## 7. Retrieval mechanism

`retrieve_section(ref)`: `build_url(ref)` → GET the section page → parse
→ `normalize()`. Single fetch, no follow-up requests needed. `VERIFIED`
for 6 sampled sections across the normal/repealed/reserved cases below.

## 8. Citation

- Standard citation form: `{title}-{chapter}-{section}`, e.g.
  `45-5-511`, exactly as rendered in the page `<h1>`-equivalent heading
  and the sections-index link text. `VERIFIED`.
- Formal abbreviation **`Mont. Code Ann. § {t}-{c}-{s}`** is the standard
  legal-citation form; `MCA § {t}-{c}-{s}` also appears in Montana's own
  materials as a shorthand. `INFERENCE` for which one the adapter should
  emit as `raw_citation` — recommend `Mont. Code Ann. § {t}-{c}-{s}` for
  consistency with the Bluebook-style abbreviations already used by other
  adapters in this project (e.g. `Neb. Rev. Stat. §`, `Wis. Stat. §`).
- No decimal or lettered section identifiers were found in any sample
  (contrast Nebraska's `77-202.12`). Montana's own numbering-system
  documentation describes only a plain three-integer scheme with no
  decimal/letter extension mechanism. `INFERENCE` (absence of evidence
  across 4 sampled parts + the official numbering-system description,
  not an exhaustive search of all 90 titles) that Montana has **no
  lettered/decimal section identifiers** as a matter of course.

## 9. Heading/catchline structure

Each section page has:

- A page `<title>`/H1-equivalent: `"{citation}. {Catchline}, MCA"`.
- A breadcrumb trail: MCA Contents → Title → Chapter → Part → section
  name (5 levels deep in the breadcrumb, even though only 3 are cited).
- A large-font restatement of the catchline as an H1 (e.g. "Effect Of
  Montana Code Annotated -- Official Version").
- Title / Chapter / Part headers repeated above the body (H4/H3/H2-style,
  decreasing size) — i.e. **every section page re-announces its full
  4-level position**, which is a convenient redundant cross-check
  (`normalize` can validate the citation's title/chapter numbers against
  these repeated headers, in addition to the numbered citation line
  itself). `VERIFIED`.

## 10. Body structure

- The operative text begins with a repeat of the numbered citation line
  (`"1-11-103. Effect of Montana Code Annotated -- official version.
  (1) ..."`), immediately followed by the body — numbered subsections
  `(1)`, `(2)`, lettered sub-subsections `(a)`, `(b)`, etc. rendered as
  plain paragraphs (not a nested list in the HTML — subsection numbers
  are inline text). `VERIFIED`.
- A trailing `History:` line (unlabeled `<p>` or similar, not a distinct
  `<div>`/`<ul>` block like Nebraska's `Source` list) gives the
  session-law amendment trail as one semicolon-joined sentence.
  `VERIFIED`.
- **No case-annotation block** was observed on the internet/current MCA
  version (Montana's own Help page confirms this: *"The annotations,
  other than histories, are not provided in the Internet version of the
  MCA."* — `VERIFIED` from `mca.legmt.gov/bills/mca/help.html`). This is
  actually a simplification relative to Nebraska, which required
  explicitly excluding an `Annotations` block from `text`; Montana's
  public pages don't carry that content at all, so no equivalent
  filtering step is needed.
- Disclaimer footer boilerplate (`"the printed version will prevail"`)
  appears on every page and must be excluded from `text`/`amendment_notes`
  the same way other adapters strip chrome.

## 11. Amendment/history structure

Single `History:` sentence per section, e.g.:

> `History: En. 12-506 by Sec. 6, Ch. 419, L. 1975; amd. Sec. 4, Ch. 1,
> L. 1977; R.C.M. 1947, 12-506; amd. Sec. 11, Ch. 119, L. 1979; ... amd.
> Sec. 12, Ch. 52, L. 2025.`

Semicolon-delimited session-law citations, terminal period. `VERIFIED`.
Recommend lifting this verbatim into `amendment_notes`, matching the
Nebraska/other adapters' "lift the History block verbatim" convention.
Repealed sections carry a much shorter `History:` line referencing only
the repealing act (see §12).

## 12. Repealed/reserved sections

Both cases were directly sampled and are structurally distinct from a
normal section — this is Montana's most important edge case:

- **Repealed** (`1-13-101`): catchline is literally the single word
  `Repealed`; body is one line — `"1-13-101. Repealed. Sec. 82, Ch. 545,
  L. 1995."` — followed by a normal `History:` line citing the
  *original* enactment. **No numbered subsections, no operative legal
  text.** `VERIFIED`.
- **Reserved, single** (`1-13-104`, listed as `"1-13-104 reserved"` in
  its part's TOC — not independently fetched this session, but the TOC
  listing convention is `VERIFIED`) and **reserved, range**
  (`1-13-106` through `1-13-110`, and multiple ranges under `2-6-10xx`):
  a single TOC row and a single fetchable section page represent the
  *entire range*. The section page's body is one line: `"1-13-106
  through 1-13-110 reserved."` — **no `History:` line at all.**
  `VERIFIED` (`1-13-106`/`0010-0130-0010-0060.html`).
- **Adapter behavior recommendation** (matching the
  Nebraska/North-Carolina precedent already in this codebase for
  repealed sections): return a `StatuteSection` with the repeal/reserved
  note as `heading`, **empty `text`**, `amendment_notes` populated only
  when a `History:` line is present (repealed) and `None` when it isn't
  (reserved). `NormalizationError` stays reserved for pages with no
  recognizable heading/citation at all, not for these two legitimate
  no-body cases.
- **Discovery implication:** a `SectionRef` built from a *range* TOC
  entry (`"1-13-106 through 1-13-110 reserved"`) should use the citation
  exactly as Montana displays it in the link text for `identifier` (i.e.
  `"1-13-106"`, the first number — matching the URL's own arithmetic,
  which keys off the first number of the range) rather than trying to
  invent per-number refs for `107`–`110`, which have no independent page.

## 13. Missing-section behavior

`VERIFIED` — exercised live (Aug 16 2026) with real `curl`. Requesting a
`SectionRef` whose number was never assigned (e.g. `1-11-199`, which
does not correspond to any TOC row) returns a **plain HTTP 404** (zero
redirects, `<title>404</title>` error page). Because `build_url` computes
the target URL deterministically from the ref (§5), `RefNotFoundError` is
reachable via `build_url` + fetch alone; no `list_sections`-based
validation pre-check is required. The same plain-404 result was observed
for nonexistent chapter, part, and title URLs (see §2).

## 14. HTTP 404 behavior

`VERIFIED` — observed live (Aug 16 2026): every deliberately nonexistent
Montana URL probed (nonexistent section under a valid part, nonexistent
chapter, nonexistent part, nonexistent title) returned HTTP 404 with zero
redirects and a real 404 error page (`<title>404</title>`, `Content-Type:
text/html`). No soft-404 (HTTP 200 with an error page) and no redirect
were observed. The adapter may therefore map 404 → `RefNotFoundError`
per the project convention with a live-verified basis.

## 15. Network failure behavior

`UNVERIFIED` — no failures observed or inducible with the tools available
this session; assume the project's standard convention (any non-2xx
response or connection failure not specifically identified as a 404 →
`AdapterUnavailableError`) pending live confirmation.

## 16. Encoding

`VERIFIED` — raw `curl` confirmed `<meta charset="utf-8">` on both a
normal section page (`1-11-103`) and the live 404 error page; the
`Content-Type` header is `text/html` (no charset parameter) but each
document itself declares UTF-8. Consistent with every other Family-A
state in this project.

## 17. Pagination

None. Every discovery/retrieval page observed is a single complete
document; no "next page" links, no result-count caps, no infinite scroll.
`VERIFIED` for the pages sampled (Title 45's chapters/parts index is a
plain 10-chapter list, nothing large enough to need paging; Title 2
Chapter 6 Part 10 lists 20 rows on one page).

## 18. JavaScript dependency

None. Every page — TOC, chapter, part, section — is fully present in the
initial server-rendered HTML with no client-side rendering step or
XHR/fetch calls needed to see content. `VERIFIED`.

## 19. Authentication / bot protection

None observed. No CAPTCHA, no Cloudflare challenge, no login wall, no
API key. `VERIFIED` for the ~15 fetches in this session; rate-limiting
behavior under heavier batch load is `UNVERIFIED`.

## 20. Version / current-edition behavior

Every page carries a **"Montana Code Annotated 2025"** banner (the
current published edition as of this research). No per-section
"effective date" chrome like Ohio's banner, and no year selector observed
on the current-edition pages — `archive.legmt.gov/bills/{year}/mca/...`
exists as a separate historical-year host, confirming `mca.legmt.gov`
serves only the current edition and doesn't itself expose a version
switcher. `VERIFIED`.

---

## Fixture plan

Recommend capturing the following **live** (no Wayback fallback needed —
the live host is directly reachable), mirroring the MN/AZ/KS/ND/MD/SC
live-fixture pattern rather than the MO/VT/WV Wayback pattern:

| Fixture | Purpose | URL |
|---|---|---|
| `montana_title_1_11_103.html` | Normal section, multi-subsection body + History | `.../title_0010/chapter_0110/part_0010/section_0030/0010-0110-0010-0030.html` |
| `montana_title_1_13_101.html` | Repealed section (no body, short History) | `.../title_0010/chapter_0130/part_0010/section_0010/0010-0130-0010-0010.html` |
| `montana_title_1_13_106.html` | Reserved-range section (no body, no History) | `.../title_0010/chapter_0130/part_0010/section_0060/0010-0130-0010-0060.html` |
| `montana_title_2_6_1001.html` | Part number ≥ 10 case | `.../title_0020/chapter_0060/part_0100/section_0010/0020-0060-0100-0010.html` |
| `montana_title_45_5_511.html` | Section number requiring the `%100` split within a double-digit-suffix part | `.../title_0450/chapter_0050/part_0050/section_0110/0450-0050-0050-0110.html` |
| `montana_title_0010_index.html` | Title discovery, incl. reserved-title plain-text rows | `.../bills/mca/index.html` |
| `montana_title_0450_chapters_index.html` | Chapter discovery | `.../title_0450/chapters_index.html` |
| `montana_title_0450_chapter_0050_parts_index.html` | Part discovery (the extra hop) | `.../title_0450/chapter_0050/parts_index.html` |
| `montana_title_0450_chapter_0050_part_0050_sections_index.html` | Section discovery incl. renumbered + reserved rows | `.../title_0450/chapter_0050/part_0050/sections_index.html` |
| `montana_missing_section_404.html` | Missing-section 404 error page (real) — capture during B10 implementation | `.../title_0010/chapter_0110/part_0010/section_0990/0010-0110-0010-0990.html` (live HTTP 404, `<title>404</title>`, 49,280 bytes) |

All fixtures above have real, live provenance (URL + this session's fetch)
and can be captured verbatim rather than fabricated. The missing-section /
404 fixture is explicitly **not** included — capturing it now would mean
guessing at Montana's actual error-page shape, which the report's
instructions forbid.

## Adapter design (proposed, not implemented)

```
class MontanaAdapter(BaseStateAdapter):
    BASE_URL = "https://mca.legmt.gov/bills/mca"
    state_code = "MT"
    state_name = "Montana"

    def build_url(self, ref):
        # TitleRef  -> {BASE_URL}/title_{code(title)}/chapters_index.html
        # ChapterRef -> {BASE_URL}/title_{code(title)}/chapter_{code(chapter)}/parts_index.html
        # SectionRef -> parse ref.identifier "T-C-S" into ints;
        #               part = S // 100; local = S % 100
        #               -> {BASE_URL}/title_{code(T)}/chapter_{code(C)}/
        #                  part_{code(part)}/section_{code(local)}/
        #                  {code(T)}-{code(C)}-{code(part)}-{code(local)}.html
        # where code(n) = f"{n*10:04d}"
        ...

    def list_titles(self):
        # scrape bills/mca/index.html; one TocNode per <a href="title_.../chapters_index.html">;
        # skip plain-text (reserved) rows; skip title_0000 (Constitution) — out of scope.
        ...

    def list_chapters(self, title_ref):
        # scrape title_{code}/chapters_index.html; same linked/reserved-skip pattern.
        ...

    def list_sections(self, chapter_ref):
        # 1) scrape chapter_{code}/parts_index.html for Part links
        # 2) for each part, scrape part_{code}/sections_index.html
        # 3) flatten all parts' section rows into one Sequence[TocNode]
        ...

    def retrieve_section(self, ref):
        # build_url -> fetch -> parse heading/body/History -> normalize()
        ...

    def normalize(self, parsed, ref):
        # cross-check citation number in the repeated numbered-citation line
        #   against ref.identifier -> RefMismatchError on mismatch
        # repealed/reserved (no numbered subsections, "Repealed."/"reserved."
        #   catchline) -> heading = catchline text, text = "", amendment_notes
        #   = History line if present else None
        # normal -> text = joined subsection paragraphs, amendment_notes =
        #   History line verbatim
        # status stays UNKNOWN (no structural status field on the source,
        #   matching the rest of this project's adapters)
        ...
```

**State-specific parsing rules:**

1. `code(n) = f"{n * 10:04d}"` — the single arithmetic rule that drives
   every path segment; implement once, reuse for title/chapter/part/
   section codes.
2. Section-number split: `part = int(section_number) // 100`,
   `local = int(section_number) % 100`.
3. Discovery must skip **plain-text (non-`<a>`) rows** at both the title
   and chapter level — these are reserved units, not errors.
4. `list_sections` is a two-hop aggregate (parts_index → N ×
   sections_index), unlike a typical single-page Family-A discovery hop.
5. Repealed/reserved section bodies get the same no-body/short-heading
   treatment already established for Nebraska/North Carolina — no new
   exception type needed.
6. Exclude Title `0000` (Constitution, `article_` URL segments) from
   `list_titles()`'s output entirely.

## Error contract

| Condition | Mapping | Status |
|---|---|---|
| HTTP 404 on any hop | `RefNotFoundError` | `VERIFIED` (live curl, Aug 16 2026 — §14) |
| Network/connection failure, non-404 non-2xx | `AdapterUnavailableError` | `UNVERIFIED` (project convention — §15) |
| Section page's numbered-citation line doesn't match `ref.identifier` | `RefMismatchError` | `INFERENCE` (structural pattern is `VERIFIED`; the mismatch trigger itself wasn't tested against a real mismatched fetch) |
| Section page has no recognizable numbered-citation heading at all | `NormalizationError` | `INFERENCE`, matching existing adapters' convention |
| `TitleRef` for the Constitution (`0000`) or any ref this adapter doesn't address | `UnsupportedRefError` | Design decision (§4/§12), not observed as a live error |
| Reserved-range section fetched as if the range's *interior* numbers (e.g. `1-13-107`) were independently addressable | Not applicable — the adapter must never construct such a ref; `list_sections` only yields the range's TOC-listed identifier | Design decision |

## Test matrix (18 tests, ≥ 15 required)

1. `test_adapter_is_concrete` — instantiates without abstract-method errors.
2. `test_section_ref_url` — normal 3-digit section (`1-11-103`) builds the exact expected URL via the `%100` arithmetic.
3. `test_section_ref_url_double_digit_part` — 4-digit section number with part ≥ 10 (`2-6-1030`) builds the correct URL.
4. `test_chapter_ref_url` — chapter-level `build_url` returns the `parts_index.html` URL (not a sections page, since Montana's chapter itself has no direct section listing).
5. `test_title_ref_url` — title-level `build_url` returns `chapters_index.html`.
6. `test_unsupported_ref_for_constitution_title` — `TitleRef(identifier="0")` raises `UnsupportedRefError`.
7. `test_returns_titles_skipping_reserved_and_constitution` — `list_titles()` excludes plain-text reserved rows and Title 0.
8. `test_returns_chapters_skipping_reserved` — `list_chapters()` excludes a plain-text reserved-chapter range.
9. `test_returns_sections_aggregated_across_parts` — `list_sections()` for a multi-part chapter returns the union of every part's sections_index rows.
10. `test_wrong_title_raises_ref_not_found` — chapter lookup under a title ref that doesn't resolve.
11. `test_404_maps_to_ref_not_found` — mocked 404 → `RefNotFoundError` (network mocked; the live 404 shape is confirmed in §14, so the mapping's realism is now live-verified).
12. `test_network_failure_raises_adapter_unavailable` — mocked connection error → `AdapterUnavailableError`.
13. `test_full_retrieval_normal_section` — real fixture (`1-11-103`), asserts heading/body/History parsed correctly.
14. `test_repealed_section_empty_body_with_heading` — real fixture (`1-13-101`), heading = `"Repealed"`, text empty, amendment_notes has the short History.
15. `test_reserved_range_section_empty_body_no_history` — real fixture (`1-13-106`), heading references the range, text empty, amendment_notes is `None`.
16. `test_section_number_mismatch_raises_ref_mismatch_error` — fixture doctored so the parsed citation ≠ `ref.identifier`.
17. `test_no_citation_heading_raises_normalization_error` — malformed/empty fixture.
18. `test_part_arithmetic_helper_matches_all_sampled_sections` — a focused unit test asserting the `code()`/split-arithmetic helper reproduces every one of the 18 cross-checked URL codes from this research session (regression guard for the one genuinely novel piece of Montana-specific logic).

## Architecture compatibility

**Fully compatible, no framework change.** `TitleRef → ChapterRef →
SectionRef` maps onto Montana's real Title → Chapter → Section citation
exactly as designed; the Part level is absorbed as adapter-internal URL
routing (derived arithmetically from the section number, never exposed
as a ref field), which is a narrower, cleaner case than Massachusetts's
genuine 4-level citation noted in the family matrix, and doesn't require
Nebraska/Minnesota/Wisconsin's synthetic-title workaround either, since
Montana has a real title level.

## Known limitations

1. **HTTP 404 / missing-section behavior is now VERIFIED live** (§2/§13/§14)
   via real `curl` probes — plain 404, zero redirects, real 404 page.
   **Network-failure (non-404 error/connection) behavior remains
   UNVERIFIED** on Montana specifically; the project convention
   (→ `AdapterUnavailableError`) is applied unchanged.
2. **URL arithmetic verified on 18 rows across 4 parts in 3 titles**, not
   exhaustively across all ~90 active titles. Labeled `INFERENCE` at the
   generalization level; recommend a spot-check of a few more
   titles/chapters during implementation (cheap, since the hypothesis is
   now precise and falsifiable).
3. **Encoding now confirmed** (§16) — `<meta charset="utf-8">` observed on
   section and 404 pages via raw `curl`.
4. **No lettered/decimal section identifiers found**, but this is an
   absence-of-evidence inference from 4 sampled parts, not a scan of the
   full code.
5. **Title 0 (Constitution) is out of scope** by design, consistent with
   this project's existing scope for other states, but worth flagging
   explicitly since it's the one title that doesn't follow the
   `chapter_XXXX` URL convention.
6. **Rate-limit behavior under batch load is unknown** — only ~15 requests
   were made this session.

## VERIFIED / UNVERIFIED / INFERENCE table

| Item | Status |
|---|---|
| Official host / live accessibility | VERIFIED |
| Title discovery | VERIFIED |
| Chapter discovery | VERIFIED |
| Part discovery (extra hop) | VERIFIED |
| Section discovery | VERIFIED |
| Section retrieval (normal) | VERIFIED |
| Section retrieval (repealed) | VERIFIED |
| Section retrieval (reserved range) | VERIFIED |
| URL arithmetic (`code(n) = n*10`, `%04d`) | VERIFIED on 18 sampled rows / INFERENCE beyond that |
| Hierarchy = Title→Chapter→Section citation, Part is URL-only | VERIFIED (official numbering-system doc + 18 samples) |
| Citation format (`{t}-{c}-{s}`) | VERIFIED |
| Formal abbreviation (`Mont. Code Ann. §`) | INFERENCE |
| Heading/body/History structure | VERIFIED |
| No case-annotations block on current pages | VERIFIED (Montana's own Help page) |
| Decimal/lettered section identifiers | INFERENCE (none found) |
| Repealed section shape | VERIFIED |
| Reserved (single + range) section shape | VERIFIED |
| Constitution (Title 0) uses `article_` not `chapter_` | VERIFIED |
| HTTP 404 behavior | VERIFIED (live curl, 4 probe cases, Aug 16 2026) |
| Network failure behavior | UNVERIFIED (project convention) |
| Encoding | VERIFIED (`<meta charset="utf-8">` on section + 404 pages) |
| Pagination (none) | VERIFIED (for sampled pages) |
| JS dependency (none) | VERIFIED |
| Bot protection / auth (none observed) | VERIFIED (for ~15 requests) |
| Version/edition banner | VERIFIED |

## FINAL VERDICT

**READY FOR B10 IMPLEMENTATION.**

The one previously-blocking item — §14 HTTP 404 / missing-section
behavior — was confirmed live on Aug 16 2026 with real `curl` against
`mca.legmt.gov`: every deliberately nonexistent URL (nonexistent section
`1-11-199` under valid title 1 / ch 11 / part 1, nonexistent chapter,
nonexistent part, nonexistent title) returned a plain HTTP 404 with zero
redirects and a real 404 error page (`<title>404</title>`, 49,280 bytes).
No soft-404 and no redirect behavior were observed. Encoding was also
confirmed (`<meta charset="utf-8">` on both section and 404 pages).

The 404 → `RefNotFoundError` mapping is therefore live-verified, not
convention-only, and `build_url` + fetch alone is sufficient to reach it
for missing sections. Every other item in this report is either VERIFIED
or a clearly-scoped, low-risk INFERENCE (URL-arithmetic generalization,
formal-citation abbreviation, absence of decimal/lettered identifiers).
Montana is a clean Family-A fit: live-reachable, no JS, no auth wall,
three-level citation with deterministic URL arithmetic, and the Part level
absorbed adapter-internally. Recommended implementation batch: B10, solo,
difficulty LOW.

**B10 kickoff evidence (recorded from this session):**

| Probe | URL | Result |
|---|---|---|
| Valid baseline | `https://mca.legmt.gov/bills/mca/title_0010/chapter_0110/part_0010/section_0030/0010-0110-0010-0030.html` (`1-11-103`) | HTTP 200, `text/html`, `<meta charset="utf-8">` |
| Nonexistent section | `https://mca.legmt.gov/bills/mca/title_0010/chapter_0110/part_0010/section_0990/0010-0110-0010-0990.html` (`1-11-199`) | HTTP 404, 0 redirects, `<title>404</title>`, 49,280 B |
| Nonexistent chapter | `https://mca.legmt.gov/bills/mca/title_0010/chapter_0990/parts_index.html` (`1-99`) | HTTP 404, 0 redirects |
| Nonexistent part | `https://mca.legmt.gov/bills/mca/title_0010/chapter_0110/part_0990/sections_index.html` (`11-99`) | HTTP 404, 0 redirects |
| Nonexistent title | `https://mca.legmt.gov/bills/mca/title_0910/chapters_index.html` (`91`) | HTTP 404, 0 redirects |
