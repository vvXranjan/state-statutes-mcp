"""IllinoisAdapter: the Illinois-specific concrete state adapter.

Source: the Illinois General Assembly's static ILCS mirror,
https://www.ilga.gov/ftp/ILCS/. Unlike Washington and Texas, this
adapter's parsing strategy is deliberately **content-anchored, not
tag-anchored**: no HTML tag name, class, id, or DOM structure for the
Illinois source has been directly verified (the fetch tooling
available in this project's research sessions returns cleaned/
extracted text, never raw response bytes, and this sandbox's network
egress allowlist does not include ilga.gov, so a direct raw-bytes
fetch was not possible either). What *has* been independently
verified, twice, via real fetches of the real URL, is the exact
*text content and its order* for one representative section. See each
method's docstring below for a strict VERIFIED / UNVERIFIED /
IMPLEMENTATION DECISION breakdown -- this module does not blur the
two the way inventing a plausible-looking tag structure would.

Because nothing about Illinois's tags is known, this adapter cannot
reuse ``WashingtonAdapter``'s structural-extraction regexes
(``_CITATION_H1``, ``_BODY_PARAGRAPH_DIV``, etc.) -- those are
correctly anchored to Washington's specific, separately-confirmed
markup and would either silently match nothing on an Illinois page or,
worse, match something unrelated. This adapter instead strips *all*
tags unconditionally (replacing each with a space, not the empty
string, specifically to avoid jamming two words together across a
removed tag boundary) and locates citation/heading/body/history purely
by matching the literal confirmed text patterns.

Explicit, deliberate scope limits (do not read past this list to infer
more was attempted):

* **No paragraph fidelity is claimed.** Blanket tag-stripping cannot
  tell a real paragraph break from a mid-sentence line wrap without
  knowing whether the source uses ``<p>``/``<div>`` boundaries for
  either -- that's exactly the tag knowledge this adapter doesn't
  have. ``StatuteSection.text`` here is a single whitespace-normalized
  blob. This is a known, accepted quality regression versus
  ``TexasAdapter`` and ``WashingtonAdapter`` (both of which do
  preserve paragraph breaks, because both do have confirmed tag
  structure to key off of), not an oversight.
* **No chapter/act *names* are populated.** The only source consulted
  for ``list_titles``/``list_chapters`` is the plain directory
  listing, which exposes chapter and act *numbers* only (e.g. a
  folder literally named ``Ch 0720``) -- it does not carry a chapter's
  or act's official display name (e.g. "Criminal Offenses"). Getting
  real names would mean fetching and parsing an actual section or
  front-matter (``F.html``) file per chapter/act, which is out of
  scope for a listing operation. ``TocNode.name`` for titles/chapters
  is therefore a generic placeholder (``"Chapter 720"``, ``"Act
  5"``), explicitly not the state's own display name -- see each
  method's docstring.
* **No chapter/act TOC page's raw structure is verified either** --
  only its content-level shape (a plain-text directory listing
  containing literal ``Ch NNNN`` / ``Act NNNN`` / filename tokens),
  confirmed via real fetches of three different listing pages during
  research. Same content-anchored-not-tag-anchored caveat as section
  retrieval.

Mapping to the framework's three-level
TitleRef -> ChapterRef -> SectionRef hierarchy
(state_statutes_mcp.models.refs) -- this is the one part of Illinois
that fits the existing model with no ambiguity or unmodeled level,
unlike New York or Michigan:

* ``TitleRef`` <-> an ILCS chapter number, e.g. ``"720"``.
* ``ChapterRef`` <-> an Act number within that chapter, e.g. ``"5"``.
* ``SectionRef`` <-> a section number within that Act, exactly as
  Illinois writes it (may include a decimal suffix, e.g. ``"9-2"`` or
  ``"9-2.1"``).
* A full citation ``720 ILCS 5/9-2`` decomposes into exactly these
  three pieces with nothing left over.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_url
from state_statutes_mcp.adapters._htmltext import strip_tags
from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection


class IllinoisAdapter(BaseStateAdapter):
    """Concrete state adapter for the Illinois Compiled Statutes (ILCS)
    static mirror at https://www.ilga.gov/ftp/ILCS/.

    Identity and all five of ``BaseStateAdapter``'s abstract methods
    are implemented, plus an adapter-owned ``retrieve_section``
    convenience method (not part of the abstract contract), mirroring
    the shape already established by ``WashingtonAdapter`` and
    ``TexasAdapter``. See the module docstring for the
    content-anchored-not-tag-anchored parsing strategy this adapter
    uses and exactly why.
    """

    BASE_URL = "https://www.ilga.gov/ftp/ILCS"
    DEFAULT_TIMEOUT_SECONDS = 30

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Illinois."""
        return "IL"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Illinois."""
        return "Illinois"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------
    #
    # VERIFIED (re-fetched independently, twice, this session):
    #   https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/072000050K9-2.html
    #   resolves to real content for 720 ILCS 5/9-2.
    # VERIFIED (real directory listings fetched for 6 different
    #   chapter/act combinations during research: 720/5, 750/5, 770/60,
    #   215/120, 820/115, 20/65):
    #   the "Ch {chapter.zfill(4)}/Act {act.zfill(4)}/" directory shape,
    #   and the "{chapter.zfill(4)}{act.zfill(4)}0" file-prefix formula
    #   (confirmed identical across all 6 examples -- the trailing "0"
    #   is consistent everywhere observed, though its meaning is
    #   undocumented anywhere found).
    # UNVERIFIED: whether every existing ILCS chapter/act follows this
    #   exact formula with zero exceptions (6 examples is a sample, not
    #   an exhaustive check).

    @staticmethod
    def _zfill4(identifier: str) -> str:
        """Zero-pad a chapter or act identifier to 4 digits for use in
        a URL path segment, e.g. ``"720"`` -> ``"0720"``,
        ``"5"`` -> ``"0005"``. Confirmed shape -- see class-level
        comment above.
        """
        return identifier.strip().zfill(4)

    def _act_dir_url(self, chapter_ref: ChapterRef) -> str:
        """The directory-listing URL for one Act within one ILCS
        chapter, e.g. ``.../Ch%200720/Act%200005/``. VERIFIED shape.
        """
        chapter = self._zfill4(chapter_ref.title.identifier)
        act = self._zfill4(chapter_ref.identifier)
        return f"{self.BASE_URL}/Ch%20{chapter}/Act%20{act}/"

    def _file_prefix(self, chapter_ref: ChapterRef) -> str:
        """The 9-digit filename prefix shared by every file under one
        chapter/act directory, e.g. ``"072000050"`` for chapter 720,
        act 5. VERIFIED formula -- see class-level comment above.
        """
        chapter = self._zfill4(chapter_ref.title.identifier)
        act = self._zfill4(chapter_ref.identifier)
        return f"{chapter}{act}0"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the ilga.gov ILCS URL for ``ref``.

        * Title (ILCS chapter): the chapter's directory-listing URL,
          ``.../Ch%20{chapter}/``. VERIFIED to be a real, fetchable
          listing page (fetched directly for several chapters during
          research), though its raw HTML is not tag-verified -- see
          module docstring.
        * Chapter (ILCS act): the act's directory-listing URL,
          ``.../Ch%20{chapter}/Act%20{act}/``. Same verification level
          as above.
        * Section: the section's own file,
          ``.../Ch%20{chapter}/Act%20{act}/{prefix}K{section}.html``.
          VERIFIED directly for 720 ILCS 5/9-2 -- real content
          returned, not a redirect or shell page.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a
                :class:`TitleRef`, :class:`ChapterRef`, or
                :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            act_dir = self._act_dir_url(ref.chapter)
            prefix = self._file_prefix(ref.chapter)
            return f"{act_dir}{prefix}K{ref.identifier}.html"
        elif isinstance(ref, ChapterRef):
            return self._act_dir_url(ref)
        elif isinstance(ref, TitleRef):
            chapter = self._zfill4(ref.identifier)
            return f"{self.BASE_URL}/Ch%20{chapter}/"
        else:
            raise UnsupportedRefError(
                f"IllinoisAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------
    #
    # Both list_titles and list_chapters parse a plain-text directory
    # listing for literal "Ch NNNN" / "Act NNNN" folder-name tokens.
    # VERIFIED at the content level (these exact tokens were observed
    # in real fetched listings for /ftp/ILCS/ itself and for several
    # chapter-level listings). UNVERIFIED at the tag level -- same
    # caveat as everywhere else in this module. IMPLEMENTATION
    # DECISION: chapter/act *names* are not available from a directory
    # listing at all (only numbers), so TocNode.name here is a
    # generic, explicitly-not-official placeholder -- see module
    # docstring.

    _CHAPTER_DIR = re.compile(r"\bCh\s+(\d{4})\b")
    _ACT_DIR = re.compile(r"\bAct\s+(\d{4})\b")

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every ILCS chapter folder found in the top-level
        directory listing at ``https://www.ilga.gov/ftp/ILCS/``.

        Returns:
            A sequence of :class:`TocNode`, one per distinct chapter
            number found, in the order first encountered on the page.
            Each node's ``name`` is a generic ``"Chapter {N}"`` label
            -- Illinois's own display name for the chapter (e.g.
            "Criminal Offenses") is not available from this listing
            and is not populated; see module docstring.

        Raises:
            AdapterUnavailableError: If the listing page cannot be
                fetched, or if it was fetched but no ``Ch NNNN`` token
                could be found in it.
        """
        url = f"{self.BASE_URL}/"
        text = self._fetch_text(url)

        seen: dict[str, None] = {}
        for match in self._CHAPTER_DIR.finditer(text):
            padded = match.group(1)
            identifier = str(int(padded))
            seen.setdefault(identifier, None)

        if not seen:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no 'Ch NNNN' chapter folder "
                "tokens in it; the listing's structure may have changed."
            )

        return tuple(
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=identifier,
                name=f"Chapter {identifier}",
                ref=TitleRef(state_code=self.state_code, identifier=identifier),
            )
            for identifier in seen
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every Act folder found in the directory listing
        for ILCS chapter ``title_ref``.

        Returns:
            A sequence of :class:`TocNode`, one per distinct act
            number found. Each node's ``name`` is a generic
            ``"Act {N}"`` label for the same reason described in
            :meth:`list_titles`.

        Raises:
            AdapterUnavailableError: If the listing page cannot be
                fetched, or if it was fetched but no ``Act NNNN`` token
                could be found in it.
        """
        url = self.build_url(title_ref)
        text = self._fetch_text(url)

        seen: dict[str, None] = {}
        for match in self._ACT_DIR.finditer(text):
            padded = match.group(1)
            identifier = str(int(padded))
            seen.setdefault(identifier, None)

        if not seen:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no 'Act NNNN' act folder "
                f"tokens in it; either chapter {title_ref.identifier!r} "
                "does not resolve, or the listing's structure has changed."
            )

        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=identifier,
                name=f"Act {identifier}",
                ref=ChapterRef(title=title_ref, identifier=identifier),
            )
            for identifier in seen
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section file found in the directory listing
        for one Act.

        Matches only filenames of the confirmed shape
        ``{prefix}K{section}.html`` -- this deliberately excludes the
        confirmed non-section files also present in the same listing
        (``{prefix}F.html`` front matter, ``{prefix}HArt. N.html`` /
        ``{prefix}HPt. N.html`` article/part heading stubs).

        Returns:
            A sequence of :class:`TocNode`, one per section file
            found, numerically sorted by section identifier (the raw
            listing's own order is lexicographic on the filename
            string, e.g. ``K1, K10, K11, ... K2, K20`` -- confirmed
            during research -- so this method re-sorts rather than
            trusting listing order). Each node's ``name`` is just its
            own identifier, since a section's real statutory heading
            is not available from a directory listing without
            fetching every individual file, which is out of scope for
            a listing operation.

        Raises:
            AdapterUnavailableError: If the listing page cannot be
                fetched, or if it was fetched but no matching
                ``{prefix}K...html`` filename could be found in it.
        """
        url = self.build_url(chapter_ref)
        text = self._fetch_text(url)
        prefix = self._file_prefix(chapter_ref)

        section_file = re.compile(re.escape(prefix) + r"K([\w.-]+)\.html")

        seen: dict[str, None] = {}
        for match in section_file.finditer(text):
            seen.setdefault(match.group(1), None)

        if not seen:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no '{prefix}K....html' section "
                f"files in it; either act {chapter_ref.identifier!r} under "
                f"chapter {chapter_ref.title.identifier!r} does not resolve, "
                "or the listing's structure has changed."
            )

        def _sort_key(identifier: str) -> tuple:
            # Numeric-first sort on the leading integer, falling back
            # to the raw string for any decimal/letter suffix, so
            # "9-2" and "9-2.1" and "10" sort in a sensible order
            # rather than the listing's lexicographic one.
            leading = re.match(r"\d+", identifier)
            return (int(leading.group()) if leading else 0, identifier)

        return tuple(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=identifier,
                name=identifier,
                ref=SectionRef(chapter=chapter_ref, identifier=identifier),
            )
            for identifier in sorted(seen, key=_sort_key)
        )

    # ------------------------------------------------------------
    # Content-anchored citation / heading / history patterns
    # ------------------------------------------------------------
    #
    # VERIFIED (re-fetched independently, twice, this session, for
    # 720 ILCS 5/9-2 specifically):
    #   (720 ILCS 5/9-2) (from Ch. 38, par. 9-2)
    #   Sec. 9-2. Second degree murder.
    #   [body text]
    #   (Source: P.A. 100-460, eff. 1-1-18.)
    #
    # UNVERIFIED: whether every Illinois section follows this exact
    # shape with no variation -- only one section has been directly,
    # fully verified end to end. In particular: whether the "(from
    # Ch. ...)" legacy-citation segment is present/absent by a
    # predictable rule (only one example checked, with it present);
    # whether a heading can itself contain a period (the pattern below
    # would truncate early if so -- an accepted limitation, matching
    # TexasAdapter's own analogous limitation); whether every section
    # has a trailing "(Source: ...)" line at all (repealed or
    # blank-placeholder sections were not checked).

    # Matches "(720 ILCS 5/9-2)" with an optional trailing
    # "(from Ch. 38, par. 9-2)" -- requirement 8. Captures chapter,
    # act, section as separate groups for normalize()'s cross-check.
    _CITATION = re.compile(
        r"\((\d+)\s+ILCS\s+([\w.]+)/([\w.-]+)\)(?:\s*\(from[^)]*\))?"
    )

    # Matches "Sec. 9-2. Second degree murder." -- heading text is
    # everything up to the next period, matching the one confirmed
    # example. Does not attempt to handle a heading that itself
    # contains a period (see UNVERIFIED note above).
    _HEADING = re.compile(r"Sec\.\s*([\w.-]+)\.\s*([^.]+)\.\s")

    # Matches a trailing "(Source: ...)" block. Anchored loosely
    # (search, not $-anchored) since this adapter does not claim to
    # know whether trailing chrome could follow it in the raw
    # (unstripped-of-nav) file -- see module docstring's "no raw HTML
    # verified" caveat. In one-file-per-section Illinois, there is no
    # "next section" to accidentally include the way there was for
    # chapter-file Texas.
    _HISTORY = re.compile(r"\(Source:.*?\)", re.DOTALL)

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Illinois.

        Re-parses ``parsed.raw_citation`` with :data:`_CITATION` and
        cross-checks all three of chapter, act, and section against
        ``ref`` -- a stronger check than a bare substring test, made
        possible because the citation format cleanly decomposes into
        exactly the three pieces the ref model already has slots for
        (see module docstring).

        ``status`` is always left at its default (``UNKNOWN``): no
        structural repealed/amended/renumbered signal distinct from
        prose has been observed (or looked for) in the one section
        checked.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Illinois ref, or
                if ``parsed.raw_citation`` does not match the expected
                ``(NNN ILCS NNN/N-N)`` shape at all.
            RefMismatchError: If ``parsed.raw_citation`` matches that
                shape but its chapter, act, or section disagrees with
                ``ref``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"IllinoisAdapter.normalize cannot normalize a ref for "
                f"state {ref.state_code!r}; expected {self.state_code!r}."
            )

        match = self._CITATION.search(parsed.raw_citation)
        if match is None:
            raise NormalizationError(
                f"raw_citation {parsed.raw_citation!r} does not match the "
                "expected '(NNN ILCS NNN/N-N)' shape."
            )

        chapter, act, section = match.groups()
        expected = (ref.chapter.title.identifier, ref.chapter.identifier, ref.identifier)
        if (chapter, act, section) != expected:
            raise RefMismatchError(
                f"Requested {ref.chapter.title.identifier} ILCS "
                f"{ref.chapter.identifier}/{ref.identifier} does not match "
                f"the citation found in the parsed document: "
                f"{parsed.raw_citation!r} (parsed as {chapter} ILCS "
                f"{act}/{section})."
            )

        citation = Citation(state_code=self.state_code, raw=parsed.raw_citation)

        return StatuteSection(
            ref=ref,
            citation=citation,
            heading=parsed.heading,
            text=parsed.text,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors WashingtonAdapter.retrieve_section
    # and TexasAdapter.retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Illinois statute section, end to
        end: :meth:`build_url` -> fetch that section's own file
        (Illinois is one-file-per-section, so no anchor-boundary logic
        is needed the way Texas's chapter-file model required) ->
        locate citation/heading/body/history purely by content, not
        tags -> :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be an Illinois ref;
                enforced by :meth:`normalize`, not this method
                directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section file cannot be
                fetched.
            NormalizationError: If the citation or heading cannot be
                located in the fetched content at all, or if the body
                text between heading and history is empty. Also raised
                by :meth:`normalize` if ``ref`` is not an Illinois ref
                or the citation shape doesn't match at all.
            RefMismatchError: Raised by :meth:`normalize` if the
                parsed citation's chapter/act/section disagrees with
                ``ref``.
        """
        url = self.build_url(ref)
        text = self._fetch_text(url)

        citation_match = self._CITATION.search(text)
        if citation_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but found no '(NNN ILCS NNN/N-N)' "
                "citation in it; either the section no longer resolves or "
                "the site's content shape has changed since this parser "
                "was written."
            )
        raw_citation = citation_match.group(0)

        heading_match = self._HEADING.search(text, citation_match.end())
        if heading_match is None:
            raise NormalizationError(
                f"Fetched {url!r} and found a citation, but no "
                "'Sec. N-N. HEADING.' heading followed it; the site's "
                "content shape may have changed since this parser was "
                "written."
            )
        heading = heading_match.group(2).strip()

        body_start = heading_match.end()
        history_match = self._HISTORY.search(text, body_start)
        if history_match is not None:
            body_text = text[body_start : history_match.start()].strip()
            amendment_notes = history_match.group(0).strip()
        else:
            body_text = text[body_start:].strip()
            amendment_notes = None

        if not body_text:
            raise NormalizationError(
                f"Fetched {url!r} and found the heading for section "
                f"{ref.identifier!r}, but its body text was empty; the "
                "site's content shape has likely changed since this "
                "parser was written."
            )

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=body_text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    # ------------------------------------------------------------
    # Shared fetch/clean helper
    # ------------------------------------------------------------

    def _fetch_text(self, url: str) -> str:
        """Fetch ``url`` and return its content as tag-stripped,
        entity-decoded, whitespace-normalized plain text.

        Deliberately blanket and tag-agnostic (see module docstring):
        every tag is replaced with a single space -- never the empty
        string, specifically to avoid jamming two words together
        across a removed tag boundary -- and all whitespace, including
        any original newlines, is collapsed to single spaces. This
        means paragraph breaks are NOT preserved; see module docstring
        for why that trade-off is accepted here rather than fixed.

        Delegates to the shared
        :func:`~state_statutes_mcp.adapters._htmltext.strip_tags`
        helper with ``preserve_block_breaks=False``.

        Args:
            url: The URL to fetch.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be fetched
                (network failure, non-2xx HTTP response).
        """
        return strip_tags(
            fetch_url(
                url,
                what="Illinois source",
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )
        )