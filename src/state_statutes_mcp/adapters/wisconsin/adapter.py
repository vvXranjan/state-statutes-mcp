"""WisconsinAdapter: the Wisconsin-specific concrete state adapter.

Source: the official Wisconsin Legislature publication of the Wisconsin
Statutes at ``https://docs.legis.wisconsin.gov`` -- anonymous, server-
rendered HTML with no authentication or API key (no SPA framework, no
client-side statute rendering).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/wisconsin.md``,
which documents the official ``docs.legis.wisconsin.gov`` HTML captured
through a Wayback Machine snapshot of the official host, timestamp
20260722161219; the live host itself is unreachable from this environment):

* Base URL ``https://docs.legis.wisconsin.gov`` with statutory pages under
  ``/document/statutes/`` and canonical node pages under
  ``/statutes/statutes/``.
* The site has NO formal title level: the statutes index page
  (``/statutes/statutes``) is a flat list of 470 chapters. To fit the
  framework's three-level ref model, this adapter maps the entire code onto
  a single synthetic ``TitleRef`` whose identifier is ``"Wisconsin
  Statutes"``. This mapping is adapter-internal and documented; it is not a
  framework change.
* Chapters: the statutes index page lists each chapter as ``<a href=
  "/document/statutes/{N}">Chapter {N}</a> ... - {Name}``. The chapter
  identifier is the number in the href (e.g. ``"13"``); the name is the text
  after the ``- `` separator.
* Sections: a chapter page (``/statutes/statutes/{N}``) lists every section
  of the chapter in ``qstoc_entry`` divs as ``<a rel="statutes/{sec}" href=
  "/document/statutes/{sec}">{sec}</a>...{Name}``. The section identifier is
  the full ``{chapter}.{local}`` form (e.g. ``"13.92"``, ``"13.035"``); the
  name is the text after the ``qstab`` span.
* Section content: ``/document/statutes/{sec}`` (e.g. ``/document/statutes/
  13.92``) -- the live site 302-redirects to the canonical node page
  ``/statutes/statutes/{ch}/{article}/{sec}``. **The fetched page renders a
  RANGE of sections** (the requested section plus preceding siblings in the
  same subchapter); the adapter isolates the requested section's
  ``qsatxt_1sect level3`` block by its ``data-section`` attribute. Verified
  structure (for 13.92 and 13.90):
  * The section block carries ``data-section="{sec}"`` (e.g. ``13.92``) and
    contains a ``qstitle_sect`` span whose text is the heading (e.g.
    ``Legislative reference bureau.``).
  * The body is the block's text after removing the heading/num/reference
    chrome and any ``qsnote_history`` div; nested subsections
    (``qsatxt_2subsect``, ``qsatxt_3para``, ``qsatxt_4subdiv``,
    ``qsatxt_5subdivpara``) are included.
  * History: a ``qsnote_history`` div appears after the last subdivision of
    a section whose history has been rendered (e.g. for 13.90). The 13.92
    sample had NO such block (13.92 is the last section rendered on its
    page, so its history falls on the next scroll chunk). ``amendment_notes``
    is therefore optional (``None`` when absent).
* Citation: ``Wis. Stat. § {chapter}.{section}`` (e.g. ``Wis. Stat. § 13.92``),
  adapter-constructed (the ``Wis. Stat.`` abbreviation is INFERENCE from
  standard Wisconsin citation usage; the number is VERIFIED from the site's
  own ``data-section`` / ``nodeCite`` values). ``SectionRef.identifier`` is
  the full ``{chapter}.{local}`` form (e.g. ``"13.92"``).
* Error boundary: a nonexistent section/document returns HTTP 404 (verified
  through the Wayback snapshot), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/wisconsin.md``): whether every chapter page keeps the same
``qstoc_entry`` section-TOC markup (sampled Chapter 13), the exact set of
siblings rendered on a section page, and whether any repealed/reserved
section renders differently from the current-section form. None of these
block the implementation below.
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


class WisconsinAdapter(BaseStateAdapter):
    """Concrete state adapter for the Wisconsin Legislature statutes
    publication at docs.legis.wisconsin.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape already
    established by ``WashingtonAdapter``, ``OhioAdapter``, and
    ``RhodeIslandAdapter``. See the module docstring for the verified site
    structure this adapter is built against.
    """

    BASE_URL = "https://docs.legis.wisconsin.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # The single synthetic title covering the entire code (the state has no
    # formal title level).
    SYNTHETIC_TITLE = "Wisconsin Statutes"

    # A chapter row on the statutes index page, e.g. '<a href="/document/
    # statutes/1">Chapter 1</a> ... </span> - Sovereignty And Jurisdiction
    # Of The State'. The chapter identifier is the number in the href; the
    # name is the text after the '- ' separator (a row may omit the name,
    # e.g. Chapter 164; the tempered-dot guard keeps each match inside a
    # single <li> row so a nameless row does not swallow the next one's
    # name). The '- ' and name are therefore optional.
    _CHAPTER_ROW = re.compile(
        r'<a href="/document/statutes/(\d+)"[^>]*>Chapter\s+\d+</a>'
        r'(?:(?!</li>).)*?</span>\s*(?:-\s*(.*?))?\s*</p>\s*</li>',
        re.DOTALL,
    )

    # A section row on a chapter page, e.g. '<a rel="statutes/13.01" href=
    # "/document/statutes/13.01" ...>13.01</a><span class="qstab"> <span
    # class='tab' ...>&nbsp;</span> </span>Number of legislators.'. The
    # section identifier is the rel/href suffix; the name is the text after
    # the qstab span's own closing </span> (the qstab span itself nests a
    # tab span, hence the explicit trailing '</span>').
    _SECTION_ROW = re.compile(
        r'<a rel="statutes/([0-9.]+)" href="/document/statutes/[0-9.]+"[^>]*>[0-9.]+</a>'
        r'<span class="qstab">.*?</span>\s*</span>\s*(.*?)</span>',
        re.DOTALL,
    )

    # The top-level section block on a section page, keyed by its
    # data-section attribute (the page renders a range of sections).
    _SECT_BLOCK = re.compile(
        r'<div class="qsatxt_1sect  level3"[^>]*data-section="([^"]+)"[^>]*>'
    )

    # The section heading inside a section block.
    _TITLE_SECT = re.compile(r'<span class="qstitle_sect">(.*?)</span>', re.DOTALL)

    # The history block, present for sections whose history has been rendered.
    _HISTORY = re.compile(r'<div class="qsnote_history".*?</div>', re.DOTALL)
    # The '13.90 History' reference label span inside the history block.
    _HISTORY_REF = re.compile(r'<span class="reference">.*?</span>', re.DOTALL)
    # The literal 'History:' label span inside the history block.
    _HISTORY_LABEL = re.compile(
        r'<span class="qstr"[^>]*>\s*History:\s*</span>', re.DOTALL
    )

    # Navigation chrome on the section page; not content.
    _REFERENCE_ANCHOR = re.compile(r'<a class="reference".*?</a>', re.DOTALL)
    _NUM_SECT = re.compile(r'<span class="qsnum_sect">.*?</span>', re.DOTALL)

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Wisconsin."""
        return "WI"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Wisconsin."""
        return "Wisconsin"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Wisconsin Legislature URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/wisconsin.md):

        * Title (synthetic -- the whole code): ``https://docs.legis.
          wisconsin.gov/statutes/statutes`` -- the chapter listing page.
        * Chapter: ``https://docs.legis.wisconsin.gov/statutes/statutes/{N}``
          -- the chapter page (section listing).
        * Section: ``https://docs.legis.wisconsin.gov/document/statutes/{sec}``
          -- ``SectionRef.identifier`` is already the full dotted
          ``{chapter}.{section}`` citation, so it is used directly; the live
          site redirects this to the canonical node page.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/document/statutes/{ref.identifier}"
        elif isinstance(ref, ChapterRef):
            return f"{self.BASE_URL}/statutes/statutes/{ref.identifier}"
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/statutes/statutes"
        else:
            raise UnsupportedRefError(
                f"WisconsinAdapter.build_url does not support refs of type "
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
        invalid chapter/section) into :class:`RefNotFoundError` -- the
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
                does not resolve on the Wisconsin Legislature site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Wisconsin Legislature "
                    "site."
                ) from exc
            raise

    @classmethod
    def _clean_inner(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return strip_tags(html_fragment).strip()

    @classmethod
    def _numeric_sort_key(cls, identifier: str) -> tuple[int, str]:
        """Sort key for Wisconsin identifiers: the integer leading part
        first (so 13.02 sorts before 13.92), then the full identifier for a
        stable tie-break. Handles the dotted ``{chapter}.{local}`` section
        ids."""
        match = re.match(r"(\d+)", identifier)
        return (int(match.group(1)) if match else 0, identifier)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate the single synthetic title of Wisconsin Statutes.

        Wisconsin has no formal title level (chapters are listed flatly on
        the statutes index page), so this adapter exposes the whole code as
        one synthetic :class:`TitleRef`. No network fetch is required: the
        synthetic title is a constant.

        Returns:
            A sequence with a single :class:`TocNode` whose ``ref`` is a
            :class:`TitleRef` with identifier ``"Wisconsin Statutes"``.

        Raises:
            This method never raises (the synthetic title is a constant).
        """
        return (
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=self.SYNTHETIC_TITLE,
                name=self.SYNTHETIC_TITLE,
                ref=TitleRef(
                    state_code=self.state_code, identifier=self.SYNTHETIC_TITLE
                ),
            ),
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter of Wisconsin Statutes from the statutes
        index page.

        The index page (``/statutes/statutes``) lists all 470 chapters as
        flat ``Chapter {N} - {Name}`` rows. The identifier is the number in
        the ``/document/statutes/{N}`` href; the name is the text after the
        ``- `` separator.

        Args:
            title_ref: The parent (synthetic) title to enumerate chapters
                under. Its identifier must equal ``SYNTHETIC_TITLE``.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"13"``) and whose
            ``name`` is the chapter name (e.g. ``"Legislative Branch"``).

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched, or
                if no usable chapter rows could be parsed from it.
        """
        if title_ref.identifier != self.SYNTHETIC_TITLE:
            raise AdapterUnavailableError(
                f"Wisconsin has no title {title_ref.identifier!r}; the only "
                f"title is the synthetic {self.SYNTHETIC_TITLE!r}."
            )

        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Wisconsin statutes index page")

        chapters = []
        seen: dict[str, None] = {}
        for identifier, name in self._CHAPTER_ROW.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(name).split())
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
                f"Fetched {url!r} but found no usable chapter rows in it; the "
                "site's structure may have changed."
            )

        return tuple(
            sorted(chapters, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        page's section TOC.

        The chapter page (``/statutes/statutes/{N}``) lists every section of
        the chapter in ``qstoc_entry`` divs. The identifier is the full
        ``{chapter}.{local}`` number (e.g. ``"13.92"``, ``"13.035"``); the
        name is the text after the ``qstab`` span.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full dotted section number (e.g.
            ``"13.92"``) and whose ``name`` is the section's name as
            presented in the listing.

        Raises:
            RefNotFoundError: If ``chapter_ref`` returns HTTP 404 (the
                chapter does not resolve).
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section rows could be
                parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Wisconsin section listing")

        sections = []
        seen: dict[str, None] = {}
        for identifier, name in self._SECTION_ROW.findall(html):
            if identifier in seen:
                continue
            seen[identifier] = None
            name = " ".join(self._clean_inner(name).split())
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

        return tuple(
            sorted(sections, key=lambda node: self._numeric_sort_key(node.identifier))
        )

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Wisconsin.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (the section number, e.g. ``"13.92"``) appears
        verbatim within ``raw_citation`` (the ``Wis. Stat. § 13.92``
        citation). The stronger cross-check against the source response
        happens in :meth:`retrieve_section`, which has the requested
        section's block in hand.

        ``status`` is always left at its default (``UNKNOWN``): Wisconsin
        section pages carry no structural repealed/amended/renumbered signal
        for current sections, and the contract forbids inferring status from
        prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Wisconsin ref
                (``ref.state_code != "WI"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"WisconsinAdapter.normalize cannot normalize a ref for state "
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
    # retrieve_section
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Wisconsin statute section, end to
        end: :meth:`build_url` -> fetch the section page -> isolate the
        requested section's block from the range of sections the page
        renders -> parse it into a :class:`ParsedDocument` -> :meth:`normalize`
        -> :class:`StatuteSection`.

        VERIFIED page structure (docs/research/wisconsin.md): the fetched
        section page renders a RANGE of sections (the requested section plus
        preceding siblings in the same subchapter), each as a
        ``qsatxt_1sect level3`` block carrying a ``data-section`` attribute.
        The adapter isolates the block whose ``data-section`` equals
        ``ref.identifier``. If no block matches, the section was not
        rendered on the page (or the structure changed) and a
        :class:`NormalizationError` is raised. The heading is the block's
        ``qstitle_sect`` text; the body is the block's text after removing
        the heading/num/reference chrome and any ``qsnote_history`` div;
        ``amendment_notes`` is the ``qsnote_history`` block text when
        present (the 13.92 sample had none, so it is optional).

        Args:
            ref: The section to retrieve. Must be a Wisconsin ref
                (``ref.state_code == "WI"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                verified not-found signal).
            NormalizationError: If the section was located but required
                structure (heading, body) is missing, or the body is empty
                after cleaning, or the requested section's block was not
                rendered on the page. Also raised by :meth:`normalize` if
                ``ref`` is not a Wisconsin ref.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Wisconsin section page")

        blocks = list(self._SECT_BLOCK.finditer(html))
        match = None
        for i, blk in enumerate(blocks):
            if blk.group(1) == ref.identifier:
                start = blk.end()
                end = blocks[i + 1].start() if i + 1 < len(blocks) else len(html)
                match = (start, end)
                break

        if match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the page did not render section "
                f"{ref.identifier!r} in its section range; the site's "
                "structure may have changed."
            )
        start, end = match
        segment = html[start:end]

        title = self._TITLE_SECT.search(segment)
        if title is None:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its section block contained no heading element; the site's "
                "structure may have changed."
            )
        heading = self._clean_inner(title.group(1)) or None

        body = self._REFERENCE_ANCHOR.sub("", segment)
        body = self._NUM_SECT.sub("", body)
        body = self._TITLE_SECT.sub("", body)
        body = self._HISTORY.sub("", body)
        text = strip_tags(body, preserve_block_breaks=True).strip()
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the section is "
                "likely an empty section or the site's structure has changed."
            )

        amendment_notes = None
        history = self._HISTORY.search(segment)
        if history is not None:
            raw = self._HISTORY_REF.sub("", history.group(0))
            raw = self._HISTORY_LABEL.sub("", raw)
            cleaned = self._clean_inner(raw)
            if cleaned:
                amendment_notes = cleaned

        raw_citation = f"Wis. Stat. § {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
