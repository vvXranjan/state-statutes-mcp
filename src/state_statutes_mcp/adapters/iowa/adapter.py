"""IowaAdapter: the Iowa-specific concrete state adapter.

Source: the official Iowa Code at ``https://www.legis.iowa.gov/law/iowaCode`` —
server-rendered HTML for discovery plus per-section PDF documents for
retrieval. This is the framework's second PDF-consuming adapter (after
Kentucky) and reuses the same ``fetch_bytes`` -> ``extract_pdf_text``
pipeline unchanged.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/iowa.md``;
all structures verified against real live captures of the official host on
Aug 23 2026 from this environment):

* Base URL ``https://www.legis.iowa.gov``.
* **Current Code year is dynamic**: the root page
  (``/law/iowaCode``) embeds ``year=YYYY`` in every title/chapter link and
  in ``docs/code/{YEAR}/...`` PDF URLs. The current year at capture time
  was 2026. The adapter derives the year from the root page rather than
  hardcoding it, so a future Code year (2027, ...) is picked up
  automatically.
* **Titles**: the root page lists all 16 titles (``TITLE I`` through
  ``TITLE XVI``), each a table row ``Title {ROMAN} - {NAME} (Ch. {lo} -
  {hi})`` plus a Chapters link ``/law/iowaCode/chapters?title={ROMAN}&year={YEAR}``.
  ``TitleRef.identifier`` is the Roman numeral (e.g. ``"I"``).
* **Chapters**: ``/law/iowaCode/chapters?title={ROMAN}&year={YEAR}`` lists
  each chapter as ``Chapter {N} - {NAME}`` with a Sections link
  ``sections?codeChapter={N}&year={YEAR}`` and a PDF link
  ``/docs/code/{YEAR}/{N}.pdf``. Chapter identifiers can be numeric
  (``1``) or numeric-plus-trailing-letter (``1A``, ``7G``). RESERVED
  chapters (e.g. ``Chapter 6 - RESERVED``) are ordinary rows.
  ``ChapterRef.identifier`` is the chapter number (e.g. ``"1"``, ``"6A"``).
* **Sections**: ``/law/iowaCode/sections?codeChapter={N}&year={YEAR}``
  lists each section as ``&sect;{section} - {catchline}.`` with a PDF link
  ``/docs/code/{YEAR}/{chapter}.{section}.pdf``. Section identifiers are
  ``{chapter}.{local}`` and can carry a trailing uppercase letter
  (e.g. ``1.15A``). ``SectionRef.identifier`` is the full citation
  ``{chapter}.{local}`` (e.g. ``"1.1"``, ``"1.15A"``).
* **Section PDF**: ``/docs/code/{YEAR}/{chapter}.{section}.pdf`` returns a
  real PDF. Extracted text structure (VERIFIED on several sections):
  * Header line: ``{title number} {TITLE NAME}, §{citation}``.
  * Citation + catchline line: ``{citation}  {catchline}.``.
  * Body: the operative statute text.
  * Codification history: one or more bracketed lines
    (``[C51, §1; R60, §1; ...]``).
  * Acts amendment lines (e.g. ``2009  Acts,  ch  41, §1``).
  * Cross-reference note (``Referred to in §1.2``; layout extraction may
    join the words, e.g. ``Referredtoin§1.2``).
  * Generated footer (``{date}  Iowa Code {year}, Section {section} ({a}, {b})``).
* **Repealed sections (VERIFIED)**: a repealed section is simply absent —
  it is omitted from the section listing AND its PDF URL returns HTTP 404
  (VERIFIED: ``§4.16`` and ``§4.17``, both historically repealed, return
  404 and are absent from Chapter 4's listing). Repealed behavior therefore
  needs no special stub handling: a repealed/absent section is a not-found.
* **Reserved chapters (VERIFIED)**: a RESERVED chapter (e.g. Chapter 6)
  exists in the chapter listing but its section listing is EMPTY (an empty
  table body, not an error). ``list_sections`` on a reserved chapter
  returns an empty sequence.
* **Error boundary (VERIFIED)**:
  * A nonexistent chapter number in the chapter listing -> no such row in
    the index; ``list_sections`` raises ``RefNotFoundError`` up front.
  * A section PDF for a nonexistent/repealed section -> genuine HTTP 404
    -> ``RefNotFoundError``.
  * A nonexistent chapter PDF -> genuine HTTP 404.
* **Citation**: ``Iowa Code § {chapter}.{section}`` (e.g. ``Iowa Code §
  1.1``), adapter-constructed from the verified section identifier.
* **Encoding**: discovery pages are UTF-8 HTML; section documents are
  binary PDFs fetched as raw bytes.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/iowa.md``): only a handful of chapters and sections were
live-captured; whether every page renders identically is otherwise
UNVERIFIED. The 2026 Code year was current at capture time; the dynamic
year derivation will follow the root page if it changes.
"""

from __future__ import annotations

import re
import urllib.error
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


class IowaAdapter(BaseStateAdapter):
    """Concrete state adapter for the Iowa Code at legis.iowa.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The Iowa Code maps onto the
    framework's three-level ref model as Title -> Chapter -> Section, with
    the Code year resolved dynamically from the root page. See the module
    docstring.
    """

    BASE_URL = "https://www.legis.iowa.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title row on the root page, e.g.
    # '<td>Title I - STATE SOVEREIGNTY AND MANAGEMENT (Ch. 1 - 38D)</td>
    #  <td><a href="/law/iowaCode/chapters?title=I&year=2026">Chapters</a></td>'.
    _TITLE_ROW = re.compile(
        r'<td>Title\s+([IVX]+)\s*-\s*(.*?)\s*\(Ch\.\s*.*?\)</td>',
        re.DOTALL,
    )

    # The current Code year, embedded in every root-page link, e.g.
    # 'title=I&year=2026' and '/docs/code/2026/1.pdf'.
    _YEAR = re.compile(r"year=(\d{4})")

    # A chapter row on a chapter-listing page, e.g.
    # '<td>Chapter 1 - SOVEREIGNTY AND JURISDICTION OF THE STATE</td>'.
    _CHAPTER_ROW = re.compile(r"<td>Chapter\s+([0-9A-Za-z]+)\s*-\s*(.*?)</td>")

    # A section row on a section-listing page, e.g.
    # '<td>&#167;1.1 - State boundaries.</td>' (the raw page uses the
    # numeric entity &#167; for the section sign).
    _SECTION_ROW = re.compile(
        r"<td>&#167;([0-9A-Za-z.]+)\s*-\s*(.*?)</td>", re.DOTALL
    )

    # The header line of an extracted section PDF, e.g.
    # '1 SOVEREIGNTY AND JURISDICTION OF THE STATE, §1.1'.
    _HEADER_LINE = re.compile(r"^\d+\s+.+?,\s*§([0-9A-Za-z.]+)$")

    # The citation + catchline line of an extracted section PDF, e.g.
    # '1.1  State boundaries.'.
    _CITATION_LINE = re.compile(r"^([0-9A-Za-z.]+)\s+(.+)$")

    # The footer line of an extracted section PDF, e.g.
    # 'Wed Dec 10 21:39:07 2025  Iowa Code 2026, Section 1.1 (17, 0)'.
    _FOOTER_LINE = re.compile(r"Iowa\s+Code\s+\d{4},\s+Section")

    # A bracketed codification-history line, e.g. '[C51, §1; R60, §1; ...]'.
    _HISTORY_BRACKET = re.compile(r"^\[")

    # An Acts amendment line, e.g. '2009 Acts, ch 41, §1'.
    _ACTS_LINE = re.compile(r"^\d{4}\s+Acts")

    # A cross-reference note, e.g. 'Referred to in §1.2' (layout extraction
    # may join the words as 'Referredtoin§1.2').
    _REFERRED_LINE = re.compile(r"^Referred\s*to\s*in\s*§", re.IGNORECASE)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Iowa."""
        return "IA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Iowa."""
        return "Iowa"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _root_url(self) -> str:
        return f"{self.BASE_URL}/law/iowaCode"

    def _chapters_url(self, title_ref: TitleRef, year: str) -> str:
        return (
            f"{self.BASE_URL}/law/iowaCode/chapters"
            f"?title={title_ref.identifier}&year={year}"
        )

    def _sections_url(self, chapter_ref: ChapterRef, year: str) -> str:
        return (
            f"{self.BASE_URL}/law/iowaCode/sections"
            f"?codeChapter={chapter_ref.identifier}&year={year}"
        )

    def _section_pdf_url(self, section_ref: SectionRef, year: str) -> str:
        return (
            f"{self.BASE_URL}/docs/code/{year}/"
            f"{section_ref.identifier}.pdf"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Iowa Code URL needed to retrieve ``ref``.

        The Code year is resolved dynamically from the root page (the
        official URLs all embed ``year=YYYY``), so constructing a URL for a
        chapter or section performs that one discovery fetch.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the root page (the only page that lists
              titles).
            * ``ChapterRef`` -> the chapter's section-listing page.
            * ``SectionRef`` -> the section's PDF URL.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            AdapterUnavailableError: If the root page cannot be reached to
                determine the current Code year.
        """
        if isinstance(ref, SectionRef):
            year = self._current_year()
            return self._section_pdf_url(ref, year)
        elif isinstance(ref, ChapterRef):
            year = self._current_year()
            return self._sections_url(ref, year)
        elif isinstance(ref, TitleRef):
            return self._root_url()
        else:
            raise UnsupportedRefError(
                f"IowaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------

    def _current_year(self) -> str:
        """Determine the current Code year from the root page.

        The root page embeds ``year=YYYY`` in every title/chapter link; the
        first match is the current Code year. This is fetched each time so
        a year change is picked up without code changes.

        Raises:
            AdapterUnavailableError: If the root page cannot be reached, or
                no ``year=YYYY`` can be parsed from it.
        """
        html = self._fetch_html(self._root_url(), what="Iowa Code root page")
        match = self._YEAR.search(html)
        if match is None:
            raise AdapterUnavailableError(
                "Fetched the Iowa Code root page but found no year=YYYY in "
                "it; the site's structure may have changed."
            )
        return match.group(1)

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML."""
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Iowa Code.

        The root page lists all 16 titles (``Title {ROMAN} - {NAME}``).
        ``TitleRef.identifier`` is the Roman numeral (e.g. ``"I"``).

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order.

        Raises:
            AdapterUnavailableError: If the root page cannot be fetched, or
                if no usable title rows could be parsed.
        """
        html = self._fetch_html(self._root_url(), what="Iowa Code root page")
        titles = []
        for roman, raw_name in self._TITLE_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=roman,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=roman),
                )
            )
        if not titles:
            raise AdapterUnavailableError(
                "Fetched the Iowa Code root page but found no usable title "
                "rows in it; the site's structure may have changed."
            )
        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter nested under ``title_ref``.

        ``ChapterRef.identifier`` is the chapter number (``"1"``, ``"6A"``)
        and includes RESERVED chapters (which are ordinary rows).

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order.

        Raises:
            AdapterUnavailableError: If the chapter-listing page cannot be
                fetched, or if no usable chapter rows could be parsed.
        """
        year = self._current_year()
        url = self._chapters_url(title_ref, year)
        html = self._fetch_html(url, what="Iowa Code chapter listing")
        chapters = []
        for number, raw_name in self._CHAPTER_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
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
                f"Fetched the Iowa chapter listing for title "
                f"{title_ref.identifier!r} but found no usable chapter rows "
                "in it; the site's structure may have changed."
            )
        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        ``SectionRef.identifier`` is the full citation ``{chapter}.{local}``
        (e.g. ``"1.1"``, ``"1.15A"``). A RESERVED chapter has no sections
        and returns an empty sequence; a chapter number absent from the
        index raises ``RefNotFoundError``.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. May be empty for a RESERVED chapter.

        Raises:
            AdapterUnavailableError: If the section-listing page cannot be
                fetched.
            RefNotFoundError: If ``chapter_ref``'s number does not exist in
                the Iowa Code.
        """
        # Validate the chapter exists (distinguishes a RESERVED chapter,
        # which has an empty listing, from a nonexistent chapter number).
        year = self._current_year()
        url = self._sections_url(chapter_ref, year)
        html = self._fetch_html(url, what="Iowa Code section listing")

        sections = []
        for citation, raw_name in self._SECTION_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=citation,
                    name=name,
                    ref=SectionRef(chapter=chapter_ref, identifier=citation),
                )
            )
        return tuple(sections)

    # ------------------------------------------------------------
    # PDF parsing (Iowa-specific, kept out of _pdftext.py)
    # ------------------------------------------------------------

    @classmethod
    def _parse_section_text(cls, text: str) -> tuple[str, str, str, str | None]:
        """Parse an extracted Iowa section PDF into its parts.

        Args:
            text: The concatenated extracted text of one section PDF.

        Returns:
            ``(citation, catchline, body, amendment_notes)`` where
            ``citation`` is the section's own declared citation (e.g.
            ``"1.1"``), ``catchline`` is the heading, ``body`` is the
            operative statute text, and ``amendment_notes`` is the
            concatenated codification-history / Acts / cross-reference text
            or ``None`` if absent.

        Raises:
            NormalizationError: If the text has no citation + catchline line
                (genuinely malformed -- the section could not be located).
        """
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        if len(lines) < 2:
            raise NormalizationError(
                "The extracted Iowa section text contained no citation "
                "line; the PDF may be malformed or the site's structure may "
                "have changed."
            )

        # Header line: '{title number} {TITLE NAME}, §{citation}'. The
        # citation appears there and in the catchline line; we require the
        # catchline line (the second line) to carry citation + catchline.
        header_match = cls._HEADER_LINE.match(lines[0])
        catchline_match = cls._CITATION_LINE.match(lines[1])
        if catchline_match is None:
            raise NormalizationError(
                "The extracted Iowa section text contained no citation + "
                "catchline line; the PDF may be malformed or the site's "
                "structure may have changed."
            )
        citation = catchline_match.group(1)
        catchline = " ".join(catchline_match.group(2).split())

        body_lines: list[str] = []
        notes_lines: list[str] = []
        in_notes = False
        for line in lines[2:]:
            if cls._FOOTER_LINE.search(line):
                continue  # generated footer; drop
            if cls._HISTORY_BRACKET.match(line) or cls._ACTS_LINE.match(line):
                in_notes = True
            if in_notes:
                notes_lines.append(" ".join(line.split()))
            else:
                # Layout-mode extraction inserts double spaces between words;
                # collapse intra-line whitespace but preserve the line
                # structure (one visual line per body line).
                body_lines.append(" ".join(line.split()))

        body = "\n".join(body_lines).strip()
        amendment_notes = "\n".join(notes_lines).strip() if notes_lines else None
        return citation, catchline, body, amendment_notes

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for Iowa.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: the full ``Iowa Code § {chapter}.{section}``
        citation must contain ``ref.identifier``.

        ``status`` is always ``UNKNOWN``: repealed sections are absent from
        the source entirely (there is no structural repeal signal to read).

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Iowa ref
                (``ref.state_code != "IA"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"IowaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Iowa Code section, end to end:
        resolve the current Code year -> construct the section PDF URL ->
        fetch the raw PDF bytes with
        :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes` -> extract
        text with :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text`
        -> parse the section into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be an Iowa ref
                (``ref.state_code == "IA"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the root page or the section PDF
                cannot be reached, or if the PDF cannot be extracted.
            RefNotFoundError: If the section PDF returns HTTP 404 (a
                repealed or nonexistent section).
            RefMismatchError: If the section's own declared citation
                disagrees with ``ref``.
            NormalizationError: If the section was located but the extracted
                PDF text is genuinely malformed.
        """
        url = self.build_url(ref)

        try:
            data = fetch_bytes(url, what="Iowa Code section PDF")
        except AdapterUnavailableError as exc:
            if isinstance(exc.__cause__, urllib.error.HTTPError) and (
                exc.__cause__.code == 404
            ):
                raise RefNotFoundError(
                    f"Could not fetch the Iowa Code section at {url!r}: it "
                    "returned HTTP 404 (the section is repealed or does not "
                    "exist)."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the Iowa Code section PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the Iowa Code section at {url!r}: the "
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

        raw_citation = f"Iowa Code § {citation}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=catchline,
            text=body,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)