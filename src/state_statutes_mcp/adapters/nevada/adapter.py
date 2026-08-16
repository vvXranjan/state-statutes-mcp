"""NevadaAdapter: the Nevada-specific concrete state adapter.

Source: the official Nevada Legislature publication of the Nevada Revised
Statutes (NRS) at ``https://www.leg.state.nv.us/nrs/`` -- anonymous,
server-rendered HTML with no authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/nevada.md``;
the official ``leg.state.nv.us/nrs/`` source was verified independently by
the research source of truth for this batch -- the host could not be
independently fetched from this environment and no Wayback capture was
available, so the fixtures used by the tests are SYNTHETIC and
representative, reproducing only the VERIFIED structures below):

* Base URL ``https://www.leg.state.nv.us`` with the NRS index under
  ``/nrs/``.
* Hierarchy Title -> Chapter -> Section. The root (``/nrs/``) lists the
  titles and, under each title, its chapter links.
* Chapter documents: ``/nrs//NRS-{chapter}.html`` -- note the literal
  DOUBLE SLASH after ``/nrs/`` (e.g. ``/nrs//NRS-220.html``). Lettered
  chapters are supported (e.g. ``NRS-220A.html``).
* Sections are embedded in their chapter document (chapter-document based
  retrieval), each carrying an anchor id of the form ``NRS{chapter}Sec{seq}``
  (e.g. ``#NRS220Sec040``). The anchor sequence number is distinct from the
  section's citation number, so the adapter uses the anchors ONLY as
  section-boundary markers and reads each section's citation from its own
  heading text.
* Section headings carry the citation ``NRS {chapter}.{section}`` (e.g.
  ``NRS 220.170``); the section's own caption follows the citation.
* History: bracketed session-law text follows the section body (e.g.
  ``[1:21:1955]``), preserved verbatim as ``amendment_notes`` and removed
  from the body. A section may have no history.
* Citation: ``NRS {chapter}.{section}`` (e.g. ``NRS 220.170``);
  ``SectionRef.identifier`` is the full ``{chapter}.{section}`` number.
* Error boundary: the live HTTP 404 behavior is UNVERIFIED (source not
  fetchable from this environment); by project convention HTTP 404 maps to
  ``RefNotFoundError`` and other network failures to
  ``AdapterUnavailableError``. A section that is not present in a fetched
  chapter document raises ``RefNotFoundError`` (adapter-level expected
  behavior based on project convention; live behavior UNVERIFIED).

**UNVERIFIED / accepted limitations** (documented in
``docs/research/nevada.md``): the exact HTML markup of the root and of the
chapter documents beyond the VERIFIED structures (the synthetic fixtures
use representative markup), the exact relationship between the anchor
sequence number and the citation number, and the lettered-chapter anchor
form. None of these block the implementation below.
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


class NevadaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Nevada Legislature
    publication of the Nevada Revised Statutes at leg.state.nv.us.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://www.leg.state.nv.us"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title heading on the root, e.g. '<h2>Title 1 - State of Nevada</h2>'.
    # The identifier is the title number; the name is the text after the
    # '- ' separator.
    _TITLE_HEADING = re.compile(
        r"<h2>\s*Title\s+([0-9A-Z]+)\s*-\s*(.*?)</h2>", re.DOTALL
    )

    # A chapter link row on the root, e.g. '<p><a href="/nrs//NRS-220.html">
    # Chapter 220 - State Highway System</a></p>'. The identifier is the
    # number/lettered suffix in the href; the name is the text after the
    # '- ' separator.
    _CHAPTER_ROW = re.compile(
        r'<a href="/nrs//NRS-([0-9A-Z]+)\.html"[^>]*>\s*Chapter\s+[0-9A-Z]+\s*-\s*(.*?)</a>',
        re.DOTALL,
    )

    # A section anchor inside a chapter document, e.g.
    # '<a name="NRS220Sec040"></a>'. The id encodes the chapter and a
    # per-chapter sequence number; the sequence number is NOT the citation
    # number, so anchors are used only as section-boundary markers.
    _SECTION_ANCHOR = re.compile(r'<a\s+name="NRS([0-9A-Z]+)Sec(\d+)"></a>')

    # A section heading line inside a chapter document, e.g.
    # '<p><b>NRS 220.170</b> Authority to acquire property.</p>'. The
    # citation number is group(1) ('220.170'); the caption is group(2).
    _HEADING = re.compile(
        r"<p><b>\s*NRS\s+([0-9A-Z]+\.[0-9]+)\s*</b>\s*(.*?)</p>", re.DOTALL
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Nevada."""
        return "NV"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Nevada."""
        return "Nevada"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Nevada NRS URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/nevada.md):

        * Title: ``https://www.leg.state.nv.us/nrs/`` -- the root, which
          lists the titles and their chapter links.
        * Chapter: ``https://www.leg.state.nv.us/nrs//NRS-{chapter}.html``
          -- note the literal double slash after ``/nrs/``. Lettered
          chapters keep their letter (e.g. ``NRS-220A.html``).
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
            return f"{self.BASE_URL}/nrs//NRS-{ref.chapter.identifier}.html"
        elif isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/nrs//NRS-{ref.identifier}.html"
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/nrs/"
        else:
            raise UnsupportedRefError(
                f"NevadaAdapter.build_url does not support refs of type "
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
        there. This method additionally maps HTTP 404 into
        :class:`RefNotFoundError` -- the source was reached, but the
        addressed document does not resolve. The live 404 behavior of the
        Nevada site is UNVERIFIED (source not fetchable from this
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
                does not resolve on the Nevada Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Nevada Legislature site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _numeric_sort_key(cls, identifier: str) -> tuple[int, str]:
        """Sort key for Nevada identifiers: the integer leading part first,
        then the full identifier for a stable tie-break. Handles the dotted
        ``{chapter}.{section}`` section ids and the plain chapter/title
        numbers."""
        match = re.match(r"(\d+)", identifier)
        return (int(match.group(1)) if match else 0, identifier)

    def _title_heading_offsets(self, html: str) -> list[tuple[str, int]]:
        """Return ``(identifier, start_offset)`` for every title heading on
        the root, in document order."""
        return [
            (match.group(1), match.start())
            for match in self._TITLE_HEADING.finditer(html)
        ]

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Nevada Revised Statutes from the
        root page.

        The root page (``/nrs/``) lists the titles; each title heading
        carries its number and name (e.g. ``Title 1 - State of Nevada``).

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"1"``).

        Raises:
            AdapterUnavailableError: If the root page cannot be fetched, or
                if no usable title headings could be parsed from it.
        """
        url = f"{self.BASE_URL}/nrs/"
        html = self._fetch_html(url, what="Nevada NRS index page")

        titles = []
        seen: dict[str, None] = {}
        for identifier, raw_name in self._TITLE_HEADING.findall(html):
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
            sorted(titles, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the root page.

        The root page (``/nrs/``) lists the titles and, under each title,
        that title's chapter links. The chapters belonging to ``title_ref``
        are the chapter rows between ``title_ref``'s heading and the next
        title heading.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"220"``, lettered
            ``"220A"``).

        Raises:
            RefNotFoundError: If ``title_ref``'s heading is not present on
                the root page (the title does not resolve).
            AdapterUnavailableError: If the root page cannot be fetched for
                any other reason, or if no usable chapter rows could be
                parsed under the title.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Nevada NRS index page")

        offsets = self._title_heading_offsets(html)
        match = None
        for i, (identifier, start) in enumerate(offsets):
            if identifier == title_ref.identifier:
                end = offsets[i + 1][1] if i + 1 < len(offsets) else len(html)
                match = (start, end)
                break
        if match is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the root page lists no title "
                f"{title_ref.identifier!r}; the title does not resolve on "
                "the Nevada Legislature site."
            )
        start, end = match
        segment = html[start:end]

        chapters = []
        seen: dict[str, None] = {}
        for identifier, raw_name in self._CHAPTER_ROW.findall(segment):
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

        return tuple(
            sorted(chapters, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        document.

        The chapter document (``/nrs//NRS-{chapter}.html``) contains all of
        the chapter's sections. Each section is opened by an anchor
        (``NRS{chapter}Sec{seq}``) followed by its heading line
        (``NRS {chapter}.{section}`` plus caption). The section identifier
        is the citation number from the heading (e.g. ``"220.170"``); the
        display name is the caption.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{chapter}.{section}`` citation
            number.

        Raises:
            RefNotFoundError: If the chapter document returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any other reason, or if no usable section
                anchors could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Nevada section listing")

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
                f"Fetched {url!r} but found no usable section anchors in it; "
                f"chapter {chapter_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    def _iter_sections(self, html: str):
        """Yield ``(identifier, name)`` for every section in a chapter
        document, in document order.

        A section runs from its anchor to the next anchor. Its heading is
        the first ``NRS {citation} ...`` heading line inside that span; the
        identifier is the citation number and the name is the caption.

        Args:
            html: The chapter document HTML.

        Returns:
            A generator of ``(identifier, name)`` pairs.
        """
        anchors = list(self._SECTION_ANCHOR.finditer(html))
        for i, anchor in enumerate(anchors):
            start = anchor.end()
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
            segment = html[start:end]
            heading = self._HEADING.search(segment)
            if heading is None:
                continue
            identifier = heading.group(1)
            name = " ".join(self._clean_inner(heading.group(2)).split())
            yield identifier, name

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Nevada.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full dotted
        ``{chapter}.{section}`` citation number, e.g. ``"220.170"``) must
        appear verbatim within ``parsed.raw_citation`` (the ``NRS 220.170``
        citation). The stronger citation cross-check against the source
        response happens in :meth:`retrieve_section`, which parses the
        chapter document's own heading lines.

        ``status`` is always left at its default (``UNKNOWN``): the Nevada
        chapter documents carry no structural repealed/amended/renumbered
        signal in the verified structure, and the contract explicitly
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Nevada ref
                (``ref.state_code != "NV"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NevadaAdapter.normalize cannot normalize a ref for state "
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

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Nevada NRS section, end to end:
        :meth:`build_url` -> fetch the section's chapter document -> locate
        the section by its own heading citation -> parse it into a
        :class:`ParsedDocument` -> :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/nevada.md): sections are
        embedded in their chapter document, each opened by an anchor
        (``NRS{chapter}Sec{seq}``) and carrying its heading line
        (``NRS {chapter}.{section}`` plus caption). The section's own
        heading citation is matched against ``ref.identifier``; a section
        whose citation is not present in the chapter document raises
        :class:`RefNotFoundError`. The body runs to the next section's
        anchor; a trailing bracketed group (the session-law history) is
        preserved verbatim as ``amendment_notes`` and removed from the
        body.

        Args:
            ref: The section to retrieve. Must be a Nevada ref
                (``ref.state_code == "NV"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the chapter document returns HTTP 404, or
                if the section's citation is not present in the chapter
                document (an adapter-level expected behavior based on
                project convention; the live behavior is UNVERIFIED).
            NormalizationError: If the section was located but required
                structure (heading, body) is missing, or the body is empty
                after cleaning. Also raised by :meth:`normalize` if ``ref``
                is not a Nevada ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Nevada section page")

        anchors = list(self._SECTION_ANCHOR.finditer(html))
        match = None
        for i, anchor in enumerate(anchors):
            start = anchor.end()
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
            segment = html[start:end]
            heading = self._HEADING.search(segment)
            if heading is not None and heading.group(1) == ref.identifier:
                match = (start, end, heading)
                break

        if match is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the chapter document contains no "
                f"section {ref.identifier!r}; the section does not resolve "
                "on the Nevada Legislature site."
            )
        start, end, heading = match
        segment = html[start:end]

        heading_text = heading.group(0)
        caption = " ".join(self._clean_inner(heading.group(2)).split()) or None

        body_html = segment.replace(heading_text, "", 1)
        body = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not body:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        history = re.search(r"\[[^\]]*\]\s*$", body)
        if history is not None:
            amendment_notes = history.group(0).strip()
            body = body[: history.start()].strip()
            if not body:
                raise NormalizationError(
                    f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                    "but its body text was empty after removing the "
                    "bracketed history."
                )

        raw_citation = f"NRS {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=caption,
            text=body,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)