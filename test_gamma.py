import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Greeks

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    print("Fetching /ES chain...")
    chain = await get_future_option_chain(session, "/ES")
    nearest = sorted(chain.keys())[0]
    options = chain[nearest]

    # take 10 contracts to test with
    sample = options[:10]
    symbols = [opt.streamer_symbol for opt in sample]
    print(f"Testing gamma stream on {len(symbols)} contracts from {nearest}")
    print("Streaming symbols:", symbols)

    print("\nConnecting to live data stream...")
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Greeks, symbols)
        print("Subscribed. Waiting for gamma values (up to 15 seconds)...\n")

        received = 0
        try:
            async with asyncio.timeout(15):
                async for greek in streamer.listen(Greeks):
                    print(f"  {greek.event_symbol}: gamma={greek.gamma}")
                    received += 1
                    if received >= len(symbols):
                        break
        except asyncio.TimeoutError:
            pass

        print(f"\nDone. Received gamma for {received} contracts.")
        if received == 0:
            print("(0 could mean market is quiet right now — not necessarily an error.)")

asyncio.run(main())
