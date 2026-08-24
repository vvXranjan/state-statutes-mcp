"""AlabamaAdapter: the Alabama-specific concrete state adapter.

Source: the official ALISON (Alabama Legislative Information System)
GraphQL API at ``https://alison.legislature.state.al.us/graphql``,
published by the Alabama Legislature. The API requires no authentication
and no API key; the official Alabama Code of 1975 is served as JSON
section records with embedded HTML content. This is the framework's first
GraphQL/JSON-POST-consuming adapter and introduces the shared
:func:`~state_statutes_mcp.adapters._fetch.fetch_graphql` helper (the only
POST transport in the framework; it is a pure addition, fully backward
compatible with the existing ``fetch_url`` / ``fetch_bytes`` GET helpers).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/alabama.md``;
all structures verified against real live captures of the official API on
Aug 23 2026 from this environment):

* Discovery query ``{ codeOfAlabamaTitles }`` returns the entire Code of
  Alabama table of contents as ONE delimited string (~4.2 MB, ~59,000
  entries, ~10.6s to retrieve):
  * Entries are separated by ``∫``; fields within an entry by ``†``.
  * A title entry: ``{codeId}†Title {n}[{letter}] {name}.`` (51 titles,
    including lettered titles ``10A`` and ``13A``).
  * A chapter entry: ``{codeId}†Chapter {n}[{letter}] {name}.†§{range}``
    (1,529 chapters, including lettered chapters like ``2A``/``2B``; some
    chapters are reserved and lack the range field).
  * A section entry: ``{codeId}†Section {T-C-S} {catchline}.`` (49,271
    sections; catchline may be absent). Citation ``T-C-S`` uses numeric
    parts that may carry trailing letters (e.g. ``10A-20-15.01``,
    ``7-9A-107A``) and decimal sections (e.g. ``1-1-1.1``).
  * Intermediate Article/Division/Part/Subpart entries interleave between
    chapters and sections; the framework's three-level model folds them
    away (Title -> Chapter -> Section).
  * The TOC is hierarchically ordered: a title's chapters (and their
    sections) appear before the next title, so parent chains can be
    tracked while parsing.
* Retrieval query ``{ codesOfAlabama(where: { codeId: { eq: {n} } }) {
  data { id codeId title content } } }`` returns exactly one record whose
  ``content`` is the section's HTML text; ``title`` is
  ``Section {T-C-S} {catchline}.``; ``codeId`` matches the requested one.
* The TOC codeId for a section equals the queryable ``codeId`` (e.g.
  section 2-1-1 -> codeId 17175).
* **Error behavior (VERIFIED)**: a nonexistent ``codeId`` returns an
  empty ``data: []`` (NOT an HTTP error) -- mapped to ``RefNotFoundError``.
  A wrong-but-valid ``codeId`` returns a DIFFERENT section, so the adapter
  cross-checks the returned ``codeId``/``title`` against the requested
  ``SectionRef`` and raises ``RefMismatchError``.
* **Repealed sections (VERIFIED)**: a repealed section's ``content`` is
  just the repeal note (e.g. ``Repealed by Act 2000-220, § 48, effective
  May 13, 2000.``) with no substantive body; the ``title`` field carries
  the (possibly unrepealed-looking) catchline. Following the
  Nebraska/North Carolina convention, the repeal note becomes the
  ``heading`` and ``text`` is empty.

**UNVERIFIED / accepted limitations** (documented in
``docs/research/alabama.md``): only 51 titles / the four targeted sections
(1-1-1, 1-1-1.1, 2-1-1, 4-2-77) and the full TOC were sampled; the
lettered-title ``10A``/``13A`` and lettered-section structures were
verified from the TOC string rather than from a retrieval probe. The full
TOC is ~4.2 MB and is fetched once and cached per adapter instance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_graphql
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


@dataclass(frozen=True)
class _Title:
    """A parsed Alabama Code title entry from the TOC."""

    code_id: str
    identifier: str
    name: str


@dataclass(frozen=True)
class _Chapter:
    """A parsed Alabama Code chapter entry from the TOC."""

    code_id: str
    title_identifier: str
    identifier: str
    name: str


@dataclass(frozen=True)
class _Section:
    """A parsed Alabama Code section entry from the TOC."""

    code_id: str
    title_identifier: str
    chapter_identifier: str
    citation: str
    name: str | None


@dataclass
class _Toc:
    """The parsed Code of Alabama table of contents."""

    titles: list[_Title] = field(default_factory=list)
    chapters: list[_Chapter] = field(default_factory=list)
    sections: list[_Section] = field(default_factory=list)


class AlabamaAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Alabama Code GraphQL API at
    alison.legislature.state.al.us.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The Code of Alabama is a
    uniform ``Title -> Chapter -> Section`` hierarchy. ``TitleRef`` /
    ``ChapterRef`` identifiers are the title/chapter numbers (lettered
    variants preserved, e.g. ``10A``, ``2A``); ``SectionRef.identifier`` is
    always the full ``T-C-S`` citation. See the module docstring.
    """

    GRAPHQL_URL = "https://alison.legislature.state.al.us/graphql"
    DEFAULT_TIMEOUT_SECONDS = 60

    # The discovery query returns the entire Code of Alabama TOC as one
    # delimited string. Entries are separated by '∫', fields by '†'.
    _TOC_QUERY = "{ codeOfAlabamaTitles }"

    # A title entry: '{codeId}†Title 1 General Provisions.' or
    # '{codeId}†Title 10A Alabama Business and Nonprofit Entities Code.'
    _TITLE_ENTRY = re.compile(
        r"^Title\s+([0-9]+[A-Z]?)\s+(.+?)\s*\.?$"
    )

    # A chapter entry:
    # '{codeId}†Chapter 2A The Alabama State Flag Act.†§1-2A-1 to §1-2A-8'
    # (the sectionRange field after the name is present for most chapters,
    # absent for reserved chapters).
    _CHAPTER_ENTRY = re.compile(
        r"^Chapter\s+([0-9]+[A-Z]?)\s+(.+?)\s*\.?$"
    )

    # A section entry: '{codeId}†Section 1-1-1 Meaning of Certain Words
    # and Terms.' or '{codeId}†Section 6-5-800' (no catchline). The
    # citation is the first whitespace-delimited token after 'Section '
    # (e.g. '1-1-1', '1-1-1.1', '7-9A-107A', '31-2A-6a', '41-9-219-6',
    # '45-57-70.01.'), optionally followed by the catchline. A trailing
    # sentence period on the citation token is stripped.
    _SECTION_HEADING = re.compile(r"^Section\s+")

    # A chapter entry: '{codeId}†Chapter 2A The Alabama State Flag Act.'
    # or a reserved chapter with no name: '{codeId}†Chapter 65'.
    _CHAPTER_ENTRY = re.compile(
        r"^Chapter\s+([0-9]+[A-Z]?)(?:\s+(.+?)\s*\.?)?$"
    )

    # A repeal note is the entire content of a repealed section, e.g.
    # 'Repealed by Act 2000-220, § 48, effective May 13, 2000.'.
    _REPEAL_NOTE = re.compile(r"^\s*Repealed\b", re.IGNORECASE)

    def __init__(self) -> None:
        """Create the adapter with an empty per-instance TOC cache.

        The full Code of Alabama TOC is ~4.2 MB and takes ~10s to fetch,
        so it is fetched at most once per adapter instance and cached in
        ``self._toc``. This is instance-local state (each registry owns
        its own constructed adapters), not global mutable state, and is
        consistent with how every existing adapter is a long-lived,
        single-construction object in ``server.build_registry``.
        """
        self._toc: _Toc | None = None

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Alabama."""
        return "AL"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Alabama."""
        return "Alabama"

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Alabama GraphQL endpoint URL for ``ref``.

        Alabama retrieval is a single POST to the GraphQL endpoint for
        every ref level (the request body, not the URL, distinguishes the
        level), so all ref types map to the same endpoint URL.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            The GraphQL endpoint URL.

        Raises:
            UnsupportedRefError: If ``ref`` is not a Title/Chapter/Section
                ref.
        """
        if isinstance(ref, (TitleRef, ChapterRef, SectionRef)):
            return self.GRAPHQL_URL
        raise UnsupportedRefError(
            f"AlabamaAdapter.build_url does not support refs of type "
            f"{type(ref).__name__!r}."
        )

    # ------------------------------------------------------------
    # GraphQL fetch helpers
    # ------------------------------------------------------------

    def _post_graphql(self, query: str, *, what: str) -> dict:
        """POST ``query`` to the Alabama GraphQL endpoint and return the
        decoded JSON.

        Delegates the actual HTTP POST to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_graphql` helper,
        which already wraps network failures and non-JSON responses into
        :class:`AdapterUnavailableError`.

        Args:
            query: The GraphQL query string.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The decoded JSON response body.

        Raises:
            AdapterUnavailableError: If the endpoint cannot be reached, or
                returns a non-JSON response.
        """
        return fetch_graphql(
            self.GRAPHQL_URL,
            query=query,
            what=what,
            timeout=self.DEFAULT_TIMEOUT_SECONDS,
        )

    # ------------------------------------------------------------
    # TOC discovery
    # ------------------------------------------------------------

    def _load_toc(self) -> _Toc:
        """Fetch and parse the Code of Alabama table of contents, caching
        it on the instance.

        The TOC is retrieved once per adapter instance (see
        :meth:`__init__`) and parsed into :class:`_Title` /
        :class:`_Chapter` / :class:`_Section` records with parent chains
        tracked by document order (the TOC is hierarchically ordered:
        a title's chapters and their sections precede the next title).
        Intermediate Article/Division/Part/Subpart entries are skipped --
        the framework's three-level model folds them away.

        Returns:
            The parsed :class:`_Toc`.

        Raises:
            AdapterUnavailableError: If the TOC cannot be fetched, or if no
                usable title entries could be parsed from it.
        """
        if self._toc is not None:
            return self._toc

        response = self._post_graphql(
            self._TOC_QUERY, what="Alabama Code table of contents"
        )
        raw = self._toc_string(response)

        toc = _Toc()
        current_title: str | None = None
        current_chapter: str | None = None
        synthetic_chapters: dict[str, str] = {}

        for entry in raw.split("\u222b"):
            entry = entry.strip()
            if not entry or entry == "\u2020":
                continue
            fields = entry.split("\u2020")
            if len(fields) < 2:
                continue
            code_id = fields[0]
            heading = fields[1]
            # A real title entry has exactly two fields (no suffix). A chapter
            # entry's heading starts with 'Chapter ' (most carry a section
            # range as the third field; a reserved chapter is two fields);
            # a handful of chapters are named 'Title N ...' (e.g. 'Title 1
            # Provisions Applicable to Counties Only.' under Title 11) and
            # carry a section-range field, distinguishing them from real
            # titles (which never carry a range). A section entry can also
            # carry extra fields (an effective date, or a cross-reference
            # like '§45-35A-51.01'), so the chapter detection keys on the
            # heading prefix and the range field, never on field count alone.
            is_chapter_heading = heading.startswith("Chapter ")
            is_title_named_chapter = heading.startswith("Title ") and (
                len(fields) >= 3
            )

            if is_chapter_heading or is_title_named_chapter:
                if current_title is None:
                    continue
                match = self._CHAPTER_ENTRY.match(heading)
                if match is None:
                    continue
                identifier = match.group(1)
                raw_name = match.group(2)
                name = raw_name.strip() if raw_name else identifier
                toc.chapters.append(
                    _Chapter(
                        code_id=code_id,
                        title_identifier=current_title,
                        identifier=identifier,
                        name=name,
                    )
                )
                current_chapter = identifier
            elif heading.startswith("Title ") and not is_title_named_chapter:
                match = self._TITLE_ENTRY.match(heading)
                if match is None:
                    continue
                identifier = match.group(1)
                name = match.group(2).strip()
                toc.titles.append(
                    _Title(code_id=code_id, identifier=identifier, name=name)
                )
                current_title = identifier
                current_chapter = None
            elif heading.startswith("Section "):
                # A section entry is two fields, or four fields (an empty
                # third field plus an effective-date field).
                if current_title is None:
                    continue
                # Title 7 (the Uniform Commercial Code) has no Chapter
                # level: its hierarchy is Title -> Article -> Part ->
                # Section. For the framework's three-level model a single
                # synthetic chapter equal to the title number is exposed
                # (the same flat-title precedent Oklahoma uses), and every
                # of that title's sections is mapped under it.
                if current_chapter is None:
                    synthetic = synthetic_chapters.get(current_title)
                    if synthetic is None:
                        synthetic = current_title
                        toc.chapters.append(
                            _Chapter(
                                code_id="",
                                title_identifier=current_title,
                                identifier=synthetic,
                                name=f"Title {current_title} sections",
                            )
                        )
                        synthetic_chapters[current_title] = synthetic
                    current_chapter = synthetic
                citation, catchline = self._split_section_heading(heading)
                if citation is None:
                    continue
                toc.sections.append(
                    _Section(
                        code_id=code_id,
                        title_identifier=current_title,
                        chapter_identifier=current_chapter,
                        citation=citation,
                        name=catchline.strip() if catchline else None,
                    )
                )
            # else: Article/Division/Part/Subpart (or header) -- skipped.

        if not toc.titles:
            raise AdapterUnavailableError(
                "Fetched the Alabama Code table of contents but found no "
                "usable title entries in it; the site's structure may have "
                "changed."
            )

        self._toc = toc
        return toc

    @staticmethod
    def _split_section_heading(heading: str) -> tuple[str | None, str | None]:
        """Split a ``Section {citation} [{catchline}]`` heading into
        ``(citation, catchline)``.

        The citation is the first whitespace-delimited token after the
        ``Section `` prefix (e.g. ``1-1-1``, ``1-1-1.1``, ``7-9A-107A``,
        ``41-9-219-6``, ``45-57-70.01.``); a single trailing sentence
        period on that token is stripped (so ``45-57-70.`` becomes
        ``45-57-70`` and ``45-57-70.01.`` becomes ``45-57-70.01``). The
        remainder, if any, is the catchline.

        Returns ``(None, None)`` if the heading is not a section heading.
        """
        match = AlabamaAdapter._SECTION_HEADING.match(heading)
        if match is None:
            return None, None
        rest = heading[match.end():].strip()
        token = rest.split(maxsplit=1)
        if not token:
            return None, None
        citation = token[0]
        if citation.endswith("."):
            citation = citation[:-1]
        catchline = token[1].strip() if len(token) > 1 else None
        return citation, catchline

    @staticmethod
    def _toc_string(response: dict) -> str:
        """Extract the TOC delimited string from a ``codeOfAlabamaTitles``
        response, or raise if the response shape is unexpected."""
        data = response.get("data")
        if not isinstance(data, dict):
            raise NormalizationError(
                "The Alabama Code table of contents response was missing "
                "its 'data' object; the API's structure may have changed."
            )
        raw = data.get("codeOfAlabamaTitles")
        if not isinstance(raw, str):
            raise NormalizationError(
                "The Alabama Code table of contents response did not contain "
                "the expected 'codeOfAlabamaTitles' string; the API's "
                "structure may have changed."
            )
        return raw

    @staticmethod
    def _numeric_sort_key(identifier: str) -> tuple[int, str]:
        """Sort key for Alabama identifiers: the integer leading part first,
        then the full identifier for a stable tie-break."""
        match = re.match(r"(\d+)", identifier)
        return (int(match.group(1)) if match else 0, identifier)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every title of the Code of Alabama from the official
        TOC.

        Returns:
            A sequence of :class:`TocNode`, one per title, in numeric
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the title number (e.g. ``"1"``, lettered
            ``"10A"``).

        Raises:
            AdapterUnavailableError: If the TOC cannot be fetched, or if no
                usable title entries could be parsed from it.
        """
        toc = self._load_toc()
        return tuple(
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=title.identifier,
                name=title.name or title.identifier,
                ref=TitleRef(
                    state_code=self.state_code, identifier=title.identifier
                ),
            )
            for title in sorted(
                toc.titles, key=lambda t: self._numeric_sort_key(t.identifier)
            )
        )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from the official
        TOC.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in numeric
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number (e.g. ``"1"``, lettered
            ``"2A"``).

        Raises:
            RefNotFoundError: If ``title_ref`` is not present in the TOC
                (the title does not resolve).
            AdapterUnavailableError: If the TOC cannot be fetched, or if no
                usable chapter entries could be parsed under the title.
        """
        toc = self._load_toc()
        if not any(t.identifier == title_ref.identifier for t in toc.titles):
            raise RefNotFoundError(
                f"Fetched the Alabama Code table of contents but it lists "
                f"no title {title_ref.identifier!r}; the title does not "
                "resolve on the Alabama Legislature site."
            )
        chapters = [
            c for c in toc.chapters if c.title_identifier == title_ref.identifier
        ]
        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched the Alabama Code table of contents but found no "
                f"usable chapter entries under title "
                f"{title_ref.identifier!r}; the title either lists no "
                "chapters or the site's structure has changed."
            )
        return tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=chapter.identifier,
                name=chapter.name or chapter.identifier,
                ref=ChapterRef(title=title_ref, identifier=chapter.identifier),
            )
            for chapter in sorted(
                chapters, key=lambda c: self._numeric_sort_key(c.identifier)
            )
        )

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the official
        TOC.

        ``SectionRef.identifier`` is always the full ``T-C-S`` citation.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full citation (e.g. ``"1-1-1"``).

        Raises:
            RefNotFoundError: If the chapter (or its parent title) is not
                present in the TOC.
            AdapterUnavailableError: If the TOC cannot be fetched, or if no
                usable section entries could be parsed under the chapter.
        """
        toc = self._load_toc()
        if not any(
            c.title_identifier == chapter_ref.title.identifier
            and c.identifier == chapter_ref.identifier
            for c in toc.chapters
        ):
            raise RefNotFoundError(
                f"Fetched the Alabama Code table of contents but it lists "
                f"no chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r}; the chapter does not "
                "resolve on the Alabama Legislature site."
            )
        sections = [
            s
            for s in toc.sections
            if s.title_identifier == chapter_ref.title.identifier
            and s.chapter_identifier == chapter_ref.identifier
        ]
        if not sections:
            raise AdapterUnavailableError(
                f"Fetched the Alabama Code table of contents but found no "
                f"usable section entries under chapter "
                f"{chapter_ref.identifier!r}; the chapter either lists no "
                "sections or the site's structure has changed."
            )
        return tuple(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=section.citation,
                name=section.name or section.citation,
                ref=SectionRef(chapter=chapter_ref, identifier=section.citation),
            )
            for section in sections
        )

    # ------------------------------------------------------------
    # Section retrieval
    # ------------------------------------------------------------

    def _code_id_for(self, citation: str) -> str | None:
        """Look up the codeId for a full ``T-C-S`` citation from the TOC.

        Returns ``None`` if the citation is not present in the TOC (the
        section does not resolve).
        """
        toc = self._load_toc()
        for section in toc.sections:
            if section.citation == citation:
                return section.code_id
        return None

    def _parse_retrieved(
        self, row: dict, code_id: str, ref: SectionRef
    ) -> ParsedDocument:
        """Parse one GraphQL section record into a :class:`ParsedDocument`,
        cross-checking the returned record against the requested ref.

        Raises:
            RefMismatchError: If the returned record's codeId or embedded
                citation disagrees with the requested ref (a wrong-but-valid
                codeId can return a different section).
            NormalizationError: If the record is missing required fields.
        """
        returned_code_id = row.get("codeId")
        title_field = row.get("title")
        content = row.get("content")
        if returned_code_id is None or not isinstance(title_field, str):
            raise NormalizationError(
                "The Alabama Code API returned a section record missing "
                "required fields (codeId/title); the API's structure may "
                "have changed."
            )
        if str(returned_code_id) != code_id:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} but the Alabama Code "
                f"API returned a record for codeId {returned_code_id!r}; "
                f"expected {code_id!r}."
            )

        returned_citation, catchline = self._split_section_heading(title_field)
        if returned_citation is None:
            raise NormalizationError(
                f"The Alabama Code API returned a section record whose title "
                f"{title_field!r} did not match the expected "
                "'Section T-C-S [catchline].' shape."
            )
        if returned_citation != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the Alabama Code API response: "
                f"{returned_citation!r}."
            )

        content_text = strip_tags(content or "", preserve_block_breaks=True)
        repeal = self._REPEAL_NOTE.match(content_text)

        if repeal is not None:
            # Documented deviation (same decision as Nebraska / North
            # Carolina): a repealed section's content is only its repeal
            # note; the repeal note becomes the heading and the body is
            # empty. The catchline from the title field is not shown as
            # the heading because the source itself presents the repeal
            # note as the section's effective caption.
            heading = content_text.strip()
            text = ""
            amendment_notes = None
        else:
            heading = catchline.strip() if catchline else None
            text = content_text
            amendment_notes = None

        return ParsedDocument(
            raw_citation=f"Ala. Code § {ref.identifier}",
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=self.GRAPHQL_URL,
            retrieved_at=datetime.now(timezone.utc),
        )

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Alabama Code section, end to end:
        look up the section's codeId from the official TOC -> POST the
        retrieval query to the GraphQL endpoint -> parse the returned
        record -> :meth:`normalize` -> :class:`StatuteSection`.

        Args:
            ref: The section to retrieve. Must be an Alabama ref
                (``ref.state_code == "AL"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the TOC or the section record cannot
                be fetched (network failure, non-2xx, or non-JSON response).
            RefNotFoundError: If the citation is absent from the TOC, or the
                retrieval query returns an empty ``data`` list (the codeId
                does not resolve).
            RefMismatchError: If the returned record's codeId or citation
                disagrees with ``ref``.
            NormalizationError: If a fetched record is missing required
                fields or is not in the expected shape.
        """
        code_id = self._code_id_for(ref.identifier)
        if code_id is None:
            raise RefNotFoundError(
                f"Fetched the Alabama Code table of contents but it lists "
                f"no section {ref.identifier!r}; the section does not "
                "resolve on the Alabama Legislature site."
            )

        query = (
            "{ codesOfAlabama(where: { codeId: { eq: "
            f"{int(code_id)}"
            " } }) { data { id codeId title content } } }"
        )
        response = self._post_graphql(
            query, what="Alabama Code section"
        )

        data = self._section_data(response, ref.identifier)
        if not data:
            raise RefNotFoundError(
                f"The Alabama Code API returned no record for section "
                f"{ref.identifier!r} (codeId {code_id!r}); the section "
                "does not resolve."
            )
        if len(data) > 1:
            raise NormalizationError(
                f"The Alabama Code API returned {len(data)} records for "
                f"section {ref.identifier!r}; expected exactly one."
            )

        parsed = self._parse_retrieved(data[0], code_id, ref)
        return self.normalize(parsed, ref)

    @staticmethod
    def _section_data(response: dict, citation: str) -> list:
        """Extract the section record list from a ``codesOfAlabama``
        response, or raise if the response shape is unexpected."""
        data = response.get("data")
        if not isinstance(data, dict):
            raise NormalizationError(
                "The Alabama Code API response was missing its 'data' "
                "object; the API's structure may have changed."
            )
        codes = data.get("codesOfAlabama")
        if not isinstance(codes, dict):
            raise NormalizationError(
                "The Alabama Code API response was missing its "
                "'codesOfAlabama' object; the API's structure may have "
                "changed."
            )
        records = codes.get("data")
        if not isinstance(records, list):
            raise NormalizationError(
                "The Alabama Code API response did not contain the expected "
                "'codesOfAlabama.data' list; the API's structure may have "
                "changed."
            )
        return records

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Alabama.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full ``T-C-S``
        citation) must appear verbatim within ``parsed.raw_citation``. The
        stronger citation cross-check against the source response happens in
        :meth:`retrieve_section`.

        ``status`` is always left at its default (``UNKNOWN``): the Alabama
        Code API signals repealed sections only as prose in the ``content``
        (the repeal note), with no structural status field -- per the
        framework rule, a prose-only signal is not a structural marker, so
        the status is not inferred from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not an Alabama ref
                (``ref.state_code != "AL"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"AlabamaAdapter.normalize cannot normalize a ref for state "
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