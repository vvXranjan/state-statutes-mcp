"""ParsedDocument: the intermediate, adapter-produced representation of
one retrieved-and-parsed statute section, prior to normalization.

A concrete state adapter's ``normalize`` method (see
:class:`~state_statutes_mcp.adapters.base.BaseStateAdapter`) maps a
``ParsedDocument`` into a fully normalized
:class:`~state_statutes_mcp.models.statute_section.StatuteSection`. In
this milestone, an adapter is responsible for producing its own
``ParsedDocument`` however it sees fit (e.g. inline fetching and
parsing within the adapter itself); this model only fixes the shape of
that intermediate result, not how it's produced.

Every field here exists because either ``StatuteSection`` requires it
downstream, or ``normalize``'s own contract requires it as input (most
notably ``raw_citation``, needed to cross-check against the
``SectionRef`` that was requested and raise ``RefMismatchError`` on a
mismatch). Fields that ``normalize`` is responsible for *deriving*
rather than receiving as raw input — such as ``StatuteSection.status``,
which is only set to a non-default value when the source supplies a
structural signal — are deliberately not duplicated here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ParsedDocument(BaseModel):
    """A single retrieved statute section's content, parsed but not yet
    normalized into a :class:`~state_statutes_mcp.models.statute_section.StatuteSection`.

    Attributes:
        raw_citation: The citation exactly as it appeared on the
            retrieved page (e.g. the citation line at the top of a
            section), unmodified. Used by ``normalize`` both to
            populate ``Citation.raw`` and to cross-check against the
            ``SectionRef`` that was originally requested, raising
            ``RefMismatchError`` if the two disagree.
        heading: The section's own heading/caption text, if the source
            provides one distinct from its identifier. Passed through
            to ``StatuteSection.heading`` unchanged.
        text: The full body text of the section, as retrieved. Passed
            through to ``StatuteSection.text`` unchanged.
        amendment_notes: Raw amendment/history text found alongside the
            section, if any, preserved verbatim rather than parsed.
            Passed through to ``StatuteSection.amendment_notes``
            unchanged.
        source_url: The URL this document's content was retrieved from.
            Passed through to ``StatuteSection.source_url`` unchanged.
        retrieved_at: When this document was retrieved, if known.
            Passed through to ``StatuteSection.retrieved_at`` unchanged.

    Example:
        >>> ParsedDocument(
        ...     raw_citation="RCW 49.60.010",
        ...     text="It is the policy of the state of Washington...",
        ... )
        ParsedDocument(raw_citation='RCW 49.60.010', heading=None, text='It is the policy of the state of Washington...', amendment_notes=None, source_url=None, retrieved_at=None)
    """

    model_config = ConfigDict(frozen=True)

    raw_citation: str = Field(
        ...,
        min_length=1,
        description="The citation exactly as it appeared on the retrieved page.",
    )
    heading: str | None = Field(
        default=None,
        description="The section's own heading/caption text, if distinct from its identifier.",
    )
    text: str = Field(..., description="Full body text of the section, as retrieved.")
    amendment_notes: str | None = Field(
        default=None,
        description="Raw amendment/history text found alongside the section, verbatim.",
    )
    source_url: str | None = Field(
        default=None,
        description="URL this document's content was retrieved from.",
    )
    retrieved_at: datetime | None = Field(
        default=None,
        description="When this document was retrieved, if known.",
    )