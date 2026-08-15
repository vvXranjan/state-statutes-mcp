"""Lightweight smoke tests for the MCP server wiring.

These confirm the server exposes exactly the five expected tools with
the expected parameter sets, and that the in-process ``list_states``
call (which makes no network requests) reaches the real adapters.
Everything else — parsing, ref building, error mapping — is covered by
``test_server_tools`` without needing the MCP SDK.
"""

from __future__ import annotations

import asyncio

from state_statutes_mcp.server import SERVER_NAME, build_server


def _tool_names(server) -> list[str]:
    async def _list() -> list[str]:
        tools = await server.list_tools()
        return sorted(tool.name for tool in tools)

    return asyncio.run(_list())


class TestServerToolsExposed:
    def test_server_exposes_exactly_five_tools(self) -> None:
        server = build_server()

        assert _tool_names(server) == [
            "get_section",
            "list_chapters",
            "list_sections",
            "list_states",
            "list_titles",
        ]

    def test_tools_carry_expected_parameters(self) -> None:
        server = build_server()

        async def _params() -> dict:
            params = {}
            for tool in await server.list_tools():
                params[tool.name] = list(
                    tool.input_schema.get("properties", {}).keys()
                )
            return params

        params = asyncio.run(_params())

        assert params["list_states"] == []
        assert params["list_titles"] == ["state_code"]
        assert params["list_chapters"] == ["state_code", "title"]
        assert params["list_sections"] == ["state_code", "title", "chapter"]
        assert params["get_section"] == ["state_code", "title", "chapter", "section"]

    def test_in_process_list_states_reaches_adapters(self) -> None:
        server = build_server()

        async def _call() -> dict:
            result = await server.call_tool("list_states", {})
            return result.structured_content

        content = asyncio.run(_call())

        states = content["result"]
        assert [s["state_code"] for s in states] == [
            "AZ",
            "DE",
            "FL",
            "IL",
            "ME",
            "MN",
            "MO",
            "SD",
            "TX",
            "VA",
            "VT",
            "WA",
            "WV",
        ]


class TestServerIdentity:
    def test_server_name(self) -> None:
        assert SERVER_NAME == "state-statutes-mcp"

    def test_build_server_accepts_injected_registry(self) -> None:
        from state_statutes_mcp.core.registry import AdapterRegistry

        registry = AdapterRegistry()
        server = build_server(registry=registry)

        async def _call() -> dict:
            result = await server.call_tool("list_states", {})
            return result.structured_content

        assert asyncio.run(_call())["result"] == []