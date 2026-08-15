"""SouthCarolinaAdapter: the South Carolina-specific concrete state adapter.

Source: the official South Carolina Legislature publication of the Code of
Laws of South Carolina at ``https://www.scstatehouse.gov`` -- anonymous,
server-rendered HTML with no authentication or API key (no SPA framework,
no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/south_carolina.md``,
which documents live requests to the official host on Aug 15, 2026):

* Base URL ``https://www.scstatehouse.gov`` with the code browser under
  ``/code/``.
* Titles: ``/code/statmast.php`` lists all 63 titles, each as
  ``<a href="/code/title{N}.php">Title {N}</a> - {Name}</span>`` (VERIFIED:
  all 63 titles, no gaps). The title identifier is the title number (e.g.
  ``"1"``); the name is the title heading (e.g. ``"Administration of the
  Government"``). Title names may contain HTML entities (e.g.
  ``&#39;`` in ``South Carolina Children&#39;s Code``).
* Chapters: ``/code/title{N}.php`` lists every chapter of the title as a
  table row ``<td>CHAPTER {N} - {NAME}</td>`` followed by a
  ``<a href="/code/t{NN}c{NNN}.php">HTML</a>`` link (VERIFIED for Title 1:
  21 chapters). Chapter URLs zero-pad the title to 2 digits and the
  chapter to 3 digits (e.g. ``t01c001.php``), regardless of the plain
  numbers in the row text.
* Sections: a chapter page (``/code/t{NN}c{NNN}.php``) contains ALL of the
  chapter's sections, one after another, each as
  ``<span style="font-weight: bold;"> SECTION {t}-{c}-{s}.</span> {heading}.<br /><br />
  {body}<br /><br /> HISTORY: {history}.<br /><br />`` (VERIFIED for
  ``t01c001.php``: 85 sections; ``t01c003.php``: 32 sections). A rare
  lettered section (e.g. ``1-1-714A``) appears in the same form but
  without the bold ``span`` wrapper (VERIFIED for ``1-1-713A`` and
  ``1-1-714A`` in chapter 1). Larger articles inside a chapter are divided
  by ``<div style="text-align: center;">ARTICLE {N}</div>`` dividers,
  which are excluded from section parsing.
* Section content: the heading is the text between the ``SECTION {id}.``
  marker and the ``<br />`` (e.g. ``"Jurisdiction and boundaries of the
  State."``); the body follows the heading's ``<br />`` and runs to the
  ``HISTORY:`` line; the history line is the raw amendment/history text
  (e.g. ``HISTORY: 2020 Act No. 113 (S.11), SECTION 1, eff February 3,
  2020.``) and is preserved verbatim as ``amendment_notes``.
* Citation: ``S.C. Code § {t}-{c}-{s}`` (e.g. ``S.C. Code § 1-1-10``),
  adapter-constructed (the ``S.C. Code`` abbreviation is INFERENCE from
  standard South Carolina citation usage; the number is VERIFIED from the
  site's own heading text).
* Error boundary: a missing title page or chapter page returns HTTP 404
  (verified), mapped here to ``RefNotFoundError``.

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef model**
(verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = the title number (e.g. ``"1"``), ``name`` = the
  title heading (e.g. ``"Administration of the Government"``).
* ``ChapterRef.identifier`` = the chapter number (e.g. ``"1"``), ``name`` =
  the chapter heading (e.g. ``"GENERAL PROVISIONS"``).
* ``SectionRef.identifier`` = the full ``{t}-{c}-{s}`` citation (e.g.
  ``"1-1-10"``).

Sections are embedded in their chapter page, so ``build_url(SectionRef)``
returns the chapter page that contains the section -- the closest real
resource, mirroring how ``DelawareAdapter`` and ``FloridaAdapter`` address
sections embedded in chapter documents.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/south_carolina.md``): whether every title page keeps the
same chapter row markup and every chapter page the same section markup
(sampled Titles 1 and 63; chapters 1 and 3); the lettered-section plain
text form is verified only for chapter 1. None of these block the
implementation below.
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


class SouthCarolinaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official South Carolina Legislature
    publication of the Code of Laws of South Carolina at scstatehouse.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://www.scstatehouse.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A linked title row on /code/statmast.php, e.g.
    # '<a href="/code/title1.php">Title 1</a> - Administration of the Government</span>'.
    _TITLE_LINK = re.compile(
        r'<a href="/code/title(\d+)\.php">Title \d+</a>\s*-\s*([^<]*)</span>',
        re.IGNORECASE | re.DOTALL,
    )

    # A chapter row on /code/title{N}.php, e.g.
    # '<td>CHAPTER 1 - GENERAL PROVISIONS</td><td><a href="/code/t01c001.php">HTML</a></td>'.
    _CHAPTER_ROW = re.compile(
        r'<td>CHAPTER (\d+)\s*-\s*(.*?)</td>\s*<td>\s*<a href="/code/t(\d+)c(\d+)\.php"',
        re.IGNORECASE | re.DOTALL,
    )

    # A section header on a chapter page: the bold-span form
    # '<span style="font-weight: bold;"> SECTION 1-1-10.</span>' for
    # regular sections, or the plain-text form 'SECTION 1-1-714A.' for
    # lettered sections (VERIFIED to coexist in chapter 1).
    _SECTION_HEADER = re.compile(
        r'(?:<span style="font-weight: bold;">\s*)?SECTION ([0-9]+-[0-9]+-[0-9]+[A-Z]?)\.(?:</span>)?',
        re.IGNORECASE,
    )
    # An article divider, e.g. '<div style="text-align: center;">ARTICLE 3</div>',
    # which splits larger chapters into articles and is not section content.
    _ARTICLE_DIVIDER = re.compile(
        r'<div style="text-align: center;">.*?</div>', re.DOTALL
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for South Carolina."""
        return "SC"

    @property
    def state_name(self) -> str:
        """Human-facing display name for South Carolina."""
        return "South Carolina"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    @staticmethod
    def _chapter_url(title: str, chapter: str) -> str:
        """Build a chapter page URL with the verified zero-padding rule.

        Chapter URLs pad the title to 2 digits and the chapter to 3 digits
        (e.g. Title 1 Chapter 1 -> ``t01c001.php``), regardless of the
        plain numbers used in row text.

        Args:
            title: The title number (e.g. ``"1"``).
            chapter: The chapter number (e.g. ``"1"``).

        Returns:
            The chapter page path (e.g. ``"/code/t01c001.php"``).
        """
        return f"/code/t{int(title):02d}c{int(chapter):03d}.php"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official South Carolina Code URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/south_carolina.md):

        * Title: ``/code/title{N}.php`` -- the title page (chapter listing).
        * Chapter: ``/code/t{NN}c{NNN}.php`` -- the chapter page, which
          contains all of the chapter's sections.
        * Section: the same chapter page -- sections are embedded in their
          chapter document, so the chapter page that contains them is the
          closest real resource.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return (
                f"{self.BASE_URL}"
                f"{self._chapter_url(ref.chapter.title.identifier, ref.chapter.identifier)}"
            )
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}"
                f"{self._chapter_url(ref.title.identifier, ref.identifier)}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/code/title{ref.identifier}.php"
        else:
            raise UnsupportedRefError(
                f"SouthCarolinaAdapter.build_url does not support refs of type "
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
        invalid title or chapter) into :class:`RefNotFoundError` -- the
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
                does not resolve on the South Carolina Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the South Carolina Legislature "
                    "site."
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
        """Enumerate every title of the South Carolina Code of Laws from
        the master title page.

        The ``/code/statmast.php`` page lists all 63 titles as linked
        rows ``<a href="/code/title{N}.php">Title {N}</a> - {Name}</span>``.
        Title names may contain HTML entities (e.g. ``&#39;``), decoded by
        ``strip_tags``.

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"1"``).

        Raises:
            AdapterUnavailableError: If the master title page cannot be
                fetched or no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/code/statmast.php"
        html = self._fetch_html(url, what="South Carolina title list")

        titles = []
        seen: set[str] = set()
        for identifier, raw_name in self._TITLE_LINK.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = " ".join(self._clean_inner(raw_name).split())
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable title links in it; the "
                "site's structure may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title page.

        The title page (``/code/title{N}.php``) lists every chapter as a
        table row ``<td>CHAPTER {N} - {NAME}</td>`` followed by a link to
        the chapter's HTML page. The identifier is the chapter number from
        the row; the display name is the chapter heading.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"1"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title page cannot be fetched
                for any other reason, or if no usable chapter rows could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="South Carolina chapter listing")

        chapters = []
        seen: set[str] = set()
        for identifier, raw_name, _title_digits, _chapter_digits in self._CHAPTER_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
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
                f"Fetched {url!r} but found no usable chapter rows in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        page.

        The chapter page (``/code/t{NN}c{NNN}.php``) contains all of the
        chapter's sections. Each section header is ``SECTION {t}-{c}-{s}.``
        in a bold ``span`` (regular sections) or plain text (lettered
        sections). The section identifier is the full ``{t}-{c}-{s}``
        citation; the display name is the section's own heading text
        (e.g. ``"Jurisdiction and boundaries of the State."``).

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{t}-{c}-{s}`` citation.

        Raises:
            RefNotFoundError: If the chapter page returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section headers could
                be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="South Carolina section listing")

        sections = []
        seen: set[str] = set()
        for header in self._SECTION_HEADER.finditer(html):
            identifier = header.group(1)
            if identifier in seen:
                continue
            seen.add(identifier)
            name = self._section_heading_from(html, header.end())
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
                f"Fetched {url!r} but found no usable section headers in it; "
                f"chapter {chapter_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    @classmethod
    def _section_heading_from(cls, html: str, start: int) -> str:
        """Extract a section's own heading from the text following its
        ``SECTION {id}.`` header.

        The heading is the text between the header marker and the first
        ``<br />`` (e.g. ``"Jurisdiction and boundaries of the State."``).
        Lettered sections may omit the bold ``span``, but the heading
        still ends at the first ``<br />``.

        Args:
            html: The chapter page HTML.
            start: The offset just after a section header.

        Returns:
            The section's heading text (may be empty).
        """
        heading, _br = cls._section_heading_and_br(html, start)
        return heading

    @classmethod
    def _section_heading_and_br(cls, html: str, start: int) -> tuple[str, int]:
        """Extract a section heading and the offset of the ``<br>`` that
        ends it.

        Args:
            html: The chapter page HTML.
            start: The offset just after a section header.

        Returns:
            A ``(heading, br_offset)`` pair where ``br_offset`` is the index
            of the ``<br>`` ending the heading (or ``-1`` if there is no
            ``<br>``).
        """
        br = html.find("<br", start)
        fragment = html[start:br] if br != -1 else html[start:]
        return " ".join(cls._clean_inner(fragment).split()), br

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        South Carolina.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full ``{t}-{c}-{s}``
        citation, e.g. ``"1-1-10"``) must appear verbatim within
        ``parsed.raw_citation`` (the ``S.C. Code § 1-1-10`` citation). The
        stronger citation-number cross-check against the source response
        happens in :meth:`retrieve_section`, which parses the page's own
        ``SECTION`` header.

        ``status`` is always left at its default (``UNKNOWN``): South
        Carolina chapter pages carry no structural repealed/amended/
        renumbered signal observed in this milestone, and the contract
        explicitly forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a South Carolina ref
                (``ref.state_code != "SC"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"SouthCarolinaAdapter.normalize cannot normalize a ref for "
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
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one South Carolina Code section, end to
        end: :meth:`build_url` -> fetch the section's chapter page ->
        cross-check the page's own ``SECTION {id}.`` header against ``ref``
        -> parse the section from the chapter page into a
        :class:`ParsedDocument` -> :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/south_carolina.md): sections
        are embedded in their chapter page, each as ``SECTION {id}.``
        followed by its heading, body, and ``HISTORY:`` line. The section's
        own header is cross-checked against ``ref.identifier`` and a
        mismatch raises :class:`RefMismatchError` before anything is
        parsed. A section that is not present on the chapter page raises
        :class:`RefNotFoundError`.

        Args:
            ref: The section to retrieve. Must be a South Carolina ref
                (``ref.state_code == "SC"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the chapter page returns HTTP 404, or if
                the section's header is not present on the chapter page
                (the verified not-found signal for an embedded section).
            RefMismatchError: If the page's ``SECTION`` header disagrees
                with ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body) is missing, or the body is empty
                after cleaning. Also raised by :meth:`normalize` if ``ref``
                is not a South Carolina ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="South Carolina section page")

        header_pattern = re.compile(
            r'(?:<span style="font-weight: bold;">\s*)?SECTION '
            + re.escape(ref.identifier)
            + r'\.(?:</span>)?',
            re.IGNORECASE,
        )
        header_match = header_pattern.search(html)
        if header_match is None:
            raise RefNotFoundError(
                f"Fetched {url!r} but the chapter page contains no section "
                f"{ref.identifier!r}; the section does not resolve on the "
                "South Carolina Legislature site."
            )

        # The section runs to the next SECTION header or the end of the page.
        section_end = len(html)
        next_header = self._SECTION_HEADER.search(html, header_match.end())
        if next_header is not None:
            section_end = next_header.start()
        block = html[header_match.end() : section_end]

        # The heading is the text up to the first <br> after the header; the
        # body begins after that <br>.
        heading, heading_br = self._section_heading_and_br(html, header_match.end())
        if heading_br == -1:
            body_block = ""
        else:
            body_block = block[heading_br - header_match.end() :]
        body_block = self._ARTICLE_DIVIDER.sub(" ", body_block)

        history_match = re.search(r"HISTORY:", body_block)
        if history_match is not None:
            body_html = body_block[: history_match.start()]
            amendment_notes = " ".join(
                self._clean_inner(body_block[history_match.start() :]).split()
            )
        else:
            body_html = body_block
            amendment_notes = None

        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        raw_citation = f"S.C. Code § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading or None,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
