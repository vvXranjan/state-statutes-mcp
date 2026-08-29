"""PennsylvaniaAdapter: the Pennsylvania-specific concrete state adapter.

Source: the official Pennsylvania consolidated statutes at ``https://www.
legis.state.pa.us/WU01/LI/LI/CT/HTM/{TT}/00.{chapter}.{local}.{decimal}..
HTM``, published by the Pennsylvania General Assembly / Legislative Data
Processing Center (LDPC). The consolidated statutes are served as
server-rendered HTML over ordinary HTTP GETs; each section is its own
static page. The live hosts (``www.legis.state.pa.us`` and its front-end
``www.palegis.us``) are TCP-blocked from this environment, so all structure
verification and fixtures below are based on **real archived official
captures** of the official host (retrieved via the Wayback Machine in Aug
2026); they are archived captures, NOT live captures (the
Colorado/Michigan/Alaska precedent).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/
pennsylvania.md``; all structures verified against real archived official
captures):

* **Hierarchy**: ``Title -> Part -> Chapter -> Subchapter -> Section``. The
  section citation ``{S}`` (e.g. ``2707``, ``2702.1``, ``2109.1``) encodes
  its chapter directly: ``chapter = int(S) // 100``, ``local =
  int(S) % 100``, and any decimal component (``S = "2702.1"`` -> decimal
  ``1``) is preserved as the URL's fourth component. Part and Subchapter
  are structural groupings NOT encoded in the citation, so they are folded
  away. The framework's three-level model maps directly: ``TitleRef`` =
  title number (0-87, as the site numbers them; 0 is the Constitution),
  ``ChapterRef`` = the chapter number (e.g. ``"27"``), ``SectionRef`` =
  the full section citation (e.g. ``"2707"`` or ``"2702.1"``).
* **Section URL (VERIFIED, 10+ sections across titles 18/20/42)**:
  ``https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/{TT}/00.{chapter:03d}.
  {local:03d}.{decimal:03d}..HTM`` (e.g. ``18 § 2707`` -> ``.../18/00.027.
  007.000..HTM``; ``18 § 1102.1`` -> ``.../18/00.011.002.001..HTM``).
* **Section page (VERIFIED)**: the page self-identifies in its ``<title>``
  as ``Section {n}[.{d}] - Title {t} - {NAME}`` (current pages render
  ``Section 2707.0 - Title 18 - CRIMES AND OFFENSES``; the Constitution,
  title 0, omits ``Title {t}``), carries a ``§ {n}. {catchline}.`` heading
  followed by the body and a legislative-history block, and a
  ``{t}c{n}s`` section anchor.
* **Chapter index (VERIFIED)**: the first-section page of each chapter
  (``00.{chapter}.001.000..HTM``) is the chapter's index — it lists every
  section of the chapter as ``{n}. {catchline}.`` rows (decimal sections
  included, e.g. ``2702.1.``) followed by the first section's full text.
  This is the section-discovery source and the chapter-probing surface.
* **Title page (VERIFIED)**: ``{TT}/00.001..HTM`` is the title document;
  its ``<title>`` is ``Chapter 1[.] - [Title {t} - ]{NAME}`` (the title
  name follows), giving the title name for title-range probing.
* **Invalid-section behavior (VERIFIED via archived capture)**: a
  nonexistent citation (e.g. ``18 § 5003`` -> ``18/00.050.003.000..HTM``,
  chapter 50 does not exist) returns **HTTP 302 -> ``/cfdocs/Errors/
  404.html``**, which serves the official "Page Not Found - PA General
  Assembly" page with HTTP 200. The adapter content-detects that page and
  maps it to ``RefNotFoundError`` (and also maps a direct HTTP 404 via the
  Iowa/Michigan ``HTTPError.__cause__`` pattern).
* **Repealed-section behavior (VERIFIED via archived capture)**: a repealed
  section (e.g. ``18 § 4321``, "Nonsupport", repealed 1985) returns HTTP
  200 with the identity ``Section 4321 - Title 18 - CRIMES AND OFFENSES``
  and a structural repeal stub ("SUBCHAPTER B NONSUPPORT (Repealed)" +
  "1985 Repeal Note. ..."). The adapter preserves the repeal note as the
  text and sets ``status = REPEALED`` (a structural signal, not prose
  inference).
* **Silent-fallback protection**: none observed in the archived corpus; the
  adapter ALWAYS content-verifies the returned page's ``Section {n}[.{d}]``
  identity and (when present) ``Title {t}`` against the request, so a
  chapter-index page or a neighboring section can never be silently
  returned (``RefMismatchError``).
* **Discovery**: ``list_titles`` probes ``{TT}/00.001..HTM`` over titles
  0-87 (title pages verified to serve the title name; invalid titles are
  filtered by identity parsing — the Colorado probing precedent);
  ``list_chapters`` probes ``{TT}/00.{c}.001.000..HTM`` over chapters
  1-99 and validates each chapter's ``CHAPTER {c}`` header (valid
  chapter-index pages verified current); ``list_sections`` reads the
  chapter-index page's section rows.
* **Encoding**: the official pages are UTF-8 (charset declared), so the
  shared ``fetch_url`` is used directly.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/pennsylvania.md``): the live hosts cannot be exercised from
this environment (TCP-blocked), so behavior relies on the archived
captures above plus defensive content checks. The exact terminal response
for an invalid *chapter* probe (vs. the verified invalid-*section* 302 ->
404 page) is unobservable from the archive; the probing mechanisms are
correct-by-design (identity parsing filters every non-valid response,
including a hypothetical cross-chapter fallback) and mirror the Colorado
probing precedent. Lettered chapters (e.g. Title 53 Chapter 57A) are not
enumerated (the legacy URL model for them is unverified) and lettered
section citations are rejected. ``list_titles`` / ``list_chapters`` probe
bounded numeric ranges (0-87 / 1-99) and are cached per adapter instance
(P2 performance note: 88 / 99 sequential GETs on first call).
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
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus


class PennsylvaniaAdapter(BaseStateAdapter):
    """Concrete state adapter for the Pennsylvania consolidated statutes at
    legis.state.pa.us.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The Pennsylvania
    consolidated statutes map directly onto the framework's three-level
    model as title -> chapter -> citation. See the module docstring.
    """

    BASE_URL = "https://www.legis.state.pa.us"
    HTM_PATH = "/WU01/LI/LI/CT/HTM"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Bounded probe ranges for the Colorado-style numeric discovery. Titles
    # are numbered 0-87 (0 is the Constitution; titles 19/21/41/55/56 are
    # repealed and simply probe as absent). Chapters within a title run
    # 1-99 (verified up to 97 in Title 18).
    TITLE_RANGE = range(0, 88)
    CHAPTER_RANGE = range(1, 100)

    # A section citation: 3-4 digit number, optional 1-3 digit decimal
    # component (e.g. '2707', '2702.1', '2109.1'). Lettered forms are not
    # observed in the archived corpus and are rejected.
    _CITATION = re.compile(r"^(\d{3,4})(?:\.(\d{1,3}))?$")

    # A title number used to address a title page.
    _TITLE = re.compile(r"^\d{1,2}$")

    # The <title> identity of a section page, e.g.
    # 'Section 2707.0 - Title 18 - CRIMES AND OFFENSES',
    # 'Section 1102.1 - Title 18 - CRIMES AND OFFENSES',
    # 'Section 4321 - Title 18 - CRIMES AND OFFENSES', or the Constitution's
    # 'Section 105 - CONSTITUTION OF PENNSYLVANIA' (no 'Title {t}'). group(1)
    # = section number, group(2) = decimal component (or None), group(3) =
    # title number (or None), group(4) = title name.
    _SECTION_IDENTITY = re.compile(
        r"^Section\s+(\d+)(?:\.(\d+))?\s*-\s*(?:Title\s+(\d+)\s*-\s*)?(.+)$"
    )

    # The <title> identity of a title page, e.g.
    # 'Chapter 1 - Title 18 - CRIMES AND OFFENSES' (older format),
    # 'Chapter 1. - Title 15 - CORPORATIONS AND UNINCORPORATED
    # ASSOCIATIONS' (current format), or 'Chapter 1. - CONSTITUTION OF
    # PENNSYLVANIA' (title 0). group(1) = the title name.
    _TITLE_IDENTITY = re.compile(
        r"^Chapter\s+1\.?\s*-\s*(?:Title\s+\d+\s*-\s*)?(.+)$"
    )

    # The chapter header on a chapter-index page, e.g. 'CHAPTER 27'.
    _CHAPTER_HEADER = re.compile(r"^CHAPTER\s+(\d+[A-Za-z]?)$")

    # A section heading line, e.g. '§ 2707. Propulsion of missiles into an
    # occupied vehicle or onto a roadway.'. group(1) = the section citation,
    # group(2) = the catchline.
    _SECTION_HEADING = re.compile(r"^§\s+(\d+(?:\.\d+)?)\.\s+(.+)$")

    # A section row on a chapter-index page, e.g. '2701. Simple assault.' or
    # '2702.1. Assault of law enforcement officer.'.
    _SECTION_ROW = re.compile(r"^(\d+(?:\.\d+)?)\.\s+(.+)$")

    # A legislative-history line, e.g. '(July 16, 1975, P.L.62, No.37; ...)'.
    _HISTORY = re.compile(r"^\(\s*[A-Za-z.]+\s+\d{1,2},?\s+\d{4}")

    # The official 'not found' page identity/content.
    _NOT_FOUND = re.compile(r"Page Not Found")

    # A structural repeal marker in a repealed section's stub page
    # ('(Repealed)' or 'Repeal Note').
    _REPEALED = re.compile(r"\(Repealed\)|Repeal Note", re.IGNORECASE)

    # The section/history anchor comment lines (e.g. '18c2707s', '18c2707v',
    # '18c1102.1s', '18c2701h') which carry no readable text.
    _ANCHOR = re.compile(r"^\d{1,2}c[\d.]+[a-z]$", re.IGNORECASE)

    def __init__(self) -> None:
        """Create the adapter with per-instance discovery caches.

        ``list_titles`` and ``list_chapters`` probe bounded numeric ranges
        (88 / 99 GETs respectively), so their results are cached per adapter
        instance. This is instance-local state (each registry owns its own
        constructed adapters), not global mutable state.
        """
        self._title_cache: tuple[TocNode, ...] | None = None
        self._chapter_cache: dict[str, tuple[TocNode, ...]] = {}

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Pennsylvania."""
        return "PA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Pennsylvania."""
        return "Pennsylvania"

    # ------------------------------------------------------------
    # Citation normalization
    # ------------------------------------------------------------

    @staticmethod
    def _parse_citation(citation: str) -> tuple[int, int] | None:
        """Parse a Pennsylvania section citation into its numeric
        ``(section_number, decimal)`` components.

        ``section_number`` is the whole-number part of the citation (the
        chapter is ``section_number // 100`` and the local section is
        ``section_number % 100``); ``decimal`` is the decimal component
        (0 when absent). Returns ``None`` for a malformed citation.

        Args:
            citation: The section identifier (e.g. ``"2707"``,
                ``"2702.1"``).

        Returns:
            ``(section_number, decimal)`` or ``None``.
        """
        match = PennsylvaniaAdapter._CITATION.fullmatch(citation)
        if match is None:
            return None
        section = int(match.group(1))
        decimal = int(match.group(2)) if match.group(2) is not None else 0
        return section, decimal

    @staticmethod
    def _identity_section_string(section: int, decimal: str | None) -> str:
        """Render the identity's section + decimal as the site's citation
        string (a trailing ``.0`` decimal is dropped)."""
        if decimal in (None, "0"):
            return str(section)
        return f"{section}.{decimal}"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _title_url(self, title: str) -> str:
        """The title page URL for ``title`` (the title document).

        The site zero-pads the title number to two digits in the URL path
        (``"0"`` -> ``00``, ``"1"`` -> ``01``, ``"18"`` -> ``18``).
        """
        return f"{self.BASE_URL}{self.HTM_PATH}/{int(title):02d}/00.001..HTM"

    def _chapter_url(self, title: str, chapter: int) -> str:
        """The chapter-index (first-section) URL for ``chapter`` of
        ``title``."""
        return (
            f"{self.BASE_URL}{self.HTM_PATH}/{int(title):02d}/00."
            f"{chapter:03d}.001.000..HTM"
        )

    def _section_url(
        self, title: str, chapter: int, local: int, decimal: int
    ) -> str:
        """The per-section URL for ``chapter``/``local``/``decimal`` of
        ``title``."""
        return (
            f"{self.BASE_URL}{self.HTM_PATH}/{int(title):02d}/00.{chapter:03d}."
            f"{local:03d}.{decimal:03d}..HTM"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Pennsylvania Legislature URL for ``ref``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the title document page.
            * ``ChapterRef`` -> the chapter-index (first-section) page.
            * ``SectionRef`` -> the per-section page.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If ``ref`` carries an invalid title, chapter,
                or citation.
        """
        if isinstance(ref, SectionRef):
            parsed = self._parse_citation(ref.identifier)
            if parsed is None:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania section identifier "
                    f"{ref.identifier!r}: expected a numeric citation such as "
                    "'2707' or '2702.1'."
                )
            section, decimal = parsed
            title = ref.chapter.title.identifier
            if self._TITLE.fullmatch(title) is None:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania title {title!r}."
                )
            return self._section_url(
                title, section // 100, section % 100, decimal
            )
        elif isinstance(ref, ChapterRef):
            title = ref.title.identifier
            if self._TITLE.fullmatch(title) is None:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania title {title!r}."
                )
            try:
                chapter = int(ref.identifier)
            except ValueError:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania chapter identifier "
                    f"{ref.identifier!r}."
                ) from None
            if chapter not in self.CHAPTER_RANGE:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania chapter identifier "
                    f"{ref.identifier!r}."
                )
            return self._chapter_url(title, chapter)
        elif isinstance(ref, TitleRef):
            if self._TITLE.fullmatch(ref.identifier) is None:
                raise RefNotFoundError(
                    f"Invalid Pennsylvania title {ref.identifier!r}."
                )
            return self._title_url(ref.identifier)
        else:
            raise UnsupportedRefError(
                f"PennsylvaniaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its content as UTF-8-decoded text.

        Args:
            url: The URL to fetch.
            what: A short human-readable description used for error
                messages.

        Returns:
            The fetched content.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached (network
                failure or non-2xx HTTP response, including HTTP 404/400
                which callers may re-map).
        """
        return fetch_url(
            url,
            what=what,
            timeout=self.DEFAULT_TIMEOUT_SECONDS,
        )

    def _is_404_error(self, exc: AdapterUnavailableError) -> bool:
        """Return True if ``exc`` wraps an HTTP 404 (``HTTPError``)."""
        cause = exc.__cause__
        return isinstance(cause, urllib.error.HTTPError) and cause.code == 404

    # ------------------------------------------------------------
    # Page identity helpers
    # ------------------------------------------------------------

    @staticmethod
    def _body_lines(html: str) -> list[str]:
        """Return the page's body as cleaned, non-empty text lines."""
        body_match = re.search(r"<body[^>]*>", html, re.IGNORECASE | re.DOTALL)
        body = html[body_match.end() :] if body_match is not None else html
        text = strip_tags(body, preserve_block_breaks=True)
        return [line for line in text.split("\n") if line]

    def _extract_section_identity(
        self, html: str
    ) -> tuple[int, str | None, str | None, str] | None:
        """Parse the ``Section {n}[.{d}] - [Title {t} - ]{name}`` identity
        from the page's ``<title>`` tag."""
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        if title_match is None:
            return None
        title_text = " ".join(title_match.group(1).split())
        m = self._SECTION_IDENTITY.match(title_text)
        if m is None:
            return None
        return (
            int(m.group(1)),
            m.group(2),
            m.group(3),
            m.group(4).strip(),
        )

    def _extract_title_name(self, html: str) -> str | None:
        """Parse the title name from a title page's ``<title>`` tag."""
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        if title_match is None:
            return None
        title_text = " ".join(title_match.group(1).split())
        m = self._TITLE_IDENTITY.match(title_text)
        if m is None:
            return None
        name = m.group(1).strip()
        return name or None

    def _extract_chapter(
        self, html: str
    ) -> tuple[str, str] | None:
        """Parse the ``CHAPTER {c}`` header and chapter name from a
        chapter-index page."""
        lines = self._body_lines(html)
        for i, line in enumerate(lines):
            m = self._CHAPTER_HEADER.match(line)
            if m is None:
                continue
            name = lines[i + 1] if i + 1 < len(lines) else ""
            return m.group(1), name.strip() or m.group(1)
        return None

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Pennsylvania consolidated statutes.

        Discovers titles dynamically by probing the deterministic official
        title-page pattern over the bounded range 0-87. Each valid title's
        name is read from the title page's ``Chapter 1[.] - [Title {t} - ]
        {name}`` identity. Invalid titles (including repealed title numbers
        such as 19/21/41/55/56) return the official "Page Not Found" page
        (or HTTP 404) and are skipped by the identity check. The result is
        built once per adapter instance (subsequent calls reuse the cache).

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"18"``).

        Raises:
            AdapterUnavailableError: If the probed title pages could not be
                reached for a network reason, or if no usable title pages
                could be parsed.
        """
        if self._title_cache is not None:
            return self._title_cache

        titles: list[TocNode] = []
        for number in self.TITLE_RANGE:
            identifier = str(number)
            url = self._title_url(identifier)
            try:
                html = self._fetch_html(url, what="Pennsylvania title page")
            except AdapterUnavailableError as exc:
                if self._is_404_error(exc):
                    continue
                raise
            name = self._extract_title_name(html)
            if name is None:
                continue
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

        if not titles:
            raise AdapterUnavailableError(
                "Probed the Pennsylvania title-page range but found no "
                "valid titles; the site's structure may have changed."
            )

        result = tuple(titles)
        self._title_cache = result
        return result

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref``.

        Discovers chapters dynamically by probing the deterministic
        chapter-index pattern (``00.{c}.001.000..HTM``) over the bounded
        range 1-99 and validating each page's ``CHAPTER {c}`` header against
        the probed number; invalid chapters are filtered out. The result is
        cached per title per adapter instance.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"27"``).

        Raises:
            AdapterUnavailableError: If the probed chapter-index pages could
                not be reached for a network reason, or if no usable
                chapters could be parsed.
            RefNotFoundError: If ``title_ref`` carries an invalid title.
        """
        if self._TITLE.fullmatch(title_ref.identifier) is None:
            raise RefNotFoundError(
                f"Invalid Pennsylvania title {title_ref.identifier!r}."
            )

        cached = self._chapter_cache.get(title_ref.identifier)
        if cached is not None:
            return cached

        chapters: list[TocNode] = []
        for number in self.CHAPTER_RANGE:
            url = self._chapter_url(title_ref.identifier, number)
            try:
                html = self._fetch_html(
                    url, what="Pennsylvania chapter index"
                )
            except AdapterUnavailableError as exc:
                if self._is_404_error(exc):
                    continue
                raise
            extracted = self._extract_chapter(html)
            if extracted is None:
                continue
            declared, name = extracted
            if declared != str(number):
                continue
            identifier = str(number)
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
                f"Probed the Pennsylvania chapter-index range for title "
                f"{title_ref.identifier!r} but found no usable chapters; "
                "the site's structure may have changed."
            )

        result = tuple(chapters)
        self._chapter_cache[title_ref.identifier] = result
        return result

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter's
        index (first-section) page.

        ``SectionRef.identifier`` is the full section citation (e.g.
        ``"2707"``, ``"2702.1"``).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order.

        Raises:
            AdapterUnavailableError: If the chapter-index page could not be
                reached for a network reason, or if no usable section rows
                could be parsed.
            RefNotFoundError: If ``chapter_ref`` carries an invalid chapter
                or title, or the chapter does not resolve.
        """
        title = chapter_ref.title.identifier
        if self._TITLE.fullmatch(title) is None:
            raise RefNotFoundError(f"Invalid Pennsylvania title {title!r}.")
        try:
            chapter = int(chapter_ref.identifier)
        except ValueError:
            raise RefNotFoundError(
                f"Invalid Pennsylvania chapter identifier "
                f"{chapter_ref.identifier!r}."
            ) from None
        if chapter not in self.CHAPTER_RANGE:
            raise RefNotFoundError(
                f"Invalid Pennsylvania chapter identifier "
                f"{chapter_ref.identifier!r}."
            )

        url = self._chapter_url(title, chapter)
        try:
            html = self._fetch_html(url, what="Pennsylvania chapter index")
        except AdapterUnavailableError as exc:
            if self._is_404_error(exc):
                raise RefNotFoundError(
                    f"Could not retrieve the Pennsylvania chapter index at "
                    f"{url!r}: it returned HTTP 404 (the chapter does not "
                    "exist)."
                ) from exc
            raise

        if self._NOT_FOUND.search(html):
            raise RefNotFoundError(
                f"Could not retrieve the Pennsylvania chapter index at "
                f"{url!r}: the site returned its 'Page Not Found' page (the "
                "chapter does not exist)."
            )

        lines = self._body_lines(html)
        sections: list[TocNode] = []
        seen: set[str] = set()
        in_list = False
        for line in lines:
            if line == "Sec.":
                in_list = True
                continue
            if not in_list:
                continue
            m = self._SECTION_ROW.match(line)
            if m is None:
                break
            identifier = m.group(1)
            if identifier in seen:
                continue
            seen.add(identifier)
            name = m.group(2).strip()
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
                f"Fetched the Pennsylvania chapter-index page for chapter "
                f"{chapter_ref.identifier!r} but found no usable section "
                "rows in it; the site's structure may have changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # Section page parsing (Pennsylvania-specific, kept in the adapter)
    # ------------------------------------------------------------

    def _parse_section_page(
        self, html: str, url: str, ref: SectionRef
    ) -> ParsedDocument:
        """Parse a section page into a :class:`ParsedDocument`.

        Content-verifies the page's ``Section {n}[.{d}] - [Title {t} - ]
        {name}`` identity against the requested ``ref`` before parsing
        (silent-fallback protection).

        Args:
            html: The fetched section page HTML.
            url: The source URL.
            ref: The section reference that was originally requested.

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"{title} Pa.C.S. § {section}"``, ``heading`` = the catchline,
            ``text`` = the body (or the repeal note for repealed stubs),
            and ``amendment_notes`` = the legislative-history block. Repealed
            stubs carry no heading.

        Raises:
            RefNotFoundError: If the page carries no section identity (e.g.
                the official 'Page Not Found' page).
            RefMismatchError: If the page declares a different section or
                title than requested (silent-fallback protection).
            NormalizationError: If the page declares the section but its
                body structure is unparseable.
        """
        identity = self._extract_section_identity(html)
        if identity is None:
            raise RefNotFoundError(
                f"Could not find the Pennsylvania section {ref.identifier!r}: "
                "the fetched page carries no 'Section {n} - Title {t}' "
                "identity (the section does not resolve)."
            )
        section, decimal, title, _name = identity

        if self._identity_section_string(section, decimal) != ref.identifier:
            raise RefMismatchError(
                f"Requested Pennsylvania section {ref.identifier!r} does not "
                f"match the section found on the fetched page: "
                f"{self._identity_section_string(section, decimal)!r}."
            )
        if title is not None and title != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested Pennsylvania title "
                f"{ref.chapter.title.identifier!r} does not match the title "
                f"found on the fetched page: {title!r}."
            )

        lines = [
            line
            for line in self._body_lines(html)
            if not self._ANCHOR.match(line)
        ]
        full_text = " ".join(lines).strip()

        heading: str | None = None
        body_lines: list[str] = []
        notes_lines: list[str] = []
        seen_history = False
        for line in lines:
            heading_match = self._SECTION_HEADING.match(line)
            if heading_match is not None:
                heading = heading_match.group(2).strip()
                continue
            if self._HISTORY.match(line):
                seen_history = True
                notes_lines.append(line)
            elif seen_history or "Amendment." in line or line.startswith(
                "Cross References."
            ):
                notes_lines.append(line)
            else:
                body_lines.append(line)

        if heading is None:
            if self._REPEALED.search(full_text):
                return ParsedDocument(
                    raw_citation=(
                        f"{ref.chapter.title.identifier} Pa.C.S. § "
                        f"{ref.identifier}"
                    ),
                    heading=None,
                    text=full_text,
                    amendment_notes=None,
                    source_url=url,
                    retrieved_at=datetime.now(timezone.utc),
                )
            raise NormalizationError(
                "The fetched Pennsylvania section page declared its section "
                f"({ref.identifier!r}) but contained no '§' section heading "
                "and no repeal marker; the site's structure may have "
                "changed."
            )

        body_text = " ".join(body_lines).strip()
        notes_text = " ".join(notes_lines).strip() or None
        if not body_text:
            raise NormalizationError(
                "The fetched Pennsylvania section page declared its section "
                f"({ref.identifier!r}) but contained no body text; the "
                "site's structure may have changed."
            )

        return ParsedDocument(
            raw_citation=f"{ref.chapter.title.identifier} Pa.C.S. § {ref.identifier}",
            heading=heading,
            text=body_text,
            amendment_notes=notes_text,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Pennsylvania.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` must appear within
        ``parsed.raw_citation``.

        ``status`` is ``REPEALED`` when the source structurally declares the
        section repealed (a repeal-note stub carrying ``(Repealed)`` /
        ``Repeal Note``), and ``UNKNOWN`` otherwise.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Pennsylvania ref
                (``ref.state_code != "PA"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"PennsylvaniaAdapter.normalize cannot normalize a ref for "
                f"state {ref.state_code!r}; expected {self.state_code!r}."
            )

        if ref.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the parsed document: "
                f"{parsed.raw_citation!r}."
            )

        status = (
            StatuteStatus.REPEALED
            if parsed.heading is None
            and parsed.text is not None
            and self._REPEALED.search(parsed.text)
            else StatuteStatus.UNKNOWN
        )

        return StatuteSection(
            ref=ref,
            citation=Citation(
                state_code=self.state_code,
                raw=parsed.raw_citation,
            ),
            heading=parsed.heading,
            text=parsed.text,
            status=status,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Pennsylvania statute section, end to
        end: parse the citation and cross-check it against the ref's chapter
        -> fetch the section page -> content-verify the page's section
        identity -> parse into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a Pennsylvania ref
                (``ref.state_code == "PA"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be reached
                for a network reason (including non-404 HTTP errors).
            RefNotFoundError: If the citation is invalid, the section page
                returns HTTP 404, the site returns its 'Page Not Found'
                page, or the fetched page carries no section identity.
            RefMismatchError: If the ref's chapter disagrees with the
                citation's chapter, or the fetched page declares a different
                section/title than requested.
            NormalizationError: If the page declares the section but its
                structure is genuinely malformed.
        """
        parsed = self._parse_citation(ref.identifier)
        if parsed is None:
            raise RefNotFoundError(
                f"Invalid Pennsylvania section identifier {ref.identifier!r}: "
                "expected a numeric citation such as '2707' or '2702.1'."
            )
        title = ref.chapter.title.identifier
        if self._TITLE.fullmatch(title) is None:
            raise RefNotFoundError(f"Invalid Pennsylvania title {title!r}.")
        section, decimal = parsed
        chapter = section // 100
        local = section % 100

        if ref.chapter.identifier != str(chapter):
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not "
                f"match the chapter of the requested section "
                f"{ref.identifier!r}."
            )

        url = self._section_url(title, chapter, local, decimal)
        try:
            html = self._fetch_html(url, what="Pennsylvania statute section")
        except AdapterUnavailableError as exc:
            if self._is_404_error(exc):
                raise RefNotFoundError(
                    f"Could not retrieve the Pennsylvania section at "
                    f"{url!r}: it returned HTTP 404 (the section does not "
                    "exist)."
                ) from exc
            raise

        if self._NOT_FOUND.search(html):
            raise RefNotFoundError(
                f"Could not retrieve the Pennsylvania section at {url!r}: "
                "the site returned its 'Page Not Found' page (the section "
                "does not exist)."
            )

        document = self._parse_section_page(html, url, ref)
        return self.normalize(document, ref)