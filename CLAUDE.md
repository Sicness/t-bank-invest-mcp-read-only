# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP (Model Context Protocol) server providing **read-only** access to the T-Bank (Tinkoff) Investment API. It exposes 38 tools for portfolio analytics, market data, instrument search, and operations history via the FastMCP framework.

## Setup & Development

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Set API token (required)
export TBANK_INVEST_TOKEN=your_token_here
# Get token at: https://www.tbank.ru/invest/settings/api/

# Run the server
t-bank-invest-mcp-read-only
# or
python -m tbank_invest_mcp.server
```

No test suite, linter, or formatter is currently configured.

## Architecture

Single-file implementation in `src/tbank_invest_mcp/server.py` (~800 lines).

**Core pattern**: Each tool is an async function decorated with `@mcp.tool()` that calls `_call(service, method, body)` → HTTP POST to `https://invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.{Service}/{Method}`.

**Internal helpers**:
- `_get_token()` / `_headers()` — auth via `TBANK_INVEST_TOKEN` env var (Bearer token)
- `_call(service, method, body)` — async POST with httpx, 30s timeout
- `_ts(dt)` / `_parse_date(s)` — datetime ↔ RFC 3339 conversion
- `_fmt(data)` — JSON serialization with `ensure_ascii=False`

**Tool categories** (mapped to T-Bank API services):
- **UsersService** — accounts, user info, margin attributes
- **OperationsService** — portfolio, positions, withdrawal limits, operations history
- **InstrumentsService** — search, instrument details by type (bond/share/ETF/currency/future), dividends, coupons, fundamentals, forecasts, favorites, trading schedules
- **MarketDataService** — candles (OHLCV), prices, order book, trading status, technical indicators
- **OrdersService** — active orders, order state

**Key API conventions**:
- Monetary values use `MoneyValue` format: `value = units + nano / 1_000_000_000`
- Instrument identifiers: FIGI, ticker (requires `class_code`), or UID
- Dates accepted as `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`; tools provide sensible defaults when omitted
- Enum values are passed as strings with full prefixes (e.g., `OPERATION_STATE_EXECUTED`, `CANDLE_INTERVAL_DAY`)

## Dependencies

Only two runtime dependencies: `mcp[cli]>=1.0.0` and `httpx>=0.27.0`. Build system: `hatchling`. Requires Python ≥ 3.11.
