# Illinois Compiled Statutes (ILCS) — Source Research

**Status: PARTIALLY VERIFIED.** The ILCS host (`ilga.gov`) is unreachable
from this environment's network egress allowlist, so no raw HTML bytes
could be captured and no real fixture exists. The adapter's verified
facts come from the IllinoisAdapter module docstring, which records
what was independently verified via real fetches during the original
design/research (c38e1b2, "Implement Illinois statute adapter") and
what remains UNVERIFIED. This document does not invent behavior.

## 1. Official source

- Illinois General Assembly static ILCS mirror:
  `https://www.ilga.gov/ftp/ILCS/`.
- **VERIFIED**: two real fetches of
  `https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/072000050K9-2.html`
  resolved to real content for `720 ILCS 5/9-2`.
- **VERIFIED**: real directory listings were fetched for 6 different
  chapter/act pages, confirming the content-level shape (literal
  `Ch NNNN` / `Act NNNN` / filename tokens).
- **UNVERIFIED / LIMITATION**: the raw HTML tag structure is NOT
  verified (this sandbox's fetch tooling returns cleaned text, and the
  host is not in the network egress allowlist). All parsing is
  **content-anchored, not tag-anchored**.

## 2. Hierarchy

Maps cleanly onto the three-level `TitleRef → ChapterRef → SectionRef`
model with no ambiguity:

- `TitleRef` ↔ an ILCS chapter number, e.g. `"720"`.
- `ChapterRef` ↔ an Act number within that chapter, e.g. `"5"`.
- `SectionRef` ↔ a section number within that Act, exactly as Illinois
  writes it (may include a decimal suffix, e.g. `"9-2"` or `"9-2.1"`).
- A full citation `720 ILCS 5/9-2` decomposes into exactly these three
  pieces with nothing left over.

## 3. Citation format

- `720 ILCS 5/9-2` — a citation decomposes as `{chapter} ILCS {act}/{section}`.
- The adapter's `_CITATION` regex captures chapter, act, and section as
  separate groups for `normalize()`'s cross-check (stronger than a bare
  substring test).
- A trailing legacy-citation segment `(from Ch. 38, par. 9-2)` may follow
  the main citation.

## 4. Section discovery

- `list_titles()` fetches the ILCS root directory listing and enumerates
  chapter numbers (e.g. folders named `Ch 0720`).
- `list_chapters(title_ref)` fetches a chapter directory listing and
  enumerates act numbers (e.g. folders named `Act 0005`).
- `list_sections(chapter_ref)` fetches an act directory listing and
  enumerates section file names.
- **VERIFIED (content level)**: directory listings expose chapter/act
  *numbers* only — they carry no official display names.
- **LIMITATION**: `TocNode.name` for titles/chapters is a generic
  placeholder (e.g. `"Chapter 720"`, `"Act 5"`), not the state's official
  display name (e.g. "Criminal Offenses"). Fetching real names would
  require parsing an actual section or front-matter file per chapter/act,
  out of scope for a listing operation.
- **UNVERIFIED**: whether every existing ILCS chapter/act follows the
  `Ch NNNN` / `Act NNNN` directory shape uniformly.

## 5. Retrieval mechanism

- One static HTML file per section: `{BASE}/Ch%20{chapter}/Act%20{act}/
  {prefix}K{section}.html` (e.g. `/Ch%200720/Act%200005/072000050K9-2.html`).
- **VERIFIED** directly for `720 ILCS 5/9-2`.
- Chapter/act identifiers are zero-padded to 4 digits for the URL
  (`_zfill4`).

## 6. Parsing approach

- **Content-anchored, not tag-anchored**: every tag is stripped
  unconditionally (replaced with a single space, never the empty string)
  and whitespace is collapsed to single spaces (`strip_tags` with
  `preserve_block_breaks=False`). The adapter cannot reuse
  Washington's structural regexes because no Illinois tag structure is
  verified.
- **VERIFIED text shape** (for `720 ILCS 5/9-2`):
  - `(720 ILCS 5/9-2) (from Ch. 38, par. 9-2)`
  - `Sec. 9-2. Second degree murder.`
  - `[body text]`
  - `(Source: P.A. 100-460, eff. 1-1-18.)`
- **LIMITATION**: no paragraph fidelity is claimed — `StatuteSection.text`
  is a single whitespace-normalized blob (a known, accepted quality
  regression vs. Texas/Washington, which preserve paragraph breaks).

## 7. History/amendment extraction

- The trailing `(Source: ...)` block is captured as `amendment_notes`
  (e.g. `(Source: P.A. 100-460, eff. 1-1-18.)`).
- **UNVERIFIED**: whether every Illinois section has a trailing
  `(Source: ...)` line (repealed or blank-placeholder sections were not
  checked).

## 8. Identifier variants

- Section identifiers can carry a **decimal suffix** (e.g. `9-2.1`).
- **UNVERIFIED**: whether a heading can itself contain a period — the
  `_HEADING` pattern (`Sec. N. heading`) would truncate early if so (an
  accepted limitation matching TexasAdapter's analogous limitation).

## 9. Error handling

- `RefMismatchError`: if the parsed citation's chapter/act/section do not
  all match `ref` (verified via `_CITATION` groups).
- `NormalizationError`: if the citation or heading cannot be located, or
  if the body text between heading and history is empty.
- `AdapterUnavailableError`: network failure (via the shared `fetch_url`).
- `UnsupportedRefError`: `build_url` for an unsupported ref type.
- `status` is always `UNKNOWN` — no structural repealed/amended/renumbered
  signal distinct from prose has been observed.

## 10. Fixture provenance

- **No real Illinois fixture exists.** `tests/fixtures/
  illinois_720_ilcs_5_9-2.html` does not exist because ilga.gov is
  unreachable from this environment.
- Tests use a **hand-written synthetic mock** (documented as synthetic in
  `test_illinois_adapter.py`), whose content matches the independently
  verified real text for `720 ILCS 5/9-2` but whose markup/whitespace is
  invented for the test.
- The `TestRetrieveSectionRealFixture` class is skipped unless the real
  fixture file is dropped in — the 1 skip in the full suite.

## 11. Known limitations

1. Raw HTML tag structure UNVERIFIED — parsing is content-anchored.
2. No real fixture — host unreachable from this environment.
3. No paragraph fidelity (whitespace-normalized blob text).
4. Title/chapter names are generic placeholders (directory listing has no
   names).
5. Only one section fully verified end-to-end; section-shape uniformity
   otherwise UNVERIFIED.
6. Heading-with-period and missing-Source-line cases UNVERIFIED.

## 12. Architecture fit

**No framework change.** Illinois fits the existing three-level model and
the shared `fetch_url` → strip_tags pipeline. It is the project's
**static-directory/one-file-per-section HTML** family member. The
deliberately content-anchored (not tag-anchored) parsing is an accepted
state-specific trade-off, not a framework gap.