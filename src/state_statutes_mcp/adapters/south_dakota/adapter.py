"""SouthDakotaAdapter: the South Dakota-specific concrete state adapter.

Source: the official South Dakota Legislature JSON API at
``https://sdlegislature.gov/api/Statutes/``. This is the framework's
first adapter whose source is a plain JSON API whose Title/Chapter/Section
records each embed a full HTML document in their ``Html`` field. Unlike
Virginia's flat JSON, the SD API also exposes the hierarchy through a
``parents`` array on each record, and linked-list navigation via
``Next``/``Previous`` fields.

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from
``docs/research/south_dakota.md`` and ``docs/research/state7_candidate_comparison.md``,
which document live requests to the official host):

* Base URL ``https://sdlegislature.gov`` with the API under
  ``/api/Statutes/``.
* Titles: ``GET /api/Statutes/Title`` -> a JSON array of title records
  (71 total, including lettered titles such as ``23A``), each with
  ``Statute`` (the title number, e.g. ``"22"``), ``CatchLine`` (the name,
  e.g. ``"CRIMES"``), and ``Type: "Title"``.
* Chapters: a title record (``GET /api/Statutes/Statute/{title}``, e.g.
  ``/22``) whose embedded ``Html`` links every chapter as
  ``Statute={title}-{chapter}`` anchors (e.g. ``Statute=22-1``,
  ``Statute=22-4A``), with the zero-padded chapter number and chapter
  name in the surrounding text. Title 22 lists 62 chapters, including
  lettered chapters like ``22-4A`` (verified).
* Sections: a chapter record (``GET /api/Statutes/Statute/{title}-{chapter}``,
  e.g. ``/22-3``) whose embedded ``Html`` links every section as
  ``Statute={title}-{chapter}-{section}`` anchors (e.g. ``Statute=22-3-1``,
  ``Statute=22-3-1.1``), with the full section number and the catchline in
  the surrounding text. Chapter 22-3 lists 11 sections (verified).
* Section content: ``GET /api/Statutes/Statute/{full-number}`` (e.g.
  ``/22-3-1``) returns the flat section record. Its ``Html`` field is a
  full rendered XHTML document with a ``<head>`` ``<style>`` block and a
  ``<body>``. Stripping the ``<body>`` (with ``preserve_block_breaks=True``)
  yields: a first line holding the section number plus catchline, the body
  paragraphs, and a final ``Source:`` line carrying the amendment history
  (verified).
* Citation: ``SDCL § {title}-{chapter}-{section}`` (e.g. ``SDCL § 22-3-1``),
  adapter-constructed. ``SectionRef.identifier`` is the full section
  number and carries title + chapter -- the same convention
  ``WashingtonAdapter``/``TexasAdapter``/``FloridaAdapter`` use.
* Status: each record carries a ``Repealed`` boolean, but it is ``False``
  even on sections whose text reads "Repealed by SL ..." (verified), so
  repeal is prose-only and ``status`` stays ``UNKNOWN``.
* Error boundary: a nonexistent chapter or section returns HTTP 404
  (verified), mapped here to ``RefNotFoundError``.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/south_dakota.md``): whether a formal rate-limit policy
exists; whether every title's embedded ``Html`` renders identically
(sampled Title 22 and Chapter 22-3 only); whether historical editions of
the Codified Laws are available (the adapter serves the current code,
like Virginia/Delaware); and the ``Constitution`` sub-API. None of these
block the implementation below.
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


class SouthDakotaAdapter(BaseStateAdapter):
    """Concrete state adapter for the South Dakota Codified Laws JSON API
    at sdlegislature.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract), mirroring the shape
    already established by the other adapters. See the module docstring
    for the verified API structure this adapter is built against.
    """

    BASE_URL = "https://sdlegislature.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Anchors matching the VERIFIED chapter listing in a title record's
    # embedded Html, e.g. "...?Type=Statute&amp;Statute=22-1" or
    # "...?Statute=22-4A". The chapter number is one hyphen-free segment
    # after the title, and may be lettered (e.g. "4A"). Anchored to the
    # end of the href value so a cross-reference to a section (e.g.
    # "Statute=22-3-1") is never mistaken for a chapter.
    _HREF_VALUE = re.compile(r"Statute=([^\"&\s]+)")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for South Dakota."""
        return "SD"

    @property
    def state_name(self) -> str:
        """Human-facing display name for South Dakota."""
        return "South Dakota"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official South Dakota Codified Laws API URL for
        ``ref``.

        VERIFIED endpoint shapes (see docs/research/south_dakota.md):

        * Title: ``/api/Statutes/Statute/{title}`` -- the per-title
          chapter listing.
        * Chapter: ``/api/Statutes/Statute/{title}-{chapter}`` -- the
          per-chapter section listing.
        * Section: ``/api/Statutes/Statute/{full-number}`` -- the
          section's own record. Per :class:`SectionRef`'s convention as
          used by this adapter, ``ref.identifier`` is already the full
          citation (e.g. ``"22-3-1"``), so it is used directly, exactly
          as ``VirginiaAdapter`` and ``WashingtonAdapter`` treat their
          ``SectionRef.identifier``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref`` is not a :class:`TitleRef`,
                :class:`ChapterRef`, or :class:`SectionRef`.
        """
        if isinstance(ref, SectionRef):
            return f"{self.BASE_URL}/api/Statutes/Statute/{ref.identifier}"
        elif isinstance(ref, ChapterRef):
            return (
                f"{self.BASE_URL}/api/Statutes/Statute/"
                f"{ref.title.identifier}-{ref.identifier}"
            )
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/api/Statutes/Statute/{ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"SouthDakotaAdapter.build_url does not support refs of type "
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
        ``AdapterUnavailableError`` there. A VERIFIED HTTP 404 (returned
        for nonexistent titles/chapters/sections) surfaces through that
        helper as an ``AdapterUnavailableError`` whose ``__cause__`` is
        an ``urllib.error.HTTPError`` with code 404 -- this method
        detects that and re-raises as :class:`RefNotFoundError`, the same
        pattern ``FloridaAdapter`` and ``DelawareAdapter`` use. A
        response that is not valid JSON is wrapped into
        ``AdapterUnavailableError`` -- the source responded, but not in
        the expected shape.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The decoded JSON value (list or dict, per endpoint).

        Raises:
            RefNotFoundError: If ``url`` returns HTTP 404.
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
                    "does not resolve on the South Dakota Codified Laws site."
                ) from exc
            raise
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but its response was not valid JSON: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Embedded-Html helpers
    # ------------------------------------------------------------

    @classmethod
    def _body_html(cls, html: str) -> str:
        """Isolate the ``<body>...</body>`` region of a record's embedded
        ``Html`` document.

        A record's ``Html`` field is a full XHTML document with a
        ``<head>`` holding a ``<style>`` block. VERIFIED (docs/research/
        south_dakota.md) that the rendered chapter/section content lives
        entirely inside ``<body>``, and that cross-reference noise (e.g.
        the 835 ``Statute=22..`` matches in Title 22's full document)
        lives outside it. Restricting parsing to the body is therefore
        both the correct extraction and the noise filter: Title 22's body
        contains exactly its 62 chapter anchors.

        If the document has no ``<body>`` markers, the whole document is
        returned as a safe fallback (callers still tag-strip it).

        Args:
            html: The record's raw ``Html`` field.

        Returns:
            The ``<body>`` region, or the whole document if none is found.
        """
        start = html.lower().find("<body")
        end = html.lower().find("</body>")
        if start != -1 and end != -1 and end > start:
            return html[start:end]
        return html

    @classmethod
    def _strip_styles(cls, html: str) -> str:
        """Remove ``<style>``/``<script>`` blocks so they never leak into
        parsed text (the body carries no such blocks, but the whole-document
        fallback path may)."""
        without_style = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE
        )
        return re.sub(
            r"<script\b[^>]*>.*?</script>",
            " ",
            without_style,
            flags=re.DOTALL | re.IGNORECASE,
        )

    @classmethod
    def _listing_lines(cls, html: str) -> list[str]:
        """Clean a record's embedded ``Html`` into non-empty lines.

        Restricts to the ``<body>`` region, strips ``<style>``/``<script>``
        blocks (belt-and-suspenders for the fallback path), then runs the
        shared :func:`~state_statutes_mcp.adapters._htmltext.strip_tags`
        helper with ``preserve_block_breaks=True`` so each ``<p>``/``<div>``
        boundary becomes a line, exactly as the verified body does.

        Args:
            html: The record's raw ``Html`` field.

        Returns:
            A list of non-empty cleaned lines.
        """
        body = cls._body_html(html)
        cleaned = strip_tags(cls._strip_styles(body), preserve_block_breaks=True)
        return [line.strip() for line in cleaned.split("\n") if line.strip()]

    @classmethod
    def _parse_entries(
        cls,
        html: str,
        *,
        pattern: re.Pattern[str],
        prefix: str,
        strip_leading: re.Pattern[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Parse ``identifier``/``name`` pairs out of a listing document.

        Splits the ``<body>`` into ``<p>`` blocks, keeps only blocks that
        contain a ``Statute={prefix}`` href, and takes the **first** href
        matching ``pattern`` as the entry's identifier. The name is the
        block's tag-stripped text with the leading number token removed:
        ``strip_leading`` is a regex for the case where the token differs
        from the identifier (chapters: the zero-padded number ``01``/
        ``04A`` vs the identifier ``1``/``4A``); when ``strip_leading`` is
        None the identifier itself is stripped (sections: the full number
        ``22-3-1`` leads the block text verbatim). Blocks are
        deduplicated on identifier (keep-first).

        Args:
            html: The record's raw ``Html`` field.
            pattern: Regex whose first group captures the identifier from
                a full ``Statute=`` href value.
            prefix: The ``Statute=`` href prefix that selects listing
                blocks (e.g. ``"22-"`` for chapters of title 22).
            strip_leading: Optional regex to strip from the start of each
                block's text to recover the name; if None, the identifier
                itself is stripped instead.

        Returns:
            A list of ``(identifier, name)`` pairs in document order.
        """
        body = cls._body_html(html)
        blocks = re.split(r"(?=<p\b)", body)
        entries: list[tuple[str, str]] = []
        seen: dict[str, None] = {}
        for block in blocks:
            if prefix not in block:
                continue
            match = cls._HREF_VALUE.search(block)
            if match is None:
                continue
            full_value = match.group(1)
            level_match = pattern.match(full_value)
            if level_match is None:
                continue
            identifier = level_match.group(1)
            if identifier in seen:
                continue
            seen[identifier] = None
            name = strip_tags(cls._strip_styles(block)).strip()
            if strip_leading is None:
                name = re.sub(rf"^\s*{re.escape(identifier)}\s*", "", name)
            else:
                name = strip_leading.sub("", name)
            name = name.lstrip(".,\xa0 ") or identifier
            entries.append((identifier, name))
        return entries

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the South Dakota Codified Laws from
        the ``/api/Statutes/Title`` endpoint.

        The response is a JSON array of title records (71 total,
        including lettered titles such as ``23A``), each with ``Statute``
        (the title number), ``CatchLine`` (the name), and
        ``Type: "Title"``. Records are deduplicated on ``Statute``
        (keep-first) and re-sorted numerically so ``1, 2, ..., 23, 23A,
        24`` order sensibly.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the ``Statute`` and whose ``name`` is the
            ``CatchLine``.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched, if
                the response is not a JSON array, or if no usable title
                rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/api/Statutes/Title"
        data = self._fetch_json(url, what="South Dakota title listing")

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
            identifier = entry.get("Statute")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen[identifier] = None
            name = entry.get("CatchLine")
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

        return tuple(sorted(titles, key=lambda node: self._sort_key(node.identifier)))

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the title
        record's embedded ``Html``.

        ``build_url(title_ref)`` returns the title record, whose ``Html``
        VERIFIED-ly links every chapter as ``Statute={title}-{chapter}``
        anchors (e.g. ``Statute=22-1``, ``Statute=22-4A``). Only the
        ``<body>`` region is parsed, which both extracts the listing and
        filters out the cross-reference noise that lives outside it (Title
        22's full document has 835 ``Statute=22..`` matches; its body has
        exactly its 62 chapters).

        The name is the surrounding text with the zero-padded number
        stripped (e.g. ``01``/``04A``), so ``01 Definitions And General
        Provisions`` becomes ``Definitions And General Provisions``.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"1"``, ``"4A"``)
            and whose ``name`` is the chapter name.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched, or
                if no usable chapter entries could be parsed from it.
        """
        url = self.build_url(title_ref)
        data = self._fetch_json(url, what="South Dakota chapter listing")

        if not isinstance(data, dict):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response was not a JSON object; "
                "the API's response shape may have changed."
            )

        html = data.get("Html")
        if not isinstance(html, str) or not html.strip():
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'Html' field; "
                f"either title {title_ref.identifier!r} does not resolve or "
                "the API's response shape has changed."
            )

        pattern = re.compile(
            rf"{re.escape(title_ref.identifier)}-(\d+[A-Za-z]*)$"
        )
        entries = self._parse_entries(
            html,
            pattern=pattern,
            prefix=f"{title_ref.identifier}-",
            strip_leading=re.compile(r"^\s*\d+[A-Za-z]*\s*"),
        )

        if not entries:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapters in it; either "
                f"title {title_ref.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        chapters = [
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=identifier,
                name=name,
                ref=ChapterRef(title=title_ref, identifier=identifier),
            )
            for identifier, name in entries
        ]
        return tuple(sorted(chapters, key=lambda node: self._sort_key(node.identifier)))

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter
        record's embedded ``Html``.

        ``build_url(chapter_ref)`` returns the chapter record, whose
        ``Html`` VERIFIED-ly links every section as
        ``Statute={title}-{chapter}-{section}`` anchors (e.g.
        ``Statute=22-3-1``, ``Statute=22-3-1.1``), with the full section
        number and the catchline in the surrounding text.

        The site groups repealed sections into a single listing line (e.g.
        Chapter 22-3 lists ``22-3-6`` and ``22-3-7`` together under one
        entry whose text reads ``22-3-6 , 22-3-7. Repealed by SL 1976,
        ch 158 , § 3-5``), so this method preserves exactly the listing the
        site presents: one ``TocNode`` per ``<p>`` block, identified by the
        block's **first** section-form href, exactly as a repealed range
        appears (the same keep-one-entry convention Delaware uses for its
        reserved range blocks).

        The name is the block's text with the leading full section number
        stripped, e.g. ``22-3-1 Persons capable of committing crimes--
        Exceptions.`` becomes ``Persons capable of committing crimes--
        Exceptions.``.

        Returns:
            A sequence of :class:`TocNode`, one per listed section, in
            numeric order. Each node's ``ref`` is a :class:`SectionRef`
            whose ``identifier`` is the full section number (e.g.
            ``"22-3-1"``) and whose ``name`` is the section's catchline
            as presented in the listing.

        Raises:
            AdapterUnavailableError: If the listing cannot be fetched, or
                if no usable section entries could be parsed from it.
        """
        url = self.build_url(chapter_ref)
        data = self._fetch_json(url, what="South Dakota section listing")

        if not isinstance(data, dict):
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response was not a JSON object; "
                "the API's response shape may have changed."
            )

        html = data.get("Html")
        if not isinstance(html, str) or not html.strip():
            raise AdapterUnavailableError(
                f"Fetched {url!r} but the response contained no 'Html' field; "
                f"either chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        full_number = f"{chapter_ref.title.identifier}-{chapter_ref.identifier}"
        pattern = re.compile(
            rf"({re.escape(full_number)}-\d+(?:\.\d+)?[A-Za-z]*)$"
        )
        entries = self._parse_entries(
            html,
            pattern=pattern,
            prefix=f"{full_number}-",
        )

        if not entries:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable sections in it; either "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} does not resolve or the "
                "API's response shape has changed."
            )

        sections = [
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=identifier,
                name=name,
                ref=SectionRef(chapter=chapter_ref, identifier=identifier),
            )
            for identifier, name in entries
        ]
        return tuple(sorted(sections, key=lambda node: self._sort_key(node.identifier)))

    @staticmethod
    def _sort_key(identifier: str) -> tuple:
        """Deterministic numeric-first sort key for title/chapter/section
        identifiers.

        Sorts on the leading integer first, falling back to the raw string
        for any lettered/dotted suffix -- the same convention
        ``IllinoisAdapter`` uses -- so ``1, 2, 4A, 10, 22`` and
        ``22-3-1, 22-3-1.1, 22-3-10`` order sensibly regardless of the
        API's order.
        """
        leading = re.match(r"\d+", identifier)
        return (int(leading.group()) if leading else 0, identifier)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        South Dakota.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way ``WashingtonAdapter`` and
        ``VirginiaAdapter`` do: rather than requiring exact string
        equality, this checks that ``ref.identifier`` (South Dakota's full
        citation, e.g. ``"22-3-1"``) appears verbatim within
        ``raw_citation`` (e.g. ``SDCL § 22-3-1``). The stronger
        title/chapter/section cross-check against the source response
        happens in :meth:`retrieve_section`, which has the JSON's
        structured ``parents`` fields; ``normalize`` enforces state and
        citation agreement, consistent with the other adapters.

        ``status`` is always left at its default (``UNKNOWN``): the
        record's ``Repealed`` boolean is VERIFIED-unreliable (``False``
        even on sections whose text reads "Repealed by SL ..."), and the
        contract forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a South Dakota ref
                (``ref.state_code != "SD"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"SouthDakotaAdapter.normalize cannot normalize a ref for state "
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
        """Retrieve and normalize one South Dakota Codified Law section,
        end to end: :meth:`build_url` -> fetch the section record JSON ->
        cross-check the response against ``ref`` -> parse the embedded
        ``Html`` into a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED response shape (docs/research/south_dakota.md): the
        section endpoint returns a flat record with ``Type: "Section"``,
        ``Statute`` equal to the requested full number, and a ``parents``
        array whose ``Title``/``Chapter`` entries carry the title and
        chapter numbers. The record's ``TitleNumber``/``ChapterNumber``
        equivalents are cross-checked against the requested
        ``TitleRef``/``ChapterRef`` and a mismatch raises
        :class:`RefMismatchError` before anything is parsed -- the
        framework-strong equivalent of ``IllinoisAdapter``'s three-part
        cross-check, possible here because the ``parents`` array exposes
        those fields directly.

        The ``Html`` field is parsed with the shared
        :func:`~state_statutes_mcp.adapters._htmltext.strip_tags` helper
        (``preserve_block_breaks=True``). VERIFIED layout of the cleaned
        body: the first line is the section number plus catchline; the
        middle lines are the body paragraphs; the final line begins with
        ``Source:`` and carries the amendment history. ``heading`` comes
        from the record's ``CatchLine`` field; the ``Source:`` line (and
        everything after it) becomes ``amendment_notes``.

        ``Next``/``Previous`` are not used: the section is addressed
        directly by its full number, so no linked-list traversal is
        required.

        Args:
            ref: The section to retrieve. Must be a South Dakota ref
                (``ref.state_code == "SD"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section endpoint cannot be
                fetched or its response is not valid JSON.
            RefNotFoundError: If the endpoint returns HTTP 404 (the
                verified not-found signal).
            RefMismatchError: If the record's ``Statute`` or ``parents``
                disagree with ``ref``. Also raised by :meth:`normalize`
                on citation disagreement.
            NormalizationError: If the section was located but required
                fields (``Html``, non-empty body) are missing, or the
                body is empty after cleaning. Also raised by
                :meth:`normalize` if ``ref`` is not a South Dakota ref.
        """
        url = self.build_url(ref)
        data = self._fetch_json(url, what="South Dakota section")

        if not isinstance(data, dict):
            raise NormalizationError(
                f"Fetched {url!r} but the response was not a JSON object; "
                "the API's response shape may have changed."
            )

        if data.get("Type") != "Section":
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the record was not of type 'Section'; the API's response "
                "shape may have changed."
            )

        if data.get("Statute") != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"section in the fetched response: {data.get('Statute')!r}."
            )

        parents = data.get("parents")
        if not isinstance(parents, list):
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the response contained no 'parents' array; the API's response "
                "shape may have changed."
            )

        title_entry = next(
            (
                parent
                for parent in parents
                if isinstance(parent, dict) and parent.get("Type") == "Title"
            ),
            None,
        )
        chapter_entry = next(
            (
                parent
                for parent in parents
                if isinstance(parent, dict) and parent.get("Type") == "Chapter"
            ),
            None,
        )
        if title_entry is not None and str(title_entry.get("Statute")) != (
            ref.chapter.title.identifier
        ):
            raise RefMismatchError(
                f"Requested title {ref.chapter.title.identifier!r} does not "
                f"match the title in the fetched section: "
                f"{title_entry.get('Statute')!r}."
            )
        if chapter_entry is not None and str(chapter_entry.get("Statute")) != (
            ref.chapter.identifier
        ):
            raise RefMismatchError(
                f"Requested chapter {ref.chapter.identifier!r} does not match "
                f"the chapter in the fetched section: "
                f"{chapter_entry.get('Statute')!r}."
            )

        heading = data.get("CatchLine")
        if isinstance(heading, str):
            heading = heading.strip() or None

        html = data.get("Html")
        if not isinstance(html, str) or not html.strip():
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
                "the response contained no 'Html' text; the API's response "
                "shape may have changed."
            )

        raw_citation = f"SDCL § {ref.identifier}"
        text, amendment_notes = self._split_body(html)
        if not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, but "
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

    def _split_body(self, html: str) -> tuple[str, str | None]:
        """Clean a section record's embedded ``Html`` and split statute
        text from the trailing ``Source:`` amendment-history line.

        VERIFIED layout (docs/research/south_dakota.md): cleaning the
        ``<body>`` with the shared
        :func:`~state_statutes_mcp.adapters._htmltext.strip_tags` helper
        (``preserve_block_breaks=True``) yields one line per paragraph:
        the first line is the section number plus catchline, the middle
        lines are the body paragraphs, and the final line begins with
        ``Source:`` and carries the amendment history (e.g.
        ``Source: SDC 1939, § 13.0201; SL 1968, ch 28, §§ 1, 2; ...``).

        This skips the first line entirely (the heading comes from the
        record's ``CatchLine`` field, so the number+catchline line is
        redundant) and treats the first ``Source:`` line and everything
        after it as ``amendment_notes``. If no ``Source:`` line exists,
        all cleaned lines after the first are body and ``amendment_notes``
        is None -- a legitimate outcome for sections without a verified
        history line.

        Args:
            html: The raw ``Html`` field from the section record.

        Returns:
            A ``(text, amendment_notes)`` pair. ``text`` is the statute
            body (paragraphs joined with a blank line);
            ``amendment_notes`` is the trailing history prose or None.
        """
        lines = self._listing_lines(html)

        source_index = next(
            (index for index, line in enumerate(lines) if line.startswith("Source:")),
            None,
        )

        if source_index is not None:
            text = "\n\n".join(lines[1:source_index])
            amendment_notes = "\n\n".join(lines[source_index:]) or None
        else:
            text = "\n\n".join(lines[1:])
            amendment_notes = None

        return text, amendment_notes