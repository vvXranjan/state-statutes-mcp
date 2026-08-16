"""NebraskaAdapter: the Nebraska-specific concrete state adapter.

Source: the official Nebraska Legislature Revised Statutes at
``https://nebraskalegislature.gov/laws/`` -- anonymous, server-rendered
HTML with no authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/nebraska.md``; verified against Wayback Machine captures
of the official host -- the live host is not reachable from this
environment -- snapshots ``20251215062931`` for ``statutes.php`` and
``20251215071544`` for ``browse-chapters.php`` and ``20260107210216`` for
``browse-statutes.php``):

* Base URL ``https://nebraskalegislature.gov`` with statutory pages under
  ``/laws/``.
* The Revised Statutes have NO title level: the official site groups the
  code into chapters 1-90 only, listed flat on ``/laws/browse-statutes.php``
  ("Browse Statutes by Chapter"; rows are ``Chapter {n}`` + title). To fit
  the framework's three-level ref model, this adapter exposes a single
  synthetic ``TitleRef`` (identifier ``"REVISED STATUTES"``) above every
  chapter. This mapping is adapter-internal and documented; it is not a
  framework change (the MinnesotaAdapter synthetic-title precedent).
* Chapters: the browse page lists all 90 chapters. Each chapter's section
  index is ``/laws/browse-chapters.php?chapter={n}`` (its header is
  ``Revised Statutes Chapter {n} - {NAME}``).
* Sections: the chapter index lists every section as a row whose link is
  ``/laws/statutes.php?statute={sec}`` where ``{sec}`` is the full
  ``{ch}-{sec}`` citation (e.g. ``"77-202.12"``, ``"77-1801"``; decimal
  subsection identifiers are preserved). ``SectionRef.identifier`` is this
  full ``{ch}-{sec}`` form, matching the citation.
* Section content: ``/laws/statutes.php?statute={sec}`` -- one page per
  section. Verified structure (77-1801, 77-202.12, 77-202.13):
  * ``<h1>Nebraska Revised Statute {sec}</h1>`` (navigation chrome; not
    used for parsing).
  * ``<div class="statute">`` holds the section: ``<h2>{sec}.</h2>`` (the
    section number cross-check), ``<h3>{caption}</h3>`` (the heading), the
    body's ``<p class="text-justify">`` paragraphs, and a ``Source`` block
    (``<h2>Source</h2>`` + ``<ul class="fa-ul">`` of ``<li>`` history
    items) carrying the session-law history.
  * A trailing ``<div class="statute_source">`` block holds case
    ``Annotations`` (case-law notes). These are editorial annotations, not
    statute text, and are deliberately excluded from ``text``.
  * A repealed section (e.g. 77-202.13) renders ``<h2>{sec}.</h2>`` with an
    ``<h3>`` heading ``Repealed. Laws 2008, LB 965, § 27.`` and NO body
    paragraphs and NO Source block. Per the documented deviation for
    repealed sections (same decision as NorthCarolinaAdapter), such a
    section is returned with that repeal note as its heading and empty
    text; ``NormalizationError`` is reserved for genuinely malformed
    documents with no heading at all.
* Citation: ``Neb. Rev. Stat. § {ch}-{sec}`` (e.g. ``Neb. Rev. Stat. §
  77-1801``), adapter-constructed (the abbreviation is standard Nebraska
  citation usage; the number is VERIFIED from the site's own headings).
* Encoding: UTF-8 (``<meta charset="utf-8">``), so the shared UTF-8
  ``fetch_url`` helper is used directly.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/nebraska.md``): the live host is not reachable from this
environment, so the HTTP 404 semantics for a missing chapter/section are
UNVERIFIED -- HTTP 404 maps to ``RefNotFoundError`` by project convention
(the source was reached but the addressed document does not resolve), and
other network failures map to ``AdapterUnavailableError``. Whether every
section page renders identically is also unverified (three pages sampled).
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


class NebraskaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Nebraska Revised Statutes
    at nebraskalegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Because Nebraska has no
    title level, a single synthetic ``TitleRef`` (``"REVISED STATUTES"``)
    sits above every chapter; see the module docstring.
    """

    BASE_URL = "https://nebraskalegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # The single synthetic title that stands in for the absent title
    # level. There is exactly one such title (the whole Revised Statutes).
    SYNTHETIC_TITLE_IDENTIFIER = "REVISED STATUTES"
    SYNTHETIC_TITLE_NAME = "Nebraska Revised Statutes"

    # A chapter row on the browse page (browse-statutes.php), e.g.
    # '<span class="col-md-2 col-sm-3 my-auto"><a href="/web/.../browse-
    # chapters.php?chapter=36">Ch<span class="d-none d-md-inline">apter
    # </span> 36</a></span> <span class="col-md-9 col-sm-8 my-auto">
    # FRAUD AND VOIDABLE TRANSACTIONS</span>'. The chapter identifier is
    # the browse-chapters query value; the name is the adjacent span.
    _CHAPTER_ROW = re.compile(
        r'<a href="[^"]*browse-chapters\.php\?chapter=(\d+)"[^>]*>.*?</a>\s*'
        r'</span>\s*<span class="col-md-9 col-sm-8 my-auto">(.*?)</span>',
        re.DOTALL,
    )

    # A section row on a chapter index page (browse-chapters.php), e.g.
    # '<span class="col-md-2 col-sm-3 my-auto"><a href="/web/.../statutes
    # .php?statute=77-202.12">...77-202.12</a></span> <span class=
    # "col-lg-9 col-md-8 col-sm-7 my-auto">Public property; ...</span>'.
    # The section identifier is the statute query value (the full
    # {ch}-{sec} citation); the name is the adjacent span.
    _SECTION_ROW = re.compile(
        r'<a href="[^"]*statutes\.php\?statute=([^"&]+)"[^>]*>.*?</a>\s*'
        r'</span>\s*<span class="col-lg-9 col-md-8 col-sm-7 my-auto">(.*?)</span>',
        re.DOTALL,
    )

    # The section number heading, e.g. '<h2>77-1801.</h2>'.
    _SECTION_NUMBER_H2 = re.compile(r"<h2>(.*?)</h2>", re.DOTALL)

    # The section caption, e.g. '<h3>Real property taxes; collection by
    # sale; when.</h3>'. A repealed section's caption is its repeal note
    # (e.g. 'Repealed. Laws 2008, LB 965, § 27.').
    _HEADING_H3 = re.compile(r"<h3>(.*?)</h3>", re.DOTALL)

    # A body paragraph, e.g. '<p class="text-justify">(1) On or before
    # March 1, ...</p>'.
    _BODY_PARAGRAPH = re.compile(
        r'<p class="text-justify">(.*?)</p>', re.DOTALL
    )

    # The Source (history) block: '<h2>Source</h2>' ... '<ul class="fa-ul">
    # <li><i class="fa fa-li fa-book"></i>Laws 1903, c. 73, § 193, p. 459;
    # </li> ... </ul>'. Items may wrap the history text in an <a>.
    _SOURCE_BLOCK = re.compile(r"<h2>Source</h2>(.*?)</ul>", re.DOTALL)
    _SOURCE_ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)

    # The case-annotation block that follows the Source block (excluded
    # from the statute text).
    _STATUTE_SOURCE = re.compile(r'<div class="statute_source">')

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Nebraska."""
        return "NE"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Nebraska."""
        return "Nebraska"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Nebraska Legislature URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/nebraska.md):

        * Section: ``https://nebraskalegislature.gov/laws/statutes.php?statute={sec}``
          where ``{sec}`` is ``SectionRef.identifier`` (the full
          ``{ch}-{sec}`` citation, e.g. ``"77-1801"``).
        * Chapter: ``https://nebraskalegislature.gov/laws/browse-chapters.php?chapter={n}``
          -- the chapter's section index page.
        * Title: no page exists (the synthetic title has no source
          document; chapters are listed on ``browse-statutes.php``);
          raising :class:`UnsupportedRefError`.

        Args:
            ref: The section or chapter to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is a :class:`TitleRef` (there
                is no Nebraska title page), or not a chapter/section ref.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/laws/statutes.php?statute={ref.identifier}"
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/laws/browse-chapters.php?"
                f"chapter={ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            raise UnsupportedRefError(
                "NebraskaAdapter.build_url cannot address a title: the "
                "Revised Statutes have no title level (the adapter exposes "
                "a single synthetic title, whose chapters are listed on "
                "browse-statutes.php, not on a per-title page)."
            )
        else:
            raise UnsupportedRefError(
                f"NebraskaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
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
        verified HTTP 404 (e.g. an invalid chapter or section) into
        :class:`RefNotFoundError` -- the source was reached, but the
        addressed document does not resolve. The live 404 semantics are
        UNVERIFIED (the host is unreachable from this environment); HTTP
        404 -> ``RefNotFoundError`` follows project convention.

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
                does not resolve on the Nebraska Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Nebraska Legislature "
                    "site."
                ) from exc
            raise

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
        """Enumerate every title of Nebraska Revised Statutes.

        The Revised Statutes have no title level, so this returns exactly
        one node: the synthetic title (identifier ``"REVISED STATUTES"``)
        that stands in for the whole code. This is a fixed adapter-internal
        mapping (the MinnesotaAdapter synthetic-title precedent), not
        derived from any fetch.

        Returns:
            A sequence containing the one synthetic :class:`TocNode` whose
            ``ref`` is a :class:`TitleRef` with identifier
            ``"REVISED STATUTES"``.
        """
        return (
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=self.SYNTHETIC_TITLE_IDENTIFIER,
                name=self.SYNTHETIC_TITLE_NAME,
                ref=TitleRef(
                    state_code=self.state_code,
                    identifier=self.SYNTHETIC_TITLE_IDENTIFIER,
                ),
            ),
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the browse
        page.

        The browse page (``/laws/browse-statutes.php``, "Browse Statutes
        by Chapter") lists all chapters 1-90 as rows whose identifier is
        the chapter number and whose name is the chapter title.

        Args:
            title_ref: The parent title. Must be the single synthetic
                title (``"REVISED STATUTES"``); any other identifier
                raises ``RefNotFoundError`` because no such title exists.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            RefNotFoundError: If ``title_ref`` is not the synthetic title,
                or if the browse page returns HTTP 404.
            AdapterUnavailableError: If the browse page cannot be fetched
                for any other reason, or if no usable chapter rows could
                be parsed from it.
        """
        if title_ref.identifier != self.SYNTHETIC_TITLE_IDENTIFIER:
            raise RefNotFoundError(
                f"Nebraska Revised Statutes have no title "
                f"{title_ref.identifier!r}; the only title is the synthetic "
                f"{self.SYNTHETIC_TITLE_IDENTIFIER!r} covering every chapter."
            )

        url = f"{self.BASE_URL}/laws/browse-statutes.php"
        html = self._fetch_html(url, what="Nebraska chapter listing")

        chapters = []
        seen: set[str] = set()
        for identifier, raw_name in self._CHAPTER_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = self._clean_row_name(raw_name)
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
                "the site's structure may have changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        index page.

        The chapter index page (``/laws/browse-chapters.php?chapter={n}``)
        lists every section of the chapter. The identifier is the full
        ``{ch}-{sec}`` citation (e.g. ``"77-202.12"``, ``"77-1801"``); the
        display name is the section caption (a repealed section's name is
        its repeal note, e.g. ``"Repealed. Laws 2008, LB 965, § 27."``).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{ch}-{sec}`` citation.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter index page cannot be
                fetched for any other reason, or if no usable section rows
                could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Nebraska section listing")

        sections = []
        seen: set[str] = set()
        for identifier, raw_name in self._SECTION_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = self._clean_row_name(raw_name)
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
                f"chapter {chapter_ref.identifier!r} either does not "
                "resolve or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Nebraska.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full
        ``{ch}-{sec}`` citation, e.g. ``"77-1801"``) must appear verbatim
        within ``parsed.raw_citation`` (the ``Neb. Rev. Stat. § 77-1801``
        citation). The stronger section-number cross-check against the
        source response happens in :meth:`retrieve_section`, which parses
        the page's own ``<h2>`` number.

        ``status`` is always left at its default (``UNKNOWN``): the
        Nebraska section pages carry no structural
        repealed/amended/renumbered signal (a repealed section is
        identified only by its prose caption, and the contract explicitly
        forbids inferring status from prose).

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Nebraska ref
                (``ref.state_code != "NE"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NebraskaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Nebraska Revised Statute section,
        end to end: :meth:`build_url` -> fetch the section page ->
        cross-check the page's ``<h2>`` section number against ``ref`` ->
        parse the section into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/nebraska.md): the heading
        is the ``<h3>`` caption following the ``<h2>`` section number; the
        body is the ``<p class="text-justify">`` paragraphs between the
        caption and the ``Source`` block; ``amendment_notes`` is the
        concatenated text of the ``Source`` block's ``<li>`` history items.
        The trailing case ``Annotations`` block is excluded from the
        statute text. A repealed section (e.g. 77-202.13) has a repeal
        caption, no body paragraphs, and no Source block; per the
        documented deviation it is returned with that repeal note as the
        heading and empty text.

        Args:
            ref: The section to retrieve. Must be a Nebraska ref
                (``ref.state_code == "NE"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                section does not resolve; live 404 semantics UNVERIFIED --
                project convention).
            RefMismatchError: If the page's ``<h2>`` section number
                disagrees with ``ref``. Also raised by :meth:`normalize`
                on citation disagreement.
            NormalizationError: If the section was located but the page is
                genuinely malformed (missing the section number or heading
                element), or the body is empty after cleaning with no
                heading to carry a repeal note.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Nebraska section page")

        statute_start = html.find('<div class="statute">')
        if statute_start < 0:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "statute content region; the site's structure may have "
                "changed."
            )
        statute_region = html[statute_start:]

        number_h2 = self._SECTION_NUMBER_H2.search(statute_region)
        if number_h2 is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no section "
                "number heading; the site's structure may have changed."
            )
        section_number = number_h2.group(1).strip().rstrip(".")
        if section_number != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section number on the fetched page: {section_number!r}."
            )

        after_number = statute_region[number_h2.end() :]
        heading_h3 = self._HEADING_H3.search(after_number)
        if heading_h3 is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but the section page contained no heading element; the "
                "site's structure may have changed."
            )
        heading = self._clean(heading_h3.group(1)) or None

        body_start = number_h2.end() + heading_h3.end()
        body_segment = statute_region[body_start:]
        source = self._SOURCE_BLOCK.search(body_segment)
        annotations = self._STATUTE_SOURCE.search(body_segment)
        body_end = len(body_segment)
        if source is not None and source.start() < body_end:
            body_end = source.start()
        if annotations is not None and annotations.start() < body_end:
            body_end = annotations.start()
        body_html = body_segment[:body_end]

        paragraphs = self._BODY_PARAGRAPH.findall(body_html)
        text = "\n\n".join(self._clean(p) for p in paragraphs)

        amendment_notes = None
        if source is not None:
            items = self._SOURCE_ITEM.findall(source.group(1))
            if items:
                amendment_notes = " ".join(self._clean(item) for item in items) or None

        if not text and not amendment_notes:
            if heading:
                # Documented deviation: a repealed/reserved section carries
                # its repeal note as the heading with an empty body (the
                # same decision as NorthCarolinaAdapter).
                text = ""
            else:
                raise NormalizationError(
                    f"Fetched {url!r} and resolved section "
                    f"{ref.identifier!r}, but its body text was empty after "
                    "cleaning, it carries no amendment notes, and it has no "
                    "heading; the section is likely empty or the site's "
                    "structure has changed."
                )

        raw_citation = f"Neb. Rev. Stat. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)