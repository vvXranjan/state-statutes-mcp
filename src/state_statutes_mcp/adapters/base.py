"""BaseStateAdapter: the minimal, five-method abstract contract every
state adapter implements.

Scope of this milestone, deliberately narrow:

* Two identity properties (``state_code``, ``state_name``) — the bare
  minimum needed to identify which state an adapter instance is for.
* Five abstract methods (``build_url``, ``list_titles``,
  ``list_chapters``, ``list_sections``, ``normalize``) — the
  genuinely irreducible, per-state surface.

Explicitly EXCLUDED from this milestone, to be introduced later:

* Health checks and canary references (production monitoring).
* ``adapter_group`` (rollout/observability, not a functional contract).
* ``AdapterCapabilities`` and any capability-gated optional methods
  (``search``, ``infer_status``) — these depend on concepts (fetcher
  choice, status-inference strategy) that don't exist yet.
* Status inference (``StatusInferenceStrategy``).
* Fetcher/parser collaborators and the constructor injection that would
  wire them in. As a direct consequence, this milestone also has no
  concrete template methods like ``retrieve_section`` or
  ``fetch_raw`` — those orchestrate a fetcher and parser that aren't
  part of the contract yet, and adding them now would mean defining
  real behavior for a class this milestone declares out of scope.

One clarification, so the MCP layer's dependency is explicit: although
``retrieve_section`` is not part of the abstract contract, the MCP
``get_section`` tool calls it on whatever adapter the registry returns
(see :mod:`state_statutes_mcp.server_tools`). Every concrete adapter
intended to be served through that tool MUST therefore implement
``retrieve_section(ref: SectionRef) -> StatuteSection`` — an
adapter-owned convenience method that chains ``build_url`` -> fetch ->
parse into a :class:`ParsedDocument` -> ``normalize``. This requirement
comes from the MCP tool layer, not from ``BaseStateAdapter`` itself, so
it is documented here rather than enforced as abstract.

Because there are no injected collaborators, ``BaseStateAdapter`` defines
no ``__init__`` of its own in this milestone. Concrete adapters may
define whatever constructor they need; the base class imposes nothing
beyond the abstract members below.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection


class BaseStateAdapter(ABC):
    """Abstract base class every concrete state adapter implements.

    A concrete adapter (e.g. a future ``TexasAdapter``) implements the
    two identity properties and the five abstract methods below. It does
    not need to call ``super().__init__()`` with any particular
    arguments, since this milestone's base class takes none.

    Adapters served through the MCP ``get_section`` tool must also
    implement the adapter-owned ``retrieve_section`` method — see the
    module docstring for the exact requirement.
    """

    # ------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------

    @property
    @abstractmethod
    def state_code(self) -> str:
        """Two-letter state code, e.g. ``"TX"``.

        Used as the stable identifier for logging, error messages, and
        (in a later milestone) registry lookup and cache keys.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-facing display name, e.g. ``"Texas"``.

        Kept separate from ``state_code`` so callers never need to
        string-manipulate a code into a display name.
        """
        raise NotImplementedError

    # ------------------------------------------------------------
    # The five essential abstract methods
    # ------------------------------------------------------------

    @abstractmethod
    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the URL needed to retrieve ``ref``.

        This is the single most state-specific method in the system: no
        two states studied during the architecture review shared a URL
        scheme.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched by whatever mechanism this
            adapter's concrete implementation uses (fetching is not yet
            part of this contract — see module docstring).

        Raises:
            state_statutes_mcp.core.exceptions.UnsupportedRefError:
                If ``ref``'s level is not addressable for this state
                (e.g. the state has no title-level page).

        Example:
            Given ``SectionRef(identifier="49.60.010", ...)``, a
            Washington-style adapter would return
            ``"https://app.leg.wa.gov/RCW/default.aspx?cite=49.60.010"``.
        """
        raise NotImplementedError

    @abstractmethod
    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every top-level title/code this adapter knows how to
        address.

        Returns:
            A sequence of ``TocNode``, one per top-level unit.

        Raises:
            state_statutes_mcp.core.exceptions.AdapterUnavailableError:
                If the state's source is unreachable at discovery time.

        Example:
            A JSON-API-backed adapter might return one ``TocNode`` per
            law id exposed by the API's law-list endpoint.
        """
        raise NotImplementedError

    @abstractmethod
    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter (or equivalent mid-level grouping)
        under ``title_ref``.

        Args:
            title_ref: The parent title to enumerate chapters under.

        Returns:
            A sequence of ``TocNode``, one per chapter.

        Raises:
            state_statutes_mcp.core.exceptions.RefNotFoundError:
                If ``title_ref`` no longer resolves.

        Example:
            Given a title ref for "Crimes and Procedure", returns one
            ``TocNode`` per chapter listed under that title's page.
        """
        raise NotImplementedError

    @abstractmethod
    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every individually retrievable section under
        ``chapter_ref``.

        This is the discovery hop most exposed to state-specific
        addressing complexity (e.g. resolving an internal numeric offset
        range into discrete section boundaries).

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of ``TocNode``, one per section.

        Raises:
            state_statutes_mcp.core.exceptions.RefNotFoundError:
                If ``chapter_ref`` no longer resolves.
            state_statutes_mcp.core.exceptions.PartialListingError:
                If some, but not all, sections were successfully
                enumerated before a failure occurred.

        Example:
            Given a chapter ref, returns one ``TocNode`` per section
            found under that chapter's listing page.
        """
        raise NotImplementedError

    @abstractmethod
    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection``.

        This is the actual adapter contract: every other method exists
        to feed this one. In this milestone, an adapter is responsible
        for producing its own ``ParsedDocument`` however it sees fit
        (e.g. inline fetching and parsing within the adapter itself);
        the injected-collaborator design that composes this out of a
        separate fetcher and parser is a later milestone.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested,
                for cross-checking against what was actually returned.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            state_statutes_mcp.core.exceptions.NormalizationError:
                If ``parsed``'s structure does not match what this
                adapter expects (e.g. after a source-site redesign).
            state_statutes_mcp.core.exceptions.RefMismatchError:
                If the citation found in ``parsed`` does not match
                ``ref``, indicating a possible silent redirect or a bug.

        Example:
            Given a parsed document and a matching ``SectionRef``,
            returns a ``StatuteSection`` with ``status`` left at its
            default (``UNKNOWN``) if this state's source provides no
            structural status information, while still populating
            ``amendment_notes`` with any raw history text found.
        """
        raise NotImplementedError