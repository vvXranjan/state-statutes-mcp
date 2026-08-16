"""NewHampshireAdapter: the New Hampshire-specific concrete state adapter.

Source: the official New Hampshire Revised Statutes Annotated (RSA)
publication at ``https://gc.nh.gov/rsa/html/`` -- anonymous,
server-rendered HTML with no authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/new_hampshire.md``; the official ``gc.nh.gov/rsa/html/``
source was verified independently by the research source of truth for
this batch -- the host could not be independently fetched from this
environment and no Wayback capture was available, so the fixtures used by
the tests are SYNTHETIC and representative, reproducing only the VERIFIED
structures below):

* Base URL ``https://gc.nh.gov`` with the RSA under ``/rsa/html/``.
* Hierarchy Title -> Chapter -> Section. The title index is
  ``/rsa/html/nhtoc.htm``.
* Chapter documents: ``/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm``
  (e.g. ``/rsa/html/xvi/201-a/201-a-mrg.htm``). Source title directories
  use Roman numerals (``xvi`` for Title 16); framework identifiers remain
  Arabic (``"16"``). The chapter URL directory is the chapter identifier
  lower-cased (``201-a``); the lower-casing is INFERENCE from the verified
  lettered example.
* Sections are embedded in their chapter document (chapter-document based
  retrieval), each marked by a heading of the form ``Section {c}:{s}``
  followed by the section's own heading ``{c}:{s} {Caption}.``.
* History: a ``Source.`` line follows the section body (e.g.
  ``Source. 1971, 224:1.``), preserved verbatim as ``amendment_notes``
  and removed from the body.
* Repealed sections and repealed ranges appear inline: a repealed section
  appears in place with its repeal annotation, and a repealed range
  appears as a section whose heading spans the range. These are preserved
  verbatim in the heading/body text; no structural repealed signal is
  defined, so ``status`` stays ``UNKNOWN`` under the framework's
  no-prose-inference rule.
* Lettered chapters are supported (e.g. ``201-A``).
* Citation: ``RSA {chapter}:{section}`` (e.g. ``RSA 201-A:1``);
  ``SectionRef.identifier`` is the full ``{chapter}:{section}`` form.
* Error boundary: the live HTTP 404 behavior is UNVERIFIED (source not
  fetchable from this environment); by project convention HTTP 404 maps to
  ``RefNotFoundError`` and other network failures to
  ``AdapterUnavailableError``. A section that is not present in a fetched
  chapter document raises ``RefNotFoundError`` (adapter-level expected
  behavior based on project convention; live behavior UNVERIFIED).

**UNVERIFIED / accepted limitations** (documented in
``docs/research/new_hampshire.md``): the exact HTML markup of ``nhtoc.htm``
and of the chapter documents beyond the VERIFIED structural elements, and
the exact markup of an inline repealed section/range. None of these block
the implementation below.
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


class NewHampshireAdapter(BaseStateAdapter):
    """Concrete state adapter for the official New Hampshire Revised
    Statutes Annotated publication at gc.nh.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://gc.nh.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title heading on the title index, e.g.
    # '<p><b>TITLE XVI</b> Libraries and Archives</p>'. The identifier is
    # the Roman numeral converted to Arabic; the name is the text after the
    # closing </b>.
    _TITLE_HEADING = re.compile(
        r"<p><b>\s*TITLE\s+([IVXLCDM]+)\s*</b>\s*(.*?)</p>", re.DOTALL
    )

    # A chapter link row on the title index, e.g.
    # '<p><a href="/rsa/html/xvi/201-a/201-a-mrg.htm">CHAPTER 201-A</a>
    # Library Trustees</p>'. Group(1) is the URL directory (lower-cased);
    # group(2) is the chapter identifier as the source names it in the link
    # text (e.g. '201-A'); group(3) is the chapter name.
    _CHAPTER_ROW = re.compile(
        r'<a href="/rsa/html/[ivxlcdm]+/([0-9a-z-]+)/\1-mrg\.htm"[^>]*>\s*'
        r"CHAPTER\s+([0-9A-Z-]+)\s*</a>\s*(.*?)</p>",
        re.DOTALL,
    )

    # A section marker inside a chapter document, e.g.
    # '<p><b>Section 201-A:1</b></p>'. Group(1) is the section citation
    # (e.g. '201-A:1').
    _SECTION_MARKER = re.compile(
        r"<p><b>\s*Section\s+([0-9A-Z]+(?:-[A-Z])?:\d+)\s*</b></p>"
    )

    # A section's own heading inside a chapter document, e.g.
    # '<p><b>201-A:1 Definitions.</b></p>' or, for a repealed range,
    # '<p><b>201-A:3 to 201-A:5 [Repealed.]</b></p>'. Group(1) is the
    # leading citation; group(2) is the rest of the heading text.
    _SECTION_HEADING = re.compile(
        r"<p><b>\s*([0-9A-Z]+(?:-[A-Z])?:\d+)(.*?)</b></p>", re.DOTALL
    )

    # The history line inside a chapter document, e.g.
    # '<p>Source. 1971, 224:1. 1990, 140:2, eff. Jan. 1, 1991.</p>'.
    _SOURCE_LINE = re.compile(r"<p>\s*Source\.(.*?)</p>", re.DOTALL)

    # The Roman numerals this adapter converts between (the source's title
    # directories use Roman numerals; framework identifiers remain Arabic).
    _ROMAN_NUMERALS: tuple[tuple[int, str], ...] = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    _ROMAN_VALUES: dict[str, int] = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
        "C": 100,
        "D": 500,
        "M": 1000,
    }

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for New Hampshire."""
        return "NH"

    @property
    def state_name(self) -> str:
        """Human-facing display name for New Hampshire."""
        return "New Hampshire"

    # ------------------------------------------------------------
    # Roman numeral conversion
    # ------------------------------------------------------------

    @classmethod
    def _arabic_to_roman(cls, number: int) -> str:
        """Convert an Arabic number to a Roman numeral string.

        Used to build the title directory of a chapter URL (e.g. Title 16
        -> ``xvi``). Supports the standard 1-3999 range.

        Args:
            number: The Arabic number to convert.

        Returns:
            The Roman numeral string (lower-case, matching the verified
            chapter URL example ``xvi``).
        """
        if number < 1 or number > 3999:
            raise ValueError(f"Cannot convert {number!r} to a Roman numeral.")
        result = []
        for value, symbol in cls._ROMAN_NUMERALS:
            while number >= value:
                result.append(symbol)
                number -= value
        return "".join(result).lower()

    @classmethod
    def _roman_to_arabic(cls, roman: str) -> int:
        """Convert a Roman numeral string to an Arabic number.

        Used to parse title headings on the title index (e.g. ``XVI`` ->
        16).

        Args:
            roman: The Roman numeral string (upper- or lower-case).

        Returns:
            The Arabic number.
        """
        total = 0
        prev = 0
        for char in reversed(roman.strip().upper()):
            value = cls._ROMAN_VALUES[char]
            if value < prev:
                total -= value
            else:
                total += value
            prev = value
        return total

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official New Hampshire RSA URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/new_hampshire.md):

        * Title: ``https://gc.nh.gov/rsa/html/nhtoc.htm`` -- the title
          index, which lists the titles and their chapter links.
        * Chapter: ``https://gc.nh.gov/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm``
          where ``{roman}`` is the title number in Roman numerals (e.g.
          ``xvi`` for Title 16) and ``{chapter}`` is the chapter identifier
          lower-cased (e.g. ``201-a``).
        * Section: the section's own chapter document -- sections are
          embedded in their chapter document, so the chapter document is
          the closest real resource (the same model
          ``SouthCarolinaAdapter`` uses).

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
            return f"{self.BASE_URL}/rsa/html/nhtoc.htm"
        else:
            raise UnsupportedRefError(
                f"NewHampshireAdapter.build_url does not support refs of "
                f"type {type(ref).__name__!r}."
            )

    def _chapter_url(self, chapter_ref: ChapterRef) -> str:
        """Build a chapter document URL for ``chapter_ref``.

        The URL is ``/rsa/html/{roman}/{dir}/{dir}-mrg.htm`` where
        ``{roman}`` is the parent title's number converted to Roman
        numerals (e.g. ``xvi`` for Title 16) and ``{dir}`` is the chapter
        identifier lower-cased (e.g. ``201-a``).

        Args:
            chapter_ref: The chapter (or section's parent chapter) to
                address.

        Returns:
            The chapter document URL.
        """
        roman = self._arabic_to_roman(int(chapter_ref.title.identifier))
        directory = chapter_ref.identifier.lower()
        return (
            f"{self.BASE_URL}/rsa/html/{roman}/{directory}/{directory}-mrg.htm"
        )

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
        New Hampshire site is UNVERIFIED (source not fetchable from this
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
                does not resolve on the New Hampshire RSA site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the New Hampshire RSA site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _heading_label(cls, identifier: str, heading_text: str) -> str:
        """Derive a human-facing label from a section's heading text.

        The heading text is the citation plus caption (e.g. ``201-A:1
        Definitions.``) or, for a repealed range, the range plus annotation
        (e.g. ``201-A:3 to 201-A:5 [Repealed.]``). The leading citation
        (``identifier``) is stripped when it prefixes the text, so the
        caption/annotation remains; otherwise the text is kept verbatim.

        Args:
            identifier: The section's citation (e.g. ``"201-A:1"``).
            heading_text: The cleaned heading text.

        Returns:
            The label.
        """
        stripped = re.sub(rf"^{re.escape(identifier)}\s*", "", heading_text)
        return " ".join(stripped.split())

    def _title_heading_offsets(self, html: str) -> list[tuple[str, int]]:
        """Return ``(identifier, start_offset)`` for every title heading on
        the title index, in document order, with identifiers converted from
        Roman to Arabic."""
        offsets = []
        for match in self._TITLE_HEADING.finditer(html):
            identifier = str(self._roman_to_arabic(match.group(1)))
            offsets.append((identifier, match.start()))
        return offsets

    def _iter_sections(self, html: str):
        """Yield ``(identifier, name)`` for every section in a chapter
        document, in document order.

        A section runs from its ``Section {c}:{s}`` marker to the next
        marker. The identifier is the marker's citation; the name is derived
        from the section's own heading line.

        Args:
            html: The chapter document HTML.

        Returns:
            A generator of ``(identifier, name)`` pairs.
        """
        markers = list(self._SECTION_MARKER.finditer(html))
        for i, marker in enumerate(markers):
            identifier = marker.group(1)
            start = marker.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(html)
            segment = html[start:end]
            heading = self._SECTION_HEADING.search(segment)
            if heading is None:
                continue
            heading_text = self._clean_inner(heading.group(1) + heading.group(2))
            name = self._heading_label(identifier, heading_text)
            yield identifier, name

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the New Hampshire RSA from the title
        index.

        The title index (``/rsa/html/nhtoc.htm``) lists the titles by
        Roman numeral (e.g. ``TITLE XVI``); framework identifiers remain
        Arabic (e.g. ``"16"``).

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the Arabic title number (e.g. ``"16"``).

        Raises:
            AdapterUnavailableError: If the title index cannot be fetched,
                or if no usable title headings could be parsed from it.
        """
        url = f"{self.BASE_URL}/rsa/html/nhtoc.htm"
        html = self._fetch_html(url, what="New Hampshire title index")

        titles = []
        seen: dict[str, None] = {}
        for roman, raw_name in self._TITLE_HEADING.findall(html):
            identifier = str(self._roman_to_arabic(roman))
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(raw_name).split())
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
                f"Fetched {url!r} but found no usable title headings in it; "
                "the site's structure may have changed."
            )

        return tuple(
            sorted(titles, key=lambda node: int(node.identifier))
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title index.

        The title index (``/rsa/html/nhtoc.htm``) lists the titles and,
        under each title, that title's chapter links. The chapters belonging
        to ``title_ref`` are the chapter rows between ``title_ref``'s
        heading and the next title heading.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"201"``, lettered
            ``"201-A"``).

        Raises:
            RefNotFoundError: If ``title_ref``'s heading is not present on
                the title index (the title does not resolve).
            AdapterUnavailableError: If the title index cannot be fetched
                for any other reason, or if no usable chapter rows could be
                parsed under the title.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="New Hampshire title index")

        offsets = self._title_heading_offsets(html)
        match = None
        for i, (identifier, start) in enumerate(offsets):
            if identifier == title_ref.identifier:
                end = offsets[i + 1][1] if i + 1 < len(offsets) else len(html)
                match = (start, end)
                break
        if match is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the title index lists no title "
                f"{title_ref.identifier!r}; the title does not resolve on "
                "the New Hampshire RSA site."
            )
        start, end = match
        segment = html[start:end]

        chapters = []
        seen: dict[str, None] = {}
        for _directory, identifier, raw_name in self._CHAPTER_ROW.findall(segment):
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(raw_name).split())
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
                f"Fetched {url!r} but found no usable chapter rows under "
                f"title {title_ref.identifier!r}; the title either lists no "
                "chapters or the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        document.

        The chapter document (``/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm``)
        contains all of the chapter's sections, each marked by a
        ``Section {c}:{s}`` heading. The section identifier is the citation
        (e.g. ``"201-A:1"``); the display name is derived from the section's
        own heading line. Repealed sections and repealed ranges appear
        inline and are listed like any other section (their annotation is
        preserved verbatim in the name).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{chapter}:{section}`` citation.

        Raises:
            RefNotFoundError: If the chapter document returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any other reason, or if no usable section
                markers could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="New Hampshire section listing")

        sections = []
        seen: dict[str, None] = {}
        for identifier, name in self._iter_sections(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name or identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section markers in it; "
                f"chapter {chapter_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        New Hampshire.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full
        ``{chapter}:{section}`` citation, e.g. ``"201-A:1"``) must appear
        verbatim within ``parsed.raw_citation`` (the ``RSA 201-A:1``
        citation). The stronger citation cross-check against the source
        response happens in :meth:`retrieve_section`, which parses the
        chapter document's own section heading.

        ``status`` is always left at its default (``UNKNOWN``): repealed
        sections/ranges appear inline as prose annotations with no
        structural repealed signal in the verified structure, and the
        contract explicitly forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a New Hampshire ref
                (``ref.state_code != "NH"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NewHampshireAdapter.normalize cannot normalize a ref for "
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
        """Retrieve and normalize one New Hampshire RSA section, end to
        end: :meth:`build_url` -> fetch the section's chapter document ->
        locate the section by its ``Section {c}:{s}`` marker -> cross-check
        the section's own heading against ``ref`` -> parse it into a
        :class:`ParsedDocument` -> :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/new_hampshire.md): sections
        are embedded in their chapter document, each marked by a
        ``Section {c}:{s}`` heading followed by the section's own heading
        (``{c}:{s} {Caption}.``) and body, with a ``Source.`` history line.
        The marker's citation must equal ``ref.identifier`` and the
        section's own heading citation must agree with it (a mismatch
        raises :class:`RefMismatchError`); a section whose marker is not
        present raises :class:`RefNotFoundError`. The ``Source.`` line is
        preserved verbatim as ``amendment_notes`` and removed from the
        body. Repealed sections and repealed ranges parse like any other
        section, with their annotation preserved in the heading/body text.

        Args:
            ref: The section to retrieve. Must be a New Hampshire ref
                (``ref.state_code == "NH"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the chapter document returns HTTP 404, or
                if the section's marker is not present in the chapter
                document (an adapter-level expected behavior based on
                project convention; the live behavior is UNVERIFIED).
            RefMismatchError: If the section's own heading citation
                disagrees with ``ref``. Also raised by :meth:`normalize` on
                citation disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body) is missing, or the body is empty
                after cleaning. Also raised by :meth:`normalize` if ``ref``
                is not a New Hampshire ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="New Hampshire section page")

        marker_pattern = re.compile(
            r"<p><b>\s*Section\s+" + re.escape(ref.identifier) + r"\s*</b></p>"
        )
        marker = marker_pattern.search(html)
        if marker is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the chapter document contains no "
                f"section {ref.identifier!r}; the section does not resolve "
                "on the New Hampshire RSA site."
            )

        block_end = len(html)
        next_marker = self._SECTION_MARKER.search(html, marker.end())
        if next_marker is not None:
            block_end = next_marker.start()
        segment = html[marker.end() : block_end]

        heading = self._SECTION_HEADING.search(segment)
        if heading is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its section block contained no heading element; the site's "
                "structure may have changed."
            )
        if heading.group(1) != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched chapter document: "
                f"{heading.group(1)!r}."
            )
        heading_text = self._clean_inner(heading.group(1) + heading.group(2))
        label = self._heading_label(ref.identifier, heading_text)
        heading_html = heading.group(0)

        block = segment.replace(heading_html, "", 1)

        amendment_notes = None
        source = self._SOURCE_LINE.search(block)
        if source is not None:
            amendment_notes = self._clean_inner("Source." + source.group(1))
            block = block[: source.start()] + block[source.end() :]

        text = strip_tags(block, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        raw_citation = f"RSA {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=label or None,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)