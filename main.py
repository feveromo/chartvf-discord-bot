import asyncio
import datetime as dt
import io
from json import JSONDecodeError
import logging
import os
import sys
import time
from typing import Any

from charting import (
    BINANCE_CRYPTO_SYMBOLS,
    PREFIX,
    ChartData,
    ChartRequest,
    NoChartData,
    aggregate_chart_data,
    chart_title,
    has_close_only_latest_ohlc,
    latest_quote_price_time,
    normalize_chart_rows,
    parse_chart_command,
    patch_close_only_latest_ohlc,
    quote_description,
    render_price_chart_png,
    safe_float,
    stock_previous_close,
    yahoo_chart_url,
)

import aiohttp
import discord
from dotenv import load_dotenv


class MarketDataProviderError(RuntimeError):
    pass


class MarketDataHTTPError(MarketDataProviderError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Market data provider returned HTTP {status}")

HELP_TEXT = """**ChartVF**

**Syntax**
`;TICKER [timeframe] [type] [range] [theme] [scale]` — stocks
`;fut ROOT [timeframe] [type] [range] [theme] [scale]` — futures

**Examples**
`;AAPL` → latest 5-minute candle chart
`;AAPL d` → daily candle chart
`;AMD 3` → AMD 3-minute intraday chart
`;QQQ w line` → weekly line chart
`;LULU 1y` → 1-year chart
`;AAPL dark log` → dark theme, log scale
`;fut ES` → E-mini S&P latest 5-minute chart
`;fut ES 15` → E-mini S&P 15-minute chart
`;fut CL w line` → crude oil weekly line
`;futures GC 1y` → gold 1-year chart
Crypto: `;BTC`, `;BTC d`, `;ETH`, `;ETH 1y percent`, `;DOGE`, `;DOGE d`
Crypto history: `;BTC max`, `;ETH max`, `;DOGE max`
Indexes: `;SPX`, `;NDX`, `;DJX`/`;DJI`/`;DJIA`, `;RUT`, `;RUI`, `;VIX`, `;IXIC`, `;OEX`

**Options** (same for stocks and futures)
Timeframes: stocks support `d`, `w`, `m`, plus intraday `1`, `2`, `3`, `5`, `15`, `30`, `60`, `4h`; crypto and futures also support `10`, `2h`
Types: `candle`, `line`
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`
Themes: `dark`, `light`
Scales: `linear`, `log`, `percent`

Options can be in any order after the ticker.

**Futures** (`;fut`/`;future`/`;futures`): `;f` is still Ford (`F`).

**Freshness**: bare stock, futures, and crypto commands default to the latest 5-minute chart.
Crypto intraday charts use perp data; crypto daily/weekly/monthly and range charts use Binance spot
OHLCV history. Crypto change figures are rolling 24-hour values. `;BTC max` fetches all available
Binance spot chart history. Every chart image is
rendered locally from market chart data.
"""

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=4, sock_read=8)
MARKET_DATA_BUDGET_SECONDS = 15
MAX_CONCURRENT_FETCHES = 4
MAX_RETRY_AFTER_SECONDS = 1.5
BINANCE_SPOT_BASE_URL = "https://data-api.binance.vision"
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
BINANCE_KLINE_LIMITS = {"spot": 1000, "perp": 1500}
OKX_BASE_URL = "https://www.okx.com"
BINANCE_INTERVALS = {
    "d": "1d",
    "w": "1w",
    "m": "1M",
    "i1": "1m",
    "i2": "1m",
    "i3": "3m",
    "i5": "5m",
    "i10": "5m",
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
    "i2": "1m",
    "i3": "3m",
    "i5": "5m",
    "i10": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "1H",
    "h2": "2H",
    "h4": "4H",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

LOGGER = logging.getLogger("chartvf")
FETCH_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
RENDER_SEMAPHORE = asyncio.Semaphore(1)


class ChartBot(discord.Client):
    session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        connector = aiohttp.TCPConnector(
            limit=8,
            limit_per_host=4,
            ttl_dns_cache=300,
        )
        self.session = aiohttp.ClientSession(
            timeout=HTTP_TIMEOUT,
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={
                "User-Agent": USER_AGENT,
                "Cache-Control": "no-cache",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None
        await super().close()


intents = discord.Intents.none()
intents.guilds = True
intents.messages = True
intents.message_content = True
client = ChartBot(intents=intents, max_messages=0)
NO_MENTIONS = discord.AllowedMentions.none()


@client.event
async def on_ready() -> None:
    LOGGER.info("gateway_ready")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.content.startswith(PREFIX):
        return

    command_text = message.content[len(PREFIX):].strip()
    if not command_text:
        await message.channel.send(HELP_TEXT, allowed_mentions=NO_MENTIONS)
        return
    if command_text.split(maxsplit=1)[0].lower() in {"help", "h"}:
        await message.channel.send(HELP_TEXT, allowed_mentions=NO_MENTIONS)
        return

    try:
        request = parse_chart_command(message.content)
    except ValueError as error:
        await message.channel.send(str(error), allowed_mentions=NO_MENTIONS)
        return

    if request:
        await send_chart(message.channel, request)


async def _request_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    for attempt in range(2):
        try:
            async with session.get(url, params=params) as response:
                if response.status in {429, 500, 502, 503, 504} and attempt == 0:
                    retry_after = safe_float(response.headers.get("Retry-After")) or 0.25
                    await asyncio.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
                    continue
                if response.status != 200:
                    raise MarketDataHTTPError(response.status)
                try:
                    return await response.json(content_type=None)
                except (JSONDecodeError, aiohttp.ContentTypeError) as error:
                    raise MarketDataProviderError("Market data provider returned malformed JSON") from error
        except (aiohttp.ClientError, TimeoutError):
            if attempt == 0:
                continue
            raise
    raise MarketDataProviderError("Market data provider returned an error")


def _chart_result(data: Any, ticker: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MarketDataProviderError("Market data provider returned malformed data")
    chart = data.get("chart") or {}
    error = chart.get("error")
    if error:
        code = str(error.get("code") if isinstance(error, dict) else error).lower()
        description = str(error.get("description") if isinstance(error, dict) else "").lower()
        if "not found" in code or "not found" in description or "no data" in description:
            raise NoChartData(f"No chart data found for `{ticker}`.")
        raise MarketDataProviderError("Market data provider returned an error")
    results = chart.get("result") or []
    if not results or not isinstance(results[0], dict):
        raise NoChartData(f"No chart data found for `{ticker}`.")
    return results[0]


async def fetch_daily_previous_close(session: aiohttp.ClientSession, request: ChartRequest) -> float | None:
    daily_request = ChartRequest(
        ticker=request.ticker,
        timeframe="d",
        timeframe_label="daily",
        date_range="m1",
        date_range_label="1 month",
        futures=request.futures,
    )
    try:
        data = await _request_json(session, yahoo_chart_url(daily_request))
        result = _chart_result(data, request.ticker)
    except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError, NoChartData):
        return None
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = raw_quote.get("close") or []
    valid_closes = [close for close in (safe_float(value) for value in closes) if close is not None]
    return valid_closes[-2] if len(valid_closes) > 1 else None


async def fetch_current_day_intraday_quote(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any] | None:
    intraday_request = ChartRequest(
        ticker=request.ticker,
        timeframe="i1",
        timeframe_label="1 min",
        futures=request.futures,
    )
    intraday_url = yahoo_chart_url(intraday_request).replace("range=5d", "range=1d").replace(
        "includePrePost=true",
        "includePrePost=false",
    )
    try:
        result = _chart_result(await _request_json(session, intraday_url), request.ticker)
    except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError, NoChartData):
        return None
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    return {
        "date": result.get("timestamp") or [],
        "open": raw_quote.get("open") or [],
        "high": raw_quote.get("high") or [],
        "low": raw_quote.get("low") or [],
        "close": raw_quote.get("close") or [],
        "volume": raw_quote.get("volume") or [],
    }


def _binance_interval(request: ChartRequest) -> str:
    interval = BINANCE_INTERVALS.get(request.timeframe)
    if interval is None:
        raise ValueError(f"Binance chart data does not support `{request.timeframe_label}` charts.")
    return interval


def _okx_interval(request: ChartRequest) -> str:
    interval = OKX_INTERVALS.get(request.timeframe)
    if interval is None:
        raise ValueError(f"OKX chart data does not support `{request.timeframe_label}` charts.")
    return interval


def _crypto_auto_market(request: ChartRequest) -> str:
    if request.crypto_market != "auto":
        return request.crypto_market or "spot"
    return "perp" if request.timeframe.startswith(("i", "h")) else "spot"


PROVIDER_INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "1H": 60 * 60,
    "2h": 2 * 60 * 60,
    "2H": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "4H": 4 * 60 * 60,
    "1d": 86400,
    "1Dutc": 86400,
    "1w": 7 * 86400,
    "1Wutc": 7 * 86400,
    "1M": 30 * 86400,
    "1Mutc": 30 * 86400,
}
DATE_RANGE_DAYS = {
    "m1": 31,
    "m3": 93,
    "m6": 186,
    "y1": 365,
    "y2": 730,
    "y5": 1826,
}


def _source_interval_seconds(interval: str) -> int | None:
    return PROVIDER_INTERVAL_SECONDS.get(interval)


def _history_start_ms(request: ChartRequest, interval_seconds: int) -> int | None:
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
    return max(0, (cutoff - 199 * interval_seconds) * 1000)


def _dedupe_rows(rows: list[list[Any]]) -> list[list[Any]]:
    unique: dict[int, list[Any]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        timestamp = safe_float(row[0])
        if timestamp is not None:
            unique[int(timestamp)] = row
    return [unique[timestamp] for timestamp in sorted(unique)]


async def _fetch_binance_klines(
    session: aiohttp.ClientSession,
    request: ChartRequest,
    market: str,
) -> list[list[Any]]:
    symbol = BINANCE_CRYPTO_SYMBOLS[request.ticker][0]
    interval = _binance_interval(request)
    limit = BINANCE_KLINE_LIMITS[market]
    base_url = BINANCE_FUTURES_BASE_URL if market == "perp" else BINANCE_SPOT_BASE_URL
    path = "/fapi/v1/klines" if market == "perp" else "/api/v3/klines"
    interval_seconds = _source_interval_seconds(interval)
    if interval_seconds is None:
        raise ValueError(f"Unsupported crypto interval `{interval}`.")
    rows: list[list[Any]] = []
    start_time = _history_start_ms(request, interval_seconds)

    while True:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        try:
            data = await _request_json(session, f"{base_url}{path}", params=params)
        except MarketDataHTTPError as error:
            if error.status == 404:
                raise NoChartData(f"No chart data found for `{request.ticker}`.") from error
            raise
        if not isinstance(data, list) or not data:
            break
        page = [row for row in data if isinstance(row, list) and len(row) >= 6]
        rows.extend(page)
        if start_time is None or len(data) < limit or not page:
            break
        next_start_time = int(page[-1][0]) + 1
        if next_start_time <= start_time or next_start_time >= int(time.time() * 1000):
            break
        start_time = next_start_time

    rows = _dedupe_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


async def _fetch_okx_swap_klines(session: aiohttp.ClientSession, request: ChartRequest) -> list[list[Any]]:
    symbol = BINANCE_CRYPTO_SYMBOLS[request.ticker][0].replace("USDT", "-USDT-SWAP")
    interval = _okx_interval(request)
    interval_seconds = _source_interval_seconds(interval)
    if interval_seconds is None:
        raise ValueError(f"Unsupported crypto interval `{interval}`.")
    cutoff = _history_start_ms(request, interval_seconds)
    rows: list[list[Any]] = []
    after: int | None = None
    while True:
        params: dict[str, Any] = {
            "instId": symbol,
            "bar": interval,
            "limit": 300,
        }
        if after is not None:
            params["after"] = after
        try:
            data = await _request_json(session, f"{OKX_BASE_URL}/api/v5/market/history-candles", params=params)
        except MarketDataHTTPError as error:
            if error.status == 404:
                raise NoChartData(f"No chart data found for `{request.ticker}`.") from error
            raise
        if not isinstance(data, dict) or data.get("code") != "0":
            raise MarketDataProviderError("Market data provider returned an error")
        page = data.get("data") or []
        if not isinstance(page, list) or not page:
            break
        valid_page = [row for row in page if isinstance(row, list) and len(row) >= 7]
        rows.extend(valid_page)
        if not valid_page or len(page) < 300:
            break
        oldest = min(int(row[0]) for row in valid_page)
        if cutoff is None or oldest <= cutoff or oldest == after:
            break
        after = oldest

    rows = _dedupe_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


async def _fetch_binance_24h_ticker(
    session: aiohttp.ClientSession,
    request: ChartRequest,
    market: str,
) -> tuple[float, float, int] | None:
    symbol = BINANCE_CRYPTO_SYMBOLS[request.ticker][0]
    base_url = BINANCE_FUTURES_BASE_URL if market == "perp" else BINANCE_SPOT_BASE_URL
    path = "/fapi/v1/ticker/24hr" if market == "perp" else "/api/v3/ticker/24hr"
    data = await _request_json(session, f"{base_url}{path}", params={"symbol": symbol})
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
) -> tuple[float, float, int] | None:
    symbol = BINANCE_CRYPTO_SYMBOLS[request.ticker][0].replace("USDT", "-USDT-SWAP")
    data = await _request_json(
        session,
        f"{OKX_BASE_URL}/api/v5/market/ticker",
        params={"instId": symbol},
    )
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


async def _optional_ticker(task: asyncio.Task[tuple[float, float, int] | None]) -> tuple[float, float, int] | None:
    try:
        return await task
    except (aiohttp.ClientError, TimeoutError, MarketDataProviderError, JSONDecodeError):
        return None


def _binance_quote_from_klines(
    rows: list[list[Any]],
    request: ChartRequest,
    market: str,
    source_label: str,
    display_market: str,
    ticker_24h: tuple[float, float, int] | None,
) -> ChartData:
    dates: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    close_times: list[int] = []
    for row in rows:
        open_time = safe_float(row[0])
        close_time = safe_float(row[6]) if len(row) > 6 else None
        open_ = safe_float(row[1])
        high = safe_float(row[2])
        low = safe_float(row[3])
        close = safe_float(row[4])
        volume = safe_float(row[5])
        if open_time is None or open_ is None or high is None or low is None or close is None:
            continue
        dates.append(int(open_time // 1000))
        opens.append(open_ or 0.0)
        highs.append(high or 0.0)
        lows.append(low or 0.0)
        closes.append(close or 0.0)
        volumes.append(volume or 0.0)
        close_times.append(int((close_time or open_time) // 1000))

    if len(closes) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")

    now = int(time.time())
    last, previous, last_time = ticker_24h or (closes[-1], None, min(close_times[-1], now))
    change = last - previous if previous is not None else None
    symbol, display_name = BINANCE_CRYPTO_SYMBOLS[request.ticker]
    interval = _binance_interval(request)
    return ChartData(
        ticker=request.ticker,
        name=f"{display_name} {display_market} ({symbol}, {source_label})",
        rows=normalize_chart_rows(dates, opens, highs, lows, closes, volumes, last_close=last),
        last_close=last,
        last_time=last_time,
        previous_close=previous,
        change=change,
        change_percent=(change / previous * 100) if change is not None and previous else None,
        market_label=f"{source_label} {display_market}",
        source_interval_seconds=_source_interval_seconds(interval),
    )


def _okx_quote_from_klines(
    rows: list[list[Any]],
    request: ChartRequest,
    ticker_24h: tuple[float, float, int] | None,
) -> ChartData:
    ordered_rows = sorted(rows, key=lambda row: int(row[0]))
    dates: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    for row in ordered_rows:
        open_time = safe_float(row[0])
        open_ = safe_float(row[1])
        high = safe_float(row[2])
        low = safe_float(row[3])
        close = safe_float(row[4])
        base_volume = safe_float(row[6])
        if open_time is None or open_ is None or high is None or low is None or close is None:
            continue
        dates.append(int(open_time // 1000))
        opens.append(open_)
        highs.append(high)
        lows.append(low)
        closes.append(close)
        volumes.append(base_volume or 0.0)

    if len(closes) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")

    last, previous, last_time = ticker_24h or (closes[-1], None, min(dates[-1], int(time.time())))
    change = last - previous if previous is not None else None
    _, display_name = BINANCE_CRYPTO_SYMBOLS[request.ticker]
    inst_id = BINANCE_CRYPTO_SYMBOLS[request.ticker][0].replace("USDT", "-USDT-SWAP")
    return ChartData(
        ticker=request.ticker,
        name=f"{display_name} perpetual ({inst_id}, OKX)",
        rows=normalize_chart_rows(dates, opens, highs, lows, closes, volumes, last_close=last),
        last_close=last,
        last_time=last_time,
        previous_close=previous,
        change=change,
        change_percent=(change / previous * 100) if change is not None and previous else None,
        market_label="OKX perp",
        source_interval_seconds=_source_interval_seconds(_okx_interval(request)),
    )


async def fetch_crypto_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> ChartData:
    market = _crypto_auto_market(request)
    if market == "perp":
        okx_ticker_task = asyncio.create_task(_fetch_okx_24h_ticker(session, request))
        try:
            rows = await _fetch_okx_swap_klines(session, request)
        except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError):
            okx_ticker_task.cancel()
            await asyncio.gather(okx_ticker_task, return_exceptions=True)
            LOGGER.info("provider_fallback source=okx target=binance market=perp")
        else:
            ticker_24h = await _optional_ticker(okx_ticker_task)
            return aggregate_chart_data(_okx_quote_from_klines(rows, request, ticker_24h), request)

    binance_ticker_task = asyncio.create_task(_fetch_binance_24h_ticker(session, request, market))
    try:
        rows = await _fetch_binance_klines(session, request, market)
    except BaseException:
        binance_ticker_task.cancel()
        await asyncio.gather(binance_ticker_task, return_exceptions=True)
        raise
    ticker_24h = await _optional_ticker(binance_ticker_task)
    data = _binance_quote_from_klines(
        rows,
        request,
        market,
        "Binance",
        "perp" if market == "perp" else "spot",
        ticker_24h,
    )
    return aggregate_chart_data(data, request)


async def fetch_market_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> ChartData:
    if request.crypto_market:
        return await fetch_crypto_chart_data(session, request)

    daily_reference_task = (
        asyncio.create_task(fetch_daily_previous_close(session, request))
        if request.futures and request.timeframe != "d"
        else None
    )
    try:
        result = _chart_result(await _request_json(session, yahoo_chart_url(request)), request.ticker)
    except BaseException as error:
        if daily_reference_task is not None:
            daily_reference_task.cancel()
            await asyncio.gather(daily_reference_task, return_exceptions=True)
        if isinstance(error, MarketDataHTTPError) and error.status == 404:
            raise NoChartData(f"No chart data found for `{request.ticker}`.") from error
        raise
    meta = result.get("meta") or {}
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    dates = result.get("timestamp") or []
    closes = raw_quote.get("close") or []
    last, last_time = latest_quote_price_time(meta, dates, closes, request)
    prev = stock_previous_close(meta, closes, request)
    if daily_reference_task is not None:
        daily_prev = await daily_reference_task
        if daily_prev is not None:
            prev = daily_prev
    elif not request.futures and request.timeframe != "d" and prev is None:
        prev = await fetch_daily_previous_close(session, request)
    change = (last - prev) if last is not None and prev else None
    raw_data = {
        "ticker": request.ticker,
        "futures": request.futures,
        "name": meta.get("shortName") or meta.get("longName") or request.ticker,
        "date": dates,
        "open": raw_quote.get("open") or [],
        "high": raw_quote.get("high") or [],
        "low": raw_quote.get("low") or [],
        "close": closes,
        "volume": raw_quote.get("volume") or [],
        "lastClose": last,
        "lastTime": last_time,
        "prevClose": prev,
        "perfDayUsd": change,
    }
    if request.timeframe == "d" and not request.futures and has_close_only_latest_ohlc(raw_data):
        intraday_quote = await fetch_current_day_intraday_quote(session, request)
        if intraday_quote is not None:
            raw_data = patch_close_only_latest_ohlc(raw_data, intraday_quote)

    interval = str(meta.get("dataGranularity") or "")
    chart_data = ChartData(
        ticker=request.ticker,
        name=str(meta.get("shortName") or meta.get("longName") or request.ticker),
        rows=normalize_chart_rows(
            raw_data["date"],
            raw_data["open"],
            raw_data["high"],
            raw_data["low"],
            raw_data["close"],
            raw_data["volume"],
            last_close=last,
        ),
        last_close=last,
        last_time=last_time,
        previous_close=prev,
        change=change,
        change_percent=(change / prev * 100) if change is not None and prev else None,
        futures=request.futures,
        source_interval_seconds=_source_interval_seconds(interval),
    )
    return aggregate_chart_data(chart_data, request)


async def send_chart(channel: discord.abc.Messageable, request: ChartRequest) -> None:
    session = client.session
    if session is None:
        await channel.send("Market data is temporarily unavailable. Try again in a minute.", allowed_mentions=NO_MENTIONS)
        return
    started = time.perf_counter()
    async with channel.typing():
        try:
            async with asyncio.timeout(MARKET_DATA_BUDGET_SECONDS):
                async with FETCH_SEMAPHORE:
                    data = await fetch_market_chart_data(session, request)
                fetched = time.perf_counter()
                async with RENDER_SEMAPHORE:
                    image = await asyncio.to_thread(render_price_chart_png, data, request)
                rendered = time.perf_counter()
        except NoChartData as error:
            LOGGER.info("chart outcome=no_data")
            await channel.send(str(error), allowed_mentions=NO_MENTIONS)
            return
        except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError) as error:
            LOGGER.warning("chart outcome=provider_error error_type=%s", type(error).__name__)
            await channel.send("Market data is temporarily unavailable. Try again in a minute.", allowed_mentions=NO_MENTIONS)
            return

    LOGGER.info(
        "chart outcome=success provider=%s fetch_ms=%d render_ms=%d total_ms=%d",
        data.market_label or "yahoo",
        round((fetched - started) * 1000),
        round((rendered - fetched) * 1000),
        round((rendered - started) * 1000),
    )

    filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
    file = discord.File(io.BytesIO(image), filename=filename)
    embed = discord.Embed(
        title=chart_title(request, data.market_label or None),
        description=quote_description(data),
        color=0x2ECC71 if (data.change or 0.0) >= 0 else 0xFF5252,
    )
    embed.set_image(url=f"attachment://{filename}")
    try:
        await channel.send(embed=embed, file=file, allowed_mentions=NO_MENTIONS)
    except discord.HTTPException:
        await channel.send("Chart rendered, but Discord rejected the image upload.", allowed_mentions=NO_MENTIONS)


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Missing DISCORD_TOKEN. Put it in .env or export it.")
    handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    client.run(token, log_handler=handler, log_level=logging.INFO)


if __name__ == "__main__":
    main()
