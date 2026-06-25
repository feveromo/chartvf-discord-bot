import datetime as dt
import io
import math

from charting import (
    CHART_RIGHT_MARGIN,
    DEFAULT_HEIGHT,
    DEFAULT_SCALE_FACTOR,
    DEFAULT_WIDTH,
    FUTURES_INTRADAY_VISIBLE_BARS,
    MARKET_TIME_ZONE,
    NoChartData,
    SMA_COLORS,
    SMA_PERIODS,
    SPARSE_CHART_MIN_BARS,
    STOCK_DAILY_VISIBLE_BARS,
    STOCK_INTRADAY_VISIBLE_BARS,
    STOCK_MONTHLY_VISIBLE_BARS,
    STOCK_WEEKLY_VISIBLE_BARS,
    YAHOO_SYMBOL_ALIASES,
    ChartRequest,
    _blend_rgb,
    _chart_x_positions,
    _clean_futures_intraday_wicks,
    _clean_stock_extended_wicks,
    _date_label,
    _futures_globex_session_bands,
    _futures_globex_session_key,
    _header_volume_label,
    _latest_quote_price_time,
    _month_tick_label,
    _nice_linear_axis,
    _patch_close_only_latest_ohlc,
    _quote_rows,
    _source_interval_seconds,
    _stock_5m_today_indexes,
    _stock_extended_session_bands,
    _stock_extended_session_key,
    _stock_previous_close,
    _visible_indexes,
    _volume_axis,
    _volume_scale_value,
    _x_grid_line_styles,
    aggregate_yahoo_chart_data,
    chart_title,
    parse_chart_command,
    quote_description,
    render_price_chart_png,
    yahoo_chart_url,
)


def test_charting_regressions() -> None:
    """Run lightweight assert-based regression checks."""
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
    assert _stock_previous_close({}, [100.0, 110.0, None], ChartRequest("BUG", "d", "daily")) == 110.0
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
    bad_vix_daily = {
        "date": [1, 2],
        "open": [19.67, 0.0],
        "high": [20.54, 0.0],
        "low": [18.61, 0.0],
        "close": [19.49, 18.63],
        "volume": [0, 0],
    }
    vix_rows = _quote_rows(bad_vix_daily, ChartRequest("VIX", "d", "daily"))
    assert vix_rows[-1][1:5] == (18.63, 18.63, 18.63, 18.63)
    vix_intraday = {
        "date": [10, 11, 12],
        "open": [19.13, 19.5, 18.63],
        "high": [20.34, 19.58, 18.63],
        "low": [18.04, 18.86, 18.63],
        "close": [19.5, 18.86, 18.63],
        "volume": [0, 0, 0],
    }
    patched_vix = _patch_close_only_latest_ohlc(bad_vix_daily, vix_intraday)
    assert _quote_rows(patched_vix, ChartRequest("VIX", "d", "daily"))[-1][1:5] == (19.13, 20.34, 18.04, 18.63)
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
        (utc_epoch(2026, 1, 15), 10.0, 15.0, 8.0, 14.0, 180.0),
        (utc_epoch(2026, 2, 1), 20.0, 22.0, 19.0, 21.0, 120.0),
    ]
    assert parse_chart_command(";amd 1") == ChartRequest("AMD", "i1", "1 min")
    assert parse_chart_command(";amd 4h") == ChartRequest("AMD", "h4", "4 hour")
    assert "interval=1m" in yahoo_chart_url(ChartRequest("AMD", "i1", "1 min"))
    assert "range=5d" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "interval=5m" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "includePrePost=true" in yahoo_chart_url(ChartRequest("AMD", "i5", "5 min"))
    assert "includePrePost=true" in yahoo_chart_url(ChartRequest("AMD", "i15", "15 min"))
    assert "range=1mo" in yahoo_chart_url(ChartRequest("AMD", "i30", "30 min"))
    assert "range=1y" in yahoo_chart_url(ChartRequest("AMD", "h4", "4 hour"))
    assert "includePrePost=true" in yahoo_chart_url(ChartRequest("AMD", "h4", "4 hour"))
    assert "range=3mo" in yahoo_chart_url(ChartRequest("ES", "h2", "2 hour", futures=True))
    assert "range=2y" in yahoo_chart_url(ChartRequest("AMD", "d", "daily"))
    for ticker, yahoo_symbol in YAHOO_SYMBOL_ALIASES.items():
        assert yahoo_symbol in yahoo_chart_url(ChartRequest(ticker, "d", "daily"))
    assert "range=2y" in yahoo_chart_url(ChartRequest("AMD", "d", "daily", date_range="y1"))
    assert "interval=1wk" in yahoo_chart_url(ChartRequest("AMD", "w", "weekly"))
    assert "range=10y" in yahoo_chart_url(ChartRequest("AMD", "w", "weekly"))
    monthly_url = yahoo_chart_url(ChartRequest("AMD", "m", "monthly"))
    assert "interval=1mo" in monthly_url and "period1=0" in monthly_url and "period2=" in monthly_url
    sample_rows = [(i, 1.0, 1.0, 1.0, float(i + 1), 1.0) for i in range(300)]
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "i15", "15 min"))) == STOCK_INTRADAY_VISIBLE_BARS
    h4_rows = [(i, 1.0, 1.0, 1.0, float(i + 1), 1.0) for i in range(500)]
    h4_indexes = _visible_indexes(h4_rows, ChartRequest("AMD", "h4", "4 hour"))
    assert len(h4_indexes) == STOCK_INTRADAY_VISIBLE_BARS
    assert h4_indexes[0] >= SMA_PERIODS[-1] - 1
    assert len(_visible_indexes(sample_rows, ChartRequest("NQ", "i5", "5 min", futures=True))) == FUTURES_INTRADAY_VISIBLE_BARS
    assert len(_visible_indexes(sample_rows + sample_rows, ChartRequest("AMD", "d", "daily"))) == STOCK_DAILY_VISIBLE_BARS
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "w", "weekly"))) == STOCK_WEEKLY_VISIBLE_BARS
    assert len(_visible_indexes(sample_rows, ChartRequest("AMD", "m", "monthly"))) == STOCK_MONTHLY_VISIBLE_BARS
    assert _nice_linear_axis(14.92, 32.73) == (14, 34, [34, 32, 30, 28, 26, 24, 22, 20, 18, 16, 14])
    assert _month_tick_label(utc_epoch(2024, 1, 1), 1_000 * 86400) == "24"
    assert _month_tick_label(utc_epoch(2024, 2, 1), 1_000 * 86400) == "F"
    assert _x_grid_line_styles([(idx, str(idx)) for idx in range(7)], False) == [
        (0, True), (1, True), (2, True), (3, True), (4, True), (5, True), (6, True)
    ]
    assert _x_grid_line_styles([(idx, str(idx)) for idx in range(7)], True) == [
        (0, True), (1, False), (2, False), (3, True), (4, False), (5, False), (6, True)
    ]
    assert _volume_axis(350_000_000, ChartRequest("SOFI", "w", "weekly")) == (
        400_000_000,
        [100_000_000, 200_000_000, 300_000_000, 400_000_000],
    )
    assert _volume_axis(250_000_000, ChartRequest("MSFT", "w", "weekly")) == (
        400_000_000,
        [100_000_000, 200_000_000, 300_000_000, 400_000_000],
    )
    assert _volume_axis(350_000_000, ChartRequest("SOFI", "m", "monthly")) == (
        400_000_000,
        [100_000_000, 200_000_000, 300_000_000, 400_000_000],
    )
    assert _volume_axis(688_100_000, ChartRequest("SOFI", "w", "weekly")) == (
        800_000_000,
        [200_000_000, 400_000_000, 600_000_000, 800_000_000],
    )
    volume_rows = [(i, 1.0, 1.0, 1.0, 1.0, float(i + 1)) for i in range(100)]
    volume_rows.append((101, 1.0, 1.0, 1.0, 1.0, 10_000.0))
    assert _volume_scale_value(volume_rows, ChartRequest("AMD", "i5", "5 min")) == 10_000.0
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
    assert _latest_quote_price_time(
        {"regularMarketPrice": 69.93, "regularMarketTime": et_epoch(16, 0)},
        [et_epoch(19, 59)],
        [80.17],
        ChartRequest("TEST", "h", "hourly"),
    ) == (80.17, et_epoch(19, 59))
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
    cleaned = _clean_stock_extended_wicks(wick_rows, ChartRequest("AMD", "i5", "5 min"))
    assert cleaned[0][3] == 100.0
    assert cleaned[3][3] == 80.0
    assert cleaned[4][2] == 100.9
    assert cleaned[5][2] == 101.0
    h4_cleaned = _clean_stock_extended_wicks(wick_rows, ChartRequest("AMD", "h4", "4 hour"))
    assert h4_cleaned[0][3] == 100.0
    assert h4_cleaned[3][3] == 80.0
    assert h4_cleaned[4][2] == 100.9
    futures_wick_rows = [
        (et_epoch(18, 0), 100.0, 101.0, 99.0, 100.5, 1.0),
        (et_epoch(18, 5), 100.5, 101.5, 100.0, 101.0, 1.0),
        (et_epoch(18, 10), 101.0, 125.0, 100.5, 101.5, 1.0),
        (et_epoch(18, 15), 101.5, 102.5, 101.0, 102.0, 1.0),
        (et_epoch(18, 20), 102.0, 125.0, 101.5, 102.5, 1.0),
        (et_epoch(18, 25), 102.5, 103.5, 102.0, 103.0, 1.0),
        (et_epoch(18, 30), 103.0, 125.0, 102.5, 103.5, 1.0),
    ]
    futures_cleaned = _clean_futures_intraday_wicks(
        futures_wick_rows,
        ChartRequest("ES", "i5", "5 min", futures=True),
    )
    assert futures_cleaned[2][2] == 101.5
    assert futures_cleaned[4][2] == 102.5
    assert futures_cleaned[6][2] == 103.5
    regular_futures_rows = [
        (et_epoch(10, 0), 100.0, 125.0, 99.0, 100.5, 1.0),
        (et_epoch(10, 5), 100.5, 125.0, 100.0, 101.0, 1.0),
        (et_epoch(10, 10), 101.0, 125.0, 100.5, 101.5, 1.0),
        (et_epoch(10, 15), 101.5, 102.5, 101.0, 102.0, 1.0),
    ]
    assert _clean_futures_intraday_wicks(
        regular_futures_rows,
        ChartRequest("ES", "i5", "5 min", futures=True),
    )[0][2] == 125.0
    mixed_session_rows = futures_wick_rows + [
        (et_epoch(10, 0), 124.0, 125.0, 123.0, 124.5, 1.0),
    ]
    mixed_cleaned = _clean_futures_intraday_wicks(
        mixed_session_rows,
        ChartRequest("ES", "i5", "5 min", futures=True),
    )
    assert mixed_cleaned[-1][2] == 125.0
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
    for bad_range_command in (";AAPL 1y 5", ";AAPL 5 1y percent", ";fut ES 1y 15"):
        try:
            parse_chart_command(bad_range_command)
        except ValueError as error:
            assert "Date ranges only work" in str(error)
        else:
            raise AssertionError("date ranges should be rejected on intraday charts")

    # Futures: use `;fut`, not `;f` — `;f` is Ford.
    assert parse_chart_command(";f") == ChartRequest("F", "i5", "5 min")
    assert parse_chart_command(";fut es") == ChartRequest("ES", "i5", "5 min", futures=True)
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
    assert parse_chart_command(";fut 6e") == ChartRequest("6E", "i5", "5 min", futures=True)
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
    try:
        render_price_chart_png({
            "ticker": "ZERO",
            "date": [1, 2],
            "open": [0, 1],
            "high": [0, 1],
            "low": [0, 1],
            "close": [0, 1],
            "volume": [1, 1],
        }, ChartRequest("ZERO", "d", "daily", scale="percentage", scale_label="percent"))
    except NoChartData as error:
        assert "zero starting price" in str(error)
    else:
        raise AssertionError("percent scale should reject a zero starting price")
    smooth_close = [100.0 + math.sin(i / 4) * 3.0 + i * 0.03 for i in range(80)]
    smooth_png = render_price_chart_png({
        "ticker": "SMA",
        "date": [1_700_000_000 + i * 86400 for i in range(len(smooth_close))],
        "open": smooth_close,
        "high": [value + 0.4 for value in smooth_close],
        "low": [value - 0.4 for value in smooth_close],
        "close": smooth_close,
        "volume": [100.0] * len(smooth_close),
    }, ChartRequest("SMA", "d", "daily"))
    from PIL import Image
    smooth_image = Image.open(io.BytesIO(smooth_png)).convert("RGB")
    crop = smooth_image.crop((60, 34, DEFAULT_WIDTH * DEFAULT_SCALE_FACTOR - CHART_RIGHT_MARGIN, 370))
    crop_bytes = crop.tobytes()
    edge_pixels = 0
    sma20 = _blend_rgb(SMA_COLORS[20], (250, 250, 250), 0.72)
    for i in range(0, len(crop_bytes), 3):
        rgb = crop_bytes[i:i + 3]
        distance = sum(abs(rgb[channel] - sma20[channel]) for channel in range(3))
        edge_pixels += 0 < distance <= 90
    assert edge_pixels > 0
    overlay_close = [130.0] * 120 + [132.0 + math.sin(i / 5) * 0.35 for i in range(180)]
    overlay_png = render_price_chart_png({
        "ticker": "SMA",
        "date": [1_550_000_000 + i * 7 * 86400 for i in range(len(overlay_close))],
        "open": overlay_close,
        "high": [value + 0.25 for value in overlay_close],
        "low": [value - 0.25 for value in overlay_close],
        "close": overlay_close,
        "volume": [100_000_000.0] * len(overlay_close),
    }, ChartRequest("SMA", "w", "weekly"))
    overlay_image = Image.open(io.BytesIO(overlay_png)).convert("RGB")
    height = DEFAULT_HEIGHT * DEFAULT_SCALE_FACTOR
    vol_bottom = height - 30
    price_bottom = vol_bottom - 68 - 8
    plot_right = DEFAULT_WIDTH * DEFAULT_SCALE_FACTOR - CHART_RIGHT_MARGIN
    overlay_crop = overlay_image.crop((60, price_bottom + 1, plot_right, vol_bottom))
    overlay_bytes = overlay_crop.tobytes()
    sma200 = _blend_rgb(SMA_COLORS[200], (250, 250, 250), 0.72)
    sma200_volume_pixels = 0
    for i in range(0, len(overlay_bytes), 3):
        rgb = overlay_bytes[i:i + 3]
        distance = sum(abs(rgb[channel] - sma200[channel]) for channel in range(3))
        sma200_volume_pixels += distance <= 50
    assert sma200_volume_pixels > 50
    aapl_req = parse_chart_command(";aapl")
    assert aapl_req is not None and not aapl_req.futures and aapl_req.timeframe == "i5"


if __name__ == "__main__":
    test_charting_regressions()
    print("test_charting ok")
