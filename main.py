import datetime as dt
import io
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

PREFIX = ";"
DEFAULT_TIMEFRAME = "d"
DEFAULT_STOCK_TIMEFRAME = "i5"
DEFAULT_STOCK_TIMEFRAME_LABEL = "5 min"
DEFAULT_CHART_TYPE = "c"
DEFAULT_THEME = "dark"
DEFAULT_SCALE = "linear"
DEFAULT_SCALE_FACTOR = 2
DEFAULT_WIDTH = 466
DEFAULT_HEIGHT = 219
CHART_RIGHT_MARGIN = 88
MARKET_TIME_ZONE = ZoneInfo("America/New_York")
CHART_IMAGE_MIN_BYTES = 10_000

TIMEFRAMES = {
    "d": ("d", "daily"),
    "daily": ("d", "daily"),
    "w": ("w", "weekly"),
    "weekly": ("w", "weekly"),
    "m": ("m", "monthly"),
    "monthly": ("m", "monthly"),
}
FUTURES_TIMEFRAMES = {
    "1": ("i1", "1 min"), "i1": ("i1", "1 min"), "1min": ("i1", "1 min"),
    "2": ("i2", "2 min"), "i2": ("i2", "2 min"), "2min": ("i2", "2 min"),
    "3": ("i3", "3 min"), "i3": ("i3", "3 min"), "3min": ("i3", "3 min"),
    "5": ("i5", "5 min"), "i5": ("i5", "5 min"), "5min": ("i5", "5 min"),
    "10": ("i10", "10 min"), "i10": ("i10", "10 min"), "10min": ("i10", "10 min"),
    "15": ("i15", "15 min"), "i15": ("i15", "15 min"), "15min": ("i15", "15 min"),
    "30": ("i30", "30 min"), "i30": ("i30", "30 min"), "30min": ("i30", "30 min"),
    "60": ("h", "hourly"), "h": ("h", "hourly"), "1h": ("h", "hourly"), "hourly": ("h", "hourly"),
    "2h": ("h2", "2 hour"), "h2": ("h2", "2 hour"),
    "4h": ("h4", "4 hour"), "h4": ("h4", "4 hour"),
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
INTRADAY_ALIASES = set(FUTURES_TIMEFRAMES)
STOCK_INTRADAY_INTERVALS = {
    "i1": "1m",
    "i2": "2m",
    "i5": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "60m",
    "h4": "4h",
}
STOCK_YAHOO_INTERVALS = STOCK_INTRADAY_INTERVALS | {"d": "1d"}
STOCK_DAILY_RANGES = {
    "": "6mo",
    "m1": "1mo",
    "m3": "3mo",
    "m6": "6mo",
    "ytd": "ytd",
    "y1": "1y",
    "y2": "2y",
    "y5": "5y",
    "max": "max",
}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
STOCK_INTRADAY_UNSUPPORTED_MESSAGE = (
    "Stock intraday supports `1`, `2`, `5`, `15`, `30`, `60`, and `4h` "
    "via Yahoo chart data. Use `d`, `w`, or `m` for Finviz stock charts."
)

# Futures must not use `;f`: that is Ford's stock ticker. Use `;fut ES`.
FUTURES_TICKER_RE = re.compile(r"^[A-Z0-9]{1,8}$")
FUTURES_ALIASES = {"fut", "future", "futures"}


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
    futures: bool = False


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
    is_futures = False
    if parts[0].lower() in FUTURES_ALIASES:
        is_futures = True
        parts = parts[1:]
        if not parts:
            raise ValueError("Usage: `;fut ES`, `;fut CL w line`, or `;futures GC 1y`")
    elif parts[0].lower() in {"chart", "charts"}:
        parts = parts[1:]
        if not parts:
            raise ValueError("Usage: `;AAPL`, `;AAPL w`, or `;AAPL m line light log`")

    ticker = parts[0].upper().replace(".", "-")
    if is_futures:
        if not FUTURES_TICKER_RE.fullmatch(ticker):
            raise ValueError("Futures root looks wrong. Use roots like `;fut ES`, `;fut CL`, or `;fut 6E`.")
    elif not TICKER_RE.fullmatch(ticker):
        raise ValueError("Ticker looks wrong. Use letters/numbers only, like `;AAPL` or `;BRK-B`.")

    timeframe, timeframe_label = TIMEFRAMES[DEFAULT_TIMEFRAME]
    timeframe_explicit = False
    date_range_explicit = False
    chart_type, chart_type_label = CHART_TYPES[DEFAULT_CHART_TYPE]
    theme, theme_label = THEMES[DEFAULT_THEME]
    scale, scale_label = SCALES[DEFAULT_SCALE]
    date_range = date_range_label = ""

    for raw_option in parts[1:]:
        option = raw_option.lower()
        if option in TIMEFRAMES:
            timeframe, timeframe_label = TIMEFRAMES[option]
            timeframe_explicit = True
        elif option in FUTURES_TIMEFRAMES:
            candidate_timeframe, candidate_label = FUTURES_TIMEFRAMES[option]
            if is_futures or candidate_timeframe in STOCK_INTRADAY_INTERVALS:
                timeframe, timeframe_label = candidate_timeframe, candidate_label
                timeframe_explicit = True
            else:
                raise ValueError(STOCK_INTRADAY_UNSUPPORTED_MESSAGE)
        elif option in CHART_TYPES:
            chart_type, chart_type_label = CHART_TYPES[option]
        elif option in THEMES:
            theme, theme_label = THEMES[option]
        elif option in SCALES:
            scale, scale_label = SCALES[option]
        elif option in DATE_RANGES:
            date_range, date_range_label = DATE_RANGES[option]
            date_range_explicit = True
        elif option in INTRADAY_ALIASES:
            raise ValueError(STOCK_INTRADAY_UNSUPPORTED_MESSAGE)
        else:
            raise ValueError(
                f"Unknown chart option `{raw_option}`. Use `d`, `w`, `m`, stock intraday `1`, `2`, `5`, `15`, `30`, `60`, `4h`, `candle`, `line`, `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`, `dark`, `light`, `linear`, `log`, or `percent`. Futures also support `3`, `10`, and `2h`."
            )

    if not is_futures and not timeframe_explicit and not date_range_explicit:
        timeframe, timeframe_label = DEFAULT_STOCK_TIMEFRAME, DEFAULT_STOCK_TIMEFRAME_LABEL

    return ChartRequest(
        ticker, timeframe, timeframe_label, chart_type, chart_type_label,
        theme, theme_label, scale, scale_label, date_range, date_range_label, is_futures,
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
    # Direct renderer schema observed from Finviz's web app.
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
        "instrument": "futures" if request.futures else "stock",
        "timeframe": request.timeframe,
        "premarket": "0",
        "aftermarket": "0",
        "patterns": "0",
        "events": "1",
        "chartEventsVersion": "4",
        "rev": str(int(time.time() * 1000)),
    }
    return "https://finviz.com/api/quote?" + urlencode(params)


def yahoo_stock_chart_url(request: ChartRequest) -> str:
    if request.timeframe not in STOCK_YAHOO_INTERVALS:
        raise ValueError(f"Yahoo chart data does not support `{request.timeframe_label}` stock charts.")
    chart_range = "1d"
    if request.timeframe == "d":
        chart_range = STOCK_DAILY_RANGES.get(request.date_range, "6mo")
    params = {
        "range": chart_range,
        "interval": STOCK_YAHOO_INTERVALS[request.timeframe],
        "includePrePost": "false",
    }
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{request.ticker}?" + urlencode(params)


def is_stock_intraday(request: ChartRequest) -> bool:
    return not request.futures and request.timeframe in STOCK_INTRADAY_INTERVALS


def is_stock_yahoo_chart(request: ChartRequest) -> bool:
    return not request.futures and request.timeframe in STOCK_YAHOO_INTERVALS


def chart_title(request: ChartRequest) -> str:
    parts = [request.ticker]
    if request.date_range_label:
        parts.append(request.date_range_label)
    parts += [request.timeframe_label, request.chart_type_label]
    if request.scale != DEFAULT_SCALE:
        parts.append(request.scale_label)
    if request.theme != DEFAULT_THEME:
        parts.append(request.theme_label)
    return " ".join(parts) + (" futures chart" if request.futures else " chart")


ChartRow = tuple[int, float, float, float, float, float]


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None



def _range_cutoff(last_epoch: int, date_range: str) -> int | None:
    if date_range in {"", "max"}:
        return None
    last = dt.datetime.fromtimestamp(last_epoch, dt.timezone.utc)
    if date_range == "ytd":
        return int(dt.datetime(last.year, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    days = {"m1": 31, "m3": 93, "m6": 186, "y1": 365, "y2": 730, "y5": 1826}.get(date_range)
    return int((last - dt.timedelta(days=days)).timestamp()) if days else None


def _quote_rows(quote: dict[str, Any], request: ChartRequest) -> list[ChartRow]:
    dates = quote.get("date") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    rows: list[ChartRow] = []
    for i in range(min(map(len, (dates, opens, highs, lows, closes)))):
        o, h, l, c = (_safe_float(values[i]) for values in (opens, highs, lows, closes))
        if None in (o, h, l, c):
            continue
        v = _safe_float(volumes[i]) if i < len(volumes) else 0.0
        rows.append((int(dates[i]), o or 0.0, h or 0.0, l or 0.0, c or 0.0, v or 0.0))
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


def _visible_indexes(rows: list[ChartRow], request: ChartRequest) -> list[int]:
    cutoff = _range_cutoff(rows[-1][0], request.date_range)
    if cutoff is not None:
        indexes = [i for i, row in enumerate(rows) if row[0] >= cutoff]
    elif request.date_range == "max":
        indexes = list(range(len(rows)))
    else:
        count = 180 if request.timeframe.startswith(("i", "h")) else {"d": 90, "w": 104, "m": 120}.get(request.timeframe, 90)
        indexes = list(range(max(0, len(rows) - count), len(rows)))
    if len(indexes) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")
    return indexes


def _sma_values(rows: list[ChartRow], period: int) -> list[float | None]:
    values: list[float | None] = []
    total = 0.0
    for i, row in enumerate(rows):
        total += row[4]
        if i >= period:
            total -= rows[i - period][4]
        values.append(total / period if i >= period - 1 else None)
    return values


def _axis_label(value: float, request: ChartRequest) -> str:
    if request.scale == "percentage":
        return f"{value:.0f}%"
    if request.scale == "logarithmic":
        value = math.exp(value)
    return _fmt(value)


def _date_label(epoch: int, intraday: bool, span: int) -> str:
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    if intraday:
        local = stamp.astimezone(MARKET_TIME_ZONE)
        return local.strftime("%H:%M") if span <= 3 * 86400 else local.strftime("%m/%d")
    return stamp.strftime("%b") if span < 400 * 86400 else stamp.strftime("%y")


def render_price_chart_png(quote: dict[str, Any], request: ChartRequest) -> bytes:
    # Pillow keeps text crisp without pulling in a full charting framework.
    from PIL import Image, ImageDraw, ImageFont

    width, height = DEFAULT_WIDTH * DEFAULT_SCALE_FACTOR, DEFAULT_HEIGHT * DEFAULT_SCALE_FACTOR
    dark = request.theme == "dark"
    bg = (31, 34, 46) if dark else (250, 250, 250)
    grid = (50, 55, 70) if dark else (214, 218, 226)
    text = (160, 170, 190) if dark else (100, 108, 122)
    strong = (176, 186, 206) if dark else (50, 55, 65)
    up, down = (25, 200, 105), (255, 82, 82)
    line_color = (55, 160, 245) if dark else (25, 105, 210)
    vol_up, vol_down = (25, 120, 75), (128, 58, 68)
    sma_colors = {20: (132, 42, 126), 50: (235, 126, 35), 200: (128, 106, 32)}

    def font(size: int, bold: bool = False) -> Any:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for path in (f"/usr/share/fonts/truetype/dejavu/{name}", name):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    title_font = font(38, True)
    header_font = font(18)
    label_font = font(17, True)
    axis_font = font(18)
    small_font = font(14)
    badge_font = font(19, True)
    sma_font = font(16, True)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    left, right, top, bottom = 60, CHART_RIGHT_MARGIN, 34, 30
    volume_h, gap = 68, 8
    vol_top, vol_bottom = height - bottom - volume_h, height - bottom
    price_top, price_bottom = top, vol_top - gap
    plot_w = width - left - right
    all_rows = _quote_rows(quote, request)
    indexes = _visible_indexes(all_rows, request)
    rows = [all_rows[i] for i in indexes]
    base = rows[0][4]
    intraday = request.timeframe.startswith(("i", "h"))
    span = rows[-1][0] - rows[0][0]

    def scaled(value: float) -> float:
        if request.scale == "percentage":
            return ((value / base) - 1.0) * 100.0
        if request.scale == "logarithmic":
            if value <= 0:
                raise NoChartData(f"Finviz has non-positive values for `{request.ticker}`, so log scale won't work.")
            return math.log(value)
        return value

    smas = {period: _sma_values(all_rows, period) for period in (20, 50, 200)}
    candles = [(i, d, scaled(o), scaled(h), scaled(l), scaled(c), v) for i, (d, o, h, l, c, v) in zip(indexes, rows)]
    scale_values = [value for _, _, o, h, l, c, _ in candles for value in (o, h, l, c)]
    for values in smas.values():
        for i in indexes:
            if values[i] is not None:
                scale_values.append(scaled(values[i] or 0.0))
    low, high = min(scale_values), max(scale_values)
    if high == low:
        high += 1
        low -= 1
    pad = (high - low) * 0.055
    low, high = low - pad, high + pad
    vol_max = max((row[5] for row in rows), default=1) or 1

    def x_at(i: int) -> int:
        return left + round(i * (plot_w - 1) / max(len(candles) - 1, 1))

    def y_at(value: float) -> int:
        return price_bottom - round((value - low) * (price_bottom - price_top) / (high - low))

    def dashed(x1: int, y1: int, x2: int, y2: int) -> None:
        if y1 == y2:
            x = x1
            while x < x2:
                draw.line((x, y1, min(x + 8, x2), y2), fill=grid, width=1)
                x += 14
        else:
            y = y1
            while y < y2:
                draw.line((x1, y, x2, min(y + 8, y2)), fill=grid, width=1)
                y += 14

    for step in range(5):
        value = high - step * (high - low) / 4
        y = y_at(value)
        dashed(left, y, width - right, y)
        draw.text((width - right + 8, y - 11), _axis_label(value, request), fill=text, font=axis_font)
    for step in range(6):
        x = left + round(step * plot_w / 5)
        dashed(x, price_top, x, vol_bottom)
        idx = round(step * (len(rows) - 1) / 5)
        label = _date_label(rows[idx][0], intraday, span)
        label_w = draw.textbbox((0, 0), label, font=axis_font)[2]
        draw.text((max(0, min(width - right - label_w, x - label_w // 2)), vol_bottom + 6), label, fill=text, font=axis_font)
    draw.line((left, price_bottom, width - right, price_bottom), fill=grid, width=1)

    candle_w = max(2, min(8, int(plot_w / max(len(candles), 1) * 0.58)))
    close_points: list[tuple[int, int]] = []
    for pos, (_, _, o, h, l, c, v) in enumerate(candles):
        x = x_at(pos)
        color = up if c >= o else down
        vh = round((v / vol_max) * (vol_bottom - vol_top))
        draw.rectangle((x - candle_w // 2, vol_bottom - vh, x + candle_w // 2, vol_bottom), fill=vol_up if c >= o else vol_down)
        if request.chart_type == "l":
            close_points.append((x, y_at(c)))
            continue
        yo, yh, yl, yc = y_at(o), y_at(h), y_at(l), y_at(c)
        draw.line((x, yh, x, yl), fill=color, width=1)
        draw.rectangle((x - candle_w // 2, min(yo, yc), x + candle_w // 2, max(yo, yc)), fill=color)
    if close_points:
        draw.line(close_points, fill=line_color, width=2, joint="curve")

    for period, values in smas.items():
        points = [(x_at(pos), y_at(scaled(values[i] or 0.0))) for pos, i in enumerate(indexes) if values[i] is not None]
        if len(points) > 1:
            draw.line(points, fill=sma_colors[period], width=2, joint="curve")

    last_idx = indexes[-1]
    last = all_rows[last_idx]
    prev = _safe_float(quote.get("prevClose")) or all_rows[max(0, last_idx - 1)][4]
    change = (_safe_float(quote.get("perfDayUsd")) if quote.get("perfDayUsd") is not None else last[4] - prev) or 0.0
    pct = (_safe_float(quote.get("perfDayPct")) if quote.get("perfDayPct") is not None else (change / prev * 100 if prev else 0.0)) or 0.0
    change_color = up if change >= 0 else down
    date = dt.datetime.fromtimestamp(last[0], dt.timezone.utc).strftime("%b %d")
    change_label = f"{change:+.2f} ({pct:+.2f}%)"

    draw.text((8, 2), request.ticker, fill=strong, font=title_font)
    title_w = draw.textbbox((8, 2), request.ticker, font=title_font)[2]
    draw.text((title_w + 12, 10), date, fill=text, font=header_font)
    change_w = draw.textbbox((0, 0), change_label, font=label_font)[2]
    draw.text((width - right - change_w - 8, 8), change_label, fill=change_color, font=label_font)

    for row, period in enumerate((20, 50, 200)):
        value = smas[period][last_idx]
        if value is not None:
            draw.text((8, 46 + row * 22), f"SMA {period} · {_fmt(value)}", fill=sma_colors[period], font=sma_font)

    label = request.timeframe_label.upper()
    label_img = Image.new("RGBA", (180, 30), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label_img)
    label_draw.text((0, 0), label, fill=text + (255,), font=label_font)
    label_img = label_img.crop(label_img.getbbox() or (0, 0, 1, 1)).rotate(90, expand=True)
    image.paste(label_img, (20, price_top + (price_bottom - price_top - label_img.height) // 2), label_img)

    last_scaled = scaled(last[4])
    badge_text = _axis_label(last_scaled, request)
    badge_w = draw.textbbox((0, 0), badge_text, font=badge_font)[2] + 12
    bx, by = width - badge_w - 6, max(price_top, min(price_bottom - 27, y_at(last_scaled) - 14))
    draw.rounded_rectangle((bx, by, bx + badge_w, by + 27), radius=2, fill=(245, 211, 65))
    draw.text((bx + 6, by + 2), badge_text, fill=(22, 24, 30), font=badge_font)
    draw.text((8, vol_top + 2), _fmt_volume(vol_max), fill=text, font=axis_font)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _fmt(value: Any, suffix: str = "") -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}{suffix}" if abs(number) < 1000 else f"{number:,.0f}{suffix}"


def _fmt_volume(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    for suffix, scale in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= scale:
            return f"{number / scale:.1f}{suffix}"
    return f"{number:,.0f}"


def _quote_time_label(quote: dict[str, Any]) -> str | None:
    timestamp = _safe_float(quote.get("lastTime"))
    if timestamp is None:
        dates = quote.get("date") or []
        timestamp = _safe_float(dates[-1]) if dates else None
    if timestamp is None:
        return None
    stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    return stamp.strftime("%I:%M %p ET").lstrip("0")


def quote_description(quote: dict[str, Any]) -> str:
    name = quote.get("name") or quote.get("ticker") or "quote"
    parts = [
        str(name),
        f"last `{_fmt(quote.get('lastClose'))}`",
        f"change `{_fmt(quote.get('perfDayUsd'))}` (`{_fmt(quote.get('perfDayPct'), '%')}`)",
    ]
    time_label = _quote_time_label(quote)
    if time_label:
        parts.append(f"updated `{time_label}`")
    return " · ".join(parts)


def _self_test() -> None:
    assert parse_chart_command("hello") is None
    assert parse_chart_command(";") is None
    assert parse_chart_command(";help") is None
    assert parse_chart_command(";aapl") == ChartRequest("AAPL", "i5", "5 min")
    assert parse_chart_command(";aapl d") == ChartRequest("AAPL", "d", "daily")
    assert parse_chart_command(";brk.b w line") == ChartRequest("BRK-B", "w", "weekly", "l", "line")
    assert parse_chart_command(";aapl m line light log") == ChartRequest(
        "AAPL", "m", "monthly", "l", "line", "light", "light", "logarithmic", "log"
    )
    ranged = parse_chart_command(";aapl 1y")
    assert ranged is not None
    assert ranged.timeframe == "d" and ranged.date_range == "y1"
    url = finviz_chart_url(ChartRequest("AAPL"))
    assert url.startswith("https://charts2-node.finviz.com/chart?")
    assert "tf=d" in url and "ct=candle_stick" in url and "sf=2" in url and "tm=d" in url
    ranged_url = finviz_chart_url(ranged)
    assert "r=y1" in ranged_url
    assert "chart.ashx" in legacy_finviz_chart_url(ChartRequest("AAPL"))
    assert "updated `10:50 AM ET`" in quote_description({"ticker": "AMD", "lastClose": 548.54, "lastTime": 1781535058})
    assert parse_chart_command(";amd 1") == ChartRequest("AMD", "i1", "1 min")
    assert parse_chart_command(";amd 4h") == ChartRequest("AMD", "h4", "4 hour")
    assert "range=1y" in yahoo_stock_chart_url(ranged) and "interval=1d" in yahoo_stock_chart_url(ranged)
    assert "interval=1m" in yahoo_stock_chart_url(ChartRequest("AMD", "i1", "1 min"))
    assert "interval=5m" in yahoo_stock_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert is_stock_intraday(ChartRequest("AMD", "i1", "1 min"))
    assert is_stock_yahoo_chart(ChartRequest("AMD", "d", "daily"))
    assert _date_label(1781536808, True, 3600) == "11:20"
    assert 80 <= CHART_RIGHT_MARGIN <= 96
    try:
        parse_chart_command(";spy 10")
    except ValueError as error:
        assert "Stock intraday supports" in str(error)
        assert "Yahoo chart data" in str(error)
    else:
        raise AssertionError("unsupported stock intraday alias should be rejected")

    # Futures: use `;fut`, not `;f` — `;f` is Ford.
    assert parse_chart_command(";f") == ChartRequest("F", "i5", "5 min")
    assert parse_chart_command(";fut es") == ChartRequest("ES", futures=True)
    assert parse_chart_command(";fut cl w line") == ChartRequest(
        "CL", "w", "weekly", "l", "line", futures=True
    )
    assert parse_chart_command(";fut es 15") == ChartRequest("ES", "i15", "15 min", futures=True)
    fut_req = parse_chart_command(";futures gc 1y")
    assert fut_req is not None
    assert fut_req.futures and fut_req.ticker == "GC" and fut_req.date_range == "y1"
    assert chart_title(ChartRequest("ES", futures=True)).endswith("futures chart")
    assert "instrument=futures" in finviz_quote_api_url(ChartRequest("ES", futures=True))
    assert parse_chart_command(";fut 6e") == ChartRequest("6E", futures=True)
    sample_png = render_price_chart_png({
        "ticker": "ES",
        "name": "S&P 500",
        "date": [1, 2, 3],
        "open": [10, 11, 10],
        "high": [12, 12, 11],
        "low": [9, 10, 9],
        "close": [11, 10, 10.5],
        "volume": [100, 150, 120],
    }, ChartRequest("ES", futures=True))
    assert sample_png.startswith(b"\x89PNG") and len(sample_png) > 1000
    aapl_req = parse_chart_command(";aapl")
    assert aapl_req is not None and not aapl_req.futures and aapl_req.timeframe == "i5"


if __name__ == "__main__" and "--self-test" in sys.argv:
    _self_test()
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
    if request.timeframe == "d" and len(valid_closes) > 1:
        prev = valid_closes[-2]
    else:
        prev = _safe_float(meta.get("chartPreviousClose")) or _safe_float(meta.get("previousClose"))
        if prev is None and len(valid_closes) > 1:
            prev = valid_closes[-2]
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
    direct_url = finviz_chart_url(request, cache_bust=True)
    legacy_url = legacy_finviz_chart_url(request)
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
