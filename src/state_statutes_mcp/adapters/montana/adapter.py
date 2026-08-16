"""MontanaAdapter: the Montana-specific concrete state adapter.

Source: the official Montana Code Annotated at
``https://mca.legmt.gov/bills/mca`` -- anonymous, server-rendered HTML
with no authentication or API key, live-reachable from this environment.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/montana.md``; verified against the live official host,
including real ``curl`` probes on Aug 16 2026):

* Base URL ``https://mca.legmt.gov/bills/mca``.
* The MCA has a real Title -> Chapter -> Section hierarchy matching the
  framework's three-level ref model exactly -- no synthetic-title
  workaround needed. Montana's Part level is folded into the published
  three-number citation and used only as URL routing (see below); it is
  absorbed adapter-internally and never exposed as a ref field.
* URL arithmetic (VERIFIED on 18 sampled rows): every path segment's
  code is ``code(n) = f"{n * 10:04d}"`` (title 1 -> ``0010``, chapter 11
  -> ``0110``, part 5 -> ``0050``, section-local 3 -> ``0030``). A
  section number ``S`` within a title/chapter is split into its Part and
  local-section components as ``part = S // 100`` and ``local = S % 100``
  (e.g. ``103`` -> part 1 / local 3; ``511`` -> part 5 / local 11;
  ``1001`` -> part 10 / local 1). ``SectionRef.identifier`` is the full
  three-number citation (e.g. ``"1-11-103"``, ``"2-6-1001"``,
  ``"45-5-511"``); the URL is derived arithmetically, never by string
  substitution.
* Section page: ``{BASE}/title_{code(T)}/chapter_{code(C)}/part_{code(part)}/
  section_{code(local)}/{code(T)}-{code(C)}-{code(part)}-{code(local)}.html``.
  Verified structure:
  * ``<div class="section-header">`` carries ``<h4 class="section-title-
    title">TITLE {T}. ...`` and ``<h3 class="section-chapter-title">CHAPTER
    {C}. ...`` -- the adapter cross-checks both against the ref chain.
  * ``<div class="section-content">`` holds ``<p class="line-indent">``
    paragraphs; the first paragraph opens with ``<span class="catchline">``
    containing the numbered-citation line ``<span class="citation">{T}-{C}-{S}</span>``
    (the cross-check citation) followed by the heading text.
  * A ``History:`` block (``<div class="history-doc">`` ->
    ``<div class="history-content">``) carries the session-law history.
* Discovery:
  * Titles: ``{BASE}/index.html``; each title is ``<a data-titlenumber="{n}"
    href="./title_{code}/chapters_index.html">TITLE {n}. ...``. Reserved
    titles render as plain-text ``<span class="reserved">`` rows with no
    link and are skipped. Title ``0`` is the Constitution (which uses
    ``article_`` URL segments) and is deliberately excluded.
  * Chapters: ``{BASE}/title_{code(T)}/chapters_index.html``; each chapter
    is ``<a href="./chapter_{code}/parts_index.html">CHAPTER {n}. ...``.
    Reserved chapter ranges render as plain-text ``<span class="reserved">``
    rows with no link and are skipped.
  * Sections: a two-hop aggregate. First ``{BASE}/title_{code(T)}/chapter_{code(C)}/
    parts_index.html`` lists the chapter's parts (``<a href="./part_{code}/
    sections_index.html">Part {n}. ...``); then each part's ``sections_index.html``
    lists its sections (``<a href="./section_{code}/..."><span class="citation">
    {T}-{C}-{S}</span> ...``). ``list_sections`` flattens every part's rows
    into one sequence. Renumbered and reserved-range rows are real TOC
    rows (e.g. ``45-5-505`` -> ``Renumbered 45-8-218``, ``45-5-509`` ->
    ``and 45-5-510 reserved``) and are returned as sections whose
    ``identifier`` is the first number of the range, matching how Montana
    keys the URL off that number.
* Repealed/reserved/renumbered sections (e.g. ``1-13-101`` repealed,
  ``1-13-104``/``1-13-106`` reserved, ``45-5-505`` renumbered) render a
  short prose catchline with no numbered subsections and, for reserved
  ranges, no ``History:`` line. Per the documented deviation (same
  decision as NebraskaAdapter/NorthCarolinaAdapter), such sections are
  returned with that note as the heading and empty text; the ``History:``
  line, when present (repealed sections), is carried in ``amendment_notes``.
* Citation: ``Mont. Code Ann. § {T}-{C}-{S}`` (the abbreviation is
  standard Montana legal-citation usage; the number is VERIFIED from the
  site's own citation spans).
* Encoding: UTF-8 (``<meta charset="utf-8">`` on section and 404 pages),
  so the shared UTF-8 ``fetch_url`` helper is used directly.

**HTTP 404 / missing-section behavior is LIVE-VERIFIED** (Aug 16 2026):
every deliberately nonexistent URL probed (a missing section under a
valid part, a nonexistent chapter, part, and title) returned a plain
HTTP 404 with zero redirects and a real 404 error page (``<title>404</title>``).
Because ``build_url`` computes the target deterministically from the ref,
``RefNotFoundError`` is reachable via ``build_url`` + fetch alone, with no
listing-based pre-check required. Network failures other than 404 map to
``AdapterUnavailableError`` (project convention; UNVERIFIED on Montana
specifically).
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

_SECTION_NUMBER = re.compile(r"^(\d+)-(\d+)-(\d+)$")


class MontanaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Montana Code Annotated at
    mca.legmt.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Montana's real Title ->
    Chapter -> Section hierarchy maps directly onto the framework's ref
    model; the Part level is adapter-internal URL routing only (derived
    arithmetically from the section number). See the module docstring.
    """

    BASE_URL = "https://mca.legmt.gov/bills/mca"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title row on the index page (index.html), e.g.
    # '<a data-titlenumber="1" href="./title_0010/chapters_index.html">
    # TITLE 1. GENERAL LAWS AND DEFINITIONS</a>'. Reserved titles are
    # plain-text <span class="reserved"> rows with no link and therefore
    # never match; the Constitution (data-titlenumber="0") is skipped by
    # identifier in list_titles.
    _TITLE_ROW = re.compile(
        r'<a data-titlenumber="(\d+)" href="\./title_\d{4}/chapters_index\.html"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    # A chapter row on a title's chapters_index.html, e.g.
    # '<a href="./chapter_0010/parts_index.html">CHAPTER 1. GENERAL
    # PRELIMINARY PROVISIONS</a>'. Reserved chapter ranges are plain-text
    # <span class="reserved"> rows with no link and never match. The
    # identifier is recovered from the code (e.g. "0010" -> "1").
    _CHAPTER_ROW = re.compile(
        r'<a href="\./chapter_(\d{4})/parts_index\.html"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    # A part row on a chapter's parts_index.html, e.g.
    # '<a href="./part_0010/sections_index.html">Part 1. Homicide</a>'.
    _PART_ROW = re.compile(
        r'<a href="\./part_(\d{4})/sections_index\.html"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    # A section row on a part's sections_index.html, e.g.
    # '<a href="./section_0010/0450-0050-0050-0010.html"><span
    # class="citation">45-5-501</span>&nbsp;Definitions</a>'. The
    # identifier is the citation text; renumbered rows carry names like
    # "Renumbered 45-8-218" and reserved ranges like "and 45-5-510 reserved".
    _SECTION_ROW = re.compile(
        r'<a href="\./section_\d{4}/[^"]+\.html"[^>]*>\s*'
        r'<span class="citation">([^<]+)</span>(.*?)</a>',
        re.DOTALL,
    )

    # The operative section-content region on a section page.
    _SECTION_CONTENT = re.compile(
        r'<div class="section-content">(.*?)</div>', re.DOTALL
    )

    # The numbered-citation line inside the first paragraph's catchline,
    # e.g. '<span class="citation">45-5-511</span>'.
    _CITATION = re.compile(r'<span class="citation">([^<]+)</span>')

    # The catchline span that opens the first body paragraph, e.g.
    # '<span class="catchline"><span class="citation">45-5-511</span>.
    # &#8195;Provisions generally applicable to sexual crimes.</span>'.
    _CATCHLINE = re.compile(
        r'<span class="catchline">(.*?)</span>', re.DOTALL
    )

    # A body paragraph, e.g. '<p class="line-indent">(1) When criminality
    # depends ...</p>'.
    _BODY_PARAGRAPH = re.compile(r'<p class="line-indent">(.*?)</p>', re.DOTALL)

    # The History (amendment) block, e.g. '<span class="header">History:
    # </span>&#8195;En. 12-506 by Sec. 6, Ch. 419, L. 1975; ...</p>'.
    _HISTORY = re.compile(
        r'<span class="header">History:</span>(.*?)</p>', re.DOTALL
    )

    # The section page's own title/chapter headers, used to cross-check the
    # ref chain: '<h4 class="section-title-title">TITLE 45. CRIMES</h4>'
    # and '<h3 class="section-chapter-title">CHAPTER 5. OFFENSES AGAINST
    # THE PERSON</h3>'.
    _TITLE_HEADER = re.compile(
        r'<h4 class="section-title-title">\s*TITLE\s+(\d+)', re.IGNORECASE
    )
    _CHAPTER_HEADER = re.compile(
        r'<h3 class="section-chapter-title">\s*CHAPTER\s+(\d+)', re.IGNORECASE
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Montana."""
        return "MT"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Montana."""
        return "Montana"

    # ------------------------------------------------------------
    # URL arithmetic
    # ------------------------------------------------------------

    @staticmethod
    def _code(number: int) -> str:
        """Encode an MCA number into its 4-digit URL code.

        ``code(n) = f"{n * 10:04d}"`` -- the single arithmetic rule that
        drives every path segment (title, chapter, part, local section).
        Examples: ``1 -> "0010"``, ``11 -> "0110"``, ``5 -> "0050"``,
        ``10 -> "0100"``.
        """
        return f"{number * 10:04d}"

    @staticmethod
    def _split_section_number(section_number: int) -> tuple[int, int]:
        """Split an MCA section number into its Part and local-section
        components.

        ``part = S // 100`` and ``local = S % 100``. Examples: ``103`` ->
        ``(1, 3)``; ``511`` -> ``(5, 11)``; ``1001`` -> ``(10, 1)``.
        """
        return section_number // 100, section_number % 100

    def _parse_section_identifier(self, identifier: str) -> tuple[int, int, int]:
        """Parse a section identifier like ``"45-5-511"`` into
        ``(title, chapter, section)`` integers.

        Raises:
            UnsupportedRefError: If ``identifier`` is not the three-part
                ``{t}-{c}-{s}`` form this adapter addresses (Montana has no
                lettered/decimal section identifiers).
        """
        match = _SECTION_NUMBER.match(identifier)
        if match is None:
            raise UnsupportedRefError(
                f"MontanaAdapter cannot address section {identifier!r}: MCA "
                "section identifiers are the three-part T-C-S citation form "
                "(e.g. '45-5-511')."
            )
        return tuple(int(part) for part in match.groups())

    def _guard_non_constitution(self, title_number: int, *, what: str) -> None:
        """Raise ``UnsupportedRefError`` for the Constitution (Title 0)."""
        if title_number == 0:
            raise UnsupportedRefError(
                f"MontanaAdapter cannot address {what}: MCA Title 0 is the "
                "Constitution, which uses 'article_' URL segments and is out "
                "of this adapter's scope."
            )

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Montana Code Annotated URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/montana.md):

        * Section: ``{BASE}/title_{code(T)}/chapter_{code(C)}/part_{code(part)}/
          section_{code(local)}/{code(T)}-{code(C)}-{code(part)}-{code(local)}.html``
          where the three-number citation is parsed from
          ``SectionRef.identifier`` and split as ``part = S // 100``,
          ``local = S % 100``.
        * Chapter: ``{BASE}/title_{code(T)}/chapter_{code(C)}/parts_index.html``
          -- the chapter's part-listing page (a chapter has no direct
          section listing; sections are reached through its parts).
        * Title: ``{BASE}/title_{code(T)}/chapters_index.html``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` addresses the Constitution
                (Title 0), or if a section identifier is not the three-part
                ``T-C-S`` form this adapter addresses.
        """
        if isinstance(ref, SectionRef):
            title_number, chapter_number, section_number = (
                self._parse_section_identifier(ref.identifier)
            )
            self._guard_non_constitution(
                title_number, what="section {ref.identifier!r}"
            )
            part, local = self._split_section_number(section_number)
            return (
                f"{self.BASE_URL}/title_{self._code(title_number)}/"
                f"chapter_{self._code(chapter_number)}/"
                f"part_{self._code(part)}/section_{self._code(local)}/"
                f"{self._code(title_number)}-{self._code(chapter_number)}-"
                f"{self._code(part)}-{self._code(local)}.html"
            )
        elif isinstance(ref, ChapterRef):
            title_number = int(ref.title.identifier)
            self._guard_non_constitution(
                title_number, what=f"chapter {ref.identifier!r}"
            )
            chapter_number = int(ref.identifier)
            return (
                f"{self.BASE_URL}/title_{self._code(title_number)}/"
                f"chapter_{self._code(chapter_number)}/parts_index.html"
            )
        elif isinstance(ref, TitleRef):
            self._guard_non_constitution(
                int(ref.identifier), what=f"title {ref.identifier!r}"
            )
            return (
                f"{self.BASE_URL}/title_{self._code(int(ref.identifier))}/"
                "chapters_index.html"
            )
        else:
            raise UnsupportedRefError(
                f"MontanaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into
        ``AdapterUnavailableError`` there. This method additionally maps a
        HTTP 404 into :class:`RefNotFoundError` -- the source was reached,
        but the addressed document does not resolve. Montana's plain-HTTP-404
        behavior is LIVE-VERIFIED (§13/§14 of the research doc); other
        network failures map to ``AdapterUnavailableError`` by project
        convention.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than an HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Montana Code Annotated site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Montana Code Annotated "
                    "site."
                ) from exc
            raise

    @classmethod
    def _clean(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return " ".join(strip_tags(html_fragment).split())

    @classmethod
    def _clean_row_name(cls, html_fragment: str) -> str:
        """Clean a row's name cell: strip tags and collapse whitespace."""
        return cls._clean(html_fragment)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Montana Code Annotated from the
        index page.

        The index page (``{BASE}/index.html``) lists every title as a row
        whose identifier is the title number and whose name is the title
        text. Reserved titles render as plain-text ``<span class="reserved">``
        rows with no link and are therefore skipped automatically; the
        Constitution (Title 0, which uses ``article_`` URL segments) is
        explicitly excluded by identifier.

        Returns:
            A sequence of :class:`TocNode`, one per active title, in
            document order. Each node's ``ref`` is a :class:`TitleRef`
            whose ``identifier`` is the title number.

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched,
                or if no usable title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/index.html"
        html = self._fetch_html(url, what="Montana title listing")

        titles = []
        seen: set[str] = set()
        for identifier, raw_name in self._TITLE_ROW.findall(html):
            if identifier == "0" or identifier in seen:
                continue
            seen.add(identifier)
            name = self._clean_row_name(raw_name)
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
                f"Fetched {url!r} but found no usable title rows in it; the "
                "site's structure may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title's
        chapters index.

        Each active chapter is ``<a href="./chapter_{code}/parts_index.html">
        CHAPTER {n}. ...``; reserved chapter ranges are plain-text
        ``<span class="reserved">`` rows with no link and are skipped
        automatically. The chapter identifier is the chapter number
        recovered from the URL code (e.g. ``"0010"`` -> ``"1"``).

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            UnsupportedRefError: If ``title_ref`` is the Constitution
                (Title 0).
            RefNotFoundError: If the chapters index returns HTTP 404 (the
                title does not resolve).
            AdapterUnavailableError: If the chapters index cannot be
                fetched for any other reason, or if no usable chapter rows
                could be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Montana chapter listing")

        chapters = []
        seen: set[str] = set()
        for code, raw_name in self._CHAPTER_ROW.findall(html):
            identifier = str(int(code) // 10)
            if identifier in seen:
                continue
            seen.add(identifier)
            name = self._clean_row_name(raw_name)
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
                f"Fetched {url!r} but found no usable chapter rows in it; "
                "the site's structure may have changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``, aggregated across
        the chapter's parts.

        Montana's chapter-level page is a part index, not a section index:
        ``list_sections`` first fetches the chapter's ``parts_index.html``,
        then fetches each part's ``sections_index.html``, and flattens every
        part's section rows into one sequence (deduplicated). Each section's
        identifier is its full ``{T}-{C}-{S}`` citation as Montana displays
        it in the link's citation span.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in discovery
            order (all parts, each part in document order). Each node's
            ``ref`` is a :class:`SectionRef` whose ``identifier`` is the
            full citation.

        Raises:
            UnsupportedRefError: If ``chapter_ref``'s title is the
                Constitution (Title 0).
            RefNotFoundError: If the parts index or a part's sections index
                returns HTTP 404.
            AdapterUnavailableError: If any listing cannot be fetched for
                any other reason, or if no usable section rows could be
                parsed from the chapter's parts.
        """
        parts_url = self.build_url(chapter_ref)
        parts_html = self._fetch_html(parts_url, what="Montana part listing")
        parts = self._PART_ROW.findall(parts_html)

        title_number = int(chapter_ref.title.identifier)
        self._guard_non_constitution(
            title_number, what=f"chapter {chapter_ref.identifier!r}"
        )
        chapter_number = int(chapter_ref.identifier)

        sections = []
        seen: set[str] = set()
        for part_code, _raw_name in parts:
            sections_url = (
                f"{self.BASE_URL}/title_{self._code(title_number)}/"
                f"chapter_{self._code(chapter_number)}/"
                f"part_{part_code}/sections_index.html"
            )
            sections_html = self._fetch_html(
                sections_url, what="Montana section listing"
            )
            for citation, raw_name in self._SECTION_ROW.findall(sections_html):
                if citation in seen:
                    continue
                seen.add(citation)
                name = self._clean_row_name(raw_name)
                sections.append(
                    TocNode(
                        level=HierarchyLevel.SECTION,
                        identifier=citation,
                        name=name,
                        ref=SectionRef(chapter=chapter_ref, identifier=citation),
                    )
                )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {parts_url!r} and its parts' section indexes but "
                f"found no usable section rows; chapter "
                f"{chapter_ref.identifier!r} either does not resolve or the "
                "site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Montana.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full ``{T}-{C}-{S}``
        citation, e.g. ``"45-5-511"``) must appear verbatim within
        ``parsed.raw_citation`` (the ``Mont. Code Ann. § 45-5-511``
        citation). The stronger cross-check against the source page's own
        citation span happens in :meth:`retrieve_section`.

        ``status`` is always left at its default (``UNKNOWN``): the Montana
        section pages carry no structural repealed/amended/renumbered
        signal (those states are identified only by prose catchlines, and
        the contract explicitly forbids inferring status from prose).

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Montana ref
                (``ref.state_code != "MT"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MontanaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Montana Code Annotated section, end
        to end: :meth:`build_url` -> fetch the section page -> cross-check
        the page's own citation span and title/chapter headers against
        ``ref`` -> parse the section into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/montana.md): the first body
        paragraph opens with a catchline span carrying the numbered
        citation line (``<span class="citation">{T}-{C}-{S}</span>``)
        followed by the heading; the body is the joined ``<p class="line-indent">``
        paragraphs; ``amendment_notes`` is the ``History:`` block's text.
        A repealed section (e.g. 1-13-101) has a ``Repealed`` catchline and
        no operative text but keeps its ``History:`` line; reserved
        sections (e.g. 1-13-104, 1-13-106) have no body and no ``History:``
        line; renumbered sections (e.g. 45-5-505) carry a ``Renumbered ...``
        catchline with no operative text. Per the documented deviation,
        these are returned with the note as the heading and empty text.

        Args:
            ref: The section to retrieve. Must be a Montana ref
                (``ref.state_code == "MT"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                section does not resolve; LIVE-VERIFIED for Montana).
            RefMismatchError: If the page's citation span or title/chapter
                headers disagree with ``ref``. Also raised by
                :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but the page is
                genuinely malformed (missing the section-content region,
                citation line, or catchline/heading), or the body is empty
                after cleaning for a section that is not a legitimate
                repealed/reserved/renumbered stub.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Montana section page")

        content = self._SECTION_CONTENT.search(html)
        if content is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "section-content region; the site's structure may have "
                "changed."
            )
        region = content.group(1)

        citation_match = self._CITATION.search(region)
        if citation_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no numbered "
                "citation line; the site's structure may have changed."
            )
        page_citation = citation_match.group(1).strip()
        if page_citation != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found on the fetched page: {page_citation!r}."
            )

        title_header = self._TITLE_HEADER.search(html)
        chapter_header = self._CHAPTER_HEADER.search(html)
        if title_header is None or chapter_header is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but the section page contained no title/chapter header; the "
                "site's structure may have changed."
            )
        if title_header.group(1) != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title on the fetched page: "
                f"{title_header.group(1)!r}."
            )
        if chapter_header.group(1) != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not "
                f"match the chapter on the fetched page: "
                f"{chapter_header.group(1)!r}."
            )

        paragraphs = self._BODY_PARAGRAPH.findall(region)
        if not paragraphs:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but the section page contained no body paragraphs; the "
                "site's structure may have changed."
            )

        first_paragraph = paragraphs[0]
        # Neutralize the nested citation span(s) inside the catchline so the
        # catchline regex can match its full extent (the catchline opens with
        # <span class="catchline"> and wraps one or two citation spans).
        neutralized_first = self._CITATION.sub(r"\1", first_paragraph)
        catchline_match = self._CATCHLINE.search(neutralized_first)
        if catchline_match is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but the first body paragraph contained no catchline/heading "
                "element; the site's structure may have changed."
            )
        catchline = self._clean(catchline_match.group(1))
        heading = self._clean_heading(catchline, ref.identifier)

        # The body is the first paragraph minus its catchline, plus the
        # remaining paragraphs.
        first_body = self._CATCHLINE.sub("", neutralized_first, count=1)
        body_parts = [first_body] + list(paragraphs[1:])
        text = "\n\n".join(self._clean(p) for p in body_parts).strip()

        amendment_notes = None
        history = self._HISTORY.search(html)
        if history is not None:
            amendment_notes = self._clean(history.group(1)) or None

        heading_lower = (heading or "").lower()
        is_stub = (
            heading_lower.startswith("repealed")
            or heading_lower.startswith("renumbered")
            or "reserved" in heading_lower
        )

        if is_stub:
            text = ""
        elif not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but its body text was empty after cleaning and its heading "
                "is not a legitimate repealed/reserved/renumbered stub; the "
                "section is likely empty or the site's structure has changed."
            )

        raw_citation = f"Mont. Code Ann. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    @classmethod
    def _clean_heading(cls, catchline: str, citation: str) -> str | None:
        """Strip the leading numbered-citation prefix from a cleaned
        catchline to yield the heading.

        E.g. ``"45-5-511. Provisions generally applicable to sexual
        crimes."`` -> ``"Provisions generally applicable to sexual
        crimes."``. A repealed/reserved/renumbered catchline becomes its
        short note (e.g. ``"1-13-101. Repealed."`` -> ``"Repealed."``).
        """
        heading = catchline
        if heading.startswith(citation):
            heading = heading[len(citation) :]
        heading = heading.lstrip(". ").strip()
        return heading or None
