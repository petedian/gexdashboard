import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Greeks, Summary, Quote
from futures_gex_engine import FuturesGEXCalculator
from gex_database import init_db, save_snapshot, count_snapshots

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

PRODUCT = "/ES"
SNAPSHOT_INTERVAL = 60      # seconds between saved snapshots
COLLECT_SECONDS = 20        # how long to gather stream data each cycle

async def one_cycle():
    """Pull fresh data, compute levels, save one snapshot. Returns a status string."""
    chain = await get_future_option_chain(session, PRODUCT)
    nearest = sorted(chain.keys())[0]
    options = chain[nearest]

    underlying_future_symbol = options[0].underlying_symbol
    fut = await Future.get(session, underlying_future_symbol)
    fut_streamer = fut.streamer_symbol

    opt_symbols = [o.streamer_symbol for o in options]
    engine = FuturesGEXCalculator(PRODUCT)

    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Quote, [fut_streamer])
        await streamer.subscribe(Greeks, opt_symbols)
        await streamer.subscribe(Summary, opt_symbols)

        spot = 0.0
        async def q():
            nonlocal spot
            async for x in streamer.listen(Quote):
                if x.bid_price and x.ask_price:
                    spot = (float(x.bid_price) + float(x.ask_price)) / 2
                    engine.update_spot_price(spot)
        async def g():
            async for x in streamer.listen(Greeks):
                engine.update_gamma(x.event_symbol, x.gamma)
        async def s():
            async for x in streamer.listen(Summary):
                engine.update_open_interest(x.event_symbol, x.open_interest)

        try:
            async with asyncio.timeout(COLLECT_SECONDS):
                await asyncio.gather(q(), g(), s())
        except asyncio.TimeoutError:
            pass

    levels = engine.get_levels()
    strike_rows = engine.get_gex_by_strike()
    sid = save_snapshot(PRODUCT, nearest, spot, levels, strike_rows)

    from datetime import datetime
    stamp = datetime.now().strftime("%H:%M:%S")
    return (f"[{stamp}] saved #{sid}  spot={spot:.2f}  "
            f"call_wall={levels['call_wall']}  put_wall={levels['put_wall']}  "
            f"strikes={levels['num_strikes']}")

async def main():
    init_db()
    print(f"Collector started for {PRODUCT}. Saving every {SNAPSHOT_INTERVAL}s.")
    print(f"Snapshots already in DB: {count_snapshots()}")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            status = await one_cycle()
            print(status)
        except Exception as e:
            from datetime import datetime
            stamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{stamp}] cycle error (will retry next interval): {e}")
        await asyncio.sleep(SNAPSHOT_INTERVAL)

asyncio.run(main())
