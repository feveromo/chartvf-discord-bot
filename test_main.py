import asyncio
import json
import time
from collections.abc import Callable
from typing import Any, cast

import aiohttp

from charting import ChartRequest, NoChartData
from crypto import _fetch_binance_klines, fetch_crypto_chart_data
from market_data import fetch_market_chart_data
from market_http import MarketDataHTTPError, request_json
from webull import _resolution_cache


class FakeResponse:
    def __init__(
        self, status: int, payload: Any, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, *, content_type: None = None) -> Any:
        del content_type
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeWebSocketMessage:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, data: str) -> None:
        self.data = data


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = [FakeWebSocketMessage(message) for message in messages]
        self.sent: list[str] = []

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> FakeWebSocketMessage:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send_str(self, message: str) -> None:
        self.sent.append(message)


Router = Callable[[str, dict[str, Any] | None], FakeResponse]


class FakeSession:
    def __init__(
        self, router: Router, websocket_messages: list[str] | None = None
    ) -> None:
        self.router = router
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.websocket = FakeWebSocket(websocket_messages or [])

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        del headers
        copied_params = dict(params) if params is not None else None
        self.calls.append((url, copied_params))
        return self.router(url, copied_params)

    def ws_connect(self, _url: str, *, origin: str, heartbeat: int) -> FakeWebSocket:
        del origin, heartbeat
        return self.websocket


def session_for(
    router: Router,
    websocket_messages: list[str] | None = None,
) -> tuple[aiohttp.ClientSession, FakeSession]:
    fake = FakeSession(router, websocket_messages)
    return cast(aiohttp.ClientSession, fake), fake


def tradingview_frame(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"~m~{len(encoded)}~m~{encoded}"

def tradingview_chart_messages(
    primary_rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
) -> list[str]:
    return [
        tradingview_frame(
            {
                "m": "timescale_update",
                "p": ["chart", {"s1": {"s": primary_rows}}],
            }
        )
        + tradingview_frame({"m": "series_completed", "p": ["chart", "s1"]}),
        tradingview_frame(
            {
                "m": "timescale_update",
                "p": ["chart", {"d1": {"s": daily_rows}}],
            }
        )
        + tradingview_frame({"m": "series_completed", "p": ["chart", "d1"]}),
    ]


def yahoo_payload(
    *,
    closes: list[float],
    previous_close: float | None,
    interval: str = "5m",
    name: str = "Test instrument",
) -> dict[str, Any]:
    start = 1_780_000_000
    step = 86400 if interval == "1d" else 300
    timestamps = [start + index * step for index in range(len(closes))]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "shortName": name,
                        "previousClose": previous_close,
                        "regularMarketPrice": closes[-1],
                        "regularMarketTime": timestamps[-1],
                        "dataGranularity": interval,
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [close - 0.5 for close in closes],
                                "high": [close + 1 for close in closes],
                                "low": [close - 1 for close in closes],
                                "close": closes,
                                "volume": [1000 for _ in closes],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        },
    }


async def test_retry_once() -> None:
    responses = [
        FakeResponse(503, {}, {"Retry-After": "0"}),
        FakeResponse(200, {"ok": True}),
    ]
    session, fake = session_for(lambda _url, _params: responses.pop(0))
    assert await request_json(session, "https://example.test/data") == {"ok": True}
    assert len(fake.calls) == 2


async def test_non_retryable_statuses_fail_once_and_preserve_no_data() -> None:
    session, fake = session_for(lambda _url, _params: FakeResponse(451, {}))
    try:
        await request_json(session, "https://example.test/restricted")
    except MarketDataHTTPError as error:
        assert error.status == 451
    else:
        raise AssertionError("HTTP 451 should fail without retrying")
    assert len(fake.calls) == 1

    missing_session, missing_fake = session_for(
        lambda _url, _params: FakeResponse(404, {})
    )
    try:
        await fetch_market_chart_data(
            missing_session, ChartRequest("MISSING", "d", "daily")
        )
    except NoChartData:
        pass
    else:
        raise AssertionError("HTTP 404 should remain a no-data result")
    assert len(missing_fake.calls) == 1


async def test_index_alias_uses_yahoo_previous_close_without_daily_fetch() -> None:
    payload = yahoo_payload(closes=[100.0, 102.0, 104.0], previous_close=99.0)
    session, fake = session_for(lambda _url, _params: FakeResponse(200, payload))
    data = await fetch_market_chart_data(session, ChartRequest("SPX", "i5", "5 min"))
    assert data.previous_close == 99.0
    assert data.change == 5.0
    assert data.source_interval_seconds == 300
    assert len(fake.calls) == 1

async def test_weekly_change_uses_previous_daily_close() -> None:
    # Yahoo's weekly/monthly meta has no previousClose, only chartPreviousClose:
    # the close before the 10-year window. The day change must not use it.
    weekly = yahoo_payload(closes=[100.0, 300.0, 340.0], previous_close=None, interval="1wk")
    weekly["chart"]["result"][0]["meta"]["chartPreviousClose"] = 28.0
    daily = yahoo_payload(closes=[330.0, 335.0, 340.0], previous_close=None, interval="1d")

    def route(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        return FakeResponse(200, daily if "interval=1d" in url else weekly)

    session, fake = session_for(route)
    data = await fetch_market_chart_data(session, ChartRequest("AAPL", "w", "weekly"))
    assert data.previous_close == 335.0
    assert data.change == 5.0
    assert len(fake.calls) == 2
    assert "interval=1d" in fake.calls[1][0] and "range=5d" in fake.calls[1][0]


async def test_stock_intraday_uses_tradingview_24h_session() -> None:
    primary_rows = [
        {"i": 2, "v": [1_787_634_000, 263.57, 263.57, 263.20, 263.25, 2964.0]},
        {"i": 0, "v": [1_787_629_500, 263.45, 263.62, 263.43, 263.59, 1423.0]},
        {"i": 1, "v": [1_787_630_400, 263.59, 263.59, 263.49, 263.52, 1038.0]},
    ]
    daily_rows = [
        {"i": 0, "v": [1_787_414_400, 260.0, 264.0, 259.0, 260.11, 1000.0]},
        {"i": 1, "v": [1_787_500_800, 261.0, 263.0, 260.0, 258.63, 1200.0]},
        {"i": 2, "v": [1_787_587_200, 262.0, 264.0, 261.0, 262.07, 200.0]},
    ]
    messages = tradingview_chart_messages(primary_rows, daily_rows)
    messages[0] = tradingview_frame(
        {
            "m": "symbol_resolved",
            "p": ["chart", "symbol_1", {"description": "Amazon.com, Inc."}],
        }
    ) + messages[0]

    def webull_unlisted(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        # Webull doesn't know the symbol, so the bot falls back to TradingView.
        assert url.startswith("https://quotes-gw.webullfintech.com/"), url
        return FakeResponse(200, {"data": []})

    _resolution_cache.clear()
    session, fake = session_for(webull_unlisted, messages)
    data = await fetch_market_chart_data(
        session,
        ChartRequest("AMZN", "i15", "15 min"),
    )

    assert [row.epoch for row in data.rows] == [
        1_787_629_500,
        1_787_630_400,
        1_787_634_000,
    ]
    assert data.name == "Amazon.com, Inc."
    assert data.last_close == 263.25
    assert data.previous_close == 262.07
    assert data.market_label == "TradingView 24h"
    assert not data.futures
    assert data.source_interval_seconds == 900
    assert [url.rsplit("/", 1)[-1] for url, _params in fake.calls] == ["tickers"]
    sent = "".join(fake.websocket.sent)
    assert "AMZN" in sent
    assert "24h" in sent
    assert "symbol_daily" in sent


async def test_futures_uses_tradingview_full_session_and_daily_reference() -> None:
    intraday_rows = [
        {"i": 2, "v": [1_780_001_800, 102.0, 104.0, 101.0, 103.0, 12.0]},
        {"i": 0, "v": [1_780_000_000, 98.0, 101.0, 97.0, 100.0, 8.0]},
        {"i": 1, "v": [1_780_000_900, 100.0, 103.0, 99.0, 102.0, 10.0]},
    ]
    daily_rows = [
        {"i": 0, "v": [1_779_700_000, 94.0, 97.0, 93.0, 95.0, 1000.0]},
        {"i": 1, "v": [1_779_786_400, 95.0, 99.0, 94.0, 98.0, 1200.0]},
        {"i": 2, "v": [1_779_872_800, 98.0, 104.0, 97.0, 103.0, 200.0]},
    ]
    messages = tradingview_chart_messages(intraday_rows, daily_rows)

    def unexpected_http(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        raise AssertionError(f"Unexpected HTTP request: {url}")

    session, fake = session_for(unexpected_http, messages)
    request = ChartRequest("ES", "i15", "15 min", futures=True)
    data = await fetch_market_chart_data(session, request)

    assert [row.epoch for row in data.rows] == [
        1_780_000_000,
        1_780_000_900,
        1_780_001_800,
    ]
    assert [row.close for row in data.rows] == [100.0, 102.0, 103.0]
    assert data.previous_close == 98.0
    assert data.last_close == 103.0
    assert data.change == 5.0
    assert data.source_interval_seconds == 900
    assert data.market_label == "TradingView delayed"
    assert not fake.calls
    assert any("CME_MINI:ES1!" in message for message in fake.websocket.sent)
    assert any('"remove_series"' in message for message in fake.websocket.sent)


async def test_okx_is_primary_for_perp_and_uses_rolling_24h_change() -> None:
    rows = [
        ["1780000600000", "101", "104", "100", "103", "1", "12", "1200", "1"],
        ["1780000300000", "100", "102", "99", "101", "1", "11", "1100", "1"],
        ["1780000000000", "98", "101", "97", "100", "1", "10", "1000", "1"],
    ]

    def route(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        if url.endswith("/history-candles"):
            return FakeResponse(200, {"code": "0", "data": rows})
        if url.endswith("/ticker"):
            return FakeResponse(
                200,
                {
                    "code": "0",
                    "data": [{"last": "105", "open24h": "95", "ts": "1780000900000"}],
                },
            )
        raise AssertionError(f"Unexpected provider URL: {url}")

    session, fake = session_for(route)
    request = ChartRequest("BTC", "i5", "5 min", crypto_market="auto")
    data = await fetch_crypto_chart_data(session, request)
    assert data.market_label == "OKX perp"
    assert data.last_close == 105.0
    assert data.previous_close == 95.0
    assert data.change == 10.0
    assert round(data.change_percent or 0.0, 6) == round(10 / 95 * 100, 6)
    assert [row.epoch for row in data.rows] == sorted(row.epoch for row in data.rows)
    assert all("binance" not in url for url, _params in fake.calls)


async def test_ticker_failure_does_not_fake_candle_change() -> None:
    rows = [
        ["1780000300000", "100", "102", "99", "101", "1", "11", "1100", "1"],
        ["1780000000000", "98", "101", "97", "100", "1", "10", "1000", "1"],
    ]

    def route(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        if url.endswith("/history-candles"):
            return FakeResponse(200, {"code": "0", "data": rows})
        return FakeResponse(451, {})

    session, _fake = session_for(route)
    request = ChartRequest("BTC", "i5", "5 min", crypto_market="auto")
    data = await fetch_crypto_chart_data(session, request)
    assert data.last_close == 101.0
    assert data.previous_close is None
    assert data.change is None
    assert data.change_percent is None


async def test_binance_five_year_history_paginates_through_cutoff() -> None:
    day_ms = 86400 * 1000
    now_ms = int(time.time() * 1000)

    def route(_url: str, params: dict[str, Any] | None) -> FakeResponse:
        assert params is not None
        start = int(params["startTime"])
        limit = int(params["limit"])
        count = min(limit, max(0, (now_ms - start) // day_ms + 1))
        rows = [
            [
                start + index * day_ms,
                "100",
                "102",
                "99",
                "101",
                "10",
                start + (index + 1) * day_ms - 1,
            ]
            for index in range(count)
        ]
        return FakeResponse(200, rows)

    session, fake = session_for(route)
    request = ChartRequest(
        "BTC",
        "d",
        "daily",
        date_range="y5",
        date_range_label="5 years",
        crypto_market="auto",
    )
    rows = await _fetch_binance_klines(session, request, "spot")
    requested_cutoff = now_ms - 1826 * day_ms
    assert rows[0][0] <= requested_cutoff - 198 * day_ms
    assert rows[-1][0] >= now_ms - day_ms
    assert len(fake.calls) >= 3
    assert len({int(row[0]) for row in rows}) == len(rows)


async def run_tests() -> None:
    await test_retry_once()
    await test_non_retryable_statuses_fail_once_and_preserve_no_data()
    await test_index_alias_uses_yahoo_previous_close_without_daily_fetch()
    await test_weekly_change_uses_previous_daily_close()
    await test_stock_intraday_uses_tradingview_24h_session()
    await test_futures_uses_tradingview_full_session_and_daily_reference()
    await test_okx_is_primary_for_perp_and_uses_rolling_24h_change()
    await test_ticker_failure_does_not_fake_candle_change()
    await test_binance_five_year_history_paginates_through_cutoff()


if __name__ == "__main__":
    asyncio.run(run_tests())
    print("test_main ok")
