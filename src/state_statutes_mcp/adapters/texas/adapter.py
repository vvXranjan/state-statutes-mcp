"""TexasAdapter: the Texas-specific concrete state adapter.

Scope of this milestone: identity (``state_code``, ``state_name``) and
all five abstract methods declared by ``BaseStateAdapter`` --
``build_url``, ``list_titles``, ``list_chapters``, ``list_sections``,
``normalize`` -- are implemented here against the official Texas
Constitution and Statutes website, statutes.capitol.texas.gov (Texas
Legislative Council). ``TexasAdapter`` is therefore fully instantiable.

On top of the abstract contract, this adapter also defines
``retrieve_section``, an adapter-owned convenience method mirroring
``WashingtonAdapter.retrieve_section`` (chains build_url -> fetch ->
parse -> normalize for one SectionRef). Not part of the abstract
contract, for the same reason given in WashingtonAdapter's module
docstring.

Texas's structure, relative to the framework's three-level
TitleRef -> ChapterRef -> SectionRef hierarchy
(state_statutes_mcp.models.refs):

* ``TitleRef`` maps to a Texas "code" (a two-letter identifier such as
  "PE" for the Penal Code, "CR" for the Code of Criminal Procedure).
  Confirmed against the site's own code index,
  https://statutes.capitol.texas.gov/StatuteCodes.aspx, which lists
  every code name alongside its two-letter identifier.
* ``ChapterRef`` maps to a Texas chapter within a code. Confirmed URL
  scheme, documented on the site's own
  https://statutes.capitol.texas.gov/LinksFAQ.aspx and independently
  verified against real fetched chapter pages (Penal Code chapters 1,
  2, 12, 19, 20, 20A, 25, 33; Estates Code chapter 21; Code of Criminal
  Procedure chapter 101; Government Code chapter 551):
  ``https://statutes.capitol.texas.gov/docs/{CODE}/htm/{CODE}.{CHAPTER}.htm``
* ``SectionRef`` maps to a Texas section within a chapter. Texas gives
  sections no URL of their own -- a section is an anchor inside its
  chapter's page. Also documented on LinksFAQ.aspx and confirmed
  against real citations in the wild (e.g. a citation to
  ``PE.19.htm#19.01``). Per the same convention WashingtonAdapter uses
  (see its ``build_url`` docstring), ``SectionRef.identifier`` here is
  already the full local dotted citation Texas itself uses --
  ``"19.01"``, not just a section-local suffix -- since that is what a
  Texas chapter page's own anchors and ``Sec.`` headings use.

One structural difference from Washington worth calling out
explicitly: Texas's internal "Title" grouping (e.g. "TITLE 5. OFFENSES
AGAINST THE PERSON" inside the Penal Code) sits *between* code and
chapter and has no URL of its own -- it is a plain heading on the
chapter page, not a fetchable resource. The framework's three-level
ref hierarchy has no slot for a fourth level, so this milestone does
not attempt to model it; a ``TocNode`` for a chapter carries only that
chapter's own identifier and name, the same as Washington's.

Confirmed vs. unconfirmed, honestly stated:

* Chapter-page structure (headings, body, legislative history) was
  confirmed against multiple independent real fetches -- see
  ``list_sections`` and ``retrieve_section`` docstrings for the exact
  patterns relied on.
* The per-code chapter *listing* page
  (``https://statutes.capitol.texas.gov/?link={CODE}``, documented by
  LinksFAQ.aspx as "a link to the table of contents [for] a code")
  could **not** be confirmed as statically scrapable in this session --
  the site's homepage renders its code/chapter tree via
  client-side-expandable ``chevron_right`` nodes, and it was not
  possible to confirm whether the ``?link=`` page underneath is
  server-rendered HTML or requires that same JS tree. ``list_chapters``
  below fetches it and looks for the same "CHAPTER N. NAME" pattern
  confirmed on chapter pages themselves, but raises
  ``AdapterUnavailableError`` with an explicit explanation if that
  pattern isn't found, rather than silently returning wrong or partial
  data. See ``list_chapters``' docstring.
* The code list itself (``list_titles``) is treated as a small, static,
  hand-verified table rather than a live scrape -- a deliberate
  departure from Washington's live-scrape-everything approach. Unlike
  a chapter's contents, Texas's set of ~30 codes changes on the order
  of once per legislative session at most, and the exact markup of
  ``StatuteCodes.aspx`` was not confirmed in this session (only its
  rendered code/name pairs were, via search results). Hardcoding the
  confirmed pairs avoids writing a regex against markup that was never
  actually seen -- consistent with this milestone's instruction not to
  invent HTML structure.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection


class TexasAdapter(BaseStateAdapter):
    """Concrete state adapter for the Texas Constitution and Statutes
    website (statutes.capitol.texas.gov).

    Identity and all five of ``BaseStateAdapter``'s abstract methods
    are implemented. This adapter also defines ``retrieve_section``,
    an adapter-owned convenience method (not part of the abstract
    contract) that chains those pieces together for end-to-end single
    -section retrieval; see its own docstring for scope, and see the
    module docstring for what is and isn't confirmed against the real
    site.
    """

    BASE_URL = "https://statutes.capitol.texas.gov"
    # Confirmed (2026) real working resource host for individually
    # fetching a chapter page's HTML -- see retrieve_section and
    # build_url docstrings. statutes.capitol.texas.gov's own
    # /docs/{code}/htm/{code}.{chapter}.htm path is superseded by this
    # host for that purpose; BASE_URL is kept only for the TitleRef
    # (code table-of-contents) URL, which has no confirmed TCSS
    # equivalent.
    TCSS_BASE_URL = "https://tcss.legis.texas.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Confirmed verbatim (code name -> two-letter identifier) from the
    # site's own code index, https://statutes.capitol.texas.gov/StatuteCodes.aspx.
    # Deliberately hardcoded rather than live-scraped -- see module
    # docstring for why. The Texas Constitution itself is listed on
    # that page as a "code" (CN) but is not a statute code, so it is
    # excluded here; this adapter is scoped to statutes.
    _CODE_NAMES: dict[str, str] = {
        "AG": "Agriculture Code",
        "AL": "Alcoholic Beverage Code",
        "WL": "Auxiliary Water Laws",
        "BC": "Business and Commerce Code",
        "BO": "Business Organizations Code",
        "CP": "Civil Practice and Remedies Code",
        "CR": "Code of Criminal Procedure",
        "ED": "Education Code",
        "EL": "Election Code",
        "ES": "Estates Code",
        "FA": "Family Code",
        "FI": "Finance Code",
        "GV": "Government Code",
        "HS": "Health and Safety Code",
        "HR": "Human Resources Code",
        "IN": "Insurance Code",
        "I1": "Insurance Code - Not Codified",
        "LA": "Labor Code",
        "LG": "Local Government Code",
        "NR": "Natural Resources Code",
        "OC": "Occupations Code",
        "PW": "Parks and Wildlife Code",
        "PE": "Penal Code",
        "PR": "Property Code",
        "SD": "Special District Local Laws Code",
        "TX": "Tax Code",
        "TN": "Transportation Code",
        "UT": "Utilities Code",
        "WA": "Water Code",
    }
    # Note: Vernon's Civil Statutes (code "CV") is intentionally
    # excluded. LinksFAQ.aspx documents it as using a different
    # addressing scheme (title.chapter.type#article, with chapter
    # numbers that are not unique within it), which this milestone's
    # build_url/list_* methods do not support. Attempting to build a
    # TitleRef for "CV" will therefore behave like any other
    # unrecognized code -- see list_titles.

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Texas."""
        return "TX"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Texas."""
        return "Texas"

    # ------------------------------------------------------------
    # build_url
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official statutes.capitol.texas.gov URL for
        ``ref``.

        * Title (Texas "code"): the code's table-of-contents link,
          ``?link={code}`` -- documented on the site's own
          ``LinksFAQ.aspx`` as "a link to the table of contents [for]
          a code".
        * Chapter: ``https://tcss.legis.texas.gov/resources/{code}/htm/{code}.{chapter}.htm``
          -- this is the current, real, confirmed-working resource
          host as of this milestone (verified by directly fetching
          ``.../resources/PE/htm/PE.19.htm`` and inspecting the
          result). The formerly-used
          ``statutes.capitol.texas.gov/docs/{code}/htm/{code}.{chapter}.htm``
          path is deliberately no longer used here -- it is not
          confirmed to be the current primary retrieval source. Only
          the *host and path prefix* changed; the
          ``{code}/htm/{code}.{chapter}.htm`` naming convention itself
          is identical on both hosts.
        * Section: the parent chapter's URL with a
          ``#{chapter}.{section}`` anchor appended -- also documented
          on that FAQ page and confirmed against real citations in the
          wild. Per ``SectionRef``'s convention as used by this
          adapter, ``ref.identifier`` is already the full local dotted
          citation (e.g. ``"19.01"``), so it is used directly as the
          anchor rather than composed from a separate section-local
          suffix.

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
            chapter_url = self.build_url(ref.chapter)
            return f"{chapter_url}#{ref.identifier}"
        elif isinstance(ref, ChapterRef):
            code = ref.title.identifier
            return f"{self.TCSS_BASE_URL}/resources/{code}/htm/{code}.{ref.identifier}.htm"
        elif isinstance(ref, TitleRef):
            return f"{self.BASE_URL}/?link={ref.identifier}"
        else:
            raise UnsupportedRefError(
                f"TexasAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every Texas statute code from the hardcoded,
        site-verified ``_CODE_NAMES`` table.

        See the module and class docstrings for why this is a static
        table rather than a live scrape.

        Returns:
            A sequence of :class:`TocNode`, one per code, in the order
            defined by ``_CODE_NAMES``. Each node's ``ref`` is a
            :class:`TitleRef` whose ``identifier`` is the code's
            two-letter abbreviation (e.g. ``"PE"``).
        """
        return tuple(
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=code,
                name=name,
                ref=TitleRef(state_code=self.state_code, identifier=code),
            )
            for code, name in self._CODE_NAMES.items()
        )

    # Matches a chapter heading line, e.g. "CHAPTER 19. CRIMINAL
    # HOMICIDE" or "CHAPTER 20A. TRAFFICKING OF PERSONS" -- confirmed
    # verbatim against multiple real fetched chapter pages (see module
    # docstring). Used both to parse the (unconfirmed-format) per-code
    # listing page in list_chapters and, defensively, would also match
    # a chapter's own page if that page is ever fed to it.
    _CHAPTER_HEADING = re.compile(
        r"CHAPTER\s+([0-9]+[A-Z]?)\.\s*([^\n]+?)\s*(?=\n|$)",
        re.IGNORECASE,
    )

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` (a Texas code)
        from that code's table-of-contents page.

        **Confidence note:** unlike :meth:`list_sections` and
        :meth:`retrieve_section`, the exact structure of the
        ``?link={code}`` listing page could not be confirmed as static
        HTML in this session -- see the module docstring. This method
        fetches it and looks for the same "CHAPTER N. NAME" heading
        pattern confirmed on chapter pages themselves. If that pattern
        isn't found, it raises rather than returning wrong or partial
        data.

        Args:
            title_ref: The parent code to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter found, in
            the order they appear on the page.

        Raises:
            AdapterUnavailableError: If the listing page cannot be
                fetched, or if it was fetched but no "CHAPTER N. NAME"
                pattern could be found in it -- which, per the
                confidence note above, may mean either that
                ``title_ref`` doesn't resolve to a real code, or that
                this page genuinely requires JavaScript rendering this
                milestone's plain HTTP fetch cannot perform.
        """
        url = self.build_url(title_ref)
        text = self._fetch_text(url, what="chapter listing")

        chapters = tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=identifier.strip(),
                name=" ".join(name.split()).rstrip("."),
                ref=ChapterRef(title=title_ref, identifier=identifier.strip()),
            )
            for identifier, name in self._CHAPTER_HEADING.findall(text)
        )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no 'CHAPTER N. NAME' headings in "
                f"it; either code {title_ref.identifier!r} does not resolve, "
                "or this listing page requires JavaScript rendering that "
                "this milestone's plain HTTP fetch cannot perform (see "
                "TexasAdapter's module docstring)."
            )

        return chapters

    # Matches one section heading, e.g. "Sec. 19.01. TYPES OF CRIMINAL
    # HOMICIDE." -- confirmed verbatim against multiple real fetched
    # chapter pages (Penal Code chapters 1, 19, 20, 25, 33; Estates
    # Code chapter 21). Defensively tolerant of the "Sec.A19.01.AA"
    # spacing artifact seen in some renderings of the same text (see
    # _normalize_artifact_spacing below) by matching on whitespace
    # generously rather than requiring exactly one space.
    _SECTION_HEADING = re.compile(
        r"Sec\.\s*([0-9]+[A-Z]?\.[0-9]+[A-Za-z]?)\.\s*([A-Z][A-Z0-9 ,\-'\"/&]*?)\.\s",
    )

    # Matches the start of a legislative-history line, e.g. "Acts
    # 1973, 63rd Leg., ..." or "Amended by Acts ..." or "Added by Acts
    # ..." -- confirmed verbatim immediately following body text on
    # every real fetched chapter page checked.
    _HISTORY_START = re.compile(r"(?:Acts\s+\d|Amended by|Added by|Renumbered from)")

    @staticmethod
    def _section_anchor_pattern(chapter_id: str) -> re.Pattern[str]:
        """Build a regex matching ``chapter_id``'s own named section
        anchors in raw (untouched) chapter-page HTML.

        Confirmed structure (``texas_current_pe19.html``): every
        section opens with a paragraph containing exactly two named
        anchors back to back -- the section's own dotted local
        citation (e.g. ``<a name="19.01"></a>``), immediately followed
        by an unrelated internal numeric id anchor (e.g.
        ``<a name="62070.53391"></a>``). Both happen to share the same
        ``digits.digits`` shape, so a bare ``\\d+\\.\\d+`` pattern would
        match either one. Anchoring the pattern to ``chapter_id`` (e.g.
        ``"19"``) as a literal prefix excludes the internal id anchor,
        whose first component is always a much larger, unrelated
        number, while still matching every real section anchor in this
        chapter (``"19.01"``, ``"19.02"``, ..., including lettered
        suffixes like ``"20A.01"`` if this chapter had them).
        """
        return re.compile(
            r'<a\s+name="(' + re.escape(chapter_id) + r'\.[0-9]+[A-Za-z]?)"\s*>\s*</a>'
        )

    @staticmethod
    def _normalize_artifact_spacing(text: str) -> str:
        """Collapse the "Sec.A19.01.AA" tab-leader rendering artifact
        (a run of literal capital ``A`` characters standing in for
        whitespace/tab stops) down to plain single spaces.

        This artifact was observed in some real renderings of Texas
        statute text (PDF-derived extractions of the same sections
        this adapter targets), but it is not confirmed whether a live
        HTML fetch of a chapter page exhibits it. This normalization
        is applied defensively before section-heading matching so
        parsing tolerates it either way; it is a no-op on text that
        doesn't contain the artifact.
        """
        return re.sub(r"(?<=[.\d])A{1,2}(?=[A-Z0-9])", " ", text)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from that
        chapter's official page.

        A chapter's page (same URL :meth:`build_url` produces for a
        :class:`ChapterRef`) is static, server-rendered HTML whose
        body text contains one ``Sec. N.NN. HEADING.`` line per
        section, confirmed against multiple real fetched chapter
        pages -- see the ``_SECTION_HEADING`` pattern's own comment.

        Args:
            chapter_ref: The parent chapter to enumerate sections
                under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in the
            order they appear on the page. Each node's ``ref`` is a
            :class:`SectionRef` whose ``identifier`` is the section's
            full local dotted citation (e.g. ``"19.01"``).

        Raises:
            AdapterUnavailableError: If the chapter's page cannot be
                fetched, or if it was fetched but no section headings
                could be parsed from it -- most likely indicating
                either that ``chapter_ref`` no longer resolves or that
                the site's HTML structure has changed since this
                parser was written.
        """
        url = self.build_url(chapter_ref)
        text = self._normalize_artifact_spacing(self._fetch_text(url, what="section listing"))

        sections = tuple(
            TocNode(
                level=HierarchyLevel.SECTION,
                identifier=identifier.strip(),
                name=" ".join(name.split()).rstrip("."),
                ref=SectionRef(chapter=chapter_ref, identifier=identifier.strip()),
            )
            for identifier, name in self._SECTION_HEADING.findall(text)
        )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no 'Sec. N.NN. NAME.' headings in "
                f"it; either chapter {chapter_ref.identifier!r} under code "
                f"{chapter_ref.title.identifier!r} no longer resolves, this "
                "code uses 'Art.' instead of 'Sec.' (e.g. the Code of "
                "Criminal Procedure -- not supported by this pattern; see "
                "known limitations), or the site's HTML structure has "
                "changed since this parser was written."
            )

        return sections

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Texas.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything, the same way
        ``WashingtonAdapter.normalize`` does: rather than requiring
        exact string equality, this checks that ``ref.identifier``
        (Texas's own dotted section citation, e.g. ``"19.01"``) appears
        verbatim within ``raw_citation``.

        ``status`` is always left at its default (``UNKNOWN``):
        nothing observed on the Texas site in this milestone's other
        methods provides a structural repealed/amended/renumbered
        signal distinct from prose in the legislative-history text,
        and the contract explicitly forbids inferring status from
        prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Texas ref
                (``ref.state_code != "TX"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"TexasAdapter.normalize cannot normalize a ref for state "
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
    # abstract contract -- mirrors WashingtonAdapter.retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Texas statute section, end to
        end: :meth:`build_url` -> fetch the parent chapter's raw page
        HTML -> locate ``ref``'s own named section anchor within it ->
        slice out its raw-HTML block -> parse that block into a
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        Texas gives sections no page of their own (see module
        docstring), so unlike Washington's per-section fetch, this
        fetches the whole parent chapter page once and extracts just
        the block belonging to ``ref``.

        Section boundaries are determined from the page's own named
        HTML anchors, not from any text pattern: every section on a
        real fetched chapter page (``texas_current_pe19.html``) opens
        with ``<a name="{chapter}.{n}"></a>``, immediately followed by
        an unrelated internal-id anchor of the same ``digits.digits``
        shape (see ``_section_anchor_pattern``). ``ref``'s block is
        everything in the *raw* HTML between the end of its own anchor
        tag and the start of the next chapter-scoped section anchor
        (or the end of the ``<pre>`` block, if ``ref`` is the
        chapter's last section) -- determined before any tag-stripping,
        so an ordinary in-body mention of another section (which the
        real page renders as the full word "Section", not "Sec.", and
        never as a named anchor) can never be mistaken for a boundary.

        Only after that raw-HTML slice is isolated is it tag-stripped
        and entity-decoded, and only then is the ``Sec. N.NN. HEADING.``
        line at its start parsed out. Within the remainder, the
        legislative-history text (lines starting ``Acts ...`` /
        ``Amended by ...`` / ``Added by ...`` / ``Renumbered from ...``,
        confirmed immediately following body text on every real chapter
        page checked -- see ``_HISTORY_START``) is split out into
        ``amendment_notes``; everything before it is ``text``.

        Args:
            ref: The section to retrieve. Must be a Texas ref
                (``ref.state_code == "TX"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the chapter page cannot be
                fetched.
            NormalizationError: If ``ref``'s own named section anchor
                cannot be located in the fetched chapter page, or is
                located but no ``Sec. N.NN. HEADING.`` line -- and
                therefore no usable body text -- follows it within its
                bounded block; either ``ref`` doesn't resolve to a real
                section, or the site's HTML structure has changed since
                this parser was written. Also raised by
                :meth:`normalize` if ``ref`` is not a Texas ref.
            RefMismatchError: Raised by :meth:`normalize` if the
                parsed citation does not match ``ref``.
        """
        chapter_url = self.build_url(ref.chapter)
        raw_html = self._fetch_raw_html(chapter_url, what="chapter page")

        anchor_pattern = self._section_anchor_pattern(ref.chapter.identifier)
        matches = list(anchor_pattern.finditer(raw_html))

        target_index = None
        for index, match in enumerate(matches):
            if match.group(1) == ref.identifier:
                target_index = index
                break

        if target_index is None:
            raise NormalizationError(
                f"Fetched {chapter_url!r} but found no "
                f'<a name="{ref.identifier}"> section anchor in it; either '
                "the section no longer resolves or the site's HTML "
                "structure has changed since this parser was written."
            )

        block_start = matches[target_index].end()
        if target_index + 1 < len(matches):
            block_end = matches[target_index + 1].start()
        else:
            pre_close = raw_html.find("</pre>", block_start)
            block_end = pre_close if pre_close != -1 else len(raw_html)

        fragment = raw_html[block_start:block_end]
        block = self._normalize_artifact_spacing(self._clean_fragment(fragment))

        heading_match = self._SECTION_HEADING.search(block)
        if heading_match is None:
            raise NormalizationError(
                f"Fetched {chapter_url!r} and located the "
                f'<a name="{ref.identifier}"> anchor, but found no '
                "'Sec. N.NN. HEADING.' line -- and therefore no usable "
                "body text -- within its bounded block; the site's HTML "
                "structure has likely changed since this parser was "
                "written."
            )

        section_id = heading_match.group(1).strip()
        # group(2) is captured non-greedily up to (but excluding) the
        # closing period the regex itself requires next, so re-attach
        # it here -- both raw_citation and heading are expected to
        # carry the trailing period as it actually appears on the
        # page (e.g. heading == "TYPES OF CRIMINAL HOMICIDE.").
        heading = f"{heading_match.group(2).strip()}."
        raw_citation = f"Sec. {section_id}. {heading}"

        body_block = block[heading_match.end():].strip()

        history_match = self._HISTORY_START.search(body_block)
        if history_match is not None:
            body_text = body_block[: history_match.start()].strip()
            amendment_notes = body_block[history_match.start() :].strip() or None
        else:
            body_text = body_block
            amendment_notes = None

        body_text = self._collapse_paragraphs(body_text)
        amendment_notes = (
            self._collapse_paragraphs(amendment_notes) if amendment_notes else None
        )

        if not body_text:
            raise NormalizationError(
                f"Fetched {chapter_url!r} and found the heading for section "
                f"{ref.identifier!r}, but its body text was empty; the "
                "site's HTML structure has likely changed since this parser "
                "was written."
            )

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=body_text,
            amendment_notes=amendment_notes,
            source_url=self.build_url(ref),
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)

    # ------------------------------------------------------------
    # Shared fetch/clean helpers
    # ------------------------------------------------------------

    _TAG = re.compile(r"<[^>]+>")
    _COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
    # Inserts a newline before common block-level tags so that
    # tag-stripping doesn't run separate lines/cells together into one
    # unbroken string -- needed because, unlike WashingtonAdapter,
    # this adapter parses page *text* rather than matching specific
    # tag/class combinations whose markup was confirmed (see module
    # docstring on what's confirmed vs. not).
    _BLOCK_TAG_OPEN = re.compile(
        r"<(?:p|div|tr|li|br|h[1-6])\b[^>]*>", re.IGNORECASE
    )

    @staticmethod
    def _collapse_paragraphs(text: str) -> str:
        """Join mid-paragraph line wraps with a space while preserving
        blank-line paragraph breaks as ``\\n\\n``.

        ``_fetch_text`` preserves the source's original line breaks
        (needed for line-anchored patterns like chapter headings), but
        within a single statute paragraph those breaks are just where
        the source happened to wrap a line, not real paragraph
        boundaries -- confirmed by the real fetched chapter text this
        adapter's tests are built from, where a sentence like "he
        recklessly causes the death of an individual." is wrapped
        across two source lines. This joins those back into normal
        prose without merging genuinely separate paragraphs.
        """
        paragraphs = re.split(r"\n\s*\n", text)
        return "\n\n".join(" ".join(p.split()) for p in paragraphs if p.strip())

    def _fetch_raw_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its content as decoded, un-cleaned
        HTML -- no tag-stripping, no entity-decoding.

        Split out from the old combined ``_fetch_text`` so
        ``retrieve_section`` can locate named-anchor section
        boundaries in the raw markup (see ``_section_anchor_pattern``)
        before any cleaning happens; ``_fetch_text`` (used by
        ``list_chapters`` / ``list_sections``, which don't need
        anchor-level precision) is now a thin wrapper that fetches via
        this method and immediately cleans the result.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what's being
                fetched, used only to build a clear error message.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be fetched
                (network failure, non-2xx HTTP response).
        """
        try:
            # TODO:
            # Replace urllib with the shared HTTP client once the
            # generic networking layer is introduced (matches the
            # TODO already left in WashingtonAdapter).
            with urllib.request.urlopen(  # noqa: S310
                url,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the Texas {what} at {url!r}: {exc}"
            ) from exc

    def _clean_fragment(self, raw_html: str) -> str:
        """Tag-strip, entity-decode, and whitespace-normalize a chunk
        of raw HTML into plain text, preserving newlines at
        block-level tag boundaries.

        Shared by ``_fetch_text`` (on a whole fetched page) and
        ``retrieve_section`` (on a single anchor-bounded section
        fragment already sliced out of a raw page) so both go through
        identical cleaning logic.
        """
        without_comments = self._COMMENT.sub(" ", raw_html)
        with_newlines = self._BLOCK_TAG_OPEN.sub("\n", without_comments)
        without_tags = self._TAG.sub(" ", with_newlines)
        decoded = html.unescape(without_tags)
        # Collapse runs of horizontal whitespace but keep the newlines
        # inserted above, so line-anchored patterns (chapter headings)
        # and paragraph boundaries survive.
        lines = (" ".join(line.split()) for line in decoded.splitlines())
        return "\n".join(line for line in lines if line)

    def _fetch_text(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its content as tag-stripped,
        entity-decoded, newline-preserving-at-block-boundaries plain
        text.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what's being
                fetched, used only to build a clear error message.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be fetched
                (network failure, non-2xx HTTP response).
        """
        return self._clean_fragment(self._fetch_raw_html(url, what=what))