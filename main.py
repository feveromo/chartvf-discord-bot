import io
import os
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlencode

PREFIX = ";"
DEFAULT_TIMEFRAME = "d"
DEFAULT_CHART_TYPE = "c"

TIMEFRAMES = {
    "d": ("d", "daily"),
    "daily": ("d", "daily"),
    "w": ("w", "weekly"),
    "weekly": ("w", "weekly"),
    "m": ("m", "monthly"),
    "monthly": ("m", "monthly"),
}
CHART_TYPES = {
    "c": ("c", "candle"),
    "candle": ("c", "candle"),
    "candles": ("c", "candle"),
    "l": ("l", "line"),
    "line": ("l", "line"),
}
INTRADAY_ALIASES = {"1", "3", "5", "15", "30", "60", "h", "hourly"}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


@dataclass(frozen=True)
class ChartRequest:
    ticker: str
    timeframe: str = DEFAULT_TIMEFRAME
    timeframe_label: str = "daily"
    chart_type: str = DEFAULT_CHART_TYPE
    chart_type_label: str = "candle"


def parse_chart_command(content: str) -> ChartRequest | None:
    if not content.startswith(PREFIX):
        return None

    parts = content[len(PREFIX):].strip().split()
    if not parts:
        return None

    if parts[0].lower() in {"help", "h"}:
        return None
    if parts[0].lower() in {"chart", "charts"}:
        parts = parts[1:]
        if not parts:
            raise ValueError("Usage: `;AAPL`, `;AAPL w`, or `;AAPL m line`")

    ticker = parts[0].upper().replace(".", "-")
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError("Ticker looks wrong. Use letters/numbers only, like `;AAPL` or `;BRK-B`.")

    timeframe, timeframe_label = TIMEFRAMES[DEFAULT_TIMEFRAME]
    chart_type, chart_type_label = CHART_TYPES[DEFAULT_CHART_TYPE]

    for raw_option in parts[1:]:
        option = raw_option.lower()
        if option in TIMEFRAMES:
            timeframe, timeframe_label = TIMEFRAMES[option]
        elif option in CHART_TYPES:
            chart_type, chart_type_label = CHART_TYPES[option]
        elif option in INTRADAY_ALIASES:
            raise ValueError("Finviz free charts here support `d`, `w`, and `m` only. Intraday is Elite-gated.")
        else:
            raise ValueError(f"Unknown chart option `{raw_option}`. Use `d`, `w`, `m`, `candle`, or `line`.")

    return ChartRequest(ticker, timeframe, timeframe_label, chart_type, chart_type_label)


def finviz_chart_url(request: ChartRequest, cache_bust: bool = False) -> str:
    params = {
        "t": request.ticker,
        "ty": request.chart_type,
        "ta": "1",
        "p": request.timeframe,
        "s": "l",
    }
    if cache_bust:
        params["v"] = str(int(time.time()))
    return "https://finviz.com/chart.ashx?" + urlencode(params)


def _self_test() -> None:
    assert parse_chart_command("hello") is None
    assert parse_chart_command(";") is None
    assert parse_chart_command(";help") is None
    assert parse_chart_command(";aapl") == ChartRequest("AAPL")
    assert parse_chart_command(";brk.b w line") == ChartRequest("BRK-B", "w", "weekly", "l", "line")
    try:
        parse_chart_command(";spy 5")
    except ValueError as error:
        assert "Intraday" in str(error)
    else:
        raise AssertionError("intraday alias should be rejected")


if __name__ == "__main__" and "--self-test" in sys.argv:
    _self_test()
    print("self-test ok")
    raise SystemExit(0)

import aiohttp
import discord
from dotenv import load_dotenv

HELP_TEXT = """**Finviz chart bot**
`;AAPL` → daily candle chart
`;AAPL w` → weekly chart
`;AAPL m line` → monthly line chart

Timeframes: `d`, `w`, `m`
Types: `candle`, `line`
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


async def send_chart(channel: discord.abc.Messageable, request: ChartRequest) -> None:
    url = finviz_chart_url(request)
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://finviz.com/quote.ashx?t={request.ticker}",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }

    async with channel.typing():
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Finviz returned HTTP {response.status}")
                    image = await response.read()
                    if not image.startswith((b"\x89PNG", b"\xff\xd8", b"GIF")):
                        raise RuntimeError("Finviz did not return an image")
        except Exception as error:
            embed = discord.Embed(
                title=f"{request.ticker} {request.timeframe_label} {request.chart_type_label} chart",
                color=0x2ECC71,
            )
            embed.set_image(url=finviz_chart_url(request, cache_bust=True))
            await channel.send(f"Upload failed ({error}). Trying the direct Finviz embed:", embed=embed)
            return

    filename = f"{request.ticker}_{request.timeframe}_{int(time.time())}.png"
    file = discord.File(io.BytesIO(image), filename=filename)
    embed = discord.Embed(
        title=f"{request.ticker} {request.timeframe_label} {request.chart_type_label} chart",
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
