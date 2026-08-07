"""Citation: a bibliographic reference to a point in a state's statutes.

A :class:`Citation` is distinct from a
:class:`~state_statutes_mcp.models.refs.SectionRef`: a ``SectionRef`` is
an *addressable locator* an adapter uses to build a URL or request a
listing, while a ``Citation`` is a *presentation-layer* record of how a
citation actually appeared in source text (e.g. inside another
section's amendment notes, or as the citation line at the top of a
retrieved section) — verbatim string included, whether or not that
string has been successfully parsed into a structured ``SectionRef``.

Keeping the two separate means a citation found in free text (e.g. a
cross-reference such as "see also Ch. 12A") can be recorded even when
it cannot yet be resolved to a concrete ref, without forcing every
``Citation`` to carry a fully-populated ref.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from state_statutes_mcp.models.refs import SectionRef


class Citation(BaseModel):
    """A single citation to a point in one state's statutes.

    Attributes:
        state_code: Two-letter USPS state code the citation belongs to,
            e.g. ``"TX"``. Stored upper-case for consistent comparison.
        raw: The citation exactly as it appeared in source text or on
            the retrieved page, unmodified. This is the only field
            guaranteed to be populated — everything else is derived
            from it on a best-effort basis.
        formatted: A canonical, human-readable rendering of the
            citation (e.g. ``"Wash. Rev. Code § 49.60.010"``), if a
            normalized form has been computed. ``None`` when no
            normalization has been attempted or it could not be
            produced.
        section: The structured :class:`SectionRef` this citation
            resolves to, if the raw text could be parsed into one.
            ``None`` for citations that reference something coarser
            than a section (e.g. a whole chapter) or that could not be
            resolved at all.

    Example:
        >>> Citation(state_code="wa", raw="RCW 49.60.010")
        Citation(state_code='WA', raw='RCW 49.60.010', formatted=None, section=None)
    """

    model_config = ConfigDict(frozen=True)

    state_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Two-letter USPS state code, e.g. 'TX'.",
    )
    raw: str = Field(
        ...,
        min_length=1,
        description="The citation exactly as it appeared in the source.",
    )
    formatted: str | None = Field(
        default=None,
        description="Canonical human-readable rendering of the citation, if computed.",
    )
    section: SectionRef | None = Field(
        default=None,
        description="Structured section ref this citation resolves to, if known.",
    )

    @field_validator("state_code", mode="after")
    @classmethod
    def _uppercase_state_code(cls, value: str) -> str:
        """Normalize to upper-case so callers may pass either case."""
        return value.upper()