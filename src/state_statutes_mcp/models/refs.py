"""Reference models: the addressable identifiers for a state's statute
hierarchy.

A ``*Ref`` is a lightweight, immutable locator — not the content itself.
It carries just enough information for a concrete state adapter to build
a URL, request a listing, or cache a result. Content (headings, body
text, status) lives on downstream models such as
:class:`~state_statutes_mcp.models.statute_section.StatuteSection`, not
here.

The three levels nest: a :class:`ChapterRef` is only meaningful relative
to the :class:`TitleRef` it falls under, and a :class:`SectionRef` only
relative to the :class:`ChapterRef` it falls under. Each level exposes
``state_code`` as a computed property derived from the root
:class:`TitleRef`, so callers never have to keep a separately-supplied
state code in sync with the nested chain.

All three models are frozen (immutable) so they are safe to use as dict
keys or in sets — useful for the caching and deduplication a later
milestone will add, and cheap to guarantee correctness for now since
these models hold no mutable state.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class TitleRef(BaseModel):
    """Reference to a single top-level title (or equivalent top-level
    code/division) within one state's statutes.

    This is the root of the reference hierarchy: every
    :class:`ChapterRef` and :class:`SectionRef` ultimately traces back to
    a ``TitleRef`` for its ``state_code``.

    Attributes:
        state_code: Two-letter USPS state code, e.g. ``"TX"``. Stored
            upper-case for consistent comparison and cache-key use.
        identifier: The state's own identifier for this title, exactly
            as that state's source names it (e.g. ``"49"`` for a
            numbered title, or ``"Health and Safety"`` for a
            name-only division). No cross-state normalization is
            applied — identifiers are only unique within a state.
        name: Human-facing display name of the title, if known at the
            point this ref was constructed. Optional because some
            discovery paths (e.g. building a ref directly from a
            citation string) may not have a display name on hand.

    Example:
        >>> TitleRef(state_code="tx", identifier="49")
        TitleRef(state_code='TX', identifier='49', name=None)
    """

    model_config = ConfigDict(frozen=True)

    state_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Two-letter USPS state code, e.g. 'TX'.",
    )
    identifier: str = Field(
        ...,
        min_length=1,
        description="This state's own identifier for the title.",
    )
    name: str | None = Field(
        default=None,
        description="Human-facing display name of the title, if known.",
    )

    @field_validator("state_code", mode="after")
    @classmethod
    def _uppercase_state_code(cls, value: str) -> str:
        """Normalize to upper-case so callers may pass either case."""
        return value.upper()


class ChapterRef(BaseModel):
    """Reference to a single chapter (or equivalent mid-level grouping)
    nested under a :class:`TitleRef`.

    Attributes:
        title: The parent title this chapter falls under.
        identifier: The state's own identifier for this chapter,
            exactly as that state's source names it. Only unique within
            ``title``, not globally.
        name: Human-facing display name of the chapter, if known.

    Example:
        >>> ref = ChapterRef(
        ...     title=TitleRef(state_code="TX", identifier="49"),
        ...     identifier="1",
        ... )
        >>> ref.state_code
        'TX'
    """

    model_config = ConfigDict(frozen=True)

    title: TitleRef
    identifier: str = Field(
        ...,
        min_length=1,
        description="This state's own identifier for the chapter.",
    )
    name: str | None = Field(
        default=None,
        description="Human-facing display name of the chapter, if known.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state_code(self) -> str:
        """Two-letter USPS state code, inherited from ``title``."""
        return self.title.state_code


class SectionRef(BaseModel):
    """Reference to a single, individually retrievable section nested
    under a :class:`ChapterRef`.

    This is the finest-grained ref in the hierarchy and the one most
    downstream methods (``build_url`` for retrieval, ``normalize`` for
    cross-checking) key off of.

    Attributes:
        chapter: The parent chapter this section falls under.
        identifier: The state's own identifier for this section, exactly
            as that state's source names it (e.g. ``"49.60.010"`` for a
            dotted-code state). Only unique within ``chapter``, not
            globally.
        name: Human-facing display name of the section, if known.

    Example:
        >>> ref = SectionRef(
        ...     chapter=ChapterRef(
        ...         title=TitleRef(state_code="WA", identifier="49"),
        ...         identifier="60",
        ...     ),
        ...     identifier="49.60.010",
        ... )
        >>> ref.state_code
        'WA'
    """

    model_config = ConfigDict(frozen=True)

    chapter: ChapterRef
    identifier: str = Field(
        ...,
        min_length=1,
        description="This state's own identifier for the section.",
    )
    name: str | None = Field(
        default=None,
        description="Human-facing display name of the section, if known.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state_code(self) -> str:
        """Two-letter USPS state code, inherited from ``chapter.title``."""
        return self.chapter.state_code