"""
MES 0DTE Gamma Pipeline
------------------------
Pulls today's (0DTE) /MES options chain, streams live Greeks/quotes,
computes gamma levels using the existing FuturesGEXCalculator engine,
flags each strike's proximity to gamma extremes (confluence signal),
and logs snapshots to SQLite.
"""

import os
import asyncio
import sqlite3
import datetime
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Greeks, Summary, Quote
from futures_gex_engine import FuturesGEXCalculator

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

PRODUCT = "/MES"
DB_PATH = "mes_0dte_history.db"
CONFLUENCE_BUFFER = 5.0
COLLECT_SECONDS = 20


def to_float(val):
    return float(val) if val is not None else None


def to_int(val):
    return int(val) if val is not None else None


def init_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mes_0dte_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            expiration TEXT,
            spot_price REAL,
            strike REAL,
            option_type TEXT,
            delta REAL,
            gamma REAL,
            open_interest INTEGER,
            call_wall REAL,
            put_wall REAL,
            gamma_flip REAL,
            confluence_signal TEXT
        )
    """)
    conn.commit()
    return conn


def classify_confluence(strike, gamma_flip, call_wall, put_wall, buffer_points=CONFLUENCE_BUFFER):
    if call_wall is not None and abs(strike - call_wall) <= buffer_points:
        return "near_call_wall"
    if put_wall is not None and abs(strike - put_wall) <= buffer_points:
        return "near_put_wall"
    if gamma_flip is not None and abs(strike - gamma_flip) <= buffer_points:
        return "near_flip"
    return None


async def main():
    print(f"Building {PRODUCT} 0DTE gamma levels...\n")
    conn = init_db()

    chain = await get_future_option_chain(session, PRODUCT)
    today = datetime.date.today()

    expirations = sorted(chain.keys())
    zero_dte_expiration = next((e for e in expirations if e == today), None)

    if zero_dte_expiration is None:
        print(f"No 0DTE expiration found for today ({today}). "
              f"Nearest available: {expirations[0]}. Using that instead.")
        target_expiration = expirations[0]
    else:
        target_expiration = zero_dte_expiration
        print(f"Found 0DTE expiration: {target_expiration}")

    options = chain[target_expiration]
    print(f"Expiration {target_expiration}: {len(options)} contracts")

    underlying_future_symbol = options[0].underlying_symbol
    fut = await Future.get(session, underlying_future_symbol)
    fut_streamer = fut.streamer_symbol
    print(f"Future streamer symbol: {fut_streamer}")

    opt_symbols = [o.streamer_symbol for o in options]
    symbol_map = {o.streamer_symbol: o for o in options}

    engine = FuturesGEXCalculator(PRODUCT)
    delta_by_symbol = {}
    oi_by_symbol = {}
    gamma_by_symbol = {}

    print(f"\nConnecting to live stream (collecting ~{COLLECT_SECONDS}s of data)...")
    spot = 0.0

    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Quote, [fut_streamer])
        await streamer.subscribe(Greeks, opt_symbols)
        await streamer.subscribe(Summary, opt_symbols)

        async def collect_quotes():
            nonlocal spot
            async for q in streamer.listen(Quote):
                if q.bid_price and q.ask_price:
                    spot = (float(q.bid_price) + float(q.ask_price)) / 2
                    engine.update_spot_price(spot)

        async def collect_greeks():
            async for g in streamer.listen(Greeks):
                engine.update_gamma(g.event_symbol, g.gamma)
                gamma_by_symbol[g.event_symbol] = g.gamma
                if hasattr(g, "delta"):
                    delta_by_symbol[g.event_symbol] = g.delta

        async def collect_summary():
            async for s in streamer.listen(Summary):
                engine.update_open_interest(s.event_symbol, s.open_interest)
                oi_by_symbol[s.event_symbol] = s.open_interest

        try:
            async with asyncio.timeout(COLLECT_SECONDS):
                await asyncio.gather(collect_quotes(), collect_greeks(), collect_summary())
        except asyncio.TimeoutError:
            pass

    levels = engine.get_levels()
    print(f"\nSpot: {spot:.2f} | Call Wall: {levels['call_wall']} | "
          f"Put Wall: {levels['put_wall']} | Gamma Flip: {levels['gamma_flip']}")

    timestamp = datetime.datetime.now().isoformat()
    rows_logged = 0

    for streamer_symbol, opt in symbol_map.items():
        strike = float(opt.strike_price) if hasattr(opt, "strike_price") else None
        if strike is None:
            continue
        option_type = "call" if getattr(opt, "option_type", "").upper().startswith("C") else "put"
        delta = to_float(delta_by_symbol.get(streamer_symbol))
        gamma = to_float(gamma_by_symbol.get(streamer_symbol))
        oi = to_int(oi_by_symbol.get(streamer_symbol))

        confluence = classify_confluence(
            strike, levels["gamma_flip"], levels["call_wall"], levels["put_wall"]
        )

        conn.execute("""
            INSERT INTO mes_0dte_snapshots
            (timestamp, expiration, spot_price, strike, option_type, delta, gamma,
             open_interest, call_wall, put_wall, gamma_flip, confluence_signal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, str(target_expiration), to_float(spot), strike, option_type, delta, gamma,
              oi, to_float(levels["call_wall"]), to_float(levels["put_wall"]),
              to_float(levels["gamma_flip"]), confluence))
        rows_logged += 1

    conn.commit()
    conn.close()
    print(f"\nLogged {rows_logged} strike snapshots to {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
