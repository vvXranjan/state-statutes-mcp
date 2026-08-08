"""Framework exceptions: the exception hierarchy required by
BaseStateAdapter's existing contract.

Every exception defined here is referenced by name in
:class:`~state_statutes_mcp.adapters.base.BaseStateAdapter`'s abstract
method docstrings, and two of them (``AdapterUnavailableError``,
``UnsupportedRefError``) are already imported and raised by
:class:`~state_statutes_mcp.adapters.washington.adapter.WashingtonAdapter`.
None of these were previously defined anywhere in the project, so this
module exists purely to make the already-documented base contract
resolvable at import time — the same category of gap ``ParsedDocument``
filled for :class:`~state_statutes_mcp.models.documents.ParsedDocument`.

No exception here carries fields beyond a plain message. Nothing in the
contracts that reference these exceptions (``BaseStateAdapter``'s
Raises clauses, and the ``RefMismatchError`` mentions in
``ParsedDocument`` and ``StatuteSection``) requires any exception to
expose structured data (e.g. the mismatched ref, or a partial results
list) as an attribute — only that it be raised under a specific,
documented condition. Adding such fields now would be inventing
contract surface area that doesn't yet exist.

All six inherit directly from a single root, :class:`StateStatutesError`,
so callers can catch broadly across any framework-raised failure without
the contracts implying any finer-grained grouping among them.
"""

from __future__ import annotations


class StateStatutesError(Exception):
    """Root of the framework's exception hierarchy.

    Not itself referenced by name in any existing contract; introduced
    only so callers have a single type to catch across every
    framework-raised failure. Every exception below inherits from this
    and from nothing else, since none of the existing contracts imply
    any finer-grained relationship among them.
    """


class UnsupportedRefError(StateStatutesError):
    """Raised by ``build_url`` when a ref's level is not addressable
    for the state in question.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.build_url`,
    this covers a ref of some type or level the adapter has no URL
    scheme for at all — not a ref that's merely unresolvable (see
    :class:`RefNotFoundError` for that case).
    """


class AdapterUnavailableError(StateStatutesError):
    """Raised when a state's source is unreachable at discovery or
    retrieval time.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.list_titles`,
    this covers network failures and non-2xx responses — the source
    itself could not be reached, as distinct from the source being
    reached but not containing what was asked for
    (see :class:`RefNotFoundError`).
    """


class RefNotFoundError(StateStatutesError):
    """Raised by ``list_chapters`` or ``list_sections`` when the
    supplied parent ref no longer resolves.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.list_chapters`
    and :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.list_sections`,
    this is for a ref that was once valid (or was constructed
    plausibly) but no longer addresses anything real on the source —
    as distinct from the source being unreachable at all
    (see :class:`AdapterUnavailableError`).
    """


class PartialListingError(StateStatutesError):
    """Raised by ``list_sections`` when some, but not all, sections
    were successfully enumerated before a failure occurred.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.list_sections`,
    the contract only specifies the condition under which this is
    raised, not that the exception itself carry the partial results;
    this class intentionally does not add such a field (see module
    docstring).
    """


class NormalizationError(StateStatutesError):
    """Raised by ``normalize`` when a parsed document's structure does
    not match what the adapter expects.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.normalize`,
    this is the general "the source's shape changed underneath us"
    failure — as distinct from a document that parsed fine but
    describes the wrong section (see :class:`RefMismatchError`).
    """


class RefMismatchError(StateStatutesError):
    """Raised by ``normalize`` when the citation found in a parsed
    document does not match the ``SectionRef`` that was requested.

    Per :meth:`~state_statutes_mcp.adapters.base.BaseStateAdapter.normalize`,
    and referenced identically in
    :class:`~state_statutes_mcp.models.documents.ParsedDocument` and
    :class:`~state_statutes_mcp.models.statute_section.StatuteSection`,
    this signals a possible silent redirect or an addressing bug —
    the document itself parsed successfully, but it isn't the section
    that was asked for.
    """