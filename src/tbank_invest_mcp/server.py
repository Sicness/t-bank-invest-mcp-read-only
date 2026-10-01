"""MCP server for T-Bank (Tinkoff) Invest API — read-only portfolio analytics."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import certifi
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from tbank_invest_mcp import __version__

BASE_URL = "https://invest-public-api.tbank.ru/rest"
SERVICE_PREFIX = "tinkoff.public.invest.api.contract.v1"

# T-API is served under certificates from the Russian Ministry of Digital
# Development CA, which no default trust store ships. We pin that root for this
# client only — installing it system-wide would let the CA impersonate any host.
CA_FILE = Path(__file__).parent / "certs" / "russian_trusted_root_ca.pem"
CA_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"

TIMEOUT_SECONDS = 30

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
# FastMCP takes no version and would report the MCP SDK's own version as the server's.
mcp._mcp_server.version = __version__


def read_only_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register fn as an MCP tool. Every tool of this server goes through here.

    The client is told the tool only reads (readOnlyHint), the docstring becomes the
    description without its source indentation, and the JSON string the tool returns
    is sent once as text — by default FastMCP would also wrap that same string into
    structuredContent, sending every response twice.
    """
    return mcp.tool(
        description=inspect.cleandoc(fn.__doc__ or ""),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
        structured_output=False,
    )(fn)


def _get_token() -> str:
    # Stripped: a trailing newline from a copy-paste or `$(cat file)` is not part of the token.
    token = os.environ.get("TBANK_INVEST_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "TBANK_INVEST_TOKEN environment variable is not set. "
            "Get your token at https://www.tbank.ru/invest/settings/api/"
        )
    # Checked here, and without echoing the value: httpx would refuse such a header with an
    # error that quotes it in full, and that error text goes to the model.
    if not token.isascii() or not token.isprintable() or " " in token:
        raise ValueError(
            "TBANK_INVEST_TOKEN contains characters a token cannot have (spaces, line breaks "
            "or non-ASCII characters). Copy the token again without anything around it."
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ssl_context() -> ssl.SSLContext:
    """Default trust store plus the pinned Russian Trusted Root CA."""
    ctx = ssl.create_default_context(cafile=certifi.where())

    override = os.environ.get("TBANK_CA_BUNDLE")
    if override:
        ctx.load_verify_locations(cafile=override)
        return ctx

    pem = CA_FILE.read_text()
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    if digest != CA_SHA256:
        raise RuntimeError(
            f"{CA_FILE} does not match the expected Russian Trusted Root CA "
            f"(sha256 {digest}, expected {CA_SHA256}). Refusing to trust it. "
            "Set TBANK_CA_BUNDLE to point at a bundle you trust if the CA "
            "has legitimately rotated."
        )
    ctx.load_verify_locations(cadata=pem)
    return ctx


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS, verify=_ssl_context())
    return _client


def _api_error(service: str, method: str, resp: httpx.Response) -> str:
    """What the API said went wrong: its message and error code, not just the HTTP status."""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("message"):
        detail = str(payload["message"])
        if payload.get("description"):
            detail += f" (error code {payload['description']})"
    else:
        detail = resp.text.strip()[:300] or "no details in the response"
    return f"T-Bank API returned HTTP {resp.status_code} for {service}/{method}: {detail}"


def _transport_error(service: str, method: str, exc: httpx.RequestError, token: str) -> str:
    """What went wrong before any HTTP status arrived: a timeout or a network failure."""
    if isinstance(exc, httpx.TimeoutException):
        # httpx gives timeouts an empty message.
        detail = f"no answer within {TIMEOUT_SECONDS} seconds; the request can be retried"
    else:
        # Never let the token through, whatever the underlying error chose to quote.
        detail = str(exc).replace(token, "<token>") or "no details"
    return f"T-Bank API request {service}/{method} failed ({type(exc).__name__}): {detail}"


async def _call(service: str, method: str, body: dict[str, Any] | None = None) -> dict:
    url = f"{BASE_URL}/{SERVICE_PREFIX}.{service}/{method}"
    headers = _headers()
    try:
        resp = await _get_client().post(url, headers=headers, json=body or {})
    except httpx.RequestError as e:
        raise type(e)(_transport_error(service, method, e, _get_token())) from None
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        # Same exception, but its text is what the model reads as the tool error: say what
        # the API answered instead of httpx's status line, URL and a link to MDN.
        raise httpx.HTTPStatusError(
            _api_error(service, method, resp), request=e.request, response=e.response
        ) from None
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
    # Compact: the reader is a model, and indentation is a third or more of a response.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _quotation_to_float(q: dict[str, Any] | None) -> float | None:
    """Convert a Quotation/MoneyValue object ({units, nano}) to a plain float."""
    if not q:
        return None
    return float(q.get("units", 0)) + float(q.get("nano", 0)) / 1_000_000_000


def _to_quotation(value: float) -> dict[str, Any]:
    """Convert a number to a Quotation object ({units, nano}) for a request body."""
    units = int(value)
    return {"units": str(units), "nano": round((value - units) * 1_000_000_000)}


# ── Account & User ──────────────────────────────────────────────────────────


@read_only_tool
async def get_accounts() -> str:
    """Get list of all user investment accounts with their types and statuses.

    Returns account IDs needed for other operations (portfolio, positions, operations).
    Account types: TINKOFF (broker), TINKOFF_IIS (individual investment account), INVEST_BOX, INVEST_FUND.
    """
    data = await _call("UsersService", "GetAccounts", {"status": "ACCOUNT_STATUS_ALL"})
    return _fmt(data)


@read_only_tool
async def get_user_info() -> str:
    """Get user information: tariff, qualified investor status, premium status, risk level."""
    data = await _call("UsersService", "GetInfo", {})
    return _fmt(data)


@read_only_tool
async def get_margin_attributes(account_id: str) -> str:
    """Get margin trading attributes for an account: liquid portfolio value, starting/minimal margin, funds sufficiency.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("UsersService", "GetMarginAttributes", {"accountId": account_id})
    return _fmt(data)


# ── Portfolio & Positions ────────────────────────────────────────────────────


@read_only_tool
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


@read_only_tool
async def get_positions(account_id: str) -> str:
    """Get all positions in an account: securities, futures, options, and cash balances.

    Unlike get_portfolio, this returns raw position balances without price calculations.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetPositions", {"accountId": account_id})
    return _fmt(data)


@read_only_tool
async def get_withdraw_limits(account_id: str) -> str:
    """Get available withdrawal limits for an account: free cash, blocked amounts, futures guarantees.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetWithdrawLimits", {"accountId": account_id})
    return _fmt(data)


# ── Operations ───────────────────────────────────────────────────────────────


@read_only_tool
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


@read_only_tool
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


@read_only_tool
async def find_instrument(query: str) -> str:
    """Search for instruments by text query (ticker, name, ISIN, FIGI).

    Returns list of matching instruments with basic info: figi, ticker, name, type, class_code.

    Args:
        query: Search string (e.g. "SBER", "Газпром", "Apple")
    """
    data = await _call("InstrumentsService", "FindInstrument", {"query": query})
    return _fmt(data)


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
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


@read_only_tool
async def get_asset_fundamentals(assets: str) -> str:
    """Get fundamental financial data for assets: P/E, P/BV, EPS, ROE, revenue, market cap, etc.

    Args:
        assets: Comma-separated list of asset UIDs
    """
    asset_list = [a.strip() for a in assets.split(",") if a.strip()]
    data = await _call("InstrumentsService", "GetAssetFundamentals", {"assets": asset_list})
    return _fmt(data)


async def _asset_uid(instrument_uid: str) -> str:
    """Asset UID of an instrument, or "" if instrument_uid is not a known instrument UID.

    Fundamentals and consensus forecasts are keyed by asset UID, which is a different
    identifier from the instrument UID that FindInstrument and the *By lookups return.
    """
    try:
        data = await _call("InstrumentsService", "GetInstrumentBy", {
            "idType": "INSTRUMENT_ID_TYPE_UID",
            "id": instrument_uid,
        })
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return ""
        raise
    return data.get("instrument", {}).get("assetUid", "")


async def _consensus_forecast(asset_uids: set[str], page_limit: int = 100, max_pages: int = 50) -> dict:
    """Scan GetConsensusForecasts pages for the item whose assetUid is in asset_uids.

    Returns the item, or {"error": ...} saying whether the whole list was scanned or the
    scan was cut short by max_pages.
    """
    if not asset_uids:
        return {"error": "No asset UID to look a consensus forecast up by"}
    label = " / ".join(sorted(asset_uids))
    for page_number in range(max_pages):
        data = await _call("InstrumentsService", "GetConsensusForecasts", {
            "paging": {"limit": page_limit, "pageNumber": page_number},
        })
        for item in data.get("items", []):
            # An item's own "uid" identifies the forecast record, not the instrument.
            if item.get("assetUid") in asset_uids:
                return item

        total_count = data.get("page", {}).get("totalCount", 0)
        if (page_number + 1) * page_limit >= total_count:
            return {"error": f"No consensus forecast found for asset {label}"}

    return {"error": (
        f"No consensus forecast found for asset {label} in the first {max_pages} pages; "
        "the scan stopped at max_pages before reaching the end of the list — raise max_pages"
    )}


@read_only_tool
async def get_consensus_forecasts(
    instrument_id: str,
    page_limit: int = 100,
    max_pages: int = 50,
) -> str:
    """Get the analyst consensus forecast for one instrument: target price, recommendation,
    number of analysts.

    GetConsensusForecasts has no server-side instrument filter — it only returns pages of
    forecasts for the whole instrument universe, keyed by asset UID. This resolves
    instrument_id to its asset UID, scans pages internally and returns just the matching
    item, or {"error": ...} if there is none.

    Args:
        instrument_id: Instrument UID or asset UID
        page_limit: Page size used while scanning (default: 100)
        max_pages: Safety cap on how many pages to scan before giving up (default: 50)
    """
    # instrument_id itself stays in the set: it is already an asset UID if the lookup found nothing.
    asset_uids = {instrument_id, await _asset_uid(instrument_id)} - {""}
    return _fmt(await _consensus_forecast(asset_uids, page_limit, max_pages))


def _pick_instrument(instruments: list[dict], query: str, class_code: str = "") -> dict | None:
    """Choose one FindInstrument hit: an exact ticker/ISIN/FIGI match beats search order."""
    if class_code:
        instruments = [i for i in instruments if i.get("classCode") == class_code]
    q = query.strip().upper()
    exact = [
        i for i in instruments
        if q in (i.get("ticker", "").upper(), i.get("isin", "").upper(), i.get("figi", "").upper())
    ]
    candidates = exact or instruments
    return next((i for i in candidates if i.get("apiTradeAvailableFlag")), next(iter(candidates), None))


@read_only_tool
async def get_stock_snapshot(ticker: str, candle_days: int = 5, class_code: str = "") -> str:
    """Get a one-call overview of a share: fundamentals, recent price change, and analyst consensus.

    Convenience wrapper around FindInstrument + GetInstrumentBy + GetAssetFundamentals +
    GetCandles + GetConsensusForecasts, so a caller doesn't need separate round trips (and
    the manual ticker → UID → asset UID resolution) to get a compact picture of one share.

    Returns ticker, class_code, uid, asset_uid and name of the share it resolved to — check
    them when the query is ambiguous — plus price {last_close, change_pct, change_sessions},
    fundamentals and consensus. Returns {"error": ...} if no share matches.

    Args:
        ticker: Ticker, name, ISIN, or FIGI of a share (searched with FindInstrument; an exact
            ticker/ISIN/FIGI match is preferred over the first search hit)
        candle_days: Number of daily candles (trading sessions) the price change spans (default: 5)
        class_code: Optional class code to disambiguate listings (e.g. "TQBR")
    """
    if candle_days < 1:
        raise ValueError(f"candle_days must be at least 1, got {candle_days}")

    found = await _call("InstrumentsService", "FindInstrument", {
        "query": ticker,
        "instrumentKind": "INSTRUMENT_TYPE_SHARE",
    })
    instrument = _pick_instrument(found.get("instruments", []), ticker, class_code)
    if instrument is None:
        return _fmt({"error": f"No share found for ticker={ticker!r}, class_code={class_code!r}"})
    uid = instrument.get("uid", "")

    asset_uid = await _asset_uid(uid)

    async def fundamentals_for_asset() -> dict:
        if not asset_uid:
            return {}
        data = await _call("InstrumentsService", "GetAssetFundamentals", {"assets": [asset_uid]})
        return next(iter(data.get("fundamentals", [])), {})

    now = datetime.now(timezone.utc)
    fundamentals, candles_data, consensus = await asyncio.gather(
        fundamentals_for_asset(),
        _call("MarketDataService", "GetCandles", {
            "instrumentId": uid,
            # Calendar window wide enough to hold candle_days + 1 sessions across
            # weekends and long holidays.
            "from": _ts(now - timedelta(days=candle_days * 3 // 2 + 14)),
            "to": _ts(now),
            "interval": "CANDLE_INTERVAL_DAY",
        }),
        _consensus_forecast({asset_uid} - {""}),
    )

    # The change is measured from the close before the first of the last candle_days sessions.
    candles = candles_data.get("candles", [])[-(candle_days + 1):]
    price: dict[str, Any] = {}
    if candles:
        base_close = _quotation_to_float(candles[0].get("close"))
        last_close = _quotation_to_float(candles[-1].get("close"))
        price["last_close"] = last_close
        if len(candles) > 1 and base_close and last_close is not None:
            price["change_pct"] = round((last_close - base_close) / base_close * 100, 2)
            price["change_sessions"] = len(candles) - 1

    return _fmt({
        "ticker": instrument.get("ticker"),
        "class_code": instrument.get("classCode"),
        "uid": uid,
        "asset_uid": asset_uid,
        "name": instrument.get("name"),
        "price": price,
        "fundamentals": fundamentals,
        "consensus": consensus,
    })


@read_only_tool
async def get_forecast_by(instrument_id: str) -> str:
    """Get investment house price forecasts for an instrument.

    Returns: analyst name, target price, recommendation (buy/hold/sell), date.

    Args:
        instrument_id: Instrument UID
    """
    data = await _call("InstrumentsService", "GetForecastBy", {"instrumentId": instrument_id})
    return _fmt(data)


@read_only_tool
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


@read_only_tool
async def get_favorites() -> str:
    """Get list of user's favorite instruments."""
    data = await _call("InstrumentsService", "GetFavorites", {})
    return _fmt(data)


@read_only_tool
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


@read_only_tool
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


@read_only_tool
async def get_last_prices(instrument_ids: str) -> str:
    """Get last trade prices for one or more instruments.

    Args:
        instrument_ids: Comma-separated list of FIGIs or UIDs
    """
    ids = [i.strip() for i in instrument_ids.split(",") if i.strip()]
    data = await _call("MarketDataService", "GetLastPrices", {"instrumentId": ids})
    return _fmt(data)


@read_only_tool
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


@read_only_tool
async def get_close_prices(instrument_ids: str) -> str:
    """Get previous trading session close prices for instruments.

    Args:
        instrument_ids: Comma-separated list of FIGIs or UIDs
    """
    ids = [i.strip() for i in instrument_ids.split(",") if i.strip()]
    instruments = [{"instrumentId": i} for i in ids]
    data = await _call("MarketDataService", "GetClosePrices", {"instruments": instruments})
    return _fmt(data)


@read_only_tool
async def get_trading_status(instrument_id: str) -> str:
    """Get current trading status for an instrument: is it tradeable, auction phase, etc.

    Args:
        instrument_id: Instrument FIGI or UID
    """
    data = await _call("MarketDataService", "GetTradingStatus", {"instrumentId": instrument_id})
    return _fmt(data)


@read_only_tool
async def get_tech_analysis(
    instrument_id: str,
    indicator_type: str,
    from_date: str = "",
    to_date: str = "",
    interval: str = "INDICATOR_INTERVAL_ONE_DAY",
    type_of_price: str = "TYPE_OF_PRICE_CLOSE",
    length: int = 14,
    deviation: float = 2.0,
    fast_length: int = 12,
    slow_length: int = 26,
    signal_smoothing: int = 9,
) -> str:
    """Get technical analysis indicators (SMA, EMA, RSI, MACD, BB) for an instrument.

    Returns technicalIndicators: one item per interval with a timestamp and the indicator's
    values — signal (SMA, EMA, RSI), macd and signal (MACD), or middleBand, upperBand and
    lowerBand (BB).

    Args:
        instrument_id: Instrument UID
        indicator_type: INDICATOR_TYPE_SMA, INDICATOR_TYPE_EMA, INDICATOR_TYPE_RSI,
                       INDICATOR_TYPE_MACD, INDICATOR_TYPE_BB
        from_date: Start date (YYYY-MM-DD), default: 90 days ago
        to_date: End date (YYYY-MM-DD), default: now
        interval: Not the get_candles names. INDICATOR_INTERVAL_ONE_MINUTE, INDICATOR_INTERVAL_2_MIN,
                  INDICATOR_INTERVAL_3_MIN, INDICATOR_INTERVAL_FIVE_MINUTES, INDICATOR_INTERVAL_10_MIN,
                  INDICATOR_INTERVAL_FIFTEEN_MINUTES, INDICATOR_INTERVAL_30_MIN, INDICATOR_INTERVAL_ONE_HOUR,
                  INDICATOR_INTERVAL_2_HOUR, INDICATOR_INTERVAL_4_HOUR, INDICATOR_INTERVAL_ONE_DAY (default),
                  INDICATOR_INTERVAL_WEEK, INDICATOR_INTERVAL_MONTH
        type_of_price: TYPE_OF_PRICE_CLOSE, TYPE_OF_PRICE_OPEN, TYPE_OF_PRICE_HIGH, TYPE_OF_PRICE_LOW, TYPE_OF_PRICE_AVG
        length: Indicator period in intervals (default: 14); MACD ignores it
        deviation: BB only — number of standard deviations between the middle and outer bands (default: 2)
        fast_length: MACD only — period of the fast EMA (default: 12)
        slow_length: MACD only — period of the slow EMA (default: 26)
        signal_smoothing: MACD only — period of the signal line (default: 9)
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
    # The API rejects BB without deviation and MACD without smoothing.
    if indicator_type == "INDICATOR_TYPE_BB":
        body["deviation"] = {"deviationMultiplier": _to_quotation(deviation)}
    if indicator_type == "INDICATOR_TYPE_MACD":
        body["smoothing"] = {
            "fastLength": fast_length,
            "slowLength": slow_length,
            "signalSmoothing": signal_smoothing,
        }
    data = await _call("MarketDataService", "GetTechAnalysis", body)
    return _fmt(data)


# ── Orders ───────────────────────────────────────────────────────────────────


@read_only_tool
async def get_orders(account_id: str) -> str:
    """Get list of active (pending) orders for an account.

    Returns: order_id, direction, type, status, price, quantity, instrument info.

    Args:
        account_id: Account ID
    """
    data = await _call("OrdersService", "GetOrders", {"accountId": account_id})
    return _fmt(data)


@read_only_tool
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


@read_only_tool
async def list_shares(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available shares (stocks).

    Warning: returns a large dataset. Use find_instrument for searching specific shares.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Shares", {"instrumentStatus": instrument_status})
    return _fmt(data)


@read_only_tool
async def list_bonds(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available bonds.

    Warning: returns a large dataset. Use find_instrument for searching specific bonds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Bonds", {"instrumentStatus": instrument_status})
    return _fmt(data)


@read_only_tool
async def list_etfs(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available ETFs and funds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Etfs", {"instrumentStatus": instrument_status})
    return _fmt(data)


@read_only_tool
async def list_currencies(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available currency instruments.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Currencies", {"instrumentStatus": instrument_status})
    return _fmt(data)


@read_only_tool
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
