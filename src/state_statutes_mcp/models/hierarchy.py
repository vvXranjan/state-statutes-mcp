"""Hierarchy models: table-of-contents entries returned by discovery
methods.

``list_titles``, ``list_chapters``, and ``list_sections`` on a state
adapter each enumerate one level of that state's statute structure and
return a flat sequence of :class:`TocNode`. Each node names its level,
carries a human-facing label, and — critically — carries the ref needed
to either build a URL directly (``build_url``) or drill down to the
next level (``list_chapters`` / ``list_sections``), so callers never
have to reconstruct a ref from a node's label.

``children`` exists for callers who want to assemble nodes returned
across several discovery calls into a single tree; the discovery
methods themselves only ever return one flat level at a time and leave
``children`` empty.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef


class HierarchyLevel(str, Enum):
    """Which level of a state's statute structure a :class:`TocNode`
    represents."""

    TITLE = "title"
    CHAPTER = "chapter"
    SECTION = "section"


class TocNode(BaseModel):
    """A single entry in a state's statute table of contents.

    Attributes:
        level: Which level of the hierarchy this node represents.
        identifier: The state's own identifier for this node, exactly
            as that state's source names it (matches ``ref``'s
            ``identifier``).
        name: Human-facing display name of this node.
        ref: The ref this node was discovered at. Its concrete type
            matches ``level``: a :class:`~state_statutes_mcp.models.refs.TitleRef`
            when ``level`` is ``TITLE``, and so on. Use this to call
            ``build_url`` directly, or to drill down via
            ``list_chapters`` / ``list_sections``.
        children: Nested nodes one level below this one, if the caller
            has assembled them. Empty for nodes as returned directly
            from a single ``list_titles`` / ``list_chapters`` /
            ``list_sections`` call, since those only ever enumerate one
            flat level at a time.

    Example:
        >>> TocNode(
        ...     level=HierarchyLevel.TITLE,
        ...     identifier="49",
        ...     name="Labor",
        ...     ref=TitleRef(state_code="WA", identifier="49"),
        ... )
        TocNode(level=<HierarchyLevel.TITLE: 'title'>, identifier='49', name='Labor', ref=TitleRef(state_code='WA', identifier='49', name=None), children=())
    """

    model_config = ConfigDict(frozen=True)

    level: HierarchyLevel
    identifier: str = Field(
        ...,
        min_length=1,
        description="This state's own identifier for the node.",
    )
    name: str = Field(..., min_length=1, description="Human-facing display name.")
    ref: TitleRef | ChapterRef | SectionRef = Field(
        ...,
        description="The ref this node was discovered at; concrete type matches 'level'.",
    )
    children: tuple["TocNode", ...] = Field(
        default_factory=tuple,
        description="Nested nodes one level below this one, if assembled by the caller.",
    )


TocNode.model_rebuild()