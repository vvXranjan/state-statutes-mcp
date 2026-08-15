"""NorthDakotaAdapter: the North Dakota-specific concrete state adapter.

Source: the official North Dakota Legislature bulk JSON at
``https://ndlegis.gov/api/data/century_code.json``. Unlike every other
adapter so far, North Dakota exposes its entire Century Code as ONE
unpaginated JSON document (~70 MB): titles -> chapters -> sections. There
is no per-title, per-chapter, or per-section endpoint, so every discovery
and retrieval call reads from the single fetched document.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the
MCP ``get_section`` tool (see ``BaseStateAdapter``'s module docstring for
that requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/north_dakota.md``, which documents live requests to the
official host):

* The canonical host is ``ndlegis.gov`` (no ``www.``); the ``www`` host
  301-redirects to it.
* The bulk is ``{"last_updated", "titles": {title_num: {"title_num",
  "title_name", "chapters": {chapter_num: {"id", "chapter_num",
  "chapter_title", "source_url", "repealed", "sections": {section_num:
  {"id", "section_num", "title", "page", "text", "html"}}}}}}}``.
  69 titles in the live bulk.
* Chapter ``source_url`` is a per-chapter PDF; this adapter never fetches
  it. ``repealed`` chapters carry ZERO sections (778 such chapters live).
* Section ``id`` is the full ``{title}-{chapter}-{section}`` citation
  (e.g. ``4.1-02-16``); ``text`` is the plain body WITHOUT a citation
  prefix or history line (may contain PDF artifacts such as double
  spaces); ``html`` is the same body with markup; ``title`` is the
  heading. Some sections are "Reserved" with BOTH ``text`` and ``html``
  empty (e.g. ``30.1-04-08``).

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef
model** (verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = ``title_num`` (e.g. ``"1"``, ``"4.1"``).
* ``ChapterRef.identifier`` = ``chapter_num`` (e.g. ``"01"``, ``"02"``).
* ``SectionRef.identifier`` = the section ``id`` (e.g. ``"4.1-02-16"``) —
  already the full citation.

**Citation and body format** (verified): the citation is ``N.D.C.C. §
{title}-{chapter}-{section}`` (e.g. ``N.D.C.C. § 4.1-02-16``),
adapter-constructed from ``ref.identifier``. ``heading`` is the section's
``title`` field; ``text`` is the section's ``text`` field preserved
verbatim (no history line exists to extract, so ``amendment_notes`` is
always None).

**Error boundary**: because every level lives in one bulk document,
"not found" means the ref's key is absent from the fetched structure
(raises ``RefNotFoundError``). A repealed chapter (zero sections) is a
valid, present chapter, so ``list_sections`` returns an empty tuple
rather than raising. A Reserved section (empty ``text``/``html``) is
surfaced as ``NormalizationError``. Network failures surface as
``AdapterUnavailableError`` via the shared ``_fetch`` helper.

**Known limitation** (documented in ``docs/research/north_dakota.md``):
retrieving any level requires fetching the entire bulk (~70 MB) on each
call; this is inherent to the source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from state_statutes_mcp.adapters._fetch import fetch_url
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


class NorthDakotaAdapter(BaseStateAdapter):
    """Concrete state adapter for the North Dakota Century Code bulk JSON
    at ndlegis.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified bulk-JSON structure this adapter is built against.
    """

    BULK_URL = "https://ndlegis.gov/api/data/century_code.json"
    DEFAULT_TIMEOUT_SECONDS = 30

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for North Dakota."""
        return "ND"

    @property
    def state_name(self) -> str:
        """Human-facing display name for North Dakota."""
        return "North Dakota"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the URL needed to retrieve ``ref``.

        North Dakota exposes exactly ONE resource — the bulk
        ``century_code.json`` — and every title, chapter, and section
        lives inside it (see the module docstring). ``build_url``
        therefore returns the bulk URL for all three ref types; the
        chapter-level ``source_url`` (a PDF) is deliberately not used as a
        fetch target. This is a documented adapter-internal decision, not
        a framework change.

        Args:
            ref: The title, chapter, or section to address (any level is
                retrievable via the bulk document).

        Returns:
            The bulk JSON URL.

        Raises:
            UnsupportedRefError: If ``ref`` is not a
                :class:`TitleRef`, :class:`ChapterRef`, or
                :class:`SectionRef`.
        """
        if isinstance(ref, (TitleRef, ChapterRef, SectionRef)):
            return self.BULK_URL
        raise UnsupportedRefError(
            f"NorthDakotaAdapter.build_url does not support refs of type "
            f"{type(ref).__name__!r}."
        )

    # ------------------------------------------------------------
    # Shared fetch/JSON helper
    # ------------------------------------------------------------

    def _fetch_json(self, url: str, *, what: str) -> Any:
        """Fetch ``url`` and parse its body as JSON.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into
        ``AdapterUnavailableError`` there. This method only adds JSON
        parsing, wrapping a response that is not valid JSON into
        ``AdapterUnavailableError`` — the source responded, but not in
        the expected shape.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The decoded JSON value (dict).

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached, or if
                the response body is not valid JSON.
        """
        text = fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but its response was not valid JSON: {exc}"
            ) from exc

    def _bulk(self) -> dict:
        """Fetch and return the whole Century Code bulk document as a
        dict, raising ``AdapterUnavailableError`` if it is not the
        expected object shape.

        Returns:
            The decoded ``century_code.json`` object.

        Raises:
            AdapterUnavailableError: If the bulk cannot be fetched, is
                not valid JSON, or is not a dict with a ``titles`` map.
        """
        data = self._fetch_json(self.BULK_URL, what="North Dakota Century Code bulk")
        titles = data.get("titles") if isinstance(data, dict) else None
        if not isinstance(titles, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but the response contained no "
                "'titles' map; the API's response shape may have changed."
            )
        return data

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the North Dakota Century Code from
        the bulk ``titles`` map.

        Each entry is ``{"title_num", "title_name", "chapters"}``. The
        result is sorted numerically (e.g. ``1, 2, 4.1, 30.1``) rather
        than trusting the bulk's key order.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the ``title_num`` (e.g. ``"4.1"``) and whose
            ``name`` is the ``title_name``.

        Raises:
            AdapterUnavailableError: If the bulk cannot be fetched, if it
                has no ``titles`` map, or if no usable title rows could be
                parsed from it.
        """
        data = self._bulk()
        titles = data["titles"]

        result = []
        for title_num, entry in titles.items():
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("title_num")
            if not isinstance(identifier, str) or not identifier.strip():
                identifier = str(title_num).strip()
            if not identifier:
                continue
            name = entry.get("title_name")
            result.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name if isinstance(name, str) and name.strip() else identifier,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not result:
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but found no usable titles in it; "
                "the API's response shape may have changed."
            )

        return tuple(sorted(result, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the bulk
        ``chapters`` map of that title.

        Each entry is ``{"id", "chapter_num", "chapter_title",
        "source_url", "repealed", "sections"}``. Repealed chapters are
        present in the bulk (with zero sections) and are listed here —
        they are real, present chapters; a caller who drills into one
        gets an empty section list from :meth:`list_sections`. The result
        is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the ``chapter_num`` (e.g. ``"02"``) and
            whose ``name`` is the ``chapter_title``.

        Raises:
            AdapterUnavailableError: If the bulk cannot be fetched.
            RefNotFoundError: If ``title_ref`` does not resolve to a
                title in the bulk.
        """
        data = self._bulk()
        titles = data["titles"]

        title_entry = titles.get(title_ref.identifier)
        if not isinstance(title_entry, dict):
            raise RefNotFoundError(
                f"Title {title_ref.identifier!r} does not resolve in the North "
                "Dakota Century Code bulk."
            )

        chapters = title_entry.get("chapters")
        if not isinstance(chapters, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but title {title_ref.identifier!r} "
                "had no 'chapters' map; the API's response shape may have "
                "changed."
            )

        result = []
        for chapter_num, entry in chapters.items():
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("chapter_num")
            if not isinstance(identifier, str) or not identifier.strip():
                identifier = str(chapter_num).strip()
            if not identifier:
                continue
            name = entry.get("chapter_title")
            result.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name if isinstance(name, str) and name.strip() else identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not result:
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but found no usable chapters in "
                f"title {title_ref.identifier!r}; the API's response shape "
                "may have changed."
            )

        return tuple(sorted(result, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the bulk
        ``sections`` map of that chapter.

        Section identifiers are the full ``{title}-{chapter}-{section}``
        ``id`` (e.g. ``"4.1-02-16"``), preserved exactly. A **repealed**
        chapter carries an empty ``sections`` map (VERIFIED) and is a
        valid, present chapter, so this returns an empty tuple rather
        than raising. The result is sorted numerically.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the section ``id`` and whose ``name`` is
            the section ``title``.

        Raises:
            AdapterUnavailableError: If the bulk cannot be fetched, or if
                the chapter's ``sections`` value is not a map.
            RefNotFoundError: If ``chapter_ref`` or its parent title does
                not resolve in the bulk.
        """
        data = self._bulk()
        titles = data["titles"]

        title_entry = titles.get(chapter_ref.title.identifier)
        if not isinstance(title_entry, dict):
            raise RefNotFoundError(
                f"Title {chapter_ref.title.identifier!r} does not resolve in "
                "the North Dakota Century Code bulk."
            )

        chapters = title_entry.get("chapters")
        if not isinstance(chapters, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but title "
                f"{chapter_ref.title.identifier!r} had no 'chapters' map; the "
                "API's response shape may have changed."
            )

        chapter_entry = chapters.get(chapter_ref.identifier)
        if not isinstance(chapter_entry, dict):
            raise RefNotFoundError(
                f"Chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} does not resolve in the "
                "North Dakota Century Code bulk."
            )

        sections = chapter_entry.get("sections")
        if not isinstance(sections, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but chapter "
                f"{chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} had no 'sections' map; the "
                "API's response shape may have changed."
            )

        result = []
        for section_num, entry in sections.items():
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            identifier = identifier.strip()
            name = entry.get("title")
            result.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name if isinstance(name, str) and name.strip() else identifier,
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        # A repealed chapter has ZERO sections (VERIFIED); that is a valid,
        # present chapter, so an empty tuple is returned rather than raising.
        return tuple(sorted(result, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title, chapter, and
        section identifiers.

        Sorts on the leading integer first, falling back to the raw
        string for any dotted suffix — the same convention
        ``IllinoisAdapter`` and ``VirginiaAdapter`` use — so ``1, 2,
        4.1, 30.1`` and ``01, 02, 89`` order sensibly regardless of the
        bulk's key order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        North Dakota.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (North Dakota's full ``{title}-{chapter}-{section}``
        citation, e.g. ``"4.1-02-16"``) appears verbatim within
        ``raw_citation`` (the adapter-constructed ``N.D.C.C. § 4.1-02-16``).
        The stronger title/chapter/section cross-check against the source
        structure happens in :meth:`retrieve_section`, which navigates the
        JSON; ``normalize`` enforces state and citation agreement,
        consistent with the other adapters.

        ``status`` is always left at its default (``UNKNOWN``): nothing
        verified about the North Dakota source provides a structural
        repealed/amended/renumbered signal for a *section* (the ``repealed``
        flag exists only at the chapter level), and the contract forbids
        inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a North Dakota ref
                (``ref.state_code != "ND"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"NorthDakotaAdapter.normalize cannot normalize a ref for "
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
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one N.D.C.C. section, end to end:
        :meth:`build_url` -> fetch the bulk JSON -> navigate to ``ref``'s
        title/chapter/section -> cross-check the record against ``ref`` ->
        build a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Because every level lives in the single bulk document, navigation
        IS the lookup: a missing title, chapter, or section raises
        :class:`RefNotFoundError`. The record's ``id`` (full citation),
        the chapter's ``chapter_num``, and the title's ``title_num`` are
        cross-checked against the requested refs, and a mismatch raises
        :class:`RefMismatchError` — the framework-strong equivalent of
        ``IllinoisAdapter``'s three-part cross-check.

        ``heading`` is the section's ``title`` field; ``text`` is the
        section's ``text`` field preserved verbatim (no history line
        exists, so ``amendment_notes`` is None). A **Reserved** section
        (VERIFIED: ``text`` AND ``html`` both empty, e.g. ``30.1-04-08``)
        has no body to return and raises :class:`NormalizationError`.

        Args:
            ref: The section to retrieve. Must be a North Dakota ref
                (``ref.state_code == "ND"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the bulk cannot be fetched or its
                response is not valid JSON.
            RefNotFoundError: If ``ref``'s title, chapter, or section does
                not resolve in the bulk.
            RefMismatchError: If the located record's ``id``,
                ``chapter_num``, or ``title_num`` disagrees with ``ref``.
                Also raised by :meth:`normalize` on citation disagreement.
            NormalizationError: If the section was located but required
                fields (``text``) are missing or empty (e.g. a Reserved
                section). Also raised by :meth:`normalize` if ``ref`` is
                not a North Dakota ref.
        """
        data = self._bulk()
        titles = data["titles"]

        title_entry = titles.get(ref.chapter.title.identifier)
        if not isinstance(title_entry, dict):
            raise RefNotFoundError(
                f"Title {ref.chapter.title.identifier!r} does not resolve in "
                "the North Dakota Century Code bulk."
            )
        if title_entry.get("title_num") != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section: "
                f"{title_entry.get('title_num')!r}."
            )

        chapters = title_entry.get("chapters")
        if not isinstance(chapters, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but title "
                f"{ref.chapter.title.identifier!r} had no 'chapters' map; the "
                "API's response shape may have changed."
            )
        chapter_entry = chapters.get(ref.chapter.identifier)
        if not isinstance(chapter_entry, dict):
            raise RefNotFoundError(
                f"Chapter {ref.chapter.identifier!r} under title "
                f"{ref.chapter.title.identifier!r} does not resolve in the "
                "North Dakota Century Code bulk."
            )
        if chapter_entry.get("chapter_num") != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section: "
                f"{chapter_entry.get('chapter_num')!r}."
            )

        sections = chapter_entry.get("sections")
        if not isinstance(sections, dict):
            raise AdapterUnavailableError(
                f"Fetched {self.BULK_URL!r} but chapter "
                f"{ref.chapter.identifier!r} under title "
                f"{ref.chapter.title.identifier!r} had no 'sections' map; the "
                "API's response shape may have changed."
            )

        # The sections map is keyed by the section number -- the final
        # dash-separated segment of the full citation (e.g. the "01" in
        # "1-01-01"). Look the record up by that key, then cross-check the
        # record's own id against the requested full citation.
        section_num = ref.identifier.rsplit("-", 1)[-1]
        section_entry = sections.get(section_num)
        if not isinstance(section_entry, dict):
            raise RefNotFoundError(
                f"Section {ref.identifier!r} under chapter "
                f"{ref.chapter.identifier!r} does not resolve in the North "
                "Dakota Century Code bulk."
            )
        if section_entry.get("id") != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched response: "
                f"{section_entry.get('id')!r}."
            )

        raw_text = section_entry.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise NormalizationError(
                f"Fetched {self.BULK_URL!r} and located section "
                f"{ref.identifier!r}, but its 'text' was empty; the section "
                "may be Reserved, or the API's response shape may have changed."
            )

        heading = section_entry.get("title")
        if isinstance(heading, str):
            heading = heading.strip() or None

        raw_citation = f"N.D.C.C. § {ref.identifier}"

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=raw_text,
            amendment_notes=None,
            source_url=self.BULK_URL,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
