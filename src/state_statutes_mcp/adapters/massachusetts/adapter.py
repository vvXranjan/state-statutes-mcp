"""MassachusettsAdapter: the Massachusetts-specific concrete state adapter.

Source: the official Massachusetts General Laws at
``https://malegislature.gov/Laws/GeneralLaws`` -- anonymous, server-rendered
HTML with no authentication or API key. ``malegislature.gov`` is the official
statute host of the General Court of the Commonwealth of Massachusetts.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/massachusetts.md``;
all structures verified against real captures of the official host, taken via
the ``r.jina.ai`` proxy with ``X-Return-Format: html`` on Aug 20 2026 --
``malegislature.gov`` does not accept direct sockets from this environment):

* Base URL ``https://malegislature.gov``.
* Discovery:
  * The General Laws page ``{BASE}/Laws/GeneralLaws`` lists the five Parts of
    the General Laws as one row per part:
    ``<li><a href="/Laws/GeneralLaws/PartI"><span class="part">Part I</span>
    <span class="partTitle">ADMINISTRATION OF THE GOVERNMENT</span>
    <span class="chapters">Chapters. 1-182</span></a></li>``. ``list_titles``
    derives ``TitleRef``s by fetching the General Laws page, then one page per
    Part, and reading the title panels off each Part page (6 fetches in all).
  * Each Part page (``{BASE}/Laws/GeneralLaws/Part{roman}``) statically lists
    its titles as accordion panels, one per title:
    ``<div id="Ititle" class="panel panel-default">`` with two anchors that
    both carry ``onclick="accordionAjaxLoad('1', '1', 'I')"`` -- the short
    label (``Title I``) and the descriptive name (``JURISDICTION AND EMBLEMS
    OF THE COMMONWEALTH, THE GENERAL COURT, STATUTES AND PUBLIC DOCUMENTS``).
    The descriptive-name anchor is uniquely the one inside
    ``<h4 class="panel-title">``.
  * Chapters are lazy-loaded through an internal AJAX endpoint --
    ``{BASE}/Laws/GeneralLaws/GetChaptersForTitle?partId={n}&titleId={m}&code={roman}``
    -- which returns one ``<li>`` per chapter:
    ``<span class="chapter">Chapter 6A</span>`` +
    ``<span class="chapterTitle">NAME</span>``. Repealed chapters are not
    marked specially; every chapter row is a normal chapter link.
  * Sections are listed statically on each chapter page
    (``{BASE}/Laws/GeneralLaws/Part{roman}/Title{roman}/Chapter{n}``):
    one ``<li>`` per section with ``<span class="section">Section 7</span>`` +
    ``<span class="sectionTitle">NAME</span>``. The TOC treats ALL entries
    uniformly, including repealed individual sections (``Section 1`` of
    chapter 186 is listed with the title ``Repealed, 2008, 521, Sec. 5``),
    repealed ranges (``Section 160 to 168A``), fractions (``Section 6 1/2``)
    and multi-part entries (``Section 44K, 44L``). This deliberately
    supersedes the B12 brief's claim that range entries have no normal
    section page -- every one of these entries VERIFIED to resolve to a
    working section page (see URL construction below).
* Global title identifiers. The Part pages use a single, GLOBAL ``titleId``
  counter across ALL five Parts (VERIFIED on all 34 titles): Part I holds
  titleIds 1-22, Part II 23-25, Part III 26-31, Part IV 32-33, Part V 34.
  ``titleId = offset(part) + position(title-within-part)`` where the offsets
  come from the VERIFIED per-part title counts
  ``{"I": 22, "II": 3, "III": 6, "IV": 2, "V": 1}`` (``_PART_TITLE_COUNTS``).
  ``TitleRef.identifier`` is ``"Part {part} Title {title}"`` (e.g. ``"Part I
  Title I"``), unique across parts and parseable. ``build_url(TitleRef)``
  returns the Part page that contains the title (the closest real document;
  ``list_chapters`` uses the AJAX endpoint instead).
* URL construction (all VERIFIED against real captures):
  * Chapter/section pages live at
    ``{BASE}/Laws/GeneralLaws/Part{part}/Title{title}/Chapter{n}`` and
    ``.../Chapter{n}/Section{slug}`` where ``{slug}`` is the section
    identifier with ``/`` encoded as ``~`` and the rest URL-quoted:
    ``"7"`` -> ``Section7``, ``"7A"`` -> ``Section7A``, ``"6 1/2"`` ->
    ``Section6%201~2``, ``"160 to 168A"`` -> ``Section160%20to%20168A``,
    ``"44K, 44L"`` -> ``Section44K,%2044L``. Lettered chapters address the
    same way (``Chapter6A``).
  * Fractional identifiers use a ``~`` for the slash: ``6 1/2`` is stored in
    the URL as ``Section6%201~2`` (VERIFIED). The slash-to-tilde substitution
    happens BEFORE URL quoting.
* Section page structure: the operative heading is
  ``<h2 id="skipTo" class="h3 genLawHeading hidden-print">Section 7: <small>
  Definitions of statutory terms;  statutory construction</small></h2>``
  followed by an empty spacer ``<p>`` and then the body paragraphs
  ``<p>&#160;&#160;Section 7. In construing statutes ...</p>``. The caption
  becomes ``heading`` and the cleaned body paragraphs (excluding the empty
  spacer) become ``text``. There is NO history/amendment text anywhere on
  the section pages (VERIFIED on several pages), so ``amendment_notes`` is
  always ``None``. A repealed or amended-into-a-special-act section renders
  its status only as prose in the caption (``Repealed, 2008, 521, Sec. 5``;
  ``Amended by 1931, 394, Sec. 182 into a special act``) with an empty body.
  Per the framework rule (a prose-only repeal signal with an empty body,
  same decision as NebraskaAdapter), such sections are returned with
  ``status=UNKNOWN``, the caption as ``heading``, ``text=""`` and
  ``amendment_notes=None`` -- an empty body is a legitimate stub, not a
  normalization error.
* Soft-404s. A nonexistent chapter (``Chapter9999``), section
  (``Section9999``) or title returns HTTP 200 with
  ``<title>404 - Page Not Found</title>`` / ``<h1>404 - Page Not Found</h1>``
  in the body (VERIFIED on all three). ``_fetch_html`` detects this content
  marker and maps it to ``RefNotFoundError``; a genuine HTTP 404 maps to
  ``RefNotFoundError`` through the shared ``fetch_url`` helper. Titles beyond
  a part's verified title count (e.g. ``Part I Title XXIII``) are rejected
  up front with ``RefNotFoundError`` by the ``_title_id`` helper.
* Citation: ``G.L. c. {chapter}, § {section}`` (lettered sections keep their
  letter, e.g. ``G.L. c. 4, § 7A``).
* Encoding: UTF-8 throughout, so the shared UTF-8 ``fetch_url`` helper is
  used directly.
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
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus


class MassachusettsAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Massachusetts General Laws at
    malegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The General Laws map onto
    the framework's three-level ref model as Part -> Chapter -> Section,
    with the Part->Title relationship flattened: ``TitleRef.identifier`` is
    ``"Part {part} Title {title}"``. See the module docstring.
    """

    BASE_URL = "https://malegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Per-part title counts, VERIFIED on all 34 titles (Aug 20 2026). The
    # Part pages use a single GLOBAL titleId counter across all five Parts
    # (Part I: 1-22, Part II: 23-25, Part III: 26-31, Part IV: 32-33,
    # Part V: 34), so the offsets below let us derive a title's global id
    # arithmetically from its (part, roman title) position.
    _PART_TITLE_COUNTS: dict[str, int] = {
        "I": 22,
        "II": 3,
        "III": 6,
        "IV": 2,
        "V": 1,
    }

    # The Parts in document order, used to compute the titleId offsets.
    _PARTS_IN_ORDER: tuple[str, ...] = ("I", "II", "III", "IV", "V")

    # A part row on the General Laws index page, e.g.
    # '<li><a href="/Laws/GeneralLaws/PartI"><span class="part">Part I</span>
    #  <span class="partTitle">ADMINISTRATION OF THE GOVERNMENT</span> ...'.
    _PART_ROW = re.compile(
        r'<a href="/Laws/GeneralLaws/Part([IVXLCDM]+)"[^>]*>\s*'
        r'<span class="part">Part \1</span>\s*'
        r'<span class="partTitle">(.*?)</span>',
        re.DOTALL,
    )

    # A title's descriptive-name anchor on a Part page. Each title panel has
    # three anchors with the same onclick (the short label, the descriptive
    # name, and the chapter range); the descriptive name is uniquely the
    # anchor inside '<h4 class="panel-title">'. The onclick gives the
    # (partId, global titleId, roman title code).
    _TITLE_ROW = re.compile(
        r'<h4 class="panel-title">\s*<a[^>]*onclick="accordionAjaxLoad\(\''
        r"(\d+)',\s*'(\d+)',\s*'([A-Z]+)'\)\"[^>]*>(.*?)</a>",
        re.DOTALL,
    )

    # A chapter row in the AJAX GetChaptersForTitle response, e.g.
    # '<span class="chapter">Chapter 6A</span>
    #  <span class="chapterTitle">BANKS AND BANKING</span>'.
    _CHAPTER_ROW = re.compile(
        r'<span class="chapter">Chapter ([^<]+)</span>\s*'
        r'<span class="chapterTitle">(.*?)</span>',
        re.DOTALL,
    )

    # A section row on a chapter page, e.g. '<span class="section">Section
    # 7</span> <span class="sectionTitle">Definitions of statutory terms;
    # statutory construction</span>'. Range/fraction/multi entries ("160 to
    # 168A", "6 1/2", "44K, 44L") are captured by the same pattern.
    _SECTION_ROW = re.compile(
        r'<span class="section">Section ([^<]+)</span>\s*'
        r'<span class="sectionTitle">(.*?)</span>',
        re.DOTALL,
    )

    # The operative heading on a section page, e.g. '<h2 id="skipTo"
    # class="h3 genLawHeading hidden-print">Section 7: <small>Definitions of
    # statutory terms;  statutory construction</small></h2>'.
    _HEADING = re.compile(
        r"<h2[^>]*genLawHeading[^>]*>\s*Section ([^:]+):\s*<small>(.*?)</small>",
        re.DOTALL,
    )

    # A body paragraph on a section page (all statute text is <p> blocks in
    # <main> after the heading; the empty spacer <p> cleans to "" and is
    # filtered out).
    _BODY_PARAGRAPH = re.compile(r"<p>(?:(?!</p>).)*?</p>", re.DOTALL)

    # The content marker of a soft-404 (VERIFIED: a nonexistent chapter,
    # section or title returns HTTP 200 whose body contains both a <title>
    # and an <h1> reading "404 - Page Not Found").
    _NOT_FOUND_MARKER = re.compile(r"404\s*-\s*Page Not Found", re.IGNORECASE)

    # A TitleRef identifier, e.g. "Part I Title I", "Part II Title I",
    # "Part IV Title II".
    _TITLE_IDENTIFIER = re.compile(r"^Part ([IVXLCDM]+) Title ([IVXLCDM]+)$")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Massachusetts."""
        return "MA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Massachusetts."""
        return "Massachusetts"

    # ------------------------------------------------------------
    # Roman-numeral and title-identifier helpers
    # ------------------------------------------------------------

    _ROMAN_VALUES: dict[str, int] = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
        "C": 100,
        "D": 500,
        "M": 1000,
    }

    @classmethod
    def _roman_to_int(cls, roman: str) -> int:
        """Convert an uppercase Roman numeral to an integer (``"I"`` -> 1,
        ``"XXII"`` -> 22). Returns 0 for anything that is not a valid Roman
        numeral of the magnitude this adapter uses."""
        if not roman or any(c not in cls._ROMAN_VALUES for c in roman):
            return 0
        total = 0
        for index, char in enumerate(roman):
            value = cls._ROMAN_VALUES[char]
            if index + 1 < len(roman) and cls._ROMAN_VALUES[roman[index + 1]] > value:
                total -= value
            else:
                total += value
        return total

    @classmethod
    def _int_to_roman(cls, value: int) -> str:
        """Convert a small integer to an uppercase Roman numeral (1 -> "I",
        5 -> "V"). Returns "" for anything outside 1-3999."""
        if not 1 <= value <= 3999:
            return ""
        numerals = [
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
        ]
        result = []
        for numeral, symbol in numerals:
            while value >= numeral:
                result.append(symbol)
                value -= numeral
        return "".join(result)

    def _parse_title_identifier(
        self, identifier: str, *, what: str
    ) -> tuple[str, str]:
        """Parse a ``"Part {part} Title {title}"`` identifier into its
        ``(part, title)`` Roman numerals.

        Raises:
            UnsupportedRefError: If ``identifier`` is not the
                ``"Part {part} Title {title}"`` form, or if ``part`` is not
                one of the five verified Parts of the General Laws.
        """
        match = self._TITLE_IDENTIFIER.match(identifier)
        if match is None:
            raise UnsupportedRefError(
                f"MassachusettsAdapter cannot address {what}: expected a "
                f"'Part {{part}} Title {{title}}' identifier like 'Part I "
                f"Title I', got {identifier!r}."
            )
        part, title = match.groups()
        if part not in self._PART_TITLE_COUNTS:
            raise UnsupportedRefError(
                f"MassachusettsAdapter cannot address {what}: {part!r} is not "
                "one of the five verified Parts of the General Laws (I-V)."
            )
        return part, title

    def _title_id(self, part: str, title: str, *, what: str) -> int:
        """Resolve the GLOBAL titleId of the ``(part, title)`` pair, e.g.
        ``("II", "I")`` -> 23, ``("I", "XXII")`` -> 22.

        The titleId counter is global across all five Parts (VERIFIED on all
        34 titles): it is the sum of the title counts of every preceding Part
        plus the title's position within its own Part.

        Raises:
            RefNotFoundError: If the title's position exceeds the verified
                number of titles in its Part (the title does not exist).
        """
        position = self._roman_to_int(title)
        count = self._PART_TITLE_COUNTS[part]
        if position < 1 or position > count:
            raise RefNotFoundError(
                f"Could not resolve {what}: Part {part} Title {title} does "
                f"not exist; Part {part} has {count} title(s)."
            )
        offset = 0
        for earlier in self._PARTS_IN_ORDER:
            if earlier == part:
                break
            offset += self._PART_TITLE_COUNTS[earlier]
        return offset + position

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Massachusetts General Laws URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/massachusetts.md):

        * Section: ``{BASE}/Laws/GeneralLaws/Part{part}/Title{title}/
          Chapter{chapter}/Section{slug}`` where ``{slug}`` is the section
          identifier with ``/`` encoded as ``~`` and the rest URL-quoted
          (``"6 1/2"`` -> ``Section6%201~2``, ``"160 to 168A"`` ->
          ``Section160%20to%20168A``).
        * Chapter: ``{BASE}/Laws/GeneralLaws/Part{part}/Title{title}/
          Chapter{chapter}`` -- the chapter's section-listing page.
        * Title: ``{BASE}/Laws/GeneralLaws/Part{part}`` -- the Part page that
          contains the title (the closest real document; chapter listing is
          done through the AJAX endpoint, not this URL).

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref``'s title identifier is not the
                ``"Part {part} Title {title}"`` form, or names a Part that is
                not one of the five verified Parts of the General Laws.
        """
        if isinstance(ref, SectionRef):
            part, title = self._parse_title_identifier(
                ref.chapter.title.identifier, what=f"section {ref.identifier!r}"
            )
            slug = urllib.parse.quote(ref.identifier.replace("/", "~"))
            return (
                f"{self.BASE_URL}/Laws/GeneralLaws/Part{part}/Title{title}/"
                f"Chapter{ref.chapter.identifier}/Section{slug}"
            )
        elif isinstance(ref, ChapterRef):
            part, title = self._parse_title_identifier(
                ref.title.identifier, what=f"chapter {ref.identifier!r}"
            )
            return (
                f"{self.BASE_URL}/Laws/GeneralLaws/Part{part}/Title{title}/"
                f"Chapter{ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            part, title = self._parse_title_identifier(
                ref.identifier, what=f"title {ref.identifier!r}"
            )
            return f"{self.BASE_URL}/Laws/GeneralLaws/Part{part}"
        else:
            raise UnsupportedRefError(
                f"MassachusettsAdapter.build_url does not support refs of "
                f"type {type(ref).__name__!r}."
            )

    def _chapters_url(self, title_ref: TitleRef) -> str:
        """Construct the AJAX endpoint that lists a title's chapters.

        The Part pages lazy-load their chapter lists through the internal
        ``GetChaptersForTitle`` endpoint, keyed by the numeric Part id, the
        GLOBAL titleId, and the title's Roman numeral:
        ``.../GetChaptersForTitle?partId={partId}&titleId={titleId}&code={title}``
        (VERIFIED against real responses for Part I Titles I and II).

        Raises:
            UnsupportedRefError: If ``title_ref``'s identifier is not the
                ``"Part {part} Title {title}"`` form.
            RefNotFoundError: If the title does not exist (its position
                exceeds the Part's verified title count).
        """
        part, title = self._parse_title_identifier(
            title_ref.identifier, what="title listing"
        )
        title_id = self._title_id(part, title, what="title listing")
        part_id = self._roman_to_int(part)
        return (
            f"{self.BASE_URL}/Laws/GeneralLaws/GetChaptersForTitle"
            f"?partId={part_id}&titleId={title_id}&code={title}"
        )

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into
        ``AdapterUnavailableError`` there. This method additionally maps a
        document that does not resolve into :class:`RefNotFoundError`, two
        ways: (a) a genuine HTTP 404 from ``fetch_url``, and (b) the
        site's soft-404 -- a nonexistent chapter, section or title returns
        HTTP 200 whose body carries a ``404 - Page Not Found`` title/h1
        (VERIFIED on all three forms). Other network failures map to
        ``AdapterUnavailableError`` by project convention.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than an HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 or a soft-404
                body (the document does not resolve on the Massachusetts
                General Laws site).
        """
        try:
            html = fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Massachusetts General "
                    "Laws site."
                ) from exc
            raise
        if self._NOT_FOUND_MARKER.search(html):
            raise RefNotFoundError(
                f"Could not fetch the {what} at {url!r}: the page did not "
                "resolve (the Massachusetts General Laws site returned its "
                "404 - Page Not Found page)."
            )
        return html

    @classmethod
    def _clean(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return " ".join(strip_tags(html_fragment).split())

    @classmethod
    def _clean_row_name(cls, html_fragment: str) -> str:
        """Clean a row's name cell: strip tags and collapse whitespace."""
        return cls._clean(html_fragment)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the General Laws from the General Laws
        index page and the five Part pages.

        The General Laws index page lists the five Parts; each Part page
        statically lists its titles as accordion panels. Each title node's
        ``identifier`` is the site-independent ``"Part {part} Title {title}"``
        form (e.g. ``"Part I Title I"``) and its name is the descriptive
        title name (e.g. ``JURISDICTION AND EMBLEMS OF THE COMMONWEALTH, THE
        GENERAL COURT, STATUTES AND PUBLIC DOCUMENTS``).

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order (Part I titles, then Part II, ...). Each node's ``ref`` is
            a :class:`TitleRef` whose ``identifier`` is the
            ``"Part {part} Title {title}"`` form.

        Raises:
            AdapterUnavailableError: If the index page or any Part page
                cannot be fetched, or if no usable Part/title rows could be
                parsed.
        """
        url = f"{self.BASE_URL}/Laws/GeneralLaws"
        html = self._fetch_html(url, what="Massachusetts General Laws index")

        parts = self._PART_ROW.findall(html)
        if not parts:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable Part rows in it; the "
                "site's structure may have changed."
            )

        titles = []
        for part, _part_name in parts:
            part_url = f"{self.BASE_URL}/Laws/GeneralLaws/Part{part}"
            part_html = self._fetch_html(
                part_url, what=f"Massachusetts Part {part} page"
            )
            rows = self._TITLE_ROW.findall(part_html)
            if not rows:
                raise AdapterUnavailableError(
                    f"Fetched {part_url!r} but found no usable title rows in "
                    "it; the site's structure may have changed."
                )
            for part_id, _title_id, title_code, raw_name in rows:
                if self._int_to_roman(int(part_id)) != part:
                    raise AdapterUnavailableError(
                        f"Fetched {part_url!r} but a title row reported an "
                        f"inconsistent Part id {part_id!r}; the site's "
                        "structure may have changed."
                    )
                identifier = f"Part {part} Title {title_code}"
                name = self._clean_row_name(raw_name)
                titles.append(
                    TocNode(
                        level=HierarchyLevel.TITLE,
                        identifier=identifier,
                        name=name,
                        ref=TitleRef(
                            state_code=self.state_code, identifier=identifier
                        ),
                    )
                )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` through the Part
        page's AJAX chapter-listing endpoint.

        Each chapter row carries ``Chapter {number}`` and the chapter name.
        Repealed chapters are not marked specially and every row is a normal
        chapter link (VERIFIED: Title II of Part I lists 87 chapters
        including ``6A`` and ``28A``).

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            UnsupportedRefError: If ``title_ref``'s identifier is not the
                ``"Part {part} Title {title}"`` form.
            RefNotFoundError: If the title does not exist (its position
                exceeds the Part's verified title count), or if the chapter
                listing does not resolve.
            AdapterUnavailableError: If the chapter listing cannot be
                fetched for any other reason, or if no usable chapter rows
                could be parsed from it.
        """
        url = self._chapters_url(title_ref)
        html = self._fetch_html(url, what="Massachusetts chapter listing")

        chapters = []
        seen: set[str] = set()
        for number, raw_name in self._CHAPTER_ROW.findall(html):
            identifier = self._clean(number)
            if identifier in seen:
                continue
            seen.add(identifier)
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=self._clean_row_name(raw_name),
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter rows in it; "
                "the site's structure may have changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter's
        section-listing page.

        The chapter page lists its sections statically, one row per section.
        All entries are treated uniformly, including repealed individual
        sections (``Section 1`` of chapter 186 carries the name ``Repealed,
        2008, 521, Sec. 5``), repealed ranges (``Section 160 to 168A``),
        fractions (``Section 6 1/2``) and multi-part entries (``Section 44K,
        44L``) -- every one of these VERIFIED to resolve to a working
        section page, so no entry is filtered.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section number.

        Raises:
            UnsupportedRefError: If ``chapter_ref``'s title identifier is
                not the ``"Part {part} Title {title}"`` form.
            RefNotFoundError: If the chapter page does not resolve.
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section rows could be
                parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Massachusetts section listing")

        sections = []
        seen: set[str] = set()
        for number, raw_name in self._SECTION_ROW.findall(html):
            identifier = self._clean(number)
            if identifier in seen:
                continue
            seen.add(identifier)
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=self._clean_row_name(raw_name),
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section rows in it; "
                f"chapter {chapter_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Massachusetts.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the section number, e.g.
        ``"7"`` or ``"6 1/2"``) must appear verbatim within
        ``parsed.raw_citation`` (the ``G.L. c. {chapter}, § {section}``
        citation). The stronger cross-check against the source page's own
        heading happens in :meth:`retrieve_section`.

        ``status`` is always ``UNKNOWN``: the site signals repealed and
        amended-into-a-special-act sections only as prose in the heading
        caption (``Repealed, 2008, 521, Sec. 5``) with an empty body -- the
        framework's rule (same decision as NebraskaAdapter) is that a prose
        repeal signal is not a structural marker, so the status is not
        inferred from prose. An empty body is a legitimate stub, not an
        error.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Massachusetts ref
                (``ref.state_code != "MA"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MassachusettsAdapter.normalize cannot normalize a ref for "
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
        """Retrieve and normalize one Massachusetts General Laws section,
        end to end: :meth:`build_url` -> fetch the section page -> cross-check
        the page's own heading identifier against ``ref`` -> parse the
        section into a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/massachusetts.md): the
        operative heading is ``<h2 ... genLawHeading ...>Section {id}:
        <small>{caption}</small></h2>`` followed by an empty spacer ``<p>``
        and then the body ``<p>`` blocks; the caption becomes ``heading``
        and the cleaned body paragraphs (excluding the empty spacer) become
        ``text``. There is no history/amendment text on the pages, so
        ``amendment_notes`` is always ``None``. A repealed or
        amended-into-a-special-act section renders only a prose caption with
        an empty body -- it is returned with ``text=""`` and the caption as
        ``heading`` (status ``UNKNOWN``), not treated as a normalization
        error.

        Args:
            ref: The section to retrieve. Must be a Massachusetts ref
                (``ref.state_code == "MA"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than an unresolvable document.
            RefNotFoundError: If the section page does not resolve (HTTP 404
                or the site's soft-404 page).
            RefMismatchError: If the page's own heading identifier disagrees
                with ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but the page is
                genuinely malformed (missing the heading) or empty (no
                heading and no body text).
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Massachusetts section page")

        heading_match = self._HEADING.search(html)
        if heading_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "genLawHeading heading; the site's structure may have "
                "changed."
            )

        page_identifier = re.sub(r"\s+", "", self._clean(heading_match.group(1)))
        if page_identifier != re.sub(r"\s+", "", ref.identifier):
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"identifier found on the fetched page: "
                f"{page_identifier!r}."
            )

        heading = self._clean(heading_match.group(2))
        body_end = html.find("</main>", heading_match.end())
        body_region = (
            html[heading_match.end() :] if body_end == -1 else html[heading_match.end() : body_end]
        )
        text = "\n\n".join(
            part for part in (self._clean(p) for p in self._BODY_PARAGRAPH.findall(body_region)) if part
        ).strip()

        if not heading and not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but both its heading and body text were empty after "
                "cleaning; the site's structure may have changed."
            )

        raw_citation = f"G.L. c. {ref.chapter.identifier}, § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=None,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)