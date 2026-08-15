"""OhioAdapter: the Ohio-specific concrete state adapter.

Source: the official Ohio Laws publication of the Ohio Revised Code (ORC)
at ``https://codes.ohio.gov`` -- anonymous, server-rendered HTML with no
authentication or API key (no SPA framework, no client-side statute
rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/ohio.md``,
which documents the official ``codes.ohio.gov`` HTML captured through a
Wayback Machine snapshot of the official host, timestamp 20260812050041;
the live host itself is unreachable from this environment):

* Base URL ``https://codes.ohio.gov`` with statutory pages under
  ``/ohio-revised-code/``.
* Titles: the ORC index page (``/ohio-revised-code``) lists all 33 numbered
  titles (1, 3, 5, ..., 63 -- all odd) as ``<a href="ohio-revised-code/
  title-{N}">Title {N} | {Name}</a>`` inside ``td.name-cell`` rows. The
  title identifier is the number in the href; the name is the text after
  the ``|`` separator. An unnumbered ``General Provisions`` entry on the
  index page (href ``ohio-revised-code/general-provisions``) is excluded
  because it is not a numbered title.
* Chapters: a title page (``/ohio-revised-code/title-{N}``) lists every
  chapter of the title as ``<a href="chapter-{NNNN}">Chapter {NNNN} |
  {Name}</a>``. Chapter numbers are the 4-digit prefix of the section
  numbers in that title (Title 29 -> 2901, 2903, ..., 2981).
* Sections: a chapter page (``/ohio-revised-code/chapter-{NNNN}``) lists
  every section of the chapter in a discovery table as ``<a href="section-
  {NNNN.NN}">Section {NNNN.NN} | {Name}</a>``. The full section text is
  also embedded lower in the page; the adapter parses only the discovery
  table for ``list_sections``.
* Section content: ``/ohio-revised-code/section-{NNNN.NN}`` (e.g.
  ``/ohio-revised-code/section-2901.01``) -- one file per section. Verified
  structure (for 2901.01 and the decimal-extension 2901.011):
  * Cross-check anchors: breadcrumbs ``<a href="/ohio-revised-code/
    title-29">Title 29 ...</a>`` and ``<a href="/ohio-revised-code/
    chapter-2901">Chapter 2901 ...</a>`` appear before the section content.
  * Heading ``<h1>Section 2901.01 <span class='codes-separator'>|</span>
    General provisions definitions.</h1>`` (the text after the ``|``
    separator is the heading; the ``Section {id} `` prefix is not).
  * Body: ``<section class="laws-body">`` containing ``<span><p>...</p>
    </span>`` -- one ``<p>`` per paragraph; the separate ``div.laws-notice``
    ("Last updated ...") sits after the closing ``</span>`` and is excluded.
  * History: ``<section class="laws-history">`` "Available Versions of this
    Section" listing each prior version as ``<li><span>{date} &ndash;
    {legislation}</span></li>`` (e.g. ``October 3, 2023 &ndash; Amended  by
    House Bill 33 - 135th General Assembly``). The version list is
    preserved verbatim (newline-joined) as ``amendment_notes``; ``status``
    stays ``UNKNOWN``.
* Citation: ``Ohio Rev. Code § {section}`` (e.g. ``Ohio Rev. Code §
  2901.01``), adapter-constructed (the ``Ohio Rev. Code`` abbreviation is
  INFERENCE from standard Ohio citation usage; the number is verified from
  the site's own h1 heading). ``SectionRef.identifier`` is the full
  ``{chapter}.{local}`` form as it appears in the URL (e.g. ``"2901.01"``,
  ``"2901.011"``).
* Error boundary: a nonexistent section returns HTTP 404 (verified via the
  Wayback capture), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/ohio.md``):
whether every title page keeps the same chapter-row markup and every
chapter page the same section-list markup (sampled Title 29 and Chapter
2901), and whether any repealed/reserved section renders differently from
the current-section form. None of these block the implementation below.
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


class OhioAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Ohio Laws publication of
    the Ohio Revised Code at codes.ohio.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://codes.ohio.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title link on the ORC index page, e.g. '<a href="ohio-revised-code/title-29">Title 29 <span class='codes-separator'>|</span> Crimes-Procedure</a>'.
    # The title identifier is the number in the href; the name is the text
    # after the '|' separator.
    _TITLE_LINK = re.compile(
        r'<a href="ohio-revised-code/title-(\d+)">\s*Title\s+\d+.*?'
        r"<span class='codes-separator'>\|</span>\s*([^<]*)</a>"
    )

    # A chapter link on a title page, e.g. '<a href="chapter-2901">Chapter 2901 <span class='codes-separator'>|</span> General Provisions</a>'.
    _CHAPTER_LINK = re.compile(
        r'<a href="chapter-(\d+)">\s*Chapter\s+\d+.*?'
        r"<span class='codes-separator'>\|</span>\s*([^<]*)</a>"
    )

    # A section link in a chapter page's discovery table, e.g. '<a href="section-2901.01">Section 2901.01 <span class='codes-separator'>|</span> General provisions definitions.</a>'.
    # The relative 'section-{id}' href distinguishes table rows from the
    # absolute cross-reference links ('/ohio-revised-code/section-...')
    # embedded in section bodies and from the dated version links.
    _SECTION_LINK = re.compile(
        r'<a href="section-([\d.]+)">\s*Section\s+[\d.]+.*?'
        r"<span class='codes-separator'>\|</span>\s*([^<]*)</a>"
    )

    # The h1 heading on a section page, e.g. '<h1>Section 2901.01 <span class='codes-separator'>|</span> General provisions definitions.</h1>'.
    _SECTION_H1 = re.compile(
        r"<h1>Section\s+([\d.]+)\s*<span class='codes-separator'>\|</span>\s*(.*?)</h1>",
        re.DOTALL,
    )
    # The breadcrumb cross-check anchors on a section page.
    _BREADCRUMB_TITLE = re.compile(
        r'<a href="/ohio-revised-code/title-(\d+)">'
    )
    _BREADCRUMB_CHAPTER = re.compile(
        r'<a href="/ohio-revised-code/chapter-(\d+)">'
    )
    # The body region on a section page: '<section class="laws-body">' then
    # '<span><p>...</p></span>' (the notice div comes after the span).
    _LAWS_BODY_SPAN = re.compile(
        r'<section class="laws-body">\s*<span>(.*?)</span>', re.DOTALL
    )
    # The history region on a section page: '<section class="laws-history">
    # ... <li><span>{version}</span></li> ...'. Captured verbatim.
    _LAWS_HISTORY = re.compile(
        r'<section class="laws-history">(.*?)</section>', re.DOTALL
    )
    _HISTORY_ITEM = re.compile(r"<span>([^<]*)</span>")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Ohio."""
        return "OH"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Ohio."""
        return "Ohio"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Ohio Laws URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/ohio.md):

        * Title: ``https://codes.ohio.gov/ohio-revised-code/title-{N}``
          -- the title page (chapter listing).
        * Chapter: ``https://codes.ohio.gov/ohio-revised-code/chapter-{NNNN}``
          -- the chapter page (section listing).
        * Section: ``https://codes.ohio.gov/ohio-revised-code/section-{NNNN.NN}``
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
            return f"{self.BASE_URL}/ohio-revised-code/section-{ref.identifier}"
        elif isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/ohio-revised-code/chapter-{ref.identifier}"
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/ohio-revised-code/title-{ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"OhioAdapter.build_url does not support refs of type "
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
        invalid title/chapter/section) into :class:`RefNotFoundError` -- the
        source was reached, but the addressed document does not resolve.

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
                does not resolve on the Ohio Laws site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Ohio Laws site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _numeric_sort_key(cls, identifier: str) -> tuple[int, str]:
        """Sort key for Ohio identifiers: the integer leading part first
        (so 2903 sorts after 2901), then the full identifier for a stable
        tie-break. Handles dotted section ids (2901.01, 2901.011) and
        plain chapter/title numbers."""
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every numbered title of the Ohio Revised Code from the
        ORC index page.

        The index page lists 33 numbered titles (1, 3, 5, ..., 63), each as
        an ``ohio-revised-code/title-{N}`` link. The identifier is the
        number in the href; the display name is the text after the ``|``
        separator. The unnumbered ``General Provisions`` entry is excluded
        because it has no ``title-{N}`` href. The result is sorted
        numerically.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"29"``) and whose
            ``name`` is the title name (e.g. ``"Crimes-Procedure"``).

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched or
                no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/ohio-revised-code"
        html = self._fetch_html(url, what="Ohio Revised Code index page")

        titles = []
        seen: dict[str, None] = {}
        for identifier, name in self._TITLE_LINK.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name.strip() or identifier,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable title links in it; the "
                "site's structure may have changed."
            )

        return tuple(sorted(titles, key=lambda node: self._numeric_sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title page.

        The title page lists every chapter of the title as
        ``chapter-{NNNN}`` links (the 4-digit chapter number that prefixes
        the title's section numbers). The identifier is the number in the
        href; the display name is the text after the ``|`` separator. The
        result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"2901"``) and whose
            ``name`` is the chapter name (e.g. ``"General Provisions"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched for
                any other reason, or if no usable chapter links could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Ohio chapter listing")

        chapters = []
        seen: dict[str, None] = {}
        for identifier, name in self._CHAPTER_LINK.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name.strip() or identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter links in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._numeric_sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        page's discovery table.

        The chapter page lists every section of the chapter in a discovery
        table as ``section-{NNNN.NN}`` links. The identifier is the number
        in the href; the display name is the text after the ``|`` separator.
        The relative ``section-{id}`` href distinguishes table rows from the
        absolute cross-reference links and dated version links elsewhere on
        the page. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full section number (e.g. ``"2901.01"``,
            ``"2901.011"``) and whose ``name`` is the section's name as
            presented in the listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section links could be
                parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Ohio section listing")

        sections = []
        seen: dict[str, None] = {}
        for identifier, name in self._SECTION_LINK.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name.strip() or identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section links in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._numeric_sort_key(node.identifier)))

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Ohio.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the section number, e.g. ``"2901.01"``) appears
        verbatim within ``raw_citation`` (the ``Ohio Rev. Code § 2901.01``
        citation). The stronger title/chapter cross-check against the source
        response happens in :meth:`retrieve_section`, which has the page's
        breadcrumb anchors.

        ``status`` is always left at its default (``UNKNOWN``): Ohio section
        pages carry no structural repealed/amended/renumbered signal for
        current sections, and the contract forbids inferring status from
        prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Ohio ref
                (``ref.state_code != "OH"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"OhioAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Ohio Revised Code section, end to
        end: :meth:`build_url` -> fetch the section page -> cross-check the
        page's h1 heading and breadcrumb title/chapter links against ``ref``
        -> parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/ohio.md): the heading is the
        text after the ``|`` separator in the ``<h1>Section {id} | {heading}
        </h1>``; the body is the ``<span>`` inside ``<section class="laws-
        body">`` (one ``<p>`` per paragraph; the trailing ``laws-notice``
        div is excluded); ``amendment_notes`` is the ``laws-history``
        version list (newline-joined, verbatim). The page's breadcrumb
        title/chapter links are cross-checked against
        ``ref.chapter.title``/``ref.chapter`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be an Ohio ref
                (``ref.state_code == "OH"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's h1 heading or breadcrumb
                title/chapter links disagree with ``ref``. Also raised by
                :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body, cross-check anchors) is missing,
                or the body is empty after cleaning. Also raised by
                :meth:`normalize` if ``ref`` is not an Ohio ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Ohio section page")

        title_crumb = self._BREADCRUMB_TITLE.search(html)
        if title_crumb is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no title "
                "breadcrumb anchor; the site's structure may have changed."
            )
        if title_crumb.group(1) != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section page: "
                f"{title_crumb.group(1)!r}."
            )

        chapter_crumb = self._BREADCRUMB_CHAPTER.search(html)
        if chapter_crumb is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no chapter "
                "breadcrumb anchor; the site's structure may have changed."
            )
        if chapter_crumb.group(1) != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section page: "
                f"{chapter_crumb.group(1)!r}."
            )

        h1 = self._SECTION_H1.search(html)
        if h1 is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no section heading element; the "
                "site's structure may have changed."
            )
        if h1.group(1) != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched section page: {h1.group(1)!r}."
            )
        heading = self._clean_inner(h1.group(2)) or None

        body_span = self._LAWS_BODY_SPAN.search(html)
        if body_span is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no body region; the site's "
                "structure may have changed."
            )
        text = strip_tags(
            body_span.group(1), preserve_block_breaks=True
        ).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        history = self._LAWS_HISTORY.search(html)
        if history is not None:
            items = [
                self._clean_inner(item)
                for item in self._HISTORY_ITEM.findall(history.group(1))
            ]
            items = [item for item in items if item]
            if items:
                amendment_notes = "\n".join(items)

        raw_citation = f"Ohio Rev. Code § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
