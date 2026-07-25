"""
52-week-low screener for the liquid universe.

Pulls the Tastytrade "High Options Volume" public watchlist, filters to the
most liquid names (liquidity_rating >= 4), then pulls 365 days of daily
candles for each and ranks by how close the last close is to its 52-week low.

This is a proximity-to-52wk-low screen, not TradingView's Pivot Points Standard
indicator specifically -- same idea (find liquid names basing near their lows,
like the ETHA chart example), not an identical calculation.

Usage: python lows_screener.py
"""
import os
import time
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Candle
from tastytrade.watchlists import PublicWatchlist
from tastytrade.metrics import get_market_metrics

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

WATCHLIST_NAME = "High Options Volume"
MIN_LIQUIDITY_RATING = 4
LOOKBACK_DAYS = 365
CHUNK_SIZE = 15        # candle subscriptions have a much stricter size limit than
                       # quotes/greeks -- small chunks with fresh connections avoid
                       # both the per-call AND cumulative-per-session limits
CHUNK_PAUSE = 1.0
IDLE_SECONDS = 3.0     # stop a chunk once no new candle arrives for this long
MAX_CHUNK_SECONDS = 30
NEAR_LOW_PCT = 10.0    # highlight threshold: % above 52wk low


def base_symbol(event_symbol):
    # candle event symbols come back as "AAPL{=d,tho=true}", not plain "AAPL"
    return event_symbol.split("{")[0]


async def build_universe():
    wl = await PublicWatchlist.get(session, WATCHLIST_NAME)
    symbols = [e["symbol"] for e in wl.watchlist_entries if e.get("instrument-type") == "Equity"]
    metrics = await get_market_metrics(session, symbols)
    return [m.symbol for m in metrics if m.liquidity_rating is not None and m.liquidity_rating >= MIN_LIQUIDITY_RATING]


async def fetch_chunk(symbols):
    data = {s: {"low": None, "high": None, "last_close": None, "last_time": None} for s in symbols}
    last_event = [time.monotonic()]
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe_candle(
            symbols, interval="1d", start_time=datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        )

        async def listen():
            async for c in streamer.listen(Candle):
                last_event[0] = time.monotonic()
                sym = base_symbol(c.event_symbol)
                if sym not in data or c.close is None or c.close == 0:
                    continue
                close = float(c.close)
                low = float(c.low) if c.low else close
                high = float(c.high) if c.high else close
                d = data[sym]
                d["low"] = low if d["low"] is None else min(d["low"], low)
                d["high"] = high if d["high"] is None else max(d["high"], high)
                if d["last_time"] is None or c.time > d["last_time"]:
                    d["last_time"] = c.time
                    d["last_close"] = close

        task = asyncio.create_task(listen())
        start = time.monotonic()
        while time.monotonic() - last_event[0] < IDLE_SECONDS and time.monotonic() - start < MAX_CHUNK_SECONDS:
            await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return data


async def main():
    print(f"Building universe from '{WATCHLIST_NAME}' (liquidity_rating >= {MIN_LIQUIDITY_RATING})...")
    symbols = await build_universe()
    print(f"{len(symbols)} liquid symbols. Pulling {LOOKBACK_DAYS}d of daily candles in chunks of {CHUNK_SIZE}...\n")

    all_data = {}
    for i in range(0, len(symbols), CHUNK_SIZE):
        chunk = symbols[i:i + CHUNK_SIZE]
        print(f"  chunk {i // CHUNK_SIZE + 1}/{-(-len(symbols) // CHUNK_SIZE)}: {chunk}")
        d = await fetch_chunk(chunk)
        all_data.update(d)
        await asyncio.sleep(CHUNK_PAUSE)

    results = []
    for s, d in all_data.items():
        if d["last_close"] and d["low"]:
            pct_above_low = (d["last_close"] - d["low"]) / d["low"] * 100
            results.append((s, d["last_close"], d["low"], d["high"], pct_above_low))

    results.sort(key=lambda r: r[4])
    print(f"\nGot data for {len(results)}/{len(symbols)} symbols\n")
    print(f"{'SYM':6s} {'Last':>10s} {'52wLow':>10s} {'52wHigh':>10s} {'%AboveLow':>10s}")
    for r in results:
        flag = "  <== NEAR LOW" if r[4] <= NEAR_LOW_PCT else ""
        print(f"{r[0]:6s} {r[1]:>10.2f} {r[2]:>10.2f} {r[3]:>10.2f} {r[4]:>9.1f}%{flag}")


if __name__ == "__main__":
    asyncio.run(main())
