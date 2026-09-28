"""TradingView intraday candles over its public chart websocket.

Used for futures (delayed continuous contracts) and as the stock fallback
when Webull is unavailable (24-hour session candles).
"""

import asyncio
import json
import logging
import secrets
from typing import Any

import aiohttp

from charting import (
    TIMEFRAMES,
    ChartData,
    ChartRequest,
    ChartRow,
    NoChartData,
    is_intraday,
    is_regular_session,
    safe_float,
)
from market_http import RETRYABLE_STATUSES, MarketDataProviderError

LOGGER = logging.getLogger("chartvf.tradingview")

WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F"
WS_ORIGIN = "https://www.tradingview.com"
RESPONSE_TIMEOUT_SECONDS = 10
HISTORY_BARS = 400
TRADINGVIEW_FUTURES_SYMBOLS = {
    "ES": "CME_MINI:ES1!",
    "MES": "CME_MINI:MES1!",
    "NQ": "CME_MINI:NQ1!",
    "MNQ": "CME_MINI:MNQ1!",
    "YM": "CBOT_MINI:YM1!",
    "MYM": "CBOT_MINI:MYM1!",
    "RTY": "CME_MINI:RTY1!",
    "M2K": "CME_MINI:M2K1!",
    "CL": "NYMEX:CL1!",
    "GC": "COMEX:GC1!",
    "6E": "CME:6E1!",
}
# TradingView serves every intraday timeframe natively, in minutes.
RESOLUTIONS = {
    code: str(timeframe.seconds // 60)
    for code, timeframe in TIMEFRAMES.items()
    if is_intraday(code)
}
CLOSED_MESSAGE_TYPES = frozenset(
    {
        aiohttp.WSMsgType.CLOSE,
        aiohttp.WSMsgType.CLOSED,
        aiohttp.WSMsgType.CLOSING,
        aiohttp.WSMsgType.ERROR,
    }
)


def _frame(payload: str) -> str:
    return f"~m~{len(payload)}~m~{payload}"


def _message(method: str, params: list[Any]) -> str:
    return _frame(json.dumps({"m": method, "p": params}, separators=(",", ":")))


def _frame_payloads(data: str) -> list[str]:
    # A websocket message carries one or more `~m~<length>~m~<payload>` frames.
    return data.split("~m~")[2::2]


def _symbol_spec(symbol: str, session: str) -> str:
    spec = {"symbol": symbol, "adjustment": "splits", "session": session}
    return "=" + json.dumps(spec, separators=(",", ":"))


def _store_bars(params: list[Any], series: dict[str, dict[int, ChartRow]]) -> None:
    if len(params) < 2 or not isinstance(params[1], dict):
        return
    for series_id, rows_by_epoch in series.items():
        update = params[1].get(series_id)
        if not isinstance(update, dict):
            continue
        for raw_bar in update.get("s") or []:
            values = raw_bar.get("v") if isinstance(raw_bar, dict) else None
            if not isinstance(values, list) or len(values) < 6:
                continue
            epoch, open_, high, low, close, volume = (safe_float(value) for value in values[:6])
            if (
                epoch is None
                or open_ is None
                or high is None
                or low is None
                or close is None
                or high < low
            ):
                continue
            rows_by_epoch[int(epoch)] = ChartRow(int(epoch), open_, high, low, close, volume or 0.0)


def _previous_close(
    last_epoch: int, daily_rows: list[ChartRow], futures: bool
) -> float | None:
    if futures:
        return daily_rows[-2].close if len(daily_rows) > 1 else None
    # During the regular session today's daily bar is still forming, so compare
    # with yesterday's close; outside it, with the latest regular close.
    if is_regular_session(last_epoch) and len(daily_rows) > 1:
        return daily_rows[-2].close
    return daily_rows[-1].close if daily_rows else None


async def fetch_tradingview_chart_data(
    session: aiohttp.ClientSession,
    request: ChartRequest,
) -> ChartData:
    for attempt in range(2):
        try:
            return await _fetch_tradingview_chart_data(session, request)
        except aiohttp.WSServerHandshakeError as error:
            # TradingView sheds load with 429/5xx handshakes; one retry usually lands.
            if attempt or error.status not in RETRYABLE_STATUSES:
                raise
            LOGGER.info("tradingview handshake retry status=%s", error.status)
    raise AssertionError("unreachable")


async def _fetch_tradingview_chart_data(
    session: aiohttp.ClientSession,
    request: ChartRequest,
) -> ChartData:
    symbol = (
        TRADINGVIEW_FUTURES_SYMBOLS.get(request.ticker)
        if request.futures
        else request.ticker.replace("-", ".")
    )
    resolution = RESOLUTIONS.get(request.timeframe)
    if symbol is None or resolution is None:
        raise NoChartData(f"No accurate intraday data found for `{request.ticker}`.")

    chart_session = f"cs_{secrets.token_hex(6)}"
    # s1: the requested candles. d1: the last 3 daily bars, for the previous close.
    series: dict[str, dict[int, ChartRow]] = {"s1": {}, "d1": {}}
    completed: set[str] = set()
    daily_requested = False
    resolved_name = request.ticker

    async with session.ws_connect(WS_URL, origin=WS_ORIGIN, heartbeat=20) as websocket:

        async def send(method: str, params: list[Any]) -> None:
            await websocket.send_str(_message(method, params))

        await send("set_auth_token", ["unauthorized_user_token"])
        await send("chart_create_session", [chart_session, ""])
        await send("switch_timezone", [chart_session, "Etc/UTC"])
        await send(
            "resolve_symbol",
            [chart_session, "symbol_1", _symbol_spec(symbol, "regular" if request.futures else "24h")],
        )
        await send(
            "create_series",
            [chart_session, "s1", "s1", "symbol_1", resolution, HISTORY_BARS, ""],
        )

        async with asyncio.timeout(RESPONSE_TIMEOUT_SECONDS):
            async for message in websocket:
                if message.type in CLOSED_MESSAGE_TYPES:
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                for raw_payload in _frame_payloads(message.data):
                    if raw_payload.startswith("~h~"):
                        await websocket.send_str(_frame(raw_payload))  # heartbeat echo
                        continue
                    try:
                        payload = json.loads(raw_payload)
                    except ValueError as error:
                        raise MarketDataProviderError(
                            "Market data provider returned malformed data"
                        ) from error
                    if not isinstance(payload, dict):
                        continue
                    method = payload.get("m")
                    params = payload.get("p") or []
                    if method == "symbol_resolved":
                        if len(params) > 2 and isinstance(params[2], dict):
                            resolved_name = str(
                                params[2].get("description")
                                or params[2].get("short_description")
                                or request.ticker
                            )
                    elif method == "symbol_error":
                        raise NoChartData(f"No chart data found for `{request.ticker}`.")
                    elif method in {"critical_error", "protocol_error"}:
                        raise MarketDataProviderError("Market data provider returned an error")
                    elif method == "timescale_update":
                        _store_bars(params, series)
                    elif method == "series_completed" and len(params) > 1:
                        series_id = str(params[1])
                        if series_id in series:
                            completed.add(series_id)
                        if series_id == "s1" and not daily_requested:
                            # Swap the finished series for 3 regular-session daily bars.
                            await send("remove_series", [chart_session, "s1"])
                            daily_symbol = "symbol_1"
                            if not request.futures:
                                daily_symbol = "symbol_daily"
                                await send(
                                    "resolve_symbol",
                                    [chart_session, daily_symbol, _symbol_spec(symbol, "regular")],
                                )
                            await send(
                                "create_series",
                                [chart_session, "d1", "d1", daily_symbol, "1D", 3, ""],
                            )
                            daily_requested = True
                if completed == series.keys():
                    break

    if completed != series.keys():
        raise MarketDataProviderError("Market data provider ended the chart response early")

    rows = tuple(series["s1"][epoch] for epoch in sorted(series["s1"]))
    daily_rows = [series["d1"][epoch] for epoch in sorted(series["d1"])]
    if len(rows) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")

    return ChartData(
        ticker=request.ticker,
        name=resolved_name,
        rows=rows,
        last_close=rows[-1].close,
        last_time=rows[-1].epoch,
        previous_close=_previous_close(rows[-1].epoch, daily_rows, request.futures),
        market_label="TradingView delayed" if request.futures else "TradingView 24h",
        futures=request.futures,
        source_interval_seconds=TIMEFRAMES[request.timeframe].seconds,
    )
