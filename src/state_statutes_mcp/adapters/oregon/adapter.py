"""OregonAdapter: the Oregon-specific concrete state adapter.

Source: the official Oregon Revised Statutes at
``https://www.oregonlegislature.gov/bills_laws/ors/`` -- anonymous,
server-rendered HTML with no authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/oregon.md``; verified against a Wayback Machine capture of
the official host, snapshot ``20260224045708id_``):

* Base URL ``https://www.oregonlegislature.gov/bills_laws/ors``. Each
  chapter's page is ``ors{NNN}.html`` where ``{NNN}`` is the chapter's
  numeric prefix zero-padded to three digits (``1`` -> ``001``,
  ``72A`` -> ``072A``); lettered chapter suffixes are kept.
* Hierarchy Chapter -> Section. Sections are ``{chapter}.{NNN}``
  identifiers (e.g. ``1.001``, ``1.212``, ``72.345``). Each section is
  opened by a heading paragraph ``<p class=MsoNormal>...<b><span
  ...>NNN.xxx Caption.</span></b>...``.
* The chapter list on each page's header (``ORS`` header) mirrors the
  sections, but repeals are reflected in the LIST, not the document:
  a repealed section (e.g. ``1.100``) is absent from the header list but
  its heading and body remain in the document, carrying a bracketed
  history such as ``[Repealed by 1983 c.763 §9]`` with no body text.
* Section body content lives in ``<p class=MsoNormal>`` paragraphs
  following the heading; a spacer paragraph (``\xa0``) separates the
  core body from a "notes" region carrying bracketed history/notes.
* The document is a Windows-1252 (latin-1) encoding with ``\xa0``
  non-breaking spaces and ``\r\n`` line breaks; the adapter decodes the
  raw bytes as ``windows-1252`` (the shared UTF-8 ``fetch_url`` is not
  used here by design).
* Citation: ``ORS {section}``; ``raw_citation`` is that form and
  ``SectionRef.identifier`` is ``{section}`` (e.g. ``"1.001"``).

**Title/chapter discovery BLOCKED BY DESIGN (UNVERIFIED):** the Oregon
source publishes its title index only as a PDF (``ORS_TitlesChapters.pdf``)
and the landing page does not server-render a title list, so
``list_titles`` and ``list_chapters`` raise ``AdapterUnavailableError``
directly with a clear explanation. Only ``list_sections`` and section
retrieval are supported. This is documented in ``docs/research/oregon.md``.

**Error boundary:** HTTP 404 maps to ``RefNotFoundError`` (project
convention; the live 404 behavior is UNVERIFIED since the host is not
reachable from this environment); other network failures map to
``AdapterUnavailableError``. A section whose heading is not present in a
fetched chapter document raises ``RefNotFoundError`` (adapter-level
expected behavior; live behavior UNVERIFIED).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Sequence

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


class OregonAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Oregon Revised Statutes.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Title/chapter discovery
    is deliberately unsupported (BLOCKED BY DESIGN; see module docstring).
    """

    BASE_URL = "https://www.oregonlegislature.gov/bills_laws/ors"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A section heading paragraph, e.g.
    # '<b><span style=\'...\'>\xa0\xa0\xa0 1.001 State policy for courts.</span></b>'.
    _HEADING = re.compile(
        r"<b><span[^>]*>\s*(\d{1,3}[A-Z]?\.\d{3})(.*?)</span></b>",
        re.DOTALL,
    )
    _SECTION_NUMBER = re.compile(r"^\d{1,3}[A-Z]?\.\d{3}")
    _PARA = re.compile(r"<p class=MsoNormal[^>]*>(.*?)</p>", re.DOTALL)
    _BRACKET = re.compile(r"\[[^\]]*\]")

    # e.g. "1" -> "001", "72A" -> "072A", "161" -> "161".
    _CHAPTER_IDENTIFIER = re.compile(r"^(\d+)([A-Za-z]*)$")

    # UNSUPPORTED discovery message (title/chapter index is PDF-only).
    _DISCOVERY_UNAVAILABLE = (
        "Oregon title/chapter discovery is not supported: the Oregon "
        "Legislature publishes its title and chapter index only as a PDF "
        "(ORS_TitlesChapters.pdf) and the ORS landing page does not "
        "server-render a title list, so there is no HTML page to enumerate "
        "titles from. Retrieve sections directly (e.g. '1.001')."
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Oregon."""
        return "OR"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Oregon."""
        return "Oregon"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    @classmethod
    def _pad_identifier(cls, identifier: str) -> str:
        """Zero-pad a chapter identifier's numeric prefix to three digits,
        keeping any trailing letter suffix (e.g. ``"1"`` -> ``"001"``,
        ``"72A"`` -> ``"072A"``)."""
        match = cls._CHAPTER_IDENTIFIER.match(identifier)
        if match is None:
            raise UnsupportedRefError(
                f"Cannot build an Oregon ORS page name from chapter "
                f"identifier {identifier!r}: expected a numeric prefix with "
                "an optional trailing letter (e.g. '1', '72A')."
            )
        number, suffix = match.groups()
        return f"{int(number):03d}{suffix}"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Oregon Revised Statutes URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/oregon.md):

        * Section / Chapter: ``https://www.oregonlegislature.gov/
          bills_laws/ors/ors{NNN}.html`` where ``{NNN}`` is the chapter's
          zero-padded numeric prefix (e.g. ``ors001.html`` for chapter 1,
          ``ors072A.html`` for chapter 72A). Sections are embedded in
          their chapter document, so that document is the closest real
          resource (the same model NevadaAdapter uses).
        * Title: no page exists (title index is PDF-only); raising
          :class:`UnsupportedRefError`.

        Args:
            ref: The chapter or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is a :class:`TitleRef` (there
                is no Oregon title page), or not a chapter/section ref.
        """
        if isinstance(ref, SectionRef):
            identifier = ref.chapter.identifier
        elif isinstance(ref, ChapterRef):
            identifier = ref.identifier
        elif isinstance(ref, TitleRef):
            raise UnsupportedRefError(
                "OregonAdapter.build_url cannot address a title: the Oregon "
                "title index is published only as a PDF and has no HTML page."
            )
        else:
            raise UnsupportedRefError(
                f"OregonAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )
        page = f"ors{self._pad_identifier(identifier)}.html"
        return f"{self.BASE_URL}/{page}"

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Oregon pages are Windows-1252 (latin-1), so this method does its
        own ``urllib.request.urlopen`` call and decodes the raw bytes as
        ``windows-1252`` rather than delegating to the shared UTF-8
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text decoded as Windows-1252.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Oregon site).
        """
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "state-statutes-mcp/0.1"},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=self.DEFAULT_TIMEOUT_SECONDS
            ) as response:
                return response.read().decode("windows-1252")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Oregon Revised Statutes "
                    "site."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    @classmethod
    def _clean(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return " ".join(strip_tags(html_fragment).split())

    @classmethod
    def _is_spacer(cls, paragraph_html: str) -> bool:
        """True if ``paragraph_html`` renders to empty text (a layout
        spacer paragraph such as ``\\xa0``)."""
        return cls._clean(paragraph_html).replace("\xa0", " ").strip() == ""

    @classmethod
    def _is_all_caps(cls, line: str) -> bool:
        """True if ``line`` is an all-caps heading line (e.g. a part
        heading such as ``PART I``)."""
        stripped = line.strip()
        if len(stripped) < 3:
            return False
        return stripped == stripped.upper() and any(c.isalpha() for c in stripped)

    @classmethod
    def _section_caption(cls, heading_html: str) -> str | None:
        """Extract the caption from a section heading, stripping the leading
        section number (e.g. ``1.001``) from the cleaned heading text."""
        cleaned = cls._clean(heading_html).lstrip()
        caption = cls._SECTION_NUMBER.sub("", cleaned, count=1).lstrip()
        return caption or None

    def _heading_offsets(self, html: str) -> list[tuple[re.Match, int]]:
        """Return ``(heading_match, absolute_start_offset)`` for every
        section heading in ``html``, in document order.

        The body region begins at the first ``<b><span`` occurrence; the
        returned offsets are absolute positions within ``html``.
        """
        first = html.find("<b><span")
        body = html[first:]
        headings = list(self._HEADING.finditer(body))
        return [(m, first + m.start()) for m in headings]

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Not supported for Oregon (BLOCKED BY DESIGN).

        The Oregon title index is published only as a PDF
        (``ORS_TitlesChapters.pdf``) and the landing page does not
        server-render a title list, so there is no HTML page to enumerate
        titles from. This method raises ``AdapterUnavailableError``
        directly instead of attempting a fetch.

        Raises:
            AdapterUnavailableError: Always, with the discovery explanation.
        """
        raise AdapterUnavailableError(self._DISCOVERY_UNAVAILABLE)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Not supported for Oregon (BLOCKED BY DESIGN).

        Same rationale as :meth:`list_titles`: the chapter index is
        PDF-only and no HTML chapter listing exists. Raises
        ``AdapterUnavailableError`` directly.

        Args:
            title_ref: Ignored; there are no enumerable titles.

        Raises:
            AdapterUnavailableError: Always, with the discovery explanation.
        """
        raise AdapterUnavailableError(self._DISCOVERY_UNAVAILABLE)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section in ``chapter_ref``'s chapter document.

        The chapter document (``ors{NNN}.html``) contains every section's
        heading; each heading's number is the section identifier (e.g.
        ``1.001``). Unlike the header's chapter list, the document still
        carries repealed sections (e.g. ``1.100``), so they are listed.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section number (e.g. ``"1.001"``).

        Raises:
            RefNotFoundError: If the chapter document returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any other reason, or if no usable section
                headings could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Oregon section listing")

        sections = []
        seen: dict[str, None] = {}
        for match, _ in self._heading_offsets(html):
            identifier = match.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            caption = self._section_caption(match.group(2))
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
                f"Fetched {url!r} but found no usable section headings in "
                f"it; chapter {chapter_ref.identifier!r} either does not "
                "resolve or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Oregon.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (e.g. ``"1.001"``) must
        appear verbatim within ``parsed.raw_citation`` (the ``ORS 1.001``
        citation). The stronger citation cross-check against the source
        response happens in :meth:`retrieve_section`, which parses the
        chapter document's own heading number.

        ``status`` is always left at its default (``UNKNOWN``): the Oregon
        chapter documents carry no structural repealed/amended/renumbered
        signal in the verified structure, and the contract explicitly
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Oregon ref
                (``ref.state_code != "OR"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"OregonAdapter.normalize cannot normalize a ref for state "
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

    def _parse_section_block(
        self,
        html: str,
        headings: list[tuple[re.Match, int]],
        index: int,
    ) -> tuple[str, str, str, str | None]:
        """Parse one section's block out of ``html`` and return
        ``(identifier, caption, text, amendment_notes)``.

        The block spans from the heading paragraph's ``<p class=MsoNormal``
        open tag to just before the next section's heading (or the end of
        the document). Its ``<p class=MsoNormal>`` paragraphs are split at
        the first layout-spacer paragraph into a CORE region (the body)
        and a NOTES region (bracketed history/notes). The body's final
        bracketed history (e.g. ``[1959 c.552 §1; ...]``) is lifted out as
        ``amendment_notes`` (whitespace collapsed); trailing all-caps part
        headings are dropped from a body with no bracket. All-caps part
        headings are also filtered out of the notes region.
        """
        heading_match, abs_start = headings[index]
        identifier = heading_match.group(1)
        caption = self._section_caption(heading_match.group(2))

        abs_end = (
            headings[index + 1][1]
            if index + 1 < len(headings)
            else len(html)
        )

        paragraph_open = html.rfind(
            "<p class=MsoNormal", max(0, abs_start - 50000), abs_start
        )
        if paragraph_open < 0:
            paragraph_open = abs_start

        segment = html[paragraph_open:abs_end].replace(heading_match.group(0), " ", 1)
        paragraphs = self._PARA.findall(segment)

        core: list[str] = []
        notes: list[str] = []
        in_notes = False
        for paragraph in paragraphs:
            if self._is_spacer(paragraph):
                in_notes = True
                continue
            (notes if in_notes else core).append(paragraph)

        core_text = strip_tags(
            " ".join(core), preserve_block_breaks=True
        ).strip()
        notes_text = strip_tags(
            " ".join(notes), preserve_block_breaks=True
        ).strip()

        notes_lines = [
            line for line in notes_text.split("\n") if not self._is_all_caps(line)
        ]
        notes_text = "\n".join(notes_lines).strip()

        amendment = None
        bracket_matches = list(self._BRACKET.finditer(core_text))
        if bracket_matches:
            last = bracket_matches[-1]
            amendment = " ".join(last.group(0).split())
            core_text = core_text[: last.start()].strip()
        else:
            lines = core_text.split("\n")
            while lines and self._is_all_caps(lines[-1]):
                lines.pop()
            core_text = "\n".join(lines).strip()

        text = core_text + ("\n\n" + notes_text if notes_text else "")
        return identifier, caption, text, amendment

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Oregon Revised Statutes section, end
        to end: :meth:`build_url` -> fetch the section's chapter document
        -> locate the section by its heading number -> parse its block into
        a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/oregon.md): sections are
        embedded in their chapter document, each opened by a heading
        paragraph whose number (e.g. ``1.001``) must equal
        ``ref.identifier``. A section whose number is not present raises
        :class:`RefNotFoundError`. The body is the block's paragraphs with
        the heading, layout spacers, and bracketed history removed; the
        history is preserved verbatim as ``amendment_notes``. A section
        whose body is empty after cleaning (e.g. a repealed section such as
        ``1.100``) is still returned when it carries amendment notes;
        empty body with no amendment raises :class:`NormalizationError`.

        Args:
            ref: The section to retrieve. Must be an Oregon ref
                (``ref.state_code == "OR"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the chapter document returns HTTP 404, or
                if the section's heading number is not present in the
                chapter document (an adapter-level expected behavior based
                on project convention; the live behavior is UNVERIFIED).
            NormalizationError: If the section was located but its body is
                empty after cleaning and it carries no amendment notes.
                Also raised by :meth:`normalize` if ``ref`` is not an
                Oregon ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Oregon section page")

        headings = self._heading_offsets(html)
        index = next(
            (
                i
                for i, (match, _) in enumerate(headings)
                if match.group(1) == ref.identifier
            ),
            None,
        )
        if index is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the chapter document contains no "
                f"section {ref.identifier!r}; the section does not resolve "
                "on the Oregon Revised Statutes site."
            )

        identifier, caption, text, amendment = self._parse_section_block(
            html, headings, index
        )
        if not text and not amendment:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning and it carries no "
                "amendment notes; the section is likely empty or the site's "
                "structure has changed."
            )

        raw_citation = f"ORS {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=caption,
            text=text,
            amendment_notes=amendment,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)