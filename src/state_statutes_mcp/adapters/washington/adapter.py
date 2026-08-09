"""WashingtonAdapter: the Washington-specific concrete state adapter.

Scope of this milestone: the identity properties (``state_code``,
``state_name``) and all five abstract discovery/retrieval methods
declared by ``BaseStateAdapter`` — ``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, and ``normalize`` — are
implemented here against the Revised Code of Washington (RCW) at
``app.leg.wa.gov/RCW``. ``WashingtonAdapter`` is therefore fully
instantiable.

On top of the abstract contract, this adapter also defines
``retrieve_section``: an adapter-owned convenience method that chains
``build_url`` → an inline fetch → inline parsing into a
``ParsedDocument`` → ``normalize`` for a single ``SectionRef``. This is
not part of ``BaseStateAdapter``'s contract (see ``retrieve_section``'s
own docstring for why), so it doesn't change what any other adapter is
required to implement.
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


class WashingtonAdapter(BaseStateAdapter):
    """Concrete state adapter for Washington's Revised Code of
    Washington (RCW).

    Identity and all five of ``BaseStateAdapter``'s abstract methods
    (``build_url``, ``list_titles``, ``list_chapters``,
    ``list_sections``, ``normalize``) are implemented. This adapter
    also defines ``retrieve_section``, an adapter-owned convenience
    method (not part of the abstract contract) that chains those
    pieces together for end-to-end single-section retrieval; see its
    own docstring for scope.
    """

    BASE_URL = "https://app.leg.wa.gov/RCW/default.aspx"
    DEFAULT_TIMEOUT_SECONDS = 30

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Washington."""
        return "WA"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Washington."""
        return "Washington"

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official RCW URL for ``ref``.

        The RCW site (``app.leg.wa.gov/RCW``) addresses every level of
        the hierarchy — title, chapter, and section — through a single
        endpoint, ``default.aspx``, parameterized by a ``cite`` query
        argument built from the dotted RCW citation:

        * Title: ``?cite={title}``, e.g. ``?cite=49``.
        * Chapter: ``?cite={title}.{chapter}``, e.g. ``?cite=49.60``.
        * Section: ``?cite={title}.{chapter}.{section}``, e.g.
          ``?cite=49.60.010``. Per :class:`SectionRef`'s own contract,
          ``SectionRef.identifier`` is already this full dotted RCW
          citation (not just a section-local suffix), so it is used
          directly as the ``cite`` value rather than being composed
          from its parent chapter and title.

        Unlike some states, Washington has no unaddressable level:
        title, chapter, and section pages all exist as real, directly
        fetchable resources on the official site, so this method never
        raises for a legitimate ``TitleRef``/``ChapterRef``/
        ``SectionRef``. It only raises for a ref of some other,
        unsupported type.

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
            cite = ref.identifier
        elif isinstance(ref, ChapterRef):
            cite = f"{ref.title.identifier}.{ref.identifier}"
        elif isinstance(ref, TitleRef):
            cite = ref.identifier
        else:
            raise UnsupportedRefError(
                f"WashingtonAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )
        return f"{self.BASE_URL}?cite={cite}"

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every RCW title from the official "RCWs by Title"
        index page.

        The RCW site's root listing page (``default.aspx``, with no
        ``cite`` query argument) is a static, server-rendered HTML page
        containing an "RCWs by Title" table: one row per title, each
        row holding a link to that title (``default.aspx?Cite={N}``)
        and the title's display name (e.g. "LABOR REGULATIONS"). This
        method fetches that page with a single plain HTTP GET and
        parses just that table — no browser automation and no separate
        HTTP client or parser class are needed, since Washington serves
        this listing as plain HTML with no client-side rendering step.

        Returns:
            A sequence of :class:`TocNode`, one per title, in the order
            they appear on the page. Each node's ``ref`` is a
            :class:`TitleRef` whose ``identifier`` is the title number
            exactly as Washington writes it (e.g. ``"9A"`` for Title 9A,
            not just numeric titles).

        Raises:
            AdapterUnavailableError: If the listing page cannot be
                fetched (network failure, non-2xx HTTP response), or if
                it was fetched but no title rows could be parsed from
                it — the latter most likely indicating the site's HTML
                structure has changed since this parser was written.
        """
        try:
            # TODO:
            # Replace urllib with the shared HTTP client once the
            # generic networking layer is introduced.
            with urllib.request.urlopen(  # noqa: S310
                self.BASE_URL,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the RCW title listing at {self.BASE_URL!r}: {exc}"
            ) from exc

        # Matches one "RCWs by Title" row at a time: a link to
        # default.aspx?Cite={identifier} (case-insensitive "Cite", to
        # tolerate either casing the site emits) whose link text starts
        # with "Title", followed by that title's plain-text display
        # name in the next table cell.

        # TODO:
        # Replace regex parsing with an HTML parser (BeautifulSoup/lxml)
        # once the generic parsing layer is introduced.
        row_pattern = re.compile(
            r'href="default\.aspx\?Cite=([^"]+)"[^>]*>\s*Title\s+[^<]*</a>'
            r'\s*(?:</t[dh]>\s*<t[dh][^>]*>)\s*([^<]+?)\s*</t[dh]>',
            re.IGNORECASE,
        )

        titles = tuple(
            TocNode(
                level=HierarchyLevel.TITLE,
                identifier=identifier.strip(),
                name=" ".join(name.split()),
                ref=TitleRef(state_code=self.state_code, identifier=identifier.strip()),
            )
            for identifier, name in row_pattern.findall(html)
        )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {self.BASE_URL!r} but found no title rows in it; "
                "the site's HTML structure may have changed."
            )

        return titles

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` from that title's
        official RCW page.

        A title's page (``default.aspx?cite={title}``, i.e. the same
        URL :meth:`build_url` produces for a :class:`TitleRef`) is a
        static, server-rendered HTML page containing a "Chapters" table:
        one row per chapter, each row holding a link to that chapter
        (``default.aspx?cite={title}.{chapter}``) and the chapter's
        display name (e.g. "Apprenticeship."). This method fetches that
        page with a single plain HTTP GET and parses just that table —
        same style as :meth:`list_titles`, no browser automation and no
        separate HTTP client or parser class.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in the
            order they appear on the page. Each node's ``ref`` is a
            :class:`ChapterRef` whose ``identifier`` is the chapter's
            own local number (the part after the title and dot, e.g.
            ``"60"`` for chapter 49.60) and whose ``title`` is
            ``title_ref``, matching :meth:`build_url`'s expectation
            that a :class:`ChapterRef`'s citation is composed from
            ``title.identifier`` and ``identifier``.

        Raises:
            AdapterUnavailableError: If the title's page cannot be
                fetched (network failure, non-2xx HTTP response), or if
                it was fetched but no chapter rows could be parsed from
                it — the latter most likely indicating either that
                ``title_ref`` no longer resolves to a real title page or
                that the site's HTML structure has changed since this
                parser was written.
        """
        url = self.build_url(title_ref)
        try:
            with urllib.request.urlopen(  # noqa: S310
                url,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the RCW chapter listing at {url!r}: {exc}"
            ) from exc

        # Matches one "Chapters" row at a time: a link to
        # default.aspx?cite={title}.{chapter} (case-insensitive "cite",
        # to tolerate either casing the site emits) scoped to this
        # specific title's identifier, capturing only the chapter-local
        # suffix after "{title}.", followed by that chapter's
        # plain-text display name in the next table cell.
        row_pattern = re.compile(
            r'href="default\.aspx\?cite=' + re.escape(title_ref.identifier) + r'\.([^"]+)"'
            r'[^>]*>[^<]*</a>'
            r'\s*(?:</t[dh]>\s*<t[dh][^>]*>)\s*([^<]+?)\s*</t[dh]>',
            re.IGNORECASE,
        )

        chapters = tuple(
            TocNode(
                level=HierarchyLevel.CHAPTER,
                identifier=identifier.strip(),
                name=" ".join(name.split()),
                ref=ChapterRef(title=title_ref, identifier=identifier.strip()),
            )
            for identifier, name in row_pattern.findall(html)
        )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no chapter rows in it; either "
                f"title {title_ref.identifier!r} no longer resolves or the "
                "site's HTML structure has changed."
            )

        return chapters

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from that
        chapter's official RCW page.

        A chapter's page (``default.aspx?cite={title}.{chapter}``, i.e.
        the same URL :meth:`build_url` produces for a
        :class:`ChapterRef`) is a static, server-rendered HTML page
        containing a "Sections" table: one row per section, each row
        holding an HTML-format link, a PDF-format link, a link to the
        section itself (whose link text is the section's full dotted
        RCW citation, e.g. ``49.60.2235``) and the section's plain-text
        catchline. This method fetches that page with a single plain
        HTTP GET and parses just that table — same style as
        :meth:`list_titles` and :meth:`list_chapters`, no browser
        automation and no separate HTTP client or parser class.

        The same page can also mention sections from other chapters or
        titles in a trailing "Notes" area (cross-references such as
        "Appropriation of water ... Chapter 90.16 RCW"). Those
        cross-references never carry a link whose citation is prefixed
        with this chapter's own ``title.chapter.`` identifier, so
        scoping the match to that prefix excludes them without needing
        to special-case a "Notes" section of the page.

        Some chapters also interleave bare group-heading rows (e.g.
        "PLAT/APPRAISAL/REPLAT") between clusters of sections, purely
        to aid human navigation. These headings carry no link to a
        section page, so they are naturally excluded by requiring a
        matching section citation link; they never produce a
        :class:`TocNode`.

        Args:
            chapter_ref: The parent chapter to enumerate sections
                under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in the
            order they first appear on the page. Each node's ``ref``
            is a :class:`SectionRef` whose ``identifier`` is the
            section's full dotted RCW citation (e.g.
            ``"49.60.2235"``), matching :class:`SectionRef`'s own
            documented contract that its ``identifier`` is already the
            complete citation rather than a section-local suffix. If a
            citation is linked more than once on the page (e.g. the
            HTML-format link and the citation link both resolving to
            the same section), only its first occurrence is kept.

        Raises:
            AdapterUnavailableError: If the chapter's page cannot be
                fetched (network failure, non-2xx HTTP response), or if
                it was fetched but no section rows could be parsed from
                it — the latter most likely indicating either that
                ``chapter_ref`` no longer resolves to a real chapter
                page or that the site's HTML structure has changed
                since this parser was written.
        """
        url = self.build_url(chapter_ref)
        try:
            with urllib.request.urlopen(  # noqa: S310
                url,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the RCW section listing at {url!r}: {exc}"
            ) from exc

        # Matches one "Sections" row at a time: a link to
        # default.aspx?cite={title}.{chapter}.{section} (case-insensitive
        # "cite", scoped to this specific chapter's title.chapter prefix,
        # which is also what keeps this from picking up cross-chapter
        # citations mentioned in the page's trailing Notes area) whose
        # link text is that same full dotted citation, followed by that
        # section's plain-text catchline in the next table cell.
        # Anchoring on link text that echoes the citation (via a
        # backreference to the captured suffix) rather than on any link
        # in the row is what distinguishes the section's own citation
        # link from the row's separate "HTML"/"PDF" format links, which
        # point at the same URL but carry different link text.
        prefix = re.escape(f"{chapter_ref.title.identifier}.{chapter_ref.identifier}.")
        row_pattern = re.compile(
            r'href="default\.aspx\?cite=' + prefix + r'([^"]+)"'
            r'[^>]*>\s*' + prefix + r'\1\s*</a>'
            r'\s*(?:</t[dh]>\s*<t[dh][^>]*>)\s*([^<]+?)\s*</t[dh]>',
            re.IGNORECASE,
        )

        seen_identifiers: set[str] = set()
        sections = []
        for suffix, name in row_pattern.findall(html):
            identifier = f"{chapter_ref.title.identifier}.{chapter_ref.identifier}.{suffix.strip()}"
            if identifier in seen_identifiers:
                continue
            seen_identifiers.add(identifier)
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=" ".join(name.split()),
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )
        sections = tuple(sections)

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no section rows in it; either "
                f"chapter {chapter_ref.identifier!r} under title "
                f"{chapter_ref.title.identifier!r} no longer resolves or the "
                "site's HTML structure has changed."
            )

        return sections

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Washington.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: Washington's canonical dotted citation
        is ``ref.identifier`` (e.g. ``"49.60.010"``, per
        :meth:`build_url`'s own documented convention), while
        ``parsed.raw_citation`` is "the citation exactly as it appeared
        on the retrieved page" and so may carry a ``"RCW "`` prefix or
        similar surrounding text. Rather than requiring exact string
        equality (which would reject a well-formed
        ``"RCW 49.60.010"``), this checks that the dotted citation
        appears verbatim within ``raw_citation`` — the same
        verbatim-substring relationship :meth:`list_sections` already
        relies on between a section's dotted citation and the RCW
        site's own link text.

        ``status`` is always left at its default (``UNKNOWN``): neither
        ``ParsedDocument`` nor anything observed on the RCW site in
        this milestone's other methods defines a structural
        repealed/amended/renumbered signal, and the contract explicitly
        forbids inferring status from prose.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested,
                for cross-checking against what was actually returned.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Washington ref
                (``ref.state_code != "WA"``), since this adapter can
                only normalize documents against its own state.
            RefMismatchError: If ``ref.identifier`` (the requested
                dotted RCW citation) does not appear in
                ``parsed.raw_citation``, indicating ``parsed`` is not
                the section that was requested.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"WashingtonAdapter.normalize cannot normalize a ref for "
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
    # abstract contract - see method docstring below)
    # ------------------------------------------------------------

    # Every pattern below is anchored to structure confirmed against
    # the real, live-fetched HTML of a representative section page
    # (default.aspx?cite=49.60.010) -- not inferred from any rendered
    # or Markdown-converted view of the page. See retrieve_section's
    # docstring for the confirmed snippets each pattern corresponds
    # to.

    # The citation lives in a bare <h1> (no attributes observed).
    _CITATION_H1 = re.compile(r"<h1>(.*?)</h1>", re.IGNORECASE | re.DOTALL)

    # The catchline lives in a bare <h2> (no attributes observed).
    # Matching only a bare <h2> -- not <h2 ...> -- is what excludes the
    # page's footer heading, which does carry an attribute
    # (class="text-warning"); see _FOOTER_H2 below.
    _CATCHLINE_H2 = re.compile(r"<h2>(.*?)</h2>", re.IGNORECASE | re.DOTALL)

    # The site-wide footer heading, confirmed to always carry
    # class="text-warning" -- this both bounds how far parsing reads
    # and, by requiring the attribute, cannot collide with the bare
    # catchline <h2> above.
    _FOOTER_H2 = re.compile(
        r'<h2[^>]*\bclass\s*=\s*["\']text-warning["\'][^>]*>',
        re.IGNORECASE,
    )

    # Each statute-body paragraph is its own
    # <div style="text-indent:0.5in;">...</div>. Confirmed not to be a
    # <p> tag, which is exactly what an earlier version assumed
    # incorrectly.
    _BODY_PARAGRAPH_DIV = re.compile(
        r'<div\s+style="text-indent:\s*0\.5in;?"\s*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )

    # The bracketed legislative-history line sits in its own
    # <div style="margin-top:15pt;margin-bottom:0pt;">...</div>,
    # immediately after the body paragraphs.
    _HISTORY_DIV = re.compile(
        r'<div\s+style="margin-top:\s*15pt;\s*margin-bottom:\s*0pt;?"\s*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )

    # The Notes heading is a plain <h3>Notes:</h3>, distinct from both
    # the citation <h1> and the catchline <h2>.
    _NOTES_H3 = re.compile(r"<h3>\s*Notes:\s*</h3>", re.IGNORECASE)

    # Notes content style wasn't confirmed precisely ("several divs"),
    # so this deliberately matches *any* <div>, unlike the two
    # style-specific patterns above -- used only within the
    # already-bounded region between the Notes heading and the footer.
    _GENERIC_DIV = re.compile(r"<div[^>]*>(.*?)</div>", re.IGNORECASE | re.DOTALL)

    _COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
    _TAG = re.compile(r"<[^>]+>")

    @classmethod
    def _clean(cls, fragment: str) -> str:
        """Strip HTML comments and tags from ``fragment``, decode HTML
        entities, and collapse whitespace to single spaces.

        The confirmed citation/catchline markup wraps its text in CMS
        field-boundary comments (e.g. ``<!-- field: Citations -->``),
        so comment removal has to happen before tag-stripping and
        whitespace-collapsing, or those comments would otherwise
        survive as literal text.
        """
        text = cls._COMMENT.sub(" ", fragment)
        text = cls._TAG.sub(" ", text)
        text = html.unescape(text)
        return " ".join(text.split())

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Washington RCW section, end to
        end: :meth:`build_url` -> fetch -> parse into
        :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        This method is deliberately **not** part of
        ``BaseStateAdapter``'s abstract contract, for the same reason
        given in the module docstring: a shared version would need an
        injected fetcher/parser this milestone doesn't have. What's
        here is Washington-specific glue chaining already-implemented
        pieces together, doing its own inline fetch and regex-based
        parse exactly the way :meth:`list_titles`, :meth:`list_chapters`,
        and :meth:`list_sections` already do.

        **Page structure this parsing relies on**, confirmed directly
        against the live page's raw HTML for a representative section
        (``default.aspx?cite=49.60.010``), including a byte-for-byte
        saved copy of the fetched page -- not inferred from any
        rendered or Markdown-converted view:

        * Citation: a bare ``<h1>`` whose text (once CMS field-boundary
          comments are stripped) is the citation, e.g.
          ``<h1><!-- field: Citations -->RCW  49.60.010<!-- field: -->
          </h1>``.
        * Catchline: a bare ``<h2>`` immediately after, e.g.
          ``<h2><!-- field: CaptionsTitles -->Purpose of chapter.
          <!-- field: --></h2>``.
        * Body: each paragraph is its own
          ``<div style="text-indent:0.5in;">``, nested inside
          ``<div id='contentWrapper' class='section-page'>`` -- not
          ``<p>`` tags.
        * Legislative history: one
          ``<div style="margin-top:15pt;margin-bottom:0pt;">`` holding
          the bracketed session-law citation list, immediately after
          the body paragraphs.
        * Notes: a plain ``<h3>Notes:</h3>`` (itself wrapped in a
          ``<div style="margin-top:0.25in;margin-bottom:0.25in;">``)
          followed by further ``<div>`` elements of free-form notes
          text.
        * Footer/stop boundary: ``<h2 class="text-warning">Legislative
          questions or comments</h2>``, present as site chrome on every
          RCW page.

        The legislative-history block and the Notes content (if
        present) are combined into one ``amendment_notes`` string,
        consistent with :class:`ParsedDocument`'s contract that this
        field is preserved as raw, unparsed text rather than
        structurally interpreted.

        This is regex-based text extraction anchored to exactly the
        confirmed containers above, not a general-purpose HTML parser
        -- consistent with every other method in this class. Verified
        against the real, saved HTML of ``?cite=49.60.010``: correctly
        extracts the citation, catchline, full body text (beginning
        "This chapter shall be known as..."), and the legislative
        history/Notes content. One known limitation: the body/history
        extraction assumes those ``<div>`` elements don't themselves
        contain a *nested* ``<div>`` before their closing tag; if a
        future section's body embedded one (e.g. a table), the
        non-greedy match would stop at that inner ``</div>`` and
        truncate. The confirmed section tested against does not
        exhibit this, but it has not been checked across every RCW
        section.

        Args:
            ref: The section to retrieve. Must be a Washington ref
                (``ref.state_code == "WA"``); enforced by
                :meth:`normalize`, not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section's page cannot be
                fetched (network failure, non-2xx HTTP response).
            NormalizationError: If no citation ``<h1>`` could be found,
                or if no body paragraph ``<div>`` could be found --
                either indicates ``ref`` doesn't resolve to a real
                section page or the site's HTML structure has changed.
                Also raised by :meth:`normalize` if ``ref`` is not a
                Washington ref.
            RefMismatchError: Raised by :meth:`normalize` if the parsed
                citation does not match ``ref``.
        """
        url = self.build_url(ref)
        try:
            with urllib.request.urlopen(  # noqa: S310
                url,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                page_html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterUnavailableError(
                f"Could not reach the RCW section page at {url!r}: {exc}"
            ) from exc

        citation_match = self._CITATION_H1.search(page_html)
        if citation_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but found no <h1> citation heading in it; "
                f"either section {ref.identifier!r} no longer resolves to a "
                "real section page or the site's HTML structure has changed."
            )
        raw_citation = self._clean(citation_match.group(1))

        footer_match = self._FOOTER_H2.search(page_html, citation_match.end())
        content_html = page_html[
            citation_match.end() : footer_match.start() if footer_match else len(page_html)
        ]

        catchline_match = self._CATCHLINE_H2.search(content_html)
        heading = self._clean(catchline_match.group(1)) if catchline_match is not None else None

        body_matches = list(self._BODY_PARAGRAPH_DIV.finditer(content_html))
        if not body_matches:
            raise NormalizationError(
                f"Fetched {url!r} and found citation {raw_citation!r}, but no "
                f"statute body paragraph could be parsed for section "
                f"{ref.identifier!r}; the site's HTML structure has likely "
                "changed since this parser was written."
            )
        text = "\n\n".join(self._clean(match.group(1)) for match in body_matches)
        if not text.strip():
            raise NormalizationError(
                f"Fetched {url!r} and found citation {raw_citation!r}, but the "
                f"statute body for section {ref.identifier!r} was empty after "
                "stripping markup; the site's HTML structure has likely "
                "changed since this parser was written."
            )

        history_match = self._HISTORY_DIV.search(content_html)
        history_text = self._clean(history_match.group(1)) if history_match is not None else None

        notes_match = self._NOTES_H3.search(content_html)
        notes_text = None
        if notes_match is not None:
            notes_region = content_html[notes_match.end() :]
            notes_paragraphs = [
                self._clean(match.group(1)) for match in self._GENERIC_DIV.finditer(notes_region)
            ]
            notes_paragraphs = [p for p in notes_paragraphs if p]
            notes_text = "\n\n".join(notes_paragraphs) if notes_paragraphs else None

        amendment_parts = [part for part in (history_text, notes_text) if part]
        amendment_notes = "\n\n".join(amendment_parts) if amendment_parts else None

        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)