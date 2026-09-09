"""Tests for all 39 MCP tool functions — _call is mocked, no real HTTP calls."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import tbank_invest_mcp.server as srv


@pytest.fixture(autouse=True)
def set_token(monkeypatch):
    monkeypatch.setenv("TBANK_INVEST_TOKEN", "test-token")


def make_call_mock(return_value=None):
    if return_value is None:
        return_value = {}
    return AsyncMock(return_value=return_value)


# ── UsersService ─────────────────────────────────────────────────────────────


class TestGetAccounts:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_accounts()
        _, _, body = mock.call_args[0]
        assert body == {"status": "ACCOUNT_STATUS_ALL"}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_accounts()
        service, method, _ = mock.call_args[0]
        assert service == "UsersService"
        assert method == "GetAccounts"


class TestGetUserInfo:
    async def test_body_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_user_info()
        _, _, body = mock.call_args[0]
        assert body == {}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_user_info()
        service, method, _ = mock.call_args[0]
        assert service == "UsersService"
        assert method == "GetInfo"


class TestGetMarginAttributes:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_margin_attributes("acc123")
        _, _, body = mock.call_args[0]
        assert body == {"accountId": "acc123"}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_margin_attributes("acc")
        service, method, _ = mock.call_args[0]
        assert service == "UsersService"
        assert method == "GetMarginAttributes"


# ── OperationsService ─────────────────────────────────────────────────────────


class TestGetPortfolio:
    async def test_rub_currency(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", "RUB")
        _, _, body = mock.call_args[0]
        assert body["currency"] == 0

    async def test_usd_currency(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", "USD")
        _, _, body = mock.call_args[0]
        assert body["currency"] == 1

    async def test_eur_currency(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", "EUR")
        _, _, body = mock.call_args[0]
        assert body["currency"] == 2

    async def test_lowercase_currency(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", "usd")
        _, _, body = mock.call_args[0]
        assert body["currency"] == 1

    async def test_unknown_currency_omits_key(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", "GBP")
        _, _, body = mock.call_args[0]
        assert "currency" not in body

    async def test_account_id_in_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("myacc", "RUB")
        _, _, body = mock.call_args[0]
        assert body["accountId"] == "myacc"

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1")
        service, method, _ = mock.call_args[0]
        assert service == "OperationsService"
        assert method == "GetPortfolio"


class TestGetPositions:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_positions("acc1")
        _, _, body = mock.call_args[0]
        assert body == {"accountId": "acc1"}


class TestGetWithdrawLimits:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_withdraw_limits("acc2")
        _, _, body = mock.call_args[0]
        assert body == {"accountId": "acc2"}


class TestGetOperations:
    async def test_defaults_present(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1")
        _, _, body = mock.call_args[0]
        assert body["accountId"] == "acc1"
        assert "from" in body
        assert "to" in body

    async def test_state_prefix(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", state="EXECUTED")
        _, _, body = mock.call_args[0]
        assert body["state"] == "OPERATION_STATE_EXECUTED"

    async def test_state_lowercase(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", state="canceled")
        _, _, body = mock.call_args[0]
        assert body["state"] == "OPERATION_STATE_CANCELED"

    async def test_figi_filter(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", figi="BBG000BHR1G2")
        _, _, body = mock.call_args[0]
        assert body["figi"] == "BBG000BHR1G2"

    async def test_empty_optional_fields_omitted(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1")
        _, _, body = mock.call_args[0]
        assert "state" not in body
        assert "figi" not in body

    async def test_explicit_dates(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", from_date="2024-01-01", to_date="2024-01-31")
        _, _, body = mock.call_args[0]
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-01-31T00:00:00Z"


class TestGetOperationsByCursor:
    async def test_limit_clamped_min(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", limit=0)
        _, _, body = mock.call_args[0]
        assert body["limit"] == 1

    async def test_limit_clamped_max(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", limit=9999)
        _, _, body = mock.call_args[0]
        assert body["limit"] == 1000

    async def test_limit_normal(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", limit=50)
        _, _, body = mock.call_args[0]
        assert body["limit"] == 50

    async def test_cursor_omitted_when_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", cursor="")
        _, _, body = mock.call_args[0]
        assert "cursor" not in body

    async def test_cursor_included_when_set(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", cursor="abc123")
        _, _, body = mock.call_args[0]
        assert body["cursor"] == "abc123"

    async def test_operation_types_prefixed(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", operation_types="BUY,SELL,DIVIDEND")
        _, _, body = mock.call_args[0]
        assert body["operationTypes"] == [
            "OPERATION_TYPE_BUY",
            "OPERATION_TYPE_SELL",
            "OPERATION_TYPE_DIVIDEND",
        ]

    async def test_operation_types_with_spaces(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", operation_types="BUY, SELL")
        _, _, body = mock.call_args[0]
        assert body["operationTypes"] == ["OPERATION_TYPE_BUY", "OPERATION_TYPE_SELL"]

    async def test_operation_types_omitted_when_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1")
        _, _, body = mock.call_args[0]
        assert "operationTypes" not in body

    async def test_state_prefixed(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", state="PROGRESS")
        _, _, body = mock.call_args[0]
        assert body["state"] == "OPERATION_STATE_PROGRESS"

    async def test_without_commissions(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", without_commissions=True)
        _, _, body = mock.call_args[0]
        assert body["withoutCommissions"] is True

    async def test_without_trades(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", without_trades=True)
        _, _, body = mock.call_args[0]
        assert body["withoutTrades"] is True

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1")
        service, method, _ = mock.call_args[0]
        assert service == "OperationsService"
        assert method == "GetOperationsByCursor"


# ── InstrumentsService ────────────────────────────────────────────────────────


class TestFindInstrument:
    async def test_query_passed(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.find_instrument("SBER")
        _, _, body = mock.call_args[0]
        assert body == {"query": "SBER"}

    async def test_cyrillic_query(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.find_instrument("Газпром")
        _, _, body = mock.call_args[0]
        assert body["query"] == "Газпром"

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.find_instrument("x")
        service, method, _ = mock.call_args[0]
        assert service == "InstrumentsService"
        assert method == "FindInstrument"


class TestGetInstrumentBy:
    async def test_default_id_type(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_instrument_by("BBG000BHR1G2")
        _, _, body = mock.call_args[0]
        assert body["idType"] == "INSTRUMENT_ID_TYPE_FIGI"
        assert body["id"] == "BBG000BHR1G2"

    async def test_class_code_omitted_when_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_instrument_by("uid123", class_code="")
        _, _, body = mock.call_args[0]
        assert "classCode" not in body

    async def test_class_code_included(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_instrument_by(
                "SBER", id_type="INSTRUMENT_ID_TYPE_TICKER", class_code="TQBR"
            )
        _, _, body = mock.call_args[0]
        assert body["classCode"] == "TQBR"


class TestGetBondCoupons:
    async def test_instrument_id_in_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_coupons(instrument_id="uid123")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"

    async def test_figi_in_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_coupons(figi="BBG000BHR1G2")
        _, _, body = mock.call_args[0]
        assert body["figi"] == "BBG000BHR1G2"

    async def test_dates_present(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_coupons(instrument_id="uid")
        _, _, body = mock.call_args[0]
        assert "from" in body
        assert "to" in body

    async def test_explicit_dates(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_coupons(instrument_id="uid", from_date="2024-01-01", to_date="2024-12-31")
        _, _, body = mock.call_args[0]
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-12-31T00:00:00Z"


class TestGetBondEvents:
    async def test_instrument_id_in_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"

    async def test_type_omitted_when_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123")
        _, _, body = mock.call_args[0]
        assert "type" not in body

    async def test_type_included_when_set(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123", type="COUPON")
        _, _, body = mock.call_args[0]
        assert body["type"] == "COUPON"


class TestGetAssetFundamentals:
    async def test_single_uid(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals("uid1")
        _, _, body = mock.call_args[0]
        assert body["assets"] == ["uid1"]

    async def test_multiple_uids(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals("uid1,uid2,uid3")
        _, _, body = mock.call_args[0]
        assert body["assets"] == ["uid1", "uid2", "uid3"]

    async def test_strips_spaces(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals("uid1, uid2 , uid3")
        _, _, body = mock.call_args[0]
        assert body["assets"] == ["uid1", "uid2", "uid3"]

    async def test_filters_empty_strings(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals("uid1,,uid2")
        _, _, body = mock.call_args[0]
        assert body["assets"] == ["uid1", "uid2"]


def make_paged_call_mock(pages):
    """pages: list of (items, total_count), consumed by pageNumber index.

    GetConsensusForecasts has no server-side instrument filter, so
    get_consensus_forecasts scans pages itself — this mock plays back one
    page per call, keyed by the pageNumber the tool asked for.
    """

    async def router(service, method, body=None):
        page_number = body["paging"]["pageNumber"]
        items, total_count = pages[page_number]
        return {"items": items, "page": {"totalCount": total_count}}

    return AsyncMock(side_effect=router)


class TestGetConsensusForecasts:
    async def test_finds_match_on_first_page(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "uid-other"}, {"assetUid": "uid-target"}], 2),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("uid-target", page_limit=2))
        assert result["assetUid"] == "uid-target"
        assert mock.await_count == 1

    async def test_paginates_until_found(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "uid-other"}], 4),
            ([{"assetUid": "uid-target"}], 4),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("uid-target", page_limit=1))
        assert result["assetUid"] == "uid-target"
        assert mock.await_count == 2

    async def test_stops_when_exhausted_without_match(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "uid-other"}], 1),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("uid-target", page_limit=1))
        assert "error" in result
        assert mock.await_count == 1

    async def test_respects_max_pages_cap(self):
        # total_count is huge, so without max_pages this would loop forever.
        mock = make_paged_call_mock([([{"assetUid": "uid-other"}], 10**6)] * 3)
        with patch.object(srv, "_call", mock):
            result = json.loads(
                await srv.get_consensus_forecasts("uid-target", page_limit=1, max_pages=3)
            )
        assert "error" in result
        assert mock.await_count == 3

    async def test_first_call_uses_given_page_limit(self):
        mock = make_paged_call_mock([([{"assetUid": "uid-target"}], 1)])
        with patch.object(srv, "_call", mock):
            await srv.get_consensus_forecasts("uid-target", page_limit=50)
        _, _, body = mock.call_args[0]
        assert body == {"paging": {"limit": 50, "pageNumber": 0}}


def make_snapshot_call_mock(
    *,
    find_result=None,
    fundamentals=None,
    candles=None,
    consensus_items=None,
):
    """Routes _call by method name so get_stock_snapshot's concurrent calls
    (FindInstrument, GetAssetFundamentals, GetCandles, GetConsensusForecasts) each
    get the right canned response."""
    find_result = find_result if find_result is not None else {
        "instruments": [{"uid": "uid-sber", "name": "Сбербанк"}]
    }
    fundamentals = fundamentals if fundamentals is not None else {
        "fundamentals": [{"peRatioTtm": 4.2}]
    }
    candles = candles if candles is not None else {
        "candles": [
            {"close": {"units": "100", "nano": 0}},
            {"close": {"units": "110", "nano": 0}},
        ]
    }
    consensus_items = consensus_items if consensus_items is not None else [
        {"assetUid": "uid-sber", "consensus": "RECOMMENDATION_BUY"}
    ]

    async def router(service, method, body=None):
        if method == "FindInstrument":
            return find_result
        if method == "GetAssetFundamentals":
            return fundamentals
        if method == "GetCandles":
            return candles
        if method == "GetConsensusForecasts":
            return {"items": consensus_items, "page": {"totalCount": len(consensus_items)}}
        raise AssertionError(f"unexpected call: {service}.{method}")

    return AsyncMock(side_effect=router)


class TestGetStockSnapshot:
    async def test_combines_all_sources(self):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["uid"] == "uid-sber"
        assert result["name"] == "Сбербанк"
        assert result["fundamentals"] == {"peRatioTtm": 4.2}
        assert result["price"]["last_close"] == 110.0
        assert result["price"]["change_5d_pct"] == 10.0
        assert result["consensus"]["assetUid"] == "uid-sber"

    async def test_no_instrument_found(self):
        mock = make_snapshot_call_mock(find_result={"instruments": []})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("NOPE"))
        assert "error" in result

    async def test_no_candles_returns_empty_price(self):
        mock = make_snapshot_call_mock(candles={"candles": []})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["price"] == {}

    async def test_candle_days_used_in_candles_request(self):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_stock_snapshot("SBER", candle_days=10)
        candles_call = next(c for c in mock.call_args_list if c[0][1] == "GetCandles")
        body = candles_call[0][2]
        assert body["instrumentId"] == "uid-sber"
        assert body["interval"] == "CANDLE_INTERVAL_DAY"


class TestGetForecastBy:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_forecast_by("uid123")
        _, _, body = mock.call_args[0]
        assert body == {"instrumentId": "uid123"}


class TestGetDividends:
    async def test_instrument_id(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_dividends("uid123")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"

    async def test_dates_present(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_dividends("uid123")
        _, _, body = mock.call_args[0]
        assert "from" in body
        assert "to" in body


class TestGetAccruedInterests:
    async def test_body_structure(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_accrued_interests("uid123", from_date="2024-01-01", to_date="2024-02-01")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-02-01T00:00:00Z"


class TestGetAssetReports:
    async def test_body_structure(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_reports("uid123", from_date="2024-01-01", to_date="2024-12-31")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-12-31T00:00:00Z"


class TestGetFavorites:
    async def test_body_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_favorites()
        _, _, body = mock.call_args[0]
        assert body == {}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_favorites()
        service, method, _ = mock.call_args[0]
        assert service == "InstrumentsService"
        assert method == "GetFavorites"


class TestGetTradingSchedules:
    async def test_exchange_omitted_when_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_trading_schedules()
        _, _, body = mock.call_args[0]
        assert "exchange" not in body

    async def test_exchange_included(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_trading_schedules(exchange="MOEX")
        _, _, body = mock.call_args[0]
        assert body["exchange"] == "MOEX"

    async def test_dates_present(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_trading_schedules()
        _, _, body = mock.call_args[0]
        assert "from" in body
        assert "to" in body


class TestInstrumentBy:
    """Test get_bond_by, get_share_by, get_etf_by, get_currency_by, get_future_by."""

    @pytest.mark.parametrize(
        "func, expected_method",
        [
            (srv.get_bond_by, "BondBy"),
            (srv.get_share_by, "ShareBy"),
            (srv.get_etf_by, "EtfBy"),
            (srv.get_currency_by, "CurrencyBy"),
            (srv.get_future_by, "FutureBy"),
        ],
    )
    async def test_service_method(self, func, expected_method):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await func("BBG000BHR1G2")
        service, method, _ = mock.call_args[0]
        assert service == "InstrumentsService"
        assert method == expected_method

    @pytest.mark.parametrize(
        "func",
        [srv.get_bond_by, srv.get_share_by, srv.get_etf_by, srv.get_currency_by, srv.get_future_by],
    )
    async def test_class_code_omitted_when_empty(self, func):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await func("figi123")
        _, _, body = mock.call_args[0]
        assert "classCode" not in body

    @pytest.mark.parametrize(
        "func",
        [srv.get_bond_by, srv.get_share_by, srv.get_etf_by, srv.get_currency_by, srv.get_future_by],
    )
    async def test_class_code_included(self, func):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await func("SBER", id_type="INSTRUMENT_ID_TYPE_TICKER", class_code="TQBR")
        _, _, body = mock.call_args[0]
        assert body["classCode"] == "TQBR"


# ── MarketDataService ─────────────────────────────────────────────────────────


class TestGetCandles:
    async def test_body_structure(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_candles("uid123", from_date="2024-01-01", to_date="2024-02-01")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-02-01T00:00:00Z"
        assert body["interval"] == "CANDLE_INTERVAL_DAY"

    async def test_custom_interval(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_candles("uid123", interval="CANDLE_INTERVAL_HOUR")
        _, _, body = mock.call_args[0]
        assert body["interval"] == "CANDLE_INTERVAL_HOUR"

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_candles("uid")
        service, method, _ = mock.call_args[0]
        assert service == "MarketDataService"
        assert method == "GetCandles"


class TestGetLastPrices:
    async def test_single_id(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_last_prices("figi1")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == ["figi1"]

    async def test_multiple_ids(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_last_prices("figi1,figi2,figi3")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == ["figi1", "figi2", "figi3"]

    async def test_strips_spaces(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_last_prices("figi1, figi2")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == ["figi1", "figi2"]

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_last_prices("figi1")
        service, method, _ = mock.call_args[0]
        assert service == "MarketDataService"
        assert method == "GetLastPrices"


class TestGetOrderBook:
    async def test_depth_clamped_min(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_book("figi1", depth=0)
        _, _, body = mock.call_args[0]
        assert body["depth"] == 1

    async def test_depth_clamped_max(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_book("figi1", depth=100)
        _, _, body = mock.call_args[0]
        assert body["depth"] == 50

    async def test_depth_normal(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_book("figi1", depth=20)
        _, _, body = mock.call_args[0]
        assert body["depth"] == 20

    async def test_instrument_id(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_book("figi123")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "figi123"


class TestGetClosePrices:
    async def test_single_id(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_close_prices("figi1")
        _, _, body = mock.call_args[0]
        assert body["instruments"] == [{"instrumentId": "figi1"}]

    async def test_multiple_ids(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_close_prices("figi1,figi2")
        _, _, body = mock.call_args[0]
        assert body["instruments"] == [
            {"instrumentId": "figi1"},
            {"instrumentId": "figi2"},
        ]

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_close_prices("figi1")
        service, method, _ = mock.call_args[0]
        assert service == "MarketDataService"
        assert method == "GetClosePrices"


class TestGetTradingStatus:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_trading_status("figi123")
        _, _, body = mock.call_args[0]
        assert body == {"instrumentId": "figi123"}


class TestGetTechAnalysis:
    async def test_uses_instrument_uid_key(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_RSI")
        _, _, body = mock.call_args[0]
        assert "instrumentUid" in body
        assert body["instrumentUid"] == "uid123"
        assert "instrumentId" not in body

    async def test_indicator_type(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_MACD")
        _, _, body = mock.call_args[0]
        assert body["indicatorType"] == "INDICATOR_TYPE_MACD"

    async def test_defaults(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_SMA")
        _, _, body = mock.call_args[0]
        assert body["interval"] == "CANDLE_INTERVAL_DAY"
        assert body["typeOfPrice"] == "TYPE_OF_PRICE_CLOSE"
        assert body["length"] == 14

    async def test_dates_present(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_EMA")
        _, _, body = mock.call_args[0]
        assert "from" in body
        assert "to" in body

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid", "INDICATOR_TYPE_BB")
        service, method, _ = mock.call_args[0]
        assert service == "MarketDataService"
        assert method == "GetTechAnalysis"


# ── OrdersService ─────────────────────────────────────────────────────────────


class TestGetOrders:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_orders("acc1")
        _, _, body = mock.call_args[0]
        assert body == {"accountId": "acc1"}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_orders("acc1")
        service, method, _ = mock.call_args[0]
        assert service == "OrdersService"
        assert method == "GetOrders"


class TestGetOrderState:
    async def test_body(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_state("acc1", "order123")
        _, _, body = mock.call_args[0]
        assert body == {"accountId": "acc1", "orderId": "order123"}

    async def test_service_method(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_order_state("acc1", "order123")
        service, method, _ = mock.call_args[0]
        assert service == "OrdersService"
        assert method == "GetOrderState"


# ── InstrumentsList tools ─────────────────────────────────────────────────────


class TestInstrumentLists:
    @pytest.mark.parametrize(
        "func, expected_method",
        [
            (srv.list_shares, "Shares"),
            (srv.list_bonds, "Bonds"),
            (srv.list_etfs, "Etfs"),
            (srv.list_currencies, "Currencies"),
            (srv.list_futures, "Futures"),
        ],
    )
    async def test_default_status(self, func, expected_method):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await func()
        service, method, body = mock.call_args[0]
        assert service == "InstrumentsService"
        assert method == expected_method
        assert body == {"instrumentStatus": "INSTRUMENT_STATUS_BASE"}

    @pytest.mark.parametrize(
        "func",
        [srv.list_shares, srv.list_bonds, srv.list_etfs, srv.list_currencies, srv.list_futures],
    )
    async def test_custom_status(self, func):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await func(instrument_status="INSTRUMENT_STATUS_ALL")
        _, _, body = mock.call_args[0]
        assert body["instrumentStatus"] == "INSTRUMENT_STATUS_ALL"


# ── Return value formatting ───────────────────────────────────────────────────


class TestReturnFormatting:
    async def test_returns_json_string(self):
        mock = make_call_mock({"key": "value"})
        with patch.object(srv, "_call", mock):
            result = await srv.get_accounts()
        # result should be a JSON string
        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    async def test_cyrillic_not_escaped_in_output(self):
        mock = make_call_mock({"name": "Газпром"})
        with patch.object(srv, "_call", mock):
            result = await srv.find_instrument("test")
        assert "Газпром" in result
        assert "\\u" not in result
