"""ConnecticutAdapter: the Connecticut-specific concrete state adapter.

Source: the official Connecticut General Statutes "current" publication
at ``https://www.cga.ct.gov/current/pub/`` -- anonymous, server-rendered
HTML with no authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/connecticut.md``; verified against a Wayback Machine
capture of the official host, snapshot ``20260811192527id_``):

* Base URL ``https://www.cga.ct.gov/current/pub``.
* Hierarchy Title -> Chapter -> Section. The title index is
  ``titles.htm``; each title's page is ``title_{id}.htm`` and lists that
  title's chapters.
* Chapter pages are ``chap_{id}.htm`` for nearly all titles. Title 42a
  (the Uniform Commercial Code) is article-based: its "chapter" pages are
  ``art_{id}.htm`` (e.g. ``art_001.htm``), and its title page lists
  articles. This is the ONLY article-based title (verified on the title
  index).
* Section identifiers are the citation form ``{chapter}-{section}``
  (e.g. ``53a-24``) or, for the UCC articles, ``{article}-{part}-{section}``
  (e.g. ``42a-1-101``). Lettered suffixes are supported (e.g. ``53a-117l``).
* Sections are embedded in their chapter document (chapter-document based
  retrieval). Each section is opened by a catchline span
  ``<span class="catchln" id="sec_{id}">Sec. {id}. {Caption}.</span>``.
* Repealed ranges appear as interleaved range catchline blocks whose id is
  ``secs_...`` (e.g. ``secs_53a-53_and_53a-54``). These are genuine block
  boundaries but are NOT individually retrievable sections, so the adapter
  excludes them from section listings.
* Body, history, annotations and navigation: each section block carries
  optional ``<p class="source-first">`` (session-law history) and
  ``<p class="history-first">`` (narrative history) paragraphs, optional
  ``<p class="annotation...">`` / ``<p class="cross-ref...">`` /
  ``<p class="front-note...">`` paragraphs, and a trailing
  ``<table class="nav_tbl">``. ``amendment_notes`` joins the source-first
  and history-first text with a newline; body, annotations, cross-refs,
  front-notes and the nav table are excluded from the body text.
* Some sections are no-caption (e.g. ``53a-90``, transferred to another
  chapter, whose heading is just ``Sec. 53a-90.``); the caption is then
  ``None`` and the body is the transfer note.
* Citation: ``Conn. Gen. Stat. § {chapter}-{section}``; the adapter's
  ``raw_citation`` is the page's own ``Sec. {id}`` form and
  ``SectionRef.identifier`` is ``{id}``.
* Error boundary: the live HTTP 404 behavior is UNVERIFIED (host not
  reachable from this environment); by project convention HTTP 404 maps to
  ``RefNotFoundError`` and other network failures to
  ``AdapterUnavailableError``. A section not present in a fetched chapter
  document raises ``RefNotFoundError`` (adapter-level expected behavior;
  live behavior UNVERIFIED).

**UNVERIFIED / accepted limitations** (documented in
``docs/research/connecticut.md``): the live hosts are not reachable from
this environment (only the Wayback capture was verified), so live 404
semantics and any markup drift since the capture are unverified. The
capture used for the fixtures is current as of the 2026 session.
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


class ConnecticutAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Connecticut General Statutes
    "current" publication at cga.ct.gov/current/pub.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://www.cga.ct.gov/current/pub"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Title 42a is article-based (UCC): its "chapter" pages are art_{id}.htm.
    _ARTICLE_BASED_TITLE = "42a"

    # A title row on the title index (titles.htm), e.g.
    # '<tr style="vertical-align:top"><td class="left_38pct"><a href="title_01.htm">
    #  <span class="toc_ttl_desig">Title 1</span></a> ...</td>
    #  <td><a href="title_01.htm"><span class="toc_ttl_name">Name</span></a></td></tr>'.
    _TITLE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    _TITLE_DESIG = re.compile(
        r'<a href="title_([0-9a-z]+)\.htm"[^>]*><span class="toc_ttl_desig">',
        re.DOTALL,
    )
    _TITLE_NAME = re.compile(r'<span class="toc_ttl_name">(.*?)</span>', re.DOTALL)

    # A chapter/article row on a title page, e.g.
    # '<tr style="vertical-align:top"><td class="left_40pct">
    #  <a class="toc_ch_link" href="chap_950.htm">Chapter 950</a> ...</td>
    #  <td><a class="toc_ch_link" href="chap_950.htm">Name</a></td></tr>'.
    _CHAPTER_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    _CHAPTER_LINK = re.compile(
        r'<a class="toc_ch_link" href="(?:chap|art)_([0-9a-z]+)\.htm"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    # An individually retrievable section's catchline span, e.g.
    # '<span class="catchln" id="sec_53a-24">Sec. 53a-24. Offense defined. ...</span>'.
    # Identifiers: 53a-24, 53a-100aa, 53a-117l, 42a-1-101.
    _CATCHLN = re.compile(
        r'<span class="catchln" id="sec_([0-9]+[a-z]?(?:-[0-9]+[a-z]*)+)">(.*?)</span>',
        re.DOTALL,
    )

    # ANY catchline span -- including the "secs_" repealed-range blocks that
    # are genuine block boundaries but NOT retrievable sections. Used only to
    # split a chapter document into blocks.
    _BOUNDARY = re.compile(r'<span class="catchln" id="(sec[^"]+)">')

    # Paragraphs excluded from the body text.
    _NAV_TABLE = re.compile(r'<table class="nav_tbl">.*?</table>', re.DOTALL)
    _ANNOTATION = re.compile(r'<p class="annotation(?:-first)?">.*?</p>', re.DOTALL)
    _CROSS_REF = re.compile(r'<p class="cross-ref(?:-first)?">.*?</p>', re.DOTALL)
    _FRONT_NOTE = re.compile(r'<p class="front-note(?:-first)?">.*?</p>', re.DOTALL)

    # History paragraphs, preserved verbatim as amendment_notes.
    _SOURCE = re.compile(r'<p class="source-first">(.*?)</p>', re.DOTALL)
    _HISTORY = re.compile(r'<p class="history-first">(.*?)</p>', re.DOTALL)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Connecticut."""
        return "CT"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Connecticut."""
        return "Connecticut"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Connecticut General Statutes URL for
        ``ref``.

        VERIFIED endpoint shapes (see docs/research/connecticut.md):

        * Title: ``https://www.cga.ct.gov/current/pub/title_{id}.htm``
          where ``{id}`` is the title href stem (e.g. ``01``, ``42a``,
          ``53a``).
        * Chapter: ``https://www.cga.ct.gov/current/pub/chap_{id}.htm``,
          EXCEPT under Title 42a (the UCC), whose "chapter" pages are
          ``art_{id}.htm`` (e.g. ``art_001.htm``). The article-based
          mapping is VERIFIED: 42a is the only article-based title.
        * Section: the section's own chapter/article document -- sections
          are embedded in their chapter document, so that document is the
          closest real resource (the same model NevadaAdapter uses).

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return self._chapter_url(ref.chapter)
        elif isinstance(ref, ChapterRef):
            return self._chapter_url(ref)
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/title_{ref.identifier}.htm"
        else:
            raise UnsupportedRefError(
                f"ConnecticutAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    def _chapter_url(self, chapter_ref: ChapterRef) -> str:
        """Build the chapter (or article) document URL for ``chapter_ref``.

        Most titles use ``chap_{id}.htm``; Title 42a (the UCC) is
        article-based and uses ``art_{id}.htm``.
        """
        prefix = (
            "art"
            if chapter_ref.title.identifier == self._ARTICLE_BASED_TITLE
            else "chap"
        )
        return f"{self.BASE_URL}/{prefix}_{chapter_ref.identifier}.htm"

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into ``AdapterUnavailableError``
        there. This method additionally maps HTTP 404 into
        :class:`RefNotFoundError` -- the source was reached, but the
        addressed document does not resolve. The live 404 behavior of the
        Connecticut site is UNVERIFIED (host not reachable from this
        environment); this mapping follows project convention.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Connecticut site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Connecticut General "
                    "Statutes site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _strip_caption_prefix(cls, heading_text: str, identifier: str) -> str | None:
        """Strip the leading ``Sec. {id}.`` prefix from a catchline's heading
        text, leaving the caption.

        The source renders lettered-section digits as italic elements, so the
        raw heading text may insert a space inside the identifier (e.g.
        ``Sec. 53a-117 l . Damage...``). The prefix pattern therefore allows
        whitespace between every identifier character and requires a trailing
        period (``.``), e.g. ``53a-117 l . ``.

        Args:
            heading_text: The cleaned catchline text (e.g. ``Sec. 53a-24.
                Offense defined.``).
            identifier: The section identifier (e.g. ``"53a-24"``).

        Returns:
            The caption with the ``Sec. {id}.`` prefix removed, or ``None``
            if nothing remains (a no-caption section such as ``53a-90``).
        """
        pattern = (
            r"^Sec\.\s+"
            + r"\s*?".join(re.escape(char) for char in identifier)
            + r"\s*?\.\s*"
        )
        stripped = re.sub(pattern, "", heading_text, count=1).strip()
        return stripped or None

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Connecticut General Statutes from
        the title index.

        The title index (``titles.htm``) lists the titles; each row carries
        a ``toc_ttl_desig`` link (whose href stem is the title identifier,
        e.g. ``01``, ``42a``, ``53a``) and a ``toc_ttl_name`` span (the
        title name). Rows without a usable designation/name pair (e.g. the
        reserved Title 2a row, which has no links) are skipped.

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title href stem (e.g. ``"01"``).

        Raises:
            AdapterUnavailableError: If the title index cannot be fetched,
                or if no usable title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/titles.htm"
        html = self._fetch_html(url, what="Connecticut title index")

        titles = []
        seen: dict[str, None] = {}
        for row in self._TITLE_ROW.finditer(html):
            desig = self._TITLE_DESIG.search(row.group(1))
            name_match = self._TITLE_NAME.search(row.group(1))
            if desig is None or name_match is None:
                continue
            identifier = desig.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(name_match.group(1)).split())
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name or identifier,
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
        """Enumerate every chapter (or article, for Title 42a) under
        ``title_ref`` from the title's page.

        The title page (``title_{id}.htm``) lists the title's chapters, one
        row per chapter. Each row carries one or more ``toc_ch_link`` links
        whose href stem is the chapter identifier (e.g. ``950``; ``001`` for
        the UCC articles); the last link's text is the chapter/article name.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter href stem (e.g. ``"950"``;
            ``"001"`` for a UCC article).

        Raises:
            RefNotFoundError: If ``title_ref``'s heading is not present on
                the title index or its page does not resolve.
            AdapterUnavailableError: If the title page cannot be fetched for
                any other reason, or if no usable chapter rows could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Connecticut title page")

        chapters = []
        seen: dict[str, None] = {}
        for row in self._CHAPTER_ROW.finditer(html):
            links = list(self._CHAPTER_LINK.finditer(row.group(1)))
            if not links:
                continue
            identifier = links[0].group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(links[-1].group(2)).split())
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name or identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter rows in it; "
                f"title {title_ref.identifier!r} either lists no chapters or "
                "the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every individually retrievable section under
        ``chapter_ref`` from the chapter document.

        The chapter document (``chap_{id}.htm`` / ``art_{id}.htm``) contains
        all of the chapter's sections, each opened by a ``sec_`` catchline
        span. Repealed-range blocks (``secs_`` catchline spans) are genuine
        block boundaries but are NOT individually retrievable sections, so
        they are excluded from this listing.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section id (e.g. ``"53a-24"``).

        Raises:
            RefNotFoundError: If the chapter document returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any other reason, or if no usable section
                catchlines could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Connecticut section listing")

        sections = []
        seen: dict[str, None] = {}
        for identifier, heading_text in self._CATCHLN.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            caption = self._strip_caption_prefix(
                " ".join(self._clean_inner(heading_text).split()), identifier
            )
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=caption or identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section catchlines in "
                f"it; chapter {chapter_ref.identifier!r} either does not "
                "resolve or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Connecticut.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (e.g. ``"53a-24"``) must
        appear verbatim within ``parsed.raw_citation`` (the ``Sec. 53a-24``
        citation). The stronger citation cross-check against the source
        response happens in :meth:`retrieve_section`, which parses the
        chapter document's own catchline.

        ``status`` is always left at its default (``UNKNOWN``): the
        Connecticut chapter documents carry no structural
        repealed/amended/renumbered signal in the verified structure, and
        the contract explicitly forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Connecticut ref
                (``ref.state_code != "CT"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"ConnecticutAdapter.normalize cannot normalize a ref for "
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
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # retrieve_section
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Connecticut General Statutes section,
        end to end: :meth:`build_url` -> fetch the section's chapter
        document -> locate the section by its ``sec_`` catchline span ->
        parse it into a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/connecticut.md): sections
        are embedded in their chapter document, each opened by a catchline
        span ``<span class="catchln" id="sec_{id}">Sec. {id}. {Caption}.</span>``.
        The catchline's id must equal ``ref.identifier``; a section whose id
        is not present raises :class:`RefNotFoundError`. Repealed-range
        (``secs_``) blocks are used only as block boundaries, never as
        retrievable sections. The body is the block minus the catchline,
        the ``source-first``/``history-first`` history paragraphs (preserved
        verbatim as ``amendment_notes``), the annotation/cross-ref/
        front-note paragraphs, and the navigation table. A section whose
        body is empty after cleaning raises :class:`NormalizationError`.

        Args:
            ref: The section to retrieve. Must be a Connecticut ref
                (``ref.state_code == "CT"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the chapter document returns HTTP 404, or
                if the section's catchline id is not present in the chapter
                document (an adapter-level expected behavior based on
                project convention; the live behavior is UNVERIFIED).
            NormalizationError: If the section was located but its body is
                empty after cleaning. Also raised by :meth:`normalize` if
                ``ref`` is not a Connecticut ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Connecticut section page")

        boundaries = list(self._BOUNDARY.finditer(html))
        target = f"sec_{ref.identifier}"
        match = None
        for i, boundary in enumerate(boundaries):
            if boundary.group(1) == target:
                end = (
                    boundaries[i + 1].start()
                    if i + 1 < len(boundaries)
                    else len(html)
                )
                match = (boundary, end)
                break

        if match is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the chapter document contains no "
                f"section {ref.identifier!r}; the section does not resolve "
                "on the Connecticut General Statutes site."
            )
        boundary, end = match
        block = html[boundary.start() : end]

        catchline = self._CATCHLN.search(block)
        if catchline is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its block contained no catchline span; the site's structure "
                "may have changed."
            )

        heading_text = " ".join(self._clean_inner(catchline.group(2)).split())
        caption = self._strip_caption_prefix(heading_text, ref.identifier)

        amendment_parts = []
        source = self._SOURCE.search(block)
        history = self._HISTORY.search(block)
        if source is not None:
            amendment_parts.append(self._clean_inner(source.group(1)))
        if history is not None:
            amendment_parts.append(self._clean_inner(history.group(1)))
        amendment_notes = "\n".join(part for part in amendment_parts if part) or None

        body_html = block.replace(catchline.group(0), "", 1)
        body_html = self._NAV_TABLE.sub(" ", body_html)
        body_html = self._ANNOTATION.sub(" ", body_html)
        body_html = self._CROSS_REF.sub(" ", body_html)
        body_html = self._FRONT_NOTE.sub(" ", body_html)
        if source is not None:
            body_html = body_html.replace(source.group(0), " ", 1)
        if history is not None:
            body_html = body_html.replace(history.group(0), " ", 1)

        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        raw_citation = f"Sec. {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=caption,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)