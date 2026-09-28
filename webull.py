"""Anonymous real-time US equity data from Webull's unofficial gateways.

No account, token, or cookie required. Four operations, reverse-engineered
from the public web app (app.webull.com) on 2026-08-25:

- REST search:   /api/search/pc/tickers            (symbol -> tickerId)
- REST snapshot: /api/bgw/quote/realtime?delay=0 (real-time quote)
- REST klines:   /api/quote/charts/query-mini    (native interval history)
- MQTT stream:   wss://wspush.webullfintech.com/mqtt (tick-grade push)

Kline CSV row order is unusual: timestamp,open,CLOSE,HIGH,LOW,prevClose,volume[,vwap]
(close comes before high/low), and intraday timestamps label bar ends. All REST
endpoints need the WEBULL_HEADERS below; the realtime endpoint returns [] unless
delay=0 is present.
"""

import datetime as dt
import json
import logging
import math
import random
import struct
import threading
import time
import uuid
from typing import Any, NamedTuple

import aiohttp
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from charting import (
    EXTENDED_SESSION_END,
    EXTENDED_SESSION_START,
    MARKET_TIME_ZONE,
    REGULAR_SESSION_END,
    REGULAR_SESSION_START,
    TIMEFRAMES,
    ChartData,
    ChartRequest,
    ChartRow,
    NoChartData,
    aggregate_chart_data,
    native_timeframe,
    safe_float,
)
from market_http import PROVIDER_ERRORS, MarketDataProviderError, background, request_json

LOGGER = logging.getLogger("chartvf.webull")

SEARCH_URL = "https://quotes-gw.webullfintech.com/api/search/pc/tickers"
REALTIME_URL = "https://quotes-gw.webullfintech.com/api/bgw/quote/realtime"
HISTORY_URL = "https://quotes-gw.webullfintech.com/api/quote/charts/query-mini"
MQTT_HOST = "wspush.webullfintech.com"
MQTT_PATH = "/mqtt"

WEBULL_HEADERS = {
    "hl": "en",
    "os": "web",
    "app": "global",
    "appid": "webull-web",
    "platform": "web",
    "ver": "5.0.0",
    "lzone": "dc-core-rg",
    "ph": "MacOS Chrome",
    "locale": "eng",
}

# Native Webull history types. There are no 2- or 3-minute candles, so those
# are aggregated from m1.
WEBULL_INTERVALS = {
    "i1": "m1",
    "i5": "m5",
    "i15": "m15",
    "i30": "m30",
    "h": "m60",
    "h4": "m240",
}

RESOLUTION_TTL_SECONDS = 24 * 3600
MISSING_TTL_SECONDS = 10 * 60  # retry unknown symbols soon; misses can be transient
RESOLUTION_CACHE_SIZE = 512
HISTORY_PAGE_SIZE = 200
HISTORY_MAX_PAGES = 6
HISTORY_TARGET_BARS = 350
STREAM_STALE_MS = 10_000
MAX_STREAM_SUBSCRIPTIONS = 50

Bar = tuple[int, float, float, float, float, float]  # epoch, open, high, low, close, volume


class WebullProviderError(MarketDataProviderError):
    pass


class TickerResolution(NamedTuple):
    ticker_id: int
    name: str
    exchange: str


class LiveQuote(NamedTuple):
    price: float
    pub_ms: int
    session: str  # F=pre-market, T=regular, A=after-hours


_resolution_cache: dict[str, tuple[float, TickerResolution | None]] = {}


def _normalized_bar_start(end_epoch: int, seconds: int) -> int:
    """Convert an end label using Webull's pre/regular/post anchors."""
    end_local = dt.datetime.fromtimestamp(end_epoch, dt.timezone.utc).astimezone(
        MARKET_TIME_ZONE
    )
    local_time = end_local.time()
    if EXTENDED_SESSION_START < local_time <= REGULAR_SESSION_START:
        anchor_time = EXTENDED_SESSION_START
    elif REGULAR_SESSION_START < local_time <= REGULAR_SESSION_END:
        anchor_time = REGULAR_SESSION_START
    elif REGULAR_SESSION_END < local_time <= EXTENDED_SESSION_END:
        anchor_time = REGULAR_SESSION_END
    else:
        return end_epoch - seconds
    anchor = dt.datetime.combine(end_local.date(), anchor_time, MARKET_TIME_ZONE)
    elapsed = end_epoch - int(anchor.timestamp())
    interval_index = max(0, (elapsed - 1) // seconds)
    return int(anchor.timestamp()) + interval_index * seconds


def _live_bucket_epoch(epoch: int, seconds: int) -> int:
    """Match Webull's exchange-anchored 1h/4h forming-bar boundaries."""
    if seconds < 3600:
        return (epoch // seconds) * seconds
    local = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone(
        MARKET_TIME_ZONE
    )
    local_time = local.time()
    if EXTENDED_SESSION_START <= local_time < REGULAR_SESSION_START:
        anchor_time = EXTENDED_SESSION_START
    elif REGULAR_SESSION_START <= local_time < REGULAR_SESSION_END:
        anchor_time = REGULAR_SESSION_START
    elif REGULAR_SESSION_END <= local_time < EXTENDED_SESSION_END:
        anchor_time = REGULAR_SESSION_END
    else:
        return (epoch // seconds) * seconds
    anchor = dt.datetime.combine(local.date(), anchor_time, MARKET_TIME_ZONE)
    intervals = math.floor((local - anchor).total_seconds() / seconds)
    return int((anchor + dt.timedelta(seconds=intervals * seconds)).timestamp())


async def resolve_ticker(
    session: aiohttp.ClientSession, symbol: str
) -> TickerResolution | None:
    """Symbol -> Webull tickerId, or None when Webull doesn't list it. Cached."""
    key = symbol.upper()
    cached = _resolution_cache.get(key)
    if cached is not None:
        stored_at, resolution = cached
        ttl = RESOLUTION_TTL_SECONDS if resolution is not None else MISSING_TTL_SECONDS
        if time.monotonic() - stored_at < ttl:
            return resolution

    payload = await request_json(
        session,
        SEARCH_URL,
        params={"keyword": key, "pageIndex": 1, "pageSize": 10, "regionId": 6},
        headers=WEBULL_HEADERS,
    )
    if not isinstance(payload, dict):
        raise WebullProviderError("webull ticker search returned invalid data")
    resolution = None
    try:
        for entry in payload.get("data") or []:
            if (
                isinstance(entry, dict)
                and str(entry.get("symbol", "")).upper() == key
                and entry.get("template") in {"stock", "etf", "fund"}
                and entry.get("regionCode") == "US"
            ):
                resolution = TickerResolution(
                    int(entry["tickerId"]),
                    str(entry.get("name") or key),
                    str(entry.get("disExchangeCode") or ""),
                )
                break
    except (KeyError, TypeError, ValueError) as error:
        raise WebullProviderError("webull ticker search returned invalid data") from error

    _resolution_cache.pop(key, None)
    _resolution_cache[key] = (time.monotonic(), resolution)
    while len(_resolution_cache) > RESOLUTION_CACHE_SIZE:
        del _resolution_cache[next(iter(_resolution_cache))]
    return resolution


async def fetch_realtime_quote(
    session: aiohttp.ClientSession, ticker_id: int
) -> dict[str, Any]:
    """Real-time snapshot. Webull returns [] without delay=0."""
    payload = await request_json(
        session,
        REALTIME_URL,
        params={"ids": str(ticker_id), "delay": 0, "more": 1, "includeSecu": 1},
        headers=WEBULL_HEADERS,
    )
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise WebullProviderError("webull realtime quote returned no data")
    return payload[0]


def snapshot_quote(raw: dict[str, Any]) -> tuple[float, float | None, int | None, str]:
    """Extract (last_price, previous_close, pub_epoch, session) from a snapshot.

    Webull puts the regular-session last price in ``close`` and an active
    extended-session price in ``pPrice``. In extended hours, ``close`` is the
    latest regular-session close; otherwise ``preClose`` is the comparison.
    """
    session = str(raw.get("tradeStatus") or raw.get("status") or "")
    extended_price = safe_float(raw.get("pPrice"))
    close = safe_float(raw.get("close"))
    pre_close = safe_float(raw.get("preClose"))
    last = (
        close
        if session == "T" and close is not None
        else extended_price if extended_price is not None else close
    )
    previous = (
        close
        if extended_price is not None and session != "T" and close is not None
        else pre_close
    )
    trade_time = raw.get("tradeTime")
    pub_epoch: int | None = None
    if isinstance(trade_time, str):
        try:
            pub_epoch = int(dt.datetime.fromisoformat(trade_time).timestamp())
        except ValueError:
            pub_epoch = None
    else:
        numeric = safe_float(trade_time)
        pub_epoch = int(numeric) if numeric else None
    if last is None:
        raise WebullProviderError("webull realtime quote missing price")
    return last, previous, pub_epoch, session


async def fetch_intraday_bars(
    session: aiohttp.ClientSession,
    ticker_id: int,
    timeframe: str,
) -> tuple[list[Bar], float | None]:
    """Fetch ascending native Webull bars and normalize labels to bar starts.

    The public client pages backward with a negative count and the oldest
    returned end timestamp. We fetch enough source bars to retain SMA-200
    context behind the 150 visible candles, including for synthetic 2m/3m.
    """
    native = native_timeframe(timeframe, WEBULL_INTERVALS)
    source_seconds = TIMEFRAMES[native].seconds
    target_rows = math.ceil(HISTORY_TARGET_BARS * TIMEFRAMES[timeframe].seconds / source_seconds)
    max_pages = min(HISTORY_MAX_PAGES, max(1, math.ceil(target_rows / (HISTORY_PAGE_SIZE - 1))))
    rows_by_epoch: dict[int, Bar] = {}
    real_pre_close: float | None = None
    timestamp: int | None = None

    for page in range(max_pages):
        params: dict[str, int | str] = {
            "tickerId": ticker_id,
            "type": WEBULL_INTERVALS[native],
            "count": -HISTORY_PAGE_SIZE,
            "restorationType": 0,
            "extendTrading": 1,
        }
        if timestamp is not None:
            params["timestamp"] = timestamp
        payload = await request_json(session, HISTORY_URL, params=params, headers=WEBULL_HEADERS)

        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, dict) or not isinstance(record.get("data"), list):
            if page == 0:
                raise WebullProviderError("no webull intraday data")
            break
        if page == 0:
            real_pre_close = safe_float(record.get("realPreClose"))

        previous_count = len(rows_by_epoch)
        oldest_end: int | None = None
        for line in record["data"]:
            parts = str(line).split(",")
            if len(parts) < 7:
                continue
            # end_ts, open, close, high, low, prevClose, volume[, vwap]
            end_epoch, open_, close, high, low = (safe_float(part) for part in parts[:5])
            if end_epoch is None or open_ is None or close is None or high is None or low is None:
                continue
            if high < max(open_, close) or low > min(open_, close):
                continue
            volume = safe_float(parts[6])
            start_epoch = _normalized_bar_start(int(end_epoch), source_seconds)
            rows_by_epoch.setdefault(
                start_epoch,
                (start_epoch, open_, high, low, close, volume if volume is not None and volume >= 0 else 0.0),
            )
            oldest_end = int(end_epoch) if oldest_end is None else min(oldest_end, int(end_epoch))

        if len(rows_by_epoch) >= target_rows:
            break
        if len(rows_by_epoch) == previous_count or oldest_end is None:
            break
        if not record.get("hasMore"):
            break
        timestamp = oldest_end

    rows = [rows_by_epoch[epoch] for epoch in sorted(rows_by_epoch)]
    if not rows:
        raise WebullProviderError("no webull intraday data")
    return rows, real_pre_close


def patch_live_bar(rows: list[Bar], live: LiveQuote, seconds: int) -> list[Bar]:
    """Fold a live price into the forming bucket (or append a new one)."""
    bucket = _live_bucket_epoch(live.pub_ms // 1000, seconds)
    epoch, open_, high, low, _close, volume = rows[-1]
    if bucket > epoch:
        rows.append((bucket, live.price, live.price, live.price, live.price, 0.0))
    elif bucket == epoch:
        rows[-1] = (
            epoch,
            open_,
            max(high, live.price),
            min(low, live.price),
            live.price,
            volume,
        )
    return rows


# ---------------------------------------------------------------------------
# MQTT tick stream (wss://wspush.webullfintech.com/mqtt)
# ---------------------------------------------------------------------------


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7


def _decode_protobuf(buf: bytes, depth: int = 0) -> dict[int, list[Any]]:
    pos = 0
    fields: dict[int, list[Any]] = {}
    while pos < len(buf):
        try:
            key, pos = _decode_varint(buf, pos)
        except IndexError:
            break
        field_number, wire = key >> 3, key & 7
        try:
            if wire == 0:
                value, pos = _decode_varint(buf, pos)
            elif wire == 1:
                value = struct.unpack("<d", buf[pos : pos + 8])[0]
                pos += 8
            elif wire == 2:
                length, pos = _decode_varint(buf, pos)
                raw = buf[pos : pos + length]
                pos += length
                try:
                    value = raw.decode("utf-8")
                    if any(ord(char) < 32 for char in value):
                        raise UnicodeDecodeError("ctl", raw, 0, 1, "control chars")
                except UnicodeDecodeError:
                    sub = _decode_protobuf(raw, depth + 1) if depth < 3 and length > 4 else {}
                    value = sub or None
            elif wire == 5:
                value = struct.unpack("<f", buf[pos : pos + 4])[0]
                pos += 4
            else:
                break
        except Exception:
            break
        if value is not None:
            fields.setdefault(field_number, []).append(value)
    return fields


def decode_quote_payload(payload: bytes) -> tuple[float, int, str] | None:
    """Type-102 protobuf -> (price, pub_ms, session). None when undecodable."""
    fields = _decode_protobuf(payload)
    header = (fields.get(1) or [{}])[0]
    body = (fields.get(2) or [{}])[0]
    if not isinstance(header, dict) or not isinstance(body, dict):
        return None
    pub_ms = (header.get(5) or header.get(8) or [None])[0]
    session = str((header.get(4) or [""])[0])
    extended_price = safe_float((body.get(4) or [None])[0])
    regular_price = safe_float((body.get(1) or [None])[0])
    price = (
        regular_price
        if session == "T" and regular_price is not None
        else extended_price if extended_price is not None else regular_price
    )
    if price is None or not isinstance(pub_ms, int):
        return None
    return price, pub_ms, session


class WebullStreamer:
    """Background MQTT quote stream. Anonymous: random credentials, random did.

    paho runs its own network thread; a small lock protects quote and
    subscription state shared with the asyncio side.
    """

    def __init__(self) -> None:
        self._client: mqtt.Client | None = None
        self._did = uuid.uuid4().hex
        self._subscriptions: dict[int, None] = {}  # insertion order = LRU order
        self._latest: dict[int, LiveQuote] = {}
        self._lock = threading.Lock()
        self.connected = False

    def start(self) -> None:
        if self._client is not None:
            return
        client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=self._did,
            transport="websockets",
        )
        client.ws_set_options(path=MQTT_PATH)
        client.tls_set()
        client.username_pw_set(str(random.random()), str(random.random()))
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.on_connect_fail = self._on_connect_fail
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        # connect_async + loop_start never blocks the event loop, and paho's
        # thread keeps retrying (with the backoff above) until the first
        # connection succeeds instead of giving up for the process lifetime.
        client.connect_async(MQTT_HOST, 443, keepalive=25)
        client.loop_start()
        self._client = client
        LOGGER.info("webull streamer started")

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.disconnect()
            client.loop_stop()
        self.connected = False

    def subscribe(self, ticker_id: int) -> None:
        evicted: list[int] = []
        with self._lock:
            if ticker_id in self._subscriptions:
                self._subscriptions.pop(ticker_id)
                self._subscriptions[ticker_id] = None
                return
            self._subscriptions[ticker_id] = None
            while len(self._subscriptions) > MAX_STREAM_SUBSCRIPTIONS:
                oldest = next(iter(self._subscriptions))
                self._subscriptions.pop(oldest)
                self._latest.pop(oldest, None)
                evicted.append(oldest)
        client = self._client
        if client is not None and self.connected:
            for evicted_id in evicted:
                client.unsubscribe(_subscription_topic(evicted_id))
            client.subscribe(_subscription_topic(ticker_id))

    def latest(self, ticker_id: int) -> LiveQuote | None:
        with self._lock:
            quote = self._latest.get(ticker_id)
            if quote is None:
                return None
            if time.time() * 1000 - quote.pub_ms > STREAM_STALE_MS:
                del self._latest[ticker_id]
                return None
            return quote

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, rc: Any, _properties: Any = None) -> None:
        if rc.is_failure:
            self.connected = False
            LOGGER.warning("webull streamer connection rejected rc=%s", rc)
            return
        self.connected = True
        hello = {
            "header": {
                "did": self._did,
                "hl": "en",
                "os": "web",
                "osv": "Mozilla/5.0",
                "app": "global",
                "ver": "1.0.0",
            }
        }
        client.subscribe(json.dumps(hello))
        with self._lock:
            pending = sorted(self._subscriptions)
        for ticker_id in pending:
            client.subscribe(_subscription_topic(ticker_id))
        LOGGER.info("webull streamer connected rc=%s subs=%d", rc, len(pending))

    def _on_connect_fail(self, _client: mqtt.Client, _userdata: Any) -> None:
        LOGGER.warning("webull streamer connect failed; retrying")

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, rc: Any, _properties: Any = None) -> None:
        self.connected = False
        if rc.is_failure:
            LOGGER.info("webull streamer disconnected rc=%s", rc)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: Any) -> None:
        try:
            topic = json.loads(msg.topic)
        except (ValueError, TypeError):
            return
        if not isinstance(topic, dict):
            return
        ticker_id = topic.get("tickerId")
        if topic.get("type") != 102 or ticker_id is None:
            return
        decoded = decode_quote_payload(msg.payload)
        if decoded is None:
            return
        price, pub_ms, session = decoded
        ticker_id = int(ticker_id)
        with self._lock:
            if ticker_id in self._subscriptions:
                self._latest[ticker_id] = LiveQuote(price, pub_ms, session)


def _subscription_topic(ticker_id: int) -> str:
    return json.dumps({"tickerIds": [ticker_id], "type": "102", "flag": "1,50"})


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------


async def _optional_snapshot(
    session: aiohttp.ClientSession, ticker_id: int
) -> tuple[float, float | None, int | None, str] | None:
    """The snapshot only refines the forming bar; history alone still charts."""
    try:
        return snapshot_quote(await fetch_realtime_quote(session, ticker_id))
    except PROVIDER_ERRORS:
        return None


async def fetch_webull_chart_data(
    session: aiohttp.ClientSession,
    request: ChartRequest,
    streamer: WebullStreamer | None = None,
) -> ChartData:
    """Real-time stock intraday candles from Webull's anonymous gateways.

    Native interval bars (extended hours included), with 2m/3m aggregated
    from 1m, and the forming bar patched from the MQTT tick stream when live
    or from the real-time REST snapshot.
    """
    resolution = await resolve_ticker(session, request.ticker)
    if resolution is None and "-" in request.ticker:
        resolution = await resolve_ticker(session, request.ticker.replace("-", "."))
    if resolution is None:
        raise NoChartData(f"No chart data found for `{request.ticker}`.")
    if streamer is not None:
        # Subscribe before the REST work so a push can land while it runs.
        streamer.subscribe(resolution.ticker_id)

    native_seconds = TIMEFRAMES[native_timeframe(request.timeframe, WEBULL_INTERVALS)].seconds
    async with background(_optional_snapshot(session, resolution.ticker_id)) as snapshot_task:
        history_rows, history_pre_close = await fetch_intraday_bars(
            session, resolution.ticker_id, request.timeframe
        )
        snapshot = await snapshot_task
    last, previous, last_time, session_flag = snapshot or (None, None, None, "")
    if previous is None:
        previous = history_pre_close
    live = streamer.latest(resolution.ticker_id) if streamer is not None else None
    if live is not None and (last_time is None or live.pub_ms // 1000 >= last_time):
        last = live.price
        last_time = live.pub_ms // 1000
        session_flag = live.session or session_flag

    rows = list(history_rows)
    if last is not None:
        live_quote = LiveQuote(last, (last_time or int(time.time())) * 1000, session_flag)
        rows = patch_live_bar(rows, live_quote, native_seconds)
    if len(rows) < 2:
        raise NoChartData(f"Too little chart data found for `{request.ticker}`.")

    data = ChartData(
        ticker=request.ticker,
        name=resolution.name,
        rows=tuple(ChartRow(*row) for row in rows),
        last_close=last if last is not None else rows[-1][4],
        last_time=last_time if last_time is not None else rows[-1][0],
        previous_close=previous,
        market_label="Webull real-time",
        source_interval_seconds=native_seconds,
        preserve_last_bar=True,
    )
    return aggregate_chart_data(data, request)
