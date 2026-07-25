import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Quote

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    # SPX index streamer symbol is typically ".SPX" or "SPX"; SPY is the ETF proxy
    candidates = ["SPX", ".SPX", "SPY"]
    print("Testing which SPX spot symbol streams a live quote...\n")

    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Quote, candidates)
        print(f"Subscribed to: {candidates}")
        print("Listening 15s for quotes...\n")

        seen = {}
        try:
            async with asyncio.timeout(15):
                async for q in streamer.listen(Quote):
                    bid = q.bid_price
                    ask = q.ask_price
                    mid = None
                    if bid and ask:
                        mid = (float(bid) + float(ask)) / 2
                    if q.event_symbol not in seen:
                        seen[q.event_symbol] = mid
                        print(f"  {q.event_symbol}: bid={bid} ask={ask} mid={mid}")
                    if len(seen) >= len(candidates):
                        break
        except asyncio.TimeoutError:
            pass

    print("\nResults:")
    for sym in candidates:
        print(f"  {sym}: {seen.get(sym, 'no quote')}")

asyncio.run(main())
