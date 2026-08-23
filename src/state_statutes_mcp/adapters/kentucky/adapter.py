"""KentuckyAdapter: the Kentucky-specific concrete state adapter.

Source: the official Kentucky Revised Statutes (KRS) at
``https://apps.legislature.ky.gov`` -- anonymous, server-rendered HTML for
discovery plus per-section PDF documents for retrieval. This is the
framework's first PDF-consuming adapter.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/kentucky.md``;
all structures verified against real live captures of the official host on
Aug 23 2026 from this environment):

* Base URL ``https://apps.legislature.ky.gov/LAW/STATUTES``.
* **Discovery hierarchy**: the statutes index page (``/LAW/STATUTES/``)
  lists every title with a Roman-numeral identifier (``TITLE I`` through
  ``TITLE LI``, 44 titles) and, nested under each title, every chapter as
  ``<a class="chapter" href="chapter.aspx?id={opaque}">CHAPTER {n} {NAME}</a>``.
  Chapter numbers are globally unique across the whole code (548 chapters,
  VERIFIED no duplicates). ``TitleRef.identifier`` is the Roman numeral
  (e.g. ``"XVII"``); ``ChapterRef.identifier`` is the chapter number
  (e.g. ``"205"``).
* **Chapter page** (``chapter.aspx?id={opaque}``) declares its own chapter
  in ``<span id="Banner1_lblPageTitle">KRS Chapter {n}</span>`` and lists
  every section as ``<a class="statute" href="statute.aspx?id={opaque}">
  .{local}  {catchline}</a>`` (e.g. ``.010  Definitions for chapter.``).
  ``SectionRef.identifier`` is the full KRS citation ``{chapter}.{local}``
  (e.g. ``"205.010"``), matching the citation the PDF itself declares.
* **DANGEROUS behavior (VERIFIED)**: ``chapter.aspx`` and ``statute.aspx``
  do NOT return clean HTTP 404s for bad IDs. An invalid/incorrect chapter
  ID or an invalid section ID returns HTTP 200 with the full chapter-index
  page (the "Service Alert" page or the index). Two protections are
  therefore mandatory and both are implemented:
  1. The requested chapter number is NEVER trusted: after fetching a
     chapter page, the adapter parses the chapter declared by the returned
     page and compares it to the requested chapter. A missing declaration
     (the index fallback) is ``RefNotFoundError``; a declaration that
     differs from the request is ``RefMismatchError``.
  2. A section fetch that does not return a PDF (``%PDF`` header) is
     ``RefNotFoundError`` -- the section does not resolve.
* **Section retrieval**: ``statute.aspx?id={opaque}`` returns a real PDF
  document (``Content-Type: application/pdf``). The adapter fetches it
  with the shared :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes`
  (raw bytes, never UTF-8-decoded) and extracts text with the shared
  :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text`.
* **PDF text structure** (VERIFIED on four real sections):
  * First line: ``{citation}   {catchline}`` (citation and catchline
    separated by two or more spaces), e.g. ``205.010   Definitions for
    chapter.``.
  * Body: the operative statute text follows, one paragraph per line
    (numbered subsections preserved as ``(1)``, ``(a)``, etc.).
  * ``Effective: {date}`` -- an effective-date metadata line.
  * ``History: {history}`` -- the legislative-history block (may span
    multiple lines).
  * Repealed sections: ``{citation}   Repealed, {year}.`` followed by a
    ``Catchline at repeal:`` line and a ``History:`` block.
  * Renumbered sections: ``{citation}   Renumbered as {n}, effective
    {year}.`` followed by a ``Note:`` block.
* **Repealed / renumbered representation** (following the framework's
  prose-only-repeal rule, the same decision as NebraskaAdapter and
  MassachusettsAdapter): the repeal/renumber signal is prose, not a
  structural marker, so ``status`` is ``UNKNOWN``; the catchline is
  returned as ``heading``, the operative body is empty (``text=""``), and
  the history/note text is preserved in ``amendment_notes``.
* **Citation**: ``KRS {chapter}.{local}`` (e.g. ``KRS 205.010``),
  adapter-constructed from the verified section identifier.
* **Encoding**: the discovery pages are UTF-8 HTML; the section documents
  are binary PDFs fetched as raw bytes.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/kentucky.md``): only chapters 205 and 367 (and four of
their sections) were live-captured; whether every chapter/section page
renders identically is otherwise UNVERIFIED. A genuine HTTP 404 was never
observed from this host -- the site returns HTTP 200 with a fallback page
for bad IDs, which is the behavior this adapter defends against.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_bytes, fetch_url
from state_statutes_mcp.adapters._htmltext import strip_tags
from state_statutes_mcp.adapters._pdftext import extract_pdf_text
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


class KentuckyAdapter(BaseStateAdapter):
    """Concrete state adapter for the Kentucky Revised Statutes at
    apps.legislature.ky.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The KRS map onto the
    framework's three-level ref model as Title -> Chapter -> Section, with
    the opaque per-chapter/per-section IDs resolved adapter-internally
    (they are not part of the citation and never leak into the refs).
    See the module docstring.
    """

    BASE_URL = "https://apps.legislature.ky.gov"
    STATUTES_PATH = "/LAW/STATUTES"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title row on the statutes index page, e.g.
    # '<li><span id="title">TITLE XVII ECONOMIC SECURITY AND PUBLIC
    #  WELFARE </span>...<li><a class="chapter" href="chapter.aspx?id=38124">
    #  CHAPTER 205 PUBLIC ASSISTANCE AND MEDICAL ASSISTANCE </a></li>'.
    _TITLE_ROW = re.compile(
        r'<span id="title">TITLE\s+([IVXLCDM]+)\s+(.*?)\s*</span>',
        re.DOTALL,
    )

    # A chapter row on the statutes index page, e.g.
    # '<a class="chapter" href="chapter.aspx?id=38124">CHAPTER 205 PUBLIC
    #  ASSISTANCE AND MEDICAL ASSISTANCE </a>'.
    _CHAPTER_ROW = re.compile(
        r'<a class="chapter" href="chapter\.aspx\?id=(\d+)">\s*'
        r"CHAPTER\s+([0-9A-Z]+)\s+(.*?)</a>",
        re.DOTALL,
    )

    # The chapter a chapter page declares itself to be, e.g.
    # '<span id="Banner1_lblPageTitle">KRS Chapter 205</span>'. The index
    # fallback (returned for bad IDs) carries 'Kentucky Revised Statutes'
    # here instead, so this regex distinguishes a real chapter page from
    # the fallback.
    _DECLARED_CHAPTER = re.compile(
        r'<span id="Banner1_lblPageTitle">\s*KRS Chapter\s+([0-9A-Z]+)\s*</span>',
        re.DOTALL,
    )

    # A section row on a chapter page, e.g.
    # '<a class="statute" href="statute.aspx?id=7624">.010  Definitions for
    #  chapter. </a>'.
    _SECTION_ROW = re.compile(
        r'<a class="statute" href="statute\.aspx\?id=(\d+)">\s*'
        r"\.([0-9A-Za-z]+)\s+(.*?)</a>",
        re.DOTALL,
    )

    # The first line of an extracted section PDF, e.g.
    # '205.010   Definitions for chapter.' (citation and catchline
    # separated by two or more spaces).
    _CITATION_LINE = re.compile(r"^(?P<citation>\S+)\s{2,}(?P<catchline>.*)$")

    # A metadata line prefix on an extracted section PDF.
    _METADATA_LINE = re.compile(
        r"^(Effective:|History:|Note:|Catchline at repeal:)"
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Kentucky."""
        return "KY"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Kentucky."""
        return "Kentucky"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _index_url(self) -> str:
        """The statutes index URL (titles and chapters)."""
        return f"{self.BASE_URL}{self.STATUTES_PATH}/"

    def _chapter_page_url(self, opaque_chapter_id: str) -> str:
        return (
            f"{self.BASE_URL}{self.STATUTES_PATH}/"
            f"chapter.aspx?id={opaque_chapter_id}"
        )

    def _section_pdf_url(self, opaque_section_id: str) -> str:
        return (
            f"{self.BASE_URL}{self.STATUTES_PATH}/"
            f"statute.aspx?id={opaque_section_id}"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Kentucky URL needed to retrieve ``ref``.

        Kentucky's addressing is opaque: chapter and section IDs cannot be
        derived from the citation, so resolving them requires discovery
        (the index page for a chapter, the chapter page for a section).
        This method therefore performs that resolution, like
        ``list_chapters``/``list_sections`` do.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the statutes index URL (the only page that
              lists titles).
            * ``ChapterRef`` -> the chapter's ``chapter.aspx`` URL.
            * ``SectionRef`` -> the section's ``statute.aspx`` PDF URL.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If the chapter does not exist (bad ID), or
                the section does not exist (bad ID, or the fetched chapter
                page does not declare the requested chapter).
            RefMismatchError: If the fetched chapter page declares a
                different chapter than the one requested.
        """
        if isinstance(ref, SectionRef):
            opaque_section_id = self._section_id_for(ref)
            return self._section_pdf_url(opaque_section_id)
        elif isinstance(ref, ChapterRef):
            opaque_chapter_id = self._chapter_id_for(ref)
            return self._chapter_page_url(opaque_chapter_id)
        elif isinstance(ref, TitleRef):
            return self._index_url()
        else:
            raise UnsupportedRefError(
                f"KentuckyAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------

    def _fetch_index(self, *, what: str) -> str:
        """Fetch the statutes index page and return its decoded HTML."""
        url = self._index_url()
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    def _fetch_chapter_page(
        self, chapter_ref: ChapterRef, *, what: str
    ) -> tuple[str, str]:
        """Resolve and fetch the chapter page for ``chapter_ref``.

        Enforces the mandatory chapter-ID safety: the opaque chapter ID is
        resolved from the index (so a nonexistent chapter number raises
        ``RefNotFoundError`` up front), and the fetched page is required to
        declare the requested chapter number. A page with no chapter
        declaration is the index/Service-Alert fallback for a bad ID
        (``RefNotFoundError``); a page declaring a *different* chapter is
        ``RefMismatchError`` (the server served content for the wrong
        chapter).

        Args:
            chapter_ref: The chapter to fetch.
            what: A short human-readable description used for error
                messages.

        Returns:
            ``(html, opaque_chapter_id)`` for the real chapter page.

        Raises:
            AdapterUnavailableError: If the index or chapter page cannot be
                reached.
            RefNotFoundError: If the chapter number is not in the index, or
                the fetched page does not declare any chapter (bad-ID
                fallback).
            RefMismatchError: If the fetched page declares a different
                chapter than requested.
        """
        opaque_chapter_id = self._chapter_id_for(chapter_ref)
        url = self._chapter_page_url(opaque_chapter_id)
        try:
            html = fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

        declared = self._DECLARED_CHAPTER.search(html)
        if declared is None:
            raise RefNotFoundError(
                f"Could not fetch the {what} at {url!r}: the page did not "
                "declare a chapter (the Kentucky site returned its "
                "index/fallback page instead of a real chapter page)."
            )
        if declared.group(1) != chapter_ref.identifier:
            raise RefMismatchError(
                f"Requested chapter {chapter_ref.identifier!r} does not "
                f"match the chapter found on the fetched page: "
                f"{declared.group(1)!r}."
            )
        return html, opaque_chapter_id

    # ------------------------------------------------------------
    # Opaque-ID resolution (adapter-local)
    # ------------------------------------------------------------

    def _chapter_id_for(self, chapter_ref: ChapterRef) -> str:
        """Resolve ``chapter_ref``'s chapter number to its opaque ID.

        The opaque IDs are not part of the citation and are derived from
        the statutes index page, where each ``CHAPTER {n}`` row carries its
        ``chapter.aspx?id={opaque}`` value. Chapter numbers are globally
        unique (VERIFIED), so a flat lookup suffices.

        Raises:
            RefNotFoundError: If the chapter number is not present in the
                index (the chapter does not exist).
        """
        html = self._fetch_index(what="Kentucky statutes index")
        for opaque_id, number, _name in self._CHAPTER_ROW.findall(html):
            if number == chapter_ref.identifier:
                return opaque_id
        raise RefNotFoundError(
            f"Could not resolve chapter {chapter_ref.identifier!r}: it is "
            "not listed in the Kentucky Revised Statutes index."
        )

    def _section_id_for(self, section_ref: SectionRef) -> str:
        """Resolve ``section_ref``'s citation to its opaque section ID.

        The chapter page lists each section as ``statute.aspx?id={opaque}``
        with the local number after the leading dot; the full citation is
        ``{chapter}.{local}``. The section is located by matching that full
        citation against the requested ``SectionRef.identifier``.

        Raises:
            RefNotFoundError: If the chapter does not exist or the section
                citation does not appear on the chapter page.
            RefMismatchError: If the chapter page declares a different
                chapter than requested.
        """
        chapter_ref = section_ref.chapter
        html, _opaque_chapter_id = self._fetch_chapter_page(
            chapter_ref, what="Kentucky chapter page"
        )
        chapter = chapter_ref.identifier
        for opaque_id, local, _catchline in self._SECTION_ROW.findall(html):
            if f"{chapter}.{local}" == section_ref.identifier:
                return opaque_id
        raise RefNotFoundError(
            f"Could not resolve section {section_ref.identifier!r}: it is "
            "not listed on the Kentucky chapter page for chapter "
            f"{chapter!r}."
        )

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Kentucky Revised Statutes.

        The index page lists all 44 titles as ``TITLE {roman} {name}``
        spans. ``TitleRef.identifier`` is the Roman numeral (e.g.
        ``"XVII"``); the title name is the descriptive name.

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order.

        Raises:
            AdapterUnavailableError: If the index cannot be fetched, or if
                no usable title rows could be parsed.
        """
        html = self._fetch_index(what="Kentucky statutes index")
        titles = []
        for roman, raw_name in self._TITLE_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
            if not name:
                continue
            identifier = roman
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
                "Fetched the Kentucky statutes index but found no usable "
                "title rows in it; the site's structure may have changed."
            )
        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter nested under ``title_ref``.

        The index page nests chapters under their title; chapters are
        filtered to those under the requested title's Roman numeral.
        ``ChapterRef.identifier`` is the chapter number (e.g. ``"205"``).

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order.

        Raises:
            AdapterUnavailableError: If the index cannot be fetched.
            RefNotFoundError: If ``title_ref``'s Roman numeral does not
                match any title on the index page.
        """
        html = self._fetch_index(what="Kentucky statutes index")

        # Walk the index: track the current title as spans are seen, and
        # attribute each chapter row to the title in scope.
        chapters_by_title: dict[str, list[tuple[str, str, str]]] = {}
        current_title: str | None = None
        position = 0
        combined = re.finditer(
            r"<span id=\"title\">TITLE\s+([IVXLCDM]+)|"
            r'<a class="chapter" href="chapter\.aspx\?id=(\d+)">\s*'
            r"CHAPTER\s+([0-9A-Z]+)\s+(.*?)</a>",
            html,
            re.DOTALL,
        )
        for match in combined:
            if match.group(1) is not None:
                current_title = match.group(1)
                chapters_by_title.setdefault(current_title, [])
            elif current_title is not None:
                opaque_id, number, raw_name = match.group(2, 3, 4)
                name = " ".join(strip_tags(raw_name).split())
                chapters_by_title[current_title].append((number, name, opaque_id))
            position += 1

        if title_ref.identifier not in chapters_by_title:
            raise RefNotFoundError(
                f"Could not resolve title {title_ref.identifier!r}: it is "
                "not listed in the Kentucky Revised Statutes index."
            )

        chapters = []
        for number, name, _opaque_id in chapters_by_title[title_ref.identifier]:
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=number,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=number),
                )
            )
        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        Fetches the chapter page (enforcing the chapter-ID safety) and
        returns one :class:`TocNode` per section, with ``identifier`` the
        full KRS citation ``{chapter}.{local}`` (e.g. ``"205.010"``) and
        ``name`` the catchline.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order.

        Raises:
            AdapterUnavailableError: If the chapter page cannot be fetched.
            RefNotFoundError: If the chapter does not exist.
            RefMismatchError: If the chapter page declares a different
                chapter than requested.
        """
        html, _opaque_chapter_id = self._fetch_chapter_page(
            chapter_ref, what="Kentucky chapter page"
        )
        chapter = chapter_ref.identifier
        sections = []
        seen: set[str] = set()
        for _opaque_id, local, raw_name in self._SECTION_ROW.findall(html):
            identifier = f"{chapter}.{local}"
            if identifier in seen:
                # VERIFIED: a few sections render twice on their chapter
                # page (the same section listed under two subchapter
                # headings, e.g. 205.522, 205.536, 205.6485). Keep the
                # first occurrence.
                continue
            seen.add(identifier)
            name = " ".join(strip_tags(raw_name).split())
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
                f"Fetched the Kentucky chapter page for chapter {chapter!r} "
                "but found no usable section rows in it; the site's "
                "structure may have changed."
            )
        return tuple(sections)

    # ------------------------------------------------------------
    # PDF parsing (Kentucky-specific, kept out of _pdftext.py)
    # ------------------------------------------------------------

    @classmethod
    def _parse_section_text(cls, text: str) -> tuple[str, str, str, str | None]:
        """Parse an extracted Kentucky section PDF into its parts.

        Args:
            text: The concatenated extracted text of one section PDF.

        Returns:
            ``(citation, catchline, body, amendment_notes)`` where
            ``citation`` is the section's own declared citation (e.g.
            ``"205.010"``), ``catchline`` is the heading, ``body`` is the
            operative statute text (empty for repealed/renumbered stubs),
            and ``amendment_notes`` is the ``History:``/``Note:`` block or
            ``None`` if absent.

        Raises:
            NormalizationError: If the text has no citation line (genuinely
                malformed -- the section could not be located).
        """
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        citation_match = cls._CITATION_LINE.match(lines[0]) if lines else None
        if citation_match is None:
            raise NormalizationError(
                "The extracted Kentucky section text contained no citation "
                "line; the PDF may be malformed or the site's structure may "
                "have changed."
            )
        citation = citation_match.group("citation")
        catchline = citation_match.group("catchline").strip()

        body_lines: list[str] = []
        notes_lines: list[str] = []
        in_notes = False
        for line in lines[1:]:
            if cls._METADATA_LINE.match(line):
                in_notes = True
            if in_notes:
                notes_lines.append(line)
            else:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        amendment_notes = "\n".join(notes_lines).strip() if notes_lines else None
        return citation, catchline, body, amendment_notes

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Kentucky.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: the full ``KRS {chapter}.{local}`` citation
        must contain ``ref.identifier``.

        ``status`` is always ``UNKNOWN``: the source signals repealed and
        renumbered sections only as prose in the catchline (``Repealed,
        1950.``, ``Renumbered as 45.235, effective 1948.``) with no
        operative body -- per the framework rule (same decision as
        NebraskaAdapter/MassachusettsAdapter), a prose-only signal is not a
        structural marker, so the status is not inferred from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Kentucky ref
                (``ref.state_code != "KY"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"KentuckyAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Kentucky Revised Statutes section,
        end to end: resolve the opaque section ID -> fetch the raw PDF
        bytes with :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes`
        -> extract text with
        :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text` ->
        parse the section into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a Kentucky ref
                (``ref.state_code == "KY"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter page or the section PDF
                cannot be reached, or if the PDF cannot be extracted.
            RefNotFoundError: If the chapter does not exist, the chapter
                page does not declare the requested chapter (bad-ID
                fallback), or the section does not resolve (the site
                returns a non-PDF fallback page for a bad section ID).
            RefMismatchError: If the chapter page declares a different
                chapter than requested, or the section's own declared
                citation disagrees with ``ref``.
            NormalizationError: If the section was located but the extracted
                PDF text is genuinely malformed (missing the citation line).
        """
        url = self.build_url(ref)

        try:
            data = fetch_bytes(url, what="Kentucky statute PDF")
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the Kentucky statute PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the Kentucky statute at {url!r}: the "
                "site returned a non-PDF page (the section does not "
                "resolve)."
            )

        text = extract_pdf_text(data)
        citation, catchline, body, amendment_notes = self._parse_section_text(text)

        if citation != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the extracted PDF: {citation!r}."
            )

        raw_citation = f"KRS {citation}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=catchline,
            text=body,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)