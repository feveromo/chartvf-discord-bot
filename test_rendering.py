import datetime as dt
import hashlib
import io
import math
import time

from PIL import Image

from charting import ChartData, ChartRequest, normalize_chart_rows, render_price_chart_png


RENDER_LIMIT_MS = 100
EXPECTED_RGB_HASHES = {
    "stock_i5_light": "6a4ee7a8dfc74c0fc0a7f20bde82d2c67cac7a2723fc82a321e8919ba172c296",
    "stock_daily_dark_line": "93bab841c2c7c6af932ea13ae75a642941141d185a42004051169dfa7c10efb0",
    "futures_i15_light": "d80b0c75c053d97d34355a06953e739c92a8363748019bdadb16bf5e317daa99",
    "crypto_daily_percent": "afd3a7baedd9cca4f2ef861ee47fe9c757d3b734029144b28fff50e214e75f0f",
}


def make_data(
    ticker: str,
    start: int,
    step: int,
    count: int,
    base: float,
    *,
    futures: bool = False,
    market_label: str = "",
    source_interval_seconds: int | None = None,
) -> ChartData:
    dates = [start + index * step for index in range(count)]
    closes = [base + index * 0.035 + math.sin(index / 8) * 2.1 for index in range(count)]
    opens = [value + math.sin(index / 5) * 0.32 for index, value in enumerate(closes)]
    highs = [max(open_, close) + 0.48 + (index % 4) * 0.03 for index, (open_, close) in enumerate(zip(opens, closes, strict=True))]
    lows = [min(open_, close) - 0.44 - (index % 3) * 0.04 for index, (open_, close) in enumerate(zip(opens, closes, strict=True))]
    volumes = [100_000 + (index % 17) * 12_345 for index in range(count)]
    return ChartData(
        ticker=ticker,
        name=f"{ticker} Test Instrument",
        rows=normalize_chart_rows(dates, opens, highs, lows, closes, volumes),
        last_close=closes[-1],
        last_time=dates[-1],
        previous_close=closes[-2],
        market_label=market_label,
        futures=futures,
        source_interval_seconds=source_interval_seconds,
    )


def rgb_hash(payload: bytes) -> str:
    pixels = Image.open(io.BytesIO(payload)).convert("RGB").tobytes()
    return hashlib.sha256(pixels).hexdigest()


def render_cases() -> dict[str, tuple[ChartData, ChartRequest]]:
    utc = dt.timezone.utc
    return {
        "stock_i5_light": (
            make_data(
                "AAPL",
                int(dt.datetime(2026, 6, 15, 8, tzinfo=utc).timestamp()),
                300,
                192,
                210,
                source_interval_seconds=300,
            ),
            ChartRequest("AAPL", "i5", "5 min"),
        ),
        "stock_daily_dark_line": (
            make_data("MSFT", int(dt.datetime(2025, 8, 1, tzinfo=utc).timestamp()), 86400, 260, 440),
            ChartRequest("MSFT", "d", "daily", "l", "line", "dark", "dark"),
        ),
        "futures_i15_light": (
            make_data(
                "ES",
                int(dt.datetime(2026, 6, 15, tzinfo=utc).timestamp()),
                900,
                240,
                6100,
                futures=True,
                source_interval_seconds=900,
            ),
            ChartRequest("ES", "i15", "15 min", futures=True),
        ),
        "crypto_daily_percent": (
            make_data(
                "BTC",
                int(dt.datetime(2025, 8, 1, tzinfo=utc).timestamp()),
                86400,
                260,
                95000,
                market_label="Binance spot",
                source_interval_seconds=86400,
            ),
            ChartRequest("BTC", "d", "daily", scale="percentage", scale_label="percent", crypto_market="auto"),
        ),
    }


def test_rendering_regressions() -> None:
    cases = render_cases()
    for name, (data, request) in cases.items():
        assert rgb_hash(render_price_chart_png(data, request)) == EXPECTED_RGB_HASHES[name]

    benchmark_data, benchmark_request = cases["stock_daily_dark_line"]
    render_price_chart_png(benchmark_data, benchmark_request)
    timings: list[float] = []
    for _ in range(10):
        started = time.perf_counter()
        render_price_chart_png(benchmark_data, benchmark_request)
        timings.append((time.perf_counter() - started) * 1000)
    average_ms = sum(timings) / len(timings)
    # Renders take ~35 ms; the old full-plot LANCZOS SMA masks took ~170 ms.
    assert average_ms <= RENDER_LIMIT_MS, f"Average warm render took {average_ms:.1f} ms"


if __name__ == "__main__":
    test_rendering_regressions()
    print("test_rendering ok")
