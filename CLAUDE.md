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
grep -c '^@read_only_tool' src/tbank_invest_mcp/server.py   # how many tools there are

export TBANK_INVEST_TOKEN=...     # https://www.tbank.ru/invest/settings/api/
t-bank-invest-mcp-read-only       # run over stdio (same as python -m tbank_invest_mcp)
mcp dev src/tbank_invest_mcp/server.py   # run under the MCP Inspector
```

The server reads the token from the environment only; it does not load `.env` (`.env.example` just documents the variable). No linter or formatter is configured. CI (`.github/workflows/tests.yml`) runs `pytest --tb=short -q -x` on Python 3.11–3.13 for pushes and PRs to `main`, plus once against the oldest `mcp` version the package claims to support.

## Architecture

Everything is in `src/tbank_invest_mcp/server.py`, top to bottom: constants → `mcp = FastMCP(...)` → the `read_only_tool` decorator → enum types for the schema → private helpers → instrument-identifier resolution → tools grouped under `# ── Section ──` banners (Account & User, Portfolio & Positions, Operations, Instruments, Market Data, Orders, Instrument Lists) → `main()`.

**Request path.** Every tool is an `async def` decorated with `@read_only_tool` that builds a JSON body and awaits `_call(service, method, body)`, which POSTs to `{BASE_URL}/tinkoff.public.invest.api.contract.v1.{Service}/{Method}` (`BASE_URL = https://invest-public-api.tbank.ru/rest`) through one shared `httpx.AsyncClient` and returns the parsed JSON. Services in use: `UsersService`, `OperationsService`, `InstrumentsService`, `MarketDataService`, `OrdersService`.

**Helpers**

| Helper | Purpose |
|---|---|
| `_get_token()` / `_headers()` | Bearer auth from `TBANK_INVEST_TOKEN`, stripped of surrounding whitespace; raises `ValueError` if unset or malformed, without echoing the value |
| `_ssl_context()` / `_get_client()` | pinned-CA TLS context; lazily created module-level client (`TIMEOUT_SECONDS`) |
| `read_only_tool(fn)` | the only way a tool is registered: `readOnlyHint`, dedented docstring as description, text-only output |
| `_call(service, method, body)` | the only place that does HTTP; returns `.json()`, or re-raises the httpx error with a text written for the model: `_api_error(...)` for an HTTP status, `_transport_error(...)` for a timeout or network failure |
| `_api_error(service, method, resp)` | the error line the model reads: HTTP status, method, the API's `message` and error code |
| `_transport_error(service, method, exc, token)` | the same for failures with no HTTP status; httpx timeouts have an empty message, and the token is masked in whatever the error quotes |
| `_ts(dt)` / `_parse_date(s, default, end_of_day=False)` | UTC datetime ↔ RFC 3339; accepts `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`, with or without `Z`; `end_of_day=True` turns a bare date into 23:59:59 of that day |
| `_period(from_date, to_date, back=, ahead=)` | a request's `{"from", "to"}`: the dates given, or by default `back` days ago to `ahead` days from now, `to` through the end of its day |
| `_enum(value, prefix, allowed=())` | full enum name from a value given with or without its prefix, in any case; with `allowed`, rejects an unknown value |
| `_choices(*values)` | type for a string parameter whose JSON schema lists its values (`CandleInterval`, `InstrumentIdType`, …); the server validates nothing against the list, a client may |
| `_plain(data)` | the response with every `{units, nano}` made a number and currencies folded into one `currency` field per object |
| `_trimmed(data, *list_keys, drop=())` | `_plain` plus zero, false and empty fields removed from the items of the named lists |
| `_fmt(data, *list_keys, drop=())` | what a tool returns: `_trimmed(...)` as compact JSON — with no list keys that is just `_plain(data)` |
| `_number(q)` / `_number_at(obj, key)` / `_to_quotation(value)` | `{units, nano}` → int or float (`None` for a missing one), and a number → `{units, nano}` for a request body |
| `_find_exact(identifier, kind, any_listing)` / `_uid(identifier, kind, figi_ok=, any_listing=)` | the instrument a ticker, FIGI, ISIN or `TICKER_CLASSCODE` names (hits cached in `_resolved`, misses for `MISS_TTL_SECONDS` in `_missed`; `ValueError` if several match), and what to send the API for it — its UID, a FIGI as is where the method takes one, or the identifier unchanged if nothing matches |
| `_csv(values)` / `_each(identifiers, resolve)` / `_uids(csv)` | split a comma-separated parameter; resolve a list: each distinct identifier once, `LOOKUP_BATCH` at a time |
| `_asset_uid_for(identifier)` / `_instrument_ref(id, id_type, class_code, kind)` | the same for asset-UID methods (instrument → asset cached in `_asset_uids`), and for the `*By` methods' `{idType, id, classCode}` |
| `_asset_uid(instrument_uid)` | instrument UID → asset UID via `GetInstrumentBy`; `""` on 404; either answer cached in `_asset_uids` |
| `_consensus_forecast(asset_uid, ...)` | pages through `GetConsensusForecasts` to find one asset's item |
| `_pick_instrument(instruments, query, class_code)` | chooses one `FindInstrument` hit for `get_stock_snapshot`, whose query may be a name |

**TLS.** T-API is served under Russian Ministry of Digital Development (НУЦ Минцифры) certificates, absent from every default trust store. `certs/russian_trusted_root_ca.pem` is pinned for this client only — never install it system-wide, since that CA could then impersonate any host. `_ssl_context()` checks the file's SHA-256 against `CA_SHA256` and refuses to run if it differs; `TBANK_CA_BUNDLE` overrides the bundle if the CA rotates.

## Tool conventions

- **The docstring is the tool's public contract.** FastMCP sends it, with the `Args:` section, to the MCP client as the tool description, and the model on the other side decides how to call the tool from that text alone. Keep parameters, defaults and the return shape described there in step with the code.
- **Every tool is registered with `@read_only_tool`, never with `mcp.tool()` directly.** It marks the tool `readOnlyHint` for the client — which is what lets a client skip confirmation prompts — and turns off FastMCP's structured output: tools return a JSON string, and FastMCP would otherwise send that string a second time wrapped in `structuredContent`. `tests/test_server.py` fails if a tool bypasses it.
- **Most tools are thin**: build the body, `_call`, `return _fmt(data)` — the API response with its camelCase keys, but never raw: `_fmt` runs everything through `_plain`, so amounts are numbers everywhere. Tools returning long lists of wide objects also trim them, `_fmt(data, "positions", drop=(...))` (`get_portfolio`, `get_positions`, both operations tools, `get_bond_events`), `get_candles` returns rows, and `find_instrument` returns a short list of slim records. Composite tools shape their own output (`get_stock_snapshot`, `get_consensus_forecasts`) and use snake_case keys for what they add.
- **A response has to fit in a model's context.** Claude Code refuses a tool result above roughly 25,000 tokens — in practice somewhere between 46k and 53k characters of JSON — and with real data that was every `get_portfolio` call. Before adding a tool or a field, look at the size of a real response, not a mocked one. Measured on a real account: a 106-position portfolio is 34k characters, a page of 50 operations 25k (which is why 50 is the default page), a hundred operations 47k. Fields that only repeat another field or the request are dropped where the lists are long (`positionUid` next to `instrumentUid`, `operationType` next to `type`, the per-item `cursor`).
- **An instrument parameter takes a ticker, FIGI, ISIN or UID.** Pass it through `_uid` (or `_uids`, `_asset_uid_for`, `_instrument_ref`) before it goes into a request body, with the tool's instrument kind when it has one (`"bond"`, `"share"`). An unknown identifier is passed to the API unchanged (a plain name — non-ASCII or with a space — is an error instead); different papers under one ticker are an error naming the candidates; several listings of one paper resolve to the one with candle history. Two flags decide what a tool needs: `figi_ok=False` for the methods that take a UID only (`GetTechAnalysis`, `GetForecastBy`, `GetAssetReports`, anything keyed by asset) — elsewhere a FIGI goes through without a lookup, which keeps a portfolio-sized `get_last_prices` at one request; and `any_listing=True` where the answer does not depend on the board (dividends, coupons, bond events, fundamentals, forecasts), so that listings of one paper which candle history cannot tell apart are not an ambiguity there. Prices, candles and order books do depend on the board and keep the error.
- **Parameters are flat strings, ints and bools.** Lists arrive as comma-separated strings and are split and stripped in the tool (`assets`, `instrument_ids`, `operation_types`). Optional parameters default to `""` and are left out of the body when empty.
- **Dates** come in as strings through `_period` (or `_parse_date` where the API picks the default), each tool supplying its own default window, documented in its docstring. They are UTC. Every `to_date` is parsed with `end_of_day=True`, so a range given in whole days includes its last day and `from_date == to_date` means that one day, not an empty range.
- **Enums** go to the API as full prefixed strings (`CANDLE_INTERVAL_DAY`, `INSTRUMENT_ID_TYPE_UID`, `INDICATOR_TYPE_RSI`) and most tools expect the caller to pass them that way. The filters that take short names go through `_enum`, which accepts the value with or without its prefix: `state` (`EXECUTED` → `OPERATION_STATE_EXECUTED`), `operation_types` (`BUY` → `OPERATION_TYPE_BUY`) and the bond event `type` (`CPN` → `EVENT_TYPE_CPN`). The other enum parameters (`interval`, `indicator_type`, `id_type`, `instrument_status`, …) are typed with a `_choices(...)` alias, so the schema lists their values, and that list is the documented spelling — a client may enforce it, so do not tell callers that other spellings work. They go through `_enum` as well, which makes the server itself lenient about a missing prefix or the case. `get_tech_analysis` translates `CANDLE_INTERVAL_*` names into the API's `INDICATOR_INTERVAL_*`. Where the enum is small, pass `allowed` so that an unknown value is an error here — the API would silently ignore it and return unfiltered data. `get_portfolio` sends currency as an integer (RUB 0, USD 1, EUR 2) and rejects anything else for the same reason.
- **Out-of-range numbers are clamped**, not rejected (`limit` 1–1000, order book `depth` 1–50).
- **Errors.** HTTP failures propagate from `_call` as `httpx.HTTPStatusError`, and bad arguments raise `ValueError`; FastMCP reports either to the client as a tool error, and the exception's text is all the model gets to correct itself with. So `_call` puts the API's own explanation there (`T-Bank API returned HTTP 404 for InstrumentsService/GetInstrumentBy: Instrument not found (error code 50002)`), and words timeouts and network failures itself; write `ValueError` messages to the same standard. An error text must never contain the token — it goes into the model's context and the conversation log. "Looked and found nothing" is a normal result instead: the composite tools return `{"error": "..."}`.
- **Nothing may write to stdout.** The server speaks MCP over stdio, so a stray `print` corrupts the protocol stream.

## T-Bank API facts worth knowing

- The REST gateway mirrors the gRPC contracts: field names are the proto names in lowerCamelCase, enums are strings, 64-bit integers (`units`) arrive as strings. The proto files are the reference for request and response shapes — `src/docs/contracts/*.proto` in `RussianInvestments/investAPI` on GitHub.
- `MoneyValue` / `Quotation`: `value = int(units) + nano / 1_000_000_000`; for negative values both parts are negative.
- Instrument identifiers: FIGI, ticker (needs `class_code`, e.g. `TQBR`), or UID. Most market-data methods take `instrumentId` (FIGI or UID); `GetTechAnalysis` takes `instrumentUid` (UID only).
- **Instrument UID ≠ asset UID.** One asset (a company's share) has many instruments (listings). `FindInstrument` and the `*By` lookups return the instrument UID; `GetAssetFundamentals` and consensus forecasts are keyed by asset UID (`assetUid` in the `GetInstrumentBy` response). A consensus forecast item's own `uid` is the forecast record's id, not an instrument.
- `FindInstrument` returns every listing of a paper — delisted and non-tradable class codes included — and not in relevance order: the first hit for `SBER` is not SBER on TQBR. It filters server-side by `instrumentKind` and `apiTradeAvailableFlag: true` (187 hits for `SBER` become 16, and 2 among shares) and finds an instrument by exact ticker, FIGI, ISIN or UID.
- Market-data methods accept `TICKER_CLASSCODE` (`SBER_TQBR`) as `instrumentId`, but not an ISIN. `GetLastPrices` answers an identifier it does not know with an empty price, not an error.
- One ticker can be several things. `T` is two different papers (T-Technologies on TQBR, AT&T on SPBXM): different ISINs, both tradable, a real ambiguity. `TMOS` is one fund with four listings of one ISIN, none of them tradable through the API; only the listing the paper really trades on has `first1dayCandleDate` set, the others are negotiated-deal and technical boards.
- A candle carries `volumeBuy` and `volumeSell` next to `volume`; `get_candles` keeps them as columns.
- `GetConsensusForecasts` has no per-instrument filter, only paging over the whole list (on the order of a hundred items). A non-positive paging `limit` is answered with pages of 100.
- **An enum filter value the API does not know is silently ignored**, not rejected: `GetBondEvents` with `type: "COUPON"` returns every event, exactly as with no filter. The real names are `EVENT_TYPE_CPN`, `_CALL`, `_MTY`, `_CONV`.
- `GetBondEvents` without `from`/`to` covers only a few years around today; a bond's maturity shows up only with an explicit range.
- A range's `to` may lie in the future. A daily candle is stamped 00:00 UTC of its day, and today's has `isComplete: false` while the session is open — its `close` is the current price.
- Errors come as `{"code", "message", "description"}`, where `description` is T-Bank's numeric error code (listed in `src/docs/errors.md` of the same repository). An unknown id gives HTTP 404 with `{"code": 5, "message": "Instrument not found", "description": "50002"}`.
- `GetTechAnalysis` has its own interval enum (`INDICATOR_INTERVAL_ONE_DAY`, …) and rejects the `CANDLE_INTERVAL_*` names of `GetCandles`. It also rejects `INDICATOR_TYPE_BB` without `deviation` and `INDICATOR_TYPE_MACD` without `smoothing`. MACD gives the same result with or without `length`; SMA is rejected without it.

## Tests

- `tests/test_tools.py` — every tool. `_call` is replaced with an `AsyncMock` (`patch.object(srv, "_call", mock)`), then the test asserts on `mock.call_args[0]` → `(service, method, body)` and on the returned JSON. Tools that make several calls use a router mock keyed by method name (`route`, `make_paged_call_mock`, `make_snapshot_call_mock`). A non-UID identifier makes a tool call `FindInstrument` first, so assert on the request with `call_body(mock, "Method")` rather than on the last call when that matters; an autouse fixture clears the `_resolved` cache between tests.
- `tests/test_call.py` — `_call` itself against a mocked `AsyncClient`: URL, headers, body, error propagation and the error text, for HTTP statuses (those tests use real `httpx.Response` objects) and for timeouts and network failures. It resets `server._client` around each test because the client is module-level.
- `tests/test_ssl.py` — the pinned CA, the fingerprint guard, the `TBANK_CA_BUNDLE` override.
- `tests/test_helpers.py` — `_get_token`, `_headers`, `_ts`, `_parse_date`, `_enum`, `_fmt`, `_to_quotation`, `_plain`, `_trimmed`.
- `tests/test_server.py` — what an MCP client receives, through `mcp.list_tools()` and `mcp.call_tool()`: every tool registered and marked read-only, descriptions, the reported server version, the shape of a result and of an error.

`asyncio_mode = "auto"`, so async tests need no marker. `tests/conftest.py` sets a fake token for every test.

**Mocks only prove the code matches what the mock assumes.** When a change depends on how the API really behaves — which identifier a field holds, what a search returns, the shape of a response — also run it once against the live API with a real token; read-only market-data calls are enough, and the token must never be printed or committed. In mocks, give distinct things distinct values (an instrument UID and its asset UID must not be the same string), or the test cannot tell them apart either.

## Adding or changing a tool

1. Put it under the matching section banner, as `@read_only_tool` + `async def`, with a docstring that has an `Args:` section.
2. Check the method's request and response fields in the proto contract rather than guessing names.
3. Add a test class to `tests/test_tools.py` covering the request body, defaults and any shaping of the result.
4. Update the tool table in `README.md` (Russian), and the helper table here if a helper was added.
5. Don't rename or remove a tool or a parameter. A model reads the tool list afresh every session and adapts, but people don't: client permission lists (`mcp__t-bank-invest__get_portfolio`), skills and prompts name tools and parameters literally. Extend instead — a new optional parameter, or a new tool next to the old one. An output's shape is cheaper to change (only scripts that parse it notice) and may change until 1.0.0; after that, keep existing fields and only add.

## Releasing

Users install from PyPI with `uvx t-bank-invest-mcp-read-only` (see `README.md`; some still run `main` straight from git), so the wheel must be self-contained: anything the server reads at runtime, like the pinned CA, has to live inside `src/tbank_invest_mcp/`. The console script name, the package name and the `tbank_invest_mcp.server:main` entry point are part of the install contract — existing client configs point at them.

To release: set `version` in `pyproject.toml` to the release number, commit, push `main`, then tag that commit `vX.Y.Z` and push the tag. `.github/workflows/release.yml` refuses a tag that is not on `main` or that differs from the version, builds sdist and wheel, runs the test suite against the installed wheel, publishes to PyPI through Trusted Publishing (the `pypi` environment; no API token is stored) and creates a GitHub Release with generated notes — marked as a pre-release when the version is a dev, alpha, beta or rc one. A final version is also published to the MCP Registry as `io.github.Sicness/t-bank-invest-mcp-read-only`: the workflow writes the version into `server.json` and logs in through GitHub OIDC. The registry accepts it only because the README, which is the package description on PyPI, carries the `mcp-name:` comment at the top — keep it, and keep it equal to `name` in `server.json`.

Semantic versioning applies to the tool contract: minor for new tools and parameters, patch for fixes. A major bump would mean a renamed or removed tool or parameter, or — from 1.0.0 on — a removed or redefined output field, and that is not planned. Breaking output changes should get a paragraph of their own in the release notes, since the generated ones list only commit titles.

## Dependencies

Runtime: `mcp[cli]>=1.14.0,<2`, `httpx>=0.27.0`, `certifi`. The floor is real: on older releases FastMCP cannot register tools from a module that uses `from __future__ import annotations`, so the server fails on import; CI runs the suite against exactly that version. The `<2` cap is deliberate: mcp 2.x removed `mcp.server.fastmcp` (`FastMCP` became `MCPServer`) and there is no lockfile, so without the cap a fresh install fails on import. Moving to the v2 API is a separate change. Test extra: `pytest>=8.0`, `pytest-asyncio>=0.23`. Build backend: `hatchling`. Python ≥ 3.11.

## Related project: `invest`

This repository holds only the server. The main consumer is the separate `invest` project (a sibling checkout, `../invest`), which launches this server from this repo's `.venv`; because the install is editable, a change here reaches it on the next server restart. Its helper scripts (`scripts/money_value.py`, `scripts/portfolio_parser.py`) and the usage references for this server (`.claude/skills/t-bank-invest-mcp/references/MCP_TOOLS.md`, `DATA_FORMATS.md`, `PATTERNS.md`) live there, not here. When a tool's contract changes, `MCP_TOOLS.md` in `invest` needs the same update.
