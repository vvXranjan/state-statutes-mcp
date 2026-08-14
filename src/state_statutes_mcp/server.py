"""MCP server: exposes the state adapters as MCP tools over stdio.

This module is the only place that depends on the MCP SDK. It builds an
:class:`~state_statutes_mcp.core.registry.AdapterRegistry` with the
concrete adapters, wraps the pure tool functions from
:mod:`state_statutes_mcp.server_tools` as MCP tools, and runs a
stdio-transport server.

Run it with::

    python -m state_statutes_mcp.server

from the project root (the package must be importable, e.g. via
``PYTHONPATH=src`` or an editable install).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from state_statutes_mcp.adapters.delaware.adapter import DelawareAdapter
from state_statutes_mcp.adapters.florida.adapter import FloridaAdapter
from state_statutes_mcp.adapters.illinois.adapter import IllinoisAdapter
from state_statutes_mcp.adapters.texas.adapter import TexasAdapter
from state_statutes_mcp.adapters.virginia.adapter import VirginiaAdapter
from state_statutes_mcp.adapters.washington.adapter import WashingtonAdapter
from state_statutes_mcp.core.registry import AdapterRegistry
from state_statutes_mcp import server_tools

SERVER_NAME = "state-statutes-mcp"
SERVER_VERSION = "0.1.0"
SERVER_DESCRIPTION = (
    "Retrieves U.S. state statutes from the official state sources, using a "
    "per-state adapter for each supported state."
)


def build_registry() -> AdapterRegistry:
    """Build the registry with every currently supported state adapter.

    Registration is explicit — each adapter is constructed and registered
    here, rather than discovered, so the supported set is always obvious.
    """
    registry = AdapterRegistry()
    registry.register(WashingtonAdapter())
    registry.register(TexasAdapter())
    registry.register(IllinoisAdapter())
    registry.register(VirginiaAdapter())
    registry.register(DelawareAdapter())
    registry.register(FloridaAdapter())
    return registry


def build_server(registry: AdapterRegistry | None = None) -> MCPServer:
    """Build the MCP server wiring the tool functions to the adapters.

    ``registry`` is optional so tests can inject a registry; when omitted
    :func:`build_registry` is used.
    """
    if registry is None:
        registry = build_registry()
    server = MCPServer(
        name=SERVER_NAME,
        title=SERVER_NAME,
        description=SERVER_DESCRIPTION,
        version=SERVER_VERSION,
    )

    @server.tool()
    def list_states() -> list[dict]:
        """List every U.S. state whose statutes this server can retrieve."""
        return server_tools.list_states(registry)

    @server.tool()
    def list_titles(state_code: str) -> list[dict]:
        """Enumerate the top-level titles of a state's statutes.

        ``state_code`` is the two-letter USPS code (e.g. "WA").
        """
        return server_tools.list_titles(registry, state_code)

    @server.tool()
    def list_chapters(state_code: str, title: str) -> list[dict]:
        """Enumerate the chapters nested under one title of a state's statutes.

        ``state_code`` is the two-letter USPS code; ``title`` is the exact
        title identifier returned by ``list_titles`` (e.g. "49" for
        Washington, "720" for Illinois).
        """
        return server_tools.list_chapters(registry, state_code, title)

    @server.tool()
    def list_sections(state_code: str, title: str, chapter: str) -> list[dict]:
        """Enumerate the sections nested under one chapter of a state's statutes.

        ``chapter`` is the exact chapter identifier returned by
        ``list_chapters`` (e.g. "60" for Washington, "5" for Illinois).
        """
        return server_tools.list_sections(registry, state_code, title, chapter)

    @server.tool()
    def get_section(state_code: str, title: str, chapter: str, section: str) -> dict:
        """Retrieve one statute section, fully normalized.

        ``section`` is the exact section identifier returned by
        ``list_sections`` — state-specific: a full dotted citation for
        Washington (e.g. "49.60.010"), the identifier for Texas (e.g.
        "19.01"), the trailing identifier for Illinois (e.g. "9-2"), or
        the flat citation for Virginia (e.g. "18.2-51").
        """
        return server_tools.get_section(registry, state_code, title, chapter, section)

    return server


def main() -> None:
    """Run the stdio-transport MCP server."""
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
