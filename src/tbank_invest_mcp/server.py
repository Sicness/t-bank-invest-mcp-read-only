"""MCP server for T-Bank (Tinkoff) Invest API — read-only portfolio analytics."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import ssl
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

import certifi
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

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
        "instruments, market data, and orders. "
        "Prices and amounts are plain numbers. An amount's currency is the `currency` field "
        "of the object it is in; an amount in some other currency is written as "
        "{value, currency}. Lists of positions, operations and bond events leave out fields "
        "that are zero, false or empty. "
        "An instrument parameter takes a ticker, FIGI, ISIN or UID; TICKER_CLASSCODE "
        "(SBER_TQBR) picks one listing when a ticker has several. Search by name with "
        "find_instrument. "
        "Dates are UTC. A from_date/to_date given as YYYY-MM-DD covers whole days: "
        "to_date includes that day up to 23:59:59."
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


def _choices(*values: str) -> Any:
    """Type of a string parameter whose JSON schema lists the values to pick from.

    The list is the documented spelling, and a client may enforce it. The server itself
    validates nothing against it: _enum also takes a value without its prefix or in another
    case, which is leniency towards a caller that got through, not something to advertise.
    """
    return Annotated[str, Field(json_schema_extra={"enum": list(values)})]


# Enum values a tool checks itself, by their short names: the API silently ignores a filter
# value it does not know. The schema types below are built from the same tuples.
INSTRUMENT_ID_TYPES = ("FIGI", "TICKER", "UID", "POSITION_UID")
INSTRUMENT_KINDS = (
    "SHARE", "BOND", "ETF", "CURRENCY", "FUTURES", "OPTION", "SP", "CLEARING_CERTIFICATE",
    "INDEX", "COMMODITY",
)
PORTFOLIO_CURRENCIES = {"RUB": 0, "USD": 1, "EUR": 2}  # GetPortfolio takes the number
OPERATION_STATES = ("EXECUTED", "CANCELED", "PROGRESS")
BOND_EVENT_TYPES = ("CPN", "CALL", "MTY", "CONV")
# GetTechAnalysis names the same intervals differently from GetCandles.
INDICATOR_INTERVALS = {
    "CANDLE_INTERVAL_1_MIN": "INDICATOR_INTERVAL_ONE_MINUTE",
    "CANDLE_INTERVAL_2_MIN": "INDICATOR_INTERVAL_2_MIN",
    "CANDLE_INTERVAL_3_MIN": "INDICATOR_INTERVAL_3_MIN",
    "CANDLE_INTERVAL_5_MIN": "INDICATOR_INTERVAL_FIVE_MINUTES",
    "CANDLE_INTERVAL_10_MIN": "INDICATOR_INTERVAL_10_MIN",
    "CANDLE_INTERVAL_15_MIN": "INDICATOR_INTERVAL_FIFTEEN_MINUTES",
    "CANDLE_INTERVAL_30_MIN": "INDICATOR_INTERVAL_30_MIN",
    "CANDLE_INTERVAL_HOUR": "INDICATOR_INTERVAL_ONE_HOUR",
    "CANDLE_INTERVAL_2_HOUR": "INDICATOR_INTERVAL_2_HOUR",
    "CANDLE_INTERVAL_4_HOUR": "INDICATOR_INTERVAL_4_HOUR",
    "CANDLE_INTERVAL_DAY": "INDICATOR_INTERVAL_ONE_DAY",
    "CANDLE_INTERVAL_WEEK": "INDICATOR_INTERVAL_WEEK",
    "CANDLE_INTERVAL_MONTH": "INDICATOR_INTERVAL_MONTH",
}

InstrumentIdType = _choices(*("INSTRUMENT_ID_TYPE_" + t for t in INSTRUMENT_ID_TYPES))
InstrumentStatus = _choices("INSTRUMENT_STATUS_BASE", "INSTRUMENT_STATUS_ALL")
InstrumentKind = _choices("", *(k.lower() for k in INSTRUMENT_KINDS))
PortfolioCurrency = _choices(*PORTFOLIO_CURRENCIES)
OperationState = _choices("", *OPERATION_STATES)
BondEventType = _choices("", *BOND_EVENT_TYPES)
CandleInterval = _choices(
    "CANDLE_INTERVAL_5_SEC", "CANDLE_INTERVAL_10_SEC", "CANDLE_INTERVAL_30_SEC",
    "CANDLE_INTERVAL_1_MIN", "CANDLE_INTERVAL_2_MIN", "CANDLE_INTERVAL_3_MIN",
    "CANDLE_INTERVAL_5_MIN", "CANDLE_INTERVAL_10_MIN", "CANDLE_INTERVAL_15_MIN",
    "CANDLE_INTERVAL_30_MIN", "CANDLE_INTERVAL_HOUR", "CANDLE_INTERVAL_2_HOUR",
    "CANDLE_INTERVAL_4_HOUR", "CANDLE_INTERVAL_DAY", "CANDLE_INTERVAL_WEEK",
    "CANDLE_INTERVAL_MONTH",
)
IndicatorType = _choices(
    "INDICATOR_TYPE_SMA", "INDICATOR_TYPE_EMA", "INDICATOR_TYPE_RSI", "INDICATOR_TYPE_MACD",
    "INDICATOR_TYPE_BB",
)
IndicatorInterval = _choices(*INDICATOR_INTERVALS.values())
TypeOfPrice = _choices(
    "TYPE_OF_PRICE_CLOSE", "TYPE_OF_PRICE_OPEN", "TYPE_OF_PRICE_HIGH", "TYPE_OF_PRICE_LOW",
    "TYPE_OF_PRICE_AVG",
)


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


def _parse_date(
    s: str | None, default: datetime | None = None, *, end_of_day: bool = False
) -> datetime | None:
    """Parse a UTC date or datetime string; an empty one gives default.

    end_of_day is for the end of a range: a date without a time then means 23:59:59 of that
    day, so that "to 2024-01-31" includes the 31st. A string with a time is taken as is.
    """
    if not s:
        return default
    s = s.strip()
    try:
        day = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    else:
        return day + timedelta(days=1, seconds=-1) if end_of_day else day
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format.")


def _period(from_date: str, to_date: str, *, back: int = 0, ahead: int = 0) -> dict[str, str]:
    """The "from" and "to" of a request: the dates given, or by default from `back` days ago
    to `ahead` days from now. A to_date without a time includes that whole day."""
    now = datetime.now(timezone.utc)
    return {
        "from": _ts(_parse_date(from_date, now - timedelta(days=back))),
        "to": _ts(_parse_date(to_date, now + timedelta(days=ahead), end_of_day=True)),
    }


def _enum(value: str, prefix: str, allowed: tuple[str, ...] = ()) -> str:
    """Full enum name for the API from a value given with or without its prefix, in any case.

    allowed lists the valid short names for enums small enough to check here: the API
    silently ignores a filter value it does not know instead of rejecting it.
    """
    name = value.strip().upper().removeprefix(prefix)
    if allowed and name not in allowed:
        raise ValueError(f"Unknown value {value!r}; expected one of: {', '.join(allowed)}")
    return prefix + name


def _number(q: dict[str, Any]) -> int | float:
    """A Quotation or MoneyValue ({units, nano}) as a number; an int when it is whole."""
    units, nano = int(q.get("units", 0)), int(q.get("nano", 0))
    return units if nano == 0 else round(units + nano / 1_000_000_000, 9)


def _number_at(obj: dict, key: str) -> int | float | None:
    """The Quotation obj[key] as a number; None when it is missing or empty."""
    return _number(obj[key]) if obj.get(key) else None


def _is_quotation(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and value.keys() <= {"units", "nano"}


def _is_money(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("currency"), str)
        and ("units" in value or "nano" in value)
        and value.keys() <= {"currency", "units", "nano"}
    )


def _plain(data: Any) -> Any:
    """An API response with every {units, nano} pair turned into a plain number.

    A Quotation becomes a number. So does a MoneyValue, and its currency is named once, in
    the `currency` field of the object holding it — the field the API often has there
    anyway. When the amounts of one object are in different currencies, or the object's own
    `currency` says something else, each amount stays explicit as {value, currency}.
    """
    if isinstance(data, list):
        return [_plain(item) for item in data]
    if not isinstance(data, dict):
        return data
    if _is_quotation(data):
        return _number(data)
    if _is_money(data):  # an amount on its own, e.g. an item of a list of balances
        return {"value": _number(data), "currency": data["currency"]} if data["currency"] else _number(data)

    currencies = {v["currency"].lower() for v in data.values() if _is_money(v) and v["currency"]}
    shared = next(iter(currencies)) if len(currencies) == 1 else None
    own = data.get("currency")
    if shared and own is not None and (not isinstance(own, str) or own.lower() != shared):
        shared = None

    out: dict[str, Any] = {}
    if shared and own is None:
        out["currency"] = shared
    for key, value in data.items():
        if _is_money(value) and (shared or not value["currency"]):
            out[key] = _number(value)
        else:
            out[key] = _plain(value)
    return out


def _is_empty(value: Any) -> bool:
    return value is None or value is False or value in (0, "0", "") or value == [] or value == {}


def _trimmed(data: Any, *list_keys: str, drop: tuple[str, ...] = ()) -> Any:
    """_plain(data) whose items in the named lists have lost their zero, false and empty fields.

    Positions, operations and bond events are long lists of wide objects in which most
    fields say "nothing here"; leaving those out is what makes such a response fit into a
    model's context. drop names fields to leave out whatever they hold.
    """
    out = _plain(data)
    for key in list_keys:
        if isinstance(out.get(key), list):
            out[key] = [
                {k: v for k, v in item.items() if k not in drop and not _is_empty(v)}
                if isinstance(item, dict) else item
                for item in out[key]
            ]
    return out


def _fmt(data: Any, *list_keys: str, drop: tuple[str, ...] = ()) -> str:
    """What a tool returns: the response made plain, as compact JSON. With list_keys (and
    drop), the items of those lists are trimmed as well — see _trimmed."""
    # Compact: the reader is a model, and indentation is a third or more of a response.
    return json.dumps(_trimmed(data, *list_keys, drop=drop), ensure_ascii=False, separators=(",", ":"))


def _to_quotation(value: float) -> dict[str, Any]:
    """Convert a number to a Quotation object ({units, nano}) for a request body."""
    units = int(value)
    return {"units": str(units), "nano": round((value - units) * 1_000_000_000)}


# ── Instrument identifiers ──────────────────────────────────────────────────

_UID_RE = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
# Bloomberg FIGIs and the ones T-Bank assigns itself. Other 12-character identifiers — ISINs,
# bond tickers — are not FIGIs and do need a lookup.
_FIGI_RE = re.compile(r"(BBG|TCS)[0-9A-Z]{9}")

# (identifier, kind, any_listing) → the instrument it names. Kept for the life of the
# process: an identifier does not change what it names.
_resolved: dict[tuple[str, str, bool], dict] = {}
# The same key → when a lookup last found nothing. That is only remembered for a while: a
# paper may be listed tomorrow, and a search may come back empty once.
_missed: dict[tuple[str, str, bool], float] = {}
MISS_TTL_SECONDS = 600
# How many identifiers of one list are looked up at a time; the API allows 200 requests a
# minute per service, and a list can hold a whole portfolio.
LOOKUP_BATCH = 8


def _is_uid(identifier: str) -> bool:
    return bool(_UID_RE.fullmatch(identifier))


async def _search(query: str, kind: str = "", tradable_only: bool = True) -> list[dict]:
    body: dict[str, Any] = {"query": query}
    if kind:
        body["instrumentKind"] = _enum(kind, "INSTRUMENT_TYPE_", INSTRUMENT_KINDS)
    if tradable_only:
        body["apiTradeAvailableFlag"] = True
    data = await _call("InstrumentsService", "FindInstrument", body)
    return data.get("instruments", [])


def _exact(instruments: list[dict], identifier: str, class_code: str = "") -> list[dict]:
    """The hits that carry identifier as their ticker, FIGI, ISIN or UID, one per instrument."""
    wanted = identifier.upper()
    found: dict[str, dict] = {}
    for i in instruments:
        if class_code and i.get("classCode", "").upper() != class_code.upper():
            continue
        if wanted in (i.get(k, "").upper() for k in ("ticker", "figi", "isin", "uid")):
            found.setdefault(i.get("uid", ""), i)
    return list(found.values())


async def _find_exact(identifier: str, kind: str = "", any_listing: bool = False) -> dict | None:
    """The instrument a ticker, FIGI, ISIN or TICKER_CLASSCODE names, or None if none does.

    Listings tradable through the API are preferred — for a share that leaves its main
    board out of a dozen technical ones. Raises ValueError when several instruments still
    match, naming them, rather than picking one silently.

    Several listings of one paper (one ISIN) are told apart by which of them has candle
    history. If that does not single one out, any_listing decides: callers after something
    the paper has whatever board it trades on — dividends, coupons, fundamentals — take the
    first, the rest get the error. Different papers under one ticker are always an error.
    """
    identifier = identifier.strip()
    key = (identifier.upper(), kind.upper(), any_listing)
    if key in _resolved:
        return _resolved[key]
    if time.monotonic() - _missed.get(key, float("-inf")) < MISS_TTL_SECONDS:
        return None

    attempts = [(identifier, "")]
    if "_" in identifier:  # after the plain reading: tickers such as CNYRUB_TOM have one too
        attempts.append(tuple(identifier.rsplit("_", 1)))
    hits: list[dict] = []
    for query, class_code in attempts:
        for tradable_only in (True, False):
            hits = _exact(await _search(query, kind, tradable_only), query, class_code)
            if hits:
                break
        if hits:
            break

    if len(hits) > 1 and len({i.get("isin") for i in hits}) == 1 and hits[0].get("isin"):
        # Several listings of one paper. The API keeps candle history for one of them — the
        # board the paper really trades on; the rest are negotiated-deal and technical boards.
        with_history = [i for i in hits if i.get("first1dayCandleDate")]
        if len(with_history) == 1 or (with_history and any_listing):
            hits = with_history[:1]
        elif any_listing:
            hits = hits[:1]
    if len(hits) > 1:
        names = ", ".join(
            f"{i.get('ticker')}_{i.get('classCode')} ({i.get('name')}, {i.get('instrumentType')})"
            for i in hits[:8]
        )
        raise ValueError(
            f"{identifier!r} names {len(hits)} instruments: {names}. "
            "Pass one of these TICKER_CLASSCODE forms or the instrument's UID."
        )
    if not hits:
        _missed[key] = time.monotonic()
        return None
    _resolved[key] = hits[0]
    return hits[0]


async def _uid(
    identifier: str, kind: str = "", *, figi_ok: bool = True, any_listing: bool = False
) -> str:
    """What to send the API for a ticker, FIGI, ISIN or UID: the instrument's UID.

    A UID needs no lookup, and neither does a FIGI where the method takes one (figi_ok;
    false for the few that take a UID only). An identifier nothing matches is returned as
    it came, so the API gets to answer for it the way it always has — unless it is plainly
    a name, which is an error here. any_listing: see _find_exact.
    """
    identifier = identifier.strip()
    if not identifier or _is_uid(identifier):
        return identifier
    if figi_ok and _FIGI_RE.fullmatch(identifier):
        return identifier
    instrument = await _find_exact(identifier, kind, any_listing)
    if instrument:
        return instrument["uid"]
    if not identifier.isascii() or " " in identifier:
        # Not something the API could take for an identifier either: a name.
        raise ValueError(
            f"No instrument has {identifier!r} as its ticker, FIGI, ISIN or UID. "
            "find_instrument searches by name"
        )
    return identifier


def _csv(values: str) -> list[str]:
    """The items of a comma-separated parameter, stripped, empty ones left out."""
    return [v.strip() for v in values.split(",") if v.strip()]


async def _each(identifiers: list[str], resolve: Callable[[str], Any]) -> list[str]:
    """resolve() for every identifier of a list: each distinct one once, a few at a time."""
    distinct = list(dict.fromkeys(identifiers))
    resolved: dict[str, str] = {}
    for start in range(0, len(distinct), LOOKUP_BATCH):
        batch = distinct[start:start + LOOKUP_BATCH]
        resolved.update(zip(batch, await asyncio.gather(*(resolve(i) for i in batch))))
    return [resolved[i] for i in identifiers]


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
async def get_portfolio(account_id: str, currency: PortfolioCurrency = "RUB") -> str:
    """Get full portfolio for an account: total values by asset type, all positions with prices, yields, and quantities.

    Each position has ticker, classCode, figi, instrumentUid, instrumentType, quantity,
    averagePositionPrice, currentPrice, expectedYield, dailyYield, currentNkd (bonds) and its
    `currency`. Amounts are plain numbers; a field that is zero or false is left out, and so
    are positionUid and the two fields the API has deprecated.

    Args:
        account_id: Account ID (get from get_accounts)
        currency: Portfolio currency — RUB, USD, or EUR (default: RUB)
    """
    code = currency.strip().upper()
    if code not in PORTFOLIO_CURRENCIES:
        raise ValueError(f"currency must be one of {', '.join(PORTFOLIO_CURRENCIES)}, got {currency!r}")
    body: dict[str, Any] = {"accountId": account_id, "currency": PORTFOLIO_CURRENCIES[code]}
    data = await _call("OperationsService", "GetPortfolio", body)
    # averagePositionPricePt and quantityLots are deprecated in the API contract. positionUid
    # is a second identifier of what instrumentUid already names, and a seventh of the size.
    return _fmt(
        data, "positions", "virtualPositions",
        drop=("averagePositionPricePt", "quantityLots", "positionUid"),
    )


@read_only_tool
async def get_positions(account_id: str) -> str:
    """Get all positions in an account: securities, futures, options, and cash balances.

    Unlike get_portfolio, this returns raw position balances without price calculations.
    A field that is zero or false (blocked, exchangeBlocked) is left out, and so is
    positionUid; instrumentUid identifies the instrument.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetPositions", {"accountId": account_id})
    return _fmt(data, "securities", "futures", "options", drop=("positionUid",))


@read_only_tool
async def get_withdraw_limits(account_id: str) -> str:
    """Get available withdrawal limits for an account: free cash, blocked amounts, futures guarantees.

    Args:
        account_id: Account ID (get from get_accounts)
    """
    data = await _call("OperationsService", "GetWithdrawLimits", {"accountId": account_id})
    return _fmt(data)


# ── Operations ───────────────────────────────────────────────────────────────

# Fields of an operation that say again what another field or the request already says:
# the operation type and the instrument under a second name, the account that was asked
# for, a per-item cursor next to the page's nextCursor. A third of every item.
_OPERATION_REPEATS = (
    "operationType", "instrumentKind", "positionUid", "assetUid", "brokerAccountId", "cursor",
)


@read_only_tool
async def get_operations(
    account_id: str,
    from_date: str = "",
    to_date: str = "",
    state: OperationState = "",
    figi: str = "",
) -> str:
    """Get list of operations (transactions) for an account within a date range.

    Returns: buys, sells, dividends, coupons, taxes, commissions, deposits, withdrawals, etc.
    Each operation has: id, type, date, payment amount, instrument info, quantity, trades.
    A field that is zero or empty is left out, and so are fields that repeat another one
    (operationType repeats type; positionUid and assetUid name what instrumentUid names).

    Note: this method has no paging and an active account has hundreds of operations a
    year — keep the range to a month or two, or use get_operations_by_cursor.

    Args:
        account_id: Account ID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD, inclusive), default: now
        state: Filter by state: EXECUTED, CANCELED, PROGRESS (empty = all)
        figi: Filter by instrument — FIGI, ticker, ISIN or UID (empty = all instruments)
    """
    body: dict[str, Any] = {"accountId": account_id, **_period(from_date, to_date, back=30)}
    if state:
        body["state"] = _enum(state, "OPERATION_STATE_", OPERATION_STATES)
    if figi:
        # This method filters by FIGI only; take it from whatever names the instrument.
        figi = figi.strip()
        instrument = None if _FIGI_RE.fullmatch(figi) else await _find_exact(figi)
        body["figi"] = (instrument or {}).get("figi") or figi
    data = await _call("OperationsService", "GetOperations", body)
    return _fmt(data, "operations", drop=_OPERATION_REPEATS)


@read_only_tool
async def get_operations_by_cursor(
    account_id: str,
    from_date: str = "",
    to_date: str = "",
    cursor: str = "",
    limit: int = 50,
    instrument_id: str = "",
    operation_types: str = "",
    state: OperationState = "",
    without_commissions: bool = False,
    without_trades: bool = False,
) -> str:
    """Get operations with cursor-based pagination. Better for large histories.

    Returns hasNext and nextCursor for pagination: pass nextCursor as cursor to get the
    next page. Each operation item includes detailed info: payment, price, commission,
    yield, quantity, trades, ticker. A field that is zero or empty is left out, and so are
    fields that repeat another one or the request (instrumentKind, positionUid, assetUid,
    brokerAccountId, the per-item cursor).

    Common operation types: BUY, SELL, DIVIDEND, COUPON, TAX, BOND_TAX, INPUT, OUTPUT,
    BROKER_FEE, BOND_REPAYMENT_FULL, BOND_REPAYMENT.

    Args:
        account_id: Account ID
        from_date: Start date (YYYY-MM-DD), default: 1 year ago
        to_date: End date (YYYY-MM-DD, inclusive), default: now
        cursor: Cursor from previous response for pagination
        limit: Number of operations per page (1-1000, default: 50; a page of 50 is about
            25,000 characters, and a client refuses a result several times that)
        instrument_id: Filter by instrument — ticker, FIGI, ISIN or UID
        operation_types: Comma-separated operation types (e.g. "BUY,SELL,DIVIDEND")
        state: Filter by state: EXECUTED, CANCELED, PROGRESS
        without_commissions: Exclude commission operations
        without_trades: Exclude trade details from response
    """
    body: dict[str, Any] = {
        "accountId": account_id,
        **_period(from_date, to_date, back=365),
        "limit": min(max(limit, 1), 1000),
        "withoutCommissions": without_commissions,
        "withoutTrades": without_trades,
    }
    if cursor:
        body["cursor"] = cursor
    if instrument_id:
        body["instrumentId"] = await _uid(instrument_id)
    if operation_types:
        body["operationTypes"] = [_enum(t, "OPERATION_TYPE_") for t in _csv(operation_types)]
    if state:
        body["state"] = _enum(state, "OPERATION_STATE_", OPERATION_STATES)
    data = await _call("OperationsService", "GetOperationsByCursor", body)
    return _fmt(data, "items", drop=_OPERATION_REPEATS)


# ── Instruments ──────────────────────────────────────────────────────────────


_SEARCH_FIELDS = ("ticker", "classCode", "name", "instrumentType", "uid", "figi", "isin", "lot")


@read_only_tool
async def find_instrument(
    query: str,
    instrument_kind: InstrumentKind = "",
    tradable_only: bool = True,
    limit: int = 20,
) -> str:
    """Search for instruments by text query (ticker, name, ISIN, FIGI).

    Returns {"instruments": [...], "total": N}. Each instrument has ticker, classCode, name,
    instrumentType, uid, figi, isin and lot; forQualInvestorFlag appears when it is true and
    apiTradeAvailableFlag when it is false. An instrument whose ticker, ISIN or FIGI equals
    the query comes first. "total" counts every match; "note" says when the list was cut to
    limit or when nothing tradable matched and non-tradable listings are shown instead.

    A paper has many listings (one per board, most of them not tradable), and a company's
    name also matches all its bonds — narrow the search with instrument_kind.

    Args:
        query: Search string (e.g. "SBER", "Газпром", "Apple")
        instrument_kind: Only this kind — share, bond, etf, currency, futures, option, sp,
            clearing_certificate, index, commodity (empty = any)
        tradable_only: Only listings tradable through the API (default: true). False also
            returns delisted papers and technical boards.
        limit: Maximum number of instruments to return (1-200, default: 20)
    """
    limit = min(max(limit, 1), 200)
    found = await _search(query, instrument_kind, tradable_only)
    note = ""
    if not found and tradable_only:
        found = await _search(query, instrument_kind, tradable_only=False)
        if found:
            note = "nothing tradable through the API matched; these listings are not tradable"

    exact = {i.get("uid") for i in _exact(found, query.strip())}
    # Stable: the API's own order is kept within each group.
    found.sort(key=lambda i: (i.get("uid") not in exact, not i.get("apiTradeAvailableFlag")))

    instruments = []
    for i in found[:limit]:
        item = {k: i[k] for k in _SEARCH_FIELDS if k in i}
        if i.get("forQualInvestorFlag"):
            item["forQualInvestorFlag"] = True
        if not i.get("apiTradeAvailableFlag"):
            item["apiTradeAvailableFlag"] = False
        instruments.append(item)

    result: dict[str, Any] = {"instruments": instruments, "total": len(found)}
    notes = [note] if note else []
    if len(found) > limit:
        notes.append(f"showing {limit} of {len(found)}; narrow the query or instrument_kind, or raise limit")
    if notes:
        result["note"] = "; ".join(notes)
    return _fmt(result)


async def _instrument_ref(id: str, id_type: str, class_code: str, kind: str = "") -> dict[str, Any]:
    """Request fields naming one instrument for the *By methods.

    The API wants to be told what kind of identifier it is given and takes a ticker only
    with its class code. A caller should not have to know either, so the identifier goes
    through _uid; id_type and class_code still work as before.
    """
    id = id.strip()
    id_type = _enum(id_type or "FIGI", "INSTRUMENT_ID_TYPE_", INSTRUMENT_ID_TYPES)
    if class_code:
        # A class code only goes with a ticker, whatever id_type was left at.
        if id_type == "INSTRUMENT_ID_TYPE_FIGI":
            id_type = "INSTRUMENT_ID_TYPE_TICKER"
        return {"idType": id_type, "id": id, "classCode": class_code}
    if id_type in ("INSTRUMENT_ID_TYPE_UID", "INSTRUMENT_ID_TYPE_POSITION_UID"):
        return {"idType": id_type, "id": id}
    ref = await _uid(id, kind)
    return {"idType": "INSTRUMENT_ID_TYPE_UID" if _is_uid(ref) else id_type, "id": ref}


@read_only_tool
async def get_instrument_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed instrument info by its identifier.

    Returns: name, ticker, figi, uid, lot size, currency, country, sector, trading status, etc.

    Args:
        id: Instrument ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code)
    data = await _call("InstrumentsService", "GetInstrumentBy", body)
    return _fmt(data)


@read_only_tool
async def get_bond_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed bond info: maturity date, coupon rate, nominal, ACI, issue size, risk level.

    Args:
        id: Bond ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code, "bond")
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
        figi: Deprecated, kept for existing callers — pass the FIGI as instrument_id instead
        instrument_id: Bond ticker, FIGI, ISIN or UID (required)
        from_date: Start date (YYYY-MM-DD), default: now
        to_date: End date (YYYY-MM-DD, inclusive), default: 1 year from now
    """
    # Both have defaults only so that the old figi parameter keeps working. Left to the API,
    # a call with neither fails with "Missing parameter: figi", which points at the wrong one.
    if not (instrument_id or figi):
        raise ValueError("instrument_id is required: the bond's ticker, FIGI, ISIN or UID")
    body: dict[str, Any] = _period(from_date, to_date, ahead=365)
    if instrument_id:
        body["instrumentId"] = await _uid(instrument_id, "bond", any_listing=True)
    if figi:
        body["figi"] = figi
    data = await _call("InstrumentsService", "GetBondCoupons", body)
    return _fmt(data)


# Names this tool's description used to give. The API never knew them and ignored the filter.
BOND_EVENT_ALIASES = {"COUPON": "CPN", "MATURITY": "MTY", "CONVERSION": "CONV"}


@read_only_tool
async def get_bond_events(
    instrument_id: str,
    type: BondEventType = "",
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get bond events: coupon payments, offers (calls), maturity, conversions.

    Without dates the API returns only a window of a few years around today, so a bond's
    maturity or a distant offer needs an explicit from_date/to_date range to show up.
    A field of an event that is zero or empty is left out.

    Args:
        instrument_id: Bond ticker, FIGI, ISIN or UID
        type: Event type filter (empty = all): CPN (coupon), CALL (offer), MTY (maturity),
            CONV (conversion). The EVENT_TYPE_ prefix is optional; COUPON, MATURITY and
            CONVERSION are accepted too.
        from_date: Start date (YYYY-MM-DD), default: chosen by the API
        to_date: End date (YYYY-MM-DD, inclusive), default: chosen by the API
    """
    body: dict[str, Any] = {}
    if type:  # checked before anything is requested
        name = type.strip().upper()
        body["type"] = _enum(BOND_EVENT_ALIASES.get(name, type), "EVENT_TYPE_", BOND_EVENT_TYPES)
    body["instrumentId"] = await _uid(instrument_id, "bond", any_listing=True)
    if from_date:
        body["from"] = _ts(_parse_date(from_date))
    if to_date:
        body["to"] = _ts(_parse_date(to_date, end_of_day=True))
    data = await _call("InstrumentsService", "GetBondEvents", body)
    return _fmt(data, "events")


@read_only_tool
async def get_share_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed share (stock) info: sector, dividend yield, IPO date, issue size, country.

    Args:
        id: Share ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code, "share")
    data = await _call("InstrumentsService", "ShareBy", body)
    return _fmt(data)


@read_only_tool
async def get_etf_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed ETF/fund info: management fee, tracking index, rebalance frequency.

    Args:
        id: ETF ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code, "etf")
    data = await _call("InstrumentsService", "EtfBy", body)
    return _fmt(data)


@read_only_tool
async def get_currency_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed currency instrument info.

    Args:
        id: Currency ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code, "currency")
    data = await _call("InstrumentsService", "CurrencyBy", body)
    return _fmt(data)


@read_only_tool
async def get_future_by(
    id: str,
    id_type: InstrumentIdType = "INSTRUMENT_ID_TYPE_FIGI",
    class_code: str = "",
) -> str:
    """Get detailed futures contract info: expiration, basic asset, margin requirements.

    Args:
        id: Future ticker, FIGI, ISIN or UID — which one it is gets recognised automatically
        id_type: Only needed with class_code: INSTRUMENT_ID_TYPE_TICKER. Otherwise leave the default.
        class_code: Board of a ticker (e.g. "TQBR"), to pick one listing out of several
    """
    body = await _instrument_ref(id, id_type, class_code, "futures")
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
        instrument_id: Instrument ticker, FIGI, ISIN or UID
        from_date: Start date (YYYY-MM-DD), default: 2 years ago
        to_date: End date (YYYY-MM-DD, inclusive), default: 1 year ahead
    """
    data = await _call("InstrumentsService", "GetDividends", {
        "instrumentId": await _uid(instrument_id, any_listing=True),
        **_period(from_date, to_date, back=730, ahead=365),
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
        instrument_id: Bond ticker, FIGI, ISIN or UID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD, inclusive), default: now
    """
    data = await _call("InstrumentsService", "GetAccruedInterests", {
        "instrumentId": await _uid(instrument_id, "bond", any_listing=True),
        **_period(from_date, to_date, back=30),
    })
    return _fmt(data)


@read_only_tool
async def get_asset_fundamentals(assets: str) -> str:
    """Get fundamental financial data for assets: P/E, P/BV, EPS, ROE, revenue, market cap, etc.

    The API keys fundamentals by asset UID, which is not the instrument UID; whatever is
    passed here is converted. Each item of the result carries its assetUid.

    Args:
        assets: Comma-separated list of tickers, FIGIs, ISINs, instrument UIDs or asset UIDs
    """
    asset_list = await _each(_csv(assets), _asset_uid_for)
    data = await _call("InstrumentsService", "GetAssetFundamentals", {"assets": asset_list})
    return _fmt(data)


# instrument UID → asset UID, or "" for a UID that is not an instrument's (an asset UID is
# passed here too); neither ever changes.
_asset_uids: dict[str, str] = {}


async def _asset_uid(instrument_uid: str) -> str:
    """Asset UID of an instrument, or "" if instrument_uid is not a known instrument UID.

    Fundamentals and consensus forecasts are keyed by asset UID, which is a different
    identifier from the instrument UID that FindInstrument and the *By lookups return.
    """
    if instrument_uid in _asset_uids:
        return _asset_uids[instrument_uid]
    try:
        data = await _call("InstrumentsService", "GetInstrumentBy", {
            "idType": "INSTRUMENT_ID_TYPE_UID",
            "id": instrument_uid,
        })
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        data = {}
    asset_uid = data.get("instrument", {}).get("assetUid", "")
    _asset_uids[instrument_uid] = asset_uid
    return asset_uid


async def _asset_uid_for(identifier: str) -> str:
    """Asset UID for a ticker, FIGI, ISIN, instrument UID or asset UID."""
    uid = await _uid(identifier, figi_ok=False, any_listing=True)
    if not _is_uid(uid):
        raise ValueError(
            f"No instrument matches {identifier!r}. Name it by ticker, FIGI, ISIN or UID; "
            "find_instrument searches by name"
        )
    # A UID the instrument lookup does not know is taken to be an asset UID already.
    return await _asset_uid(uid) or uid


async def _consensus_forecast(asset_uid: str, page_limit: int = 100, max_pages: int = 50) -> dict:
    """Scan GetConsensusForecasts pages for the item of asset_uid.

    Returns the item, or {"error": ...} saying whether the whole list was scanned or the
    scan was cut short by max_pages.
    """
    if not asset_uid:
        return {"error": "No asset UID to look a consensus forecast up by"}
    if page_limit < 1:
        # What the API itself does with a non-positive limit; say so in the request, because
        # clamping to 1 would turn the scan into a request per item.
        page_limit = 100
    seen = 0
    for page_number in range(max(max_pages, 1)):
        data = await _call("InstrumentsService", "GetConsensusForecasts", {
            "paging": {"limit": page_limit, "pageNumber": page_number},
        })
        items = data.get("items", [])
        for item in items:
            # An item's own "uid" identifies the forecast record, not the instrument.
            if item.get("assetUid") == asset_uid:
                return item

        # Counted from what actually came back, not from the page size that was asked for.
        seen += len(items)
        if not items or seen >= data.get("page", {}).get("totalCount", 0):
            return {"error": f"No consensus forecast found for asset {asset_uid}"}

    return {"error": (
        f"No consensus forecast found for asset {asset_uid} in the first {max_pages} pages; "
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
        instrument_id: Ticker, FIGI, ISIN, instrument UID or asset UID
        page_limit: Page size used while scanning (default: 100; a non-positive value means 100)
        max_pages: Safety cap on how many pages to scan before giving up (default: 50, at least 1)
    """
    # A UID the instrument lookup does not know is taken to be an asset UID already.
    uid = await _uid(instrument_id, figi_ok=False, any_listing=True)
    asset_uid = await _asset_uid(uid) or uid
    return _fmt(await _consensus_forecast(asset_uid, page_limit, max_pages))


def _pick_instrument(instruments: list[dict], query: str, class_code: str = "") -> dict | None:
    """Choose one FindInstrument hit: an exact ticker/ISIN/FIGI match beats search order."""
    if class_code:
        instruments = [i for i in instruments if i.get("classCode", "").upper() == class_code.upper()]
    candidates = _exact(instruments, query.strip()) or instruments
    return next((i for i in candidates if i.get("apiTradeAvailableFlag")), next(iter(candidates), None))


@read_only_tool
async def get_stock_snapshot(ticker: str, candle_days: int = 5, class_code: str = "") -> str:
    """Get a one-call overview of a share: fundamentals, recent price change, and analyst consensus.

    Convenience wrapper around FindInstrument + GetInstrumentBy + GetAssetFundamentals +
    GetCandles + GetConsensusForecasts, so a caller doesn't need separate round trips (and
    the manual ticker → UID → asset UID resolution) to get a compact picture of one share.

    Returns ticker, class_code, uid, asset_uid and name of the share it resolved to — check
    them when the query is ambiguous — plus price, fundamentals and consensus. Returns
    {"error": ...} if no share matches.

    price holds last_close and last_close_date (the latest finished session), change_pct over
    change_sessions finished sessions, and — only while today's session is still open —
    current_price, which is not a close.

    Args:
        ticker: Ticker, name, ISIN, or FIGI of a share (searched with FindInstrument; an exact
            ticker/ISIN/FIGI match is preferred over the first search hit)
        candle_days: Number of daily candles (trading sessions) the price change spans (default: 5)
        class_code: Optional class code to disambiguate listings (e.g. "TQBR")
    """
    if candle_days < 1:
        raise ValueError(f"candle_days must be at least 1, got {candle_days}")

    hits = await _search(ticker, "share", tradable_only=False)
    rivals = _exact([i for i in hits if i.get("apiTradeAvailableFlag")], ticker.strip(), class_code)
    if len({i.get("isin") for i in rivals}) > 1:
        names = ", ".join(f"{i.get('ticker')} on {i.get('classCode')} ({i.get('name')})" for i in rivals[:8])
        return _fmt({"error": f"{ticker!r} names several shares: {names}. Pass class_code to choose one."})
    instrument = _pick_instrument(hits, ticker, class_code)
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
            # Calendar window wide enough to hold candle_days + 1 finished sessions across
            # weekends and long holidays.
            "from": _ts(now - timedelta(days=candle_days * 3 // 2 + 14)),
            "to": _ts(now),
            "interval": "CANDLE_INTERVAL_DAY",
        }),
        _consensus_forecast(asset_uid),
    )

    # Today's candle is unfinished while the session is open: its "close" is the price right
    # now. Closes and the change are taken from finished sessions only.
    all_candles = candles_data.get("candles", [])
    finished = [c for c in all_candles if c.get("isComplete", True)]

    # The change is measured from the close before the first of the last candle_days sessions.
    candles = finished[-(candle_days + 1):]
    price: dict[str, Any] = {}
    if candles:
        base_close = _number_at(candles[0], "close")
        last_close = _number_at(candles[-1], "close")
        price["last_close"] = last_close
        if candles[-1].get("time"):
            price["last_close_date"] = candles[-1]["time"][:10]
        if len(candles) > 1 and base_close and last_close is not None:
            price["change_pct"] = round((last_close - base_close) / base_close * 100, 2)
            price["change_sessions"] = len(candles) - 1
    if all_candles and not all_candles[-1].get("isComplete", True):
        price["current_price"] = _number_at(all_candles[-1], "close")

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
        instrument_id: Instrument ticker, FIGI, ISIN or UID
    """
    data = await _call("InstrumentsService", "GetForecastBy", {
        "instrumentId": await _uid(instrument_id, figi_ok=False, any_listing=True),
    })
    return _fmt(data)


@read_only_tool
async def get_asset_reports(
    instrument_id: str,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Get upcoming and past earnings report dates for an instrument's issuer.

    Args:
        instrument_id: Instrument ticker, FIGI, ISIN or UID
        from_date: Start date (YYYY-MM-DD), default: now
        to_date: End date (YYYY-MM-DD, inclusive), default: 1 year ahead
    """
    data = await _call("InstrumentsService", "GetAssetReports", {
        "instrumentId": await _uid(instrument_id, figi_ok=False, any_listing=True),
        **_period(from_date, to_date, ahead=365),
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
        to_date: End date (YYYY-MM-DD, inclusive), default: 7 days ahead
    """
    body: dict[str, Any] = _period(from_date, to_date, ahead=7)
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
    interval: CandleInterval = "CANDLE_INTERVAL_DAY",
) -> str:
    """Get historical candles (OHLCV) for an instrument.

    Returns {"columns": ["time", "open", "high", "low", "close", "volume", "volumeBuy",
    "volumeSell"], "candles": [...]}: one row per candle, oldest first, in the order of
    "columns". Volumes are in lots; the two columns splitting volume into buys and sells are
    there when the API has them. For day, week and month candles "time" is a date.
    "last_candle_complete": false appears when the last candle's period is still running —
    its close is the current price, not a close.

    The API limits the period one request may span: a day for minute candles, a week for
    5-10 minute ones, 3 weeks for 15-30 minute ones, 3 months for hourly ones, 6 years for
    daily ones.

    Args:
        instrument_id: Instrument ticker, FIGI, ISIN or UID
        from_date: Start date (YYYY-MM-DD), default: 30 days ago
        to_date: End date (YYYY-MM-DD, inclusive), default: now
        interval: Candle interval — CANDLE_INTERVAL_1_MIN, CANDLE_INTERVAL_5_MIN,
                  CANDLE_INTERVAL_15_MIN, CANDLE_INTERVAL_HOUR, CANDLE_INTERVAL_DAY,
                  CANDLE_INTERVAL_WEEK, CANDLE_INTERVAL_MONTH (also 5/10/30_SEC,
                  2/3/10/30_MIN, 2/4_HOUR)
    """
    interval = _enum(interval, "CANDLE_INTERVAL_")
    data = await _call("MarketDataService", "GetCandles", {
        "instrumentId": await _uid(instrument_id),
        **_period(from_date, to_date, back=30),
        "interval": interval,
    })
    candles = data.get("candles", [])
    dates_only = interval in ("CANDLE_INTERVAL_DAY", "CANDLE_INTERVAL_WEEK", "CANDLE_INTERVAL_MONTH")

    def lots(candle: dict, key: str) -> int | None:
        return int(candle[key]) if candle.get(key) is not None else None

    # Buy and sell volume are not there for every instrument and period.
    sides = [k for k in ("volumeBuy", "volumeSell") if any(k in c for c in candles)]
    result: dict[str, Any] = {
        "columns": ["time", "open", "high", "low", "close", "volume", *sides],
        "candles": [
            [
                c.get("time", "")[:10] if dates_only else c.get("time", ""),
                *(_number_at(c, k) for k in ("open", "high", "low", "close")),
                int(c.get("volume") or 0),
                *(lots(c, k) for k in sides),
            ]
            for c in candles
        ],
    }
    if candles and not candles[-1].get("isComplete", True):
        result["last_candle_complete"] = False
    return _fmt(result)


async def _uids(instrument_ids: str) -> list[str]:
    """Instrument UIDs for a comma-separated list of tickers, FIGIs, ISINs or UIDs."""
    return await _each(_csv(instrument_ids), _uid)


@read_only_tool
async def get_last_prices(instrument_ids: str) -> str:
    """Get last trade prices for one or more instruments.

    Args:
        instrument_ids: Comma-separated list of tickers, FIGIs, ISINs or UIDs
    """
    ids = await _uids(instrument_ids)
    data = await _call("MarketDataService", "GetLastPrices", {"instrumentId": ids})
    return _fmt(data)


@read_only_tool
async def get_order_book(instrument_id: str, depth: int = 20) -> str:
    """Get order book (market depth) for an instrument: bids, asks, last price, spread.

    Args:
        instrument_id: Instrument ticker, FIGI, ISIN or UID
        depth: Order book depth 1-50 (default: 20)
    """
    data = await _call("MarketDataService", "GetOrderBook", {
        "instrumentId": await _uid(instrument_id),
        "depth": min(max(depth, 1), 50),
    })
    return _fmt(data)


@read_only_tool
async def get_close_prices(instrument_ids: str) -> str:
    """Get previous trading session close prices for instruments.

    Args:
        instrument_ids: Comma-separated list of tickers, FIGIs, ISINs or UIDs
    """
    instruments = [{"instrumentId": i} for i in await _uids(instrument_ids)]
    data = await _call("MarketDataService", "GetClosePrices", {"instruments": instruments})
    return _fmt(data)


@read_only_tool
async def get_trading_status(instrument_id: str) -> str:
    """Get current trading status for an instrument: is it tradeable, auction phase, etc.

    Args:
        instrument_id: Instrument ticker, FIGI, ISIN or UID
    """
    data = await _call("MarketDataService", "GetTradingStatus", {"instrumentId": await _uid(instrument_id)})
    return _fmt(data)



@read_only_tool
async def get_tech_analysis(
    instrument_id: str,
    indicator_type: IndicatorType,
    from_date: str = "",
    to_date: str = "",
    interval: IndicatorInterval = "INDICATOR_INTERVAL_ONE_DAY",
    type_of_price: TypeOfPrice = "TYPE_OF_PRICE_CLOSE",
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
        instrument_id: Instrument ticker, FIGI, ISIN or UID
        indicator_type: INDICATOR_TYPE_SMA, INDICATOR_TYPE_EMA, INDICATOR_TYPE_RSI,
                       INDICATOR_TYPE_MACD, INDICATOR_TYPE_BB
        from_date: Start date (YYYY-MM-DD), default: 90 days ago
        to_date: End date (YYYY-MM-DD, inclusive), default: now
        interval: INDICATOR_INTERVAL_ONE_DAY (default), _ONE_HOUR, _WEEK, _MONTH and the minute
                  and hour steps listed in the schema. The API names intervals differently
                  here than in get_candles; a CANDLE_INTERVAL_* name is translated.
        type_of_price: TYPE_OF_PRICE_CLOSE, TYPE_OF_PRICE_OPEN, TYPE_OF_PRICE_HIGH, TYPE_OF_PRICE_LOW, TYPE_OF_PRICE_AVG
        length: Indicator period in intervals (default: 14); MACD ignores it
        deviation: BB only — number of standard deviations between the middle and outer bands (default: 2)
        fast_length: MACD only — period of the fast EMA (default: 12)
        slow_length: MACD only — period of the slow EMA (default: 26)
        signal_smoothing: MACD only — period of the signal line (default: 9)
    """
    indicator_type = _enum(indicator_type, "INDICATOR_TYPE_")
    candle_name = _enum(interval, "CANDLE_INTERVAL_")
    interval = INDICATOR_INTERVALS.get(candle_name) or _enum(interval, "INDICATOR_INTERVAL_")
    type_of_price = _enum(type_of_price, "TYPE_OF_PRICE_")
    body: dict[str, Any] = {
        "instrumentUid": await _uid(instrument_id, figi_ok=False),
        "indicatorType": indicator_type,
        **_period(from_date, to_date, back=90),
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
async def list_shares(instrument_status: InstrumentStatus = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available shares (stocks).

    Warning: returns a large dataset. Use find_instrument for searching specific shares.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Shares", {
        "instrumentStatus": _enum(instrument_status, "INSTRUMENT_STATUS_"),
    })
    return _fmt(data)


@read_only_tool
async def list_bonds(instrument_status: InstrumentStatus = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available bonds.

    Warning: returns a large dataset. Use find_instrument for searching specific bonds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Bonds", {
        "instrumentStatus": _enum(instrument_status, "INSTRUMENT_STATUS_"),
    })
    return _fmt(data)


@read_only_tool
async def list_etfs(instrument_status: InstrumentStatus = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available ETFs and funds.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Etfs", {
        "instrumentStatus": _enum(instrument_status, "INSTRUMENT_STATUS_"),
    })
    return _fmt(data)


@read_only_tool
async def list_currencies(instrument_status: InstrumentStatus = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available currency instruments.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Currencies", {
        "instrumentStatus": _enum(instrument_status, "INSTRUMENT_STATUS_"),
    })
    return _fmt(data)


@read_only_tool
async def list_futures(instrument_status: InstrumentStatus = "INSTRUMENT_STATUS_BASE") -> str:
    """Get list of all available futures contracts.

    Args:
        instrument_status: INSTRUMENT_STATUS_BASE (tradeable) or INSTRUMENT_STATUS_ALL
    """
    data = await _call("InstrumentsService", "Futures", {
        "instrumentStatus": _enum(instrument_status, "INSTRUMENT_STATUS_"),
    })
    return _fmt(data)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
