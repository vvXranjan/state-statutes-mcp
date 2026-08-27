# 50-State Retrieval-Family Matrix

Research performed Aug 15, 2026. Findings labeled:

- **VERIFIED** — observed live against the official host from this
  environment (plain `curl` GET, browser UA), or verified through a
  Wayback Machine snapshot of the official host.
- **UNVERIFIED** — not yet exercised; URL pattern known but structure
  unconfirmed.
- **INFERENCE** — reasoned from verified structure or prior official
  research rather than directly observed.
- **STOPPED** — source unusable without auth/API key/JS execution/browser
  instrumentation.

34 adapters were implemented at the time this matrix's research was
written (WA, TX, IL, VA, DE, FL, SD, ME, MO, VT, WV, MN, AZ, KS, ND, MD,
SC, NE, MT, HI, MA, OH, RI, WI, ID, NV, NH, CT, OR, NC, KY, IA, NM, OK),
plus Alabama (the 35th, a GraphQL/JSON-POST family-L adapter), Wyoming
(the 36th, a per-title-PDF family-I adapter), Colorado (the 37th, a
per-title-PDF family-I adapter using archived official fixtures), and
California (the 38th, a server-rendered-HTML family-M adapter), all added
after the matrix's research was written. This matrix now classifies the
remaining 12 states. Each row records the adapter family the state would
map to (A–M), its reachability, and its batch recommendation.

Family legend (from research):

- **A** — one HTML file per section (Washington-style).
- **B** — one HTML file per chapter, sections embedded as anchors
  (Delaware/Florida/Texas-style).
- **C** — static directory of files (Illinois-style).
- **D** — JSON/REST API returning structured text (Virginia-style).
- **E** — JSON API with embedded HTML content (South Dakota-style).
- **F** — JS-form / postback-driven HTML (requires browser events).
- **G** — Lexis/Nexis or other third-party vendor host (auth wall).
- **H** — Folio/NXT database system (search-only, no persistent URLs).
- **I** — bulk or per-section PDF/RTF documents.
- **J** — JS SPA; content only via client-side rendering or keyed API.
- **K** — infeasible / framework-mismatched (hierarchy or access).
- **L** — GraphQL/JSON POST API returning structured records with embedded
  HTML (Alabama-style).
- **M** — server-rendered HTML over ordinary HTTP GET with a deep
  (4+-level) hierarchy folded into the three-level ref model and direct
  per-section pages (California-style).

---

## Implemented (37)

| State | Code | Adapter | Family | Status |
|-------|------|---------|--------|--------|
| Washington | WA | `washington` | A | VERIFIED live |
| Texas | TX | `texas` | B (chapter anchors) + JS discovery | VERIFIED live |
| Illinois | IL | `illinois` | C (FTP static) | VERIFIED live |
| Virginia | VA | `virginia` | D (JSON API, structured text) | VERIFIED live |
| Delaware | DE | `delaware` | B/C (static HTML) | VERIFIED live |
| Florida | FL | `florida` | B (chapter HTML, versioned) | VERIFIED live |
| South Dakota | SD | `south_dakota` | E (JSON API, embedded HTML) | VERIFIED live |
| Minnesota | MN | `minnesota` | A (one file per section) | VERIFIED live |
| Arizona | AZ | `arizona` | A (one file per section) | VERIFIED live |
| Kansas | KS | `kansas` | D (JSON API, structured text) | VERIFIED live |
| Maine | ME | `maine` | A (one file per section) | VERIFIED live |
| Maryland | MD | `maryland` | A (one file per section) | VERIFIED live |
| Missouri | MO | `missouri` | A/B (Wayback fixtures; live host bot-blocks) | VERIFIED fixtures |
| North Dakota | ND | `north_dakota` | E (bulk JSON, embedded HTML) | VERIFIED live |
| South Carolina | SC | `south_carolina` | B (chapter HTML, embedded sections) | VERIFIED live |
| Vermont | VT | `vermont` | B (chapter HTML; Wayback fixtures) | VERIFIED fixtures |
| West Virginia | WV | `west_virginia` | B (chapter HTML; Wayback fixtures) | VERIFIED fixtures |
| Nebraska | NE | `nebraska` | A (one file per section) | VERIFIED fixtures |
| Montana | MT | `montana` | A (one file per section) | VERIFIED live |
| Hawaii | HI | `hawaii` | A/C (one file per section; proxy captures) | VERIFIED via proxy |
| Massachusetts | MA | `massachusetts` | A (one file per section) | VERIFIED via proxy |
| Ohio | OH | `ohio` | A (one file per section) | VERIFIED fixtures |
| Rhode Island | RI | `rhode_island` | A (one file per section) | VERIFIED fixtures |
| Wisconsin | WI | `wisconsin` | A (one file per section) | VERIFIED fixtures |
| Idaho | ID | `idaho` | A (one file per section) | VERIFIED fixtures |
| Nevada | NV | `nevada` | B (chapter HTML; synthetic fixtures) | VERIFIED fixtures |
| New Hampshire | NH | `new_hampshire` | B (chapter HTML; synthetic fixtures) | VERIFIED fixtures |
| Connecticut | CT | `connecticut` | B (chapter HTML) | VERIFIED fixtures |
| Oregon | OR | `oregon` | B (chapter HTML, latin-1) | VERIFIED fixtures |
| North Carolina | NC | `north_carolina` | B (chapter HTML, dual encoding) | VERIFIED fixtures |
| Kentucky | KY | `kentucky` | I (per-section PDF) | VERIFIED live |
| Iowa | IA | `iowa` | I (per-section PDF, versioned year) | VERIFIED live |
| New Mexico | NM | `new_mexico` | I (chapter-level PDF) | VERIFIED live |
| Oklahoma | OK | `oklahoma` | I (per-title PDF, flat/chaptered) | VERIFIED live |
| Alabama | AL | `alabama` | L (GraphQL/JSON POST, embedded HTML) | VERIFIED live |
| Wyoming | WY | `wyoming` | I (per-title PDF, `title{NN:02d}.pdf`) | VERIFIED live |
| Colorado | CO | `colorado` | I (per-title PDF, archived official fixtures) | VERIFIED fixtures |
| California | CA | `california` | M (server-rendered HTML per-section, folded 4-level hierarchy) | VERIFIED live |

---

## Remaining 12 States

Groups 1-3 below originally described candidate families. All states in
Groups 1-3 are now implemented except Michigan (still remaining, in Group
1); see the Implemented table above. Only Groups 5 and 6 hold
un-implemented states other than Michigan and Utah (Group 5).

### Group 1 — One file per section (Family A)

These map directly onto the Washington/Maine adapter pattern (per-section
URL, server-rendered HTML, no JS).

| State | Official source | Reachability | Discovery | Section retrieval | Hierarchy | Citation | Version/year | 404 signal | Family | Confidence | Difficulty | Batch |
|-------|-----------------|--------------|-----------|-------------------|-----------|----------|--------------|------------|--------|------------|------------|-------|
| **Idaho** | `legislature.idaho.gov/statutesrules/idstat/{Title}/{T}{CH}/SECT{sec}/` | **VERIFIED** (Wayback 20260712203433) | Title/chapter directories | One file per section, TITLE/CHAPTER heading + history line | Title → Chapter → Section | `Idaho Code § {t}-{ch}-{sec}` | Current-code | (live host 000; assume 404) | A | MEDIUM | LOW | MN + AZ + ID |
| **Wisconsin** | `docs.legis.wisconsin.gov/document/statutes/{sec}` | **VERIFIED** (Wayback 20260722161219) | `/statutes/statutes` lists chapters | One file per section (103 KB, "Wisconsin Legislature: 13.92") | Chapter → Section | `Wis. Stat. § {ch}.{sec}` | Current-code | (live host 000) | A | MEDIUM | LOW | MN + AZ + ID |
| **Ohio** | `codes.ohio.gov/ohio-revised-code/section-{sec}` | **VERIFIED** (Wayback 20260812050041) | Title/chapter TOC | One file per section (full text; effective-date banner) | Title → Chapter → Section | `Ohio Rev. Code § {ch}.{sec}` | Versioned banner ("effective Sept 7, 2026") | 404 | A | HIGH | LOW | **OH + RI** |
| **Rhode Island** | `webserver.rilegislature.gov/Statutes/TITLE{nn}/{nn}-{c}/{nn}-{c}-{s}.htm` | **VERIFIED** (Wayback 20250401074949) | Title/chapter dirs | One file per section (5.9 KB, `R.I. Gen. Laws § 43-3-2`) | Title → Chapter → Section | `R.I. Gen. Laws § {t}-{c}-{s}` | Current-code | (live host 000) | A | MEDIUM | LOW | **OH + RI** |
| **Massachusetts** | `malegislature.gov/Laws/GeneralLaws/Part{}/Title{}/Chapter{n}/Section{n}` | **VERIFIED** (Wayback 20260705180333) | Part→Title→Chapter→Section hierarchical | One file per section (77 KB) | Part → Title → Chapter → Section (4 levels) | `M.G.L. c. {n}, § {s}` | Current-code | 404 | A | HIGH | MEDIUM (4-level flattening) | **MA + NE** |
| **Nebraska** | `nebraskalegislature.gov/laws/statutes.php?statute={sec}` | **VERIFIED** (Wayback 20251215062931) | Title→chapter index | One file per section (`Neb. Rev. Stat. 77-1801`, 30 KB) | Chapter → Section | `Neb. Rev. Stat. § {ch}-{sec}` | Current-code | 404 | A | MEDIUM | LOW | **MA + NE** |
| **Michigan** | `legislature.mi.gov/Home/GetObject?objectName=mcl-{ch}-{sec}` | **VERIFIED** (Wayback 20250421214234) | ChapterIndex (`mcl-chap{n}`) | One file per section (`MCL - Section 28.2`, 22 KB) | Chapter → Section | `MCL § {ch}.{sec}` | Versioned ("Complete Through PA …") | 404 | A | HIGH | LOW | **MI + UT** |
| **Hawaii** | `capitol.hawaii.gov/hrscurrent/Vol{nn}_Ch{n}-{n}/HRS{n}/HRS_{n}-{n}.htm` | **PARTIAL** (volume dir VERIFIED via Wayback 20251010215648; section page Cloudflare-blocked) | Static volume→chapter directory | One file per section (structure INFERENCE from dir + filename pattern) | Title (volume) → Chapter → Section | `Haw. Rev. Stat. § {ch}-{sec}` | Current-code | (Cloudflare) | A/C | LOW (Cloudflare) | MEDIUM | **HI + CT** |

### Group 2 — Chapter-document HTML (Family B)

These map onto the Delaware/Florida/Texas adapter pattern (chapter page
with embedded section anchors).

| State | Official source | Reachability | Discovery | Section retrieval | Hierarchy | Citation | Version/year | 404 signal | Family | Confidence | Difficulty | Batch |
|-------|-----------------|--------------|-----------|-------------------|-----------|----------|--------------|------------|--------|------------|------------|-------|
| **Connecticut** | `cga.ct.gov/current/pub/chap_{n}.htm` | **VERIFIED** (Wayback 20260811192527) | `titles.htm` → `title_{n}.htm` | Chapter page with `Sec. {c}-{s}.` headings (110 KB) | Title → Chapter → Section | `Conn. Gen. Stat. § {c}-{s}` | Current (2026 session) | (live host 000) | B | MEDIUM | LOW | **HI + CT** |
| **North Carolina** | `ncleg.gov/Laws/GeneralStatuteSections/Chapter{n}` | **VERIFIED** (Wayback 20260430164349) | `ChapterIndex` | Chapter page `§ {c}-{s}.` headings (69 KB) | Chapter → Section | `N.C. Gen. Stat. § {c}-{s}` | Current-code | (live host 403) | B | MEDIUM | LOW | **NC + OR** |
| **Oregon** | `oregonlegislature.gov/bills_laws/ors/ors{n}.html` | **VERIFIED** (Wayback 20260224045708) | Title index → chapter files | Chapter page `{c}.{s} State policy…` (361 KB, latin-1) | Title → Chapter → Section | `Or. Rev. Stat. § {c}.{s}` | Current-code | (live host 000) | B | MEDIUM | LOW | **NC + OR** |
| **Nevada** | `leg.state.nv.us/NRS/NRS-{n}.html` | **VERIFIED** (Wayback 20260203155133) | Title list → chapter files | Chapter page `NRS {ch}.{s}` headings (114 KB) | Title → Chapter → Section | `Nev. Rev. Stat. § {ch}.{s}` | Current-code | (live host 403) | B | MEDIUM | LOW | **NV + NH** |
| **New Hampshire** | `gc.nh.gov/rsa/html/{X}/{n}/{n}-mrg.htm` | **VERIFIED** (Wayback 20250924222607) | `nhtoc.htm` → chapter files | Chapter page `Section {c}:{s}` + `{c}:{s} Text.` headings (44 KB) | Chapter → Section (RSA chapter.section) | `N.H. RSA {c}:{s}` | Current-code | (live host 403) | B | MEDIUM | LOW | **NV + NH** |

### Group 3 — JSON/REST APIs (Families D/E)

Map onto Virginia (structured text) or South Dakota (embedded HTML). Both
original JSON-family states (KS, ND) are implemented; no states remain in
this group.

### Group 4 — Bulk PDF/RTF (Family I)

**Kentucky (KY), Iowa (IA), New Mexico (NM), and Oklahoma (OK) are now
IMPLEMENTED** (the PDF-family adapters, sharing `fetch_bytes` +
`extract_pdf_text`); they are moved to the Implemented table above. No
PDF-family states remain.

### Group 5 — Blocked live, unverified or fixture candidates (VERIFIED pattern or known URL)

| State | Official source | Reachability | Notes | Family | Confidence | Difficulty | Batch |
|-------|-----------------|--------------|-------|--------|------------|------------|-------|
| **Alaska** | `akleg.gov/basis/statutes.asp` | **BLOCKED** live (403); title list VERIFIED via Wayback 20260813221705 | Titles are JS-driven (Basis Infobase); no static per-section URL observed | J (JS) / H | LOW | HIGH | defer |
| **Utah** | `le.utah.gov/xcode/…`; `glen.le.utah.gov/code/{cite}/` | **BLOCKED** live (000) | Official XML API requires a developer token; xcode chapter content JS-loaded | J (token) / D | LOW | MEDIUM | defer or keyed |
| **New Jersey** | `pub.njleg.state.nj.us/Statutes/` | **BLOCKED** (000) | LIS is a Folio database — search-based, no persistent URLs; `STATUTES-TEXT.zip` download offered | H | LOW | HIGH | defer (zip) |
| **Louisiana** | `legis.la.gov/legis/LawSearch.aspx` | **BLOCKED** live (000); search page VERIFIED via Wayback 20260811192827 | Folder-based ASP.NET WebForms postback navigation | F | LOW | HIGH | defer |

### Group 6 — STOPPED (auth wall, API key, or JS-only content)

| State | Official source | Reason | Family | Difficulty |
|-------|-----------------|--------|--------|------------|
| **Georgia** | `legis.ga.gov/api/` | 401 auth; official code via LexisNexis | G | HIGH |
| **Arkansas** | `advance.lexis.com` | Lexis auth wall | G | HIGH |
| **Tennessee** | Lexis via `tncourts.gov` | Lexis auth wall | G | HIGH |
| **Mississippi** | Lexis-published via `sos.ms.gov` | Lexis auth wall | G | HIGH |
| **Indiana** | `iga.in.gov` | React SPA (empty shell); `api.iga.in.gov` 403 "Invalid API key" | J (key) | HIGH |
| **New York** | `legislation.nysenate.gov/api/3/` | 403/000; documented REST API requires free API key | D (key) | MEDIUM |
| **Pennsylvania** | `palegis.us/statutes/consolidated/view-statute` | 000/302; legacy `consCheck.cfm` form-based (Wayback has no content captures) | F/J | HIGH |

---

## Batch Recommendations (next 3–5)

Priority ordering: reachable live FIRST, then Wayback-verified fixtures,
then deferred/unverified. Each batch shares a genuine mechanism.

| Batch | States | Family | Shared mechanism | Why | Status |
|-------|--------|--------|------------------|-----|--------|
| **B1** | **MN + AZ** | A | One-file-per-section, live-reachable, clean markup, numeric section ids | Both fully VERIFIED live; lowest risk; no fixtures needed | DONE |
| **B2** | **KS + ND** | D/E | Official JSON APIs | KS is clean JSON API (structured text, D); ND is bulk JSON with embedded HTML (E). Both live-reachable. ND needs 13 MB stream handling | DONE |
| **B3** | **MD + SC** | A + B | Both live-reachable, low complexity | MD is per-section (A), SC is chapter-document (B); both pure static HTML, no JS, no fixtures | DONE |
| **B4** | **OH + RI** | A | One-file-per-section; both VERIFIED via recent Wayback snapshots (2026) | High-confidence structures; fixtures from Wayback like MO/VT/WV | — |
| **B5** | **WI + ID** | A | One-file-per-section; Wayback-verified | Same family as B1/B4; adds lettered sections and legislative-nav chrome | — |

After B1–B5 (10 more states, total 21), the remaining reachable set is
MA, NE, MI, CT, NC, OR, NV, NH (Wayback-verified) plus KY/NM/IA/OK (PDF
family) — then the blocked/stopped remainder. B1–B3 are complete (17
states); B4 (OH + RI) and B5 (WI + ID) remain.

## Architectural Pattern Notes

- **No framework changes needed.** The VERIFIED patterns all reduce to
  existing families A–E, I, plus J/F/G/H (unusable). `TitleRef →
  ChapterRef → SectionRef` holds everywhere with three exceptions:
  - Minnesota and Wisconsin expose **Chapter → Section only** (no title
    level). Framework requires a TitleRef; a synthetic title is the
    only mapping without framework change. (MN implemented with a
    synthetic title in Batch B1.)
  - Massachusetts is a **4-level** hierarchy (Part → Title → Chapter →
    Section); flatten Part into the TitleRef identifier or drop Part
    (citation `M.G.L. c. {n}` needs only chapter+section).
  - Alaska/NJ/UT/WY are Folio/NXT/JS systems with no stable citation
    URL — infeasible without browser instrumentation.
- **PDF family (KY, NM, IA, OK)** introduces text extraction into the
  framework for the first time. KY and IA are per-section/per-chapter
  small docs; OK is per-title bulk (heavy). Recommend deferring PDF
  extraction until a dedicated research question, or treating KY's
  section-PDF as a per-section I-family adapter.
- **Bot-blocks are the dominant risk** (MO/VT/WV precedent): OH, WI, ID,
  CT, NC, OR, NV, NH, RI, MA, NE, MI are all unreachable from this
  environment live (000/403) but have Wayback snapshots; adapters for
  them should follow the MO/VT/WV fixture pattern.

## 50-State Scalability Review (real bottlenecks)

1. **Live-host unreachability (~20 states)** — not a parsing problem but
   a network-egress problem. The fixture pattern (capture to
   `tests/fixtures/`, parse offline, live-batch once per session) is the
   only way to make progress; it already works for MO/VT/WV.
2. **Discovery-vs-retrieval asymmetry** — Family A states (WA/ME/MN/AZ/
   ID/WI/MD/OH/RI/NE/MI/MA) give clean per-section URLs but their
   discovery often sits behind a JS or postback listing (AZ title list is
   fine; ID/NE chapter indexes vary). Discovery must be verified per
   state, not assumed from the retrieval URL shape.
3. **Bulk JSON (ND 13 MB, WY PDFs, OK per-title PDFs)** — memory and
   streaming; ND needs chunked fetch/retry. This is an I/O bottleneck
   shared by ~4 states.
4. **PDF extraction (KY/NM/IA/OK)** — a genuinely new code path (PDF
   text layer + citation anchoring). One adapter proves it; the other
   three reuse it.
5. **No-title-level states (MN, WI)** — two states cannot map onto the
   three-level ref model without either a synthetic title or a framework
   change. Framework change is out of scope per the research mandate, so
   these are mapped with a synthetic title and flagged (MN done in Batch
   B1; WI remains).
6. **Stopped set (~10)** — auth/Lexis/API-key states are not solvable
   from this environment at all. They should be documented as
   out-of-scope rather than repeatedly re-probed.

## Test Strategy

- Every adapter keeps the existing offline `_mock_network` pattern
  (mock `state_statutes_mcp.adapters._fetch.urllib.request.urlopen`, not
  adapter internals).
- Live-reachable states (MN, AZ, KS, ND, MD, SC): capture real HTML/JSON
  to `tests/fixtures/{state}*` in the session where they're implemented;
  tests assert against those fixtures exactly as Maine/FL/SD do.
- Wayback-verified states (OH, RI, WI, ID, CT, NC, OR, NV, NH, MA, NE,
  MI, HI): capture the Wayback snapshot to a fixture with provenance
  (timestamp + URL) recorded in the adapter doc, mirroring the
  MO/VT/WV pattern.
- New behaviors covered by existing adapters since this matrix was
  written (all now implemented and tested):
  - ND bulk-JSON streaming and embedded-HTML section extraction.
  - KS structured-text JSON record parsing (no HTML).
  - MD article-level refs (article replaces title).
  - SC chapter-document embedded sections (family B).
  - Synthetic-title mapping for MN (adopted for the no-title state).
  - MA 4-level flattening (adopted).
  - KY/IA/NM PDF extraction (adopted; per-title PDFs for OK are the
    remaining PDF-family candidate).
- Assertion set per state stays the 15-case matrix from Maine (identity,
  URL construction, title/chapter/section discovery, retrieval,
  cross-checks, citation parsing, normalization, ref mismatch, malformed
  source, missing section, network failure, real fixture, MCP
  integration).

## DeepSeek Handoff

Summary for the next session (implementing batch B4 onward):

- **Historical snapshot (pre-Oklahoma)**: at the time this handoff was
  written, 33 adapters were committed (WA TX IL VA DE FL SD ME MO VT WV MN
  AZ KS ND MD SC NE MT HI MA OH RI WI ID NV NH CT OR NC KY IA NM) and the
  NM commit (0289363) was not yet pushed. **Current state (post-Alabama,
  state #35)**: 35 adapters committed on `feature/framework` (Oklahoma and
  Alabama added since this handoff), 1132 passing tests with 1 documented
  pre-existing Illinois real-fixture skip, and commit 7746681 (Alabama) is
  not yet pushed.
- **Research phase complete**; matrix lives in this file. The next
  realistic candidate is **Oklahoma** (per-title bulk PDFs, Family I;
  hierarchy is heterogeneous — flat Title→Section for most titles and
  Title→Chapter→Section for a minority), then **Michigan** (pending
  re-verification of its host). Reference adapters: Washington (A family),
  Delaware/South Carolina (B family), Kentucky/Iowa/New Mexico (I family),
  and the MO/VT/WV fixture pattern for any batch whose live host is
  blocked.
- **Do not** implement adapters for STOPPED states or propose framework
  changes; the mandate forbids both.
- Verify each URL live before coding; label findings VERIFIED/UNVERIFIED/
  INFERENCE in the adapter doc exactly as the prior state docs do.
