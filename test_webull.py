import asyncio
import datetime as dt
import struct
import time
from typing import Any, cast

import aiohttp

import main
from charting import ChartRequest, NoChartData
from webull import (
    LiveQuote,
    WebullProviderError,
    bucket_rows,
    decode_quote_payload,
    fetch_intraday_bars,
    fetch_realtime_quote,
    patch_live_bar,
    resolve_ticker,
    snapshot_quote,
    _resolution_cache,
)


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, *, content_type: None = None) -> Any:
        del content_type
        return self.payload


class FakeSession:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.call_params: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: Any = None, headers: Any = None) -> FakeResponse:
        del headers
        self.calls.append(url)
        copied_params = dict(params) if params is not None else None
        self.call_params.append((url, copied_params))
        payload = self.routes[url]
        if callable(payload):
            payload = cast(Any, payload)(copied_params)
        if isinstance(payload, BaseException):
            raise payload
        status, body = payload
        return FakeResponse(status, body)

    def ws_connect(self, _url: str, *, origin: str, heartbeat: int) -> Any:
        del origin, heartbeat
        messages: list[str] = self.routes.get("__ws__", [])

        class WS:
            async def __aenter__(self) -> "WS":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            def __aiter__(self) -> "WS":
                return self

            async def __anext__(self) -> Any:
                if not messages:
                    raise StopAsyncIteration

                class Msg:
                    type = aiohttp.WSMsgType.TEXT

                    def __init__(self, data: str) -> None:
                        self.data = data

                return Msg(messages.pop(0))

            async def send_str(self, _message: str) -> None:
                return None

        return WS()


def session_for(routes: dict[str, Any]) -> aiohttp.ClientSession:
    return cast(aiohttp.ClientSession, FakeSession(routes))


SEARCH_URL = "https://quotes-gw.webullfintech.com/api/search/pc/tickers"
REALTIME_URL = "https://quotes-gw.webullfintech.com/api/bgw/quote/realtime"
HISTORY_URL = "https://quotes-gw.webullfintech.com/api/quote/charts/query-mini"

SEARCH_PAYLOAD = {
    "data": [
        {
            "tickerId": 913256135,
            "symbol": "AAPL",
            "template": "stock",
            "regionCode": "US",
            "name": "Apple Inc",
            "disExchangeCode": "NASDAQ",
        }
    ]
}

# end_ts, open, close, high, low, prevClose, volume[, vwap]
HISTORY_PAYLOAD = [
    {
        "tickerId": 913256135,
        "realPreClose": 310.34,
        "hasMore": 0,
        "data": [
            "1787660400,310.00,310.10,310.20,309.90,310.34,100",
            "1787660340,309.80,310.00,310.05,309.75,310.34,200",
            "bad-row",
        ],
    }
]

PREMARKET_REALTIME_PAYLOAD = [
    {
        "pPrice": "310.25",
        "close": "310.34",
        "preClose": "309.35",
        "tradeStatus": "F",
        "tradeTime": "2026-08-25T12:21:47.353+0000",
    }
]

REGULAR_REALTIME_PAYLOAD = [
    {
        "pPrice": "999.00",  # stale extended price must not win in T session
        "close": "310.25",
        "preClose": "310.34",
        "tradeStatus": "T",
        "tradeTime": "2026-08-25T15:21:47.353+0000",
    }
]


async def test_resolve_ticker_caches_results() -> None:
    _resolution_cache.clear()
    session = session_for({SEARCH_URL: (200, SEARCH_PAYLOAD)})

    first = await resolve_ticker(session, "AAPL")
    second = await resolve_ticker(session, "AAPL")

    assert first is not None and first.ticker_id == 913256135
    assert first.name == "Apple Inc"
    assert second == first
    assert cast(FakeSession, session).calls.count(SEARCH_URL) == 1


async def test_resolve_ticker_missing_symbol() -> None:
    _resolution_cache.clear()
    session = session_for({SEARCH_URL: (200, {"data": []})})
    assert await resolve_ticker(session, "ZZZZ") is None


async def test_fetch_intraday_bars_field_order_and_label_normalization() -> None:
    session = session_for({HISTORY_URL: (200, HISTORY_PAYLOAD)})
    rows, pre_close = await fetch_intraday_bars(session, 913256135, "i1")

    assert pre_close == 310.34
    # Webull rows are newest-first with END labels -> shifted back, ascending.
    assert [row[0] for row in rows] == [1787660280, 1787660340]
    # row: (epoch, open, high, low, close, volume) with close BEFORE high/low upstream
    assert rows[0] == (1787660280, 309.80, 310.05, 309.75, 310.00, 200.0)
    assert rows[1] == (1787660340, 310.00, 310.20, 309.90, 310.10, 100.0)
    history_params = cast(FakeSession, session).call_params[0][1]
    assert history_params is not None
    assert history_params["type"] == "m1"
    assert history_params["count"] == -200
    assert history_params["extendTrading"] == 1


async def test_fetch_intraday_bars_uses_native_interval_and_pages_without_duplicates() -> None:
    first_page = [
        {
            "tickerId": 913256135,
            "realPreClose": 310.34,
            "hasMore": 1,
            "data": [
                "1787660400,310.00,310.10,310.20,309.90,310.00,100",
                "1787660100,309.80,310.00,310.05,309.75,309.80,200",
            ],
        }
    ]
    second_page = [
        {
            "tickerId": 913256135,
            "realPreClose": 310.34,
            "hasMore": 0,
            "data": [
                "1787660100,309.80,310.00,310.05,309.75,309.80,200",
                "1787659800,309.70,309.80,309.90,309.60,309.70,50",
            ],
        }
    ]

    def history_route(params: dict[str, Any] | None) -> tuple[int, Any]:
        return (200, second_page if params and "timestamp" in params else first_page)

    session = session_for({HISTORY_URL: history_route})
    rows, _ = await fetch_intraday_bars(session, 913256135, "i5")
    assert [row[0] for row in rows] == [
        1787659800 - 300,
        1787660100 - 300,
        1787660400 - 300,
    ]
    calls = cast(FakeSession, session).call_params
    assert calls[0][1] is not None and calls[0][1]["type"] == "m5"
    assert calls[1][1] is not None and calls[1][1]["timestamp"] == 1787660100


async def test_fetch_intraday_bars_normalizes_partial_h4_session_bars() -> None:
    history = [
        {
            "tickerId": 913256135,
            "realPreClose": 310.34,
            "hasMore": 0,
            "data": [
                "1787702400,310,311,312,309,310,50",  # after: 16:00-20:00
                "1787688000,309,310,311,308,309,40",  # regular: 13:30-16:00
                "1787679000,308,309,310,307,308,30",  # regular: 09:30-13:30
                "1787664600,307,308,309,306,307,20",  # pre: 08:00-09:30
                "1787659200,306,307,308,305,306,10",  # pre: 04:00-08:00
            ],
        }
    ]
    session = session_for({HISTORY_URL: (200, history)})
    rows, _ = await fetch_intraday_bars(session, 913256135, "h4")
    assert [row[0] for row in rows] == [
        1787644800,
        1787659200,
        1787664600,
        1787679000,
        1787688000,
    ]


async def test_fetch_realtime_quote_empty_list_is_provider_error() -> None:
    session = session_for({REALTIME_URL: (200, [])})
    try:
        await fetch_realtime_quote(session, 913256135)
    except WebullProviderError:
        return
    raise AssertionError("expected WebullProviderError")


def test_snapshot_quote_premarket_uses_close_as_previous() -> None:
    last, previous, pub_epoch, session = snapshot_quote(PREMARKET_REALTIME_PAYLOAD[0])
    assert last == 310.25
    assert previous == 310.34  # F session: previous regular close is `close`
    assert session == "F"
    assert pub_epoch is not None and pub_epoch > 1_787_000_000


def test_snapshot_quote_regular_session_uses_preclose() -> None:
    last, previous, _, session = snapshot_quote(REGULAR_REALTIME_PAYLOAD[0])
    assert last == 310.25  # regular-session snapshots use `close`, not `pPrice`
    assert previous == 310.34  # T session: previous close is `preClose`
    assert session == "T"


def test_bucket_rows_aggregates_and_aligns() -> None:
    base = (1787660280 // 300) * 300  # aligned to the 300s bucket grid
    rows = [
        (base, 100.0, 101.0, 99.0, 100.5, 10.0),
        (base + 60, 100.5, 102.0, 100.0, 101.5, 20.0),
        (base + 120, 101.5, 101.5, 98.0, 99.0, 5.0),
        (base + 300, 99.0, 99.5, 98.5, 99.4, 7.0),
    ]
    bucketed = bucket_rows(rows, 300)
    assert len(bucketed) == 2
    epoch, open_, high, low, close, volume = bucketed[0]
    assert epoch == base
    assert (open_, high, low, close, volume) == (100.0, 102.0, 98.0, 99.0, 35.0)
    assert bucketed[1][0] == base + 300


def test_patch_live_bar_updates_forming_bucket() -> None:
    base = (1787660280 // 300) * 300
    rows = [(base, 100.0, 101.0, 99.0, 100.5, 10.0)]
    patched = patch_live_bar(rows, LiveQuote(102.0, (base + 30) * 1000, "T"), 300)
    assert len(patched) == 1
    assert patched[0][2] == 102.0  # high lifted
    assert patched[0][4] == 102.0  # close updated
    assert patched[0][5] == 10.0  # volume preserved


def test_patch_live_bar_appends_accurate_flat_next_bucket() -> None:
    base = (1787660280 // 300) * 300
    rows = [(base, 100.0, 101.0, 99.0, 100.5, 10.0)]
    patched = patch_live_bar(rows, LiveQuote(102.0, (base + 300) * 1000, "T"), 300)
    assert len(patched) == 2
    epoch, open_, high, low, close, _ = patched[1]
    assert epoch == base + 300
    # The first observed tick is the new bar's actual open; no synthetic wick.
    assert open_ == close == high == low == 102.0


def test_patch_live_bar_uses_webull_hourly_session_alignment() -> None:
    market_tz = dt.timezone(dt.timedelta(hours=-4))
    start = int(dt.datetime(2026, 8, 25, 9, 30, tzinfo=market_tz).timestamp())
    live_epoch = int(dt.datetime(2026, 8, 25, 11, 45, tzinfo=market_tz).timestamp())
    rows = [(start, 310.95, 313.58, 308.39, 309.40, 8_000_000.0)]
    patched = patch_live_bar(rows, LiveQuote(309.55, live_epoch * 1000, "T"), 14_400)
    assert len(patched) == 1
    assert patched[0][0] == start
    assert patched[0][4] == 309.55


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _field_bytes(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def test_decode_quote_payload_real_capture_shape() -> None:
    pub_ms = 1_787_660_545_391
    header = (
        _field_varint(2, 18808)
        + _field_varint(3, 913257561)
        + _field_bytes(4, b"F")
        + _field_varint(5, pub_ms)
        + _field_varint(6, 102)
    )
    body = _field_bytes(4, b"211.25") + _field_bytes(5, b"2.22")
    payload = _field_bytes(1, header) + _field_bytes(2, body)
    assert decode_quote_payload(payload) == (211.25, pub_ms, "F")


def test_decode_quote_payload_regular_session_uses_close_field() -> None:
    pub_ms = 1_787_671_861_345
    header = (
        _field_varint(3, 913256135)
        + _field_bytes(4, b"T")
        + _field_varint(5, pub_ms)
        + _field_varint(6, 102)
    )
    # Current type-102 SaleItem schema: field 1=close, field 4=pPrice.
    body = (
        _field_bytes(1, b"309.40")
        + _field_bytes(2, b"-0.94")
        + _field_bytes(4, b"999.00")
    )
    payload = _field_bytes(1, header) + _field_bytes(2, body)
    assert decode_quote_payload(payload) == (309.40, pub_ms, "T")


def test_decode_quote_payload_rejects_garbage() -> None:
    assert decode_quote_payload(b"\xff\xff\xff\xff") is None
    assert decode_quote_payload(b"") is None
    # fixed64/fixed32 wires must not crash the decoder
    mixed = _varint(1 << 3 | 1) + struct.pack("<d", 1.5) + _varint(2 << 3 | 5) + struct.pack("<f", 2.5)
    assert decode_quote_payload(mixed) is None


class StubStreamer:
    def __init__(self, live: LiveQuote | None) -> None:
        self.live = live
        self.subscribed: list[int] = []

    def subscribe(self, ticker_id: int) -> None:
        self.subscribed.append(ticker_id)

    def latest(self, ticker_id: int) -> LiveQuote | None:
        return self.live


async def test_fetch_webull_intraday_uses_stream_price_when_live() -> None:
    session = session_for(
        {
            SEARCH_URL: (200, SEARCH_PAYLOAD),
            HISTORY_URL: (200, HISTORY_PAYLOAD),
            REALTIME_URL: (200, REGULAR_REALTIME_PAYLOAD),
        }
    )
    now_ms = int(time.time() * 1000)
    streamer = StubStreamer(LiveQuote(311.50, now_ms, "F"))
    main.client.webull_streamer = cast(Any, streamer)
    _resolution_cache.clear()
    try:
        data = await main.fetch_webull_intraday_chart_data(
            session, ChartRequest(ticker="AAPL", timeframe="i1", timeframe_label="1 min")
        )
    finally:
        main.client.webull_streamer = None

    assert data.market_label == "Webull real-time"
    assert data.name == "Apple Inc"
    assert data.last_close == 311.50  # stream price wins over snapshot
    assert data.previous_close == 310.34
    assert data.change is not None and abs(data.change - 1.16) < 1e-9
    assert data.rows[-1].close == 311.50  # forming bar patched
    assert streamer.subscribed == [913256135]
    assert data.source_interval_seconds == 60


async def test_fetch_webull_intraday_falls_back_to_snapshot_price() -> None:
    session = session_for(
        {
            SEARCH_URL: (200, SEARCH_PAYLOAD),
            HISTORY_URL: (200, HISTORY_PAYLOAD),
            REALTIME_URL: (200, REGULAR_REALTIME_PAYLOAD),
        }
    )
    main.client.webull_streamer = None
    _resolution_cache.clear()
    data = await main.fetch_webull_intraday_chart_data(
        session, ChartRequest(ticker="AAPL", timeframe="i1", timeframe_label="1 min")
    )
    assert data.last_close == 310.25
    assert data.previous_close == 310.34


async def test_fetch_webull_h4_preserves_native_session_alignment() -> None:
    history = [
        {
            "tickerId": 913256135,
            "realPreClose": 310.34,
            "hasMore": 0,
            "data": [
                "1787679000,310.95,310.25,313.58,308.39,310.95,8000000",
                "1787664600,310.10,310.95,311.00,309.80,310.10,100000",
            ],
        }
    ]
    session = session_for(
        {
            SEARCH_URL: (200, SEARCH_PAYLOAD),
            HISTORY_URL: (200, history),
            REALTIME_URL: (200, REGULAR_REALTIME_PAYLOAD),
        }
    )
    main.client.webull_streamer = None
    _resolution_cache.clear()
    data = await main.fetch_webull_intraday_chart_data(
        session, ChartRequest(ticker="AAPL", timeframe="h4", timeframe_label="4 hour")
    )
    assert [row.epoch for row in data.rows] == [1787659200, 1787664600]
    assert data.rows[-1].close == 310.25


async def test_fetch_webull_intraday_unknown_ticker_raises_no_chart_data() -> None:
    session = session_for({SEARCH_URL: (200, {"data": []})})
    _resolution_cache.clear()
    try:
        await main.fetch_webull_intraday_chart_data(
            session, ChartRequest(ticker="AAPL", timeframe="i1", timeframe_label="1 min")
        )
    except NoChartData:
        return
    raise AssertionError("expected NoChartData")


def _tv_frame(payload: dict[str, Any]) -> str:
    import json

    encoded = json.dumps(payload, separators=(",", ":"))
    return f"~m~{len(encoded)}~m~{encoded}"


def _tradingview_messages() -> list[str]:
    rows = [
        {"i": index, "v": [1787660000 + index * 300, 100.0, 101.0, 99.0, 100.5, 10.0]}
        for index in range(3)
    ]
    daily = [
        {"i": 0, "v": [1787600000, 99.0, 102.0, 98.0, 100.0, 100.0]}
        for _ in range(3)
    ]
    return [
        _tv_frame({"m": "timescale_update", "p": ["chart", {"s1": {"s": rows}}]})
        + _tv_frame({"m": "series_completed", "p": ["chart", "s1"]}),
        _tv_frame({"m": "timescale_update", "p": ["chart", {"d1": {"s": daily}}]})
        + _tv_frame({"m": "series_completed", "p": ["chart", "d1"]}),
    ]


async def test_dispatch_falls_back_to_tradingview_on_webull_provider_error() -> None:
    ws_messages = _tradingview_messages()
    session = session_for({SEARCH_URL: (500, {}), "__ws__": ws_messages})
    _resolution_cache.clear()
    request = ChartRequest(ticker="AAPL", timeframe="i5", timeframe_label="5 min")
    data = await main.fetch_market_chart_data(session, request)
    assert data.market_label == "TradingView 24h"


async def test_dispatch_falls_back_when_webull_history_is_empty() -> None:
    session = session_for(
        {
            SEARCH_URL: (200, SEARCH_PAYLOAD),
            HISTORY_URL: (200, {"code": "417", "msg": "no chart"}),
            REALTIME_URL: (200, REGULAR_REALTIME_PAYLOAD),
            "__ws__": _tradingview_messages(),
        }
    )
    _resolution_cache.clear()
    request = ChartRequest(ticker="AAPL", timeframe="i5", timeframe_label="5 min")
    data = await main.fetch_market_chart_data(session, request)
    assert data.market_label == "TradingView 24h"


async def test_dispatch_falls_back_when_webull_cannot_resolve_symbol() -> None:
    session = session_for(
        {
            SEARCH_URL: (200, {"data": []}),
            "__ws__": _tradingview_messages(),
        }
    )
    _resolution_cache.clear()
    request = ChartRequest(ticker="AAPL", timeframe="i5", timeframe_label="5 min")
    data = await main.fetch_market_chart_data(session, request)
    assert data.market_label == "TradingView 24h"


async def run_tests() -> None:
    await test_resolve_ticker_caches_results()
    await test_resolve_ticker_missing_symbol()
    await test_fetch_intraday_bars_field_order_and_label_normalization()
    await test_fetch_intraday_bars_uses_native_interval_and_pages_without_duplicates()
    await test_fetch_intraday_bars_normalizes_partial_h4_session_bars()
    await test_fetch_realtime_quote_empty_list_is_provider_error()
    test_snapshot_quote_premarket_uses_close_as_previous()
    test_snapshot_quote_regular_session_uses_preclose()
    test_bucket_rows_aggregates_and_aligns()
    test_patch_live_bar_updates_forming_bucket()
    test_patch_live_bar_appends_accurate_flat_next_bucket()
    test_patch_live_bar_uses_webull_hourly_session_alignment()
    test_decode_quote_payload_real_capture_shape()
    test_decode_quote_payload_regular_session_uses_close_field()
    test_decode_quote_payload_rejects_garbage()
    await test_fetch_webull_intraday_uses_stream_price_when_live()
    await test_fetch_webull_intraday_falls_back_to_snapshot_price()
    await test_fetch_webull_h4_preserves_native_session_alignment()
    await test_fetch_webull_intraday_unknown_ticker_raises_no_chart_data()
    await test_dispatch_falls_back_to_tradingview_on_webull_provider_error()
    await test_dispatch_falls_back_when_webull_history_is_empty()
    await test_dispatch_falls_back_when_webull_cannot_resolve_symbol()


if __name__ == "__main__":
    asyncio.run(run_tests())
    print("test_webull ok")
