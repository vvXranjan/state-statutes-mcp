"""FloridaAdapter: the Florida-specific concrete state adapter.

Source: the official Florida Senate publication of the Florida Statutes
at ``https://www.flsenate.gov/Laws/Statutes/`` — anonymous, server-rendered
HTML with no authentication or API key (jQuery for presentation only; no
SPA framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/florida.md``, which documents live requests to the
official host):

* Base URL ``https://www.flsenate.gov``. The Florida Statutes are
  published as distinct **per-year editions**; the site's edition selector
  offers 1997–2027, and ``/Laws/Statutes/{year}`` serves 200 for many of
  them. The site's default edition is 2025. This adapter pins the current
  published edition in :data:`DEFAULT_YEAR` as an **adapter-internal**
  constant: the year appears in every URL but never in the refs or the
  citation, and the MCP tools expose no version parameter.
* Titles: the home page (``/Laws/Statutes/``) lists 49 titles, each as a
  ``/Laws/Statutes/2025/Title{N}/#Title{N}`` link whose inner markup is
  ``<span class="title">Title I</span><span class="descript">CONSTRUCTION
  OF STATUTES </span>``. The identifier is the trailing ``N`` (``"1"`` …
  ``"49"``); the descriptive name is used as the display name.
* Chapters: a title page (e.g. ``/Laws/Statutes/2025/Title46``) lists that
  title's chapters as ``/Laws/Statutes/2025/Chapter{N}`` links whose inner
  markup is ``<span class="chTitle">Chapter 775</span><span
  class="chDescript">- GENERAL PENALTIES; ...</span>``. Chapter numbers are
  plain integers (no letter suffixes observed).
* Sections: a chapter has **no per-section page** — a request such as
  ``/Laws/Statutes/2025/Chapter775/Section775.01`` redirects to the
  statutes root (verified). The retrieval unit is the chapter's ``/All``
  document (``/Laws/Statutes/{year}/Chapter{N}/All``), which contains
  every section inline. Each section is one ``<div class="Section">``
  block (55 in Chapter 775's ``/All``, verified) headed by ``<span
  class="SectionNumber">775.01&#x2003;</span>`` (a trailing U+2003 em
  space, stripped here), followed by a catchline, a ``SectionBody``, and
  a ``History`` div. All 55 sampled sections carried both a
  ``SectionBody`` and a ``HistoryText`` (verified).
* Section markup (verified for § 775.01, § 775.021, § 775.15, and
  § 775.082):
  ``<span class="SectionNumber">775.01&#x2003;</span>``,
  ``<span class="Catchline"><span class="CatchlineText">Common law of
  England.</span>...</span>``, ``<span class="SectionBody">...</span>``,
  then ``<div class="History"><span class="HistoryTitle">History.</span>
  ...<span class="HistoryText">s. 1, Nov. 6, 1829; ...</span></div>``.
  Multi-paragraph sections carry ``<div class="Subsection">`` and nested
  ``<div class="Paragraph">`` blocks inside ``SectionBody``, so section
  boundaries are found by splitting on ``<div class="Section">`` — never
  by balancing ``<div>`` tags. A few sections carry an editorial ``<div
  class="Note">`` block after ``History`` (e.g. § 775.15); its text is
  appended to ``amendment_notes``.
* Citation: ``s. {chapter.section}, Fla. Stat.`` (e.g. ``s. 775.01, Fla.
  Stat.``), adapter-constructed. The chapter is part of the citation and
  of the section number, so ``SectionRef.identifier`` carries the full
  ``chapter.section`` number — the same convention ``WashingtonAdapter``
  and ``TexasAdapter`` use.

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef
model** (verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = the title number (e.g. ``"46"``).
* ``ChapterRef.identifier`` = the chapter number (e.g. ``"775"``).
* ``SectionRef.identifier`` = the full section number (e.g. ``"775.01"``).

The edition year is a publication dimension, not a structural level: it
never appears in the citation and carries no citable identity, so it is
absorbed as an adapter-internal URL constant — the same
"assume the current edition" convention Virginia documents for "the
current Code", now over a source that genuinely publishes per-year
editions.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/florida.md``): whether a formal rate-limit policy exists;
whether *every* chapter's ``/All`` document renders identically (sampled
Chapter 775 only); section-number uniqueness within a chapter (no
duplicates observed in Chapter 775); and exact 404 markup for a
nonexistent chapter (INFERENCE from server behavior). None of these block
the implementation below.
"""

from __future__ import annotations

import re
import urllib.error
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_url
from state_statutes_mcp.adapters._htmltext import strip_tags
from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection


class FloridaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Florida Senate publication
    of the Florida Statutes at flsenate.gov/Laws/Statutes.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by ``WashingtonAdapter``, ``TexasAdapter``,
    ``IllinoisAdapter``, ``VirginiaAdapter``, and ``DelawareAdapter``.
    See the module docstring for the verified site structure this adapter
    is built against.
    """

    BASE_URL = "https://www.flsenate.gov"
    # The current published edition of the Florida Statutes served by the
    # official site. VERIFIED (docs/research/florida.md): the site's
    # default edition is 2025, and 2026/2024/2023 also serve. This is an
    # ADAPTER-INTERNAL constant: it appears in every URL but never in the
    # refs or the citation, and the MCP tools expose no version parameter.
    # The adapter must be updated deliberately when a new edition becomes
    # the site's default — it does not pretend to serve historical
    # editions.
    DEFAULT_YEAR = "2025"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title link on the home page, e.g. "/Laws/Statutes/2025/Title1/#Title1".
    _TITLE_URL = re.compile(r"/Laws/Statutes/\d+/Title(\d+)", re.IGNORECASE)
    # A chapter link on a title page, e.g. "/Laws/Statutes/2025/Chapter775".
    _CHAPTER_URL = re.compile(r"/Laws/Statutes/\d+/Chapter(\d+)", re.IGNORECASE)
    # Any <a href="...">...</a> pair, used for the generic link scan.
    _LINK = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    # The descriptive title name, e.g. '<span class="descript">CONSTRUCTION OF STATUTES </span>'.
    _TITLE_DESCRIPT = re.compile(
        r'<span[^>]*class="descript"[^>]*>(.*?)</span>', re.DOTALL
    )
    # The Roman-numeral title label, e.g. '<span class="title">Title I</span>'.
    _TITLE_LABEL = re.compile(r'<span[^>]*class="title"[^>]*>(.*?)</span>', re.DOTALL)
    # "Title I" / "Title 46" -> strip the label prefix, leaving the name.
    _TITLE_NAME_PREFIX = re.compile(r"^Title\s+[IVXLCDM]+\.?\s*", re.IGNORECASE)
    # The chapter name, e.g. '<span class="chDescript">- GENERAL PENALTIES; ...</span>'.
    _CHAPTER_DESCRIPT = re.compile(
        r'<span[^>]*class="chDescript"[^>]*>(.*?)</span>', re.DOTALL
    )
    # A section block opening tag; blocks are split on this, so each chunk
    # holds exactly one section (nested Subsection/Paragraph divs included).
    _SECTION_BLOCK = re.compile(r'<div class="Section">')
    # The section's own number, e.g. '<span class="SectionNumber">775.01&#x2003;</span>'.
    _SECTION_NUMBER = re.compile(
        r'<span[^>]*class="SectionNumber"[^>]*>(.*?)</span>', re.DOTALL
    )
    # The catchline, e.g. '<span class="CatchlineText">Common law of England.</span>'.
    _CATCHLINE_TEXT = re.compile(
        r'<span[^>]*class="CatchlineText"[^>]*>(.*?)</span>', re.DOTALL
    )
    # The body container opening; the body is everything from here up to the
    # History div.
    _SECTION_BODY = re.compile(r'<span class="SectionBody">')
    # The history container opening; body extraction stops here.
    _HISTORY_DIV = re.compile(r'<div class="History">')
    # The amendment-history chain, e.g. '<span class="HistoryText">s. 1, Nov. 6, 1829; ...</span>'.
    _HISTORY_TEXT = re.compile(
        r'<span[^>]*class="HistoryText"[^>]*>(.*?)</span>', re.DOTALL
    )
    # An editorial note after the history, e.g. '<div class="Note">...Former ss. ...</div>'.
    _NOTE_DIV = re.compile(r'<div class="Note">(.*?)</div>', re.DOTALL)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Florida."""
        return "FL"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Florida."""
        return "Florida"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _chapter_all_url(self, title_identifier: str, chapter_identifier: str) -> str:
        """Build the verified URL of a chapter's ``/All`` document — the
        retrieval unit holding every section of the chapter inline."""
        return (
            f"{self.BASE_URL}/Laws/Statutes/{self.DEFAULT_YEAR}/"
            f"Chapter{chapter_identifier}/All"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Florida Statutes URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/florida.md):

        * Title: ``https://www.flsenate.gov/Laws/Statutes/{year}/Title{N}``.
        * Chapter: ``https://www.flsenate.gov/Laws/Statutes/{year}/Chapter{N}``
          (the chapter navigation shell).
        * Section: the parent chapter's ``/All`` document,
          ``.../Chapter{N}/All``. Sections have no per-section URL
          (verified redirect to the statutes root), so retrieval uses the
          containing document and matches the ``SectionNumber`` anchor
          after fetching.

        The pinned edition year is always ``DEFAULT_YEAR`` — it is
        adapter-internal and never part of any ref.

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
            return self._chapter_all_url(
                ref.chapter.title.identifier, ref.chapter.identifier
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/Laws/Statutes/{self.DEFAULT_YEAR}/"
                f"Chapter{ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return (
                f"{self.BASE_URL}/Laws/Statutes/{self.DEFAULT_YEAR}/"
                f"Title{ref.identifier}"
            )
        else:
            raise UnsupportedRefError(
                f"FloridaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into ``AdapterUnavailableError``
        there. This method additionally maps a verified HTTP 404 (e.g. an
        invalid chapter) into :class:`RefNotFoundError` — the source was
        reached, but the addressed document does not resolve.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than a verified HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Florida Statutes site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Florida Statutes site."
                ) from exc
            raise

    @classmethod
    def _link_identifier(cls, href: str, pattern: re.Pattern) -> str | None:
        """Return the identifier captured by ``pattern`` from ``href``, or
        None if the href is not of that shape."""
        match = pattern.search(href)
        return match.group(1) if match is not None else None

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Florida Statutes from the home page.

        The home page lists 49 titles, each as a ``Title{N}/#Title{N}``
        link. The identifier is the trailing number (``"1"`` … ``"49"``);
        the display name is the ``descript`` text with the ``Title N``
        label prefix stripped. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"46"``) and whose
            ``name`` is the title's descriptive name (e.g. ``"CRIMES"``).

        Raises:
            AdapterUnavailableError: If the home page cannot be fetched or
                no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/Laws/Statutes/"
        html = self._fetch_html(url, what="Florida statutes home page")

        titles = []
        seen: dict[str, None] = {}
        for href, inner in self._LINK.findall(html):
            identifier = self._link_identifier(href, self._TITLE_URL)
            if identifier is None or identifier in seen:
                continue
            seen[identifier] = None

            descript = self._TITLE_DESCRIPT.search(inner)
            name = (
                self._clean_inner(descript.group(1)) if descript is not None else None
            )
            if not name:
                label = self._TITLE_LABEL.search(inner)
                if label is not None:
                    name = self._TITLE_NAME_PREFIX.sub(
                        "", self._clean_inner(label.group(1))
                    ).strip()
            name = name or identifier

            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable title links in it; the "
                "site's structure may have changed."
            )

        return tuple(sorted(titles, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title page.

        Chapters are linked as ``Chapter{N}`` with a ``chDescript`` name
        (e.g. ``- GENERAL PENALTIES; REGISTRATION OF CRIMINALS``). The
        leading ``- `` is stripped from the display name, and the result
        is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"775"``) and
            whose ``name`` is the chapter name without the leading ``- ``.

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched
                for any other reason, or if no usable chapter links could
                be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Florida chapter listing")

        chapters = []
        seen: dict[str, None] = {}
        for href, inner in self._LINK.findall(html):
            identifier = self._link_identifier(href, self._CHAPTER_URL)
            if identifier is None or identifier in seen:
                continue
            seen[identifier] = None

            descript = self._CHAPTER_DESCRIPT.search(inner)
            name = (
                self._clean_inner(descript.group(1)).lstrip("-").strip()
                if descript is not None
                else None
            )
            name = name or identifier

            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter links in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter's
        ``/All`` document.

        The ``/All`` document contains every section of the chapter inline
        as ``<div class="Section">`` blocks (there is no per-section page).
        Each block's ``SectionNumber`` is the section identifier (e.g.
        ``"775.01"``) and its ``CatchlineText`` is the display name.

        Returns:
            A sequence of :class:`TocNode`, one per section, in
            deterministic numeric order, deduplicated on the
            ``SectionNumber``. Each node's ``ref`` is a
            :class:`SectionRef` whose ``identifier`` is the full
            ``chapter.section`` number (e.g. ``"775.01"``) and whose
            ``name`` is the catchline (e.g. ``"Common law of England."``).

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the ``/All`` document cannot be
                fetched for any other reason, or if no section blocks
                could be parsed from it.
        """
        url = self._chapter_all_url(
            chapter_ref.title.identifier, chapter_ref.identifier
        )
        html = self._fetch_html(url, what="Florida section listing")

        sections = []
        seen: dict[str, None] = {}
        for block in self._SECTION_BLOCK.split(html)[1:]:
            number = self._SECTION_NUMBER.search(block)
            if number is None:
                continue
            identifier = self._clean_inner(number.group(1))
            if not identifier or identifier in seen:
                continue
            seen[identifier] = None
            name = self._catchline(block) or identifier
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section blocks in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @classmethod
    def _catchline(cls, block: str) -> str | None:
        """Return the stripped ``CatchlineText`` of one section block, or
        None if the block has no catchline."""
        match = cls._CATCHLINE_TEXT.search(block)
        if match is None:
            return None
        return cls._clean_inner(match.group(1))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title, chapter, and
        section identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any dotted suffix — the same convention ``VirginiaAdapter`` and
        ``DelawareAdapter`` use — so ``1, 2, 46, 49`` and ``775.01,
        775.021, 775.082`` order sensibly regardless of document order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Florida.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the full section number, e.g. ``"775.01"``)
        appears verbatim within ``raw_citation`` (the ``s. 775.01, Fla.
        Stat.`` citation). ``status`` is always left at its default
        (``UNKNOWN``): nothing verified about the Florida source provides a
        structural repealed/amended/renumbered signal, and the contract
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Florida ref
                (``ref.state_code != "FL"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"FloridaAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )

        if ref.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the parsed document: "
                f"{parsed.raw_citation!r}."
            )

        citation = Citation(
            state_code=self.state_code,
            raw=parsed.raw_citation,
        )

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
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Florida Statutes section, end to
        end: :meth:`build_url` -> fetch the parent chapter's ``/All``
        document -> locate the ``<div class="Section">`` block whose
        ``SectionNumber`` equals ``ref.identifier`` -> parse the block into
        a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED that sections have no per-section URL, so the chapter
        ``/All`` document is the single starting point; the section is
        matched by its ``SectionNumber`` anchor within that document.

        Args:
            ref: The section to retrieve. Must be a Florida ref
                (``ref.state_code == "FL"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the ``/All`` document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the chapter ``/All`` document returns HTTP
                404, or if no section block holds a ``SectionNumber``
                matching ``ref.identifier``.
            RefMismatchError: Raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but its body is
                empty after cleaning (the empty-body convention
                ``VirginiaAdapter`` and ``DelawareAdapter`` use). Also
                raised by :meth:`normalize` if ``ref`` is not a Florida
                ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Florida chapter All document")

        block = self._block_for_section(html, ref.identifier)
        if block is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but found no section matching "
                f"{ref.identifier!r} in it; the section does not resolve on "
                "the Florida Statutes site."
            )

        heading, text, amendment_notes = self._parse_section_block(
            block, ref.identifier, document_url=url
        )

        parsed = ParsedDocument(
            raw_citation=f"s. {ref.identifier}, Fla. Stat.",
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    @classmethod
    def _block_for_section(cls, html: str, identifier: str) -> str | None:
        """Return the section block whose ``SectionNumber`` equals
        ``identifier``, or None if there is no such block.

        The document is split on ``<div class="Section">`` openings so each
        chunk holds exactly one section's markup — including its nested
        ``Subsection``/``Paragraph`` divs (verified for § 775.082, whose
        block contains 78 nested ``<div>`` opens) — so section boundaries
        never depend on balancing ``<div>`` tags.
        """
        for part in cls._SECTION_BLOCK.split(html)[1:]:
            number = cls._SECTION_NUMBER.search(part)
            if number is not None and cls._clean_inner(number.group(1)) == identifier:
                return part
        return None

    @classmethod
    def _parse_section_block(
        cls, block: str, identifier: str, *, document_url: str
    ) -> tuple[str, str, str | None]:
        """Parse one section block into ``(heading, text, amendment_notes)``.

        Args:
            block: The inner HTML of one ``<div class="Section">`` block.
            identifier: The expected section number.
            document_url: The URL the block came from (for error messages).

        Returns:
            A ``(heading, text, amendment_notes)`` triple. ``heading`` is
            the ``CatchlineText`` (or None); ``text`` is the ``SectionBody``
            cleaned with paragraph breaks (subsections and paragraphs
            separated by a blank line); ``amendment_notes`` is the
            ``HistoryText`` chain verbatim, with any editorial ``Note``
            text appended, or None.

        Raises:
            NormalizationError: If the block has no ``SectionNumber``, its
                number disagrees with ``identifier``, or its body is empty
                after cleaning.
        """
        number = cls._SECTION_NUMBER.search(block)
        if number is None:
            raise NormalizationError(
                f"Fetched {document_url!r} and located section {identifier!r}, "
                "but its Section block contained no SectionNumber element; the "
                "site's structure may have changed."
            )
        if cls._clean_inner(number.group(1)) != identifier:
            raise NormalizationError(
                f"Fetched {document_url!r} and located a Section block, but its "
                f"SectionNumber {cls._clean_inner(number.group(1))!r} does not "
                f"match the requested section {identifier!r}; the site's "
                "structure may have changed."
            )

        heading = cls._catchline(block)

        body_start = cls._SECTION_BODY.search(block)
        if body_start is None:
            raise NormalizationError(
                f"Fetched {document_url!r} and located section {identifier!r}, "
                "but its Section block contained no SectionBody element; the "
                "site's structure may have changed."
            )

        body_html = block[body_start.end() :]
        history_match = cls._HISTORY_DIV.search(body_html)
        if history_match is not None:
            body_html = body_html[: history_match.start()]

        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {document_url!r} and located section {identifier!r}, "
                "but its body text was empty after cleaning; the section is "
                "likely a repealed/empty section or the site's structure has "
                "changed."
            )
        text = "\n\n".join(line for line in text.split("\n"))

        amendment_notes = None
        history = cls._HISTORY_TEXT.search(block)
        if history is not None:
            amendment_notes = cls._clean_inner(history.group(1)) or None
        note = cls._NOTE_DIV.search(block)
        if note is not None:
            note_text = cls._clean_inner(note.group(1))
            if note_text:
                amendment_notes = (
                    f"{amendment_notes}\n{note_text}"
                    if amendment_notes
                    else note_text
                )

        return heading, text, amendment_notes
