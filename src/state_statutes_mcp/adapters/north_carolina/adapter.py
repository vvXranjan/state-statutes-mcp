"""NorthCarolinaAdapter: the North Carolina-specific concrete state adapter.

Source: the official General Statutes of North Carolina (G.S.) at
``https://www.ncleg.gov`` -- anonymous, server-rendered HTML with no
authentication or API key.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/north_carolina.md``; verified against Wayback Machine
captures of the official host):

* Hierarchy Chapter -> Section. Chapters are the top level (e.g. ``15``,
  ``15A``); there is no title level in the modern G.S.
* Chapter discovery page:
  ``https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter{ch}`` (e.g.
  ``Chapter15``). Each section is a ``div.row`` block holding the section's
  HTML document link, a PDF link, the citation (``G.S. 15-1``), and the
  catchline (``&#xA7; 15-1.  Statute of limitations for misdemeanors.``).
* Each section has ONE static HTML document (the Family A model) at
  ``/EnactedLegislation/Statutes/HTML/BySection/Chapter_{ch}/GS_{file}.html``
  where ``{file}`` is the citation with spaces replaced by underscores:
  ``15-1`` -> ``GS_15-1.html``, ``15-10.1`` -> ``GS_15-10.1.html``, and a
  range ``15-2 through 15-3`` -> ``GS_15-2_through_15-3.html``.
* Section identifiers include decimals (``15-10.1``, ``15A-101.1``) and
  repealed/reserved ranges (``15-2 through 15-3``). A range has ONE
  ``GS_{a}_through_{b}.html`` document; there is no ``GS_15-2.html``.
* The section document is Word-generated XHTML. The catchline is the first
  paragraph whose cleaned text starts with the section symbol (``§`` /
  ``§§``); the body is every paragraph after it. The CSS class hashes on
  the tags are per-document and NOT stable, so parsing keys on structure,
  not class names.
* History is an inline parenthetical at the end of the section's last
  body paragraph (nested parentheses allowed), lifted out as
  ``amendment_notes``. Some sections carry none.
* Repealed and reserved sections are catchline-only documents: the whole
  content is the heading, e.g. ``§ 15-9. Repealed by Session Laws 1973,
  c. 1286, s. 26.``. These are returned with ``text == ""`` and the
  repeal/reservation note as ``heading``; ``status`` remains ``UNKNOWN``.
  This is a deliberate, documented deviation from the blanket "empty text
  + no amendment -> NormalizationError" rule (see retrieve_section).
* Citation: ``G.S. {ch}-{sec}`` (e.g. ``G.S. 15-1``, ``G.S. 15-10.1``,
  ``G.S. 15-2 through 15-3``); ``raw_citation`` is that form and
  ``SectionRef.identifier`` is ``{ch}-{sec}``.
* Section documents are served in two encodings (UTF-8 with ``&sect;``
  entities, and Windows-1252 with literal bytes); the adapter detects the
  declared charset and decodes accordingly, so the shared UTF-8-only
  ``fetch_url`` helper is not used here by design.

**Title/chapter discovery BLOCKED BY DESIGN (UNVERIFIED):** the modern G.S.
has no title hierarchy, so ``list_titles`` raises ``AdapterUnavailableError``
directly. ``list_chapters`` also raises it: the framework contract anchors a
chapter under a ``TitleRef``, and North Carolina has no titles to anchor
under. Only ``list_sections`` and section retrieval are supported.

**Error boundary:** HTTP 404 maps to ``RefNotFoundError`` (project
convention; the live 404 behavior is UNVERIFIED since the host rejects
automated clients with HTTP 403); other network failures map to
``AdapterUnavailableError``. A fetched document whose catchline does not
begin with the requested identifier raises ``RefMismatchError``; a document
with no catchline (or no heading AND no body) raises ``NormalizationError``.
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
from state_statutes_mcp.models.statute_section import StatuteSection


class NorthCarolinaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official General Statutes of North
    Carolina.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). Title/chapter discovery
    is deliberately unsupported (BLOCKED BY DESIGN; see module docstring).
    """

    BASE_URL = "https://www.ncleg.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # One section row on the chapter discovery page. Anchored to the real
    # structure (see docs/research/north_carolina.md): the row div, the
    # section's HTML document link (the file name is the citation with
    # spaces replaced by underscores), then the "G.S. {id}" citation link,
    # then the catchline link ("§ {id}.  {caption}." / "§§ {range}.
    # {caption}."). The article-heading rows carry no "G.S." citation link
    # and so never match.
    _ROW = re.compile(
        r'<div class="row" style="padding-top:5px; padding-bottom:2px; ">'
        r'\s*<div class="col-3[^"]*">\s*'
        r'<a href="[^"]*/EnactedLegislation/Statutes/HTML/BySection/Chapter_'
        r'(?:[^/"]+)/(GS_[^"/]+\.html)"[^>]*>.*?'
        r"G\.S\. ([^<]+)</a>\s*</div>\s*"
        r'<div class="col-12 col-md-9 col-lg-10">\s*'
        r'<a href="[^"]+">([^<]+)</a>',
        re.DOTALL,
    )

    # A paragraph element in a section document. Section documents are
    # Word-generated XHTML whose chapter headings are <h3> and whose
    # catchline/body paragraphs are <p>; the per-document CSS class hashes
    # are not stable, so the match is structural only.
    _PARAGRAPH = re.compile(r"<(?:p|h3|h4)[^>]*>(.*?)</(?:p|h3|h4)>", re.DOTALL)

    # The catchline starts with one or two section symbols, e.g.
    # "§ 15-1. ..." or "§§ 15-2 through 15-3. ...".
    _CATCHLINE_PREFIX = re.compile(r"^§+\s*")

    # UNSUPPORTED discovery message (no title hierarchy in the modern G.S.).
    _DISCOVERY_UNAVAILABLE = (
        "North Carolina title/chapter discovery is not supported: the "
        "General Statutes of North Carolina have no title hierarchy -- "
        "chapters are the top-level grouping -- so there is no title to "
        "enumerate, and list_chapters anchors a chapter under a title that "
        "does not exist. List sections directly for a known chapter "
        "(e.g. '15', '15A') or retrieve a section directly (e.g. '15-1')."
    )

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for North Carolina."""
        return "NC"

    @property
    def state_name(self) -> str:
        """Human-facing display name for North Carolina."""
        return "North Carolina"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official North Carolina General Statutes URL for
        ``ref``.

        VERIFIED endpoint shapes (see docs/research/north_carolina.md):

        * Chapter: ``https://www.ncleg.gov/Laws/GeneralStatuteSections/
          Chapter{ch}`` (e.g. ``Chapter15``, ``Chapter15A``) -- the
          chapter's section-listing discovery page.
        * Section: ``https://www.ncleg.gov/EnactedLegislation/Statutes/
          HTML/BySection/Chapter_{ch}/GS_{file}.html`` where ``{file}`` is
          the section's citation with spaces replaced by underscores
          (e.g. ``GS_15-1.html``, ``GS_15-10.1.html``,
          ``GS_15-2_through_15-3.html``) -- the section's own static
          document (Family A).
        * Title: no page exists (the modern G.S. has no title hierarchy);
          raising :class:`UnsupportedRefError`.

        Args:
            ref: The chapter or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is a :class:`TitleRef` (there
                is no North Carolina title page), or not a chapter/section
                ref.
        """
        if isinstance(ref, SectionRef):
            file_stem = ref.identifier.replace(" ", "_")
            return (
                f"{self.BASE_URL}/EnactedLegislation/Statutes/HTML/BySection/"
                f"Chapter_{ref.chapter.identifier}/GS_{file_stem}.html"
            )
        if isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/Laws/GeneralStatuteSections/Chapter{ref.identifier}"
        if isinstance(ref, TitleRef):
            raise UnsupportedRefError(
                "NorthCarolinaAdapter.build_url cannot address a title: the "
                "General Statutes of North Carolina have no title hierarchy."
            )
        raise UnsupportedRefError(
            f"NorthCarolinaAdapter.build_url does not support refs of type "
            f"{type(ref).__name__!r}."
        )

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        North Carolina section documents are served in two encodings
        (UTF-8 with ``&sect;`` entities and Windows-1252 with literal
        bytes), so this method does its own ``urllib.request.urlopen`` call
        and decodes the raw bytes according to the document's declared
        charset (defaulting to UTF-8) rather than delegating to the shared
        UTF-8-only :func:`~state_statutes_mcp.adapters._fetch.fetch_url`
        helper.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text decoded per its declared charset.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the North Carolina site).
        """
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "state-statutes-mcp/0.1"},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=self.DEFAULT_TIMEOUT_SECONDS
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the North Carolina General "
                    "Statutes site."
                ) from exc
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the {what} at {url!r}: {exc}"
            ) from exc
        return raw.decode(self._detect_charset(raw[:2048]), errors="replace")

    @classmethod
    def _detect_charset(cls, head: bytes) -> str:
        """Return the charset declared in ``head``'s ``<meta ... charset=...>``,
        defaulting to ``"utf-8"`` when none is declared."""
        match = re.search(rb"""charset\s*=\s*["']?([\w-]+)""", head, re.IGNORECASE)
        if match is None:
            return "utf-8"
        charset = match.group(1).decode("ascii", errors="replace").lower()
        return charset or "utf-8"

    @classmethod
    def _clean(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment)

    @classmethod
    def _caption_from_catchline(cls, catchline: str, identifier: str) -> str | None:
        """Strip ``§ {identifier}. `` (or ``§§ {range}. ``) off ``catchline``
        and return the caption, or ``None`` if the catchline does not begin
        with the identifier."""
        stripped = cls._CATCHLINE_PREFIX.sub("", catchline, count=1)
        if not stripped.startswith(identifier):
            return None
        remainder = stripped[len(identifier):]
        if not remainder.lstrip().startswith("."):
            return None
        caption = remainder.lstrip()[1:].strip()
        return caption or None

    @classmethod
    def _strip_trailing_parenthetical(cls, text: str) -> tuple[str, str | None]:
        """Lift a trailing balanced parenthetical off ``text`` (handling
        nested parentheses) and return ``(body, parenthetical)``; if the
        text does not end in a balanced parenthetical, return ``(text, None)``."""
        if not text.endswith(")"):
            return text, None
        balance = 0
        start = None
        for index in range(len(text) - 1, -1, -1):
            if text[index] == ")":
                balance += 1
            elif text[index] == "(":
                balance -= 1
                if balance == 0:
                    start = index
                    break
        if start is None:
            return text, None
        return text[:start].rstrip(), text[start:].strip()

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Not supported for North Carolina (BLOCKED BY DESIGN).

        The modern General Statutes have no title hierarchy: chapters are
        the top-level grouping, so there is no title page to enumerate.
        This method raises ``AdapterUnavailableError`` directly instead of
        attempting a fetch.

        Raises:
            AdapterUnavailableError: Always, with the discovery explanation.
        """
        raise AdapterUnavailableError(self._DISCOVERY_UNAVAILABLE)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Not supported for North Carolina (BLOCKED BY DESIGN).

        The ``list_chapters`` contract anchors a chapter under a
        ``TitleRef``, and North Carolina has no titles to anchor under
        (chapters are the top level). Raises ``AdapterUnavailableError``
        directly.

        Args:
            title_ref: Ignored; there are no enumerable titles.

        Raises:
            AdapterUnavailableError: Always, with the discovery explanation.
        """
        raise AdapterUnavailableError(self._DISCOVERY_UNAVAILABLE)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter's
        discovery page.

        The chapter's section-listing page
        (``/Laws/GeneralStatuteSections/Chapter{ch}``, i.e. the URL
        :meth:`build_url` produces for a :class:`ChapterRef`) lists every
        section in a ``div.row`` per row, each holding the section's HTML
        document link, its citation (``G.S. 15-1``), and its catchline
        (``§ 15-1.  Statute of limitations for misdemeanors.``). Each row's
        identifier is the citation text (e.g. ``15-1``, ``15-10.1``, and
        for a repealed/reserved range ``15-2 through 15-3``); the name is
        the catchline's caption (e.g. ``Statute of limitations for
        misdemeanors.`` or ``Repealed by Session Laws 1973, c. 1286, s.
        26.``).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in the order
            they appear on the page. Each node's ``ref`` is a
            :class:`SectionRef` whose ``identifier`` is the full
            ``{ch}-{sec}`` citation (e.g. ``"15-1"``).

        Raises:
            RefNotFoundError: If the chapter's page returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter's page cannot be
                fetched for any other reason, or if no usable section rows
                could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="North Carolina section listing")

        sections = []
        seen: dict[str, None] = {}
        for _file, identifier, catchline in self._ROW.findall(html):
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen[identifier] = None
            name = self._caption_from_catchline(self._clean(catchline), identifier)
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
        North Carolina.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (e.g. ``"15-1"``) must
        appear verbatim within ``parsed.raw_citation`` (the ``G.S. 15-1``
        citation). The stronger citation cross-check against the source
        response happens in :meth:`retrieve_section`, which verifies the
        section document's own catchline begins with ``ref.identifier``.

        ``status`` is always left at its default (``UNKNOWN``): the North
        Carolina section documents carry no structural repealed/amended/
        renumbered signal beyond the prose of the catchline, and the
        contract explicitly forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a North Carolina ref
                (``ref.state_code != "NC"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NorthCarolinaAdapter.normalize cannot normalize a ref for "
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
    # retrieve_section
    # ------------------------------------------------------------

    def _parse_section(
        self,
        html: str,
        identifier: str,
    ) -> tuple[str | None, str, str | None]:
        """Parse one section document and return
        ``(heading, text, amendment_notes)``.

        The catchline is the first paragraph whose cleaned text starts with
        the section symbol; its citation (the text after ``§`` up to the
        following period) is verified to begin with ``identifier`` before
        anything is extracted. The body is every paragraph after the
        catchline; a trailing balanced parenthetical of the body is lifted
        out as ``amendment_notes``. A catchline-only document (a repealed
        or reserved section) yields an empty body and the repeal/
        reservation note as its heading.

        Raises:
            NormalizationError: If no catchline paragraph could be found.
            RefMismatchError: If the catchline does not begin with
                ``identifier``.
        """
        paragraphs = self._PARAGRAPH.findall(html)
        catchline_index = next(
            (
                i
                for i, inner in enumerate(paragraphs)
                if self._clean(inner).startswith("§")
            ),
            None,
        )
        if catchline_index is None:
            raise NormalizationError(
                f"The fetched section document contains no catchline "
                f"paragraph for section {identifier!r}; either the section "
                "does not resolve to a real section document or the site's "
                "structure has changed."
            )

        catchline = self._clean(paragraphs[catchline_index])
        caption = self._caption_from_catchline(catchline, identifier)
        if caption is None:
            raise RefMismatchError(
                f"The fetched section document's catchline {catchline!r} "
                f"does not begin with the requested citation for section "
                f"{identifier!r}; the document is not the section that was "
                "requested."
            )

        body = [
            self._clean(inner) for inner in paragraphs[catchline_index + 1 :]
        ]
        text = "\n\n".join(paragraph for paragraph in body if paragraph)

        text, amendment = self._strip_trailing_parenthetical(text)
        return caption, text, amendment

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one North Carolina General Statutes
        section, end to end: :meth:`build_url` -> fetch the section's own
        document -> parse it into a :class:`ParsedDocument` ->
        :meth:`normalize` -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/north_carolina.md): each
        section has one static document
        (``GS_{citation-with-spaces-as-underscores}.html``). The catchline
        is the first paragraph starting with the section symbol and must
        begin with ``ref.identifier``; the body is every paragraph after
        it; the history is the trailing balanced parenthetical of the body,
        preserved verbatim (whitespace collapsed) as ``amendment_notes``.

        A repealed or reserved section is a catchline-only document (e.g.
        ``§ 15-9. Repealed by Session Laws 1973, c. 1286, s. 26.``). Such a
        section is returned with ``text == ""`` and the repeal/reservation
        note as its ``heading`` -- a deliberate, documented deviation from
        the blanket "empty text + no amendment -> NormalizationError" rule:
        the heading is a structural element of the catchline, so a
        catchline-only section is genuinely retrievable. ``NormalizationError``
        is raised only when a fetched document yields no heading AND no
        body text.

        Args:
            ref: The section to retrieve. Must be a North Carolina ref
                (``ref.state_code == "NC"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section's document cannot be
                fetched for any reason other than HTTP 404.
            RefNotFoundError: If the section's document returns HTTP 404
                (the section does not resolve on the North Carolina site --
                e.g. a range's single-file form such as ``15-2``, whose
                content lives only in ``GS_15-2_through_15-3.html``).
            NormalizationError: If the section was fetched but its document
                has no catchline paragraph, or yields neither a heading nor
                body text. Also raised by :meth:`normalize` if ``ref`` is
                not a North Carolina ref.
            RefMismatchError: If the fetched document's catchline does not
                begin with ``ref.identifier``.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="North Carolina section page")

        heading, text, amendment = self._parse_section(html, ref.identifier)
        if heading is None and not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its document yielded neither a heading nor body text after "
                "cleaning; the section is likely empty or the site's "
                "structure has changed."
            )

        parsed = ParsedDocument(
            raw_citation=f"G.S. {ref.identifier}",
            heading=heading,
            text=text,
            amendment_notes=amendment,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)