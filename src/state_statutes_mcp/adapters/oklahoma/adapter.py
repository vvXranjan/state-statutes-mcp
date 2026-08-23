"""OklahomaAdapter: the Oklahoma-specific concrete state adapter.

Source: the official Oklahoma Statutes at ``https://www.oklegislature.gov``
(the Oklahoma Legislature). Each title's full text is served as one PDF
at ``/OK_Statutes/CompleteTitles/os{N}.pdf``. This is the framework's
fourth PDF-consuming adapter (after Kentucky, Iowa, and New Mexico) and
reuses the same ``fetch_bytes`` -> ``extract_pdf_text`` pipeline unchanged.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/oklahoma.md``;
all structures verified against real live captures of the official host on
Aug 23 2026 from this environment):

* Official title index: ``https://www.oklegislature.gov/osStatuesTitle.html``
  lists every title as ``CompleteTitles/os{N}.pdf`` (90 PDFs; titles are
  numeric or numeric-plus-letter, e.g. ``3A``, ``74E``, ``85A``; some
  numbers are gaps, e.g. 35, 48, 55 are absent).
* Title PDFs: ``https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os{N}.pdf``.
* **Heterogeneous hierarchy (VERIFIED)**: most titles are FLAT
  (``Title -> Section``, e.g. Title 21 uses ``§21-701.7``); a minority are
  CHAPTERED (``Title -> Chapter -> Section``, e.g. Title 2 uses ``§2-1-1``).
  This is the approved architecture: for FLAT titles the adapter exposes a
  single synthetic chapter whose identifier equals the title number; for
  CHAPTERED titles the real chapters are exposed.
* **PDF structure (VERIFIED)**:
  * The PDF begins with a table of contents whose section lines carry
    dotted leaders and trailing page numbers (e.g.
    ``§21-701.7.  Murder in the first degree. ...... 299``).
  * The body follows the TOC; a body section line is ``§{citation}.
    {Catchline}.`` with NO dotted leader. Body section lines are
    distinguished from TOC lines by the absence of dotted leaders
    (``...``) in the line or its immediate continuation.
  * Each body section ends at the next body section citation.
  * Footers (``Oklahoma Statutes - Title {N}. {NAME} Page {p}``) are
    interleaved and must be stripped.
  * History is prose after the body (``Added by Laws ... Amended by Laws
    ...``) and ``NOTE:`` blocks; these become ``amendment_notes``.
* **Citation format**: ``{title}-{section}`` (flat) or ``{title}-{chapter}-
  {section}`` (chaptered), with decimal (``2-2-17.1``), lettered
  (``2-2-17A``), and lettered-title (``3A-201``) variants. The full
  citation is always used as ``SectionRef.identifier``.
* **Error boundary (VERIFIED)**: nonexistent title PDFs return a genuine
  HTTP 404. A nonexistent chapter/section is absent from the PDF body.
  The PDF self-identifies its title (e.g. ``TITLE 21. ...``), so a wrong
  title's PDF is detectable.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/oklahoma.md``): only Titles 1, 2, 3A, 21, 11, 68 (and
trimmed page-range slices of 2 and 21) were sampled; per-title PDF
uniformity is otherwise UNVERIFIED. Per-title PDFs are large (up to
~5.6 MB / 884 pages), so each retrieval re-fetches and re-extracts the
whole title (P2 performance limitation; no caching in B16).
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


class OklahomaAdapter(BaseStateAdapter):
    """Concrete state adapter for the Oklahoma Statutes at
    oklegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Oklahoma's heterogeneous
    hierarchy is handled adapter-locally: FLAT titles expose one synthetic
    chapter whose identifier equals the title number; CHAPTERED titles
    expose the real chapters. ``SectionRef.identifier`` is always the full
    Oklahoma citation. See the module docstring.
    """

    BASE_URL = "https://www.oklegislature.gov"
    TITLES_PATH = "/osStatuesTitle.html"
    COMPLETE_TITLES_PATH = "/OK_Statutes/CompleteTitles"
    DEFAULT_TIMEOUT_SECONDS = 60

    # A title row on the official index, e.g.
    # '<a href="https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf"><b>Title
    #  21. </b></a>Crimes and Punishments (3510KB)'.
    # Some names contain parentheticals (e.g. Title 1 "Abstracting (See 74,
    # State Government)"), so the name is captured up to the first "<" or
    # the final "(NKB)" size token, whichever comes first.
    _TITLE_ROW = re.compile(
        r'href="[^"]*/CompleteTitles/os([0-9A-Za-z]+)\.pdf"[^>]*>\s*'
        r"<b>Title\s+[0-9A-Za-z]+\.\s*</b></a>\s*(.*?)(?:\((\d+)KB\)|</a>|<BR|<br)",
        re.DOTALL,
    )

    # Any title PDF URL on the index (authoritative title-number set,
    # including lettered titles and gaps).
    _TITLE_PDF = re.compile(r"CompleteTitles/os([0-9A-Za-z]+)\.pdf")

    # A section-citation line, e.g. '§21-701.7.  Murder in the first
    # degree.' or '§2-1-1.  Short title.' or '§3A-201.  Oklahoma Horse'.
    _SECTION_START = re.compile(
        r"^§([0-9A-Za-z]+(?:-[0-9A-Za-z.]+)*)\.\s",
        re.MULTILINE,
    )

    # A body footer line, e.g.
    # 'Oklahoma Statutes - Title 21. Crimes and Punishments Page 301'.
    _FOOTER = re.compile(r"^Oklahoma Statutes - Title\s+.+?Page\s+\d+\s*$")

    # The history/amendment block start (prose after the body). Most sections
    # use "Added by Laws" / "Amended by Laws"; some use a bare "Laws {year}"
    # line (e.g. 'Laws 1970, c. 260, § 19, emerg. eff. April 22, 1970.').
    _HISTORY_START = re.compile(
        r"^(Added by Laws|Amended by Laws|NOTE:|Laws\s+\d{4})"
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Oklahoma."""
        return "OK"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Oklahoma."""
        return "Oklahoma"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _titles_url(self) -> str:
        return f"{self.BASE_URL}{self.TITLES_PATH}"

    def _title_pdf_url(self, title: str) -> str:
        return f"{self.BASE_URL}{self.COMPLETE_TITLES_PATH}/os{title}.pdf"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Oklahoma URL needed to retrieve ``ref``.

        ``ref`` maps to a per-title PDF. For a ``SectionRef`` or
        ``ChapterRef`` the title is the top of the reference chain.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official title PDF URL (the section lives inside it).

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
        """
        if isinstance(ref, SectionRef):
            return self._title_pdf_url(ref.chapter.title.identifier)
        elif isinstance(ref, ChapterRef):
            return self._title_pdf_url(ref.title.identifier)
        elif isinstance(ref, TitleRef):
            return self._title_pdf_url(ref.identifier)
        else:
            raise UnsupportedRefError(
                f"OklahomaAdapter.build_url does not support refs of type "
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
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Oklahoma Statutes.

        Discovers titles dynamically from the official index (the
        ``os{N}.pdf`` links), including lettered titles and gaps.

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order.

        Raises:
            AdapterUnavailableError: If the index cannot be fetched, or if
                no usable title rows could be parsed.
        """
        html = self._fetch_html(self._titles_url(), what="Oklahoma Statutes index")
        # Authoritative title set: every os{N}.pdf link (covers lettered
        # titles and gaps). Names are attached from parsed rows where
        # available; otherwise a descriptive fallback is used.
        title_numbers = self._TITLE_PDF.findall(html)
        if not title_numbers:
            raise AdapterUnavailableError(
                "Fetched the Oklahoma Statutes index but found no usable "
                "title rows in it; the site's structure may have changed."
            )
        name_by_number: dict[str, str] = {}
        for number, raw_name, _kb in self._TITLE_ROW.findall(html):
            # Strip any residual HTML artifacts; if the name is still
            # malformed, leave it out so the fallback is used.
            cleaned = re.sub(r"<[^>]+>", " ", raw_name)
            cleaned = " ".join(cleaned.split()).strip()
            if cleaned and "<" not in cleaned:
                name_by_number[number] = cleaned
        seen: set[str] = set()
        titles = []
        for number in title_numbers:
            if number in seen:
                continue
            seen.add(number)
            name = name_by_number.get(number) or f"Title {number}"
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=number,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=number),
                )
            )
        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate the chapters under ``title_ref``.

        Oklahoma is heterogeneous: most titles are FLAT (``Title ->
        Section``) and have no real chapter level; a minority are
        CHAPTERED (``Title -> Chapter -> Section``). For a FLAT title this
        returns ONE synthetic chapter whose identifier equals the title
        number; for a CHAPTERED title it returns the real chapters.

        To determine flat-vs-chaptered without a full PDF download, the
        title PDF is fetched and its section citations inspected: if any
        section citation has three parts (``T-C-S``), the title is
        chaptered; otherwise it is flat.

        Args:
            title_ref: The parent title.

        Returns:
            A sequence of :class:`TocNode`, one per chapter.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted.
            RefNotFoundError: If the title PDF returns HTTP 404.
        """
        text = self._fetch_title_text(title_ref)
        citations = [
            m.group(1) for m in self._SECTION_START.finditer(text)
            if not self._is_toc_line(text, m.start())
        ]
        # A title is CHAPTERED if any citation has the form T-C-S where the
        # middle part C is a dot-free small integer (a genuine chapter). Flat
        # titles use T-S (the section may itself be dotted, e.g. 21-701.7, or
        # carry a sub-number, e.g. 21-701.10-1).
        chaptered = any(
            len(cit.split("-")) == 3 and "." not in cit.split("-")[1]
            for cit in citations
        )
        if chaptered:
            # Chaptered title: expose the distinct chapter numbers.
            chapters: dict[str, str] = {}
            for cit in citations:
                parts = cit.split("-")
                if len(parts) >= 3 and "." not in parts[1]:
                    chapters.setdefault(parts[1], f"Chapter {parts[1]}")
            return tuple(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=num,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=num),
                )
                for num, name in sorted(chapters.items(), key=lambda kv: (self._num_key(kv[0]), kv[0]))
            )
        # Flat title: one synthetic chapter whose identifier equals the title number.
        return (
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=title_ref.identifier,
                name=f"Title {title_ref.identifier} sections",
                ref=ChapterRef(title=title_ref, identifier=title_ref.identifier),
            ),
        )

    @staticmethod
    def _num_key(identifier: str) -> tuple:
        m = re.match(r"^(\d+)([A-Za-z]*)$", identifier)
        return (int(m.group(1)), m.group(2)) if m else (10**9, identifier)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        For a FLAT title, ``chapter_ref`` is the synthetic chapter (whose
        identifier equals the title number); all sections of that title
        are returned. For a CHAPTERED title, only the sections of the
        requested real chapter are returned.

        ``SectionRef.identifier`` is always the full Oklahoma citation.

        Args:
            chapter_ref: The parent chapter.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted.
            RefNotFoundError: If the title PDF returns HTTP 404.
        """
        title = chapter_ref.title.identifier
        text = self._fetch_title_text(chapter_ref.title)
        chapter = chapter_ref.identifier
        sections = []
        # Determine whether this is a chaptered title (the caller supplied a
        # real chapter) or a flat title (the caller supplied the synthetic
        # chapter equal to the title number).
        chaptered = any(
            len(cit.split("-")) == 3 and "." not in cit.split("-")[1]
            for cit in (
                m.group(1) for m in self._SECTION_START.finditer(text)
                if not self._is_toc_line(text, m.start())
            )
        )
        for match in self._SECTION_START.finditer(text):
            if self._is_toc_line(text, match.start()):
                continue
            citation = match.group(1)
            if chaptered:
                # Only sections whose second part matches the requested real chapter.
                parts = citation.split("-")
                if len(parts) < 3 or parts[1] != chapter:
                    continue
            else:
                # Flat title: the synthetic chapter equals the title number;
                # include every section of this title.
                if not citation.startswith(f"{title}-"):
                    continue
            catchline = " ".join(
                text[match.end():].split("\n", 1)[0].split()
            )
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=citation,
                    name=catchline,
                    ref=SectionRef(chapter=chapter_ref, identifier=citation),
                )
            )
        return tuple(sections)

    # ------------------------------------------------------------
    # Title PDF retrieval + section location
    # ------------------------------------------------------------

    def _fetch_title_text(self, title_ref: TitleRef) -> str:
        """Fetch the title PDF and extract its text.

        Raises:
            AdapterUnavailableError: If the PDF cannot be reached or
                extracted.
            RefNotFoundError: If the title PDF returns HTTP 404.
        """
        url = self._title_pdf_url(title_ref.identifier)
        try:
            data = fetch_bytes(url, what="Oklahoma Statutes title PDF")
        except AdapterUnavailableError as exc:
            if isinstance(exc.__cause__, urllib.error.HTTPError) and (
                exc.__cause__.code == 404
            ):
                raise RefNotFoundError(
                    f"Could not fetch the Oklahoma title PDF at {url!r}: it "
                    "returned HTTP 404 (the title does not exist)."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the Oklahoma title PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the Oklahoma title PDF at {url!r}: the "
                "site returned a non-PDF page (the title does not resolve)."
            )

        return extract_pdf_text(data)

    @staticmethod
    def _is_toc_line(text: str, offset: int) -> bool:
        """Return True if the section citation at ``offset`` is a table-of-
        contents entry rather than a body section.

        A TOC entry has dotted leaders (``...``) on its own line or in its
        immediate continuation; a body section never does. The continuation
        scan stops at the next ``§`` line.
        """
        lines = text.splitlines()
        # find the line containing offset
        char_count = 0
        line_idx = 0
        for i, l in enumerate(lines):
            if char_count + len(l) + 1 > offset:
                line_idx = i
                break
            char_count += len(l) + 1
        else:
            return True
        j = line_idx
        while j < len(lines):
            l = lines[j]
            if re.search(r"\.{3,}", l):
                return True
            if j > line_idx and re.match(r"^§", l):
                return False
            if j > line_idx + 4:
                return False
            j += 1
        return False

    # ------------------------------------------------------------
    # PDF parsing (Oklahoma-specific, kept out of _pdftext.py)
    # ------------------------------------------------------------

    @classmethod
    def _extract_body_section(
        cls, text: str, citation: str
    ) -> list[str] | None:
        """Locate the body occurrence of ``citation`` in ``text``.

        Returns the section's body lines (from the citation line up to but
        not including the next body section citation), or ``None`` if the
        citation does not appear in the body.

        The TOC lists every section first (with dotted leaders); the body
        repeats each section without leaders. This returns the BODY
        occurrence.
        """
        lines = text.splitlines()
        pat = re.compile(rf"^§{re.escape(citation)}\.\s")
        # Find candidate lines; pick the first non-TOC occurrence.
        start = None
        for i, l in enumerate(lines):
            if pat.match(l):
                if not cls._is_toc_line(text, cls._line_offset(lines, i)):
                    start = i
                    break
        if start is None:
            return None
        # Boundary: next body section citation.
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if cls._SECTION_START.match(lines[j]) and not cls._is_toc_line(
                text, cls._line_offset(lines, j)
            ):
                end = j
                break
        return lines[start:end]

    @staticmethod
    def _line_offset(lines: list[str], idx: int) -> int:
        """Return the character offset of the start of line ``idx``."""
        return sum(len(l) + 1 for l in lines[:idx])

    @classmethod
    def _parse_section(cls, text: str, citation: str) -> ParsedDocument:
        """Parse one Oklahoma section from an extracted title PDF.

        Args:
            text: The concatenated extracted text of a title PDF.
            citation: The requested ``SectionRef.identifier`` (full
                citation, e.g. ``"21-701.7"``).

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"Okla. Stat. tit. {title}, § {citation}"``, ``heading`` =
            the catchline, ``text`` = the body (footers and history
            excluded), and ``amendment_notes`` = the history/notes prose.

        Raises:
            RefNotFoundError: If the citation does not appear in the body.
            NormalizationError: If the section was located but the text is
                malformed (missing the citation line).
        """
        chunk = cls._extract_body_section(text, citation)
        if chunk is None:
            raise RefNotFoundError(
                f"Could not find section {citation!r} in the Oklahoma title "
                "PDF."
            )

        citation_match = cls._SECTION_START.match(chunk[0])
        if citation_match is None:
            raise NormalizationError(
                "The extracted Oklahoma section text contained no citation "
                "line; the title PDF may be malformed."
            )
        found_citation = citation_match.group(1)
        if found_citation != citation:
            raise RefMismatchError(
                f"Requested section {citation!r} does not match the "
                f"citation found in the extracted PDF: {found_citation!r}."
            )

        # The catchline runs from the citation line until the first line
        # that ends with a period (the catchline's terminal period).
        # Wrapped catchlines (e.g. "2-1-2. State Department of Agriculture -
        # Establishment - Composition.") span multiple lines.
        catchline_end = 0
        for i, line in enumerate(chunk):
            if line.rstrip().endswith("."):
                catchline_end = i
                break
        catchline = " ".join(line.strip() for line in chunk[: catchline_end + 1])
        # Strip the citation prefix from the catchline.
        catchline = catchline[citation_match.end() :].strip()

        # Remaining lines: body, then history/notes. Footers are dropped.
        body_lines: list[str] = []
        notes_lines: list[str] = []
        in_notes = False
        for line in chunk[catchline_end + 1 :]:
            stripped = line.strip()
            if not stripped:
                continue
            if cls._FOOTER.match(stripped):
                continue
            if cls._HISTORY_START.match(stripped):
                in_notes = True
            if in_notes:
                notes_lines.append(stripped)
            else:
                body_lines.append(stripped)

        body = "\n".join(body_lines)
        amendment_notes = "\n".join(notes_lines) if notes_lines else None

        title = citation.split("-")[0]
        return ParsedDocument(
            raw_citation=f"Okla. Stat. tit. {title}, § {citation}",
            heading=catchline,
            text=body,
            amendment_notes=amendment_notes,
            source_url="",
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Oklahoma.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: the raw citation must contain
        ``ref.identifier``.

        ``status`` is always ``UNKNOWN``: the source signals repealed and
        renumbered sections only as prose in the catchline (``Repealed by
        Laws ...``, ``Renumbered as ...``) with no substantive body -- per
        the framework rule (same decision as Nebraska/Massachusetts/
        Kentucky/New Mexico), a prose-only signal is not a structural
        marker, so the status is not inferred from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Oklahoma ref
                (``ref.state_code != "OK"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"OklahomaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Oklahoma Statutes section, end to end:
        fetch the title PDF bytes with
        :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes` -> extract
        text with :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text`
        -> locate and parse the requested section -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be an Oklahoma ref
                (``ref.state_code == "OK"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be reached or
                extracted.
            RefNotFoundError: If the title PDF returns HTTP 404, or the
                section's citation is absent from the title PDF body.
            RefMismatchError: If the section's own declared citation
                disagrees with ``ref``.
            NormalizationError: If the section was located but the text is
                malformed.
        """
        text = self._fetch_title_text(ref.chapter.title)
        parsed = self._parse_section(text, ref.identifier)
        parsed = parsed.model_copy(update={"source_url": self.build_url(ref)})
        return self.normalize(parsed, ref)