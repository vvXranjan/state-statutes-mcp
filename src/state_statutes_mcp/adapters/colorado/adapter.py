"""ColoradoAdapter: the Colorado-specific concrete state adapter.

Source: the official Colorado Revised Statutes (CRS) per-title PDFs at
``https://content.leg.colorado.gov/sites/default/files/images/olls/
crs2024-title-{NN}.pdf``, published by the Colorado Office of Legislative
Legal Services (OLLS). Each title's full text is served as one PDF. This is
the framework's sixth PDF-consuming adapter and reuses the same
``fetch_bytes`` -> ``extract_pdf_text`` pipeline unchanged.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/colorado.md``;
all structures verified against real archived official captures of the
official host, captured via the Wayback Machine on Aug 24 2026 from this
environment — the live host returns an AWS WAF HTTP 403 to this environment
for both valid and invalid title URLs, so the archived captures are the
authoritative verified source; see the research document):

* Official per-title PDFs: ``https://content.leg.colorado.gov/sites/default/
  files/images/olls/crs2024-title-{NN}.pdf`` (two-digit title number).
  Valid titles return ``application/pdf``; the live host is WAF-gated from
  this environment, so the exact non-existent-title HTTP response is
  UNVERIFIED (archived evidence: a nonexistent title URL is never captured;
  the live WAF returns an identical 403 for valid and invalid URLs).
* **Valid title set (verified from archived captures)**: Titles 01-42, 97
  (a special constitution-related volume), and 99 are the published CRS
  titles; the per-title PDFs for titles 1, 8, and 42 were verified.
* **Hierarchy**: ``Title -> Article -> Part -> Section``. The section
  citation ``T-A-S`` encodes the Article as its middle component (e.g.
  ``42-1-102`` = Title 42, Article 1, Section 102). Part is a structural
  grouping that is NOT encoded in the citation, so it is folded away.
  Articles may be decimal (e.g. ``1-1.5-101`` = Article 1.5), which is
  preserved in the ChapterRef identifier.
* **PDF structure (VERIFIED, Titles 1 and 42)**:
  * A title PDF begins with ``Colorado Revised Statutes 2024`` then
    ``TITLE {NN}`` then the title name, followed by an optional title-level
    ``Editor's note:`` / ``Cross references:`` block.
  * ``ARTICLE {n}`` / ``PART {n}`` markers are structural headers (not
    sections) and are skipped by the section parser.
  * A section line is ``{T-A-S}.  {Catchline}.`` (e.g. ``42-1-101.  Short
    title.``) followed by the body; the next section citation starts the
    next section.
  * Decimal sections exist (e.g. ``42-1-218.5``), decimal articles exist
    (e.g. ``1-1.5-101``), and range-repeal lines exist (e.g.
    ``1-1-401 to 1-1-403. (Repealed)``).
  * ``Source: ...`` and ``Editor's note: ...`` lines carry the legislative
    history and are captured as ``amendment_notes``.
  * Repealed sections carry ``(Repealed)`` in the catchline (e.g.
    ``1-1-112.  Powers and duties of election commission. (Repealed)``) with
    a Source/Editor's-note block; following the Nebraska convention, the
    repeal note is reflected in the heading and the body is empty.
  * **Merged page footer (VERIFIED)**: every page ends with
    ``Colorado Revised Statutes 2024 Page {n} of {m} Uncertified Printout``
    which is CONCATENATED onto the start of the following text line (there
    is no newline), so the parser must strip this prefix from any line that
    begins with it.
* **Error boundary**: a non-PDF response (WAF HTML shell, or an archived
  non-existent title) is detected by the ``%PDF`` magic check and mapped to
  ``RefNotFoundError``. The PDF self-identifies its title (``TITLE {NN}``
  line), enabling a wrong-title cross-check (``RefMismatchError``).

**UNVERIFIED / accepted limitations** (documented in
``docs/research/colorado.md``): the live invalid-title HTTP behavior is
unobservable behind the AWS WAF from this environment (identical 403 for
valid and invalid URLs). Only Titles 1, 8, 42 (and trimmed page-range
slices) were sampled; per-title PDF uniformity is otherwise UNVERIFIED.
Per-title PDFs are large (up to ~4.7 MB / 834 pages), so each retrieval
re-fetches and re-extracts the whole title (P2 performance limitation; no
caching in the framework).
"""

from __future__ import annotations

import re
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


class ColoradoAdapter(BaseStateAdapter):
    """Concrete state adapter for the Colorado Revised Statutes at
    content.leg.colorado.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The CRS is a ``Title ->
    Article -> Part -> Section`` hierarchy; Article is exposed as
    ``ChapterRef`` (decimal articles preserved, e.g. ``1.5``), Part is folded
    away, and ``SectionRef.identifier`` is always the full ``T-A-S``
    citation. See the module docstring.
    """

    BASE_URL = "https://content.leg.colorado.gov"
    PDFS_PATH = "/sites/default/files/images/olls"
    DEFAULT_TIMEOUT_SECONDS = 60

    # The official per-title PDF URL pattern. The title number is zero-padded
    # to two digits (e.g. '01', '42').
    def _title_pdf_url(self, title: str) -> str:
        return f"{self.BASE_URL}{self.PDFS_PATH}/crs2024-title-{int(title):02d}.pdf"

    # The self-identifying title line in a title PDF, e.g. 'TITLE 42'.
    # group(1) is the title number (possibly '1'..'42','97','99').
    _TITLE_HEADER = re.compile(r"^\s*TITLE\s+(\d+)\s*$")

    # A structural ARTICLE marker, e.g. 'ARTICLE 1' or 'ARTICLE 1.5'. Skipped
    # by the section parser (not a section).
    _ARTICLE_MARKER = re.compile(r"^ARTICLE\s+\d+(?:\.\d+)*\s*$")

    # A structural PART marker, e.g. 'PART 1'. Skipped by the section parser.
    _PART_MARKER = re.compile(r"^PART\s+\d+\s*$")

    # A section citation line. Colorado section citations are 'T-A-S' where
    # T is the title, A the article (integer or decimal, e.g. '1' or '1.5'),
    # and S the section (integer or decimal, e.g. '101' or '218.5'). A
    # range-repeal line uses 'T-A-S1 to T-A-S2' (e.g. '1-1-401 to 1-1-403').
    # This matches both forms.
    _SECTION_START = re.compile(
        r"^([0-9]+-[0-9]+(?:\.[0-9]+)?-[0-9]+(?:\.[0-9]+)?)"
        r"(?:\s+to\s+[0-9]+-[0-9]+(?:\.[0-9]+)?-[0-9]+(?:\.[0-9]+)?)?"
        r"\.\s"
    )

    # The merged page footer that is concatenated onto the start of the next
    # text line: 'Colorado Revised Statutes 2024 Page {n} of {m} Uncertified
    # Printout{content}'. Stripped from any line that begins with it.
    _FOOTER = re.compile(
        r"^Colorado Revised Statutes 2024 Page \d+ of\s+\d+ Uncertified Printout"
    )

    # The legislative history line.
    _SOURCE = re.compile(r"^Source:\s*")

    # The editor's note line.
    _EDITORS_NOTE = re.compile(r"^Editor's note:\s*")

    # A bare repealed/renumbered note on its own line (e.g. a wrapped
    # catchline's '(Repealed)' marker on the line following the catchline).
    _REPEAL_NOTE_LINE = re.compile(
        r"^\((?:Repealed|Renumbered)\)\s*$", re.IGNORECASE
    )

    # A repealed/renumbered section's catchline ends with '(Repealed)' or
    # '(Renumbered)'.
    _REPEALED = re.compile(r"\((?:Repealed|Renumbered)\)\s*$", re.IGNORECASE)

    def __init__(self) -> None:
        """Create the adapter with an empty per-instance title cache.

        The per-title PDFs are large (up to ~4.7 MB), so extracted title text
        is cached per adapter instance to avoid re-fetching the same title.
        This is instance-local state (each registry owns its own constructed
        adapters), not global mutable state.
        """
        self._title_cache: dict[str, str] = {}

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Colorado."""
        return "CO"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Colorado."""
        return "Colorado"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Colorado URL needed to retrieve ``ref``.

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
                f"ColoradoAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Title PDF retrieval
    # ------------------------------------------------------------

    def _fetch_title_text(self, title_ref: TitleRef) -> str:
        """Fetch the title PDF and extract its text, cached per instance.

        Args:
            title_ref: The title to fetch.

        Returns:
            The extracted text of the title PDF.

        Raises:
            AdapterUnavailableError: If the title PDF cannot be reached or
                extracted.
            RefNotFoundError: If the title PDF is not actually a PDF (the
                site returned a non-PDF page, meaning the title does not
                resolve).
        """
        cached = self._title_cache.get(title_ref.identifier)
        if cached is not None:
            return cached

        url = self._title_pdf_url(title_ref.identifier)
        try:
            data = fetch_bytes(
                url, what="Colorado Statutes title PDF", timeout=self.DEFAULT_TIMEOUT_SECONDS
            )
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the Colorado title PDF at {url!r}: {exc}"
            ) from exc

        if not data.startswith(b"%PDF"):
            raise RefNotFoundError(
                f"Could not retrieve the Colorado title PDF at {url!r}: the "
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
            m = ColoradoAdapter._TITLE_HEADER.match(line.strip())
            if m is not None:
                return m.group(1)
        return None

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def _probe_title_exists(self, title_number: int) -> bool:
        """Return True if ``crs2024-title-{NN:02d}.pdf`` is a real PDF.

        Uses a HEAD request to check the ``Content-Type``: valid titles
        return ``application/pdf``; non-existent titles (or a WAF-gated
        response) return HTML.

        Args:
            title_number: The title number (1-99) to probe.

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
        """Enumerate every title of the Colorado Revised Statutes.

        Discovers titles dynamically by probing the deterministic official
        per-title PDF pattern over the bounded range 01-99. Each valid
        title's name is read from the PDF's own ``TITLE {n}`` header followed
        by the title name line. The result is built once per adapter
        instance (subsequent calls reuse the cached title texts).

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric order.
            Each node's ``ref`` is a :class:`TitleRef` whose ``identifier``
            is the zero-padded title number (e.g. ``"1"``, ``"42"``).

        Raises:
            AdapterUnavailableError: If none of the probed titles could be
                fetched/parsed (the source is unreachable or returned no
                usable title PDFs).
        """
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
                "Probed the Colorado title PDF range but found no valid "
                "titles; the site's structure may have changed."
            )

        return tuple(titles)

    @classmethod
    def _title_name(cls, text: str, identifier: str) -> str:
        """Extract the title name from the PDF's ``TITLE`` header block.

        The PDF presents the title identity as ``TITLE {n}`` on one line
        followed by the title name on the next non-blank line. Returns a
        descriptive ``Title {n}`` fallback if the name cannot be read.
        """
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if cls._TITLE_HEADER.match(line.strip()):
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = " ".join(lines[j].split())
                    if candidate:
                        return candidate
                break
        return f"Title {identifier}"

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every article under ``title_ref`` from the title PDF.

        Colorado's Article level is exposed as ``ChapterRef`` (the framework
        has no Article level). Articles are read from the ``ARTICLE {n}``
        markers in the title PDF. Decimal articles (e.g. ``1.5``) are
        preserved.

        Args:
            title_ref: The parent title to enumerate articles under.

        Returns:
            A sequence of :class:`TocNode`, one per article, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the article number (e.g. ``"1"``, ``"1.5"``).

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted, or if no usable article markers could be parsed.
            RefNotFoundError: If the title PDF is not a PDF (the title does
                not resolve).
        """
        text = self._fetch_title_text(title_ref)
        articles: list[tuple[str, str]] = []
        seen: set[str] = set()
        for line in text.splitlines():
            stripped = line.strip()
            m = self._ARTICLE_MARKER.match(stripped)
            if m is None:
                continue
            number = stripped.split()[1]
            if number in seen:
                continue
            seen.add(number)
            articles.append((number, f"Article {number}"))

        if not articles:
            raise AdapterUnavailableError(
                f"Fetched the Colorado title PDF for title "
                f"{title_ref.identifier!r} but found no usable article "
                "markers in it; the site's structure may have changed."
            )

        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=num,
                name=name,
                ref=ChapterRef(title=title_ref, identifier=num),
            )
            for num, name in sorted(
                articles, key=lambda kv: (self._num_key(kv[0]), kv[0])
            )
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the title PDF.

        Sections are the ``T-A-S.`` citation lines in the title PDF whose
        citation's article component matches ``chapter_ref``. ``SectionRef
        .identifier`` is always the full Colorado citation.

        Args:
            chapter_ref: The parent article to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full citation (e.g. ``"42-1-101"``).

        Raises:
            AdapterUnavailableError: If the title PDF cannot be fetched or
                extracted, or if no usable section citations could be parsed
                under the article.
            RefNotFoundError: If the title PDF is not a PDF (the title does
                not resolve).
        """
        text = self._fetch_title_text(chapter_ref.title)
        article = chapter_ref.identifier
        sections = []
        for line in text.splitlines():
            stripped = self._strip_footer(line.strip())
            m = self._SECTION_START.match(stripped)
            if m is None:
                continue
            citation = m.group(1)
            parts = citation.split("-")
            if len(parts) < 3 or parts[1] != article:
                continue
            # A range-repeal line (e.g. '1-1-401 to 1-1-403. (Repealed)') is a
            # structural marker for a whole repealed range, not a single
            # retrievable section: do not expose it as an ordinary section
            # (there is no individual section to retrieve for it).
            if " to " in m.group(0):
                continue
            catchline = " ".join(stripped[m.end():].split())
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
                f"Fetched the Colorado title PDF for title "
                f"{chapter_ref.title.identifier!r} but found no usable "
                f"section citations under article {article!r}; the article "
                "either lists no sections or the site's structure has "
                "changed."
            )

        return tuple(sections)

    @staticmethod
    def _num_key(identifier: str) -> tuple[float, str]:
        """Sort key for Colorado article identifiers (integers or decimals)."""
        try:
            return (float(identifier), identifier)
        except ValueError:
            return (float("inf"), identifier)

    @classmethod
    def _strip_footer(cls, line: str) -> str:
        """Remove a merged Colorado page-footer prefix from ``line`` if
        present."""
        return cls._FOOTER.sub("", line)

    @staticmethod
    def _catchline_ends(text: str) -> bool:
        """Return True if ``text`` is a complete catchline fragment (i.e. it
        ends with a sentence period or a ``(Repealed)`` / ``(Renumbered)``
        note), so no further lines should be appended to the catchline."""
        stripped = text.strip()
        return stripped.endswith(".") or bool(
            re.search(r"\.\s*\([Rr]e(?:pealed|numbered)\)\s*$", text)
        ) or bool(
            re.match(r"\([Rr]e(?:pealed|numbered)\)\s*$", stripped)
        )

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
        citation does not appear at a line start. ``TITLE``/``ARTICLE``/
        ``PART`` header lines inside the section span are ignored by the
        caller; the boundary is strictly the next ``T-A-S.`` line.

        Args:
            text: The extracted title PDF text.
            citation: The requested full citation (e.g. ``"42-1-101"``).

        Returns:
            The section's lines, or ``None`` if not found.
        """
        lines = text.splitlines()
        pat = re.compile(rf"^{re.escape(citation)}\.\s")
        start = None
        for i, l in enumerate(lines):
            if pat.match(cls._strip_footer(l.strip())):
                start = i
                break
        if start is None:
            return None
        end = len(lines)
        for j in range(start + 1, len(lines)):
            stripped = cls._strip_footer(lines[j].strip())
            if cls._SECTION_START.match(stripped):
                end = j
                break
        return lines[start:end]

    @classmethod
    def _parse_section(cls, text: str, citation: str) -> ParsedDocument:
        """Parse one Colorado section from an extracted title PDF.

        Args:
            text: The concatenated extracted text of a title PDF.
            citation: The requested ``SectionRef.identifier`` (full
                citation, e.g. ``"42-1-101"``).

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"Colo. Rev. Stat. {citation}"``, ``heading`` = the catchline
            (including a ``(Repealed)`` note), ``text`` = the body (with
            page footers stripped and Source/Editor's-note history removed),
            and ``amendment_notes`` = the concatenated Source/Editor's-note
            text.

        Raises:
            RefNotFoundError: If the citation does not appear at a line
                start in the body.
            NormalizationError: If the section was located but the text is
                malformed (no citation line).
            RefMismatchError: If the found citation disagrees with the
                requested citation.
        """
        chunk = cls._extract_section(text, citation)
        if chunk is None:
            raise RefNotFoundError(
                f"Could not find section {citation!r} in the Colorado title "
                "PDF."
            )

        first = cls._strip_footer(chunk[0].strip())
        citation_match = cls._SECTION_START.match(first)
        if citation_match is None:
            raise NormalizationError(
                "The extracted Colorado section text contained no citation "
                "line; the title PDF may be malformed."
            )
        found_citation = citation_match.group(1)
        if found_citation != citation:
            raise RefMismatchError(
                f"Requested section {citation!r} does not match the "
                f"citation found in the extracted PDF: {found_citation!r}."
            )

        # The catchline runs from after the citation to the first sentence
        # boundary. Colorado catchlines are followed (sometimes on the same
        # line) by the body, which begins with a subsection marker such as
        # '(1)', '(a)', a capital letter, or a digit. A repealed/renumbered
        # catchline ends with '.(Repealed)' / '.(Renumbered)' and is kept
        # whole, and a bare '(Repealed)' / '(Renumbered)' marker on the line
        # immediately after a wrapped catchline is folded into it. The
        # catchline may span multiple physical lines (wrapped).
        after_citation = first[citation_match.end():].strip()
        catchline_parts = [after_citation]
        catchline_terminated = cls._catchline_ends(after_citation)
        for line in chunk[1:]:
            stripped = cls._strip_footer(line.strip())
            if not stripped:
                break
            # A bare '(Repealed)' / '(Renumbered)' marker on its own line
            # continues the catchline even when the preceding line already
            # ended with a period (a wrapped catchline, e.g. '42-1-223.').
            if cls._REPEAL_NOTE_LINE.match(stripped):
                catchline_parts.append(stripped)
                break
            if catchline_terminated:
                break
            catchline_parts.append(stripped)
            catchline_terminated = cls._catchline_ends(stripped)
        raw_catchline = " ".join(catchline_parts)

        # Split the catchline from the body that follows on the same line.
        # The catchline ends at the first '. ' boundary that is followed by a
        # body marker (digit, '(', or capital letter) -- unless the '. '
        # introduces the '(Repealed)' / '(Renumbered)' note (part of the
        # catchline).
        catchline = raw_catchline
        body_prefix = ""
        for m in re.finditer(r"\.\s+(?=[A-Z0-9(])", raw_catchline):
            tail = raw_catchline[m.end():]
            if re.match(r"\([Rr]e(?:pealed|numbered)\)", tail):
                continue
            catchline = raw_catchline[: m.end()]
            body_prefix = raw_catchline[m.end():]
            break

        # Remaining lines are the body (until the section boundary, which
        # _extract_section already cut off). TITLE/ARTICLE/PART headers are
        # dropped; page footers are stripped; Source/Editor's-note lines are
        # collected into amendment_notes.
        body_lines: list[str] = []
        if body_prefix:
            body_lines.append(body_prefix)
        notes: list[str] = []
        in_notes = False
        for line in chunk[1:]:
            stripped = cls._strip_footer(line.strip())
            if not stripped:
                continue
            if cls._REPEAL_NOTE_LINE.match(stripped):
                continue
            if cls._SOURCE.match(stripped) or cls._EDITORS_NOTE.match(stripped):
                in_notes = True
            if cls._ARTICLE_MARKER.match(stripped) or cls._PART_MARKER.match(stripped):
                in_notes = False
                continue
            if in_notes:
                notes.append(stripped)
            else:
                body_lines.append(stripped)
        body = "\n".join(body_lines).strip()
        amendment_notes = " ".join(notes).strip() if notes else None

        catchline = catchline.strip()

        # Repealed sections carry '(Repealed)' in the catchline and a
        # Source/Editor's-note block (the Nebraska convention). The repeal
        # note is kept in the heading; the body is empty because a repealed
        # section has no substantive text.
        if cls._REPEALED.search(catchline):
            heading = catchline
            text_body = ""
        else:
            heading = catchline or citation
            text_body = body

        return ParsedDocument(
            raw_citation=f"Colo. Rev. Stat. {citation}",
            heading=heading,
            text=text_body,
            amendment_notes=amendment_notes,
            source_url="",
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Colorado.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` must appear verbatim
        within ``parsed.raw_citation``.

        ``status`` is always ``UNKNOWN``: the Colorado Statutes signal
        repealed sections only as prose in the catchline (``(Repealed)``)
        with no structural status field -- per the framework rule, a
        prose-only signal is not a structural marker, so the status is not
        inferred from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Colorado ref
                (``ref.state_code != "CO"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"ColoradoAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Colorado Revised Statutes section, end
        to end: fetch the title PDF bytes with
        :func:`~state_statutes_mcp.adapters._fetch.fetch_bytes` -> verify it
        is a PDF -> extract text with
        :func:`~state_statutes_mcp.adapters._pdftext.extract_pdf_text` ->
        verify the PDF self-identifies the requested title -> locate and
        parse the requested section -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a Colorado ref
                (``ref.state_code == "CO"``); enforced by :meth:`normalize`,
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
                f"Requested title {title_ref.identifier!r} but the Colorado "
                f"title PDF self-identifies as title {pdf_title!r}; the "
                "retrieved document is not the requested title."
            )

        parsed = self._parse_section(text, ref.identifier)
        parsed = parsed.model_copy(update={"source_url": self.build_url(ref)})
        return self.normalize(parsed, ref)