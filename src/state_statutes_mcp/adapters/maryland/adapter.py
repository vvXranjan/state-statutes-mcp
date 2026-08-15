"""MarylandAdapter: the Maryland-specific concrete state adapter.

Source: the official Maryland General Assembly publication of the
Annotated Code of Maryland at ``https://mgaleg.maryland.gov`` --
anonymous, server-rendered HTML with no authentication or API key (the
statute browser is a plain ASP.NET MVC site; no SPA framework, no
client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/maryland.md``,
which documents live requests to the official host on Aug 15, 2026):

* Base URL ``https://mgaleg.maryland.gov`` with the statute browser under
  ``/mgawebsite/Laws/``.
* The Annotated Code is organized into articles, each with a three-letter
  article code (e.g. ``gtr`` for Transportation, ``gag`` for Agriculture)
  and a display name (e.g. ``"Transportation"``). The article list page
  (``/mgawebsite/Laws/Statutes``) lists every article as a
  ``<select id="Articles">`` whose ``<option value="{code}">`` label is
  ``"{Name} - ({code})"`` (VERIFIED: 36 articles, all with codes beginning
  with ``g`` -- the ``c*``/``l*``/``acts``/``baltc``/``municc`` options are
  the Constitution, local codes, and charters, not Annotated Code articles).
* Chapters: a JSON API returns the article's full section list. The API
  endpoint ``/mgawebsite/api/Laws/GetSections?articleCode={code}&enactments=false``
  returns a JSON array of ``{"DisplayText": "1-101", "Value": "100"}``
  records, one per section, in citation order (VERIFIED for ``gtr``: 1744
  sections across 28 subtitles). This adapter maps the article's subtitle
  groupings onto the framework's ChapterRef: the subtitle number is the
  section id's leading segment (e.g. ``"1"`` in ``1-101``, ``"18.5"`` in
  ``18.5-101``), so ``list_chapters`` groups the section list by leading
  segment and ``list_sections`` filters it -- the same flattening pattern
  Arizona uses for its chapter-in-section-range structure.
* Sections: ``/mgawebsite/Laws/StatuteText?article={code}&section={sec}``
  returns a full HTML page whose ``<div id="StatuteText">`` holds the
  section document as an embedded ``<html>`` fragment: an article banner
  (``Article - Transportation``), Previous/Next navigation buttons, the
  section's own citation heading (``&sect;1&ndash;101.``), then the body
  (VERIFIED for 1-101, 2-103.1, and 5-4A-01). The ``enactments`` query
  parameter is optional for section text (omitted here; verified working).
* Section content: the section heading is the citation number (e.g.
  ``1-101``) with NO catchline -- Maryland section pages carry no
  standalone heading text, so ``heading`` is ``None``. The body is the
  tagged text after the heading; there is no history/amendment line on
  Maryland section pages, so ``amendment_notes`` stays ``None``.
* Citation: ``Md. Code, {ArticleName} § {section}`` (e.g. ``Md. Code,
  Transportation § 1-101``), adapter-constructed: the ``Md. Code``
  abbreviation is INFERENCE from standard Maryland citation usage, the
  article display name comes VERIFIED from the section page's own banner
  (``Article - Transportation``), and the section number is VERIFIED from
  the site's own heading text.
* Error boundary: a section that does not exist returns a 200 page whose
  ``StatuteText`` div reads ``<Label>File Not Found</Label>`` (VERIFIED),
  mapped here to ``RefNotFoundError``. An invalid ``GetSections`` article
  code returns ``{"message": "No HTTP resource was found ..."}`` (a 200
  JSON body), mapped here to ``RefNotFoundError`` in listing paths.

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef model**
(verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = the article code (e.g. ``"gtr"``), ``name`` =
  the article display name (e.g. ``"Transportation"``).
* ``ChapterRef.identifier`` = the subtitle number (the section id's leading
  segment, e.g. ``"1"``, ``"18.5"``).
* ``SectionRef.identifier`` = the full section citation (e.g. ``"1-101"``,
  ``"2-103.1"``, ``"5-4A-01"``).

The subtitle level is adapter-internal grouping of the article's flat
section list; it carries no URL of its own, so ``build_url(ChapterRef)``
returns the article's ``GetSections`` API URL -- the closest real resource,
mirroring how ``ArizonaAdapter`` returns the title detail page for its
chapter-level refs.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/maryland.md``): whether every article's ``GetSections``
response and every section page render identically (sampled ``gtr``, ``gag``
and sections 1-101/2-103.1/5-4A-01); whether the ``enactments`` parameter
changes section text for enacted-law views (omitted for current code). None
of these block the implementation below.
"""

from __future__ import annotations

import json
import re
import urllib.error
from datetime import datetime, timezone
from typing import Any, Sequence

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


class MarylandAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Maryland General Assembly
    publication of the Annotated Code of Maryland at mgaleg.maryland.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). See the module docstring
    for the verified site structure this adapter is built against.
    """

    BASE_URL = "https://mgaleg.maryland.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # An article option in the Articles select, e.g. '<option value="gtr">Transportation - (gtr)</option>'.
    _ARTICLE_OPTION = re.compile(
        r'<option value="(g[a-z]{2})">(.*?)</option>',
        re.IGNORECASE,
    )
    # The #Articles select block (the same options are repeated inside the
    # #StatutesAffected select further down the page, so the parse is scoped
    # to the article browser's select).
    _ARTICLES_SELECT = re.compile(
        r'<select[^>]*id="Articles"[^>]*>(.*?)</select>',
        re.IGNORECASE | re.DOTALL,
    )
    # The option label's trailing ' - ({code})' decoration.
    _ARTICLE_LABEL_SUFFIX = re.compile(r"\s*-\s*\([^)]*\)\s*$")

    # The StatuteText div holds an embedded <html> fragment (article banner,
    # nav buttons, then '&sect;1&ndash;101.' heading and body) that ends with
    # the fragment's own </html>.
    _STATUTE_TEXT_DIV = re.compile(
        r'<div id="StatuteText">(.*?)</html>', re.DOTALL
    )
    # A not-found section renders as '<Label>File Not Found</Label>' inside
    # the StatuteText div (the page itself is HTTP 200).
    _FILE_NOT_FOUND = re.compile(r"<Label>File Not Found</Label>", re.IGNORECASE)
    # The embedded fragment's trailing nav buttons, e.g. '<div class="row">...' -> strip them.
    _NAV_BUTTONS = re.compile(r'<div class="row">.*?</div>\s*</div>\s*<br\s*/?>', re.DOTALL)
    # The article banner inside the embedded fragment, e.g. '<div style="text-align: center;"><span style="font-weight: bold;">Article - Transportation</span></div>'.
    _ARTICLE_BANNER = re.compile(
        r'<div[^>]*>\s*<span[^>]*>\s*Article\s*-\s*(.*?)</span>\s*</div>',
        re.DOTALL | re.IGNORECASE,
    )
    # The section heading, e.g. '&sect;1&ndash;101.<br>' or '&sect;2&ndash;103.1.<br>'.
    # The period is followed by the <br> that ends the heading, so a dotted
    # section number (2-103.1) is consumed whole rather than cut at its own
    # internal period.
    _SECTION_HEADING = re.compile(
        r"&sect;\s*([^<]+?)\s*\.(?:\s*<br\b[^>]*>)", re.IGNORECASE
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Maryland."""
        return "MD"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Maryland."""
        return "Maryland"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Maryland statute URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/maryland.md):

        * Title: the article's ``GetSections`` API URL -- the article
          itself has no page; its full section list is the closest real
          resource and the one ``list_chapters``/``list_sections`` use.
        * Chapter: the same article ``GetSections`` API URL (the subtitle
          level has no page of its own).
        * Section: ``/mgawebsite/Laws/StatuteText?article={code}&section={sec}``
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
            return (
                f"{self.BASE_URL}/mgawebsite/Laws/StatuteText"
                f"?article={ref.chapter.title.identifier}&section={ref.identifier}"
            )
        elif isinstance(ref, ChapterRef):
            return self._sections_api_url(ref.title.identifier)
        elif isinstance(ref, TitleRef):
            return self._sections_api_url(ref.identifier)
        else:
            raise UnsupportedRefError(
                f"MarylandAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    @classmethod
    def _sections_api_url(cls, article_code: str) -> str:
        """Build the article's verified ``GetSections`` API URL."""
        return (
            f"{cls.BASE_URL}/mgawebsite/api/Laws/GetSections"
            f"?articleCode={article_code}&enactments=false"
        )

    # ------------------------------------------------------------
    # Shared fetch/JSON/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into
        ``AdapterUnavailableError`` there. Maryland returns HTTP 200 for
        both real pages and not-found section pages (the not-found signal
        is in the body), so no HTTP 404 mapping is needed here -- the
        body-level ``File Not Found`` signal is handled in the calling
        methods.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached.
        """
        return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)

    def _fetch_json(self, url: str, *, what: str) -> Any:
        """Fetch ``url`` and parse its body as JSON.

        A VERIFIED not-found article code returns HTTP 200 with a JSON body
        of ``{"message": "No HTTP resource was found ..."}`` (not a 404),
        so this method does not map HTTP errors; the calling discovery
        methods inspect the response shape.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched.

        Returns:
            The decoded JSON value.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached, or if
                the response body is not valid JSON.
        """
        try:
            text = fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Fetched {url!r} and it returned HTTP 404; the {what} "
                    "does not resolve on the Maryland General Assembly site."
                ) from exc
            raise
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but its response was not valid JSON: {exc}"
            ) from exc

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every article of the Annotated Code of Maryland from
        the statute browser page.

        The article list page (``/mgawebsite/Laws/Statutes``) renders a
        ``<select id="Articles">`` whose options are the Annotated Code
        articles -- each ``<option value="{code}">{Name} - ({code})</option>``
        with a code beginning with ``g`` (VERIFIED: 36 articles). Options
        for the Constitution, county/local codes, and charters (codes
        beginning with other letters) are excluded because they are not
        Annotated Code articles.

        Returns:
            A sequence of :class:`TocNode`, one per article, in document
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the article code (e.g. ``"gtr"``) and whose
            ``name`` is the article display name (e.g. ``"Transportation"``).

        Raises:
            AdapterUnavailableError: If the statute browser page cannot be
                fetched or no usable article options could be parsed from it.
        """
        url = f"{self.BASE_URL}/mgawebsite/Laws/Statutes"
        html = self._fetch_html(url, what="Maryland statute browser page")

        select_match = self._ARTICLES_SELECT.search(html)
        if select_match is None:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no #Articles select in it; the "
                "site's structure may have changed."
            )
        select_html = select_match.group(1)

        titles = []
        seen: set[str] = set()
        for code, raw_label in self._ARTICLE_OPTION.findall(select_html):
            if code in seen:
                continue
            seen.add(code)
            name = self._ARTICLE_LABEL_SUFFIX.sub("", raw_label).strip()
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=code,
                    name=name or code,
                    ref=TitleRef(state_code=self.state_code, identifier=code),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable article options in it; "
                "the site's structure may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the article's
        ``GetSections`` listing.

        Maryland articles carry no separate chapter pages: the subtitle
        level exists only as the leading segment of each section id (e.g.
        ``"1"`` in ``1-101``). This method fetches the article's flat
        section list and groups it by that leading segment, so each subtitle
        becomes one chapter -- the same flattening pattern ``ArizonaAdapter``
        applies to its chapter-in-section-range structure.

        Returns:
            A sequence of :class:`TocNode`, one per subtitle, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the subtitle number (e.g. ``"1"``, ``"18.5"``).

        Raises:
            RefNotFoundError: If the article code does not resolve on the
                ``GetSections`` API.
            AdapterUnavailableError: If the listing cannot be fetched, or
                if no usable chapter groupings could be derived from it.
        """
        url = self.build_url(title_ref)
        data = self._fetch_json(url, what="Maryland section listing")

        sections = self._sections_from_api(data, url=url, title_ref=title_ref)
        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no sections in it; either article "
                f"{title_ref.identifier!r} does not resolve or the API's "
                "response shape has changed."
            )

        chapters = []
        seen: set[str] = set()
        for identifier, _ in sections:
            chapter_id = identifier.split("-", 1)[0]
            if chapter_id in seen:
                continue
            seen.add(chapter_id)
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=chapter_id,
                    name=chapter_id,
                    ref=ChapterRef(title=title_ref, identifier=chapter_id),
                )
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the article's
        ``GetSections`` listing.

        The article's flat section list is filtered to the sections whose
        leading segment (subtitle) equals ``chapter_ref.identifier``.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full section citation (e.g. ``"1-101"``).

        Raises:
            RefNotFoundError: If the article code does not resolve on the
                ``GetSections`` API.
            AdapterUnavailableError: If the listing cannot be fetched, or
                if no sections for ``chapter_ref`` could be found in it.
        """
        url = self.build_url(chapter_ref)
        data = self._fetch_json(url, what="Maryland section listing")

        sections = self._sections_from_api(
            data, url=url, title_ref=chapter_ref.title
        )
        chapter_id = chapter_ref.identifier
        matched = [
            (identifier, identifier)
            for identifier, _ in sections
            if identifier.split("-", 1)[0] == chapter_id
        ]

        if not matched:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no sections for chapter "
                f"{chapter_id!r} under article {chapter_ref.title.identifier!r}; "
                "the API's response shape may have changed."
            )

        return tuple(
            sorted(
                (
                    TocNode(
                        level=HierarchyLevel.SECTION,
                        identifier=identifier,
                        name=identifier,
                        ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                    )
                    for identifier, _ in matched
                ),
                key=lambda node: self._sort_key(node.identifier),
            )
        )

    @classmethod
    def _sections_from_api(
        cls, data: Any, *, url: str, title_ref: TitleRef
    ) -> list[tuple[str, str]]:
        """Validate and unpack a ``GetSections`` API response.

        A VERIFIED invalid article code returns a JSON object with a
        ``message`` field rather than an array; that maps to
        ``RefNotFoundError``.

        Args:
            data: The parsed JSON response.
            url: The API URL (for error messages).
            title_ref: The article the listing is for.

        Returns:
            A list of ``(identifier, display_name)`` pairs in response
            order (the API returns no separate names, so the identifier is
            also the display name).

        Raises:
            RefNotFoundError: If the response is a ``message`` object
                (invalid article code).
            AdapterUnavailableError: If the response is neither an array
                nor a message object.
        """
        if isinstance(data, dict):
            message = data.get("message")
            if isinstance(message, str) and "No HTTP resource" in message:
                raise RefNotFoundError(
                    f"Fetched {url!r} but the API could not resolve article "
                    f"{title_ref.identifier!r}: {message}"
                )
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response was not a JSON array of "
                "sections; the API's response shape may have changed."
            )

        if not isinstance(data, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response was not a JSON array of "
                "sections; the API's response shape may have changed."
            )

        sections = []
        seen: set[str] = set()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("DisplayText")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen.add(identifier)
            sections.append((identifier, identifier))
        return sections

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for chapter and section
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any dotted/lettered suffix -- the same convention the other
        adapters use -- so ``1, 2, 18.5, 27`` and ``1-101, 1-102, 2-103.1``
        order sensibly regardless of the API's order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Maryland.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full section
        citation, e.g. ``"1-101"``) must appear verbatim within
        ``parsed.raw_citation`` (the ``Md. Code, Transportation § 1-101``
        citation). The stronger citation-number cross-check against the
        source response happens in :meth:`retrieve_section`, which parses
        the page's own heading number.

        ``status`` is always left at its default (``UNKNOWN``): Maryland
        section pages carry no structural repealed/amended/renumbered
        signal observed in this milestone, and the contract explicitly
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Maryland ref
                (``ref.state_code != "MD"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"MarylandAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Annotated Code of Maryland section,
        end to end: :meth:`build_url` -> fetch the section page ->
        cross-check the page's own citation number against ``ref`` -> parse
        the section page into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/maryland.md): the section
        text lives in ``<div id="StatuteText">`` as an embedded ``<html>``
        fragment holding an article banner, Previous/Next navigation
        buttons, then the section's own citation heading (``&sect;1&ndash;101.``)
        followed by the body. Maryland pages carry no catchline, so
        ``heading`` is ``None``, and no history line, so ``amendment_notes``
        is ``None``. The page's own citation number is cross-checked
        against ``ref.identifier`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed. A not-found
        section (``<Label>File Not Found</Label>`` in the div) raises
        :class:`RefNotFoundError`.

        Args:
            ref: The section to retrieve. Must be a Maryland ref
                (``ref.state_code == "MD"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched.
            RefNotFoundError: If the page's ``StatuteText`` div contains the
                verified ``File Not Found`` signal.
            RefMismatchError: If the page's citation number disagrees with
                ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                structure (the embedded fragment, heading) is missing, or
                the body is empty after cleaning. Also raised by
                :meth:`normalize` if ``ref`` is not a Maryland ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Maryland section page")

        div_match = self._STATUTE_TEXT_DIV.search(html)
        if div_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the page contained no StatuteText div; "
                "the site's structure may have changed."
            )
        fragment = div_match.group(1)

        if self._FILE_NOT_FOUND.search(fragment):
            raise RefNotFoundError(
                f"Fetched {url!r} but it reported 'File Not Found'; section "
                f"{ref.identifier!r} does not resolve on the Maryland General "
                "Assembly site."
            )

        heading_match = self._SECTION_HEADING.search(fragment)
        if heading_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no section "
                "heading; the site's structure may have changed."
            )

        citation_number = self._decode_section_number(heading_match.group(1))
        if citation_number != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation number in the fetched section page: "
                f"{citation_number!r}."
            )

        text = self._parse_section_text(fragment, heading_match.end())
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        # The article name for the citation comes from the page's own
        # banner (e.g. "Article - Transportation"), VERIFIED on every
        # section page; this keeps the citation correct even when the
        # caller built the ref from tool arguments and carried no article
        # display name on the TitleRef.
        banner_match = self._ARTICLE_BANNER.search(fragment)
        if banner_match is None:
            article_name = ref.chapter.title.name or ref.chapter.title.identifier
        else:
            article_name = self._clean_inner(banner_match.group(1)) or (
                ref.chapter.title.name or ref.chapter.title.identifier
            )
        raw_citation = f"Md. Code, {article_name} § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=None,
            text=text,
            amendment_notes=None,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    @classmethod
    def _decode_section_number(cls, raw: str) -> str:
        """Decode a section heading number's entities and normalize dashes.

        The site renders the en dash as ``&ndash;`` (e.g.
        ``1&ndash;101``), so after entity decoding the heading is ``1-101``
        when ``&ndash;`` maps to ``\u2013`` -- this replaces any en/em dash
        with an ASCII hyphen to match ``ref.identifier``.

        Args:
            raw: The raw heading-number text (e.g. ``"1&ndash;101"``).

        Returns:
            The normalized ASCII-hyphen section number (e.g. ``"1-101"``).
        """
        decoded = strip_tags(raw).strip()
        decoded = decoded.replace("\u2013", "-").replace("\u2014", "-")
        return decoded

    @classmethod
    def _parse_section_text(cls, fragment: str, heading_end: int) -> str:
        """Extract the section body from the embedded fragment.

        Args:
            fragment: The ``StatuteText`` div's inner HTML.
            heading_end: The offset just after the citation heading, where
                the body begins.

        Returns:
            The cleaned body text (blank-line-separated paragraphs), or an
            empty string if the body is empty after cleaning.
        """
        body_html = fragment[heading_end:]
        body_html = cls._NAV_BUTTONS.sub("", body_html)
        text = strip_tags(body_html, preserve_block_breaks=True).strip()
        return text
