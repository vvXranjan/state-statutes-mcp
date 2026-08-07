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

from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import UnsupportedRefError
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

_BASE_URL = "https://app.leg.wa.gov/RCW/default.aspx"


class WashingtonAdapter(BaseStateAdapter):
    """Concrete state adapter for Washington's Revised Code of
    Washington (RCW).

    Only identity and ``build_url`` are implemented at this milestone;
    see the module docstring for what's deliberately still missing.
    """

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
        return f"{_BASE_URL}?cite={cite}"