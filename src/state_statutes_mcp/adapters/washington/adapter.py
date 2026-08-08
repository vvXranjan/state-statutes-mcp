"""WashingtonAdapter: the Washington-specific concrete state adapter.

Scope of this milestone: the identity properties (``state_code``,
``state_name``) and four of the five abstract discovery/retrieval
methods declared by ``BaseStateAdapter`` — ``build_url``,
``list_titles``, ``list_chapters``, and ``list_sections`` — are
implemented here against the Revised Code of Washington (RCW) at
``app.leg.wa.gov/RCW``. Only ``normalize`` remains unimplemented, so
``WashingtonAdapter`` remains abstract and cannot yet be instantiated —
that's expected, and will be resolved in a later milestone.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Sequence

from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import AdapterUnavailableError, UnsupportedRefError
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef


class WashingtonAdapter(BaseStateAdapter):
    """Concrete state adapter for Washington's Revised Code of
    Washington (RCW).

    Identity, ``build_url``, ``list_titles``, ``list_chapters``, and
    ``list_sections`` are implemented at this milestone; see the
    module docstring for what's deliberately still missing.
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
