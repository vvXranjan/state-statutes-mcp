"""MichiganAdapter: the Michigan-specific concrete state adapter.

Source: the official Michigan Legislature / Michigan Compiled Laws (MCL) at
``https://www.legislature.mi.gov``, run by the Legislative Service Bureau in
cooperation with the Legislative Council and the Legislature. The MCL is
served as server-rendered HTML over ordinary HTTP GETs. The live host is
protected by a bot-challenge wall (HTTP 403 to this environment), so all
structure verification and fixtures below are based on **real archived
official captures** of the official host (retrieved via the Wayback Machine
in Aug 2026); they are archived captures, NOT live captures (the Colorado
precedent).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/michigan.md``;
all structures verified against real archived official captures):

* **Hierarchy**: the real structure is ``Chapter-group -> Act -> Division ->
  Section`` with the citation ``{chapter}.{section}`` encoding Chapter ->
  Section (e.g. ``712A.2d`` = chapter 712A, section 2d). The framework's
  three-level model is preserved by folding: ``TitleRef`` = a single
  synthetic title ``"MCL"`` (the Minnesota/Wisconsin synthetic-title
  precedent), ``ChapterRef`` = the MCL chapter (e.g. ``"701"``, ``"712A"``),
  and ``SectionRef.identifier`` = the full citation (e.g. ``"712A.2d"``).
  Act/Division/group are folded into discovery and are not framework
  levels.
* **Direct section URL**: ``/Laws/MCL?objectName=mcl-{chapter}-{section}``
  is derived deterministically from the citation by replacing the single
  ``.`` with ``-`` (``712A.2d`` -> ``mcl-712A-2d``). The ``GetObject``
  endpoint is a 302 redirect wrapper; the canonical content URL is the
  ``/Laws/MCL?objectName=`` form used directly.
* **Section page**: ``<title>MCL - Section {citation} ...</title>`` plus a
  ``<B>{citation} {catchline.}</B>`` heading, a ``<P>Sec. {n}.</P>``
  marker, ``<div>`` body paragraphs, and a ``<font size=\"2\">`` block
  carrying ``History:`` / ``Former Law:`` lines. Verified for 750.82,
  257.1, 712A.2a, 712A.2d (lettered + subsection-heavy).
* **Discovery**: ``/Laws/ChapterIndex`` lists every chapter as a ``<tr>``
  with a ``mcl-chap{n}`` link and the chapter name (241 chapters). The
  chapter page (``mcl-chap{n}``) lists the Acts in the chapter. An Act page
  (``mcl-Act-{n}-of-{year}``) lists either the sections directly
  (``Type = Section`` rows, e.g. Act 62 of 1872 -> sections 6.1-6.16) or
  the Divisions (``Type = Division`` rows, e.g. Act 288 of 1939). A
  Division page (``mcl-{act}-{year}-{ROMAN}``) lists the sections of one
  chapter as ``Section`` rows (e.g. division XIIA -> sections 712A.1-712A.91).
  A repealed Act (e.g. Act 120 of 1937) renders only a section-range repeal
  note (``5.1-5.5 Repealed.``) with no sections.
* **Invalid/repealed behavior (VERIFIED via archived captures)**: a
  well-formed objectName that does not resolve to current content (e.g.
  ``MCL-10-31``, a section of the repealed Act 302 of 1945) returns
  **HTTP 400 with an \"Error - Michigan Legislature\" page** (no statute
  content, no fallback to another section). A malformed objectName
  (``MCL-``) returns HTTP 404 (\"The specified URL cannot be found.\").
  Repealed sections behave exactly like nonexistent ones: absent ->
  ``RefNotFoundError`` (the Iowa/California \"repealed = absent\"
  convention). Valid sections (e.g. ``MCL-712A-2D``, upper or lower case)
  return HTTP 200 with full content, so the 400 is not a case-sensitivity
  artifact.
* **Silent fallback**: none. The 400 \"Error\" page contains no section
  content; the adapter additionally content-verifies the page title
  (``MCL - Section {citation}``) and the declared section head before
  accepting a result, so a wrong page can never be silently accepted.
* **Versioning**: every page header carries a global \"MCL Complete Through
  PA {n} of {year}\" banner; it is a site-wide stamp, not per-section data,
  and is ignored.
* **Encoding**: UTF-8 HTML; the shared ``fetch_url`` helper is used
  directly.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/michigan.md``): the live host cannot be exercised from this
environment (bot-challenge 403), so the invalid/repealed behavior relies on
the archived captures above and a defensive content check. Lettered
sections are verified; decimal section citations were not observed in the
archived corpus. Some large chapters contain many Acts, making
``list_sections`` a bounded multi-request walk (the only faithful
chapter->sections path the source offers).
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


class MichiganAdapter(BaseStateAdapter):
    """Concrete state adapter for the Michigan Compiled Laws at
    legislature.mi.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The MCL maps onto the
    framework's three-level ref model as a synthetic title -> chapter ->
    citation, with the real Act/Division levels folded into discovery. See
    the module docstring.
    """

    BASE_URL = "https://www.legislature.mi.gov"
    MCL_PATH = "/Laws/MCL"
    CHAPTER_INDEX_PATH = "/Laws/ChapterIndex"
    DEFAULT_TIMEOUT_SECONDS = 30

    # The single synthetic title covering the entire code (the state has no
    # formal title level) -- the Minnesota/Wisconsin precedent.
    SYNTHETIC_TITLE = "MCL"

    # A full MCL section citation '{chapter}.{section}': the chapter is an
    # integer with an optional trailing letter (e.g. '712A'), the section an
    # integer with an optional decimal and optional trailing letter (e.g.
    # '2d', '13a'). The objectName is 'mcl-{chapter}-{section}'.
    _CITATION = re.compile(r"^(\d+[A-Z]?)\.(\d+(?:\.\d+)?[a-zA-Z]?)$")

    # A chapter identifier: an integer with an optional trailing letter.
    _CHAPTER = re.compile(r"^\d+[A-Z]?$")

    # A chapter row on the ChapterIndex page, e.g.
    # '<tr><td><a href="...mcl-chap1">Chapter 1</a></td><td>Constitution of
    #  the State of Michigan of 1963</td></tr>'.
    _CHAPTER_ROW = re.compile(
        r'<a href="[^"]*mcl-chap(\d+[A-Z]?)"[^>]*>\s*Chapter\s+\d+[A-Z]?\s*</a>'
        r"\s*</td>\s*<td>\s*(.*?)\s*</td>",
        re.DOTALL,
    )

    # An Act row on a chapter page, e.g.
    # '<a href="...mcl-Act-282-of-1945">Act 282 of 1945</a>'.
    _ACT_ROW = re.compile(
        r'<a href="[^"]*objectName=(mcl-Act-[^"?]+)"[^>]*>\s*Act\s+[^<]+</a>',
        re.DOTALL,
    )

    # A generic table row on an Act/Division page, e.g.
    # '<tr><td><a href="...mcl-6-1">Section 6.1</a></td><td>Section</td>...'
    # or '<tr><td><a href="...mcl-288-1939-I">288-1939-I</a></td>
    #  <td>Division</td>...'. group(1) = objectName, group(2) = link label,
    # group(3) = row type ('Section' | 'Division').
    _TABLE_ROW = re.compile(
        r'<tr>\s*<td><a href="[^"]*objectName=([^"?]+)"[^>]*>(.*?)</a></td>'
        r"\s*<td>([A-Za-z]+)</td>",
        re.DOTALL,
    )

    # The section page title element, e.g.
    # '<title>MCL - Section 750.82 - Michigan Legislature</title>'.
    _SECTION_TITLE = re.compile(
        r"MCL\s*-\s*Section\s+([0-9A-Za-z.]+)", re.IGNORECASE
    )

    # The section head on a section page, e.g.
    # '<B>750.82 Felonious assault; ...</B>'. group(1) = the declared
    # citation, group(2) = the catchline. The citation pattern is strict so
    # the act-header '<B>' elements (e.g. 'Act 328 of 1931') never match.
    _SECTION_HEAD = re.compile(
        r"<B>\s*(\d+[A-Z]?\.\d+(?:\.\d+)?[a-zA-Z]?)\s+([^<]*?)</B>"
    )

    # The '<P>Sec. 82.</P>' marker that precedes the body.
    _SEC_MARKER = re.compile(r"<P>\s*Sec\.[^<]*</P>", re.IGNORECASE)

    # The leading 'Sec. {n}.' text in the stripped body.
    _SEC_TEXT = re.compile(r"^Sec\.\s*[0-9A-Za-z.]+\s*", re.IGNORECASE)

    # The legislative-history block on a section page.
    _HISTORY_BLOCK = re.compile(
        r'<font size="2">(.*?)</font>', re.DOTALL | re.IGNORECASE
    )

    def __init__(self) -> None:
        """Create the adapter with a per-instance chapter-index cache.

        The chapter index page is ~90 KB and identical across repeated
        discovery calls, so the parsed chapter listing is cached per adapter
        instance. This is instance-local state (each registry owns its own
        constructed adapters), not global mutable state.
        """
        self._chapter_cache: tuple[TocNode, ...] | None = None

    # ------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Michigan."""
        return "MI"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Michigan."""
        return "Michigan"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _section_url(self, chapter: str, section: str) -> str:
        """The direct section URL for ``{chapter}.{section}``."""
        return f"{self.BASE_URL}{self.MCL_PATH}?objectName=mcl-{chapter}-{section}"

    def _chapter_url(self, chapter: str) -> str:
        """The chapter page URL for ``chapter``."""
        return f"{self.BASE_URL}{self.MCL_PATH}?objectName=mcl-chap{chapter}"

    def _object_url(self, object_name: str) -> str:
        """The canonical /Laws/MCL URL for a raw objectName."""
        return f"{self.BASE_URL}{self.MCL_PATH}?objectName={object_name}"

    def _chapter_index_url(self) -> str:
        """The chapter-index URL."""
        return f"{self.BASE_URL}{self.CHAPTER_INDEX_PATH}"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Michigan Legislature URL for ``ref``.

        Args:
            ref: The title (synthetic), chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the chapter-index page (the only page that
              lists the whole code).
            * ``ChapterRef`` -> the chapter page ``mcl-chap{n}``.
            * ``SectionRef`` -> the direct section page ``mcl-{ch}-{sec}``.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If ``ref`` carries an invalid code title,
                chapter, or citation.
        """
        if isinstance(ref, SectionRef):
            match = self._CITATION.fullmatch(ref.identifier)
            if match is None:
                raise RefNotFoundError(
                    f"Invalid Michigan section identifier {ref.identifier!r}: "
                    "expected a '{chapter}.{section}' citation (e.g. "
                    "'712A.2d')."
                )
            return self._section_url(match.group(1), match.group(2))
        elif isinstance(ref, ChapterRef):
            if self._CHAPTER.fullmatch(ref.identifier) is None:
                raise RefNotFoundError(
                    f"Invalid Michigan chapter identifier {ref.identifier!r}."
                )
            return self._chapter_url(ref.identifier)
        elif isinstance(ref, TitleRef):
            if ref.identifier != self.SYNTHETIC_TITLE:
                raise RefNotFoundError(
                    f"Invalid Michigan title {ref.identifier!r}: the only "
                    f"title is the synthetic {self.SYNTHETIC_TITLE!r}."
                )
            return self._chapter_index_url()
        else:
            raise UnsupportedRefError(
                f"MichiganAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached.
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate the single synthetic title of the Michigan Compiled
        Laws.

        Michigan has no formal title level (the chapter index lists chapters
        flatly), so this adapter exposes the whole code as one synthetic
        :class:`TitleRef` -- the Minnesota/Wisconsin precedent. No network
        fetch is required.

        Returns:
            A sequence with a single :class:`TocNode` whose ``ref`` is a
            :class:`TitleRef` with identifier ``"MCL"``.

        Raises:
            This method never raises (the synthetic title is a constant).
        """
        return (
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=self.SYNTHETIC_TITLE,
                name="Michigan Compiled Laws",
                ref=TitleRef(
                    state_code=self.state_code, identifier=self.SYNTHETIC_TITLE
                ),
            ),
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter of the Michigan Compiled Laws from the
        chapter-index page.

        The index page (``/Laws/ChapterIndex``) lists all 241 chapters as
        rows with a ``mcl-chap{n}`` link and the chapter name. The chapter
        identifier is the number in the link (e.g. ``"701"``, ``"712A"``);
        the name is the second cell.

        Args:
            title_ref: The parent (synthetic) title to enumerate chapters
                under. Its identifier must equal ``SYNTHETIC_TITLE``.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order.

        Raises:
            AdapterUnavailableError: If ``title_ref`` is not the synthetic
                title, or the index page cannot be fetched, or no usable
                chapter rows could be parsed from it.
        """
        if title_ref.identifier != self.SYNTHETIC_TITLE:
            raise AdapterUnavailableError(
                f"Michigan has no title {title_ref.identifier!r}; the only "
                f"title is the synthetic {self.SYNTHETIC_TITLE!r}."
            )

        if self._chapter_cache is not None:
            return self._chapter_cache

        url = self._chapter_index_url()
        html = self._fetch_html(url, what="Michigan chapter index")

        chapters: list[TocNode] = []
        for number, raw_name in self._CHAPTER_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=number,
                    name=name or f"Chapter {number}",
                    ref=ChapterRef(title=title_ref, identifier=number),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                "Fetched the Michigan chapter index but found no usable "
                "chapter rows in it; the site's structure may have changed."
            )

        result = tuple(chapters)
        self._chapter_cache = result
        return result

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        Michigan exposes no single chapter->sections page, so this is a
        bounded walk over the chapter's Acts: the chapter page lists the
        Acts in the chapter; an Act page lists either the sections directly
        (``Section`` rows) or the Divisions (``Division`` rows); a Division
        page lists the sections of one chapter. Repealed Acts render only a
        repeal note and contribute no sections (repealed = absent). Empty
        intermediate documents are not errors.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. May be empty for a fully-repealed chapter.

        Raises:
            AdapterUnavailableError: If any discovery page cannot be
                fetched.
            RefNotFoundError: If ``chapter_ref`` carries an invalid chapter
                identifier.
        """
        chapter = chapter_ref.identifier
        if self._CHAPTER.fullmatch(chapter) is None:
            raise RefNotFoundError(
                f"Invalid Michigan chapter identifier {chapter!r}."
            )

        chapter_html = self._fetch_html(
            self._chapter_url(chapter), what="Michigan chapter page"
        )
        act_names = list(self._ACT_ROW.findall(chapter_html))

        sections: list[TocNode] = []
        seen: set[str] = set()
        for act_name in act_names:
            act_html = self._fetch_html(
                self._object_url(act_name), what="Michigan statute Act"
            )
            for obj, _label, row_type in self._TABLE_ROW.findall(act_html):
                if row_type == "Section":
                    citation = self._citation_from_row(obj, _label)
                    self._add_section(sections, seen, chapter_ref, citation, chapter)
                elif row_type == "Division":
                    division_html = self._fetch_html(
                        self._object_url(obj), what="Michigan statute Division"
                    )
                    for obj2, label2, kind2 in self._TABLE_ROW.findall(division_html):
                        if kind2 == "Section":
                            citation = self._citation_from_row(obj2, label2)
                            self._add_section(
                                sections, seen, chapter_ref, citation, chapter
                            )
        return tuple(sections)

    @staticmethod
    def _citation_from_row(object_name: str, label: str) -> str | None:
        """Derive a ``{chapter}.{section}`` citation from a Section row.

        The row label is the canonical form (e.g. ``"Section 712A.2d"``);
        the objectName is the fallback (``mcl-712A-2d``). Returns ``None``
        if neither yields a valid citation.
        """
        stripped = label.strip()
        if stripped.lower().startswith("section "):
            candidate = stripped[len("section ") :].strip()
            if re.fullmatch(r"\d+[A-Z]?\.\d+(?:\.\d+)?[a-zA-Z]?", candidate):
                return candidate
        m = re.fullmatch(r"mcl-(\d+[A-Z]?)-(\d+(?:\.\d+)?[a-zA-Z]?)", object_name)
        if m is not None:
            return f"{m.group(1)}.{m.group(2)}"
        return None

    @staticmethod
    def _add_section(
        sections: list[TocNode],
        seen: set[str],
        chapter_ref: ChapterRef,
        citation: str | None,
        chapter: str,
    ) -> None:
        """Append ``citation`` as a section node under ``chapter_ref`` if it
        is valid, unique, and belongs to ``chapter``."""
        if citation is None or citation in seen:
            return
        if not citation.startswith(f"{chapter}."):
            return
        seen.add(citation)
        sections.append(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=citation,
                name=citation,
                ref=SectionRef(chapter=chapter_ref, identifier=citation),
            )
        )

    # ------------------------------------------------------------
    # Section page parsing (Michigan-specific, kept in the adapter)
    # ------------------------------------------------------------

    @classmethod
    def _extract_catchline(cls, html: str) -> tuple[str, str] | None:
        """Return ``(declared_citation, catchline)`` from the section head,
        or ``None`` if no section head is present."""
        match = cls._SECTION_HEAD.search(html)
        if match is None:
            return None
        return match.group(1), " ".join(strip_tags(match.group(2)).split())

    @classmethod
    def _extract_body(cls, html: str) -> str:
        """Return the section body text (between the section head and the
        history block), with the ``Sec. {n}.`` marker removed."""
        head = cls._SECTION_HEAD.search(html)
        history = cls._HISTORY_BLOCK.search(html)
        start = head.end() if head is not None else 0
        end = history.start() if history is not None else len(html)
        chunk = html[start:end]
        text = " ".join(strip_tags(chunk).split())
        return cls._SEC_TEXT.sub("", text).strip()

    @classmethod
    def _extract_history(cls, html: str) -> str | None:
        """Return the ``History:``/``Former Law:`` block text, or ``None``."""
        history = cls._HISTORY_BLOCK.search(html)
        if history is None:
            return None
        text = " ".join(strip_tags(history.group(1)).split())
        return text or None

    @classmethod
    def _parse_section_page(
        cls, html: str, citation: str, url: str
    ) -> ParsedDocument:
        """Parse a section page into a :class:`ParsedDocument`.

        Args:
            html: The fetched section page HTML.
            citation: The canonical citation that was requested (e.g.
                ``"712A.2d"``).
            url: The source URL.

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"MCL § {citation}"``, ``heading`` = the catchline, ``text`` =
            the body paragraphs, and ``amendment_notes`` = the
            History/Former Law block.

        Raises:
            RefNotFoundError: If the page carries no ``MCL - Section``
                title (the section does not resolve -- including the
                site's HTTP-400 "Error" page if it were served with 200).
            RefMismatchError: If the page declares a different citation than
                requested.
            NormalizationError: If the page declares the section but its
                structure is malformed (no section head, or no body text).
        """
        title = cls._SECTION_TITLE.search(html)
        if title is None:
            raise RefNotFoundError(
                f"Could not find the Michigan section {citation!r}: the page "
                "carries no 'MCL - Section' title (the section does not "
                "resolve)."
            )
        if title.group(1) != citation:
            raise RefMismatchError(
                f"Requested Michigan section {citation!r} does not match the "
                f"section found on the fetched page: {title.group(1)!r}."
            )

        head = cls._extract_catchline(html)
        if head is None:
            raise NormalizationError(
                "The fetched Michigan section page contained no section "
                "heading; the site's structure may have changed."
            )
        declared, catchline = head
        if declared != citation:
            raise RefMismatchError(
                f"Requested Michigan section {citation!r} does not match the "
                f"section heading found on the fetched page: {declared!r}."
            )

        text = cls._extract_body(html)
        if not text:
            raise NormalizationError(
                "The fetched Michigan section page declared its section "
                f"({declared!r}) but contained no body text; the site's "
                "structure may have changed."
            )

        amendment_notes = cls._extract_history(html)

        return ParsedDocument(
            raw_citation=f"MCL § {citation}",
            heading=catchline or None,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Michigan.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` must appear within
        ``parsed.raw_citation``.

        ``status`` is always ``UNKNOWN``: the Michigan source signals
        repealed/removed sections by their absence (the objectName returns
        HTTP 400 / an Error page), not by a structural status field.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Michigan ref
                (``ref.state_code != "MI"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MichiganAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Michigan Compiled Laws section, end to
        end: validate the citation and cross-check it against the ref's
        chapter -> fetch the direct section page with the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` -> verify the
        page declares the requested citation -> parse into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a Michigan ref
                (``ref.state_code == "MI"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be reached
                for a network reason.
            RefNotFoundError: If the citation is invalid, the section page
                returns HTTP 400/404 (an invalid or repealed section), or
                the fetched page carries no ``MCL - Section`` title.
            RefMismatchError: If the ref's chapter disagrees with the
                citation's chapter, or the fetched page declares a different
                section than requested.
            NormalizationError: If the page declares the section but its
                structure is genuinely malformed.
        """
        match = self._CITATION.fullmatch(ref.identifier)
        if match is None:
            raise RefNotFoundError(
                f"Invalid Michigan section identifier {ref.identifier!r}: "
                "expected a '{chapter}.{section}' citation (e.g. '712A.2d')."
            )
        chapter, section = match.group(1), match.group(2)

        if ref.chapter.identifier != chapter:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not "
                f"match the chapter of the requested section "
                f"{ref.identifier!r}."
            )

        url = self._section_url(chapter, section)
        try:
            html = fetch_url(
                url,
                what="Michigan statute section",
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code in (
                400,
                404,
            ):
                raise RefNotFoundError(
                    f"Could not retrieve the Michigan section at {url!r}: "
                    "it returned an error response (the section is invalid, "
                    "repealed, or does not exist)."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the Michigan statute section at {url!r}: "
                f"{exc}"
            ) from exc

        parsed = self._parse_section_page(html, ref.identifier, url)
        return self.normalize(parsed, ref)