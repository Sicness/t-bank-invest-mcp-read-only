"""Tests for _call() — URL construction, headers, body, response handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tbank_invest_mcp.server import BASE_URL, SERVICE_PREFIX, _call


@pytest.fixture(autouse=True)
def set_token(monkeypatch):
    monkeypatch.setenv("TBANK_INVEST_TOKEN", "test-token")


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
