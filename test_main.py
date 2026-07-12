import asyncio
import time
from collections.abc import Callable
from typing import Any, cast

import aiohttp

from charting import ChartRequest, NoChartData
from main import (
    MarketDataHTTPError,
    _fetch_binance_klines,
    _request_json,
    fetch_crypto_chart_data,
    fetch_market_chart_data,
)


class FakeResponse:
    def __init__(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
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


Router = Callable[[str, dict[str, Any] | None], FakeResponse]


class FakeSession:
    def __init__(self, router: Router) -> None:
        self.router = router
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> FakeResponse:
        copied_params = dict(params) if params is not None else None
        self.calls.append((url, copied_params))
        return self.router(url, copied_params)


def session_for(router: Router) -> tuple[aiohttp.ClientSession, FakeSession]:
    fake = FakeSession(router)
    return cast(aiohttp.ClientSession, fake), fake


def yahoo_payload(
    *,
    closes: list[float],
    previous_close: float,
    interval: str = "5m",
    name: str = "Test instrument",
) -> dict[str, Any]:
    start = 1_780_000_000
    step = 86400 if interval == "1d" else 300
    timestamps = [start + index * step for index in range(len(closes))]
    return {
        "chart": {
            "result": [{
                "meta": {
                    "shortName": name,
                    "previousClose": previous_close,
                    "regularMarketPrice": closes[-1],
                    "regularMarketTime": timestamps[-1],
                    "dataGranularity": interval,
                },
                "timestamp": timestamps,
                "indicators": {"quote": [{
                    "open": [close - 0.5 for close in closes],
                    "high": [close + 1 for close in closes],
                    "low": [close - 1 for close in closes],
                    "close": closes,
                    "volume": [1000 for _ in closes],
                }]},
            }],
            "error": None,
        },
    }


async def test_retry_once() -> None:
    responses = [
        FakeResponse(503, {}, {"Retry-After": "0"}),
        FakeResponse(200, {"ok": True}),
    ]
    session, fake = session_for(lambda _url, _params: responses.pop(0))
    assert await _request_json(session, "https://example.test/data") == {"ok": True}
    assert len(fake.calls) == 2


async def test_non_retryable_statuses_fail_once_and_preserve_no_data() -> None:
    session, fake = session_for(lambda _url, _params: FakeResponse(451, {}))
    try:
        await _request_json(session, "https://example.test/restricted")
    except MarketDataHTTPError as error:
        assert error.status == 451
    else:
        raise AssertionError("HTTP 451 should fail without retrying")
    assert len(fake.calls) == 1

    missing_session, missing_fake = session_for(lambda _url, _params: FakeResponse(404, {}))
    try:
        await fetch_market_chart_data(missing_session, ChartRequest("MISSING", "d", "daily"))
    except NoChartData:
        pass
    else:
        raise AssertionError("HTTP 404 should remain a no-data result")
    assert len(missing_fake.calls) == 1


async def test_stock_uses_yahoo_previous_close_without_daily_fetch() -> None:
    payload = yahoo_payload(closes=[100.0, 102.0, 104.0], previous_close=99.0)
    session, fake = session_for(lambda _url, _params: FakeResponse(200, payload))
    data = await fetch_market_chart_data(session, ChartRequest("TEST", "i5", "5 min"))
    assert data.previous_close == 99.0
    assert data.change == 5.0
    assert data.source_interval_seconds == 300
    assert len(fake.calls) == 1


async def test_futures_fetches_daily_reference_concurrently() -> None:
    intraday = yahoo_payload(closes=[6100.0, 6110.0], previous_close=6000.0)
    daily = yahoo_payload(closes=[5980.0, 6050.0, 6110.0], previous_close=5980.0, interval="1d")

    def route(url: str, _params: dict[str, Any] | None) -> FakeResponse:
        return FakeResponse(200, daily if "interval=1d" in url else intraday)

    session, fake = session_for(route)
    request = ChartRequest("ES", "i5", "5 min", futures=True)
    data = await fetch_market_chart_data(session, request)
    assert data.previous_close == 6050.0
    assert data.change == 60.0
    assert len(fake.calls) == 2


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
            return FakeResponse(200, {"code": "0", "data": [{"last": "105", "open24h": "95", "ts": "1780000900000"}]})
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
            [start + index * day_ms, "100", "102", "99", "101", "10", start + (index + 1) * day_ms - 1]
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
    await test_stock_uses_yahoo_previous_close_without_daily_fetch()
    await test_futures_fetches_daily_reference_concurrently()
    await test_okx_is_primary_for_perp_and_uses_rolling_24h_change()
    await test_ticker_failure_does_not_fake_candle_change()
    await test_binance_five_year_history_paginates_through_cutoff()


if __name__ == "__main__":
    asyncio.run(run_tests())
    print("test_main ok")
