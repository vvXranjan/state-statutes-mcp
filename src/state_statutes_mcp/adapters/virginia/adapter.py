"""VirginiaAdapter: the Virginia-specific concrete state adapter.

Source: the official Code of Virginia JSON API at
``https://law.lis.virginia.gov/api/`` (operations documented at
``https://law.lis.virginia.gov/jsonapi/`` and the developers page at
``https://law.lis.virginia.gov/developers/``). This is the framework's
first JSON-consuming adapter: unlike Washington, Texas, and Illinois —
which scrape HTML — Virginia's source is a documented, public,
pagination-free JSON API that requires no authentication.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the
MCP ``get_section`` tool (see ``BaseStateAdapter``'s module docstring for
that requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/virginia.md``, which documents live requests to the
official host):

* Base URL ``https://law.lis.virginia.gov/api/``; a **trailing slash is
  required** on every endpoint.
* Titles: ``CoVTitlesGetListOfJson`` -> a JSON array of
  ``{"TitleNumber", "TitleName", "ChapterList":null}``. The response can
  contain **duplicate ``TitleNumber`` rows** (verified: ``8.2``,
  ``8.2A``, ``8.4A``, ``54.1`` each appear twice with cosmetically
  different names), so this adapter deduplicates on ``TitleNumber``,
  keeping the first valid occurrence.
* Chapters: ``CoVChaptersGetListOfJson/{title}`` ->
  ``{"TitleNumber", "TitleName", "ChapterList":[{"ChapterNum","ChapterName"}]}``.
  The API returns chapters in **lexicographic order**, so this adapter
  re-sorts numerically.
* Sections: ``CoVSectionsGetListOfJson/{title}/{chapter}`` -> a nested
  object ``{"ArticleList":[{"SubPartList":[{"SectionList":[{"SectionRange","SectionNumber","SectionTitle"}]}]}]}``.
  The ``Article``/``SubPart`` levels are presentation grouping only —
  they carry no addressable number and are flattened away here; sections
  are addressed by their flat ``SectionNumber`` (e.g. ``"1-1"``,
  ``"18.2-51"``, ``"18.2-76.2"``), which can contain decimal forms.
* Section detail: ``CoVSectionsGetSectionDetailsJson/{section}`` -> one
  section inside ``{"TitleNumber", ..., "ChapterList":[{...}]}``. The
  section is keyed by its flat ``SectionNumber`` alone (title and chapter
  are not needed to fetch it, and **chapter is not part of the
  citation**). A **nonexistent section returns HTTP 200 with an empty
  ``ChapterList``** — never HTTP 404 — so this adapter treats an empty
  ``ChapterList`` as not-found and raises ``RefNotFoundError``.

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef
model** (verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = ``TitleNumber`` (e.g. ``"1"``, ``"18.2"``).
* ``ChapterRef.identifier`` = ``ChapterNum`` (e.g. ``"1"``, ``"4"``).
* ``SectionRef.identifier`` = ``SectionNumber`` (e.g. ``"1-1"``) —
  already the full citation, used directly by the section-detail
  endpoint (mirrors how ``WashingtonAdapter`` treats
  ``SectionRef.identifier`` as the full citation).

**Citation and body format** (verified): the citation is
``§ {title}-{section}`` (e.g. ``§ 1-1``, ``§ 18.2-51``), matching the
API's ``SectionRange`` verbatim. ``Body`` is HTML with one ``<p>`` per
paragraph; the legislative history is **trailing prose** (e.g.
``Code 1919, § 1; R. P. 1948, § 1-1.``), so history extraction splits
the *last* history-looking paragraph and everything after it out of the
body into ``amendment_notes``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/virginia.md``): ``SectionText`` was null in every
verified sample (``Body`` is authoritative); whether ``?version=`` is
honored is unknown (this adapter assumes the current Code); and whether
*every* section's final paragraph is the history line is unconfirmed
(only two representative sections were verified) — hence the
conservative "last history-looking paragraph" split below.
"""

from __future__ import annotations

import json
import re
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


class VirginiaAdapter(BaseStateAdapter):
    """Concrete state adapter for the Code of Virginia JSON API at
    law.lis.virginia.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by ``WashingtonAdapter``, ``TexasAdapter``, and
    ``IllinoisAdapter``. See the module docstring for the verified API
    structure this adapter is built against.
    """

    BASE_URL = "https://law.lis.virginia.gov/api"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Matches the start of a verified Virginia legislative-history
    # paragraph, e.g. "Code 1919, § 1; R. P. 1948, § 1-1." or
    # "Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15." — see the
    # module docstring and docs/research/virginia.md. Anchored to the
    # paragraph start so an in-text mention is never mistaken for a
    # history boundary.
    _HISTORY_START = re.compile(r"^(Code\s+\d|Acts\s+\d|R\.\s?P\.\s+\d)")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Virginia."""
        return "VA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Virginia."""
        return "Virginia"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Code of Virginia API URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/virginia.md) — a
        trailing slash is required on each:

        * Title: ``CoVChaptersGetListOfJson/{title}`` — the per-title
          chapter listing.
        * Chapter: ``CoVSectionsGetListOfJson/{title}/{chapter}`` — the
          per-chapter section listing.
        * Section: ``CoVSectionsGetSectionDetailsJson/{section}`` — the
          section's own detail. Per :class:`SectionRef`'s convention as
          used by this adapter, ``ref.identifier`` is already the full
          flat citation (e.g. ``"18.2-51"``), so it is used directly,
          exactly as ``WashingtonAdapter`` treats its
          ``SectionRef.identifier``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a
                :class:`TitleRef`, :class:`ChapterRef`, or
                :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/CoVSectionsGetSectionDetailsJson/{ref.identifier}/"
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/CoVSectionsGetListOfJson/"
                f"{ref.title.identifier}/{ref.identifier}/"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/CoVChaptersGetListOfJson/{ref.identifier}/"
        else:
            raise UnsupportedRefError(
                f"VirginiaAdapter.build_url does not support refs of type "
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
            The decoded JSON value (list or dict, per endpoint).

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

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Code of Virginia from the
        ``CoVTitlesGetListOfJson`` endpoint.

        The response is a JSON array of ``{"TitleNumber", "TitleName"}``
        rows. VERIFIED that the API can list the same ``TitleNumber``
        more than once with cosmetically different names, so this method
        deduplicates on ``TitleNumber``, keeping the first valid
        occurrence (the same keep-first convention ``IllinoisAdapter``
        uses for its listings). Rows that lack a usable ``TitleNumber``
        are skipped.

        Returns:
            A sequence of :class:`TocNode`, one per distinct title, in
            the order first encountered. Each node's ``ref`` is a
            :class:`TitleRef` whose ``identifier`` is the ``TitleNumber``
            (e.g. ``"18.2"``) and whose ``name`` is the ``TitleName``.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched,
                if the response is not a JSON array, or if no usable
                title rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/CoVTitlesGetListOfJson/"
        data = self._fetch_json(url, what="Virginia title listing")

        if not isinstance(data, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response was not a JSON array of "
                "titles; the API's response shape may have changed."
            )

        seen: dict[str, None] = {}
        titles = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("TitleNumber")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen[identifier] = None
            name = entry.get("TitleName")
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name if isinstance(name, str) and name.strip() else identifier,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable titles in it; the "
                "API's response shape may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the
        ``CoVChaptersGetListOfJson/{title}`` endpoint.

        VERIFIED that the API returns chapters in lexicographic order
        (e.g. ``1, 10, 11, 2, ...``), so this method re-sorts them
        numerically rather than trusting the API order. Chapter numbers
        can themselves be dotted (e.g. ``"2.1"``), handled by the sort
        key below.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the ``ChapterNum`` and whose ``name`` is
            the ``ChapterName``.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched,
                if the response has no ``ChapterList`` array, or if no
                usable chapter rows could be parsed from it.
        """
        url = self.build_url(title_ref)
        data = self._fetch_json(url, what="Virginia chapter listing")

        chapter_list = data.get("ChapterList") if isinstance(data, dict) else None
        if not isinstance(chapter_list, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'ChapterList' "
                "array; either the API's response shape has changed or "
                f"title {title_ref.identifier!r} does not resolve."
            )

        seen: dict[str, None] = {}
        chapters = []
        for entry in chapter_list:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("ChapterNum")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen[identifier] = None
            name = entry.get("ChapterName")
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name if isinstance(name, str) and name.strip() else identifier,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapters in it; either "
                f"title {title_ref.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the
        ``CoVSectionsGetListOfJson/{title}/{chapter}`` endpoint.

        VERIFIED that the response nests sections three levels deep —
        ``ArticleList`` -> ``SubPartList`` -> ``SectionList`` — with
        ``Article``/``SubPart`` being presentation grouping only. The
        framework models exactly three levels (``TitleRef`` ->
        ``ChapterRef`` -> ``SectionRef``), so this method flattens all
        three nesting levels into a flat sequence of ``TocNode`` and
        does NOT expose Article/SubPart as hierarchy levels.

        Section identifiers are preserved exactly as returned (e.g.
        ``"1-1"``, ``"18.2-76.2"``) and may contain decimal/multi-part
        forms. The result is sorted deterministically and deduplicated on
        ``SectionNumber`` (keep-first), so a section listed under more
        than one grouping is returned once.

        Returns:
            A sequence of :class:`TocNode`, one per section, in
            deterministic numeric order. Each node's ``ref`` is a
            :class:`SectionRef` whose ``identifier`` is the
            ``SectionNumber`` and whose ``name`` is the ``SectionTitle``.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched,
                if the response has no ``ArticleList`` array, or if no
                usable section rows could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        data = self._fetch_json(url, what="Virginia section listing")

        article_list = data.get("ArticleList") if isinstance(data, dict) else None
        if not isinstance(article_list, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'ArticleList' "
                "array; either the API's response shape has changed or "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} does not resolve."
            )

        seen: dict[str, None] = {}
        sections = []
        for article in article_list:
            if not isinstance(article, dict):
                continue
            subpart_list = article.get("SubPartList")
            if not isinstance(subpart_list, list):
                continue
            for subpart in subpart_list:
                if not isinstance(subpart, dict):
                    continue
                section_list = subpart.get("SectionList")
                if not isinstance(section_list, list):
                    continue
                for section in section_list:
                    if not isinstance(section, dict):
                        continue
                    identifier = section.get("SectionNumber")
                    if not isinstance(identifier, str) or not identifier.strip():
                        continue
                    identifier = identifier.strip()
                    if identifier in seen:
                        continue
                    seen[identifier] = None
                    name = section.get("SectionTitle")
                    sections.append(
                        TocNode(
                            level=HierarchyLevel.SECTION,
                            identifier=identifier,
                            name=(
                                name
                                if isinstance(name, str) and name.strip()
                                else identifier
                            ),
                            ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                        )
                    )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable sections in it; either "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for chapter and section
        identifiers.

        Sorts on the leading integer first, falling back to the raw
        string for any dotted/lettered suffix — the same convention
        ``IllinoisAdapter`` uses — so ``1, 2, 2.1, 10`` and
        ``18.2-30, 18.2-76.2`` order sensibly regardless of the API's
        lexicographic order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Virginia.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way ``WashingtonAdapter`` and
        ``TexasAdapter`` do: rather than requiring exact string
        equality, this checks that ``ref.identifier`` (Virginia's flat
        citation, e.g. ``"18.2-51"``) appears verbatim within
        ``raw_citation`` (the ``SectionRange``, e.g. ``§ 18.2-51``). The
        stronger title/chapter/section cross-check against the source
        response happens in :meth:`retrieve_section`, which has the
        JSON's structured fields; ``normalize`` enforces state and
        citation agreement, consistent with the other adapters.

        ``status`` is always left at its default (``UNKNOWN``): nothing
        verified about the Virginia source provides a structural
        repealed/amended/renumbered signal, and the contract forbids
        inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Virginia ref
                (``ref.state_code != "VA"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"VirginiaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one Code of Virginia section, end to
        end: :meth:`build_url` -> fetch the section-detail JSON ->
        cross-check the response against ``ref`` -> parse ``Body`` into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED response shape (docs/research/virginia.md): the detail
        endpoint returns one section inside
        ``{"TitleNumber", ..., "ChapterList":[{...}]}``, keyed by the
        flat ``SectionNumber``. A nonexistent or malformed section number
        returns HTTP 200 with an **empty** ``ChapterList`` — never HTTP
        404 — so an empty ``ChapterList`` is treated as not-found and
        raises :class:`RefNotFoundError` (the section no longer resolves
        to anything real on the source).

        The response's ``TitleNumber``, ``ChapterNum``, and
        ``SectionNumber`` are cross-checked against the requested
        ``TitleRef``/``ChapterRef``/``SectionRef`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed — the
        framework-strong equivalent of ``IllinoisAdapter``'s three-part
        cross-check, possible here because the JSON exposes those fields
        directly.

        Args:
            ref: The section to retrieve. Must be a Virginia ref
                (``ref.state_code == "VA"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section-detail endpoint
                cannot be fetched or its response is not valid JSON.
            RefNotFoundError: If the response contains an empty
                ``ChapterList`` (the verified not-found signal).
            RefMismatchError: If the response's ``TitleNumber``,
                ``ChapterNum``, or ``SectionNumber`` disagrees with
                ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but required
                fields (``SectionRange``, non-empty ``Body``) are
                missing, or the body is empty after cleaning. Also
                raised by :meth:`normalize` if ``ref`` is not a Virginia
                ref.
        """
        url = self.build_url(ref)
        data = self._fetch_json(url, what="Virginia section detail")

        if not isinstance(data, dict):
            raise NormalizationError(
                f"Fetched {url!r} but the response was not a JSON object; "
                "the API's response shape may have changed."
            )

        chapter_list = data.get("ChapterList")
        if not isinstance(chapter_list, list) or not chapter_list:
            raise RefNotFoundError(
                f"Fetched {url!r} but the response contained no section; "
                f"either section {ref.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        section = chapter_list[0]
        if not isinstance(section, dict):
            raise NormalizationError(
                f"Fetched {url!r} and located section {ref.identifier!r}, but "
                "the section entry in the response was not a JSON object; the "
                "API's response shape may have changed."
            )

        if data.get("TitleNumber") != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section: "
                f"{data.get('TitleNumber')!r}."
            )
        if section.get("ChapterNum") != ref.chapter.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section: {section.get('ChapterNum')!r}."
            )
        if section.get("SectionNumber") != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched response: {section.get('SectionNumber')!r}."
            )

        raw_citation = section.get("SectionRange")
        if not isinstance(raw_citation, str) or not raw_citation.strip():
            raise NormalizationError(
                f"Fetched {url!r} and located section {ref.identifier!r}, but "
                "the response contained no 'SectionRange' citation; the API's "
                "response shape may have changed."
            )
        raw_citation = raw_citation.strip()

        heading = section.get("SectionTitle")
        if isinstance(heading, str):
            heading = heading.strip() or None

        body_html = section.get("Body")
        if not isinstance(body_html, str) or not body_html.strip():
            raise NormalizationError(
                f"Fetched {url!r} and located section {ref.identifier!r}, but "
                "the response contained no 'Body' text; the API's response "
                "shape may have changed."
            )

        text, amendment_notes = self._split_body(body_html)
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and located section {ref.identifier!r}, but "
                "its body text was empty after cleaning; the API's response "
                "shape may have changed."
            )

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    def _split_body(self, body_html: str) -> tuple[str, str | None]:
        """Clean the HTML ``Body`` and split statute text from trailing
        legislative-history prose.

        ``Body`` is VERIFIED to be HTML with one ``<p>`` per paragraph.
        Cleaning it with the shared
        :func:`~state_statutes_mcp.adapters._htmltext.strip_tags` helper
        (``preserve_block_breaks=True``) yields one paragraph per line.
        The verified history format is trailing prose whose paragraph
        begins with e.g. ``Code 1919, ...`` or ``R. P. 1948, ...``, so
        this finds the **last** paragraph matching :data:`_HISTORY_START`
        and treats it and everything after it as ``amendment_notes``.

        Taking the last match (rather than the first) is the conservative
        choice: it keeps an early body paragraph that happens to start
        with "Code ..." from being mistaken for history, and it never
        invents a boundary. If no paragraph matches, all cleaned text is
        body and ``amendment_notes`` is None — a legitimate outcome for
        sections without a verified history line.

        Args:
            body_html: The raw HTML ``Body`` from the section detail.

        Returns:
            A ``(text, amendment_notes)`` pair. ``text`` is the statute
            body (paragraphs joined with a blank line); ``amendment_notes``
            is the trailing history prose or None.
        """
        cleaned = strip_tags(body_html, preserve_block_breaks=True)
        paragraphs = [paragraph.strip() for paragraph in cleaned.split("\n")]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]

        history_start = None
        for index, paragraph in enumerate(paragraphs):
            if self._HISTORY_START.match(paragraph):
                history_start = index

        if history_start is not None:
            text = "\n\n".join(paragraphs[:history_start])
            amendment_notes = "\n\n".join(paragraphs[history_start:]) or None
        else:
            text = "\n\n".join(paragraphs)
            amendment_notes = None

        return text, amendment_notes