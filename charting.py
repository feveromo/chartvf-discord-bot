import datetime as dt
import io
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

PREFIX = ";"
DEFAULT_TIMEFRAME = "d"
DEFAULT_STOCK_TIMEFRAME = "i5"
DEFAULT_STOCK_TIMEFRAME_LABEL = "5 min"
DEFAULT_CHART_TYPE = "c"
DEFAULT_THEME = "light"
DEFAULT_SCALE = "linear"
DEFAULT_SCALE_FACTOR = 2
DEFAULT_WIDTH = 466
DEFAULT_HEIGHT = 219
CHART_RIGHT_MARGIN = 80
MARKET_TIME_ZONE = ZoneInfo("America/New_York")
STOCK_DAILY_VISIBLE_BARS = 240
STOCK_WEEKLY_VISIBLE_BARS = 240
STOCK_INTRADAY_VISIBLE_BARS = 180
STOCK_MONTHLY_VISIBLE_BARS = 240
SMA_PERIODS = (20, 50, 200)
SMA_COLORS = {20: (142, 43, 132), 50: (238, 126, 35), 200: (139, 111, 43)}
FUTURES_INTRADAY_VISIBLE_BARS = 140
STOCK_5M_START = dt.time(4, 0)
STOCK_5M_END = dt.time(20, 0)
REGULAR_SESSION_START = dt.time(9, 30)
REGULAR_SESSION_END = dt.time(16, 0)
EXTENDED_WICK_PCT_LIMIT = 0.004
EXTENDED_WICK_RANGE_MULTIPLE = 8.0
SPARSE_CHART_MIN_BARS = 24
INTRADAY_VOLUME_SCALE_PERCENTILE = 0.90

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
STOCK_INTRADAY_INTERVALS = {
    "i1": "1m",
    "i2": "2m",
    "i5": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "60m",
    "h4": "4h",
}
YAHOO_TIMEFRAME_INTERVALS = {
    "d": "1d",
    "w": "1wk",
    "m": "1mo",
    "i1": "1m",
    "i2": "2m",
    "i3": "1m",
    "i5": "5m",
    "i10": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "60m",
    "h2": "60m",
    "h4": "4h",
}
YAHOO_INTRADAY_RANGES = {
    "i1": "5d",
    "i2": "5d",
    "i3": "5d",
    "i5": "5d",
    "i10": "5d",
    "i15": "5d",
    "i30": "1mo",
    "h": "1mo",
    "h2": "1mo",
    "h4": "6mo",
}
DAILY_SMA_FETCH_RANGES = {
    "": "2y",
    "m1": "1y",
    "m3": "1y",
    "m6": "2y",
    "ytd": "2y",
    "y1": "2y",
    "y2": "5y",
    "y5": "10y",
    "max": "max",
}
WEEKLY_SMA_FETCH_RANGES = {
    "": "10y",
    "m1": "5y",
    "m3": "5y",
    "m6": "5y",
    "ytd": "5y",
    "y1": "5y",
    "y2": "10y",
    "y5": "10y",
    "max": "max",
}
YAHOO_AGGREGATE_SECONDS = {
    "i3": 3 * 60,
    "i10": 10 * 60,
    "h2": 2 * 60 * 60,
}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
YAHOO_SYMBOL_ALIASES = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJX": "^DJI",
    "DJI": "^DJI",
    "DJIA": "^DJI",
    "RUT": "^RUT",
    "RUI": "^RUI",
    "VIX": "^VIX",
    "IXIC": "^IXIC",
    "OEX": "^OEX",
}
STOCK_INTRADAY_UNSUPPORTED_MESSAGE = (
    "Stock intraday supports `1`, `2`, `5`, `15`, `30`, `60`, and `4h` "
    "via market chart data. Use `d`, `w`, or `m` for higher timeframes."
)

# Futures must not use `;f`: that is Ford's stock ticker. Use `;fut ES`.
FUTURES_TICKER_RE = re.compile(r"^[A-Z0-9]{1,8}$")
FUTURES_ALIASES = {"fut", "future", "futures"}
FUTURES_DISPLAY_NAMES = {
    "ES": "E-mini S&P 500",
    "MES": "Micro E-mini S&P 500",
    "NQ": "E-mini Nasdaq-100",
    "MNQ": "Micro E-mini Nasdaq-100",
    "YM": "E-mini Dow",
    "MYM": "Micro E-mini Dow",
    "RTY": "E-mini Russell 2000",
    "M2K": "Micro E-mini Russell 2000",
    "CL": "Crude oil futures",
    "GC": "Gold futures",
    "6E": "Euro FX futures",
}


@dataclass(frozen=True)
class ChartRequest:
    ticker: str
    timeframe: str = DEFAULT_TIMEFRAME
    timeframe_label: str = "daily"
    chart_type: str = DEFAULT_CHART_TYPE
    chart_type_label: str = "candle"
    theme: str = DEFAULT_THEME
    theme_label: str = "light"
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
            raise ValueError("Usage: `;AAPL`, `;AAPL w`, or `;AAPL m line dark log`")

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


def yahoo_chart_symbol(request: ChartRequest) -> str:
    if request.futures:
        return f"{request.ticker}=F"
    return YAHOO_SYMBOL_ALIASES.get(request.ticker, request.ticker)


def _yahoo_chart_range(request: ChartRequest) -> str:
    if request.timeframe in YAHOO_INTRADAY_RANGES:
        return YAHOO_INTRADAY_RANGES[request.timeframe]
    if request.timeframe == "d":
        return DAILY_SMA_FETCH_RANGES.get(request.date_range, "2y")
    if request.timeframe == "w":
        return WEEKLY_SMA_FETCH_RANGES.get(request.date_range, "10y")
    if request.timeframe == "m":
        return "max"
    raise ValueError(f"Chart data does not support `{request.timeframe_label}` charts.")


def yahoo_chart_url(request: ChartRequest) -> str:
    interval = YAHOO_TIMEFRAME_INTERVALS.get(request.timeframe)
    if interval is None:
        raise ValueError(f"Chart data does not support `{request.timeframe_label}` charts.")

    params = {
        "interval": interval,
        "includePrePost": "true" if not request.futures and request.timeframe == "i5" else "false",
        "events": "div,splits",
    }
    if request.timeframe == "m":
        params["period1"] = "0"
        params["period2"] = str(int(dt.datetime.now(dt.timezone.utc).timestamp()))
    else:
        params["range"] = _yahoo_chart_range(request)
    symbol = quote(yahoo_chart_symbol(request), safe="=^")
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?" + urlencode(params)


def chart_title(request: ChartRequest) -> str:
    parts = [request.ticker]
    if request.date_range_label:
        parts.append(request.date_range_label)
    chart_type = "candles" if request.chart_type == "c" else request.chart_type_label
    parts.append(f"{request.timeframe_label} {chart_type}")
    if request.scale != DEFAULT_SCALE:
        parts.append(request.scale_label)
    if request.theme != DEFAULT_THEME:
        parts.append(request.theme_label)
    if request.futures:
        parts.append("futures")
    return " · ".join(parts)


ChartRow = tuple[int, float, float, float, float, float]
SessionKey = tuple[str, object]


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


def _collapse_monthly_rows(rows: list[ChartRow]) -> list[ChartRow]:
    collapsed: list[ChartRow] = []
    last_month: tuple[int, int] | None = None
    for epoch, open_, high, low, close, volume in rows:
        stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
        month = (stamp.year, stamp.month)
        if month == last_month:
            _, prev_open, prev_high, prev_low, _, prev_volume = collapsed[-1]
            collapsed[-1] = (
                epoch,
                prev_open,
                max(prev_high, high),
                min(prev_low, low),
                close,
                max(prev_volume, volume),
            )
            continue
        collapsed.append((epoch, open_, high, low, close, volume))
        last_month = month
    return collapsed


def _source_interval_seconds(request: ChartRequest) -> int | None:
    interval = YAHOO_TIMEFRAME_INTERVALS.get(request.timeframe)
    if interval and interval.endswith("m") and interval[:-1].isdigit():
        return int(interval[:-1]) * 60
    if interval and interval.endswith("h") and interval[:-1].isdigit():
        return int(interval[:-1]) * 60 * 60
    return None


def _drop_live_quote_row(rows: list[ChartRow], request: ChartRequest) -> list[ChartRow]:
    interval = _source_interval_seconds(request)
    if interval is None or len(rows) < 2:
        return rows
    epoch, open_, high, low, close, volume = rows[-1]
    previous_epoch = rows[-2][0]
    # ponytail: Yahoo appends a live quote row; it is not a finished candle.
    if (
        volume == 0
        and open_ == high == low == close
        and (
            request.futures
            or epoch % interval != 0
            or epoch - previous_epoch < interval
            or not _is_regular_stock_session(epoch)
        )
    ):
        return rows[:-1]
    return rows


def _quote_rows(quote: dict[str, Any], request: ChartRequest) -> list[ChartRow]:
    dates = quote.get("date") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    rows: list[ChartRow] = []
    last_close = _safe_float(quote.get("lastClose"))
    row_count = min(map(len, (dates, opens, highs, lows, closes)))
    for i in range(row_count):
        o, h, l = (_safe_float(values[i]) for values in (opens, highs, lows))
        c = _safe_float(closes[i])
        if c is None and i == row_count - 1:
            c = last_close
        if None in (o, h, l, c):
            continue
        v = _safe_float(volumes[i]) if i < len(volumes) else 0.0
        rows.append((int(dates[i]), o or 0.0, h or 0.0, l or 0.0, c or 0.0, v or 0.0))
    rows = _drop_live_quote_row(rows, request)
    if request.timeframe == "m":
        rows = _collapse_monthly_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


def aggregate_yahoo_chart_data(quote: dict[str, Any], request: ChartRequest) -> dict[str, Any]:
    bucket_seconds = YAHOO_AGGREGATE_SECONDS.get(request.timeframe)
    if bucket_seconds is None:
        return quote

    buckets: list[ChartRow] = []
    for epoch, open_, high, low, close, volume in _quote_rows(quote, request):
        bucket_epoch = (epoch // bucket_seconds) * bucket_seconds
        if not buckets or buckets[-1][0] != bucket_epoch:
            buckets.append((bucket_epoch, open_, high, low, close, volume))
            continue
        prev_epoch, prev_open, prev_high, prev_low, _, prev_volume = buckets[-1]
        buckets[-1] = (
            prev_epoch,
            prev_open,
            max(prev_high, high),
            min(prev_low, low),
            close,
            prev_volume + volume,
        )

    aggregated = dict(quote)
    aggregated["date"] = [row[0] for row in buckets]
    aggregated["open"] = [row[1] for row in buckets]
    aggregated["high"] = [row[2] for row in buckets]
    aggregated["low"] = [row[3] for row in buckets]
    aggregated["close"] = [row[4] for row in buckets]
    aggregated["volume"] = [row[5] for row in buckets]
    return aggregated


def _stock_5m_today_indexes(rows: list[ChartRow], request: ChartRequest) -> list[int] | None:
    if request.futures or request.timeframe != "i5" or request.date_range:
        return None
    last_local = dt.datetime.fromtimestamp(rows[-1][0], dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    start = dt.datetime.combine(last_local.date(), STOCK_5M_START, MARKET_TIME_ZONE).timestamp()
    end = dt.datetime.combine(last_local.date(), STOCK_5M_END, MARKET_TIME_ZONE).timestamp()
    indexes = [i for i, row in enumerate(rows) if start <= row[0] <= end]
    if len(indexes) >= SPARSE_CHART_MIN_BARS:
        return indexes
    same_day = [
        i for i, row in enumerate(rows)
        if dt.datetime.fromtimestamp(row[0], dt.timezone.utc).astimezone(MARKET_TIME_ZONE).date() == last_local.date()
    ]
    return same_day if len(same_day) >= SPARSE_CHART_MIN_BARS else None


def _visible_indexes(rows: list[ChartRow], request: ChartRequest) -> list[int]:
    today_indexes = _stock_5m_today_indexes(rows, request)
    if today_indexes is not None:
        indexes = today_indexes
    elif (cutoff := _range_cutoff(rows[-1][0], request.date_range)) is not None:
        indexes = [i for i, row in enumerate(rows) if row[0] >= cutoff]
    elif request.date_range == "max":
        indexes = list(range(len(rows)))
    else:
        if request.timeframe.startswith(("i", "h")):
            count = FUTURES_INTRADAY_VISIBLE_BARS if request.futures else STOCK_INTRADAY_VISIBLE_BARS
        elif request.timeframe == "d" and not request.futures:
            count = STOCK_DAILY_VISIBLE_BARS
        elif request.timeframe == "w" and not request.futures:
            count = STOCK_WEEKLY_VISIBLE_BARS
        elif request.timeframe == "m" and not request.futures:
            count = STOCK_MONTHLY_VISIBLE_BARS
        else:
            count = {"d": 90, "w": 104, "m": 120}.get(request.timeframe, 90)
        indexes = list(range(max(0, len(rows) - count), len(rows)))
    if len(indexes) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")
    return indexes


def _is_regular_stock_session(epoch: int) -> bool:
    local_time = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE).time()
    return REGULAR_SESSION_START <= local_time < REGULAR_SESSION_END


def _stock_extended_session_key(epoch: int) -> SessionKey | None:
    local = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    local_time = local.time()
    if STOCK_5M_START <= local_time < REGULAR_SESSION_START:
        return "pre", local.date()
    if REGULAR_SESSION_END <= local_time <= STOCK_5M_END:
        return "after", local.date()
    return None


def _futures_globex_session_key(epoch: int) -> SessionKey | None:
    local_time = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE).time()
    if REGULAR_SESSION_START <= local_time < REGULAR_SESSION_END:
        return None
    return "globex", "globex"


def _extended_session_bands(
    rows: list[ChartRow],
    x_positions: list[int],
    left: int,
    plot_right: int,
    session_key_for_epoch: Callable[[int], SessionKey | None],
) -> list[tuple[int, int, str]]:
    bands: list[tuple[int, int, str]] = []
    active: SessionKey | None = None
    start_pos = 0

    def append_band(start: int, end: int, kind: str) -> None:
        band_left = left if start == 0 else (x_positions[start - 1] + x_positions[start]) // 2
        band_right = plot_right if end == len(x_positions) - 1 else (x_positions[end] + x_positions[end + 1]) // 2
        if band_right > band_left:
            bands.append((band_left, band_right, kind))

    for pos, row in enumerate(rows):
        key = session_key_for_epoch(row[0])
        if key == active:
            continue
        if active is not None:
            append_band(start_pos, pos - 1, active[0])
        active = key
        start_pos = pos

    if active is not None:
        append_band(start_pos, len(rows) - 1, active[0])
    return bands


def _stock_extended_session_bands(
    rows: list[ChartRow],
    x_positions: list[int],
    left: int,
    plot_right: int,
) -> list[tuple[int, int, str]]:
    return _extended_session_bands(rows, x_positions, left, plot_right, _stock_extended_session_key)


def _futures_globex_session_bands(
    rows: list[ChartRow],
    x_positions: list[int],
    left: int,
    plot_right: int,
) -> list[tuple[int, int, str]]:
    return _extended_session_bands(rows, x_positions, left, plot_right, _futures_globex_session_key)


def _clean_stock_5m_wicks(rows: list[ChartRow], request: ChartRequest) -> list[ChartRow]:
    if request.futures or request.timeframe != "i5":
        return rows
    regular_ranges = sorted(
        max(0.0, row[2] - row[3])
        for row in rows
        if _is_regular_stock_session(row[0])
    )
    typical_range = regular_ranges[len(regular_ranges) // 2] if regular_ranges else 0.0
    threshold = max(abs(rows[-1][4]) * EXTENDED_WICK_PCT_LIMIT, typical_range * EXTENDED_WICK_RANGE_MULTIPLE, 0.0001)
    cleaned: list[ChartRow] = []
    for epoch, open_, high, low, close, volume in rows:
        body_high = max(open_, close)
        body_low = min(open_, close)
        if not _is_regular_stock_session(epoch):
            if body_low - low > threshold:
                low = body_low
            if high - body_high > threshold:
                high = body_high
        cleaned.append((epoch, open_, max(high, body_high), min(low, body_low), close, volume))
    return cleaned


def _chart_x_positions(count: int, left: int, plot_w: int) -> list[int]:
    if count < SPARSE_CHART_MIN_BARS:
        step = min(32, plot_w // SPARSE_CHART_MIN_BARS)
        start = left + plot_w - 1 - step * (count - 1)
        return [start + step * pos for pos in range(count)]
    return [left + round(pos * (plot_w - 1) / max(count - 1, 1)) for pos in range(count)]


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


def _nice_linear_axis(low: float, high: float) -> tuple[float, float, list[float]]:
    span = high - low
    if span <= 0:
        return low - 1, high + 1, [high + 1, low - 1]
    step = _nice_step(span / 10)
    nice_low = math.floor(low / step) * step
    nice_high = math.ceil(high / step) * step
    ticks: list[float] = []
    value = nice_high
    while value >= nice_low - step / 2:
        ticks.append(round(value, 10))
        value -= step
    return nice_low, nice_high, ticks


def _nice_step(value: float) -> float:
    magnitude = 10 ** math.floor(math.log10(value))
    residual = value / magnitude
    if residual <= 1:
        multiplier = 1
    elif residual <= 2:
        multiplier = 2
    elif residual <= 5:
        multiplier = 5
    else:
        multiplier = 10
    return multiplier * magnitude


def _volume_axis(value: float, request: ChartRequest) -> tuple[float, list[float]]:
    if value <= 0:
        return 1, []
    target_steps = 2 if request.timeframe in {"w", "m"} else 5
    step = _nice_step(value / target_steps)
    high = math.ceil(value / step) * step
    if request.timeframe == "w":
        return high, [step]
    ticks: list[float] = []
    tick = step
    while tick <= high + step / 2:
        ticks.append(tick)
        tick += step
    return high, ticks


def _volume_scale_value(rows: list[ChartRow], request: ChartRequest) -> float:
    values = sorted(row[5] for row in rows if row[5] > 0)
    if not values:
        return 0
    if request.timeframe.startswith(("i", "h")) and len(values) >= SPARSE_CHART_MIN_BARS:
        index = math.ceil(len(values) * INTRADAY_VOLUME_SCALE_PERCENTILE) - 1
        return values[max(0, min(index, len(values) - 1))]
    return values[-1]


def _date_label(epoch: int, intraday: bool, span: int) -> str:
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    if intraday:
        local = stamp.astimezone(MARKET_TIME_ZONE)
        return local.strftime("%H:%M") if span <= 3 * 86400 else local.strftime("%m/%d")
    return stamp.strftime("%b") if span < 400 * 86400 else stamp.strftime("%y")


def _month_tick_label(epoch: int, span: int) -> str:
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    if span < 400 * 86400:
        return stamp.strftime("%Y") if stamp.month == 1 else stamp.strftime("%b")
    if span < 900 * 86400:
        return stamp.strftime("%y") if stamp.month == 1 else stamp.strftime("%b")[0]
    return stamp.strftime("%y")


def render_price_chart_png(quote: dict[str, Any], request: ChartRequest) -> bytes:
    # Pillow keeps text crisp without pulling in a full charting framework.
    from PIL import Image, ImageDraw, ImageFont

    width, height = DEFAULT_WIDTH * DEFAULT_SCALE_FACTOR, DEFAULT_HEIGHT * DEFAULT_SCALE_FACTOR
    dark = request.theme == "dark"
    bg = (30, 34, 44) if dark else (250, 250, 250)
    grid = (43, 49, 62) if dark else (214, 218, 226)
    text = (148, 160, 181) if dark else (100, 108, 122)
    strong = (176, 186, 206) if dark else (50, 55, 65)
    up, down = (25, 200, 105), (255, 82, 82)
    line_color = (55, 160, 245) if dark else (25, 105, 210)
    vol_up, vol_down = (25, 120, 75), (128, 58, 68)

    def font(size: int, bold: bool = False) -> Any:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for path in (f"/usr/share/fonts/truetype/dejavu/{name}", name):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    header_font = font(18)
    label_font = font(17, True)
    axis_font = font(18)
    small_font = font(14)
    badge_font = font(17, True)
    sma_font = font(16)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    left, right, top, bottom = 60, CHART_RIGHT_MARGIN, 34, 30
    volume_h, gap = 68, 8
    vol_top, vol_bottom = height - bottom - volume_h, height - bottom
    price_top, price_bottom = top, vol_top - gap
    plot_right = width - right
    plot_w = plot_right - left
    all_rows = _clean_stock_5m_wicks(_quote_rows(quote, request), request)
    indexes = _visible_indexes(all_rows, request)
    rows = [all_rows[i] for i in indexes]
    base = rows[0][4]
    intraday = request.timeframe.startswith(("i", "h"))
    span = rows[-1][0] - rows[0][0]
    period_shell = request.timeframe in {"w", "m"} and not intraday

    def scaled(value: float) -> float:
        if request.scale == "percentage":
            return ((value / base) - 1.0) * 100.0
        if request.scale == "logarithmic":
            if value <= 0:
                raise NoChartData(f"Chart data has non-positive values for `{request.ticker}`, so log scale won't work.")
            return math.log(value)
        return value

    smas = {period: _sma_values(all_rows, period) for period in SMA_PERIODS}
    candles = [(i, d, scaled(o), scaled(h), scaled(l), scaled(c), v) for i, (d, o, h, l, c, v) in zip(indexes, rows)]
    scale_values = [value for _, _, o, h, l, c, _ in candles for value in (o, h, l, c)]
    low, high = min(scale_values), max(scale_values)
    if high == low:
        high += 1
        low -= 1
    if request.scale == "linear":
        low, high, y_ticks = _nice_linear_axis(low, high)
    else:
        pad = (high - low) * 0.055
        low, high = low - pad, high + pad
        y_ticks = [high - step * (high - low) / 4 for step in range(5)]
    vol_axis_high, vol_ticks = _volume_axis(_volume_scale_value(rows, request), request)

    x_positions = _chart_x_positions(len(candles), left, plot_w)
    if intraday and request.futures:
        session_bands = _futures_globex_session_bands(rows, x_positions, left, plot_right)
    elif intraday:
        session_bands = _stock_extended_session_bands(rows, x_positions, left, plot_right)
    else:
        session_bands = []
    session_fills = {
        "pre": (34, 42, 58) if dark else (236, 244, 252),
        "after": (45, 39, 53) if dark else (250, 240, 247),
        "globex": (34, 42, 58) if dark else (236, 244, 252),
    }
    session_boundary = (61, 76, 101) if dark else (184, 195, 211)
    session_text = (108, 126, 158) if dark else (112, 124, 143)
    session_labels = {"pre": "PRE", "after": "AH", "globex": "GLOBEX"}

    def x_at(i: int) -> int:
        return x_positions[i]

    def y_at(value: float) -> int:
        return price_bottom - round((value - low) * (price_bottom - price_top) / (high - low))

    def clip_price_segment(
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> tuple[tuple[int, int], tuple[int, int]] | None:
        x1, y1 = start
        x2, y2 = end
        if y1 == y2:
            return (start, end) if price_top <= y1 <= price_bottom else None
        if (y1 < price_top and y2 < price_top) or (y1 > price_bottom and y2 > price_bottom):
            return None

        def at_y(bound: int) -> tuple[int, int]:
            ratio = (bound - y1) / (y2 - y1)
            return round(x1 + (x2 - x1) * ratio), bound

        if y1 < price_top:
            start = at_y(price_top)
        elif y1 > price_bottom:
            start = at_y(price_bottom)
        if y2 < price_top:
            end = at_y(price_top)
        elif y2 > price_bottom:
            end = at_y(price_bottom)
        return start, end

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

    for x1, x2, kind in session_bands:
        draw.rectangle((x1, price_top, x2, vol_bottom), fill=session_fills[kind])

    for value in y_ticks:
        y = y_at(value)
        dashed(left, y, plot_right, y)
        if not (
            (request.scale == "linear" and low == 0 and value == 0)
            or (period_shell and value == high)
        ):
            draw.text((plot_right + 8, y - 11), _axis_label(value, request), fill=text, font=axis_font)
    x_ticks: list[tuple[int, str]]
    if request.timeframe == "m" and not intraday:
        x_ticks = [
            (pos, dt.datetime.fromtimestamp(row[0], dt.timezone.utc).strftime("%Y"))
            for pos, row in enumerate(rows)
            if dt.datetime.fromtimestamp(row[0], dt.timezone.utc).month == 1
        ]
    elif not intraday and len(rows) >= SPARSE_CHART_MIN_BARS:
        x_ticks = []
        previous_month: tuple[int, int] | None = None
        for pos, row in enumerate(rows):
            stamp = dt.datetime.fromtimestamp(row[0], dt.timezone.utc)
            month = (stamp.year, stamp.month)
            if month != previous_month:
                if span >= 400 * 86400 and not x_ticks and stamp.month != 1:
                    previous_month = month
                    continue
                x_ticks.append((pos, _month_tick_label(row[0], span)))
                previous_month = month
        if not 4 <= len(x_ticks) <= 20:
            x_ticks = []
    else:
        x_ticks = []
    if not x_ticks:
        x_ticks = [
            (round(step * (len(rows) - 1) / 5), _date_label(rows[round(step * (len(rows) - 1) / 5)][0], intraday, span))
            for step in range(6)
        ]

    drawn_sparse_labels: set[str] = set()
    for idx, label in x_ticks:
        x = x_at(idx)
        dashed(x, price_top, x, vol_bottom)
        if len(rows) < SPARSE_CHART_MIN_BARS:
            if label in drawn_sparse_labels:
                continue
            drawn_sparse_labels.add(label)
        label_w = draw.textbbox((0, 0), label, font=axis_font)[2]
        draw.text((max(0, min(plot_right - label_w, x - label_w // 2)), vol_bottom + 6), label, fill=text, font=axis_font)
    draw.line((left, price_bottom, plot_right, price_bottom), fill=grid, width=1)

    for x1, x2, kind in session_bands:
        if x1 > left:
            draw.line((x1, price_top, x1, vol_bottom), fill=session_boundary, width=1)
        if x2 < plot_right:
            draw.line((x2, price_top, x2, vol_bottom), fill=session_boundary, width=1)
        label = session_labels[kind]
        label_w = draw.textbbox((0, 0), label, font=small_font)[2]
        if x2 - x1 >= label_w + 12:
            label_x = max(x1 + 4, min(x2 - label_w - 4, x1 + (x2 - x1 - label_w) // 2))
            draw.text((label_x, price_top + 4), label, fill=session_text, font=small_font)

    candle_w = max(2, min(8, int(plot_w / max(len(candles), 1) * 0.58)))
    close_points: list[tuple[int, int]] = []
    for pos, (_, _, o, h, l, c, v) in enumerate(candles):
        x = x_at(pos)
        color = up if c >= o else down
        vh = min(vol_bottom - vol_top, round((v / vol_axis_high) * (vol_bottom - vol_top)))
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
        points: list[tuple[int, int]] = []
        for pos, i in enumerate(indexes):
            value = values[i]
            if value is not None:
                points.append((x_at(pos), y_at(scaled(value))))
        for start, end in zip(points, points[1:]):
            clipped = clip_price_segment(start, end)
            if clipped is not None:
                draw.line(clipped, fill=SMA_COLORS[period], width=1)

    last_idx = indexes[-1]
    last = all_rows[last_idx]
    prev = _safe_float(quote.get("prevClose")) or all_rows[max(0, last_idx - 1)][4]
    change = (_safe_float(quote.get("perfDayUsd")) if quote.get("perfDayUsd") is not None else last[4] - prev) or 0.0
    pct = (_safe_float(quote.get("perfDayPct")) if quote.get("perfDayPct") is not None else (change / prev * 100 if prev else 0.0)) or 0.0
    change_color = up if change >= 0 else down
    candle_color = up if last[4] >= last[1] else down
    date = dt.datetime.fromtimestamp(last[0], dt.timezone.utc).strftime("%b %d")
    change_label = f"{change:+.2f} ({pct:+.2f}%)"

    if period_shell:
        title_font = font(38, True)
        draw.text((8, 0), request.ticker, fill=strong, font=title_font)
        title_w = draw.textbbox((8, 0), request.ticker, font=title_font)[2]
        draw.text((title_w + 14, 10), date, fill=text, font=header_font)
    else:
        header_x = 8
        header_parts = [
            (request.ticker, strong),
            (f"   {date}", text),
            ("   O", text), (_fmt(last[1]), candle_color),
            ("   H", text), (_fmt(last[2]), candle_color),
            ("   L", text), (_fmt(last[3]), candle_color),
            ("   C", text), (_fmt(last[4]), candle_color),
            ("   Vol ", text), (_header_volume_label(last, request), candle_color),
        ]
        for part, color in header_parts:
            draw.text((header_x, 6), part, fill=color, font=header_font)
            header_x += draw.textbbox((0, 0), part, font=header_font)[2]
    change_w = draw.textbbox((0, 0), change_label, font=label_font)[2]
    draw.text((width - right - change_w - 8, 8), change_label, fill=change_color, font=label_font)

    for row, period in enumerate(SMA_PERIODS):
        value = smas[period][last_idx]
        if value is not None:
            draw.text((8, 46 + row * 22), f"SMA {period} · {_fmt(value)}", fill=SMA_COLORS[period], font=sma_font)
    if period_shell:
        side_font = font(24, True)
        label = request.timeframe_label.upper()
        label_img = Image.new("RGBA", (220, 42), (0, 0, 0, 0))
        label_draw = ImageDraw.Draw(label_img)
        label_draw.text((0, 0), label, fill=text + (255,), font=side_font)
        label_img = label_img.crop(label_img.getbbox() or (0, 0, 1, 1)).rotate(90, expand=True)
        image.paste(label_img, (18, price_top + (price_bottom - price_top - label_img.height) // 2), label_img)

    last_scaled = scaled(last[4])
    badge_text = _axis_label(last_scaled, request)
    badge_w = draw.textbbox((0, 0), badge_text, font=badge_font)[2] + 10
    bx, by = width - badge_w - 6, max(price_top, min(price_bottom - 25, y_at(last_scaled) - 13))
    draw.rounded_rectangle((bx, by, bx + badge_w, by + 25), radius=2, fill=(245, 211, 65))
    draw.text((bx + 6, by + 2), badge_text, fill=(22, 24, 30), font=badge_font)
    for value in vol_ticks:
        y = vol_bottom - round((value / vol_axis_high) * (vol_bottom - vol_top))
        draw.text((6, y - 9), _fmt_volume(value), fill=text, font=small_font)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _fmt(value: Any, suffix: str = "") -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}{suffix}" if abs(number) < 1000 else f"{number:,.0f}{suffix}"


def _fmt_signed(value: Any, suffix: str = "") -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return ("+" if number > 0 else "") + _fmt(number, suffix)


def _fmt_volume(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    for suffix, scale in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= scale:
            scaled = number / scale
            if suffix != "B" and abs(scaled) >= 100:
                return f"{scaled:.0f}{suffix}"
            return f"{scaled:.1f}{suffix}"
    return f"{number:,.0f}"


def _header_volume_label(row: ChartRow, request: ChartRequest) -> str:
    if (
        _source_interval_seconds(request) is not None
        and row[5] == 0
        and (request.futures or not _is_regular_stock_session(row[0]))
    ):
        return "n/a"
    return _fmt_volume(row[5])


def _quote_time_label(quote: dict[str, Any]) -> str | None:
    timestamp = _safe_float(quote.get("lastTime"))
    if timestamp is None:
        dates = quote.get("date") or []
        timestamp = _safe_float(dates[-1]) if dates else None
    if timestamp is None:
        return None
    stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    return stamp.strftime("%I:%M %p ET").lstrip("0")


def _stock_previous_close(meta: dict[str, Any], valid_closes: list[float], request: ChartRequest) -> float | None:
    if request.timeframe == "d" and len(valid_closes) > 1:
        return valid_closes[-2]
    return (
        _safe_float(meta.get("previousClose"))
        or _safe_float(meta.get("chartPreviousClose"))
        or (valid_closes[-2] if len(valid_closes) > 1 else None)
    )


def _latest_quote_price_time(
    meta: dict[str, Any],
    dates: list[Any],
    closes: list[Any],
    request: ChartRequest,
) -> tuple[float | None, int | None]:
    latest_close = next(
        (close for close in (_safe_float(value) for value in reversed(closes)) if close is not None),
        None,
    )
    latest_time = int(dates[-1]) if dates else None
    regular_price = _safe_float(meta.get("regularMarketPrice"))
    regular_time_float = _safe_float(meta.get("regularMarketTime"))
    regular_time = int(regular_time_float) if regular_time_float is not None else None
    if (
        not request.futures
        and request.timeframe == "i5"
        and latest_close is not None
        and latest_time is not None
        and (regular_time is None or latest_time > regular_time)
    ):
        return latest_close, latest_time
    return (regular_price if regular_price is not None else latest_close), (regular_time or latest_time)


def _quote_display_name(quote: dict[str, Any]) -> str:
    ticker = str(quote.get("ticker") or "").upper()
    if quote.get("futures") and ticker in FUTURES_DISPLAY_NAMES:
        return FUTURES_DISPLAY_NAMES[ticker]
    return str(quote.get("name") or quote.get("ticker") or "quote")


def quote_description(quote: dict[str, Any]) -> str:
    metric_parts = [f"Last **{_fmt(quote.get('lastClose'))}**"]
    if quote.get("perfDayUsd") is not None or quote.get("perfDayPct") is not None:
        metric_parts.append(f"**{_fmt_signed(quote.get('perfDayUsd'))}** ({_fmt_signed(quote.get('perfDayPct'), '%')})")
    time_label = _quote_time_label(quote)
    if time_label:
        metric_parts.append(time_label)
    return f"{_quote_display_name(quote)}\n" + " · ".join(metric_parts)


def self_test() -> None:
    assert parse_chart_command("hello") is None
    assert parse_chart_command(";") is None
    assert parse_chart_command(";help") is None
    assert parse_chart_command(";aapl") == ChartRequest("AAPL", "i5", "5 min")
    assert parse_chart_command(";aapl d") == ChartRequest("AAPL", "d", "daily")
    assert parse_chart_command(";brk.b w line") == ChartRequest("BRK-B", "w", "weekly", "l", "line")
    assert parse_chart_command(";aapl m line dark log") == ChartRequest(
        "AAPL", "m", "monthly", "l", "line", "dark", "dark", "logarithmic", "log"
    )
    ranged = parse_chart_command(";aapl 1y")
    assert ranged is not None
    assert ranged.timeframe == "d" and ranged.date_range == "y1"
    amd_description = quote_description({"ticker": "AMD", "lastClose": 548.54, "lastTime": 1781535058})
    assert amd_description == "AMD\nLast **548.54** · 10:50 AM ET"
    assert "`" not in amd_description
    assert _stock_previous_close(
        {"chartPreviousClose": 490.33, "previousClose": 511.57},
        [490.33, 551.24],
        ChartRequest("AMD", "i5", "5 min"),
    ) == 511.57
    assert _stock_previous_close({}, [488.45, 511.57, 551.24], ChartRequest("AMD", "d", "daily")) == 511.57
    pending_rows = _quote_rows({
        "date": [1, 2],
        "open": [10, 11],
        "high": [12, 13],
        "low": [9, 10],
        "close": [10.5, None],
        "volume": [100, 120],
        "lastClose": 12.5,
    }, ChartRequest("AMD", "d", "daily"))
    assert pending_rows[-1][4] == 12.5
    def utc_epoch(year: int, month: int, day: int) -> int:
        return int(dt.datetime(year, month, day, tzinfo=dt.timezone.utc).timestamp())
    monthly_rows = _quote_rows({
        "date": [utc_epoch(2026, 1, 1), utc_epoch(2026, 1, 15), utc_epoch(2026, 2, 1)],
        "open": [10, 11, 20],
        "high": [12, 15, 22],
        "low": [9, 8, 19],
        "close": [11, 14, 21],
        "volume": [100, 80, 120],
    }, ChartRequest("AMD", "m", "monthly"))
    assert monthly_rows == [
        (utc_epoch(2026, 1, 15), 10.0, 15.0, 8.0, 14.0, 100.0),
        (utc_epoch(2026, 2, 1), 20.0, 22.0, 19.0, 21.0, 120.0),
    ]
    assert parse_chart_command(";amd 1") == ChartRequest("AMD", "i1", "1 min")
    assert parse_chart_command(";amd 4h") == ChartRequest("AMD", "h4", "4 hour")
    assert "interval=1m" in yahoo_chart_url(ChartRequest("AMD", "i1", "1 min"))
    assert "range=5d" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "interval=5m" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "includePrePost=true" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "includePrePost=false" in yahoo_chart_url(ChartRequest("AMD", "i15", "15 min"))
    assert "range=1mo" in yahoo_chart_url(ChartRequest("AMD", "i30", "30 min"))
    assert "range=6mo" in yahoo_chart_url(ChartRequest("AMD", "h4", "4 hour"))
    assert "range=2y" in yahoo_chart_url(ChartRequest("AMD", "d", "daily"))
    for ticker, yahoo_symbol in YAHOO_SYMBOL_ALIASES.items():
        assert yahoo_symbol in yahoo_chart_url(ChartRequest(ticker, "d", "daily"))
    assert "range=2y" in yahoo_chart_url(ChartRequest("AMD", "d", "daily", date_range="y1"))
    assert "interval=1wk" in yahoo_chart_url(ChartRequest("AMD", "w", "weekly"))
    assert "range=10y" in yahoo_chart_url(ChartRequest("AMD", "w", "weekly"))
    monthly_url = yahoo_chart_url(ChartRequest("AMD", "m", "monthly"))
    assert "interval=1mo" in monthly_url and "period1=0" in monthly_url and "period2=" in monthly_url
    sample_rows = [(i, 1.0, 1.0, 1.0, float(i + 1), 1.0) for i in range(300)]
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "i15", "15 min"))) == 180
    assert len(_visible_indexes(sample_rows, ChartRequest("NQ", "i5", "5 min", futures=True))) == 140
    assert len(_visible_indexes(sample_rows + sample_rows, ChartRequest("AMD", "d", "daily"))) == STOCK_DAILY_VISIBLE_BARS
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "w", "weekly"))) == STOCK_WEEKLY_VISIBLE_BARS
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "m", "monthly"))) == STOCK_MONTHLY_VISIBLE_BARS
    assert _nice_linear_axis(14.92, 32.73) == (14, 34, [34, 32, 30, 28, 26, 24, 22, 20, 18, 16, 14])
    assert _volume_axis(688_100_000, ChartRequest("SOFI", "w", "weekly")) == (1_000_000_000, [500_000_000])
    volume_rows = [(i, 1.0, 1.0, 1.0, 1.0, float(i + 1)) for i in range(100)]
    volume_rows.append((101, 1.0, 1.0, 1.0, 1.0, 10_000.0))
    assert _volume_scale_value(volume_rows, ChartRequest("AMD", "i5", "5 min")) == 91.0
    assert _volume_scale_value(volume_rows, ChartRequest("AMD", "d", "daily")) == 10_000.0
    def et_epoch(hour: int, minute: int, day: int = 15) -> int:
        return int(dt.datetime(2026, 6, day, hour, minute, tzinfo=MARKET_TIME_ZONE).timestamp())
    mes_description = quote_description({
        "ticker": "MES",
        "futures": True,
        "name": "MICRO E-MINI S&P 500 INDEX FUTU",
        "lastClose": 7588,
        "perfDayUsd": 26.5,
        "perfDayPct": 0.35,
        "lastTime": et_epoch(18, 2),
    })
    assert mes_description == "Micro E-mini S&P 500\nLast **7,588** · **+26.50** (+0.35%) · 6:02 PM ET"
    assert _header_volume_label((et_epoch(7, 10), 1, 1, 1, 1, 0), ChartRequest("AMD", "i5", "5 min")) == "n/a"
    assert _header_volume_label((et_epoch(10, 10), 1, 1, 1, 1, 0), ChartRequest("AMD", "i5", "5 min")) == "0"
    assert _header_volume_label((et_epoch(7, 10), 1, 1, 1, 1, 10_500), ChartRequest("AMD", "i5", "5 min")) == "10.5K"
    assert _header_volume_label((et_epoch(7, 10), 1, 2, 1, 2, 0), ChartRequest("ES", "i5", "5 min", futures=True)) == "n/a"
    assert _header_volume_label((et_epoch(7, 10), 1, 2, 1, 2, 10_500), ChartRequest("ES", "i5", "5 min", futures=True)) == "10.5K"
    assert _stock_extended_session_key(et_epoch(7, 10)) == ("pre", dt.date(2026, 6, 15))
    assert _stock_extended_session_key(et_epoch(10, 10)) is None
    assert _stock_extended_session_key(et_epoch(16, 0)) == ("after", dt.date(2026, 6, 15))
    session_rows = [
        (et_epoch(4, 0), 1.0, 1.0, 1.0, 1.0, 1.0),
        (et_epoch(9, 30), 1.0, 1.0, 1.0, 1.0, 1.0),
        (et_epoch(16, 0), 1.0, 1.0, 1.0, 1.0, 1.0),
        (et_epoch(20, 0), 1.0, 1.0, 1.0, 1.0, 1.0),
    ]
    assert _stock_extended_session_bands(session_rows, [10, 20, 30, 40], 10, 40) == [
        (10, 15, "pre"),
        (25, 40, "after"),
    ]
    assert _futures_globex_session_key(et_epoch(7, 10)) == ("globex", "globex")
    assert _futures_globex_session_key(et_epoch(10, 10)) is None
    assert _futures_globex_session_key(et_epoch(16, 0)) == ("globex", "globex")
    assert _futures_globex_session_bands(session_rows, [10, 20, 30, 40], 10, 40) == [
        (10, 15, "globex"),
        (25, 40, "globex"),
    ]
    live_quote_rows = {
        "date": [et_epoch(7, 5), et_epoch(7, 7) + 15],
        "open": [10, 12],
        "high": [11, 12],
        "low": [9, 12],
        "close": [10.5, 12],
        "volume": [100, 0],
    }
    assert _source_interval_seconds(ChartRequest("ES", "i10", "10 min", futures=True)) == 5 * 60
    assert _source_interval_seconds(ChartRequest("ES", "h2", "2 hour", futures=True)) == 60 * 60
    assert len(_quote_rows(live_quote_rows, ChartRequest("AMD", "i5", "5 min"))) == 1
    assert len(_quote_rows(live_quote_rows, ChartRequest("ES", "i5", "5 min", futures=True))) == 1
    assert len(_quote_rows({
        "date": [et_epoch(10, 0), et_epoch(10, 5)],
        "open": [10, 12],
        "high": [10, 12],
        "low": [10, 12],
        "close": [10, 12],
        "volume": [0, 0],
    }, ChartRequest("AMD", "i5", "5 min"))) == 2
    assert len(_quote_rows({
        "date": [et_epoch(15, 30), et_epoch(16, 0)],
        "open": [10, 12],
        "high": [11, 12],
        "low": [9, 12],
        "close": [10.5, 12],
        "volume": [100, 0],
    }, ChartRequest("AMD", "h", "hourly"))) == 1
    assert len(_quote_rows({
        "date": [et_epoch(15, 59), et_epoch(16, 0)],
        "open": [10, 12],
        "high": [11, 12],
        "low": [9, 12],
        "close": [10.5, 12],
        "volume": [100, 0],
    }, ChartRequest("AMD", "i1", "1 min"))) == 1
    assert _latest_quote_price_time(
        {"regularMarketPrice": 754.83, "regularMarketTime": et_epoch(16, 0, 14)},
        [et_epoch(4, 0)],
        [754.54],
        ChartRequest("SPY", "i5", "5 min"),
    ) == (754.54, et_epoch(4, 0))
    assert _latest_quote_price_time(
        {"regularMarketPrice": 754.83, "regularMarketTime": et_epoch(9, 31)},
        [et_epoch(9, 30)],
        [754.54],
        ChartRequest("SPY", "i5", "5 min"),
    ) == (754.83, et_epoch(9, 31))
    today_rows = [
        (et_epoch(15, 55, 14), 1.0, 1.0, 1.0, 1.0, 1.0),
        (et_epoch(6, 55), 1.0, 1.0, 1.0, 2.0, 1.0),
        (et_epoch(7, 0), 1.0, 1.0, 1.0, 3.0, 1.0),
        (et_epoch(12, 0), 1.0, 1.0, 1.0, 4.0, 1.0),
        (et_epoch(20, 0), 1.0, 1.0, 1.0, 5.0, 1.0),
        (et_epoch(20, 5), 1.0, 1.0, 1.0, 6.0, 1.0),
    ]
    assert _stock_5m_today_indexes(today_rows, ChartRequest("AMD", "i5", "5 min")) is None
    dense_today_rows = [
        (
            int((dt.datetime(2026, 6, 15, 4, 0, tzinfo=MARKET_TIME_ZONE) + dt.timedelta(minutes=5 * i)).timestamp()),
            1.0,
            1.0,
            1.0,
            float(i + 1),
            1.0,
        )
        for i in range(SPARSE_CHART_MIN_BARS)
    ]
    assert _visible_indexes(
        [today_rows[0], *dense_today_rows],
        ChartRequest("AMD", "i5", "5 min"),
    ) == list(range(1, SPARSE_CHART_MIN_BARS + 1))
    wick_rows = [
        (et_epoch(7, 0), 100.0, 101.0, 80.0, 100.5, 1.0),
        (et_epoch(9, 30), 100.5, 100.8, 100.2, 100.6, 1.0),
        (et_epoch(9, 35), 100.6, 100.9, 100.3, 100.7, 1.0),
        (et_epoch(9, 40), 100.7, 101.0, 80.0, 100.8, 1.0),
        (et_epoch(16, 0), 100.8, 130.0, 100.6, 100.9, 1.0),
        (et_epoch(17, 0), 100.9, 130.0, 100.7, 101.0, 1.0),
    ]
    cleaned = _clean_stock_5m_wicks(wick_rows, ChartRequest("AMD", "i5", "5 min"))
    assert cleaned[0][3] == 100.0
    assert cleaned[3][3] == 80.0
    assert cleaned[4][2] == 100.9
    assert cleaned[5][2] == 101.0
    sparse_positions = _chart_x_positions(2, 60, 776)
    assert sparse_positions[0] > 760 and sparse_positions[1] == 835
    assert _date_label(1781536808, True, 3600) == "11:20"
    assert 80 <= CHART_RIGHT_MARGIN <= 96
    try:
        parse_chart_command(";spy 10")
    except ValueError as error:
        assert "Stock intraday supports" in str(error)
        assert "market chart data" in str(error)
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
    assert chart_title(ChartRequest("ES", futures=True)) == "ES · daily candles · futures"
    assert "ES=F" in yahoo_chart_url(ChartRequest("ES", futures=True))
    assert "interval=1m" in yahoo_chart_url(ChartRequest("ES", "i3", "3 min", futures=True))
    assert "interval=5m" in yahoo_chart_url(ChartRequest("ES", "i10", "10 min", futures=True))
    aggregated = aggregate_yahoo_chart_data({
        "ticker": "ES",
        "date": [0, 60, 120, 180],
        "open": [10, 11, 12, 13],
        "high": [11, 12, 13, 14],
        "low": [9, 10, 11, 12],
        "close": [10.5, 11.5, 12.5, 13.5],
        "volume": [1, 2, 3, 4],
    }, ChartRequest("ES", "i3", "3 min", futures=True))
    assert aggregated["date"] == [0, 180]
    assert aggregated["open"] == [10.0, 13.0]
    assert aggregated["high"] == [13.0, 14.0]
    assert aggregated["low"] == [9.0, 12.0]
    assert aggregated["close"] == [12.5, 13.5]
    assert aggregated["volume"] == [6.0, 4.0]
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
