import datetime as dt
import hashlib
import io
import math
import os
import time

from PIL import Image

from charting import ChartData, ChartRequest, normalize_chart_rows, render_price_chart_png


EXPECTED_RGB_HASHES = {
    "stock_i5_light": "95c9bd6a18492dbddc9f0d888279a9f6886411663cda1f4852e395d7b38de5dd",
    "stock_daily_dark_line": "f72a992c42aaf9ef049bd5f5e84c17bd16b723f523f1ff6be9d283872bd19389",
    "futures_i15_light": "083801cd73a52b4af42b449b3af467091af081bb09760b87fcbce7bfc41e437a",
    "crypto_daily_percent": "af6ee0464d7a44ef24ef421ace16ae7f99c818ce76a37a6fae2fc40ea578b201",
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
    previous = closes[-2]
    change = closes[-1] - previous
    return ChartData(
        ticker=ticker,
        name=f"{ticker} Test Instrument",
        rows=normalize_chart_rows(dates, opens, highs, lows, closes, volumes),
        last_close=closes[-1],
        last_time=dates[-1],
        previous_close=previous,
        change=change,
        change_percent=change / previous * 100,
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
    limit_ms = 175 if os.getenv("CI") else 115
    assert average_ms <= limit_ms, f"Average warm render took {average_ms:.1f} ms"


if __name__ == "__main__":
    test_rendering_regressions()
    print("test_rendering ok")
