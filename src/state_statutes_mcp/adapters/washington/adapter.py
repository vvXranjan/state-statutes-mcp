"""WashingtonAdapter: the Washington-specific concrete state adapter.

Scope of this milestone, deliberately narrow: only the two identity
properties (``state_code``, ``state_name``) are implemented here. The
five abstract discovery/retrieval methods declared by
``BaseStateAdapter`` (``build_url``, ``list_titles``, ``list_chapters``,
``list_sections``, ``normalize``) are intentionally left unimplemented
in this milestone, so ``WashingtonAdapter`` remains abstract and cannot
yet be instantiated — that's expected, and will be resolved as those
methods are implemented in later milestones against the Revised Code of
Washington (RCW) at ``app.leg.wa.gov/RCW``.
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

    Only identity, ``build_url``, and ``list_titles`` are implemented at
    this milestone; see the module docstring for what's deliberately
    still missing.
    """

    BASE_URL = "https://app.leg.wa.gov/RCW/default.aspx"

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
            with urllib.request.urlopen(self.BASE_URL, timeout=30) as response:  # noqa: S310
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