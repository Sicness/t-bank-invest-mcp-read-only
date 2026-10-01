"""Tests for what an MCP client receives from the server: tool list, server info, result shape."""

import json
from importlib.metadata import version
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

import tbank_invest_mcp
import tbank_invest_mcp.server as srv


@pytest.fixture
async def tools():
    return await srv.mcp.list_tools()


class TestToolList:
    async def test_every_public_coroutine_is_registered(self, tools):
        """A tool defined without @read_only_tool would silently be missing from the list."""
        registered = {t.name for t in tools}
        defined = {
            name for name, obj in vars(srv).items()
            if not name.startswith("_") and name.startswith(("get_", "find_", "list_")) and callable(obj)
        }
        assert defined == registered

    async def test_every_tool_is_marked_read_only(self, tools):
        """Read-only is the product's promise; a tool registered with bare mcp.tool() fails here."""
        not_marked = [t.name for t in tools if not (t.annotations and t.annotations.readOnlyHint is True)]
        assert not_marked == []

    async def test_no_tool_claims_to_be_destructive(self, tools):
        assert [t.name for t in tools if t.annotations.destructiveHint] == []

    async def test_descriptions_are_dedented(self, tools):
        for tool in tools:
            assert tool.description, tool.name
            assert tool.description == tool.description.strip(), tool.name
            # Docstring bodies are indented four spaces in the source; "Args:" must sit at column 0.
            assert "\n    Args:" not in tool.description, tool.name

    async def test_description_is_the_docstring(self, tools):
        description = next(t.description for t in tools if t.name == "get_margin_attributes")
        assert description.startswith("Get margin trading attributes for an account")
        assert "\nArgs:\n    account_id: Account ID (get from get_accounts)" in description

    async def test_enum_parameters_list_their_values(self, tools):
        """The values are in the schema, where a client can show and check them, not only in prose."""
        by_name = {t.name: t.inputSchema["properties"] for t in tools}
        assert "CANDLE_INTERVAL_DAY" in by_name["get_candles"]["interval"]["enum"]
        assert by_name["get_candles"]["interval"]["default"] == "CANDLE_INTERVAL_DAY"
        assert by_name["get_portfolio"]["currency"]["enum"] == ["RUB", "USD", "EUR"]
        assert "INDICATOR_TYPE_RSI" in by_name["get_tech_analysis"]["indicator_type"]["enum"]
        assert "bond" in by_name["find_instrument"]["instrument_kind"]["enum"]
        for name in ("get_bond_by", "get_share_by", "get_instrument_by"):
            assert "INSTRUMENT_ID_TYPE_UID" in by_name[name]["id_type"]["enum"]

    async def test_enum_hints_do_not_reject_other_spellings(self):
        with patch.object(srv, "_call", AsyncMock(return_value={"candles": []})) as mock:
            await srv.mcp.call_tool("get_candles", {
                "instrument_id": "e6123145-9665-43e0-8413-cd61b8aa9b13", "interval": "week",
            })
        assert mock.call_args[0][2]["interval"] == "CANDLE_INTERVAL_WEEK"

    async def test_tech_analysis_schema_keeps_the_interval_names_it_used_to_take(self, tools):
        """A client that enforces the schema must not refuse what the server still translates."""
        by_name = {t.name: t.inputSchema["properties"] for t in tools}
        interval = by_name["get_tech_analysis"]["interval"]["enum"]
        assert "INDICATOR_INTERVAL_ONE_DAY" in interval and "CANDLE_INTERVAL_DAY" in interval

    async def test_account_id_may_arrive_as_a_number(self, tools):
        by_name = {t.name: t.inputSchema["properties"] for t in tools}
        assert by_name["get_orders"]["account_id"]["type"] == "string"
        with patch.object(srv, "_call", AsyncMock(return_value={"orders": []})) as mock:
            await srv.mcp.call_tool("get_orders", {"account_id": 2010663975})
        assert mock.call_args[0][2] == {"accountId": "2010663975"}

    async def test_removed_parameter_of_consensus_forecasts_is_still_taken(self, tools):
        by_name = {t.name: t.inputSchema["properties"] for t in tools}
        assert "page_number" in by_name["get_consensus_forecasts"]

    async def test_no_output_schema(self, tools):
        """Tools return a JSON string; a {"result": string} schema would make FastMCP send it twice."""
        assert [t.name for t in tools if t.outputSchema is not None] == []


class TestServerInfo:
    def test_reports_package_version_not_sdk_version(self):
        options = srv.mcp._mcp_server.create_initialization_options()
        assert options.server_version == version("t-bank-invest-mcp-read-only")
        assert options.server_version == tbank_invest_mcp.__version__
        assert options.server_version != version("mcp")

    def test_server_name(self):
        assert srv.mcp._mcp_server.create_initialization_options().server_name == "t-bank-invest-mcp-read-only"


class TestCallToolResult:
    async def test_response_is_sent_once_as_compact_json(self):
        data = {"accounts": [{"id": "1", "name": "Брокерский счёт"}]}
        with patch.object(srv, "_call", AsyncMock(return_value=data)):
            result = await srv.mcp.call_tool("get_accounts", {})
        # A (content, structuredContent) tuple here would mean the payload goes out twice.
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].text == '{"accounts":[{"id":"1","name":"Брокерский счёт"}]}'
        assert json.loads(result[0].text) == data

    async def test_api_error_reaches_the_client_with_its_message(self):
        response = httpx.Response(
            404,
            json={"code": 5, "message": "Instrument not found", "description": "50002"},
            request=httpx.Request("POST", "https://example.invalid/"),
        )
        client = AsyncMock()
        client.post.return_value = response
        with patch.object(srv, "_get_client", return_value=client):
            with pytest.raises(ToolError) as exc_info:
                await srv.mcp.call_tool("get_instrument_by", {"id": "NOPE"})
        assert "Instrument not found (error code 50002)" in str(exc_info.value)
