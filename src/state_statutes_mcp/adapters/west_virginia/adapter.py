"""WestVirginiaAdapter: the West Virginia-specific concrete state adapter.

Source: the official West Virginia Legislature publication of the West
Virginia Code at ``https://code.wvlegislature.gov/`` -- anonymous,
server-rendered HTML (WordPress-based) with no authentication or API key
(no SPA framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/west_virginia.md``,
which documents Wayback captures of the official host):

* The West Virginia Code has NO title level: its structural hierarchy is
  **Chapter -> Article -> Section**, mapped onto the framework model
  (Texas precedent) as **Chapter -> TitleRef**, **Article -> ChapterRef**,
  **Section -> SectionRef**. So ``get_section(state_code="WV", title="11",
  chapter="21", section="11-21-12")`` retrieves WV Chapter 11, Article 21,
  Section 11-21-12; ``list_chapters(title_ref="11")`` lists WV Articles of
  Chapter 11; ``list_sections(chapter_ref="21")`` lists the sections of
  Article 21.
* URLs: home/top-level enumeration ``{BASE}/``; chapter page (articles)
  ``{BASE}/{chapter}/``; article page (sections)
  ``{BASE}/{chapter}-{article}/``; section ``{BASE}/{section}/``.
* Top-level enumeration: the ``<select id='sel-chapter'>`` dropdown present
  on code pages lists every chapter, e.g. ``<option value='11'>CHAPTER 11.
  TAXATION.</option>``. VERIFIED: 139 options on the home capture
  (including lettered ``5A``-``5H``, ``60A``, ``60B``, ``49A``). The
  identifier is the option value (e.g. ``"11"``, ``"5A"``).
* Chapter page (article list): ``<div class='art-head' id='ah-1'><a
  href='/11-1/'>ARTICLE 1. SUPERVISION.</a></div>``. VERIFIED for Chapter
  11: 102 article links. The identifier is the article URL segment (e.g.
  ``"1"``, ``"1A"``, ``"21"``).
* Article page (section list): ``<div class='sec-head' data-id='ah-21'><a
  href='/11-21-1/'>§11-21-1. Legislative findings.</a></div>``. VERIFIED
  for Article 11-21: 143 section links, including lettered ``11-21-3A``
  and ``11-21-12A`` (uppercase in hrefs). The identifier is the section
  URL segment (e.g. ``"11-21-1"``, ``"11-21-3A"``), matching the URL path
  exactly. A ``Display all ... Sections`` toggle div has no link and is
  skipped.
* Section page structure (VERIFIED for 11-21-12):
  * Cross-check anchor ``<div id='chpsel-container' data-m='home'
    data-c='11' data-a='21' data-s='12' ...>`` exposing the chapter,
    article, and section codes.
  * Heading ``<h4>§11-21-12. West Virginia adjusted gross income of
    resident individual.</h4>`` -- the first ``<h4>`` inside the
    ``<div class='sectiontext hid'>`` body container; the leading
    ``§{id}. `` is stripped.
  * Body: the ``<p>`` paragraphs following the ``<h4>`` inside the
    ``sectiontext hid`` container (subsections ``(a)``, ``(b)``, ...,
    each with an em-dash lead-in).
  * History: the site renders Bill History and Signed Bills as separate
    linked-out widgets (a ``codeaffected`` widget), NOT in the section
    body, so ``amendment_notes`` stays ``None``.
* Citation: ``W. Va. Code § {id}`` (e.g. ``W. Va. Code § 11-21-12``),
  adapter-constructed. The ``W. Va. Code`` abbreviation is INFERENCE from
  standard West Virginia citation usage (the site itself renders
  ``§11-21-12.`` in headings and metadata); the ``{id}`` is VERIFIED from
  the site's own headings.
* Error boundary: live HTTP 404 behavior for missing
  chapters/articles/sections is UNVERIFIED (host unreachable); by
  convention HTTP 404 is mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/west_virginia.md``):
whether every chapter/article/section page renders identically (sampled
Chapters 1/11 and Article 11-21), the live 404 page shape, and whether the
home page's chapter ``<select>`` is always present. None of these block the
implementation below.
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
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus


class WestVirginiaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official West Virginia Legislature
    publication of the West Virginia Code at code.wvlegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified site structure this adapter is built against.

    WV has no title level: its Chapter -> Article -> Section hierarchy is
    mapped onto the framework's Title -> Chapter -> Section model (Texas
    precedent), as documented in the module docstring and
    ``docs/research/west_virginia.md``.
    """

    BASE_URL = "https://code.wvlegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A chapter option in the '<select id='sel-chapter'>' dropdown, e.g.
    # '<option value='11'>CHAPTER 11. TAXATION.</option>'.
    _CHAPTER_OPTION = re.compile(
        r"<option value='([^']+)'[^>]*>(.*?)</option>", re.DOTALL
    )
    # The leading 'CHAPTER 11. ' label prefix on a chapter option.
    _CHAPTER_LABEL_PREFIX = re.compile(r"^CHAPTER\s+[0-9]+[A-Z]*\.\s*")

    # An article link on a chapter page, e.g. '<div class='art-head'
    # id='ah-1'><a href='/11-1/'>ARTICLE 1. SUPERVISION.</a></div>'.
    _ARTICLE_LINK = re.compile(
        r"<div class='art-head'[^>]*><a href='/([0-9]+(?:[A-Za-z]+)?-[0-9]+[A-Za-z]*)/'>(.*?)</a>",
        re.DOTALL,
    )
    # The leading 'ARTICLE 1. ' / 'ARTICLE 1A. ' label prefix.
    _ARTICLE_LABEL_PREFIX = re.compile(r"^ARTICLE\s+[0-9]+[A-Za-z]*\.\s*")

    # A section link on an article page, e.g. '<div class='sec-head'
    # data-id='ah-21'><a href='/11-21-1/'>§11-21-1. Legislative
    # findings.</a></div>'.
    _SECTION_LINK = re.compile(
        r"<div class='sec-head'[^>]*><a href='/([0-9]+(?:[A-Za-z]+)?-[0-9]+[A-Za-z]*-[0-9]+[A-Za-z]*)/'>(.*?)</a>",
        re.DOTALL,
    )
    # The leading '§11-21-1. ' / '§11-21-3a. ' label prefix. Note the
    # label renders the lettered suffix lowercase even though the href is
    # uppercase.
    _SECTION_LABEL_PREFIX = re.compile(
        r"^§\s*[0-9]+(?:[A-Za-z]+)?-[0-9]+[A-Za-z]*-[0-9]+[A-Za-z]*\.\s*"
    )

    # The per-section-page cross-check container, e.g. '<div id=
    # 'chpsel-container' data-m='home' data-c='11' data-a='21' data-s='12'
    # ...>'.
    _CROSSCHECK_CONTAINER = re.compile(
        r"<div id='chpsel-container'[^>]*data-c='([^']*)' "
        r"data-a='([^']*)' data-s='([^']*)'"
    )
    # The body container on a section page: '<div class='sectiontext
    # hid'><h4>§11-21-12. ...</h4><p>...</p>...</div>'.
    _SECTIONTEXT_DIV = re.compile(
        r"<div class='sectiontext hid'>(.*?)</div>", re.DOTALL
    )
    # The heading element inside the sectiontext container.
    _HEADING_H4 = re.compile(r"<h4>(.*?)</h4>", re.DOTALL)
    # The leading '§11-21-12. ' prefix on the heading.
    _HEADING_PREFIX = re.compile(
        r"^§\s*[0-9]+(?:[A-Za-z]+)?-[0-9]+[A-Za-z]*-[0-9]+[A-Za-z]*\.\s*"
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for West Virginia."""
        return "WV"

    @property
    def state_name(self) -> str:
        """Human-facing display name for West Virginia."""
        return "West Virginia"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official West Virginia Code URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/west_virginia.md).
        Recall the WV Chapter -> Article -> Section mapping onto the
        framework's Title -> Chapter -> Section model:

        * TitleRef (WV chapter): ``{BASE}/{chapter}/`` -- the chapter page
          (article listing), e.g. ``/11/``.
        * ChapterRef (WV article): ``{BASE}/{chapter}-{article}/`` -- the
          article page (section listing), e.g. ``/11-21/``.
        * SectionRef (WV section): ``{BASE}/{section}/`` -- the section's
          own page, e.g. ``/11-21-12/``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/{ref.identifier}/"
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/{ref.title.identifier}-{ref.identifier}/"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/{ref.identifier}/"
        else:
            raise UnsupportedRefError(
                f"WestVirginiaAdapter.build_url does not support refs of type "
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
        verified HTTP 404 (e.g. an invalid chapter/article/section) into
        :class:`RefNotFoundError` -- the source was reached, but the
        addressed document does not resolve. Live 404 behavior is
        UNVERIFIED for this host (unreachable from the research
        environment); the mapping follows the Maine/other-adapters
        convention and is simulated in tests.

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
                does not resolve on the West Virginia Code site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the West Virginia Code site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _section_identifier(cls, href: str) -> str:
        """Extract the section identifier from an article-page link href.

        The section href is ``/{section}/`` where ``{section}`` is the full
        dotted ``chapter-article-number`` form (e.g. ``/11-21-12/``,
        ``/11-21-3A/``). The identifier is that URL segment verbatim,
        matching the URL path exactly.
        """
        return href.strip("/")

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every chapter of the West Virginia Code from the home
        page's chapter dropdown.

        The ``<select id='sel-chapter'>`` dropdown present on the home
        page lists every chapter, e.g. ``<option value='11'>CHAPTER 11.
        TAXATION.</option>``. The identifier is the option value (e.g.
        ``"11"``, ``"5A"``); the display name is the label with the
        ``CHAPTER {n}. `` prefix stripped. The result is sorted
        numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the WV chapter (e.g. ``"11"``) and whose
            ``name`` is the chapter name (e.g. ``"TAXATION."``).

        Raises:
            AdapterUnavailableError: If the home page cannot be fetched or
                no usable chapter options could be parsed from it.
        """
        url = f"{self.BASE_URL}/"
        html = self._fetch_html(url, what="West Virginia Code home page")

        titles = []
        for identifier, label in self._CHAPTER_OPTION.findall(html):
            name = self._CHAPTER_LABEL_PREFIX.sub(
                "", self._clean_inner(label)
            ).strip() or identifier
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=TitleRef(
                        state_code=self.state_code, identifier=identifier
                    ),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter options in it; "
                "the site's structure may have changed."
            )

        return tuple(sorted(titles, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every WV article under ``title_ref`` (a WV chapter)
        from the chapter page.

        ``build_url(title_ref)`` returns ``{BASE}/{chapter}/``, whose
        ``results-box`` enumerates the chapter's articles as ``<div
        class='art-head' ...><a href='/{chapter}-{article}/'>ARTICLE {n}.
        {name}</a></div>``. The identifier is the article URL segment
        (e.g. ``"1"``, ``"1A"``, ``"21"``); the display name is the label
        with the ``ARTICLE {n}. `` prefix stripped. The result is sorted
        numerically.

        Returns:
            A sequence of :class:`TocNode`, one per WV article, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the WV article (e.g. ``"21"``) and whose
            ``name`` is the article name (e.g. ``"PERSONAL INCOME TAX."``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404, or if the
                served chapter page's cross-check container disagrees with
                ``title_ref`` (the chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable article links could
                be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="West Virginia chapter page")

        anchor = self._CROSSCHECK_CONTAINER.search(html)
        if anchor is None or anchor.group(1) != title_ref.identifier:
            raise RefNotFoundError(
                f"Could not resolve chapter {title_ref.identifier!r} at "
                f"{url!r}; the served page does not match the requested "
                "chapter."
            )

        chapters = []
        for href, label in self._ARTICLE_LINK.findall(html):
            article = self._section_identifier(href).split("-", 1)[-1]
            name = self._ARTICLE_LABEL_PREFIX.sub(
                "", self._clean_inner(label)
            ).strip() or article
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=article,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=article),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} and found chapter {title_ref.identifier!r}, "
                "but its page contained no usable article links; the "
                "site's structure may have changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every WV section under ``chapter_ref`` (a WV article)
        from the article page.

        ``build_url(chapter_ref)`` returns
        ``{BASE}/{chapter}-{article}/``, whose ``results-box`` enumerates
        the article's sections as ``<div class='sec-head' ...><a href=
        '/{section}/'>§{id}. {name}</a></div>``. The identifier is the
        section URL segment verbatim (e.g. ``"11-21-1"``, ``"11-21-3A"``);
        the display name is the label with the ``§{id}. `` prefix stripped.
        A href-less "Display all ..." toggle div is skipped. The result is
        sorted by the trailing section number.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section URL segment (e.g. ``"11-21-1"``)
            and whose ``name`` is the section's name as presented in the
            listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404, or if
                the served article page's cross-check container disagrees
                with ``chapter_ref`` (the article does not resolve).
            AdapterUnavailableError: If the article page cannot be fetched
                for any other reason, or if no usable section links could
                be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="West Virginia article page")

        anchor = self._CROSSCHECK_CONTAINER.search(html)
        if anchor is None or (
            anchor.group(1) != chapter_ref.title.identifier
            or anchor.group(2) != chapter_ref.identifier
        ):
            raise RefNotFoundError(
                f"Could not resolve article {chapter_ref.identifier!r} under "
                f"chapter {chapter_ref.title.identifier!r} at {url!r}; the "
                "served page does not match the requested article."
            )

        sections = []
        seen: dict[str, None] = {}
        for href, label in self._SECTION_LINK.findall(html):
            identifier = self._section_identifier(href)
            if identifier in seen:
                continue
            seen[identifier] = None
            name = self._SECTION_LABEL_PREFIX.sub(
                "", self._clean_inner(label)
            ).strip() or identifier
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
                f"Fetched {url!r} and found article {chapter_ref.identifier!r} "
                f"under chapter {chapter_ref.title.identifier!r}, but its page "
                "contained no usable section links; the site's structure may "
                "have changed."
            )

        return tuple(
            sorted(sections, key=lambda node: self._section_sort_key(node.identifier))
        )

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for chapter/article
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any letter suffix -- the same convention the other adapters
        use -- so ``1, 2, 5A, 11, 49A`` order sensibly regardless of
        document order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    @classmethod
    def _section_sort_key(cls, identifier: str) -> tuple:
        """Numeric sort key for WV section identifiers.

        A WV section identifier is the dotted ``chapter-article-number``
        form (e.g. ``"11-21-1"``, ``"11-21-3A"``); every section shares the
        same leading ``chapter-article`` prefix, so sorting must use the
        trailing number (with any letter suffix as tiebreaker) -- e.g.
        ``11-21-1, 11-21-3A, 11-21-12, 11-21-97``.
        """
        parts = identifier.split("-")
        if len(parts) >= 3:
            leading = re.match(r"\d+", parts[-1])
            number = int(leading.group()) if leading else 0
            return (number, parts[-1], identifier)
        return (0, "", identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        West Virginia.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the dotted ``chapter-article-number`` form,
        e.g. ``"11-21-12"``) appears verbatim within ``raw_citation`` (the
        ``W. Va. Code § 11-21-12`` citation). The stronger chapter/article
        cross-check against the source response happens in
        :meth:`retrieve_section`, which has the page's ``data-c``/``data-a``
        container attributes.

        ``status`` stays ``UNKNOWN`` for West Virginia: no structural status
        signal exists in the captured section pages.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a West Virginia ref
                (``ref.state_code != "WV"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"WestVirginiaAdapter.normalize cannot normalize a ref for "
                f"state {ref.state_code!r}; expected {self.state_code!r}."
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
            status=StatuteStatus.UNKNOWN,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one West Virginia Code section, end to
        end: :meth:`build_url` -> fetch the section page -> cross-check the
        page's ``data-c``/``data-a``/``data-s`` container attributes
        against ``ref`` -> parse the section page into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/west_virginia.md): the
        heading is the ``<h4>`` inside the ``sectiontext hid`` container
        with the leading ``§{id}. `` prefix stripped; the body is the
        ``<p>`` paragraphs following the ``<h4>`` inside that container;
        ``amendment_notes`` stays ``None`` (bill history is a separate
        linked-out widget, not in the body). The section page's
        ``data-c``/``data-a`` container attributes are cross-checked
        against ``ref.chapter.title``/``ref.chapter`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be a West Virginia ref
                (``ref.state_code == "WV"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                conventional not-found signal).
            RefMismatchError: If the page's chapter/article container
                attributes disagree with ``ref``. Also raised by
                :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but required
                structure (cross-check container, heading, body) is
                missing, or the body is empty after cleaning. Also raised
                by :meth:`normalize` if ``ref`` is not a West Virginia ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="West Virginia section page")

        anchor = self._CROSSCHECK_CONTAINER.search(html)
        if anchor is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "cross-check container; the site's structure may have "
                "changed."
            )
        chapter_code, article_code, section_code = anchor.groups()
        if chapter_code != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.title.identifier!r} does not "
                f"match the chapter in the fetched section page: "
                f"{chapter_code!r}."
            )
        if article_code != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested article {ref.chapter.identifier!r} does not match "
                f"the article in the fetched section page: {article_code!r}."
            )
        if section_code and section_code != ref.identifier.rsplit("-", 1)[-1]:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched section page: {section_code!r}."
            )

        sectiontext = self._SECTIONTEXT_DIV.search(html)
        if sectiontext is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "sectiontext body container; the site's structure may have "
                "changed."
            )

        heading_h4 = self._HEADING_H4.search(sectiontext.group(1))
        if heading_h4 is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._HEADING_PREFIX.sub(
            "", self._clean_inner(heading_h4.group(1))
        ).strip() or None

        body_html = sectiontext.group(1)[heading_h4.end() :]
        text = strip_tags(body_html, preserve_block_breaks=True).strip()

        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        raw_citation = f"W. Va. Code § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=None,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
