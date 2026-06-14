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
DEFAULT_THEME = "dark"
DEFAULT_SCALE = "linear"
DEFAULT_SCALE_FACTOR = 2
DEFAULT_WIDTH = 466
DEFAULT_HEIGHT = 219
CHART_IMAGE_MIN_BYTES = 10_000

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
DIRECT_CHART_TYPES = {
    "c": "candle_stick",
    "l": "line_chart",
}
THEMES = {
    "dark": ("dark", "dark"),
    "light": ("light", "light"),
}
SCALES = {
    "linear": ("linear", "linear"),
    "lin": ("linear", "linear"),
    "log": ("logarithmic", "log"),
    "logarithmic": ("logarithmic", "log"),
    "percent": ("percentage", "percent"),
    "percentage": ("percentage", "percent"),
    "pct": ("percentage", "percent"),
}
DATE_RANGES = {
    "1m": ("m1", "1 month"),
    "m1": ("m1", "1 month"),
    "3m": ("m3", "3 months"),
    "m3": ("m3", "3 months"),
    "6m": ("m6", "6 months"),
    "m6": ("m6", "6 months"),
    "ytd": ("ytd", "YTD"),
    "1y": ("y1", "1 year"),
    "y1": ("y1", "1 year"),
    "2y": ("y2", "2 years"),
    "y2": ("y2", "2 years"),
    "5y": ("y5", "5 years"),
    "y5": ("y5", "5 years"),
    "max": ("max", "max"),
    "all": ("max", "max"),
}
INTRADAY_ALIASES = {"1", "2", "3", "5", "10", "15", "30", "60", "h", "hourly"}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


@dataclass(frozen=True)
class ChartRequest:
    ticker: str
    timeframe: str = DEFAULT_TIMEFRAME
    timeframe_label: str = "daily"
    chart_type: str = DEFAULT_CHART_TYPE
    chart_type_label: str = "candle"
    theme: str = DEFAULT_THEME
    theme_label: str = "dark"
    scale: str = DEFAULT_SCALE
    scale_label: str = "linear"
    date_range: str = ""
    date_range_label: str = ""


class NoChartData(ValueError):
    pass


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
            raise ValueError("Usage: `;AAPL`, `;AAPL w`, or `;AAPL m line light log`")

    ticker = parts[0].upper().replace(".", "-")
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError("Ticker looks wrong. Use letters/numbers only, like `;AAPL` or `;BRK-B`.")

    timeframe, timeframe_label = TIMEFRAMES[DEFAULT_TIMEFRAME]
    chart_type, chart_type_label = CHART_TYPES[DEFAULT_CHART_TYPE]
    theme, theme_label = THEMES[DEFAULT_THEME]
    scale, scale_label = SCALES[DEFAULT_SCALE]
    date_range = date_range_label = ""

    for raw_option in parts[1:]:
        option = raw_option.lower()
        if option in TIMEFRAMES:
            timeframe, timeframe_label = TIMEFRAMES[option]
        elif option in CHART_TYPES:
            chart_type, chart_type_label = CHART_TYPES[option]
        elif option in THEMES:
            theme, theme_label = THEMES[option]
        elif option in SCALES:
            scale, scale_label = SCALES[option]
        elif option in DATE_RANGES:
            date_range, date_range_label = DATE_RANGES[option]
        elif option in INTRADAY_ALIASES:
            raise ValueError("Finviz free charts here support `d`, `w`, and `m` only. Intraday is silently downgraded by Finviz.")
        else:
            raise ValueError(
                f"Unknown chart option `{raw_option}`. Use `d`, `w`, `m`, `candle`, `line`, `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`, `dark`, `light`, `linear`, `log`, or `percent`."
            )

    return ChartRequest(
        ticker, timeframe, timeframe_label, chart_type, chart_type_label,
        theme, theme_label, scale, scale_label, date_range, date_range_label,
    )


def legacy_finviz_chart_url(request: ChartRequest, cache_bust: bool = False) -> str:
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


def finviz_chart_url(request: ChartRequest, cache_bust: bool = False) -> str:
    # Direct renderer schema observed in /home/fever/Dev/api-re-cases/finviz.com.
    params = [
        ("w", str(DEFAULT_WIDTH)),
        ("h", str(DEFAULT_HEIGHT)),
        ("bw", "2"),
        ("bm", "1"),
        ("bb", "1"),
        ("t", request.ticker),
        ("tf", request.timeframe),
        ("s", request.scale),
        ("pm", "0"),
        ("am", "0"),
        ("ct", DIRECT_CHART_TYPES[request.chart_type]),
        ("o[0][ot]", "sma"),
        ("o[0][op]", "20"),
        ("o[0][oc]", "DC32B363"),
        ("o[1][ot]", "sma"),
        ("o[1][op]", "50"),
        ("o[1][oc]", "FF8F33C6"),
        ("o[2][ot]", "sma"),
        ("o[2][op]", "200"),
        ("o[2][oc]", "DCB3326D"),
        ("o[3][ot]", "patterns"),
        ("o[3][op]", ""),
        ("o[3][oc]", "000"),
        ("sf", str(DEFAULT_SCALE_FACTOR)),
        ("rev", str(int(time.time()) if cache_bust else int(time.time() // 20))),
    ]
    if request.date_range:
        params.append(("r", request.date_range))
    if request.theme == "dark":
        params.append(("tm", "d"))
    return "https://charts2-node.finviz.com/chart?" + urlencode(params)


def finviz_quote_api_url(request: ChartRequest) -> str:
    params = {
        "ticker": request.ticker,
        "instrument": "stock",
        "timeframe": request.timeframe,
        "premarket": "0",
        "aftermarket": "0",
        "patterns": "0",
        "events": "1",
        "chartEventsVersion": "4",
        "rev": str(int(time.time() * 1000)),
    }
    return "https://finviz.com/api/quote?" + urlencode(params)


def chart_title(request: ChartRequest) -> str:
    parts = [request.ticker]
    if request.date_range_label:
        parts.append(request.date_range_label)
    parts += [request.timeframe_label, request.chart_type_label]
    if request.scale != DEFAULT_SCALE:
        parts.append(request.scale_label)
    if request.theme != DEFAULT_THEME:
        parts.append(request.theme_label)
    return " ".join(parts) + " chart"


def _self_test() -> None:
    assert parse_chart_command("hello") is None
    assert parse_chart_command(";") is None
    assert parse_chart_command(";help") is None
    assert parse_chart_command(";aapl") == ChartRequest("AAPL")
    assert parse_chart_command(";brk.b w line") == ChartRequest("BRK-B", "w", "weekly", "l", "line")
    assert parse_chart_command(";aapl m line light log") == ChartRequest(
        "AAPL", "m", "monthly", "l", "line", "light", "light", "logarithmic", "log"
    )
    ranged = parse_chart_command(";aapl 1y")
    assert ranged is not None
    assert ranged.date_range == "y1"
    url = finviz_chart_url(ChartRequest("AAPL"))
    assert url.startswith("https://charts2-node.finviz.com/chart?")
    assert "tf=d" in url and "ct=candle_stick" in url and "sf=2" in url and "tm=d" in url
    ranged_url = finviz_chart_url(ranged)
    assert "r=y1" in ranged_url
    assert "chart.ashx" in legacy_finviz_chart_url(ChartRequest("AAPL"))
    try:
        parse_chart_command(";spy 5")
    except ValueError as error:
        assert "silently downgraded" in str(error)
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

**Syntax**
`;TICKER [timeframe] [type] [range] [size] [theme] [scale]`

**Examples**
`;AAPL` → daily candle chart
`;QQQ w line` → weekly line chart
`;SERV m` → monthly candle chart
`;LULU 1y` → 1-year chart
`;AAPL light log` → light theme, log scale
`;SPY 5y w percent` → 5-year weekly percent chart

**Options**
Timeframes: `d`, `w`, `m`
Types: `candle`, `line`
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`
Themes: `dark`, `light`
Scales: `linear`, `log`, `percent`

Options can be in any order after the ticker.
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


async def ensure_chart_data(session: aiohttp.ClientSession, request: ChartRequest) -> None:
    async with session.get(finviz_quote_api_url(request), headers={"Accept": "application/json"}) as response:
        if response.status == 404:
            raise NoChartData(f"Finviz has no chart data for `{request.ticker}`.")
        if response.status != 200:
            raise RuntimeError(f"Finviz quote check returned HTTP {response.status}")
        await response.read()


async def fetch_chart_image(session: aiohttp.ClientSession, request: ChartRequest, url: str) -> bytes:
    async with session.get(url, headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}) as response:
        if response.status != 200:
            raise RuntimeError(f"Finviz returned HTTP {response.status}")
        image = await response.read()
    if not image.startswith((b"\x89PNG", b"\xff\xd8", b"GIF")):
        raise RuntimeError("Finviz did not return an image")
    if len(image) < CHART_IMAGE_MIN_BYTES:
        # ponytail: size floor catches Finviz's valid-PNG empty chart for bad tickers.
        raise NoChartData(f"Finviz returned an empty chart for `{request.ticker}`.")
    return image


async def send_chart(channel: discord.abc.Messageable, request: ChartRequest) -> None:
    direct_url = finviz_chart_url(request)
    legacy_url = legacy_finviz_chart_url(request)
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://finviz.com/quote.ashx?t={request.ticker}",
        "Cache-Control": "no-cache",
        "Cookie": f"chartsTheme={request.theme}",
    }

    async with channel.typing():
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, headers=headers) as session:
                try:
                    await ensure_chart_data(session, request)
                except NoChartData:
                    raise
                except Exception:
                    pass  # precheck is best-effort; the image fetch still proves the chart.

                try:
                    image = await fetch_chart_image(session, request, direct_url)
                except NoChartData:
                    raise
                except Exception:
                    image = await fetch_chart_image(session, request, legacy_url)
        except NoChartData as error:
            await channel.send(str(error))
            return
        except Exception as error:
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
