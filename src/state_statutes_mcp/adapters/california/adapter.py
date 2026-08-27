"""CaliforniaAdapter: the California-specific concrete state adapter.

Source: the official California Legislative Information site,
``https://leginfo.legislature.ca.gov``, run by the California Legislature.
The California Codes are served as server-rendered HTML over ordinary HTTP
GETs -- no JavaScript execution, no browser automation, and no bulk archive
is required. This is the framework's first fully server-rendered-HTML
adapter with a four-level hierarchy folded into the three-level ref model.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/california.md``;
all structures verified against real live captures of the official host on
Aug 27 2026 from this environment):

* **Hierarchy**: the real structure is ``Code -> Division -> Chapter ->
  Article -> Section`` with an optional ``Part`` level and a top-level
  ``General Provisions`` node that has no division. The framework's
  three-level model is preserved by folding: ``TitleRef`` = the Code
  (e.g. ``"BPC"``), ``ChapterRef`` = one fetchable statute document (the
  ``codes_displayText`` page identified by its ``division/part/chapter/
  article`` segments), and ``SectionRef.identifier`` = the section number.
  No intermediate level becomes a new framework level.
* **Codes index**: ``/faces/codesTOC.xhtml`` lists every code as
  ``codesTOCSelected.xhtml?tocCode={CODE}&tocTitle={NAME}``. 29 statute
  codes are exposed; the California Constitution (``CONS``) is a separate
  document and is excluded from ``list_titles``.
* **Code tree**: ``/faces/codedisplayexpand.xhtml?tocCode={CODE}`` returns
  the ENTIRE code tree in one request. Each fetchable leaf document is a
  ``codes_displayText.xhtml`` link carrying the exact ``division/part/
  chapter/article`` query parameters (992 documents for BPC). Divisions,
  parts, and chapters that merely expand the tree use
  ``codes_displayexpandedbranch.xhtml`` links and are not documents.
* **Document page**: ``/faces/codes_displayText.xhtml?lawCode={CODE}&
  division={D}&title=&part={P}&chapter={C}&article={A}`` returns the full
  server-rendered statute text of one article (or of a chapter with no
  articles, a part, a division, or the General Provisions). Sections are
  listed as ``submitCodesValues('{N}.', ...)`` anchors. Empty or
  "not found" documents (e.g. BPC Division 6, or a nonexistent segment
  combination) render HTTP 200 with no section content -- an empty
  document, not an error.
* **Section page**: ``/faces/codes_displaySection.xhtml?lawCode={CODE}&
  sectionNum={N}`` returns one COMPLETE section, server-rendered, in a
  ``<div id="codeLawSectionNoHead">`` block: an ``<h4><b>`` breadcrumb
  (code, division, chapter, article), an ``<h6><b>{N}.`` section-number
  heading, ``<p>`` body paragraphs, and a trailing ``<i>`` legislative
  history line. Verified for BPC 5000/5025.3, CIV 43.3/1624, PEN 187, VEH
  23152, GOV 12940, WIC 5325.
* **Invalid section behavior (VERIFIED)**: a nonexistent or removed/
  repealed section (e.g. BPC 999999, PEN 12020) returns HTTP 200 with NO
  ``codeLawSectionNoHead`` content block -- the empty-response signal the
  adapter maps to ``RefNotFoundError``. Repealed-and-removed sections are
  therefore indistinguishable from never-existent ones (the Iowa
  convention).
* **Invalid code behavior (VERIFIED)**: an unknown code, or a lowercase
  code, causes the site to 302-redirect to ``codes.xhtml`` (followed by
  the shared fetch helper), yielding a page with no section content.
  Codes are validated and upper-cased before any request.
* **Leading zeros (VERIFIED)**: ``sectionNum=05000`` is NOT treated as
  ``5000`` by the site (it returns an empty page), so the adapter
  canonicalizes section identifiers (``05000`` -> ``5000``) before
  requesting, and cross-checks the canonical form against the declared
  section.
* **Query form (VERIFIED)**: dotless query values work identically to the
  site's own dotted hrefs (``division=3&chapter=1&article=1`` returns the
  same page as ``division=3.&chapter=1.&article=1.``), so the adapter uses
  a clean dotless canonical form.
* **Encoding**: UTF-8 HTML throughout; the shared ``fetch_url`` helper is
  used directly.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/california.md``): only BPC (fully), plus representative
sections of CIV/PEN/VEH/GOV/WIC, were live-captured; uniformity across all
29 codes is otherwise UNVERIFIED. Some intermediate documents are
legitimately empty (e.g. BPC Division 6). ``robots.txt`` on the host
disallows bulk crawling (``Disallow: /``, ``Crawl-Delay: 10``); this
adapter performs targeted single-document requests only. Sections carry no
catchline/short title, so ``heading`` is ``None``.
"""

from __future__ import annotations

import html as _html
import re
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


class CaliforniaAdapter(BaseStateAdapter):
    """Concrete state adapter for the California Codes at
    leginfo.legislature.ca.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The California Code maps
    onto the framework's three-level ref model as Code -> (folded
    Division/Part/Chapter/Article document) -> Section, with the real
    hierarchy folded so no intermediate level becomes a new framework
    level. See the module docstring.
    """

    BASE_URL = "https://leginfo.legislature.ca.gov"
    FACES_PATH = "/faces"
    DEFAULT_TIMEOUT_SECONDS = 30

    # The Constitution is a separate document, not a statute code; it is
    # excluded from the statute title listing (and rejected in validation).
    CONSTITUTION_CODE = "CONS"

    # A valid California statute code: 2-4 upper-case letters.
    _CODE_PATTERN = re.compile(r"[A-Z]{2,4}")

    # A valid section identifier: integer or decimal (e.g. "5000", "5025.3").
    _SECTION_PATTERN = re.compile(r"\d+(?:\.\d+)?")

    # A valid hierarchy segment: integer or decimal, possibly repeated
    # (e.g. "3", "1.5", "10.7"); empty is allowed for absent levels.
    _SEGMENT_PATTERN = re.compile(r"\d+(?:\.\d+)*")

    # A code row on the codes index page, e.g.
    # 'codesTOCSelected.xhtml?tocCode=BPC&tocTitle=+Business+and+Professions
    #  +Code+-+BPC'.
    _TOC_CODE = re.compile(
        r"codesTOCSelected\.xhtml\?tocCode=([A-Z]+)(?:&amp;|&)"
        r"tocTitle=([^\"']*)"
    )

    # A fetchable document row on the code-tree page, e.g.
    # '<a href="/faces/codes_displayText.xhtml?lawCode=BPC&division=3.&
    #   title=&part=&chapter=1.&article=1." ...><div ...> ARTICLE 1.
    #   Administration </div>'.
    _TREE_ROW = re.compile(
        r'<a href="([^"]*codes_displayText\.xhtml\?[^"]*)"[^>]*>'
        r'\s*<div[^>]*>\s*(.*?)\s*</div>',
        re.DOTALL,
    )

    # A query parameter inside a tree href, e.g. 'division=3.'.
    _QUERY_PARAM = re.compile(r"([A-Za-z]+)=([^&\"']*)")

    # A section anchor on a document page, e.g.
    # "submitCodesValues('5000.', '5.1.1', '2024', ...)".
    _SECTION_ANCHOR = re.compile(r"submitCodesValues\('([^']+)'")

    # The content block on a section page.
    _SECTION_NOHEAD = re.compile(
        r'<div id="codeLawSectionNoHead">(.*?)</div>\s*</div>\s*</BODY>',
        re.DOTALL,
    )

    # The section's own text block (section number heading, body paragraphs,
    # history) inside the content block.
    _FONT_BLOCK = re.compile(r'<font face="Times New Roman">(.*?)</font>', re.DOTALL)

    # A breadcrumb heading inside the section content block, e.g.
    # '<h4><b>Business and Professions Code - BPC</b></h4>'.
    _BREADCRUMB = re.compile(r"<h4[^>]*><b>(.*?)</b></h4>", re.DOTALL)

    # The declared section number, e.g.
    # '<h6 style="float:left;"><b>5000.  </b></h6>'.
    _DECLARED_SECTION = re.compile(
        r'<h6 style="float:left;"><b>([^<]+)</b></h6>'
    )

    # A body paragraph inside the section text, e.g.
    # '<p style="margin:0 0 0.5em 0;">(a) ...</p>'.
    _BODY_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)

    # The legislative history line(s) inside the section text, e.g.
    # '<i>(Amended by Stats. 2024, Ch. 586, Sec. 1. ...)</i>'.
    _HISTORY_I = re.compile(r"<i>(.*?)</i>", re.DOTALL)

    def __init__(self) -> None:
        """Create the adapter with a per-instance code-tree cache.

        The code-tree page (``codedisplayexpand.xhtml``) is large (up to
        ~650 KB) and identical across repeated discovery calls, so the
        parsed chapter listing is cached per adapter instance. This is
        instance-local state (each registry owns its own constructed
        adapters), not global mutable state.
        """
        self._tree_cache: dict[str, tuple[TocNode, ...]] = {}

    # ------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for California."""
        return "CA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for California."""
        return "California"

    # ------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------

    def _valid_code(self, code: str) -> str:
        """Validate and normalize a California code identifier.

        The site requires upper-case codes; lower-case or unknown codes
        cause a redirect to the codes index (no content). Codes are
        upper-cased and restricted to the expected alphabetic form. The
        Constitution (``CONS``) is not a statute code.

        Args:
            code: The raw code identifier (e.g. ``"BPC"``, ``"bpc"``).

        Returns:
            The normalized upper-case code (e.g. ``"BPC"``).

        Raises:
            RefNotFoundError: If ``code`` is not a valid upper-case
                alphabetic statute code (or is the Constitution).
        """
        normalized = code.upper()
        if (
            normalized == self.CONSTITUTION_CODE
            or self._CODE_PATTERN.fullmatch(normalized) is None
        ):
            raise RefNotFoundError(
                f"Invalid California code {code!r}: expected a 2-4 letter "
                "upper-case statute code (e.g. 'BPC')."
            )
        return normalized

    @staticmethod
    def _canonical_section(section: str) -> str | None:
        """Canonicalize a California section identifier.

        The site does not treat ``05000`` as ``5000``, so leading zeros are
        stripped from the integer part. Returns ``None`` for identifiers
        that are not an integer or decimal number.

        Args:
            section: The raw section identifier (e.g. ``"5000"``,
                ``"5025.3"``, ``"05000"``, ``"1A"``).

        Returns:
            The canonical form (e.g. ``"5000"``, ``"5025.3"``), or ``None``
            if the identifier is not a valid number.
        """
        match = re.fullmatch(r"(\d+)(?:\.(\d+))?", section)
        if match is None:
            return None
        integer = str(int(match.group(1)))
        decimal = match.group(2)
        return f"{integer}.{decimal}" if decimal is not None else integer

    def _parse_chapter(self, identifier: str) -> tuple[str, str, str, str]:
        """Parse a ChapterRef identifier into its four query segments.

        The identifier is ``"{division}/{part}/{chapter}/{article}"`` where
        absent levels are empty (e.g. ``"3///1/1"`` for Division 3, Chapter
        1, Article 1; ``"////"`` for the General Provisions; ``"4/3//"``
        for Division 4, Part 3).

        Args:
            identifier: The ChapterRef identifier.

        Returns:
            ``(division, part, chapter, article)`` as dotless numeric
            strings or empty strings.

        Raises:
            RefNotFoundError: If the identifier does not have exactly four
                segments or any non-empty segment is not numeric.
        """
        parts = identifier.split("/")
        if len(parts) != 4:
            raise RefNotFoundError(
                f"Invalid California chapter identifier {identifier!r}: "
                "expected four 'division/part/chapter/article' segments."
            )
        for segment in parts:
            if segment and self._SEGMENT_PATTERN.fullmatch(segment) is None:
                raise RefNotFoundError(
                    f"Invalid California chapter identifier {identifier!r}: "
                    f"segment {segment!r} is not a valid numeric hierarchy "
                    "component."
                )
        return parts[0], parts[1], parts[2], parts[3]

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def _codes_toc_url(self) -> str:
        """The codes index URL."""
        return f"{self.BASE_URL}{self.FACES_PATH}/codesTOC.xhtml"

    def _tree_url(self, code: str) -> str:
        """The full code-tree URL for ``code``."""
        return f"{self.BASE_URL}{self.FACES_PATH}/codedisplayexpand.xhtml?tocCode={code}"

    def _document_url(
        self,
        code: str,
        division: str,
        part: str,
        chapter: str,
        article: str,
    ) -> str:
        """The fetchable document URL for one division/part/chapter/article."""
        return (
            f"{self.BASE_URL}{self.FACES_PATH}/codes_displayText.xhtml"
            f"?lawCode={code}&division={division}&title=&part={part}"
            f"&chapter={chapter}&article={article}"
        )

    def _section_url(self, code: str, section: str) -> str:
        """The single-section URL for ``code`` section ``section``."""
        return (
            f"{self.BASE_URL}{self.FACES_PATH}/codes_displaySection.xhtml"
            f"?lawCode={code}&sectionNum={section}"
        )

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official California URL needed to retrieve ``ref``.

        Args:
            ref: The title (code), chapter (hierarchy document), or section
                to address.

        Returns:
            The official URL:
            * ``TitleRef`` -> the code's full tree page.
            * ``ChapterRef`` -> the fetchable document page identified by
              its ``division/part/chapter/article`` segments.
            * ``SectionRef`` -> the single-section page.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
            RefNotFoundError: If ``ref`` carries an invalid code, chapter
                identifier, or section identifier.
        """
        if isinstance(ref, SectionRef):
            code = self._valid_code(ref.chapter.title.identifier)
            section = self._canonical_section(ref.identifier)
            if section is None:
                raise RefNotFoundError(
                    f"Invalid California section identifier {ref.identifier!r}."
                )
            return self._section_url(code, section)
        elif isinstance(ref, ChapterRef):
            code = self._valid_code(ref.title.identifier)
            division, part, chapter, article = self._parse_chapter(ref.identifier)
            return self._document_url(code, division, part, chapter, article)
        elif isinstance(ref, TitleRef):
            code = self._valid_code(ref.identifier)
            return self._tree_url(code)
        else:
            raise UnsupportedRefError(
                f"CaliforniaAdapter.build_url does not support refs of type "
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
        """Enumerate every statute code of the California Codes.

        The codes index page lists every code as ``tocCode={CODE}`` with a
        ``tocTitle`` name. The California Constitution (``CONS``) is
        excluded -- this adapter is scoped to statutes.

        Returns:
            A sequence of :class:`TocNode`, one per statute code, in
            document order. ``TitleRef.identifier`` is the code (e.g.
            ``"BPC"``).

        Raises:
            AdapterUnavailableError: If the codes index cannot be fetched,
                or if no usable code rows could be parsed.
        """
        html = self._fetch_html(self._codes_toc_url(), what="California codes index")
        codes: list[TocNode] = []
        for code, raw_name in self._TOC_CODE.findall(html):
            if code == self.CONSTITUTION_CODE:
                continue
            name = urllib.parse.unquote_plus(raw_name).strip()
            codes.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=code,
                    name=name or code,
                    ref=TitleRef(state_code=self.state_code, identifier=code),
                )
            )
        if not codes:
            raise AdapterUnavailableError(
                "Fetched the California codes index but found no usable "
                "code rows in it; the site's structure may have changed."
            )
        return tuple(codes)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every fetchable statute document under ``title_ref``.

        The code-tree page (``codedisplayexpand.xhtml``) returns the entire
        hierarchy in one request. Each fetchable leaf document (an article,
        a chapter with no articles, a part, a division, or the General
        Provisions) is a ``codes_displayText.xhtml`` link; tree-expansion
        nodes use ``codes_displayexpandedbranch.xhtml`` and are not
        documents, so they are not emitted.

        ``ChapterRef.identifier`` is the document's
        ``"{division}/{part}/{chapter}/{article}"`` segment path (e.g.
        ``"3///1/1"`` for Division 3, Chapter 1, Article 1; ``"////"`` for
        the General Provisions). Decimal components are preserved.

        Args:
            title_ref: The parent code (e.g. ``"BPC"``).

        Returns:
            A sequence of :class:`TocNode`, one per fetchable document, in
            document order.

        Raises:
            AdapterUnavailableError: If the code-tree page cannot be
                fetched, or if no usable document rows could be parsed.
            RefNotFoundError: If ``title_ref`` is not a valid statute code.
        """
        code = self._valid_code(title_ref.identifier)

        cached = self._tree_cache.get(code)
        if cached is not None:
            return cached

        url = self._tree_url(code)
        html = self._fetch_html(url, what="California code tree")

        chapters: list[TocNode] = []
        seen: set[str] = set()
        for raw_href, raw_label in self._TREE_ROW.findall(html):
            href = _html.unescape(raw_href)
            params = dict(self._QUERY_PARAM.findall(href))
            law_code = params.get("lawCode")
            if law_code != code:
                continue
            division = self._dotless(params.get("division", ""))
            part = self._dotless(params.get("part", ""))
            chapter = self._dotless(params.get("chapter", ""))
            article = self._dotless(params.get("article", ""))
            identifier = f"{division}/{part}/{chapter}/{article}"
            if identifier in seen:
                continue
            seen.add(identifier)
            name = " ".join(strip_tags(raw_label).split())
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
                f"Fetched the California code tree for code {code!r} but "
                "found no usable document rows in it; the site's structure "
                "may have changed."
            )

        result = tuple(chapters)
        self._tree_cache[code] = result
        return result

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref``.

        Fetches the document page identified by ``chapter_ref``'s
        ``division/part/chapter/article`` segments and returns one
        :class:`TocNode` per section, with ``identifier`` the section
        number (e.g. ``"5000"``, ``"5025.3"``).

        An intermediate document may legitimately be empty (e.g. a
        heading-only division, or a segment combination that renders no
        sections); that is an empty listing, not an error.

        Args:
            chapter_ref: The parent document to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. May be empty for a genuinely empty intermediate
            document.

        Raises:
            AdapterUnavailableError: If the document page cannot be
                fetched.
            RefNotFoundError: If ``chapter_ref`` carries an invalid code or
                an invalid segment identifier.
        """
        code = self._valid_code(chapter_ref.title.identifier)
        division, part, chapter, article = self._parse_chapter(chapter_ref.identifier)
        url = self._document_url(code, division, part, chapter, article)
        html = self._fetch_html(url, what="California statute document")

        sections: list[TocNode] = []
        seen: set[str] = set()
        for raw_anchor in self._SECTION_ANCHOR.findall(html):
            identifier = raw_anchor.rstrip(".")
            if not identifier or identifier in seen:
                continue
            if self._SECTION_PATTERN.fullmatch(identifier) is None:
                continue
            seen.add(identifier)
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )
        return tuple(sections)

    @staticmethod
    def _dotless(segment: str) -> str:
        """Strip a trailing dot from a query segment (``"3."`` -> ``"3"``)."""
        return segment[:-1] if segment.endswith(".") else segment

    # ------------------------------------------------------------
    # Section page parsing (California-specific, kept in the adapter)
    # ------------------------------------------------------------

    @classmethod
    def _declared_code(cls, html: str) -> str | None:
        """Return the code the section page declares itself to be.

        The first breadcrumb line is the code line, e.g. ``"Business and
        Professions Code - BPC"``; the code is the token after the last
        ``" - "``.
        """
        matches = cls._BREADCRUMB.findall(html)
        if not matches:
            return None
        code_line = " ".join(strip_tags(matches[0]).split())
        if " - " not in code_line:
            return None
        return code_line.rsplit(" - ", 1)[1].strip()

    @classmethod
    def _declared_section_number(cls, html: str) -> str | None:
        """Return the section number the page declares, or ``None``."""
        match = cls._DECLARED_SECTION.search(html)
        if match is None:
            return None
        return match.group(1).strip().rstrip(".")

    @classmethod
    def _parse_section_page(
        cls, html: str, code: str, section: str, url: str
    ) -> ParsedDocument:
        """Parse a section page into a :class:`ParsedDocument`.

        Args:
            html: The fetched section page HTML.
            code: The canonical code that was requested.
            section: The canonical section number that was requested.
            url: The source URL.

        Returns:
            A :class:`ParsedDocument` with ``raw_citation`` =
            ``f"Cal. {code} § {section}"``, ``heading`` = ``None``
            (California sections carry no catchline), ``text`` = the body
            paragraphs, and ``amendment_notes`` = the history line(s).

        Raises:
            RefNotFoundError: If the page has no section content block (the
                section does not resolve).
            RefMismatchError: If the page declares a different code or a
                different section number than requested.
            NormalizationError: If the content block exists but its
                structure is genuinely malformed (no declared section, or
                no body text).
        """
        block = cls._SECTION_NOHEAD.search(html)
        if block is None:
            raise RefNotFoundError(
                f"Could not find the California section {section!r} of code "
                f"{code!r}: the site returned a page with no section content "
                "(the section does not resolve)."
            )
        content = block.group(1)

        declared_code = cls._declared_code(content)
        if declared_code is not None and declared_code != code:
            raise RefMismatchError(
                f"Requested California code {code!r} does not match the code "
                f"found on the fetched page: {declared_code!r}."
            )

        # The body/history live in the section's own font block; the
        # breadcrumb <i> notes (division/chapter/article history) live
        # outside it and are not part of the section's amendment notes.
        font_block = cls._FONT_BLOCK.search(content)
        if font_block is None:
            raise NormalizationError(
                "The fetched California section page contained no section "
                "text block; the site's structure may have changed."
            )
        text_block = font_block.group(1)

        declared = cls._declared_section_number(text_block)
        if declared is None:
            raise NormalizationError(
                "The fetched California section page contained no section "
                "number heading; the site's structure may have changed."
            )
        if declared != section:
            raise RefMismatchError(
                f"Requested California section {section!r} does not match "
                f"the section found on the fetched page: {declared!r}."
            )

        paragraphs = [
            " ".join(strip_tags(p).split())
            for p in cls._BODY_PARAGRAPH.findall(text_block)
            if " ".join(strip_tags(p).split())
        ]
        text = "\n".join(paragraphs).strip()

        history_parts = [
            " ".join(strip_tags(i).split())
            for i in cls._HISTORY_I.findall(text_block)
            if " ".join(strip_tags(i).split())
        ]
        amendment_notes = " ".join(history_parts).strip() or None

        if not text:
            raise NormalizationError(
                "The fetched California section page declared its section "
                f"number ({declared!r}) but contained no body text; the "
                "site's structure may have changed."
            )

        return ParsedDocument(
            raw_citation=f"Cal. {code} § {section}",
            heading=None,
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
        California.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: the canonical section number must appear
        within ``parsed.raw_citation``.

        ``status`` is always ``UNKNOWN``: the California source signals
        repealed/removed sections by their absence (the site returns an
        empty response), not by a structural status field.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a California ref
                (``ref.state_code != "CA"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"CaliforniaAdapter.normalize cannot normalize a ref for "
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
        """Retrieve and normalize one California Code section, end to end:
        validate and canonicalize the code and section -> fetch the
        server-rendered section page with the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` -> verify the
        page declares the requested code and section -> parse into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be a California ref
                (``ref.state_code == "CA"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be reached.
            RefNotFoundError: If the code or section identifier is invalid,
                or the fetched page has no section content (the section
                does not resolve).
            RefMismatchError: If the fetched page declares a different code
                or a different section than requested.
            NormalizationError: If the content block is genuinely malformed.
        """
        code = self._valid_code(ref.chapter.title.identifier)
        section = self._canonical_section(ref.identifier)
        if section is None:
            raise RefNotFoundError(
                f"Invalid California section identifier {ref.identifier!r}: "
                "expected a numeric section number (e.g. '5000', '5025.3')."
            )

        url = self._section_url(code, section)
        html = self._fetch_html(url, what="California statute section")

        parsed = self._parse_section_page(html, code, section, url)

        # Normalize against the canonical section identifier (e.g. "5000"
        # rather than a leading-zero "05000"), so the returned section ref,
        # citation, and cross-checks are all consistent.
        if section != ref.identifier:
            ref = ref.model_copy(update={"identifier": section})
        return self.normalize(parsed, ref)