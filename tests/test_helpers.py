"""Tests for helper functions: _get_token, _headers, _ts, _parse_date, _fmt, _to_quotation."""

import json
from datetime import datetime, timezone

import pytest

from tbank_invest_mcp.server import (
    _enum,
    _plain,
    _trimmed,
    _fmt,
    _get_token,
    _headers,
    _parse_date,
    _number,
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
        assert _number(_to_quotation(value)) == pytest.approx(value)


def q(units, nano=0):
    return {"units": str(units), "nano": nano}


def m(units, nano=0, currency="rub"):
    return {"currency": currency, "units": str(units), "nano": nano}


class TestPlain:
    @pytest.mark.parametrize("value, expected", [
        (q(273, 800000000), 273.8),
        (q(100), 100),
        (q(0), 0),
        (q(-1, -500000000), -1.5),
        (q(0, 10000000), 0.01),
        ({"units": "5"}, 5),
        ({"nano": 250000000}, 0.25),
    ])
    def test_quotation_becomes_a_number(self, value, expected):
        result = _plain({"price": value})["price"]
        assert result == expected
        assert type(result) is type(expected)

    def test_amounts_share_the_objects_currency(self):
        assert _plain({"price": m(274, 100000000), "payment": m(-27410)}) == {
            "currency": "rub", "price": 274.1, "payment": -27410,
        }

    def test_existing_currency_field_is_kept_when_it_agrees(self):
        assert _plain({"currency": "RUB", "nominal": m(1000)}) == {"currency": "RUB", "nominal": 1000}

    def test_amounts_in_different_currencies_stay_explicit(self):
        assert _plain({"nominal": m(1000, currency="usd"), "aciValue": m(12, 300000000)}) == {
            "nominal": {"value": 1000, "currency": "usd"},
            "aciValue": {"value": 12.3, "currency": "rub"},
        }

    def test_amount_that_disagrees_with_the_objects_currency_stays_explicit(self):
        assert _plain({"currency": "rub", "nominal": m(1000, currency="usd")}) == {
            "currency": "rub", "nominal": {"value": 1000, "currency": "usd"},
        }

    def test_amount_without_a_currency_does_not_decide_it(self):
        assert _plain({"price": m(10), "varMargin": m(0, currency="")}) == {
            "currency": "rub", "price": 10, "varMargin": 0,
        }

    def test_amount_on_its_own(self):
        assert _plain([m(1500, 500000000), m(20, currency="usd")]) == [
            {"value": 1500.5, "currency": "rub"}, {"value": 20, "currency": "usd"},
        ]

    def test_nested_structures(self):
        data = {"bids": [{"price": q(274, 100000000), "quantity": "10"}], "depth": 1, "name": "x"}
        assert _plain(data) == {"bids": [{"price": 274.1, "quantity": "10"}], "depth": 1, "name": "x"}

    def test_other_objects_are_left_alone(self):
        data = {"units": "5", "nano": 0, "figi": "F"}  # not a Quotation: it has another field
        assert _plain(data) == data
        assert _plain({}) == {}
        assert _plain({"brand": {}}) == {"brand": {}}

    def test_applying_twice_changes_nothing(self):
        data = {"price": m(274, 100000000), "items": [m(1), {"nominal": m(5, currency="usd"), "x": m(1)}]}
        once = _plain(data)
        assert _plain(once) == once

    def test_fmt_applies_it(self):
        assert _fmt({"price": q(1, 500000000)}) == '{"price":1.5}'


class TestTrimmed:
    def test_drops_zero_false_and_empty_fields_of_list_items(self):
        data = {"positions": [{"ticker": "SBER", "blocked": False, "blockedLots": q(0), "note": "",
                               "balance": "0", "trades": [], "extra": {}, "quantity": q(10), "flag": True}]}
        assert _trimmed(data, "positions") == {"positions": [{"ticker": "SBER", "quantity": 10, "flag": True}]}

    def test_named_fields_are_dropped_whatever_they_hold(self):
        data = {"positions": [{"ticker": "SBER", "quantityLots": q(10)}]}
        assert _trimmed(data, "positions", drop=("quantityLots",)) == {"positions": [{"ticker": "SBER"}]}

    def test_only_the_named_lists_are_trimmed(self):
        data = {"total": q(0), "hasNext": False, "other": [{"x": 0}], "positions": [{"x": 0, "y": 1}]}
        assert _trimmed(data, "positions") == {"total": 0, "hasNext": False, "other": [{"x": 0}], "positions": [{"y": 1}]}

    def test_missing_list_is_fine(self):
        assert _trimmed({"a": 1}, "positions") == {"a": 1}
