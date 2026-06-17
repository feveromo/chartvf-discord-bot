import io
import os
import sys
import time
from typing import Any

from charting import (
    PREFIX,
    ChartRequest,
    NoChartData,
    _safe_float,
    _latest_quote_price_time,
    aggregate_yahoo_chart_data,
    _stock_previous_close,
    chart_title,
    parse_chart_command,
    quote_description,
    render_price_chart_png,
    self_test,
    yahoo_chart_url,
)


if __name__ == "__main__" and "--self-test" in sys.argv:
    self_test()
    print("self-test ok")
    raise SystemExit(0)

import aiohttp
import discord
from dotenv import load_dotenv

HELP_TEXT = """**ChartVF**

**Syntax**
`;TICKER [timeframe] [type] [range] [theme] [scale]` — stocks
`;fut ROOT [timeframe] [type] [range] [theme] [scale]` — futures

**Examples**
`;AAPL` → latest 5-minute candle chart
`;AAPL d` → daily candle chart
`;AMD 1` → AMD 1-minute intraday chart
`;QQQ w line` → weekly line chart
`;LULU 1y` → 1-year chart
`;AAPL dark log` → dark theme, log scale
`;fut ES` → E-mini S&P daily candle
`;fut ES 15` → E-mini S&P 15-minute chart
`;fut CL w line` → crude oil weekly line
`;futures GC 1y` → gold 1-year chart
Indexes: `;SPX`, `;NDX`, `;DJX`/`;DJI`/`;DJIA`, `;RUT`, `;RUI`, `;VIX`, `;IXIC`, `;OEX`

**Options** (same for stocks and futures)
Timeframes: stocks support `d`, `w`, `m`, plus intraday `1`, `2`, `5`, `15`, `30`, `60`, `4h`; futures also support `3`, `10`, `2h`
Types: `candle`, `line`
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`
Themes: `dark`, `light`
Scales: `linear`, `log`, `percent`

Options can be in any order after the ticker.

**Futures** (`;fut`/`;future`/`;futures`): `;f` is still Ford (`F`).

**Freshness**: bare stock commands default to the latest 5-minute chart. Every
chart image is rendered locally from market chart data.
"""

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=12)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    print(f"{client.user} is online")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.content.startswith(PREFIX):
        return

    command_text = message.content[len(PREFIX):].strip()
    if not command_text:
        await message.channel.send(HELP_TEXT)
        return
    if command_text.split(maxsplit=1)[0].lower() in {"help", "h"}:
        await message.channel.send(HELP_TEXT)
        return

    try:
        request = parse_chart_command(message.content)
    except ValueError as error:
        await message.channel.send(str(error))
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


async def fetch_market_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any]:
    async with session.get(yahoo_chart_url(request), headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"No chart data found for `{request.ticker}`.")
        if response.status != 200:
            raise RuntimeError(f"Chart data fetch returned HTTP {response.status}")
        data = await response.json(content_type=None)

    chart = data.get("chart") or {}
    if chart.get("error"):
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    results = chart.get("result") or []
    if not results:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")

    result = results[0]
    meta = result.get("meta") or {}
    raw_quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    dates = result.get("timestamp") or []
    closes = raw_quote.get("close") or []
    valid_closes = [close for close in (_safe_float(value) for value in closes) if close is not None]
    last, last_time = _latest_quote_price_time(meta, dates, closes, request)
    prev = _stock_previous_close(meta, valid_closes, request)
    if request.timeframe != "d":
        prev = await fetch_daily_previous_close(session, request) or prev
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
            await channel.send(str(error))
            return
        except Exception as error:
            await channel.send(f"Upload failed ({error}).")
            return

    filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
    file = discord.File(io.BytesIO(image), filename=filename)
    embed = discord.Embed(
        title=chart_title(request),
        description=description,
        color=0x2ECC71 if (_safe_float(quote.get("perfDayUsd")) or 0.0) >= 0 else 0xFF5252,
    )
    embed.set_image(url=f"attachment://{filename}")
    await channel.send(embed=embed, file=file)


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Missing DISCORD_TOKEN. Put it in .env or export it.")
    client.run(token)


if __name__ == "__main__":
    main()
