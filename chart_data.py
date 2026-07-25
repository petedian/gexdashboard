"""Candle fetching for the Part 3 chart module (8H/Daily + 1H panels).
Confirmed via live test that dxfeed's subscribe_candle() accepts "8h" and
"1d" directly -- no manual bar aggregation needed. Futures need front-month
resolution first (a continuous "/MES" doesn't stream anything by itself);
equities/gauges use their ticker as-is.
"""
import os
import json
import time
import asyncio
import threading
import concurrent.futures
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Candle
from tastytrade.instruments import Future

try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except ImportError:
    add_script_run_ctx = get_script_run_ctx = None

CT = ZoneInfo("America/Chicago")


def to_ct_naive(dt):
    """Converts a UTC-aware datetime to Chicago wall-clock time, then strips
    tzinfo. Plotly serializes naive datetimes as-is with no timezone
    reinterpretation, which is what guarantees the chart actually displays
    CT rather than leaving it to however the browser/Plotly might handle an
    embedded UTC offset."""
    return dt.astimezone(CT).replace(tzinfo=None)


HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "chart_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def is_futures_symbol(symbol):
    return symbol.startswith("/")


def cache_path(symbol, interval):
    safe = symbol.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{interval}_sr.json")


def load_disk_cache(symbol, interval):
    path = cache_path(symbol, interval)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        for c in data["candles"]:
            c["time"] = datetime.fromisoformat(c["time"])
        return data
    except Exception:
        return None


def save_disk_cache(symbol, interval, candles):
    path = cache_path(symbol, interval)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "candles": [{**c, "time": c["time"].isoformat()} for c in candles],
    }
    with open(path, "w") as f:
        json.dump(payload, f)


async def run_listeners_until_idle(listener_coros, idle_seconds, max_seconds):
    last_event = [time.monotonic()]
    start = time.monotonic()

    async def watchdog():
        while True:
            await asyncio.sleep(0.25)
            now = time.monotonic()
            if now - last_event[0] >= idle_seconds or now - start >= max_seconds:
                return

    tasks = [asyncio.create_task(c(last_event)) for c in listener_coros]
    watchdog_task = asyncio.create_task(watchdog())
    await watchdog_task
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def run_async_isolated(coro):
    """Runs a coroutine in its own thread/event loop (Streamlit's script
    thread can't host a second asyncio.run()), propagating the Streamlit
    script-run context first so any st.* call inside coro still works."""
    ctx = get_script_run_ctx() if get_script_run_ctx else None

    def _run():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run)
        return future.result()


async def resolve_futures_trading_symbol(session, symbol):
    root = symbol.lstrip("/")
    futs = await Future.get(session, product_codes=[root])
    if not futs:
        return None
    active = [f for f in futs if getattr(f, "active_month", False)]
    chosen = active[0] if active else sorted(futs, key=lambda f: f.expiration_date)[0]
    return chosen.streamer_symbol


async def fetch_candles(session, trading_symbol, interval, days):
    by_time = {}
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe_candle(
            [trading_symbol], interval=interval,
            start_time=datetime.now(timezone.utc) - timedelta(days=days),
        )

        async def listen(last_event):
            async for c in streamer.listen(Candle):
                last_event[0] = time.monotonic()
                if c.open is None or (c.open == 0 and c.high == 0 and c.low == 0 and c.close == 0):
                    continue
                by_time[c.time] = {
                    "time": datetime.fromtimestamp(c.time / 1000, tz=timezone.utc),
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": float(c.volume) if c.volume else 0.0,
                    # aggressor-side volume split -- ask_volume = traded at the
                    # ask (buyer-initiated), bid_volume = traded at the bid
                    # (seller-initiated). Confirmed real (bid+ask == volume),
                    # not derived/approximated.
                    "buy_volume": float(c.ask_volume) if c.ask_volume else 0.0,
                    "sell_volume": float(c.bid_volume) if c.bid_volume else 0.0,
                }

        await run_listeners_until_idle([listen], idle_seconds=1.5, max_seconds=15)
    return [by_time[t] for t in sorted(by_time.keys())]


async def load_symbol_candles(symbol, interval, days):
    load_dotenv(os.path.join(HERE, ".env"))
    session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))
    trading_symbol = symbol
    if is_futures_symbol(symbol):
        resolved = await resolve_futures_trading_symbol(session, symbol)
        if resolved:
            trading_symbol = resolved
    return await fetch_candles(session, trading_symbol, interval, days)


def get_candles_cached(symbol, interval, days, ttl_seconds):
    """Disk-cached, TTL'd, never raises -- falls back to last known-good."""
    disk = load_disk_cache(symbol, interval)
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        if age < ttl_seconds:
            return disk["candles"], age, None
    try:
        candles = run_async_isolated(load_symbol_candles(symbol, interval, days))
    except Exception as e:
        if disk:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
            return disk["candles"], age, str(e)
        return [], None, str(e)
    if candles:
        save_disk_cache(symbol, interval, candles)
        return candles, 0, None
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        return disk["candles"], age, "empty fetch, showing cache"
    return [], None, "no data"
