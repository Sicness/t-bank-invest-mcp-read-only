"""Tests for helper functions: _get_token, _headers, _ts, _parse_date, _fmt, _to_quotation."""

import json
from datetime import datetime, timezone

import pytest

from tbank_invest_mcp.server import (
    _fmt,
    _get_token,
    _headers,
    _parse_date,
    _quotation_to_float,
    _to_quotation,
    _ts,
)


class TestGetToken:
    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("TBANK_INVEST_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TBANK_INVEST_TOKEN"):
            _get_token()

    def test_empty_raises(self, monkeypatch):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", "")
        with pytest.raises(ValueError):
            _get_token()

    def test_present_returns_token(self, monkeypatch):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", "mytoken123")
        assert _get_token() == "mytoken123"


class TestHeaders:
    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", "secret")

    def test_bearer(self):
        assert _headers()["Authorization"] == "Bearer secret"

    def test_content_type(self):
        assert _headers()["Content-Type"] == "application/json"

    def test_accept(self):
        assert _headers()["Accept"] == "application/json"


class TestTs:
    def test_format(self):
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        assert _ts(dt) == "2024-01-15T10:30:45Z"

    def test_midnight(self):
        dt = datetime(2024, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
        assert _ts(dt) == "2024-12-31T00:00:00Z"


class TestParseDate:
    def test_ymd(self):
        result = _parse_date("2024-01-15")
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)

    def test_iso(self):
        result = _parse_date("2024-01-15T10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_isoz(self):
        result = _parse_date("2024-01-15T10:30:00Z")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_none_returns_default(self):
        default = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert _parse_date(None, default) is default

    def test_empty_returns_default(self):
        default = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert _parse_date("", default) is default

    def test_none_no_default_returns_none(self):
        assert _parse_date(None) is None

    @pytest.mark.parametrize("bad", ["15/01/2024", "not-a-date"])
    def test_invalid_raises(self, bad):
        with pytest.raises(ValueError, match="Cannot parse date"):
            _parse_date(bad)


class TestFmt:
    def test_cyrillic_not_escaped(self):
        result = _fmt({"name": "Газпром"})
        assert "Газпром" in result
        assert "\\u" not in result

    def test_compact(self):
        assert _fmt({"a": 1, "b": [1, {"c": None}]}) == '{"a":1,"b":[1,{"c":null}]}'

    def test_none_value(self):
        result = _fmt(None)
        assert result == "null"

    def test_list(self):
        result = _fmt([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]


class TestToQuotation:
    @pytest.mark.parametrize("value,expected", [
        (2, {"units": "2", "nano": 0}),
        (2.0, {"units": "2", "nano": 0}),
        (2.5, {"units": "2", "nano": 500_000_000}),
        (2.1, {"units": "2", "nano": 100_000_000}),
        (0.05, {"units": "0", "nano": 50_000_000}),
        (-1.5, {"units": "-1", "nano": -500_000_000}),
    ])
    def test_values(self, value, expected):
        assert _to_quotation(value) == expected

    @pytest.mark.parametrize("value", [2.0, 2.5, 0.05, 312.45, -1.5])
    def test_round_trip(self, value):
        assert _quotation_to_float(_to_quotation(value)) == pytest.approx(value)
