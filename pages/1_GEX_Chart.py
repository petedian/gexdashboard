"""Chart page - candlesticks with GEX levels (call wall / put wall / gamma flip)
computed live for whatever ticker you type, no fixed watchlist. Pulls every
expiration the chain returns.

Robustness:
- One fresh Session + one event loop per load (a cached Session reused across
  separate asyncio.run() calls breaks after the first ticker -- its internal
  async HTTP client binds to whichever event loop was running when first used).
- Subscription batches are small and throttled -- pulling *every* expiration on
  a heavily-optioned name (TSLA/NVDA can be 4,000-6,000+ contracts) trips
  dxfeed's "subscription rate too high" limit if sent too fast.
- Every network call is wrapped so a failure degrades gracefully (partial
  data, or the last known-good result) instead of crashing the whole page.
- Disk-backed cache (chart_cache/<SYMBOL>.json) survives dashboard restarts,
  unlike Streamlit's in-memory cache. A fresh successful pull overwrites it;
  a failed pull falls back to it and says how old it is.
"""
import os
import sys
import json
import time
import asyncio
import subprocess
import traceback
import concurrent.futures
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Candle, Greeks, Quote, Summary
from tastytrade.instruments import get_option_chain, get_future_option_chain, Future
from futures_gex_engine import FuturesGEXCalculator, get_multiplier
from gex_database import get_latest_snapshot
from instruments_config import GEX_PRODUCTS
import theme
import chart_data  # only for its lightweight futures front-month resolver --
                    # candle-only reloads don't need the full options chain
                    # that GEX fetching requires, so they shouldn't pay for it.

st.set_page_config(page_title="GEX Chart", layout="wide", page_icon="📈")
theme.inject()
theme.sidebar_brand("GEX Chart — GEX levels, any ticker")

BG = theme.BG
GRID = theme.GRID
TEXT = theme.TEXT

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", ".env")
CACHE_DIR = os.path.join(HERE, "..", "chart_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_TTL_SECONDS = 1200  # 20 min -- was 10, expired too fast when switching between a
                          # few tickers and coming back to check on one
LAST_SYMBOL_FILE = os.path.join(CACHE_DIR, "_last_symbol.txt")
LAST_INTERVAL_FILE = os.path.join(CACHE_DIR, "_last_chart_interval.txt")
MAX_DTE_DAYS = 60  # cap expirations by calendar days out -- fine for equities (weekly
                    # cadence, ~8 expirations in 60 days), but futures like /ES can have
                    # 30+ expirations in that window (near-daily), so also cap by count
MAX_EXPIRATIONS = 4  # matches the "nearest N expirations" convention already used
                      # elsewhere in this codebase (collector_all.py) for futures/SPX.
                      # Measured: /ES with 6 expirations = 4,382 contracts even after
                      # strike filtering -- near-daily futures expirations blow this up fast.
STRIKE_BAND = 0.05  # +/- around spot -- wall detection alone only needs ~5%.

DB_PATH = os.path.join(HERE, "..", "gex_history.db")
COLLECTOR = os.path.join(HERE, "..", "collector_all.py")


def load_gex_from_db(symbol):
    """Instant read of the latest gex_history.db snapshot for `symbol` -- the
    exact same cached row the main Dashboard just displayed. Used for the 8
    quick-access instruments so navigating here never triggers a live
    options-chain pull; only clicking 'Refresh (ignore cache)' does."""
    snap = get_latest_snapshot(symbol, db_path=DB_PATH)
    if not snap:
        return 0.0, None, None, None
    dt = datetime.fromisoformat(snap["captured_at"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    levels = {
        "call_wall": snap.get("call_wall"),
        "put_wall": snap.get("put_wall"),
        "gamma_flip": snap.get("gamma_flip"),
        "num_strikes": snap.get("num_strikes"),
        # 0DTE-only walls/flip (computed from the nearest expiration's chain
        # alone, not blended across all 4 fetched expirations) -- see
        # collector_all.py's engine_0dte. Any of these can be None: a product
        # can lack a same-day listing, or the 0DTE chain alone can have no
        # clean gamma-flip zero-crossing even when the blended one does.
        "call_wall_0dte": snap.get("call_wall_0dte"),
        "put_wall_0dte": snap.get("put_wall_0dte"),
        "gamma_flip_0dte": snap.get("gamma_flip_0dte"),
        "dte_expiration": snap.get("dte_expiration"),
    }
    return snap.get("spot_price") or 0.0, levels, age, None


def pull_fresh_snapshot(symbol, timeout=60):
    """One-off subprocess pull for a single quick-access instrument -- same
    mechanism as the Dashboard's per-card Pull/Refresh buttons (collector_all.py
    isn't a persistent daemon anymore, see gex-collector.timer)."""
    try:
        subprocess.run([sys.executable, COLLECTOR, "--pull", symbol],
                        cwd=os.path.join(HERE, ".."), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def load_last_symbol(default="IBM"):
    try:
        with open(LAST_SYMBOL_FILE) as f:
            s = f.read().strip()
            return s if s else default
    except Exception:
        return default


def save_last_symbol(symbol):
    try:
        with open(LAST_SYMBOL_FILE, "w") as f:
            f.write(symbol)
    except Exception:
        pass


def load_last_interval(default="1d"):
    try:
        with open(LAST_INTERVAL_FILE) as f:
            s = f.read().strip()
            return s if s in ("5m", "15m", "1h", "1d") else default
    except Exception:
        return default


def save_last_interval(interval):
    try:
        with open(LAST_INTERVAL_FILE, "w") as f:
            f.write(interval)
    except Exception:
        pass


def _safe_name(symbol):
    # futures symbols contain "/" (e.g. "/ES") which would otherwise be
    # interpreted as a path separator -- os.path.join even discards CACHE_DIR
    # entirely if the filename half starts with "/". Sanitize first.
    return symbol.replace("/", "_")


# GEX (options-chain-derived) and candles are cached SEPARATELY and keyed
# differently on purpose: GEX levels don't depend on which candle interval
# you're looking at, so switching timeframe shouldn't force the slow
# options-chain/Greeks refetch -- only a candle-cache-key change should.

def gex_cache_path(symbol):
    return os.path.join(CACHE_DIR, f"{_safe_name(symbol)}_gex.json")


def load_gex_disk_cache(symbol):
    path = gex_cache_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_gex_disk_cache(symbol, spot, levels):
    payload = {"saved_at": datetime.now(timezone.utc).isoformat(), "spot": spot, "levels": levels}
    with open(gex_cache_path(symbol), "w") as f:
        json.dump(payload, f)


def candle_cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"{_safe_name(symbol)}_{interval}_candles.json")


def load_candle_disk_cache(symbol, interval):
    path = candle_cache_path(symbol, interval)
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


def save_candle_disk_cache(symbol, interval, candles):
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "candles": [{**c, "time": c["time"].isoformat()} for c in candles],
    }
    with open(candle_cache_path(symbol, interval), "w") as f:
        json.dump(payload, f)


async def run_listeners_until_idle(listener_coros, idle_seconds, max_seconds):
    """Runs listener coroutines (each takes a shared last_event ref and updates
    last_event[0] = time.monotonic() whenever it processes something) until no
    listener has produced anything for `idle_seconds`, or `max_seconds` total
    has elapsed -- whichever comes first.

    Without this, every load waited a FIXED window regardless of how fast data
    actually arrived: a ticker with 8 relevant contracts paid the same ~15-60s
    tax as one with thousands, because asyncio.timeout() only cancels after
    its full duration, never early. This is what made "light" tickers feel
    just as laggy as heavy ones.
    """
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


def is_futures_symbol(symbol):
    return symbol.startswith("/")


async def _resolve_chain(session, symbol):
    """Returns (options, trading_symbol, multiplier). trading_symbol is what
    actually streams Quote/Candle data -- for futures that's the specific
    front-month contract's streamer symbol (e.g. "/ESU6:XCME"), NOT the raw
    "/ES" continuous symbol, which doesn't stream anything by itself."""
    today = datetime.now(timezone.utc).date()

    if is_futures_symbol(symbol):
        chain = await get_future_option_chain(session, symbol)
        if not chain:
            return [], None, None
        exps = ([e for e in sorted(chain.keys()) if (e - today).days <= MAX_DTE_DAYS]
                or sorted(chain.keys())[:1])[:MAX_EXPIRATIONS]
        options = []
        for e in exps:
            options.extend(chain[e])
        if not options:
            return [], None, None
        underlying = options[0].underlying_symbol
        fut = await Future.get(session, underlying)
        return options, fut.streamer_symbol, get_multiplier(symbol)
    else:
        chain = await get_option_chain(session, symbol)
        if not chain:
            return [], None, None
        exps = ([e for e in sorted(chain.keys()) if (e - today).days <= MAX_DTE_DAYS]
                or sorted(chain.keys())[:1])[:MAX_EXPIRATIONS]
        options = []
        for e in exps:
            options.extend(chain[e])
        return options, symbol, 100


async def _fetch_candles(session, trading_symbol, interval, days):
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
                }

        # historical candles arrive in a quick burst then stop -- 1s of
        # silence means the burst is done, no need to wait out a fixed clock
        await run_listeners_until_idle([listen], idle_seconds=1.0, max_seconds=12)
    return [by_time[t] for t in sorted(by_time.keys())]


async def _fetch_gex(session, symbol, options, trading_symbol, multiplier):
    if not options:
        return 0.0, None

    engine = FuturesGEXCalculator(symbol)
    engine.multiplier = multiplier

    spot = 0.0

    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Quote, [trading_symbol])

        # get an initial spot read BEFORE subscribing to the full chain, so we
        # can filter to strikes actually near the money -- pulling every strike
        # across every expiration (some futures chains run 400+ strikes each)
        # is what made this take 5 minutes for /ES.
        try:
            async with asyncio.timeout(6):
                async for x in streamer.listen(Quote):
                    if x.event_symbol == trading_symbol and x.bid_price and x.ask_price:
                        spot = (float(x.bid_price) + float(x.ask_price)) / 2
                        engine.update_spot_price(spot)
                        break
        except asyncio.TimeoutError:
            pass

        if spot > 0:
            band_lo, band_hi = spot * (1 - STRIKE_BAND), spot * (1 + STRIKE_BAND)
            filtered = [o for o in options if band_lo <= float(o.strike_price) <= band_hi]
            if filtered:
                options = filtered

        opt_symbols = [o.streamer_symbol for o in options]

        # small batches, throttled -- even after strike-band filtering, a
        # busy name across several expirations can still be 1,000+ contracts,
        # and subscribing too fast trips dxfeed's rate limit for one symbol.
        # Only Greeks (gamma) + Summary (open interest) are needed for wall/
        # gamma-flip math -- no per-leg Quote subscription, that was only for
        # the spread-idea bid/ask pricing that's been removed.
        BATCH = 50
        for i in range(0, len(opt_symbols), BATCH):
            chunk = opt_symbols[i:i + BATCH]
            await streamer.subscribe(Greeks, chunk)
            await asyncio.sleep(0.4)
            await streamer.subscribe(Summary, chunk)
            await asyncio.sleep(0.4)

        async def q(last_event):
            nonlocal spot
            async for x in streamer.listen(Quote):
                last_event[0] = time.monotonic()
                if x.event_symbol == trading_symbol and x.bid_price and x.ask_price:
                    spot = (float(x.bid_price) + float(x.ask_price)) / 2
                    engine.update_spot_price(spot)

        async def g(last_event):
            async for x in streamer.listen(Greeks):
                last_event[0] = time.monotonic()
                engine.update_gamma(x.event_symbol, x.gamma)

        async def s(last_event):
            async for x in streamer.listen(Summary):
                last_event[0] = time.monotonic()
                engine.update_open_interest(x.event_symbol, x.open_interest)

        # max_seconds is a ceiling, not a guaranteed wait -- once every
        # subscribed contract has reported once, the stream goes quiet and we
        # exit on the idle gap instead of always burning the full window
        max_secs = min(60, max(10, len(opt_symbols) // 30))
        await run_listeners_until_idle([q, g, s], idle_seconds=2.0, max_seconds=max_secs)

    return spot, engine.get_levels()


async def _load_gex_data(symbol):
    """GEX levels only -- resolves the options chain (needed for GEX, not for
    candles) and streams Greeks/Summary. This is the slow part; it must NOT
    re-run just because the user switched candle timeframe."""
    load_dotenv(ENV_PATH)
    session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

    options, trading_symbol, multiplier, resolve_err = [], symbol, 100, None
    try:
        options, resolved_symbol, multiplier = await _resolve_chain(session, symbol)
        if resolved_symbol:
            trading_symbol = resolved_symbol
    except Exception:
        resolve_err = traceback.format_exc()

    spot, levels, gex_err = 0.0, None, None
    try:
        spot, levels = await _fetch_gex(session, symbol, options, trading_symbol, multiplier)
    except Exception:
        gex_err = traceback.format_exc()

    return spot, levels, (resolve_err or gex_err)


async def _load_candle_data(symbol, interval, days):
    """Candles only -- deliberately does NOT touch the options chain. Futures
    still need front-month resolution to stream candles at all, but that's a
    single lightweight lookup (chart_data.resolve_futures_trading_symbol),
    not the full options-chain pull that only GEX needs."""
    load_dotenv(ENV_PATH)
    session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

    trading_symbol = symbol
    if chart_data.is_futures_symbol(symbol):
        try:
            resolved = await chart_data.resolve_futures_trading_symbol(session, symbol)
            if resolved:
                trading_symbol = resolved
        except Exception:
            pass  # fall through with trading_symbol = symbol; fetch below just yields no candles

    candles, candle_err = [], None
    try:
        candles = await _fetch_candles(session, trading_symbol, interval, days)
    except Exception:
        candle_err = traceback.format_exc()

    return candles, candle_err


def run_async_isolated(coro):
    """Runs a coroutine to completion in a brand-new thread with its own event
    loop. Streamlit's script-runner thread has its own asyncio event loop
    expectations; calling asyncio.run() directly on that thread conflicts with
    it and eventually throws 'RuntimeError: Event loop is closed' on later
    reruns (surfaces as the page silently hanging or failing to load). Running
    in an isolated thread avoids touching Streamlit's loop entirely."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def load_gex(symbol, force=False):
    """Disk-cached, TTL'd, never raises -- falls back to last known-good on
    any failure. Cached per SYMBOL ONLY (no interval) -- this is the slow
    options-chain/Greeks fetch, and it doesn't change just because the chart's
    candle timeframe did."""
    disk = None if force else load_gex_disk_cache(symbol)
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return disk["spot"], disk["levels"], age, None

    try:
        spot, levels, gex_err = run_async_isolated(_load_gex_data(symbol))
    except Exception:
        if disk:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
            return disk["spot"], disk["levels"], age, traceback.format_exc()
        return 0.0, None, None, traceback.format_exc()

    if levels:
        save_gex_disk_cache(symbol, spot, levels)
        return spot, levels, 0, gex_err
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        return disk["spot"], disk["levels"], age, gex_err
    return spot, levels, None, gex_err


def load_candles(symbol, interval, days=180, force=False, respect_ttl=True):
    """Disk-cached, never raises -- falls back to last known-good on any
    failure. Cached per symbol+interval, since candles genuinely differ by
    timeframe -- this is the only part a timeframe switch should re-fetch.

    respect_ttl=True (default, used for arbitrary free-text tickers) keeps
    the original behavior: a stale (>CACHE_TTL_SECONDS) cache triggers an
    automatic live refetch. respect_ttl=False (used for the 8 quick-access
    instruments) serves whatever's on disk regardless of age -- navigating to
    one of them must never trigger a live pull on its own, only an explicit
    'Refresh (ignore cache)' click (force=True) does that."""
    disk = None if force else load_candle_disk_cache(symbol, interval)
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        if not respect_ttl or age < CACHE_TTL_SECONDS:
            return disk["candles"], age, None

    try:
        candles, candle_err = run_async_isolated(_load_candle_data(symbol, interval, days))
    except Exception:
        if disk:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
            return disk["candles"], age, traceback.format_exc()
        return [], None, traceback.format_exc()

    if candles:
        save_candle_disk_cache(symbol, interval, candles)
        return candles, 0, candle_err
    if disk:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(disk["saved_at"])).total_seconds()
        return disk["candles"], age, candle_err
    return [], None, candle_err


INTERVAL_OPTIONS = ["5m", "15m", "1h", "1d"]
INTERVAL_DAYS = {"5m": 5, "15m": 10, "1h": 30, "1d": 180}  # fetch window scaled to
                                                            # bar size -- 180 days of
                                                            # 5m candles would be excessive

# 8 quick-access buttons for the tracked instruments -- load instantly from
# gex_history.db (see load_gex_from_db below) instead of a live options-chain
# pull. Purely additive: the free-text box below still reaches any ticker,
# live-fetched, exactly as before.
#
# The text_input below is programmatically settable via its "symbol_input"
# session_state key -- seed it once (not on every rerun) and never also pass
# value=, or Streamlit logs a "default value AND Session State API" warning.
if "symbol_input" not in st.session_state:
    st.session_state["symbol_input"] = load_last_symbol()

quick_cols = st.columns(len(GEX_PRODUCTS))
for i, qsym in enumerate(GEX_PRODUCTS):
    with quick_cols[i]:
        if st.button(qsym, key=f"quick_{qsym}", width="stretch",
                     type="primary" if st.session_state["symbol_input"] == qsym else "secondary"):
            st.session_state["symbol_input"] = qsym

top = st.columns([2, 1, 1])
with top[0]:
    symbol = st.text_input("Symbol", key="symbol_input", label_visibility="collapsed",
                            placeholder="Type any ticker (e.g. IBM, NVDA, SPY)...").strip().upper()
with top[1]:
    interval = st.selectbox("Candle size", INTERVAL_OPTIONS,
                             index=INTERVAL_OPTIONS.index(load_last_interval()), label_visibility="collapsed")
with top[2]:
    refresh = st.button("Refresh (ignore cache)", width="stretch")

if not symbol:
    st.stop()

is_quick = symbol in GEX_PRODUCTS

if is_quick:
    # Background poll: reruns the whole page the moment the collector writes
    # a newer snapshot for this symbol, so an open tab picks up new GEX
    # levels without the user having to click anything. No new live pull --
    # this only re-reads gex_history.db (already instant, see
    # load_gex_from_db above) and compares the timestamp it already got.
    @st.fragment(run_every=60)
    def _poll_for_new_snapshot(sym=symbol):
        snap = get_latest_snapshot(sym, db_path=DB_PATH)
        seen_key = f"_last_seen_captured_at_{sym}"
        latest_ts = snap["captured_at"] if snap else None
        if seen_key not in st.session_state:
            st.session_state[seen_key] = latest_ts
        elif st.session_state[seen_key] != latest_ts:
            st.session_state[seen_key] = latest_ts
            st.rerun()
    _poll_for_new_snapshot()

    # DB-snapshot path: same cached row the main Dashboard just displayed --
    # no options-chain/Greeks pull on plain navigation, only on Refresh click.
    if refresh:
        with st.spinner(f"Pulling fresh data for {symbol}…"):
            pull_fresh_snapshot(symbol)
            spot, levels, gex_age, gex_err = load_gex_from_db(symbol)
            candles, candle_age, candle_err = load_candles(
                symbol, interval, INTERVAL_DAYS[interval], force=True, respect_ttl=False)
    else:
        spot, levels, gex_age, gex_err = load_gex_from_db(symbol)
        if load_candle_disk_cache(symbol, interval) is None:
            with st.spinner(f"Loading {interval} candles for {symbol} (first load)…"):
                candles, candle_age, candle_err = load_candles(
                    symbol, interval, INTERVAL_DAYS[interval], force=False, respect_ttl=False)
        else:
            candles, candle_age, candle_err = load_candles(
                symbol, interval, INTERVAL_DAYS[interval], force=False, respect_ttl=False)
else:
    # Free-text arbitrary-ticker path -- unchanged from before: live options-
    # chain GEX fetch + TTL-driven candle cache, both disk-cached.
    # GEX (options chain + Greeks/OI) and candles (price history) are independent
    # fetches -- nothing about one depends on the other finishing first. Running
    # them in parallel threads means the wall-clock cost is whichever one is
    # slower, not the sum.
    with st.spinner(f"Loading {symbol} GEX levels + {interval} candles — pulling every "
                    f"expiration, this can take a bit for heavily-optioned names..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            gex_future = executor.submit(load_gex, symbol, refresh)
            candle_future = executor.submit(load_candles, symbol, interval, INTERVAL_DAYS[interval], refresh)
            spot, levels, gex_age, gex_err = gex_future.result()
            candles, candle_age, candle_err = candle_future.result()

if candles:
    save_last_symbol(symbol)
    save_last_interval(interval)

status_bits = []
if gex_age:
    status_bits.append(theme.pill("neutral", f"GEX · {gex_age/60:.0f}m old"))
elif gex_age == 0:
    status_bits.append(theme.pill("bull", "GEX fresh", pulse=True))
if candle_age:
    status_bits.append(theme.pill("neutral", f"{interval} candles · {candle_age/60:.0f}m old"))
elif candle_age == 0:
    status_bits.append(theme.pill("bull", f"{interval} candles fresh", pulse=True))
if status_bits:
    theme.statusline("".join(status_bits))

err = gex_err or candle_err
if err:
    with st.expander("A fetch error occurred (data above may be partial/cached)"):
        st.code(err)

if not candles:
    theme.empty_state(f"No candle data for {symbol}",
                      "No cached fallback available — check the ticker is valid and has market data.")
    st.stop()

if spot and levels and levels.get("call_wall"):
    c1, c2, c3, c4 = st.columns(4)
    with c1: theme.stat_tile("Spot", f"{spot:,.2f}")
    with c2: theme.stat_tile("Call Wall", f"{levels['call_wall']:,.2f}")
    with c3: theme.stat_tile("Put Wall", f"{levels['put_wall']:,.2f}")
    with c4:
        theme.stat_tile("Gamma Flip",
                        f"{levels['gamma_flip']:,.2f}" if levels.get("gamma_flip") else "—",
                        accent=True)

CT = ZoneInfo("America/Chicago")
fig = go.Figure(data=[go.Candlestick(
    x=[c["time"].astimezone(CT).replace(tzinfo=None) for c in candles],
    open=[c["open"] for c in candles], high=[c["high"] for c in candles],
    low=[c["low"] for c in candles], close=[c["close"] for c in candles],
    name=symbol,
    increasing=dict(line=dict(color=theme.BULLISH, width=1), fillcolor=theme.BULLISH),
    decreasing=dict(line=dict(color=theme.BEARISH, width=1), fillcolor=theme.BEARISH),
)])

if levels:
    # Gamma Flip is the signature key level -- solid brass, heaviest weight --
    # call/put walls stay dashed so the flip reads as the dominant line.
    for label, level, color, dash, width in [
        ("Call Wall", levels.get("call_wall"), theme.BEARISH, "dash", 1.2),
        ("Put Wall", levels.get("put_wall"), theme.BULLISH, "dash", 1.2),
        ("Gamma Flip", levels.get("gamma_flip"), theme.PRIMARY, "solid", 2.4),
    ]:
        if level:
            fig.add_hline(y=level, line_dash=dash, line_width=width, line_color=color, opacity=0.9)
            fig.add_annotation(
                x=1.0, xref="paper", y=level, yref="y",
                text=f"{label}  {level:,.2f}", showarrow=False,
                xanchor="left", align="left",
                font=dict(color=color, size=10.5, family=theme.PLOTLY_FONT["family"]),
                bgcolor=theme.BG_SECONDARY, bordercolor=color,
                borderwidth=1, borderpad=3,
            )

    # 0DTE-only walls/flip, 8 tracked instruments only -- same colors as the
    # blended lines above but dotted/thinner and labeled on the LEFT edge (the
    # blended labels sit on the right) so the two sets never overlap. The
    # blend can pull a wall away from where today's chain is actually
    # concentrated; when the dotted and solid/dashed lines diverge, that gap
    # is the signal. Not shown for free-text tickers -- no per-expiration
    # tracking exists for those (live-fetch path only ever computes the
    # blended view).
    if is_quick:
        for label, level, color in [
            ("0DTE CW", levels.get("call_wall_0dte"), theme.BEARISH),
            ("0DTE PW", levels.get("put_wall_0dte"), theme.BULLISH),
            ("0DTE Flip", levels.get("gamma_flip_0dte"), theme.PRIMARY),
        ]:
            if level:
                fig.add_hline(y=level, line_dash="dot", line_width=1.1, line_color=color, opacity=0.75)
                fig.add_annotation(
                    x=0.0, xref="paper", y=level, yref="y",
                    text=f"{label}  {level:,.2f}", showarrow=False,
                    xanchor="right", align="right",
                    font=dict(color=color, size=9, family=theme.PLOTLY_FONT["family"]),
                    bgcolor=theme.BG_SECONDARY, bordercolor=color,
                    borderwidth=1, borderpad=2,
                )

fig.update_layout(
    plot_bgcolor=BG, paper_bgcolor=BG, font=theme.PLOTLY_FONT,
    hoverlabel=theme.PLOTLY_HOVERLABEL,
    height=680, xaxis_rangeslider_visible=False,
    # r is wider than the old sans-serif label needed -- IBM Plex Mono is
    # wider per character, and labels like "Gamma Flip  752.40" were
    # clipping at the figure edge. l widens for the 8 tracked instruments'
    # 0DTE labels, which anchor to the left edge specifically so they never
    # collide with the blended labels on the right.
    margin=dict(l=100 if is_quick else 10, r=135, t=54, b=10),
    title=dict(
        text=symbol, x=0.01,
        font=dict(size=17, color=TEXT, family=theme.PLOTLY_FONT["family"]),
        subtitle=dict(text=f"{interval} candles · GEX levels overlay",
                      font=dict(size=11.5, color=theme.TEXT_MUTED)),
    ),
    # TradingView-style interaction: drag inside the chart pans; dragging on the
    # time axis (bottom) or price axis (right) rescales just that axis --
    # that per-axis behavior is native Plotly as long as fixedrange stays False.
    # Double-click anywhere resets both axes to auto-range.
    dragmode="pan",
    xaxis=dict(gridcolor=GRID, showline=False, fixedrange=False,
               tickfont=dict(size=11, color=theme.TEXT_MUTED),
               rangebreaks=[dict(bounds=["sat", "mon"])]),
    yaxis=dict(gridcolor=GRID, showline=False, side="right", fixedrange=False,
               tickfont=dict(size=11, color=theme.TEXT_MUTED)),
    showlegend=False,
    hovermode="x unified",
)
st.plotly_chart(fig, width="stretch",
                config={"displayModeBar": False, "scrollZoom": True,
                        "doubleClick": "reset+autosize"})
theme.export_png_button(fig, key=f"export_{symbol}")

if spot and levels and levels.get("call_wall"):
    st.caption(f"GEX levels computed from {levels.get('num_strikes', 0)} strikes "
               f"across the {MAX_EXPIRATIONS} nearest expirations.")
elif not levels and is_quick:
    st.caption(f"No {symbol} snapshot yet — waiting for the next scheduled sweep, "
               f"or click 'Refresh (ignore cache)' to pull it now.")
elif not levels:
    st.caption(f"No GEX levels for {symbol} yet — check it has listed options, or see the error above.")
