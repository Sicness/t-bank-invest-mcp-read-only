"""MCP server for T-Bank (Tinkoff) Invest API — read-only portfolio analytics."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = "https://invest-public-api.tinkoff.ru/rest"
SERVICE_PREFIX = "tinkoff.public.invest.api.contract.v1"

mcp = FastMCP(
    "t-bank-invest-mcp-read-only",
    instructions=(
        "MCP server for reading T-Bank (Tinkoff) investment portfolio data. "
        "Provides read-only access to accounts, portfolios, positions, operations, "
        "instruments, market data, and orders. All monetary values use MoneyValue format: "
        "units (integer part) + nano (fractional part, 10^-9). "
        "To convert: value = units + nano / 1_000_000_000. "
        "Quotation format is the same but without currency."
    ),
)


def _get_token() -> str:
    token = os.environ.get("TBANK_INVEST_TOKEN", "")
    if not token:
        raise ValueError(
            "TBANK_INVEST_TOKEN environment variable is not set. "
            "Get your token at https://www.tbank.ru/invest/settings/api/"
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _call(service: str, method: str, body: dict[str, Any] | None = None) -> dict:
    url = f"{BASE_URL}/{SERVICE_PREFIX}.{service}/{method}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_headers(), json=body or {})
        resp.raise_for_status()
        return resp.json()


def _ts(dt: datetime) -> str:
    """Convert datetime to RFC 3339 string for the API."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date(s: str | None, default: datetime | None = None) -> datetime | None:
    if not s:
        return default
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format.")


def _fmt(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── Account & User ──────────────────────────────────────────────────────────


@mcp.tool()
async def get_accounts() -> str:
    """Get list of all user investment accounts with their types and statuses.

    Returns account IDs needed for other operations (portfolio, positions, operations).
    Account types: TINKOFF (broker), TINKOFF_IIS (individual investment account), INVEST_BOX, INVEST_FUND.
    """
    data = await _call("UsersService", "GetAccounts", {"status": "ACCOUNT_STATUS_ALL"})
    return _fmt(data)


@mcp.tool()
async def get_user_info() -> str:
    """Get user information: tariff, qualified investor status, premium status, risk level."""
    data = await _call("UsersService", "GetInfo", {})
    return _fmt(data)


@mcp.tool()
async def get_margin_attributes(account_id: str) -> str:
    """Get margin trading attributes for an account: liquid portfolio value, starting/minimal margin, funds sufficiency.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("UsersService", "GetMarginAttributes", {"accountId": account_id})
    return _fmt(data)


# ── Portfolio & Positions ────────────────────────────────────────────────────


@mcp.tool()
async def get_portfolio(account_id: str, currency: str = "RUB") -> str:
    """Get full portfolio for an account: total values by asset type, all positions with prices, yields, and quantities.

    Each position includes: figi, instrument_type, quantity, average_position_price,
    expected_yield, current_price, daily_yield, ticker, class_code.

    Args:
        account_id: Account ID (get from get_accounts)
        currency: Portfolio currency — RUB, USD, or EUR (default: RUB)
    """
    currency_map = {"RUB": 0, "USD": 1, "EUR": 2}
    body: dict[str, Any] = {"accountId": account_id}
    if currency.upper() in currency_map:
        body["currency"] = currency_map[currency.upper()]
    data = await _call("OperationsService", "GetPortfolio", body)
    return _fmt(data)


@mcp.tool()
async def get_positions(account_id: str) -> str:
    """Get all positions in an account: securities, futures, options, and cash balances.

    Unlike get_portfolio, this returns raw position balances without price calculations.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetPositions", {"accountId": account_id})
    return _fmt(data)


@mcp.tool()
async def get_withdraw_limits(account_id: str) -> str:
    """Get available withdrawal limits for an account: free cash, blocked amounts, futures guarantees.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetWithdrawLimits", {"accountId": account_id})
    return _fmt(data)


# ── Operations ───────────────────────────────────────────────────────────────


@mcp.tool()
async def get_operations(
    account_id: str,
    from_date: str = "",
    to_date: str = "",
    state: str = "",
    figi: str = "",
) -> str:
    """Get list of operations (transactions) for an account within a date range.

    Returns: buys, sells, dividends, coupons, taxes, commissions, deposits, withdrawals, etc.
    Each operation has: id, type, date, payment amount, instrument info, quantity, trades.

    Note: for large histories use get_operations_by_cursor instead.

    Args:
        account_id: Account ID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD), default: now
        state: Filter by state: EXECUTED, CANCELED, PROGRESS (empty = all)
        figi: Filter by instrument FIGI (empty = all instruments)
    """
    now = datetime.now(timezone.utc)
    dt_from = _parse_date(from_date, now - timedelta(days=30))
    dt_to = _parse_date(to_date, now)
    body: dict[str, Any] = {
        "accountId": account_id,
        "from": _ts(dt_from),
        "to": _ts(dt_to),
    }
    if state:
        body["state"] = f"OPERATION_STATE_{state.upper()}"
    if figi:
        body["figi"] = figi
    data = await _call("OperationsService", "GetOperations", body)
    return _fmt(data)


@mcp.tool()
async def get_operations_by_cursor(
    account_id: str,
    from_date: str = "",
    to_date: str = "",
    cursor: str = "",
    limit: int = 100,
    instrument_id: str = "",
    operation_types: str = "",
    state: str = "",
    without_commissions: bool = False,
    without_trades: bool = False,
) -> str:
    """Get operations with cursor-based pagination. Better for large histories.

    Returns has_next flag and next_cursor for pagination. Each operation item includes
    detailed info: payment, price, commission, yield, quantity, trades, ticker.

    Common operation types: BUY, SELL, DIVIDEND, COUPON, TAX, BOND_TAX, INPUT, OUTPUT,
    BROKER_FEE, BOND_REPAYMENT_FULL, BOND_REPAYMENT.

    Args:
        account_id: Account ID
        from_date: Start date (YYYY-MM-DD), default: 1 year ago
        to_date: End date (YYYY-MM-DD), default: now
        cursor: Cursor from previous response for pagination
        limit: Number of operations per page (1-1000, default: 100)
        instrument_id: Filter by instrument FIGI or UID
        operation_types: Comma-separated operation types (e.g. "BUY,SELL,DIVIDEND")
        state: Filter by state: EXECUTED, CANCELED, PROGRESS
        without_commissions: Exclude commission operations
        without_trades: Exclude trade details from response
    """
    now = datetime.now(timezone.utc)
    dt_from = _parse_date(from_date, now - timedelta(days=365))
    dt_to = _parse_date(to_date, now)
    body: dict[str, Any] = {
        "accountId": account_id,
        "from": _ts(dt_from),
        "to": _ts(dt_to),
        "limit": min(max(limit, 1), 1000),
        "withoutCommissions": without_commissions,
        "withoutTrades": without_trades,
    }
    if cursor:
        body["cursor"] = cursor
    if instrument_id:
        body["instrumentId"] = instrument_id
    if operation_types:
        body["operationTypes"] = [
            f"OPERATION_TYPE_{t.strip().upper()}" for t in operation_types.split(",")
        ]
    if state:
        body["state"] = f"OPERATION_STATE_{state.upper()}"
    data = await _call("OperationsService", "GetOperationsByCursor", body)
    return _fmt(data)


# ── Instruments ──────────────────────────────────────────────────────────────


@mcp.tool()
async def find_instrument(query: str) -> str:
    """Search for instruments by text query (ticker, name, ISIN, FIGI).

    Returns list of matching instruments with basic info: figi, ticker, name, type, class_code.

    Args:
        query: Search string (e.g. "SBER", "Газпром", "Apple")
    """
    data = await _call("InstrumentsService", "FindInstrument", {"query": query})
    return _fmt(data)


@mcp.tool()
async def get_instrument_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed instrument info by its identifier.

    Returns: name, ticker, figi, uid, lot size, currency, country, sector, trading status, etc.

    Args:
        id: Instrument identifier (FIGI, ticker, or UID)
        id_type: Type of ID — INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER (e.g. "TQBR" for Moscow Exchange shares)
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "GetInstrumentBy", body)
    return _fmt(data)


@mcp.tool()
async def get_bond_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed bond info: maturity date, coupon rate, nominal, ACI, issue size, risk level.

    Args:
        id: Bond identifier (FIGI, ticker, or UID)
        id_type: INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "BondBy", body)
    return _fmt(data)


@mcp.tool()
async def get_bond_coupons(
    figi: str = "",
    instrument_id: str = "",
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get bond coupon payment schedule: dates, amounts, coupon periods.

    Args:
        figi: Bond FIGI (deprecated, prefer instrument_id)
        instrument_id: Bond FIGI or UID
        from_date: Start date (YYYY-MM-DD), default: now
        to_date: End date (YYYY-MM-DD), default: 1 year from now
    """
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "from": _ts(_parse_date(from_date, now)),
        "to": _ts(_parse_date(to_date, now + timedelta(days=365))),
    }
    if instrument_id:
        body["instrumentId"] = instrument_id
    if figi:
        body["figi"] = figi
    data = await _call("InstrumentsService", "GetBondCoupons", body)
    return _fmt(data)


@mcp.tool()
async def get_bond_events(instrument_id: str, type: str = "") -> str:
    """Get bond events: coupon payments, amortizations, calls, puts, etc.

    Args:
        instrument_id: Bond FIGI or UID
        type: Event type filter (empty = all). Values: COUPON, CALL, PUT, MATURITY, etc.
    """
    body: dict[str, Any] = {"instrumentId": instrument_id}
    if type:
        body["type"] = type
    data = await _call("InstrumentsService", "GetBondEvents", body)
    return _fmt(data)


@mcp.tool()
async def get_share_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed share (stock) info: sector, dividend yield, IPO date, issue size, country.

    Args:
        id: Share identifier (FIGI, ticker, or UID)
        id_type: INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER (e.g. "TQBR")
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "ShareBy", body)
    return _fmt(data)


@mcp.tool()
async def get_etf_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed ETF/fund info: management fee, tracking index, rebalance frequency.

    Args:
        id: ETF identifier (FIGI, ticker, or UID)
        id_type: INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "EtfBy", body)
    return _fmt(data)


@mcp.tool()
async def get_currency_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed currency instrument info.

    Args:
        id: Currency identifier (FIGI, ticker, or UID)
        id_type: INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "CurrencyBy", body)
    return _fmt(data)


@mcp.tool()
async def get_future_by(
    id: str,
    id_type: str = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed futures contract info: expiration, basic asset, margin requirements.

    Args:
        id: Future identifier (FIGI, ticker, or UID)
        id_type: INSTRUMENT_ID_TYPE_FIGI, INSTRUMENT_ID_TYPE_TICKER, or INSTRUMENT_ID_TYPE_UID
        class_code: Required when id_type is TICKER
    """
    body: dict[str, Any] = {"idType": id_type, "id": id}
    if class_code:
        body["classCode"] = class_code
    data = await _call("InstrumentsService", "FutureBy", body)
    return _fmt(data)


@mcp.tool()
async def get_dividends(
    instrument_id: str,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get dividend payment history and upcoming dividends for an instrument.

    Returns: record date, payment date, dividend per share, yield, currency.

    Args:
        instrument_id: Instrument FIGI or UID
        from_date: Start date (YYYY-MM-DD), default: 2 years ago
        to_date: End date (YYYY-MM-DD), default: 1 year ahead
    """
    now = datetime.now(timezone.utc)
    data = await _call("InstrumentsService", "GetDividends", {
        "instrumentId": instrument_id,
        "from": _ts(_parse_date(from_date, now - timedelta(days=730))),
        "to": _ts(_parse_date(to_date, now + timedelta(days=365))),
    })
    return _fmt(data)


@mcp.tool()
async def get_accrued_interests(
    instrument_id: str,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get accrued coupon interest (NKD) history for a bond.

    Args:
        instrument_id: Bond FIGI or UID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD), default: now
    """
    now = datetime.now(timezone.utc)
    data = await _call("InstrumentsService", "GetAccruedInterests", {
        "instrumentId": instrument_id,
        "from": _ts(_parse_date(from_date, now - timedelta(days=30))),
        "to": _ts(_parse_date(to_date, now)),
    })
    return _fmt(data)


@mcp.tool()
async def get_asset_fundamentals(assets: str) -> str:
    """Get fundamental financial data for assets: P/E, P/BV, EPS, ROE, revenue, market cap, etc.

    Args:
        assets: Comma-separated list of asset UIDs
    """
    asset_list = [a.strip() for a in assets.split(",") if a.strip()]
    data = await _call("InstrumentsService", "GetAssetFundamentals", {"assets": asset_list})
    return _fmt(data)


@mcp.tool()
async def get_consensus_forecasts(
    instrument_id: str,
    page_limit: int = 100,
    page_number: int = 0,
) -> str:
    """Get analyst consensus forecasts for an instrument: target price, recommendation, number of analysts.

    Args:
        instrument_id: Instrument UID
        page_limit: Results per page (default: 100)
        page_number: Page number starting from 0
    """
    data = await _call("InstrumentsService", "GetConsensusForecasts", {
        "paging": {"limit": page_limit, "pageNumber": page_number},
    })
    # Filter for the requested instrument if needed
    return _fmt(data)


@mcp.tool()
async def get_forecast_by(instrument_id: str) -> str:
    """Get investment house price forecasts for an instrument.

    Returns: analyst name, target price, recommendation (buy/hold/sell), date.

    Args:
        instrument_id: Instrument UID
    """
    data = await _call("InstrumentsService", "GetForecastBy", {"instrumentId": instrument_id})
    return _fmt(data)


@mcp.tool()
async def get_asset_reports(
    instrument_id: str,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get upcoming and past earnings report dates for an instrument's issuer.

    Args:
        instrument_id: Instrument UID
        from_date: Start date (YYYY-MM-DD), default: now
        to_date: End date (YYYY-MM-DD), default: 1 year ahead
    """
    now = datetime.now(timezone.utc)
    data = await _call("InstrumentsService", "GetAssetReports", {
        "instrumentId": instrument_id,
        "from": _ts(_parse_date(from_date, now)),
        "to": _ts(_parse_date(to_date, now + timedelta(days=365))),
    })
    return _fmt(data)


@mcp.tool()
async def get_favorites() -> str:
    """Get list of user's favorite instruments."""
    data = await _call("InstrumentsService", "GetFavorites", {})
    return _fmt(data)


@mcp.tool()
async def get_trading_schedules(
    exchange: str = "",
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get trading schedules for exchanges: trading hours, auction times, clearing times.

    Args:
        exchange: Exchange name (e.g. "MOEX", "SPB"). Empty = all exchanges.
        from_date: Start date (YYYY-MM-DD), default: today
        to_date: End date (YYYY-MM-DD), default: 7 days ahead
    """
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "from": _ts(_parse_date(from_date, now)),
        "to": _ts(_parse_date(to_date, now + timedelta(days=7))),
    }
    if exchange:
        body["exchange"] = exchange
    data = await _call("InstrumentsService", "TradingSchedules", body)
    return _fmt(data)


# ── Market Data ──────────────────────────────────────────────────────────────


@mcp.tool()
async def get_candles(
    instrument_id: str,
    from_date: str = "",
    to_date: str = "",
    interval: str = "CANDLE_INTERVAL_DAY",
) -> str:
    """Get historical candles (OHLCV) for an instrument.

    Args:
        instrument_id: Instrument FIGI or UID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD), default: now
        interval: Candle interval — CANDLE_INTERVAL_1_MIN, CANDLE_INTERVAL_5_MIN,
                  CANDLE_INTERVAL_15_MIN, CANDLE_INTERVAL_HOUR, CANDLE_INTERVAL_DAY,
                  CANDLE_INTERVAL_WEEK, CANDLE_INTERVAL_MONTH
    """
    now = datetime.now(timezone.utc)
    data = await _call("MarketDataService", "GetCandles", {
        "instrumentId": instrument_id,
        "from": _ts(_parse_date(from_date, now - timedelta(days=30))),
        "to": _ts(_parse_date(to_date, now)),
        "interval": interval,
    })
    return _fmt(data)


@mcp.tool()
async def get_last_prices(instrument_ids: str) -> str:
    """Get last trade prices for one or more instruments.

    Args:
        instrument_ids: Comma-separated list of FIGIs or UIDs
    """
    ids = [i.strip() for i in instrument_ids.split(",") if i.strip()]
    data = await _call("MarketDataService", "GetLastPrices", {"instrumentId": ids})
    return _fmt(data)


@mcp.tool()
async def get_order_book(instrument_id: str, depth: int = 20) -> str:
    """Get order book (market depth) for an instrument: bids, asks, last price, spread.

    Args:
        instrument_id: Instrument FIGI or UID
        depth: Order book depth 1-50 (default: 20)
    """
    data = await _call("MarketDataService", "GetOrderBook", {
        "instrumentId": instrument_id,
        "depth": min(max(depth, 1), 50),
    })
    return _fmt(data)


@mcp.tool()
async def get_close_prices(instrument_ids: str) -> str:
    """Get previous trading session close prices for instruments.

    Args:
        instrument_ids: Comma-separated list of FIGIs or UIDs
    """
    ids = [i.strip() for i in instrument_ids.split(",") if i.strip()]
    instruments = [{"instrumentId": i} for i in ids]
    data = await _call("MarketDataService", "GetClosePrices", {"instruments": instruments})
    return _fmt(data)


@mcp.tool()
async def get_trading_status(instrument_id: str) -> str:
    """Get current trading status for an instrument: is it tradeable, auction phase, etc.

    Args:
        instrument_id: Instrument FIGI or UID
    """
    data = await _call("MarketDataService", "GetTradingStatus", {"instrumentId": instrument_id})
    return _fmt(data)


@mcp.tool()
async def get_tech_analysis(
    instrument_id: str,
    indicator_type: str,
    from_date: str = "",
    to_date: str = "",
    interval: str = "CANDLE_INTERVAL_DAY",
    type_of_price: str = "TYPE_OF_PRICE_CLOSE",
    length: int = 14,
) -> str:
    """Get technical analysis indicators (SMA, EMA, RSI, MACD, BB) for an instrument.

    Args:
        instrument_id: Instrument UID
        indicator_type: INDICATOR_TYPE_SMA, INDICATOR_TYPE_EMA, INDICATOR_TYPE_RSI,
                       INDICATOR_TYPE_MACD, INDICATOR_TYPE_BB
        from_date: Start date (YYYY-MM-DD), default: 90 days ago
        to_date: End date (YYYY-MM-DD), default: now
        interval: Candle interval (see get_candles)
        type_of_price: TYPE_OF_PRICE_CLOSE, TYPE_OF_PRICE_OPEN, TYPE_OF_PRICE_HIGH, TYPE_OF_PRICE_LOW, TYPE_OF_PRICE_AVG
        length: Indicator period length (default: 14)
    """
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "instrumentUid": instrument_id,
        "indicatorType": indicator_type,
        "from": _ts(_parse_date(from_date, now - timedelta(days=90))),
        "to": _ts(_parse_date(to_date, now)),
        "interval": interval,
        "typeOfPrice": type_of_price,
        "length": length,
    }
    data = await _call("MarketDataService", "GetTechAnalysis", body)
    return _fmt(data)


# ── Orders ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_orders(account_id: str) -> str:
    """Get list of active (pending) orders for an account.

    Returns: order_id, direction, type, status, price, quantity, instrument info.

    Args:
        account_id: Account ID
    """
    data = await _call("OrdersService", "GetOrders", {"accountId": account_id})
    return _fmt(data)


@mcp.tool()
async def get_order_state(account_id: str, order_id: str) -> str:
    """Get detailed status of a specific order: execution status, filled quantity, average price.

    Args:
        account_id: Account ID
        order_id: Order ID
    """
    data = await _call("OrdersService", "GetOrderState", {
        "accountId": account_id,
        "orderId": order_id,
    })
    return _fmt(data)


# ── Instrument Lists ─────────────────────────────────────────────────────────


@mcp.tool()
async def list_shares(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available shares (stocks).

    Warning: returns a large dataset. Use find_instrument for searching specific shares.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Shares", {"instrumentStatus": instrument_status})
    return _fmt(data)


@mcp.tool()
async def list_bonds(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available bonds.

    Warning: returns a large dataset. Use find_instrument for searching specific bonds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Bonds", {"instrumentStatus": instrument_status})
    return _fmt(data)


@mcp.tool()
async def list_etfs(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available ETFs and funds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Etfs", {"instrumentStatus": instrument_status})
    return _fmt(data)


@mcp.tool()
async def list_currencies(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available currency instruments.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Currencies", {"instrumentStatus": instrument_status})
    return _fmt(data)


@mcp.tool()
async def list_futures(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available futures contracts.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Futures", {"instrumentStatus": instrument_status})
    return _fmt(data)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
