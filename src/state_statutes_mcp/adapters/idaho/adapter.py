"""IdahoAdapter: the Idaho-specific concrete state adapter.

Source: the official Idaho Legislature publication of the Idaho Code at
``https://legislature.idaho.gov`` -- anonymous, server-rendered HTML with no
authentication or API key (no SPA framework, no client-side statute
rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/idaho.md``,
which documents the official ``legislature.idaho.gov`` HTML captured
through Wayback Machine snapshots of the official host, timestamp
20260712203433; the live host itself is unreachable from this environment):

* Base URL ``https://legislature.idaho.gov`` with statutory pages under
  ``/statutesrules/idstat/``.
* Titles: the statutes index page (``/statutesrules/idstat/``) lists all 74
  titles as table rows ``<a href="/statutesrules/idstat/Title{N}">TITLE
  {N}</a>`` with the title name in the third ``<td>``. The title identifier
  is the number in the href (e.g. ``"18"``).
* Chapters: a title page (``/idstat/Title{N}``) lists every chapter of the
  title as table rows ``<a href=".../Title{N}/T{N}CH{CH}">CHAPTER {CH}</a>``
  with the chapter name in the third ``<td>``. The chapter identifier is the
  number in the href (e.g. ``"40"``).
* Sections: a chapter page (``/idstat/Title{N}/T{N}CH{CH}``) lists every
  section of the chapter as table rows ``<a href=".../SECT{sec}">{sec}</a>``
  with the section name in the third ``<td>``. The section identifier is the
  full ``{title}-{chapter}{local}`` form exactly as the links name it (e.g.
  ``"18-4001"``, ``"18-4004A"``).
* Section content: ``/idstat/Title{N}/T{N}CH{CH}/SECT{sec}`` -- one section
  per page. Verified structure (for 18-4001 and 18-4003):
  * Cross-check anchors: ``<title>Section {sec} &#8211; Idaho State
    Legislature</title>`` and the breadcrumb
    ``... / Title {N} / Chapter {CH} / Section {sec}``.
  * The content region opens with centered ``TITLE {N}``/``CHAPTER {CH}``
    headers, then the section body whose first ``<div>`` holds
    ``<span class="f11s" ...>{sec}.&nbsp;&nbsp;<span style="text-transform:
    uppercase">{Heading}&nbsp;</span>{body}</span>``. The heading is the
    ``text-transform: uppercase`` span text; the body is the remaining text
    of that first paragraph plus any subsequent subsection ``<div>``s
    (``(a)`` through ``(g)`` for 18-4003).
  * History: a ``History:`` label div followed by a ``<span class="f11s">``
    holding the session-law line ``[18-4001, added 1972, ch. 336, sec. 1,
    p. 928; am. ...]``, preserved verbatim as ``amendment_notes``.
* Citation: ``Idaho Code § {title}-{chapter}{local}`` (e.g. ``Idaho Code §
  18-4001``), adapter-constructed; the ``Idaho Code`` abbreviation is
  INFERENCE from standard Idaho citation usage (the site itself says "Idaho
  Statutes" in its header), and the section number is VERIFIED from the
  site's own links and section heading. ``SectionRef.identifier`` is the
  full ``{title}-{chapter}{local}`` form.
* Error boundary: a nonexistent section returns HTTP 404 (verified through
  the Wayback snapshot, ``/SECT18-9999/`` -> 404), mapped here to
  ``RefNotFoundError``. A missing title/chapter is expected to 404 as well
  (INFERENCE from the section 404 and the consistent resource-per-level
  scheme).

**UNVERIFIED / accepted limitations** (documented in
``docs/research/idaho.md``): whether every title keeps the same table-row
markup as Title 18 and every chapter the same as Chapter 40 (sampled), and
whether any section page renders differently from the current-section form
verified (e.g. repealed/reserved sections). None of these block the
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
from state_statutes_mcp.models.statute_section import StatuteSection


class IdahoAdapter(BaseStateAdapter):
    """Concrete state adapter for the Idaho Legislature statutes
    publication at legislature.idaho.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape already
    established by ``WashingtonAdapter``, ``OhioAdapter``, and
    ``RhodeIslandAdapter``. See the module docstring for the verified site
    structure this adapter is built against.
    """

    BASE_URL = "https://legislature.idaho.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A generic table row on an index/title/chapter page, e.g. on the
    # statutes index page:
    #   '<tr><td valign="top" nowrap="true"><a href="/statutesrules/idstat/
    #    Title1">TITLE 1</a></td><td valign="top">&#160;&#160;</td><td
    #    valign="top"> COURTS AND COURT OFFICIALS  </td></tr>'
    # Captures the href, the link text, and the third <td> (the name).
    _TABLE_ROW = re.compile(
        r'<td valign="top" nowrap="true"><a href="(/statutesrules/idstat/[^"]+)">'
        r"([^<]*)</a></td>\s*<td valign=\"top\">&#160;&#160;</td>\s*"
        r'<td valign="top">\s*(.*?)\s*</td>',
        re.DOTALL,
    )

    # The title/chapter number inside a title-page or chapter-page href.
    _TITLE_NUMBER = re.compile(r"/statutesrules/idstat/Title(\d+)")
    # The chapter number inside a chapter-page href.
    _CHAPTER_NUMBER = re.compile(r"/T\d+CH(\d+)")
    # The section identifier inside a section-page href.
    _SECTION_NUMBER = re.compile(r"/SECT([0-9]+-[0-9]+[A-Z]?)")

    # Cross-check anchors on the section page.
    _TITLE_CRUMB = re.compile(r'title="Browse to: Title (\d+)">Title \d+</a>')
    _CHAPTER_CRUMB = re.compile(r'title="Browse to: Chapter (\d+)">Chapter \d+</a>')
    _TITLE_TAG = re.compile(r"<title>Section ([0-9]+-[0-9]+[A-Z]?) &#8211;")

    # The section body marker: the section identifier with trailing period
    # inside the content <div>.
    _SECTION_MARKER = re.compile(
        r'<span class="f11s" style="font-family: Courier New;">([0-9]+-[0-9]+[A-Z]?)\.'
    )
    # The heading span inside the first content <div>.
    _HEADING = re.compile(r'<span style="text-transform: uppercase">(.*?)</span>')
    # The History: label span that delimits the end of the body.
    _HISTORY_LABEL = re.compile(
        r'<span style="font-size: 11pt; font-family: Courier New;">History:</span>'
    )
    # The session-law line span that follows the History: label.
    _HISTORY_TEXT = re.compile(
        r'<span class="f11s" style="font-family: Courier New;">(.*?)</span>'
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Idaho."""
        return "ID"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Idaho."""
        return "Idaho"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Idaho Legislature URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/idaho.md):

        * Title: ``https://legislature.idaho.gov/statutesrules/idstat/Title{N}``
          -- the title page (chapter listing).
        * Chapter: ``https://legislature.idaho.gov/statutesrules/idstat/
          Title{N}/T{N}CH{CH}`` -- the chapter page (section listing).
        * Section: ``https://legislature.idaho.gov/statutesrules/idstat/
          Title{N}/T{N}CH{CH}/SECT{sec}`` -- the section's own page.

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
                f"{self.BASE_URL}/statutesrules/idstat/Title{title}/"
                f"T{title}CH{ref.chapter.identifier}/SECT{ref.identifier}"
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/statutesrules/idstat/Title"
                f"{ref.title.identifier}/T{ref.title.identifier}CH{ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/statutesrules/idstat/Title{ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"IdahoAdapter.build_url does not support refs of type "
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
        invalid chapter/section) into :class:`RefNotFoundError` -- the
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
                does not resolve on the Idaho Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Idaho Legislature site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _numeric_sort_key(cls, identifier: str) -> tuple[int, ...]:
        """Sort key for Idaho identifiers: split the dotted/dashed number
        into its numeric parts so 18-4001 sorts before 18-4011. Handles the
        optional trailing letter (``18-4004A``) by appending the raw
        identifier as a final string tie-break."""
        parts = []
        for chunk in re.split(r"[\-.]+", identifier):
            match = re.match(r"(\d+)(.*)", chunk)
            if match:
                parts.append(int(match.group(1)))
                parts.append(match.group(2))
            else:
                parts.append(chunk)
        return (tuple(parts), identifier)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Idaho Code from the statutes index
        page.

        The index page (``/statutesrules/idstat/``) lists all 74 titles as
        table rows. The identifier is the number in the ``Title{N}`` href;
        the name is the third ``<td>`` text.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"18"``) and whose
            ``name`` is the title name (e.g. ``"CRIMES AND PUNISHMENTS"``).

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched, or
                if no usable title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/statutesrules/idstat/"
        html = self._fetch_html(url, what="Idaho statutes index page")

        titles = []
        seen: dict[str, None] = {}
        for href, _link_text, name in self._TABLE_ROW.findall(html):
            number = self._TITLE_NUMBER.search(href)
            if number is None:
                continue
            identifier = number.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=" ".join(self._clean_inner(name).split()) or identifier,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable title rows in it; the "
                "site's structure may have changed."
            )

        return tuple(
            sorted(titles, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title page.

        The title page (``/idstat/Title{N}``) lists every chapter of the
        title as table rows. The identifier is the number in the
        ``T{N}CH{CH}`` href; the name is the third ``<td>`` text.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"40"``) and whose
            ``name`` is the chapter name (e.g. ``"HOMICIDE"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched for
                any other reason, or if no usable chapter rows could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Idaho chapter listing")

        chapters = []
        seen: dict[str, None] = {}
        for href, _link_text, name in self._TABLE_ROW.findall(html):
            number = self._CHAPTER_NUMBER.search(href)
            if number is None:
                continue
            identifier = number.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=" ".join(self._clean_inner(name).split()) or identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter rows in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(
            sorted(chapters, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        page's section table.

        The chapter page (``/idstat/Title{N}/T{N}CH{CH}``) lists every
        section of the chapter as table rows. The identifier is the full
        ``{title}-{chapter}{local}`` href suffix (e.g. ``"18-4001"``,
        ``"18-4004A"``); the name is the third ``<td>`` text.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full section number (e.g. ``"18-4001"``)
            and whose ``name`` is the section's name as presented in the
            listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section rows could be
                parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Idaho section listing")

        sections = []
        seen: dict[str, None] = {}
        for href, _link_text, name in self._TABLE_ROW.findall(html):
            number = self._SECTION_NUMBER.search(href)
            if number is None:
                continue
            identifier = number.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=" ".join(self._clean_inner(name).split()) or identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section rows in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(
            sorted(sections, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Idaho.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the section number, e.g. ``"18-4001"``) appears
        verbatim within ``raw_citation`` (the ``Idaho Code § 18-4001``
        citation). The stronger cross-check against the source response
        happens in :meth:`retrieve_section`, which has the page's title tag
        and breadcrumb in hand.

        ``status`` is always left at its default (``UNKNOWN``): Idaho
        section pages carry no structural repealed/amended/renumbered signal
        for current sections, and the contract forbids inferring status from
        prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Idaho ref
                (``ref.state_code != "ID"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"IdahoAdapter.normalize cannot normalize a ref for state "
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
    # retrieve_section
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Idaho Code section, end to end:
        :meth:`build_url` -> fetch the section page -> cross-check the
        page's ``<title>`` tag and breadcrumb title/chapter links against
        ``ref`` -> parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/idaho.md): the ``<title>``
        tag is ``Section {sec} &#8211; Idaho State Legislature``; the
        breadcrumb links ``Title {N}``/``Chapter {CH}`` precede the content.
        The heading is the ``<span style="text-transform: uppercase">`` text
        inside the first content ``<div>``; the body is the remaining text of
        that paragraph plus any subsequent subsection ``<div>``s, all before
        the ``History:`` label. ``amendment_notes`` is the ``<span
        class="f11s">`` session-law line that follows the ``History:`` label,
        preserved verbatim.

        Args:
            ref: The section to retrieve. Must be an Idaho ref
                (``ref.state_code == "ID"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's ``<title>`` tag or breadcrumb
                title/chapter links disagree with ``ref``. Also raised by
                :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body, cross-check anchors) is missing,
                or the body is empty after cleaning. Also raised by
                :meth:`normalize` if ``ref`` is not an Idaho ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Idaho section page")

        title_crumb = self._TITLE_CRUMB.search(html)
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

        chapter_crumb = self._CHAPTER_CRUMB.search(html)
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

        title_tag = self._TITLE_TAG.search(html)
        if title_tag is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no title tag; the site's "
                "structure may have changed."
            )
        if title_tag.group(1) != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched section page: {title_tag.group(1)!r}."
            )

        marker = self._SECTION_MARKER.search(html)
        if marker is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no section body marker; the "
                "site's structure may have changed."
            )
        body_start = marker.end()

        history = self._HISTORY_LABEL.search(html, body_start)
        body_end = history.start() if history is not None else len(html)

        body = html[body_start:body_end]
        heading_match = self._HEADING.search(body)
        if heading_match is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its section body contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._clean_inner(heading_match.group(1)) or None

        body = self._HEADING.sub("", body)
        text = strip_tags(body, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        if history is not None:
            history_match = self._HISTORY_TEXT.search(html, history.end())
            if history_match is not None:
                cleaned = self._clean_inner(history_match.group(1))
                if cleaned:
                    amendment_notes = cleaned

        raw_citation = f"Idaho Code § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
