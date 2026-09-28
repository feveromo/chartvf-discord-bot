"""Yahoo Finance charts: indexes, unmapped futures roots, and daily+ stock charts."""

import time
from dataclasses import replace
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp

from charting import (
    TIMEFRAMES,
    ChartData,
    ChartRequest,
    NoChartData,
    aggregate_chart_data,
    is_intraday,
    native_timeframe,
    normalize_chart_rows,
    safe_float,
)
from market_http import (
    PROVIDER_ERRORS,
    MarketDataHTTPError,
    MarketDataProviderError,
    background,
    request_json,
)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
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
YAHOO_CRYPTO_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "DOGE": "DOGE-USD",
}
# Native Yahoo intervals; other intraday timeframes are aggregated from these.
YAHOO_INTERVALS = {
    "d": "1d",
    "w": "1wk",
    "m": "1mo",
    "i1": "1m",
    "i2": "2m",
    "i5": "5m",
    "i15": "15m",
    "i30": "30m",
    "h": "60m",
    "h4": "4h",
}
INTRADAY_RANGES = {
    "i1": "5d",
    "i2": "5d",
    "i3": "5d",
    "i5": "5d",
    "i10": "5d",
    "i15": "5d",
    "i30": "1mo",
    "h": "1mo",
    "h2": "3mo",
    "h4": "1y",
}
# Fetch enough history behind each visible range to seed SMA200.
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


def yahoo_chart_symbol(request: ChartRequest) -> str:
    if request.futures:
        return f"{request.ticker}=F"
    return YAHOO_CRYPTO_SYMBOLS.get(
        request.ticker,
        YAHOO_SYMBOL_ALIASES.get(request.ticker, request.ticker),
    )


def _chart_range(request: ChartRequest) -> str:
    if is_intraday(request.timeframe):
        return INTRADAY_RANGES[request.timeframe]
    if request.timeframe == "w":
        return WEEKLY_SMA_FETCH_RANGES.get(request.date_range, "10y")
    return DAILY_SMA_FETCH_RANGES.get(request.date_range, "2y")


def yahoo_chart_url(
    request: ChartRequest,
    *,
    chart_range: str | None = None,
    include_prepost: bool | None = None,
) -> str:
    interval = YAHOO_INTERVALS[native_timeframe(request.timeframe, YAHOO_INTERVALS)]
    if include_prepost is None:
        include_prepost = not request.futures and is_intraday(request.timeframe)
    params = {
        "interval": interval,
        "includePrePost": "true" if include_prepost else "false",
        "events": "div,splits",
    }
    if chart_range is None and request.timeframe == "m":
        params["period1"] = "0"
        params["period2"] = str(int(time.time()))
    else:
        params["range"] = chart_range or _chart_range(request)
    symbol = quote(yahoo_chart_symbol(request), safe="=^")
    return CHART_URL.format(symbol=symbol) + "?" + urlencode(params)


def _chart_result(data: Any, ticker: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MarketDataProviderError("Market data provider returned malformed data")
    chart = data.get("chart") or {}
    if not isinstance(chart, dict):
        raise MarketDataProviderError("Market data provider returned malformed data")
    error = chart.get("error")
    if error:
        code = str(error.get("code") if isinstance(error, dict) else error).lower()
        description = str(
            error.get("description") if isinstance(error, dict) else ""
        ).lower()
        if (
            "not found" in code
            or "not found" in description
            or "no data" in description
        ):
            raise NoChartData(f"No chart data found for `{ticker}`.")
        raise MarketDataProviderError("Market data provider returned an error")
    results = chart.get("result") or []
    if not results or not isinstance(results[0], dict):
        raise NoChartData(f"No chart data found for `{ticker}`.")
    return results[0]


async def _fetch_chart_result(
    session: aiohttp.ClientSession, url: str, ticker: str
) -> dict[str, Any]:
    try:
        return _chart_result(await request_json(session, url), ticker)
    except MarketDataHTTPError as error:
        if error.status == 404:
            raise NoChartData(f"No chart data found for `{ticker}`.") from error
        raise


def _quote(result: dict[str, Any]) -> dict[str, Any]:
    quotes = (result.get("indicators") or {}).get("quote") or [{}]
    return quotes[0] if isinstance(quotes[0], dict) else {}


async def fetch_daily_previous_close(
    session: aiohttp.ClientSession, request: ChartRequest
) -> float | None:
    daily = replace(request, timeframe="d", timeframe_label="daily", date_range="")
    try:
        result = await _fetch_chart_result(
            session, yahoo_chart_url(daily, chart_range="5d"), request.ticker
        )
    except (*PROVIDER_ERRORS, NoChartData):
        return None
    closes = [
        close
        for close in (safe_float(value) for value in _quote(result).get("close") or [])
        if close is not None
    ]
    return closes[-2] if len(closes) > 1 else None


async def fetch_current_day_intraday_quote(
    session: aiohttp.ClientSession, request: ChartRequest
) -> dict[str, Any] | None:
    minute = replace(request, timeframe="i1", timeframe_label="1 min", date_range="")
    url = yahoo_chart_url(minute, chart_range="1d", include_prepost=False)
    try:
        return _quote(await _fetch_chart_result(session, url, request.ticker))
    except (*PROVIDER_ERRORS, NoChartData):
        return None


def has_close_only_latest_ohlc(quote: dict[str, Any]) -> bool:
    """Yahoo sometimes reports today's daily bar as close-only (O/H/L = 0)."""
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    row_count = min(map(len, (opens, highs, lows, closes)))
    if row_count == 0:
        return False
    last = row_count - 1
    open_, high, low = (safe_float(values[last]) for values in (opens, highs, lows))
    close = safe_float(closes[last])
    return close is not None and close > 0 and open_ == high == low == 0


def patch_close_only_latest_ohlc(
    quote: dict[str, Any], intraday_quote: dict[str, Any]
) -> dict[str, Any]:
    """Fill a close-only latest daily bar's O/H/L from today's 1-minute bars."""
    if not has_close_only_latest_ohlc(quote):
        return quote

    intraday_columns = [
        intraday_quote.get(key) or [] for key in ("open", "high", "low", "close")
    ]
    intraday_rows: list[tuple[float, float, float, float]] = []
    for values in zip(*intraday_columns, strict=False):
        open_, high, low, close = (safe_float(value) for value in values)
        if open_ is None or high is None or low is None or close is None or high < low:
            continue
        if close > 0 and open_ == high == low == 0:
            continue
        intraday_rows.append((open_, high, low, close))
    if not intraday_rows:
        return quote

    last = min(len(quote.get(key) or []) for key in ("open", "high", "low", "close")) - 1
    patched = dict(quote)
    for key, value in (
        ("open", intraday_rows[0][0]),
        ("high", max(row[1] for row in intraday_rows)),
        ("low", min(row[2] for row in intraday_rows)),
    ):
        values = list(quote.get(key) or [])
        values[last] = value
        patched[key] = values
    return patched


def stock_previous_close(
    meta: dict[str, Any], closes: list[Any], request: ChartRequest
) -> float | None:
    """The previous session's close, for the day-change figure.

    Never `chartPreviousClose`: that is the close before the chart window
    (10 years back on a weekly chart), not yesterday's close. None makes the
    caller look up the previous daily close instead.
    """
    valid_closes = [
        close for close in (safe_float(value) for value in closes) if close is not None
    ]
    if request.timeframe == "d" and len(valid_closes) > 1:
        # While today's close is pending, the last valid close is yesterday's.
        return valid_closes[-2] if safe_float(closes[-1]) is not None else valid_closes[-1]
    return safe_float(meta.get("previousClose"))


def latest_quote_price_time(
    meta: dict[str, Any],
    dates: list[Any],
    closes: list[Any],
    request: ChartRequest,
) -> tuple[float | None, int | None]:
    latest_close = next(
        (close for close in (safe_float(value) for value in reversed(closes)) if close is not None),
        None,
    )
    latest_time = int(dates[-1]) if dates else None
    regular_price = safe_float(meta.get("regularMarketPrice"))
    regular_time_float = safe_float(meta.get("regularMarketTime"))
    regular_time = int(regular_time_float) if regular_time_float is not None else None
    if (
        not request.futures
        and is_intraday(request.timeframe)
        and latest_close is not None
        and latest_time is not None
        and (regular_time is None or latest_time > regular_time)
    ):
        return latest_close, latest_time
    return (regular_price if regular_price is not None else latest_close), (regular_time or latest_time)


async def fetch_yahoo_chart_data(
    session: aiohttp.ClientSession, request: ChartRequest
) -> ChartData:
    url = yahoo_chart_url(request)
    reference_close: float | None = None
    if request.futures and request.timeframe != "d":
        # Futures intraday compare against the prior daily settlement.
        async with background(fetch_daily_previous_close(session, request)) as reference:
            result = await _fetch_chart_result(session, url, request.ticker)
            reference_close = await reference
    else:
        result = await _fetch_chart_result(session, url, request.ticker)

    meta = result.get("meta") or {}
    quote = _quote(result)
    dates = result.get("timestamp") or []
    closes = quote.get("close") or []
    last, last_time = latest_quote_price_time(meta, dates, closes, request)
    previous = reference_close or stock_previous_close(meta, closes, request)
    if previous is None and not request.futures and request.timeframe != "d":
        previous = await fetch_daily_previous_close(session, request)
    if request.timeframe == "d" and not request.futures and has_close_only_latest_ohlc(quote):
        intraday_quote = await fetch_current_day_intraday_quote(session, request)
        if intraday_quote is not None:
            quote = patch_close_only_latest_ohlc(quote, intraday_quote)

    native = native_timeframe(request.timeframe, YAHOO_INTERVALS)
    data = ChartData(
        ticker=request.ticker,
        name=str(meta.get("shortName") or meta.get("longName") or request.ticker),
        rows=normalize_chart_rows(
            dates,
            quote.get("open") or [],
            quote.get("high") or [],
            quote.get("low") or [],
            quote.get("close") or [],
            quote.get("volume") or [],
            last_close=last,
        ),
        last_close=last,
        last_time=last_time,
        previous_close=previous,
        futures=request.futures,
        source_interval_seconds=TIMEFRAMES[native].seconds,
    )
    return aggregate_chart_data(data, request)
