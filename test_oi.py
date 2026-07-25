import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    print("Fetching /ES chain...")
    chain = await get_future_option_chain(session, "/ES")
    nearest = sorted(chain.keys())[0]
    options = chain[nearest]
    sample = options[:10]
    symbols = [opt.streamer_symbol for opt in sample]
    print(f"Testing open interest on {len(symbols)} contracts from {nearest}\n")

    print("Connecting to live data stream...")
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Summary, symbols)
        print("Subscribed. Waiting for open interest (up to 15 seconds)...\n")

        received = 0
        try:
            async with asyncio.timeout(15):
                async for s in streamer.listen(Summary):
                    print(f"  {s.event_symbol}: open_interest={s.open_interest}")
                    received += 1
                    if received >= len(symbols):
                        break
        except asyncio.TimeoutError:
            pass

        print(f"\nDone. Received open interest for {received} contracts.")
        if received == 0:
            print("(0 could mean market is quiet — or OI comes from elsewhere. We'll adapt.)")

asyncio.run(main())
