"""KansasAdapter: the Kansas-specific concrete state adapter.

Source: the official Kansas Legislature JSON API at
``https://www.kslegislature.gov/api/v1/statutes/``. This is the
framework's second JSON-consuming adapter (after Virginia): the API is a
plain, unauthenticated, pagination-aware JSON service with no JS
rendering. Unlike Virginia (single flat title -> chapter -> section),
Kansas's hierarchy is Chapter -> Article -> Section, which this adapter
flattens onto the framework's TitleRef -> ChapterRef -> SectionRef model
(Chapter becomes the synthetic TitleRef).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the
MCP ``get_section`` tool (see ``BaseStateAdapter``'s module docstring for
that requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/kansas.md``, which documents live requests to the
official host):

* Index: ``/api/v1/statutes/`` -> ``{"count": 87, "results":
  [{"chapter": int, "caption": "", "section_count", "href"}]}``. Chapter
  captions are always empty in the verified response.
* Article listing: ``?chapter={N}`` -> ``{"chapter", "caption": "",
  "count", "results": [{"article": int, "caption": "", "section_count",
  "href"}]}``. Article captions are always empty.
* Section listing: ``?chapter={N}&article={M}`` -> ``{"chapter",
  "chapter_caption", "article", "article_caption", "count",
  "next_offset", "previous_offset", "results": [{"number", "caption",
  "url"}]}``. Paginated at 200 per page via ``next_offset``/``offset``.
* Section detail: ``/api/v1/statutes/{section}/`` -> ``{"section",
  "chapter", "rest", "text", "url"}``. ``text`` is ONE plain-text string
  ``"{section}. {heading} {body}History: ..."``. A nonexistent section
  returns HTTP 404. A comma inside a section number MUST be URL-encoded
  (``%2C``); a bare chapter-only path returns HTTP 400.
* Section identifiers are the full ``{chapter}-{number}`` form and may
  contain a comma (e.g. ``8-1,208``).

**Mapping onto the framework's TitleRef -> ChapterRef -> SectionRef
model** (verified to fit with no additional hierarchy level):

* ``TitleRef.identifier`` = the chapter number (e.g. ``"21"``, ``"8"``).
* ``ChapterRef.identifier`` = the article number (e.g. ``"59"``, ``"1"``).
* ``SectionRef.identifier`` = the full ``{chapter}-{number}`` identifier
  (e.g. ``"21-5903"``, ``"8-1,208"``), already the citation used by the
  section-detail endpoint.

**Citation and body format** (verified): the citation is ``Kan. Stat.
Ann. § {chapter}-{number}`` (e.g. ``Kan. Stat. Ann. § 21-5903``),
adapter-constructed from ``ref.identifier``. The ``text`` field is a
single string: citation prefix, heading, body (subsections inline, no
line breaks), and a trailing ``History: ...`` block. Heading is split
from the body at the first ``(a)``-style subsection marker, and the
``History:`` block (last occurrence) becomes ``amendment_notes``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/kansas.md``): chapter/article captions are always empty
(so those listing names fall back to the identifier); the heading/body
split relies on the first ``(a)`` marker (verified on two samples); and
section-listing pagination beyond the two verified pages is inferred
from the ``next_offset``/``offset`` contract.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
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


class KansasAdapter(BaseStateAdapter):
    """Concrete state adapter for the Kansas Legislature JSON API at
    kslegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by ``WashingtonAdapter``, ``TexasAdapter``,
    ``IllinoisAdapter``, and ``VirginiaAdapter``. See the module
    docstring for the verified API structure this adapter is built
    against.
    """

    BASE_URL = "https://www.kslegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # A section's ``text`` field is one plain string. After stripping the
    # citation prefix (``{section}. ``), the heading ends at the first
    # ``. `` that is immediately followed by an opening paren -- the first
    # ``(a)``-style subsection marker (verified on ``21-5903`` and
    # ``8-1,208``). The regex matches the period+space that precedes the
    # body's first parenthetical marker.
    _BODY_START = re.compile(r"\.\s+(?=\()")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Kansas."""
        return "KS"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Kansas."""
        return "Kansas"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Kansas Legislature API URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/kansas.md):

        * Title (synthetic, a Kansas chapter): ``?chapter={N}`` — the
          per-chapter article listing.
        * Chapter (a Kansas article): ``?chapter={N}&article={M}`` — the
          per-article section listing.
        * Section: ``/api/v1/statutes/{section}/`` — the section's own
          detail. The section identifier (e.g. ``8-1,208``) is URL-encoded
          with ``urllib.parse.quote(..., safe="")`` so an embedded comma
          becomes ``%2C`` (VERIFIED required: a raw comma 404s).

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
            encoded = urllib.parse.quote(ref.identifier, safe="")
            return f"{self.BASE_URL}/api/v1/statutes/{encoded}/"
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/api/v1/statutes/"
                f"?chapter={ref.title.identifier}&article={ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/api/v1/statutes/?chapter={ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"KansasAdapter.build_url does not support refs of type "
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
        ``AdapterUnavailableError`` there. This method additionally maps
        a verified HTTP 404 (e.g. a nonexistent section) into
        :class:`RefNotFoundError` -- the source was reached, but the
        addressed document does not resolve -- mirroring how
        ``MinnesotaAdapter._fetch_html`` handles 404s.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The decoded JSON value (dict, per endpoint).

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than a verified HTTP 404, or if the response
                body is not valid JSON.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Kansas Legislature site).
        """
        try:
            text = fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Kansas Legislature site."
                ) from exc
            raise
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
        """Enumerate every top-level unit of the K.S.A. from the statutes
        index.

        The index is a flat chapter list (``{"chapter", "caption",
        "section_count", "href"}``) where ``chapter`` is an int and
        ``caption`` is always empty. Kansas's official Chapter level maps
        onto the framework's ``TitleRef`` (see the module docstring), so
        each chapter becomes one title node whose identifier is the
        chapter number. Since captions are empty, names fall back to the
        identifier.

        Returns:
            A sequence of :class:`TocNode`, one per chapter (as a
            synthetic title), in the order the API returned them. Each
            node's ``ref`` is a :class:`TitleRef` whose ``identifier`` is
            the chapter number (e.g. ``"21"``).

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched,
                if the response has no ``results`` array, or if no usable
                chapter rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/api/v1/statutes/"
        data = self._fetch_json(url, what="Kansas statutes index")

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'results' "
                "array; the API's response shape may have changed."
            )

        titles = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            chapter = entry.get("chapter")
            if chapter is None:
                continue
            identifier = str(chapter).strip()
            if not identifier:
                continue
            caption = entry.get("caption")
            name = caption if isinstance(caption, str) and caption.strip() else identifier
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapters in it; the "
                "API's response shape may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every article under ``title_ref`` (a Kansas chapter)
        from the ``?chapter={N}`` endpoint.

        Kansas's official Article level maps onto the framework's
        ``ChapterRef`` (see the module docstring). The response is a flat
        article list (``{"article": int, "caption": "", ...}``) where
        ``article`` is an int and ``caption`` is always empty, so names
        fall back to the identifier.

        Returns:
            A sequence of :class:`TocNode`, one per article (as a
            synthetic chapter), in the order the API returned them. Each
            node's ``ref`` is a :class:`ChapterRef` whose ``identifier``
            is the article number (e.g. ``"59"``).

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched,
                if the response has no ``results`` array, or if no usable
                article rows could be parsed from it.
        """
        url = self.build_url(title_ref)
        data = self._fetch_json(url, what="Kansas article listing")

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'results' "
                "array; either the API's response shape has changed or "
                f"chapter {title_ref.identifier!r} does not resolve."
            )

        chapters = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            article = entry.get("article")
            if article is None:
                continue
            identifier = str(article).strip()
            if not identifier:
                continue
            caption = entry.get("caption")
            name = caption if isinstance(caption, str) and caption.strip() else identifier
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
                f"Fetched {url!r} but found no usable articles in it; either "
                f"chapter {title_ref.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` (a Kansas
        article) from the ``?chapter={N}&article={M}`` endpoint.

        Section identifiers are the full ``{chapter}-{number}`` form
        (e.g. ``"21-5903"``, ``"8-113a"``, ``"8-1,208"``), preserved
        exactly as returned. The listing is paginated at 200 results per
        page: the response carries ``next_offset``, and the next page is
        requested by appending ``&offset={next_offset}`` (VERIFIED for
        article 1 of chapter 8, which spans two pages). This method walks
        the pagination until ``next_offset`` is null, so the result is
        the full section list.

        Returns:
            A sequence of :class:`TocNode`, one per section, in numeric
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full ``{chapter}-{number}`` form and
            whose ``name`` is the ``caption`` (falling back to the
            identifier when the caption is empty).

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched, if
                a page lacks a usable ``results`` array, or if no usable
                section rows could be parsed.
        """
        sections = []
        url = self.build_url(chapter_ref)
        visited_offsets: set[Any] = set()

        while True:
            data = self._fetch_json(url, what="Kansas section listing")

            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise AdapterUnavailableError(
                    f"Fetched {url!r} but the response contained no 'results' "
                    "array; either the API's response shape has changed or "
                    f"article {chapter_ref.identifier!r} under chapter "
                    f"{chapter_ref.title.identifier!r} does not resolve."
                )

            for entry in results:
                if not isinstance(entry, dict):
                    continue
                identifier = entry.get("number")
                if not isinstance(identifier, str) or not identifier.strip():
                    continue
                identifier = identifier.strip()
                caption = entry.get("caption")
                sections.append(
                    TocNode(
                        level=HierarchyLevel.SECTION,
                        identifier=identifier,
                        name=(
                            caption
                            if isinstance(caption, str) and caption.strip()
                            else identifier
                        ),
                        ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                    )
                )

            next_offset = data.get("next_offset") if isinstance(data, dict) else None
            if next_offset is None:
                break
            if next_offset in visited_offsets:
                raise AdapterUnavailableError(
                    f"Fetched {url!r} but the listing repeated page offset "
                    f"{next_offset!r}; the API's pagination contract may have "
                    "changed."
                )
            visited_offsets.add(next_offset)
            url = self._listing_url(chapter_ref, next_offset)

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable sections in it; either "
                f"article {chapter_ref.identifier!r} under chapter "
                f"{chapter_ref.title.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    def _listing_url(self, chapter_ref: ChapterRef, offset: Any) -> str:
        """Build the paginated section-listing URL for ``chapter_ref`` at
        ``offset``, appending ``&offset={offset}`` to the base listing
        URL (VERIFIED contract)."""
        base = self.build_url(chapter_ref)
        return f"{base}&offset={offset}"

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for article and section
        identifiers.

        Sorts on the leading integer first, falling back to the raw
        string for any dotted/lettered/comma suffix — the same convention
        ``IllinoisAdapter`` and ``VirginiaAdapter`` use — so ``8-1,208,
        8-113, 8-113a, 8-119`` and article numbers order sensibly
        regardless of the API's listing order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Kansas.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way the other adapters do: rather
        than requiring exact string equality, this checks that
        ``ref.identifier`` (Kansas's full ``{chapter}-{number}`` citation,
        e.g. ``"21-5903"``) appears verbatim within ``raw_citation`` (the
        adapter-constructed ``Kan. Stat. Ann. § 21-5903``). The stronger
        chapter/section cross-check against the source response happens in
        :meth:`retrieve_section`, which has the JSON's structured fields;
        ``normalize`` enforces state and citation agreement, consistent
        with the other adapters.

        ``status`` is always left at its default (``UNKNOWN``): nothing
        verified about the Kansas source provides a structural
        repealed/amended/renumbered signal, and the contract forbids
        inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Kansas ref
                (``ref.state_code != "KS"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"KansasAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one K.S.A. section, end to end:
        :meth:`build_url` -> fetch the section-detail JSON ->
        cross-check the response against ``ref`` -> parse ``text`` into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED response shape (docs/research/kansas.md): the detail
        endpoint returns ``{"section", "chapter", "rest", "text", "url"}``
        where ``section`` is the full identifier (e.g. ``21-5903``),
        ``chapter`` is the top-level chapter number (matching the
        flattened ``TitleRef`` identifier), and ``text`` is one plain
        string with the citation prefix, heading, body, and a trailing
        ``History:`` block. A nonexistent section returns HTTP 404, which
        :meth:`_fetch_json` maps to :class:`RefNotFoundError`.

        The response's ``section`` and ``chapter`` fields are
        cross-checked against the requested ``SectionRef``/``TitleRef``
        and a mismatch raises :class:`RefMismatchError` before anything
        is parsed -- the framework-strong equivalent of
        ``IllinoisAdapter``'s three-part cross-check. (The detail response
        does not expose the article, so the flattened ``ChapterRef`` is
        not independently cross-checkable there.)

        Args:
            ref: The section to retrieve. Must be a Kansas ref
                (``ref.state_code == "KS"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section-detail endpoint
                cannot be fetched or its response is not valid JSON.
            RefNotFoundError: If ``url`` returns HTTP 404 (the verified
                not-found signal for a nonexistent section).
            RefMismatchError: If the response's ``section`` or ``chapter``
                disagrees with ``ref``. Also raised by :meth:`normalize`
                on citation disagreement.
            NormalizationError: If the section was located but required
                fields (``text``) are missing, the citation prefix is
                absent, or the body is empty after parsing. Also raised
                by :meth:`normalize` if ``ref`` is not a Kansas ref.
        """
        url = self.build_url(ref)
        data = self._fetch_json(url, what="Kansas section detail")

        if not isinstance(data, dict):
            raise NormalizationError(
                f"Fetched {url!r} but the response was not a JSON object; "
                "the API's response shape may have changed."
            )

        if data.get("section") != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched response: {data.get('section')!r}."
            )
        if data.get("chapter") != ref.chapter.title.identifier:
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.title.identifier!r} does not "
                f"match the chapter in the fetched section: {data.get('chapter')!r}."
            )

        raw_text = data.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise NormalizationError(
                f"Fetched {url!r} and located section {ref.identifier!r}, but "
                "the response contained no 'text'; the API's response shape "
                "may have changed."
            )
        raw_text = raw_text.strip()

        text, heading, amendment_notes = self._parse_text(raw_text, ref)

        raw_citation = f"Kan. Stat. Ann. § {ref.identifier}"

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    def _parse_text(
        self, raw_text: str, ref: SectionRef
    ) -> tuple[str, str | None, str | None]:
        """Parse the verified ``text`` string into
        ``(body, heading, amendment_notes)``.

        The ``text`` field is one plain string of the verified shape
        ``"{section}. {heading} {body}History: ..."``:

        1. The citation prefix ``"{ref.identifier}. "`` is confirmed and
           stripped; its absence is a ``NormalizationError`` (the source's
           shape changed or the wrong section was served).
        2. The heading is everything up to the first ``. `` immediately
           followed by an ``(`` -- the first ``(a)``-style subsection
           marker (VERIFIED on ``21-5903`` and ``8-1,208``). If no such
           marker exists, the heading is None and the whole remainder is
           treated as body (INFERENCE; not verified to occur).
        3. The trailing ``History:`` block (LAST occurrence) is split out
           verbatim into ``amendment_notes``; everything before it is the
           body. If there is no ``History:`` block, ``amendment_notes``
           is None.

        Args:
            raw_text: The ``text`` field from the section detail.
            ref: The requested section, used for the citation-prefix
                cross-check.

        Returns:
            A ``(text, heading, amendment_notes)`` triple.

        Raises:
            NormalizationError: If ``raw_text`` does not start with the
                citation prefix ``"{ref.identifier}. "``, or if the body
                is empty after parsing.
        """
        prefix = f"{ref.identifier}. "
        if not raw_text.startswith(prefix):
            raise NormalizationError(
                f"Fetched section {ref.identifier!r} but its text did not start "
                f"with the expected citation prefix {prefix!r}; the API's "
                "response shape may have changed."
            )
        remainder = raw_text[len(prefix):]

        match = self._BODY_START.search(remainder)
        if match is not None:
            heading = remainder[: match.start() + 1].strip() or None
            body = remainder[match.end():].strip()
        else:
            heading = None
            body = remainder.strip()

        history_index = body.rfind("History:")
        if history_index != -1:
            amendment_notes = body[history_index:].strip() or None
            body = body[:history_index].rstrip()
        else:
            amendment_notes = None

        if not body:
            raise NormalizationError(
                f"Fetched section {ref.identifier!r} but its body text was "
                "empty after parsing; the API's response shape may have "
                "changed."
            )

        return body, heading, amendment_notes
