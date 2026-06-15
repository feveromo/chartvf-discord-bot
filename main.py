import io
import os
import sys
import time
from typing import Any

from charting import (
    CHART_IMAGE_MIN_BYTES,
    PREFIX,
    ChartRequest,
    NoChartData,
    _safe_float,
    _stock_previous_close,
    chart_title,
    finviz_chart_url,
    finviz_quote_api_url,
    is_stock_yahoo_chart,
    legacy_finviz_chart_url,
    parse_chart_command,
    quote_description,
    render_price_chart_png,
    self_test,
    yahoo_stock_chart_url,
)


if __name__ == "__main__" and "--self-test" in sys.argv:
    self_test()
    print("self-test ok")
    raise SystemExit(0)

import aiohttp
import discord
from dotenv import load_dotenv

HELP_TEXT = """**Finviz chart bot**

**Syntax**
`;TICKER [timeframe] [type] [range] [theme] [scale]` — stocks
`;fut ROOT [timeframe] [type] [range] [theme] [scale]` — futures

**Examples**
`;AAPL` → latest 5-minute candle chart
`;AAPL d` → daily candle chart
`;AMD 1` → AMD 1-minute intraday chart
`;QQQ w line` → weekly line chart
`;LULU 1y` → 1-year chart
`;AAPL light log` → light theme, log scale
`;fut ES` → E-mini S&P daily candle
`;fut ES 15` → E-mini S&P 15-minute chart
`;fut CL w line` → crude oil weekly line
`;futures GC 1y` → gold 1-year chart

**Options** (same for stocks and futures)
Timeframes: stocks support `d`, `w`, `m`, plus intraday `1`, `2`, `5`, `15`, `30`, `60`, `4h`; futures also support `3`, `10`, `2h`
Types: `candle`, `line`
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`
Themes: `dark`, `light`
Scales: `linear`, `log`, `percent`

Options can be in any order after the ticker.

**Futures** (`;fut`/`;future`/`;futures`): `;f` is still Ford (`F`). Futures are
rendered from Finviz's futures quote API, so roots like `ES`, `NQ`, `GC`, `CL`,
`6E`, and `VX` work even when Finviz's stock image endpoint would collide.

**Stock freshness**: bare stock commands default to the latest 5-minute chart.
Default, daily, and stock intraday charts are rendered from Yahoo chart data so
the candle, price badge, and updated timestamp come from the same fresher feed.
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


async def fetch_quote_data(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any]:
    async with session.get(finviz_quote_api_url(request), headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"Finviz has no chart data for `{request.ticker}`.")
        if response.status != 200:
            raise RuntimeError(f"Finviz quote check returned HTTP {response.status}")
        data = await response.json(content_type=None)
    if not data.get("date"):
        raise NoChartData(f"Finviz has no chart data for `{request.ticker}`.")
    return data


async def fetch_stock_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> dict[str, Any]:
    async with session.get(yahoo_stock_chart_url(request), headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"Yahoo has no chart data for `{request.ticker}`.")
        if response.status != 200:
            raise RuntimeError(f"Yahoo chart check returned HTTP {response.status}")
        data = await response.json(content_type=None)

    chart = data.get("chart") or {}
    if chart.get("error"):
        raise NoChartData(f"Yahoo has no chart data for `{request.ticker}`.")
    results = chart.get("result") or []
    if not results:
        raise NoChartData(f"Yahoo has no chart data for `{request.ticker}`.")

    result = results[0]
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    dates = result.get("timestamp") or []
    closes = quote.get("close") or []
    valid_closes = [close for close in (_safe_float(value) for value in closes) if close is not None]
    last = _safe_float(meta.get("regularMarketPrice")) or next(
        (_safe_float(value) for value in reversed(closes) if _safe_float(value) is not None),
        None,
    )
    prev = _stock_previous_close(meta, valid_closes, request)
    change = (last - prev) if last is not None and prev else None
    return {
        "ticker": request.ticker,
        "name": request.ticker,
        "date": dates,
        "open": quote.get("open") or [],
        "high": quote.get("high") or [],
        "low": quote.get("low") or [],
        "close": closes,
        "volume": quote.get("volume") or [],
        "lastClose": last,
        "lastTime": meta.get("regularMarketTime") or (dates[-1] if dates else None),
        "prevClose": prev,
        "perfDayUsd": change,
        "perfDayPct": (change / prev * 100) if change is not None and prev else None,
    }


async def fetch_chart_image(session: aiohttp.ClientSession, request: ChartRequest, url: str) -> bytes:
    async with session.get(url, headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}) as response:
        if response.status != 200:
            raise RuntimeError(f"Finviz returned HTTP {response.status}")
        image = await response.read()
    if not image.startswith((b"\x89PNG", b"\xff\xd8", b"GIF")):
        raise RuntimeError("Finviz did not return an image")
    if len(image) < CHART_IMAGE_MIN_BYTES:
        # Size floor catches Finviz's valid-PNG empty chart for bad stock tickers.
        raise NoChartData(f"Finviz returned an empty chart for `{request.ticker}`.")
    return image


async def send_chart(channel: discord.abc.Messageable, request: ChartRequest) -> None:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": (
            f"https://finviz.com/futures_charts?t={request.ticker}" if request.futures
            else f"https://finviz.com/quote.ashx?t={request.ticker}"
        ),
        "Cache-Control": "no-cache",
        "Cookie": f"chartsTheme={request.theme}",
    }
    description = None

    async with channel.typing():
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, headers=headers) as session:
                if request.futures:
                    quote = await fetch_quote_data(session, request)
                    image = render_price_chart_png(quote, request)
                    description = quote_description(quote)
                elif is_stock_yahoo_chart(request):
                    quote = await fetch_stock_chart_data(session, request)
                    image = render_price_chart_png(quote, request)
                    description = quote_description(quote)
                else:
                    try:
                        quote = await fetch_quote_data(session, request)
                        description = quote_description(quote)
                    except NoChartData:
                        raise
                    except (aiohttp.ClientError, RuntimeError, TimeoutError, ValueError):
                        pass  # precheck is best-effort; the image fetch still proves the chart.

                    direct_url = finviz_chart_url(request, cache_bust=True)
                    legacy_url = legacy_finviz_chart_url(request)
                    try:
                        image = await fetch_chart_image(session, request, direct_url)
                    except NoChartData:
                        raise
                    except (aiohttp.ClientError, RuntimeError, TimeoutError):
                        image = await fetch_chart_image(session, request, legacy_url)
        except NoChartData as error:
            await channel.send(str(error))
            return
        except Exception as error:
            if request.futures or is_stock_yahoo_chart(request):
                await channel.send(f"Upload failed ({error}).")
                return
            embed = discord.Embed(
                title=chart_title(request),
                color=0x2ECC71,
            )
            embed.set_image(url=legacy_finviz_chart_url(request, cache_bust=True))
            await channel.send(f"Upload failed ({error}). Trying the legacy Finviz embed:", embed=embed)
            return

    filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
    file = discord.File(io.BytesIO(image), filename=filename)
    embed = discord.Embed(
        title=chart_title(request),
        description=description,
        color=0x2ECC71,
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
