"""Tests for helper functions: _get_token, _headers, _ts, _parse_date, _fmt, _to_quotation."""

import json
from datetime import datetime, timezone

import pytest

from tbank_invest_mcp.server import (
    _enum,
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

    @pytest.mark.parametrize("raw", ["mytoken123\n", "  mytoken123", "\tmytoken123\r\n"])
    def test_surrounding_whitespace_is_stripped(self, monkeypatch, raw):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", raw)
        assert _get_token() == "mytoken123"

    def test_whitespace_only_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", " \n")
        with pytest.raises(ValueError, match="is not set"):
            _get_token()

    @pytest.mark.parametrize("bad", ["my token", "my\ntoken", "токен123", "tok\x7fen"])
    def test_malformed_token_is_rejected_without_echoing_it(self, monkeypatch, bad):
        monkeypatch.setenv("TBANK_INVEST_TOKEN", bad)
        with pytest.raises(ValueError) as exc_info:
            _get_token()
        assert "characters a token cannot have" in str(exc_info.value)
        assert bad not in str(exc_info.value)


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

    def test_surrounding_spaces_ignored(self):
        assert _parse_date(" 2024-01-15 ") == datetime(2024, 1, 15, tzinfo=timezone.utc)

    def test_end_of_day_for_a_bare_date(self):
        result = _parse_date("2024-01-15", end_of_day=True)
        assert result == datetime(2024, 1, 15, 23, 59, 59, tzinfo=timezone.utc)

    @pytest.mark.parametrize("s", ["2024-01-15T10:30:00", "2024-01-15T10:30:00Z", "2024-01-15T00:00:00"])
    def test_end_of_day_leaves_an_explicit_time_alone(self, s):
        assert _parse_date(s, end_of_day=True) == _parse_date(s)

    def test_end_of_day_does_not_touch_the_default(self):
        default = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert _parse_date("", default, end_of_day=True) is default


class TestEnum:
    @pytest.mark.parametrize("given", ["EXECUTED", "executed", " Executed ", "OPERATION_STATE_EXECUTED"])
    def test_prefix_added_once(self, given):
        assert _enum(given, "OPERATION_STATE_") == "OPERATION_STATE_EXECUTED"

    def test_allowed_values_pass(self):
        assert _enum("mty", "EVENT_TYPE_", ("CPN", "MTY")) == "EVENT_TYPE_MTY"

    def test_unknown_value_names_the_valid_ones(self):
        with pytest.raises(ValueError, match="'MATURITY'.*CPN, MTY"):
            _enum("MATURITY", "EVENT_TYPE_", ("CPN", "MTY"))

    def test_no_allowed_list_means_no_check(self):
        assert _enum("anything", "OPERATION_TYPE_") == "OPERATION_TYPE_ANYTHING"


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
