"""MissouriAdapter: the Missouri-specific concrete state adapter.

Source: the official Revisor of Missouri publication of the Revised
Statutes of Missouri (RSMo) at ``https://revisor.mo.gov/main/`` --
anonymous, server-rendered HTML with no authentication or API key (no SPA
framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/missouri.md``,
which documents Wayback captures of the official host):

* Base URL ``https://revisor.mo.gov`` with statutory pages under ``/main/``.
* Titles: the home page (``/main/Home.aspx``) holds a "Chapters in Title"
  region of 41 title ``<details>`` blocks. Each block's ``<summary>`` has
  two ``<span class="lr-font-emph">`` spans: the first is the chapter range
  (``Chs. 1-3``), the second is the title identifier and name
  (``I\u2003LAWS AND STATUTES``, where the identifier is the Roman numeral
  before ``\u2003`` and the name is the remainder). Each block body lists
  the title's chapters as ``/main/OneChapter.aspx?chapter=N`` links.
  VERIFIED: 41 unique titles; 468 chapter links across the blocks.
* Chapters: a title block on the home page lists every chapter of that
  title. The chapter identifier is the ``chapter=N`` value (e.g. ``"1"``,
  ``"536"``); the display name is the link text with the leading chapter
  number and ``\u2003`` runs stripped. Titles have no URL of their own:
  ``build_url(TitleRef)`` returns the home page, and ``list_chapters``
  fetches the home page and filters by title block. VERIFIED.
* Sections: a chapter TOC page (``/main/PageSelect.aspx?chapter={N}``)
  lists every section as table rows
  ``<a href="/main/PageSelect.aspx?section=536.010&amp;bid=28388&amp;hl=">536.010</a>``
  with the name in the next cell (e.g. ``Definitions. (8/28/2006)``,
  effective-date parenthetical preserved verbatim). VERIFIED for Chapter
  536: 54 sections, 536.010 -> 536.320. Both ``PageSelect.aspx`` and
  ``OneChapter.aspx`` return the same listing.
* Section content: ``/main/OneSection.aspx?section={section}`` (e.g.
  ``...?section=536.050``) -- one page per section. VERIFIED structure
  (for 536.050 and 536.303):
  * Cross-check anchors ``<p>Title XXXVI STATUTORY ACTIONS AND TORTS</p>``
    and ``<a href="/main/PageSelect.aspx?chapter=536">Chapter 536</a>``
    (with ``title="Return to section list for Chapter 536"``) appear
    before the section content.
  * Heading ``<span class="bold"> 536.050.<span> </span>Declaratory
    judgments respecting the validity of rules — fees and expenses —
    standing, intervention by general assembly. — </span>``. The heading is
    the bold-span text with the leading ``536.050.`` prefix and the
    trailing `` — `` separator stripped.
  * Body: the ``1.``-style text immediately following the bold span,
    inside the ``<div class="norm">`` container, up to the
    ``<div class="foot">`` history block.
  * History: ``<div class="foot">`` containing a ``--------`` marker
    paragraph followed by ``<p class="norm">(L. 1945 p. 1504 § 5, A.L.
    1978 S.B. 661, ...) </p>`` and editorial footnotes.
  * Repealed sections (e.g. 536.303): the body is just
    ``<span class="bold"> 536.303. (Repealed L. 2024 S.B. 894 &amp;
    825)</span>`` with an empty foot block. The repeal note is the
    section's entire content -- a structural "Repealed" marker in place of
    body text -- so ``status`` is set to ``REPEALED`` (the first adapter
    in this codebase to do so).
* Citation: ``RSMo § {section}`` (e.g. ``RSMo § 536.050``),
  adapter-constructed. ``SectionRef.identifier`` is the dotted section
  number (e.g. ``"536.050"``); ``ChapterRef.identifier`` the chapter
  number (e.g. ``"536"``); ``TitleRef.identifier`` the Roman numeral
  (e.g. ``"XXXVI"``). The ``RSMo`` abbreviation is VERIFIED from the
  site's own page title/share metadata; the ``§`` shape is INFERENCE from
  standard Missouri citation usage.
* Error boundary: live HTTP 404 behavior for missing
  titles/chapters/sections is UNVERIFIED (host unreachable); by
  convention HTTP 404 is mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/missouri.md``):
whether every chapter TOC page renders identically (sampled Chapter 536),
the exact markup of chapter-listing "stub" entries for missing/repealed
sections (Chapter 536 contains none; stub rows without ``section=`` links
are skipped), and the live 404 page shape. None of these block the
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


class MissouriAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Revisor of Missouri
    publication of the Revised Statutes of Missouri at revisor.mo.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://revisor.mo.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title block on the home page: '<details ...> <summary ...> <span
    # class="lr-font-emph">Chs. 1-3</span> <span class="lr-font-emph">I
    # LAWS AND STATUTES</span> </summary> <body with chapter links> </details>'.
    _TITLE_BLOCK = re.compile(
        r"<details[^>]*>\s*<summary[^>]*>(.*?)</summary>(.*?)</details>",
        re.DOTALL,
    )
    # The two lr-font-emph spans inside a title summary. The second span's
    # content is '<roman>\u2003<name>'.
    _TITLE_SUMMARY_SPANS = re.compile(
        r'<span class="lr-font-emph">(.*?)</span>', re.DOTALL
    )
    # A chapter link inside a title block, e.g. '<a href="/main/
    # OneChapter.aspx?chapter=1">\u2003\u20031\u2003Laws in Force and
    # Construction of Statutes</a>'.
    _CHAPTER_LINK = re.compile(
        r'<a class="lr-font-emph" href="/main/OneChapter\.aspx\?chapter=([0-9]+)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # The leading '\u2003\u20031\u2003' chapter-number prefix on a chapter
    # link's label.
    _CHAPTER_NUMBER_PREFIX = re.compile(r"^\s*\u2003*\d+\u2003*\s*")

    # A section row on a chapter TOC page. Two alternatives: the section
    # anchor '<a href="/main/PageSelect.aspx?section=536.010&bid=...">' and
    # the name cell '<td>Definitions. <span>(8/28/2006)</span></td>'.
    _SECTION_ROW_LINK = re.compile(
        r'<a class="lr-font-emph" href="/main/PageSelect\.aspx\?section='
        r'([^&"]+)&[^"]*"[^>]*>(.*?)</a>'
    )
    _SECTION_NAME_CELL = re.compile(
        r"<td[^>]*>(.*?)</td>", re.DOTALL
    )

    # The per-section-page cross-check anchors.
    _TITLE_CROSSCHECK = re.compile(
        r"<p[^>]*>\s*Title\s+([IVXLCDM]+)\s+[^<]+</p>"
    )
    _CHAPTER_CROSSCHECK = re.compile(
        r'<a href="/main/PageSelect\.aspx\?chapter=([0-9]+)"'
    )
    # A nested inner span inside the heading bold span, e.g. the
    # '<span>  </span>' padding after the section number.
    _BOLD_INNER_SPAN = re.compile(r"<span[^>]*>.*?</span>", re.DOTALL)
    # The heading's trailing ' — ' separator after the section name.
    _HEADING_TRAILING_EMDASH = re.compile(r"\s*—\s*$")
    # The foot (history) block on a section page.
    _FOOT_DIV = re.compile(r'<div class="foot"[^>]*>(.*?)</div>', re.DOTALL)
    # The '--------' marker paragraph opening the foot history.
    _FOOT_MARKER = re.compile(r"<p[^>]*>.*?\u00ad*--------.*?</p>", re.DOTALL)
    # A structural repeal marker in place of body text, e.g. '(Repealed
    # L. 2024 S.B. 894 & 825)'.
    _REPEAL_MARKER = re.compile(r"^\(Repealed\b")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Missouri."""
        return "MO"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Missouri."""
        return "Missouri"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Revisor of Missouri URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/missouri.md):

        * Title: ``https://revisor.mo.gov/main/Home.aspx`` -- the home
          page. Titles have no URL of their own; ``list_chapters`` fetches
          the home page and filters by title block, so ``build_url``
          returns the home page for a :class:`TitleRef`.
        * Chapter: ``https://revisor.mo.gov/main/PageSelect.aspx?chapter={N}``
          -- the chapter TOC page (section listing).
        * Section: ``https://revisor.mo.gov/main/OneSection.aspx?section={S}``
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
            return (
                f"{self.BASE_URL}/main/OneSection.aspx?section={ref.identifier}"
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/main/PageSelect.aspx?chapter={ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/main/Home.aspx"
        else:
            raise UnsupportedRefError(
                f"MissouriAdapter.build_url does not support refs of type "
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
                does not resolve on the Revisor of Missouri site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Revisor of Missouri site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _extract_bold_span(cls, html: str) -> str | None:
        """Extract the inner content of the section page's ``<span
        class="bold">`` heading element.

        VERIFIED the heading is the section page's single
        ``<span class="bold">`` element, e.g. ``<span class="bold">
        536.050.<span> </span>Declaratory judgments ... — </span>``. The
        heading may contain a nested ``<span> </span>`` padding element
        after the section number (present on 536.050, absent on the
        repealed 536.303), so a depth scan is used to find the heading's
        own closing ``</span>`` rather than the nested one's.

        Args:
            html: The section page HTML.

        Returns:
            The heading's inner HTML (nested spans included), or None if
            no ``<span class="bold">`` element is present.
        """
        start = html.find('<span class="bold">')
        if start == -1:
            return None
        open_end = start + len('<span class="bold">')
        depth = 1
        i = open_end
        while i < len(html):
            next_open = html.find("<span", i)
            next_close = html.find("</span>", i)
            if next_close == -1:
                return None
            if next_open != -1 and next_open < next_close:
                depth += 1
                i = next_open + len("<span")
            else:
                depth -= 1
                if depth == 0:
                    return html[open_end:next_close]
                i = next_close + len("</span>")
        return None

    @classmethod
    def _bold_span_end(cls, html: str) -> int:
        """Return the character offset just past the section page's heading
        ``<span class="bold">...</span>``.

        Args:
            html: The section page HTML.

        Returns:
            The offset after the heading element's closing ``</span>``.

        Raises:
            NormalizationError: If no ``<span class="bold">`` element is
                present.
        """
        start = html.find('<span class="bold">')
        if start == -1:
            raise NormalizationError(
                "The section page contained no <span class='bold'> heading "
                "element; the site's structure may have changed."
            )
        open_end = start + len('<span class="bold">')
        depth = 1
        i = open_end
        while i < len(html):
            next_open = html.find("<span", i)
            next_close = html.find("</span>", i)
            if next_close == -1:
                raise NormalizationError(
                    "The section page's <span class='bold'> heading element "
                    "was not closed; the site's structure may have changed."
                )
            if next_open != -1 and next_open < next_close:
                depth += 1
                i = next_open + len("<span")
            else:
                depth -= 1
                if depth == 0:
                    return next_close + len("</span>")
                i = next_close + len("</span>")
        raise NormalizationError(
            "The section page's <span class='bold'> heading element was "
            "not closed; the site's structure may have changed."
        )

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def _title_blocks(self, html: str) -> list[tuple[str, str, str, int]]:
        """Parse the home page's 41 title blocks.

        Each returned tuple is ``(identifier, name, chapter_body_html,
        range_start)``: the Roman-numeral identifier (e.g. ``"XXXVI"``),
        the title name (e.g. ``"STATUTORY ACTIONS AND TORTS"``), the
        block body containing the chapter links, and the chapter-range
        start number used for sorting. Blocks whose summaries do not match
        the two-span title shape (e.g. the "Chapters Alphabetically"
        block) are skipped.

        Args:
            html: The home page HTML.

        Returns:
            A list of parsed title blocks in document order.
        """
        blocks = []
        for summary, body in self._TITLE_BLOCK.findall(html):
            spans = self._TITLE_SUMMARY_SPANS.findall(summary)
            if len(spans) < 2:
                continue
            # The second span is '<roman>\u2003<name>'. The EM SPACE
            # (\u2003) separator must be split on BEFORE whitespace
            # cleaning, since strip_tags collapses it to a plain space.
            raw_title = spans[1]
            em_space = raw_title.find("\u2003")
            if em_space == -1:
                continue
            identifier = strip_tags(raw_title[:em_space]).strip()
            name = strip_tags(raw_title[em_space + 1 :]).strip()
            if not identifier:
                continue
            range_text = self._clean_inner(spans[0])
            range_match = re.search(r"Chs\.\s*([0-9]+)", range_text)
            range_start = int(range_match.group(1)) if range_match else 0
            blocks.append((identifier, name, body, range_start))
        return blocks

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Revised Statutes of Missouri from
        the home page.

        The home page lists 41 titles, each as a ``<details>`` block whose
        summary carries the Roman-numeral identifier and name. The
        identifier is the Roman numeral (e.g. ``"XXXVI"``); the display
        name is the title name after the ``\u2003`` separator. The result
        is sorted by chapter-range start so titles order by their first
        chapter (I, II, ..., XLI).

        Returns:
            A sequence of :class:`TocNode`, one per title, in chapter-range
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the Roman numeral (e.g. ``"XXXVI"``) and
            whose ``name`` is the title name (e.g.
            ``"STATUTORY ACTIONS AND TORTS"``).

        Raises:
            AdapterUnavailableError: If the home page cannot be fetched or
                no usable title blocks could be parsed from it.
        """
        url = f"{self.BASE_URL}/main/Home.aspx"
        html = self._fetch_html(url, what="Missouri statutes home page")

        titles = []
        for identifier, name, _body, range_start in self._title_blocks(html):
            titles.append(
                (
                    TocNode(
                        level=HierarchyLevel.TITLE,
                        identifier=identifier,
                        name=name or identifier,
                        ref=TitleRef(
                            state_code=self.state_code, identifier=identifier
                        ),
                    ),
                    range_start,
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable title blocks in it; "
                "the site's structure may have changed."
            )

        return tuple(node for node, _start in sorted(titles, key=lambda t: t[1]))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the home page's
        title blocks.

        ``build_url(title_ref)`` returns the home page (titles have no URL
        of their own). The home page's title blocks are parsed, the block
        whose Roman-numeral identifier matches ``title_ref.identifier`` is
        located, and its ``OneChapter.aspx?chapter=N`` links are
        enumerated. The identifier is the ``chapter=N`` value (e.g.
        ``"536"``); the display name is the link text with the leading
        chapter number and ``\u2003`` runs stripped. The result is sorted
        numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"536"``) and whose
            ``name`` is the chapter name (e.g. ``"Administrative Procedure
            and Review"``).

        Raises:
            RefNotFoundError: If no title block matches ``title_ref``
                (the title does not resolve on the home page).
            AdapterUnavailableError: If the home page cannot be fetched for
                any other reason, or if the matched title block contains no
                usable chapter links.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Missouri statutes home page")

        matched_body = None
        for identifier, _name, body, _start in self._title_blocks(html):
            if identifier == title_ref.identifier:
                matched_body = body
                break

        if matched_body is None:
            raise RefNotFoundError(
                f"Could not find title {title_ref.identifier!r} in the "
                f"home page at {url!r}; the title does not resolve."
            )

        chapters = []
        seen: dict[str, None] = {}
        for number, label in self._CHAPTER_LINK.findall(matched_body):
            if number in seen:
                continue
            seen[number] = None
            name = self._CHAPTER_NUMBER_PREFIX.sub(
                "", self._clean_inner(label)
            ).strip() or number
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=number,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=number),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} and found title {title_ref.identifier!r}, "
                "but its block contained no usable chapter links; the "
                "site's structure may have changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        TOC page.

        ``build_url(chapter_ref)`` returns
        ``/main/PageSelect.aspx?chapter={N}``, which lists every section
        as table rows. The identifier is the dotted ``section=`` value
        (e.g. ``"536.010"``); the display name is the name cell text with
        its effective-date parenthetical preserved verbatim (e.g.
        ``"Definitions. (8/28/2006)"``). Rows without a ``section=`` link
        (e.g. stub rows for missing sections) are skipped. The result is
        sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per listed section, in
            numeric order. Each node's ``ref`` is a :class:`SectionRef`
            whose ``identifier`` is the dotted section number (e.g.
            ``"536.010"``) and whose ``name`` is the section's name as
            presented in the listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter TOC page cannot be
                fetched for any other reason, or if no usable section
                links could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Missouri section listing")

        sections = []
        seen: dict[str, None] = {}
        for row in html.split("<tr"):
            link = self._SECTION_ROW_LINK.search(row)
            if link is None:
                continue
            number = link.group(1)
            if number in seen:
                continue
            seen[number] = None
            cells = self._SECTION_NAME_CELL.findall(row)
            name = ""
            for cell in cells:
                text = self._clean_inner(cell)
                if text and text != self._clean_inner(link.group(2)):
                    name = text
                    break
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=number,
                    name=name or number,
                    ref=SectionRef(chapter=chapter_ref, identifier=number),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section links in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for chapter/section
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any dotted suffix -- the same convention the other adapters
        use -- so ``1, 2, 536, 538`` and ``536.010, 536.014, 536.320``
        order sensibly regardless of document order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Missouri.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the dotted section number, e.g. ``"536.050"``)
        appears verbatim within ``raw_citation`` (the ``RSMo § 536.050``
        citation). The stronger title/chapter cross-check against the
        source response happens in :meth:`retrieve_section`, which has the
        page's Title/Chapter anchors.

        ``status`` is set to ``REPEALED`` only when the heading is a
        structural repeal marker (``(Repealed ...)`` in place of body
        text, e.g. section 536.303) -- the framework's own rule for a
        structural signal. All other sections stay ``UNKNOWN``.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Missouri ref
                (``ref.state_code != "MO"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MissouriAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )

        if ref.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the parsed document: "
                f"{parsed.raw_citation!r}."
            )

        status = StatuteStatus.UNKNOWN
        if parsed.heading and self._REPEAL_MARKER.match(parsed.heading):
            status = StatuteStatus.REPEALED

        citation = Citation(
            state_code=self.state_code,
            raw=parsed.raw_citation,
        )

        return StatuteSection(
            ref=ref,
            citation=citation,
            heading=parsed.heading,
            text=parsed.text,
            status=status,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Revised Statutes of Missouri section,
        end to end: :meth:`build_url` -> fetch the section page ->
        cross-check the page's Title/Chapter anchors against ``ref`` ->
        parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/missouri.md): the heading is
        the ``<span class="bold">`` text with the leading ``NNN.NNN.``
        prefix and the trailing `` — `` separator stripped; the body is the
        region between the heading and the ``<div class="foot">`` history
        block; ``amendment_notes`` is the foot block content after the
        ``--------`` marker; a section whose body is entirely replaced by a
        ``(Repealed ...)`` marker is ``REPEALED``. The section page's
        Title/Chapter anchors are cross-checked against
        ``ref.chapter.title``/``ref.chapter`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be a Missouri ref
                (``ref.state_code == "MO"``); enforced by :meth:`normalize`,
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
                structure (title anchor, chapter anchor, heading) is
                missing, or the body is empty after cleaning without a
                structural repeal marker. Also raised by :meth:`normalize`
                if ``ref`` is not a Missouri ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Missouri section page")

        title_anchor = self._TITLE_CROSSCHECK.search(html)
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

        chapter_anchor = self._CHAPTER_CROSSCHECK.search(html)
        if chapter_anchor is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no Chapter "
                "anchor; the site's structure may have changed."
            )
        if chapter_anchor.group(1) != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section page: "
                f"{chapter_anchor.group(1)!r}."
            )

        bold_span = self._extract_bold_span(html)
        if bold_span is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._BOLD_INNER_SPAN.sub("", bold_span)
        heading = self._clean_inner(heading)
        heading = re.sub(
            rf"^\s*{re.escape(ref.identifier)}\.\s*", "", heading
        )
        heading = self._HEADING_TRAILING_EMDASH.sub("", heading).strip() or None

        body_start = self._bold_span_end(html)
        body_html = html[body_start:]
        foot = self._FOOT_DIV.search(body_html)
        if foot is not None:
            body_html = body_html[: foot.start()]

        text = strip_tags(body_html, preserve_block_breaks=True).strip()

        repealed = heading is not None and self._REPEAL_MARKER.match(heading)
        if not text and not repealed:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )
        if repealed:
            text = ""

        amendment_notes = None
        if foot is not None:
            marker = self._FOOT_MARKER.search(foot.group(1))
            if marker is not None:
                history_html = foot.group(1)[marker.end() :]
                amendment_notes = (
                    strip_tags(history_html, preserve_block_breaks=True).strip()
                    or None
                )

        raw_citation = f"RSMo § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
