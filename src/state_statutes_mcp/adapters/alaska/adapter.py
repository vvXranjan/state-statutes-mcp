"""AlaskaAdapter: the Alaska-specific concrete state adapter.

Source: the official Alaska Statutes at ``https://www.akleg.gov/basis/
statutes.asp``, published by the Alaska State Legislature / Legislative
Affairs Agency. The Alaska Statutes are served as server-rendered HTML over
ordinary HTTP GETs. The live host is protected by a bot-challenge wall
(HTTP 403 to this environment), so all structure verification and fixtures
below are based on **real archived official captures** of the official host
(retrieved via the Wayback Machine in Aug 2026); they are archived
captures, NOT live captures (the Colorado/Michigan precedent).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/alaska.md``;
all structures verified against real archived official captures):

* **Hierarchy**: ``Title -> Chapter -> Section`` with a citation
  ``{T}.{C}.{S}`` (e.g. ``AS 11.41.100`` = Title 11, Chapter 41, Section
  100). The site zero-pads every component (``01.10.070``). The framework's
  three-level model maps directly: ``TitleRef`` = title number (1-47, as
  the index numbers them), ``ChapterRef`` = the zero-padded ``T.C``
  citation (e.g. ``"11.41"``), ``SectionRef.identifier`` = the full
  zero-padded citation (e.g. ``"11.41.100"``).
* **Title index**: ``statutes.asp`` renders all 47 titles server-side as
  ``<a onclick="loadTOC(N)">Title {NN}. {NAME}</a>``.
* **Title TOC**: ``statutes.asp?media=js&type=TOC&title={T}`` returns the
  chapters of a title as ``<b>Chapter {T.C} {NAME}</b>`` rows.
* **Chapter TOC**: ``statutes.asp?media=js&type=TOC&title={T.C}`` returns
  the sections of a chapter as ``Sec. {T.C.S}. {NAME}`` rows.
* **Section**: ``statutes.asp?media=print&secStart={T.C.S}&secEnd=``
  returns one complete section in a ``<div class="statute">`` block:
  ``<b><a name="{citation}"></a>Sec. {citation}. {catchline.}</b>`` plus the
  body.
* **Invalid-section behavior (VERIFIED via archived captures)**: a
  nonexistent citation (e.g. ``11.71``, ``26.23``, ``34.35``) returns
  **HTTP 404** (\"404 Not Found\"). Valid citations return HTTP 200 with
  the section. The 404 maps to ``RefNotFoundError`` (the Iowa/Michigan
  ``HTTPError.__cause__`` pattern).
* **Silent fallback**: none. The 404 confirms nonexistent citations never
  return a nearby section; the adapter additionally content-verifies the
  page's ``<a name="{citation}">`` anchor and the ``Sec. {citation}.``
  heading against the request, so a wrong section can never be silently
  accepted.
* **Special cases (VERIFIED via archived captures)**:
  * Repealed sections render inline bracketed notes (e.g. ``[Repealed, § 3
    ch 6 SLA 1978.]``) and ARE NOT absent; the adapter preserves the text
    and moves the bracketed note to ``amendment_notes``. ``status`` is
    always ``UNKNOWN`` (prose-only signals are never treated as a
    structural status, per the framework rule).
  * Renumbered sections render a stub (``Sec. {a}. - {b}. [Renumbered as
    AS ...].``) with a \"Repealed or Renumbered\" body marker; the adapter
    preserves the renumber note as the heading, leaves the body empty, and
    keeps the note in ``amendment_notes``.
* **Citation format**: the site uses zero-padded ``T.CC.SSS`` (title 2
  digits, chapter 2 digits, section 3 digits). User input is canonicalized
  (``1.10.7`` -> ``01.10.007``). No lettered or decimal section citations
  were observed in the archived corpus, so only the strict numeric format
  is accepted.
* **Encoding**: the official pages are ISO-8859-1 (verified via a 0xA7
  ``§`` byte in a repealed-note capture and the index's charset
  declaration), so this adapter performs its own ``urllib`` fetch and
  decodes as ``windows-1252`` (the Oregon precedent) rather than the shared
  UTF-8 ``fetch_url``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/alaska.md``): the live host cannot be exercised from this
environment (bot-challenge 403), so behavior relies on the archived
captures above plus defensive content checks. Repealed sections render
their text with an inline note (not absent), which differs from the
Iowa/California \"absent\" convention and is handled deliberately. No
lettered/decimal section citations were verified.
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
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus


class AlaskaAdapter(BaseStateAdapter):
    """Concrete state adapter for the Alaska Statutes at akleg.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The Alaska Statutes map
    directly onto the framework's three-level model as title -> chapter ->
    citation. See the module docstring.
    """

    BASE_URL = "https://www.akleg.gov"
    BASIS_PATH = "/basis/statutes.asp"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A full citation '{T}.{C}.{S}' with 1-2 digit title, 1-2 digit
    # chapter, 1-3 digit section (the site zero-pads to 2/2/3).
    _CITATION = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,3})$")

    # A chapter citation '{T}.{C}'.
    _CHAPTER = re.compile(r"^\d{1,2}\.\d{1,2}$")

    # A title row on the index page, e.g.
    # '<li><a onclick="loadTOC(1);" href="javascript:void(0);">Title 01.
    #  GENERAL PROVISIONS </a></li>'. group(1) = the title number the site
    # uses to load its TOC, group(2) = the title name.
    _TITLE_ROW = re.compile(
        r'loadTOC\((\d+)\);[^>]*>Title\s+\d+\.\s*(.*?)\s*</a>', re.DOTALL
    )

    # A chapter row in a title TOC, e.g.
    # '<li><a onclick=loadTOC("11.05"); href=javascript:void(0) ><b>Chapter
    #  11.05 PUNISHMENT</h6> </a></li>'. group(1) = the chapter citation,
    # group(2) = the chapter name.
    _CHAPTER_ROW = re.compile(
        r'loadTOC\("(\d{1,2}\.\d{1,2})"\);[^>]*><b>Chapter\s+'
        r"\d{1,2}\.\d{1,2}\s+(.*?)\s*</a>",
        re.DOTALL,
    )

    # A section row in a chapter TOC, e.g.
    # '<li><a onclick=loadTOC("01"); href=statutes.asp?year=2016&title=1
    #  #01.10.010 >Sec. 01.10.010. Applicability of common law. </a></li>'.
    # group(1) = the section citation (from the href anchor), group(2) =
    # the section name (may contain nested <a> tags).
    _SECTION_ROW = re.compile(
        r'href=statutes\.asp[^>]*#(\d{2}\.\d{2}\.\d{3})[^>]*>\s*'
        r"Sec\.\s+\d{2}\.\d{2}\.\d{3}\.\s*(.*?)\s*</a></li>",
        re.DOTALL,
    )

    # The section block on a section page.
    _STATUTE = re.compile(r'<div class="statute">(.*?)</div>', re.DOTALL)

    # The section head, e.g.
    # '<b><a name="01.10.070"></a>Sec. 01.10.070. Time statutes become law
    #  and take effect.</b>' (or the renumbered variant with a nested
    #  '<i>' and a '[Renumbered as ...]' note). group(1) = the declared
    #  citation anchor, group(2) = the 'Sec. ...' text.
    _HEAD = re.compile(
        r"<b[^>]*>(?:<i>)?<a name=\"([^\"]+)\"[^>]*>\s*</a>(?:</i>)?"
        r"\s*Sec\.\s+(.*?)</b>",
        re.DOTALL,
    )

    # The declared citation + catchline from the section head text, e.g.
    # '01.10.070. Time statutes become law and take effect.'.
    _DECLARED = re.compile(r"^(\d{2}\.\d{2}\.\d{3})\.\s*(.*)$", re.DOTALL)

    # Bracketed history/amendment notes in the body, e.g.
    # '[Repealed, § 3 ch 6 SLA 1978.]'.
    _HISTORY = re.compile(r"\[[^\]]*\]")

    # A renumbered stub's body marker.
    _STUB = re.compile(r"^Repealed or Renumbered\s*$", re.IGNORECASE)

    def __init__(self) -> None:
        """Create the adapter with a per-instance title-list cache.

        The title index page is ~18 KB and identical across repeated
        discovery calls, so the parsed title listing is cached per adapter
        instance. This is instance-local state (each registry owns its own
        constructed adapters), not global mutable state.
        """
        self._title_cache: tuple[TocNode, ...] | None = None

    # ------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Alaska."""
        return "AK"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Alaska."""
        return "Alaska"

    # ------------------------------------------------------------
    # Citation normalization
    # ------------------------------------------------------------

    @staticmethod
    def _canonical_citation(citation: str) -> str | None:
        """Canonicalize a citation to the official zero-padded
        ``T.CC.SSS`` form (e.g. ``"1.10.7"`` -> ``"01.10.007"``).

        Returns ``None`` if ``citation`` is not a numeric ``T.C.S``
        citation (lettered/decimal forms were not verified and are
        rejected).
        """
        match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{1,3})", citation)
        if match is None:
            return None
        return (
            f"{int(match.group(1)):02d}.{int(match.group(2)):02d}."
            f"{int(match.group(3)):03d}"
        )

    @staticmethod
    def _canonical_chapter(chapter: str) -> str | None:
        """Canonicalize a chapter citation to the zero-padded ``T.CC``
        form (e.g. ``"1.5"`` -> ``"01.05"``). Returns ``None`` if invalid."""
        match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", chapter)
        if match is None:
            return None
        return f"{int(match.group(1)):02d}.{int(match.group(2)):02d}"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _index_url(self) -> str:
        """The title-index URL."""
        return f"{self.BASE_URL}{self.BASIS_PATH}"

    def _toc_url(self, title_param: str) -> str:
        """The TOC URL for a title (``title={T}``) or chapter
        (``title={T.C}``)."""
        return (
            f"{self.BASE_URL}{self.BASIS_PATH}?media=js&type=TOC"
            f"&title={title_param}"
        )

    def _section_url(self, citation: str) -> str:
        """The section URL for a full citation."""
        return (
            f"{self.BASE_URL}{self.BASIS_PATH}?media=print"
            f"&secStart={citation}&secEnd="
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Alaska Legislature URL for ``ref``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the title TOC page.
            * ``ChapterRef`` -> the chapter TOC page.
            * ``SectionRef`` -> the section print page.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If ``ref`` carries an invalid title, chapter,
                or citation.
        """
        if isinstance(ref, SectionRef):
            citation = self._canonical_citation(ref.identifier)
            if citation is None:
                raise RefNotFoundError(
                    f"Invalid Alaska section identifier {ref.identifier!r}: "
                    "expected a '{T}.{C}.{S}' citation (e.g. '11.41.100')."
                )
            return self._section_url(citation)
        elif isinstance(ref, ChapterRef):
            chapter = self._canonical_chapter(ref.identifier)
            if chapter is None:
                raise RefNotFoundError(
                    f"Invalid Alaska chapter identifier {ref.identifier!r}."
                )
            return self._toc_url(chapter)
        elif isinstance(ref, TitleRef):
            if re.fullmatch(r"\d{1,2}", ref.identifier) is None:
                raise RefNotFoundError(
                    f"Invalid Alaska title {ref.identifier!r}."
                )
            return self._toc_url(ref.identifier)
        else:
            raise UnsupportedRefError(
                f"AlaskaAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch helper (adapter-local: the official pages are
    # ISO-8859-1, so the shared UTF-8 fetch_url is not used; see the
    # Oregon precedent)
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its HTML decoded as ``windows-1252``.

        Args:
            url: The URL to fetch.
            what: A short human-readable description used for error
                messages.

        Returns:
            The fetched content decoded as ``windows-1252``.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached (network
                failure or non-2xx HTTP response, including HTTP 404/400
                which callers may re-map).
        """
        try:
            with urllib.request.urlopen(  # noqa: S310
                url,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                return response.read().decode("windows-1252")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Alaska Statutes from the index
        page.

        The index page renders all 47 titles server-side. The title
        identifier is the number the site itself uses to load its TOC
        (e.g. ``"1"``, ``"11"``); the name is the displayed title name.

        Returns:
            A sequence of :class:`TocNode`, one per title, in document
            order.

        Raises:
            AdapterUnavailableError: If the index cannot be fetched, or if
                no usable title rows could be parsed from it.
        """
        if self._title_cache is not None:
            return self._title_cache

        html = self._fetch_html(self._index_url(), what="Alaska Statutes index")
        titles: list[TocNode] = []
        for number, raw_name in self._TITLE_ROW.findall(html):
            name = " ".join(strip_tags(raw_name).split())
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=number,
                    name=name or f"Title {number}",
                    ref=TitleRef(
                        state_code=self.state_code, identifier=number
                    ),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                "Fetched the Alaska Statutes index but found no usable "
                "title rows in it; the site's structure may have changed."
            )

        result = tuple(titles)
        self._title_cache = result
        return result

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title TOC.

        ``ChapterRef.identifier`` is the zero-padded chapter citation
        (e.g. ``"11.41"``).

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order.

        Raises:
            AdapterUnavailableError: If the title TOC cannot be fetched, or
                if no usable chapter rows could be parsed from it.
            RefNotFoundError: If ``title_ref`` carries an invalid title.
        """
        if re.fullmatch(r"\d{1,2}", title_ref.identifier) is None:
            raise RefNotFoundError(
                f"Invalid Alaska title {title_ref.identifier!r}."
            )

        url = self._toc_url(title_ref.identifier)
        html = self._fetch_html(url, what="Alaska title table of contents")

        chapters: list[TocNode] = []
        for citation, raw_name in self._CHAPTER_ROW.findall(html):
            identifier = self._canonical_chapter(citation)
            if identifier is None:
                continue
            name = " ".join(strip_tags(raw_name).split())
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
                f"Fetched the Alaska title TOC for title "
                f"{title_ref.identifier!r} but found no usable chapter "
                "rows in it; the site's structure may have changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        TOC.

        ``SectionRef.identifier`` is the full zero-padded citation (e.g.
        ``"11.41.100"``).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order.

        Raises:
            AdapterUnavailableError: If the chapter TOC cannot be fetched.
            RefNotFoundError: If ``chapter_ref`` carries an invalid chapter
                identifier.
        """
        chapter = self._canonical_chapter(chapter_ref.identifier)
        if chapter is None:
            raise RefNotFoundError(
                f"Invalid Alaska chapter identifier {chapter_ref.identifier!r}."
            )

        url = self._toc_url(chapter)
        html = self._fetch_html(url, what="Alaska chapter table of contents")

        sections: list[TocNode] = []
        seen: set[str] = set()
        for citation, raw_name in self._SECTION_ROW.findall(html):
            identifier = self._canonical_citation(citation)
            if identifier is None or identifier in seen:
                continue
            seen.add(identifier)
            name = " ".join(strip_tags(raw_name).split())
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name or identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )
        return tuple(sections)

    # ------------------------------------------------------------
    # Section page parsing (Alaska-specific, kept in the adapter)
    # ------------------------------------------------------------

    @staticmethod
    def _clean(html_fragment: str) -> str:
        """Strip tags from ``html_fragment``, decode entities, and
        normalize whitespace (including non-breaking spaces)."""
        return " ".join(strip_tags(html_fragment).replace("\xa0", " ").split())

    @classmethod
    def _parse_section_page(
        cls, html: str, citation: str, url: str
    ) -> ParsedDocument:
        """Parse a section page into a :class:`ParsedDocument`.

        Args:
            html: The fetched section page HTML.
            citation: The canonical citation that was requested (e.g.
                ``"01.10.070"``).
            url: The source URL.

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"AS {citation}"``, ``heading`` = the catchline, ``text`` =
            the body (with bracketed history notes removed), and
            ``amendment_notes`` = the bracketed history notes. Renumbered
            stubs preserve the note as the heading with an empty body.

        Raises:
            RefNotFoundError: If the page carries no statute block or no
                section head (the section does not resolve).
            RefMismatchError: If the page declares a different citation
                than requested (silent-fallback protection).
            NormalizationError: If the section head is present but the
                structure is malformed (unparseable head, or an empty body
                that is not a renumbered stub).
        """
        block = cls._STATUTE.search(html)
        if block is None:
            raise RefNotFoundError(
                f"Could not find the Alaska section {citation!r}: the page "
                "carries no statute content (the section does not resolve)."
            )
        content = block.group(1)

        head = cls._HEAD.search(content)
        if head is None:
            raise RefNotFoundError(
                f"Could not find the Alaska section {citation!r}: the page "
                "carries no 'Sec.' section heading."
            )
        anchor_citation = head.group(1)
        if anchor_citation != citation:
            raise RefMismatchError(
                f"Requested Alaska section {citation!r} does not match the "
                f"section found on the fetched page: {anchor_citation!r}."
            )

        rest_text = cls._clean(head.group(2))
        declared = cls._DECLARED.match(rest_text)
        if declared is None:
            raise NormalizationError(
                "The fetched Alaska section page contained an unparseable "
                "section heading; the site's structure may have changed."
            )
        declared_citation, catchline = declared.group(1), declared.group(2).strip()
        if declared_citation != citation:
            raise RefMismatchError(
                f"Requested Alaska section {citation!r} does not match the "
                f"section heading found on the fetched page: "
                f"{declared_citation!r}."
            )

        body_html = content[head.end():]
        body_text = cls._clean(body_html)

        history_notes = cls._HISTORY.findall(body_text)
        amendment_notes = " ".join(history_notes).strip() or None
        body_without_notes = cls._HISTORY.sub("", body_text).strip()

        # A renumbered stub renders only a 'Repealed or Renumbered' marker
        # as its body; the renumber note lives in the catchline.
        if cls._STUB.match(body_without_notes):
            return ParsedDocument(
                raw_citation=f"AS {citation}",
                heading=catchline or None,
                text="",
                amendment_notes=catchline or None,
                source_url=url,
                retrieved_at=datetime.now(timezone.utc),
            )

        if not body_without_notes:
            raise NormalizationError(
                "The fetched Alaska section page declared its section "
                f"({declared_citation!r}) but contained no body text; the "
                "site's structure may have changed."
            )

        return ParsedDocument(
            raw_citation=f"AS {citation}",
            heading=catchline or None,
            text=body_without_notes,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Alaska.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` must appear within
        ``parsed.raw_citation``.

        ``status`` is always ``UNKNOWN``: the Alaska source signals
        repealed/renumbered sections only as prose (bracketed notes and
        'Repealed or Renumbered' markers), never as a structural status
        field.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Alaska ref
                (``ref.state_code != "AK"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"AlaskaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Alaska Statutes section, end to end:
        canonicalize the citation and cross-check it against the ref's
        chapter -> fetch the section page with the adapter-local
        windows-1252 fetch -> verify the page declares the requested
        citation -> parse into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be an Alaska ref
                (``ref.state_code == "AK"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be reached
                for a network reason (including non-404 HTTP errors).
            RefNotFoundError: If the citation is invalid, the section page
                returns HTTP 404 (a nonexistent section), or the fetched
                page carries no statute content / section head.
            RefMismatchError: If the ref's chapter disagrees with the
                citation's chapter, or the fetched page declares a
                different section than requested.
            NormalizationError: If the page declares the section but its
                structure is genuinely malformed.
        """
        citation = self._canonical_citation(ref.identifier)
        if citation is None:
            raise RefNotFoundError(
                f"Invalid Alaska section identifier {ref.identifier!r}: "
                "expected a '{T}.{C}.{S}' citation (e.g. '11.41.100')."
            )
        title, chapter, _section = citation.split(".")

        if self._canonical_chapter(ref.chapter.identifier) != f"{title}.{chapter}":
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not "
                f"match the chapter of the requested section "
                f"{ref.identifier!r}."
            )

        url = self._section_url(citation)
        try:
            html = self._fetch_html(url, what="Alaska statute section")
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not retrieve the Alaska section at {url!r}: it "
                    "returned HTTP 404 (the section does not exist)."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the Alaska statute section at {url!r}: {exc}"
            ) from exc

        parsed = self._parse_section_page(html, citation, url)

        if citation != ref.identifier:
            ref = ref.model_copy(update={"identifier": citation})
        return self.normalize(parsed, ref)