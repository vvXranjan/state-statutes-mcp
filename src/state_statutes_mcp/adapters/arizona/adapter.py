"""ArizonaAdapter: the Arizona-specific concrete state adapter.

Source: the official Arizona Legislature publication of the Arizona
Revised Statutes (A.R.S.) at ``https://www.azleg.gov`` -- anonymous,
server-rendered HTML with no authentication or API key (no SPA framework,
no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/arizona.md``,
which documents live requests to the official host):

* Base URL ``https://www.azleg.gov``.
* Titles: the title list page (``/arstitle/``) lists 47 linked titles
  (Title 1 through 49, minus repealed Titles 2 and 24, each without a
  link). The title identifier is the title number (e.g. ``"28"``); the
  label is the title heading (e.g. ``"Motor Vehicle Act"``).
* Title detail: ``/arsDetail/?title={N}`` (trailing slash required; the
  no-slash form 301-redirects) lists every chapter and section of the
  title as ``<div id="chapter{N}" class="accordion">`` blocks. Chapter
  identifiers are the accordion's numeric id (e.g. ``"1"``); chapter
  names come from the ``.two-thirds`` div (e.g. ``"DEFINITIONS, PENALTIES
  AND GENERAL PROVISIONS"``). Sections appear as ``<li class="colleft">``
  (link, whose label is the full ``{title}-{section}`` citation) +
  ``<li class="colright">`` (name) pairs. Chapters have no page of their
  own (empty ``href``), so they are only discoverable from the title
  detail page.
* Sections: ``https://www.azleg.gov/ars/{title}/{file}.htm`` -- one clean
  file per section (e.g. ``/ars/28/00101.htm``). File name rule: the
  section's local number (after the title dash) is split; the base is
  zero-padded to 5 digits and, for compound sections, a ``-{suffix}`` is
  appended: ``28-101`` -> ``00101.htm``, ``28-622.01`` -> ``00622-01.htm``.
  ``SectionRef.identifier`` is the full ``{title}-{section}`` form (e.g.
  ``"28-101"``, ``"28-622.01"``), matching the citation.
* Section content (verified for ``28-101`` and ``28-622.01``): the heading
  paragraph is ``<p><font color=GREEN>28-101.</font> <font color=PURPLE><u>
  Definitions</u></font></p>`` (the citation number is the GREEN text, a
  trailing period may be inside or outside the font; the heading is the
  PURPLE underlined text). The body is plain ``<p>`` paragraphs following
  the heading. There is no history/amendment line on Arizona section
  pages.
* Citation: ``A.R.S. § {title}-{section}`` (e.g. ``A.R.S. § 28-101``),
  adapter-constructed (the ``A.R.S.`` abbreviation is INFERENCE from
  standard Arizona citation usage; the number is VERIFIED from the site's
  own heading text).
* Error boundary: a missing section file or missing title returns HTTP 404
  (verified), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/arizona.md``):
whether every title detail page keeps the same accordion markup and every
section page the same heading shape (sampled Titles 1 and 28; sections
28-101 and 28-622.01); the compound-section file naming rule is verified
only for ``28-622.01`` and is otherwise INFERENCE. None of these block the
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


class ArizonaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Arizona Legislature
    publication of the Arizona Revised Statutes at azleg.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://www.azleg.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A linked title row on /arstitle/, e.g. '<td><a href="https://www.azleg.gov/arsDetail?title=1">Title 1</a></td><td>General Provision</td>'.
    _TITLE_ROW = re.compile(
        r'<td>\s*<a href="[^"]*arsDetail\?title=(\d+)">[^<]*</a>\s*</td>\s*<td>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    # A chapter accordion opener on the title detail page, e.g. '<div id="chapter1" class="accordion">'.
    _CHAPTER_ACCORDION = re.compile(
        r'<div id="chapter(\d+)" class="accordion">',
        re.IGNORECASE,
    )
    # The chapter heading inside an accordion, e.g. '<div class="two-thirds">DEFINITIONS, PENALTIES AND GENERAL PROVISIONS</div>'.
    _CHAPTER_NAME_DIV = re.compile(
        r'<div class="two-thirds">(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )

    # A section pair inside an accordion: '<li class="colleft"><a ... href="/viewdocument/?docName=https://www.azleg.gov/ars/28/00101.htm">28-101</a></li><li class="colright"> Definitions </li>'.
    _SECTION_PAIR = re.compile(
        r'<li class="colleft">.*?/ars/\d+/[^/]+\.htm"[^>]*>\s*([^<]+?)\s*</a>.*?</li>\s*'
        r'<li class="colright">(.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )

    # The section heading paragraph on a section page, e.g. '<p><font color=GREEN>28-101.</font> <font color=PURPLE><u>Definitions</u></font></p>'.
    _HEADING_P = re.compile(
        r"<p><font color=GREEN>(.*?)</font>[^<]*<font color=PURPLE><u>(.*?)</u></font></p>",
        re.IGNORECASE | re.DOTALL,
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Arizona."""
        return "AZ"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Arizona."""
        return "Arizona"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    @staticmethod
    def _section_filename(identifier: str) -> str:
        """Derive the official section file name from ``identifier``.

        ``identifier`` is the full ``{title}-{section}`` citation (e.g.
        ``"28-622.01"``). The local part after the title dash is split on
        ``.``: the base is zero-padded to 5 digits and a ``-{suffix}`` is
        appended for compound sections -- ``28-101`` -> ``00101.htm``,
        ``28-622.01`` -> ``00622-01.htm``. VERIFIED against the live site
        for both shapes.

        Args:
            identifier: The section's full ``{title}-{section}`` citation.

        Returns:
            The section file name (e.g. ``"00101.htm"``).
        """
        local = identifier.split("-", 1)[1]
        base, _, suffix = local.partition(".")
        if suffix:
            return f"{base.zfill(5)}-{suffix}.htm"
        return f"{base.zfill(5)}.htm"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Arizona Legislature URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/arizona.md):

        * Title: ``https://www.azleg.gov/arsDetail/?title={N}`` -- the
          title detail page (chapter/section listing).
        * Chapter: same title detail page -- chapters have no page of
          their own (their links' ``href`` is empty), so the title detail
          page that contains them is the closest real resource.
        * Section: ``https://www.azleg.gov/ars/{title}/{file}.htm`` --
          the section's own page, where ``{file}`` follows
          :meth:`_section_filename`.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            title = ref.chapter.title.identifier
            return f"{self.BASE_URL}/ars/{title}/{self._section_filename(ref.identifier)}"
        elif isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/arsDetail/?title={ref.title.identifier}"
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/arsDetail/?title={ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"ArizonaAdapter.build_url does not support refs of type "
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
        invalid title or section) into :class:`RefNotFoundError` -- the
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
                does not resolve on the Arizona Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Arizona Legislature site."
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
        """Enumerate every title of the Arizona Revised Statutes from the
        title list page.

        The ``/arstitle/`` page lists every title as a table row with a
        linked ``arsDetail?title={N}`` anchor and a title heading. Repealed
        titles (e.g. Title 2) carry no link and the "All" search row has no
        ``arsDetail`` anchor, so both are naturally excluded.

        Returns:
            A sequence of :class:`TocNode`, one per linked title, in
            document order. Each node's ``ref`` is a :class:`TitleRef`
            whose ``identifier`` is the title number (e.g. ``"28"``).

        Raises:
            AdapterUnavailableError: If the title list page cannot be
                fetched or no usable title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/arstitle/"
        html = self._fetch_html(url, what="Arizona title list")

        titles = []
        seen: set[str] = set()
        for identifier, raw_name in self._TITLE_ROW.findall(html):
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
                f"Fetched {url!r} but found no usable title rows in it; the "
                "site's structure may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title
        detail page.

        The title detail page (``/arsDetail/?title={N}``) lists every
        chapter as a ``<div id="chapter{N}" class="accordion">`` block. The
        identifier is the accordion's numeric id; the display name is the
        chapter heading from the ``.two-thirds`` div.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title detail page cannot be
                fetched for any other reason, or if no usable chapter
                accordions could be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Arizona chapter listing")

        chapters = []
        seen: set[str] = set()
        for accordion in self._CHAPTER_ACCORDION.finditer(html):
            identifier = accordion.group(1)
            if identifier in seen:
                continue
            seen.add(identifier)
            name_match = self._CHAPTER_NAME_DIV.search(html, accordion.end())
            name = (
                " ".join(self._clean_inner(name_match.group(1)).split())
                if name_match is not None
                else identifier
            )
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
                f"Fetched {url!r} but found no usable chapter accordions in "
                f"it; title {title_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the title
        detail page.

        Chapters have no page of their own, so sections are read from the
        title detail page that contains them. Each chapter's sections live
        in its ``<div id="chapter{N}" class="accordion">`` block; within
        that block, each section is a ``colleft`` (link whose label is the
        full ``{title}-{section}`` citation) + ``colright`` (name) ``<li>``
        pair. Scoping the parse to the specific accordion block keeps this
        from picking up other chapters' sections.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{title}-{section}`` citation.

        Raises:
            AdapterUnavailableError: If the title detail page cannot be
                fetched for any reason, or if no usable section pairs could
                be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Arizona section listing")

        # Locate the specific chapter's accordion block.
        pattern = re.compile(
            rf'<div id="chapter{re.escape(chapter_ref.identifier)}" class="accordion">',
            re.IGNORECASE,
        )
        block_match = pattern.search(html)
        if block_match is None:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no accordion block for chapter "
                f"{chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r}; the site's structure has "
                "changed."
            )
        block_end = len(html)
        next_block = self._CHAPTER_ACCORDION.search(html, block_match.end())
        if next_block is not None:
            block_end = next_block.start()
        block_html = html[block_match.end() : block_end]

        sections = []
        seen: set[str] = set()
        for identifier, raw_name in self._SECTION_PAIR.findall(block_html):
            identifier = identifier.strip()
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
                f"Fetched {url!r} and found chapter {chapter_ref.identifier!r} "
                "but no usable section pairs in its accordion block; the "
                "site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Arizona.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full
        ``{title}-{section}`` citation, e.g. ``"28-101"``) must appear
        verbatim within ``parsed.raw_citation`` (the ``A.R.S. § 28-101``
        citation). The stronger citation-number cross-check against the
        source response happens in :meth:`retrieve_section`, which parses
        the page's own heading number.

        ``status`` is always left at its default (``UNKNOWN``): Arizona
        section pages carry no structural repealed/amended/renumbered
        signal observed in this milestone, and the contract explicitly
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Arizona ref
                (``ref.state_code != "AZ"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"ArizonaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Arizona Revised Statutes section,
        end to end: :meth:`build_url` -> fetch the section page ->
        cross-check the page's own citation number against ``ref`` -> parse
        the section page into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/arizona.md): the heading
        paragraph is ``<p><font color=GREEN>{num}</font> <font color=PURPLE>
        <u>{heading}</u></font></p>`` where ``{num}`` is the citation number
        (a trailing period may be inside or outside the ``<font>``) and the
        heading is the PURPLE underlined text; the body is the plain ``<p>``
        paragraphs following the heading. There is no history line, so
        ``amendment_notes`` stays ``None``. The page's own citation number
        is cross-checked against ``ref.identifier`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be an Arizona ref
                (``ref.state_code == "AZ"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's citation number disagrees with
                ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body) is missing, or the body is empty
                after cleaning. Also raised by :meth:`normalize` if ``ref``
                is not an Arizona ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Arizona section page")

        heading_p = self._HEADING_P.search(html)
        if heading_p is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no heading "
                "paragraph; the site's structure may have changed."
            )
        citation_number = heading_p.group(1).strip().rstrip(".")
        if citation_number != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation number in the fetched section page: "
                f"{citation_number!r}."
            )

        heading = " ".join(heading_p.group(2).split()) or None

        body_html = html[heading_p.end() :]
        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        raw_citation = f"A.R.S. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=None,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
