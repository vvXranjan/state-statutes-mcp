"""Pure MCP tool implementations.

Every function here is the adapter-facing logic behind one MCP tool:
it takes an :class:`~state_statutes_mcp.core.registry.AdapterRegistry`
explicitly as its first argument (so callers can inject a registry of
their choosing) and returns plain, JSON-serializable ``dict``/``list``
values. Nothing in this module imports the MCP SDK, which keeps the
whole layer testable with nothing more than pydantic and pytest.

The MCP server in :mod:`state_statutes_mcp.server` wires these
functions up as tools; it owns the registry construction and the
transport. Do not add MCP-specific concerns (schemas, error content
objects, lifecycle) here.

Error behavior: framework exceptions (``StateStatutesError`` and its
subclasses, ``registry.UnknownStateError``) propagate untouched so the
caller can decide how to surface them. Input errors raised here are
``ValueError``.
"""

from __future__ import annotations

from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.registry import AdapterRegistry, UnknownStateError
from state_statutes_mcp.models.hierarchy import TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection


def _resolve_adapter(registry: AdapterRegistry, state_code: str) -> BaseStateAdapter:
    """Look up the adapter for ``state_code`` or raise a clear ``ValueError``."""
    try:
        return registry.get(state_code)
    except UnknownStateError as exc:
        raise ValueError(f"Unknown or unsupported state: {state_code!r}") from exc


def _node_to_dict(node: TocNode) -> dict:
    """Serialize a :class:`TocNode` to a flat JSON-safe dict."""
    return {
        "level": node.level.value,
        "identifier": node.identifier,
        "name": node.name,
    }


def _section_to_dict(section: StatuteSection) -> dict:
    """Serialize a :class:`StatuteSection` to a flat JSON-safe dict."""
    return {
        "state": section.ref.state_code,
        "section": section.ref.identifier,
        "citation": section.citation.raw,
        "heading": section.heading,
        "text": section.text,
        "status": section.status.value,
        "amendment_notes": section.amendment_notes,
        "source_url": section.source_url,
        "retrieved_at": (
            section.retrieved_at.isoformat() if section.retrieved_at is not None else None
        ),
    }


def list_states(registry: AdapterRegistry) -> list[dict]:
    """Return every state the registry can serve, as ``{state_code, state_name}``."""
    return [
        {"state_code": adapter.state_code, "state_name": adapter.state_name}
        for adapter in registry.list_adapters()
    ]


def list_titles(registry: AdapterRegistry, state_code: str) -> list[dict]:
    """Enumerate the top-level titles (or codes/divisions) of a state's statutes."""
    adapter = _resolve_adapter(registry, state_code)
    return [_node_to_dict(node) for node in adapter.list_titles()]


def list_chapters(registry: AdapterRegistry, state_code: str, title: str) -> list[dict]:
    """Enumerate the chapters nested under one title of a state's statutes."""
    adapter = _resolve_adapter(registry, state_code)
    title_ref = TitleRef(state_code=adapter.state_code, identifier=title)
    return [_node_to_dict(node) for node in adapter.list_chapters(title_ref)]


def list_sections(
    registry: AdapterRegistry,
    state_code: str,
    title: str,
    chapter: str,
) -> list[dict]:
    """Enumerate the sections nested under one chapter of a state's statutes."""
    adapter = _resolve_adapter(registry, state_code)
    title_ref = TitleRef(state_code=adapter.state_code, identifier=title)
    chapter_ref = ChapterRef(title=title_ref, identifier=chapter)
    return [_node_to_dict(node) for node in adapter.list_sections(chapter_ref)]


def get_section(
    registry: AdapterRegistry,
    state_code: str,
    title: str,
    chapter: str,
    section: str,
) -> dict:
    """Retrieve a single statute section and return it fully normalized."""
    adapter = _resolve_adapter(registry, state_code)
    title_ref = TitleRef(state_code=adapter.state_code, identifier=title)
    chapter_ref = ChapterRef(title=title_ref, identifier=chapter)
    section_ref = SectionRef(chapter=chapter_ref, identifier=section)
    statute = adapter.retrieve_section(section_ref)
    return _section_to_dict(statute)


__all__ = [
    "list_states",
    "list_titles",
    "list_chapters",
    "list_sections",
    "get_section",
]
