"""StatuteSection: the fully normalized, adapter-agnostic representation
of one retrieved statute section.

Every :class:`~state_statutes_mcp.adapters.base.BaseStateAdapter` method
exists to eventually feed ``normalize``, and ``normalize`` exists to
produce one of these. Once a caller has a ``StatuteSection`` in hand,
it no longer matters which state (or which adapter implementation)
produced it — this model is the common shape every state's data is
mapped into.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.refs import SectionRef


class StatuteStatus(str, Enum):
    """The legal status of a statute section, as best determined at
    normalization time.

    ``UNKNOWN`` is the default and expected value for any state whose
    source provides no structural status signal — status inference from
    unstructured text is explicitly out of scope for this milestone
    (see the module docstring on
    :class:`~state_statutes_mcp.adapters.base.BaseStateAdapter`).
    """

    UNKNOWN = "unknown"
    IN_FORCE = "in_force"
    AMENDED = "amended"
    REPEALED = "repealed"
    RENUMBERED = "renumbered"
    EXPIRED = "expired"


class StatuteSection(BaseModel):
    """A single, fully normalized statute section.

    Attributes:
        ref: The section ref this content was retrieved for. Cross-check
            this against the citation embedded in the source (an
            adapter's ``normalize`` is expected to raise
            ``RefMismatchError`` rather than return a ``StatuteSection``
            when the two disagree).
        citation: The citation for this section, as it appears at the
            point of retrieval.
        heading: The section's own heading/caption text, if the source
            provides one distinct from its identifier.
        text: The full body text of the section, as retrieved.
        status: Legal status of this section. Defaults to ``UNKNOWN``;
            only set to a more specific value when the source itself
            supplies a structural signal (e.g. a "Repealed" marker in
            place of body text), not by inferring intent from prose.
        amendment_notes: Raw amendment/history text found alongside the
            section, if any, preserved verbatim rather than parsed —
            structured amendment history is out of scope for this
            milestone.
        source_url: The URL this section's content was retrieved from.
        retrieved_at: When this section was retrieved, if known.

    Example:
        >>> section = StatuteSection(
        ...     ref=SectionRef(
        ...         chapter=ChapterRef(
        ...             title=TitleRef(state_code="WA", identifier="49"),
        ...             identifier="60",
        ...         ),
        ...         identifier="49.60.010",
        ...     ),
        ...     citation=Citation(state_code="WA", raw="RCW 49.60.010"),
        ...     text="It is the policy of the state of Washington...",
        ... )
        >>> section.status
        <StatuteStatus.UNKNOWN: 'unknown'>
    """

    model_config = ConfigDict(frozen=True)

    ref: SectionRef
    citation: Citation
    heading: str | None = Field(
        default=None,
        description="The section's own heading/caption text, if distinct from its identifier.",
    )
    text: str = Field(..., description="Full body text of the section, as retrieved.")
    status: StatuteStatus = Field(
        default=StatuteStatus.UNKNOWN,
        description="Legal status of this section; UNKNOWN unless the source signals otherwise.",
    )
    amendment_notes: str | None = Field(
        default=None,
        description="Raw amendment/history text found alongside the section, verbatim.",
    )
    source_url: str | None = Field(
        default=None,
        description="URL this section's content was retrieved from.",
    )
    retrieved_at: datetime | None = Field(
        default=None,
        description="When this section was retrieved, if known.",
    )