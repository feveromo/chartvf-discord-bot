import datetime as dt
import io
import math
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import pairwise
from typing import Any, Literal, NamedTuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

PREFIX = ";"
HELP_COMMANDS = frozenset({"help", "h"})
DEFAULT_TIMEFRAME = "d"
DEFAULT_INTRADAY_TIMEFRAME = "i5"
DEFAULT_CHART_TYPE = "c"
DEFAULT_THEME = "light"
DEFAULT_SCALE = "linear"
DEFAULT_SCALE_FACTOR = 2
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 239
CHART_RIGHT_MARGIN = 80
MARKET_TIME_ZONE = ZoneInfo("America/New_York")
STOCK_DAILY_VISIBLE_BARS = 140
STOCK_WEEKLY_VISIBLE_BARS = 160
STOCK_INTRADAY_VISIBLE_BARS = 150
STOCK_MONTHLY_VISIBLE_BARS = 240
SMA_PERIODS = (20, 50, 200)
SMA_COLORS = {20: (142, 43, 132), 50: (238, 126, 35), 200: (139, 111, 43)}
# SMA lines are drawn on a 4x supersampled mask and box-filtered down, which
# gives exact coverage anti-aliasing without blurring the line.
SMA_SUPERSAMPLE = 4
SMA_LINE_WIDTH = 1.25
SMA_MASK_MARGIN = 2
LIGHT_DAILY_UP = (21, 141, 54)
LIGHT_DAILY_DOWN = (213, 33, 45)
LIGHT_DAILY_VOLUME_ALPHA = 0.28
LIGHT_LINE_COLOR = (25, 105, 210)
DARK_UP = (25, 200, 105)
DARK_DOWN = (255, 82, 82)
DARK_LINE_COLOR = (55, 160, 245)
DARK_VOLUME_UP = (25, 120, 75)
DARK_VOLUME_DOWN = (128, 58, 68)
FUTURES_INTRADAY_VISIBLE_BARS = 120
EXTENDED_SESSION_START = dt.time(4, 0)
REGULAR_SESSION_START = dt.time(9, 30)
REGULAR_SESSION_END = dt.time(16, 0)
EXTENDED_SESSION_END = dt.time(20, 0)
EXTENDED_WICK_PCT_LIMIT = 0.004
EXTENDED_WICK_RANGE_MULTIPLE = 3.0
FUTURES_STALE_WICK_RANGE_MULTIPLE = 2.0
FUTURES_STALE_EXTREME_MIN_REPEATS = 3
FUTURES_STALE_EXTREME_MIN_FLAGS = 2
SPARSE_CHART_MIN_BARS = 24
DAY = 86400
WEEK = 7 * DAY


class Timeframe(NamedTuple):
    label: str
    seconds: int
    stocks: bool = True  # False: crypto and futures only


TIMEFRAMES = {
    "d": Timeframe("daily", DAY),
    "w": Timeframe("weekly", WEEK),
    "m": Timeframe("monthly", 30 * DAY),
    "i1": Timeframe("1 min", 60),
    "i2": Timeframe("2 min", 2 * 60),
    "i3": Timeframe("3 min", 3 * 60),
    "i5": Timeframe("5 min", 5 * 60),
    "i10": Timeframe("10 min", 10 * 60, stocks=False),
    "i15": Timeframe("15 min", 15 * 60),
    "i30": Timeframe("30 min", 30 * 60),
    "h": Timeframe("hourly", 60 * 60),
    "h2": Timeframe("2 hour", 2 * 60 * 60, stocks=False),
    "h4": Timeframe("4 hour", 4 * 60 * 60),
}
TIMEFRAME_ALIASES = {
    **{code: code for code in TIMEFRAMES},
    **{
        alias: f"i{minutes}"
        for minutes in (1, 2, 3, 5, 10, 15, 30)
        for alias in (str(minutes), f"{minutes}min")
    },
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
    "60": "h",
    "1h": "h",
    "hourly": "h",
    "2h": "h2",
    "4h": "h4",
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
DATE_RANGE_DAYS = {"m1": 31, "m3": 93, "m6": 186, "y1": 365, "y2": 730, "y5": 1826}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
CRYPTO_TICKER_ALIASES = {
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "ETHER": "ETH",
    "DOGECOIN": "DOGE",
}
CRYPTO_SYMBOLS = {
    "BTC": ("BTCUSDT", "Bitcoin / TetherUS"),
    "ETH": ("ETHUSDT", "Ethereum / TetherUS"),
    "DOGE": ("DOGEUSDT", "Dogecoin / TetherUS"),
}
# `;p`, `;P` and `;D` are faces, not charts, unless chart options follow
# (`;D d` still charts Dominion Energy daily).
FACE_TOKENS = frozenset({"p", "P", "D"})
STOCK_INTRADAY_UNSUPPORTED_MESSAGE = (
    "Stock intraday supports `1`, `2`, `3`, `5`, `15`, `30`, `60`, and `4h` "
    "via market chart data. Use `d`, `w`, or `m` for higher timeframes."
)
UNKNOWN_OPTION_MESSAGE = (
    "Unknown chart option `{option}`. Use `d`, `w`, `m`, stock intraday `1`, `2`, `3`, `5`, "
    "`15`, `30`, `60`, `4h`, `candle`, `line`, `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, "
    "`max`, `dark`, `light`, `linear`, `log`, or `percent`. Crypto and futures also "
    "support `10` and `2h`."
)

# Futures must not use `;f`: that is Ford's stock ticker. Use `;fut ES`.
FUTURES_TICKER_RE = re.compile(r"^[A-Z0-9]{1,8}$")
FUTURES_ALIASES = frozenset({"fut", "future", "futures"})
CHART_ALIASES = frozenset({"chart", "charts"})
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


CryptoMarket = Literal["", "auto", "spot", "perp"]


@dataclass(frozen=True, slots=True)
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
    crypto_market: CryptoMarket = ""


class ChartRow(NamedTuple):
    epoch: int
    open: float
    high: float
    low: float
    close: float
    volume: float


ChartRowValues = tuple[int, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class ChartData:
    ticker: str
    name: str
    rows: tuple[ChartRow, ...]
    last_close: float | None = None
    last_time: int | None = None
    previous_close: float | None = None
    market_label: str = ""
    futures: bool = False
    source_interval_seconds: int | None = None
    preserve_last_bar: bool = False

    @property
    def change(self) -> float | None:
        if self.last_close is None or not self.previous_close:
            return None
        return self.last_close - self.previous_close

    @property
    def change_percent(self) -> float | None:
        change = self.change
        if change is None or not self.previous_close:
            return None
        return change / self.previous_close * 100


class NoChartData(ValueError):
    pass


def is_intraday(timeframe: str) -> bool:
    return timeframe.startswith(("i", "h"))


def native_timeframe(timeframe: str, supported: Collection[str]) -> str:
    """Pick the timeframe to fetch from a provider that natively has `supported`.

    Intraday timeframes a provider lacks fall back to the coarsest supported
    timeframe that divides them evenly; `aggregate_chart_data` rebuilds the
    requested bars from those.
    """
    if timeframe in supported:
        return timeframe
    seconds = TIMEFRAMES[timeframe].seconds
    divisors = [
        code
        for code in supported
        if is_intraday(code) and seconds % TIMEFRAMES[code].seconds == 0
    ]
    if not is_intraday(timeframe) or not divisors:
        raise ValueError(f"No source data for `{TIMEFRAMES[timeframe].label}` charts.")
    return max(divisors, key=lambda code: TIMEFRAMES[code].seconds)


def parse_chart_command(content: str) -> ChartRequest | None:
    """Parse `;TICKER [options]`. None means the message is not a chart command."""
    if not content.startswith(PREFIX):
        return None
    parts = content[len(PREFIX):].split()
    if not parts or parts[0].lower() in HELP_COMMANDS:
        return None

    command = parts[0].lower()
    futures = command in FUTURES_ALIASES
    explicit = futures or command in CHART_ALIASES
    if explicit:
        parts = parts[1:]
        if not parts:
            raise ValueError(
                "Usage: `;fut ES`, `;fut CL w line`, or `;futures GC 1y`"
                if futures
                else "Usage: `;AAPL`, `;AAPL w`, or `;AAPL m line dark log`"
            )

    raw_ticker, options = parts[0], parts[1:]
    ticker = raw_ticker.upper().replace(".", "-")
    if futures:
        if not FUTURES_TICKER_RE.fullmatch(ticker):
            raise ValueError("Futures root looks wrong. Use roots like `;fut ES`, `;fut CL`, or `;fut 6E`.")
    elif not TICKER_RE.fullmatch(ticker):
        if explicit:
            raise ValueError("Ticker looks wrong. Use letters/numbers only, like `;AAPL` or `;BRK-B`.")
        return None  # chatter such as `;)` or `;_;`
    else:
        ticker = CRYPTO_TICKER_ALIASES.get(ticker, ticker)

    face = not explicit and raw_ticker in FACE_TOKENS
    if face and not options:
        return None
    try:
        return _parse_chart_options(ticker, options, futures=futures)
    except ValueError:
        if face:
            return None  # `;p` followed by chatter
        raise


def _parse_chart_options(ticker: str, options: list[str], *, futures: bool) -> ChartRequest:
    crypto = not futures and ticker in CRYPTO_SYMBOLS
    timeframe: str | None = None
    chart_type, chart_type_label = CHART_TYPES[DEFAULT_CHART_TYPE]
    theme, theme_label = THEMES[DEFAULT_THEME]
    scale, scale_label = SCALES[DEFAULT_SCALE]
    date_range = date_range_label = ""

    for raw_option in options:
        option = raw_option.lower()
        if option in TIMEFRAME_ALIASES:
            timeframe = TIMEFRAME_ALIASES[option]
            if not (futures or crypto or TIMEFRAMES[timeframe].stocks):
                raise ValueError(STOCK_INTRADAY_UNSUPPORTED_MESSAGE)
        elif option in CHART_TYPES:
            chart_type, chart_type_label = CHART_TYPES[option]
        elif option in THEMES:
            theme, theme_label = THEMES[option]
        elif option in SCALES:
            scale, scale_label = SCALES[option]
        elif option in DATE_RANGES:
            date_range, date_range_label = DATE_RANGES[option]
        else:
            raise ValueError(UNKNOWN_OPTION_MESSAGE.format(option=raw_option))

    if timeframe is None:
        timeframe = DEFAULT_TIMEFRAME if date_range else DEFAULT_INTRADAY_TIMEFRAME
    if date_range and is_intraday(timeframe):
        raise ValueError(
            "Date ranges only work with `d`, `w`, or `m` charts. "
            "Use `;AAPL 1y` for a 1-year daily chart, or drop the range for intraday."
        )

    return ChartRequest(
        ticker=ticker,
        timeframe=timeframe,
        timeframe_label=TIMEFRAMES[timeframe].label,
        chart_type=chart_type,
        chart_type_label=chart_type_label,
        theme=theme,
        theme_label=theme_label,
        scale=scale,
        scale_label=scale_label,
        date_range=date_range,
        date_range_label=date_range_label,
        futures=futures,
        crypto_market="auto" if crypto else "",
    )


def chart_title(request: ChartRequest, market_label: str | None = None) -> str:
    parts = [request.ticker]
    if request.date_range_label:
        parts.append(request.date_range_label)
    chart_type = "candles" if request.chart_type == "c" else request.chart_type_label
    parts.append(f"{request.timeframe_label} {chart_type}")
    if request.scale != DEFAULT_SCALE:
        parts.append(request.scale_label)
    if request.theme != DEFAULT_THEME:
        parts.append(request.theme_label)
    if market_label is not None:
        parts.append(market_label)
    if request.futures:
        parts.append("futures")
    return " · ".join(parts)


SessionKey = tuple[str, object]


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _blend_rgb(fg: tuple[int, int, int], bg: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return (
        round(fg[0] * alpha + bg[0] * (1.0 - alpha)),
        round(fg[1] * alpha + bg[1] * (1.0 - alpha)),
        round(fg[2] * alpha + bg[2] * (1.0 - alpha)),
    )


def _range_cutoff(last_epoch: int, date_range: str) -> int | None:
    if date_range in {"", "max"}:
        return None
    last = dt.datetime.fromtimestamp(last_epoch, dt.timezone.utc)
    if date_range == "ytd":
        return int(dt.datetime(last.year, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    days = DATE_RANGE_DAYS.get(date_range)
    return int((last - dt.timedelta(days=days)).timestamp()) if days else None


def _collapse_monthly_rows(rows: list[ChartRow]) -> list[ChartRow]:
    collapsed: list[ChartRow] = []
    last_month: tuple[int, int] | None = None
    for epoch, open_, high, low, close, volume in rows:
        stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
        month = (stamp.year, stamp.month)
        if month == last_month:
            _, prev_open, prev_high, prev_low, _, prev_volume = collapsed[-1]
            collapsed[-1] = ChartRow(
                epoch,
                prev_open,
                max(prev_high, high),
                min(prev_low, low),
                close,
                prev_volume + volume,
            )
            continue
        collapsed.append(ChartRow(epoch, open_, high, low, close, volume))
        last_month = month
    return collapsed


def _drop_live_quote_row(
    rows: list[ChartRow],
    request: ChartRequest,
    source_interval_seconds: int | None = None,
    preserve_last_bar: bool = False,
) -> list[ChartRow]:
    if preserve_last_bar or len(rows) < 2:
        return rows
    interval = source_interval_seconds
    if interval is None and is_intraday(request.timeframe):
        interval = TIMEFRAMES[request.timeframe].seconds
    if interval is None or interval >= WEEK:
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
            or not is_regular_session(epoch)
        )
    ):
        return rows[:-1]
    return rows


def normalize_chart_rows(
    dates: list[Any],
    opens: list[Any],
    highs: list[Any],
    lows: list[Any],
    closes: list[Any],
    volumes: list[Any],
    *,
    last_close: float | None = None,
) -> tuple[ChartRow, ...]:
    rows: list[ChartRow] = []
    row_count = min(map(len, (dates, opens, highs, lows, closes)))
    for i in range(row_count):
        open_, high, low = (safe_float(values[i]) for values in (opens, highs, lows))
        close = safe_float(closes[i])
        if close is None and i == row_count - 1:
            close = last_close
        if open_ is None or high is None or low is None or close is None:
            continue
        if close > 0 and open_ == high == low == 0:
            open_ = high = low = close
        volume = safe_float(volumes[i]) if i < len(volumes) else 0.0
        rows.append(
            ChartRow(
                int(dates[i]),
                open_ or 0.0,
                high or 0.0,
                low or 0.0,
                close or 0.0,
                volume or 0.0,
            )
        )
    return tuple(rows)


def _chart_rows(data: ChartData, request: ChartRequest) -> list[ChartRow]:
    rows = _drop_live_quote_row(
        list(data.rows),
        request,
        data.source_interval_seconds,
        data.preserve_last_bar,
    )
    if request.timeframe == "m":
        rows = _collapse_monthly_rows(rows)
    if not rows:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    return rows


def aggregate_chart_data(data: ChartData, request: ChartRequest) -> ChartData:
    """Rebuild requested intraday bars from finer source bars (e.g. 3m from 1m)."""
    bucket_seconds = TIMEFRAMES[request.timeframe].seconds
    source_seconds = data.source_interval_seconds
    if (
        not is_intraday(request.timeframe)
        or source_seconds is None
        or source_seconds >= bucket_seconds
    ):
        return data

    buckets: list[ChartRow] = []
    for epoch, open_, high, low, close, volume in _chart_rows(data, request):
        bucket_epoch = (epoch // bucket_seconds) * bucket_seconds
        if not buckets or buckets[-1][0] != bucket_epoch:
            buckets.append(ChartRow(bucket_epoch, open_, high, low, close, volume))
            continue
        prev_epoch, prev_open, prev_high, prev_low, _, prev_volume = buckets[-1]
        buckets[-1] = ChartRow(
            prev_epoch,
            prev_open,
            max(prev_high, high),
            min(prev_low, low),
            close,
            prev_volume + volume,
        )

    return replace(data, rows=tuple(buckets), source_interval_seconds=bucket_seconds)


def _stock_5m_today_indexes(rows: Sequence[ChartRowValues], request: ChartRequest) -> list[int] | None:
    if request.futures or request.timeframe != "i5" or request.date_range:
        return None
    last_local = dt.datetime.fromtimestamp(rows[-1][0], dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    session_date = last_local.date()
    if last_local.time() >= EXTENDED_SESSION_END:
        session_date += dt.timedelta(days=1)
    start = dt.datetime.combine(
        session_date - dt.timedelta(days=1),
        EXTENDED_SESSION_END,
        MARKET_TIME_ZONE,
    ).timestamp()
    end = dt.datetime.combine(session_date, EXTENDED_SESSION_END, MARKET_TIME_ZONE).timestamp()
    indexes = [i for i, row in enumerate(rows) if start <= row[0] < end]
    if len(indexes) >= SPARSE_CHART_MIN_BARS:
        return indexes
    same_day = [
        i for i, row in enumerate(rows)
        if dt.datetime.fromtimestamp(row[0], dt.timezone.utc).astimezone(MARKET_TIME_ZONE).date() == last_local.date()
    ]
    return same_day if len(same_day) >= SPARSE_CHART_MIN_BARS else None


def _visible_indexes(rows: Sequence[ChartRowValues], request: ChartRequest) -> list[int]:
    today_indexes = _stock_5m_today_indexes(rows, request)
    if today_indexes is not None:
        indexes = today_indexes
    elif (cutoff := _range_cutoff(rows[-1][0], request.date_range)) is not None:
        indexes = [i for i, row in enumerate(rows) if row[0] >= cutoff]
    elif request.date_range == "max":
        indexes = list(range(len(rows)))
    else:
        if is_intraday(request.timeframe):
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


def is_regular_session(epoch: int) -> bool:
    local_time = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE).time()
    return REGULAR_SESSION_START <= local_time < REGULAR_SESSION_END


def _stock_extended_session_key(epoch: int) -> SessionKey | None:
    local = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    local_time = local.time()
    if local_time >= EXTENDED_SESSION_END:
        return "overnight", local.date() + dt.timedelta(days=1)
    if local_time < EXTENDED_SESSION_START:
        return "overnight", local.date()
    if EXTENDED_SESSION_START <= local_time < REGULAR_SESSION_START:
        return "pre", local.date()
    if REGULAR_SESSION_END <= local_time < EXTENDED_SESSION_END:
        return "after", local.date()
    return None


def _futures_globex_session_key(epoch: int) -> SessionKey | None:
    local_time = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(MARKET_TIME_ZONE).time()
    if REGULAR_SESSION_START <= local_time < REGULAR_SESSION_END:
        return None
    return "globex", "globex"


def _extended_session_bands(
    rows: Sequence[ChartRowValues],
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
    rows: Sequence[ChartRowValues],
    x_positions: list[int],
    left: int,
    plot_right: int,
) -> list[tuple[int, int, str]]:
    return _extended_session_bands(rows, x_positions, left, plot_right, _stock_extended_session_key)


def _futures_globex_session_bands(
    rows: Sequence[ChartRowValues],
    x_positions: list[int],
    left: int,
    plot_right: int,
) -> list[tuple[int, int, str]]:
    return _extended_session_bands(rows, x_positions, left, plot_right, _futures_globex_session_key)


def _clean_stock_extended_wicks(
    rows: Sequence[ChartRowValues],
    request: ChartRequest,
) -> list[ChartRowValues]:
    if request.futures or not is_intraday(request.timeframe):
        return list(rows)
    regular_ranges = sorted(
        max(0.0, row[2] - row[3])
        for row in rows
        if is_regular_session(row[0])
    )
    typical_range = regular_ranges[len(regular_ranges) // 2] if regular_ranges else 0.0
    threshold = max(abs(rows[-1][4]) * EXTENDED_WICK_PCT_LIMIT, typical_range * EXTENDED_WICK_RANGE_MULTIPLE, 0.0001)
    cleaned: list[ChartRowValues] = []
    for epoch, open_, high, low, close, volume in rows:
        body_high = max(open_, close)
        body_low = min(open_, close)
        if not is_regular_session(epoch):
            if body_low - low > threshold:
                low = body_low
            if high - body_high > threshold:
                high = body_high
        cleaned.append(ChartRow(epoch, open_, max(high, body_high), min(low, body_low), close, volume))
    return cleaned


def _price_key(value: float) -> float:
    return round(value, 8)


def _clean_futures_intraday_wicks(
    rows: Sequence[ChartRowValues],
    request: ChartRequest,
) -> list[ChartRowValues]:
    if not request.futures or not is_intraday(request.timeframe):
        return list(rows)
    ranges = sorted(max(0.0, row[2] - row[3]) for row in rows if row[2] >= row[3])
    typical_range = ranges[len(ranges) // 2] if ranges else 0.0
    threshold = max(abs(rows[-1][4]) * 0.0004, typical_range * FUTURES_STALE_WICK_RANGE_MULTIPLE, 0.0001)
    high_counts: dict[float, int] = {}
    low_counts: dict[float, int] = {}
    high_flags: dict[float, int] = {}
    low_flags: dict[float, int] = {}

    for epoch, open_, high, low, close, _ in rows:
        if _futures_globex_session_key(epoch) is None:
            continue
        body_high = max(open_, close)
        body_low = min(open_, close)
        high_key = _price_key(high)
        low_key = _price_key(low)
        high_counts[high_key] = high_counts.get(high_key, 0) + 1
        low_counts[low_key] = low_counts.get(low_key, 0) + 1
        if high - body_high > threshold:
            high_flags[high_key] = high_flags.get(high_key, 0) + 1
        if body_low - low > threshold:
            low_flags[low_key] = low_flags.get(low_key, 0) + 1

    stale_highs = {
        value for value, count in high_counts.items()
        if count >= FUTURES_STALE_EXTREME_MIN_REPEATS and high_flags.get(value, 0) >= FUTURES_STALE_EXTREME_MIN_FLAGS
    }
    stale_lows = {
        value for value, count in low_counts.items()
        if count >= FUTURES_STALE_EXTREME_MIN_REPEATS and low_flags.get(value, 0) >= FUTURES_STALE_EXTREME_MIN_FLAGS
    }
    if not stale_highs and not stale_lows:
        return list(rows)

    cleaned: list[ChartRowValues] = []
    for epoch, open_, high, low, close, volume in rows:
        body_high = max(open_, close)
        body_low = min(open_, close)
        if _futures_globex_session_key(epoch) is not None:
            if _price_key(high) in stale_highs and high > body_high:
                high = body_high
            if _price_key(low) in stale_lows and low < body_low:
                low = body_low
        cleaned.append(ChartRow(epoch, open_, max(high, body_high), min(low, body_low), close, volume))
    return cleaned


def _chart_x_positions(count: int, left: int, plot_w: int) -> list[int]:
    if count < SPARSE_CHART_MIN_BARS:
        step = min(32, plot_w // SPARSE_CHART_MIN_BARS)
        start = left + plot_w - 1 - step * (count - 1)
        return [start + step * pos for pos in range(count)]
    return [left + round(pos * (plot_w - 1) / max(count - 1, 1)) for pos in range(count)]


def _sma_values(rows: Sequence[ChartRowValues], period: int) -> list[float | None]:
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
    target_steps = 4 if request.timeframe in {"w", "m"} else 5
    step = _nice_step(value / target_steps)
    high_steps = math.ceil(value / step)
    if request.timeframe in {"w", "m"}:
        high_steps = max(high_steps, target_steps)
    high = high_steps * step
    ticks: list[float] = []
    tick = step
    while tick <= high + step / 2:
        ticks.append(tick)
        tick += step
    return high, ticks


def _volume_scale_value(rows: Sequence[ChartRowValues]) -> float:
    return max((row[5] for row in rows), default=0.0)


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
    return stamp.strftime("%y") if stamp.month == 1 else stamp.strftime("%b")[0]


def _x_grid_line_styles(x_ticks: list[tuple[int, str]], quarterly_grid: bool) -> list[tuple[int, bool]]:
    if not quarterly_grid:
        return [(idx, True) for idx, _ in x_ticks]
    return [(idx, position % 3 == 0) for position, (idx, _) in enumerate(x_ticks)]


@lru_cache(maxsize=None)
def _font(size: int, bold: bool = False) -> Any:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in (f"/usr/share/fonts/truetype/dejavu/{name}", name):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=None)
def _date_font(size: int) -> Any:
    for path in (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return _font(size)


def render_price_chart_png(data: ChartData, request: ChartRequest) -> bytes:
    # Pillow keeps text crisp without pulling in a full charting framework.

    width, height = DEFAULT_WIDTH * DEFAULT_SCALE_FACTOR, DEFAULT_HEIGHT * DEFAULT_SCALE_FACTOR
    dark = request.theme == "dark"
    intraday = is_intraday(request.timeframe)
    bg = (30, 34, 44) if dark else (250, 250, 250)
    grid = (43, 49, 62) if dark else (214, 218, 226)
    minor_grid = _blend_rgb(grid, bg, 0.52)
    text = (148, 160, 181) if dark else (100, 108, 122)
    strong = (176, 186, 206) if dark else (50, 55, 65)
    if dark:
        up, down = DARK_UP, DARK_DOWN
        line_color = DARK_LINE_COLOR
        vol_up = _blend_rgb(DARK_VOLUME_UP, bg, 0.58)
        vol_down = _blend_rgb(DARK_VOLUME_DOWN, bg, 0.58)
    else:
        up, down = LIGHT_DAILY_UP, LIGHT_DAILY_DOWN
        line_color = LIGHT_LINE_COLOR
        vol_up = _blend_rgb(up, bg, LIGHT_DAILY_VOLUME_ALPHA)
        vol_down = _blend_rgb(down, bg, LIGHT_DAILY_VOLUME_ALPHA)
    sma_alpha = 0.82 if dark else 0.72
    sma_colors = {period: _blend_rgb(SMA_COLORS[period], bg, sma_alpha) for period in SMA_PERIODS}

    header_font = _font(18)
    label_font = _font(17, True)
    axis_font = _font(18)
    date_axis_font = _date_font(11)
    small_font = _font(14)
    badge_font = _font(17, True)
    sma_font = _font(16)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    left, right, top, bottom = 60, CHART_RIGHT_MARGIN, 34, 30
    volume_h, gap = 68, 8
    vol_top, vol_bottom = height - bottom - volume_h, height - bottom
    price_top, price_bottom = top, vol_top - gap
    plot_right = width - right
    plot_w = plot_right - left
    all_rows = _clean_futures_intraday_wicks(
        _clean_stock_extended_wicks(_chart_rows(data, request), request),
        request,
    )
    indexes = _visible_indexes(all_rows, request)
    rows = [all_rows[i] for i in indexes]
    base = rows[0][4]
    if request.scale == "percentage" and base == 0:
        raise NoChartData(f"Chart data has a zero starting price for `{request.ticker}`, so percent scale won't work.")
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
    candles = [
        (index, epoch, scaled(open_), scaled(high), scaled(low), scaled(close), volume)
        for index, (epoch, open_, high, low, close, volume) in zip(indexes, rows, strict=True)
    ]
    scale_values = [
        value
        for _, _, open_, high, low, close, _ in candles
        for value in (open_, high, low, close)
    ]
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
    vol_axis_high, vol_ticks = _volume_axis(_volume_scale_value(rows), request)

    x_positions = _chart_x_positions(len(candles), left, plot_w)
    if intraday and request.futures:
        session_bands = _futures_globex_session_bands(rows, x_positions, left, plot_right)
    elif intraday and not request.crypto_market:
        session_bands = _stock_extended_session_bands(rows, x_positions, left, plot_right)
    else:
        session_bands = []
    session_fills = {
        "pre": (34, 42, 58) if dark else (236, 244, 252),
        "after": (45, 39, 53) if dark else (250, 240, 247),
        "overnight": (43, 40, 58) if dark else (244, 240, 250),
        "globex": (34, 42, 58) if dark else (236, 244, 252),
    }
    session_boundary = (61, 76, 101) if dark else (184, 195, 211)
    session_text = (108, 126, 158) if dark else (112, 124, 143)
    session_labels = {"pre": "PRE", "after": "AH", "overnight": "ON", "globex": "GLOBEX"}

    def x_at(i: int) -> int:
        return x_positions[i]

    def price_y_at(value: float) -> float:
        return price_bottom - (value - low) * (price_bottom - price_top) / (high - low)

    def y_at(value: float) -> int:
        return round(price_y_at(value))

    draw_bottom = vol_bottom

    def clip_price_segment(
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        x1, y1 = start
        x2, y2 = end
        if y1 == y2:
            return (start, end) if price_top <= y1 <= draw_bottom else None
        if (y1 < price_top and y2 < price_top) or (y1 > draw_bottom and y2 > draw_bottom):
            return None

        def at_y(bound: int) -> tuple[float, float]:
            ratio = (bound - y1) / (y2 - y1)
            return x1 + (x2 - x1) * ratio, float(bound)

        if y1 < price_top:
            start = at_y(price_top)
        elif y1 > draw_bottom:
            start = at_y(draw_bottom)
        if y2 < price_top:
            end = at_y(price_top)
        elif y2 > draw_bottom:
            end = at_y(draw_bottom)
        return start, end

    def dashed(
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: tuple[int, int, int] = grid,
        dash: int = 8,
        gap: int = 6,
    ) -> None:
        if y1 == y2:
            x = x1
            while x < x2:
                draw.line((x, y1, min(x + dash, x2), y2), fill=color, width=1)
                x += dash + gap
        else:
            y = y1
            while y < y2:
                draw.line((x1, y, x2, min(y + dash, y2)), fill=color, width=1)
                y += dash + gap

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
                x_ticks.append((pos, _month_tick_label(row[0], span)))
                previous_month = month
        max_x_ticks = 48 if span >= 400 * 86400 else 20
        if not 4 <= len(x_ticks) <= max_x_ticks:
            x_ticks = []
    else:
        x_ticks = []
    if not x_ticks:
        x_ticks = [
            (round(step * (len(rows) - 1) / 5), _date_label(rows[round(step * (len(rows) - 1) / 5)][0], intraday, span))
            for step in range(6)
        ]

    drawn_sparse_labels: set[str] = set()
    last_label_right = -9999
    quarterly_grid = not intraday and span >= 400 * 86400 and len(x_ticks) >= 9
    for idx, is_major in _x_grid_line_styles(x_ticks, quarterly_grid):
        x = x_at(idx)
        dashed(x, price_top, x, vol_bottom, grid if is_major else minor_grid, 8 if is_major else 6, 6 if is_major else 10)
    for idx, label in x_ticks:
        x = x_at(idx)
        if len(rows) < SPARSE_CHART_MIN_BARS:
            if label in drawn_sparse_labels:
                continue
            drawn_sparse_labels.add(label)
        label_w = draw.textbbox((0, 0), label, font=date_axis_font)[2]
        label_x = max(0, min(plot_right - label_w, x - label_w // 2))
        if label_x < last_label_right + 8:
            continue
        draw.text((label_x, vol_bottom + 4), label, fill=text, font=date_axis_font)
        last_label_right = label_x + label_w

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

    candle_w = max(2, min(8, round(plot_w / max(len(candles), 1) * 0.68)))

    def bar_bounds(x: int) -> tuple[int, int]:
        left = x - candle_w // 2
        return left, left + candle_w - 1

    close_points: list[tuple[int, int]] = []
    for pos, (_, _, open_value, high_value, low_value, close_value, volume) in enumerate(candles):
        x = x_at(pos)
        color = up if close_value >= open_value else down
        vh = min(vol_bottom - vol_top, round((volume / vol_axis_high) * (vol_bottom - vol_top)))
        bar_left, bar_right = bar_bounds(x)
        draw.rectangle(
            (bar_left, vol_bottom - vh, bar_right, vol_bottom),
            fill=vol_up if close_value >= open_value else vol_down,
        )
        if request.chart_type == "l":
            close_points.append((x, y_at(close_value)))
            continue
        open_y = y_at(open_value)
        high_y = y_at(high_value)
        low_y = y_at(low_value)
        close_y = y_at(close_value)
        draw.line((x, high_y, x, low_y), fill=color, width=1)
        draw.rectangle((bar_left, min(open_y, close_y), bar_right, max(open_y, close_y)), fill=color)
    if close_points:
        draw.line(close_points, fill=line_color, width=2, joint="curve")

    scale = SMA_SUPERSAMPLE
    line_width = max(1, round(SMA_LINE_WIDTH * scale))
    for period in SMA_PERIODS:
        values = smas[period]
        points = [
            (float(x_at(pos)), price_y_at(scaled(value)))
            for pos, i in enumerate(indexes)
            if (value := values[i]) is not None
        ]
        segments = [
            clipped
            for start, end in pairwise(points)
            if (clipped := clip_price_segment(start, end)) is not None
        ]
        if not segments:
            continue
        # Supersample only the line's own bounding box, not the whole plot.
        xs = [x for segment in segments for x, _ in segment]
        ys = [y for segment in segments for _, y in segment]
        box_left = max(0, math.floor(min(xs)) - SMA_MASK_MARGIN)
        box_top = max(0, math.floor(min(ys)) - SMA_MASK_MARGIN)
        box_right = min(width, math.ceil(max(xs)) + SMA_MASK_MARGIN + 1)
        box_bottom = min(height, math.ceil(max(ys)) + SMA_MASK_MARGIN + 1)
        mask = Image.new("L", ((box_right - box_left) * scale, (box_bottom - box_top) * scale), 0)
        mask_draw = ImageDraw.Draw(mask)
        for (x1, y1), (x2, y2) in segments:
            mask_draw.line(
                (
                    round((x1 - box_left) * scale),
                    round((y1 - box_top) * scale),
                    round((x2 - box_left) * scale),
                    round((y2 - box_top) * scale),
                ),
                fill=255,
                width=line_width,
            )
        image.paste(sma_colors[period], (box_left, box_top, box_right, box_bottom), mask.reduce(scale))

    last_idx = indexes[-1]
    last = all_rows[last_idx]
    prev = data.previous_close or all_rows[max(0, last_idx - 1)][4]
    change = (data.change if data.change is not None else last[4] - prev) or 0.0
    pct = (data.change_percent if data.change_percent is not None else (change / prev * 100 if prev else 0.0)) or 0.0
    change_color = up if change >= 0 else down
    candle_color = up if last[4] >= last[1] else down
    date = dt.datetime.fromtimestamp(last[0], dt.timezone.utc).strftime("%b %d")
    change_label = f"{change:+.2f} ({pct:+.2f}%)"

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
            draw.text((8, 46 + row * 22), f"SMA {period} · {_fmt(value)}", fill=sma_colors[period], font=sma_font)
    if period_shell:
        side_font = _font(14)
        label = request.timeframe_label.upper()
        label_img = Image.new("RGBA", (220, 42), (0, 0, 0, 0))
        label_draw = ImageDraw.Draw(label_img)
        label_draw.text((0, 0), label, fill=(*text, 255), font=side_font)
        label_img = label_img.crop(label_img.getbbox() or (0, 0, 1, 1)).rotate(90, expand=True)
        image.paste(label_img, (18, price_top + (price_bottom - price_top - label_img.height) // 2), label_img)

    last_scaled = scaled(last[4])
    badge_text = _axis_label(last_scaled, request)
    text_box = draw.textbbox((0, 0), badge_text, font=badge_font)
    text_w, text_h = text_box[2] - text_box[0], text_box[3] - text_box[1]
    pad_x, pad_y = 2, 1
    badge_w, badge_h = text_w + pad_x * 2, text_h + pad_y * 2
    bx = min(width - badge_w - 4, plot_right + 8)
    by = max(price_top, min(price_bottom - badge_h, y_at(last_scaled) - badge_h // 2))
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=2, fill=(245, 211, 65))
    draw.text(
        (bx + pad_x - text_box[0], by + (badge_h - text_h) // 2 - text_box[1]),
        badge_text,
        fill=(22, 24, 30),
        font=badge_font,
    )
    for value in vol_ticks:
        y = vol_bottom - round((value / vol_axis_high) * (vol_bottom - vol_top))
        draw.text((6, y - 9), _fmt_volume(value), fill=text, font=small_font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _fmt(value: Any, suffix: str = "") -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}{suffix}" if abs(number) < 1000 else f"{number:,.0f}{suffix}"


def _fmt_signed(value: Any, suffix: str = "") -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    return ("+" if number > 0 else "") + _fmt(number, suffix)


def _fmt_volume(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    for suffix, scale in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= scale:
            scaled = number / scale
            if suffix != "B" and abs(scaled) >= 100:
                return f"{scaled:.0f}{suffix}"
            return f"{scaled:.1f}{suffix}"
    return f"{number:,.0f}"


def _header_volume_label(row: ChartRowValues, request: ChartRequest) -> str:
    if request.crypto_market:
        return _fmt_volume(row[5])
    if (
        is_intraday(request.timeframe)
        and row[5] == 0
        and (request.futures or not is_regular_session(row[0]))
    ):
        return "n/a"
    return _fmt_volume(row[5])


def _quote_time_label(data: ChartData) -> str | None:
    timestamp = data.last_time
    if timestamp is None and data.rows:
        timestamp = data.rows[-1].epoch
    if timestamp is None:
        return None
    stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(MARKET_TIME_ZONE)
    return stamp.strftime("%I:%M %p ET").lstrip("0")


def _quote_display_name(data: ChartData) -> str:
    ticker = data.ticker.upper()
    if data.futures and ticker in FUTURES_DISPLAY_NAMES:
        return FUTURES_DISPLAY_NAMES[ticker]
    return data.name or data.ticker or "quote"


def quote_description(data: ChartData) -> str:
    metric_parts = [f"Last **{_fmt(data.last_close)}**"]
    if data.change is not None:
        metric_parts.append(f"**{_fmt_signed(data.change)}** ({_fmt_signed(data.change_percent, '%')})")
    time_label = _quote_time_label(data)
    if time_label:
        metric_parts.append(time_label)
    return f"{_quote_display_name(data)}\n" + " · ".join(metric_parts)
