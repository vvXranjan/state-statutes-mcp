"""WyomingAdapter: the Wyoming-specific concrete state adapter.

Source: the official Wyoming Legislature publication of the Wyoming
Statutes at ``https://wyoleg.gov/statutes/compress/title{NN:02d}.pdf``.
Each title's full text is served as one PDF (e.g. ``title01.pdf`` for
Title 1, ``title31.pdf`` for Title 31). This is the framework's fifth
PDF-consuming adapter (after Kentucky, Iowa, New Mexico, and Oklahoma) and
reuses the same ``fetch_bytes`` -> ``extract_pdf_text`` pipeline unchanged.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/wyoming.md``;
all structures verified against real live captures of the official host on
Aug 24 2026 from this environment):

* Official per-title PDFs: ``https://wyoleg.gov/statutes/compress/title{NN:02d}.pdf``
  (zero-padded two-digit title number). Valid titles return ``application/pdf``;
  nonexistent titles return HTTP 200 with an HTML SPA shell page (NOT a PDF),
  so the ``%PDF`` magic check distinguishes valid from invalid titles.
* **Valid title set (VERIFIED)**: titles 01-42, 97 (Wyoming Constitution),
  and 99 (Noncodified Statutes). No valid titles exist in 43-96 or 98 or
  beyond 99.
* **Hierarchy**: ``Title -> Chapter -> [Article] -> Section``. Article is an
  intermediate grouping that carries no section-address information (the
  section citation ``T-C-S`` does not encode the article), so it is folded
  away and not exposed as a framework level.
* **PDF structure (VERIFIED, Title 1)**: the PDF begins with ``TITLE 1 -
  CODE OF CIVIL PROCEDURE`` followed by ``CHAPTER 1 - GENERAL PROVISIONS ...``
  then the sections. Chapter markers are ``CHAPTER {n} - {name}``. A section
  line is ``{T-C-S}.  {Catchline}.`` (e.g. ``1-1-101.  Provisions to be
  liberally construed.``) followed by the body; the next ``T-C-S.`` line
  starts the next section.
* **Section format**: full citation ``T-C-S`` (e.g. ``1-1-101``) with
  decimal sections (e.g. ``1-1-123.1`` through ``1-1-123.5``). The
  citation is always used as ``SectionRef.identifier``.
* **Repealed/renumbered (VERIFIED)**: a repealed or renumbered section's
  catchline IS the note, e.g. ``1-1-110.  Repealed by Laws 1986, ch. 24,
  § 2.`` or ``1-12-502.  Renumbered by Laws 1979, ch. 142, § 3.``, with an
  empty body. Following the Nebraska/North Carolina convention, the note
  becomes the ``heading`` and ``text`` is empty.
* **Error boundary (VERIFIED)**: nonexistent title numbers return the HTML
  SPA shell (detectable via the ``%PDF`` magic check); a nonexistent
  section is absent from the PDF body. The PDF self-identifies its title
  (e.g. ``TITLE 1 - ...``), so a wrong title's PDF is detectable.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/wyoming.md``): only Titles 1, 31, 97, 99 (and trimmed
page-range slices of 1 and 31) were sampled; per-title PDF uniformity is
otherwise UNVERIFIED. Lettered chapters/sections were not observed in the
sampled titles; the citation regex accepts an optional trailing letter per
part defensively (no false positives observed). Per-title PDFs are up to
~3 MB, so each retrieval re-fetches and re-extracts the whole title (P2
performance limitation; no caching in the framework).
"""

from __future__ import annotations

import re
import urllib.error
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_bytes
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


class WyomingAdapter(BaseStateAdapter):
    """Concrete state adapter for the Wyoming Statutes at wyoleg.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The Wyoming Statutes are a
    uniform ``Title -> Chapter -> [Article] -> Section`` hierarchy; the
    Article grouping is folded away (not exposed as a framework level).
    ``TitleRef`` / ``ChapterRef`` identifiers are the title/chapter numbers;
    ``SectionRef.identifier`` is always the full ``T-C-S`` citation. See the
    module docstring.
    """

    BASE_URL = "https://wyoleg.gov"
    STATUTES_PATH = "/statutes/compress"
    DEFAULT_TIMEOUT_SECONDS = 60

    # The official per-title PDF URL pattern. The title number is zero-padded
    # to two digits (e.g. '01', '97', '99').
    _TITLE_PDF_RE = re.compile(r"title(\d{2})\.pdf$")

    # The self-identifying title header at the top of a title PDF, e.g.
    # 'TITLE 1 - CODE OF CIVIL PROCEDURE'. group(1) is the title number.
    _TITLE_HEADER = re.compile(
        r"^\s*TITLE\s+(\d+)+\s*-\s*(.+?)\s*$"
    )

    # A chapter marker, e.g. 'CHAPTER 1 - GENERAL PROVISIONS AS TO CIVIL
    # ACTIONS'. group(1) is the chapter number (numeric, with an optional
    # trailing letter accepted defensively).
    _CHAPTER_MARKER = re.compile(
        r"^CHAPTER\s+([0-9]+[A-Z]?)\s*-\s*(.*?)\s*$"
    )

    # A section citation line, e.g. '1-1-101.  Provisions to be liberally
    # construed.' or '1-1-123.1.  ...'. The citation is 'T-C-S' with an
    # optional trailing letter per part and an optional decimal section
    # suffix. group(1) is the full citation.
    _SECTION_START = re.compile(
        r"^([0-9]+[A-Z]?-[0-9]+[A-Z]?-[0-9]+[A-Z]?(?:\.[0-9]+)*)\.\s"
    )

    def __init__(self) -> None:
        """Create the adapter with an empty per-instance discovery cache.

        Title discovery (probing ``title{NN:02d}.pdf`` over the bounded
        range 00-99) and the extracted title PDF text are cached per adapter
        instance to avoid re-fetching the same large PDFs. This is
        instance-local state (each registry owns its own constructed
        adapters), not global mutable state, and is consistent with how the
        other PDF-family adapters are long-lived, single-construction objects.
        """
        self._title_cache: dict[str, str] = {}
        self._title_list_cache: tuple[TocNode, ...] | None = None

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Wyoming."""
        return "WY"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Wyoming."""
        return "Wyoming"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _title_pdf_url(self, title: str) -> str:
        """Build the official per-title PDF URL for a title number."""
        return f"{self.BASE_URL}{self.STATUTES_PATH}/title{int(title):02d}.pdf"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Wyoming URL needed to retrieve ``ref``.

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
                f"WyomingAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Title PDF retrieval
    # ------------------------------------------------------------

    def _fetch_title_text(self, title_ref: TitleRef) -> str:
        """Fetch the title PDF and extract its text, cached per instance.

        If the title number is present in the per-instance cache the cached
        text is returned without a network call. Otherwise the title PDF is
        fetched with :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes`,
        its ``%PDF`` magic bytes verified (an HTML shell means the title does
        not exist), and its text extracted.

        Args:
            title_ref: The title to fetch.

        Returns:
            The extracted text of the title PDF.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be reached or
                extracted.
            RefNotFoundError: If the title PDF is not actually a PDF (the
                site returned an HTML page, meaning the title does not
                exist).
        """
        cached = self._title_cache.get(title_ref.identifier)
        if cached is not None:
            return cached

        url = self._title_pdf_url(title_ref.identifier)
        try:
            data = fetch_bytes(
                url, what="Wyoming Statutes title PDF", timeout=self.DEFAULT_TIMEOUT_SECONDS
            )
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the Wyoming title PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the Wyoming title PDF at {url!r}: the "
                "site returned a non-PDF page (the title does not resolve)."
            )

        text = extract_pdf_text(data)
        self._title_cache[title_ref.identifier] = text
        return text

    @staticmethod
    def _title_identity(text: str) -> str | None:
        """Return the title number the PDF text self-identifies as, or None
        if it cannot be determined."""
        for line in text.splitlines():
            m = WyomingAdapter._TITLE_HEADER.match(line.strip())
            if m is not None:
                return m.group(1)
        return None

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def _probe_title_exists(self, title_number: int) -> bool:
        """Return True if ``title{NN:02d}.pdf`` is a real PDF.

        Uses a HEAD request to check the ``Content-Type``: valid titles
        return ``application/pdf``; nonexistent titles return the HTML SPA
        shell (``text/html``).

        Args:
            title_number: The title number (0-99) to probe.

        Returns:
            True if the title exists (the PDF is served), False otherwise.
        """
        url = self._title_pdf_url(str(title_number))
        import urllib.request

        request = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                content_type = response.headers.get("Content-Type", "")
                return content_type.startswith("application/pdf")
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Wyoming Statutes.

        Discovers titles dynamically by probing the deterministic official
        per-title PDF pattern over the bounded range 00-99 (the source
        provides no static title index). Each valid title's name is read
        from the PDF's own ``TITLE {n} - {name}`` header. The result is
        cached per adapter instance.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the zero-padded title number (e.g. ``"1"``,
            ``"97"``, ``"99"``).

        Raises:
            AdapterUnavailableError: If none of the probed titles could be
                fetched/parsed (the source is unreachable or returned no
                usable title PDFs).
        """
        if self._title_list_cache is not None:
            return self._title_list_cache

        titles: list[TocNode] = []
        for number in range(1, 100):
            if not self._probe_title_exists(number):
                continue
            identifier = str(number)
            title_ref = TitleRef(state_code=self.state_code, identifier=identifier)
            text = self._fetch_title_text(title_ref)
            name = self._title_name(text, identifier)
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=title_ref,
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                "Probed the Wyoming title PDF range but found no valid "
                "titles; the site's structure may have changed."
            )

        self._title_list_cache = tuple(titles)
        return self._title_list_cache

    @classmethod
    def _title_name(cls, text: str, identifier: str) -> str:
        """Extract the human-facing title name from the PDF's ``TITLE``
        header, falling back to a descriptive ``Title {n}`` label."""
        for line in text.splitlines():
            m = cls._TITLE_HEADER.match(line.strip())
            if m is not None:
                name = " ".join(m.group(2).split())
                if name:
                    return name
        return f"Title {identifier}"

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title PDF.

        Chapters are parsed from the ``CHAPTER {n} - {name}`` markers in the
        title PDF. The Article grouping (intermediate between Chapter and
        Section) is not exposed as a framework level.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"1"``).

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted, or if no usable chapter markers could be parsed.
            RefNotFoundError: If the title PDF is not a PDF (the title does
                not resolve).
        """
        text = self._fetch_title_text(title_ref)
        chapters: dict[str, str] = {}
        for line in text.splitlines():
            m = self._CHAPTER_MARKER.match(line.strip())
            if m is not None:
                chapters.setdefault(m.group(1), m.group(2).strip())

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched the Wyoming title PDF for title "
                f"{title_ref.identifier!r} but found no usable chapter "
                "markers in it; the site's structure may have changed."
            )

        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=num,
                name=name or f"Chapter {num}",
                ref=ChapterRef(title=title_ref, identifier=num),
            )
            for num, name in sorted(
                chapters.items(),
                key=lambda kv: (self._num_key(kv[0]), kv[0]),
            )
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the title PDF.

        Sections are the ``T-C-S.`` citation lines in the title PDF whose
        citation's chapter component matches ``chapter_ref``. ``SectionRef
        .identifier`` is always the full Wyoming citation.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full citation (e.g. ``"1-1-101"``).

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted, or if no usable section citations could be parsed
                under the chapter.
            RefNotFoundError: If the title PDF is not a PDF (the title does
                not resolve).
        """
        text = self._fetch_title_text(chapter_ref.title)
        chapter = chapter_ref.identifier
        sections = []
        for line in text.splitlines():
            m = self._SECTION_START.match(line.strip())
            if m is None:
                continue
            citation = m.group(1)
            parts = citation.split("-")
            if len(parts) < 3 or parts[1] != chapter:
                continue
            catchline = " ".join(line.strip()[m.end():].split())
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=citation,
                    name=catchline or citation,
                    ref=SectionRef(chapter=chapter_ref, identifier=citation),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched the Wyoming title PDF for title "
                f"{chapter_ref.title.identifier!r} but found no usable "
                f"section citations under chapter {chapter!r}; the chapter "
                "either lists no sections or the site's structure has "
                "changed."
            )

        return tuple(sections)

    @staticmethod
    def _num_key(identifier: str) -> tuple[int, str]:
        """Sort key for Wyoming chapter identifiers: the integer leading
        part first, then the full identifier for a stable tie-break."""
        m = re.match(r"(\d+)", identifier)
        return (int(m.group(1)) if m else 0, identifier)

    # ------------------------------------------------------------
    # Section parsing
    # ------------------------------------------------------------

    @classmethod
    def _extract_section(
        cls, text: str, citation: str
    ) -> list[str] | None:
        """Locate the body occurrence of ``citation`` in ``text``.

        Returns the section's lines (from the citation line up to but not
        including the next section citation line), or ``None`` if the
        citation does not appear at a line start. ``TITLE``/``CHAPTER``/
        ``ARTICLE`` header lines inside the section span are ignored by the
        caller; the boundary is strictly the next ``T-C-S.`` line.
        """
        lines = text.splitlines()
        pat = re.compile(rf"^{re.escape(citation)}\.\s")
        start = None
        for i, l in enumerate(lines):
            if pat.match(l.strip()):
                start = i
                break
        if start is None:
            return None
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if cls._SECTION_START.match(lines[j].strip()):
                end = j
                break
        return lines[start:end]

    @classmethod
    def _parse_section(cls, text: str, citation: str) -> ParsedDocument:
        """Parse one Wyoming section from an extracted title PDF.

        Args:
            text: The concatenated extracted text of a title PDF.
            citation: The requested ``SectionRef.identifier`` (full
                citation, e.g. ``"1-1-101"``).

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"Wyo. Stat. {citation}"``, ``heading`` = the catchline (or
            the repeal/renumber note for repealed/renumbered sections),
            ``text`` = the body, and ``amendment_notes`` = None.

        Raises:
            RefNotFoundError: If the citation does not appear at a line
                start in the body.
            NormalizationError: If the section was located but the text is
                malformed (empty body and no heading).
        """
        chunk = cls._extract_section(text, citation)
        if chunk is None:
            raise RefNotFoundError(
                f"Could not find section {citation!r} in the Wyoming title "
                "PDF."
            )

        citation_match = cls._SECTION_START.match(chunk[0].strip())
        if citation_match is None:
            raise NormalizationError(
                "The extracted Wyoming section text contained no citation "
                "line; the title PDF may be malformed."
            )
        found_citation = citation_match.group(1)
        if found_citation != citation:
            raise RefMismatchError(
                f"Requested section {citation!r} does not match the "
                f"citation found in the extracted PDF: {found_citation!r}."
            )

        # The catchline runs from after the citation to the first line that
        # ends with a period. Wrapped catchlines span multiple lines.
        after_citation = chunk[0][citation_match.end():].strip()
        catchline_parts = [after_citation]
        for line in chunk[1:]:
            stripped = line.strip()
            if not stripped:
                break
            catchline_parts.append(stripped)
            if stripped.rstrip().endswith("."):
                break
        catchline = " ".join(catchline_parts)

        # Remaining lines are the body (until the section boundary, which
        # _extract_section already cut off). TITLE/CHAPTER/ARTICLE headers
        # are dropped.
        body_lines = []
        for line in chunk[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^(TITLE|CHAPTER|ARTICLE)\s+\d+", stripped):
                continue
            body_lines.append(stripped)
        body = "\n".join(body_lines).strip()

        # Repealed/renumbered sections carry the note as the catchline with
        # an empty body (the Nebraska/North Carolina convention).
        repeal = re.match(
            r"^(Repealed|Renumbered)\b", catchline, re.IGNORECASE
        )
        if repeal is not None:
            heading = catchline
            text_body = ""
        else:
            heading = catchline or citation
            text_body = body

        return ParsedDocument(
            raw_citation=f"Wyo. Stat. {citation}",
            heading=heading,
            text=text_body,
            amendment_notes=None,
            source_url="",
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Wyoming.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` must appear verbatim
        within ``parsed.raw_citation``.

        ``status`` is always ``UNKNOWN``: the Wyoming Statutes signal
        repealed and renumbered sections only as prose in the catchline
        (``Repealed by ...``, ``Renumbered by ...``) with no substantive
        body -- per the framework rule (same decision as
        Nebraska/Massachusetts/Kentucky/New Mexico/Oklahoma), a prose-only
        signal is not a structural marker, so the status is not inferred
        from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Wyoming ref
                (``ref.state_code != "WY"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"WyomingAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Wyoming Statutes section, end to end:
        fetch the title PDF bytes with
        :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes` -> verify
        it is a PDF -> extract text with
        :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text` ->
        verify the PDF self-identifies the requested title -> locate and
        parse the requested section -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a Wyoming ref
                (``ref.state_code == "WY"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be reached or
                extracted.
            RefNotFoundError: If the title PDF is not a PDF (the title does
                not resolve), or the section's citation is absent from the
                title PDF body.
            RefMismatchError: If the PDF self-identifies a different title
                than ``ref``, or the section's own declared citation
                disagrees with ``ref``.
            NormalizationError: If the section was located but the text is
                malformed.
        """
        title_ref = ref.chapter.title
        text = self._fetch_title_text(title_ref)

        # Cross-check the PDF's self-identified title against the requested
        # title (a wrong-title PDF must not be accepted).
        pdf_title = self._title_identity(text)
        if pdf_title is not None and pdf_title != title_ref.identifier:
            raise RefMismatchError(
                f"Requested title {title_ref.identifier!r} but the Wyoming "
                f"title PDF self-identifies as title {pdf_title!r}; the "
                "retrieved document is not the requested title."
            )

        parsed = self._parse_section(text, ref.identifier)
        parsed = parsed.model_copy(update={"source_url": self.build_url(ref)})
        return self.normalize(parsed, ref)