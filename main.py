import io
from json import JSONDecodeError
import os
import time
from typing import Any

from charting import (
    BINANCE_CRYPTO_SYMBOLS,
    PREFIX,
    ChartRequest,
    NoChartData,
    _has_close_only_latest_ohlc,
    _patch_close_only_latest_ohlc,
    _safe_float,
    _latest_quote_price_time,
    aggregate_yahoo_chart_data,
    _stock_previous_close,
    chart_title,
    parse_chart_command,
    quote_description,
    render_price_chart_png,
    yahoo_chart_url,
)

import aiohttp
import discord
from dotenv import load_dotenv


class MarketDataProviderError(RuntimeError):
    pass

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
Crypto: `;BTC`, `;BTC d`, `;ETH`, `;ETH 1y percent`
Crypto history: `;BTC max`, `;ETH max`
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
OHLCV history. `;BTC max` fetches all available Binance spot chart history. Every chart image is
rendered locally from market chart data.
"""

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=12)
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

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
NO_MENTIONS = discord.AllowedMentions.none()


@client.event
async def on_ready() -> None:
    print(f"{client.user} is online")


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


async def fetch_daily_previous_close(session: aiohttp.ClientSession, request: ChartRequest) -> float | None:
    daily_request = ChartRequest(
        request.ticker,
        "d",
        "daily",
        date_range="m1",
        date_range_label="1 month",
        futures=request.futures,
    )
    async with session.get(yahoo_chart_url(daily_request), headers={"Accept": "application/json"}) as response:
        if response.status != 200:
            return None
        data = await response.json(content_type=None)

    chart = data.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        return None
    raw_quote = ((results[0].get("indicators") or {}).get("quote") or [{}])[0]
    closes = raw_quote.get("close") or []
    valid_closes = [close for close in (_safe_float(value) for value in closes) if close is not None]
    return valid_closes[-2] if len(valid_closes) > 1 else None


async def fetch_current_day_intraday_quote(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any] | None:
    intraday_request = ChartRequest(
        request.ticker,
        "i1",
        "1 min",
        futures=request.futures,
    )
    intraday_url = yahoo_chart_url(intraday_request).replace("range=5d", "range=1d").replace(
        "includePrePost=true",
        "includePrePost=false",
    )
    async with session.get(intraday_url, headers={"Accept": "application/json"}) as response:
        if response.status != 200:
            return None
        data = await response.json(content_type=None)

    chart = data.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        return None
    result = results[0]
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    return {
        "ticker": request.ticker,
        "futures": request.futures,
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
    rows: list[list[Any]] = []
    start_time = 0 if request.date_range == "max" else None

    while True:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        async with session.get(f"{base_url}{path}", params=params, headers={"Accept": "application/json"}) as response:
            if response.status == 404:
                raise NoChartData(f"No chart data found for `{request.ticker}`.")
            if response.status != 200:
                raise MarketDataProviderError("Market data provider returned an error")
            data = await response.json(content_type=None)
        if not isinstance(data, list) or not data:
            break
        page = [row for row in data if isinstance(row, list) and len(row) >= 6]
        rows.extend(page)
        if request.date_range != "max" or len(data) < limit:
            break
        next_start_time = int(page[-1][0]) + 1
        if next_start_time == start_time:
            break
        start_time = next_start_time

    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


async def _fetch_okx_swap_klines(session: aiohttp.ClientSession, request: ChartRequest) -> list[list[Any]]:
    symbol = BINANCE_CRYPTO_SYMBOLS[request.ticker][0].replace("USDT", "-USDT-SWAP")
    params: dict[str, Any] = {
        "instId": symbol,
        "bar": _okx_interval(request),
        "limit": 300,
    }
    async with session.get(f"{OKX_BASE_URL}/api/v5/market/candles", params=params, headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"No chart data found for `{request.ticker}`.")
        if response.status != 200:
            raise MarketDataProviderError("Market data provider returned an error")
        data = await response.json(content_type=None)
    if not isinstance(data, dict) or data.get("code") != "0":
        raise MarketDataProviderError("Market data provider returned an error")
    rows = data.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return [row for row in rows if isinstance(row, list) and len(row) >= 7]


def _binance_quote_from_klines(
    rows: list[list[Any]],
    request: ChartRequest,
    market: str,
    source_label: str,
    display_market: str,
) -> dict[str, Any]:
    dates: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    close_times: list[int] = []
    for row in rows:
        open_time = _safe_float(row[0])
        close_time = _safe_float(row[6]) if len(row) > 6 else None
        open_ = _safe_float(row[1])
        high = _safe_float(row[2])
        low = _safe_float(row[3])
        close = _safe_float(row[4])
        volume = _safe_float(row[5])
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
    last = closes[-1]
    prev = closes[-2]
    change = last - prev
    symbol, display_name = BINANCE_CRYPTO_SYMBOLS[request.ticker]
    return {
        "ticker": request.ticker,
        "name": f"{display_name} {display_market} ({symbol}, {source_label})",
        "marketLabel": f"{source_label} {display_market}",
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "lastClose": last,
        "lastTime": min(close_times[-1], now),
        "prevClose": prev,
        "perfDayUsd": change,
        "perfDayPct": (change / prev * 100) if prev else None,
    }


def _okx_quote_from_klines(rows: list[list[Any]], request: ChartRequest) -> dict[str, Any]:
    ordered_rows = sorted(rows, key=lambda row: int(row[0]))
    dates: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    for row in ordered_rows:
        open_time = _safe_float(row[0])
        open_ = _safe_float(row[1])
        high = _safe_float(row[2])
        low = _safe_float(row[3])
        close = _safe_float(row[4])
        base_volume = _safe_float(row[6])
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

    last = closes[-1]
    prev = closes[-2]
    change = last - prev
    _, display_name = BINANCE_CRYPTO_SYMBOLS[request.ticker]
    inst_id = BINANCE_CRYPTO_SYMBOLS[request.ticker][0].replace("USDT", "-USDT-SWAP")
    return {
        "ticker": request.ticker,
        "name": f"{display_name} perpetual ({inst_id}, OKX)",
        "marketLabel": "OKX perp",
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "lastClose": last,
        "lastTime": min(dates[-1], int(time.time())),
        "prevClose": prev,
        "perfDayUsd": change,
        "perfDayPct": (change / prev * 100) if prev else None,
    }


async def fetch_binance_crypto_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any]:
    market = _crypto_auto_market(request)
    try:
        rows = await _fetch_binance_klines(session, request, market)
    except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError):
        if market != "perp":
            raise
        okx_rows = await _fetch_okx_swap_klines(session, request)
        quote = _okx_quote_from_klines(okx_rows, request)
        return aggregate_yahoo_chart_data(quote, request)
    quote = _binance_quote_from_klines(
        rows,
        request,
        market,
        "Binance",
        "perp" if market == "perp" else "spot",
    )
    return aggregate_yahoo_chart_data(quote, request)


async def fetch_market_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any]:
    if request.crypto_market:
        return await fetch_binance_crypto_chart_data(session, request)

    async with session.get(yahoo_chart_url(request), headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"No chart data found for `{request.ticker}`.")
        if response.status != 200:
            raise MarketDataProviderError("Market data provider returned an error")
        data = await response.json(content_type=None)

    chart = data.get("chart") or {}
    error = chart.get("error")
    if error:
        code = str(error.get("code") if isinstance(error, dict) else error).lower()
        description = str(error.get("description") if isinstance(error, dict) else "").lower()
        if "not found" in code or "not found" in description or "no data" in description:
            raise NoChartData(f"No chart data found for `{request.ticker}`.")
        raise MarketDataProviderError("Market data provider returned an error")
    results = chart.get("result") or []
    if not results:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")

    result = results[0]
    meta = result.get("meta") or {}
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    dates = result.get("timestamp") or []
    closes = raw_quote.get("close") or []
    last, last_time = _latest_quote_price_time(meta, dates, closes, request)
    prev = _stock_previous_close(meta, closes, request)
    if request.timeframe != "d":
        try:
            daily_prev = await fetch_daily_previous_close(session, request)
        except (aiohttp.ClientError, TimeoutError, JSONDecodeError):
            daily_prev = None
        if daily_prev is not None:
            prev = daily_prev
    change = (last - prev) if last is not None and prev else None
    quote = {
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
        "perfDayPct": (change / prev * 100) if change is not None and prev else None,
    }
    if request.timeframe == "d" and not request.futures and _has_close_only_latest_ohlc(quote):
        try:
            intraday_quote = await fetch_current_day_intraday_quote(session, request)
        except (aiohttp.ClientError, TimeoutError, JSONDecodeError):
            intraday_quote = None
        if intraday_quote is not None:
            quote = _patch_close_only_latest_ohlc(quote, intraday_quote)
    return aggregate_yahoo_chart_data(quote, request)


async def send_chart(channel: discord.abc.Messageable, request: ChartRequest) -> None:
    headers = {
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache",
    }
    description = None

    async with channel.typing():
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, headers=headers) as session:
                quote = await fetch_market_chart_data(session, request)
                image = render_price_chart_png(quote, request)
                description = quote_description(quote)
        except NoChartData as error:
            await channel.send(str(error), allowed_mentions=NO_MENTIONS)
            return
        except (aiohttp.ClientError, TimeoutError, JSONDecodeError, MarketDataProviderError):
            await channel.send("Market data is temporarily unavailable. Try again in a minute.", allowed_mentions=NO_MENTIONS)
            return

    filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
    file = discord.File(io.BytesIO(image), filename=filename)
    embed = discord.Embed(
        title=chart_title(request, str(quote.get("marketLabel")) if quote.get("marketLabel") else None),
        description=description,
        color=0x2ECC71 if (_safe_float(quote.get("perfDayUsd")) or 0.0) >= 0 else 0xFF5252,
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
    client.run(token)


if __name__ == "__main__":
    main()
