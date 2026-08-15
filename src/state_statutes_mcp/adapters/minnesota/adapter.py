"""MinnesotaAdapter: the Minnesota-specific concrete state adapter.

Source: the official Revisor of Statutes publication of Minnesota
Statutes at ``https://www.revisor.mn.gov/statutes/`` -- anonymous,
server-rendered HTML with no authentication or API key (no SPA
framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/minnesota.md``,
which documents live requests to the official host):

* Base URL ``https://www.revisor.mn.gov`` with statutory pages under
  ``/statutes/``.
* The site has NO formal title level: chapters are grouped directly into
  105 official "Parts". To fit the framework's three-level ref model, this
  adapter maps each official Part onto a synthetic ``TitleRef`` whose
  identifier is the part name (e.g. ``"DATA PRACTICES"``). This mapping is
  adapter-internal and documented; it is not a framework change.
* Parts: the statutes root page (``/statutes/``) lists all 105 parts as
  rows of a ``toc_table`` -- link text is the chapter range (``13 - 13C``),
  the adjacent ``<td>`` is the part name (``DATA PRACTICES``). The part page
  URL is ``/statutes/part/{quote_plus(name)}`` (spaces become ``+``, commas
  ``%2C``; the comma form is required -- omitting it 404s).
* Chapters: a part page (``/statutes/part/{NAME}``) lists every chapter of
  the part in a ``chapters_table`` (e.g. ``13``, ``13A``, ``13B``, ``13C``
  under ``DATA PRACTICES``; lettered chapters like ``3C`` exist).
* Sections: a chapter TOC page (``/statutes/cite/{chapter}``, e.g.
  ``/statutes/cite/3C``) lists every section of the chapter as rows whose
  link text is the full dotted citation (``3C.01`` ... ``3C.056``).
  ``SectionRef.identifier`` is this full dotted ``{chapter}.{section}``
  form, matching the citation.
* Section content: ``/statutes/cite/{chapter}.{section}`` (e.g.
  ``/statutes/cite/3C.12``) -- one page per section. Verified structure
  (for 3C.12 and 3E.01):
  * Cross-check anchors ``<h2>Chapter 3C</h2>`` and ``<h2>Section 3C.12</h2>``
    appear before the section content.
  * Heading ``<h1 class="shn">3C.12 SALE AND DISTRIBUTION OF STATUTES AND
    LAWS.</h1>`` (the leading ``{section} `` is stripped for the heading).
  * Body: ``<div class="subd" id="stat.3C.12.1">`` blocks each holding a
    ``<h2 class="subd_no">Subdivision 1.<span class="headnote">...</span>
    </h2>`` and ``<p>`` paragraphs; simple sections use bare ``<p>`` blocks
    (3E.01). A leading ``<a class="permalink">§</a>`` anchor per subd is
    navigation chrome and is dropped.
  * History: ``<div class="history" ...> <h2>History: </h2> <p class="first">
    1984 c 480 s 12; ...</p>`` -- the ``<p class="first">`` holds the
    session-law citations.
* Citation: ``Minn. Stat. § {chapter}.{section}`` (e.g. ``Minn. Stat. §
  3C.12``), adapter-constructed (the ``Minn. Stat.`` abbreviation is
  INFERENCE from standard Minnesota citation usage; the number is VERIFIED
  from the site's own headings).
* Error boundary: a nonexistent part, chapter, or section returns HTTP 404
  (verified), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/minnesota.md``):
whether every part page and every section page renders identically (sampled
``3C.12`` and ``3E.01``), and the exact markup of a repealed section page.
None of these block the implementation below.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
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


class MinnesotaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Revisor of Statutes
    publication of Minnesota Statutes at revisor.mn.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Because Minnesota has no
    formal title level, the official Part groupings are exposed through
    the framework's ``TitleRef`` (a synthetic adapter-internal mapping);
    see the module docstring.
    """

    BASE_URL = "https://www.revisor.mn.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A part row on the statutes root page, e.g. '<tr> <td> <a href=
    # ".../statutes/part/DATA+PRACTICES"> 13 - 13C </a> </td> <td>DATA
    # PRACTICES</td> </tr>'. The part name is in the second <td>; the link
    # text is the chapter range (not used as the identifier).
    _PART_ROW = re.compile(
        r"<tr>\s*<td>\s*<a href=\"[^\"]*statutes/part/[^\"]+\"[^>]*>[^<]*</a>\s*</td>\s*"
        r"<td>(.*?)</td>\s*</tr>",
        re.IGNORECASE | re.DOTALL,
    )

    # A chapter row on a part page, e.g. '<tr> <td><a href=".../statutes/cite/13">13</a>
    # </td> <td>GOVERNMENT DATA PRACTICES</td> </tr>'. The chapter identifier
    # is the link's cite suffix; the name is the adjacent <td>.
    _CHAPTER_ROW = re.compile(
        r"<tr>\s*<td>\s*<a href=\"[^\"]*statutes/cite/([^\"/]+)\"[^>]*>[^<]*</a>\s*</td>\s*"
        r"<td>(.*?)</td>\s*</tr>",
        re.IGNORECASE | re.DOTALL,
    )

    # A section row on a chapter TOC page, e.g. '<tr> <td> <a href=
    # "/statutes/cite/3C.01">3C.01</a> </td> <td>APPOINTMENT OF REVISOR.</td> </tr>'.
    # Repealed sections carry '<td class="inactive"> [Repealed, ...]</td>',
    # so the name cell's class attribute is optional. The section identifier
    # is the full dotted cite; the name is the adjacent <td>.
    _SECTION_ROW = re.compile(
        r"<tr>\s*<td>\s*<a href=\"[^\"]*statutes/cite/([^\"/]+)\"[^>]*>\s*\1\s*</a>\s*</td>\s*"
        r"<td(?:\s+class=\"[^\"]*\")?>(.*?)</td>\s*</tr>",
        re.IGNORECASE | re.DOTALL,
    )

    # The per-section-page cross-check anchors.
    _CHAPTER_TOC = re.compile(r"<h2>Chapter\s+([^<]+)</h2>")
    _SECTION_TOC = re.compile(r"<h2>Section\s+([^<]+)</h2>")

    # The section heading, e.g. '<h1 class="shn">3C.12 SALE AND DISTRIBUTION
    # OF STATUTES AND LAWS.</h1>'.
    _HEADING_H1 = re.compile(r'<h1 class="shn">(.*?)</h1>', re.DOTALL)

    # The history block opener on a section page.
    _HISTORY = re.compile(r'<div class="history"')
    # The session-law citations inside the history block, e.g. '<p class="first">
    # <a href="...">1984 c 480 s 12</a>; ...</p>'.
    _HIST_FIRST = re.compile(r'<p class="first">(.*?)</p>', re.DOTALL)

    # Navigation chrome inside the body: per-subdivision permalink anchors
    # (e.g. '<a title="Link to Subdivision 1." class="permalink" href="#...">§</a>').
    _PERMALINK = re.compile(r'<a[^>]*class="permalink"[^>]*>.*?</a>', re.DOTALL)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Minnesota."""
        return "MN"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Minnesota."""
        return "Minnesota"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Revisor of Minnesota URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/minnesota.md):

        * Title (synthetic -- an official Part): ``https://www.revisor.mn.gov/statutes/part/{NAME}``
          where ``{NAME}`` is the part name URL-encoded with
          ``urllib.parse.quote_plus`` (spaces ``+``, commas ``%2C``).
        * Chapter: ``https://www.revisor.mn.gov/statutes/cite/{chapter}``
          -- the chapter TOC page (section listing).
        * Section: ``https://www.revisor.mn.gov/statutes/cite/{section}``
          -- the section's own page; ``SectionRef.identifier`` is already
          the full dotted ``{chapter}.{section}`` citation, so it is used
          directly.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/statutes/cite/{ref.identifier}"
        elif isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/statutes/cite/{ref.identifier}"
        elif isinstance(ref, TitleRef):
            name = urllib.parse.quote_plus(ref.identifier)
            return f"{self.BASE_URL}/statutes/part/{name}"
        else:
            raise UnsupportedRefError(
                f"MinnesotaAdapter.build_url does not support refs of type "
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
        there. This method additionally maps a verified HTTP 404 (e.g. an
        invalid part/chapter/section) into :class:`RefNotFoundError` -- the
        source was reached, but the addressed document does not resolve.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than a verified HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Revisor of Minnesota site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Revisor of Minnesota site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every Part (synthetic title) of Minnesota Statutes
        from the statutes root page.

        The root page lists all 105 official Parts. Each Part's identifier
        is its name (e.g. ``"DATA PRACTICES"``), taken from the row's
        second ``<td>``; the display name is the same part name.

        Returns:
            A sequence of :class:`TocNode`, one per part, in document
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the part name.

        Raises:
            AdapterUnavailableError: If the root page cannot be fetched or
                no usable part rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/statutes/"
        html = self._fetch_html(url, what="Minnesota statutes root page")

        parts = []
        seen: set[str] = set()
        for raw_name in self._PART_ROW.findall(html):
            name = " ".join(self._clean_inner(raw_name).split())
            if not name or name in seen:
                continue
            seen.add(name)
            parts.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=name,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=name),
                )
            )

        if not parts:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable part rows in it; the "
                "site's structure may have changed."
            )

        return tuple(parts)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` (a Part) from that
        part's official page.

        The part page (``/statutes/part/{NAME}``) lists every chapter of
        the part in a ``chapters_table``. The identifier is the chapter
        number (e.g. ``"13"``, ``"13A"``, ``"3C"``); the display name is
        the chapter title.

        Args:
            title_ref: The parent part (synthetic title) to enumerate
                chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the part
                does not resolve).
            AdapterUnavailableError: If the part page cannot be fetched for
                any other reason, or if no usable chapter rows could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Minnesota chapter listing")

        chapters = []
        seen: set[str] = set()
        for identifier, raw_name in self._CHAPTER_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = " ".join(self._clean_inner(raw_name).split())
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter rows in it; "
                f"part {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        TOC page.

        The chapter TOC page (``/statutes/cite/{chapter}``) lists every
        section of the chapter. The identifier is the full dotted
        ``{chapter}.{section}`` citation (e.g. ``"3C.01"``); the display
        name is the section headnote.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full dotted citation.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter TOC page cannot be
                fetched for any other reason, or if no usable section rows
                could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Minnesota section listing")

        sections = []
        seen: set[str] = set()
        for identifier, raw_name in self._SECTION_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = " ".join(self._clean_inner(raw_name).split())
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
                f"Fetched {url!r} but found no usable section rows in it; "
                f"chapter {chapter_ref.identifier!r} under part "
                f"{chapter_ref.title.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Minnesota.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full dotted
        ``{chapter}.{section}`` citation, e.g. ``"3C.12"``) must appear
        verbatim within ``parsed.raw_citation`` (the ``Minn. Stat. § 3C.12``
        citation). The stronger chapter/section cross-check against the
        source response happens in :meth:`retrieve_section`, which has the
        page's ``<h2>Chapter`` / ``<h2>Section`` anchors.

        ``status`` is always left at its default (``UNKNOWN``): neither
        ``ParsedDocument`` nor anything observed on the Revisor of
        Minnesota site in this milestone's other methods defines a
        structural repealed/amended/renumbered signal, and the contract
        explicitly forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Minnesota ref
                (``ref.state_code != "MN"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MinnesotaAdapter.normalize cannot normalize a ref for state "
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
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Minnesota statute section, end to
        end: :meth:`build_url` -> fetch the section page -> cross-check the
        page's ``<h2>Chapter`` / ``<h2>Section`` anchors against ``ref`` ->
        parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/minnesota.md): the heading
        is a ``<h1 class="shn">`` (the leading ``{section} `` prefix is
        stripped); the body is the region between the heading and the
        ``history`` block, with per-subdivision permalink anchors dropped
        and subdivision headings/paragraphs preserved as block-separated
        text; ``amendment_notes`` is the history block's ``<p class="first">``
        text. The section page's ``<h2>Chapter`` / ``<h2>Section`` anchors
        are cross-checked against ``ref.chapter`` / ``ref`` and a mismatch
        raises :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be a Minnesota ref
                (``ref.state_code == "MN"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's chapter/section anchors disagree
                with ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body, anchors) is missing, or the body
                is empty after cleaning. Also raised by :meth:`normalize`
                if ``ref`` is not a Minnesota ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Minnesota section page")

        chapter_toc = self._CHAPTER_TOC.search(html)
        if chapter_toc is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no Chapter "
                "anchor; the site's structure may have changed."
            )
        if chapter_toc.group(1).strip() != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section page: "
                f"{chapter_toc.group(1)!r}."
            )

        section_toc = self._SECTION_TOC.search(html)
        if section_toc is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no Section "
                "anchor; the site's structure may have changed."
            )
        if section_toc.group(1).strip() != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched section page: {section_toc.group(1)!r}."
            )

        heading_h1 = self._HEADING_H1.search(html)
        if heading_h1 is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading element; the site's "
                "structure may have changed."
            )
        raw_heading = self._clean_inner(heading_h1.group(1))
        heading = re.sub(rf"^{re.escape(ref.identifier)}\s*", "", raw_heading).strip()
        heading = heading or None

        body_html = html[heading_h1.end() :]
        history = self._HISTORY.search(body_html)
        if history is not None:
            body_html = body_html[: history.start()]

        body_html = self._PERMALINK.sub(" ", body_html)
        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        if history is not None:
            history_region = html[history.end() :]
            hist_first = self._HIST_FIRST.search(history_region)
            if hist_first is not None:
                amendment_notes = self._clean_inner(hist_first.group(1)) or None

        raw_citation = f"Minn. Stat. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
