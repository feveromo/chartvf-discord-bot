"""Crypto charts: OKX perpetuals for intraday, Binance spot history otherwise.

Each falls back to the other, so a coin listed on either one charts.
"""

import asyncio
import datetime as dt
import logging
import time
from typing import Any

import aiohttp

from charting import (
    DATE_RANGE_DAYS,
    MAIN_COINS,
    SMA_PERIODS,
    TIMEFRAMES,
    ChartData,
    ChartRequest,
    ChartRow,
    NoChartData,
    aggregate_chart_data,
    is_intraday,
    native_timeframe,
    safe_float,
)
from market_http import (
    PROVIDER_ERRORS,
    MarketDataHTTPError,
    MarketDataProviderError,
    background,
    request_json,
)
from yahoo import YAHOO_SYMBOL_ALIASES

LOGGER = logging.getLogger("chartvf.crypto")

BINANCE_SPOT_BASE_URL = "https://data-api.binance.vision"
BINANCE_KLINE_LIMIT = 1000
OKX_BASE_URL = "https://www.okx.com"
OKX_PAGE_SIZE = 300
OKX_UNKNOWN_INSTRUMENT = "51001"
OKX_CRYPTO_CATEGORY = "1"  # OKX also lists stock and commodity perps.
COINBASE_CURRENCIES_URL = "https://api.exchange.coinbase.com/currencies"
# Every US-listed stock and ETF symbol, Nasdaq and NYSE alike.
US_STOCK_SYMBOLS_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
# A short file is a bad download. Trusting it would let coins shadow stocks.
MIN_US_STOCK_SYMBOLS = 5000
LISTING_REFRESH_SECONDS = 6 * 3600
LISTING_RETRY_SECONDS = 300
# Native exchange intervals; 2m and 10m are aggregated from 1m and 5m.
BINANCE_INTERVALS = {
    "d": "1d",
    "w": "1w",
    "m": "1M",
    "i1": "1m",
    "i3": "3m",
    "i5": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "1h",
    "h2": "2h",
    "h4": "4h",
}
OKX_INTERVALS = {
    "d": "1Dutc",
    "w": "1Wutc",
    "m": "1Mutc",
    "i1": "1m",
    "i3": "3m",
    "i5": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "1H",
    "h2": "2H",
    "h4": "4H",
}

Ticker24h = tuple[float, float, int]  # last price, price 24h ago, epoch seconds

# Tickers that chart as crypto without `;crypto`, and coin names for embeds.
# refresh_crypto_listing() replaces both; MAIN_COINS covers startup.
crypto_tickers: frozenset[str] = MAIN_COINS
coin_names: dict[str, str] = {}


def _binance_symbol(ticker: str) -> str:
    return f"{ticker}USDT"


def _okx_inst_id(ticker: str) -> str:
    return f"{ticker}-USDT-SWAP"


def _pair_name(ticker: str) -> str:
    return f"{coin_names.get(ticker, ticker)} / TetherUS"


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers={"Accept": "text/plain"}) as response:
        if response.status != 200:
            raise MarketDataHTTPError(response.status)
        return await response.text()


async def _fetch_coin_names(session: aiohttp.ClientSession) -> dict[str, str]:
    try:
        data = await request_json(session, COINBASE_CURRENCIES_URL)
    except PROVIDER_ERRORS:
        return {}
    if not isinstance(data, list):
        return {}
    return {
        str(row["id"]): str(row["name"])
        for row in data
        if isinstance(row, dict) and row.get("id") and row.get("name")
    }


async def _fetch_crypto_listing(
    session: aiohttp.ClientSession,
) -> tuple[frozenset[str], dict[str, str]]:
    """Coins on Binance spot or OKX perps, minus US stock and index tickers."""
    binance, okx, stock_file, names = await asyncio.gather(
        request_json(
            session,
            f"{BINANCE_SPOT_BASE_URL}/api/v3/exchangeInfo",
            params={"permissions": "SPOT"},
        ),
        request_json(
            session, f"{OKX_BASE_URL}/api/v5/public/instruments", params={"instType": "SWAP"}
        ),
        _fetch_text(session, US_STOCK_SYMBOLS_URL),
        _fetch_coin_names(session),
    )
    coins = {
        str(row.get("baseAsset"))
        for row in (binance.get("symbols") if isinstance(binance, dict) else None) or []
        if isinstance(row, dict)
        and row.get("quoteAsset") == "USDT"
        and row.get("status") == "TRADING"
    }
    coins |= {
        str(row.get("instId")).removesuffix("-USDT-SWAP")
        for row in (okx.get("data") if isinstance(okx, dict) else None) or []
        if isinstance(row, dict)
        and str(row.get("instId")).endswith("-USDT-SWAP")
        and row.get("instCategory") == OKX_CRYPTO_CATEGORY
        and row.get("state") == "live"
    }
    # Pipe-separated with a header line; the symbol is the second field.
    stocks = {
        line.split("|")[1] for line in stock_file.splitlines()[1:] if line.count("|") > 3
    }
    if len(stocks) < MIN_US_STOCK_SYMBOLS:
        raise MarketDataProviderError("US stock symbol list looks incomplete")
    return MAIN_COINS | (coins - stocks - YAHOO_SYMBOL_ALIASES.keys()), names


async def refresh_crypto_listing(session: aiohttp.ClientSession) -> None:
    """Keep `crypto_tickers` and `coin_names` current for the life of the bot."""
    global crypto_tickers, coin_names
    while True:
        try:
            tickers, names = await _fetch_crypto_listing(session)
        except PROVIDER_ERRORS as error:
            LOGGER.warning("crypto_listing outcome=error error_type=%s", type(error).__name__)
            delay = LISTING_RETRY_SECONDS
        else:
            crypto_tickers, coin_names = tickers, names or coin_names
            LOGGER.info("crypto_listing outcome=success coins=%d", len(tickers))
            delay = LISTING_REFRESH_SECONDS
        await asyncio.sleep(delay)


def _history_start_ms(request: ChartRequest, interval_seconds: int) -> int | None:
    """Oldest bar to fetch: the visible range plus enough bars to seed SMA200."""
    if request.date_range == "max":
        return 0
    now = int(time.time())
    if request.date_range == "ytd":
        current = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        cutoff = int(dt.datetime(current.year, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    else:
        days = DATE_RANGE_DAYS.get(request.date_range)
        if days is None:
            return None
        cutoff = now - days * 86400
    return max(0, (cutoff - (SMA_PERIODS[-1] - 1) * interval_seconds) * 1000)


def _dedupe_rows(rows: list[list[Any]]) -> list[list[Any]]:
    unique: dict[int, list[Any]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        timestamp = safe_float(row[0])
        if timestamp is not None:
            unique[int(timestamp)] = row
    return [unique[timestamp] for timestamp in sorted(unique)]


def _kline_chart_rows(rows: list[list[Any]], volume_index: int) -> tuple[ChartRow, ...]:
    chart_rows: list[ChartRow] = []
    for row in rows:
        open_time, open_, high, low, close = (safe_float(value) for value in row[:5])
        if open_time is None or open_ is None or high is None or low is None or close is None:
            continue
        volume = safe_float(row[volume_index]) if len(row) > volume_index else None
        chart_rows.append(
            ChartRow(int(open_time // 1000), open_, high, low, close, volume or 0.0)
        )
    return tuple(chart_rows)


async def _fetch_binance_klines(
    session: aiohttp.ClientSession, request: ChartRequest
) -> list[list[Any]]:
    native = native_timeframe(request.timeframe, BINANCE_INTERVALS)
    rows: list[list[Any]] = []
    start_time = _history_start_ms(request, TIMEFRAMES[native].seconds)

    while True:
        params: dict[str, Any] = {
            "symbol": _binance_symbol(request.ticker),
            "interval": BINANCE_INTERVALS[native],
            "limit": BINANCE_KLINE_LIMIT,
        }
        if start_time is not None:
            params["startTime"] = start_time
        try:
            data = await request_json(
                session, f"{BINANCE_SPOT_BASE_URL}/api/v3/klines", params=params
            )
        except MarketDataHTTPError as error:
            # Binance answers an unknown symbol with 400.
            if error.status in (400, 404):
                raise NoChartData(f"No chart data found for `{request.ticker}`.") from error
            raise
        if not isinstance(data, list) or not data:
            break
        page = [row for row in data if isinstance(row, list) and len(row) >= 6]
        rows.extend(page)
        if start_time is None or len(data) < BINANCE_KLINE_LIMIT or not page:
            break
        next_start_time = int(page[-1][0]) + 1
        if next_start_time <= start_time or next_start_time >= int(time.time() * 1000):
            break
        start_time = next_start_time

    rows = _dedupe_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


async def _fetch_okx_swap_klines(
    session: aiohttp.ClientSession, request: ChartRequest
) -> list[list[Any]]:
    native = native_timeframe(request.timeframe, OKX_INTERVALS)
    cutoff = _history_start_ms(request, TIMEFRAMES[native].seconds)
    rows: list[list[Any]] = []
    after: int | None = None
    while True:
        params: dict[str, Any] = {
            "instId": _okx_inst_id(request.ticker),
            "bar": OKX_INTERVALS[native],
            "limit": OKX_PAGE_SIZE,
        }
        if after is not None:
            params["after"] = after
        try:
            data = await request_json(
                session, f"{OKX_BASE_URL}/api/v5/market/history-candles", params=params
            )
        except MarketDataHTTPError as error:
            if error.status == 404:
                raise NoChartData(f"No chart data found for `{request.ticker}`.") from error
            raise
        if isinstance(data, dict) and data.get("code") == OKX_UNKNOWN_INSTRUMENT:
            raise NoChartData(f"No chart data found for `{request.ticker}`.")
        if not isinstance(data, dict) or data.get("code") != "0":
            raise MarketDataProviderError("Market data provider returned an error")
        page = data.get("data") or []
        if not isinstance(page, list) or not page:
            break
        valid_page = [
            row
            for row in page
            if isinstance(row, list) and len(row) >= 7 and safe_float(row[0]) is not None
        ]
        rows.extend(valid_page)
        if not valid_page or len(page) < OKX_PAGE_SIZE:
            break
        oldest = min(int(float(row[0])) for row in valid_page)
        if cutoff is None or oldest <= cutoff or oldest == after:
            break
        after = oldest

    rows = _dedupe_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


# The rolling 24h change is a nice-to-have: these return None rather than
# failing the chart.


async def _fetch_binance_24h_ticker(
    session: aiohttp.ClientSession, request: ChartRequest
) -> Ticker24h | None:
    try:
        data = await request_json(
            session,
            f"{BINANCE_SPOT_BASE_URL}/api/v3/ticker/24hr",
            params={"symbol": _binance_symbol(request.ticker)},
        )
    except PROVIDER_ERRORS:
        return None
    if not isinstance(data, dict):
        return None
    last = safe_float(data.get("lastPrice"))
    open_ = safe_float(data.get("openPrice"))
    close_time = safe_float(data.get("closeTime"))
    if last is None or open_ is None:
        return None
    return last, open_, int((close_time or time.time() * 1000) // 1000)


async def _fetch_okx_24h_ticker(
    session: aiohttp.ClientSession,
    request: ChartRequest,
) -> Ticker24h | None:
    try:
        data = await request_json(
            session,
            f"{OKX_BASE_URL}/api/v5/market/ticker",
            params={"instId": _okx_inst_id(request.ticker)},
        )
    except PROVIDER_ERRORS:
        return None
    if not isinstance(data, dict) or data.get("code") != "0":
        return None
    rows = data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    last = safe_float(rows[0].get("last"))
    open_ = safe_float(rows[0].get("open24h"))
    timestamp = safe_float(rows[0].get("ts"))
    if last is None or open_ is None:
        return None
    return last, open_, int((timestamp or time.time() * 1000) // 1000)


def _crypto_chart_data(
    request: ChartRequest,
    rows: tuple[ChartRow, ...],
    ticker_24h: Ticker24h | None,
    *,
    name: str,
    market_label: str,
    native: str,
) -> ChartData:
    if len(rows) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")
    seconds = TIMEFRAMES[native].seconds
    if ticker_24h is None:
        # Without the rolling 24h ticker, show no change rather than a fake one.
        last, previous = rows[-1].close, None
        last_time = min(rows[-1].epoch + seconds - 1, int(time.time()))
    else:
        last, previous, last_time = ticker_24h
    data = ChartData(
        ticker=request.ticker,
        name=name,
        rows=rows,
        last_close=last,
        last_time=last_time,
        previous_close=previous,
        market_label=market_label,
        source_interval_seconds=seconds,
    )
    return aggregate_chart_data(data, request)


async def _okx_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> ChartData:
    async with background(_fetch_okx_24h_ticker(session, request)) as ticker_task:
        rows = await _fetch_okx_swap_klines(session, request)
        ticker_24h = await ticker_task
    return _crypto_chart_data(
        request,
        _kline_chart_rows(rows, volume_index=6),  # base-currency volume
        ticker_24h,
        name=f"{_pair_name(request.ticker)} perpetual ({_okx_inst_id(request.ticker)}, OKX)",
        market_label="OKX perp",
        native=native_timeframe(request.timeframe, OKX_INTERVALS),
    )


async def _binance_chart_data(
    session: aiohttp.ClientSession, request: ChartRequest
) -> ChartData:
    async with background(_fetch_binance_24h_ticker(session, request)) as ticker_task:
        rows = await _fetch_binance_klines(session, request)
        ticker_24h = await ticker_task
    return _crypto_chart_data(
        request,
        _kline_chart_rows(rows, volume_index=5),
        ticker_24h,
        name=f"{_pair_name(request.ticker)} spot ({_binance_symbol(request.ticker)}, Binance)",
        market_label="Binance spot",
        native=native_timeframe(request.timeframe, BINANCE_INTERVALS),
    )


async def fetch_crypto_chart_data(
    session: aiohttp.ClientSession, request: ChartRequest
) -> ChartData:
    sources = [("okx", _okx_chart_data), ("binance", _binance_chart_data)]
    if not is_intraday(request.timeframe):
        sources.reverse()
    (source, fetch), (target, fallback) = sources
    try:
        return await fetch(session, request)
    except (*PROVIDER_ERRORS, NoChartData) as error:
        LOGGER.info(
            "provider_fallback source=%s target=%s ticker=%s error_type=%s",
            source,
            target,
            request.ticker,
            type(error).__name__,
        )
    return await fallback(session, request)
