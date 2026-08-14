"""DelawareAdapter: the Delaware-specific concrete state adapter.

Source: the official Delaware Code site at ``https://delcode.delaware.gov/``
— anonymous, server-rendered HTML with no authentication or API key. The
site is maintained by the Delaware Code Revisors with the editorial staff
of LexisNexis in cooperation with the Division of Legislative Services of
the General Assembly, and its Title 11 PDF describes itself as "an official
version of the State of Delaware statutory code."

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/delaware.md``,
which documents live requests to the official host):

* Base URL ``https://delcode.delaware.gov/``. The home page lists 31
  titles, each linked as ``title{N}/index.html`` next to an "Authenticated
  PDF" link that must be ignored.
* Titles: ``/title{N}/index.html`` lists a title's chapters as links of the
  form ``.../title11/c001/index.html``, ``.../title11/c084a/index.html`` —
  zero-padded three-digit chapter ids with optional letter suffixes for
  inserted chapters. The page also groups chapters under ``Part`` headings,
  which are presentation only and flattened away here (the same flattening
  pattern Virginia applies to Article/SubPart and Texas to internal title
  headings).
* Chapters have one of two shapes (both verified): a chapter may render
  sections inline on the chapter page (``c001`` renders ``id="101"``,
  ``102``, ``103`` with no subchapters), or it may split into subchapters
  (``c005`` links ``sc01``–``sc07`` with **no** inline sections). Subchapter
  pages live at ``/title{N}/cXXX/scYY/index.html``.
* Sections are **NOT individually addressable by URL** — a direct request
  such as ``/title11/c005/sc01/501.html`` returns HTTP 404 (verified). The
  retrieval unit is the containing document (the chapter page when the
  chapter has no subchapters, otherwise the subchapter page), and a section
  is matched by its ``SectionHead`` anchor ``id`` (the bare section number,
  e.g. ``"501"``). Section numbers are unique within a title.
* Section markup (verified for § 501 and § 101): each section is a
  ``<div class="Section">`` block (a ``<br>`` separates adjacent blocks)
  headed by ``<div class="SectionHead" id="501">§ 501. ...heading...</div>``,
  followed by ``<p class="subsection">`` (and ``<p class="indent-2">``)
  body paragraphs, followed by an inline trailing amendment-history chain
  whose entries are session-law hyperlinks, e.g.
  ``11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1; ...``.
* Citation: ``11 Del. C. § {section}`` — Title, "Del. C.", section number.
  The subchapter is not part of the citation.
* Reserved/range blocks exist and are VERIFIED: e.g.
  ``<div class="SectionHead" id="504-510">§§ 504-510. [Reserved.]</div>``
  with no body paragraphs. These are preserved in listings exactly as the
  site presents them (a single ``504-510`` entry, not one per covered
  number); retrieving one yields an empty body, which raises
  ``NormalizationError`` — the same empty-body convention
  ``VirginiaAdapter`` uses.
* Not found: an invalid chapter (``/title11/c999/index.html``) returns HTTP
  404; a section number with no matching ``SectionHead`` anchor is simply
  absent from a 200 page. Both map to ``RefNotFoundError`` here.

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef model**
(verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = the title number (e.g. ``"11"``).
* ``ChapterRef.identifier`` = the chapter number with leading zeros
  stripped and any letter suffix lower-cased (``c005`` -> ``"5"``,
  ``c084a`` -> ``"84a"``, ``c087a`` -> ``"87a"``).
* ``SectionRef.identifier`` = the ``SectionHead`` anchor id (e.g.
  ``"501"``), which is already the section number used in the citation.

The fourth level (Subchapter) carries no citable identity, so it is fully
absorbed as an adapter-internal discovery/retrieval detail — the same
flattening pattern already proven by Virginia (Article/SubPart) and Texas
(internal title headings), now exercised over a genuine four-level source.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/delaware.md``): whether a formal rate-limit policy exists;
whether section-number uniqueness within a title holds for *every* chapter
(sampled chapters only); and whether the HTML and PDF representations are
byte-identical in content. None of these block the implementation below.
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


class DelawareAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Delaware Code site at
    delcode.delaware.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by ``WashingtonAdapter``, ``TexasAdapter``,
    ``IllinoisAdapter``, and ``VirginiaAdapter``. See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://delcode.delaware.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A chapter link, e.g. ".../title11/c084a/index.html" -> "084a". The
    # leading zeros and any letter suffix are significant and preserved
    # here; identifier conversion happens in _chapter_to_identifier.
    _CHAPTER_URL = re.compile(r"c(\d+[a-z]*)/index\.html", re.IGNORECASE)
    # A subchapter link, e.g. ".../title11/c005/sc01/index.html" -> "01".
    _SUBCHAPTER_URL = re.compile(r"sc(\d+[a-z]*)/index\.html", re.IGNORECASE)
    # A title link, e.g. ".../title11/index.html" -> "11".
    _TITLE_URL = re.compile(r"title(\d+)/index\.html", re.IGNORECASE)
    # A section anchor, e.g. '<div class="SectionHead" id="501">'.
    _SECTION_HEAD = re.compile(
        r'<div\s+class="SectionHead"\s+id="([^"]+)"\s*>(.*?)</div>', re.DOTALL
    )
    # Opening tag of a Section block.
    _SECTION_BLOCK = re.compile(r'<div\s+class="Section">', re.DOTALL)
    # A body paragraph ("subsection" / "indent-2" / any other <p>).
    _BODY_PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)
    # Any <a href="...">...</a> pair, used for the generic link scan.
    _LINK = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    # "Title 12 - Decedents' Estates..." -> strip the "Title N - " prefix.
    _TITLE_NAME_PREFIX = re.compile(r"^Title\s+\d+\s*-\s+", re.IGNORECASE)
    # "Chapter 84A. Body-Worn Cameras..." -> strip the "Chapter N. " prefix.
    _CHAPTER_NAME_PREFIX = re.compile(r"^Chapter\s+\d+[a-z]*\.\s*", re.IGNORECASE)
    # "§ 501. Heading text." / "§§ 504-510. [Reserved.]" -> strip the
    # section symbol(s) and the leading number token, leaving the heading.
    _HEADING_PREFIX = re.compile(r"^\s*§+\s*[\w.\-]+\.?\s*")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Delaware."""
        return "DE"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Delaware."""
        return "Delaware"

    # ------------------------------------------------------------
    # URL construction and identifier conversion
    # ------------------------------------------------------------

    @staticmethod
    def _chapter_to_url(identifier: str) -> str:
        """Convert a chapter identifier (e.g. ``"5"``, ``"84a"``) to its
        zero-padded URL form (``"005"``, ``"084a"``).

        The numeric part is zero-padded to three digits and any trailing
        letter suffix is preserved (lower-case), matching the verified
        ``c001`` / ``c084a`` / ``c087a`` URL scheme.
        """
        match = re.match(r"(\d+)([a-z]*)$", identifier, re.IGNORECASE)
        if match is None:
            return identifier
        number, suffix = match.groups()
        return f"{int(number):03d}{suffix.lower()}"

    @staticmethod
    def _chapter_to_identifier(url_id: str) -> str:
        """Convert a chapter URL id (e.g. ``"005"``, ``"084a"``) to its
        identifier form (``"5"``, ``"84a"``): leading zeros stripped and
        any letter suffix lower-cased.
        """
        match = re.match(r"(\d+)([a-z]*)$", url_id, re.IGNORECASE)
        if match is None:
            return url_id.lstrip("0") or url_id
        number, suffix = match.groups()
        return f"{int(number)}{suffix.lower()}"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Delaware Code URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/delaware.md):

        * Title: ``https://delcode.delaware.gov/title{N}/index.html``.
        * Chapter: ``https://delcode.delaware.gov/title{N}/c{NNN}/index.html``
          (zero-padded to three digits, letter suffix preserved).
        * Section: the chapter page of the section's parent chapter.
          Sections have no per-section URL (verified HTTP 404), so
          retrieval uses the containing document and matches the
          ``SectionHead`` anchor after fetching.

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
            return (
                f"{self.BASE_URL}/title{ref.chapter.title.identifier}/"
                f"c{self._chapter_to_url(ref.chapter.identifier)}/index.html"
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/title{ref.title.identifier}/"
                f"c{self._chapter_to_url(ref.identifier)}/index.html"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/title{ref.identifier}/index.html"
        else:
            raise UnsupportedRefError(
                f"DelawareAdapter.build_url does not support refs of type "
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
        verified HTTP 404 (e.g. an invalid chapter such as
        ``/title11/c999/index.html``) into :class:`RefNotFoundError` —
        the source was reached, but the addressed document does not
        resolve to anything real.

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
                does not resolve on the Delaware Code site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Delaware Code site."
                ) from exc
            raise

    def _subchapter_url(
        self, title_ref: TitleRef, chapter_identifier: str, subchapter: str
    ) -> str:
        """Build the verified URL of one subchapter document.

        The URL is constructed from parts rather than resolved relative to
        the fetched chapter page's own URL, matching the verified
        ``/title{N}/cXXX/scYY/index.html`` scheme.
        """
        return (
            f"{self.BASE_URL}/title{title_ref.identifier}/"
            f"c{self._chapter_to_url(chapter_identifier)}/sc{subchapter}/index.html"
        )

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Delaware Code from the home page.

        The home page lists 31 titles, each as a ``title{N}/index.html``
        link (next to an "Authenticated PDF" link that this method
        ignores). The ``"Title N - "`` prefix is stripped from each
        display name, and the result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"11"``) and whose
            ``name`` is the title name without the ``Title N - `` prefix.

        Raises:
            AdapterUnavailableError: If the home page cannot be fetched or
                no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/"
        html = self._fetch_html(url, what="Delaware home page")

        titles = []
        seen: dict[str, None] = {}
        for href, inner in self._LINK.findall(html):
            match = self._TITLE_URL.search(href)
            if match is None:
                continue
            identifier = match.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            name = strip_tags(inner).strip()
            name = self._TITLE_NAME_PREFIX.sub("", name).strip() or identifier
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

        Chapters are linked as zero-padded ``cNNN...`` (lettered suffixes
        included, e.g. ``c084a``, ``c087a``). The ``"Chapter N. "`` prefix
        is stripped from each display name, leading zeros are stripped from
        the identifier, and the result is sorted numerically. The ``Part``
        groupings on the page are presentation only and flattened away.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the stripped chapter number (e.g. ``"5"``,
            ``"84a"``) and whose ``name`` is the chapter name without the
            ``Chapter N. `` prefix.

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched
                for any other reason, or if no usable chapter links could
                be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Delaware chapter listing")

        chapters = []
        seen: dict[str, None] = {}
        for href, inner in self._LINK.findall(html):
            match = self._CHAPTER_URL.search(href)
            if match is None:
                continue
            identifier = self._chapter_to_identifier(match.group(1))
            if identifier in seen:
                continue
            seen[identifier] = None
            name = strip_tags(inner).strip()
            name = self._CHAPTER_NAME_PREFIX.sub("", name).strip() or identifier
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
        """Enumerate every section under ``chapter_ref``.

        VERIFIED that a chapter page has one of two shapes: it either
        renders its sections inline as ``SectionHead`` anchors (e.g.
        ``c001`` -> ``101``, ``102``, ``103``), or it lists subchapters
        (e.g. ``c005`` -> ``sc01``–``sc07``) with no inline sections. For
        the subchapter shape, each subchapter document is fetched and its
        ``SectionHead`` anchors collected, so sections from every
        subchapter are flattened into one sequence (the subchapter level
        carries no citable identity).

        Reserved/range blocks (e.g. ``id="504-510"`` with ``[Reserved.]``
        body) are preserved in listings exactly as the site presents them:
        one entry per range, not one per covered number.

        Returns:
            A sequence of :class:`TocNode`, one per section, in
            deterministic numeric order, deduplicated on the anchor id.
            Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the ``SectionHead`` anchor id (e.g. ``"501"``)
            and whose ``name`` is the heading text (e.g. ``"Criminal
            solicitation in the third degree; class A misdemeanor."``).

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve), or if a subchapter the chapter
                page links to returns HTTP 404.
            AdapterUnavailableError: If a document cannot be fetched for
                any other reason, or if no section anchors could be found
                in the chapter's documents.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Delaware section listing")

        section_entries = self._collect_section_entries(
            html, chapter_ref, what="Delaware section listing"
        )

        if not section_entries:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no section anchors in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        sections = []
        seen: dict[str, None] = {}
        for identifier, heading in section_entries:
            if identifier in seen:
                continue
            seen[identifier] = None
            name = heading or identifier
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    def _collect_section_entries(
        self,
        chapter_html: str,
        chapter_ref: ChapterRef,
        *,
        what: str,
    ) -> list[tuple[str, str]]:
        """Collect every ``(anchor id, heading text)`` for ``chapter_ref``.

        If ``chapter_html`` (the chapter page) lists subchapters, each
        subchapter document is fetched and its entries collected; the
        subchapters are walked in document order. Otherwise the entries
        are collected from the chapter page itself.

        Args:
            chapter_html: The fetched chapter page HTML.
            chapter_ref: The chapter being enumerated.
            what: Short human-readable description for error messages.

        Returns:
            A list of ``(identifier, heading)`` pairs in document order.
            ``heading`` is the ``SectionHead`` text with the ``§``
            symbol(s) and leading number token stripped (e.g. ``"Criminal
            solicitation in the third degree; class A misdemeanor."``, or
            ``"[Reserved.]"`` for a reserved range block).

        Raises:
            RefNotFoundError: If a subchapter the chapter page links to
                returns HTTP 404.
            AdapterUnavailableError: If a subchapter document cannot be
                fetched for any other reason.
        """
        subchapters = [
            match.group(1)
            for href, _ in self._LINK.findall(chapter_html)
            if (match := self._SUBCHAPTER_URL.search(href)) is not None
        ]

        if subchapters:
            section_entries = []
            for subchapter in subchapters:
                sub_url = self._subchapter_url(
                    chapter_ref.title, chapter_ref.identifier, subchapter
                )
                sub_html = self._fetch_html(sub_url, what=what)
                section_entries.extend(self._sections_from_document(sub_html))
            return section_entries

        return self._sections_from_document(chapter_html)

    @classmethod
    def _sections_from_document(cls, html: str) -> list[tuple[str, str]]:
        """Return the ordered ``(anchor id, heading text)`` pairs of every
        ``SectionHead`` in one document."""
        entries = []
        for match in cls._SECTION_HEAD.finditer(html):
            heading = strip_tags(match.group(2)).strip()
            heading = cls._HEADING_PREFIX.sub("", heading).strip()
            entries.append((match.group(1), heading))
        return entries

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title, chapter, and
        section identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any lettered/range suffix — the same convention
        ``VirginiaAdapter`` uses — so ``1, 2, 5, 84a, 87a`` and
        ``501, 502, 504-510, 511`` order sensibly regardless of document
        order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Delaware.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the section number, e.g. ``"501"``) appears
        verbatim within ``raw_citation`` (the ``11 Del. C. § 501``
        citation). The stronger title/chapter/section cross-check against
        the source happens in :meth:`retrieve_section`, which has the
        document's anchor structure; ``normalize`` enforces state and
        citation agreement, consistent with the other adapters.

        ``status`` is always left at its default (``UNKNOWN``): nothing
        verified about the Delaware source provides a structural
        repealed/amended/renumbered signal, and the contract forbids
        inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Delaware ref
                (``ref.state_code != "DE"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"DelawareAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Delaware Code section, end to end:
        :meth:`build_url` -> fetch the parent chapter page -> resolve which
        containing document holds the section (walking subchapters when
        the chapter has them) -> match the ``SectionHead`` anchor ->
        parse the block into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        VERIFIED that sections are not individually addressable by URL, so
        the parent chapter page is the single starting point: if it lists
        subchapters, each subchapter document is fetched (in document
        order) until the anchor is found; otherwise the chapter page itself
        is searched.

        Args:
            ref: The section to retrieve. Must be a Delaware ref
                (``ref.state_code == "DE"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If a document cannot be fetched for
                any reason other than HTTP 404.
            RefNotFoundError: If the parent chapter (or a linked
                subchapter) returns HTTP 404, or if no containing document
                holds a ``SectionHead`` anchor matching ``ref.identifier``.
            RefMismatchError: Raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but its body is
                empty after cleaning (e.g. a reserved ``[Reserved.]``
                block, matching ``VirginiaAdapter``'s empty-body
                convention), or if the located block's anchor id disagrees
                with ``ref``. Also raised by :meth:`normalize` if ``ref``
                is not a Delaware ref.
        """
        url = self.build_url(ref)
        chapter_html = self._fetch_html(url, what="Delaware chapter page")

        block = self._find_section_block(chapter_html, ref, document_url=url)
        if block is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but found no section matching "
                f"{ref.identifier!r} in it; the section does not resolve on "
                "the Delaware Code site."
            )

        heading, text, amendment_notes = self._parse_section_block(
            block, ref.identifier, document_url=url
        )

        parsed = ParsedDocument(
            raw_citation=f"{ref.chapter.title.identifier} Del. C. § {ref.identifier}",
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    def _find_section_block(
        self,
        chapter_html: str,
        ref: SectionRef,
        *,
        document_url: str,
    ) -> str | None:
        """Locate the ``<div class="Section">`` block containing ``ref``.

        If the chapter page lists subchapters, each subchapter document is
        fetched (in document order) and searched; otherwise the chapter
        page itself is searched.

        Args:
            chapter_html: The fetched parent chapter page HTML.
            ref: The section being located.
            document_url: The chapter page URL (for error messages).

        Returns:
            The inner HTML of the matching ``Section`` block, or None if no
            document holds an anchor for ``ref.identifier``.
        """
        subchapters = [
            match.group(1)
            for href, _ in self._LINK.findall(chapter_html)
            if (match := self._SUBCHAPTER_URL.search(href)) is not None
        ]

        if subchapters:
            for subchapter in subchapters:
                sub_url = self._subchapter_url(
                    ref.chapter.title, ref.chapter.identifier, subchapter
                )
                sub_html = self._fetch_html(sub_url, what="Delaware subchapter page")
                block = self._block_for_section(sub_html, ref.identifier)
                if block is not None:
                    return block
            return None

        return self._block_for_section(chapter_html, ref.identifier)

    @classmethod
    def _block_for_section(cls, html: str, identifier: str) -> str | None:
        """Return the ``Section`` block whose ``SectionHead`` id equals
        ``identifier``, or None if there is no such block.

        The document is split on ``<div class="Section">`` openings so each
        chunk holds exactly one section's markup (verified: a ``<br>``
        separates adjacent blocks, and the split keeps the boundary clean).
        """
        parts = cls._SECTION_BLOCK.split(html)
        for part in parts[1:]:
            match = cls._SECTION_HEAD.search(part)
            if match is not None and match.group(1) == identifier:
                return part
        return None

    @classmethod
    def _parse_section_block(
        cls, block: str, identifier: str, *, document_url: str
    ) -> tuple[str, str, str | None]:
        """Parse one ``Section`` block into ``(heading, text, amendment_notes)``.

        Args:
            block: The inner HTML of one ``<div class="Section">`` block.
            identifier: The expected section anchor id.
            document_url: The URL the block came from (for error messages).

        Returns:
            A ``(heading, text, amendment_notes)`` triple. ``heading`` is
            the ``SectionHead`` text with the ``§`` symbol(s) and leading
            number token stripped; ``text`` is the body paragraphs joined
            with a blank line; ``amendment_notes`` is the trailing history
            chain (text after the last body paragraph) or None.

        Raises:
            NormalizationError: If the block has no ``SectionHead``, its
                anchor id disagrees with ``identifier``, or its body is
                empty after cleaning (a reserved ``[Reserved.]`` block).
        """
        head = cls._SECTION_HEAD.search(block)
        if head is None:
            raise NormalizationError(
                f"Fetched {document_url!r} and located section {identifier!r}, "
                "but its Section block contained no SectionHead element; the "
                "site's structure may have changed."
            )
        if head.group(1) != identifier:
            raise NormalizationError(
                f"Fetched {document_url!r} and located a Section block, but its "
                f"anchor id {head.group(1)!r} does not match the requested "
                f"section {identifier!r}; the site's structure may have changed."
            )

        heading = strip_tags(head.group(2)).strip()
        heading = cls._HEADING_PREFIX.sub("", heading).strip() or identifier

        body_paragraphs = [
            paragraph
            for paragraph in (
                strip_tags(match.group(1)).strip() for match in cls._BODY_PARA.finditer(block)
            )
            if paragraph
        ]
        text = "\n\n".join(body_paragraphs)
        if not text:
            raise NormalizationError(
                f"Fetched {document_url!r} and located section {identifier!r}, "
                "but its body text was empty after cleaning; the section is "
                "likely a reserved '[Reserved.]' block or the site's structure "
                "has changed."
            )

        last_paragraph_end = 0
        for match in cls._BODY_PARA.finditer(block):
            last_paragraph_end = match.end()

        trailing = strip_tags(block[last_paragraph_end:]).strip() if last_paragraph_end else None
        amendment_notes = trailing or None

        return heading, text, amendment_notes
