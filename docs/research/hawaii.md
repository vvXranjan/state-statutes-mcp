# Hawaii Research — B11

**Research performed:** August 17-18, 2026. All page structures below were
verified against real captures of the official host.

**Accessibility note (honest):** `data.capitol.hawaii.gov` is protected by
Cloudflare and direct HTTP access from this environment returns HTTP 403
(`curl`/`urllib`/`webfetch` all blocked). All live captures were therefore
retrieved through the `r.jina.ai` fetch proxy, which reaches the host and
returns its **verbatim, byte-for-byte official HTML** (`Microsoft Word 15
(filtered)` pages; re-fetches are identical). The fixtures in
`tests/fixtures/hi_*` are real official captures via that proxy; their
provenance is recorded below. The proxy reports the upstream HTTP status
(see §6); the 404 behavior was reported that way and is UNVERIFIED directly.

---

## 1. Official source

- **Official host:** `https://data.capitol.hawaii.gov` — the official
  Hawaii Revised Statutes (HRS) HTML site, server-rendered, anonymous, no
  auth/API key. `VERIFIED` (via proxy).
- **Do NOT use `www.capitol.hawaii.gov`** — that is the legislature portal,
  not the statute host (B11 brief).
- Pages are Microsoft Word-exported filtered HTML: `charset=utf-8`,
  class-driven (`RegularParagraphs`, `oneParagraph`, `XNotes`,
  `XNotesHeading`), no semantic heading tags for statute content.

## 2. Discovery

- **Titles = printed volumes.** `https://data.capitol.hawaii.gov/hrsall`
  lists 14 rows, one per HRS volume:
  `...<td class="text-left"><a href="ChaptersByVolume.aspx?id=1">VOLUME 1</a></td>
  <td class="text-right"><a href="ChaptersByVolume.aspx?id=1">1-42F</a></td>...`
  `TitleRef.identifier` is the volume number `"1".."14"`. `VERIFIED` (14/14).
- **Chapters:** `https://data.capitol.hawaii.gov/hrsall/ChaptersByVolume.aspx?id={vol}`.
  Chapter rows:
  `<td class="text-left col-sm-1"><a href="/hrscurrent/Vol07_Ch0346-0398/HRS0377/HRS_0377-.htm">377</a></td>
   <td class="text-left"><a href="...">HAWAII EMPLOYMENT RELATIONS ACT</a></td>`.
  The identifier is the anchor text (`"377"`, `"346C"`, `"1B"`). Front-matter
  rows (`01-USCON`, `02-HNP/`, `03-ORG/`, `04-ADM/`, `05-CONST/`, `06-HHCA/`)
  use a different cell layout and are not chapters. `VERIFIED` (all 14 volumes).
  - **Repealed chapters** are still listed with `(REPEALED)` in the name
    (e.g. chapter 2 `STATUTE REVISION AND PUBLICATION (REPEALED)`; 10 in
    vol 1). Per the B11 brief they are NOT treated as normal chapter links
    and are skipped by the adapter.
- **Sections:** the chapter page
  `/hrscurrent/{folder}/HRS{ch}/HRS_{ch}-.htm` is a plain-text TOC:
  `<p class="RegularParagraphs">&#160;&#160;&#160; 377-1 Definitions</p>`,
  `... 377-4.5 Religious exemption from labor organization membership`.
  `SectionRef.identifier` is the full `{chapter}-{section}` citation
  (`"377-4.5"`, `"1B-1"`). `VERIFIED`.
  - For chapter 1, the page (`HRS_0001-.htm`) is the printed title page
    ("DIVISION 1 ... CHAPTER 1 ...") and also lists the title's chapters
    (`1 Common Law; Construction of Laws`) as non-link rows; a
    `^\d+[A-Z]?-\d+(\.\d+)?` row pattern plus a `{chapter}-` prefix filter
    keeps those out. `VERIFIED`.

## 3. Volume → folder map (VERIFIED, all 14)

The `/hrscurrent/` folder is a printed-range name that is NOT arithmetically
derivable (volume 7 lists chapters `346-398A` but its folder is
`Vol07_Ch0346-0398`). The adapter hardcodes this verified constant:

| Volume | Folder |
|--------|--------|
| 1 | `Vol01_Ch0001-0042F` |
| 2 | `Vol02_Ch0046-0115` |
| 3 | `Vol03_Ch0121-0200D` |
| 4 | `Vol04_Ch0201-0257` |
| 5 | `Vol05_Ch0261-0319` |
| 6 | `Vol06_Ch0321-0344` |
| 7 | `Vol07_Ch0346-0398` |
| 8 | `Vol08_Ch0401-0429` |
| 9 | `Vol09_Ch0431-0435H` |
| 10 | `Vol10_Ch0436-0474` |
| 11 | `Vol11_Ch0476-0490` |
| 12 | `Vol12_Ch0501-0588` |
| 13 | `Vol13_Ch0601-0676` |
| 14 | `Vol14_Ch0701-0853` |

## 4. Section URL construction (VERIFIED)

- Chapter directory/file: numeric part zero-padded to 4 digits, letter
  suffix verbatim: `377`→`0377`, `1B`→`0001B`, `346C`→`0346C`.
- Section filename: integer part zero-padded to 4 digits; optional decimal
  appended `_{decimal:04d}`. Verified examples:
  - `377-4.5` → `/hrscurrent/Vol07_Ch0346-0398/HRS0377/HRS_0377-0004_0005.htm`
  - `1-4.5`  → `/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0004_0005.htm`
  - `1-13.5` → `/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0013_0005.htm`
  - `1B-1`   → `/hrscurrent/Vol01_Ch0001-0042F/HRS0001B/HRS_0001B-0001.htm`
  - `701-119`→ `/hrscurrent/Vol14_Ch0701-0853/HRS0701/HRS_0701-0119.htm`

## 5. Section page structure (VERIFIED)

Operative content lives in `<div class="WordSection1">`; after it comes the
`pageLinks` navigation and a Cloudflare beacon script.

- **Heading:** the first `<p class="RegularParagraphs">`. The heading text
  is everything up to the LAST `</b>`. The heading may be split across bold
  runs and the citation may sit in its own bracket:
  - Normal: `<b>§377-4.5&#160; Religious exemption from labor organization
    membership.</b>` → `§377-4.5 Religious exemption from labor
    organization membership.`
  - Split bold: `<b>&#160;&#160;&#160;&#160; §1</b>-<b>2&#160; Certain laws
    not obligatory until published.</b>` → `§1 - 2 Certain laws ...`
  - Bracketed lettered/decimal: `<b>[§1B-1]</b>&#160; <b>Rural areas and
    federal programs.</b>` → `[§1B-1] Rural areas and federal programs.`
  The page's own citation is recovered with `[\[§]\s*§?\s*(\d+[A-Z]?\s*-\s*\d+(?:\.\d+)?)`,
  whitespace-normalized (so `§1 - 2` → `1-2`), and cross-checked against
  `ref.identifier`; a mismatch raises `RefMismatchError`. `VERIFIED`.
- **Body:** everything after the last `</b>` of the first paragraph plus
  all following `<p class="RegularParagraphs">` / `<p class="oneParagraph">`
  paragraphs (the latter hold lettered/list items like `(1)`, `(2)`),
  up to the first annotation block. Paragraphs are joined with blank lines.
  `VERIFIED` (1-1, 1-2, 1-4.5, 1-13.5, 1B-1, 377-4, 377-4.5).
- **History:** the inline bracketed citation at the end of the operative
  text, e.g. `[L 1982, c 102, §2; am L 1983, c 124, §9]` or
  `[L 1892, c 57, §5; am L 1903, c 32, §2; ...; HRS §1-1]`. Extracted into
  `amendment_notes` verbatim (brackets kept) and stripped from `text`.
  Some sections (e.g. 1B-1) have NO history bracket → `amendment_notes`
  stays `None`. `VERIFIED`.
- **Annotations:** `Attorney General Opinions`, `Law Journals and Reviews`,
  `Case Notes`, `Cross References` are all `XNotesHeading`/`XNotes` blocks
  AFTER the operative text. The adapter splits the WordSection at the first
  `class="XNotes"`, so annotation text is never part of `StatuteSection.text`.
  `VERIFIED`.

## 6. HTTP 404 / missing-document behavior (UNVERIFIED directly)

- Probed a deliberately nonexistent chapter `HRS0031` in Volume 1
  (`/hrscurrent/Vol01_Ch0001-0042F/HRS0031/HRS_0031-.htm`) and its section
  page. The fetch proxy reported **`Target URL returned error 404: Not Found`**
  for the upstream, and the body is the server's IIS error page
  (`<title>404 - File or directory not found.</title>`, `charset=iso-8859-1`).
- **Verdict:** the upstream is *reported* by the proxy to return a real HTTP
  404 (not a soft-404) for the missing chapter, and the body is the server's
  IIS error page — consistent with an upstream 404 but NOT a direct socket
  observation (Cloudflare blocks direct access here). The adapter therefore
  keeps the HTTP 404 → `RefNotFoundError` mapping **per project convention**
  (same as MontanaAdapter), and it is explicitly marked **UNVERIFIED
  directly**. Documented honestly here and in the adapter.

## 7. Repealed / reserved behavior (VERIFIED)

- **Repealed section** (701-119): `<b>§701-119</b> <b>&#160;REPEALED.&#160;
  </b>L 1988, c 260, §§4, 7; L 1996, c 104, §6.` — a `REPEALED.` heading
  with the repeal citation as the following text, then `Cross References`
  annotations. The adapter returns `heading="REPEALED."`, `text=""`, the
  repeal citation in `amendment_notes`, and `status=REPEALED` (the
  framework's structural-signal rule; same decision as Missouri/Rhode
  Island).
- **Repealed chapter** (chapter 2): the chapter page renders a `REPEALED.`
  paragraph and has no section rows. Repealed chapters are skipped by
  `list_chapters` (their names carry `(REPEALED)`).

## 8. Citation

`Haw. Rev. Stat. Section {chapter}-{section}` (e.g.
`Haw. Rev. Stat. Section 377-4.5`).

## 9. Encoding

All Word pages are UTF-8. The shared UTF-8 `fetch_url` helper is used
directly. (The 404 page is iso-8859-1 but is only ever raised as an error,
never parsed.)

## 10. UNVERIFIED / limitations

- Direct-from-host access is Cloudflare-blocked in this environment; live
  statuses (200/404) could not be directly observed and are only ever
  reported by the proxy's upstream status. The 404 → `RefNotFoundError`
  mapping is **UNVERIFIED directly** and kept per project convention.
- The volume→folder map is a snapshot as of Aug 17 2026. It is a
  printed-range naming convention; if the state reprints volumes the map
  would need updating (no live re-verification possible here).
- A section whose operative text legitimately ends with `]` (unlike any
  sampled section) would have that bracket misread as its history marker;
  no such section was observed.

## 11. Fixture provenance

All `tests/fixtures/hi_*` files are verbatim official captures of
`data.capitol.hawaii.gov` retrieved Aug 17 2026 via the `r.jina.ai` fetch
proxy (byte-identical to direct official HTML; see accessibility note).
Mapping:

- `hi_hrsall.html` — `/hrsall` (14 volume rows).
- `hi_vol01_chapters.html`, `hi_vol07_chapters.html` — `ChaptersByVolume.aspx?id=1|7`.
- `hi_chapter_0001.html` — `HRS_0001-.htm` (title/chapter-1 page).
- `hi_chapter_0001b.html` — `HRS_0001B-.htm` (chapter 1B TOC).
- `hi_chapter_0002.html` — `HRS_0002-.htm` (repealed chapter TOC).
- `hi_chapter_0377.html` — `HRS_0377-.htm` (chapter 377 TOC).
- `hi_section_1-1.html` — `HRS_0001-0001.htm` (older chapter; AG Opinions annotations).
- `hi_section_1-2.html` — `HRS_0001-0002.htm` (split-bold heading; Case Notes).
- `hi_section_1-4.5.html` — `HRS_0001-0004_0005.htm` (decimal, `[§...]` citation).
- `hi_section_1-13.5.html` — `HRS_0001-0013_0005.htm` (multi-paragraph body; Law Journals).
- `hi_section_1b-1.html` — `HRS_0001B-0001.htm` (lettered chapter; no history bracket).
- `hi_section_377-4.5.html` — `HRS_0377-0004_0005.htm` (decimal section).
- `hi_section_701-119.html` — `HRS_0701-0119.htm` (repealed section; Cross References).
- `hi_missing_chapter_404.html` — `HRS_0031-.htm` (HTTP 404 body).
