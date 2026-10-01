"""Tests for _call() — URL construction, headers, body, response handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tbank_invest_mcp import server
from tbank_invest_mcp.server import BASE_URL, SERVICE_PREFIX, _call


@pytest.fixture(autouse=True)
def set_token(monkeypatch):
    monkeypatch.setenv("TBANK_INVEST_TOKEN", "test-token")


@pytest.fixture(autouse=True)
def reset_client():
    """_call() reuses one module-level client; drop it so each test gets its mock."""
    server._client = None
    yield
    server._client = None


def _make_mock_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def make_http_mock():
    """Factory: make_http_mock(data, status_code) → configured AsyncClient mock."""
    def _make(data=None, status_code=200):
        resp = _make_mock_response(data or {}, status_code)
        client = AsyncMock()
        client.post.return_value = resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client
    return _make


class TestCallUrlConstruction:
    async def test_url_format(self, make_http_mock):
        client = make_http_mock({"ok": True})
        with patch("httpx.AsyncClient", return_value=client):
            await _call("UsersService", "GetAccounts", {})
        url = client.post.call_args[0][0]
        assert url == f"{BASE_URL}/{SERVICE_PREFIX}.UsersService/GetAccounts"

    async def test_url_contains_base(self, make_http_mock):
        client = make_http_mock()
        with patch("httpx.AsyncClient", return_value=client):
            await _call("MarketDataService", "GetCandles", {})
        url = client.post.call_args[0][0]
        assert url.startswith(BASE_URL)
        assert "MarketDataService" in url
        assert "GetCandles" in url


class TestCallHeaders:
    async def test_auth_header_sent(self, make_http_mock):
        client = make_http_mock()
        with patch("httpx.AsyncClient", return_value=client):
            await _call("UsersService", "GetInfo", {})
        headers = client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"


class TestCallBody:
    async def test_none_body_sends_empty_dict(self, make_http_mock):
        client = make_http_mock()
        with patch("httpx.AsyncClient", return_value=client):
            await _call("UsersService", "GetInfo", None)
        assert client.post.call_args[1]["json"] == {}

    async def test_body_passed_as_json(self, make_http_mock):
        client = make_http_mock()
        body = {"accountId": "acc123", "limit": 50}
        with patch("httpx.AsyncClient", return_value=client):
            await _call("OperationsService", "GetPortfolio", body)
        assert client.post.call_args[1]["json"] == body


class TestCallResponse:
    async def test_returns_json(self, make_http_mock):
        expected = {"accounts": [{"id": "123"}]}
        client = make_http_mock(expected)
        with patch("httpx.AsyncClient", return_value=client):
            result = await _call("UsersService", "GetAccounts", {})
        assert result == expected

    async def test_raises_on_http_error(self, make_http_mock):
        client = make_http_mock(status_code=401)
        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError):
                await _call("UsersService", "GetAccounts", {})

    async def test_raises_on_404(self, make_http_mock):
        client = make_http_mock(status_code=404)
        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError):
                await _call("InstrumentsService", "GetInstrumentBy", {"id": "xxx"})


class TestCallErrorMessage:
    """The exception text is what the model reads as the tool error."""

    @staticmethod
    async def _error(response: httpx.Response) -> httpx.HTTPStatusError:
        # A real httpx.Response, so raise_for_status() behaves exactly as in production.
        response.request = httpx.Request("POST", f"{BASE_URL}/{SERVICE_PREFIX}.InstrumentsService/GetInstrumentBy")
        client = AsyncMock()
        client.post.return_value = response
        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await _call("InstrumentsService", "GetInstrumentBy", {"id": "xxx"})
        return exc_info.value

    async def test_carries_api_message_and_code(self):
        error = await self._error(httpx.Response(
            404, json={"code": 5, "message": "Instrument not found", "description": "50002"},
        ))
        assert str(error) == (
            "T-Bank API returned HTTP 404 for InstrumentsService/GetInstrumentBy: "
            "Instrument not found (error code 50002)"
        )

    async def test_message_without_code(self):
        error = await self._error(httpx.Response(400, json={"message": "`interval` is invalid"}))
        assert str(error).endswith("GetInstrumentBy: `interval` is invalid")

    async def test_non_json_body_is_quoted(self):
        error = await self._error(httpx.Response(502, text="<html>Bad Gateway</html>"))
        assert str(error).endswith("HTTP 502 for InstrumentsService/GetInstrumentBy: <html>Bad Gateway</html>")

    async def test_empty_body(self):
        error = await self._error(httpx.Response(503))
        assert str(error).endswith("no details in the response")

    async def test_json_without_message_is_quoted(self):
        error = await self._error(httpx.Response(500, json={"unexpected": True}))
        assert '"unexpected"' in str(error)

    async def test_long_body_is_truncated(self):
        error = await self._error(httpx.Response(500, text="x" * 5000))
        assert len(str(error)) < 500

    async def test_no_url_or_token_in_message(self):
        error = await self._error(httpx.Response(401, json={"message": "Authentication token is missing or invalid"}))
        assert "https://" not in str(error)
        assert "test-token" not in str(error)

    async def test_response_stays_available(self):
        error = await self._error(httpx.Response(404, json={"message": "Instrument not found"}))
        assert error.response.status_code == 404
