"""Tests for all 39 MCP tool functions — _call is mocked, no real HTTP calls."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import tbank_invest_mcp.server as srv


@pytest.fixture(autouse=True)
def forget_resolved_instruments():
    """Identifier lookups are cached for the life of the process; tests must not share them."""
    for cache in (srv._resolved, srv._missed, srv._asset_uids):
        cache.clear()
    yield
    for cache in (srv._resolved, srv._missed, srv._asset_uids):
        cache.clear()


def make_call_mock(return_value=None):
    if return_value is None:
        return_value = {}
    return AsyncMock(return_value=return_value)


def route(**by_method):
    """_call mock answering by API method name; a value may be a function of the request body.
    Methods not named answer {} — which for FindInstrument means "nothing matches"."""
    async def router(service, method, body=None):
        answer = by_method.get(method, {})
        return answer(body) if callable(answer) else answer

    return AsyncMock(side_effect=router)


SBER = {
    "ticker": "SBER", "classCode": "TQBR", "name": "Сбер Банк", "instrumentType": "share",
    "instrumentKind": "INSTRUMENT_TYPE_SHARE", "uid": "e6123145-9665-43e0-8413-cd61b8aa9b13",
    "figi": "BBG004730N88", "isin": "RU0009029540", "lot": 1, "apiTradeAvailableFlag": True,
    "forQualInvestorFlag": False, "forIisFlag": True, "weekendFlag": True, "blockedTcaFlag": False,
    "positionUid": "41eb2102-5333-4713-bf15-72b204c4bf7b",
}
SBERP = {**SBER, "ticker": "SBERP", "name": "Сбер Банк - привилегированные акции",
         "uid": "c190ff1f-1447-4227-b543-316332699ca5", "figi": "BBG0047315Y7", "isin": "RU0009029557"}
SBER_OTC = {**SBER, "classCode": "SPEQ", "uid": "11111111-2222-3333-4444-555555555555",
            "figi": "TCS009029540", "apiTradeAvailableFlag": False}


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

    async def test_unknown_currency_is_rejected(self):
        # Silently falling back to roubles would let the caller read rouble totals as GBP.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="RUB, USD, EUR"):
                await srv.get_portfolio("acc1", "GBP")
        mock.assert_not_called()

    async def test_currency_case_and_spaces(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_portfolio("acc1", " usd ")
        _, _, body = mock.call_args[0]
        assert body["currency"] == 1

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
        assert body["to"] == "2024-01-31T23:59:59Z"

    async def test_one_day_range_is_not_empty(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", from_date="2024-01-31", to_date="2024-01-31")
        _, _, body = mock.call_args[0]
        assert (body["from"], body["to"]) == ("2024-01-31T00:00:00Z", "2024-01-31T23:59:59Z")

    async def test_to_date_with_time_is_taken_as_is(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", to_date="2024-01-31T10:00:00")
        _, _, body = mock.call_args[0]
        assert body["to"] == "2024-01-31T10:00:00Z"

    async def test_state_already_prefixed(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc1", state="OPERATION_STATE_EXECUTED")
        _, _, body = mock.call_args[0]
        assert body["state"] == "OPERATION_STATE_EXECUTED"

    async def test_unknown_state_is_rejected(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="EXECUTED, CANCELED, PROGRESS"):
                await srv.get_operations("acc1", state="DONE")
        mock.assert_not_called()


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

    async def test_state_already_prefixed(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", state="operation_state_progress")
        _, _, body = mock.call_args[0]
        assert body["state"] == "OPERATION_STATE_PROGRESS"

    async def test_operation_types_already_prefixed_and_empty_items(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", operation_types="OPERATION_TYPE_BUY, sell,,")
        _, _, body = mock.call_args[0]
        assert body["operationTypes"] == ["OPERATION_TYPE_BUY", "OPERATION_TYPE_SELL"]

    async def test_to_date_includes_the_whole_day(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", from_date="2024-01-31", to_date="2024-01-31")
        _, _, body = mock.call_args[0]
        assert (body["from"], body["to"]) == ("2024-01-31T00:00:00Z", "2024-01-31T23:59:59Z")

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
        # Deprecated, but existing callers pass it and the API still takes it.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_coupons(figi="BBG000BHR1G2")
        _, _, body = mock.call_args[0]
        assert body["figi"] == "BBG000BHR1G2"
        assert "instrumentId" not in body

    async def test_no_identifier_is_rejected_before_the_request(self):
        # The API would answer "Missing parameter: figi", sending the caller to the deprecated one.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="instrument_id is required"):
                await srv.get_bond_coupons(from_date="2026-01-01")
        mock.assert_not_called()

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
        assert body["to"] == "2024-12-31T23:59:59Z"


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

    @pytest.mark.parametrize("given", ["CPN", "cpn", "EVENT_TYPE_CPN", " event_type_cpn "])
    async def test_type_sent_as_full_enum_name(self, given):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123", type=given)
        _, _, body = mock.call_args[0]
        assert body["type"] == "EVENT_TYPE_CPN"

    @pytest.mark.parametrize("old_name, sent", [
        ("COUPON", "EVENT_TYPE_CPN"), ("maturity", "EVENT_TYPE_MTY"), ("CONVERSION", "EVENT_TYPE_CONV"),
    ])
    async def test_names_from_the_old_description_now_filter(self, old_name, sent):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123", type=old_name)
        _, _, body = mock.call_args[0]
        assert body["type"] == sent

    @pytest.mark.parametrize("unknown", ["PUT", "AMORTIZATION", "EVENT_TYPE_BOGUS"])
    async def test_unknown_type_is_rejected(self, unknown):
        # The API ignores a type it does not know and returns every event, with no error.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="CPN, CALL, MTY, CONV"):
                await srv.get_bond_events("uid123", type=unknown)
        mock.assert_not_called()

    async def test_dates_omitted_by_default(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123")
        _, _, body = mock.call_args[0]
        assert body == {"instrumentId": "uid123"}

    async def test_explicit_dates(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("uid123", type="MTY", from_date="2020-01-01", to_date="2045-01-01")
        _, _, body = mock.call_args[0]
        assert body == {
            "instrumentId": "uid123",
            "type": "EVENT_TYPE_MTY",
            "from": "2020-01-01T00:00:00Z",
            "to": "2045-01-01T23:59:59Z",
        }


ASSET_1 = "40d89385-a03a-4659-bf4e-d3ecba011782"
ASSET_2 = "bfc8184d-9562-4ea2-87dd-be6e76dc1279"
ASSET_3 = "cccccccc-1111-2222-3333-444444444444"


class TestGetAssetFundamentals:
    """Asset UIDs given directly: the mock answers {} to the instrument lookup, as the API
    answers 404 — nothing knows them as instruments, so they are taken to be asset UIDs."""

    async def test_single_uid(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(ASSET_1)
        _, _, body = mock.call_args[0]
        assert body["assets"] == [ASSET_1]

    async def test_multiple_uids(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(f"{ASSET_1},{ASSET_2},{ASSET_3}")
        _, _, body = mock.call_args[0]
        assert body["assets"] == [ASSET_1, ASSET_2, ASSET_3]

    async def test_strips_spaces(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(f"{ASSET_1}, {ASSET_2} , {ASSET_3}")
        _, _, body = mock.call_args[0]
        assert body["assets"] == [ASSET_1, ASSET_2, ASSET_3]

    async def test_filters_empty_strings(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(f"{ASSET_1},,{ASSET_2}")
        _, _, body = mock.call_args[0]
        assert body["assets"] == [ASSET_1, ASSET_2]

    async def test_something_that_names_no_instrument_is_rejected(self):
        # Sent on, it would reach the API as an "asset UID" and come back as an empty list.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="No instrument matches 'NOPE'"):
                await srv.get_asset_fundamentals("NOPE")
        assert calls_to(mock, "GetAssetFundamentals") == []


def http_error(status_code):
    request = httpx.Request("POST", "https://invest-public-api.tbank.ru/rest")
    return httpx.HTTPStatusError(
        str(status_code), request=request, response=httpx.Response(status_code, request=request)
    )


def make_paged_call_mock(pages, asset_uids=None):
    """pages: list of (items, total_count), consumed by pageNumber index.
    asset_uids: {instrument uid: asset uid} that GetInstrumentBy knows about.

    GetConsensusForecasts has no server-side instrument filter, so
    get_consensus_forecasts scans pages itself — this mock plays back one
    page per call, keyed by the pageNumber the tool asked for. Forecasts are
    keyed by asset uid, so the tool first asks GetInstrumentBy for it; like the
    real API, the mock answers 404 for an id that is not an instrument uid.
    """
    asset_uids = asset_uids or {}

    async def router(service, method, body=None):
        if method == "GetInstrumentBy":
            if body["id"] not in asset_uids:
                raise http_error(404)
            return {"instrument": {"uid": body["id"], "assetUid": asset_uids[body["id"]]}}
        if method == "FindInstrument":
            return {"instruments": []}
        page_number = body["paging"]["pageNumber"]
        items, total_count = pages[page_number]
        return {"items": items, "page": {"totalCount": total_count}}

    return AsyncMock(side_effect=router)


def calls_to(mock, method):
    return [c[0][2] for c in mock.call_args_list if c[0][1] == method]


class TestGetConsensusForecasts:
    async def test_finds_match_on_first_page(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "asset-other"}, {"assetUid": "asset-target"}], 2),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_limit=2))
        assert result["assetUid"] == "asset-target"
        assert len(calls_to(mock, "GetConsensusForecasts")) == 1

    async def test_paginates_until_found(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "asset-other"}], 4),
            ([{"assetUid": "asset-target"}], 4),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_limit=1))
        assert result["assetUid"] == "asset-target"
        assert len(calls_to(mock, "GetConsensusForecasts")) == 2

    async def test_resolves_instrument_uid_to_asset_uid(self):
        mock = make_paged_call_mock(
            [([{"uid": "forecast-1", "assetUid": "asset-target"}], 1)],
            asset_uids={"instr-target": "asset-target"},
        )
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("instr-target"))
        assert result["assetUid"] == "asset-target"
        assert calls_to(mock, "GetInstrumentBy") == [
            {"idType": "INSTRUMENT_ID_TYPE_UID", "id": "instr-target"}
        ]

    async def test_item_uid_is_not_an_instrument_id(self):
        # An item's own "uid" identifies the forecast record; matching on it would be wrong.
        mock = make_paged_call_mock([([{"uid": "forecast-1", "assetUid": "asset-target"}], 1)])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("forecast-1"))
        assert "error" in result

    async def test_instrument_lookup_failure_is_not_swallowed(self):
        mock = AsyncMock(side_effect=http_error(401))
        with patch.object(srv, "_call", mock):
            with pytest.raises(httpx.HTTPStatusError):
                await srv.get_consensus_forecasts("instr-target")

    async def test_stops_when_exhausted_without_match(self):
        mock = make_paged_call_mock([
            ([{"assetUid": "asset-other"}], 1),
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_limit=1))
        assert "error" in result
        assert "max_pages" not in result["error"]
        assert len(calls_to(mock, "GetConsensusForecasts")) == 1

    async def test_respects_max_pages_cap(self):
        # total_count is huge, so without max_pages this would loop forever.
        mock = make_paged_call_mock([([{"assetUid": "asset-other"}], 10**6)] * 3)
        with patch.object(srv, "_call", mock):
            result = json.loads(
                await srv.get_consensus_forecasts("asset-target", page_limit=1, max_pages=3)
            )
        # A truncated scan must not read as "this instrument has no forecast".
        assert "max_pages" in result["error"]
        assert len(calls_to(mock, "GetConsensusForecasts")) == 3

    async def test_non_positive_page_limit_does_not_scan_forever(self):
        # The scan must stop once it has seen every item, not spend all max_pages requests
        # because 0 * pages never reaches the total.
        mock = make_paged_call_mock(
            [([{"assetUid": "asset-other"}] * 100, 105), ([{"assetUid": "asset-other"}] * 5, 105)]
            + [([], 105)] * 48
        )
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_limit=0))
        assert "max_pages" not in result["error"]
        assert len(calls_to(mock, "GetConsensusForecasts")) == 2
        assert calls_to(mock, "GetConsensusForecasts")[0]["paging"]["limit"] == 100

    async def test_stops_on_an_empty_page(self):
        mock = make_paged_call_mock([([{"assetUid": "asset-other"}], 10), ([], 10)])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_limit=1))
        assert "max_pages" not in result["error"]
        assert len(calls_to(mock, "GetConsensusForecasts")) == 2

    async def test_non_positive_max_pages_still_scans_one_page(self):
        mock = make_paged_call_mock([([{"assetUid": "asset-target"}], 1)])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", max_pages=0))
        assert result["assetUid"] == "asset-target"

    async def test_first_call_uses_given_page_limit(self):
        mock = make_paged_call_mock([([{"assetUid": "asset-target"}], 1)])
        with patch.object(srv, "_call", mock):
            await srv.get_consensus_forecasts("asset-target", page_limit=50)
        assert calls_to(mock, "GetConsensusForecasts") == [{"paging": {"limit": 50, "pageNumber": 0}}]


def closes(*values):
    """Daily candles, oldest first, with the given close prices."""
    return {"candles": [{"close": quotation(v)} for v in values]}


def candle(close, day, complete=True):
    """A daily candle the way the API sends it: with its date and the isComplete flag."""
    return {
        "close": quotation(close),
        "time": f"{day}T00:00:00Z",
        "isComplete": complete,
    }


def make_snapshot_call_mock(
    *,
    find_result=None,
    instrument=None,
    fundamentals=None,
    candles=None,
    consensus_items=None,
):
    """Routes _call by method name so each of get_stock_snapshot's calls (FindInstrument,
    GetInstrumentBy, GetAssetFundamentals, GetCandles, GetConsensusForecasts) gets the
    right canned response.

    The instrument uid and the asset uid are deliberately different strings, as they are
    in the real API: fundamentals and consensus are keyed by the asset uid.
    """
    find_result = find_result if find_result is not None else {
        "instruments": [
            {"uid": "instr-sber", "ticker": "SBER", "classCode": "TQBR", "name": "Сбербанк"}
        ]
    }
    instrument = instrument if instrument is not None else {
        "instrument": {"uid": "instr-sber", "assetUid": "asset-sber"}
    }
    fundamentals = fundamentals if fundamentals is not None else {
        "fundamentals": [{"peRatioTtm": 4.2}]
    }
    candles = candles if candles is not None else closes(100, 110)
    consensus_items = consensus_items if consensus_items is not None else [
        {"uid": "forecast-1", "assetUid": "asset-sber", "consensus": "RECOMMENDATION_BUY"}
    ]

    async def router(service, method, body=None):
        if method == "FindInstrument":
            return find_result
        if method == "GetInstrumentBy":
            return instrument
        if method == "GetAssetFundamentals":
            return fundamentals
        if method == "GetCandles":
            return candles
        if method == "GetConsensusForecasts":
            return {"items": consensus_items, "page": {"totalCount": len(consensus_items)}}
        raise AssertionError(f"unexpected call: {service}.{method}")

    return AsyncMock(side_effect=router)


def call_body(mock, method):
    return calls_to(mock, method)[0]


class TestGetStockSnapshot:
    async def test_combines_all_sources(self):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["ticker"] == "SBER"
        assert result["class_code"] == "TQBR"
        assert result["uid"] == "instr-sber"
        assert result["asset_uid"] == "asset-sber"
        assert result["name"] == "Сбербанк"
        assert result["fundamentals"] == {"peRatioTtm": 4.2}
        assert result["price"] == {"last_close": 110.0, "change_pct": 10.0, "change_sessions": 1}
        assert result["consensus"]["consensus"] == "RECOMMENDATION_BUY"

    async def test_searches_shares_only(self):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_stock_snapshot("SBER")
        assert call_body(mock, "FindInstrument") == {
            "query": "SBER",
            "instrumentKind": "INSTRUMENT_TYPE_SHARE",
        }

    async def test_candles_by_instrument_uid_fundamentals_by_asset_uid(self):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_stock_snapshot("SBER")
        assert call_body(mock, "GetInstrumentBy") == {
            "idType": "INSTRUMENT_ID_TYPE_UID",
            "id": "instr-sber",
        }
        assert call_body(mock, "GetAssetFundamentals") == {"assets": ["asset-sber"]}
        assert call_body(mock, "GetCandles")["instrumentId"] == "instr-sber"

    async def test_consensus_matched_by_asset_uid(self):
        mock = make_snapshot_call_mock(consensus_items=[
            {"assetUid": "asset-other", "consensus": "RECOMMENDATION_SELL"},
            {"assetUid": "asset-sber", "consensus": "RECOMMENDATION_BUY"},
        ])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["consensus"]["consensus"] == "RECOMMENDATION_BUY"

    async def test_no_consensus_reports_error_but_keeps_the_rest(self):
        mock = make_snapshot_call_mock(consensus_items=[{"assetUid": "asset-other"}])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert "error" in result["consensus"]
        assert result["fundamentals"] == {"peRatioTtm": 4.2}

    async def test_missing_asset_uid_skips_fundamentals_and_consensus(self):
        mock = make_snapshot_call_mock(instrument={"instrument": {"uid": "instr-sber"}})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["fundamentals"] == {}
        assert "error" in result["consensus"]
        assert calls_to(mock, "GetAssetFundamentals") == []
        assert calls_to(mock, "GetConsensusForecasts") == []
        assert result["price"]["last_close"] == 110.0

    async def test_prefers_exact_ticker_over_first_hit(self):
        mock = make_snapshot_call_mock(find_result={"instruments": [
            {"uid": "instr-sberp", "ticker": "SBERP", "classCode": "TQBR"},
            {"uid": "instr-sber", "ticker": "SBER", "classCode": "TQBR"},
        ]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("sber"))
        assert result["uid"] == "instr-sber"

    async def test_class_code_picks_listing(self):
        mock = make_snapshot_call_mock(find_result={"instruments": [
            {"uid": "instr-spb", "ticker": "SBER", "classCode": "SPBRU"},
            {"uid": "instr-sber", "ticker": "SBER", "classCode": "TQBR"},
        ]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER", class_code="TQBR"))
        assert result["uid"] == "instr-sber"

    async def test_different_shares_under_one_ticker_are_not_picked_between(self):
        t_tech = {"uid": "instr-t", "ticker": "T", "classCode": "TQBR", "isin": "RU000A107UL4",
                  "name": "Т-Технологии", "apiTradeAvailableFlag": True}
        att = {"uid": "instr-att", "ticker": "T", "classCode": "SPBXM", "isin": "US00206R1023",
               "name": "AT&T", "apiTradeAvailableFlag": True}
        mock = make_snapshot_call_mock(find_result={"instruments": [att, t_tech]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("T"))
            chosen = json.loads(await srv.get_stock_snapshot("T", class_code="TQBR"))
        assert "T on TQBR" in result["error"] and "T on SPBXM" in result["error"]
        assert chosen["uid"] == "instr-t"

    async def test_no_instrument_found(self):
        mock = make_snapshot_call_mock(find_result={"instruments": []})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("NOPE"))
        assert "error" in result
        assert mock.await_count == 1

    async def test_no_candles_returns_empty_price(self):
        mock = make_snapshot_call_mock(candles={"candles": []})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["price"] == {}

    async def test_change_spans_candle_days_sessions(self):
        # 2 sessions back from the last close of 120 is the close of 100, not 80 or 110.
        mock = make_snapshot_call_mock(candles=closes(80, 100, 110, 120))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER", candle_days=2))
        assert result["price"] == {"last_close": 120.0, "change_pct": 20.0, "change_sessions": 2}

    async def test_unfinished_session_is_not_a_close(self):
        # During trading hours the last daily candle is today's, still open: its "close" is
        # the price right now and must not be reported as a close or counted as a session.
        mock = make_snapshot_call_mock(candles={"candles": [
            candle(80, "2026-09-28"),
            candle(100, "2026-09-29"),
            candle(110, "2026-09-30"),
            candle(999, "2026-10-01", complete=False),
        ]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER", candle_days=1))
        assert result["price"] == {
            "last_close": 110.0,
            "last_close_date": "2026-09-30",
            "change_pct": 10.0,
            "change_sessions": 1,
            "current_price": 999.0,
        }

    async def test_no_current_price_when_last_session_is_finished(self):
        mock = make_snapshot_call_mock(candles={"candles": [
            candle(100, "2026-09-29"), candle(110, "2026-09-30"),
        ]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER", candle_days=1))
        assert result["price"] == {
            "last_close": 110.0,
            "last_close_date": "2026-09-30",
            "change_pct": 10.0,
            "change_sessions": 1,
        }

    async def test_only_an_unfinished_candle(self):
        mock = make_snapshot_call_mock(candles={"candles": [candle(105, "2026-10-01", complete=False)]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["price"] == {"current_price": 105.0}

    async def test_single_candle_reports_no_change(self):
        mock = make_snapshot_call_mock(candles=closes(100))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER", candle_days=1))
        assert result["price"] == {"last_close": 100.0}

    async def test_candle_without_close_does_not_crash(self):
        mock = make_snapshot_call_mock(candles={"candles": [
            {"close": {"units": "100", "nano": 0}},
            {},
        ]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_stock_snapshot("SBER"))
        assert result["price"] == {"last_close": None}

    @pytest.mark.parametrize("candle_days", [1, 5, 60])
    async def test_candles_window_fits_candle_days_sessions(self, candle_days):
        mock = make_snapshot_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_stock_snapshot("SBER", candle_days=candle_days)
        body = call_body(mock, "GetCandles")
        assert body["interval"] == "CANDLE_INTERVAL_DAY"
        window = srv._parse_date(body["to"]) - srv._parse_date(body["from"])
        # candle_days + 1 sessions at 5 sessions a week, plus room for a holiday week.
        assert window.days >= (candle_days + 1) * 7 / 5 + 7

    async def test_rejects_non_positive_candle_days(self):
        with pytest.raises(ValueError):
            await srv.get_stock_snapshot("SBER", candle_days=0)


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
        assert body["to"] == "2024-02-01T23:59:59Z"


class TestGetAssetReports:
    async def test_body_structure(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_asset_reports("uid123", from_date="2024-01-01", to_date="2024-12-31")
        _, _, body = mock.call_args[0]
        assert body["instrumentId"] == "uid123"
        assert body["from"] == "2024-01-01T00:00:00Z"
        assert body["to"] == "2024-12-31T23:59:59Z"


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
        assert body["to"] == "2024-02-01T23:59:59Z"
        assert body["interval"] == "CANDLE_INTERVAL_DAY"

    async def test_one_day_of_intraday_candles(self):
        # from == to used to send an empty range and get no candles back.
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_candles(
                "uid123", from_date="2024-02-01", to_date="2024-02-01", interval="CANDLE_INTERVAL_HOUR"
            )
        _, _, body = mock.call_args[0]
        assert (body["from"], body["to"]) == ("2024-02-01T00:00:00Z", "2024-02-01T23:59:59Z")

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
        # GetTechAnalysis has its own interval enum; it rejects the CANDLE_INTERVAL_* names.
        assert body["interval"] == "INDICATOR_INTERVAL_ONE_DAY"
        assert body["typeOfPrice"] == "TYPE_OF_PRICE_CLOSE"
        assert body["length"] == 14

    @pytest.mark.parametrize("indicator", ["INDICATOR_TYPE_SMA", "INDICATOR_TYPE_EMA", "INDICATOR_TYPE_RSI"])
    async def test_single_line_indicators_send_no_extra_params(self, indicator):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", indicator)
        _, _, body = mock.call_args[0]
        assert "deviation" not in body
        assert "smoothing" not in body

    async def test_bb_sends_deviation(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_BB")
        _, _, body = mock.call_args[0]
        assert body["deviation"] == {"deviationMultiplier": {"units": "2", "nano": 0}}
        assert "smoothing" not in body

    async def test_bb_custom_deviation(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_BB", length=20, deviation=2.5)
        _, _, body = mock.call_args[0]
        assert body["length"] == 20
        assert body["deviation"] == {"deviationMultiplier": {"units": "2", "nano": 500_000_000}}

    async def test_macd_sends_smoothing(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis("uid123", "INDICATOR_TYPE_MACD")
        _, _, body = mock.call_args[0]
        assert body["smoothing"] == {"fastLength": 12, "slowLength": 26, "signalSmoothing": 9}
        assert "deviation" not in body

    async def test_macd_custom_smoothing(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis(
                "uid123", "INDICATOR_TYPE_MACD", fast_length=5, slow_length=35, signal_smoothing=5,
            )
        _, _, body = mock.call_args[0]
        assert body["smoothing"] == {"fastLength": 5, "slowLength": 35, "signalSmoothing": 5}

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
            result = await srv.get_user_info()
        assert "Газпром" in result
        assert "\\u" not in result

    async def test_amounts_are_plain_numbers_in_every_tool(self):
        mock = make_call_mock({"lastPrices": [{"figi": "F", "price": {"units": "274", "nano": 270000000}}]})
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_last_prices("e6123145-9665-43e0-8413-cd61b8aa9b13"))
        assert result == {"lastPrices": [{"figi": "F", "price": 274.27}]}


# ── Instrument identifiers ────────────────────────────────────────────────────


def search_results(*by_flag):
    """FindInstrument answer that honours apiTradeAvailableFlag the way the API does."""
    def answer(body):
        hits = [i for i in by_flag if i.get("apiTradeAvailableFlag") or not body.get("apiTradeAvailableFlag")]
        return {"instruments": hits}
    return answer


class TestInstrumentResolution:
    async def test_uid_is_taken_as_is_without_a_lookup(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            assert await srv._uid(SBER["uid"]) == SBER["uid"]
        mock.assert_not_called()

    @pytest.mark.parametrize("identifier", ["SBER", "sber", " SBER ", "RU0009029540"])
    async def test_ticker_and_isin_resolve_to_the_uid(self, identifier):
        mock = route(FindInstrument=search_results(SBER, SBERP, SBER_OTC))
        with patch.object(srv, "_call", mock):
            assert await srv._uid(identifier) == SBER["uid"]

    @pytest.mark.parametrize("figi", ["BBG004730N88", "TCS00A10DA74"])
    async def test_figi_goes_through_where_the_api_takes_one(self, figi):
        # A portfolio's worth of FIGIs in get_last_prices must stay one request, not one each.
        mock = route()
        with patch.object(srv, "_call", mock):
            assert await srv._uid(figi) == figi
        mock.assert_not_called()

    async def test_figi_is_resolved_for_uid_only_methods(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("BBG004730N88", figi_ok=False) == SBER["uid"]
            await srv.get_tech_analysis("BBG004730N88", "INDICATOR_TYPE_RSI")
            await srv.get_forecast_by("BBG004730N88")
        assert call_body(mock, "GetTechAnalysis")["instrumentUid"] == SBER["uid"]
        assert call_body(mock, "GetForecastBy")["instrumentId"] == SBER["uid"]

    @pytest.mark.parametrize("not_a_figi", ["RU0009029540", "SU26238RMFS4", "RU000A10DA74"])
    async def test_isin_and_twelve_character_tickers_are_not_taken_for_figis(self, not_a_figi):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv._uid(not_a_figi)
        assert calls_to(mock, "FindInstrument") != []

    async def test_a_miss_is_forgotten_after_a_while(self, monkeypatch):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv._uid("NEWCO")
            monkeypatch.setattr(srv, "MISS_TTL_SECONDS", 0)
            await srv._uid("NEWCO")
        assert len(calls_to(mock, "FindInstrument")) == 2  # searched again the second time

    async def test_a_name_is_rejected_here_rather_than_sent_to_the_api(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="find_instrument searches by name"):
                await srv.get_candles("Сбербанк")
            with pytest.raises(ValueError, match="find_instrument"):
                await srv.get_candles("Sber Bank")
        assert calls_to(mock, "GetCandles") == []

    async def test_listing_with_candle_history_is_the_papers_real_board(self):
        # A fund: four listings of one ISIN, none tradable through the API, one with history.
        boards = [{**SBER_OTC, "classCode": c, "uid": f"{n}0000000-2222-3333-4444-555555555555"}
                  for n, c in enumerate(("PTTF", "TQBR", "PTEQ", "TQTF"), start=1)]
        boards[1]["first1dayCandleDate"] = "2020-08-26T00:00:00Z"
        mock = route(FindInstrument=search_results(*boards))
        with patch.object(srv, "_call", mock):
            await srv.get_candles("SBER")
            await srv.get_dividends("SBER")
        assert call_body(mock, "GetCandles")["instrumentId"] == boards[1]["uid"]
        assert call_body(mock, "GetDividends")["instrumentId"] == boards[1]["uid"]

    async def test_listings_of_one_paper_are_not_an_ambiguity_for_asset_level_tools(self):
        boards = [{**SBER, "classCode": c, "uid": f"{n}0000000-2222-3333-4444-555555555555"}
                  for n, c in enumerate(("TQTF", "PTTF", "TQBR"), start=1)]
        mock = route(FindInstrument=search_results(*boards))
        with patch.object(srv, "_call", mock):
            await srv.get_dividends("SBER")
            with pytest.raises(ValueError, match="SBER_TQTF"):
                await srv.get_candles("SBER")  # prices do depend on the board
        assert call_body(mock, "GetDividends")["instrumentId"] == boards[0]["uid"]

    async def test_different_papers_under_one_ticker_stay_an_ambiguity(self):
        att = {**SBER, "classCode": "SPBXM", "isin": "US00206R1023", "name": "AT&T",
               "uid": "99999999-2222-3333-4444-555555555555"}
        mock = route(FindInstrument=search_results(SBER, att))
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="names 2 instruments"):
                await srv.get_dividends("SBER")

    async def test_a_long_list_is_looked_up_a_few_at_a_time_and_each_name_once(self):
        running = peak = 0

        async def find(service, method, body=None):
            nonlocal running, peak
            if method == "FindInstrument":
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0)
                running -= 1
            return {}

        tickers = [f"T{n}" for n in range(30)]
        with patch.object(srv, "_call", AsyncMock(side_effect=find)) as mock:
            await srv.get_last_prices(",".join(tickers + tickers))
        assert peak <= srv.LOOKUP_BATCH
        assert len({b["query"] for b in calls_to(mock, "FindInstrument")}) == 30
        assert len(calls_to(mock, "FindInstrument")) == 60  # short names: tradable, then all, once each
        assert len(call_body(mock, "GetLastPrices")["instrumentId"]) == 60

    async def test_only_exact_matches_count(self):
        # "SBER" also finds SBERP and every Sber bond; a name is not an identifier.
        mock = route(FindInstrument=search_results(SBERP))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("SBER") == "SBER"

    async def test_tradable_listing_is_preferred(self):
        mock = route(FindInstrument=search_results(SBER_OTC, SBER))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("SBER") == SBER["uid"]
        # One search, and not limited to tradable listings: see the next tests for why.
        assert calls_to(mock, "FindInstrument") == [{"query": "SBER"}]

    async def test_falls_back_to_non_tradable_listings(self):
        mock = route(FindInstrument=search_results(SBER_OTC))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("SBER") == SBER_OTC["uid"]

    async def test_a_tradable_paper_does_not_hide_another_one_under_the_same_ticker(self):
        # Real case: TECH is a foreign share tradable through the API and a Russian fund
        # that is not. Looking among tradable listings alone found only the share, and a
        # holder of the fund silently got the prices and dividends of another company.
        share = {**SBER, "ticker": "TECH", "classCode": "SPBXM", "isin": "US09073M1045",
                 "name": "Bio-Techne", "uid": "11111111-aaaa-bbbb-cccc-000000000001"}
        fund = {**SBER_OTC, "ticker": "TECH", "classCode": "TQBR", "isin": "RU000A101X68",
                "name": "Технологии Америки", "instrumentType": "etf",
                "first1dayCandleDate": "2020-08-26T00:00:00Z",
                "uid": "11111111-aaaa-bbbb-cccc-000000000002"}
        fund_board = {**fund, "classCode": "TQTF", "uid": "11111111-aaaa-bbbb-cccc-000000000003"}
        del fund_board["first1dayCandleDate"]
        mock = route(FindInstrument=search_results(share, fund_board, fund))
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError) as exc_info:
                await srv.get_dividends("TECH")
            assert await srv._uid("TECH_TQBR") == fund["uid"]
        message = str(exc_info.value)
        assert "TECH_SPBXM" in message and "TECH_TQBR" in message
        assert "TECH_TQTF" not in message  # one line per paper, not per board

    async def test_a_dead_record_of_another_paper_is_not_an_ambiguity(self):
        # Real case: ASTR also finds a delisted "Astra Space" on a technical board — not
        # tradable, no candle history. It must not turn the live share into a question.
        dead = {**SBER_OTC, "classCode": "FAKE_BEB", "isin": "US04634X2027", "name": "Astra Space",
                "uid": "22222222-aaaa-bbbb-cccc-000000000001"}
        mock = route(FindInstrument=search_results(dead, SBER))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("SBER") == SBER["uid"]

    async def test_a_short_generic_query_is_not_searched_in_full(self):
        # "T" matches tens of thousands of listings: the full search is megabytes the API
        # does not manage to send. Its tradable matches are all that can be had.
        t_share = {**SBER, "ticker": "T"}
        noise = [{**SBERP, "uid": f"{n:08d}-aaaa-bbbb-cccc-000000000000"} for n in range(srv.GENERIC_QUERY_HITS)]
        mock = route(FindInstrument=search_results(t_share, *noise))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("T") == SBER["uid"]
        assert calls_to(mock, "FindInstrument") == [{"query": "T", "apiTradeAvailableFlag": True}]

    async def test_a_short_specific_query_is_searched_in_full_as_well(self):
        x5 = {**SBER, "ticker": "X5"}
        mock = route(FindInstrument=search_results(x5))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("X5") == SBER["uid"]
        assert calls_to(mock, "FindInstrument") == [{"query": "X5", "apiTradeAvailableFlag": True}, {"query": "X5"}]

    async def test_several_matches_are_reported_not_guessed(self):
        other_board = {**SBER, "classCode": "SMAL", "uid": "99999999-2222-3333-4444-555555555555"}
        mock = route(FindInstrument=search_results(SBER, other_board))
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError) as exc_info:
                await srv._uid("SBER")
        message = str(exc_info.value)
        assert "SBER_TQBR" in message and "SBER_SMAL" in message
        assert "UID" in message

    async def test_ticker_with_class_code_picks_a_listing(self):
        other_board = {**SBER, "classCode": "SMAL", "uid": "99999999-2222-3333-4444-555555555555"}

        def answer(body):
            return {"instruments": [SBER, other_board] if body["query"] == "SBER" else []}

        mock = route(FindInstrument=answer)
        with patch.object(srv, "_call", mock):
            assert await srv._uid("SBER_SMAL") == other_board["uid"]

    async def test_ticker_that_contains_an_underscore(self):
        cny = {"ticker": "CNYRUB_TOM", "classCode": "CETS", "uid": "4587ab1d-a9c9-4910-a0d6-86c7b9c42510",
               "figi": "BBG0013HRTL0", "isin": "", "apiTradeAvailableFlag": True}
        mock = route(FindInstrument=search_results(cny))
        with patch.object(srv, "_call", mock):
            assert await srv._uid("CNYRUB_TOM") == cny["uid"]

    async def test_unknown_identifier_is_passed_through(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            assert await srv._uid("NOPE") == "NOPE"

    async def test_lookups_are_cached_including_misses(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv._uid("SBER")
            await srv._uid("sber")
            await srv._uid("NOPE")
            await srv._uid("NOPE")
        queries = [b["query"] for b in calls_to(mock, "FindInstrument")]
        assert queries == ["SBER", "NOPE"]  # a hit and a miss, each asked about once

    async def test_kind_narrows_the_search(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv._uid("SBER", "share")
        assert calls_to(mock, "FindInstrument")[0] == {
            "query": "SBER", "instrumentKind": "INSTRUMENT_TYPE_SHARE",
        }

    @pytest.mark.parametrize("call, method, key", [
        (lambda: srv.get_candles("SBER"), "GetCandles", "instrumentId"),
        (lambda: srv.get_order_book("SBER"), "GetOrderBook", "instrumentId"),
        (lambda: srv.get_trading_status("SBER"), "GetTradingStatus", "instrumentId"),
        (lambda: srv.get_dividends("SBER"), "GetDividends", "instrumentId"),
        (lambda: srv.get_forecast_by("SBER"), "GetForecastBy", "instrumentId"),
        (lambda: srv.get_asset_reports("SBER"), "GetAssetReports", "instrumentId"),
        (lambda: srv.get_tech_analysis("SBER", "RSI"), "GetTechAnalysis", "instrumentUid"),
        (lambda: srv.get_operations_by_cursor("acc", instrument_id="SBER"), "GetOperationsByCursor", "instrumentId"),
    ])
    async def test_tools_accept_a_ticker(self, call, method, key):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await call()
        assert call_body(mock, method)[key] == SBER["uid"]

    async def test_lists_of_identifiers(self):
        mock = route(FindInstrument=lambda body: {"instruments": [i for i in (SBER, SBERP) if i["ticker"] == body["query"]]})
        with patch.object(srv, "_call", mock):
            await srv.get_last_prices(f"SBER, {SBERP['uid']},SBERP")
            await srv.get_close_prices("SBER,SBERP")
        assert call_body(mock, "GetLastPrices") == {"instrumentId": [SBER["uid"], SBERP["uid"], SBERP["uid"]]}
        assert call_body(mock, "GetClosePrices") == {
            "instruments": [{"instrumentId": SBER["uid"]}, {"instrumentId": SBERP["uid"]}],
        }

    async def test_operations_figi_filter_takes_any_identifier(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv.get_operations("acc", figi="SBER")
        assert call_body(mock, "GetOperations")["figi"] == "BBG004730N88"

    async def test_bond_tools_search_among_bonds(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_events("SU26238RMFS4")
        assert calls_to(mock, "FindInstrument")[0]["instrumentKind"] == "INSTRUMENT_TYPE_BOND"


class TestInstrumentRef:
    """How the *By tools tell the API which instrument is meant."""

    async def test_uid_is_recognised_by_its_shape(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_instrument_by(SBER["uid"])
        assert call_body(mock, "GetInstrumentBy") == {"idType": "INSTRUMENT_ID_TYPE_UID", "id": SBER["uid"]}
        assert calls_to(mock, "FindInstrument") == []

    async def test_ticker_is_looked_up_among_the_tools_kind(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv.get_share_by("SBER")
        assert calls_to(mock, "FindInstrument")[0]["instrumentKind"] == "INSTRUMENT_TYPE_SHARE"
        assert call_body(mock, "ShareBy") == {"idType": "INSTRUMENT_ID_TYPE_UID", "id": SBER["uid"]}

    async def test_class_code_means_a_ticker_even_with_the_default_id_type(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_share_by("SBER", class_code="TQBR")
        assert call_body(mock, "ShareBy") == {
            "idType": "INSTRUMENT_ID_TYPE_TICKER", "id": "SBER", "classCode": "TQBR",
        }
        assert calls_to(mock, "FindInstrument") == []

    async def test_explicit_uid_type_is_not_looked_up(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_by("anything", id_type="INSTRUMENT_ID_TYPE_UID")
        assert call_body(mock, "BondBy") == {"idType": "INSTRUMENT_ID_TYPE_UID", "id": "anything"}
        assert calls_to(mock, "FindInstrument") == []

    async def test_short_id_type_name(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_bond_by("anything", id_type="uid")
        assert call_body(mock, "BondBy")["idType"] == "INSTRUMENT_ID_TYPE_UID"

    async def test_figi_goes_to_the_api_without_a_lookup(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_etf_by("BBG000000001")
        assert call_body(mock, "EtfBy") == {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": "BBG000000001"}
        assert calls_to(mock, "FindInstrument") == []

    async def test_unknown_identifier_goes_to_the_api_as_before(self):
        mock = route()
        with patch.object(srv, "_call", mock):
            await srv.get_etf_by("RU000A0JX0J2")
        assert call_body(mock, "EtfBy") == {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": "RU000A0JX0J2"}

    async def test_a_name_is_an_error(self):
        with patch.object(srv, "_call", route()):
            with pytest.raises(ValueError, match="find_instrument"):
                await srv.get_share_by("Сбербанк")


class TestFindInstrumentShaping:
    async def test_searches_tradable_listings_by_default(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv.find_instrument("SBER")
        assert calls_to(mock, "FindInstrument") == [{"query": "SBER", "apiTradeAvailableFlag": True}]

    async def test_kind_filter(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            await srv.find_instrument("Сбер", instrument_kind="share")
        assert calls_to(mock, "FindInstrument")[0]["instrumentKind"] == "INSTRUMENT_TYPE_SHARE"

    async def test_unknown_kind_is_rejected(self):
        with patch.object(srv, "_call", route()):
            with pytest.raises(ValueError, match="SHARE, BOND"):
                await srv.find_instrument("Сбер", instrument_kind="stock")

    async def test_instruments_keep_only_what_identifies_them(self):
        mock = route(FindInstrument=search_results(SBER))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("SBER"))
        assert result == {"total": 1, "instruments": [{
            "ticker": "SBER", "classCode": "TQBR", "name": "Сбер Банк", "instrumentType": "share",
            "uid": SBER["uid"], "figi": "BBG004730N88", "isin": "RU0009029540", "lot": 1,
        }]}

    async def test_exact_match_comes_first(self):
        mock = route(FindInstrument=search_results(SBERP, SBER))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("sber"))
        assert [i["ticker"] for i in result["instruments"]] == ["SBER", "SBERP"]

    async def test_non_tradable_listings_on_request(self):
        mock = route(FindInstrument=search_results(SBER, SBER_OTC))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("SBER", tradable_only=False))
        assert calls_to(mock, "FindInstrument") == [{"query": "SBER"}]
        assert [i.get("apiTradeAvailableFlag") for i in result["instruments"]] == [None, False]

    async def test_falls_back_to_non_tradable_and_says_so(self):
        mock = route(FindInstrument=search_results(SBER_OTC))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("SBER"))
        assert result["total"] == 1
        assert result["instruments"][0]["apiTradeAvailableFlag"] is False
        assert "not tradable" in result["note"]

    async def test_qualified_investor_flag_shown_when_set(self):
        mock = route(FindInstrument=search_results({**SBER, "forQualInvestorFlag": True}))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("SBER"))
        assert result["instruments"][0]["forQualInvestorFlag"] is True

    async def test_both_notes_survive_together(self):
        many = [{**SBER_OTC, "ticker": f"T{n}", "uid": f"uid-{n}"} for n in range(30)]
        mock = route(FindInstrument=search_results(*many))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("Сбер", limit=5))
        assert "not tradable" in result["note"]
        assert "5 of 30" in result["note"]

    async def test_limit_cuts_the_list_and_says_so(self):
        many = [{**SBER, "ticker": f"T{n}", "uid": f"uid-{n}"} for n in range(30)]
        mock = route(FindInstrument=search_results(*many))
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.find_instrument("Сбер", limit=5))
        assert len(result["instruments"]) == 5
        assert result["total"] == 30
        assert "5 of 30" in result["note"]

    async def test_nothing_found(self):
        with patch.object(srv, "_call", route()):
            result = json.loads(await srv.find_instrument("NOPE"))
        assert result == {"instruments": [], "total": 0}


# ── Output shaping ────────────────────────────────────────────────────────────


def money(units, nano=0, currency="rub"):
    return {"currency": currency, "units": str(units), "nano": nano}


def quotation(units, nano=0):
    return {"units": str(units), "nano": nano}


PORTFOLIO = {
    "accountId": "acc1",
    "totalAmountShares": money(150000),
    "totalAmountBonds": money(0),
    "totalAmountPortfolio": money(150000, 500000000),
    "expectedYield": quotation(3, 250000000),
    "positions": [{
        "figi": "BBG004730N88", "instrumentType": "share", "ticker": "SBER", "classCode": "TQBR",
        "instrumentUid": SBER["uid"], "positionUid": SBER["positionUid"],
        "quantity": quotation(100), "quantityLots": quotation(100),
        "averagePositionPrice": money(270, 100000000), "averagePositionPriceFifo": money(269),
        "averagePositionPricePt": quotation(0), "currentPrice": money(274, 270000000),
        "currentNkd": money(0), "expectedYield": quotation(417), "expectedYieldFifo": quotation(527),
        "dailyYield": money(-35), "blocked": False, "blockedLots": quotation(0),
        "varMargin": money(0, currency=""), "varMarginSettled": money(0, currency=""),
    }],
    "virtualPositions": [],
}


class TestPortfolioShaping:
    async def test_amounts_are_numbers_with_one_currency_per_object(self):
        with patch.object(srv, "_call", make_call_mock(PORTFOLIO)):
            result = json.loads(await srv.get_portfolio("acc1"))
        assert result["currency"] == "rub"
        assert result["totalAmountPortfolio"] == 150000.5
        assert result["totalAmountBonds"] == 0  # totals are kept even when zero
        assert result["expectedYield"] == 3.25

    async def test_position_drops_zero_false_and_deprecated_fields(self):
        with patch.object(srv, "_call", make_call_mock(PORTFOLIO)):
            result = json.loads(await srv.get_portfolio("acc1"))
        assert result["positions"] == [{
            "currency": "rub",
            "figi": "BBG004730N88", "instrumentType": "share", "ticker": "SBER", "classCode": "TQBR",
            "instrumentUid": SBER["uid"], "positionUid": SBER["positionUid"],
            "quantity": 100,
            "averagePositionPrice": 270.1, "averagePositionPriceFifo": 269,
            "currentPrice": 274.27,
            "expectedYield": 417, "expectedYieldFifo": 527,
            "dailyYield": -35,
        }]

    async def test_real_sized_portfolio_is_several_times_smaller(self):
        big = {**PORTFOLIO, "positions": PORTFOLIO["positions"] * 100}
        with patch.object(srv, "_call", make_call_mock(big)):
            result = await srv.get_portfolio("acc1")
        raw = json.dumps(big, ensure_ascii=False, separators=(",", ":"))
        assert len(result) < len(raw) / 2

    async def test_positions_trimmed(self):
        data = {
            "money": [money(1500, 500000000), money(20, currency="usd")],
            "blocked": [],
            "securities": [{"figi": "F", "blocked": "0", "balance": "10", "exchangeBlocked": False,
                            "instrumentType": "share", "ticker": "SBER", "positionUid": "p-1",
                            "instrumentUid": "i-1"}],
            "limitsLoadingInProgress": False,
            "futures": [], "options": [], "accountId": "acc1",
        }
        with patch.object(srv, "_call", make_call_mock(data)):
            result = json.loads(await srv.get_positions("acc1"))
        assert result["money"] == [{"value": 1500.5, "currency": "rub"}, {"value": 20, "currency": "usd"}]
        # positionUid stays: it is the key of the position, not another name of the instrument
        assert result["securities"] == [
            {"figi": "F", "balance": "10", "instrumentType": "share", "ticker": "SBER",
             "positionUid": "p-1", "instrumentUid": "i-1"},
        ]
        assert result["limitsLoadingInProgress"] is False  # only list items are trimmed

    async def test_operations_by_cursor_trimmed(self):
        # An item the way GetOperationsByCursor sends it: `type` is the code.
        item = {"id": "1", "type": "OPERATION_TYPE_BUY", "payment": money(-27410), "price": money(274, 100000000),
                "commission": money(-13, -700000000), "yield": money(0), "accruedInt": money(0),
                "yieldRelative": quotation(0), "quantity": "100", "quantityDone": "100", "quantityRest": "0",
                "cancelReason": "", "tradesInfo": {"trades": []}, "childOperations": [],
                "positionUid": "p-1", "instrumentUid": "i-1", "instrumentType": "share",
                # what the request or another field already says
                "cursor": "c-1", "brokerAccountId": "acc1", "instrumentKind": "INSTRUMENT_TYPE_SHARE",
                "assetUid": "a-1"}
        with patch.object(srv, "_call", make_call_mock({"hasNext": False, "nextCursor": "", "items": [item]})):
            result = json.loads(await srv.get_operations_by_cursor("acc1"))
        assert result["items"] == [{
            "currency": "rub", "id": "1", "type": "OPERATION_TYPE_BUY", "payment": -27410, "price": 274.1,
            "commission": -13.7, "quantity": "100", "quantityDone": "100", "tradesInfo": {"trades": []},
            "positionUid": "p-1", "instrumentUid": "i-1", "instrumentType": "share",
        }]

    async def test_operations_trimmed(self):
        # GetOperations names things differently: `type` is a description in Russian, and
        # the code is in operationType — which therefore is not a repeat to drop.
        item = {"id": "1", "type": "Покупка ценных бумаг", "operationType": "OPERATION_TYPE_BUY",
                "state": "OPERATION_STATE_EXECUTED", "payment": money(-27410), "price": money(274, 100000000),
                "currency": "rub", "quantity": "100", "quantityRest": "0", "parentOperationId": "",
                "figi": "BBG004730N88", "instrumentType": "share", "trades": [], "childOperations": [],
                "instrumentUid": "i-1", "positionUid": "p-1", "assetUid": "a-1"}
        with patch.object(srv, "_call", make_call_mock({"operations": [item]})):
            result = json.loads(await srv.get_operations("acc1"))
        assert result["operations"] == [{
            "id": "1", "type": "Покупка ценных бумаг", "operationType": "OPERATION_TYPE_BUY",
            "state": "OPERATION_STATE_EXECUTED", "payment": -27410, "price": 274.1, "currency": "rub",
            "quantity": "100", "figi": "BBG004730N88", "instrumentType": "share",
            "instrumentUid": "i-1", "positionUid": "p-1",
        }]

    async def test_operations_page_defaults_to_fifty(self):
        # A hundred real operations is more than a client lets through.
        mock = make_call_mock({"items": []})
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1")
        assert mock.call_args[0][2]["limit"] == 50

    async def test_bond_events_trimmed(self):
        event = {"instrumentId": "uid", "eventNumber": 12, "eventDate": "2026-12-02T00:00:00Z",
                 "eventType": "EVENT_TYPE_CPN", "eventTotalVol": quotation(0), "payOneBond": money(35, 400000000),
                 "couponInterestRate": quotation(7, 100000000), "note": "", "convertToFinToolId": ""}
        with patch.object(srv, "_call", make_call_mock({"events": [event]})):
            result = json.loads(await srv.get_bond_events(SBER["uid"]))
        assert result == {"events": [{
            "currency": "rub", "instrumentId": "uid", "eventNumber": 12, "eventDate": "2026-12-02T00:00:00Z",
            "eventType": "EVENT_TYPE_CPN", "payOneBond": 35.4, "couponInterestRate": 7.1,
        }]}


def raw_candle(time, o, h, l, c, volume, complete=True):
    return {"time": time, "open": quotation(o), "high": quotation(h), "low": quotation(l),
            "close": quotation(c, 500000000), "volume": str(volume), "isComplete": complete,
            "candleSource": "CANDLE_SOURCE_EXCHANGE"}


class TestCandleRows:
    async def test_daily_candles_as_rows_with_dates(self):
        data = {"candles": [raw_candle("2026-09-29T00:00:00Z", 270, 275, 269, 273, 1000),
                            raw_candle("2026-09-30T00:00:00Z", 273, 276, 272, 274, 2000)]}
        with patch.object(srv, "_call", make_call_mock(data)):
            result = json.loads(await srv.get_candles(SBER["uid"]))
        assert result == {
            "columns": ["time", "open", "high", "low", "close", "volume"],
            "candles": [["2026-09-29", 270, 275, 269, 273.5, 1000], ["2026-09-30", 273, 276, 272, 274.5, 2000]],
        }

    async def test_buy_and_sell_volume_columns_when_the_api_has_them(self):
        candle = {**raw_candle("2026-09-30T00:00:00Z", 273, 276, 272, 274, 2000), "volumeBuy": "1200", "volumeSell": "800"}
        partial = raw_candle("2026-10-01T00:00:00Z", 274, 275, 273, 274, 500)
        with patch.object(srv, "_call", make_call_mock({"candles": [candle, partial]})):
            result = json.loads(await srv.get_candles(SBER["uid"]))
        assert result["columns"] == ["time", "open", "high", "low", "close", "volume", "volumeBuy", "volumeSell"]
        assert result["candles"] == [
            ["2026-09-30", 273, 276, 272, 274.5, 2000, 1200, 800],
            ["2026-10-01", 274, 275, 273, 274.5, 500, None, None],
        ]

    async def test_intraday_candles_keep_the_time(self):
        data = {"candles": [raw_candle("2026-09-30T07:00:00Z", 270, 275, 269, 273, 1000)]}
        with patch.object(srv, "_call", make_call_mock(data)):
            result = json.loads(await srv.get_candles(SBER["uid"], interval="CANDLE_INTERVAL_HOUR"))
        assert result["candles"][0][0] == "2026-09-30T07:00:00Z"

    async def test_unfinished_last_candle_is_flagged(self):
        data = {"candles": [raw_candle("2026-09-30T00:00:00Z", 270, 275, 269, 273, 1000),
                            raw_candle("2026-10-01T00:00:00Z", 273, 276, 272, 274, 50, complete=False)]}
        with patch.object(srv, "_call", make_call_mock(data)):
            result = json.loads(await srv.get_candles(SBER["uid"]))
        assert result["last_candle_complete"] is False
        assert len(result["candles"]) == 2

    async def test_no_candles(self):
        with patch.object(srv, "_call", make_call_mock({"candles": []})):
            result = json.loads(await srv.get_candles(SBER["uid"]))
        assert result["candles"] == []
        assert "last_candle_complete" not in result

    async def test_candle_with_a_missing_price(self):
        with patch.object(srv, "_call", make_call_mock({"candles": [{"time": "2026-09-30T00:00:00Z"}]})):
            result = json.loads(await srv.get_candles(SBER["uid"]))
        assert result["candles"] == [["2026-09-30", None, None, None, None, 0]]

    @pytest.mark.parametrize("given", ["DAY", "day", "CANDLE_INTERVAL_DAY"])
    async def test_interval_prefix_is_optional(self, given):
        mock = make_call_mock({"candles": []})
        with patch.object(srv, "_call", mock):
            await srv.get_candles(SBER["uid"], interval=given)
        assert mock.call_args[0][2]["interval"] == "CANDLE_INTERVAL_DAY"

    async def test_a_year_of_candles_is_several_times_smaller(self):
        data = {"candles": [raw_candle(f"2026-01-{d % 28 + 1:02}T00:00:00Z", 270, 275, 269, 273, 874332) for d in range(250)]}
        with patch.object(srv, "_call", make_call_mock(data)):
            result = await srv.get_candles(SBER["uid"])
        assert len(result) < len(json.dumps(data, separators=(",", ":"))) / 4


class TestAssetFundamentalsIdentifiers:
    async def test_ticker_and_instrument_uid_become_asset_uids(self):
        instrument_uid = "aaaaaaaa-1111-2222-3333-444444444444"
        asset_of = {SBER["uid"]: "asset-sber", instrument_uid: "asset-other"}

        def by_uid(body):
            if body["id"] not in asset_of:
                raise http_error(404)
            return {"instrument": {"assetUid": asset_of[body["id"]]}}

        mock = route(FindInstrument=search_results(SBER), GetInstrumentBy=by_uid)
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(f"SBER, {instrument_uid}")
        assert call_body(mock, "GetAssetFundamentals") == {"assets": ["asset-sber", "asset-other"]}

    async def test_asset_of_an_instrument_is_asked_for_once(self):
        mock = route(FindInstrument=search_results(SBER),
                     GetInstrumentBy={"instrument": {"assetUid": ASSET_1}})
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals("SBER")
            await srv.get_asset_fundamentals("SBER")
            await srv.get_consensus_forecasts("SBER")
        assert len(calls_to(mock, "GetInstrumentBy")) == 1

    async def test_asset_uid_is_kept(self):
        asset_uid = "40d89385-a03a-4659-bf4e-d3ecba011782"

        def not_an_instrument(body):
            raise http_error(404)

        mock = route(GetInstrumentBy=not_an_instrument)
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(asset_uid)
        assert call_body(mock, "GetAssetFundamentals") == {"assets": [asset_uid]}

    async def test_an_asset_uid_is_asked_about_once(self):
        asset_uid = "40d89385-a03a-4659-bf4e-d3ecba011782"

        def not_an_instrument(body):
            raise http_error(404)

        mock = route(GetInstrumentBy=not_an_instrument)
        with patch.object(srv, "_call", mock):
            await srv.get_asset_fundamentals(asset_uid)
            await srv.get_asset_fundamentals(asset_uid)
        assert len(calls_to(mock, "GetInstrumentBy")) == 1


class TestTechAnalysisNames:
    @pytest.mark.parametrize("given, sent", [
        ("CANDLE_INTERVAL_DAY", "INDICATOR_INTERVAL_ONE_DAY"),
        ("CANDLE_INTERVAL_HOUR", "INDICATOR_INTERVAL_ONE_HOUR"),
        ("day", "INDICATOR_INTERVAL_ONE_DAY"),
        ("ONE_DAY", "INDICATOR_INTERVAL_ONE_DAY"),
        ("INDICATOR_INTERVAL_WEEK", "INDICATOR_INTERVAL_WEEK"),
    ])
    async def test_candle_interval_names_are_translated(self, given, sent):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis(SBER["uid"], "INDICATOR_TYPE_RSI", interval=given)
        assert mock.call_args[0][2]["interval"] == sent

    async def test_short_indicator_and_price_names(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.get_tech_analysis(SBER["uid"], "bb", type_of_price="open")
        body = mock.call_args[0][2]
        assert body["indicatorType"] == "INDICATOR_TYPE_BB"
        assert body["typeOfPrice"] == "TYPE_OF_PRICE_OPEN"
        assert "deviation" in body  # the BB-only field follows the normalised name


class TestInstrumentListStatus:
    async def test_short_status_name(self):
        mock = make_call_mock()
        with patch.object(srv, "_call", mock):
            await srv.list_shares("all")
        assert mock.call_args[0][2] == {"instrumentStatus": "INSTRUMENT_STATUS_ALL"}


class TestSilentlyWrongAnswers:
    """Things the API answers without complaint and with the wrong data; the server must not."""

    @pytest.mark.parametrize("types", ["DIVIDENDS", "FOO", "COUPON,FOO"])
    async def test_unknown_operation_type_is_rejected(self, types):
        # The API ignores a type it does not know and returns every operation of the period.
        mock = make_call_mock({"items": []})
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="Unknown value"):
                await srv.get_operations_by_cursor("acc1", operation_types=types)
        mock.assert_not_called()

    @pytest.mark.parametrize("known", ["INP_MULTI", "DIV_EXT", "OPERATION_TYPE_BOND_REPAYMENT_FULL", "coupon"])
    async def test_real_operation_types_pass(self, known):
        mock = make_call_mock({"items": []})
        with patch.object(srv, "_call", mock):
            await srv.get_operations_by_cursor("acc1", operation_types=known)
        assert mock.call_args[0][2]["operationTypes"] == [
            "OPERATION_TYPE_" + known.upper().removeprefix("OPERATION_TYPE_")
        ]

    async def test_operations_cut_off_by_the_api_say_so(self):
        operations = [{"id": str(n), "date": f"2026-{1 + n % 9:02d}-15T10:00:00Z"} for n in range(1000)]
        with patch.object(srv, "_call", make_call_mock({"operations": operations})):
            text = await srv.get_operations("acc1", from_date="2025-10-01", to_date="2026-09-30")
        result = json.loads(text)
        assert text.startswith('{"note":')  # first, so that it is read even from a saved file
        assert "at most 1000" in result["note"] and "before 2026-01-15T10:00:00Z" in result["note"]
        assert len(result["operations"]) == 1000

    async def test_a_complete_list_of_operations_has_no_note(self):
        with patch.object(srv, "_call", make_call_mock({"operations": [{"id": "1"}] * 999})):
            assert "note" not in json.loads(await srv.get_operations("acc1"))

    @pytest.mark.parametrize("tool", [srv.get_last_prices, srv.get_close_prices, srv.get_asset_fundamentals])
    @pytest.mark.parametrize("empty", ["", " ", ",", " , "])
    async def test_an_empty_list_is_not_a_request_for_the_whole_market(self, tool, empty):
        mock = route()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="name at least one instrument"):
                await tool(empty)
        mock.assert_not_called()

    async def test_unknown_identifier_in_a_price_list_is_named(self):
        # The API answers it with a record whose every field is empty, in its place in the list.
        stub = {"figi": "", "ticker": "", "classCode": "", "instrumentUid": "", "lastPriceType": "LAST_PRICE_UNSPECIFIED"}
        price = {"figi": "BBG004730N88", "ticker": "SBER", "instrumentUid": SBER["uid"], "price": quotation(274)}
        mock = route(FindInstrument=search_results(SBER), GetLastPrices={"lastPrices": [price, stub]},
                     GetClosePrices={"closePrices": [{"figi": "", "instrumentUid": ""}, price]})
        with patch.object(srv, "_call", mock):
            last = json.loads(await srv.get_last_prices("SBER, NOPE123"))
            close = json.loads(await srv.get_close_prices("NOPE123,SBER"))
        assert last["lastPrices"][0]["price"] == 274
        assert last["lastPrices"][1] == {"requested": "NOPE123", "error": "No instrument matches this identifier"}
        assert close["closePrices"][0]["requested"] == "NOPE123"
        assert close["closePrices"][1]["ticker"] == "SBER"

    @pytest.mark.parametrize("call", [
        lambda: srv.list_currencies("FOO"),
        lambda: srv.get_candles(SBER["uid"], interval="CANDLE_INTERVAL_FORTNIGHT"),
        lambda: srv.get_tech_analysis(SBER["uid"], "INDICATOR_TYPE_MA"),
        lambda: srv.get_tech_analysis(SBER["uid"], "INDICATOR_TYPE_RSI", interval="FORTNIGHT"),
        lambda: srv.get_tech_analysis(SBER["uid"], "INDICATOR_TYPE_RSI", type_of_price="MEDIAN"),
    ])
    async def test_unknown_enum_values_are_rejected(self, call):
        mock = route()
        with patch.object(srv, "_call", mock):
            with pytest.raises(ValueError, match="Unknown value"):
                await call()
        mock.assert_not_called()


class TestFindInstrumentOrder:
    async def test_shares_come_before_the_bonds_a_company_name_also_matches(self):
        # Real case: "Газпром" has 74 tradable matches, and the first 20 in the API's order
        # were 19 bonds and a future — the share itself was not in the list.
        def paper(n, kind, name):
            return {"ticker": f"X{n}", "classCode": "C", "name": name, "instrumentType": kind,
                    "uid": f"{n:08d}-aaaa-bbbb-cccc-000000000000", "figi": f"F{n}", "isin": f"I{n}",
                    "lot": 1, "apiTradeAvailableFlag": True}
        found = [paper(1, "bond", "Газпром капитал 001Р"), paper(2, "futures", "GAZR-12.26"),
                 paper(3, "bond", "Газпром нефть 003P"), paper(4, "etf", "Фонд Газпром"),
                 paper(5, "share", "Газпром")]
        with patch.object(srv, "_call", route(FindInstrument={"instruments": found})):
            result = json.loads(await srv.find_instrument("газпром", limit=3))
        assert [i["instrumentType"] for i in result["instruments"]] == ["share", "etf", "bond"]
        assert result["instruments"][2]["ticker"] == "X1"  # the API's order is kept among bonds

    async def test_an_exact_name_beats_the_kind(self):
        found = [
            {"ticker": "A", "name": "Сбер Банк", "instrumentType": "share", "uid": "u-1", "apiTradeAvailableFlag": True},
            {"ticker": "B", "name": "Сбербанк", "instrumentType": "bond", "uid": "u-2", "apiTradeAvailableFlag": True},
        ]
        with patch.object(srv, "_call", route(FindInstrument={"instruments": found})):
            result = json.loads(await srv.find_instrument("Сбербанк"))
        assert [i["ticker"] for i in result["instruments"]] == ["B", "A"]


class TestConsensusPageNumber:
    async def test_the_old_parameter_is_accepted_and_changes_nothing(self):
        mock = make_paged_call_mock([([{"assetUid": "asset-target"}], 1)])
        with patch.object(srv, "_call", mock):
            result = json.loads(await srv.get_consensus_forecasts("asset-target", page_number=3))
        assert result["assetUid"] == "asset-target"
        assert calls_to(mock, "GetConsensusForecasts")[0]["paging"]["pageNumber"] == 0
