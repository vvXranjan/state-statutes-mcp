"""VermontAdapter: the Vermont-specific concrete state adapter.

Source: the official Vermont General Assembly publication of the Vermont
Statutes Annotated (V.S.A.) at ``https://legislature.vermont.gov/statutes/``
-- anonymous, server-rendered HTML with no authentication or API key (no
SPA framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/vermont.md``,
which documents Wayback captures of the official host):

* Three structural levels, mapping 1:1 onto the framework model. The
  identifiers are the zero-padded URL segments themselves (padding is
  inherent in the URL and carries through the identifiers):
  * Title: the title URL segment (``"01"``, ``"21"``, ``"09A"``,
    ``"03APPENDIX"``) -- ``list_titles`` returns ``"01"`` for Title 1.
  * Chapter: the chapter URL segment (``"001"``, ``"017"``).
  * Section: the section URL segment (``"01344"``, ``"01301a"``).
* URLs: titles ``{BASE}/statutes/``; title page (chapters)
  ``{BASE}/statutes/title/{title}``; chapter page (sections)
  ``{BASE}/statutes/chapter/{title}/{chapter}``; section
  ``{BASE}/statutes/section/{title}/{chapter}/{section}``.
* Section page structure (VERIFIED for 21/017/01344):
  * Cross-check anchors ``<h2 class="statute-title"><a href=
    "/statutes/title/21">Title 21: Labor</a></h2>`` and ``<h3
    class="statute-chapter"><a href="/statutes/chapter/21/017">Chapter
    017: ...</a></h3>``, plus an informational ``<h4 class="statute-section">``
    subchapter heading.
  * Citation ``<b>(Cite as: 21 V.S.A. § 1344)</b>`` immediately before
    the body. The citation is the "Cite as:" line's content, e.g.
    ``21 V.S.A. § 1344`` (unpadded title/section numbers).
  * Heading ``<b>§ 1344. Disqualifications</b>`` -- the first ``<b>``
    inside the ``<ul class="item-list statutes-detail">`` list; the
    ``§ {n}. `` prefix is stripped.
  * Body: the ``<p>`` paragraphs inside the ``statutes-detail`` list
    after the heading (indented subsection paragraphs). The final body
    paragraph ends with the trailing amendment history parenthetical,
    e.g. ``(Amended 1959, No. 236; ... 2023, No. 6, § 252, eff. July 1,
    2023.)`` -- preserved verbatim into ``amendment_notes`` and removed
    from the body.
* Discovery:
  * Titles: the statutes index page lists every title as ``<li><a
    href="statutes/title/01">Title 1: General Provisions</a></li>``
    (relative hrefs for titles 1-3, absolute for the rest). VERIFIED: 46
    titles.
  * Chapters: the title page lists every chapter as ``<li><a href=
    "/statutes/chapter/01/001">Chapter <span class="dirty">001</span>:
    ...</a></li>`` plus a "Contains: §§ ..." sub-list. VERIFIED for Title
    1: 13 chapters.
  * Sections: the chapter page lists sections as ``<li><a href=
    "/statutes/section/21/017/01301">§ 1301.  Definitions</a></li>``,
    interspersed with subchapter ``<strong>`` markers (presentation-only,
    flattened, not a ref level). VERIFIED for Chapter 21/017: 123 section
    links. Repealed-section annotations are prose-level and preserved
    verbatim in listing names (``status`` stays ``UNKNOWN``).
* Citation: ``{title} V.S.A. § {section}`` -- adapter-constructed from the
  section page's own "(Cite as:)" line (verified on the page), with the
  zero-padded identifiers unpadded for display (e.g. section ``"01344"``
  cites as ``1344``).
* Error boundary: live HTTP 404 behavior for missing
  titles/chapters/sections is UNVERIFIED (host unreachable); by
  convention HTTP 404 is mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/vermont.md``):
whether title/chapter pages always render identically, the exact markup of
every section page, and the live 404 page shape. None of these block the
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


class VermontAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Vermont General Assembly
    publication of the Vermont Statutes Annotated at legislature.vermont.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://legislature.vermont.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title link on the statutes index page. Titles 1-3 use relative
    # hrefs ('statutes/title/01'); the rest use absolute hrefs
    # ('/statutes/title/03APPENDIX').
    _TITLE_LINK = re.compile(
        r'<a href="(?:/)?statutes/title/([0-9]+[A-Z]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # The leading 'Title 3 Appendix: ' / 'Title 1: ' label prefix on a
    # title link.
    _TITLE_LABEL_PREFIX = re.compile(r"^Title\s+[^:]+:\s*")

    # A chapter link on a title page, e.g. '<a href="/statutes/chapter/
    # 01/001">Chapter  <span class="dirty">001</span>: <span class="caps">
    # Vermont Statutes Annotated</span></a>'.
    _CHAPTER_LINK = re.compile(
        r'<a href="/statutes/chapter/([0-9]+)/([0-9]+)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # The leading 'Chapter 001 : ' label prefix on a chapter link (the
    # space before the colon is an artifact of the removed <span> tag).
    _CHAPTER_LABEL_PREFIX = re.compile(r"^Chapter\s+[0-9]+\s*:\s*")

    # A section link on a chapter page, e.g. '<a href="/statutes/section/
    # 21/017/01301"> § 1301.  Definitions</a>'. Lettered sections use
    # 01301a-style hrefs.
    _SECTION_LINK = re.compile(
        r'<a href="/statutes/section/([0-9]+)/([0-9]+)/([0-9]+[a-z]?)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # The leading '§ 1301.  ' label prefix on a section link.
    _SECTION_LABEL_PREFIX = re.compile(r"^§\s*[0-9]+[a-z]*\.\s*")

    # The per-section-page cross-check anchors.
    _TITLE_ANCHOR = re.compile(
        r'<h2 class="statute-title">.*?href="[^"]*?/statutes/title/'
        r'([0-9]+[A-Z]*)"[^>]*>.*?</h2>',
        re.DOTALL,
    )
    # The h3 chapter anchor. On a section page it is '<h3 class=
    # "statute-chapter"><a href="/statutes/chapter/21/017">...' but on a
    # chapter-listing page it is plain '<h3 class="statute-chapter">Chapter
    # <span class="dirty">017</span>: ...</h3>' with no href, so the
    # chapter number is read from its dirty span instead.
    _CHAPTER_ANCHOR = re.compile(
        r'<h3 class="statute-chapter">.*?<span class="dirty">\s*'
        r'([0-9]+[A-Z]*)\s*</span>.*?</h3>',
        re.DOTALL,
    )
    # The 'Cite as' line: '<b>(Cite as: 21 V.S.A. § 1344)</b>'.
    _CITE_AS = re.compile(r"\(Cite as:\s*(.*?)\s*\)", re.DOTALL)
    # The heading element inside the statutes-detail list, e.g. '<b>§ 1344.
    # Disqualifications</b>'.
    _HEADING_B = re.compile(r"<b>(.*?)</b>", re.DOTALL)
    # The leading '§ 1344. ' prefix on the heading.
    _HEADING_PREFIX = re.compile(r"^§\s*[0-9]+[a-z]*\.\s*")
    # The statutes-detail body list on a section page.
    _DETAIL_UL = re.compile(
        r'<ul class="item-list statutes-detail">(.*?)</ul>', re.DOTALL
    )
    # A trailing amendment-history parenthetical, e.g. '(Amended 1959,
    # No. 236; ... 2023, No. 6, § 252, eff. July 1, 2023.)', anchored to
    # the very end of the body text. The leading greedy '.*' group makes
    # this match the LAST such parenthetical that reaches the end of the
    # text.
    _HISTORY = re.compile(
        r"^(.*)(\((?:(?:Amended|Added)\b.*)\))$", re.DOTALL
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Vermont."""
        return "VT"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Vermont."""
        return "Vermont"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Vermont Statutes URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/vermont.md):

        * Title: ``https://legislature.vermont.gov/statutes/title/{title}``
          -- the title page (chapter listing).
        * Chapter: ``https://legislature.vermont.gov/statutes/chapter/{title}/{chapter}``
          -- the chapter page (section listing).
        * Section: ``https://legislature.vermont.gov/statutes/section/{title}/{chapter}/{section}``
          -- the section's own page.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            title = ref.chapter.title.identifier
            return (
                f"{self.BASE_URL}/statutes/section/{title}/"
                f"{ref.chapter.identifier}/{ref.identifier}"
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/statutes/chapter/{ref.title.identifier}/"
                f"{ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/statutes/title/{ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"VermontAdapter.build_url does not support refs of type "
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
        verified HTTP 404 (e.g. an invalid title/chapter/section) into
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
                does not resolve on the Vermont Statutes site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Vermont Statutes site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _unpad(cls, identifier: str) -> str:
        """Strip the leading-zero padding from a URL-segment identifier.

        The identifiers carry the site's zero-padding (``"01344"``), but
        the citation form is unpadded (``"1344"``). This helper strips the
        leading zeros so the unpadded number can be used for citations and
        for the ``normalize`` cross-check.
        """
        return re.sub(r"^(0+)(?=\d)", "", identifier)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Vermont Statutes from the statutes
        index page.

        The index page lists 46 titles, each as a ``Title {n}: {name}``
        link whose href carries the zero-padded URL segment (``"01"``,
        ``"21"``, ``"09A"``, ``"03APPENDIX"``). The identifier is the URL
        segment verbatim; the display name is the label with the
        ``Title {n}: `` prefix stripped. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title URL segment (e.g. ``"01"``,
            ``"21"``) and whose ``name`` is the title name (e.g.
            ``"General Provisions"``).

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched or
                no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/statutes/"
        html = self._fetch_html(url, what="Vermont statutes index page")

        titles = []
        for identifier, label in self._TITLE_LINK.findall(html):
            name = self._TITLE_LABEL_PREFIX.sub(
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
                f"Fetched {url!r} but found no usable title links in it; "
                "the site's structure may have changed."
            )

        return tuple(sorted(titles, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title page.

        ``build_url(title_ref)`` returns
        ``/statutes/title/{title}``, whose ``statutes-list`` enumerates
        the title's chapters as ``Chapter {n}: {name}`` links (plus
        informational "Contains: §§ ..." sub-lists that are skipped). The
        identifier is the chapter URL segment (e.g. ``"001"``); the
        display name is the label with the ``Chapter {n}: `` prefix
        stripped. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter URL segment (e.g. ``"001"``) and
            whose ``name`` is the chapter name (e.g. ``"Construction of
            Statutes"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404, or if the
                served title page's title anchor does not match
                ``title_ref`` (the title does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched
                for any other reason, or if no usable chapter links could
                be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Vermont title page")

        anchor = self._TITLE_ANCHOR.search(html)
        if anchor is None or anchor.group(1) != title_ref.identifier:
            raise RefNotFoundError(
                f"Could not resolve title {title_ref.identifier!r} at {url!r}; "
                "the served page does not match the requested title."
            )

        chapters = []
        for _title, identifier, label in self._CHAPTER_LINK.findall(html):
            name = self._CHAPTER_LABEL_PREFIX.sub(
                "", self._clean_inner(label)
            ).strip() or identifier
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
                f"Fetched {url!r} and found title {title_ref.identifier!r}, "
                "but its page contained no usable chapter links; the "
                "site's structure may have changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        page.

        ``build_url(chapter_ref)`` returns
        ``/statutes/chapter/{title}/{chapter}``, whose ``statutes-list``
        enumerates the chapter's sections as ``§ {n}.  {name}`` links,
        interspersed with subchapter ``<strong>`` markers that are
        presentation-only and flattened away. The identifier is the
        section URL segment (e.g. ``"01301"``, ``"01301a"``); the display
        name is the label with the ``§ {n}. `` prefix stripped, with any
        repealed-section annotation preserved verbatim (e.g. ``"Repealed.
        2001, No. 142, § 302c."``). The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section URL segment (e.g. ``"01301"``)
            and whose ``name`` is the section's name as presented in the
            listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404, or if
                the served chapter page's title/chapter anchors do not
                match ``chapter_ref`` (the chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section links could
                be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Vermont chapter page")

        title_anchor = self._TITLE_ANCHOR.search(html)
        if title_anchor is None or title_anchor.group(1) != chapter_ref.title.identifier:
            raise RefNotFoundError(
                f"Could not resolve chapter {chapter_ref.identifier!r} under "
                f"title {chapter_ref.title.identifier!r} at {url!r}; the served "
                "page does not match the requested title."
            )
        chapter_anchor = self._CHAPTER_ANCHOR.search(html)
        if chapter_anchor is None or chapter_anchor.group(1) != chapter_ref.identifier:
            raise RefNotFoundError(
                f"Could not resolve chapter {chapter_ref.identifier!r} under "
                f"title {chapter_ref.title.identifier!r} at {url!r}; the served "
                "page does not match the requested chapter."
            )

        sections = []
        for _title, _chapter, identifier, label in self._SECTION_LINK.findall(html):
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
                f"Fetched {url!r} and found chapter {chapter_ref.identifier!r} "
                f"under title {chapter_ref.title.identifier!r}, but its page "
                "contained no usable section links; the site's structure may "
                "have changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title/chapter/section
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any letter suffix -- the same convention the other adapters
        use -- so ``01, 02, 03, 03APPENDIX, 04`` and ``01301, 01301a,
        01301b, 01302`` order sensibly regardless of document order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Vermont.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that the section
        number appears within ``raw_citation``. The identifiers carry the
        site's zero-padding (``"01344"``) while the citation is unpadded
        (``21 V.S.A. § 1344``), so the leading zeros are stripped before
        the check. The stronger title/chapter cross-check against the
        source response happens in :meth:`retrieve_section`, which has the
        page's Title/Chapter anchors.

        ``status`` stays ``UNKNOWN`` for Vermont: repealed sections carry
        their annotation as prose in the listing/body and no structural
        repeal marker was verified on a section page.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Vermont ref
                (``ref.state_code != "VT"``).
            RefMismatchError: If the section number does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"VermontAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )

        if self._unpad(ref.identifier) not in parsed.raw_citation:
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
        """Retrieve and normalize one Vermont Statutes Annotated section,
        end to end: :meth:`build_url` -> fetch the section page ->
        cross-check the page's Title/Chapter anchors against ``ref`` ->
        parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/vermont.md): the citation is
        the page's ``(Cite as: ...)`` line; the heading is the first
        ``<b>`` inside the ``statutes-detail`` list with the ``§ {n}. ``
        prefix stripped; the body is the ``<p>`` paragraphs after the
        heading inside that list; ``amendment_notes`` is the trailing
        ``(Amended ...)`` / ``(Added ...)`` parenthetical of the final body
        paragraph, removed from the body. The section page's Title/Chapter
        anchors are cross-checked against ``ref.chapter.title``/``ref.chapter``
        and a mismatch raises :class:`RefMismatchError` before anything is
        parsed.

        Args:
            ref: The section to retrieve. Must be a Vermont ref
                (``ref.state_code == "VT"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                conventional not-found signal).
            RefMismatchError: If the page's Title/Chapter anchors disagree
                with ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                structure (title anchor, chapter anchor, citation line,
                heading, body) is missing, or the body is empty after
                cleaning. Also raised by :meth:`normalize` if ``ref`` is
                not a Vermont ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Vermont section page")

        title_anchor = self._TITLE_ANCHOR.search(html)
        if title_anchor is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no Title "
                "anchor; the site's structure may have changed."
            )
        if title_anchor.group(1) != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section page: "
                f"{title_anchor.group(1)!r}."
            )

        chapter_anchor = self._CHAPTER_ANCHOR.search(html)
        if chapter_anchor is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no Chapter "
                "anchor; the site's structure may have changed."
            )
        if chapter_anchor.group(1) != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} under title "
                f"{ref.chapter.title.identifier!r} does not match the chapter "
                f"in the fetched section page: {chapter_anchor.group(1)!r}."
            )

        cite_as = self._CITE_AS.search(html)
        if cite_as is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "'Cite as:' line; the site's structure may have changed."
            )
        raw_citation = self._clean_inner(cite_as.group(1))

        detail = self._DETAIL_UL.search(html)
        if detail is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "statutes-detail body list; the site's structure may have "
                "changed."
            )

        heading_b = self._HEADING_B.search(detail.group(1))
        if heading_b is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._HEADING_PREFIX.sub(
            "", self._clean_inner(heading_b.group(1))
        ).strip() or None

        body_html = detail.group(1)[heading_b.end() :]
        text = strip_tags(body_html, preserve_block_breaks=True).strip()

        amendment_notes = None
        history = self._HISTORY.match(text)
        if history is not None:
            amendment_notes = history.group(2).strip()
            text = history.group(1).strip()

        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
