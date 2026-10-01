# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP (Model Context Protocol) server that gives AI assistants **read-only** access to the T-Bank (Tinkoff) Invest API: accounts, portfolio, operations history, instrument search, market data, fundamentals and forecasts. Built on FastMCP; the user-facing tool list is in `README.md` (in Russian).

**Read-only is the product's promise, not a default.** The user's token may well have trading rights, so the guarantee lives in this code: it only calls `Get*` / `Find*` / listing methods. Never add a call that places, changes or cancels orders, moves money, or edits account state (favorites included) — not even behind a flag.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"          # editable install + pytest, pytest-asyncio

pytest                            # whole suite, no network
pytest tests/test_tools.py -k snapshot
grep -c '^@mcp.tool()' src/tbank_invest_mcp/server.py   # how many tools there are

export TBANK_INVEST_TOKEN=...     # https://www.tbank.ru/invest/settings/api/
t-bank-invest-mcp-read-only       # run over stdio (same as python -m tbank_invest_mcp)
mcp dev src/tbank_invest_mcp/server.py   # run under the MCP Inspector
```

The server reads the token from the environment only; it does not load `.env` (`.env.example` just documents the variable). No linter or formatter is configured. CI (`.github/workflows/tests.yml`) runs `pytest --tb=short -q -x` on Python 3.11–3.13 for pushes and PRs to `main`.

## Architecture

Everything is in `src/tbank_invest_mcp/server.py`, top to bottom: constants → `mcp = FastMCP(...)` → private helpers → tools grouped under `# ── Section ──` banners (Account & User, Portfolio & Positions, Operations, Instruments, Market Data, Orders, Instrument Lists) → `main()`.

**Request path.** Every tool is an `async def` decorated with `@mcp.tool()` that builds a JSON body and awaits `_call(service, method, body)`, which POSTs to `{BASE_URL}/tinkoff.public.invest.api.contract.v1.{Service}/{Method}` (`BASE_URL = https://invest-public-api.tbank.ru/rest`) through one shared `httpx.AsyncClient` and returns the parsed JSON. Services in use: `UsersService`, `OperationsService`, `InstrumentsService`, `MarketDataService`, `OrdersService`.

**Helpers**

| Helper | Purpose |
|---|---|
| `_get_token()` / `_headers()` | Bearer auth from `TBANK_INVEST_TOKEN`; raises `ValueError` if unset |
| `_ssl_context()` / `_get_client()` | pinned-CA TLS context; lazily created module-level client (30 s timeout) |
| `_call(service, method, body)` | the only place that does HTTP; `raise_for_status()` then `.json()` |
| `_ts(dt)` / `_parse_date(s, default)` | UTC datetime ↔ RFC 3339; accepts `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`, with or without `Z` |
| `_fmt(data)` | `json.dumps(..., ensure_ascii=False, indent=2)` — what every tool returns |
| `_quotation_to_float(q)` | `{units, nano}` → float, `None` for a missing value |
| `_asset_uid(instrument_uid)` | instrument UID → asset UID via `GetInstrumentBy`; `""` on 404 |
| `_consensus_forecast(asset_uids, ...)` | pages through `GetConsensusForecasts` to find one asset's item |
| `_pick_instrument(instruments, query, class_code)` | chooses one `FindInstrument` hit |

**TLS.** T-API is served under Russian Ministry of Digital Development (НУЦ Минцифры) certificates, absent from every default trust store. `certs/russian_trusted_root_ca.pem` is pinned for this client only — never install it system-wide, since that CA could then impersonate any host. `_ssl_context()` checks the file's SHA-256 against `CA_SHA256` and refuses to run if it differs; `TBANK_CA_BUNDLE` overrides the bundle if the CA rotates.

## Tool conventions

- **The docstring is the tool's public contract.** FastMCP sends it, with the `Args:` section, to the MCP client as the tool description, and the model on the other side decides how to call the tool from that text alone. Keep parameters, defaults and the return shape described there in step with the code.
- **Most tools are thin pass-throughs**: build the body, `_call`, `return _fmt(data)` — the raw API response with its camelCase keys. Only composite tools shape their own output (`get_stock_snapshot`, `get_consensus_forecasts`); those use snake_case keys for what they add.
- **Parameters are flat strings, ints and bools.** Lists arrive as comma-separated strings and are split and stripped in the tool (`assets`, `instrument_ids`, `operation_types`). Optional parameters default to `""` and are left out of the body when empty.
- **Dates** come in as strings through `_parse_date`, each tool supplying its own default window (documented in its docstring) relative to `datetime.now(timezone.utc)`.
- **Enums** go to the API as full prefixed strings (`CANDLE_INTERVAL_DAY`, `INSTRUMENT_ID_TYPE_UID`, `INDICATOR_TYPE_RSI`) and most tools expect the caller to pass them that way. The exceptions add the prefix themselves: `state` (`EXECUTED` → `OPERATION_STATE_EXECUTED`) and `operation_types` (`BUY` → `OPERATION_TYPE_BUY`). `get_portfolio` sends currency as an integer (RUB 0, USD 1, EUR 2).
- **Out-of-range numbers are clamped**, not rejected (`limit` 1–1000, order book `depth` 1–50).
- **Errors.** HTTP failures propagate from `_call` as `httpx.HTTPStatusError`, and bad arguments raise `ValueError`; FastMCP reports either to the client as a tool error. "Looked and found nothing" is a normal result instead: the composite tools return `{"error": "..."}`.
- **Nothing may write to stdout.** The server speaks MCP over stdio, so a stray `print` corrupts the protocol stream.

## T-Bank API facts worth knowing

- The REST gateway mirrors the gRPC contracts: field names are the proto names in lowerCamelCase, enums are strings, 64-bit integers (`units`) arrive as strings. The proto files are the reference for request and response shapes — `src/docs/contracts/*.proto` in `RussianInvestments/investAPI` on GitHub.
- `MoneyValue` / `Quotation`: `value = int(units) + nano / 1_000_000_000`; for negative values both parts are negative.
- Instrument identifiers: FIGI, ticker (needs `class_code`, e.g. `TQBR`), or UID. Most market-data methods take `instrumentId` (FIGI or UID); `GetTechAnalysis` takes `instrumentUid` (UID only).
- **Instrument UID ≠ asset UID.** One asset (a company's share) has many instruments (listings). `FindInstrument` and the `*By` lookups return the instrument UID; `GetAssetFundamentals` and consensus forecasts are keyed by asset UID (`assetUid` in the `GetInstrumentBy` response). A consensus forecast item's own `uid` is the forecast record's id, not an instrument.
- `FindInstrument` returns every listing of a paper — delisted and non-tradable class codes included — and not in relevance order: the first hit for `SBER` is not SBER on TQBR. Narrow with `instrumentKind`, an exact ticker match and `apiTradeAvailableFlag`.
- `GetConsensusForecasts` has no per-instrument filter, only paging over the whole list (on the order of a hundred items).
- An unknown id gives HTTP 404 with `{"code": 5, "message": "Instrument not found"}`.

## Tests

- `tests/test_tools.py` — every tool. `_call` is replaced with an `AsyncMock` (`patch.object(srv, "_call", mock)`), then the test asserts on `mock.call_args[0]` → `(service, method, body)` and on the returned JSON. Tools that make several calls use a router mock keyed by method name (`make_paged_call_mock`, `make_snapshot_call_mock`).
- `tests/test_call.py` — `_call` itself against a mocked `AsyncClient`: URL, headers, body, error propagation. It resets `server._client` around each test because the client is module-level.
- `tests/test_ssl.py` — the pinned CA, the fingerprint guard, the `TBANK_CA_BUNDLE` override.
- `tests/test_helpers.py` — `_get_token`, `_headers`, `_ts`, `_parse_date`, `_fmt`.

`asyncio_mode = "auto"`, so async tests need no marker.

**Mocks only prove the code matches what the mock assumes.** When a change depends on how the API really behaves — which identifier a field holds, what a search returns, the shape of a response — also run it once against the live API with a real token; read-only market-data calls are enough, and the token must never be printed or committed. In mocks, give distinct things distinct values (an instrument UID and its asset UID must not be the same string), or the test cannot tell them apart either.

## Adding or changing a tool

1. Put it under the matching section banner, as `@mcp.tool()` + `async def`, with a docstring that has an `Args:` section.
2. Check the method's request and response fields in the proto contract rather than guessing names.
3. Add a test class to `tests/test_tools.py` covering the request body, defaults and any shaping of the result.
4. Update the tool table in `README.md` (Russian), and the helper table here if a helper was added.
5. Renaming a tool, renaming or removing a parameter, or changing an output shape breaks existing clients — say so in the commit message.

## Releasing

Users install with `uvx` straight from this repository (see `README.md`), so the wheel must be self-contained: anything the server reads at runtime, like the pinned CA, has to live inside `src/tbank_invest_mcp/`. The console script name, the package name and the `tbank_invest_mcp.server:main` entry point are part of the install contract — existing client configs point at them.

To release: set `version` in `pyproject.toml` to the release number, commit, then tag that commit `vX.Y.Z` and push the tag. `.github/workflows/release.yml` refuses a tag that differs from the version, builds sdist and wheel, runs the test suite against the installed wheel, publishes to PyPI through Trusted Publishing (the `pypi` environment; no API token is stored) and creates a GitHub Release with generated notes.

The first published release will be 1.0.0; until then `version` stays `1.0.0.dev0` and tool contracts may still change. From 1.0.0 on, semantic versioning applies to the tool contract: major for a renamed or removed tool or parameter or a changed output shape, minor for new tools and parameters, patch for fixes.

## Dependencies

Runtime: `mcp[cli]>=1.0.0,<2`, `httpx>=0.27.0`, `certifi`. The `<2` cap is deliberate: mcp 2.x removed `mcp.server.fastmcp` (`FastMCP` became `MCPServer`) and there is no lockfile, so without the cap a fresh install fails on import. Moving to the v2 API is a separate change. Test extra: `pytest>=8.0`, `pytest-asyncio>=0.23`. Build backend: `hatchling`. Python ≥ 3.11.

## Related project: `invest`

This repository holds only the server. The main consumer is the separate `invest` project (a sibling checkout, `../invest`), which launches this server from this repo's `.venv`; because the install is editable, a change here reaches it on the next server restart. Its helper scripts (`scripts/money_value.py`, `scripts/portfolio_parser.py`) and the usage references for this server (`.claude/skills/t-bank-invest-mcp/references/MCP_TOOLS.md`, `DATA_FORMATS.md`, `PATTERNS.md`) live there, not here. When a tool's contract changes, `MCP_TOOLS.md` in `invest` needs the same update.
