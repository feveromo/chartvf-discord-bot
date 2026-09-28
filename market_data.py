"""Route a chart request to the provider with the best data for it."""

import logging

import aiohttp

from charting import ChartData, ChartRequest, NoChartData, is_intraday
from crypto import fetch_crypto_chart_data
from market_http import PROVIDER_ERRORS
from tradingview import TRADINGVIEW_FUTURES_SYMBOLS, fetch_tradingview_chart_data
from webull import WebullStreamer, fetch_webull_chart_data
from yahoo import YAHOO_SYMBOL_ALIASES, fetch_yahoo_chart_data

LOGGER = logging.getLogger("chartvf")


async def fetch_market_chart_data(
    session: aiohttp.ClientSession,
    request: ChartRequest,
    streamer: WebullStreamer | None = None,
) -> ChartData:
    """Crypto: OKX/Binance. Stock intraday: Webull real-time, then TradingView 24h.
    Mapped futures intraday: TradingView. Everything else: Yahoo."""
    if request.crypto_market:
        return await fetch_crypto_chart_data(session, request)
    if is_intraday(request.timeframe):
        if not request.futures and request.ticker not in YAHOO_SYMBOL_ALIASES:
            try:
                return await fetch_webull_chart_data(session, request, streamer)
            except (*PROVIDER_ERRORS, NoChartData) as error:
                LOGGER.info(
                    "provider_fallback source=webull target=tradingview ticker=%s error_type=%s",
                    request.ticker,
                    type(error).__name__,
                )
            return await fetch_tradingview_chart_data(session, request)
        if request.futures and request.ticker in TRADINGVIEW_FUTURES_SYMBOLS:
            return await fetch_tradingview_chart_data(session, request)
    return await fetch_yahoo_chart_data(session, request)
