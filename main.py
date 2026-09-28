import asyncio
import contextlib
import io
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import discord
from dotenv import load_dotenv

from charting import (
    HELP_COMMANDS,
    PREFIX,
    ChartRequest,
    NoChartData,
    chart_title,
    parse_chart_command,
    quote_description,
    render_price_chart_png,
)
from market_data import fetch_market_chart_data
from market_http import PROVIDER_ERRORS, create_session
from webull import WebullStreamer

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

**Faces**: `;)`, `;p`, and `;D` on their own are left alone; `;d` or `;D d` charts Dominion.

**Freshness**: bare stock, futures, and crypto commands default to the latest 5-minute chart.
Stock intraday charts use real-time Webull candles (tick-level push, pre/post market included),
with TradingView 24-hour candles as fallback.
Supported futures intraday charts use delayed TradingView continuous-contract candles.
Crypto intraday charts use perp data; crypto daily/weekly/monthly and range charts use Binance spot
OHLCV history. Crypto change figures are rolling 24-hour values. `;BTC max` fetches all available
Binance spot chart history. Every chart image is
rendered locally from market chart data.
"""

# Budget for the network fetch only; rendering is local and fast.
MARKET_DATA_BUDGET_SECONDS = 15
# Renders take ~30 ms and overlap well; two threads finish a 10-chart burst in
# ~0.25 s while keeping memory flat on hosts that report many CPUs.
RENDER_WORKERS = 2
UNAVAILABLE_MESSAGE = "Market data is temporarily unavailable. Try again in a minute."
ERROR_MESSAGE = "Something went wrong making that chart."
NO_MENTIONS = discord.AllowedMentions.none()
LOGGER = logging.getLogger("chartvf")


class ChartBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents, max_messages=0, allowed_mentions=NO_MENTIONS)
        self.session: aiohttp.ClientSession | None = None
        self.webull_streamer: WebullStreamer | None = None
        self.render_pool = ThreadPoolExecutor(RENDER_WORKERS, thread_name_prefix="render")

    async def setup_hook(self) -> None:
        self.session = create_session()
        self.webull_streamer = WebullStreamer()
        self.webull_streamer.start()

    async def close(self) -> None:
        if self.webull_streamer is not None:
            self.webull_streamer.stop()
            self.webull_streamer = None
        if self.session is not None:
            await self.session.close()
            self.session = None
        self.render_pool.shutdown(wait=False, cancel_futures=True)
        await super().close()

    async def on_ready(self) -> None:
        LOGGER.info("gateway_ready")

    async def on_message(self, message: discord.Message) -> None:
        # discord.py runs each event in its own task, so rapid-fire commands
        # fetch and render concurrently.
        if message.author.bot or not message.content.startswith(PREFIX):
            return
        words = message.content[len(PREFIX):].split(maxsplit=1)
        if not words or words[0].lower() in HELP_COMMANDS:
            await message.channel.send(HELP_TEXT)
            return
        try:
            request = parse_chart_command(message.content)
        except ValueError as error:
            await message.channel.send(str(error))
            return
        if request is not None:
            await self.send_chart(message.channel, request)

    async def send_chart(
        self, channel: discord.abc.Messageable, request: ChartRequest
    ) -> None:
        try:
            await self._send_chart(channel, request)
        except Exception:
            LOGGER.exception("chart outcome=error ticker=%s", request.ticker)
            with contextlib.suppress(discord.HTTPException):
                await channel.send(ERROR_MESSAGE)

    async def _send_chart(
        self, channel: discord.abc.Messageable, request: ChartRequest
    ) -> None:
        if self.session is None:
            await channel.send(UNAVAILABLE_MESSAGE)
            return
        started = time.perf_counter()
        async with channel.typing():
            try:
                async with asyncio.timeout(MARKET_DATA_BUDGET_SECONDS):
                    data = await fetch_market_chart_data(
                        self.session, request, self.webull_streamer
                    )
                fetched = time.perf_counter()
                image = await asyncio.get_running_loop().run_in_executor(
                    self.render_pool, render_price_chart_png, data, request
                )
                rendered = time.perf_counter()
            except NoChartData as error:
                LOGGER.info("chart outcome=no_data ticker=%s", request.ticker)
                await channel.send(str(error))
                return
            except PROVIDER_ERRORS as error:
                LOGGER.warning(
                    "chart outcome=provider_error ticker=%s error_type=%s",
                    request.ticker,
                    type(error).__name__,
                )
                await channel.send(UNAVAILABLE_MESSAGE)
                return

        LOGGER.info(
            "chart outcome=success ticker=%s provider=%s fetch_ms=%d render_ms=%d total_ms=%d",
            request.ticker,
            data.market_label or "yahoo",
            round((fetched - started) * 1000),
            round((rendered - fetched) * 1000),
            round((rendered - started) * 1000),
        )
        filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
        embed = discord.Embed(
            title=chart_title(request, data.market_label or None),
            description=quote_description(data),
            color=0x2ECC71 if (data.change or 0.0) >= 0 else 0xFF5252,
        )
        embed.set_image(url=f"attachment://{filename}")
        try:
            await channel.send(embed=embed, file=discord.File(io.BytesIO(image), filename=filename))
        except discord.HTTPException:
            LOGGER.warning("chart outcome=upload_rejected ticker=%s", request.ticker)
            await channel.send("Chart rendered, but Discord rejected the image upload.")


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Missing DISCORD_TOKEN. Put it in .env or export it.")
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)], force=True)
    ChartBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
