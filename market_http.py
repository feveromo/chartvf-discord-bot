"""Shared HTTP plumbing for the market data providers."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import aiohttp

from charting import safe_float

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=4, sock_read=8)
MAX_RETRY_AFTER_SECONDS = 1.5
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


class MarketDataProviderError(RuntimeError):
    pass


class MarketDataHTTPError(MarketDataProviderError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Market data provider returned HTTP {status}")


# Everything a provider call can fail with that means "try again later".
PROVIDER_ERRORS = (aiohttp.ClientError, TimeoutError, MarketDataProviderError)


def create_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=HTTP_TIMEOUT,
        # No pool caps: a burst of charts should all fetch at once.
        connector=aiohttp.TCPConnector(limit=0, ttl_dns_cache=300),
        cookie_jar=aiohttp.DummyCookieJar(),
        headers={
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Accept": "application/json",
        },
    )


async def request_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET JSON, retrying once on a network error, 429, or 5xx."""
    for attempt in range(2):
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status in RETRYABLE_STATUSES and attempt == 0:
                    retry_after = safe_float(response.headers.get("Retry-After")) or 0.25
                    await asyncio.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
                    continue
                if response.status != 200:
                    raise MarketDataHTTPError(response.status)
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as error:
                    raise MarketDataProviderError(
                        "Market data provider returned malformed JSON"
                    ) from error
        except (aiohttp.ClientError, TimeoutError):
            if attempt == 0:
                continue
            raise
    raise MarketDataProviderError("Market data provider returned an error")


@contextlib.asynccontextmanager
async def background[T](coro: Coroutine[Any, Any, T]) -> AsyncIterator[asyncio.Task[T]]:
    """Run a side request alongside the main one; cancel it if the block exits early."""
    task = asyncio.create_task(coro)
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
