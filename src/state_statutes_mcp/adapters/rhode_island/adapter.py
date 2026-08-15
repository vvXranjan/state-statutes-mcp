"""RhodeIslandAdapter: the Rhode Island-specific concrete state adapter.

Source: the official Rhode Island General Assembly publication of the
General Laws of Rhode Island at ``http://webserver.rilegislature.gov`` --
anonymous, server-rendered HTML with no authentication or API key (no SPA
framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/rhode_island.md``,
which documents the official ``webserver.rilegislature.gov`` HTML captured
through a Wayback Machine snapshot of the official host, timestamp
20250401074949; the live host itself is unreachable from this environment):

* Base URL ``http://webserver.rilegislature.gov`` with the statutory tree
  under ``/Statutes/``.
* Titles: the master page (``/Statutes/Statutes.html``) lists all 47
  titles -- numbered 1-47 plus lettered ``6A`` and decimal ``40.1`` -- as
  absolute links to ``/Statutes/TITLE{n}/INDEX.HTM``. The title identifier
  is the number between ``TITLE`` and ``/INDEX.HTM``; the name sits in the
  table cell adjacent to the link cell (e.g. Title 43 is ``Statutes and
  Statutory Construction``).
* Chapters: a title index page (``/Statutes/TITLE{n}/INDEX.HTM``) lists
  every chapter of the title as ``<a href="{t}-{c}/INDEX.htm">Chapter
  {t}-{c}&nbsp;{Name}</a>``. The chapter identifier is the full
  ``{t}-{c}`` directory prefix (e.g. ``43-3``, ``6A-2.1``, ``40.1-1.1``);
  the name is the text after the leading ``Chapter {id}&nbsp;`` prefix.
* Sections: a chapter index page (``/Statutes/TITLE{n}/{t}-{c}/INDEX.htm``)
  lists every section of the chapter as ``<a href="{t}-{c}-{s}.htm">
  &sect;&nbsp;{t}-{c}-{s}.&nbsp;{Name}</a>``. The section identifier is the
  full citation ``{t}-{c}-{s}`` (e.g. ``43-3-2``, ``43-3-3.1``); the name
  is the text after the leading ``&sect;&nbsp;{id}.&nbsp;`` prefix.
* Section content: ``/Statutes/TITLE{n}/{t}-{c}/{t}-{c}-{s}.htm`` -- one
  file per section. Verified structure (for 43-3-2, the decimal 43-3-3.1,
  and the repealed 43-3-7):
  * Cross-check anchors: ``<h1>`` holds ``Title {n}`` (the title number),
    and ``<h3>`` holds the full citation ``R.I. Gen. Laws &sect; {t}-{c}-{s}``.
    NOTE: the ``<h2>`` chapter anchor uses the LOCAL chapter number (``3``)
    not the full ``43-3`` form, so chapter identity is cross-checked through
    the ``<h3>`` citation instead.
  * Heading: ``<p style="margin-left:0px"><b>&sect;&nbsp;43-3-2.&nbsp;
    Application of rules of construction.</b></p>`` -- the heading is the
    bold text with the leading ``&sect;&nbsp;{id}.&nbsp;`` prefix stripped.
  * Body: the ``<p style="margin-left:0px">`` paragraphs between the heading
    paragraph and the history block.
  * History: ``<p>History of Section.<br>{text}</p>`` -- the text after the
    ``History of Section.<br>`` marker is preserved verbatim as
    ``amendment_notes``.
  * Repealed section 43-3-7: heading ``&sect;&nbsp;43-3-7.&nbsp;Repealed.``
    and NO body paragraph -- a structural repeal signal (a "Repealed."
    marker in place of body text), so ``status`` is ``REPEALED`` and
    ``text`` is empty, following the framework rule and the
    MissouriAdapter precedent. A second repealed form (section 40.1-1-1)
    uses a repealed-range heading ``&sect;&nbsp;40.1-1-1 — 40.1-1-3.
    &nbsp;[Repealed.]`` with the same empty body; the heading's leading
    citation prefix (single-id or range form) is stripped by
    ``_HEADING_ID_PREFIX`` and the bracketed ``[Repealed.]`` marker is
    matched by ``_REPEAL_MARKER`` the same way.
* Citation: ``R.I. Gen. Laws &sect; {t}-{c}-{s}`` (e.g. ``R.I. Gen. Laws
  &sect; 43-3-2``), adapter-constructed; the ``R.I. Gen. Laws`` abbreviation
  is VERIFIED from the site's own ``<h3>`` citation text. ``SectionRef
  .identifier`` is the full ``{t}-{c}-{s}`` form as it appears in the URL.
* Error boundary: a nonexistent section returns HTTP 404 (verified via the
  Wayback capture), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/rhode_island.md``):
whether every title index page keeps the same chapter-row markup and every
chapter index page the same section-row markup (sampled Titles 43, 6A, and
40.1; chapter 43-3), and whether repealed sections beyond 43-3-7 drop the
body paragraph entirely. None of these block the implementation below.
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
from state_statutes_mcp.models.statute_section import (
    StatuteSection,
    StatuteStatus,
)


class RhodeIslandAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Rhode Island General Assembly
    publication of the General Laws at webserver.rilegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape already
    established by the other adapters. See the module docstring for the
    verified site structure this adapter is built against.
    """

    BASE_URL = "http://webserver.rilegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title row on the master page, e.g. a link cell
    # '<td ...><p align="center"><span ...><a href="http://webserver.rilegislature.gov//Statutes/TITLE43/INDEX.HTM" class="homeLinks">43</a></span></p></td>'
    # followed by the name cell '<td ...><p><span ...>&nbsp;&nbsp;Statutes and Statutory Construction</span></p></td>'.
    # The identifier is the text between 'TITLE' and '/INDEX.HTM' (1-47, 6A, 40.1).
    _TITLE_ROW = re.compile(
        r'TITLE([0-9.]+[A-Z]?)/INDEX\.HTM" class="homeLinks">[^<]*</a></span></p></td>'
        r"\s*<td[^>]*>\s*<p>(.*?)</p></td>",
        re.DOTALL,
    )

    # A chapter link on a title index page, e.g.
    # '<a href="43-1/INDEX.htm">Chapter 43-1&nbsp;Action by Governor</a>'.
    # The identifier is the full '{t}-{c}' directory prefix.
    _CHAPTER_LINK = re.compile(
        r'<a href="([0-9.]+[A-Z]?-\d+(?:\.\d+)?)/INDEX\.htm"[^>]*>'
        r"Chapter\s+[^<]*?&nbsp;(.*?)</a>",
        re.DOTALL,
    )

    # A section link on a chapter index page, e.g.
    # '<a href="43-3-2.htm">&sect;&nbsp;43-3-2.&nbsp;Application of rules of construction.</a>'.
    # The raw HTML uses a literal U+00A7 section sign (not the '&sect;'
    # entity), so the link text begins '§&nbsp;{id}.&nbsp;'.
    # The identifier is the full '{t}-{c}-{s}' file stem.
    _SECTION_LINK = re.compile(
        r'<a href="([0-9.]+[A-Z]?-\d+-\d+(?:\.\d+)?)\.htm"[^>]*>'
        r"§&nbsp;[^<]*?&nbsp;(.*?)</a>",
        re.DOTALL,
    )

    # The section page's title anchor: '<h1><center>Title 43<br>...'.
    _TITLE_CROSSCHECK = re.compile(r"<h1>\s*<center>Title\s+([0-9.]+[A-Z]?)\s*<br>")
    # The section page's citation anchor: '<h3>R.I. Gen. Laws &sect; 43-3-2</h3>'.
    _CITATION_CROSSCHECK = re.compile(
        r"<h3>(.*?)</h3>", re.DOTALL
    )
    # The heading paragraph on a section page:
    # '<p style="margin-left:0px"><b>&sect;&nbsp;43-3-2.&nbsp;Application of rules of construction.</b></p>'.
    _HEADING_P = re.compile(
        r'<p style="margin-left:0px"><b>(.*?)</b></p>', re.DOTALL
    )
    # The history block: '<p>History of Section.<br>{text}</p>'.
    _HISTORY_BLOCK = re.compile(
        r"<p>History of Section\.<br>(.*?)</p>", re.DOTALL
    )
    # A structural repeal marker in place of body text, e.g. 'Repealed.' or
    # '[Repealed.]' (the bracketed form is used by repealed-range sections
    # such as 40.1-1-1 -- 40.1-1-3).
    _REPEAL_MARKER = re.compile(r"^\[?Repealed\.?\]?$")
    # The leading citation prefix of a section heading paragraph, which is
    # stripped before the heading is kept. Covers both the single-section
    # form ('§ 43-3-2. Application of rules of construction.') and the
    # repealed-range form ('§ 40.1-1-1 — 40.1-1-3. [Repealed.]'). A Rhode
    # Island section id is '{t}-{c}-{s}' where {t} may be a decimal
    # (40.1) or lettered (6A) title and {c}/{s} may carry decimal
    # extensions.
    _HEADING_ID_PREFIX = re.compile(
        r"^\s*§\s*[\d.]+[A-Z]?-\d+(?:\.\d+)?-\d+(?:\.\d+)?"
        r"(?:\s*(?:—|--|–|-)\s*[\d.]+[A-Z]?-\d+(?:\.\d+)?-\d+(?:\.\d+)?)?"
        r"\s*\.\s*"
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Rhode Island."""
        return "RI"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Rhode Island."""
        return "Rhode Island"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Rhode Island General Assembly URL for
        ``ref``.

        VERIFIED endpoint shapes (see docs/research/rhode_island.md):

        * Title: ``http://webserver.rilegislature.gov/Statutes/TITLE{n}/INDEX.HTM``
          -- the title index page (chapter listing).
        * Chapter: ``http://webserver.rilegislature.gov/Statutes/TITLE{n}/{t}-{c}/INDEX.htm``
          -- the chapter index page (section listing).
        * Section: ``http://webserver.rilegislature.gov/Statutes/TITLE{n}/{t}-{c}/{t}-{c}-{s}.htm``
          -- the section's own page.

        The title's identifier is embedded in the ``TITLE{n}`` directory,
        so the chapter ref's title identifier is required to construct a
        chapter URL and the section ref's full citation to construct a
        section URL.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            chapter_dir = ref.chapter.identifier
            title_dir = ref.chapter.title.identifier
            return (
                f"{self.BASE_URL}/Statutes/TITLE{title_dir}/{chapter_dir}/"
                f"{ref.identifier}.htm"
            )
        elif isinstance(ref, ChapterRef):
            title_dir = ref.title.identifier
            return (
                f"{self.BASE_URL}/Statutes/TITLE{title_dir}/{ref.identifier}/"
                "INDEX.htm"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/Statutes/TITLE{ref.identifier}/INDEX.HTM"
        else:
            raise UnsupportedRefError(
                f"RhodeIslandAdapter.build_url does not support refs of type "
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
                does not resolve on the General Assembly site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Rhode Island General "
                    "Assembly site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the General Laws from the master
        ``Statutes.html`` page.

        The master page lists all 47 titles (1-47 plus lettered ``6A`` and
        decimal ``40.1``). The identifier is the text between ``TITLE`` and
        ``/INDEX.HTM`` in the link href; the display name is the text of the
        table cell adjacent to the link cell. The result is ordered as the
        page lists them (numeric order, ``6A`` after ``47``, ``40.1`` last);
        ``list_chapters`` never depends on this order, so the page's natural
        order is preserved.

        Returns:
            A sequence of :class:`TocNode`, one per title, in page order.
            Each node's ``ref`` is a :class:`TitleRef` whose ``identifier``
            is the title number/letter (e.g. ``"43"``, ``"6A"``, ``"40.1"``)
            and whose ``name`` is the title name (e.g. ``"Statutes and
            Statutory Construction"``).

        Raises:
            AdapterUnavailableError: If the master page cannot be fetched or
                no usable title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/Statutes/Statutes.html"
        html = self._fetch_html(url, what="Rhode Island master Statutes page")

        titles = []
        seen: dict[str, None] = {}
        for identifier, name in self._TITLE_ROW.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=self._clean_inner(name) or identifier,
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
        """Enumerate every chapter under ``title_ref`` from the title index
        page.

        The title index page lists every chapter of the title as
        ``{t}-{c}/INDEX.htm`` links. The identifier is the full ``{t}-{c}``
        directory prefix (e.g. ``43-3``, ``6A-2.1``, ``40.1-1.1``); the
        display name is the text after the leading ``Chapter {id}&nbsp;``
        prefix. The result is ordered as the page lists them (alphabetical
        order, e.g. ``43-1, 43-2, 43-3, 43-4``).

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in page order.
            Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the full ``{t}-{c}`` form (e.g. ``"43-3"``)
            and whose ``name`` is the chapter name (e.g. ``"Construction and
            Effect of Statutes"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title index page cannot be
                fetched for any other reason, or if no usable chapter links
                could be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Rhode Island chapter listing")

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
                    name=self._clean_inner(name) or identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter links in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        index page.

        The chapter index page lists every section of the chapter as
        ``{t}-{c}-{s}.htm`` links. The identifier is the full ``{t}-{c}-{s}``
        file stem (e.g. ``43-3-2``, ``43-3-3.1``); the display name is the
        text after the leading ``&sect;&nbsp;{id}.&nbsp;`` prefix. The
        result is ordered as the page lists them (alphabetical order).

        Returns:
            A sequence of :class:`TocNode`, one per section, in page order.
            Each node's ``ref`` is a :class:`SectionRef` whose ``identifier``
            is the full ``{t}-{c}-{s}`` form (e.g. ``"43-3-2"``,
            ``"43-3-3.1"``) and whose ``name`` is the section's name as
            presented in the listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter index page cannot be
                fetched for any other reason, or if no usable section links
                could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Rhode Island section listing")

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
                    name=self._clean_inner(name) or identifier,
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

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Rhode Island.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the full ``{t}-{c}-{s}`` section citation, e.g.
        ``"43-3-2"``) appears verbatim within ``raw_citation`` (the ``R.I.
        Gen. Laws &sect; 43-3-2`` citation). The stronger title/chapter
        cross-check against the source response happens in
        :meth:`retrieve_section`, which has the page's title and citation
        anchors.

        ``status`` is set to ``REPEALED`` only when the heading is a
        structural repeal marker (``Repealed.`` or ``[Repealed.]`` in place
        of body text, e.g. section 43-3-7 and the repealed-range section
        40.1-1-1) -- the framework's own rule for a structural signal.
        All other sections stay ``UNKNOWN``.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Rhode Island ref
                (``ref.state_code != "RI"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"RhodeIslandAdapter.normalize cannot normalize a ref for "
                f"state {ref.state_code!r}; expected {self.state_code!r}."
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
        """Retrieve and normalize one General Laws section, end to end:
        :meth:`build_url` -> fetch the section page -> cross-check the
        page's title and citation anchors against ``ref`` -> parse the
        section page into a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/rhode_island.md): the
        ``<h1>`` holds the title number (``Title 43``) and the ``<h3>`` the
        full citation (``R.I. Gen. Laws &sect; 43-3-2``), both cross-checked
        against ``ref``; the heading is the ``<p style="margin-left:0px">
        <b>`` text with the leading ``&sect;&nbsp;{id}.&nbsp;`` prefix
        stripped; the body is the ``<p style="margin-left:0px">`` region
        between the heading paragraph and the history block;
        ``amendment_notes`` is the text after ``History of Section.<br>``.
        The page's title anchor is cross-checked against
        ``ref.chapter.title`` and the citation anchor against
        ``ref.chapter`` + ``ref.identifier``; a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be a Rhode Island ref
                (``ref.state_code == "RI"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's title or citation anchors
                disagree with ``ref``. Also raised by :meth:`normalize` on
                citation disagreement.
            NormalizationError: If the section was located but required
                structure (title anchor, citation anchor, heading) is
                missing, or the body is empty after cleaning without a
                structural repeal marker. Also raised by :meth:`normalize`
                if ``ref`` is not a Rhode Island ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Rhode Island section page")

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

        citation_anchor = self._CITATION_CROSSCHECK.search(html)
        if citation_anchor is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no citation "
                "anchor; the site's structure may have changed."
            )
        citation_text = self._clean_inner(citation_anchor.group(1))
        if ref.identifier not in citation_text:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation in the fetched section page: "
                f"{citation_text!r}."
            )

        heading_p = self._HEADING_P.search(html)
        if heading_p is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading paragraph; the site's "
                "structure may have changed."
            )
        heading = self._clean_inner(heading_p.group(1))
        heading = self._HEADING_ID_PREFIX.sub("", heading).strip() or None

        body_start = heading_p.end()
        body_html = html[body_start:]
        history = self._HISTORY_BLOCK.search(body_html)
        if history is not None:
            body_html = body_html[: history.start()]

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
        if history is not None:
            amendment_notes = (
                strip_tags(history.group(1), preserve_block_breaks=True).strip()
                or None
            )

        raw_citation = f"R.I. Gen. Laws § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
