"""MaineAdapter: the Maine-specific concrete state adapter.

Source: the official Maine Legislature publication of the Maine Revised
Statutes (M.R.S.) at ``https://legislature.maine.gov/statutes/`` --
anonymous, server-rendered HTML with no authentication or API key (no SPA
framework, no client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/maine.md``,
which documents live requests to the official host):

* Base URL ``https://legislature.maine.gov`` with statutory pages under
  ``/statutes/``.
* Titles: the statutes homepage (``/statutes/homepage.html``) lists all 64
  titles as ``<li class="right_nav"><a href="1/title1ch0sec0.html">TITLE 1:
  GENERAL PROVISIONS</a></li>``. The title identifier is the href's
  directory prefix; the label is ``TITLE {id}: {name}``. 25 of 64 titles
  are lettered (``7-A``, ``13-A``, ``17-A``, ``34-B``, ``39-A``, ...).
* Chapters: a title contents page (``/statutes/{title}/title{title}ch0sec0.html``,
  e.g. ``/statutes/17-A/title17-Ach0sec0.html``) lists every chapter of the
  title as ``<div class="MRSChapter_toclist "><a href="./title17-Ach1sec0.html">
  Chapter 1: PRELIMINARY</a> §1 - §19-A</div>``, grouped under presentation-only
  ``<h2 class="heading_part">Part 1: ...</h2>`` headings (flattened; Parts
  are not a structural level). Title 17-A lists 52 chapters, including
  lettered chapters ``54-A`` ... ``54-G`` (verified).
* Sections: a chapter TOC page (``/statutes/{title}/title{title}ch{chapter}sec0.html``,
  e.g. ``/statutes/17-A/title17-Ach1sec0.html``) lists every section of the
  chapter as ``<div class="MRSSection_toclist "><a href="./title17-Asec2.html">
  17-A §2. Definitions</a> </div>``. Section identifiers may carry a letter
  suffix (``4-A``, ``9-A``, ``19-A``) or a numeric dash suffix (``18-1``).
  Repealed sections use ``<div class="MRSSection_toclist right_nav_repealed">``
  with ``(REPEALED)`` in the link text (e.g. §5, §10, §11). Chapter 1 of
  Title 17-A lists 26 sections (verified).
* Section content: ``/statutes/{title}/title{title}sec{section}.html``
  (e.g. ``/statutes/17-A/title17-Asec2.html``) -- one file per section.
  Verified structure (for § 2, § 5, and § 18-1):
  * Cross-check anchors ``<div class="MRSTitle toc">Title 17-A: MAINE
    CRIMINAL CODE</div>`` and ``<div class="MRSChapter toc">Chapter 1:
    PRELIMINARY</div>`` appear before the section content.
  * Heading ``<h3 class="heading_section">§2. Definitions</h3>`` (the
    leading ``§{n}. `` is stripped for the heading).
  * Body: ``<div class="mrs-text ...">`` and ``<div class="MRSSubSection">``
    blocks between the heading and the history block, with inline
    per-paragraph ``<span class="bhistory">[PL 1975, c. 499, §1 (NEW).]</span>``
    amendment notes (dropped from the body; consolidated in the SECTION
    HISTORY).
  * History: ``<div class="qhistory">SECTION HISTORY
    <div class="qhistory_list"><span class="hist_chapter">PL 1975, c. 499,
    §1 (NEW). PL 1975, c. 740, §11 (AMD). ...</span></div></div>``.
  * Repealed sections (e.g. § 5) replace the body with ``<div
    class="headnote_blip">(REPEALED)</div>`` and still carry a SECTION
    HISTORY. The page's ``MRSSection status_current`` class is present even
    on a repealed section, so repeal is prose-level only and ``status``
    stays ``UNKNOWN``.
  * Section 18-1 is identified by its URL file suffix (``18-1``) even
    though its listing label reads ``17-A §18.``; its citation uses the
    URL identifier (``17-A M.R.S. § 18-1``). This site-file-naming quirk is
    documented rather than normalized.
* Citation: ``{title} M.R.S. § {section}`` (e.g. ``17-A M.R.S. § 2``),
  adapter-constructed (the ``M.R.S.`` abbreviation is INFERENCE from
  standard Maine citation usage; the number is verified from the site's own
  headings). ``SectionRef.identifier`` is the section number as it appears
  in the URL (e.g. ``"2"``, ``"4-A"``, ``"18-1"``).
* Error boundary: a nonexistent title, chapter, or section returns HTTP
  404 (verified), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in ``docs/research/maine.md``):
whether a formal rate-limit policy exists; whether every one of the 64
titles' contents page and every section page renders identically (sampled
Title 17-A and its Chapters 1/5/18); and exact markup of repealed-section
listing markers beyond Title 17-A. None of these block the implementation
below.
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


class MaineAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Maine Legislature
    publication of the Maine Revised Statutes at legislature.maine.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by ``WashingtonAdapter``, ``TexasAdapter``,
    ``IllinoisAdapter``, ``VirginiaAdapter``, ``DelawareAdapter``,
    ``FloridaAdapter``, and ``SouthDakotaAdapter``. See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://legislature.maine.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A title link on the statutes homepage, e.g. '<li class="right_nav">
    # <a href="1/title1ch0sec0.html">TITLE 1: GENERAL PROVISIONS</a></li>'.
    # The backreference ensures the directory prefix equals the file
    # prefix (e.g. "7-A/title7-Ach0sec0.html"), so no other link matches.
    _TITLE_LINK = re.compile(
        r'<a href="([\w-]+)/title\1ch0sec0\.html">([^<]*)</a>'
    )
    # The label prefix, e.g. 'TITLE 1: ' / 'TITLE 39-A: '.
    _TITLE_NAME_PREFIX = re.compile(r"^TITLE\s+[\w-]+:\s*", re.IGNORECASE)

    # A chapter link on a title contents page, e.g. '<a href="./title17-Ach1sec0.html">Chapter 1: PRELIMINARY</a>'.
    # The chapter identifier is the suffix between 'ch' and 'sec0.html'
    # (e.g. "1", "54-A"). 'ch0sec0.html' (the title contents self-link on
    # chapter/section pages) never appears on the title contents page
    # itself, but the identifier "0" is excluded defensively.
    # The label prefix, e.g. 'Chapter 1: ' / 'Chapter 54-A: '.
    _CHAPTER_NAME_PREFIX = re.compile(r"^Chapter\s+[\w.-]+:\s*")
    _CHAPTER_LINK = re.compile(
        r'<a href="\./title[\w-]+ch([\w.-]+)sec0\.html">([^<]*)</a>'
    )

    # A section link on a chapter TOC page, e.g. '<a href="./title17-Asec2.html">17-A §2. Definitions</a>'.
    # The section identifier is the suffix between 'sec' and '.html'
    # (e.g. "2", "4-A", "18-1"). The label prefix, e.g. '17-A §2. ' /
    # '17-A §18. ', is built per-title (see _section_name_prefix): the
    # label uses the displayed number (e.g. "§18." for URL sec18-1), so the
    # prefix regex is anchored to the title, not the identifier.
    _SECTION_LINK = re.compile(
        r'<a href="\./title[\w-]+sec([\w.-]+)\.html">([^<]*)</a>'
    )

    # The heading on a section page, e.g. '<h3 class="heading_section">
    # §2. Definitions</h3>'.
    _HEADING_H3 = re.compile(r'<h3 class="heading_section">(.*?)</h3>', re.DOTALL)
    # The leading '§2. ' / '§18. ' token on the heading.
    _HEADING_NUMBER_PREFIX = re.compile(r"^§[\w.-]+\.\s*")
    # The history block opener on a section page.
    _QHISTORY = re.compile(r'<div class="qhistory">')
    # Inline per-paragraph amendment notes, e.g. '<span class="bhistory">
    # [PL 1975, c. 499, §1 (NEW).]</span>'.
    _BHISTORY = re.compile(r'<span class="bhistory">\[.*?\]</span>', re.DOTALL)
    # The consolidated SECTION HISTORY, e.g. '<span class="hist_chapter">
    # PL 1975, c. 499, §1 (NEW). ...</span>'.
    _HIST_CHAPTER = re.compile(r'<span class="hist_chapter">(.*?)</span>', re.DOTALL)
    # An editorial note inside a section body, e.g. '<div class="note">
    # Revisor's Note: ...</div>'.
    _NOTE_DIV = re.compile(r'<div class="note">(.*?)</div>', re.DOTALL)
    # The per-section-page cross-check anchors.
    _MRSTITLE_TOC = re.compile(r'<div class="MRSTitle toc">Title\s+([\w-]+):')
    _MRSCHAPTER_TOC = re.compile(
        r'<div class="MRSChapter toc">Chapter\s+([\w.-]+):'
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Maine."""
        return "ME"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Maine."""
        return "Maine"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Maine Legislature Statutes URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/maine.md):

        * Title: ``https://legislature.maine.gov/statutes/{title}/title{title}ch0sec0.html``
          -- the title contents page (chapter listing).
        * Chapter: ``https://legislature.maine.gov/statutes/{title}/title{title}ch{chapter}sec0.html``
          -- the chapter TOC page (section listing).
        * Section: ``https://legislature.maine.gov/statutes/{title}/title{title}sec{section}.html``
          -- the section's own page.

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
            return (
                f"{self.BASE_URL}/statutes/{title}/title{title}sec{ref.identifier}.html"
            )
        elif isinstance(ref, ChapterRef):
            title = ref.title.identifier
            return (
                f"{self.BASE_URL}/statutes/{title}/title{title}ch{ref.identifier}sec0.html"
            )
        elif isinstance(ref, TitleRef):
            return (
                f"{self.BASE_URL}/statutes/{ref.identifier}/"
                f"title{ref.identifier}ch0sec0.html"
            )
        else:
            raise UnsupportedRefError(
                f"MaineAdapter.build_url does not support refs of type "
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
        invalid title/chapter/section) into :class:`RefNotFoundError` -- the
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
                does not resolve on the Maine Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Maine Legislature site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _section_name_prefix(cls, title: str) -> re.Pattern[str]:
        """Build the section-label prefix-strip regex for ``title``."""
        return re.compile(rf"^{re.escape(title)}\s*§[\w.-]+\.\s*")

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Maine Revised Statutes from the
        statutes homepage.

        The homepage lists 64 titles, each as a ``{id}/title{id}ch0sec0.html``
        link. The identifier is the href's directory prefix (e.g. ``"17-A"``);
        the display name is the ``TITLE {id}: `` label prefix stripped. The
        result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"17-A"``) and whose
            ``name`` is the title name (e.g. ``"MAINE CRIMINAL CODE"``).

        Raises:
            AdapterUnavailableError: If the homepage cannot be fetched or
                no usable title links could be parsed from it.
        """
        url = f"{self.BASE_URL}/statutes/homepage.html"
        html = self._fetch_html(url, what="Maine statutes home page")

        titles = []
        seen: dict[str, None] = {}
        for identifier, label in self._TITLE_LINK.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            name = self._TITLE_NAME_PREFIX.sub("", label).strip() or identifier
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

        return tuple(sorted(titles, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title
        contents page.

        The title contents page lists every chapter of the title as
        ``./title{title}ch{chapter}sec0.html`` links (the ``ch0sec0.html``
        title-contents self-link is never on this page). The identifier is
        the suffix between ``ch`` and ``sec0.html`` (e.g. ``"1"``,
        ``"54-A"``); the display name is the ``Chapter {n}: `` label prefix
        stripped. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"1"``, ``"54-A"``)
            and whose ``name`` is the chapter name (e.g. ``"PRELIMINARY"``).

        Raises:
            RefNotFoundError: If ``title_ref`` returns HTTP 404 (the title
                does not resolve).
            AdapterUnavailableError: If the title contents page cannot be
                fetched for any other reason, or if no usable chapter links
                could be parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Maine chapter listing")

        chapters = []
        seen: dict[str, None] = {}
        for identifier, label in self._CHAPTER_LINK.findall(html):
            if identifier == "0" or identifier in seen:
                continue
            seen[identifier] = None
            name = self._CHAPTER_NAME_PREFIX.sub("", label).strip() or identifier
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
                f"Fetched {url!r} but found no usable chapter links in it; "
                f"title {title_ref.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        TOC page.

        The chapter TOC page lists every section of the chapter as
        ``./title{title}sec{section}.html`` links (PDF/docx and
        ``ch0sec0.html`` sidebar links are excluded by the ``sec{n}.html``
        anchor). The identifier is the suffix between ``sec`` and ``.html``
        (e.g. ``"2"``, ``"4-A"``, ``"18-1"``); the display name is the
        ``{title} §{n}. `` label prefix stripped. Repealed sections keep
        their ``(REPEALED)`` marker in the name, exactly as the site lists
        them. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per listed section, in
            numeric order. Each node's ``ref`` is a :class:`SectionRef`
            whose ``identifier`` is the section number (e.g. ``"2"``,
            ``"18-1"``) and whose ``name`` is the section's name as
            presented in the listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter TOC page cannot be
                fetched for any other reason, or if no usable section links
                could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Maine section listing")

        title = chapter_ref.title.identifier
        prefix = self._section_name_prefix(title)

        sections = []
        seen: dict[str, None] = {}
        for identifier, label in self._SECTION_LINK.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            name = prefix.sub("", label).strip() or identifier
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
                f"Fetched {url!r} but found no usable section links in it; "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} either does not resolve or "
                "the site's structure has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title/chapter/section
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any lettered/dashed suffix -- the same convention
        ``SouthDakotaAdapter`` and ``IllinoisAdapter`` use -- so ``1, 2,
        17, 18-1, 19`` and ``4-A, 9-A, 19-A`` order sensibly regardless of
        document order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Maine.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the section number, e.g. ``"2"``) appears
        verbatim within ``raw_citation`` (the ``17-A M.R.S. § 2`` citation).
        The stronger title/chapter cross-check against the source response
        happens in :meth:`retrieve_section`, which has the page's
        ``MRSTitle``/``MRSChapter`` toc anchors.

        ``status`` is always left at its default (``UNKNOWN``): the page's
        ``MRSSection status_current`` class is VERIFIED-unreliable (present
        even on a repealed section), and the contract forbids inferring
        status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Maine ref
                (``ref.state_code != "ME"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MaineAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Maine Revised Statutes section, end
        to end: :meth:`build_url` -> fetch the section page -> cross-check
        the page's ``MRSTitle``/``MRSChapter`` toc anchors against ``ref``
        -> parse the section page into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/maine.md): the heading is a
        ``<h3 class="heading_section">`` (the ``§{n}. `` prefix is stripped);
        the body is the region between the heading and the ``qhistory``
        history block, with inline ``bhistory`` per-paragraph amendment
        notes dropped (their content is consolidated in the SECTION
        HISTORY); ``amendment_notes`` is the ``hist_chapter`` span text;
        any editorial ``<div class="note">`` (e.g. Revisor's Notes) is
        appended to ``amendment_notes``. The section page's
        ``MRSTitle``/``MRSChapter`` toc anchors are cross-checked against
        ``ref.chapter.title``/``ref.chapter`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed.

        Args:
            ref: The section to retrieve. Must be a Maine ref
                (``ref.state_code == "ME"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the page's ``MRSTitle``/``MRSChapter`` toc
                anchors disagree with ``ref``. Also raised by
                :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but required
                structure (heading, body, toc anchors) is missing, or the
                body is empty after cleaning. Also raised by
                :meth:`normalize` if ``ref`` is not a Maine ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Maine section page")

        title_toc = self._MRSTITLE_TOC.search(html)
        if title_toc is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no MRSTitle "
                "toc anchor; the site's structure may have changed."
            )
        if title_toc.group(1) != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section page: "
                f"{title_toc.group(1)!r}."
            )

        chapter_toc = self._MRSCHAPTER_TOC.search(html)
        if chapter_toc is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no MRSChapter "
                "toc anchor; the site's structure may have changed."
            )
        if chapter_toc.group(1) != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section page: "
                f"{chapter_toc.group(1)!r}."
            )

        heading_h3 = self._HEADING_H3.search(html)
        if heading_h3 is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the section page contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._HEADING_NUMBER_PREFIX.sub(
            "", self._clean_inner(heading_h3.group(1))
        ).strip() or None

        body_html = html[heading_h3.end() :]
        qhistory = self._QHISTORY.search(body_html)
        if qhistory is not None:
            body_html = body_html[: qhistory.start()]

        note = self._NOTE_DIV.search(body_html)
        note_text = None
        if note is not None:
            note_text = self._clean_inner(note.group(1))
            body_html = body_html[: note.start()] + body_html[note.end() :]

        body_html = self._BHISTORY.sub(" ", body_html)
        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        history = self._HIST_CHAPTER.search(html)
        if history is not None:
            amendment_notes = self._clean_inner(history.group(1)) or None
        if note_text:
            amendment_notes = (
                f"{amendment_notes}\n{note_text}" if amendment_notes else note_text
            )

        raw_citation = f"{ref.chapter.title.identifier} M.R.S. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)