"""NewMexicoAdapter: the New Mexico-specific concrete state adapter.

Source: the official New Mexico Statutes Annotated (NMSA) 1978 at
``https://nmonesource.com``, published by the New Mexico Compilation
Commission. Discovery is server-rendered HTML navigation pages; each
chapter's full text is served as one PDF document. This is the framework's
third PDF-consuming adapter (after Kentucky and Iowa) and reuses the same
``fetch_bytes`` -> ``extract_pdf_text`` pipeline unchanged.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/new_mexico.md``;
all structures verified against real live captures of the official host on
Aug 23 2026 from this environment):

* Base URL ``https://nmonesource.com``.
* **Hierarchy**: the NMSA has NO Title level in the official navigation --
  its real structure is **Chapter -> Article -> Section**. This maps onto
  the framework's ``TitleRef -> ChapterRef -> SectionRef`` model with a
  single **synthetic ``TitleRef``** (identifier ``"NMSA"``), the same
  established pattern used by Minnesota, Nebraska, and Wisconsin. The
  Article level is folded into the section identifier (like Montana folds
  Part and Kentucky uses the full citation as the section identifier).
* **Chapter discovery**: the navigation pages
  (``/nmos/nmsa/en/nav_date.do?iframe=true&page={1..4}``) list all 84
  chapters (25 + 25 + 25 + 9) as ``Chapter {N} - {NAME}`` with an **opaque
  item ID** (``/nmos/nmsa/en/item/{id}/index.do``). ``ChapterRef.identifier``
  is the chapter number (e.g. ``"1"``, ``"22A"``). The opaque IDs are
  NON-sequential (1->4351, 2->4359, 3->4362) and MUST be discovered
  dynamically -- never hardcoded.
* **Section identifiers**: the NMSA citation is ``{chapter}-{article}-
  {section}`` (e.g. ``1-2-1``), with decimal variants (``1-1-1.1``).
  ``SectionRef.identifier`` is the full citation. Lettered chapters exist
  (``22A``); lettered *section* identifiers were NOT verified.
* **Chapter PDF**: each chapter's full text is one PDF at
  ``/nmos/nmsa/en/{item_id}/1/document.do`` (the ``/1/`` segment is
  required; ``/2/`` returns 404). Sizes vary widely (Chapter 1 = 3.78 MB /
  657 pages; Chapter 30 = 5.84 MB / 1138 pages; Chapter 77 = 1.4 MB / 233
  pages). PDFs are text-based and extract cleanly with the shared
  ``extract_pdf_text`` (default pypdf mode; no fragmentation fallback
  triggered).
* **PDF text structure** (VERIFIED on Chapters 1, 2, 30, 77):
  * Section start: ``{citation}. {Catchline}.`` at a line start (e.g.
    ``1-2-1. Secretary of state; chief election officer; rules.``).
  * Body: the operative statute text (subsections ``A.``/``B.``/``(1)``).
  * ``History: {history}`` -- the legislative-history block.
  * ``ANNOTATIONS`` -- a block of case law / Am. Jur. / C.J.S. references
    that is NOT statutory text.
  * The **next section citation** at a line start is the section boundary.
* **Repealed sections** (VERIFIED, e.g. ``1-2-8``): ``1-2-8. Repealed.``
  with no body, then ``History:`` (containing ``repealed by Laws ...``) and
  ``ANNOTATIONS``. Per the framework's prose-only-repeal rule (the same
  decision as Nebraska/Massachusetts/Kentucky), the catchline is returned
  as ``heading``, ``text=""``, ``status=UNKNOWN``, and the history is
  preserved in ``amendment_notes``.
* **Error boundary (VERIFIED)**: an invalid chapter item ID returns a
  genuine HTTP 404. A nonexistent chapter number is absent from the nav
  pages. A section absent from a chapter PDF is detectable (its citation
  does not appear).
* **Citation**: ``{chapter}-{article}-{section}`` (e.g. ``1-2-1``), used
  verbatim as ``SectionRef.identifier``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/new_mexico.md``): only Chapters 1, 2, 30, and 77 (and a
trimmed page-range slice of 1 and 2) were live-captured; whether every
chapter PDF renders identically is otherwise UNVERIFIED. Lettered section
identifiers were not verified. Large chapter PDFs make each ``get_section``
request heavy (see the performance limitation).
"""

from __future__ import annotations

import re
import urllib.error
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_bytes, fetch_url
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


class NewMexicoAdapter(BaseStateAdapter):
    """Concrete state adapter for the New Mexico Statutes Annotated at
    nmonesource.com.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The NMSA maps onto the
    framework's three-level ref model as a single synthetic Title ->
    Chapter -> Section, with the Article level folded into the section
    identifier and the chapter's opaque item ID resolved dynamically from
    the navigation pages. See the module docstring.
    """

    BASE_URL = "https://nmonesource.com"
    NMSA_PATH = "/nmos/nmsa/en"
    DEFAULT_TIMEOUT_SECONDS = 60

    # The synthetic title standing in for the NMSA's absent Title level.
    SYNTHETIC_TITLE = "NMSA"

    # Number of navigation pages covering all 84 chapters (25+25+25+9).
    NAV_PAGE_COUNT = 4

    # A chapter row on a navigation page, e.g.
    # '<a href="/nmos/nmsa/en/item/4351/index.do">Chapter 1 - Elections</a>'.
    _CHAPTER_ROW = re.compile(
        r'/nmos/nmsa/en/item/(\d+)/index\.do[^>]*>\s*Chapter\s+([0-9A-Za-z]+)[^<]*',
        re.DOTALL,
    )

    # A section start in an extracted chapter PDF, e.g. '1-2-1. ',
    # '1-1-1.1. ', '22A-1-1. ' (lettered chapters like 22A are VERIFIED).
    # Anchored to a line start and requiring the trailing period +
    # whitespace so inline citations in the body ("Section 1-1-13 NMSA
    # 1978") and cross-references are never mistaken for boundaries.
    _SECTION_START = re.compile(
        r"^(\d{1,2}[A-Z]?)-(\d{1,2})-(\d{1,3}(?:\.\d+)?)\.\s+",
        re.MULTILINE,
    )

    # The catchline/citation line of a section, e.g.
    # '1-2-1. Secretary of state; chief election officer; rules.'.
    _CITATION_LINE = re.compile(r"^([0-9A-Za-z.-]+)\.\s+(.*)$")

    # The History block marker.
    _HISTORY = re.compile(r"^History:\s*", re.MULTILINE)

    # The ANNOTATIONS block marker (case law / commentary, not statute text).
    _ANNOTATIONS = re.compile(r"^ANNOTATIONS\s*$", re.MULTILINE)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for New Mexico."""
        return "NM"

    @property
    def state_name(self) -> str:
        """Human-facing display name for New Mexico."""
        return "New Mexico"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _nav_url(self, page: int) -> str:
        return f"{self.BASE_URL}{self.NMSA_PATH}/nav_date.do?iframe=true&page={page}"

    def _chapter_pdf_url(self, opaque_item_id: str) -> str:
        return (
            f"{self.BASE_URL}{self.NMSA_PATH}/{opaque_item_id}/1/document.do"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official New Mexico URL needed to retrieve ``ref``.

        New Mexico's chapter addressing is opaque: the chapter's item ID
        cannot be derived from the chapter number, so it is resolved
        dynamically from the navigation pages (like Kentucky's opaque
        chapter IDs). ``build_url`` therefore performs that resolution for
        a ``ChapterRef`` or ``SectionRef``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the first navigation page (the closest real
              document that lists titles/chapters).
            * ``ChapterRef`` -> the chapter's PDF URL.
            * ``SectionRef`` -> the chapter's PDF URL (the section lives
              inside the chapter PDF).

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If the chapter number is not listed in the
                navigation pages.
        """
        if isinstance(ref, SectionRef):
            opaque_item_id = self._item_id_for(ref.chapter.identifier)
            return self._chapter_pdf_url(opaque_item_id)
        elif isinstance(ref, ChapterRef):
            opaque_item_id = self._item_id_for(ref.identifier)
            return self._chapter_pdf_url(opaque_item_id)
        elif isinstance(ref, TitleRef):
            return self._nav_url(1)
        else:
            raise UnsupportedRefError(
                f"NewMexicoAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML."""
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Opaque-ID resolution (adapter-local)
    # ------------------------------------------------------------

    def _chapter_map(self) -> dict[str, str]:
        """Discover the chapter-number -> opaque-item-ID mapping from the
        four navigation pages.

        The opaque IDs are NON-sequential and must be discovered live --
        they are never hardcoded. The mapping is rebuilt on each call so a
        change in the official structure is picked up (mirroring Kentucky's
        and Iowa's dynamic-discovery approach).

        Raises:
            AdapterUnavailableError: If a navigation page cannot be fetched,
                or if no usable chapter rows could be parsed from any page.
        """
        mapping: dict[str, str] = {}
        for page in range(1, self.NAV_PAGE_COUNT + 1):
            html = self._fetch_html(
                self._nav_url(page), what="New Mexico statutes navigation"
            )
            for item_id, number in self._CHAPTER_ROW.findall(html):
                mapping[number] = item_id
        if not mapping:
            raise AdapterUnavailableError(
                "Fetched the New Mexico navigation pages but found no usable "
                "chapter rows in them; the site's structure may have changed."
            )
        return mapping

    def _item_id_for(self, chapter_number: str) -> str:
        """Resolve ``chapter_number`` to its opaque item ID.

        Raises:
            RefNotFoundError: If the chapter number is not present in the
                navigation pages (the chapter does not exist).
        """
        mapping = self._chapter_map()
        if chapter_number not in mapping:
            raise RefNotFoundError(
                f"Could not resolve chapter {chapter_number!r}: it is not "
                "listed in the New Mexico Statutes Annotated navigation."
            )
        return mapping[chapter_number]

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate the NMSA's titles.

        The NMSA has NO Title level; this returns the single synthetic
        title ``"NMSA"`` (the Minnesota/Nebraska/Wisconsin synthetic-title
        precedent).

        Returns:
            A sequence with one :class:`TocNode` for the synthetic title.
        """
        return (
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=self.SYNTHETIC_TITLE,
                name="New Mexico Statutes Annotated 1978",
                ref=TitleRef(state_code=self.state_code, identifier=self.SYNTHETIC_TITLE),
            ),
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter of the NMSA.

        ``ChapterRef.identifier`` is the chapter number (``"1"``, ``"22A"``).

        Args:
            title_ref: The parent title (the synthetic ``"NMSA"`` title).

        Returns:
            A sequence of :class:`TocNode`, one per chapter, sorted by
            chapter number.

        Raises:
            RefNotFoundError: If ``title_ref`` is not the synthetic NMSA
                title.
            AdapterUnavailableError: If the navigation pages cannot be
                fetched.
        """
        if title_ref.identifier != self.SYNTHETIC_TITLE:
            raise RefNotFoundError(
                f"Could not resolve title {title_ref.identifier!r}: New "
                "Mexico has a single synthetic title "
                f"{self.SYNTHETIC_TITLE!r}."
            )
        mapping = self._chapter_map()
        chapters = []
        for number in sorted(mapping, key=self._chapter_sort_key):
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=number,
                    name=f"Chapter {number}",
                    ref=ChapterRef(title=title_ref, identifier=number),
                )
            )
        return tuple(chapters)

    @staticmethod
    def _chapter_sort_key(identifier: str) -> tuple:
        """Sort chapters numerically, with trailing letters ordered after
        the bare number (e.g. '1', '1A', '2', ...)."""
        match = re.match(r"^(\d+)([A-Za-z]*)$", identifier)
        return (int(match.group(1)), match.group(2)) if match else (10**9, identifier)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        The NMSA does not expose per-section URLs; sections are embedded in
        the chapter PDF. This method fetches the chapter PDF, extracts its
        text, and returns one :class:`TocNode` per section, with
        ``identifier`` the full ``{chapter}-{article}-{section}`` citation.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order.

        Raises:
            AdapterUnavailableError: If the chapter PDF cannot be reached or
                extracted.
            RefNotFoundError: If the chapter number is not listed in the
                navigation pages.
        """
        chapter = chapter_ref.identifier
        text, _source_url = self._fetch_chapter_text(
            chapter_ref, what="New Mexico chapter PDF"
        )
        sections = []
        for citation, _catchline in self._iter_sections(text, chapter):
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=citation,
                    name=_catchline,
                    ref=SectionRef(chapter=chapter_ref, identifier=citation),
                )
            )
        return tuple(sections)

    # ------------------------------------------------------------
    # Chapter PDF retrieval + section iteration
    # ------------------------------------------------------------

    def _fetch_chapter_text(self, chapter_ref: ChapterRef, *, what: str) -> tuple[str, str]:
        """Fetch the chapter PDF for ``chapter_ref`` and extract its text.

        Returns:
            ``(text, url)`` — the extracted chapter text and the chapter
            PDF's source URL (used for ``StatuteSection.source_url``).

        Raises:
            AdapterUnavailableError: If the PDF cannot be reached or
                extracted.
            RefNotFoundError: If the chapter number is not listed in the
                navigation pages.
        """
        url = self.build_url(chapter_ref)
        try:
            data = fetch_bytes(url, what=what)
        except AdapterUnavailableError as exc:
            if isinstance(exc.__cause__, urllib.error.HTTPError) and (
                exc.__cause__.code == 404
            ):
                raise RefNotFoundError(
                    f"Could not fetch the New Mexico chapter PDF at {url!r}: "
                    "it returned HTTP 404 (the chapter does not exist)."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the New Mexico chapter PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the New Mexico chapter PDF at {url!r}: "
                "the site returned a non-PDF page (the chapter does not "
                "resolve)."
            )

        return extract_pdf_text(data), url

    def _iter_sections(self, text: str, chapter: str):
        """Yield ``(citation, catchline)`` for every section of ``chapter``
        in the extracted chapter text, in document order.

        The section start regex is anchored to a line start and requires the
        trailing ``. `` so inline citations in the body are never mistaken
        for boundaries. Only sections whose chapter prefix matches the
        requested chapter are yielded (defensive: a wrong chapter's PDF
        would otherwise be silently accepted).
        """
        for match in self._SECTION_START.finditer(text):
            cit_ch, cit_art, cit_sec = match.groups()
            citation = f"{cit_ch}-{cit_art}-{cit_sec}"
            if cit_ch != chapter:
                continue
            # catchline = rest of the citation line after "{citation}. "
            rest = text[match.end() :].split("\n", 1)[0]
            catchline = " ".join(rest.split())
            yield citation, catchline

    # ------------------------------------------------------------
    # PDF parsing (New Mexico-specific, kept out of _pdftext.py)
    # ------------------------------------------------------------

    @classmethod
    def _parse_section(
        cls, text: str, chapter: str, section: str, source_url: str
    ) -> ParsedDocument:
        """Locate and parse one section from an extracted chapter PDF.

        Args:
            text: The concatenated extracted text of a chapter PDF.
            chapter: The chapter number the section must belong to.
            section: The requested ``SectionRef.identifier`` (full citation,
                e.g. ``"1-2-1"``).

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` = ``f"NM Stat.
            Ann. {section}"``, ``heading`` = the catchline, ``text`` = the
            body (History/ANNOTATIONS excluded), and ``amendment_notes`` =
            the ``History:`` block (ANNOTATIONS excluded).

        Raises:
            RefNotFoundError: If the section's citation does not appear in
                the chapter text (the section is absent or repealed-only).
            NormalizationError: If the section was located but the text is
                genuinely malformed (missing the catchline line).
        """
        section_start = cls._SECTION_START.search(
            text, cls._find_section_offset(text, chapter, section)
        )
        if section_start is None or section_start.group(0).strip() != f"{section}.":
            raise RefNotFoundError(
                f"Could not find section {section!r} in the New Mexico "
                f"chapter {chapter!r} PDF."
            )

        # End of the section = the next section citation at a line start.
        next_start = cls._SECTION_START.search(text, section_start.end())
        chunk = text[section_start.start() : next_start.start()] if next_start else text[section_start.start() :]
        lines = chunk.split("\n")

        citation_line = lines[0]
        citation_match = cls._CITATION_LINE.match(citation_line.strip())
        if citation_match is None:
            raise NormalizationError(
                "The extracted New Mexico section text contained no citation "
                "line; the chapter PDF may be malformed or the site's "
                "structure may have changed."
            )
        citation = citation_match.group(1)
        catchline = " ".join(citation_match.group(2).split())

        # Split the remaining lines into body / history / annotations.
        body_lines: list[str] = []
        notes_lines: list[str] = []
        in_annotations = False
        in_history = False
        for line in lines[1:]:
            if cls._ANNOTATIONS.match(line):
                in_annotations = True
                continue
            history_match = cls._HISTORY.match(line)
            if history_match is not None:
                in_history = True
                remainder = line[history_match.end() :].strip()
                if remainder:
                    notes_lines.append(remainder)
                continue
            if in_annotations:
                continue  # ANNOTATIONS are commentary, not statute text
            if in_history:
                notes_lines.append(line)
            else:
                body_lines.append(line)

        body = "\n".join(line.strip() for line in body_lines if line.strip())
        amendment_notes = "\n".join(
            line.strip() for line in notes_lines if line.strip()
        )

        return ParsedDocument(
            raw_citation=f"NM Stat. Ann. {citation}",
            heading=catchline,
            text=body,
            amendment_notes=amendment_notes if amendment_notes else None,
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _find_section_offset(text: str, chapter: str, section: str) -> int:
        """Find the byte offset where ``section`` starts as a section
        citation in ``text``, or ``0`` if absent.

        ``section`` is a full citation like ``"1-2-1"``; it must appear as a
        line-start ``"{section}. "`` (a section boundary), never as an
        inline mention.
        """
        pattern = re.compile(rf"^({re.escape(section)})\.\s+", re.MULTILINE)
        match = pattern.search(text)
        return match.start() if match else 0

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for New
        Mexico.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: the ``NM Stat. Ann. {citation}`` raw citation
        must contain ``ref.identifier``.

        ``status`` is always ``UNKNOWN``: the source signals repealed
        sections only as prose in the catchline (``1-2-8. Repealed.``) with
        no operative body -- per the framework rule (same decision as
        Nebraska/Massachusetts/Kentucky), a prose-only signal is not a
        structural marker, so the status is not inferred from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a New Mexico ref
                (``ref.state_code != "NM"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NewMexicoAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one New Mexico Statutes Annotated section,
        end to end: resolve the chapter's opaque item ID -> fetch the raw
        chapter PDF bytes with
        :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes` -> extract
        text with :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text`
        -> locate and parse the requested section -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a New Mexico ref
                (``ref.state_code == "NM"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the navigation page or the chapter
                PDF cannot be reached, or if the PDF cannot be extracted.
            RefNotFoundError: If the chapter number is not listed in the
                navigation pages, or the section's citation is absent from
                the chapter PDF.
            RefMismatchError: If the section's own declared citation
                disagrees with ``ref``.
            NormalizationError: If the section was located but the extracted
                text is genuinely malformed.
        """
        chapter = ref.chapter.identifier
        text, source_url = self._fetch_chapter_text(
            ref.chapter, what="New Mexico chapter PDF"
        )

        parsed = self._parse_section(text, chapter, ref.identifier, source_url)
        return self.normalize(parsed, ref)